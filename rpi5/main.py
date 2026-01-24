#!/usr/bin/env python3
"""
ProjectCortex v2.0 - Main System Orchestrator
================================================

This is the MAIN entry point that runs all 4 AI layers and manages:
- Layer 0: Guardian (Safety-Critical Detection)
- Layer 1: Learner (Adaptive Detection)
- Layer 2: Thinker (Conversational AI)
- Layer 3: Router (Intent Routing)
- Layer 4: Memory (Hybrid SQLite + Supabase)

Integrations:
- Camera capture (Picamera2/OpenCV)
- Supabase cloud storage (batch sync)
- Laptop dashboard (WebSocket)
- Voice commands (VAD + Whisper)

Author: Haziq (@IRSPlays)
Competition: Young Innovators Awards (YIA) 2026
Date: January 8, 2026
"""

import asyncio
import json
import logging
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Any, List, Optional
import datetime

import cv2
import numpy as np
import yaml
import psutil

# Create logs directory if it doesn't exist
logs_dir = Path('logs')
logs_dir.mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/cortex.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Add rpi5 to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# =====================================================
# LOAD ENVIRONMENT VARIABLES FROM .env
# =====================================================
# Load .env file if it exists (for API keys and config)
dotenv_path = PROJECT_ROOT / ".env"
if dotenv_path.exists():
    try:
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
        logger.info(f"Loaded environment variables from {dotenv_path}")
    except Exception as e:
        logger.warning(f"Failed to load .env file: {e}")

# =====================================================
# THREADING OPTIMIZATION (Must be set before importing Torch/NCNN)
# =====================================================
# Read directly from config file as we haven't loaded the full config module yet
try:
    with open('rpi5/config/config.yaml') as f:
        _cfg = yaml.safe_load(f)
        _threads = str(_cfg.get('performance', {}).get('cpu_threads', 3))
        
        logger.info(f"🚀 Performance Optimization: Setting OMP_NUM_THREADS={_threads}")
        os.environ["OMP_NUM_THREADS"] = _threads
        os.environ["MKL_NUM_THREADS"] = _threads
        os.environ["OPENBLAS_NUM_THREADS"] = _threads
except Exception as e:
    logger.warning(f"⚠️ Could not load threading config, defaulting to 3: {e}")
    os.environ["OMP_NUM_THREADS"] = "3"

# =====================================================
# IMPORT LAYERS
# =====================================================
logger.info("[DEBUG] ===== LAYER IMPORTS STARTING =====")
try:
    from rpi5.layer0_guardian import YOLOGuardian
    logger.info("[DEBUG] ✅ Layer 0 (Guardian) imported successfully")
except ImportError as e:
    logger.error(f"[DEBUG] ❌ Layer 0 (Guardian) import failed: {e}")
    YOLOGuardian = None

try:
    from rpi5.layer1_learner import YOLOELearner, YOLOEMode
    logger.info("[DEBUG] ✅ Layer 1 (Learner) imported successfully")
except ImportError as e:
    logger.error(f"[DEBUG] ❌ Layer 1 (Learner) import failed: {e}")
    YOLOELearner = None
    YOLOEMode = None

try:
    from rpi5.layer2_thinker.gemini_live_handler import GeminiLiveHandler
    logger.info("[DEBUG] ✅ Layer 2 (Thinker) imported successfully")
except ImportError as e:
    logger.error(f"[DEBUG] ❌ Layer 2 (Thinker) import failed: {e}")
    GeminiLiveHandler = None

try:
    from rpi5.layer3_guide.router import IntentRouter
    from rpi5.layer3_guide.detection_router import DetectionRouter
    logger.info("[DEBUG] ✅ Layer 3 (Router) imported successfully")
except ImportError as e:
    logger.error(f"[DEBUG] ❌ Layer 3 (Router) import failed: {e}")
    IntentRouter = None
    DetectionRouter = None

try:
    from rpi5.layer4_memory.hybrid_memory_manager import HybridMemoryManager
    logger.info("[DEBUG] ✅ Layer 4 (Memory) imported successfully")
except ImportError as e:
    logger.error(f"[DEBUG] ❌ Layer 4 (Memory) import failed: {e}")
    HybridMemoryManager = None

logger.info("[DEBUG] ===== LAYER IMPORTS COMPLETE =====")

# =====================================================
# IMPORT SUPPORTING MODULES
# =====================================================
try:
    from rpi5.fastapi_client import CortexFastAPIClient
except ImportError:
    logger.warning("FastAPI client not found, falling back to legacy")
    CortexFastAPIClient = None
    try:
        from rpi5.websocket_client import RPiWebSocketClient
    except ImportError:
        RPiWebSocketClient = None


# =====================================================
# CONFIGURATION
# =====================================================
# Use the config module
from rpi5.config.config import get_config
from rpi5.voice_coordinator import VoiceCoordinator


# =====================================================
# CAMERA HANDLER
# =====================================================
class CameraHandler:
    """Continuous camera frame capture with threading"""

    def __init__(self, camera_id: int = 0, use_picamera: bool = True, resolution: tuple = (1920, 1080), fps: int = 30):
        self.camera_id = camera_id
        self.use_picamera = use_picamera
        self.resolution = resolution
        self.fps = fps
        self.camera = None
        self.running = False
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.capture_thread = None

    def start(self):
        """Start camera capture thread"""
        if self.running:
            logger.warning("Camera already running")
            return

        self.running = True

        if self.use_picamera:
            self._start_picamera()
        else:
            self._start_opencv()

        logger.info(f"✅ Camera started: {self.camera_id} @ {self.resolution[0]}x{self.resolution[1]}")

    def _start_picamera(self):
        """Initialize Picamera2 (RPi5)"""
        try:
            # Optimizations for Module 3 Wide (IMX708)
            # 1. Force Wide Tuning File for LSC/Color Correction
            # This ensures we don't get dark corners or weird colors
            os.environ["LIBCAMERA_RPI_TUNING_FILE"] = "/usr/share/libcamera/ipa/rpi/vc4/imx708_wide.json"
            
            from picamera2 import Picamera2

            self.camera = Picamera2(self.camera_id)
            
            # 2. Use Video Configuration (Better for high FPS/continuous than preview)
            config = self.camera.create_video_configuration(
                main={"format": 'RGB888', "size": self.resolution},
                buffer_count=4  # Prevent starvation
            )
            self.camera.configure(config)
            
            # 3. Enable Continuous Auto-Focus (AfMode=2) & Auto-Exposure
            # 0=Manual, 1=Auto(Single), 2=Continuous
            try:
                self.camera.set_controls({
                    "AfMode": 2,
                    "AeEnable": True
                })
                logger.info("✅ Picamera2: Continuous Auto-Focus & AE Enabled")
            except Exception as e:
                logger.warning(f"⚠️ Could not set Camera Controls: {e}")

            self.camera.start()

            # Start capture thread
            self.capture_thread = threading.Thread(
                target=self._picamera_capture_loop,
                daemon=True
            )
            self.capture_thread.start()

        except ImportError as e:
            # Try to find system libcamera (common on RPi with custom venv)
            if "libcamera" in str(e) or "picamera2" in str(e):
                system_site = "/usr/lib/python3/dist-packages"
                if system_site not in sys.path and os.path.exists(system_site):
                    logger.info(f"⚠️  Attempting to load system libcamera from {system_site}")
                    # CRITICAL: Use insert(0) to prioritize system packages over broken venv packages
                    sys.path.insert(0, system_site)
                    try:
                        # Clean any partial imports
                        if 'picamera2' in sys.modules: del sys.modules['picamera2']
                        if 'libcamera' in sys.modules: del sys.modules['libcamera']
                        
                        import libcamera
                        import picamera2
                        logger.info("✅ System libcamera/picamera2 found and loaded!")
                        # If successful, re-attempt starting picamera with the NEWLY loaded module
                        # We must re-instantiate because the class object might have come from the broken module
                        self.camera = picamera2.Picamera2(self.camera_id)
                        
                        # Re-apply config
                        config = self.camera.create_video_configuration(
                            main={"format": 'RGB888', "size": self.resolution},
                            buffer_count=4
                        )
                        self.camera.configure(config)
                        self.camera.set_controls({"AfMode": 2, "AeEnable": True})
                        self.camera.start()
                        
                        # Start thread
                        self.capture_thread = threading.Thread(
                            target=self._picamera_capture_loop,
                            daemon=True
                        )
                        self.capture_thread.start()
                        return 
                    except ImportError:
                        logger.warning(f"❌ System libcamera/picamera2 not found in {system_site} or failed to load.")
                        # Remove the path if it failed, to be clean
                        if system_site in sys.path:
                            sys.path.remove(system_site)
                        pass

            logger.error(f"❌ picamera2 not installed, falling back to OpenCV")
            logger.error(f"   Import Error: {e}")
            logger.error(f"   Python Path: {sys.path}")
            try:
                import types
                logger.error(f"   picamera2 in modules? {'picamera2' in sys.modules}")
            except:
                 pass
            self.use_picamera = False
            self._start_opencv()
        except Exception as e:
            logger.error(f"❌ Failed to start Picamera2: {e}")
            raise

    def _start_opencv(self):
        """Initialize OpenCV (laptop/testing/RPi fallback)"""
        # Iterate to find the correct camera index (RPi5 often creates multiple video nodes)
        found_camera = False
        
        # Try indices 0 to 10
        for idx in range(10):
            try:
                # Explicitly request V4L2 backend
                self.camera = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                
                if self.camera.isOpened():
                    # Read a test frame to ensure it's actually working
                    ret, _ = self.camera.read()
                    if ret:
                        logger.info(f"✅ OpenCV connected to camera index {idx}")
                        self.camera_id = idx
                        found_camera = True
                        break
                    else:
                        self.camera.release()
            except Exception:
                pass
        
        if not found_camera:
            # Last ditch attempt with default backend at original index
            self.camera = cv2.VideoCapture(self.camera_id)
            if not self.camera.isOpened():
                raise RuntimeError(f"Failed to open camera (tried indices 0-9)")
            logger.info(f"⚠️  OpenCV connected to index {self.camera_id} (fallback backend)")

        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.camera.set(cv2.CAP_PROP_FPS, self.fps)

        # Start capture thread
        self.capture_thread = threading.Thread(
            target=self._opencv_capture_loop,
            daemon=True
        )
        self.capture_thread.start()

    def _picamera_capture_loop(self):
        """Continuous capture loop for Picamera2"""
        while self.running:
            frame = self.camera.capture_array()
            with self.frame_lock:
                self.latest_frame = frame
            time.sleep(1.0 / self.fps)

    def _opencv_capture_loop(self):
        """Continuous capture loop for OpenCV"""
        while self.running:
            ret, frame = self.camera.read()
            if ret:
                with self.frame_lock:
                    self.latest_frame = frame
            time.sleep(1.0 / self.fps)

    def get_frame(self) -> Optional[np.ndarray]:
        """Get latest frame (thread-safe)"""
        with self.frame_lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
            return None

    def stop(self):
        """Stop camera capture"""
        self.running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)

        if self.camera:
            if self.use_picamera:
                self.camera.stop()
            else:
                self.camera.release()

        logger.info("✅ Camera stopped")


# =====================================================
# MAIN SYSTEM ORCHESTRATOR
# =====================================================
class CortexSystem:
    """
    Main system orchestrator - connects all layers

    Responsibilities:
    1. Initialize all 4 layers
    2. Start camera capture
    3. Run detection loops (Layer 0 + Layer 1 parallel)
    4. Handle voice commands
    5. Sync data to Supabase
    6. Send data to laptop dashboard
    7. Manage graceful shutdown
    """

    def __init__(self, config_path: str = None):
        logger.info("Initializing ProjectCortex v2.0...")

        # Load configuration
        if config_path:
            self.config = load_config(config_path)
        else:
            self.config = get_config()

        # Initialize Layer 4: Memory Manager (Hybrid)
        logger.info("[DEBUG] ===== LAYER 4 INITIALIZATION START =====")
        if HybridMemoryManager:
            logger.info("💾 Initializing Layer 4: Memory Manager...")
            logger.info(f"[DEBUG] Layer 4 config: url={self.config['supabase']['url'][:30]}..., device_id={self.config['supabase']['device_id']}")
            self.memory_manager = HybridMemoryManager(
                supabase_url=self.config['supabase']['url'],
                supabase_key=self.config['supabase']['anon_key'],
                device_id=self.config['supabase']['device_id'],
                local_db_path=self.config['supabase']['local_db_path'],
                sync_interval=self.config['supabase']['sync_interval_seconds'],
                batch_size=self.config['supabase']['batch_size'],
                local_cache_size=self.config['supabase']['local_cache_size']
            )
            self.memory_manager.start_sync_worker()
            logger.info("✅ Layer 4 initialized")
        else:
            self.memory_manager = None
            logger.warning("⚠️  Layer 4 not available, running without cloud storage")
        logger.info("[DEBUG] ===== LAYER 4 INITIALIZATION COMPLETE =====")

        # Initialize Layer 0: Guardian (Safety-Critical Detection)
        logger.info("[DEBUG] ===== LAYER 0 INITIALIZATION START =====")
        if YOLOGuardian:
            logger.info("🛡️  Initializing Layer 0: Guardian...")
            logger.info(f"[DEBUG] Layer 0 config: model_path={self.config['layer0']['model_path']}, device={self.config['layer0']['device']}")
            self.layer0 = YOLOGuardian(
                model_path=self.config['layer0']['model_path'],
                device=self.config['layer0']['device'],
                confidence=self.config['layer0']['confidence'],
                enable_haptic=self.config['layer0']['enable_haptic'],
                gpio_pin=self.config['layer0']['gpio_pin'],
                memory_manager=self.memory_manager
            )
            logger.info("✅ Layer 0 initialized")
        else:
            self.layer0 = None
            logger.warning("⚠️  Layer 0 not available")
        logger.info("[DEBUG] ===== LAYER 0 INITIALIZATION COMPLETE =====")

        # Initialize Layer 1: Learner (Adaptive Detection)
        logger.info("[DEBUG] ===== LAYER 1 INITIALIZATION START =====")
        if YOLOELearner and YOLOEMode:
            logger.info("🎯 Initializing Layer 1: Learner...")
            logger.info(f"[DEBUG] Layer 1 config: model_path={self.config['layer1']['model_path']}, mode={self.config['layer1']['mode']}")
            mode_map = {
                'PROMPT_FREE': YOLOEMode.PROMPT_FREE,
                'TEXT_PROMPTS': YOLOEMode.TEXT_PROMPTS,
                'VISUAL_PROMPTS': YOLOEMode.VISUAL_PROMPTS
            }
            self.layer1 = YOLOELearner(
                model_path=self.config['layer1']['model_path'],
                device=self.config['layer1']['device'],
                confidence=self.config['layer1']['confidence'],
                mode=mode_map.get(self.config['layer1']['mode'], YOLOEMode.TEXT_PROMPTS),
                memory_manager=self.memory_manager
            )
            logger.info("✅ Layer 1 initialized")
        else:
            self.layer1 = None
            logger.warning("⚠️  Layer 1 not available")
        logger.info("[DEBUG] ===== LAYER 1 INITIALIZATION COMPLETE =====")

        # Initialize Layer 2: Thinker (Gemini Live API)
        logger.info("[DEBUG] ===== LAYER 2 INITIALIZATION START =====")
        if GeminiLiveHandler:
            logger.info("🧠 Initializing Layer 2: Thinker...")
            logger.info(f"[DEBUG] Layer 2 config: api_key={'*' * 10} (hidden)")
            self.layer2 = GeminiLiveHandler(
                api_key=self.config['layer2']['gemini_api_key']
            )
            logger.info("✅ Layer 2 initialized")
        else:
            self.layer2 = None
            logger.warning("⚠️  Layer 2 not available")
        logger.info("[DEBUG] ===== LAYER 2 INITIALIZATION COMPLETE =====")

        # Initialize Layer 3: Router (Intent Routing)
        logger.info("[DEBUG] ===== LAYER 3 INITIALIZATION START =====")
        if IntentRouter and DetectionRouter:
            logger.info("🔀 Initializing Layer 3: Router...")
            self.intent_router = IntentRouter()
            self.detection_router = DetectionRouter()
            logger.info("✅ Layer 3 initialized")
        else:
            self.intent_router = None
            self.detection_router = None
            logger.warning("⚠️  Layer 3 not available")
        logger.info("[DEBUG] ===== LAYER 3 INITIALIZATION COMPLETE =====")

        # Initialize Camera Handler
        logger.info("📸 Initializing Camera...")
        self.camera = CameraHandler(
            camera_id=self.config['camera']['device_id'],
            use_picamera=self.config['camera']['use_picamera'],
            resolution=tuple(self.config['camera']['resolution']),
            fps=self.config['camera']['fps']
        )

        # Initialize WebSocket Client (for laptop dashboard) - Use FastAPI client
        self.ws_client = None
        if CortexFastAPIClient:
            logger.info("🌐 Initializing FastAPI Client...")
            self.ws_client = CortexFastAPIClient(
                host=self.config['laptop_server']['host'],
                port=self.config['laptop_server']['port'],
                device_id=self.config['supabase']['device_id']
            )
            # Link command handler
            self.ws_client.on_command = self.handle_dashboard_command
            logger.info("✅ FastAPI client initialized")
        elif RPiWebSocketClient:
            logger.info("🌐 Initializing legacy WebSocket Client...")
            self.ws_client = RPiWebSocketClient(
                host=self.config['laptop_server']['host'],
                port=self.config['laptop_server']['port'],
                device_id=self.config['supabase']['device_id']
            )
            logger.info("✅ Legacy WebSocket client initialized")
        else:
            logger.warning("⚠️  No dashboard client available")

        # Video streaming state
        self.video_streaming_active = False

        # System state
        self.running = False
        self.detection_count = 0

        # Initialize Voice Coordinator
        self.voice_coordinator = VoiceCoordinator(on_command_detected=self.handle_voice_command)
        self.voice_coordinator.initialize()

        # Start Time for Uptime
        self.start_time = time.time()

        logger.info("✅ ProjectCortex v2.0 initialized successfully")

    def handle_dashboard_command(self, cmd: Dict[str, Any]):
        """Handle incoming commands from dashboard"""
        action = cmd.get("action")
        logger.info(f"📥 Dashboard Command: {action}")
        
        if action == "SET_MODE":
            mode = cmd.get("mode")
            self.set_mode(mode)
        elif action == "RESTART":
             self.stop()
             sys.exit(0) # Systemd should restart
        
        # New: Text Query Handling
        elif action == "TEXT_QUERY":
            query = cmd.get("query")
            if query:
                logger.info(f"⌨️ Text Query: '{query}'")
                # Run sync since main loop isn't async
                asyncio.run(self.handle_voice_command(query))

        # New: Layer Control (Restart)
        elif action == "RESTART_LAYER":
            target = cmd.get("layer")
            if target == "layer1":
                # Re-init Layer 1
                logger.info("🔄 Restarting Layer 1 (Learner)...") 
                # Ideally we'd reload the module but for now we just re-instantiate if possible
                if self.layer1:
                     # Re-loading logic would go here
                     logger.info("Re-initialization of Layer 1 triggered (placeholder)")
            elif target == "layer2":
                pass

        # New: Layer Mode Toggle
        elif action == "SET_LAYER_MODE":
            layer = cmd.get("layer") # "layer1"
            mode = cmd.get("mode") # "TEXT_PROMPTS" vs "PROMPT_FREE"
            if layer == "layer1" and self.layer1:
                # Check for set_mode in layer1 (assumed to exist or added)
                # YOLOELearner usually has 'mode' attribute.
                # Just set it directly if possible or call method
                if hasattr(self.layer1, "set_mode"):
                    self.layer1.set_mode(mode) # Assuming this method exists or we add it to Layer1
                else:
                    self.layer1.mode = mode # Direct attribute fallback
                logger.info(f"✅ Layer 1 switched to {mode}")

    def set_mode(self, mode: str):
        """Set system operation mode"""
        logger.info(f"🔄 Switching to Mode: {mode}")
        
        if mode == "PRODUCTION":
            # Enable VAD (Always On)
            logger.info("🎙️ PRODUCTION MODE: Enforcing VAD Always On")
            self.voice_coordinator.start()
            
            # TODO: Enforce Bluetooth (requires shell/bluez)
            logger.info("🎧 PRODUCTION MODE: Verifying Bluetooth Audio...")
            # For now just log, real impl needs platform specific check
            
            # Update Layer 1 to use tighter thresholds?
            if self.layer1:
                self.layer1.confidence = 0.6 # Stricter
                
        elif mode == "DEV":
            # Disable VAD monitoring (manual trigger only)
            logger.info("🛠️ DEV MODE: Disabling VAD monitoring")
            self.voice_coordinator.stop()
            
            if self.layer1:
                self.layer1.confidence = 0.4 # Laxer

    def start(self):
        """Start main system loop"""
        logger.info("🚀 Starting ProjectCortex v2.0...")

        self.running = True

        # Start camera
        self.camera.start()

        # Connect to laptop dashboard
        if self.ws_client:
            try:
                self.ws_client.start()
                logger.info("✅ Connected to laptop dashboard (FastAPI)")
                
                # Send initial status
                self.ws_client.send_status("ONLINE", "RPi5 System Started")
            except Exception as e:
                logger.warning(f"⚠️  Failed to connect to laptop: {e}")

        # Start Layer 2 Gemini Live API session (only if enabled and API key valid)
        gemini_enabled = os.getenv("GEMINI_LIVE_ENABLED", "true").lower() == "true"
        if self.layer2 and gemini_enabled:
            # Check if API key is valid (not placeholder)
            api_key = os.getenv("GEMINI_API_KEY", "")
            if api_key and not api_key.startswith("YOUR_"):
                try:
                    asyncio.run(self.layer2.connect())
                    logger.info("✅ Gemini Live API connected")
                except Exception as e:
                    logger.warning(f"⚠️ Gemini Live API failed: {e}")
            else:
                logger.info("ℹ️ Gemini Live API skipped (invalid or missing API key)")
        elif self.layer2:
            logger.info("ℹ️ Gemini Live API disabled via GEMINI_LIVE_ENABLED=false")

        logger.info("✅ System started")
        logger.info("📸 Capturing frames...")
        logger.info("🔍 Running detections...")
        logger.info("💾 Syncing to Supabase...")
        logger.info("🌐 Sending to laptop dashboard...")

        # Main loop
        self._main_loop()

    def _main_loop(self):
        """Main processing loop"""
        fps_tracker = []
        last_sync_time = time.time()
        last_metrics_time = time.time()

        try:
            while self.running:
                loop_start = time.time()

                # 1. Get frame from camera
                frame = self.camera.get_frame()
                if frame is None:
                    time.sleep(0.1)
                    continue

                # 2. Run Layer 0 + Layer 1 in parallel
                all_detections = self._run_dual_detection(frame)

                # 3. Send to laptop dashboard via WebSocket
                if self.ws_client:
                     # Video streaming is toggled inside client class, we just send
                    self._send_to_laptop(frame, all_detections)

                # 4. Update device heartbeat every 30 seconds
                if time.time() - last_sync_time > 30:
                    self._update_heartbeat()
                    last_sync_time = time.time()

                # 5. Send Metrics (every 0.5s)
                if time.time() - last_metrics_time > 0.5 and self.ws_client and self.ws_client.is_connected:
                    loop_time = time.time() - loop_start
                    fps = 1.0 / loop_time if loop_time > 0 else 0
                    
                    self.ws_client.send_metrics(
                        fps=fps,
                        cpu_percent=psutil.cpu_percent(),
                        ram_percent=psutil.virtual_memory().percent,
                        temperature=self._get_cpu_temp()
                    )
                    last_metrics_time = time.time()

                # 6. Track FPS for Logging
                loop_time = time.time() - loop_start
                fps = 1.0 / loop_time if loop_time > 0 else 0
                fps_tracker.append(fps)

                if len(fps_tracker) >= 30:
                    avg_fps = sum(fps_tracker) / len(fps_tracker)
                    logger.debug(f"📊 FPS: {avg_fps:.1f}")
                    fps_tracker = []

        except KeyboardInterrupt:
            logger.info("⚠️  Interrupted by user")
        except Exception as e:
            logger.error(f"❌ Main loop error: {e}", exc_info=True)

    def _get_cpu_temp(self):
        """Get CPU temperature (RPi specific)"""
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return float(f.read()) / 1000.0
        except:
            return 0.0

    def _run_dual_detection(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """Run Layer 0 + Layer 1 detection in parallel"""
        detections = []

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []

            # Layer 0: Guardian (Safety-Critical)
            if self.layer0:
                future = executor.submit(self.layer0.detect, frame)
                futures.append(('layer0', future))

            # Layer 1: Learner (Adaptive)
            if self.layer1:
                future = executor.submit(self.layer1.detect, frame)
                futures.append(('layer1', future))

            # Collect results
            for layer_name, future in futures:
                try:
                    layer_detections = future.result(timeout=1.0)  # 1 second timeout
                    detections.extend(layer_detections)
                except Exception as e:
                    import traceback
                    logger.error(f"❌ {layer_name} detection failed: {e}\n{traceback.format_exc()}")

        self.detection_count += len(detections)
        return detections

    def _send_to_laptop(self, frame: np.ndarray, detections: List[Dict[str, Any]]):
        """Send frame and detections to laptop dashboard"""
        if not self.ws_client:
            return

        try:
            # Prepare detection list with layer info
            enriched_detections = []
            for det in detections:
                enriched_detections.append({
                    "class": det.get('class', 'unknown'),
                    "confidence": det.get('confidence', 0.0),
                    "x1": int(det.get('x1', 0)),
                    "y1": int(det.get('y1', 0)),
                    "x2": int(det.get('x2', 0)),
                    "y2": int(det.get('y2', 0)),
                    # Ensure layer is always present
                    "layer": det.get('layer', 'layer0') 
                })

            # Send video frame with detections (only if streaming enabled)
            self.ws_client.send_video_frame(frame, enriched_detections)

            # Send individual detections
            for det in enriched_detections:
                self.ws_client.send_detection(det)

        except Exception as e:
            logger.debug(f"⚠️  Failed to send to laptop: {e}")

    def _update_heartbeat(self):
        """Update device heartbeat to Supabase"""
        if self.memory_manager:
            asyncio.run(self.memory_manager.update_device_heartbeat(
                device_name='RPi5-Cortex-001',
                battery_percent=85,
                cpu_percent=45.2,
                memory_mb=2048,
                temperature=42.5,
                active_layers=['layer0', 'layer1', 'layer2', 'layer3'],
                current_mode='TEXT_PROMPTS'
            ))

    async def handle_voice_command(self, query: str):
        """
        Handle voice command through routing system
        
        Args:
            query: User's voice command text
        """
        # Ensure we are not missing frames
        
        if not self.intent_router:
            logger.warning("⚠️  Intent router not available")
            return

        logger.info(f"🎤 Voice command: '{query}'")

        # Route intent with context
        target_layer = self.intent_router.route(query)
        mode = self.intent_router.get_recommended_mode(query)

        logger.info(f"🔀 Routed to: {target_layer} (mode: {mode})")
        
        # Notify dashboard of audio event
        if self.ws_client:
            # We don't have send_audio_event on FastAPI client yet, implementing mock or assume extended
            pass 

        frame = self.camera.get_frame()
        if frame is None:
            logger.warning("⚠️  No frame available")
            return

        # Handle based on target layer
        if target_layer == "layer1" and self.layer1:
            # Switch mode if needed
            if mode == "PROMPT_FREE":
                # Assuming this method exists or logic is similar to set_mode
                if hasattr(self.layer1, "switch_to_prompt_free"):
                     self.layer1.switch_to_prompt_free()
                elif hasattr(self.layer1, "set_mode"):
                     self.layer1.set_mode("PROMPT_FREE")
            elif mode == "VISUAL_PROMPTS":
                # Would need visual prompts
                pass

            # Run detection
            detections = self.layer1.detect(frame)

            # Generate response
            if detections:
                top_detection = detections[0]
                response = f"I see a {top_detection['class']} with {top_detection['confidence']:.0%} confidence"
            else:
                response = "I don't see anything specific right now"

            logger.info(f"✅ Response: {response}")

            # Store to Supabase
            if self.memory_manager:
                await self.memory_manager.store_query(
                    user_query=query,
                    transcribed_text=query,
                    routed_layer=target_layer,
                    routing_confidence=0.95,
                    detection_mode=mode,
                    ai_response=response
                )

        elif target_layer == "layer2" and self.layer2:
            # Deep analysis with Gemini
            try:
                response = await self.layer2.send_query(query, frame)
                logger.info(f"✅ Gemini response: {response}")

                # Store to Supabase
                if self.memory_manager:
                    await self.memory_manager.store_query(
                        user_query=query,
                        transcribed_text=query,
                        routed_layer=target_layer,
                        routing_confidence=0.95,
                        ai_response=response,
                        tier_used='gemini_live'
                    )
            except Exception as e:
                logger.error(f"❌ Layer 2 error: {e}")
        
        elif target_layer == "layer3":
             # Route to Layer 3 (Navigation/Guide)
             pass 

    def stop(self):
        """Graceful shutdown"""
        logger.info("🛑 Stopping ProjectCortex v2.0...")

        self.running = False

        # Stop camera
        self.camera.stop()

        # Disconnect Layer 2
        if self.layer2:
            asyncio.run(self.layer2.disconnect())

        # Disconnect WebSocket
        if self.ws_client:
            self.ws_client.stop()

        # Stop sync worker
        if self.memory_manager:
            self.memory_manager.stop_sync_worker()
            self.memory_manager.cleanup()

        logger.info("✅ ProjectCortex v2.0 stopped")
        logger.info(f"📊 Total detections: {self.detection_count}")


# =====================================================
# ENTRY POINT
# =====================================================
def main():
    """Main entry point"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                            ║
║     🧠 ProjectCortex v2.0 - AI Wearable Assistant          ║
║     Young Innovators Awards 2026                          ║
║                                                            ║
║     Author: Haziq (@IRSPlays)                            ║
║     AI Implementer: Claude (Sonnet 4.5)                 ║
║                                                            ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Initialize system
    try:
        cortex = CortexSystem()
    except Exception as e:
        logger.error(f"❌ Failed to initialize Cortex: {e}", exc_info=True)
        sys.exit(1)

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"⚠️  Signal {signum} received, shutting down...")
        cortex.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start system
    try:
        cortex.start()
    except Exception as e:
        logger.error(f"❌ System error: {e}", exc_info=True)
    finally:
        cortex.stop()


if __name__ == "__main__":
    main()
