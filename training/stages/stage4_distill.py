"""
Stage 4: Teacher Distillation

Fine-tune on Cortex + Gemini captured data.
Match Gemini's text responses, mode decisions, and tool calls.

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
from training.data.instruct_loader import build_teacher_dataloader

logger = logging.getLogger(__name__)


def train_stage4(config: dict, checkpoint_path: str):
    """Run Stage 4 teacher distillation."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Stage 4 starting on {device}")

    model = CortexLocalModel(**config["model"]).to(device)
    model.load_state_dict(torch.load(checkpoint_path, map_location=device))

    dataloader = build_teacher_dataloader(
        data_root=config["data"]["data_root"],
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
            video = batch["video"].to(device)
            audio = batch["audio"].to(device)
            input_ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)
            gemini_logprobs = batch.get("gemini_logprobs")
            mode_label = batch["mode_label"].to(device)
            tool_label = batch["tool_label"].to(device)

            frame = video[:, :, 0, :, :] if video.dim() == 5 else video

            conv_state, ssm_state = model.init_states(frame.size(0), device)
            outputs = model(
                video=frame,
                audio=audio,
                text_tokens=input_ids,
                conv_state=conv_state,
                ssm_state=ssm_state,
            )

            # LM loss
            logits = outputs["logits"]
            loss_lm = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                labels.reshape(-1),
                ignore_index=-100,
            )

            # KL distillation vs Gemini logprobs (if available)
            loss_kl = torch.tensor(0.0, device=device)
            if gemini_logprobs is not None:
                gemini_logprobs = gemini_logprobs.to(device)
                # TODO: compute KL(P_gemini || P_local)
                pass

            # Mode + tool losses
            loss_mode = F.cross_entropy(outputs["mode_logits"], mode_label)
            tool_mask = (mode_label == 2)
            loss_tool = (
                F.cross_entropy(outputs["tool_logits"][tool_mask], tool_label[tool_mask])
                if tool_mask.any() and (tool_label[tool_mask] >= 0).any()
                else torch.tensor(0.0, device=device)
            )

            loss = loss_lm + 0.3 * loss_kl + 0.5 * loss_mode + 0.5 * loss_tool

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()

            global_step += 1
            if global_step % 100 == 0:
                logger.info(f"Epoch {epoch} Step {global_step} Loss {loss.item():.4f}")

        ckpt_path = Path(config["training"]["output_dir"]) / f"ckpt_cortex_epoch{epoch}.pt"
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), ckpt_path)

    logger.info("Stage 4 complete.")


if __name__ == "__main__":
    import yaml
    with open("training/configs/stage4.yaml", "r") as f:
        cfg = yaml.safe_load(f)
    train_stage4(cfg, checkpoint_path="outputs/stage3/ckpt_instruct_final.pt")
