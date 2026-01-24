
from ultralytics import YOLO
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Export")

def export_model(pt_path, output_name=None):
    logger.info(f"Loading PT model: {pt_path}")
    try:
        model = YOLO(pt_path)
        logger.info(f"Model loaded. Exporting to ONNX (imgsz=192)...")
        
        # Export with imgsz=192
        path = model.export(format='onnx', dynamic=True, imgsz=192)
        logger.info(f"✅ Export success! Saved to: {path}")
        return path
    except Exception as e:
        logger.error(f"❌ Export failed for {pt_path}: {e}")
        return None

if __name__ == "__main__":
    # 1. Prompt-Free (PF)
    export_model("models/converted/yoloe_26n_seg_pf/yoloe-26n-seg-pf.pt")
    
    # 2. Non-Prompt-Free (Standard YOLOE-Seg)
    # We use the source .pt file found in models/
    export_model("models/yoloe-26s-seg.pt")

