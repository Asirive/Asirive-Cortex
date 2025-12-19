# Project-Cortex v2.0 - Development Workflow

**Status:** Laptop-Assisted Development Phase  
**Hardware Status:** ⏳ Waiting for Raspberry Pi 5 + Sensors  
**Current Focus:** Software Development & Testing on Windows Laptop  

---

## 🎯 Development Philosophy

**"Fail with Honour" & "Pain First, Rest Later"**

We develop on the laptop **first** to:
1. Validate the 3-layer architecture
2. Test AI models at full speed (GPU)
3. Build the server components (SLAM, pathfinding)
4. Iterate rapidly without hardware dependencies

**Then** we deploy to Raspberry Pi 5 once parts arrive.

---

## 🖥️ Development Environment

### Hardware
- **Dell Inspiron 15 3520**
  - CPU: 12th Gen Intel Core i5-1235U
  - GPU: NVIDIA RTX 2050 (4GB VRAM, CUDA 12.8)
  - RAM: 16GB DDR4
  - OS: Windows 11

### Software Stack
- **Python:** 3.11+ (with CUDA support for PyTorch)
- **Git:** For version control
- **Git LFS:** For large model files
- **VS Code:** Primary IDE with Python + Jupyter extensions

---

## 📁 Project Structure (Hybrid Development)

```
ProjectCortex/
├── src/                          # Pi-side code (edge computing)
│   ├── layer1_reflex/            # YOLO, VAD, Whisper, Kokoro
│   ├── layer2_thinker/           # Gemini Live API client
│   ├── layer3_guide/             # Spatial audio, GPS/IMU fusion
│   ├── cortex_gui.py             # GUI for laptop development
│   └── main.py                   # Headless mode for Pi deployment
│
├── server/                       # Server-side code (laptop compute)
│   ├── slam_engine.py            # ORB-SLAM3 wrapper
│   ├── pathfinder.py             # A* navigation
│   ├── map_database.py           # PostgreSQL + PostGIS
│   └── websocket_server.py       # Real-time communication with Pi
│
├── models/                       # Large AI models (tracked by Git LFS)
│   ├── yolo11x.pt                # GPU-optimized for laptop
│   ├── yolo8n.pt                 # CPU-optimized for Pi
│   └── ...
│
├── tests/                        # Unit + integration tests
├── docs/                         # Technical documentation
└── config/                       # Configuration files
```

---

## 🔄 Development Workflow

### Phase 1: Laptop Development (Current)

#### 1.1 GUI Testing (`cortex_gui.py`)
**Purpose:** Test full system with USB webcam

```bash
# Activate virtual environment
venv\Scripts\activate

# Run GUI
python src/cortex_gui.py
```

**Features Available:**
- ✅ Layer 1: YOLO object detection (GPU)
- ✅ Layer 2: Gemini Live API (WebSocket)
- ✅ Layer 3: 3D spatial audio (OpenAL + USB headphones)
- ✅ Voice activation with Silero VAD
- ✅ Whisper STT + Kokoro TTS

**Testing Checklist:**
- [ ] YOLO detects objects in webcam feed
- [ ] Voice command: "What do you see?" → Gemini responds
- [ ] 3D audio: "Where is the chair?" → Directional ping
- [ ] Haptic simulation: Object <1.5m triggers warning

---

#### 1.2 Server Component Development

**SLAM Engine (`server/slam_engine.py`)**
```bash
# Install ORB-SLAM3 dependencies (Windows)
# Follow: https://github.com/raulmur/ORB_SLAM3

# Test SLAM with recorded video
python server/slam_engine.py --video test_data/indoor_walk.mp4
```

**Pathfinding API (`server/pathfinder.py`)**
```bash
# Start pathfinding server
python server/pathfinder.py --host 0.0.0.0 --port 8000

# Test endpoint (from another terminal)
curl http://localhost:8000/pathfind \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"start": [1.3521, 103.8198], "goal": [1.3530, 103.8200]}'
```

**WebSocket Server (`server/websocket_server.py`)**
```bash
# Start WebSocket server for Pi communication
python server/websocket_server.py --port 8765

# Test with mock Pi client
python tests/test_websocket_client.py
```

---

#### 1.3 Integration Testing

**Test Scenario: End-to-End Navigation**
```bash
# Terminal 1: Start server components
python server/slam_engine.py
python server/pathfinder.py
python server/websocket_server.py

# Terminal 2: Run GUI (simulates Pi)
python src/cortex_gui.py

# Terminal 3: Monitor logs
tail -f cortex_gui.log
```

**Expected Flow:**
1. GUI captures webcam frame → Sends to SLAM engine
2. SLAM calculates position → Sends to pathfinder
3. Pathfinder generates waypoint → Sends to GUI via WebSocket
4. GUI renders 3D audio directional ping
5. User hears: "Turn left in 10 meters"

---

### Phase 2: Raspberry Pi 5 Deployment (Future)

#### 2.1 Hardware Assembly
1. Connect Camera Module 3 to CSI port
2. Wire BNO055 IMU to I2C (SDA: GPIO 2, SCL: GPIO 3)
3. Wire GPS module to UART (TX: GPIO 14, RX: GPIO 15)
4. Connect vibration motor to GPIO 18 (PWM)
5. Pair Bluetooth headphones

#### 2.2 Software Deployment
```bash
# On Raspberry Pi 5
git clone https://github.com/IRSPlays/ProjectCortexV2.git
cd ProjectCortexV2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install picamera2  # RPi-specific

# Configure .env
nano .env
# Set: SERVER_IP=<laptop_wifi_ip>
# Set: GEMINI_API_KEY=<your_key>

# Test hardware
python tests/test_camera.py      # Camera Module 3
python tests/test_imu.py         # BNO055
python tests/test_gps.py         # GY-NEO6MV2
python tests/test_vibration.py   # PWM Motor

# Run headless mode
python src/main.py
```

#### 2.3 Network Configuration
```bash
# On Raspberry Pi 5
# Connect to 2 Wi-Fi networks simultaneously
sudo nmcli con add type wifi ifname wlan0 con-name "Internet" ssid "Home_WiFi"
sudo nmcli con add type wifi ifname wlan1 con-name "Server" ssid "Laptop_Hotspot"

# Set static IP for server connection
sudo nmcli con mod "Server" ipv4.addresses 192.168.137.10/24
sudo nmcli con mod "Server" ipv4.gateway 192.168.137.1
```

---

## 🧪 Testing Strategy

### Unit Tests
```bash
# Test individual components
pytest tests/test_yolo_cpu.py          # Layer 1
pytest tests/test_gemini_tts.py        # Layer 2
pytest tests/test_spatial_audio.py     # Layer 3
```

### Integration Tests
```bash
# Test full pipeline
pytest tests/test_integration.py
```

### Performance Benchmarks
```bash
# Measure latency budget
python tests/benchmark_latency.py

# Expected results:
# Camera capture:        ~33ms
# YOLO inference (GPU):  ~50ms (laptop) / ~85ms (Pi)
# Haptic trigger:        <10ms
# Gemini WebSocket:      ~450ms
# Server SLAM:           ~180ms
```

---

## 🐛 Debugging Tips

### GPU Not Detected
```python
import torch
print(torch.cuda.is_available())  # Should be True
print(torch.cuda.get_device_name(0))  # "NVIDIA GeForce RTX 2050"
```

### Git LFS Files Not Downloaded
```bash
git lfs ls-files  # Check tracked files
git lfs pull      # Force download
```

### WebSocket Connection Failed
```bash
# Check server is running
netstat -an | findstr 8765

# Test connection
python -c "import websockets; print('WebSocket library OK')"
```

### Bluetooth Audio Latency Too High
```bash
# Check codec (should be aptX or AAC, not SBC)
# Windows: Settings > Bluetooth > Device Properties > Advanced
```

---

## 📊 Performance Targets

| Component | Laptop (Dev) | Pi 5 (Prod) | Status |
|-----------|-------------|-------------|--------|
| YOLO Inference | 50ms (GPU) | 85ms (CPU) | ✅ Tested |
| Whisper STT | 800ms (GPU) | TBD | ⏳ Pending |
| Kokoro TTS | 1200ms (CPU) | 1200ms (CPU) | ✅ Tested |
| Gemini WebSocket | 450ms | 450ms | ⏳ Pending |
| SLAM Processing | 180ms (GPU) | N/A (Server) | ⏳ Pending |
| **Total Safety Loop** | <200ms | <200ms | 🎯 Target |

---

## 🚀 Next Steps (Priority Order)

1. **[HIGH]** Test Gemini 2.5 Flash Live API with WebSocket
2. **[HIGH]** Implement audio priority mixing (ducking)
3. **[MEDIUM]** Develop ORB-SLAM3 integration
4. **[MEDIUM]** Build A* pathfinding with obstacle avoidance
5. **[LOW]** Create caregiver web dashboard (React)

---

## 📖 Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [BOM.md](BOM.md) - Hardware bill of materials
- [SPATIAL_AUDIO_IMPLEMENTATION.md](SPATIAL_AUDIO_IMPLEMENTATION.md) - 3D audio system
- [TEST_PROTOCOL.md](TEST_PROTOCOL.md) - Testing procedures

---

**Last Updated:** December 19, 2025  
**Author:** Haziq (@IRSPlays)  
**Competition:** Young Innovators Awards (YIA) 2026
