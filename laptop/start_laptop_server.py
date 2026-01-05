#!/usr/bin/env python3
"""
Project-Cortex v2.0 - Laptop Server Launcher

Unified launcher for all Tier 2 laptop server components:
- PyQt6 Monitor GUI (WebSocket server on Port 8765)
- FastAPI Server (REST/WebSocket for companion app on Port 8000) [OPTIONAL]

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: January 3, 2026
"""

import sys
import argparse
import logging
from pathlib import Path
import subprocess
import multiprocessing

# Add laptop module to path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    API_PORT, WS_SERVER_PORT, ENABLE_API_SERVER,
    LOG_LEVEL
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_banner():
    """Print startup banner."""
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║           ██████╗ ██████╗  ██████╗      ██╗███████╗ ██████╗████████╗║
║           ██╔══██╗██╔══██╗██╔═══██╗     ██║██╔════╝██╔════╝╚══██╔══╝║
║           ██████╔╝██████╔╝██║   ██║     ██║█████╗  ██║        ██║   ║
║           ██╔═══╝ ██╔══██╗██║   ██║██   ██║██╔══╝  ██║        ██║   ║
║           ██║     ██║  ██║╚██████╔╝╚█████╔╝███████╗╚██████╗   ██║   ║
║           ╚═╝     ╚═╝  ╚═╝ ╚═════╝  ╚════╝ ╚══════╝ ╚═════╝   ╚═╝   ║
║                                                                      ║
║                ██████╗ ██████╗ ██████╗ ████████╗███████╗██╗  ██╗    ║
║               ██╔════╝██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝    ║
║               ██║     ██║   ██║██████╔╝   ██║   █████╗   ╚███╔╝     ║
║               ██║     ██║   ██║██╔══██╗   ██║   ██╔══╝   ██╔██╗     ║
║               ╚██████╗╚██████╔╝██║  ██║   ██║   ███████╗██╔╝ ██╗    ║
║                ╚═════╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝    ║
║                                                                      ║
║                         v2.0 - LAPTOP SERVER (TIER 2)               ║
║                      Real-Time Monitoring System                    ║
║                         YIA 2026 Competition                        ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
    """)


def run_gui(args):
    """Run PyQt6 Monitor GUI."""
    logger.info("🚀 Starting PyQt6 Monitor GUI...")
    
    from cortex_monitor_gui import main as gui_main
    
    try:
        gui_main()
    except Exception as e:
        logger.error(f"❌ GUI crashed: {e}", exc_info=True)
        sys.exit(1)


def run_api(args):
    """Run FastAPI Server."""
    logger.info("🚀 Starting FastAPI Server...")
    
    try:
        import uvicorn
        from cortex_api_server import app
        
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=API_PORT,
            log_level=LOG_LEVEL.lower()
        )
    
    except Exception as e:
        logger.error(f"❌ API server crashed: {e}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Project-Cortex v2.0 - Laptop Server Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run GUI only (default)
  python start_laptop_server.py
  
  # Run GUI + API server (for companion app)
  python start_laptop_server.py --enable-api
  
  # Run API server only (headless)
  python start_laptop_server.py --api-only
  
  # Custom ports
  python start_laptop_server.py --ws-port 9000 --api-port 9001

For more info, see laptop/README.md
        """
    )
    
    parser.add_argument(
        "--enable-api",
        action="store_true",
        default=ENABLE_API_SERVER,
        help="Enable FastAPI server for companion app (Port 8000)"
    )
    
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="Run API server only (no GUI)"
    )
    
    parser.add_argument(
        "--ws-port",
        type=int,
        default=WS_SERVER_PORT,
        help=f"WebSocket server port (default: {WS_SERVER_PORT})"
    )
    
    parser.add_argument(
        "--api-port",
        type=int,
        default=API_PORT,
        help=f"FastAPI server port (default: {API_PORT})"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=LOG_LEVEL,
        help=f"Log level (default: {LOG_LEVEL})"
    )
    
    args = parser.parse_args()
    
    # Update logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Print banner
    print_banner()
    
    # Show configuration
    print("📋 Configuration:")
    print(f"   WebSocket Port: {args.ws_port}")
    print(f"   API Port: {args.api_port}")
    print(f"   API Server: {'✅ Enabled' if args.enable_api or args.api_only else '❌ Disabled'}")
    print(f"   Log Level: {args.log_level}")
    print()
    
    # Check dependencies
    try:
        import PyQt6
        import websockets
        import PIL
        import numpy
        
        if args.enable_api or args.api_only:
            import fastapi
            import uvicorn
            import jose
        
        logger.info("✅ All dependencies installed")
    
    except ImportError as e:
        logger.error(f"❌ Missing dependency: {e}")
        logger.error("Run: pip install PyQt6 websockets Pillow numpy")
        
        if args.enable_api or args.api_only:
            logger.error("For API: pip install fastapi uvicorn python-jose[cryptography] passlib[bcrypt]")
        
        sys.exit(1)
    
    # Run components
    if args.api_only:
        # API server only (no GUI)
        logger.info("🔧 Running in API-only mode (headless)")
        run_api(args)
    
    elif args.enable_api:
        # Run both GUI and API server in separate processes
        logger.info("🔧 Running GUI + API server")
        
        gui_process = multiprocessing.Process(target=run_gui, args=(args,))
        api_process = multiprocessing.Process(target=run_api, args=(args,))
        
        try:
            gui_process.start()
            api_process.start()
            
            logger.info(f"✅ GUI started (PID: {gui_process.pid})")
            logger.info(f"✅ API server started (PID: {api_process.pid})")
            logger.info(f"📡 WebSocket: ws://0.0.0.0:{args.ws_port}")
            logger.info(f"🌐 API: http://0.0.0.0:{args.api_port}")
            logger.info(f"📚 Docs: http://0.0.0.0:{args.api_port}/api/v1/docs")
            
            # Wait for GUI to exit
            gui_process.join()
            
            # Terminate API server when GUI closes
            logger.info("🛑 GUI closed, stopping API server...")
            api_process.terminate()
            api_process.join(timeout=5)
            
            if api_process.is_alive():
                logger.warning("⚠️ API server didn't stop gracefully, killing...")
                api_process.kill()
        
        except KeyboardInterrupt:
            logger.info("🛑 Keyboard interrupt received, shutting down...")
            
            gui_process.terminate()
            api_process.terminate()
            
            gui_process.join(timeout=5)
            api_process.join(timeout=5)
            
            if gui_process.is_alive():
                gui_process.kill()
            if api_process.is_alive():
                api_process.kill()
    
    else:
        # GUI only (default)
        logger.info("🔧 Running in GUI-only mode")
        logger.info(f"📡 WebSocket: ws://0.0.0.0:{args.ws_port}")
        
        run_gui(args)
    
    logger.info("✅ Laptop server stopped")


if __name__ == "__main__":
    main()
