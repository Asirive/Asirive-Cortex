"""
Laptop Dashboard for Asirive Cortex v2.0

PyQt6-based real-time monitoring dashboard for RPi5 AI wearable system.
Receives data via WebSocket/FastAPI from RPi5 and displays:
- Live video feed
- System metrics (FPS, latency, RAM, CPU, battery)
- Detection logs
- System logs

Author: Haziq (@IRSPlays)
Date: January 8, 2026
"""

__version__ = "2.0.0"
__author__ = "Haziq (@IRSPlays)"

# Core imports
from laptop.config import DashboardConfig, default_config
# TB2 fix: previously this re-exported from the laptop-local protocol.py
# even though shared/api/protocol.py has the same names. Migrate to
# the shared module so there is exactly ONE message-protocol definition
# across the codebase.
from shared.api.protocol import MessageType, BaseMessage, parse_message

# GUI modules
from laptop.gui.cortex_dashboard import CortexDashboard, DashboardSignals
from laptop.gui.cortex_ui import CortexDashboard as CortexDashboardUI

# Server modules
from laptop.server.websocket_server import CortexWebSocketServer
from laptop.server.fastapi_server import FastAPIServer, run_server
from laptop.server.fastapi_integration import FastAPIIntegration, FastAPISignals

# CLI entry point
from laptop.cli.start_dashboard import main as start_dashboard

__all__ = [
    # Config
    "DashboardConfig",
    "default_config",
    # Protocol (from shared.api.protocol, re-exported)
    "MessageType",
    "BaseMessage",
    "parse_message",
    # GUI
    "CortexDashboard",
    "DashboardSignals",
    "CortexDashboardUI",
    # Server
    "CortexWebSocketServer",
    "FastAPIServer",
    "run_server",
    "FastAPIIntegration",
    "FastAPISignals",
    # CLI
    "start_dashboard",
]
