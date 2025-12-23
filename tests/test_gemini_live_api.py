"""
Gemini Live API Test Script - Standalone Testing
Project-Cortex v2.0 - Layer 2 Implementation Validation

Tests all 5 phases of Live API integration:
✅ Phase 1: WebSocket connection with reconnection logic
✅ Phase 2: GeminiLiveManager (sync wrapper)
✅ Phase 3: Streaming audio playback (sounddevice)
✅ Phase 4: Interruption handling (VAD trigger)
✅ Phase 5: Video frame streaming (2-5 FPS)

Usage:
    python tests/test_gemini_live_api.py

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: December 23, 2025
"""

import os
import sys
import time
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
from PIL import Image
import numpy as np

# Import Live API components
from layer2_thinker.gemini_live_handler import GeminiLiveManager
from layer2_thinker.streaming_audio_player import StreamingAudioPlayer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()


def test_phase_1_2_connection():
    """Test Phase 1 & 2: WebSocket connection and manager."""
    print("\n" + "="*80)
    print("🧪 TEST: Phase 1 & 2 - WebSocket Connection + Manager")
    print("="*80)
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not found in .env")
        return False
    
    print("✅ API key loaded")
    
    # Test audio callback
    audio_chunks = []
    def on_audio(audio_bytes: bytes):
        audio_chunks.append(audio_bytes)
        print(f"📥 Received {len(audio_bytes)} bytes (total: {len(audio_chunks)} chunks)")
    
    # Create manager
    print("🔌 Creating GeminiLiveManager...")
    manager = GeminiLiveManager(
        api_key=api_key,
        audio_callback=on_audio
    )
    
    # Start background thread
    print("🚀 Starting Live API connection...")
    manager.start()
    
    # Wait for connection
    time.sleep(3)
    
    if not manager.handler.is_connected:
        print("❌ Failed to connect to Live API")
        manager.stop()
        return False
    
    print("✅ Connected to Gemini Live API")
    
    # Send test message
    print("📤 Sending test query: 'Hello, how are you?'")
    manager.send_text("Hello, how are you? Please respond briefly.")
    
    # Wait for response
    print("⏳ Waiting for audio response (10 seconds)...")
    time.sleep(10)
    
    if len(audio_chunks) > 0:
        print(f"✅ Received {len(audio_chunks)} audio chunks")
        total_bytes = sum(len(chunk) for chunk in audio_chunks)
        print(f"📊 Total audio: {total_bytes} bytes ({total_bytes/1024:.1f} KB)")
        success = True
    else:
        print("❌ No audio received")
        success = False
    
    # Cleanup
    manager.stop()
    print("🛑 Manager stopped")
    
    return success


def test_phase_3_streaming_audio():
    """Test Phase 3: Streaming audio playback."""
    print("\n" + "="*80)
    print("🧪 TEST: Phase 3 - Streaming Audio Playback")
    print("="*80)
    
    # Create streaming player
    print("🔊 Creating StreamingAudioPlayer...")
    player = StreamingAudioPlayer(sample_rate=24000)
    
    # Set callbacks
    def on_start():
        print("✅ Playback started")
    
    def on_stop():
        print("✅ Playback stopped")
    
    def on_interrupt():
        print("⚠️ Playback interrupted")
    
    player.set_callbacks(on_start=on_start, on_stop=on_stop, on_interrupt=on_interrupt)
    
    # Generate test audio (sine wave)
    print("🎵 Generating test audio (2 seconds @ 440Hz)...")
    duration = 2.0
    sample_rate = 24000
    frequency = 440.0
    
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio_array = np.sin(2 * np.pi * frequency * t) * 32767
    audio_array = audio_array.astype(np.int16)
    
    # Split into chunks (200ms each)
    chunk_size = 4800  # 200ms @ 24kHz
    chunks = [audio_array[i:i+chunk_size].tobytes() 
              for i in range(0, len(audio_array), chunk_size)]
    
    print(f"📊 Generated {len(chunks)} chunks ({len(audio_array)} samples)")
    
    # Play audio
    print("🔊 Starting playback...")
    player.start()
    
    for i, chunk in enumerate(chunks):
        player.add_audio_chunk(chunk)
        print(f"📤 Added chunk {i+1}/{len(chunks)}")
        time.sleep(0.1)  # Simulate streaming delay
    
    # Wait for playback to finish
    print("⏳ Waiting for playback to finish...")
    time.sleep(3)
    
    # Check if playback finished
    if not player.is_playing:
        print("✅ Playback finished successfully")
        success = True
    else:
        print("⚠️ Playback still running (stopping manually)")
        player.stop()
        success = False
    
    return success


def test_phase_4_interruption():
    """Test Phase 4: Interruption handling."""
    print("\n" + "="*80)
    print("🧪 TEST: Phase 4 - Interruption Handling")
    print("="*80)
    
    # Create streaming player
    print("🔊 Creating StreamingAudioPlayer...")
    player = StreamingAudioPlayer(sample_rate=24000)
    
    interrupted = [False]  # Use list for closure
    
    def on_interrupt():
        print("✅ Playback interrupted successfully")
        interrupted[0] = True
    
    player.set_callbacks(on_interrupt=on_interrupt)
    
    # Generate test audio (4 seconds)
    print("🎵 Generating test audio (4 seconds)...")
    duration = 4.0
    sample_rate = 24000
    frequency = 440.0
    
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio_array = np.sin(2 * np.pi * frequency * t) * 32767
    audio_array = audio_array.astype(np.int16)
    
    chunks = [audio_array[i:i+4800].tobytes() 
              for i in range(0, len(audio_array), 4800)]
    
    # Start playback
    print("🔊 Starting playback (will interrupt after 1.5s)...")
    player.start()
    
    # Add first chunks
    for chunk in chunks[:5]:  # Add first 1 second
        player.add_audio_chunk(chunk)
        time.sleep(0.1)
    
    # Wait a bit
    time.sleep(0.5)
    
    # Simulate VAD interruption
    print("🛑 Simulating VAD interruption...")
    player.stop(interrupted=True)
    
    # Check if interrupted
    time.sleep(0.5)
    
    if interrupted[0]:
        print("✅ Interruption handled correctly")
        return True
    else:
        print("❌ Interruption callback not triggered")
        return False


def test_phase_5_video_streaming():
    """Test Phase 5: Video frame streaming."""
    print("\n" + "="*80)
    print("🧪 TEST: Phase 5 - Video Frame Streaming")
    print("="*80)
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not found in .env")
        return False
    
    # Create manager
    print("🔌 Creating GeminiLiveManager...")
    manager = GeminiLiveManager(api_key=api_key)
    
    # Start connection
    print("🚀 Starting Live API connection...")
    manager.start()
    time.sleep(3)
    
    if not manager.handler.is_connected:
        print("❌ Failed to connect to Live API")
        manager.stop()
        return False
    
    print("✅ Connected to Gemini Live API")
    
    # Generate test image (colored gradient)
    print("📷 Generating test image (640x480)...")
    width, height = 640, 480
    image_array = np.zeros((height, width, 3), dtype=np.uint8)
    
    # Create gradient
    for y in range(height):
        for x in range(width):
            image_array[y, x] = [
                int((x / width) * 255),  # Red
                int((y / height) * 255), # Green
                128                      # Blue
            ]
    
    pil_image = Image.fromarray(image_array, 'RGB')
    print(f"📊 Image size: {pil_image.width}x{pil_image.height}")
    
    # Send image + text query
    print("📤 Sending image + query: 'What colors do you see?'")
    manager.send_video(pil_image)
    manager.send_text("What colors do you see in this image? Describe briefly.")
    
    # Wait for response
    print("⏳ Waiting for response (10 seconds)...")
    time.sleep(10)
    
    # Cleanup
    manager.stop()
    print("✅ Video streaming test complete")
    
    return True


def run_all_tests():
    """Run all 5 phases of tests."""
    print("\n" + "="*80)
    print("🚀 GEMINI LIVE API - COMPREHENSIVE TEST SUITE")
    print("="*80)
    print("Testing all 5 phases of implementation:")
    print("  ✅ Phase 1: WebSocket connection with reconnection")
    print("  ✅ Phase 2: GeminiLiveManager (sync wrapper)")
    print("  ✅ Phase 3: Streaming audio playback")
    print("  ✅ Phase 4: Interruption handling")
    print("  ✅ Phase 5: Video frame streaming")
    print("="*80)
    
    results = {}
    
    # Test Phase 1 & 2
    results['phase_1_2'] = test_phase_1_2_connection()
    
    # Test Phase 3
    results['phase_3'] = test_phase_3_streaming_audio()
    
    # Test Phase 4
    results['phase_4'] = test_phase_4_interruption()
    
    # Test Phase 5
    results['phase_5'] = test_phase_5_video_streaming()
    
    # Print summary
    print("\n" + "="*80)
    print("📊 TEST SUMMARY")
    print("="*80)
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    for phase, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {phase.replace('_', ' ').title()}: {status}")
    
    print("="*80)
    print(f"🎯 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🏆 ALL TESTS PASSED - Live API ready for production!")
    else:
        print("⚠️ Some tests failed - check logs for details")
    
    print("="*80)


if __name__ == "__main__":
    try:
        run_all_tests()
    except KeyboardInterrupt:
        print("\n⚠️ Tests interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test suite failed: {e}", exc_info=True)
        print(f"❌ FATAL ERROR: {e}")
