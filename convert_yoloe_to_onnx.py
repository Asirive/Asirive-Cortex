#!/usr/bin/env python3
"""
Export YOLOE PyTorch models to ONNX format for Raspberry Pi 5
Use ONNX Runtime for prompt-free models (NCNN incompatible)

Usage:
    python convert_yoloe_to_onnx.py           # Convert all models
    python convert_yoloe_to_onnx.py --model yoloe-11s-seg-pf.pt
    python convert_yoloe_to_onnx.py --list    # List available models
"""

import argparse
import shutil
import sys
from pathlib import Path


# YOLOE models that require ONNX format
YOLOE_ONNX_MODELS = {
    "yoloe-11s-seg-pf.pt": {
        "name": "YOLOE-11s-seg-pf (Prompt-Free)",
        "imgsz": 640,
        "description": "Prompt-free variant - requires ONNX (NCNN incompatible)"
    },
    "yoloe-11m-seg-pf.pt": {
        "name": "YOLOE-11m-seg-pf (Prompt-Free)",
        "imgsz": 640,
        "description": "Medium prompt-free variant - requires ONNX"
    },
}


def list_models():
    """List available YOLOE models for ONNX export."""
    print("\nAvailable YOLOE Models (ONNX format required):")
    print("-" * 60)
    models_dir = Path("models")

    for model_file, info in YOLOE_ONNX_MODELS.items():
        model_path = models_dir / model_file
        if model_path.exists():
            print(f"  ✓ Found {info['name']}")
            print(f"         {info['description']}")
            print()
        else:
            print(f"  ? Missing {model_file}")
            print()

    print("\nThese models use LRPCHead which is NOT compatible with NCNN.")
    print("ONNX Runtime is required for prompt-free YOLOE models.")
    return any((models_dir / m).exists() for m in YOLOE_ONNX_MODELS)


def convert_model(model_path: str, imgsz: int = 640):
    """Convert a single YOLOE model to ONNX format."""
    from ultralytics import YOLO

    model_name = Path(model_path).stem
    output_path = Path(f"models/{model_name}.onnx")

    print(f"\n{'='*60}")
    print(f"Converting: {model_path}")
    print(f"Output: {output_path}")
    print(f"{'='*60}")

    # Load model
    print("Loading model (this may take a moment)...")
    model = YOLO(model_path)

    # Export to ONNX
    print(f"Exporting to ONNX (imgsz={imgsz})...")
    success = model.export(
        format="onnx",
        imgsz=imgsz,
        simplify=True,  # Simplify model graph
        dynamic=False,  # Fixed batch size for better performance
        opset=12,       # ONNX opset version
    )

    if success:
        # Rename to expected path if needed
        exported = Path(str(model_path).replace(".pt", ".onnx"))
        if exported.exists() and exported != output_path:
            shutil.move(str(exported), str(output_path))

        print(f"\n✓ Successfully exported to ONNX!")
        print(f"  File: {output_path}")
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"  Size: {size_mb:.2f} MB")
        return True
    else:
        print(f"\n✗ Failed to export {model_path}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert YOLOE prompt-free models to ONNX format"
    )
    parser.add_argument(
        "--model", "-m",
        help="Specific model to convert (e.g., yoloe-11s-seg-pf.pt)"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available models and exit"
    )
    parser.add_argument(
        "--imgsz", "-s",
        type=int,
        default=640,
        help="Input image size (default: 640)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Convert all available YOLOE models"
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  YOLOE PyTorch to ONNX Converter")
    print("  For Raspberry Pi 5 (Prompt-Free Models)")
    print("=" * 60)

    models_dir = Path("models")
    if not models_dir.exists():
        print(f"\n✗ Models directory not found: {models_dir}")
        sys.exit(1)

    if args.list:
        list_models()
        return

    # Check ultralytics import works
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
        # Convert specific model
        model_path = models_dir / args.model
        if not model_path.exists():
            print(f"\n✗ Model not found: {model_path}")
            sys.exit(1)
        convert_model(str(model_path), args.imgsz)

    elif args.all:
        # Convert all ONNX-compatible models
        print("\nConverting all YOLOE models to ONNX...")
        results = []
        for model_file in YOLOE_ONNX_MODELS:
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
            print(f"\nAll {len(results)} models exported to ONNX!")
            print("\nSync to RPi5:")
            print("  - models/yoloe-11s-seg-pf.onnx")
            print("  - models/yoloe-11m-seg-pf.onnx")
        else:
            print(f"\n{failed} model(s) failed to export")

    else:
        # Default: list models
        print("\nNo model specified. Available models:")
        list_models()
        print("\nUsage:")
        print("  python convert_yoloe_to_onnx.py --all       # Convert all models")
        print("  python convert_yoloe_to_onnx.py -m yoloe-11s-seg-pf.pt  # Convert specific")
        print("  python convert_yoloe_to_onnx.py --list     # List models")


if __name__ == "__main__":
    main()
