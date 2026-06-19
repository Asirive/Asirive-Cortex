"""
RPi5 dependency / environment setup helper.

All commands are run over SSH using the credentials from
``scripts/_rpi_ssh.py`` (env vars, never hardcoded). See
``python scripts/_rpi_ssh.py`` to verify your env is set.

Usage:
    python rpi5_setup.py check         # check numpy/picamera2
    python rpi5_setup.py fix-numpy     # upgrade numpy in venv
    python rpi5_setup.py core          # install core python pkgs
    python rpi5_setup.py verify        # run a full import check
    ... (see __main__ block for the full list)
"""
import sys

from scripts._rpi_ssh import (
    RPI_HOST,
    RPI_PASSWORD,
    RPI_USER,
    get_ssh_client,
    require_credentials,
)

require_credentials()
import paramiko  # noqa: E402  (imported after env check)

ssh = get_ssh_client()
ssh.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)

VENV = "source /home/cortex/ProjectCortex/venv/bin/activate"


def run(cmd, label=""):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=300)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    code = stdout.channel.recv_exit_status()
    if label:
        print(f"\n[{label}]")
    if out:
        lines = out.split('\n')
        if len(lines) > 30:
            print('\n'.join(lines[:10]))
            print(f"  ... ({len(lines)-20} lines skipped) ...")
            print('\n'.join(lines[-10:]))
        else:
            print(out)
    if err:
        print(f"STDERR: {err[:300]}")
    print(f"EXIT: {code}")
    return code, out, err


# Step from command line arg
step = sys.argv[1] if len(sys.argv) > 1 else "check"

if step == "check":
    run('python3 -c "import numpy; print(numpy.__version__)"', "System numpy")
    run(f'bash -c "{VENV} && python -c \\"import numpy; print(numpy.__version__)\\""', "Venv numpy")
    run(f'bash -c "{VENV} && python -c \\"import picamera2; print(\\\\\\"picamera2 OK\\\\\\")\\""', "Venv picamera2")

elif step == "fix-numpy":
    run(f'bash -c "{VENV} && pip install --upgrade \\"numpy>=2.1.0\\""', "Upgrade numpy in venv")

elif step == "fix-simplejpeg":
    run(f'bash -c "{VENV} && pip install --force-reinstall simplejpeg"', "Force reinstall simplejpeg")

elif step == "core":
    run(f'bash -c "{VENV} && pip install python-dotenv pyyaml psutil requests pillow rich"', "Core essentials")

elif step == "opencv":
    run(f'bash -c "{VENV} && pip install opencv-python-headless"', "OpenCV headless")

elif step == "zmq":
    run(f'bash -c "{VENV} && pip install pyzmq imagezmq"', "ZMQ packages")

elif step == "audio":
    run(f'bash -c "{VENV} && pip install pygame sounddevice soundfile scipy pydub silero-vad"', "Audio packages")

elif step == "web":
    run(f'bash -c "{VENV} && pip install fastapi \\"uvicorn[standard]\\" websockets"', "Web/Server")

elif step == "torch":
    run(f'bash -c "{VENV} && pip install torch torchvision"', "PyTorch (this takes a while)")

elif step == "yolo":
    run(f'bash -c "{VENV} && pip install ultralytics ncnn onnxruntime onnx"', "YOLO + inference")

elif step == "cloud":
    run(f'bash -c "{VENV} && pip install google-genai google-generativeai openai gradio-client cartesia"', "Cloud APIs")

elif step == "tts":
    run(f'bash -c "{VENV} && pip install openai-whisper kokoro-onnx \\"misaki[en]\\" espeakng-loader"', "TTS/STT")

elif step == "supabase":
    run(f'bash -c "{VENV} && pip install supabase"', "Supabase")

elif step == "spatial":
    run(f'bash -c "{VENV} && pip install PyOpenAL"', "PyOpenAL")

elif step == "extras":
    run(f'bash -c "{VENV} && pip install pyaudio"', "PyAudio")
    run(f'bash -c "{VENV} && pip install pyserial"', "PySerial (GPS UART)")
    run(f'bash -c "{VENV} && pip install aiohttp"', "aiohttp (phone GPS)")
    run(f'bash -c "{VENV} && python -m spacy download en_core_web_sm"', "spaCy model")

elif step == "fix-torchaudio":
    run(f'bash -c "{VENV} && ls /home/cortex/ProjectCortex/venv/lib/python3.11/site-packages/torch/lib/libc10* 2>&1 | head -5"', "Check torch libs exist")
    run(f'bash -c "{VENV} && pip install torchaudio --index-url https://download.pytorch.org/whl/cpu --force-reinstall --no-deps"', "Install CPU-only torchaudio")
    run(f'bash -c "{VENV} && ldd /home/cortex/ProjectCortex/venv/lib/python3.11/site-packages/torchaudio/lib/_torchaudio.abi3.so 2>&1 | grep not"', "Check missing shared libs after fix")

elif step == "aiohttp":
    run(f'bash -c "{VENV} && pip install aiohttp"', "aiohttp")

elif step == "hailo":
    run(f'bash -c "{VENV} && python -c \\"from hailo_platform import VDevice; print(\\\\\\"Hailo OK\\\\\\")\\""', "Hailo check")

elif step == "verify":
    # Write a verification script to RPi5 to avoid quoting hell
    verify_script = '''
import sys
checks = {
    "numpy": "import numpy; v=numpy.__version__",
    "cv2": "import cv2; v=cv2.__version__",
    "picamera2": "import picamera2; v='OK'",
    "torch": "import torch; v=torch.__version__",
    "ultralytics": "from ultralytics import YOLO; v='OK'",
    "zmq": "import zmq; v=zmq.__version__",
    "sounddevice": "import sounddevice; v='OK'",
    "fastapi": "import fastapi; v=fastapi.__version__",
    "websockets": "import websockets; v='OK'",
    "whisper": "import whisper; v='OK'",
    "yaml": "import yaml; v='OK'",
    "psutil": "import psutil; v='OK'",
    "supabase": "import supabase; v='OK'",
    "PyOpenAL": "from openal import *; v='OK'",
    "genai": "from google import genai; v='OK'",
    "hailo": "from hailo_platform import VDevice; v='OK'",
}
passed = failed = 0
for name, code in checks.items():
    try:
        v = None
        exec(code)
        print(f"  PASS  {name}: {v}")
        passed += 1
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        failed += 1
print(f"\\nRESULTS: {passed} passed, {failed} failed / {len(checks)}")
'''
    # Upload and run the script
    run(f"cat > /tmp/verify_imports.py << 'SCRIPT_EOF'\n{verify_script}\nSCRIPT_EOF", "Upload verify script")
    run(f'bash -c "{VENV} && python /tmp/verify_imports.py"', "Run verification")

elif step == "test-import":
    run(f'bash -c "{VENV} && cd /home/cortex/ProjectCortex && python -c \\"from rpi5.main import CortexSystem; print(\\\\\\"CortexSystem import OK\\\\\\")\\""', "Test rpi5.main import")

elif step == "test-import-full":
    run(f'bash -c "{VENV} && cd /home/cortex/ProjectCortex && python -c \\"from rpi5.main import CortexSystem; print(\\\\\\"CortexSystem import OK\\\\\\")\\" 2>&1"', "Test rpi5.main import (full stderr)")

else:
    print(f"Unknown step: {step}")
    print("Steps: check fix-numpy fix-simplejpeg core opencv zmq audio web torch yolo cloud tts supabase spatial hailo verify test-import")

ssh.close()
