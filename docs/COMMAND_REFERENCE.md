# ProjectCortex v2.0 — Command Reference

> All commands run from the project root: `cd ~/ProjectCortex` (RPi5) or `cd C:\Users\Haziq\Documents\ProjectCortex` (Laptop)

---

## 1. Main System Commands

### Start Everything (Production)

```bash
# Terminal 1 (Laptop): Start dashboard + server
python -m laptop all --fastapi

# Terminal 2 (RPi5): Start wearable (all 5 layers + sensors)
python -m rpi5 all
```

### RPi5 Wearable — `python -m rpi5`

| Command | Description |
|---------|-------------|
| `python -m rpi5 all` | Start all layers + camera + sensors |
| `python -m rpi5 all --offline` | Start without cloud/network |
| `python -m rpi5 all --no-haptic` | Start without vibration motor |
| `python -m rpi5 all --laptop 10.207.144.101` | Specify laptop IP |
| `python -m rpi5 layer0` | Layer 0: Guardian (YOLO safety detection) |
| `python -m rpi5 layer1` | Layer 1: Learner (adaptive YOLOE) |
| `python -m rpi5 layer2` | Layer 2: Thinker (Gemini Live API) |
| `python -m rpi5 layer3` | Layer 3: Guide (router + spatial audio) |
| `python -m rpi5 layer4` | Layer 4: Memory (SQLite + Supabase) |
| `python -m rpi5 camera` | Test camera capture |
| `python -m rpi5 camera --device 1` | Test specific camera device |
| `python -m rpi5 audio` | Test audio I/O |
| `python -m rpi5 connect` | Test WebSocket connection to laptop |
| `python -m rpi5 connect --port 8765` | Specify port |
| `python -m rpi5 status` | Check system status |
| `python -m rpi5 test` | Run self-test diagnostics |
| `python -m rpi5 --version` | Print version |
| `python rpi5/main.py` | Direct start (all layers) |
| `python rpi5/main.py --debug` | Start with debug logging |

### Laptop Dashboard — `python -m laptop`

| Command | Description |
|---------|-------------|
| `python -m laptop all --fastapi` | Start FastAPI server + PyQt6 GUI |
| `python -m laptop all` | Start WebSocket server + GUI |
| `python -m laptop all --host 0.0.0.0 --port 8765` | Specify bind address |
| `python -m laptop server --fastapi` | Start FastAPI server only (no GUI) |
| `python -m laptop server --gui` | Start server with GUI |
| `python -m laptop gui` | Launch PyQt6 GUI only (no server) |
| `python -m laptop gui --theme dark` | GUI with theme |
| `python -m laptop status` | Check server status |
| `python -m laptop --version` | Print version |

### Direct Server Launch

| Command | Description |
|---------|-------------|
| `python laptop/server/fastapi_server.py --host 0.0.0.0 --port 8765` | FastAPI server standalone |
| `python laptop/server/fastapi_integration.py --host 0.0.0.0 --port 8765` | FastAPI integration server |
| `python laptop/cli/start_dashboard.py --fastapi --host 0.0.0.0` | Dashboard CLI launcher |
| `python laptop/gui/cortex_ui.py` | Full PyQt6 dashboard |
| `python laptop/gui/cortex_dashboard.py` | Simplified dashboard |
| `python laptop/config.py` | Print config summary |

---

## 2. File Sync (Laptop ? RPi5)

```bash
python sync_rpi5.py <command>
```

| Command | Description |
|---------|-------------|
| `python sync_rpi5.py to-rpi` | Sync project files TO RPi5 via rsync/SFTP |
| `python sync_rpi5.py from-rpi` | Sync logs, recordings FROM RPi5 |
| `python sync_rpi5.py install` | Install Python dependencies on RPi5 |
| `python sync_rpi5.py full` | Sync to RPi5 AND install deps |

**Network:** RPi5 `10.207.144.31` ? Laptop `10.207.144.101`

---

## 3. Model Conversion

### Unified Converter

```bash
python "Conversion Scripts/convert_all_models.py" --all          # Convert all models
python "Conversion Scripts/convert_all_models.py" --list         # List available models
python "Conversion Scripts/convert_all_models.py" --imgsz 256    # Set image size
```

### YOLOE ? ONNX

```bash
python "Conversion Scripts/convert_yoloe_to_onnx.py" --all                # All YOLOE ? ONNX
python "Conversion Scripts/convert_yoloe_to_onnx.py" -m yoloe-26s-seg.pt  # Specific model
python "Conversion Scripts/convert_yoloe_to_onnx.py" --list               # List models
python "Conversion Scripts/convert_yoloe_to_onnx.py" --imgsz 640          # Image size
```

### YOLOE ? NCNN

```bash
python "Conversion Scripts/convert_yoloe_to_ncnn.py" --all                # All YOLOE ? NCNN
python "Conversion Scripts/convert_yoloe_to_ncnn.py" -m yoloe-26s-seg.pt  # Specific model
python "Conversion Scripts/convert_yoloe_to_ncnn.py" --imgsz 256          # Image size
```

### Other Exports

```bash
python "Conversion Scripts/convert_to_ncnn.py"    # YOLO/YOLOE ? NCNN at 192×192 FP16
python export_pf_models.py                        # YOLOE PF ? ONNX
python export_pf_torchscript.py                   # YOLOE PF ? TorchScript
python rpi5/export_to_onnx.py                     # Models ? ONNX at 192px
```

---

## 4. Testing

### Pytest

```bash
pytest tests/ -v                                    # Run ALL tests
pytest tests/ -v --cov=src --cov-report=html        # With coverage report
PYTHONPATH=rpi5 pytest tests/ -v                     # Fix import path issues (Linux)
$env:PYTHONPATH="rpi5"; pytest tests/ -v             # Fix import path issues (PowerShell)
```

### Individual Test Files

```bash
pytest tests/test_router_fix.py -v                  # Intent router accuracy
pytest tests/test_router_priority_fix.py -v         # Router priority logic
pytest tests/test_dual_yolo.py -v                   # Dual-model YOLO
pytest tests/test_cascading_fallback.py -v          # Cascading fallback
pytest tests/test_spatial_audio.py -v               # Spatial audio
pytest tests/test_memory_storage.py -v              # Memory storage
pytest tests/test_hybrid_memory_manager.py -v       # Hybrid memory manager
pytest tests/test_integration.py -v                 # Integration tests
pytest tests/test_rpi5_simulator.py -v              # RPi5 simulator
pytest tests/test_gemini_2_flash.py -v              # Gemini 2 Flash API
pytest tests/test_gemini_live_api.py -v             # Gemini Live WebSocket
pytest tests/test_gemini_tts.py -v                  # Gemini TTS
pytest tests/test_layer1_service.py -v              # Layer 1 service
pytest tests/test_latency.py -v                     # Latency benchmarks
pytest tests/test_video_receiver.py -v              # Video receiver
pytest tests/test_gui_integration.py -v             # GUI integration
pytest tests/test_yolo_cpu.py -v                    # YOLO CPU inference
```

### Single Test Function

```bash
pytest tests/test_router_fix.py::test_router -v
```

### Syntax Check (Quick Validation)

```bash
python -m py_compile rpi5/main.py
python -m py_compile laptop/server/fastapi_server.py
python -m py_compile laptop/gui/cortex_ui.py
```

---

## 5. Component Testing (Direct Execution)

### Layer 0 — Guardian (YOLO + Haptics)

```bash
python rpi5/layer0_guardian/__init__.py              # Test YOLO detection
python rpi5/layer0_guardian/haptic_controller.py     # Test vibration patterns
```

### Layer 1 — Learner (Adaptive YOLOE)

```bash
python rpi5/layer1_learner/__init__.py               # Test YOLOE detection
python rpi5/layer1_learner/adaptive_prompt_manager.py # Test prompt learning
python rpi5/layer1_learner/visual_prompt_manager.py   # Test visual prompts
```

### Layer 1 — Reflex (Voice Pipeline)

```bash
python rpi5/layer1_reflex/whisper_handler.py     # Test Whisper STT
python rpi5/layer1_reflex/vad_handler.py         # Test VAD (live mic)
python rpi5/layer1_reflex/kokoro_handler.py      # Test Kokoro TTS
```

### Layer 2 — Thinker (Gemini / LLM)

```bash
python rpi5/layer2_thinker/gemini_live_handler.py      # Test Gemini Live API
python rpi5/layer2_thinker/glm4v_handler.py            # Test GLM-4V fallback
python rpi5/layer2_thinker/streaming_audio_player.py   # Test audio streaming
```

### Layer 3 — Guide (Router + Spatial Audio)

```bash
python rpi5/layer3_guide/detection_aggregator.py                  # Test detection formatting
python rpi5/layer3_guide/detection_router.py                      # Test detection routing
python rpi5/layer3_guide/spatial_audio/manager.py                 # Test spatial audio (L?R pan)
python rpi5/layer3_guide/spatial_audio/object_sounds.py           # Test object?sound mapping
python rpi5/layer3_guide/spatial_audio/object_tracker.py          # Test object tracking
python rpi5/layer3_guide/spatial_audio/position_calculator.py     # Test bbox?3D position
python rpi5/layer3_guide/spatial_audio/audio_beacon.py            # Test navigation beacon
python rpi5/layer3_guide/spatial_audio/proximity_alert.py         # Test proximity alerts
python rpi5/layer3_guide/spatial_audio/sound_generator.py         # Test sound generation
```

### Layer 4 — Memory

```bash
python rpi5/layer4_memory/__init__.py                  # Test memory manager
python rpi5/layer4_memory/hybrid_memory_manager.py     # Test hybrid SQLite+Supabase
```

### Other Modules

```bash
python rpi5/benchmark_models.py          # Benchmark NCNN models
python rpi5/websocket_client.py          # Test WebSocket with simulated data
python rpi5/fastapi_client.py            # Test FastAPI client with simulated data
python rpi5/bluetooth_handler.py         # List Bluetooth devices
python rpi5/bluetooth_handler.py connect # Connect to BT device
python rpi5/tts_router.py               # Test TTS engine selection
python rpi5/tts_router.py "Hello world" # Speak text through TTS
python rpi5/vision_query_handler.py      # Test vision queries (mock)
```

---

## 6. Benchmarking

```bash
python rpi5/benchmark_models.py                               # Benchmark all NCNN models
python tests/benchmark_models.py --all                        # Benchmark all formats
python tests/benchmark_models.py --model yolo11n              # Specific model
python tests/benchmark_models.py --format ncnn                # Specific format (pytorch/ncnn/onnx/openvino)
python tests/demo_three_modes.py                              # Demo YOLOE 3 modes
```

---

## 7. Utility Scripts

```bash
python utils/configure_hrtf.py                 # Configure OpenAL HRTF (spatial audio)
python laptop/protocol.py                      # Print protocol message examples
python test_kokoro_debug.py                    # Debug Kokoro TTS
python test_zai_coding_endpoint.py             # Test Z.ai GLM-4V API
```

---

## 8. Shell Scripts (RPi5 / Linux)

```bash
./validate_hardware.sh           # Validate RPi5 hardware (CPU, RAM, camera, GPIO, audio)
./install_flask_dashboard.sh     # Install Flask + Gunicorn for web dashboard
./enhance_dashboard.sh           # Patch dashboard with debug logging
```

---

## 9. Git Workflow

```bash
git add -A
git commit -m "feat: description"
git push projectcortexv2 main           # Push to ProjectCortexV2 remote
git push origin main                     # Push to Gemini-Cortex remote
```

---

## 10. Quick Reference — Most Used

```bash
# -- FULL SYSTEM --
python -m laptop all --fastapi           # Laptop (start first)
python -m rpi5 all                       # RPi5 (start second)

# -- DEBUG --
python rpi5/main.py --debug              # RPi5 with verbose logging

# -- SYNC --
python sync_rpi5.py full                 # Sync code + install deps on RPi5

# -- TEST --
pytest tests/ -v                         # Run all tests
python -m py_compile rpi5/main.py        # Quick syntax check

# -- BENCHMARK --
python rpi5/benchmark_models.py          # Model speed benchmark
```
