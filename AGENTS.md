# AGENTS.md - Coding Agent Guidelines for ProjectCortex

This file provides instructions for AI coding agents (Claude, Copilot, Cursor, etc.) working on this repository.

## Project Overview

**ProjectCortex** is an AI wearable for the visually impaired using a Raspberry Pi 5 as the compute core. The system uses a 4-Layer AI Brain architecture with a hybrid edge-server topology.

**Key constraint:** RPi5 has 4GB RAM. Avoid libraries requiring 8GB+ or x86-only dependencies.

## Directory Structure

```
ProjectCortex/
├── rpi5/                   # Wearable device code (runs on Raspberry Pi 5)
│   ├── main.py             # Main orchestrator entry point
│   ├── config/config.yaml  # Central configuration
│   ├── layer0_guardian/    # Safety-critical YOLO detection
│   ├── layer1_learner/     # Adaptive YOLOE detection
│   ├── layer2_thinker/     # Gemini Live API integration
│   ├── layer3_guide/       # Intent router + spatial audio
│   └── layer4_memory/      # SQLite + Supabase sync
├── laptop/                 # Dashboard server code (runs on laptop)
│   ├── gui/                # PyQt6 dashboard UI
│   ├── server/             # FastAPI WebSocket server
│   └── cli/                # CLI launchers
├── shared/                 # Shared code between RPi5 and laptop
│   └── api/                # WebSocket protocol, exceptions, base classes
├── tests/                  # Test files
└── models/                 # YOLO models (.pt, .ncnn)
```

## Build & Run Commands

### Installation
```bash
pip install -r requirements.txt
# RPi5 only: sudo apt install python3-picamera2
```

### Running the System
```bash
# Full system (start laptop FIRST, then RPi5)
python -m laptop all --fastapi    # Terminal 1: Laptop dashboard
python -m rpi5 all                # Terminal 2: RPi5 wearable

# Individual components
python rpi5/main.py --debug       # RPi5 with debug logging
python laptop/gui/cortex_ui.py    # PyQt6 dashboard only
python laptop/fastapi_server.py --host 0.0.0.0 --port 8765
```

### Testing
```bash
# Run all tests
pytest tests/ -v

# Run a SINGLE test file
pytest tests/test_router_fix.py -v

# Run a SINGLE test function
pytest tests/test_router_fix.py::test_router -v

# Run tests with coverage
pytest tests/ --cov=src --cov-report=html

# Quick syntax check
python -m py_compile rpi5/main.py laptop/server/fastapi_server.py
```

**Note:** Tests require `rpi5/` in sys.path. Use `PYTHONPATH=rpi5 pytest tests/` if imports fail.

### Linting (No formal linter configured)
```bash
# Manual checks
python -m py_compile <file.py>  # Syntax check
```

## Code Style Guidelines

### File Headers
Every Python file should have a docstring header:
```python
"""
Module Name - Brief Description

Longer description of what this module does.

Author: Haziq (@IRSPlays)
Date: Month Day, Year
"""
```

### Imports
Order imports as follows (with blank lines between groups):
```python
# 1. Standard library
import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# 2. Third-party packages
import cv2
import numpy as np
from fastapi import FastAPI, WebSocket

# 3. Local/project imports (add to sys.path first if needed)
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.api import MessageType, BaseMessage
from rpi5.layer3_guide.router import IntentRouter
```

### Naming Conventions
| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `IntentRouter`, `RPi5Client` |
| Functions/Methods | snake_case | `create_video_frame()`, `parse_message()` |
| Constants | UPPER_SNAKE_CASE | `PROJECT_ROOT`, `TEST_MODEL_PATH` |
| Private | Leading underscore | `_connection_manager`, `_handle_connect()` |
| Module-level logger | `logger` | `logger = logging.getLogger(__name__)` |

### Type Hints
Use type hints for function signatures:
```python
def route(self, query: str) -> str:
    """Route a voice command to the appropriate layer."""
    ...

async def send_detection(
    self,
    class_name: str,
    bbox: List[float],
    confidence: float,
    layer: int = 0
) -> bool:
    ...
```

### Async Patterns
- Use `async`/`await` for WebSocket and I/O operations
- Never call `asyncio.run()` inside an already-running event loop
- Use this helper pattern when unsure:
```python
def run_async_safe(coro):
    """Run coroutine safely, handling existing event loops."""
    try:
        loop = asyncio.get_running_loop()
        return asyncio.ensure_future(coro)
    except RuntimeError:
        return asyncio.run(coro)
```

### Error Handling
- Use custom exceptions from `shared/api/exceptions.py`
- Always log errors with context:
```python
try:
    await self.connect()
except ConnectionRefused as e:
    logger.error(f"Failed to connect to {e.host}:{e.port}: {e}")
    raise
```

### Logging
Use the module-level logger pattern:
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Starting service...")
logger.warning(f"Retry attempt {attempt}/{max_retries}")
logger.error(f"Failed to process: {e}")
logger.debug(f"Received frame: {frame.shape}")
```

## Architecture Rules (DO NOT VIOLATE)

1. **YOLO stays LOCAL on RPi** - Safety-critical, no network dependency
2. **Gemini via WebSocket Live API** - Not HTTP API (latency: <500ms vs 2-3s)
3. **VIO/SLAM on laptop ONLY** - Too heavy for RPi (1GB+ RAM)
4. **Layer routing:**
   - Layer 0/1 (Detection) → RPi5 (offline, <150ms)
   - Layer 2 (Gemini) → Cloud via WebSocket
   - Layer 3 (VIO/SLAM) → Laptop (post-processing)
   - Layer 4 (Memory) → RPi5 SQLite + Supabase sync

## Testing Guidelines

### Test File Structure
```python
"""
Test Description

Author: Haziq (@IRSPlays)
Project: Cortex v2.0
"""
import sys
from pathlib import Path

# Add rpi5 to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "rpi5"))

from layer3_guide.router import IntentRouter

def test_router_basic():
    """Test basic routing functionality."""
    router = IntentRouter()
    assert router.route("what do you see") == "layer1"
```

### Fixtures (conftest.py)
Common fixtures are in `tests/conftest.py`:
- `project_root` - Returns project root path
- `skip_if_no_model` - Skips if YOLO model missing
- `skip_if_no_webcam` - Skips if camera unavailable

## Key Files Reference

| File | Purpose |
|------|---------|
| `rpi5/main.py` | Main orchestrator (entry point) |
| `rpi5/layer3_guide/router.py` | Intent routing (97.7% accuracy) |
| `rpi5/config/config.yaml` | Central configuration |
| `laptop/gui/cortex_ui.py` | PyQt6 dashboard |
| `laptop/server/fastapi_server.py` | WebSocket server |
| `shared/api/protocol.py` | Message types and serialization |
| `shared/api/exceptions.py` | Custom exception classes |

## Before Implementing

1. Read `docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md` for context
2. Check RAM budget: RPi5 has 4GB, laptop has 8GB+
3. Verify which device the code runs on (RPi5 vs laptop)
4. Plan before coding - present structured plan with scope and testing strategy
5. After changes, verify files across `laptop/`, `rpi5/`, and `shared/`
