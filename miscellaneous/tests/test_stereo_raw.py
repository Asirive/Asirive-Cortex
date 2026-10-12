"""
Raw Stereo Output Diagnostic — Bypasses OpenAL entirely.

Tests if your earphones actually receive stereo audio by writing
a WAV with LEFT-only then RIGHT-only channels and playing via aplay
(direct ALSA, no PulseAudio, no OpenAL).

If you can't hear L/R separation here, the problem is your audio
output hardware/config, NOT OpenAL.

Usage (on RPi5):
    python tests/test_stereo_raw.py

Author: Haziq (@IRSPlays)
"""

import struct
import os
import sys
import tempfile
import subprocess
import numpy as np

SAMPLE_RATE = 44100
DURATION = 2.0  # seconds per test


def generate_stereo_wav(left: np.ndarray, right: np.ndarray, path: str):
    """Write a stereo 16-bit WAV file from separate L/R float arrays."""
    assert len(left) == len(right)
    n = len(left)
    
    # Interleave L/R samples
    stereo = np.empty(n * 2, dtype=np.int16)
    stereo[0::2] = (np.clip(left, -1.0, 1.0) * 32767).astype(np.int16)
    stereo[1::2] = (np.clip(right, -1.0, 1.0) * 32767).astype(np.int16)
    
    data = stereo.tobytes()
    channels = 2
    bps = 16
    byte_rate = SAMPLE_RATE * channels * (bps // 8)
    block_align = channels * (bps // 8)
    
    with open(path, 'wb') as f:
        f.write(b'RIFF')
        f.write(struct.pack('<I', 36 + len(data)))
        f.write(b'WAVE')
        f.write(b'fmt ')
        f.write(struct.pack('<IHHIIHH', 16, 1, channels, SAMPLE_RATE,
                            byte_rate, block_align, bps))
        f.write(b'data')
        f.write(struct.pack('<I', len(data)))
        f.write(data)


def make_chirp(duration_s: float, f_start: float = 300, f_end: float = 1200) -> np.ndarray:
    """Generate a pleasant FM chirp sweep — broadband, HRTF-friendly."""
    n = int(SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n, endpoint=False)
    # Linear frequency sweep
    freq = f_start + (f_end - f_start) * t / duration_s
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    # Gentle envelope (fade in/out)
    env = np.ones(n)
    fade = int(0.05 * SAMPLE_RATE)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return np.sin(phase) * env * 0.8


def play_wav(path: str):
    """Play a WAV file using aplay (direct ALSA) or fallback to paplay."""
    try:
        # Try aplay first (bypasses PulseAudio)
        subprocess.run(['aplay', '-D', 'default', path],
                      check=True, timeout=10)
    except (FileNotFoundError, subprocess.CalledProcessError):
        try:
            # Fallback: paplay (PulseAudio)
            subprocess.run(['paplay', path], check=True, timeout=10)
        except (FileNotFoundError, subprocess.CalledProcessError):
            print("ERROR: Neither aplay nor paplay available!")
            print("       Install with: sudo apt install alsa-utils pulseaudio-utils")
            sys.exit(1)


def main():
    print()
    print("=" * 60)
    print("  RAW STEREO OUTPUT DIAGNOSTIC")
    print("  (Bypasses OpenAL — tests hardware directly)")
    print("=" * 60)
    print()
    print("  PUT ON YOUR EARPHONES before starting!")
    print()
    
    chirp = make_chirp(DURATION)
    silence = np.zeros_like(chirp)
    tmp_dir = tempfile.gettempdir()
    
    # --- Test 1: Left channel only ---
    print("  TEST 1: Playing chirp in LEFT EAR ONLY...")
    wav_path = os.path.join(tmp_dir, "stereo_test_left.wav")
    generate_stereo_wav(chirp, silence, wav_path)
    play_wav(wav_path)
    
    import time
    time.sleep(0.5)
    
    # --- Test 2: Right channel only ---
    print("  TEST 2: Playing chirp in RIGHT EAR ONLY...")
    wav_path = os.path.join(tmp_dir, "stereo_test_right.wav")
    generate_stereo_wav(silence, chirp, wav_path)
    play_wav(wav_path)
    
    time.sleep(0.5)
    
    # --- Test 3: Both channels ---
    print("  TEST 3: Playing chirp in BOTH EARS (centered)...")
    wav_path = os.path.join(tmp_dir, "stereo_test_both.wav")
    generate_stereo_wav(chirp, chirp, wav_path)
    play_wav(wav_path)
    
    print()
    print("=" * 60)
    print("  RESULTS:")
    print("=" * 60)
    print()
    print("  Q1: Did Test 1 play ONLY in your LEFT ear?")
    print("  Q2: Did Test 2 play ONLY in your RIGHT ear?")
    print("  Q3: Did Test 3 play in BOTH ears centered?")
    print()
    print("  If Q1=yes and Q2=yes:")
    print("    -> Your earphones output STEREO correctly.")
    print("    -> OpenAL was the problem, not your hardware.")
    print()
    print("  If both tests sounded the SAME in both ears:")
    print("    -> Audio is being downmixed to MONO somewhere.")
    print("    -> Check: bluetoothctl info | grep 'UUID'")
    print("    -> Your BT headphones may be in HFP/HSP (mono) mode")
    print("    -> instead of A2DP (stereo) mode.")
    print()
    print("  If you heard nothing:")
    print("    -> Check: aplay -l  (list audio devices)")
    print("    -> Check volume: amixer -c 0 sset Master 100%")
    print()
    
    # Clean up
    for f in ['stereo_test_left.wav', 'stereo_test_right.wav', 'stereo_test_both.wav']:
        p = os.path.join(tmp_dir, f)
        if os.path.exists(p):
            os.unlink(p)


if __name__ == "__main__":
    main()
