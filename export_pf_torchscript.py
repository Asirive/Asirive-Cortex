"""
Export YOLOE Prompt-Free models to TorchScript (workaround for ONNX export bug).
TorchScript works for prompt-free models since it doesn't try to fuse embeddings.
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

def export_pf_to_torchscript(model_path, output_name):
    """Export YOLOE prompt-free model to TorchScript."""
    print(f"\n{'='*60}")
    print(f"Exporting: {model_path}")
    print(f"{'='*60}")

    try:
        # Load model
        model = YOLOE(model_path)
        model.eval()
        print(f"  Model loaded successfully")

        # Create output directory
        output_folder = f"models/converted/{output_name}"
        os.makedirs(output_folder, exist_ok=True)

        # Create dummy input
        dummy_input = torch.randn(1, 3, 320, 320)
        print(f"  Tracing with input shape: {dummy_input.shape}")

        # TorchScript export via torch.jit.trace
        traced = torch.jit.trace(model, dummy_input)

        # Save TorchScript
        ts_path = os.path.join(output_folder, f"{output_name}.torchscript")
        traced.save(ts_path)
        size_mb = os.path.getsize(ts_path) / (1024 * 1024)
        print(f"  SUCCESS: {output_name}/{output_name}.torchscript")
        print(f"  Size: {size_mb:.1f} MB")

        # Also export as ONNX using traced model (sometimes works better)
        try:
            onnx_path = os.path.join(output_folder, f"{output_name}.onnx")
            torch.onnx.export(
                traced,
                dummy_input,
                onnx_path,
                input_names=['images'],
                output_names=['detections', 'masks'],
                opset_version=12,
                dynamic_axes=None  # Fixed shape
            )
            onnx_size = os.path.getsize(onnx_path) / (1024 * 1024)
            print(f"  Bonus ONNX: {output_name}/{output_name}.onnx ({onnx_size:.1f} MB)")
        except Exception as e:
            print(f"  ONNX fallback skipped: {e}")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("="*60)
    print("YOLOE Prompt-Free Export (TorchScript)")
    print("="*60)

    for model_path, output_name in PF_MODELS:
        if not os.path.exists(model_path):
            print(f"  Skipping {model_path} - not found")
            continue
        export_pf_to_torchscript(model_path, output_name)

    print("\n" + "="*60)
    print("Done!")
    print("="*60)
