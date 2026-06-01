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
        self._gemini_active = False
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
        """Mark Gemini Live as actively speaking."""
        with self._lock:
            self._gemini_active = active
            if not active:
                self._gemini_turn_complete = True
    
    def mark_gemini_turn_complete(self):
        """Mark Gemini turn as complete — queued TTS can now play."""
        with self._lock:
            self._gemini_turn_complete = True
    
    def interrupt(self, reason: str = "safety_alert"):
        """
        Immediately stop current playback and clear queue.
        Used for safety alerts and user barge-in.
        """
        with self._lock:
            if self._on_interrupt_callback:
                try:
                    self._on_interrupt_callback(reason)
                except Exception:
                    pass
            self._current_source = None
            self._is_playing = False
            self._queue.clear()
            self.interrupt_count += 1
    
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
            # Safety alerts: bypass queue, immediately play
            if source == AudioSource.SAFETY_ALERT:
                self._queue.clear()  # clear lower-priority items
                self._current_source = None
                req = AudioRequest(
                    source=source,
                    audio_data=audio_data,
                    sample_rate=sample_rate,
                    is_continuous=False,
                    is_final_chunk=True,
                )
                self._queue.append(req)
                self.queued_count += 1
                return True
            
            # Drop TTS requests if Gemini is actively playing
            if source >= AudioSource.CARTESIA_TTS and self._gemini_active and not self._gemini_turn_complete:
                self.dropped_count += 1
                return False
            
            req = AudioRequest(
                source=source,
                audio_data=audio_data,
                sample_rate=sample_rate,
                is_continuous=is_continuous,
                is_final_chunk=is_final_chunk,
            )
            
            # Cap queue size
            if len(self._queue) >= 20:
                self.dropped_count += 1
                return False
            
            self._queue.append(req)
            self.queued_count += 1
            return True
    
    def next_request(self) -> Optional[AudioRequest]:
        """
        Get the next request that should play, respecting priority.
        
        Returns None if no playable request.
        """
        with self._lock:
            if not self._queue:
                return None
            
            # If Gemini is actively playing, don't return TTS requests
            if self._gemini_active and not self._gemini_turn_complete:
                for req in self._queue:
                    if req.source == AudioSource.GEMINI_LIVE:
                        self._queue.remove(req)
                        self._current_source = req.source
                        return req
                return None
            
            # Gemini turn complete — play next TTS request
            if self._gemini_turn_complete:
                for req in self._queue:
                    if req.source != AudioSource.GEMINI_LIVE:
                        self._queue.remove(req)
                        self._current_source = req.source
                        # If we played non-Gemini, reset the turn flag
                        if req.source != AudioSource.GEMINI_LIVE:
                            self._gemini_turn_complete = False
                        return req
                # Only Gemini chunks left, but turn is "complete"
                # let them drain
            
            # Default: pop highest priority
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
            "gemini_active": self._gemini_active,
        }


# Global singleton
audio_queue = AudioQueueManager()
