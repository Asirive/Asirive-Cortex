"""
Voice Coordinator Module
========================

Orchestrates Voice Activity Detection (Silero VAD) and Speech-to-Text (Whisper).
Part of the Production Mode pipeline for "Always On" voice commands.

Author: Haziq (@IRSPlays)
Date: January 17, 2026
"""

import logging
import asyncio
import numpy as np
from typing import Callable, Optional

from rpi5.layer1_reflex.vad_handler import VADHandler
from rpi5.layer1_reflex.whisper_handler import WhisperSTT

logger = logging.getLogger(__name__)

class VoiceCoordinator:
    """
    Coordinates VAD listening and Whisper transcription.
    Calls a callback with the transcribed text.
    """
    
    def __init__(self, on_command_detected: Callable[[str], None], config: Optional[dict] = None):
        """
        Args:
            on_command_detected: Async callback function(text: str) -> None
            config: Optional config dict (from config.yaml 'audio' section)
        """
        self.on_command_detected = on_command_detected
        self.config = config or {}
        self.vad = None
        self.stt = None
        self.is_active = False
        # Optional raw audio callback: fn(audio_bytes: bytes, sample_rate: int) -> None
        # Set this after init to forward PCM audio to GeminiLiveHandler (audio-to-audio path)
        self.on_raw_audio: Optional[Callable] = None
    
    @property
    def is_listening(self) -> bool:
        """Alias for is_active (compatibility with main.py)."""
        return self.is_active

    def initialize(self):
        """Initialize VAD and Whisper models"""
        try:
            # Read VAD config (with tuned defaults for noisy environments)
            vad_config = self.config.get('vad', {})
            vad_threshold = vad_config.get('threshold', 0.65)
            vad_min_speech = vad_config.get('min_speech_duration_ms', 400)
            vad_min_silence = vad_config.get('min_silence_duration_ms', 500)
            vad_padding = vad_config.get('padding_duration_ms', 200)
            
            # Initialize VAD with config-driven params
            self.vad = VADHandler(
                threshold=vad_threshold,
                min_speech_duration_ms=vad_min_speech,
                min_silence_duration_ms=vad_min_silence,
                padding_duration_ms=vad_padding,
                on_speech_end=self._on_speech_end
            )
            logger.info(
                f"VAD config: threshold={vad_threshold}, "
                f"min_speech={vad_min_speech}ms, min_silence={vad_min_silence}ms, "
                f"padding={vad_padding}ms"
            )
            if not self.vad.load_model():
                logger.error("Failed to load VAD model")
                
            # Initialize Whisper (base model for better accuracy on RPi5)
            whisper_model = self.config.get('whisper', {}).get('model_size', 'base')
            self.stt = WhisperSTT(model_size=whisper_model)
            if not self.stt.load_model():
                logger.error("Failed to load Whisper model")
                
            logger.info("Voice Coordinator Initialized")
        except Exception as e:
            logger.error(f"Voice Coordinator Init Failed: {e}", exc_info=True)

    def start(self):
        """Start listening loop (VAD)"""
        if not self.vad or not self.stt:
            logger.error("⚠️ Voice Coordinator not initialized")
            return

        if self.is_active:
            return

        logger.info("🎤 Starting Voice Coordinator (VAD Active)...")
        if self.vad.start_listening():
            self.is_active = True

    def stop(self):
        """Stop listening"""
        if self.vad and self.is_active:
            self.vad.stop_listening()
            self.is_active = False
            logger.info("🛑 Voice Coordinator Stopped")

    def _on_speech_end(self, audio: np.ndarray):
        """Callback from VAD when speech segment ends"""
        logger.info(f"🎤 Speech segment detected ({len(audio)} samples), transcribing...")

        # Forward raw PCM to GeminiLiveHandler (audio-to-audio path) if wired
        if self.on_raw_audio is not None:
            try:
                # Convert float32 [-1,1] to int16 PCM bytes at 16kHz
                pcm_bytes = (audio * 32767).astype(np.int16).tobytes()
                self.on_raw_audio(pcm_bytes, 16000)
            except Exception as e:
                logger.debug(f"Raw audio forwarding error: {e}")

        try:
            # Transcribe (this blocks the VAD thread momentarily, which is acceptable for single-user command flow)
            # Ideally offload to another thread, but WhisperSTT handles simple calls well.
            text = self.stt.transcribe(audio)
            
            if text and len(text.strip()) > 1:
                logger.info(f"🗣️ Transcribed: '{text}'")
                
                # Send to main system (async)
                if self.on_command_detected:
                    try:
                        # Use thread-safe async execution
                        try:
                            loop = asyncio.get_running_loop()
                            # Loop is running, use run_coroutine_threadsafe
                            asyncio.run_coroutine_threadsafe(self._dispatch_command(text), loop)
                        except RuntimeError:
                            # No running loop, safe to use asyncio.run()
                            asyncio.run(self._dispatch_command(text))
                    except Exception as e:
                        logger.error(f"❌ Error dispatching command: {e}")
            else:
                logger.debug("⚠️ Empty transcription or noise")
                
        except Exception as e:
            logger.error(f"❌ Transcription error: {e}")

    async def _dispatch_command(self, text: str):
        """Async dispatch wrapper"""
        try:
            # Check if callback is a coroutine
            if asyncio.iscoroutinefunction(self.on_command_detected):
                await self.on_command_detected(text)
            else:
                self.on_command_detected(text)
        except Exception as e:
            logger.error(f"❌ Error handling voice command: {e}")
