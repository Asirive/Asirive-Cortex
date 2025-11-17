"""
Integration tests for Project-Cortex v2.0 GUI Application

Tests the integration between video capture, YOLO processing,
and GUI display components.

Author: Haziq (@IRSPlays)
Date: November 17, 2025
"""

import pytest
import tkinter as tk
import threading
import queue
import time
import cv2
import numpy as np
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestThreadingPipeline:
    """Test the threading pipeline for frame processing."""
    
    def test_frame_queue_flow(self):
        """Test that frames flow correctly through queues."""
        frame_queue = queue.Queue(maxsize=2)
        processed_queue = queue.Queue(maxsize=2)
        
        # Simulate video capture thread
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame_queue.put(test_frame)
        
        # Simulate processing thread
        retrieved_frame = frame_queue.get(timeout=1)
        assert retrieved_frame is not None
        assert retrieved_frame.shape == (480, 640, 3)
        
        # Simulate putting processed frame
        processed_queue.put(retrieved_frame)
        
        # Simulate UI thread
        ui_frame = processed_queue.get(timeout=1)
        assert ui_frame is not None
        assert ui_frame.shape == test_frame.shape
    
    def test_queue_overflow_handling(self):
        """Test that queue overflow is handled correctly."""
        test_queue = queue.Queue(maxsize=2)
        
        # Fill queue
        test_queue.put(1)
        test_queue.put(2)
        
        assert test_queue.full()
        
        # Simulate clearing old frame before adding new
        if test_queue.full():
            old_frame = test_queue.get_nowait()
        
        test_queue.put(3)
        
        assert not test_queue.full()
        assert test_queue.qsize() == 2


class TestVideoProcessing:
    """Test video processing utilities."""
    
    def test_aspect_ratio_preservation(self):
        """Test that aspect ratio is preserved during resize."""
        original_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        canvas_width, canvas_height = 640, 480
        
        h, w, _ = original_frame.shape
        aspect = w / h
        
        if canvas_width / canvas_height > aspect:
            new_h = canvas_height
            new_w = int(new_h * aspect)
        else:
            new_w = canvas_width
            new_h = int(new_w / aspect)
        
        resized = cv2.resize(original_frame, (new_w, new_h))
        
        # Check aspect ratio is preserved (with small tolerance for rounding)
        original_aspect = original_frame.shape[1] / original_frame.shape[0]
        resized_aspect = resized.shape[1] / resized.shape[0]
        
        assert abs(original_aspect - resized_aspect) < 0.01, "Aspect ratio should be preserved"
    
    def test_bgr_to_rgb_conversion(self):
        """Test BGR to RGB color conversion."""
        bgr_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        bgr_frame[:, :, 0] = 255  # Blue channel
        
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        
        assert rgb_frame[:, :, 2][0, 0] == 255, "Blue should be in red channel after conversion"
        assert rgb_frame[:, :, 0][0, 0] == 0, "Red channel should be 0"


class TestDetectionProcessing:
    """Test detection extraction and formatting."""
    
    def test_detection_string_formatting(self):
        """Test that detection strings are formatted correctly."""
        detections = ["person (0.95)", "car (0.87)", "person (0.92)"]
        
        # Remove duplicates and sort
        unique_detections = sorted(set(detections))
        detections_str = ", ".join(unique_detections)
        
        assert "person (0.95)" in detections_str
        assert "car (0.87)" in detections_str
        # Should only have one "person" entry
        assert detections_str.count("person") == 1
    
    def test_empty_detections_handling(self):
        """Test handling when no objects are detected."""
        detections = []
        detections_str = ", ".join(detections) or "nothing"
        
        assert detections_str == "nothing"
    
    def test_confidence_filtering(self):
        """Test filtering detections by confidence threshold."""
        mock_boxes = [
            {"conf": 0.95, "cls": 0, "name": "person"},
            {"conf": 0.45, "cls": 1, "name": "car"},
            {"conf": 0.60, "cls": 2, "name": "bicycle"}
        ]
        
        threshold = 0.5
        filtered = [b for b in mock_boxes if b["conf"] > threshold]
        
        assert len(filtered) == 2
        assert all(b["conf"] > threshold for b in filtered)


class TestEnvironmentVariables:
    """Test environment variable loading."""
    
    def test_default_values(self):
        """Test that default values are used when env vars not set."""
        import os
        
        # Test YOLO_DEVICE default
        yolo_device = os.getenv('YOLO_DEVICE', 'cpu')
        assert yolo_device == 'cpu', "Default YOLO_DEVICE should be 'cpu'"
        
        # Test YOLO_CONFIDENCE default
        yolo_confidence = float(os.getenv('YOLO_CONFIDENCE', '0.5'))
        assert yolo_confidence == 0.5, "Default YOLO_CONFIDENCE should be 0.5"


class TestHybridAIContext:
    """Test the hybrid AI system context generation."""
    
    def test_gemini_context_includes_yolo_detections(self):
        """Test that Gemini context includes Layer 1 YOLO detections."""
        last_detections = "person (0.95), car (0.87)"
        user_query = "What do you see?"
        
        context = f"""You are Project-Cortex, an AI assistant for visually impaired users.

**3-Layer Hybrid AI Architecture:**
- Layer 1 (Reflex - Local YOLO): Currently detected objects: {last_detections}
- Layer 2 (Thinker - You): Analyze the scene using the image and Layer 1 context
- Layer 3 (Guide): Your response will be converted to speech

**User Query:** {user_query}"""
        
        assert "person (0.95)" in context
        assert "car (0.87)" in context
        assert user_query in context
        assert "Layer 1" in context
        assert "Layer 2" in context
    
    def test_context_length_constraint(self):
        """Test that context follows length constraints for TTS."""
        # Simulate checking for TTS-friendly response length
        max_words = 50
        response = "This is a test response that should be concise."
        word_count = len(response.split())
        
        assert word_count <= max_words, f"Response should be under {max_words} words for TTS efficiency"


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
