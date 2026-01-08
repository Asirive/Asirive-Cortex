"""
PyQt6 Dashboard for ProjectCortex

Real-time monitoring dashboard with:
- Live video feed from RPi5 camera
- System metrics (FPS, RAM, CPU, battery)
- Detection log (scrolling list)
- System log (color-coded messages)
- Dark theme for professional appearance

Thread-safe updates using Qt signals/slots.

Author: Haziq (@IRSPlays)
Date: January 8, 2026
"""

import sys
import os

# Add project root to path so laptop module can be found
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import logging
from datetime import datetime
from typing import Dict, Any, Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QScrollArea, QFrame, QSplitter, QGroupBox,
    QPushButton, QStatusBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPalette, QColor
import base64
import io

from laptop.config import DashboardConfig
from laptop.protocol import MessageType, BaseMessage


logger = logging.getLogger(__name__)


# ============================================================================
# SIGNAL BRIDGE (Thread-safe communication)
# ============================================================================

class DashboardSignals(QObject):
    """Signals for thread-safe GUI updates"""
    video_frame = pyqtSignal(bytes, int, int)  # frame_data, width, height
    metrics_update = pyqtSignal(dict)  # metrics data
    detection_log = pyqtSignal(str)  # log message
    system_log = pyqtSignal(str, str)  # log message, level
    client_connected = pyqtSignal(str)  # client address
    client_disconnected = pyqtSignal(str)  # client address


# ============================================================================
# VIDEO WIDGET
# ============================================================================

class VideoWidget(QLabel):
    """Widget for displaying live video feed"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #000; border: 2px solid #333;")
        self.setText("📹 Waiting for video stream...")
        self.setStyleSheet("color: #666; font-size: 16px;")

    def update_frame(self, frame_data: bytes, width: int, height: int):
        """Update video frame"""
        try:
            # Decode base64 JPEG
            image = QImage.fromData(frame_data)
            if image.isNull():
                logger.warning("Failed to decode image")
                return

            # Scale to fit widget
            pixmap = QPixmap.fromImage(image)
            scaled_pixmap = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            self.setPixmap(scaled_pixmap)

        except Exception as e:
            logger.error(f"Error updating video frame: {e}")

    def clear_frame(self):
        """Clear video display"""
        self.clear()
        self.setText("📹 No video signal")


# ============================================================================
# METRICS WIDGET
# ============================================================================

class MetricsWidget(QFrame):
    """Widget for displaying system metrics"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setStyleSheet("""
            QFrame {
                background-color: #252526;
                border: 1px solid #3e3e42;
                border-radius: 5px;
                padding: 10px;
            }
            QLabel {
                color: #cccccc;
                font-size: 14px;
                font-weight: bold;
            }
            .value {
                color: #4ec9b0;
                font-size: 18px;
            }
            .warning {
                color: #ce9178;
            }
            .error {
                color: #f48771;
            }
        """)

        layout = QVBoxLayout()
        layout.setSpacing(10)

        # Title
        title = QLabel("📊 System Metrics")
        title.setStyleSheet("color: #007acc; font-size: 16px;")
        layout.addWidget(title)

        # Metrics grid
        metrics_layout = QVBoxLayout()

        self.fps_label = self.create_metric_label("FPS:", "--")
        self.ram_label = self.create_metric_label("RAM:", "--")
        self.cpu_label = self.create_metric_label("CPU:", "--")
        self.battery_label = self.create_metric_label("Battery:", "--")
        self.temp_label = self.create_metric_label("Temperature:", "--")
        self.mode_label = self.create_metric_label("Mode:", "--")

        metrics_layout.addWidget(self.fps_label)
        metrics_layout.addWidget(self.ram_label)
        metrics_layout.addWidget(self.cpu_label)
        metrics_layout.addWidget(self.battery_label)
        metrics_layout.addWidget(self.temp_label)
        metrics_layout.addWidget(self.mode_label)

        layout.addLayout(metrics_layout)
        layout.addStretch()
        self.setLayout(layout)

    def create_metric_label(self, title: str, default: str) -> QLabel:
        """Create a metric label with title and value"""
        label = QLabel(f"{title} <span class='value'>{default}</span>")
        return label

    def update_metrics(self, metrics: Dict[str, Any]):
        """Update metrics display"""
        try:
            # FPS
            fps = metrics.get("fps", 0)
            self.fps_label.setText(f"FPS: <span class='value'>{fps:.1f}</span>")

            # RAM
            ram_mb = metrics.get("ram_mb", 0)
            ram_percent = metrics.get("ram_percent", 0)
            ram_class = "value" if ram_percent < 70 else "warning" if ram_percent < 90 else "error"
            self.ram_label.setText(f"RAM: <span class='{ram_class}'>{ram_mb} MB ({ram_percent:.1f}%)</span>")

            # CPU
            cpu = metrics.get("cpu_percent", 0)
            cpu_class = "value" if cpu < 70 else "warning" if cpu < 90 else "error"
            self.cpu_label.setText(f"CPU: <span class='{cpu_class}'>{cpu:.1f}%</span>")

            # Battery
            battery = metrics.get("battery_percent", 0)
            battery_class = "value" if battery > 50 else "warning" if battery > 20 else "error"
            self.battery_label.setText(f"Battery: <span class='{battery_class}'>{battery}%</span>")

            # Temperature
            temp = metrics.get("temperature", 0)
            temp_class = "value" if temp < 60 else "warning" if temp < 75 else "error"
            self.temp_label.setText(f"Temperature: <span class='{temp_class}'>{temp:.1f}°C</span>")

            # Mode
            mode = metrics.get("current_mode", "Unknown")
            self.mode_label.setText(f"Mode: <span class='value'>{mode}</span>")

        except Exception as e:
            logger.error(f"Error updating metrics: {e}")


# ============================================================================
# DETECTION LOG WIDGET
# ============================================================================

class DetectionLogWidget(QFrame):
    """Widget for displaying detection log"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setStyleSheet("""
            QFrame {
                background-color: #252526;
                border: 1px solid #3e3e42;
                border-radius: 5px;
                padding: 10px;
            }
            QLabel {
                color: #cccccc;
                font-size: 14px;
                font-weight: bold;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #cccccc;
                border: none;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
            }
        """)

        layout = QVBoxLayout()

        # Title
        title = QLabel("🎯 Detection Log")
        title.setStyleSheet("color: #007acc; font-size: 16px;")
        layout.addWidget(title)

        # Log display
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMaximumHeight(200)
        layout.addWidget(self.log_display)

        self.setLayout(layout)

        self.max_entries = 100

    def add_detection(self, detection: Dict[str, Any]):
        """Add detection to log"""
        try:
            layer = detection.get("layer", "unknown")
            class_name = detection.get("class_name", "unknown")
            confidence = detection.get("confidence", 0.0)
            source = detection.get("source", "base")
            mode = detection.get("detection_mode", "")

            # Format timestamp
            timestamp = datetime.now().strftime("%H:%M:%S")

            # Format detection
            log_entry = f"[{timestamp}] {layer.upper()}: {class_name} ({confidence:.2f})"
            if source != "base":
                log_entry += f" [{source}]"
            if mode:
                log_entry += f" ({mode})"

            # Color coding
            if confidence > 0.8:
                color = "#4ec9b0"  # Green
            elif confidence > 0.6:
                color = "#ce9178"  # Orange
            else:
                color = "#f48771"  # Red

            # Add to log
            self.log_display.append(f'<span style="color: {color};">{log_entry}</span>')

            # Auto-scroll
            if self.log_display.verticalScrollBar():
                self.log_display.verticalScrollBar().setValue(
                    self.log_display.verticalScrollBar().maximum()
                )

            # Trim old entries
            self._trim_log()

        except Exception as e:
            logger.error(f"Error adding detection: {e}")

    def _trim_log(self):
        """Trim log to max entries"""
        # Note: QTextEdit doesn't have easy way to count lines
        # This is simplified - in production, you'd track line count
        pass


# ============================================================================
# SYSTEM LOG WIDGET
# ============================================================================

class SystemLogWidget(QFrame):
    """Widget for displaying system log"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setStyleSheet("""
            QFrame {
                background-color: #252526;
                border: 1px solid #3e3e42;
                border-radius: 5px;
                padding: 10px;
            }
            QLabel {
                color: #cccccc;
                font-size: 14px;
                font-weight: bold;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #cccccc;
                border: none;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
            }
        """)

        layout = QVBoxLayout()

        # Title
        title = QLabel("📝 System Log")
        title.setStyleSheet("color: #007acc; font-size: 16px;")
        layout.addWidget(title)

        # Log display
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        layout.addWidget(self.log_display)

        self.setLayout(layout)

    def add_log(self, message: str, level: str = "INFO"):
        """Add log message"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")

            # Color coding
            if level == "ERROR":
                color = "#f48771"  # Red
            elif level == "WARNING":
                color = "#ce9178"  # Orange
            elif level == "SUCCESS":
                color = "#4ec9b0"  # Green
            else:
                color = "#9cdcfe"  # Blue

            log_entry = f'<span style="color: {color};">[{timestamp}] [{level}] {message}</span>'
            self.log_display.append(log_entry)

            # Auto-scroll
            if self.log_display.verticalScrollBar():
                self.log_display.verticalScrollBar().setValue(
                    self.log_display.verticalScrollBar().maximum()
                )

        except Exception as e:
            logger.error(f"Error adding log: {e}")


# ============================================================================
# MAIN DASHBOARD WINDOW
# ============================================================================

class CortexDashboard(QMainWindow):
    """Main dashboard window"""

    def __init__(self, config: DashboardConfig):
        super().__init__()
        self.config = config
        self.signals = DashboardSignals()

        # Setup window
        self.setWindowTitle(config.gui_title)
        self.resize(config.gui_width, config.gui_height)

        # Apply dark theme
        self._apply_dark_theme()

        # Setup UI
        self._setup_ui()

        # Connect signals
        self._connect_signals()

        # Setup update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_dashboard)
        self.update_timer.start(config.gui_update_interval)

        logger.info("✅ Dashboard initialized")

    def _apply_dark_theme(self):
        """Apply dark theme to application"""
        app = QApplication.instance()
        app.setStyle("Fusion")

        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#252526"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2d2d2d"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#cccccc"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#3e3e42"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.BrightText, QColor("#ff0000"))
        palette.setColor(QPalette.ColorRole.Link, QColor("#007acc"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#007acc"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        app.setPalette(palette)

    def _setup_ui(self):
        """Setup user interface"""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout
        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # Left panel (video + metrics)
        left_panel = QVBoxLayout()

        # Video widget
        self.video_widget = VideoWidget()
        left_panel.addWidget(self.video_widget, stretch=2)

        # Metrics widget
        self.metrics_widget = MetricsWidget()
        left_panel.addWidget(self.metrics_widget, stretch=1)

        main_layout.addLayout(left_panel, stretch=2)

        # Right panel (logs)
        right_panel = QVBoxLayout()

        # Detection log
        self.detection_log = DetectionLogWidget()
        right_panel.addWidget(self.detection_log, stretch=1)

        # System log
        self.system_log = SystemLogWidget()
        right_panel.addWidget(self.system_log, stretch=1)

        main_layout.addLayout(right_panel, stretch=1)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("🔌 Waiting for RPi5 connection...")

        # Client count label
        self.client_count_label = QLabel("Clients: 0/0")
        self.status_bar.addPermanentWidget(self.client_count_label)

    def _connect_signals(self):
        """Connect signals to slots"""
        self.signals.video_frame.connect(self._on_video_frame)
        self.signals.metrics_update.connect(self._on_metrics_update)
        self.signals.detection_log.connect(self._on_detection_log)
        self.signals.system_log.connect(self._on_system_log)
        self.signals.client_connected.connect(self._on_client_connected)
        self.signals.client_disconnected.connect(self._on_client_disconnected)

    def _on_video_frame(self, frame_data: bytes, width: int, height: int):
        """Handle video frame update"""
        self.video_widget.update_frame(frame_data, width, height)

    def _on_metrics_update(self, metrics: Dict[str, Any]):
        """Handle metrics update"""
        self.metrics_widget.update_metrics(metrics)

    def _on_detection_log(self, message: str):
        """Handle detection log"""
        self.system_log.add_log(message, "INFO")

    def _on_system_log(self, message: str, level: str):
        """Handle system log"""
        self.system_log.add_log(message, level)

    def _on_client_connected(self, address: str):
        """Handle client connected"""
        self.system_log.add_log(f"Client connected: {address}", "SUCCESS")
        self.status_bar.showMessage(f"✅ Connected to {address}")

    def _on_client_disconnected(self, address: str):
        """Handle client disconnected"""
        self.system_log.add_log(f"Client disconnected: {address}", "WARNING")
        self.status_bar.showMessage(f"❌ Disconnected from {address}")

    def _update_dashboard(self):
        """Periodic dashboard updates"""
        # This is called every 30ms for GUI refresh
        pass

    def closeEvent(self, event):
        """Handle window close"""
        logger.info("🛑 Dashboard closing...")
        event.accept()


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

def main():
    """Example dashboard startup"""
    from laptop.config import default_config

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create application
    app = QApplication(sys.argv)
    app.setApplicationName("ProjectCortex Dashboard")

    # Create dashboard
    dashboard = CortexDashboard(default_config)
    dashboard.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
