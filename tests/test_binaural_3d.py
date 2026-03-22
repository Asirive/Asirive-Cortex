"""
Binaural 3D Audio Test — Uses manual HRTF, NO OpenAL.

This test demonstrates real 3D audio using the BinauralEngine.
It applies ITD (time delay), ILD (level difference), and head-shadow
filtering to produce binaural stereo that's GUARANTEED to spatialize.

Two modes:
  1. STATIC TEST: Plays pings at 8 compass positions (no IMU needed)
  2. IMU TEST: Continuous tone + head tracking (requires BNO055)

Usage (on RPi5, with earphones):
    cd /home/cortex/ProjectCortex
    source venv/bin/activate
    python tests/test_binaural_3d.py           # static test
    python tests/test_binaural_3d.py --imu     # with head tracking

Author: Haziq (@IRSPlays)
Date: March 23, 2026
"""

import sys
import time
import argparse
import threading
import logging
from pathlib import Path

# Path setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "rpi5"))
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("binaural_test")

from rpi5.layer3_guide.spatial_audio.binaural_engine import (
    BinauralEngine,
    generate_chirp,
    generate_melody_ping,
    generate_continuous_tone,
    render_binaural,
    compute_azimuth_elevation,
)

# Test positions: (name, azimuth_deg, elevation_deg)
# 0° = front, +90° = right, -90° = left, 180° = behind
TEST_POSITIONS = [
    ("FRONT",        0,    0),
    ("FRONT-RIGHT",  45,   0),
    ("RIGHT",        90,   0),
    ("BEHIND-RIGHT", 135,  0),
    ("BEHIND",       180,  0),
    ("BEHIND-LEFT",  -135, 0),
    ("LEFT",         -90,  0),
    ("FRONT-LEFT",   -45,  0),
]


def static_test(engine: BinauralEngine):
    """
    Play pings at 8 compass positions.
    No IMU needed — just listen with earphones.
    """
    print()
    print("=" * 60)
    print("  BINAURAL 3D AUDIO — STATIC POSITION TEST")
    print("  (Manual HRTF — NO OpenAL)")
    print("=" * 60)
    print()
    print("  PUT ON YOUR EARPHONES!")
    print()
    print("  You'll hear a chirp ping at 8 positions around you.")
    print("  Each position plays twice with a 1s gap.")
    print()
    input("  Press Enter to start...")
    print()

    for name, az, el in TEST_POSITIONS:
        print(f"  >>> {name:15s} (azimuth={az:+4d}°)")

        # Play twice so user can focus
        engine.play_at(azimuth_deg=az, elevation_deg=el,
                       sound="melody", duration_s=0.5)
        time.sleep(0.3)
        engine.play_at(azimuth_deg=az, elevation_deg=el,
                       sound="melody", duration_s=0.5)
        time.sleep(1.0)

    print()
    print("=" * 60)
    print("  TEST COMPLETE — Did you hear the sound move around?")
    print("=" * 60)
    print()
    print("  Expected perception:")
    print("    FRONT:       centered, both ears equal")
    print("    FRONT-RIGHT: slightly louder in right ear")
    print("    RIGHT:       clearly louder/earlier in right ear")
    print("    BEHIND:      centered but slightly duller")
    print("    LEFT:        clearly louder/earlier in left ear")
    print()
    print("  If LEFT/RIGHT sounded the same → your headphones")
    print("  are outputting MONO. Run test_stereo_raw.py first!")
    print()


def continuous_sweep_test(engine: BinauralEngine):
    """
    Sweep a continuous tone around the listener (no IMU).
    Sound should audibly rotate around your head.
    """
    print()
    print("=" * 60)
    print("  BINAURAL 3D AUDIO — CONTINUOUS SWEEP")
    print("=" * 60)
    print()
    print("  A continuous tone will sweep 360° around your head.")
    print("  PUT ON YOUR EARPHONES!")
    print()
    input("  Press Enter to start...")
    print()

    engine.start_continuous(azimuth_deg=0, elevation_deg=0,
                            freq=500, loop_duration_s=2.0)

    # Sweep 360° over 8 seconds
    duration = 8.0
    steps = 200
    for i in range(steps):
        az = -180 + (360 * i / steps)
        engine.update_position(az, 0)
        label = "FRONT" if abs(az) < 10 else ("RIGHT" if 80 < az < 100 else
                ("BEHIND" if abs(az) > 170 else ("LEFT" if -100 < az < -80 else "")))
        if label:
            print(f"  >>> {label:10s}  (az={az:+6.1f}°)")
        time.sleep(duration / steps)

    engine.stop_continuous()
    print()
    print("  Sweep complete! Did the sound rotate around your head?")
    print()


def imu_test(engine: BinauralEngine):
    """
    Continuous tone at a fixed position + IMU head tracking.
    When you turn your head, the sound should shift between ears.
    """
    print()
    print("=" * 60)
    print("  BINAURAL 3D AUDIO — IMU HEAD TRACKING TEST")
    print("=" * 60)
    print()
    print("  A tone plays at a fixed point in space (FRONT).")
    print("  Turn your head — the sound should shift between ears.")
    print()
    print("  Controls:")
    print("    Enter     = cycle source position")
    print("    r + Enter = reset reference heading")
    print("    Ctrl+C    = quit")
    print()

    # Start IMU
    try:
        from rpi5.hardware.imu_handler import IMUHandler
    except ImportError:
        print("  ERROR: IMUHandler not available (not on RPi5?)")
        return

    imu = IMUHandler(i2c_address=0x29, poll_hz=50, mounting="right_temple_down")
    if not imu.start():
        print("  ERROR: Failed to start IMU!")
        return

    print("  IMU started, waiting for calibration...")
    time.sleep(1.0)

    # Capture reference heading
    ref_heading = None
    reading = imu.get_reading()
    if reading:
        ref_heading = reading.heading
        print(f"  Reference heading: {ref_heading:.1f}°")

    # Start continuous tone at FRONT (0°)
    pos_idx = 0
    source_az = TEST_POSITIONS[pos_idx][1]
    source_el = TEST_POSITIONS[pos_idx][2]

    engine.start_continuous(azimuth_deg=source_az, elevation_deg=source_el,
                            freq=500, loop_duration_s=2.0)

    print(f"\n  >>> Source at: {TEST_POSITIONS[pos_idx][0]}")
    print(f"  >>> Turn your head — sound stays fixed in space")
    print()

    # Non-blocking input
    user_input = [None]
    input_ready = threading.Event()

    def _input_thread():
        while True:
            try:
                line = input()
                user_input[0] = line.strip().lower()
                input_ready.set()
            except EOFError:
                break

    t = threading.Thread(target=_input_thread, daemon=True)
    t.start()

    last_print = 0
    try:
        while True:
            reading = imu.get_reading()
            if reading and ref_heading is not None:
                # Compute head rotation relative to reference
                delta = reading.heading - ref_heading
                # Normalize to [-180, 180]
                while delta > 180:
                    delta -= 360
                while delta < -180:
                    delta += 360

                # Source azimuth in head-relative frame
                # If head turns right (+delta), sound appears to move left
                effective_az = source_az - delta

                engine.update_position(effective_az, source_el)

                now = time.time()
                if now - last_print > 0.3:
                    print(
                        f"\r  hdg={reading.heading:6.1f}°  "
                        f"Δ={delta:+6.1f}°  "
                        f"eff_az={effective_az:+6.1f}°  "
                        f"src={TEST_POSITIONS[pos_idx][0]:12s}  "
                        f"cal:S{reading.cal_system}G{reading.cal_gyro}"
                        f"A{reading.cal_accel}M{reading.cal_mag}",
                        end="", flush=True,
                    )
                    last_print = now

            # Check input
            if input_ready.is_set():
                input_ready.clear()
                cmd = user_input[0]
                if cmd == "" or cmd is None:
                    pos_idx = (pos_idx + 1) % len(TEST_POSITIONS)
                    source_az = TEST_POSITIONS[pos_idx][1]
                    source_el = TEST_POSITIONS[pos_idx][2]
                    engine.update_position(source_az - (reading.heading - ref_heading if reading and ref_heading else 0), source_el)
                    print(f"\n  >>> Source moved to: {TEST_POSITIONS[pos_idx][0]} (az={source_az}°)")
                elif cmd == "r":
                    if reading:
                        ref_heading = reading.heading
                        print(f"\n  >>> Reference RESET to {ref_heading:.1f}°")

            time.sleep(0.02)  # 50 Hz

    except KeyboardInterrupt:
        print("\n\n  Stopping...")

    engine.stop_continuous()
    imu.stop()
    print("  Test complete.")


def main():
    parser = argparse.ArgumentParser(description="Binaural 3D Audio Test")
    parser.add_argument("--imu", action="store_true",
                        help="Run with IMU head tracking")
    parser.add_argument("--sweep", action="store_true",
                        help="Run continuous 360° sweep test")
    parser.add_argument("--gain", type=float, default=1.0,
                        help="Output gain multiplier (default: 1.0)")
    args = parser.parse_args()

    engine = BinauralEngine(gain=args.gain)
    if not engine.start():
        print("Failed to start BinauralEngine! Install: pip install sounddevice")
        sys.exit(1)

    try:
        if args.imu:
            imu_test(engine)
        elif args.sweep:
            continuous_sweep_test(engine)
        else:
            static_test(engine)
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
