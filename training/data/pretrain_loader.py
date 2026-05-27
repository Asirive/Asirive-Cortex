"""
Pretraining Data Loader

Loads image-caption and video-caption datasets for Stage 1 and Stage 2.
Supports LAION-400M, WebVid-10M, Ego4D, and HowTo100M.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
import random
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader, IterableDataset

logger = logging.getLogger(__name__)


class ImageCaptionDataset(Dataset):
    """
    Simple image-caption dataset for Stage 1 pretraining.

    Expects a JSONL or TSV with columns: image_path, caption
    """

    def __init__(
        self,
        manifest_path: str,
        image_size: int = 224,
        max_length: int = 64,
        tokenizer=None,
    ):
        super().__init__()
        self.manifest_path = Path(manifest_path)
        self.image_size = image_size
        self.max_length = max_length
        self.tokenizer = tokenizer

        # TODO: load manifest lines
        self.samples: List[Dict] = []
        logger.info(f"ImageCaptionDataset initialized with {len(self.samples)} samples.")

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        # TODO: load image, preprocess, tokenize caption
        return {
            "video": torch.randn(3, self.image_size, self.image_size),  # placeholder
            "caption_ids": torch.randint(0, 32000, (self.max_length,)),
            "caption_mask": torch.ones(self.max_length),
        }


class VideoCaptionIterableDataset(IterableDataset):
    """
    Streaming video-caption dataset for Stage 2.

    Supports WebVid, Ego4D, HowTo100M.
    Yields clips of N frames + caption.
    """

    def __init__(
        self,
        video_root: str,
        caption_file: str,
        num_frames: int = 4,
        frame_size: int = 224,
        fps: int = 2,
        tokenizer=None,
    ):
        super().__init__()
        self.video_root = Path(video_root)
        self.num_frames = num_frames
        self.frame_size = frame_size
        self.fps = fps
        self.tokenizer = tokenizer

        # TODO: load caption annotations
        self.samples: List[Dict] = []
        logger.info(f"VideoCaptionIterableDataset initialized.")

    def __iter__(self):
        worker_info = torch.utils.data.get_worker_info()
        if worker_info is None:
            samples = self.samples
        else:
            # Shard across workers
            per_worker = len(self.samples) // worker_info.num_workers
            start = worker_info.id * per_worker
            end = start + per_worker if worker_info.id < worker_info.num_workers - 1 else len(self.samples)
            samples = self.samples[start:end]

        for sample in samples:
            # TODO: decode video frames, sample N frames at target FPS
            yield {
                "video": torch.randn(3, self.num_frames, self.frame_size, self.frame_size),
                "caption_ids": torch.randint(0, 32000, (64,)),
                "caption_mask": torch.ones(64),
            }


def build_pretrain_dataloader(
    manifest_path: str,
    batch_size: int = 256,
    num_workers: int = 16,
    tokenizer=None,
) -> DataLoader:
    """Build DataLoader for Stage 1 image pretraining."""
    dataset = ImageCaptionDataset(
        manifest_path=manifest_path,
        tokenizer=tokenizer,
    )
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=True,
        drop_last=True,
    )


def build_video_dataloader(
    video_root: str,
    caption_file: str,
    batch_size: int = 256,
    num_workers: int = 16,
    tokenizer=None,
) -> DataLoader:
    """Build DataLoader for Stage 2 video extension."""
    dataset = VideoCaptionIterableDataset(
        video_root=video_root,
        caption_file=caption_file,
        tokenizer=tokenizer,
    )
    return DataLoader(
        dataset,
        batch_size=batch_size,
        num_workers=num_workers,
        pin_memory=True,
        drop_last=True,
    )
