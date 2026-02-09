"""
Cartesia Sonic 3 TTS Handler - Ultra-Low Latency Cloud TTS

Wrapper around the Cartesia Python SDK for Sonic 3 text-to-speech.
Designed for Layer 2 (Gemini vision responses) where natural voice
quality and low latency are critical for visually impaired users.

Key features:
- Industry-leading latency via Sonic 3 model
- WAV output at 24kHz pcm_s16le (matches Kokoro pipeline)
- Emotion control (default: calm for assistive device)
- Automatic .env key loading

Author: Haziq (@IRSPlays) + AI Implementer (Claude)
Date: February 7, 2026
Project: Cortex v2.0 - YIA 2026
"""

import logging
import os
import time
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Load .env for API key
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Lazy import — cartesia SDK
_cartesia_module = None


def _get_cartesia():
    """Lazy-load the cartesia module."""
    global _cartesia_module
    if _cartesia_module is None:
        try:
            import cartesia
            _cartesia_module = cartesia
        except ImportError:
            logger.error("cartesia package not installed. Run: pip install cartesia")
    return _cartesia_module


class CartesiaTTS:
    """
    Cartesia Sonic 3 TTS handler for ultra-low latency speech synthesis.
    
    Uses the Cartesia Python SDK to generate WAV audio from text.
    Singleton pattern to avoid re-initializing the client.
    
    Output format: WAV, 24kHz, pcm_s16le (mono) — matches Kokoro pipeline
    so existing playback code works unchanged.
    """
    
    _instance = None  # Singleton
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern — one instance across the app."""
        if cls._instance is None:
            cls._instance = super(CartesiaTTS, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: str = "sonic-3",
        voice_id: str = "f786b574-daa5-4673-aa0c-cbe3e8534c02",  # Katie
        language: str = "en",
        sample_rate: int = 24000,
        speed: float = 1.0,
        emotion: str = "calm",
    ):
        """
        Initialize Cartesia TTS handler.
        
        Args:
            api_key: Cartesia API key (falls back to CARTESIA_API_KEY env var)
            model_id: Sonic model ID (default: "sonic-3")
            voice_id: Voice ID (default: Katie — stable, realistic)
            language: Language code (default: "en")
            sample_rate: Audio sample rate (default: 24000 to match Kokoro)
            speed: Speech speed 0.6-1.5 (default: 1.0)
            emotion: Emotion preset (default: "calm" for assistive device)
        """
        if self._initialized:
            return
        
        self.api_key = api_key or os.getenv("CARTESIA_API_KEY")
        self.model_id = model_id
        self.voice_id = voice_id
        self.language = language
        self.sample_rate = sample_rate
        self.speed = speed
        self.emotion = emotion
        
        self.client = None
        self.available = False
        
        # Stats
        self.request_count = 0
        self.total_latency = 0.0
        self.error_count = 0
        
        # Audio output directory
        self.audio_dir = Path("temp_audio")
        self.audio_dir.mkdir(exist_ok=True)
        
        # Try to initialize client
        self._init_client()
        
        self._initialized = True
    
    def _init_client(self) -> bool:
        """Initialize the Cartesia client."""
        if not self.api_key:
            logger.warning("No CARTESIA_API_KEY found in .env — Cartesia TTS disabled")
            return False
        
        cartesia = _get_cartesia()
        if cartesia is None:
            return False
        
        try:
            self.client = cartesia.Cartesia(api_key=self.api_key)
            self.available = True
            logger.info(f"Cartesia Sonic 3 TTS initialized (voice: Katie, model: {self.model_id})")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Cartesia client: {e}")
            self.available = False
            return False
    
    def generate_speech(self, text: str) -> Optional[bytes]:
        """
        Generate WAV audio bytes from text using Cartesia Sonic 3.
        
        Uses the synchronous client.tts.bytes() API for simplicity.
        Returns complete WAV file bytes ready to play or save.
        
        Args:
            text: Text to synthesize
            
        Returns:
            WAV audio bytes, or None if failed
        """
        if not self.client or not self.available:
            if not self._init_client():
                return None
        
        if not text or not text.strip():
            return None
        
        start_time = time.time()
        self.request_count += 1
        
        try:
            logger.info(f"Cartesia TTS: generating speech ({len(text)} chars)...")
            
            # Build generation config for Sonic 3
            generation_config = {
                "speed": self.speed,
                "emotion": self.emotion,
            }
            
            # Call Cartesia TTS API — returns iterator of WAV chunks
            chunk_iter = self.client.tts.bytes(
                model_id=self.model_id,
                transcript=text,
                voice={
                    "mode": "id",
                    "id": self.voice_id,
                },
                language=self.language,
                output_format={
                    "container": "wav",
                    "sample_rate": self.sample_rate,
                    "encoding": "pcm_s16le",
                },
                generation_config=generation_config,
            )
            
            # Collect all chunks into a single WAV bytes object
            audio_bytes = b""
            for chunk in chunk_iter:
                audio_bytes += chunk
            
            latency = (time.time() - start_time) * 1000
            self.total_latency += latency
            
            if audio_bytes:
                logger.info(
                    f"Cartesia TTS: {len(audio_bytes)} bytes, "
                    f"{latency:.0f}ms latency"
                )
                return audio_bytes
            else:
                logger.warning("Cartesia TTS returned empty audio")
                self.error_count += 1
                return None
                
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            logger.error(f"Cartesia TTS error ({latency:.0f}ms): {e}")
            self.error_count += 1
            return None
    
    def save_to_file(
        self,
        text: str,
        output_path: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate speech and save to a WAV file.
        
        Args:
            text: Text to synthesize
            output_path: Path to save WAV file (auto-generated if None)
            
        Returns:
            Path to saved WAV file, or None if failed
        """
        audio_bytes = self.generate_speech(text)
        if not audio_bytes:
            return None
        
        if output_path is None:
            output_path = str(self.audio_dir / f"cartesia_{int(time.time())}.wav")
        
        try:
            with open(output_path, 'wb') as f:
                f.write(audio_bytes)
            logger.debug(f"Cartesia audio saved: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to save Cartesia audio: {e}")
            return None
    
    def get_stats(self) -> dict:
        """Get performance statistics."""
        avg_latency = (self.total_latency / self.request_count) if self.request_count > 0 else 0
        return {
            "engine": "cartesia_sonic3",
            "available": self.available,
            "requests": self.request_count,
            "errors": self.error_count,
            "avg_latency_ms": round(avg_latency, 1),
            "model": self.model_id,
            "voice": "Katie",
        }
