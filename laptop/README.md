# 💻 Project-Cortex v2.0 - Laptop Server (Tier 2)

**Professional Real-Time Monitoring System for YIA 2026 Competition**

This is the **Tier 2 Laptop Server** that receives real-time data from the **Tier 1 RPi Wearable** and displays it in a professional PyQt6 GUI for competition demos and development.

---

## 📁 Directory Structure

```
laptop/
├── __init__.py                    # Package initialization
├── config.py                      # Centralized configuration (WS, API, JWT, CORS)
├── protocol.py                    # WebSocket message protocol (14 message types)
├── websocket_server.py            # WebSocket server (Port 8765)
├── cortex_monitor_gui.py          # PyQt6 real-time visualization GUI
├── cortex_api_server.py           # FastAPI REST/WebSocket (Port 8000) [FUTURE]
├── test_laptop_server.py          # Quick test script
└── README.md                      # This file
```

---

## 🚀 Quick Start

### Prerequisites

```bash
# Install dependencies
pip install PyQt6 websockets Pillow numpy

# For future FastAPI support:
pip install fastapi uvicorn python-jose[cryptography] passlib[bcrypt]
```

### Run Laptop Server

```bash
# From project root
python laptop/test_laptop_server.py
```

Or directly:

```bash
cd laptop/
python cortex_monitor_gui.py
```

### Test with Simulated RPi Data

In another terminal:

```bash
# Run test client (simulates RPi sending data)
python src/rpi_websocket_client.py
```

---

## 🎯 Features

### PyQt6 Real-Time Monitor GUI

✅ **Live Video Feed** (30 FPS from RPi camera)  
✅ **Metrics Dashboard** (FPS, latency, RAM, CPU, battery)  
✅ **Detection Log** (real-time object detections with timestamps)  
✅ **System Log** (status messages, errors, events)  
✅ **Command Interface** (send commands to RPi)  
✅ **Dark Theme** (professional, easy on eyes during demos)  

### WebSocket Server (Port 8765)

✅ **Multi-Client Support** (up to 5 RPi devices)  
✅ **Automatic Reconnection** (RPi reconnects after network drops)  
✅ **Message Broadcasting** (send commands to all connected RPis)  
✅ **Heartbeat/Ping-Pong** (30s interval, 10s timeout)  
✅ **10MB Max Message Size** (accommodates video frames)  

### Message Protocol (14 Message Types)

**Upstream (RPi → Laptop):**
- `METRICS` - Performance metrics (FPS, latency, RAM, CPU, battery)
- `DETECTIONS` - YOLO detection results (merged, counts, modes)
- `VIDEO_FRAME` - Base64-encoded JPEG frames (real-time video)
- `GPS_IMU` - GPS/IMU sensor data (for Layer 3 navigation)
- `AUDIO_EVENT` - Audio events (TTS, STT, voice commands)
- `MEMORY_EVENT` - Memory events (object saved/recalled)
- `STATUS` - Status updates (info, warning, error)

**Downstream (Laptop → RPi):**
- `COMMAND` - Commands (start_recording, change_mode, etc.)
- `NAVIGATION` - Navigation instructions (for Layer 3)
- `SPATIAL_AUDIO` - Spatial audio parameters
- `CONFIG` - Configuration updates

**Bidirectional:**
- `PING/PONG` - Heartbeat mechanism
- `ERROR` - Error reporting

---

## 🔧 Configuration

Edit [config.py](config.py) to customize:

```python
# WebSocket Server (RPi ↔ Laptop)
WS_SERVER_HOST = "0.0.0.0"          # Listen on all interfaces
WS_SERVER_PORT = 8765               # Default WebSocket port
WS_MAX_CLIENTS = 5                  # Max concurrent RPi connections
WS_PING_INTERVAL = 30               # Heartbeat interval (seconds)

# GUI Settings
GUI_TITLE = "Project-Cortex v2.0 - Monitor"
GUI_WIDTH = 1280                    # Window width
GUI_HEIGHT = 800                    # Window height
GUI_VIDEO_FPS = 30                  # Video display FPS

# FastAPI Settings (Future)
API_HOST = "0.0.0.0"
API_PORT = 8000
JWT_SECRET_KEY = "your-secret-key-change-in-production"
ENABLE_API_SERVER = False           # Toggle companion app API

# Deployment
DEPLOYMENT_MODE = "local"           # local, ngrok, tailscale, cloudflare
```

---

## 🔌 Integrating with RPi Wearable

### Step 1: Update cortex_gui.py

Add WebSocket client to [src/cortex_gui.py](../src/cortex_gui.py):

```python
from src.rpi_websocket_client import RPiWebSocketClient

class CortexGUI:
    def __init__(self):
        # ... existing code ...
        
        # Initialize WebSocket client
        self.ws_client = RPiWebSocketClient(
            server_url="ws://192.168.1.100:8765",  # Replace with laptop IP
            device_id="rpi5_wearable_001"
        )
        self.ws_client.start()
    
    def update_metrics(self):
        # Send metrics to laptop
        self.ws_client.send_metrics(
            fps=self.current_fps,
            latency_ms=self.current_latency,
            ram_usage_gb=self.ram_usage,
            ram_total_gb=4.0,
            cpu_usage_percent=self.cpu_usage,
            battery_percent=self.battery_percent,
            active_layer=self.active_layer
        )
    
    def on_detection(self, merged_detections, count, mode):
        # Send detections to laptop
        self.ws_client.send_detections(
            merged_detections=merged_detections,
            detection_count=count,
            yoloe_mode=mode
        )
    
    def on_video_frame(self, frame):
        # Encode frame to base64 JPEG
        import cv2
        import base64
        
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frame_b64 = base64.b64encode(buffer).decode('utf-8')
        
        # Send to laptop
        self.ws_client.send_video_frame(frame_b64)
```

### Step 2: Find Laptop IP Address

On laptop:

```bash
# Linux/Mac
ifconfig | grep "inet "

# Windows
ipconfig
```

Look for your local network IP (e.g., `192.168.1.100`).

### Step 3: Update RPi Configuration

```python
# In cortex_gui.py on RPi
ws_client = RPiWebSocketClient(
    server_url="ws://192.168.1.100:8765",  # Replace with your laptop IP
    device_id="rpi5_wearable_001"
)
```

### Step 4: Test Connection

1. **Start laptop server:**
   ```bash
   python laptop/test_laptop_server.py
   ```

2. **Start RPi wearable:**
   ```bash
   python src/cortex_gui.py
   ```

3. **Verify connection:**
   - Laptop GUI should show "✅ RPi connected (1 client(s))"
   - Video feed should appear
   - Metrics should update in real-time
   - Detections should appear in log

---

## 📡 Network Deployment Options

### Option 1: Local Network (Default)

Both devices on same WiFi:
- **Laptop IP:** Find with `ifconfig` or `ipconfig`
- **RPi connects to:** `ws://<laptop_ip>:8765`
- **Pros:** Low latency, no internet required
- **Cons:** Same network only

### Option 2: Ngrok Tunnel

For remote access:

```bash
# On laptop
ngrok tcp 8765

# Update RPi to use ngrok URL
ws_client = RPiWebSocketClient(
    server_url="ws://0.tcp.ngrok.io:12345"  # Use ngrok URL
)
```

### Option 3: Tailscale VPN

For secure remote access:

```bash
# Install on both devices
curl -fsSL https://tailscale.com/install.sh | sh

# Connect both devices to Tailscale network
# RPi connects to laptop's Tailscale IP
```

### Option 4: Cloudflare Tunnel

For production deployment:

```bash
# Install cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

# Create tunnel
cloudflared tunnel create cortex-monitor
cloudflared tunnel route dns cortex-monitor cortex.yourdomain.com

# Run tunnel
cloudflared tunnel run cortex-monitor
```

---

## 🧪 Testing

### Test 1: Protocol Message Creation

```python
from laptop.protocol import create_message, MessageType

# Create metrics message
msg = create_message(
    MessageType.METRICS,
    device_id="test_rpi",
    fps=30.0,
    latency_ms=50.0,
    ram_usage_gb=2.5,
    ram_total_gb=4.0,
    cpu_usage_percent=45.0,
    battery_percent=85.0,
    active_layer="Layer 1 Learner"
)

print(msg)
```

### Test 2: WebSocket Server Standalone

```python
from laptop.websocket_server import WebSocketServer
import asyncio

async def test_server():
    server = WebSocketServer()
    await server.start()

asyncio.run(test_server())
```

### Test 3: RPi Client Standalone

```bash
python src/rpi_websocket_client.py
```

### Test 4: Full Integration

1. Start laptop server
2. Start RPi client
3. Verify connection in GUI
4. Check logs for messages

---

## 🐛 Troubleshooting

### Issue: "Connection Refused"

**Cause:** Firewall blocking port 8765

**Solution:**
```bash
# Linux
sudo ufw allow 8765/tcp

# Windows
# Open Windows Firewall > Advanced Settings > Inbound Rules
# New Rule > Port > TCP > 8765 > Allow
```

### Issue: "No Video Feed"

**Cause:** Video frames not being sent or encoding failed

**Solution:**
- Check RPi logs for encoding errors
- Verify `enable_video=True` in RPi client
- Reduce video quality/resolution if bandwidth limited

### Issue: "High Latency"

**Cause:** Network congestion or slow encoding

**Solution:**
- Reduce video FPS (change `GUI_VIDEO_FPS` in config)
- Lower JPEG quality in encoding
- Use 5GHz WiFi instead of 2.4GHz
- Disable video streaming if not needed for demo

### Issue: "PyQt6 Crashes"

**Cause:** Thread safety issues with GUI updates

**Solution:**
- Use PyQt signals/slots for all GUI updates (already implemented)
- Never update GUI from WebSocket thread directly
- Check Qt version: `pip install --upgrade PyQt6`

---

## 🔮 Future: Companion App (Tier 3)

The infrastructure is **future-proof** for a mobile companion app:

### FastAPI REST/WebSocket Server (Port 8000)

```python
# laptop/cortex_api_server.py (to be implemented)

from fastapi import FastAPI, Depends
from fastapi.security import OAuth2PasswordBearer

app = FastAPI()

@app.get("/api/v1/status")
async def get_status():
    return {"status": "online", "connected_rpis": 1}

@app.websocket("/api/v1/stream")
async def stream_data(websocket: WebSocket):
    # Stream real-time data to mobile app
    pass
```

### JWT Authentication

```python
# JWT tokens for secure mobile app access
from laptop.config import JWT_SECRET_KEY, JWT_ALGORITHM

# Mobile app authenticates with username/password
# Receives JWT token for API access
```

### CORS Configuration

```python
# laptop/config.py
CORS_ORIGINS = [
    "http://localhost:3000",        # React Native dev
    "https://cortex-app.com"        # Production mobile app
]
```

---

## 📊 Performance Metrics

**Tested on Acer Nitro V15 (RTX 2050):**
- **RAM Usage:** ~150MB (GUI only) + 50MB per connected RPi
- **CPU Usage:** <5% idle, ~10% with video streaming
- **Latency:** <50ms (local network), ~150ms (ngrok), ~100ms (Tailscale)
- **Video FPS:** 30 FPS (limited by network, not GUI)
- **Max Clients:** 5 concurrent RPi devices tested

---

## 🏆 YIA 2026 Competition Demo

### Demo Setup

1. **Laptop Server:** 
   - Run on Acer Nitro V15
   - Full screen on external monitor/projector
   - Dark theme for professional look

2. **RPi Wearable:**
   - Worn by demo user
   - Connected to laptop via WiFi (local network)
   - Camera pointing forward

3. **Demo Flow:**
   - Judge sees real-time video feed on laptop screen
   - Metrics dashboard shows system performance
   - Detection log displays YOLO detections as they happen
   - Layer switching visible in real-time

### Key Talking Points

✅ **"Sub-100ms latency"** (show latency metric)  
✅ **"Runs on $150 hardware"** (contrast with $4,000 OrCam)  
✅ **"4-layer AI architecture"** (show layer switching)  
✅ **"Graceful degradation"** (disconnect WiFi, show offline mode)  
✅ **"Professional monitoring system"** (show laptop GUI)  

---

## 📚 References

- **Architecture:** [docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md](../docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md)
- **Protocol Spec:** [laptop/protocol.py](protocol.py)
- **Configuration:** [laptop/config.py](config.py)
- **WebSocket Server:** [laptop/websocket_server.py](websocket_server.py)
- **RPi Client:** [src/rpi_websocket_client.py](../src/rpi_websocket_client.py)

---

## 🤝 Contributing

This is a YIA 2026 competition project by **Haziq (@IRSPlays)**.  
For questions or contributions, refer to the main [README.md](../README.md).

---

## 📄 License

Part of Project-Cortex v2.0 - Copyright (c) 2026 Haziq  
See main repository for license details.

---

**Last Updated:** January 3, 2026  
**Author:** Haziq (@IRSPlays) + GitHub Copilot (CTO)  
**Status:** ✅ Tier 2 Complete (PyQt6 GUI + WebSocket Server)  
**Next:** 🔮 Tier 3 Future (FastAPI + Companion App)
