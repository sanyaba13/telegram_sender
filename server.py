import asyncio
import threading
from flask import Flask, request, jsonify
from telethon import TelegramClient

# Данные от Telegram API
API_ID = 22450360
API_HASH = "61bac300978d7a52ce2743969aa72332"
PHONE_NUMBER = "+966542968297"

# Создаём клиент Telethon
client = TelegramClient("session_name", API_ID, API_HASH)
loop = asyncio.new_event_loop()  # Отдельный event loop для Telethon
asyncio.set_event_loop(loop)

# Flask-сервер
app = Flask(__name__)

@app.route("/send", methods=["POST"])
def send_message():
    data = request.json
    messages = data.get("messages", [])

    for msg in messages:
        phone = msg["phone"]
        text = msg["message"]
        try:
            # Отправляем сообщение через event loop Telethon
            future = asyncio.run_coroutine_threadsafe(client.send_message(phone, text), loop)
            future.result()  # Дожидаемся выполнения
            print(f"Отправлено {phone}: {text}")
        except Exception as e:
            print(f"Ошибка при отправке {phone}: {str(e)}")

    return jsonify({"status": "ok"})

# Запускаем Flask в отдельном потоке
def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

# Основная функция
async def main():
    await client.start(PHONE_NUMBER)  # Авторизация в Telegram
    print("Бот подключён к Telegram!")
    threading.Thread(target=run_flask, daemon=True).start()  # Запускаем Flask в отдельном потоке
    await asyncio.Event().wait()  # Держим главный поток открытым

if __name__ == "__main__":
    loop.run_until_complete(main())  # Запускаем Telethon
