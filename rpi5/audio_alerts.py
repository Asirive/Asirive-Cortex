"""
Audio Alert Manager — Pre-recorded Safety Alerts

Manages pre-recorded WAV audio clips for instant hazard alerts.
Clips are played non-blocking via PipeWire/paplay for <50ms latency.

On first run, generates all alert clips using Kokoro TTS if they don't exist.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — YIA 2026
"""

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Alert definitions: alert_key -> spoken text template
# Use {distance} placeholder for runtime distance injection
ALERT_TEXTS: Dict[str, str] = {
    "wall":                "Wall, {distance} ahead",
    "stairs_down":         "Stairs going down, {distance} ahead",
    "stairs_up":           "Stairs going up, {distance} ahead",
    "curb":                "Step, {distance} ahead",
    "dropoff":             "Drop off, {distance} ahead. Stop!",
    "approaching_object":  "Something approaching, {distance} away",
    "overhead":            "Overhead obstacle, {distance} ahead. Duck!",
    "signboard":           "Low signboard ahead, {distance}",
    "branch":              "Low branch ahead, {distance}",
}


class AudioAlertManager:
    """
    Plays pre-recorded WAV clips for instant hazard alerts.
    
    Features:
    - Non-blocking playback via paplay (PipeWire/PulseAudio)
    - Per-alert cooldown to prevent spam
    - Auto-generates clips via Kokoro TTS on first run
    """

    def __init__(
        self,
        alerts_dir: str = None,
        cooldown: float = 3.0,
    ):
        """
        Initialize the audio alert manager.
        
        Args:
            alerts_dir: Directory containing WAV alert clips.
                        Defaults to rpi5/assets/alerts/
            cooldown: Minimum seconds between the same alert type
        """
        if alerts_dir is None:
            alerts_dir = str(Path(__file__).parent / "assets" / "alerts")
        
        self.alerts_dir = Path(alerts_dir)
        self.cooldown = cooldown
        self._last_played: Dict[str, float] = {}
        self._clips: Dict[str, str] = {}  # alert_key -> full path to WAV
        self._play_lock = threading.Lock()
        
        # Ensure directory exists
        self.alerts_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing clips
        self._load_clips()
        
        # Generate missing clips
        missing = [k for k in ALERT_TEXTS if k not in self._clips]
        if missing:
            logger.info(f"Generating {len(missing)} missing alert clips: {missing}")
            self._generate_missing_clips(missing)

    def _load_clips(self):
        """Scan alerts directory for existing WAV files."""
        for key in ALERT_TEXTS:
            wav_path = self.alerts_dir / f"{key}.wav"
            if wav_path.exists():
                self._clips[key] = str(wav_path)
                logger.debug(f"Loaded alert clip: {key} -> {wav_path}")
        
        logger.info(f"Alert clips loaded: {len(self._clips)}/{len(ALERT_TEXTS)}")

    def _generate_missing_clips(self, missing_keys: list):
        """
        Generate missing WAV clips using Kokoro TTS.
        Falls back to pico2wave or espeak if Kokoro is unavailable.
        """
        for key in missing_keys:
            text = ALERT_TEXTS[key]
            wav_path = self.alerts_dir / f"{key}.wav"
            
            try:
                # Try Kokoro TTS first (highest quality)
                if self._generate_with_kokoro(text, str(wav_path)):
                    self._clips[key] = str(wav_path)
                    logger.info(f"Generated alert clip (Kokoro): {key}")
                    continue
                
                # Fallback to espeak (always available on RPi)
                if self._generate_with_espeak(text, str(wav_path)):
                    self._clips[key] = str(wav_path)
                    logger.info(f"Generated alert clip (espeak): {key}")
                    continue
                    
                logger.warning(f"Failed to generate alert clip: {key}")
                
            except Exception as e:
                logger.error(f"Error generating alert clip '{key}': {e}")

    def _generate_with_kokoro(self, text: str, output_path: str) -> bool:
        """Generate WAV using Kokoro TTS engine."""
        try:
            from rpi5.layer1_reflex.kokoro_handler import KokoroTTS
            kokoro = KokoroTTS()
            kokoro.load_pipeline()
            
            # Generate speech
            audio_data = kokoro.generate_speech(text)
            if audio_data is not None:
                import numpy as np
                import wave
                import struct
                
                # Kokoro returns float32 audio, convert to int16 WAV
                if isinstance(audio_data, np.ndarray):
                    audio_int16 = (audio_data * 32767).astype(np.int16)
                    with wave.open(output_path, 'w') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)  # 16-bit
                        wf.setframerate(24000)  # Kokoro default sample rate
                        wf.writeframes(audio_int16.tobytes())
                    return True
            return False
        except Exception as e:
            logger.debug(f"Kokoro TTS not available for alert generation: {e}")
            return False

    def _generate_with_espeak(self, text: str, output_path: str) -> bool:
        """Generate WAV using espeak-ng (fallback, lower quality)."""
        try:
            result = subprocess.run(
                ["espeak-ng", "-w", output_path, "-s", "160", "-p", "50", text],
                capture_output=True, timeout=10
            )
            return result.returncode == 0 and os.path.exists(output_path)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def play(self, alert_key: str, blocking: bool = False, distance_m: float = None) -> bool:
        """
        Speak an alert with distance info if not on cooldown.
        
        Uses espeak-ng for real-time speech with distance, falling back to
        pre-recorded clips if espeak is unavailable.
        
        Args:
            alert_key: Alert type (e.g., "wall", "stairs_down", "dropoff")
            blocking: If True, wait for playback to complete
            distance_m: Distance in meters (injected into speech text)
            
        Returns:
            True if alert was spoken, False if on cooldown or unavailable
        """
        now = time.time()
        
        # Check cooldown
        last = self._last_played.get(alert_key, 0)
        if (now - last) < self.cooldown:
            logger.debug(f"Alert '{alert_key}' on cooldown ({now - last:.1f}s < {self.cooldown}s)")
            return False
        
        self._last_played[alert_key] = now

        # Build spoken text with distance
        template = ALERT_TEXTS.get(alert_key, alert_key.replace("_", " "))
        if distance_m is not None:
            if distance_m < 1.0:
                dist_str = f"{distance_m:.1f} meters"
            else:
                dist_str = f"{distance_m:.0f} meters"
            text = template.format(distance=dist_str)
        else:
            text = template.replace(", {distance}", "").replace("{distance} ", "").replace("{distance}", "")

        # Try real-time TTS with espeak-ng (dynamic distance in speech)
        def _speak():
            try:
                result = subprocess.run(
                    ["espeak-ng", "-s", "180", "-p", "50", "-a", "200", text],
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            # Fallback: play pre-recorded clip (no distance info)
            clip_path = self._clips.get(alert_key)
            if clip_path and os.path.exists(clip_path):
                return self._play_sync(clip_path)
            return False

        if blocking:
            return _speak()
        else:
            thread = threading.Thread(target=_speak, daemon=True)
            thread.start()
            return True

    def _play_sync(self, clip_path: str) -> bool:
        """Play a WAV file synchronously via paplay (PipeWire/PulseAudio)."""
        with self._play_lock:
            try:
                result = subprocess.run(
                    ["paplay", clip_path],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode != 0:
                    # Fallback to aplay
                    result = subprocess.run(
                        ["aplay", "-q", clip_path],
                        capture_output=True,
                        timeout=5
                    )
                return result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                logger.warning(f"Audio playback failed: {e}")
                return False

    def is_clip_available(self, alert_key: str) -> bool:
        """Check if a clip exists for the given alert type."""
        return alert_key in self._clips

    @property
    def available_alerts(self) -> list:
        """List of alert types with available clips."""
        return list(self._clips.keys())

    def cleanup(self):
        """No persistent resources to clean up."""
        logger.info("Audio alert manager cleaned up")
