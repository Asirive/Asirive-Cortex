
import time
import cv2
import numpy as np
import logging
import sys
from pathlib import Path

# Configure logging to flush immediately
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger("Benchmark")

def benchmark_ultralytics(model_path, input_size=(640, 640), iterations=10):
    """Test Ultralytics YOLO wrapper with DEEP DEBUG"""
    print(f"\n--- Benchmarking Ultralytics: {model_path} @ {input_size} ---")
    try:
        print("[DEBUG] Importing ultralytics...")
        from ultralytics import YOLO
        import torch
        print(f"[DEBUG] Ultralytics imported. Torch: {torch.__version__}")
        
        print(f"[DEBUG] Initializing YOLO('{model_path}')...")
        model = YOLO(model_path, task='detect')
        print("[DEBUG] YOLO object initialized.")
        
        # DEBUG: Inspect class names
        if hasattr(model, 'names'):
            print(f"[DEBUG] Model Names Length: {len(model.names)}")
            print(f"[DEBUG] First 5 names: {list(model.names.values())[:5]}")
        else:
             print("[DEBUG] Model has no 'names' attribute!")

        # Verify files exist
        param_file = Path(model_path) / "model.ncnn.param"
        bin_file = Path(model_path) / "model.ncnn.bin"
        print(f"[DEBUG] Checking files:\n  - Param: {param_file} ({param_file.exists()})\n  - Bin: {bin_file} ({bin_file.exists()})")
        
        # Create dummy image
        print(f"[DEBUG] Creating dummy input {input_size}...")
        img = np.zeros((input_size[1], input_size[0], 3), dtype=np.uint8)
        
        # Warmup (Critical Step)
        print("[DEBUG] STARTING WARMUP PREDICT (Verbose=False)...")
        # Set verbose=False to avoid KeyError in logging
        model.predict(img, verbose=False, imgsz=640) 
        print("[DEBUG] WARMUP COMPLETE.")
        
        # Measure
        print(f"[DEBUG] Starting loop ({iterations} iters)...")
        start = time.perf_counter()
        for i in range(iterations):
            print(f"[DEBUG] Iter {i+1}/{iterations}...")
            model.predict(img, verbose=False, imgsz=640)
        end = time.perf_counter()
        
        avg = (end - start) / iterations * 1000
        logger.info(f"⚡ Ultralytics Average (`{model_path}`): {avg:.2f} ms")
        
    except Exception as e:
        logger.error(f"❌ Ultralytics Benchmark Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("====================================")
    print("   Project Cortex Model Benchmark   ")
    print("====================================")
    
    # Base directory
    base_dir = Path("models/converted")
    
    # Find all subdirectories (assuming they are NCNN/ONNX models)
    if not base_dir.exists():
        print(f"❌ Error: {base_dir} does not exist!")
        sys.exit(1)
        
    # Get all entries
    all_models = [d for d in base_dir.iterdir() if d.is_dir()]
    all_models.sort() # Alphabetical
    
    results = []

    print(f"Found {len(all_models)} potential models.")

    for model_path in all_models:
        model_name = model_path.name
        str_path = str(model_path)
        
        # Determine Resolution
        # Rules: 
        # - YOLOE / Seg -> 192x192
        # - Standard YOLO -> 320x320
        # - Fallback -> 640x640
        if "yoloe" in model_name or "seg" in model_name:
            res = (192, 192)
            res_label = "192px (Optimized)"
        elif "yolo" in model_name:
            res = (320, 320)
            res_label = "320px (Standard)"
        else:
            res = (640, 640)
            res_label = "640px (Fallback)"
            
        print(f"\n🔹 Testing: {model_name} [{res_label}]...")
        
        # Run Benchmark
        try:
             # We use the function we defined above
             # Note: benchmark_ultralytics logs to stdout, we want to capture the AVG logic 
             # but the current function only logs it. 
             # We will just run it and let the user see the logs.
             # Ideally we'd modify the function to return the value, but let's keep it simple for now.
             benchmark_ultralytics(str_path, input_size=res, iterations=10)
        except Exception as e:
             print(f"⚠️ Skipped {model_name}: {e}")

    print("\n====================================")
    print("   Benchmark Complete")
    print("====================================")

