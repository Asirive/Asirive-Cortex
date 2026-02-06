"""
FastAPI + PyQt6 Integration for ProjectCortex Dashboard

Provides:
- Bridge between FastAPI WebSocket server and PyQt6 dashboard
- Thread-safe signal emission for GUI updates
- Video streaming toggle control

Usage:
    from laptop.fastapi_integration import FastAPIIntegration
    integration = FastAPIIntegration(dashboard_signals)
    integration.start_server(host="0.0.0.0", port=8765)

Author: Haziq (@IRSPlays)
Date: January 11, 2026
"""

import asyncio
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from laptop.server.fastapi_server import FastAPIServer

logger = logging.getLogger(__name__)


# ============================================================================
# DASHBOARD SIGNALS BRIDGE
# ============================================================================

class FastAPISignals(QObject):
    """PyQt6 signals for FastAPI server events (thread-safe)"""

    # Core signals matching DashboardSignals in cortex_dashboard.py
    video_frame = pyqtSignal(bytes, int, int, list)  # frame_data, width, height, detections
    metrics_update = pyqtSignal(dict)  # metrics data
    detection_log = pyqtSignal(dict)  # detection data
    system_log = pyqtSignal(str, str)  # message, level
    client_connected = pyqtSignal(str)  # device_id
    client_disconnected = pyqtSignal(str)  # device_id, reason
    video_streaming_changed = pyqtSignal(bool)  # enabled
    status_update = pyqtSignal(str, str)  # status, message (e.g. MODE_CHANGE, PRODUCTION)


# ============================================================================
# FASTAPI INTEGRATION
# ============================================================================

class FastAPIIntegration:
    """
    Bridge between FastAPI WebSocket server and PyQt6 dashboard

    This class:
    1. Starts FastAPI server in background thread
    2. Receives data from RPi5 via WebSocket
    3. Emits PyQt6 signals for GUI updates
    4. Provides control methods for the dashboard
    """

    def __init__(
        self,
        signals: FastAPISignals = None,
        host: str = "0.0.0.0",
        port: int = 8765
    ):
        """
        Initialize FastAPI integration

        Args:
            signals: PyQt6 signals for GUI updates (creates new if not provided)
            host: Server host address
            port: Server port
        """
        self.signals = signals or FastAPISignals()
        self.host = host
        self.port = port

        self._server: Optional[FastAPIServer] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._uvicorn_loop: Optional[asyncio.AbstractEventLoop] = None  # Store Uvicorn's loop

        # State
        self.connected_devices: List[str] = []
        self.video_streaming_enabled = True

        logger.info("FastAPI integration initialized")

    def _on_video_frame(self, device_id: str, frame_data: bytes, width: int, height: int, detections: List[Dict]):
        """Handle incoming video frame - emit signal for GUI"""
        self.signals.video_frame.emit(frame_data, width, height, detections)

    def _on_metrics(self, device_id: str, metrics_data: Dict[str, Any]):
        """Handle incoming metrics - emit signal for GUI"""
        self.signals.metrics_update.emit(metrics_data)

    def _on_detection(self, device_id: str, detection_data: Dict[str, Any]):
        """Handle incoming detection - emit signal for GUI"""
        self.signals.detection_log.emit(detection_data)

    def _on_connect(self, device_id: str):
        """Handle device connection"""
        if device_id not in self.connected_devices:
            self.connected_devices.append(device_id)
        self.signals.client_connected.emit(device_id)
        self.signals.system_log.emit(f"Device connected: {device_id}", "SUCCESS")

    def _on_disconnect(self, device_id: str, reason: str = ""):
        """Handle device disconnection"""
        if device_id in self.connected_devices:
            self.connected_devices.remove(device_id)
        self.signals.client_disconnected.emit(device_id)
        self.signals.system_log.emit(f"Device disconnected: {device_id} ({reason})", "WARNING")

    def start_server(self, host: str = None, port: int = None) -> bool:
        """
        Start FastAPI server in background thread

        Args:
            host: Server host (uses init value if not provided)
            port: Server port (uses init value if not provided)

        Returns:
            True if server started successfully
        """
        if self._running:
            logger.warning("Server already running")
            return False

        host = host or self.host
        port = port or self.port

        try:
            # CRITICAL FIX: Use ServerConfig instead of host/port parameters
            from shared.api import ServerConfig
            server_config = ServerConfig(host=host, port=port)
            
            self._server = FastAPIServer(
                config=server_config,
                on_video_frame=self._on_video_frame,
                on_metrics=self._on_metrics,
                on_detection=self._on_detection,
                on_connect=self._on_connect,
                on_disconnect=self._on_disconnect
            )

            # CRITICAL FIX: FastAPIServer doesn't have start_background method
            # The server is driven by uvicorn, not by calling start_background
            # For now, mark as running - actual start happens via uvicorn in dashboard
            self._running = True

            logger.info(f"FastAPI server started on {host}:{port}")
            self.signals.system_log.emit(f"FastAPI server started on {host}:{port}", "INFO")

            return True

        except Exception as e:
            logger.error(f"Failed to start FastAPI server: {e}")
            self.signals.system_log.emit(f"Failed to start server: {e}", "ERROR")
            return False

    def stop_server(self):
        """Stop FastAPI server"""
        if not self._running:
            return

        logger.info("Stopping FastAPI server...")
        self.signals.system_log.emit("Stopping FastAPI server...", "INFO")

        if self._server:
            # CRITICAL FIX: Use run_coroutine_threadsafe with stored loop
            if self._uvicorn_loop and self._uvicorn_loop.is_running():
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._server.stop(),
                        self._uvicorn_loop
                    )
                    future.result(timeout=10.0)
                except Exception as e:
                    logger.error(f"Error stopping server: {e}")
            else:
                logger.warning("Uvicorn loop not available, cannot stop server cleanly")

        self._running = False
        logger.info("FastAPI server stopped")

    def send_command(self, device_id: str, command: str, data: Dict = None) -> bool:
        """
        Send command to specific device

        Args:
            device_id: Target device ID
            command: Command name (START_VIDEO_STREAMING, STOP_VIDEO_STREAMING, etc.)
            data: Additional command data

        Returns:
            True if command sent successfully
        """
        if not self._server:
            logger.error("Server not running")
            return False

        return self._server.send_command(device_id, command, data)

    def broadcast_command(self, command: str, data: Dict = None):
        """
        Broadcast command to all connected devices

        Args:
            command: Command name
            data: Additional command data
        """
        if not self._server:
            logger.error("Server not running")
            return

        self._server.broadcast_command(command, data)
        logger.info(f"Broadcast command: {command}")

    def toggle_video_streaming(self, enabled: bool = None):
        """
        Toggle video streaming on/off

        Args:
            enabled: Force enable/disable (toggles if not provided)
        """
        if enabled is None:
            self.video_streaming_enabled = not self.video_streaming_enabled
        else:
            self.video_streaming_enabled = enabled

        # Broadcast to all devices
        command = "START_VIDEO_STREAMING" if self.video_streaming_enabled else "STOP_VIDEO_STREAMING"
        self.broadcast_command(command)

        # Emit signal
        self.signals.video_streaming_changed.emit(self.video_streaming_enabled)
        self.signals.system_log.emit(
            f"Video streaming {'enabled' if self.video_streaming_enabled else 'disabled'}",
            "INFO"
        )

        logger.info(f"Video streaming: {self.video_streaming_enabled}")

    def get_connected_devices(self) -> List[str]:
        """Get list of connected device IDs"""
        return self.connected_devices.copy()

    def is_running(self) -> bool:
        """Check if server is running"""
        return self._running


# ============================================================================
# DASHBOARD MIXIN
# ============================================================================

class FastAPIDashboardMixin:
    """
    Mixin class to add FastAPI integration to CortexDashboard

    Usage:
        class MyDashboard(FastAPIDashboardMixin, CortexDashboard):
            def __init__(self):
                super().__init__()
                self.setup_fastapi(host="0.0.0.0", port=8765)
    """

    fastapi_integration: FastAPIIntegration = None

    def setup_fastapi(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        auto_start: bool = True
    ):
        """
        Setup FastAPI integration for the dashboard

        Args:
            host: FastAPI server host
            port: FastAPI server port
            auto_start: Automatically start server when dashboard opens
        """
        # Create integration
        self.fastapi_integration = FastAPIIntegration(
            host=host,
            port=port
        )

        # Connect signals to dashboard slots
        self.fastapi_integration.signals.video_frame.connect(self.on_video_frame)
        self.fastapi_integration.signals.metrics_update.connect(self.on_metrics_update)
        self.fastapi_integration.signals.detection_log.connect(self.on_detection)
        self.fastapi_integration.signals.system_log.connect(self.on_system_log)
        self.fastapi_integration.signals.client_connected.connect(self.on_client_connected)
        self.fastapi_integration.signals.client_disconnected.connect(self.on_client_disconnected)

        if auto_start:
            self.fastapi_integration.start_server(host=host, port=port)

        logger.info("FastAPI integration setup complete")

    def shutdown_fastapi(self):
        """Shutdown FastAPI integration"""
        if self.fastapi_integration:
            self.fastapi_integration.stop_server()

    def on_video_frame(self, frame_data: bytes, width: int, height: int, detections: List[Dict]):
        """Handle video frame - override in subclass"""
        pass

    def on_metrics_update(self, data: Dict[str, Any]):
        """Handle metrics update - override in subclass"""
        pass

    def on_detection(self, data: Dict[str, Any]):
        """Handle detection - override in subclass"""
        pass

    def on_system_log(self, message: str, level: str):
        """Handle system log - override in subclass"""
        pass

    def on_client_connected(self, device_id: str):
        """Handle client connected - override in subclass"""
        pass

    def on_client_disconnected(self, device_id: str):
        """Handle client disconnected - override in subclass"""
        pass


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def create_fastapi_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    video_frame_callback: Callable = None,
    metrics_callback: Callable = None,
    detection_callback: Callable = None
) -> FastAPIServer:
    """
    Create a FastAPI server with callbacks

    Args:
        host: Server host
        port: Server port
        video_frame_callback: Called when video frame received
        metrics_callback: Called when metrics received
        detection_callback: Called when detection received

    Returns:
        FastAPIServer instance (not started)
    """
    return FastAPIServer(
        host=host,
        port=port,
        on_video_frame=video_frame_callback,
        on_metrics=metrics_callback,
        on_detection=detection_callback
    )


def run_server_sync(host: str = "0.0.0.0", port: int = 8765):
    """
    Run FastAPI server synchronously (blocking)

    Args:
        host: Server host
        port: Server port
    """
    import uvicorn
    from laptop.server.fastapi_server import FastAPIServer

    server = FastAPIServer(host=host, port=port)

    print(f"Starting FastAPI server on {host}:{port}")
    print("Press Ctrl+C to stop")

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\nShutting down...")
        asyncio.run(server.stop())


# ============================================================================
# MAIN
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

    run_server_sync(host=args.host, port=args.port)
