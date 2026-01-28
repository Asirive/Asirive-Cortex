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
# IMPORT NEW VOICE PIPELINE HANDLERS
# =====================================================
try:
    from rpi5.bluetooth_handler import BluetoothAudioManager
    logger.info("[DEBUG] ✅ BluetoothAudioManager imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ BluetoothAudioManager import failed: {e}")
    BluetoothAudioManager = None

try:
    from rpi5.vision_query_handler import VisionQueryHandler
    logger.info("[DEBUG] ✅ VisionQueryHandler imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ VisionQueryHandler import failed: {e}")
    VisionQueryHandler = None

try:
    from rpi5.tts_router import TTSRouter
    logger.info("[DEBUG] ✅ TTSRouter imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ TTSRouter import failed: {e}")
    TTSRouter = None

try:
    from rpi5.layer3_guide.detection_aggregator import DetectionAggregator
    logger.info("[DEBUG] ✅ DetectionAggregator imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ DetectionAggregator import failed: {e}")
    DetectionAggregator = None


# =====================================================
# ASYNC HELPER FUNCTION
# =====================================================
def run_async_safe(coro):
    """
    Safely run an async coroutine from sync code.
    
    Handles the case where an event loop may or may not be running.
    If a loop is running, schedules the coroutine on it.
    Otherwise, creates a new loop with asyncio.run().
    """
    try:
        # Check if there's already a running event loop
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, safe to use asyncio.run()
        return asyncio.run(coro)
    else:
        # Loop is running, schedule coroutine
        # This returns a concurrent.futures.Future
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            # Wait for result with timeout
            return future.result(timeout=30)
        except Exception as e:
            logger.error(f"Async execution failed: {e}")
            return None


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
        supabase_enabled = self.config['supabase'].get('enabled', True)
        if HybridMemoryManager and supabase_enabled:
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
        elif HybridMemoryManager and not supabase_enabled:
            logger.info("💾 Initializing Layer 4: Memory Manager (local only, Supabase disabled)...")
            self.memory_manager = HybridMemoryManager(
                supabase_url=self.config['supabase']['url'],
                supabase_key=self.config['supabase']['anon_key'],
                device_id=self.config['supabase']['device_id'],
                local_db_path=self.config['supabase']['local_db_path'],
                sync_interval=self.config['supabase']['sync_interval_seconds'],
                batch_size=self.config['supabase']['batch_size'],
                local_cache_size=self.config['supabase']['local_cache_size']
            )
            # Disable Supabase sync but keep local storage
            self.memory_manager.supabase_available = False
            logger.info("✅ Layer 4 initialized (local only)")
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
        layer1_enabled = self.config['layer1'].get('enabled', True)
        if YOLOELearner and YOLOEMode and layer1_enabled:
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
        # Initialize ZMQ Video Streamer
        self.video_streamer = None
        try:
            from rpi5.video_streamer import VideoStreamer
            # Use laptop host from config. Port 5555 is hardcoded for now or add to config?
            # Using 5555 as agreed.
            host = self.config['laptop_server']['host']
            logger.info(f"🎥 Initializing ZMQ Streamer to {host}:5555...")
            self.video_streamer = VideoStreamer(host, 5555)
            logger.info(f"✅ ZMQ Streamer initialized: {self.video_streamer is not None}")
        except Exception as e:
            logger.error(f"❌ Failed to init ZMQ Streamer: {e}")

        # Video streaming state
        self.video_streaming_active = True # Default true for ZMQ
        logger.info(f"[DEBUG] video_streaming_active={self.video_streaming_active}, video_streamer={self.video_streamer is not None}")

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
                # Use safe async runner instead of asyncio.run()
                run_async_safe(self.handle_voice_command(query))

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
            
            # Setup Bluetooth audio (CMF Buds 2 Plus)
            logger.info("🎧 PRODUCTION MODE: Setting up Bluetooth Audio...")
            if BluetoothAudioManager:
                try:
                    bt_manager = BluetoothAudioManager(device_name="CMF Buds")
                    if bt_manager.connect_and_setup():
                        logger.info("✅ Bluetooth audio connected and set as default")
                    else:
                        logger.warning("⚠️ Bluetooth audio setup failed - using default audio")
                except Exception as e:
                    logger.error(f"❌ Bluetooth setup error: {e}")
            else:
                logger.warning("⚠️ BluetoothAudioManager not available")
            
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
                logger.info("Connected to laptop dashboard (FastAPI)")

                # Send initial status
                self.ws_client.send_status("ONLINE", "RPi5 System Started")

                # Fix: Wait for laptop acknowledgment before starting ZMQ video stream
                # This ensures the laptop's VideoReceiver is bound and ready
                logger.info("Waiting for laptop to be ready for video stream...")
                time.sleep(1.0)  # Give laptop time to start ZMQ receiver

                # Start ZMQ video streaming only after WebSocket is established
                if self.video_streaming_active and self.video_streamer:
                    logger.info("Starting ZMQ video stream...")
                    # Video streaming is always-on in main loop via self.video_streamer.send_frame()

            except Exception as e:
                logger.warning(f"Failed to connect to laptop: {e}")

        # Start Layer 2 Gemini Live API session (only if enabled and API key valid)
        gemini_enabled = os.getenv("GEMINI_LIVE_ENABLED", "true").lower() == "true"
        if self.layer2 and gemini_enabled:
            # Check if API key is valid (not placeholder)
            api_key = os.getenv("GEMINI_API_KEY", "")
            if api_key and not api_key.startswith("YOUR_"):
                try:
                    run_async_safe(self.layer2.connect())
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

                # 3. Send to laptop dashboard via ZMQ (Hybrid Architecture)
                if self.video_streamer:
                    self.video_streamer.send_frame(frame)
                    logger.debug(f"[ZMQ] Sent frame to laptop, frame shape: {frame.shape}")
                
                # Still send DETECTIONS via WebSocket (Metadata only)
                if self.ws_client:
                     # We modify _send_to_laptop to OPTIONALLY send frame, or just detections
                    self._send_to_laptop(None, all_detections) # Pass None for frame to skip WS video

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

    def _send_to_laptop(self, frame: Optional[np.ndarray], detections: List[Dict[str, Any]]):
        """Send frame and detections to laptop dashboard"""
        if not self.ws_client:
            return

        try:
            # Prepare detection list with layer info
            enriched_detections = []
            for det in detections:
                # Handle bbox: Layer 0 uses 'bbox' list, normalize to x1,y1,x2,y2
                bbox = det.get('bbox', [0, 0, 0, 0])
                if isinstance(bbox, list) and len(bbox) >= 4:
                    x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                else:
                    x1 = int(det.get('x1', 0))
                    y1 = int(det.get('y1', 0))
                    x2 = int(det.get('x2', 0))
                    y2 = int(det.get('y2', 0))
                
                # Normalize layer name: 'guardian' -> 'layer0', 'learner' -> 'layer1'
                layer = det.get('layer', 'layer0')
                if layer == 'guardian':
                    layer = 'layer0'
                elif layer == 'learner':
                    layer = 'layer1'
                
                enriched_detections.append({
                    "class": det.get('class', 'unknown'),
                    "confidence": det.get('confidence', 0.0),
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "layer": layer
                })

            # Send video frame (Legacy WS) only if frame provided
            if frame is not None:
                self.ws_client.send_video_frame(frame, enriched_detections)

            # Send individual detections (Always)
            # This allows the laptop to receive detections from RPi's local layers (Guardian)
            # even if video comes via ZMQ.
            for det in enriched_detections:
                # CRITICAL FIX: Unpack dict to match send_detection signature
                self.ws_client.send_detection(
                    class_name=det.get('class', 'unknown'),
                    confidence=det.get('confidence', 0.0),
                    bbox=[det.get('x1', 0), det.get('y1', 0), det.get('x2', 0), det.get('y2', 0)],
                    layer=0 if det.get('layer', 'layer0') == 'layer0' else 1,
                    width=640,  # Default frame width
                    height=480  # Default frame height
                )

        except Exception as e:
            logger.debug(f"⚠️  Failed to send to laptop: {e}")

    def _update_heartbeat(self):
        """Update device heartbeat to Supabase"""
        if self.memory_manager:
            run_async_safe(self.memory_manager.update_device_heartbeat(
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
        Handle voice command through routing system with new voice pipeline.
        
        Pipeline:
        1. VAD detects speech -> Whisper transcribes -> query arrives here
        2. IntentRouter determines layer and flags
        3. Execute appropriate handler (VisionQueryHandler, Gemini, etc.)
        4. Aggregate detections if needed
        5. Route to TTS (Gemini or Kokoro based on length)
        
        Args:
            query: User's voice command text
        """
        if not self.intent_router:
            logger.warning("⚠️  Intent router not available")
            return

        logger.info(f"🎤 Voice command: '{query}'")

        # Get routing with detailed flags
        routing = self.intent_router.route_with_flags(query)
        target_layer = routing["layer"]
        
        logger.info(f"🔀 Routed to: {target_layer} | L0={routing['use_layer0']}, "
                   f"L1={routing['use_layer1']}, Gemini={routing['use_gemini']}, "
                   f"Type={routing['query_type']}")
        
        # Notify dashboard of audio event
        if self.ws_client:
            try:
                # Send voice command event
                pass  # TODO: Implement send_audio_event on FastAPI client
            except Exception:
                pass

        frame = self.camera.get_frame()
        if frame is None:
            logger.warning("⚠️  No frame available")
            # Speak error via TTS
            if TTSRouter:
                tts = TTSRouter()
                await tts.speak_async("I couldn't capture an image from the camera.")
            return

        response = ""

        # =================================================================
        # Layer 1: Detection queries ("what do you see")
        # =================================================================
        if target_layer == "layer1":
            logger.info("🔍 Processing Layer 1 detection query...")
            
            # Run Layer 0 (YOLO NCNN) locally
            layer0_detections = []
            if routing["use_layer0"] and self.layer0:
                try:
                    layer0_result = self.layer0.detect(frame)
                    layer0_detections = layer0_result if layer0_result else []
                    logger.info(f"  Layer 0: {len(layer0_detections)} detections")
                except Exception as e:
                    logger.error(f"  Layer 0 error: {e}")
            
            # Request Layer 1 (YOLOE) from laptop via WebSocket
            layer1_detections = []
            if routing["use_layer1"] and self.ws_client:
                try:
                    # For now, use local layer1 if available (laptop integration via WS is async)
                    # Full WS integration is in VisionQueryHandler
                    if self.layer1:
                        layer1_result = self.layer1.detect(frame)
                        layer1_detections = layer1_result if layer1_result else []
                        logger.info(f"  Layer 1: {len(layer1_detections)} detections")
                except Exception as e:
                    logger.error(f"  Layer 1 error: {e}")
            
            # Aggregate detections
            if DetectionAggregator:
                aggregator = DetectionAggregator(min_confidence=0.25)
                if layer1_detections:
                    merged = aggregator.merge_layers(layer0_detections, layer1_detections)
                else:
                    merged = aggregator.aggregate(layer0_detections, "layer0")
                
                response = aggregator.format_for_speech(merged)
                logger.info(f"  Aggregated: {merged['total']} objects -> '{response}'")
            else:
                # Fallback without aggregator
                total = len(layer0_detections) + len(layer1_detections)
                if total > 0:
                    response = f"I see {total} objects."
                else:
                    response = "I don't see anything specific right now."
            
            # Speak via TTS
            if TTSRouter and response:
                tts = TTSRouter()
                await tts.speak_async(response)
            
            # Store to memory
            if self.memory_manager:
                await self.memory_manager.store_query(
                    user_query=query,
                    transcribed_text=query,
                    routed_layer=target_layer,
                    routing_confidence=0.95,
                    detection_mode=routing["query_type"],
                    ai_response=response
                )

        # =================================================================
        # Layer 2: Deep analysis queries ("explain what you see")
        # =================================================================
        elif target_layer == "layer2":
            logger.info("🧠 Processing Layer 2 analysis query...")
            
            if routing["use_gemini"]:
                try:
                    # Use Gemini for vision analysis
                    if self.layer2:
                        response = await self.layer2.send_query(query, frame)
                        logger.info(f"  Gemini response: {response[:100]}...")
                    else:
                        # Fallback to GeminiTTS vision handler
                        try:
                            from rpi5.layer2_thinker.gemini_tts_handler import GeminiTTS
                            from PIL import Image
                            
                            gemini = GeminiTTS()
                            pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                            response = gemini.generate_text_from_image(pil_image, query)
                            
                            if response:
                                logger.info(f"  Gemini vision response: {response[:100]}...")
                            else:
                                response = "I couldn't analyze the scene."
                        except Exception as e:
                            logger.error(f"  Gemini vision error: {e}")
                            response = "I encountered an error analyzing the scene."
                    
                    # Speak via TTS (route based on length)
                    if TTSRouter and response:
                        tts = TTSRouter()
                        await tts.speak_async(response)
                    
                    # Store to memory
                    if self.memory_manager:
                        await self.memory_manager.store_query(
                            user_query=query,
                            transcribed_text=query,
                            routed_layer=target_layer,
                            routing_confidence=0.95,
                            ai_response=response,
                            tier_used='gemini'
                        )
                except Exception as e:
                    logger.error(f"❌ Layer 2 error: {e}")
                    response = "I encountered an error processing your request."
                    if TTSRouter:
                        tts = TTSRouter()
                        await tts.speak_async(response)
        
        # =================================================================
        # Layer 3: Navigation and spatial audio
        # =================================================================
        elif target_layer == "layer3":
            logger.info("🧭 Processing Layer 3 navigation query...")
            
            if routing["use_spatial_audio"]:
                # TODO: Implement spatial audio for object localization
                response = "Spatial audio navigation is coming soon."
            else:
                # TODO: Implement GPS/navigation
                response = "Navigation features are coming soon."
            
            if TTSRouter and response:
                tts = TTSRouter()
                await tts.speak_async(response)
        
        logger.info(f"✅ Voice command processed: '{response[:50]}...'" if len(response) > 50 else f"✅ Voice command processed: '{response}'")

    def stop(self):
        """Graceful shutdown"""
        logger.info("🛑 Stopping ProjectCortex v2.0...")

        self.running = False

        # Stop camera
        self.camera.stop()

        # Disconnect Layer 2
        if self.layer2:
            run_async_safe(self.layer2.disconnect())

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
