# Project-Cortex v2.0
## AI-Powered Assistive Wearable for the Visually Impaired

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Raspberry Pi 5](https://img.shields.io/badge/Hardware-Raspberry%20Pi%205-red.svg)](https://www.raspberrypi.com/products/raspberry-pi-5/)

---

## 🎯 Project Mission

**Project-Cortex** is a low-cost (<$150), high-impact AI wearable designed to assist visually impaired individuals by providing real-time scene understanding, object detection, and audio navigation. Built for the **Young Innovators Awards (YIA) 2026** competition.

We aim to democratize assistive technology by disrupting the $4,000+ premium device market (OrCam, eSight) using commodity hardware and a novel "Hybrid AI" architecture.

---

## 🏗️ Architecture Overview: Hybrid-Edge Computing

**NEW in v2.0:** Server-assisted architecture for enterprise-grade navigation while maintaining edge safety guarantees.

### Hardware Platform

#### Edge Unit (Raspberry Pi 5 - Wearable)
- **Compute:** Raspberry Pi 5 (4GB RAM)
- **Vision:** Camera Module 3 (IMX708, 11.9MP)
- **Sensors:** BNO055 9-DOF IMU (head-tracking), GY-NEO6MV2 GPS
- **Haptics:** PWM Vibration Motor (GPIO 18)
- **Audio:** Bluetooth Headphones (low-latency codec)
- **Power:** 30,000mAh USB-C PD Power Bank
- **Cooling:** Official RPi 5 Active Cooler

#### Compute Node (Laptop - Development Server)
- **Role:** Heavy spatial computing (SLAM, VIO, pathfinding)
- **Specs:** Dell Inspiron 15 (RTX 2050 CUDA)
- **Communication:** WebSocket (8765) + REST API (8000)

### The "3-Layer Hybrid AI" Brain

#### Layer 1: The Reflex (On Pi - Local Inference)
- **Purpose:** Immediate physical safety (<100ms latency)
- **Model:** YOLOv8n (INT8 quantized for ARM CPU)
- **Output:** Direct GPIO → PWM Vibration Motor
- **Reliability:** 100% offline, zero network dependency
- **Location:** `src/layer1_reflex/`

#### Layer 2: The Thinker (Hybrid - 3-Tier Cascading Fallback) 🆕
- **Purpose:** Vision intelligence & conversation with 100% uptime
- **Architecture:** 3-tier cascading fallback system
  - **Tier 0 (Best):** Gemini Live API (WebSocket, <500ms latency)
  - **Tier 1 (Good):** Gemini 2.5 Flash TTS (HTTP, ~1-2s, 6-key rotation)
  - **Tier 2 (Backup):** GLM-4.6V Z.ai (HTTP, ~1-2s, final fallback)
- **Auto-Failover:** Automatic tier switching on quota exhaustion
- **Documentation:** See [CASCADING_FALLBACK_ARCHITECTURE.md](docs/implementation/CASCADING_FALLBACK_ARCHITECTURE.md)
- **I/O:** Microphone PCM + Camera → PCM Audio via Bluetooth
- **Latency:** ~500ms (includes Bluetooth)
- **Location:** `src/layer2_thinker/`

#### Layer 3: The Navigator (HYBRID: Server + Pi)
- **Server:** SLAM (ORB-SLAM3), VIO, A* pathfinding
- **Pi:** GPS/IMU fusion, 3D spatial audio rendering (PyOpenAL)
- **Communication:** WebSocket @ 10Hz (target waypoints)
- **Audio Priority:** Navigation pings auto-duck Gemini by -10dB
- **Location:** `src/layer3_guide/` (Pi), `server/` (Laptop)

---

## 📁 Repository Structure

```
ProjectCortex/
├── Version_1/                      # Archived ESP32-CAM implementation
│   ├── Docs/                      # v1.0 technical retrospective
│   └── Code/                      # v1.0 Python/Arduino code
├── models/                         # Shared AI models (YOLO variants)
├── TTS Model/                      # Piper TTS model files
├── src/                           # Version 2.0 source code
│   ├── layer1_reflex/             # Local object detection module
│   ├── layer2_thinker/            # Cloud AI integration module
│   ├── layer3_guide/              # Navigation & UI module
│   └── main.py                    # Application entry point
├── config/                         # Configuration files (.yaml, .json)
├── tests/                          # Unit and integration tests
├── docs/                           # Technical documentation
├── utils/                          # Helper scripts and tools
├── .env.example                    # Environment variables template
├── requirements.txt                # Python dependencies
└── README.md                       # This file
```

---

## 🚀 Quick Start

### Development Modes

**⚙️ Mode 1: Laptop-Assisted Development (Current Phase)**  
Develop and test the full system on your laptop while waiting for hardware.

**🤖 Mode 2: Raspberry Pi 5 Deployment (Future)**  
Deploy to wearable once parts arrive.

---

### Mode 1: Laptop Development Setup

#### Prerequisites
- **Laptop:** Windows 10/11, Python 3.11+, Git, Git LFS
- **GPU (Optional):** NVIDIA RTX/GTX for faster YOLO testing
- **Internet:** Required for Gemini API

#### Installation

1. **Clone the repository with Git LFS:**
   ```bash
   git clone https://github.com/IRSPlays/ProjectCortexV2.git
   cd ProjectCortexV2
   git lfs pull  # Download large model files
   ```

2. **Set up Python environment:**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Configure API keys:**
   ```bash
   copy .env.example .env
   notepad .env  # Add your GEMINI_API_KEY
   ```

4. **Test the GUI (Development Interface):**
   ```bash
   python src/cortex_gui.py
   ```
   - Uses USB webcam instead of Pi camera
   - Full 3-layer AI functionality
   - Voice activation with VAD
   - 3D spatial audio testing

5. **Run server components (Layer 3 - Future):**
   ```bash
   # When ready to test navigation
   python server/slam_engine.py  # Start SLAM server
   python server/pathfinder.py    # Start pathfinding API
   ```

---

### Mode 2: Raspberry Pi 5 Deployment

#### Prerequisites
- Raspberry Pi 5 (4GB RAM) with Raspberry Pi OS (64-bit Lite)
- Camera Module 3 (connected via CSI port)
- BNO055 IMU (I2C), GY-NEO6MV2 GPS (UART)
- Bluetooth headphones, vibration motor (GPIO 18)
- Active internet connection (Wi-Fi)

#### Installation

1. **Install system dependencies:**
   ```bash
   sudo apt update && sudo apt install -y \
     python3-pip python3-venv \
     libcamera-apps \
     i2c-tools \
     bluetooth bluez pulseaudio-module-bluetooth
   ```

2. **Enable hardware interfaces:**
   ```bash
   sudo raspi-config
   # Enable: Camera, I2C, Serial (GPS)
   ```

3. **Clone and setup:**
   ```bash
   git clone https://github.com/IRSPlays/ProjectCortexV2.git
   cd ProjectCortexV2
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   pip install picamera2  # RPi-specific
   ```

4. **Configure `.env` file:**
   ```bash
   cp .env.example .env
   nano .env  # Add GEMINI_API_KEY, SERVER_IP (laptop IP)
   ```

5. **Test camera:**
   ```bash
   libcamera-hello --camera 0  # Should show preview
   ```

6. **Run the headless application:**
   ```bash
   python src/main.py
   ```

---

## 🔧 Configuration

### Power Management
Add to `/boot/firmware/config.txt`:
```ini
usb_max_current_enable=1
dtoverlay=imx415
```

### Camera Settings
Configure in `config/camera.yaml`:
```yaml
resolution: [1920, 1080]
framerate: 30
format: RGB888
```

### AI Model Selection
Edit `config/models.yaml`:
```yaml
layer1:
  model: "models/yolo11s.pt"
  device: "cpu"  # Change to "cuda" if using Coral TPU
  confidence: 0.5
```

---

## 🔊 3D Spatial Audio Navigation System

Project-Cortex features a **binaural 3D spatial audio system** that helps visually impaired users navigate their environment using audio cues. This system converts YOLO object detections into positioned audio sources, creating an "audio map" of the surroundings.

### Features

| Feature | Description |
|---------|-------------|
| **Audio Beacons** | Continuous directional sounds that guide users to targets (e.g., "lead me to the door") |
| **Proximity Alerts** | Distance-based warnings that intensify as obstacles approach |
| **Object Tracking** | Real-time 3D audio sources for each detected object |
| **Distance Estimation** | Calculate real-world distance using known object sizes |
| **Object-Specific Sounds** | Distinct audio signatures for different object classes (car vs person vs chair) |
| **HRTF Support** | Head-Related Transfer Function for realistic binaural audio on headphones |

### How It Works

```
YOLO Detection → Position Calculator → OpenAL 3D Audio → Headphones
     │                   │                    │
     ▼                   ▼                    ▼
  [bbox]    →    [x, y, z coords]    →   [Binaural audio]
```

**Position Mapping Algorithm:**
- **X-axis (Left/Right):** Bbox horizontal center → audio pan
- **Y-axis (Up/Down):** Bbox vertical center → audio elevation  
- **Z-axis (Distance):** Bbox size → audio volume/distance

### Quick Start

```python
from src.layer3_guide.spatial_audio import SpatialAudioManager, Detection

# Initialize spatial audio
audio = SpatialAudioManager()
audio.start()

# Update with YOLO detections
detections = [
    Detection("chair_1", "chair", 0.92, (100, 200, 300, 600)),
    Detection("person_1", "person", 0.87, (1400, 100, 1800, 900)),
]
audio.update_detections(detections)

# Start navigation beacon to guide user
audio.start_beacon("chair")  # "Follow the sound to the chair"

# Stop when done
audio.stop()
```

### Configuration

Edit `config/spatial_audio.yaml` to customize:
- Distance thresholds for proximity alerts
- Object-specific sound mappings
- Ping rates and volumes for beacons
- Known object sizes for distance estimation

### Components

| Module | File | Purpose |
|--------|------|---------|
| `SpatialAudioManager` | `manager.py` | Central orchestrator for all spatial audio |
| `PositionCalculator` | `position_calculator.py` | YOLO bbox → 3D coordinates |
| `AudioBeacon` | `audio_beacon.py` | Navigation guidance pings |
| `ProximityAlertSystem` | `proximity_alert.py` | Distance-based warnings |
| `ObjectSoundMapper` | `object_sounds.py` | Object class → sound mapping |
| `ObjectTracker` | `object_tracker.py` | Multi-object audio management |

### Requirements

```bash
pip install PyOpenAL numpy PyYAML
```

**Linux/Raspberry Pi:**
```bash
sudo apt-get install libopenal-dev libopenal1
```

📖 **Full documentation:** [docs/SPATIAL_AUDIO_IMPLEMENTATION.md](docs/SPATIAL_AUDIO_IMPLEMENTATION.md)

---

## 🧪 Testing

Run unit tests:
```bash
pytest tests/ -v
```

Run integration tests (requires hardware):
```bash
pytest tests/integration/ --hardware
```

---

## 📊 Performance Benchmarks

| Metric | Target | Current Status |
|--------|--------|----------------|
| Layer 1 Latency | <100ms | TBD |
| Layer 2 Latency | <3s | TBD |
| Power Consumption | <20W avg | TBD |
| Battery Life | 6-8 hours | TBD |
| Object Detection Accuracy | >85% mAP | TBD |

---

## 🛠️ Development Roadmap

### Phase 1: Core Infrastructure (Current)
- [x] Repository restructure
- [ ] Camera integration with libcamera
- [ ] Layer 1 YOLO inference pipeline
- [ ] Layer 2 Gemini API integration
- [ ] Audio subsystem (TTS + STT)

### Phase 2: Feature Development
- [ ] GPS navigation module
- [x] 3D spatial audio engine ✅ **IMPLEMENTED**
- [ ] Caregiver web dashboard
- [ ] Power optimization

### Phase 3: YIA Preparation
- [ ] User testing & feedback
- [ ] Documentation for judges
- [ ] Prototype enclosure design
- [ ] Demonstration video

---

## 📚 Documentation

- **[Bill of Materials (BOM)](docs/BOM.md)** - Complete parts list with costs
- **[Architecture Deep Dive](docs/ARCHITECTURE.md)** - Technical design decisions
- **[API Reference](docs/API.md)** - Code documentation
- **[v1.0 Retrospective](Version_1/Docs/)** - Lessons learned from ESP32-CAM

---

## 🤝 Contributing

This is a competition prototype developed by **Haziq (@IRSPlays)**. For questions or collaboration inquiries, please open an issue.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🏆 Acknowledgments

- **YIA 2026 Organizers** - For the opportunity to innovate
- **Raspberry Pi Foundation** - For affordable, powerful compute
- **Ultralytics** - For accessible YOLO implementations
- **Google Gemini Team** - For multimodal AI API access

---

## 📞 Contact

**Project Lead:** Haziq  
**GitHub:** [@IRSPlays](https://github.com/IRSPlays)  
**Repository:** [ProjectCortex](https://github.com/IRSPlays/ProjectCortex)

---

**Built with 💙 for accessibility. Engineered with 🔥 for excellence.**
