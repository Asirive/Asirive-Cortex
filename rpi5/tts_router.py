"""
TTS Router - Smart Text-to-Speech Routing
==========================================

Routes text to the appropriate TTS engine based on text length:
- Short text (<300 chars): Gemini 2.5 Flash TTS (cloud, natural voice)
- Long text (>=300 chars): Kokoro TTS (local, faster for long text)

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
Date: January 27, 2026
"""

import logging
import asyncio
from typing import Optional, Tuple, Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# TTS Engine imports (lazy loaded)
_gemini_tts = None
_kokoro_tts = None


def _get_gemini_tts():
    """Lazy load Gemini TTS handler."""
    global _gemini_tts
    if _gemini_tts is None:
        try:
            from rpi5.layer2_thinker.gemini_tts_handler import GeminiTTS
            _gemini_tts = GeminiTTS()
            logger.info("Loaded Gemini TTS")
        except Exception as e:
            logger.warning(f"Failed to load Gemini TTS: {e}")
    return _gemini_tts


def _get_kokoro_tts():
    """Lazy load Kokoro TTS handler."""
    global _kokoro_tts
    if _kokoro_tts is None:
        try:
            from rpi5.layer1_reflex.kokoro_handler import KokoroTTS
            _kokoro_tts = KokoroTTS()
            if not _kokoro_tts.load_pipeline():
                logger.warning("Kokoro TTS pipeline failed to load")
                _kokoro_tts = None
            else:
                logger.info("Loaded Kokoro TTS")
        except Exception as e:
            logger.warning(f"Failed to load Kokoro TTS: {e}")
    return _kokoro_tts


class TTSRouter:
    """
    Smart TTS router that selects the best TTS engine based on text length.
    
    Routing logic:
    - Short text (<300 chars): Gemini 2.5 Flash TTS (natural, cloud-based)
    - Long text (>=300 chars): Kokoro TTS (local, faster for long responses)
    - Fallback: If primary engine fails, use the other
    """
    
    _instance = None  # Singleton
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super(TTSRouter, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        length_threshold: int = 300,
        prefer_local: bool = False,
        audio_output_dir: str = "temp_audio"
    ):
        """
        Initialize TTS Router.
        
        Args:
            length_threshold: Character count threshold for switching to Kokoro
            prefer_local: If True, always use Kokoro (offline mode)
            audio_output_dir: Directory for temporary audio files
        """
        if self._initialized:
            return
            
        self.length_threshold = length_threshold
        self.prefer_local = prefer_local
        self.audio_output_dir = Path(audio_output_dir)
        self.audio_output_dir.mkdir(exist_ok=True)
        
        self._gemini_available = False
        self._kokoro_available = False
        
        self._initialized = True
        logger.info(f"TTSRouter initialized (threshold: {length_threshold} chars)")
    
    def initialize(self) -> Tuple[bool, bool]:
        """
        Pre-initialize both TTS engines.
        
        Returns:
            Tuple of (gemini_available, kokoro_available)
        """
        gemini = _get_gemini_tts()
        self._gemini_available = gemini is not None
        
        kokoro = _get_kokoro_tts()
        self._kokoro_available = kokoro is not None
        
        logger.info(f"TTS Engines: Gemini={self._gemini_available}, Kokoro={self._kokoro_available}")
        
        return self._gemini_available, self._kokoro_available
    
    def select_engine(self, text: str) -> str:
        """
        Select the appropriate TTS engine for the given text.
        
        Args:
            text: Text to synthesize
            
        Returns:
            "gemini" or "kokoro"
        """
        if self.prefer_local:
            return "kokoro"
        
        text_length = len(text)
        
        if text_length >= self.length_threshold:
            # Long text -> Kokoro (faster for long responses)
            return "kokoro"
        else:
            # Short text -> Gemini (more natural voice)
            return "gemini"
    
    async def speak_async(
        self,
        text: str,
        play_audio: bool = True,
        save_path: Optional[str] = None
    ) -> Tuple[bool, str, Optional[bytes]]:
        """
        Synthesize and optionally play text using the appropriate TTS engine.
        
        Args:
            text: Text to speak
            play_audio: If True, play audio immediately
            save_path: Optional path to save audio file
            
        Returns:
            Tuple of (success, engine_used, audio_bytes)
        """
        engine = self.select_engine(text)
        logger.info(f"TTS routing '{text[:50]}...' to {engine} ({len(text)} chars)")
        
        success = False
        audio_data = None
        
        try:
            if engine == "gemini":
                success, audio_data = await self._speak_gemini(text, play_audio, save_path)
                if not success:
                    logger.warning("Gemini TTS failed, falling back to Kokoro")
                    engine = "kokoro"
                    success, audio_data = await self._speak_kokoro(text, play_audio, save_path)
            else:
                success, audio_data = await self._speak_kokoro(text, play_audio, save_path)
                if not success:
                    logger.warning("Kokoro TTS failed, falling back to Gemini")
                    engine = "gemini"
                    success, audio_data = await self._speak_gemini(text, play_audio, save_path)
        
        except Exception as e:
            logger.error(f"TTS error: {e}")
        
        return success, engine, audio_data
    
    def speak(
        self,
        text: str,
        play_audio: bool = True,
        save_path: Optional[str] = None
    ) -> Tuple[bool, str, Optional[bytes]]:
        """
        Synchronous wrapper for speak_async.
        
        Args:
            text: Text to speak
            play_audio: If True, play audio immediately
            save_path: Optional path to save audio file
            
        Returns:
            Tuple of (success, engine_used, audio_bytes)
        """
        try:
            loop = asyncio.get_running_loop()
            # Already in async context, create task
            future = asyncio.run_coroutine_threadsafe(
                self.speak_async(text, play_audio, save_path),
                loop
            )
            return future.result(timeout=30)
        except RuntimeError:
            # No running loop, safe to use asyncio.run()
            return asyncio.run(self.speak_async(text, play_audio, save_path))
    
    async def _speak_gemini(
        self,
        text: str,
        play_audio: bool,
        save_path: Optional[str]
    ) -> Tuple[bool, Optional[bytes]]:
        """Use Gemini TTS to synthesize speech."""
        gemini = _get_gemini_tts()
        if not gemini:
            return False, None
        
        try:
            # GeminiTTS.generate_speech_from_text() returns path to saved audio file
            audio_path = await asyncio.to_thread(
                gemini.generate_speech_from_text, text
            )
            
            if audio_path:
                audio_data = None
                if save_path or not play_audio:
                    with open(audio_path, 'rb') as f:
                        audio_data = f.read()
                    if save_path:
                        import shutil
                        shutil.copy(audio_path, save_path)
                
                if play_audio:
                    # Play using sounddevice or system audio
                    await self._play_audio_file(audio_path)
                
                return True, audio_data
            
            return False, None
            
        except Exception as e:
            logger.error(f"Gemini TTS error: {e}")
            return False, None
    
    async def _speak_kokoro(
        self,
        text: str,
        play_audio: bool,
        save_path: Optional[str]
    ) -> Tuple[bool, Optional[bytes]]:
        """Use Kokoro TTS to synthesize speech."""
        kokoro = _get_kokoro_tts()
        if not kokoro:
            return False, None
        
        try:
            # KokoroTTS.generate_speech() returns audio samples (numpy array)
            audio_samples = kokoro.generate_speech(text)
            
            if audio_samples is not None:
                # Convert to WAV bytes
                import io
                import wave
                import numpy as np
                
                # Kokoro returns float32 [-1, 1] audio at 24kHz
                sample_rate = 24000
                
                # Normalize to int16
                audio_int16 = (audio_samples * 32767).astype(np.int16)
                
                # Create WAV in memory
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(audio_int16.tobytes())
                
                audio_data = wav_buffer.getvalue()
                
                if save_path:
                    with open(save_path, 'wb') as f:
                        f.write(audio_data)
                
                if play_audio:
                    await self._play_audio_samples(audio_samples, sample_rate)
                
                return True, audio_data
            
            return False, None
            
        except Exception as e:
            logger.error(f"Kokoro TTS error: {e}")
            return False, None
    
    async def _play_audio_file(self, audio_path: str):
        """Play an audio file using sounddevice."""
        try:
            import sounddevice as sd
            import soundfile as sf
            
            data, samplerate = sf.read(audio_path)
            sd.play(data, samplerate)
            sd.wait()  # Wait until audio finishes
            
        except Exception as e:
            logger.error(f"Audio playback error: {e}")
            # Fallback to system audio player
            import subprocess
            import platform
            
            if platform.system() == "Linux":
                subprocess.run(["aplay", audio_path], check=False)
            elif platform.system() == "Darwin":
                subprocess.run(["afplay", audio_path], check=False)
    
    async def _play_audio_samples(self, samples, sample_rate: int):
        """Play audio samples directly using sounddevice."""
        try:
            import sounddevice as sd
            
            sd.play(samples, sample_rate)
            sd.wait()
            
        except Exception as e:
            logger.error(f"Audio playback error: {e}")


# =============================================================================
# Convenience Functions
# =============================================================================

_router_instance: Optional[TTSRouter] = None


def get_tts_router() -> TTSRouter:
    """Get the singleton TTS router instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = TTSRouter()
    return _router_instance


def speak(text: str, play_audio: bool = True) -> bool:
    """
    Quick speak function using smart TTS routing.
    
    Args:
        text: Text to speak
        play_audio: If True, play audio immediately
        
    Returns:
        True if successful
    """
    router = get_tts_router()
    success, engine, _ = router.speak(text, play_audio)
    return success


async def speak_async(text: str, play_audio: bool = True) -> bool:
    """
    Async speak function using smart TTS routing.
    
    Args:
        text: Text to speak
        play_audio: If True, play audio immediately
        
    Returns:
        True if successful
    """
    router = get_tts_router()
    success, engine, _ = await router.speak_async(text, play_audio)
    return success


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    router = TTSRouter()
    
    # Test engine selection
    short_text = "I see 3 storage boxes and 1 person."
    long_text = "In front of you, I can see a complex scene. " * 10  # ~400 chars
    
    print(f"Short text ({len(short_text)} chars) -> {router.select_engine(short_text)}")
    print(f"Long text ({len(long_text)} chars) -> {router.select_engine(long_text)}")
    
    # Test actual synthesis if argument provided
    if len(sys.argv) > 1:
        test_text = " ".join(sys.argv[1:])
        print(f"\nSpeaking: '{test_text}'")
        
        async def test():
            router.initialize()
            success, engine, _ = await router.speak_async(test_text)
            print(f"Result: {'SUCCESS' if success else 'FAILED'} (engine: {engine})")
        
        asyncio.run(test())
