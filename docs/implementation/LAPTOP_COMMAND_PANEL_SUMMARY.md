# 🎮 Laptop GUI Command Panel - Quick Reference

**For:** Laptop Server Agent  
**Priority:** 🔴 HIGH (YIA 2026 Demo Critical)  
**Status:** 📝 Ready for Implementation

---

## 📸 Reference Images

**Current State:**
- Laptop GUI: Metrics working, video feed not displaying, no command controls
- RPi GUI: Full controls at bottom (voice activation, recording, TTS, device selection)

**Goal:**
- Add command panel to laptop GUI (similar to RPi GUI bottom controls)
- Enable remote control of RPi from laptop (click button → RPi executes)
- Fix video feed display (currently shows "Waiting for video stream")

---

## 🎯 What to Implement

### 1. Command Panel UI (Bottom Section)

**Location:** `laptop/cortex_monitor_gui.py` (after line ~700)

**Buttons to Add:**
- 🎙️ Toggle Voice Activation (checkable button)
- 🔇 Interrupt TTS (checkable button)
- 🔊 3D Audio (checkable button)
- 🔴 Start Recording
- 🛑 Stop Recording
- 🔊 Replay TTS
- 🎯 Mark POI
- 💾 Save Memory
- 🗺️ Navigate
- ⚙️ Settings

**Dropdowns to Add:**
- 🎚️ Active Layer: [Layer 0 Guardian, Layer 1 Learner, Layer 2 Thinker, Layer 3 Guide]
- 🎛️ Tier: [Testing (FREE), Demo Mode (PAID), Auto (Cascading), Tier 0 (Live API), Tier 1 (Gemini TTS)]

### 2. Command Sending Logic

**Method to Add:** `send_command(command: str, params: Optional[Dict] = None)`

**What it does:**
1. Check if WebSocket server running → show warning if not
2. Check if RPi connected → show warning if not connected
3. Create COMMAND message using protocol
4. Broadcast to all connected RPis via WebSocket
5. Log success/failure

**Example:**
```python
self.voice_activation_btn.clicked.connect(
    lambda: self.send_command("toggle_voice_activation")
)

self.layer_selector.currentTextChanged.connect(
    lambda layer: self.send_command("change_layer", {"layer": layer})
)
```

### 3. Video Feed Fix

**Issue:** Laptop GUI shows "Waiting for video stream" despite connection working

**Fix in:** `update_video_frame()` method
- Decode base64 frame → Convert to QPixmap → Display in label
- Remove placeholder text on first frame
- Ensure RGB format (not BGR)

**RPi Side Requirement:** Need to send VIDEO_FRAME messages in `cortex_gui.py`

---

## 🧪 Testing Steps

1. **UI Testing (No RPi):**
   ```bash
   python laptop/start_laptop_server.py
   ```
   - ✅ Command panel visible
   - ✅ All buttons styled correctly
   - ✅ Dropdowns populated
   - ✅ Click events log to console

2. **Command Testing (With RPi):**
   ```bash
   # Laptop: python laptop/start_laptop_server.py
   # RPi: python src/cortex_gui.py
   ```
   - ✅ Click button → RPi receives command
   - ✅ RPi executes command (voice activation, recording, etc.)
   - ✅ Latency <100ms

3. **Video Feed Testing:**
   - ✅ Laptop GUI shows video from RPi
   - ✅ Updates at ~10 FPS
   - ✅ Clear and recognizable

---

## 📚 Full Documentation

**Detailed Implementation Plan:** [LAPTOP_GUI_COMMAND_PANEL_PLAN.md](./LAPTOP_GUI_COMMAND_PANEL_PLAN.md)
- Complete code snippets
- UI layout specifications
- Testing checklist
- Troubleshooting guide

**Architecture Reference:** [UNIFIED-SYSTEM-ARCHITECTURE.md](../architecture/UNIFIED-SYSTEM-ARCHITECTURE.md)
- WebSocket protocol specification (14 message types)
- Command list with parameters
- Security considerations

---

## ⚡ Quick Start

1. Read full plan: [LAPTOP_GUI_COMMAND_PANEL_PLAN.md](./LAPTOP_GUI_COMMAND_PANEL_PLAN.md)
2. Implement Step 1: Add command panel UI
3. Implement Step 2: Add send_command() method
4. Implement Step 3: Fix video feed display
5. Implement Step 4: Add stylesheet for toggle buttons
6. Test with RPi: Click buttons, verify commands execute

**Estimated Time:** 2-3 hours implementation + 1 hour testing

---

## 📞 Support

**Questions?** Ask Haziq (@IRSPlays) or check:
- Protocol: `laptop/protocol.py` (MessageType definitions)
- WebSocket Server: `laptop/websocket_server.py` (broadcast_message)
- RPi GUI Reference: `src/cortex_gui.py` (lines 307-500)

---

**Status:** 📝 Plan ready, awaiting implementation  
**Blocker:** None (RPi side will integrate after laptop GUI ready)  
**Next:** Laptop agent implements UI, then Haziq integrates RPi command handlers
