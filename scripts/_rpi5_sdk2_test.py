#!/usr/bin/env python3
"""Test SDK 1.68 on RPi5 with audio send to trigger responses."""
import os, sys, signal, asyncio, struct
from pathlib import Path
for line in Path("/home/cortex/ProjectCortex/.env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()
key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")

def handler(signum, frame):
    print("HARD TIMEOUT 30s")
    sys.exit(124)
signal.signal(signal.SIGALRM, handler)
signal.alarm(30)

from google import genai
from google.genai import types
print("SDK:", genai.__version__)

async def main():
    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    try:
        print("Connecting...")
        async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as s:
            print("SDK: OPEN")
            # Try sending a small text prompt
            print("Sending text prompt 'hello'...")
            await s.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text="hi")])],
                turn_complete=True,
            )
            print("Sent. Waiting for first msg (20s)...")
            try:
                r = await asyncio.wait_for(s.receive().__anext__(), timeout=20)
                print(f"msg: {type(r).__name__} sc={getattr(r, 'server_content', None) is not None}")
                if hasattr(r, 'server_content') and r.server_content:
                    sc = r.server_content
                    print("  model_turn:", sc.model_turn is not None)
                    if sc.model_turn:
                        for p in sc.model_turn.parts:
                            if p.text: print("  text:", p.text[:200])
                            if p.inline_data: print("  audio bytes:", len(p.inline_data.data))
            except asyncio.TimeoutError:
                print("No response in 20s")
            except Exception as e:
                print("Recv error:", e)
    except Exception as e:
        print("SDK FAIL:", type(e).__name__, str(e)[:300])
asyncio.run(main())
