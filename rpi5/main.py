#!/usr/bin/env python3
"""
Asirive Cortex v2.0 - Main System Orchestrator
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
- Laptop dashboard (WebSocket, optional) 
- Voice commands (VAD + Whisper)

Author: Haziq (@IRSPlays)
Competition: Young Innovators Awards (YIA) 2026
Date: January 8, 2026
"""

import asyncio
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
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
_cfg = {}
_layer0_enabled = False
_layer1_enabled = False
try:
    with open('rpi5/config/config.yaml') as f:
        _cfg = yaml.safe_load(f) or {}
        _threads = str(_cfg.get('performance', {}).get('cpu_threads', 3))
        _layer0_enabled = bool(_cfg.get('layer0', {}).get('enabled', False))
        _layer1_enabled = bool(_cfg.get('layer1', {}).get('enabled', False))
        
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
if _layer0_enabled:
    try:
        from rpi5.layer0_guardian import YOLOGuardian
        logger.info("[DEBUG] ✅ Layer 0 (Guardian) imported successfully")
    except ImportError as e:
        logger.error(f"[DEBUG] ❌ Layer 0 (Guardian) import failed: {e}")
        YOLOGuardian = None
else:
    logger.info("[DEBUG] ⏭️ Skipping Layer 0 (Guardian) import because layer0.enabled=false")
    YOLOGuardian = None

if _layer1_enabled:
    try:
        from rpi5.layer1_learner import YOLOELearner, YOLOEMode
        logger.info("[DEBUG] ✅ Layer 1 (Learner) imported successfully")
    except ImportError as e:
        logger.error(f"[DEBUG] ❌ Layer 1 (Learner) import failed: {e}")
        YOLOELearner = None
        YOLOEMode = None
else:
    logger.info("[DEBUG] ⏭️ Skipping Layer 1 (Learner) import because layer1.enabled=false")
    YOLOELearner = None
    YOLOEMode = None

try:
    from rpi5.layer2_thinker.gemini_live_handler import GeminiLiveHandler, GeminiLiveManager
    logger.info("[DEBUG] ✅ Layer 2 (Thinker) imported successfully")
except ImportError as e:
    logger.error(f"[DEBUG] ❌ Layer 2 (Thinker) import failed: {e}")
    GeminiLiveHandler = None
    GeminiLiveManager = None

try:
    from rpi5.layer2_thinker.streaming_audio_player import StreamingAudioPlayer
    logger.info("[DEBUG] ✅ StreamingAudioPlayer imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ StreamingAudioPlayer import failed: {e}")
    StreamingAudioPlayer = None

try:
    from rpi5.layer3_guide.router import IntentRouter
    from rpi5.layer3_guide.detection_router import DetectionRouter
    from rpi5.layer3_guide import Navigator
    # NOTE: SpatialAudioManager SCRAPPED — legacy code kept in rpi5/layer3_guide/spatial_audio/
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

try:
    from rpi5.session_av_recorder import SessionAVRecorder
    logger.info("[DEBUG] ✅ SessionAVRecorder imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ SessionAVRecorder import failed: {e}")
    SessionAVRecorder = None

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
    from rpi5.sensors.vl53l5cx_handler import VL53L5CXHandler
    logger.info("[DEBUG] ✅ VL53L5CXHandler imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ VL53L5CXHandler import failed: {e}")
    VL53L5CXHandler = None

try:
    from rpi5.camera.usb_camera_handler import USBCameraHandler
    logger.info("[DEBUG] ✅ USBCameraHandler imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ USBCameraHandler import failed: {e}")
    USBCameraHandler = None

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
    from rpi5.safety_monitor import SafetyMonitor
    logger.info("[DEBUG] ✅ SafetyMonitor imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ SafetyMonitor import failed: {e}")
    SafetyMonitor = None

try:
    from rpi5.hailo_ocr import HailoOCRPipeline
    logger.info("[DEBUG] ✅ HailoOCRPipeline imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ HailoOCRPipeline import failed: {e}")
    HailoOCRPipeline = None

try:
    from rpi5.hardware import GPSHandler, FusedGPSHandler, IMUHandler, ButtonHandler
    logger.info("[DEBUG] ✅ Hardware peripherals (GPS, IMU, Button) imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ Hardware peripherals import failed: {e}")
    GPSHandler = None
    FusedGPSHandler = None
    IMUHandler = None
    ButtonHandler = None

try:
    from rpi5.layer3_guide.navigation_engine import NavigationEngine, NavState
    logger.info("[DEBUG] ✅ NavigationEngine imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ NavigationEngine import failed: {e}")
    NavigationEngine = None

try:
    from rpi5.layer3_guide.saved_locations import SavedLocations
except ImportError:
    SavedLocations = None

try:
    from rpi5.layer3_guide.bus_handler import BusHandler
    logger.info("[DEBUG] ✅ BusHandler imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ BusHandler import failed: {e}")
    BusHandler = None

try:
    from rpi5.layer2_thinker.scene_change_detector import SceneChangeDetector
    logger.info("[DEBUG] ✅ SceneChangeDetector imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ SceneChangeDetector import failed: {e}")
    SceneChangeDetector = None

try:
    from rpi5.layer3_guide.connectivity_monitor import ConnectivityMonitor
    logger.info("[DEBUG] ✅ ConnectivityMonitor imported successfully")
except ImportError as e:
    logger.warning(f"[DEBUG] ⚠️ ConnectivityMonitor import failed: {e}")
    ConnectivityMonitor = None


# =====================================================
# ASYNC HELPER FUNCTION
# =====================================================
_async_bridge_loop = None
_async_bridge_thread = None
_async_bridge_lock = threading.Lock()


def _async_bridge_worker(loop: asyncio.AbstractEventLoop, ready_event: threading.Event):
    """Run a dedicated event loop for async work launched from sync code."""
    asyncio.set_event_loop(loop)
    ready_event.set()
    try:
        loop.run_forever()
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


def _ensure_async_bridge_loop() -> asyncio.AbstractEventLoop:
    """Create the background async bridge loop on first use."""
    global _async_bridge_loop, _async_bridge_thread
    with _async_bridge_lock:
        if _async_bridge_loop and _async_bridge_thread and _async_bridge_thread.is_alive():
            return _async_bridge_loop

        loop = asyncio.new_event_loop()
        ready_event = threading.Event()
        thread = threading.Thread(
            target=_async_bridge_worker,
            args=(loop, ready_event),
            name="async-bridge",
            daemon=True,
        )
        thread.start()
        ready_event.wait(timeout=2.0)
        _async_bridge_loop = loop
        _async_bridge_thread = thread
        return loop


def run_async_safe(coro, blocking=True):
    """
    Safely run an async coroutine from sync code.
    
    Args:
        coro: The coroutine to run.
        blocking: If True, blocks until complete (max 30s). If False, fire-and-forget.
    """
    try:
        # Check if there's already a running event loop
        asyncio.get_running_loop()
    except RuntimeError:
        target_loop = _ensure_async_bridge_loop()
    else:
        if not blocking:
            return asyncio.create_task(coro)
        target_loop = _ensure_async_bridge_loop()

    future = asyncio.run_coroutine_threadsafe(coro, target_loop)
    if not blocking:
        return future

    try:
        return future.result(timeout=30)
    except Exception as error:
        future.cancel()
        logger.error(f"Async execution failed: {error}")
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
        
        # GPS/IMU state
        self._gps_fix_quality = -1  # -1 = no module, 0 = no fix, 1+ = fix
        self._gps_satellites = 0
        self._gps_lat = 0.0
        self._gps_lon = 0.0
        self._gps_source = ""  # "m8u", "phone", or ""
        self._imu_heading = 0.0
        self._imu_calibration = [0, 0, 0, 0]  # sys, gyro, accel, mag
        self._environment = "unknown"
        
        # AI routing state
        self._ai_active = False  # True = Gemini routing, False = local IntentRouter
        self._ai_last_call = ""  # Last function call from Gemini
        
        # Rich console and live display - use shared console to prevent logging interference
        self._console = _rich_console  # Use the module-level shared console
        self._live = None
        self._started = False
        self._enabled = RICH_AVAILABLE
        self._last_refresh_time = 0.0
        self._refresh_interval_s = 0.25
        
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
    
    def update_gps(self, gps_fix, environment: str = "unknown", source: str = ""):
        """Update GPS display (thread-safe)."""
        with self._lock:
            self._environment = environment
            self._gps_source = source
            if gps_fix:
                self._gps_fix_quality = getattr(gps_fix, 'fix_quality', 1)
                self._gps_satellites = getattr(gps_fix, 'satellites', 0)
                self._gps_lat = getattr(gps_fix, 'latitude', 0.0)
                self._gps_lon = getattr(gps_fix, 'longitude', 0.0)
            else:
                self._gps_fix_quality = 0
                self._gps_satellites = 0
        self._refresh()
    
    def update_imu(self, imu_reading):
        """Update IMU display (thread-safe)."""
        with self._lock:
            if imu_reading:
                self._imu_heading = getattr(imu_reading, 'heading', 0.0)
                self._imu_calibration = [
                    getattr(imu_reading, 'cal_system', 0),
                    getattr(imu_reading, 'cal_gyro', 0),
                    getattr(imu_reading, 'cal_accel', 0),
                    getattr(imu_reading, 'cal_mag', 0),
                ]
        self._refresh()
    
    def update_ai(self, active: bool, last_call: str = ""):
        """Update AI routing display (thread-safe)."""
        with self._lock:
            self._ai_active = active
            if last_call:
                self._ai_last_call = last_call
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
                
                # Row 4: GPS status
                row4 = Text()
                row4.append("GPS:         ", style="bold green")
                if self._gps_fix_quality < 0:
                    row4.append("NO MODULE", style="dim")
                elif self._gps_fix_quality == 0:
                    row4.append("NO FIX", style="bold red")
                    row4.append(f"  sats: {self._gps_satellites}", style="dim")
                else:
                    fix_label = "3D FIX" if self._gps_fix_quality >= 2 else "GPS FIX"
                    row4.append(fix_label, style="bold green")
                    row4.append(f"  sats: {self._gps_satellites}", style="white")
                    row4.append(f"  ({self._gps_lat:.5f}, {self._gps_lon:.5f})", style="dim")
                env_color = "cyan" if self._environment == "indoor" else "yellow" if self._environment == "outdoor" else "dim"
                row4.append(f"  [{self._environment}]", style=env_color)
                if self._gps_source:
                    src_color = "green" if self._gps_source == "m8u" else "yellow"
                    row4.append(f"  src:{self._gps_source}", style=src_color)
                
                # Row 5: IMU status
                row5 = Text()
                row5.append("IMU:         ", style="bold blue")
                cal = self._imu_calibration
                if any(c > 0 for c in cal):
                    row5.append(f"hdg: {self._imu_heading:.0f}°", style="bold white")
                    cal_color = "green" if cal[0] == 3 else "yellow" if cal[0] >= 1 else "red"
                    row5.append(f"  cal: S{cal[0]} G{cal[1]} A{cal[2]} M{cal[3]}", style=cal_color)
                else:
                    row5.append("NO DATA", style="dim")
                
                table.add_row(row4)
                table.add_row(row5)
                
                # Row 6: AI routing status
                row6 = Text()
                row6.append("AI:          ", style="bold yellow")
                if self._ai_active:
                    row6.append("🤖 GEMINI ROUTING", style="bold green")
                    if self._ai_last_call:
                        # Truncate long function call strings
                        call_display = self._ai_last_call[:50]
                        row6.append(f"  |  Last: {call_display}", style="dim")
                else:
                    row6.append("⚡ LOCAL ROUTING", style="bold yellow")
                
                table.add_row(row6)
                
                return Panel(
                    table,
                    title="[bold white]Asirive Cortex Status[/bold white]",
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
            now = time.monotonic()
            if now - self._last_refresh_time < self._refresh_interval_s:
                return
            self._last_refresh_time = now
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

    _AWB_MODE_MAP = {
        "auto": 0,
        "incandescent": 1,
        "tungsten": 2,
        "fluorescent": 3,
        "indoor": 4,
        "daylight": 5,
        "cloudy": 6,
    }

    def __init__(
        self,
        camera_id: int = 0,
        use_picamera: bool = True,
        resolution: tuple = (1920, 1080),
        fps: int = 30,
        rotation: int = 0,
        pixel_format: str = "RGB888",
        tuning_file: Optional[str] = None,
        force_wide_tuning: bool = False,
        image_controls: Optional[Dict[str, Any]] = None,
    ):
        self.camera_id = camera_id
        self.use_picamera = use_picamera
        self.resolution = resolution
        self.fps = fps
        self.rotation = rotation  # 0, 90, -90 (or 270), 180
        self.pixel_format = str(pixel_format or "RGB888").upper()
        self.tuning_file = str(tuning_file).strip() if tuning_file else None
        self.force_wide_tuning = bool(force_wide_tuning)
        self.image_controls = dict(image_controls or {})
        self.camera = None
        self.running = False
        self.latest_frame = None
        self.latest_frame_seq = 0
        self.frame_lock = threading.Lock()
        self.capture_thread = None

    def _normalize_awb_mode(self, awb_mode: Any) -> int:
        """Convert friendly AWB mode names to libcamera enum values."""
        if isinstance(awb_mode, str):
            return self._AWB_MODE_MAP.get(awb_mode.strip().lower(), 0)

        try:
            return int(awb_mode)
        except (TypeError, ValueError):
            return 0

    def _build_picamera_controls(self) -> Dict[str, Any]:
        """Build the control set applied to Picamera2."""
        configured_controls = dict(self.image_controls)
        awb_mode = configured_controls.pop("awb_mode", configured_controls.pop("AwbMode", 0))
        awb_enable = configured_controls.pop("awb_enable", configured_controls.pop("AwbEnable", True))
        colour_gains = configured_controls.pop(
            "colour_gains",
            configured_controls.pop("ColourGains", None)
        )

        controls: Dict[str, Any] = {
            "AfMode": 2,
            "AfSpeed": 1,
            "AeEnable": True,
            "AwbEnable": bool(awb_enable),
            "AwbMode": self._normalize_awb_mode(awb_mode),
        }

        for source_key, target_key in (
            ("brightness", "Brightness"),
            ("contrast", "Contrast"),
            ("saturation", "Saturation"),
            ("sharpness", "Sharpness"),
            ("exposure_value", "ExposureValue"),
            ("noise_reduction_mode", "NoiseReductionMode"),
        ):
            value = configured_controls.pop(source_key, configured_controls.pop(target_key, None))
            if value is not None:
                controls[target_key] = value

        if colour_gains is not None:
            if isinstance(colour_gains, (list, tuple)) and len(colour_gains) == 2:
                controls["ColourGains"] = tuple(float(gain) for gain in colour_gains)
                controls["AwbEnable"] = False
            else:
                logger.warning(
                    "⚠️ camera.image_controls.colour_gains must contain exactly two values; ignoring %r",
                    colour_gains,
                )

        return controls

    def _resolve_picamera_tuning_file(self) -> Optional[str]:
        """Return the explicit tuning file path if one should be used."""
        if self.tuning_file:
            if os.path.exists(self.tuning_file):
                logger.info(f"✅ Using configured camera tuning file: {self.tuning_file}")
                return self.tuning_file

            logger.warning(
                f"⚠️ Configured camera tuning file not found: {self.tuning_file}; using libcamera auto-detect"
            )
            return None

        if not self.force_wide_tuning:
            logger.info("📷 Using libcamera auto-detected tuning")
            return None

        for backend in ("pisp", "vc4"):
            tuning_path = f"/usr/share/libcamera/ipa/rpi/{backend}/imx708_wide.json"
            if os.path.exists(tuning_path):
                logger.info(f"✅ IMX708 Wide tuning file found: {tuning_path}")
                return tuning_path

        logger.warning("⚠️ IMX708 wide tuning file not found, using libcamera auto-detect")
        return None

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

        logger.info(f"✅ Camera started: {self.camera_id} @ {self.resolution[0]}x{self.resolution[1]}"
                    f", format={self.pixel_format}"
                    f"{f', rotation={self.rotation}°' if self.rotation else ''}")

    def _start_picamera(self):
        """Initialize Picamera2 (RPi5)"""
        try:
            tuning_file_path = self._resolve_picamera_tuning_file()
            camera_controls = self._build_picamera_controls()
            
            logger.info(f"📷 [CAM-DEBUG] Importing Picamera2...")
            from picamera2 import Picamera2

            # Enumerate available cameras BEFORE trying to open one
            try:
                cam_list = Picamera2.global_camera_info()
                logger.info(f"📷 [CAM-DEBUG] Available cameras: {cam_list}")
                logger.info(f"📷 [CAM-DEBUG] Number of cameras detected: {len(cam_list)}")
                if not cam_list:
                    logger.error("📷 [CAM-DEBUG] NO CAMERAS DETECTED by libcamera! Check ribbon cable & run: python3 -c 'from picamera2 import Picamera2; print(Picamera2.global_camera_info())'")
            except Exception as enum_err:
                logger.warning(f"📷 [CAM-DEBUG] Could not enumerate cameras: {enum_err}")

            logger.info(f"📷 [CAM-DEBUG] Attempting to open camera_id={self.camera_id}, tuning_file={tuning_file_path}")

            # Load tuning file properly via Picamera2 API (more reliable than env var)
            if tuning_file_path:
                logger.info(f"📷 [CAM-DEBUG] Loading tuning file...")
                tuning = Picamera2.load_tuning_file(tuning_file_path)
                logger.info(f"📷 [CAM-DEBUG] Tuning file loaded OK, creating Picamera2 instance...")
                self.camera = Picamera2(self.camera_id, tuning=tuning)
                logger.info(f"✅ Picamera2 initialized with explicit tuning: {tuning_file_path}")
            else:
                logger.info(f"📷 [CAM-DEBUG] Creating Picamera2 instance (no tuning)...")
                self.camera = Picamera2(self.camera_id)
                logger.info("✅ Picamera2 initialized with auto-detected tuning")
            
            # Log camera model info 
            cam_info = self.camera.camera_properties
            logger.info(f"📷 Camera model: {cam_info.get('Model', 'unknown')}, "
                        f"Rotation: {cam_info.get('Rotation', 'N/A')}")
            
            # 2. Use Video Configuration (better for continuous capture)
            # Normalize back to OpenCV BGR after capture so the rest of the
            # pipeline has a single color convention regardless of ISP format.
            logger.info(
                f"📷 [CAM-DEBUG] Creating video config: format={self.pixel_format}, "
                f"size={self.resolution}, buffer_count=4"
            )
            config = self.camera.create_video_configuration(
                main={"format": self.pixel_format, "size": self.resolution},
                buffer_count=4  # Prevent starvation
            )
            logger.info(f"📷 [CAM-DEBUG] Video config created: {config}")
            self.camera.configure(config)
            logger.info(f"📷 [CAM-DEBUG] Camera configured OK")
            
            # 3. Enable Continuous Auto-Focus/Exposure and apply image controls.
            try:
                logger.info(f"📷 [CAM-DEBUG] Setting camera controls: {camera_controls}")
                self.camera.set_controls(camera_controls)
                logger.info("✅ Picamera2 camera controls applied")
            except Exception as e:
                logger.warning(f"⚠️ Could not set Camera Controls: {e}")

            logger.info(f"📷 [CAM-DEBUG] Starting camera stream...")
            self.camera.start()
            logger.info(f"📷 [CAM-DEBUG] Camera stream started OK")
            
            # 4. Give AWB/AE time to converge, then log actual gains
            import time as _time
            _time.sleep(1.0)  # Let ISP settle for 1 second
            try:
                metadata = self.camera.capture_metadata()
                colour_gains = metadata.get("ColourGains", "N/A")
                exposure_time = metadata.get("ExposureTime", "N/A")
                analogue_gain = metadata.get("AnalogueGain", "N/A")
                lux = metadata.get("Lux", "N/A")
                colour_temp = metadata.get("ColourTemperature", "N/A")
                logger.info(f"📷 AWB settled → ColourGains={colour_gains}, "
                            f"ColourTemp={colour_temp}K, Lux={lux}, "
                            f"Exposure={exposure_time}µs, Gain={analogue_gain}")
            except Exception as e:
                logger.debug(f"Could not read camera metadata: {e}")

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
                        # Load tuning file if available
                        if tuning_file_path:
                            tuning = picamera2.Picamera2.load_tuning_file(tuning_file_path)
                            self.camera = picamera2.Picamera2(self.camera_id, tuning=tuning)
                        else:
                            self.camera = picamera2.Picamera2(self.camera_id)
                        
                        # Re-apply config
                        config = self.camera.create_video_configuration(
                            main={"format": self.pixel_format, "size": self.resolution},
                            buffer_count=4
                        )
                        self.camera.configure(config)
                        self.camera.set_controls(camera_controls)
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
            import traceback
            logger.error(f"❌ Failed to start Picamera2: {e}")
            logger.error(f"❌ [CAM-DEBUG] Exception type: {type(e).__name__}")
            logger.error(f"❌ [CAM-DEBUG] Full traceback:\n{traceback.format_exc()}")
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

    def _apply_rotation(self, frame: np.ndarray) -> np.ndarray:
        """Apply configured rotation to a frame."""
        if self.rotation == -90 or self.rotation == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif self.rotation == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        return frame

    def _normalize_picamera_frame(self, frame: np.ndarray) -> np.ndarray:
        """Normalize Picamera2 output into OpenCV BGR channel order."""
        if frame is None:
            return frame
        if self.pixel_format == "RGB888":
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        return frame

    def _picamera_capture_loop(self):
        """Continuous capture loop for Picamera2.
        
        Picamera2 output is normalized to OpenCV BGR immediately after
        capture so downstream code can assume a single color convention.
        Rotation is applied per config (e.g. -90° for sideways-mounted camera).
        """
        while self.running:
            frame = self.camera.capture_array()
            frame = self._normalize_picamera_frame(frame)
            frame = self._apply_rotation(frame)
            with self.frame_lock:
                self.latest_frame = frame
                self.latest_frame_seq += 1
            time.sleep(1.0 / self.fps)

    def _opencv_capture_loop(self):
        """Continuous capture loop for OpenCV"""
        while self.running:
            ret, frame = self.camera.read()
            if ret:
                frame = self._apply_rotation(frame)
                with self.frame_lock:
                    self.latest_frame = frame
                    self.latest_frame_seq += 1
            time.sleep(1.0 / self.fps)

    def get_frame(self) -> Optional[np.ndarray]:
        """Get latest frame (thread-safe)"""
        with self.frame_lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
            return None

    def get_frame_with_seq(self, last_seq: Optional[int] = None) -> tuple[Optional[np.ndarray], int]:
        """Get the latest frame and its sequence number atomically."""
        with self.frame_lock:
            if self.latest_frame is None:
                return None, self.latest_frame_seq
            if last_seq is not None and self.latest_frame_seq == last_seq:
                return None, self.latest_frame_seq
            if self.latest_frame is not None:
                return self.latest_frame.copy(), self.latest_frame_seq
            return None, self.latest_frame_seq

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

    def __init__(self, config_path: str = None, standalone: bool = False):
        logger.info("Initializing Asirive Cortex v2.0...")
        self.standalone = standalone

        # Load configuration
        if config_path:
            self.config = load_config(config_path)
        else:
            self.config = get_config()

        # System-level flags
        self.privacy_mode = False
        self._explore_mode = False  # User requested "describe around me"
        self._battery_warned = set()  # Track which battery thresholds have been warned
        self._last_battery_check = 0.0
        self._camera_blocked_since = 0.0  # Timestamp when dark frames started
        self._camera_blocked_warned = False
        self._last_env_check = 0.0  # Environment classification timestamp
        self._last_gemini_frame_time = 0.0  # Last time we sent a frame to Gemini
        self._last_gemini_connect_time = 0.0
        self._last_gemini_context_time = 0.0  # Last time we sent context to Gemini
        self._was_indoor = False  # Track indoor→outdoor transitions for Gemini
        self._background_gemini_turns_disabled_logged = False
        self._user_speaking_to_gemini = False
        self._last_proactive_gemini_time = 0.0
        self._last_proactive_gemini_signature = ""
        self._last_processed_frame_seq = -1
        self._last_status_fps_update = 0.0
        self._live31_proactive_guidance_enabled = (
            os.getenv("GEMINI_31_PROACTIVE_GUIDANCE", "true").lower() == "true"
        )

        # AI routing state — tracks Gemini function-call routing for status display
        self._ai_routing_active = False  # True when Gemini handles all routing
        self._last_tool_call = ""  # e.g. 'guide_indoor("living room")'
        self._last_tool_call_time = 0.0
        self._last_confirmed_voice_query = ""
        self._last_confirmed_voice_query_time = 0.0

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

        layer0_cfg = self.config.get('layer0', {})
        self.layer0 = None
        if layer0_cfg.get('enabled', False) and YOLOGuardian:
            try:
                logger.info("🛡️ Initializing Layer 0: Guardian...")
                self.layer0 = YOLOGuardian(
                    model_path=layer0_cfg.get('model_path', 'models/converted/yolo26n_ncnn_model'),
                    device=layer0_cfg.get('device', 'cpu'),
                    confidence=layer0_cfg.get('confidence', 0.5),
                    enable_haptic=layer0_cfg.get('enable_haptic', True),
                    gpio_pin=layer0_cfg.get('gpio_pin', 18),
                    memory_manager=self.memory_manager,
                )
                logger.info("✅ Layer 0 initialized")
            except Exception as e:
                logger.error(f"❌ Layer 0 init failed: {e}")
                self.layer0 = None
        elif layer0_cfg.get('enabled', False):
            logger.warning("⚠️ Layer 0 enabled in config but YOLOGuardian import is unavailable")
        else:
            logger.info("⏭️ Layer 0 disabled by config")

        layer1_cfg = self.config.get('layer1', {})
        self.layer1 = None
        if layer1_cfg.get('enabled', False) and YOLOELearner and YOLOEMode:
            layer1_model_path = layer1_cfg.get('model_path', 'models/converted/yoloe_26n_seg_pf/model.onnx')
            # Gracefully skip Layer 1 if model file is missing
            if not Path(layer1_model_path).exists():
                logger.warning(f"⚠️ Layer 1 model not found at {layer1_model_path} — disabling Layer 1")
                self.layer1 = None
            else:
                try:
                    logger.info("🎯 Initializing Layer 1: Learner...")
                    layer1_mode_name = str(layer1_cfg.get('mode', 'TEXT_PROMPTS')).upper()
                    layer1_mode = {
                        'PROMPT_FREE': YOLOEMode.PROMPT_FREE,
                        'TEXT_PROMPTS': YOLOEMode.TEXT_PROMPTS,
                        'VISUAL_PROMPTS': YOLOEMode.VISUAL_PROMPTS,
                    }.get(layer1_mode_name, YOLOEMode.TEXT_PROMPTS)
                    self.layer1 = YOLOELearner(
                        model_path=layer1_model_path,
                        device=layer1_cfg.get('device', 'cpu'),
                        confidence=layer1_cfg.get('confidence', 0.25),
                        mode=layer1_mode,
                        memory_manager=self.memory_manager,
                    )
                    logger.info("✅ Layer 1 initialized")
                except Exception as e:
                    logger.error(f"❌ Layer 1 init failed: {e}")
                    self.layer1 = None
        elif layer1_cfg.get('enabled', False):
            logger.warning("⚠️ Layer 1 enabled in config but YOLOELearner import is unavailable")
        else:
            logger.info("⏭️ Layer 1 disabled by config")

        # Initialize Layer 2: Thinker (Gemini Live API via Manager)
        logger.info("[DEBUG] ===== LAYER 2 INITIALIZATION START =====")
        self.gemini_audio_player = None
        if GeminiLiveManager:
            logger.info("🧠 Initializing Layer 2: Thinker (GeminiLiveManager)...")
            layer2_cfg = self.config.get('layer2', {})
            # Prefer config file key over env var so config.yaml edits take effect
            # without requiring shell restart. Env var still works as fallback.
            config_key = layer2_cfg.get('gemini_api_key', '')
            env_key = os.environ.get('GEMINI_API_KEY', '') or os.environ.get('GOOGLE_API_KEY', '')
            api_key = config_key or env_key
            if api_key:
                masked = f"{api_key[:7]}...{api_key[-4:]}" if len(api_key) > 11 else "..."
                source = "config.yaml" if config_key else "env var"
                logger.info(f"[DEBUG] Layer 2 API key from {source}: {masked}")
            else:
                logger.warning("[DEBUG] Layer 2 API key not found in config.yaml or env vars")

            # Initialize streaming audio player for Gemini output
            if StreamingAudioPlayer:
                try:
                    self.gemini_audio_player = StreamingAudioPlayer(
                        sample_rate=24000,  # Gemini Live API outputs 24kHz PCM
                        channels=1,
                        blocksize=4800,     # 200ms blocks
                    )
                    # Reset _gemini_audio_active_since when playback stops
                    # so the echo cooldown doesn't extend past actual audio
                    self.gemini_audio_player.on_stop_callback = (
                        lambda: setattr(self, '_gemini_audio_active_since', 0)
                    )
                    logger.info("✅ StreamingAudioPlayer initialized for Gemini output")
                except Exception as e:
                    logger.warning(f"⚠️ StreamingAudioPlayer init failed: {e}")
                    self.gemini_audio_player = None

            def _on_gemini_audio(audio_bytes: bytes):
                """Callback: play Gemini audio responses via StreamingAudioPlayer."""
                if self.session_recorder:
                    self.session_recorder.write_ai_audio(audio_bytes, sample_rate=24000)
                if self.gemini_audio_player:
                    handler = getattr(self.layer2, 'handler', None) if self.layer2 else None
                    if handler and getattr(handler, 'interrupted', False):
                        return
                    # Record timestamp IMMEDIATELY so is_output_playing() returns True
                    # before the player's start() finishes opening the audio stream.
                    # This prevents real mic audio leaking to Gemini's auto-VAD
                    # during the startup window → false barge-in → session death.
                    self._gemini_audio_active_since = time.time()
                    if self.scene_detector:
                        self.scene_detector.record_speech()
                    if not self.gemini_audio_player.is_playing:
                        logger.debug("🔊 Auto-starting audio player for Gemini response")
                        self.gemini_audio_player.start()
                    self.gemini_audio_player.add_audio_chunk(audio_bytes)

            self.layer2 = GeminiLiveManager(
                api_key=api_key,
                audio_callback=_on_gemini_audio,
                model=layer2_cfg.get('model', 'gemini-3.1-flash-live-preview'),
                response_modalities=layer2_cfg.get('live_api_config', {}).get('response_modalities', ['AUDIO']),
            )
            # Wire barge-in callback so interrupted events flush the hardware audio buffer
            if hasattr(self.layer2, 'handler') and self.gemini_audio_player:
                self.layer2.handler._on_barge_in_callback = lambda: self.gemini_audio_player.request_stop(interrupted=True)
                self.layer2.handler._on_turn_complete_callback = self._on_gemini_turn_complete
            # Wire barge-in enabled flag from config
            if hasattr(self.layer2, 'handler'):
                barge_in = bool((self.config.get('vad') or {}).get('barge_in_enabled', True))
                self.layer2.handler.barge_in_enabled = barge_in
                self.layer2.handler._on_connected_callback = self._on_gemini_reconnected
            logger.info("✅ Layer 2 initialized (GeminiLiveManager)")
        elif GeminiLiveHandler:
            logger.info("🧠 Initializing Layer 2: Thinker (GeminiLiveHandler fallback)...")
            layer2_cfg = self.config.get('layer2', {})
            config_key = layer2_cfg.get('gemini_api_key', '')
            env_key = os.environ.get('GEMINI_API_KEY', '') or os.environ.get('GOOGLE_API_KEY', '')
            api_key = config_key or env_key
            self.layer2 = GeminiLiveHandler(api_key=api_key)
            logger.info("✅ Layer 2 initialized (fallback)")
        else:
            self.layer2 = None
            logger.warning("⚠️  Layer 2 not available")

        # Wire Gemini function calling callback
        if self.layer2 and hasattr(self.layer2, 'set_tool_callback'):
            self.layer2.set_tool_callback(self._handle_gemini_tool_call)

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
        # IVP: Prefer USB camera (glasses-mounted) over CSI / picamera2
        logger.info("📸 Initializing Camera...")
        cam_cfg = self.config.get('camera', {})
        self._using_usb_camera = False
        if USBCameraHandler:
            try:
                usb_cam = USBCameraHandler(
                    device_id=cam_cfg.get('usb_device_id', 0),
                    resolution=tuple(cam_cfg.get('resolution', [640, 480])),
                    fps=cam_cfg.get('fps', 30),
                    rotation=cam_cfg.get('rotation', 0),
                    fourcc=cam_cfg.get('usb_fourcc', 'MJPG'),
                )
                # Don't start here — start() is called in system start()
                self.camera = usb_cam
                self._using_usb_camera = True
                logger.info("✅ USB camera selected (glasses-mounted)")
            except Exception as e:
                logger.warning(f"⚠️ USB camera init failed ({e}), falling back to CSI/picamera2")
                self.camera = None
        if self.camera is None:
            cam_tuning_cfg = cam_cfg.get('tuning', {})
            self.camera = CameraHandler(
                camera_id=cam_cfg.get('device_id', 0),
                use_picamera=cam_cfg.get('use_picamera', False),
                resolution=tuple(cam_cfg.get('resolution', [640, 480])),
                fps=cam_cfg.get('fps', 30),
                rotation=cam_cfg.get('rotation', 0),
                pixel_format=cam_cfg.get('format', 'RGB888'),
                tuning_file=cam_tuning_cfg.get('file'),
                force_wide_tuning=cam_tuning_cfg.get('use_explicit_wide_tuning', False),
                image_controls=cam_cfg.get('image_controls', {}),
            )

        # Initialize WebSocket Client (for laptop dashboard) - Use FastAPI client
        self.ws_client = None
        server_cfg = self.config.get('laptop_server', {})
        supabase_cfg = self.config.get('supabase', {})
        if self.standalone:
            logger.info("⏭️  Standalone mode — skipping laptop dashboard client")
        elif CortexFastAPIClient:
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
        if not self.standalone:
            try:
                from rpi5.video_streamer import VideoStreamer
                host = server_cfg.get('host', 'localhost')
                logger.info(f"🎥 Initializing ZMQ Streamer to {host}:5555...")
                self.video_streamer = VideoStreamer(host, 5555)
                logger.info(f"✅ ZMQ Streamer initialized: {self.video_streamer is not None}")
            except Exception as e:
                logger.error(f"❌ Failed to init ZMQ Streamer: {e}")
        else:
            logger.info("⏭️  Standalone mode — skipping ZMQ video streamer")

        # Video streaming state - only active if streamer was successfully initialized
        self.video_streaming_active = (self.video_streamer is not None)  # CRITICAL FIX: Check if streamer exists
        logger.info(f"[DEBUG] video_streaming_active={self.video_streaming_active}, video_streamer={self.video_streamer is not None}")

        # System state
        self.running = False
        self.detection_count = 0
        self.session_recorder = None
        self._recording_hotkey_thread = None
        self._recording_hotkey_stop = threading.Event()
        self._layer0_executor = None
        self._layer1_executor = None
        self._layer0_future = None
        self._layer1_future = None
        self._layer0_submit_time = 0.0
        self._layer1_submit_time = 0.0
        self._layer0_timeout_logged = False
        self._layer1_timeout_logged = False
        self._last_layer0_detections = []
        self._last_layer1_detections = []

        # TTS singleton (M1 fix: avoid re-instantiation on every voice command)
        self.tts = TTSRouter() if TTSRouter else None

        # Initialize Voice Coordinator (with audio config for VAD/Whisper tuning)
        audio_config = self.config.get('audio', {})
        self.voice_coordinator = VoiceCoordinator(
            on_command_detected=self.handle_voice_command,
            config=audio_config
        )
        self.voice_coordinator.initialize()

        recorder_cfg = self.config.get('data_recorder', {})
        if SessionAVRecorder and recorder_cfg.get('enabled', False):
            self.session_recorder = SessionAVRecorder(recorder_cfg)
            self.voice_coordinator.on_mic_audio = self._on_mic_audio
            logger.info(
                f"✅ Session recorder ready (press '{self.session_recorder.toggle_key}' to toggle recording)"
            )

        # Wire GeminiLiveManager into voice pipeline.
        # Raw audio is streamed continuously for ambient context.
        # Local VAD owns turn boundaries for Gemini 3.1 via explicit
        # activity_start/activity_end signals. Text commands still trigger
        # model turns when explicitly used.
        if self.layer2 is not None:
            self.voice_coordinator.on_raw_audio = self._forward_audio_to_gemini
            self.voice_coordinator.on_speech_start_callback = self._forward_gemini_activity_start
            self.voice_coordinator.on_speech_end_callback = self._forward_gemini_activity_end
            self.voice_coordinator.on_barge_in_callback = self._handle_gemini_barge_in
            logger.info("✅ Gemini Live wired into voice pipeline (audio-first mode, explicit VAD)")

        # Wire echo suppression: tell VoiceCoordinator when speaker is active
        # so it discards speech segments that are just Gemini's own output
        if self.gemini_audio_player:
            self._gemini_audio_active_since = 0  # Timestamp of first Gemini audio chunk
            def _is_output_playing() -> bool:
                p = self.gemini_audio_player
                if p.is_playing:
                    return True
                # 0.15s cooldown after playback stops (was 0.5s — too long,
                # caused "system doesn't answer" bug where user's immediate
                # speech after Gemini finish was silently discarded)
                if (time.time() - p._last_stop_time) < 0.15:
                    return True
                # Early protection: covers the gap between first Gemini audio
                # chunk arriving and the player stream actually opening.
                # Auto-expires after 0.15s — just enough for stream open latency.
                if self._gemini_audio_active_since > 0 and (time.time() - self._gemini_audio_active_since) < 0.15:
                    return True
                return False
            self.voice_coordinator.is_output_playing = _is_output_playing
            logger.info("✅ Echo suppression wired (VAD + mic gate, 0.15s cooldown)")

        # Initialize Bluetooth Manager (will be connected in start() if configured)
        self.bt_manager = None

        # Start Time for Uptime
        self.start_time = time.time()

        # Initialize interactive status display
        self.status_display = init_status_display()
        logger.info("📊 Interactive status display initialized")

        # Initialize Navigator (Layer 3 — spatial audio SCRAPPED, kept for routing only)
        self.navigator = None
        if Navigator:
            try:
                self.navigator = Navigator(enable_spatial_audio=False)
                self.navigator.start()
                logger.info("✅ Navigator initialized (spatial audio disabled)")
            except Exception as e:
                logger.error(f"❌ Failed to init Navigator: {e}")
                self.navigator = None

        # SpatialAudioManager SCRAPPED — legacy code in rpi5/layer3_guide/spatial_audio/
        self.spatial_audio = None

        # =====================================================
        # HARDWARE PERIPHERALS (GPS, IMU, Button)
        # =====================================================
        sensor_cfg = self.config.get('sensors', {})

        # GPS Handler (FusedGPS = M8U hardware + phone browser fallback)
        self.gps = None  # type: Optional[FusedGPSHandler]
        gps_cfg = sensor_cfg.get('gps', {})
        if GPSHandler and FusedGPSHandler and gps_cfg.get('enabled', False):
            try:
                hw_gps = GPSHandler(
                    port=gps_cfg.get('port', '/dev/ttyAMA0'),
                    baudrate=gps_cfg.get('baudrate', 9600),
                    timeout=gps_cfg.get('timeout', 1.0),
                )
                phone_gps_port = gps_cfg.get('phone_gps_port', 8766)
                phone_gps_enabled = gps_cfg.get('phone_gps_enabled', True)
                self.gps = FusedGPSHandler(
                    gps_handler=hw_gps,
                    phone_gps_port=phone_gps_port,
                    phone_gps_enabled=phone_gps_enabled,
                )
                # Wire GPS into Navigator so get_gps_location() returns real data
                if self.navigator and hasattr(self.navigator, 'set_gps_handler'):
                    self.navigator.set_gps_handler(self.gps)
                logger.info("✅ Fused GPS initialized (M8U + Phone fallback, will start in start())")
            except Exception as e:
                logger.error(f"❌ Failed to init GPS: {e}")
                self.gps = None

        # IMU Handler
        self.imu = None  # type: Optional[IMUHandler]
        imu_cfg = sensor_cfg.get('imu', {})
        if IMUHandler and imu_cfg.get('enabled', False):
            try:
                self.imu = IMUHandler(
                    i2c_address=int(imu_cfg.get('i2c_address', 0x28)),
                    poll_hz=float(imu_cfg.get('poll_hz', 25.0)),
                    mounting=imu_cfg.get('mounting', 'default'),
                )
                # Fall-detection wired to haptic + TTS alert
                self.imu.on_fall_detected = self._on_fall_detected
                logger.info("✅ IMU Handler initialized (will start in start())")
            except Exception as e:
                logger.error(f"❌ Failed to init IMU: {e}")
                self.imu = None

        # Button Handler
        self.button = None  # type: Optional[ButtonHandler]
        btn_cfg = sensor_cfg.get('button', {})
        if ButtonHandler and btn_cfg.get('enabled', False):
            try:
                self.button = ButtonHandler(
                    gpio_pin=btn_cfg.get('gpio_pin', 16),
                    auto_shutdown=btn_cfg.get('auto_shutdown', True),
                )
                # Short press → activate voice command listen
                self.button.on_short_press = self._on_button_short_press
                # Long press → graceful system stop (not OS shutdown — auto_shutdown handles that)
                self.button.on_long_press = self._on_button_long_press
                logger.info("✅ Button Handler initialized (will start in start())")
            except Exception as e:
                logger.error(f"❌ Failed to init Button: {e}")
                self.button = None

        # =====================================================
        # NAVIGATION ENGINE + BUS HANDLER + SCENE CHANGE
        # =====================================================
        nav_cfg = self.config.get('layer3', {}).get('navigation', {})
        self.nav_engine = None
        self._pending_destination = None  # Queued destination when no GPS fix
        self._awaiting_origin = None  # Destination saved while asking user for origin
        self.saved_locations = None
        if SavedLocations:
            locations_cfg = nav_cfg.get('saved_locations', [])
            self.saved_locations = SavedLocations(locations_cfg)
        if NavigationEngine:
            try:
                spatial_audio = self.navigator.spatial_audio if self.navigator and hasattr(self.navigator, 'spatial_audio') else None
                self.nav_engine = NavigationEngine(
                    api_key=os.environ.get('GOOGLE_MAPS_API_KEY', nav_cfg.get('google_maps_api_key', '')),
                    gps=self.gps,
                    imu=self.imu,
                    spatial_audio=spatial_audio,
                    tts=self.tts,
                    on_arrival=self._on_nav_arrival,
                    on_mode_change=self._on_nav_mode_change,
                    on_nav_event=self._on_nav_event_gemini,
                )
                # Let the engine know when to stay silent — Gemini narrates
                # while its Live session is connected.
                try:
                    self.nav_engine.set_gemini_online_callback(self._should_suppress_local_nav_voice)
                except Exception as e:
                    logger.warning(f"nav_engine.set_gemini_online_callback failed: {e}")
                logger.info("✅ NavigationEngine initialized")
            except Exception as e:
                logger.error(f"❌ Failed to init NavigationEngine: {e}")
                self.nav_engine = None

        bus_cfg = self.config.get('layer3', {}).get('bus', {})
        self.bus_handler = None
        if BusHandler:
            try:
                self.bus_handler = BusHandler(
                    lta_api_key=os.environ.get('LTA_API_KEY', bus_cfg.get('lta_api_key', '')),
                    tts=self.tts,
                )
                logger.info("✅ BusHandler initialized")
            except Exception as e:
                logger.error(f"❌ Failed to init BusHandler: {e}")
                self.bus_handler = None

        # Wire bus_handler into nav_engine for transit route leg management
        if self.nav_engine and self.bus_handler:
            self.nav_engine.bus_handler = self.bus_handler
            logger.info("🔗 BusHandler wired to NavigationEngine")

        self.scene_detector = None
        if SceneChangeDetector:
            try:
                self.scene_detector = SceneChangeDetector()
                logger.info("✅ SceneChangeDetector initialized")
            except Exception as e:
                logger.error(f"❌ Failed to init SceneChangeDetector: {e}")
                self.scene_detector = None

        self.connectivity_monitor = None
        if ConnectivityMonitor:
            try:
                # Pass the underlying handler if layer2 is a GeminiLiveManager
                gemini_handler_ref = None
                if self.layer2:
                    if hasattr(self.layer2, 'handler'):
                        gemini_handler_ref = self.layer2.handler  # GeminiLiveManager
                    else:
                        gemini_handler_ref = self.layer2  # Direct GeminiLiveHandler
                self.connectivity_monitor = ConnectivityMonitor(
                    ws_client=self.ws_client,
                    gemini_handler=gemini_handler_ref,
                    tts=self.tts,
                )
                logger.info("✅ ConnectivityMonitor initialized")
            except Exception as e:
                logger.error(f"❌ Failed to init ConnectivityMonitor: {e}")
                self.connectivity_monitor = None

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

        # ── IVP: Initialize VL53L5CX ToF depth sensor (glasses-mounted) ──
        self.tof_handler = None
        if VL53L5CXHandler:
            try:
                self.tof_handler = VL53L5CXHandler(
                    i2c_bus=1,
                    i2c_address=0x52,
                    mock=False,  # Set True for dev without hardware
                )
                if self.tof_handler.is_available:
                    logger.info("✅ VL53L5CX ToF handler initialized (8×8 depth, glasses-mounted)")
                else:
                    logger.warning("⚠️ VL53L5CX handler not available")
                    self.tof_handler = None
            except Exception as e:
                logger.error(f"❌ Failed to init VL53L5CX ToF handler: {e}")
                self.tof_handler = None

        if hailo_config.get('enabled', False):
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

        # Initialize SafetyMonitor (fusion engine: YOLO + Hailo depth → tiered alerts)
        self.safety_monitor = None
        if SafetyMonitor:
            try:
                safety_cfg = self.config.get('safety', {})
                cam_cfg = self.config.get('camera', {})
                fw = cam_cfg.get('resolution', [1920, 1080])[0]
                self.safety_monitor = SafetyMonitor(
                    tier2_max_distance=safety_cfg.get('tier2_max_distance', 2.0),
                    tier3_max_distance=safety_cfg.get('tier3_max_distance', 4.0),
                    tier3_approach_velocity=safety_cfg.get('tier3_approach_velocity', 1.0),
                    alert_cooldown=safety_cfg.get('alert_cooldown', 3.0),
                    tts_cooldown=safety_cfg.get('tts_cooldown', 8.0),
                    haptic_cooldown=safety_cfg.get('haptic_cooldown', 2.0),
                    frame_width=fw,
                    imu=self.imu,
                )
                logger.info("✅ SafetyMonitor initialized (YOLO + Hailo depth fusion)")
            except Exception as e:
                logger.error(f"❌ Failed to init SafetyMonitor: {e}")
                self.safety_monitor = None

        logger.info("✅ Asirive Cortex v2.0 initialized successfully")

    # ------------------------------------------------------------------
    # Hardware peripheral callbacks
    # ------------------------------------------------------------------

    def _on_button_short_press(self) -> None:
        """Short button press: activate voice command listen."""
        logger.info("🔘 Button short press → triggering voice command listen")
        if self.voice_coordinator:
            self.voice_coordinator.start()  # Re-activates VAD listening

    def _on_button_long_press(self) -> None:
        """Long button press (3–5s): graceful application stop."""
        logger.info("🔘 Button long press → stopping system (graceful)")
        self.stop()

    def _on_fall_detected(self) -> None:
        """IMU fall detection callback: alert user and caregiver."""
        logger.warning("⚠️ Free-fall / fall detected by IMU!")
        # Haptic alert if available
        if self.layer0 and hasattr(self.layer0, 'haptic') and self.layer0.haptic:
            self.layer0.haptic.pulse(intensity=100, duration=0.5)
        # TTS alert
        if self.tts:
            try:
                self.tts.speak("Warning: fall detected. Are you okay?")
            except Exception as exc:
                logger.error(f"TTS fall alert error: {exc}")

    def _forward_audio_to_gemini(self, pcm_bytes: bytes, sample_rate: int) -> None:
        """
        Forward raw PCM audio to GeminiLiveManager (audio-to-audio path).
        Called by VoiceCoordinator for every 32ms VAD chunk (continuous stream).
        Video is sent separately at 1 FPS from the detection loop.

        During speaker playback, sends zero-filled silence instead of real audio.
        This keeps the audio stream continuous — dropping audio creates
        silence→audio transitions that destabilize Gemini's live turn state.
        """
        if not self.layer2 or not self.layer2.is_running:
            return
        try:
            self.layer2.send_audio(pcm_bytes, sample_rate)
        except Exception as e:
            logger.debug(f"GeminiLive audio forward error: {e}")

    def _on_mic_audio(self, pcm_bytes: bytes, sample_rate: int) -> None:
        """Capture continuous microphone PCM for the manual recorder."""
        if self.session_recorder:
            self.session_recorder.write_mic_audio(pcm_bytes, sample_rate)

    def _toggle_session_recording(self) -> None:
        """Toggle session recording without stopping the Cortex runtime."""
        if not self.session_recorder:
            return

        if self.session_recorder.is_recording:
            self.session_recorder.stop()
            return

        frame = self.camera.get_frame() if self.camera else None
        frame_shape = frame.shape if frame is not None else None
        if self.session_recorder.start(frame_shape=frame_shape) and frame is not None:
            self.session_recorder.write_video_frame(frame)

    def _recording_hotkey_loop(self) -> None:
        """Listen for a single-key terminal toggle on Linux TTY sessions."""
        if not self.session_recorder:
            return
        if os.name != 'posix' or not sys.stdin or not sys.stdin.isatty():
            logger.info("ℹ️ Session recorder hotkey disabled (interactive POSIX TTY required)")
            return

        try:
            import select
            import termios
            import tty
        except ImportError:
            logger.info("ℹ️ Session recorder hotkey unavailable on this platform")
            return

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            logger.info(
                f"⌨️ Press '{self.session_recorder.toggle_key}' to start/stop session recording"
            )
            while self.running and not self._recording_hotkey_stop.is_set():
                readable, _, _ = select.select([sys.stdin], [], [], 0.2)
                if not readable:
                    continue
                key = sys.stdin.read(1)
                if key and key.lower() == self.session_recorder.toggle_key:
                    self._toggle_session_recording()
        except Exception as e:
            logger.warning(f"⚠️ Session recorder hotkey loop stopped: {e}")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _start_recording_hotkey_listener(self) -> None:
        """Start the terminal hotkey listener for manual recording."""
        if not self.session_recorder or self._recording_hotkey_thread:
            return
        self._recording_hotkey_stop.clear()
        self._recording_hotkey_thread = threading.Thread(
            target=self._recording_hotkey_loop,
            name="recording-hotkey",
            daemon=True,
        )
        self._recording_hotkey_thread.start()

    def _stop_recording_hotkey_listener(self) -> None:
        """Stop the terminal hotkey listener."""
        self._recording_hotkey_stop.set()
        if self._recording_hotkey_thread and self._recording_hotkey_thread.is_alive():
            self._recording_hotkey_thread.join(timeout=1.0)
        self._recording_hotkey_thread = None

    def _handle_gemini_barge_in(self) -> None:
        """Stop Gemini playback immediately when the user starts speaking."""
        if self.layer2 and hasattr(self.layer2, 'handler'):
            self.layer2.handler.interrupted = True
        if not self.gemini_audio_player:
            return
        if self.gemini_audio_player.is_playing:
            logger.info("🛑 User barge-in detected — stopping Gemini playback")
            self.gemini_audio_player.request_stop(interrupted=True)

    def _on_gemini_turn_complete(self) -> None:
        """Let local playback stop as soon as Gemini's queued audio finishes."""
        if not self.gemini_audio_player:
            return
        self.gemini_audio_player.mark_turn_complete()

    def _forward_gemini_activity_start(self) -> None:
        """Forward local speech-start to Gemini 3.1 explicit VAD."""
        if not self.layer2 or not self.layer2.is_running:
            return
        self._user_speaking_to_gemini = True
        try:
            self.layer2.send_activity_start()
        except Exception as e:
            logger.debug(f"Gemini activity start forward error: {e}")

    def _forward_gemini_activity_end(self) -> None:
        """Forward local speech-end to Gemini 3.1 explicit VAD."""
        if not self.layer2 or not self.layer2.is_running:
            self._user_speaking_to_gemini = False
            return
        try:
            self.layer2.send_activity_end()
        except Exception as e:
            logger.debug(f"Gemini activity end forward error: {e}")
        finally:
            self._user_speaking_to_gemini = False

    def _gemini_is_live_31(self) -> bool:
        """Return True when the active Live runtime is Gemini 3.1."""
        return bool(
            self.layer2
            and hasattr(self.layer2, 'handler')
            and getattr(self.layer2.handler, '_is_gemini_live_31', False)
        )

    def _gemini_background_turns_allowed(self) -> bool:
        """Synthetic system-triggered Gemini turns are disabled on 3.1."""
        return bool(self.layer2 and self.layer2.is_running and not self._gemini_is_live_31())

    def _gemini_mid_session_context_allowed(self) -> bool:
        """Return True when the active runtime supports silent mid-session context."""
        return bool(self.layer2 and self.layer2.is_running and not self._gemini_is_live_31())

    def _should_suppress_local_nav_voice(self) -> bool:
        """Suppress local nav TTS when Gemini Live is connected.

        Gemini narrates via tool responses (user-triggered turns). Background
        turns are disabled on 3.1, but tool call responses still generate audio.
        """
        return self._is_gemini_live_online()

    def _log_gemini_background_turn_skipped(self, reason: str) -> None:
        """Log once that 3.1 background turns are intentionally suppressed."""
        if not self._background_gemini_turns_disabled_logged:
            logger.info("🛡️ Synthetic Gemini background turns disabled on Gemini 3.1 Live")
            self._background_gemini_turns_disabled_logged = True
        logger.debug(f"Skipped Gemini background turn: {reason}")

    def _send_gemini_video(self, frame=None, min_interval: float = 1.0) -> bool:
        """Send a frame to Gemini while coalescing reconnect/query/periodic bursts."""
        if not self.layer2 or not self.layer2.is_running:
            return False
        if self._user_speaking_to_gemini:
            return False
        now = time.time()
        if min_interval > 0 and (now - self._last_gemini_frame_time) < min_interval:
            return False
        try:
            if frame is None:
                if not self.camera:
                    return False
                frame = self.camera.get_frame()
            if frame is None:
                return False
            from PIL import Image
            pil_frame = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            self.layer2.send_video(pil_frame)
            self._last_gemini_frame_time = now
            return True
        except Exception as e:
            logger.debug(f"Gemini video send error: {e}")
            return False

    def _can_send_proactive_gemini_guidance(self) -> bool:
        """Return True when a proactive Gemini guidance turn is safe to send."""
        now = time.time()
        if not self.layer2 or not self.layer2.is_running:
            return False
        if not hasattr(self.layer2, 'handler') or not self.layer2.handler.is_connected:
            return False
        if self._gemini_is_live_31():
            if not self._live31_proactive_guidance_enabled:
                self._log_gemini_background_turn_skipped("proactive_guidance_live31")
                return False
            if self._last_gemini_connect_time and (now - self._last_gemini_connect_time) < 20.0:
                return False
        elif self._last_gemini_connect_time and (now - self._last_gemini_connect_time) < 5.0:
            return False
        if self._user_speaking_to_gemini:
            return False
        if (self.voice_coordinator
            and self.voice_coordinator.is_output_playing
            and self.voice_coordinator.is_output_playing()):
            return False
        if self.tts and getattr(self.tts, 'is_playing', False):
            return False
        if not self.nav_engine or not hasattr(self.nav_engine, 'mode') or not hasattr(self.nav_engine, 'state'):
            return False
        return (
            getattr(self.nav_engine.mode, 'value', self.nav_engine.mode) == 'indoor'
            and getattr(self.nav_engine.state, 'value', self.nav_engine.state) == 'navigating'
        )

    def _send_proactive_gemini_guidance(
        self,
        prompt: str,
        reason: str,
        signature: str,
        frame=None,
        min_interval: float = 6.0,
    ) -> bool:
        """Send a proactive indoor-guidance turn when the active runtime supports it."""
        if not self._can_send_proactive_gemini_guidance():
            return False
        if self._gemini_is_live_31() and reason.endswith("periodic_update"):
            logger.debug("Skipping periodic proactive turn on Gemini 3.1 Live")
            return False
        now = time.time()
        effective_min_interval = max(min_interval, 12.0) if self._gemini_is_live_31() else min_interval
        if now - self._last_proactive_gemini_time < effective_min_interval:
            return False
        if signature and signature == self._last_proactive_gemini_signature:
            if now - self._last_proactive_gemini_time < (effective_min_interval * 2):
                return False
        if frame is not None:
            self._send_gemini_video(frame, min_interval=0.0)
        audio_pause_s = 1.25 if self._gemini_is_live_31() else 0.75
        try:
            self.layer2.send_text(prompt, audio_pause_s=audio_pause_s)
        except TypeError:
            self.layer2.send_text(prompt)
        self._last_proactive_gemini_time = now
        self._last_proactive_gemini_signature = signature
        if self.scene_detector:
            self.scene_detector.record_speech()
        logger.info(f"🧭 Proactive Gemini guidance triggered ({reason})")
        return True

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
                # Use safe async runner — NON-BLOCKING to avoid deadlocking event loop
                run_async_safe(self.handle_voice_command(query), blocking=False)

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

        # New: Navigation commands from laptop dashboard
        elif action == "NAVIGATION":
            nav_data = cmd.get("navigation_data", {})
            nav_action = nav_data.get("action", "")
            if nav_action == "set_destination" and self.nav_engine:
                dest = nav_data.get("destination", {})
                dest_str = dest.get("name") or f"{dest.get('lat')},{dest.get('lon')}"
                run_async_safe(self.nav_engine.start_navigation("current", dest_str), blocking=False)
            elif nav_action == "cancel" and self.nav_engine:
                run_async_safe(self.nav_engine.stop_navigation(), blocking=False)
            else:
                logger.warning(f"⚠️ Unhandled NAVIGATION action: {nav_action}")

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
        
        # Support new multi-device config: bluetooth.active_device -> bluetooth.devices.<key>.name
        active_key = bluetooth_config.get('active_device')
        devices_map = bluetooth_config.get('devices', {})
        
        if active_key and active_key in devices_map:
            dev_cfg = devices_map[active_key]
            device_name = dev_cfg.get('name', 'CMF Buds')
            device_mac = dev_cfg.get('mac')
            device_type = dev_cfg.get('type', 'unknown')
            logger.info(f"🎧 Active earbud: {active_key} ({device_type}) -> '{device_name}' [{device_mac or 'no MAC'}]")
        else:
            # Legacy fallback
            device_name = bluetooth_config.get('device_name', 'CMF Buds')
            device_mac = None
        
        auto_connect = bluetooth_config.get('auto_connect', True)
        
        if not auto_connect:
            logger.info("ℹ️ Bluetooth auto-connect disabled in config")
            return
        
        logger.info(f"🎧 Initializing Bluetooth Audio: {device_name}")
        
        try:
            self.bt_manager = BluetoothAudioManager(
                device_name=device_name,
                mac_address=device_mac,
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

    def get_gemini_mode(self) -> str:
        """
        Get the current system mode for Gemini context injection.
        
        Derives mode from NavigationEngine state + user flags.
        Returns one of: IDLE, OUTDOOR_NAV, INDOOR_NAV, BUS_WATCH, TRANSIT, EXPLORE
        """
        if self._explore_mode:
            return "EXPLORE"
        if self.nav_engine:
            try:
                from rpi5.layer3_guide.navigation_engine import NavMode, NavState
                nav_mode = getattr(self.nav_engine, 'mode', NavMode.IDLE)
                nav_state = getattr(self.nav_engine, 'state', NavState.INACTIVE)
                if nav_state in (NavState.NAVIGATING, NavState.PAUSED):
                    if nav_mode == NavMode.INDOOR:
                        return "INDOOR_NAV"
                    elif nav_mode == NavMode.TRANSIT:
                        return "TRANSIT"
                    else:
                        return "OUTDOOR_NAV"
                elif nav_state in (NavState.WAITING_FOR_BUS,):
                    return "BUS_WATCH"
                elif nav_state == NavState.ON_VEHICLE:
                    return "TRANSIT"
                elif nav_mode == NavMode.BUS_STOP:
                    return "BUS_WATCH"
            except Exception:
                pass
        return "IDLE"

    def _on_nav_arrival(self):
        """Callback when NavigationEngine reaches the destination — play arrival sound."""
        try:
            # Spatial audio beacon SCRAPPED — use TTS arrival confirmation
            if self.tts:
                run_async_safe(
                    self.tts.speak_async("You have reached your destination."),
                    blocking=False,
                )
            logger.info("🎵 Arrival announcement triggered")
        except Exception as e:
            logger.debug(f"Arrival callback error: {e}")

    async def _start_navigation_and_respond(
        self,
        origin: str,
        destination: str,
        source_label: str = "",
        speak: bool = True,
    ):
        """
        Unified navigation start helper.

        Handles the common boilerplate across all entrypoints:
        - call nav_engine.start_navigation()
        - build distance/duration response string
        - optional TTS speak
        - log consistently

        Returns (success: bool, response: str).
        """
        if not self.nav_engine:
            return False, "Navigation engine is not available."

        try:
            success = await self.nav_engine.start_navigation(origin, destination)
            if success:
                route = self.nav_engine.route
                if route:
                    dist_str = f"{route.total_distance_m:.0f} meters"
                    dur_str = f"{route.total_duration_s / 60:.0f} minutes" if route.total_duration_s else ""
                    if source_label:
                        response = (
                            f"Route to {destination}: {dist_str}, {dur_str}. "
                            f"Navigation started from {source_label}."
                        )
                    else:
                        response = (
                            f"Getting directions to {destination}. "
                            f"Route found. {dist_str}. {dur_str}. Navigation started."
                        )
                else:
                    response = f"Navigation started to {destination}."
                logger.info(f"🧭 [NAV] SUCCESS: {response}")
                if speak and self.tts:
                    await self.tts.speak_async(response)
                return True, response
            else:
                response = f"Sorry, I couldn't find a walking route to {destination}."
                logger.warning(f"🧭 [NAV] FAILED: origin='{origin}', dest='{destination}'")
                if speak and self.tts:
                    await self.tts.speak_async(response)
                return False, response
        except Exception as e:
            logger.error(f"🧭 [NAV] Error starting navigation: {e}")
            response = "Sorry, there was an error getting directions."
            if speak and self.tts:
                await self.tts.speak_async(response)
            return False, response

    def _on_nav_mode_change(self, new_mode):
        """Callback when NavigationEngine switches mode (OUTDOOR ↔ INDOOR ↔ TRANSIT)."""
        try:
            from rpi5.layer3_guide.navigation_engine import NavMode
            if new_mode == NavMode.INDOOR:
                logger.info("🏢 Indoor mode — Gemini Guide Mode active")
                if self.scene_detector:
                    self.scene_detector.cooldown_seconds = 3.0  # Narrate more often indoors
                    self.scene_detector.cooldown_navigating = 5.0  # Indoor nav needs frequent updates
                    self.scene_detector.silence_timeout_navigating = 20.0  # Speak up sooner indoors
                # Switch BNO055 to gyro-only (avoid magnetic interference)
                if self.imu and hasattr(self.imu, 'set_gyro_only'):
                    self.imu.set_gyro_only()
            elif new_mode == NavMode.TRANSIT:
                logger.info("🚌 Transit mode — reduced processing")
                if self.scene_detector:
                    self.scene_detector.cooldown_seconds = 15.0  # Less narration on vehicle
            elif new_mode == NavMode.OUTDOOR:
                logger.info("🌳 Outdoor mode")
                if self.scene_detector:
                    self.scene_detector.cooldown_seconds = 5.0  # Normal cooldown
                    self.scene_detector.cooldown_navigating = 15.0  # Outdoor nav standard
                    self.scene_detector.silence_timeout_navigating = 120.0  # Outdoor: less interruption
                # Switch BNO055 back to NDOF (full 9-axis fusion)
                if self.imu and hasattr(self.imu, 'set_ndof_mode'):
                    self.imu.set_ndof_mode()
        except Exception as e:
            logger.debug(f"Nav mode change error: {e}")

    def _on_nav_event_gemini(self, event: str, details: dict):
        """
        Forward navigation events to Gemini Live as [NAV_EVENT] context messages.
        Called by NavigationEngine.on_nav_event at key navigation moments.

        Critical events (road_crossing, approaching_destination, indoor_mode)
        trigger a Gemini response. Routine events are absorbed silently.
        """
        if not self.layer2 or not self.layer2.is_running:
            return
        if self._gemini_is_live_31():
            self._log_gemini_background_turn_skipped(f"nav_event:{event}")
            return
        try:
            # Build event message for Gemini
            detail_parts = [f"{k}={v}" for k, v in details.items() if v]
            detail_str = ", ".join(detail_parts) if detail_parts else ""
            msg = f"[NAV_EVENT] {event}"
            if detail_str:
                msg += f" | {detail_str}"

            # Critical events → trigger Gemini response (describe what you see)
            critical_events = {
                "road_crossing", "approaching_destination", "arrived",
                "indoor_mode_activated", "approaching_turn",
                "leg_started",
            }
            # navigating_to is context-only — Cartesia speaks the route summary
            # first, then we explicitly prompt Gemini after TTS finishes
            if event == "navigating_to":
                dest = details.get("destination", "destination")
                msg += (
                    f"\nNavigation to {dest} has started. The system will play "
                    "a Cartesia TTS route summary to the user first. "
                    "Wait until prompted before speaking."
                )
                self.layer2.send_context(msg)
            elif event in critical_events:
                if event == "indoor_mode_activated":
                    msg += (
                        "\nGPS lost — user is INDOORS. You are now the PRIMARY NAVIGATOR. "
                        "Give SHORT voice commands: 'door left', 'straight ahead', 'stairs right'. "
                        "Read signs, exit markers, and room labels from camera. "
                        "Do NOT describe the scene. GUIDE with short voice commands."
                    )
                    # Send current camera frame so Gemini can SEE the indoor environment
                    if self.camera:
                        try:
                            _frame = self.camera.get_frame()
                            self._send_gemini_video(_frame)
                        except Exception:
                            pass  # best-effort — text still goes through
                elif event == "leg_started":
                    msg += "\nBriefly tell the user what this next leg involves."
                else:
                    msg += "\nBriefly describe what you see to help the user."
                if self._gemini_background_turns_allowed():
                    self.layer2.send_text(msg)
                    if self.gemini_audio_player and not self.gemini_audio_player.is_playing:
                        self.gemini_audio_player.start()
                else:
                    self._log_gemini_background_turn_skipped(f"nav_event:{event}")
            else:
                # Routine events → silent context absorption
                self.layer2.send_context(msg)

            logger.info(f"🧭➡️🤖 Gemini nav event: {event} ({detail_str})")
        except Exception as e:
            logger.debug(f"Nav event Gemini forward error: {e}")

    def _is_gemini_live_online(self) -> bool:
        """Return True when the Gemini Live session is connected.

        Used by NavigationEngine to decide whether to suppress its own
        voice output (Gemini narrates while online).
        """
        try:
            return bool(
                self.layer2
                and getattr(self.layer2, "is_running", False)
                and getattr(self.layer2, "handler", None)
                and getattr(self.layer2.handler, "is_connected", False)
            )
        except Exception:
            return False

    def _on_gemini_reconnected(self):
        """Called after each Gemini Live API (re)connection.

        Sends an initial video frame so Gemini has visual context.
        Schedules a delayed context injection only on runtimes that support
        silent mid-session context.
        Runs on Gemini's background thread.
        """
        try:
            import time
            # Record connect time so periodic context waits before firing
            self._last_gemini_connect_time = time.time()
            # Reset periodic context timer so it doesn't fire immediately
            self._last_gemini_context_time = time.time()

            # Send an initial video frame FIRST so Gemini has visual context
            # before any queries arrive. Video data (JPEG) does NOT trigger
            # a model turn — only text input does.
            if self._send_gemini_video(min_interval=0.0):
                logger.info("📤 Sent initial video frame after reconnect")

            # Gemini 3.1 Live does not support mid-session context updates.
            # Keep reconnect lightweight: rely on session resumption and the
            # ambient audio/video stream instead of synthetic context turns.
            connect_time = self._last_gemini_connect_time
            has_handle = (self.layer2 and self.layer2.handler
                          and self.layer2.handler.session_handle)
            supports_mid_session_context = self._gemini_mid_session_context_allowed()
            if self.layer2 and self.layer2.loop and not has_handle and supports_mid_session_context:
                async def _delayed_context_send():
                    import asyncio as _aio
                    await _aio.sleep(5.0)
                    # Verify connection is still the same one (not stale)
                    if getattr(self, '_last_gemini_connect_time', 0) != connect_time:
                        return  # A newer connection superseded this one
                    if not self.layer2 or not self.layer2.is_running:
                        return
                    # Build mode context
                    ctx_parts = ["[CONTEXT] Session state update:"]
                    if self.privacy_mode:
                        mode = "IDLE"
                    else:
                        mode = self.get_gemini_mode()
                    ctx_parts.append(f"[MODE] {mode}")
                    if self.nav_engine:
                        nav_ctx = self.nav_engine.get_context_string()
                        if nav_ctx:
                            ctx_parts.append(nav_ctx)
                    env_label = "indoor" if (self.depth_estimator and hasattr(self.depth_estimator, '_is_indoor') and self.depth_estimator._is_indoor) else "outdoor"
                    ctx_parts.append(f"[ENV] {env_label}")
                    context_msg = "\n".join(ctx_parts)
                    await self.layer2.handler.send_context(context_msg)
                    logger.info(f"📤 Delayed context injection after reconnect: [MODE] {mode}")
                asyncio.run_coroutine_threadsafe(_delayed_context_send(), self.layer2.loop)
            else:
                logger.info("📝 Skipping delayed context (session resumption / Gemini 3.1)")

            logger.info(
                f"📤 Reconnect callback done (context scheduled={'5s' if (not has_handle and supports_mid_session_context) else 'SKIP'})"
            )
        except Exception as e:
            logger.debug(f"Reconnect callback failed: {e}")

    def _update_ai_routing(self, func_name: str, args: dict):
        """Update AI routing state for status display (thread-safe)."""
        import time
        arg_str = ", ".join(f'"{v}"' if isinstance(v, str) else str(v)
                           for v in args.values()) if args else ""
        self._last_tool_call = f'{func_name}({arg_str})'
        self._last_tool_call_time = time.time()
        if self.status_display:
            self.status_display.update_ai(True, self._last_tool_call)

    def _remember_confirmed_voice_query(self, query: str) -> None:
        """Store the latest accepted STT transcript for tool-call verification."""
        self._last_confirmed_voice_query = " ".join((query or "").lower().split())
        self._last_confirmed_voice_query_time = time.time()

    def _tokenize_intent_text(self, text: str) -> List[str]:
        """Tokenize free-form user text for lightweight intent matching."""
        return [token for token in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(token) > 1]

    def _recent_query_supports_tool_call(self, name: str, args: Dict[str, Any], max_age_s: float = 12.0) -> bool:
        """Allow high-impact Gemini tools only when recent STT confirms user intent."""
        if name not in {"start_outdoor_navigation", "guide_indoor", "start_navigation_with_route"}:
            return True

        query = self._last_confirmed_voice_query
        if not query or (time.time() - self._last_confirmed_voice_query_time) > max_age_s:
            logger.warning(f"⚠️ Blocking {name}: no recent confirmed STT query")
            return False

        query_tokens = set(self._tokenize_intent_text(query))
        outdoor_phrases = (
            "navigate to", "take me to", "directions to", "go to",
            "how do i get to", "route to", "bring me to"
        )
        indoor_phrases = (
            "guide me to", "lead me to", "help me get to", "take me to",
            "bring me to", "find the", "where is the", "show me the",
            "get me to", "get me out of", "get me through", "guide me through",
            "help me through", "help me out of", "take me out of", "lead me through"
        )
        if name == "start_navigation_with_route":
            destination = str(args.get("destination_name", "") or "").strip().lower()
        else:
            destination = str(args.get("destination", "") or "").strip().lower()
        destination_tokens = [
            token for token in self._tokenize_intent_text(destination)
            if token not in {"the", "a", "an", "my", "me", "to", "please"}
        ]
        if name == "guide_indoor":
            required_phrases = indoor_phrases
            indoor_motion_tokens = {"guide", "lead", "help", "take", "bring", "get", "find", "show", "navigate"}
            indoor_context_tokens = {"room", "living", "bedroom", "kitchen", "bathroom", "hall", "hallway", "corridor", "door", "exit", "through", "outside", "out", "there"}
        else:
            # Both start_outdoor_navigation and start_navigation_with_route
            # require an outdoor-nav intent phrase in recent STT
            required_phrases = outdoor_phrases
        phrase_match = any(phrase in query for phrase in required_phrases)
        if name == "guide_indoor" and not phrase_match:
            if destination_tokens and any(token in query_tokens for token in indoor_motion_tokens):
                phrase_match = True
            elif any(token in query_tokens for token in indoor_motion_tokens) and any(token in query_tokens for token in indoor_context_tokens):
                phrase_match = True
        if not phrase_match:
            logger.warning(
                f"⚠️ Blocking {name}: recent STT '{query[:80]}' does not confirm the required user intent"
            )
            return False
        if destination_tokens and not any(token in query_tokens for token in destination_tokens):
            logger.warning(
                f"⚠️ Blocking {name}: destination '{destination}' was not present in recent STT '{query[:80]}'"
            )
            return False

        return True

    def _handle_gemini_tool_call(self, name: str, args: dict) -> dict:
        """Handle function calls from Gemini Live API.
        
        Called from GeminiLiveHandler's receive loop when Gemini invokes
        a declared function. Runs on Gemini's background thread — only
        access thread-safe data (get_status, _gps_accuracy are safe).
        """
        if name == "get_navigation_state":
            if self.nav_engine:
                return self.nav_engine.get_status()
            return {"state": "inactive", "message": "Navigation engine not available"}

        elif name == "report_obstacle":
            direction = args.get("direction", "unknown")
            distance = args.get("distance_m")
            obj_type = args.get("object_type", "obstacle")
            logger.info(
                f"🚧 Gemini reported obstacle: {obj_type} at {direction}"
                f"{f', ~{distance:.0f}m' if distance else ''}"
            )
            # Phase 1: Acknowledge.
            return {"acknowledged": True, "action": "noted_for_user_warning"}

        elif name == "get_gps_accuracy":
            if self.nav_engine:
                pos = self.nav_engine._get_current_position()
                return {
                    "accuracy_m": round(self.nav_engine._gps_accuracy, 1),
                    "has_fix": pos is not None,
                    "lat": pos[0] if pos else None,
                    "lng": pos[1] if pos else None,
                }
            elif self.gps:
                fix = self.gps.get_fix()
                return {
                    "accuracy_m": getattr(fix, 'accuracy', -1) if fix else -1,
                    "has_fix": fix is not None,
                }
            return {"accuracy_m": -1, "has_fix": False}

        # set_beam_direction SCRAPPED — spatial audio removed
        # Legacy code in rpi5/layer3_guide/spatial_audio/

        elif name == "get_bus_arrival":
            bus_stop_code = args.get("bus_stop_code", "")
            if not bus_stop_code:
                return {"error": "bus_stop_code is required"}
            try:
                from rpi5.layer2_thinker.lta_datamall import get_bus_arrivals
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    # Already in an async context — run sync fallback
                    from rpi5.layer2_thinker.lta_datamall import _get_bus_arrivals_sync, _get_api_key
                    api_key = _get_api_key()
                    if not api_key:
                        return {"error": "LTA_API_KEY not configured"}
                    result = _get_bus_arrivals_sync(bus_stop_code, api_key)
                except RuntimeError:
                    result = asyncio.run(get_bus_arrivals(bus_stop_code))
                logger.info(f"🚌 Bus arrival query for stop {bus_stop_code}: {result.get('summary', '')}")
                return result
            except Exception as e:
                logger.error(f"Bus arrival query failed: {e}")
                return {"error": f"Bus arrival lookup failed: {e}"}

        elif name == "get_nearby_bus_stops":
            try:
                lat = args.get("lat")
                lon = args.get("lon")
                if lat is None or lon is None:
                    # Auto-fill from engine GPS when possible
                    if self.nav_engine:
                        pos = self.nav_engine._get_current_position()
                        if pos:
                            lat, lon = pos[0], pos[1]
                if lat is None or lon is None:
                    return {"error": "lat and lon required and no GPS fix available"}
                radius = float(args.get("radius_m", 500) or 500)
                from rpi5.layer2_thinker.lta_datamall import get_nearby_bus_stops
                self._update_ai_routing("get_nearby_bus_stops", {"lat": lat, "lon": lon, "radius_m": radius})
                result = run_async_safe(
                    get_nearby_bus_stops(float(lat), float(lon), radius),
                    blocking=True,
                )
                return result if result is not None else {"error": "get_nearby_bus_stops returned no result"}
            except Exception as e:
                logger.error(f"get_nearby_bus_stops failed: {e}")
                return {"error": f"Lookup failed: {e}"}

        elif name == "get_all_services_at_stop":
            bus_stop_code = args.get("bus_stop_code", "")
            if not bus_stop_code:
                return {"error": "bus_stop_code is required"}
            try:
                from rpi5.layer2_thinker.lta_datamall import get_all_services_at_stop
                self._update_ai_routing("get_all_services_at_stop", args)
                result = run_async_safe(
                    get_all_services_at_stop(bus_stop_code),
                    blocking=True,
                )
                return result if result is not None else {"error": "get_all_services_at_stop returned no result"}
            except Exception as e:
                logger.error(f"get_all_services_at_stop failed: {e}")
                return {"error": f"Lookup failed: {e}"}

        elif name == "search_places":
            query_str = args.get("query", "")
            if not query_str:
                return {"error": "query is required"}
            try:
                near_lat = args.get("near_lat")
                near_lon = args.get("near_lon")
                if (near_lat is None or near_lon is None) and self.nav_engine:
                    pos = self.nav_engine._get_current_position()
                    if pos:
                        near_lat, near_lon = pos[0], pos[1]
                radius = int(args.get("radius_m", 1000) or 1000)
                maps_key = ""
                if self.nav_engine and getattr(self.nav_engine, "api_key", ""):
                    maps_key = self.nav_engine.api_key
                else:
                    maps_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
                if not maps_key:
                    return {"error": "GOOGLE_MAPS_API_KEY not configured"}
                from rpi5.layer3_guide.gmaps_places import search_places
                self._update_ai_routing("search_places", {"query": query_str})
                result = run_async_safe(
                    search_places(
                        maps_key,
                        query_str,
                        float(near_lat) if near_lat is not None else None,
                        float(near_lon) if near_lon is not None else None,
                        radius,
                    ),
                    blocking=True,
                )
                return result if result is not None else {"error": "search_places returned no result"}
            except Exception as e:
                logger.error(f"search_places failed: {e}")
                return {"error": f"Places search failed: {e}"}

        elif name == "get_directions":
            origin = args.get("origin", "")
            destination = args.get("destination", "")
            mode = (args.get("mode", "walking") or "walking").lower()
            if not origin or not destination:
                return {"error": "origin and destination are required"}
            try:
                # Resolve "current" to GPS lat,lng
                if origin.strip().lower() == "current":
                    if self.nav_engine:
                        pos = self.nav_engine._get_current_position()
                        if pos:
                            origin = f"{pos[0]},{pos[1]}"
                        else:
                            return {"error": "NO_GPS_FIX: cannot resolve 'current'"}
                    else:
                        return {"error": "Navigation engine not available"}

                maps_key = ""
                if self.nav_engine and getattr(self.nav_engine, "api_key", ""):
                    maps_key = self.nav_engine.api_key
                else:
                    maps_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
                if not maps_key:
                    return {"error": "GOOGLE_MAPS_API_KEY not configured"}

                from rpi5.layer3_guide.gmaps_directions import get_directions
                self._update_ai_routing(
                    "get_directions",
                    {"origin": origin, "destination": destination, "mode": mode},
                )
                result = run_async_safe(
                    get_directions(maps_key, origin, destination, mode),
                    blocking=True,
                )
                return result if result is not None else {"error": "get_directions returned no result"}
            except Exception as e:
                logger.error(f"get_directions failed: {e}")
                return {"error": f"Directions lookup failed: {e}"}

        elif name == "start_navigation_with_route":
            destination_name = args.get("destination_name", "")
            waypoints = args.get("waypoints", [])
            metadata = args.get("metadata", {}) or {}
            if not destination_name:
                return {"error": "destination_name is required"}
            if not isinstance(waypoints, list) or len(waypoints) < 2:
                return {"error": "waypoints must be a list with at least 2 [lat, lng] points"}
            if not self._recent_query_supports_tool_call(name, args):
                return {
                    "success": False,
                    "blocked": True,
                    "message": (
                        "Navigation tool call blocked because recent confirmed STT did not "
                        "match this destination. Ask the user to restate the destination clearly."
                    ),
                }
            self._update_ai_routing("start_navigation_with_route", {"destination_name": destination_name})
            if not self.nav_engine:
                return {"error": "Navigation engine not available"}
            logger.info(
                f"🧭 Gemini→start_navigation_with_route('{destination_name}', {len(waypoints)} waypoints)"
            )
            try:
                # Coerce waypoints to list of (lat, lng) tuples
                parsed: List[Tuple[float, float]] = []
                for pt in waypoints:
                    try:
                        parsed.append((float(pt[0]), float(pt[1])))
                    except (TypeError, ValueError, IndexError):
                        continue
                if len(parsed) < 2:
                    return {"error": "waypoints did not parse to at least 2 valid [lat, lng] points"}

                result = run_async_safe(
                    self.nav_engine.start_navigation_with_route(destination_name, parsed, metadata),
                    blocking=True,
                )
                if result:
                    route = self.nav_engine.route
                    dist = f"{route.total_distance_m:.0f}m" if route else ""
                    dur = f"{route.total_duration_s / 60:.0f} min" if (route and route.total_duration_s) else ""
                    return {
                        "success": True,
                        "distance": dist,
                        "duration": dur,
                        "message": f"Navigation started to {destination_name}.",
                    }
                return {"success": False, "message": "Could not activate route on device."}
            except Exception as e:
                logger.error(f"start_navigation_with_route failed: {e}")
                return {"error": f"Navigation handoff failed: {e}"}

        # ── Routing functions — Gemini decides actions ──

        elif name == "start_outdoor_navigation":
            destination = args.get("destination", "")
            if not destination:
                return {"error": "destination is required"}
            if not self._recent_query_supports_tool_call(name, args):
                return {
                    "success": False,
                    "blocked": True,
                    "message": (
                        "Navigation tool call blocked because recent confirmed STT did not "
                        "match this destination. Ask the user to restate the destination clearly."
                    ),
                }
            self._update_ai_routing("start_outdoor_navigation", args)
            if not self.nav_engine:
                return {"error": "Navigation engine not available"}
            logger.info(f"🧭 Gemini→start_outdoor_navigation('{destination}')")
            try:
                # Resolve origin: prefer a live GPS fix, fall back to a saved
                # default only when current position is unavailable.
                origin = "current"
                gps_origin = None
                if self.gps and hasattr(self.gps, 'get_location'):
                    gps_origin = self.gps.get_location()
                if not gps_origin and self.saved_locations:
                    default_loc = self.saved_locations.get_default()
                    if default_loc and default_loc.get("address"):
                        origin = default_loc["address"]
                result = run_async_safe(
                    self.nav_engine.start_navigation(origin, destination),
                    blocking=True
                )
                if result:
                    route = self.nav_engine.route
                    if route:
                        dist = f"{route.total_distance_m:.0f}m"
                        dur = f"{route.total_duration_s / 60:.0f} min" if route.total_duration_s else ""
                        return {
                            "success": True,
                            "distance": dist,
                            "duration": dur,
                            "message": f"Navigation started to {destination}. {dist}, {dur}.",
                        }
                    return {"success": True, "message": f"Navigation started to {destination}."}
                return {"success": False, "message": "Could not find a route. Try a more specific address."}
            except Exception as e:
                logger.error(f"Outdoor navigation failed: {e}")
                return {"error": f"Navigation failed: {e}"}

        elif name == "guide_indoor":
            destination = args.get("destination", "")
            if not self._recent_query_supports_tool_call(name, args):
                return {
                    "success": False,
                    "blocked": True,
                    "message": (
                        "Indoor guidance tool call blocked because recent confirmed STT did not "
                        "support this request. Ask the user to repeat the destination clearly."
                    ),
                }
            self._update_ai_routing("guide_indoor", args)
            logger.info(f"🏢 Gemini→guide_indoor('{destination}')")
            try:
                if not self.nav_engine:
                    return {"success": False, "message": "Navigation engine not available."}

                activated = run_async_safe(
                    self.nav_engine.start_indoor_guidance(destination),
                    blocking=True,
                )
                if not activated:
                    return {
                        "success": False,
                        "mode": "IDLE",
                        "message": f"Could not activate indoor guidance for '{destination}'.",
                    }
                return {
                    "success": True,
                    "mode": "INDOOR_NAV",
                    "message": (
                        f"Indoor guidance activated for '{destination}'. "
                        "You are now the primary navigator. Use the camera feed "
                        "to guide the user with short voice directions. "
                        "Give STEP-BY-STEP instructions: first describe what you see, "
                        "then tell the user which direction to go. Continue guiding "
                        "with multiple instructions until they reach the destination. "
                        "Do NOT stop after one instruction."
                    ),
                }
            except Exception as e:
                logger.error(f"Indoor guidance activation failed: {e}")
                return {
                    "success": False,
                    "mode": "IDLE",
                    "message": f"Indoor guidance activation failed: {e}",
                }

        elif name == "stop_navigation":
            self._update_ai_routing("stop_navigation", {})
            logger.info("🛑 Gemini→stop_navigation()")
            if self.nav_engine:
                try:
                    run_async_safe(self.nav_engine.stop_navigation(), blocking=True)
                    return {"success": True, "message": "Navigation stopped."}
                except Exception as e:
                    logger.error(f"Stop navigation failed: {e}")
                    return {"error": f"Failed to stop navigation: {e}"}
            return {"success": True, "message": "No active navigation to stop."}

        elif name == "search_memory":
            item_name = args.get("item_name", "")
            if not item_name:
                return {"error": "item_name is required"}
            self._update_ai_routing("search_memory", args)
            logger.info(f"🧠 Gemini→search_memory('{item_name}')")
            if self.memory_manager:
                try:
                    result = self.memory_manager.recall(item_name)
                    if result:
                        return {
                            "found": True,
                            "item": item_name,
                            "description": result.get("description", ""),
                            "location": result.get("location_estimate", ""),
                            "timestamp": result.get("timestamp", ""),
                        }
                    return {"found": False, "item": item_name, "message": f"No memory found for '{item_name}'."}
                except Exception as e:
                    logger.error(f"Memory search failed: {e}")
                    return {"error": f"Memory search failed: {e}"}
            return {"found": False, "item": item_name, "message": "Memory system not available."}

        elif name == "set_system_mode":
            mode = args.get("mode", "")
            if mode not in ("PRODUCTION", "DEV"):
                return {"error": f"Invalid mode '{mode}'. Must be PRODUCTION or DEV."}
            self._update_ai_routing("set_system_mode", args)
            logger.info(f"⚙️ Gemini→set_system_mode('{mode}')")
            try:
                self.set_mode(mode)
                return {"success": True, "mode": mode, "message": f"Switched to {mode} mode."}
            except Exception as e:
                logger.error(f"Mode switch failed: {e}")
                return {"error": f"Mode switch failed: {e}"}

        return {"error": f"Unknown function: {name}"}

    def start(self):
        """Start main system loop"""
        logger.info("🚀 Starting Asirive Cortex v2.0...")

        self.running = True

        # Start camera
        self.camera_available = False
        try:
            self.camera.start()
            # Verify the camera can actually produce frames (not just open)
            time.sleep(0.3)  # Give capture thread time to spin up
            test_frame = self.camera.get_frame()
            if test_frame is None:
                raise RuntimeError("Camera opened but cannot read frames — lens covered, cable loose, or wrong driver")
            logger.info(f"📷 Camera verified: {test_frame.shape[1]}x{test_frame.shape[0]} frame received")
            self.camera_available = True
        except Exception as e:
            logger.error(f"❌ Camera startup failed: {e}")
            # If USB camera fails, try CSI/picamera2 fallback
            if self._using_usb_camera and CameraHandler:
                logger.info("🔄 Falling back to CSI camera (picamera2)...")
                try:
                    if self.camera:
                        self.camera.stop()
                    cam_cfg = self.config.get('camera', {})
                    self.camera = CameraHandler(
                        camera_id=cam_cfg.get('device_id', 0),
                        use_picamera=True,
                        resolution=tuple(cam_cfg.get('resolution', [640, 480])),
                        fps=cam_cfg.get('fps', 30),
                        rotation=cam_cfg.get('rotation', 0),
                        pixel_format=cam_cfg.get('format', 'RGB888'),
                    )
                    self.camera.start()
                    time.sleep(0.3)
                    test_frame = self.camera.get_frame()
                    if test_frame is not None:
                        logger.info(f"📷 CSI camera verified: {test_frame.shape[1]}x{test_frame.shape[0]} frame received")
                        self._using_usb_camera = False
                        self.camera_available = True
                    else:
                        logger.error("❌ CSI camera also cannot read frames")
                except Exception as e2:
                    logger.error(f"❌ CSI camera fallback failed: {e2}")
            if not self.camera_available:
                logger.warning("⚠️ Running in NO-CAMERA mode — detection/vision disabled, audio-only features active")

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
            layer2_cfg = self.config.get('layer2', {})
            config_key = layer2_cfg.get('gemini_api_key', '')
            env_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
            api_key = config_key or env_key
            if api_key and not api_key.startswith("YOUR_"):
                try:
                    # GeminiLiveManager.start() launches background thread (non-blocking)
                    self.layer2.start()
                    # Audio player starts lazily on first Gemini audio chunk
                    # via _on_gemini_audio → add_audio_chunk → auto-start.
                    # Do NOT start it here — premature start sets is_playing=True
                    # which triggers echo suppression and suppresses all speech.
                    logger.info("✅ Gemini Live API started (background thread)")
                except Exception as e:
                    logger.warning(f"⚠️ Gemini Live API failed: {e}")
            else:
                logger.info("ℹ️ Gemini Live API skipped (invalid or missing API key)")
        elif self.layer2:
            logger.info("ℹ️ Gemini Live API disabled via GEMINI_LIVE_ENABLED=false")
        
        # Set default mode to PRODUCTION
        # This handles: Bluetooth init, voice coordinator start, layer thresholds
        self.set_mode("PRODUCTION")

        # Start hardware peripherals
        if self.gps:
            self.gps.start()
        if self.imu:
            self.imu.start()
        if self.button:
            self.button.start()

        # BusHandler doesn't need start() — it uses start_monitoring(lat, lng)
        # which is called on-demand when the user asks about buses
        if self.bus_handler:
            logger.info("✅ BusHandler ready (will activate on bus query)")

        # Start connectivity monitor
        if self.connectivity_monitor:
            try:
                run_async_safe(self.connectivity_monitor.start())
            except Exception as e:
                logger.warning(f"⚠️ ConnectivityMonitor start failed: {e}")

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

        if self.session_recorder:
            if self.session_recorder.start_on_init:
                self._toggle_session_recording()
            self._start_recording_hotkey_listener()

        # Main loop
        self._main_loop()

    def _main_loop(self):
        """Main processing loop"""
        fps_tracker = []
        last_sync_time = time.time()
        last_metrics_time = time.time()
        last_sensor_time = time.time()

        try:
            while self.running:
                loop_start = time.time()

                # Privacy mode: skip all vision, keep sensors running
                if self.privacy_mode or not self.camera_available:
                    time.sleep(0.5)
                    continue

                # 1. Get frame from camera
                frame, frame_seq = self.camera.get_frame_with_seq(self._last_processed_frame_seq)
                if frame is None:
                    time.sleep(0.01)
                    continue
                self._last_processed_frame_seq = frame_seq
                if self.session_recorder:
                    self.session_recorder.write_video_frame(frame)

                # 1b. Camera blocked detection (all-dark frame for >3 seconds)
                avg_brightness = frame.mean()
                if avg_brightness < 10:  # Very dark frame
                    if self._camera_blocked_since == 0.0:
                        self._camera_blocked_since = time.time()
                    elif time.time() - self._camera_blocked_since > 3.0 and not self._camera_blocked_warned:
                        self._camera_blocked_warned = True
                        if self.tts:
                            run_async_safe(self.tts.speak_async(
                                "My camera seems blocked. Can you check it? I can't see obstacles, so please use your cane."
                            ))
                        logger.warning("📷 Camera blocked detected — dark frames for >3s")
                else:
                    if self._camera_blocked_warned:
                        self._camera_blocked_warned = False
                        if self.tts:
                            run_async_safe(self.tts.speak_async("Camera's working again."))
                    self._camera_blocked_since = 0.0

                # 2. Run Layer 0 + Layer 1 in parallel
                all_detections = self._run_dual_detection(frame)

                # 2b. Depth + hazard detection
                # IVP priority: ToF (close-range, glasses-mounted) → Hailo (monocular, fallback)
                depth_map = None
                hazards = []

                # ── Try VL53L5CX ToF first ──
                if self.tof_handler and self.tof_handler.is_available:
                    try:
                        hazards = self.tof_handler.update()
                        if hazards:
                            logger.debug(f"[ToF] {len(hazards)} hazards: "
                                         f"{', '.join(h.type.value for h in hazards)}")
                        # Simple depth map reconstruction for compatibility
                        raw_mm = self.tof_handler.get_depth_mm()
                        if np.any(raw_mm > 0):
                            depth_map = raw_mm.astype(np.float32) / 1000.0  # mm -> m
                    except Exception as e:
                        logger.debug(f"ToF update error: {e}")

                # ── Fallback to Hailo monocular depth ──
                if not hazards and self.depth_estimator and self.depth_estimator.is_available:
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
                            # Classify indoor/outdoor every ~5 seconds
                            now_env = time.time()
                            if now_env - self._last_env_check > 5.0:
                                self._last_env_check = now_env
                                env = self.depth_estimator.classify_environment(depth_map)
                                is_indoor = (env == "indoor")
                                self.depth_estimator.set_environment(is_indoor)
                                if self.safety_monitor:
                                    self.safety_monitor.set_environment(is_indoor)
                                # Notify Gemini on indoor transition during active nav
                                is_nav_active_now = (
                                    self.nav_engine
                                    and hasattr(self.nav_engine, 'state')
                                    and self.nav_engine.state.value == "navigating"
                                )
                                if is_indoor and not self._was_indoor and is_nav_active_now:
                                    if self.layer2 and self.layer2.is_running:
                                        self._send_gemini_video(frame)
                                        indoor_prompt = (
                                            "[INDOOR_GUIDE] GPS lost — user is INDOORS while navigating. "
                                            "You are now the PRIMARY NAVIGATOR. "
                                            "Give SHORT voice commands: 'door on your left', 'go straight', 'stairs right'. "
                                            "Read signs, exit markers, and room labels from camera. "
                                            "Do NOT describe the scene — GUIDE the user out."
                                        )
                                        if self._gemini_background_turns_allowed():
                                            self.layer2.send_text(indoor_prompt)
                                            if self.gemini_audio_player and not self.gemini_audio_player.is_playing:
                                                self.gemini_audio_player.start()
                                            logger.info("🏢 Indoor + navigating → Gemini indoor guide mode activated")
                                        else:
                                            guided = self._send_proactive_gemini_guidance(
                                                indoor_prompt,
                                                reason="indoor_transition",
                                                signature="indoor_transition",
                                                frame=frame,
                                                min_interval=12.0,
                                            )
                                            if not guided:
                                                self._log_gemini_background_turn_skipped("indoor_transition")
                                self._was_indoor = is_indoor
                    except Exception as e:
                        logger.warning(f"Depth processing error: {e}")

                # 2c. Safety Monitor: fuse YOLO + Hailo depth → tiered alerts
                if self.safety_monitor:
                    try:
                        alert = self.safety_monitor.process_frame(
                            all_detections, hazards, depth_map, frame.shape
                        )
                        if alert:
                            # DON'T interrupt Gemini audio — safety uses haptic + TTS
                            # Gemini Live audio is prioritized over safety TTS

                            # 3D-positioned warning sound
                            if alert.position_3d:
                                sa = None
                                if self.navigator and hasattr(self.navigator, 'spatial_audio'):
                                    sa = self.navigator.spatial_audio
                                elif self.nav_engine and hasattr(self.nav_engine, 'spatial_audio'):
                                    sa = self.nav_engine.spatial_audio
                                elif self.spatial_audio:
                                    sa = self.spatial_audio
                                if sa:
                                    urgency = "critical" if alert.tier == 1 and alert.needs_haptic else (
                                        "warning" if alert.tier <= 2 else "notice"
                                    )
                                    sa.play_directional_alert(alert.position_3d, alert.alert_type, urgency)

                            # TTS voice for first-time Tier 1 hazards
                            if alert.needs_tts and self.audio_alerts:
                                self.audio_alerts.play(alert.alert_type, distance_m=alert.distance_m)

                            # Haptic pulse for critical Tier 1
                            if (alert.needs_haptic
                                and self.layer0 and hasattr(self.layer0, 'haptic')
                                and self.layer0.haptic):
                                try:
                                    self.layer0.haptic.pulse(intensity=100, duration=0.3)
                                except Exception as e:
                                    logger.debug(f"Haptic pulse error: {e}")

                            # Send alert to laptop dashboard
                            if self.ws_client:
                                self.ws_client.send_safety_alert(
                                    tier=alert.tier,
                                    alert_type=alert.alert_type,
                                    direction=alert.direction,
                                    distance_m=alert.distance_m,
                                    score=alert.score,
                                )

                            # Spatial audio beam override SCRAPPED

                    except Exception as e:
                        logger.error(f"Safety monitor error: {e}")

                # 2d. Update beacon tracking (no per-object pinging)
                if self.navigator and all_detections:
                    try:
                        self.navigator.update_detections(all_detections)
                    except Exception as e:
                        logger.debug(f"Beacon tracking error: {e}")

                # 2d2. Feed YOLO + depth into navigation engine
                if self.nav_engine:
                    try:
                        self.nav_engine.update_vision_context(all_detections, depth_map)
                    except Exception as e:
                        logger.debug(f"Nav vision context error: {e}")

                # 2e. Bus handler: check YOLO for "bus" class
                if self.bus_handler and all_detections:
                    try:
                        self.bus_handler.update_detections(all_detections)
                    except Exception as e:
                        logger.debug(f"Bus detection update error: {e}")

                # 2f. Scene change detection → proactive Gemini indoor guidance
                # Re-enabled only for INDOOR navigation with strict gating so
                # Gemini can volunteer short movement cues without waiting for
                # the user to ask again.
                if self.scene_detector and self.layer2 and self.layer2.is_running:
                    try:
                        avg_depth = None
                        if depth_map is not None:
                            avg_depth = float(depth_map.mean())
                        nav_event = None
                        if self.nav_engine:
                            ctx = self.nav_engine.get_context_string()
                            if "crossing" in ctx.lower():
                                nav_event = "road_crossing"
                        is_navigating = self.nav_engine.state.value if self.nav_engine and hasattr(self.nav_engine, 'state') else False
                        is_nav_active = is_navigating == "navigating" if isinstance(is_navigating, str) else False
                        is_indoor_nav = bool(
                            self.nav_engine
                            and hasattr(self.nav_engine, 'mode')
                            and getattr(self.nav_engine.mode, 'value', self.nav_engine.mode) == 'indoor'
                            and is_nav_active
                        )

                        if is_indoor_nav and self._can_send_proactive_gemini_guidance() and self.scene_detector.should_narrate(all_detections, avg_depth, nav_event, is_nav_active):
                            trigger = self.scene_detector.get_last_trigger()
                            logger.info(f"🎙️ Indoor scene change detected ({trigger}), requesting proactive Gemini guidance")
                            context_parts = []
                            if self.nav_engine:
                                context_parts.append(self.nav_engine.get_context_string())
                            if self.bus_handler:
                                context_parts.append(self.bus_handler.get_context_string())
                            if avg_depth is not None:
                                context_parts.append(f"[DEPTH] avg={avg_depth:.1f}m")

                            trigger_desc = "scene_change"
                            if trigger.startswith("silence:"):
                                trigger_desc = "periodic_update"
                            elif trigger.startswith("depth_change:"):
                                trigger_desc = "environment_change"
                            elif trigger.startswith("nav_event:"):
                                trigger_desc = trigger

                            context_str = "\n".join(context_parts)
                            proactive_prompt = (
                                "[PROACTIVE_GUIDE] Indoor navigation is active. "
                                "Without waiting for the user, give ONE short movement cue based on the current camera view. "
                                "Speak only if there is an immediate navigation-relevant cue such as a doorway, corridor opening, clear path, obstacle, furniture hazard, stairs, wall edge, or target landmark. "
                                "Use direct commands like 'Door ahead slightly left', 'Clear path forward', 'Obstacle right, keep left', 'Turn a little right'. "
                                "Do NOT ask questions. Do NOT describe the whole room. Keep it under 12 words.\n"
                                f"[TRIGGER] {trigger_desc}\n{context_str}"
                            )
                            signature = f"{trigger_desc}|{context_str}"
                            self._send_proactive_gemini_guidance(
                                proactive_prompt,
                                reason=f"scene_change:{trigger_desc}",
                                signature=signature,
                                frame=frame,
                            )
                    except Exception as e:
                        logger.debug(f"Scene change detection error: {e}")

                # 2g. Periodic video frame streaming to Gemini (1 FPS)
                # Gemini needs continuous visual context to be an effective companion
                # Gate: skip while Gemini is outputting audio — sending frames
                # during a response triggers server-side barge-in detection.
                _vid_audio_playing = (
                    self.voice_coordinator.is_output_playing
                    and self.voice_coordinator.is_output_playing()
                )
                _vid_user_speaking = self._user_speaking_to_gemini
                # Reset timer while gated so frames don't burst on gate-open
                if _vid_audio_playing or _vid_user_speaking:
                    self._last_gemini_frame_time = time.time()
                if self.layer2 and self.layer2.is_running and frame is not None and not _vid_audio_playing and not _vid_user_speaking:
                    now_vid = time.time()
                    if now_vid - self._last_gemini_frame_time >= 1.0:
                        self._send_gemini_video(frame, min_interval=1.0)

                # 2h. Periodic context injection to Gemini (non-3.1 runtimes only)
                # Gate: skip while Gemini is outputting audio — sending text
                # during a response can trigger server-side barge-in.
                _ctx_audio_playing = (
                    self.voice_coordinator.is_output_playing
                    and self.voice_coordinator.is_output_playing()
                )
                if _ctx_audio_playing:
                    # Reset timer while gated so context doesn't fire
                    # immediately when audio ends (avoids stimulus during echo cooldown)
                    self._last_gemini_context_time = time.time()
                if self.layer2 and self.layer2.is_running and not _ctx_audio_playing and self._gemini_mid_session_context_allowed():
                    now_ctx = time.time()
                    # Post-connect cooldown: don't inject context for 15s after
                    # a (re)connection — text triggers turn_complete which kills
                    # fresh sessions before they stabilise.
                    _connect_age = now_ctx - getattr(self, '_last_gemini_connect_time', 0)
                    if _connect_age < 15.0:
                        self._last_gemini_context_time = now_ctx  # keep timer reset
                    if now_ctx - self._last_gemini_context_time >= 30.0:  # was 15.0 — each injection triggers a turn_complete
                        self._last_gemini_context_time = now_ctx
                        try:
                            ctx_parts = []
                            # GPS position
                            if self.gps:
                                gps_fix = self.gps.get_fix() if hasattr(self.gps, 'get_fix') else None
                                if gps_fix and hasattr(gps_fix, 'latitude') and gps_fix.latitude:
                                    ctx_parts.append(
                                        f"[GPS] {gps_fix.latitude:.6f}°N, {gps_fix.longitude:.6f}°E"
                                        f" | sats={getattr(gps_fix, 'satellites', '?')}"
                                        f" | speed={getattr(gps_fix, 'speed_kmh', 0):.1f}km/h"
                                    )
                                else:
                                    ctx_parts.append("[GPS] No fix")
                            # Navigation status
                            if self.nav_engine:
                                ctx_parts.append(self.nav_engine.get_context_string())
                            # Bus handler status
                            if self.bus_handler:
                                bus_ctx = self.bus_handler.get_context_string()
                                if bus_ctx:
                                    ctx_parts.append(bus_ctx)
                            # Mode — drives Gemini proactivity
                            if self.privacy_mode:
                                mode = "IDLE"  # Privacy overrides to quiet
                            else:
                                mode = self.get_gemini_mode()
                            ctx_parts.append(f"[MODE] {mode}")
                            # Battery (if available via power monitor)
                            try:
                                battery_path = Path("/sys/class/power_supply/battery/capacity")
                                if battery_path.exists():
                                    battery_pct = battery_path.read_text().strip()
                                    ctx_parts.append(f"[BATTERY] {battery_pct}%")
                            except Exception:
                                pass
                            # Connectivity
                            if self.connectivity_monitor:
                                ctx_parts.append(f"[SIGNAL] {self.connectivity_monitor.level.name}")
                            # Safety environment
                            env_label = "indoor" if (self.depth_estimator and hasattr(self.depth_estimator, '_is_indoor') and self.depth_estimator._is_indoor) else "outdoor"
                            ctx_parts.append(f"[ENV] {env_label}")
                            # Visible objects summary
                            if all_detections:
                                det_summary = ", ".join(set(d.get('class', '?') for d in all_detections[:10]))
                                ctx_parts.append(f"[VISIBLE] {det_summary}")
                            if depth_map is not None:
                                ctx_parts.append(f"[DEPTH] avg={float(depth_map.mean()):.1f}m")

                            context_str = "\n".join(ctx_parts)
                            self.layer2.send_context(f"[CONTEXT]\n{context_str}")
                        except Exception as e:
                            logger.debug(f"Periodic Gemini context injection error: {e}")

                # 3. Send to laptop dashboard via ZMQ (Hybrid Architecture)
                # Rate-limit to ~10 FPS to save CPU (encode+resize runs per call)
                if self.video_streamer:
                    _now_zmq = time.time()
                    if not hasattr(self, '_last_zmq_frame_time'):
                        self._last_zmq_frame_time = 0.0
                    if _now_zmq - self._last_zmq_frame_time >= 0.1:  # 10 FPS max
                        self._last_zmq_frame_time = _now_zmq
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
                    
                    mem = psutil.virtual_memory()
                    self.ws_client.send_metrics(
                        fps=fps,
                        ram_mb=int(mem.used / 1024 / 1024),
                        ram_percent=mem.percent,
                        cpu_percent=psutil.cpu_percent(),
                        battery_percent=self._get_battery_percent(),
                        temperature=self._get_cpu_temp(),
                        active_layers=["layer0", "layer1"],
                        current_mode="PRODUCTION" if not self.privacy_mode else "PRIVACY"
                    )
                    last_metrics_time = time.time()

                # 6. Stream GPS/IMU sensor data & update TUI (every 1s)
                if time.time() - last_sensor_time > 1.0:
                    try:
                        gps_fix = self.gps.get_fix() if self.gps else None
                        imu_reading = self.imu.get_reading() if self.imu else None

                        # Update TUI status display with sensor data (always, even without WS)
                        if self.status_display:
                            env_label = "unknown"
                            if self.depth_estimator and hasattr(self.depth_estimator, '_is_indoor'):
                                env_label = "indoor" if self.depth_estimator._is_indoor else "outdoor"
                            gps_source = ""
                            if hasattr(self.gps, 'active_source'):
                                gps_source = self.gps.active_source or ""
                            self.status_display.update_gps(gps_fix, environment=env_label, source=gps_source)
                            self.status_display.update_imu(imu_reading)

                        # Bus proximity check (piggyback on GPS poll)
                        if gps_fix and self.bus_handler:
                            try:
                                run_async_safe(self.bus_handler.check_proximity(
                                    gps_fix.latitude, gps_fix.longitude
                                ), blocking=False)
                            except Exception as e:
                                logger.debug(f"Bus proximity check error: {e}")

                        # Auto-start pending navigation once GPS fix arrives
                        if gps_fix and gps_fix.latitude != 0.0 and self._pending_destination and self.nav_engine:
                            dest = self._pending_destination
                            self._pending_destination = None  # Clear before async to avoid re-trigger
                            origin = f"{gps_fix.latitude},{gps_fix.longitude}"
                            logger.info(f"🧭 [NAV] GPS fix acquired — starting queued navigation to {dest} from {origin}")
                            try:
                                async def _start_deferred_nav():
                                    success, response = await self._start_navigation_and_respond(
                                        origin, dest, source_label="GPS fix", speak=False
                                    )
                                    if success and self.tts:
                                        await self.tts.speak_async(f"GPS signal found. {response}")
                                    elif not success and self.tts:
                                        await self.tts.speak_async(f"GPS signal found, but {response}")
                                run_async_safe(_start_deferred_nav(), blocking=False)
                            except Exception as e:
                                logger.error(f"🧭 [NAV] Deferred navigation error: {e}")

                        if self.ws_client and self.ws_client.is_connected and (gps_fix or imu_reading):
                            # Determine current environment
                            env_label = "unknown"
                            if self.depth_estimator and hasattr(self.depth_estimator, '_is_indoor'):
                                env_label = "indoor" if self.depth_estimator._is_indoor else "outdoor"
                            self.ws_client.send_gps_imu(
                                latitude=gps_fix.latitude if gps_fix else 0.0,
                                longitude=gps_fix.longitude if gps_fix else 0.0,
                                altitude=gps_fix.altitude if gps_fix else None,
                                accuracy=None,
                                speed_kmh=gps_fix.speed_kmh if gps_fix else 0.0,
                                heading=gps_fix.heading if gps_fix else 0.0,
                                fix_quality=gps_fix.fix_quality if gps_fix else 0,
                                satellites=gps_fix.satellites if gps_fix else 0,
                                accelerometer=[imu_reading.accel_x, imu_reading.accel_y, imu_reading.accel_z] if imu_reading else None,
                                gyroscope=[imu_reading.gyro_x, imu_reading.gyro_y, imu_reading.gyro_z] if imu_reading else None,
                                magnetometer=[imu_reading.mag_x, imu_reading.mag_y, imu_reading.mag_z] if imu_reading else None,
                                euler=[imu_reading.heading, imu_reading.roll, imu_reading.pitch] if imu_reading else None,
                                calibration=[imu_reading.cal_system, imu_reading.cal_gyro, imu_reading.cal_accel, imu_reading.cal_mag] if imu_reading else None,
                                environment=env_label,
                            )
                        elif self.ws_client and self.ws_client.is_connected:
                            # Always send status even without sensor data so dashboard stays updated
                            env_label = "unknown"
                            if self.depth_estimator and hasattr(self.depth_estimator, '_is_indoor'):
                                env_label = "indoor" if self.depth_estimator._is_indoor else "outdoor"
                            gps_receiving = self.gps.is_receiving if self.gps and hasattr(self.gps, 'is_receiving') else False
                            self.ws_client.send_gps_imu(
                                latitude=0.0,
                                longitude=0.0,
                                fix_quality=-1 if not gps_receiving else 0,
                                satellites=0,
                                environment=env_label,
                            )
                    except Exception as e:
                        logger.debug(f"Sensor streaming error: {e}")
                    last_sensor_time = time.time()

                # 6b. Battery monitoring
                self._check_battery()

                # 6c. IMU head-tracking (spatial audio listener orientation SCRAPPED)
                # Legacy: rpi5/layer3_guide/spatial_audio/

                # 7. Track FPS for Logging and Status Display
                loop_time = time.time() - loop_start
                fps = 1.0 / loop_time if loop_time > 0 else 0
                fps_tracker.append(fps)

                # Throttle FPS status writes to match the live panel refresh cadence.
                if self.status_display and (time.time() - self._last_status_fps_update) >= 0.25:
                    self._last_status_fps_update = time.time()
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

    def _get_battery_percent(self) -> int:
        """Get battery percentage from UPS HAT or return 100 if wall-powered."""
        try:
            # Try common UPS HAT sysfs paths
            for path in [
                "/sys/class/power_supply/battery/capacity",
                "/sys/class/power_supply/BAT0/capacity",
            ]:
                try:
                    with open(path, "r") as f:
                        return int(f.read().strip())
                except FileNotFoundError:
                    continue
            # Try psutil if available
            if hasattr(psutil, 'sensors_battery') and psutil.sensors_battery():
                return int(psutil.sensors_battery().percent)
        except Exception:
            pass
        return 100  # Wall-powered / unknown

    def _check_battery(self):
        """Check battery level and warn at 20%, 10%, 5% thresholds."""
        now = time.time()
        if now - self._last_battery_check < 60.0:  # Check every 60 seconds
            return
        self._last_battery_check = now
        
        pct = self._get_battery_percent()
        if pct <= 5 and 5 not in self._battery_warned:
            self._battery_warned.add(5)
            if self.tts:
                run_async_safe(self.tts.speak_async(
                    "Critical battery. Saving your location."
                ))
            # Save state for resume
            if self.nav_engine and self.nav_engine._breadcrumbs:
                logger.warning(f"🔋 5% — breadcrumb trail has {len(self.nav_engine._breadcrumbs)} points")
        elif pct <= 10 and 10 not in self._battery_warned:
            self._battery_warned.add(10)
            if self.tts:
                run_async_safe(self.tts.speak_async(
                    "Battery at 10 percent. Reduced processing. Navigation still active."
                ))
        elif pct <= 20 and 20 not in self._battery_warned:
            self._battery_warned.add(20)
            if self.tts:
                run_async_safe(self.tts.speak_async(
                    "Battery low. Want me to guide you home?"
                ))

    def _run_dual_detection(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """Run Layer 0 + Layer 1 detection in parallel"""
        detections = []
        new_detection_count = 0
        now = time.time()

        if self.layer0:
            if self._layer0_future is not None:
                if self._layer0_future.done():
                    try:
                        layer0_detections = self._layer0_future.result() or []
                        latency_ms = (now - self._layer0_submit_time) * 1000
                        self._last_layer0_detections = layer0_detections
                        new_detection_count += len(layer0_detections)
                        if self.status_display:
                            self.status_display.update_layer0(layer0_detections, latency_ms)
                    except Exception as e:
                        import traceback
                        logger.error(f"❌ layer0 detection failed: {e}\n{traceback.format_exc()}")
                        self._last_layer0_detections = []
                    finally:
                        self._layer0_future = None
                        self._layer0_timeout_logged = False
                elif (now - self._layer0_submit_time) > 1.0 and not self._layer0_timeout_logged:
                    logger.warning("⚠️ layer0 detection is still running; skipping stale frame submission")
                    self._layer0_timeout_logged = True
                    if self.status_display:
                        self.status_display.update_layer0(
                            self._last_layer0_detections,
                            (now - self._layer0_submit_time) * 1000,
                        )

            if self._layer0_future is None:
                if self._layer0_executor is None:
                    self._layer0_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="layer0")
                self._layer0_submit_time = now
                self._layer0_future = self._layer0_executor.submit(self.layer0.detect, frame)

            detections.extend(self._last_layer0_detections)

        if self.layer1:
            if self._layer1_future is not None:
                if self._layer1_future.done():
                    try:
                        layer1_detections = self._layer1_future.result() or []
                        latency_ms = (now - self._layer1_submit_time) * 1000
                        self._last_layer1_detections = layer1_detections
                        new_detection_count += len(layer1_detections)
                        if self.status_display:
                            self.status_display.update_layer1(layer1_detections, latency_ms)
                    except Exception as e:
                        import traceback
                        logger.error(f"❌ layer1 detection failed: {e}\n{traceback.format_exc()}")
                        self._last_layer1_detections = []
                    finally:
                        self._layer1_future = None
                        self._layer1_timeout_logged = False
                elif (now - self._layer1_submit_time) > 1.0 and not self._layer1_timeout_logged:
                    logger.warning("⚠️ layer1 detection is still running; skipping stale frame submission")
                    self._layer1_timeout_logged = True
                    if self.status_display:
                        self.status_display.update_layer1(
                            self._last_layer1_detections,
                            (now - self._layer1_submit_time) * 1000,
                        )

            if self._layer1_future is None:
                if self._layer1_executor is None:
                    self._layer1_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="layer1")
                self._layer1_submit_time = now
                self._layer1_future = self._layer1_executor.submit(self.layer1.detect, frame)

            detections.extend(self._last_layer1_detections)

        self.detection_count += new_detection_count
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
                ), blocking=False)
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
        query_lower = query.lower().strip()

        # Q&A backlog prevention: if Gemini is currently responding with audio,
        # discard new queries to prevent chain reaction where slow responses
        # pile up and spam the user with stale answers.
        # Allow critical/safety commands through even during playback.
        if (self.voice_coordinator
            and self.voice_coordinator.is_output_playing
            and self.voice_coordinator.is_output_playing()):
            _critical_kws = ["stop", "cancel", "privacy mode", "camera off", "camera on", "help", "emergency"]
            if not any(kw in query_lower for kw in _critical_kws):
                logger.info(f"🔇 Discarding query during Gemini response: '{query[:50]}'")
                return

        # Echo filter: if STT picked up Gemini's own speaker output, discard it
        if (self.layer2
            and hasattr(self.layer2, 'handler')
            and self.layer2.handler.is_echo(query)):
            logger.info(f"🔇 Discarding echo: '{query[:60]}'")
            return

        self._remember_confirmed_voice_query(query)

        if any(kw in query_lower for kw in ["privacy mode", "camera off", "turn off camera", "turn off the camera"]):
            self.privacy_mode = True
            self.camera.stop()
            if self.tts:
                await self.tts.speak_async(
                    "Camera off. Using sensors only. Say camera on to re-enable."
                )
            logger.info("🔒 Privacy mode enabled — camera stopped")
            return

        if any(kw in query_lower for kw in ["camera on", "turn on camera", "turn on the camera", "disable privacy"]):
            self.privacy_mode = False
            self.camera.start()
            if self.tts:
                await self.tts.speak_async("Camera back on. Full system active.")
            logger.info("🔓 Privacy mode disabled — camera restarted")
            return

        # ══════════════════════════════════════════════════════════════════
        # GEMINI-ONLY MODE: When Gemini is connected, ALL queries go
        # directly to Gemini. No local router, no filler filter, no L0/L1.
        # Gemini handles detection, analysis, navigation, greetings, etc.
        # via its function calling and continuous audio/video context.
        # ══════════════════════════════════════════════════════════════════
        gemini_online = (
            self.layer2
            and hasattr(self.layer2, 'is_running')
            and self.layer2.is_running
            and hasattr(self.layer2, 'handler')
            and self.layer2.handler.is_connected
        )

        if gemini_online:
            logger.info(f"🤖 Gemini handling: '{query[:60]}'")
            self._ai_routing_active = True
            if self.status_display:
                self.status_display.update_ai(True, self._last_tool_call)
            logger.info("🎧 Live audio already forwarded to Gemini — suppressing duplicate text resend")
            self._send_gemini_video(min_interval=1.0)
            return

        # ══════════════════════════════════════════════════════════════════
        # GEMINI OFFLINE FALLBACK: Gemini is reconnecting.
        # Only system commands and nav commands work locally.
        # Everything else: tell user to wait.
        # ══════════════════════════════════════════════════════════════════
        logger.info(f"⚠️ Gemini offline — local fallback for: '{query[:60]}'")
        self._ai_routing_active = False
        if self.status_display:
            self.status_display.update_ai(False, "")

        # Check if this is a nav command that can be handled locally
        _nav_command_kws = [
            "navigate to", "take me to", "directions to", "go to",
            "how do i get to", "stop nav", "cancel nav", "cancel route",
            "stop navigation", "cancel navigation",
            "i'm lost", "im lost", "i am lost", "retrace", "take me back",
            "go back", "bus", "next bus", "resume nav", "resume route",
            "continue nav", "continue route", "keep going",
            "where am i", "where are we", "what location", "my location",
            "current location",
        ]
        _has_nav_keyword = any(kw in query_lower for kw in _nav_command_kws)

        # Route locally: only system commands + nav commands
        # Use router ONLY to get routing flags for nav queries
        routing = self.intent_router.route_with_flags(query)
        target_layer = routing["layer"]

        # Force nav keyword queries to layer3
        if _has_nav_keyword and target_layer != "layer3":
            target_layer = "layer3"

        # If not a nav/system command, tell user to wait for Gemini
        if target_layer not in ("layer3",) and not any(kw in query_lower for kw in [
            "privacy mode", "camera off", "turn off camera", "camera on",
            "turn on camera", "disable privacy"
        ]):
            logger.info(f"⏳ Query needs Gemini but it's offline: '{query[:60]}'")
            if self.tts:
                await self.tts.speak_async("One moment, I'm reconnecting.")
            return

        # Privacy mode ON
        if any(kw in query_lower for kw in ["privacy mode", "camera off", "turn off camera", "turn off the camera"]):
            self.privacy_mode = True
            self.camera.stop()
            if self.tts:
                await self.tts.speak_async(
                    "Camera off. Using sensors only. Say camera on to re-enable."
                )
            logger.info("🔒 Privacy mode enabled — camera stopped")
            return

        # Privacy mode OFF
        if any(kw in query_lower for kw in ["camera on", "turn on camera", "turn on the camera", "disable privacy"]):
            self.privacy_mode = False
            self.camera.start()
            if self.tts:
                await self.tts.speak_async("Camera back on. Full system active.")
            logger.info("🔓 Privacy mode disabled — camera restarted")
            return

        # Notify dashboard of audio event
        if self.ws_client:
            try:
                # Send voice command event
                pass  # TODO: Implement send_audio_event on FastAPI client
            except Exception as e:
                logger.debug(f"Audio event send error: {e}")

        frame = self.camera.get_frame()
        if frame is None and target_layer != "layer3":
            logger.warning("⚠️  No frame available")
            # Speak error via TTS
            if self.tts:
                await self.tts.speak_async("I couldn't capture an image from the camera.")
            return

        response = ""

        # =================================================================
        # Pre-routing intercept: follow-up for pending navigation origin
        # When _awaiting_origin is set, the user was asked "where are you?"
        # Their reply (e.g. "home", "I'm at relative's house") may route to
        # any layer, so we intercept here BEFORE the layer dispatch.
        # =================================================================
        if self._awaiting_origin and self.saved_locations:
            location_input = query_lower
            for prefix in ["i'm at ", "im at ", "i am at ", "at ", "from "]:
                if location_input.startswith(prefix):
                    location_input = location_input[len(prefix):]
                    break

            loc = self.saved_locations.resolve(location_input)
            if loc and loc["address"]:
                destination = self._awaiting_origin
                self._awaiting_origin = None
                origin_addr = loc["address"]
                origin_name = loc["name"]
                logger.info(f"📍 User said '{location_input}' → matched '{origin_name}' ({origin_addr})")
                logger.info(f"🧭 [NAV] Follow-up resolved: origin='{origin_name}' ({origin_addr}), destination='{destination}'")
                _, response = await self._start_navigation_and_respond(
                    origin_addr, destination, source_label=origin_name, speak=False
                )
                # TTS and return — skip normal layer routing
                if response and self.tts:
                    await self.tts.speak_async(response)
                logger.info(f"✅ Voice command processed: '{response[:50]}...'")
                return
            elif location_input.strip():
                # User gave a raw address string instead of a saved name
                destination = self._awaiting_origin
                self._awaiting_origin = None
                origin_addr = query  # Use the raw query as address
                logger.info(f"📍 User gave raw address: '{origin_addr}' → navigating to {destination}")
                logger.info(f"🧭 [NAV] Follow-up raw address: origin='{origin_addr}', destination='{destination}'")
                _, response = await self._start_navigation_and_respond(
                    origin_addr, destination, speak=False
                )
                if response and self.tts:
                    await self.tts.speak_async(response)
                logger.info(f"✅ Voice command processed: '{response[:50]}...'")
                return

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
            
            # Speak via TTS (Cartesia cloud preferred — Kokoro CPU starves L0 YOLO)
            if self.tts and response:
                await self.tts.speak_async(response)
            
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
                            await self.tts.speak_async(response)
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
            query_lower = query.lower()
            _nav_just_started = False  # Track if we just started navigation

            # --- GPS Navigation: "navigate to [destination]" ---
            if self.nav_engine and any(kw in query_lower for kw in ["navigate to", "take me to", "directions to", "go to", "how do i get to"]):
                # Extract destination from query
                destination = ""
                for prefix in ["navigate to", "take me to", "directions to", "go to", "how do i get to"]:
                    if prefix in query_lower:
                        destination = query[query_lower.index(prefix) + len(prefix):].strip()
                        break
                if destination:
                    # Get current GPS position
                    gps_fix = self.gps.get_fix() if self.gps else None
                    if gps_fix and gps_fix.latitude != 0.0:
                        origin = f"{gps_fix.latitude},{gps_fix.longitude}"
                        logger.info(f"🧭 [NAV] GPS available — origin={origin}, destination='{destination}'")
                        success, response = await self._start_navigation_and_respond(
                            origin, destination, speak=False
                        )
                        _nav_just_started = success
                    else:
                        # No GPS fix — use saved location as origin
                        default_loc = self.saved_locations.get_default() if self.saved_locations else None
                        if default_loc and default_loc["address"]:
                            origin_addr = default_loc["address"]
                            origin_name = default_loc["name"]
                            logger.info(f"🧭 [NAV] No GPS — using saved location '{origin_name}' as origin: {origin_addr}")
                            success, response = await self._start_navigation_and_respond(
                                origin_addr, destination, source_label=origin_name, speak=False
                            )
                            _nav_just_started = success
                        elif self.saved_locations and self.saved_locations.list_names():
                            # No default location — ask user to pick one
                            self._awaiting_origin = destination
                            places = self.saved_locations.list_names_spoken()
                            logger.info(f"🧭 [NAV] No GPS, no default — asking user. Saved: {places}")
                            response = f"No GPS signal. Where are you right now? Say I'm at {places}, or tell me an address."
                        else:
                            # No saved locations at all — queue for GPS
                            self._pending_destination = destination
                            logger.info(f"🧭 [NAV] No GPS, no saved locations — queued: {destination}")
                            response = f"No GPS signal and no saved locations. I'll start navigation to {destination} once GPS connects."
                else:
                    response = "Where would you like to go? Say navigate to, followed by your destination."

            # --- Stop Navigation ---
            elif self.nav_engine and any(kw in query_lower for kw in ["stop navigation", "stop navigating", "cancel navigation", "cancel route"]):
                await self.nav_engine.stop_navigation()
                response = "Navigation stopped."

            # --- I'm lost / retrace steps ---
            elif self.nav_engine and any(kw in query_lower for kw in ["i'm lost", "im lost", "i am lost", "retrace", "take me back", "go back"]):
                if self.tts:
                    await self.tts.speak_async("Don't worry. Let me work out where you are.")
                # Try GPS reverse geocode for context
                gps_fix = self.gps.get_fix() if self.gps else None
                if gps_fix and gps_fix.latitude != 0.0:
                    # Reverse geocode to tell user where they are
                    try:
                        maps_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')
                        if maps_key:
                            import requests
                            geo_url = "https://maps.googleapis.com/maps/api/geocode/json"
                            geo_resp = requests.get(geo_url, params={
                                'latlng': f"{gps_fix.latitude},{gps_fix.longitude}",
                                'key': maps_key,
                            }, timeout=5)
                            geo_data = geo_resp.json()
                            if geo_data.get('results'):
                                address = geo_data['results'][0].get('formatted_address', '')
                                if address and self.tts:
                                    await self.tts.speak_async(f"You're near {address}.")
                    except Exception as e:
                        logger.debug(f"Reverse geocode error: {e}")

                    success = await self.nav_engine.retrace_steps()
                    if success:
                        response = "I'm guiding you back the way you came."
                    else:
                        response = "I don't have enough trail history. Try saying navigate to, followed by your destination."
                else:
                    response = "I can't get a GPS fix. Stay where you are and try again in a moment."

            # --- Bus queries: "what bus", "bus arrivals", "next bus" ---
            elif self.bus_handler and any(kw in query_lower for kw in ["bus", "what bus", "next bus", "bus arrival", "bus stop"]):
                gps_fix = self.gps.get_fix() if self.gps else None
                if gps_fix and gps_fix.latitude != 0.0:
                    try:
                        await self.bus_handler.start_monitoring(gps_fix.latitude, gps_fix.longitude)
                        # Give time for first query
                        await asyncio.sleep(1.0)
                        context = self.bus_handler.get_context_string()
                        if "No nearby bus stop" in context:
                            response = "I can't find any bus stops nearby. Try moving closer to a road."
                        else:
                            # Extract the useful info from context
                            response = context.replace("[BUS] ", "").replace("[/BUS]", "").strip()
                            if not response:
                                response = "Checking bus arrivals. I'll announce them as they come."
                    except Exception as e:
                        logger.error(f"Bus query error: {e}")
                        response = "Sorry, I couldn't check bus arrivals right now."
                else:
                    response = "I need a GPS fix to find nearby bus stops."

            # --- Resume / continue navigation ---
            elif self.nav_engine and any(kw in query_lower for kw in ["resume nav", "resume route", "continue nav", "continue route", "keep going", "keep navigating"]):
                if self.nav_engine.route and self.nav_engine.state != NavState.NAVIGATING:
                    await self.nav_engine.resume_navigation()
                    response = "Resuming navigation."
                elif self.nav_engine.state == NavState.NAVIGATING:
                    response = "Navigation is already active."
                else:
                    response = "There's no active route to resume. Say navigate to, followed by your destination."

            # --- Where am I: reverse geocode current position ---
            elif any(kw in query_lower for kw in ["where am i", "where are we", "what location", "my location", "current location"]):
                gps_fix = self.gps.get_fix() if self.gps else None
                if gps_fix and gps_fix.latitude != 0.0:
                    try:
                        maps_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')
                        if maps_key:
                            import requests
                            geo_url = "https://maps.googleapis.com/maps/api/geocode/json"
                            geo_resp = requests.get(geo_url, params={
                                'latlng': f"{gps_fix.latitude},{gps_fix.longitude}",
                                'key': maps_key,
                            }, timeout=5)
                            geo_data = geo_resp.json()
                            if geo_data.get('results'):
                                address = geo_data['results'][0].get('formatted_address', '')
                                response = f"You're near {address}."
                            else:
                                response = f"You're at latitude {gps_fix.latitude:.4f}, longitude {gps_fix.longitude:.4f}."
                        else:
                            response = f"You're at latitude {gps_fix.latitude:.4f}, longitude {gps_fix.longitude:.4f}."
                    except Exception as e:
                        logger.warning(f"Reverse geocode error: {e}")
                        response = f"You're at latitude {gps_fix.latitude:.4f}, longitude {gps_fix.longitude:.4f}."
                else:
                    response = "I can't get a GPS fix right now. Stay in an open area and try again."

            # --- Catch-all: Query reached L3 but doesn't match any nav handler ---
            # This happens when Gemini is offline and the query has nav keywords
            # but isn't a specific command. Ask user to try again.
            else:
                response = "I can't process that right now. Try saying navigate to, followed by your destination."
            
            if self.tts and response:
                await self.tts.speak_async(response)

            # After Cartesia speaks the route summary, prompt Gemini to elaborate
            if _nav_just_started and self.layer2:
                if self._gemini_background_turns_allowed():
                    self.layer2.send_text(
                        "[SYSTEM] The route summary was just spoken to the user via TTS. "
                        "Now briefly describe what you see ahead on their path — "
                        "1-2 sentences max. Mention obstacles or people if visible."
                    )
                    if self.gemini_audio_player and not self.gemini_audio_player.is_playing:
                        self.gemini_audio_player.start()
                else:
                    self._log_gemini_background_turn_skipped("post_route_summary")
        
        logger.info(f"✅ Voice command processed: '{response[:50]}...'" if len(response) > 50 else f"✅ Voice command processed: '{response}'")

    def stop(self):
        """Graceful shutdown"""
        turn_count = len(self.conversation_manager.turns) if self.conversation_manager else 0
        print(f"\n[Cortex] Shutting down... ({turn_count} turns saved to SQLite)")
        logger.info("Stopping Asirive Cortex v2.0...")

        self.running = False

        self._stop_recording_hotkey_listener()
        if self.session_recorder:
            self.session_recorder.stop()

        # Stop camera
        self.camera.stop()

        # Disconnect Layer 2
        if self.layer2:
            self.layer2.stop()

        # Stop Gemini audio player
        if self.gemini_audio_player:
            self.gemini_audio_player.stop()

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

        # Stop navigation engine and bus handler
        if self.nav_engine:
            try:
                run_async_safe(self.nav_engine.stop_navigation())
            except Exception as e:
                logger.debug(f"NavigationEngine stop error: {e}")
        if self.bus_handler:
            try:
                run_async_safe(self.bus_handler.stop_monitoring())
            except Exception as e:
                logger.debug(f"BusHandler stop error: {e}")
        if self.connectivity_monitor:
            try:
                run_async_safe(self.connectivity_monitor.stop())
            except Exception as e:
                logger.debug(f"ConnectivityMonitor stop error: {e}")

        # Stop hardware peripherals
        if self.gps:
            self.gps.stop()
        if self.imu:
            self.imu.stop()
        if self.button:
            self.button.stop()

        # Cleanup depth sensors (ToF + Hailo) and OCR
        if self.tof_handler:
            self.tof_handler.stop()
        if self.depth_estimator:
            self.depth_estimator.cleanup()
        if self.audio_alerts:
            self.audio_alerts.cleanup()
        if self.ocr_pipeline:
            self.ocr_pipeline.cleanup()
        if self.layer0 and hasattr(self.layer0, 'cleanup'):
            self.layer0.cleanup()
        if self.layer1 and hasattr(self.layer1, 'cleanup'):
            self.layer1.cleanup()
        if self._layer0_executor is not None:
            self._layer0_executor.shutdown(wait=False, cancel_futures=True)
            self._layer0_executor = None
        if self._layer1_executor is not None:
            self._layer1_executor.shutdown(wait=False, cancel_futures=True)
            self._layer1_executor = None
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

        logger.info("✅ Asirive Cortex v2.0 stopped")
        logger.info(f"📊 Total detections: {self.detection_count}")


# =====================================================
# ENTRY POINT
# =====================================================
def main():
    """Main entry point"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                            ║
║     🧠 Asirive Cortex v2.0 - AI Wearable Assistant         ║
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
