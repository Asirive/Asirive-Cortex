# VAD Debugging Guide - Project Cortex

**Date:** November 20, 2025  
**Author:** GitHub Copilot (CTO)  
**Status:** ✅ IMPLEMENTED & READY FOR TESTING

---

## 🎯 Problem Statement

**User Issue:** "The VAD is not really working because it detects the voice but I am not sure if it recorded stop or still recording."

### Root Causes Identified

1. **VAD Not Loaded on Startup** - VAD was lazy-loaded only when voice activation was enabled
2. **Insufficient State Visibility** - No debug logging showing speech start/end transitions
3. **Recording State Uncertainty** - User couldn't tell when recording was active vs stopped
4. **Pipeline Entry Unclear** - No confirmation when audio was sent to Whisper/Router/TTS

---

## ✅ Solutions Implemented

### 1. **VAD Eager Loading on Startup** ✅

**File:** `src/cortex_gui.py` (Line ~175)

```python
# Initialize all handlers EAGERLY on startup (no lazy loading)
logger.info("⏳ Initializing all AI handlers on startup...")
self.init_whisper_stt()
self.init_kokoro_tts()
self.init_gemini_tts()
self.init_vad()  # ✅ Load VAD on startup for instant voice activation
```

**Benefits:**
- VAD indicator turns **green** immediately when GUI starts
- No loading delay when enabling voice activation
- User can see VAD is ready to use

---

### 2. **Comprehensive VAD Configuration Logging** ✅

**File:** `src/cortex_gui.py` (init_vad function)

When VAD initializes, you'll now see:

```
⏳ Initializing Silero VAD...
📋 VAD Configuration:
   Sample Rate: 16000 Hz
   Chunk Size: 512 samples (32.0ms)
   Threshold: 0.5 (0.0=sensitive, 1.0=strict)
   Min Speech: 500ms
   Min Silence: 700ms (to end recording)
   Padding: 300ms (before/after speech)
🔄 Loading Silero VAD model...
✅ Silero VAD initialized and ready
```

**Benefits:**
- Understand VAD sensitivity settings
- Know how long silence is needed to end recording (700ms)
- See padding duration that captures context

---

### 3. **VAD Model Loading Details** ✅

**File:** `src/layer1_reflex/vad_handler.py` (load_model function)

```
⏳ Loading Silero VAD model from torch.hub...
📥 Model Source: snakers4/silero-vad
✅ Silero VAD model loaded in 2.34s
🔄 Creating VADIterator for streaming mode...
📋 VADIterator Configuration:
   Sampling Rate: 16000 Hz
   Threshold: 0.5
   Min Silence Duration: 700ms
✅ VADIterator initialized successfully
```

**Benefits:**
- Know where VAD model comes from
- See how long it takes to load
- Verify iterator is configured correctly

---

### 4. **Real-Time Chunk Processing Debug Logs** ✅

**File:** `src/layer1_reflex/vad_handler.py` (_process_audio_chunks function)

**Every 32ms chunk shows:**

```
📊 Chunk #42: VAD latency=3.2ms, Queue size=0, Speech active=False, Buffer size=0 chunks
📊 Chunk #43: VAD latency=2.8ms, Queue size=0, Speech active=True, Buffer size=15 chunks
```

**Benefits:**
- See VAD processing in real-time
- Monitor latency (target: <10ms)
- Track buffer growth during speech

---

### 5. **Speech Start Detection Logging** ✅

**When you start speaking:**

```
🗣️ SPEECH START (Segment #1): Chunk #43, Event: {'start': 1.37}, Padding added: 9 chunks
```

**In GUI debug console:**

```
🗣️ VAD: Speech START detected - Recording audio...
⏺️ Recording State: ACTIVE
Status: 🎤 RECORDING SPEECH...
```

**Benefits:**
- **INSTANT FEEDBACK** when speech is detected
- Know exactly which chunk triggered detection
- See how much padding was added for context
- Status bar shows you're recording

---

### 6. **Speech End Detection Logging** ✅

**When you stop speaking (700ms silence):**

```
🔇 SPEECH END DETECTED: Silence threshold reached, Buffer has 47 chunks
✅ VALID SPEECH SEGMENT: Duration=1500ms, Samples=24000, Min required=500ms, Status=SENDING_TO_PIPELINE
📤 Calling on_speech_end callback...
✅ on_speech_end callback completed
🧹 Clearing speech buffer (47 chunks)
```

**In GUI debug console:**

```
🔇 VAD: Speech END detected
⏹️ Recording State: STOPPED
📊 Audio Stats: Duration=1500ms, Samples=24000
💾 Saving audio to: C:\Users\Haziq\Documents\ProjectCortex\temp_mic_input.wav
✅ Audio file saved: 96044 bytes
🔄 Sending VAD audio to processing pipeline...
📋 Pipeline Entry Point: process_recorded_audio()
✅ VAD audio sent to pipeline, waiting for next speech...
```

**Benefits:**
- **CLEAR CONFIRMATION** when recording stops
- See exact duration and sample count
- Verify audio file was saved successfully
- Know when audio enters Whisper/Router/TTS pipeline

---

### 7. **Short Segment Rejection Logging** ✅

**If you speak too briefly (<500ms):**

```
⚠️ REJECTED SHORT SEGMENT: Duration=320ms < Minimum=500ms, Status=DISCARDED
```

**Benefits:**
- Understand why short utterances are ignored
- Prevents false triggers from background noise
- Shows VAD quality control is working

---

### 8. **VAD State Reset Logging** ✅

**When voice activation is disabled:**

```
🔄 Resetting VAD iterator states...
✅ VAD iterator states reset complete
```

**Benefits:**
- Confirm VAD is properly reset between sessions
- Ensures no "ghost" speech segments carry over

---

## 🧪 Testing Instructions

### Step 1: Launch GUI and Verify VAD Loads

1. Run: `python src\cortex_gui.py`
2. **Expected Output in Debug Console:**
   ```
   ⏳ Initializing Silero VAD...
   📋 VAD Configuration: (all parameters listed)
   ✅ Silero VAD initialized and ready
   ```
3. **Expected Visual:** VAD indicator dot turns **GREEN** on startup

---

### Step 2: Enable Voice Activation

1. Click **"🎙️ Voice Activation"** toggle in GUI
2. **Expected Output:**
   ```
   🎤 Starting VAD listening...
   ✅ VAD listening started
   ✅ Voice Activation ENABLED - Speak to interact
   ```
3. **Expected Visual:** VAD indicator turns **YELLOW** (active listening mode)
4. Status bar shows: **"Status: VOICE-ACTIVATED MODE"**

---

### Step 3: Test Speech Detection

1. **Speak clearly:** "What objects do you see?"
2. **Expected Output (Speech Start):**
   ```
   🗣️ SPEECH START (Segment #1): Chunk #X, Event: {...}, Padding added: Y chunks
   🗣️ VAD: Speech START detected - Recording audio...
   ⏺️ Recording State: ACTIVE
   ```
3. **While Speaking:**
   - Debug console shows real-time chunk processing
   - Status bar: **"🎤 RECORDING SPEECH..."**
   - VAD indicator: **YELLOW** (processing)

4. **After 700ms of Silence:**
   ```
   🔇 SPEECH END DETECTED: Silence threshold reached, Buffer has Z chunks
   ✅ VALID SPEECH SEGMENT: Duration=XXXXms, Samples=XXXXX, Status=SENDING_TO_PIPELINE
   💾 Saving audio to: temp_mic_input.wav
   ✅ Audio file saved: XXXXX bytes
   🔄 Sending VAD audio to processing pipeline...
   ```

5. **Expected Pipeline Flow:**
   ```
   [STAGE 1] 🎙️ Transcribing audio with Whisper...
   [STAGE 1] ✅ Transcription: "what objects do you see" (Latency: XXXms)
   [STAGE 2] 🧠 Routing intent...
   [STAGE 2] ✅ Intent Router: LAYER_1_REFLEX (Latency: XXms)
   [STAGE 3] 🔄 Executing Layer 1: Real-time Reflex (YOLO + Kokoro TTS)
   Layer 1: Processing reflex response...
   Layer 1: YOLO detected X objects
   Layer 1: Generating TTS response...
   ✅ TTS audio generated (XXX bytes)
   🔊 Playing audio...
   ```

---

### Step 4: Verify VAD Behavior

**Test Case A: Normal Speech (>500ms)**
- ✅ Should detect, record, and process
- ✅ Audio file saved
- ✅ Pipeline executes
- ✅ TTS plays response

**Test Case B: Short Utterance (<500ms)**
- ✅ Should reject with warning:
  ```
  ⚠️ REJECTED SHORT SEGMENT: Duration=XXXms < Minimum=500ms, Status=DISCARDED
  ```
- ✅ No audio file saved
- ✅ No pipeline execution

**Test Case C: Continuous Speaking**
- ✅ Recording continues until 700ms of silence
- ✅ Buffer grows (check chunk count logs)
- ✅ Final audio contains full utterance

**Test Case D: Background Noise**
- ✅ Should NOT trigger if below 0.5 threshold
- ✅ Check chunk logs for speech probability values

---

## 📊 Performance Metrics to Monitor

### VAD Latency (Target: <10ms)
```
📊 Chunk #X: VAD latency=3.2ms ✅ GOOD
📊 Chunk #Y: VAD latency=15.8ms ❌ SLOW (investigate)
```

### Speech Detection Accuracy
- **True Positive:** Speech detected when you speak ✅
- **False Positive:** Speech detected when silent ❌
- **True Negative:** No detection when silent ✅
- **False Negative:** No detection when you speak ❌

### End-to-End Latency (VAD → TTS)
```
Speech END → Whisper (XXXms) → Router (XXms) → Layer 1 (XXXms) → TTS (XXXms)
Total: XXXX ms (Target: <3000ms)
```

---

## 🔧 Troubleshooting

### Issue: VAD Indicator Stays Grey on Startup

**Cause:** VAD failed to load  
**Check:**
```
❌ VAD init error: [error message]
```
**Solution:**
1. Verify `silero-vad` installed: `pip show silero-vad`
2. Check PyAudio installed: `pip show pyaudio`
3. Restart GUI

---

### Issue: "Recording State: ACTIVE" Never Shows "STOPPED"

**Cause:** Silence threshold not met (need 700ms silence)  
**Check:**
```
📊 Chunk logs show: Speech active=True (continuously)
```
**Solution:**
1. Stop speaking for 700ms (0.7 seconds)
2. If background noise is high, increase `min_silence_duration_ms` to 1000ms
3. Check microphone sensitivity settings

---

### Issue: All Speech Rejected as "SHORT SEGMENT"

**Cause:** Speaking too briefly (<500ms)  
**Check:**
```
⚠️ REJECTED SHORT SEGMENT: Duration=XXXms < Minimum=500ms
```
**Solution:**
1. Speak longer phrases (>0.5 seconds)
2. Lower `min_speech_duration_ms` to 300ms if needed
3. Check VAD threshold (0.5 = balanced, lower = more sensitive)

---

### Issue: No Speech Detection at All

**Cause:** VAD threshold too high or mic not working  
**Check:**
```
📊 Chunk logs: No SPEECH START events
```
**Solution:**
1. Test microphone in Windows Sound Settings
2. Select correct input device in GUI dropdown
3. Lower VAD threshold from 0.5 to 0.3 (more sensitive)
4. Check chunk logs for any speech probability values

---

## 🎓 Understanding VAD Parameters

### `threshold` (0.0 - 1.0)
- **0.3** = Very sensitive (detects whispers, more false positives)
- **0.5** = Balanced (recommended, good for normal speech)
- **0.7** = Strict (requires clear loud speech, fewer false positives)

**Current Setting:** `0.5`

---

### `min_speech_duration_ms`
- Minimum duration to consider speech valid
- **500ms** = Rejects quick clicks, coughs, short noise
- Lower = More responsive, but more false positives
- Higher = Fewer false triggers, but may miss quick questions

**Current Setting:** `500ms`

---

### `min_silence_duration_ms`
- How long to wait after speech ends before stopping recording
- **700ms** = Wait 0.7 seconds of silence to end
- Lower = Faster response, but may cut off speech
- Higher = More complete sentences, but slower response

**Current Setting:** `700ms`

---

### `padding_duration_ms`
- Audio padding added before/after speech
- **300ms** = Captures 0.3s before speech starts (context)
- Helps Whisper get full context
- Prevents word cutoff at start/end

**Current Setting:** `300ms`

---

## 📚 References

### Research Sources Used

1. **Context7 MCP:** Silero VAD documentation and examples
2. **GitHub MCP:** snakers4/silero-vad repository (best practices)
3. **DeepWiki MCP:** Voice Activity Detection algorithms

### Key Findings from Research

- **VADIterator** is the correct class for streaming audio (not batch mode)
- `reset_states()` must be called after each audio stream to prevent state leakage
- Chunk size must be 512 for 16kHz (32ms windows)
- Speech probability uses hysteresis: `threshold` for start, `threshold - 0.15` for end

---

## 🚀 Next Steps

1. **Test All Debug Logging** (TODO #12)
   - Enable voice activation
   - Speak test phrases
   - Verify all debug messages appear
   - Check VAD indicator state changes

2. **Measure End-to-End Latency**
   - Time from "Speech END" to TTS playback
   - Target: <3 seconds
   - Log all pipeline stages

3. **Optimize VAD Parameters**
   - Test different thresholds (0.3, 0.5, 0.7)
   - Adjust silence duration for your use case
   - Fine-tune speech duration minimum

4. **Add Timeout Protection** (Future TODO)
   - Wrap Whisper in timeout (30s)
   - Wrap Gemini API in timeout (60s)
   - Handle timeout errors gracefully

---

## ✅ Summary

**Before:**
- ❌ VAD loaded only when voice activation enabled
- ❌ No visibility into speech start/end
- ❌ User unsure if recording stopped
- ❌ No confirmation when audio sent to pipeline

**After:**
- ✅ VAD loads on GUI startup (green indicator)
- ✅ Real-time chunk processing logs every 32ms
- ✅ Clear "SPEECH START" and "SPEECH END" messages
- ✅ Recording state shown: ACTIVE / STOPPED
- ✅ Audio file save confirmation with size
- ✅ Pipeline entry notification
- ✅ Comprehensive debug logging at every stage
- ✅ VAD state reset logging

**Result:** You now have **FULL VISIBILITY** into the VAD pipeline. Every chunk, every state transition, every decision is logged in the debug console.

---

**Ready to Test!** 🚀

Run the GUI and enable voice activation. Watch the debug console light up with real-time VAD processing information!
