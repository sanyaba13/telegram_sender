import asyncio
from flask import Flask, request, jsonify
from telethon import TelegramClient

# Данные Telegram API
API_ID = 22450360
API_HASH = "61bac300978d7a52ce2743969aa72332"
PHONE_NUMBER = "+966542968297"

# Создаём Telethon-клиент
client = TelegramClient("session_name", API_ID, API_HASH)

app = Flask(__name__)

@app.route("/send", methods=["POST"])
async def send_message():
    try:
        data = request.get_json(force=True)  # ✅ Принудительное получение JSON
        if not data:
            return jsonify({"error": "No JSON received"}), 400
        
        messages = data.get("messages", [])
        if not messages:
            return jsonify({"error": "No messages provided"}), 400
        
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

        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"❌ Ошибка сервера: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
