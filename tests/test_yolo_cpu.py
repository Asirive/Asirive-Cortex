"""
Test script to verify YOLO model works with CPU inference.
This script tests the exact configuration that will run on Raspberry Pi.

Author: Haziq (@IRSPlays)
Date: November 17, 2025
"""

import cv2
import time
import torch
from ultralytics import YOLO
import numpy as np

print("=" * 60)
print("Project-Cortex - YOLO CPU Inference Test")
print("=" * 60)

# Check PyTorch and CUDA availability
print(f"\nPyTorch Version: {torch.__version__}")
print(f"CUDA Available: {torch.cuda.is_available()}")
print(f"CUDA Version: {torch.version.cuda if torch.cuda.is_available() else 'N/A'}")

# Model configuration
MODEL_PATH = "models/yolo11x.pt"
DEVICE = "cpu"  # Force CPU for RPi simulation

print(f"\nLoading model: {MODEL_PATH}")
print(f"Device: {DEVICE}")

try:
    # Load model
    model = YOLO(MODEL_PATH)
    print("✅ Model loaded successfully")
    
    # Display model info
    print(f"Model classes: {len(model.names)}")
    print(f"Sample classes: {list(model.names.values())[:10]}")
    
    # Test inference with dummy image
    print("\n--- Testing inference with dummy image ---")
    dummy_img = np.zeros((640, 640, 3), dtype=np.uint8)
    
    start_time = time.time()
    results = model(dummy_img, device=DEVICE, verbose=False)
    inference_time = (time.time() - start_time) * 1000
    
    print(f"✅ Inference successful")
    print(f"⏱️  Inference time: {inference_time:.2f}ms")
    
    # Test with webcam
    print("\n--- Testing with webcam ---")
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("❌ Could not open webcam")
    else:
        print("✅ Webcam opened")
        
        # Capture a frame
        ret, frame = cap.read()
        if ret:
            print(f"✅ Frame captured: {frame.shape}")
            
            # Run inference
            start_time = time.time()
            results = model(frame, device=DEVICE, verbose=False, conf=0.5)
            inference_time = (time.time() - start_time) * 1000
            
            # Extract detections
            detections = []
            for box in results[0].boxes:
                class_id = int(box.cls)
                class_name = model.names[class_id]
                confidence = float(box.conf)
                detections.append(f"{class_name} ({confidence:.2f})")
            
            print(f"✅ Inference successful")
            print(f"⏱️  Inference time: {inference_time:.2f}ms")
            print(f"🎯 Detections: {', '.join(detections) if detections else 'nothing detected'}")
            
            # Display annotated frame
            annotated_frame = results[0].plot()
            cv2.imshow("YOLO CPU Test - Press 'q' to quit", annotated_frame)
            print("\n📺 Displaying annotated frame. Press 'q' to quit.")
            
            while True:
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            
        else:
            print("❌ Failed to capture frame")
        
        cap.release()
        cv2.destroyAllWindows()

except FileNotFoundError:
    print(f"❌ Model file not found: {MODEL_PATH}")
    print("   Please ensure the model file exists in the models/ directory")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Test complete")
print("=" * 60)
