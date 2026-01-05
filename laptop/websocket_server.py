"""
WebSocket Server for RPi ↔ Laptop Communication (Port 8765)

Handles real-time data streaming from RPi wearable devices to the laptop server.
Supports multiple concurrent RPi connections with broadcasting capabilities.

Features:
- Asyncio-based WebSocket server (websockets library)
- Connection management with heartbeat ping/pong
- Message routing and broadcasting
- Thread-safe data sharing with PyQt6 GUI
- Automatic reconnection handling

Protocol: See protocol.py for message format specification

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: January 3, 2026
"""

import asyncio
import json
import logging
from typing import Set, Dict, Any, Optional
from datetime import datetime
import websockets
from websockets.asyncio.server import serve, ServerConnection, broadcast
from websockets.exceptions import ConnectionClosed

from .config import (
    WS_SERVER_HOST,
    WS_SERVER_PORT,
    WS_MAX_CLIENTS,
    WS_PING_INTERVAL,
    WS_PING_TIMEOUT,
)
from .protocol import MessageType, parse_message, BaseMessage

logger = logging.getLogger(__name__)


class WebSocketServer:
    """
    WebSocket server for receiving data from RPi wearable devices.
    
    This server handles connections from one or more RPi devices and
    forwards data to the PyQt6 GUI for visualization.
    """
    
    def __init__(self, gui_callback=None):
        """
        Initialize WebSocket server.
        
        Args:
            gui_callback: Optional callback function to send data to GUI
                         Signature: callback(message_type: str, data: dict)
        """
        self.connections: Set[ServerConnection] = set()
        self.device_info: Dict[str, Dict[str, Any]] = {}  # device_id -> metadata
        self.message_count = 0
        self.gui_callback = gui_callback
        self.running = False
        self.server = None
        
        # Statistics
        self.stats = {
            "total_connections": 0,
            "messages_received": 0,
            "messages_sent": 0,
            "errors": 0,
        }
    
    async def start(self):
        """Start the WebSocket server."""
        logger.info(f"🚀 Starting WebSocket server on {WS_SERVER_HOST}:{WS_SERVER_PORT}")
        
        try:
            self.running = True
            
            # Create server with custom configuration
            async with serve(
                self.handler,
                WS_SERVER_HOST,
                WS_SERVER_PORT,
                ping_interval=WS_PING_INTERVAL,
                ping_timeout=WS_PING_TIMEOUT,
                max_size=10 * 1024 * 1024,  # 10MB max message size (for video frames)
            ) as server:
                self.server = server
                logger.info(f"✅ WebSocket server listening on ws://{WS_SERVER_HOST}:{WS_SERVER_PORT}")
                logger.info(f"   Max clients: {WS_MAX_CLIENTS}")
                logger.info(f"   Ping interval: {WS_PING_INTERVAL}s")
                
                # Run until stopped
                await asyncio.Future()  # Run forever
                
        except Exception as e:
            logger.error(f"❌ WebSocket server failed to start: {e}", exc_info=True)
            self.running = False
    
    async def stop(self):
        """Stop the WebSocket server."""
        logger.info("🛑 Stopping WebSocket server...")
        self.running = False
        
        # Close all active connections
        if self.connections:
            tasks = [conn.close() for conn in self.connections.copy()]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        self.connections.clear()
        logger.info("✅ WebSocket server stopped")
    
    async def handler(self, websocket: ServerConnection):
        """
        Handle incoming WebSocket connection from RPi.
        
        Args:
            websocket: WebSocket connection object
        """
        # Connection metadata
        client_address = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        device_id = None
        
        # Check max connections limit
        if len(self.connections) >= WS_MAX_CLIENTS:
            logger.warning(f"⚠️ Max connections reached ({WS_MAX_CLIENTS}), rejecting {client_address}")
            await websocket.close(1008, "Server at max capacity")
            return
        
        try:
            # Register connection
            self.connections.add(websocket)
            self.stats["total_connections"] += 1
            logger.info(f"✅ RPi connected: {client_address} (Total: {len(self.connections)})")
            
            # Send welcome message
            await self.send_message(
                websocket,
                MessageType.STATUS,
                status="Connected to Cortex Laptop Server",
                level="info",
                component="websocket_server"
            )
            
            # Message processing loop
            async for message in websocket:
                try:
                    # Parse JSON message
                    data = json.loads(message)
                    msg_obj = parse_message(data)
                    
                    # Extract device_id if present
                    if msg_obj.device_id and not device_id:
                        device_id = msg_obj.device_id
                        self.device_info[device_id] = {
                            "address": client_address,
                            "connected_at": datetime.utcnow(),
                            "last_message": datetime.utcnow(),
                        }
                        logger.info(f"   Device registered: {device_id}")
                    
                    # Update statistics
                    self.message_count += 1
                    self.stats["messages_received"] += 1
                    
                    if device_id:
                        self.device_info[device_id]["last_message"] = datetime.utcnow()
                    
                    # Route message to appropriate handler
                    await self.route_message(msg_obj, websocket)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Invalid JSON from {client_address}: {e}")
                    self.stats["errors"] += 1
                    await self.send_error(websocket, "INVALID_JSON", str(e))
                
                except Exception as e:
                    logger.error(f"❌ Message processing error: {e}", exc_info=True)
                    self.stats["errors"] += 1
                    await self.send_error(websocket, "PROCESSING_ERROR", str(e))
        
        except ConnectionClosed as e:
            logger.info(f"🔌 RPi disconnected: {client_address} (Code: {e.code}, Reason: {e.reason})")
        
        except Exception as e:
            logger.error(f"❌ Connection error with {client_address}: {e}", exc_info=True)
        
        finally:
            # Cleanup connection
            self.connections.remove(websocket)
            
            if device_id and device_id in self.device_info:
                del self.device_info[device_id]
            
            logger.info(f"   Remaining connections: {len(self.connections)}")
    
    async def route_message(self, message: BaseMessage, websocket: ServerConnection):
        """
        Route incoming message to appropriate handler.
        
        Args:
            message: Parsed message object
            websocket: Source WebSocket connection
        """
        # Log message (except frequent ones like metrics/video)
        if message.type not in [MessageType.METRICS, MessageType.VIDEO_FRAME]:
            logger.debug(f"📨 Received {message.type.value} from {message.device_id}")
        
        # Forward to GUI callback
        if self.gui_callback:
            try:
                data = message.dict()
                self.gui_callback(message.type.value, data)
            except Exception as e:
                logger.error(f"❌ GUI callback error: {e}")
        
        # Handle specific message types
        if message.type == MessageType.PING:
            # Respond with pong
            await self.send_message(
                websocket,
                MessageType.PONG,
                sequence=message.sequence
            )
        
        elif message.type == MessageType.STATUS:
            # Log status updates
            level_emoji = {"info": "ℹ️", "warning": "⚠️", "error": "❌"}.get(message.level, "📢")
            logger.info(f"{level_emoji} RPi Status: {message.status}")
    
    async def send_message(self, websocket: ServerConnection, msg_type: MessageType, **kwargs):
        """
        Send message to specific RPi client.
        
        Args:
            websocket: Target WebSocket connection
            msg_type: Message type
            **kwargs: Message fields
        """
        try:
            from .protocol import create_message
            
            message = create_message(msg_type, **kwargs)
            data = message.json()
            
            await websocket.send(data)
            self.stats["messages_sent"] += 1
            
        except Exception as e:
            logger.error(f"❌ Failed to send message: {e}")
            self.stats["errors"] += 1
    
    async def send_error(self, websocket: ServerConnection, error_code: str, error_message: str):
        """Send error message to client."""
        await self.send_message(
            websocket,
            MessageType.ERROR,
            error_code=error_code,
            error_message=error_message
        )
    
    async def broadcast_message(self, msg_type: MessageType, **kwargs):
        """
        Broadcast message to all connected RPi clients.
        
        Args:
            msg_type: Message type
            **kwargs: Message fields
        """
        if not self.connections:
            return
        
        try:
            from .protocol import create_message
            
            message = create_message(msg_type, **kwargs)
            data = message.json()
            
            # Use websockets.broadcast for efficient sending
            broadcast(self.connections, data)
            self.stats["messages_sent"] += len(self.connections)
            
            logger.debug(f"📡 Broadcasted {msg_type.value} to {len(self.connections)} clients")
            
        except Exception as e:
            logger.error(f"❌ Broadcast failed: {e}")
            self.stats["errors"] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics."""
        return {
            **self.stats,
            "active_connections": len(self.connections),
            "devices": list(self.device_info.keys()),
            "uptime_seconds": 0,  # TODO: Track server uptime
        }


def main():
    """Standalone server for testing."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    def test_callback(msg_type: str, data: dict):
        """Test callback that just logs messages."""
        logger.info(f"GUI Callback: {msg_type} - {data.get('device_id', 'unknown')}")
    
    # Create and run server
    server = WebSocketServer(gui_callback=test_callback)
    
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("⏸️ Received interrupt signal")
    finally:
        logger.info("👋 Server shutdown complete")


if __name__ == "__main__":
    main()
