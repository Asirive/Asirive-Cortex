"""
Data Augmentation

Audio and video augmentation for training robustness.
Designed for first-person blind-assistance scenarios (MRT, street, mall).

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
import random
from typing import Optional

import numpy as np
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class AudioAugment:
    """
    Augment 1-second PCM audio chunks.
    """

    def __init__(
        self,
        reverb_prob: float = 0.3,
        noise_prob: float = 0.4,
        pitch_shift_prob: float = 0.2,
        noise_snrs: list = [5, 10, 15],  # dB
    ):
        self.reverb_prob = reverb_prob
        self.noise_prob = noise_prob
        self.pitch_shift_prob = pitch_shift_prob
        self.noise_snrs = noise_snrs

    def __call__(self, pcm: np.ndarray, sr: int = 16000) -> np.ndarray:
        """
        Args:
            pcm: int16 or float32 numpy array
            sr: sample rate
        Returns:
            augmented pcm
        """
        # TODO: implement with librosa / torchaudio
        # - Reverb: convolve with random IR
        # - Noise: mix with MRT/street noise samples at random SNR
        # - Pitch shift: librosa.effects.pitch_shift
        return pcm


class VideoAugment:
    """
    Augment 224x224 video frames.
    """

    def __init__(
        self,
        brightness: float = 0.2,
        contrast: float = 0.2,
        motion_blur_prob: float = 0.3,
        occlusion_prob: float = 0.1,
        temporal_jitter_ms: int = 200,
    ):
        self.brightness = brightness
        self.contrast = contrast
        self.motion_blur_prob = motion_blur_prob
        self.occlusion_prob = occlusion_prob
        self.temporal_jitter_ms = temporal_jitter_ms

    def __call__(self, frames: torch.Tensor) -> torch.Tensor:
        """
        Args:
            frames: [C, T, H, W] or [T, C, H, W]
        Returns:
            augmented frames
        """
        # TODO: implement with torchvision / kornia / opencv
        # - Random brightness/contrast
        # - Motion blur (simulated by averaging shifted frames)
        # - Occlusion (random black rectangles)
        # - Temporal jitter (shift frame alignment +/- 200ms)
        return frames


class TemporalAlignAugment:
    """
    Randomly misalign audio and video by +/- 200ms to teach robustness.
    """

    def __init__(self, max_shift_ms: int = 200):
        self.max_shift_ms = max_shift_ms

    def __call__(self, audio: np.ndarray, video: torch.Tensor, sr: int = 16000) -> tuple:
        shift_ms = random.randint(-self.max_shift_ms, self.max_shift_ms)
        shift_samples = int(shift_ms * sr / 1000)
        if shift_samples > 0:
            audio = np.pad(audio[shift_samples:], (0, shift_samples), mode="constant")
        elif shift_samples < 0:
            audio = np.pad(audio[:shift_samples], (-shift_samples, 0), mode="constant")
        return audio, video
