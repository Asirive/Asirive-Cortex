"""
Layer 2: Gemini 3 Flash Preview TTS Handler - Multimodal Vision + TTS

This module sends images + prompts to Gemini 3 Flash Preview and receives
AUDIO responses directly (not text). This is the most intelligent Gemini model that combines
vision understanding with text-to-speech in a single API call.

Key Features:
- Send image + prompt to gemini-3-flash-preview
- Receive PCM audio at 24kHz sample rate
- Built-in TTS with natural voice ("Kore" default)
- No separate TTS pipeline needed
- Uses new Google Gen AI SDK (google.genai)
- Automatic retry with exponential backoff for rate limits

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
Date: December 30, 2025

HYBRID TTS ARCHITECTURE:
- Primary: Gemini 3 Flash Preview (cloud, most intelligent model, Jan 2025)
- Fallback: Kokoro-82M (local, unlimited, when all API keys exhausted)
"""

import logging
import os
import wave
import time
from typing import Optional, Tuple
from pathlib import Path
import base64

import numpy as np
from PIL import Image
from dotenv import load_dotenv

# Import Kokoro TTS for fallback (local TTS when Gemini rate-limited)
try:
    from layer1_reflex.kokoro_handler import KokoroTTS
    KOKORO_AVAILABLE = True
except ImportError:
    KOKORO_AVAILABLE = False
    logging.info("ℹ️ Kokoro TTS not available for fallback")

# Import NEW Google Gen AI SDK (not google.generativeai)
try:
    from google import genai
    from google.genai import types
    from google.genai import errors as genai_errors  # For proper error handling
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai_errors = None  # Fallback for import error
    logging.warning("⚠️ google-genai not installed. Run: pip install google-genai")

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class GeminiTTS:
    """
    Gemini 2.5 Flash TTS Handler - Vision + Audio Output
    
    This handler sends an image + text prompt to Gemini and receives
    AUDIO as the response (not text). Perfect for visually impaired users
    who need scene descriptions spoken naturally.
    """
    
    _instance = None  # Singleton pattern
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern to prevent multiple API client initializations."""
        if cls._instance is None:
            cls._instance = super(GeminiTTS, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_name: str = "Kore",
        output_dir: str = "temp_audio"
    ):
        """
        Initialize Gemini 2.5 Flash TTS API client.
        
        Args:
            api_key: Google API key (reads from GEMINI_API_KEY env var if None)
            voice_name: Voice to use (Kore, Puck, Charon, Leda, etc.)
            output_dir: Directory to save temporary audio files
        """
        if self._initialized:
            return
        
        if not GENAI_AVAILABLE:
            raise ImportError(
                "google-genai package not installed. "
                "Install it with: pip install google-genai"
            )
        
        logger.info("🎤 Initializing Gemini 2.5 Flash TTS Handler (Hybrid Mode)...")
        
        # Kokoro TTS fallback (local TTS when all API keys exhausted)
        self.kokoro_fallback: Optional[KokoroTTS] = None
        self.kokoro_initialized = False
        self.using_fallback = False  # Track if currently using fallback
        
        # API Key Rotation Pool - loaded entirely from environment variables
        # Reads GEMINI_API_KEY (primary), then GEMINI_API_KEY_2, _3, ... _10
        # Falls back to GOOGLE_API_KEY if GEMINI_API_KEY is not set
        self.api_key_pool = []
        
        # Primary key: from constructor arg, GEMINI_API_KEY, or GOOGLE_API_KEY
        primary_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if primary_key:
            self.api_key_pool.append(primary_key)
        
        # Additional keys: GEMINI_API_KEY_2 through GEMINI_API_KEY_10
        for i in range(2, 11):
            key = os.getenv(f"GEMINI_API_KEY_{i}")
            if key:
                self.api_key_pool.append(key)
        
        # Deduplicate while preserving order
        seen = set()
        deduped_pool = []
        for key in self.api_key_pool:
            if key not in seen:
                seen.add(key)
                deduped_pool.append(key)
        self.api_key_pool = deduped_pool
        
        if not self.api_key_pool:
            raise ValueError(
                "No API keys available. Set GEMINI_API_KEY in .env file.\n"
                "Add more keys as GEMINI_API_KEY_2, GEMINI_API_KEY_3, etc.\n"
                "Get your API key from: https://aistudio.google.com/app/apikey"
            )
        
        # API Key rotation state
        self.current_key_index = 0
        self.api_key = self.api_key_pool[0]
        self.failed_keys = {}  # Track failed keys with timestamps
        
        logger.info(f"API Key Pool: {len(self.api_key_pool)} keys loaded from environment")
        logger.info(f"Active Key: #{self.current_key_index + 1} ({self.api_key[:12]}...{self.api_key[-4:]})")
        
        self.voice_name = voice_name
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.client = None
        
        # Performance tracking
        self.request_count = 0
        self.error_count = 0
        
        # Rate limiting
        self.max_retries = 3
        self.base_retry_delay = 1.0  # seconds
        
        logger.info(f"📋 Gemini TTS Config:")
        logger.info(f"   Model: gemini-3-flash-preview")
        logger.info(f"   Voice: {voice_name}")
        logger.info(f"   Output Dir: {self.output_dir}")
        # Removed duplicate API key logging (already shown above with pool info)
        
        self._initialized = True
    
    def _parse_retry_delay(self, error_message: str) -> float:
        """
        Extract retry delay from Gemini API error response.
        
        Example error: "Please retry in 12.904512739s."
        Returns: 12.904512739
        """
        import re
        match = re.search(r'retry in ([\d.]+)s', error_message)
        if match:
            return float(match.group(1))
        return self.base_retry_delay
    
    def rotate_to_next_key(self) -> bool:
        """
        Rotate to the next available API key in the pool.
        
        Returns:
            True if successfully switched to new key, False if all keys exhausted
        """
        import time
        
        # Mark current key as failed
        current_key = self.api_key_pool[self.current_key_index]
        self.failed_keys[current_key] = time.time()
        
        logger.warning(f"❌ API Key #{self.current_key_index + 1} rate-limited")
        
        # Try to find next available key
        attempts = 0
        while attempts < len(self.api_key_pool):
            self.current_key_index = (self.current_key_index + 1) % len(self.api_key_pool)
            next_key = self.api_key_pool[self.current_key_index]
            
            # Check if this key was recently failed (within last 60 seconds)
            if next_key in self.failed_keys:
                time_since_fail = time.time() - self.failed_keys[next_key]
                if time_since_fail < 60:  # Skip recently failed keys
                    attempts += 1
                    continue
            
            # Found available key
            self.api_key = next_key
            logger.info(f"🔄 Switching to API Key #{self.current_key_index + 1} ({self.api_key[:12]}...{self.api_key[-4:]})")
            
            # Reinitialize client with new key
            try:
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"✅ Successfully switched to backup API key #{self.current_key_index + 1}")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to initialize with key #{self.current_key_index + 1}: {e}")
                self.failed_keys[next_key] = time.time()
                attempts += 1
        
        logger.error("❌ All API keys exhausted or rate-limited")
        return False
    
    def _initialize_kokoro_fallback(self) -> bool:
        """
        Initialize Kokoro TTS as fallback for when all Gemini API keys are exhausted.
        
        Returns:
            True if Kokoro initialized successfully, False otherwise
        """
        if not KOKORO_AVAILABLE:
            logger.warning("⚠️ Kokoro TTS not available for fallback")
            return False
        
        if self.kokoro_initialized:
            return True
        
        try:
            logger.info("🔄 Initializing Kokoro-82M as TTS fallback...")
            self.kokoro_fallback = KokoroTTS(
                lang_code="a",  # American English
                default_voice="af_bella",  # Nice female voice for Layer 2
                default_speed=1.0
            )
            if self.kokoro_fallback.load_pipeline():
                self.kokoro_initialized = True
                logger.info("✅ Kokoro-82M fallback ready (unlimited local TTS)")
                return True
            else:
                logger.error("❌ Failed to load Kokoro pipeline")
                return False
        except Exception as e:
            logger.error(f"❌ Failed to initialize Kokoro fallback: {e}")
            return False
    
    def _generate_with_kokoro_fallback(self, text: str, filename: Optional[str] = None) -> Optional[str]:
        """
        Generate speech using Kokoro-82M (local fallback).
        
        Args:
            text: Text to convert to speech
            filename: Optional output filename
            
        Returns:
            Path to saved audio file, or None if failed
        """
        if not self._initialize_kokoro_fallback():
            return None
        
        try:
            logger.info(f"🔊 [FALLBACK] Generating speech with Kokoro-82M: '{text[:50]}...'")
            self.using_fallback = True
            
            # Generate audio with Kokoro
            audio_data = self.kokoro_fallback.generate_speech(text, log_latency=True)
            
            if audio_data is None:
                logger.error("❌ [FALLBACK] Kokoro failed to generate audio")
                return None
            
            # Save as WAV file
            if filename is None:
                filename = f"kokoro_fallback_{int(time.time())}.wav"
            
            output_path = self.output_dir / filename
            
            # Convert float32 [-1, 1] to int16 PCM
            audio_int16 = (audio_data * 32767).astype(np.int16)
            pcm_data = audio_int16.tobytes()
            
            self._save_wav_file(str(output_path), pcm_data)
            
            logger.info(f"✅ [FALLBACK] Kokoro audio saved to: {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"❌ [FALLBACK] Kokoro generation failed: {e}")
            return None
    
    def _retry_api_call(self, api_call_func, *args, **kwargs):
        """
        Retry wrapper for Gemini API calls with exponential backoff and API key rotation.
        
        Uses proper google.genai error handling instead of string matching.
        
        Args:
            api_call_func: The API call function to retry
            *args, **kwargs: Arguments to pass to the function
        
        Returns:
            Result from api_call_func or None if all retries failed
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                return api_call_func(*args, **kwargs)
            
            except Exception as e:
                last_exception = e
                error_str = str(e)
                
                # Check if it's a rate limit (429) or service unavailable (503) error
                # Use proper error code detection (google.genai.errors.APIError has .code attribute)
                is_rate_limit_error = False
                
                # Method 1: Check if it's a proper genai APIError with .code attribute
                if genai_errors and isinstance(e, genai_errors.APIError):
                    if e.code in (429, 503):
                        is_rate_limit_error = True
                        logger.warning(f"⚠️ APIError detected: code={e.code}, message={e.message[:100]}...")
                
                # Method 2: Fallback to string matching for other exception types
                # (Some errors may be wrapped differently)
                if not is_rate_limit_error:
                    if any(x in error_str for x in ['429', 'RESOURCE_EXHAUSTED', '503', 'UNAVAILABLE', 'Service Unavailable']):
                        is_rate_limit_error = True
                        logger.warning(f"⚠️ Rate limit detected via string match: {error_str[:150]}...")
                
                if is_rate_limit_error:
                    logger.warning(
                        f"⏳ Rate limit/unavailable hit on API Key #{self.current_key_index + 1} "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    
                    # Try to rotate to next API key
                    if self.rotate_to_next_key():
                        logger.info(f"🔄 Retrying with new API key...")
                        continue  # Retry immediately with new key
                    else:
                        # All keys exhausted, extract retry delay and wait
                        retry_delay = self._parse_retry_delay(error_str)
                        
                        if attempt < self.max_retries - 1:
                            logger.warning(
                                f"⏳ All keys exhausted. Waiting {retry_delay:.1f}s before retry..."
                            )
                            time.sleep(retry_delay)
                        else:
                            logger.error(
                                f"❌ Rate limit exceeded after {self.max_retries} attempts. "
                                "All API keys exhausted."
                            )
                            raise
                else:
                    # Non-rate-limit error, don't retry
                    logger.error(f"❌ Non-retryable error: {error_str[:200]}")
                    raise
        
        # If we get here, all retries failed - raise to trigger fallback
        if last_exception:
            raise last_exception
        return None
    
    def is_using_fallback(self) -> bool:
        """Check if currently using Kokoro fallback instead of Gemini."""
        return self.using_fallback
    
    def reset_fallback_status(self):
        """Reset fallback status (call when API keys become available again)."""
        self.using_fallback = False
        logger.info("🔄 Fallback status reset, will try Gemini first")
    
    def initialize(self) -> bool:
        """
        Initialize the Gemini TTS API client.
        
        Returns:
            True if initialization successful, False otherwise
        """
        if self.client is not None:
            logger.info("✅ Gemini TTS client already initialized")
            return True
        
        try:
            logger.info("⏳ Initializing Gemini TTS client...")
            
            # Create client with API key
            self.client = genai.Client(api_key=self.api_key)
            
            logger.info("✅ Gemini TTS client initialized successfully")
            
            # Skip connection test - wastes quota and can hit rate limits
            # Client initialization is sufficient validation
            logger.info("✅ Skipping API test to preserve quota")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini TTS: {e}")
            self.error_count += 1
            return False
    
    def generate_speech_from_image(
        self,
        image: Image.Image,
        prompt: str = "Describe what you see in this image",
        save_to_file: bool = True,
        filename: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate speech from image + prompt using TWO-STEP PIPELINE:
        Step 1: Use gemini-2.0-flash-exp (vision model) to generate text description
        Step 2: Use gemini-2.0-flash-exp (same model) with audio output for TTS
        
        Note: Gemini 2.0 Flash supports both vision AND audio output in one model
        image input (it's a TTS-only model). We need vision + TTS in sequence.
        
        Args:
            image: PIL Image to analyze
            prompt: Text prompt to guide the description
            save_to_file: Whether to save audio to file
            filename: Optional custom filename (auto-generated if None)
        
        Returns:
            Path to saved audio file, or None if failed
        """
        if not self.client:
            if not self.initialize():
                return None
        
        # Track text_description for potential fallback use
        text_description = None
        
        try:
            logger.info(f"🎙️ Generating speech from image (2-step pipeline)...")
            logger.info(f"   Step 1: Vision model → text description")
            logger.info(f"   Prompt: '{prompt[:50]}...'")
            self.request_count += 1
            
            # Convert PIL Image to base64 (required for Gemini API)
            import io
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            # Create parts: image + prompt
            contents = [
                types.Part.from_bytes(
                    data=base64.b64decode(image_base64),
                    mime_type='image/png'
                ),
                types.Part.from_text(text=prompt)
            ]
            
            # STEP 1: Use VISION model (gemini-3-flash-preview) with retry on rate limits
            # Official docs: gemini-3-flash-preview is the most intelligent model (Jan 2025)
            # Supports text, images, video, audio inputs with enhanced capabilities
            # See: https://ai.google.dev/gemini-api/docs/models/gemini
            def _vision_api_call():
                return self.client.models.generate_content(
                    model='gemini-3-flash-preview',  # Most intelligent Gemini model
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["TEXT"]  # Get text response (not audio)
                    )
                )
            
            vision_response = self._retry_api_call(_vision_api_call)
            
            # Extract text description from vision model
            text_description = vision_response.text
            logger.info(f"   Step 1 ✅: Generated text ({len(text_description)} chars)")
            logger.info(f"   Step 2: TTS model → audio from text")
            
            # STEP 2: Use TTS model to convert text to audio (also with retry)
            audio_path = self.generate_speech_from_text(
                text=text_description,
                save_to_file=save_to_file,
                filename=filename
            )
            
            if audio_path:
                logger.info(f"✅ Two-step pipeline complete: Vision → TTS → Audio")
            
            return audio_path
            
        except Exception as e:
            error_str = str(e)
            logger.warning(f"⚠️ Gemini TTS failed: {error_str[:100]}...")
            
            # Check if all API keys exhausted AND we have text to speak - trigger Kokoro fallback
            if text_description and any(x in error_str for x in ['429', 'RESOURCE_EXHAUSTED', '503', 'exhausted', 'rate limit']):
                logger.info("🔄 All Gemini API keys exhausted → Switching to Kokoro-82M fallback")
                return self._generate_with_kokoro_fallback(text_description)
            
            logger.error(f"❌ Failed to generate speech from image: {e}")
            self.error_count += 1
            return None
    
    def generate_text_from_image(
        self,
        image: Image.Image,
        prompt: str = "Describe what you see in this image"
    ) -> Optional[str]:
        """
        Generate TEXT ONLY from image + prompt (no TTS).
        Used when you want Gemini vision analysis but will use a different TTS engine.
        
        Args:
            image: PIL Image to analyze
            prompt: Text prompt to guide the description
        
        Returns:
            Text description from Gemini vision model, or None if failed
        """
        if not self.client:
            if not self.initialize():
                return None
        
        try:
            logger.info(f"👁️ Generating text from image (vision only)...")
            logger.info(f"   Prompt: '{prompt[:50]}...'")
            self.request_count += 1
            
            # Convert PIL Image to base64
            import io
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            # Create parts: image + prompt
            contents = [
                types.Part.from_bytes(
                    data=base64.b64decode(image_base64),
                    mime_type='image/png'
                ),
                types.Part.from_text(text=prompt)
            ]
            
            # Use VISION model (gemini-3-flash-preview) with retry on rate limits
            def _vision_api_call():
                return self.client.models.generate_content(
                    model='gemini-3-flash-preview',  # Most intelligent Gemini model
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["TEXT"],  # Get text response only
                        max_output_tokens=300,  # Allow enough room for ~150 char detailed responses
                        system_instruction=(
                            "You are a visual assistant for a visually impaired user wearing a camera. "
                            "Describe the scene in 2-4 sentences, around 100-150 characters total. "
                            "Be specific and useful: name objects, their positions (left, right, ahead), "
                            "distances, colors, text on signs, and any hazards. "
                            "Never give vague responses like 'a person is sitting'. Instead say what "
                            "they're doing, where they are, and what's around them."
                        )
                    )
                )
            
            vision_response = self._retry_api_call(_vision_api_call)
            text_description = vision_response.text
            
            logger.info(f"✅ Text generated ({len(text_description)} chars)")
            return text_description
            
        except Exception as e:
            logger.error(f"❌ Failed to generate text from image: {e}")
            self.error_count += 1
            return None
    
    def generate_speech_from_text(
        self,
        text: str,
        save_to_file: bool = True,
        filename: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate speech from text only (no image) using Gemini 2.5 Flash TTS.
        
        Args:
            text: Text to convert to speech
            save_to_file: Whether to save audio to file
            filename: Optional custom filename
        
        Returns:
            Path to saved audio file, or None if failed
        """
        if not self.client:
            if not self.initialize():
                return None
        
        try:
            logger.info(f"🎙️ Generating speech from text: '{text[:50]}...'")
            self.request_count += 1
            
            # Call Gemini 2.5 Flash TTS (text-only) with retry/rotation wrapper
            def _tts_api_call():
                return self.client.models.generate_content(
                    model='gemini-2.5-flash-preview-tts',
                    contents=text,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=self.voice_name
                                )
                            )
                        )
                    )
                )
            
            try:
                response = self._retry_api_call(_tts_api_call)
            except Exception as api_error:
                error_str = str(api_error)
                logger.warning(f"⚠️ Gemini TTS API exhausted: {error_str[:100]}...")
                
                # All API keys exhausted - use Kokoro fallback
                if any(x in error_str for x in ['429', 'RESOURCE_EXHAUSTED', '503', 'exhausted', 'rate limit']):
                    logger.info("🔄 Switching to Kokoro-82M fallback for TTS")
                    return self._generate_with_kokoro_fallback(text, filename)
                raise
            
            # Reset fallback status since Gemini worked
            self.using_fallback = False
            
            # Extract audio data
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            
            if save_to_file:
                if filename is None:
                    import time
                    filename = f"gemini_tts_text_{int(time.time())}.wav"
                
                output_path = self.output_dir / filename
                self._save_wav_file(str(output_path), audio_data)
                
                logger.info(f"✅ Audio saved to: {output_path}")
                return str(output_path)
            else:
                logger.info("✅ Audio generated (not saved)")
                return None
            
        except Exception as e:
            logger.error(f"❌ Failed to generate speech from text: {e}")
            self.error_count += 1
            return None
    
    def _save_wav_file(self, filename: str, pcm_data: bytes, channels: int = 1, rate: int = 24000, sample_width: int = 2):
        """
        Save PCM audio data as WAV file.
        
        Args:
            filename: Output filename
            pcm_data: Raw PCM audio bytes (already decoded, NOT base64)
            channels: Number of audio channels (1 = mono)
            rate: Sample rate in Hz (24000 for Gemini TTS)
            sample_width: Sample width in bytes (2 = 16-bit)
        """
        # pcm_data is already raw bytes from inline_data.data
        # No base64 decoding needed
        
        with wave.open(filename, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(rate)
            wf.writeframes(pcm_data)
    
    def get_stats(self) -> dict:
        """Get usage statistics including fallback status."""
        return {
            "requests": self.request_count,
            "errors": self.error_count,
            "success_rate": (self.request_count - self.error_count) / max(self.request_count, 1) * 100,
            "current_api_key": self.current_key_index + 1,
            "total_api_keys": len(self.api_key_pool),
            "using_kokoro_fallback": self.using_fallback,
            "kokoro_available": KOKORO_AVAILABLE and self.kokoro_initialized
        }


# Singleton instance
_gemini_tts_instance = None

def get_gemini_tts_instance(**kwargs) -> GeminiTTS:
    """Get singleton instance of GeminiTTS."""
    global _gemini_tts_instance
    if _gemini_tts_instance is None:
        _gemini_tts_instance = GeminiTTS(**kwargs)
    return _gemini_tts_instance
