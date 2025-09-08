import asyncio
import websockets
import json
import base64
import wave
import audioop
from flask import Flask, send_file
from threading import Thread

audio_frames = []

async def handler(websocket):
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
            payload_b64 = data["media"]["payload"]
            ulaw_bytes = base64.b64decode(payload_b64)
            pcm16_bytes = audioop.ulaw2lin(ulaw_bytes, 2)  # decode μ-law -> PCM16
            audio_frames.append(pcm16_bytes)

        elif event == "stop":
            print("Stream stopped")
            if audio_frames:
                pcm_data = b"".join(audio_frames)
                audio_frames.clear()

                # ghi WAV chuẩn PCM16
                with wave.open("output.wav", "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(8000)
                    wf.writeframes(pcm_data)
                print("💾 Saved output.wav (PCM16 8kHz)")

# WebSocket server
async def ws_main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("🚀 WebSocket server listening on ws://0.0.0.0:8765/media")
        await asyncio.Future()

# Flask server để download
app = Flask(__name__)
@app.route("/download", methods=["GET"])
def download():
    try:
        return send_file("output.wav", as_attachment=True)
    except Exception as e:
        return f"Error: {e}", 500

def flask_thread():
    app.run(host="0.0.0.0", port=5111)

if __name__ == "__main__":
    Thread(target=flask_thread, daemon=True).start()
    asyncio.run(ws_main())
