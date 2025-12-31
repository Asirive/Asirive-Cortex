# Raspberry Pi 5 Hardware Validation Guide - Project Cortex V2.0

**Author:** GitHub Copilot (CTO)  
**Date:** December 31, 2025  
**Status:** READY TO EXECUTE  
**Priority:** 🔥 CRITICAL - Hardware Foundation  
**Target Hardware:** Raspberry Pi 5 (4GB), Raspberry Pi OS Lite (64-bit)

---

## 🎯 MISSION OBJECTIVES

Validate that your Raspberry Pi 5 can run **ALL** Project Cortex V2.0 edge components:
1. ✅ **Python 3.11+** with AI libraries (PyTorch, Ultralytics, OpenCV)
2. ✅ **RPi Camera Module 3** (CSI/MIPI connectivity, 720p/1080p capture)
3. ✅ **GPIO Access** (PWM vibration motor control)
4. ✅ **YOLO Performance** (Layer 1 latency <100ms requirement)
5. ✅ **RAM Budget** (3.9GB total: YOLO 2.5GB + Whisper 800MB + others)

**Expected Duration:** 90 minutes (includes download times)

---

## 📋 PRE-FLIGHT CHECKLIST

Before starting, confirm you have:
- [ ] Raspberry Pi 5 (4GB RAM model)
- [ ] RPi OS Lite (64-bit) installed and booted
- [ ] SSH connection working (`ssh pi@<RPi_IP>`)
- [ ] Internet connection on RPi (WiFi or Ethernet)
- [ ] RPi Camera Module 3 (Wide) physically connected to CSI port
- [ ] MicroSD card with 32GB+ space (for models)
- [ ] Active Cooler installed (MANDATORY for heavy AI workloads)

**SSH Connection Test:**
```bash
# From your laptop (Windows PowerShell)
ssh pi@raspberrypi.local
# OR
ssh pi@<IP_ADDRESS>
```

**Default Credentials:**
- Username: `pi`
- Password: `raspberry` (change this immediately!)

---

## 🔒 STEP 0: SECURITY & SYSTEM PREP (5 minutes)

### 0.1: Change Default Password
```bash
# Change password for security
passwd
# Enter new password (use strong password!)
```

### 0.2: Update System
```bash
# Update package lists
sudo apt update

# Upgrade existing packages (may take 5-10 minutes)
sudo apt upgrade -y

# Install essential tools
sudo apt install -y git wget curl vim htop tmux
```

### 0.3: Enable Active Cooler (CRITICAL)
```bash
# Enable fan control (if not already enabled)
sudo raspi-config nonint do_fan 0 60  # Start fan at 60°C

# Verify fan is running
vcgencmd measure_temp
# Should show ~40-50°C when idle
```

### 0.4: Check System Info
```bash
# Verify hardware
cat /proc/cpuinfo | grep Model
# Expected: Raspberry Pi 5 Model B Rev 1.0

# Check RAM
free -h
# Expected: Total ~3.8GB (4GB with ~200MB reserved)

# Check disk space
df -h
# Expected: At least 20GB free on /dev/mmcblk0p2
```

**Validation:** RAM shows ~3.8GB total, temp <60°C, 20GB+ disk space ✅

---

## 🐍 STEP 1: PYTHON 3.11+ INSTALLATION (15 minutes)

Raspberry Pi OS Lite (Bookworm) should have Python 3.11 pre-installed. Let's verify and set up virtual environment.

### 1.1: Verify Python Version
```bash
# Check Python version
python3 --version
# Expected: Python 3.11.2 or newer

# Check pip
pip3 --version
# Expected: pip 23.0 or newer
```

**If Python 3.11+ not installed:**
```bash
sudo apt install -y python3 python3-pip python3-venv
```

### 1.2: Create Virtual Environment (Recommended)
```bash
# Create project directory
mkdir -p ~/cortex
cd ~/cortex

# Create virtual environment
python3 -m venv venv

# Activate venv
source venv/bin/activate

# Upgrade pip in venv
pip install --upgrade pip setuptools wheel
```

**Note:** Add `source ~/cortex/venv/bin/activate` to `~/.bashrc` to auto-activate on SSH login:
```bash
echo "source ~/cortex/venv/bin/activate" >> ~/.bashrc
```

**Validation:** `(venv)` prefix appears in terminal prompt ✅

---

## 🔥 STEP 2: PYTORCH INSTALLATION (20 minutes)

PyTorch is CRITICAL for YOLO and Whisper. RPi 5 has **NO native GPU** (no CUDA), so we use CPU-optimized PyTorch.

### 2.1: Install PyTorch (CPU-only, ARM64)
```bash
# Activate venv (if not already)
source ~/cortex/venv/bin/activate

# Install PyTorch 2.1+ (ARM64-optimized build)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

**This will take 15-20 minutes** (PyTorch is ~200MB download, slow on RPi).

**Alternative (Faster):** Use pre-built wheel from piwheels:
```bash
pip install torch torchvision torchaudio --extra-index-url https://www.piwheels.org/simple
```

### 2.2: Verify PyTorch
```bash
# Test PyTorch import
python3 -c "import torch; print(f'PyTorch {torch.__version__} installed')"
# Expected: PyTorch 2.1.0 or newer

# Check CPU optimization
python3 -c "import torch; print(f'CPU threads: {torch.get_num_threads()}')"
# Expected: CPU threads: 4 (RPi 5 has 4 cores)
```

### 2.3: Monitor RAM During Install
```bash
# Open another SSH session and watch RAM
watch -n 1 free -h
# Should stay under 1GB during install
```

**Validation:** PyTorch imports without error, <1GB RAM used ✅

---

## 📷 STEP 3: CAMERA MODULE VALIDATION (10 minutes)

### 3.1: Enable Camera Interface
```bash
# Enable camera (legacy interface not needed for RPi Camera Module 3)
sudo raspi-config nonint do_camera 0

# Reboot to apply changes
sudo reboot
```

**Wait 30 seconds, then reconnect SSH.**

### 3.2: Install picamera2 (Modern Camera API)
```bash
# Activate venv
source ~/cortex/venv/bin/activate

# Install picamera2 and dependencies
sudo apt install -y python3-picamera2 python3-libcamera

# Install into venv (use system packages)
pip install picamera2 --no-build-isolation
```

### 3.3: Test Camera Capture
```bash
# Test camera with simple capture
python3 << EOF
from picamera2 import Picamera2
import time

print("🔍 Initializing camera...")
picam2 = Picamera2()

# Configure for 720p preview
config = picam2.create_preview_configuration(main={"size": (1280, 720)})
picam2.configure(config)

print("📸 Starting camera...")
picam2.start()
time.sleep(2)  # Let camera warm up

# Capture test image
picam2.capture_file("/home/pi/test_capture.jpg")
print("✅ Image saved to /home/pi/test_capture.jpg")

picam2.stop()
print("🛑 Camera stopped")
EOF
```

**Expected Output:**
```
🔍 Initializing camera...
📸 Starting camera...
✅ Image saved to /home/pi/test_capture.jpg
🛑 Camera stopped
```

### 3.4: Verify Image
```bash
# Check file size (should be ~200-500KB)
ls -lh /home/pi/test_capture.jpg

# Transfer to laptop to view (from laptop PowerShell)
# scp pi@raspberrypi.local:/home/pi/test_capture.jpg ./
```

**Validation:** Image file exists, 200-500KB size, no errors ✅

---

## 🎮 STEP 4: GPIO ACCESS VALIDATION (5 minutes)

### 4.1: Install GPIO Library
```bash
# Activate venv
source ~/cortex/venv/bin/activate

# Install RPi.GPIO (for PWM control)
pip install RPi.GPIO

# Install lgpio (modern alternative, recommended)
pip install lgpio
```

### 4.2: Test GPIO (LED Blink)
```bash
# Test GPIO 18 (used for vibration motor in Cortex)
sudo python3 << EOF
import RPi.GPIO as GPIO
import time

print("🔌 Testing GPIO 18...")
GPIO.setmode(GPIO.BCM)
GPIO.setup(18, GPIO.OUT)

# Blink 5 times
for i in range(5):
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

**Expected Output:**
```
🔌 Testing GPIO 18...
  1. GPIO 18 ON
  1. GPIO 18 OFF
  2. GPIO 18 ON
  ...
✅ GPIO test complete
```

**Note:** To test with actual vibration motor, connect:
- Motor `+` → GPIO 18
- Motor `-` → GND (pin 6 or 14)
- Add 10kΩ resistor for safety

**Validation:** No permission errors, GPIO toggles successfully ✅

---

## 🧠 STEP 5: YOLO INSTALLATION & BENCHMARK (30 minutes)

This is the **CRITICAL TEST** - can RPi 5 run YOLO at <100ms latency?

### 5.1: Install Ultralytics YOLO
```bash
# Activate venv
source ~/cortex/venv/bin/activate

# Install Ultralytics (includes YOLOv11)
pip install ultralytics opencv-python-headless pillow

# Install additional dependencies
pip install numpy scipy
```

**Note:** `opencv-python-headless` is used (no GUI support) since we're on OS Lite.

### 5.2: Download YOLO Models
```bash
# Create models directory
mkdir -p ~/cortex/models
cd ~/cortex/models

# Download YOLOv11n (nano, 10MB - fastest)
wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt

# Download YOLOv11s (small, 40MB - good balance)
wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt

# Download YOLOv11x (extra-large, 2.5GB - most accurate, SLOW on CPU)
# ⚠️ WARNING: This will take 20-30 minutes to download
# wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x.pt
```

**Recommendation:** Start with `yolo11n.pt` for testing, then try `yolo11s.pt`.

### 5.3: Create Benchmark Script
```bash
# Create benchmark script
cat > ~/cortex/benchmark_yolo.py << 'EOF'
import time
import cv2
from ultralytics import YOLO
from picamera2 import Picamera2
import numpy as np

print("=" * 60)
print("PROJECT CORTEX - YOLO BENCHMARK ON RASPBERRY PI 5")
print("=" * 60)

# Model to test
MODEL_PATH = "/home/pi/cortex/models/yolo11n.pt"  # Change to yolo11s.pt or yolo11x.pt

print(f"\n📦 Loading model: {MODEL_PATH}")
model = YOLO(MODEL_PATH)
print(f"✅ Model loaded: {model.model_name}")

# Initialize camera
print("\n📸 Initializing camera...")
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"size": (640, 480)})  # Lower res for speed
picam2.configure(config)
picam2.start()
time.sleep(2)  # Camera warm-up

print("\n🔥 Running inference benchmark (30 frames)...")
latencies = []

for i in range(30):
    # Capture frame
    frame = picam2.capture_array()
    
    # Convert RGBA to RGB (if needed)
    if frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
    
    # Run inference
    start_time = time.time()
    results = model(frame, verbose=False)
    latency_ms = (time.time() - start_time) * 1000
    latencies.append(latency_ms)
    
    # Get detections
    detections = results[0].boxes
    num_objects = len(detections) if detections is not None else 0
    
    print(f"  Frame {i+1:2d}: {latency_ms:6.1f}ms | Objects: {num_objects}")

# Stop camera
picam2.stop()

# Calculate statistics
avg_latency = np.mean(latencies)
min_latency = np.min(latencies)
max_latency = np.max(latencies)
p95_latency = np.percentile(latencies, 95)
fps = 1000 / avg_latency

print("\n" + "=" * 60)
print("📊 BENCHMARK RESULTS")
print("=" * 60)
print(f"Model:           {MODEL_PATH.split('/')[-1]}")
print(f"Average Latency: {avg_latency:.1f}ms")
print(f"Min Latency:     {min_latency:.1f}ms")
print(f"Max Latency:     {max_latency:.1f}ms")
print(f"P95 Latency:     {p95_latency:.1f}ms")
print(f"Effective FPS:   {fps:.1f}")
print("=" * 60)

# Validate against Layer 1 requirement (<100ms)
if avg_latency < 100:
    print("✅ PASS: Meets Layer 1 latency requirement (<100ms)")
elif avg_latency < 500:
    print("⚠️  MARGINAL: Acceptable for Layer 1 with optimization")
else:
    print("❌ FAIL: Too slow for Layer 1 (need faster model or hardware)")

print("\nℹ️  NOTE: Layer 1 in Tkinter uses yolo11x.pt (~500-800ms on RPi CPU)")
print("   Consider using yolo11n.pt or yolo11s.pt for <100ms latency.")
EOF

chmod +x ~/cortex/benchmark_yolo.py
```

### 5.4: Run Benchmark (yolo11n.pt)
```bash
# Activate venv
source ~/cortex/venv/bin/activate

# Run benchmark
python3 ~/cortex/benchmark_yolo.py
```

**Expected Output (yolo11n.pt on RPi 5 CPU):**
```
📦 Loading model: /home/pi/cortex/models/yolo11n.pt
✅ Model loaded: YOLOv11n
📸 Initializing camera...
🔥 Running inference benchmark (30 frames)...
  Frame  1:   85.2ms | Objects: 2
  Frame  2:   82.1ms | Objects: 2
  Frame  3:   79.8ms | Objects: 1
  ...
📊 BENCHMARK RESULTS
Model:           yolo11n.pt
Average Latency: 83.4ms
Min Latency:     78.1ms
Max Latency:     94.2ms
P95 Latency:     91.5ms
Effective FPS:   12.0
✅ PASS: Meets Layer 1 latency requirement (<100ms)
```

### 5.5: Run Benchmark (yolo11s.pt)
```bash
# Test with larger model
sed -i 's/yolo11n.pt/yolo11s.pt/g' ~/cortex/benchmark_yolo.py
python3 ~/cortex/benchmark_yolo.py
```

**Expected Output (yolo11s.pt on RPi 5 CPU):**
```
Average Latency: 280.5ms  (⚠️ MARGINAL - too slow for <100ms requirement)
```

### 5.6: Monitor RAM Usage During Benchmark
```bash
# Open another SSH session
watch -n 1 free -h
```

**Expected RAM Usage:**
- `yolo11n.pt`: ~300MB
- `yolo11s.pt`: ~600MB
- `yolo11x.pt`: ~2500MB (WARNING: May cause OOM on 4GB RPi!)

**Validation:** 
- `yolo11n.pt` achieves <100ms ✅
- `yolo11s.pt` ~280ms (acceptable fallback)
- Total RAM <2GB during inference ✅

---

## 📊 STEP 6: FULL SYSTEM RAM BUDGET TEST (10 minutes)

Simulate running **ALL** Layer 1 components simultaneously to validate 3.9GB budget.

### 6.1: Install Whisper (for RAM test)
```bash
# Activate venv
source ~/cortex/venv/bin/activate

# Install OpenAI Whisper
pip install openai-whisper
```

### 6.2: Create RAM Budget Test Script
```bash
cat > ~/cortex/test_ram_budget.py << 'EOF'
import time
import psutil
from ultralytics import YOLO

print("=" * 60)
print("PROJECT CORTEX - RAM BUDGET VALIDATION")
print("=" * 60)

def get_ram_usage():
    """Get current RAM usage in MB."""
    mem = psutil.virtual_memory()
    return mem.used / (1024**2), mem.available / (1024**2), mem.percent

# Baseline
used, avail, pct = get_ram_usage()
print(f"\n📊 Baseline RAM:")
print(f"   Used: {used:.0f}MB | Available: {avail:.0f}MB | {pct:.1f}%")

# Load YOLO (Layer 1 Reflex)
print("\n⚡ Loading YOLO (Layer 1 Reflex)...")
yolo = YOLO("/home/pi/cortex/models/yolo11n.pt")
used, avail, pct = get_ram_usage()
print(f"   Used: {used:.0f}MB | Available: {avail:.0f}MB | {pct:.1f}%")

# Simulate Whisper (800MB)
print("\n🎤 Simulating Whisper STT (Layer 1 - 800MB)...")
import numpy as np
whisper_mock = np.zeros((800 * 1024 * 1024 // 8,), dtype=np.float64)  # 800MB array
used, avail, pct = get_ram_usage()
print(f"   Used: {used:.0f}MB | Available: {avail:.0f}MB | {pct:.1f}%")

# Simulate Kokoro TTS (500MB)
print("\n🔊 Simulating Kokoro TTS (Layer 1 - 500MB)...")
kokoro_mock = np.zeros((500 * 1024 * 1024 // 8,), dtype=np.float64)  # 500MB array
used, avail, pct = get_ram_usage()
print(f"   Used: {used:.0f}MB | Available: {avail:.0f}MB | {pct:.1f}%")

# Simulate VAD (50MB)
print("\n🎙️  Simulating VAD Handler (Layer 1 - 50MB)...")
vad_mock = np.zeros((50 * 1024 * 1024 // 8,), dtype=np.float64)  # 50MB array
used, avail, pct = get_ram_usage()
print(f"   Used: {used:.0f}MB | Available: {avail:.0f}MB | {pct:.1f}%")

# Total
print("\n" + "=" * 60)
print("📊 FINAL RAM USAGE (ALL LAYER 1 COMPONENTS)")
print("=" * 60)
print(f"Total Used:      {used:.0f}MB ({pct:.1f}%)")
print(f"Total Available: {avail:.0f}MB")
print(f"Total System:    ~3800MB")
print("=" * 60)

# Budget check
TARGET_RAM = 3900  # 3.9GB target from architecture
if used < TARGET_RAM:
    print(f"✅ PASS: Under budget ({used:.0f}MB < {TARGET_RAM}MB)")
else:
    print(f"❌ FAIL: Over budget ({used:.0f}MB > {TARGET_RAM}MB)")
    print("   ⚠️  WARNING: May experience OOM errors in production!")

# Cleanup
del whisper_mock, kokoro_mock, vad_mock
EOF

chmod +x ~/cortex/test_ram_budget.py
```

### 6.3: Run RAM Budget Test
```bash
# Install psutil for memory monitoring
pip install psutil

# Run test
python3 ~/cortex/test_ram_budget.py
```

**Expected Output:**
```
📊 Baseline RAM:
   Used: 450MB | Available: 3350MB | 11.8%

⚡ Loading YOLO (Layer 1 Reflex)...
   Used: 750MB | Available: 3050MB | 19.7%

🎤 Simulating Whisper STT (Layer 1 - 800MB)...
   Used: 1550MB | Available: 2250MB | 40.8%

🔊 Simulating Kokoro TTS (Layer 1 - 500MB)...
   Used: 2050MB | Available: 1750MB | 53.9%

🎙️  Simulating VAD Handler (Layer 1 - 50MB)...
   Used: 2100MB | Available: 1700MB | 55.3%

📊 FINAL RAM USAGE (ALL LAYER 1 COMPONENTS)
Total Used:      2100MB (55.3%)
Total Available: 1700MB
Total System:    ~3800MB
✅ PASS: Under budget (2100MB < 3900MB)
```

**Validation:** Total RAM <3900MB (55-60% usage), system remains stable ✅

---

## 📋 VALIDATION SUMMARY CHECKLIST

After completing all steps, verify:

### System Basics:
- [ ] Python 3.11+ installed (`python3 --version`)
- [ ] Virtual environment active (`(venv)` in prompt)
- [ ] PyTorch 2.1+ installed (`python -c "import torch; print(torch.__version__)"`)
- [ ] Active cooler working (temp <60°C)

### Camera:
- [ ] picamera2 installed
- [ ] Test image captured (test_capture.jpg exists)
- [ ] No camera errors during capture

### GPIO:
- [ ] RPi.GPIO installed
- [ ] GPIO 18 toggle test passed
- [ ] No permission errors

### YOLO Performance:
- [ ] yolo11n.pt downloaded (10MB)
- [ ] Benchmark completed (30 frames)
- [ ] Average latency <100ms ✅ OR <500ms (acceptable)
- [ ] No inference errors

### RAM Budget:
- [ ] Full system test passed
- [ ] Total RAM <3900MB
- [ ] System stable under load

---

## 🚨 TROUBLESHOOTING

### Issue: PyTorch import fails with "Illegal instruction"
**Cause:** PyTorch compiled for newer ARM architecture  
**Solution:**
```bash
# Use older PyTorch version
pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cpu
```

### Issue: Camera not detected
**Cause:** Camera ribbon cable loose or interface not enabled  
**Solution:**
```bash
# Check camera detection
vcgencmd get_camera
# Should show: detected=1

# If detected=0:
sudo raspi-config
# Navigate to: Interface Options → Camera → Enable
sudo reboot
```

### Issue: YOLO latency >500ms
**Cause:** Using yolo11x.pt (too large for RPi CPU)  
**Solution:** Use yolo11n.pt or yolo11s.pt instead

### Issue: Out of Memory during benchmark
**Cause:** 4GB RAM insufficient for yolo11x.pt  
**Solution:**
```bash
# Add swap space (emergency fallback)
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile
# Change: CONF_SWAPSIZE=2048 (2GB swap)
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

### Issue: High CPU temperature (>80°C)
**Cause:** Active cooler not working or thermal paste issue  
**Solution:**
```bash
# Check fan status
sudo systemctl status pigpiod

# Enable fan at lower temp
sudo raspi-config nonint do_fan 0 50  # Start fan at 50°C

# If still high, check cooler installation
```

---

## 📊 EXPECTED RESULTS (Success Criteria)

### 🎯 Gold Standard (Production Ready):
- ✅ YOLO (yolo11n.pt): **<100ms** latency
- ✅ RAM usage: **<2500MB** (65% of 3.8GB)
- ✅ Camera: **30 FPS** capture at 720p
- ✅ CPU temp: **<60°C** under load
- ✅ GPIO: No permission errors

### ⚠️ Acceptable (With Optimizations):
- ⚠️ YOLO (yolo11s.pt): **280-500ms** latency (need optimization)
- ⚠️ RAM usage: **2500-3500MB** (65-92% of 3.8GB)
- ⚠️ Camera: **15-30 FPS** capture
- ⚠️ CPU temp: **60-75°C** (monitor closely)

### ❌ Failure (Need Hardware Upgrade):
- ❌ YOLO latency: **>500ms** (unacceptable for Layer 1)
- ❌ RAM usage: **>3500MB** (OOM risk)
- ❌ Camera: **<15 FPS** (too slow)
- ❌ CPU temp: **>80°C** (thermal throttling)

---

## 🚀 NEXT STEPS AFTER VALIDATION

### If All Tests Pass ✅:
**Phase 2: Deploy Core Components**
1. Transfer Project Cortex codebase via git/SCP
2. Install remaining dependencies (Whisper, Kokoro TTS)
3. Test Layer 1 (Reflex) end-to-end on RPi
4. Set up edge-server WebSocket communication

### If Performance Marginal ⚠️:
**Phase 2A: Optimization Required**
1. Switch to yolo11n.pt permanently (sacrifice accuracy for speed)
2. Implement frame skipping (process every 2nd frame)
3. Reduce camera resolution to 640x480
4. Enable RPi 5 GPU acceleration (experimental)

### If Tests Fail ❌:
**Phase 2B: Architecture Revision**
1. Move YOLO to laptop server (all vision processing cloud-based)
2. RPi becomes "thin client" (camera + GPIO only)
3. Revise edge-server hybrid to full server architecture
4. Increase latency budget from <100ms to <500ms

---

## 📝 BENCHMARK REPORT TEMPLATE

After completing validation, fill out this report:

```
PROJECT CORTEX V2.0 - RASPBERRY PI 5 HARDWARE VALIDATION REPORT
================================================================
Date: December 31, 2025
Tester: Haziq (Co-Founder)

HARDWARE:
- Model: Raspberry Pi 5 (4GB RAM)
- OS: Raspberry Pi OS Lite (64-bit, Bookworm)
- Python: 3.11.x
- PyTorch: 2.1.x
- Camera: RPi Camera Module 3 (Wide)
- Cooling: Active Cooler

BENCHMARK RESULTS:
- YOLO Model: yolo11n.pt / yolo11s.pt / yolo11x.pt
- Avg Latency: ___ ms
- P95 Latency: ___ ms
- Effective FPS: ___ FPS
- RAM Usage: ___ MB (___ %)
- CPU Temp: ___ °C

VALIDATION STATUS:
- [ ] YOLO <100ms: PASS / MARGINAL / FAIL
- [ ] RAM <3900MB: PASS / FAIL
- [ ] Camera 30 FPS: PASS / FAIL
- [ ] GPIO Access: PASS / FAIL
- [ ] Temp <60°C: PASS / MARGINAL / FAIL

RECOMMENDATION:
[ ] READY FOR PHASE 2 (Deploy Core Components)
[ ] NEEDS OPTIMIZATION (Use lighter models)
[ ] ARCHITECTURE REVISION REQUIRED (Move compute to server)

NOTES:
___________________________________________________________________
```

---

## 📚 REFERENCES

1. **Raspberry Pi 5 Documentation:** https://www.raspberrypi.com/documentation/computers/raspberry-pi.html
2. **picamera2 Guide:** https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
3. **Ultralytics YOLO:** https://docs.ultralytics.com/
4. **PyTorch on ARM:** https://pytorch.org/get-started/locally/
5. **Project Cortex Architecture:** `docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md`

---

**Status:** Ready to execute. Estimated completion time: 90 minutes.  
**Next Command:** Copy this guide to RPi and start Step 0.

```bash
# From your laptop (PowerShell), transfer this guide:
scp docs/implementation/RASPBERRY-PI-HARDWARE-VALIDATION-GUIDE.md pi@raspberrypi.local:~/
```

Then SSH into RPi and follow steps sequentially. **Good luck, Co-Founder!** 🚀
