"""
FastAPI Client for RPi5 → Laptop Dashboard Communication

Features:
- WebSocket connection for real-time video + YOLO data
- REST API client for config/status
- Toggleable video streaming (on/off)
- Auto-reconnect with exponential backoff

Usage:
    from rpi5.fastapi_client import CortexFastAPIClient
    client = CortexFastAPIClient(host="192.168.0.91", port=8765)
    client.start()

Author: Haziq (@IRSPlays)
Date: January 11, 2026
"""

import asyncio
import base64
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime

import cv2
import numpy as np
import websockets
from websockets.exceptions import ConnectionClosed

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)


class CortexFastAPIClient:
    """
    FastAPI client for RPi5 to connect to laptop dashboard

    Supports:
    - WebSocket for real-time video + YOLO data
    - REST API for control commands
    - Video streaming toggle (save system resources when off)
    """

    def __init__(
        self,
        host: str = "192.168.0.91",
        port: int = 8765,
        device_id: str = "rpi5-cortex-001",
        auto_reconnect: bool = True,
        reconnect_interval: float = 5.0,
        video_quality: int = 85
    ):
        """
        Initialize client

        Args:
            host: Laptop IP address
            port: FastAPI server port
            device_id: Unique device identifier
            auto_reconnect: Automatically reconnect on disconnect
            reconnect_interval: Seconds between reconnect attempts
            video_quality: JPEG quality (1-100)
        """
        self.host = host
        self.port = port
        self.device_id = device_id
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval = reconnect_interval
        self.video_quality = video_quality

        # Connection state
        self.websocket: Optional[websockets.client.WebSocketClientProtocol] = None
        self.is_connected = False
        self.should_reconnect = True
        self.video_streaming_enabled = True  # Can be toggled by laptop

        # Video streaming state
        self._send_video = True  # Local toggle
        self._frame_skip = 0
        self._last_frame_time = 0

        # Event loop
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None

        # Callbacks
        self.on_connect: Optional[Callable] = None
        self.on_disconnect: Optional[Callable] = None
        self.on_command: Optional[Callable[[Dict[str, Any]], None]] = None

        logger.info(f"FastAPI client initialized: {host}:{port} ({device_id})")

    # =========================================================================
    # CONNECTION METHODS
    # =========================================================================

    async def _connect_ws(self):
        """Connect to laptop via WebSocket"""
        uri = f"ws://{self.host}:{self.port}/ws/{self.device_id}"

        while self.should_reconnect:
            try:
                logger.info(f"🔌 Connecting to laptop: {uri}")

                self.websocket = await websockets.connect(
                    uri,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=10
                )

                self.is_connected = True
                logger.info(f"✅ Connected to laptop dashboard")

                # Send initial status
                await self._send_status("connected", f"Device {self.device_id} connected")

                # Notify callback
                if self.on_connect:
                    self.on_connect()

                # Handle incoming messages
                await self._handle_messages()

            except (ConnectionRefusedError, ConnectionError) as e:
                logger.warning(f"⚠️  Connection refused: {e}")
                self.is_connected = False
                self._handle_disconnect()

                if self.auto_reconnect:
                    logger.info(f"🔄 Reconnecting in {self.reconnect_interval}s...")
                    await asyncio.sleep(self.reconnect_interval)
                else:
                    break

            except Exception as e:
                logger.error(f"❌ Connection error: {e}")
                self.is_connected = False
                self._handle_disconnect()

                if self.auto_reconnect:
                    await asyncio.sleep(self.reconnect_interval)
                else:
                    break

    async def _handle_messages(self):
        """Handle incoming WebSocket messages"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "PING":
                        await self._send_pong(data.get("data", {}))

                    elif msg_type == "COMMAND":
                        cmd_data = data.get("data", {})
                        command = cmd_data.get("command")
                        logger.info(f"📥 Received command: {command}")

                        # Handle commands
                        if command == "START_VIDEO_STREAMING":
                            self._send_video = True
                        elif command == "STOP_VIDEO_STREAMING":
                            self._send_video = False
                        elif command == "RESTART":
                            # Trigger restart
                            if self.on_command:
                                self.on_command({"action": "restart"})

                        # Notify callback
                        if self.on_command:
                            self.on_command(cmd_data)

                    elif msg_type == "CONFIG":
                        config_data = data.get("data", {})
                        key = config_data.get("key")
                        value = config_data.get("value")

                        if key == "video_streaming_enabled":
                            self._send_video = bool(value)
                            logger.info(f"📹 Video streaming set to: {self._send_video}")

                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON: {message}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")

        except ConnectionClosed:
            logger.warning("⚠️  Connection closed")
            self.is_connected = False
        except Exception as e:
            logger.error(f"❌ Message handler error: {e}")
            self.is_connected = False

    def _handle_disconnect(self):
        """Handle disconnection"""
        if self.on_disconnect:
            self.on_disconnect()

    async def _send_pong(self, ping_data: Dict[str, Any]):
        """Send pong response"""
        pong_msg = {
            "type": "PONG",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "ping_timestamp": ping_data.get("timestamp"),
                "pong_timestamp": datetime.utcnow().isoformat() + "Z"
            }
        }
        await self._send_message(pong_msg)

    async def _send_status(self, status: str, message: str):
        """Send status message"""
        status_msg = {
            "type": "STATUS",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "status": status,
                "message": message,
                "device_id": self.device_id
            }
        }
        await self._send_message(status_msg)

    async def _send_message(self, message: Dict[str, Any]):
        """Send message to laptop"""
        if not self.is_connected or not self.websocket:
            return

        try:
            await self.websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            self.is_connected = False

    # =========================================================================
    # PUBLIC API (Thread-safe)
    # =========================================================================

    def _run_event_loop(self):
        """Run event loop in background thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self._connect_ws())
        except Exception as e:
            logger.error(f"Event loop error: {e}")
        finally:
            self.loop.close()

    def start(self):
        """Start client in background thread"""
        if self.thread and self.thread.is_alive():
            logger.warning("Client already running")
            return

        logger.info("🚀 Starting FastAPI client...")
        self.should_reconnect = True

        self.thread = threading.Thread(
            target=self._run_event_loop,
            daemon=True,
            name="FastAPIClient"
        )
        self.thread.start()

        logger.info("✅ FastAPI client started")

    def stop(self):
        """Stop client"""
        logger.info("🛑 Stopping FastAPI client...")
        self.should_reconnect = False
        self.is_connected = False

        if self.websocket:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.websocket.close(),
                    self.loop
                )
            except Exception:
                pass

        if self.thread:
            self.thread.join(timeout=5.0)

        logger.info("✅ FastAPI client stopped")

    def set_video_streaming(self, enabled: bool):
        """Enable/disable video streaming (local control)"""
        self._send_video = enabled
        logger.info(f"📹 Video streaming {'enabled' if enabled else 'disabled'}")

        # Notify laptop
        msg_type = "VIDEO_STREAMING_START" if enabled else "VIDEO_STREAMING_STOP"
        if self.is_connected:
            asyncio.run_coroutine_threadsafe(
                self._send_message({
                    "type": msg_type,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": {"device_id": self.device_id}
                }),
                self.loop
            )

    # =========================================================================
    # SEND METHODS
    # =========================================================================

    def send_video_frame(self, frame: np.ndarray, detections: List[Dict[str, Any]] = None,
                         width: int = 640, height: int = 480):
        """
        Send video frame with YOLO detections to laptop

        Only sends if:
        - Connected to laptop
        - Video streaming is enabled (by laptop or locally)
        - Frame rate limiting (max 15 FPS when streaming)
        """
        if not self.is_connected or not self._send_video:
            return

        # Rate limiting
        current_time = time.time()
        if current_time - self._last_frame_time < 0.067:  # ~15 FPS max when streaming
            return
        self._last_frame_time = current_time

        try:
            # Encode frame to JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.video_quality])
            frame_b64 = base64.b64encode(buffer).decode('utf-8')

            # Prepare detection data
            detection_data = []
            if detections:
                for det in detections:
                    detection_data.append({
                        "class": det.get("class", "unknown"),
                        "confidence": det.get("confidence", 0.0),
                        "x1": int(det.get("x1", 0)),
                        "y1": int(det.get("y1", 0)),
                        "x2": int(det.get("x2", 0)),
                        "y2": int(det.get("y2", 0)),
                        "layer": det.get("layer", "unknown")
                    })

            message = {
                "type": "VIDEO_FRAME",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "data": {
                    "frame": frame_b64,
                    "width": width,
                    "height": height,
                    "detections": detection_data,
                    "device_id": self.device_id
                }
            }

            self._send_to_loop(message)

        except Exception as e:
            logger.error(f"Error encoding frame: {e}")

    def send_metrics(self, fps: float, ram_mb: int, ram_percent: float,
                     cpu_percent: float, battery_percent: float, temperature: float,
                     active_layers: List[str], current_mode: str):
        """Send system metrics to laptop"""
        message = {
            "type": "METRICS",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "fps": fps,
                "ram_mb": ram_mb,
                "ram_percent": ram_percent,
                "cpu_percent": cpu_percent,
                "battery_percent": battery_percent,
                "temperature": temperature,
                "active_layers": active_layers,
                "current_mode": current_mode,
                "device_id": self.device_id
            }
        }
        self._send_to_loop(message)

    def send_detection(self, detection: Dict[str, Any]):
        """Send single detection event"""
        message = {
            "type": "DETECTIONS",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                **detection,
                "device_id": self.device_id
            }
        }
        self._send_to_loop(message)

    def send_audio_event(self, event: str, text: str, layer: str, confidence: float = 0.0):
        """Send audio event"""
        message = {
            "type": "AUDIO_EVENT",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "event": event,
                "text": text,
                "layer": layer,
                "confidence": confidence,
                "device_id": self.device_id
            }
        }
        self._send_to_loop(message)

    def _send_to_loop(self, message: Dict[str, Any]):
        """Send message to event loop (thread-safe)"""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._send_message(message),
                self.loop
            )

    # =========================================================================
    # REST API CLIENT
    # =========================================================================

    async def _api_request(self, method: str, endpoint: str, data: Dict = None):
        """Make REST API request to laptop"""
        import aiohttp

        url = f"http://{self.host}:{self.port}/api/v1/{endpoint}"

        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url) as response:
                    return await response.json()
            elif method == "POST":
                async with session.post(url, json=data) as response:
                    return await response.json()

    async def get_status(self) -> Dict[str, Any]:
        """Get dashboard status"""
        return await self._api_request("GET", "status")

    async def get_devices(self) -> Dict[str, Any]:
        """Get connected devices"""
        return await self._api_request("GET", "devices")

    async def start_video_streaming(self) -> Dict[str, Any]:
        """Request to start video streaming"""
        return await self._api_request("POST", "control", {
            "action": "start_video",
            "device_id": self.device_id
        })

    async def stop_video_streaming(self) -> Dict[str, Any]:
        """Request to stop video streaming"""
        return await self._api_request("POST", "control", {
            "action": "stop_video",
            "device_id": self.device_id
        })


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    import time
    import numpy as np

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create client
    client = CortexFastAPIClient(
        host="192.168.0.91",
        port=8765,
        device_id="rpi5-cortex-001"
    )

    def on_command(cmd):
        print(f"Received command: {cmd}")
        if cmd.get("command") == "STOP_VIDEO_STREAMING":
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
                ram_mb=2048,
                ram_percent=52.3,
                cpu_percent=45.2,
                battery_percent=85,
                temperature=42.5,
                active_layers=["layer0", "layer1"],
                current_mode="TEXT_PROMPTS"
            )

            # Send fake frame with detections
            fake_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
            detections = [
                {
                    "class": "person",
                    "confidence": 0.92,
                    "x1": 100, "y1": 50, "x2": 300, "y2": 400,
                    "layer": "layer0"
                }
            ]
            client.send_video_frame(fake_frame, detections)

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n🛑 Stopping client...")
        client.stop()
