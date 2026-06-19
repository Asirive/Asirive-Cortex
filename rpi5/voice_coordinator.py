"""
Voice Coordinator Module
========================

Orchestrates Voice Activity Detection (Silero VAD) and Speech-to-Text (Whisper).
Part of the Production Mode pipeline for "Always On" voice commands.

STT engines (selected via `stt.cartesia_mode` in config):
- batch:     Cartesia Ink-Whisper HTTP POST (default, ~66ms)
- websocket: Cartesia Ink 2 streaming with built-in turn detection

Author: Haziq (@IRSPlays)
Date: January 17, 2026
"""

import logging
import asyncio
import queue as _queue
import threading
import time
import numpy as np
from typing import Callable, Optional, List

from rpi5.layer1_reflex.vad_handler import VADHandler
from rpi5.layer1_reflex.whisper_handler import WhisperSTT
from rpi5.layer1_reflex.cartesia_stt import CartesiaSTT

logger = logging.getLogger(__name__)


class VoiceCoordinator:
    """
    Coordinates VAD listening and Whisper transcription.
    Calls a callback with the transcribed text.

    NEW: Command Queue Mode (for noisy environments)
    When barge-in is disabled and Gemini is speaking, user speech is buffered
    locally instead of being discarded. After Gemini stops, the buffer is
    evaluated and sent to STT if it contains valid speech.
    """

    def __init__(self, on_command_detected: Callable[[str], None], config: Optional[dict] = None, system: Optional[object] = None):
        """
        Args:
            on_command_detected: Async callback function(text: str) -> None
            config: Optional config dict (from config.yaml 'audio' section)
            system: Optional CortexSystem reference — used to push STT
                transcripts and event-feed entries into the live dashboard.
        """
        self.on_command_detected = on_command_detected
        self.config = config or {}
        # Optional CortexSystem reference — used by the dashboard activity feed
        # so STT transcripts and command dispatches show up in the unified
        # timeline alongside safety alerts, L2 tool calls, and nav changes.
        self.system = system
        self.vad = None
        self.stt = None         # Local Whisper (offline fallback)
        self.cloud_stt = None   # Cartesia Ink (primary, cloud) — batch HTTP
        self.ws_stt = None      # Cartesia Ink 2 — WebSocket streaming
        self._ws_mode_active = False
        self._ws_chunk_queue: Optional[_queue.Queue] = None
        self._ws_drain_task: Optional[asyncio.Task] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_lock = threading.Lock()
        self.is_active = False
        # Optional raw audio callback: fn(audio_bytes: bytes, sample_rate: int) -> None
        # Set this after init to forward PCM audio to GeminiLiveHandler (audio-to-audio path)
        self.on_raw_audio: Optional[Callable] = None
        # Optional microphone tap for recording raw 16kHz PCM chunks.
        self.on_mic_audio: Optional[Callable] = None
        # Optional activity signal callbacks for explicit VAD
        self.on_speech_start_callback: Optional[Callable] = None
        self.on_speech_end_callback: Optional[Callable] = None
        # Optional callback fired when the user interrupts model playback.
        self.on_barge_in_callback: Optional[Callable] = None
        # Callback that returns True when speaker output is active (echo suppression)
        # Set by main.py to check gemini_audio_player state
        self.is_output_playing: Optional[Callable[[], bool]] = None
        self.barge_in_enabled = bool((self.config.get('vad') or {}).get('barge_in_enabled', True))

        # Command queue config (buffer speech during playback)
        vad_cfg = self.config.get('vad', {})
        self._command_queue_enabled = bool(vad_cfg.get('command_queue_enabled', True))
        self._command_queue_max_ms = int(vad_cfg.get('command_queue_max_duration_ms', 5000))
        self._command_queue_min_ms = int(vad_cfg.get('command_queue_min_valid_ms', 400))

        # Noise gate config
        self._noise_gate_db = float(vad_cfg.get('noise_gate_db', -40))

        # Hall mode config
        hall_cfg = vad_cfg.get('hall_mode', {})
        self._hall_mode_enabled = bool(hall_cfg.get('enabled', False))
        self._hall_mode_threshold = float(hall_cfg.get('threshold', 0.80))
        self._hall_mode_min_speech = int(hall_cfg.get('min_speech_duration_ms', 600))
        self._hall_mode_min_silence = int(hall_cfg.get('min_silence_duration_ms', 700))
        self._hall_mode_noise_gate = float(hall_cfg.get('noise_gate_db', -35))
        self._hall_mode_debounce = float(hall_cfg.get('debounce_seconds', 3))

        # Hall mode auto-detection state
        self._vad_trigger_times: List[float] = []
        self._in_hall_mode = False

        # Command queue state
        self._cmd_queue_buffer: Optional[np.ndarray] = None
        self._cmd_queue_speech_ms = 0.0
        self._cmd_queue_silence_ms = 0.0
        self._cmd_queue_active = False
        self._cmd_queue_last_eval = 0.0

        # Debounce state
        self._last_stt_time = 0.0
        self._debounce_seconds = self._hall_mode_debounce if self._in_hall_mode else 0.0

        # Tracks whether continuous audio hook is wired
        self._continuous_audio_wired = False
        self._speech_started_during_output = False
        self._ignore_current_speech_segment = False

    @property
    def is_listening(self) -> bool:
        """Alias for is_active (compatibility with main.py)."""
        return self.is_active

    def _rms_db(self, audio: np.ndarray) -> float:
        """Compute RMS in dB. Returns -inf for silence."""
        if audio is None or len(audio) == 0:
            return -float('inf')
        rms = np.sqrt(np.mean(audio ** 2))
        if rms <= 0:
            return -float('inf')
        return 20 * np.log10(rms)

    def _passes_noise_gate(self, audio: np.ndarray) -> bool:
        """Return True if audio level is above the noise gate threshold."""
        gate = self._hall_mode_noise_gate if self._in_hall_mode else self._noise_gate_db
        db = self._rms_db(audio)
        passes = db >= gate
        if not passes:
            logger.debug(f"🔇 Noise gate blocked: {db:.1f}dB < {gate}dB")
        return passes

    def _update_hall_mode(self):
        """Auto-enable hall mode if >5 VAD triggers in 10 seconds."""
        if not self._hall_mode_enabled:
            return
        now = time.time()
        # Keep only triggers in last 10s
        self._vad_trigger_times = [t for t in self._vad_trigger_times if now - t < 10.0]
        self._vad_trigger_times.append(now)
        was_hall = self._in_hall_mode
        self._in_hall_mode = len(self._vad_trigger_times) >= 5
        if self._in_hall_mode and not was_hall:
            logger.info(f"🏛️ Hall mode AUTO-ENABLED ({len(self._vad_trigger_times)} VAD triggers in 10s)")
            self._debounce_seconds = self._hall_mode_debounce
        elif not self._in_hall_mode and was_hall:
            logger.info("🏛️ Hall mode disabled (quiet environment detected)")
            self._debounce_seconds = 0.0

    def _get_effective_vad_config(self) -> dict:
        """Return VAD config adjusted for hall mode if active."""
        if self._in_hall_mode:
            return {
                'threshold': self._hall_mode_threshold,
                'min_speech_duration_ms': self._hall_mode_min_speech,
                'min_silence_duration_ms': self._hall_mode_min_silence,
            }
        vad_cfg = self.config.get('vad', {})
        return {
            'threshold': vad_cfg.get('threshold', 0.65),
            'min_speech_duration_ms': vad_cfg.get('min_speech_duration_ms', 400),
            'min_silence_duration_ms': vad_cfg.get('min_silence_duration_ms', 500),
        }

    def initialize(self):
        """Initialize VAD, Cartesia cloud STT (primary), and Whisper (fallback)"""
        try:
            # Read VAD config (with tuned defaults for noisy environments)
            vad_cfg = self._get_effective_vad_config()
            vad_threshold = vad_cfg['threshold']
            vad_min_speech = vad_cfg['min_speech_duration_ms']
            vad_min_silence = vad_cfg['min_silence_duration_ms']
            vad_padding = self.config.get('vad', {}).get('padding_duration_ms', 200)

            # Initialize VAD with config-driven params
            self.vad = VADHandler(
                threshold=vad_threshold,
                min_speech_duration_ms=vad_min_speech,
                min_silence_duration_ms=vad_min_silence,
                padding_duration_ms=vad_padding,
                on_speech_start=self._on_speech_start,
                on_speech_end=self._on_speech_end,
                on_valid_speech_end=self._on_valid_speech_end
            )
            logger.info(
                f"VAD config: threshold={vad_threshold}, "
                f"min_speech={vad_min_speech}ms, min_silence={vad_min_silence}ms, "
                f"padding={vad_padding}ms, barge_in_enabled={self.barge_in_enabled}, "
                f"command_queue={self._command_queue_enabled}, noise_gate={self._noise_gate_db}dB"
            )
            if not self.vad.load_model():
                logger.error("Failed to load VAD model")

            # Initialize Cartesia STT (primary — cloud).
            # `cartesia_mode` picks the transport: "batch" (HTTP POST) or
            # "websocket" (Ink 2 streaming with built-in turn detection).
            stt_config = self.config.get('stt', {})
            cartesia_mode = stt_config.get('cartesia_mode', 'batch')
            # Whisper fallback can be disabled via config when the user
            # wants Cartesia-only (e.g. when Whisper is too slow on the Pi).
            self._whisper_disabled = bool(stt_config.get('whisper_disabled', False))
            if stt_config.get('cartesia_enabled', True):
                if cartesia_mode == "websocket":
                    from rpi5.layer1_reflex.cartesia_stt_ws import CartesiaSTTWebSocket
                    self.ws_stt = CartesiaSTTWebSocket(
                        sample_rate=16000,
                        encoding=stt_config.get('encoding', 'pcm_s16le'),
                    )
                    if self.ws_stt.available:
                        logger.info("🌐 Primary STT: Cartesia Ink 2 (websocket, turn detection)")
                    else:
                        self.ws_stt = None
                        logger.warning("⚠️ Cartesia WebSocket STT unavailable — falling back to batch")
                # Always also instantiate batch (used as fallback if WS disconnects)
                self.cloud_stt = CartesiaSTT(
                    model=stt_config.get('cartesia_model', 'ink-whisper'),
                    language=stt_config.get('language', 'en'),
                )
                if self.cloud_stt.available:
                    if cartesia_mode == "websocket" and self.ws_stt:
                        logger.info("🔇 Fallback STT: Cartesia Ink (batch HTTP)")
                    else:
                        logger.info("🌐 Primary STT: Cartesia Ink (cloud, ~66ms)")
                else:
                    self.cloud_stt = None

            # Initialize Whisper (fallback — offline, ~8000ms on RPi5)
            whisper_model = self.config.get('whisper', {}).get('model_size', 'base')
            self.stt = WhisperSTT(model_size=whisper_model)
            if not self.stt.load_model():
                logger.error("Failed to load Whisper model")
            if self.cloud_stt:
                logger.info(f"🔇 Fallback STT: Whisper {whisper_model} (offline)")
            else:
                logger.info(f"🎤 STT: Whisper {whisper_model} (offline only — no Cartesia key)")

            logger.info("Voice Coordinator Initialized")
        except Exception as e:
            logger.error(f"Voice Coordinator Init Failed: {e}", exc_info=True)

    def start(self):
        """Start listening loop (VAD) and connect WebSocket STT if configured."""
        if not self.vad:
            logger.error("⚠️ VAD not initialized")
            return
        if not self.cloud_stt and not self.ws_stt and (not self.stt or not self.stt.model):
            logger.error("⚠️ No STT available (Cartesia disabled and Whisper model not loaded)")
            return

        if self.is_active:
            return

        logger.info("🎤 Starting Voice Coordinator (VAD Active)...")

        # Wire continuous audio forwarding to Gemini Live (every 32ms chunk)
        if (self.on_raw_audio or self.on_mic_audio or self.ws_stt) and not self._continuous_audio_wired:
            self.vad.on_audio_chunk = self._on_audio_chunk
            self._continuous_audio_wired = True
            logger.info("🔊 Continuous audio streaming enabled (Gemini Live + WS STT)")

        if self.vad.start_listening():
            self.is_active = True

        # WebSocket STT: open connection, register turn-end callback, and
        # launch an async drain task that pulls chunks from the thread-safe
        # queue and forwards them to the WS handler.
        if self.ws_stt and self.ws_stt.available and not self._ws_mode_active:
            try:
                self._ws_chunk_queue = _queue.Queue(maxsize=200)
                self.ws_stt.on_turn_end(self._on_ws_turn_end)
                # Capture the running loop so the audio thread can schedule work
                try:
                    self._ws_loop = asyncio.get_running_loop()
                except RuntimeError:
                    self._ws_loop = None
                self._ws_drain_task = asyncio.ensure_future(self._ws_drain_loop())
                self._ws_mode_active = True
                logger.info("🌐 Cartesia WebSocket STT: drain loop armed (queue=200 chunks)")
            except Exception as e:
                logger.error(f"❌ Failed to arm WebSocket STT: {e}")
                self._ws_mode_active = False

    def stop(self):
        """Stop listening and close WebSocket STT if active."""
        if self.vad and self.is_active:
            self.vad.stop_listening()
            self.is_active = False
            logger.info("🛑 Voice Coordinator Stopped")

        if self._ws_mode_active:
            self._ws_mode_active = False
            # Cancel drain task
            if self._ws_drain_task and not self._ws_drain_task.done():
                self._ws_drain_task.cancel()
            self._ws_drain_task = None
            # Close WS connection
            if self.ws_stt:
                try:
                    loop = self._ws_loop
                    if loop and loop.is_running():
                        asyncio.ensure_future(self.ws_stt.close())
                    else:
                        # No live loop — best effort
                        pass
                except Exception as e:
                    logger.warning(f"WS STT close error: {e}")
            self._ws_loop = None
            logger.info("🛑 Cartesia WebSocket STT closed")

    async def _ws_drain_loop(self):
        """Async task: pull PCM chunks from the queue and send to WS.

        Runs in the main asyncio loop. Bridges the audio thread
        (which calls `_on_audio_chunk` and pushes to `_ws_chunk_queue`)
        with the WS handler's async `send_audio_chunk`.
        """
        if not self.ws_stt:
            return
        try:
            await self.ws_stt.connect()
            logger.info("🌐 Cartesia WebSocket STT connected")
        except Exception as e:
            logger.error(f"❌ Cartesia WebSocket connect failed: {e}")
            return
        while self._ws_mode_active:
            try:
                pcm_bytes = await asyncio.to_thread(self._ws_chunk_queue.get, True, 0.1)
            except _queue.Empty:
                continue
            except Exception as e:
                logger.debug(f"WS drain queue error: {e}")
                continue
            try:
                await self.ws_stt.send_audio_chunk(pcm_bytes)
            except Exception as e:
                logger.warning(f"WS send_audio_chunk failed: {e}")
                break

    def _on_ws_turn_end(self, transcript: str):
        """Callback: WS STT produced a final transcript for a turn."""
        if not transcript or not transcript.strip():
            return
        # Skip if the same transcript was already produced by batch STT
        # (defensive: in WS mode we suppress batch, but keep this guard)
        text = transcript.strip()
        logger.info(f"🗣️ Transcribed (Cartesia WS): '{text}'")
        # Push to the live dashboard activity feed + STT history
        if self.system is not None and hasattr(self.system, "record_stt"):
            try:
                # WS transcripts don't expose a confidence score; use 0.0 placeholder
                self.system.record_stt(text, confidence=0.0)
            except Exception as e:
                logger.debug(f"record_stt (WS) error: {e}")
        if self.on_command_detected:
            try:
                # on_command_detected is the async dispatcher in main.py.
                # Schedule it on the captured event loop.
                if self._ws_loop and self._ws_loop.is_running():
                    self._ws_loop.call_soon_threadsafe(
                        self._dispatch_ws_async, text
                    )
                else:
                    # Fallback: fire the callback directly (may not be async-safe)
                    try:
                        self.on_command_detected(text)
                    except Exception as e:
                        logger.error(f"WS dispatch error: {e}")
            except Exception as e:
                logger.error(f"WS dispatch error: {e}")

    def _dispatch_ws_async(self, text: str):
        """Run the async on_command_detected from the event loop thread."""
        try:
            cb = self.on_command_detected
            if cb is None:
                return
            try:
                loop = asyncio.get_running_loop()
                asyncio.ensure_future(cb(text))
            except RuntimeError:
                pass
        except Exception as e:
            logger.error(f"WS async dispatch error: {e}")

    def _on_audio_chunk(self, chunk: np.ndarray):
        """Forward every VAD audio chunk to Gemini Live + Cartesia WebSocket STT."""
        # Noise gate: reject very quiet audio (distant speech, ambient noise)
        if not self._passes_noise_gate(chunk):
            # Still send silence to Gemini to maintain stream continuity
            if self.on_raw_audio is not None:
                try:
                    silence = b'\x00' * (len(chunk) * 2)
                    self.on_raw_audio(silence, 16000)
                except Exception:
                    pass
            # Also push silence to WS so it knows we're still connected
            if self._ws_mode_active and self._ws_chunk_queue is not None:
                try:
                    self._ws_chunk_queue.put_nowait(b'\x00' * (len(chunk) * 2))
                except _queue.Full:
                    pass
            return

        if self.on_mic_audio is not None:
            try:
                pcm_bytes = (chunk * 32767).astype(np.int16).tobytes()
                self.on_mic_audio(pcm_bytes, 16000)
            except Exception:
                pass  # Don't log per-chunk errors

        if self.on_raw_audio is not None:
            try:
                # During speaker playback, send silence instead of dropping audio.
                # Dropping creates silence→audio transitions that Gemini's server-side
                # auto-VAD interprets as speech onset → barge-in → session killed.
                if self.is_output_playing and self.is_output_playing():
                    silence = b'\x00' * (len(chunk) * 2)  # int16 = 2 bytes per sample
                    self.on_raw_audio(silence, 16000)
                else:
                    pcm_bytes = (chunk * 32767).astype(np.int16).tobytes()
                    self.on_raw_audio(pcm_bytes, 16000)
            except Exception:
                pass  # Don't log per-chunk errors

        # Forward to WebSocket STT (non-blocking; drop on full queue)
        if self._ws_mode_active and self._ws_chunk_queue is not None:
            try:
                pcm_bytes = (chunk * 32767).astype(np.int16).tobytes()
                self._ws_chunk_queue.put_nowait(pcm_bytes)
            except _queue.Full:
                # Drop — better than blocking the audio thread
                pass
            except Exception:
                pass

    def _on_speech_start(self):
        """Callback from VAD when speech starts."""
        output_active = bool(self.is_output_playing and self.is_output_playing())

        if output_active and not self.barge_in_enabled:
            if self._command_queue_enabled:
                # Buffer speech locally instead of discarding
                self._cmd_queue_active = True
                self._cmd_queue_buffer = None
                self._cmd_queue_speech_ms = 0.0
                self._cmd_queue_silence_ms = 0.0
                logger.info("📦 Command queue started (buffering speech during Gemini playback)")
            else:
                self._speech_started_during_output = False
                self._ignore_current_speech_segment = True
                logger.info("🔇 Barge-in disabled — ignoring speech detected during Gemini playback")
            return

        self._ignore_current_speech_segment = False
        self._speech_started_during_output = output_active
        if output_active and self.on_barge_in_callback:
            try:
                self.on_barge_in_callback()
            except Exception:
                pass
        if self.on_speech_start_callback:
            try:
                self.on_speech_start_callback()
            except Exception:
                pass

    def _on_valid_speech_end(self, _audio: np.ndarray):
        """Signal Gemini turn-end immediately for each valid VAD segment."""
        if self._ignore_current_speech_segment:
            return
        if self.on_speech_end_callback:
            try:
                self.on_speech_end_callback()
            except Exception:
                pass

    def _on_speech_end(self, audio: np.ndarray):
        """Callback from VAD when speech segment ends.

        Pipeline: Cartesia Ink (cloud, ~66ms) → Whisper (offline fallback, ~8s)
        Gemini Live audio path runs in parallel via continuous chunk streaming.
        If WebSocket STT is active, the transcript is delivered via its
        turn-end callback and we skip the batch path to avoid double-fire.
        """
        # Track VAD triggers for hall mode auto-detection
        self._update_hall_mode()

        # Handle command queue: if we were buffering during playback, evaluate now
        if self._cmd_queue_active:
            self._cmd_queue_active = False
            # Evaluate the buffered speech
            valid, audio_to_send = self._evaluate_command_queue()
            if valid and audio_to_send is not None:
                logger.info(f"📦 Command queue: valid speech buffered ({len(audio_to_send)} samples), sending to STT")
                self._transcribe_and_dispatch(audio_to_send)
            else:
                logger.info("📦 Command queue: rejected (noise or too short)")
            self._cmd_queue_buffer = None
            self._cmd_queue_speech_ms = 0.0
            self._cmd_queue_silence_ms = 0.0
            return

        # Suppress echo: discard speech captured while speaker was playing
        if self._ignore_current_speech_segment:
            self._ignore_current_speech_segment = False
            self._speech_started_during_output = False
            logger.info(
                f"🔇 Ignoring {len(audio)} sample speech segment during Gemini playback (barge-in disabled)"
            )
            return

        output_active = bool(self.is_output_playing and self.is_output_playing())
        speech_started_during_output = self._speech_started_during_output
        self._speech_started_during_output = False
        if output_active and not speech_started_during_output:
            logger.info(f"🔇 Suppressing {len(audio)} sample speech segment (speaker active)")
            return

        # WebSocket STT mode: VAD gives us the speech-boundary signal but the
        # transcript arrives via the WS turn-end callback. Skip batch here
        # to avoid double-dispatch (the WS queue has already received all
        # chunks of this segment).
        if self._ws_mode_active and self.ws_stt and self.ws_stt.is_connected:
            logger.debug("🌐 VAD segment ended — waiting for WS turn.end callback")
            return

        self._transcribe_and_dispatch(audio)

    def _evaluate_command_queue(self) -> tuple[bool, Optional[np.ndarray]]:
        """Evaluate buffered speech from command queue.

        Returns:
            (valid, audio): valid=True if buffer contains enough clean speech
        """
        if self._cmd_queue_buffer is None or len(self._cmd_queue_buffer) == 0:
            return False, None
        # Check minimum duration
        duration_ms = len(self._cmd_queue_buffer) / 16.0  # 16000 Hz = 16 samples/ms
        if duration_ms < self._command_queue_min_ms:
            logger.debug(f"📦 Command queue too short: {duration_ms:.0f}ms < {self._command_queue_min_ms}ms")
            return False, None
        # Check noise gate again on the whole buffer
        if not self._passes_noise_gate(self._cmd_queue_buffer):
            return False, None
        return True, self._cmd_queue_buffer

    def _transcribe_and_dispatch(self, audio: np.ndarray):
        """Send audio to STT and dispatch the transcribed text."""
        # Debounce: prevent API spam in noisy environments
        now = time.time()
        if self._debounce_seconds > 0 and (now - self._last_stt_time) < self._debounce_seconds:
            logger.info(f"🔇 Debounce: skipping STT ({self._debounce_seconds}s cooldown)")
            return
        self._last_stt_time = now

        logger.info(f"🎤 Speech segment detected ({len(audio)} samples), transcribing...")

        try:
            text = None

            # 1. Try Cartesia Ink (cloud) — ~66ms latency
            #    Returns str (possibly empty) on success, None on API failure
            if self.cloud_stt and self.cloud_stt.available:
                text = self.cloud_stt.transcribe(audio)
                if text:
                    logger.info(f"🗣️ Transcribed (Cartesia): '{text}'")
                elif text is not None:
                    # Empty string = API succeeded but no speech (don't waste 6s on Whisper)
                    logger.debug("🔇 Cartesia: no speech detected (empty response)")

            # 2. Fallback to local Whisper ONLY if Cartesia actually failed (None)
            #    Skip Whisper if config says so (e.g. user wants Cartesia only
            #    and would rather have no transcript than a 6s Whisper block).
            if text is None and self.stt:
                if not getattr(self, "_whisper_disabled", False):
                    if self.cloud_stt and self.cloud_stt.available:
                        logger.info("🔄 Cartesia API error, falling back to Whisper...")
                    text = self.stt.transcribe(audio)
                    if text:
                        logger.info(f"🗣️ Transcribed (Whisper): '{text}'")
                        # Push to the dashboard activity feed + STT history
                        # even when local Whisper produced the transcript
                        # (Cartesia path does this at line 588, Whisper path
                        # was silently dropping it before).
                        if self.system is not None and hasattr(self.system, "record_stt"):
                            try:
                                self.system.record_stt(text.strip(), confidence=0.0)
                            except Exception as e:
                                logger.debug(f"record_stt (whisper) error: {e}")
                else:
                    logger.debug("🔇 Whisper fallback disabled (config); dropping transcript")

            if text and len(text.strip()) > 1:
                # Push to the live dashboard activity feed + STT history.
                # Confidence isn't exposed by Cartesia/Whisper here, so use 0.0.
                if self.system is not None and hasattr(self.system, "record_stt"):
                    try:
                        self.system.record_stt(text.strip(), confidence=0.0)
                    except Exception as e:
                        logger.debug(f"record_stt (batch) error: {e}")
                # Send to main system (async)
                if self.on_command_detected:
                    try:
                        # Use thread-safe async execution
                        try:
                            loop = asyncio.get_running_loop()
                            asyncio.run_coroutine_threadsafe(self._dispatch_command(text), loop)
                        except RuntimeError:
                            asyncio.run(self._dispatch_command(text))
                    except Exception as e:
                        logger.error(f"❌ Error dispatching command: {e}")
            else:
                logger.debug("⚠️ Empty transcription or noise")

        except Exception as e:
            logger.error(f"❌ Transcription error: {e}")

    async def _dispatch_command(self, text: str):
        """Async dispatch wrapper"""
        try:
            # Check if callback is a coroutine
            if asyncio.iscoroutinefunction(self.on_command_detected):
                await self.on_command_detected(text)
            else:
                self.on_command_detected(text)
        except Exception as e:
            logger.error(f"❌ Error handling voice command: {e}")
