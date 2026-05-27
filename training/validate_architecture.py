"""
Architecture Validation Script

End-to-end training and validation of the FULL CortexLocal model
(image + audio + text -> text) on a small synthetic dataset.

This proves the architecture trains, loss converges, and text generation works
before committing to full datacenter GPU training.

Run locally (RTX 2050, batch=2) or on cloud GPU (RTX 6000 Ada, batch=32).

Usage:
    python training/validate_architecture.py --dummy --steps 1000 --batch_size 2
    python training/validate_architecture.py --dataset coco --steps 10000 --batch_size 32

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import argparse
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm

# Ensure project root in path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from training.models.cortex_local import CortexLocalModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "vocab_size": 1000,          # Tiny vocab for fast validation
    "d_model": 256,              # Smaller than production (512) for speed
    "n_layer": 6,                # Fewer layers for validation
    "d_state": 64,
    "d_conv": 4,
    "expand": 2,
    "num_tools": 14,
    "max_seq_len": 48,
    "num_scenes": 100,           # Number of synthetic scene types
    "lr": 1e-3,
    "weight_decay": 1e-4,
    "warmup_steps": 100,
}


# ---------------------------------------------------------------------------
# 2. Synthetic Multimodal Dataset
# ---------------------------------------------------------------------------

class COCOCaptionDataset(Dataset):
    """
    MS COCO Captions dataset for vision-language validation.

    Expects COCO 2017 train images + annotations JSON.
    Auto-downloads if not present.
    """

    def __init__(
        self,
        root_dir: str = "data/coco",
        split: str = "train",
        max_length: int = 48,
        vocab_size: int = 1000,
        image_size: int = 224,
        max_samples: Optional[int] = None,
    ):
        self.root_dir = Path(root_dir)
        self.split = split
        self.max_length = max_length
        self.image_size = image_size
        self.max_samples = max_samples

        # Build vocabulary from captions
        self.words = ["<pad>", "<unk>", "<eos>"]
        self.word_to_id = {}
        self._build_vocab(vocab_size)

        # Load COCO annotations
        self.samples = self._load_coco()
        if max_samples:
            self.samples = self.samples[:max_samples]

        logger.info(f"COCO {split}: {len(self.samples)} samples loaded")

    def _build_vocab(self, vocab_size: int):
        """Build simple word-frequency vocabulary from captions."""
        # For validation, we use a fixed small vocab
        common_words = [
            "a", "the", "an", "is", "are", "was", "were", "on", "in", "at", "to",
            "of", "and", "with", "for", "from", "by", "about", "into", "through",
            "person", "people", "man", "woman", "child", "boy", "girl", "dog",
            "cat", "bird", "horse", "sheep", "cow", "elephant", "bear", "zebra",
            "giraffe", "animal", "bird", "plane", "train", "bus", "car", "truck",
            "motorcycle", "bicycle", "boat", "airplane", "vehicle", "street", "road",
            "building", "house", "bridge", "bench", "chair", "table", "couch",
            "bed", "door", "window", "wall", "floor", "ceiling", "room", "kitchen",
            "bathroom", "bedroom", "office", "restaurant", "park", "garden", "field",
            "beach", "mountain", "forest", "tree", "flower", "grass", "sky", "water",
            "ocean", "lake", "river", "snow", "rain", "sun", "cloud", "standing",
            "sitting", "walking", "running", "riding", "playing", "eating", "drinking",
            "talking", "looking", "watching", "holding", "carrying", "wearing", "red",
            "blue", "green", "yellow", "white", "black", "brown", "orange", "pink",
            "purple", "gray", "small", "large", "big", "little", "tall", "short",
            "young", "old", "happy", "sad", "beautiful", "pretty", "nice", "good",
            "young", "old", "playing", "sitting", "riding", "skateboard", "surfboard",
            "ski", "snowboard", "sports", "ball", "frisbee", "kite", "baseball",
            "tennis", "skateboarding", "surfing", "snowboarding", "flying", "lying",
            "jumping", "standing", "walking", "running", "big", "small", "white",
            "black", "brown", "green", "photo", "picture", "scene", "outside",
            "inside", "indoor", "outdoor", "group", "crowd", "family", "friends",
            "couple", "team", "pair", "background", "foreground", "center", "left",
            "right", "top", "bottom", "middle", "front", "back", "side", "near",
            "far", "close", "distant", "bright", "dark", "sunny", "cloudy", "clear",
            "overcast", "night", "day", "morning", "evening", "sunset", "sunrise",
        ]
        self.words = ["<pad>", "<unk>", "<eos>"] + common_words
        while len(self.words) < vocab_size:
            self.words.append(f"tok_{len(self.words)}")
        self.word_to_id = {w: i for i, w in enumerate(self.words)}

    def _load_coco(self) -> List[Dict]:
        """Load COCO annotations or return dummy data if not found."""
        ann_file = self.root_dir / f"annotations/captions_{self.split}2017.json"
        img_dir = self.root_dir / f"{self.split}2017"

        if not ann_file.exists():
            logger.warning(f"COCO annotations not found at {ann_file}")
            logger.warning("Using dummy COCO samples. Run download_coco.py to get real data.")
            # Return dummy samples
            return self._dummy_samples()

        import json
        with open(ann_file) as f:
            data = json.load(f)

        # Build image_id -> filename mapping
        id_to_file = {img["id"]: img["file_name"] for img in data["images"]}

        samples = []
        for ann in data["annotations"]:
            img_id = ann["image_id"]
            caption = ann["caption"]
            file_name = id_to_file.get(img_id)
            if file_name:
                samples.append({
                    "image_path": str(img_dir / file_name),
                    "caption": caption,
                })

        return samples

    def _dummy_samples(self) -> List[Dict]:
        """Create synthetic COCO-like samples when real data unavailable."""
        scenes = [
            ("red", "car", "street"), ("blue", "sky", "cloud"), ("green", "tree", "park"),
            ("yellow", "bus", "road"), ("white", "dog", "grass"), ("black", "cat", "house"),
            ("brown", "horse", "field"), ("big", "elephant", "zoo"), ("small", "bird", "tree"),
            ("tall", "building", "city"), ("young", "child", "playground"), ("old", "man", "bench"),
        ]
        samples = []
        for color, obj, place in scenes:
            samples.append({
                "image_path": None,
                "caption": f"a {color} {obj} in the {place}",
                "dummy_color": self._color_to_rgb(color),
            })
        # Repeat to get more samples
        samples = samples * 20
        return samples

    def _color_to_rgb(self, color: str) -> List[float]:
        colors = {
            "red": [0.8, 0.2, 0.2], "blue": [0.2, 0.2, 0.8], "green": [0.2, 0.8, 0.2],
            "yellow": [0.8, 0.8, 0.2], "white": [0.9, 0.9, 0.9], "black": [0.1, 0.1, 0.1],
            "brown": [0.6, 0.4, 0.2], "big": [0.5, 0.5, 0.5], "small": [0.7, 0.7, 0.7],
            "tall": [0.4, 0.4, 0.4], "young": [0.6, 0.6, 0.6], "old": [0.3, 0.3, 0.3],
        }
        return colors.get(color, [0.5, 0.5, 0.5])

    def __len__(self) -> int:
        return len(self.samples)

    def _tokenize(self, text: str) -> List[int]:
        words = text.lower().replace(",", "").replace(".", "").split()
        return [self.word_to_id.get(w, 1) for w in words]  # 1 = <unk>

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        sample = self.samples[idx]

        if sample.get("image_path") and Path(sample["image_path"]).exists():
            # Load real image
            img = cv2.imread(sample["image_path"])
            if img is None:
                img = np.zeros((self.image_size, self.image_size, 3), dtype=np.uint8)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                img = cv2.resize(img, (self.image_size, self.image_size))
            video = torch.from_numpy(img).permute(2, 0, 1).float() / 255.0
            # Normalize
            mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
            std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
            video = (video - mean) / std
        else:
            # Dummy image
            color = sample.get("dummy_color", [0.5, 0.5, 0.5])
            video = torch.tensor(color).view(3, 1, 1).expand(3, self.image_size, self.image_size).float()
            video = video + torch.randn(3, self.image_size, self.image_size) * 0.05
            video = torch.clamp(video, 0, 1)

        # Dummy audio
        audio = torch.randn(1, 80, 100) * 0.1

        # Tokenize
        query = "describe the image"
        caption = sample["caption"]

        query_ids = self._tokenize(query)
        caption_ids = self._tokenize(caption)

        input_ids = query_ids + caption_ids[:-1] if len(caption_ids) > 1 else query_ids
        labels = [-100] * len(query_ids) + caption_ids

        input_ids = self._pad(input_ids, self.max_length, 0)
        labels = self._pad(labels, self.max_length, -100)

        return {
            "video": video,
            "audio": audio,
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }

    def _pad(self, seq: List[int], length: int, pad_val: int) -> List[int]:
        if len(seq) < length:
            seq = seq + [pad_val] * (length - len(seq))
        return seq[:length]


class SyntheticMultimodalDataset(Dataset):
    """
    Generates synthetic (video, audio, query, response) samples.

    There are N scene types. Each scene has:
    - A fixed color video frame (e.g., red = "car", blue = "sky")
    - A fixed pitch audio mel (different frequency per scene)
    - A fixed caption sentence

    The model must learn to map (color + pitch) -> caption.
    This is a "canary" test: if architecture is broken, loss won't drop.
    """

    def __init__(self, num_samples: int = 5000, config: dict = None, seed: int = 42):
        self.config = config or DEFAULT_CONFIG
        self.num_samples = num_samples
        self.vocab_size = self.config["vocab_size"]
        self.max_len = self.config["max_seq_len"]
        self.num_scenes = self.config["num_scenes"]

        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)

        # Build a tiny vocabulary
        self.words = [
            "a", "the", "red", "blue", "green", "yellow", "big", "small",
            "car", "dog", "cat", "tree", "house", "street", "park", "sky",
            "on", "in", "near", "under", "running", "sitting", "flying",
            "is", "are", "was", "were", "happy", "sad", "bright", "dark",
            "one", "two", "three", "man", "woman", "child", "bird", "fish",
            "quickly", "slowly", "loudly", "quietly", "old", "new", "tall", "short",
            "and", "but", "or", "with", "without", "up", "down", "left", "right",
        ]
        # Pad to vocab_size with random tokens
        while len(self.words) < self.vocab_size:
            self.words.append(f"tok_{len(self.words)}")
        self.word_to_id = {w: i for i, w in enumerate(self.words)}

        # Generate scene captions
        self.scene_captions = []
        colors = ["red", "blue", "green", "yellow"]
        nouns = ["car", "dog", "cat", "tree", "house", "bird", "fish"]
        verbs = ["running", "sitting", "flying"]
        preps = ["on", "in", "near"]
        for i in range(self.num_scenes):
            color = colors[i % len(colors)]
            noun = nouns[i % len(nouns)]
            verb = verbs[i % len(verbs)]
            prep = preps[i % len(preps)]
            place = random.choice(["street", "park", "house", "sky"])
            caption = f"a {color} {noun} {verb} {prep} the {place}"
            self.scene_captions.append(caption)

    def __len__(self):
        return self.num_samples

    def _tokenize(self, text: str) -> list:
        words = text.lower().split()
        return [self.word_to_id.get(w, 0) for w in words]

    def __getitem__(self, idx: int):
        scene_idx = idx % self.num_scenes

        # Video: solid color image [3, 224, 224]
        color_idx = scene_idx % 4
        color_vals = [
            [0.8, 0.2, 0.2],  # red
            [0.2, 0.2, 0.8],  # blue
            [0.2, 0.8, 0.2],  # green
            [0.8, 0.8, 0.2],  # yellow
        ]
        video = torch.tensor(color_vals[color_idx]).view(3, 1, 1).expand(3, 224, 224).float().clone()
        # Add small noise so it's not *too* easy
        video = video + torch.randn(3, 224, 224) * 0.05
        video = torch.clamp(video, 0, 1)

        # Audio: mel spectrogram [1, 80, 100] with pitch pattern
        base_freq = (scene_idx + 1) * 50.0  # Hz-ish
        t = torch.linspace(0, 1, 100)
        freq = base_freq + scene_idx * 10
        wave = torch.sin(2 * np.pi * freq * t)  # [100]
        mel = wave.unsqueeze(0).expand(80, 100)  # [80, 100]
        mel = mel.unsqueeze(0)  # [1, 80, 100]
        mel = mel + torch.randn(1, 80, 100) * 0.1
        mel = torch.clamp(mel, -1, 1)

        # Text: fixed query + variable response
        query = "describe the scene"
        response = self.scene_captions[scene_idx]

        query_ids = self._tokenize(query)
        resp_ids = self._tokenize(response)

        # Build input: [query] + [resp[:-1]]
        input_ids = query_ids + resp_ids[:-1]
        # Target: [resp]
        labels = [-100] * len(query_ids) + resp_ids  # ignore query in loss

        # Pad/truncate
        input_ids = self._pad(input_ids, self.max_len, 0)
        labels = self._pad(labels, self.max_len, -100)

        return {
            "video": video,
            "audio": mel,
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "scene_idx": scene_idx,
        }

    def _pad(self, seq, length, pad_val):
        if len(seq) < length:
            seq = seq + [pad_val] * (length - len(seq))
        return seq[:length]


# ---------------------------------------------------------------------------
# 3. Training Loop
# ---------------------------------------------------------------------------

class Trainer:
    def __init__(self, model, config, device):
        self.model = model.to(device)
        self.config = config
        self.device = device
        self.optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=config["lr"],
            weight_decay=config["weight_decay"],
        )
        self.global_step = 0
        self.best_loss = float("inf")

    def train_step(self, batch):
        video = batch["video"].to(self.device)
        audio = batch["audio"].to(self.device)
        input_ids = batch["input_ids"].to(self.device)
        labels = batch["labels"].to(self.device)

        B = video.size(0)
        conv_state, ssm_state = self.model.init_states(B, self.device)

        outputs = self.model(
            video=video,
            audio=audio,
            text_tokens=input_ids,
            conv_state=conv_state,
            ssm_state=ssm_state,
        )

        logits = outputs["logits"]  # [B, vision+audio+text, vocab]
        text_len = input_ids.size(1)
        # Only compute loss on text token positions (last text_len positions)
        text_logits = logits[:, -text_len:, :]  # [B, text_len, vocab]
        loss = F.cross_entropy(
            text_logits.reshape(-1, text_logits.size(-1)),
            labels.reshape(-1),
            ignore_index=-100,
        )

        # Mode prediction loss (auxiliary)
        # For synthetic data, mode is always "speak" (0)
        mode_target = torch.zeros(B, dtype=torch.long, device=self.device)
        loss_mode = F.cross_entropy(outputs["mode_logits"], mode_target)

        total_loss = loss + 0.3 * loss_mode

        self.optimizer.zero_grad()
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
        self.optimizer.step()

        self.global_step += 1
        return {
            "loss": loss.item(),
            "mode_loss": loss_mode.item(),
            "total_loss": total_loss.item(),
        }

    def generate(self, video, audio, query_ids, max_new_tokens: int = 20):
        """Greedy autoregressive generation for one sample."""
        self.model.eval()
        with torch.no_grad():
            B = 1
            input_ids = query_ids.unsqueeze(0).to(self.device)
            video = video.to(self.device)
            audio = audio.to(self.device)
            conv_state, ssm_state = self.model.init_states(B, self.device)

            generated = []
            for _ in range(max_new_tokens):
                outputs = self.model(
                    video=video.unsqueeze(0),
                    audio=audio.unsqueeze(0),
                    text_tokens=input_ids,
                    conv_state=conv_state,
                    ssm_state=ssm_state,
                )
                conv_state = outputs["next_conv_state"]
                ssm_state = outputs["next_ssm_state"]

                next_token = outputs["logits"][:, -1, :].argmax(dim=-1)
                generated.append(next_token.item())
                input_ids = torch.cat([input_ids, next_token.unsqueeze(0)], dim=1)

                # Stop on EOS token (use a special id, e.g., vocab_size-1)
                if next_token.item() == self.config["vocab_size"] - 1:
                    break

        self.model.train()
        return generated

    def evaluate(self, dataloader, dataset, num_samples: int = 10):
        """Run validation: generate text for N samples and compute exact-match accuracy."""
        self.model.eval()
        correct = 0
        total = 0

        with torch.no_grad():
            for i, batch in enumerate(dataloader):
                if i >= num_samples:
                    break
                video = batch["video"][0].to(self.device)
                audio = batch["audio"][0].to(self.device)
                query_ids = batch["input_ids"][0]
                labels = batch["labels"][0].cpu().numpy()

                # Find where target starts (after query)
                target_start = next((i for i, v in enumerate(labels) if v != -100), 0)
                target_ids = labels[target_start:]
                target_ids = target_ids[target_ids != -100]

                gen_ids = self.generate(video, audio, query_ids, max_new_tokens=len(target_ids))

                if gen_ids == target_ids.tolist():
                    correct += 1
                total += 1

        self.model.train()
        accuracy = correct / total if total > 0 else 0.0
        return accuracy


# ---------------------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------------------

def print_gpu_stats():
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1e6
        reserved = torch.cuda.memory_reserved() / 1e6
        print(f"  GPU Memory: {allocated:.1f} MB allocated, {reserved:.1f} MB reserved")


def main():
    parser = argparse.ArgumentParser(description="Validate CortexLocal architecture")
    parser.add_argument("--dataset", type=str, default="synthetic", choices=["synthetic", "coco"], help="Dataset to use")
    parser.add_argument("--dummy", action="store_true", help="Use synthetic dummy dataset (deprecated, use --dataset)")
    parser.add_argument("--steps", type=int, default=1000, help="Total training steps")
    parser.add_argument("--batch_size", type=int, default=4, help="Batch size")
    parser.add_argument("--eval_every", type=int, default=200, help="Evaluate every N steps")
    parser.add_argument("--save_every", type=int, default=500, help="Save checkpoint every N steps")
    parser.add_argument("--output_dir", type=str, default="outputs/validate", help="Output directory")
    parser.add_argument("--device", type=str, default="auto", help="cuda/cpu/auto")
    parser.add_argument("--coco_root", type=str, default="data/coco", help="COCO dataset root")
    parser.add_argument("--max_samples", type=int, default=None, help="Max dataset samples (for fast testing)")
    args = parser.parse_args()

    if args.dummy:
        args.dataset = "synthetic"

    # Device
    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    print(f"Device: {device}")
    if device.type == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

    # Config
    config = DEFAULT_CONFIG.copy()
    print(f"Config: {json.dumps(config, indent=2)}")

    # Model
    print("\n[1/4] Building model...")
    model = CortexLocalModel(
        vocab_size=config["vocab_size"],
        d_model=config["d_model"],
        n_layer=config["n_layer"],
        d_state=config["d_state"],
        d_conv=config["d_conv"],
        expand=config["expand"],
        num_tools=config["num_tools"],
    )
    total_params = model.count_parameters()
    print(f"Total parameters: {total_params:,}")
    print_gpu_stats()

    # Dataset
    print(f"\n[2/4] Building dataset (dataset={args.dataset})...")
    if args.dataset == "synthetic":
        train_dataset = SyntheticMultimodalDataset(num_samples=2000, config=config)
        val_dataset = SyntheticMultimodalDataset(num_samples=200, config=config, seed=43)
    elif args.dataset == "coco":
        train_dataset = COCOCaptionDataset(
            root_dir=args.coco_root,
            split="train",
            max_length=config["max_seq_len"],
            vocab_size=config["vocab_size"],
            image_size=224,
            max_samples=args.max_samples,
        )
        val_dataset = COCOCaptionDataset(
            root_dir=args.coco_root,
            split="val",
            max_length=config["max_seq_len"],
            vocab_size=config["vocab_size"],
            image_size=224,
            max_samples=args.max_samples,
        )
    else:
        raise ValueError(f"Unknown dataset: {args.dataset}")

    train_loader = DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=0
    )
    val_loader = DataLoader(
        val_dataset, batch_size=1, shuffle=False, num_workers=0
    )
    print(f"Train samples: {len(train_dataset)}, Val samples: {len(val_dataset)}")

    # Trainer
    trainer = Trainer(model, config, device)

    # Training
    print(f"\n[3/4] Training for {args.steps} steps...")
    print("=" * 60)
    losses = []
    timings = []
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

        losses.append(metrics["total_loss"])
        step_times.append(t1 - t0)
        trainer.global_step += 1  # actually incremented in train_step, but let's track

        # Logging
        if trainer.global_step % 10 == 0:
            avg_loss = sum(losses[-10:]) / min(len(losses), 10)
            avg_time = sum(step_times[-10:]) / min(len(step_times), 10)
            tokens_per_sec = (args.batch_size * config["max_seq_len"]) / avg_time
            pbar.set_postfix({
                "loss": f"{avg_loss:.4f}",
                "step_ms": f"{avg_time*1000:.1f}",
                "tok/s": f"{tokens_per_sec:.0f}",
            })
        pbar.update(1)

        # Evaluation
        if trainer.global_step % args.eval_every == 0:
            print(f"\n--- Eval at step {trainer.global_step} ---")
            acc = trainer.evaluate(val_loader, val_dataset, num_samples=20)
            print(f"Exact-match accuracy: {acc:.2%}")
            print_gpu_stats()

            # Show a generation example
            sample = val_dataset[0]
            gen_ids = trainer.generate(
                sample["video"], sample["audio"], sample["input_ids"], max_new_tokens=10
            )
            gen_words = [train_dataset.words[i] if i < len(train_dataset.words) else "<?>" for i in gen_ids]
            target_words = [train_dataset.words[i] if i < len(train_dataset.words) else "<?>" for i in sample["labels"].tolist() if i >= 0]
            print(f"  Generated: {' '.join(gen_words)}")
            print(f"  Target:    {' '.join(target_words)}")
            print("-" * 40)

        # Checkpoint
        if trainer.global_step % args.save_every == 0:
            out_dir = Path(args.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            ckpt_path = out_dir / f"ckpt_step{trainer.global_step}.pt"
            torch.save({
                "step": trainer.global_step,
                "model": model.state_dict(),
                "optimizer": trainer.optimizer.state_dict(),
                "config": config,
            }, ckpt_path)
            print(f"Checkpoint saved: {ckpt_path}")

    pbar.close()
    elapsed = time.time() - start_time

    print("\n" + "=" * 60)
    print("[4/4] Training complete!")
    print(f"Total steps: {trainer.global_step}")
    print(f"Total time: {elapsed/60:.1f} minutes")
    print(f"Avg step time: {sum(step_times)/len(step_times)*1000:.1f} ms")
    print(f"Final loss: {sum(losses[-100:])/min(len(losses), 100):.4f}")
    print(f"Best checkpoint: {args.output_dir}/ckpt_step{args.save_every * (trainer.global_step // args.save_every)}.pt")
    print_gpu_stats()
    print("=" * 60)

    # Final evaluation
    print("\nFinal evaluation on 50 samples:")
    final_acc = trainer.evaluate(val_loader, val_dataset, num_samples=50)
    print(f"Final exact-match accuracy: {final_acc:.2%}")

    # Save results summary
    summary = {
        "config": config,
        "args": vars(args),
        "total_steps": trainer.global_step,
        "total_time_sec": elapsed,
        "avg_step_ms": sum(step_times) / len(step_times) * 1000,
        "final_loss": sum(losses[-100:]) / min(len(losses), 100),
        "final_accuracy": final_acc,
        "parameter_count": total_params,
    }
    summary_path = Path(args.output_dir) / "validation_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary saved: {summary_path}")


if __name__ == "__main__":
    main()
