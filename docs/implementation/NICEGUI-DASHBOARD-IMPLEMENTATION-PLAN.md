# NiceGUI Dashboard Implementation Plan - Feature Parity with Tkinter System

**Author:** GitHub Copilot (CTO)  
**Date:** December 30, 2025  
**Status:** PENDING IMPLEMENTATION  
**Priority:** HIGH - YIA 2026 Demo System

---

## 📋 TABLE OF CONTENTS
1. [Objective](#objective)
2. [Gap Analysis](#gap-analysis)
3. [Research Findings](#research-findings)
4. [Implementation Strategy](#implementation-strategy)
5. [Technical Challenges](#technical-challenges)
6. [Success Criteria](#success-criteria)
7. [Timeline](#timeline)
8. [Risk Assessment](#risk-assessment)

---

## 🎯 OBJECTIVE

Transform the NiceGUI dashboard (`cortex_dashboard.py`) to have **100% feature parity** with the existing Tkinter system (`cortex_gui.py`) while leveraging web-native patterns for audio/video streaming.

**Why NiceGUI over Tkinter:**
- ✅ Web-based → Remote access from phone/tablet
- ✅ Modern UI → Glassmorphism, Tailwind CSS
- ✅ Better performance → Async by default
- ✅ Easier deployment → Just open browser
- ✅ Multi-client → Multiple users can connect

---

## 📊 GAP ANALYSIS

### ✅ ALREADY IMPLEMENTED (NiceGUI Dashboard)
- Basic video feed rendering (`ui.interactive_image`)
- Neural layer status cards (UI only, no logic)
- Boot log terminal (`ui.log`)
- Chat interface (UI only, no AI integration)
- Basic `CortexHardwareManager` singleton
- Dual YOLO inference loop (background thread)
- Detection aggregation (Guardian + Learner merge)
- Frame annotation (safety bounding boxes)
- Base64 JPEG encoding for web display

### ❌ MISSING CRITICAL FEATURES

#### 1. **Audio System** (Highest Priority - 0% Complete)
**Tkinter Has:**
- Whisper STT (voice input) → `WhisperSTT` handler
- Kokoro TTS (voice output) → `KokoroTTS` handler  
- Gemini 3 Flash Preview TTS → `GeminiTTS` handler
- Voice Activity Detection (VAD) → `VADHandler` with Silero
- Audio device selection → sounddevice enumeration
- Real-time audio playback → pygame mixer
- Recording state management → threading + queues

**NiceGUI Needs:**
- JavaScript MediaRecorder API bridge
- Server-side Whisper processing
- Dynamic `ui.audio()` source updates
- WebSocket for audio streaming
- Device selection via MediaDevices API

**Impact:** **CRITICAL** - Without audio, the system is unusable for visually impaired users.

---

#### 2. **AI Handler Integration** (30% Complete)
**Tkinter Has:**
- `IntentRouter` - Routes queries to Layer 1/2/3 (<1ms, 97.7% accuracy)
- `DetectionRouter` - Confidence-based escalation (high/med/low conf routing)
- `GeminiLiveManager` - WebSocket audio-to-audio (<500ms latency)
- `GLM4VHandler` - Z.ai fallback API (Tier 2)
- `StreamingAudioPlayer` - Real-time PCM playback for Live API
- Full exception handling + retry logic

**NiceGUI Has:**
- ✅ `DualYOLOHandler` initialized
- ✅ `DetectionAggregator` working
- ❌ No Intent Router
- ❌ No Detection Router
- ❌ No Gemini handlers
- ❌ No GLM-4.6V handler

**Impact:** **HIGH** - Layer 2/3 completely non-functional.

---

#### 3. **3-Tier Cascading Fallback System** (0% Complete)
**Tkinter Implementation:**
```python
# Auto Mode: Try each tier in sequence until success
Tier 0: Gemini Live API (WebSocket, <500ms, $0.005/min)
  ↓ Quota exceeded?
Tier 1: Gemini 3 Flash TTS (HTTP, 1-2s, $3.00/1M tokens)
  ↓ All keys exhausted?
Tier 2: GLM-4.6V Z.ai (HTTP, 1-2s, Z.ai pricing)
  ↓ All failed?
ERROR: No AI APIs available
```

**NiceGUI Status:** Not implemented (all Layer 2 queries will fail)

**Impact:** **CRITICAL** - No graceful degradation, single point of failure.

---

#### 4. **Layer Execution Pipeline** (10% Complete)
**Tkinter Pipeline:**
```python
Voice Input → Whisper STT → Intent Router → Layer Execution → TTS Output
              (~500ms)      (<1ms)          (varies)        (~1s)
```

**Current NiceGUI:**
- ✅ Video capture thread
- ✅ YOLO processing thread
- ❌ Audio pipeline missing
- ❌ Router missing
- ❌ Layer execution missing

**Impact:** **CRITICAL** - Core functionality missing.

---

#### 5. **User Controls** (20% Complete)
**Tkinter Controls:**
- ✅ Voice activation toggle
- ✅ VAD interrupt toggle
- ✅ Spatial audio toggle
- ✅ YOLOE mode selector (Prompt-Free/Text Prompts/Visual Prompts)
- ✅ Tier selector dropdown (Auto/Tier 0/Tier 1/Tier 2)
- ✅ Audio input device dropdown
- ✅ Audio output device dropdown
- ✅ Manual recording button
- ✅ TTS replay button

**NiceGUI Has:**
- ✅ Voice Activation switch (UI only, no logic)
- ✅ Spatial Audio switch (UI only, no logic)
- ✅ Vision Mode selector (UI only, no logic)
- ❌ Tier selector missing
- ❌ Audio device dropdowns missing
- ❌ Recording button missing

**Impact:** **HIGH** - Users cannot configure system.

---

#### 6. **Memory System Integration** (0% Complete)
**Tkinter Has:**
- Layer 4 Memory Manager (`get_memory_manager()`)
- "Remember this as X" command parsing
- "Find my X" recall logic
- SQLite persistent storage
- Visual memory grid (6 slots)

**NiceGUI Has:**
- ✅ Memory grid placeholder (6 random images)
- ❌ No Memory Manager integration
- ❌ No commands parsed

**Impact:** **MEDIUM** - Nice-to-have, not critical for MVP.

---

#### 7. **Spatial Audio (Layer 3)** (0% Complete)
**Tkinter Has:**
- PyOpenAL 3D audio rendering
- GPS sensor fusion
- HRTF spatial positioning
- Memory location commands

**NiceGUI Has:**
- ❌ Not implemented

**Impact:** **LOW** - Future feature, not critical.

---

## 🔬 RESEARCH FINDINGS

### NiceGUI Audio Architecture Patterns

#### 1. **No Native Audio Recording**
**Problem:** NiceGUI has `ui.audio()` for playback but no recording API.

**Solution:** Use JavaScript Web Audio API bridge:
```javascript
// Client-side recording
navigator.mediaDevices.getUserMedia({ audio: true })
  .then(stream => {
    const recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => {
      // Convert to Base64 and send to Python
      emitEvent('audio-data', base64Data);
    };
  });
```

**Research Source:** NiceGUI Wiki - Audio Recorder Example

---

#### 2. **Audio Device Selection**
**Problem:** No Python API for device enumeration in web context.

**Solution:** Use MediaDevices API:
```javascript
navigator.mediaDevices.enumerateDevices()
  .then(devices => {
    const audioInputs = devices.filter(d => d.kind === 'audioinput');
    emitEvent('devices-list', audioInputs);
  });
```

**Best Practice:** Populate `ui.select()` with device list from JavaScript.

---

#### 3. **Real-Time Audio Streaming**
**Problem:** Tkinter uses PyAudio direct stream, web needs different approach.

**Solution:** Chunked audio streaming:
1. **Client → Server:** MediaRecorder chunks via WebSocket
2. **Server Processing:** Whisper/VAD on accumulated chunks
3. **Server → Client:** TTS audio via `ui.audio()` dynamic source

**Latency:** Expect +200-300ms overhead vs Tkinter (acceptable tradeoff for web)

---

#### 4. **State Synchronization**
**Research:** NiceGUI `app.storage.user` for persistence, `ui.timer()` for polling.

**Current Dashboard Issue:** 30 FPS polling (0.033s) is too aggressive.
- Causes: High CPU, network bandwidth waste, UI lag
- Solution: Reduce to 10-15 FPS (0.066-0.1s), use `ui.refreshable()` pattern

---

## 🏗️ IMPLEMENTATION STRATEGY

### Phase 1: Core Audio System (Week 1, Priority: CRITICAL)
**Goal:** Voice input/output working end-to-end

#### Task 1.1: JavaScript Audio Bridge (2 days)
**Files to Create:**
- `src/web/audio_bridge.js` - Client-side recording
- `src/cortex_dashboard.py` - Add audio event handlers

**Implementation:**
```python
class AudioBridge:
    """JavaScript ↔ Python audio communication bridge."""
    
    def __init__(self, app):
        self.recorder_active = False
        self.audio_buffer = bytearray()
        
        # Inject JavaScript
        ui.add_body_html('''
        <script src="/static/audio_bridge.js"></script>
        ''')
        
    async def start_recording(self):
        """Signal JavaScript to start MediaRecorder."""
        await ui.run_javascript('''
        window.audioRecorder.start();
        ''')
        
    async def stop_recording(self):
        """Signal JavaScript to stop and return audio."""
        audio_b64 = await ui.run_javascript('''
        return window.audioRecorder.stop();
        ''')
        return base64.b64decode(audio_b64)
        
    async def list_devices(self):
        """Get audio device list from browser."""
        devices = await ui.run_javascript('''
        const devices = await navigator.mediaDevices.enumerateDevices();
        return devices.filter(d => d.kind === 'audioinput');
        ''')
        return devices
```

**Testing:** Record 3s audio → Print base64 length → Verify non-empty

---

#### Task 1.2: Whisper STT Integration (1 day)
**Reuse:** `src/layer1_reflex/whisper_handler.py` (already exists)

**Implementation:**
```python
class CortexDashboard:
    def __init__(self):
        self.whisper_stt = WhisperSTT(
            model_size='base',
            device='cuda',
            language='en'
        )
        self.audio_bridge = AudioBridge(app)
        
    async def process_voice_input(self):
        """Voice pipeline: Record → Whisper → Display."""
        # Record audio
        audio_bytes = await self.audio_bridge.stop_recording()
        
        # Save to temp file
        wav_path = "temp_audio/recording.wav"
        with open(wav_path, 'wb') as f:
            f.write(audio_bytes)
        
        # Transcribe
        text = await asyncio.to_thread(
            self.whisper_stt.transcribe_file, wav_path
        )
        
        # Update chat UI
        with self.chat_container:
            ui.chat_message(text, name='User', sent=True)
```

**Testing:** Say "hello world" → Check transcription accuracy

---

#### Task 1.3: TTS Playback System (1 day)
**Reuse:** `src/layer1_reflex/kokoro_handler.py` (already exists)

**Implementation:**
```python
class CortexDashboard:
    def __init__(self):
        self.kokoro_tts = KokoroTTS(
            lang_code='a',
            default_voice='af_alloy',
            default_speed=1.0
        )
        self.audio_player = ui.audio().props('autoplay')
        
    async def speak(self, text: str):
        """Generate TTS and play in browser."""
        # Generate audio file
        audio_path = await asyncio.to_thread(
            self.kokoro_tts.generate_speech, text
        )
        
        # Update audio source (triggers autoplay)
        self.audio_player.set_source(f'/audio/{audio_path}')
        
        # Update chat UI
        with self.chat_container:
            ui.chat_message(text, name='Cortex', sent=False)
```

**Testing:** Click button → TTS plays "Cortex initialized"

---

#### Task 1.4: Voice Activation UI (1 day)
**Implementation:**
```python
@ui.refreshable
def voice_controls():
    """Voice activation control panel."""
    with ui.row().classes('gap-4 items-center'):
        # Recording indicator
        if app.storage.user.get('recording', False):
            ui.spinner('dots', size='lg', color='red')
            ui.label('Recording...').classes('text-red-500 font-bold')
        
        # Voice activation switch
        switch = ui.switch('Voice Activation')
        switch.bind_value(app.storage.user, 'voice_active')
        switch.on_value_change(toggle_voice_activation)
        
        # Manual record button
        ui.button(
            '🎤 Record',
            on_click=manual_record,
            color='red' if app.storage.user.get('recording') else 'blue'
        )

async def toggle_voice_activation(e):
    """Start/stop continuous voice activation."""
    if e.value:
        await dashboard.audio_bridge.start_recording()
        await dashboard.init_vad()  # Start VAD monitoring
    else:
        await dashboard.audio_bridge.stop_recording()
        await dashboard.stop_vad()
```

**Testing:** Toggle ON → Speak → Auto-transcribe → Toggle OFF

**Phase 1 Deliverable:** ✅ User can speak → transcription appears → TTS response plays

---

### Phase 2: AI Handler Integration (Week 2, Priority: HIGH)
**Goal:** Full 3-layer routing working

#### Task 2.1: Intent Router Integration (1 day)
**Reuse:** `src/layer3_guide/router.py` (already exists)

**Implementation:**
```python
from layer3_guide.router import IntentRouter

class CortexHardwareManager:
    def __init__(self):
        # ... existing code ...
        self.intent_router = IntentRouter()
        self.detection_router = DetectionRouter()
        
    async def process_query(self, text: str):
        """Route query to appropriate layer."""
        # Stage 1: Intent Routing
        start_time = time.time()
        layer = self.intent_router.route(text)
        router_latency = (time.time() - start_time) * 1000
        
        self.add_log(f"🎯 Router ({router_latency:.1f}ms): {layer}")
        
        # Update layer card status
        self.state['layers'][layer]['active'] = True
        self.state['layers'][layer]['msg'] = 'Processing...'
        
        # Stage 2: Execute layer
        if layer == 'layer1':
            await self.execute_layer1(text)
        elif layer == 'layer2':
            await self.execute_layer2(text)
        elif layer == 'layer3':
            await self.execute_layer3(text)
```

**Testing:** 
- "what do you see" → layer1
- "explain what you see" → layer2
- "where am i" → layer3

---

#### Task 2.2: Layer 1 (Reflex) Execution (1 day)
**Implementation:**
```python
async def execute_layer1(self, text: str):
    """Layer 1: Fast object detection response."""
    self.add_log("⚡ [LAYER 1] Reflex Mode Activated")
    
    # Get latest detections
    with self.lock:
        detections = self.state['detections']
    
    # Generate response
    response = f"I see {detections}."
    
    # TTS playback
    await self.dashboard.speak(response)
    
    # Update layer status
    self.state['layers']['reflex']['active'] = True
    self.state['layers']['reflex']['msg'] = f'Detected: {detections}'
```

**Testing:** "what do you see" → TTS says "I see person, car."

---

#### Task 2.3: Layer 2 (Thinker) Execution (2 days)
**Reuse:**
- `src/layer2_thinker/gemini_tts_handler.py`
- `src/layer2_thinker/glm4v_handler.py`

**Implementation:**
```python
async def execute_layer2(self, text: str):
    """Layer 2: 3-tier cascading fallback."""
    self.add_log("☁️ [LAYER 2] Thinker Mode Activated")
    
    # Get current frame
    with self.lock:
        frame_b64 = self.state['last_frame']
    
    # Try Tier 1: Gemini 3 Flash (default)
    if self.gemini_tts:
        try:
            response = await asyncio.to_thread(
                self.gemini_tts.generate_response_from_image,
                frame_b64,  # Base64 JPEG
                text
            )
            await self.dashboard.speak(response)
            return
        except Exception as e:
            self.add_log(f"⚠️ Tier 1 failed: {e}")
    
    # Try Tier 2: GLM-4.6V (fallback)
    if self.glm4v:
        try:
            response = await asyncio.to_thread(
                self.glm4v.query_vision,
                frame_b64,
                text
            )
            await self.dashboard.speak(response)
            return
        except Exception as e:
            self.add_log(f"❌ Tier 2 failed: {e}")
    
    # All tiers failed
    await self.dashboard.speak("Sorry, all AI systems are currently unavailable.")
```

**Testing:** "explain what you see" → Gemini analyzes scene

---

#### Task 2.4: Layer 3 (Guide) Execution (1 day)
**Implementation (Placeholder):**
```python
async def execute_layer3(self, text: str):
    """Layer 3: Navigation and memory."""
    self.add_log("🧭 [LAYER 3] Guide Mode Activated")
    
    if 'where am i' in text.lower():
        response = "GPS coordinates: 40.7128° N, 74.0060° W. Location: New York City."
    elif 'remember' in text.lower():
        response = "Memory feature not yet implemented."
    else:
        response = "Navigation command received."
    
    await self.dashboard.speak(response)
```

**Testing:** "where am i" → GPS response

**Phase 2 Deliverable:** ✅ "what do you see" → Layer 1, "explain" → Layer 2, "where am i" → Layer 3

---

### Phase 3: Advanced Features (Week 3, Priority: MEDIUM)

#### Task 3.1: VAD (Voice Activity Detection) (2 days)
**Reuse:** `src/layer1_reflex/vad_handler.py`

**Implementation:**
```python
class VADManager:
    """Server-side VAD for continuous voice activation."""
    
    def __init__(self):
        self.vad_handler = VADHandler(
            sample_rate=16000,
            threshold=0.5,
            min_speech_duration_ms=500,
            min_silence_duration_ms=700
        )
        self.audio_chunks = []
        
    async def process_chunk(self, audio_chunk: bytes):
        """Process incoming audio chunk from browser."""
        self.audio_chunks.append(audio_chunk)
        
        # Check for speech end
        speech_end = self.vad_handler.process(audio_chunk)
        
        if speech_end:
            # Concatenate chunks and process
            full_audio = b''.join(self.audio_chunks)
            self.audio_chunks = []
            
            # Trigger STT pipeline
            await self.dashboard.process_voice_input(full_audio)
```

**Testing:** Speak continuously → Auto-segments speech → Processes each segment

---

#### Task 3.2: YOLOE Mode Switching (1 day)
**Implementation:**
```python
async def on_mode_change(mode: str):
    """Switch YOLOE Learner detection mode."""
    manager.add_log(f"🔄 Switching to {mode} mode...")
    
    # Convert string to enum
    mode_map = {
        'Prompt-Free': YOLOEMode.PROMPT_FREE,
        'Text Prompts': YOLOEMode.TEXT_PROMPTS,
        'Visual Prompts': YOLOEMode.VISUAL_PROMPTS
    }
    
    # Switch mode (runs in thread to avoid blocking)
    await asyncio.to_thread(
        manager.dual_yolo.switch_mode,
        mode_map[mode]
    )
    
    manager.add_log(f"✅ Switched to {mode} mode")
```

**Testing:** Change dropdown → Log shows mode switch → Detections update

---

#### Task 3.3: Tier Selection UI (1 day)
**Implementation:**
```python
# Add to controls panel
tier_options = ['Auto (Fallback)', 'Tier 0 (Live API)', 'Tier 1 (Gemini)', 'Tier 2 (GLM-4.6V)']
ui.select(tier_options, value='Auto (Fallback)', label='AI Tier') \
    .bind_value(app.storage.user, 'selected_tier') \
    .on_value_change(on_tier_change)

# Add tier indicator
@ui.refreshable
def tier_indicator():
    active_tier = manager.state.get('active_tier', 'Auto')
    color = {'Tier 0': 'green', 'Tier 1': 'blue', 'Tier 2': 'orange'}.get(active_tier, 'gray')
    ui.badge(f'Active: {active_tier}').props(f'color={color}')
```

**Testing:** Select "Tier 1 (Gemini)" → Only Gemini API used

---

#### Task 3.4: Audio Device Selection (1 day)
**Implementation:**
```python
async def populate_devices():
    """Fetch device list from browser."""
    devices = await ui.run_javascript('''
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter(d => d.kind === 'audioinput').map(d => ({
        id: d.deviceId,
        label: d.label || `Microphone ${d.deviceId.slice(0, 5)}`
    }));
    ''')
    
    # Update dropdown
    device_names = [d['label'] for d in devices]
    input_device_dropdown.set_options(device_names)

# Add to controls
input_device_dropdown = ui.select([], label='Microphone').bind_value(app.storage.user, 'input_device')
ui.button('Refresh Devices', on_click=populate_devices)
```

**Testing:** Click refresh → Dropdown populates → Select device → Recording uses new device

**Phase 3 Deliverable:** ✅ All Tkinter features ported to web UI

---

### Phase 4: Memory & Spatial Audio (Week 4, Priority: LOW)

#### Task 4.1: Memory System (2 days)
**Reuse:** `src/layer4_memory/__init__.py`

**Implementation:**
```python
from layer4_memory import get_memory_manager

class CortexHardwareManager:
    def __init__(self):
        self.memory_manager = get_memory_manager()
        
    async def execute_memory_command(self, text: str):
        """Handle 'remember this as X' and 'find my X' commands."""
        if 'remember this as' in text.lower():
            # Extract object name
            obj_name = text.lower().split('remember this as')[1].strip()
            
            # Save current frame
            memory_id = self.memory_manager.store_object(
                obj_name,
                self.state['last_frame']
            )
            
            response = f"Remembered {obj_name}."
            
        elif 'find my' in text.lower():
            # Extract object name
            obj_name = text.lower().split('find my')[1].strip()
            
            # Recall from memory
            memory = self.memory_manager.recall(obj_name)
            
            if memory:
                response = f"I found your {obj_name}. Last seen: {memory['location']}."
            else:
                response = f"I don't remember seeing your {obj_name}."
        
        await self.dashboard.speak(response)
```

**Testing:** "remember this as keys" → Stores frame → "find my keys" → Recalls location

---

#### Task 4.2: Spatial Audio (Optional, 1 day)
**Implementation (Mock):**
```python
async def execute_spatial_audio(self, direction: str):
    """3D audio navigation (placeholder)."""
    # In production: Use PyOpenAL to render spatial audio
    # For now: Just announce direction
    response = f"Object is {direction}."
    await self.dashboard.speak(response)
```

---

#### Task 4.3: Polish & Testing (2 days)
**Checklist:**
- [ ] Error messages user-friendly
- [ ] Loading spinners for all async ops
- [ ] Performance profiling (reduce latency)
- [ ] Cross-browser testing (Chrome, Firefox, Edge)
- [ ] Mobile responsiveness
- [ ] Keyboard shortcuts
- [ ] Accessibility (ARIA labels)

**Phase 4 Deliverable:** ✅ Production-ready web dashboard

---

## 🔧 TECHNICAL CHALLENGES & SOLUTIONS

### Challenge 1: Video Feed Lag (CURRENT ISSUE)
**Symptoms:**
- High CPU usage
- UI freezes
- Frame drops
- Network bandwidth saturation

**Root Causes:**
1. **30 FPS Polling Too Aggressive:**
   - Current: `ui.timer(0.033, update_tick)` = 30 FPS
   - Network can't keep up with Base64 JPEG stream

2. **No Frame Rate Limiting on Inference Side:**
   - Inference loop runs at GPU speed (~100 FPS)
   - All frames encoded to Base64 (wasted CPU)

3. **Lock Contention:**
   - UI thread and inference thread both access `self.state`
   - Mutex causes blocking

4. **JPEG Encoding Overhead:**
   - Every frame: `cv2.imencode('.jpg', frame)` + Base64
   - ~10-20ms per frame = 100-200ms per second wasted

**Solutions:**

#### Solution A: Reduce UI Polling Rate (Quick Fix)
```python
# Change from 30 FPS to 10 FPS
ui.timer(0.1, update_tick)  # 10 FPS

# Or adaptive rate based on network
async def adaptive_update():
    if network_slow:
        await asyncio.sleep(0.2)  # 5 FPS
    else:
        await asyncio.sleep(0.066)  # 15 FPS
```

**Impact:** Immediate improvement, simple change

---

#### Solution B: Frame Rate Limiting on Inference Side (Better)
```python
class CortexHardwareManager:
    def _inference_loop(self):
        target_fps = 10  # Limit to 10 FPS
        frame_interval = 1.0 / target_fps
        last_encode_time = 0
        
        while self.is_running:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    # Run inference (always)
                    g_results, l_results = self.dual_yolo.process_frame(frame)
                    
                    # Encode to Base64 (only every 100ms = 10 FPS)
                    current_time = time.time()
                    if current_time - last_encode_time >= frame_interval:
                        annotated = self._annotate_frame(frame, g_results)
                        _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        b64 = base64.b64encode(buffer).decode('utf-8')
                        
                        with self.lock:
                            self.state['last_frame'] = f'data:image/jpeg;base64,{b64}'
                        
                        last_encode_time = current_time
            
            time.sleep(0.01)  # Small sleep to avoid busy loop
```

**Impact:** 66% reduction in encoding overhead

---

#### Solution C: Use `ui.refreshable()` Pattern (Best)
```python
@ui.refreshable
async def video_feed():
    """Refreshable video feed (only updates when called)."""
    frame_data = manager.state['last_frame']
    if frame_data:
        ui.image(frame_data).classes('w-full h-full object-cover')

# Update on-demand instead of polling
async def update_video_on_change():
    """Only refresh when new frame available."""
    last_frame_id = None
    while True:
        current_frame_id = manager.state.get('frame_id', 0)
        if current_frame_id != last_frame_id:
            video_feed.refresh()
            last_frame_id = current_frame_id
        await asyncio.sleep(0.1)
```

**Impact:** Only updates when frame changes, not on fixed timer

---

### Challenge 2: Real-Time Audio in Browser
**Problem:** Tkinter uses PyAudio direct stream, web needs different approach.

**Solution:** Chunked audio streaming:
1. **Client → Server:** MediaRecorder chunks (every 100ms) via WebSocket
2. **Server Processing:** Accumulate chunks until speech end (VAD detects)
3. **Server → Client:** TTS audio via `ui.audio()` dynamic source

**Latency Comparison:**
- Tkinter: ~500ms (PyAudio direct)
- Web: ~700ms (+200ms for WebSocket overhead)

**Acceptable:** +40% latency is acceptable for web convenience

---

### Challenge 3: State Synchronization
**Problem:** Multiple clients may connect, state needs to be shared.

**Solution:** Use `manager` singleton pattern:
```python
# All clients share same manager instance
manager = CortexHardwareManager()

@ui.page('/')
async def main_page():
    dashboard = CortexDashboard(manager)  # Each client gets own UI
    dashboard.build_ui()
    
    # But they all read from same manager.state
    async def update_tick():
        state = manager.state  # Shared global state
        dashboard.update_ui(state)
```

**Benefit:** Multiple users can view same video feed simultaneously

---

## 📊 SUCCESS CRITERIA

### Functional Requirements:
- ✅ Voice input → Transcription → Response (end-to-end working)
- ✅ 3-layer routing (L1/L2/L3) 97.7% accuracy
- ✅ 3-tier fallback (Live API → Gemini → GLM-4.6V) graceful degradation
- ✅ Voice activation toggle functional
- ✅ YOLOE mode switching (3 modes)
- ✅ Audio device selection (input/output)
- ✅ Memory commands ("remember this", "find my X")

### Performance Requirements:
| Metric | Tkinter Baseline | NiceGUI Target | Status |
|--------|------------------|----------------|--------|
| Whisper STT | 500-800ms | <1000ms | TBD |
| Intent Router | <1ms | <10ms | TBD |
| Layer 1 Response | <500ms | <700ms | TBD |
| Layer 2 (Tier 1) | 1-2s | <3s | TBD |
| Layer 2 (Tier 0) | <500ms | <1s | TBD |
| Video Feed FPS | 30 FPS | 10-15 FPS | **NEEDS FIX** |

### User Experience:
- ✅ No page refresh required
- ✅ Visual feedback for all actions (spinners, badges, notifications)
- ✅ Error messages user-friendly (not stack traces)
- ✅ Loading states visible (processing indicators)
- ✅ Mobile responsive (Tailwind CSS classes)

---

## 📅 TIMELINE ESTIMATE

| Phase | Duration | Deliverable | Priority |
|-------|----------|-------------|----------|
| **Phase 0** | **1 day** | **Fix video lag (URGENT)** | **CRITICAL** |
| Phase 1 | 5 days | Voice input/output working | CRITICAL |
| Phase 2 | 5 days | 3-layer routing working | HIGH |
| Phase 3 | 5 days | Feature parity achieved | MEDIUM |
| Phase 4 | 4 days | Complete system polished | LOW |

**Total:** ~20 working days (4 weeks)

**Critical Path:** Phase 0 → Phase 1 → Phase 2 (must be sequential)

---

## ⚠️ RISK ASSESSMENT

### High Risk:
1. **Browser audio latency** → Mitigate with WebSocket streaming, chunk buffering
2. **Live API WebSocket in web** → Complex architecture, needs separate WebSocket server

### Medium Risk:
1. **Device selection compatibility** → Test on Chrome, Firefox, Safari, Edge
2. **TTS audio format** → Ensure WAV/MP3 compatibility across browsers
3. **State synchronization bugs** → Use proper locking, test multi-client

### Low Risk:
1. **UI state management** → NiceGUI handles this well with `app.storage`
2. **Router integration** → Already tested in Tkinter (97.7% accuracy)
3. **Memory system** → SQLite stable, well-tested

---

## 🚀 NEXT STEPS

### Immediate Actions (Next 24 Hours):
1. ✅ Create this implementation plan document
2. **🔥 FIX VIDEO LAG (Priority #1):**
   - Reduce UI polling from 30 FPS to 10 FPS
   - Add frame rate limiting to inference loop
   - Reduce JPEG quality to 70%
3. Start Phase 1: JavaScript Audio Bridge prototype

### Decision Required:
**Which implementation order do you prefer?**

**Option A: Fix-Then-Build (Recommended)**
- Day 1: Fix video lag issue
- Day 2-6: Phase 1 (Audio system)
- Day 7-11: Phase 2 (AI handlers)
- Day 12-16: Phase 3 (Advanced features)
- Day 17-20: Phase 4 (Polish)

**Option B: Parallel-Build**
- Day 1: Fix video lag + Start audio bridge
- Day 2-20: Work on multiple phases simultaneously
- Risk: May introduce bugs, harder to debug

**Recommendation:** Option A (Fix-Then-Build) for stability.

---

## 📝 CHANGELOG
- **v1.0 (Dec 30, 2025):** Initial implementation plan created
- **v1.1 (Pending):** Video lag fix implemented
- **v1.2 (Pending):** Phase 1 audio system complete
- **v1.3 (Pending):** Phase 2 routing complete
- **v1.4 (Pending):** Phase 3 feature parity achieved
- **v1.5 (Pending):** Phase 4 production ready

---

## 📚 REFERENCES
1. NiceGUI Documentation: https://nicegui.io/documentation
2. Web Audio API: https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API
3. MediaRecorder API: https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder
4. Whisper Documentation: https://github.com/openai/whisper
5. Gemini API: https://ai.google.dev/gemini-api/docs
6. Tkinter System: `src/cortex_gui.py` (reference implementation)

---

**Status:** Ready for implementation. Awaiting approval to proceed with Phase 0 (video lag fix).
