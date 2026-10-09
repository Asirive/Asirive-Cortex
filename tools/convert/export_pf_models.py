"""
Custom export for YOLOE Prompt-Free models.
These models need special handling to export correctly.
"""
import os
import torch
import shutil
from ultralytics import YOLOE

# Prompt-Free model paths
PF_MODELS = [
    ("models/yoloe-26n-seg-pf.pt", "yoloe_26n_seg_pf"),
    ("models/yoloe-26s-seg-pf.pt", "yoloe_26s_seg_pf"),
]

def export_yoloe_pf_to_onnx(model_path, output_name):
    """Export YOLOE prompt-free model to ONNX with proper class setup."""
    print(f"\n{'='*60}")
    print(f"Exporting: {model_path}")
    print(f"{'='*60}")

    try:
        # Load model
        model = YOLOE(model_path)
        print(f"  Model loaded successfully")
        print(f"  Classes built-in: 4585 (open vocabulary)")
        # Prompt-free models have vocabulary pre-fused - no set_classes() needed!

        # Create output directory
        output_folder = f"models/converted/{output_name}"
        os.makedirs(output_folder, exist_ok=True)

        # Export to ONNX
        success = model.export(
            format="onnx",
            imgsz=320,
            half=True,
            simplify=True,
            opset=12,
            dynamic=False,
        )

        if success and os.path.exists(success):
            # Move to correct location
            if os.path.isdir(success):
                for f in os.listdir(success):
                    src = os.path.join(success, f)
                    dst = os.path.join(output_folder, f)
                    shutil.move(src, dst)
                    print(f"  Saved: {output_name}/{f}")
                os.rmdir(success)
            else:
                dst = os.path.join(output_folder, f"{output_name}.onnx")
                shutil.move(success, dst)
                print(f"  Saved: {dst}")
                print(f"  Size: {os.path.getsize(dst) / (1024*1024):.1f} MB")
            print(f"  SUCCESS!")
        else:
            print(f"  ERROR: Export returned {success}")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("="*60)
    print("YOLOE Prompt-Free Export")
    print("="*60)

    for model_path, output_name in PF_MODELS:
        if not os.path.exists(model_path):
            print(f"  Skipping {model_path} - not found")
            continue
        export_yoloe_pf_to_onnx(model_path, output_name)

    print("\n" + "="*60)
    print("Done!")
    print("="*60)
