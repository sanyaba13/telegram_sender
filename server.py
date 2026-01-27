import os
import asyncio
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
    raise RuntimeError("TG_SESSION is missing in env variables")

client = TelegramClient(StringSession(TG_SESSION), API_ID, API_HASH)

# отдельный loop в фоне
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)


async def _init():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telethon session not authorized (TG_SESSION wrong/expired)")
    return True


_loop.run_until_complete(_init())


async def _resolve_entity_by_phone(phone: str):
    """
    Пытаемся заставить Telegram узнать номер:
    1) импортируем контакт
    2) если импорт вернул users -> берем первого
    """
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
    # 1) пробуем entity через импорт контакта
    entity = await _resolve_entity_by_phone(phone)
    if not entity:
        return {"phone": phone, "status": "error", "reason": "Telegram cannot resolve this phone (user may not exist / privacy / not in Telegram)"}

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

        # ограничим текст, чтобы не словить неожиданные лимиты
        if len(text) > 3500:
            text = text[:3500]

        res = await _send_one(phone, text)
        results.append(res)

        # если flood_wait — реально подождём, чтобы следующая отправка не убилась
        if res.get("status") == "flood_wait":
            await asyncio.sleep(int(res.get("retry_after", 60)))

        # маленькая пауза между сообщениями
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

        # ВАЖНО: не держим воркер долго. максимум 25 секунд на запрос.
        fut = asyncio.run_coroutine_threadsafe(_send_messages(messages), _loop)
        results = fut.result(timeout=25)

        all_ok = len(results) > 0 and all(r.get("status") == "ok" for r in results)
        status = "ok" if all_ok else "partial"

        return jsonify({"status": status, "results": results}), 200

    except asyncio.TimeoutError:
        # чтобы gunicorn не убивал воркер — вернём норм ответ и GAS решит retry
        return jsonify({"status": "error", "reason": "timeout"}), 504

    except Exception as e:
        return jsonify({"status": "error", "reason": str(e)}), 500
