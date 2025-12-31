# Project Cortex v2.0 - Quick Start Scripts

This directory contains automated scripts for Raspberry Pi 5 setup and validation.

## 📜 Available Scripts

### 1. `setup_rpi5.sh` - Complete Installation
**Purpose:** Automated installation of all Project Cortex dependencies on Raspberry Pi 5

**What it does:**
- ✅ Installs system packages (build tools, audio, camera, GPIO)
- ✅ Creates Python virtual environment
- ✅ Installs PyTorch (CPU-optimized for ARM)
- ✅ Installs all Python dependencies (YOLO, Whisper, Kokoro, etc.)
- ✅ Downloads AI models (YOLO11x, YOLOE, etc.)
- ✅ Clones Project Cortex repository
- ✅ Configures hardware (camera, GPIO, performance)
- ✅ Runs validation tests
- ✅ Creates .env template

**Usage:**
```bash
# Make executable
chmod +x setup_rpi5.sh

# Run (will take 2-3 hours)
./setup_rpi5.sh
```

**Requirements:**
- Raspberry Pi 5 (4GB RAM)
- Raspberry Pi OS Lite (64-bit) or Desktop (64-bit)
- Internet connection
- 10GB+ free disk space

---

### 2. `validate_hardware.sh` - Hardware Validation
**Purpose:** Verify all hardware components before running Project Cortex

**What it tests:**
- ✅ Raspberry Pi 5 detection
- ✅ RAM capacity (need 4GB)
- ✅ Disk space (need 10GB+)
- ✅ Temperature & cooling (active cooler)
- ✅ Camera Module 3 connectivity
- ✅ GPIO access
- ✅ Audio output (ALSA, PulseAudio, OpenAL)
- ✅ Bluetooth (for headphones)
- ✅ USB power configuration
- ✅ Python 3.11+ environment

**Usage:**
```bash
# Make executable
chmod +x validate_hardware.sh

# Run (takes ~30 seconds)
./validate_hardware.sh
```

**Output Example:**
```
✅ PASS: Detected: Raspberry Pi 5 Model B Rev 1.0
✅ PASS: RAM capacity sufficient (3.8GB)
✅ PASS: Temperature normal (48.5°C)
✅ PASS: Detected: Raspberry Pi Camera Module 3 (IMX708)
✅ PASS: GPIO device found
✅ PASS: OpenAL library installed

========================================
VALIDATION SUMMARY
========================================
Passed:   28
Warnings: 2
Failed:   0
Total:    30

✅ ALL TESTS PASSED - HARDWARE READY!
```

---

## 🚀 Recommended Workflow

### First-Time Setup on New Raspberry Pi:
```bash
# 1. Validate hardware first
./validate_hardware.sh

# 2. If validation passes, run full setup
./setup_rpi5.sh

# 3. After setup, edit .env with your API keys
nano ~/cortex/.env

# 4. Reboot to apply all changes
sudo reboot

# 5. After reboot, run Project Cortex
cd ~/cortex
python3 src/main.py
```

### Before Competition Demo:
```bash
# Run quick validation before demo
./validate_hardware.sh

# Check temperature is normal
vcgencmd measure_temp

# Test camera
libcamera-hello --list-cameras

# Verify models are downloaded
ls -lh ~/cortex/models/
```

---

## 🐛 Troubleshooting

### Script Permission Denied
```bash
# Make scripts executable
chmod +x setup_rpi5.sh
chmod +x validate_hardware.sh
```

### Setup Script Fails Mid-Way
```bash
# Check error message, then re-run
# Script is idempotent (safe to re-run)
./setup_rpi5.sh
```

### Validation Shows Warnings
- **Temperature > 60°C**: Ensure active cooler is installed and running
- **Low disk space**: Delete unnecessary files or use larger SD card
- **Camera not detected**: Reseat camera cable (blue side faces USB ports)
- **GPIO access denied**: Add user to gpio group: `sudo usermod -aG gpio $USER`

---

## 📚 Additional Resources

- **Full Setup Guide**: [docs/implementation/RPI5-COMPLETE-SETUP-GUIDE.md](../docs/implementation/RPI5-COMPLETE-SETUP-GUIDE.md)
- **Hardware Validation Guide**: [docs/implementation/RASPBERRY-PI-HARDWARE-VALIDATION-GUIDE.md](../docs/implementation/RASPBERRY-PI-HARDWARE-VALIDATION-GUIDE.md)
- **System Architecture**: [docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md](../docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md)

---

## 🎯 Competition Readiness Checklist

Before YIA 2026 demo:
- [ ] Run `validate_hardware.sh` - all tests pass
- [ ] Active cooler installed and running (<60°C)
- [ ] Camera Module 3 detected (IMX708)
- [ ] All models downloaded (YOLO11x, YOLOE)
- [ ] API keys configured in .env
- [ ] Bluetooth headphones paired
- [ ] Battery pack fully charged (30,000mAh)
- [ ] Demo script practiced (10-15 min)
- [ ] Backup SD card prepared

**Good luck at YIA 2026! 🏆**
