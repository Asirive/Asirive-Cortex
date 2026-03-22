"""
Interactive HRTF + IMU Head-Tracking Test

Plays a CONTINUOUS broadband noise at a fixed 3D position while tracking
head orientation via the BNO055 IMU.

KEY INSIGHT: Pure tones (sine waves) are almost impossible to localise via
HRTF because HRTF works through *frequency-dependent* filtering.  Broadband
noise (pink noise) has energy across all frequencies, so the ear's direction-
dependent spectral filtering is clearly audible.

When you turn your head, the noise should clearly shift between ears.
Press Enter to cycle the source around 8 compass positions.

Usage (on RPi5, with earphones):
    cd /home/cortex/ProjectCortex
    source venv/bin/activate
    python tests/test_hrtf_imu.py

Controls: Enter = next position, r = reset reference, Ctrl+C = quit

Author: Haziq (@IRSPlays)
"""

import sys
import os
import struct
import time
import math
import logging
import tempfile
import threading
import numpy as np
from pathlib import Path

# ── Path setup ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "rpi5"))
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hrtf_test")

# ── OpenAL + project imports ──
from openal import oalInit, oalQuit, oalGetListener, oalGetDevice
from openal import Listener, Source, Buffer, WaveFile
from openal import alDistanceModel, AL_INVERSE_DISTANCE_CLAMPED
from rpi5.layer3_guide.spatial_audio.manager import SpatialAudioManager
from rpi5.layer3_guide.spatial_audio.position_calculator import Position3D
from rpi5.hardware.imu_handler import IMUHandler


# ═══════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════
IMU_ADDRESS = 0x29
IMU_MOUNTING = "right_temple_down"
SAMPLE_RATE = 44100

# Positions at distance 1.0 — closer = louder, less distance attenuation
# x: left(-)/right(+), y: up/down, z: front(-)/behind(+)
TEST_POSITIONS = {
    "FRONT":        Position3D(x= 0.0, y=0.0, z=-1.0, distance_meters=1.0),
    "FRONT-LEFT":   Position3D(x=-0.7, y=0.0, z=-0.7, distance_meters=1.0),
    "LEFT":         Position3D(x=-1.0, y=0.0, z= 0.0, distance_meters=1.0),
    "BEHIND-LEFT":  Position3D(x=-0.7, y=0.0, z= 0.7, distance_meters=1.0),
    "BEHIND":       Position3D(x= 0.0, y=0.0, z= 1.0, distance_meters=1.0),
    "BEHIND-RIGHT": Position3D(x= 0.7, y=0.0, z= 0.7, distance_meters=1.0),
    "RIGHT":        Position3D(x= 1.0, y=0.0, z= 0.0, distance_meters=1.0),
    "FRONT-RIGHT":  Position3D(x= 0.7, y=0.0, z=-0.7, distance_meters=1.0),
}

POSITION_NAMES = list(TEST_POSITIONS.keys())


# ═══════════════════════════════════════════════════════════
# Sound generation — broadband pink noise (HRTF-friendly)
# ═══════════════════════════════════════════════════════════

def _pink_noise(n_samples: int) -> np.ndarray:
    """Generate pink noise (1/f spectrum) via Voss-McCartney algorithm."""
    # Use 16 octaves of random generators
    n_rows = 16
    total = n_samples
    array = np.empty((total, n_rows))
    array[:] = np.random.randn(1, n_rows)

    # Each row updates at a different rate (powers of 2)
    for i in range(n_rows):
        step = 1 << i
        indices = np.arange(0, total, step)
        array[indices, i] = np.random.randn(len(indices))

    result = array.sum(axis=1)
    result /= np.max(np.abs(result))  # normalise to [-1, 1]
    return result


def generate_broadband_loop_wav(duration_s: float = 4.0) -> str:
    """
    Generate a continuous pink-noise loop for HRTF testing.

    Pink noise has energy across all audible frequencies, making it
    dramatically easier to spatially localise via HRTF compared to a
    pure tone.  A gentle amplitude modulation (2 Hz pulse) is mixed in
    so you can *hear* that the sound is alive / moving.

    Returns path to temporary WAV file.
    """
    n = int(SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n, endpoint=False)

    # Pink noise base
    noise = _pink_noise(n) * 0.7

    # Gentle 2 Hz AM pulse so it doesn't feel like dead static
    am = 0.7 + 0.3 * np.sin(2 * np.pi * 2.0 * t)
    wave = noise * am

    # Crossfade edges for seamless loop (100 ms)
    xf = int(SAMPLE_RATE * 0.10)
    fade = np.linspace(0, 1, xf)
    wave[:xf] = wave[:xf] * fade + wave[-xf:] * (1 - fade)
    wave[-xf:] = wave[:xf]

    # Boost overall amplitude
    wave *= 0.9 / (np.max(np.abs(wave)) + 1e-9)

    # Convert to 16-bit PCM WAV
    pcm = (np.clip(wave, -1.0, 1.0) * 32767).astype(np.int16)
    data_bytes = pcm.tobytes()

    header = b"RIFF"
    header += struct.pack("<I", 36 + len(data_bytes))
    header += b"WAVE"
    header += b"fmt "
    header += struct.pack("<IHHIIHH", 16, 1, 1, SAMPLE_RATE,
                          SAMPLE_RATE * 2, 2, 16)
    header += b"data"
    header += struct.pack("<I", len(data_bytes))

    tmp = os.path.join(tempfile.gettempdir(), "hrtf_test_noise.wav")
    with open(tmp, "wb") as f:
        f.write(header + data_bytes)

    logger.info(f"Generated {duration_s}s pink-noise loop → {tmp}")
    return tmp


def main():
    print()
    print("=" * 60)
    print("  HRTF + IMU Head-Tracking Test  (broadband noise)")
    print("=" * 60)
    print()
    print("  A continuous pink-noise plays at a fixed 3D position.")
    print("  Turn your head — the noise should clearly shift")
    print("  between your left and right ears.")
    print()
    print("  PUT ON YOUR EARPHONES before starting!")
    print()
    print("  Controls:")
    print("    Enter          = cycle to next position")
    print("    r + Enter      = reset head-tracking reference")
    print("    Ctrl+C         = quit")
    print()

    # ── Start IMU ──
    logger.info("Starting IMU...")
    imu = IMUHandler(
        i2c_address=IMU_ADDRESS,
        poll_hz=50,
        mounting=IMU_MOUNTING,
    )
    if not imu.start():
        logger.error("Failed to start IMU! Check I2C connection.")
        return
    logger.info("IMU started — waiting for first reading...")
    time.sleep(1.0)

    # ── Start Spatial Audio (for HRTF init + listener orientation) ──
    logger.info("Starting Spatial Audio Manager (HRTF)...")
    sa = SpatialAudioManager(enable_hrtf=True)
    if not sa.start():
        logger.error("Failed to start spatial audio!")
        imu.stop()
        return
    logger.info("Spatial audio ready.")

    # ── Generate broadband noise WAV ──
    logger.info("Generating broadband noise loop...")
    wav_path = generate_broadband_loop_wav(duration_s=4.0)

    # ── Load into OpenAL buffer + create looping source ──
    wave_file = WaveFile(wav_path)
    buf = Buffer(wave_file)
    source = Source(buf)
    source.set_looping(True)

    # --- Source spatial properties ---
    # World-space positioning, no distance rolloff so HRTF is the only cue
    source.set_source_relative(False)
    source.set_rolloff_factor(0.0)
    source.set_reference_distance(1.0)
    source.set_max_distance(50.0)

    # Position at first test location
    pos_idx = 0
    pos_name = POSITION_NAMES[pos_idx]
    pos = TEST_POSITIONS[pos_name]
    source.set_position(pos.as_tuple())

    # LOUD — max gain on source
    source.set_gain(3.0)
    source.play()
    logger.info(f"Playing broadband noise at: {pos_name}  {pos}")

    print()
    print(f"  >>> Sound at: {pos_name}")
    print(f"  >>> Turn your head — the sound should stay fixed in space")
    print()

    # ── Non-blocking input reader ──
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

    update_count = 0
    last_print = 0

    try:
        while True:
            # ── Update listener orientation from IMU ──
            reading = imu.get_reading()
            if reading:
                sa.set_listener_orientation(
                    yaw=reading.heading,
                    pitch=reading.pitch,
                )
                update_count += 1

                now = time.time()
                if now - last_print > 0.5:
                    delta = sa._listener_orientation[0] if hasattr(sa, '_listener_orientation') else 0
                    print(
                        f"\r  hdg={reading.heading:6.1f}°  "
                        f"Δ={delta:+6.1f}°  "
                        f"pitch={reading.pitch:+5.1f}°  "
                        f"cal:S{reading.cal_system}G{reading.cal_gyro}"
                        f"A{reading.cal_accel}M{reading.cal_mag}  "
                        f"pos={pos_name:12s}  "
                        f"[{update_count}]   ",
                        end="", flush=True,
                    )
                    last_print = now

            # ── Check for user input ──
            if input_ready.is_set():
                input_ready.clear()
                cmd = user_input[0]

                if cmd == "" or cmd == " ":
                    pos_idx = (pos_idx + 1) % len(POSITION_NAMES)
                    pos_name = POSITION_NAMES[pos_idx]
                    pos = TEST_POSITIONS[pos_name]
                    source.set_position(pos.as_tuple())
                    print(f"\n  >>> Sound moved to: {pos_name}  {pos}")

                elif cmd == "r":
                    sa.reset_reference_heading()
                    print(f"\n  >>> Reference heading RESET — face forward now")

            time.sleep(0.02)  # ~50 Hz

    except KeyboardInterrupt:
        print("\n\n  Stopping...")

    # ── Cleanup ──
    source.stop()
    sa.stop()
    imu.stop()
    logger.info("Test complete.")


if __name__ == "__main__":
    main()
