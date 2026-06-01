"""
Navigation Architecture Validation

End-to-end training and validation of CortexLocal NAVIGATOR model.
Tests: raw pixels + audio + GPS -> navigation instructions, landmarks, safety.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import argparse
import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from training.models.cortex_local import CortexLocalModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CONFIG = {
    "vocab_size": 500,
    "d_model": 256,
    "n_layer": 6,
    "d_state": 64,
    "d_conv": 4,
    "expand": 2,
    "num_tools": 14,
    "num_nav_actions": 12,
    "num_safety_types": 12,
    "max_seq_len": 64,
    "lr": 1e-3,
    "weight_decay": 1e-4,
}

NAV_WORDS = [
    "<pad>", "<unk>", "<eos>", "walk", "forward", "turn", "left", "right",
    "step", "up", "down", "stop", "wait", "meter", "meters", "ahead",
    "on", "your", "the", "is", "a", "obstacle", "clear", "path",
    "doorway", "corner", "intersection", "crosswalk", "stairs", "elevator",
    "escalator", "ramp", "curb", "wall", "pole", "tree", "bench",
    "sign", "bus", "stop", "station", "entrance", "exit", "ticket",
    "gate", "platform", "track", "road", "street", "sidewalk", "alley",
    "building", "shop", "store", "restaurant", "cafe", "toilet", "lift",
    "crowd", "person", "people", "bicycle", "motorcycle", "car", "van",
    "truck", "noise", "quiet", "bright", "dark", "narrow", "wide",
    "slippery", "wet", "dry", "smooth", "rough", "uneven", "blocked",
    "open", "closed", "automatic", "manual", "push", "pull", "handle",
    "rail", "barrier", "fence", "planter", "trash", "box", "bag",
    "luggage", "trolley", "cart", "stroller", "wheelchair", "dog", "animal",
    "water", "fountain", "puddle", "hole", "crack", "edge", "drop",
    "slope", "hill", "bridge", "tunnel", "underpass", "overpass", "flyover",
    "traffic", "light", "signal", "zebra", "crossing", "junction", "roundabout",
    "fork", "merge", "lane", "cycle", "track", "trail", "pavement",
    "grass", "dirt", "gravel", "concrete", "tile", "wood", "metal",
    "glass", "plastic", "stone", "brick", "concrete", "marble", "carpet",
    "and", "or", "but", "then", "next", "now", "soon", "careful",
    "slowly", "quickly", "carefully", "gently", "firmly", "slightly", "sharply",
    "continue", "proceed", "follow", "keep", "stay", "move", "go", "come",
    "approach", "reach", "arrive", "find", "locate", "identify", "see",
    "hear", "feel", "notice", "watch", "check", "confirm", "verify",
]

while len(NAV_WORDS) < CONFIG["vocab_size"]:
    NAV_WORDS.append(f"tok_{len(NAV_WORDS)}")

WORD_TO_ID = {w: i for i, w in enumerate(NAV_WORDS)}

NAV_ACTION_NAMES = [
    "STOP", "FORWARD", "LEFT", "RIGHT", "LEFT_SMALL", "RIGHT_SMALL",
    "TURN_AROUND", "STEP_UP", "STEP_DOWN", "DUCK", "WAIT", "REORIENT",
]

SAFETY_NAMES = [
    "NONE", "CURB", "STAIR_UP", "STAIR_DOWN", "OBSTACLE_LOW",
    "OBSTACLE_HEAD", "OBSTACLE_SIDE", "VEHICLE_APPROACH", "CROWD",
    "DROP_OFF", "WET_FLOOR", "CONSTRUCTION",
]

# Scene types for synthetic data
SCENE_TYPES = [
    "clear_corridor", "doorway_ahead", "corner_left", "corner_right",
    "intersection_4way", "stair_up", "stair_down", "escalator_up",
    "escalator_down", "elevator_front", "crowded_area", "narrow_passage",
    "outdoor_sidewalk", "crosswalk", "bus_stop", "mrt_entrance",
    "shop_front", "ramp_up", "ramp_down", "obstacle_low",
    "obstacle_head", "wet_floor_area", "construction_zone", "dark_area",
]


class NavigationCorridorDataset(Dataset):
    """
    Synthetic first-person navigation corridor dataset.

    Each sample represents one 'step' in a navigation sequence:
    - Visual: corridor image with walls, obstacles, landmarks
    - Audio: ambient sounds (footsteps, traffic, echoes)
    - Target: navigation instruction text + action + safety
    """

    def __init__(self, num_samples: int = 5000, config: dict = None, seed: int = 42):
        self.config = config or CONFIG
        self.num_samples = num_samples
        random.seed(seed)
        np.random.seed(seed)

    def __len__(self):
        return self.num_samples

    def _tokenize(self, text: str) -> List[int]:
        words = text.lower().replace(",", "").replace(".", "").split()
        return [WORD_TO_ID.get(w, 1) for w in words]  # 1 = <unk>

    def _generate_scene(self, idx: int) -> Dict:
        """Generate one synthetic navigation scene."""
        scene_type = SCENE_TYPES[idx % len(SCENE_TYPES)]

        # Generate corridor image
        if "clear" in scene_type:
            # Empty corridor: gray floor, walls on sides
            video = self._make_corridor(obstacle=False, landmark=None)
            caption = "walk forward the path is clear"
            nav_action = "FORWARD"
            distance = 5.0
            safety = "NONE"
            landmark = None

        elif "doorway" in scene_type:
            # Doorway ahead
            video = self._make_corridor(obstacle=False, landmark="doorway")
            caption = "walk forward doorway ahead on your right"
            nav_action = "FORWARD"
            distance = 3.0
            safety = "NONE"
            landmark = "doorway"

        elif "corner_left" in scene_type:
            video = self._make_corridor(corner="left")
            caption = "turn left at the corner ahead"
            nav_action = "LEFT"
            distance = 2.0
            safety = "NONE"
            landmark = "corner"

        elif "corner_right" in scene_type:
            video = self._make_corridor(corner="right")
            caption = "turn right at the corner"
            nav_action = "RIGHT"
            distance = 2.0
            safety = "NONE"
            landmark = "corner"

        elif "stair_up" in scene_type:
            video = self._make_corridor(stair="up")
            caption = "step up stairs ahead"
            nav_action = "STEP_UP"
            distance = 1.5
            safety = "STAIR_UP"
            landmark = "stairs"

        elif "stair_down" in scene_type:
            video = self._make_corridor(stair="down")
            caption = "step down stairs ahead"
            nav_action = "STEP_DOWN"
            distance = 1.5
            safety = "STAIR_DOWN"
            landmark = "stairs"

        elif "crowded" in scene_type:
            video = self._make_corridor(crowd=True)
            caption = "crowd ahead slow down and stay left"
            nav_action = "LEFT_SMALL"
            distance = 4.0
            safety = "CROWD"
            landmark = None

        elif "obstacle_low" in scene_type:
            video = self._make_corridor(obstacle="low")
            caption = "obstacle low on the ground step over"
            nav_action = "STEP_UP"
            distance = 1.0
            safety = "OBSTACLE_LOW"
            landmark = None

        elif "obstacle_head" in scene_type:
            video = self._make_corridor(obstacle="head")
            caption = "duck low branch ahead"
            nav_action = "DUCK"
            distance = 1.5
            safety = "OBSTACLE_HEAD"
            landmark = None

        elif "crosswalk" in scene_type:
            video = self._make_corridor(landmark="crosswalk")
            caption = "crosswalk ahead wait for signal"
            nav_action = "WAIT"
            distance = 3.0
            safety = "NONE"
            landmark = "crosswalk"

        elif "bus_stop" in scene_type:
            video = self._make_corridor(landmark="bus_stop")
            caption = "bus stop ahead on your left"
            nav_action = "FORWARD"
            distance = 4.0
            safety = "NONE"
            landmark = "bus_stop"

        elif "wet" in scene_type:
            video = self._make_corridor(wet=True)
            caption = "wet floor ahead walk carefully"
            nav_action = "FORWARD"
            distance = 2.0
            safety = "WET_FLOOR"
            landmark = None

        else:
            # Default
            video = self._make_corridor()
            caption = "walk forward"
            nav_action = "FORWARD"
            distance = 5.0
            safety = "NONE"
            landmark = None

        return {
            "video": video,
            "caption": caption,
            "nav_action": nav_action,
            "distance": distance,
            "safety": safety,
            "landmark": landmark,
        }

    def _make_corridor(
        self,
        obstacle: Optional[str] = None,
        landmark: Optional[str] = None,
        corner: Optional[str] = None,
        stair: Optional[str] = None,
        crowd: bool = False,
        wet: bool = False,
    ) -> torch.Tensor:
        """Generate a synthetic corridor image [3, 224, 224]."""
        img = torch.zeros(3, 224, 224)

        # Floor (bottom half, gray)
        img[:, 112:, :] = 0.5

        # Walls (top half, darker gray)
        img[:, :112, :] = 0.3

        # Side walls (vertical lines)
        img[:, :, :20] = 0.2  # left wall
        img[:, :, 204:] = 0.2  # right wall

        # Add obstacle
        if obstacle == "low":
            img[:, 180:200, 80:144] = 0.8  # box on floor
        elif obstacle == "head":
            img[:, 20:60, 80:144] = 0.7  # branch from top

        # Add landmark
        if landmark == "doorway":
            img[:, 40:180, 160:200] = 0.9  # bright doorway on right
        elif landmark == "crosswalk":
            img[:, 180:200, 20:204] = 0.9  # white stripes on floor
            img[:, 200:210, 20:204] = 0.1
        elif landmark == "bus_stop":
            img[:, 60:180, 10:30] = 0.9  # pole/sign on left
        elif landmark == "stairs":
            for i in range(5):
                y = 180 - i * 15
                img[:, y:y+10, 20:204] = 0.6 + (i % 2) * 0.2

        # Add corner
        if corner == "left":
            img[:, 40:180, :100] = 0.4  # wall appears on left
        elif corner == "right":
            img[:, 40:180, 124:] = 0.4  # wall appears on right

        # Crowd = noise in center
        if crowd:
            img[:, 80:160, 60:164] += torch.randn(3, 80, 104) * 0.3
            img = torch.clamp(img, 0, 1)

        # Wet floor = reflective
        if wet:
            img[:, 160:, :] += 0.2
            img = torch.clamp(img, 0, 1)

        return img

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        scene = self._generate_scene(idx)

        # Video frame
        video = scene["video"]  # [3, 224, 224]

        # Dummy audio
        audio = torch.randn(1, 80, 100) * 0.1

        # Navigation instruction
        query = "what should i do"
        caption = scene["caption"]
        query_ids = self._tokenize(query)
        caption_ids = self._tokenize(caption)

        input_ids = query_ids + caption_ids[:-1] if len(caption_ids) > 1 else query_ids
        labels = [-100] * len(query_ids) + caption_ids

        input_ids = self._pad(input_ids, CONFIG["max_seq_len"], 0)
        labels = self._pad(labels, CONFIG["max_seq_len"], -100)

        # Nav action label
        nav_action_idx = NAV_ACTION_NAMES.index(scene["nav_action"])

        # Safety label
        safety_idx = SAFETY_NAMES.index(scene["safety"])

        # Landmark present + class
        landmark_present = 1.0 if scene["landmark"] else 0.0
        landmark_class_idx = 0  # simplified

        # Distance
        distance = scene["distance"]

        return {
            "video": video,
            "audio": audio,
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "nav_action": torch.tensor(nav_action_idx, dtype=torch.long),
            "safety": torch.tensor(safety_idx, dtype=torch.long),
            "landmark_present": torch.tensor(landmark_present, dtype=torch.float32),
            "landmark_class": torch.tensor(landmark_class_idx, dtype=torch.long),
            "distance": torch.tensor(distance, dtype=torch.float32),
            "caption_text": caption,
        }

    def _pad(self, seq: List[int], length: int, pad_val: int) -> List[int]:
        if len(seq) < length:
            seq = seq + [pad_val] * (length - len(seq))
        return seq[:length]


class NavTrainer:
    """Trainer for navigation model with multi-task losses."""

    def __init__(self, model, config, device):
        self.model = model.to(device)
        self.config = config
        self.device = device
        self.optimizer = torch.optim.AdamW(
            model.parameters(), lr=config["lr"], weight_decay=config["weight_decay"]
        )
        self.global_step = 0

    def train_step(self, batch: Dict[str, torch.Tensor]) -> Dict[str, float]:
        video = batch["video"].to(self.device)
        audio = batch["audio"].to(self.device)
        input_ids = batch["input_ids"].to(self.device)
        labels = batch["labels"].to(self.device)
        nav_action_target = batch["nav_action"].to(self.device)
        safety_target = batch["safety"].to(self.device)
        landmark_present_target = batch["landmark_present"].to(self.device)
        landmark_class_target = batch["landmark_class"].to(self.device)
        distance_target = batch["distance"].to(self.device)

        B = video.size(0)
        conv_state, ssm_state = self.model.init_states(B, self.device)

        outputs = self.model(
            video=video,
            audio=audio,
            text_tokens=input_ids,
            conv_state=conv_state,
            ssm_state=ssm_state,
        )

        # Text generation loss
        logits = outputs["logits"]
        text_len = input_ids.size(1)
        text_logits = logits[:, -text_len:, :]
        loss_text = F.cross_entropy(
            text_logits.reshape(-1, text_logits.size(-1)),
            labels.reshape(-1),
            ignore_index=-100,
        )

        # Nav action loss
        loss_nav = F.cross_entropy(outputs["nav_action_logits"], nav_action_target)

        # Safety loss
        loss_safety = F.cross_entropy(outputs["safety_logits"], safety_target)

        # Landmark losses
        loss_landmark_pres = F.binary_cross_entropy(
            outputs["landmark_present"], landmark_present_target
        )
        loss_landmark_cls = F.cross_entropy(
            outputs["landmark_class_logits"], landmark_class_target
        )

        # Distance regression loss (only when relevant)
        loss_distance = F.mse_loss(outputs["distance"], distance_target)

        # Combined loss
        total_loss = (
            loss_text
            + 2.0 * loss_nav
            + 1.0 * loss_safety
            + 0.5 * loss_landmark_pres
            + 0.5 * loss_landmark_cls
            + 0.3 * loss_distance
        )

        self.optimizer.zero_grad()
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
        self.optimizer.step()

        self.global_step += 1
        return {
            "total": total_loss.item(),
            "text": loss_text.item(),
            "nav": loss_nav.item(),
            "safety": loss_safety.item(),
            "landmark": (loss_landmark_pres + loss_landmark_cls).item(),
            "distance": loss_distance.item(),
        }

    def evaluate(self, dataloader, num_samples: int = 50) -> Dict[str, float]:
        """Evaluate navigation accuracy."""
        self.model.eval()
        nav_correct = 0
        safety_correct = 0
        landmark_correct = 0
        total = 0

        with torch.no_grad():
            for i, batch in enumerate(dataloader):
                if i >= num_samples:
                    break

                video = batch["video"].to(self.device)
                audio = batch["audio"].to(self.device)
                input_ids = batch["input_ids"].to(self.device)

                conv_state, ssm_state = self.model.init_states(1, self.device)
                outputs = self.model(
                    video=video,
                    audio=audio,
                    text_tokens=input_ids,
                    conv_state=conv_state,
                    ssm_state=ssm_state,
                )

                # Nav action accuracy
                pred_nav = outputs["nav_action_logits"].argmax(dim=-1)
                if pred_nav.item() == batch["nav_action"].item():
                    nav_correct += 1

                # Safety accuracy
                pred_safety = outputs["safety_logits"].argmax(dim=-1)
                if pred_safety.item() == batch["safety"].item():
                    safety_correct += 1

                # Landmark accuracy
                pred_landmark = (outputs["landmark_present"] > 0.5).float()
                if abs(pred_landmark.item() - batch["landmark_present"].item()) < 0.5:
                    landmark_correct += 1

                total += 1

        self.model.train()
        return {
            "nav_accuracy": nav_correct / total,
            "safety_accuracy": safety_correct / total,
            "landmark_accuracy": landmark_correct / total,
        }


def print_gpu_stats():
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1e6
        reserved = torch.cuda.memory_reserved() / 1e6
        print(f"  GPU: {allocated:.1f}MB alloc, {reserved:.1f}MB reserved")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--eval_every", type=int, default=200)
    parser.add_argument("--output_dir", type=str, default="outputs/validate_nav")
    parser.add_argument("--device", type=str, default="auto")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else torch.device(args.device)
    print(f"Device: {device}")
    if device.type == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    print("\n[1/4] Building navigation model...")
    model = CortexLocalModel(
        vocab_size=CONFIG["vocab_size"],
        d_model=CONFIG["d_model"],
        n_layer=CONFIG["n_layer"],
        d_state=CONFIG["d_state"],
        d_conv=CONFIG["d_conv"],
        expand=CONFIG["expand"],
        num_tools=CONFIG["num_tools"],
    )
    print(f"Parameters: {model.count_parameters():,}")
    print_gpu_stats()

    print(f"\n[2/4] Building navigation corridor dataset...")
    train_dataset = NavigationCorridorDataset(num_samples=3000, config=CONFIG)
    val_dataset = NavigationCorridorDataset(num_samples=300, config=CONFIG, seed=43)
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=1, shuffle=False)
    print(f"Train: {len(train_dataset)}, Val: {len(val_dataset)}")

    trainer = NavTrainer(model, CONFIG, device)

    print(f"\n[3/4] Training for {args.steps} steps...")
    print("=" * 60)
    losses = []
    step_times = []

    pbar = tqdm(total=args.steps, desc="Training")
    train_iter = iter(train_loader)

    start_time = time.time()
    while trainer.global_step < args.steps:
        try:
            batch = next(train_iter)
        except StopIteration:
            train_iter = iter(train_loader)
            batch = next(train_iter)

        t0 = time.time()
        metrics = trainer.train_step(batch)
        t1 = time.time()

        losses.append(metrics)
        step_times.append(t1 - t0)

        if trainer.global_step % 10 == 0:
            avg = {k: sum(m[k] for m in losses[-10:]) / 10 for k in losses[-1]}
            pbar.set_postfix({k: f"{v:.3f}" for k, v in avg.items()})
        pbar.update(1)

        if trainer.global_step % args.eval_every == 0:
            print(f"\n--- Eval @ step {trainer.global_step} ---")
            acc = trainer.evaluate(val_loader)
            print(f"  Nav accuracy: {acc['nav_accuracy']:.1%}")
            print(f"  Safety accuracy: {acc['safety_accuracy']:.1%}")
            print(f"  Landmark accuracy: {acc['landmark_accuracy']:.1%}")
            print_gpu_stats()

            # Show example
            sample = val_dataset[0]
            print(f"  Example: '{sample['caption_text']}'")
            print(f"  Action: {NAV_ACTION_NAMES[sample['nav_action']]}, Safety: {SAFETY_NAMES[sample['safety']]}")
            print("-" * 40)

    pbar.close()
    elapsed = time.time() - start_time

    print("\n" + "=" * 60)
    print("[4/4] Training complete!")
    print(f"Steps: {trainer.global_step}, Time: {elapsed/60:.1f}min")
    print(f"Avg step: {sum(step_times)/len(step_times)*1000:.1f}ms")

    final_acc = trainer.evaluate(val_loader, num_samples=100)
    print(f"\nFinal accuracy:")
    print(f"  Nav: {final_acc['nav_accuracy']:.1%}")
    print(f"  Safety: {final_acc['safety_accuracy']:.1%}")
    print(f"  Landmark: {final_acc['landmark_accuracy']:.1%}")
    print_gpu_stats()

    # Save
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"step": trainer.global_step, "model": model.state_dict()}, out_dir / "ckpt_final.pt")
    print(f"Checkpoint: {out_dir}/ckpt_final.pt")


if __name__ == "__main__":
    main()
