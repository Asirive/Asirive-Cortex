"""
ProjectCortex Dashboard v2.0 - Glassmorphic Production UI
=========================================================

A complete redesign of the Cortex Dashboard featuring:
- Glassmorphic Dark Theme (Deep Navy + Neon Accents)
- Production Mode Control
- Real-time Sparkline Metrics
- Uptime Monitoring
- Thread-safe WebSocket integration
- Tabbed Interface (Overview, Testing, Logs)

Author: Haziq (@IRSPlays)
Date: January 18, 2026
"""

import sys
import os
import asyncio
import logging
import json
import time
from collections import deque
from datetime import datetime
from typing import Dict, Any, Optional, List

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QFrame, QPushButton, QProgressBar, 
    QGridLayout, QScrollArea, QSizePolicy, QStackedWidget, QLineEdit,
    QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QSize
from PyQt6.QtGui import (
    QColor, QPainter, QBrush, QPen, QFont, QImage, QPixmap,
    QRadialGradient, QLinearGradient, QPalette
)

from laptop.config import DashboardConfig

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('CortexUI')

# ============================================================================
# THEME & STYLES (Cyberpunk / Glassmorphism)
# ============================================================================

class Theme:
    # Deep Navy Backgrounds
    BG_MAIN = "#0a0e17"
    BG_GLASS = "rgba(30, 35, 45, 0.7)"
    BG_GLASS_HOVER = "rgba(40, 45, 60, 0.8)"
    
    # Neon Accents
    NEON_CYAN = "#00f2ea"
    NEON_PURPLE = "#7000ff"
    NEON_GREEN = "#00ff9d"
    NEON_RED = "#ff0055"
    NEON_YELLOW = "#ffee00"
    
    # Text
    TEXT_WHITE = "#ffffff"
    TEXT_GRAY = "#8b9bb4"
    
    FONT_MAIN = "Segoe UI"
    FONT_MONO = "Consolas"

STYLE_SHEET = f"""
    QMainWindow {{
        background-color: {Theme.BG_MAIN};
    }}
    QWidget {{
        color: {Theme.TEXT_WHITE};
        font-family: {Theme.FONT_MAIN};
    }}
    QFrame#GlassCard {{
        background-color: {Theme.BG_GLASS};
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
    }}
    QLabel#Title {{
        font-size: 18px;
        font-weight: bold;
        color: {Theme.NEON_CYAN};
    }}
    QLabel#Subtitle {{
        font-size: 12px;
        color: {Theme.TEXT_GRAY};
    }}
    QPushButton {{
        background-color: rgba(0, 242, 234, 0.1);
        border: 1px solid {Theme.NEON_CYAN};
        border-radius: 6px;
        color: {Theme.NEON_CYAN};
        padding: 5px 15px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: rgba(0, 242, 234, 0.3);
    }}
    QPushButton:pressed {{
        background-color: {Theme.NEON_CYAN};
        color: {Theme.BG_MAIN};
    }}
    QPushButton#StopBtn {{
        background-color: rgba(255, 0, 85, 0.1);
        border: 1px solid {Theme.NEON_RED};
        color: {Theme.NEON_RED};
    }}
    QPushButton#StopBtn:hover {{
        background-color: rgba(255, 0, 85, 0.3);
    }}
    
    /* Nav Buttons */
    QPushButton#NavBtn {{
        background-color: transparent;
        border: none;
        color: {Theme.TEXT_GRAY};
        font-size: 14px;
        padding: 10px;
    }}
    QPushButton#NavBtn:hover {{
        color: {Theme.TEXT_WHITE};
        background-color: rgba(255,255,255,0.05);
    }}
    QPushButton#NavBtn[active="true"] {{
        color: {Theme.NEON_CYAN};
        border-bottom: 2px solid {Theme.NEON_CYAN};
    }}

    /* Inputs */
    QLineEdit {{
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 4px;
        padding: 5px;
        color: {Theme.TEXT_WHITE};
        font-family: {Theme.FONT_MONO};
    }}
    QComboBox {{
        background-color: rgba(30, 35, 45, 1.0);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 4px;
        padding: 5px;
        color: {Theme.TEXT_WHITE};
    }}
"""

# ============================================================================
# CUSTOM WIDGETS
# ============================================================================

class GlassCard(QFrame):
    """Semi-transparent container with border"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlassCard")

class SparklineWidget(QWidget):
    """Real-time line graph for metrics"""
    def __init__(self, color=Theme.NEON_CYAN, max_points=50, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.data = deque([0]*max_points, maxlen=max_points)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def add_value(self, value):
        self.data.append(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw background
        rect = self.rect()
        painter.fillRect(rect, QColor(0, 0, 0, 0)) # Transparent
        
        if not self.data:
            return
            
        points = []
        w = rect.width()
        h = rect.height()
        step = w / (len(self.data) - 1) if len(self.data) > 1 else w
        
        min_val = 0
        max_val = 100 
        
        for i, val in enumerate(self.data):
            x = i * step
            normalized = (val - min_val) / (max_val - min_val) if max_val > min_val else 0
            y = h - (normalized * h)
            points.append((x, y))
            
        # Draw Line
        pen = QPen(self.color)
        pen.setWidth(2)
        painter.setPen(pen)
        
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i+1]
            painter.drawLine(int(p1[0]), int(p1[1]), int(p2[0]), int(p2[1]))

class UptimeWidget(QWidget):
    """Tracks and displays uptime"""
    def __init__(self, label, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_name = QLabel(label)
        self.lbl_name.setStyleSheet(f"color: {Theme.TEXT_GRAY};")
        
        self.lbl_time = QLabel("00:00:00")
        self.lbl_time.setStyleSheet(f"color: {Theme.TEXT_WHITE}; font-family: {Theme.FONT_MONO}; font-weight: bold;")
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        layout.addWidget(self.lbl_name)
        layout.addStretch()
        layout.addWidget(self.lbl_time)
        
        self.start_time = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        
    def start(self):
        self.start_time = time.time()
        self.timer.start(1000)
        
    def stop(self):
        self.timer.stop()
        self.lbl_time.setText("OFFLINE")
        self.lbl_time.setStyleSheet(f"color: {Theme.NEON_RED}; font-family: {Theme.FONT_MONO};")

    def update_time(self):
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            hours = elapsed // 3600
            minutes = (elapsed % 3600) // 60
            seconds = elapsed % 60
            self.lbl_time.setText(f"{hours:02}:{minutes:02}:{seconds:02}")
            self.lbl_time.setStyleSheet(f"color: {Theme.NEON_GREEN}; font-family: {Theme.FONT_MONO};")

class ProductionToggle(QWidget):
    """Large Toggle Switch for Production Mode"""
    toggled = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.lbl_status = QLabel("DEV MODE")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet(f"color: {Theme.TEXT_GRAY}; font-weight: bold; font-size: 14px;")
        
        self.btn_toggle = QPushButton("ENABLE PRODUCTION")
        self.btn_toggle.setFixedSize(200, 40)
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.05);
                border: 2px solid {Theme.TEXT_GRAY};
                color: {Theme.TEXT_GRAY};
                border-radius: 20px;
                font-size: 12px;
            }}
            QPushButton:checked {{
                background-color: {Theme.NEON_PURPLE};
                border: 2px solid {Theme.NEON_PURPLE};
                color: {Theme.TEXT_WHITE};
                box-shadow: 0 0 15px {Theme.NEON_PURPLE};
            }}
        """)
        self.btn_toggle.clicked.connect(self._on_toggle)
        
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.btn_toggle)
        
    def _on_toggle(self, checked):
        if checked:
            self.lbl_status.setText("PRODUCTION ACTIVE")
            self.lbl_status.setStyleSheet(f"color: {Theme.NEON_PURPLE}; font-weight: bold; font-size: 14px;")
            self.btn_toggle.setText("DISABLE PRODUCTION")
        else:
            self.lbl_status.setText("DEV MODE")
            self.lbl_status.setStyleSheet(f"color: {Theme.TEXT_GRAY}; font-weight: bold; font-size: 14px;")
            self.btn_toggle.setText("ENABLE PRODUCTION")
        self.toggled.emit(checked)


class TopNavBar(GlassCard):
    """Navigation Bar"""
    tab_changed = pyqtSignal(int) # index of tab

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Branding
        title = QLabel("PROJECT CORTEX")
        title.setObjectName("Title")
        title.setStyleSheet("font-size: 16px; margin-right: 20px;")
        layout.addWidget(title)
        
        # Tabs
        self.btn_overview = self._create_nav_btn("OVERVIEW", 0, True)
        self.btn_testing = self._create_nav_btn("TESTING", 1)
        self.btn_logs = self._create_nav_btn("LOGS", 2)
        
        layout.addWidget(self.btn_overview)
        layout.addWidget(self.btn_testing)
        layout.addWidget(self.btn_logs)
        layout.addStretch()
        
        # Status
        self.lbl_status = QLabel("DISCONNECTED")
        self.lbl_status.setStyleSheet(f"color: {Theme.NEON_RED}; font-weight: bold;")
        layout.addWidget(self.lbl_status)

    def _create_nav_btn(self, text, index, active=False):
        btn = QPushButton(text)
        btn.setObjectName("NavBtn")
        btn.setProperty("active", str(active).lower())
        btn.clicked.connect(lambda: self._on_click(index))
        return btn
        
    def _on_click(self, index):
        self.tab_changed.emit(index)
        # Update active state
        self.btn_overview.setProperty("active", "false")
        self.btn_testing.setProperty("active", "false")
        self.btn_logs.setProperty("active", "false")
        
        if index == 0: self.btn_overview.setProperty("active", "true")
        elif index == 1: self.btn_testing.setProperty("active", "true")
        elif index == 2: self.btn_logs.setProperty("active", "true")
        
        self.style().unpolish(self.btn_overview)
        self.style().polish(self.btn_overview)
        self.style().unpolish(self.btn_testing)
        self.style().polish(self.btn_testing)
        self.style().unpolish(self.btn_logs)
        self.style().polish(self.btn_logs)

    def set_connection_status(self, connected: bool, addr: str = ""):
        if connected:
            self.lbl_status.setText(f"CONNECTED: {addr}")
            self.lbl_status.setStyleSheet(f"color: {Theme.NEON_GREEN}; font-weight: bold;")
        else:
            self.lbl_status.setText("DISCONNECTED")
            self.lbl_status.setStyleSheet(f"color: {Theme.NEON_RED}; font-weight: bold;")


# ============================================================================
# APP VIEWS
# ============================================================================

class DashboardOverviewWidget(QWidget):
    """Main Overview Tab"""
    send_command = pyqtSignal(dict) # Relay to parent

    def __init__(self, parent=None):
        super().__init__(parent)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(20)
        
        # === LEFT COLUMN: Video & Production Control (60%) ===
        left_col = QVBoxLayout()
        left_col.setSpacing(20)
        
        # 1. Mode Control
        self.prod_toggle = ProductionToggle()
        self.prod_toggle.toggled.connect(self._send_mode)
        left_col.addWidget(self.prod_toggle)
        
        # 2. Video Feed
        self.video_frame = QLabel("Waiting for Video Source...")
        self.video_frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_frame.setStyleSheet(f"""
            background-color: black;
            border: 2px solid {Theme.BG_GLASS};
            border-radius: 12px;
            color: {Theme.TEXT_GRAY};
        """)
        self.video_frame.setMinimumSize(640, 480)
        self.video_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left_col.addWidget(self.video_frame)
        
        # 2b. Clean Control Bar
        ctrl_panel = GlassCard()
        ctrl_layout = QHBoxLayout(ctrl_panel)
        ctrl_layout.setContentsMargins(10, 5, 10, 5)
        
        # Group 1: Stream
        self.btn_stream = QPushButton("START STREAM")
        self.btn_stream.setCheckable(True)
        self.btn_stream.clicked.connect(self._toggle_stream)
        ctrl_layout.addWidget(self.btn_stream)
        
        # Group 2: Overlays
        ctrl_layout.addWidget(QLabel("|"))
        self.chk_bbox_l0 = QCheckBox("Guardian (L0)")
        self.chk_bbox_l0.setChecked(True)
        self.chk_bbox_l1 = QCheckBox("Learner (L1)") 
        self.chk_bbox_l1.setChecked(True)
        ctrl_layout.addWidget(self.chk_bbox_l0)
        ctrl_layout.addWidget(self.chk_bbox_l1)
        
        # Group 3: Features
        ctrl_layout.addWidget(QLabel("|"))
        self.chk_supabase = QCheckBox("Cloud Sync")
        self.chk_supabase.setChecked(True)
        self.chk_supabase.setToolTip("Enable/Disable Supabase Sync")
        ctrl_layout.addWidget(self.chk_supabase)
        
        # Group 4: Mode (Right Aligned)
        ctrl_layout.addStretch()
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["TEXT_PROMPTS", "PROMPT_FREE"])
        self.combo_mode.setToolTip("Switch Layer 1 Detection Mode")
        self.combo_mode.currentTextChanged.connect(self._send_mode_update)
        ctrl_layout.addWidget(self.combo_mode)
        
        left_col.addWidget(ctrl_panel)

        
        # 3. Detection Stream (Compact)

        
        # 3. Detection Stream (Compact)
        det_panel = GlassCard()
        det_layout = QVBoxLayout(det_panel)
        det_layout.addWidget(QLabel("LIVE DETECTIONS", objectName="Title"))
        
        self.det_log = QTextEdit()
        self.det_log.setReadOnly(True)
        self.det_log.setStyleSheet(f"background-color: transparent; border: none; font-family: {Theme.FONT_MONO}; color: {Theme.NEON_CYAN};")
        self.det_log.setMaximumHeight(150)
        det_layout.addWidget(self.det_log)
        
        left_col.addWidget(det_panel)
        
        # === RIGHT COLUMN: Metrics & Controls (40%) ===
        right_col = QVBoxLayout()
        right_col.setSpacing(20)
        
        # 1. System Status
        status_panel = GlassCard()
        status_layout = QVBoxLayout(status_panel)
        status_layout.addWidget(QLabel("SYSTEM METRICS", objectName="Title"))
        
        # Sparklines
        self.cpu_spark = SparklineWidget(Theme.NEON_RED)
        status_layout.addWidget(QLabel("CPU Load"))
        status_layout.addWidget(self.cpu_spark)
        
        self.ram_spark = SparklineWidget(Theme.NEON_PURPLE)
        status_layout.addWidget(QLabel("Memory Usage"))
        status_layout.addWidget(self.ram_spark)
        
        self.fps_spark = SparklineWidget(Theme.NEON_GREEN)
        status_layout.addWidget(QLabel("FPS Analysis"))
        status_layout.addWidget(self.fps_spark)
        
        # Uptimes
        self.uptime_layer = UptimeWidget("Layer Runtime")
        self.uptime_cam = UptimeWidget("Camera Feed")
        status_layout.addWidget(self.uptime_layer)
        status_layout.addWidget(self.uptime_cam)
        
        right_col.addWidget(status_panel)
        
        # 2. Layer Control
        control_panel = GlassCard()
        control_layout = QVBoxLayout(control_panel)
        control_layout.addWidget(QLabel("LAYER CONTROL", objectName="Title"))
        
        # Layer 1 Mode
        l1_row = QHBoxLayout()
        l1_row.addWidget(QLabel("L1 Mode:"))
        self.combo_l1_mode = QComboBox()
        self.combo_l1_mode.addItems(["TEXT_PROMPTS", "PROMPT_FREE"])
        self.combo_l1_mode.currentTextChanged.connect(self._set_l1_mode)
        l1_row.addWidget(self.combo_l1_mode)
        control_layout.addLayout(l1_row)
        
        layers = [
            ("Guardian (Safe)", Theme.NEON_RED, "layer0"),
            ("Learner (Adapt)", Theme.NEON_YELLOW, "layer1"),
            ("Thinker (LLM)", Theme.NEON_PURPLE, "layer2"),
            ("Guide (Nav)", Theme.NEON_CYAN, "layer3")
        ]
        
        for name, color, lid in layers:
            row = QHBoxLayout()
            lbl = QLabel(name)
            btn = QPushButton("RESTART")
            btn.setStyleSheet(f"border-color: {color}; color: {color}; font-size: 10px;")
            btn.clicked.connect(lambda checked, l=lid: self._restart_layer(l))
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(btn)
            control_layout.addLayout(row)
            
        # Full Restart
        btn_full_restart = QPushButton("FULL SYSTEM RESTART")
        btn_full_restart.setObjectName("StopBtn")
        btn_full_restart.clicked.connect(self._restart_system)
        control_layout.addWidget(btn_full_restart)
        
        right_col.addWidget(control_panel)
        right_col.addStretch()
        
        # Add columns to main layout
        main_layout.addLayout(left_col, 60)
        main_layout.addLayout(right_col, 40)

    # --- Actions ---
    def _send_mode(self, enabled):
        cmd = {
            "action": "SET_MODE",
            "mode": "PRODUCTION" if enabled else "DEV"
        }
        self.send_command.emit(cmd)

    def _send_mode_update(self, mode_text: str):
        """Send mode update command to RPi5"""
        cmd = {
            "type": "CONFIG",
            "data": {
                "layer": "layer1",
                "mode": mode_text
            }
        }
        self.send_command.emit(cmd)

    def _toggle_stream(self):
        # We don't track state locally effectively without feedback, but we can send toggle
        # Actually protocol says START/STOP_VIDEO_STREAMING
        # For simplicity, let's just assume we want to START
        # Or better, make it a checkable button
        pass # Implemented in future if needed

    def _set_l1_mode(self, mode_str):
        cmd = {
            "action": "SET_LAYER_MODE",
            "layer": "layer1",
            "mode": mode_str
        }
        self.send_command.emit(cmd)

    def _restart_layer(self, layer_id):
        cmd = {
            "action": "RESTART_LAYER",
            "layer": layer_id
        }
        self.send_command.emit(cmd)

    def _restart_system(self):
         self.send_command.emit({"action": "RESTART"})


class TestingWidget(QWidget):
    """Manual Testing Tab"""
    send_command = pyqtSignal(dict) # Relay

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        
        # Title
        layout.addWidget(QLabel("MANUAL TESTING SUITE", objectName="Title"))
        
        # Input Area
        input_panel = GlassCard()
        input_layout = QVBoxLayout(input_panel)
        input_layout.addWidget(QLabel("TEXT QUERY INJECTION"))
        
        input_row = QHBoxLayout()
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Type a query here (e.g. 'What is this?') and press Enter...")
        self.txt_input.returnPressed.connect(self._send_text)
        
        btn_send = QPushButton("SEND")
        btn_send.clicked.connect(self._send_text)
        
        input_row.addWidget(self.txt_input)
        input_row.addWidget(btn_send)
        input_layout.addLayout(input_row)
        layout.addWidget(input_panel)
        
        # Test Presets
        presets_panel = GlassCard()
        presets_layout = QGridLayout(presets_panel)
        
        presets = [
            ("Describe Scene", "Describe what you see"),
            ("Read Text", "Read any text visible"),
            ("Find Person", "Is there a person here?"),
            ("Count Objects", "Count the objects"),
            ("Where am I?", "Where am I?"),
            ("Safety Check", "Is this path safe?")
        ]
        
        row = 0
        col = 0
        for label, query in presets:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, q=query: self._inject_query(q))
            presets_layout.addWidget(btn, row, col)
            col += 1
            if col > 2:
                col = 0
                row += 1
                
        layout.addWidget(presets_panel)
        
        # Test Log
        log_panel = GlassCard()
        log_layout = QVBoxLayout(log_panel)
        log_layout.addWidget(QLabel("TEST RESULTS / RESPONSES"))
        
        self.test_log = QTextEdit()
        self.test_log.setReadOnly(True)
        self.test_log.setStyleSheet(f"background-color: transparent; border: none; font-family: {Theme.FONT_MONO}; color: {Theme.NEON_YELLOW};")
        log_layout.addWidget(self.test_log)
        
        layout.addWidget(log_panel)
        
    def _send_text(self):
        text = self.txt_input.text().strip()
        if text:
            self._inject_query(text)
            self.txt_input.clear()
            
    def _inject_query(self, text):
        self.test_log.append(f">>> {text}")
        cmd = {
            "action": "TEXT_QUERY",
            "query": text
        }
        self.send_command.emit(cmd)
        
    def append_log(self, text):
        self.test_log.append(text)


class LogsWidget(QWidget):
    """Full Logs Tab"""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("SYSTEM LOGS", objectName="Title"))
        
        self.sys_log = QTextEdit()
        self.sys_log.setReadOnly(True)
        self.sys_log.setStyleSheet(f"background-color: rgba(0,0,0,0.3); border: 1px solid {Theme.BG_GLASS}; font-family: {Theme.FONT_MONO}; font-size: 11px;")
        layout.addWidget(self.sys_log)

    def append(self, html):
        self.sys_log.append(html)


# ============================================================================
# MAIN WINDOW
# ============================================================================

class DashboardSignals(QObject):
    video_frame = pyqtSignal(bytes, int, int)
    metrics_update = pyqtSignal(dict)
    detection_log = pyqtSignal(dict)
    system_log = pyqtSignal(str, str)  # message, level
    client_connected = pyqtSignal(str)
    client_disconnected = pyqtSignal(str)
    send_command = pyqtSignal(dict) # UI -> Server

class CortexDashboard(QMainWindow):
    def __init__(self, config: DashboardConfig = None):
        super().__init__()
        self.config = config
        self.setWindowTitle("ProjectCortex v2.0 // Dashboard")
        self.resize(1400, 900)
        self.setStyleSheet(STYLE_SHEET)
        
        # Signals
        self.signals = DashboardSignals() # Will be replaced by shared instance in DashboardApplication usually, or we connect to this one
        
        # UI Setup
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 1. Top Nav
        self.navbar = TopNavBar()
        self.navbar.tab_changed.connect(self.switch_tab)
        layout.addWidget(self.navbar)
        
        # 2. Content Stack
        self.stack = QStackedWidget()
        
        # View 0: Overview
        self.view_overview = DashboardOverviewWidget()
        self.view_overview.send_command.connect(self.broadcast_command)
        self.stack.addWidget(self.view_overview)
        
        # View 1: Testing
        self.view_testing = TestingWidget()
        self.view_testing.send_command.connect(self.broadcast_command)
        self.stack.addWidget(self.view_testing)
        
        # View 2: Logs
        self.view_logs = LogsWidget()
        self.stack.addWidget(self.view_logs)
        
        layout.addWidget(self.stack)
        
        # Connect internal signals
        self.signals.video_frame.connect(self.on_video_frame)
        self.signals.metrics_update.connect(self.on_metrics_update)
        self.signals.detection_log.connect(self.on_detection)
        self.signals.system_log.connect(self.on_system_log)
        self.signals.client_connected.connect(self.on_client_connected)
        self.signals.client_disconnected.connect(self.on_client_disconnected)

    def switch_tab(self, index):
        self.stack.setCurrentIndex(index)

    def broadcast_command(self, cmd):
        # Emit signal for Application to pick up and send
        self.signals.send_command.emit(cmd)

    # --- Slot Handlers ---

    def on_video_frame(self, frame_data, w, h):
        image = QImage.fromData(frame_data)
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            target = self.view_overview.video_frame
            target.setPixmap(pixmap.scaled(
                target.size(), 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            ))

    def on_metrics_update(self, data):
        # Update overview widgets
        if "cpu_percent" in data:
            self.view_overview.cpu_spark.add_value(data["cpu_percent"])
        if "ram_percent" in data:
            self.view_overview.ram_spark.add_value(data["ram_percent"])
        if "fps" in data:
            self.view_overview.fps_spark.add_value(data["fps"])

    def on_detection(self, det):
        cls = det.get("class", "unknown")
        conf = det.get("confidence", 0)
        layer = det.get("layer", "sys")
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        line = f"[{timestamp}] <{layer}> {cls} ({conf:.0%})"
        
        # Add to overview log
        self.view_overview.det_log.append(line)
        # Scroll
        sb = self.view_overview.det_log.verticalScrollBar()
        sb.setValue(sb.maximum())
        
        # Visualize Bounding Box? 
        # (Would need to overlay on video_frame, requiring custom PaintEvent on QLabel or a canvas)
        # For now we just log.

    def on_system_log(self, msg, level):
        color = Theme.NEON_CYAN if level == "INFO" else Theme.NEON_RED if level == "ERROR" else Theme.NEON_GREEN
        timestamp = datetime.now().strftime("%H:%M:%S")
        html = f'<span style="color:{Theme.TEXT_GRAY}">[{timestamp}]</span> <b style="color:{color}">[{level}]</b> {msg}'
        
        self.view_logs.append(html)
        
        # Also log key events to testing tab if relevant?
        if "Audio" in msg or "Response" in msg:
             self.view_testing.append_log(msg)

    def on_client_connected(self, addr):
        self.on_system_log(f"Client Connected: {addr}", "SUCCESS")
        self.navbar.set_connection_status(True, addr)
        self.view_overview.uptime_layer.start()
        self.view_overview.uptime_cam.start()

    def on_client_disconnected(self, addr):
        self.on_system_log(f"Client Disconnected: {addr}", "WARNING")
        self.navbar.set_connection_status(False)
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = QFont(Theme.FONT_MAIN, 10)
    app.setFont(font)
    dashboard = CortexDashboard()
    dashboard.show()
    sys.exit(app.exec())
