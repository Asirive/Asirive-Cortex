"""
Stage 5: Quantization-Aware Training

Insert fake INT8 quantization nodes and fine-tune at very low LR.
Prepare model for ONNX export and Hailo INT8 deployment.

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
from torch.ao.quantization import get_default_qat_qconfig, prepare_qat

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from training.models.cortex_local import CortexLocalModel
from training.data.instruct_loader import build_teacher_dataloader

logger = logging.getLogger(__name__)


def train_stage5(config: dict, checkpoint_path: str):
    """Run Stage 5 QAT."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Stage 5 QAT starting on {device}")

    model = CortexLocalModel(**config["model"]).to(device)
    model.load_state_dict(torch.load(checkpoint_path, map_location=device))
    model.train()

    # Prepare for QAT
    model.qconfig = get_default_qat_qconfig("fbgemm")
    # TODO: mark which layers to quantize (Conv, Linear, except Embedding)
    prepare_qat(model, inplace=True)
    logger.info("QAT preparation complete.")

    dataloader = build_teacher_dataloader(
        data_root=config["data"]["data_root"],
        batch_size=config["training"]["batch_size"] // 2,  # smaller batch for stability
        num_workers=config["training"]["num_workers"],
    )

    optimizer = AdamW(model.parameters(), lr=1e-5, weight_decay=1e-4)

    global_step = 0
    for epoch in range(config["training"]["max_epochs"]):
        for batch in dataloader:
            video = batch["video"].to(device)
            audio = batch["audio"].to(device)
            input_ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)

            frame = video[:, :, 0, :, :] if video.dim() == 5 else video
            conv_state, ssm_state = model.init_states(frame.size(0), device)
            outputs = model(
                video=frame,
                audio=audio,
                text_tokens=input_ids,
                conv_state=conv_state,
                ssm_state=ssm_state,
            )

            logits = outputs["logits"]
            loss = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                labels.reshape(-1),
                ignore_index=-100,
            )

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad()

            global_step += 1
            if global_step % 100 == 0:
                logger.info(f"Epoch {epoch} Step {global_step} Loss {loss.item():.4f}")

        ckpt_path = Path(config["training"]["output_dir"]) / f"ckpt_int8_epoch{epoch}.pt"
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), ckpt_path)

    # Convert to quantized model for export
    # model = convert(model, inplace=True)
    logger.info("Stage 5 complete. Ready for ONNX export.")


if __name__ == "__main__":
    import yaml
    with open("training/configs/stage5.yaml", "r") as f:
        cfg = yaml.safe_load(f)
    train_stage5(cfg, checkpoint_path="outputs/stage4/ckpt_cortex_final.pt")
