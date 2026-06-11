"""
SSH into RPi5 and investigate the Gemini Live 1008 issue.

Connects, captures:
1. .env contents (which API key is actually live)
2. pip show google-genai (SDK version)
3. runs minimal raw-WS Live test (proves whether server rejects)
4. runs google-genai SDK Live test (proves whether SDK is the bug)
5. cat logs/cortex.log tail (last 30 lines)
"""
import os
import sys
import time
import io
import paramiko
from pathlib import Path

# Force UTF-8 stdout (Windows cp1252 can't print emoji)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

HOST = "10.202.14.31"
PORT = 22
USER = "cortex"
PASS = "REDACTED-RPI-PASSWORD"
PROJECT_DIR = "~/ProjectCortex"

# Resolve project dir to absolute
def ssh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, PORT, USER, PASS, timeout=10, allow_agent=False, look_for_keys=False)
    return c

def run(c, cmd, timeout=30):
    """Run cmd, return (stdout, stderr, exit_code)."""
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return out, err, rc

def banner(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)

def main():
    c = ssh()
    print(f"[OK] Connected to {USER}@{HOST}")

    # 1. PWD + project layout
    banner("1. Environment basics")
    out, _, _ = run(c, "pwd && ls -la ProjectCortex/ | head -20 && echo '---' && cat ProjectCortex/.env 2>&1 | head -20")
    print(out)

    # 2. SDK + python version
    banner("2. Installed SDK versions")
    out, _, _ = run(c, f"cd {PROJECT_DIR} && source venv/bin/activate 2>/dev/null; python -c 'import google.genai; print(\"google-genai:\", google.genai.__version__)' 2>&1; python --version 2>&1; pip show google-genai 2>&1 | head -3")
    print(out)

    # 3. Raw WebSocket test (proves server is reachable + key works)
    banner("3. Raw WebSocket test (should pass if key+model OK)")
    out, err, rc = run(c, f"cd {PROJECT_DIR} && source venv/bin/activate && python -c "
        "\"\"\n"
        "import os, asyncio, json, websockets\n"
        "from pathlib import Path\n"
        "for line in Path('.env').read_text().splitlines():\n"
        "    line = line.strip()\n"
        "    if line and not line.startswith('#') and '=' in line:\n"
        "        k,v = line.split('=',1)\n"
        "        os.environ.setdefault(k.strip(), v.strip())\n"
        "key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')\n"
        "print('KEY:', key[:7]+'...'+key[-4:] if key else 'NONE')\n"
        "async def main():\n"
        "    url = 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=' + key\n"
        "    headers = {'x-goog-api-key': key}\n"
        "    try:\n"
        "        async with websockets.connect(url, additional_headers=headers) as ws:\n"
        "            print('WS: OPEN')\n"
        "            await ws.send(json.dumps({'setup':{'model':'models/gemini-3.1-flash-live-preview','generation_config':{'response_modalities':['AUDIO']}}}))\n"
        "            msg = await asyncio.wait_for(ws.recv(), timeout=10)\n"
        "            print('FIRST MSG:', msg[:200])\n"
        "    except Exception as e:\n"
        "        print('WS FAIL:', type(e).__name__, str(e)[:200])\n"
        "asyncio.run(main())\n"
        "\"\"\"", timeout=20)
    print("STDOUT:", out)
    if err.strip():
        print("STDERR:", err[:600])
    print("RC:", rc)

    # 4. google-genai SDK test (proves whether SDK has the bug)
    banner("4. google-genai SDK test (minimal config)")
    out, err, rc = run(c, f"cd {PROJECT_DIR} && source venv/bin/activate && python -c "
        "\"\"\n"
        "import os, asyncio\n"
        "from pathlib import Path\n"
        "for line in Path('.env').read_text().splitlines():\n"
        "    line = line.strip()\n"
        "    if line and not line.startswith('#') and '=' in line:\n"
        "        k,v = line.split('=',1)\n"
        "        os.environ.setdefault(k.strip(), v.strip())\n"
        "from google import genai\n"
        "from google.genai import types\n"
        "key = os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')\n"
        "print('KEY:', key[:7]+'...'+key[-4:])\n"
        "client = genai.Client(api_key=key, http_options={'api_version': 'v1beta'})\n"
        "config = types.LiveConnectConfig(response_modalities=[types.Modality.AUDIO])\n"
        "async def main():\n"
        "    try:\n"
        "        async with client.aio.live.connect(model='gemini-3.1-flash-live-preview', config=config) as s:\n"
        "            print('SDK: OPEN')\n"
        "            count = 0\n"
        "            async for r in s.receive():\n"
        "                count += 1\n"
        "                sc = getattr(r, 'server_content', None)\n"
        "                print(f'msg#{count} setup_complete={getattr(sc, \"setup_complete\", None)}')\n"
        "                if count >= 2: break\n"
        "    except Exception as e:\n"
        "        print('SDK FAIL:', type(e).__name__, str(e)[:200])\n"
        "asyncio.run(main())\n"
        "\"\"\"", timeout=30)
    print("STDOUT:", out)
    if err.strip():
        print("STDERR:", err[:600])
    print("RC:", rc)

    # 5. Test WITHOUT http_options (maybe default v1 works)
    banner("5. google-genai SDK test (no http_options)")
    out, err, rc = run(c, f"cd {PROJECT_DIR} && source venv/bin/activate && python -c "
        "\"\"\n"
        "import os, asyncio\n"
        "from pathlib import Path\n"
        "for line in Path('.env').read_text().splitlines():\n"
        "    line = line.strip()\n"
        "    if line and not line.startswith('#') and '=' in line:\n"
        "        k,v = line.split('=',1)\n"
        "        os.environ.setdefault(k.strip(), v.strip())\n"
        "from google import genai\n"
        "from google.genai import types\n"
        "key = os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')\n"
        "client = genai.Client(api_key=key)  # no http_options\n"
        "config = types.LiveConnectConfig(response_modalities=[types.Modality.AUDIO])\n"
        "async def main():\n"
        "    try:\n"
        "        async with client.aio.live.connect(model='gemini-3.1-flash-live-preview', config=config) as s:\n"
        "            print('SDK(no-httpa): OPEN')\n"
        "            count = 0\n"
        "            async for r in s.receive():\n"
        "                count += 1\n"
        "                sc = getattr(r, 'server_content', None)\n"
        "                print(f'msg#{count} setup_complete={getattr(sc, \"setup_complete\", None)}')\n"
        "                if count >= 2: break\n"
        "    except Exception as e:\n"
        "        print('SDK FAIL:', type(e).__name__, str(e)[:200])\n"
        "asyncio.run(main())\n"
        "\"\"\"", timeout=30)
    print("STDOUT:", out)
    if err.strip():
        print("STDERR:", err[:600])
    print("RC:", rc)

    # 6. Last 40 lines of cortex.log
    banner("6. Last 40 lines of logs/cortex.log")
    out, _, _ = run(c, f"cd {PROJECT_DIR} && tail -40 logs/cortex.log 2>&1")
    print(out)

    c.close()
    print("\n[OK] Investigation done.")

if __name__ == "__main__":
    main()
