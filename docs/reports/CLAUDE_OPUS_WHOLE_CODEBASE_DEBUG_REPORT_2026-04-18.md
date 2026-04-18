# Project Cortex - Whole Codebase Debug Report for Claude Opus

**Date:** April 18, 2026  
**Audit method:** 15 focused subagents, static diagnostics, targeted code inspection  
**Scope:** `rpi5/`, `laptop/`, `shared/`, `tests/`, `docs/`, startup scripts, deployment artifacts  
**Important:** This document intentionally lists problems only. It does not include proposed fixes.

---

## Top Blockers

1. The active outdoor and indoor navigation flow can go silent under the default Gemini 3.1 Live configuration because both Gemini-generated nav turns and local fallback speech are suppressed in overlapping ways.
2. Cross-system communication is fragmented across incompatible protocol and transport paths, so dashboard controls, REST commands, and legacy WebSocket commands do not reliably reach the wearable.
3. Indoor guidance is not a real navigation session in the current flow; `guide_indoor` bypasses the main navigation state machine and can report success without establishing usable indoor guidance behavior.
4. Multiple shutdown, reconnect, and async-loop paths are unsafe, including a server-stop deadlock, client-stop loop races, and unsynchronized cross-thread navigation mutation from Gemini and voice callbacks.
5. The memory sync pipeline is not operational in the normal startup path, and local/remote persistence has queue and SQLite race conditions.
6. Camera, GPS, microphone, and audio-output recovery all have stale-state or cleanup bugs that can leave the system appearing alive while operating on dead hardware state.
7. The dashboard exposes several controls that are optimistic, stale, or no-op, so UI state can claim success while the device state is unchanged.
8. Route and transit metadata handling has drifted: waypoint advancement, maneuver transfer, and transit bus-state activation can all be wrong or unreachable.
9. The detection stack has stale-cache and state-type bugs that can produce phantom detections, lagged overlays, broken mode switches, or learned prompts being ignored in production.
10. Test and documentation coverage no longer match the codebase closely enough to act as a trustworthy regression or operator guide.

---

## 1. Gemini Live, Voice, and Navigation

- **Critical** - Default Gemini Live behavior and nav speech suppression combine into a silent-guidance failure mode. The current default model path is Gemini 3.1, mid-session context delivery is disabled on that path, synthetic Gemini nav turns are disabled, and `NavigationEngine` suppresses its own speech when Gemini is considered online. Approaching turns, crossings, arrival, and indoor-transition prompts can therefore have no spoken output path at all.  
  **Files:** `rpi5/config/config.yaml`, `rpi5/main.py`, `rpi5/layer2_thinker/gemini_live_handler.py`, `rpi5/layer3_guide/navigation_engine.py`

- **Critical** - `guide_indoor` does not establish a real indoor navigation session. It mutates navigation mode directly and calls the main-process callback, but it does not transition the navigation state machine through the normal `NavigationEngine` path. The rest of the system still gates indoor behavior on active navigation state, so Gemini can remain idle, proactive indoor narration stays off, and the nav loop can revert mode later.  
  **Files:** `rpi5/main.py`, `rpi5/layer3_guide/navigation_engine.py`

- **High** - The indoor-navigation voice path has a combined "heard but no response" failure pattern. Audit findings indicate valid STT output can be dropped under overlap, indoor phrases can false-match duplicate or echo suppression, and Gemini session loss around Live API code `1007` can leave the live turn gone while local suppression still prevents recovery.  
  **Files:** `rpi5/voice_coordinator.py`, `rpi5/layer2_thinker/gemini_live_handler.py`, `rpi5/main.py`

- **High** - Voice pipeline coordination is internally inconsistent. Rejected short utterances can leave unmatched VAD start/end markers, local TTS is not gated under the same output-playing coordination as streamed Gemini output, and valid indoor-navigation phrases can be filtered as duplicates.  
  **Files:** `rpi5/voice_coordinator.py`, `rpi5/layer1_reflex/vad_handler.py`, `rpi5/layer2_thinker/gemini_live_handler.py`

- **High** - Activity markers and real-time media share the same Gemini input path, so activity boundaries can be misordered relative to audio delivery. That creates a manual-VAD drift risk where the server sees incomplete or late speech boundaries relative to the audio payload.  
  **Files:** `rpi5/layer2_thinker/gemini_live_handler.py`, `rpi5/voice_coordinator.py`

- **High** - Interruption cooldown logic can skip relevant incoming events and turn-complete handling. When that happens during a Live session disruption, the system can lose a turn and still suppress fallback behavior as if the live response were still valid.  
  **Files:** `rpi5/layer2_thinker/gemini_live_handler.py`

- **High** - The current code still assumes Gemini 3.1 session context can be relied on in ways the runtime path does not actually deliver. Context and state continuity are treated as available after reconnect or mid-session updates even when the selected path disables or loses them.  
  **Files:** `rpi5/layer2_thinker/gemini_live_handler.py`, `rpi5/main.py`

- **High** - Dashboard-issued text queries are effectively dropped or deprioritized when Gemini is online. That creates a control-path mismatch where text-triggered device actions behave differently depending on live session state.  
  **Files:** `rpi5/main.py`, `laptop/server/fastapi_server.py`

- **High** - Local Layer 1 and Layer 2 voice paths are effectively dead or bypassed in normal orchestration. The result is that large portions of the intended routing model no longer function as independent fallback paths when Gemini is live or partially live.  
  **Files:** `rpi5/main.py`, `rpi5/layer3_guide/router.py`

- **High** - Route step metadata is misaligned with waypoint usage in the new route-tool chain. Instructions can be associated with the wrong waypoints, which corrupts navigation semantics even when route fetch succeeds.  
  **Files:** `rpi5/layer3_guide/gmaps_directions.py`, `rpi5/layer3_guide/navigation_engine.py`

- **High** - Transit walking legs lose maneuver metadata during route conversion. That strips useful turn semantics out of mixed-mode routes before navigation execution.  
  **Files:** `rpi5/layer3_guide/gmaps_directions.py`, `rpi5/layer3_guide/navigation_engine.py`

- **High** - The first transit leg may never transition the engine into `WAITING_FOR_BUS`. That breaks downstream transit-state behavior even when a route is otherwise activated.  
  **Files:** `rpi5/layer3_guide/navigation_engine.py`, `rpi5/layer2_thinker/lta_datamall.py`

- **High** - Navigation accuracy handling assumes fixes expose an `accuracy` field, but active GPS sources do not. This leaves `_gps_accuracy` at the fallback extreme value and can make non-final waypoint advancement unreachable while still accepting poor phone-based coordinates as usable fixes.  
  **Files:** `rpi5/layer3_guide/navigation_engine.py`, `rpi5/hardware/gps_handler.py`, `rpi5/hardware/fused_gps.py`, `rpi5/hardware/phone_gps.py`

- **High** - Stale last-known GPS fixes can feed routing and arrival logic after the real signal quality has changed. That can yield wrong route origins, false arrivals, or navigation progress based on old coordinates.  
  **Files:** `rpi5/layer3_guide/navigation_engine.py`, `rpi5/hardware/gps_handler.py`, `rpi5/hardware/fused_gps.py`

- **Medium** - The `start_outdoor_navigation` compatibility tool always prefers the default saved location over live GPS when a default exists. Routes can therefore begin from the wrong origin whenever the user is not physically at that saved default.  
  **Files:** `rpi5/main.py`, `rpi5/layer3_guide/saved_locations.py`

---

## 2. Protocol, Dashboard, and Cross-System Control

- **Critical** - The repo still contains dual incompatible protocol definitions. `laptop/protocol.py` and `shared/api/protocol.py` both define message structures and enums that are not interchangeable, yet different runtime paths import different versions.  
  **Files:** `laptop/protocol.py`, `shared/api/protocol.py`, `rpi5/websocket_client.py`, `rpi5/fastapi_client.py`, `laptop/server/websocket_server.py`, `laptop/server/fastapi_server.py`

- **Critical** - Client/server pairing is ambiguous at runtime. The wearable conditionally imports both the legacy WebSocket client and the newer FastAPI client, while the laptop side exposes multiple server implementations. There is no strong validation that the chosen client and server are protocol-compatible.  
  **Files:** `rpi5/main.py`, `rpi5/websocket_client.py`, `rpi5/fastapi_client.py`, `laptop/__main__.py`, `laptop/server/websocket_server.py`, `laptop/server/fastapi_server.py`

- **High** - In the real FastAPI dashboard startup path, REST control endpoints remain effectively unavailable because the shared server is injected into the app but not started in the state expected by the control handlers. `/api/v1/control` and `/api/v1/broadcast` can reject requests even while devices are connected over WebSocket.  
  **Files:** `laptop/server/fastapi_server.py`, `laptop/cli/start_dashboard.py`

- **High** - The FastAPI REST control path serializes command arguments under `data.parameters`, but device-side consumers expect sibling fields such as `data.mode`, `data.query`, and `data.layer`. REST-issued commands can therefore arrive with missing arguments and silently no-op or log validation errors.  
  **Files:** `shared/api/protocol.py`, `laptop/server/fastapi_server.py`, `rpi5/fastapi_client.py`, `rpi5/main.py`

- **High** - Legacy WebSocket dashboard commands are double-serialized. The UI sends an already serialized JSON string, the server serializes it again, and the fallback client parses the outer JSON into a plain string and then treats that string as a dict-like payload. Commands are dropped before action routing.  
  **Files:** `laptop/cli/start_dashboard.py`, `laptop/server/websocket_server.py`, `rpi5/websocket_client.py`

- **High** - Even correctly delivered legacy dashboard control messages do not change wearable state, because the legacy fallback client does not wire a dashboard-command callback equivalent to the FastAPI path and treats control messages as future placeholders.  
  **Files:** `rpi5/main.py`, `rpi5/websocket_client.py`

- **High** - The Layer 1 offload contract is broken in both laptop server stacks. One path calls a nonexistent synchronous `run_inference()` API, and the other logs the request without emitting the expected response message.  
  **Files:** `laptop/server/websocket_server.py`, `laptop/server/fastapi_server.py`, `laptop/layer1_service.py`, `shared/api/protocol.py`, `rpi5/fastapi_client.py`

- **High** - GUI command sends block the Qt thread while waiting synchronously for device send completion, up to five seconds per connected device. A slow network or stuck event loop can freeze the dashboard during normal control use.  
  **Files:** `laptop/cli/start_dashboard.py`

- **High** - The FastAPI disconnect callback is wired to a Qt signal that expects one argument, but the server emits two. Disconnect-time exceptions can prevent accurate GUI state updates and interrupt cleanup sequencing.  
  **Files:** `laptop/cli/start_dashboard.py`, `laptop/server/fastapi_integration.py`, `laptop/server/fastapi_server.py`

- **High** - The dashboard production toggle is optimistic and not state-authoritative. It updates its own label and checked state immediately on click before device confirmation exists, so the UI can claim a mode change that never reached the RPi5.  
  **Files:** `laptop/gui/cortex_ui.py`, `laptop/cli/start_dashboard.py`, `rpi5/main.py`

- **Medium** - Several visible dashboard controls are no-ops or stubbed paths, including `START STREAM`, `Cloud Sync`, `STOP SERVICE`, and multiple layer restart buttons. They present as active operational controls while doing nothing or only logging placeholders.  
  **Files:** `laptop/gui/cortex_ui.py`, `laptop/cli/start_dashboard.py`, `rpi5/main.py`

- **Medium** - The dashboard exposes multiple independent Layer 1 mode selectors for the same backend state without a return path to keep them synchronized. The two widgets can diverge from each other and from the real device mode.  
  **Files:** `laptop/gui/cortex_ui.py`, `rpi5/main.py`, `rpi5/fastapi_client.py`

- **Medium** - Feed and connection state shown in the dashboard are not authoritative. Uptime counters, navbar status, and camera/feed status can stay stale after stream loss or disconnect, and multi-device state is collapsed poorly.  
  **Files:** `laptop/cli/start_dashboard.py`, `laptop/server/video_receiver.py`, `laptop/gui/cortex_ui.py`, `laptop/server/fastapi_server.py`

- **Medium** - The documented server-only/headless dashboard path is not real. Both `server` and `server --gui` ultimately construct the Qt dashboard, so a claimed headless mode does not exist in practice.  
  **Files:** `laptop/__main__.py`, `laptop/cli/start_dashboard.py`

---

## 3. Memory and Persistence

- **High** - The memory sync worker does not run in the normal startup path. It is started from synchronous initialization, creates a task on a newly created loop, and that loop is never actually driven, so queued detections remain local and never sync to Supabase.  
  **Files:** `rpi5/main.py`, `rpi5/layer4_memory/hybrid_memory_manager.py`

- **High** - Layer 0 and Layer 1 write through a shared SQLite connection and a shared upload queue without proper synchronization. Under load, DB writes and queue slicing/reassignment can race and lose or duplicate persistence work.  
  **Files:** `rpi5/main.py`, `rpi5/layer0_guardian/__init__.py`, `rpi5/layer1_learner/__init__.py`, `rpi5/layer4_memory/hybrid_memory_manager.py`

- **High** - Live Gemini voice conversations are not persisted correctly. The production `GeminiLiveManager` does not pass a memory manager into `GeminiLiveHandler`, and the audio path updates history/query state differently from text paths, so live spoken conversations are not reliably saved and response logging can attach to stale text state.  
  **Files:** `rpi5/main.py`, `rpi5/layer2_thinker/gemini_live_handler.py`

- **Medium** - The `search_memory` tool claims to search saved items and saved locations, but the callback only delegates to `memory_manager.recall`. `SavedLocations` is not queried, so configured places such as home or school are invisible to that tool.  
  **Files:** `rpi5/layer2_thinker/gemini_live_handler.py`, `rpi5/main.py`, `rpi5/layer3_guide/saved_locations.py`

- **Medium** - `HybridMemoryManager.recall()` performs raw substring search over local conversations without role filtering and returns empty location metadata even on matches. It can return the user's own question as the "memory" while still producing no structured location output.  
  **Files:** `rpi5/main.py`, `rpi5/layer4_memory/hybrid_memory_manager.py`

- **Medium** - `ConversationManager` restores the last session on startup regardless of age and resets its activity timestamp to now. Arbitrarily old conversational context can therefore bleed into new interactions after restart.  
  **Files:** `rpi5/conversation_manager.py`

- **Medium** - The memory manager is only truly hybrid for detections. Query logs, system logs, and heartbeats are remote-only and are simply skipped when Supabase is unavailable, so offline periods silently lose those records.  
  **Files:** `rpi5/layer4_memory/hybrid_memory_manager.py`

- **Medium** - A heartbeat-specific Supabase RPC ambiguity can set the shared `supabase_available` flag to false directly instead of through a cooldown path. One heartbeat failure can disable all later cloud sync and cloud-backed writes for the lifetime of the process.  
  **Files:** `rpi5/layer4_memory/hybrid_memory_manager.py`

---

## 4. Hardware, Perception, and Detection

- **High** - Camera recovery after a start failure is broken. `CameraHandler.start()` marks the camera as running before backend initialization fully succeeds, so a failed open can leave later restart attempts short-circuited as "already running" while other code still reports that the camera is back.  
  **Files:** `rpi5/main.py`

- **High** - Camera read failures turn into stale vision rather than no-camera fallback. Capture loops lack strong liveness handling, and `get_frame()` can keep returning the last successful frame after disconnect or capture exception, freezing detections and Gemini context on old imagery.  
  **Files:** `rpi5/main.py`

- **Medium** - Microphone startup failures can leak input resources. PyAudio and stream objects may be partially allocated before `is_listening` becomes true, and the failure cleanup path can return early because it believes listening never started.  
  **Files:** `rpi5/layer1_reflex/vad_handler.py`

- **Medium** - Graceful shutdown does not stop the voice capture pipeline. `VoiceCoordinator` is constructed and started, but teardown stops camera, Gemini, and sensors without calling `VoiceCoordinator.stop()`.  
  **Files:** `rpi5/main.py`, `rpi5/voice_coordinator.py`

- **Medium** - GPS availability becomes stale. UART GPS and phone GPS latch connected/receiving state after initial success and do not age that state back out cleanly when data stops. Downstream status reporting and fused GPS behavior can therefore claim a live source that is gone.  
  **Files:** `rpi5/hardware/gps_handler.py`, `rpi5/hardware/phone_gps.py`, `rpi5/hardware/fused_gps.py`, `rpi5/main.py`

- **Medium** - Fall detection has no debounce or cooldown. One low-acceleration event can trigger repeated fall alerts, repeated TTS, and repeated haptic behavior in rapid succession.  
  **Files:** `rpi5/hardware/imu_handler.py`, `rpi5/main.py`

- **Medium** - The streaming audio player can fail permanently after transient output-device issues. After enough startup failures it stops retrying for the rest of the process, and the failure counter is not reset when the audio device comes back.  
  **Files:** `rpi5/layer2_thinker/streaming_audio_player.py`

- **Medium** - The proactive scene-change path treats `depth_map.mean()` as physical distance even though the Hailo depth model is handled as inverse depth. That makes depth-change narration and Gemini depth context semantically wrong.  
  **Files:** `rpi5/hailo_depth.py`, `rpi5/main.py`, `rpi5/layer2_thinker/scene_change_detector.py`

- **Medium** - Indoor/outdoor classification is a single-frame whole-image heuristic with no hysteresis and no unknown state. Doorways, windows, clipped far regions, or noisy deep pixels can flip the result and immediately retune depth thresholds, safety cooldowns, environment status, and Gemini transition behavior.  
  **Files:** `rpi5/hailo_depth.py`, `rpi5/main.py`

- **Medium** - `SafetyMonitor` only prunes tracked-object history after choosing a winning alert. Frames with detections but no selected alert can leave stale distance samples indefinitely, allowing old state to leak into later approach-velocity decisions.  
  **Files:** `rpi5/safety_monitor.py`

- **High** - Laptop Layer 1 offload drops empty inference results, so the last positive detection set stays cached and voice queries can speak phantom objects for several seconds after the scene changed.  
  **Files:** `laptop/cli/start_dashboard.py`, `rpi5/main.py`

- **High** - Dashboard-issued Layer 1 mode changes can corrupt learner state. The UI sends raw strings, the device-side fallback can store that raw string as `self.layer1.mode`, and the learner later expects a `YOLOEMode` enum and dereferences `.value`.  
  **Files:** `laptop/gui/cortex_ui.py`, `rpi5/main.py`, `rpi5/layer1_learner/__init__.py`

- **Medium** - Dashboard detection overlays are drawn from the latest inference results onto a just-arrived video frame even though inference for that exact frame has not completed yet. Boxes can lag and appear on the wrong objects or even the wrong scene.  
  **Files:** `laptop/cli/start_dashboard.py`, `laptop/layer1_service.py`

- **Medium** - Adaptive prompts are persisted and reloaded by the prompt manager, but the production learner still boots with a hard-coded base class list and skips applying the loaded prompts. Learned vocabulary can exist on disk while live detection continues using the old classes.  
  **Files:** `rpi5/layer1_learner/adaptive_prompt_manager.py`, `rpi5/layer1_learner/__init__.py`, `tests/test_dual_yolo.py`

- **Medium** - Cross-layer detection aggregation resolves same-class conflicts by taking the maximum count rather than deduplicating or counting distinct objects spatially. Spoken scene summaries can therefore undercount or arbitrarily count visible objects.  
  **Files:** `rpi5/layer3_guide/detection_aggregator.py`, `rpi5/main.py`

---

## 5. Async, Threading, and Connectivity

- **Critical** - `AsyncWebSocketServer.stop()` can deadlock. It holds a non-reentrant `asyncio.Lock` and then awaits a client-disconnect path that tries to acquire the same lock again. Shutdown can hang indefinitely whenever clients are connected.  
  **Files:** `shared/api/base_server.py`

- **High** - `AsyncWebSocketClient.stop()` races shutdown by stopping the background loop before scheduling the async disconnect that is supposed to run on that same loop. Cleanup can fail or hang in a loop-lifecycle race.  
  **Files:** `shared/api/base_client.py`

- **High** - The shared client reconnect logic only performs one reconnect cycle after a disconnect. If the nested reconnect attempts all fail, the outer loop exits while the client can still be marked as running, leaving a permanently disconnected but apparently active client.  
  **Files:** `shared/api/base_client.py`

- **High** - Server-to-device send failures do not fully unregister server-side connection state. A failed send can remove a socket from one map but still leave surrounding bookkeeping intact, which creates stale connected-state assumptions and silent command-delivery failures.  
  **Files:** `laptop/server/fastapi_server.py`, `shared/api/base_server.py`

- **High** - Gemini reconnect can loop forever trying to resume an invalid session handle. Stale handles are not cleared in every disconnect path, including the `1007`-style Live session failure case, so reconnect can repeatedly attempt to resume a dead session.  
  **Files:** `rpi5/layer2_thinker/gemini_live_handler.py`

- **High** - The voice pipeline wires the async `handle_voice_command()` coroutine directly into callback-thread execution, and the fallback path uses `asyncio.run()` in that callback thread. This mutates orchestrator state from a non-owner loop and thread.  
  **Files:** `rpi5/main.py`, `rpi5/voice_coordinator.py`

- **High** - Gemini tool calls mutate navigation state across multiple threads and loops without synchronization. The Gemini background thread, main orchestrator, and `NavigationEngine`'s own loop all touch navigation state such as `state`, `_running`, and waypoint progress.  
  **Files:** `rpi5/main.py`, `rpi5/layer3_guide/navigation_engine.py`

- **Medium** - Heartbeat logic in the shared client is effectively broken. Continuous pinging is disabled, the one-time ping does not arm the pending state correctly, and pong correlation depends on fields that are not consistently set. The configured application-level heartbeat timeout is therefore not actually trustworthy.  
  **Files:** `shared/api/base_client.py`

- **Medium** - Laptop Layer 1 detection cache is updated on the client async thread and read on the command path without synchronization. Readers can observe mismatched detections and timestamps, and stale cache survives disconnect long enough to influence spoken answers.  
  **Files:** `rpi5/fastapi_client.py`, `rpi5/main.py`

- **Medium** - `PhoneGPSReceiver.stop()` force-stops its event loop while the server coroutine is still blocked in `run_until_complete()`. Cleanup can abort before the HTTP server stack reaches normal shutdown.  
  **Files:** `rpi5/hardware/phone_gps.py`

- **Low** - The legacy dashboard client buffers messages while disconnected but has no flush path after reconnect, so status, metrics, and detections generated during outages can remain stranded permanently.  
  **Files:** `rpi5/websocket_client.py`

---

## 6. Modes, Buttons, Emergency Paths, and Startup Behavior

- **High** - The `all` startup path claims it starts Guardian, Learner, Thinker, and Memory, but `CortexSystem` hard-disables Layer 0 and Layer 1 unconditionally and later reports them as active in metrics. Startup behavior and runtime telemetry contradict each other.  
  **Files:** `rpi5/__main__.py`, `rpi5/main.py`

- **High** - CLI flags for offline and no-haptic startup are advertised but not enforced. The command path prints the requested mode but still initializes cloud-backed memory and Gemini behavior as normal.  
  **Files:** `rpi5/__main__.py`, `rpi5/main.py`

- **High** - Several RPi CLI subcommands rely on top-level module imports rather than package-qualified imports. They therefore depend on implicit working-directory or `PYTHONPATH` hacks and can fail under the documented `python -m rpi5` invocation style.  
  **Files:** `rpi5/__main__.py`, `rpi5/cli/commands.py`

- **High** - The checked-in deployment artifacts still target an older Flask and Gunicorn dashboard stack rather than the current live dashboard path. Script-based or systemd-based deployment can therefore launch the wrong service or fail immediately.  
  **Files:** `cortex-dashboard.service`, `install_flask_dashboard.sh`

- **Medium** - Early startup reads `rpi5/config/config.yaml` through a current-working-directory-relative path before normal config loading. Launching the process from outside the repo root changes thread settings and layer-import flags through silent fallback behavior.  
  **Files:** `rpi5/main.py`

- **Medium** - Operational mode has no single source of truth. Startup hard-sets one mode, dashboard metrics collapse mode differently, and heartbeat derives mode from whether VAD is listening. Remote observers can therefore see contradictory mode reports from one process.  
  **Files:** `rpi5/main.py`

- **High** - `DEV` mode is described as manual-trigger-only, but the short-press button path starts the same persistent listening mode used by production. One short press can leave the system continuously listening while heartbeat state later claims `PRODUCTION` simply because listening is active.  
  **Files:** `rpi5/main.py`, `rpi5/voice_coordinator.py`

- **High** - `help` and `emergency` are treated as critical only for the playback-drop gate, but the local Gemini-offline fallback does not implement concrete local handling for them. In degraded or reconnecting states these terms can fall through to a generic reconnect message rather than deterministic assist behavior.  
  **Files:** `rpi5/main.py`, `rpi5/voice_coordinator.py`

- **Medium** - The dashboard production toggle is under-synchronized with device state on reconnect or late connect. The UI starts in one assumed mode, the RPi boots in another, and no authoritative state push guarantees convergence until a later explicit mode change occurs.  
  **Files:** `laptop/gui/cortex_ui.py`, `laptop/cli/start_dashboard.py`, `rpi5/main.py`, `rpi5/fastapi_client.py`

- **Medium** - The `guide_indoor` command path can return `success: true` even from its exception path. Upstream callers can believe indoor mode is active when activation actually failed.  
  **Files:** `rpi5/main.py`

---

## 7. Tests, Documentation, and Operational Guidance

- **High** - A representative `pytest` run aborts during collection because multiple tests still depend on removed import paths, missing APIs, or undefined symbols. The checked-in suite is not runnable enough to act as a regression gate.  
  **Files:** `tests/test_router_priority_fix.py`, `tests/test_memory_storage.py`, `tests/test_dual_yolo.py`

- **High** - Router tests no longer match current router semantics even aside from stale import paths. Several assertions validate pre-refactor routing behavior that the current keyword tables no longer implement.  
  **Files:** `tests/test_router_fix.py`, `tests/test_router_v2.py`, `rpi5/layer3_guide/router.py`

- **High** - YOLO-related tests and test documentation still target retired model names and a removed dual-handler setup. The repo now ships 26-series weights and a different production shape, so these tests and instructions do not describe a valid validation path.  
  **Files:** `tests/conftest.py`, `tests/test_yolo_cpu.py`, `tests/test_gui_integration.py`, `tests/test_dual_yolo.py`, `tests/README.md`, `models/`

- **High** - Repo guidance still points operators at broken or misleading startup paths and flags. Examples include dead laptop server paths, a `--debug` flow that the direct script path does not actually parse, and stale coverage targets.  
  **Files:** `AGENTS.md`, `README.md`, `docs/COMMAND_REFERENCE.md`, `rpi5/main.py`, `laptop/server/fastapi_server.py`, `tests/README.md`

- **High** - Top-level docs still describe a legacy codebase layout and direct readers toward removed or stale entrypoints. Because these are active index and architecture docs rather than archived notes, they actively misroute contributors and operators.  
  **Files:** `docs/README.md`, `docs/DEVELOPMENT_WORKFLOW.md`, `docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md`

- **High** - The highest-risk runtime surfaces remain weakly covered by tests. `CortexSystem` startup and teardown, navigation-engine wiring, FastAPI WebSocket auth/rate-limiting behavior, and the live Gemini path are largely untested or only exercised through manual scripts requiring real credentials and sleeps.  
  **Files:** `rpi5/main.py`, `laptop/server/fastapi_server.py`, `tests/test_phase0_voice_bridge.py`, `tests/test_hybrid_memory_manager.py`, `tests/test_video_receiver.py`, `tests/test_gemini_live_api.py`, `tests/test_cascading_fallback.py`

- **Medium** - User-facing guidance still describes Layer 3 as navigation plus spatial audio even though the main runtime explicitly treats spatial audio as scrapped and starts the navigator with spatial audio disabled.  
  **Files:** `docs/COMMAND_REFERENCE.md`, `docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md`, `rpi5/main.py`

- **Medium** - The laptop CLI still advertises distinct `server` and `server --gui` modes even though both end in the same Qt-backed dashboard launch path. Operational documentation therefore encodes a mode split that does not exist.  
  **Files:** `laptop/__main__.py`, `laptop/cli/start_dashboard.py`

---

## 8. Local Static Diagnostics Collected During This Audit

- Static diagnostics reported no immediate editor errors in these recently changed navigation-related files during this audit pass:  
  `rpi5/layer3_guide/navigation_engine.py`  
  `rpi5/layer2_thinker/gemini_live_handler.py`  
  `rpi5/layer2_thinker/lta_datamall.py`  
  `rpi5/layer3_guide/gmaps_directions.py`  
  `rpi5/layer3_guide/gmaps_places.py`

- `rpi5/main.py` still reports environment-sensitive unresolved imports for hardware-specific packages such as `hailo_platform`, `picamera2`, and `libcamera`, plus invalid `Optional[...]` type-expression warnings in the current editor environment. These diagnostics may be partly environment-specific, but they were present during the audit.  
  **File:** `rpi5/main.py`

---

## 9. Audit Coverage

This report consolidates a 15-subagent read-only sweep across these areas:

1. Whole-codebase cross-system audit
2. Shared protocol and laptop-server audit
3. Memory and persistence audit
4. Hardware interaction audit
5. Scene, depth, and safety monitor audit
6. Layer 0 and Layer 1 detection stack audit
7. Startup, config, CLI, and deployment audit
8. Tests, docs, and guidance audit
9. Laptop GUI and dashboard interaction audit
10. Connectivity and reconnect audit
11. Async, threading, and event-loop audit
12. Mode, button, and emergency-path audit
13. Earlier navigation/maps/transit sweep
14. Earlier indoor-navigation duplicate-text / `1007` / Gemini-live sweep
15. Earlier orchestration and cross-module interaction sweep

Where multiple subagents found the same root failure, duplicate findings were merged into one problem statement above.