"""
Layer 1: KokoroTTS Handler - Ultra-Fast Text-to-Speech

This module handles real-time text-to-speech using Kokoro-82M.
Optimized for <500ms latency for short phrases on Raspberry Pi 5.

Key Features:
- Lightweight 82M parameter model (vs multi-GB cloud TTS)
- 54 voices across 8 languages
- Offline operation (critical for Layer 1 reflex)
- Thread-safe singleton pattern

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import logging
import time
from typing import Optional, List, Generator
import numpy as np
from kokoro import KPipeline

logger = logging.getLogger(__name__)


class KokoroTTS:
    """
    Ultra-fast text-to-speech handler using Kokoro-82M.
    
    This is part of Layer 1 (Reflex) - providing fast, offline TTS
    for safety alerts and object descriptions with <500ms latency target.
    """
    
    _instance = None  # Singleton pattern
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern to prevent multiple pipeline loads."""
        if cls._instance is None:
            cls._instance = super(KokoroTTS, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        lang_code: str = "a",  # 'a' for American English
        default_voice: str = "af_alloy",  # American Female - Alloy
        default_speed: float = 1.0
    ):
        """
        Initialize Kokoro TTS engine.
        
        Args:
            lang_code: Language code. Options:
                - 'a' = American English (🇺🇸)
                - 'b' = British English (🇬🇧)
                - 'e' = Spanish (🇪🇸)
                - 'f' = French (🇫🇷)
                - 'i' = Italian (🇮🇹)
                - 'j' = Japanese (🇯🇵)
                - 'p' = Portuguese (🇧🇷)
                - 'z' = Chinese (🇨🇳)
            default_voice: Default voice to use. American English voices:
                - af_alloy, af_bella, af_jessica, af_nicole, af_sarah (Female)
                - am_adam, am_michael (Male)
            default_speed: Speech speed multiplier (1.0 = normal, 1.2 = faster)
        """
        if self._initialized:
            logger.debug("KokoroTTS already initialized, skipping...")
            return
            
        logger.info("🔊 Initializing Kokoro TTS Handler...")
        
        self.lang_code = lang_code
        self.default_voice = default_voice
        self.default_speed = default_speed
        self.pipeline = None
        
        # Performance tracking
        self.generation_times = []
        
        logger.info(f"📋 Kokoro Config:")
        logger.info(f"   Language Code: {lang_code}")
        logger.info(f"   Default Voice: {default_voice}")
        logger.info(f"   Default Speed: {default_speed}x")
        
        self._initialized = True
    
    def load_pipeline(self) -> bool:
        """
        Load the Kokoro TTS pipeline.
        
        On first run, this will download:
        - kokoro-v1_0.pth (~312MB) - Main TTS model
        - Voice files (~500KB each) - Downloaded on-demand per voice
        
        Returns:
            True if pipeline loaded successfully, False otherwise
        """
        if self.pipeline is not None:
            logger.info("✅ Kokoro pipeline already loaded")
            return True
            
        try:
            logger.info(f"⏳ Loading Kokoro pipeline for lang='{self.lang_code}'...")
            start_time = time.time()
            
            # Initialize pipeline (auto-downloads model from HuggingFace)
            self.pipeline = KPipeline(lang_code=self.lang_code)
            
            load_time = time.time() - start_time
            logger.info(f"✅ Kokoro pipeline loaded in {load_time:.2f}s")
            
            # Warm-up generation for accurate latency measurement
            logger.info("🔥 Running warm-up generation...")
            warmup_text = "Cortex initialized"
            _ = list(self.pipeline(
                warmup_text,
                voice=self.default_voice,
                speed=self.default_speed
            ))
            logger.info("✅ Warm-up complete")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to load Kokoro pipeline: {e}")
            return False
    
    def generate_speech(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        log_latency: bool = True
    ) -> Optional[np.ndarray]:
        """
        Generate speech from text.
        
        Args:
            text: Text to convert to speech
            voice: Voice name (uses default if None). American English voices:
                - af_alloy, af_bella, af_jessica, af_nicole, af_sarah (Female)
                - am_adam, am_michael (Male)
            speed: Speech speed multiplier (uses default if None)
            log_latency: If True, log generation latency
            
        Returns:
            Audio data as numpy array (24kHz sample rate), or None if failed
        """
        if self.pipeline is None:
            logger.error("❌ Pipeline not loaded. Call load_pipeline() first.")
            return None
        
        if not text or text.strip() == "":
            logger.warning("⚠️ Empty text provided, skipping TTS")
            return None
        
        try:
            start_time = time.time()
            
            # Use default values if not specified
            voice = voice or self.default_voice
            speed = speed or self.default_speed
            
            # Generate audio (returns generator of audio chunks)
            audio_generator = self.pipeline(
                text,
                voice=voice,
                speed=speed
            )
            
            # Collect all audio chunks into single array
            audio_chunks = list(audio_generator)
            
            if not audio_chunks:
                logger.warning("⚠️ No audio generated")
                return None
            
            # Extract audio data from chunks
            # Kokoro generator yields tuples: (graphemes, phonemes, audio)
            audio_tensors = []
            for chunk in audio_chunks:
                # Check if chunk is a tuple (gs, ps, audio)
                if isinstance(chunk, tuple) and len(chunk) == 3:
                    _, _, audio_data = chunk
                # Check if chunk has .output.audio (Result object)
                elif hasattr(chunk, 'output') and hasattr(chunk.output, 'audio'):
                    audio_data = chunk.output.audio
                # Direct audio data
                else:
                    audio_data = chunk
                
                # Convert to numpy if needed
                if hasattr(audio_data, 'cpu'):  # PyTorch tensor
                    audio_np = audio_data.cpu().numpy()
                elif hasattr(audio_data, 'numpy'):  # NumPy-compatible
                    audio_np = audio_data.numpy() if callable(audio_data.numpy) else audio_data
                else:
                    audio_np = np.array(audio_data, dtype=np.float32)
                audio_tensors.append(audio_np)
            
            if not audio_tensors:
                logger.error("❌ No valid audio data extracted from chunks")
                return None
            
            # Concatenate all audio segments
            if len(audio_tensors) == 1:
                audio_data = audio_tensors[0]
            else:
                audio_data = np.concatenate(audio_tensors)
            
            generation_time = (time.time() - start_time) * 1000  # Convert to ms
            self.generation_times.append(generation_time)
            
            if log_latency:
                audio_duration = len(audio_data) / 24000  # 24kHz sample rate
                logger.info(
                    f"🔊 TTS: '{text[:50]}...' → {len(audio_chunks)} chunks, "
                    f"{audio_duration:.2f}s audio (latency: {generation_time:.0f}ms)"
                )
                
                # Check if we're meeting latency targets
                if generation_time > 500:  # 500ms target
                    logger.warning(f"⚠️ Latency above target: {generation_time:.0f}ms > 500ms")
            
            return audio_data
            
        except Exception as e:
            logger.error(f"❌ Speech generation failed: {e}")
            return None
    
    def generate_speech_streaming(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None
    ) -> Generator[np.ndarray, None, None]:
        """
        Generate speech with streaming output (for low-latency playback).
        
        This yields audio chunks as they're generated, allowing playback
        to start before the entire audio is generated.
        
        Args:
            text: Text to convert to speech
            voice: Voice name (uses default if None)
            speed: Speech speed multiplier (uses default if None)
            
        Yields:
            Audio chunks as numpy arrays
        """
        if self.pipeline is None:
            logger.error("❌ Pipeline not loaded. Call load_pipeline() first.")
            return
        
        try:
            voice = voice or self.default_voice
            speed = speed or self.default_speed
            
            logger.info(f"🔊 Streaming TTS: '{text[:50]}...'")
            
            # Yield chunks as they're generated
            for chunk in self.pipeline(text, voice=voice, speed=speed):
                yield chunk
                
        except Exception as e:
            logger.error(f"❌ Streaming generation failed: {e}")
    
    def save_to_file(
        self,
        text: str,
        output_path: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None
    ) -> bool:
        """
        Generate speech and save to WAV file.
        
        Args:
            text: Text to convert to speech
            output_path: Path to save WAV file
            voice: Voice name (uses default if None)
            speed: Speech speed multiplier (uses default if None)
            
        Returns:
            True if saved successfully, False otherwise
        """
        audio_data = self.generate_speech(text, voice, speed)
        
        if audio_data is None:
            return False
        
        try:
            import scipy.io.wavfile as wavfile
            
            # Save as 24kHz WAV file
            wavfile.write(output_path, 24000, audio_data)
            logger.info(f"💾 Audio saved to: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to save audio: {e}")
            return False
    
    def get_available_voices(self) -> List[str]:
        """
        Get list of available voices for current language.
        
        Returns:
            List of voice names
        """
        # Voice mappings per language
        voices = {
            "a": [  # American English (🇺🇸)
                "af_alloy", "af_bella", "af_jessica", "af_nicole", "af_sarah",
                "am_adam", "am_michael"
            ],
            "b": [  # British English (🇬🇧)
                "bf_emma", "bf_isabella", "bm_george", "bm_lewis"
            ],
            "e": [  # Spanish (🇪🇸)
                "ef_garcia", "em_martinez"
            ],
            "f": [  # French (🇫🇷)
                "ff_dubois", "fm_petit"
            ],
            "i": [  # Italian (🇮🇹)
                "if_rossi", "im_conti"
            ],
            "j": [  # Japanese (🇯🇵)
                "jf_sato", "jm_tanaka"
            ],
            "p": [  # Portuguese (🇧🇷)
                "pf_silva", "pm_santos"
            ],
            "z": [  # Chinese (🇨🇳)
                "zf_wang", "zm_li"
            ]
        }
        
        return voices.get(self.lang_code, [])
    
    def get_stats(self) -> dict:
        """
        Get performance statistics.
        
        Returns:
            Dictionary with average latency, min/max, and generation count
        """
        if not self.generation_times:
            return {
                "count": 0,
                "avg_latency_ms": 0,
                "min_latency_ms": 0,
                "max_latency_ms": 0
            }
        
        return {
            "count": len(self.generation_times),
            "avg_latency_ms": np.mean(self.generation_times),
            "min_latency_ms": np.min(self.generation_times),
            "max_latency_ms": np.max(self.generation_times),
            "lang_code": self.lang_code,
            "default_voice": self.default_voice
        }


# Convenience function for quick usage
def create_kokoro_tts(
    lang_code: str = "a",
    voice: str = "af_alloy"
) -> KokoroTTS:
    """
    Factory function to create and load KokoroTTS instance.
    
    Args:
        lang_code: Language code ('a' for American English)
        voice: Default voice name
        
    Returns:
        Initialized KokoroTTS instance
    """
    tts = KokoroTTS(lang_code=lang_code, default_voice=voice)
    tts.load_pipeline()
    return tts


if __name__ == "__main__":
    # Test the KokoroTTS handler
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("="*60)
    print("🧪 Testing KokoroTTS Handler")
    print("="*60)
    
    # Test 1: Initialize pipeline
    tts = create_kokoro_tts()
    
    # Test 2: Generate speech
    print("\n📝 Test 1: Generate short phrase")
    audio = tts.generate_speech("Obstacle detected ahead")
    if audio is not None:
        print(f"✅ Generated {len(audio)/24000:.2f}s of audio")
    
    # Test 3: List available voices
    print("\n📝 Test 2: Available voices")
    voices = tts.get_available_voices()
    print(f"Found {len(voices)} voices: {', '.join(voices)}")
    
    # Test 4: Test different voice
    print("\n📝 Test 3: Test with different voice (am_adam)")
    audio = tts.generate_speech("Testing male voice", voice="am_adam")
    if audio is not None:
        print(f"✅ Generated {len(audio)/24000:.2f}s of audio")
    
    # Test 5: Show stats
    print("\n📊 Performance Stats:")
    stats = tts.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    print("\n✅ KokoroTTS handler test complete!")
