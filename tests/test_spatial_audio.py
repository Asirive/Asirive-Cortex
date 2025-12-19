#!/usr/bin/env python3
"""
Project-Cortex v2.0 - Spatial Audio Positioning Test

🎧 PUT ON HEADPHONES BEFORE RUNNING THIS TEST!

This test verifies that HRTF spatial audio is working correctly by:
1. Playing a sound that pans from LEFT → CENTER → RIGHT
2. Testing object detection at different screen positions
3. Testing distance-based ping rates (closer = faster pings)
4. Testing emergency alerts for close objects

Author: Haziq (@IRSPlays)
"""

import sys
import os
import time
import logging

# Enable INFO logging for test output
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def main():
    print("=" * 70)
    print("🎧 PROJECT-CORTEX SPATIAL AUDIO POSITIONING TEST 🎧")
    print("=" * 70)
    print()
    print("⚠️  PUT ON HEADPHONES BEFORE CONTINUING!")
    print("⚠️  Speakers will NOT work for spatial audio perception.")
    print()
    
    input("Press ENTER when you have headphones on...")
    print()
    
    try:
        from layer3_guide.spatial_audio.manager import SpatialAudioManager, OPENAL_AVAILABLE, Detection
        
        if not OPENAL_AVAILABLE:
            print("❌ ERROR: PyOpenAL is not installed!")
            print("   Install with: pip install PyOpenAL")
            return
        
        # Create manager with default comfort settings
        print("Initializing Spatial Audio Manager...")
        audio = SpatialAudioManager(
            frame_width=1920,
            frame_height=1080,
            max_sources=8
        )
        
        print(f"   OpenAL Available: {OPENAL_AVAILABLE}")
        print(f"   Spatial Width: {audio.position_calc.spatial_width_meters}m")
        print(f"   Master Volume: {audio.comfort.master_volume}")
        print()
        
        if audio.start():
            print("✅ Audio system started successfully")
            print()
            
            # Run the built-in spatial test
            print("-" * 70)
            print("TEST 1: Sound panning from LEFT → CENTER → RIGHT")
            print("-" * 70)
            print("You should clearly hear the sound move across your head.")
            print()
            
            audio.test_spatial_positioning(duration_seconds=8.0)
            
            print()
            print("-" * 70)
            print("TEST 2: Distance-based ping rate (CLOSER = FASTER PINGS)")
            print("-" * 70)
            print("The ping rate should increase as objects get closer!")
            print()
            
            # Test far object (slow pings)
            print("🔊 FAR OBJECT (slow pings - ~2 seconds apart)...")
            far_detection = Detection(
                class_name="person",
                confidence=0.95,
                bbox=(860, 200, 960, 400),  # Small bbox = far
                object_id="test_far"
            )
            for _ in range(4):  # 4 update cycles
                audio.update_detections([far_detection])
                time.sleep(0.5)
            audio.update_detections([])  # Clear
            time.sleep(1)
            
            # Test mid object (moderate pings)
            print("🔊 MID-RANGE OBJECT (moderate pings - ~1 second apart)...")
            mid_detection = Detection(
                class_name="person",
                confidence=0.95,
                bbox=(760, 200, 1160, 700),  # Medium bbox = mid-range
                object_id="test_mid"
            )
            for _ in range(6):
                audio.update_detections([mid_detection])
                time.sleep(0.3)
            audio.update_detections([])
            time.sleep(1)
            
            # Test close object (fast pings)
            print("🔊 CLOSE OBJECT (fast pings - ~0.3 seconds apart)...")
            close_detection = Detection(
                class_name="person",
                confidence=0.95,
                bbox=(560, 100, 1360, 900),  # Large bbox = close
                object_id="test_close"
            )
            for _ in range(12):
                audio.update_detections([close_detection])
                time.sleep(0.15)
            audio.update_detections([])
            time.sleep(1)
            
            # Test very close object (rapid pings + emergency alert)
            print("🔊 VERY CLOSE OBJECT (rapid pings + EMERGENCY ALERT!)...")
            very_close_detection = Detection(
                class_name="person",
                confidence=0.95,
                bbox=(200, 50, 1720, 1000),  # Huge bbox = very close
                object_id="test_emergency"
            )
            for _ in range(20):
                audio.update_detections([very_close_detection])
                time.sleep(0.1)
            audio.update_detections([])
            
            print()
            print("-" * 70)
            print("TEST 3: LEFT, CENTER, RIGHT positions")
            print("-" * 70)
            
            # Test LEFT
            print("\n🔊 LEFT side of screen...")
            left_detection = Detection(
                class_name="chair",
                confidence=0.95,
                bbox=(50, 200, 350, 700),  # Far left
                object_id="test_left"
            )
            for _ in range(8):
                audio.update_detections([left_detection])
                time.sleep(0.25)
            audio.update_detections([])
            time.sleep(0.5)
            
            # Test CENTER
            print("🔊 CENTER of screen...")
            center_detection = Detection(
                class_name="chair",
                confidence=0.95,
                bbox=(860, 200, 1060, 700),
                object_id="test_center"
            )
            for _ in range(8):
                audio.update_detections([center_detection])
                time.sleep(0.25)
            audio.update_detections([])
            time.sleep(0.5)
            
            # Test RIGHT
            print("🔊 RIGHT side of screen...")
            right_detection = Detection(
                class_name="chair",
                confidence=0.95,
                bbox=(1570, 200, 1870, 700),  # Far right
                object_id="test_right"
            )
            for _ in range(8):
                audio.update_detections([right_detection])
                time.sleep(0.25)
            audio.update_detections([])
            
            audio.stop()
            
            print()
            print("=" * 70)
            print("TEST COMPLETE")
            print("=" * 70)
            print()
            print("📋 Results checklist:")
            print("   [ ] TEST 1: Could you hear sound move LEFT → RIGHT?")
            print("   [ ] TEST 2: Did ping rate INCREASE as objects got CLOSER?")
            print("   [ ] TEST 2: Did you hear the EMERGENCY alert (rapid beeping)?")
            print("   [ ] TEST 3: Could you distinguish LEFT, CENTER, RIGHT?")
            print()
            print("If you answered NO to any:")
            print("   1. Make sure you're using stereo headphones")
            print("   2. Run: python utils/configure_hrtf.py")
            print("   3. Check %APPDATA%\\alsoft.ini has 'hrtf = true'")
            print()
            
        else:
            print("❌ Failed to start audio system")
            
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure you're running from the project root.")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
