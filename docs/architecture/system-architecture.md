# Project-Cortex v2.0 - Architecture Documentation

**Last Updated:** December 19, 2025  
**Author:** Haziq (@IRSPlays)  
**Status:** Hybrid-Edge Architecture Active Development  
**Architecture Type:** Server-Assisted Wearable (Laptop Development Phase)

---

## 🎯 System Architecture Overview: Hybrid-Edge Computing

Project-Cortex v2.0 implements a **Hybrid-Edge Architecture** where the Raspberry Pi 5 wearable handles time-critical AI (vision, reflexes) locally, while a high-performance laptop server manages computationally intensive spatial navigation (SLAM, VIO, pathfinding).

### Why Hybrid-Edge?

**On-Device Processing (Pi 5)**: Guarantees <100ms latency for safety-critical object detection and haptic feedback, even if network fails.

**Server Offloading (Laptop)**: Enables complex Visual-Inertial Odometry and real-time SLAM that would overwhelm the Pi's ARM CPU.

**Result**: Gold-standard latency + enterprise-grade spatial intelligence.

---

## 🏗️ Physical Infrastructure (The "Body")

### Edge Unit (Wearable - Raspberry Pi 5)
```
┌─────────────────────────────────────────────────────────────┐
│                   RASPBERRY PI 5 (4GB RAM)                   │
├─────────────────────────────────────────────────────────────┤
│ SENSORS:                                                     │
│  • Camera Module 3 (IMX708) - Vision Input                  │
│  • BNO055 IMU - 9-DOF Head-Tracking (I2C)                   │
│  • GY-NEO6MV2 GPS - Outdoor Localization (UART)             │
│                                                              │
│ ACTUATORS:                                                   │
│  • PWM Vibration Motor - Haptic Alerts (GPIO 18)            │
│  • Bluetooth Headphones - 3D Spatial Audio (Low-Latency)    │
│                                                              │
│ CONNECTIVITY:                                                │
│  • Wi-Fi 1: Internet (Gemini API)                           │
│  • Wi-Fi 2: Local Server (Navigation Data)                  │
└─────────────────────────────────────────────────────────────┘
```

### Compute Node (Server - High-Performance Laptop)
```
┌─────────────────────────────────────────────────────────────┐
│             DELL INSPIRON 15 (RTX 2050 CUDA)                │
├─────────────────────────────────────────────────────────────┤
│ ROLE: Heavy Spatial Computing                                │
│  • SLAM (Simultaneous Localization & Mapping)               │
│  • VIO (Visual-Inertial Odometry)                           │
│  • A* Pathfinding with Dynamic Obstacle Avoidance           │
│  • 3D Map Generation & Storage                              │
│                                                              │
│ COMMUNICATION:                                               │
│  • WebSocket Server (Port 8765) - Real-time Nav Data        │
│  • REST API (Port 8000) - Configuration & Logs              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🧠 The 3-Layer Computational Brain

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER INTERACTION LAYER                             │
│  Voice Commands (Mic) → Gemini Live API → PCM Audio (Bluetooth Headphones)  │
│  Haptic Feedback (Vibration Motor) ← Obstacle Alerts ← YOLO Detection       │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   LAYER 1 [Pi]   │  │   LAYER 2 [Pi]   │  │ LAYER 3 [HYBRID] │
│   The Reflex     │  │   The Thinker    │  │   The Navigator  │
├──────────────────┤  ├──────────────────┤  ├──────────────────┤
│ YOLOv8n (Nano)   │  │ Gemini 2.5 Flash │  │ Server: SLAM/VIO │
│ Haptic Feedback  │  │ Live API (WebSoc)│  │ Pi: 3D Audio Out │
│ <100ms, Offline  │  │ PCM Audio Direct │  │ GPS+IMU Fusion   │
│ Priority: HIGH   │  │ ~500ms Latency   │  │ Priority: MEDIUM │
└──────────────────┘  └──────────────────┘  └──────────────────┘
        │                        │                        │
        └────────────────────────┴────────────────────────┘
                                 │
                                 ▼
                   ┌──────────────────────────┐
                   │  Camera Module 3 (Pi 5)  │
                   │  1640x1232 @ 30fps       │
                   └──────────────────────────┘
```

---

## 📋 Layer Specifications

### Layer 1: The Reflex [RUNS ON RASPBERRY PI 5]

**Purpose:** Immediate Physical Safety - Zero-Tolerance Latency

**Technical Stack:**
- **Model:** YOLOv8n (Nano variant - optimized for ARM CPU)
- **Framework:** Ultralytics YOLO + PyTorch (CPU-only)
- **Device:** Raspberry Pi 5 (Quad-core Cortex-A76 @ 2.4GHz)
- **Output:** Direct GPIO 18 → PWM Vibration Motor

**Performance Requirements:**
- **Latency:** <100ms (frame capture → detection → haptic trigger)
- **Throughput:** 10-15 FPS minimum
- **Power Draw:** 8-12W during inference
- **Memory:** <800MB RAM allocated
- **Reliability:** 100% offline operation (no network dependency)

**Haptic Feedback Protocol:**
```python
# Proximity-based vibration intensity
if distance < 0.5m:  vibrate(intensity=100%, pattern="continuous")
elif distance < 1.0m: vibrate(intensity=70%, pattern="pulse_fast")
elif distance < 1.5m: vibrate(intensity=40%, pattern="pulse_slow")
```

**Safety-Critical Objects (Trigger Haptics):**
- **Immediate Hazards**: Stairs, open manholes, walls
- **Moving Threats**: Vehicles, bicycles, scooters
- **Human Collisions**: People in path (<1.5m)

**Key Optimization:**
- Uses INT8 quantization for 4x speedup on ARM
- Aggressive NMS (Non-Maximum Suppression) to reduce false positives
- Frame skipping: Processes every 2nd frame if latency exceeds budget

**Implementation Files:**
- `src/layer1_reflex/__init__.py` - Main detector
- `src/layer1_reflex/haptic_controller.py` - GPIO PWM control

---

### Layer 2: The Thinker [RUNS ON RASPBERRY PI 5]

**Purpose:** Vision Intelligence & Conversational AI

**Technical Stack:**
- **Primary API:** Google Gemini 2.5 Flash Native Audio (Live API)
- **Transport:** WebSocket (Direct Pi → Google Cloud)
- **Input:** Microphone PCM Stream (16kHz) + Camera JPEG Frames
- **Output:** PCM Audio Stream (24kHz) → Bluetooth Headphones

**Revolutionary Feature: NO LAPTOP MIDDLEMAN**
- **Old v1.0 Flow**: Pi → Laptop → Gemini → Laptop → Pi (200ms+ overhead)
- **New v2.0 Flow**: Pi → Gemini → Pi (Direct WebSocket, ~500ms total)

**Use Cases:**
1. **Conversational Queries**: "What's in front of me?"
2. **OCR/Text Reading**: "Read that sign"
3. **Scene Understanding**: "Describe the environment"
4. **Object Identification**: "What is this object?"

**Performance Requirements:**
- **Audio Latency:** ~500ms (includes Bluetooth transmission)
- **Network Dependency:** Requires Wi-Fi (falls back to Kokoro TTS if offline)
- **Cost:** $0 (Free tier: 1500 RPM)

**Bluetooth Latency Compensation:**
```python
# Assume 40-100ms Bluetooth delay
# Sync visual cues (YOLO bboxes) with audio output
visual_delay = bluetooth_latency_ms
delayed_bbox_render(bbox, delay=visual_delay)
```

**Key Classes:**
- `GeminiLiveClient` - WebSocket handler
- `AudioStreamManager` - PCM buffer management
- `SyncController` - A/V synchronization

**Implementation Files:**
- `src/layer2_thinker/gemini_tts_handler.py` - Live API integration
- `src/layer2_thinker/audio_sync.py` - Bluetooth compensation

---

### Layer 3: The Navigator [HYBRID: SERVER + RASPBERRY PI 5]

**Purpose:** Spatial Guidance & 3D Audio Rendering

**Split-Task Architecture:**

#### Server Responsibilities (Laptop - Heavy Compute)
- **SLAM (Simultaneous Localization & Mapping)**
  - ORB-SLAM3 for visual odometry
  - Constructs 3D point cloud of environment
- **VIO (Visual-Inertial Odometry)**
  - Fuses camera + BNO055 IMU data
  - Dead-reckoning when GPS unavailable (indoors)
- **Pathfinding**
  - A* algorithm with dynamic obstacle avoidance
  - Generates waypoint list: `[(lat, lon, alt), ...]`
- **Map Database**
  - Stores explored areas for future reference
  - PostgreSQL + PostGIS for geospatial queries

#### Pi 5 Responsibilities (Wearable - Real-Time)
- **Sensor Fusion**
  - GPS (GY-NEO6MV2) for outdoor positioning
  - BNO055 IMU for head orientation (Euler angles)
- **3D Spatial Audio Rendering**
  - PyOpenAL with HRTF (Head-Related Transfer Function)
  - Receives target coordinate from server
  - Calculates azimuth/elevation relative to head
  - Renders directional "ping" sound via Bluetooth
- **Audio Priority Mixing (Ducking)**
  ```python
  Priority 1 (HIGH):   Layer 1 Haptics (Never delayed)
  Priority 2 (MEDIUM): Layer 3 Nav Pings ("Turn left")
  Priority 3 (LOW):    Layer 2 Gemini Voice (Auto-duck by -10dB)
  ```

**Communication Protocol:**
```json
// Server → Pi (WebSocket, 10Hz)
{
  "target_waypoint": {"lat": 1.3521, "lon": 103.8198},
  "distance_to_target": 12.5,  // meters
  "turn_angle": -45,            // degrees (left = negative)
  "obstacles_ahead": ["car", "person"]
}
```

**Performance Requirements:**
- **Server Processing:** <200ms (SLAM + pathfinding)
- **Network Latency:** <50ms (local Wi-Fi)
- **Audio Rendering:** <100ms (3D position calculation)
- **Total Latency:** <350ms (acceptable for navigation)

**Key Classes:**
- **Server Side:**
  - `SLAMEngine` - ORB-SLAM3 wrapper
  - `PathPlanner` - A* implementation
  - `MapDatabase` - PostgreSQL interface
- **Pi Side:**
  - `SpatialAudioManager` - OpenAL renderer
  - `SensorFusion` - GPS + IMU + Server data
  - `NavigationController` - Waypoint following logic

**Implementation Files:**
- **Server:** `server/slam_engine.py`, `server/pathfinder.py`
- **Pi:** `src/layer3_guide/spatial_audio/manager.py`
- **Communication:** `src/layer3_guide/websocket_client.py`

---

## 🎧 Audio Latency & Priority System

### Bluetooth Latency Compensation

**Challenge:** Standard Bluetooth audio introduces 40-100ms latency  
**Solution:** Predictive delay compensation for visual feedback sync

```python
# Measure Bluetooth roundtrip latency on startup
bt_latency_ms = measure_bluetooth_latency()  # ~60-80ms typical

# When YOLO detects object, delay visual bbox rendering
def render_detection(bbox, timestamp):
    # Wait for audio to reach ears before showing visual
    time.sleep(bt_latency_ms / 1000.0)
    draw_bbox(bbox)
```

### Audio Priority Mixing (Ducking)

**Principle:** Safety alerts must NEVER be masked by conversation

```python
class AudioMixer:
    """
    3-tier priority system with automatic volume ducking.
    """
    PRIORITIES = {
        'CRITICAL': 1,   # Layer 1 Haptics (Vibration)
        'HIGH': 2,       # Layer 3 Navigation Pings
        'NORMAL': 3      # Layer 2 Gemini Conversation
    }
    
    def play_audio(self, audio_data, priority='NORMAL'):
        # If higher-priority audio is playing, duck current audio
        if priority > self.current_priority:
            self.duck_volume(target_db=-10)  # Lower by 10dB
            self.queue_audio(audio_data)
            # Restore volume when priority audio ends
            self.restore_volume(delay=2.0)
```

**Priority Rules:**
1. **Layer 1 (CRITICAL)**: Haptic vibration fires IMMEDIATELY, no audio queue
2. **Layer 3 (HIGH)**: Navigation pings interrupt Gemini (but queue, don't skip)
3. **Layer 2 (NORMAL)**: Gemini pauses when nav/safety alerts occur

**Example Scenario:**
```
Time 0.0s:  User asks "What's ahead?" (Gemini starts responding)
Time 0.5s:  YOLO detects car <1.5m (Haptics fire + vibration)
Time 0.6s:  Navigation: "Turn left in 10 meters" (Gemini ducks -10dB)
Time 2.6s:  Navigation ends (Gemini volume restored)
Time 3.0s:  Gemini continues: "...and there's a traffic light"
```

### Latency Budget Table

| Component | Target Latency | Actual (Measured) | Notes |
|-----------|---------------|-------------------|-------|
| Camera Capture | 30ms | 33ms | 30 FPS = 33.3ms |
| YOLOv8n Inference | <100ms | 85ms (Pi 5) | INT8 quantized |
| Haptic Trigger | <10ms | 5ms | Direct GPIO, no queue |
| Bluetooth Audio | 40-100ms | 60ms (avg) | Codec-dependent |
| Gemini WebSocket | <500ms | 450ms | Including TTS |
| Server SLAM | <200ms | 180ms | ORB-SLAM3 on RTX 2050 |
| **Total (Safety Loop)** | **<200ms** | **185ms** | ✅ Within budget |

---

## 🔄 Data Flow Architecture

### Typical Processing Pipeline

```python
# Pseudocode for main loop

while running:
    # 1. Capture frame from IMX415
    frame = camera.capture_array()  # ~30ms @ 1080p
    
    # 2. Layer 1: Instant object detection
    detections = layer1.detect(frame, confidence=0.5)  # <100ms
    
    # 3. Filter for high-priority objects
    critical_objects = [d for d in detections if d['priority'] == 'high']
    
    if critical_objects:
        # Immediate audio warning
        layer3.speak(f"Warning: {critical_objects[0]['class']} ahead!", priority='high')
    
    # 4. Layer 2: Triggered by user or on schedule
    if user_pressed_button or time_since_last_analysis > 30:
        description = layer2.analyze_scene(frame, prompt="Describe surroundings")
        layer3.speak(description, priority='normal')
    
    # 5. Layer 3: Update dashboard
    layer3.update_dashboard({
        'location': layer3.get_gps_location(),
        'detections': detections,
        'timestamp': time.time()
    })
    
    # Rate limiting: ~10-15 FPS
    time.sleep(0.066)  # ~15 FPS
```

---

## 🔌 Hardware Integration

### Camera Interface (libcamera)

```python
from picamera2 import Picamera2

camera = Picamera2()
config = camera.create_preview_configuration(
    main={"size": (1920, 1080), "format": "RGB888"},
    controls={"FrameRate": 30}
)
camera.configure(config)
camera.start()

# Continuous capture
while True:
    frame = camera.capture_array()  # Returns numpy array
    process_frame(frame)
```

### GPIO Button Input (gpiod)

```python
import gpiod

# Modern GPIO library for RPi 5
chip = gpiod.Chip('gpiochip4')
button = chip.get_line(17)  # GPIO17
button.request(consumer="user_button", type=gpiod.LINE_REQ_DIR_IN)

# Event-driven input
while True:
    if button.get_value() == 0:  # Active low
        handle_button_press()
```

### Power Management

**Boot Configuration (`/boot/firmware/config.txt`):**
```ini
# Enable max USB current (required for power bank)
usb_max_current_enable=1

# Camera overlay
dtoverlay=imx415

# Active cooling (fan control)
dtparam=fan_temp0=60000  # Start fan at 60°C
dtparam=fan_temp0_hyst=5000  # 5°C hysteresis
```

---

## 📊 Performance Monitoring

### Key Metrics to Track

1. **Layer 1 Latency**
   - Target: <100ms
   - Measurement: Time from frame capture to detection output

2. **Memory Usage**
   - Target: <3GB total (leave 1GB for system)
   - Monitor: `psutil.virtual_memory()`

3. **CPU Temperature**
   - Safe Range: 50-80°C
   - Critical: >85°C (thermal throttling)

4. **Power Consumption**
   - Idle: 3-4W
   - Active: 18-22W
   - Monitor: USB-C power meter

### Logging Configuration

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cortex.log'),
        logging.StreamHandler()  # Console output
    ]
)
```

---

## 🚨 Error Handling Strategy

### Critical Failures (Stop Execution)
- Camera initialization failed
- YOLO model loading failed
- GPIO hardware not detected

### Degraded Operation (Fallback)
- Layer 2 API unavailable → Use Layer 1 only
- GPS signal lost → Use last known position
- TTS failed → Use fallback pyttsx3

### Warnings (Log & Continue)
- High CPU temperature (>75°C)
- Network latency spike (>5s)
- Low battery (<20%)

---

## 🔐 Security Considerations

### API Key Management
- **Never hardcode** API keys in source code
- Store in `.env` file (gitignored)
- Load using `python-dotenv`

### Data Privacy
- **No persistent storage** of camera frames
- Audio recordings deleted after STT processing
- User location data encrypted in transit

### Network Security
- HTTPS only for API calls
- Certificate validation enabled
- Rate limiting to prevent abuse

---

## 🛣️ Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Camera integration with libcamera
- [ ] Basic YOLO inference pipeline
- [ ] Audio output (TTS only)
- [ ] Simple logging system

### Phase 2: AI Integration (Week 3-4)
- [ ] Layer 1 optimization (target <100ms)
- [ ] Layer 2 Gemini API integration
- [ ] Speech-to-Text (Whisper)
- [ ] Multi-threaded architecture

### Phase 3: Features (Week 5-6)
- [ ] GPS navigation module
- [ ] 3D spatial audio
- [ ] Web dashboard (MVP)
- [ ] GPIO button controls

### Phase 4: Polish (Week 7-8)
- [ ] Power optimization
- [ ] Enclosure design
- [ ] User testing
- [ ] YIA documentation

---

## 📚 References

- [Raspberry Pi 5 Documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi-5.html)
- [libcamera Python Bindings](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)
- [Ultralytics YOLO](https://docs.ultralytics.com/)
- [Google Gemini API](https://ai.google.dev/docs)
- [PyOpenAL Documentation](https://github.com/kcat/openal-soft)

---

**Next Steps:** Begin Phase 1 implementation with camera integration.
