"""
Test configuration and utilities for Project-Cortex v2.0

Provides common fixtures and utilities for all test modules.

Author: Haziq (@IRSPlays)
Date: November 17, 2025
"""

import pytest
import os
import sys

# Add common project import roots to Python path.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SRC_ROOT = os.path.join(PROJECT_ROOT, 'src')
RPI5_ROOT = os.path.join(PROJECT_ROOT, 'rpi5')
LAPTOP_ROOT = os.path.join(PROJECT_ROOT, 'laptop')

for path in [PROJECT_ROOT, SRC_ROOT, RPI5_ROOT, LAPTOP_ROOT]:
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)

# Test constants
TEST_MODEL_PATH = "models/yolo11x.pt"
TEST_DEVICE = "cpu"
TEST_CONFIDENCE = 0.5
TEST_IMAGE_SIZE = (640, 640, 3)


@pytest.fixture(scope="session")
def project_root():
    """Returns the project root directory."""
    return os.path.dirname(os.path.dirname(__file__))


@pytest.fixture(scope="session")
def model_exists():
    """Check if the YOLO model file exists."""
    return os.path.exists(TEST_MODEL_PATH)


@pytest.fixture(scope="session")
def skip_if_no_model():
    """Skip test if model file is not available."""
    if not os.path.exists(TEST_MODEL_PATH):
        pytest.skip(f"Model file not found: {TEST_MODEL_PATH}")


@pytest.fixture(scope="session")
def skip_if_no_webcam():
    """Skip test if webcam is not available."""
    import cv2
    cap = cv2.VideoCapture(0)
    is_available = cap.isOpened()
    cap.release()
    
    if not is_available:
        pytest.skip("Webcam not available")
