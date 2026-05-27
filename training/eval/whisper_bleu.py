"""
Whisper + BLEU Evaluation

Transcribe generated audio responses with Whisper and compute BLEU
against Gemini ground-truth transcripts.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from pathlib import Path
from typing import Dict, List

import numpy as np
import torch

# TODO: install evaluate, sacrebleu, openai-whisper
logger = logging.getLogger(__name__)


class WhisperBLEUEvaluator:
    """
    Evaluate local model responses against Gemini transcripts.
    """

    def __init__(self, whisper_model_size: str = "base"):
        self.whisper_model_size = whisper_model_size
        # TODO: load whisper model
        self.whisper = None

    def transcribe(self, audio_pcm: np.ndarray, sr: int = 24000) -> str:
        """Transcribe audio to text."""
        # TODO: whisper transcribe
        return ""

    def compute_bleu(self, predictions: List[str], references: List[str]) -> Dict[str, float]:
        """Compute corpus BLEU score."""
        # TODO: use sacrebleu or evaluate library
        return {"bleu": 0.0, "bleu_1": 0.0, "bleu_4": 0.0}

    def evaluate_batch(
        self,
        audio_samples: List[np.ndarray],
        gemini_transcripts: List[str],
    ) -> Dict[str, float]:
        """
        Transcribe all audio samples and compute BLEU vs Gemini.

        Returns:
            {"bleu": float, "avg_wer": float}
        """
        predictions = [self.transcribe(a) for a in audio_samples]
        bleu_scores = self.compute_bleu(predictions, gemini_transcripts)

        # TODO: compute Word Error Rate (WER) as well
        wer = 0.0

        logger.info(f"BLEU: {bleu_scores['bleu']:.3f}, WER: {wer:.3f}")
        return {**bleu_scores, "wer": wer}
