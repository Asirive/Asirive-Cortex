"""
Instruction Tuning Data Loader

Loads multimodal instruction-following datasets for Stage 3.
Supports LLaVA-Instruct, ShareGPT4V, VideoChatGPT, M3IT, MagicLM-Vision,
and Singlish/Malay/Mandarin code-switch corpus.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
import json
from pathlib import Path
from typing import Dict, List, Optional

import torch
from torch.utils.data import Dataset, DataLoader

logger = logging.getLogger(__name__)


class InstructionDataset(Dataset):
    """
    Multimodal instruction dataset.

    Each sample: {
        "image": str (path) or null,
        "video": str (path) or null,
        "conversations": [
            {"from": "human", "value": "..."},
            {"from": "gpt", "value": "..."}
        ],
        "mode": "<speak>" or "<silence>" or "<tool>",
        "tool_call": null or {...}
    }
    """

    def __init__(
        self,
        data_root: str,
        dataset_names: List[str],
        tokenizer=None,
        max_length: int = 512,
        image_size: int = 224,
        num_video_frames: int = 4,
    ):
        super().__init__()
        self.data_root = Path(data_root)
        self.dataset_names = dataset_names
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.image_size = image_size
        self.num_video_frames = num_video_frames

        self.samples: List[Dict] = []
        for name in dataset_names:
            self._load_dataset(name)

        logger.info(f"InstructionDataset: {len(self.samples)} samples from {dataset_names}")

    def _load_dataset(self, name: str):
        """Load a specific dataset by name."""
        # TODO: implement per-dataset loading logic
        # LLaVA-Instruct: JSON
        # ShareGPT4V: JSONL
        # VideoChatGPT: JSON
        # M3IT: JSON
        # MagicLM-Vision: JSON
        # Singlish corpus: custom TSV/JSONL
        logger.info(f"Loading dataset: {name}")
        pass

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        # TODO: load media, tokenize conversations, create labels
        return {
            "video": torch.randn(3, self.num_video_frames, self.image_size, self.image_size),
            "audio": torch.randn(1, 80, 100),
            "input_ids": torch.randint(0, 32000, (self.max_length,)),
            "labels": torch.randint(0, 32000, (self.max_length,)),
            "mode_label": torch.tensor(0),  # MODE_SPEAK
            "tool_label": torch.tensor(-1),  # no tool
        }


class TeacherDistillationDataset(Dataset):
    """
    Cortex + Gemini teacher distillation dataset for Stage 4.

    Each sample: {
        "video_path": str,
        "audio_path": str,
        "user_query": str,
        "gemini_response": str,
        "gemini_logprobs": List[float] or null,
        "tool_calls": List[dict] or null,
        "whisper_confidence": float
    }
    """

    def __init__(
        self,
        data_root: str,
        tokenizer=None,
        max_length: int = 512,
        min_whisper_confidence: float = 0.9,
        min_bleu: float = 0.6,
    ):
        super().__init__()
        self.data_root = Path(data_root)
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.min_whisper_confidence = min_whisper_confidence
        self.min_bleu = min_bleu

        self.samples: List[Dict] = []
        # TODO: load and filter samples
        logger.info(f"TeacherDistillationDataset initialized.")

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        # TODO: load media, tokenize, attach Gemini logprobs if available
        return {
            "video": torch.randn(3, 4, 224, 224),
            "audio": torch.randn(1, 80, 100),
            "input_ids": torch.randint(0, 32000, (self.max_length,)),
            "labels": torch.randint(0, 32000, (self.max_length,)),
            "gemini_logprobs": torch.randn(self.max_length, 32000),
            "mode_label": torch.tensor(0),
            "tool_label": torch.tensor(-1),
        }


def build_instruct_dataloader(
    data_root: str,
    dataset_names: List[str],
    batch_size: int = 128,
    num_workers: int = 16,
    tokenizer=None,
) -> DataLoader:
    """Build DataLoader for Stage 3 instruction tuning."""
    dataset = InstructionDataset(
        data_root=data_root,
        dataset_names=dataset_names,
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


def build_teacher_dataloader(
    data_root: str,
    batch_size: int = 128,
    num_workers: int = 16,
    tokenizer=None,
) -> DataLoader:
    """Build DataLoader for Stage 4 teacher distillation."""
    dataset = TeacherDistillationDataset(
        data_root=data_root,
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
