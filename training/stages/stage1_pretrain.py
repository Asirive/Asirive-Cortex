"""
Stage 1: Multimodal Pretraining

Train vision-language alignment on LAION-400M + WebVid-10M.
Vision tower frozen or partially frozen; Mamba core + text embedder trained.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
import os
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torch.optim import AdamW
from transformers import get_cosine_schedule_with_warmup

# Ensure project root in path
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from training.models.cortex_local import CortexLocalModel
from training.data.pretrain_loader import build_pretrain_dataloader

logger = logging.getLogger(__name__)


def train_stage1(config: dict):
    """
    Run Stage 1 pretraining.

    Args:
        config: dict with keys model, training, data, etc.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Stage 1 starting on {device}")

    # Build model
    model = CortexLocalModel(
        vocab_size=config["model"]["text_embedder"]["vocab_size"],
        d_model=config["model"]["fusion"]["d_model"],
        n_layer=config["model"]["fusion"]["n_layer"],
        d_state=config["model"]["fusion"]["d_state"],
        d_conv=config["model"]["fusion"]["d_conv"],
        expand=config["model"]["fusion"]["expand"],
        freeze_vision=config["model"].get("freeze_vision", True),
        freeze_audio=config["model"].get("freeze_audio", True),
    ).to(device)

    logger.info(f"Model parameters: {model.count_parameters():,}")

    # Build dataloader
    dataloader = build_pretrain_dataloader(
        manifest_path=config["data"]["manifest_path"],
        batch_size=config["training"]["batch_size"],
        num_workers=config["training"]["num_workers"],
    )

    # Optimizer + scheduler
    optimizer = AdamW(
        model.parameters(),
        lr=config["training"]["learning_rate"],
        weight_decay=config["training"]["weight_decay"],
    )
    total_steps = len(dataloader) * config["training"]["max_epochs"]
    scheduler = get_cosine_schedule_with_warmup(
        optimizer,
        num_warmup_steps=config["training"]["warmup_steps"],
        num_training_steps=total_steps,
    )

    # Training loop
    model.train()
    global_step = 0
    for epoch in range(config["training"]["max_epochs"]):
        for batch in dataloader:
            video = batch["video"].to(device)  # [B, 3, 224, 224]
            caption_ids = batch["caption_ids"].to(device)
            caption_mask = batch["caption_mask"].to(device)

            # Forward: video -> caption prediction
            conv_state, ssm_state = model.init_states(video.size(0), device)
            outputs = model(
                video=video,
                text_tokens=caption_ids[:, :-1],
                conv_state=conv_state,
                ssm_state=ssm_state,
            )

            logits = outputs["logits"]  # [B, L-1, vocab_size]
            labels = caption_ids[:, 1:]

            loss = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                labels.reshape(-1),
                ignore_index=-100,
            )

            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                model.parameters(), config["training"]["gradient_clip"]
            )
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()

            global_step += 1
            if global_step % 100 == 0:
                logger.info(f"Epoch {epoch} Step {global_step} Loss {loss.item():.4f}")

        # Save checkpoint
        ckpt_path = Path(config["training"]["output_dir"]) / f"ckpt_pretrain_epoch{epoch}.pt"
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), ckpt_path)
        logger.info(f"Saved checkpoint: {ckpt_path}")

    logger.info("Stage 1 complete.")


if __name__ == "__main__":
    import yaml
    with open("training/configs/stage1.yaml", "r") as f:
        cfg = yaml.safe_load(f)
    train_stage1(cfg)
