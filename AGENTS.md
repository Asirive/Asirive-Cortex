# AGENTS.md — Full Handoff for ProjectCortex

**Project**: Asirive Cortex — AI Wearable for the Visually Impaired
**Competition**: Tan Kah Kee Young Inventors' Award (YIA) 2026 (Finalist)
**Team**: Haziq Shah, Muhammad Irfan Nuafal, Eryna Natasha
**Institution**: Admiralty Secondary School, Singapore
**Last Updated**: June 1, 2026

---

## 1. Project Overview

Cortex is a multi-layer AI system that runs on a **Raspberry Pi 5 (4GB RAM)** and connects to a laptop for monitoring. It uses a 5-layer AI Brain architecture with hybrid edge-server topology:

| Layer | Name | Where | Purpose |
|------:|------|-------|---------|
| 0 | Guardian | RPi5 (local) | Safety-critical YOLO 26n detection, <100ms latency |
| 1 | Learner | RPi5 (local) | Adaptive YOLOE open-vocabulary detection |
| 2 | Thinker | Cloud (Gemini Live) | Conversational AI with audio/video |
| 3 | Guide | RPi5 (local) | Intent routing, navigation, spatial audio |
| 4 | Memory | RPi5 + Supabase | Detection storage, telemetry, sync |

**Key constraints:**
- RPi5: 4GB RAM, ARM64, no GPU. Avoid libraries requiring 8GB+ or x86-only.
- Hailo-8L M.2 HAT: dedicated NPU for depth estimation (driver status: was crashing on kernel 6.12.75+; check status before enabling).
- Bluetooth F-16 lavalier mic + UGREEN HiTune S3 earbuds (or CMF Buds).

**Cost**: USD 156 BOM (~SGD 250) — 90% reduction vs USD 2,500–3,000 competitors.
**Latency**: <100ms local safety, ~500ms cloud cognition.
**Intent classification routing accuracy**: 97.7%.

---

## 2. Hardware & Network

### Devices
| Device | IP | SSH User | Path |
|--------|----|----|------|
| RPi5 | **10.41.240.31** | `cortex` | `/home/cortex/ProjectCortex` |
| Laptop | **10.41.240.101** | — | Local dev machine |
| Hailo-8L NPU | M.2 HAT on RPi5 | — | scdepthv3.hef |
| USB Camera (V4L2) | `/dev/video0` (often flaky) | — | Falls back to CSI imx708_wide |
| CSI Camera | imx708_wide via picamera2 | — | **Primary** — 1920x1080 RGB888 |
| ToF VL53L5CX | I2C bus 1, addr 0x52 | — | Optional (8×8 depth) |
| BT Earbuds | F-16 (`41:42:98:C2:E0:3F`) | — | Audio I/O |
| IMU BNO055 | I2C | — | **DISABLED** (short circuit) |

### Power-on sequence
1. Power on RPi5 (USB-C, 5V/5A recommended).
2. Wait for CSI camera LED (~3s).
3. SSH in: `ssh cortex@10.41.240.31`.
4. Activate venv: `cd ~/ProjectCortex && source venv/bin/activate`.
5. Start system: `python cortex.py run --standalone` (or `python -m rpi5 all`).
6. Start laptop dashboard: `python -m laptop all --fastapi`.

---

## 3. Directory Layout

```
ProjectCortex/
├── cortex.py                 # NEW: unified CLI (run, status, test, sync, debug)
├── cortex                     # Unix wrapper for cortex.py
├── cortex.bat                 # Windows wrapper for cortex.py
├── pyproject.toml             # pip install -e . entry point
├── sync_rpi5.py              # DEPRECATED: delegates to scripts/sync
├── requirements.txt
├── rpi5/
│   ├── main.py                # Main orchestrator (entry point)
│   ├── __main__.py            # Old CLI: python -m rpi5 all
│   ├── config/config.yaml     # Central config (IPs, model paths, thresholds)
│   ├── layer0_guardian/       # YOLO 26n NCNN safety detection
│   │   ├── __init__.py        # YOLOGuardian class (now supports depth_map)
│   │   └── haptic_controller.py
│   ├── layer1_reflex/         # VAD, STT, TTS
│   │   ├── vad_handler.py
│   │   ├── cartesia_stt.py        # Cartesia batch STT (ink-2)
│   │   ├── cartesia_stt_ws.py     # NEW: Cartesia WebSocket turns STT
│   │   ├── whisper_handler.py     # Offline fallback
│   │   └── supertonic_handler.py  # NEW: Supertonic TTS (replaces Kokoro)
│   ├── layer2_thinker/        # Gemini Live API
│   │   ├── gemini_live_handler.py
│   │   ├── gemini_tts_handler.py
│   │   ├── cartesia_handler.py    # Cartesia Sonic 3.5 TTS
│   │   └── streaming_audio_player.py
│   ├── layer3_guide/          # Router, navigation, spatial audio
│   │   ├── router.py           # IntentRouter (97.7% accuracy)
│   │   ├── navigation_engine.py
│   │   └── bus_handler.py
│   ├── layer4_memory/         # SQLite + Supabase
│   ├── cli/                   # CLI helpers
│   │   ├── commands.py        # Old CLI handlers
│   │   ├── log_setup.py       # NEW: shared Rich-based logging
│   │   ├── audio_queue.py     # NEW: audio playback coordinator
│   │   └── debug_hailo.py     # Hailo diagnostic
│   ├── safety_monitor.py      # Tier 1/2/3 fusion engine
│   ├── hailo_depth.py         # SCDepthV3 / fast_depth depth estimator
│   ├── audio_alerts.py        # Safety alert TTS (Supertonic pre-generated)
│   ├── tts_router.py          # Smart TTS routing (Cartesia → Supertonic → Gemini)
│   ├── voice_coordinator.py   # VAD + STT pipeline
│   ├── main.py                # Orchestrator
│   └── conversation_manager.py
├── scripts/
│   ├── __init__.py            # NEW
│   └── sync.py                # NEW: modern sync tool
├── shared/
│   ├── api/                   # WebSocket protocol, exceptions
│   └── config/__init__.py     # Network config defaults
├── laptop/                    # Dashboard (FastAPI + PyQt6)
├── models/
│   ├── converted/yolo26n_ncnn_model/  # YOLO 26n NCNN (~11MB)
│   ├── hailo/
│   │   ├── scdepthv3.hef             # SCDepthV3 depth model
│   │   ├── fast_depth.hef            # Legacy depth model
│   │   └── paddle_ocr_v3_recognition.hef
│   └── yolo26n.pt                     # PyTorch weights
├── tests/                    # pytest
├── docs/
│   ├── plans/                # Implementation plans
│   └── architecture/
│       └── UNIFIED-SYSTEM-ARCHITECTURE.md
└── logs/                     # Runtime logs (cortex.log)
```

---

## 4. APIs & Models

### TTS (priority order in `tts_router.py`)
1. **Cartesia Sonic 3.5** — cloud, ultra-low latency. `model_id="sonic-3.5"`, voice `f786b574-daa5-4673-aa0c-cbe3e8534c02` (Katie).
2. **Supertonic 3** — local ONNX, 99M params, 31 languages, 912 chars/sec. `pip install supertonic>=1.3.0`. Voice `M1`.
3. **Gemini 2.5 Flash TTS** — cloud fallback. Voice `Kore`.

### STT
- **Primary**: Cartesia Ink-2 (batch HTTP, 66ms median, model `ink-2`).
- **WebSocket mode** (new, `cartesia_stt_ws.py`): `/stt/turns/websocket` with built-in turn detection. Config flag: `stt.cartesia_mode: "batch"` (default) or `"websocket"`. Test in noisy environments before enabling.
- **Offline fallback**: Whisper base, ~1.2s load + ~4.5s inference.

### Vision
- **YOLO 26n NCNN** — primary detection. `models/converted/yolo26n_ncnn_model/`, 80 COCO classes, ~80ms @ 640px on RPi5 CPU.
- **YOLOE 26n** — adaptive detection. Model missing on RPi5 (`models/converted/yoloe_26n_seg_pf/model.onnx`); graceful skip implemented.
- **SCDepthV3** — Hailo NPU depth, 256×320 input, metric depth output (meters), 8/97 in `scdepthv3.hef`. Driver was crashing on kernel 6.12.75+; check `dmesg | grep hailo` before enabling.

---

## 5. Key Files (read these first)

| File | Why |
|------|-----|
| `rpi5/main.py` | Orchestrator. Has 4000+ lines. Look for `def _run_detection_loop`, `def _handle_voice_query`, `def _start`. |
| `rpi5/config/config.yaml` | All tunables. Don't commit `.env` — gitignored. |
| `rpi5/voice_coordinator.py` | VAD + STT pipeline. Silero VAD, Cartesia STT, command queue mode. |
| `rpi5/tts_router.py` | TTS routing with audio queue integration. |
| `rpi5/safety_monitor.py` | Tier 1/2/3 fusion: YOLO + depth → threats. |
| `rpi5/hailo_depth.py` | SCDepthV3 / fast_depth, metric depth. |
| `rpi5/layer0_guardian/__init__.py` | YOLO + depth fusion. |
| `rpi5/cli/log_setup.py` | New shared logging (Rich). |
| `rpi5/cli/audio_queue.py` | New audio coordinator. |
| `scripts/sync.py` | New sync tool. |
| `cortex.py` | New unified CLI. |

---

## 6. CLI Usage

### New `cortex` command
```bash
# Run system
cortex run --standalone --debug      # RPi5 only
cortex run                           # Connected to laptop

# Diagnostics
cortex status                        # System overview
cortex test all                      # Test all components
cortex test layer0                   # Test YOLO
cortex test hailo                    # Test SCDepthV3

# Sync
cortex sync check                    # Test SSH to RPi5
cortex sync to                       # Code only
cortex sync to --models              # Code + ~500MB models
cortex sync from                     # Download logs/recordings
cortex sync install                  # pip install on RPi5
cortex sync full                     # to + install

# Debug
cortex debug                         # Interactive REPL
```

### Old `python -m rpi5 all` (still works)
```bash
python -m rpi5 all --standalone       # Same as cortex run --standalone
python -m rpi5 all --laptop 10.41.240.101 --earbuds cmf
python -m rpi5 test                   # Self-test diagnostics
python -m rpi5 status                 # Quick status
```

### Windows install
```powershell
cd C:\Users\Haziq\Documents\ProjectCortex
pip install -e .                      # One-time: makes `cortex` work globally
cortex status                         # Now works from any directory
```

---

## 7. Running the System

### First-time setup (RPi5)
```bash
cd ~/ProjectCortex
source venv/bin/activate
pip install -r requirements.txt
pip install "supertonic>=1.3.0" "websockets>=12.0"
sudo apt install espeak-ng python3-picamera2
```

### Start
```bash
# Standalone (no laptop)
cortex run --standalone

# Connected (ZMQ video + FastAPI to laptop)
cortex run

# With live monitor
cortex run --monitor
```

### Sync from laptop
```bash
cd ~/ProjectCortex  # on laptop
cortex sync check                    # Verify SSH
cortex sync to --models              # Full sync
cortex sync install                  # Update deps on RPi5
```

### Stop
- Ctrl+C (graceful shutdown).
- Or `pkill -f cortex` from another SSH.

---

## 8. Recent Changes (June 1, 2026)

### Phase 1: Supertonic TTS (replaces Kokoro)
- New `rpi5/layer1_reflex/supertonic_handler.py`. ONNX, 99M params, 44.1kHz→24kHz resampling.
- `tts_router.py`: Cartesia → Supertonic → Gemini.
- `audio_alerts.py`, `gemini_tts_handler.py`, `bus_handler.py`, `main.py`: updated.

### Phase 2: Cartesia Sonic 3.5
- `cartesia_handler.py`: `model_id="sonic-3.5"`.

### Phase 3: SCDepthV3 depth
- `hailo_depth.py`: auto-detect HEF shapes, support `scdepthv3` (metric depth) and `fast_depth` (inverse depth). Config: `hailo.depth.enabled: true`, `model_type: "scdepthv3"`.

### Phase 4: YOLO + depth fusion
- `layer0_guardian/__init__.py`: `detect()` now takes optional `depth_map`; uses metric distance for proximity when available.

### Phase 5: Premade verbal alerts
- `audio_alerts.py`: pre-generates WAV clips for 1–5m at startup using Supertonic. Cached for instant playback.

### Phase 6: Cartesia Ink 2 WebSocket STT
- New `rpi5/layer1_reflex/cartesia_stt_ws.py`. Enable via `stt.cartesia_mode: "websocket"`.

### CLI + sync rewrite
- `cortex.py`: unified CLI with `run`, `status`, `test`, `sync`, `config`, `debug`.
- `scripts/sync.py`: modern sync tool with progress, verify, and `cortex` file sync + `chmod +x`.
- Old `sync_rpi5.py` delegates to new tool.
- `pyproject.toml`: `pip install -e .` for global `cortex` command.

### Logging + audio queue
- `rpi5/cli/log_setup.py`: shared Rich-based logging producing `[HH:MM:SS] INFO     ` format (matches `python -m rpi5 all`).
- `rpi5/cli/audio_queue.py`: centralized coordinator preventing Cartesia/Supertonic TTS and Gemini Live from overlapping. Safety alerts preempt everything.
- `cartesia_stt.py`: timeout 15s → 30s, handle empty body / invalid JSON.
- `config.yaml`: `dropoff_threshold: 3.0` → `5.0` (reduce false positives).

---

## 9. Known Issues & Fixes Needed

| Issue | Status | Fix |
|-------|--------|-----|
| Hailo driver crash (kernel 6.12.75+) | Was broken | Re-enable in `config.yaml` once driver is upgraded |
| YOLOE 26n model missing | Code done, model absent | Download `yoloe_26n_seg_pf/model.onnx` |
| IMU BNO055 short circuit | Hardware | Replace IMU wiring |
| ToF VL53L5CX not installed | `pip install vl53l5cx` | Sensor not on hand yet |
| Layer 0 latency >100ms (111ms spikes) | Open | YOLO is 80ms + Python overhead. Consider INT8 or prune model. |
| Supabase DNS failure | Network | Check `/etc/resolv.conf` on RPi5 |
| Dropoff false positives | Fixed | Threshold raised 3.0 → 5.0 |
| Cartesia STT 15s timeout | Fixed | Raised to 30s |
| Cartesia/Supertonic TTS overlap with Gemini | Fixed | `audio_queue.py` coordinator |
| USB camera flaky (0 frames) | Open | Always falls back to CSI imx708_wide |
| Audio alert TTS quality | Open | Supertonic pre-generation works; espeak-ng fallback only |

---

## 10. Testing & Verification

### Quick smoke test
```bash
cortex status
cortex test all
```

### Each component
```bash
cortex test layer0      # YOLO 26n inference
cortex test layer2      # Gemini Live API
cortex test tts         # Supertonic + Cartesia
cortex test stt         # Cartesia + Whisper
cortex test camera      # USB/CSI frame capture
cortex test audio       # VAD + sounddevice
cortex test hailo       # SCDepthV3 depth
```

### Log files
- `logs/cortex.log` — main runtime log
- `tts_recordings/` — pristine WAV files per TTS output (for video editing)
- `recordings/` — session AV recordings
- `memory_images/` — captured frames for memory
- `temp_audio/` — temporary Cartesia outputs
- `nav_cache.db` — navigation cache
- `local_cortex.db` — local SQLite

---

## 11. Architecture Decisions

1. **YOLO stays LOCAL on RPi** — Safety-critical, no network dependency.
2. **Gemini via WebSocket Live API** — Not HTTP API (latency: <500ms vs 2-3s).
3. **VIO/SLAM on laptop ONLY** — Too heavy for RPi (1GB+ RAM).
4. **Layer routing**:
   - Layer 0/1 (Detection) → RPi5 (offline, <150ms)
   - Layer 2 (Gemini) → Cloud via WebSocket
   - Layer 3 (VIO/SLAM) → Laptop (post-processing)
   - Layer 4 (Memory) → RPi5 SQLite + Supabase sync

5. **Audio queue priority**:
   - Safety alerts (preempt)
   - Gemini Live
   - Cartesia/Supertonic TTS (wait for Gemini turn complete)
   - Whisper/local TTS

---

## 12. Adding a New Feature

1. **New TTS engine**: Add to `rpi5/layer1_reflex/`, update `tts_router.py` fallback chain.
2. **New sensor**: Add handler in `rpi5/sensors/`, wire into `main.py` initialization, update `config.yaml`.
3. **New layer**: Create `rpi5/layerN_*/`, import in `main.py`, add to orchestrator.
4. **New CLI command**: Add to `cortex.py` subparsers, add handler in commands dict.
5. **New safety hazard**: Add to `HazardType` enum in `hailo_depth.py`, add detection method, update `safety_monitor.py` tiers.

---

## 13. Commit Style

```
<type>(<scope>): <short summary>

<body explaining what and why>

Co-authored-by: ... (if applicable)
```

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`.

Examples:
```
feat(tts): replace Kokoro with Supertonic
fix(depth): increase dropoff threshold to reduce false positives
chore(network): update IPs to 10.41.240.x
```

---

## 14. Environment Variables (.env — gitignored)

```ini
GEMINI_API_KEY=AIzaSyBRDAw9CrcAHag8jk7uFpEjrw1DvDTHciE
GOOGLE_API_KEY=AIzaSyBRDAw9CrcAHag8jk7uFpEjrw1DvDTHciE
CARTESIA_API_KEY=sk_car_NT4eGwZApSGqBHJQd4acq7
SUPABASE_URL=https://ziarxgoansbhesdypfic.supabase.co
SUPABASE_KEY=...
```

`.env` is in `.gitignore` (via `.*` pattern with explicit allowlist). Never commit it.

---

## 15. Performance Targets

- Layer 0 YOLO 26n: <100ms (currently spikes to 111ms — fix needed)
- VAD + STT pipeline: <500ms end-to-end
- Cartesia TTS: <300ms
- Gemini Live audio: <500ms first byte
- SCDepthV3 (Hailo): ~5ms per frame
- System boot: ~30s
- TTS pre-generation: ~2s per clip × 45 clips = ~90s on first run

---

## 16. One-Liner Health Check

```bash
cortex status && cortex test all
```

Should show all green. If anything red, run the specific `cortex test <component>` for details.
