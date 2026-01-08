# Laptop Dashboard - Installation & Testing Guide

**Complete guide to setting up and testing the ProjectCortex v2.0 Laptop Dashboard**

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Testing](#testing)
5. [Integration with RPi5](#integration-with-rpi5)
6. [Troubleshooting](#troubleshooting)

---

## 🎯 Overview

The laptop dashboard is a **PyQt6-based real-time monitoring system** that:

✅ **Receives live video** from RPi5 camera (30 FPS)
✅ **Displays system metrics** (FPS, RAM, CPU, battery, temperature)
✅ **Shows detection logs** (real-time object detections from Layer 0/1)
✅ **Multi-client support** (connect up to 5 RPi5 devices)
✅ **Professional dark theme** for competition demos
✅ **Thread-safe architecture** (asyncio WebSocket + PyQt6 signals)

**Tech Stack**:
- **GUI**: PyQt6 (cross-platform desktop framework)
- **Networking**: websockets (asyncio-based)
- **Threading**: Qt signals/slots for thread-safe updates

---

## 📦 Installation

### Step 1: Install Python Dependencies

On your **laptop** (Windows):

```bash
# Navigate to project directory
cd C:\Users\Haziq\Documents\ProjectCortex

# Install laptop dashboard dependencies
pip install -r laptop/requirements.txt
```

**Dependencies**:
- `PyQt6==6.6.1` - GUI framework
- `websockets==12.0` - WebSocket client/server

### Step 2: Verify Installation

```bash
python -c "import PyQt6; import websockets; print('✅ All dependencies installed')"
```

---

## ⚙️ Configuration

Default settings in `laptop/config.py`:

```python
# WebSocket Server
ws_host = "0.0.0.0"  # Listen on all interfaces
ws_port = 8765
ws_max_clients = 5

# GUI
gui_width = 1400
gui_height = 900
gui_theme = "dark"

# Video Display
video_width = 640
video_height = 480
video_fps = 30
video_quality = 85  # JPEG quality (1-100)
```

**To customize**: Edit `laptop/config.py` before starting the dashboard.

---

## 🧪 Testing

### Test 1: Start Dashboard (Standalone)

```bash
# From project root
python -m laptop.start_dashboard
```

**Expected Output**:
```
============================================================
ProjectCortex v2.0 - Laptop Dashboard
============================================================
✅ Dashboard initialized
🧵 Starting WebSocket server thread...
✅ WebSocket client started
🚀 Starting WebSocket server thread...
✅ Connected to laptop dashboard
   WebSocket: 0.0.0.0:8765
   GUI: 1400x900
   Waiting for RPi5 connections...
```

**Expected GUI**:
- Dashboard window opens (1400x900)
- Video panel shows: "📹 Waiting for video stream..."
- Metrics panel shows: "--" for all values
- System log shows: "Dashboard started successfully", "Waiting for RPi5 connections..."

### Test 2: Test WebSocket Connection (RPi5 → Laptop)

**On RPi5** (via SSH):

```bash
# Connect to RPi5
ssh cortex@192.168.0.91

# Navigate to project
cd ~/ProjectCortex/rpi5

# Run WebSocket client test
python websocket_client.py
```

**This will**:
- Connect to laptop dashboard (192.168.0.91:8765)
- Send fake video frames (30 FPS)
- Send fake metrics (every 1s)
- Send fake detections

**Expected on Laptop**:
- Video panel: Shows random noise (test frames)
- Metrics panel: Updates with test values
- Detection log: Shows "GUARDIAN: person (0.92)"
- System log: Shows connection events

### Test 3: End-to-End Test (With RPi5 main.py)

**Prerequisites**:
1. Dashboard running on laptop
2. RPi5 synced with latest code
3. Camera connected to RPi5

**On Laptop**:
```bash
python -m laptop.start_dashboard
```

**On RPi5**:
```bash
ssh cortex@192.168.0.91
cd ~/ProjectCortex/rpi5
python main.py
```

**Expected Flow**:
1. RPi5 starts, initializes all layers
2. RPi5 WebSocket client connects to laptop
3. Laptop shows: "✅ Client connected: 192.168.0.91:xxxxx"
4. Video starts streaming (30 FPS)
5. Metrics update every 1s
6. Detections appear in real-time

---

## 🔗 Integration with RPi5

### RPi5 WebSocket Client

The `rpi5/websocket_client.py` provides a **thread-safe API**:

```python
from rpi5.websocket_client import RPiWebSocketClient

# Initialize client
ws_client = RPiWebSocketClient(
    host="192.168.0.91",  # Laptop IP (CHANGE THIS!)
    port=8765
)

# Start client (background thread)
ws_client.start()

# Send data (thread-safe, can be called from any thread)
ws_client.send_video_frame(frame, width=640, height=480)

ws_client.send_metrics(
    fps=30.0,
    ram_mb=2048,
    ram_percent=52.3,
    cpu_percent=45.2,
    battery_percent=85,
    temperature=42.5,
    active_layers=["layer0", "layer1"],
    current_mode="TEXT_PROMPTS"
)

ws_client.send_detection(
    layer="guardian",
    class_name="person",
    confidence=0.92,
    bbox_area=0.12,
    source="base"
)

# Stop client (cleanup)
ws_client.stop()
```

### Integration in main.py

**Update `rpi5/main.py`** to include WebSocket client:

```python
# In CortexSystem.__init__():
self.ws_client = RPiWebSocketClient(
    host="192.168.0.91",  # Laptop IP
    port=8765
)
self.ws_client.start()

# In _main_loop():
# After getting detections
for detection in detections:
    self.ws_client.send_detection(
        layer=detection['layer'],
        class_name=detection['class'],
        confidence=detection['confidence'],
        bbox_area=detection.get('bbox_area', 0.0)
    )

# Every 1 second, send metrics
self.ws_client.send_metrics(...)

# Send video frames
self.ws_client.send_video_frame(frame, width=640, height=480)

# In cleanup():
self.ws_client.stop()
```

---

## 🔧 Troubleshooting

### Issue 1: "No module named 'PyQt6'"

**Solution**:
```bash
pip install PyQt6==6.6.1
```

### Issue 2: "WebSocket connection refused"

**Symptoms**:
- RPi5 can't connect to laptop
- Error: "ConnectionRefusedError"

**Solutions**:
1. **Check laptop IP is correct**:
   ```bash
   # On laptop
   ipconfig  # Windows
   # Find "IPv4 Address" (e.g., 192.168.0.91)
   ```

2. **Check firewall**:
   ```bash
   # Windows - Allow Python through firewall
   # Or temporarily disable firewall for testing
   ```

3. **Check dashboard is running**:
   ```bash
   # On laptop, check for process
   tasklist | findstr python
   ```

4. **Check port is listening**:
   ```bash
   # On laptop
   netstat -an | findstr 8765
   # Should show: LISTENING on 0.0.0.0:8765
   ```

### Issue 3: Video not displaying

**Symptoms**:
- Dashboard connects but video panel stays black
- "📹 Waiting for video stream..."

**Solutions**:
1. **Check RPi5 camera is working**:
   ```bash
   # On RPi5
   libcamera-hello --list-cameras
   ```

2. **Check video frames are being sent**:
   - Look for logs: "📥 Received VIDEO_FRAME"
   - Check RPi5 main.py logs

3. **Check base64 encoding**:
   - Verify frame data is properly encoded
   - Check JPEG quality setting

### Issue 4: High CPU usage

**Symptoms**:
- Laptop CPU usage > 50%
- Dashboard laggy

**Solutions**:
1. **Reduce video quality**:
   ```python
   # In laptop/config.py
   video_quality = 70  # (default: 85)
   ```

2. **Reduce GUI update rate**:
   ```python
   # In laptop/config.py
   gui_update_interval = 60  # (default: 30ms)
   ```

3. **Reduce video FPS**:
   ```python
   # In rpi5/main.py
   # Send video every 2nd frame
   if frame_count % 2 == 0:
       ws_client.send_video_frame(frame)
   ```

### Issue 5: Detections not showing

**Symptoms**:
- Video and metrics work, but detection log empty

**Solutions**:
1. **Check detections are being generated**:
   ```bash
   # On RPi5
   # Check logs for "🎯 [LAYER 1] Detected X objects"
   ```

2. **Check WebSocket messages**:
   ```bash
   # Look for logs: "📥 Received DETECTIONS"
   ```

3. **Check layer integration**:
   - Verify Layer 0/1 are using HybridMemoryManager
   - Check main.py is calling `ws_client.send_detection()`

---

## 📊 Performance Optimization

### Recommended Settings for Competition

```python
# laptop/config.py
video_quality = 85  # Good balance of quality/size
video_fps = 30      # Smooth video
gui_update_interval = 30  # ~33 FPS for GUI
metrics_update_interval = 1000  # Update metrics every 1s
```

### Network Bandwidth

**Estimated usage** (30 FPS, 640x480):
- **With JPEG quality 85**: ~50-100 Mbps
- **With JPEG quality 70**: ~30-60 Mbps

**If WiFi is slow**, reduce quality or FPS:

```python
# laptop/config.py
video_quality = 70  # Lower quality
# OR
# rpi5/main.py
# Send every 3rd frame
if frame_count % 3 == 0:
    ws_client.send_video_frame(frame)
```

---

## ✅ Checklist

Before competition day:

- [ ] Install PyQt6 and websockets on laptop
- [ ] Test dashboard starts successfully
- [ ] Find laptop IP address
- [ ] Update RPi5 client with laptop IP
- [ ] Test RPi5 → Laptop connection
- [ ] Verify video streaming works
- [ ] Verify metrics update
- [ ] Verify detections show in log
- [ ] Test with real camera (not just simulated)
- [ ] Test for 30+ minutes continuous operation
- [ ] Monitor CPU/RAM usage
- [ ] Have backup plan if WiFi fails

---

## 🚀 Quick Start (Copy & Paste)

```bash
# ========== ON LAPTOP ==========
cd C:\Users\Haziq\Documents\ProjectCortex

# Install dependencies
pip install PyQt6==6.6.1 websockets==12.0

# Start dashboard
python -m laptop.start_dashboard

# ========== ON RPI5 ==========
ssh cortex@192.168.0.91
cd ~/ProjectCortex/rpi5

# Run main system
python main.py
```

---

## 📁 File Structure

```
ProjectCortex/
├── laptop/
│   ├── __init__.py              # Package init
│   ├── config.py                # Configuration
│   ├── protocol.py              # Message protocol (14 types)
│   ├── websocket_server.py      # WebSocket server
│   ├── cortex_dashboard.py      # PyQt6 GUI (7 widgets)
│   ├── start_dashboard.py       # Main launcher
│   ├── requirements.txt         # Dependencies
│   └── README.md               # Documentation
│
└── rpi5/
    ├── main.py                  # Main orchestrator (to be updated)
    └── websocket_client.py      # WebSocket client ✅ NEW
```

---

## 🎯 Next Steps

1. ✅ **Test standalone dashboard** (no RPi5 needed)
2. ✅ **Test WebSocket client** (with fake data)
3. ⏳ **Integrate client into main.py**
4. ⏳ **Test end-to-end with real camera**
5. ⏳ **Optimize performance**
6. ⏳ **Deploy to competition setup**

---

**Status**: ✅ Laptop Dashboard **COMPLETE** and ready for testing!

**Author**: Haziq (@IRSPlays)
**Date**: January 8, 2026
**Version**: 2.0.0
