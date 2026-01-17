"""
FastAPI Server for ProjectCortex Laptop Dashboard

Provides:
- WebSocket endpoint for RPi5 real-time data (video, metrics, detections)
- REST API for control commands
- Thread-safe callbacks for PyQt6 integration

Usage:
    from laptop.fastapi_server import FastAPIServer, run_server
    server = FastAPIServer(host="0.0.0.0", port=8765)
    await server.start()

Author: Haziq (@IRSPlays)
Date: January 11, 2026
"""

import asyncio
import base64
import json
import logging
import sys
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from laptop.config import DashboardConfig

logger = logging.getLogger(__name__)

# ============================================================================
# DATA MODELS
# ============================================================================

class MessageType(str, Enum):
    """Message types for RPi5 communication"""
    VIDEO_FRAME = "VIDEO_FRAME"
    METRICS = "METRICS"
    DETECTIONS = "DETECTIONS"
    AUDIO_EVENT = "AUDIO_EVENT"
    STATUS = "STATUS"
    PING = "PING"
    PONG = "PONG"
    COMMAND = "COMMAND"
    VIDEO_STREAMING_START = "VIDEO_STREAMING_START"
    VIDEO_STREAMING_STOP = "VIDEO_STREAMING_STOP"


class VideoFrameData(BaseModel):
    """Video frame message data"""
    frame: str  # Base64-encoded JPEG
    width: int = 640
    height: int = 480
    detections: List[Dict[str, Any]] = []
    device_id: str = ""


class MetricsData(BaseModel):
    """System metrics message data"""
    fps: float = 0.0
    ram_mb: int = 0
    ram_percent: float = 0.0
    cpu_percent: float = 0.0
    battery_percent: float = 0.0
    temperature: float = 0.0
    active_layers: List[str] = []
    current_mode: str = ""
    device_id: str = ""


class DetectionData(BaseModel):
    """Detection message data"""
    class_name: str = ""
    confidence: float = 0.0
    bbox: List[int] = []
    layer: str = ""
    source: str = "NCNN"
    detection_mode: str = ""
    device_id: str = ""


class ControlRequest(BaseModel):
    """Control command request"""
    action: str
    device_id: str = ""


class StatusResponse(BaseModel):
    """Status response"""
    status: str
    connected_devices: int = 0
    video_streaming_enabled: bool = True
    server_time: str = ""


# ============================================================================
# CONNECTION MANAGER
# ============================================================================

class ConnectionManager:
    """Manages WebSocket connections from RPi5 devices"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}  # device_id -> websocket
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket, device_id: str):
        """Accept and register new connection"""
        await websocket.accept()
        with self._lock:
            self.active_connections[device_id] = websocket
        logger.info(f"Device connected: {device_id} (total: {len(self.active_connections)})")

    async def disconnect(self, device_id: str, reason: str = ""):
        """Unregister connection"""
        with self._lock:
            if device_id in self.active_connections:
                del self.active_connections[device_id]
        logger.info(f"Device disconnected: {device_id} - {reason}")

    async def send_message(self, device_id: str, message: Dict[str, Any]) -> bool:
        """Send message to specific device"""
        with self._lock:
            websocket = self.active_connections.get(device_id)

        if websocket:
            try:
                await websocket.send_json(message)
                return True
            except Exception as e:
                logger.error(f"Error sending to {device_id}: {e}")
                await self.disconnect(device_id, str(e))
        return False

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected devices"""
        disconnected = []
        with self._lock:
            connections = list(self.active_connections.items())

        for device_id, websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {device_id}: {e}")
                disconnected.append(device_id)

        for device_id in disconnected:
            await self.disconnect(device_id, "broadcast failed")

    def get_connected_devices(self) -> List[str]:
        """Get list of connected device IDs"""
        with self._lock:
            return list(self.active_connections.keys())

    def get_connection_count(self) -> int:
        """Get number of connected devices"""
        with self._lock:
            return len(self.active_connections)


# ============================================================================
# FASTAPI SERVER
# ============================================================================

class FastAPIServer:
    """
    FastAPI server for RPi5 communication

    Features:
    - WebSocket endpoint for real-time video/metrics/detections
    - REST API for control commands
    - Thread-safe callbacks for PyQt6 integration
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        config: DashboardConfig = None,
        on_video_frame: Optional[Callable] = None,
        on_metrics: Optional[Callable] = None,
        on_detection: Optional[Callable] = None,
        on_connect: Optional[Callable[[str], None]] = None,
        on_disconnect: Optional[Callable[[str], None]] = None
    ):
        """
        Initialize FastAPI server

        Args:
            host: Server host address
            port: Server port
            config: Dashboard configuration
            on_video_frame: Callback for video frames (device_id, frame_data, width, height, detections)
            on_metrics: Callback for metrics (device_id, metrics_data)
            on_detection: Callback for detections (device_id, detection_data)
            on_connect: Callback for device connect (device_id)
            on_disconnect: Callback for device disconnect (device_id)
        """
        self.host = host
        self.port = port
        self.config = config or DashboardConfig()
        self.on_video_frame = on_video_frame
        self.on_metrics = on_metrics
        self.on_detection = on_detection
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        self.connection_manager = ConnectionManager()
        self.video_streaming_enabled = True
        self._server = None
        self._thread: Optional[threading.Thread] = None

        # Create FastAPI app
        self.app = FastAPI(
            title="ProjectCortex Dashboard API",
            description="API for RPi5 device communication",
            version="2.0.0"
        )
        self._setup_cors()
        self._setup_routes()

        logger.info(f"FastAPI server initialized: {host}:{port}")

    def _setup_cors(self):
        """Setup CORS middleware"""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self):
        """Setup API routes"""

        @self.app.websocket("/ws/{device_id}")
        async def websocket_endpoint(websocket: WebSocket, device_id: str):
            """WebSocket endpoint for RPi5 devices"""
            await self._handle_websocket(websocket, device_id)

        @self.app.get("/api/v1/status", response_model=StatusResponse)
        async def get_status():
            """Get server status"""
            return StatusResponse(
                status="running",
                connected_devices=self.connection_manager.get_connection_count(),
                video_streaming_enabled=self.video_streaming_enabled,
                server_time=datetime.utcnow().isoformat() + "Z"
            )

        @self.app.get("/api/v1/devices")
        async def get_devices():
            """Get list of connected devices"""
            return {
                "devices": self.connection_manager.get_connected_devices(),
                "count": self.connection_manager.get_connection_count()
            }

        @self.app.post("/api/v1/control")
        async def control(request: ControlRequest):
            """Send control command to device"""
            action = request.action.lower()
            device_id = request.device_id

            if action == "start_video":
                self.video_streaming_enabled = True
                await self.connection_manager.broadcast({
                    "type": "COMMAND",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": {"command": "START_VIDEO_STREAMING"}
                })
                return {"success": True, "action": "video_started"}

            elif action == "stop_video":
                self.video_streaming_enabled = False
                await self.connection_manager.broadcast({
                    "type": "COMMAND",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": {"command": "STOP_VIDEO_STREAMING"}
                })
                return {"success": True, "action": "video_stopped"}

            elif action == "ping" and device_id:
                success = await self.connection_manager.send_message(device_id, {
                    "type": "PING",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": {}
                })
                return {"success": success, "action": "ping_sent"}

            else:
                raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

        @self.app.post("/api/v1/broadcast")
        async def broadcast_message(request: Dict[str, Any]):
            """Broadcast message to all connected devices"""
            await self.connection_manager.broadcast(request)
            return {"success": True, "devices": self.connection_manager.get_connection_count()}

    async def _handle_websocket(self, websocket: WebSocket, device_id: str):
        """Handle WebSocket connection from RPi5 device"""
        await self.connection_manager.connect(websocket, device_id)

        if self.on_connect:
            try:
                self.on_connect(device_id)
            except Exception as e:
                logger.error(f"Error in on_connect callback: {e}")

        try:
            while True:
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                    await self._process_message(device_id, data)
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.send_json({
                        "type": "PING",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "data": {}
                    })

        except WebSocketDisconnect:
            await self.connection_manager.disconnect(device_id, "WebSocket disconnected")

            if self.on_disconnect:
                try:
                    self.on_disconnect(device_id)
                except Exception as e:
                    logger.error(f"Error in on_disconnect callback: {e}")

        except Exception as e:
            logger.error(f"WebSocket error for {device_id}: {e}")
            await self.connection_manager.disconnect(device_id, str(e))

    async def _process_message(self, device_id: str, raw_data: str):
        """Process incoming WebSocket message"""
        try:
            data = json.loads(raw_data)
            msg_type = data.get("type", "")
            msg_data = data.get("data", {})

            logger.debug(f"Received {msg_type} from {device_id}")

            if msg_type == MessageType.VIDEO_FRAME.value:
                await self._handle_video_frame(device_id, msg_data)

            elif msg_type == MessageType.METRICS.value:
                await self._handle_metrics(device_id, msg_data)

            elif msg_type == MessageType.DETECTIONS.value:
                await self._handle_detection(device_id, msg_data)

            elif msg_type == MessageType.AUDIO_EVENT.value:
                await self._handle_audio_event(device_id, msg_data)

            elif msg_type == MessageType.STATUS.value:
                logger.info(f"Device status from {device_id}: {msg_data}")

            elif msg_type == MessageType.PONG.value:
                logger.debug(f"Pong from {device_id}")

            elif msg_type == MessageType.VIDEO_STREAMING_START.value:
                logger.info(f"Video streaming started by {device_id}")
                self.video_streaming_enabled = True

            elif msg_type == MessageType.VIDEO_STREAMING_STOP.value:
                logger.info(f"Video streaming stopped by {device_id}")
                self.video_streaming_enabled = False

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from {device_id}: {e}")
        except Exception as e:
            logger.error(f"Error processing message from {device_id}: {e}")

    async def _handle_video_frame(self, device_id: str, data: Dict[str, Any]):
        """Handle video frame message"""
        frame_b64 = data.get("frame", "")
        width = data.get("width", 640)
        height = data.get("height", 480)
        detections = data.get("detections", [])

        try:
            frame_data = base64.b64decode(frame_b64)

            if self.on_video_frame:
                try:
                    self.on_video_frame(device_id, frame_data, width, height, detections)
                except Exception as e:
                    logger.error(f"Error in on_video_frame callback: {e}")

        except Exception as e:
            logger.error(f"Error decoding frame from {device_id}: {e}")

    async def _handle_metrics(self, device_id: str, data: Dict[str, Any]):
        """Handle metrics message"""
        # Add device_id to metrics data
        data["device_id"] = device_id

        if self.on_metrics:
            try:
                self.on_metrics(device_id, data)
            except Exception as e:
                logger.error(f"Error in on_metrics callback: {e}")

    async def _handle_detection(self, device_id: str, data: Dict[str, Any]):
        """Handle detection message"""
        # Add device_id to detection data
        data["device_id"] = device_id

        if self.on_detection:
            try:
                self.on_detection(device_id, data)
            except Exception as e:
                logger.error(f"Error in on_detection callback: {e}")

    async def _handle_audio_event(self, device_id: str, data: Dict[str, Any]):
        """Handle audio event message"""
        logger.info(f"Audio event from {device_id}: {data}")
        # Could add audio callback in future

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    async def start(self):
        """Start the FastAPI server"""
        import uvicorn

        logger.info(f"Starting FastAPI server on {self.host}:{self.port}")

        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host=self.host,
                port=self.port,
                log_level="info"
            )
        )
        await self._server.serve()

    def start_background(self):
        """Start server in background thread"""
        if self._thread and self._thread.is_alive():
            logger.warning("Server already running")
            return

        def run_server():
            asyncio.run(self.start())

        self._thread = threading.Thread(
            target=run_server,
            daemon=True,
            name="FastAPIServer"
        )
        self._thread.start()
        logger.info("FastAPI server started in background")

    async def stop(self):
        """Stop the server"""
        if self._server:
            self._server.should_exit = True
            logger.info("FastAPI server stopping...")

    def send_command(self, device_id: str, command: str, data: Dict = None):
        """Send command to specific device"""
        message = {
            "type": "COMMAND",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "command": command,
                **(data or {})
            }
        }
        return asyncio.run(self.connection_manager.send_message(device_id, message))

    def broadcast_command(self, command: str, data: Dict = None):
        """Broadcast command to all devices"""
        message = {
            "type": "COMMAND",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "command": command,
                **(data or {})
            }
        }
        return asyncio.run(self.connection_manager.broadcast(message))


# ============================================================================
# RUNNER FUNCTION
# ============================================================================

def run_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    on_video_frame: Callable = None,
    on_metrics: Callable = None,
    on_detection: Callable = None
):
    """
    Convenience function to run FastAPI server

    Args:
        host: Server host
        port: Server port
        on_video_frame: Callback for video frames
        on_metrics: Callback for metrics
        on_detection: Callback for detections
    """
    server = FastAPIServer(
        host=host,
        port=port,
        on_video_frame=on_video_frame,
        on_metrics=on_metrics,
        on_detection=on_detection
    )

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server interrupted")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ProjectCortex FastAPI Server")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=8765, help="Server port")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print(f"Starting FastAPI server on {args.host}:{args.port}")
    run_server(host=args.host, port=args.port)
