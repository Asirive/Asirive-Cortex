"""
ProjectCortex Dashboard - Clean UI with custom-ui-pyqt6

A clean, minimal PyQt6 dashboard using custom-ui-pyqt6 components.
Features:
- Real-time video feed with detection overlays
- System metrics monitoring (FPS, RAM, CPU, battery, temperature)
- Layer control panel for testing all 4 layers
- Text input for testing voice queries and workflows
- Detection and system logs
- Clean dark theme without gradient spam

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
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QScrollArea, QFrame, QSplitter,
    QPushButton, QStatusBar, QComboBox, QSlider, QSpinBox, QDoubleSpinBox,
    QCheckBox, QLineEdit, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QGridLayout, QStackedWidget, QDialog,
    QDialogButtonBox, QFormLayout, QMessageBox, QFileDialog, QFrame,
    QInputDialog, QLineEdit
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, pyqtSlot, QMetaObject, arg
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPalette, QColor, QFont, QIcon

import base64
import io
import json
import numpy as np

# Setup debug logging BEFORE other imports that might use logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('CortexDashboard')

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.warning("websockets package not installed, WebSocket client disabled")

# Custom UI components - clean, modern, no gradients
from custom_ui_package import (
    CustomCard, CustomTabWidget,
    CustomInputBox, CustomTextArea, CustomDropdown,
    CustomMainWindow, CustomTitleBar, CustomModal, CustomToast,
    CustomProgressBar, CustomCheckBox, CustomRadioButton,
    CustomSlider, CustomSpinner, CustomAccordion,
    CustomMessageDialog
)

from laptop.config import DashboardConfig
from laptop.protocol import (
    MessageType, BaseMessage, create_message, parse_message
)

# Setup debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger.info("CortexDashboard module initialized")


# ============================================================================
# COLOR PALETTE (Clean, no gradients)
# ============================================================================

class CortexColors:
    """Clean color palette for ProjectCortex"""

    # Backgrounds
    BG_PRIMARY = "#0f1419"
    BG_SECONDARY = "#1a1f26"
    BG_TERTIARY = "#242b33"
    BG_CARD = "#1e252d"

    # Accents - muted, professional
    ACCENT = "#00b894"      # Teal green
    ACCENT_SECONDARY = "#6c5ce7"  # Soft purple
    WARNING = "#fdcb6e"     # Warm yellow
    DANGER = "#e17055"      # Soft red
    SUCCESS = "#00b894"     # Green

    # Text
    TEXT_PRIMARY = "#eceff4"
    TEXT_SECONDARY = "#abb2bf"
    TEXT_MUTED = "#5c6370"

    # Layer colors
    LAYER_0 = "#e17055"     # Guardian - coral
    LAYER_1 = "#fdcb6e"     # Learner - yellow
    LAYER_2 = "#00b894"     # Thinker - green
    LAYER_3 = "#74b9ff"     # Guide - blue
    LAYER_4 = "#a29bfe"     # Memory - purple


# Apply custom colors to the library
def apply_custom_theme():
    """Apply clean theme to custom_ui_package"""
    # Custom colors are applied via stylesheets in components
    # The library handles its own internal theming
    pass


# ============================================================================
# SIGNAL BRIDGE
# ============================================================================

class DashboardSignals(QObject):
    """Signals for thread-safe GUI updates"""
    video_frame = pyqtSignal(bytes, int, int)
    metrics_update = pyqtSignal(dict)
    detection_log = pyqtSignal(dict)
    system_log = pyqtSignal(str, str)
    client_connected = pyqtSignal(str)
    client_disconnected = pyqtSignal(str)
    layer_response = pyqtSignal(str, dict)


# ============================================================================
# BASE STYLESHEET
# ============================================================================

BASE_STYLESHEET = f"""
    QMainWindow {{
        background-color: {CortexColors.BG_PRIMARY};
    }}
    QWidget {{
        background-color: {CortexColors.BG_PRIMARY};
        color: {CortexColors.TEXT_PRIMARY};
        font-family: 'Segoe UI', 'Roboto', sans-serif;
        font-size: 13px;
    }}
    QLabel {{
        color: {CortexColors.TEXT_PRIMARY};
    }}
    QGroupBox {{
        border: 1px solid {CortexColors.BG_TERTIARY};
        border-radius: 8px;
        margin-top: 12px;
        padding-top: 8px;
        font-weight: 600;
        color: {CortexColors.TEXT_SECONDARY};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 8px;
        color: {CortexColors.ACCENT};
    }}
    QProgressBar {{
        background-color: {CortexColors.BG_TERTIARY};
        border: none;
        border-radius: 4px;
        text-align: center;
        color: {CortexColors.TEXT_PRIMARY};
    }}
    QProgressBar::chunk {{
        background-color: {CortexColors.ACCENT};
        border-radius: 4px;
    }}
    QTableWidget {{
        background-color: {CortexColors.BG_CARD};
        color: {CortexColors.TEXT_PRIMARY};
        border: 1px solid {CortexColors.BG_TERTIARY};
        gridline-color: {CortexColors.BG_TERTIARY};
        border-radius: 6px;
    }}
    QHeaderView::section {{
        background-color: {CortexColors.BG_TERTIARY};
        color: {CortexColors.TEXT_SECONDARY};
        padding: 8px 12px;
        border: none;
        font-weight: 600;
    }}
    QMenuBar {{
        background-color: {CortexColors.BG_SECONDARY};
        color: {CortexColors.TEXT_PRIMARY};
        border-bottom: 1px solid {CortexColors.BG_TERTIARY};
        padding: 4px;
    }}
    QMenuBar::item:selected {{
        background-color: {CortexColors.ACCENT};
        border-radius: 4px;
    }}
    QMenu {{
        background-color: {CortexColors.BG_SECONDARY};
        color: {CortexColors.TEXT_PRIMARY};
        border: 1px solid {CortexColors.BG_TERTIARY};
        border-radius: 6px;
        padding: 4px;
    }}
    QMenu::item:selected {{
        background-color: {CortexColors.BG_TERTIARY};
    }}
    QStatusBar {{
        background-color: {CortexColors.BG_SECONDARY};
        color: {CortexColors.TEXT_SECONDARY};
        border-top: 1px solid {CortexColors.BG_TERTIARY};
        padding: 4px 8px;
    }}
    QScrollBar:vertical {{
        background-color: {CortexColors.BG_PRIMARY};
        width: 10px;
        border-radius: 5px;
    }}
    QScrollBar::handle:vertical {{
        background-color: {CortexColors.BG_TERTIARY};
        border-radius: 4px;
        min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        background: none;
        height: 0px;
    }}
"""


# ============================================================================
# VIDEO WIDGET
# ============================================================================

class VideoWidget(QFrame):
    """Video feed display with detection overlays"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(1)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {CortexColors.BG_CARD};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 8px;
            }}
        """)
        self.setMinimumSize(640, 400)
        self.frame_data = None
        self.detections = []
        self.fps = 0.0

        # FPS label overlay
        self.fps_label = QLabel("FPS: --", self)
        self.fps_label.setStyleSheet(f"""
            QLabel {{
                color: {CortexColors.ACCENT};
                font-size: 14px;
                font-weight: bold;
                background-color: rgba(15, 20, 25, 180);
                padding: 4px 8px;
                border-radius: 4px;
            }}
        """)

    def update_frame(self, frame_data: bytes, width: int, height: int):
        """Update video frame"""
        self.frame_data = (frame_data, width, height)
        self.update()

    def update_detections(self, detections: List[Dict]):
        """Update detection overlays"""
        self.detections = detections
        self.update()

    def update_fps(self, fps: float):
        """Update FPS display"""
        self.fps = fps
        self.fps_label.setText(f"FPS: {fps:.1f}")

    def paintEvent(self, event):
        """Draw video frame and detection overlays"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw frame if available
        if self.frame_data:
            try:
                frame_data, width, height = self.frame_data
                image = QImage(frame_data, width, height, QImage.Format.Format_Jpeg)
                painter.drawImage(self.rect(), image)
            except Exception as e:
                pass

        # Draw detection overlays
        for det in self.detections:
            bbox = det.get('bbox', [])
            if len(bbox) >= 4:
                x1, y1, x2, y2 = bbox
                conf = det.get('confidence', 0)
                layer = det.get('layer', 'unknown')
                class_name = det.get('class_name', 'object')

                # Color based on layer
                layer_colors = {
                    'guardian': CortexColors.LAYER_0,
                    'learner': CortexColors.LAYER_1,
                }
                color_str = layer_colors.get(layer, CortexColors.TEXT_SECONDARY)
                color = QColor(color_str)
                color.setAlpha(180)

                pen = QColor(color_str)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)

                # Draw bounding box
                rect_w = x2 - x1
                rect_h = y2 - y1
                painter.drawRect(int(x1), int(y1), int(rect_w), int(rect_h))

                # Draw label background
                label = f"{class_name} {conf:.0%}"
                font = QFont("Segoe UI", 10, QFont.Weight.Bold)
                painter.setFont(font)
                fm = painter.fontMetrics()
                text_width = fm.horizontalAdvance(label) + 16

                bg_color = QColor(color_str)
                bg_color.setAlpha(220)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(bg_color)
                painter.drawRoundedRect(int(x1), int(y1) - 20, text_width, 20, 4, 4)

                # Draw label text
                painter.setPen(QColor(CortexColors.BG_PRIMARY))
                painter.drawText(int(x1) + 8, int(y1) - 6, label)

        painter.end()

    def resizeEvent(self, event):
        """Position FPS label"""
        super().resizeEvent(event)
        self.fps_label.move(12, 12)


# ============================================================================
# METRICS WIDGET
# ============================================================================

class MetricsWidget(QFrame):
    """System metrics display using CustomCard"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {CortexColors.BG_CARD};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("System Metrics")
        title.setStyleSheet(f"""
            QLabel {{
                color: {CortexColors.ACCENT};
                font-size: 14px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title)

        # Metrics grid
        self.metrics = {}
        metric_config = [
            ("FPS", "fps", CortexColors.ACCENT),
            ("RAM", "ram_percent", CortexColors.WARNING),
            ("CPU", "cpu_percent", CortexColors.DANGER),
            ("Battery", "battery_percent", CortexColors.SUCCESS),
            ("Temperature", "temperature", CortexColors.ACCENT_SECONDARY),
        ]

        for name, key, color in metric_config:
            row_layout = QHBoxLayout()

            # Label
            name_label = QLabel(f"{name}:")
            name_label.setStyleSheet(f"color: {CortexColors.TEXT_SECONDARY}; font-size: 12px;")
            name_label.setFixedWidth(80)
            row_layout.addWidget(name_label)

            # Value
            value_label = QLabel("--")
            value_label.setStyleSheet(f"""
                QLabel {{
                    color: {color};
                    font-size: 14px;
                    font-weight: bold;
                    min-width: 70px;
                }}
            """)
            row_layout.addWidget(value_label)

            # Progress bar
            progress = CustomProgressBar()
            progress.setFixedHeight(6)
            progress.setRange(0, 100)
            progress.setValue(0)
            row_layout.addWidget(progress)

            layout.addLayout(row_layout)
            self.metrics[key] = (value_label, progress)

        # Mode display
        self.mode_label = QLabel("Mode: --")
        self.mode_label.setStyleSheet(f"""
            QLabel {{
                color: {CortexColors.TEXT_PRIMARY};
                font-size: 13px;
                padding: 8px 12px;
                background-color: {CortexColors.BG_TERTIARY};
                border-radius: 6px;
                margin-top: 8px;
            }}
        """)
        layout.addWidget(self.mode_label)

        # Active layers
        self.layers_label = QLabel("Layers: None")
        self.layers_label.setStyleSheet(f"""
            QLabel {{
                color: {CortexColors.TEXT_SECONDARY};
                font-size: 12px;
            }}
        """)
        layout.addWidget(self.layers_label)

        layout.addStretch()

    def update_metrics(self, data: Dict):
        """Update metrics display"""
        for key, (value_label, progress) in self.metrics.items():
            if key in data:
                value = data[key]
                if key == "fps":
                    value_label.setText(f"{value:.1f}")
                    progress.setValue(int(min(value, 60)))
                elif key == "temperature":
                    value_label.setText(f"{value:.1f}°C")
                    progress.setValue(int(min(value, 100)))
                else:
                    value_label.setText(f"{value:.1f}%")
                    progress.setValue(int(value))

        # Update mode
        mode = data.get("current_mode", "--")
        self.mode_label.setText(f"Mode: {mode}")

        # Update layers
        layers = data.get("active_layers", [])
        layers_text = ", ".join(layers) if layers else "None"
        self.layers_label.setText(f"Layers: {layers_text}")


# ============================================================================
# DETECTION LOG WIDGET
# ============================================================================

class DetectionLogWidget(QFrame):
    """Detection log widget"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {CortexColors.BG_CARD};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        header_layout = QHBoxLayout()

        title = QLabel("Detection Log")
        title.setStyleSheet(f"""
            QLabel {{
                color: {CortexColors.ACCENT};
                font-size: 14px;
                font-weight: bold;
            }}
        """)
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedSize(70, 28)
        clear_btn.clicked.connect(self.clear_log)
        header_layout.addWidget(clear_btn)

        layout.addLayout(header_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Time", "Layer", "Object", "Conf", "Source"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setRowCount(0)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                border: none;
                gridline-color: {CortexColors.BG_TERTIARY};
            }}
        """)
        layout.addWidget(self.table)

    def add_detection(self, data: Dict):
        """Add detection entry"""
        row = self.table.rowCount()
        self.table.insertRow(row)

        time_str = datetime.now().strftime("%H:%M:%S")

        items = [
            QTableWidgetItem(time_str),
            QTableWidgetItem(data.get('layer', 'unknown')[:7]),
            QTableWidgetItem(data.get('class_name', 'unknown')[:15]),
            QTableWidgetItem(f"{data.get('confidence', 0):.0%}"),
            QTableWidgetItem(data.get('source', 'NCNN')[:8])
        ]

        # Color based on confidence
        conf = data.get('confidence', 0)
        bg_color = QColor(CortexColors.BG_TERTIARY)

        for i, item in enumerate(items):
            if i == 3:  # Confidence column
                item.setBackground(bg_color)
            self.table.setItem(row, i, item)

        # Scroll and limit
        self.table.scrollToBottom()
        if self.table.rowCount() > 500:
            self.table.removeRow(0)

    def clear_log(self):
        """Clear the log"""
        self.table.clearContents()
        self.table.setRowCount(0)


# ============================================================================
# SYSTEM LOG WIDGET
# ============================================================================

class SystemLogWidget(QFrame):
    """System log widget"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {CortexColors.BG_CARD};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        header_layout = QHBoxLayout()

        title = QLabel("System Log")
        title.setStyleSheet(f"""
            QLabel {{
                color: {CortexColors.ACCENT};
                font-size: 14px;
                font-weight: bold;
            }}
        """)
        header_layout.addWidget(title)

        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Log text area (create before button that connects to it)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {CortexColors.BG_PRIMARY};
                color: {CortexColors.TEXT_PRIMARY};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 4px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
                padding: 8px;
            }}
        """)
        layout.addWidget(self.log_area)

        # Clear button (after log_area is created)
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedSize(70, 28)
        clear_btn.clicked.connect(self.log_area.clear)
        header_layout.addWidget(clear_btn)

        # Log colors
        self.colors = {
            "ERROR": CortexColors.DANGER,
            "WARNING": CortexColors.WARNING,
            "SUCCESS": CortexColors.SUCCESS,
            "INFO": CortexColors.ACCENT,
            "DEBUG": CortexColors.TEXT_MUTED
        }

    def add_log(self, message: str, level: str = "INFO"):
        """Add log entry"""
        time_str = datetime.now().strftime("%H:%M:%S")
        color = self.colors.get(level, CortexColors.TEXT_PRIMARY)

        formatted = f'<span style="color: {CortexColors.TEXT_MUTED};">[{time_str}]</span> ' \
                    f'<span style="color: {color}; font-weight: bold;">[{level}]</span> {message}'
        self.log_area.append(formatted)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )


# ============================================================================
# LAYER CONTROL PANEL
# ============================================================================

class LayerCard(QFrame):
    """Card for controlling a single layer"""

    command_sent = pyqtSignal(str, dict)

    def __init__(self, layer_name: str, display_name: str, color: str, parent=None):
        super().__init__(parent)
        self.layer_name = layer_name
        self.color = color

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {CortexColors.BG_CARD};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 8px;
            }}
        """)
        self.setup_ui(display_name)

    def setup_ui(self, display_name: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        header_layout = QHBoxLayout()

        title = QLabel(display_name)
        title.setStyleSheet(f"""
            QLabel {{
                color: {self.color};
                font-size: 14px;
                font-weight: bold;
            }}
        """)
        header_layout.addWidget(title)

        # Status badge (simple label-based)
        self.status_badge = QLabel("Disconnected")
        self.status_badge.setStyleSheet(f"""
            QLabel {{
                background-color: {CortexColors.BG_TERTIARY};
                color: {CortexColors.TEXT_SECONDARY};
                padding: 4px 12px;
                border-radius: 12px;
                font-size: 11px;
            }}
        """)
        header_layout.addWidget(self.status_badge)

        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedSize(80, 32)
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.color};
                color: {CortexColors.BG_PRIMARY};
                border: none;
                border-radius: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)
        self.start_btn.clicked.connect(lambda: self.send_command("start"))
        btn_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedSize(80, 32)
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {CortexColors.BG_TERTIARY};
                color: {CortexColors.TEXT_PRIMARY};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 6px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {CortexColors.DANGER};
                color: white;
            }}
        """)
        self.stop_btn.clicked.connect(lambda: self.send_command("stop"))
        btn_layout.addWidget(self.stop_btn)

        layout.addLayout(btn_layout)

        # Response area
        self.response_area = QTextEdit()
        self.response_area.setMaximumHeight(100)
        self.response_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {CortexColors.BG_PRIMARY};
                color: {CortexColors.TEXT_PRIMARY};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 4px;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                padding: 8px;
            }}
        """)
        layout.addWidget(self.response_area)

        layout.addStretch()

    def send_command(self, action: str):
        """Send command for this layer"""
        command_data = {
            "action": action,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        self.command_sent.emit(self.layer_name, command_data)
        self.response_area.append(f"[SENT] {action.upper()}")

    def set_status(self, status: str, is_running: bool):
        """Update status badge"""
        self.status_badge.setText(status or ("Running" if is_running else "Stopped"))
        if is_running:
            self.status_badge.setStyleSheet(f"""
                QLabel {{
                    background-color: {CortexColors.SUCCESS};
                    color: {CortexColors.BG_PRIMARY};
                    padding: 4px 12px;
                    border-radius: 12px;
                    font-size: 11px;
                    font-weight: bold;
                }}
            """)
        else:
            self.status_badge.setStyleSheet(f"""
                QLabel {{
                    background-color: {CortexColors.BG_TERTIARY};
                    color: {CortexColors.TEXT_SECONDARY};
                    padding: 4px 12px;
                    border-radius: 12px;
                    font-size: 11px;
                }}
            """)

    def add_response(self, response: Dict):
        """Add response from layer"""
        self.response_area.append(f"[OK] {response}")


class LayerControlPanel(QWidget):
    """Panel for controlling all layers"""

    command_sent = pyqtSignal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("Layer Control")
        title.setStyleSheet(f"""
            QLabel {{
                color: {CortexColors.ACCENT};
                font-size: 16px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title)

        # Layer cards
        self.layer_cards = {}

        layers = [
            ("layer_0", "Layer 0: Guardian", CortexColors.LAYER_0),
            ("layer_1", "Layer 1: Learner", CortexColors.LAYER_1),
            ("layer_2", "Layer 2: Thinker", CortexColors.LAYER_2),
            ("layer_3", "Layer 3: Guide", CortexColors.LAYER_3),
        ]

        for layer_id, display_name, color in layers:
            card = LayerCard(layer_id, display_name, color)
            card.command_sent.connect(self.command_sent.emit)
            layout.addWidget(card)
            self.layer_cards[layer_id] = card

        layout.addStretch()


# ============================================================================
# WORKFLOW TEST WIDGET
# ============================================================================

class WorkflowTestWidget(QWidget):
    """Widget for testing complete workflows"""

    test_query = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("Workflow Test")
        title.setStyleSheet(f"""
            QLabel {{
                color: {CortexColors.ACCENT};
                font-size: 16px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title)

        # Query input
        input_group = QFrame()
        input_group.setStyleSheet(f"""
            QFrame {{
                background-color: {CortexColors.BG_CARD};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 8px;
            }}
        """)
        input_layout = QVBoxLayout(input_group)
        input_layout.setContentsMargins(12, 12, 12, 12)
        input_layout.setSpacing(8)

        input_label = QLabel("Test Query")
        input_label.setStyleSheet(f"color: {CortexColors.TEXT_SECONDARY}; font-size: 12px;")
        input_layout.addWidget(input_label)

        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Enter test query...")
        self.query_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {CortexColors.BG_PRIMARY};
                color: {CortexColors.TEXT_PRIMARY};
                border: 1px solid {CortexColors.BG_TERTIARY};
                padding: 10px 12px;
                font-size: 13px;
                border-radius: 6px;
            }}
            QLineEdit:focus {{
                border-color: {CortexColors.ACCENT};
            }}
        """)
        input_layout.addWidget(self.query_input)

        # Quick test buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        quick_tests = [
            ("What do you see?", "text_prompts"),
            ("Scan everything", "prompt_free"),
            ("Where is my wallet?", "visual_prompts"),
        ]

        for label, mode in quick_tests:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda checked, q=label, m=mode: self.on_quick_test(q, m))
            btn_layout.addWidget(btn)

        input_layout.addLayout(btn_layout)

        # Submit button
        submit_btn = QPushButton("Submit Query")
        submit_btn.setFixedHeight(36)
        submit_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {CortexColors.ACCENT};
                color: {CortexColors.BG_PRIMARY};
                border: none;
                border-radius: 6px;
                font-weight: bold;
                padding: 8px 20px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)
        submit_btn.clicked.connect(self.on_submit_query)
        input_layout.addWidget(submit_btn)

        layout.addWidget(input_group)

        # Expected behavior
        expected_group = QFrame()
        expected_group.setStyleSheet(f"""
            QFrame {{
                background-color: {CortexColors.BG_CARD};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 8px;
            }}
        """)
        expected_layout = QVBoxLayout(expected_group)
        expected_layout.setContentsMargins(12, 12, 12, 12)
        expected_layout.setSpacing(8)

        expected_label = QLabel("Expected Behavior")
        expected_label.setStyleSheet(f"color: {CortexColors.TEXT_SECONDARY}; font-size: 12px;")
        expected_layout.addWidget(expected_label)

        self.expected_text = QLabel("Enter a query to see expected behavior...")
        self.expected_text.setStyleSheet(f"color: {CortexColors.TEXT_PRIMARY}; font-size: 13px;")
        self.expected_text.setWordWrap(True)
        expected_layout.addWidget(self.expected_text)

        layout.addWidget(expected_group)

        # Query history
        history_group = QFrame()
        history_group.setStyleSheet(f"""
            QFrame {{
                background-color: {CortexColors.BG_CARD};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 8px;
            }}
        """)
        history_layout = QVBoxLayout(history_group)
        history_layout.setContentsMargins(12, 12, 12, 12)
        history_layout.setSpacing(8)

        history_label = QLabel("Query History")
        history_label.setStyleSheet(f"color: {CortexColors.TEXT_SECONDARY}; font-size: 12px;")
        history_layout.addWidget(history_label)

        self.history_area = QTextEdit()
        self.history_area.setMaximumHeight(120)
        self.history_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {CortexColors.BG_PRIMARY};
                color: {CortexColors.TEXT_PRIMARY};
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 4px;
                font-size: 12px;
                padding: 8px;
            }}
        """)
        history_layout.addWidget(self.history_area)

        layout.addWidget(history_group)
        layout.addStretch()

    def on_quick_test(self, query: str, expected_mode: str):
        """Handle quick test button click"""
        self.query_input.setText(query)

        behaviors = {
            "text_prompts": "Route: Layer 1 (Learner)\nMode: TEXT_PROMPTS\nConfidence: 0.7-0.9\nAdaptive vocabulary",
            "prompt_free": "Route: Layer 1 (Learner)\nMode: PROMPT_FREE\nConfidence: 0.3-0.6\n4585+ built-in classes",
            "visual_prompts": "Route: Layer 1 (Learner)\nMode: VISUAL_PROMPTS\nConfidence: 0.6-0.95\nVisual embeddings from memory",
        }

        self.expected_text.setText(behaviors.get(expected_mode, "Unknown mode"))

    def on_submit_query(self):
        """Submit test query"""
        query = self.query_input.text().strip()
        if not query:
            return

        self.test_query.emit(query)

        # Add to history
        time_str = datetime.now().strftime("%H:%M:%S")
        self.history_area.append(f"[{time_str}] {query}")

        self.query_input.clear()


# ============================================================================
# MESSAGE INJECTOR WIDGET
# ============================================================================

class MessageInjectorWidget(QWidget):
    """Widget for injecting test messages"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("Message Injector")
        title.setStyleSheet(f"""
            QLabel {{
                color: {CortexColors.ACCENT};
                font-size: 16px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title)

        # Message type selector
        type_layout = QHBoxLayout()

        type_label = QLabel("Type:")
        type_label.setStyleSheet(f"color: {CortexColors.TEXT_SECONDARY};")
        type_layout.addWidget(type_label)

        self.type_combo = QComboBox()
        for msg_type in MessageType:
            self.type_combo.addItem(msg_type.value, msg_type)
        self.type_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {CortexColors.BG_CARD};
                color: {CortexColors.TEXT_PRIMARY};
                padding: 8px 12px;
                border: 1px solid {CortexColors.BG_TERTIARY};
                border-radius: 6px;
                min-width: 150px;
            }}
        """)
        type_layout.addWidget(self.type_combo)

        layout.addLayout(type_layout)

        # Message data input
        self.data_input = QTextEdit()
        self.data_input.setPlaceholderText("Enter message data as JSON...")
        self.data_input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {CortexColors.BG_CARD};
                color: {CortexColors.TEXT_PRIMARY};
                border: 1px solid {CortexColors.BG_TERTIARY};
                font-family: 'Consolas', monospace;
                font-size: 12px;
                border-radius: 6px;
                padding: 8px;
                min-height: 100px;
            }}
        """)
        layout.addWidget(self.data_input)

        # Preset buttons
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(8)

        presets = [
            ("Ping", {"type": "PING"}),
            ("Start", {"type": "COMMAND", "command": "start"}),
            ("Pause", {"type": "COMMAND", "command": "pause"}),
        ]

        for name, preset in presets:
            btn = QPushButton(name)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda checked, p=preset: self.load_preset(p))
            preset_layout.addWidget(btn)

        layout.addLayout(preset_layout)

        # Send button
        send_btn = QPushButton("Send Message")
        send_btn.setFixedHeight(40)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {CortexColors.ACCENT};
                color: {CortexColors.BG_PRIMARY};
                border: none;
                border-radius: 6px;
                font-weight: bold;
                padding: 8px 20px;
            }}
        """)
        layout.addWidget(send_btn)

        # Sent log
        sent_label = QLabel("Sent Messages")
        sent_label.setStyleSheet(f"color: {CortexColors.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(sent_label)

        self.sent_log = QTextEdit()
        self.sent_log.setMaximumHeight(100)
        self.sent_log.setStyleSheet(f"""
            QTextEdit {{
                background-color: {CortexColors.BG_CARD};
                color: {CortexColors.TEXT_PRIMARY};
                border: 1px solid {CortexColors.BG_TERTIARY};
                font-family: 'Consolas', monospace;
                font-size: 11px;
                border-radius: 6px;
                padding: 8px;
            }}
        """)
        layout.addWidget(self.sent_log)

        layout.addStretch()

    def load_preset(self, preset: dict):
        """Load a preset message"""
        self.type_combo.setCurrentText(preset.get("type", ""))
        self.data_input.setText(json.dumps(preset, indent=2))


# ============================================================================
# TESTING WINDOW
# ============================================================================

class TestingWindow(QDialog):
    """Separate window for testing and controlling layers"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ProjectCortex - Testing & Control")
        self.setMinimumSize(800, 600)
        self.setStyleSheet(f"background-color: {CortexColors.BG_PRIMARY};")
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Custom tab widget
        self.tabs = CustomTabWidget()

        # Layer Control Tab
        self.layer_control = LayerControlPanel()
        self.tabs.addTab(self.layer_control, "Layers")

        # Workflow Test Tab
        self.workflow_test = WorkflowTestWidget()
        self.tabs.addTab(self.workflow_test, "Workflow")

        # Message Injector Tab
        self.message_injector = MessageInjectorWidget()
        self.tabs.addTab(self.message_injector, "Messages")

        layout.addWidget(self.tabs)

        # Button box
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(16, 12, 16, 12)

        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedSize(80, 36)
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)


# ============================================================================
# WEBSOCKET CLIENT
# ============================================================================

class WebSocketClient(QThread):
    """WebSocket client for connecting to RPi5 simulator"""

    # Signals for GUI updates
    connected = pyqtSignal(str)  # server_url
    disconnected = pyqtSignal(str)  # reason
    video_frame = pyqtSignal(bytes, int, int)  # frame_data, width, height
    metrics_update = pyqtSignal(dict)
    detection = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, server_url: str = "ws://localhost:8765"):
        super().__init__()
        self.server_url = server_url
        self.running = False
        self._websocket = None

    def run(self):
        """Run the WebSocket client loop"""
        if not WEBSOCKETS_AVAILABLE:
            self.error.emit("WebSocket support not available. Install: pip install websockets")
            return

        logger.info(f"WebSocket client connecting to {self.server_url}...")
        self.running = True

        async def client_loop():
            try:
                async with websockets.connect(self.server_url) as websocket:
                    self._websocket = websocket
                    self.connected.emit(self.server_url)
                    logger.info(f"Connected to {self.server_url}")

                    while self.running:
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                            self._handle_message(message)
                        except asyncio.TimeoutError:
                            continue
                        except websockets.exceptions.ConnectionClosed:
                            self.disconnected.emit("Connection closed")
                            break

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self.error.emit(str(e))
                self.disconnected.emit(str(e))

        asyncio.run(client_loop())

    def _handle_message(self, message: str):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")
            msg_data = data.get("data", {})

            if msg_type == "VIDEO_FRAME":
                frame_b64 = msg_data.get("frame", "")
                frame_data = base64.b64decode(frame_b64)
                width = msg_data.get("width", 640)
                height = msg_data.get("height", 480)
                self.video_frame.emit(frame_data, width, height)

            elif msg_type == "METRICS_UPDATE":
                self.metrics_update.emit(msg_data)

            elif msg_type == "DETECTION":
                self.detection.emit(msg_data)

            elif msg_type == "PONG":
                logger.debug("Received PONG")

            else:
                logger.debug(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    def send_message(self, message: dict):
        """Send a message to the server"""
        if self._websocket and self.running:
            try:
                msg_str = json.dumps(message)
                asyncio.run(self._websocket.send(msg_str))
            except Exception as e:
                logger.error(f"Failed to send message: {e}")

    def stop(self):
        """Stop the WebSocket client"""
        logger.info("Stopping WebSocket client...")
        self.running = False
        if self._websocket:
            asyncio.run(self._websocket.close())


# ============================================================================
# MAIN DASHBOARD WINDOW
# ============================================================================

class CortexDashboard(QMainWindow):
    """Main dashboard window"""

    def __init__(self):
        super().__init__()
        logger.info("Initializing CortexDashboard...")
        self.setWindowTitle("ProjectCortex Dashboard")
        self.setMinimumSize(1100, 700)

        # Apply stylesheet
        self.setStyleSheet(BASE_STYLESHEET)
        logger.debug("Base stylesheet applied")

        self.signals = DashboardSignals()
        logger.debug("DashboardSignals created")

        # WebSocket client (initially None)
        self.ws_client = None
        self.ws_connected = False

        self.setup_ui()
        logger.debug("UI setup complete")

        self.setup_menus()
        logger.debug("Menus setup complete")

        self.setup_connections()
        logger.debug("Signal connections established")

        logger.info("CortexDashboard initialized successfully")

    def setup_ui(self):
        """Setup main dashboard UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Video and Metrics
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(12)

        # Video feed
        self.video_widget = VideoWidget()
        self.video_widget.setMinimumSize(560, 360)
        left_layout.addWidget(self.video_widget, 2)

        # Metrics
        self.metrics_widget = MetricsWidget()
        left_layout.addWidget(self.metrics_widget, 1)

        splitter.addWidget(left_widget)

        # Right panel - Logs
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(12)

        # Detection log
        self.detection_log = DetectionLogWidget()
        right_layout.addWidget(self.detection_log, 1)

        # System log
        self.system_log = SystemLogWidget()
        right_layout.addWidget(self.system_log, 1)

        splitter.addWidget(right_widget)

        # Set splitter sizes
        splitter.setSizes([600, 400])

        main_layout.addWidget(splitter)

        # Status bar
        self.statusBar().showMessage("Ready - Connect a RPi5 device")

    def setup_menus(self):
        """Setup menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")
        file_menu.addAction("Connect...", self.on_connect)
        file_menu.addAction("Disconnect", self.on_disconnect)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        # View menu
        view_menu = menubar.addMenu("View")
        view_menu.addAction("Testing Window", self.show_testing_window)

        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        tools_menu.addAction("Clear Logs", self.on_clear_logs)

        # Help menu
        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About", self.on_about)

        # Testing window reference
        self.testing_window = None

    def setup_connections(self):
        """Setup signal connections"""
        self.signals.video_frame.connect(self.on_video_frame)
        self.signals.metrics_update.connect(self.on_metrics_update)
        self.signals.detection_log.connect(self.on_detection)
        self.signals.system_log.connect(self.on_system_log)
        self.signals.client_connected.connect(self.on_client_connected)
        self.signals.client_disconnected.connect(self.on_client_disconnected)

    # =========================================================================
    # SLOT IMPLEMENTATIONS
    # =========================================================================

    @pyqtSlot(bytes, int, int)
    def on_video_frame(self, frame_data: bytes, width: int, height: int):
        """Handle video frame update"""
        logger.debug(f"Video frame received: {width}x{height}, {len(frame_data)} bytes")
        self.video_widget.update_frame(frame_data, width, height)

    @pyqtSlot(dict)
    def on_metrics_update(self, data: Dict):
        """Handle metrics update"""
        logger.debug(f"Metrics update: {list(data.keys())}")
        self.metrics_widget.update_metrics(data)
        self.video_widget.update_fps(data.get('fps', 0))

    @pyqtSlot(dict)
    def on_detection(self, data: Dict):
        """Handle detection log update"""
        logger.debug(f"Detection: {data.get('class_name')} conf={data.get('confidence'):.2%} layer={data.get('layer')}")
        self.detection_log.add_detection(data)
        current = self.video_widget.detections
        current.append(data)
        self.video_widget.detections = current[-10:]
        self.video_widget.update_detections(current[-10:])

    @pyqtSlot(str, str)
    def on_system_log(self, message: str, level: str):
        """Handle system log update"""
        logger.info(f"[{level}] {message}")
        self.system_log.add_log(message, level)

    @pyqtSlot(str)
    def on_client_connected(self, address: str):
        """Handle client connection"""
        logger.info(f"Client connected: {address}")
        self.statusBar().showMessage(f"Connected: {address}")
        self.on_system_log(f"Client connected: {address}", "SUCCESS")

    @pyqtSlot(str)
    def on_client_disconnected(self, address: str):
        """Handle client disconnection"""
        logger.info(f"Client disconnected: {address}")
        self.statusBar().showMessage(f"Disconnected: {address}")
        self.on_system_log(f"Client disconnected: {address}", "WARNING")

    # =========================================================================
    # MENU ACTIONS
    # =========================================================================

    def on_connect(self):
        """Handle connect action - show dialog to enter server URL"""
        # Ask for server URL
        default_url = "ws://192.168.0.92:8765" if self.ws_connected else "ws://localhost:8765"
        server_url, ok = QInputDialog.getText(
            self,
            "Connect to RPi5",
            "Enter WebSocket server URL:",
            QLineEdit.EchoMode.Normal,
            default_url
        )

        if not ok or not server_url:
            return

        logger.info(f"Connecting to {server_url}...")

        # Create and start WebSocket client
        self.ws_client = WebSocketClient(server_url)

        # Connect signals
        self.ws_client.connected.connect(self.on_ws_connected)
        self.ws_client.disconnected.connect(self.on_ws_disconnected)
        self.ws_client.video_frame.connect(self.on_video_frame)
        self.ws_client.metrics_update.connect(self.on_metrics_update)
        self.ws_client.detection.connect(self.on_detection)
        self.ws_client.error.connect(lambda msg: self.on_system_log(f"WebSocket Error: {msg}", "ERROR"))

        # Start client in background thread
        self.ws_client.start()

    def on_disconnect(self):
        """Handle disconnect action"""
        if self.ws_client and self.ws_connected:
            logger.info("Disconnecting from server...")
            self.ws_client.stop()
            self.ws_client.wait()
            self.ws_client = None
            self.ws_connected = False
            self.on_system_log("Disconnected from server", "WARNING")
        else:
            self.on_system_log("Not connected to any server", "INFO")

    @pyqtSlot(str)
    def on_ws_connected(self, server_url: str):
        """Handle WebSocket connection"""
        self.ws_connected = True
        self.statusBar().showMessage(f"Connected: {server_url}")
        self.on_system_log(f"Connected to {server_url}", "SUCCESS")
        logger.info(f"WebSocket connected to {server_url}")

    @pyqtSlot(str)
    def on_ws_disconnected(self, reason: str):
        """Handle WebSocket disconnection"""
        self.ws_connected = False
        self.statusBar().showMessage(f"Disconnected: {reason}")
        self.on_system_log(f"Disconnected: {reason}", "WARNING")
        logger.info(f"WebSocket disconnected: {reason}")

    def show_testing_window(self):
        """Show the testing window"""
        if not self.testing_window:
            self.testing_window = TestingWindow(self)
        self.testing_window.show()

    def on_clear_logs(self):
        """Clear all logs"""
        self.detection_log.clear_log()
        self.system_log.log_area.clear()
        self.on_system_log("Logs cleared", "INFO")

    def on_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About ProjectCortex",
            f"<h2>ProjectCortex Dashboard</h2>"
            f"<p>Version 2.0</p>"
            f"<p>AI Wearable for the Visually Impaired</p>"
            f"<p>Author: Haziq (@IRSPlays)</p>"
        )

    def closeEvent(self, event):
        """Handle window close - cleanup WebSocket client"""
        logger.info("Dashboard closing...")
        if self.ws_client and self.ws_connected:
            self.ws_client.stop()
            self.ws_client.wait()
        if self.testing_window:
            self.testing_window.close()
        event.accept()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    app = QApplication(sys.argv)

    # Apply clean theme
    apply_custom_theme()

    # Set application info
    app.setApplicationName("ProjectCortex Dashboard")
    app.setOrganizationName("ProjectCortex")

    # Create and show dashboard
    window = CortexDashboard()
    window.show()

    print("ProjectCortex Dashboard started.")
    print("Use 'View -> Testing Window' to access layer controls.")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
