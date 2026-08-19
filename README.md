<div align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=timeGradient&height=250&section=header&text=Asirive%20Cortex&fontSize=80&fontColor=ffffff&animation=fadeIn&fontAlignY=35&desc=Hybrid%20Edge%2BCloud%20Navigation%20Wearable&descAlignY=55&descSize=18" width="100%" />

  <br/>

  <img src="https://img.shields.io/badge/Cost-USD%20156%20BOM-00C853?style=for-the-badge&logo=dollar-sign&logoColor=white" />
  <img src="https://img.shields.io/badge/Safety_Latency-%3C100ms-FF6B6B?style=for-the-badge&logo=shield&logoColor=white" />
  <img src="https://img.shields.io/badge/Cloud_Latency-~500ms-4285F4?style=for-the-badge&logo=google&logoColor=white" />
  <img src="https://img.shields.io/badge/Platform-Raspberry%20Pi%205-E36D47?style=for-the-badge&logo=raspberrypifoundation&logoColor=white" />

  <br/>
  <br/>

  **Hands-free navigation independence for the visually impaired**
  *~90% cheaper than premium AI glasses · Tested with SAVH Singapore · Offline safety layer*
</div>

---

## 🌟 The Problem

> Visually impaired users are forced to choose between their **white cane** (for safety) and a **smartphone** (for navigation). Both hands, two tools, constant trade-off.

**Asirive Cortex** removes that trade-off. A wearable smart-glasses form factor that keeps the cane in hand while delivering real-time navigation, scene understanding, and safety alerts through open-ear audio.

The system is built around one core UX insight — **the cane already handles the ground** — so the AI only speaks up for hazards the user genuinely cannot perceive: overhead obstacles, fast-approaching vehicles, and visual information (signs, text, faces).

Validated in real-world trials with the **Singapore Association for the Visually Handicapped (SAVH)**.

---

## 🧠 5-Layer Hybrid Brain

Cortex runs an edge-first, cloud-augmented architecture on a Raspberry Pi 5. Safety-critical layers stay on-device; deep reasoning goes to the cloud.

| Layer | Name | Role | Tech | Latency | Where |
|:---:|:---|:---|:---|:---:|:---|
| **L0** | **Guardian** | Safety-critical obstacle detection + haptic | YOLO11n-NCNN + Hailo-8L monocular depth + GPIO PWM | **<100ms** | RPi5 (offline) |
| **L1** | **Learner** | Adaptive open-vocabulary detection (text / visual / prompt-free prompts) | YOLOE + MobileCLIP text encoder | ~200ms | RPi5 (laptop GPU in prod) |
| **L2** | **Thinker** | Scene understanding, OCR, conversational Q&A, function calling | **Gemini 3.1 Flash Live** (WebSocket audio↔audio) | ~500ms | Cloud |
| **L3** | **Guide** | Intent routing, GPS navigation, LTA transit, scene narration | Fuzzy router + Google Maps + LTA DataMall + NavigationEngine | <50ms | RPi5 |
| **L4** | **Memory** | Object recall, conversation history, telemetry | SQLite (hot cache) + Supabase (cold storage, 60s batch sync) | ~1ms | Hybrid |

```mermaid
graph TD
    User[User Audio/Video] --> VAD[Silero VAD]
    VAD --> STT[Cartesia Ink STT → Whisper fallback]
    VAD -->|32ms PCM chunks| Live[Gemini Live continuous audio]

    STT --> Router[IntentRouter<br/>97.7% accuracy · 14 intents]

    Router -->|safety| L0[L0 Guardian<br/>YOLO11n-NCNN + Hailo depth]
    Router -->|adaptive| L1[L1 Learner<br/>YOLOE]
    Router -->|open-ended| L2[L2 Thinker<br/>Gemini Live]
    Router -->|nav/transit| L3[L3 Guide<br/>NavEngine + LTA]

    L0 --> Safety[SafetyMonitor fusion<br/>tiered alerts]
    L1 --> Detect[DetectionAggregator]
    L2 --> Convo[Conversation + Tool Calling<br/>14+ functions]
    L3 --> Nav[Turn-by-turn voice<br/>+ bus arrivals]

    Safety --> TTS[TTSRouter<br/>Cartesia (safety·Troy) → Supertonic]
    Convo --> TTS
    Nav --> TTS
    TTS --> Earbuds[BT Earbuds<br/>CMF / UGREEN / F-16]
```

---

## 🛡️ The Core Insight: Cane-Aware Safety

The white cane already detects ground-level obstacles (curbs, steps, puddles, uneven ground). Cortex does **not** duplicate that — instead it filters out ground hazards indoors and **only fires on what the cane cannot see**:

| Hazard class | Cane covers it? | AI alerts? |
|:---|:---:|:---:|
| Walls, benches, fire hydrants (ground) | ✅ | ❌ indoors |
| Drop-offs, stairs going **down**, curbs | ✅ | ❌ indoors |
| **Overhead obstacles** (signs, branches, low ceilings) | ❌ | ✅ |
| **Stairs going up** (foot lands on riser) | ❌ | ✅ |
| **Fast-approaching** objects (vehicles, runners, e-scooters) | ❌ | ✅ |
| Visual info (text on signs, bus numbers, faces) | ❌ | ✅ |

Outdoors, the alert set widens. Cane-invisible hazards (overhang/stairs_up/incoming_fast) **always escalate to Tier 0 (critical)** with mandatory haptic feedback — these are life-safety traps the cane has no way to detect.

The fusion engine (`SafetyMonitor`) scores candidates and emits the single highest-priority `ThreatAlert` per frame:

- **Tier 0** — Critical: cane-invisible trap indoors / severity=critical outdoors → haptic + voice + record
- **Tier 1** — Environmental (overhang, stairs_up, incoming_fast, walls) → voice alert at <1.5m, haptic at <1.0m
- **Tier 2** — Silent static obstacle (bench, hydrant, etc.) <2m → voice alert
- **Tier 3** — Fast-approaching vehicle / person / skateboard >1 m/s closing → voice alert

Cooldowns prevent alert spam. Per-hazard-key haptic tracking means a continuous overhang can re-alert every 2s while *different* hazards fire independently. Object-ID tracker uses a 10px grid (50px caused cell-flips for slow-moving walkers).

---

## 🎤 Voice Pipeline

Audio is the primary UX. Cortex runs continuous, low-latency voice in both directions.

**Input (mic → system):**
- F-16 lavalier BT mic via HFP/HSP at 16 kHz mono
- Silero VAD fires `activity_start/activity_end` to Gemini Live (manual mode — auto-VAD kept killing the session via false barge-ins)
- Cloud STT primary: **Cartesia Ink** (~66 ms median)
- Local STT fallback: **Whisper base** (~8 s on RPi5)
- Hall-mode auto-detection: >5 VAD triggers in 10s → stricter thresholds
- Noise gate: -40 dB default (-35 dB in hall mode)

**Output (system → earbuds):**
- Gemini Live audio: streamed through `StreamingAudioPlayer` (50 ms blocksize)
- Local TTS: **Cartesia Sonic 3.5** (cloud) → **Supertonic ONNX** (offline fallback) → **Gemini TTS** → **GLM-4.6V** (Chinese)
- **Two distinct voices**:
  - **Katie** (female) for conversational replies
  - **Troy** (male, "designed for trust-building") for safety alerts — different gender = instant distinguishability in the <100 ms warning window, before the user has parsed any words

**Barge-in:** user speech during Gemini playback triggers `request_stop(interrupted=True)` on the audio player. Echo suppression sends silence (not dropped audio) to Gemini when the speaker is active — dropping creates silence→audio transitions that Gemini's VAD misreads as speech onset.

**Audio queue priority** (highest first): `SAFETY_ALERT → GEMINI_LIVE → CARTESIA_TTS → SUPERTONIC_TTS → WHISPER_LOCAL`. Balanced-counter state machine (boolean was buggy under nested start/stop calls).

---

## 🗺️ Context-Aware Navigation

The 5-mode Gemini Live runtime adapts behavior to context:

| Mode | Trigger | Behavior |
|:---|:---|:---|
| **IDLE** | Default | Silent unless overhead/approaching hazard detected |
| **OUTDOOR_NAV** | GPS fix + active route | Turn-by-turn voice, reads landmarks & signs at turns |
| **INDOOR_NAV** | GPS lost | Gemini becomes primary navigator — short voice commands ("door left", "straight ahead") |
| **BUS_STOP** | Within 50m of bus stop | LTA DataMall arrivals + on-device YOLO bus number reading |
| **TRANSIT** | On bus/MRT | Stop-counting mode, overhead sign reading |

Gemini has **14+ function declarations** including:
- `search_places`, `get_directions`, `start_navigation_with_route` (preferred outdoor chain)
- `start_outdoor_navigation` (compatibility fallback)
- `guide_indoor` (activates NavigationEngine's indoor mode)
- `get_bus_arrival`, `get_nearby_bus_stops`, `get_all_services_at_stop`
- `zoom_in` (region crop → force-turn response with upscaled crop)
- `search_memory`, `set_system_mode`, `report_obstacle`, `stop_navigation`, `get_navigation_state`, `get_gps_accuracy`

High-impact tools (`guide_indoor`, `start_outdoor_navigation`, `start_navigation_with_route`) are **gated by recent STT transcripts** to prevent Gemini from hallucinating destination names.

Multi-leg routes (Walk → Bus → Walk) are supported. Saved locations (Home / Relative's / School) act as default origin when GPS is unavailable.

---

## 📷 Vision Pipeline

**Cameras (auto-selected):**
1. **WITMOTION 400W stereo** (preferred) — composite 3840×1080 MJPG split in software:
   - **LEFT lens** (270° rotation → 9:16 portrait) → safety pipeline (YOLO + Hailo depth)
   - **RIGHT lens** (180° rotation → 16:9 landscape) → Gemini Live
2. **USB camera** (OpenCV/V4L2, indices 0–9 probed)
3. **CSI / Picamera2** (imx708_wide) — final fallback

**Detection layers:**
- **L0 Guardian** — YOLO11n-NCNN, COCO-80 subset, 0.35 confidence (lower than typical 0.5 to catch more real-world scenes), `<100ms` validated on RPi5 (80.7ms avg, 12.4 FPS, 417MB RAM @ 640px). Uses Hailo depth if available (7×7 region lookup) else bbox-area heuristic.
- **L1 Learner** — YOLOE with three modes:
  - `PROMPT_FREE` (4,585+ built-in classes via LRPC head)
  - `TEXT_PROMPTS` (adaptive vocabulary — Gemini describes the scene → "fire extinguisher" gets added → next detection runs with it)
  - `VISUAL_PROMPTS` (user draws bounding box → SAVPE visual encoder for "remember this wallet")
- **Hailo-8L NPU** (M.2 HAT) — shared VDevice hosts both:
  - **SCDepthV3** (metric depth, m) — wall/stair/curb/drop-off/overhang/incoming-fast detection. Indoor-aware thresholds.
  - **PaddleOCR v3** (recognition HEF) — text reading via vision_query_handler
- **VL53L5CX 8×8 ToF sensor** (glasses bridge, ~10° down) — close-range (<2m) depth, frees Hailo NPU from close-range work. Currently being integrated.

---

## 🧠 Memory (L4)

`HybridMemoryManager` keeps a **hot cache** in SQLite (WAL mode, 64MB cache, 1000-row ring buffer) and **batches uploads** to Supabase every 60 seconds with exponential backoff (1s → 300s cap). Graceful degradation: if Supabase is down, queues locally and resumes when WiFi returns. Stores:

- **Detections** — every L0/L1 detection with bbox, confidence, source, mode
- **Conversations** — multi-turn dialogue history with session-based grouping (30-min session timeout)
- **User profile** — key-value personalization facts
- **Adaptive prompts** — YOLOE text-vocab updates from Gemini ("fire extinguisher" learned)

`search_memory("wallet")` lets Gemini recall past observations via tool call.

---

## 🖥️ Hardware

### Current Prototype BOM (USD 156)

| Component | Purpose | Cost |
|:---|:---|---:|
| Raspberry Pi 5 (4GB) | Core compute | $60 |
| Camera Module 3 Wide | 1080p @ 30fps scene capture | $35 |
| Hailo-8L NPU (M.2 HAT, 13 TOPS) | Edge AI acceleration (depth + YOLO + OCR) | $30 |
| NEO-6M GPS + BNO055 IMU | Positioning & heading | $20 |
| Open-ear BT earbuds (F-16 / CMF / UGREEN) | Safe audio output | $20 |
| F-16 BT lavalier mic | 16 kHz voice input | $8 |
| Vibration motor (GPIO 18) | Haptic feedback via PWM | $3 |
| 10,000 mAh USB-C PD power bank | ~3.5 hours active runtime | $10 |
| **Total** | | **~$186** |

*Hailo is optional. Without it, YOLO11n runs on CPU at ~80ms — still meets the <100ms target. BOM without Hailo: **~$156**.*

### Peripherals

- **Physical button** (GPIO 16, momentary to GND) — short press = voice listen, long press (3–5s) = graceful shutdown, very-long (5s+) = OS shutdown
- **Bluetooth audio manager** — auto-pairs with F-16 / CMF / UGREEN, switches PipeWire profile (HSP/HFP for mic, A2DP for music), VAD-restart callback when BT link comes up mid-run
- **Power monitor** — battery / UPS state for the dashboard

---

## 📊 Live Dashboard

Three modes available via `python -m rpi5 all`:

- **`--old-dashboard`** — Legacy Rich `Live` panel + log scroll on stderr
- **default (Textual TUI)** — full-screen terminal UI: layers, system sensors, hailo, GPS, IMU, BT, AI routing, L0/L1/L2/L3/L4 panels, recent alerts, activity feed, transcript. Logs tailed from file (TUI owns the terminal)
- **`--2.4`** — plain-print dashboard for slow SSH over 2.4 GHz WiFi
- **`--no-dashboard`** — logs only

State lives in a single thread-safe `DashboardState` (deep-copy snapshots, bounded 60-sample history deques). The FULL TUI runs the main detection loop in a background thread and blocks on the Textual app on the main thread (Textual needs SIGTSTP/SIGCONT signal handlers from main thread).

Optional laptop-side companion dashboard (FastAPI + WebSocket) shows the same data in a browser, plus the camera feed and YOLO overlays.

---

## ⚙️ Setup

### Prerequisites
- **Hardware:** RPi5 (4GB), Camera Module 3 Wide, BT audio device
- **API keys:** [Gemini API](https://aistudio.google.com/app/apikey), [Google Maps Directions](https://developers.google.com/maps/documentation/directions), [LTA DataMall](https://datamall.lta.gov.sg/)
- **Python 3.11+**

### Installation

```bash
git clone https://github.com/IRSPlays/ProjectCortex.git
cd ProjectCortex

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# On RPi5 only — system packages
sudo apt install python3-picamera2 espeak-ng
```

> ⚠️ `numpy<2.0` is pinned for HailoRT 4.20 compatibility. Do not upgrade.

### Configuration

Create `.env` (gitignored):

```env
# Required
GEMINI_API_KEY=your_gemini_key_here
GOOGLE_MAPS_API_KEY=your_maps_key_here
LTA_API_KEY=your_lta_key_here

# Optional
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
CARTESIA_API_KEY=your_cartesia_key_here
ZAI_API_KEY=your_zai_glm_key_here
```

API key rotation pool is supported — add `GEMINI_API_KEY_2`, `GEMINI_API_KEY_3`, etc. The handler rotates through them on 429/503.

The laptop's IP goes in `rpi5/config/config.yaml` under `laptop_server.host` (current production: `10.127.61.101`). The RPi5's `.env` is gitignored — push it via the included `scripts/fix_rpi5_env.py` (uses `scripts/.rpi5_key`, also gitignored).

### Run

```bash
# Production (RPi5) — full system with Textual TUI
python -m rpi5 all

# Standalone (no laptop dashboard)
python -m rpi5 all --standalone

# Debug a single subsystem
python -m rpi5 test-live          # minimal Gemini Live probe (prints real close codes)
python -m rpi5 layer0             # Guardian only
python -m rpi5 status             # print env / config / layer availability

# Laptop dashboard
python -m laptop all --fastapi    # opens on http://localhost:8000
```

---

## 🧪 Engineering Highlights

- **Hybrid edge+cloud with hard latency budgets** — safety runs offline at <100ms, reasoning goes to cloud at ~500ms. No safety feature requires the network.
- **Cane-aware safety** — explicitly models what the user already has and only fires on what they don't. The `_is_indoor` flag in `SafetyMonitor` switches the entire alert set.
- **Manual VAD with Gemini Live** — auto-VAD kept killing the session via false barge-ins from trailing TTS audio. Switched to explicit `activity_start/end` signals from Silero VAD.
- **API key rotation pool** — `GEMINI_API_KEY` through `_10`, exponential backoff, automatic Supertonic fallback when all keys are exhausted.
- **Two distinct TTS voices** — Katie for chat, Troy for safety. Different genders = instantly distinguishable without parsing words.
- **Echo suppression by silence substitution** — sending silence (not dropping) to Gemini when the local speaker is playing, preventing false barge-ins.
- **Hailo shared VDevice** — depth + OCR models share a `ROUND_ROBIN` VDevice. Skip `activate()` when sharing (FIX-HAILO-DIAG-2: it raises `HAILO_INVALID_OPERATION(6)`).
- **Bbox-area distance fallback** — when Hailo depth is unavailable, YOLO detections get a coarse class-aware distance from bbox area. The safety system stays useful even when the NPU driver fails.
- **Frequent bug-fix archaeology** — `M##`, `FIX-`, `H##`, `TB##`, `L##` tags throughout the codebase document specific bug IDs and their resolutions. The codebase reads like a forensic engineering log.

---

## 🛣️ Roadmap

### Q2 2026 — Custom SBC
- Compute Module 5-based wearable, 1.5× lighter, waterproof
- Integrated Hailo-8L M.2 (eliminate USB dongle)
- On-board mic array for 360° voice capture
- 6,000 mAh battery with solar trickle charge (~6h runtime)
- **Target BOM:** USD 120

### Q3–Q4 2026 — Edge Audio & Offline Resilience
- Finish VL53L5CX ToF integration (replace Hailo for <2m close-range)
- Breadcrumb retracing for "I'm lost" / "take me back"
- On-device ONNX action decoder for fallback navigation without cloud
- **Goal:** solo travel in low-cellular areas

### Q1 2027+ — Assistive Ecosystem
- Caretaker app (caregiver voice link, fall-detection SOS, stationary-zone alerts)
- Memory cloud with family/caregiver sharing (user-consented)
- Community-driven object library

---

## 📂 Project Layout

```
ProjectCortex/
├── rpi5/                       # RPi5 runtime
│   ├── main.py                 # CortexSystem orchestrator (~7,300 lines)
│   ├── cli/                    # CLI + Textual TUI + logging + audio queue
│   ├── config/                 # YAML config + env overlay
│   ├── layer0_guardian/        # YOLO11n-NCNN + haptic
│   ├── layer1_learner/        # YOLOE adaptive (3 modes)
│   ├── layer1_reflex/         # VAD + STT + local TTS
│   ├── layer2_thinker/         # Gemini Live + Cartesia TTS + GLM4V fallback
│   ├── layer3_guide/           # Intent router + nav engine + LTA bus + saved locations
│   ├── layer4_memory/          # SQLite + Supabase hybrid memory
│   ├── camera/                 # USB + WITMOTION stereo handlers
│   ├── sensors/                # VL53L5CX 8×8 ToF
│   ├── hardware/               # GPS, IMU, button, BT audio, power
│   ├── live_dashboard/         # Textual TUI + ConsoleApp (2.4 mode)
│   ├── local_copilot/          # Local-only inference path (in development)
│   └── safety_monitor.py       # Fusion engine: YOLO + Hailo → tiered alerts
├── laptop/                     # FastAPI dashboard server + GPU Layer-1 service
├── shared/                     # Cross-device WebSocket protocol + base client
├── scripts/                    # Dev/sync/debug (fix_rpi5_env.py handles SFTP for .env)
├── docs/                       # Architecture, plans, fixes, handoffs, research
├── models/                     # .pt / .ncnn / .hef / .onnx (gitignored)
├── pyproject.toml              # pip install -e .
└── requirements.txt            # numpy<2.0 pinned for HailoRT 4.20
```

---

## 👤 About

**Asirive Cortex** is built by **Asirive**, founded by **Haziq** ([@IRSPlays](https://github.com/IRSPlays)).

The project's name comes from *Asir* (Arabic: difficult/challenging) + the suffix *-ive*: making the difficult navigable. Cortex is the brain that connects the user's cane, camera, microphone, and the cloud into a single conversational assistant.

---

## 📄 License

Asirive Cortex is licensed under the GNU General Public License v3.0 or later. See [LICENSE](LICENSE).

---

<div align="center">
  <p><b>Hands-free navigation independence.</b></p>
  <p><i>Built by Asirive. Designed with the visually impaired community.</i></p>
  <p><img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="GNU GPL v3 License" /></p>
</div>