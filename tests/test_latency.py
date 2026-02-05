import pytest
import time
import json
import asyncio
from datetime import datetime
from shared.api import BaseMessage, MessageType

def test_detection_serialization_latency():
    """Measure latency of creating and serializing a detection message."""
    start_time = time.time()
    
    # Create large batch of detections to simulate heavy load
    detections = []
    for i in range(50):
        detections.append({
            "class": "person",
            "confidence": 0.95,
            "bbox": {"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4}
        })
        
    msg = BaseMessage(
        type=MessageType.DETECTIONS,
        data={
            "source": "laptop",
            "layer": "layer1",
            "detections": detections,
            "inference_time_ms": 15.0
        }
    )
    
    json_str = msg.to_json()
    
    end_time = time.time()
    latency_ms = (end_time - start_time) * 1000
    
    print(f"Serialization Latency (50 dets): {latency_ms:.3f}ms")
    assert latency_ms < 5.0 # Should be very fast

def test_end_to_end_payload_size():
    """Verify payload size optimization."""
    # Normalized
    det_norm = {
        "class": "person",
        "confidence": 0.95,
        "bbox": {"x1": 0.1234, "y1": 0.2345, "x2": 0.3456, "y2": 0.4567}
    }
    
    # Absolute (Old style)
    det_abs = {
        "class": "person",
        "confidence": 0.95,
        "x1": 123, "y1": 234, "x2": 345, "y2": 456,
        "bbox": [123, 234, 345, 456]
    }
    
    msg_norm = BaseMessage(type=MessageType.DETECTIONS, data={"detections": [det_norm]})
    msg_abs = BaseMessage(type=MessageType.DETECTIONS, data={"detections": [det_abs]})
    
    size_norm = len(msg_norm.to_json())
    size_abs = len(msg_abs.to_json())
    
    print(f"Payload Size: Normalized={size_norm}b, Absolute={size_abs}b")
    print(f"Reduction: {100 * (1 - size_norm/size_abs):.1f}%")
    
    assert size_norm < size_abs
