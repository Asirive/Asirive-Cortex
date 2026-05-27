"""
Stage 2: Video Extension

Extend pretraining to temporal video clips (4-8 frames) + ambient audio.
Unfreeze vision projector. Next-frame prediction as auxiliary loss.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import AdamW
from transformers import get_cosine_schedule_with_warmup

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from training.models.cortex_local import CortexLocalModel
from training.data.pretrain_loader import build_video_dataloader

logger = logging.getLogger(__name__)


def train_stage2(config: dict, checkpoint_path: str):
    """Run Stage 2 video extension training."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Stage 2 starting on {device}")

    model = CortexLocalModel(**config["model"]).to(device)
    model.load_state_dict(torch.load(checkpoint_path, map_location=device))

    # Unfreeze vision projector if needed
    for param in model.vision_tower.proj.parameters():
        param.requires_grad = True

    dataloader = build_video_dataloader(
        video_root=config["data"]["video_root"],
        caption_file=config["data"]["caption_file"],
        batch_size=config["training"]["batch_size"],
        num_workers=config["training"]["num_workers"],
    )

    optimizer = AdamW(model.parameters(), lr=1e-4, weight_decay=1e-4)
    total_steps = len(dataloader) * config["training"]["max_epochs"]
    scheduler = get_cosine_schedule_with_warmup(
        optimizer,
        num_warmup_steps=config["training"]["warmup_steps"],
        num_training_steps=total_steps,
    )

    model.train()
    global_step = 0
    for epoch in range(config["training"]["max_epochs"]):
        for batch in dataloader:
            video = batch["video"].to(device)  # [B, 3, T, H, W]
            caption_ids = batch["caption_ids"].to(device)

            # TODO: handle temporal video input (average frames or feed as sequence)
            # For now, take first frame as placeholder
            frame = video[:, :, 0, :, :]

            conv_state, ssm_state = model.init_states(frame.size(0), device)
            outputs = model(
                video=frame,
                text_tokens=caption_ids[:, :-1],
                conv_state=conv_state,
                ssm_state=ssm_state,
            )

            logits = outputs["logits"]
            labels = caption_ids[:, 1:]
            loss = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                labels.reshape(-1),
                ignore_index=-100,
            )

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()

            global_step += 1
            if global_step % 100 == 0:
                logger.info(f"Epoch {epoch} Step {global_step} Loss {loss.item():.4f}")

        ckpt_path = Path(config["training"]["output_dir"]) / f"ckpt_video_epoch{epoch}.pt"
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), ckpt_path)

    logger.info("Stage 2 complete.")


if __name__ == "__main__":
    import yaml
    with open("training/configs/stage2.yaml", "r") as f:
        cfg = yaml.safe_load(f)
    train_stage2(cfg, checkpoint_path="outputs/stage1/ckpt_pretrain_final.pt")
