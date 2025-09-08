import asyncio
import websockets
import json
import base64
import soundfile as sf
import numpy as np

# buffer để lưu audio
audio_frames = []

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

        if data["event"] == "start":
            print("Stream started:", data["streamSid"])

        elif data["event"] == "media":
            # Nhận audio base64 từ Twilio
            payload = data["media"]["payload"]
            audio_chunk = base64.b64decode(payload)
            audio_frames.append(audio_chunk)

        elif data["event"] == "stop":
            print("Stream stopped")
            # Khi kết thúc stream -> lưu ra file WAV
            pcm_data = b"".join(audio_frames)
            audio_frames = []

            # Chuyển sang numpy int16
            audio_array = np.frombuffer(pcm_data, dtype=np.int16)

            # Lưu thành wav (mono, 8kHz vì Twilio gửi ở 8kHz)
            sf.write("output.wav", audio_array, 8000)
            print("💾 Saved output.wav")

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("🚀 WebSocket server listening on ws://0.0.0.0:8765/media")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
