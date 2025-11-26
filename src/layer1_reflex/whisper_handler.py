"""
Layer 1: WhisperSTT Handler - GPU-Accelerated Speech Recognition

This module handles real-time speech-to-text using OpenAI Whisper.
Optimized for <1s latency for 5-second audio clips on RTX 2050.

Key Features:
- GPU-accelerated inference with automatic CPU fallback
- Multiple model sizes (tiny, base, small for speed vs accuracy)
- Real-time audio chunk processing
- Thread-safe singleton pattern

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import logging
import os
import time
from typing import Optional, Dict, Any
import torch
import whisper
import numpy as np

logger = logging.getLogger(__name__)


class WhisperSTT:
    """
    GPU-accelerated speech-to-text handler using OpenAI Whisper.
    
    This is part of Layer 1 (Reflex) - providing fast, offline transcription
    for voice commands with <1s latency target.
    """
    
    _instance = None  # Singleton pattern
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern to prevent multiple model loads."""
        if cls._instance is None:
            cls._instance = super(WhisperSTT, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        model_size: str = "base",  # tiny, base, small, medium, large, turbo
        device: Optional[str] = None,
        language: str = "en"
    ):
        """
        Initialize Whisper STT engine.
        
        Args:
            model_size: Whisper model size. Options:
                - 'tiny' (39M params, ~1GB VRAM, ~10x speed) - Ultra-fast
                - 'base' (74M params, ~1GB VRAM, ~7x speed) - Recommended for RPi5
                - 'small' (244M params, ~2GB VRAM, ~4x speed) - Good accuracy
                - 'medium' (769M params, ~5GB VRAM, ~2x speed) - High accuracy
                - 'turbo' (809M params, ~6GB VRAM, ~8x speed) - Fast + accurate
            device: Inference device ('cuda' or 'cpu'). Auto-detected if None.
            language: Target language code (default: 'en' for English)
        """
        if self._initialized:
            logger.debug("WhisperSTT already initialized, skipping...")
            return
            
        logger.info("🎤 Initializing Whisper STT Handler...")
        
        # Auto-detect device if not specified
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        # Verify CUDA availability
        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning("⚠️ CUDA requested but not available. Falling back to CPU.")
            self.device = "cpu"
            
        self.model_size = model_size
        self.language = language
        self.model = None
        self.fp16 = self.device == "cuda"  # Use FP16 only on GPU
        
        # Performance tracking
        self.inference_times = []
        
        logger.info(f"📋 Whisper Config:")
        logger.info(f"   Model Size: {model_size}")
        logger.info(f"   Device: {self.device}")
        logger.info(f"   FP16 Enabled: {self.fp16}")
        logger.info(f"   Language: {language}")
        
        if self.device == "cuda":
            gpu_name = torch.cuda.get_device_name(0)
            gpu_vram = torch.cuda.get_device_properties(0).total_memory / 1e9
            logger.info(f"🔥 GPU Detected: {gpu_name} ({gpu_vram:.1f}GB VRAM)")
        
        self._initialized = True
    
    def load_model(self) -> bool:
        """
        Load the Whisper model into memory.
        
        Returns:
            True if model loaded successfully, False otherwise
        """
        if self.model is not None:
            logger.info("✅ Whisper model already loaded")
            return True
            
        try:
            logger.info(f"⏳ Loading Whisper '{self.model_size}' model...")
            start_time = time.time()
            
            # Load model with GPU support
            self.model = whisper.load_model(
                self.model_size,
                device=self.device
            )
            
            load_time = time.time() - start_time
            logger.info(f"✅ Whisper model loaded in {load_time:.2f}s")
            
            # Warm-up inference for accurate latency measurement
            logger.info("🔥 Running warm-up inference...")
            dummy_audio = np.zeros(16000 * 2, dtype=np.float32)  # 2 seconds of silence
            self._transcribe_internal(dummy_audio, warmup=True)
            logger.info("✅ Warm-up complete")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to load Whisper model: {e}")
            return False
    
    def _transcribe_internal(
        self,
        audio: np.ndarray,
        warmup: bool = False
    ) -> Dict[str, Any]:
        """
        Internal transcription method.
        
        Args:
            audio: Audio data as numpy array (16kHz sample rate expected)
            warmup: If True, skip logging (for warm-up runs)
            
        Returns:
            Whisper transcription result dictionary
        """
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")
        
        # Ensure audio is padded or trimmed to 30-second chunks
        # Whisper processes audio in 30-second windows
        audio = whisper.pad_or_trim(audio)
        
        # Convert to mel spectrogram
        mel = whisper.log_mel_spectrogram(audio).to(self.device)
        
        # Detect language (or use preset language)
        options = whisper.DecodingOptions(
            language=self.language,
            fp16=self.fp16
        )
        
        # Decode the audio
        result = whisper.decode(self.model, mel, options)
        
        return result
    
    def transcribe(
        self,
        audio: np.ndarray,
        log_latency: bool = True
    ) -> Optional[str]:
        """
        Transcribe audio to text.
        
        Args:
            audio: Audio data as numpy array (16kHz sample rate)
            log_latency: If True, log inference latency
            
        Returns:
            Transcribed text, or None if transcription failed
        """
        if self.model is None:
            logger.error("❌ Model not loaded. Call load_model() first.")
            return None
        
        try:
            start_time = time.time()
            
            # Transcribe using high-level API for better accuracy
            result = self.model.transcribe(
                audio,
                language=self.language,
                fp16=self.fp16,
                verbose=False  # Suppress Whisper's verbose output
            )
            
            inference_time = (time.time() - start_time) * 1000  # Convert to ms
            self.inference_times.append(inference_time)
            
            text = result["text"].strip()
            
            if log_latency:
                audio_duration = len(audio) / 16000  # 16kHz sample rate
                logger.info(f"🎤 STT: '{text}' (latency: {inference_time:.0f}ms for {audio_duration:.1f}s audio)")
                
                # Check if we're meeting latency targets
                if inference_time > 1000:  # 1 second target
                    logger.warning(f"⚠️ Latency above target: {inference_time:.0f}ms > 1000ms")
            
            return text
            
        except Exception as e:
            logger.error(f"❌ Transcription failed: {e}")
            return None
    
    def transcribe_file(self, audio_path: str) -> Optional[str]:
        """
        Transcribe audio from a file.
        
        Args:
            audio_path: Path to audio file (supports wav, mp3, etc.)
            
        Returns:
            Transcribed text, or None if transcription failed
        """
        if self.model is None:
            logger.error("❌ Model not loaded. Call load_model() first.")
            return None
        
        try:
            logger.info(f"📁 Transcribing file: {audio_path}")
            
            # Load audio file
            # For WAV files (our VAD output), load directly with scipy to avoid ffmpeg dependency
            # For other formats, use whisper.load_audio (requires ffmpeg)
            if audio_path.lower().endswith('.wav'):
                logger.debug("📂 Loading WAV file with scipy (no ffmpeg needed)")
                from scipy.io import wavfile
                sample_rate, audio_data = wavfile.read(audio_path)
                
                # Convert to float32 mono as Whisper expects
                if audio_data.dtype == np.int16:
                    audio = audio_data.astype(np.float32) / 32768.0
                elif audio_data.dtype == np.int32:
                    audio = audio_data.astype(np.float32) / 2147483648.0
                elif audio_data.dtype == np.uint8:
                    audio = (audio_data.astype(np.float32) - 128.0) / 128.0
                else:
                    audio = audio_data.astype(np.float32)
                
                # Handle stereo -> mono conversion
                if audio.ndim > 1:
                    audio = audio.mean(axis=1)
                
                # Resample to 16kHz if needed (Whisper requirement)
                if sample_rate != 16000:
                    logger.warning(f"⚠️ Resampling from {sample_rate}Hz to 16kHz...")
                    # Simple linear interpolation resampling
                    duration = len(audio) / sample_rate
                    new_length = int(duration * 16000)
                    audio = np.interp(
                        np.linspace(0, len(audio), new_length),
                        np.arange(len(audio)),
                        audio
                    )
            else:
                # For non-WAV files, use whisper.load_audio (requires ffmpeg)
                logger.debug("📂 Loading audio file with ffmpeg (whisper.load_audio)")
                audio = whisper.load_audio(audio_path)
            
            return self.transcribe(audio)
            
        except Exception as e:
            logger.error(f"❌ File transcription failed: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics.
        
        Returns:
            Dictionary with average latency, min/max, and inference count
        """
        if not self.inference_times:
            return {
                "count": 0,
                "avg_latency_ms": 0,
                "min_latency_ms": 0,
                "max_latency_ms": 0
            }
        
        return {
            "count": len(self.inference_times),
            "avg_latency_ms": np.mean(self.inference_times),
            "min_latency_ms": np.min(self.inference_times),
            "max_latency_ms": np.max(self.inference_times),
            "device": self.device,
            "model_size": self.model_size
        }
    
    def unload_model(self):
        """Unload model to free memory."""
        if self.model is not None:
            del self.model
            self.model = None
            if self.device == "cuda":
                torch.cuda.empty_cache()
            logger.info("✅ Whisper model unloaded")


# Convenience function for quick usage
def create_whisper_stt(
    model_size: str = "base",
    device: Optional[str] = None
) -> WhisperSTT:
    """
    Factory function to create and load WhisperSTT instance.
    
    Args:
        model_size: Whisper model size ('tiny', 'base', 'small', etc.)
        device: Device to use ('cuda' or 'cpu')
        
    Returns:
        Initialized WhisperSTT instance
    """
    stt = WhisperSTT(model_size=model_size, device=device)
    stt.load_model()
    return stt


if __name__ == "__main__":
    # Test the WhisperSTT handler
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("="*60)
    print("🧪 Testing WhisperSTT Handler")
    print("="*60)
    
    # Test 1: Initialize with GPU
    stt = create_whisper_stt(model_size="base")
    
    # Test 2: Transcribe dummy audio
    print("\n📝 Test 1: Transcribe 2-second silence")
    dummy_audio = np.zeros(16000 * 2, dtype=np.float32)
    result = stt.transcribe(dummy_audio)
    print(f"Result: '{result}'")
    
    # Test 3: Show stats
    print("\n📊 Performance Stats:")
    stats = stt.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    print("\n✅ WhisperSTT handler test complete!")
