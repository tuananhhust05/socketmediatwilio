import asyncio
import websockets
import json
import base64
import numpy as np
import wave
from flask import Flask, send_file
from threading import Thread

audio_frames = []

# --------------------
# WebSocket server
# --------------------
async def handler(websocket):
    """
    Xử lý kết nối WebSocket từ Twilio.
    Twilio sẽ kết nối đến wss://your-domain:8765/media
    """
    global audio_frames
    print("✅ Client connected on /media")

    async for message in websocket:
        try:
            data = json.loads(message)
        except Exception as e:
            print("❌ JSON parse error:", e)
            continue

        event = data.get("event")
        if event == "start":
            print("Stream started:", data.get("streamSid"))

        elif event == "media":
            # Nhận audio base64 từ Twilio
            payload = data["media"]["payload"]
            audio_chunk = base64.b64decode(payload)
            audio_frames.append(audio_chunk)

        elif event == "stop":
            print("Stream stopped")
            # Khi kết thúc stream -> lưu ra file WAV chuẩn PCM16 8kHz
            if audio_frames:
                pcm_data = b"".join(audio_frames)
                audio_frames.clear()

                # Ghi WAV chuẩn
                with wave.open("output.wav", "wb") as wf:
                    wf.setnchannels(1)       # Mono
                    wf.setsampwidth(2)       # 16-bit PCM
                    wf.setframerate(8000)    # 8kHz sample rate
                    wf.writeframes(pcm_data)
                print("💾 Saved output.wav (PCM16 8kHz)")

async def ws_main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("🚀 WebSocket server listening on ws://0.0.0.0:8765/media")
        await asyncio.Future()  # run forever

# --------------------
# Flask server
# --------------------
app = Flask(__name__)

@app.route("/download", methods=["GET"])
def download():
    """
    Download the latest output.wav
    """
    try:
        return send_file("output.wav", as_attachment=True)
    except Exception as e:
        return f"Error: {e}", 500

def flask_thread():
    app.run(host="0.0.0.0", port=5111)

# --------------------
# Run both servers
# --------------------
if __name__ == "__main__":
    # Flask chạy trong thread
    t = Thread(target=flask_thread, daemon=True)
    t.start()
    # WebSocket chạy chính thread
    asyncio.run(ws_main())
