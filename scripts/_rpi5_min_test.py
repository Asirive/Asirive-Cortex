#!/usr/bin/env python3
import os, sys, json, asyncio
from pathlib import Path
for line in Path("/home/cortex/ProjectCortex/.env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()
key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
print("KEY:", key[:7] + "..." + key[-4:] if key else "NONE")
print("KEY from env GOOGLE_API_KEY:", "GOOGLE_API_KEY" in os.environ)
print("KEY from env GEMINI_API_KEY:", "GEMINI_API_KEY" in os.environ)

async def main():
    import websockets
    url = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=" + key
    print("Connecting...")
    try:
        async with websockets.connect(url, additional_headers={"x-goog-api-key": key}, open_timeout=10) as ws:
            print("WS: OPEN")
            setup = {"setup": {"model": "models/gemini-3.1-flash-live-preview", "generation_config": {"response_modalities": ["AUDIO"]}}}
            await ws.send(json.dumps(setup))
            print("Waiting for first msg (10s timeout)...")
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            print("FIRST MSG:", msg[:300])
    except asyncio.TimeoutError:
        print("TIMEOUT")
    except Exception as e:
        print("FAIL:", type(e).__name__, str(e)[:300])
asyncio.run(main())
