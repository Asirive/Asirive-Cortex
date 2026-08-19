"""
TTS Router - Smart Text-to-Speech Routing
==========================================

Routes text to the appropriate TTS engine based on text length:
- Short text (<300 chars): Gemini 2.5 Flash TTS (cloud, natural voice)
- Long text (>=300 chars): Supertonic TTS (local, ONNX, faster for long text)

Auto-saves every TTS output as a pristine .wav file to tts_recordings/
for video editing (mute camera audio, drag in the .wav).

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
Date: January 27, 2026
"""

import logging
import asyncio
import socket
import time
import re
import threading
from typing import Optional, Tuple, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# FIX-SAFETY-VOICE-COMMAND: lightweight network reachability probe for
# the safety-voice path. Cartesia is the preferred safety TTS (≈120ms
# TTFB, clear urgent prosody) but it's a cloud call. We must NOT block
# a 4-word "wall ahead" alert waiting on a TCP timeout. The probe
# tries DNS resolution first (cheap) and then a 0.5s TCP connect to
# the Cartesia API host (api.cartesia.ai:443). Result is cached for
# 10 seconds so the per-frame safety loop doesn't hammer DNS.
# ──────────────────────────────────────────────────────────────────────
_INTERNET_PROBE_CACHE = {"ok": True, "ts": 0.0}
_INTERNET_PROBE_TTL_S = 10.0
_INTERNET_PROBE_HOST = "api.cartesia.ai"
_INTERNET_PROBE_PORT = 443


def _cartia_internet_reachable() -> bool:
    """Return True if api.cartesia.ai is reachable. Cached for 10s."""
    now = time.time()
    if now - _INTERNET_PROBE_CACHE["ts"] < _INTERNET_PROBE_TTL_S:
        return _INTERNET_PROBE_CACHE["ok"]
    ok = True
    try:
        # DNS first — if resolution fails, skip the TCP connect entirely
        socket.getaddrinfo(_INTERNET_PROBE_HOST, _INTERNET_PROBE_PORT)
        # Then a short TCP probe with a tight timeout
        with socket.create_connection(
            (_INTERNET_PROBE_HOST, _INTERNET_PROBE_PORT), timeout=0.5
        ) as _s:
            pass
    except Exception:
        ok = False
    _INTERNET_PROBE_CACHE["ok"] = ok
    _INTERNET_PROBE_CACHE["ts"] = now
    if not ok:
        logger.debug(
            f"Cartesia unreachable — safety voice will use local Supertonic"
        )
    return ok


# TTS Engine imports (lazy loaded)
_gemini_tts = None
_supertonic_tts = None


def _get_gemini_tts():
    """Lazy load Gemini TTS handler."""
    global _gemini_tts
    if _gemini_tts is None:
        try:
            from rpi5.layer2_thinker.gemini_tts_handler import GeminiTTS
            _gemini_tts = GeminiTTS()
            logger.info("Loaded Gemini TTS")
        except Exception as e:
            logger.warning(f"Failed to load Gemini TTS: {e}")
    return _gemini_tts


def _get_supertonic_tts():
    """Lazy load Supertonic TTS handler."""
    global _supertonic_tts
    if _supertonic_tts is None:
        try:
            from rpi5.layer1_reflex.supertonic_handler import SupertonicTTS
            _supertonic_tts = SupertonicTTS()
            if not _supertonic_tts.available:
                logger.warning("Supertonic TTS not available")
                _supertonic_tts = None
            else:
                logger.info("Loaded Supertonic TTS")
        except Exception as e:
            logger.warning(f"Failed to load Supertonic TTS: {e}")
    return _supertonic_tts


_cartesia_tts = None


def _get_cartesia_tts():
    """Lazy load Cartesia Sonic 3.5 TTS handler."""
    global _cartesia_tts
    if _cartesia_tts is None:
        try:
            from rpi5.layer2_thinker.cartesia_handler import CartesiaTTS
            _cartesia_tts = CartesiaTTS()
            if _cartesia_tts.available:
                logger.info("Loaded Cartesia Sonic 3.5 TTS")
            else:
                _cartesia_tts = None
        except Exception as e:
            logger.warning(f"Failed to load Cartesia TTS: {e}")
    return _cartesia_tts


class TTSRouter:
    """
    Smart TTS router that selects the best TTS engine based on text length.
    
    Routing logic:
    - Short text (<300 chars): Gemini 2.5 Flash TTS (natural, cloud-based)
    - Long text (>=300 chars): Supertonic TTS (local, ONNX, faster for long responses)
    - Cartesia Sonic 3.5: Ultra-low latency cloud TTS for Layer 2 (via engine_override)
    - Fallback: If primary engine fails, use the other
    
    Engine override options: "gemini", "supertonic", "cartesia"
    """
    
    _instance = None  # Singleton
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super(TTSRouter, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        length_threshold: int = 300,
        prefer_local: bool = False,
        audio_output_dir: str = "temp_audio"
    ):
        """
        Initialize TTS Router.
        
        Args:
            length_threshold: Character count threshold for switching to Supertonic
            prefer_local: If True, always use Supertonic (offline mode)
            audio_output_dir: Directory for temporary audio files
        """
        if self._initialized:
            return
            
        self.length_threshold = length_threshold
        self.prefer_local = prefer_local
        self.audio_output_dir = Path(audio_output_dir)
        self.audio_output_dir.mkdir(exist_ok=True)
        
        # TTS recordings directory — pristine .wav files for video editing
        self.recordings_dir = Path("tts_recordings")
        self.recordings_dir.mkdir(exist_ok=True)
        self._recording_counter = 0  # Sequential numbering for easy sorting
        
        self._gemini_available = False
        self._supertonic_available = False
        self._cartesia_available = False
        self._playback_lock = threading.Lock()
        self._active_playbacks = 0

        # TUI state publishing — the FULL Textual dashboard reads
        # tts.engine/tts.state from DashboardState. Without this, the
        # TTS panel always shows "[idle]" even when we're speaking.
        self._dashboard_state = None  # set via bind_dashboard_state()
        self._last_engine = ""  # last engine used (for idle-state re-publish)
        self.muted = False
        
        # Audio queue integration — prevents TTS from playing over Gemini Live
        try:
            from rpi5.cli.audio_queue import audio_queue
            self._audio_queue = audio_queue
            self._audio_queue_active = True
        except ImportError:
            self._audio_queue = None
            self._audio_queue_active = False
        
        self._initialized = True
        logger.info(f"TTSRouter initialized (threshold: {length_threshold} chars)")
        logger.info(f"TTS recordings will be saved to: {self.recordings_dir.absolute()}")
        if self._audio_queue_active:
            logger.info("   Audio queue: ENABLED (TTS will wait for Gemini Live)")

    @property
    def is_playing(self) -> bool:
        """Return True while any local TTS playback is active."""
        with self._playback_lock:
            return self._active_playbacks > 0

    def bind_dashboard_state(self, dashboard_state) -> None:
        """Wire the TTSRouter to push its current engine/state to a
        DashboardState so the Textual TUI's TTS panel stays in sync."""
        self._dashboard_state = dashboard_state

    def _publish_tts_state(self, engine: str = "", state: str = "idle") -> None:
        """Push the current TTS engine + state to DashboardState.
        No-op if DashboardState wasn't bound. Uses `safe_publish` so
        a TUI disconnect can't break a TTS call."""
        if self._dashboard_state is None:
            return
        try:
            voice = ""
            speed = 1.0
            # Pull voice from the active engine when known
            if engine == "cartesia":
                voice = "Cartesia Sonic 3.5"
            elif engine == "supertonic":
                voice = "Supertonic (local ONNX)"
            elif engine == "gemini":
                voice = "Gemini 2.5 Flash TTS"
            elif engine == "gemini-live":
                voice = "Gemini Live (Zephyr)"
            self._dashboard_state.update(tts={
                "engine": engine,
                "state": state,
                "voice": voice,
                "speed": speed,
                "muted": bool(getattr(self, "muted", False)),
            })
        except Exception:
            pass

    def _mark_playback_start(self):
        with self._playback_lock:
            self._active_playbacks += 1

    def _mark_playback_end(self):
        with self._playback_lock:
            self._active_playbacks = max(0, self._active_playbacks - 1)
        # When the last active playback ends, flip the TTS panel back to
        # idle so the operator can see we're ready for the next utterance
        # (bug: panel used to stick on "speaking" forever).
        if self._active_playbacks == 0:
            self._publish_tts_state(engine=self._last_engine, state="idle")

    # FIX-SAFETY-VOICE-COMMAND: light wrapper around the project-wide
    # async-bridge loop used by run_async_safe(). Kept here (instead of
    # importing from main.py) so the tts module has no main.py
    # dependency cycle.
    _bridge_loop = None
    _bridge_thread = None
    _bridge_lock = threading.Lock()

    def _ensure_bridge_loop(self):
        """Start a background event loop on first use, return it."""
        with self._bridge_lock:
            if self._bridge_loop is not None and self._bridge_thread is not None and self._bridge_thread.is_alive():
                return self._bridge_loop
            loop = asyncio.new_event_loop()
            ready = threading.Event()
            t = threading.Thread(
                target=lambda: (asyncio.set_event_loop(loop), ready.set(), loop.run_forever()),
                name="tts-safety-bridge",
                daemon=True,
            )
            t.start()
            ready.wait(timeout=2.0)
            self._bridge_loop = loop
            self._bridge_thread = t
            return loop

    def _remember_engine(self, engine: str) -> None:
        """Cache the last engine used so playback-end can re-publish it
        with state='idle' (keeps the TTS panel showing which engine was
        last used even after the playback completes)."""
        self._last_engine = engine
    
    def _save_recording(self, audio_data: bytes, engine: str, text: str):
        """
        Save a pristine copy of TTS audio for video editing.
        
        Files are saved as: tts_recordings/NNN_engine_textsnippet.wav
        A companion .txt file stores the full text for reference.
        
        Args:
            audio_data: WAV audio bytes
            engine: Engine name ("supertonic", "cartesia", "gemini")
            text: Full text that was spoken
        """
        try:
            self._recording_counter += 1
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            
            # Sanitize text for filename (keep only alphanum + spaces, truncate)
            safe_text = re.sub(r'[^a-zA-Z0-9 ]', '', text)[:40].strip().replace(' ', '_')
            if not safe_text:
                safe_text = "response"
            
            basename = f"{self._recording_counter:04d}_{timestamp}_{engine}_{safe_text}"
            wav_path = self.recordings_dir / f"{basename}.wav"
            txt_path = self.recordings_dir / f"{basename}.txt"
            
            # Save pristine WAV
            with open(wav_path, 'wb') as f:
                f.write(audio_data)
            
            # Save companion text file (full text + metadata)
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(f"Engine: {engine}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Text length: {len(text)} chars\n")
                f.write(f"Audio size: {len(audio_data)} bytes\n")
                f.write(f"---\n")
                f.write(text)
            
            logger.info(f"TTS recording saved: {wav_path.name} ({len(audio_data)} bytes)")
        except Exception as e:
            logger.warning(f"Failed to save TTS recording: {e}")
    
    def initialize(self) -> Tuple[bool, bool]:
        """
        Pre-initialize all TTS engines.
        
        Returns:
            Tuple of (gemini_available, supertonic_available)
        """
        gemini = _get_gemini_tts()
        self._gemini_available = gemini is not None
        
        supertonic = _get_supertonic_tts()
        self._supertonic_available = supertonic is not None
        
        cartesia = _get_cartesia_tts()
        self._cartesia_available = cartesia is not None
        
        logger.info(f"TTS Engines: Gemini={self._gemini_available}, Supertonic={self._supertonic_available}, Cartesia={self._cartesia_available}")
        
        return self._gemini_available, self._supertonic_available
    
    def select_engine(self, text: str) -> str:
        """
        Select the appropriate TTS engine for the given text.
        
        Args:
            text: Text to synthesize
            
        Returns:
            "cartesia", "supertonic", or "gemini"
        """
        if self.prefer_local:
            return "supertonic"
        
        # Primary: Cartesia Sonic 3.5 (lowest latency cloud TTS)
        if self._cartesia_available:
            return "cartesia"
        
        text_length = len(text)
        
        if text_length >= self.length_threshold:
            # Long text -> Supertonic (faster for long responses, local)
            return "supertonic"
        else:
            # Short text -> Gemini (more natural voice)
            return "gemini"
    
    async def speak_async(
        self,
        text: str,
        play_audio: bool = True,
        save_path: Optional[str] = None,
        engine_override: Optional[str] = None
    ) -> Tuple[bool, str, Optional[bytes]]:
        """
        Synthesize and optionally play text using the appropriate TTS engine.
        
        Args:
            text: Text to speak
            play_audio: If True, play audio immediately
            save_path: Optional path to save audio file
            engine_override: Force a specific engine ("gemini", "supertonic", or "cartesia"),
                             bypassing the automatic selection logic.
            
        Returns:
            Tuple of (success, engine_used, audio_bytes)
        """
        engine = engine_override or self.select_engine(text)
        requested_engine = engine  # M21 fix: remember the original choice
        if self.muted:
            logger.info(f"TTS muted — skipping '{text[:50]}'")
            self._publish_tts_state(engine="muted", state="muted")
            return False, "muted", None
        logger.info(f"TTS routing '{text[:50]}...' to {engine} ({len(text)} chars)")

        # Track the active engine so the TUI's TTS panel can show it
        # in real time. Without this, the panel always shows "[idle]".
        self._remember_engine(engine)
        self._publish_tts_state(engine=engine, state="speaking")

        success = False
        audio_data = None
        fallback_used = False

        try:
            if engine == "cartesia":
                success, audio_data = await self._speak_cartesia(text, play_audio, save_path)
                if not success:
                    logger.warning("Cartesia TTS failed, falling back to Supertonic")
                    engine = "supertonic"
                    fallback_used = True
                    success, audio_data = await self._speak_supertonic(text, play_audio, save_path)
                    if not success:
                        logger.warning("Supertonic TTS also failed, falling back to Gemini")
                        engine = "gemini"
                        success, audio_data = await self._speak_gemini(text, play_audio, save_path)
            elif engine == "gemini":
                success, audio_data = await self._speak_gemini(text, play_audio, save_path)
                if not success:
                    logger.warning("Gemini TTS failed, falling back to Supertonic")
                    engine = "supertonic"
                    fallback_used = True
                    success, audio_data = await self._speak_supertonic(text, play_audio, save_path)
            else:
                success, audio_data = await self._speak_supertonic(text, play_audio, save_path)
                if not success:
                    logger.warning("Supertonic TTS failed, falling back to Gemini")
                    engine = "gemini"
                    fallback_used = True
                    success, audio_data = await self._speak_gemini(text, play_audio, save_path)
            # M21 fix: when a fallback fires and the user's chosen engine
            # was unavailable, surface it through a dedicated engine
            # name so the TUI can show "cartesia→supertonic" instead
            # of silently substituting.
            if fallback_used and engine_override is None and success:
                engine = f"{requested_engine}→{engine}"
        
        except Exception as e:
            logger.error(f"TTS error: {e}")
            # M22 fix: publish an "error" state so the TUI panel
            # doesn't stay stuck on "speaking" forever after a
            # failure. The TUI state for TTS only transitions
            # out of "speaking" via the success path's
            # state="idle" publish (line 208); an exception
            # skipped that publish and left the panel frozen.
            self._publish_tts_state(engine=engine, state="error")

        # Auto-save pristine recording for video editing
        if success and audio_data:
            self._save_recording(audio_data, engine, text)

        return success, engine, audio_data

    # ──────────────────────────────────────────────────────────────────────
    # FIX-SAFETY-VOICE-COMMAND: dedicated safety-voice path. Replaces the
    # old haptic + plain speak_async combo. The user said "haptic is not
    # being used" — haptic on the RPi5 has no physical actuator wired up
    # (the BOM lists a vibration motor but it's not connected in the
    # current glasses prototype), so haptics do literally nothing. Voice
    # commands via Cartesia TTS, with a local Supertonic fallback when
    # WiFi is unavailable, are the actual safety path.
    #
    # Differences from `speak_async`:
    #   - Force Cartesia Sonic 3.5 (not Gemini) — ~120ms TTFB, much
    #     faster than Gemini TTS for short bursts, and Gemini's voice
    #     "Kore" doesn't carry urgency well for 4-word safety phrases.
    #   - Bypass the is_output_playing echo gate. Safety must be heard
    #     even when Gemini is mid-sentence.
    #   - Bypass the audio-queue wait. If Gemini is speaking, we
    #     INTERRUPT it (the user is more interested in "wall ahead" than
    #     whatever Gemini was saying about the door).
    #   - Auto-fallback to Supertonic local TTS when:
    #       a) Cartesia API call fails (timeout, 4xx, 5xx)
    #       b) No internet reachability (DNS / TCP probe to cartesia.ai)
    # ──────────────────────────────────────────────────────────────────────
    _SAFETY_INTERRUPT_ENGINES = {"gemini-live", "cartesia", "supertonic", "gemini"}

    async def speak_safety(
        self,
        text: str,
        emotion: str = "alarmed",
    ) -> Tuple[bool, str]:
        """
        Speak a safety alert. Cartesia first, local Supertonic fallback.

        Args:
            text: short safety phrase (≤80 chars recommended)
            emotion: Cartesia emotion tag (alarmed, panicked, scared, ...)
                     Default "alarmed" — a valid Sonic 3.5 emotion. The
                     previous default of "urgent" was NOT in the Sonic
                     3.5 enum and silently fell back to the instance
                     default ("calm"), making the safety voice sound
                     calm — the opposite of the safety intent.

        Returns:
            (success, engine_used)
        """
        if self.muted:
            return False, "muted"
        if not text or not text.strip():
            return False, "empty"

        # 1. Try Cartesia (cloud, fastest, most natural)
        # FIX-SAFETY-TTS-CARTESIA-FIRST: removed the
        # `_cartia_internet_reachable()` gate. The probe was caching
        # a single transient DNS failure for 10s, which caused the
        # safety voice to silently fall through to Supertonic for
        # the next 10 seconds. Gemini Live (which also hits the
        # cloud) was working fine in the same window, so the network
        # IS available — the probe was a false negative. The
        # try/except below already handles Cartesia failures
        # gracefully (falls through to Supertonic), so the gate
        # was a net negative.
        if self._cartesia_available:
            try:
                success = await self._speak_safety_cartesia(text, emotion)
                if success:
                    self._remember_engine("cartesia")
                    self._publish_tts_state(engine="cartesia", state="speaking")
                    return True, "cartesia"
                else:
                    logger.debug("Safety Cartesia returned False (no audio)")
            except Exception as e:
                logger.warning(f"⚠️ Safety Cartesia attempt failed: {type(e).__name__}: {e}")

        # 2. Local Supertonic fallback
        if self._supertonic_available:
            try:
                success, audio_data = await self._speak_supertonic(
                    text, play_audio=True, save_path=None
                )
                if success:
                    self._remember_engine("supertonic")
                    self._publish_tts_state(engine="supertonic", state="speaking")
                    return True, "supertonic"
                logger.debug("Safety Supertonic attempt failed (returned False)")
            except Exception as e:
                logger.debug(f"Safety Supertonic attempt failed: {e}")

        # 3. Last resort: Gemini TTS
        if self._gemini_available:
            try:
                success, audio_data = await self._speak_gemini(
                    text, play_audio=True, save_path=None
                )
                if success:
                    self._remember_engine("gemini")
                    self._publish_tts_state(engine="gemini", state="speaking")
                    return True, "gemini"
            except Exception as e:
                logger.debug(f"Safety Gemini fallback failed: {e}")

        logger.warning(f"⚠️ speak_safety: all TTS engines failed for '{text[:50]}'")
        return False, "none"

    async def _speak_safety_cartesia(self, text: str, emotion: str) -> bool:
        """Synthesize + play a safety phrase via Cartesia. Interrupt-safe.
        FIX-SAFETY-VOICE-MALE: uses the dedicated safety voice (Troy —
        strong, dependable male, "designed for trust-building") so the
        user can distinguish a safety alert from a Gemini Live reply
        (Zephyr, female) without parsing the words first.

        FIX-SAFETY-CARTESIA-IMPORT: `_get_cartesia_tts` is the
        module-level factory defined at the top of this same file
        (`tts_router.py:107`). The previous code tried to import it
        from `rpi5.layer2_thinker.cartesia_handler`, which doesn't
        expose it — resulting in `ImportError: cannot import name
        '_get_cartesia_tts'` and silent safety-TTS fallback. Use the
        local reference directly.
        """
        cartesia = _get_cartesia_tts()
        if not cartesia:
            return False
        # Run synthesis in a worker thread (the SDK is sync).
        # Pass voice_id explicitly so the safety voice is used even if
        # someone later changes the default of generate_speech_with_emotion.
        audio_bytes = await asyncio.to_thread(
            cartesia.generate_speech_with_emotion,
            text, emotion,
            getattr(cartesia, "_voice_id_safety", None),
        )
        if not audio_bytes:
            return False
        # Save to temp file, then play with paplay (same as _play_audio_file).
        temp_path = str(self.audio_output_dir / "safety_temp.wav")
        try:
            with open(temp_path, "wb") as f:
                f.write(audio_bytes)
        except Exception as e:
            logger.error(f"safety temp write failed: {e}")
            return False
        # Bypass the audio queue so safety overrides Gemini.
        import platform
        if platform.system() == "Linux":
            import subprocess
            self._mark_playback_start()
            try:
                await asyncio.to_thread(
                    subprocess.run, ["paplay", temp_path],
                    check=False, timeout=10
                )
            finally:
                self._mark_playback_end()
            return True
        return False

    def speak_safety_sync(self, text: str, emotion: str = "alarmed") -> Tuple[bool, str]:
        """Sync wrapper for speak_safety. Returns (success, engine)."""
        try:
            asyncio.get_running_loop()
            # Async context — schedule on the async bridge
            import concurrent.futures
            bridge_loop = self._ensure_bridge_loop()
            future = asyncio.run_coroutine_threadsafe(
                self.speak_safety(text, emotion), bridge_loop
            )
            try:
                return future.result(timeout=15)
            except Exception as e:
                logger.debug(f"speak_safety_sync bridge error: {e}")
                return False, "bridge_error"
        except RuntimeError:
            # No running loop — use a fresh one
            try:
                return asyncio.run(self.speak_safety(text, emotion))
            except Exception as e:
                logger.debug(f"speak_safety_sync run error: {e}")
                return False, "run_error"
    
    def speak(
        self,
        text: str,
        play_audio: bool = True,
        save_path: Optional[str] = None
    ) -> Tuple[bool, str, Optional[bytes]]:
        """
        Synchronous wrapper for speak_async.

        H20 fix: the previous implementation called
        `asyncio.run_coroutine_threadsafe(...).result(timeout=30)` from
        inside an async caller occupying the same loop. The future
        could never complete because the coroutine needed the same
        loop it was blocking — and `.result(timeout=30)` then timed
        out after 30 seconds for every TTS call, ballooning voice
        feedback latency. Now we detect the running loop and return
        the awaitable directly, so async callers can `await` it
        naturally; sync callers fall through to `asyncio.run`.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — safe to use asyncio.run() for a
            # one-shot execution.
            return asyncio.run(self.speak_async(text, play_audio, save_path))

        # We're already in an async context on this loop. We CANNOT
        # block on `.result()` here (would deadlock). Provide a
        # coroutine wrapper that the caller can choose to await.
        # Keep the method signature compatible (returns tuple) by
        # dispatching a fire-and-forget task and returning a synthetic
        # "scheduled" result immediately.
        try:
            self._loop = loop
            future = asyncio.run_coroutine_threadsafe(
                self.speak_async(text, play_audio, save_path),
                loop,
            )
            # Stash the future so the orchestrator can await it if it
            # wants to. We do NOT block here.
            self._last_speak_future = future
        except RuntimeError:
            pass
        # Return a "scheduled" sentinel. The actual result will be
        # observable via the state publisher. Async callers should
        # prefer `speak_async` directly.
        return (True, "scheduled", None)
    
    async def _speak_gemini(
        self,
        text: str,
        play_audio: bool,
        save_path: Optional[str]
    ) -> Tuple[bool, Optional[bytes]]:
        """Use Gemini TTS to synthesize speech."""
        gemini = _get_gemini_tts()
        if not gemini:
            return False, None
        
        try:
            # GeminiTTS.generate_speech_from_text() returns path to saved audio file
            audio_path = await asyncio.to_thread(
                gemini.generate_speech_from_text, text
            )
            
            if audio_path:
                audio_data = None
                if save_path or not play_audio:
                    with open(audio_path, 'rb') as f:
                        audio_data = f.read()
                    if save_path:
                        import shutil
                        shutil.copy(audio_path, save_path)
                
                if play_audio:
                    # Play using sounddevice or system audio
                    await self._play_audio_file(audio_path)
                
                return True, audio_data
            
            return False, None
            
        except Exception as e:
            logger.error(f"Gemini TTS error: {e}")
            return False, None
    
    async def _speak_supertonic(
        self,
        text: str,
        play_audio: bool,
        save_path: Optional[str]
    ) -> Tuple[bool, Optional[bytes]]:
        """Use Supertonic TTS to synthesize speech."""
        supertonic = _get_supertonic_tts()
        if not supertonic:
            return False, None
        
        try:
            # SupertonicTTS.generate_wav_bytes() returns WAV bytes at 24kHz
            audio_bytes = await asyncio.to_thread(supertonic.generate_wav_bytes, text)
            
            if audio_bytes:
                if save_path:
                    with open(save_path, 'wb') as f:
                        f.write(audio_bytes)
                
                if play_audio:
                    # Save to temp file and play via paplay
                    temp_path = str(self.audio_output_dir / "supertonic_temp.wav")
                    with open(temp_path, 'wb') as f:
                        f.write(audio_bytes)
                    await self._play_audio_file(temp_path)
                
                return True, audio_bytes
            
            return False, None
            
        except Exception as e:
            logger.error(f"Supertonic TTS error: {e}")
            return False, None
    
    async def _speak_cartesia(
        self,
        text: str,
        play_audio: bool,
        save_path: Optional[str]
    ) -> Tuple[bool, Optional[bytes]]:
        """Use Cartesia Sonic 3.5 TTS to synthesize speech."""
        cartesia = _get_cartesia_tts()
        if not cartesia:
            return False, None
        
        try:
            # CartesiaTTS.generate_speech() returns WAV bytes directly
            audio_bytes = await asyncio.to_thread(cartesia.generate_speech, text)
            
            if audio_bytes:
                if save_path:
                    with open(save_path, 'wb') as f:
                        f.write(audio_bytes)
                
                if play_audio:
                    # Save to temp file and play via sounddevice
                    temp_path = str(self.audio_output_dir / "cartesia_temp.wav")
                    with open(temp_path, 'wb') as f:
                        f.write(audio_bytes)
                    await self._play_audio_file(temp_path)
                
                return True, audio_bytes
            
            return False, None
            
        except Exception as e:
            logger.error(f"Cartesia TTS error: {e}")
            return False, None
    
    async def _play_audio_file(self, audio_path: str):
        """Play an audio file via paplay (Linux/PipeWire) or sounddevice (fallback).
        
        On Linux (RPi5), uses paplay (PipeWire-aware) so audio routes through
        the correct BT default sink set by BluetoothAudioManager.
        
        If audio queue is active, waits for Gemini Live to finish first.
        """
        # Wait for Gemini Live to finish before playing TTS (prevents overlap)
        if self._audio_queue_active and self._audio_queue:
            waited = 0.0
            max_wait = 5.0  # Don't block TTS for more than 5s
            # FIX-AUDIO-QUEUE: use getattr with default. The
            # AudioQueueManager class was refactored and the
            # `_gemini_active` attribute is no longer always
            # present, so accessing it directly raises AttributeError
            # and the TTS call returns False ("no result"). This
            # safety check makes the TTS work even if the manager's
            # internal state contract changes.
            _gemini_busy = bool(getattr(self._audio_queue, '_gemini_active', False))
            while _gemini_busy and waited < max_wait:
                await asyncio.sleep(0.1)
                waited += 0.1
                _gemini_busy = bool(getattr(self._audio_queue, '_gemini_active', False))
            if waited >= max_wait:
                logger.debug("TTS waited 5s for Gemini, playing anyway")
        
        import platform
        self._mark_playback_start()
        if platform.system() == "Linux":
            import subprocess
            try:
                await asyncio.to_thread(
                    subprocess.run, ["paplay", audio_path],
                    check=False, timeout=30
                )
            except Exception as e:
                logger.error(f"paplay error: {e}")
            finally:
                self._mark_playback_end()
            return
        
        # Non-Linux fallback
        try:
            import sounddevice as sd
            import soundfile as sf
            data, samplerate = sf.read(audio_path)
            sd.play(data, samplerate)
            sd.wait()
        except Exception as e:
            logger.error(f"Audio playback error: {e}")
        finally:
            self._mark_playback_end()
    
    async def _play_audio_samples(self, samples, sample_rate: int):
        """Play audio samples via paplay (Linux/PipeWire) or sounddevice (fallback).
        
        On Linux (RPi5), writes a temp WAV and uses paplay (PipeWire-aware)
        so audio routes through the correct BT default sink.
        
        If audio queue is active, waits for Gemini Live to finish first.
        """
        # Wait for Gemini Live to finish before playing TTS (prevents overlap)
        if self._audio_queue_active and self._audio_queue:
            waited = 0.0
            max_wait = 5.0
            # FIX-AUDIO-QUEUE: see the first occurrence in this
            # file for the rationale.
            _gemini_busy = bool(getattr(self._audio_queue, '_gemini_active', False))
            while _gemini_busy and waited < max_wait:
                await asyncio.sleep(0.1)
                waited += 0.1
                _gemini_busy = bool(getattr(self._audio_queue, '_gemini_active', False))
            if waited >= max_wait:
                logger.debug("TTS waited 5s for Gemini, playing anyway")
        
        import platform
        self._mark_playback_start()
        if platform.system() == "Linux":
            import tempfile
            import wave
            import numpy as np
            import subprocess
            import os
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                    temp_path = f.name
                    with wave.open(f, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
                        if isinstance(samples, np.ndarray) and samples.dtype == np.float32:
                            samples = (samples * 32767).astype(np.int16)
                        wf.writeframes(samples.tobytes())
                await asyncio.to_thread(
                    subprocess.run, ["paplay", temp_path],
                    check=False, timeout=30
                )
            except Exception as e:
                logger.error(f"paplay samples error: {e}")
            finally:
                if temp_path:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                self._mark_playback_end()
            return
        
        # Non-Linux fallback
        try:
            import sounddevice as sd
            sd.play(samples, sample_rate)
            sd.wait()
        except Exception as e:
            logger.error(f"Audio playback error: {e}")
        finally:
            self._mark_playback_end()


# =============================================================================
# Convenience Functions
# =============================================================================

_router_instance: Optional[TTSRouter] = None


def get_tts_router() -> TTSRouter:
    """Get the singleton TTS router instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = TTSRouter()
    return _router_instance


def speak(text: str, play_audio: bool = True) -> bool:
    """
    Quick speak function using smart TTS routing.
    
    Args:
        text: Text to speak
        play_audio: If True, play audio immediately
        
    Returns:
        True if successful
    """
    router = get_tts_router()
    success, engine, _ = router.speak(text, play_audio)
    return success


async def speak_async(text: str, play_audio: bool = True) -> bool:
    """
    Async speak function using smart TTS routing.
    
    Args:
        text: Text to speak
        play_audio: If True, play audio immediately
        
    Returns:
        True if successful
    """
    router = get_tts_router()
    success, engine, _ = await router.speak_async(text, play_audio)
    return success


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    router = TTSRouter()
    
    # Test engine selection
    short_text = "I see 3 storage boxes and 1 person."
    long_text = "In front of you, I can see a complex scene. " * 10  # ~400 chars
    
    print(f"Short text ({len(short_text)} chars) -> {router.select_engine(short_text)}")
    print(f"Long text ({len(long_text)} chars) -> {router.select_engine(long_text)}")
    
    # Test actual synthesis if argument provided
    if len(sys.argv) > 1:
        test_text = " ".join(sys.argv[1:])
        print(f"\nSpeaking: '{test_text}'")
        
        async def test():
            router.initialize()
            success, engine, _ = await router.speak_async(test_text)
            print(f"Result: {'SUCCESS' if success else 'FAILED'} (engine: {engine})")
        
        asyncio.run(test())
