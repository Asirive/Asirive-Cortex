# Project-Cortex v2.0 - Test Suite

This directory contains comprehensive tests for the Project-Cortex assistive AI wearable system.

## Test Structure

```
tests/
├── conftest.py              # Pytest configuration and shared fixtures
├── test_yolo_cpu.py         # Standalone YOLO CPU inference test
├── test_integration.py      # Integration tests for GUI components
└── README.md               # This file
```

## Running Tests

### Run All Tests
```powershell
pytest tests/ -v
```

### Run Specific Test File
```powershell
pytest tests/test_integration.py -v
```

### Run with Coverage
```powershell
pytest tests/ --cov=src --cov-report=html
```

### Run Standalone YOLO Test
```powershell
python tests/test_yolo_cpu.py
```

## Test Categories

### 1. **YOLO CPU Inference Tests** (`test_yolo_cpu.py`)
Tests the core YOLO object detection functionality:
- Model loading on CPU device
- Inference performance measurement
- Webcam frame processing
- Confidence threshold filtering
- Annotated frame generation

**Key Tests:**
- `test_model_loading()` - Verifies model loads successfully
- `test_inference_dummy_image()` - Tests inference on blank image
- `test_inference_with_webcam()` - Tests with real webcam input
- `test_cpu_inference_performance()` - Measures inference time over multiple frames

### 2. **Integration Tests** (`test_integration.py`)
Tests the integration between components:
- Threading pipeline (frame_queue → YOLO → processed_queue → UI)
- Video processing utilities
- Detection extraction and formatting
- Hybrid AI context generation

**Key Tests:**
- `test_frame_queue_flow()` - Verifies frames flow through pipeline
- `test_queue_overflow_handling()` - Tests queue management
- `test_aspect_ratio_preservation()` - Ensures correct video scaling
- `test_gemini_context_includes_yolo_detections()` - Validates hybrid AI integration

## Test Requirements

### Required Hardware
- **Webcam**: For real-world video capture tests
- **CPU**: All tests run on CPU (Raspberry Pi compatible)

### Required Files
- **YOLO Model**: `models/yolo11x.pt` (114MB)
- **Environment**: `.env` file with API keys (for full integration tests)

### Skip Conditions
Tests automatically skip if:
- Model file is missing
- Webcam is not available
- API keys are not configured

## Performance Expectations

### Laptop (Development)
- YOLO Inference: ~200-500ms per frame
- Queue Processing: <10ms
- Frame Display: ~15ms refresh rate

### Raspberry Pi 5 (Production Target)
- YOLO Inference: ~500-800ms per frame (yolo11x.pt)
- Expected: May need to use yolo11m.pt for better performance

## Continuous Integration

These tests are designed to run in CI/CD pipelines:
```yaml
# Example GitHub Actions workflow
- name: Run Tests
  run: |
    pip install pytest pytest-cov
    pytest tests/ -v --cov=src
```

## Adding New Tests

### Test Naming Convention
- Test files: `test_*.py`
- Test functions: `test_*()` or `Test*` classes
- Fixtures: Descriptive names in `conftest.py`

### Example Test Structure
```python
import pytest

class TestNewFeature:
    """Test suite for new feature."""
    
    def test_basic_functionality(self):
        """Test basic feature works."""
        assert True
    
    @pytest.mark.skipif(condition, reason="Skip reason")
    def test_optional_feature(self):
        """Test that may be skipped."""
        pass
```

## Debugging Tests

### Verbose Output
```powershell
pytest tests/ -v -s
```

### Run Single Test
```powershell
pytest tests/test_integration.py::TestThreadingPipeline::test_frame_queue_flow -v
```

### Debug with Print Statements
```powershell
pytest tests/ -v -s --capture=no
```

## Known Issues

1. **Webcam Tests**: May fail in headless environments (CI servers)
2. **Performance Tests**: Results vary by hardware
3. **Model Size**: yolo11x.pt is large (114MB) - may affect CI cache

## Future Tests

Planned test additions:
- [ ] Layer 3 (Guide) - TTS/STT integration tests
- [ ] Gemini API mock tests
- [ ] 3D Audio (OpenAL) tests
- [ ] GPS navigation tests
- [ ] End-to-end workflow tests
- [ ] Performance regression tests
- [ ] Raspberry Pi-specific tests

---
**Author**: Haziq (@IRSPlays)  
**Project**: Project-Cortex v2.0  
**Competition**: Young Innovators Awards (YIA) 2026
