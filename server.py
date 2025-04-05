import asyncio
from flask import Flask, request, jsonify
from telethon import TelegramClient

API_ID = 22450360
API_HASH = "61bac300978d7a52ce2743969aa72332"
PHONE_NUMBER = "+966542968297"

client = TelegramClient("session_name", API_ID, API_HASH)
loop = asyncio.get_event_loop()
app = Flask(__name__)

@app.route("/send", methods=["POST"])
def send_message():
    try:
        print(f"📥 Входящий запрос: {request.data}")

        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"status": "error", "reason": "Invalid JSON"}), 400

        messages = data.get("messages", [])
        if not messages:
            return jsonify({"status": "error", "reason": "No messages provided"}), 400

        if not client.is_connected():
            loop.run_until_complete(client.connect())

        if not client.is_user_authorized():
            return jsonify({"status": "error", "reason": "Telethon not authorized"}), 500

        results = []

        async def send():
            async with client:
                for msg in messages:
                    phone = msg.get("phone")
                    text = msg.get("message")
                    if not phone or not text:
                        results.append({
                            "phone": phone,
                            "status": "error",
                            "reason": "Missing phone or message"
                        })
                        continue

                    try:
                        await client.send_message(phone, text)
                        print(f"✅ Отправлено {phone}")
                        results.append({
                            "phone": phone,
                            "status": "ok"
                        })
                    except Exception as e:
                        print(f"❌ Ошибка при отправке {phone}: {e}")
                        results.append({
                            "phone": phone,
                            "status": "error",
                            "reason": str(e)
                        })

        loop.run_until_complete(send())

        return jsonify({"status": "partial", "results": results})

    except Exception as e:
        print(f"❌ Ошибка сервера: {e}")
        return jsonify({"status": "error", "reason": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
