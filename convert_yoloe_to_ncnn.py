#!/usr/bin/env python3
"""
Convert YOLOE PyTorch models to NCNN format for Raspberry Pi 5
256x256 resolution for optimal performance on RPi5 (4GB RAM)

Usage:
    python convert_yoloe_to_ncnn.py           # Convert all models
    python convert_yoloe_to_ncnn.py --model yoloe-11s-seg.pt
    python convert_yoloe_to_ncnn.py --list    # List available models
"""

import argparse
import shutil
import sys
from pathlib import Path


# YOLOE models to convert (256x256 for RPi5 optimization)
YOLOE_MODELS = {
    "yoloe-11s-seg.pt": {
        "name": "YOLOE-11s-seg (Small)",
        "imgsz": 256,  # 256x256 for RPi5 optimization
        "description": "Small segmentation model - text/visual prompts"
    },
    "yoloe-11m-seg.pt": {
        "name": "YOLOE-11m-seg (Medium)",
        "imgsz": 256,
        "description": "Medium model - balanced speed/accuracy"
    },
}


def list_models():
    """List available YOLOE models."""
    print("\nAvailable YOLOE Models (256x256 NCNN):")
    print("-" * 60)
    models_dir = Path("models")

    for model_file, info in YOLOE_MODELS.items():
        model_path = models_dir / model_file
        if model_path.exists():
            print(f"  ✓ Found {info['name']}")
            print(f"         {info['description']}")
            print(f"         Resolution: {info['imgsz']}x{info['imgsz']}")
            print()
        else:
            print(f"  ? Missing {model_file}")
            print()

    print("\n256x256 resolution:")
    print("  - 4x fewer pixels than 640x640")
    print("  - ~4x faster inference")
    print("  - Slightly lower accuracy (acceptable for RPi5)")
    print("  - Required for staying under 4GB RAM budget")

    return any((models_dir / m).exists() for m in YOLOE_MODELS)


def convert_model(model_path: str, imgsz: int = 256):
    """Convert a single YOLOE model to NCNN format."""
    from ultralytics import YOLO

    model_name = Path(model_path).stem
    output_dir = Path(f"models/{model_name}_ncnn_model")

    print(f"\n{'='*60}")
    print(f"Converting: {model_path}")
    print(f"Output: {output_dir}")
    print(f"Resolution: {imgsz}x{imgsz}")
    print(f"{'='*60}")

    # Load model
    print("Loading model (this may take a moment)...")
    model = YOLO(model_path)

    # Export to NCNN
    print(f"Exporting to NCNN (imgsz={imgsz})...")
    success = model.export(
        format="ncnn",
        imgsz=imgsz,
        simplify=True,
        workspace=4096,
    )

    if success:
        # Move exported files to expected location
        exported_dir = Path(model_path).stem
        for f in Path(".").glob(f"{exported_dir}_ncnn_model/*"):
            if f.is_file():
                dest = output_dir / f.name
                if dest.exists():
                    dest.unlink()
                print(f"  Moving {f.name} -> {dest}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                f.rename(dest)

        # Clean up temp directory
        if Path(exported_dir).exists():
            shutil.rmtree(exported_dir)

        print(f"\n✓ Successfully converted to NCNN!")
        print(f"  Model files in: {output_dir}/")
        for f in sorted(output_dir.glob("*")):
            if f.is_file():
                size_mb = f.stat().st_size / (1024 * 1024)
                print(f"    - {f.name} ({size_mb:.2f} MB)")
        return True
    else:
        print(f"\n✗ Failed to convert {model_path}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert YOLOE PyTorch models to NCNN format (256x256)"
    )
    parser.add_argument(
        "--model", "-m",
        help="Specific model to convert (e.g., yoloe-11s-seg.pt)"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available models and exit"
    )
    parser.add_argument(
        "--imgsz", "-s",
        type=int,
        default=256,
        help="Input image size (default: 256 for RPi5 optimization)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Convert all available YOLOE models"
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  YOLOE PyTorch to NCNN Converter")
    print("  256x256 Resolution - Optimized for RPi5")
    print("=" * 60)

    models_dir = Path("models")
    if not models_dir.exists():
        print(f"\n✗ Models directory not found: {models_dir}")
        sys.exit(1)

    if args.list:
        list_models()
        return

    # Check ultralytics import
    print("\nChecking ultralytics import...")
    try:
        from ultralytics import YOLO
        print("  ✓ ultralytics imported successfully")
    except ImportError as e:
        print(f"  ✗ Import failed: {e}")
        print("\nInstall ultralytics:")
        print("  pip install ultralytics")
        sys.exit(1)

    if args.model:
        model_path = models_dir / args.model
        if not model_path.exists():
            print(f"\n✗ Model not found: {model_path}")
            sys.exit(1)
        convert_model(str(model_path), args.imgsz)

    elif args.all:
        print("\nConverting YOLOE models to NCNN (256x256)...")
        results = []
        for model_file in YOLOE_MODELS:
            model_path = models_dir / model_file
            if model_path.exists():
                print(f"\n  Converting {model_file}...")
                result = convert_model(str(model_path), args.imgsz)
                results.append((model_file, result))

        # Summary
        print("\n" + "=" * 60)
        print("Conversion Summary")
        print("=" * 60)
        for model_file, success in results:
            status = "✓ Success" if success else "✗ Failed"
            print(f"  {status}: {model_file}")

        failed = sum(1 for _, s in results if not s)
        if failed == 0:
            print(f"\nAll {len(results)} models converted successfully!")
        else:
            print(f"\n{failed} model(s) failed to convert")

    else:
        print("\nNo model specified. Available models:")
        list_models()
        print("\nUsage:")
        print("  python convert_yoloe_to_ncnn.py --all       # Convert all")
        print("  python convert_yoloe_to_ncnn.py -m yoloe-11s-seg.pt")
        print("  python convert_yoloe_to_ncnn.py --list")


if __name__ == "__main__":
    main()
