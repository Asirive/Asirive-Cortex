"""
CLI Command Implementations for ProjectCortex RPi5

This module contains the command handlers for the RPi5 CLI.

Author: Haziq (@IRSPlays)
Date: January 11, 2026
"""

import sys
import time
import logging
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_layer(layer_num: str, laptop_host: str = "10.226.221.101") -> int:
    """Run a single layer for testing"""
    print(f"Starting Layer {layer_num}...")

    try:
        if layer_num == "0":
            from layer0_guardian import YOLOGuardian
            from config.config import get_config

            config = get_config()
            guardian = YOLOGuardian(
                model_path=config['layer0']['model_path'],
                device=config['layer0']['device'],
                confidence=config['layer0']['confidence'],
                enable_haptic=config['layer0']['enable_haptic'],
                gpio_pin=config['layer0']['gpio_pin'],
                memory_manager=None
            )
            print("Layer 0 (Guardian) initialized. Testing with sample frames...")
            # TODO: Add test loop

        elif layer_num == "1":
            from layer1_learner import YOLOELearner, YOLOEMode
            from config.config import get_config

            config = get_config()
            mode_map = {
                'PROMPT_FREE': YOLOEMode.PROMPT_FREE,
                'TEXT_PROMPTS': YOLOEMode.TEXT_PROMPTS,
                'VISUAL_PROMPTS': YOLOEMode.VISUAL_PROMPTS
            }
            learner = YOLOELearner(
                model_path=config['layer1']['model_path'],
                device=config['layer1']['device'],
                confidence=config['layer1']['confidence'],
                mode=mode_map.get(config['layer1']['mode'], YOLOEMode.TEXT_PROMPTS),
                memory_manager=None
            )
            print("Layer 1 (Learner) initialized. Testing with sample frames...")
            # TODO: Add test loop

        elif layer_num == "2":
            from layer2_thinker.gemini_live_handler import GeminiLiveHandler
            import os

            api_key = os.getenv('GEMINI_API_KEY', '')
            if not api_key:
                print("Error: GEMINI_API_KEY not set")
                return 1

            handler = GeminiLiveHandler(api_key=api_key)
            print("Layer 2 (Thinker) initialized. Ready for Gemini Live API...")
            # TODO: Add test

        elif layer_num == "3":
            from layer3_guide.router import IntentRouter
            from layer3_guide.detection_router import DetectionRouter

            intent_router = IntentRouter()
            detection_router = DetectionRouter()
            print("Layer 3 (Guide) initialized. Ready for routing...")

        elif layer_num == "4":
            from layer4_memory.hybrid_memory_manager import HybridMemoryManager
            from config.config import get_config
            import os

            config = get_config()
            memory = HybridMemoryManager(
                supabase_url=config['supabase']['url'] or os.getenv('SUPABASE_URL', ''),
                supabase_key=config['supabase']['anon_key'] or os.getenv('SUPABASE_KEY', ''),
                device_id=config['supabase']['device_id'],
                local_db_path=config['supabase']['local_db_path'],
                sync_interval=config['supabase']['sync_interval_seconds'],
                batch_size=config['supabase']['batch_size'],
                local_cache_size=config['supabase']['local_cache_size']
            )
            print("Layer 4 (Memory) initialized. Testing local storage...")
            # TODO: Add test

        else:
            print(f"Unknown layer: {layer_num}")
            return 1

        print(f"Layer {layer_num} test completed")
        return 0

    except ImportError as e:
        print(f"Failed to import Layer {layer_num}: {e}")
        return 1
    except Exception as e:
        print(f"Error running Layer {layer_num}: {e}")
        import traceback
        traceback.print_exc()
        return 1


def test_camera(device_id: int = 0) -> int:
    """Test camera capture"""
    print(f"Testing camera (device {device_id})...")

    try:
        from main import CameraHandler

        camera = CameraHandler(
            camera_id=device_id,
            use_picamera=False,  # Use OpenCV for testing
            resolution=(640, 480),
            fps=30
        )
        camera.start()

        print("Capturing frames for 5 seconds...")
        time.sleep(5)

        camera.stop()
        print("Camera test completed successfully")
        return 0

    except Exception as e:
        print(f"Camera test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def test_audio() -> int:
    """Test audio I/O"""
    print("Testing audio I/O...")

    try:
        # Test VAD
        from layer1_reflex.vad_handler import VADHandler
        vad = VADHandler()
        print("VAD handler initialized")

        # Test Whisper STT
        from layer1_reflex.whisper_handler import WhisperSTT
        stt = WhisperSTT()
        print("Whisper STT initialized")

        # Test Kokoro TTS (if available)
        try:
            from layer1_reflex.kokoro_handler import KokoroTTS
            tts = KokoroTTS()
            print("Kokoro TTS initialized")
        except ImportError:
            print("Kokoro TTS not available (optional)")

        print("Audio I/O test completed")
        return 0

    except Exception as e:
        print(f"Audio test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def run_self_test() -> int:
    """Run self-test diagnostics"""
    print("Running ProjectCortex self-test diagnostics...")
    print("=" * 50)

    tests_passed = 0
    tests_failed = 0

    # Test 1: Python version
    print("\n[1/8] Python version...")
    version = sys.version.split()[0]
    print(f"    Python {version} - OK")
    tests_passed += 1

    # Test 2: Configuration
    print("\n[2/8] Configuration...")
    try:
        from config.config import get_config
        config = get_config()
        print("    Configuration loaded - OK")
        tests_passed += 1
    except Exception as e:
        print(f"    Configuration failed: {e}")
        tests_failed += 1

    # Test 3: Layer 0 (Guardian)
    print("\n[3/8] Layer 0 (Guardian)...")
    try:
        from layer0_guardian import YOLOGuardian
        print("    Layer 0 imported - OK")
        tests_passed += 1
    except ImportError as e:
        print(f"    Layer 0 import failed: {e}")
        tests_failed += 1

    # Test 4: Layer 1 (Learner)
    print("\n[4/8] Layer 1 (Learner)...")
    try:
        from layer1_learner import YOLOELearner
        print("    Layer 1 imported - OK")
        tests_passed += 1
    except ImportError as e:
        print(f"    Layer 1 import failed: {e}")
        tests_failed += 1

    # Test 5: Layer 2 (Thinker)
    print("\n[5/8] Layer 2 (Thinker)...")
    try:
        from layer2_thinker.gemini_live_handler import GeminiLiveHandler
        print("    Layer 2 imported - OK")
        tests_passed += 1
    except ImportError as e:
        print(f"    Layer 2 import failed: {e}")
        tests_failed += 1

    # Test 6: Layer 3 (Guide)
    print("\n[6/8] Layer 3 (Guide)...")
    try:
        from layer3_guide.router import IntentRouter
        print("    Layer 3 imported - OK")
        tests_passed += 1
    except ImportError as e:
        print(f"    Layer 3 import failed: {e}")
        tests_failed += 1

    # Test 7: Layer 4 (Memory)
    print("\n[7/8] Layer 4 (Memory)...")
    try:
        from layer4_memory.hybrid_memory_manager import HybridMemoryManager
        print("    Layer 4 imported - OK")
        tests_passed += 1
    except ImportError as e:
        print(f"    Layer 4 import failed: {e}")
        tests_failed += 1

    # Test 8: Camera
    print("\n[8/8] Camera...")
    try:
        from main import CameraHandler
        print("    Camera handler imported - OK")
        tests_passed += 1
    except ImportError as e:
        print(f"    Camera import failed: {e}")
        tests_failed += 1

    # Summary
    print("\n" + "=" * 50)
    print(f"Self-test complete: {tests_passed} passed, {tests_failed} failed")

    return 0 if tests_failed == 0 else 1


def connect_to_laptop(host: str = "10.226.221.101", port: int = 8765) -> int:
    """Connect to laptop dashboard"""
    print(f"Connecting to laptop dashboard at {host}:{port}...")

    try:
        from fastapi_client import CortexFastAPIClient

        client = CortexFastAPIClient(
            host=host,
            port=port,
            device_id="rpi5-cortex-cli"
        )

        print("Starting FastAPI client...")
        client.start()

        print("Connected! Press Ctrl+C to disconnect.")
        # Keep running
        import time
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nDisconnecting...")
        if 'client' in dir():
            client.stop()
        print("Disconnected")
        return 0

    except Exception as e:
        print(f"Connection failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def check_status() -> int:
    """Check system status"""
    print("ProjectCortex RPi5 System Status")
    print("=" * 40)

    # Check Python
    print(f"Python: {sys.version.split()[0]}")

    # Check config
    try:
        from config.config import get_config
        config = get_config()
        print(f"Laptop: {config['laptop_server']['host']}:{config['laptop_server']['port']}")
    except Exception as e:
        print(f"Config: Error - {e}")

    # Check layers
    layers = ["layer0_guardian", "layer1_learner", "layer2_thinker", "layer3_guide", "layer4_memory"]
    for layer in layers:
        try:
            __import__(layer)
            print(f"Layer {layer[-1]}: Available")
        except ImportError:
            print(f"Layer {layer[-1]}: Not available")

    # Check environment
    import os
    gemini_key = "***" if os.getenv('GEMINI_API_KEY') else "Not set"
    supabase_url = "***" if os.getenv('SUPABASE_URL') else "Not set"
    print(f"\nEnvironment:")
    print(f"  GEMINI_API_KEY: {gemini_key}")
    print(f"  SUPABASE_URL: {supabase_url}")

    return 0
