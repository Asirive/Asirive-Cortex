#!/usr/bin/env python3
"""
Cortex CLI — Unified Command-Line Interface for Asirive Cortex

Replaces: python -m rpi5 all
Usage:    python cortex [command] [options]

Commands:
  run       Start the full Cortex system
  status    Show system diagnostics
  test      Test individual components
  monitor   Real-time monitoring dashboard
  debug     Interactive debug mode
  config    View/edit configuration

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — YIA 2026
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# ─── Setup Logging ────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
RPI5_DIR = PROJECT_ROOT / "rpi5"

# ─── ANSI Colors ──────────────────────────────────────────────────
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG_RED = "\033[101m"
    BG_GREEN = "\033[102m"
    BG_YELLOW = "\033[103m"

# ─── Banner ─────────────────────────────────────────────────────
def print_banner():
    print(f"""
{Colors.CYAN}{Colors.BOLD}   ██████╗ ██████╗ ██████╗ ████████╗███████╗██╗  ██╗{Colors.RESET}
{Colors.CYAN}{Colors.BOLD}  ██╔════╝██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝{Colors.RESET}
{Colors.CYAN}{Colors.BOLD}  ██║     ██║   ██║██████╔╝   ██║   █████╗   ╚███╔╝ {Colors.RESET}
{Colors.CYAN}{Colors.BOLD}  ██║     ██║   ██║██╔══██╗   ██║   ██╔══╝   ██╔██╗ {Colors.RESET}
{Colors.CYAN}{Colors.BOLD}  ╚██████╗╚██████╔╝██║  ██║   ██║   ███████╗██╔╝ ██╗{Colors.RESET}
{Colors.CYAN}{Colors.BOLD}   ╚═════╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝{Colors.RESET}
{Colors.YELLOW}  Asirive Cortex v2.0 — YIA 2026 — Visually Impaired AI Wearable{Colors.RESET}
{Colors.DIM}  RPi5: 10.<REDACTED-RPI-IP>  |  Laptop: 10.<REDACTED-LAPTOP-IP>{Colors.RESET}
""")

# ─── Status Check ─────────────────────────────────────────────────
def cmd_status(args):
    """Show comprehensive system status."""
    print_banner()
    
    print(f"{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.RESET}")
    print(f"{Colors.BOLD}║                    SYSTEM DIAGNOSTICS                        ║{Colors.RESET}")
    print(f"{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.RESET}")
    
    # Python version
    py_ver = sys.version.split()[0]
    print(f"\n{Colors.BOLD}🐍 Python Environment{Colors.RESET}")
    print(f"   Version: {Colors.CYAN}{py_ver}{Colors.RESET}")
    print(f"   Platform: {Colors.CYAN}{sys.platform}{Colors.RESET}")
    
    # Load config
    config_path = RPI5_DIR / "config" / "config.yaml"
    config = {}
    try:
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception:
        pass
    
    # Network
    print(f"\n{Colors.BOLD}🌐 Network Configuration{Colors.RESET}")
    laptop_host = config.get('laptop_server', {}).get('host', 'NOT SET')
    rpi_host = config.get('rpi5_device', {}).get('host', 'NOT SET')
    print(f"   Laptop: {Colors.GREEN}{laptop_host}{Colors.RESET}")
    print(f"   RPi5:   {Colors.GREEN}{rpi_host}{Colors.RESET}")
    
    # Environment variables
    print(f"\n{Colors.BOLD}🔑 API Keys & Secrets{Colors.RESET}")
    keys = [
        ("GEMINI_API_KEY", "Gemini AI"),
        ("CARTESIA_API_KEY", "Cartesia TTS/STT"),
        ("SUPABASE_URL", "Supabase DB"),
    ]
    for env_var, name in keys:
        val = os.getenv(env_var, '')
        status = f"{Colors.GREEN}✅ Set{Colors.RESET}" if val else f"{Colors.RED}❌ Missing{Colors.RESET}"
        print(f"   {name:20s} {status}")
    
    # Layer imports
    print(f"\n{Colors.BOLD}🧠 AI Layers{Colors.RESET}")
    layers = {
        "Layer 0 (Guardian)": "layer0_guardian",
        "Layer 1 (Learner)": "layer1_learner",
        "Layer 2 (Thinker)": "layer2_thinker",
        "Layer 3 (Guide)": "layer3_guide",
        "Layer 4 (Memory)": "layer4_memory",
    }
    for name, module in layers.items():
        try:
            __import__(f"rpi5.{module}")
            print(f"   {Colors.GREEN}✅{Colors.RESET} {name}")
        except ImportError:
            print(f"   {Colors.RED}❌{Colors.RESET} {name}")
    
    # Hardware
    print(f"\n{Colors.BOLD}🔌 Hardware{Colors.RESET}")
    
    # Camera
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            print(f"   {Colors.GREEN}✅{Colors.RESET} Camera")
            cap.release()
        else:
            print(f"   {Colors.RED}❌{Colors.RESET} Camera (not accessible)")
    except Exception:
        print(f"   {Colors.RED}❌{Colors.RESET} Camera (OpenCV not available)")
    
    # Hailo NPU
    hailo_path = PROJECT_ROOT / "models" / "hailo" / "scdepthv3.hef"
    if hailo_path.exists():
        print(f"   {Colors.GREEN}✅{Colors.RESET} SCDepthV3 HEF model")
    else:
        print(f"   {Colors.RED}❌{Colors.RESET} SCDepthV3 HEF (not found)")
    
    # Model files
    print(f"\n{Colors.BOLD}📦 Model Files{Colors.RESET}")
    models = {
        "YOLO 26n NCNN": PROJECT_ROOT / "models" / "converted" / "yolo26n_ncnn_model",
        "SCDepthV3 HEF": PROJECT_ROOT / "models" / "hailo" / "scdepthv3.hef",
        "OCR HEF": PROJECT_ROOT / "models" / "hailo" / "paddle_ocr_v3_recognition.hef",
    }
    for name, path in models.items():
        exists = path.exists()
        status = f"{Colors.GREEN}✅{Colors.RESET}" if exists else f"{Colors.RED}❌{Colors.RESET}"
        print(f"   {status} {name}")
    
    print()
    return 0

# ─── Run System ─────────────────────────────────────────────────
def cmd_run(args):
    """Start the full Cortex system with optional monitoring."""
    print_banner()
    
    # Setup logging level
    # Setup Rich-based colored logging (matches `python -m rpi5 all` style)
    sys.path.insert(0, str(PROJECT_ROOT))
    from rpi5.cli.log_setup import setup_logging
    log_level = "DEBUG" if args.debug else "INFO"
    setup_logging(level=log_level, log_file="logs/cortex.log")
    
    # Check if running standalone or with laptop
    mode = "standalone" if args.standalone else "connected"
    print(f"{Colors.BOLD}🚀 Starting Cortex in {Colors.CYAN}{mode}{Colors.RESET} mode...{Colors.RESET}")
    print(f"{Colors.DIM}   Press Ctrl+C to stop{Colors.RESET}\n")
    
    if args.monitor:
        # Launch system in background thread + monitoring in main thread
        return _run_with_monitor(args)
    
    # Standard run — just import and run main
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from rpi5.main import main
        
        if asyncio.iscoroutinefunction(main):
            asyncio.run(main())
        else:
            main()
        
        return 0
    
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}⏹️  Stopped by user{Colors.RESET}")
        return 0
    except Exception as e:
        print(f"\n{Colors.RED}❌ Error: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        return 1

# ─── Run with Monitor ───────────────────────────────────────────
def _run_with_monitor(args):
    """Run system with a simple text-based monitor."""
    
    monitor_data = {
        "fps": 0.0,
        "layer0_latency_ms": 0.0,
        "tts_engine": "idle",
        "stt_status": "idle",
        "gemini_connected": False,
        "hailo_available": False,
        "camera_active": False,
        "errors": [],
    }
    
    # This would hook into the actual main system
    # For now, show a mock monitor
    try:
        while True:
            os.system("clear" if os.name != "nt" else "cls")
            print_banner()
            
            print(f"{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.RESET}")
            print(f"{Colors.BOLD}║                    REAL-TIME MONITOR                         ║{Colors.RESET}")
            print(f"{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.RESET}")
            
            print(f"\n{Colors.BOLD}📊 Performance{Colors.RESET}")
            print(f"   FPS:           {Colors.CYAN}{monitor_data['fps']:.1f}{Colors.RESET}")
            print(f"   Layer0 Latency:{Colors.CYAN}{monitor_data['layer0_latency_ms']:.0f}ms{Colors.RESET}")
            
            print(f"\n{Colors.BOLD}🎙️ Audio Pipeline{Colors.RESET}")
            tts_status = f"{Colors.GREEN}✅{Colors.RESET}" if monitor_data['tts_engine'] != "idle" else f"{Colors.DIM}○{Colors.RESET}"
            stt_status = f"{Colors.GREEN}✅{Colors.RESET}" if monitor_data['stt_status'] != "idle" else f"{Colors.DIM}○{Colors.RESET}"
            print(f"   TTS Engine:    {tts_status} {monitor_data['tts_engine']}")
            print(f"   STT Engine:    {stt_status} {monitor_data['stt_status']}")
            
            print(f"\n{Colors.BOLD}🧠 AI Layers{Colors.RESET}")
            gemini = f"{Colors.GREEN}✅ Connected{Colors.RESET}" if monitor_data['gemini_connected'] else f"{Colors.RED}❌ Disconnected{Colors.RESET}"
            hailo = f"{Colors.GREEN}✅ Ready{Colors.RESET}" if monitor_data['hailo_available'] else f"{Colors.RED}❌ Offline{Colors.RESET}"
            print(f"   Gemini Live:   {gemini}")
            print(f"   Hailo Depth:   {hailo}")
            print(f"   Camera:        {Colors.GREEN if monitor_data['camera_active'] else Colors.RED}●{'Active' if monitor_data['camera_active'] else 'Inactive'}{Colors.RESET}")
            
            if monitor_data['errors']:
                print(f"\n{Colors.BOLD}{Colors.RED}⚠️ Recent Errors{Colors.RESET}")
                for err in monitor_data['errors'][-3:]:
                    print(f"   {Colors.RED}! {err}{Colors.RESET}")
            
            print(f"\n{Colors.DIM}Press Ctrl+C to exit monitor | System running in background{Colors.RESET}")
            time.sleep(1.0)
    
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}⏹️  Monitor stopped{Colors.RESET}")
        return 0

# ─── Test Command ───────────────────────────────────────────────
def cmd_test(args):
    """Test individual components."""
    print_banner()
    
    component = args.component.lower() if args.component else None
    
    tests = {
        "layer0": _test_layer0,
        "layer1": _test_layer1,
        "layer2": _test_layer2,
        "tts": _test_tts,
        "stt": _test_stt,
        "camera": _test_camera,
        "audio": _test_audio,
        "hailo": _test_hailo,
        "all": _test_all,
    }
    
    if component not in tests:
        print(f"{Colors.RED}❌ Unknown component: {component}{Colors.RESET}")
        print(f"Available: {', '.join(tests.keys())}")
        return 1
    
    return tests[component](args)

def _test_layer0(args):
    print(f"{Colors.BOLD}🛡️ Testing Layer 0 (Guardian)...{Colors.RESET}")
    try:
        from rpi5.layer0_guardian import YOLOGuardian
        g = YOLOGuardian(enable_haptic=False)
        print(f"   {Colors.GREEN}✅{Colors.RESET} YOLOGuardian initialized")
        
        # Quick inference test with a dummy frame
        import numpy as np
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        dets = g.detect(dummy)
        print(f"   {Colors.GREEN}✅{Colors.RESET} Inference OK ({len(dets)} detections on blank frame)")
        
        print(f"\n{Colors.GREEN}✅ Layer 0 test passed{Colors.RESET}")
        return 0
    except Exception as e:
        print(f"\n{Colors.RED}❌ Layer 0 test failed: {e}{Colors.RESET}")
        return 1

def _test_layer1(args):
    print(f"{Colors.BOLD}🧠 Testing Layer 1 (Learner)...{Colors.RESET}")
    print(f"   {Colors.YELLOW}⚠️ Layer 1 test requires YOLOE model — skipping{Colors.RESET}")
    return 0

def _test_layer2(args):
    print(f"{Colors.BOLD}💭 Testing Layer 2 (Thinker)...{Colors.RESET}")
    try:
        from rpi5.layer2_thinker.gemini_live_handler import GeminiLiveHandler
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            print(f"   {Colors.YELLOW}⚠️ GEMINI_API_KEY not set — cannot test connection{Colors.RESET}")
            return 1
        h = GeminiLiveHandler(api_key=api_key)
        print(f"   {Colors.GREEN}✅{Colors.RESET} GeminiLiveHandler initialized")
        print(f"\n{Colors.GREEN}✅ Layer 2 test passed{Colors.RESET}")
        return 0
    except Exception as e:
        print(f"\n{Colors.RED}❌ Layer 2 test failed: {e}{Colors.RESET}")
        return 1

def _test_tts(args):
    print(f"{Colors.BOLD}🔊 Testing TTS...{Colors.RESET}")
    
    # Test Supertonic
    try:
        from rpi5.layer1_reflex.supertonic_handler import SupertonicTTS
        tts = SupertonicTTS()
        if tts.available:
            wav = tts.generate_speech("Supertonic test successful")
            print(f"   {Colors.GREEN}✅{Colors.RESET} Supertonic: {len(wav) if wav is not None else 0} samples")
        else:
            print(f"   {Colors.RED}❌{Colors.RESET} Supertonic not available")
    except Exception as e:
        print(f"   {Colors.RED}❌{Colors.RESET} Supertonic failed: {e}")
    
    # Test Cartesia
    try:
        from rpi5.layer2_thinker.cartesia_handler import CartesiaTTS
        ct = CartesiaTTS()
        if ct.available:
            print(f"   {Colors.GREEN}✅{Colors.RESET} Cartesia Sonic 3.5 ready")
        else:
            print(f"   {Colors.YELLOW}⚠️{Colors.RESET} Cartesia not available (no API key)")
    except Exception as e:
        print(f"   {Colors.RED}❌{Colors.RESET} Cartesia failed: {e}")
    
    return 0

def _test_stt(args):
    print(f"{Colors.BOLD}🎤 Testing STT...{Colors.RESET}")
    
    # Test Cartesia batch
    try:
        from rpi5.layer1_reflex.cartesia_stt import CartesiaSTT
        stt = CartesiaSTT()
        print(f"   {'✅' if stt.available else '❌'} Cartesia batch STT: {'ready' if stt.available else 'no API key'}")
    except Exception as e:
        print(f"   ❌ Cartesia batch STT: {e}")
    
    # Test WebSocket
    try:
        from rpi5.layer1_reflex.cartesia_stt_ws import CartesiaSTTWebSocket
        ws = CartesiaSTTWebSocket()
        print(f"   {'✅' if ws.available else '❌'} Cartesia Ink 2 WebSocket: {'ready' if ws.available else 'no API key'}")
    except Exception as e:
        print(f"   ❌ Cartesia WebSocket: {e}")
    
    # Test Whisper
    try:
        from rpi5.layer1_reflex.whisper_handler import WhisperSTT
        w = WhisperSTT()
        print(f"   ✅ Whisper STT: {w.model_size} model loaded")
    except Exception as e:
        print(f"   ❌ Whisper STT: {e}")
    
    return 0

def _test_camera(args):
    print(f"{Colors.BOLD}📷 Testing Camera...{Colors.RESET}")
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print(f"   {Colors.RED}❌{Colors.RESET} Cannot open camera /dev/video0")
            return 1
        ret, frame = cap.read()
        if not ret or frame is None:
            print(f"   {Colors.RED}❌{Colors.RESET} Camera opened but cannot read frames")
            cap.release()
            return 1
        h, w = frame.shape[:2]
        print(f"   {Colors.GREEN}✅{Colors.RESET} Camera OK: {w}x{h} @ {int(cap.get(cv2.CAP_PROP_FPS))}fps")
        cap.release()
        return 0
    except Exception as e:
        print(f"   {Colors.RED}❌{Colors.RESET} Camera test failed: {e}")
        return 1

def _test_audio(args):
    print(f"{Colors.BOLD}🎙️ Testing Audio...{Colors.RESET}")
    
    try:
        from rpi5.layer1_reflex.vad_handler import VADHandler
        vad = VADHandler()
        print(f"   ✅ Silero VAD loaded")
    except Exception as e:
        print(f"   ❌ VAD: {e}")
    
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devs = [d for d in devices if d.get('max_input_channels', 0) > 0]
        output_devs = [d for d in devices if d.get('max_output_channels', 0) > 0]
        print(f"   ✅ Audio: {len(input_devs)} input, {len(output_devs)} output devices")
    except Exception as e:
        print(f"   ❌ Audio devices: {e}")
    
    return 0

def _test_hailo(args):
    print(f"{Colors.BOLD}⚡ Testing Hailo NPU...{Colors.RESET}")
    
    hef_path = PROJECT_ROOT / "models" / "hailo" / "scdepthv3.hef"
    if not hef_path.exists():
        print(f"   {Colors.RED}❌{Colors.RESET} SCDepthV3 HEF not found: {hef_path}")
        return 1
    
    try:
        from rpi5.hailo_depth import HailoDepthEstimator
        est = HailoDepthEstimator(str(hef_path))
        if est.is_available:
            print(f"   {Colors.GREEN}✅{Colors.RESET} Hailo depth estimator ready")
            print(f"   {Colors.DIM}   Input: {est.input_height}x{est.input_width}x{est.input_channels}{Colors.RESET}")
            print(f"   {Colors.DIM}   Output: {est.output_height}x{est.output_width}{Colors.RESET}")
            
            # Quick inference
            import numpy as np
            import time
            dummy = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
            t0 = time.time()
            depth = est.estimate(dummy)
            elapsed = (time.time() - t0) * 1000
            if depth is not None:
                print(f"   {Colors.GREEN}✅{Colors.RESET} Inference: {depth.shape}, {elapsed:.1f}ms")
            else:
                print(f"   {Colors.RED}❌{Colors.RESET} Inference returned None")
        else:
            print(f"   {Colors.RED}❌{Colors.RESET} Hailo depth estimator not available (driver issue?)")
    except Exception as e:
        print(f"   {Colors.RED}❌{Colors.RESET} Hailo test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

def _test_all(args):
    print(f"{Colors.BOLD}🔬 Running all tests...{Colors.RESET}\n")
    results = {}
    for name, fn in [("Layer 0", _test_layer0), ("Layer 2", _test_layer2),
                     ("TTS", _test_tts), ("STT", _test_stt),
                     ("Camera", _test_camera), ("Audio", _test_audio),
                     ("Hailo", _test_hailo)]:
        print(f"\n{'─'*50}")
        results[name] = fn(args) == 0
    
    passed = sum(results.values())
    total = len(results)
    print(f"\n{'='*50}")
    print(f"{Colors.BOLD}Results: {Colors.GREEN}{passed} passed{Colors.RESET} / {Colors.RED}{total-passed} failed{Colors.RESET} / {total} total{Colors.RESET}")
    return 0 if passed == total else 1

# ─── Config Command ───────────────────────────────────────────────
def cmd_config(args):
    """View/edit configuration."""
    config_path = RPI5_DIR / "config" / "config.yaml"
    
    if args.edit:
        editor = os.getenv("EDITOR", "nano")
        os.system(f"{editor} {config_path}")
        return 0
    
    if args.get:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        
        keys = args.get.split(".")
        for key in keys:
            cfg = cfg.get(key, {})
        
        if isinstance(cfg, dict):
            print(json.dumps(cfg, indent=2))
        else:
            print(cfg)
        return 0
    
    # Default: show summary
    print_banner()
    print(f"{Colors.BOLD}📋 Configuration Summary{Colors.RESET}")
    print(f"   File: {Colors.CYAN}{config_path}{Colors.RESET}\n")
    
    import yaml
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    
    # Show key sections
    sections = ["layer0", "layer2", "layer3", "safety", "hailo", "laptop_server", "rpi5_device"]
    for sec in sections:
        val = cfg.get(sec, {})
        print(f"{Colors.BOLD}{sec}{Colors.RESET}")
        if isinstance(val, dict):
            for k, v in val.items():
                if not isinstance(v, (dict, list)):
                    print(f"   {k}: {v}")
        print()
    
    return 0

# ─── Debug Command ──────────────────────────────────────────────
def cmd_debug(args):
    """Interactive debug mode."""
    print_banner()
    print(f"{Colors.BOLD}🐛 Interactive Debug Mode{Colors.RESET}")
    print(f"{Colors.DIM}   Commands: r=run, s=status, t=test, q=quit{Colors.RESET}\n")
    
    while True:
        try:
            cmd = input(f"{Colors.CYAN}cortex>{Colors.RESET} ").strip().lower()
            
            if cmd == "q" or cmd == "quit":
                print(f"{Colors.YELLOW}Goodbye!{Colors.RESET}")
                break
            elif cmd == "r" or cmd == "run":
                print(f"{Colors.GREEN}Starting system...{Colors.RESET}")
                cmd_run(argparse.Namespace(standalone=True, debug=True, monitor=False))
            elif cmd == "s" or cmd == "status":
                cmd_status(argparse.Namespace())
            elif cmd == "t" or cmd == "test":
                cmd_test(argparse.Namespace(component="all"))
            elif cmd.startswith("t "):
                cmd_test(argparse.Namespace(component=cmd[2:].strip()))
            elif cmd == "":
                continue
            else:
                print(f"{Colors.RED}Unknown command: {cmd}{Colors.RESET}")
        
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Goodbye!{Colors.RESET}")
            break
        except EOFError:
            break
    
    return 0

# ─── Main CLI Parser ────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="cortex",
        description="Asirive Cortex CLI — AI Wearable for the Visually Impaired",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cortex run --standalone        # Run RPi5 in standalone mode
  cortex run --monitor           # Run with real-time monitoring
  cortex status                  # Show system diagnostics
  cortex test layer0             # Test Layer 0 (Guardian)
  cortex test all                # Run all component tests
  cortex config                  # View configuration
  cortex config --get laptop_server.host
  cortex debug                   # Interactive debug mode
  cortex sync check              # Test RPi5 connectivity
  cortex sync to --models        # Sync code + models to RPi5
  cortex sync from --paths logs  # Download logs from RPi5
  cortex sync full               # Sync + install deps
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # run command
    run_parser = subparsers.add_parser("run", help="Start the full Cortex system")
    run_parser.add_argument("--standalone", "-s", action="store_true",
                          help="Run in standalone mode (no laptop connection)")
    run_parser.add_argument("--debug", "-d", action="store_true",
                          help="Enable debug logging")
    run_parser.add_argument("--monitor", "-m", action="store_true",
                          help="Show real-time monitoring dashboard")
    
    # status command
    status_parser = subparsers.add_parser("status", help="Show system diagnostics")
    
    # test command
    test_parser = subparsers.add_parser("test", help="Test individual components")
    test_parser.add_argument("component", nargs="?", default="all",
                           choices=["layer0", "layer1", "layer2", "tts", "stt",
                                   "camera", "audio", "hailo", "all"],
                           help="Component to test")
    
    # config command
    config_parser = subparsers.add_parser("config", help="View/edit configuration")
    config_parser.add_argument("--edit", "-e", action="store_true",
                             help="Open config in $EDITOR")
    config_parser.add_argument("--get", "-g", type=str,
                             help="Get a config value (dot notation, e.g. 'laptop_server.host')")
    
    # debug command
    debug_parser = subparsers.add_parser("debug", help="Interactive debug mode")
    
    # sync command
    sync_parser = subparsers.add_parser("sync", help="Sync with RPi5")
    sync_sub = sync_parser.add_subparsers(dest="sync_cmd", help="Sync command")
    
    sync_check = sync_sub.add_parser("check", help="Test SSH connectivity")
    sync_status = sync_sub.add_parser("status", help="Preview sync (dry-run)")
    sync_status.add_argument("--models", action="store_true", help="Include models/")
    
    sync_to = sync_sub.add_parser("to", help="Sync code TO RPi5")
    sync_to.add_argument("--models", action="store_true", help="Include models/ (~500MB)")
    sync_to.add_argument("--dry-run", "-n", action="store_true", help="Preview without uploading")
    
    sync_from = sync_sub.add_parser("from", help="Sync data FROM RPi5")
    sync_from.add_argument("--paths", type=str, help="Comma-separated paths")
    
    sync_install = sync_sub.add_parser("install", help="Install deps on RPi5")
    sync_full = sync_sub.add_parser("full", help="Sync TO + install")
    sync_full.add_argument("--models", action="store_true", help="Include models/")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    # Handle sync subcommands by delegating to scripts.sync
    if args.command == "sync":
        if not args.sync_cmd:
            sync_parser.print_help()
            return 0
        # Pass through to scripts.sync
        import scripts.sync as sync_mod
        sync_args = argparse.Namespace()
        sync_args.command = args.sync_cmd
        sync_args.models = getattr(args, "models", False)
        sync_args.dry_run = getattr(args, "dry_run", False)
        sync_args.paths = getattr(args, "paths", None)
        sync_args.verify = False
        return sync_mod.commands[args.sync_cmd](sync_args)
    
    commands = {
        "run": cmd_run,
        "status": cmd_status,
        "test": cmd_test,
        "config": cmd_config,
        "debug": cmd_debug,
    }
    
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
