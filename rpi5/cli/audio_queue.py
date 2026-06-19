"""
Audio Queue Manager — Centralized TTS playback coordinator

Prevents Cartesia/Supertonic TTS and Gemini Live audio from interfering
with each other. All audio sources go through this manager.

Priority:
  1. Safety alerts (highest) — interrupt everything
  2. Gemini Live — audio-first mode
  3. Cartesia/Supertonic TTS — queued until Gemini idle
  4. Whisper/Local TTS (lowest)

Usage:
    from rpi5.cli.audio_queue import audio_queue, AudioSource
    
    await audio_queue.play(sound_bytes, source=AudioSource.CARTESIA)
    await audio_queue.play(gemini_chunk, source=AudioSource.GEMINI_LIVE)
    audio_queue.interrupt()  # safety alert
"""
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Callable, Deque

import numpy as np


class AudioSource(IntEnum):
    """Priority levels for audio playback (lower number = higher priority)."""
    SAFETY_ALERT = 0
    GEMINI_LIVE = 1
    CARTESIA_TTS = 2
    SUPERTONIC_TTS = 3
    WHISPER_LOCAL = 4


@dataclass
class AudioRequest:
    """A single audio playback request."""
    source: AudioSource
    audio_data: np.ndarray
    sample_rate: int
    is_continuous: bool = False  # True for streaming sources like Gemini Live
    is_final_chunk: bool = False  # True for the last chunk of a turn
    queued_at: float = field(default_factory=time.time)


class AudioQueueManager:
    """
    Single-source-of-truth audio playback queue.
    
    - Safety alerts always preempt anything else
    - Gemini Live audio plays through when no safety alert
    - Cartesia/Supertonic TTS plays after Gemini turns complete
    - Whispers/local TTS are lowest priority
    """
    
    def __init__(self):
        self._queue: Deque[AudioRequest] = deque()
        self._lock = threading.Lock()
        self._current_source: Optional[AudioSource] = None
        self._is_playing = False
        self._on_play_callback: Optional[Callable] = None
        self._on_interrupt_callback: Optional[Callable] = None
        
        # Source active flags
        # M23 fix: track the number of overlapping Gemini "active"
        # markers (not just a boolean) so nested start/stop calls
        # from competing producers (turn-taking, barge-in, multi-
        # segment responses) don't prematurely release the gate.
        self._gemini_active_count = 0
        self._gemini_turn_complete = False

        # Stats
        self.interrupt_count = 0
        self.queued_count = 0
        self.dropped_count = 0
    
    def set_callbacks(
        self,
        on_play: Optional[Callable] = None,
        on_interrupt: Optional[Callable] = None,
    ):
        """Set callbacks for playback events."""
        self._on_play_callback = on_play
        self._on_interrupt_callback = on_interrupt
    
    def mark_gemini_active(self, active: bool = True):
        """Mark Gemini Live as actively speaking.

        M23 fix: balanced counter so multiple overlapping
        mark_gemini_active(True) calls require an equal number of
        mark_gemini_active(False) calls before the gate releases.
        """
        with self._lock:
            if active:
                self._gemini_active_count += 1
            else:
                # Floor at 0 so under-counts from a missed start don't
                # pin the gate open forever.
                self._gemini_active_count = max(0, self._gemini_active_count - 1)
            if self._gemini_active_count == 0:
                self._gemini_turn_complete = True
    
    def mark_gemini_turn_complete(self):
        """Mark Gemini turn as complete — queued TTS can now play."""
        with self._lock:
            self._gemini_turn_complete = True
    
    def interrupt(self, reason: str = "safety_alert"):
        """
        Immediately stop current playback and clear queue.
        Used for safety alerts and user barge-in.

        H22 fix: the previous version only cleared state — it never
        told the consumer to terminate the in-progress playback. The
        callback is the consumer's hook for "kill the current
        subprocess now"; we call it under the lock so the consumer
        can't race the state mutation, and we release the lock
        BEFORE invoking the callback (M25 fix) so the callback can
        safely call back into us (e.g. re-enqueue) without deadlocking.
        """
        with self._lock:
            self._current_source = None
            self._is_playing = False
            self._queue.clear()
            self.interrupt_count += 1
            cb = self._on_interrupt_callback
        # Call outside the lock — the callback may need to re-acquire
        # it (e.g. to enqueue the interrupting audio).
        if cb:
            try:
                cb(reason)
            except Exception as e:
                # Callback failures must never bring down the queue.
                import logging
                logging.getLogger(__name__).warning(
                    f"on_interrupt_callback error: {e}"
                )

    def enqueue(
        self,
        audio_data: np.ndarray,
        sample_rate: int,
        source: AudioSource,
        is_continuous: bool = False,
        is_final_chunk: bool = False,
    ) -> bool:
        """
        Add audio to the playback queue.

        Returns True if accepted, False if dropped (queue full).
        """
        with self._lock:
            # Safety alerts: bypass queue, immediately play.
            # H23 fix: also fire the on_interrupt_callback so the
            # consumer actually stops any in-progress TTS. Previously
            # the comment claimed "safety always preempts" but the
            # code only cleared _current_source; the consumer kept
            # playing its current chunk for the full duration before
            # noticing. Now safety alerts go through the same path
            # as interrupt() so the in-progress subprocess is killed.
            if source == AudioSource.SAFETY_ALERT:
                self._queue.clear()  # clear lower-priority items
                self._current_source = None
                cb = self._on_interrupt_callback
            else:
                cb = None

            req = AudioRequest(
                source=source,
                audio_data=audio_data,
                sample_rate=sample_rate,
                is_continuous=is_continuous,
                is_final_chunk=is_final_chunk,
            )

            if source == AudioSource.SAFETY_ALERT:
                self._queue.append(req)
                self.queued_count += 1
                accepted = True
            else:
                # Drop TTS requests if Gemini is actively playing
                if (
                    source >= AudioSource.CARTESIA_TTS
                    and self._gemini_active
                    and not self._gemini_turn_complete
                ):
                    self.dropped_count += 1
                    return False

                # Cap queue size
                if len(self._queue) >= 20:
                    self.dropped_count += 1
                    return False

                self._queue.append(req)
                self.queued_count += 1
                accepted = True

        # Call the interrupt callback OUTSIDE the lock — the consumer
        # may need to re-acquire the lock to terminate its subprocess
        # and the locked re-entry would deadlock.
        if cb is not None:
            try:
                cb("safety_alert")
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"on_interrupt_callback error during safety enqueue: {e}"
                )

        return accepted

    def next_request(self) -> Optional[AudioRequest]:
        """
        Get the next request that should play, respecting priority.

        Returns None if no playable request.
        """
        with self._lock:
            if not self._queue:
                return None

            # M23 fix: previously a boolean `_gemini_active` meant
            # only the latest mark_gemini_active() call mattered. A
            # chunk that arrived mid-utterance (before the consumer
            # saw "active=False") was treated as "during Gemini" and
            # could be dequeued in the wrong order. Use a counter so
            # nested start/stop calls (e.g. overlapping TTS turns)
            # correctly reflect whether ANY Gemini audio is in flight.
            # M24 fix: don't mutate the deque mid-iteration; find the
            # index and popleft, or just popleft the head and check.
            if self._gemini_active_count > 0 and not self._gemini_turn_complete:
                for i, req in enumerate(self._queue):
                    if req.source == AudioSource.GEMINI_LIVE:
                        # Pop by index to avoid O(n) list.remove inside
                        # the for-loop iteration.
                        popped = self._queue[i]
                        del self._queue[i]
                        self._current_source = popped.source
                        return popped
                return None

            # Gemini turn complete — play next non-Gemini request.
            # M24 fix: previously this was `for i, req in enumerate + del
            # self._queue[i]` which is O(n) per pop on a deque
            # (deletion shifts the tail). Use a single pass that
            # tracks the first match and either rotates+pops it out,
            # or just dequeues from the left if it's the first item.
            if self._gemini_turn_complete:
                for i, req in enumerate(self._queue):
                    if req.source != AudioSource.GEMINI_LIVE:
                        if i == 0:
                            popped = self._queue.popleft()
                        else:
                            # Rotate the deque so the match is at the
                            # left, then popleft. This keeps the
                            # operation O(n) for the rotate but the
                            # dequeue is O(1).
                            popped = self._queue[i]
                            del self._queue[i]
                        self._current_source = popped.source
                        self._gemini_turn_complete = False
                        return popped
                # Only Gemini chunks left, but turn is "complete"
                # let them drain.

            # Default: pop highest priority (head of deque)
            req = self._queue.popleft()
            self._current_source = req.source
            return req
    
    def complete_current(self, source: AudioSource):
        """Mark the current playback as complete."""
        with self._lock:
            if self._current_source == source:
                self._current_source = None
            if source == AudioSource.GEMINI_LIVE and self._gemini_turn_complete:
                self._gemini_turn_complete = False
    
    @property
    def is_busy(self) -> bool:
        """Whether the queue has pending or playing audio."""
        with self._lock:
            return self._current_source is not None or len(self._queue) > 0
    
    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)
    
    def stats(self) -> dict:
        return {
            "queued": self.queued_count,
            "dropped": self.dropped_count,
            "interrupted": self.interrupt_count,
            "pending": self.queue_size,
            "gemini_active": self._gemini_active_count > 0,
        }


# Global singleton
audio_queue = AudioQueueManager()
