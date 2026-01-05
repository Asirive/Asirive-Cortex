"""
Project-Cortex v2.0 - Laptop Real-Time Monitor (PyQt6 GUI)

Professional monitoring interface for real-time visualization of RPi wearable data.
Displays video feed, metrics dashboard, detection logs, and provides command interface.

Features:
- Real-time video feed rendering (30 FPS)
- Metrics dashboard (FPS, latency, RAM, battery)
- Detection log with timestamps
- WebSocket server integration (Port 8765)
- Graceful degradation (works without RPi connection)
- Future-proof for companion app integration

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: January 3, 2026
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
import asyncio
import threading
import base64
from io import BytesIO

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QGroupBox, QSplitter, QStatusBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QPalette
from PIL import Image
import numpy as np

# Import server components
from .websocket_server import WebSocketServer
from .protocol import MessageType
from .config import (
    GUI_TITLE, GUI_WIDTH, GUI_HEIGHT, GUI_VIDEO_FPS,
    GUI_METRICS_UPDATE_RATE, VIDEO_WIDTH, VIDEO_HEIGHT,
    WS_SERVER_PORT, LOG_LEVEL
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WebSocketServerThread(QThread):
    """
    Background thread for running asyncio WebSocket server.
    
    Runs the WebSocket server in a separate thread with its own event loop.
    Communicates with GUI via Qt signals for thread safety.
    """
    
    # Signals for thread-safe communication with GUI
    connection_status_changed = pyqtSignal(bool, int)  # (is_connected, num_clients)
    message_received = pyqtSignal(str, dict)  # (message_type, data)
    server_error = pyqtSignal(str)  # error_message
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.server: Optional[WebSocketServer] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.running = False
    
    def run(self):
        """Run WebSocket server in asyncio event loop."""
        try:
            # Create new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Create server with GUI callback
            self.server = WebSocketServer(gui_callback=self._on_message)
            
            # Start server
            self.running = True
            logger.info("🔄 Starting WebSocket server thread...")
            
            # Run server
            self.loop.run_until_complete(self.server.start())
            
        except Exception as e:
            logger.error(f"❌ WebSocket server thread error: {e}", exc_info=True)
            self.server_error.emit(str(e))
        
        finally:
            self.running = False
            if self.loop:
                self.loop.close()
    
    def _on_message(self, msg_type: str, data: dict):
        """Callback for WebSocket messages (runs in asyncio thread)."""
        # Emit signal to forward to GUI thread
        self.message_received.emit(msg_type, data)
        
        # Update connection status
        if self.server:
            num_clients = len(self.server.connections)
            self.connection_status_changed.emit(num_clients > 0, num_clients)
    
    def stop_server(self):
        """Stop the WebSocket server gracefully."""
        if self.server and self.loop:
            logger.info("🛑 Stopping WebSocket server...")
            
            # Schedule stop in asyncio loop
            asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop)
            
            # Give it time to cleanup
            self.wait(2000)  # Wait up to 2 seconds


class CortexMonitorGUI(QMainWindow):
    """
    Main PyQt6 GUI for monitoring RPi wearable in real-time.
    
    This is the Tier 2 visualization system that receives data from Tier 1 (RPi)
    via WebSocket and displays it for competition demos and development.
    """
    
    def __init__(self):
        super().__init__()
        
        # State variables
        self.connected = False
        self.num_clients = 0
        self.last_video_frame: Optional[QPixmap] = None
        self.metrics_data: Dict[str, Any] = {}
        self.detection_count = 0
        
        # WebSocket server thread
        self.ws_thread: Optional[WebSocketServerThread] = None
        
        # UI setup
        self.init_ui()
        
        # Start WebSocket server
        self.start_websocket_server()
        
        # Status update timer
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status_bar)
        self.status_timer.start(1000)  # Update every second
        
        logger.info("✅ Cortex Monitor GUI initialized")
    
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle(GUI_TITLE)
        self.setGeometry(100, 100, GUI_WIDTH, GUI_HEIGHT)
        
        # Apply dark theme
        self.apply_dark_theme()
        
        # Main layout with splitter
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # Create splitter for video/logs
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # === LEFT PANEL: Video Feed ===
        video_panel = self.create_video_panel()
        splitter.addWidget(video_panel)
        
        # === RIGHT PANEL: Metrics & Logs ===
        info_panel = self.create_info_panel()
        splitter.addWidget(info_panel)
        
        # Set initial splitter sizes (70% video, 30% info)
        splitter.setSizes([int(GUI_WIDTH * 0.7), int(GUI_WIDTH * 0.3)])
        
        main_layout.addWidget(splitter)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(f"WebSocket Server: ws://0.0.0.0:{WS_SERVER_PORT} (Waiting for RPi...)")
    
    def apply_dark_theme(self):
        """Apply dark theme styling."""
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Base, QColor(20, 20, 20))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(40, 40, 40))
        palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Button, QColor(40, 40, 40))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        
        self.setPalette(palette)
        
        # Set stylesheet for additional styling
        self.setStyleSheet("""
            QGroupBox {
                border: 2px solid #444;
                border-radius: 5px;
                margin-top: 10px;
                font-weight: bold;
                padding: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QTextEdit {
                background-color: #1a1a1a;
                color: #00ff00;
                font-family: 'Courier New', monospace;
                border: 1px solid #444;
            }
            QPushButton {
                background-color: #2a5a8a;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a7aaa;
            }
            QPushButton:pressed {
                background-color: #1a4a7a;
            }
        """)
    
    def create_video_panel(self) -> QWidget:
        """Create video feed panel."""
        panel = QGroupBox("📹 Live Camera Feed")
        layout = QVBoxLayout()
        
        # Video display label
        self.video_label = QLabel()
        self.video_label.setMinimumSize(VIDEO_WIDTH, VIDEO_HEIGHT)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("border: 2px solid #444; background-color: black;")
        
        # Set placeholder text
        self.video_label.setText("Waiting for video stream from RPi...\n\nMake sure RPi is:\n1. Connected to same network\n2. Running cortex_gui.py with WebSocket enabled")
        self.video_label.setStyleSheet("border: 2px solid #444; background-color: black; color: #888; font-size: 16px;")
        
        layout.addWidget(self.video_label)
        
        # Video controls
        controls_layout = QHBoxLayout()
        
        self.record_btn = QPushButton("⏺️ Record")
        self.record_btn.clicked.connect(self.toggle_recording)
        self.record_btn.setEnabled(False)  # Disable until connected
        
        self.snapshot_btn = QPushButton("📸 Snapshot")
        self.snapshot_btn.clicked.connect(self.take_snapshot)
        self.snapshot_btn.setEnabled(False)
        
        controls_layout.addWidget(self.record_btn)
        controls_layout.addWidget(self.snapshot_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        panel.setLayout(layout)
        return panel
    
    def create_info_panel(self) -> QWidget:
        """Create info panel with metrics and logs."""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # === METRICS DASHBOARD ===
        metrics_group = QGroupBox("📊 Performance Metrics")
        metrics_layout = QVBoxLayout()
        
        # Create metric labels
        self.fps_label = self.create_metric_label("FPS:", "--", "#00ff00")
        self.latency_label = self.create_metric_label("Latency:", "--", "#ffff00")
        self.ram_label = self.create_metric_label("RAM:", "--", "#00ffff")
        self.cpu_label = self.create_metric_label("CPU:", "--", "#ff00ff")
        self.battery_label = self.create_metric_label("Battery:", "--", "#00ff00")
        self.layer_label = self.create_metric_label("Active Layer:", "--", "#ff8800")
        
        metrics_layout.addWidget(self.fps_label)
        metrics_layout.addWidget(self.latency_label)
        metrics_layout.addWidget(self.ram_label)
        metrics_layout.addWidget(self.cpu_label)
        metrics_layout.addWidget(self.battery_label)
        metrics_layout.addWidget(self.layer_label)
        
        metrics_group.setLayout(metrics_layout)
        layout.addWidget(metrics_group)
        
        # === DETECTION LOG ===
        detection_group = QGroupBox("🎯 Detection Log")
        detection_layout = QVBoxLayout()
        
        self.detection_log = QTextEdit()
        self.detection_log.setReadOnly(True)
        self.detection_log.setMaximumHeight(200)
        self.detection_log.setPlaceholderText("Waiting for detections from RPi...")
        
        detection_layout.addWidget(self.detection_log)
        detection_group.setLayout(detection_layout)
        layout.addWidget(detection_group)
        
        # === SYSTEM LOG ===
        log_group = QGroupBox("📜 System Log")
        log_layout = QVBoxLayout()
        
        self.system_log = QTextEdit()
        self.system_log.setReadOnly(True)
        self.system_log.setPlaceholderText("System messages will appear here...")
        
        log_layout.addWidget(self.system_log)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # === COMMAND PANEL ===
        command_group = QGroupBox("🎮 Commands")
        command_layout = QVBoxLayout()
        
        self.clear_log_btn = QPushButton("🗑️ Clear Logs")
        self.clear_log_btn.clicked.connect(self.clear_logs)
        
        command_layout.addWidget(self.clear_log_btn)
        command_group.setLayout(command_layout)
        layout.addWidget(command_group)
        
        panel.setLayout(layout)
        return panel
    
    def create_metric_label(self, label: str, value: str, color: str) -> QLabel:
        """Create a styled metric label."""
        text = f"{label} <span style='color:{color};'>{value}</span>"
        label_widget = QLabel(text)
        label_widget.setFont(QFont("Arial", 12))
        label_widget.setTextFormat(Qt.TextFormat.RichText)
        return label_widget
    
    def start_websocket_server(self):
        """Start WebSocket server in background thread."""
        self.log_message("🚀 Starting WebSocket server...", "info")
        
        self.ws_thread = WebSocketServerThread()
        
        # Connect signals
        self.ws_thread.connection_status_changed.connect(self.on_connection_status_changed)
        self.ws_thread.message_received.connect(self.on_message_received)
        self.ws_thread.server_error.connect(self.on_server_error)
        
        # Start thread
        self.ws_thread.start()
        
        self.log_message(f"✅ WebSocket server started on port {WS_SERVER_PORT}", "info")
    
    @pyqtSlot(bool, int)
    def on_connection_status_changed(self, is_connected: bool, num_clients: int):
        """Handle connection status changes."""
        self.connected = is_connected
        self.num_clients = num_clients
        
        if is_connected:
            self.log_message(f"✅ RPi connected ({num_clients} client(s))", "success")
            self.record_btn.setEnabled(True)
            self.snapshot_btn.setEnabled(True)
        else:
            self.log_message("🔌 RPi disconnected", "warning")
            self.record_btn.setEnabled(False)
            self.snapshot_btn.setEnabled(False)
    
    @pyqtSlot(str, dict)
    def on_message_received(self, msg_type: str, data: dict):
        """Handle incoming WebSocket messages."""
        try:
            if msg_type == MessageType.METRICS.value:
                self.update_metrics(data)
            
            elif msg_type == MessageType.DETECTIONS.value:
                self.update_detections(data)
            
            elif msg_type == MessageType.VIDEO_FRAME.value:
                self.update_video_frame(data)
            
            elif msg_type == MessageType.STATUS.value:
                level = data.get("level", "info")
                status = data.get("status", "")
                self.log_message(f"[RPi] {status}", level)
            
            elif msg_type == MessageType.AUDIO_EVENT.value:
                event = data.get("event", "")
                text = data.get("text", "")
                self.log_message(f"🎙️ Audio: {event} - {text}", "info")
            
            elif msg_type == MessageType.MEMORY_EVENT.value:
                event = data.get("event", "")
                obj_name = data.get("object_name", "")
                self.log_message(f"💾 Memory: {event} - {obj_name}", "info")
        
        except Exception as e:
            logger.error(f"❌ Error processing message: {e}", exc_info=True)
    
    @pyqtSlot(str)
    def on_server_error(self, error_message: str):
        """Handle server errors."""
        self.log_message(f"❌ Server Error: {error_message}", "error")
    
    def update_metrics(self, data: dict):
        """Update metrics display."""
        self.metrics_data = data
        
        # Update labels with colored values
        fps = data.get("fps", 0)
        self.fps_label.setText(f"FPS: <span style='color:#00ff00;'>{fps:.1f}</span>")
        
        latency = data.get("latency_ms", 0)
        latency_color = "#00ff00" if latency < 100 else "#ffff00" if latency < 200 else "#ff0000"
        self.latency_label.setText(f"Latency: <span style='color:{latency_color};'>{latency:.0f}ms</span>")
        
        ram_usage = data.get("ram_usage_gb", 0)
        ram_total = data.get("ram_total_gb", 4)
        ram_percent = (ram_usage / ram_total) * 100
        ram_color = "#00ff00" if ram_percent < 70 else "#ffff00" if ram_percent < 85 else "#ff0000"
        self.ram_label.setText(f"RAM: <span style='color:{ram_color};'>{ram_usage:.1f}GB / {ram_total:.1f}GB ({ram_percent:.0f}%)</span>")
        
        cpu = data.get("cpu_usage_percent", 0)
        cpu_color = "#00ff00" if cpu < 70 else "#ffff00" if cpu < 85 else "#ff0000"
        self.cpu_label.setText(f"CPU: <span style='color:{cpu_color};'>{cpu:.0f}%</span>")
        
        battery = data.get("battery_percent")
        if battery is not None:
            battery_color = "#00ff00" if battery > 50 else "#ffff00" if battery > 20 else "#ff0000"
            self.battery_label.setText(f"Battery: <span style='color:{battery_color};'>{battery:.0f}%</span>")
        else:
            self.battery_label.setText(f"Battery: <span style='color:#888;'>N/A</span>")
        
        layer = data.get("active_layer", "unknown")
        self.layer_label.setText(f"Active Layer: <span style='color:#ff8800;'>{layer}</span>")
    
    def update_detections(self, data: dict):
        """Update detection log."""
        self.detection_count += 1
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        merged = data.get("merged_detections", "nothing")
        count = data.get("detection_count", 0)
        mode = data.get("yoloe_mode", "unknown")
        
        log_entry = f"[{timestamp}] Detected ({count}): {merged} | Mode: {mode}"
        
        self.detection_log.append(log_entry)
        
        # Auto-scroll to bottom
        scrollbar = self.detection_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        # Limit log size
        if self.detection_count > 100:
            self.detection_log.clear()
            self.detection_count = 0
    
    def update_video_frame(self, data: dict):
        """Update video display with new frame."""
        try:
            # Decode base64 frame
            frame_data = data.get("frame_data", "")
            if not frame_data:
                return
            
            # Decode base64
            frame_bytes = base64.b64decode(frame_data)
            
            # Convert to QPixmap
            image = Image.open(BytesIO(frame_bytes))
            image_array = np.array(image)
            
            # Convert to Qt format
            height, width, channels = image_array.shape
            bytes_per_line = channels * width
            
            qt_image = QImage(
                image_array.data,
                width,
                height,
                bytes_per_line,
                QImage.Format.Format_RGB888
            )
            
            pixmap = QPixmap.fromImage(qt_image)
            
            # Scale to fit label while maintaining aspect ratio
            scaled_pixmap = pixmap.scaled(
                self.video_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # Update display
            self.video_label.setPixmap(scaled_pixmap)
            self.last_video_frame = pixmap
            
        except Exception as e:
            logger.error(f"❌ Failed to update video frame: {e}")
    
    def log_message(self, message: str, level: str = "info"):
        """Add message to system log."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # Color based on level
        colors = {
            "info": "#00ffff",
            "success": "#00ff00",
            "warning": "#ffff00",
            "error": "#ff0000"
        }
        color = colors.get(level, "#ffffff")
        
        log_entry = f"<span style='color:#888;'>[{timestamp}]</span> <span style='color:{color};'>{message}</span>"
        self.system_log.append(log_entry)
        
        # Auto-scroll
        scrollbar = self.system_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def update_status_bar(self):
        """Update status bar with current info."""
        if self.connected:
            status = f"✅ Connected ({self.num_clients} client(s)) | Port: {WS_SERVER_PORT}"
            
            if self.metrics_data:
                fps = self.metrics_data.get("fps", 0)
                latency = self.metrics_data.get("latency_ms", 0)
                status += f" | FPS: {fps:.1f} | Latency: {latency:.0f}ms"
        else:
            status = f"⏳ Waiting for RPi connection on ws://0.0.0.0:{WS_SERVER_PORT}"
        
        self.status_bar.showMessage(status)
    
    def toggle_recording(self):
        """Toggle video recording (placeholder)."""
        # TODO: Implement video recording
        self.log_message("📹 Video recording not yet implemented", "warning")
    
    def take_snapshot(self):
        """Save current video frame (placeholder)."""
        if self.last_video_frame:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"snapshot_{timestamp}.jpg"
            
            # TODO: Save to proper location
            self.log_message(f"📸 Snapshot saved: {filename}", "success")
        else:
            self.log_message("⚠️ No video frame available", "warning")
    
    def clear_logs(self):
        """Clear all logs."""
        self.detection_log.clear()
        self.system_log.clear()
        self.detection_count = 0
        self.log_message("🗑️ Logs cleared", "info")
    
    def closeEvent(self, event):
        """Handle application close."""
        self.log_message("👋 Shutting down Cortex Monitor...", "info")
        
        # Stop WebSocket server
        if self.ws_thread and self.ws_thread.isRunning():
            self.ws_thread.stop_server()
            self.ws_thread.quit()
            self.ws_thread.wait()
        
        logger.info("✅ Cortex Monitor GUI closed")
        event.accept()


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Use Fusion style for consistent look
    
    # Create and show GUI
    gui = CortexMonitorGUI()
    gui.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
