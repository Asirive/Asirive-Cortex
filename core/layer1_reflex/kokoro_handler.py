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
import os
import time
from typing import Optional, List, Generator
import numpy as np

# --- Force system espeak-ng BEFORE any kokoro/phonemizer imports ---
# The pip package espeakng-loader bundles its own espeak-ng library but the
# bundled data path points to a non-existent CI build directory:
#   /home/runner/work/espeakng-loader/.../espeak-ng-data/phontab
# This causes a segfault when Kokoro tries to phonemize text.
# Fix: tell phonemizer to use the system espeak-ng library and data instead.
_SYSTEM_ESPEAK_LIB = "/usr/lib/aarch64-linux-gnu/libespeak-ng.so.1"
_SYSTEM_ESPEAK_DATA = "/usr/share/espeak-ng-data"

if os.path.exists(_SYSTEM_ESPEAK_LIB):
    os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = _SYSTEM_ESPEAK_LIB
    logging.getLogger(__name__).info(
        f"Using system espeak-ng library: {_SYSTEM_ESPEAK_LIB}"
    )
if os.path.exists(_SYSTEM_ESPEAK_DATA):
    os.environ["ESPEAK_DATA_PATH"] = _SYSTEM_ESPEAK_DATA
    logging.getLogger(__name__).info(
        f"Using system espeak-ng data: {_SYSTEM_ESPEAK_DATA}"
    )

# --- Monkey-patch EspeakWrapper BEFORE importing kokoro_onnx ---
# kokoro-onnx 0.4.9/0.5.0 calls EspeakWrapper.set_data_path() which doesn't
# exist in phonemizer-fork 3.3.2. We add it here so the import succeeds.
# The patched method points to the system espeak-ng-data directory.
try:
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    if not hasattr(EspeakWrapper, 'set_data_path'):
        @classmethod
        def _set_data_path(cls, path):
            # Ignore the bundled path; use system espeak-ng-data instead
            cls._data_path = _SYSTEM_ESPEAK_DATA if os.path.exists(_SYSTEM_ESPEAK_DATA) else path
        EspeakWrapper.set_data_path = _set_data_path
        logging.getLogger(__name__).info(
            "Patched EspeakWrapper.set_data_path (phonemizer-fork compat)"
        )
except ImportError:
    pass  # phonemizer not installed — kokoro import will fail on its own
# --- End monkey-patch ---

try:
    from kokoro_onnx import Kokoro
    KOKORO_AVAILABLE = True
except ImportError:
    KOKORO_AVAILABLE = False
    Kokoro = None

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
        logger.info("🔊 load_pipeline() called")
        
        if self.pipeline is not None:
            logger.info("✅ Kokoro pipeline already loaded (pipeline object exists)")
            logger.info(f"   Pipeline type: {type(self.pipeline)}")
            logger.info(f"   Current voice: {self.pipeline.voice if hasattr(self.pipeline, 'voice') else 'unknown'}")
            return True
            
        try:
            # Check if kokoro-onnx is installed
            logger.info("📦 Checking kokoro-onnx availability...")
            if not KOKORO_AVAILABLE:
                logger.error("❌ kokoro-onnx not installed")
                logger.error("   Install command: pip install kokoro-onnx")
                logger.error("   Or: pip install kokoro>=0.3.4")
                return False
            
            logger.info("✅ kokoro-onnx is available")
            logger.info(f"   Kokoro class: {Kokoro}")
            
            logger.info(f"⏳ Initializing Kokoro pipeline...")
            logger.info(f"   Language code: '{self.lang_code}'")
            logger.info(f"   Default voice: '{self.default_voice}'")
            logger.info(f"   Speed: {self.default_speed}x")
            start_time = time.time()
            
            # Initialize pipeline (auto-downloads model from HuggingFace)
            logger.info("📥 Creating Kokoro instance...")
            logger.info("   Using kokoro-onnx API v0.4+ (requires model files)")
            
            # NEW API (v0.4+): Requires model_path and voices_path
            # Files must be downloaded from GitHub releases first
            import os
            import urllib.request
            from pathlib import Path
            
            # Use user's cache directory for models
            cache_dir = Path.home() / ".cache" / "kokoro-onnx"
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            # Model files (v1.0 is latest stable)
            model_path = cache_dir / "kokoro-v1.0.onnx"
            voices_path = cache_dir / "voices-v1.0.bin"
            
            logger.info(f"   Model path: {model_path}")
            logger.info(f"   Voices path: {voices_path}")
            
            # Download URLs
            model_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
            voices_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
            
            # Download model if not exists
            if not model_path.exists():
                logger.info(f"   📥 Downloading model (~312MB) from {model_url}...")
                logger.info("      This may take 2-5 minutes on first run...")
                try:
                    urllib.request.urlretrieve(model_url, model_path)
                    logger.info("   ✅ Model downloaded successfully")
                except Exception as e:
                    logger.error(f"   ❌ Model download failed: {e}")
                    return False
            
            # Download voices if not exists
            if not voices_path.exists():
                logger.info(f"   📥 Downloading voices (~500KB) from {voices_url}...")
                try:
                    urllib.request.urlretrieve(voices_url, voices_path)
                    logger.info("   ✅ Voices downloaded successfully")
                except Exception as e:
                    logger.error(f"   ❌ Voices download failed: {e}")
                    return False
            
            # Create Kokoro instance with file paths
            self.pipeline = Kokoro(
                model_path=str(model_path),
                voices_path=str(voices_path)
            )
            
            if self.pipeline is None:
                logger.error("❌ Kokoro() returned None instead of pipeline object")
                return False
            
            load_time = time.time() - start_time
            logger.info(f"✅ Kokoro pipeline created in {load_time:.2f}s")
            logger.info(f"   Pipeline type: {type(self.pipeline)}")
            logger.info(f"   Pipeline methods: {[m for m in dir(self.pipeline) if not m.startswith('_')]}")
            
            # Warm-up generation for accurate latency measurement (OPTIONAL - may fail on some systems)
            logger.info("🔥 Running warm-up generation to test pipeline...")
            warmup_text = "Cortex initialized"
            logger.info(f"   Warm-up text: '{warmup_text}'")
            logger.info(f"   Warm-up voice: '{self.default_voice}'")
            
            try:
                warmup_start = time.time()
                # NEW API: create(text, voice, speed, lang)
                warmup_audio, sample_rate = self.pipeline.create(
                    warmup_text,
                    voice=self.default_voice,
                    speed=self.default_speed,
                    lang="en-us"  # English US
                )
                warmup_time = time.time() - warmup_start
                
                if warmup_audio is None:
                    logger.warning("⚠️ Warm-up generation returned None (pipeline may still work)")
                else:
                    logger.info(f"✅ Warm-up complete in {warmup_time:.2f}s")
                    logger.info(f"   Warm-up audio shape: {warmup_audio.shape if hasattr(warmup_audio, 'shape') else 'N/A'}")
                    logger.info(f"   Warm-up audio type: {type(warmup_audio)}")
                    logger.info(f"   Sample rate: {sample_rate} Hz")
            except KeyboardInterrupt:
                logger.warning("⚠️ Warm-up interrupted - skipping (pipeline should still work)")
            except Exception as warmup_err:
                logger.warning(f"⚠️ Warm-up failed: {warmup_err}")
                logger.warning("   This is non-critical - pipeline should still work for actual TTS")
            
            # Return success even if warm-up fails (warm-up is optional)
            logger.info("✅ Kokoro pipeline loaded (warm-up skipped/optional)")
            return True
            
        except ImportError as e:
            logger.error(f"❌ Import error loading Kokoro: {e}")
            logger.error("   Make sure kokoro-onnx is installed: pip install kokoro-onnx")
            logger.error("   Full traceback:", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"❌ Failed to load Kokoro pipeline: {e}")
            logger.error("   Error type: " + type(e).__name__)
            logger.error("   Full traceback:", exc_info=True)
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
        logger.debug(f"🔊 generate_speech() called with text: '{text[:50]}...'")
        
        if self.pipeline is None:
            logger.error("❌ Pipeline not loaded. Call load_pipeline() first.")
            logger.error("   Current pipeline state: None")
            logger.error("   Initialized flag: " + str(self._initialized))
            logger.error("   KOKORO_AVAILABLE: " + str(KOKORO_AVAILABLE))
            return None
        
        logger.debug(f"✅ Pipeline exists: {type(self.pipeline)}")
        
        if not text or text.strip() == "":
            logger.warning("⚠️ Empty text provided, skipping TTS")
            return None
        
        try:
            start_time = time.time()
            
            # Use default values if not specified
            voice = voice or self.default_voice
            speed = speed or self.default_speed
            
            logger.debug(f"   Voice: {voice}")
            logger.debug(f"   Speed: {speed}x")
            
            # NEW API: create(text, voice, speed, lang) returns (audio, sample_rate)
            audio_data, sample_rate = self.pipeline.create(
                text,
                voice=voice,
                speed=speed,
                lang="en-us",  # American English
                trim=True  # Trim silence
            )
            
            if audio_data is None or len(audio_data) == 0:
                logger.warning("⚠️ No audio generated")
                return None
            
            # Ensure audio is float32 numpy array
            if not isinstance(audio_data, np.ndarray):
                audio_data = np.array(audio_data, dtype=np.float32)
            
            generation_time = (time.time() - start_time) * 1000  # Convert to ms
            self.generation_times.append(generation_time)
            
            if log_latency:
                audio_duration = len(audio_data) / sample_rate
                logger.info(
                    f"🔊 TTS: '{text[:50]}...' → "
                    f"{audio_duration:.2f}s audio (latency: {generation_time:.0f}ms, "
                    f"voice={voice})"
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
