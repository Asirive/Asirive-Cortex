"""
Supertonic TTS Handler - On-Device Text-to-Speech

Lightning-fast, on-device TTS using Supertonic 3 (99M params, ONNX).
Outputs 44.1kHz audio, resampled to 24kHz for compatibility with
existing playback pipeline (Gemini Live, StreamingAudioPlayer).

Replaces Kokoro TTS across the codebase.

Key features:
- 99M parameters (vs Kokoro's larger model)
- 912 chars/sec on CPU (vs Kokoro's 104 chars/sec)
- 31 languages supported
- Zero network dependency (runs locally via ONNX)
- Auto-downloads model on first run (~400MB)

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import io
import logging
import wave
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_SUPERTONIC_AVAILABLE = False
try:
    from supertonic import TTS
    _SUPERTONIC_AVAILABLE = True
except ImportError:
    logger.warning("supertonic not installed. Run: pip install supertonic")


class SupertonicTTS:
    """
    On-device TTS using Supertonic 3.
    
    Singleton pattern to avoid reloading the model.
    Outputs float32 numpy arrays at 24kHz (resampled from 44.1kHz).
    """
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        voice: str = "M1",
        lang: str = "en",
        speed: float = 1.05,
        total_steps: int = 8,
        target_sample_rate: int = 24000,
    ):
        """
        Initialize Supertonic TTS handler.
        
        Args:
            voice: Voice name (M1-M5, F1-F5) or path to Voice Builder JSON
            lang: Language code (en, ko, ja, etc.) or "na" for auto-detect
            speed: Speech speed (0.7-2.0, default 1.05)
            total_steps: Quality steps (5=low, 8=medium, 12=high)
            target_sample_rate: Output sample rate (default 24000 for compatibility)
        """
        if self._initialized:
            return
        
        if not _SUPERTONIC_AVAILABLE:
            logger.error("Supertonic not available")
            self.available = False
            self._initialized = True
            return
        
        self.voice_name = voice
        self.lang = lang
        self.speed = speed
        self.total_steps = total_steps
        self.target_sample_rate = target_sample_rate
        self.source_sample_rate = 44100
        
        self.tts = None
        self.style = None
        self.available = False
        
        self._init_model()
        self._initialized = True
    
    def _init_model(self) -> bool:
        """Load Supertonic model and voice style."""
        try:
            logger.info(f"Loading Supertonic TTS (voice={self.voice_name}, lang={self.lang})...")
            self.tts = TTS(auto_download=True)
            self.style = self.tts.get_voice_style(voice_name=self.voice_name)
            self.available = True
            logger.info(f"✅ Supertonic TTS initialized (voice={self.voice_name})")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Supertonic: {e}")
            self.available = False
            return False
    
    def _resample(self, audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        """Resample audio from src_rate to dst_rate using linear interpolation."""
        if src_rate == dst_rate:
            return audio
        
        duration = len(audio) / src_rate
        num_samples = int(duration * dst_rate)
        indices = np.linspace(0, len(audio) - 1, num_samples)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
    
    def generate_speech(self, text: str) -> Optional[np.ndarray]:
        """
        Generate speech from text.
        
        Args:
            text: Text to synthesize
            
        Returns:
            float32 numpy array at target_sample_rate (24kHz), or None on failure
        """
        if not self.available or not self.tts:
            return None
        
        if not text or not text.strip():
            return None
        
        try:
            wav, duration = self.tts.synthesize(
                text=text,
                voice_style=self.style,
                total_steps=self.total_steps,
                speed=self.speed,
                lang=self.lang,
                verbose=False,
            )
            
            wav_1d = wav.squeeze()
            wav_resampled = self._resample(wav_1d, self.source_sample_rate, self.target_sample_rate)
            
            logger.debug(f"Supertonic: {len(text)} chars → {duration[0]:.2f}s audio")
            return wav_resampled
            
        except Exception as e:
            logger.error(f"Supertonic synthesis failed: {e}")
            return None
    
    def generate_wav_bytes(self, text: str) -> Optional[bytes]:
        """
        Generate WAV audio bytes from text.
        
        Args:
            text: Text to synthesize
            
        Returns:
            WAV bytes at target_sample_rate (24kHz, 16-bit mono), or None on failure
        """
        wav = self.generate_speech(text)
        if wav is None:
            return None
        
        try:
            pcm = (wav * 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.target_sample_rate)
                wf.writeframes(pcm.tobytes())
            return buf.getvalue()
        except Exception as e:
            logger.error(f"Failed to encode WAV: {e}")
            return None
    
    def save_to_file(self, text: str, output_path: str) -> bool:
        """
        Generate speech and save to WAV file.
        
        Args:
            text: Text to synthesize
            output_path: Path to save WAV file
            
        Returns:
            True if successful, False otherwise
        """
        wav_bytes = self.generate_wav_bytes(text)
        if wav_bytes is None:
            return False
        
        try:
            with open(output_path, "wb") as f:
                f.write(wav_bytes)
            logger.debug(f"Saved Supertonic audio: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save audio: {e}")
            return False
