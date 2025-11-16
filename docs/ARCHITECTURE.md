# Project-Cortex v2.0 - Architecture Documentation

**Last Updated:** November 16, 2025  
**Author:** Haziq (@IRSPlays)  
**Status:** Architecture Defined, Implementation Pending  

---

## 🎯 System Architecture Overview

Project-Cortex v2.0 implements a **3-Layer Hybrid AI Architecture** optimized for the Raspberry Pi 5 platform. Each layer serves a distinct purpose with specific latency and reliability requirements.

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INTERFACE LAYER                      │
│  (Bone Conduction Audio + GPIO Buttons + Web Dashboard)     │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   LAYER 3    │  │   LAYER 2    │  │   LAYER 1    │
│  The Guide   │  │ The Thinker  │  │  The Reflex  │
│              │  │              │  │              │
│ Navigation   │  │ Gemini API   │  │ YOLO Local   │
│ 3D Audio     │  │ Scene Desc.  │  │ <100ms       │
│ Dashboard    │  │ OCR/Text     │  │ Offline      │
│              │  │ ~1-3s        │  │ Safety       │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └─────────────────┴─────────────────┘
                         │
                         ▼
              ┌────────────────────┐
              │  IMX415 Camera     │
              │  1920x1080 @ 30fps │
              └────────────────────┘
```

---

## 📋 Layer Specifications

### Layer 1: The Reflex (Local Object Detection)

**Purpose:** Instant, offline safety-critical object detection

**Technical Stack:**
- **Model:** YOLOv8n (nano) or YOLOv11s
- **Framework:** Ultralytics YOLO + PyTorch
- **Optimization:** TensorFlow Lite (optional, for production)
- **Device:** CPU-only (RPi 5 @ 2.4GHz)

**Performance Requirements:**
- **Latency:** <100ms per frame
- **Throughput:** 10-15 FPS minimum
- **Power Draw:** 8-12W during inference
- **Memory:** <1GB RAM allocated

**Key Classes:**
- `ObjectDetector` - Main detection engine
- `PriorityClassifier` - Safety-critical object ranking
- `FrameBuffer` - Efficient memory management

**Safety-Critical Objects (High Priority):**
- Vehicles (car, bus, truck, motorcycle)
- Stairs/Steps
- Open doors/obstacles
- People (pedestrian detection)

**Implementation Files:**
- `src/layer1_reflex/__init__.py` - Main detector
- `src/layer1_reflex/optimizer.py` - Model optimization tools
- `src/layer1_reflex/classifier.py` - Object priority logic

---

### Layer 2: The Thinker (Cloud Intelligence)

**Purpose:** Complex scene understanding via multimodal AI

**Technical Stack:**
- **Primary API:** Google Gemini 1.5 Flash
- **Fallback:** OpenAI GPT-4 Vision
- **Transport:** HTTPS REST API via mobile hotspot
- **Rate Limiting:** 60 requests/minute (Gemini free tier)

**Use Cases:**
1. **Scene Description:** "What's in front of me?"
2. **OCR/Text Reading:** Signs, labels, documents
3. **Object Identification:** Unknown objects from Layer 1
4. **Navigation Assistance:** Route descriptions, landmarks

**Performance Requirements:**
- **Latency:** 1-3 seconds (network dependent)
- **Accuracy:** >95% for text recognition
- **Cost:** Stay within free tier limits
- **Fallback:** Queue requests if network unavailable

**Key Classes:**
- `SceneAnalyzer` - Gemini API wrapper
- `TextReader` - OCR-specific logic
- `RequestQueue` - Rate limiting & retry logic

**Implementation Files:**
- `src/layer2_thinker/__init__.py` - Main analyzer
- `src/layer2_thinker/gemini_client.py` - API integration
- `src/layer2_thinker/ocr.py` - Text extraction

---

### Layer 3: The Guide (Integration & UX)

**Purpose:** Orchestrate outputs and provide user interface

**Technical Stack:**
- **GPS:** USB GPS module (optional) or smartphone location sharing
- **3D Audio:** PyOpenAL for spatial sound
- **TTS:** Piper TTS (local) + Murf AI (cloud, high-quality)
- **STT:** Whisper Large v3 via Hugging Face API
- **Dashboard:** FastAPI backend + React frontend

**Features:**

1. **Audio Subsystem**
   - Text-to-Speech with configurable voices
   - 3D spatial audio for directional cues
   - Haptic feedback integration (future)

2. **Navigation Module**
   - GPS coordinate tracking
   - Turn-by-turn voice guidance
   - Landmark-based waypoint system

3. **Caregiver Dashboard**
   - Real-time location tracking
   - Remote configuration
   - Emergency alerts
   - Activity logs

**Performance Requirements:**
- **Audio Latency:** <500ms (TTS generation + playback)
- **Dashboard Response:** <100ms API response time
- **GPS Accuracy:** ±5 meters (typical smartphone)

**Key Classes:**
- `Navigator` - Main orchestration class
- `SpatialAudioEngine` - 3D audio rendering
- `TTSEngine` - Multi-provider TTS manager
- `STTEngine` - Speech recognition
- `Dashboard` - Web interface backend

**Implementation Files:**
- `src/layer3_guide/__init__.py` - Main navigator
- `src/layer3_guide/audio.py` - Audio subsystem
- `src/layer3_guide/gps.py` - GPS module
- `src/layer3_guide/dashboard/` - Web interface

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
