"""
Convert all YOLO models to optimized formats:
- NCNN: For YOLOv26 and YOLOE (segmentation) - optimized for ARM/Raspberry Pi
- ONNX: For YOLOE Prompt-Free - better support for open-vocabulary detection

Frame size: 192x192 | Precision: FP16
"""
import os
import shutil
from ultralytics import YOLO, YOLOE

# Model directory
MODEL_DIR = "models"
OUTPUT_DIR = "models/converted"

# Model configurations
MODEL_CONFIGS = [
    # YOLOv26 - Detection (NCNN)
    {"name": "yolo26n.pt", "type": "yolo", "format": "ncnn"},
    {"name": "yolo26s.pt", "type": "yolo", "format": "ncnn"},
    {"name": "yolo26m.pt", "type": "yolo", "format": "ncnn"},
    # YOLOE - Segmentation (NCNN)
    {"name": "yoloe-26n-seg.pt", "type": "yoloe", "format": "ncnn"},
    {"name": "yoloe-26s-seg.pt", "type": "yoloe", "format": "ncnn"},
    # YOLOE Prompt-Free - Open vocabulary (ONNX)
    {"name": "yoloe-26n-seg-pf.pt", "type": "yoloe", "format": "onnx"},
    {"name": "yoloe-26s-seg-pf.pt", "type": "yoloe", "format": "onnx"},
]

def convert_model(config):
    """Convert a model to the specified format."""
    model_name = config["name"]
    model_type = config["type"]
    fmt = config["format"]

    # Create individual folder for each model
    model_base = os.path.splitext(model_name)[0].replace("-", "_")
    
    # Append suffix for NCNN (Required by Ultralytics AutoBackend)
    if fmt == "ncnn":
        output_folder_name = f"{model_base}_ncnn_model"
    else:
        output_folder_name = model_base
        
    output_folder = os.path.join(OUTPUT_DIR, output_folder_name)
    os.makedirs(output_folder, exist_ok=True)

    model_path = os.path.join(MODEL_DIR, model_name)

    print(f"\n{'='*60}")
    print(f"Converting: {model_name} -> {fmt.upper()}")
    print(f"Output folder: {model_base}/")
    print(f"{'='*60}")

    try:
        if model_type == "yoloe":
            model = YOLOE(model_path)
        else:
            model = YOLO(model_path)

        # Common export options
        export_kwargs = {
            "half": True,       # FP16 for smaller size
            "simplify": True,   # ONNX simplification
            "opset": 12,
            "dynamic": False,   # FIXED SHAPE IS FASTER & SAFER (Prevents Hangs)
        }
        
        # Resolution logic (Per User Request)
        if model_type == "yolo":
            # Layer 0 (Normal YOLO): 320x320
            export_kwargs["imgsz"] = 320
        else:
            # Layer 1 (YOLOE/Seg): 192x192 (Heavy model optimization)
            export_kwargs["imgsz"] = 192
            export_kwargs["int8"] = True  # Enable INT8 Quantization for Speed

        if fmt == "ncnn":
            exported_path = model.export(format="ncnn", **export_kwargs)
        elif fmt == "onnx":
            # ONNX doesn't support 'int8' arg in ultra export, use dynamic=False and half=True
            if "int8" in export_kwargs:
                del export_kwargs["int8"]
            # Ensure opset is 12 for compatibility
            export_kwargs["opset"] = 12
            exported_path = model.export(format="onnx", **export_kwargs)
        else:
            raise ValueError(f"Unsupported format: {fmt}")

        # Move exported files to output folder
        if os.path.exists(exported_path):
            if os.path.isdir(exported_path):
                for f in os.listdir(exported_path):
                    src = os.path.join(exported_path, f)
                    dst = os.path.join(output_folder, f)
                    shutil.move(src, dst)
                    print(f"  Saved: {model_base}/{f}")
                os.rmdir(exported_path)
            else:
                # Single file (ONNX)
                dst = os.path.join(output_folder, f"{model_base}.{fmt}")
                shutil.move(exported_path, dst)
                print(f"  Saved: {model_base}/{model_base}.{fmt}")

            print(f"  SUCCESS: {model_name} -> {fmt.upper()} (192x192, FP16)")
        else:
            print(f"  ERROR: Export failed for {model_name}")

    except Exception as e:
        print(f"  ERROR converting {model_name}: {e}")

def main():
    print("="*60)
    print("YOLO/YOLOE Model Conversion")
    print("Frame size: 192x192 | Precision: FP16")
    print(f"Output directory: {OUTPUT_DIR}/")
    print("="*60)

    for config in MODEL_CONFIGS:
        model_path = os.path.join(MODEL_DIR, config["name"])
        if not os.path.exists(model_path):
            print(f"\nSkipping {config['name']} - not found")
            continue
        convert_model(config)

    print(f"\n{'='*60}")
    print("Conversion complete!")
    print(f"Output: {OUTPUT_DIR}/")
    print("="*60)

if __name__ == "__main__":
    main()
