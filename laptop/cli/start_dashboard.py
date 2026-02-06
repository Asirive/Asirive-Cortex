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

from laptop.config import DashboardConfig, YOLOEConfig, default_config
from laptop.server.websocket_server import CortexWebSocketServer
from laptop.server.fastapi_server import FastAPIServer
from laptop.gui.cortex_ui import CortexDashboard as CortexDashboardUI, DashboardSignals
# CRITICAL FIX: Use shared.api consistently for protocol to avoid type mismatches
from shared.api import MessageType, BaseMessage


logger = logging.getLogger(__name__)


from laptop.server.video_receiver import VideoReceiver
from laptop.layer1_service import Layer1Service
import cv2

class DashboardApplication:
    """
    Main dashboard application
    
    Integrates WebSocket or FastAPI server with PyQt6 GUI using thread-safe signals.
    """

    def __init__(self, config: DashboardConfig = None, use_fastapi: bool = False):
        """Initialize dashboard application"""
        self.config = config or default_config
        self.use_fastapi = use_fastapi
        self._running = True  # Flag to track application state

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

        # Custom ZMQ Pipeline (Hybrid Architecture)
        self.zmq_receiver = VideoReceiver(port=5555, on_frame=self._handle_zmq_frame)
        self.yoloe_config = YOLOEConfig()
        self.layer1_service = Layer1Service(
            model_path=self.yoloe_config.model_path,      # yoloe-26x-seg.pt (text-prompt)
            device=self.yoloe_config.device,
            confidence=self.yoloe_config.confidence,       # 0.40 (raised from 0.25)
            class_names=self.yoloe_config.text_prompts     # ~118 curated classes
        )
        self.layer1_service.on_result = self._handle_inference_result

        # Metrics history (for last update tracking)
        self.last_metrics = {}

        # FastAPI specific
        self.fastapi_server = None
        self._uvicorn_loop = None  # Store Uvicorn's event loop for cross-thread communication

    def _handle_zmq_frame(self, frame_bgr):
        """Handle raw frame from ZMQ (runs in ZMQ thread)"""
        if not self._running:
            return

        try:
            # 1. Feed to inference engine
            self.layer1_service.process_frame(frame_bgr)
            
            # 2. Get latest inference results
            # (Inference runs async, so we just grab what's available to keep video smooth)
            # We need to map Layer1Service results format to UI format
            # Service returns: { "data": [ {class, confidence, bbox...} ] }
            # UI expects: [ {class, confidence, x1, y1...} ]
            
            # Since Layer1Service.on_result emits via signals separately,
            # we can either draw them here OR rely on the separate signal.
            # But UI draws detections ON TOP of the video frame.
            # So we should attach them here if we want them sync-ish.
            
            # Ideally:
            detections = self.layer1_service.latest_results # We need to access this property
            # Wait, I didn't verify if I exposed `latest_results` in Layer1Service.
            # I did: `self.latest_results = []` in __init__.
            # But the on_result callback is for logging/broadcasting events.
            
            # Convert frame to bytes (JPG for UI loading)
            # Qt loads from bytes.
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            h, w, ch = frame_rgb.shape
            
            # PyQt requires bytes or QImage. 
            # Our signal `.emit(frame_data, width, height, detections)`
            # In `start_dashboard.py` (legacy WS), `frame_data` was bytes.
            # In `cortex_ui.py`, `load_image_from_bytes` uses `QImage.fromData` which expects encoded file (JPG/PNG) OR raw bytes if we handle it.
            # The UI code: `image.loadFromData(data)`. This implies encoded image (JPG/PNG).
            
            # So we MUST encode to JPG here.
            # This is CPU overhead on Laptop (fine).
            ret, buffer = cv2.imencode('.jpg', frame_bgr)
            if ret:
                frame_bytes = buffer.tobytes()
                logger.debug(f"UI: Emitting frame {len(frame_bytes)} bytes + {len(detections)} dets")

                # Emit
                self.signals.video_frame.emit(frame_bytes, w, h, detections)
                logger.debug(f"[UI] video_frame signal emitted")
            else:
                 logger.error("Failed to encode frame for UI")
                
        except Exception as e:
            logger.error(f"ZMQ Handler Error: {e}")

    def _handle_inference_result(self, result: dict):
        """Handle inference result from Layer1Service - broadcast to RPi5 devices"""
        if not self._running:
            return
        
        detections = result.get("data", [])
        if not detections:
            return
        
        # Log locally for debugging
        logger.debug(f"Layer 1: {len(detections)} detections, broadcasting to RPi5")
        
        # Broadcast to connected RPi5 devices via WebSocket
        if self.use_fastapi and self.fastapi_server:
            try:
                from shared.api import BaseMessage, MessageType
                
                # Optimization: Strip absolute coordinates for network transmission
                # The RPi5 should use the normalized 'bbox' dict
                optimized_detections = []
                for det in detections:
                    # Create a copy to avoid modifying the original used by local UI
                    opt_det = det.copy()
                    # Remove absolute keys if they exist
                    for key in ['x1', 'y1', 'x2', 'y2']:
                        opt_det.pop(key, None)
                    optimized_detections.append(opt_det)
                
                # Create DETECTIONS message with source="laptop"
                msg = BaseMessage(
                    type=MessageType.DETECTIONS,
                    data={
                        "source": "laptop",
                        "layer": "layer1",
                        "detections": optimized_detections,
                        "inference_time_ms": result.get("inference_time_ms", 0)
                    }
                )
                
                # Get connection manager and broadcast
                connection_manager = getattr(self.fastapi_server, '_connection_manager', None)
                if connection_manager and connection_manager.get_connection_count() > 0:
                    import asyncio
                    
                    # Schedule broadcast on the event loop
                    # The FastAPI server thread has its own event loop
                    # CRITICAL FIX: Use run_coroutine_threadsafe with stored Uvicorn loop
                    if self._uvicorn_loop and self._uvicorn_loop.is_running():
                        try:
                            asyncio.run_coroutine_threadsafe(
                                connection_manager.broadcast(msg),
                                self._uvicorn_loop
                            )
                        except Exception as e:
                            logger.debug(f"Error scheduling broadcast: {e}")
                    else:
                        logger.debug("Uvicorn loop not available, skipping broadcast")
            except Exception as e:
                logger.debug(f"Error broadcasting laptop detections: {e}")

    def _create_message_handler(self):
        """Create message handler for WebSocket server"""
        async def handle_message(websocket, message: BaseMessage):
            """Handle incoming message from RPi5"""
            # Check if shutting down to avoid "wrapped C/C++ object deleted" errors
            if not self._running:
                return

            try:
                if message.type == MessageType.VIDEO_FRAME.value:
                    # WebSocket Video (Legacy/Fallback)
                    # Only process if ZMQ is NOT active or fails?
                    # For now, allow both but they might fight on UI.
                    # Hybrid Architecture implies ZMQ is primary.
                    # If ZMQ is working, RPi should NOT be sending WS frames.
                    pass 

                elif message.type == MessageType.METRICS.value:
                    # Handle metrics
                    metrics = message.data
                    self.last_metrics = metrics

                    # Emit signal to GUI
                    if self._running:
                        self.signals.metrics_update.emit(metrics)

                    # Log to system
                    logger.debug(f"Metrics: FPS={metrics.get('fps', 0):.1f}, "
                               f"RAM={metrics.get('ram_percent', 0):.1f}%, "
                               f"CPU={metrics.get('cpu_percent', 0):.1f}%")
                               
                # ... (rest of messages same) ...

                elif message.type == MessageType.DETECTIONS.value:
                    # Handle detection
                    detection = message.data
                    layer = detection.get("layer", "unknown")
                    class_name = detection.get("class_name", "unknown")
                    confidence = detection.get("confidence", 0.0)

                    # Emit signal to GUI with dict
                    if self._running:
                        self.signals.detection_log.emit(detection)

                    logger.info(f"Detection: {class_name} ({confidence:.2f}) [{layer}]")

                elif message.type == MessageType.STATUS.value:
                    # Handle status message
                    status = message.data.get("status", "unknown")
                    msg = message.data.get("message", "")

                    level = "INFO" if status == "connected" else "WARNING"
                    if self._running:
                        self.signals.system_log.emit(f"RPi5 Status: {msg}", level)
                        
                        # Forward mode changes to UI toggle
                        if status == "MODE_CHANGE":
                            self.signals.mode_changed.emit(msg)

                    logger.info(f"Status: {status} - {msg}")

                elif message.type == MessageType.AUDIO_EVENT.value:
                    # Handle audio event
                    event = message.data.get("event", "unknown")
                    text = message.data.get("text", "")
                    layer = message.data.get("layer", "unknown")

                    log_msg = f"Audio [{event}]: {text} (routed to {layer})"
                    if self._running:
                        self.signals.system_log.emit(log_msg, "INFO")

                    logger.info(f"Audio Event: {log_msg}")

                elif message.type == MessageType.MEMORY_EVENT.value:
                    # Handle memory event
                    event = message.data.get("event", "unknown")
                    local_rows = message.data.get("local_rows", 0)
                    synced_rows = message.data.get("synced_rows", 0)
                    queue_size = message.data.get("upload_queue", 0)

                    log_msg = f"Memory [{event}]: Local={local_rows}, Synced={synced_rows}, Queue={queue_size}"
                    if self._running:
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

                elif message.type == "LAYER1_QUERY":
                    # Handle Layer 1 detection query from RPi5
                    # RPi5 sends a frame, we run YOLOE inference and send back detections
                    try:
                        import base64
                        import cv2
                        import numpy as np
                        
                        frame_b64 = message.data.get("frame")
                        if frame_b64 and self.layer1_service:
                            # Decode frame
                            frame_bytes = base64.b64decode(frame_b64)
                            nparr = np.frombuffer(frame_bytes, np.uint8)
                            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            
                            if frame is not None:
                                # Run Layer 1 inference
                                result = self.layer1_service.run_inference(frame)
                                detections = result.get("data", [])
                                
                                # Send response back to RPi5
                                response = {
                                    "type": "LAYER1_RESPONSE",
                                    "timestamp": datetime.utcnow().isoformat() + "Z",
                                    "data": {
                                        "detections": detections,
                                        "inference_time_ms": result.get("inference_time_ms", 0),
                                        "source": "laptop"
                                    }
                                }
                                await websocket.send(json.dumps(response))
                                logger.debug(f"LAYER1_QUERY: Sent {len(detections)} detections to RPi5")
                    except Exception as e:
                        logger.error(f"Error handling LAYER1_QUERY: {e}")

            except RuntimeError:
                # Ignore "wrapped C/C++ object deleted" errors during shutdown
                pass
            except Exception as e:
                # Log other errors only if running
                if self._running:
                    logger.error(f"Error handling message: {e}")

        # CRITICAL FIX: Return the handler function
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
            self.signals.mode_changed.connect(self.dashboard.on_mode_changed)

            # Show dashboard
            self.dashboard.show()

            # Connect UI Logic for Sending Commands
            self.signals.send_command.connect(self._handle_ui_command)

            # Start ZMQ Pipeline (Hybrid Architecture)
            logger.info("Starting ZMQ Video Receiver...")
            self.zmq_receiver.start()
            self.layer1_service.start()

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
            logger.info(f"   ZMQ Receiver: 0.0.0.0:5555")
            logger.info(f"   GUI: {self.config.gui_width}x{self.config.gui_height}")
            logger.info("   Waiting for RPi5 connections...")

            mode_str = "FastAPI" if self.use_fastapi else "WebSocket"
            self.dashboard.on_system_log("Dashboard started successfully", "SUCCESS")
            self.dashboard.on_system_log(f"{mode_str} server listening on {self.config.ws_host}:{self.config.ws_port}", "INFO")
            self.dashboard.on_system_log("ZMQ Receiver active on port 5555", "INFO")
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
            lambda data, w, h, dets: self.signals.video_frame.emit(data, w, h, dets)
        )
        fastapi_signals.metrics_update.connect(self.signals.metrics_update.emit)
        fastapi_signals.detection_log.connect(self.signals.detection_log.emit)
        fastapi_signals.system_log.connect(self.signals.system_log.emit)
        fastapi_signals.client_connected.connect(self.signals.client_connected.emit)
        fastapi_signals.client_disconnected.connect(self.signals.client_disconnected.emit)
        
        # Bridge status updates — detect MODE_CHANGE and emit mode_changed
        def _handle_fastapi_status(status: str, msg: str):
            self.signals.system_log.emit(f"RPi5 Status: {msg}", "INFO")
            if status == "MODE_CHANGE":
                self.signals.mode_changed.emit(msg)
        fastapi_signals.status_update.connect(_handle_fastapi_status)

        def run_server():
            # Standard blocking uvicorn run
            import uvicorn
            from laptop.server.fastapi_server import app, set_server_instance, set_dashboard_runner

            # Setup the Logic Handler (with signals)
            # We don't need to call .start() on it because Uvicorn drives the loop
            # But we do need it initialized
            from shared.api import ServerConfig
            server_config = ServerConfig(
                host=self.config.ws_host,
                port=self.config.ws_port,
                max_clients=self.config.ws_max_clients
            )

            try:
                logger.info(f"Initializing FastAPIServer logic handler")
                self.fastapi_server = FastAPIServer(
                    config=server_config,
                    on_video_frame=fastapi_signals.video_frame.emit,
                    on_metrics=fastapi_signals.metrics_update.emit,
                    on_detection=fastapi_signals.detection_log.emit,
                    on_connect=fastapi_signals.client_connected.emit,
                    on_disconnect=fastapi_signals.client_disconnected.emit,
                    on_status=fastapi_signals.status_update.emit
                )

                # Inject into FastAPI app global state
                set_server_instance(self.fastapi_server)
                # Store reference to dashboard runner so Uvicorn startup can capture the loop
                set_dashboard_runner(self)

                logger.info(f"Launching Uvicorn on {self.config.ws_host}:{self.config.ws_port}")
                # Note: Event loop will be captured in Uvicorn startup event
                uvicorn.run(
                    app,
                    host=self.config.ws_host,
                    port=self.config.ws_port,
                    log_level="info",
                    ws_ping_interval=None, # We handle pings manually in shared protocol
                    ws_ping_timeout=None
                )
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
        self._running = False  # Signal threads to stop emitting
        
        # Stop ZMQ Pipeline
        if self.zmq_receiver:
            self.zmq_receiver.stop()
        if self.layer1_service:
            self.layer1_service.stop()

        # Stop FastAPI server
        if self.use_fastapi and self.fastapi_server:
            try:
                # CRITICAL FIX: Use run_coroutine_threadsafe with stored Uvicorn loop
                if self._uvicorn_loop and self._uvicorn_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self.fastapi_server.stop(),
                        self._uvicorn_loop
                    )
                    future.result(timeout=10.0)  # Wait up to 10 seconds
                else:
                    logger.warning("Uvicorn loop not available, cannot stop server cleanly")
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

    def _handle_local_command(self, cmd: dict):
        """Handle local laptop commands"""
        try:
            action = cmd.get("action")
            
            if action == "SET_CONFIDENCE":
                conf = float(cmd.get("confidence", 0.5))
                if self.layer1_service:
                    self.layer1_service.confidence = conf
                    logger.info(f"🔧 Local Layer 1 Confidence set to {conf:.2f}")
                    
            elif action == "SET_MODEL":
                model_name = cmd.get("model")
                logger.info(f"🔧 Request to switch local model to {model_name}")
                if self.layer1_service:
                    self.layer1_service.set_model(model_name)
                
        except Exception as e:
            logger.error(f"Error executing local command: {e}")

    def _handle_ui_command(self, cmd: dict):
        """Handle command from UI -> Broadcast to RPi5"""

        # 1. Check for local target (Server Tab)
        if cmd.get("target") == "local":
            self._handle_local_command(cmd)
            return

        import asyncio

        logger.info(f"📤 UI Command: {cmd.get('action', cmd)}")
        logger.info(f"📤 Full command payload: {cmd}")

        # Broadcast
        if self.use_fastapi and self.fastapi_server:
            # FastAPI server runs in a separate thread with its own event loop
            # We need to use the global connection manager from fastapi_server module

            from laptop.server.fastapi_server import get_connection_manager
            connection_manager = get_connection_manager()
            
            if connection_manager and connection_manager.get_connection_count() > 0:
                # Create a command message (using shared.api imports from top of file)
                cmd_msg = BaseMessage(
                    type=MessageType.COMMAND,
                    data=cmd
                )
                
                # Broadcast to all connected devices
                connected_devices = connection_manager.get_connected_devices()
                logger.info(f"📡 Broadcasting to {len(connected_devices)} device(s): {connected_devices}")
                
                for device_id in connected_devices:
                    try:
                        # CRITICAL FIX: Use Uvicorn's event loop, not a new one
                        # The WebSocket was created in Uvicorn's loop, so we must use that loop
                        if self._uvicorn_loop and self._uvicorn_loop.is_running():
                            # Schedule the coroutine in Uvicorn's loop
                            future = asyncio.run_coroutine_threadsafe(
                                connection_manager.send_message(device_id, cmd_msg),
                                self._uvicorn_loop
                            )
                            try:
                                # Wait for completion with timeout
                                result = future.result(timeout=5.0)
                                if result:
                                    logger.info(f"✅ Command sent to {device_id}")
                                else:
                                    logger.warning(f"⚠️ Send returned False for {device_id}")
                            except Exception as e:
                                logger.error(f"❌ Failed to send to {device_id}: {e}")
                        else:
                            logger.warning(f"⚠️ Uvicorn loop not available for {device_id}, cannot send")
                        
                    except Exception as e:
                        logger.warning(f"Could not send command to {device_id}: {e}")
            else:
                if not connection_manager:
                    logger.warning("⚠️ Connection manager not ready, cannot broadcast command")
                else:
                    logger.warning("⚠️ No devices connected, cannot broadcast command")

        elif self.server and self.loop:
            # Legacy WebSocket server mode - create message using shared.api
            message = BaseMessage(
                type=MessageType.COMMAND,
                data=cmd
            )
            asyncio.run_coroutine_threadsafe(
                self.server.broadcast(message.to_json()),
                self.loop
            )



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
