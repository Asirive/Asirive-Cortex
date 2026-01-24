"""
Abstract WebSocket Server Base Class

Provides common functionality for WebSocket servers:
- Multi-client connection management
- Broadcast to all/specific clients
- Rate limiting
- Connection statistics
- Event callbacks for subclasses
"""
import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from collections import defaultdict

from .protocol import BaseMessage, MessageType
from .exceptions import ConnectionError, ProtocolError

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """WebSocket server configuration."""
    host: str = "0.0.0.0"
    port: int = 8765
    max_clients: int = 5
    ping_interval: float = 30.0
    ping_timeout: float = 10.0
    max_message_size: int = 10 * 1024 * 1024  # 10MB
    rate_limit: int = 100  # Messages per second per client


@dataclass
class ClientInfo:
    """Information about a connected client."""
    client_id: str
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    messages_sent: int = 0
    messages_received: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class AsyncWebSocketServer(ABC):
    """
    Abstract base class for WebSocket servers.

    Subclasses must implement:
    - _start_server_impl(): Start listening for connections
    - _stop_server_impl(): Stop listening
    - _send_to_client_impl(client_id, message): Send to specific client
    - _broadcast_impl(message, exclude): Send to all clients

    Features:
    - Multi-client support with connection limits
    - Per-client rate limiting
    - Connection statistics
    - Event callbacks
    """

    def __init__(self, config: Optional[ServerConfig] = None):
        self.config = config or ServerConfig()

        # State
        self._running = False
        self._clients: Dict[str, Any] = {}  # client_id -> websocket
        self._client_info: Dict[str, ClientInfo] = {}

        # Rate limiting: client_id -> (timestamp, count)
        self._rate_limit: Dict[str, List[float]] = defaultdict(list)

        # Statistics
        self._total_connections = 0
        self._total_messages = 0

        # Callbacks
        self.on_connect: Optional[Callable[[str], None]] = None  # client_id
        self.on_disconnect: Optional[Callable[[str, str], None]] = None  # client_id, reason
        self.on_message: Optional[Callable[[str, BaseMessage], None]] = None  # client_id, message
        self.on_error: Optional[Callable[[str, Exception], None]] = None  # client_id, error
        self.on_rate_limit: Optional[Callable[[str], None]] = None  # client_id

        # Lock for thread safety
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    @property
    def client_count(self) -> int:
        """Get number of connected clients."""
        return len(self._clients)

    @property
    def connected_devices(self) -> List[str]:
        """Get list of connected client IDs."""
        return list(self._clients.keys())

    def get_client_info(self, client_id: str) -> Optional[ClientInfo]:
        """Get information about a client."""
        return self._client_info.get(client_id)

    def get_all_client_info(self) -> List[ClientInfo]:
        """Get information about all clients."""
        return list(self._client_info.values())

    def get_statistics(self) -> Dict[str, Any]:
        """Get server statistics."""
        return {
            "running": self._running,
            "client_count": self.client_count,
            "total_connections": self._total_connections,
            "total_messages": self._total_messages,
            "clients": [
                {
                    "client_id": info.client_id,
                    "connected_at": info.connected_at.isoformat(),
                    "messages_sent": info.messages_sent,
                    "messages_received": info.messages_received,
                }
                for info in self._client_info.values()
            ]
        }

    # ==================== Public API ====================

    async def start(self):
        """Start the server."""
        if self._running:
            logger.warning("Server already running")
            return

        logger.info(f"Starting server on {self.config.host}:{self.config.port}")
        self._running = True

        await self._start_server_impl()
        logger.info("Server started")

    async def stop(self):
        """Stop the server gracefully."""
        if not self._running:
            return

        logger.info("Stopping server...")
        self._running = False

        # Disconnect all clients
        async with self._lock:
            for client_id in list(self._clients.keys()):
                await self._disconnect_client(client_id, "server_shutdown")

        await self._stop_server_impl()
        logger.info("Server stopped")

    async def send_to_client(self, client_id: str, message: BaseMessage) -> bool:
        """
        Send a message to a specific client.

        Args:
            client_id: Target client ID.
            message: Message to send.

        Returns:
            True if sent, False if client not connected.
        """
        async with self._lock:
            if client_id not in self._clients:
                logger.warning(f"Client {client_id} not connected")
                return False

        # Check rate limit
        if not self._check_rate_limit(client_id):
            logger.warning(f"Rate limit exceeded for {client_id}")
            if self.on_rate_limit:
                self.on_rate_limit(client_id)
            return False

        try:
            await self._send_to_client_impl(client_id, message)

            # Update stats
            async with self._lock:
                if client_id in self._client_info:
                    self._client_info[client_id].messages_sent += 1
                    self._client_info[client_id].bytes_sent += len(message.to_json())
                    self._client_info[client_id].last_active = datetime.now(timezone.utc)

            self._total_messages += 1
            return True

        except Exception as e:
            logger.error(f"Failed to send to {client_id}: {e}")
            await self._disconnect_client(client_id, str(e))
            return False

    async def broadcast(self, message: BaseMessage, exclude: Optional[Set[str]] = None) -> int:
        """
        Broadcast a message to all connected clients.

        Args:
            message: Message to broadcast.
            exclude: Set of client IDs to exclude.

        Returns:
            Number of clients message was sent to.
        """
        exclude = exclude or set()
        sent_count = 0

        async with self._lock:
            connected_ids = list(self._clients.keys())

        for client_id in connected_ids:
            if client_id not in exclude:
                if await self.send_to_client(client_id, message):
                    sent_count += 1

        logger.debug(f"Broadcast to {sent_count} clients")
        return sent_count

    async def disconnect_client(self, client_id: str, reason: str = "requested"):
        """Disconnect a specific client."""
        await self._disconnect_client(client_id, reason)

    async def disconnect_all(self, reason: str = "maintenance"):
        """Disconnect all clients."""
        async with self._lock:
            client_ids = list(self._clients.keys())

        for client_id in client_ids:
            await self._disconnect_client(client_id, reason)

    # ==================== Connection Management ====================

    async def _register_client(self, client_id: str, websocket: Any):
        """Register a new client connection."""
        async with self._lock:
            # Check max clients
            if len(self._clients) >= self.config.max_clients:
                logger.warning(f"Max clients reached, rejecting {client_id}")
                return False

            # Register
            self._clients[client_id] = websocket
            self._client_info[client_id] = ClientInfo(client_id=client_id)
            self._total_connections += 1

            logger.info(f"Client connected: {client_id} (total: {len(self._clients)})")

        # Notify callback
        if self.on_connect:
            self.on_connect(client_id)

        return True

    async def _disconnect_client(self, client_id: str, reason: str):
        """Disconnect a client."""
        async with self._lock:
            if client_id not in self._clients:
                return

            # Remove from clients
            websocket = self._clients.pop(client_id, None)

        # Cleanup
        if websocket:
            try:
                await self._close_websocket(websocket)
            except Exception:
                pass

        # Remove from rate limit
        self._rate_limit.pop(client_id, None)

        logger.info(f"Client disconnected: {client_id} ({reason})")

        # Notify callback
        if self.on_disconnect:
            self.on_disconnect(client_id, reason)

    async def _handle_client_message(self, client_id: str, message: BaseMessage):
        """Process a message from a client."""
        # Update stats
        async with self._lock:
            if client_id in self._client_info:
                self._client_info[client_id].messages_received += 1
                self._client_info[client_id].last_active = datetime.now(timezone.utc)

        logger.debug(f"Message from {client_id}: {message.type}")

        # Handle PING
        if message.type == MessageType.PING:
            from .protocol import create_pong
            ping_id = message.data.get("ping_id")
            pong = create_pong(client_id, 0.0, ping_id=ping_id)
            await self.send_to_client(client_id, pong)
            return

        # Dispatch to handler
        handler_name = f"_handle_{message.type.value.lower()}"
        handler = getattr(self, handler_name, None)

        if handler:
            await handler(client_id, message)
        elif self.on_message:
            self.on_message(client_id, message)

    # ==================== Rate Limiting ====================

    def _check_rate_limit(self, client_id: str) -> bool:
        """Check if client is within rate limit."""
        now = time.time()
        window_start = now - 1.0  # 1 second window

        # Clean old entries
        self._rate_limit[client_id] = [
            t for t in self._rate_limit[client_id] if t > window_start
        ]

        # Check limit
        return len(self._rate_limit[client_id]) < self.config.rate_limit

    def _record_message(self, client_id: str):
        """Record a message for rate limiting."""
        self._rate_limit[client_id].append(time.time())

    # ==================== Abstract Methods ====================

    @abstractmethod
    async def _start_server_impl(self):
        """Start listening for connections."""
        pass

    @abstractmethod
    async def _stop_server_impl(self):
        """Stop listening."""
        pass

    @abstractmethod
    async def _send_to_client_impl(self, client_id: str, message: BaseMessage):
        """Send message to specific client."""
        pass

    @abstractmethod
    async def _close_websocket(self, websocket: Any):
        """Close a WebSocket connection."""
        pass

    # ==================== Default Handlers ====================

    async def _handle_command(self, client_id: str, message: BaseMessage):
        """Handle COMMAND message (override in subclass)."""
        logger.info(f"Command from {client_id}: {message.data}")

    async def _handle_video_frame(self, client_id: str, message: BaseMessage):
        """Handle VIDEO_FRAME message (override in subclass)."""
        pass

    async def _handle_metrics(self, client_id: str, message: BaseMessage):
        """Handle METRICS message (override in subclass)."""
        pass

    async def _handle_detections(self, client_id: str, message: BaseMessage):
        """Handle DETECTIONS message (override in subclass)."""
        pass

    async def _handle_error(self, client_id: str, message: BaseMessage):
        """Handle ERROR message."""
        error_code = message.data.get("error_code", "UNKNOWN")
        error_msg = message.data.get("error_message", "")
        logger.error(f"Error from {client_id} [{error_code}]: {error_msg}")


# ==================== FastAPI Integration ====================

class FastAPIWebSocketServer(AsyncWebSocketServer):
    """
    FastAPI-compatible WebSocket server.

    Uses FastAPI's WebSocket endpoint pattern.
    """

    def __init__(self, config: Optional[ServerConfig] = None):
        super().__init__(config)
        self._websockets: Dict[str, Any] = {}  # client_id -> WebSocket

    async def _start_server_impl(self):
        """Nothing to do - FastAPI handles server start."""
        pass

    async def _stop_server_impl(self):
        """Close all WebSocket connections."""
        async with self._lock:
            for ws in list(self._websockets.values()):
                try:
                    await ws.close()
                except Exception:
                    pass
            self._websockets.clear()

    async def _send_to_client_impl(self, client_id: str, message: BaseMessage):
        """Send via FastAPI WebSocket."""
        if client_id not in self._websockets:
            raise ConnectionError(f"Client {client_id} not connected")

        ws = self._websockets[client_id]
        await ws.send_text(message.to_json())

    async def _close_websocket(self, websocket: Any):
        """Close FastAPI WebSocket."""
        try:
            await websocket.close()
        except Exception:
            pass

    def register_websocket(self, client_id: str, websocket: Any):
        """Register a FastAPI WebSocket connection."""
        self._websockets[client_id] = websocket
        self._clients[client_id] = websocket

    def unregister_websocket(self, client_id: str):
        """Unregister a FastAPI WebSocket connection."""
        self._websockets.pop(client_id, None)
