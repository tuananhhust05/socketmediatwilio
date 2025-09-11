import asyncio
import websockets
import json
import base64
import wave
import audioop
from flask import Flask, send_file
from threading import Thread
from faster_whisper import WhisperModel
import webrtcvad
import soundfile as sf
import numpy as np

# Load Faster Whisper
model = WhisperModel("tiny.en", device="cpu", compute_type="int8")

# Voice Activity Detector
vad = webrtcvad.Vad(2)  
frame_duration_ms = 30  
sample_rate = 8000
frame_bytes = int(sample_rate * 2 * frame_duration_ms / 1000)  # 16-bit PCM → 2 bytes

buffer_pcm = b""
speech_buffer = b""

audio_frames = []

async def handler(websocket):
    global buffer_pcm, speech_buffer
    print("✅ Client connected on /media")

    async for message in websocket:
        try:
            data = json.loads(message)
        except Exception as e:
            print("❌ JSON parse error:", e)
            continue

        event = data.get("event")
        if event == "media":
            # decode μ-law -> PCM16
            payload_b64 = data["media"]["payload"]
            ulaw_bytes = base64.b64decode(payload_b64)
            pcm16_bytes = audioop.ulaw2lin(ulaw_bytes, 2)
            buffer_pcm += pcm16_bytes

            # chia thành frame 30ms
            while len(buffer_pcm) >= frame_bytes:
                frame = buffer_pcm[:frame_bytes]
                buffer_pcm = buffer_pcm[frame_bytes:]

                is_speech = vad.is_speech(frame, sample_rate)

                if is_speech:
                    speech_buffer += frame
                else:
                    if len(speech_buffer) > 0:
                        # Người nói vừa dừng lại → transcript đoạn speech_buffer
                        await transcribe_and_print(speech_buffer)
                        speech_buffer = b""

        elif event == "stop":
            print("Stream stopped")
            if speech_buffer:
                await transcribe_and_print(speech_buffer)
                speech_buffer = b""

async def transcribe_and_print(pcm_bytes):
    # Chuyển sang float32 numpy cho faster-whisper
    audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    # Lưu tạm ra file WAV (hoặc dùng trực tiếp np array cũng được)
    sf.write("temp.wav", audio_np, sample_rate)

    segments, _ = model.transcribe("temp.wav", beam_size=1)
    text = "".join([seg.text for seg in segments])
    print("📝 Transcript:", text.strip())

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
