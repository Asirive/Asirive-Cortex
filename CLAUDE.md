# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ProjectCortex** is an AI wearable for the visually impaired targeting the YIA 2026 competition. It's a low-cost (<$150) alternative to $4,000+ assistive devices using a Raspberry Pi 5 as the compute core.

The system uses a **4-Layer AI Brain** architecture:
- **Layer 0 (Guardian)**: YOLO safety-critical detection (~105ms, offline, GPIO haptic feedback)
- **Layer 1 (Learner)**: Adaptive YOLOE detection with 3 modes (text prompts, prompt-free, visual prompts)
- **Layer 2 (Thinker)**: Gemini 2.0 Flash Live API via WebSocket for audio-to-audio conversation (<500ms)
- **Layer 3 (Router)**: Intent routing to layer 0/1/2/3 (97.7% accuracy)
- **Layer 4 (Memory)**: Hybrid SQLite + Supabase sync

## Commands

### Installation
```bash
# Core dependencies
pip install -r requirements.txt

# RPi5-specific
sudo apt install python3-picamera2
pip install supabase>=2.3.4  # For Layer 4 Memory
```

### Running the System

**Full System (RPi5 + Laptop):**
```bash
# Terminal 1: Start laptop dashboard FIRST
python -m laptop all --fastapi

# Terminal 2: Start RPi5 (after laptop is running)
python -m rpi5 all
```

**Individual Components:**
```bash
# RPi5 main entry point (with debug)
python rpi5/main.py --debug

# Laptop dashboard (PyQt6 GUI)
python laptop/gui/cortex_ui.py

# CLI launcher
python -m laptop.cli.start_dashboard

# FastAPI server only
python laptop/fastapi_server.py --host 0.0.0.0 --port 8765
```

### Testing
```bash
pytest tests/ -v
pytest tests/test_router_fix.py -v  # 44 intent router tests
python tests/test_yolo_cpu.py
pytest tests/ --cov=src --cov-report=html
```

### Model Conversion
```bash
python convert_to_ncnn.py --model models/yolo26s.pt --output models/converted/
```

## Architecture

### Hybrid-Edge Topology
```
User ←→ RPi5 (Wearable) ←→ Laptop (Server) ←→ Supabase (Cloud)
           │                    │
           │                    │
     YOLO, Whisper        VIO/SLAM (post-processing)
     Gemini Live API      PyQt6 Dashboard
     3D Spatial Audio     REST API + WebSocket
     SQLite
```

### Key Entry Points
| File | Purpose |
|------|---------|
| `rpi5/main.py` | System orchestrator (main entry) |
| `rpi5/layer3_guide/router.py` | Intent routing (97.7% accuracy, 44 tests) |
| `laptop/gui/cortex_ui.py` | PyQt6 dashboard with glassmorphic dark theme |
| `laptop/server/fastapi_server.py` | FastAPI WebSocket server |
| `convert_to_ncnn.py` | PyTorch → NCNN model conversion |

### Configuration
Central config: `rpi5/config/config.yaml` - contains all layer, sensor, camera, and cloud settings.

## Critical Rules

1. **YOLO stays LOCAL on RPi** - Safety-critical, no network dependency
2. **Gemini via WebSocket Live API** - Not HTTP API (<500ms latency vs 2-3s)
3. **VIO/SLAM on laptop ONLY** - Not real-time on RPi (RAM constraints)
4. **Plan before executing** - Use MCP tools to research before any implementation
5. **Hardware reality** - RPi5 has 4GB RAM, avoid libraries requiring 8GB+ or x86-only
6. **ALWAYS verify across laptop/rpi5/shared** - Use multi-branch-code-verifier after any changes

## Known Issues (As of Jan 25, 2026)

| Issue | Severity | Status | Workaround |
|-------|----------|--------|------------|
| Layer 0 latency 100-126ms | Medium | Monitor | AI Hat+ NPU planned for 5ms |
| PROMPT_FREE mode disabled | Low | Needs ONNX fix | Use TEXT/VISUAL prompts |
| Camera V4L2 controls error | Low | Hardware | Check camera not in use |
| supabase package missing | Critical | FIXED | Install from requirements.txt |
| WebSocket double-accept | Critical | FIXED | Removed duplicate accept() in FastAPIConnectionManager |
| Supabase heartbeat function | Medium | FIXED | Changed function to accept TEXT, cast to UUID internally |
| WebSocket connection manager sync | Medium | FIXED | Synced global and server connection managers |
| ZMQ video streaming debug | Low | Added | Debug logs to trace video frames (RPi5, laptop receiver, UI) |

## Mandatory Protocol

Before generating any plan or code:
1. Read `docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md` for context
2. Use MCP tools to research (github, deepwiki, context7)
3. Present a structured plan with scope, architecture impact, constraints verified, and testing strategy
4. Wait for approval before implementing

After implementing fixes:
1. Use `@agent-multi-branch-code-verifier` to verify all affected files
2. Update CLAUDE.md with any new commands or known issues
