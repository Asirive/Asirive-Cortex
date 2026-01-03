#!/usr/bin/env python3
"""
Project-Cortex v2.0 - Laptop Server Test Script

Quick test to verify laptop server is working properly.
Run this before integrating with actual RPi wearable.

Tests:
1. WebSocket server starts correctly
2. PyQt6 GUI launches successfully
3. Protocol message creation/parsing
4. Connection handling
5. Message routing

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: January 3, 2026
"""

import sys
from pathlib import Path

# Add laptop module to path
sys.path.insert(0, str(Path(__file__).parent / "laptop"))

from laptop.cortex_monitor_gui import main

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║          PROJECT-CORTEX v2.0 - LAPTOP SERVER TEST            ║
║                                                              ║
║  This will launch the PyQt6 Monitor GUI with WebSocket      ║
║  server running on Port 8765.                                ║
║                                                              ║
║  To test with simulated RPi data:                            ║
║  1. Open another terminal                                    ║
║  2. Run: python src/rpi_websocket_client.py                  ║
║                                                              ║
║  Or test with actual RPi:                                    ║
║  1. Update RPi code to use rpi_websocket_client.py           ║
║  2. Run cortex_gui.py on RPi with server IP configured       ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    input("Press Enter to start laptop server... ")
    
    main()
