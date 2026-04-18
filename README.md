<div align="center">

<br/>

<img src="https://img.shields.io/badge/Platform-Raspberry%20Pi%205-E36D47?style=for-the-badge&logo=raspberrypifoundation&logoColor=white" />
<img src="https://img.shields.io/badge/AI-Gemini%203.1%20Flash-4285F4?style=for-the-badge&logo=google&logoColor=white" />
<img src="https://img.shields.io/badge/Detection-YOLO%20v11-00FFFF?style=for-the-badge&logo=yolo&logoColor=black" />
<img src="https://img.shields.io/badge/Safety-Silent%20Dangers%20Only-FF6B6B?style=for-the-badge&logo=shield&logoColor=white" />

<br/>

# ProjectCortex

### AI Wearable for the Visually Impaired

**Context-aware AI companion · Silent-danger-first safety · GPS navigation with transit · Natural conversation**

*Turn on → it works. Say where → it navigates. Say nothing → it keeps you safe.*

<br/>

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Hardware: <$150](https://img.shields.io/badge/Cost-%3C%24150-success.svg)](https://www.raspberrypi.com/products/raspberry-pi-5/)
[![Safety: Offline](https://img.shields.io/badge/Safety-Offline%20First-critical.svg)]()

</div>

---

## The Problem

> **"The biggest daily challenge is taking the bus."** — SAVH Advocate

1.3 billion people live with vision impairment. Existing AI glasses describe scenes — but they don't **navigate**. They can't guide a blind person to a bus stop, tell them which bus is arriving, or help them board the right one. Scene description is already solved (Be My AI, Seeing AI). **Independent mobility is not.**

## The Solution

ProjectCortex is a **<$150 chest-mounted wearable** powered by a Raspberry Pi 5 that provides:

| Feature | How |
|:---|:---|
| **6-Mode Contextual AI** | Gemini switches between 6 behavioral profiles (IDLE → EXPLORE) based on what you're doing. Silent when walking, proactive when lost, laser-focused at bus stops. Not a chatbot — a context-adaptive companion. |
| **Silent-Dangers-Only Safety** | Fuses YOLO + depth + velocity to warn ONLY about what you can't hear. Walls, poles, overhead obstacles, approaching cars. Never alerts about things you can already hear. Progressive: voice → haptic as distance closes. Works offline, <100ms. |
| **GPS Navigation + Transit** | Multi-leg routing: walk → bus → MRT → walk. Voice navigation, stop counting, arrival detection. LTA DataMall real-time bus arrivals. |
| **Natural Conversation** | Ask anything: *"What do you see?"*, *"Read that sign"*, *"Where did I leave my keys?"* — Gemini 3.1 Flash answers in <1 second. |
| **Object Memory** | *"Remember where I put my wallet"* — SQLite + Supabase cloud sync. Ask later: *"Where's my wallet?"* |
| **Autonomous Narration** | System decides when to speak unprompted — new objects appearing, depth changes, navigation events. Navigation-aware cooldowns prevent spam. |

### How It Works

```
  User speaks ──> Silero VAD ──> Whisper/Cartesia STT ──> Intent Router (97.7%)
                                                              │
                                                 ┌────────────┼──────────────┐
                                                 │            │               │
                                            L0/L1 Safety   L2 Gemini    L3 Navigation
                                            (YOLO, <100ms)  (Vision/QA)  (GPS+Transit+Bus)
                                                 │            │               │
                                    ┌────────────┤            │               │
                                    │            │            │               │
                              Haptic Pulse   Voice Alert   Conversation   Voice Guidance
                              (imminent)     (approaching) (Q&A/narrate)  (turns, stops)
                                    │            │            │               │
                                    └────────────┴────────────┴───────────────┘
                                                      Bluetooth Earbuds
```

---

## Architecture

### 5-Layer AI Brain

| Layer | Name | Role | Technology | Latency | Device |
|:---:|:---|:---|:---|:---:|:---|
| **L0** | Guardian | Safety-critical detection + haptic alerts | YOLO v11 NCNN + GPIO vibration motor | <100ms | RPi5 (offline) |
| **L1** | Learner | Adaptive open-vocabulary detection | YOLOE (text/visual prompts) | ~200ms | RPi5 |
| **L2** | Thinker | Scene understanding, reading, Q&A, conversation | Gemini 3.1 Flash via Live API + function calling | ~500ms | Cloud |
| **L3** | Guide | Intent routing + GPS navigation + transit | Fuzzy router + Google Maps + LTA DataMall | <5ms | RPi5 |
| **L4** | Memory | Object recall, conversation history, cloud sync | SQLite (local) + Supabase (cloud) | ~1ms | RPi5 + Cloud |

### Hybrid Edge-Server Topology

```
                 ┌──────────────────────────────────────────┐
                 │        Raspberry Pi 5 (4GB RAM)          │
                 │                                          │
                 │  Camera Module 3 Wide                    │
                 │  NEO-6M GPS · BNO055 IMU                 │
                 │  Push Button · Vibration Motor           │
                 │          │                               │
                 │   ┌──────┴──────┐                        │
                 │   │ CortexSystem │ ◄── Main Orchestrator │
                 │   └──────┬──────┘                        │
                 │     ┌────┼────┐                          │
                 │    L0   L1   L3 ─── GPS Navigation       │
                 │    │    │    │     Transit Routing        │
                 │    │    │    │     Bus Handler            │
                 │    │    │    │     Safety Monitor         │
                 │   L2 ──┘    │                             │
                 │   Gemini    │                             │
                 │   Live API  L4 ── SQLite + Supabase      │
                 │                    │                       │
                 └────────────────────┼──────────────────────┘
                                      │ WebSocket (optional)
                                      ▼
                 ┌──────────────────────────────────────────┐
                 │        Laptop Dashboard (Optional)        │
                 │                                          │
                 │  PyQt6 Glassmorphic UI                   │
                 │  FastAPI WebSocket Server                 │
                 │  Live Video + Detection Overlays          │
                 │  GPS/IMU Sensors · System Metrics        │
                 └──────────────────────────────────────────┘
```

> **The RPi5 runs fully standalone.** The laptop dashboard is for monitoring and development only — all core functionality works without it.

---

## 6-Mode Contextual AI Companion

The core innovation: **Gemini doesn't have one personality — it has six.** The same model switches behavior completely depending on what the user is doing, controlled by a context-adaptive system prompt and 9 function-calling tools.

### The Six Modes

| Mode | Trigger | AI Behavior |
|:---|:---|:---|
| **IDLE** | No active route | *"Silence is correct behavior."* Only speaks for overhead hazards or direct questions. Max 2 sentences unprompted. |
| **OUTDOOR_NAV** | GPS fix available, route active | Turn-by-turn companion. Reads street signs. Announces waypoints and arrivals. Concise directions. |
| **INDOOR_NAV** | No GPS / GPS accuracy >10m | *"YOU are the primary navigator."* Full proactive guidance via camera — obstacles, direction, "look around slowly" prompts when lost. |
| **BUS_WATCH** | Within 50m of bus stop | Single-minded focus: read bus numbers, call LTA arrival API, guide to correct bus. |
| **TRANSIT** | GPS speed >15 km/h | Mostly quiet. Announces stops through windows. Counts remaining stops. |
| **EXPLORE** | User toggles explore mode | Describes everything. Maximum proactivity. Scene narration. |

### Function Calling (9 Tools)

Gemini doesn't just talk — it **acts**. Through function calling, it can query real-time data:

```python
# 9 function-calling tools exposed to Gemini:
tools = [
    get_navigation_state,       # Current waypoint, bearing, distance
    report_obstacle,            # Gemini reports what it sees → SafetyMonitor
    get_gps_accuracy,           # Current GPS fix quality
    get_bus_arrival,            # LTA DataMall bus arrival times
    start_outdoor_navigation,   # Activate GPS turn-by-turn
    guide_indoor,               # Switch to indoor camera-guidance
    stop_navigation,            # Cancel active navigation
    search_memory,              # Search saved items/locations
    set_system_mode,            # Switch PRODUCTION / DEV mode
]

# + Google Search grounding for real-time information
```

### Scene Change Detection (Autonomous Narration)

The system decides **when** Gemini should speak unprompted — not on a timer, but based on what actually changed:

| Trigger | Priority | Example |
|:---|:---:|:---|
| **Navigation event** | Highest | Waypoint reached, mode switched, road crossing |
| **New object classes** | High | *"A bench and a fire hydrant appeared nearby"* |
| **Depth change >30%** | Medium | Entering a room, reaching a wall |
| **Silence timeout** | Low | 60s idle / 120s navigating — check-in |

Boring classes like "person" and "bird" are filtered — they're transient and noisy indoors. Navigation-aware cooldowns: 5s between narrations when idle, 15s when navigating.

### Echo Detection & Barrier Suppression

| Problem | Solution |
|:---|:---|
| STT picks up device's own speaker output | 15-second buffer of Gemini transcripts checked against STT via word overlap |
| False barge-in after text/tool send | 2-3s cooldown after tool calls prevents Gemini's VAD from interpreting trailing noise as speech |
| Audio stream dropout during speaker output | Send zero-filled PCM frames instead of muting — maintains stream continuity |
| Context overflow in long sessions | Sliding window compression: trigger at ~105k tokens, compress older turns to bullet points |

---

## Silent-Dangers-Only Safety System

> **Most assistive devices alert about everything. ProjectCortex only alerts about what you CAN'T hear.**

The user wears transparency-mode earbuds — they can hear cars, people, and dogs naturally. The system focuses exclusively on **silent dangers**: walls, poles, overhead obstacles, and vehicles approaching from blind spots.

### 4-Tier Threat Classification

```
┌──────────────────────────────────────────────────────────┐
│  TIER 1 — Environmental Hazards (Depth Map)              │
│  Walls, stairs_down, stairs_up, curbs, dropoffs           │
│  → 2x score multiplier for critical severity               │
│  → Progressive: voice-only >1.5m → +voice <1.5m         │
│     → +haptic vibration <1.0m                              │
│  → Indoor walls at 0.5-0.8m SUPPRESSED (normal room)     │
├──────────────────────────────────────────────────────────┤
│  TIER 2 — Silent Static Obstacles (YOLO + Depth <2m)     │
│  Fire hydrant, bench, chair, pole, suitcase, bollard...    │
│  → Score = 5 / distance_m                                 │
│  → Only if depth <2m (filters distant objects)            │
│  → Distance-injected voice: "Pole, 1.2m ahead"           │
├──────────────────────────────────────────────────────────┤
│  TIER 3 — Approaching Vehicles (YOLO + Velocity Tracking) │
│  Car, truck, bus, motorcycle, bicycle                      │
│  → Score = 10 / TTC (time-to-contact)                    │
│  → Only if approach velocity >1 m/s AND distance <4m     │
│  → Velocity computed from rolling (timestamp, dist) deque│
├──────────────────────────────────────────────────────────┤
│  TIER 4 — Safe (No Alert)                                 │
│  People, dogs, cats, distant objects                       │
│  → User can hear these naturally through open-ear earbuds  │
│  → Explicitly filtered OUT to reduce alert fatigue        │
└──────────────────────────────────────────────────────────┘
```

### Progressive Alerting

The system never startles — it escalates:

| Distance | Alert Type | Example |
|:---|:---|:---|
| >3.5m | None | Too far, no alert |
| 2-3.5m | "Notice" | Low-priority awareness |
| 1.2-2m | "Warning" | *"Wall, 1.5m ahead"* |
| 0.7-1.2m | "Danger" + TTS | *"Pole, 0.8m ahead"* |
| <0.7m | "Critical" + TTS + Haptic | Vibration motor pulses |
| <0.3m | "Emergency" + TTS + Haptic | Sustained vibration |

### Environment-Aware Cooldowns

Alerting indoors is different from outdoors:

| Alert Type | Outdoor Cooldown | Indoor Cooldown | Why |
|:---|:---:|:---:|:---|
| General alert | 3s | 8s | Hallways have walls everywhere — spam prevents useful alerts |
| TTS voice | 8s | 20s | Don't repeat "wall ahead" every 2 seconds in a corridor |
| Haptic pulse | 2s | 5s | Vibration fatigue is real |

### Safety Guard Rules (Hard-Coded, Non-Negotiable)

| # | Rule | Rationale |
|:---:|:---|:---|
| 1 | **Never guide toward moving objects** | Navigation locks on fixed references (bus stop pole), never shifts to a moving bus |
| 2 | **No in-ear tips** | Blind users' ears = primary survival sensor. Bone conduction or open-ear only |
| 3 | **Physical privacy shutter** | 3D-printed sliding shutter + GPIO reed switch = no frames when closed |
| 4 | **Escalator = voice + cane** | Single vibration motor can't encode step timing. Too risky. |
| 5 | **Safety never depends on cloud** | YOLO + depth run 100% on-device. No network needed. |
| 6 | **Multi-source verification** | Never cross road / change direction / board transport from ONE source |

---

## Navigation System

### Auto-Switching Navigation Modes

| Mode | Trigger | Behavior |
|:---|:---|:---|
| **OUTDOOR** | GPS fix available (accuracy <10m) | GPS waypoint tracking, voice turn guidance, distance announcements |
| **INDOOR** | No GPS / GPS accuracy >10m / depth sensor detects walls <1m | Gemini camera guidance via function calling — "look around slowly" when lost |
| **BUS_STOP** | Within 50m of a bus stop | LTA DataMall arrivals + YOLO bus detection, voice announces bus numbers |
| **TRANSIT** | GPS speed >15 km/h | Pause navigation, announce stops, auto-detect arrival |
| **IDLE** | No active route | Safety alerts only. No navigation guidance. |

### Transit Routing (Multi-Leg Journeys)

```
"Take me to VivoCity"

Route: Walk → Bus 23 (8 stops) → Walk → Arrived

┌────────┐     ┌──────────────┐     ┌──────────┐
│  Walk  │────▶│   Bus 23     │────▶│   Walk   │────▶ 🏁
│ 350m   │     │ 8 stops      │     │ 120m     │
│ 4 min  │     │ 12 min       │     │ 1 min    │
└────────┘     └──────────────┘     └──────────┘
   voice           voice +              voice
   guides          stop count           guides
   to stop         announces            to door
```

- Google Maps Directions API (walking + transit modes)
- `RouteLeg` objects with `TransitInfo` (service number, stop count, headsign)
- Bus boarding confirmed via YOLO visual detection
- Stop counting + arrival detection via GPS speed changes

### Bus Handler

| Feature | Detail |
|:---|:---|
| **LTA DataMall** | Real-time bus arrivals for all ~5,000 Singapore bus stops |
| **YOLO Detection** | Visual bus detection triggers approach state |
| **Target Service** | When navigating, prioritizes the specific bus from your route |
| **Proximity Auto-Detect** | Within 50m → auto-start monitoring nearest stop |
| **Re-announce** | Every 60s, re-announces upcoming arrivals |

---

## Gemini Integration

### Live API (Bidirectional Streaming)

Real-time WebSocket session with Gemini 3.1 Flash. Streams microphone audio + camera frames, receives native 24kHz PCM audio back. No HTTP round-trips.

| Capability | Implementation |
|:---|:---|
| **Model** | `gemini-3.1-flash-live-preview` via v1beta API |
| **Voice** | "Zephyr" — clear, natural, accessibility-optimized |
| **Latency** | <500ms round-trip (83% improvement over HTTP API's 2-3s) |
| **Context Management** | Sliding window compression: compress older turns to bullet points at ~105k tokens |
| **Thinking** | `thinking_budget=0` for ~200ms latency savings on simple queries |
| **Echo Detection** | 15s buffer of Gemini transcripts compared against STT to prevent self-hearing |
| **Reconnection** | 5 attempts with exponential backoff, session handle resumption |

### TTS Routing (Smart Engine Selection)

| Response Length | Engine | Why |
|:---|:---|:---|
| < 300 chars | **Gemini 2.5 Flash TTS** | Natural voice, low latency for short phrases |
| >= 300 chars | **Kokoro-82M** (local ONNX) | Faster for long text, zero API cost |
| All keys exhausted | **Kokoro-82M** (automatic fallback) | Graceful offline degradation |

### Intent Router (97.7% Accuracy)

Pure keyword/stem/phrase matching — no ML model:
- **Layer 3**: Navigation, bus, memory queries → GPS engine, bus handler, memory search
- **Layer 2**: Describe, read, explain, analyze → Gemini vision
- **Layer 1**: Detect, count, identify → YOLOE
- **Filler**: Greetings, hallucinations, acknowledgments → ignore

---

## Hardware

### Bill of Materials

| Component | Model | Interface | Purpose | Cost |
|:---|:---|:---|:---|:---|
| **SBC** | Raspberry Pi 5 (4GB) | — | Compute core | $60 |
| **Camera** | Camera Module 3 Wide (IMX708) | CSI-2 | Scene capture 1920×1080 @ 30fps | $35 |
| **GPS** | NEO-6M / GT-U7 | UART (/dev/ttyAMA0) | Positioning, navigation | $8 |
| **IMU** | BNO055 9-axis | I2C | Heading, orientation, indoor gyro mode | $12 |
| **Vibration Motor** | 3V coin ERM | GPIO 18 PWM | Haptic proximity alerts | $2 |
| **Push Button** | Momentary | GPIO 16 | Short=listen, Long=mute, 5s=shutdown | $1 |
| **Microphone** | USB Lavalier | USB-A | Voice input (16kHz) | $8 |
| **Earbuds** | Bluetooth A2DP | BT 5.0 | Open-ear or bone conduction (safety!) | $20 |
| **Battery** | 5000mAh USB-C PD | USB-C | ~4 hours active runtime | $10 |
| | | | | **Total: ~$156** |

> **Safety: Open-ear or bone conduction ONLY.** Never in-ear tips — blind users need their ears for environmental awareness.

### Sensor Pipeline

```
Camera Module 3 Wide ──► Picamera2 ──► 1920x1080@30fps ──► YOLO / Gemini
NEO-6M GPS ───────────► UART NMEA ──► 1Hz position ───► Navigation Engine
BNO055 IMU ───────────► I2C ─────────► Euler angles ───► Heading + Indoor Gyro Mode
Push Button ──────────► GPIO 16 ─────► Interrupt ──────► Voice / Mute / Shutdown
Vibration Motor ─────► GPIO 18 PWM ─► Haptic Alerts ──► Safety Monitor
USB Lavalier Mic ─────► USB-A ───────► 16kHz input ────► VAD → STT
```

---

## Project Structure

```
ProjectCortex/
├── rpi5/                              # ▶ Wearable device code (RPi5)
│   ├── main.py                        # Main orchestrator (CortexSystem, 3991 lines)
│   ├── conversation_manager.py        # Multi-turn Gemini history + object recall
│   ├── voice_coordinator.py           # VAD + Whisper/Cartesia STT + echo detection
│   ├── tts_router.py                  # Smart Gemini/Kokoro TTS routing
│   ├── safety_monitor.py             # Fusion threat classifier (4 tiers)
│   ├── audio_alerts.py               # Distance-injected voice alerts
│   ├── bluetooth_handler.py          # A2DP output + USB mic input
│   ├── hailo_depth.py                # Hailo-8L depth estimation (NPU)
│   ├── hailo_ocr.py                  # Hailo-8L OCR (PaddleOCR backend)
│   ├── config/config.yaml            # Central configuration (554 lines)
│   │
│   ├── layer0_guardian/               # L0: Safety-critical YOLO + haptic
│   │   └── haptic_controller.py       # lgpio PWM vibration motor
│   │
│   ├── layer1_learner/               # L1: Adaptive YOLOE detection
│   │   ├── adaptive_prompt_manager.py
│   │   └── visual_prompt_manager.py
│   │
│   ├── layer1_reflex/                # L1: Voice pipeline
│   │   ├── kokoro_handler.py         # Local TTS (Kokoro-82M ONNX)
│   │   ├── whisper_handler.py        # OpenAI Whisper STT
│   │   ├── vad_handler.py            # Silero VAD
│   │   └── cartesia_stt.py           # Cartesia Sonic-3 STT
│   │
│   ├── layer2_thinker/               # L2: Gemini integration
│   │   ├── gemini_live_handler.py    # Live API (WS), function calling, echo detect
│   │   ├── gemini_tts_handler.py     # Vision + TTS generation
│   │   ├── scene_change_detector.py  # Proactive narration triggers + nav-aware cooldowns
│   │   ├── streaming_audio_player.py  # 24kHz PCM playback
│   │   └── lta_datamall.py           # Singapore bus arrival API
│   │
│   ├── layer3_guide/                 # L3: Navigation + Intent
│   │   ├── router.py                 # Intent classification (97.7% accuracy)
│   │   ├── navigation_engine.py      # GPS waypoint nav + transit routing (1799 lines)
│   │   ├── bus_handler.py            # LTA DataMall + YOLO bus detection (578 lines)
│   │   ├── detection_aggregator.py   # Multi-source detection fusion
│   │   ├── detection_router.py       # Route detections to alert systems
│   │   ├── connectivity_monitor.py   # Network health monitoring
│   │   ├── saved_locations.py        # Named location bookmarks
│   │   └── spatial_audio/            # Audio engine (beacon, alerts, proximity)
│   │       ├── manager.py            # OpenAL + beacon + proximity alerts
│   │       ├── audio_beacon.py       # Navigation beacon generator
│   │       ├── binaural_engine.py    # Fallback binaural (sounddevice)
│   │       ├── object_tracker.py    # Multi-object tracking with velocity
│   │       ├── position_calculator.py # 3D position from bbox + depth
│   │       ├── proximity_alert.py    # Distance-based alert tiers
│   │       ├── sound_generator.py    # Tone synthesis (beacon, alert, chime)
│   │       └── object_sounds.py     # Class-specific sound mappings
│   │
│   ├── layer4_memory/                # L4: Persistent memory
│   │   ├── memory_manager.py         # SQLite local storage
│   │   └── hybrid_memory_manager.py  # SQLite + Supabase cloud sync
│   │
│   └── hardware/                     # Peripheral drivers
│       ├── gps_handler.py            # NEO-6M UART NMEA reader
│       ├── phone_gps.py              # Phone GPS server (WiFi tether)
│       ├── fused_gps.py              # Multi-source GPS fusion
│       ├── imu_handler.py            # BNO055 (NDOF/gyro modes)
│       └── button_handler.py         # lgpio button (short/long/shutdown)
│
├── laptop/                           # Dashboard server (optional)
│   ├── gui/
│   │   ├── cortex_ui.py              # PyQt6 glassmorphic dashboard
│   │   └── cortex_dashboard.py       # Dashboard widget panels
│   ├── server/
│   │   ├── fastapi_server.py         # WebSocket server
│   │   ├── fastapi_integration.py    # RPi5 → Dashboard data bridge
│   │   ├── video_receiver.py         # ZMQ video stream receiver
│   │   └── websocket_server.py       # Real-time event streaming
│   └── cli/start_dashboard.py        # CLI launcher
│
├── shared/                           # Shared protocol code
│   └── api/
│       ├── protocol.py               # BaseMessage, MessageType, factories
│       ├── base_server.py            # Abstract WebSocket server
│       └── exceptions.py             # Custom exception hierarchy
│
├── models/                           # YOLO weights (.pt, .ncnn, .onnx)
├── docs/                             # Architecture & guides
│   ├── HARDWARE_WIRING_GUIDE.md      # Sensor wiring diagrams
│   ├── COMMAND_REFERENCE.md           # CLI commands
│   ├── plans/NAVIGATION_MASTER_PLAN.md  # 1481-line master reference
│   ├── Improvements/V2_TO_V3_HARDWARE_EVOLUTION.md
│   └── architecture/UNIFIED-SYSTEM-ARCHITECTURE.md
├── tests/                            # Test suite
├── requirements.txt                  # Python dependencies
└── sync_rpi5.py                      # Rsync deployment script
```

---

## Key Technical Decisions

### Why Gemini 3.1 Flash via Live API?

| Aspect | Decision | Rationale |
|:---|:---|:---|
| **Model** | `gemini-3.1-flash-live-preview` | Fastest multimodal model. Native audio output. Function calling. |
| **API** | Live API (WebSocket), not HTTP | <500ms round-trip vs 2-3s HTTP. Bidirectional streaming. |
| **Thinking** | `thinking_budget=0` | Disables internal reasoning for ~200ms latency savings |
| **Context** | Compression at 52k tokens, trigger at 104k | Prevents context overflow in long sessions |
| **Voice** | "Zephyr" | Clear, natural, suitable for accessibility |

### Why Silent-Dangers-Only (Not All-Objects)?

Traditional assistive devices alert about every detected object — cars, people, dogs, chairs. This creates alert fatigue and distracts from what matters. ProjectCortex uses transparency-mode earbuds (the user can already hear cars and people), so the system filters out audible threats and focuses exclusively on **silent dangers** that the user cannot perceive:

| What you CAN hear | What you CAN'T hear |
|:---|:---|
| Cars, motorcycles (engine noise) | Walls, poles, signboards |
| People talking, footsteps | Overhead obstacles, low branches |
| Dogs barking | Stairs, curbs, drop-offs |
| Bicycle bells | Approaching vehicles from blind spots |

The 4-tier classification + velocity tracking + environment-aware cooldowns means the system speaks only when it has something important to say.

### Why Local YOLO + Cloud Gemini?

- **Safety-critical detection** must work **offline with <100ms latency** — no network dependency
- Gemini adds ~500ms network latency — too slow for "a car is approaching"
- **YOLO handles reflexes, Gemini handles thinking**

### Why 6-Mode Contextual AI?

A single-voice assistant that describes everything becomes noise. A navigation-only system can't answer "what's that sign?" The mode-driven system adapts:
- **IDLE mode**: Silence is correct. Speak only for safety.
- **INDOOR_NAV mode**: Full proactive guidance — the user has no GPS, so Gemini IS the navigator.
- **BUS_WATCH mode**: Laser focus on bus numbers. No scene narration.

Each mode has different proactivity levels, detail requirements, and communication styles — all from the same Gemini model via dynamic system prompts.

### Why Hybrid Edge-Server?

| Component | Device | Why |
|:---|:---|:---|
| YOLO detection | RPi5 | Safety = must be local and fast |
| Voice pipeline | RPi5 | Latency-critical, works offline |
| Navigation + GPS | RPi5 | Real-time, 10Hz loop |
| Safety monitor | RPi5 | Must work without internet |
| Gemini Vision | Cloud | Needs GPU, 4GB RPi can't run it |
| Dashboard | Laptop | PyQt6 + VIO/SLAM too heavy for RPi |

---

## Performance

Measured on Raspberry Pi 5 (4GB RAM), Bluetooth audio, production code:

| Metric | Result |
|:---|:---|
| **End-to-end latency** (speak → hear answer) | ~800ms - 1.2s |
| **YOLO safety detection (L0)** | 60-80ms |
| **Intent routing** | <5ms |
| **GPS position refresh** | 1Hz (NEO-6M) |
| **Gemini function calling** | ~300-500ms |
| **Safety alert latency** (detection → haptic) | <100ms |
| **RAM usage** | ~3.6GB / 4GB |
| **Battery life** | ~4 hours active |
| **Total hardware cost** | <\$150 |

---

## Quick Start

### Prerequisites

- **Hardware:** Raspberry Pi 5 (4GB) + Camera Module 3 Wide + Bluetooth earbuds
- **Optional sensors:** NEO-6M GPS, BNO055 IMU, vibration motor, push button
- **Laptop:** Any machine for the monitoring dashboard (optional)
- **API Keys:**
  - [Gemini API key](https://aistudio.google.com/app/apikey) (required)
  - [LTA DataMall Account Key](https://datamall.lta.gov.sg/) (for bus arrivals, free)
  - [Google Maps API key](https://developers.google.com/maps) (for transit routing)
  - [Supabase project](https://supabase.com/) (for cloud memory sync, optional)
- **Python:** 3.11+

### Installation

```bash
git clone https://github.com/IRSPlays/ProjectCortex.git
cd ProjectCortex

python -m venv venv
source venv/bin/activate   # Linux/RPi5
pip install -r requirements.txt

# RPi5 only:
sudo apt install python3-picamera2 espeak-ng
```

### Configuration

```bash
# Create .env with your API keys
cat > .env << 'EOF'
GEMINI_API_KEY=your_gemini_key_here
GEMINI_API_KEY_2=backup_key_optional
GEMINI_API_KEY_3=another_backup
LTA_ACCOUNT_KEY=your_lta_key_here
GOOGLE_MAPS_API_KEY=your_maps_key_here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
EOF
```

Edit `rpi5/config/config.yaml` for camera, audio, sensor, and layer settings.

### Run

```bash
# ── Option 1: Full system (start laptop FIRST, then RPi5) ──
python -m laptop all --fastapi        # Terminal 1: Laptop dashboard
python -m rpi5 all                    # Terminal 2: RPi5 wearable

# ── Option 2: RPi5 standalone ──
python rpi5/main.py                   # Production mode
python rpi5/main.py --debug           # Debug logging

# ── Option 3: Individual components ──
python laptop/gui/cortex_ui.py        # PyQt6 dashboard only
python laptop/server/fastapi_server.py --host 0.0.0.0 --port 8765
```

### Deploy to RPi5

```bash
# Sync code from laptop to RPi5
python sync_rpi5.py                    # rsync to 10.173.242.31
```

---

## Demo Scenarios (SAVH)

Four stations designed with Singapore Association for the Visually Handicapped:

| # | Station | What It Tests | Key Feature |
|:---:|:---|:---|:---|
| 1 | **Indoor Safety** | Obstacle avoidance in a room | Tiered safety: voice alerts → haptic pulses, distance-injected |
| 2 | **Ask AI** | Natural conversation about the scene | Gemini Live multimodal Q&A with function calling |
| 3 | **Outdoor Navigation** | Walk to a destination with voice guidance | GPS waypoint tracking + turn announcements |
| 4 | **Bus Arrival** | Detect and read bus numbers, announce arrival times | LTA DataMall + YOLO bus detection |

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_router_fix.py -v

# Run a single test function
pytest tests/test_router_fix.py::test_router -v

# Syntax check
python -m py_compile rpi5/main.py laptop/server/fastapi_server.py

# If imports fail, add rpi5 to path:
PYTHONPATH=rpi5 pytest tests/ -v
```

---

## Phase Roadmap

| Phase | Features | Status |
|:---|:---|:---|
| **V1.0** | Core 5-layer pipeline, YOLO safety, Gemini vision, GPS navigation | ✅ Complete |
| **V2.0** | Transit routing (bus/MRT), bus detection, safety tiers, Live API, 6-mode AI | ✅ Complete |
| **V2.5** | SAVH demo polish, hazard cooldown fixes, IMU reliability | 🔄 In Progress |
| **V3.0** | Custom PCB, integrated audio, 57% lighter, waterproof enclosure | 📋 Planned |

See [NAVIGATION_MASTER_PLAN.md](docs/plans/NAVIGATION_MASTER_PLAN.md) for the full 1481-line master plan.

---

## Documentation

| Document | Description |
|:---|:---|
| [Hardware Wiring Guide](docs/HARDWARE_WIRING_GUIDE.md) | Sensor wiring diagrams and setup |
| [Navigation Master Plan](docs/plans/NAVIGATION_MASTER_PLAN.md) | Full navigation architecture and safety rules |
| [V2→V3 Hardware Evolution](docs/Improvements/V2_TO_V3_HARDWARE_EVOLUTION.md) | Custom PCB design, 77% smaller, 57% lighter |
| [System Architecture](docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md) | Complete system architecture document |
| [Command Reference](docs/COMMAND_REFERENCE.md) | CLI commands and configuration |

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Built for independence. Powered by Gemini. Designed with SAVH.**

*ProjectCortex by [Haziq](https://github.com/IRSPlays)*

</div>