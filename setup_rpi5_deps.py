#!/usr/bin/env python3
"""
RPi5 Dependency Setup via Paramiko
Fixes numpy/picamera2 incompatibility, installs zmq, hailo, and all deps.

Author: Haziq (@IRSPlays)
Date: March 25, 2026
"""
import sys
import time

try:
    import paramiko
except ImportError:
    print("ERROR: paramiko not installed. Run: pip install paramiko")
    sys.exit(1)

# RPi5 connection details
RPI_HOST = "10.245.247.31"
RPI_USER = "cortex"
RPI_PASS = "Haziqshah21"
PROJECT_DIR = "/home/cortex/ProjectCortex"
VENV_ACTIVATE = f"source {PROJECT_DIR}/venv/bin/activate"


def run_cmd(ssh, cmd, timeout=300, check=False):
    """Execute a command over SSH and print output in real-time."""
    print(f"\n{'='*60}")
    print(f"[CMD] {cmd}")
    print('='*60)
    
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    exit_code = stdout.channel.recv_exit_status()
    
    if out.strip():
        # Truncate very long output
        lines = out.strip().split('\n')
        if len(lines) > 50:
            print('\n'.join(lines[:20]))
            print(f"  ... ({len(lines) - 40} lines omitted) ...")
            print('\n'.join(lines[-20:]))
        else:
            print(out.strip())
    if err.strip():
        print(f"[STDERR] {err.strip()[:500]}")
    
    if check and exit_code != 0:
        print(f"[FAIL] Exit code: {exit_code}")
    else:
        print(f"[OK] Exit code: {exit_code}")
    
    return exit_code, out, err


def main():
    print("Connecting to RPi5...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(RPI_HOST, username=RPI_USER, password=RPI_PASS, timeout=10)
        print(f"Connected to {RPI_USER}@{RPI_HOST}")
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)
    
    # ──────────────────────────────────────────────────
    # PHASE 1: System packages (apt)
    # ──────────────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 1: System packages (apt)")
    print("="*60)
    
    # Update apt cache
    run_cmd(ssh, "echo 'Haziqshah21' | sudo -S apt-get update -qq", timeout=120)
    
    # Install all system dependencies in one shot
    system_pkgs = [
        # Audio
        "libportaudio2", "portaudio19-dev", "libopenal1", "libopenal-dev",
        "espeak-ng", "ffmpeg", "libsndfile1",
        # Camera
        "python3-picamera2", "python3-libcamera",
        # Build tools (for pip packages that compile)
        "build-essential", "python3-dev", "cmake",
        # Math/science libs
        "libatlas-base-dev", "libopenblas-dev",
        # ZMQ system lib
        "libzmq3-dev",
        # I2C/GPIO
        "python3-rpi-lgpio", "i2c-tools",
        # Hailo
        "hailo-all",
    ]
    
    pkg_str = " ".join(system_pkgs)
    run_cmd(ssh, f"echo 'Haziqshah21' | sudo -S apt-get install -y {pkg_str}", timeout=600)
    
    # ──────────────────────────────────────────────────
    # PHASE 2: Fix numpy in venv
    # ──────────────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 2: Fix numpy / picamera2 compatibility")
    print("="*60)
    
    # Check system numpy version first
    run_cmd(ssh, "python3 -c \"import numpy; print('System numpy:', numpy.__version__)\"")
    
    # Check current venv numpy
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && python -c \"import numpy; print(numpy.__version__)\"'")
    
    # Force reinstall numpy to match what system simplejpeg expects (numpy 2.x)
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install --upgrade \"numpy>=2.1.0\"'", timeout=180)
    
    # Verify picamera2 now works
    exit_code, out, _ = run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && python -c \"import picamera2; print(picamera2.__version__)\"'")
    if exit_code == 0:
        print("\n>>> picamera2 import FIXED!")
    else:
        print("\n>>> picamera2 still broken - trying alternative fix...")
        # Alternative: reinstall simplejpeg to match current numpy
        run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install --force-reinstall simplejpeg'", timeout=120)
        run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && python -c \"import picamera2; print(picamera2.__version__)\"'")
    
    # ──────────────────────────────────────────────────
    # PHASE 3: Core Python packages (pip)
    # ──────────────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 3: Core Python packages")
    print("="*60)
    
    # Install in batches to avoid OOM on 4GB RPi5
    
    # Batch 1: Core essentials
    batch1 = [
        "python-dotenv",
        "pyyaml>=6.0.2",
        "psutil>=6.1.1",
        "requests>=2.32.3",
        "pillow>=11.1.0",
        "rich",
    ]
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install {' '.join(batch1)}'", timeout=180)
    
    # Batch 2: OpenCV (headless for Lite OS)
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install opencv-python-headless>=4.10.0'", timeout=300)
    
    # Batch 3: ZMQ
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install pyzmq>=26.0.0 imagezmq>=1.2.0'", timeout=180)
    
    # Batch 4: Audio
    batch4 = [
        "pygame>=2.6.1",
        "sounddevice>=0.5.1",
        "soundfile>=0.13.0",
        "scipy>=1.15.0",
        "pydub>=0.25.1",
        "silero-vad>=5.1.2",
    ]
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install {' '.join(batch4)}'", timeout=300)
    
    # Batch 5: Web/Server
    batch5 = [
        "fastapi>=0.115.6",
        "uvicorn[standard]>=0.34.0",
        "websockets>=14.1",
    ]
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install {' '.join(batch5)}'", timeout=180)
    
    # Batch 6: AI/ML (heavy - torch is big)
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install torch>=2.6.0 torchvision>=0.21.0'", timeout=900)
    
    # Batch 7: YOLO + inference
    batch7 = [
        "ultralytics>=8.4.0",
        "ncnn>=1.0.20240410",
        "onnxruntime>=1.17.0",
        "onnx>=1.15.0",
    ]
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install {' '.join(batch7)}'", timeout=600)
    
    # Batch 8: Cloud APIs
    batch8 = [
        "google-genai>=1.60.0",
        "google-generativeai>=0.8.6",
        "openai>=1.60.1",
        "gradio-client>=1.7.0",
        "cartesia>=1.0.0",
    ]
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install {' '.join(batch8)}'", timeout=300)
    
    # Batch 9: TTS/STT
    batch9 = [
        "openai-whisper>=20240930",
        "kokoro-onnx>=0.4.9",
        "\"misaki[en]>=0.5.0\"",
        "espeakng-loader>=0.1.3",
    ]
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install {' '.join(batch9)}'", timeout=600)

    # Batch 10: Supabase
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install supabase>=2.3.4'", timeout=180)
    
    # Batch 11: PyOpenAL for spatial audio
    run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install PyOpenAL'", timeout=120)
    
    # ──────────────────────────────────────────────────
    # PHASE 4: Hailo SDK (if apt didn't cover it)
    # ──────────────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 4: Hailo SDK check")
    print("="*60)
    
    exit_code, _, _ = run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && python -c \"from hailo_platform import VDevice; print(\\\"Hailo OK\\\")\"'")
    if exit_code != 0:
        print("Hailo platform not available via system. Trying pip...")
        run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && pip install hailort'", timeout=300)
        run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && python -c \"from hailo_platform import VDevice; print(\\\"Hailo OK\\\")\"'")
    
    # ──────────────────────────────────────────────────
    # PHASE 5: Verification
    # ──────────────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 5: Verification")  
    print("="*60)
    
    checks = [
        ("numpy",      "import numpy; print('numpy', numpy.__version__)"),
        ("cv2",        "import cv2; print('cv2', cv2.__version__)"),
        ("picamera2",  "import picamera2; print('picamera2 OK')"),
        ("torch",      "import torch; print('torch', torch.__version__)"),
        ("ultralytics","from ultralytics import YOLO; print('ultralytics OK')"),
        ("zmq",        "import zmq; print('zmq', zmq.__version__)"),
        ("sounddevice","import sounddevice; print('sounddevice OK')"),
        ("fastapi",    "import fastapi; print('fastapi', fastapi.__version__)"),
        ("websockets", "import websockets; print('websockets OK')"),
        ("whisper",    "import whisper; print('whisper OK')"),
        ("yaml",       "import yaml; print('yaml OK')"),
        ("psutil",     "import psutil; print('psutil OK')"),
        ("supabase",   "import supabase; print('supabase OK')"),
        ("PyOpenAL",   "from openal import *; print('PyOpenAL OK')"),
        ("genai",      "from google import genai; print('google-genai OK')"),
        ("hailo",      "from hailo_platform import VDevice; print('hailo OK')"),
    ]
    
    passed = 0
    failed = 0
    for name, check_code in checks:
        exit_code, out, err = run_cmd(ssh, f"bash -c '{VENV_ACTIVATE} && python -c \"{check_code}\"'")
        if exit_code == 0:
            passed += 1
        else:
            failed += 1
            print(f"  >>> {name} FAILED")
    
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(checks)}")
    print(f"{'='*60}")
    
    ssh.close()
    print("\nDone! SSH connection closed.")


if __name__ == "__main__":
    main()
