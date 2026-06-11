"""
Asirive Cortex RPi5 CLI - Main Entry Point

Usage:
    python -m rpi5                      # Show help
    python -m rpi5 all                  # Start all 4 layers
    python -m rpi5 all --standalone      # Start without laptop dashboard
    python -m rpi5 layer0               # Start Guardian only (YOLO)
    python -m rpi5 layer1               # Start Learner only (YOLOE)
    python -m rpi5 layer2               # Start Thinker only (Gemini)
    python -m rpi5 layer3               # Start Guide only (navigation)
    python -m rpi5 layer4               # Start Memory only (SQLite)
    python -m rpi5 camera               # Test camera only
    python -m rpi5 audio                # Test audio I/O only
    python -m rpi5 connect              # Connect to laptop dashboard
    python -m rpi5 status               # Check system status
    python -m rpi5 test                 # Run self-test diagnostics
    python -m rpi5 tui                  # Live terminal dashboard (TUI)

Options:
    --laptop HOST   Override laptop IP for dashboard connection
    --port PORT     Dashboard port (default: 8765)
    --offline       Disable cloud APIs (Gemini, Supabase)
    --no-haptic     Disable vibration motor

Author: Haziq (@IRSPlays)
Date: January 11, 2026
"""

import sys
import argparse
import logging

from rpi5.cli.log_setup import setup_logging

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser"""
    parser = argparse.ArgumentParser(
        description="Asirive Cortex RPi5 AI Wearable",
        prog="python -m rpi5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m rpi5                      Show this help message
  python -m rpi5 all                  Start all 4 layers
  python -m rpi5 all --standalone      Start without laptop dashboard
  python -m rpi5 layer0               Test Layer 0 (Guardian)
  python -m rpi5 layer1               Test Layer 1 (Learner)
  python -m rpi5 camera               Test camera only
  python -m rpi5 test                 Run self-test diagnostics
  python -m rpi5 all --offline        Run without cloud APIs
  python -m rpi5 connect --laptop 192.168.1.100  # Connect to custom laptop IP
        """
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 2.0.0"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-essential logs (WARNING level)",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands"
    )

    # all command - start everything
    all_parser = subparsers.add_parser(
        "all",
        help="Start all 4 layers (Guardian, Learner, Thinker, Memory)"
    )
    all_parser.add_argument(
        "--laptop",
        default=None,
        help="Override laptop IP for dashboard connection"
    )
    all_parser.add_argument(
        "--offline",
        action="store_true",
        help="Disable cloud APIs (Gemini, Supabase)"
    )
    all_parser.add_argument(
        "--no-haptic",
        action="store_true",
        help="Disable vibration motor"
    )
    all_parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run without laptop dashboard (no WebSocket/ZMQ connection)"
    )
    all_parser.add_argument(
        "--earbuds",
        choices=["in", "out", "cmf", "ugreen"],
        default=None,
        help="Select earbuds: 'in'/'cmf' for CMF Buds (in-ear), 'out'/'ugreen' for UGREEN HiTune S3 (open-ear)"
    )
    all_parser.add_argument(
        "--2.4",
        dest="two_point_four",
        action="store_true",
        help="Use the lightweight plain-print dashboard (designed for 2.4 GHz WiFi / slow SSH)"
    )
    all_parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Disable the on-system dashboard entirely (logs only)"
    )
    all_parser.add_argument(
        "--old-dashboard",
        action="store_true",
        help="Use the legacy single-panel Rich Live StatusDisplay instead of the Textual TUI"
    )

    # layer commands
    for layer_num, layer_name, help_text in [
        ("0", "guardian", "Safety-critical YOLO detection"),
        ("1", "learner", "Adaptive YOLOE detection"),
        ("2", "thinker", "Gemini Live API conversational AI"),
        ("3", "guide", "Navigation and spatial audio"),
        ("4", "memory", "SQLite + Supabase storage"),
    ]:
        layer_parser = subparsers.add_parser(
            f"layer{layer_num}",
            help=f"Start Layer {layer_num}: {layer_name}",
            description=f"Start Layer {layer_num} ({layer_name}) - {help_text}"
        )
        layer_parser.add_argument(
            "--laptop",
            default=None,
            help="Override laptop IP for dashboard connection"
        )

    # test commands
    camera_parser = subparsers.add_parser(
        "camera",
        help="Test camera capture",
        description="Test camera capture and display a few frames"
    )
    camera_parser.add_argument(
        "--device",
        type=int,
        default=0,
        help="Camera device ID (default: 0)"
    )

    audio_parser = subparsers.add_parser(
        "audio",
        help="Test audio I/O",
        description="Test microphone input and speaker output"
    )

    test_parser = subparsers.add_parser(
        "test",
        help="Run self-test diagnostics",
        description="Run system diagnostics to verify all components work"
    )

    # test-live command - minimal Gemini Live API connectivity check
    test_live_parser = subparsers.add_parser(
        "test-live",
        help="Test Gemini Live API connection (minimal, no tools)",
        description=(
            "Connect to the Gemini Live API with a minimal config and "
            "exit immediately. Prints the actual close code and reason "
            "so you can see what's blocking the production connect loop."
        ),
    )

    connect_parser = subparsers.add_parser(
        "connect",
        help="Connect to laptop dashboard",
        description="Start FastAPI client and connect to laptop dashboard"
    )
    connect_parser.add_argument(
        "--laptop",
        default=None,
        help="Override laptop IP for dashboard connection"
    )
    connect_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Dashboard port (default: 8765)"
    )

    # status command
    subparsers.add_parser(
        "status",
        help="Check system status"
    )

    # tui command - live dashboard
    tui_parser = subparsers.add_parser(
        "tui",
        help="Live terminal dashboard (TUI)",
        description="Real-time terminal UI: system metrics, layer status, log tail.",
    )
    tui_parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Refresh interval in seconds (default: 1.0)",
    )
    tui_parser.add_argument(
        "--log-file",
        default="logs/cortex.log",
        help="Log file to tail (default: logs/cortex.log)",
    )

    return parser


def run_command(args: argparse.Namespace) -> int:
    """Execute the requested command"""
    command = args.command

    if command == "all":
        from rpi5.main import CortexSystem
        from rpi5.config.config import get_config

        logger.info("Starting Asirive Cortex v2.0 (all layers)...")

        config = get_config()
        if getattr(args, "laptop", None):
            config['laptop_server']['host'] = args.laptop

        standalone = getattr(args, "standalone", False)
        if getattr(args, "offline", False):
            logger.info("Running in offline mode (cloud APIs disabled)")
        # Default to standalone unless --laptop is explicitly provided
        if getattr(args, "laptop", None) is None and not standalone:
            standalone = True
            logger.info("Running in standalone mode (no laptop dashboard)")
        elif standalone:
            logger.info("Running in standalone mode (no laptop dashboard)")

        # Handle --earbuds flag: map "in"->"cmf", "out"->"ugreen"
        earbuds = getattr(args, "earbuds", None)
        if earbuds:
            earbuds_key = {"in": "cmf", "cmf": "cmf", "out": "ugreen", "ugreen": "ugreen"}[earbuds]
            config.setdefault('bluetooth', {})['active_device'] = earbuds_key
            label = "CMF Buds (in-ear)" if earbuds_key == "cmf" else "UGREEN HiTune S3 (open-ear)"
            logger.info(f"Earbuds: {label}")

        system = CortexSystem(standalone=standalone)

        # Decide which on-system dashboard to run. --2.4 forces the
        # plain-print 2.4 mode. --old-dashboard keeps the legacy
        # StatusDisplay (Rich Live, single panel, no Textual). --no-dashboard
        # disables the on-system UI entirely (logs only).
        # Default is the FULL Textual TUI (validated in Round 2b: 0efee15).
        if getattr(args, "no_dashboard", False):
            dashboard_mode = "none"
        elif getattr(args, "two_point_four", False):
            dashboard_mode = "2.4"
        elif getattr(args, "old_dashboard", False):
            dashboard_mode = "old"
        else:
            dashboard_mode = "full"  # Textual — the new default
        system.dashboard_mode = dashboard_mode
        logger.info(f"📊 Dashboard mode: {dashboard_mode}")

        system.start()

    elif command and command.startswith("layer"):
        from rpi5.cli.commands import run_layer

        layer_num = command.replace("layer", "")
        run_layer(
            layer_num,
            laptop_host=getattr(args, "laptop", None)
        )

    elif command == "camera":
        from rpi5.cli.commands import test_camera

        device = getattr(args, "device", 0)
        return test_camera(device_id=device)

    elif command == "audio":
        from rpi5.cli.commands import test_audio
        return test_audio()

    elif command == "test":
        from rpi5.cli.commands import run_self_test
        return run_self_test()

    elif command == "test-live":
        from rpi5.cli.commands import test_gemini_live
        return test_gemini_live()

    elif command == "connect":
        from rpi5.cli.commands import connect_to_laptop

        host = getattr(args, "laptop", None)
        port = getattr(args, "port", 8765)
        return connect_to_laptop(host=host, port=port)

    elif command == "status":
        from rpi5.cli.commands import check_status
        return check_status()

    elif command == "tui":
        from rpi5.cli.tui import run_tui
        return run_tui(
            interval=getattr(args, "interval", 1.0),
            log_file=getattr(args, "log_file", "logs/cortex.log"),
        )

    else:
        # No command specified, show help
        args.parser.print_help()
        return 0


def main() -> int:
    """Main entry point"""
    # Parse early to grab log-level flags before configuring logging.
    parser = create_parser()
    args = parser.parse_args()

    log_level = "INFO"
    if getattr(args, "debug", False):
        log_level = "DEBUG"
    elif getattr(args, "quiet", False):
        log_level = "WARNING"

    # The `all` command runs an interactive Live status panel on stdout.
    # The RichHandler writes to stderr instead so the panel and the log
    # stream don't share a cursor (and tear each other's frames). Other
    # commands (camera, audio, test, tui, connect) have no Live panel
    # and can use stdout directly.
    #
    # v3 (tui-layout-overflow fix): for the FULL Textual TUI, the TUI's own
    # RichLog already shows the log content (tail of logs/cortex.log). If we
    # also write RichHandler to stderr, those lines "leak" onto the terminal
    # in the gap above the TUI's blue header (Textual uses the alternate
    # screen buffer for stdout, but stderr still hits the underlying
    # terminal). So in FULL mode we suppress the RichHandler entirely.
    is_all = getattr(args, "command", None) == "all"
    # Resolve the dashboard mode from args — mirrors the logic in run_command().
    if is_all:
        if getattr(args, "no_dashboard", False):
            dashboard_mode = "none"
        elif getattr(args, "two_point_four", False):
            dashboard_mode = "2.4"
        elif getattr(args, "old_dashboard", False):
            dashboard_mode = "old"
        else:
            dashboard_mode = "full"
    else:
        dashboard_mode = "none"
    use_rich = dashboard_mode != "full"
    rich_stream = "stderr" if is_all else "stdout"
    setup_logging(
        level=log_level,
        log_file="logs/cortex.log",
        use_rich=use_rich,
        rich_stream=rich_stream,
    )

    if is_all and dashboard_mode == "full":
        # In FULL mode logs are shown in the TUI's log panel; quiet the
        # terminal so we don't get stray log lines above the header.
        logger.info(
            "📊 FULL Textual TUI active — log lines appear in the bottom panel, "
            "not the terminal. The full log is still saved to logs/cortex.log."
        )
    elif is_all:
        logger.info(
            "📋 Logs are being written to logs/cortex.log (and stderr). "
            "Run `python -m rpi5 tui` in another shell for a structured view."
        )

    if args.command is None:
        parser.print_help()
        return 0

    # Store parser for backward compat
    args.parser = parser

    try:
        return run_command(args)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
