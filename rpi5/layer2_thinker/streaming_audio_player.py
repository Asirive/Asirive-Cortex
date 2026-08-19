"""
Streaming Audio Player for Gemini Live API
Project-Cortex v2.0 - Real-Time PCM Audio Playback

Replaces pygame with sounddevice for zero-latency streaming.
- No temp files (direct PCM playback)
- Real-time audio queue (async-safe)
- Interruption support (VAD integration)
- 24kHz PCM output (Gemini Live API format)

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: December 23, 2025
"""

import sounddevice as sd
import numpy as np
import logging
import threading
import queue
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class StreamingAudioPlayer:
    """
    Real-time PCM audio player for Gemini Live API responses.
    
    Features:
    - Zero-latency streaming (no file I/O)
    - Automatic resampling (24kHz → device sample rate)
    - Thread-safe audio queue
    - Interruption support (stop playback on VAD trigger)
    - Callback for playback events
    """
    
    def __init__(
        self,
        sample_rate: int = 24000,
        channels: int = 1,
        dtype: str = 'int16',
        device: Optional[int] = None,
        blocksize: int = 1200  # 50ms blocks @ 24kHz (was 4800=200ms — too laggy)
    ):
        """
        Initialize streaming audio player.

        Args:
            sample_rate: Input PCM sample rate (24000 Hz from Gemini)
            channels: Number of audio channels (1 = mono)
            dtype: Audio data type ('int16' for PCM)
            device: Output device ID (None = default)
            blocksize: Audio block size in samples. 1200 = 50ms @ 24kHz.
                Was 4800 (200ms) which made Gemini's first audio chunk
                take ~200ms to start playing. 50ms is the sweet spot for
                Bluetooth HSP/HFP output on RPi5 — low enough to feel
                realtime, high enough to avoid constant underflow.
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.device = device
        self.blocksize = blocksize
        
        # Audio queue (thread-safe) — large buffer for Gemini burst-mode audio
        self.audio_queue = queue.Queue(maxsize=500)

        # Playback state
        self.is_playing = False
        self.is_interrupted = False
        self.stream: Optional[sd.OutputStream] = None
        self.playback_thread: Optional[threading.Thread] = None
        self._stop_lock = threading.Lock()
        self._stop_in_progress = False
        self._silence_count = 0  # Track consecutive silence callbacks
        self._chunks_played = 0  # Track total chunks played
        self._last_logged_chunks = -1  # Prevent log spam at same chunk count
        self._leftover: Optional[np.ndarray] = None  # Leftover samples from previous callback
        self._queue_full_count = 0  # Debounce queue-full warnings
        self._silence_timeout = 5.0  # Auto-stop after N seconds of empty queue (was 8.0 — too long, user muted for 8+0.5s)
        self._drain_stop_delay = 0.35  # Stop quickly once Gemini explicitly ends the turn
        self._turn_complete = False
        # M-AUDIO-FIRST-CHUNK: bytes buffered while we wait for a
        # big-enough first chunk to start the player. Flushed on
        # stop() / turn_complete so we never lose the first
        # few samples of real audio. See add_audio_chunk() for the
        # threshold and rationale.
        self._pending_first_chunk: Optional[bytes] = None
        
        # Timestamp when playback last stopped (for echo cooldown)
        self._last_stop_time: float = 0.0
        
        # Callback for playback events
        self.on_start_callback: Optional[Callable] = None
        self.on_stop_callback: Optional[Callable] = None
        self.on_interrupt_callback: Optional[Callable] = None
        
        logger.info(f"✅ StreamingAudioPlayer initialized (rate={sample_rate}Hz, channels={channels})")
    
    def start(self):
        """Start audio playback thread."""
        if self.is_playing:
            logger.warning("⚠️ Audio player already playing")
            return
        
        # Prevent infinite thread spawning if audio device is broken
        if getattr(self, '_start_failure_count', 0) >= 5:
            logger.error("❌ Audio device permanently unavailable — giving up after 5 failures")
            return
        
        self.is_playing = True
        self.is_interrupted = False
        self._silence_count = 0
        self._chunks_played = 0
        self._leftover = None
        self._queue_full_count = 0
        self._turn_complete = False
        
        # Bump generation counter so old playback thread won't close our stream
        self._stream_generation = getattr(self, '_stream_generation', 0) + 1
        
        # Clear audio queue
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
        
        # Start playback thread
        self.playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self.playback_thread.start()
        
        # Notify audio queue that Gemini Live is now active
        try:
            from rpi5.cli.audio_queue import audio_queue, AudioSource
            audio_queue.mark_gemini_active(True)
        except Exception:
            pass
        
        if self.on_start_callback:
            self.on_start_callback()
        
        logger.info("🔊 Audio playback started")
    
    def stop(self, interrupted: bool = False):
        """
        Stop audio playback.
        
        Args:
            interrupted: True if stopped by interruption (VAD trigger)
        """
        with self._stop_lock:
            if self._stop_in_progress:
                return
            self._stop_in_progress = True

        try:
            if not self.is_playing:
                return

            # Set stop time BEFORE is_playing=False to prevent race condition
            # where another thread sees is_playing=False + stale _last_stop_time
            self._last_stop_time = time.time()
            self.is_playing = False
            self.is_interrupted = interrupted
            self._turn_complete = False

            # Clear audio queue and leftover buffer
            self._leftover = None
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break

            # Close audio stream
            stream = self.stream
            self.stream = None
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception as e:
                    logger.debug(f"Stream cleanup in stop(): {e}")

            # Wait for playback thread unless we're already on it
            if self.playback_thread and self.playback_thread is not threading.current_thread():
                self.playback_thread.join(timeout=2.0)
                self.playback_thread = None

            if interrupted and self.on_interrupt_callback:
                self.on_interrupt_callback()
            elif self.on_stop_callback:
                self.on_stop_callback()

            # Notify audio queue that Gemini Live is no longer active
            try:
                from rpi5.cli.audio_queue import audio_queue
                audio_queue.mark_gemini_active(False)
            except Exception:
                pass

            logger.info(f"🛑 Audio playback stopped (interrupted={interrupted})")
        finally:
            with self._stop_lock:
                self._stop_in_progress = False

    def request_stop(self, interrupted: bool = False):
        """Stop playback on a helper thread so callers do not block."""
        if not self.is_playing:
            return
        with self._stop_lock:
            if self._stop_in_progress:
                return
        threading.Thread(
            target=self.stop,
            args=(interrupted,),
            name="gemini-audio-stop",
            daemon=True,
        ).start()
    
    def add_audio_chunk(self, audio_bytes: bytes):
        """
        Add audio chunk to playback queue.
        Auto-starts the player if not already playing.

        M-AUDIO-FIRST-CHUNK: the very first chunk Gemini sends on a
        new turn is often 1–2 int16 samples (≈0.04–0.08 ms of audio
        at 24 kHz) — a metadata marker, not real speech. The old
        code auto-started the player on the first chunk of any size,
        which triggered the blocking PortAudio stream open (50–200 ms
        on Bluetooth). The user then heard ~50–200 ms of silence
        before the next chunk with actual audio arrived — which they
        reported as "the audio is cut off when I send another query
        immediately after the previous one".

        Fix: don't auto-start on a tiny first chunk. Buffer small
        first chunks in `_pending_first_chunk` and only call
        `start()` once the cumulative buffer crosses
        `MIN_FIRST_CHUNK_SAMPLES` (240 = 10 ms at 24 kHz) OR a
        second non-tiny chunk arrives. The buffer is flushed on
        turn_complete or `stop()` so we never lose audio.
        """
        # First-chunk buffering for the auto-start path. The
        # threshold matches ~10 ms of audio at 24 kHz — small enough
        # that the latency hit (~10 ms) is inaudible, but big enough
        # to skip the Gemini metadata-marker chunks.
        MIN_FIRST_CHUNK_SAMPLES = 240
        n_samples = len(audio_bytes) // 2  # int16 = 2 bytes/sample

        if not self.is_playing:
            # Buffer tiny first chunks instead of starting the
            # player. The actual audio follows within ~50 ms on a
            # healthy Gemini Live stream; we wait for either enough
            # samples to accumulate or turn_complete to fire.
            if (
                not getattr(self, "_pending_first_chunk", None)
                and n_samples < MIN_FIRST_CHUNK_SAMPLES
            ):
                # First tiny chunk — buffer it, don't start yet.
                self._pending_first_chunk = audio_bytes
                logger.debug(
                    f"⏳ Buffering tiny first chunk "
                    f"({n_samples} samples) — waiting for real audio"
                )
                return
            if getattr(self, "_pending_first_chunk", None):
                # We had a buffered first chunk and now have more
                # audio — concatenate and play. Either the second
                # chunk is big enough on its own, or the combined
                # buffer is.
                pending = self._pending_first_chunk
                self._pending_first_chunk = None
                combined = pending + audio_bytes
                if len(combined) // 2 < MIN_FIRST_CHUNK_SAMPLES:
                    # Still under threshold (rare — Gemini usually
                    # sends a flood of small chunks at the start of a
                    # turn). Re-buffer and wait for more.
                    self._pending_first_chunk = combined
                    return
                # Combined buffer is large enough — start the
                # player and queue the combined chunk.
                logger.debug(
                    f"🔊 Auto-starting audio player with combined "
                    f"first chunk ({len(combined) // 2} samples)"
                )
                self.start()
                try:
                    self._turn_complete = False
                    audio_array = np.frombuffer(combined, dtype=np.int16)
                    self.audio_queue.put_nowait(audio_array)
                except queue.Full:
                    self._queue_full_count += 1
                    if self._queue_full_count == 1:
                        logger.warning(
                            f"⚠️ Audio queue full "
                            f"(qsize={self.audio_queue.maxsize}) "
                            f"- dropping chunks"
                        )
                return
            # First chunk is already big enough — start normally.
            logger.debug("🔊 Auto-starting audio player for incoming Gemini chunk")
            self.start()

        try:
            self._turn_complete = False
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            self.audio_queue.put_nowait(audio_array)
            if self._chunks_played == 0 and self.audio_queue.qsize() == 1:
                logger.info(f"📥 First Gemini audio chunk queued: {len(audio_array)} samples")
            if self._queue_full_count > 0:
                logger.info(f"📥 Audio queue recovered after dropping {self._queue_full_count} chunks")
                self._queue_full_count = 0
        except queue.Full:
            self._queue_full_count += 1
            if self._queue_full_count == 1:
                logger.warning(f"⚠️ Audio queue full (qsize={self.audio_queue.maxsize}) - dropping chunks")
        except Exception as e:
            logger.error(f"❌ Error adding audio chunk: {e}")

    def mark_turn_complete(self):
        """Stop playback promptly once Gemini has finished sending audio for this turn."""
        if not self.is_playing:
            return
        self._turn_complete = True
        # Notify audio queue so queued TTS can start playing
        try:
            from rpi5.cli.audio_queue import audio_queue
            audio_queue.mark_gemini_turn_complete()
        except Exception:
            pass
        logger.info("🔊 Gemini turn complete — draining remaining audio")
    
    def _playback_loop(self):
        """Background thread for audio playback."""
        my_generation = self._stream_generation  # Capture at thread start
        try:
            # Open audio output stream
            # latency='low' asks PortAudio for the smallest buffer it can
            # safely negotiate with the hardware (typically 20-40ms on
            # Bluetooth HSP/HFP). Combined with blocksize=1200 (50ms),
            # the first Gemini audio chunk starts playing ~70ms after
            # arrival instead of the old ~250ms.
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                device=self.device,
                blocksize=self.blocksize,
                latency='low',
                callback=self._audio_callback
            )
            
            self.stream.start()
            logger.info(f"🔊 Audio stream opened (rate={self.sample_rate}, blocksize={self.blocksize}, device={self.device})")
            
            # Keep thread alive while playing, auto-stop on prolonged silence
            import time as _time
            silence_start = None
            while self.is_playing:
                threading.Event().wait(0.5)
                qsize = self.audio_queue.qsize()
                has_leftover = self._leftover is not None and len(self._leftover) > 0
                has_buffered_audio = qsize > 0 or has_leftover
                
                # Periodic status log (only when chunk count changes)
                if self._chunks_played > 0 and self._chunks_played % 50 == 0 and self._chunks_played != self._last_logged_chunks:
                    self._last_logged_chunks = self._chunks_played
                    logger.debug(f"🔊 Audio player: {self._chunks_played} chunks played, qsize={qsize}")

                if self._turn_complete:
                    if has_buffered_audio:
                        silence_start = None
                    else:
                        if silence_start is None:
                            silence_start = _time.time()
                        elif _time.time() - silence_start >= self._drain_stop_delay:
                            logger.info("🔇 Audio player stopping after Gemini turn completion")
                            self._last_stop_time = _time.time()
                            self.is_playing = False
                            break
                    continue
                
                # Auto-stop after silence timeout (queue drained, no new audio)
                # Also handles startup case where player was started but no audio ever arrived
                if qsize == 0:
                    if self._chunks_played > 0 or (silence_start is not None and _time.time() - silence_start >= self._silence_timeout):
                        if silence_start is None:
                            silence_start = _time.time()
                        elif _time.time() - silence_start >= self._silence_timeout:
                            logger.info(f"🔇 Audio player auto-stopping after {self._silence_timeout}s of silence")
                            self._last_stop_time = _time.time()
                            self.is_playing = False
                            break
                    elif silence_start is None:
                        silence_start = _time.time()
                else:
                    silence_start = None
            
        except Exception as e:
            logger.error(f"❌ Audio playback error: {e}")
            self._last_stop_time = time.time()
            self.is_playing = False
            self._start_failure_count = getattr(self, '_start_failure_count', 0) + 1
        finally:
            # Only close our own stream (generation check prevents race condition
            # where old thread closes a newly opened stream)
            if getattr(self, '_stream_generation', 0) == my_generation:
                stream = self.stream
                self.stream = None
                if stream:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception as e:
                        logger.debug(f"Stream cleanup in _playback_loop: {e}")
            else:
                logger.debug("Skipping stream cleanup — newer generation took over")
    
    def _audio_callback(self, outdata, frames, time_info, status):
        """
        Audio callback for sounddevice stream.
        
        Runs in audio thread — must be fast, no blocking, no logging.
        Uses self._leftover buffer to avoid put_nowait(remaining) failures.
        """
        if status:
            logger.warning(f"⚠️ Audio stream status: {status}")
        
        # Check for interruption
        if self.is_interrupted:
            outdata.fill(0)
            return
        
        # Build audio data: start from leftover, then pull from queue
        try:
            parts = []
            total = 0
            
            # Use leftover from previous callback first
            if self._leftover is not None and len(self._leftover) > 0:
                parts.append(self._leftover)
                total += len(self._leftover)
                self._leftover = None
            
            # Pull chunks from queue until we have enough
            while total < frames:
                try:
                    chunk = self.audio_queue.get_nowait()
                    parts.append(chunk)
                    total += len(chunk)
                except queue.Empty:
                    break
            
            if total == 0:
                outdata.fill(0)
                self._silence_count += 1
                return
            
            # Concatenate once (not in a loop)
            audio_data = np.concatenate(parts) if len(parts) > 1 else parts[0]
            
            if len(audio_data) >= frames:
                outdata[:] = audio_data[:frames].reshape(-1, self.channels)
                self._silence_count = 0
                self._chunks_played += 1
                
                # Store leftover in buffer (never put_nowait back to queue)
                if len(audio_data) > frames:
                    self._leftover = audio_data[frames:]
            else:
                # Not enough data — pad with silence
                outdata[:len(audio_data)] = audio_data.reshape(-1, self.channels)
                outdata[len(audio_data):].fill(0)
                self._silence_count = 0
                self._chunks_played += 1
        
        except Exception as e:
            logger.error(f"❌ Audio callback error: {e}")
            outdata.fill(0)
    
    def set_callbacks(
        self,
        on_start: Optional[Callable] = None,
        on_stop: Optional[Callable] = None,
        on_interrupt: Optional[Callable] = None
    ):
        """
        Set callback functions for playback events.
        
        Args:
            on_start: Called when playback starts
            on_stop: Called when playback stops normally
            on_interrupt: Called when playback is interrupted (VAD)
        """
        self.on_start_callback = on_start
        self.on_stop_callback = on_stop
        self.on_interrupt_callback = on_interrupt
    
    @property
    def queue_size(self) -> int:
        """Get current audio queue size."""
        return self.audio_queue.qsize()
    
    @property
    def is_queue_empty(self) -> bool:
        """Check if audio queue is empty."""
        return self.audio_queue.empty()


# Example usage (for testing)
if __name__ == "__main__":
    import time
    
    # Create player
    player = StreamingAudioPlayer(sample_rate=24000)
    
    # Set callbacks
    player.set_callbacks(
        on_start=lambda: print("🔊 Playback started"),
        on_stop=lambda: print("🛑 Playback stopped"),
        on_interrupt=lambda: print("⚠️ Playback interrupted")
    )
    
    # Generate test audio (sine wave)
    duration = 2.0  # seconds
    sample_rate = 24000
    frequency = 440.0  # A4 note
    
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio_array = np.sin(2 * np.pi * frequency * t) * 32767  # Scale to int16 range
    audio_array = audio_array.astype(np.int16)
    
    # Split into chunks
    chunk_size = 4800  # 200ms @ 24kHz
    chunks = [audio_array[i:i+chunk_size].tobytes() for i in range(0, len(audio_array), chunk_size)]
    
    # Play audio
    player.start()
    
    for chunk in chunks:
        player.add_audio_chunk(chunk)
        time.sleep(0.1)  # Simulate streaming delay
    
    # Wait for playback to finish
    time.sleep(3.0)
    
    player.stop()
    print("✅ Test complete")
