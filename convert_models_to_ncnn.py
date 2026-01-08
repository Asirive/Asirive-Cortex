#!/usr/bin/env python3
"""
Project Cortex v2.0 - Model Conversion to NCNN

Convert all YOLO models to NCNN format for 4-5x faster inference on RPi 5.

CRITICAL PERFORMANCE OPTIMIZATION:
- YOLO11n PyTorch: 388ms → NCNN: 94ms (4.1x faster) ✅
- YOLO11s PyTorch: 1085ms → NCNN: 222ms (4.9x faster) ✅
- YOLO11x PyTorch: ~1000ms → NCNN: ~280ms (3.6x faster) ✅

Usage:
    python3 convert_models_to_ncnn.py

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: December 31, 2025
"""

import os
import sys
from pathlib import Path
from ultralytics import YOLO
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Models to convert
MODELS_TO_CONVERT = [
    # Layer 0: Guardian (Safety-Critical Detection)
    {
        "path": "models/yolo11n.pt",
        "description": "YOLO11n - Fastest (94ms, recommended for Layer 0)",
        "priority": "HIGH"
    },
    {
        "path": "models/yolo11s.pt",
        "description": "YOLO11s - Balanced (222ms)",
        "priority": "MEDIUM"
    },
    {
        "path": "models/yolo11x.pt",
        "description": "YOLO11x - Most Accurate (280ms, but slow)",
        "priority": "LOW"
    },
    
    # Layer 1: Learner (Adaptive Context Detection)
    {
        "path": "models/yoloe-11s-seg.pt",
        "description": "YOLOE-11s Text/Visual Prompts (222ms)",
        "priority": "HIGH"
    },
    {
        "path": "models/yoloe-11m-seg.pt",
        "description": "YOLOE-11m Text/Visual Prompts (more accurate)",
        "priority": "MEDIUM"
    },
    {
        "path": "models/yoloe-11s-seg-pf.pt",
        "description": "YOLOE-11s Prompt-Free (4585+ classes)",
        "priority": "HIGH"
    },
    {
        "path": "models/yoloe-11m-seg-pf.pt",
        "description": "YOLOE-11m Prompt-Free (more accurate)",
        "priority": "MEDIUM"
    },
]


def check_prerequisites():
    """Check if all prerequisites are met."""
    logger.info("🔍 Checking prerequisites...")
    
    # Check Ultralytics
    try:
        from ultralytics import YOLO
        logger.info("✅ Ultralytics installed")
    except ImportError:
        logger.error("❌ Ultralytics not installed. Run: pip install ultralytics[export]")
        return False
    
    # Check models directory
    if not os.path.exists("models"):
        logger.error("❌ models/ directory not found")
        return False
    
    logger.info("✅ Prerequisites met")
    return True


def convert_model(model_info):
    """Convert a single model to NCNN format."""
    model_path = model_info["path"]
    description = model_info["description"]
    priority = model_info["priority"]
    is_yoloe = "yoloe" in model_path.lower()
    
    # Check if model exists
    if not os.path.exists(model_path):
        logger.warning(f"⚠️  [{priority}] Skipping {model_path} (not found)")
        logger.info(f"    Download from: https://github.com/ultralytics/assets/releases")
        return False
    
    # Check if already converted
    ncnn_dir = model_path.replace(".pt", "_ncnn_model")
    if os.path.exists(ncnn_dir):
        logger.info(f"✅ [{priority}] Already converted: {ncnn_dir}")
        return True
    
    logger.info(f"\n{'='*70}")
    logger.info(f"🔄 [{priority}] Converting: {model_path}")
    logger.info(f"    {description}")
    logger.info(f"{'='*70}")
    
    try:
        # Load PyTorch model
        logger.info("📦 Loading PyTorch model...")
        
        # Handle YOLOE models differently
        if is_yoloe:
            from ultralytics import YOLOE
            model = YOLOE(model_path)
            
            # Configure default classes for export (required for YOLOE)
            # Using COCO classes for compatibility
            default_classes = [
                "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
                "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
                "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
                "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
                "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
                "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
                "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
                "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
                "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
                "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
            ]
            logger.info(f"    Setting {len(default_classes)} COCO classes for YOLOE export...")
            model.set_classes(default_classes, model.get_text_pe(default_classes))
        else:
            model = YOLO(model_path)
        
        # Get model size
        model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
        logger.info(f"    Model size: {model_size_mb:.1f} MB")
        
        # Export to NCNN
        logger.info("⚡ Exporting to NCNN format (this may take 30-60 seconds)...")
        model.export(format="ncnn")
        
        # Verify NCNN model exists
        if os.path.exists(ncnn_dir):
            # Check NCNN model size
            ncnn_size_mb = sum(
                os.path.getsize(os.path.join(ncnn_dir, f)) 
                for f in os.listdir(ncnn_dir)
            ) / (1024 * 1024)
            
            logger.info(f"✅ Success: {ncnn_dir}")
            logger.info(f"    NCNN size: {ncnn_size_mb:.1f} MB")
            logger.info(f"    Expected speedup: 4-5x faster inference!")
            return True
        else:
            logger.error(f"❌ Failed: NCNN directory not created")
            return False
    
    except Exception as e:
        logger.error(f"❌ Error converting {model_path}: {e}")
        return False


def main():
    """Main conversion workflow."""
    print("\n" + "="*70)
    print("PROJECT CORTEX V2.0 - YOLO MODEL CONVERSION TO NCNN")
    print("="*70)
    print("\n🎯 Goal: 4-5x faster inference on Raspberry Pi 5")
    print("📊 Benchmark: YOLO11n 388ms → 94ms (PyTorch → NCNN)")
    print("\n")
    
    # Check prerequisites
    if not check_prerequisites():
        logger.error("\n❌ Prerequisites not met. Exiting.")
        sys.exit(1)
    
    # Convert models
    results = {
        "success": [],
        "skipped": [],
        "failed": []
    }
    
    for model_info in MODELS_TO_CONVERT:
        result = convert_model(model_info)
        
        if result is None:
            results["skipped"].append(model_info["path"])
        elif result:
            results["success"].append(model_info["path"])
        else:
            results["failed"].append(model_info["path"])
    
    # Summary
    print("\n" + "="*70)
    print("📊 CONVERSION SUMMARY")
    print("="*70)
    print(f"✅ Successful: {len(results['success'])}")
    for path in results["success"]:
        print(f"   - {path}")
    
    if results["skipped"]:
        print(f"\n⚠️  Skipped: {len(results['skipped'])} (models not found)")
        for path in results["skipped"]:
            print(f"   - {path}")
    
    if results["failed"]:
        print(f"\n❌ Failed: {len(results['failed'])}")
        for path in results["failed"]:
            print(f"   - {path}")
    
    # Next steps
    print("\n" + "="*70)
    print("📋 NEXT STEPS")
    print("="*70)
    print("1. Update .env file:")
    print("   YOLO_MODEL_PATH=models/yolo11n_ncnn_model")
    print("   YOLOE_MODEL_PATH=models/yoloe-11s-seg_ncnn_model")
    print()
    print("2. Update layer0_guardian/__init__.py:")
    print("   model_path='models/yolo11n_ncnn_model'")
    print()
    print("3. Update layer1_learner/__init__.py:")
    print("   model_path='models/yoloe-11s-seg_ncnn_model'")
    print()
    print("4. Run benchmark: python3 tests/benchmark_ncnn.py")
    print()
    print("5. Test full system: python3 src/main.py")
    print()
    print("🚀 Expected result: 4-5x faster inference!")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
