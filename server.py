import asyncio
from flask import Flask, request, jsonify
from telethon import TelegramClient

API_ID = 22450360
API_HASH = "61bac300978d7a52ce2743969aa72332"
PHONE_NUMBER = "+966542968297"

client = TelegramClient("session_name", API_ID, API_HASH)

# Глобальный event loop
loop = asyncio.get_event_loop()

app = Flask(__name__)

@app.route("/send", methods=["POST"])
def send_message():
    try:
        print(f"📥 Входящий запрос: {request.data}")

        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        messages = data.get("messages", [])
        if not messages:
            return jsonify({"error": "No messages provided"}), 400

        # Подключаем клиента, если он отключён
        if not client.is_connected():
            loop.run_until_complete(client.connect())

        if not client.is_user_authorized():
            return jsonify({"error": "Telethon не авторизован"}), 500

        async def send():
            async with client:
                for msg in messages:
                    phone = msg.get("phone")
                    text = msg.get("message")
                    if not phone or not text:
                        continue

                    try:
                        await client.send_message(phone, text)
                        print(f"✅ Отправлено {phone}: {text}")
                    except Exception as e:
                        print(f"❌ Ошибка при отправке {phone}: {e}")

        loop.run_until_complete(send())

        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"❌ Ошибка сервера: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
