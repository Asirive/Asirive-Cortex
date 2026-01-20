# Fix Circular Import and Connection Error

The user is experiencing a circular import error in Layer 4 and a connection error to the laptop dashboard.

## User Review Required

> [!IMPORTANT]
> I am ensuring the laptop server host is set to `192.168.0.171` in `rpi5/config/config.yaml` as requested.
> This assumes 192.168.0.171 is the correct IP address for the laptop dashboard.

## Proposed Changes

### rpi5.layer4_memory
#### [MODIFY] [memory_manager.py](file:///c:/Users/Haziq/Documents/ProjectCortex/rpi5/layer4_memory/memory_manager.py)
- Clear content to remove self-referential import.
- Add docstring indicating deprecation.
- This resolves: `ImportError: cannot import name 'MemoryManager' from partially initialized module 'rpi5.layer4_memory.memory_manager'`

### rpi5.cli
#### [MODIFY] [__main__.py](file:///c:/Users/Haziq/Documents/ProjectCortex/rpi5/__main__.py)
- Change default `laptop` argument from `192.168.0.92` to `192.168.0.171`.
- This ensures `python -m rpi5 all` uses the correct IP without conflicting with `config.yaml`.

#### [MODIFY] [commands.py](file:///c:/Users/Haziq/Documents/ProjectCortex/rpi5/cli/commands.py)
- Change default `laptop_host` argument from `192.168.0.92` to `192.168.0.171`.

### Scripts
#### [MODIFY] [sync.bat](file:///c:/Users/Haziq/Documents/ProjectCortex/sync.bat)
- Revert default RPI_HOST to `192.168.0.92`.

### laptop.server
#### [MODIFY] [websocket_server.py](file:///c:/Users/Haziq/Documents/ProjectCortex/laptop/server/websocket_server.py)
- Remove `path` argument from `handle_client` method signature.

# Production Mode & UI Redesign
## User Review Required
> [!IMPORTANT]
> The UI will be completely redesigned with a "Glassmorphic" dark theme.
> "Production Mode" will be implemented as a global state that enforces:
> - VAD (Voice Activity Detection) ALWAYS ON
> - Bluetooth Audio Output enforced (system level or via audio manager)
> - All Layers active and synchronized

## Proposed Changes

### Laptop Dashboard (UI Redesign)
#### [MODIFY] [cortex_ui.py](file:///c:/Users/Haziq/Documents/ProjectCortex/laptop/gui/cortex_ui.py)
- **Visuals**:
    - Implement `GlassMorphism` style with semi-transparent cards (`rgba(30, 30, 40, 0.8)`).
    - Use a "Cyberpunk/Sci-Fi" color palette (Deep Navy `#0a0e17` bg, Neon Cyan `#00f2ea` & Purple `#7000ff` accents).
    - Custom Title Bar and framed window.
- **Components**:
    - **Header**: "Production Mode" Toggle Switch (Big, glowing when active).
    - **Video Feed**: Central widget with "High-Tech" distinct bounding boxes (corner brackets only).
    - **Metrics**: 
        - Sparkline graphs for CPU/RAM.
        - **Uptime Monitors**: Layer Uptime, Camera Uptime, Sensor Status.
    - **Logs**: Distinct panels for System Logs vs Detection Logs.
- **Functionality**:
    - **Preserve Existing Features**: All current tabs/controls will be retained/refactored into the new layout, not deleted.
    - Send `SET_MODE` command via WebSocket.
    - Visualize "VAD State" (Voice Activity).

### RPi5 System (Production Logic)
#### [MODIFY] [main.py](file:///c:/Users/Haziq/Documents/ProjectCortex/rpi5/main.py)
- Add `set_mode` capability to `CortexSystem`.
- Implement `enable_production_mode()`:
    - **Enforce Silero VAD**: Ensure `VadHandler` is active and listening.
    - **Context Routing**: Use `IntentRouter` with current context understanding (Layer Priority) to pick layers dynamically.
    - **System Sync**: Check/Connect Bluetooth Audio.
    - **Uptime Tracking**: Start tracking start times for all components.
- Implement `disable_production_mode()`:
    - Revert to manual/dev control.

#### [MODIFY] [websocket_client.py](file:///c:/Users/Haziq/Documents/ProjectCortex/rpi5/websocket_client.py) / [fastapi_client.py](file:///c:/Users/Haziq/Documents/ProjectCortex/rpi5/fastapi_client.py)
- Ensure they can receive and route the `SET_MODE` command to the main system.

### Verification Plan
- **Manual**: Toggle "Production Mode" on Laptop -> Verify RPi5 logs show "Switching to PRODUCTION MODE".
- **Audio**: Verify audio output routes to Bluetooth (user verification required for hardware).
- **UI**: Visual inspection of the new "wow" factor design.
#### [MODIFY] [requirements.txt](file:///c:/Users/Haziq/Documents/ProjectCortex/requirements.txt)
- Add `paramiko>=3.0.0` to support password-based SSH/SCP on Windows.

### Scripts (Refinement)
#### [MODIFY] [sync_rpi5.py](file:///c:/Users/Haziq/Documents/ProjectCortex/sync_rpi5.py)
- Implement `paramiko` based file transfer and command execution.
- Use `paramiko` if available to bypass `scp` password prompt using the hardcoded password.

### rpi5.config
#### [MODIFY] [config.yaml](file:///c:/Users/Haziq/Documents/ProjectCortex/rpi5/config/config.yaml)
- Verify `laptop_server.host` is set to `192.168.0.171`.
- This resolves: `[Errno 111] Connect call failed` (by ensuring the correct target IP).

## Verification Plan


## RPi5 Updates
### Command Handling
#### [MODIFY] [main.py](file:///c:/Users/Haziq/Documents/ProjectCortex/rpi5/main.py)
- **Text Queries**: Update `handle_dashboard_command` to support `action="TEXT_QUERY"`.
- **Routing**: Pass the text query directly to `handle_voice_command` (reusing existing logic).
- **Layer Control**: Support `action="RESTART_LAYER"`.
    - If `target_layer` provided (e.g. "layer1"), re-initialize just that layer.
    - Else, full restart.
- **Video Stream**:
    - Handle `START/STOP_VIDEO_STREAMING` commands.
    - **Camera Tuning**: Update `_start_picamera` to enable Auto-Focus (`AfMode=2`) for Module 3 Wide.
    - **Bounding Boxes**: Ensure Layer 0 and Layer 1 detections are correctly tagged for UI filtering.
- **Layer 1 Mode**: Support `action="SET_LAYER_MODE"` (e.g., `PROMPT_FREE` vs `TEXT_PROMPTS`).

## Protocol Fixes
- **Status/Metrics**:
    - Call `ws_client.send_metrics()` in `_main_loop` (FPS, CPU, RAM).
    - **Uptimes**: Calculate and send `layer_uptime` (since initialization) and `sensor_uptime` (camera/mic).
    - Send initial `STATUS` message on connection.

## Protocol Fixes
### Laptop Server
#### [MODIFY] [websocket_server.py](file:///c:/Users/Haziq/Documents/ProjectCortex/laptop/server/websocket_server.py)
- **Heartbeat**: Intercept `MessageType.PING` and automatically respond with `MessageType.PONG`.
- **Latency**: Include original timestamp in PONG to allow RPi5 to calculate round-trip time.

## GUI Enhancements
### Laptop Dashboard
#### [MODIFY] [cortex_ui.py](file:///c:/Users/Haziq/Documents/ProjectCortex/laptop/gui/cortex_ui.py)
- **Top Navigation Bar**: Add a custom top bar for switching "window options" (Views).
- **View Architecture**: Use `QStackedWidget` to switch between:
    - **Overview**: Video, Sparklines, Detection Stream (Existing).
    - **Testing**: Manual query input, Test buttons (New).
    - **Logs**: Expanded System/Connection logs.
- **Controls & Toggles**:
    - **Video Stream**: Toggle Switch (Send `START/STOP` cmds).
    - **Layer Mode**: Dropdown/Toggle for `PROMPT_FREE` vs `TEXT_PROMPTS`.
    - **Visualization**: Checkboxes for "Show Layer 0 Box", "Show Layer 1 Box".
- **Refinements**:
    - **Layer Control**: Ensure "RESTART" buttons are functional/wired to commands.
    - **Detection Stream**: Ensure it auto-scrolls and uses color-coding.

### Manual Verification
1.  **Run the system**: The user should run `python -m rpi5 all` again.
2.  **Check Logs**:
    - Verify `Layer 4 (Memory) imported successfully`.
    - Verify `Connected to laptop dashboard (FastAPI)`.
    - Verify no `Connection error` loop.
