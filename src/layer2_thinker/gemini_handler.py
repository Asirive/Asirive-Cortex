"""
Layer 2: Gemini Vision Handler - Cloud-Based Scene Analysis

This module handles complex scene understanding using Google Gemini 1.5 Flash.
Provides OCR, detailed scene descriptions, and contextual analysis for the visually impaired.

Key Features:
- Multimodal AI (vision + text) with Gemini 1.5 Flash
- OCR for reading text in images
- Detailed scene descriptions
- API key management with environment variables
- Rate limiting and error handling

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import logging
import os
import time
from typing import Optional, Dict, Any, List
from pathlib import Path
import base64
from io import BytesIO

import numpy as np
from PIL import Image
from dotenv import load_dotenv

# Import Google Generative AI SDK
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logging.warning("⚠️ google-generativeai not installed. Run: pip install google-generativeai")

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class GeminiVision:
    """
    Cloud-based vision analysis handler using Google Gemini 1.5 Flash.
    
    This is Layer 2 (The Thinker) - providing detailed scene understanding
    for complex queries that Layer 1's local YOLO cannot handle.
    """
    
    _instance = None  # Singleton pattern
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern to prevent multiple API client initializations."""
        if cls._instance is None:
            cls._instance = super(GeminiVision, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-1.5-flash-latest",
        max_tokens: int = 2048,
        temperature: float = 0.7
    ):
        """
        Initialize Gemini Vision API client.
        
        Args:
            api_key: Google API key (reads from GOOGLE_API_KEY env var if None)
            model_name: Gemini model to use (default: gemini-1.5-flash-latest)
            max_tokens: Maximum tokens in response
            temperature: Response randomness (0.0-1.0, lower = more deterministic)
        """
        if self._initialized:
            return
        
        if not GEMINI_AVAILABLE:
            raise ImportError(
                "google-generativeai package not installed. "
                "Install it with: pip install google-generativeai"
            )
        
        logger.info("🧠 Initializing Gemini Vision Handler...")
        
        # Get API key from environment or parameter
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            raise ValueError(
                "Google API key not found. Set GOOGLE_API_KEY in .env file or pass as parameter.\n"
                "Get your API key from: https://makersuite.google.com/app/apikey"
            )
        
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.model = None
        
        # Performance tracking
        self.request_times = []
        self.request_count = 0
        self.error_count = 0
        
        logger.info(f"📋 Gemini Config:")
        logger.info(f"   Model: {model_name}")
        logger.info(f"   Max Tokens: {max_tokens}")
        logger.info(f"   Temperature: {temperature}")
        logger.info(f"   API Key: {self.api_key[:8]}...{self.api_key[-4:]}")
        
        self._initialized = True
    
    def initialize(self) -> bool:
        """
        Initialize the Gemini API client and model.
        
        Returns:
            True if initialization successful, False otherwise
        """
        if self.model is not None:
            logger.info("✅ Gemini model already initialized")
            return True
        
        try:
            logger.info("⏳ Configuring Gemini API...")
            
            # Configure API key
            genai.configure(api_key=self.api_key)
            
            # Initialize model
            self.model = genai.GenerativeModel(
                model_name=self.model_name,
                generation_config={
                    "max_output_tokens": self.max_tokens,
                    "temperature": self.temperature,
                }
            )
            
            logger.info("✅ Gemini model initialized successfully")
            
            # Test with a simple query
            logger.info("🔥 Running connection test...")
            test_response = self.model.generate_content("Hello")
            logger.info(f"✅ Connection test passed: '{test_response.text[:50]}...'")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini: {e}")
            self.error_count += 1
            return False
    
    def _numpy_to_pil(self, image: np.ndarray) -> Image.Image:
        """
        Convert numpy array to PIL Image.
        
        Args:
            image: Image as numpy array (OpenCV format: BGR)
            
        Returns:
            PIL Image object
        """
        # Convert BGR to RGB if needed
        if len(image.shape) == 3 and image.shape[2] == 3:
            image = image[:, :, ::-1]  # BGR -> RGB
        
        return Image.fromarray(image.astype('uint8'))
    
    def describe_scene(
        self,
        image: np.ndarray,
        prompt: Optional[str] = None,
        detailed: bool = False,
        log_latency: bool = True
    ) -> Optional[str]:
        """
        Get a description of the scene in the image.
        
        Args:
            image: Image as numpy array (OpenCV format)
            prompt: Custom prompt (uses default if None)
            detailed: If True, request more detailed description
            log_latency: If True, log API latency
            
        Returns:
            Scene description text, or None if failed
        """
        if self.model is None:
            logger.error("❌ Model not initialized. Call initialize() first.")
            return None
        
        try:
            start_time = time.time()
            
            # Convert numpy array to PIL Image
            pil_image = self._numpy_to_pil(image)
            
            # Construct prompt
            if prompt is None:
                if detailed:
                    prompt = (
                        "You are assisting a visually impaired person. "
                        "Describe this scene in detail, including: "
                        "1) Main objects and their positions "
                        "2) People and their activities "
                        "3) Any text visible in the image "
                        "4) Potential hazards or obstacles "
                        "5) Overall context and setting. "
                        "Be concise but thorough."
                    )
                else:
                    prompt = (
                        "You are assisting a visually impaired person. "
                        "Briefly describe what's in this image, focusing on important objects, "
                        "people, and any potential hazards. Be concise."
                    )
            
            # Generate content
            response = self.model.generate_content([prompt, pil_image])
            
            request_time = (time.time() - start_time) * 1000  # Convert to ms
            self.request_times.append(request_time)
            self.request_count += 1
            
            description = response.text.strip()
            
            if log_latency:
                logger.info(
                    f"🧠 Scene Description: '{description[:80]}...' "
                    f"(latency: {request_time:.0f}ms)"
                )
                
                # Check if we're meeting latency targets
                if request_time > 5000:  # 5 second target
                    logger.warning(f"⚠️ Latency above target: {request_time:.0f}ms > 5000ms")
            
            return description
            
        except Exception as e:
            logger.error(f"❌ Scene description failed: {e}")
            self.error_count += 1
            return None
    
    def read_text(
        self,
        image: np.ndarray,
        log_latency: bool = True
    ) -> Optional[str]:
        """
        Extract and read text from the image (OCR).
        
        Args:
            image: Image as numpy array (OpenCV format)
            log_latency: If True, log API latency
            
        Returns:
            Extracted text, or None if failed or no text found
        """
        if self.model is None:
            logger.error("❌ Model not initialized. Call initialize() first.")
            return None
        
        try:
            start_time = time.time()
            
            # Convert numpy array to PIL Image
            pil_image = self._numpy_to_pil(image)
            
            # Construct OCR prompt
            prompt = (
                "You are assisting a visually impaired person. "
                "Read all visible text in this image, exactly as written. "
                "If there is no text, respond with 'No text found'. "
                "Organize the text logically if there are multiple sections."
            )
            
            # Generate content
            response = self.model.generate_content([prompt, pil_image])
            
            request_time = (time.time() - start_time) * 1000  # Convert to ms
            self.request_times.append(request_time)
            self.request_count += 1
            
            text = response.text.strip()
            
            if log_latency:
                if text.lower() == "no text found":
                    logger.info(f"📄 OCR: No text detected (latency: {request_time:.0f}ms)")
                else:
                    logger.info(
                        f"📄 OCR: '{text[:80]}...' "
                        f"(latency: {request_time:.0f}ms)"
                    )
            
            return text
            
        except Exception as e:
            logger.error(f"❌ OCR failed: {e}")
            self.error_count += 1
            return None
    
    def answer_question(
        self,
        image: np.ndarray,
        question: str,
        log_latency: bool = True
    ) -> Optional[str]:
        """
        Answer a specific question about the image.
        
        Args:
            image: Image as numpy array (OpenCV format)
            question: User's question about the image
            log_latency: If True, log API latency
            
        Returns:
            Answer to the question, or None if failed
        """
        if self.model is None:
            logger.error("❌ Model not initialized. Call initialize() first.")
            return None
        
        try:
            start_time = time.time()
            
            # Convert numpy array to PIL Image
            pil_image = self._numpy_to_pil(image)
            
            # Construct prompt with context
            prompt = (
                f"You are assisting a visually impaired person. "
                f"Answer this question about the image: {question}\n\n"
                f"Provide a clear, concise answer focused on what they need to know."
            )
            
            # Generate content
            response = self.model.generate_content([prompt, pil_image])
            
            request_time = (time.time() - start_time) * 1000  # Convert to ms
            self.request_times.append(request_time)
            self.request_count += 1
            
            answer = response.text.strip()
            
            if log_latency:
                logger.info(
                    f"❓ Q&A: '{question}' → '{answer[:80]}...' "
                    f"(latency: {request_time:.0f}ms)"
                )
            
            return answer
            
        except Exception as e:
            logger.error(f"❌ Q&A failed: {e}")
            self.error_count += 1
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get performance and usage statistics.
        
        Returns:
            Dictionary with request count, latency stats, and error rate
        """
        if not self.request_times:
            return {
                "request_count": self.request_count,
                "error_count": self.error_count,
                "avg_latency_ms": 0,
                "min_latency_ms": 0,
                "max_latency_ms": 0,
                "error_rate": 0.0
            }
        
        return {
            "request_count": self.request_count,
            "error_count": self.error_count,
            "avg_latency_ms": np.mean(self.request_times),
            "min_latency_ms": np.min(self.request_times),
            "max_latency_ms": np.max(self.request_times),
            "error_rate": self.error_count / max(self.request_count, 1),
            "model": self.model_name
        }


# Convenience function for quick usage
def create_gemini_vision(
    api_key: Optional[str] = None,
    model_name: str = "gemini-1.5-flash-latest"
) -> GeminiVision:
    """
    Factory function to create and initialize GeminiVision instance.
    
    Args:
        api_key: Google API key (reads from env if None)
        model_name: Gemini model to use
        
    Returns:
        Initialized GeminiVision instance
    """
    vision = GeminiVision(api_key=api_key, model_name=model_name)
    vision.initialize()
    return vision


if __name__ == "__main__":
    # Test the GeminiVision handler
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("="*60)
    print("🧪 Testing GeminiVision Handler")
    print("="*60)
    
    # Test 1: Initialize (will fail without API key)
    try:
        vision = create_gemini_vision()
        print("✅ Gemini initialized successfully")
        
        # Test 2: Create dummy image
        print("\n📝 Test: Scene description with dummy image")
        dummy_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        description = vision.describe_scene(dummy_image)
        print(f"Description: '{description}'")
        
        # Test 3: Show stats
        print("\n📊 Performance Stats:")
        stats = vision.get_stats()
        for key, value in stats.items():
            print(f"   {key}: {value}")
            
    except ValueError as e:
        print(f"⚠️ Test skipped: {e}")
        print("\n💡 To test Gemini Vision:")
        print("   1. Get API key from: https://makersuite.google.com/app/apikey")
        print("   2. Add to .env file: GOOGLE_API_KEY=your_key_here")
        print("   3. Run this test again")
    
    print("\n✅ GeminiVision handler test complete!")
