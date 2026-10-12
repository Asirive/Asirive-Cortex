"""
Manual HRTF + IMU Head Tracking Test

Places a virtual sound source in 3D space. As you turn your head,
the BNO055 IMU tracks your rotation and the binaural engine shifts
the audio between your ears — just like a real sound in the room.

Controls (single keypress, no Enter needed):
    n       = next position
    p       = previous position
    r       = reset reference heading (re-center)
    s       = toggle between chirp / tone / melody sound
    m       = toggle moving source mode (orbits around you)
    +/-     = volume up/down
    q       = quit

Usage (on RPi5):
    cd /home/cortex/ProjectCortex
    source venv/bin/activate
    python tests/test_hrtf_imu.py
    python tests/test_hrtf_imu.py --gain 0.6

Author: Haziq (@IRSPlays)
Date: March 23, 2026
"""

import sys
import os
import time
import argparse
import threading
import select
import logging
import importlib.util
from pathlib import Path

# ─── Direct imports to avoid triggering rpi5/__init__.py ────────
# This prevents the full layer import chain (which loads OpenAL, YOLO, etc.)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
_rpi5_dir = PROJECT_ROOT / "rpi5"

def _direct_import(module_name: str, file_path: Path):
    """Import a module directly from file path without package chain."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hrtf_imu")

# Import binaural engine directly (no OpenAL, no full rpi5 chain)
_be = _direct_import(
    "binaural_engine",
    _rpi5_dir / "layer3_guide" / "spatial_audio" / "binaural_engine.py",
)
BinauralEngine = _be.BinauralEngine

# Import IMU handler directly
sys.path.insert(0, str(_rpi5_dir))

# ─── Positions ──────────────────────────────────────────────────
POSITIONS = [
    ("FRONT",         0,    0),
    ("FRONT-RIGHT",   45,   0),
    ("RIGHT",         90,   0),
    ("BEHIND-RIGHT",  135,  0),
    ("BEHIND",        180,  0),
    ("BEHIND-LEFT",  -135,  0),
    ("LEFT",         -90,   0),
    ("FRONT-LEFT",   -45,   0),
]

SOUNDS = ["tone", "chirp", "melody"]


def normalize_angle(a: float) -> float:
    while a > 180:
        a -= 360
    while a < -180:
        a += 360
    return a


def direction_label(az: float) -> str:
    az = normalize_angle(az)
    if abs(az) < 22.5:
        return "FRONT"
    elif abs(az) > 157.5:
        return "BEHIND"
    elif 22.5 <= az < 67.5:
        return "FRONT-R"
    elif 67.5 <= az < 112.5:
        return "RIGHT"
    elif 112.5 <= az < 157.5:
        return "BEHIND-R"
    elif -67.5 < az <= -22.5:
        return "FRONT-L"
    elif -112.5 < az <= -67.5:
        return "LEFT"
    else:
        return "BEHIND-L"


# ─── Single keypress reader (Linux) ────────────────────────────
class KeyReader:
    """Non-blocking single keypress reader using termios (no Enter needed)."""

    def __init__(self):
        self._old_settings = None
        self._active = False

    def start(self):
        import termios, tty
        self._old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        self._active = True

    def stop(self):
        if self._old_settings:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
            self._active = False

    def get_key(self) -> str | None:
        """Return a key if one is available, else None (non-blocking)."""
        if not self._active:
            return None
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None


def main():
    parser = argparse.ArgumentParser(description="Manual HRTF + IMU Test")
    parser.add_argument("--gain", type=float, default=0.5, help="Audio gain")
    parser.add_argument("--freq", type=float, default=500, help="Tone frequency")
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║       MANUAL HRTF + IMU HEAD TRACKING TEST              ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  Sound is placed in 3D space.                           ║")
    print("║  Turn your head → sound shifts between ears.            ║")
    print("║                                                         ║")
    print("║  Keys (no Enter needed):                                ║")
    print("║    n = next pos    p = prev pos    r = reset heading    ║")
    print("║    s = change sound    m = orbit mode    q = quit       ║")
    print("║    + = louder      - = quieter                          ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # ─── Init IMU ───────────────────────────────────────────────
    try:
        from hardware.imu_handler import IMUHandler
    except ImportError:
        print("  ERROR: IMUHandler not available!")
        print("  This test must run on RPi5 with BNO055 connected.")
        return

    imu = IMUHandler(i2c_address=0x29, poll_hz=50, mounting="right_temple_down")
    print("  Starting IMU...")
    if not imu.start():
        print("  ERROR: Failed to start IMU! Check I2C connection.")
        return
    time.sleep(1.0)

    ref_heading = None
    reading = imu.get_reading()
    if reading:
        ref_heading = reading.heading
        print(f"  ✅ IMU ready — ref heading: {ref_heading:.1f}°")
        print(f"     Cal: S{reading.cal_system} G{reading.cal_gyro} A{reading.cal_accel} M{reading.cal_mag}")
    else:
        print("  ⚠️  No IMU reading, using 0° as reference")
        ref_heading = 0.0

    # ─── Init Audio ─────────────────────────────────────────────
    gain = args.gain
    engine = BinauralEngine(sr=48000, gain=gain)
    if not engine.start():
        print("  ERROR: Failed to start BinauralEngine!")
        imu.stop()
        return

    # ─── State ──────────────────────────────────────────────────
    pos_idx = 0
    source_az = float(POSITIONS[pos_idx][1])
    source_el = float(POSITIONS[pos_idx][2])
    sound_idx = 0  # start with "tone"
    moving_mode = False
    moving_angle = 0.0

    engine.start_continuous(
        azimuth_deg=source_az,
        elevation_deg=source_el,
        freq=args.freq,
        loop_duration_s=2.0,
    )

    print()
    print(f"  🔊 {POSITIONS[pos_idx][0]} (az={source_az:+.0f}°)  🎵 {SOUNDS[sound_idx]}  🔈 gain={gain:.2f}")
    print()
    print("  Turn your head now!")
    print("  ─────────────────────────────────────────────────────────")
    print()

    # ─── Keyboard ───────────────────────────────────────────────
    keys = KeyReader()
    keys.start()

    last_print = 0.0
    running = True

    try:
        while running:
            reading = imu.get_reading()

            if reading and ref_heading is not None:
                delta = normalize_angle(reading.heading - ref_heading)

                if moving_mode:
                    moving_angle += 1.2
                    if moving_angle > 180:
                        moving_angle -= 360
                    source_az = moving_angle

                effective_az = normalize_angle(source_az - delta)
                engine.update_position(effective_az, source_el)

                now = time.time()
                if now - last_print > 0.25:
                    heard_dir = direction_label(effective_az)
                    src_name = POSITIONS[pos_idx][0] if not moving_mode else f"ORB{source_az:+.0f}"

                    bar_pos = int((effective_az + 180) / 360 * 40)
                    bar_pos = max(0, min(39, bar_pos))
                    bar = list("─" * 40)
                    bar[20] = "┼"  # center marker (front)
                    bar[bar_pos] = "◆"
                    bar_str = "".join(bar)

                    print(
                        f"\r  hd={delta:+5.0f}°  "
                        f"{src_name:10s}  "
                        f"ear={effective_az:+5.0f}° [{heard_dir:8s}]  "
                        f"L{bar_str}R  "
                        f"S{reading.cal_system} ",
                        end="", flush=True,
                    )
                    last_print = now

            # ─── Handle keys ────────────────────────────────────
            key = keys.get_key()
            if key:
                if key == "n" or key == " ":
                    moving_mode = False
                    pos_idx = (pos_idx + 1) % len(POSITIONS)
                    source_az = float(POSITIONS[pos_idx][1])
                    source_el = float(POSITIONS[pos_idx][2])
                    print(f"\n  🔊 → {POSITIONS[pos_idx][0]} (az={source_az:+.0f}°)")

                elif key == "p":
                    moving_mode = False
                    pos_idx = (pos_idx - 1) % len(POSITIONS)
                    source_az = float(POSITIONS[pos_idx][1])
                    source_el = float(POSITIONS[pos_idx][2])
                    print(f"\n  🔊 → {POSITIONS[pos_idx][0]} (az={source_az:+.0f}°)")

                elif key == "r":
                    if reading:
                        ref_heading = reading.heading
                        print(f"\n  🧭 Reference RESET to {ref_heading:.1f}°")

                elif key == "s":
                    engine.stop_continuous()
                    time.sleep(0.05)
                    sound_idx = (sound_idx + 1) % len(SOUNDS)
                    freq_map = {"chirp": 600, "tone": args.freq, "melody": 440}
                    engine.start_continuous(
                        azimuth_deg=effective_az if reading else source_az,
                        elevation_deg=source_el,
                        freq=freq_map[SOUNDS[sound_idx]],
                        loop_duration_s=2.0,
                    )
                    print(f"\n  🎵 → {SOUNDS[sound_idx]}")

                elif key == "m":
                    moving_mode = not moving_mode
                    if moving_mode:
                        moving_angle = 0.0
                        print(f"\n  🔄 ORBIT mode ON")
                    else:
                        source_az = float(POSITIONS[pos_idx][1])
                        print(f"\n  🔄 FIXED → {POSITIONS[pos_idx][0]}")

                elif key == "+" or key == "=":
                    gain = min(1.0, gain + 0.1)
                    engine._gain = gain
                    print(f"\n  🔈 gain={gain:.1f}")

                elif key == "-":
                    gain = max(0.1, gain - 0.1)
                    engine._gain = gain
                    print(f"\n  🔈 gain={gain:.1f}")

                elif key == "q":
                    running = False

            time.sleep(0.02)

    except KeyboardInterrupt:
        pass

    print("\n\n  Stopping...")
    keys.stop()
    engine.stop_continuous()
    engine.stop()
    imu.stop()
    print("  Done! 👋")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
