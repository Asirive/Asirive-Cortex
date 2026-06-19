"""
Audio Alert Manager — Pre-recorded Safety Alerts

Manages pre-recorded WAV audio clips for instant hazard alerts.
Clips are played non-blocking via PipeWire/paplay for <50ms latency.

On first run, generates all alert clips using Supertonic TTS if they don't exist.

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
# Use {distance} placeholder for runtime distance injection.
# C4 fix: keys must match the safety_monitor / hailo_depth hazard type
# values (lowercase strings: "wall", "stairs_down", "overhang", etc.).
# Previously the overhang key was misspelled as "overhead" — Hailo emits
# "overhang" so the lookup missed and pre-generated overhang.wav never
# played; the user got haptic only.
ALERT_TEXTS: Dict[str, str] = {
    "wall":                "Wall, {distance} ahead",
    "stairs_down":         "Stairs going down, {distance} ahead",
    "stairs_up":           "Stairs going up, {distance} ahead",
    "curb":                "Step, {distance} ahead",
    "dropoff":             "Drop off, {distance} ahead. Stop!",
    "approaching_object":  "Something approaching, {distance} away",
    "overhang":            "Overhead obstacle, {distance} ahead. Duck!",
    "signboard":           "Low signboard ahead, {distance}",
    "branch":              "Low branch ahead, {distance}",
    # H32 fix: Tier 2 (COCO silent-static) alerts. The original
    # template lookup fell through to `alert_key.replace("_", " ")`
    # and produced "fire hydrant" with no distance, even when
    # distance_m was known. Add explicit templates so the
    # formatter replaces {distance} properly.
    "fire_hydrant":        "Fire hydrant, {distance} ahead",
    "bench":               "Bench, {distance} ahead",
    "chair":               "Chair, {distance} ahead",
    "potted plant":        "Plant, {distance} ahead",
    "parking meter":       "Parking meter, {distance} ahead",
    "suitcase":            "Suitcase, {distance} ahead",
    "backpack":            "Backpack, {distance} ahead",
    "skateboard":          "Skateboard, {distance} ahead",
    "stop sign":           "Stop sign, {distance} ahead",
    "traffic light":       "Traffic light, {distance} ahead",
    "umbrella":            "Umbrella, {distance} ahead",
    "handbag":             "Handbag, {distance} ahead",
    "surfboard":           "Surfboard, {distance} ahead",
    "snowboard":           "Snowboard, {distance} ahead",
    "dining table":        "Table, {distance} ahead",
    "toilet":              "Toilet, {distance} ahead",
    "couch":               "Couch, {distance} ahead",
    "bed":                 "Bed, {distance} ahead",
}


class AudioAlertManager:
    """
    Plays pre-recorded WAV clips for instant hazard alerts.
    
    Features:
    - Non-blocking playback via paplay (PipeWire/PulseAudio)
    - Per-alert cooldown to prevent spam
    - Auto-generates clips via Supertonic TTS on first run
    - Pre-generates common distance variants for instant playback
    """

    # Common distances to pre-generate (meters)
    PREMADE_DISTANCES = [1, 2, 3, 4, 5]

    def __init__(
        self,
        alerts_dir: str = None,
        cooldown: float = 6.0,  # H21 fix: 6.0s per safety spec, was 3.0s
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
        self._premade_clips: Dict[str, str] = {}  # "alert_key_dist" -> full path
        self._play_lock = threading.Lock()
        self._supertonic = None
        
        # Ensure directory exists
        self.alerts_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing clips
        self._load_clips()
        
        # Generate missing base clips
        missing = [k for k in ALERT_TEXTS if k not in self._clips]
        if missing:
            logger.info(f"Generating {len(missing)} missing alert clips: {missing}")
            self._generate_missing_clips(missing)
        
        # Pre-generate common distance variants
        self._generate_premade_distance_clips()

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
        Generate missing WAV clips using Supertonic TTS.
        Falls back to pico2wave or espeak if Supertonic is unavailable.
        """
        for key in missing_keys:
            text = ALERT_TEXTS[key]
            wav_path = self.alerts_dir / f"{key}.wav"
            
            try:
                # Try Supertonic TTS first (highest quality, local ONNX)
                if self._generate_with_supertonic(text, str(wav_path)):
                    self._clips[key] = str(wav_path)
                    logger.info(f"Generated alert clip (Supertonic): {key}")
                    continue
                
                # Fallback to espeak (always available on RPi)
                if self._generate_with_espeak(text, str(wav_path)):
                    self._clips[key] = str(wav_path)
                    logger.info(f"Generated alert clip (espeak): {key}")
                    continue
                    
                logger.warning(f"Failed to generate alert clip: {key}")
                
            except Exception as e:
                logger.error(f"Error generating alert clip '{key}': {e}")

    def _generate_with_supertonic(self, text: str, output_path: str) -> bool:
        """Generate WAV using Supertonic TTS engine (local ONNX)."""
        try:
            if self._supertonic is None:
                from rpi5.layer1_reflex.supertonic_handler import SupertonicTTS
                self._supertonic = SupertonicTTS()
            if not self._supertonic.available:
                return False
            return self._supertonic.save_to_file(text, output_path)
        except Exception as e:
            logger.debug(f"Supertonic TTS not available for alert generation: {e}")
            return False

    def _generate_premade_distance_clips(self):
        """Pre-generate WAV clips for common distance variants."""
        generated = 0
        for alert_key, template in ALERT_TEXTS.items():
            for dist in self.PREMADE_DISTANCES:
                clip_key = f"{alert_key}_{dist}m"
                wav_path = self.alerts_dir / f"{clip_key}.wav"
                
                # Skip if already exists
                if wav_path.exists():
                    self._premade_clips[clip_key] = str(wav_path)
                    continue
                
                # Build text with distance
                if dist == 1:
                    dist_str = "1 meter"
                else:
                    dist_str = f"{dist} meters"
                text = template.format(distance=dist_str)
                
                # Generate with Supertonic
                if self._generate_with_supertonic(text, str(wav_path)):
                    self._premade_clips[clip_key] = str(wav_path)
                    generated += 1
        
        if generated > 0:
            logger.info(f"Pre-generated {generated} distance variant clips")
        logger.info(f"Premade clips loaded: {len(self._premade_clips)}")

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

        Uses pre-generated clips for common distances, Supertonic for
        real-time generation, and espeak-ng as last-resort fallback.

        Args:
            alert_key: Alert type (e.g., "wall", "stairs_down", "dropoff")
            blocking: If True, wait for playback to complete
            distance_m: Distance in meters (injected into speech text)

        Returns:
            True if alert was spoken, False if on cooldown or unavailable
        """
        now = time.time()

        # H21 fix: key the cooldown by (alert_key, distance_bucket)
        # so a "wall 2m" alert doesn't suppress an updated "wall 3m"
        # 100ms later. The previous version keyed on alert_key alone,
        # so a distance change still hit cooldown and the user heard
        # a stale distance for the configured cooldown window.
        # Bucket to 1m granularity — finer buckets let micro-jitter
        # bypass cooldown; coarser buckets re-create the bug.
        if distance_m is not None:
            bucket = int(round(distance_m))
            cooldown_key = f"{alert_key}@{bucket}m"
        else:
            cooldown_key = alert_key

        last = self._last_played.get(cooldown_key, 0)
        if (now - last) < self.cooldown:
            logger.debug(
                f"Alert '{cooldown_key}' on cooldown "
                f"({now - last:.1f}s < {self.cooldown}s)"
            )
            return False

        self._last_played[cooldown_key] = now

        # Build spoken text with distance
        template = ALERT_TEXTS.get(alert_key, alert_key.replace("_", " "))
        if distance_m is not None:
            if distance_m < 1.0:
                dist_str = f"{distance_m:.1f} meters"
            else:
                dist_str = f"{int(round(distance_m))} meters"
            text = template.format(distance=dist_str)
        else:
            text = template.replace(", {distance}", "").replace("{distance} ", "").replace("{distance}", "")

        # Try pre-generated clip first (instant playback for common distances)
        if distance_m is not None:
            rounded_dist = int(round(distance_m))
            if rounded_dist in self.PREMADE_DISTANCES:
                clip_key = f"{alert_key}_{rounded_dist}m"
                clip_path = self._premade_clips.get(clip_key)
                if clip_path and os.path.exists(clip_path):
                    if blocking:
                        return self._play_sync(clip_path)
                    else:
                        thread = threading.Thread(target=self._play_sync, args=(clip_path,), daemon=True)
                        thread.start()
                        return True

        # Fall back to real-time TTS with Supertonic
        def _speak():
            # Try Supertonic first (high quality, local)
            if self._supertonic is None:
                try:
                    from rpi5.layer1_reflex.supertonic_handler import SupertonicTTS
                    self._supertonic = SupertonicTTS()
                except Exception:
                    pass
            
            if self._supertonic and self._supertonic.available:
                wav_bytes = self._supertonic.generate_wav_bytes(text)
                if wav_bytes:
                    # Save to temp file and play
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                        temp_path = f.name
                        f.write(wav_bytes)
                    try:
                        result = self._play_sync(temp_path)
                        os.unlink(temp_path)
                        return result
                    except Exception:
                        pass
            
            # Last resort: espeak-ng
            try:
                result = subprocess.run(
                    ["espeak-ng", "-s", "180", "-p", "50", "-a", "200", text],
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            
            # Final fallback: play pre-recorded clip (no distance info)
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
