"""
Abstract WebSocket Client Base Class

Provides common functionality for WebSocket clients:
- Auto-reconnect with exponential backoff
- Heartbeat management (PING/PONG)
- Message queue for reliability
- Thread-safe operations
- Event callbacks for subclasses
"""
import asyncio
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Deque
from collections import deque
import json

from .protocol import BaseMessage, MessageType
from .exceptions import ConnectionError, TimeoutError, ProtocolError

logger = logging.getLogger(__name__)


@dataclass
class ClientConfig:
    """WebSocket client configuration."""
    url: str
    device_id: str
    reconnect_delay: float = 5.0  # Initial reconnect delay (seconds)
    max_reconnect_delay: float = 60.0  # Max delay between reconnects
    ping_interval: float = 30.0  # Send PING every N seconds
    ping_timeout: float = 10.0  # Wait N seconds for PONG
    message_queue_size: int = 100  # Max queued messages
    heartbeat_timeout: float = 10.0  # Consider disconnected if no activity


class HeartbeatState:
    """Track heartbeat state."""
    def __init__(self, ping_interval: float, ping_timeout: float):
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.last_ping_sent: Optional[datetime] = None
        self.last_pong_received: Optional[datetime] = None
        self.ping_id: Optional[str] = None
        self.pending_ping = False

    def mark_pong(self, ping_id: str):
        """Mark that PONG was received."""
        if self.pending_ping and self.ping_id == ping_id:
            self.pending_ping = False
            self.last_pong_received = datetime.now(timezone.utc)
            self.ping_id = None

    def should_send_ping(self) -> bool:
        """Check if it's time to send a new PING."""
        if self.pending_ping:
            # Check for timeout
            if self.last_ping_sent:
                elapsed = (datetime.now(timezone.utc) - self.last_ping_sent).total_seconds()
                if elapsed > self.ping_timeout:
                    return True  # Timeout, retry
            return False

        if self.last_pong_received:
            elapsed = (datetime.now(timezone.utc) - self.last_pong_received).total_seconds()
            return elapsed >= self.ping_interval

        # First ping
        return True


class AsyncWebSocketClient(ABC):
    """
    Abstract base class for WebSocket clients.

    Subclasses must implement:
    - _connect_impl(): Establish WebSocket connection
    - _send_impl(message): Send raw message
    - _disconnect_impl(): Close connection
    - _handle_message(message): Process received messages

    Features:
    - Auto-reconnect with exponential backoff
    - Heartbeat (PING/PONG) management
    - Message queue for offline buffering
    - Thread-safe operations
    """

    def __init__(self, config: ClientConfig):
        self.config = config
        self.device_id = config.device_id

        # State
        self._connected = False
        self._running = False
        self._closing = False

        # Components
        self._message_queue: Deque[BaseMessage] = deque(maxlen=config.message_queue_size)
        self._heartbeat = HeartbeatState(config.ping_interval, config.ping_timeout)

        # Event loops (for async/sync bridge)
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_thread: Optional[threading.Thread] = None

        # Callbacks (can be overridden by subclasses)
        self.on_connect: Optional[Callable[[], None]] = None
        self.on_disconnect: Optional[Callable[[str], None]] = None  # reason
        self.on_message: Optional[Callable[[BaseMessage], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None
        self.on_reconnect: Optional[Callable[[int], None]] = None  # attempt number

        # Lock for thread safety
        self._lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        with self._lock:
            return self._connected

    @property
    def is_running(self) -> bool:
        """Check if client is running."""
        with self._lock:
            return self._running

    # ==================== Public API ====================

    def start(self, run_async: bool = True):
        """
        Start the client.

        Args:
            run_async: If True, run async event loop in background thread.
        """
        with self._lock:
            if self._running:
                logger.warning("Client already running")
                return

            self._running = True
            self._closing = False

        if run_async:
            self._start_async_thread()
        else:
            # Run in current thread (caller manages event loop)
            self._run_loop()

    def stop(self, timeout: float = 10.0):
        """
        Stop the client gracefully.

        Args:
            timeout: Max seconds to wait for graceful shutdown.
        """
        logger.info(f"Stopping client {self.device_id}")

        with self._lock:
            if not self._running:
                return

            self._closing = True

        # Stop async thread if running
        if self._async_thread and self._async_thread.is_alive():
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)
            self._async_thread.join(timeout=timeout)

        # Disconnect if connected
        if self._connected:
            try:
                self._disconnect_impl()
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")

        with self._lock:
            self._running = False
            self._connected = False

        logger.info("Client stopped")

    async def send(self, message: BaseMessage) -> bool:
        """
        Send a message. Queues if not connected.

        Args:
            message: Message to send.

        Returns:
            True if sent or queued, False if queue full.
        """
        with self._lock:
            if self._connected:
                try:
                    await self._send_impl(message)
                    return True
                except Exception as e:
                    logger.error(f"Send failed: {e}")
                    # Queue for retry
                    return self._queue_message(message)
            else:
                return self._queue_message(message)

    def send_sync(self, message: BaseMessage, timeout: float = 5.0) -> bool:
        """
        Send a message synchronously (blocking).

        Args:
            message: Message to send.
            timeout: Max seconds to wait for send.

        Returns:
            True if sent, False otherwise.
        """
        if not self._async_loop:
            raise RuntimeError("Client not started with async support")

        future = asyncio.run_coroutine_threadsafe(
            self.send(message),
            self._async_loop
        )

        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            logger.error("Send timed out")
            return False

    # ==================== Queue Management ====================

    def _queue_message(self, message: BaseMessage) -> bool:
        """Queue a message for later sending."""
        if len(self._message_queue) >= self.config.message_queue_size:
            logger.warning("Message queue full, dropping message")
            return False

        self._message_queue.append(message)
        logger.debug(f"Queued message: {message.type}")
        return True

    async def _flush_queue(self):
        """Send all queued messages."""
        logger.debug(f"[DEBUG] _flush_queue called, queue size: {len(self._message_queue)}")
        # Copy to list to avoid modification during iteration if needed, 
        # but popleft is safer.
        while self._lock: # Check lock/connected? actually just check queue
             if not self._message_queue:
                 break
             
             try:
                # Peek first
                message = self._message_queue[0]
                logger.debug(f"[DEBUG] Sending queued message: {message.type}")
                await self._send_impl(message)
                
                # Pop only if send succeeded
                if self._message_queue:
                    self._message_queue.popleft()
                
                logger.debug(f"[DEBUG] Sent queued message: {message.type}")
             except Exception as e:
                logger.error(f"[DEBUG] Failed to send queued message: {e}")
                # Don't pop if failed, but break to avoid loop
                break

    # ==================== Heartbeat ====================

    async def _heartbeat_loop(self):
        """Background task for heartbeat management."""
        while self._running and self._connected:
            try:
                # Check for PONG timeout
                if self._heartbeat.pending_ping:
                    elapsed = (datetime.now(timezone.utc) - self._heartbeat.last_ping_sent).total_seconds()
                    if elapsed > self.config.ping_timeout:
                        logger.warning("PONG timeout, reconnecting...")
                        await self._reconnect("heartbeat_timeout")
                        break

                # Send PING if needed
                # User requested disabling continuous heartbeat to save bandwidth/latency
                # if self._heartbeat.should_send_ping():
                #     ping_id = f"{self.device_id}_{int(time.time() * 1000)}"
                #     self._heartbeat.pending_ping = True
                #     self._heartbeat.last_ping_sent = datetime.now(timezone.utc)
                #     self._heartbeat.ping_id = ping_id
                # 
                #     from .protocol import create_ping
                #     ping_msg = create_ping(self.device_id, ping_id)
                #     await self._send_impl(ping_msg)
                #     logger.debug(f"Sent PING: {ping_id}")

                await asyncio.sleep(5.0) # Check less frequently

            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                break

    def _handle_pong(self, message: BaseMessage):
        """Handle incoming PONG message."""
        ping_id = message.data.get("ping_id")
        self._heartbeat.mark_pong(ping_id)
        logger.debug(f"Received PONG: {ping_id}")

    # ==================== Connection Management ====================

    async def _reconnect(self, reason: str = "reconnect", attempt: int = 1):
        """Attempt to reconnect with exponential backoff."""
        logger.info(f"Reconnecting (attempt {attempt}): {reason}")

        # Disconnect first
        try:
            await self._disconnect_impl()
        except Exception:
            pass

        # Calculate delay with exponential backoff
        delay = min(
            self.config.reconnect_delay * (2 ** (attempt - 1)),
            self.config.max_reconnect_delay
        )
        delay += (time.time() % 1)  # Add jitter

        logger.info(f"Reconnecting in {delay:.1f}s...")
        await asyncio.sleep(delay)

        # Try to connect
        for i in range(3):  # 3 attempts per reconnect cycle
            try:
                await self._connect_impl()
                self._connected = True
                logger.info("Reconnected successfully")

                # Notify callback
                if self.on_reconnect:
                    self.on_reconnect(attempt)

                # Flush queued messages
                await self._flush_queue()

                # Start heartbeat
                asyncio.create_task(self._heartbeat_loop())

                return

            except Exception as e:
                logger.error(f"Reconnect attempt {i+1} failed: {e}")
                await asyncio.sleep(2.0)

        # All attempts failed
        logger.error("Reconnect failed, will retry later")
        self._connected = False

    async def _ensure_connected(self):
        """Ensure we're connected, reconnect if needed."""
        if not self._connected:
            await self._connect_impl()
            self._connected = True

    # ==================== Async Loop ====================

    def _start_async_thread(self):
        """Start async event loop in background thread."""
        self._async_loop = asyncio.new_event_loop()
        self._async_thread = threading.Thread(
            target=self._run_loop,
            args=(self._async_loop,),
            daemon=True
        )
        self._async_thread.start()
        logger.info("Async thread started")

    def _run_loop(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Run the main event loop."""
        if loop is None:
            loop = asyncio.new_event_loop()

        async def _main():
            """Main async task."""
            try:
                await self._connect_impl()
                self._connected = True

                if self.on_connect:
                    self.on_connect()

                # Send initial PING (One-time check)
                try:
                    from .protocol import create_ping
                    ping_id = f"{self.device_id}_init_{int(time.time())}"
                    ping_msg = create_ping(self.device_id, ping_id)
                    await self._send_impl(ping_msg)
                    logger.info(f"Sent INITIAL PING: {ping_id}")
                except Exception as e:
                    logger.error(f"Failed to send initial PING: {e}")

                # Start heartbeat
                asyncio.create_task(self._heartbeat_loop())

                # Main receive loop
                await self._receive_loop()

            except Exception as e:
                logger.error(f"Connection error: {e}")
                if self.on_error:
                    self.on_error(e)

            finally:
                if not self._closing:
                    await self._reconnect("connection_lost")

        loop.run_until_complete(_main())

    async def _receive_loop(self):
        """Main message receive loop."""
        while self._running and self._connected:
            try:
                message = await self._receive_impl()
                if message is None:
                    break

                await self._handle_message(message)

            except Exception as e:
                logger.error(f"Receive error: {e}")
                break

    # ==================== Abstract Methods ====================

    @abstractmethod
    async def _connect_impl(self):
        """Establish WebSocket connection. Must set self._websocket."""
        pass

    @abstractmethod
    async def _send_impl(self, message: BaseMessage):
        """Send raw message over WebSocket."""
        pass

    @abstractmethod
    async def _disconnect_impl(self):
        """Close WebSocket connection."""
        pass

    @abstractmethod
    async def _receive_impl(self) -> Optional[BaseMessage]:
        """Receive and parse next message. Return None to disconnect."""
        pass

    async def _handle_message(self, message: BaseMessage):
        """Process received message."""
        logger.debug(f"Received: {message.type}")

        # Handle heartbeat messages
        if message.type == MessageType.PONG:
            self._handle_pong(message)
            return

        # Dispatch to handler
        handler_name = f"_handle_{message.type.value.lower()}"
        handler = getattr(self, handler_name, None)

        if handler:
            await handler(message)
        elif self.on_message:
            self.on_message(message)

    # ==================== Default Handlers ====================

    async def _handle_ping(self, message: BaseMessage):
        """Handle incoming PING."""
        from .protocol import create_pong
        pong = create_pong(self.device_id, 0.0)  # Latency calculated by sender
        await self._send_impl(pong)

    async def _handle_command(self, message: BaseMessage):
        """Handle COMMAND message (override in subclass)."""
        logger.info(f"Received command: {message.data}")

    async def _handle_error(self, message: BaseMessage):
        """Handle ERROR message."""
        error_code = message.data.get("error_code", "UNKNOWN")
        error_msg = message.data.get("error_message", "")
        logger.error(f"Remote error [{error_code}]: {error_msg}")

        if self.on_error:
            self.on_error(ProtocolError(error_msg))


# ==================== Sync Bridge ====================

class SyncWebSocketClient(AsyncWebSocketClient):
    """
    Synchronous wrapper for AsyncWebSocketClient.

    Provides blocking send/connect methods for non-async code.
    """

    def __init__(self, config: ClientConfig):
        super().__init__(config)
        self._ws = None  # Actual WebSocket reference

    def connect(self, timeout: float = 10.0) -> bool:
        """
        Connect synchronously.

        Args:
            timeout: Max seconds to wait for connection.

        Returns:
            True if connected, False otherwise.
        """
        if self.is_connected:
            return True

        self.start(run_async=False)

        # Wait for connection
        start = time.time()
        while time.time() - start < timeout:
            if self.is_connected:
                return True
            time.sleep(0.1)

        return False

    def disconnect(self):
        """Disconnect synchronously."""
        self.stop()

    def send_message(self, message_data: Dict[str, Any], timeout: float = 5.0) -> bool:
        """
        Send a message dict (auto-wrapped in BaseMessage).

        Args:
            message_data: Message data dict.
            timeout: Max seconds to wait.

        Returns:
            True if sent, False otherwise.
        """
        from .protocol import BaseMessage, MessageType

        message = BaseMessage(
            type=MessageType(message_data.get("type", "UNKNOWN")),
            data=message_data.get("data", {}),
        )
        return self.send_sync(message, timeout)

    # Abstract method implementations (override per use case)

    async def _connect_impl(self):
        """Override in subclass with actual WebSocket library."""
        raise NotImplementedError

    async def _send_impl(self, message: BaseMessage):
        """Override in subclass with actual WebSocket library."""
        raise NotImplementedError

    async def _disconnect_impl(self):
        """Override in subclass with actual WebSocket library."""
        raise NotImplementedError

    async def _receive_impl(self) -> Optional[BaseMessage]:
        """Override in subclass with actual WebSocket library."""
        raise NotImplementedError
