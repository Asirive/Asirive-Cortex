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
        blocksize: int = 4800  # 200ms blocks @ 24kHz
    ):
        """
        Initialize streaming audio player.
        
        Args:
            sample_rate: Input PCM sample rate (24000 Hz from Gemini)
            channels: Number of audio channels (1 = mono)
            dtype: Audio data type ('int16' for PCM)
            device: Output device ID (None = default)
            blocksize: Audio block size in samples (4800 = 200ms @ 24kHz)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.device = device
        self.blocksize = blocksize
        
        # Audio queue (thread-safe)
        self.audio_queue = queue.Queue(maxsize=100)
        
        # Playback state
        self.is_playing = False
        self.is_interrupted = False
        self.stream: Optional[sd.OutputStream] = None
        self.playback_thread: Optional[threading.Thread] = None
        self._silence_count = 0  # Track consecutive silence callbacks
        self._chunks_played = 0  # Track total chunks played
        
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
        
        self.is_playing = True
        self.is_interrupted = False
        self._silence_count = 0
        self._chunks_played = 0
        
        # Clear audio queue
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
        
        # Start playback thread
        self.playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self.playback_thread.start()
        
        if self.on_start_callback:
            self.on_start_callback()
        
        logger.info("🔊 Audio playback started")
    
    def stop(self, interrupted: bool = False):
        """
        Stop audio playback.
        
        Args:
            interrupted: True if stopped by interruption (VAD trigger)
        """
        if not self.is_playing:
            return
        
        self.is_playing = False
        self.is_interrupted = interrupted
        
        # Clear audio queue
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
        
        # Wait for playback thread
        if self.playback_thread:
            self.playback_thread.join(timeout=2.0)
            self.playback_thread = None
        
        if interrupted and self.on_interrupt_callback:
            self.on_interrupt_callback()
        elif self.on_stop_callback:
            self.on_stop_callback()
        
        logger.info(f"🛑 Audio playback stopped (interrupted={interrupted})")
    
    def add_audio_chunk(self, audio_bytes: bytes):
        """
        Add audio chunk to playback queue.
        Auto-starts the player if not already playing.
        """
        if not self.is_playing:
            logger.info("🔊 Auto-starting audio player for incoming Gemini chunk")
            self.start()
        
        try:
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            self.audio_queue.put_nowait(audio_array)
            if self._chunks_played == 0 and self.audio_queue.qsize() == 1:
                logger.info(f"📥 First Gemini audio chunk queued: {len(audio_array)} samples")
            else:
                logger.debug(f"📥 Added {len(audio_array)} samples to queue (qsize={self.audio_queue.qsize()})")
        except queue.Full:
            logger.warning("⚠️ Audio queue full - dropping chunk")
        except Exception as e:
            logger.error(f"❌ Error adding audio chunk: {e}")
    
    def _playback_loop(self):
        """Background thread for audio playback."""
        try:
            # Open audio output stream
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                device=self.device,
                blocksize=self.blocksize,
                callback=self._audio_callback
            )
            
            self.stream.start()
            logger.info(f"🔊 Audio stream opened (rate={self.sample_rate}, blocksize={self.blocksize}, device={self.device})")
            
            # Keep thread alive while playing
            while self.is_playing:
                threading.Event().wait(0.5)
                # Periodic status log
                if self._chunks_played > 0 and self._chunks_played % 50 == 0:
                    logger.info(f"🔊 Audio player: {self._chunks_played} chunks played, qsize={self.audio_queue.qsize()}")
            
        except Exception as e:
            logger.error(f"❌ Audio playback error: {e}")
            self.is_playing = False
        finally:
            stream = self.stream
            self.stream = None
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception as e:
                    logger.debug(f"Stream cleanup in _playback_loop: {e}")
    
    def _audio_callback(self, outdata, frames, time_info, status):
        """
        Audio callback for sounddevice stream.
        
        Runs in audio thread — must be fast, no blocking, no logging.
        """
        if status:
            logger.warning(f"⚠️ Audio stream status: {status}")
        
        # Check for interruption
        if self.is_interrupted:
            outdata.fill(0)
            return
        
        # Get audio from queue
        try:
            audio_data = np.array([], dtype=np.int16)
            
            while len(audio_data) < frames and not self.audio_queue.empty():
                chunk = self.audio_queue.get_nowait()
                audio_data = np.concatenate([audio_data, chunk])
            
            if len(audio_data) >= frames:
                outdata[:] = audio_data[:frames].reshape(-1, self.channels)
                self._silence_count = 0
                self._chunks_played += 1
                
                # Put back remaining data
                if len(audio_data) > frames:
                    remaining = audio_data[frames:]
                    self.audio_queue.put_nowait(remaining)
            else:
                # Not enough data — pad with silence
                if len(audio_data) > 0:
                    outdata[:len(audio_data)] = audio_data.reshape(-1, self.channels)
                    outdata[len(audio_data):].fill(0)
                    self._silence_count = 0
                    self._chunks_played += 1
                else:
                    outdata.fill(0)
                    self._silence_count += 1
        
        except queue.Empty:
            outdata.fill(0)
            self._silence_count += 1
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
