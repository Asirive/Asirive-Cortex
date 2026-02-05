import pytest
import torch
import os
from laptop.layer1_service import Layer1Service

def test_layer1_service_initialization():
    """Test that Layer1Service initializes correctly with a model."""
    # We'll use a small model for testing if available, or just check the logic
    model_path = "yolo26n.pt" # Using n model for speed in tests
    service = Layer1Service(model_path=model_path, device="cpu")
    service.initialize()
    
    assert service.model is not None
    assert service.device == "cpu"
    assert service.model_path.endswith(model_path)

def test_layer1_service_npf_model_loading():
    """Test that Layer1Service can load the specific NPF model requested by user."""
    # Based on audit, yoloe-26n-seg.pt exists in models/
    model_path = "models/yoloe-26n-seg.pt"
    if not os.path.exists(model_path):
        pytest.skip(f"Model {model_path} not found for test")
        
    service = Layer1Service(model_path=model_path)
    service.initialize()
    
    assert service.model is not None
    # Verify it loaded as a segmentation model
    assert hasattr(service.model, 'task')
    assert service.model.task == 'segment'
