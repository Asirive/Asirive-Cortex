"""
Fix RPi5: replace expired API key in .env with the new one, then test.
Uses SFTP to drop a small Python script on the RPi5 to avoid shell-quoting hell.
"""
import io
import sys
import paramiko

# Force UTF-8 stdout (Windows cp1252)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

HOST = "172.26.13.31"
USER = "cortex"
PASS = "Haziqshah21"
ENV_PATH = "/home/cortex/ProjectCortex/.env"
SCRIPTS_DIR = "/home/cortex/ProjectCortex/scripts"
NEW_KEY = "REDACTED_GEMINI_KEY"

def banner(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)

def run(c, cmd, timeout=30):
    print(f"\n>>> {cmd[:200]}")
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return out, err, rc

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, USER, PASS, timeout=10, allow_agent=False, look_for_keys=False)
print(f"[OK] Connected to {USER}@{HOST}")

sftp = c.open_sftp()

# 1. Read current .env
banner("1. Current RPi5 .env")
with sftp.open(ENV_PATH, "r") as f:
    old_env = f.read().decode("utf-8", errors="replace")
print(old_env)

# 2. Patch .env: replace GEMINI_API_KEY and GOOGLE_API_KEY primary lines
new_env_lines = []
seen_keys = set()
for line in old_env.splitlines():
    if "=" in line and not line.strip().startswith("#"):
        key_name = line.split("=", 1)[0].strip()
        if key_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and key_name not in seen_keys:
            new_env_lines.append(f"{key_name}={NEW_KEY}")
            seen_keys.add(key_name)
            continue
    new_env_lines.append(line)
new_env = "\n".join(new_env_lines) + "\n"

# 3. Write patched .env
banner("2. Patched .env (NEW key written)")
with sftp.open(ENV_PATH, "w") as f:
    f.write(new_env)
print("[OK] Patched .env written")
print(new_env)

# 4. Write a test script to RPi5 (avoids shell escaping)
banner("3. Writing test script to RPi5")
test_script = '''#!/usr/bin/env python3
"""Live API test using the patched .env."""
import os, sys, json, asyncio
from pathlib import Path

# Force load .env (in case it was already loaded)
for line in Path(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
print(f"KEY: {key[:7]}...{key[-4:] if len(key) > 11 else ''}")
print(f"SDK: ", end="")
try:
    from google import genai
    print(f"google-genai {genai.__version__}")
except Exception as e:
    print(f"IMPORT FAIL: {e}")
    sys.exit(1)

# Test 1: raw WebSocket
print("\\n--- TEST 1: Raw WebSocket ---")
async def test_raw():
    import websockets
    url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={key}"
    try:
        async with websockets.connect(url, additional_headers={"x-goog-api-key": key}) as ws:
            print("WS: OPEN")
            setup = {
                "setup": {
                    "model": "models/gemini-3.1-flash-live-preview",
                    "generation_config": {"response_modalities": ["AUDIO"]},
                }
            }
            await ws.send(json.dumps(setup))
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            print(f"FIRST MSG: {msg[:200]}")
    except Exception as e:
        print(f"WS FAIL: {type(e).__name__}: {str(e)[:200]}")

asyncio.run(test_raw())

# Test 2: google-genai SDK (v1beta)
print("\\n--- TEST 2: google-genai SDK v1beta ---")
async def test_sdk():
    from google.genai import types
    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    config = types.LiveConnectConfig(response_modalities=[types.Modality.AUDIO])
    try:
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
        print(f"SDK FAIL: {type(e).__name__}: {str(e)[:300]}")

asyncio.run(test_sdk())
'''
import os
os.makedirs(SCRIPTS_DIR, exist_ok=True)
sftp.makedirs(SCRIPTS_DIR) if not os.path.exists(SCRIPTS_DIR) else None
with sftp.open(f"{SCRIPTS_DIR}/test_live_now.py", "w") as f:
    f.write(test_script)
print(f"[OK] Wrote {SCRIPTS_DIR}/test_live_now.py")

# 5. Run the test
banner("4. Running test on RPi5")
out, err, rc = run(c, "cd ~/ProjectCortex && source venv/bin/activate && python scripts/test_live_now.py", timeout=60)
print("STDOUT:")
print(out)
if err.strip():
    print("STDERR:")
    print(err[:1000])
print(f"RC: {rc}")

c.close()
print("\n[OK] Done.")
