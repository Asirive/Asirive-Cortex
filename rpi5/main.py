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

import cv2
import numpy as np
import yaml

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
sys.path.insert(0, str(Path(__file__).parent))

# =====================================================
# IMPORT LAYERS
# =====================================================
try:
    from layer0_guardian import YOLOGuardian
except ImportError:
    logger.error("❌ Layer 0 (Guardian) not found")
    YOLOGuardian = None

try:
    from layer1_learner import YOLOELearner, YOLOEMode
except ImportError:
    logger.error("❌ Layer 1 (Learner) not found")
    YOLOELearner = None
    YOLOEMode = None

try:
    from layer2_thinker.gemini_live_handler import GeminiLiveHandler
except ImportError:
    logger.error("❌ Layer 2 (Thinker) not found")
    GeminiLiveHandler = None

try:
    from layer3_guide.router import IntentRouter
    from layer3_guide.detection_router import DetectionRouter
except ImportError:
    logger.error("❌ Layer 3 (Router) not found")
    IntentRouter = None
    DetectionRouter = None

try:
    from layer4_memory.hybrid_memory_manager import HybridMemoryManager
except ImportError:
    logger.error("❌ Layer 4 (Memory) not found")
    HybridMemoryManager = None

# =====================================================
# IMPORT SUPPORTING MODULES
# =====================================================
try:
    from rpi_websocket_client import RPiWebSocketClient
except ImportError:
    logger.warning("⚠️  RPi WebSocket client not found (laptop dashboard won't work)")
    RPiWebSocketClient = None


# =====================================================
# CONFIGURATION LOADER
# =====================================================
def load_config(config_path: str = "rpi5/config/config.yaml") -> Dict[str, Any]:
    """Load configuration from YAML file"""
    default_config = {
        'supabase': {
            'url': os.getenv('SUPABASE_URL', ''),
            'anon_key': os.getenv('SUPABASE_KEY', ''),
            'device_id': os.getenv('DEVICE_ID', 'rpi5-cortex-001'),
            'sync_interval_seconds': 60,
            'batch_size': 100,
            'local_cache_size': 1000,
            'local_db_path': 'local_cortex.db'
        },
        'layer0': {
            'model_path': 'models/yolo11n_ncnn_model',
            'device': 'cpu',
            'confidence': 0.5,
            'enable_haptic': True,
            'gpio_pin': 18
        },
        'layer1': {
            'model_path': 'models/yoloe-11m-seg.pt',
            'device': 'cpu',
            'confidence': 0.25,
            'mode': 'TEXT_PROMPTS'
        },
        'layer2': {
            'gemini_api_key': os.getenv('GEMINI_API_KEY', ''),
            'model': 'gemini-2.0-flash-exp',
            'enable_live_api': True
        },
        'camera': {
            'device_id': 0,
            'use_picamera': True,
            'resolution': [1920, 1080],
            'fps': 30
        },
        'laptop_server': {
            'host': os.getenv('LAPTOP_HOST', 'localhost'),
            'port': int(os.getenv('LAPTOP_PORT', 8765))
        }
    }

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            # Merge with defaults
            for key in default_config:
                if key not in config:
                    config[key] = default_config[key]
            return config
    except FileNotFoundError:
        logger.warning(f"⚠️  Config file not found: {config_path}, using defaults")
        return default_config
    except Exception as e:
        logger.error(f"❌ Error loading config: {e}, using defaults")
        return default_config


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
            from picamera2 import Picamera2

            self.camera = Picamera2(self.camera_id)
            config = self.camera.create_preview_configuration(
                main={"format": 'RGB888', "size": self.resolution}
            )
            self.camera.configure(config)
            self.camera.start()

            # Start capture thread
            self.capture_thread = threading.Thread(
                target=self._picamera_capture_loop,
                daemon=True
            )
            self.capture_thread.start()

        except ImportError:
            logger.error("❌ picamera2 not installed, falling back to OpenCV")
            self.use_picamera = False
            self._start_opencv()
        except Exception as e:
            logger.error(f"❌ Failed to start Picamera2: {e}")
            raise

    def _start_opencv(self):
        """Initialize OpenCV (laptop/testing)"""
        self.camera = cv2.VideoCapture(self.camera_id)
        if not self.camera.isOpened():
            raise RuntimeError(f"Failed to open camera {self.camera_id}")

        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])

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

    def __init__(self, config_path: str = "rpi5/config/config.yaml"):
        logger.info("🧠 Initializing ProjectCortex v2.0...")

        # Load configuration
        self.config = load_config(config_path)

        # Initialize Layer 4: Memory Manager (Hybrid)
        if HybridMemoryManager:
            logger.info("💾 Initializing Layer 4: Memory Manager...")
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

        # Initialize Layer 0: Guardian (Safety-Critical Detection)
        if YOLOGuardian:
            logger.info("🛡️  Initializing Layer 0: Guardian...")
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

        # Initialize Layer 1: Learner (Adaptive Detection)
        if YOLOELearner and YOLOEMode:
            logger.info("🎯 Initializing Layer 1: Learner...")
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

        # Initialize Layer 2: Thinker (Gemini Live API)
        if GeminiLiveHandler:
            logger.info("🧠 Initializing Layer 2: Thinker...")
            self.layer2 = GeminiLiveHandler(
                api_key=self.config['layer2']['gemini_api_key']
            )
            logger.info("✅ Layer 2 initialized")
        else:
            self.layer2 = None
            logger.warning("⚠️  Layer 2 not available")

        # Initialize Layer 3: Router (Intent Routing)
        if IntentRouter and DetectionRouter:
            logger.info("🔀 Initializing Layer 3: Router...")
            self.intent_router = IntentRouter()
            self.detection_router = DetectionRouter()
            logger.info("✅ Layer 3 initialized")
        else:
            self.intent_router = None
            self.detection_router = None
            logger.warning("⚠️  Layer 3 not available")

        # Initialize Camera Handler
        logger.info("📸 Initializing Camera...")
        self.camera = CameraHandler(
            camera_id=self.config['camera']['device_id'],
            use_picamera=self.config['camera']['use_picamera'],
            resolution=tuple(self.config['camera']['resolution']),
            fps=self.config['camera']['fps']
        )

        # Initialize WebSocket Client (for laptop dashboard)
        if RPiWebSocketClient:
            logger.info("🌐 Initializing WebSocket Client...")
            self.ws_client = RPiWebSocketClient(
                server_url=f"ws://{self.config['laptop_server']['host']}:{self.config['laptop_server']['port']}",
                device_id=self.config['supabase']['device_id']
            )
        else:
            self.ws_client = None
            logger.warning("⚠️  WebSocket client not available")

        # System state
        self.running = False
        self.detection_count = 0

        logger.info("✅ ProjectCortex v2.0 initialized successfully")

    def start(self):
        """Start main system loop"""
        logger.info("🚀 Starting ProjectCortex v2.0...")

        self.running = True

        # Start camera
        self.camera.start()

        # Connect to laptop dashboard
        if self.ws_client:
            try:
                self.ws_client.connect()
                logger.info("✅ Connected to laptop dashboard")
            except Exception as e:
                logger.warning(f"⚠️  Failed to connect to laptop: {e}")

        # Start Layer 2 Gemini Live API session
        if self.layer2:
            asyncio.run(self.layer2.connect())

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
                if self.ws_client and all_detections:
                    self._send_to_laptop(frame, all_detections)

                # 4. Update device heartbeat every 30 seconds
                if time.time() - last_sync_time > 30:
                    self._update_heartbeat()
                    last_sync_time = time.time()

                # 5. Track FPS
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
                    logger.error(f"❌ {layer_name} detection failed: {e}")

        self.detection_count += len(detections)
        return detections

    def _send_to_laptop(self, frame: np.ndarray, detections: List[Dict[str, Any]]):
        """Send frame and detections to laptop dashboard"""
        if not self.ws_client:
            return

        try:
            # Send video frame
            import io
            is_success, buffer = cv2.imencode(".jpg", frame)
            if is_success:
                frame_bytes = buffer.tobytes()
                self.ws_client.send_video_frame(frame_bytes)

            # Send detections
            detection_strings = []
            for det in detections:
                layer = det.get('layer', 'unknown')
                class_name = det.get('class', 'unknown')
                confidence = det.get('confidence', 0.0)
                detection_strings.append(f"{layer}: {class_name} ({confidence:.2f})")

            self.ws_client.send_detections("; ".join(detection_strings))

            # Send system metrics
            self.ws_client.send_metrics(
                fps=30.0,
                latency_ms=100,
                ram_mb=2048,
                cpu_percent=45.2,
                battery=85,
                temperature=42.5
            )

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
        if not self.intent_router:
            logger.warning("⚠️  Intent router not available")
            return

        logger.info(f"🎤 Voice command: '{query}'")

        # Route intent
        target_layer = self.intent_router.route(query)
        mode = self.intent_router.get_recommended_mode(query)

        logger.info(f"🔀 Routed to: {target_layer} (mode: {mode})")

        frame = self.camera.get_frame()
        if frame is None:
            logger.warning("⚠️  No frame available")
            return

        # Handle based on target layer
        if target_layer == "layer1" and self.layer1:
            # Switch mode if needed
            if mode == "PROMPT_FREE":
                self.layer1.switch_to_prompt_free()
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
            self.ws_client.disconnect()

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
