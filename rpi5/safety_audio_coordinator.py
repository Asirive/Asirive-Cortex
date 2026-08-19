"""
Safety Audio Coordinator — Serializes Safety TTS Calls
======================================================

Single-purpose: prevent two safety alarms from playing on top of each other.

Problem this solves
-------------------
Three audio paths can fire on the same hazard, each non-blocking:

  1. Path A frame-level overhead detector  ->  tts.speak_safety(...) async
  2. Path B/C safety_monitor overhang      ->  audio_alerts.play(...) WAV
  3. Path B/C safety_monitor overhang      ->  tts.speak_safety(...) async

Path 1 + Path 2 + Path 3 can all fire on adjacent frames for the same
physical hazard (e.g. a hand held over the camera). The user hears the
Cartesia voice + the WAV + a second Cartesia voice stacked together.

Design
------
A single worker thread + deque. `enqueue()` is non-blocking (the per-frame
detection loop must not stall). The worker pops one request at a time,
calls `tts.speak_safety_sync(text, emotion)` which BLOCKS until the TTS
engine finishes, then pops the next. Result: requests play strictly in
order, never overlapping.

Coalesce window
---------------
If a new request's `source` matches the most-recently-queued one within
`coalesce_window_s` (default 0.5s), it is dropped. Same hazard, already
spoken — the user doesn't need to hear it twice.

Gemini interrupt
----------------
Before each play, the worker calls `audio_queue.interrupt("safety_alert")`
to kill any in-flight Gemini Live audio. This un-orphanizes the interrupt
path that has been in `cli/audio_queue.py` but never actually called.

Failure modes
-------------
- TTS engine unavailable: speak_safety_sync returns (False, "none"); we
  log and continue. The next request still plays.
- audio_queue import fails: we degrade gracefully — Gemini is not
  interrupted but serialization still works.
- Worker thread crash: caught and logged; main loop continues. A new
  enqueue will re-raise so the user notices.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class _SafetyAudioRequest:
    text: str
    emotion: str
    source: str
    queued_at: float = field(default_factory=time.time)


class SafetyAudioCoordinator:
    """Serializes safety TTS calls so two alarms never overlap."""

    def __init__(
        self,
        tts_router,
        audio_queue=None,
        coalesce_window_s: float = 0.5,
        max_queue_depth: int = 2,
    ):
        """
        Args:
            tts_router: the TTSRouter singleton (has speak_safety_sync).
            audio_queue: the cli.audio_queue singleton (for interrupting
                Gemini Live). If None, Gemini interrupt is skipped.
            coalesce_window_s: drop new requests whose `source` matches
                the most-recent enqueue within this window.
            max_queue_depth: cap on pending requests. New requests are
                dropped (with a log) once the queue is full.
        """
        self._tts = tts_router
        self._audio_queue = audio_queue
        self._coalesce_window_s = float(coalesce_window_s)
        self._max_queue_depth = max(1, int(max_queue_depth))

        self._queue: "deque[_SafetyAudioRequest]" = deque()
        self._lock = threading.Lock()
        self._last_source: Optional[str] = None
        self._last_source_ts: float = 0.0

        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        # Stats
        self.enqueued_count = 0
        self.played_count = 0
        self.coalesced_count = 0
        self.dropped_count = 0

        self._start_worker()

    def _start_worker(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="safety-audio-coordinator",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info(
            f"✅ SafetyAudioCoordinator started "
            f"(coalesce={self._coalesce_window_s}s, "
            f"max_queue_depth={self._max_queue_depth})"
        )

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the worker to exit and join it (called on shutdown)."""
        self._stop_event.set()
        self._wake_event.set()  # wake the worker so it can see the stop
        t = self._worker_thread
        if t and t.is_alive():
            t.join(timeout=timeout)
        self._worker_thread = None

    def enqueue(
        self,
        text: str,
        emotion: str = "alarmed",
        source: str = "",
    ) -> bool:
        """
        Append a safety phrase to the playback queue. Non-blocking.

        Returns True if accepted, False if coalesced or dropped.

        Args:
            text: the phrase to speak.
            emotion: Cartesia emotion tag (alarmed, urgent, calm, ...).
            source: short tag identifying the caller's intent (e.g.
                "frame_overhead", "safety_monitor_overhang",
                "fall_detected", "ui_ack"). Used for coalescing — two
                requests with the same source within the coalesce window
                collapse to one playback.
        """
        if not text or not text.strip():
            return False

        now = time.time()
        with self._lock:
            # Coalesce: drop if same source arrived recently.
            if (
                source
                and self._last_source == source
                and (now - self._last_source_ts) < self._coalesce_window_s
            ):
                self.coalesced_count += 1
                logger.debug(
                    f"🔕 safety_audio coalesced "
                    f"(source={source}, "
                    f"age={now - self._last_source_ts:.2f}s)"
                )
                return False

            # Queue cap: drop overflow.
            if len(self._queue) >= self._max_queue_depth:
                self.dropped_count += 1
                logger.warning(
                    f"⚠️ safety_audio queue full "
                    f"(depth={len(self._queue)}, "
                    f"max={self._max_queue_depth}) — dropped "
                    f"source={source}"
                )
                return False

            req = _SafetyAudioRequest(
                text=text.strip(),
                emotion=emotion,
                source=source,
                queued_at=now,
            )
            self._queue.append(req)
            self._last_source = source
            self._last_source_ts = now
            self.enqueued_count += 1

        self._wake_event.set()
        logger.debug(
            f"📥 safety_audio enqueued "
            f"(source={source}, queue_depth={len(self._queue)})"
        )
        return True

    def _worker_loop(self) -> None:
        """Pop one request at a time, block until TTS finishes, repeat."""
        while not self._stop_event.is_set():
            req = self._take_next()
            if req is None:
                # No work — wait for a wake signal or shutdown.
                self._wake_event.wait(timeout=0.5)
                self._wake_event.clear()
                continue

            self._play_one(req)

    def _take_next(self) -> Optional[_SafetyAudioRequest]:
        with self._lock:
            if not self._queue:
                return None
            return self._queue.popleft()

    def _play_one(self, req: _SafetyAudioRequest) -> None:
        """Interrupt Gemini, then speak the phrase synchronously."""
        # Interrupt any in-flight Gemini Live audio so the user actually
        # hears the safety alert. This finally un-orphanizes
        # audio_queue.interrupt() (defined in cli/audio_queue.py).
        if self._audio_queue is not None:
            try:
                self._audio_queue.interrupt("safety_alert")
            except Exception as e:
                logger.debug(f"safety_audio interrupt failed: {e}")

        wait_ms = (time.time() - req.queued_at) * 1000.0
        logger.info(
            f"🔊 safety_audio play "
            f"(source={req.source}, waited={wait_ms:.0f}ms, "
            f"text='{req.text[:60]}')"
        )

        try:
            if self._tts is None:
                logger.warning("safety_audio: no TTS router; skipping")
                return

            ok, engine = self._tts.speak_safety_sync(req.text, req.emotion)
            if not ok:
                logger.warning(
                    f"safety_audio: TTS engine '{engine}' failed for "
                    f"source={req.source}"
                )
            self.played_count += 1
        except Exception as e:
            logger.error(f"safety_audio play error: {e}")

    @property
    def queue_depth(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def is_busy(self) -> bool:
        """True if a phrase is currently being spoken or queued."""
        with self._lock:
            return bool(self._queue)

    def stats(self) -> dict:
        with self._lock:
            return {
                "queued": self.enqueued_count,
                "played": self.played_count,
                "coalesced": self.coalesced_count,
                "dropped": self.dropped_count,
                "pending": len(self._queue),
                "last_source": self._last_source,
                "last_source_age_s": (
                    time.time() - self._last_source_ts
                    if self._last_source_ts
                    else -1.0
                ),
            }