<div align="center">

# ProjectCortex v2.0

### AI Wearable for the Visually Impaired — Powered by Gemini

[![Google Gemini](https://img.shields.io/badge/Powered%20by-Gemini%203%20Flash-4285F4?logo=google&logoColor=white)](https://ai.google.dev/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Hardware: RPi 5](https://img.shields.io/badge/Edge-Raspberry%20Pi%205-red.svg)](https://www.raspberrypi.com/products/raspberry-pi-5/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**A <$150 wearable that gives visually impaired users real-time scene understanding, spatial audio guidance, object memory, and natural conversation — powered by a 5-layer AI brain on a Raspberry Pi 5.**

</div>

---

## What It Does

ProjectCortex is a chest-mounted wearable camera connected to a Raspberry Pi 5 that continuously captures the world around a visually impaired user. When the user speaks a question — *"What's in front of me?"*, *"Read that sign"*, *"Where did I leave my keys?"* — the system sends the live camera frame + voice query to **Gemini 3 Flash Preview** and speaks the answer back through Bluetooth earbuds in under 1 second.

Safety-critical objects (cars, stairs, obstacles) are detected locally by YOLO in <100ms with haptic vibration and 3D spatial audio alerts — no internet required.

**Demo flow:**
1. User asks: *"What do you see?"*
2. Silero VAD detects speech, Whisper transcribes it
3. Intent Router classifies it as a vision query (97.7% accuracy)
4. Camera frame + prompt sent to **Gemini 3 Flash Preview** (multimodal)
5. Gemini analyzes the scene and returns a natural description
6. **Gemini 2.5 Flash TTS** converts the response to speech
7. Audio plays through Bluetooth earbuds — total latency ~800ms

Meanwhile, YOLO runs every frame detecting obstacles, the vibration motor pulses for proximity warnings, and the laptop dashboard streams everything in real-time.

---

## How Gemini Is Used

This project uses **three Gemini capabilities** via the `google-genai` SDK:

### 1. Gemini 3 Flash Preview — Multimodal Vision Brain

The core intelligence. Every vision query sends a PNG frame + text prompt to `gemini-3-flash-preview`:

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model='gemini-3-flash-preview',
    contents=[
        types.Part.from_bytes(data=image_bytes, mime_type='image/png'),
        types.Part.from_text(text=user_query)
    ],
    config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        system_instruction="You are a visual assistant for a visually impaired user...",
        thinking_config=types.ThinkingConfig(thinking_budget=0),  # Speed optimization
    )
)
```

**Key features used:**
- **Multi-turn conversation** — rolling history of user/model turns for contextual follow-ups
- **System instructions** — dynamic persona with spatial guidance rules, object recall behavior, and personalization (user's name, preferences extracted from speech)
- **ThinkingConfig** — `thinking_budget=0` disables internal reasoning for ~200-500ms latency savings on simple queries
- **Reference image comparison** — for object recall ("Where's my wallet?"), historical frames tagged `[Historical observation]` are sent alongside the current view so Gemini can compare locations

### 2. Gemini 2.5 Flash Preview TTS — Natural Speech Output

Text responses are converted to speech using Gemini's native TTS:

```python
response = client.models.generate_content(
    model='gemini-2.5-flash-preview-tts',
    contents=text_description,
    config=types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Kore"
                )
            )
        )
    )
)

# Extract raw PCM audio (24kHz, 16-bit mono)
audio_data = response.candidates[0].content.parts[0].inline_data.data
```

### 3. Smart TTS Routing (Gemini + Local Fallback)

A TTS router intelligently selects the engine based on response length:

| Response Length | Engine | Why |
|:---|:---|:---|
| < 300 chars | **Gemini 2.5 Flash TTS** | Natural voice, low latency for short phrases |
| >= 300 chars | **Kokoro-82M** (local ONNX) | Faster for long text, no API quota cost |
| All keys exhausted | **Kokoro-82M** (automatic) | Graceful offline degradation |

---

## Architecture

ProjectCortex uses a **hybrid edge-server topology** — the RPi5 handles real-time detection and voice locally, while a laptop runs the monitoring dashboard and optional GPU inference.

```
                    User (Visually Impaired)
                     |                |
              [Bluetooth Earbuds]  [Button]
                     |                |
        +------------+----------------+-----------+
        |         Raspberry Pi 5 (4GB)            |
        |                                         |
        |  Camera Module 3 Wide    NEO-6M GPS     |
        |         |                BNO055 IMU     |
        |    [Frame Capture]       Vibration Motor|
        |         |                               |
        |  +------+------+                        |
        |  | Intent      |                        |
        |  | Router      |                        |
        |  +------+------+                        |
        |    |    |    |                           |
        |   L0   L1   L2 ---------------------->  |---> Gemini 3 Flash (cloud)
        |   |    |     |                           |
        |  YOLO YOLOE  Gemini                     |
        |   |    |     |                           |
        |  L3: Spatial Audio + Navigator          |
        |  L4: SQLite + Supabase Memory           |
        |                                         |
        +-----|-----------------------------------+
              | WebSocket
              v
        +-----+------+
        |   Laptop   |
        | Dashboard  |  <-- PyQt6 glassmorphic UI
        | FastAPI WS |  <-- Real-time metrics, video, GPS/IMU
        +------------+
```

### The 5-Layer AI Brain

| Layer | Name | Role | Technology | Device |
|:---|:---|:---|:---|:---|
| **L0** | Guardian | Safety-critical obstacle detection + haptic alerts | YOLO v26n NCNN + GPIO vibration motor | RPi5 (offline, <100ms) |
| **L1** | Learner | Adaptive open-vocabulary detection | YOLOE v26 (ONNX/PyTorch, text/visual prompts) | RPi5 |
| **L2** | Thinker | Scene understanding, reading, Q&A, conversation | Gemini 3 Flash Preview + multi-turn history | Cloud |
| **L3** | Guide | Intent routing + 3D spatial audio + navigation | Fuzzy router (97.7%) + PyOpenAL + GPS | RPi5 |
| **L4** | Memory | Object recall, conversation history, cloud sync | SQLite (local) + Supabase (cloud) | RPi5 + Cloud |

### Voice Pipeline

```
Microphone ──> Silero VAD ──> Whisper STT ──> Intent Router ──> Gemini Vision
                                                                     │
BT Speaker <── Audio Playback <── Gemini TTS / Kokoro <── Response ──┘
```

### Hardware Sensors

| Sensor | Model | Interface | Purpose |
|:---|:---|:---|:---|
| **GPS** | NEO-6M / GT-U7 | UART | Location for navigation, geotagged memory |
| **IMU** | BNO055 9-axis | I2C | Heading, fall detection, orientation |
| **Vibration Motor** | 3V coin/ERM | GPIO 18 PWM | Haptic proximity alerts |
| **Button** | Momentary push | GPIO 16 | Short press = listen, long = mute, 5s = shutdown |

See [docs/HARDWARE_WIRING_GUIDE.md](docs/HARDWARE_WIRING_GUIDE.md) for full wiring diagrams and setup.

---

## Gemini API Features Used

| Feature | How We Use It | File |
|:---|:---|:---|
| **Multimodal input** (image + text) | Send camera frame + voice query | `rpi5/layer2_thinker/gemini_tts_handler.py` |
| **Multi-turn conversation** | Rolling session history for context | `rpi5/conversation_manager.py` |
| **Dynamic system instructions** | Personalized persona with spatial guidance | `rpi5/conversation_manager.py` |
| **ThinkingConfig** | Disable thinking for latency optimization | `rpi5/layer2_thinker/gemini_tts_handler.py` |
| **Native TTS output** | `response_modalities=["AUDIO"]` with voice config | `rpi5/layer2_thinker/gemini_tts_handler.py` |
| **API key rotation** | Pool of up to 10 keys with automatic failover | `rpi5/layer2_thinker/gemini_tts_handler.py` |
| **Rate limit retry** | Exponential backoff + key rotation on 429/503 | `rpi5/layer2_thinker/gemini_tts_handler.py` |
| **Reference image comparison** | Historical frames for object recall queries | `rpi5/conversation_manager.py` |
| **Personal fact extraction** | "My name is..." extracted and stored | `rpi5/conversation_manager.py` |

---

## Quick Start

### Prerequisites

- **Hardware:** Raspberry Pi 5 (4GB) + Camera Module 3 Wide + Bluetooth earbuds
- **Optional sensors:** NEO-6M GPS, BNO055 IMU, vibration motor, push button
- **Laptop:** Any machine for the monitoring dashboard (Windows/macOS/Linux)
- **API Key:** [Get a Gemini API key](https://aistudio.google.com/app/apikey)
- **Python:** 3.11+

### Installation

```bash
git clone https://github.com/IRSPlays/Gemini-Cortex.git
cd Gemini-Cortex

python -m venv venv
source venv/bin/activate   # Linux/RPi
pip install -r requirements.txt

# RPi5 only:
sudo apt install python3-picamera2 espeak-ng
```

### Configuration

```bash
# Create .env with your Gemini API key(s)
echo "GEMINI_API_KEY=your_key_here" > .env

# Optional: add backup keys for rate limit rotation
echo "GEMINI_API_KEY_2=second_key" >> .env
echo "GEMINI_API_KEY_3=third_key" >> .env
```

Edit `rpi5/config/config.yaml` for camera, audio, sensor, and layer settings.

### Run

```bash
# ── Terminal 1 (Laptop): Start dashboard ──
python -m laptop all --fastapi

# ── Terminal 2 (RPi5): Start wearable ──
python -m rpi5 all

# Or run RPi5 standalone with debug logging
python rpi5/main.py --debug
```

The laptop dashboard opens a PyQt6 window showing live video, detection overlays, system metrics (CPU/RAM/FPS sparklines), GPS/IMU sensor readings, and layer controls.

---

## Project Structure

```
ProjectCortex/
├── rpi5/                           # Wearable device code (Raspberry Pi 5)
│   ├── main.py                     # Main orchestrator (entry point)
│   ├── conversation_manager.py     # Multi-turn Gemini history + object recall
│   ├── voice_coordinator.py        # VAD + Whisper STT coordination
│   ├── tts_router.py               # Smart Gemini/Kokoro TTS routing
│   ├── fastapi_client.py           # WebSocket client → laptop dashboard
│   ├── video_streamer.py           # ZMQ video streaming to laptop
│   ├── config/config.yaml          # Central configuration
│   ├── hardware/                   # Peripheral drivers
│   │   ├── gps_handler.py          # NEO-6M UART NMEA reader
│   │   ├── imu_handler.py          # BNO055 I2C (fusion, fall detection)
│   │   └── button_handler.py       # GPIO button (short/long/shutdown)
│   ├── layer0_guardian/            # YOLO safety detection + haptic alerts
│   ├── layer1_learner/             # Adaptive YOLOE open-vocabulary detection
│   ├── layer1_reflex/              # Kokoro TTS + Whisper STT + VAD
│   │   ├── kokoro_handler.py       # Local TTS fallback (82M ONNX)
│   │   ├── whisper_handler.py      # Speech-to-text
│   │   └── vad_handler.py          # Voice activity detection (Silero)
│   ├── layer2_thinker/             # Gemini integration
│   │   └── gemini_tts_handler.py   # Gemini 3 Flash vision + TTS
│   ├── layer3_guide/               # Intent router + spatial audio + navigation
│   │   └── router.py               # Voice command classification (97.7%)
│   └── layer4_memory/              # SQLite + Supabase cloud sync
├── laptop/                         # Dashboard server (runs on laptop)
│   ├── gui/cortex_ui.py            # PyQt6 glassmorphic dashboard
│   ├── server/fastapi_server.py    # FastAPI WebSocket server
│   ├── cli/start_dashboard.py      # CLI launcher
│   └── config.py                   # Dashboard configuration
├── shared/                         # Shared code (RPi5 + laptop)
│   └── api/                        # WebSocket protocol, message types
│       ├── protocol.py             # BaseMessage, MessageType, factories
│       ├── base_server.py          # Abstract WebSocket server
│       └── exceptions.py           # Custom exception classes
├── models/                         # YOLO model weights (.pt, .ncnn, .onnx)
├── docs/                           # Architecture docs & guides
│   ├── HARDWARE_WIRING_GUIDE.md    # Sensor wiring + setup instructions
│   └── architecture/               # System architecture diagrams
├── tests/                          # Test files
├── requirements.txt
└── .env                            # API keys (not committed)
```

---

## Performance

Measured on Raspberry Pi 5 (4GB RAM), Bluetooth audio, production code:

| Metric | Result |
|:---|:---|
| **End-to-end latency** (ask → hear answer) | ~800ms - 1.2s |
| **Gemini vision response** | ~400-600ms |
| **Gemini TTS generation** | ~200-400ms |
| **Safety detection (YOLO L0)** | 60-80ms |
| **Intent routing** | <5ms |
| **GPS/IMU sensor streaming** | 0.5 Hz to dashboard |
| **RAM usage** | ~3.6GB / 4GB |
| **Total hardware cost** | <$150 |

---

## Laptop Dashboard

The PyQt6 dashboard provides real-time monitoring over WebSocket:

- **Live video feed** with bounding box overlays (L0 Guardian + L1 Learner)
- **System metrics** — CPU, RAM, FPS sparklines with uptime tracking
- **Hardware sensors** — GPS coordinates, IMU accelerometer/gyroscope/magnetometer
- **Detection log** — timestamped detections from all layers
- **Layer control** — restart individual layers, switch L1 detection modes
- **Production/Dev toggle** — switch RPi5 between modes remotely
- **Server tab** — connection status, client management
- **Logs tab** — system log with color-coded severity levels

---

## Key Technical Decisions

**Why Gemini 3 Flash Preview?**
- Multimodal (image + text) in a single API call — no separate vision pipeline needed
- Fast enough for real-time (<600ms typical response)
- High-quality scene descriptions with spatial awareness
- Native TTS output eliminates a separate speech synthesis step

**Why local YOLO alongside Gemini?**
- Safety-critical detection (cars, stairs) must work offline with <100ms latency
- Gemini adds ~500ms network latency — too slow for "a car is approaching" alerts
- YOLO handles the reflexes, Gemini handles the thinking

**Why Kokoro-82M as TTS fallback?**
- Gemini API has rate limits (especially free tier)
- Kokoro runs locally on RPi5 with zero API cost
- Automatic failover: if all API keys are exhausted, TTS degrades gracefully

**Why hybrid RPi5 + laptop?**
- RPi5 (4GB) handles real-time detection, voice, and sensors locally
- Laptop handles heavy post-processing (VIO/SLAM), monitoring dashboard, and optional GPU inference
- WebSocket bridge keeps everything in sync with <50ms transport latency

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run a single test
pytest tests/test_router_fix.py -v

# Syntax check
python -m py_compile rpi5/main.py
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Built for accessibility. Powered by Gemini.**

*ProjectCortex by [@IRSPlays](https://github.com/IRSPlays)*

</div>
