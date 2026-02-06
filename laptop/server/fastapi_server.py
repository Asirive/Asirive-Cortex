"""
FastAPI Server for ProjectCortex Laptop Dashboard

Uses shared API for protocol and base server classes.
Provides WebSocket endpoint for RPi5 real-time data and REST API for control.

Usage:
    from laptop.server.fastapi_server import FastAPIServer
    server = FastAPIServer(host="0.0.0.0", port=8765)
    await server.start()

Author: Haziq (@IRSPlays)
Date: January 17, 2026 (Refactored)
"""

import asyncio
import base64
import json
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import shared API
from shared.api import (
    AsyncWebSocketServer,
    ServerConfig,
    ClientInfo,
    BaseMessage,
    MessageType,
    parse_message,
    create_command,
    create_ping,
)
from shared.config import get_default_laptop_config

logger = logging.getLogger(__name__)

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Project Cortex Dashboard API",
    description="API for Project Cortex wearable device dashboard",
    version="2.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global connection manager and server
_connection_manager: Optional["FastAPIConnectionManager"] = None
_server: Optional["LaptopWebSocketServer"] = None
_dashboard_runner: Optional[Any] = None  # Reference to DashboardRunner for loop capture


def set_server_instance(server: "LaptopWebSocketServer"):
    """Set the global server instance."""
    global _server
    _server = server

def get_server_instance() -> Optional["LaptopWebSocketServer"]:
    """Get the global server instance."""
    return _server

def set_connection_instance(manager: "FastAPIConnectionManager"):
    """Set the global connection manager instance."""
    global _connection_manager
    _connection_manager = manager

def get_connection_manager() -> Optional["FastAPIConnectionManager"]:
    """Get the global connection manager."""
    return _connection_manager

def set_dashboard_runner(runner: Any):
    """Set reference to DashboardRunner to capture event loop on startup."""
    global _dashboard_runner
    _dashboard_runner = runner
    logger.info(f"Dashboard runner registered: {runner}")


# ============================================================================
# DATA MODELS (Pydantic for REST API)
# ============================================================================

class ControlRequest(BaseModel):
    """Control command request"""
    action: str
    device_id: str = ""
    parameters: Dict[str, Any] = {}

class StatusResponse(BaseModel):
    """Status response"""
    status: str
    connected_devices: int = 0
    video_streaming_enabled: bool = True
    server_time: str = ""


# ============================================================================
# CONNECTION MANAGER
# ============================================================================

class FastAPIConnectionManager:
    """
    Manages WebSocket connections using FastAPI WebSocket.

    Integrates with shared AsyncWebSocketServer for protocol handling.
    
    Thread-Safety Note:
        Uses threading.Lock() instead of asyncio.Lock() to allow cross-thread
        access from the Qt main thread (via _handle_ui_command) while Uvicorn
        runs in its own thread with its own event loop.
    """

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}  # device_id -> websocket
        # CRITICAL: Use threading.Lock for cross-thread safety (Qt thread -> Uvicorn thread)
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket, device_id: str):
        """Register new connection (WebSocket already accepted by endpoint handler)"""
        with self._lock:
            self.active_connections[device_id] = websocket
        logger.info(f"Device connected: {device_id} (total: {len(self.active_connections)})")

    async def disconnect(self, device_id: str, reason: str = ""):
        """Unregister connection"""
        with self._lock:
            if device_id in self.active_connections:
                del self.active_connections[device_id]
        logger.info(f"Device disconnected: {device_id} - {reason}")

    async def send_message(self, device_id: str, message: BaseMessage) -> bool:
        """Send message to specific device (thread-safe)"""
        with self._lock:
            websocket = self.active_connections.get(device_id)

        if websocket:
            try:
                await websocket.send_text(message.to_json())
                logger.debug(f"Message sent to {device_id}: {message.type}")
                return True
            except Exception as e:
                logger.error(f"Error sending to {device_id}: {e}")
                await self.disconnect(device_id, str(e))
        return False

    async def broadcast(self, message: BaseMessage):
        """Broadcast message to all connected devices"""
        disconnected = []
        with self._lock:
            connected = list(self.active_connections.keys())

        for device_id in connected:
            success = await self.send_message(device_id, message)
            if not success:
                disconnected.append(device_id)

        for device_id in disconnected:
            await self.disconnect(device_id, "send_failed")

    def get_connected_devices(self) -> List[str]:
        """Get list of connected device IDs (thread-safe)"""
        with self._lock:
            return list(self.active_connections.keys())

    def get_connection_count(self) -> int:
        """Get number of connections (thread-safe)"""
        with self._lock:
            return len(self.active_connections)


# ============================================================================
# LAPTOP WEBSOCKET SERVER (Shared API Integration)
# ============================================================================

class LaptopWebSocketServer(AsyncWebSocketServer):
    """
    Laptop dashboard WebSocket server using shared API.

    Integrates with FastAPI WebSocket for the actual transport.
    """

    def __init__(self, config: Optional[ServerConfig] = None,
                 on_video_frame: Optional[Callable] = None,
                 on_metrics: Optional[Callable] = None,
                 on_detection: Optional[Callable] = None,
                 on_connect: Optional[Callable] = None,
                 on_disconnect: Optional[Callable] = None,
                 on_status: Optional[Callable] = None):
        super().__init__(config)
        self._connection_manager = None  # Will be set when first client connects
        self._websockets = {}  # Fix: Initialize storage for raw websockets

        # Store callbacks
        self._on_video_frame_cb = on_video_frame
        self._on_metrics_cb = on_metrics
        self._on_detection_cb = on_detection
        self._on_connect_cb = on_connect
        self._on_disconnect_cb = on_disconnect
        self._on_status_cb = on_status

        # Register default handlers (that call our custom ones)
        self.on_connect = self._handle_connect
        self.on_disconnect = self._handle_disconnect

    async def _handle_connect(self, client_id: str):
        """Connect handler"""
        logger.info(f"Client connected: {client_id}")
        if self._on_connect_cb:
            if asyncio.iscoroutinefunction(self._on_connect_cb):
                await self._on_connect_cb(client_id)
            else:
                 self._on_connect_cb(client_id)

    async def _handle_disconnect(self, client_id: str, reason: str):
        """Disconnect handler"""
        logger.info(f"Client disconnected: {client_id} ({reason})")
        if self._on_disconnect_cb:
            if asyncio.iscoroutinefunction(self._on_disconnect_cb):
                await self._on_disconnect_cb(client_id)
            else:
                self._on_disconnect_cb(client_id)

    async def _handle_video_frame(self, client_id: str, message: BaseMessage):
        """Handle incoming video frame"""
        data = message.data
        if self._on_video_frame_cb:
            try:
                # Extract relevant data
                frame_b64 = data.get("frame", "")
                width = data.get("width", 640)
                height = data.get("height", 480)
                detections = data.get("detections", [])
                
                # Debug log
                logger.debug(f"DEBUG: Processing VideoFrame on FastAPI Server. B64Size={len(frame_b64)}")
                
                frame_bytes = base64.b64decode(frame_b64)
                logger.debug(f"DEBUG: Decoded Frame Bytes: {len(frame_bytes)}")
                
                # Call callback
                if asyncio.iscoroutinefunction(self._on_video_frame_cb):
                    await self._on_video_frame_cb(frame_bytes, width, height, detections)
                else:
                    self._on_video_frame_cb(frame_bytes, width, height, detections)
                
                logger.debug("DEBUG: VideoFrame callback executed successfully")
                
            except Exception as e:
                logger.error(f"ERROR processing video frame: {e}")
                logger.error(f"Traceback: {str(e)}")


    async def _handle_metrics(self, client_id: str, message: BaseMessage):
        """Handle incoming metrics"""
        data = message.data
        logger.debug(f"Metrics from {client_id}: FPS={data.get('fps')}")
        # CRITICAL FIX: Call the metrics callback
        if self._on_metrics_cb:
            try:
                if asyncio.iscoroutinefunction(self._on_metrics_cb):
                    await self._on_metrics_cb(data)
                else:
                    self._on_metrics_cb(data)
            except Exception as e:
                logger.error(f"Error in metrics callback: {e}")

    async def _handle_detections(self, client_id: str, message: BaseMessage):
        """Handle incoming detections"""
        data = message.data
        detections = data.get("detections", [])
        logger.debug(f"Detections from {client_id}: {len(detections)} objects")
        # CRITICAL FIX: Call the detections callback
        if self._on_detection_cb:
            try:
                for det in detections:
                    if asyncio.iscoroutinefunction(self._on_detection_cb):
                        await self._on_detection_cb(det)
                    else:
                        self._on_detection_cb(det)
            except Exception as e:
                logger.error(f"Error in detection callback: {e}")

    async def _handle_status(self, client_id: str, message: BaseMessage):
        """Handle STATUS messages from RPi5."""
        data = message.data
        status = data.get("status", "unknown")
        msg = data.get("message", "")
        logger.info(f"Status from {client_id}: {status} - {msg}")
        
        # Forward to callback (e.g., for MODE_CHANGE notifications)
        if self._on_status_cb:
            if asyncio.iscoroutinefunction(self._on_status_cb):
                await self._on_status_cb(status, msg)
            else:
                self._on_status_cb(status, msg)

    async def _handle_audio_event(self, client_id: str, message: BaseMessage):
        """Handle AUDIO_EVENT messages from RPi5."""
        data = message.data
        event = data.get("event", "unknown")
        text = data.get("text", "")
        logger.info(f"Audio event from {client_id}: [{event}] {text}")

    async def _handle_memory_event(self, client_id: str, message: BaseMessage):
        """Handle MEMORY_EVENT messages from RPi5."""
        data = message.data
        event = data.get("event", "unknown")
        local_rows = data.get("local_rows", 0)
        synced_rows = data.get("synced_rows", 0)
        logger.debug(f"Memory event from {client_id}: {event} (local={local_rows}, synced={synced_rows})")

    async def _handle_gps_imu(self, client_id: str, message: BaseMessage):
        """Handle GPS_IMU messages from RPi5."""
        data = message.data
        logger.debug(f"GPS/IMU from {client_id}: lat={data.get('latitude')}, lon={data.get('longitude')}")

    async def _handle_layer_response(self, client_id: str, message: BaseMessage):
        """Handle LAYER_RESPONSE messages from RPi5."""
        data = message.data
        layer = data.get("layer", "unknown")
        logger.info(f"Layer response from {client_id}: layer={layer}")

    async def _handle_layer1_query(self, client_id: str, message: BaseMessage):
        """Handle LAYER1_QUERY messages - RPi5 requesting GPU inference."""
        data = message.data
        frame_b64 = data.get("frame")
        
        if not frame_b64:
            logger.warning(f"LAYER1_QUERY from {client_id} missing frame data")
            return
        
        logger.debug(f"LAYER1_QUERY from {client_id}: processing GPU inference request")

    # Abstract method implementations for FastAPI

    async def _start_server_impl(self):
        """Nothing needed - FastAPI handles server lifecycle"""
        pass

    async def _stop_server_impl(self):
        """Close all connections"""
        await self.disconnect_all("server_shutdown")

    async def _send_to_client_impl(self, client_id: str, message: BaseMessage):
        """Send via FastAPI connection manager"""
        # Fix: Add null safety check for connection manager
        if self._connection_manager is None:
            logger.warning(f"Connection manager not ready, cannot send to {client_id}")
            return

        # Fix: Also check if client_id is in the active connections
        # The connection manager uses a lock internally, so we use its method
        await self._connection_manager.send_message(client_id, message)

    async def _close_websocket(self, websocket: Any):
        """Close FastAPI WebSocket"""
        try:
            await websocket.close()
        except Exception:
            pass

    def register_websocket(self, device_id: str, websocket: WebSocket):
        """Register a FastAPI WebSocket connection"""
        self._websockets[device_id] = websocket
        self._clients[device_id] = websocket
        self._client_info[device_id] = ClientInfo(client_id=device_id)
        self._total_connections += 1

    def unregister_websocket(self, device_id: str):
        """Unregister a FastAPI WebSocket connection"""
        self._websockets.pop(device_id, None)
        self._clients.pop(device_id, None)


# ============================================================================
# LIFESPAN EVENTS
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Capture Uvicorn's event loop on startup for cross-thread communication."""
    global _dashboard_runner
    if _dashboard_runner:
        # Store the event loop that Uvicorn is using
        import asyncio
        _dashboard_runner._uvicorn_loop = asyncio.get_running_loop()
        logger.info(f"✅ Uvicorn event loop captured: {_dashboard_runner._uvicorn_loop}")


# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================

@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    """WebSocket endpoint for RPi5 devices"""
    global _connection_manager, _server

    logger.debug(f"WebSocket Connect Request from: {device_id} ({websocket.client.host if websocket.client else 'Unknown'})")

    # Fix: Initialize connection manager if not exists (lazy initialization)
    if _connection_manager is None:
        _connection_manager = FastAPIConnectionManager()
        logger.info(f"Created new connection manager")

    # Fix: Initialize server if not exists - USE the globally set server if available
    if _server is None:
        config = get_default_laptop_config()
        server_config = ServerConfig(
            host=config["server"]["host"],
            port=config["server"]["port"],
            max_clients=config["server"].get("max_clients", 5),
        )
        _server = LaptopWebSocketServer(server_config)
        # Fix: Set the connection manager on the server instance
        _server._connection_manager = _connection_manager
        logger.info("Created new server instance with connection manager")
    else:
        # Ensure the server's connection manager is synced with the global one
        if _server._connection_manager is None and _connection_manager is not None:
            _server._connection_manager = _connection_manager
            logger.info("Synced server connection manager with global connection manager")
        logger.debug(f"Using existing server instance, connection_manager ready: {_server._connection_manager is not None}")

    # Register connection - Accept FIRST before any other operations
    try:
        await websocket.accept()
        logger.info(f"WebSocket accepted for {device_id}")
    except Exception as e:
        logger.error(f"WebSocket Accept Failed for {device_id}: {e}")
        raise

    # Now register with connection manager and server
    try:
        await _connection_manager.connect(websocket, device_id)
        _server.register_websocket(device_id, websocket)
        # CRITICAL FIX: Call the _handle_connect to trigger the on_connect callback
        await _server._handle_connect(device_id)
        logger.info(f"WebSocket registered: {device_id} (total: {_connection_manager.get_connection_count()})")
    except Exception as e:
        logger.error(f"WebSocket Registration Failed for {device_id}: {e}")
        await _connection_manager.disconnect(device_id, str(e))
        raise

    try:
        # Handle messages
        while True:
            try:
                data = await websocket.receive_text()
                message = parse_message(data)

                # Process via shared server
                await _server._handle_client_message(device_id, message)

            except json.JSONDecodeError:
                logger.error(f"Invalid JSON from {device_id}")
            except Exception as e:
                logger.error(f"Error handling message from {device_id}: {e}")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {device_id}")
    finally:
        await _connection_manager.disconnect(device_id, "websocket_closed")
        _server.unregister_websocket(device_id)
        logger.info(f"WebSocket cleanup complete for {device_id}")


# ============================================================================
# REST API ENDPOINTS
# ============================================================================

@app.get("/api/v1/status")
async def get_status() -> StatusResponse:
    """Get server status"""
    global _connection_manager
    if _connection_manager is None:
        return StatusResponse(
            status="ready",
            connected_devices=0,
            video_streaming_enabled=True,
            server_time=datetime.now().isoformat(),
        )

    return StatusResponse(
        status="running",
        connected_devices=_connection_manager.get_connection_count(),
        video_streaming_enabled=True,
        server_time=datetime.now().isoformat(),
    )


@app.get("/api/v1/devices")
async def get_devices() -> Dict[str, Any]:
    """Get connected devices list"""
    global _connection_manager
    if _connection_manager is None:
        return {"devices": []}

    return {
        "devices": _connection_manager.get_connected_devices(),
        "count": _connection_manager.get_connection_count(),
    }


@app.post("/api/v1/control")
async def send_control(request: ControlRequest) -> Dict[str, Any]:
    """Send control command to device"""
    global _server

    if _server is None or not _server.is_running:
        raise HTTPException(status_code=503, detail="Server not running")

    # Create command message
    cmd_msg = create_command(
        action=request.action,
        target_layer=request.parameters.get("target_layer"),
        parameters=request.parameters,
    )

    if request.device_id:
        # Send to specific device
        success = await _server.send_to_client(request.device_id, cmd_msg)
    else:
        # Broadcast to all
        sent = await _server.broadcast(cmd_msg)
        success = sent > 0

    return {
        "success": success,
        "action": request.action,
        "target": request.device_id or "all",
    }


@app.post("/api/v1/broadcast")
async def broadcast_message(request: Dict[str, Any]) -> Dict[str, Any]:
    """Broadcast message to all devices"""
    global _server

    if _server is None or not _server.is_running:
        raise HTTPException(status_code=503, detail="Server not running")

    msg_type = request.get("type", "COMMAND")
    msg_data = request.get("data", {})

    from shared.api import MessageType, BaseMessage
    msg = BaseMessage(type=MessageType(msg_type), data=msg_data)

    sent = await _server.broadcast(msg)

    return {
        "success": True,
        "sent_to": sent,
    }


# ============================================================================
# SERVER LIFECYCLE
# ============================================================================

def get_server() -> Optional[LaptopWebSocketServer]:
    """Get the current server instance"""
    return _server


def reset_server():
    """Reset server state (for testing)"""
    global _connection_manager, _server
    _connection_manager = None
    _server = None


# ============================================================================
# RUNNER (Standalone)
# ============================================================================

def run_server(host: str = "0.0.0.0", port: int = 8765):
    """Run the FastAPI server with uvicorn"""
    import uvicorn

    config = get_default_laptop_config()
    config["server"]["host"] = host
    config["server"]["port"] = port

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


# Alias for backwards compatibility
FastAPIServer = LaptopWebSocketServer


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Project Cortex Dashboard Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    run_server(args.host, args.port)
