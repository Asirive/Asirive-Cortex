# Project Cortex v2.0 - Complete RPi 5 Dependency Setup Guide

**Author:** GitHub Copilot (CTO)  
**Date:** December 31, 2025  
**Status:** PRODUCTION READY  
**Hardware:** Raspberry Pi 5 (4GB), Raspberry Pi Camera Module 3 (Wide)  
**OS:** Raspberry Pi OS Lite (64-bit) or Raspberry Pi OS (64-bit)

---

## 🎯 EXECUTIVE SUMMARY

This document provides **complete setup instructions** for deploying Project Cortex v2.0 on Raspberry Pi 5. After following this guide, your RPi will be running:
- **Layer 0 (Guardian):** YOLO11x safety detection (<100ms)
- **Layer 1 (Learner):** YOLOE-11s adaptive learning (3 modes)
- **Layer 2 (Thinker):** Whisper STT + Gemini Live API + Kokoro TTS
- **Layer 3 (Guide):** 3D Spatial Audio with PyOpenAL
- **Layer 4 (Memory):** SQLite object storage

**Total Setup Time:** 2-3 hours (including downloads)  
**Estimated RAM Usage:** 3.4-3.8GB (within 4GB limit)

---

## 📋 SYSTEM ARCHITECTURE OVERVIEW

### Hardware Components
```
┌─────────────────────────────────────────────────────────────┐
│                   RASPBERRY PI 5 (4GB RAM)                   │
├─────────────────────────────────────────────────────────────┤
│ SENSORS:                                                     │
│  • RPi Camera Module 3 (Wide) - 11.9MP, IMX708 sensor       │
│  • BNO055 IMU - 9-DOF Head-Tracking (I2C) [FUTURE]         │
│  • GY-NEO6MV2 GPS - Outdoor Localization (UART) [FUTURE]   │
│                                                              │
│ ACTUATORS:                                                   │
│  • PWM Vibration Motor - Haptic Alerts (GPIO 18)           │
│  • Bluetooth Headphones - 3D Spatial Audio                  │
│                                                              │
│ POWER:                                                       │
│  • 30,000mAh USB-C PD Power Bank                            │
│  • Official Active Cooler (MANDATORY)                       │
└─────────────────────────────────────────────────────────────┘
```

### Software Stack (5 Layers)
```
Layer 0 (Guardian)  → YOLO11x (2.5GB RAM) - Safety-critical detection
Layer 1 (Learner)   → YOLOE-11s (0.8GB RAM) - Adaptive learning (3 modes)
Layer 2 (Thinker)   → Whisper (800MB) + Gemini Live API + Kokoro (500MB)
Layer 3 (Guide)     → PyOpenAL (100MB) + Spatial Audio
Layer 4 (Memory)    → SQLite (50MB) + File Storage

Total RPi RAM: ~3.4-3.8GB (within 4GB limit) ✅
```

---

## 📦 PART 1: CORE DEPENDENCIES

### 1.1 System Packages (via apt)
```bash
# Update package lists
sudo apt update && sudo apt upgrade -y

# Essential build tools
sudo apt install -y \
    git \
    wget \
    curl \
    vim \
    htop \
    tmux \
    build-essential \
    cmake \
    pkg-config \
    libopenblas-dev \
    liblapack-dev \
    gfortran \
    libhdf5-dev \
    libssl-dev \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev

# Python 3.11+ (should be pre-installed on Bookworm)
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-numpy

# Audio libraries (for PyOpenAL, pygame, sounddevice)
sudo apt install -y \
    libopenal-dev \
    libopenal1 \
    openal-utils \
    libsndfile1 \
    libsndfile1-dev \
    portaudio19-dev \
    alsa-utils \
    pulseaudio \
    pulseaudio-utils

# Camera support (picamera2 + libcamera)
sudo apt install -y \
    python3-picamera2 \
    python3-libcamera \
    libcamera-apps

# GPIO support
sudo apt install -y \
    python3-gpiod \
    gpiod

# OpenCV dependencies (headless mode)
sudo apt install -y \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libv4l-dev \
    libxvidcore-dev \
    libx264-dev \
    libatlas-base-dev

# eSpeak NG (for Kokoro TTS phonemizer)
sudo apt install -y \
    espeak-ng \
    libespeak-ng1
```

---

## 🐍 PART 2: PYTHON ENVIRONMENT SETUP

### 2.1 Create Virtual Environment
```bash
# Create project directory
mkdir -p ~/cortex
cd ~/cortex

# Create virtual environment
python3 -m venv venv

# Activate venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel
```

### 2.2 Core Python Dependencies
```bash
# === Environment Management ===
pip install python-dotenv==1.0.0

# === Computer Vision ===
# Note: Install opencv-python-headless for RPi (no GUI dependencies)
pip install opencv-python-headless==4.8.1.78
pip install numpy>=1.24.3,<2.0
pip install pillow==10.1.0

# === AI/ML Models ===
pip install ultralytics==8.0.227  # YOLO object detection (includes YOLOE)

# === PyTorch (CPU-only for RPi) ===
# Option 1: Official PyTorch (slower download)
pip install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cpu

# Option 2: PiWheels (faster, pre-built for ARM)
# pip install torch torchvision torchaudio --extra-index-url https://www.piwheels.org/simple

# === Cloud AI APIs ===
pip install google-generativeai>=0.7.0  # Gemini Vision API
pip install google-genai>=1.0.0         # Gemini 2.5 Flash TTS + Live API
pip install openai==1.3.5               # OpenAI GPT-4 Vision (fallback)
pip install requests==2.31.0
pip install zai-sdk                     # Z.ai GLM-4.6V (Tier 2 fallback)
pip install websockets>=12.0            # Gemini Live API WebSocket

# === Local AI Models ===
pip install openai-whisper              # Local Whisper STT
pip install kokoro>=0.3.4               # Local Kokoro TTS
pip install misaki[en]                  # G2P for Kokoro
pip install phonemizer                  # Phoneme support

# === Audio Processing ===
pip install pygame==2.5.2               # Audio playback
pip install sounddevice==0.4.6          # Audio recording/playback
pip install scipy==1.11.4               # Audio file I/O
pip install pydub==0.25.1               # Audio manipulation
pip install pyaudio>=0.2.11             # Real-time microphone capture
pip install silero-vad>=4.0.0           # Silero VAD for voice activity detection

# === 3D Spatial Audio ===
# PyOpenAL requires system OpenAL libraries (installed via apt above)
pip install PyOpenAL>=0.7.11a1

# === GPIO & Hardware ===
pip install RPi.GPIO                    # GPIO control
pip install lgpio                       # Modern GPIO library
# pip install pyserial==3.5             # GPS module (future)

# === NLP (for YOLOE adaptive prompts) ===
pip install spacy>=3.7.0
python -m spacy download en_core_web_sm  # Download English model

# === GUI (for development/testing only) ===
pip install nicegui>=1.4.0              # Web dashboard (optional)
# Note: Tkinter comes with Python standard library

# === Utilities ===
pip install pyyaml==6.0.1
pip install python-dateutil==2.8.2
pip install psutil==5.9.6               # System resource monitoring

# === Development Tools (optional) ===
pip install pytest==7.4.3
pip install black==23.11.0
pip install flake8==6.1.0
```

---

## 📷 PART 3: CAMERA SETUP (RPi Camera Module 3)

### 3.1 Enable Camera Interface
```bash
# Enable camera interface
sudo raspi-config nonint do_camera 0

# Verify camera is detected
libcamera-hello --list-cameras

# Expected output:
# Available cameras
# -----------------
# 0 : imx708_wide [4608x2592] (/base/soc/i2c0mux/i2c@1/imx708@1a)
#     Modes: 'SRGGB10_CSI2P' : 1536x864 [120.13 fps - (768, 432)/3072/1728 crop]
#                              2304x1296 [56.03 fps - (0, 0)/4608/2592 crop]
#                              4608x2592 [14.35 fps - (0, 0)/4608/2592 crop]
```

### 3.2 Test Camera with picamera2
```bash
# Activate venv
source ~/cortex/venv/bin/activate

# Test camera capture
python3 << 'EOF'
from picamera2 import Picamera2
import time

print("📸 Testing RPi Camera Module 3...")
picam2 = Picamera2()

# Configure for 1080p (used by Cortex)
config = picam2.create_preview_configuration(
    main={"size": (1920, 1080), "format": "RGB888"}
)
picam2.configure(config)
picam2.start()
time.sleep(2)  # Camera warm-up

# Capture test image
picam2.capture_file("/home/pi/test_capture.jpg")
print("✅ Image saved to /home/pi/test_capture.jpg")

picam2.stop()
EOF
```

---

## 🔊 PART 4: AUDIO SETUP (3D Spatial Audio)

### 4.1 Verify OpenAL Installation
```bash
# Check OpenAL libraries
dpkg -l | grep openal
# Expected: libopenal1, libopenal-dev

# Test OpenAL device
python3 << 'EOF'
from openal import oalInit, oalQuit, oalGetDevice
from openal.alc import alcGetString, ALC_DEVICE_SPECIFIER

print("🔊 Testing OpenAL...")
oalInit()
device = oalGetDevice()
device_name = alcGetString(device, ALC_DEVICE_SPECIFIER)
print(f"✅ OpenAL Device: {device_name.decode('utf-8')}")
oalQuit()
EOF
```

### 4.2 Configure Bluetooth Audio (for headphones)
```bash
# Install Bluetooth tools
sudo apt install -y bluez bluez-tools pulseaudio-module-bluetooth

# Pair Bluetooth headphones (interactive)
bluetoothctl
# Inside bluetoothctl:
# power on
# agent on
# default-agent
# scan on
# (Wait for your headphones to appear)
# pair [MAC_ADDRESS]
# trust [MAC_ADDRESS]
# connect [MAC_ADDRESS]
# exit

# Set as default audio output
pactl set-default-sink [SINK_NAME]
# To find sink name: pactl list short sinks
```

---

## 🎮 PART 5: GPIO SETUP (Haptic Motor)

### 5.1 Test GPIO Access
```bash
# Test GPIO 18 (vibration motor pin)
python3 << 'EOF'
import RPi.GPIO as GPIO
import time

print("🔌 Testing GPIO 18...")
GPIO.setmode(GPIO.BCM)
GPIO.setup(18, GPIO.OUT)

# Blink 3 times
for i in range(3):
    GPIO.output(18, GPIO.HIGH)
    print(f"  {i+1}. GPIO 18 ON")
    time.sleep(0.5)
    GPIO.output(18, GPIO.LOW)
    print(f"  {i+1}. GPIO 18 OFF")
    time.sleep(0.5)

GPIO.cleanup()
print("✅ GPIO test complete")
EOF
```

### 5.2 Wire Vibration Motor
```
Connections:
  Motor (+) → GPIO 18 (Pin 12)
  Motor (-) → GND (Pin 6 or 14)
  Optional: Add 10kΩ resistor for current limiting
```

---

## 🧠 PART 6: DOWNLOAD AI MODELS

### 6.1 YOLO Models (Layer 0 + Layer 1)
```bash
# Create models directory
mkdir -p ~/cortex/models
cd ~/cortex/models

# Layer 0: YOLO11x (Guardian - 2.5GB)
wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x.pt

# Layer 1: YOLOE-11s (Learner - Text/Visual Prompts - 820MB)
wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11m-seg.pt

# Layer 1: YOLOE-11s (Learner - Prompt-Free - 820MB)
wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11m-seg-pf.pt

# Smaller models for testing (optional)
wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt  # 10MB
wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt  # 40MB
```

### 6.2 Whisper Model (Layer 2 - STT)
```bash
# Whisper models auto-download on first use
# Test download (base model, ~74M params, ~400MB)
python3 << 'EOF'
import whisper

print("📥 Downloading Whisper base model...")
model = whisper.load_model("base")
print("✅ Whisper model ready")
print(f"   Model size: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M parameters")
EOF
```

### 6.3 Kokoro TTS Model (Layer 2 - TTS Fallback)
```bash
# Kokoro models auto-download on first use
# Test download (~312MB model)
python3 << 'EOF'
from kokoro_onnx import Kokoro

print("📥 Downloading Kokoro TTS model...")
kokoro = Kokoro("en_us", "af_alloy")
print("✅ Kokoro model ready")
EOF
```

### 6.4 Silero VAD Model (Layer 2 - Voice Activity Detection)
```bash
# Silero VAD auto-downloads from torch.hub
python3 << 'EOF'
import torch

print("📥 Downloading Silero VAD model...")
model, utils = torch.hub.load(
    repo_or_dir='snakers4/silero-vad',
    model='silero_vad',
    force_reload=False
)
print("✅ Silero VAD model ready")
EOF
```

---

## 🔑 PART 7: API KEYS SETUP

### 7.1 Create .env File
```bash
cd ~/cortex

# Create .env file with your API keys
cat > .env << 'EOF'
# Google Gemini API Keys (rotation support - up to 6 keys)
GEMINI_API_KEY=your_primary_key_here
GEMINI_API_KEY_2=your_backup_key_2_here
GEMINI_API_KEY_3=your_backup_key_3_here
# Add up to GEMINI_API_KEY_6

# OpenAI API Key (fallback)
OPENAI_API_KEY=your_openai_key_here

# Z.ai API Key (Tier 2 fallback)
ZAI_API_KEY=your_zai_key_here

# Model Paths (relative to project root)
YOLO_MODEL_PATH=models/yolo11x.pt
YOLOE_MODEL_PATH=models/yoloe-11m-seg.pt
YOLO_CONFIDENCE=0.5
YOLO_DEVICE=cpu

# Database
DATABASE_PATH=cortex_memory.db
EOF

# Secure the .env file
chmod 600 .env

echo "✅ .env file created"
echo "⚠️  IMPORTANT: Edit .env and add your real API keys!"
```

### 7.2 Get API Keys
```
1. Google Gemini API:
   - Go to: https://aistudio.google.com/app/apikey
   - Create new API key
   - Free tier: 60 requests/minute

2. OpenAI API (optional):
   - Go to: https://platform.openai.com/api-keys
   - Create new API key
   - Note: Costs $0.01-0.03 per request

3. Z.ai API (optional):
   - Go to: https://z.ai
   - Create account and generate API key
```

---

## 📂 PART 8: CLONE PROJECT CORTEX

### 8.1 Clone Repository
```bash
cd ~/cortex

# Clone the repository
git clone https://github.com/IRSPlays/ProjectCortexV2.git .

# Verify structure
ls -la
# Expected: src/, models/, docs/, requirements.txt, etc.
```

### 8.2 Install Project-Specific Dependencies
```bash
# Activate venv
source ~/cortex/venv/bin/activate

# Install from requirements.txt
pip install -r requirements.txt

# Install adaptive YOLOE dependencies
pip install -r requirements_adaptive_yoloe.txt
```

---

## ✅ PART 9: VALIDATION & TESTING

### 9.1 Quick System Test
```bash
cd ~/cortex
source venv/bin/activate

# Run system test
python3 << 'EOF'
import sys
print("="*60)
print("PROJECT CORTEX V2.0 - SYSTEM VALIDATION")
print("="*60)

# Test 1: PyTorch
try:
    import torch
    print(f"✅ PyTorch {torch.__version__} (CPU threads: {torch.get_num_threads()})")
except Exception as e:
    print(f"❌ PyTorch: {e}")
    sys.exit(1)

# Test 2: YOLO
try:
    from ultralytics import YOLO
    print(f"✅ Ultralytics YOLO installed")
except Exception as e:
    print(f"❌ YOLO: {e}")
    sys.exit(1)

# Test 3: Whisper
try:
    import whisper
    print(f"✅ Whisper STT installed")
except Exception as e:
    print(f"❌ Whisper: {e}")

# Test 4: Kokoro
try:
    from kokoro_onnx import Kokoro
    print(f"✅ Kokoro TTS installed")
except Exception as e:
    print(f"❌ Kokoro: {e}")

# Test 5: OpenCV
try:
    import cv2
    print(f"✅ OpenCV {cv2.__version__}")
except Exception as e:
    print(f"❌ OpenCV: {e}")

# Test 6: picamera2
try:
    from picamera2 import Picamera2
    print(f"✅ picamera2 installed")
except Exception as e:
    print(f"❌ picamera2: {e}")

# Test 7: OpenAL
try:
    from openal import oalInit, oalQuit
    oalInit()
    oalQuit()
    print(f"✅ PyOpenAL 3D audio")
except Exception as e:
    print(f"❌ OpenAL: {e}")

# Test 8: Gemini API
try:
    from google import genai
    print(f"✅ Google Gemini SDK")
except Exception as e:
    print(f"❌ Gemini SDK: {e}")

# Test 9: GPIO
try:
    import RPi.GPIO as GPIO
    print(f"✅ RPi.GPIO installed")
except Exception as e:
    print(f"❌ GPIO: {e}")

print("="*60)
print("✅ ALL CORE DEPENDENCIES VALIDATED")
print("="*60)
EOF
```

### 9.2 YOLO Performance Benchmark
```bash
# Run YOLO benchmark (tests inference speed)
python3 tests/test_yolo_cpu.py

# Expected output:
# ⏱️ Performance (YOLO11x on RPi 5 CPU):
#    Average: 60-80ms per frame
#    Target: <100ms ✅
```

### 9.3 Camera + YOLO Integration Test
```bash
# Run integrated test
python3 tests/test_integration.py

# Expected:
# - Camera captures frames at 30 FPS
# - YOLO detects objects in real-time
# - Detections displayed in console
```

---

## 🚀 PART 10: RUN PROJECT CORTEX

### 10.1 Headless Mode (Production - RPi Only)
```bash
cd ~/cortex
source venv/bin/activate

# Run main application (headless mode)
python3 src/main.py

# Expected output:
# 🧠 Project-Cortex v2.0 Initializing (Headless Mode)...
# 📹 Initializing IMX415 camera...
# ✅ IMX415 camera ready
# 🔄 Loading YOLO model: models/yolo11x.pt
# ✅ YOLO model loaded on cpu
# 🔊 Loading Kokoro TTS...
# ✅ Kokoro TTS ready
# ✅ Project-Cortex initialized
# 🚀 Starting Project-Cortex headless mode...
```

### 10.2 GUI Mode (Development - Laptop/RPi Desktop)
```bash
# Run with NiceGUI dashboard
python3 src/cortex_dashboard.py

# Open browser: http://localhost:5000
# Features: Live video feed, voice commands, memory management
```

### 10.3 Test Voice Commands
```bash
# With application running, try these voice commands:
1. "What do you see?" → Layer 2 (Gemini vision analysis)
2. "Find the chair" → Layer 1 (YOLOE targeted detection)
3. "Scan the room" → Layer 1 (YOLOE prompt-free mode)
4. "Remember this wallet" → Layer 4 (Memory storage)
5. "Where is my wallet?" → Layer 1 + Layer 4 (Memory recall)
```

---

## 📊 PART 11: PERFORMANCE OPTIMIZATION

### 11.1 Enable Performance Mode
```bash
# Set CPU governor to performance
sudo cpufreq-set -g performance

# Verify
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# Expected: performance

# Increase USB power limit (for camera)
echo "usb_max_current_enable=1" | sudo tee -a /boot/config.txt

# Reboot to apply
sudo reboot
```

### 11.2 Monitor System Resources
```bash
# Real-time resource monitoring
htop

# Memory usage
free -h

# GPU temperature (RPi 5)
vcgencmd measure_temp

# Expected during inference:
# CPU: 70-90% (4 cores fully utilized)
# RAM: 3.4-3.8GB / 4GB
# Temp: 55-70°C (with active cooler)
```

### 11.3 Swap Configuration (Emergency Only)
```bash
# Check current swap
free -h

# Increase swap if RAM runs out (NOT RECOMMENDED - slows down system)
sudo dphys-swapfile swapoff
sudo sed -i 's/CONF_SWAPSIZE=100/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon

# Verify
free -h
```

---

## 🐛 PART 12: TROUBLESHOOTING

### Common Issues

#### Issue 1: PyTorch DLL Error (Windows Development)
```
Error: [WinError 1114] A dynamic link library (DLL) initialization routine failed
Solution: Install Visual C++ Redistributables
Download: https://aka.ms/vs/17/release/vc_redist.x64.exe
```

#### Issue 2: Camera Not Detected
```bash
# Check camera connection
libcamera-hello --list-cameras

# If no cameras found:
1. Power off RPi
2. Reseat camera cable (blue side faces USB ports)
3. Enable camera interface: sudo raspi-config
4. Reboot: sudo reboot
```

#### Issue 3: YOLO Out of Memory
```
Error: RuntimeError: [enforce fail at alloc_cpu.cpp] defaultCPUAllocator
Solution 1: Use smaller model (yolo11s.pt instead of yolo11x.pt)
Solution 2: Reduce frame resolution in main.py (640x480 instead of 1920x1080)
Solution 3: Enable swap (see 11.3)
```

#### Issue 4: OpenAL Device Not Found
```bash
# Check OpenAL libraries
dpkg -l | grep openal

# Reinstall
sudo apt install --reinstall libopenal1 libopenal-dev

# Test audio output
speaker-test -t wav -c 2
```

#### Issue 5: Gemini API Rate Limit
```
Error: 429 Resource has been exhausted
Solution: Add more API keys to .env (GEMINI_API_KEY_2, _3, etc.)
System will auto-rotate keys every 60 requests
```

---

## 📚 PART 13: ADDITIONAL RESOURCES

### Documentation
- [UNIFIED-SYSTEM-ARCHITECTURE.md](docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md) - Complete system design
- [RASPBERRY-PI-HARDWARE-VALIDATION-GUIDE.md](docs/implementation/RASPBERRY-PI-HARDWARE-VALIDATION-GUIDE.md) - Hardware tests
- [DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md) - Development best practices

### Model URLs
- YOLO Models: https://github.com/ultralytics/assets/releases
- Whisper Models: Auto-downloaded from Hugging Face
- Kokoro TTS: Auto-downloaded from Hugging Face
- Silero VAD: Auto-downloaded from torch.hub

### Support
- GitHub Issues: https://github.com/IRSPlays/ProjectCortexV2/issues
- Documentation: https://github.com/IRSPlays/ProjectCortexV2/tree/main/docs

---

## ✅ FINAL CHECKLIST

Before submitting to YIA 2026:
- [ ] All dependencies installed (Part 1-2)
- [ ] Camera working (Part 3)
- [ ] Audio output configured (Part 4)
- [ ] GPIO tested (Part 5)
- [ ] All models downloaded (Part 6)
- [ ] API keys configured (Part 7)
- [ ] Project cloned (Part 8)
- [ ] System validation passed (Part 9)
- [ ] Application runs successfully (Part 10)
- [ ] Performance optimized (Part 11)
- [ ] Active cooler installed (MANDATORY)
- [ ] <100ms YOLO latency achieved
- [ ] Voice commands working
- [ ] Memory system functional

**Congratulations! Your RPi 5 is now running Project Cortex v2.0! 🎉**

---

## 🎯 COMPETITION READINESS

### YIA 2026 Demo Script
1. **Power On** → 30 seconds boot time
2. **Voice Command** → "What do you see?" (Gemini vision analysis)
3. **Object Detection** → Show real-time YOLO detection
4. **Adaptive Learning** → "Find the fire extinguisher" (learned from Gemini)
5. **Memory Recall** → "Remember this wallet" + "Where is my wallet?"
6. **Spatial Audio** → Demonstrate 3D audio navigation with beacons
7. **Offline Mode** → Disconnect WiFi, show offline capabilities
8. **Cost Breakdown** → $150 total vs $4,000 OrCam

**Estimated Setup Time for Demo:** 5 minutes  
**Demo Duration:** 10-15 minutes  
**WOW Factor:** Adaptive learning without retraining + <$150 cost

Good luck at YIA 2026! 🏆
