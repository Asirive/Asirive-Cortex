"""
CortexLocal Runtime

Offline multimodal copilot that plugs into rpi5/main.py as a Gemini Live fallback.
Handles audio/video ingestion, stateful inference, and audio output via Kokoro TTS.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
import threading
import time
from typing import Optional, Dict, Any

import numpy as np
import cv2

from rpi5.local_copilot.inference_engine import InferenceEngine
from rpi5.local_copilot.state_manager import StateManager
from rpi5.local_copilot.tool_adapter import ToolAdapter

logger = logging.getLogger(__name__)


class CortexLocal:
    """
    Local offline copilot runtime.

    Mirrors the integration pattern of HailoDepthEstimator in main.py:
    - Constructor takes shared device / audio player / managers
    - ingest_audio() and ingest_video() called from main loop hooks
    - generate_response() called from handle_voice_command() fallback branch
    """

    def __init__(
        self,
        config: dict,
        vdevice=None,  # Hailo shared VDevice (optional)
        audio_player=None,  # StreamingAudioPlayer instance
        memory_manager=None,
        conversation_manager=None,
        tts_router=None,
        tool_callback=None,
    ):
        self.config = config
        self.vdevice = vdevice
        self.audio_player = audio_player
        self.memory_manager = memory_manager
        self.conversation_manager = conversation_manager
        self.tts_router = tts_router
        self.tool_callback = tool_callback

        self.engine = InferenceEngine(config, vdevice=vdevice)
        self.state_mgr = StateManager(
            n_layer=config["model"]["n_layer"],
            d_model=config["model"]["d_model"],
            d_state=config["model"]["d_state"],
            d_conv=config["model"]["d_conv"],
        )
        self.tool_adapter = ToolAdapter(tool_callback=tool_callback)

        # Ring buffers
        self.audio_buffer = np.zeros(16000, dtype=np.int16)  # 1 sec @ 16kHz
        self.last_video_frame = None
        self.last_video_timestamp = 0.0

        self._lock = threading.Lock()
        self._active = False

    @property
    def is_available(self) -> bool:
        """Return True if the local model is loaded and ready."""
        return self.engine.is_loaded

    def start(self):
        """Initialize inference engine. Called from CortexSystem.start()."""
        self.engine.load()
        self._active = True
        logger.info("CortexLocal started.")

    def stop(self):
        """Release resources. Called from CortexSystem.stop()."""
        self._active = False
        self.engine.unload()
        logger.info("CortexLocal stopped.")

    def ingest_audio(self, pcm_chunk: np.ndarray):
        """
        Feed microphone PCM chunk.
        Called from _forward_audio_to_gemini() in main.py.

        Args:
            pcm_chunk: int16 numpy array, any length (typically 512 samples = 32ms)
        """
        with self._lock:
            self.audio_buffer = np.roll(self.audio_buffer, -len(pcm_chunk))
            self.audio_buffer[-len(pcm_chunk):] = pcm_chunk

    def ingest_video(self, frame: np.ndarray):
        """
        Feed latest camera frame.
        Called from _send_gemini_video() / main loop in main.py.

        Args:
            frame: BGR uint8 numpy array [H, W, 3]
        """
        with self._lock:
            # Preprocess: BGR -> RGB, resize, normalize
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            resized = cv2.resize(rgb, (224, 224))
            norm = (resized / 255.0 - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
            self.last_video_frame = norm.transpose(2, 0, 1).astype(np.float32)
            self.last_video_timestamp = time.time()

    def generate_response(self, query_text: str) -> Dict[str, Any]:
        """
        Run one autoregressive generation for a user query.
        Called from handle_voice_command() when Gemini is offline.

        Args:
            query_text: Whisper-transcribed user query
        Returns:
            {"text": str, "mode": str, "tool_call": Optional[dict]}
        """
        if not self._active:
            logger.warning("CortexLocal not active.")
            return {"text": "", "mode": "<silence>", "tool_call": None}

        with self._lock:
            video = self.last_video_frame
            audio = self._compute_mel(self.audio_buffer) if self.audio_buffer is not None else None

        # Build input tokens from query + conversation history
        input_ids = self.engine.tokenize(query_text)

        # Run inference step-by-step (autoregressive)
        generated_ids = []
        max_new_tokens = self.config.get("inference", {}).get("max_seq_len", 64)

        for _ in range(max_new_tokens):
            conv_state, ssm_state = self.state_mgr.get_states()
            outputs = self.engine.run(
                video=video,
                audio=audio,
                tokens=input_ids,
                conv_state=conv_state,
                ssm_state=ssm_state,
            )
            self.state_mgr.set_states(outputs["next_conv"], outputs["next_ssm"])

            # Sample next token
            next_token = self._sample_token(outputs["logits"])
            generated_ids.append(next_token)
            input_ids = np.append(input_ids, [next_token]).astype(np.int64)

            # Check mode head for early termination
            mode = self._decode_mode(outputs["mode_logits"])
            if mode == "<eos>":
                break

        text = self.engine.detokenize(generated_ids)
        mode = self._decode_mode(outputs["mode_logits"])
        tool_call = None
        if mode == "<tool>":
            tool_call = self.tool_adapter.decode(outputs["tool_logits"])

        return {"text": text, "mode": mode, "tool_call": tool_call}

    def proactive_narration(self) -> Optional[str]:
        """
        Generate ambient narration when no user query is active.
        Called from SceneChangeDetector when offline.

        Returns:
            Generated text if mode == <speak>, else None
        """
        # TODO: implement by prepending a system prompt like
        # "Describe what you see in one sentence."
        return None

    def reset_states(self):
        """Reset Mamba recurrent states (e.g., on mode switch or turn complete)."""
        self.state_mgr.reset()

    def _compute_mel(self, pcm: np.ndarray) -> np.ndarray:
        """Compute mel spectrogram from 1-second PCM buffer."""
        import librosa
        mel = librosa.feature.melspectrogram(
            y=pcm.astype(np.float32) / 32768.0,
            sr=16000,
            n_mels=80,
            n_fft=512,
            hop_length=160,
            win_length=400,
        )
        mel_db = librosa.power_to_db(mel, ref=np.max)
        mel_norm = np.clip(mel_db / 80.0, -1.0, 1.0)
        return mel_norm[np.newaxis, ...].astype(np.float32)  # [1, 80, 100]

    def _sample_token(self, logits: np.ndarray) -> int:
        """Greedy or top-k sampling from logits."""
        # TODO: add temperature, top-k, top-p
        return int(np.argmax(logits[-1]))

    def _decode_mode(self, mode_logits: np.ndarray) -> str:
        """Decode mode token from logits."""
        modes = ["<speak>", "<silence>", "<tool>", "<eos>"]
        idx = int(np.argmax(mode_logits))
        return modes[idx]
