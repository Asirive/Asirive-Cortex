"""
Main Launcher for ProjectCortex Laptop Dashboard

Integrates:
- WebSocket server (receives RPi5 data)
- PyQt6 GUI (displays real-time data)
- Thread-safe message handling

Usage:
    python -m laptop.start_dashboard

Author: Haziq (@IRSPlays)
Date: January 8, 2026
"""

import asyncio
import sys
import logging
import threading
from datetime import datetime
import json
import base64
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from laptop.config import DashboardConfig, default_config
from laptop.websocket_server import CortexWebSocketServer
from laptop.cortex_dashboard import CortexDashboard, DashboardSignals
from laptop.protocol import MessageType, BaseMessage


logger = logging.getLogger(__name__)


class DashboardApplication:
    """
    Main dashboard application

    Integrates WebSocket server with PyQt6 GUI using thread-safe signals.
    """

    def __init__(self, config: DashboardConfig = None):
        """Initialize dashboard application"""
        self.config = config or default_config

        # Setup logging
        logging.basicConfig(
            level=getattr(logging, self.config.log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.config.log_file),
                logging.StreamHandler()
            ]
        )

        logger.info("="*70)
        logger.info("ProjectCortex v2.0 - Laptop Dashboard")
        logger.info("="*70)

        # Qt application (created in main thread)
        self.app = None
        self.dashboard = None

        # Signals for thread-safe communication
        self.signals = DashboardSignals()

        # WebSocket server (runs in separate thread)
        self.server = None
        self.server_thread = None
        self.loop = None

        # Metrics history (for last update tracking)
        self.last_metrics = {}

    def _create_message_handler(self):
        """Create message handler for WebSocket server"""
        async def handle_message(websocket, message: BaseMessage):
            """Handle incoming message from RPi5"""
            try:
                if message.type == MessageType.VIDEO_FRAME.value:
                    # Handle video frame
                    frame_data = base64.b64decode(message.data.get("frame", ""))
                    width = message.data.get("width", 640)
                    height = message.data.get("height", 480)

                    # Emit signal to GUI (thread-safe)
                    self.signals.video_frame.emit(frame_data, width, height)

                elif message.type == MessageType.METRICS.value:
                    # Handle metrics
                    metrics = message.data
                    self.last_metrics = metrics

                    # Emit signal to GUI
                    self.signals.metrics_update.emit(metrics)

                    # Log to system
                    logger.debug(f"Metrics: FPS={metrics.get('fps', 0):.1f}, "
                               f"RAM={metrics.get('ram_percent', 0):.1f}%, "
                               f"CPU={metrics.get('cpu_percent', 0):.1f}%")

                elif message.type == MessageType.DETECTIONS.value:
                    # Handle detection
                    detection = message.data
                    layer = detection.get("layer", "unknown")
                    class_name = detection.get("class_name", "unknown")
                    confidence = detection.get("confidence", 0.0)

                    # Format log message
                    log_msg = f"{layer.upper()}: {class_name} ({confidence:.2f})"

                    # Emit signal to GUI
                    self.signals.detection_log.emit(log_msg)

                    logger.info(f"Detection: {log_msg}")

                elif message.type == MessageType.STATUS.value:
                    # Handle status message
                    status = message.data.get("status", "unknown")
                    msg = message.data.get("message", "")

                    level = "INFO" if status == "connected" else "WARNING"
                    self.signals.system_log.emit(f"RPi5 Status: {msg}", level)

                    logger.info(f"Status: {status} - {msg}")

                elif message.type == MessageType.AUDIO_EVENT.value:
                    # Handle audio event
                    event = message.data.get("event", "unknown")
                    text = message.data.get("text", "")
                    layer = message.data.get("layer", "unknown")

                    log_msg = f"Audio [{event}]: {text} (routed to {layer})"
                    self.signals.system_log.emit(log_msg, "INFO")

                    logger.info(f"Audio Event: {log_msg}")

                elif message.type == MessageType.MEMORY_EVENT.value:
                    # Handle memory event
                    event = message.data.get("event", "unknown")
                    local_rows = message.data.get("local_rows", 0)
                    synced_rows = message.data.get("synced_rows", 0)
                    queue_size = message.data.get("upload_queue", 0)

                    log_msg = f"Memory [{event}]: Local={local_rows}, Synced={synced_rows}, Queue={queue_size}"
                    self.signals.system_log.emit(log_msg, "INFO")

                    logger.info(f"Memory Event: {log_msg}")

                elif message.type == "PING":
                    # Respond with pong
                    pong_msg = {
                        "type": "PONG",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "data": {
                            "ping_timestamp": message.data.get("timestamp"),
                            "pong_timestamp": datetime.utcnow().isoformat() + "Z"
                        }
                    }
                    await websocket.send(json.dumps(pong_msg))

            except Exception as e:
                logger.error(f"Error handling message: {e}")
                self.signals.system_log.emit(f"Error: {str(e)}", "ERROR")

        return handle_message

    def _create_connect_handler(self):
        """Create client connect handler"""
        async def handle_connect(websocket):
            """Handle client connection"""
            address = str(websocket.remote_address)
            logger.info(f"✅ Client connected: {address}")

            # Emit signal to GUI
            self.signals.client_connected.emit(address)

            # Update client count
            QTimer.singleShot(0, lambda: self._update_client_count())

        return handle_connect

    def _create_disconnect_handler(self):
        """Create client disconnect handler"""
        async def handle_disconnect(websocket, reason):
            """Handle client disconnection"""
            address = str(websocket.remote_address)
            logger.info(f"❌ Client disconnected: {address} - {reason}")

            # Emit signal to GUI
            self.signals.client_disconnected.emit(address)

            # Update client count
            QTimer.singleShot(0, lambda: self._update_client_count())

        return handle_disconnect

    def _update_client_count(self):
        """Update client count in GUI"""
        if self.dashboard and self.server:
            count = self.server.get_client_count()
            max_clients = self.config.ws_max_clients
            self.dashboard.client_count_label.setText(f"Clients: {count}/{max_clients}")

    def _run_server(self):
        """Run WebSocket server in background thread"""
        # Create new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Create server
        self.server = CortexWebSocketServer(
            config=self.config,
            on_message=self._create_message_handler(),
            on_connect=self._create_connect_handler(),
            on_disconnect=self._create_disconnect_handler()
        )

        # Run server
        try:
            logger.info("🚀 Starting WebSocket server thread...")
            self.loop.run_until_complete(self.server.start())
        except Exception as e:
            logger.error(f"Server error: {e}")
        finally:
            logger.info("🛑 WebSocket server thread stopped")

    def start(self):
        """Start dashboard application"""
        try:
            # Create Qt application
            self.app = QApplication(sys.argv)
            self.app.setApplicationName("ProjectCortex Dashboard")

            # Create dashboard GUI
            self.dashboard = CortexDashboard(self.config)

            # Connect signals to dashboard
            self.signals.video_frame.connect(self.dashboard._on_video_frame)
            self.signals.metrics_update.connect(self.dashboard._on_metrics_update)
            self.signals.detection_log.connect(self.dashboard._on_detection_log)
            self.signals.system_log.connect(self.dashboard._on_system_log)
            self.signals.client_connected.connect(self.dashboard._on_client_connected)
            self.signals.client_disconnected.connect(self.dashboard._on_client_disconnected)

            # Show dashboard
            self.dashboard.show()

            # Start WebSocket server in background thread
            logger.info("🧵 Starting WebSocket server thread...")
            self.server_thread = threading.Thread(
                target=self._run_server,
                daemon=True,
                name="WebSocketServer"
            )
            self.server_thread.start()

            # Log startup
            logger.info("✅ Dashboard started")
            logger.info(f"   WebSocket: {self.config.ws_host}:{self.config.ws_port}")
            logger.info(f"   GUI: {self.config.gui_width}x{self.config.gui_height}")
            logger.info(f"   Waiting for RPi5 connections...")

            self.dashboard.system_log.add_log("Dashboard started successfully", "SUCCESS")
            self.dashboard.system_log.add_log(f"WebSocket server listening on {self.config.ws_host}:{self.config.ws_port}", "INFO")
            self.dashboard.system_log.add_log("Waiting for RPi5 connections...", "INFO")

            # Run Qt application
            return self.app.exec()

        except Exception as e:
            logger.error(f"Error starting dashboard: {e}")
            return 1

    def stop(self):
        """Stop dashboard application"""
        logger.info("🛑 Stopping dashboard...")

        # Stop server
        if self.server and self.loop:
            asyncio.run_coroutine_threadsafe(
                self.server.stop(),
                self.loop
            )

        # Close dashboard
        if self.dashboard:
            self.dashboard.close()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="ProjectCortex Laptop Dashboard")
    parser.add_argument(
        "--host",
        default=None,
        help="WebSocket host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="WebSocket port (default: 8765)"
    )

    args = parser.parse_args()

    # Create config
    config = default_config
    if args.host:
        config.ws_host = args.host
    if args.port:
        config.ws_port = args.port

    # Create and start application
    application = DashboardApplication(config)

    try:
        exit_code = application.start()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n🛑 Interrupted by user")
        application.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
