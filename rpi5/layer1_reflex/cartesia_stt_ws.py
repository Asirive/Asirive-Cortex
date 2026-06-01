"""
Cartesia Ink 2 WebSocket STT Handler - Real-time Streaming STT

Uses Cartesia's Ink 2 model via WebSocket for real-time speech-to-text
with built-in turn detection. Replaces Silero VAD + batch HTTP approach.

Key features:
- Built-in turn detection (no external VAD needed for speech boundaries)
- Streaming audio via WebSocket (100ms chunks)
- Turn lifecycle events: turn.start, turn.update, turn.eager_end, turn.end
- Lower latency than batch HTTP approach

Falls back to batch CartesiaSTT if WebSocket disconnects.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import asyncio
import json
import logging
import os
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.warning("websockets not installed. Run: pip install websockets>=12.0")


class CartesiaSTTWebSocket:
    """
    Real-time STT using Cartesia Ink 2 WebSocket turns endpoint.
    
    Streams audio chunks to WebSocket and receives turn events.
    Built-in turn detection eliminates need for external VAD for
    speech boundary detection.
    """

    WS_URL = "wss://api.cartesia.ai/stt/turns/websocket"
    MODEL = "ink-2"
    API_VERSION = "2026-03-01"

    def __init__(
        self,
        api_key: Optional[str] = None,
        sample_rate: int = 16000,
        encoding: str = "pcm_s16le",
    ):
        """
        Initialize Cartesia Ink 2 WebSocket STT handler.
        
        Args:
            api_key: Cartesia API key (falls back to CARTESIA_API_KEY env var)
            sample_rate: Audio sample rate in Hz (default 16000)
            encoding: Audio encoding format (default pcm_s16le)
        """
        self.api_key = api_key or os.getenv("CARTESIA_API_KEY")
        self.sample_rate = sample_rate
        self.encoding = encoding
        
        self._ws = None
        self._connected = False
        self._listen_task: Optional[asyncio.Task] = None
        self._turn_callbacks: list[Callable] = []
        
        # Stats
        self.request_count = 0
        self.total_latency = 0.0
        self.error_count = 0
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        
        self.available = bool(self.api_key) and WEBSOCKETS_AVAILABLE
        
        if not self.available:
            if not self.api_key:
                logger.warning("No CARTESIA_API_KEY — Cartesia Ink 2 WebSocket STT disabled")
            if not WEBSOCKETS_AVAILABLE:
                logger.warning("websockets not available — Cartesia Ink 2 WebSocket STT disabled")
        else:
            logger.info(f"✅ Cartesia Ink 2 WebSocket STT ready (model={self.MODEL})")

    async def connect(self) -> bool:
        """
        Open WebSocket connection to Cartesia STT turns endpoint.
        
        Returns:
            True if connected successfully, False otherwise
        """
        if not self.available:
            return False
        
        # Circuit breaker
        if self.consecutive_errors >= self.max_consecutive_errors:
            logger.warning(
                f"⚡ Circuit breaker: Cartesia WebSocket disabled after "
                f"{self.consecutive_errors} consecutive failures"
            )
            self.available = False
            return False
        
        try:
            url = (
                f"{self.WS_URL}?"
                f"model={self.MODEL}&"
                f"encoding={self.encoding}&"
                f"sample_rate={self.sample_rate}&"
                f"cartesia_version={self.API_VERSION}"
            )
            
            self._ws = await websockets.connect(
                url,
                additional_headers={"X-API-Key": self.api_key},
                ping_interval=20,
                ping_timeout=10,
            )
            
            self._connected = True
            self.consecutive_errors = 0
            logger.info("✅ Connected to Cartesia Ink 2 WebSocket STT")
            
            # Start background listener
            self._listen_task = asyncio.create_task(self._listen_for_events())
            
            return True
            
        except Exception as e:
            self.error_count += 1
            self.consecutive_errors += 1
            logger.error(f"❌ Failed to connect to Cartesia WebSocket: {e}")
            return False

    async def send_audio_chunk(self, pcm_bytes: bytes) -> bool:
        """
        Send audio chunk to WebSocket.
        
        Args:
            pcm_bytes: Raw PCM audio bytes (100ms chunks recommended)
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self._connected or not self._ws:
            return False
        
        try:
            await self._ws.send(pcm_bytes)
            return True
        except Exception as e:
            logger.warning(f"Failed to send audio chunk: {e}")
            self._connected = False
            return False

    def on_turn_end(self, callback: Callable):
        """
        Register callback for turn.end events.
        
        Callback signature: async def callback(transcript: str)
        """
        self._turn_callbacks.append(callback)

    async def _listen_for_events(self):
        """Background task: listen for turn events from WebSocket."""
        try:
            async for message in self._ws:
                try:
                    event = json.loads(message)
                    event_type = event.get("type")
                    
                    if event_type == "connected":
                        logger.debug(f"Cartesia STT connected: {event.get('request_id')}")
                    
                    elif event_type == "turn.start":
                        logger.debug("Cartesia STT: turn started")
                    
                    elif event_type == "turn.update":
                        transcript = event.get("transcript", "")
                        logger.debug(f"Cartesia STT: turn update: '{transcript[:50]}...'")
                    
                    elif event_type == "turn.eager_end":
                        transcript = event.get("transcript", "")
                        logger.debug(f"Cartesia STT: eager end: '{transcript[:50]}...'")
                    
                    elif event_type == "turn.end":
                        transcript = event.get("transcript", "")
                        self.request_count += 1
                        logger.info(f"🎤 Cartesia Ink 2: '{transcript}'")
                        
                        # Invoke callbacks
                        for callback in self._turn_callbacks:
                            try:
                                await callback(transcript)
                            except Exception as cb_err:
                                logger.error(f"Turn callback error: {cb_err}")
                    
                    elif event_type == "turn.resume":
                        logger.debug("Cartesia STT: turn resumed after eager_end")
                    
                    elif event_type == "error":
                        self.error_count += 1
                        logger.error(
                            f"Cartesia STT error: {event.get('title')} - "
                            f"{event.get('message')}"
                        )
                
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from Cartesia: {message[:100]}")
        
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Cartesia WebSocket connection closed")
            self._connected = False
        
        except Exception as e:
            logger.error(f"Cartesia WebSocket listener error: {e}")
            self._connected = False

    async def close(self):
        """Close WebSocket connection gracefully."""
        if not self._ws:
            return
        
        try:
            # Send close command
            await self._ws.send(json.dumps({"type": "close"}))
            
            # Wait for remaining events (with timeout)
            try:
                await asyncio.wait_for(self._drain_events(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            
            await self._ws.close()
            logger.info("Cartesia WebSocket STT closed")
        
        except Exception as e:
            logger.warning(f"Error closing Cartesia WebSocket: {e}")
        
        finally:
            self._connected = False
            self._ws = None
            
            if self._listen_task:
                self._listen_task.cancel()
                try:
                    await self._listen_task
                except asyncio.CancelledError:
                    pass
                self._listen_task = None

    async def _drain_events(self):
        """Drain remaining events after close command."""
        async for message in self._ws:
            event = json.loads(message)
            if event.get("type") == "turn.end":
                transcript = event.get("transcript", "")
                for callback in self._turn_callbacks:
                    try:
                        await callback(transcript)
                    except Exception as e:
                        logger.error(f"Drain callback error: {e}")

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket is currently connected."""
        return self._connected

    def get_stats(self) -> dict:
        """Get performance statistics."""
        avg_latency = (self.total_latency / self.request_count) if self.request_count > 0 else 0
        return {
            "engine": "cartesia_ink2_websocket",
            "available": self.available,
            "connected": self._connected,
            "requests": self.request_count,
            "errors": self.error_count,
            "avg_latency_ms": round(avg_latency, 1),
            "model": self.MODEL,
        }
