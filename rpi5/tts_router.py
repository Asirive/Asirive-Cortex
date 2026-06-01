"""
TTS Router - Smart Text-to-Speech Routing
==========================================

Routes text to the appropriate TTS engine based on text length:
- Short text (<300 chars): Gemini 2.5 Flash TTS (cloud, natural voice)
- Long text (>=300 chars): Supertonic TTS (local, ONNX, faster for long text)

Auto-saves every TTS output as a pristine .wav file to tts_recordings/
for video editing (mute camera audio, drag in the .wav).

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
Date: January 27, 2026
"""

import logging
import asyncio
import time
import re
import threading
from typing import Optional, Tuple, Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# TTS Engine imports (lazy loaded)
_gemini_tts = None
_supertonic_tts = None


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


def _get_supertonic_tts():
    """Lazy load Supertonic TTS handler."""
    global _supertonic_tts
    if _supertonic_tts is None:
        try:
            from rpi5.layer1_reflex.supertonic_handler import SupertonicTTS
            _supertonic_tts = SupertonicTTS()
            if not _supertonic_tts.available:
                logger.warning("Supertonic TTS not available")
                _supertonic_tts = None
            else:
                logger.info("Loaded Supertonic TTS")
        except Exception as e:
            logger.warning(f"Failed to load Supertonic TTS: {e}")
    return _supertonic_tts


_cartesia_tts = None


def _get_cartesia_tts():
    """Lazy load Cartesia Sonic 3.5 TTS handler."""
    global _cartesia_tts
    if _cartesia_tts is None:
        try:
            from rpi5.layer2_thinker.cartesia_handler import CartesiaTTS
            _cartesia_tts = CartesiaTTS()
            if _cartesia_tts.available:
                logger.info("Loaded Cartesia Sonic 3.5 TTS")
            else:
                _cartesia_tts = None
        except Exception as e:
            logger.warning(f"Failed to load Cartesia TTS: {e}")
    return _cartesia_tts


class TTSRouter:
    """
    Smart TTS router that selects the best TTS engine based on text length.
    
    Routing logic:
    - Short text (<300 chars): Gemini 2.5 Flash TTS (natural, cloud-based)
    - Long text (>=300 chars): Supertonic TTS (local, ONNX, faster for long responses)
    - Cartesia Sonic 3.5: Ultra-low latency cloud TTS for Layer 2 (via engine_override)
    - Fallback: If primary engine fails, use the other
    
    Engine override options: "gemini", "supertonic", "cartesia"
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
            length_threshold: Character count threshold for switching to Supertonic
            prefer_local: If True, always use Supertonic (offline mode)
            audio_output_dir: Directory for temporary audio files
        """
        if self._initialized:
            return
            
        self.length_threshold = length_threshold
        self.prefer_local = prefer_local
        self.audio_output_dir = Path(audio_output_dir)
        self.audio_output_dir.mkdir(exist_ok=True)
        
        # TTS recordings directory — pristine .wav files for video editing
        self.recordings_dir = Path("tts_recordings")
        self.recordings_dir.mkdir(exist_ok=True)
        self._recording_counter = 0  # Sequential numbering for easy sorting
        
        self._gemini_available = False
        self._supertonic_available = False
        self._cartesia_available = False
        self._playback_lock = threading.Lock()
        self._active_playbacks = 0
        
        self._initialized = True
        logger.info(f"TTSRouter initialized (threshold: {length_threshold} chars)")
        logger.info(f"TTS recordings will be saved to: {self.recordings_dir.absolute()}")

    @property
    def is_playing(self) -> bool:
        """Return True while any local TTS playback is active."""
        with self._playback_lock:
            return self._active_playbacks > 0

    def _mark_playback_start(self):
        with self._playback_lock:
            self._active_playbacks += 1

    def _mark_playback_end(self):
        with self._playback_lock:
            self._active_playbacks = max(0, self._active_playbacks - 1)
    
    def _save_recording(self, audio_data: bytes, engine: str, text: str):
        """
        Save a pristine copy of TTS audio for video editing.
        
        Files are saved as: tts_recordings/NNN_engine_textsnippet.wav
        A companion .txt file stores the full text for reference.
        
        Args:
            audio_data: WAV audio bytes
            engine: Engine name ("supertonic", "cartesia", "gemini")
            text: Full text that was spoken
        """
        try:
            self._recording_counter += 1
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            
            # Sanitize text for filename (keep only alphanum + spaces, truncate)
            safe_text = re.sub(r'[^a-zA-Z0-9 ]', '', text)[:40].strip().replace(' ', '_')
            if not safe_text:
                safe_text = "response"
            
            basename = f"{self._recording_counter:04d}_{timestamp}_{engine}_{safe_text}"
            wav_path = self.recordings_dir / f"{basename}.wav"
            txt_path = self.recordings_dir / f"{basename}.txt"
            
            # Save pristine WAV
            with open(wav_path, 'wb') as f:
                f.write(audio_data)
            
            # Save companion text file (full text + metadata)
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(f"Engine: {engine}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Text length: {len(text)} chars\n")
                f.write(f"Audio size: {len(audio_data)} bytes\n")
                f.write(f"---\n")
                f.write(text)
            
            logger.info(f"TTS recording saved: {wav_path.name} ({len(audio_data)} bytes)")
        except Exception as e:
            logger.warning(f"Failed to save TTS recording: {e}")
    
    def initialize(self) -> Tuple[bool, bool]:
        """
        Pre-initialize all TTS engines.
        
        Returns:
            Tuple of (gemini_available, supertonic_available)
        """
        gemini = _get_gemini_tts()
        self._gemini_available = gemini is not None
        
        supertonic = _get_supertonic_tts()
        self._supertonic_available = supertonic is not None
        
        cartesia = _get_cartesia_tts()
        self._cartesia_available = cartesia is not None
        
        logger.info(f"TTS Engines: Gemini={self._gemini_available}, Supertonic={self._supertonic_available}, Cartesia={self._cartesia_available}")
        
        return self._gemini_available, self._supertonic_available
    
    def select_engine(self, text: str) -> str:
        """
        Select the appropriate TTS engine for the given text.
        
        Args:
            text: Text to synthesize
            
        Returns:
            "cartesia", "supertonic", or "gemini"
        """
        if self.prefer_local:
            return "supertonic"
        
        # Primary: Cartesia Sonic 3.5 (lowest latency cloud TTS)
        if self._cartesia_available:
            return "cartesia"
        
        text_length = len(text)
        
        if text_length >= self.length_threshold:
            # Long text -> Supertonic (faster for long responses, local)
            return "supertonic"
        else:
            # Short text -> Gemini (more natural voice)
            return "gemini"
    
    async def speak_async(
        self,
        text: str,
        play_audio: bool = True,
        save_path: Optional[str] = None,
        engine_override: Optional[str] = None
    ) -> Tuple[bool, str, Optional[bytes]]:
        """
        Synthesize and optionally play text using the appropriate TTS engine.
        
        Args:
            text: Text to speak
            play_audio: If True, play audio immediately
            save_path: Optional path to save audio file
            engine_override: Force a specific engine ("gemini", "supertonic", or "cartesia"),
                             bypassing the automatic selection logic.
            
        Returns:
            Tuple of (success, engine_used, audio_bytes)
        """
        engine = engine_override or self.select_engine(text)
        logger.info(f"TTS routing '{text[:50]}...' to {engine} ({len(text)} chars)")
        
        success = False
        audio_data = None
        
        try:
            if engine == "cartesia":
                success, audio_data = await self._speak_cartesia(text, play_audio, save_path)
                if not success:
                    logger.warning("Cartesia TTS failed, falling back to Supertonic")
                    engine = "supertonic"
                    success, audio_data = await self._speak_supertonic(text, play_audio, save_path)
                    if not success:
                        logger.warning("Supertonic TTS also failed, falling back to Gemini")
                        engine = "gemini"
                        success, audio_data = await self._speak_gemini(text, play_audio, save_path)
            elif engine == "gemini":
                success, audio_data = await self._speak_gemini(text, play_audio, save_path)
                if not success:
                    logger.warning("Gemini TTS failed, falling back to Supertonic")
                    engine = "supertonic"
                    success, audio_data = await self._speak_supertonic(text, play_audio, save_path)
            else:
                success, audio_data = await self._speak_supertonic(text, play_audio, save_path)
                if not success:
                    logger.warning("Supertonic TTS failed, falling back to Gemini")
                    engine = "gemini"
                    success, audio_data = await self._speak_gemini(text, play_audio, save_path)
        
        except Exception as e:
            logger.error(f"TTS error: {e}")
        
        # Auto-save pristine recording for video editing
        if success and audio_data:
            self._save_recording(audio_data, engine, text)
        
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
    
    async def _speak_supertonic(
        self,
        text: str,
        play_audio: bool,
        save_path: Optional[str]
    ) -> Tuple[bool, Optional[bytes]]:
        """Use Supertonic TTS to synthesize speech."""
        supertonic = _get_supertonic_tts()
        if not supertonic:
            return False, None
        
        try:
            # SupertonicTTS.generate_wav_bytes() returns WAV bytes at 24kHz
            audio_bytes = await asyncio.to_thread(supertonic.generate_wav_bytes, text)
            
            if audio_bytes:
                if save_path:
                    with open(save_path, 'wb') as f:
                        f.write(audio_bytes)
                
                if play_audio:
                    # Save to temp file and play via paplay
                    temp_path = str(self.audio_output_dir / "supertonic_temp.wav")
                    with open(temp_path, 'wb') as f:
                        f.write(audio_bytes)
                    await self._play_audio_file(temp_path)
                
                return True, audio_bytes
            
            return False, None
            
        except Exception as e:
            logger.error(f"Supertonic TTS error: {e}")
            return False, None
    
    async def _speak_cartesia(
        self,
        text: str,
        play_audio: bool,
        save_path: Optional[str]
    ) -> Tuple[bool, Optional[bytes]]:
        """Use Cartesia Sonic 3.5 TTS to synthesize speech."""
        cartesia = _get_cartesia_tts()
        if not cartesia:
            return False, None
        
        try:
            # CartesiaTTS.generate_speech() returns WAV bytes directly
            audio_bytes = await asyncio.to_thread(cartesia.generate_speech, text)
            
            if audio_bytes:
                if save_path:
                    with open(save_path, 'wb') as f:
                        f.write(audio_bytes)
                
                if play_audio:
                    # Save to temp file and play via sounddevice
                    temp_path = str(self.audio_output_dir / "cartesia_temp.wav")
                    with open(temp_path, 'wb') as f:
                        f.write(audio_bytes)
                    await self._play_audio_file(temp_path)
                
                return True, audio_bytes
            
            return False, None
            
        except Exception as e:
            logger.error(f"Cartesia TTS error: {e}")
            return False, None
    
    async def _play_audio_file(self, audio_path: str):
        """Play an audio file via paplay (Linux/PipeWire) or sounddevice (fallback).
        
        On Linux (RPi5), uses paplay (PipeWire-aware) so audio routes through
        the correct BT default sink set by BluetoothAudioManager.
        """
        import platform
        self._mark_playback_start()
        if platform.system() == "Linux":
            import subprocess
            try:
                await asyncio.to_thread(
                    subprocess.run, ["paplay", audio_path],
                    check=False, timeout=30
                )
            except Exception as e:
                logger.error(f"paplay error: {e}")
            finally:
                self._mark_playback_end()
            return
        
        # Non-Linux fallback
        try:
            import sounddevice as sd
            import soundfile as sf
            data, samplerate = sf.read(audio_path)
            sd.play(data, samplerate)
            sd.wait()
        except Exception as e:
            logger.error(f"Audio playback error: {e}")
        finally:
            self._mark_playback_end()
    
    async def _play_audio_samples(self, samples, sample_rate: int):
        """Play audio samples via paplay (Linux/PipeWire) or sounddevice (fallback).
        
        On Linux (RPi5), writes a temp WAV and uses paplay (PipeWire-aware)
        so audio routes through the correct BT default sink.
        """
        import platform
        self._mark_playback_start()
        if platform.system() == "Linux":
            import tempfile
            import wave
            import numpy as np
            import subprocess
            import os
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                    temp_path = f.name
                    with wave.open(f, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
                        if isinstance(samples, np.ndarray) and samples.dtype == np.float32:
                            samples = (samples * 32767).astype(np.int16)
                        wf.writeframes(samples.tobytes())
                await asyncio.to_thread(
                    subprocess.run, ["paplay", temp_path],
                    check=False, timeout=30
                )
            except Exception as e:
                logger.error(f"paplay samples error: {e}")
            finally:
                if temp_path:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                self._mark_playback_end()
            return
        
        # Non-Linux fallback
        try:
            import sounddevice as sd
            sd.play(samples, sample_rate)
            sd.wait()
        except Exception as e:
            logger.error(f"Audio playback error: {e}")
        finally:
            self._mark_playback_end()


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
