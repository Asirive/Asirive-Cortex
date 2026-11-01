"""
GLM-4.6V API Handler - Z.ai Multimodal Vision Model (Final Fallback)
Project-Cortex v2.0 - Layer 2 (Thinker) - Fallback Tier 2

This handler provides the final fallback when both Gemini APIs fail.
Uses Z.ai's GLM-4.6V model for vision + text generation.

Features:
- 128K context length
- Native multimodal tool use
- Video/Image/Text/File input
- Streaming support
- Base64 image encoding
- OpenAI-compatible API

Pricing: Check https://open.bigmodel.cn for current rates
Latency: ~1-2s (similar to Gemini HTTP)

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: December 23, 2025
Status: PRODUCTION READY
"""

import logging
import time
import base64
from typing import Optional, Union
from io import BytesIO

from zai import ZaiClient
from zai.core import (
    APIAuthenticationError,
    APIReachLimitError,
    APIRequestFailedError,
    APITimeoutError,
    APIInternalError,
    APIServerFlowExceedError,
    APIStatusError
)
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


class GLM4VHandler:
    """
    Z.ai GLM-4.6V API handler (final fallback).
    
    OpenAI-compatible API with vision support.
    128K context, multimodal tool calling.
    
    Usage:
        handler = GLM4VHandler(api_key="YOUR_ZAI_KEY")
        response = handler.generate_content(
            text="What's in this image?",
            image=pil_image
        )
        print(response)
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "glm-4.6v",
        api_base: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_retries: int = 3,
        initial_delay: float = 1.0
    ):
        """
        Initialize GLM-4.6V handler with official SDK.
        
        Args:
            api_key: Z.ai API key (ZAI_API_KEY)
            model: Model name (glm-4.6v, glm-4.6v-flash, glm-4.6v-flashx)
            api_base: API base URL (optional, uses SDK default)
            system_instruction: System prompt
            temperature: AI creativity (0.0-1.0)
            max_retries: Max retry attempts
            initial_delay: Initial retry delay
        """
        self.api_key = api_key
        self.model = model
        self.system_instruction = system_instruction or self._default_system_instruction()
        self.temperature = temperature
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        
        # Initialize official SDK client
        if api_base:
            self.client = ZaiClient(api_key=api_key, base_url=api_base)
        else:
            self.client = ZaiClient(api_key=api_key)
        
        # Performance tracking
        self.request_count = 0
        self.total_latency = 0.0
        self.quota_exceeded = False
        self.insufficient_balance = False
        
        logger.info(f"✅ GLM4VHandler initialized (model={model}, SDK=zai-sdk)")
    
    @staticmethod
    def _default_system_instruction() -> str:
        """Default system instruction for assistive AI."""
        return """You are an AI assistant for a visually impaired person using Project-Cortex, 
        a wearable device with camera and sensors. Your role is to:
        
        1. Describe visual scenes clearly and concisely
        2. Read text from images (OCR)
        3. Identify objects and their locations
        4. Provide navigation guidance
        5. Answer questions about the environment
        
        Guidelines:
        - Be concise (under 50 words per response)
        - Prioritize safety-critical information
        - Use simple, clear language
        - Avoid technical jargon
        - Respond naturally in conversational tone
        - If you see obstacles, warn immediately"""
    
    def generate_content(
        self,
        text: str,
        image: Optional[Union[Image.Image, bytes, np.ndarray]] = None,
        stream: bool = False
    ) -> Optional[str]:
        """
        Generate content from text + optional image using official SDK.
        
        Args:
            text: Text prompt/query
            image: Optional image (PIL Image, bytes, or numpy array)
            stream: Enable streaming (not implemented yet)
        
        Returns:
            str: Generated text response, or None on failure
        """
        delay = self.initial_delay
        
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                
                # Build messages (OpenAI format)
                messages = []
                
                # Add system message
                messages.append({
                    "role": "system",
                    "content": self.system_instruction
                })
                
                # Build user message content
                user_content = []
                
                # Add image if provided (base64 encoded)
                if image is not None:
                    image_url = self._prepare_image_url(image)
                    if image_url:
                        user_content.append({
                            "type": "image_url",
                            "image_url": {"url": image_url}
                        })
                
                # Add text
                user_content.append({
                    "type": "text",
                    "text": text
                })
                
                messages.append({
                    "role": "user",
                    "content": user_content
                })
                
                logger.debug(f"📤 Sending request to Z.ai (attempt {attempt + 1}/{self.max_retries})")
                logger.debug(f"   Text: {text[:50]}...")
                logger.debug(f"   Image: {'Yes' if image is not None else 'No'}")
                
                # Call Z.ai API using official SDK
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    thinking={"type": "enabled"},
                    stream=stream
                )
                
                # Debug: Log response structure
                logger.debug(f"📥 Response type: {type(response)}")
                logger.debug(f"📥 Response: {response}")
                
                # Parse response (handle both OpenAI and Anthropic formats)
                try:
                    if hasattr(response, 'choices') and response.choices:
                        # OpenAI format
                        content = response.choices[0].message.content
                    elif hasattr(response, 'content') and response.content:
                        # Anthropic format
                        content = response.content[0].text if isinstance(response.content, list) else response.content
                    else:
                        logger.error(f"❌ Unknown response format: {response}")
                        return None
                except (AttributeError, IndexError, KeyError) as e:
                    logger.error(f"❌ Failed to parse response: {e}")
                    logger.error(f"   Response object: {response}")
                    return None
                
                # Calculate latency
                latency = time.time() - start_time
                self.request_count += 1
                self.total_latency += latency
                
                logger.info(f"✅ Z.ai response received in {latency:.2f}s (avg: {self.average_latency:.2f}s)")
                
                return content
                
            except APIAuthenticationError as err:
                logger.error("❌ INVALID Z.ai API KEY - check ZAI_API_KEY")
                logger.error(f"   Details: {err}")
                return None
            
            except APIReachLimitError as err:
                # Parse error message to distinguish rate limit vs billing
                error_msg = str(err)
                
                if "1113" in error_msg or "Insufficient balance" in error_msg or "no resource package" in error_msg:
                    logger.error("❌ INSUFFICIENT BALANCE - Z.ai account needs recharge")
                    logger.error(f"   Error Code: 1113")
                    logger.error(f"   Message: {err}")
                    logger.error("   ⚠️ ACTION REQUIRED: Add credits at https://open.bigmodel.cn")
                    self.insufficient_balance = True
                else:
                    logger.error("❌ RATE LIMIT EXCEEDED (Z.ai)")
                    logger.error(f"   Details: {err}")
                    self.quota_exceeded = True
                
                return None
            
            except APIRequestFailedError as err:
                logger.error(f"❌ INVALID REQUEST to Z.ai API")
                logger.error(f"   Details: {err}")
                if attempt < self.max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                return None
            
            except APITimeoutError as err:
                logger.warning(f"⚠️ Request timeout on attempt {attempt + 1}")
                logger.warning(f"   Details: {err}")
                if attempt < self.max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                return None
            
            except APIInternalError as err:
                logger.error(f"❌ Z.ai SERVER ERROR")
                logger.error(f"   Details: {err}")
                if attempt < self.max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                return None
            
            except APIServerFlowExceedError as err:
                logger.warning(f"⚠️ Z.ai server overloaded")
                logger.warning(f"   Details: {err}")
                if attempt < self.max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                return None
            
            except APIStatusError as err:
                logger.error(f"❌ Z.ai API STATUS ERROR: {err.status_code}")
                logger.error(f"   Message: {err.message}")
                if attempt < self.max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                return None
            
            except Exception as err:
                logger.error(f"❌ Unexpected error on attempt {attempt + 1}")
                logger.error(f"   Error: {err}")
                if attempt < self.max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                return None
        
        logger.error(f"❌ All {self.max_retries} retry attempts failed")
        return None
    
    def _prepare_image_url(
        self,
        image: Union[Image.Image, bytes, np.ndarray]
    ) -> Optional[str]:
        """
        Convert image to base64 data URL for Z.ai API.
        
        Args:
            image: PIL Image, bytes, or numpy array
        
        Returns:
            str: Base64 data URL, or None on failure
        """
        try:
            # Convert to PIL Image if needed
            if isinstance(image, np.ndarray):
                # Convert BGR to RGB if needed
                if len(image.shape) == 3 and image.shape[2] == 3:
                    image_rgb = image[:, :, ::-1]
                else:
                    image_rgb = image
                pil_image = Image.fromarray(image_rgb)
                
            elif isinstance(image, bytes):
                pil_image = Image.open(BytesIO(image))
                
            elif isinstance(image, Image.Image):
                pil_image = image
                
            else:
                logger.error(f"❌ Unsupported image type: {type(image)}")
                return None
            
            # Convert to JPEG bytes
            buffer = BytesIO()
            pil_image.save(buffer, format='JPEG', quality=85)
            image_bytes = buffer.getvalue()
            
            # Encode to base64
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            
            # Create data URL
            data_url = f"data:image/jpeg;base64,{base64_image}"
            
            logger.debug(f"📷 Image encoded: {len(base64_image)} chars")
            
            return data_url
            
        except Exception as e:
            logger.error(f"❌ Image preparation failed: {e}")
            return None
    
    @property
    def average_latency(self) -> float:
        """Calculate average request latency."""
        if self.request_count == 0:
            return 0.0
        return self.total_latency / self.request_count
    
    def reset_quota_flag(self):
        """Reset quota exceeded flag (for testing)."""
        self.quota_exceeded = False
        logger.info("🔄 Quota flag reset")


# Example usage
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    api_key = os.getenv("ZAI_API_KEY")
    
    if not api_key:
        print("❌ ZAI_API_KEY not found")
        print("Get your API key at: https://open.bigmodel.cn")
        exit(1)
    
    # Create handler
    handler = GLM4VHandler(api_key=api_key)
    
    # Test text-only
    response = handler.generate_content("What is the capital of China?")
    print(f"Response: {response}")
    
    # Test with image
    try:
        test_image = Image.new('RGB', (200, 200), color='blue')
        response = handler.generate_content(
            "What color is this image?",
            image=test_image
        )
        print(f"Image response: {response}")
    except Exception as e:
        print(f"Image test failed: {e}")
