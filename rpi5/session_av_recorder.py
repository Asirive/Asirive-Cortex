"""
Session AV Recorder - Manual Camera + Audio Capture

Records camera frames, microphone PCM, and Gemini response PCM into a
timestamped session directory. Recording is designed to be toggled at
runtime so the main Cortex system can stay live when capture starts/stops.

Author: Haziq (@IRSPlays)
Date: April 23, 2026
"""

import json
import logging
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import cv2

logger = logging.getLogger(__name__)


class SessionAVRecorder:
    """Thread-safe session recorder for camera, mic, and Gemini audio."""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.start_on_init = bool(cfg.get("start_on_init", False))
        self.toggle_key = str(cfg.get("toggle_key", "b") or "b")[:1].lower()
        self.output_root = Path(cfg.get("output_path", "recordings"))
        self.record_camera = bool(cfg.get("record_camera", True))
        self.record_mic = bool(cfg.get("record_mic", True))
        self.record_ai_audio = bool(cfg.get("record_ai_audio", True))
        self.record_events = bool(cfg.get("record_events", True))
        self.video_fps = float(cfg.get("video_fps", 10.0))
        self.video_codec = str(cfg.get("video_codec", "MJPG") or "MJPG")
        self.video_container = str(cfg.get("video_container", "avi") or "avi")

        self.is_recording = False
        self.session_dir: Optional[Path] = None

        self._lock = threading.Lock()
        self._video_writer = None
        self._video_size: Optional[Tuple[int, int]] = None
        self._last_video_write = 0.0
        self._mic_wave = None
        self._ai_wave = None
        self._events_file = None

    def start(self, frame_shape: Optional[Tuple[int, int, int]] = None) -> bool:
        """Open a new recording session directory and prepare output files."""
        if not self.enabled:
            return False

        with self._lock:
            if self.is_recording:
                return True

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.session_dir = self.output_root / f"session_{timestamp}"
            self.session_dir.mkdir(parents=True, exist_ok=True)

            if frame_shape is not None:
                self._video_size = (int(frame_shape[1]), int(frame_shape[0]))

            if self.record_events:
                self._events_file = open(self.session_dir / "events.jsonl", "a", encoding="utf-8")

            self.is_recording = True
            self._last_video_write = 0.0
            self._log_event("recording_started", session_dir=str(self.session_dir))
            logger.info(f"🎥 Session recorder started: {self.session_dir}")
            return True

    def stop(self) -> None:
        """Flush and close the active recording session."""
        with self._lock:
            if not self.is_recording:
                return

            self._log_event("recording_stopped")
            self.is_recording = False

            if self._video_writer is not None:
                self._video_writer.release()
                self._video_writer = None

            if self._mic_wave is not None:
                self._mic_wave.close()
                self._mic_wave = None

            if self._ai_wave is not None:
                self._ai_wave.close()
                self._ai_wave = None

            if self._events_file is not None:
                self._events_file.close()
                self._events_file = None

            self._video_size = None
            logger.info("🛑 Session recorder stopped")

    def write_video_frame(self, frame, timestamp: Optional[float] = None) -> None:
        """Write a BGR OpenCV frame when the recorder is active."""
        if not self.is_recording or not self.record_camera or frame is None:
            return

        with self._lock:
            if not self.is_recording:
                return

            now = timestamp or time.time()
            min_interval = 1.0 / self.video_fps if self.video_fps > 0 else 0.0
            if min_interval and (now - self._last_video_write) < min_interval:
                return

            if self._video_writer is None:
                self._video_size = (int(frame.shape[1]), int(frame.shape[0]))
                self._ensure_video_writer()

            if self._video_writer is None:
                return

            if self._video_size != (int(frame.shape[1]), int(frame.shape[0])):
                frame = cv2.resize(frame, self._video_size, interpolation=cv2.INTER_AREA)

            self._video_writer.write(frame)
            self._last_video_write = now

    def write_mic_audio(self, audio_bytes: bytes, sample_rate: int) -> None:
        """Append microphone PCM bytes to the session WAV file."""
        if not self.is_recording or not self.record_mic or not audio_bytes:
            return

        with self._lock:
            if not self.is_recording:
                return
            if self._mic_wave is None:
                self._mic_wave = self._open_wave_file("mic_input.wav", sample_rate)
            if self._mic_wave is not None:
                self._mic_wave.writeframes(audio_bytes)

    def write_ai_audio(self, audio_bytes: bytes, sample_rate: int = 24000) -> None:
        """Append Gemini response PCM bytes to the session WAV file."""
        if not self.is_recording or not self.record_ai_audio or not audio_bytes:
            return

        with self._lock:
            if not self.is_recording:
                return
            if self._ai_wave is None:
                self._ai_wave = self._open_wave_file("gemini_output.wav", sample_rate)
            if self._ai_wave is not None:
                self._ai_wave.writeframes(audio_bytes)

    def log_text_event(self, kind: str, text: str) -> None:
        """Write a text event into the session log while recording."""
        if not text:
            return
        with self._lock:
            if not self.is_recording:
                return
            self._log_event(kind, text=text)

    def _ensure_video_writer(self) -> None:
        if self._video_writer is not None or self.session_dir is None or self._video_size is None:
            return

        video_path = self.session_dir / f"camera.{self.video_container}"
        fourcc = cv2.VideoWriter_fourcc(*self.video_codec)
        writer = cv2.VideoWriter(str(video_path), fourcc, self.video_fps, self._video_size)
        if writer is None or not writer.isOpened():
            logger.error(f"❌ Failed to open video writer: {video_path}")
            self._video_writer = None
            return
        self._video_writer = writer

    def _open_wave_file(self, filename: str, sample_rate: int):
        if self.session_dir is None:
            return None
        wav_file = wave.open(str(self.session_dir / filename), "wb")
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        return wav_file

    def _log_event(self, event_type: str, **payload) -> None:
        if self._events_file is None:
            return
        entry = {
            "timestamp": time.time(),
            "event": event_type,
        }
        entry.update(payload)
        self._events_file.write(json.dumps(entry) + "\n")
        self._events_file.flush()
