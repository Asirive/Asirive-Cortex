# 🔌 RPi WebSocket Client - Testing Guide

**Location:** `src/rpi_websocket_client.py`  
**Status:** ✅ Standalone (no dependencies on laptop module)

---

## Quick Test (Windows/Mac/Linux)

### 1. Install Dependencies

```bash
pip install websockets
```

### 2. Start Laptop Server

```bash
# In one terminal
python laptop/start_laptop_server.py
```

### 3. Run Test Client

```bash
# In another terminal
cd src
python test_websocket_client.py
```

**Expected Output:**
```
✅ Connected to laptop server!
📊 Sent metrics: FPS=30.2, Latency=54.3ms, RAM=2.8GB
🎯 Sent detections: person, car, bicycle (Mode: Prompt-Free)
```

---

## Using in cortex_gui.py

```python
from src.rpi_websocket_client import RPiWebSocketClient

class CortexGUI:
    def __init__(self):
        # Initialize WebSocket client
        self.ws_client = RPiWebSocketClient(
            server_url="ws://192.168.1.100:8765",  # Your laptop IP
            device_id="rpi5_wearable_001"
        )
        self.ws_client.start()
    
    def process_frame(self):
        # Send metrics every frame
        self.ws_client.send_metrics(
            fps=self.current_fps,
            latency_ms=self.current_latency * 1000,
            ram_usage_gb=self.ram_usage,
            ram_total_gb=4.0,
            cpu_usage_percent=self.cpu_usage,
            battery_percent=self.battery_percent,
            active_layer="Layer 1 Learner"
        )
```

---

## API Reference

### `RPiWebSocketClient(server_url, device_id, ...)`

**Parameters:**
- `server_url`: WebSocket server URL (e.g., `"ws://192.168.1.100:8765"`)
- `device_id`: Unique identifier for this RPi device
- `reconnect_interval`: Seconds to wait before reconnecting (default: 5)
- `enable_metrics`: Enable metrics sending (default: True)
- `enable_detections`: Enable detection sending (default: True)
- `enable_video`: Enable video frame sending (default: True)
- `enable_audio`: Enable audio event sending (default: True)
- `enable_memory`: Enable memory event sending (default: True)

**Methods:**
- `start()` - Start the client (non-blocking)
- `stop()` - Stop the client gracefully
- `send_metrics(...)` - Send performance metrics
- `send_detections(...)` - Send YOLO detections
- `send_video_frame(frame_data)` - Send base64-encoded JPEG frame
- `send_audio_event(...)` - Send audio event (TTS/STT)
- `send_memory_event(...)` - Send memory event (save/recall)
- `send_status(level, status)` - Send status update
- `get_statistics()` - Get client statistics

**Callbacks:**
- `on_connected()` - Called when connected to server
- `on_disconnected()` - Called when disconnected from server
- `on_error(error)` - Called when error occurs

---

## Troubleshooting

### "Connection Refused"

**Cause:** Laptop server not running or firewall blocking port

**Solution:**
```bash
# Start laptop server first
python laptop/start_laptop_server.py

# Allow port 8765 (Linux)
sudo ufw allow 8765/tcp

# Windows: Windows Firewall > Advanced Settings > Inbound Rules
# New Rule > Port > TCP > 8765 > Allow
```

### "ModuleNotFoundError: No module named 'websockets'"

**Cause:** Missing dependency

**Solution:**
```bash
pip install websockets
```

### "Not connected. Is laptop server running?"

**Cause:** Wrong IP address or server not running

**Solution:**
```bash
# Find laptop IP
ifconfig | grep "inet "  # Linux/Mac
ipconfig                 # Windows

# Update server_url in code
server_url="ws://192.168.1.100:8765"  # Use your laptop IP
```

---

## Network Setup

### Find Laptop IP Address

**Linux/Mac:**
```bash
ifconfig | grep "inet "
# Look for 192.168.x.x or 10.0.x.x
```

**Windows:**
```powershell
ipconfig
# Look for IPv4 Address under your WiFi adapter
```

### Same Network Required

Both laptop and RPi must be on the same WiFi network.

**Example:**
- Laptop: `192.168.1.100` (WiFi)
- RPi: `192.168.1.50` (WiFi)
- Server URL: `ws://192.168.1.100:8765`

---

## File Structure

```
src/
├── rpi_websocket_client.py     # ⭐ Standalone WebSocket client
├── test_websocket_client.py    # Test script (simulates RPi)
├── cortex_gui.py               # Main RPi GUI (existing)
└── README_WEBSOCKET.md         # This file
```

---

## Next Steps

1. ✅ Test client works standalone: `python src/test_websocket_client.py`
2. ⏳ Integrate into cortex_gui.py: Follow [integration guide](../docs/integration/CORTEX_GUI_INTEGRATION.md)
3. ⏳ Test with real RPi camera
4. ⏳ Deploy for YIA 2026 competition

---

**Last Updated:** January 3, 2026  
**Author:** Haziq (@IRSPlays) + GitHub Copilot (CTO)
