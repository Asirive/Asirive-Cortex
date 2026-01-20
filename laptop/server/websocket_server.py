"""
WebSocket Server for ProjectCortex Laptop Dashboard

Receives real-time data from RPi5 devices:
- Video frames
- System metrics
- Object detections
- Audio events
- Status updates

Uses asyncio for non-blocking, efficient handling of multiple clients.

Author: Haziq (@IRSPlays)
Date: January 8, 2026
"""

import sys
import os

# Add project root to path so laptop module can be found
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import asyncio
import websockets
import logging
from typing import Set, Dict, Any, Callable, Optional, TYPE_CHECKING
from datetime import datetime
import json

from laptop.protocol import (
    MessageType,
    parse_message,
    BaseMessage
)
from laptop.config import DashboardConfig

# Handle type checking separately to avoid websockets version issues
if TYPE_CHECKING:
    from websockets import WebSocketServerProtocol


logger = logging.getLogger(__name__)


class CortexWebSocketServer:
    """
    WebSocket server for receiving RPi5 data

    Features:
    - Multiple client support (up to 5 RPi5 devices)
    - Message broadcasting
    - Auto-reconnect support
    - Ping/pong heartbeat
    - Thread-safe callbacks
    """

    def __init__(
        self,
        config: DashboardConfig,
        on_message: Optional[Callable] = None,
        on_connect: Optional[Callable] = None,
        on_disconnect: Optional[Callable] = None
    ):
        """
        Initialize WebSocket server

        Args:
            config: Dashboard configuration
            on_message: Callback when message received (websocket, message)
            on_connect: Callback when client connects (websocket)
            on_disconnect: Callback when client disconnects (websocket, reason)
        """
        self.config = config
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        # Connected clients
        self.clients: Set[websockets.server.WebSocketServerProtocol] = set()

        # Server state
        self.server = None
        self.is_running = False

        logger.info(f"WebSocket server initialized on {config.ws_host}:{config.ws_port}")

    async def register_client(self, websocket):
        """Register a new client connection"""
        self.clients.add(websocket)
        client_id = id(websocket)
        client_addr = websocket.remote_address

        logger.info(f"✅ Client connected: {client_addr} (ID: {client_id})")
        logger.info(f"   Total clients: {len(self.clients)}/{self.config.ws_max_clients}")

        # Call connect callback
        if self.on_connect:
            try:
                await self.on_connect(websocket)
            except Exception as e:
                logger.error(f"Error in on_connect callback: {e}")

        # Send welcome message
        try:
            welcome_msg = {
                "type": "STATUS",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "data": {
                    "status": "connected",
                    "message": f"Connected to ProjectCortex Dashboard v2.0",
                    "server_time": datetime.utcnow().isoformat() + "Z"
                }
            }
            await websocket.send(json.dumps(welcome_msg))
        except Exception as e:
            logger.error(f"Error sending welcome message: {e}")

    async def unregister_client(self, websocket, reason: str = ""):
        """Unregister a disconnected client"""
        if websocket in self.clients:
            self.clients.remove(websocket)
            client_id = id(websocket)
            client_addr = websocket.remote_address

            logger.info(f"❌ Client disconnected: {client_addr} (ID: {client_id}) - {reason}")
            logger.info(f"   Total clients: {len(self.clients)}/{self.config.ws_max_clients}")

            # Call disconnect callback
            if self.on_disconnect:
                try:
                    await self.on_disconnect(websocket, reason)
                except Exception as e:
                    logger.error(f"Error in on_disconnect callback: {e}")

    async def handle_client(self, websocket):
        """Handle client connection and messages"""
        await self.register_client(websocket)

        try:
            async for message in websocket:
                # Check message size
                if len(message) > self.config.ws_max_message_size:
                    logger.warning(f"⚠️  Message too large: {len(message)} bytes")
                    await self.send_error(websocket, "MESSAGE_TOO_LARGE", f"Message exceeds {self.config.ws_max_message_size} bytes")
                    continue

                # Parse message
                try:
                    parsed_message = parse_message(message)
                    if parsed_message:
                        # 2. Handle System Messages (PING/PONG)
                        if parsed_message.type == MessageType.PING:
                            logger.debug(f"Received PING from {websocket.remote_address}")
                            from laptop.protocol import create_pong
                            
                            # Respond with standardized PONG
                            pong_msg = create_pong(
                                device_id="laptop-dashboard",
                                latency_ms=0.0
                            )
                            await websocket.send(pong_msg.to_json())
                            continue

                        # 3. Handle Other Messages
                        logger.debug(f"📥 Received {parsed_message.type} from {websocket.remote_address}")

                        # Call message callback
                        if self.on_message:
                            try:
                                await self.on_message(websocket, parsed_message)
                            except Exception as e:
                                logger.error(f"Error in on_message callback: {e}")
                except Exception as e:
                    logger.error(f"Error parsing message: {e}")

        except websockets.exceptions.ConnectionClosed as e:
            await self.unregister_client(websocket, f"Connection closed: {e.code}")
        except Exception as e:
            await self.unregister_client(websocket, f"Error: {e}")

    async def send_error(self, websocket, code: str, message: str):
        """Send error message to client"""
        error_msg = {
            "type": "ERROR",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "error_type": "validation",
                "error_code": code,
                "message": message
            }
        }
        try:
            await websocket.send(json.dumps(error_msg))
        except Exception as e:
            logger.error(f"Error sending error message: {e}")

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients"""
        if not self.clients:
            return

        message_str = json.dumps(message)
        disconnected = set()

        for client in self.clients:
            try:
                await client.send(message_str)
            except Exception as e:
                logger.warning(f"Error broadcasting to {client.remote_address}: {e}")
                disconnected.add(client)

        # Remove disconnected clients
        for client in disconnected:
            await self.unregister_client(client, "Broadcast failed")

    async def send_to_client(self, websocket, message: Dict[str, Any]):
        """Send message to specific client"""
        try:
            message_str = json.dumps(message)
            await websocket.send(message_str)
        except Exception as e:
            logger.error(f"Error sending message to client: {e}")

    async def start(self):
        """Start WebSocket server"""
        if self.is_running:
            logger.warning("WebSocket server is already running")
            return

        self.is_running = True
        logger.info(f"🚀 Starting WebSocket server on {self.config.ws_host}:{self.config.ws_port}")
        logger.info(f"   Max clients: {self.config.ws_max_clients}")
        logger.info(f"   Max message size: {self.config.ws_max_message_size} bytes")

        try:
            self.server = await websockets.serve(
                self.handle_client,
                self.config.ws_host,
                self.config.ws_port,
                max_size=self.config.ws_max_message_size,
                ping_interval=self.config.ws_ping_interval,
                ping_timeout=self.config.ws_ping_timeout,
                close_timeout=10
            )

            logger.info(f"✅ WebSocket server started successfully")

            # Keep server running
            await asyncio.Future()  # Run forever

        except Exception as e:
            logger.error(f"❌ Error starting WebSocket server: {e}")
            self.is_running = False
            raise

    async def stop(self):
        """Stop WebSocket server"""
        if not self.is_running:
            return

        logger.info("🛑 Stopping WebSocket server...")
        self.is_running = False

        # Close all client connections
        for client in self.clients.copy():
            await client.close(reason="Server shutting down")

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        logger.info("✅ WebSocket server stopped")

    def get_client_count(self) -> int:
        """Get number of connected clients"""
        return len(self.clients)

    def get_client_info(self) -> list:
        """Get information about connected clients"""
        clients_info = []
        for client in self.clients:
            clients_info.append({
                "id": id(client),
                "address": str(client.remote_address),
                "state": client.state.name
            })
        return clients_info


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

async def on_message_example(websocket, message: BaseMessage):
    """Example message handler"""
    print(f"Received: {message.type} - {message.data}")


async def on_connect_example(websocket):
    """Example connect handler"""
    print(f"Client connected: {websocket.remote_address}")


async def on_disconnect_example(websocket, reason):
    """Example disconnect handler"""
    print(f"Client disconnected: {websocket.remote_address} - {reason}")


async def main():
    """Example server startup"""
    import signal
    from laptop.config import default_config

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create server
    server = CortexWebSocketServer(
        config=default_config,
        on_message=on_message_example,
        on_connect=on_connect_example,
        on_disconnect=on_disconnect_example
    )

    # Handle shutdown
    def signal_handler(sig, frame):
        print("\n🛑 Shutting down...")
        asyncio.create_task(server.stop())

    signal.signal(signal.SIGINT, signal_handler)

    # Start server
    try:
        await server.start()
    except KeyboardInterrupt:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
