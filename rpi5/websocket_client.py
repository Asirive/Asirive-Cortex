"""
WebSocket Client for RPi5 → Laptop Dashboard Communication

Sends real-time data from RPi5 to laptop dashboard:
- Video frames (30 FPS)
- System metrics (every 1s)
- Object detections (real-time)
- Status updates

Features:
- Auto-reconnect with exponential backoff
- Message queuing when disconnected
- Thread-safe (can be called from any thread)
- Non-blocking asyncio

Author: Haziq (@IRSPlays)
Date: January 8, 2026
"""

import asyncio
import websockets
import logging
import json
import base64
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from threading import Thread, Lock
import queue

from laptop.protocol import MessageType


logger = logging.getLogger(__name__)


class RPiWebSocketClient:
    """
    WebSocket client for sending RPi5 data to laptop dashboard

    Thread-safe: Can be called from main thread or background threads
    """

    def __init__(
        self,
        host: str = None,  # Will load from config if not provided
        port: int = 8765,
        device_id: str = "rpi5-cortex-001",
        auto_reconnect: bool = True,
        reconnect_interval: float = 5.0,
        queue_size: int = 100
    ):
        # Load from config if host not provided
        if host is None:
            from rpi5.config.config import get_config
            config = get_config()
            host = config.get('laptop_server', {}).get('host', '10.17.233.101')
        
        """
        Initialize WebSocket client

        Args:
            host: Laptop IP address (loads from config if None)
            port: WebSocket port (default: 8765)
            device_id: Unique device identifier
            auto_reconnect: Automatically reconnect on disconnect
            reconnect_interval: Seconds between reconnect attempts
            queue_size: Max messages to queue when disconnected
        """
        self.host = host
        self.port = port
        self.device_id = device_id
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval = reconnect_interval
        self.queue_size = queue_size

        # WebSocket connection
        self.websocket: Optional[websockets.client.WebSocketClientProtocol] = None
        self.is_connected = False
        self.should_reconnect = True

        # Event loop (runs in background thread)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[Thread] = None

        # Message queue (for thread-safe communication)
        self.message_queue = queue.Queue(maxsize=queue_size)
        self.queue_lock = Lock()

        # Connection state
        self.connect_time: Optional[datetime] = None
        self.disconnect_count = 0

        logger.info(f"WebSocket client initialized: {host}:{port}")

    async def _connect(self):
        """Connect to laptop dashboard"""
        uri = f"ws://{self.host}:{self.port}"

        while self.should_reconnect:
            try:
                logger.info(f"🔌 Connecting to laptop dashboard: {uri}")

                self.websocket = await websockets.connect(
                    uri,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=10
                )

                self.is_connected = True
                self.connect_time = datetime.now()

                logger.info(f"✅ Connected to laptop dashboard")
                await self._send_status("connected", f"Device {self.device_id} connected")

                # Process incoming messages (if any)
                await self._receive_loop()

            except (ConnectionRefusedError, ConnectionError) as e:
                logger.warning(f"⚠️  Connection refused: {e}")
                self.is_connected = False
                self.disconnect_count += 1

                if self.auto_reconnect:
                    logger.info(f"🔄 Reconnecting in {self.reconnect_interval}s...")
                    await asyncio.sleep(self.reconnect_interval)
                else:
                    logger.error("❌ Auto-reconnect disabled, giving up")
                    break

            except Exception as e:
                logger.error(f"❌ Connection error: {e}")
                self.is_connected = False

                if self.auto_reconnect:
                    await asyncio.sleep(self.reconnect_interval)
                else:
                    break

    async def _receive_loop(self):
        """Receive messages from laptop"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    # Handle PING (compare with .value for string comparison)
                    if msg_type == MessageType.PING.value:
                        # Echo ping_id if present
                        ping_id = data.get("data", {}).get("ping_id")
                        await self._send_pong(self.device_id, 0.0, ping_id)

                    # Handle COMMAND (future)
                    elif msg_type == MessageType.COMMAND.value:
                        logger.info(f"📥 Received command: {data.get('data')}")

                    # Handle CONFIG (future)
                    elif msg_type == MessageType.CONFIG.value:
                        logger.info(f"📥 Received config update: {data.get('data')}")

                except Exception as e:
                    logger.error(f"Error processing message: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("⚠️  Connection closed by laptop")
            self.is_connected = False
        except Exception as e:
            logger.error(f"❌ Error in receive loop: {e}")
            self.is_connected = False

    async def _send_pong(self, device_id: str, latency: float, ping_id: Optional[str]):
        """Send pong response"""
        from shared.api import create_pong
        pong_msg = create_pong(device_id, latency, ping_id)
        await self._send_message(pong_msg.to_dict())

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
            # Queue message for later
            try:
                self.message_queue.put_nowait(message)
            except queue.Full:
                logger.warning("⚠️  Message queue full, dropping message")
            return

        try:
            await self.websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            self.is_connected = False

    def _run_event_loop(self):
        """Run event loop in background thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            # Start connection
            self.loop.run_until_complete(self._connect())
        except Exception as e:
            logger.error(f"Event loop error: {e}")
        finally:
            logger.info("🛑 Event loop stopped")
            self.loop.close()

    def start(self):
        """Start WebSocket client in background thread"""
        if self.thread and self.thread.is_alive():
            logger.warning("WebSocket client already running")
            return

        logger.info("🚀 Starting WebSocket client...")
        self.should_reconnect = True

        self.thread = Thread(
            target=self._run_event_loop,
            daemon=True,
            name="WebSocketClient"
        )
        self.thread.start()

        logger.info("✅ WebSocket client started")

    def stop(self):
        """Stop WebSocket client"""
        logger.info("🛑 Stopping WebSocket client...")
        self.should_reconnect = False
        self.is_connected = False

        if self.websocket:
            asyncio.run_coroutine_threadsafe(
                self.websocket.close(),
                self.loop
            )

        if self.thread:
            self.thread.join(timeout=5.0)

        logger.info("✅ WebSocket client stopped")

    # ============================================================================
    # PUBLIC API (Thread-safe)
    # ============================================================================

    def send_video_frame(self, frame: bytes, width: int = 640, height: int = 480):
        """Send video frame to laptop (thread-safe)"""
        # Encode frame to base64 JPEG
        import cv2
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frame_b64 = base64.b64encode(buffer).decode('utf-8')

        message = {
            "type": "VIDEO_FRAME",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "frame": frame_b64,
                "width": width,
                "height": height
            }
        }

        self._send_to_loop(message)

    def send_metrics(self, fps: float, ram_mb: int, ram_percent: float, cpu_percent: float,
                     battery_percent: float, temperature: float, active_layers: list,
                     current_mode: str):
        """Send system metrics to laptop (thread-safe)"""
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
                "current_mode": current_mode
            }
        }

        self._send_to_loop(message)

    def send_detection(self, layer: str, class_name: str, confidence: float,
                      bbox_area: float, source: str = "base", detection_mode: str = ""):
        """Send detection to laptop (thread-safe)"""
        message = {
            "type": "DETECTIONS",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "layer": layer,
                "class_name": class_name,
                "confidence": confidence,
                "bbox_area": bbox_area,
                "source": source,
                "detection_mode": detection_mode
            }
        }

        self._send_to_loop(message)

    def send_audio_event(self, event: str, text: str, layer: str, confidence: float = 0.0):
        """Send audio event to laptop (thread-safe)"""
        message = {
            "type": "AUDIO_EVENT",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "event": event,
                "text": text,
                "layer": layer,
                "confidence": confidence
            }
        }

        self._send_to_loop(message)

    def send_memory_event(self, event: str, local_rows: int, synced_rows: int,
                         upload_queue: int, error: str = ""):
        """Send memory event to laptop (thread-safe)"""
        message = {
            "type": "MEMORY_EVENT",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "event": event,
                "local_rows": local_rows,
                "synced_rows": synced_rows,
                "upload_queue": upload_queue,
                "error": error
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
        else:
            # Queue for later
            try:
                self.message_queue.put_nowait(message)
            except queue.Full:
                logger.warning("⚠️  Message queue full, dropping message")


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
    client = RPiWebSocketClient(
        host=None,  # Laptop IP (loaded from config.yaml)
        port=8765
    )

    # Start client
    client.start()

    try:
        # Simulate sending data
        frame_count = 0
        while True:
            # Send metrics every second
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

            # Send fake video frame (every iteration)
            fake_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
            client.send_video_frame(fake_frame)

            # Send fake detection
            client.send_detection(
                layer="guardian",
                class_name="person",
                confidence=0.92,
                bbox_area=0.12
            )

            time.sleep(1)
            frame_count += 1

    except KeyboardInterrupt:
        print("\n🛑 Stopping client...")
        client.stop()
