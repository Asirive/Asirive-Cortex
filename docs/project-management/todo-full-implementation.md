# Project-Cortex v2.0 - Complete Implementation TODO List

**Status**: In Progress  
**Target**: YIA 2026 Competition  
**Hardware**: RTX 2050 (Development) → Raspberry Pi 5 (Production)  
**CUDA**: 12.8 (Development) → CPU-only (Production)

---

## Phase 1: Infrastructure & GPU Optimization ⏳

### 1.1 CUDA/GPU Configuration ✅ COMPLETED
- [x] Verify CUDA 12.8 + PyTorch 2.7.1 compatibility
- [x] Confirm RTX 2050 GPU detection
- [x] Test CUDA availability in Python
- **Result**: PyTorch 2.7.1+cu128, CUDA 12.8, RTX 2050 working

### 1.2 Project Structure Reorganization 🔄 IN PROGRESS
- [ ] Move all documentation to `docs/` folder
  - [x] Move FLICKERING_FIX.md to docs/
  - [x] Move CHANGELOG_2025-11-17.md to docs/
  - [ ] Create docs/ARCHITECTURE.md (update for new layers)
  - [ ] Create docs/API_KEYS.md (setup guide)
- [ ] Ensure all tests are in `tests/` folder
  - [x] test_yolo_cpu.py in tests/
  - [x] test_integration.py in tests/
  - [x] conftest.py in tests/
  - [ ] Add test_whisper_local.py
  - [ ] Add test_kokoro_tts.py
  - [ ] Add test_layer_routing.py
- [ ] Create proper config/ structure
  - [ ] config/layer_config.yaml (layer routing rules)
  - [ ] config/voices.yaml (TTS voice mappings)
  - [ ] config/model_paths.yaml (all model locations)

### 1.3 Update YOLO for GPU 🔄 IN PROGRESS
- [ ] Change YOLO_DEVICE from 'cpu' to 'cuda'
- [ ] Update .env.example with GPU settings
- [ ] Add GPU memory management for YOLO
- [ ] Benchmark RTX 2050 inference speed
- [ ] Add automatic fallback to CPU if GPU unavailable
- [ ] Test YOLO with different batch sizes on GPU

---

## Phase 2: Voice Input System (Speech-to-Text) 🔜 NEXT

### 2.1 Local Whisper Integration (Layer 1)
- [ ] Install OpenAI Whisper: `pip install openai-whisper`
- [ ] Download Whisper model (medium or large for accuracy)
  - [ ] Create models/whisper/ directory
  - [ ] Download with GPU support
  - [ ] Test model loading time
- [ ] Implement WhisperSTT class
  - [ ] Initialize with GPU device
  - [ ] Implement transcribe() method
  - [ ] Add language detection
  - [ ] Return confidence scores
- [ ] Audio recording improvements
  - [ ] Add VAD (Voice Activity Detection)
  - [ ] Implement recording indicator (visual feedback)
  - [ ] Add audio level meter
- [ ] Testing
  - [ ] Test with various accents
  - [ ] Measure latency (target: <2s)
  - [ ] Test GPU vs CPU performance

### 2.2 Hugging Face Whisper (Layer 2 Fallback)
- [ ] Keep existing Gradio client integration
- [ ] Use only for Layer 2 complex queries
- [ ] Implement fallback logic if local Whisper fails
- [ ] Add timeout handling (30s max)

---

## Phase 3: Voice Output System (Text-to-Speech) 🔜 NEXT

### 3.1 Kokoro TTS Local Integration (Layer 1)
- [ ] Clone/Install Kokoro TTS: `git clone https://github.com/PierrunoYT/Kokoro-TTS-Local`
- [ ] Setup KPipeline class
  - [ ] Initialize with GPU support
  - [ ] Download kokoro-v1_0.pth model
  - [ ] Download config.json
- [ ] Voice selection
  - [ ] Test all 31 available voices
  - [ ] Select default voice (e.g., 'af_alloy' - clear female)
  - [ ] Allow user voice preference in config
- [ ] Implement KokoroTTS class
  - [ ] load_voice() method
  - [ ] generate_speech() method
  - [ ] Save to temporary audio file
  - [ ] Play using pygame
- [ ] Testing
  - [ ] Test synthesis quality
  - [ ] Measure latency (target: <1s)
  - [ ] Test long vs short responses

### 3.2 TTS for Layer 2 (Gemini Responses)
- [ ] Keep existing TTS system or use Kokoro
- [ ] Add prosody/emotion support for richer responses
- [ ] Implement SSML support if needed

### 3.3 No TTS for Layer 3 (Remember AI)
- [ ] Layer 3 only stores context
- [ ] No voice output needed
- [ ] Visual confirmation only

---

## Phase 4: 3-Layer AI System Architecture 🔜 CRITICAL

### 4.1 Layer Decision Algorithm
- [ ] Create LayerRouter class
  - [ ] analyze_query(text) method
  - [ ] returns: layer_number (1, 2, or 3)
- [ ] Layer 1 (Simple - Local Only) Rules:
  - [ ] Keywords: "what do you see", "identify", "detect", "objects"
  - [ ] Short queries (<10 words)
  - [ ] Real-time safety queries
  - [ ] Response: YOLO detections + Kokoro TTS
- [ ] Layer 2 (Complex - Cloud AI) Rules:
  - [ ] Keywords: "describe", "read", "text", "what is", "explain"
  - [ ] Longer queries (>10 words)
  - [ ] Scene understanding needed
  - [ ] Response: Gemini 2.0 Flash + TTS
- [ ] Layer 3 (Remember AI - Context) Rules:
  - [ ] Keywords: "remember", "recall", "what did I", "earlier"
  - [ ] All queries processed through this layer
  - [ ] Stores conversation history
  - [ ] Uses Gemini API for memory retrieval
  - [ ] No TTS output (context only)

### 4.2 Layer 1 Implementation (Local YOLO + Whisper + Kokoro)
- [ ] Create Layer1Handler class
  - [ ] Uses local Whisper for STT
  - [ ] Gets YOLO detections from current frame
  - [ ] Formats simple response (e.g., "I see: person, car, bicycle")
  - [ ] Uses Kokoro TTS for output
  - [ ] Target latency: <3 seconds total
- [ ] Testing
  - [ ] Test offline functionality
  - [ ] Benchmark end-to-end latency
  - [ ] Test accuracy with real-world scenarios

### 4.3 Layer 2 Implementation (Gemini 2.0 Flash)
- [ ] Update to Gemini 2.0 Flash API
  - [ ] Check if model ID changed
  - [ ] Update API calls
  - [ ] Test with current API key
- [ ] Create Layer2Handler class
  - [ ] Uses Hugging Face Whisper for STT
  - [ ] Sends frame + YOLO context to Gemini
  - [ ] Gets detailed scene description
  - [ ] Uses TTS for output (Kokoro or cloud)
  - [ ] Target latency: <5 seconds total
- [ ] Enhance prompts
  - [ ] Add Layer 1 YOLO context to prompt
  - [ ] Request safety-first information
  - [ ] Limit response length (50 words for TTS)
- [ ] Testing
  - [ ] Test OCR capability (reading signs)
  - [ ] Test scene understanding
  - [ ] Test with poor lighting

### 4.4 Layer 3 Implementation (Remember AI)
- [ ] Create Layer3Handler class (Memory Management)
  - [ ] Uses Gemini API for context storage
  - [ ] No Whisper/TTS needed (piggybacks on Layer 1/2)
  - [ ] Stores conversation history
  - [ ] Retrieves relevant past interactions
- [ ] Memory storage
  - [ ] Use Gemini API's context window
  - [ ] Store last N interactions (configurable)
  - [ ] Tag with timestamps and locations (if GPS available)
- [ ] Memory retrieval
  - [ ] Query past conversations
  - [ ] Semantic search through history
  - [ ] Return relevant context to user
- [ ] Integration with all layers
  - [ ] ALL queries pass through Layer 3 first
  - [ ] Layer 3 adds context before routing to Layer 1/2
  - [ ] Layer 3 stores results after processing
- [ ] Testing
  - [ ] Test memory recall accuracy
  - [ ] Test context preservation
  - [ ] Test multi-turn conversations

---

## Phase 5: GUI Enhancements 🔜 NEXT

### 5.1 New GUI Workflow
- [ ] Keep existing video display canvas
- [ ] Redesign control panel
  - [ ] Single "Record & Send" button (primary action)
  - [ ] Layer indicator (shows Layer 1/2/3)
  - [ ] Recording status indicator (animated)
  - [ ] Processing status (Whisper → Layer → TTS)
- [ ] Audio controls
  - [ ] Microphone level meter (visual feedback)
  - [ ] Recording waveform display
  - [ ] TTS volume control
  - [ ] Mute toggle
- [ ] Response display
  - [ ] Show text response
  - [ ] Show which layer processed it
  - [ ] Show YOLO detections (always visible)
  - [ ] Show processing time breakdown

### 5.2 New Button: "Record & Send"
- [ ] Replace separate record/send buttons
- [ ] Workflow:
  1. Click button → Start recording
  2. Button shows "Recording..." (red pulse)
  3. User speaks (audio level meter shows input)
  4. Click again → Stop recording
  5. Button shows "Processing..."
  6. Whisper transcribes (local or HF based on layer)
  7. LayerRouter decides layer (1, 2, or 3)
  8. Layer processes query
  9. TTS speaks response (if Layer 1 or 2)
  10. Button returns to "Record & Send"
- [ ] Add keyboard shortcut (Space bar or Enter)
- [ ] Add visual feedback for each stage

### 5.3 Layer Indicator Widget
- [ ] Visual indicator showing current layer
  - Layer 1: Green badge "🟢 Local"
  - Layer 2: Blue badge "🔵 Cloud AI"
  - Layer 3: Purple badge "🟣 Memory"
- [ ] Show layer decision reason (tooltip)
- [ ] Add layer override option (developer mode)

---

## Phase 6: Configuration & Environment 🔜 NEXT

### 6.1 Update Environment Variables
- [ ] Create new .env structure
  ```bash
  # GPU Configuration
  DEVICE=cuda  # 'cuda' or 'cpu'
  YOLO_MODEL_PATH=models/yolo11x.pt
  YOLO_DEVICE=cuda  # Force GPU for YOLO
  
  # Whisper Configuration
  WHISPER_MODEL=medium  # tiny, base, small, medium, large
  WHISPER_DEVICE=cuda
  WHISPER_LOCAL=true  # Use local Whisper for Layer 1
  WHISPER_HF_API=hf-audio/whisper-large-v3  # For Layer 2
  
  # Kokoro TTS Configuration
  KOKORO_MODEL_PATH=models/kokoro/kokoro-v1_0.pth
  KOKORO_VOICE=af_alloy  # Default voice
  KOKORO_DEVICE=cuda
  
  # Layer Configuration
  LAYER_1_MAX_WORDS=10  # Max words for Layer 1 queries
  LAYER_2_MAX_RESPONSE_WORDS=50  # Limit for TTS
  LAYER_3_MEMORY_SIZE=20  # Number of past interactions to keep
  
  # Gemini API
  GOOGLE_API_KEY=your_key_here
  GEMINI_MODEL=gemini-2.0-flash-latest
  
  # Hugging Face (for Layer 2 Whisper fallback)
  HUGGINGFACE_API_TOKEN=your_token_here
  ```
- [ ] Update .env.example with all new variables
- [ ] Add validation for required API keys

### 6.2 Requirements.txt Update
- [ ] Add new dependencies:
  ```
  openai-whisper>=20231117
  kokoro-onnx>=0.1.0  # Or install from GitHub
  pydub>=0.25.1  # Audio manipulation
  webrtcvad>=2.0.10  # Voice Activity Detection
  ```
- [ ] Pin versions for reproducibility
- [ ] Separate dev requirements (pytest, etc.)

---

## Phase 7: Testing & Validation 🔜 IMPORTANT

### 7.1 Unit Tests
- [ ] tests/test_whisper_local.py
  - [ ] Test model loading
  - [ ] Test transcription accuracy
  - [ ] Test GPU utilization
  - [ ] Test latency
- [ ] tests/test_kokoro_tts.py
  - [ ] Test voice loading
  - [ ] Test speech generation
  - [ ] Test audio quality
  - [ ] Test GPU utilization
- [ ] tests/test_layer_router.py
  - [ ] Test Layer 1 detection (simple queries)
  - [ ] Test Layer 2 detection (complex queries)
  - [ ] Test Layer 3 detection (memory queries)
  - [ ] Test edge cases

### 7.2 Integration Tests
- [ ] tests/test_end_to_end.py
  - [ ] Test full workflow: record → STT → layer → response → TTS
  - [ ] Test Layer 1 full pipeline
  - [ ] Test Layer 2 full pipeline
  - [ ] Test Layer 3 memory storage/retrieval
  - [ ] Test layer switching mid-conversation
- [ ] tests/test_gpu_memory.py
  - [ ] Test GPU memory usage
  - [ ] Test multiple model loading
  - [ ] Test memory cleanup

### 7.3 Performance Benchmarks
- [ ] Create benchmarks/benchmark_layers.py
  - [ ] Measure Layer 1 latency (target: <3s)
  - [ ] Measure Layer 2 latency (target: <5s)
  - [ ] Measure Layer 3 latency (target: <2s)
  - [ ] Compare GPU vs CPU for each component
  - [ ] Create performance report

---

## Phase 8: Raspberry Pi Compatibility 🔜 LATER

### 8.1 Dual-Mode Configuration
- [ ] Create device detection logic
  - [ ] Detect if running on RPi vs laptop
  - [ ] Auto-configure device='cpu' for RPi
  - [ ] Auto-configure device='cuda' for laptop
- [ ] Model size optimization for RPi
  - [ ] Use yolo11m.pt instead of yolo11x.pt on RPi
  - [ ] Use Whisper 'small' instead of 'medium' on RPi
  - [ ] Test if Kokoro TTS works on RPi CPU

### 8.2 Deployment Scripts
- [ ] Create deploy_to_rpi.sh
  - [ ] SSH to RPi
  - [ ] Transfer files
  - [ ] Install dependencies
  - [ ] Configure for CPU
  - [ ] Test on RPi
- [ ] Create start scripts for both platforms
  - [ ] start_laptop.ps1 (GPU mode)
  - [ ] start_rpi.sh (CPU mode)

---

## Phase 9: Documentation 📝 ONGOING

### 9.1 User Documentation
- [ ] docs/USER_GUIDE.md
  - [ ] Installation instructions
  - [ ] First-time setup
  - [ ] How to use the 3 layers
  - [ ] Voice command examples
  - [ ] Troubleshooting
- [ ] docs/VOICE_COMMANDS.md
  - [ ] Layer 1 example commands
  - [ ] Layer 2 example commands
  - [ ] Layer 3 example commands
  - [ ] Tips for best recognition

### 9.2 Developer Documentation
- [ ] docs/ARCHITECTURE.md (update)
  - [ ] 3-Layer system diagram
  - [ ] Data flow diagrams
  - [ ] Class hierarchy
  - [ ] API reference
- [ ] docs/LAYER_ROUTING.md
  - [ ] How the LayerRouter works
  - [ ] Algorithm explanation
  - [ ] How to customize rules
- [ ] docs/GPU_OPTIMIZATION.md
  - [ ] GPU memory management
  - [ ] Performance tuning
  - [ ] CUDA best practices

### 9.3 API Keys Setup
- [ ] docs/API_KEYS.md
  - [ ] How to get Google Gemini API key
  - [ ] How to get Hugging Face token
  - [ ] Setting up .env file
  - [ ] Security best practices

---

## Phase 10: Advanced Features 🔮 FUTURE

### 10.1 3D Spatial Audio (OpenAL)
- [ ] Research OpenAL for Python
- [ ] Implement spatial audio for directions
- [ ] Test with headphones
- [ ] Add to Layer 1 for obstacle warnings

### 10.2 GPS Integration
- [ ] Add GPS module support
- [ ] Location-based context for Layer 3
- [ ] Navigation assistance
- [ ] Location tagging in memory

### 10.3 Caregiver Dashboard
- [ ] Web dashboard (FastAPI + React)
- [ ] Live feed from camera
- [ ] Conversation history
- [ ] Alert system
- [ ] Remote configuration

---

## Critical Path (Priority Order)

### Week 1: Foundation
1. ✅ GPU Configuration & Testing
2. 🔄 Project Structure Reorganization
3. 🔄 Update YOLO for GPU
4. 🔜 Install Whisper + Kokoro TTS

### Week 2: Core Layers
5. 🔜 Implement Layer 1 (Local YOLO + Whisper + Kokoro)
6. 🔜 Implement LayerRouter (decision algorithm)
7. 🔜 Update Layer 2 (Gemini 2.0 Flash)
8. 🔜 Implement Layer 3 (Remember AI)

### Week 3: Integration
9. 🔜 New GUI with "Record & Send" button
10. 🔜 Layer indicator widget
11. 🔜 End-to-end testing
12. 🔜 Performance optimization

### Week 4: Polish
13. 🔜 Documentation completion
14. 🔜 User testing
15. 🔜 Bug fixes
16. 🔜 YIA demo preparation

---

## Dependencies to Install

```bash
# Core ML
pip install openai-whisper
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# Kokoro TTS
git clone https://github.com/PierrunoYT/Kokoro-TTS-Local
cd Kokoro-TTS-Local
pip install -r requirements.txt
cd ..

# Audio processing
pip install pydub
pip install webrtcvad
pip install sounddevice
pip install scipy

# Existing
pip install ultralytics
pip install google-generativeai
pip install gradio-client
pip install python-dotenv
pip install pygame
pip install pillow
pip install opencv-python
```

---

## Success Metrics

### Layer 1 (Local)
- ✅ Transcription accuracy >90%
- ✅ End-to-end latency <3 seconds
- ✅ Works offline
- ✅ GPU utilization >70%

### Layer 2 (Cloud)
- ✅ Scene description accuracy >85%
- ✅ End-to-end latency <5 seconds
- ✅ OCR accuracy >90%

### Layer 3 (Memory)
- ✅ Context recall accuracy >95%
- ✅ Retrieval latency <2 seconds
- ✅ Stores 20+ conversations

### Overall
- ✅ User can complete task without visual input
- ✅ System makes correct layer decision >90% of time
- ✅ TTS sounds natural and clear
- ✅ System works on both laptop (GPU) and RPi (CPU)

---

**Generated**: November 17, 2025  
**Author**: Haziq (@IRSPlays)  
**Competition**: YIA 2026  
**Target**: Gold Medal 🥇
