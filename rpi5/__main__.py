"""
ProjectCortex RPi5 CLI - Main Entry Point

Usage:
    python -m rpi5                      # Show help
    python -m rpi5 all                  # Start all 4 layers
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

Options:
    --laptop HOST   Laptop IP for dashboard connection (default: 192.168.0.92)
    --port PORT     Dashboard port (default: 8765)
    --offline       Disable cloud APIs (Gemini, Supabase)
    --no-haptic     Disable vibration motor

Author: Haziq (@IRSPlays)
Date: January 11, 2026
"""

import sys
import argparse
import os


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser"""
    parser = argparse.ArgumentParser(
        description="ProjectCortex RPi5 AI Wearable",
        prog="python -m rpi5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m rpi5                      Show this help message
  python -m rpi5 all                  Start all 4 layers
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
        default="192.168.0.92",
        help="Laptop IP for dashboard connection (default: 192.168.0.92)"
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
            default="192.168.0.92",
            help="Laptop IP for dashboard connection"
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

    connect_parser = subparsers.add_parser(
        "connect",
        help="Connect to laptop dashboard",
        description="Start FastAPI client and connect to laptop dashboard"
    )
    connect_parser.add_argument(
        "--laptop",
        default="192.168.0.92",
        help="Laptop IP (default: 192.168.0.92)"
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

    return parser


def run_command(args: argparse.Namespace) -> int:
    """Execute the requested command"""
    command = args.command

    if command == "all":
        from rpi5.main import CortexSystem
        from rpi5.config.config import get_config

        print(f"Starting ProjectCortex v2.0 (all layers)...")

        config = get_config()
        config['laptop_server']['host'] = getattr(args, "laptop", "192.168.0.92")

        if getattr(args, "offline", False):
            print("Running in offline mode (cloud APIs disabled)")

        system = CortexSystem()
        system.start()

    elif command and command.startswith("layer"):
        from rpi5.cli.commands import run_layer

        layer_num = command.replace("layer", "")
        run_layer(
            layer_num,
            laptop_host=getattr(args, "laptop", "192.168.0.92")
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

    elif command == "connect":
        from rpi5.cli.commands import connect_to_laptop

        host = getattr(args, "laptop", "192.168.0.92")
        port = getattr(args, "port", 8765)
        return connect_to_laptop(host=host, port=port)

    elif command == "status":
        from rpi5.cli.commands import check_status
        return check_status()

    else:
        # No command specified, show help
        args.parser.print_help()
        return 0


def main() -> int:
    """Main entry point"""
    parser = create_parser()
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
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
