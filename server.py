import asyncio
import os
import threading
from urllib.parse import urlsplit

from flask import Flask, jsonify, request
from telethon import TelegramClient, errors, utils
from telethon.tl.types import InputMediaPhotoExternal


# Set these in Render -> Environment, using your existing values.
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
# Keep the existing authorized session file and its path.
SESSION_NAME = os.environ.get("TELEGRAM_SESSION", "session_name")

app = Flask(__name__)
send_lock = threading.Lock()


async def send_batch(messages):
    # Each request owns its client and event loop. The lock protects the session.
    client = TelegramClient(
        SESSION_NAME, API_ID, API_HASH, flood_sleep_threshold=0
    )
    results = []
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {
                "status": "error",
                "reason": "Telethon not authorized: restore the existing authorized session file.",
            }, 500

        for msg in messages:
            phone = msg.get("phone") if isinstance(msg, dict) else None
            result = {"phone": phone, "status": "error"}
            try:
                if not isinstance(msg, dict):
                    raise ValueError("Each message must be an object")
                text = msg.get("message")
                if not isinstance(phone, str) or not phone.strip():
                    raise ValueError("Missing phone")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("Missing message")

                photo_url = msg.get("photo_url")
                parse_mode = msg.get("parse_mode", "html")
                if parse_mode not in ("html", "md", "markdown", None):
                    raise ValueError("Unsupported parse_mode")

                parser = utils.sanitize_parse_mode(parse_mode)
                plain_text = parser.parse(text)[0] if parser else text
                limit = 1024 if photo_url else 4096
                if len(plain_text.encode("utf-16-le")) // 2 > limit:
                    raise ValueError(f"Message exceeds the {limit}-character limit")

                if photo_url:
                    if not isinstance(photo_url, str):
                        raise ValueError("photo_url must be an HTTP(S) URL")
                    photo_url = photo_url.strip()
                    parsed = urlsplit(photo_url)
                    if parsed.scheme not in ("http", "https") or not parsed.hostname:
                        raise ValueError("photo_url must be an HTTP(S) URL")

                    # Telegram fetches the image. The URL is not in the caption.
                    sent = await client.send_file(
                        phone.strip(),
                        InputMediaPhotoExternal(url=photo_url),
                        caption=text,
                        parse_mode=parse_mode,
                        force_document=False,
                    )
                else:
                    sent = await client.send_message(
                        phone.strip(), text,
                        parse_mode=parse_mode,
                        link_preview=False,
                    )

                if sent is None:
                    raise RuntimeError("Telegram returned no message confirmation")
                result.update(status="ok", message_id=sent.id)
                result["media_sent"] = bool(photo_url)
            except errors.FloodWaitError as exc:
                result["reason"] = f"FLOOD_WAIT_{exc.seconds}"
                result["retry_after"] = exc.seconds
                results.append(result)
                # Do not send more messages before Telegram's wait expires.
                for pending in messages[len(results):]:
                    results.append({
                        "phone": pending.get("phone") if isinstance(pending, dict) else None,
                        "status": "error",
                        "reason": f"FLOOD_WAIT_{exc.seconds}",
                        "retry_after": exc.seconds,
                    })
                break
            except Exception as exc:
                # Do not silently fall back to text when the image fails.
                result["reason"] = str(exc)
            results.append(result)

        return {"status": "partial", "results": results}, 200
    finally:
        await client.disconnect()


@app.route("/send", methods=["POST"])
def send_message():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"status": "error", "reason": "Invalid JSON"}), 400
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        return jsonify({"status": "error", "reason": "No messages provided"}), 400

    # Run a single worker/process for this session file.
    with send_lock:
        try:
            body, status = asyncio.run(send_batch(messages))
            return jsonify(body), status
        except Exception as exc:
            return jsonify({"status": "error", "reason": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
