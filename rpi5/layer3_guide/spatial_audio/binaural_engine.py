"""
Project-Cortex v2.0 - Binaural HRTF Engine

Manual binaural 3D audio rendering that bypasses OpenAL entirely.
Implements real HRTF physics: ITD, ILD, and head-shadow filtering.

Inspired by:
- franciscorotea/3D-Audio-Panner (CIPIC HRTF + overlap-save convolution)
- pffelix/audio3d (KEMAR HRTF + FFT overlap-add)
- Sound-engineer skill (HRTF convolution theory)

HOW IT WORKS:
    1. Takes a mono audio signal (tone, chirp, WAV, etc.)
    2. Computes azimuth/elevation to the virtual source
    3. Applies HRTF cues to produce stereo binaural output:
       - ITD: Interaural Time Delay (sound arrives earlier at near ear)
       - ILD: Interaural Level Difference (sound is louder in near ear)
       - Head Shadow: high frequencies attenuated on far ear (low-pass)
    4. Outputs stereo via sounddevice (direct ALSA, no OpenAL)

For full HRTF fidelity, a KEMAR/CIPIC database can be loaded.
The built-in model uses physics-based ITD/ILD/head-shadow which
gives very convincing L/R separation (the most critical for navigation).

Dependencies: numpy, scipy, sounddevice
    pip install numpy scipy sounddevice

Author: Haziq (@IRSPlays)
Date: March 23, 2026
"""

import math
import struct
import threading
import time
import logging
import os
import tempfile
from typing import Optional, Tuple, Dict
from dataclasses import dataclass

import numpy as np
from scipy import signal as sig

logger = logging.getLogger("BinauralEngine")

# ============================================================================
# Constants
# ============================================================================

SAMPLE_RATE = 44100
HEAD_RADIUS_M = 0.0875        # Average human head radius (ITD model)
SPEED_OF_SOUND = 343.0        # m/s at 20°C

# Maximum ITD in samples (~0.65ms at 90°)
MAX_ITD_SAMPLES = int(HEAD_RADIUS_M * 3.0 / SPEED_OF_SOUND * SAMPLE_RATE)  # ~8 samples


# ============================================================================
# Sound Generators — pleasant, HRTF-localizable sounds
# ============================================================================

def generate_chirp(duration_s: float = 0.3, f_start: float = 400,
                   f_end: float = 1200, sr: int = SAMPLE_RATE) -> np.ndarray:
    """
    Generate a pleasant FM chirp sweep.
    Broadband content makes it HRTF-localizable.
    Short duration feels like a sonar ping.
    """
    n = int(sr * duration_s)
    t = np.linspace(0, duration_s, n, endpoint=False)
    freq = f_start + (f_end - f_start) * t / duration_s
    phase = 2 * np.pi * np.cumsum(freq) / sr
    # Hann envelope for clean onset/offset
    env = np.hanning(n)
    return (np.sin(phase) * env * 0.8).astype(np.float64)


def generate_melody_ping(duration_s: float = 0.4, base_freq: float = 600,
                         sr: int = SAMPLE_RATE) -> np.ndarray:
    """
    Generate a two-tone melody ping (like Microsoft Soundscape beacon).
    Two notes: base and a fifth above (1.5x freq). Pleasant and localizable.
    """
    half_n = int(sr * duration_s / 2)
    t1 = np.linspace(0, duration_s / 2, half_n, endpoint=False)
    t2 = np.linspace(0, duration_s / 2, half_n, endpoint=False)

    # First note + harmonics (richer spectrum = better HRTF)
    note1 = (np.sin(2 * np.pi * base_freq * t1) * 0.6 +
             np.sin(2 * np.pi * base_freq * 2 * t1) * 0.25 +
             np.sin(2 * np.pi * base_freq * 3 * t1) * 0.15)
    # Second note (fifth above)
    f2 = base_freq * 1.5
    note2 = (np.sin(2 * np.pi * f2 * t2) * 0.6 +
             np.sin(2 * np.pi * f2 * 2 * t2) * 0.25 +
             np.sin(2 * np.pi * f2 * 3 * t2) * 0.15)

    wave = np.concatenate([note1, note2])
    env = np.hanning(len(wave))
    return (wave * env * 0.8).astype(np.float64)


def generate_continuous_tone(duration_s: float = 2.0, freq: float = 500,
                             sr: int = SAMPLE_RATE) -> np.ndarray:
    """
    Generate a rich continuous tone with harmonics.
    Vibrato adds movement. Harmonics provide broadband content for HRTF.
    """
    n = int(sr * duration_s)
    t = np.linspace(0, duration_s, n, endpoint=False)
    # Vibrato (slight pitch modulation)
    vibrato = 1.0 + 0.005 * np.sin(2 * np.pi * 5 * t)
    phase = 2 * np.pi * freq * np.cumsum(vibrato) / sr
    # Fundamental + harmonics (rich spectrum for HRTF)
    wave = (np.sin(phase) * 0.5 +
            np.sin(2 * phase) * 0.25 +
            np.sin(3 * phase) * 0.12 +
            np.sin(4 * phase) * 0.08 +
            np.sin(5 * phase) * 0.05)
    # Gentle fade in/out
    fade = int(0.05 * sr)
    wave[:fade] *= np.linspace(0, 1, fade)
    wave[-fade:] *= np.linspace(1, 0, fade)
    return (wave * 0.7).astype(np.float64)


# ============================================================================
# HRTF Model — Physics-based ITD, ILD, Head Shadow
# ============================================================================

@dataclass
class BinauralParams:
    """Computed binaural parameters for a given source position."""
    itd_samples: int       # Interaural time delay (positive = left ear leads)
    ild_left_db: float     # Level for left ear (dB)
    ild_right_db: float    # Level for right ear (dB)
    azimuth_deg: float     # Source azimuth in degrees
    elevation_deg: float   # Source elevation in degrees
    shadow_cutoff_hz: float  # Head shadow low-pass cutoff for far ear


def compute_azimuth_elevation(x: float, y: float, z: float) -> Tuple[float, float]:
    """
    Compute azimuth and elevation from 3D position.

    Coordinate system (matching OpenAL):
        X = right (+) / left (-)
        Y = up (+) / down (-)
        Z = behind (+) / front (-)

    Returns azimuth [-180, 180] and elevation [-90, 90] in degrees.
    Azimuth: 0 = front, +90 = right, -90 = left, ±180 = behind.
    """
    dist_xz = math.sqrt(x * x + z * z)
    # Azimuth: angle in XZ plane. Front is -Z, so atan2(x, -z)
    azimuth = math.degrees(math.atan2(x, -z)) if dist_xz > 1e-9 else 0.0
    # Elevation: angle above/below horizon
    dist_total = math.sqrt(x * x + y * y + z * z)
    elevation = math.degrees(math.asin(y / dist_total)) if dist_total > 1e-9 else 0.0
    return azimuth, elevation


def compute_binaural_params(azimuth_deg: float, elevation_deg: float = 0.0) -> BinauralParams:
    """
    Compute binaural rendering parameters from azimuth/elevation.

    Uses the Woodworth spherical-head model for ITD and
    frequency-dependent ILD based on head-shadow physics.

    Args:
        azimuth_deg: -180 to +180 (0=front, +90=right, -90=left)
        elevation_deg: -90 to +90
    """
    az_rad = math.radians(azimuth_deg)
    el_rad = math.radians(elevation_deg)

    # Effective azimuth (elevation reduces lateral displacement)
    effective_az = math.asin(math.cos(el_rad) * math.sin(az_rad))

    # --- ITD: Woodworth spherical-head model ---
    # For |azimuth| <= 90°: ITD = (a/c) * (sin(θ) + θ)
    # For |azimuth| > 90°: add pi-θ term
    abs_az = abs(effective_az)
    if abs_az <= math.pi / 2:
        itd_seconds = (HEAD_RADIUS_M / SPEED_OF_SOUND) * (math.sin(abs_az) + abs_az)
    else:
        itd_seconds = (HEAD_RADIUS_M / SPEED_OF_SOUND) * (math.sin(abs_az) + (math.pi - abs_az))

    # Positive ITD = right ear leads (source on right), negative = left leads
    itd_samples = int(round(itd_seconds * SAMPLE_RATE))
    if azimuth_deg < 0:  # Source on left → left ear leads → negative ITD
        itd_samples = -itd_samples

    # --- ILD: Head shadow intensity difference ---
    # Simplified model: ILD increases with frequency and azimuth
    # At 1kHz: ~3dB at 30°, ~8dB at 60°, ~10dB at 90°
    # We apply an average broadband ILD
    sin_az = math.sin(abs(effective_az))
    ild_db = 10.0 * sin_az  # 0 dB at front, 10 dB at 90°

    if azimuth_deg >= 0:  # Source on right
        ild_left_db = -ild_db   # Left ear (far) is quieter
        ild_right_db = 0.0      # Right ear (near) at full level
    else:  # Source on left
        ild_left_db = 0.0       # Left ear (near) at full level
        ild_right_db = -ild_db  # Right ear (far) is quieter

    # --- Head Shadow cutoff ---
    # The head acts as a low-pass filter on the far ear.
    # Shadow effect is strongest at 90° (cutoff ~1.5kHz),
    # weakest at 0° (no shadow, cutoff essentially infinite).
    # This is the MOST IMPORTANT cue for localization.
    min_cutoff = 1500.0   # Strong shadow at 90°
    max_cutoff = 16000.0  # No shadow at 0°
    shadow_cutoff = max_cutoff - (max_cutoff - min_cutoff) * sin_az

    return BinauralParams(
        itd_samples=itd_samples,
        ild_left_db=ild_left_db,
        ild_right_db=ild_right_db,
        azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,
        shadow_cutoff_hz=shadow_cutoff,
    )


# ============================================================================
# Binaural Renderer — applies HRTF cues to mono signal
# ============================================================================

def render_binaural(mono: np.ndarray, azimuth_deg: float,
                    elevation_deg: float = 0.0,
                    sr: int = SAMPLE_RATE) -> np.ndarray:
    """
    Render a mono signal to binaural stereo using physics-based HRTF.

    Args:
        mono: 1D float64 array, mono audio signal
        azimuth_deg: source azimuth (-180 to +180, 0=front, +90=right)
        elevation_deg: source elevation (-90 to +90)
        sr: sample rate

    Returns:
        2D float64 array of shape (n_samples, 2) — [left, right] channels
    """
    params = compute_binaural_params(azimuth_deg, elevation_deg)
    n = len(mono)

    # Start with copies for each ear
    left = mono.copy()
    right = mono.copy()

    # --- Apply ITD (time delay) ---
    delay = abs(params.itd_samples)
    if delay > 0:
        if params.itd_samples > 0:
            # Source on right → right ear hears first → delay left ear
            left = np.concatenate([np.zeros(delay), left[:n - delay]])
        else:
            # Source on left → left ear hears first → delay right ear
            right = np.concatenate([np.zeros(delay), right[:n - delay]])

    # --- Apply ILD (level difference) ---
    left *= 10 ** (params.ild_left_db / 20)
    right *= 10 ** (params.ild_right_db / 20)

    # --- Apply Head Shadow (low-pass on far ear) ---
    if params.shadow_cutoff_hz < (sr / 2 - 100):
        # Design a gentle low-pass (2nd order Butterworth)
        sos = sig.butter(2, params.shadow_cutoff_hz, btype='low',
                         fs=sr, output='sos')
        if azimuth_deg >= 0:
            # Source on right → filter left (far) ear
            left = sig.sosfilt(sos, left)
        else:
            # Source on left → filter right (far) ear
            right = sig.sosfilt(sos, right)

    # Combine into stereo
    stereo = np.column_stack([left, right])
    return stereo


# ============================================================================
# Binaural Audio Engine — manages playback via sounddevice
# ============================================================================

class BinauralEngine:
    """
    Real-time binaural 3D audio engine using manual HRTF rendering.

    Bypasses OpenAL entirely. Outputs stereo directly via sounddevice
    (which talks to ALSA on RPi5, not PulseAudio).

    Usage:
        engine = BinauralEngine()
        engine.start()

        # Play a ping at 45° right
        engine.play_at(azimuth_deg=45, elevation_deg=0)

        # Or play continuously with head tracking
        engine.start_continuous(azimuth_deg=90)
        engine.update_position(azimuth_deg=45)  # smooth transition
        engine.stop_continuous()

        engine.stop()
    """

    def __init__(self, sr: int = SAMPLE_RATE, gain: float = 1.0):
        self._sr = sr
        self._gain = gain
        self._sd = None  # sounddevice module (lazy import)
        self._stream = None
        self._lock = threading.Lock()

        # Continuous playback state
        self._continuous = False
        self._cont_mono: Optional[np.ndarray] = None   # looping mono buffer
        self._cont_azimuth = 0.0
        self._cont_elevation = 0.0
        self._cont_pos = 0       # playback position in mono buffer
        self._cont_params: Optional[BinauralParams] = None

    def start(self) -> bool:
        """Initialize the audio engine."""
        try:
            import sounddevice as sd
            self._sd = sd
            sd.default.samplerate = self._sr
            sd.default.channels = 2
            sd.default.dtype = 'float32'
            logger.info(f"BinauralEngine started (sr={self._sr})")
            logger.info(f"  Output device: {sd.query_devices(sd.default.device[1])['name']}")
            return True
        except ImportError:
            logger.error("sounddevice not installed! pip install sounddevice")
            return False
        except Exception as e:
            logger.error(f"Failed to init sounddevice: {e}")
            return False

    def stop(self):
        """Shut down the engine."""
        self.stop_continuous()
        self._sd = None
        logger.info("BinauralEngine stopped")

    def play_at(self, azimuth_deg: float, elevation_deg: float = 0.0,
                sound: str = "chirp", duration_s: float = 0.3):
        """
        Play a one-shot ping at a 3D position.

        Args:
            azimuth_deg: 0=front, +90=right, -90=left, 180=behind
            elevation_deg: +90=above, -90=below
            sound: "chirp", "melody", or "tone"
            duration_s: duration of the ping
        """
        if not self._sd:
            return

        # Generate sound
        if sound == "melody":
            mono = generate_melody_ping(duration_s)
        elif sound == "tone":
            mono = generate_continuous_tone(duration_s)
        else:
            mono = generate_chirp(duration_s)

        # Render binaural
        stereo = render_binaural(mono, azimuth_deg, elevation_deg, self._sr)
        stereo *= self._gain

        # Play (blocking for one-shot)
        self._sd.play(stereo.astype(np.float32), self._sr)
        self._sd.wait()

    def play_at_nonblocking(self, azimuth_deg: float, elevation_deg: float = 0.0,
                            sound: str = "chirp", duration_s: float = 0.3):
        """Non-blocking version of play_at — fire and forget."""
        if not self._sd:
            return

        if sound == "melody":
            mono = generate_melody_ping(duration_s)
        elif sound == "tone":
            mono = generate_continuous_tone(duration_s)
        else:
            mono = generate_chirp(duration_s)

        stereo = render_binaural(mono, azimuth_deg, elevation_deg, self._sr)
        stereo *= self._gain
        self._sd.play(stereo.astype(np.float32), self._sr)

    def start_continuous(self, azimuth_deg: float = 0.0,
                         elevation_deg: float = 0.0,
                         freq: float = 500, loop_duration_s: float = 2.0):
        """
        Start a continuous looping sound at a 3D position.
        Call update_position() to move it in real-time.
        """
        if not self._sd:
            return

        self._cont_mono = generate_continuous_tone(loop_duration_s, freq, self._sr)
        self._cont_azimuth = azimuth_deg
        self._cont_elevation = elevation_deg
        self._cont_pos = 0
        self._cont_params = compute_binaural_params(azimuth_deg, elevation_deg)
        self._continuous = True

        def _callback(outdata, frames, time_info, status):
            if status:
                logger.warning(f"Audio callback status: {status}")

            if not self._continuous or self._cont_mono is None:
                outdata[:] = 0
                return

            mono = self._cont_mono
            n_mono = len(mono)

            # Extract a chunk from the looping buffer
            chunk = np.empty(frames, dtype=np.float64)
            pos = self._cont_pos
            for i in range(frames):
                chunk[i] = mono[pos % n_mono]
                pos += 1
            self._cont_pos = pos % n_mono

            # Render binaural with current position
            stereo = render_binaural(chunk, self._cont_azimuth,
                                     self._cont_elevation, self._sr)
            stereo *= self._gain
            outdata[:] = stereo.astype(np.float32)

        self._stream = self._sd.OutputStream(
            samplerate=self._sr,
            channels=2,
            dtype='float32',
            blocksize=1024,
            callback=_callback,
        )
        self._stream.start()
        logger.info(f"Continuous playback started at az={azimuth_deg}°")

    def update_position(self, azimuth_deg: float, elevation_deg: float = 0.0):
        """Update the position of the continuous sound source."""
        self._cont_azimuth = azimuth_deg
        self._cont_elevation = elevation_deg

    def stop_continuous(self):
        """Stop continuous playback."""
        self._continuous = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def render_to_wav(self, mono: np.ndarray, azimuth_deg: float,
                      elevation_deg: float = 0.0) -> str:
        """
        Render mono audio to a binaural stereo WAV file.

        Returns path to the temporary WAV file (useful for playback
        via aplay if sounddevice isn't available).
        """
        stereo = render_binaural(mono, azimuth_deg, elevation_deg, self._sr)
        stereo *= self._gain

        # Write stereo WAV
        n = len(stereo)
        left = (np.clip(stereo[:, 0], -1.0, 1.0) * 32767).astype(np.int16)
        right = (np.clip(stereo[:, 1], -1.0, 1.0) * 32767).astype(np.int16)
        interleaved = np.empty(n * 2, dtype=np.int16)
        interleaved[0::2] = left
        interleaved[1::2] = right
        data = interleaved.tobytes()

        channels = 2
        bps = 16
        byte_rate = self._sr * channels * (bps // 8)
        block_align = channels * (bps // 8)

        path = os.path.join(tempfile.gettempdir(), "binaural_render.wav")
        with open(path, 'wb') as f:
            f.write(b'RIFF')
            f.write(struct.pack('<I', 36 + len(data)))
            f.write(b'WAVE')
            f.write(b'fmt ')
            f.write(struct.pack('<IHHIIHH', 16, 1, channels, self._sr,
                                byte_rate, block_align, bps))
            f.write(b'data')
            f.write(struct.pack('<I', len(data)))
            f.write(data)

        return path
