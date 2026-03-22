"""
3D Audio Diagnostic — tests OpenAL HRTF on RPi5.

Plays noise hard LEFT for 3s, then hard RIGHT for 3s.
If you hear it move between ears → basic panning works.
If it sounds the same in both ears → OpenAL spatial is broken.

Usage:
    python tests/diagnose_3d_audio.py
"""
import sys, struct, time, os, tempfile
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rpi5"))

from openal import oalInit, oalQuit, oalGetDevice, oalGetListener
from openal import Source, Buffer, WaveFile

# ---------- Query HRTF status ----------
oalInit()
dev = oalGetDevice()

from openal.alc import alcGetString, ALC_DEVICE_SPECIFIER
name = alcGetString(dev, ALC_DEVICE_SPECIFIER)
print(f"Device: {name}")

import ctypes
ALC_HRTF_SOFT = 0x1992
ALC_HRTF_STATUS_SOFT = 0x1993
try:
    from openal.alc import alcIsExtensionPresent, alcGetIntegerv
    has_ext = alcIsExtensionPresent(dev, b"ALC_SOFT_HRTF")
    print(f"ALC_SOFT_HRTF extension present: {has_ext}")
    buf = (ctypes.c_int * 1)()
    alcGetIntegerv(dev, ALC_HRTF_SOFT, 1, buf)
    print(f"HRTF enabled (ALC query): {buf[0]}")
    alcGetIntegerv(dev, ALC_HRTF_STATUS_SOFT, 1, buf)
    status_map = {0: "Disabled", 1: "Enabled", 2: "Denied", 3: "Required",
                  4: "Headphones detected", 5: "Unsupported format"}
    print(f"HRTF status: {buf[0]} = {status_map.get(buf[0], 'unknown')}")
except Exception as e:
    print(f"HRTF query error: {e}")

# ---------- Generate 1s white noise WAV ----------
SR = 44100
noise = np.random.randn(SR * 2).astype(np.float64)
noise = noise / np.max(np.abs(noise)) * 0.9
pcm = (noise * 32767).astype(np.int16)
data = pcm.tobytes()
header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt "
header += struct.pack("<IHHIIHH", 16, 1, 1, SR, SR * 2, 2, 16)
header += b"data" + struct.pack("<I", len(data))
tmp = os.path.join(tempfile.gettempdir(), "diag3d.wav")
with open(tmp, "wb") as f:
    f.write(header + data)

wf = WaveFile(tmp)
buf2 = Buffer(wf)
src = Source(buf2)
src.set_looping(True)
src.set_gain(3.0)
src.set_rolloff_factor(0.0)  # no distance attenuation

listener = oalGetListener()
listener.set_position((0, 0, 0))
listener.set_orientation((0, 0, -1, 0, 1, 0))  # facing -Z

# ---------- Test 1: Hard LEFT ----------
print("\n--- TEST 1: Sound at HARD LEFT (-1, 0, 0) for 3 seconds ---")
print("    You should hear noise ONLY/MAINLY in LEFT ear")
src.set_position((-1, 0, 0))
src.play()
time.sleep(3)

# ---------- Test 2: Hard RIGHT ----------
print("\n--- TEST 2: Sound at HARD RIGHT (1, 0, 0) for 3 seconds ---")
print("    You should hear noise ONLY/MAINLY in RIGHT ear")
src.set_position((1, 0, 0))
time.sleep(3)

# ---------- Test 3: FRONT ----------
print("\n--- TEST 3: Sound at FRONT (0, 0, -1) for 3 seconds ---")
print("    You should hear noise equally in BOTH ears (centered)")
src.set_position((0, 0, -1))
time.sleep(3)

# ---------- Test 4: BEHIND ----------
print("\n--- TEST 4: Sound at BEHIND (0, 0, 1) for 3 seconds ---")
print("    Should sound different from FRONT (more diffuse/inside head)")
src.set_position((0, 0, 1))
time.sleep(3)

src.stop()
print("\n--- Tests complete ---")
print("Q1: Did LEFT sound go to your left ear?")
print("Q2: Did RIGHT sound go to your right ear?")
print("Q3: Did FRONT and BEHIND sound different from each other?")
print()
print("If Q1=yes, Q2=yes: Basic panning works")
print("If Q3=yes: HRTF is active (front/back discrimination)")
print("If Q3=no: HRTF may not be working (only simple panning)")
print("If ALL no: OpenAL spatial audio is completely broken")

oalQuit()
