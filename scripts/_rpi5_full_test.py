#!/usr/bin/env python3
"""Test SDK 1.68 with full production config + multiple messages."""
import os, sys, signal, asyncio
from pathlib import Path
for line in Path("/home/cortex/ProjectCortex/.env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()
key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")

def handler(signum, frame):
    print("\nHARD TIMEOUT")
    sys.exit(124)
signal.signal(signal.SIGALRM, handler)
signal.alarm(45)

from google import genai
from google.genai import types
print("SDK:", genai.__version__)

async def main():
    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})

    # Mimic the FULL production config from gemini_live_handler.py
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction="You are a test assistant. Reply in 1 short sentence.",
        temperature=0.7,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Zephyr")
            )
        ),
        media_resolution="MEDIA_RESOLUTION_MEDIUM",
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=104857,
            sliding_window=types.SlidingWindow(target_tokens=52428),
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        ),
    )
    try:
        print("Connecting with FULL config...")
        async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as s:
            print("SDK: OPEN")
            await s.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text="hi, what is 2+2?")])],
                turn_complete=True,
            )
            print("Sent prompt. Reading messages for 25s...")
            count = 0
            try:
                async for r in s.receive():
                    count += 1
                    sc = getattr(r, 'server_content', None)
                    mt = getattr(sc, 'model_turn', None) if sc else None
                    if mt and mt.parts:
                        for p in mt.parts:
                            if p.text: print(f"  [TEXT] {p.text[:200]}")
                            if p.inline_data: print(f"  [AUDIO] {len(p.inline_data.data)} bytes")
                    elif mt:
                        print(f"  [empty model_turn]")
                    sc_complete = getattr(sc, 'setup_complete', None) if sc else None
                    sc_interrupted = getattr(sc, 'interrupted', None) if sc else None
                    sc_turn_complete = getattr(sc, 'turn_complete', None) if sc else None
                    print(f"msg#{count} turn_complete={sc_turn_complete} setup_complete={sc_complete} interrupted={sc_interrupted}")
                    if sc_turn_complete and count > 0:
                        break
                    if count >= 30: break
            except asyncio.TimeoutError:
                print("Timeout in receive")
    except Exception as e:
        print("SDK FAIL:", type(e).__name__, str(e)[:500])
asyncio.run(main())
