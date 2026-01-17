# Laptop Dashboard - ProjectCortex v2.0

PyQt6-based real-time monitoring dashboard for ProjectCortex AI wearable system.

## Features

- **Live Video Feed**: Real-time camera stream from RPi5 (30 FPS)
- **System Metrics**: FPS, RAM, CPU, battery, temperature
- **Detection Log**: Scrolling log of object detections from Layer 0/1
- **System Log**: Color-coded status messages
- **Multi-Device**: Support up to 5 concurrent RPi5 connections
- **Dark Theme**: Professional appearance for competition demos
- **Thread-Safe**: Asyncio WebSocket + PyQt6 signals/slots

## Installation

```bash
# Navigate to laptop directory
cd laptop

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Start Dashboard

```bash
# Default settings (0.0.0.0:8765)
python -m laptop.start_dashboard

# Custom host/port
python -m laptop.start_dashboard --host 192.168.1.100 --port 9000
```

### From Project Root

```bash
# From project root directory
python -m laptop.start_dashboard
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│           LAPTOP DASHBOARD (Windows)                │
│                                                      │
│  ┌──────────────────────────────────────────────┐  │
│  │  PyQt6 GUI (Main Thread)                     │  │
│  │  - Video display                             │  │
│  │  - Metrics dashboard                         │  │
│  │  - Detection log                             │  │
│  │  - System log                                │  │
│  └──────────────┬───────────────────────────────┘  │
│                 │ (Qt Signals - Thread Safe)       │
│  ┌──────────────▼───────────────────────────────┐  │
│  │  WebSocket Server (Background Thread)        │  │
│  │  - Receives data from RPi5                   │  │
│  │  - Handles multiple clients                  │  │
│  │  - Message parsing & routing                 │  │
│  └──────────────┬───────────────────────────────┘  │
└─────────────────┼───────────────────────────────────┘
                  │
                  │ WebSocket Connection
                  │
┌─────────────────▼───────────────────────────────────┐
│           RPI5 (192.168.0.91)                       │
│  ┌──────────────────────────────────────────────┐  │
│  │  WebSocket Client (main.py)                 │  │
│  │  - Sends video frames (30 FPS)              │  │
│  │  - Sends metrics (every 1s)                  │  │
│  │  - Sends detections (real-time)              │  │
│  │  - Sends status updates                      │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

## Message Protocol

### Upstream (RPi5 → Laptop)

```json
{
  "type": "VIDEO_FRAME | METRICS | DETECTIONS | STATUS",
  "timestamp": "2026-01-08T12:34:56Z",
  "data": { ... }
}
```

**Video Frame**:
```json
{
  "type": "VIDEO_FRAME",
  "data": {
    "frame": "base64_encoded_jpeg",
    "width": 640,
    "height": 480
  }
}
```

**Metrics**:
```json
{
  "type": "METRICS",
  "data": {
    "fps": 30.0,
    "ram_mb": 2048,
    "ram_percent": 52.3,
    "cpu_percent": 45.2,
    "battery_percent": 85,
    "temperature": 42.5
  }
}
```

**Detections**:
```json
{
  "type": "DETECTIONS",
  "data": {
    "layer": "guardian",
    "class_name": "person",
    "confidence": 0.92,
    "bbox_area": 0.12
  }
}
```

## Configuration

Edit `laptop/config.py` to customize:

```python
# WebSocket Server
ws_host = "0.0.0.0"
ws_port = 8765
ws_max_clients = 5

# GUI
gui_width = 1400
gui_height = 900
gui_theme = "dark"

# Video
video_width = 640
video_height = 480
video_fps = 30

# Performance
metrics_update_interval = 1000  # ms
gui_update_interval = 30  # ms (~33 FPS)
```

## Troubleshooting

### "No module named 'PyQt6'"

```bash
pip install PyQt6==6.6.1
```

### "WebSocket connection refused"

- Check RPi5 is powered on
- Check RPi5 IP address: `ping 192.168.0.91`
- Check RPi5 main.py is running
- Check firewall settings

### "Video not displaying"

- Check RPi5 camera is connected
- Check RPi5 main.py logs
- Check WebSocket message logs

### High CPU usage

- Reduce video quality in config (video_quality: 85 → 70)
- Reduce GUI update interval (gui_update_interval: 30 → 60)
- Reduce video FPS (video_fps: 30 → 15)

## Performance

Typical resource usage:

- **CPU**: 5-15% (Windows laptop)
- **RAM**: 150-250 MB
- **Network**: 50-100 Mbps (for 30 FPS video)

## Files

```
laptop/
├── __init__.py              # Package init + exports
├── config.py                # Configuration
├── protocol.py              # Message protocol
├── requirements.txt         # Dependencies
├── README.md                # This file
├── gui/                     # PyQt6 GUI components
│   ├── __init__.py
│   ├── cortex_dashboard.py  # Main dashboard UI (basic)
│   └── cortex_ui.py         # Dashboard UI (custom-ui version)
├── server/                  # Server implementations
│   ├── __init__.py
│   ├── websocket_server.py  # Legacy WebSocket server
│   ├── fastapi_server.py    # FastAPI + WebSocket server
│   └── fastapi_integration.py  # FastAPI + PyQt6 integration
└── cli/                     # CLI entry points
    ├── __init__.py
    └── start_dashboard.py   # Main launcher
```

## Next Steps

1. Install dependencies: `pip install -r laptop/requirements.txt`
2. Start dashboard: `python -m laptop.start_dashboard`
3. Sync to RPi5: Use `sync.bat`
4. Run on RPi5: `ssh cortex@192.168.0.91 "cd ~/ProjectCortex/rpi5 && python main.py"`
5. Watch real-time data flow! 🚀

---

**Author**: Haziq (@IRSPlays)
**Date**: January 8, 2026
**Version**: 2.0.0
