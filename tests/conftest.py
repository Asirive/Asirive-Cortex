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


# TB10 fix: pytest's default test discovery picks up every file in
# tests/ that starts with `test_`, including several demo / script /
# debug files that are not actually unit tests. These files use
# `print()` headers, `sys.exit()`, and import removed modules
# (dual_yolo_handler, yolo11x.pt) — all from before the YOLOE +
# yolo26x refactor. The remaining 23 unit tests that DO have proper
# `class Test*` definitions are unaffected.
#
# We can't rename the files (they're referenced by the docs and the
# user runs them manually with `python tests/test_*.py`). The
# standard pytest mechanism to skip files at collection is the
# `collect_ignore` global — a list of glob patterns pytest skips
# before trying to import them. This prevents the import-time
# ModuleNotFoundError on the removed dual_yolo_handler module.
collect_ignore = [
    "test_dual_yolo.py",          # imports removed dual_yolo_handler
    "test_gui_integration.py",    # demo with print()/sys.exit
    "test_yolo_cpu.py",           # demo with print() and removed yolo11x paths
    # Below: more stale tests from before the YOLOE 26 + memory refactor
    "test_memory_storage.py",     # imports removed memory_storage.get_memory_storage
    "test_router_priority_fix.py",# imports removed src.* module path
    "test_zai_coding_endpoint.py",# imports removed src.* module path
    # Below: helper scripts (not unit tests). They live alongside the
    # real tests for convenience but use `def main()` + sys.exit() and
    # pull in API keys at import time.
    "_run_binaural_test.py",
    "_run_stereo_test.py",
    "_run_static.py",
    "_run_sweep.py",
    "_run_sweep2.py",
]
