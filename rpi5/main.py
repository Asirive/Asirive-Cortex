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
from collections import Counter

# Rich library for interactive status display
try:
    from rich.console import Console
    from rich.live import Live
    from rich.text import Text
    from rich.panel import Panel
    from rich.logging import RichHandler
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    RichHandler = None

# Create logs directory if it doesn't exist
logs_dir = Path('logs')
logs_dir.mkdir(exist_ok=True)

# Create shared Rich console for both logging and Live display
# This prevents logging from interfering with the Live panel
_rich_console = Console() if RICH_AVAILABLE else None

# Configure logging with RichHandler to prevent interference with Live display
if RICH_AVAILABLE and RichHandler:
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',  # RichHandler handles formatting
        datefmt='[%X]',
        handlers=[
            logging.FileHandler('logs/cortex.log'),
            RichHandler(
                console=_rich_console,
                show_time=True,
                show_path=False,
                rich_tracebacks=True,
                tracebacks_show_locals=False
            )
        ]
    )
else:
    # Fallback if Rich not available
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
    from rpi5.layer3_guide import Navigator
    logger.info("[DEBUG] ✅ Layer 3 (Router + Navigator) imported successfully")
except ImportError as e:
    logger.error(f"[DEBUG] ❌ Layer 3 (Router) import failed: {e}")
    IntentRouter = None
    DetectionRouter = None
    Navigator = None

try:
    from rpi5.layer4_memory.hybrid_memory_manager import HybridMemoryManager
    logger.info("[DEBUG] ✅ Layer 4 (Memory) imported successfully")
except ImportError as e:
    logger.error(f"[DEBUG] ❌ Layer 4 (Memory) import failed: {e}")
    HybridMemoryManager = None

try:
    from rpi5.conversation_manager import ConversationManager
    logger.info("[DEBUG] ✅ ConversationManager imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ ConversationManager import failed: {e}")
    ConversationManager = None

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
from rpi5.config.config import get_config, load_config
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
    VisionQueryHandler = None  # H5: kept import for future use; guarded usage

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

try:
    from rpi5.hailo_depth import HailoDepthEstimator
    logger.info("[DEBUG] ✅ HailoDepthEstimator imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ HailoDepthEstimator import failed: {e}")
    HailoDepthEstimator = None

try:
    from hailo_platform import VDevice as HailoVDevice, HailoSchedulingAlgorithm
    HAILO_VDEVICE_AVAILABLE = True
    logger.info("[DEBUG] ✅ Hailo VDevice import successful")
except ImportError:
    HAILO_VDEVICE_AVAILABLE = False
    HailoVDevice = None
    HailoSchedulingAlgorithm = None

try:
    from rpi5.audio_alerts import AudioAlertManager
    logger.info("[DEBUG] ✅ AudioAlertManager imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ AudioAlertManager import failed: {e}")
    AudioAlertManager = None

try:
    from rpi5.hailo_ocr import HailoOCRPipeline
    logger.info("[DEBUG] ✅ HailoOCRPipeline imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ HailoOCRPipeline import failed: {e}")
    HailoOCRPipeline = None


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
# INTERACTIVE STATUS DISPLAY
# =====================================================
class StatusDisplay:
    """
    Interactive status panel for real-time detection display.
    
    Uses Rich library for in-place terminal updates.
    Shows: Mode, FPS, Layer 0 detections, Layer 1 detections (multi-line).
    
    Thread-safe for use across camera, detection, and main loops.
    """
    
    _instance = None  # Singleton instance
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._lock = threading.Lock()
        
        # Detection state
        self._l0_count = 0
        self._l0_classes = []
        self._l0_latency = 0.0
        self._l1_count = 0
        self._l1_classes = []
        self._l1_latency = 0.0
        self._fps = 0.0
        self._mode = "DEV"
        
        # Rich console and live display - use shared console to prevent logging interference
        self._console = _rich_console  # Use the module-level shared console
        self._live = None
        self._started = False
        self._enabled = RICH_AVAILABLE
        
        if not RICH_AVAILABLE:
            logger.warning("Rich library not available, using fallback status display")
    
    def start(self):
        """Start the live status display."""
        if not self._enabled or self._started:
            return
        
        try:
            self._live = Live(
                self._render(),
                console=self._console,
                refresh_per_second=4,
                transient=False,
                vertical_overflow="visible"
            )
            self._live.start()
            self._started = True
            logger.info("Interactive status display started")
        except Exception as e:
            logger.warning(f"Failed to start Rich live display: {e}")
            self._enabled = False
    
    def stop(self):
        """Stop the live status display."""
        if self._live and self._started:
            try:
                self._live.stop()
                self._started = False
            except Exception as e:
                logger.debug(f"Rich live stop error: {e}")
    
    def update_layer0(self, detections: List[Dict], latency_ms: float = 0.0):
        """Update Layer 0 detection info (thread-safe)."""
        with self._lock:
            self._l0_count = len(detections)
            self._l0_classes = [d.get('class', 'unknown') for d in detections]
            self._l0_latency = latency_ms
        self._refresh()
    
    def update_layer1(self, detections: List[Dict], latency_ms: float = 0.0):
        """Update Layer 1 detection info (thread-safe)."""
        with self._lock:
            self._l1_count = len(detections)
            self._l1_classes = [d.get('class', 'unknown') for d in detections]
            self._l1_latency = latency_ms
        self._refresh()
    
    def update_fps(self, fps: float):
        """Update FPS display (thread-safe)."""
        with self._lock:
            self._fps = fps
        self._refresh()
    
    def update_mode(self, mode: str):
        """Update mode display (thread-safe)."""
        with self._lock:
            self._mode = mode
        self._refresh()
    
    def _format_classes(self, classes: List[str], max_show: int = 8) -> str:
        """
        Format class list with grouping.
        
        Example: ['person', 'person', 'car', 'dog', 'cat'] 
              -> 'person x2, car, dog, cat'
        """
        if not classes:
            return "none"
        
        counts = Counter(classes)
        items = []
        
        for cls, count in counts.most_common(max_show):
            if count > 1:
                items.append(f"{cls} x{count}")
            else:
                items.append(cls)
        
        remaining = len(counts) - max_show
        if remaining > 0:
            items.append(f"+{remaining} more")
        
        return ", ".join(items)
    
    def _render(self):
        """Render the multi-line status panel."""
        with self._lock:
            # Format classes with more items shown
            l0_str = self._format_classes(self._l0_classes, max_show=5)
            l1_str = self._format_classes(self._l1_classes, max_show=8)
            
            # Build status text with colors
            if RICH_AVAILABLE:
                from rich.table import Table
                
                # Create a compact table for the status
                table = Table.grid(padding=(0, 2))
                table.add_column(justify="left")
                table.add_column(justify="left")
                table.add_column(justify="left")
                
                # Row 1: Mode and FPS
                mode_color = "green" if self._mode == "PRODUCTION" else "yellow"
                fps_color = "green" if self._fps >= 10 else "yellow" if self._fps >= 5 else "red"
                
                row1 = Text()
                row1.append(f"[{self._mode}]", style=f"bold {mode_color}")
                row1.append("  FPS: ", style="bold")
                row1.append(f"{self._fps:.1f}", style=f"bold {fps_color}")
                row1.append(f"  |  L0: {self._l0_latency:.0f}ms  L1: {self._l1_latency:.0f}ms", style="dim")
                
                # Row 2: Layer 0 detections
                row2 = Text()
                row2.append("L0 Guardian: ", style="bold cyan")
                row2.append(f"{self._l0_count}", style="bold white")
                if self._l0_count > 0:
                    row2.append(f" ({l0_str})", style="cyan")
                else:
                    row2.append(" (none)", style="dim")
                
                # Row 3: Layer 1 detections
                row3 = Text()
                row3.append("L1 Learner:  ", style="bold magenta")
                row3.append(f"{self._l1_count}", style="bold white")
                if self._l1_count > 0:
                    row3.append(f" ({l1_str})", style="magenta")
                else:
                    row3.append(" (none)", style="dim")
                
                table.add_row(row1)
                table.add_row(row2)
                table.add_row(row3)
                
                return Panel(
                    table,
                    title="[bold white]ProjectCortex Status[/bold white]",
                    border_style="blue",
                    padding=(0, 1)
                )
            else:
                # Fallback plain text
                return f"[{self._mode}] L0: {self._l0_count} ({l0_str}) | L1: {self._l1_count} ({l1_str}) | FPS: {self._fps:.1f}"
    
    def _refresh(self):
        """Refresh the status display."""
        if not self._enabled or not self._started or not self._live:
            return
        
        try:
            self._live.update(self._render())
        except Exception as e:
            logger.debug(f"Rich live refresh error: {e}")
    
    def print_above(self, message: str, style: str = None):
        """Print a message above the status line (for important logs)."""
        if self._console and self._started:
            try:
                if style:
                    self._console.print(message, style=style)
                else:
                    self._console.print(message)
            except Exception as e:
                print(message)
                logger.debug(f"Console print error: {e}")
        else:
            print(message)


# Global status display instance
_status_display: Optional[StatusDisplay] = None

def get_status_display() -> Optional[StatusDisplay]:
    """Get the global status display instance."""
    global _status_display
    return _status_display

def init_status_display() -> StatusDisplay:
    """Initialize and return the global status display."""
    global _status_display
    if _status_display is None:
        _status_display = StatusDisplay()
    return _status_display


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
            
            # 3. Enable Continuous Auto-Focus, Auto-Exposure, Auto White Balance
            # AfMode: 0=Manual, 1=Auto(Single), 2=Continuous
            # AwbMode: 0=Auto, 1=Incandescent, 2=Tungsten, 3=Fluorescent,
            #          4=Indoor, 5=Daylight, 6=Cloudy
            try:
                self.camera.set_controls({
                    "AfMode": 2,
                    "AeEnable": True,
                    "AwbEnable": True,
                    "AwbMode": 0,       # Auto — let ISP pick CCM from tuning file
                })
                logger.info("✅ Picamera2: AF + AE + AWB Enabled (IMX708 Wide)")
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
                        self.camera.set_controls({
                            "AfMode": 2,
                            "AeEnable": True,
                            "AwbEnable": True,
                            "AwbMode": 0,
                        })
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
            except Exception as e:
                 logger.debug(f"Module check error: {e}")
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
            except Exception as e:
                logger.debug(f"Camera index {idx} failed: {e}")
        
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
        """Continuous capture loop for Picamera2.
        
        Picamera2 outputs RGB888 natively, but the entire downstream pipeline
        (YOLO, cv2.imencode, Hailo, video streamer) expects BGR (OpenCV convention).
        We convert RGB→BGR here so get_frame() always returns BGR regardless of backend.
        """
        while self.running:
            frame = self.camera.capture_array()       # RGB888
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)  # → BGR
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
            if self.capture_thread.is_alive():
                logger.warning("Camera capture thread did not exit within 2s, forcing camera release")

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
        sb_cfg = self.config.get('supabase', {})
        supabase_enabled = sb_cfg.get('enabled', True)
        if HybridMemoryManager and supabase_enabled:
            logger.info("💾 Initializing Layer 4: Memory Manager...")
            sb_url = sb_cfg.get('url', '')
            logger.info(f"[DEBUG] Layer 4 config: url={sb_url[:30]}..., device_id={sb_cfg.get('device_id', 'rpi5-001')}")
            self.memory_manager = HybridMemoryManager(
                supabase_url=sb_url,
                supabase_key=sb_cfg.get('anon_key', ''),
                device_id=sb_cfg.get('device_id', 'rpi5-001'),
                local_db_path=sb_cfg.get('local_db_path', 'cortex_local.db'),
                sync_interval=sb_cfg.get('sync_interval_seconds', 60),
                batch_size=sb_cfg.get('batch_size', 50),
                local_cache_size=sb_cfg.get('local_cache_size', 1000)
            )
            self.memory_manager.start_sync_worker()
            logger.info("✅ Layer 4 initialized")
        elif HybridMemoryManager and not supabase_enabled:
            logger.info("💾 Initializing Layer 4: Memory Manager (local only, Supabase disabled)...")
            self.memory_manager = HybridMemoryManager(
                supabase_url=sb_cfg.get('url', ''),
                supabase_key=sb_cfg.get('anon_key', ''),
                device_id=sb_cfg.get('device_id', 'rpi5-001'),
                local_db_path=sb_cfg.get('local_db_path', 'cortex_local.db'),
                sync_interval=sb_cfg.get('sync_interval_seconds', 60),
                batch_size=sb_cfg.get('batch_size', 50),
                local_cache_size=sb_cfg.get('local_cache_size', 1000)
            )
            # Disable Supabase sync but keep local storage
            self.memory_manager.supabase_available = False
            logger.info("✅ Layer 4 initialized (local only)")
        else:
            self.memory_manager = None
            logger.warning("⚠️  Layer 4 not available, running without cloud storage")
        logger.info("[DEBUG] ===== LAYER 4 INITIALIZATION COMPLETE =====")

        # Initialize Conversation Manager
        self.conversation_manager = None
        conv_config = self.config.get('conversation', {})
        if conv_config.get('enabled', True) and ConversationManager:
            try:
                self.conversation_manager = ConversationManager(
                    db_path=sb_cfg.get('local_db_path', 'cortex_local.db'),
                    session_timeout=conv_config.get('session_timeout_seconds', 300),
                    max_turns=conv_config.get('max_turns', None),
                    config=conv_config,
                )
                logger.info("✅ ConversationManager initialized")
            except Exception as e:
                logger.error(f"❌ ConversationManager init failed: {e}")

        # Initialize Layer 0: Guardian (Safety-Critical Detection)
        logger.info("[DEBUG] ===== LAYER 0 INITIALIZATION START =====")
        if YOLOGuardian:
            logger.info("🛡️  Initializing Layer 0: Guardian...")
            layer0_cfg = self.config.get('layer0', {})
            logger.info(f"[DEBUG] Layer 0 config: model_path={layer0_cfg.get('model_path', 'N/A')}, device={layer0_cfg.get('device', 'cpu')}")
            self.layer0 = YOLOGuardian(
                model_path=layer0_cfg.get('model_path', 'models/yolo26n.pt'),
                device=layer0_cfg.get('device', 'cpu'),
                confidence=layer0_cfg.get('confidence', 0.5),
                enable_haptic=layer0_cfg.get('enable_haptic', False),
                gpio_pin=layer0_cfg.get('gpio_pin', 18),
                memory_manager=self.memory_manager
            )
            logger.info("✅ Layer 0 initialized")
        else:
            self.layer0 = None
            logger.warning("⚠️  Layer 0 not available")
        logger.info("[DEBUG] ===== LAYER 0 INITIALIZATION COMPLETE =====")

        # Initialize Layer 1: Learner (Adaptive Detection)
        logger.info("[DEBUG] ===== LAYER 1 INITIALIZATION START =====")
        layer1_cfg = self.config.get('layer1', {})
        layer1_enabled = layer1_cfg.get('enabled', True)
        if YOLOELearner and YOLOEMode and layer1_enabled:
            logger.info("🎯 Initializing Layer 1: Learner...")
            logger.info(f"[DEBUG] Layer 1 config: model_path={layer1_cfg.get('model_path', 'N/A')}, mode={layer1_cfg.get('mode', 'TEXT_PROMPTS')}")
            mode_map = {
                'PROMPT_FREE': YOLOEMode.PROMPT_FREE,
                'TEXT_PROMPTS': YOLOEMode.TEXT_PROMPTS,
                'VISUAL_PROMPTS': YOLOEMode.VISUAL_PROMPTS
            }
            self.layer1 = YOLOELearner(
                model_path=layer1_cfg.get('model_path', 'models/yoloe-26s-seg.pt'),
                device=layer1_cfg.get('device', 'cpu'),
                confidence=layer1_cfg.get('confidence', 0.25),
                mode=mode_map.get(layer1_cfg.get('mode', 'TEXT_PROMPTS'), YOLOEMode.TEXT_PROMPTS),
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
            layer2_cfg = self.config.get('layer2', {})
            logger.info(f"[DEBUG] Layer 2 config: api_key={'*' * 10} (hidden)")
            self.layer2 = GeminiLiveHandler(
                api_key=layer2_cfg.get('gemini_api_key', '')
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
        cam_cfg = self.config.get('camera', {})
        self.camera = CameraHandler(
            camera_id=cam_cfg.get('device_id', 0),
            use_picamera=cam_cfg.get('use_picamera', False),
            resolution=tuple(cam_cfg.get('resolution', [640, 480])),
            fps=cam_cfg.get('fps', 30)
        )

        # Initialize WebSocket Client (for laptop dashboard) - Use FastAPI client
        self.ws_client = None
        server_cfg = self.config.get('laptop_server', {})
        supabase_cfg = self.config.get('supabase', {})
        if CortexFastAPIClient:
            logger.info("🌐 Initializing FastAPI Client...")
            self.ws_client = CortexFastAPIClient(
                host=server_cfg.get('host', 'localhost'),
                port=server_cfg.get('port', 8765),
                device_id=supabase_cfg.get('device_id', 'rpi5-001')
            )
            # Link command handler
            self.ws_client.on_command = self.handle_dashboard_command
            logger.info("✅ FastAPI client initialized")
        elif RPiWebSocketClient:
            logger.info("🌐 Initializing legacy WebSocket Client...")
            self.ws_client = RPiWebSocketClient(
                host=server_cfg.get('host', 'localhost'),
                port=server_cfg.get('port', 8765),
                device_id=supabase_cfg.get('device_id', 'rpi5-001')
            )
            logger.info("✅ Legacy WebSocket client initialized")
        # Initialize ZMQ Video Streamer
        self.video_streamer = None
        try:
            from rpi5.video_streamer import VideoStreamer
            host = server_cfg.get('host', 'localhost')
            logger.info(f"🎥 Initializing ZMQ Streamer to {host}:5555...")
            self.video_streamer = VideoStreamer(host, 5555)
            logger.info(f"✅ ZMQ Streamer initialized: {self.video_streamer is not None}")
        except Exception as e:
            logger.error(f"❌ Failed to init ZMQ Streamer: {e}")

        # Video streaming state - only active if streamer was successfully initialized
        self.video_streaming_active = (self.video_streamer is not None)  # CRITICAL FIX: Check if streamer exists
        logger.info(f"[DEBUG] video_streaming_active={self.video_streaming_active}, video_streamer={self.video_streamer is not None}")

        # System state
        self.running = False
        self.detection_count = 0

        # TTS singleton (M1 fix: avoid re-instantiation on every voice command)
        self.tts = TTSRouter() if TTSRouter else None

        # Initialize Voice Coordinator (with audio config for VAD/Whisper tuning)
        audio_config = self.config.get('audio', {})
        self.voice_coordinator = VoiceCoordinator(
            on_command_detected=self.handle_voice_command,
            config=audio_config
        )
        self.voice_coordinator.initialize()
        
        # Initialize Bluetooth Manager (will be connected in start() if configured)
        self.bt_manager = None

        # Start Time for Uptime
        self.start_time = time.time()

        # Initialize interactive status display
        self.status_display = init_status_display()
        logger.info("📊 Interactive status display initialized")

        # Initialize Navigator (Layer 3 spatial audio)
        self.navigator = None
        if Navigator:
            try:
                self.navigator = Navigator(enable_spatial_audio=True)
                self.navigator.start()
                logger.info("✅ Navigator (spatial audio) initialized")
            except Exception as e:
                logger.error(f"❌ Failed to init Navigator: {e}")
                self.navigator = None

        # Initialize Hailo Depth Estimator (lazy — only if config enabled)
        self.depth_estimator = None
        self.audio_alerts = None
        self.ocr_pipeline = None
        self._shared_hailo_vdevice = None  # Shared across depth + OCR
        hailo_config = self.config.get('hailo', {})
        if hailo_config.get('enabled', False):
            # Create a single shared VDevice for all Hailo modules
            # Hailo-8L has only ONE physical device — can't create multiple VDevices
            if HAILO_VDEVICE_AVAILABLE:
                try:
                    # Enable ROUND_ROBIN scheduler so multiple HEFs (depth + OCR)
                    # can time-share the single Hailo-8L device
                    vdevice_params = HailoVDevice.create_params()
                    vdevice_params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
                    self._shared_hailo_vdevice = HailoVDevice(vdevice_params)
                    logger.info("✅ Shared Hailo VDevice created (ROUND_ROBIN scheduler, depth + OCR)")
                except Exception as e:
                    logger.error(f"❌ Failed to create shared Hailo VDevice: {e}")
                    self._shared_hailo_vdevice = None

            depth_config = hailo_config.get('depth', {})
            if depth_config.get('enabled', False) and HailoDepthEstimator:
                try:
                    hazard_cfg = depth_config.get('hazard_detection', {})
                    self.depth_estimator = HailoDepthEstimator(
                        hef_path=depth_config.get('model_path', 'models/hailo/fast_depth.hef'),
                        scale_factor=depth_config.get('scale_factor', 1.0),
                        wall_threshold=hazard_cfg.get('wall_threshold', 1.5),
                        stair_gradient_threshold=hazard_cfg.get('stair_gradient_threshold', 0.3),
                        dropoff_threshold=hazard_cfg.get('dropoff_threshold', 3.0),
                        approach_rate_threshold=hazard_cfg.get('approach_rate_threshold', 0.1),
                        alert_cooldown=hazard_cfg.get('alert_cooldown', 3.0),
                        vdevice=self._shared_hailo_vdevice,
                    )
                    if self.depth_estimator.is_available:
                        logger.info("✅ Hailo depth estimator initialized")
                    else:
                        logger.warning("⚠️ Hailo depth estimator loaded but NPU not available (will run without depth)")
                except Exception as e:
                    logger.error(f"❌ Failed to init Hailo depth estimator: {e}")
                    self.depth_estimator = None

            # Initialize Audio Alert Manager (for hazard alerts)
            if self.depth_estimator and AudioAlertManager:
                try:
                    self.audio_alerts = AudioAlertManager(
                        cooldown=hazard_cfg.get('alert_cooldown', 3.0)
                    )
                    logger.info(f"✅ Audio alerts initialized ({len(self.audio_alerts.available_alerts)} clips)")
                except Exception as e:
                    logger.error(f"❌ Failed to init audio alerts: {e}")
                    self.audio_alerts = None

            # Initialize OCR pipeline (lazy — detector loaded on first query)
            ocr_config = hailo_config.get('ocr', {})
            if ocr_config.get('enabled', False) and HailoOCRPipeline:
                try:
                    self.ocr_pipeline = HailoOCRPipeline(
                        recognition_hef_path=ocr_config.get('recognition_model_path', 'models/hailo/paddle_ocr_v3_recognition.hef'),
                        confidence_threshold=ocr_config.get('confidence', 0.5),
                        vdevice=self._shared_hailo_vdevice,
                    )
                    if self.ocr_pipeline.is_available:
                        logger.info("✅ Hailo OCR pipeline initialized (detector lazy-loaded)")
                    else:
                        logger.warning("⚠️ Hailo OCR pipeline loaded but NPU not available")
                except Exception as e:
                    logger.error(f"❌ Failed to init Hailo OCR: {e}")
                    self.ocr_pipeline = None

        logger.info("✅ ProjectCortex v2.0 initialized successfully")

    def handle_dashboard_command(self, cmd: Dict[str, Any]):
        """Handle incoming commands from dashboard"""
        action = cmd.get("action")
        logger.info(f"📥 Dashboard Command: {action}")
        logger.debug(f"📥 Full command payload: {cmd}")
        
        if action == "SET_MODE":
            mode = cmd.get("mode")
            logger.info(f"📥 SET_MODE command received: mode='{mode}'")
            if mode:
                self.set_mode(mode)
            else:
                logger.error(f"❌ SET_MODE missing 'mode' field! Full cmd: {cmd}")
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
        logger.info(f"🔄 set_mode() called with: '{mode}'")
        
        if mode is None:
            logger.error("❌ set_mode() called with None! Ignoring.")
            return
        
        logger.info(f"🔄 Switching to Mode: {mode}")
        
        # Update status display
        if self.status_display:
            logger.debug(f"📊 Updating status display to: {mode}")
            self.status_display.update_mode(mode)
        else:
            logger.warning("⚠️ status_display is None, cannot update mode display")
        
        if mode == "PRODUCTION":
            # Setup Bluetooth audio (uses config for device name)
            if not self.bt_manager:
                self._init_bluetooth()
            elif self.bt_manager:
                logger.info("🎧 PRODUCTION MODE: Ensuring Bluetooth Audio & Mic Profile...")
                if self.bt_manager.connect_and_setup():
                    logger.info("✅ Bluetooth audio connected and mic profile ready")
                else:
                    logger.warning("⚠️ Bluetooth audio setup incomplete - mic may not work")

            # Enable VAD (Always On) - only if not already started
            if not self.voice_coordinator.is_listening:
                logger.info("🎙️ PRODUCTION MODE: Starting VAD Always On")
                self.voice_coordinator.start()
            
            # Update Layer 1 to use tighter thresholds
            if self.layer1:
                self.layer1.confidence = 0.6 # Stricter
                
        elif mode == "DEV":
            # Disable VAD monitoring (manual trigger only)
            logger.info("🛠️ DEV MODE: Disabling VAD monitoring")
            self.voice_coordinator.stop()
            
            if self.layer1:
                self.layer1.confidence = 0.4 # Laxer
        
        # Notify laptop dashboard of mode change
        if self.ws_client and self.ws_client.is_connected:
            self.ws_client.send_status("MODE_CHANGE", mode)
            logger.info(f"Sent MODE_CHANGE={mode} to dashboard")
    
    def _init_bluetooth(self):
        """Initialize Bluetooth audio connection from config."""
        bluetooth_config = self.config.get('bluetooth', {})
        
        if not bluetooth_config.get('enabled', True):
            logger.info("ℹ️ Bluetooth disabled in config")
            return
        
        if not BluetoothAudioManager:
            logger.warning("⚠️ BluetoothAudioManager not available")
            return
        
        device_name = bluetooth_config.get('device_name', 'CMF Buds')
        auto_connect = bluetooth_config.get('auto_connect', True)
        
        if not auto_connect:
            logger.info("ℹ️ Bluetooth auto-connect disabled in config")
            return
        
        logger.info(f"🎧 Initializing Bluetooth Audio: {device_name}")
        
        try:
            self.bt_manager = BluetoothAudioManager(
                device_name=device_name,
                max_retries=bluetooth_config.get('retry_count', 3)
            )
            
            # Try to connect (to paired device) or scan and pair
            if self.bt_manager.auto_connect_or_pair(
                scan_duration=bluetooth_config.get('scan_duration', 15)
            ):
                logger.info(f"✅ Bluetooth audio connected: {device_name}")
                
                # Start auto-reconnect monitoring
                if bluetooth_config.get('auto_reconnect', True):
                    self.bt_manager.start_auto_reconnect()
                    logger.info("🔄 Bluetooth auto-reconnect enabled")
            else:
                logger.warning(f"⚠️ Bluetooth connection failed for {device_name}")
        except Exception as e:
            logger.error(f"❌ Bluetooth initialization error: {e}")

    def start(self):
        """Start main system loop"""
        logger.info("🚀 Starting ProjectCortex v2.0...")

        self.running = True

        # Start camera
        self.camera.start()

        # Connect to laptop dashboard
        if self.ws_client:
            try:
                result = self.ws_client.start()
                if result is False:
                    logger.warning("WebSocket client start() returned False — dashboard may be unavailable")
                else:
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
                    result = run_async_safe(self.layer2.connect())
                    if result is False:
                        logger.warning("⚠️ Gemini Live API connection returned False")
                    else:
                        logger.info("✅ Gemini Live API connected")
                except Exception as e:
                    logger.warning(f"⚠️ Gemini Live API failed: {e}")
            else:
                logger.info("ℹ️ Gemini Live API skipped (invalid or missing API key)")
        elif self.layer2:
            logger.info("ℹ️ Gemini Live API disabled via GEMINI_LIVE_ENABLED=false")
        
        # Set default mode to PRODUCTION
        # This handles: Bluetooth init, voice coordinator start, layer thresholds
        self.set_mode("PRODUCTION")

        # Pre-initialize TTS engines to avoid 5.5s spike on first voice query
        if self.tts:
            logger.info("🔊 Pre-loading TTS engines (Kokoro + Gemini)...")
            gemini_ok, kokoro_ok = self.tts.initialize()
            logger.info(f"🔊 TTS ready — Kokoro: {'OK' if kokoro_ok else 'FAIL'}, Gemini: {'OK' if gemini_ok else 'FAIL'}")

        logger.info("✅ System started")
        logger.info("📸 Capturing frames...")
        logger.info("🔍 Running detections...")
        logger.info("💾 Syncing to Supabase...")
        logger.info("🌐 Sending to laptop dashboard...")

        # Start interactive status display
        if self.status_display:
            self.status_display.start()
            logger.info("📊 Interactive status display active")

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

                # 2b. Run Hailo depth estimation + hazard detection
                depth_map = None
                if self.depth_estimator and self.depth_estimator.is_available:
                    try:
                        depth_map = self.depth_estimator.estimate(frame)
                        
                        if depth_map is not None:
                            # Enrich YOLO detections with distance estimates
                            for det in all_detections:
                                bbox = det.get('bbox', [])
                                if bbox and len(bbox) >= 4:
                                    dist = self.depth_estimator.get_depth_at_bbox(
                                        depth_map, bbox, frame.shape
                                    )
                                    det['distance_m'] = dist
                                    det['distance_label'] = self.depth_estimator.classify_distance(dist)
                            
                            # Analyze depth map for environmental hazards
                            hazards = self.depth_estimator.analyze_hazards(
                                depth_map, all_detections, frame.shape
                            )
                            
                            # Trigger alerts for critical/warning hazards
                            if hazards:
                                # Find highest-severity hazard
                                top_hazard = hazards[0]  # Already sorted by severity
                                
                                # Compare with L0 haptic feedback priority
                                # L0 haptic runs independently via trigger_haptic_feedback()
                                # Depth hazards use audio alerts (non-competing channel)
                                if self.audio_alerts and top_hazard.severity.value in ("critical", "warning"):
                                    self.audio_alerts.play(top_hazard.alert_key)
                                
                                # Haptic boost: if depth hazard is CRITICAL and
                                # L0 haptic is not already at max, pulse the motor
                                if (top_hazard.severity.value == "critical" 
                                    and self.layer0 and hasattr(self.layer0, 'haptic')
                                    and self.layer0.haptic):
                                    try:
                                        self.layer0.haptic.pulse(intensity=100, duration=0.3)
                                    except Exception as e:
                                        logger.debug(f"Haptic pulse error: {e}")
                    except Exception as e:
                        logger.debug(f"Depth processing error: {e}")

                # 2c. Update spatial audio with current detections
                if self.navigator and all_detections:
                    try:
                        self.navigator.update_detections(all_detections)
                    except Exception as e:
                        logger.debug(f"Spatial audio update error: {e}")

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

                # 6. Track FPS for Logging and Status Display
                loop_time = time.time() - loop_start
                fps = 1.0 / loop_time if loop_time > 0 else 0
                fps_tracker.append(fps)

                # Update status display with FPS (every frame for smooth display)
                if self.status_display:
                    self.status_display.update_fps(fps)

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
        except Exception as e:
            logger.debug(f"CPU temp read error: {e}")
            return 0.0

    def _run_dual_detection(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """Run Layer 0 + Layer 1 detection in parallel"""
        detections = []
        layer0_detections = []
        layer1_detections = []

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []
            start_times = {}

            # Layer 0: Guardian (Safety-Critical)
            if self.layer0:
                start_times['layer0'] = time.time()
                future = executor.submit(self.layer0.detect, frame)
                futures.append(('layer0', future))

            # Layer 1: Learner (Adaptive)
            if self.layer1:
                start_times['layer1'] = time.time()
                future = executor.submit(self.layer1.detect, frame)
                futures.append(('layer1', future))

            # Collect results
            for layer_name, future in futures:
                try:
                    layer_dets = future.result(timeout=1.0)  # 1 second timeout
                    latency_ms = (time.time() - start_times.get(layer_name, time.time())) * 1000
                    
                    if layer_name == 'layer0':
                        layer0_detections = layer_dets if layer_dets else []
                        # Update status display for Layer 0
                        if self.status_display:
                            self.status_display.update_layer0(layer0_detections, latency_ms)
                    elif layer_name == 'layer1':
                        layer1_detections = layer_dets if layer_dets else []
                        # Update status display for Layer 1
                        if self.status_display:
                            self.status_display.update_layer1(layer1_detections, latency_ms)
                    
                    detections.extend(layer_dets if layer_dets else [])
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
                    "layer": layer,
                    "distance_m": det.get('distance_m', -1.0),
                    "distance_label": det.get('distance_label', ''),
                })

            # Send video frame (Legacy WS) only if frame provided
            if frame is not None:
                self.ws_client.send_video_frame(frame, enriched_detections)

            # Send individual detections (Always)
            # This allows the laptop to receive detections from RPi's local layers (Guardian)
            # even if video comes via ZMQ.
            for det in enriched_detections:
                # Send each detection to laptop dashboard
                self.ws_client.send_detection(
                    class_name=det.get('class', 'unknown'),
                    confidence=det.get('confidence', 0.0),
                    bbox=[det.get('x1', 0), det.get('y1', 0), det.get('x2', 0), det.get('y2', 0)],
                    layer=0 if det.get('layer', 'layer0') == 'layer0' else 1,
                    width=self.camera.resolution[0] if self.camera else 640,
                    height=self.camera.resolution[1] if self.camera else 480
                )

        except Exception as e:
            logger.debug(f"⚠️  Failed to send to laptop: {e}")

    def _update_heartbeat(self):
        """Update device heartbeat to Supabase"""
        if self.memory_manager:
            # Gather real system metrics
            active_layers = []
            if self.layer0: active_layers.append('layer0')
            if self.layer1: active_layers.append('layer1')
            if self.layer2: active_layers.append('layer2')
            if self.intent_router: active_layers.append('layer3')
            
            current_mode = 'PRODUCTION' if self.voice_coordinator and self.voice_coordinator.is_listening else 'DEV'
            
            try:
                run_async_safe(self.memory_manager.update_device_heartbeat(
                    device_name='RPi5-Cortex-001',
                    battery_percent=100,  # RPi5 is wall-powered
                    cpu_percent=psutil.cpu_percent(),
                    memory_mb=psutil.virtual_memory().used / (1024 * 1024),
                    temperature=self._get_cpu_temp(),
                    active_layers=active_layers,
                    current_mode=current_mode
                ))
            except Exception as e:
                logger.warning(f"Heartbeat update failed: {e}")

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
        
        # Ignore filler/non-command utterances (e.g., "yeah", "thanks", "um")
        if target_layer == "ignore":
            logger.debug(f"Ignoring filler utterance: '{query}'")
            return
        
        # Intent routing now active (Layer 2 force override removed)
        
        # Notify dashboard of audio event
        if self.ws_client:
            try:
                # Send voice command event
                pass  # TODO: Implement send_audio_event on FastAPI client
            except Exception as e:
                logger.debug(f"Audio event send error: {e}")

        frame = self.camera.get_frame()
        if frame is None:
            logger.warning("⚠️  No frame available")
            # Speak error via TTS
            if self.tts:
                await self.tts.speak_async("I couldn't capture an image from the camera.")
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
            
            # Use cached Layer 1 (YOLOE) results from laptop
            layer1_detections = []
            if routing["use_layer1"] and self.ws_client:
                try:
                    import time as _time
                    cached = self.ws_client.latest_layer1_detections
                    cache_age = _time.time() - self.ws_client._layer1_cache_time
                    if cached and cache_age < 5.0:
                        layer1_detections = cached
                        logger.info(f"  Layer 1 (cached from laptop): {len(layer1_detections)} detections ({cache_age:.1f}s old)")
                    else:
                        logger.info(f"  Layer 1: No recent cached results from laptop (age={cache_age:.1f}s)")
                except Exception as e:
                    logger.error(f"  Layer 1 cache error: {e}")
            
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
            
            # Append OCR text if available (e.g., "I see 2 people. I can read: Exit, Floor 3.")
            if self.ocr_pipeline and self.ocr_pipeline.is_available:
                try:
                    ocr_results = self.ocr_pipeline.read_text(frame)
                    ocr_text = self.ocr_pipeline.format_for_speech(ocr_results)
                    if ocr_text:
                        response = response.rstrip('.') + ". " + ocr_text
                        logger.info(f"  OCR appended: {ocr_text}")
                except Exception as e:
                    logger.debug(f"OCR in Layer 1 failed: {e}")
            
            # Speak via Kokoro TTS (local, fast)
            if self.tts and response:
                await self.tts.speak_async(response, engine_override="kokoro")
            
            # Store to memory
            if self.memory_manager:
                try:
                    await self.memory_manager.store_query(
                        user_query=query,
                        transcribed_text=query,
                        routed_layer=target_layer,
                        routing_confidence=0.95,
                        detection_mode=routing["query_type"],
                        ai_response=response
                    )
                except Exception as e:
                    logger.warning(f"Memory store failed: {e}")

        # =================================================================
        # Layer 2: Deep analysis queries ("explain what you see")
        # =================================================================
        elif target_layer == "layer2":
            logger.info("Processing Layer 2 analysis query...")
            
            # OCR shortcut: Use local Hailo OCR for "read" queries instead of Gemini
            if routing["query_type"] == "analysis_ocr" and self.ocr_pipeline and self.ocr_pipeline.is_available:
                try:
                    ocr_results = self.ocr_pipeline.read_text(frame)
                    if ocr_results:
                        response = self.ocr_pipeline.format_for_speech(ocr_results)
                        logger.info(f"  OCR response (local Hailo, {self.ocr_pipeline.avg_latency_ms:.0f}ms): {response}")
                        if self.tts and response:
                            await self.tts.speak_async(response, engine_override="kokoro")
                        # Store to memory
                        if self.memory_manager:
                            try:
                                await self.memory_manager.store_query(
                                    user_query=query,
                                    transcribed_text=query,
                                    routed_layer=target_layer,
                                    routing_confidence=0.95,
                                    ai_response=response,
                                    tier_used='hailo_ocr'
                                )
                            except Exception as e:
                                logger.warning(f"Memory store failed: {e}")
                        return  # Skip Gemini — OCR handled locally
                except Exception as e:
                    logger.warning(f"Local OCR failed, falling back to Gemini vision: {e}")
            
            if routing["use_gemini"]:
                try:
                    # Use GeminiTTS vision handler (Gemini 2.0 Flash vision -> text)
                    from rpi5.layer2_thinker.gemini_tts_handler import GeminiTTS
                    from PIL import Image
                    
                    gemini = GeminiTTS()
                    # Frame is BGR (normalized at capture time) — convert to RGB for PIL
                    pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    
                    # --- Save camera frame for memory recall ---
                    saved_image_path = None
                    if self.conversation_manager:
                        saved_image_path = self.conversation_manager.save_image(pil_image)
                        if saved_image_path:
                            logger.info(f"  [MEMORY] Frame saved: {saved_image_path}")
                    
                    # --- Object recall: check if this is a search query ---
                    reference_images = None
                    if self.conversation_manager:
                        search_obj = self.conversation_manager.extract_search_object(query)
                        if search_obj:
                            logger.info(f"  [MEMORY] Object recall: searching for '{search_obj}' in history...")
                            matches = self.conversation_manager.search_object_in_history(search_obj)
                            if matches:
                                reference_images = []
                                for match in matches:
                                    if match.get("image_path") and os.path.exists(match["image_path"]):
                                        ref_img = Image.open(match["image_path"])
                                        context = match.get("full_response") or match.get("content", "")
                                        # Truncate context to ~500 chars for token efficiency
                                        reference_images.append({
                                            "image": ref_img,
                                            "context": context[:500] if context else "Object was seen here previously."
                                        })
                                logger.info(f"  [MEMORY] Loaded {len(reference_images)} reference images from history")
                        else:
                            logger.info(f"  [MEMORY] Not a search query, skipping object recall")
                    
                    # --- Conversation memory integration ---
                    history = None
                    system_instruction = None
                    enable_code_exec = routing.get("enable_code_execution", False)
                    max_chars = 150  # default
                    
                    if self.conversation_manager:
                        history = self.conversation_manager.get_history_for_gemini()
                        system_instruction = self.conversation_manager.build_system_instruction()
                        max_chars = self.conversation_manager.get_response_limit(routing["query_type"])
                        # Override code execution from ConversationManager config
                        enable_code_exec = self.conversation_manager.should_enable_code_execution(routing["query_type"])
                        logger.info(
                            f"  [MEMORY] History: {len(history) if history else 0} turns, "
                            f"refs: {len(reference_images) if reference_images else 0}, "
                            f"max_chars: {max_chars}, code_exec: {enable_code_exec}"
                        )
                    
                    response = gemini.generate_text_from_image(
                        pil_image, query,
                        conversation_history=history,
                        system_instruction=system_instruction,
                        enable_code_execution=enable_code_exec,
                        max_response_chars=max_chars,
                        reference_images=reference_images,
                    )
                    
                    # --- Fallback if Gemini returned nothing ---
                    if not response:
                        response = "I couldn't analyze the scene."
                    
                    logger.info(f"  [L2] Gemini response: {response[:100]}...")
                    
                    # --- Store turns in conversation manager (with image + full response) ---
                    # Always store, even if Gemini failed — preserves the image record
                    if self.conversation_manager:
                        full_resp = getattr(gemini, 'last_full_response', response)
                        self.conversation_manager.add_turn(
                            "user", query,
                            query_type=routing["query_type"],
                            image_path=saved_image_path,
                        )
                        self.conversation_manager.add_turn(
                            "model", response,
                            query_type=routing["query_type"],
                            full_response=full_resp,
                        )
                        # Extract personal facts from user query
                        self.conversation_manager.extract_personal_facts(query)
                    
                    # Speak via TTS — Cartesia Sonic 3 for Layer 2 (ultra-low latency cloud)
                    # Fallback chain: Cartesia -> Kokoro -> Gemini
                    if self.tts and response:
                        await self.tts.speak_async(response, engine_override="cartesia")
                    
                    # Store to memory
                    if self.memory_manager:
                        try:
                            await self.memory_manager.store_query(
                                user_query=query,
                                transcribed_text=query,
                                routed_layer=target_layer,
                                routing_confidence=0.95,
                                ai_response=response,
                                tier_used='gemini'
                            )
                        except Exception as e:
                            logger.warning(f"Memory store failed: {e}")
                except Exception as e:
                    logger.error(f"Layer 2 error: {e}")
                    response = "I encountered an error processing your request."
                    if self.tts:
                        await self.tts.speak_async(response)
        
        # =================================================================
        # Layer 3: Navigation and spatial audio
        # =================================================================
        elif target_layer == "layer3":
            logger.info("🧭 Processing Layer 3 navigation query...")
            
            if routing["use_spatial_audio"] and self.navigator:
                # Extract target object from query (e.g. "find the door" → "door")
                target = routing.get("target_object", query.split()[-1])
                started = self.navigator.start_navigation_beacon(target)
                if started:
                    response = f"Guiding you to {target} with spatial audio."
                else:
                    response = f"I can't locate {target} right now. Try asking me to look around first."
            elif self.navigator:
                response = "Navigation features are coming soon."
            else:
                response = "Spatial audio system is not available."
            
            if self.tts and response:
                await self.tts.speak_async(response)
        
        logger.info(f"✅ Voice command processed: '{response[:50]}...'" if len(response) > 50 else f"✅ Voice command processed: '{response}'")

    def stop(self):
        """Graceful shutdown"""
        turn_count = len(self.conversation_manager.turns) if self.conversation_manager else 0
        print(f"\n[Cortex] Shutting down... ({turn_count} turns saved to SQLite)")
        logger.info("Stopping ProjectCortex v2.0...")

        self.running = False

        # Stop camera
        self.camera.stop()

        # Disconnect Layer 2
        if self.layer2:
            run_async_safe(self.layer2.close())

        # Disconnect WebSocket
        if self.ws_client:
            self.ws_client.stop()

        # Stop sync worker
        if self.memory_manager:
            self.memory_manager.stop_sync_worker()
            self.memory_manager.cleanup()

        # Save conversation session and cleanup old data
        if self.conversation_manager:
            self.conversation_manager.save_session()
            cleanup_days = self.config.get('conversation', {}).get('cleanup_days', 7)
            self.conversation_manager.cleanup_old_conversations(days=cleanup_days)
            session_id = self.conversation_manager.session_id[:8]
            print(f"[Cortex] Session {session_id}... saved. Data is safe.")
            logger.info("Conversation session saved")

        # Stop interactive status display
        if self.status_display:
            self.status_display.stop()

        # Stop Navigator (spatial audio)
        if self.navigator:
            self.navigator.stop()

        # Cleanup Hailo depth estimator and OCR
        if self.depth_estimator:
            self.depth_estimator.cleanup()
        if self.audio_alerts:
            self.audio_alerts.cleanup()
        if self.ocr_pipeline:
            self.ocr_pipeline.cleanup()
        # Release shared Hailo VDevice AFTER both modules are cleaned up
        if self._shared_hailo_vdevice:
            self._shared_hailo_vdevice = None
            logger.info("Shared Hailo VDevice released")

        # Cleanup temp audio files to save storage
        try:
            import shutil
            for temp_dir in ['temp_audio']:
                temp_path = Path(temp_dir)
                if temp_path.exists():
                    for f in temp_path.glob('*.wav'):
                        f.unlink(missing_ok=True)
                    logger.info(f"🧹 Cleaned up temp audio in {temp_dir}/")
        except Exception as e:
            logger.debug(f"Temp audio cleanup error: {e}")

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
