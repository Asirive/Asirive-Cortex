#!/usr/bin/env python3
"""Test google-genai SDK on RPi5 with new key."""
import os, sys, signal, asyncio
from pathlib import Path
for line in Path("/home/cortex/ProjectCortex/.env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()
key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
print("KEY:", key[:7] + "..." + key[-4:])

def handler(signum, frame):
    print("HARD TIMEOUT")
    sys.exit(124)
signal.signal(signal.SIGALRM, handler)
signal.alarm(30)

from google import genai
from google.genai import types
print("SDK:", genai.__version__)

async def main():
    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    config = types.LiveConnectConfig(response_modalities=[types.Modality.AUDIO])
    try:
        print("Connecting via SDK...")
        async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as s:
            print("SDK: OPEN")
            count = 0
            async for r in s.receive():
                count += 1
                sc = getattr(r, "server_content", None)
                complete = getattr(sc, "setup_complete", None) if sc else None
                print(f"msg#{count} setup_complete={complete}")
                if count >= 2 or complete:
                    break
    except Exception as e:
        print("SDK FAIL:", type(e).__name__, str(e)[:300])
asyncio.run(main())
