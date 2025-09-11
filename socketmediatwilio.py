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
import requests
import edge_tts
import tempfile
import traceback
import os
import shutil
import math
# Load Faster Whisper
model = WhisperModel("tiny.en", device="cpu", compute_type="int8")

# Voice Activity Detector
vad = webrtcvad.Vad(0)
frame_duration_ms = 30
sample_rate = 8000
frame_bytes = int(sample_rate * 2 * frame_duration_ms / 1000)  # 16-bit PCM → 2 bytes

buffer_pcm = b""
speech_buffer = b""
silence_threshold = int(0.8 * 1000 / frame_duration_ms)

# global state
is_processing = False
stream_sid = None
current_websocket = None

VOICE = "en-US-AriaNeural"  # giọng của edge-tts

async def handler(websocket):
    global buffer_pcm, speech_buffer, stream_sid, current_websocket
    current_websocket = websocket
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
                        await transcribe_and_respond(speech_buffer)
                        speech_buffer = b""

        elif event == "start":
            stream_sid = data["start"]["streamSid"]
            print(f"🎧 Stream started with streamSid={stream_sid}")

        elif event == "stop":
            print("⏹️ Stream stopped")
            if speech_buffer:
                await transcribe_and_respond(speech_buffer)
                speech_buffer = b""


async def transcribe_and_respond(pcm_bytes):
    global is_processing, stream_sid, current_websocket
    if is_processing:
        print("⏳ waiting for previous transcription to finish...")
        return

    # convert cho Whisper
    audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    sf.write("temp.wav", audio_np, sample_rate)

    segments, _ = model.transcribe("temp.wav", beam_size=1)
    text = "".join([seg.text for seg in segments])
    print("📝 Transcript:", text)
    if not text:
        return

    is_processing = True

    # ====== gọi webhook LLM ======
    try:
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "0",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "messages": [
                                    {
                                        "type": "text",
                                        "text": {"body": text.strip()}
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        response = requests.post(
            "http://127.0.0.1:8501/webhook",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()
        llm_response = response.json().get("reply", "Please repeat that.")
    except Exception as e:
        print("❌ Webhook error:", e)
        llm_response = "Please repeat that."

    print("🤖 LLM Response:", llm_response)

     # ====== Tạo audio bằng edge-tts ======
    try:
        tts = edge_tts.Communicate(llm_response, voice=VOICE)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmpfile:
            out_wav = tmpfile.name
        await tts.save(out_wav)

        # Đọc file wav -> PCM16
        data, sr = sf.read(out_wav, dtype="int16")
        if sr != sample_rate:
            print(f"⚠️ sample rate {sr}Hz, cần 8000Hz cho Twilio")
            # convert về 8kHz
            sf.write(out_wav, data, sample_rate)
            data, sr = sf.read(out_wav, dtype="int16")

        pcm16 = data.flatten().tobytes()

        # PCM16 -> μ-law (PCMU)
        mulaw_bytes = audioop.lin2ulaw(pcm16, 2)

        # Chia thành chunk nhỏ (20ms ~ 160 bytes ở 8kHz μ-law)
        chunk_size = int(sample_rate * 0.02)  # 20ms = 160 samples
        for i in range(0, len(mulaw_bytes), chunk_size):
            chunk = mulaw_bytes[i:i+chunk_size]
            payload_b64 = base64.b64encode(chunk).decode("utf-8")
            audio_event = {
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": payload_b64}
            }
            await current_websocket.send(json.dumps(audio_event))
            await asyncio.sleep(0.02)  # giả lập realtime streaming
        print("🔊 Sent TTS audio to Twilio")

        os.remove(out_wav)
    except Exception as e:
        print("❌ TTS error:", e)
        traceback.print_exc()



    is_processing = False


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
