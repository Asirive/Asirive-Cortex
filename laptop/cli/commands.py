"""
CLI Command Implementations for ProjectCortex Laptop Dashboard

This module contains the command handlers for the laptop CLI.
Commands are implemented in __main__.py for simplicity.

Author: Haziq (@IRSPlays)
Date: January 11, 2026
"""

import sys
from typing import Optional


def run_gui(theme: str = "dark") -> int:
    """Launch GUI dashboard only"""
    from laptop.gui.cortex_dashboard import CortexDashboard
    from laptop.config import default_config
    from PyQt6.QtWidgets import QApplication

    print("Launching GUI dashboard...")
    app = QApplication(sys.argv)
    app.setApplicationName("ProjectCortex Dashboard")

    dashboard = CortexDashboard(default_config)
    dashboard.show()

    print("GUI launched. Press Ctrl+C to exit.")
    return app.exec()


def run_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    use_fastapi: bool = False,
    show_gui: bool = False
) -> int:
    """Start server (optionally with GUI)"""
    from laptop.cli.start_dashboard import DashboardApplication
    from laptop.config import default_config

    config = default_config
    config.ws_host = host
    config.ws_port = port

    print(f"Starting server ({'FastAPI' if use_fastapi else 'WebSocket'}) on {host}:{port}...")

    app = DashboardApplication(config, use_fastapi=use_fastapi)
    return app.start()


def run_all(host: str = "0.0.0.0", port: int = 8765, use_fastapi: bool = False) -> int:
    """Start server with GUI"""
    return run_server(host=host, port=port, use_fastapi=use_fastapi, show_gui=True)


def check_status() -> int:
    """Check server status"""
    print("ProjectCortex Laptop Dashboard Status")
    print("=" * 40)
    # TODO: Implement actual status check
    print("Server: Not running (run 'python -m laptop server')")
    print("GUI: Not running")
    return 0


def run_command(args) -> int:
    """Dispatch command to appropriate handler"""
    command = args.command

    if command == "gui":
        theme = getattr(args, "theme", "dark")
        return run_gui(theme=theme)

    elif command == "server":
        return run_server(
            host=getattr(args, "host", "0.0.0.0"),
            port=getattr(args, "port", 8765),
            use_fastapi=getattr(args, "fastapi", False),
            show_gui=getattr(args, "gui", False)
        )

    elif command == "all":
        return run_all(
            host=getattr(args, "host", "0.0.0.0"),
            port=getattr(args, "port", 8765),
            use_fastapi=getattr(args, "fastapi", False)
        )

    elif command == "status":
        return check_status()

    else:
        return 1
