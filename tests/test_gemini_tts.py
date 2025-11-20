"""
Test Suite for Gemini 2.5 Flash TTS Integration
Project-Cortex v2.0 - YIA 2026

This test suite validates the Gemini TTS handler functionality:
1. API connection and authentication
2. Text-to-speech generation
3. Image + prompt to audio generation
4. Audio file quality validation
5. Error handling

Author: Haziq (@IRSPlays)
Date: November 20, 2025
"""

import pytest
import os
import sys
from pathlib import Path
from PIL import Image
import wave

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from layer2_thinker.gemini_tts_handler import GeminiTTS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Test API key (from .env)
API_KEY = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')


class TestGeminiTTSInitialization:
    """Test Gemini TTS handler initialization."""
    
    def test_api_key_loaded(self):
        """Test that API key is loaded from environment."""
        assert API_KEY is not None, "GEMINI_API_KEY not found in .env file"
        assert len(API_KEY) > 20, "API key seems too short"
    
    def test_handler_initialization(self):
        """Test GeminiTTS handler can be initialized."""
        tts = GeminiTTS(api_key=API_KEY, voice_name="Kore")
        assert tts is not None
        assert tts.voice_name == "Kore"
        assert tts.api_key == API_KEY
    
    def test_singleton_pattern(self):
        """Test that GeminiTTS uses singleton pattern."""
        tts1 = GeminiTTS(api_key=API_KEY)
        tts2 = GeminiTTS(api_key=API_KEY)
        assert tts1 is tts2, "GeminiTTS should be a singleton"


class TestGeminiTTSTextToSpeech:
    """Test text-to-speech generation."""
    
    @pytest.fixture
    def tts(self):
        """Create and initialize GeminiTTS handler."""
        handler = GeminiTTS(api_key=API_KEY, voice_name="Kore", output_dir="tests/temp_audio")
        handler.initialize()
        return handler
    
    def test_simple_text_to_speech(self, tts):
        """Test basic text-to-speech generation."""
        audio_path = tts.generate_speech_from_text(
            text="Testing Gemini TTS",
            save_to_file=True
        )
        
        assert audio_path is not None, "Audio path should not be None"
        assert os.path.exists(audio_path), f"Audio file not created: {audio_path}"
        
        # Verify WAV file properties
        with wave.open(audio_path, 'rb') as wf:
            assert wf.getnchannels() == 1, "Audio should be mono"
            assert wf.getframerate() == 24000, "Sample rate should be 24kHz"
            assert wf.getsampwidth() == 2, "Sample width should be 16-bit"
        
        # Cleanup
        os.remove(audio_path)
    
    def test_long_text_to_speech(self, tts):
        """Test TTS with longer text."""
        long_text = "The quick brown fox jumps over the lazy dog. This is a test of the Gemini text-to-speech system."
        
        audio_path = tts.generate_speech_from_text(
            text=long_text,
            save_to_file=True
        )
        
        assert audio_path is not None
        assert os.path.exists(audio_path)
        
        # Verify file size is reasonable (longer text = larger file)
        file_size = os.path.getsize(audio_path)
        assert file_size > 10000, "Audio file seems too small for long text"
        
        # Cleanup
        os.remove(audio_path)


class TestGeminiTTSImageToSpeech:
    """Test image + prompt to speech generation."""
    
    @pytest.fixture
    def tts(self):
        """Create and initialize GeminiTTS handler."""
        handler = GeminiTTS(api_key=API_KEY, voice_name="Kore", output_dir="tests/temp_audio")
        handler.initialize()
        return handler
    
    @pytest.fixture
    def sample_image(self):
        """Create a sample test image."""
        # Create a simple 100x100 red image
        img = Image.new('RGB', (100, 100), color='red')
        return img
    
    def test_image_to_speech_basic(self, tts, sample_image):
        """Test basic image + prompt to speech."""
        audio_path = tts.generate_speech_from_image(
            image=sample_image,
            prompt="Describe what you see in this image",
            save_to_file=True
        )
        
        assert audio_path is not None, "Audio path should not be None"
        assert os.path.exists(audio_path), f"Audio file not created: {audio_path}"
        
        # Verify WAV file
        with wave.open(audio_path, 'rb') as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 24000
        
        # Cleanup
        os.remove(audio_path)
    
    def test_image_to_speech_custom_prompt(self, tts, sample_image):
        """Test image to speech with custom safety prompt."""
        audio_path = tts.generate_speech_from_image(
            image=sample_image,
            prompt="Is there any danger in this image? Respond with yes or no.",
            save_to_file=True
        )
        
        assert audio_path is not None
        assert os.path.exists(audio_path)
        
        # Cleanup
        os.remove(audio_path)


class TestGeminiTTSErrorHandling:
    """Test error handling and edge cases."""
    
    def test_invalid_api_key(self):
        """Test initialization with invalid API key."""
        tts = GeminiTTS(api_key="INVALID_KEY_12345", voice_name="Kore")
        success = tts.initialize()
        
        # Should return False or raise an exception
        assert success is False or tts.error_count > 0
    
    def test_empty_text(self):
        """Test TTS with empty text."""
        tts = GeminiTTS(api_key=API_KEY)
        tts.initialize()
        
        # This should handle gracefully
        audio_path = tts.generate_speech_from_text(
            text="",
            save_to_file=True
        )
        
        # Depending on implementation, might return None or create minimal audio
        # Just ensure it doesn't crash
        assert True  # If we got here, no crash occurred


class TestGeminiTTSPerformance:
    """Test performance metrics."""
    
    @pytest.fixture
    def tts(self):
        """Create and initialize GeminiTTS handler."""
        handler = GeminiTTS(api_key=API_KEY, voice_name="Kore", output_dir="tests/temp_audio")
        handler.initialize()
        return handler
    
    def test_tts_latency(self, tts):
        """Test TTS generation latency."""
        import time
        
        start_time = time.time()
        audio_path = tts.generate_speech_from_text(
            text="Quick latency test",
            save_to_file=True
        )
        end_time = time.time()
        
        latency = end_time - start_time
        
        assert audio_path is not None
        assert latency < 5.0, f"TTS took too long: {latency:.2f}s (should be <5s)"
        
        print(f"\n✅ TTS Latency: {latency:.2f}s")
        
        # Cleanup
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
    
    def test_statistics_tracking(self, tts):
        """Test that usage statistics are tracked."""
        # Generate a few TTS requests
        for i in range(3):
            tts.generate_speech_from_text(
                text=f"Test number {i+1}",
                save_to_file=False
            )
        
        stats = tts.get_stats()
        
        assert stats['requests'] >= 3, "Request count not tracked"
        assert 'success_rate' in stats
        assert stats['success_rate'] >= 0


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
