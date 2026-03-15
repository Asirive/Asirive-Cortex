"""
Cartesia Ink STT Handler - Cloud Speech-to-Text

Uses Cartesia's Ink-Whisper batch API for fast, accurate transcription.
66ms median latency vs ~8000ms for local Whisper on RPi5.
Falls back to local Whisper when offline.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import logging
import os
import io
import time
import wave
from typing import Optional

import numpy as np
import requests

logger = logging.getLogger(__name__)

# Cartesia STT API endpoint
CARTESIA_STT_URL = "https://api.cartesia.ai/stt"
CARTESIA_API_VERSION = "2025-04-16"


class CartesiaSTT:
    """
    Cloud speech-to-text using Cartesia Ink-Whisper batch API.

    Accepts numpy float32 audio arrays (16kHz) from VAD,
    converts to WAV, sends to Cartesia, returns text.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "ink-whisper",
        language: str = "en",
        sample_rate: int = 16000,
    ):
        self.api_key = api_key or os.getenv("CARTESIA_API_KEY")
        self.model = model
        self.language = language
        self.sample_rate = sample_rate
        self.available = bool(self.api_key)

        # Stats
        self.request_count = 0
        self.total_latency = 0.0
        self.error_count = 0
        self.consecutive_errors = 0
        self.max_consecutive_errors = 3

        if not self.available:
            logger.warning("No CARTESIA_API_KEY — Cartesia STT disabled")
        else:
            logger.info(f"✅ Cartesia Ink STT ready (model={model})")

    def _audio_to_wav_bytes(self, audio: np.ndarray) -> bytes:
        """Convert float32 numpy audio to WAV bytes for upload."""
        pcm = (audio * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    def transcribe(self, audio: np.ndarray, log_latency: bool = True) -> Optional[str]:
        """
        Transcribe audio using Cartesia Ink batch API.

        Args:
            audio: float32 numpy array at 16kHz
            log_latency: whether to log timing info

        Returns:
            Transcribed text or None on failure
        """
        if not self.available:
            return None

        # Circuit breaker: disable after too many consecutive failures
        if self.consecutive_errors >= self.max_consecutive_errors:
            logger.warning(
                f"⚡ Circuit breaker: Cartesia disabled after {self.consecutive_errors} "
                f"consecutive failures — using Whisper only until restart"
            )
            self.available = False
            return None

        wav_bytes = self._audio_to_wav_bytes(audio)
        audio_duration = len(audio) / self.sample_rate

        start = time.time()
        try:
            resp = requests.post(
                CARTESIA_STT_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Cartesia-Version": CARTESIA_API_VERSION,
                },
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={
                    "model": self.model,
                    "language": self.language,
                },
                timeout=15.0,
            )
            latency_ms = (time.time() - start) * 1000

            if resp.status_code != 200:
                self.error_count += 1
                self.consecutive_errors += 1
                logger.warning(
                    f"⚠️ Cartesia STT HTTP {resp.status_code}: {resp.text[:200]}"
                )
                return None

            data = resp.json()
            text = data.get("text", "").strip()

            self.request_count += 1
            self.total_latency += latency_ms
            self.consecutive_errors = 0

            if log_latency:
                logger.info(
                    f"🎤 Cartesia STT: '{text}' "
                    f"(latency: {latency_ms:.0f}ms for {audio_duration:.1f}s audio)"
                )

            # Return text (may be empty string — means API succeeded but no speech)
            # None is reserved for actual API failures (triggers Whisper fallback)
            return text

        except requests.Timeout:
            self.error_count += 1
            self.consecutive_errors += 1
            logger.warning(
                f"⚠️ Cartesia STT timeout ({(time.time() - start)*1000:.0f}ms)"
            )
            return None
        except Exception as e:
            self.error_count += 1
            self.consecutive_errors += 1
            logger.warning(f"⚠️ Cartesia STT error: {e}")
            return None
