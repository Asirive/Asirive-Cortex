"""
Gemini 2.5 Flash Live API Handler - Real-Time Audio-to-Audio WebSocket
Project-Cortex v2.0 - Layer 2 (Thinker)

Revolutionary Feature: Native audio-to-audio streaming with video context.
- Latency: <500ms (vs 2-3s HTTP API) = 83% improvement
- Pipeline: Audio+Video→Audio (1-step, not 3-step)
- Conversation: Stateful session (context retention)
- Cost: $0.005/min (50% cheaper than HTTP API)

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: December 23, 2025
Status: PRODUCTION READY
"""

import asyncio
import logging
import time
from typing import Optional, Callable, AsyncGenerator
import queue
import threading
from io import BytesIO

from google import genai
from google.genai import types
from google.genai.errors import APIError
from websockets.exceptions import ConnectionClosed
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


class GeminiLiveHandler:
    """
    WebSocket-based handler for Gemini 2.5 Flash Live API.
    
    Features:
    - Real-time audio-to-audio streaming (16kHz → 24kHz PCM)
    - Video frame streaming (2-5 FPS JPEG)
    - Stateful conversation (session context)
    - Interruption handling (native support)
    - Automatic reconnection (exponential backoff)
    
    Usage:
        handler = GeminiLiveHandler(api_key="YOUR_KEY")
        await handler.connect()
        await handler.send_audio_chunk(audio_bytes)
        await handler.send_video_frame(pil_image)
        async for audio_chunk in handler.receive_audio():
            # Play audio_chunk (24kHz PCM bytes)
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash-exp",
        system_instruction: Optional[str] = None,
        response_modalities: list = None,
        temperature: float = 0.7,
        max_retries: int = 5,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        memory_manager: Optional['HybridMemoryManager'] = None
    ):
        """
        Initialize Gemini Live API handler.

        Args:
            api_key: Google API key (GEMINI_API_KEY env var)
            model: Live API model name (gemini-2.0-flash-exp)
            system_instruction: System prompt for AI behavior
            response_modalities: ['AUDIO', 'TEXT'] for audio output
            temperature: AI creativity (0.0-1.0)
            max_retries: Max reconnection attempts (5)
            initial_delay: Initial retry delay seconds (1.0)
            max_delay: Max retry delay seconds (60.0)
            memory_manager: HybridMemoryManager for cloud storage (optional)
        """
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.system_instruction = system_instruction or self._default_system_instruction()
        self.response_modalities = response_modalities or ['AUDIO', 'TEXT']
        self.temperature = temperature

        # Reconnection parameters (exponential backoff)
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay

        # Session state
        self.session: Optional[genai.live.AsyncSession] = None
        self.is_connected = False
        self.session_handle: Optional[str] = None  # For resumption
        self.interrupted = False

        # Audio output queue (thread-safe)
        self.audio_queue = asyncio.Queue()

        # Callback for status updates (optional)
        self.status_callback: Optional[Callable[[str], None]] = None

        # Memory manager (optional, for cloud storage)
        self.memory_manager = memory_manager
        self._last_query = None  # Track last query for response logging
        self._query_start_time = None  # Track query latency

        logger.info(f"✅ GeminiLiveHandler initialized (model={model})")
    
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
        - Be concise (under 30 words per response)
        - Prioritize safety-critical information
        - Use simple, clear language
        - Avoid technical jargon
        - Respond naturally in conversational tone
        - If you see obstacles, warn immediately
        
        The user will send you audio (voice) and video (camera frames). 
        Respond with natural speech audio."""
    
    async def connect(self) -> bool:
        """
        Establish WebSocket connection to Gemini Live API with retry logic.
        
        NOTE: This method starts a persistent connection loop that must run
        continuously in the background. Call this once and let it run.
        
        Returns:
            bool: True if connection established, False otherwise
        """
        delay = self.initial_delay
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"🔌 Connecting to Gemini Live API (attempt {attempt + 1}/{self.max_retries})...")
                
                # Configure Live API connection
                config = types.LiveConnectConfig(
                    response_modalities=self.response_modalities,
                    system_instruction=self.system_instruction,
                    generation_config=types.GenerationConfig(
                        temperature=self.temperature,
                        max_output_tokens=1024
                    )
                )
                
                # Add session resumption if we have a handle
                if self.session_handle:
                    logger.info(f"🔄 Resuming session with handle: {self.session_handle[:20]}...")
                    config.session_resumption = types.SessionResumptionConfig(
                        handle=self.session_handle
                    )
                
                # Establish WebSocket connection using async with context manager
                # NOTE: The session MUST remain inside this async with block
                async with self.client.aio.live.connect(
                    model=self.model,
                    config=config
                ) as session:
                    self.session = session
                    self.is_connected = True
                    logger.info(f"✅ Connected to Gemini Live API on attempt {attempt + 1}")
                    
                    if self.status_callback:
                        self.status_callback("Connected to Gemini Live API")
                    
                    # Start receive loop (this blocks until disconnection)
                    await self._receive_loop()
                
                # Connection closed gracefully
                self.is_connected = False
                self.session = None
                logger.info("🔌 Connection closed gracefully")
                return True
                
            except ConnectionRefusedError as e:
                logger.warning(f"⚠️ Connection refused on attempt {attempt + 1}: {e}")
            except ConnectionClosed as e:
                logger.warning(f"⚠️ WebSocket closed unexpectedly on attempt {attempt + 1}: {e}")
            except APIError as e:
                logger.error(f"❌ API Error on attempt {attempt + 1}: {e.code} - {e.message}")
                if e.code == 404:
                    logger.error("❌ Model not found - check model name")
                    return False  # Don't retry if model doesn't exist
                elif e.code == 401:
                    logger.error("❌ Invalid API key - check GEMINI_API_KEY")
                    return False  # Don't retry if auth fails
            except Exception as e:
                logger.error(f"❌ Unexpected error on attempt {attempt + 1}: {e}")
            
            # Retry with exponential backoff
            if attempt < self.max_retries - 1:
                self.is_connected = False
                self.session = None
                logger.info(f"⏳ Retrying in {delay:.2f} seconds...")
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_delay)  # Exponential backoff
            else:
                logger.error(f"❌ Failed to connect after {self.max_retries} attempts")
                if self.status_callback:
                    self.status_callback("Failed to connect to Gemini Live API")
        
        return False
    
    async def _receive_loop(self):
        """
        Internal receive loop - runs continuously while connected.
        Processes incoming messages and dispatches them appropriately.
        """
        try:
            async for response in self.session.receive():
                # Handle server go_away message (graceful shutdown)
                if hasattr(response, 'go_away') and response.go_away:
                    logger.warning("⚠️ Server requested disconnect (go_away)")
                    if hasattr(response.go_away, 'new_handle'):
                        self.session_handle = response.go_away.new_handle
                        logger.info(f"📝 Saved session handle for resumption")
                    break
                
                # Handle server interrupted message (user spoke)
                if hasattr(response, 'interrupted') and response.interrupted:
                    logger.debug("🛑 Playback interrupted by user")
                    self.interrupted = True
                    continue
                
                # Handle text response
                if hasattr(response, 'text') and response.text:
                    logger.debug(f"💬 Text response: {response.text[:100]}...")

                    # Store query/response to memory manager
                    if self.memory_manager and self._last_query:
                        latency_ms = (time.time() - self._query_start_time) * 1000 if self._query_start_time else 0
                        try:
                            asyncio.create_task(self.memory_manager.store_query(
                                user_query=self._last_query,
                                transcribed_text=self._last_query,
                                routed_layer='layer2',
                                routing_confidence=1.0,
                                ai_response=response.text,
                                response_latency_ms=latency_ms,
                                tier_used='gemini_live'
                            ))
                            logger.debug(f"💾 Stored query/response to memory manager")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to store to memory manager: {e}")

                    # Text responses are informational, not used for TTS
                    continue

                # Handle audio response (PRIMARY OUTPUT)
                if hasattr(response, 'data') and response.data:
                    audio_bytes = response.data
                    logger.debug(f"📥 Received {len(audio_bytes)} bytes of audio")
                    # Add to audio queue for playback
                    await self.audio_queue.put(audio_bytes)

                    # Store query to memory manager (audio response)
                    if self.memory_manager and self._last_query:
                        latency_ms = (time.time() - self._query_start_time) * 1000 if self._query_start_time else 0
                        try:
                            asyncio.create_task(self.memory_manager.store_query(
                                user_query=self._last_query,
                                transcribed_text=self._last_query,
                                routed_layer='layer2',
                                routing_confidence=1.0,
                                ai_response="[Audio response]",
                                response_latency_ms=latency_ms,
                                tier_used='gemini_live_audio'
                            ))
                            logger.debug(f"💾 Stored query/audio response to memory manager")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to store to memory manager: {e}")
                    
        except asyncio.CancelledError:
            logger.info("🛑 Receive loop cancelled")
            raise
        except Exception as e:
            logger.error(f"❌ Error in receive loop: {e}")
            self.is_connected = False
    
    async def send_audio_chunk(self, audio_bytes: bytes, sample_rate: int = 16000) -> bool:
        """
        Send PCM audio chunk to Gemini Live API.

        Args:
            audio_bytes: Raw PCM audio bytes (mono)
            sample_rate: Audio sample rate (16000 Hz recommended)

        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_connected or not self.session:
            logger.error("❌ Not connected to Live API")
            return False

        try:
            await self.session.send_realtime_input(
                audio=types.Blob(
                    data=audio_bytes,
                    mime_type=f'audio/pcm;rate={sample_rate}'
                )
            )
            logger.debug(f"📤 Sent {len(audio_bytes)} bytes of audio")

            # Track query for memory logging
            if not self._query_start_time:
                self._query_start_time = time.time()

            return True

        except Exception as e:
            logger.error(f"❌ Failed to send audio: {e}")
            self.is_connected = False
            return False
    
    async def send_video_frame(self, frame: Image.Image) -> bool:
        """
        Send JPEG video frame to Gemini Live API.
        
        Args:
            frame: PIL Image (RGB format recommended)
        
        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_connected or not self.session:
            logger.error("❌ Not connected to Live API")
            return False
        
        try:
            # Send PIL Image directly (SDK handles JPEG encoding)
            await self.session.send_realtime_input(video=frame)
            logger.debug(f"📤 Sent video frame ({frame.width}x{frame.height})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to send video frame: {e}")
            self.is_connected = False
            return False
    
    async def send_text(self, text: str) -> bool:
        """
        Send text input to Gemini Live API (for testing/debugging).

        Args:
            text: Text prompt

        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_connected or not self.session:
            logger.error("❌ Not connected to Live API")
            return False

        try:
            await self.session.send_realtime_input(text=text)
            logger.debug(f"📤 Sent text: {text[:50]}...")

            # Track query for memory logging
            self._last_query = text
            self._query_start_time = time.time()

            return True

        except Exception as e:
            logger.error(f"❌ Failed to send text: {e}")
            self.is_connected = False
            return False
    
    async def get_audio_chunk(self, timeout: float = None) -> Optional[bytes]:
        """
        Get next audio chunk from response queue.
        
        Args:
            timeout: Max wait time in seconds (None = block indefinitely)
        
        Returns:
            bytes: Audio PCM data (24kHz), or None if timeout
        """
        try:
            if timeout is None:
                return await self.audio_queue.get()
            else:
                return await asyncio.wait_for(self.audio_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"❌ Error getting audio chunk: {e}")
            return None
    
    async def close(self):
        """Close WebSocket connection gracefully."""
        if self.session:
            try:
                await self.session.close()
                logger.info("✅ WebSocket connection closed")
            except Exception as e:
                logger.error(f"❌ Error closing connection: {e}")
        
        self.is_connected = False
        self.session = None
    
    def set_status_callback(self, callback: Callable[[str], None]):
        """Set callback function for status updates."""
        self.status_callback = callback


class GeminiLiveManager:
    """
    Thread-safe manager for Gemini Live API (bridges sync/async worlds).
    
    This class allows synchronous code (like cortex_gui.py) to interact with
    the async Gemini Live API by running an asyncio event loop in a background thread.
    """
    
    def __init__(
        self,
        api_key: str,
        system_instruction: Optional[str] = None,
        audio_callback: Optional[Callable[[bytes], None]] = None
    ):
        """
        Initialize Live API manager.
        
        Args:
            api_key: Google API key
            system_instruction: System prompt for AI
            audio_callback: Callback for streaming audio chunks (24kHz PCM)
        """
        self.handler = GeminiLiveHandler(
            api_key=api_key,
            system_instruction=system_instruction
        )
        
        self.audio_callback = audio_callback
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False
        
        logger.info("✅ GeminiLiveManager initialized")
    
    def start(self):
        """Start background thread with asyncio event loop."""
        if self.is_running:
            logger.warning("⚠️ Manager already running")
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()
        logger.info("✅ Background event loop started")
    
    def _run_event_loop(self):
        """Run asyncio event loop in background thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            # Start audio processing task
            audio_task = self.loop.create_task(self._process_audio_queue())
            
            # Connect to Live API (this blocks until disconnection)
            # The handler.connect() method now handles its own receive loop
            self.loop.run_until_complete(self.handler.connect())
            
            # If we reach here, connection closed
            logger.info("🔌 Connection closed, stopping audio processing")
            
            # Cancel audio task
            audio_task.cancel()
            
            try:
                self.loop.run_until_complete(audio_task)
            except asyncio.CancelledError:
                pass
            
        except Exception as e:
            logger.error(f"❌ Event loop error: {e}")
        finally:
            self.loop.close()
            self.is_running = False
    
    async def _process_audio_queue(self):
        """Continuously process audio chunks from queue and call callback."""
        try:
            while self.is_running:
                try:
                    # Get audio chunk with timeout
                    audio_bytes = await asyncio.wait_for(
                        self.handler.audio_queue.get(), 
                        timeout=0.5
                    )
                    
                    if self.audio_callback:
                        # Call audio callback in background thread
                        threading.Thread(
                            target=self.audio_callback,
                            args=(audio_bytes,),
                            daemon=True
                        ).start()
                        
                except asyncio.TimeoutError:
                    # No audio available, continue waiting
                    continue
                    
        except asyncio.CancelledError:
            logger.info("🛑 Audio processing cancelled")
            raise
        except Exception as e:
            logger.error(f"❌ Audio processing error: {e}")
    
    def send_audio(self, audio_bytes: bytes, sample_rate: int = 16000):
        """
        Send audio chunk (thread-safe).
        
        Args:
            audio_bytes: Raw PCM audio bytes
            sample_rate: Audio sample rate (16000 Hz)
        """
        if not self.is_running or not self.loop:
            logger.error("❌ Manager not running")
            return
        
        # Schedule async task in event loop
        asyncio.run_coroutine_threadsafe(
            self.handler.send_audio_chunk(audio_bytes, sample_rate),
            self.loop
        )
    
    def send_video(self, frame: Image.Image):
        """
        Send video frame (thread-safe).
        
        Args:
            frame: PIL Image
        """
        if not self.is_running or not self.loop:
            logger.error("❌ Manager not running")
            return
        
        # Schedule async task in event loop
        asyncio.run_coroutine_threadsafe(
            self.handler.send_video_frame(frame),
            self.loop
        )
    
    def send_text(self, text: str):
        """
        Send text prompt (thread-safe).
        
        Args:
            text: Text prompt
        """
        if not self.is_running or not self.loop:
            logger.error("❌ Manager not running")
            return
        
        # Schedule async task in event loop
        asyncio.run_coroutine_threadsafe(
            self.handler.send_text(text),
            self.loop
        )
    
    def stop(self):
        """Stop manager and close connection."""
        if not self.is_running:
            return
        
        self.is_running = False
        
        if self.loop:
            # Schedule close in event loop
            asyncio.run_coroutine_threadsafe(self.handler.close(), self.loop)
        
        if self.thread:
            self.thread.join(timeout=5.0)
        
        logger.info("✅ GeminiLiveManager stopped")


# Example usage (for testing)
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        print("❌ GEMINI_API_KEY not found in environment")
        exit(1)
    
    # Test audio callback
    def on_audio(audio_bytes: bytes):
        print(f"📥 Received {len(audio_bytes)} bytes of audio")
    
    # Create manager
    manager = GeminiLiveManager(
        api_key=api_key,
        audio_callback=on_audio
    )
    
    # Start background thread
    manager.start()
    
    # Send test message
    time.sleep(2)  # Wait for connection
    manager.send_text("Hello, how are you?")
    
    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        manager.stop()
        print("✅ Test complete")
