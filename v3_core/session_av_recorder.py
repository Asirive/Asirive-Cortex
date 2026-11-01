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

        # M46 fix: split the single lock into per-resource locks so
        # video writes, audio writes, and event logging don't block
        # each other. The legacy `_lock` is kept as an alias for the
        # session-state transitions (start/stop) only.
        self._state_lock = threading.Lock()
        self._video_lock = threading.Lock()
        self._audio_lock = threading.Lock()
        self._events_lock = threading.Lock()
        self._lock = self._state_lock  # backwards-compat alias

        self._video_writer = None
        self._video_size: Optional[Tuple[int, int]] = None
        self._last_video_write = 0.0
        # Real-time pacing: track when the FIRST frame of a session was
        # written and how many have been written, so the AVI container FPS
        # matches reality (prevents sped-up/slowed playback when the capture
        # rate differs from the configured video_fps).
        self._video_first_ts: Optional[float] = None
        self._video_frame_count: int = 0

        # Dual-lens recording (WITMOTION 400W stereo). The legacy
        # `_video_writer`/`_video_size`/`_last_video_write` above are the
        # LEFT-lens (safety) stream — kept as-is so existing behaviour and
        # the `camera.avi` filename never change. The members below add the
        # RIGHT lens (Gemini view) as a SECOND video file when the recorder
        # is attached to a stereo camera.
        self.record_stereo_right = bool(cfg.get("record_stereo_right", True))
        self._video_writer_right = None
        self._video_size_right: Optional[Tuple[int, int]] = None
        self._last_video_write_right = 0.0
        self._video_first_ts_right: Optional[float] = None
        self._video_frame_count_right: int = 0
        self._mic_wave = None
        self._ai_wave = None
        self._events_file = None

        # ── Dedicated capture thread ─────────────────────────────────────
        # The main loop is too busy (YOLO/depth/Gemini) to feed the recorder
        # frames steadily, so the video starved and played back sped-up. We
        # instead PULL frames directly from the camera in our own thread at a
        # steady video_fps, fully decoupled from main-loop load. Attach the
        # camera via attach_camera() before start().
        self._camera = None            # primary (LEFT / safety) camera object
        self._stereo = None            # StereoCameraHandler for the RIGHT lens
        self._capture_thread: Optional[threading.Thread] = None
        self._capture_running = False

    def attach_camera(self, camera, stereo=None) -> None:
        """Give the recorder a camera to pull frames from in its own thread.

        camera: the primary (LEFT/safety) camera — must expose get_frame().
        stereo: optional StereoCameraHandler — when given, the RIGHT
                (landscape/Gemini) lens is recorded to camera_right.avi.
        """
        self._camera = camera
        self._stereo = stereo

    def _capture_loop(self) -> None:
        """Pull frames from the camera at a steady video_fps, in real time.

        Runs in its own thread so the busy main loop can't starve the
        recording. Pacing is by wall-clock schedule: each iteration targets the
        next 1/video_fps tick, so the AVI frame count matches elapsed time and
        playback is true speed.
        """
        interval = 1.0 / self.video_fps if self.video_fps > 0 else 0.1
        next_tick = time.monotonic()
        while self._capture_running:
            now = time.monotonic()
            if now < next_tick:
                time.sleep(next_tick - now)
                continue
            next_tick = now + interval

            if not self.is_recording:
                continue

            # LEFT / primary lens
            if self._camera is not None and self.record_camera:
                try:
                    frame = self._camera.get_frame()
                except Exception:
                    frame = None
                if frame is not None:
                    self._write_frame_now(frame, side="left")

            # RIGHT / Gemini lens (stereo only)
            if self._stereo is not None and self.record_stereo_right:
                try:
                    rframe = self._stereo.get_right_frame()
                except Exception:
                    rframe = None
                if rframe is not None:
                    self._write_frame_now(rframe, side="right")

    def _write_frame_now(self, frame, side: str) -> None:
        """Write one frame immediately (called by the steady capture thread)."""
        with self._video_lock:
            if not self.is_recording:
                return
            if side == "left":
                if self._video_writer is None:
                    self._video_size = (int(frame.shape[1]), int(frame.shape[0]))
                    self._ensure_video_writer()
                if self._video_writer is None:
                    return
                if self._video_size != (int(frame.shape[1]), int(frame.shape[0])):
                    frame = cv2.resize(frame, self._video_size, interpolation=cv2.INTER_AREA)
                self._video_writer.write(frame)
                self._video_frame_count += 1
                self._last_video_write = time.time()
            else:
                if self._video_writer_right is None:
                    self._video_size_right = (int(frame.shape[1]), int(frame.shape[0]))
                    self._ensure_video_writer_right()
                if self._video_writer_right is None:
                    return
                if self._video_size_right != (int(frame.shape[1]), int(frame.shape[0])):
                    frame = cv2.resize(frame, self._video_size_right, interpolation=cv2.INTER_AREA)
                self._video_writer_right.write(frame)
                self._video_frame_count_right += 1
                self._last_video_write_right = time.time()

    def start(self, frame_shape: Optional[Tuple[int, int, int]] = None) -> bool:
        """Open a new recording session directory and prepare output files."""
        if not self.enabled:
            return False

        with self._state_lock:
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

            # Start the dedicated camera capture thread (real-time pacing).
            if self._camera is not None and self._capture_thread is None:
                self._capture_running = True
                self._capture_thread = threading.Thread(
                    target=self._capture_loop, name="av-recorder-capture", daemon=True
                )
                self._capture_thread.start()

            self._log_event("recording_started", session_dir=str(self.session_dir))
            logger.info(f"🎥 Session recorder started: {self.session_dir}")
            return True

    def stop(self) -> None:
        """Flush and close the active recording session."""
        with self._state_lock:
            if not self.is_recording:
                return

            self._log_event("recording_stopped")
            self.is_recording = False

            # Stop the dedicated capture thread.
            self._capture_running = False
            if self._capture_thread is not None:
                self._capture_thread.join(timeout=2.0)
                self._capture_thread = None

            if self._video_writer is not None:
                self._video_writer.release()
                self._video_writer = None

            if self._video_writer_right is not None:
                self._video_writer_right.release()
                self._video_writer_right = None

            # Reset real-time pacing state for the next session.
            self._video_first_ts = None
            self._video_first_ts_right = None
            self._video_frame_count = 0
            self._video_frame_count_right = 0

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
        """Legacy hook kept for backward compatibility.

        Video is now captured by the recorder's own thread (see _capture_loop),
        which pulls frames directly from the camera at a steady video_fps. When
        that thread is active this is a no-op so we never double-write. If no
        camera was attached (thread inactive), fall back to writing the frame
        the caller passed in.
        """
        if self._capture_thread is not None:
            return  # dedicated thread owns video capture
        if not self.is_recording or not self.record_camera or frame is None:
            return
        self._write_frame_now(frame, side="left")

    def write_video_frame_right(self, frame, timestamp: Optional[float] = None) -> None:
        """Write the RIGHT-lens (Gemini view) frame to its own video file.

        Records to ``camera_right.avi`` alongside the LEFT ``camera.avi``.
        No-op unless the recorder was built from a stereo camera (i.e.
        ``record_stereo_right`` is enabled) — when the system runs on the
        single-lens USB / CSI fallback this is simply never called.

        Like write_video_frame, this is a legacy hook: when the dedicated
        capture thread is active it owns the RIGHT lens too, so this no-ops.
        """
        if self._capture_thread is not None:
            return  # dedicated thread owns video capture
        if not self.is_recording or not self.record_stereo_right or frame is None:
            return
        self._write_frame_now(frame, side="right")

    def _ensure_video_writer_right(self) -> None:
        if self._video_writer_right is not None or self.session_dir is None or self._video_size_right is None:
            return

        video_path = self.session_dir / f"camera_right.{self.video_container}"
        fourcc = cv2.VideoWriter_fourcc(*self.video_codec)
        writer = cv2.VideoWriter(str(video_path), fourcc, self.video_fps, self._video_size_right)
        if writer is None or not writer.isOpened():
            logger.error(f"❌ Failed to open right-lens video writer: {video_path}")
            self._video_writer_right = None
            return
        self._video_writer_right = writer
        logger.info(f"🎥 Right-lens (Gemini) recording: {video_path}")

    def write_mic_audio(self, audio_bytes: bytes, sample_rate: int) -> None:
        """Append microphone PCM bytes to the session WAV file."""
        if not self.is_recording or not self.record_mic or not audio_bytes:
            return

        with self._audio_lock:
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

        with self._audio_lock:
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
        with self._events_lock:
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
        try:
            self._events_file.write(json.dumps(entry) + "\n")
            # M47 fix: catch the flush — on a full disk or
            # read-only mount the file write succeeds but flush()
            # raises BlockingIOError, which previously propagated
            # and killed the record loop. Silently logging the
            # failure is the right behaviour (recording continues,
            # event is lost) since dropping the event beats
            # dropping the entire session.
            self._events_file.flush()
        except (OSError, IOError) as e:
            # Don't crash the recording loop on a transient
            # disk error — just log and move on. The video +
            # audio streams are still being captured.
            logger.warning(
                f"SessionAVRecorder._log_event flush failed: {e}"
            )
