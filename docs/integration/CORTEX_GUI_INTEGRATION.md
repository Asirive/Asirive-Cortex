# 🔌 Integration Guide: Adding WebSocket Client to cortex_gui.py

**Objective:** Integrate `rpi_websocket_client.py` into the existing Tkinter GUI (`src/cortex_gui.py`) to send real-time data to the laptop server.

**Time Estimate:** 30-60 minutes  
**Difficulty:** Medium (requires understanding of cortex_gui.py structure)

---

## 📋 Prerequisites

1. ✅ Laptop server running: `python laptop/start_laptop_server.py`
2. ✅ Laptop IP address known (e.g., `192.168.1.100`)
3. ✅ Both devices on same WiFi network
4. ✅ Firewall allows Port 8765 (WebSocket)

---

## 🔧 Step-by-Step Integration

### Step 1: Import the WebSocket Client

**Location:** Top of `src/cortex_gui.py` (with other imports)

```python
# Add this import near the top
from src.rpi_websocket_client import RPiWebSocketClient
import base64
import cv2
```

### Step 2: Initialize WebSocket Client in `__init__`

**Location:** Inside `CortexGUI.__init__()` method

**Find this section:**
```python
class CortexGUI:
    def __init__(self, root):
        self.root = root
        # ... existing initialization ...
```

**Add after existing initialization:**
```python
        # ============ WEBSOCKET CLIENT (TIER 2 INTEGRATION) ============
        
        # Get laptop server IP from config or environment
        LAPTOP_SERVER_IP = os.getenv("CORTEX_LAPTOP_IP", "192.168.1.100")  # Change this!
        LAPTOP_SERVER_PORT = 8765
        
        self.ws_client = RPiWebSocketClient(
            server_url=f"ws://{LAPTOP_SERVER_IP}:{LAPTOP_SERVER_PORT}",
            device_id="rpi5_wearable_001",  # Unique ID for this device
            reconnect_interval=5,
            enable_metrics=True,
            enable_detections=True,
            enable_video=True,  # Set False if bandwidth limited
            enable_audio=True,
            enable_memory=True
        )
        
        # Set callbacks
        self.ws_client.on_connected = self._on_ws_connected
        self.ws_client.on_disconnected = self._on_ws_disconnected
        self.ws_client.on_error = self._on_ws_error
        
        # Start client
        self.ws_client.start()
        
        logger.info(f"✅ WebSocket client initialized (Server: {LAPTOP_SERVER_IP}:{LAPTOP_SERVER_PORT})")
```

### Step 3: Add WebSocket Callbacks

**Location:** Add these methods to the `CortexGUI` class

```python
    def _on_ws_connected(self):
        """Called when WebSocket connects to laptop server."""
        logger.info("✅ Connected to laptop server")
        
        # Send initial status
        self.ws_client.send_status("info", "RPi wearable connected and ready")
    
    def _on_ws_disconnected(self):
        """Called when WebSocket disconnects from laptop server."""
        logger.warning("🔌 Disconnected from laptop server")
    
    def _on_ws_error(self, error: str):
        """Called when WebSocket encounters an error."""
        logger.error(f"❌ WebSocket error: {error}")
```

### Step 4: Send Metrics (Every Frame)

**Location:** Find the frame processing loop (usually in a method like `process_frame()` or `update()`)

**Find this pattern:**
```python
def process_frame(self):
    # ... existing frame processing ...
    
    # Calculate FPS
    current_fps = ...
    
    # Calculate latency
    current_latency = ...
    
    # Get RAM usage
    ram_usage = ...
```

**Add after metrics calculation:**
```python
    # Send metrics to laptop server
    if hasattr(self, 'ws_client') and self.ws_client.connected:
        try:
            # Get system metrics
            import psutil
            
            ram = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            # Get battery (if available)
            battery = psutil.sensors_battery()
            battery_percent = battery.percent if battery else None
            
            # Determine active layer
            active_layer = self._get_active_layer_name()  # You'll need to implement this
            
            # Send to laptop
            self.ws_client.send_metrics(
                fps=current_fps,
                latency_ms=current_latency * 1000,  # Convert to ms
                ram_usage_gb=ram.used / (1024 ** 3),
                ram_total_gb=ram.total / (1024 ** 3),
                cpu_usage_percent=cpu_percent,
                battery_percent=battery_percent,
                active_layer=active_layer
            )
        
        except Exception as e:
            logger.error(f"❌ Failed to send metrics: {e}")
```

### Step 5: Send Detections (When Objects Detected)

**Location:** Find where YOLO detections are processed

**Find this pattern:**
```python
def process_detections(self, detections):
    # ... process YOLO results ...
    
    merged_detections = "person, car, bicycle"  # Example
    detection_count = 3
```

**Add after detection processing:**
```python
    # Send detections to laptop server
    if hasattr(self, 'ws_client') and self.ws_client.connected:
        try:
            # Determine current YOLOE mode
            yoloe_mode = self._get_yoloe_mode()  # e.g., "Prompt-Free", "Text Prompts", "Visual Prompts"
            
            self.ws_client.send_detections(
                merged_detections=merged_detections,
                detection_count=detection_count,
                yoloe_mode=yoloe_mode,
                layer0_detections=layer0_results if 'layer0_results' in locals() else None,
                layer1_detections=layer1_results if 'layer1_results' in locals() else None
            )
        
        except Exception as e:
            logger.error(f"❌ Failed to send detections: {e}")
```

### Step 6: Send Video Frames (Optional - Bandwidth Intensive)

**Location:** In the frame processing loop (same as Step 4)

**Add after frame processing:**
```python
    # Send video frame to laptop server (throttled to reduce bandwidth)
    if hasattr(self, 'ws_client') and self.ws_client.connected:
        # Only send every 3rd frame (10 FPS if processing at 30 FPS)
        if not hasattr(self, '_ws_frame_counter'):
            self._ws_frame_counter = 0
        
        self._ws_frame_counter += 1
        
        if self._ws_frame_counter % 3 == 0:  # Throttle to 10 FPS
            try:
                # Encode frame to JPEG
                _, buffer = cv2.imencode(
                    '.jpg',
                    current_frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 75]  # Lower quality = less bandwidth
                )
                
                # Convert to base64
                frame_b64 = base64.b64encode(buffer).decode('utf-8')
                
                # Send to laptop
                self.ws_client.send_video_frame(frame_b64)
            
            except Exception as e:
                logger.error(f"❌ Failed to send video frame: {e}")
```

### Step 7: Send Audio Events (When TTS/STT Triggers)

**Location:** Find where TTS or STT events happen

**Find this pattern:**
```python
def speak_text(self, text):
    # ... TTS code ...
    logger.info(f"🔊 Speaking: {text}")
```

**Add after TTS trigger:**
```python
    # Send audio event to laptop server
    if hasattr(self, 'ws_client') and self.ws_client.connected:
        try:
            self.ws_client.send_audio_event(
                event="tts_started",
                layer="Layer 2 Thinker",
                text=text,
                duration_ms=None  # Will be filled when TTS completes
            )
        
        except Exception as e:
            logger.error(f"❌ Failed to send audio event: {e}")
```

### Step 8: Send Memory Events (When Objects Saved/Recalled)

**Location:** Find where memory save/recall happens (Layer 3)

**Find this pattern:**
```python
def save_object_memory(self, object_name, location, image_path):
    # ... save to database ...
    logger.info(f"💾 Saved: {object_name} at {location}")
```

**Add after save:**
```python
    # Send memory event to laptop server
    if hasattr(self, 'ws_client') and self.ws_client.connected:
        try:
            self.ws_client.send_memory_event(
                event="object_saved",
                object_name=object_name,
                location=location,
                image_path=image_path
            )
        
        except Exception as e:
            logger.error(f"❌ Failed to send memory event: {e}")
```

### Step 9: Send Status Updates (For Errors/Warnings)

**Location:** Wherever you log important events

**Example:**
```python
def on_layer_switch(self, from_layer, to_layer):
    logger.info(f"🔄 Switching: {from_layer} → {to_layer}")
    
    # Send status to laptop
    if hasattr(self, 'ws_client') and self.ws_client.connected:
        self.ws_client.send_status(
            "info",
            f"Layer switch: {from_layer} → {to_layer}"
        )
```

### Step 10: Cleanup on Exit

**Location:** Find the cleanup/exit method

**Find this pattern:**
```python
def cleanup(self):
    # ... existing cleanup ...
    logger.info("👋 Shutting down...")
```

**Add before final shutdown:**
```python
    # Stop WebSocket client
    if hasattr(self, 'ws_client'):
        logger.info("🛑 Stopping WebSocket client...")
        self.ws_client.stop()
```

---

## 🧪 Testing Integration

### Test 1: Check Connection

**Start laptop server:**
```bash
python laptop/start_laptop_server.py
```

**Start RPi GUI:**
```bash
python src/cortex_gui.py
```

**Expected:**
- Laptop GUI shows "✅ RPi connected (1 client(s))"
- RPi logs show "✅ Connected to laptop server"

### Test 2: Verify Metrics

**Look at laptop GUI metrics dashboard:**
- FPS should update in real-time
- Latency should show current processing time
- RAM/CPU should reflect RPi usage
- Battery should show percentage (or N/A)

### Test 3: Verify Detections

**Point RPi camera at objects:**
- Detection log on laptop should show detected objects
- Timestamps should be recent
- YOLOE mode should be correct

### Test 4: Verify Video (If Enabled)

**Check laptop GUI video feed:**
- Video should appear within 2-3 seconds of connection
- Should update at ~10 FPS (throttled)
- Quality should be decent (not too pixelated)

### Test 5: Test Disconnection/Reconnection

**Disconnect WiFi on RPi:**
- Laptop GUI should show "🔌 RPi disconnected"
- RPi logs should show "🔌 Disconnected from laptop server"

**Reconnect WiFi:**
- Should auto-reconnect within 5 seconds
- Laptop GUI should show "✅ RPi connected"
- Metrics should resume updating

---

## ⚙️ Configuration Options

### Environment Variables (Recommended)

Create `.env` file in project root:

```bash
# Laptop Server Configuration
CORTEX_LAPTOP_IP=192.168.1.100
CORTEX_LAPTOP_PORT=8765

# Feature Flags
CORTEX_ENABLE_VIDEO=true
CORTEX_ENABLE_METRICS=true
CORTEX_ENABLE_DETECTIONS=true
```

Load in `cortex_gui.py`:
```python
from dotenv import load_dotenv
load_dotenv()

LAPTOP_SERVER_IP = os.getenv("CORTEX_LAPTOP_IP", "localhost")
```

### Config File (Alternative)

Create `config/websocket_client.yaml`:

```yaml
laptop_server:
  host: "192.168.1.100"
  port: 8765
  device_id: "rpi5_wearable_001"

features:
  enable_metrics: true
  enable_detections: true
  enable_video: true
  enable_audio: true
  enable_memory: true

performance:
  video_throttle: 3  # Send every 3rd frame
  jpeg_quality: 75   # 0-100
  reconnect_interval: 5  # seconds
```

Load in `cortex_gui.py`:
```python
import yaml

with open("config/websocket_client.yaml") as f:
    config = yaml.safe_load(f)

LAPTOP_SERVER_IP = config["laptop_server"]["host"]
```

---

## 🐛 Common Issues

### Issue: "Connection Refused"

**Possible Causes:**
1. Laptop server not running
2. Wrong IP address
3. Firewall blocking Port 8765

**Solutions:**
```bash
# 1. Verify laptop server running
python laptop/start_laptop_server.py

# 2. Verify laptop IP
ifconfig | grep "inet "

# 3. Allow port in firewall
sudo ufw allow 8765/tcp
```

### Issue: "Video not showing in laptop GUI"

**Possible Causes:**
1. `enable_video=False` in client
2. Frame encoding fails
3. Bandwidth too limited

**Solutions:**
```python
# 1. Enable video
self.ws_client = RPiWebSocketClient(
    enable_video=True  # Make sure this is True
)

# 2. Check encoding
_, buffer = cv2.imencode('.jpg', frame)
if buffer is None:
    logger.error("❌ Failed to encode frame")

# 3. Reduce quality/resolution
cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])  # Lower quality
```

### Issue: "Metrics not updating"

**Possible Causes:**
1. `send_metrics()` not called every frame
2. Exception in metrics calculation
3. Connection dropped

**Solutions:**
```python
# 1. Add debug logging
logger.debug(f"Sending metrics: FPS={fps}, Latency={latency}ms")
self.ws_client.send_metrics(...)

# 2. Wrap in try-except
try:
    self.ws_client.send_metrics(...)
except Exception as e:
    logger.error(f"Failed to send metrics: {e}")

# 3. Check connection status
if self.ws_client.connected:
    logger.info("✅ WebSocket connected")
else:
    logger.warning("🔌 WebSocket disconnected")
```

### Issue: "High latency or lag"

**Possible Causes:**
1. Too many video frames sent
2. Network congestion
3. Large message queue

**Solutions:**
```python
# 1. Throttle video frames more aggressively
if self._ws_frame_counter % 5 == 0:  # 6 FPS instead of 10 FPS
    self.ws_client.send_video_frame(frame_b64)

# 2. Reduce JPEG quality
cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])

# 3. Disable video for now
self.ws_client = RPiWebSocketClient(enable_video=False)
```

---

## 📊 Performance Tuning

### Recommended Settings for YIA 2026 Demo

```python
# Balanced performance (works on most networks)
self.ws_client = RPiWebSocketClient(
    server_url=f"ws://{LAPTOP_SERVER_IP}:8765",
    device_id="rpi5_wearable_001",
    reconnect_interval=5,
    enable_metrics=True,      # Always enable (low bandwidth)
    enable_detections=True,   # Always enable (low bandwidth)
    enable_video=True,        # Enable for demo (high bandwidth)
    enable_audio=True,        # Enable for demo (medium bandwidth)
    enable_memory=True        # Enable for demo (low bandwidth)
)

# Video throttling (in process_frame)
if self._ws_frame_counter % 3 == 0:  # 10 FPS
    # Encode with 75% quality
    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
```

### High-Performance Settings (5GHz WiFi)

```python
# Maximum quality for competition demos
enable_video=True
video_throttle=1  # Every frame (30 FPS)
jpeg_quality=90   # High quality
```

### Low-Bandwidth Settings (2.4GHz WiFi)

```python
# Optimized for slower networks
enable_video=True
video_throttle=5  # 6 FPS
jpeg_quality=60   # Lower quality
```

---

## ✅ Integration Checklist

- [ ] WebSocket client imported
- [ ] Client initialized in `__init__`
- [ ] Laptop IP configured
- [ ] Callbacks added (`on_connected`, `on_disconnected`, `on_error`)
- [ ] Metrics sent every frame (`send_metrics()`)
- [ ] Detections sent when objects detected (`send_detections()`)
- [ ] Video frames sent (if enabled, `send_video_frame()`)
- [ ] Audio events sent (TTS/STT, `send_audio_event()`)
- [ ] Memory events sent (save/recall, `send_memory_event()`)
- [ ] Status updates sent (errors/warnings, `send_status()`)
- [ ] Cleanup on exit (`ws_client.stop()`)
- [ ] Tested with laptop server
- [ ] Connection/reconnection works
- [ ] Metrics update in real-time
- [ ] Detections appear in log
- [ ] Video feed shows in GUI (if enabled)

---

## 🎉 Success!

If all steps completed successfully:
- ✅ Laptop GUI shows "✅ RPi connected"
- ✅ Metrics update in real-time (FPS, latency, RAM, CPU, battery)
- ✅ Detections appear in log as objects detected
- ✅ Video feed shows camera view (if enabled)
- ✅ System log shows status messages

**You're ready for YIA 2026 competition demos!** 🏆

---

## 📚 Additional Resources

- [WebSocket Client API Reference](../src/rpi_websocket_client.py)
- [Message Protocol Documentation](../laptop/protocol.py)
- [Laptop Server README](../laptop/README.md)
- [Troubleshooting Guide](../laptop/IMPLEMENTATION_COMPLETE.md#-troubleshooting)

---

**Last Updated:** January 3, 2026  
**Author:** Haziq (@IRSPlays) + GitHub Copilot (CTO)
