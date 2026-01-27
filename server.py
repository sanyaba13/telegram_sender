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

client = TelegramClient(StringSession(TG_SESSION), API_ID, API_HASH)

# --- ВАЖНО: loop должен крутиться постоянно ---
_loop = asyncio.new_event_loop()

def _run_loop_forever():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()

_thread = threading.Thread(target=_run_loop_forever, daemon=True)
_thread.start()


async def _init_client():
    await client.connect()
    ok = await client.is_user_authorized()
    if not ok:
        raise RuntimeError("Telethon session is not authorized (TG_SESSION wrong/expired)")
    return True

# инициализация клиента на работающем loop
asyncio.run_coroutine_threadsafe(_init_client(), _loop).result(timeout=30)


async def _resolve_entity_by_phone(phone: str):
    phone_clean = phone.replace(" ", "")
    contact = InputPhoneContact(
        client_id=0,
        phone=phone_clean,
        first_name="Tmp",
        last_name="Contact"
    )
    result = await client(ImportContactsRequest([contact]))
    if result.users:
        return result.users[0]
    return None


async def _send_one(phone: str, text: str):
    entity = await _resolve_entity_by_phone(phone)
    if not entity:
        return {
            "phone": phone,
            "status": "error",
            "reason": "Telegram cannot resolve this phone (no TG / privacy / cannot message first)"
        }

    try:
        await client.send_message(entity, text)
        return {"phone": phone, "status": "ok"}

    except FloodWaitError as e:
        return {"phone": phone, "status": "flood_wait", "retry_after": int(e.seconds)}

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

        res = await _send_one(phone, text)
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

        # Держим запрос разумно (чтобы GAS мог ретраить)
        results = fut.result(timeout=40)

        all_ok = len(results) > 0 and all(r.get("status") == "ok" for r in results)
        status = "ok" if all_ok else "partial"

        return jsonify({"status": status, "results": results}), 200

    except asyncio.TimeoutError:
        return jsonify({"status": "error", "reason": "timeout"}), 504

    except Exception as e:
        return jsonify({"status": "error", "reason": str(e)}), 500
