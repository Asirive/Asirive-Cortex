"""
Layer 2: Gemini 2.5 Flash TTS Handler - Multimodal Vision + TTS

This module sends images + prompts to Gemini 2.5 Flash Preview TTS and receives
AUDIO responses directly (not text). This is the new Gemini model that combines
vision understanding with text-to-speech in a single API call.

Key Features:
- Send image + prompt to gemini-2.5-flash-preview-tts
- Receive PCM audio at 24kHz sample rate
- Built-in TTS with natural voice ("Kore" default)
- No separate TTS pipeline needed
- Uses new Google Gen AI SDK (google.genai)

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
Date: November 20, 2025
"""

import logging
import os
import wave
from typing import Optional
from pathlib import Path
import base64

import numpy as np
from PIL import Image
from dotenv import load_dotenv

# Import NEW Google Gen AI SDK (not google.generativeai)
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
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
        
        logger.info("🎤 Initializing Gemini 2.5 Flash TTS Handler...")
        
        # Get API key (try GEMINI_API_KEY first, then GOOGLE_API_KEY for compatibility)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        
        if not self.api_key:
            raise ValueError(
                "Google API key not found. Set GEMINI_API_KEY in .env file.\n"
                "Get your API key from: https://aistudio.google.com/app/apikey"
            )
        
        self.voice_name = voice_name
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.client = None
        
        # Performance tracking
        self.request_count = 0
        self.error_count = 0
        
        logger.info(f"📋 Gemini TTS Config:")
        logger.info(f"   Model: gemini-2.5-flash-preview-tts")
        logger.info(f"   Voice: {voice_name}")
        logger.info(f"   Output Dir: {self.output_dir}")
        logger.info(f"   API Key: {self.api_key[:12]}...{self.api_key[-4:]}")
        
        self._initialized = True
    
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
            
            # Test with a simple audio generation
            logger.info("🔥 Running TTS connection test...")
            test_audio_path = self.generate_speech_from_text("Testing Gemini TTS", save_to_file=False)
            if test_audio_path:
                logger.info(f"✅ Connection test passed")
            else:
                logger.warning("⚠️ Connection test returned no audio")
            
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
        Generate speech from image + prompt using Gemini 2.5 Flash TTS.
        
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
        
        try:
            logger.info(f"🎙️ Generating speech from image...")
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
            
            # Call Gemini 2.5 Flash TTS
            response = self.client.models.generate_content(
                model='gemini-2.5-flash-preview-tts',
                contents=contents,
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
            
            # Extract audio data from response
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            
            if save_to_file:
                # Generate filename if not provided
                if filename is None:
                    import time
                    filename = f"gemini_tts_{int(time.time())}.wav"
                
                output_path = self.output_dir / filename
                
                # Save as WAV file (PCM format, 24kHz, mono, 16-bit)
                self._save_wav_file(str(output_path), audio_data)
                
                logger.info(f"✅ Audio saved to: {output_path}")
                return str(output_path)
            else:
                logger.info("✅ Audio generated (not saved)")
                return None
            
        except Exception as e:
            logger.error(f"❌ Failed to generate speech from image: {e}")
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
            
            # Call Gemini 2.5 Flash TTS (text-only)
            response = self.client.models.generate_content(
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
    
    def _save_wav_file(self, filename: str, pcm_data: str, channels: int = 1, rate: int = 24000, sample_width: int = 2):
        """
        Save PCM audio data as WAV file.
        
        Args:
            filename: Output filename
            pcm_data: Base64-encoded PCM audio data
            channels: Number of audio channels (1 = mono)
            rate: Sample rate in Hz (24000 for Gemini TTS)
            sample_width: Sample width in bytes (2 = 16-bit)
        """
        # Decode base64 PCM data
        pcm_bytes = base64.b64decode(pcm_data)
        
        with wave.open(filename, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(rate)
            wf.writeframes(pcm_bytes)
    
    def get_stats(self) -> dict:
        """Get usage statistics."""
        return {
            "requests": self.request_count,
            "errors": self.error_count,
            "success_rate": (self.request_count - self.error_count) / max(self.request_count, 1) * 100
        }


# Singleton instance
_gemini_tts_instance = None

def get_gemini_tts_instance(**kwargs) -> GeminiTTS:
    """Get singleton instance of GeminiTTS."""
    global _gemini_tts_instance
    if _gemini_tts_instance is None:
        _gemini_tts_instance = GeminiTTS(**kwargs)
    return _gemini_tts_instance
