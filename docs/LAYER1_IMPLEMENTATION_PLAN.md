# Layer 1 Implementation Plan: Voice Activation + STT/TTS
**Project Cortex v2.0 - YIA 2026**  
**Author:** Haziq (Founder) + GitHub Copilot (CTO)  
**Date:** 2025-01-XX  
**Status:** APPROVED FOR IMPLEMENTATION

---

## 🎯 MISSION OBJECTIVE
Implement **voice-activated** and **button-activated** modes for Layer 1 (Reflex), integrating:
1. **Whisper STT** (Speech-to-Text) - GPU-accelerated, <1s latency
2. **Kokoro TTS** (Text-to-Speech) - Local, <500ms latency
3. **Silero VAD** (Voice Activity Detection) - Real-time speech detection

---

## 📊 RESEARCH FINDINGS (COMPLETED)

### 1. OpenAI Whisper (Speech-to-Text)
**Source:** Context7 + GitHub MCP (`/openai/whisper`)

**Key Patterns:**
```python
# Model loading with GPU support
model = whisper.load_model("base", device="cuda")

# Audio preprocessing (16kHz mono required)
audio = whisper.load_audio("file.wav")  # Returns numpy array
audio = whisper.pad_or_trim(audio)      # 30-second chunks

# Transcription with GPU acceleration
result = model.transcribe(
    audio,
    language="en",
    fp16=True,           # Use FP16 on GPU (2x speed)
    verbose=False
)
text = result["text"].strip()
```

**Performance:**
- **Model Size:** `base` (74M params, ~1GB VRAM, ~7x real-time speed)
- **Latency Target:** <1s for 5-second audio clips
- **GPU Support:** CUDA/cuDNN via PyTorch
- **Sample Rate:** 16kHz mono

**Alternative:** `faster-whisper` (4x speed improvement via CTranslate2)

---

### 2. Silero VAD (Voice Activity Detection)
**Source:** Context7 (`/snakers4/silero-vad`)

**Key Patterns:**
```python
# Load Silero VAD model
from silero_vad import load_silero_vad, VADIterator

model = load_silero_vad(onnx=False)
vad_iterator = VADIterator(model, sampling_rate=16000)

# Real-time streaming inference (512-sample chunks)
window_size_samples = 512  # 32ms at 16kHz
for i in range(0, len(wav), window_size_samples):
    chunk = wav[i:i+window_size_samples]
    speech_dict = vad_iterator(chunk, return_seconds=True)
    if speech_dict:
        print(f"Speech detected: {speech_dict}")

# Reset model state after each audio stream
vad_iterator.reset_states()
```

**Advantages over WebRTC VAD:**
- ✅ **Flexible Chunk Sizes:** No fixed 10/20/30ms requirement
- ✅ **Better Accuracy:** Deep learning-based (vs signal processing)
- ✅ **Streaming Support:** Built-in `VADIterator` for real-time
- ✅ **Probabilities + Timestamps:** Returns detailed speech segments

---

### 3. PyAudio (Real-time Microphone Capture)
**Source:** GitHub MCP (`cristifati/pyaudio`)

**Key Patterns:**
```python
import pyaudio

# Callback function signature
def callback(in_data, frame_count, time_info, status_flags):
    # in_data: bytes (audio data from microphone)
    # frame_count: int (number of frames in chunk)
    # time_info: dict (timing information)
    # status_flags: int (buffer overflow/underflow flags)
    
    # Process audio here (e.g., VAD detection)
    # Return (out_data, flag) where flag is paContinue/paComplete/paAbort
    return (None, pyaudio.paContinue)

# Open stream with callback (non-blocking)
p = pyaudio.PyAudio()
stream = p.open(
    format=pyaudio.paInt16,
    channels=1,              # Mono
    rate=16000,              # 16kHz (Whisper requirement)
    input=True,
    frames_per_buffer=512,   # 32ms chunks (Silero VAD window)
    stream_callback=callback
)

# Callback runs in separate thread automatically
while stream.is_active():
    time.sleep(0.1)

stream.close()
p.terminate()
```

**Key Points:**
- Callback runs in **separate thread** (non-blocking main thread)
- Ideal for real-time VAD processing
- `frames_per_buffer=512` matches Silero VAD window size

---

## 🏗️ SYSTEM ARCHITECTURE

### High-Level Flow
```
┌─────────────────────────────────────────────────────────────┐
│                     USER INPUT MODES                        │
├──────────────────────┬──────────────────────────────────────┤
│   BUTTON MODE        │         VOICE MODE                   │
│   (Manual Trigger)   │    (Auto-Triggered by VAD)           │
└──────────┬───────────┴──────────────┬───────────────────────┘
           │                          │
           ▼                          ▼
    ┌──────────────────────────────────────────┐
    │      PyAudio Stream (16kHz Mono)         │
    │      Callback: process_audio_chunk()     │
    └───────────────┬──────────────────────────┘
                    │
                    ▼
    ┌──────────────────────────────────────────┐
    │      Silero VAD (Voice Detection)        │
    │      - Detects speech vs non-speech      │
    │      - Returns probabilities/timestamps  │
    └───────────────┬──────────────────────────┘
                    │
                    ▼ (Speech Detected)
    ┌──────────────────────────────────────────┐
    │      Speech Buffer (Accumulate Audio)    │
    │      - Collect audio until silence       │
    │      - Min 0.5s, Max 10s chunks          │
    └───────────────┬──────────────────────────┘
                    │
                    ▼
    ┌──────────────────────────────────────────┐
    │      Whisper STT (Transcription)         │
    │      - GPU-accelerated inference         │
    │      - Target: <1s latency               │
    └───────────────┬──────────────────────────┘
                    │
                    ▼
    ┌──────────────────────────────────────────┐
    │      Intent Router (Command Parser)      │
    │      - "What's ahead?" → YOLO Vision     │
    │      - "Read text" → OCR                 │
    └───────────────┬──────────────────────────┘
                    │
                    ▼
    ┌──────────────────────────────────────────┐
    │      YOLO + Gemini/Kokoro TTS            │
    │      - Generate response                 │
    │      - Speak via Kokoro (fast, offline)  │
    └──────────────────────────────────────────┘
```

### State Machine
```
IDLE
 │
 ├── Button Press OR Voice Detected (VAD)
 ▼
LISTENING
 │
 ├── Accumulate audio chunks
 ▼
BUFFERING
 │
 ├── Silence detected OR max duration reached
 ▼
PROCESSING
 │
 ├── Whisper STT → Intent Router → YOLO → TTS
 ▼
SPEAKING
 │
 ├── TTS audio playback complete
 ▼
IDLE (repeat)
```

---

## 🛠️ TECHNOLOGY STACK (FINAL DECISION)

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| **STT** | OpenAI Whisper (`base` model) | ✅ Official repo, proven GPU support, 74M params, <1s latency |
| **VAD** | Silero VAD | ✅ Flexible chunks, better accuracy, streaming support |
| **Audio Capture** | PyAudio (callback mode) | ✅ Non-blocking, real-time, separate thread |
| **TTS** | Kokoro-82M | ✅ Local, offline, <500ms latency, 54 voices |

**Alternative Considered:** `faster-whisper` (use if latency >1s)

---

## 📁 FILE CHANGES REQUIRED

### New Files to Create
1. **`src/layer1_reflex/vad_handler.py`**
   - `VADHandler` class
   - Methods: `start_listening()`, `stop_listening()`, `is_speech_detected()`
   - Integration with PyAudio callbacks

2. **`docs/LAYER1_ARCHITECTURE.md`**
   - System overview
   - Component interactions
   - API specifications

3. **`docs/LAYER1_USER_GUIDE.md`**
   - How to use voice activation
   - How to change Kokoro voices
   - Troubleshooting guide

4. **`docs/LAYER1_API_REFERENCE.md`**
   - Full API documentation
   - Code examples

5. **`tests/test_whisper_handler.py`**
6. **`tests/test_kokoro_handler.py`**
7. **`tests/test_vad_handler.py`**
8. **`tests/test_layer1_integration.py`**

### Files to Modify
1. **`src/cortex_gui.py`**
   - Add voice activation mode toggle
   - Integrate `VADHandler`
   - Add `VOICE-ACTIVE` status indicator
   - Create threaded audio listener

2. **`requirements.txt`**
   - Add `silero-vad`
   - Add `pyaudio`

3. **`README.md`**
   - Update with voice activation feature
   - Add Layer 1 usage instructions

---

## 🧪 TESTING STRATEGY

### Unit Tests
1. **`test_whisper_handler.py`**
   - Test GPU inference
   - Test latency with various audio lengths
   - Test edge cases (empty audio, long audio, GPU fallback)

2. **`test_kokoro_handler.py`**
   - Test tuple extraction logic (line 200+)
   - Test all 7 American English voices
   - Test audio generation latency

3. **`test_vad_handler.py`**
   - Test speech detection accuracy
   - Test false positive/negative rates
   - Test buffer management

### Integration Tests
1. **`test_layer1_integration.py`**
   - Test button activation flow
   - Test voice activation flow
   - Test latency (<1s STT, <500ms TTS)
   - Test resource usage (RAM/GPU)
   - Test error recovery

### Performance Tests
- Profile with `cProfile`
- Optimize bottlenecks (likely Whisper inference)
- Test on Raspberry Pi 5 (if available)

---

## 📦 DEPENDENCIES

### New Python Packages
```txt
# Add to requirements.txt
silero-vad>=4.0.0
pyaudio>=0.2.11
```

### System Requirements
- **Microphone:** USB or built-in mic (16kHz+ sample rate)
- **GPU (Optional):** NVIDIA GPU with CUDA for Whisper acceleration
- **CPU Fallback:** Whisper works on CPU (slower, ~5-10s latency)

---

## ⚙️ IMPLEMENTATION SEQUENCE

### Phase 1: Validation (Items 9-10)
✅ Test existing `whisper_handler.py`  
✅ Test existing `kokoro_handler.py`

### Phase 2: VAD Implementation (Item 11)
🔨 Create `vad_handler.py`  
🔨 Implement `VADHandler` class  
🔨 Integrate Silero VAD + PyAudio callbacks

### Phase 3: GUI Integration (Item 12)
🔨 Update `cortex_gui.py`  
🔨 Add voice activation toggle  
🔨 Add `VOICE-ACTIVE` status indicator  
🔨 Create threaded audio listener

### Phase 4: Integration (Item 13)
🔨 Wire together: GUI → VAD → Whisper → YOLO → TTS  
🔨 Test both button and voice activation modes  
🔨 Ensure thread safety and resource cleanup

### Phase 5: Testing (Items 14-16)
🧪 Write unit tests  
🧪 Write integration tests  
🧪 Performance optimization

### Phase 6: Documentation (Items 17-18)
📝 Write user guide  
📝 Write API reference  
📝 Update main README

### Phase 7: Final Validation (Items 19-20)
✅ Run full test suite  
✅ Test on real hardware  
✅ Create demo video  
✅ Update MIGRATION_SUMMARY.md

---

## 🚀 NEXT STEPS

1. **START WITH VALIDATION:**
   - Run `python src/layer1_reflex/whisper_handler.py` to test STT
   - Run `python src/layer1_reflex/kokoro_handler.py` to test TTS

2. **IMPLEMENT VAD:**
   - Create `vad_handler.py` using Silero VAD
   - Test with real microphone input

3. **INTEGRATE GUI:**
   - Add voice activation mode to `cortex_gui.py`
   - Test both activation modes

4. **OPTIMIZE & DOCUMENT:**
   - Profile performance
   - Write comprehensive documentation

---

## 📊 SUCCESS CRITERIA

✅ **Whisper STT:** <1s latency for 5-second audio clips  
✅ **Kokoro TTS:** <500ms latency for short phrases  
✅ **Silero VAD:** <100ms speech detection latency  
✅ **Dual Activation:** Button + voice modes both work  
✅ **Resource Usage:** <4GB RAM, GPU optional  
✅ **Reliability:** 95%+ uptime, graceful error handling  
✅ **Documentation:** Complete user guide + API reference

---

## 🔥 FOUNDER'S NOTES (From Haziq)
- **Philosophy:** "Pain first, rest later" - We test thoroughly before celebrating
- **Quality Bar:** This is for **YIA 2026 Gold Medal** - no shortcuts
- **Engineering Reality:** We use real data, not hallucinations. Everything in this plan is backed by MCP research.

---

**APPROVED FOR IMPLEMENTATION**  
*Let's build this, Co-Founder.* 🚀
