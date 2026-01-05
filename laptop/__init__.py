"""
Project-Cortex v2.0 - Laptop Server (Tier 2)

This package contains the laptop server infrastructure for real-time monitoring
and future companion app support.

Components:
- cortex_monitor_gui.py: PyQt6 real-time visualization GUI
- websocket_server.py: WebSocket server for RPi communication (Port 8765)
- cortex_api_server.py: FastAPI REST/WebSocket API for companion app (Port 8000)

Architecture:
    Tier 1 (RPi Wearable) → WebSocket → Tier 2 (Laptop Server) → REST/WS → Tier 3 (Companion App)

Author: Haziq (@IRSPlays)
Date: January 3, 2026
"""

__version__ = "2.0.0"
__all__ = ["CortexMonitorGUI", "WebSocketServer", "CortexAPIServer"]
