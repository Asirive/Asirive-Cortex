"""
RPi5 WebSocket Client using Shared API

Uses the shared AsyncWebSocketClient and protocol for
communication with the laptop dashboard.

Features:
- WebSocket connection for real-time video + YOLO data
- REST API client for config/status
- Toggleable video streaming (on/off)
- Auto-reconnect with exponential backoff

Usage:
    from rpi5.fastapi_client import RPi5Client
    client = RPi5Client(
        host="10.17.233.101",  # Laptop IP
        port=8765,
        device_id="rpi5-cortex-001"
    )
    client.start()

Author: Haziq (@IRSPlays)
Date: January 17, 2026
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import websockets
from websockets.exceptions import ConnectionClosed

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import shared API
from shared.api import (
    AsyncWebSocketClient,
    ClientConfig,
    BaseMessage,
    MessageType,
    Detection,
    BoundingBox,
    SystemMetrics,
    create_video_frame,
    create_metrics,
    create_detections,
    create_command,
    parse_message,
)

logger = logging.getLogger(__name__)


class RPi5Client(AsyncWebSocketClient):
    """
    RPi5 client for connecting to laptop dashboard.

    Inherits from shared AsyncWebSocketClient, adding RPi5-specific methods.
    """

    def __init__(
        self,
        host: str = None,  # Will load from config if not provided
        port: int = 8765,
        device_id: str = "rpi5-cortex-001",
        auto_reconnect: bool = True,
        reconnect_delay: float = 5.0,
        video_quality: int = 85,
        max_fps: int = 15,
    ):
        """
        Initialize client.

        Args:
            host: Laptop IP address (loads from config if None)
            port: FastAPI server port
            device_id: Unique device identifier
            auto_reconnect: Automatically reconnect on disconnect
            reconnect_delay: Seconds between reconnect attempts
            video_quality: JPEG quality (1-100)
            max_fps: Maximum video FPS to send
        """
        # Load from config if host not provided
        if host is None:
            from rpi5.config.config import get_config
            config = get_config()
            host = config.get('laptop_server', {}).get('host', '10.17.233.101')
        
        # Build WebSocket URL
        url = f"ws://{host}:{port}/ws/{device_id}"

        # Create shared config
        config = ClientConfig(
            url=url,
            device_id=device_id,
            reconnect_delay=reconnect_delay,
            ping_interval=30.0,
            ping_timeout=10.0,
            message_queue_size=100,
        )

        super().__init__(config)

        self.host = host
        self.port = port
        self.video_quality = video_quality
        self.max_fps = max_fps

        # Video streaming state
        self._send_video = True  # Local toggle
        self._last_frame_time = 0

        # Callbacks
        self.on_command: Optional[Callable[[Dict[str, Any]], None]] = None

        logger.info(f"RPi5 client initialized: {host}:{port} ({device_id})")

    # =========================================================================
    # Abstract Method Implementations (WebSockets)
    # =========================================================================

    async def _connect_impl(self):
        """Connect using websockets library."""
        try:
            logger.info(f"Connecting to WebSocket: {self.config.url}")
            self.websocket = await websockets.connect(
                self.config.url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10
            )
            logger.info("WebSocket connected, waiting for server ready...")

            # Fix: Wait for server to be ready by receiving the first message
            # This ensures the server has accepted and processed our connection
            await asyncio.sleep(0.5)

            logger.info("WebSocket ready for communication")
        except Exception as e:
            logger.error(f"WebSocket connection failed to {self.config.url}: {e}")
            raise

    async def _send_impl(self, message: BaseMessage):
        """Send message over WebSocket."""
        await self.websocket.send(message.to_json())

    async def _disconnect_impl(self):
        """Close WebSocket connection."""
        if self.websocket:
            await self.websocket.close()

    async def _receive_impl(self) -> Optional[BaseMessage]:
        """Receive next message."""
        try:
            async for message in self.websocket:
                return parse_message(message)
        except ConnectionClosed:
            return None
        except Exception:
            return None

    # =========================================================================
    # Message Handlers
    # =========================================================================

    async def _handle_command(self, message: BaseMessage):
        """Handle COMMAND messages from laptop."""
        cmd_data = message.data
        command = cmd_data.get("action")

        logger.info(f"📥 Received COMMAND from laptop: {command}")
        logger.info(f"📥 Full command data: {cmd_data}")  # Changed to INFO for visibility

        # Handle built-in commands
        if command == "START_VIDEO_STREAMING":
            self._send_video = True
            logger.info("🎥 Video streaming ENABLED")
        elif command == "STOP_VIDEO_STREAMING":
            self._send_video = False
            logger.info("🎥 Video streaming DISABLED")
        elif command == "RESTART":
            logger.info("🔄 RESTART command received")
            if self.on_command:
                self.on_command({"action": "restart"})
        elif command == "SET_MODE":
            mode = cmd_data.get("mode")
            logger.info(f"🔄 SET_MODE command: mode='{mode}'")

        # Forward ALL commands to callback (for main.py to handle SET_MODE, TEXT_QUERY, etc.)
        if self.on_command:
            logger.info(f"📡 Forwarding command to on_command callback: {command}")
            self.on_command(cmd_data)
        else:
            logger.warning("⚠️ No on_command callback registered!")

    async def _handle_config(self, message: BaseMessage):
        """Handle CONFIG messages."""
        config_data = message.data
        key = config_data.get("key")
        value = config_data.get("value")

        if key == "video_streaming_enabled":
            self._send_video = bool(value)
            logger.info(f"Video streaming set to: {self._send_video}")

    async def _handle_ping(self, message: BaseMessage):
        """Handle PING - send PONG response."""
        # Use parent's _handle_ping which sends PONG automatically
        await super()._handle_ping(message)

    async def _handle_detections(self, message: BaseMessage):
        """Handle DETECTIONS messages from laptop (Layer 1 GPU inference results)."""
        data = message.data
        source = data.get("source", "unknown")
        
        # Only process detections from laptop
        if source == "laptop":
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            detections = data.get("detections", [])
            inference_time_ms = data.get("inference_time_ms", 0)
            
            for det in detections:
                # Handle different field names (class vs class_name)
                cls = det.get("class", det.get("class_name", "unknown"))
                conf = det.get("confidence", 0)
                
                # Handle both bbox list and individual x1,y1,x2,y2 keys
                if "bbox" in det:
                    bbox = det["bbox"]
                    bbox_str = f"[{int(bbox[0])}, {int(bbox[1])}, {int(bbox[2])}, {int(bbox[3])}]"
                elif "x1" in det:
                    bbox_str = f"[{int(det['x1'])}, {int(det['y1'])}, {int(det['x2'])}, {int(det['y2'])}]"
                else:
                    bbox_str = "[?,?,?,?]"
                
                # Log at DEBUG level (status display shows summary)
                logger.debug(f"[{timestamp}] <laptop> {cls} ({int(conf*100)}%) bbox={bbox_str}")
            
            # Update the interactive status display with Layer 1 detections from laptop
            try:
                from rpi5.main import get_status_display
                status_display = get_status_display()
                if status_display and detections:
                    # Format detections for status display (needs 'class' key)
                    formatted_dets = [
                        {"class": det.get("class", det.get("class_name", "unknown"))}
                        for det in detections
                    ]
                    status_display.update_layer1(formatted_dets, inference_time_ms)
            except ImportError:
                pass  # Status display not available yet

    async def _handle_navigation(self, message: BaseMessage):
        """Handle NAVIGATION messages from laptop."""
        data = message.data
        action = data.get("action", "unknown")
        logger.info(f"📍 Navigation command received: {action}")
        # Forward to Layer 3 spatial audio system if callback registered
        if self.on_command:
            self.on_command({"action": "NAVIGATION", "navigation_data": data})

    async def _handle_spatial_audio(self, message: BaseMessage):
        """Handle SPATIAL_AUDIO messages from laptop."""
        data = message.data
        enabled = data.get("enabled", True)
        logger.info(f"🔊 Spatial audio config received: enabled={enabled}")
        # Forward to command handler
        if self.on_command:
            self.on_command({"action": "SPATIAL_AUDIO", "audio_data": data})

    async def _handle_layer1_response(self, message: BaseMessage):
        """Handle LAYER1_RESPONSE messages from laptop (GPU inference results)."""
        data = message.data
        detections = data.get("detections", [])
        inference_time_ms = data.get("inference_time_ms", 0)
        
        logger.debug(f"📥 LAYER1_RESPONSE: {len(detections)} detections, {inference_time_ms:.1f}ms")
        
        # Update status display with Layer 1 detections from laptop
        try:
            from rpi5.main import get_status_display
            status_display = get_status_display()
            if status_display and detections:
                formatted_dets = [
                    {"class": det.get("class", det.get("class_name", "unknown"))}
                    for det in detections
                ]
                status_display.update_layer1(formatted_dets, inference_time_ms)
        except ImportError:
            pass

    # =========================================================================
    # Public API (RPi5-specific)
    # =========================================================================

    def send_video_frame(
        self,
        frame: np.ndarray,
        detections: List[Dict[str, Any]] = None,
        width: int = None,
        height: int = None,
    ):
        """
        Send video frame with detections to laptop.

        Args:
            frame: OpenCV frame (BGR format)
            detections: List of detection dicts
            width: Frame width (auto-detected if None)
            height: Frame height (auto-detected if None)
        """
        if not self.is_connected or not self._send_video:
            return

        # Rate limiting
        current_time = time.time()
        min_interval = 1.0 / self.max_fps
        if current_time - self._last_frame_time < min_interval:
            return
        self._last_frame_time = current_time

        # Auto-detect dimensions
        if width is None:
            height, width = frame.shape[:2]

        # Convert detections to Detection objects
        detection_objects = None
        if detections:
            detection_objects = []
            for det in detections:
                detection_objects.append(Detection(
                    class_name=det.get("class", "unknown"),
                    confidence=det.get("confidence", 0.0),
                    bbox=BoundingBox(
                        x1=det.get("x1", 0) / width,
                        y1=det.get("y1", 0) / height,
                        x2=det.get("x2", 0) / width,
                        y2=det.get("y2", 0) / height,
                    ),
                    layer=det.get("layer", 0),
                ))

        # Create and send message
        msg = create_video_frame(
            device_id=self.device_id,
            frame_bytes=frame,
            width=width,
            height=height,
            detections=detection_objects,
            quality=self.video_quality,
        )

        if self._async_loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(self.send(msg), self._async_loop)
        else:
            logger.warning("Async loop not active, cannot send video frame")

    def send_metrics(
        self,
        fps: float,
        cpu_percent: float,
        ram_percent: float,
        battery_percent: float = None,
        temperature: float = None,
        inference_time_ms: float = None,
    ):
        """
        Send system metrics to laptop.

        Args:
            fps: Current FPS
            cpu_percent: CPU usage percentage
            ram_percent: RAM usage percentage
            battery_percent: Battery level (if available)
            temperature: CPU temperature (if available)
            inference_time_ms: Last inference time
        """
        metrics = SystemMetrics(
            fps=fps,
            cpu_percent=cpu_percent,
            ram_percent=ram_percent,
            battery_percent=battery_percent,
            temperature=temperature,
            inference_time_ms=inference_time_ms,
        )

        msg = create_metrics(self.device_id, metrics)
        
        if self._async_loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(self.send(msg), self._async_loop)
        else:
            logger.warning("Async loop not active, cannot send metrics")

    def send_detection(
        self,
        class_name: str,
        confidence: float,
        bbox: List[int],  # [x1, y1, x2, y2]
        layer: int = 0,
        width: int = None,
        height: int = None,
    ):
        """
        Send single detection event.

        Args:
            class_name: Detected class name
            confidence: Confidence score (0-1)
            bbox: Bounding box [x1, y1, x2, y2]
            layer: Detection layer (0=Guardian, 1=Learner)
            width: Frame width for normalization
            height: Frame height for normalization
        """
        if width is None or height is None:
            # Use defaults if not provided
            width, height = 640, 480

        detection = Detection(
            class_name=class_name,
            confidence=confidence,
            bbox=BoundingBox(
                x1=bbox[0] / width,
                y1=bbox[1] / height,
                x2=bbox[2] / width,
                y2=bbox[3] / height,
            ),
            layer=layer,
        )

        msg = create_detections(self.device_id, [detection])
        
        if self._async_loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(self.send(msg), self._async_loop)
        else:
            logger.warning("Async loop not active, cannot send detection")

    def set_video_streaming(self, enabled: bool):
        """Enable/disable video streaming (local control)."""
        self._send_video = enabled
        logger.info(f"Video streaming {'enabled' if enabled else 'disabled'}")

    def send_status(self, status: str, message: str):
        """Send status update to laptop."""
        msg = BaseMessage(
            type=MessageType.STATUS,
            data={
                "status": status,
                "message": message,
                "device_id": self.device_id,
            }
        )
        
        if self._async_loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(self.send(msg), self._async_loop)
        else:
            logger.warning("Async loop not active, cannot send status")


# Backwards compatibility alias
CortexFastAPIClient = RPi5Client





# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    import numpy as np

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create client
    client = RPi5Client(
        host=None,  # Laptop IP (loaded from config.yaml)
        port=8765,
        device_id="rpi5-cortex-001"
    )

    def on_command(cmd):
        print(f"Received command: {cmd}")
        if cmd.get("action") == "STOP_VIDEO_STREAMING":
            print("Stopping video streaming...")

    client.on_command = on_command

    # Start client
    client.start()

    try:
        # Simulate sending data
        while True:
            # Send metrics
            client.send_metrics(
                fps=30.0,
                cpu_percent=45.2,
                ram_percent=52.3,
                battery_percent=85,
                temperature=42.5,
                inference_time_ms=15.0,
            )

            # Send fake frame with detections
            fake_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
            detections = [
                {
                    "class": "person",
                    "confidence": 0.92,
                    "x1": 100, "y1": 50, "x2": 300, "y2": 400,
                    "layer": 0
                }
            ]
            client.send_video_frame(fake_frame, detections)

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping client...")
        client.stop()
