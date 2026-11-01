"""
Cartesia Sonic 3.5 TTS Handler - Ultra-Low Latency Cloud TTS

Wrapper around the Cartesia Python SDK for Sonic 3.5 text-to-speech.
Designed for Layer 2 (Gemini vision responses) where natural voice
quality and low latency are critical for visually impaired users.

Key features:
- Industry-leading latency via Sonic 3.5 model
- WAV output at 24kHz pcm_s16le (matches Supertonic pipeline)
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
    Cartesia Sonic 3.5 TTS handler for ultra-low latency speech synthesis.
    
    Uses the Cartesia Python SDK to generate WAV audio from text.
    Singleton pattern to avoid re-initializing the client.
    
    Output format: WAV, 24kHz, pcm_s16le (mono) — matches Supertonic pipeline
    so existing playback code works unchanged.
    """
    
    _instance = None  # Singleton
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern — one instance across the app."""
        if cls._instance is None:
            cls._instance = super(CartesiaTTS, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    # FIX-SAFETY-VOICE-MALE: separate voice for safety alerts. The
    # conversational voice (Katie, female) is used for Gemini Live
    # replies. The safety voice is a strong, dependable male (Troy —
    # "designed for trust-building"). Using a different gender makes
    # safety alerts instantly distinguishable from conversational
    # speech without the user needing to interpret the words first,
    # which matters in the <100 ms warning window.
    DEFAULT_SAFETY_VOICE_ID = "726d5ae5-055f-4c3d-8355-d9677de68937"  # Troy - Fix It Man

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: str = "sonic-3.5",
        voice_id: str = "f786b574-daa5-4673-aa0c-cbe3e8534c02",  # Katie
        voice_id_safety: Optional[str] = None,
        language: str = "en",
        sample_rate: int = 24000,
        speed: float = 1.0,
        emotion: str = "calm",
    ):
        """
        Initialize Cartesia TTS handler.

        Args:
            api_key: Cartesia API key (falls back to CARTESIA_API_KEY env var)
            model_id: Sonic model ID (default: "sonic-3.5")
            voice_id: Conversational voice ID (default: Katie — stable, realistic)
            voice_id_safety: Safety voice ID (default: Troy — strong, dependable male)
            language: Language code (default: "en")
            sample_rate: Audio sample rate (default: 24000 to match Supertonic)
            speed: Speech speed 0.6-1.5 (default: 1.0)
            emotion: Emotion preset (default: "calm" for assistive device)
        """
        if self._initialized:
            return

        self.api_key = api_key or os.getenv("CARTESIA_API_KEY")
        self.model_id = model_id
        self.voice_id = voice_id
        self._voice_id_safety = voice_id_safety or self.DEFAULT_SAFETY_VOICE_ID
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
            logger.info(
                f"Cartesia Sonic 3.5 TTS initialized "
                f"(conversational: Katie, safety: Troy, model: {self.model_id})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Cartesia client: {e}")
            self.available = False
            return False
    
    def generate_speech(self, text: str) -> Optional[bytes]:
        """
        Generate WAV audio bytes from text using Cartesia Sonic 3.5.
        
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
            
            # Build generation config for Sonic 3.5
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

    def generate_speech_with_emotion(
        self,
        text: str,
        emotion: str = "alarmed",
        voice_id: Optional[str] = None,
    ) -> Optional[bytes]:
        """FIX-SAFETY-VOICE-COMMAND: synthesize with a per-call emotion
        override. Used by the safety-voice path in TTSRouter.speak_safety
        to get alarmed / panicked prosody for short safety phrases
        ("wall ahead", "camera blocked", "obstacle left"). The
        generate_speech() method uses the instance-level emotion which
        defaults to "calm" for the assistive UX — that's correct for
        conversational replies but too muted for a safety alert.
        Default emotion is "alarmed" — a valid Sonic 3.5 emotion. The
        previous default of "urgent" was NOT in the Sonic 3.5 enum
        and silently fell back to "calm" at runtime.

        FIX-SAFETY-VOICE-MALE: defaults to the safety voice
        (`_voice_id_safety`, Troy — a strong, dependable male) instead
        of the conversational voice (Katie — female). The safety
        voice is intentionally a different gender from Gemini Live
        (Zephyr, female) so the user can distinguish a safety alert
        from a conversational reply in the <100 ms warning window
        without parsing the words.
        """
        if not self.client or not self.available:
            if not self._init_client():
                return None
        if not text or not text.strip():
            return None

        # FIX-SAFETY-VOICE-MALE: use the safety voice by default. Allow
        # explicit override for callers that need the conversational
        # voice on the safety path (none today, but keeps the door
        # open).
        chosen_voice = voice_id or self._voice_id_safety

        start_time = time.time()
        self.request_count += 1
        try:
            # Validate emotion against the Sonic 3.5 enum. Bad values
            # cause the API to 400; fall back to the instance default.
            valid_emotions = {
                "neutral", "happy", "excited", "enthusiastic", "elated",
                "euphoric", "triumphant", "amazed", "surprised", "flirtatious",
                "curious", "content", "peaceful", "serene", "calm", "grateful",
                "affectionate", "trust", "sympathetic", "anticipation",
                "mysterious", "angry", "mad", "outraged", "frustrated",
                "agitated", "threatened", "disgusted", "contempt", "envious",
                "sarcastic", "ironic", "sad", "dejected", "melancholic",
                "disappointed", "hurt", "guilty", "bored", "tired", "rejected",
                "nostalgic", "wistful", "apologetic", "hesitant", "insecure",
                "confused", "resigned", "anxious", "panicked", "alarmed",
                "scared", "proud", "confident", "distant", "skeptical",
                "contemplative", "determined",
            }
            chosen_emotion = emotion if emotion in valid_emotions else self.emotion
            # Boost speed slightly for safety phrases — short, punchy
            # delivery reads as more urgent than slow speech.
            chosen_speed = min(1.2, max(0.6, 1.1))

            chunk_iter = self.client.tts.bytes(
                model_id=self.model_id,
                transcript=text,
                voice={"mode": "id", "id": chosen_voice},
                language=self.language,
                output_format={
                    "container": "wav",
                    "sample_rate": self.sample_rate,
                    "encoding": "pcm_s16le",
                },
                generation_config={
                    "speed": chosen_speed,
                    "emotion": chosen_emotion,
                },
            )
            audio_bytes = b""
            for chunk in chunk_iter:
                audio_bytes += chunk
            latency = (time.time() - start_time) * 1000
            self.total_latency += latency
            if audio_bytes:
                logger.info(
                    f"Cartesia safety TTS: {len(audio_bytes)} bytes, "
                    f"{latency:.0f}ms latency, emotion={chosen_emotion}, "
                    f"voice={chosen_voice[:8]}"
                )
                return audio_bytes
            self.error_count += 1
            return None
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            logger.error(f"Cartesia safety TTS error ({latency:.0f}ms): {e}")
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
            "engine": "cartesia_sonic35",
            "available": self.available,
            "requests": self.request_count,
            "errors": self.error_count,
            "avg_latency_ms": round(avg_latency, 1),
            "model": self.model_id,
            "voice": "Katie",
            "voice_safety": "Troy",
        }
