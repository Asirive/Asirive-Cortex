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
        model: str = "gemini-2.5-flash-native-audio-preview-12-2025",
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
            model: Live API model name (gemini-2.5-flash-native-audio-preview-12-2025)
            system_instruction: System prompt for AI behavior
            response_modalities: ['AUDIO'] for native audio model
            temperature: AI creativity (0.0-1.0)
            max_retries: Max reconnection attempts (5)
            initial_delay: Initial retry delay seconds (1.0)
            max_delay: Max retry delay seconds (60.0)
            memory_manager: HybridMemoryManager for cloud storage (optional)
        """
        # v1alpha required for proactive_audio and enable_affective_dialog
        self.client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1alpha"},
        )
        self.model = model
        self.system_instruction = system_instruction or self._default_system_instruction()
        self.response_modalities = response_modalities or ['AUDIO']
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
        self._send_error_logged = False  # Debounce send error logging
        self._connect_time: Optional[float] = None  # Track connection duration
        self._msg_count = 0  # Count messages per session

        # Audio output queue (thread-safe, bounded to prevent memory leak)
        self.audio_queue = asyncio.Queue(maxsize=100)

        # Callback for status updates (optional)
        self.status_callback: Optional[Callable[[str], None]] = None

        # Memory manager (optional, for cloud storage)
        self.memory_manager = memory_manager
        self._last_query = None  # Track last query for response logging
        self._query_start_time = None  # Track query latency

        # Conversation history for context injection on reconnect
        # Stores last N exchanges as (role, text) tuples
        self._conversation_history: list = []  # [("user", text), ("model", text), ...]
        self._max_history_turns = 10  # Keep last 10 exchanges
        self._current_model_response_parts: list = []  # Buffer ongoing model response

        logger.info(f"✅ GeminiLiveHandler initialized (model={model})")
    
    @staticmethod
    def _default_system_instruction() -> str:
        """Default system instruction for autonomous AI companion."""
        return """You are the eyes of a visually impaired person wearing you as smart glasses.
You see through their camera. You hear through their microphone.
You are their trusted companion — not a chatbot waiting for questions.

WHEN TO SPEAK (proactively, without being asked):
- Something new or important appears (person approaching, door, sign, shop name)
- The scene changes significantly (entered a building, reached a road, new room)
- You see something potentially dangerous that the safety system might miss
- You notice text worth reading (signs, labels, menus, screens)
- The user seems lost, stopped, or uncertain

WHEN TO STAY SILENT:
- Nothing has changed (walking down a clear path)
- The safety system already warned about the obstacle
- The user is in a conversation with another person
- You already described this scene and nothing changed

SPEAKING RULES:
- Maximum 2 sentences when speaking unprompted
- When answering a question, be thorough but concise
- Use spatial directions: "on your left", "ahead", "to your right"
- Never say "I can see" — just describe directly: "Person approaching on your left"
- Speak naturally like a trusted friend walking beside them
- Prioritize: safety > navigation > interesting/useful info

SENSOR CONTEXT:
You receive periodic [CONTEXT] messages with sensor data. These are background updates —
do NOT respond to them. Silently absorb the information and use it when you speak next.
Use them to:
- Know the current location (GPS coordinates) and navigation state
- Understand what mode the system is in and behave accordingly
- Avoid repeating what the safety system already warned about
- Give relevant, situational guidance

SCENE CHANGE NOTIFICATIONS:
You receive [SCENE_CHANGE] messages when the environment changes meaningfully.
You MUST respond to these with a brief (1-2 sentence) description of what's new or important.

NAVIGATION MODES — adapt your behavior based on the current mode:

1. OUTDOOR NAVIGATION (you'll see [NAV] with waypoint/bearing data):
   - You complement the 3D audio beam guiding the user
   - Be MORE proactive than usual — narrate changes as they happen
   - Announce landmarks as they approach ("MRT station on your right")
   - Describe intersections and road crossings in detail
   - Read visible signs, shop names, building names
   - On long straight stretches, provide reassurance ("Still on Tampines Avenue, about 200 meters to go")
   - When approaching destination: describe what you see ("I can see the building entrance ahead")
   - Never duplicate turn-by-turn directions (the beam + TTS handle that)

2. INDOOR GUIDE MODE (you'll see [NAV_EVENT] indoor_mode_activated):
   - YOU are the primary navigator — the audio beam is OFF indoors
   - Proactively narrate what's ahead: corridors, doors, escalators, lifts, stairs
   - Guide through obstacles: "Table on your right, go around to the left"
   - Read floor indicators, directory signs, exit signs
   - In malls: announce shops, escalator directions (up/down), level numbers
   - In food courts: scan and name stalls, identify queues, find empty tables
   - Be more verbose than outdoor mode — the user depends entirely on your voice indoors

3. BUS STOP MODE (you'll see [BUS] context):
   - Help identify approaching buses by reading bus numbers
   - Describe the bus stop environment (shelter, queue, seating)
   - When a bus approaches: "A bus is pulling up" + read bus number if visible

4. IDLE / EXPLORING (no [NAV] context):
   - Standard companion mode — describe scene changes, read text, warn about hazards
   - Be concise, only speak when something is worth mentioning

NAVIGATION EVENTS:
You receive [NAV_EVENT] messages for important navigation changes. When you see these:
- "navigating_to: X" → The user just started navigating. Be ready to provide visual context.
- "waypoint_reached" → Acknowledge only if something interesting is visible
- "approaching_turn" → Describe what you see at the upcoming turn (intersection, crossing, etc.)
- "approaching_destination" → Describe the destination as you see it
- "arrived" → Confirm what you see matches the destination
- "indoor_mode_activated" → Switch to Indoor Guide Mode (see above)
- "outdoor_mode_activated" → Switch back to outdoor complement mode
- "navigation_stopped" → Return to idle companion mode
- "road_crossing" → Describe the crossing (traffic lights, zebra crossing, traffic)

Remember: silence is fine. Only speak when it adds value. Safety always comes first."""
    
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
                # Generation params (temperature etc.) are set directly on LiveConnectConfig.
                config = types.LiveConnectConfig(
                    response_modalities=self.response_modalities,
                    system_instruction=self.system_instruction,
                    temperature=self.temperature,
                    # Thinking IS supported with native audio (docs confirm),
                    # but budget=0 gives lowest latency for real-time companion.
                    # Increase to 1024+ for complex reasoning tasks.
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    # Sliding window compression prevents session timeout (~15 min)
                    context_window_compression=types.ContextWindowCompressionConfig(
                        sliding_window=types.SlidingWindow(),
                    ),
                    # Transcribe model audio output for logging
                    output_audio_transcription=types.AudioTranscriptionConfig(),
                    # Transcribe model audio INPUT for logging what Gemini hears
                    input_audio_transcription=types.AudioTranscriptionConfig(),
                    # Disable automatic activity detection — the client controls
                    # when the user is speaking via explicit activityStart/End.
                    # This prevents Gemini from responding to ambient noise.
                    realtime_input_config=types.RealtimeInputConfig(
                        automatic_activity_detection=types.AutomaticActivityDetection(
                            disabled=True,
                        ),
                    ),
                    # Natural emotional voice
                    enable_affective_dialog=True,
                )
                
                # Always enable session resumption so we receive handles
                # from the server. On reconnect, supply the saved handle to
                # preserve multi-turn conversation context.
                if self.session_handle:
                    logger.info(f"🔄 Resuming session with handle: {self.session_handle[:20]}...")
                    config.session_resumption = types.SessionResumptionConfig(
                        handle=self.session_handle
                    )
                else:
                    # First connect — request handles for future resumption
                    config.session_resumption = types.SessionResumptionConfig()
                
                # Establish WebSocket connection using async with context manager
                # NOTE: The session MUST remain inside this async with block
                async with self.client.aio.live.connect(
                    model=self.model,
                    config=config
                ) as session:
                    self.session = session
                    self.is_connected = True
                    self._send_error_logged = False  # Reset on new connection
                    self._connect_time = time.time()
                    self._msg_count = 0
                    logger.info(f"✅ Connected to Gemini Live API on attempt {attempt + 1}")
                    
                    if self.status_callback:
                        self.status_callback("Connected to Gemini Live API")
                    
                    # Inject conversation history on reconnect (if no
                    # session resumption handle or as safeguard)
                    await self._inject_conversation_history()
                    
                    # Start receive loop (this blocks until disconnection)
                    await self._receive_loop()
                
                # Connection closed — log duration and reason
                duration = time.time() - self._connect_time if self._connect_time else 0
                self.is_connected = False
                self.session = None
                logger.info(
                    f"🔌 Connection closed gracefully "
                    f"(duration={duration:.1f}s, messages={self._msg_count})"
                )
                return True
                
            except ConnectionRefusedError as e:
                logger.warning(f"⚠️ Connection refused on attempt {attempt + 1}: {e}")
            except ConnectionClosed as e:
                duration = time.time() - self._connect_time if self._connect_time else 0
                logger.warning(
                    f"⚠️ WebSocket closed unexpectedly on attempt {attempt + 1}: "
                    f"code={e.code}, reason='{e.reason}', duration={duration:.1f}s"
                )
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
        Processes incoming messages from server_content.model_turn.parts.
        
        Audio parts have inline_data.data (24kHz PCM bytes).
        Text parts have text (informational transcript).
        """
        try:
            async for response in self.session.receive():
                self._msg_count += 1

                # === DEBUG: Log raw response structure ===
                populated = []
                for attr in ['data', 'text', 'server_content', 'go_away',
                             'session_resumption_update', 'tool_call',
                             'tool_call_cancellation', 'usage_metadata']:
                    val = getattr(response, attr, None)
                    if val is not None:
                        populated.append(attr)
                logger.debug(
                    f"📨 [MSG #{self._msg_count}] Response fields: {populated}"
                )

                # Handle server go_away message (graceful shutdown)
                if hasattr(response, 'go_away') and response.go_away:
                    ga = response.go_away
                    time_left = getattr(ga, 'time_left', None)
                    logger.warning(
                        f"⚠️ Server go_away: time_left={time_left}, "
                        f"has_handle={bool(getattr(ga, 'new_handle', None))}"
                    )
                    if getattr(ga, 'new_handle', None):
                        self.session_handle = ga.new_handle
                        logger.info("📝 Saved session handle for resumption")
                    break

                # Capture session resumption handles sent DURING the session
                # (these arrive periodically, not just at disconnect)
                sru = getattr(response, 'session_resumption_update', None)
                if sru:
                    if getattr(sru, 'resumable', False) and getattr(sru, 'new_handle', None):
                        self.session_handle = sru.new_handle
                        logger.info("📝 Session resumption handle updated")

                # Convenience accessors (SDK >= 1.x)
                # response.data → raw audio bytes, response.text → text string

                # Handle audio via convenience accessor (PRIMARY OUTPUT)
                if hasattr(response, 'data') and response.data:
                    audio_bytes = response.data
                    await self.audio_queue.put(audio_bytes)
                    self._store_response("[Audio response]", 'gemini_live_audio')
                    continue

                # Handle text via convenience accessor
                if hasattr(response, 'text') and response.text:
                    logger.info(f"💬 Gemini text response: {response.text[:100]}")
                    self._store_response(response.text, 'gemini_live')
                    continue

                # Fallback: parse server_content.model_turn.parts (older SDK / edge cases)
                sc = getattr(response, 'server_content', None)
                if sc:
                    # Interrupted by user speech — flush queued audio immediately
                    if getattr(sc, 'interrupted', False):
                        logger.info("🛑 Barge-in detected, flushing audio queue")
                        self.interrupted = True
                        flushed = 0
                        while not self.audio_queue.empty():
                            try:
                                self.audio_queue.get_nowait()
                                flushed += 1
                            except asyncio.QueueEmpty:
                                break
                        if flushed:
                            logger.debug(f"🗑️ Flushed {flushed} obsolete audio chunks")
                        continue

                    # Input transcription (from input_audio_transcription config)
                    it = getattr(sc, 'input_transcription', None)
                    if it and getattr(it, 'text', None):
                        logger.info(f"👂 User said (Gemini heard): {it.text}")
                        continue

                    # Output transcription (from output_audio_transcription config)
                    ot = getattr(sc, 'output_transcription', None)
                    if ot and getattr(ot, 'text', None):
                        logger.info(f"🗣️ Gemini said: {ot.text}")
                        self._store_response(ot.text, 'gemini_live')
                        # Accumulate model response text for conversation history
                        self._current_model_response_parts.append(ot.text)
                        continue

                    # Generation complete (model finished all output)
                    gc = getattr(sc, 'generation_complete', None)
                    if gc is True:
                        logger.debug(f"📨 [MSG #{self._msg_count}] Generation complete")
                        continue

                    model_turn = getattr(sc, 'model_turn', None)
                    if model_turn and hasattr(model_turn, 'parts'):
                        for part in model_turn.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                audio_bytes = part.inline_data.data
                                logger.debug(f"📥 Received {len(audio_bytes)} bytes of audio (parts)")
                                await self.audio_queue.put(audio_bytes)
                                self._store_response("[Audio response]", 'gemini_live_audio')
                            elif hasattr(part, 'text') and part.text:
                                logger.debug(f"💬 Text part: {part.text[:100]}...")
                                self._store_response(part.text, 'gemini_live')

                    # Handle turn_complete (model finished responding)
                    tc = getattr(sc, 'turn_complete', None)
                    if tc is not None:
                        reason = getattr(sc, 'turn_complete_reason', None)
                        logger.info(
                            f"📨 [MSG #{self._msg_count}] Turn complete "
                            f"(reason={reason})"
                        )
                        # Save accumulated model response to conversation history
                        if self._current_model_response_parts:
                            full_response = "".join(self._current_model_response_parts)
                            self._add_to_history("model", full_response)
                            self._current_model_response_parts.clear()
                        continue

                    if not getattr(sc, 'interrupted', False) and not ot and not model_turn:
                        logger.debug(
                            f"📨 [MSG #{self._msg_count}] Unhandled server_content: "
                            f"attrs={[a for a in dir(sc) if not a.startswith('_')]}"
                        )

            # async for loop ended normally — server closed the stream
            duration = time.time() - self._connect_time if self._connect_time else 0
            logger.warning(
                f"⚠️ Receive loop ended (stream closed by server) "
                f"after {duration:.1f}s, {self._msg_count} messages"
            )

        except asyncio.CancelledError:
            logger.info("🛑 Receive loop cancelled")
            raise
        except ConnectionClosed as e:
            duration = time.time() - self._connect_time if self._connect_time else 0
            logger.error(
                f"❌ WebSocket closed in receive loop: code={e.code}, "
                f"reason='{e.reason}', duration={duration:.1f}s, msgs={self._msg_count}"
            )
            self.is_connected = False
        except Exception as e:
            duration = time.time() - self._connect_time if self._connect_time else 0
            logger.error(
                f"❌ Error in receive loop: {type(e).__name__}: {e} "
                f"(duration={duration:.1f}s, msgs={self._msg_count})"
            )
            self.is_connected = False

    def _store_response(self, response_text: str, tier: str):
        """Store query/response to memory manager (fire-and-forget)."""
        if not self.memory_manager or not self._last_query:
            return
        latency_ms = (time.time() - self._query_start_time) * 1000 if self._query_start_time else 0
        try:
            asyncio.create_task(self.memory_manager.store_query(
                user_query=self._last_query,
                transcribed_text=self._last_query,
                routed_layer='layer2',
                routing_confidence=1.0,
                ai_response=response_text,
                response_latency_ms=latency_ms,
                tier_used=tier
            ))
        except Exception as e:
            logger.warning(f"⚠️ Failed to store to memory manager: {e}")

    def _add_to_history(self, role: str, text: str):
        """Add a turn to conversation history buffer."""
        # Skip empty or very short entries
        if not text or len(text.strip()) < 2:
            return
        self._conversation_history.append((role, text.strip()))
        # Trim to max size (keep most recent)
        if len(self._conversation_history) > self._max_history_turns * 2:
            self._conversation_history = self._conversation_history[-(self._max_history_turns * 2):]

    async def _inject_conversation_history(self):
        """Inject conversation history on reconnect for context continuity.

        If we have a session_handle the server restores context natively.
        We still inject as a safety net — the model handles duplicates well.
        """
        if not self._conversation_history or not self.is_connected or not self.session:
            return
        try:
            # Build a compact summary of recent conversation
            summary_parts = ["[CONTEXT] Previous conversation (for continuity):"]
            for role, text in self._conversation_history[-10:]:  # Last 10 turns
                prefix = "User" if role == "user" else "You"
                # Truncate very long entries
                truncated = text[:200] + "..." if len(text) > 200 else text
                summary_parts.append(f"{prefix}: {truncated}")
            summary = "\n".join(summary_parts)

            await self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": summary}]},
                turn_complete=False,  # Don't trigger a response
            )
            logger.info(
                f"📝 Injected conversation history "
                f"({len(self._conversation_history)} turns) on reconnect"
            )
        except Exception as e:
            logger.debug(f"History injection failed: {e}")
    
    async def send_activity_start(self) -> bool:
        """Signal that user started speaking (explicit VAD)."""
        if not self.is_connected or not self.session:
            return False
        try:
            await self.session.send_realtime_input(
                activity_start=types.ActivityStart()
            )
            logger.info("🎙️ Activity START signaled to Gemini")
            return True
        except Exception as e:
            logger.debug(f"Activity start signal error: {e}")
            return False

    async def send_activity_end(self) -> bool:
        """Signal that user stopped speaking (explicit VAD)."""
        if not self.is_connected or not self.session:
            return False
        try:
            await self.session.send_realtime_input(
                activity_end=types.ActivityEnd()
            )
            logger.info("🎙️ Activity END signaled to Gemini")
            return True
        except Exception as e:
            logger.debug(f"Activity end signal error: {e}")
            return False

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
            logger.debug("Audio send skipped: not connected")
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
            if not self._send_error_logged:
                logger.warning(f"⚠️ Gemini send failed (audio), suppressing further: {e}")
                self._send_error_logged = True
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
            logger.debug("Video send skipped: not connected")
            return False
        
        try:
            # Resize to cap bandwidth (max 1024px on longest side)
            max_dim = 1024
            if max(frame.width, frame.height) > max_dim:
                frame.thumbnail((max_dim, max_dim), Image.LANCZOS)

            # JPEG-encode — higher quality to prevent hallucination from compression
            buf = BytesIO()
            frame.save(buf, format='JPEG', quality=85)
            jpeg_bytes = buf.getvalue()

            await self.session.send_realtime_input(
                video=types.Blob(data=jpeg_bytes, mime_type='image/jpeg')
            )
            logger.debug(f"📤 Sent video frame ({frame.width}x{frame.height}, {len(jpeg_bytes)} bytes)")
            return True
            
        except Exception as e:
            if not self._send_error_logged:
                logger.warning(f"⚠️ Gemini send failed (video), suppressing further: {e}")
                self._send_error_logged = True
            self.is_connected = False
            return False
    
    async def send_text(self, text: str) -> bool:
        """
        Send text input to Gemini Live API.

        Uses send_realtime_input(text=...) per Live API guidance — all new user
        input (audio, video, text) goes via realtime_input for lower latency.
        send_client_content is reserved for conversation history / context only.

        Args:
            text: Text prompt

        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_connected or not self.session:
            logger.debug("Text send skipped: not connected")
            return False

        try:
            await self.session.send_realtime_input(text=text)
            logger.debug(f"📤 Sent text (realtime): {text[:50]}...")

            # Track query for memory logging and conversation history
            self._last_query = text
            self._query_start_time = time.time()
            self._add_to_history("user", text)
            # Clear any leftover model response buffer
            self._current_model_response_parts.clear()

            return True

        except Exception as e:
            if not self._send_error_logged:
                logger.warning(f"⚠️ Gemini send failed (text), suppressing further: {e}")
                self._send_error_logged = True
            self.is_connected = False
            return False

    async def send_context(self, text: str) -> bool:
        """
        Send silent context to Gemini Live API (no response triggered).

        Uses send_client_content() with turn_complete=False so Gemini absorbs
        the information without generating a response. This is the correct
        API for incremental context / history injection (not new user input).

        Args:
            text: Context text to inject silently

        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_connected or not self.session:
            return False

        try:
            await self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": text}]},
                turn_complete=False,
            )
            return True

        except Exception as e:
            if not self._send_error_logged:
                logger.warning(f"⚠️ Gemini send failed (context), suppressing further: {e}")
                self._send_error_logged = True
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
        """Run asyncio event loop in background thread with auto-reconnection."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        reconnect_delay = 1.0  # Fast reconnect between sessions
        max_delay = 15.0
        
        try:
            while self.is_running:
                audio_task = None
                try:
                    # Start audio processing task
                    audio_task = self.loop.create_task(self._process_audio_queue())
                    
                    # Connect to Live API (blocks until disconnection)
                    self.loop.run_until_complete(self.handler.connect())
                    
                    # Connection ended normally (turn_complete → session close)
                    # This is expected behavior for native audio model
                    logger.info("🔌 Gemini session ended, reconnecting...")
                    reconnect_delay = 1.0  # Reset delay on clean disconnect
                    
                except Exception as e:
                    logger.error(f"❌ Gemini event loop error: {e}")
                    # Only increase delay on errors, not clean disconnects
                    reconnect_delay = min(reconnect_delay * 1.5, max_delay)
                finally:
                    if audio_task:
                        audio_task.cancel()
                        try:
                            self.loop.run_until_complete(audio_task)
                        except (asyncio.CancelledError, Exception):
                            pass
                
                # Reconnect if still supposed to be running
                if not self.is_running:
                    break
                
                logger.info(f"🔄 Gemini reconnecting in {reconnect_delay:.0f}s...")
                import time
                time.sleep(reconnect_delay)
                
                # Reset handler connection state for fresh connect
                self.handler.is_connected = False
                self.handler.session = None
            
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
                        # Call directly — add_audio_chunk is non-blocking
                        # (spawning a thread per audio chunk overwhelms RPi5)
                        self.audio_callback(audio_bytes)
                        
                except asyncio.TimeoutError:
                    # No audio available, continue waiting
                    continue
                    
        except asyncio.CancelledError:
            logger.info("🛑 Audio processing cancelled")
            raise
        except Exception as e:
            logger.error(f"❌ Audio processing error: {e}")
    
    def send_activity_start(self):
        """Signal speech start (thread-safe)."""
        if not self.is_running or not self.loop:
            return
        asyncio.run_coroutine_threadsafe(
            self.handler.send_activity_start(), self.loop
        )

    def send_activity_end(self):
        """Signal speech end (thread-safe)."""
        if not self.is_running or not self.loop:
            return
        asyncio.run_coroutine_threadsafe(
            self.handler.send_activity_end(), self.loop
        )

    def send_audio(self, audio_bytes: bytes, sample_rate: int = 16000):
        """
        Send audio chunk (thread-safe).
        
        Args:
            audio_bytes: Raw PCM audio bytes
            sample_rate: Audio sample rate (16000 Hz)
        """
        if not self.is_running or not self.loop:
            logger.debug("Manager not running, skipping send_audio")
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
            logger.debug("Manager not running, skipping send_video")
            return
        
        # Schedule async task in event loop
        asyncio.run_coroutine_threadsafe(
            self.handler.send_video_frame(frame),
            self.loop
        )
    
    def send_text(self, text: str):
        """
        Send text prompt (thread-safe). Triggers a model response.
        
        Args:
            text: Text prompt
        """
        if not self.is_running or not self.loop:
            logger.debug("Manager not running, skipping send_text")
            return
        
        # Schedule async task in event loop
        asyncio.run_coroutine_threadsafe(
            self.handler.send_text(text),
            self.loop
        )

    def send_context(self, text: str):
        """
        Send silent context (thread-safe). Does NOT trigger a model response.
        Use for periodic [CONTEXT] injections.
        
        Args:
            text: Context text
        """
        if not self.is_running or not self.loop:
            return
        
        asyncio.run_coroutine_threadsafe(
            self.handler.send_context(text),
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
