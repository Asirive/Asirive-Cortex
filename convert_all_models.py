#!/usr/bin/env python3
"""
Unified Model Converter for Raspberry Pi 5
Converts ALL YOLO/YOLOE models to optimized formats at 256x256 resolution

Models:
- YOLO11n/s/m -> NCNN (ARM-optimized)
- YOLOE-11s/m-seg -> NCNN (text/visual prompts)
- YOLOE-11s/m-seg-pf -> ONNX (prompt-free, NCNN incompatible)

Usage:
    python convert_all_models.py --all           # Convert all models
    python convert_all_models.py --list          # List models
    python convert_all_models.py --onnx-only     # Convert only ONNX models
    python convert_all_models.py --ncnn-only     # Convert only NCNN models
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def get_short_temp_dir():
    """Get a temporary directory with short path to avoid Windows limits."""
    # Try to create temp in drive root to minimize path length
    drive = Path(__file__).anchor[:2]  # e.g., "C:"
    temp_base = Path(f"{drive}\\tmp_cortex")

    try:
        temp_base.mkdir(parents=True, exist_ok=True)
        return temp_base
    except Exception:
        # Fallback to system temp
        return Path(tempfile.gettempdir())


# All models to convert (256x256 resolution)
MODELS = {
    # === YOLO MODELS (NCNN) ===
    "yolo11n.pt": {
        "type": "yolo",
        "format": "ncnn",
        "imgsz": 256,
        "description": "YOLO11n - Nano"
    },
    "yolo11s.pt": {
        "type": "yolo",
        "format": "ncnn",
        "imgsz": 256,
        "description": "YOLO11s - Small"
    },
    "yolo11m.pt": {
        "type": "yolo",
        "format": "ncnn",
        "imgsz": 256,
        "description": "YOLO11m - Medium"
    },

    # === YOLOE MODELS (NCNN - text/visual prompts) ===
    "yoloe-11s-seg.pt": {
        "type": "yoloe",
        "format": "ncnn",
        "imgsz": 256,
        "description": "YOLOE-11s-seg"
    },
    "yoloe-11m-seg.pt": {
        "type": "yoloe",
        "format": "ncnn",
        "imgsz": 256,
        "description": "YOLOE-11m-seg"
    },

    # === YOLOE MODELS (ONNX - prompt-free) ===
    "yoloe-11s-seg-pf.pt": {
        "type": "yoloe",
        "format": "onnx",
        "imgsz": 256,
        "description": "YOLOE-11s-seg-pf (prompt-free)"
    },
    "yoloe-11m-seg-pf.pt": {
        "type": "yoloe",
        "format": "onnx",
        "imgsz": 256,
        "description": "YOLOE-11m-seg-pf (prompt-free)"
    },
}


def list_models():
    """List all available models."""
    print("\n" + "=" * 60)
    print("  Models for Conversion (256x256)")
    print("=" * 60)

    models_dir = Path("models")

    print("\nNCNN Format (ARM-optimized):")
    print("-" * 40)
    for model_file, info in MODELS.items():
        if info["format"] == "ncnn":
            model_path = models_dir / model_file
            status = "[OK]" if model_path.exists() else "[??]"
            print(f"  {status} {info['description']}")
            print(f"      {model_file} -> {model_file.replace('.pt', '_ncnn_model')}/")

    print("\nONNX Format (prompt-free YOLOE):")
    print("-" * 40)
    for model_file, info in MODELS.items():
        if info["format"] == "onnx":
            model_path = models_dir / model_file
            status = "[OK]" if model_path.exists() else "[??]"
            print(f"  {status} {info['description']}")
            print(f"      {model_file} -> {model_file.replace('.pt', '.onnx')}")


def convert_model(model_path: str, output_format: str, imgsz: int = 256):
    """Convert a single model to the specified format."""
    from ultralytics import YOLO

    model_path = Path(model_path)
    model_name = model_path.stem

    if output_format == "ncnn":
        output_dir = Path(f"models/{model_name}_ncnn_model")
    else:
        output_dir = Path(f"models/{model_name}.onnx")

    print(f"\n  Converting: {model_path.name}")
    print(f"  -> {output_dir.name}")

    # Load model
    model = YOLO(str(model_path))

    # Export
    if output_format == "ncnn":
        success = model.export(
            format="ncnn",
            imgsz=imgsz,
            simplify=True,
            workspace=4096,
        )
    else:  # onnx
        # ONNX export doesn't require onnxruntime-gpu
        success = model.export(
            format="onnx",
            imgsz=imgsz,
            simplify=True,
            dynamic=False,
            opset=12,
        )

    if success:
        if output_format == "ncnn":
            # Move NCNN files to expected location
            exported_dir = model_path.stem
            for f in Path(".").glob(f"{exported_dir}_ncnn_model/*"):
                if f.is_file():
                    dest = output_dir / f.name
                    if dest.exists():
                        dest.unlink()
                    f.rename(dest)
            if Path(exported_dir).exists():
                shutil.rmtree(exported_dir)
        else:
            # Rename ONNX file
            exported = Path(str(model_path).replace(".pt", ".onnx"))
            if exported.exists() and exported != output_dir:
                shutil.move(str(exported), str(output_dir))

        if output_dir.is_dir():
            total_size = sum(f.stat().st_size for f in output_dir.glob("*") if f.is_file())
        else:
            total_size = output_dir.stat().st_size
        print(f"  [OK] Success ({total_size / (1024 * 1024):.2f} MB)")
        return True
    else:
        print(f"  [FAIL] Failed")
        return False


def main():
    parser = argparse.ArgumentParser(description="Model converter for RPi5 (256x256)")
    parser.add_argument("--all", "-a", action="store_true", help="Convert all models")
    parser.add_argument("--list", "-l", action="store_true", help="List models")
    parser.add_argument("--imgsz", "-s", type=int, default=256, help="Image size (default: 256)")

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  Model Converter for Raspberry Pi 5")
    print("  Resolution: 256x256")
    print("=" * 60)

    models_dir = Path("models")
    if not models_dir.exists():
        print(f"\n✗ Models directory not found: {models_dir}")
        sys.exit(1)

    if args.list:
        list_models()
        return

    # Check ultralytics
    try:
        from ultralytics import YOLO
        print("\n✓ ultralytics available")
    except ImportError:
        print("\n✗ ultralytics not installed")
        print("  Install: pip install ultralytics")
        sys.exit(1)

    # Convert all models
    print(f"\nConverting all models...")
    results = []

    for model_file, info in MODELS.items():
        model_path = models_dir / model_file
        if not model_path.exists():
            print(f"\n  ? Skipping {model_file} (not found)")
            continue

        result = convert_model(str(model_path), info["format"], args.imgsz)
        results.append((model_file, result))

    # Summary
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    success = sum(1 for _, s in results if s)
    print(f"  Success: {success}/{len(results)}")

    print("\n  Output files:")
    for model_file, info in MODELS.items():
        if info["format"] == "ncnn":
            print(f"    models/{Path(model_file).stem}_ncnn_model/")
        else:
            print(f"    models/{Path(model_file).stem}.onnx")


if __name__ == "__main__":
    main()
