# 🎯 Implementation Plan: Laptop GUI Command Panel & Video Feed

**For:** Laptop Server Agent (Other Developer)  
**From:** RPi Agent (Haziq's Co-Founder/CTO)  
**Date:** January 3, 2026  
**Priority:** HIGH (YIA 2026 Competition Demo Critical)

---

## 📋 Executive Summary

**Objective:** Add command panel to laptop monitor GUI (similar to RPi GUI bottom controls) to allow remote control of RPi wearable and enable video feed display.

**Files to Modify:**
1. `laptop/cortex_monitor_gui.py` - Add command panel with buttons
2. `laptop/websocket_server.py` - No changes needed (already supports commands)
3. `laptop/protocol.py` - No changes needed (COMMAND message type exists)

**RPi Side Integration:**
- Video feed: RPi needs to send VIDEO_FRAME messages with base64-encoded JPEG
- Command handling: RPi needs to implement command handlers (already in protocol)

---

## 🎨 UI Design Reference

### Current RPi GUI Bottom Controls (Reference Image 2)

```
┌─────────────────────────────────────────────────────────────────┐
│ Video Feed (with YOLO detections)                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ [💬 Ask Gemini: _______________] [🎯 POI] [Send 📤]            │
│                                                                 │
│ [⭕ Voice Act] [🔇 Int TTS] [🔊 3D Audio] [🎚️ AI Tier ▼]      │
│ [Testing (FREE) ▼] [🔴 Record] [🔊 Replay] [Input: Device ▼]  │
│ [1: Mic Array ▼] [Layer 1: Text Prompts ▼] [Output: 3: Spkr ▼]│
│ [Layer 1 Mode: Text Prompts ▼] [Layer 2: Testing (FREE) ▼]    │
└─────────────────────────────────────────────────────────────────┘
```

### Proposed Laptop GUI Command Panel

```
┌─────────────────────────────────────────────────────────────────┐
│ 📹 Live Camera Feed (from RPi)                                  │
│                                                                 │
│ [Waiting for video stream from RPi...]                         │
│                                                                 │
│ Make sure RPi is:                                               │
│ 1. Connected to same network                                    │
│ 2. Running cortex_gui.py with WebSocket enabled                │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ 🎮 Remote Commands (Send to RPi)                                │
│                                                                 │
│ [🎙️ Toggle Voice Activation] [🔇 Interrupt TTS] [🔊 3D Audio] │
│ [🎚️ Change Layer: Layer 1 Learner ▼] [🎛️ Tier: Testing ▼]   │
│ [🔴 Start Recording] [🛑 Stop Recording] [🔊 Replay TTS]       │
│ [🎯 Mark POI] [💾 Save Memory] [🗺️ Navigate] [⚙️ Settings]   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Implementation Steps

### **Step 1: Add Command Panel to PyQt6 GUI**

**File:** `laptop/cortex_monitor_gui.py`

**Location:** In `create_info_panel()` method, after the "Command Panel" groupbox

**Current Code (Line ~700):**
```python
# === COMMAND PANEL ===
command_group = QGroupBox("🎮 Commands")
command_layout = QVBoxLayout()

self.clear_log_btn = QPushButton("🗑️ Clear Logs")
self.clear_log_btn.clicked.connect(self.clear_logs)

command_layout.addWidget(self.clear_log_btn)
command_group.setLayout(command_layout)
layout.addWidget(command_group)
```

**Replace with:**
```python
# === COMMAND PANEL ===
command_group = QGroupBox("🎮 Remote Commands (Send to RPi)")
command_layout = QVBoxLayout()

# Row 1: Voice Controls
voice_controls_layout = QHBoxLayout()

self.voice_activation_btn = QPushButton("🎙️ Voice Activation")
self.voice_activation_btn.setCheckable(True)  # Toggle button
self.voice_activation_btn.clicked.connect(lambda: self.send_command("toggle_voice_activation"))

self.interrupt_tts_btn = QPushButton("🔇 Interrupt TTS")
self.interrupt_tts_btn.setCheckable(True)
self.interrupt_tts_btn.clicked.connect(lambda: self.send_command("toggle_interrupt_tts"))

self.spatial_audio_btn = QPushButton("🔊 3D Audio")
self.spatial_audio_btn.setCheckable(True)
self.spatial_audio_btn.clicked.connect(lambda: self.send_command("toggle_spatial_audio"))

voice_controls_layout.addWidget(self.voice_activation_btn)
voice_controls_layout.addWidget(self.interrupt_tts_btn)
voice_controls_layout.addWidget(self.spatial_audio_btn)

command_layout.addLayout(voice_controls_layout)

# Row 2: Layer/Tier Selection
layer_controls_layout = QHBoxLayout()

layer_label = QLabel("🎚️ Active Layer:")
self.layer_selector = QComboBox()
self.layer_selector.addItems([
    "Layer 0 Guardian",
    "Layer 1 Learner", 
    "Layer 2 Thinker",
    "Layer 3 Guide"
])
self.layer_selector.currentTextChanged.connect(lambda layer: self.send_command("change_layer", {"layer": layer}))

tier_label = QLabel("🎛️ Tier:")
self.tier_selector = QComboBox()
self.tier_selector.addItems([
    "Testing (FREE)",
    "Demo Mode (PAID)",
    "Auto (Cascading)",
    "Tier 0 (Live API)",
    "Tier 1 (Gemini TTS)"
])
self.tier_selector.currentTextChanged.connect(lambda tier: self.send_command("change_tier", {"tier": tier}))

layer_controls_layout.addWidget(layer_label)
layer_controls_layout.addWidget(self.layer_selector)
layer_controls_layout.addWidget(tier_label)
layer_controls_layout.addWidget(self.tier_selector)

command_layout.addLayout(layer_controls_layout)

# Row 3: Recording Controls
recording_controls_layout = QHBoxLayout()

self.start_recording_btn = QPushButton("🔴 Start Recording")
self.start_recording_btn.clicked.connect(lambda: self.send_command("start_recording"))

self.stop_recording_btn = QPushButton("🛑 Stop Recording")
self.stop_recording_btn.clicked.connect(lambda: self.send_command("stop_recording"))

self.replay_tts_btn = QPushButton("🔊 Replay TTS")
self.replay_tts_btn.clicked.connect(lambda: self.send_command("replay_tts"))

recording_controls_layout.addWidget(self.start_recording_btn)
recording_controls_layout.addWidget(self.stop_recording_btn)
recording_controls_layout.addWidget(self.replay_tts_btn)

command_layout.addLayout(recording_controls_layout)

# Row 4: Memory/Navigation
memory_controls_layout = QHBoxLayout()

self.mark_poi_btn = QPushButton("🎯 Mark POI")
self.mark_poi_btn.clicked.connect(lambda: self.send_command("mark_poi"))

self.save_memory_btn = QPushButton("💾 Save Memory")
self.save_memory_btn.clicked.connect(lambda: self.send_command("save_memory"))

self.navigate_btn = QPushButton("🗺️ Navigate")
self.navigate_btn.clicked.connect(lambda: self.send_command("navigate"))

memory_controls_layout.addWidget(self.mark_poi_btn)
memory_controls_layout.addWidget(self.save_memory_btn)
memory_controls_layout.addWidget(self.navigate_btn)

command_layout.addLayout(memory_controls_layout)

# Row 5: Utility Commands
utility_controls_layout = QHBoxLayout()

self.clear_log_btn = QPushButton("🗑️ Clear Logs")
self.clear_log_btn.clicked.connect(self.clear_logs)

self.settings_btn = QPushButton("⚙️ Settings")
self.settings_btn.clicked.connect(lambda: self.send_command("open_settings"))

utility_controls_layout.addWidget(self.clear_log_btn)
utility_controls_layout.addWidget(self.settings_btn)

command_layout.addLayout(utility_controls_layout)

command_group.setLayout(command_layout)
layout.addWidget(command_group)
```

---

### **Step 2: Add send_command() Method**

**File:** `laptop/cortex_monitor_gui.py`

**Location:** Add new method after `clear_logs()` method (around line 650)

```python
def send_command(self, command: str, params: Optional[Dict] = None):
    """
    Send command to connected RPi device(s) via WebSocket.
    
    Args:
        command: Command name (toggle_voice_activation, start_recording, etc.)
        params: Optional command parameters
    """
    if not self.ws_thread or not self.ws_thread.server:
        self.log_message("⚠️ No WebSocket server running", "warning")
        return
    
    if self.num_clients == 0:
        self.log_message("⚠️ No RPi connected to send command", "warning")
        return
    
    try:
        # Create command message using protocol
        from .protocol import create_message, MessageType
        
        message = create_message(
            MessageType.COMMAND,
            device_id="laptop_server",
            command=command,
            params=params or {}
        )
        
        # Broadcast command to all connected RPis
        if self.ws_thread.server:
            asyncio.run_coroutine_threadsafe(
                self.ws_thread.server.broadcast_message(message),
                self.ws_thread.loop
            )
            
            self.log_message(f"📤 Sent command: {command}", "info")
            logger.info(f"📤 Command sent to RPi: {command} with params {params}")
    
    except Exception as e:
        logger.error(f"❌ Failed to send command: {e}", exc_info=True)
        self.log_message(f"❌ Failed to send command: {e}", "error")
```

---

### **Step 3: Fix Video Feed Display**

**File:** `laptop/cortex_monitor_gui.py`

**Location:** In `update_video_frame()` method (around line 590)

**Current Issue:** Video label shows placeholder text instead of frames

**Fix Required:**
```python
def update_video_frame(self, data: dict):
    """Update video display with new frame."""
    try:
        # Decode base64 frame
        frame_data = data.get("frame_data", "")
        if not frame_data:
            return
        
        # Decode base64
        frame_bytes = base64.b64decode(frame_data)
        
        # Convert to QPixmap
        image = Image.open(BytesIO(frame_bytes))
        image_array = np.array(image)
        
        # Convert to Qt format
        height, width, channels = image_array.shape
        bytes_per_line = channels * width
        
        # CRITICAL FIX: Ensure RGB format (not BGR)
        if channels == 3:
            # Convert RGB to Qt RGB888 format
            qt_image = QImage(
                image_array.data,
                width,
                height,
                bytes_per_line,
                QImage.Format.Format_RGB888
            )
        else:
            logger.error(f"Unsupported image channels: {channels}")
            return
        
        pixmap = QPixmap.fromImage(qt_image)
        
        # Scale to fit label while maintaining aspect ratio
        scaled_pixmap = pixmap.scaled(
            self.video_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        # Update display
        self.video_label.setPixmap(scaled_pixmap)
        self.last_video_frame = pixmap
        
        # Remove placeholder text on first frame
        if self.video_label.text():
            self.video_label.setText("")
            self.video_label.setStyleSheet("border: 2px solid #444; background-color: black;")
        
    except Exception as e:
        logger.error(f"❌ Failed to update video frame: {e}")
```

---

### **Step 4: Update Stylesheet for Toggle Buttons**

**File:** `laptop/cortex_monitor_gui.py`

**Location:** In `apply_dark_theme()` method (around line 120)

**Add to stylesheet:**
```python
self.setStyleSheet("""
    /* ... existing styles ... */
    
    QPushButton:checked {
        background-color: #2a8a5a;
        border: 2px solid #3aaa7a;
    }
    QPushButton:checked:hover {
        background-color: #3aaa7a;
    }
    QComboBox {
        background-color: #2a2a2a;
        color: white;
        border: 1px solid #444;
        padding: 5px;
        border-radius: 3px;
    }
    QComboBox::drop-down {
        border: none;
    }
    QComboBox::down-arrow {
        image: url(down_arrow.png);
        width: 12px;
        height: 12px;
    }
""")
```

---

## 🔌 RPi Side Integration Requirements

### Video Feed Integration

**File:** `src/cortex_gui.py` (RPi side)

**Add to process_frame() method:**

```python
def process_frame(self):
    """Process camera frame (existing method)."""
    # ... existing YOLO detection code ...
    
    # Send video frame to laptop (throttled to 10 FPS)
    if hasattr(self, 'ws_client') and self.ws_client.connected:
        if not hasattr(self, '_ws_frame_counter'):
            self._ws_frame_counter = 0
        
        self._ws_frame_counter += 1
        
        # Send every 3rd frame (10 FPS if processing at 30 FPS)
        if self._ws_frame_counter % 3 == 0:
            try:
                # Get current frame (already processed by YOLO)
                frame_to_send = self.current_frame.copy()
                
                # Resize to reduce bandwidth (optional)
                frame_to_send = cv2.resize(frame_to_send, (640, 480))
                
                # Encode to JPEG
                _, buffer = cv2.imencode(
                    '.jpg',
                    frame_to_send,
                    [cv2.IMWRITE_JPEG_QUALITY, 75]  # 75% quality
                )
                
                # Convert to base64
                frame_b64 = base64.b64encode(buffer).decode('utf-8')
                
                # Send to laptop
                self.ws_client.send_video_frame(frame_b64)
            
            except Exception as e:
                logger.error(f"Failed to send video frame: {e}")
```

### Command Handler Integration

**File:** `src/rpi_websocket_client.py` (already implemented, just needs handlers in cortex_gui.py)

**Add to cortex_gui.py:**

```python
def _handle_laptop_command(self, command: str, params: dict):
    """Handle commands from laptop server."""
    logger.info(f"📩 Received command from laptop: {command}")
    
    if command == "toggle_voice_activation":
        self.root.after(0, self.toggle_voice_activation)
    
    elif command == "toggle_interrupt_tts":
        self.root.after(0, self.toggle_vad_interrupt)
    
    elif command == "toggle_spatial_audio":
        self.root.after(0, self.toggle_spatial_audio)
    
    elif command == "change_layer":
        layer = params.get("layer", "Layer 1 Learner")
        # TODO: Implement layer switching logic
        self.debug_print(f"🔄 Switching to: {layer}")
    
    elif command == "change_tier":
        tier = params.get("tier", "Testing (FREE)")
        self.selected_tier.set(tier)
        self.on_tier_selection_changed(tier)
    
    elif command == "start_recording":
        if not self.recording_active:
            self.root.after(0, self.start_recording)
    
    elif command == "stop_recording":
        if self.recording_active:
            self.root.after(0, self.stop_recording)
    
    elif command == "replay_tts":
        self.root.after(0, self.replay_last_tts)
    
    elif command == "mark_poi":
        self.root.after(0, self.learn_from_maps)
    
    elif command == "save_memory":
        # TODO: Implement memory save dialog
        self.debug_print("💾 Memory save requested from laptop")
    
    elif command == "navigate":
        # TODO: Implement navigation mode
        self.debug_print("🗺️ Navigation mode requested from laptop")
    
    elif command == "open_settings":
        # TODO: Implement settings dialog
        self.debug_print("⚙️ Settings requested from laptop")
    
    else:
        logger.warning(f"Unknown command: {command}")

# Register handler with WebSocket client
self.ws_client.on_command_received = self._handle_laptop_command
```

**Add to rpi_websocket_client.py `_handle_command()` method:**

```python
def _handle_command(self, data: dict):
    """Handle command from laptop server."""
    command = data.get("command")
    params = data.get("params", {})
    
    logger.info(f"📩 Received command: {command} with params: {params}")
    
    # Call custom handler if registered
    if self.on_command_received:
        self.on_command_received(command, params)
```

---

## 🧪 Testing Checklist

### Phase 1: UI Testing (No RPi Required)

- [ ] Command panel renders correctly
- [ ] All buttons visible and styled
- [ ] Dropdowns populated with correct values
- [ ] Toggle buttons show checked/unchecked states
- [ ] Click events log to console

**Test Command:**
```bash
python laptop/start_laptop_server.py
```

### Phase 2: Command Sending (With Test Client)

- [ ] Commands sent to WebSocket server
- [ ] Broadcast works (visible in server logs)
- [ ] Error handling for no client connected
- [ ] Multiple button clicks work

**Test Command:**
```bash
# Terminal 1: Laptop server
python laptop/start_laptop_server.py

# Terminal 2: Test client
python src/test_websocket_client.py
```

### Phase 3: Full Integration (With Real RPi)

- [ ] Commands received by RPi
- [ ] RPi executes commands (voice activation, recording, etc.)
- [ ] Video feed appears in laptop GUI
- [ ] Video updates in real-time (10 FPS)
- [ ] Detection log shows RPi detections
- [ ] Metrics update from RPi

---

## 📊 Success Metrics

| Metric | Target | Testing Method |
|--------|--------|----------------|
| Command latency | <100ms | Laptop click → RPi log |
| Video FPS | 10 FPS | Count frames in 10 seconds |
| Video quality | Clear, recognizable | Visual inspection |
| UI responsiveness | No lag | Click all buttons rapidly |
| Error handling | Graceful warnings | Disconnect RPi, click commands |

---

## ⚠️ Known Issues & Limitations

### Issue 1: Video Feed Placeholder

**Symptom:** Video label shows text "Waiting for video stream..."  
**Cause:** RPi not sending VIDEO_FRAME messages  
**Fix:** Implement Step 4 (RPi Side Integration)

### Issue 2: Commands Not Working

**Symptom:** Buttons clicked but RPi doesn't respond  
**Cause:** Command handler not registered in cortex_gui.py  
**Fix:** Implement command handler in cortex_gui.py (see Step 4)

### Issue 3: Toggle Buttons Don't Show State

**Symptom:** Toggle buttons don't show checked/unchecked visually  
**Cause:** Missing QPushButton:checked stylesheet  
**Fix:** Add stylesheet in Step 4

---

## 🔮 Future Enhancements

1. **Bidirectional State Sync:**
   - RPi sends status updates when state changes
   - Laptop buttons reflect RPi state (voice activation on/off, etc.)

2. **Command Queue:**
   - Queue commands when RPi disconnected
   - Send when reconnected

3. **Command History:**
   - Log of all commands sent
   - Replay/undo functionality

4. **Advanced Controls:**
   - Adjustable detection threshold
   - Camera resolution selector
   - Audio device selection from laptop

---

## 📚 References

- **WebSocket Protocol:** `laptop/protocol.py` (line 35 - MessageType.COMMAND)
- **WebSocket Server:** `laptop/websocket_server.py` (line 150 - broadcast_message)
- **RPi GUI Reference:** `src/cortex_gui.py` (line 307-500 - UI layout)
- **PyQt6 Signals/Slots:** PyQt6 documentation (connected() pattern)

---

## ✅ Implementation Checklist

**Laptop Side (This Agent):**
- [ ] Add command panel to `cortex_monitor_gui.py`
- [ ] Implement `send_command()` method
- [ ] Fix video feed display (`update_video_frame()`)
- [ ] Add toggle button stylesheet
- [ ] Test UI renders correctly
- [ ] Test command sending (with logs)

**RPi Side (Haziq):**
- [ ] Add video frame sending to `cortex_gui.py`
- [ ] Add command handler to `cortex_gui.py`
- [ ] Register handler with WebSocket client
- [ ] Test commands execute correctly
- [ ] Test video feed transmits

**Integration Testing:**
- [ ] Commands work end-to-end
- [ ] Video feed displays correctly
- [ ] Both systems work together
- [ ] YIA 2026 demo ready

---

## 🚀 Deployment Instructions

### For Laptop Agent:

1. **Backup existing file:**
   ```bash
   cp laptop/cortex_monitor_gui.py laptop/cortex_monitor_gui.py.backup
   ```

2. **Apply changes** (follow Steps 1-4 above)

3. **Test standalone:**
   ```bash
   python laptop/start_laptop_server.py
   ```

4. **Verify:**
   - GUI opens
   - Command panel visible
   - Buttons clickable
   - No errors in console

### For Haziq (RPi Side):

1. **Integrate video feed** (Step 4, Video Feed Integration)

2. **Add command handler** (Step 4, Command Handler Integration)

3. **Test with laptop:**
   ```bash
   python src/cortex_gui.py
   ```

4. **Verify:**
   - Laptop shows "✅ RPi connected"
   - Video feed appears
   - Commands execute on RPi

---

## 📞 Support

**Questions?** Contact Haziq (@IRSPlays) or check:
- [Laptop Server README](../laptop/README.md)
- [Protocol Specification](../laptop/protocol.py)
- [Integration Guide](./CORTEX_GUI_INTEGRATION.md)

---

**Status:** 📝 **PLAN READY** - Ready for implementation by laptop agent  
**Priority:** 🔴 **HIGH** - Required for YIA 2026 competition demo  
**Estimated Time:** 2-3 hours implementation + 1 hour testing

---

**Created:** January 3, 2026  
**Author:** Haziq (@IRSPlays) - RPi Agent/CTO  
**For:** Laptop Server Agent
