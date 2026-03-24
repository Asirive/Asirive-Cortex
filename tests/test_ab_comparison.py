"""
A/B Comparison: Manual Binaural Engine vs OpenAL HRTF

Plays the same positions with both engines so you can compare
which gives better 3D audio directionality.

Usage (on RPi5):
    cd /home/cortex/ProjectCortex
    source venv/bin/activate
    python tests/test_ab_comparison.py

Author: Haziq (@IRSPlays)
Date: March 23, 2026
"""

import sys
import time
import math
import wave
import struct
import tempfile
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
logger = logging.getLogger("ab_test")

# ─── Import both engines ────────────────────────────────────────
from rpi5.layer3_guide.spatial_audio.binaural_engine import (
    BinauralEngine,
    generate_chirp,
)

# OpenAL imports
OPENAL_OK = False
try:
    from openal import oalInit, oalQuit, oalGetListener
    from openal import Source, Buffer
    OPENAL_OK = True
except ImportError:
    logger.warning("PyOpenAL not available — OpenAL test will be skipped")


# ─── Helpers ────────────────────────────────────────────────────
SAMPLE_RATE = 44100


def make_openal_chirp_wav(duration_s: float = 0.4) -> str:
    """Generate a chirp WAV file for OpenAL to load."""
    n = int(SAMPLE_RATE * duration_s)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = 400 + 1200 * (t / duration_s)  # 400→1600 Hz sweep
        # Add harmonics for better HRTF localization
        val = 0.5 * math.sin(2 * math.pi * freq * t)
        val += 0.25 * math.sin(2 * math.pi * freq * 2 * t)
        val += 0.12 * math.sin(2 * math.pi * freq * 3 * t)
        # Envelope
        attack = min(1.0, t * 20)
        release = min(1.0, (duration_s - t) * 20)
        val *= attack * release * 0.7
        samples.append(int(val * 32767))

    path = tempfile.mktemp(suffix=".wav")
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)  # MONO — OpenAL spatializes mono sources
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def azimuth_to_openal_xyz(az_deg: float, distance: float = 2.0):
    """
    Convert azimuth to OpenAL position.
    OpenAL: -Z = forward, +X = right, +Y = up
    Our convention: 0° = front, +90° = right, -90° = left
    """
    az_rad = math.radians(az_deg)
    x = distance * math.sin(az_rad)    # +X = right
    z = -distance * math.cos(az_rad)   # -Z = forward
    return (x, 0.0, z)


# ─── Test positions ─────────────────────────────────────────────
POSITIONS = [
    ("FRONT",    0),
    ("RIGHT",   90),
    ("BEHIND", 180),
    ("LEFT",   -90),
    ("FRONT-RIGHT",  45),
    ("FRONT-LEFT",  -45),
]


def test_manual_binaural():
    """Test using our manual HRTF engine."""
    print()
    print("=" * 60)
    print("  ENGINE A: Manual Binaural (ITD + ILD + Head Shadow)")
    print("=" * 60)
    print()

    engine = BinauralEngine(sr=48000, gain=0.5)
    if not engine.start():
        print("  FAILED to start BinauralEngine!")
        return

    for name, az in POSITIONS:
        print(f"  >>> {name:15s} (az={az:+4d}°)")
        engine.play_at(az, 0, sound="chirp", duration_s=0.4)
        time.sleep(0.6)

    # Quick sweep
    print()
    print("  360° sweep...")
    engine.start_continuous(azimuth_deg=0, elevation_deg=0,
                            freq=500, loop_duration_s=2.0)
    steps = 150
    for i in range(steps):
        az = -180 + (360 * i / steps)
        engine.update_position(az, 0)
        time.sleep(6.0 / steps)
    engine.stop_continuous()

    engine.stop()
    print("  Done!")
    print()


def test_openal_hrtf():
    """Test using OpenAL-Soft HRTF."""
    if not OPENAL_OK:
        print("\n  OpenAL not available — skipping!\n")
        return

    print()
    print("=" * 60)
    print("  ENGINE B: OpenAL-Soft HRTF")
    print("=" * 60)
    print()

    try:
        oalInit()
    except Exception as e:
        print(f"  FAILED to init OpenAL: {e}")
        return

    # Set listener
    listener = oalGetListener()
    listener.set_position((0, 0, 0))
    listener.set_orientation((0, 0, -1, 0, 1, 0))

    # Create chirp WAV
    wav_path = make_openal_chirp_wav(0.4)

    for name, az in POSITIONS:
        pos = azimuth_to_openal_xyz(az, distance=2.0)
        print(f"  >>> {name:15s} (az={az:+4d}°)  pos={pos[0]:+.1f},{pos[1]:+.1f},{pos[2]:+.1f}")

        try:
            from openal import WaveFile
            buf = Buffer(WaveFile(wav_path))
            src = Source(buf)
            src.set_position(pos)
            src.set_gain(0.7)
            src.set_source_relative(False)
            src.set_rolloff_factor(0.0)  # No distance attenuation
            src.set_reference_distance(1.0)
            src.set_max_distance(100.0)
            src.play()
            time.sleep(0.5)
            src.stop()
            time.sleep(0.5)
        except Exception as e:
            print(f"    Error: {e}")

    # Quick sweep with OpenAL
    print()
    print("  360° sweep...")
    try:
        from openal import WaveFile
        # Use a longer tone for sweep
        long_wav = make_openal_chirp_wav(8.0)
        buf = Buffer(WaveFile(long_wav))
        src = Source(buf)
        src.set_gain(0.5)
        src.set_source_relative(False)
        src.set_rolloff_factor(0.0)
        src.set_looping(True)
        src.set_position(azimuth_to_openal_xyz(0))
        src.play()

        steps = 150
        for i in range(steps):
            az = -180 + (360 * i / steps)
            pos = azimuth_to_openal_xyz(az, distance=2.0)
            src.set_position(pos)
            time.sleep(6.0 / steps)

        src.stop()
    except Exception as e:
        print(f"    Sweep error: {e}")

    try:
        oalQuit()
    except Exception:
        pass

    # Clean up temp files
    import os
    try:
        os.unlink(wav_path)
    except Exception:
        pass

    print("  Done!")
    print()


def main():
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║     A/B COMPARISON: Manual Binaural vs OpenAL HRTF     ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  Each engine plays the SAME positions.                  ║")
    print("║  Listen and compare which gives better directionality.  ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print("  Positions: FRONT, RIGHT, BEHIND, LEFT, FRONT-RIGHT, FRONT-LEFT")
    print("  + 360° sweep with each engine")
    print()
    input("  Press ENTER to start Engine A (Manual Binaural)...")
    test_manual_binaural()

    input("  Press ENTER to start Engine B (OpenAL HRTF)...")
    test_openal_hrtf()

    print()
    print("=" * 60)
    print("  COMPARISON COMPLETE!")
    print("=" * 60)
    print()
    print("  Which engine gave better directionality?")
    print("    A = Manual Binaural (ITD + ILD + Head Shadow)")
    print("    B = OpenAL-Soft HRTF")
    print()


if __name__ == "__main__":
    main()
