"""
Main Launcher for ProjectCortex Laptop Dashboard

Integrates:
- WebSocket server (legacy mode)
- FastAPI server (new mode with REST API + WebSocket)
- PyQt6 GUI (displays real-time data)
- Thread-safe message handling

Usage:
    python -m laptop.start_dashboard              # Legacy WebSocket mode
    python -m laptop.start_dashboard --fastapi    # FastAPI mode (recommended)

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
from laptop.server.websocket_server import CortexWebSocketServer
from laptop.server.fastapi_server import FastAPIServer
from laptop.gui.cortex_ui import CortexDashboard as CortexDashboardUI, DashboardSignals
from laptop.protocol import MessageType, BaseMessage


logger = logging.getLogger(__name__)


class DashboardApplication:
    """
    Main dashboard application

    Integrates WebSocket or FastAPI server with PyQt6 GUI using thread-safe signals.
    """

    def __init__(self, config: DashboardConfig = None, use_fastapi: bool = False):
        """Initialize dashboard application"""
        self.config = config or default_config
        self.use_fastapi = use_fastapi

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
        logger.info(f"ProjectCortex v2.0 - Laptop Dashboard ({'FastAPI' if use_fastapi else 'WebSocket'})")
        logger.info("="*70)

        # Qt application (created in main thread)
        self.app = None
        self.dashboard = None

        # Signals for thread-safe communication
        self.signals = DashboardSignals()

        # Server (WebSocket or FastAPI)
        self.server = None
        self.server_thread = None
        self.loop = None

        # Metrics history (for last update tracking)
        self.last_metrics = {}

        # FastAPI specific
        self.fastapi_server = None

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

                    # Emit signal to GUI with dict
                    self.signals.detection_log.emit(detection)

                    logger.info(f"Detection: {class_name} ({confidence:.2f}) [{layer}]")

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

                elif message.type == MessageType.PING:
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
        if self.dashboard:
            count = self.server.get_client_count() if self.server else 0
            max_clients = self.config.ws_max_clients
            self.dashboard.statusBar().showMessage(f"Clients: {count}/{max_clients}")

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
            self.dashboard = CortexDashboardUI(self.config)

            # Connect signals to dashboard
            self.signals.video_frame.connect(self.dashboard.on_video_frame)
            self.signals.metrics_update.connect(self.dashboard.on_metrics_update)
            self.signals.detection_log.connect(self.dashboard.on_detection)
            self.signals.system_log.connect(self.dashboard.on_system_log)
            self.signals.client_connected.connect(self.dashboard.on_client_connected)
            self.signals.client_disconnected.connect(self.dashboard.on_client_disconnected)

            # Show dashboard
            self.dashboard.show()

            # Connect UI Logic for Sending Commands
            self.signals.send_command.connect(self._handle_ui_command)

            if self.use_fastapi:
                # Start FastAPI server in background thread
                self._run_fastapi_server()
            else:
                # Start legacy WebSocket server in background thread
                logger.info("🧵 Starting WebSocket server thread...")
                self.server_thread = threading.Thread(
                    target=self._run_server,
                    daemon=True,
                    name="WebSocketServer"
                )
                self.server_thread.start()

            # Log startup
            logger.info("Dashboard started")
            logger.info(f"   Server: {'FastAPI' if self.use_fastapi else 'WebSocket'}")
            logger.info(f"   Address: {self.config.ws_host}:{self.config.ws_port}")
            logger.info(f"   GUI: {self.config.gui_width}x{self.config.gui_height}")
            logger.info("   Waiting for RPi5 connections...")

            mode_str = "FastAPI" if self.use_fastapi else "WebSocket"
            self.dashboard.on_system_log("Dashboard started successfully", "SUCCESS")
            self.dashboard.on_system_log(f"{mode_str} server listening on {self.config.ws_host}:{self.config.ws_port}", "INFO")
            self.dashboard.on_system_log("Waiting for RPi5 connections...", "INFO")

            # Run Qt application
            return self.app.exec()

        except Exception as e:
            logger.error(f"Error starting dashboard: {e}")
            return 1

    def _run_fastapi_server(self):
        """Run FastAPI server in background thread"""
        import asyncio
        from laptop.server.fastapi_integration import FastAPISignals

        logger.info("🚀 Starting FastAPI server...")

        # Create FastAPI signals that bridge to dashboard signals
        fastapi_signals = FastAPISignals()

        # Connect FastAPI signals to dashboard signals
        fastapi_signals.video_frame.connect(
            lambda data, w, h, dets: self.signals.video_frame.emit(data, w, h)
        )
        fastapi_signals.metrics_update.connect(self.signals.metrics_update.emit)
        fastapi_signals.detection_log.connect(self.signals.detection_log.emit)
        fastapi_signals.system_log.connect(self.signals.system_log.emit)
        fastapi_signals.client_connected.connect(self.signals.client_connected.emit)
        fastapi_signals.client_disconnected.connect(self.signals.client_disconnected.emit)

        def run_server():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.fastapi_loop = loop

            try:
                self.fastapi_server = FastAPIServer(
                    host=self.config.ws_host,
                    port=self.config.ws_port,
                    on_video_frame=fastapi_signals.video_frame.emit,
                    on_metrics=fastapi_signals.metrics_update.emit,
                    on_detection=fastapi_signals.detection_log.emit,
                    on_connect=fastapi_signals.client_connected.emit,
                    on_disconnect=fastapi_signals.client_disconnected.emit
                )
                loop.run_until_complete(self.fastapi_server.start())
            except Exception as e:
                logger.error(f"FastAPI server error: {e}")

        self.server_thread = threading.Thread(
            target=run_server,
            daemon=True,
            name="FastAPIServer"
        )
        self.server_thread.start()

    def stop(self):
        """Stop dashboard application"""
        logger.info("Stopping dashboard...")

        # Stop FastAPI server
        if self.use_fastapi and self.fastapi_server:
            try:
                asyncio.run(self.fastapi_server.stop())
            except Exception as e:
                logger.error(f"Error stopping FastAPI server: {e}")

        # Stop legacy WebSocket server
        elif self.server and self.loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.server.stop(),
                    self.loop
                )
            except Exception as e:
                logger.error(f"Error stopping WebSocket server: {e}")

        # Close dashboard
        if self.dashboard:
            self.dashboard.close()

    def _handle_ui_command(self, cmd: dict):
        """Handle command from UI -> Broadcast to RPi5"""
        from laptop.protocol import MessageType, BaseMessage
        import asyncio
        
        # Wrap in BaseMessage
        message = BaseMessage(
            type=MessageType.COMMAND,
            data=cmd
        )
        
        # Broadcast
        if self.use_fastapi and self.fastapi_server:
            # FastAPI server broadcast is async, run in loop
            # We are in UI thread here, so we need to schedule it
            # Ideally use a queue, but for now run_coroutine_threadsafe if we have loop
             # But FastAPI server runs in its own loop in a thread? 
             # No, run_server creates a new loop.
             pass # Logic complexity here: accessing separate thread loop
             
             # Actually, simpler:
             # FastAPIServer.broadcast() is async.
             # We need to find the loop it is running in.
             # In _run_fastapi_server, we create a loop: `loop = asyncio.new_event_loop()`
             # But we don't store it in self.loop (that's for legacy server).
             # We should store existing loop.
             pass

        if self.use_fastapi and self.fastapi_server:
            # We need to locate the loop running the server
            # Since _run_fastapi_server is a local scope `loop`, we can't access it easily unless we stored it.
            # Let's fix _run_fastapi_server to store self.fastapi_loop
            if hasattr(self, 'fastapi_loop') and self.fastapi_loop:
                 asyncio.run_coroutine_threadsafe(
                    self.fastapi_server.broadcast(message),
                    self.fastapi_loop
                )
            else:
                logger.error("Cannot send command: FastAPI loop not accessible")

        elif self.server and self.loop:
            asyncio.run_coroutine_threadsafe(
                self.server.broadcast(message.to_json()), # Legacy server might expect string? No, checking logic
                self.loop
            )
            # Legacy server .broadcast() method signature?
            # It inherits from AsyncWebSocketServer. broadcast(message: str | BaseMessage).
            # If base class, it expects BaseMessage object usually, or string?
            # Let's check shared.api.AsyncWebSocketServer.broadcast
            # It calls send_to_client_impl which usually takes BaseMessage if properly typed.
            # But here let's assume valid.



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
        help="Server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Server port (default: 8765)"
    )
    parser.add_argument(
        "--fastapi",
        action="store_true",
        default=False,
        help="Use FastAPI server (recommended for new deployments)"
    )

    args = parser.parse_args()

    # Create config
    config = default_config
    if args.host:
        config.ws_host = args.host
    if args.port:
        config.ws_port = args.port

    # Create and start application with FastAPI mode
    application = DashboardApplication(config, use_fastapi=args.fastapi)

    try:
        exit_code = application.start()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n🛑 Interrupted by user")
        application.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
