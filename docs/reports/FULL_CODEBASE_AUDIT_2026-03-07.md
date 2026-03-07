# Project Cortex — Full Codebase Audit Report

**Date:** March 7, 2026  
**Audited by:** 9 parallel subagents (deep read of every file)  
**Scope:** All `rpi5/`, `laptop/`, `shared/`, config, requirements  

---

## Executive Summary

| Severity | Count | Description |
|----------|-------|-------------|
| 🔴 CRITICAL | **22** | System crashes, safety failures, security breaches, data loss |
| 🟠 HIGH | **31** | Broken features, race conditions, resource leaks |
| 🟡 MEDIUM | **28** | Logic bugs, dead code, edge cases |
| 🔵 LOW | **15** | Code quality, docs, minor cleanup |
| **TOTAL** | **96** | |

---

## 🔴 CRITICAL BUGS (Must Fix Before Any Deployment)

### C1. Layer 2 Force Override — ALL voice queries go to Gemini
- **File:** [rpi5/main.py](../rpi5/main.py) ~line 1445–1449
- **Code:** `if target_layer != "layer2": target_layer = "layer2"`
- **Impact:** IntentRouter is completely bypassed. Layer 0/1/3 voice commands ALL route to Gemini. Entire routing system is dead.
- **Fix:** Delete lines 1445–1449

### C2. `trigger_haptic_feedback()` NEVER CALLED
- **File:** [rpi5/layer0_guardian/__init__.py](../rpi5/layer0_guardian/__init__.py) ~line 298
- **Impact:** Safety-critical! A blind user gets NO haptic alerts for obstacles. The method exists but is never invoked from `detect()` or `main.py`.
- **Fix:** Add `self.trigger_haptic_feedback(detections)` at end of `detect()` method

### C3. Haptic pulse duration = 300 SECONDS (should be 0.3s)
- **File:** [rpi5/main.py](../rpi5/main.py) ~line 1308
- **Code:** `self.layer0.haptic.pulse(intensity=100, duration=300)`
- **Impact:** Motor vibrates for 5 minutes straight, blocking the detection thread
- **Fix:** Change to `duration=0.3`

### C4. SpatialAudioManager NEVER instantiated
- **File:** [rpi5/main.py](../rpi5/main.py) — `CortexSystem.__init__()`
- **Impact:** 7-module PyOpenAL+HRTF spatial audio system is 100% dead code. Never receives detections.
- **Fix:** Instantiate in `__init__()`, wire `update_detections()` in main loop

### C5. GeminiLiveHandler.disconnect() does NOT exist
- **File:** [rpi5/main.py](../rpi5/main.py) ~line 1818
- **Code:** `run_async_safe(self.layer2.disconnect())` → `AttributeError`
- **Reality:** The method is called `close()` in `gemini_live_handler.py`
- **Fix:** Change to `self.layer2.close()` or add `disconnect()` alias

### C6. `_send_to_laptop()` indentation error — send_detection unreachable
- **File:** [rpi5/main.py](../rpi5/main.py) ~line 1276–1282
- **Impact:** Detection data never reaches the laptop dashboard
- **Fix:** Fix indentation on `self.ws_client.send_detection()` call

### C7. Layer 1 method name mismatch → AttributeError crash
- **File:** [rpi5/layer1_learner/__init__.py](../rpi5/layer1_learner/__init__.py) ~line 259
- **Code:** `self.prompt_manager.get_all_classes()` — method doesn't exist
- **Actual:** Method is `get_current_prompts()`
- **Fix:** Change to `self.prompt_manager.get_current_prompts()`

### C8. NCNN model: `set_classes()` crashes unconditionally
- **File:** [rpi5/layer1_learner/__init__.py](../rpi5/layer1_learner/__init__.py) ~line 476
- **Code:** `self.model.get_text_pe(class_names)` — NCNN models don't have this method
- **Impact:** TEXT_PROMPTS mode crashes on NCNN models
- **Fix:** Add `hasattr()` guard before calling `get_text_pe()`

### C9. Visual prompts bboxes wrapped in extra list dimension
- **File:** [rpi5/layer1_learner/__init__.py](../rpi5/layer1_learner/__init__.py) ~line 751
- **Code:** `"bboxes": [prompt.bboxes]` — adds (1, N, 4) instead of (N, 4)
- **Fix:** Remove the list wrapper: `"bboxes": prompt.bboxes`

### C10. Hardcoded Supabase credentials in config.yaml
- **File:** [rpi5/config/config.yaml](../rpi5/config/config.yaml) ~line 12–14
- **Code:** `anon_key: "sb_publishable_..."` in plaintext
- **Impact:** Anyone with repo access owns the Supabase database
- **Fix:** Move to `.env` file, load with `os.getenv()`

### C11. Hardcoded Supabase credentials in laptop/config.py
- **File:** [laptop/config.py](../laptop/config.py) ~line 75–77
- **Same issue as C10** — duplicate exposure in laptop code
- **Fix:** Environment variables only

### C12. WiFi detection always returns True
- **File:** [rpi5/layer4_memory/hybrid_memory_manager.py](../rpi5/layer4_memory/hybrid_memory_manager.py) ~line 333
- **Code:** `return True` (stub)
- **Impact:** Upload attempts on offline device, drains battery, errors
- **Fix:** Implement real WiFi check with `socket.gethostbyname()`

### C13. Cleanup deletes UNSYNCED rows (permanent data loss)
- **File:** [rpi5/layer4_memory/hybrid_memory_manager.py](../rpi5/layer4_memory/hybrid_memory_manager.py) ~line 228
- **Impact:** Unsynced detections deleted if sync fails → data permanently lost
- **Fix:** Only delete rows where `synced = 1`

### C14. Race condition in sync tracking — wrong rows marked synced
- **File:** [rpi5/layer4_memory/hybrid_memory_manager.py](../rpi5/layer4_memory/hybrid_memory_manager.py) ~line 315
- **Impact:** Uses float timestamp for matching → precision loss → wrong rows updated
- **Fix:** Use `row_id` (integer primary key) instead of timestamp

### C15. CORS open to world on FastAPI server
- **File:** [laptop/server/fastapi_server.py](../laptop/server/fastapi_server.py) ~line 61–68
- **Code:** `allow_origins=["*"]` + `allow_credentials=True`
- **Impact:** Remote hijacking of WebSocket connections, command injection
- **Fix:** Restrict to `["http://localhost:8765"]`

### C16. Duplicate protocol.py — type mismatches everywhere
- **File:** [laptop/protocol.py](../laptop/protocol.py) vs [shared/api/protocol.py](../shared/api/protocol.py)
- **Impact:** `laptop.protocol.MessageType ≠ shared.api.MessageType` → runtime crashes
- **Fix:** Delete `laptop/protocol.py`, use `shared.api` everywhere

### C17. GUI crashes from non-main-thread Qt signal emission
- **File:** [laptop/cli/start_dashboard.py](../laptop/cli/start_dashboard.py) ~line 80–110
- **Impact:** ZMQ thread emits Qt signals directly → segfaults, "deleted C++ object"
- **Fix:** Use queue + QTimer for thread-safe Qt updates

### C18. Python built-in ConnectionError shadowed
- **File:** [shared/api/exceptions.py](../shared/api/exceptions.py) ~line 22
- **Code:** `class ConnectionError(CortexException)` — shadows built-in
- **Impact:** `except ConnectionError:` catches custom but misses real network errors
- **Fix:** Rename to `CortexConnectionError`

### C19. HEF model path not validated before Hailo use
- **File:** [rpi5/hailo_depth.py](../rpi5/hailo_depth.py) ~line 98–99
- **Impact:** Runtime crash if HEF file missing
- **Fix:** Add `Path(hef_path).exists()` check

### C20. Dual VDevice creation crash (Hailo depth + OCR)
- **File:** [rpi5/hailo_depth.py](../rpi5/hailo_depth.py) ~line 124–132
- **Impact:** Two modules try to create separate Hailo VDevices → hardware conflict
- **Fix:** Create singleton VDevice manager

### C21. Bluetooth has NO auto-reconnect
- **File:** [rpi5/bluetooth_handler.py](../rpi5/bluetooth_handler.py) ~line 203–217
- **Impact:** If BT headphones disconnect, blind user loses all audio — no retry
- **Fix:** Add reconnect loop with exponential backoff

### C22. OpenAL crashes on headless RPi5 (no audio device)
- **File:** [rpi5/layer3_guide/spatial_audio/manager.py](../rpi5/layer3_guide/spatial_audio/manager.py) ~line 424
- **Code:** `oalInit()` — no try/except
- **Fix:** Wrap in try/except, return False if no device

---

## 🟠 HIGH SEVERITY (31 issues)

### Main Orchestrator (main.py)
| # | Issue | Line(s) |
|---|-------|---------|
| H1 | `run_async_safe()` broken for threaded event loops — RuntimeError | ~922–933 |
| H2 | Fire-and-forget WebSocket `start()` — no await, no error check | ~1361 |
| H3 | Gemini connection result not checked, success logged anyway | ~1401–1407 |
| H4 | Config direct key access (`config['layer0']['device']`) — KeyError on missing | ~747,760,777,693 |
| H5 | `VisionQueryHandler` imported but never used | ~213 |
| H6 | Bare `except Exception: pass` in camera init | ~669 |

### Layer 0 (Guardian)
| # | Issue | Line(s) |
|---|-------|---------|
| H7 | Missing safety classes: bicycle, fire hydrant, bench, traffic light | ~57 |
| H8 | Proximity thresholds NOT validated with real distances | ~219–234 |
| H9 | `pulse()` is BLOCKING with `time.sleep()` — stalls detection thread | haptic_controller ~113 |
| H10 | Model metadata check logs error but continues anyway — no fail-safe | ~105–122 |
| H11 | No frame null-check in `detect()` | ~171 |

### Layer 1 (Learner)
| # | Issue | Line(s) |
|---|-------|---------|
| H12 | Adaptive prompt mass-pruning can delete ALL dynamic prompts | ~360–383 |
| H13 | Race condition in `add_from_gemini()` — no atomic save | ~180–200 |
| H14 | Model reload without cleanup — OOM on RPi5 (4GB) | ~196–239 |

### Layer 2 (Thinker)
| # | Issue | Line(s) |
|---|-------|---------|
| H15 | Audio queue unbounded — memory leak if player crashes | gemini_live ~87 |
| H16 | GeminiLive not wired to voice pipeline — HTTP GeminiTTS used instead | main.py ~1493 |
| H17 | API key rotation missing in GeminiLiveHandler (exists in GeminiTTS) | gemini_live ~61 |

### Layer 3 (Guide)
| # | Issue | Line(s) |
|---|-------|---------|
| H18 | ProximityAlertSystem alert thread target function MISSING | proximity_alert ~150 |
| H19 | ObjectTracker race condition — dict modified during iteration | object_tracker |
| H20 | Router keyword conflict: "find" routes to Layer 1 instead of Layer 3 | router ~67 |
| H21 | `update_detections()` never called from main orchestrator | __init__ ~60 |

### Layer 4 (Memory)
| # | Issue | Line(s) |
|---|-------|---------|
| H22 | `synchronous=NORMAL` — data loss on power failure (RPi5 wearable!) | HMM |
| H23 | No rate limiting / backoff — can exceed Supabase free tier quota | HMM |
| H24 | DB connections never closed — resource exhaustion | HMM |
| H25 | No timeout on Supabase API calls — hangs forever | HMM |
| H26 | One Supabase error permanently disables sync | HMM |

### Laptop
| # | Issue | Line(s) |
|---|-------|---------|
| H27 | No authentication on WebSocket connections | fastapi_server ~441 |
| H28 | No rate limiting — DoS possible | fastapi_server ~468 |
| H29 | Corrupted JPEG frames crash server (no validation) | cortex_dashboard ~115 |

### Hardware
| # | Issue | Line(s) |
|---|-------|---------|
| H30 | Hailo depth scale_factor not calibrated — distances meaningless | hailo_depth ~98 |
| H31 | Audio alerts can't play simultaneously (lock held during playback) | audio_alerts ~161 |

---

## 🟡 MEDIUM SEVERITY (28 issues — abbreviated)

| # | Category | Issue |
|---|----------|-------|
| M1 | main.py | TTSRouter instantiated 4× per execution (should be singleton) |
| M2 | main.py | Camera capture_thread.join(timeout=2.0) — thread may outlive cleanup |
| M3 | main.py | OCR exception silently falls through to Gemini |
| M4 | main.py | `reference_images` feature may not match Gemini API signature |
| M5 | Layer 0 | Dual latency measurements (two separate timers) confusing |
| M6 | Layer 0 | `inference_times` list not thread-safe |
| M7 | Layer 1 | Stale embeddings on mode switch (old visual prompts not cleared) |
| M8 | Layer 1 | Redundant mode assignment (4× in switch_mode) |
| M9 | Layer 1 | No warning when dynamic prompts collapse to zero |
| M10 | Layer 2 | Session resumption handle saved but never used for reconnect |
| M11 | Layer 2 | Kokoro fallback lazy-loads on first failure (500ms+ delay) |
| M12 | Layer 2 | Cartesia handler exists but never in fallback chain |
| M13 | Layer 3 | GPS functions stubbed with `return None # TODO` |
| M14 | Layer 3 | Comfort settings (volume ramping, interval pings) never wired |
| M15 | Layer 3 | Detection aggregator returns `""` for no detections (TTS speaks nothing) |
| M16 | Layer 3 | Sample rate mismatch: sound generator 44.1kHz vs device 48kHz |
| M17 | Layer 3 | ObjectSoundMapper defined but never used |
| M18 | Layer 4 | Timestamp float vs ISO string mismatch |
| M19 | Layer 4 | Multi-row operations not transactional |
| M20 | Layer 4 | Unbounded upload queue (could OOM) |
| M21 | Laptop | Signal/slots not disconnected → memory leaks |
| M22 | Laptop | Frame rate unlimited (60 FPS uncapped) |
| M23 | Laptop | Layer1Service.process_frame() not implemented |
| M24 | Shared | 8 MessageTypes have no factory functions |
| M25 | Shared | No input validation on message deserialization |
| M26 | Shared | SyncWebSocketClient has broken abstract methods |
| M27 | Config | Relative paths in YAML break if cwd changes |
| M28 | Config | Version conflicts in requirements.txt (torch/scipy) |

---

## 🔵 LOW SEVERITY (15 issues — abbreviated)

- Dead `repeat` parameter in haptic `pulse()`
- Router memory logging spam (146MB/year)
- Missing `gps_handler.py`, `imu_handler.py` files (config references them)
- Duplicate WebSocket clients (`fastapi_client.py` vs `websocket_client.py`)
- TTS recording files never cleaned up
- Config CPU threads=6 on 4-core RPi5 (over-subscription)
- Conversation memory extraction method not validated
- Head tracking config section unused
- Generic `except Exception:` used instead of custom exceptions (7 instances)
- Various missing docstrings and documentation gaps

---

## Priority Fix Order

### Phase 0: SAFETY-CRITICAL (do first)
1. **C2** — Wire haptic feedback (blind user safety)
2. **C3** — Fix 300-second pulse duration
3. **H7** — Expand safety classes
4. **H9** — Make haptic pulse non-blocking

### Phase 1: SYSTEM INTEGRITY (system won't crash)
5. **C1** — Remove Layer 2 force override
6. **C5** — Fix disconnect() → close()
7. **C6** — Fix _send_to_laptop() indentation
8. **C7** — Fix get_all_classes() → get_current_prompts()
9. **C8** — Guard NCNN set_classes()
10. **C9** — Fix visual prompts bbox dimension

### Phase 2: SECURITY
11. **C10/C11** — Move all credentials to .env
12. **C15** — Restrict CORS origins
13. **C18** — Rename ConnectionError

### Phase 3: DATA INTEGRITY
14. **C12** — Implement real WiFi check
15. **C13** — Fix cleanup to preserve unsynced rows
16. **C14** — Fix sync tracking with row_id

### Phase 4: INTEGRATION WIRING
17. **C4** — Instantiate SpatialAudioManager
18. **C16** — Delete duplicate protocol.py
19. **C22** — Guard OpenAL initialization
20. **H16** — Wire GeminiLive to voice pipeline
21. **H21** — Wire update_detections() in main loop

### Phase 5: ROBUSTNESS
22. **C21** — Bluetooth auto-reconnect
23. **C20** — Singleton Hailo VDevice
24. **C19** — Validate HEF paths
25. All HIGH issues

---

*Generated by 9 parallel deep-audit subagents covering every .py file in the project.*
