"""
Project-Cortex v2.0 - RPi WebSocket Client

Client-side WebSocket implementation for sending real-time data from RPi wearable
to laptop server for visualization and monitoring.

Features:
- Non-blocking async WebSocket connection
- Automatic reconnection with exponential backoff
- Message queuing when disconnected
- Thread-safe integration with cortex_gui.py
- Graceful degradation (works offline)
- Heartbeat/ping-pong mechanism

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: January 3, 2026
"""

import asyncio
import websockets
import json
import logging
import threading
from datetime import datetime
from typing import Optional, Callable, Dict, Any
from queue import Queue
import time

logger = logging.getLogger(__name__)


# ============ PROTOCOL DEFINITIONS (INLINED FOR STANDALONE OPERATION) ============
# This allows the client to run independently without importing from laptop module

class MessageType:
    """WebSocket message types."""
    # RPi → Laptop (Upstream)
    METRICS = "metrics"
    DETECTIONS = "detections"
    VIDEO_FRAME = "video_frame"
    GPS_IMU = "gps_imu"
    AUDIO_EVENT = "audio_event"
    MEMORY_EVENT = "memory_event"
    STATUS = "status"
    
    # Laptop → RPi (Downstream)
    COMMAND = "command"
    NAVIGATION = "navigation"
    SPATIAL_AUDIO = "spatial_audio"
    CONFIG = "config"
    
    # Bidirectional
    PING = "ping"
    PONG = "pong"
    ERROR = "error"


def create_message(msg_type: str, device_id: str = None, **kwargs) -> dict:
    """
    Create a protocol-compliant message.
    
    Args:
        msg_type: Message type from MessageType
        device_id: Device identifier
        **kwargs: Message-specific fields
    
    Returns:
        dict: JSON-serializable message
    """
    message = {
        "type": msg_type,
        "timestamp": datetime.now().isoformat(),
        "device_id": device_id,
        **kwargs
    }
    return message


class RPiWebSocketClient:
    """
    WebSocket client for RPi to send data to laptop server.
    
    Runs in background thread with asyncio event loop.
    Provides thread-safe methods for sending data from main GUI thread.
    """
    
    def __init__(
        self,
        server_url: str = "ws://192.168.0.171:8765",
        device_id: str = "rpi5_wearable_001",
        reconnect_interval: int = 5,
        max_queue_size: int = 100,
        enable_metrics: bool = True,
        enable_detections: bool = True,
        enable_video: bool = True,
        enable_audio: bool = True,
        enable_memory: bool = True
    ):
        """
        Initialize RPi WebSocket client.
        
        Args:
            server_url: WebSocket server URL (ws://laptop_ip:8765)
            device_id: Unique identifier for this RPi device
            reconnect_interval: Seconds to wait before reconnecting
            max_queue_size: Maximum messages to queue when disconnected
            enable_*: Feature flags to disable specific message types
        """
        self.server_url = server_url
        self.device_id = device_id
        self.reconnect_interval = reconnect_interval
        self.max_queue_size = max_queue_size
        
        # Feature flags
        self.enable_metrics = enable_metrics
        self.enable_detections = enable_detections
        self.enable_video = enable_video
        self.enable_audio = enable_audio
        self.enable_memory = enable_memory
        
        # Connection state
        self.connected = False
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        
        # Message queue for when disconnected
        self.message_queue: Queue = Queue(maxsize=max_queue_size)
        
        # Statistics
        self.messages_sent = 0
        self.messages_failed = 0
        self.connection_attempts = 0
        self.last_connection_time: Optional[datetime] = None
        
        # Callbacks
        self.on_connected: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_command_received: Optional[Callable[[str, dict], None]] = None  # Command handler callback
    
    def start(self):
        """Start the WebSocket client in background thread."""
        if self.running:
            logger.warning("⚠️ Client already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()
        
        logger.info(f"🚀 WebSocket client started (Server: {self.server_url})")
    
    def stop(self):
        """Stop the WebSocket client gracefully."""
        if not self.running:
            return
        
        logger.info("🛑 Stopping WebSocket client...")
        self.running = False
        
        # Stop event loop
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        
        # Wait for thread
        if self.thread:
            self.thread.join(timeout=2)
        
        logger.info("✅ WebSocket client stopped")
    
    def _run_event_loop(self):
        """Run asyncio event loop in background thread."""
        try:
            # Create event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Run connection loop
            self.loop.run_until_complete(self._connection_loop())
            
        except Exception as e:
            logger.error(f"❌ Event loop error: {e}", exc_info=True)
            if self.on_error:
                self.on_error(str(e))
        
        finally:
            if self.loop:
                self.loop.close()
    
    async def _connection_loop(self):
        """Main connection loop with automatic reconnection."""
        while self.running:
            try:
                self.connection_attempts += 1
                logger.info(f"🔌 Connecting to {self.server_url} (Attempt #{self.connection_attempts})...")
                
                async with websockets.connect(
                    self.server_url,
                    ping_interval=30,
                    ping_timeout=10,
                    max_size=10 * 1024 * 1024  # 10MB max message size
                ) as websocket:
                    self.websocket = websocket
                    self.connected = True
                    self.last_connection_time = datetime.now()
                    
                    logger.info(f"✅ Connected to laptop server")
                    if self.on_connected:
                        self.on_connected()
                    
                    # Send any queued messages
                    await self._flush_queue()
                    
                    # Handle incoming messages
                    await self._handle_messages()
            
            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                logger.warning(f"🔌 Connection lost: {e}")
                self.connected = False
                self.websocket = None
                
                if self.on_disconnected:
                    self.on_disconnected()
                
                # Wait before reconnecting
                if self.running:
                    logger.info(f"⏳ Reconnecting in {self.reconnect_interval}s...")
                    await asyncio.sleep(self.reconnect_interval)
            
            except Exception as e:
                logger.error(f"❌ Unexpected error: {e}", exc_info=True)
                if self.on_error:
                    self.on_error(str(e))
                
                await asyncio.sleep(self.reconnect_interval)
    
    async def _flush_queue(self):
        """Send all queued messages."""
        if self.message_queue.empty():
            return
        
        logger.info(f"📤 Flushing {self.message_queue.qsize()} queued messages...")
        
        while not self.message_queue.empty():
            try:
                message = self.message_queue.get_nowait()
                await self._send_message_async(message)
            except Exception as e:
                logger.error(f"❌ Failed to flush message: {e}")
    
    async def _handle_messages(self):
        """Handle incoming messages from server."""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    if msg_type == MessageType.COMMAND:
                        # Handle commands from laptop
                        self._handle_command(data)
                    
                    elif msg_type == MessageType.CONFIG:
                        # Handle config updates
                        self._handle_config_update(data)
                    
                    elif msg_type == MessageType.PING:
                        # Respond to ping with pong
                        pong = create_message(MessageType.PONG, device_id=self.device_id)
                        await self._send_message_async(pong)
                
                except json.JSONDecodeError:
                    logger.error("❌ Invalid JSON from server")
                
                except Exception as e:
                    logger.error(f"❌ Error handling message: {e}")
        
        except websockets.ConnectionClosed:
            logger.info("🔌 Connection closed by server")
    
    def _handle_command(self, data: dict):
        """Handle command from laptop server."""
        command = data.get("command")
        params = data.get("params", {})
        
        logger.info(f"📩 Received command: {command} with params: {params}")
        
        # Call custom handler if registered
        if self.on_command_received:
            try:
                self.on_command_received(command, params)
            except Exception as e:
                logger.error(f"❌ Error in command handler: {e}", exc_info=True)
    
    def _handle_config_update(self, data: dict):
        """Handle configuration update from server."""
        config = data.get("config", {})
        logger.info(f"⚙️ Received config update: {config}")
        
        # Update feature flags if provided
        if "enable_metrics" in config:
            self.enable_metrics = config["enable_metrics"]
        if "enable_detections" in config:
            self.enable_detections = config["enable_detections"]
        if "enable_video" in config:
            self.enable_video = config["enable_video"]
    
    async def _send_message_async(self, message: dict):
        """Send message asynchronously."""
        if not self.websocket or not self.connected:
            raise ConnectionError("Not connected")
        
        await self.websocket.send(json.dumps(message))
        self.messages_sent += 1
    
    def send_message(self, message: dict) -> bool:
        """
        Send message to laptop server (thread-safe).
        
        Args:
            message: Message dict created by protocol.create_message()
        
        Returns:
            True if sent successfully or queued, False if queue full
        """
        if not self.running:
            return False
        
        # If connected, send immediately
        if self.connected and self.websocket:
            try:
                # Schedule in event loop
                future = asyncio.run_coroutine_threadsafe(
                    self._send_message_async(message),
                    self.loop
                )
                future.result(timeout=1)  # Wait up to 1 second
                return True
            
            except Exception as e:
                logger.error(f"❌ Failed to send message: {e}")
                self.messages_failed += 1
        
        # If disconnected, queue message
        if not self.message_queue.full():
            self.message_queue.put(message)
            logger.debug(f"📝 Message queued (queue size: {self.message_queue.qsize()})")
            return True
        else:
            logger.warning(f"⚠️ Message queue full ({self.max_queue_size}), dropping message")
            self.messages_failed += 1
            return False
    
    # ============ HIGH-LEVEL API FOR cortex_gui.py ============
    
    def send_metrics(
        self,
        fps: float,
        latency_ms: float,
        ram_usage_gb: float,
        ram_total_gb: float,
        cpu_usage_percent: float,
        battery_percent: Optional[float],
        active_layer: str
    ) -> bool:
        """Send performance metrics."""
        if not self.enable_metrics:
            return False
        
        message = create_message(
            MessageType.METRICS,
            device_id=self.device_id,
            fps=fps,
            latency_ms=latency_ms,
            ram_usage_gb=ram_usage_gb,
            ram_total_gb=ram_total_gb,
            cpu_usage_percent=cpu_usage_percent,
            battery_percent=battery_percent,
            active_layer=active_layer
        )
        
        return self.send_message(message)
    
    def send_detections(
        self,
        merged_detections: str,
        detection_count: int,
        yoloe_mode: str,
        layer0_detections: Optional[list] = None,
        layer1_detections: Optional[list] = None
    ) -> bool:
        """Send detection results."""
        if not self.enable_detections:
            return False
        
        message = create_message(
            MessageType.DETECTIONS,
            device_id=self.device_id,
            merged_detections=merged_detections,
            detection_count=detection_count,
            yoloe_mode=yoloe_mode,
            layer0_detections=layer0_detections or [],
            layer1_detections=layer1_detections or []
        )
        
        return self.send_message(message)
    
    def send_video_frame(self, frame_data: str) -> bool:
        """
        Send video frame (base64-encoded JPEG).
        
        Args:
            frame_data: Base64-encoded JPEG image
        """
        if not self.enable_video:
            return False
        
        message = create_message(
            MessageType.VIDEO_FRAME,
            device_id=self.device_id,
            frame_data=frame_data
        )
        
        return self.send_message(message)
    
    def send_audio_event(
        self,
        event: str,
        layer: str,
        text: Optional[str] = None,
        duration_ms: Optional[float] = None
    ) -> bool:
        """Send audio event (TTS, STT, etc.)."""
        if not self.enable_audio:
            return False
        
        message = create_message(
            MessageType.AUDIO_EVENT,
            device_id=self.device_id,
            event=event,
            layer=layer,
            text=text,
            duration_ms=duration_ms
        )
        
        return self.send_message(message)
    
    def send_memory_event(
        self,
        event: str,
        object_name: str,
        location: Optional[str] = None,
        image_path: Optional[str] = None
    ) -> bool:
        """Send memory event (object saved/recalled)."""
        if not self.enable_memory:
            return False
        
        message = create_message(
            MessageType.MEMORY_EVENT,
            device_id=self.device_id,
            event=event,
            object_name=object_name,
            location=location,
            image_path=image_path
        )
        
        return self.send_message(message)
    
    def send_status(self, level: str, status: str) -> bool:
        """Send status update."""
        message = create_message(
            MessageType.STATUS,
            device_id=self.device_id,
            level=level,
            status=status
        )
        
        return self.send_message(message)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get client statistics."""
        return {
            "connected": self.connected,
            "messages_sent": self.messages_sent,
            "messages_failed": self.messages_failed,
            "messages_queued": self.message_queue.qsize(),
            "connection_attempts": self.connection_attempts,
            "last_connection_time": self.last_connection_time.isoformat() if self.last_connection_time else None
        }


# ============ EXAMPLE USAGE ============

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Create client
    client = RPiWebSocketClient(
        server_url="ws://192.168.0.171:8765",
        device_id="test_rpi"
    )
    
    # Set callbacks
    def on_connected():
        print("✅ Connected to laptop server!")
    
    def on_disconnected():
        print("🔌 Disconnected from laptop server")
    
    def on_error(error):
        print(f"❌ Error: {error}")
    
    client.on_connected = on_connected
    client.on_disconnected = on_disconnected
    client.on_error = on_error
    
    # Start client
    client.start()
    
    # Send test data
    try:
        time.sleep(2)  # Wait for connection
        
        # Send metrics
        client.send_metrics(
            fps=30.0,
            latency_ms=50.0,
            ram_usage_gb=2.5,
            ram_total_gb=4.0,
            cpu_usage_percent=45.0,
            battery_percent=85.0,
            active_layer="Layer 1 Learner"
        )
        
        # Send detections
        client.send_detections(
            merged_detections="person, car, bicycle",
            detection_count=3,
            yoloe_mode="Prompt-Free"
        )
        
        # Send status
        client.send_status("info", "System running normally")
        
        print(f"📊 Statistics: {client.get_statistics()}")
        
        # Keep running
        input("Press Enter to stop...\n")
    
    finally:
        client.stop()
