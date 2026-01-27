import os
import asyncio
import threading
from flask import Flask, request, jsonify

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact

app = Flask(__name__)

API_ID = int(os.environ.get("API_ID", "22450360"))
API_HASH = os.environ.get("API_HASH", "61bac300978d7a52ce2743969aa72332")
TG_SESSION = os.environ.get("TG_SESSION", "")

if not TG_SESSION:
    raise RuntimeError("TG_SESSION is missing in env vars")

# --- loop + client создаём в одном потоке ---
_loop = asyncio.new_event_loop()
_client = None

_ready = threading.Event()
_init_error = {"err": None}


async def _async_init_client():
    global _client
    _client = TelegramClient(StringSession(TG_SESSION), API_ID, API_HASH)
    await _client.connect()

    ok = await _client.is_user_authorized()
    if not ok:
        raise RuntimeError("Telethon session is not authorized (TG_SESSION wrong/expired)")

    return True


def _loop_thread():
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_async_init_client())
        print("✅ Telethon client initialized")
        _ready.set()
        _loop.run_forever()
    except Exception as e:
        _init_error["err"] = str(e)
        print("❌ Init error:", e)
        _ready.set()


threading.Thread(target=_loop_thread, daemon=True).start()

# ждём инициализацию (при старте сервиса)
_ready.wait(timeout=30)
if _init_error["err"]:
    raise RuntimeError("Telethon init failed: " + _init_error["err"])


async def _resolve_entity_by_phone(phone: str):
    # Жёсткий таймаут, чтобы Telethon не зависал
    async def _do():
        phone_clean = phone.replace(" ", "")
        contact = InputPhoneContact(
            client_id=0,
            phone=phone_clean,
            first_name="Tmp",
            last_name="Contact"
        )
        result = await _client(ImportContactsRequest([contact]))
        if result.users:
            return result.users[0]
        return None

    return await asyncio.wait_for(_do(), timeout=12)


async def _send_one(phone: str, text: str):
    # 1) entity (таймаут)
    entity = await _resolve_entity_by_phone(phone)
    if not entity:
        return {
            "phone": phone,
            "status": "error",
            "reason": "Cannot resolve phone (user may not exist / privacy / not in Telegram)"
        }

    # 2) send (таймаут)
    async def _do_send():
        await _client.send_message(entity, text)
        return True

    try:
        await asyncio.wait_for(_do_send(), timeout=12)
        return {"phone": phone, "status": "ok"}

    except FloodWaitError as e:
        return {"phone": phone, "status": "flood_wait", "retry_after": int(e.seconds)}

    except asyncio.TimeoutError:
        return {"phone": phone, "status": "error", "reason": "telethon_send_timeout"}

    except Exception as e:
        return {"phone": phone, "status": "error", "reason": str(e)}


async def _send_messages(messages):
    results = []

    for msg in messages:
        phone = (msg.get("phone") or "").strip()
        text = (msg.get("message") or "").strip()

        if not phone or not text:
            results.append({"phone": phone, "status": "error", "reason": "Missing phone or message"})
            continue

        if len(text) > 3500:
            text = text[:3500]

        try:
            res = await _send_one(phone, text)
        except asyncio.TimeoutError:
            res = {"phone": phone, "status": "error", "reason": "telethon_stage_timeout"}
        except Exception as e:
            res = {"phone": phone, "status": "error", "reason": f"server_exception: {e}"}

        results.append(res)

        if res.get("status") == "flood_wait":
            await asyncio.sleep(int(res.get("retry_after", 60)))

        await asyncio.sleep(0.3)

    return results


@app.route("/", methods=["GET", "HEAD"])
def health():
    return "OK", 200


@app.route("/send", methods=["POST"])
def send_message():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"status": "error", "reason": "Invalid JSON"}), 400

        messages = data.get("messages", [])
        if not messages:
            return jsonify({"status": "error", "reason": "No messages provided"}), 400

        fut = asyncio.run_coroutine_threadsafe(_send_messages(messages), _loop)

        # максимум 40 секунд на HTTP (чтобы GAS мог ретраить)
        results = fut.result(timeout=40)

        all_ok = len(results) > 0 and all(r.get("status") == "ok" for r in results)
        status = "ok" if all_ok else "partial"

        return jsonify({"status": status, "results": results}), 200

    except asyncio.TimeoutError:
        return jsonify({"status": "error", "reason": "timeout"}), 504

    except Exception as e:
        return jsonify({"status": "error", "reason": str(e)}), 500
