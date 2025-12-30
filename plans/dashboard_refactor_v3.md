# Cortex Dashboard v3 Final Implementation Plan

## Architectural Split
To fix the `RuntimeError` and "Invisible Video" issues, I will implement a **Producer-Consumer** architecture using a Singleton Hardware Manager.

### 1. The Core: `CortexHardwareManager` (Singleton)
- **Responsibility:** Manages all heavy AI models and physical hardware.
- **Initialization:** Triggered once at the module level.
- **Inference Loop:** Runs in a dedicated background thread.
- **State Object:** A thread-safe dictionary containing:
    - `last_frame`: The latest annotated frame as a Base64 string.
    - `layer_status`: Real-time health of Reflex, Thinker, Guide, and Memory.
    - `detections`: Current merged detection list.
    - `boot_logs`: A deque of initialization events (e.g., "Connecting to Camera 0... [OK]").
- **Constraint:** Real hardware ONLY (no simulation mode).

### 2. The Interface: `NiceGUI Dashboard` (Per-Client)
- **Responsibility:** Rendering the "Neural Dashboard" for each web client.
- **Visuals:**
    - **Background:** `bg-gradient-to-br from-slate-950 via-slate-900 to-black`.
    - **Glassmorphism:** Cards with `bg-white/5 backdrop-blur-md border border-white/10`.
    - **Neural Console:** A new scrollable terminal-style widget below the video feed for detailed boot sequence logs.
- **Sync Logic:** A per-client `ui.timer(0.05)` (30 FPS) that polls the `HardwareManager.state` and updates local UI components.

## Implementation Steps
1.  **Refactor `src/cortex_dashboard.py`**:
    - Integrate `CortexHardwareManager` class.
    - Update `NeuralCard` with modern CSS effects.
    - Implement `NeuralConsole` for real-time boot logs.
    - Replace the buggy `feed_loop` with a global state polling mechanism.
2.  **Boot Sequence Details**:
    - Show specific progress: `[REFLEX] Loading YOLOv11x...`, `[REFLEX] CUDA Warmup...`, `[MEMORY] SQLite Checksum...`.

## Verification
- Access via `http://localhost:8080` or remote IP.
- Confirm video feed visibility.
- Confirm module status updates in real-time.

**I am ready to apply these changes to `src/cortex_dashboard.py`. Please provide your orders.**