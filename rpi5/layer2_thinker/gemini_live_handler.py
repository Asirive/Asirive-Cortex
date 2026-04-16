"""
Gemini 3.1 Flash Live API Handler - Real-Time Audio-to-Audio WebSocket
Project-Cortex v2.0 - Layer 2 (Thinker)

Revolutionary Feature: Native audio-to-audio streaming with video context.
- Latency: <500ms (vs 2-3s HTTP API) = 83% improvement
- Pipeline: Audio+Video→Audio (1-step, not 3-step)
- Conversation: Stateful session (context retention)
- Cost: $0.005/min (50% cheaper than HTTP API)

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: December 23, 2025
Status: EXPERIMENTAL
"""

import asyncio
import logging
import time
from typing import Optional, Callable, AsyncGenerator
from typing import TYPE_CHECKING
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

if TYPE_CHECKING:
    from rpi5.layer4_memory.hybrid_memory_manager import HybridMemoryManager


class GeminiLiveHandler:
    """
    WebSocket-based handler for Gemini 3.1 Flash Live API.
    
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
        model: str = "gemini-3.1-flash-live-preview",
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
            model: Live API model name (gemini-3.1-flash-live-preview)
            system_instruction: System prompt for AI behavior
            response_modalities: ['AUDIO'] for native audio model
            temperature: AI creativity (0.0-1.0)
            max_retries: Max reconnection attempts (5)
            initial_delay: Initial retry delay seconds (1.0)
            max_delay: Max retry delay seconds (60.0)
            memory_manager: HybridMemoryManager for cloud storage (optional)
        """
        # v1beta required for gemini-3.1-flash-live-preview
        self.client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1beta"},
        )
        self.model = model
        self.system_instruction = system_instruction or self._default_system_instruction()
        self.response_modalities = response_modalities or ['AUDIO']
        self.temperature = temperature
        response_modality_values = {
            str(getattr(modality, 'value', modality)).upper()
            for modality in self.response_modalities
        }
        self._audio_only_response = (
            'AUDIO' in response_modality_values and 'TEXT' not in response_modality_values
        )

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
        self._on_barge_in_callback: Optional[Callable] = None  # Called on barge-in to flush audio player
        self._on_connected_callback: Optional[Callable] = None  # Called after each successful (re)connection
        self._connect_time: Optional[float] = None  # Track connection duration
        self._msg_count = 0  # Count messages per session
        self._barge_in_cooldown_until: float = 0.0  # Suppress false barge-in after text/tool sends

        # Audio output queue (thread-safe, bounded to prevent memory leak)
        # 500 chunks ≈ 20s buffer at 40ms/chunk — prevents drops during burst responses
        self.audio_queue = asyncio.Queue(maxsize=500)

        # Per-session write lock to prevent interleaved WebSocket frames
        self._send_lock: Optional[asyncio.Lock] = None
        self._is_gemini_live_31 = model.startswith("gemini-3.1-flash-live-preview")
        self._context_disabled_logged = False

        # Debug counters for diagnosing 1007
        self._audio_chunks_sent = 0
        self._video_frames_sent = 0
        self._audio_bytes_total = 0

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

        # Echo detection: recent Gemini output transcriptions (for filtering
        # mic echo when STT picks up speaker output)
        self._recent_gemini_outputs: list = []  # [(timestamp, text), ...]
        self._echo_buffer_seconds = 15.0  # Keep outputs for 15s

        # Tool callback for function calling (set by main.py)
        self._tool_callback: Optional[Callable] = None

        logger.info(f"✅ GeminiLiveHandler initialized (model={model})")
    
    @staticmethod
    def _default_system_instruction() -> str:
        """Default system instruction for autonomous AI companion."""
        return """You are the eyes of a visually impaired person wearing you as smart glasses.
You see through their camera. You hear through their microphone.
You are their trusted companion — not a chatbot waiting for questions.

CRITICAL CONTEXT — WHAT THE WHITE CANE ALREADY HANDLES:
The user carries a white cane that detects ground-level obstacles (kerbs, steps,
bollards, uneven ground, puddles). Do NOT warn about things the cane handles.
Focus on what the cane CANNOT detect:
- OVERHEAD obstacles: signboards, low branches, awnings, open cabinet doors, scaffolding
- APPROACHING objects: vehicles, cyclists, e-scooters, other pedestrians on collision course
- SIDE obstacles at torso/head height that the cane sweeps under
- Visual information: text, signs, bus numbers, shop names, people's faces

=== MODE-DRIVEN BEHAVIOR ===
You receive a [MODE] tag in every context update. Your proactivity level depends on it:

[MODE] IDLE — DEFAULT, QUIET MODE
  - Do NOT speak unless spoken to, EXCEPT for overhead/approaching hazards
  - Only speak proactively for: overhead obstacles, approaching vehicles/cyclists,
    or if the user seems lost/distressed
  - Answer questions fully when asked
  - Do NOT describe the scene, read signs, or narrate what you see
  - Do NOT talk about GPS status, navigation, or the environment
  - Silence is correct behavior in IDLE mode

[MODE] OUTDOOR_NAV — GPS NAVIGATION ACTIVE
  - You are the voice companion for turn-by-turn navigation
  - Give directions: "Turn left ahead", "Continue straight for 50 meters"
  - Announce landmarks you see: "MRT station on your right"
  - Read street signs, building names, and shop names at turns
  - Describe intersections and road crossings in detail
  - On long straight stretches, reassure briefly ("Still on Tampines Ave, 200m left")
  - When approaching destination: describe what you see
  - OVERHEAD HAZARDS remain your top priority
  - Maximum 2 sentences when speaking unprompted

[MODE] INDOOR_NAV — YOU ARE THE PRIMARY NAVIGATOR
  - GPS is unavailable. YOU guide the user using the camera feed.
  - Give short voice commands: "Turn left", "Go straight", "Door on your right"
  - Read signs, exit markers, gate numbers, room labels from camera
  - Be proactive — the user depends entirely on you for voice guidance
  - If you cannot see the destination or surroundings clearly (dark, blurry,
    camera pointing at floor/ceiling/wall), ask the user to slowly look around
    so you can orient yourself: "Could you slowly look around so I can see
    where we are?" or "I can't see much, try turning your head slowly."
  - If the user asks to go to a room you can't see yet, guide them step by
    step using what IS visible (corridors, doors, furniture, light sources)

[MODE] BUS_WATCH — WAITING AT BUS STOP
  - The user's #1 question: "Which bus is coming?"
  - Read bus numbers from approaching buses
  - Call get_bus_arrival(bus_stop_code) for real-time ETAs
  - Describe the bus stop (shelter, queue, seating, bay)
  - When a bus arrives: "Bus 21 is pulling up now"
  - Help find the correct door / boarding point

[MODE] TRANSIT — ON BUS OR MRT
  - Mostly quiet — announce stops if visible through windows
  - Read overhead signs for station names
  - Alert when approaching the user's destination stop (if navigating)

[MODE] EXPLORE — USER REQUESTED SCENE DESCRIPTION
  - Be highly proactive — describe everything around the user
  - Read all visible text, signs, menus, screens
  - Describe people, objects, layout, distances
  - Continue until the user says "stop" or "thanks"

SPEAKING RULES (all modes):
- Maximum 2 sentences when speaking unprompted
- When answering a question, be thorough but concise
- Use clock directions or simple spatial terms: "on your left", "ahead", "to your right"
- Include distance when relevant: "Wall, about 3 meters ahead"
- Never say "I can see" — just describe directly: "Person approaching on your left"
- Speak naturally like a trusted friend walking beside them
- NEVER use colour as the only identifier — some users have no colour concept
  Bad: "the red sign". Good: "the rectangular sign on the pole to your left"
- Describe objects by shape, texture, position, and size instead of colour alone
- Prioritize: safety > navigation > useful info
- Do NOT spam — the user needs to concentrate

SENSOR CONTEXT:
You receive periodic [CONTEXT] messages with sensor data. These are background updates —
do NOT respond to them. Silently absorb the information and use it when you speak next.
NEVER announce, acknowledge, or comment on mode changes or session state updates.
Do NOT say things like "I'm now in idle mode" or "Switching to navigation mode" or
"Session resumed". Mode changes are internal system events — the user does not need to
hear about them. Just silently adjust your behavior to match the new mode.

SCENE CHANGE NOTIFICATIONS:
You receive [SCENE_CHANGE] messages when the environment changes meaningfully.
In OUTDOOR_NAV or INDOOR_NAV: respond briefly if navigation-relevant.
In IDLE: only respond if there's a safety hazard.
In EXPLORE: always respond with a description.

NAVIGATION EVENTS:
You receive [NAV_EVENT] messages for important navigation changes:
- "navigating_to: X" → Navigation started. Be ready to guide.
- "waypoint_reached" → Acknowledge only if something interesting is visible
- "approaching_turn" → Describe what you see at the upcoming turn
- "approaching_destination" → Describe the destination as you see it
- "arrived" → Confirm what you see matches the destination
- "indoor_mode_activated" → Switch to Indoor Guide Mode (give voice directions)
- "outdoor_mode_activated" → Switch back to outdoor GPS guidance
- "navigation_stopped" → Return to IDLE (go quiet)
- "road_crossing" → Describe the crossing (traffic lights, zebra crossing, traffic)

Remember: in IDLE mode, silence is correct. Only speak when it genuinely helps.
Safety always comes first. Overhead hazards are your highest priority."""
    
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
                    # Disable thinking for faster responses — thinking adds
                    # multi-second delays and creates long silent gaps that are
                    # hostile to explicit turn control.
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    # Voice configuration — Zephyr voice
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Zephyr")
                        )
                    ),
                    # Medium resolution for video frames (258 tokens/image)
                    media_resolution="MEDIA_RESOLUTION_MEDIUM",
                    # Sliding window compression prevents session timeout (~15 min)
                    context_window_compression=types.ContextWindowCompressionConfig(
                        trigger_tokens=104857,
                        sliding_window=types.SlidingWindow(target_tokens=52428),
                    ),
                    # Transcribe model audio output for logging
                    output_audio_transcription=types.AudioTranscriptionConfig(),
                    # Transcribe model audio INPUT for logging what Gemini hears
                    input_audio_transcription=types.AudioTranscriptionConfig(),
                    # Gemini 3.1 runs with client-side turn control from the
                    # local VoiceCoordinator. Official Live API docs disable
                    # automatic activity detection in realtime_input_config,
                    # then send activity_start / activity_end on the stream.
                    realtime_input_config=types.RealtimeInputConfig(
                        automatic_activity_detection=types.AutomaticActivityDetection(
                            disabled=True,
                        ),
                        activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                    ),
                    # Function calling: let Gemini query nav state & report obstacles
                    tools=[
                        # Google Search grounding — real-time info (bus routes, places, etc.)
                        types.Tool(google_search=types.GoogleSearch()),
                        # Custom function declarations
                        types.Tool(function_declarations=[
                        {
                            "name": "get_navigation_state",
                            "description": (
                                "Get current navigation state including waypoint index, "
                                "distance to waypoint, bearing, distance to destination, "
                                "and next instruction. Call this when the user asks about "
                                "navigation progress or when you need route context."
                            ),
                        },
                        {
                            "name": "report_obstacle",
                            "description": (
                                "Report an obstacle you see in the camera feed that could "
                                "block the user's path. The navigation system will note it."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "direction": {
                                        "type": "string",
                                        "enum": ["left", "center", "right", "ahead"],
                                        "description": "Where the obstacle is relative to the user",
                                    },
                                    "distance_m": {
                                        "type": "number",
                                        "description": "Estimated distance in meters",
                                    },
                                    "object_type": {
                                        "type": "string",
                                        "description": "What the obstacle is (e.g. bollard, construction, pothole)",
                                    },
                                },
                                "required": ["direction"],
                            },
                        },
                        {
                            "name": "get_gps_accuracy",
                            "description": (
                                "Get current GPS fix quality and accuracy in meters. "
                                "Useful for understanding position reliability."
                            ),
                        },
                        # set_beam_direction SCRAPPED — spatial audio removed
                        # Legacy code in rpi5/layer3_guide/spatial_audio/
                        {
                            "name": "get_bus_arrival",
                            "description": (
                                "Get real-time bus arrival times for a Singapore bus stop. "
                                "Returns service numbers, next bus ETA in minutes, and load. "
                                "Call this when the user is at a bus stop or asks about buses. "
                                "Use Google Search or GPS context to determine the bus stop code."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "bus_stop_code": {
                                        "type": "string",
                                        "description": "5-digit bus stop code (e.g. '75009')",
                                    },
                                },
                                "required": ["bus_stop_code"],
                            },
                        },
                        # ── Routing functions ── Gemini decides actions instead of keyword matching
                        {
                            "name": "start_outdoor_navigation",
                            "description": (
                                "Start GPS turn-by-turn navigation to an OUTDOOR destination "
                                "(street address, MRT station, bus stop, shop, building). "
                                "Only call this for real outdoor places reachable by walking/transit. "
                                "Do NOT call this for rooms inside the user's home or indoor locations."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "destination": {
                                        "type": "string",
                                        "description": "The place to navigate to (e.g. 'Tampines MRT', 'Block 123 Tampines St 11')",
                                    },
                                },
                                "required": ["destination"],
                            },
                        },
                        {
                            "name": "guide_indoor",
                            "description": (
                                "Activate indoor camera-guidance mode to help the user reach "
                                "a room or area INSIDE a building (e.g. living room, kitchen, "
                                "bathroom, gate, office). When called, the system switches to "
                                "indoor navigation mode and you become the primary guide using "
                                "the camera feed. Use this instead of start_outdoor_navigation "
                                "when the destination is a room or area inside the current building."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "destination": {
                                        "type": "string",
                                        "description": "The indoor location (e.g. 'living room', 'kitchen', 'exit')",
                                    },
                                },
                                "required": ["destination"],
                            },
                        },
                        {
                            "name": "stop_navigation",
                            "description": (
                                "Stop any active navigation (outdoor GPS or indoor guidance). "
                                "Call when the user says stop, cancel, or has arrived."
                            ),
                        },
                        {
                            "name": "search_memory",
                            "description": (
                                "Search the user's saved items and locations memory. "
                                "Call when the user asks 'where is my X', 'find my X', "
                                "'where did I put my X'. Returns stored location/description."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "item_name": {
                                        "type": "string",
                                        "description": "The item to search for (e.g. 'keys', 'wallet', 'phone', 'glasses')",
                                    },
                                },
                                "required": ["item_name"],
                            },
                        },
                        {
                            "name": "set_system_mode",
                            "description": (
                                "Switch the system operating mode. "
                                "'PRODUCTION' enables Bluetooth audio, always-on VAD, and stricter detection. "
                                "'DEV' disables VAD monitoring and uses relaxed thresholds. "
                                "Only call when the user explicitly asks to change mode."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "mode": {
                                        "type": "string",
                                        "enum": ["PRODUCTION", "DEV"],
                                        "description": "The mode to switch to",
                                    },
                                },
                                "required": ["mode"],
                            },
                        },
                    ])],
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
                
                # --- DEBUG: Log config summary before connecting ---
                _tools_summary = []
                for t in (config.tools or []):
                    if getattr(t, 'google_search', None):
                        _tools_summary.append('google_search')
                    if getattr(t, 'function_declarations', None):
                        _tools_summary.append(f'functions({len(t.function_declarations)})')
                _thinking_budget = getattr(getattr(config, 'thinking_config', None), 'thinking_budget', 'N/A')
                logger.info(
                    f"📋 Config: model={self.model}, "
                    f"modalities={config.response_modalities}, "
                    f"temp={config.temperature}, "
                    f"thinking_budget={_thinking_budget}, "
                    f"voice={'Zephyr'}, "
                    f"media_res={config.media_resolution}, "
                    f"tools={_tools_summary}, "
                    f"sys_instruction_len={len(self.system_instruction)}, "
                    f"session_handle={'yes' if self.session_handle else 'no'}, "
                    f"compression=trigger:{getattr(getattr(config, 'context_window_compression', None), 'trigger_tokens', 'N/A')}, "
                    f"vad=manual-client-signals, "
                    f"input_transcription={config.input_audio_transcription is not None}, "
                    f"output_transcription={config.output_audio_transcription is not None}"
                )

                # Establish WebSocket connection using async with context manager
                # NOTE: The session MUST remain inside this async with block
                async with self.client.aio.live.connect(
                    model=self.model,
                    config=config
                ) as session:
                    self.session = session
                    self._send_error_logged = False  # Reset on new connection
                    self.interrupted = False  # Reset barge-in flag on reconnect
                    self._connect_time = time.time()
                    self._msg_count = 0
                    self._audio_chunks_sent = 0
                    self._video_frames_sent = 0
                    self._audio_bytes_total = 0
                    self._send_lock = asyncio.Lock()  # Fresh lock per session
                    self._clear_audio_queue()

                    # Seed history only during setup before realtime traffic starts.
                    await self._inject_conversation_history()

                    self.is_connected = True
                    logger.info(f"✅ Connected to Gemini Live API on attempt {attempt + 1}")
                    
                    if self.status_callback:
                        self.status_callback("Connected to Gemini Live API")
                    
                    # Fire connected callback so orchestrator can resend
                    # state (mode, nav context) immediately after reconnect
                    if self._on_connected_callback:
                        try:
                            self._on_connected_callback()
                        except Exception as cb_err:
                            logger.debug(f"Connected callback error: {cb_err}")
                    
                    # Start receive loop (this blocks until disconnection)
                    await self._receive_loop()
                
                # Connection closed — log duration and reason
                duration = time.time() - self._connect_time if self._connect_time else 0
                self.is_connected = False
                self.session = None
                # Clear stale model response buffer from dead session
                self._current_model_response_parts.clear()
                self._clear_audio_queue()
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
                duration = time.time() - self._connect_time if self._connect_time else 0
                logger.error(
                    f"❌ API Error on attempt {attempt + 1}: code={e.code}, "
                    f"message='{e.message}', duration={duration:.1f}s, "
                    f"msgs_received={self._msg_count}, "
                    f"audio_chunks_sent={self._audio_chunks_sent}, "
                    f"video_frames_sent={self._video_frames_sent}, "
                    f"audio_bytes_total={self._audio_bytes_total}"
                )
                if e.code == 404:
                    logger.error("❌ Model not found - check model name")
                    return False  # Don't retry if model doesn't exist
                elif e.code == 401:
                    logger.error("❌ Invalid API key - check GEMINI_API_KEY")
                    return False  # Don't retry if auth fails
                elif e.code in (400, 410, 1007):
                    # Bad, expired, or invalid-argument session handle — clear it
                    # so next attempt starts fresh. 1007 = "invalid argument",
                    # commonly caused by stale/corrupt session handles.
                    if self.session_handle:
                        logger.warning(f"⚠️ Clearing expired/invalid session handle (code={e.code})")
                        self.session_handle = None
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

        The python-genai Live SDK exposes session.receive() as a turn-scoped
        async iterator in practice, so re-enter it until the websocket itself
        closes or the server explicitly sends go_away.
        
        Audio parts have inline_data.data (24kHz PCM bytes).
        Text parts have text (informational transcript).
        """
        try:
            server_requested_close = False
            while self.is_connected and self.session:
                turn_message_count = 0
                turn_completed = False

                async for response in self.session.receive():
                    turn_message_count += 1
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
                        server_requested_close = True
                        break

                    # Capture session resumption handles sent DURING the session
                    # (these arrive periodically, not just at disconnect)
                    sru = getattr(response, 'session_resumption_update', None)
                    if sru:
                        if getattr(sru, 'resumable', False) and getattr(sru, 'new_handle', None):
                            self.session_handle = sru.new_handle
                            logger.info("📝 Session resumption handle updated")

                    # Handle function calls from Gemini
                    tc = getattr(response, 'tool_call', None)
                    if tc:
                        function_calls = getattr(tc, 'function_calls', []) or []
                        logger.info(
                            f"🔧 Gemini tool_call: {[fc.name for fc in function_calls]}"
                        )
                        function_responses = []
                        for fc in function_calls:
                            result = {"error": "No tool callback registered"}
                            if self._tool_callback:
                                try:
                                    if asyncio.iscoroutinefunction(self._tool_callback):
                                        result = await self._tool_callback(
                                            fc.name, getattr(fc, 'args', {}) or {}
                                        )
                                    else:
                                        result = await asyncio.to_thread(
                                            self._tool_callback,
                                            fc.name,
                                            getattr(fc, 'args', {}) or {},
                                        )
                                except Exception as e:
                                    logger.error(f"Tool callback error for {fc.name}: {e}")
                                    result = {"error": str(e)}
                            function_responses.append(
                                types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"result": result},
                                )
                            )
                        if function_responses and self.session:
                            if self._send_lock:
                                async with self._send_lock:
                                    await self.session.send_tool_response(
                                        function_responses=function_responses
                                    )
                            else:
                                await self.session.send_tool_response(
                                    function_responses=function_responses
                                )
                            logger.info(f"🔧 Sent {len(function_responses)} tool response(s)")
                            # Suppress false barge-in for 3s after tool response.
                            self._barge_in_cooldown_until = time.time() + 3.0
                        continue

                    # Handle tool call cancellation
                    tcc = getattr(response, 'tool_call_cancellation', None)
                    if tcc:
                        logger.info(f"🔧 Tool call cancelled: {tcc}")
                        continue

                    # Gemini 3.1 can return payload + metadata in the SAME event.
                    # Process convenience payloads additively, then always inspect
                    # server_content for turn state, interruptions, and transcripts.
                    top_level_audio = getattr(response, 'data', None)
                    if top_level_audio:
                        try:
                            self.audio_queue.put_nowait(top_level_audio)
                        except asyncio.QueueFull:
                            logger.debug("🗑️ Audio queue full — dropping chunk to keep receive loop alive")
                        self._store_response("[Audio response]", 'gemini_live_audio')

                    top_level_text = None
                    if not self._audio_only_response:
                        top_level_text = getattr(response, 'text', None)
                        if top_level_text:
                            logger.info(f"💬 Gemini text response: {top_level_text[:100]}")
                            self._store_response(top_level_text, 'gemini_live')

                    # Parse server_content on every event to avoid missing
                    # turn_complete / interrupted / transcription metadata.
                    sc = getattr(response, 'server_content', None)
                    if sc:
                        # Interrupted by user speech — flush queued audio immediately
                        if getattr(sc, 'interrupted', False):
                            if time.time() < self._barge_in_cooldown_until:
                                logger.info("🛡️ Barge-in SUPPRESSED (cooldown active — likely false positive from trailing audio)")
                                continue
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
                            if self._on_barge_in_callback:
                                try:
                                    self._on_barge_in_callback()
                                except Exception as cb_err:
                                    logger.debug(f"Barge-in callback error: {cb_err}")

                        it = getattr(sc, 'input_transcription', None)
                        if it and getattr(it, 'text', None):
                            logger.info(f"👂 User said (Gemini heard): {it.text}")

                        ot = getattr(sc, 'output_transcription', None)
                        if ot and getattr(ot, 'text', None):
                            logger.info(f"🗣️ Gemini said: {ot.text}")
                            self._store_response(ot.text, 'gemini_live')
                            self._current_model_response_parts.append(ot.text)
                            self._recent_gemini_outputs.append((time.time(), ot.text))
                            cutoff = time.time() - self._echo_buffer_seconds
                            self._recent_gemini_outputs = [
                                (t, txt) for t, txt in self._recent_gemini_outputs if t > cutoff
                            ]

                        gc = getattr(sc, 'generation_complete', None)
                        if gc is True:
                            logger.debug(f"📨 [MSG #{self._msg_count}] Generation complete")

                        model_turn = getattr(sc, 'model_turn', None)
                        if model_turn and hasattr(model_turn, 'parts'):
                            for part in model_turn.parts:
                                if hasattr(part, 'inline_data') and part.inline_data and not top_level_audio:
                                    audio_bytes = part.inline_data.data
                                    logger.debug(f"📥 Received {len(audio_bytes)} bytes of audio (parts)")
                                    try:
                                        self.audio_queue.put_nowait(audio_bytes)
                                    except asyncio.QueueFull:
                                        logger.debug("🗑️ Audio queue full (parts path) — dropping chunk")
                                    self._store_response("[Audio response]", 'gemini_live_audio')
                                elif hasattr(part, 'text') and part.text and not top_level_text:
                                    logger.debug(f"💬 Text part: {part.text[:100]}...")
                                    self._store_response(part.text, 'gemini_live')

                        tc = getattr(sc, 'turn_complete', None)
                        if tc is not None:
                            turn_completed = True
                            reason = getattr(sc, 'turn_complete_reason', None)
                            self.interrupted = False
                            logger.info(
                                f"📨 [MSG #{self._msg_count}] Turn complete "
                                f"(reason={reason})"
                            )
                            if self._current_model_response_parts:
                                full_response = "".join(self._current_model_response_parts)
                                self._add_to_history("model", full_response)
                                self._current_model_response_parts.clear()

                        if not getattr(sc, 'interrupted', False) and not ot and not model_turn:
                            logger.debug(
                                f"📨 [MSG #{self._msg_count}] Unhandled server_content: "
                                f"attrs={[a for a in dir(sc) if not a.startswith('_')]}"
                            )

                if server_requested_close or not self.is_connected or not self.session:
                    break

                if turn_message_count == 0:
                    logger.warning("⚠️ Receive iterator ended with no messages — treating session as closed")
                    break

                if turn_completed:
                    logger.debug("🔁 Turn iterator ended after turn_complete — keeping session open")
                else:
                    logger.debug("🔁 Receive iterator ended mid-session — re-entering receive stream")
                await asyncio.sleep(0)

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
                f"reason='{e.reason}', duration={duration:.1f}s, msgs={self._msg_count}, "
                f"audio_sent={self._audio_chunks_sent}, video_sent={self._video_frames_sent}"
            )
            self.is_connected = False
        except Exception as e:
            duration = time.time() - self._connect_time if self._connect_time else 0
            logger.error(
                f"❌ Error in receive loop: {type(e).__name__}: {e} "
                f"(duration={duration:.1f}s, msgs={self._msg_count}, "
                f"audio_sent={self._audio_chunks_sent}, video_sent={self._video_frames_sent})"
            )
            # Clear stale session handle on 1007 ("invalid argument")
            # so the next connection starts fresh instead of retrying
            # the same broken handle in a loop.
            if hasattr(e, 'code') and e.code in (400, 410, 1007):
                if self.session_handle:
                    logger.warning(f"⚠️ Clearing session handle after {e.code} in receive loop")
                    self.session_handle = None
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

    def is_echo(self, text: str, threshold: float = 0.5) -> bool:
        """Check if text is likely echo of recent Gemini audio output.

        Compares word overlap between *text* (from STT) and recent Gemini
        output transcriptions.  If >= *threshold* fraction of the STT words
        appear in any recent Gemini output, it's considered echo.

        Args:
            text: STT transcription to check
            threshold: minimum word-overlap ratio (0-1) to classify as echo

        Returns:
            True if the text is likely echo of Gemini's own speech
        """
        if not text or not self._recent_gemini_outputs:
            return False

        # Prune stale entries
        cutoff = time.time() - self._echo_buffer_seconds
        self._recent_gemini_outputs = [
            (t, txt) for t, txt in self._recent_gemini_outputs if t > cutoff
        ]
        if not self._recent_gemini_outputs:
            return False

        # Build set of words from all recent Gemini output
        gemini_words = set()
        for _, gtxt in self._recent_gemini_outputs:
            gemini_words.update(gtxt.lower().split())

        stt_words = text.lower().split()
        if not stt_words:
            return False

        overlap = sum(1 for w in stt_words if w in gemini_words)
        ratio = overlap / len(stt_words)
        if ratio >= threshold:
            logger.info(
                f"🔇 Echo detected ({ratio:.0%} overlap): '{text[:60]}...'"
            )
            return True
        return False

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
        """Seed initial history during session setup when starting fresh.

        Gemini 3.1 only supports send_client_content for initial history
        seeding during setup. Mid-session mutations are unsupported.
        Session resumption handles continuity for resumed sessions.
        """
        if not self._conversation_history or not self.session:
            return
        if self.session_handle:
            logger.debug(
                "📝 Skipping history seeding (session resumption handle active)"
            )
            return
        if self._is_gemini_live_31:
            logger.debug(
                "📝 Skipping initial history seeding for Gemini 3.1 Live "
                "(installed SDK lacks HistoryConfig support)"
            )
            return
        try:
            turns = []
            for role, text in self._conversation_history[-10:]:  # Last 10 turns
                truncated = text[:200] + "..." if len(text) > 200 else text
                turns.append(
                    types.Content(
                        role=role,
                        parts=[types.Part(text=truncated)]
                    )
                )

            await self.session.send_client_content(
                turns=turns,
                turn_complete=True,
            )
            logger.info(
                f"📝 Seeded initial conversation history "
                f"({len(self._conversation_history)} turns)"
            )
        except Exception as e:
            logger.debug(f"Initial history seeding failed: {e}")
    
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
            if self._send_lock:
                async with self._send_lock:
                    await self.session.send_realtime_input(
                        audio=types.Blob(
                            data=audio_bytes,
                            mime_type=f'audio/pcm;rate={sample_rate}'
                        )
                    )
            else:
                await self.session.send_realtime_input(
                    audio=types.Blob(
                        data=audio_bytes,
                        mime_type=f'audio/pcm;rate={sample_rate}'
                    )
                )
            self._audio_chunks_sent += 1
            self._audio_bytes_total += len(audio_bytes)
            # Log first 5 chunks, then every 100th
            if self._audio_chunks_sent <= 5 or self._audio_chunks_sent % 100 == 0:
                elapsed = time.time() - self._connect_time if self._connect_time else 0
                logger.info(
                    f"📤 Audio chunk #{self._audio_chunks_sent}: "
                    f"{len(audio_bytes)}B, rate={sample_rate}, "
                    f"total={self._audio_bytes_total}B, "
                    f"elapsed={elapsed:.1f}s"
                )
            else:
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
            # Offload CPU-heavy JPEG encoding to thread pool executor
            # so the Gemini event loop stays free for audio sends.
            max_dim = 1024
            loop = asyncio.get_event_loop()
            jpeg_bytes = await loop.run_in_executor(
                None, self._encode_frame_jpeg, frame, max_dim
            )

            if self._send_lock:
                async with self._send_lock:
                    await self.session.send_realtime_input(
                        video=types.Blob(data=jpeg_bytes, mime_type='image/jpeg')
                    )
            else:
                await self.session.send_realtime_input(
                    video=types.Blob(data=jpeg_bytes, mime_type='image/jpeg')
                )
            self._video_frames_sent += 1
            elapsed = time.time() - self._connect_time if self._connect_time else 0
            logger.info(
                f"📤 Video frame #{self._video_frames_sent}: "
                f"{frame.width}x{frame.height}, {len(jpeg_bytes)}B JPEG, "
                f"elapsed={elapsed:.1f}s"
            )
            return True
            
        except Exception as e:
            if not self._send_error_logged:
                logger.warning(f"⚠️ Gemini send failed (video), suppressing further: {e}")
                self._send_error_logged = True
            self.is_connected = False
            return False
    
    def _encode_frame_jpeg(self, frame: Image.Image, max_dim: int = 1024) -> bytes:
        """Synchronous JPEG encoder — runs in thread pool, not event loop."""
        if max(frame.width, frame.height) > max_dim:
            frame = frame.copy()
            frame.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = BytesIO()
        frame.save(buf, format='JPEG', quality=85)
        return buf.getvalue()

    async def send_text(self, text: str) -> bool:
        """
        Send text input to Gemini Live API.

        Uses send_realtime_input(text=...) to deliver text alongside the
        active audio/video stream.  The server's automatic VAD treats this
        as part of the real-time input and will generate a response.

        NOTE: send_client_content MUST NOT be called while
        send_realtime_input audio is streaming — mixing the two causes
        error 1007 ("Request contains an invalid argument").

        Args:
            text: Text prompt

        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_connected or not self.session:
            logger.debug("Text send skipped: not connected")
            return False

        try:
            if self._send_lock:
                async with self._send_lock:
                    await self.session.send_realtime_input(text=text)
            else:
                await self.session.send_realtime_input(text=text)
            logger.debug(f"📤 Sent text (realtime): {text[:50]}...")

            # Track query for memory logging and conversation history
            self._last_query = text
            self._query_start_time = time.time()
            self._add_to_history("user", text)
            # Clear any leftover model response buffer
            self._current_model_response_parts.clear()
            # Suppress false barge-in for 2s after text send.
            # Gemini's server-side VAD often fires on the trailing mic audio
            # that was captured during the user's speech.
            self._barge_in_cooldown_until = time.time() + 2.0

            return True

        except Exception as e:
            if not self._send_error_logged:
                logger.warning(f"⚠️ Gemini send failed (text), suppressing further: {e}")
                self._send_error_logged = True
            self.is_connected = False
            return False

    async def send_context(self, text: str) -> bool:
        """
        Send silent context to Gemini Live API.

        Uses send_client_content(turn_complete=False) to inject context
        into the model's context window WITHOUT triggering a model turn.
        Previously used send_realtime_input(text=...) which is treated
        as user input → triggers model response → turn_complete →
        server closes the stream.

        Args:
            text: Context text to inject

        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_connected or not self.session:
            return False

        if self._is_gemini_live_31:
            if not self._context_disabled_logged:
                logger.info(
                    "📝 Mid-session context injection disabled for Gemini 3.1 Live"
                )
                self._context_disabled_logged = True
            return False

        try:
            turn = types.Content(
                role="user",
                parts=[types.Part(text=text)]
            )
            if self._send_lock:
                async with self._send_lock:
                    await self.session.send_client_content(
                        turns=turn, turn_complete=False
                    )
            else:
                await self.session.send_client_content(
                    turns=turn, turn_complete=False
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
        self._clear_audio_queue()

    def _clear_audio_queue(self):
        """Flush stale audio so dead-session audio cannot leak into next session."""
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
    
    def set_status_callback(self, callback: Callable[[str], None]):
        """Set callback function for status updates."""
        self.status_callback = callback

    def set_tool_callback(self, callback: Callable):
        """Set callback for Gemini function-calling tool invocations."""
        self._tool_callback = callback
        logger.info("✅ Tool callback registered on GeminiLiveHandler")


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
        self._outbound_queue: Optional[asyncio.Queue] = None
        self._pending_video_frame: Optional[Image.Image] = None  # Latest-wins video buffer
        self._video_send_pending = False  # Guard for dedup
        self._drop_audio_until = 0.0  # Short pause around text turns on live audio stream
        
        logger.info("✅ GeminiLiveManager initialized")

    def set_tool_callback(self, callback: Callable):
        """Set callback for Gemini function calling (thread-safe passthrough)."""
        self.handler.set_tool_callback(callback)
    
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
        self._outbound_queue = asyncio.Queue(maxsize=512)
        
        reconnect_delay = 1.0  # Fast reconnect between sessions
        max_delay = 15.0
        writer_task = self.loop.create_task(self._outbound_writer())
        
        try:
            while self.is_running:
                audio_task = None
                try:
                    # Start audio processing task
                    audio_task = self.loop.create_task(self._process_audio_queue())
                    
                    # Connect to Live API (blocks until disconnection)
                    self.loop.run_until_complete(self.handler.connect())
                    
                    # Handler returned because the underlying session ended.
                    logger.info("🔌 Gemini connection ended, reconnecting...")
                    # Only reset delay if session lived long enough to be healthy
                    session_duration = time.time() - (self.handler._connect_time or time.time())
                    if session_duration >= 20.0:
                        reconnect_delay = 1.0  # Healthy session — reset delay
                    else:
                        reconnect_delay = min(reconnect_delay * 1.2, max_delay)
                        logger.warning(f"⚠️ Short session ({session_duration:.1f}s) — backing off")
                    
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
                # Use async sleep so the event loop keeps draining queued
                # coroutines (send_audio, send_video) instead of accumulating
                # them in _ready queue and flushing in a burst on wake.
                self.loop.run_until_complete(asyncio.sleep(reconnect_delay))
                
                # Reset handler connection state for fresh connect
                self.handler.is_connected = False
                self.handler.session = None
            
        finally:
            writer_task.cancel()
            try:
                self.loop.run_until_complete(writer_task)
            except (asyncio.CancelledError, Exception):
                pass
            self.loop.close()
            self.is_running = False

    async def _outbound_writer(self):
        """Serialize all outbound session writes through one writer task."""
        try:
            while self.is_running:
                item = await self._outbound_queue.get()
                kind = item[0]

                if kind == "audio":
                    _, audio_bytes, sample_rate, scheduled_at = item
                    if time.monotonic() - scheduled_at > 0.5:
                        continue
                    if time.monotonic() < self._drop_audio_until:
                        continue
                    await self.handler.send_audio_chunk(audio_bytes, sample_rate)
                elif kind == "text":
                    audio_pause_s = item[2] if len(item) > 2 else 0.0
                    if audio_pause_s > 0:
                        self._drop_audio_until = max(
                            self._drop_audio_until,
                            time.monotonic() + audio_pause_s,
                        )
                    await self.handler.send_text(item[1])
                elif kind == "context":
                    await self.handler.send_context(item[1])
                elif kind == "activity_start":
                    await self.handler.send_activity_start()
                elif kind == "activity_end":
                    await self.handler.send_activity_end()
                elif kind == "video_flush":
                    try:
                        while self.is_running:
                            frame = self._pending_video_frame
                            self._pending_video_frame = None
                            if frame is None:
                                break
                            await self.handler.send_video_frame(frame)
                    finally:
                        self._video_send_pending = False
                        if self._pending_video_frame is not None and self.is_running:
                            self._schedule_video_flush()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"❌ Outbound writer error: {e}")

    def _queue_outbound(self, item):
        """Queue outbound work on the manager loop thread."""
        if not self._outbound_queue:
            return
        try:
            self._outbound_queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.debug(f"🗑️ Dropping outbound {item[0]} — queue full")

    def _schedule_video_flush(self):
        if self._video_send_pending:
            return
        self._video_send_pending = True
        self._queue_outbound(("video_flush",))
    
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
        self.loop.call_soon_threadsafe(self._queue_outbound, ("activity_start",))

    def send_activity_end(self):
        """Signal speech end (thread-safe)."""
        if not self.is_running or not self.loop:
            return
        self.loop.call_soon_threadsafe(self._queue_outbound, ("activity_end",))

    def send_audio(self, audio_bytes: bytes, sample_rate: int = 16000):
        """
        Send audio chunk (thread-safe).
        Drops stale chunks if the event loop is congested.
        
        Args:
            audio_bytes: Raw PCM audio bytes
            sample_rate: Audio sample rate (16000 Hz)
        """
        if not self.is_running or not self.loop:
            logger.debug("Manager not running, skipping send_audio")
            return

        scheduled_at = time.monotonic()
        self.loop.call_soon_threadsafe(
            self._queue_outbound,
            ("audio", audio_bytes, sample_rate, scheduled_at),
        )
    
    def send_video(self, frame: Image.Image):
        """
        Send video frame (thread-safe).
        Uses 'latest wins' pattern — only the most recent frame matters.
        
        Args:
            frame: PIL Image
        """
        if not self.is_running or not self.loop:
            logger.debug("Manager not running, skipping send_video")
            return

        def _queue_video():
            self._pending_video_frame = frame
            self._schedule_video_flush()

        self.loop.call_soon_threadsafe(_queue_video)
    
    def send_text(self, text: str, audio_pause_s: float = 0.75):
        """
        Send text prompt (thread-safe). Triggers a model response.
        
        Args:
            text: Text prompt
        """
        if not self.is_running or not self.loop:
            logger.debug("Manager not running, skipping send_text")
            return

        self.loop.call_soon_threadsafe(
            self._queue_outbound,
            ("text", text, audio_pause_s),
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

        self.loop.call_soon_threadsafe(self._queue_outbound, ("context", text))
    
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
