"""
ProjectCortex Laptop Dashboard CLI

Usage:
    python -m laptop                    # Show help
    python -m laptop gui                # Launch GUI only
    python -m laptop server            # Start WebSocket server only
    python -m laptop server --fastapi  # Start FastAPI server
    python -m laptop server --gui      # Start server + GUI
    python -m laptop all               # Start everything
    python -m laptop status            # Check server status

Options:
    --host HOST     Server host (default: 0.0.0.0)
    --port PORT     Server port (default: 8765)
    --fastapi       Use FastAPI instead of legacy WebSocket
    --theme dark|light   GUI theme (default: dark)

Author: Haziq (@IRSPlays)
Date: January 11, 2026
"""

import sys
import argparse


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser"""
    parser = argparse.ArgumentParser(
        description="ProjectCortex Laptop Dashboard",
        prog="python -m laptop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m laptop                    Show this help message
  python -m laptop gui                Launch GUI only
  python -m laptop server            Start WebSocket server
  python -m laptop server --fastapi  Start FastAPI server
  python -m laptop all               Start everything (server + GUI)
  python -m laptop status            Check server status
        """
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 2.0.0"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands"
    )

    # gui command
    gui_parser = subparsers.add_parser(
        "gui",
        help="Launch GUI dashboard only (no server)"
    )
    gui_parser.add_argument(
        "--theme",
        default="dark",
        choices=["dark", "light"],
        help="GUI theme (default: dark)"
    )

    # server command
    server_parser = subparsers.add_parser(
        "server",
        help="Start server (optionally with GUI)"
    )
    server_parser.add_argument(
        "--fastapi",
        action="store_true",
        help="Use FastAPI server instead of legacy WebSocket"
    )
    server_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Server host (default: 0.0.0.0)"
    )
    server_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Server port (default: 8765)"
    )
    server_parser.add_argument(
        "--gui",
        action="store_true",
        help="Also launch GUI dashboard"
    )

    # all command
    all_parser = subparsers.add_parser(
        "all",
        help="Start server with GUI dashboard (same as 'server --gui')"
    )
    all_parser.add_argument(
        "--fastapi",
        action="store_true",
        help="Use FastAPI server"
    )
    all_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Server host (default: 0.0.0.0)"
    )
    all_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Server port (default: 8765)"
    )

    # status command
    subparsers.add_parser(
        "status",
        help="Check server status"
    )

    return parser


def run_command(args: argparse.Namespace) -> int:
    """Execute the requested command"""
    command = args.command

    if command == "gui":
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

    elif command == "server":
        from laptop.cli.start_dashboard import DashboardApplication
        from laptop.config import default_config

        use_fastapi = getattr(args, "fastapi", False)
        host = getattr(args, "host", "0.0.0.0")
        port = getattr(args, "port", 8765)
        show_gui = getattr(args, "gui", False)

        config = default_config
        config.ws_host = host
        config.ws_port = port

        print(f"Starting server ({'FastAPI' if use_fastapi else 'WebSocket'}) on {host}:{port}...")

        app = DashboardApplication(config, use_fastapi=use_fastapi)

        if show_gui:
            # Start both - this is handled in DashboardApplication
            pass

        return app.start()

    elif command == "all":
        from laptop.cli.start_dashboard import DashboardApplication
        from laptop.config import default_config

        use_fastapi = getattr(args, "fastapi", False)
        host = getattr(args, "host", "0.0.0.0")
        port = getattr(args, "port", 8765)

        config = default_config
        config.ws_host = host
        config.ws_port = port

        print(f"Starting server ({'FastAPI' if use_fastapi else 'WebSocket'}) with GUI on {host}:{port}...")

        app = DashboardApplication(config, use_fastapi=use_fastapi)
        return app.start()

    elif command == "status":
        print("ProjectCortex Laptop Dashboard Status")
        print("=" * 40)
        # TODO: Add actual status check
        print("Server: Not running (run 'python -m laptop server')")
        print("GUI: Not running")
        return 0

    else:
        # No command specified, show help
        args.parser.print_help()
        return 0


def main() -> int:
    """Main entry point"""
    parser = create_parser()
    args = parser.parse_args()

    # Handle backward compatibility for old command format
    if len(sys.argv) > 1 and sys.argv[1].startswith("-"):
        # Old format: python -m laptop.start_dashboard --fastapi
        # Translate to new format
        new_args = ["server"] + sys.argv[1:]
        sys.argv = [sys.argv[0]] + new_args
        args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    # Store parser for backward compat
    args.parser = parser

    try:
        return run_command(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
