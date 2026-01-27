import os
import asyncio
from flask import Flask, request, jsonify
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

app = Flask(__name__)

API_ID = int(os.environ.get("API_ID", "22450360"))
API_HASH = os.environ.get("API_HASH", "61bac300978d7a52ce2743969aa72332")
TG_SESSION = os.environ.get("TG_SESSION", "")

if not TG_SESSION:
    raise RuntimeError("TG_SESSION is missing. Generate StringSession locally and set TG_SESSION env var on Render.")

client = TelegramClient(StringSession(TG_SESSION), API_ID, API_HASH)

# Стартуем отдельный event loop в фоне, чтобы Flask (sync) мог нормально дергать async
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

async def _init_client():
    await client.connect()
    if not await client.is_user_authorized():
        # Если вдруг сессия битая/неверная
        raise RuntimeError("Telethon session is not authorized. Re-generate TG_SESSION.")
    return True

_loop.run_until_complete(_init_client())


async def _send_messages(messages):
    results = []

    for msg in messages:
        phone = (msg.get("phone") or "").strip()
        text = (msg.get("message") or "").strip()

        if not phone or not text:
            results.append({"phone": phone, "status": "error", "reason": "Missing phone or message"})
            continue

        try:
            # ВАЖНО: отправка по номеру работает только если контакт доступен аккаунту
            await client.send_message(phone, text)
            results.append({"phone": phone, "status": "ok"})

        except FloodWaitError as e:
            # Telegram просит подождать
            results.append({"phone": phone, "status": "flood_wait", "retry_after": int(e.seconds)})
            await asyncio.sleep(int(e.seconds))

        except Exception as e:
            results.append({"phone": phone, "status": "error", "reason": str(e)})

    return results


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
        results = fut.result(timeout=120)

        all_ok = all(r.get("status") == "ok" for r in results) and len(results) > 0
        status = "ok" if all_ok else "partial"

        return jsonify({"status": status, "results": results}), 200

    except Exception as e:
        return jsonify({"status": "error", "reason": str(e)}), 500


@app.route("/", methods=["GET"])
def health():
    return "OK", 200
