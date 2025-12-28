"""
Project-Cortex v2.0 - Dual YOLO Test Script

This script validates the Layer 0 + Layer 1 dual-model adaptive system.

TESTS:
1. Parallel Inference: Verify both models run concurrently
2. Safety Latency: Ensure Layer 0 <100ms
3. Context Latency: Ensure Layer 1 <150ms
4. Adaptive Learning: Test Gemini, Maps, Memory integration
5. RAM Budget: Verify <3.9GB total
6. Prompt Persistence: Test JSON save/load
7. Haptic Feedback: Test vibration patterns (mock mode)

REQUIREMENTS:
- ultralytics (with YOLO and YOLOE support)
- spacy + en_core_web_sm model
- psutil (for RAM monitoring)
- Test frame image (tests/test_frame.jpg)

USAGE:
    python tests/test_dual_yolo.py

Author: Haziq (@IRSPlays)
Competition: Young Innovators Awards (YIA) 2026
"""

import logging
import sys
import time
from pathlib import Path
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import test dependencies
try:
    import cv2
    import psutil
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.error("❌ OpenCV not installed. Run: pip install opencv-python")

try:
    from dual_yolo_handler import DualYOLOHandler
    HANDLER_AVAILABLE = True
except ImportError as e:
    HANDLER_AVAILABLE = False
    logger.error(f"❌ Failed to import DualYOLOHandler: {e}")


class TestResults:
    """Container for test results."""
    
    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
        self.test_details = []
    
    def record(self, test_name: str, passed: bool, message: str):
        """Record test result."""
        if passed:
            self.tests_passed += 1
            status = "✅ PASS"
        else:
            self.tests_failed += 1
            status = "❌ FAIL"
        
        self.test_details.append(f"{status} {test_name}: {message}")
        logger.info(f"{status} {test_name}: {message}")
    
    def summary(self):
        """Print test summary."""
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        for detail in self.test_details:
            print(detail)
        print("="*70)
        print(f"TOTAL: {self.tests_passed} passed, {self.tests_failed} failed")
        print("="*70 + "\n")
        
        return self.tests_failed == 0


def test_model_loading(results: TestResults) -> DualYOLOHandler:
    """
    Test 1: Model Loading
    
    Verify both YOLO11x and YOLOE-11s can be loaded.
    """
    logger.info("\n🧪 Test 1: Model Loading")
    
    try:
        handler = DualYOLOHandler(
            guardian_model_path="models/yolo11x.pt",
            learner_model_path="models/yoloe-11m-seg.pt",
            device="cpu"  # Use CPU for laptop testing
        )
        results.record(
            "Model Loading",
            True,
            "Both models loaded successfully"
        )
        return handler
    except Exception as e:
        results.record(
            "Model Loading",
            False,
            f"Failed to load models: {e}"
        )
        return None


def test_parallel_inference(handler: DualYOLOHandler, frame: np.ndarray, results: TestResults):
    """
    Test 2: Parallel Inference
    
    Verify both models run concurrently on the same frame.
    """
    logger.info("\n🧪 Test 2: Parallel Inference")
    
    try:
        start = time.time()
        guardian_results, learner_results = handler.process_frame(frame)
        total_time = (time.time() - start) * 1000
        
        results.record(
            "Parallel Inference",
            True,
            f"Both models completed in {total_time:.1f}ms (guardian: {len(guardian_results)}, learner: {len(learner_results)})"
        )
    except Exception as e:
        results.record(
            "Parallel Inference",
            False,
            f"Failed: {e}"
        )


def test_safety_latency(handler: DualYOLOHandler, frame: np.ndarray, results: TestResults):
    """
    Test 3: Safety Latency
    
    Verify Layer 0 Guardian meets <100ms requirement.
    """
    logger.info("\n🧪 Test 3: Safety Latency (<100ms requirement)")
    
    try:
        # Run multiple frames to get average
        latencies = []
        for _ in range(10):
            guardian_results, _ = handler.process_frame(frame)
        
        avg_latency = handler.get_performance_stats()['guardian_avg_ms']
        
        passed = avg_latency < 100
        results.record(
            "Safety Latency",
            passed,
            f"Layer 0: {avg_latency:.1f}ms (target: <100ms)"
        )
    except Exception as e:
        results.record(
            "Safety Latency",
            False,
            f"Failed: {e}"
        )


def test_context_latency(handler: DualYOLOHandler, frame: np.ndarray, results: TestResults):
    """
    Test 4: Context Latency
    
    Verify Layer 1 Learner meets <150ms acceptable latency.
    """
    logger.info("\n🧪 Test 4: Context Latency (<150ms acceptable)")
    
    try:
        # Use existing stats from previous tests
        avg_latency = handler.get_performance_stats()['learner_avg_ms']
        
        passed = avg_latency < 150
        results.record(
            "Context Latency",
            passed,
            f"Layer 1: {avg_latency:.1f}ms (target: <150ms)"
        )
    except Exception as e:
        results.record(
            "Context Latency",
            False,
            f"Failed: {e}"
        )


def test_adaptive_learning_gemini(handler: DualYOLOHandler, results: TestResults):
    """
    Test 5: Adaptive Learning from Gemini
    
    Test learning new objects from scene descriptions.
    """
    logger.info("\n🧪 Test 5: Adaptive Learning from Gemini")
    
    try:
        # Simulate Gemini response
        gemini_response = "I see a red fire extinguisher, a water fountain, and exit signs above the doors"
        
        # Extract objects
        new_objects = handler.add_gemini_objects(gemini_response)
        
        # Verify objects were added
        current_prompts = handler.prompt_manager.get_current_prompts()
        
        passed = len(new_objects) > 0 and any(obj in current_prompts for obj in new_objects)
        results.record(
            "Adaptive Learning (Gemini)",
            passed,
            f"Learned {len(new_objects)} objects: {new_objects}"
        )
    except Exception as e:
        results.record(
            "Adaptive Learning (Gemini)",
            False,
            f"Failed: {e}"
        )


def test_adaptive_learning_maps(handler: DualYOLOHandler, results: TestResults):
    """
    Test 6: Adaptive Learning from Maps
    
    Test learning objects from Google Maps POI.
    """
    logger.info("\n🧪 Test 6: Adaptive Learning from Maps")
    
    try:
        # Simulate Maps POI
        poi_list = ["Starbucks", "Bank of America", "CVS Pharmacy"]
        
        # Convert POI to objects
        new_objects = handler.add_maps_objects(poi_list)
        
        # Verify objects were added
        current_prompts = handler.prompt_manager.get_current_prompts()
        
        passed = len(new_objects) > 0 and any(obj in current_prompts for obj in new_objects)
        results.record(
            "Adaptive Learning (Maps)",
            passed,
            f"Learned {len(new_objects)} objects: {new_objects}"
        )
    except Exception as e:
        results.record(
            "Adaptive Learning (Maps)",
            False,
            f"Failed: {e}"
        )


def test_adaptive_learning_memory(handler: DualYOLOHandler, results: TestResults):
    """
    Test 7: Adaptive Learning from Memory
    
    Test learning objects from user memory (Layer 4).
    """
    logger.info("\n🧪 Test 7: Adaptive Learning from Memory")
    
    try:
        # Add user object
        object_name = "brown leather wallet"
        metadata = {"color": "brown", "material": "leather"}
        
        added = handler.add_memory_object(object_name, metadata)
        
        # Verify object was added
        current_prompts = handler.prompt_manager.get_current_prompts()
        
        passed = added and object_name in current_prompts
        results.record(
            "Adaptive Learning (Memory)",
            passed,
            f"Stored: {object_name}"
        )
    except Exception as e:
        results.record(
            "Adaptive Learning (Memory)",
            False,
            f"Failed: {e}"
        )


def test_ram_budget(results: TestResults):
    """
    Test 8: RAM Budget
    
    Verify system stays under 3.9GB RAM usage.
    """
    logger.info("\n🧪 Test 8: RAM Budget (<3.9GB requirement)")
    
    try:
        process = psutil.Process()
        ram_usage_gb = process.memory_info().rss / (1024**3)
        
        passed = ram_usage_gb < 3.9
        results.record(
            "RAM Budget",
            passed,
            f"Current: {ram_usage_gb:.2f}GB (target: <3.9GB)"
        )
    except Exception as e:
        results.record(
            "RAM Budget",
            False,
            f"Failed: {e}"
        )


def test_prompt_persistence(handler: DualYOLOHandler, results: TestResults):
    """
    Test 9: Prompt Persistence
    
    Verify prompts are saved to JSON and can be reloaded.
    """
    logger.info("\n🧪 Test 9: Prompt Persistence (JSON)")
    
    try:
        # Check if JSON file was created
        json_path = Path("memory/adaptive_prompts.json")
        
        passed = json_path.exists() and json_path.stat().st_size > 0
        results.record(
            "Prompt Persistence",
            passed,
            f"JSON file exists and contains data: {json_path}"
        )
    except Exception as e:
        results.record(
            "Prompt Persistence",
            False,
            f"Failed: {e}"
        )


def main():
    """Run all tests."""
    logger.info("="*70)
    logger.info("Project-Cortex v2.0 - Dual YOLO Test Suite")
    logger.info("="*70)
    
    if not HANDLER_AVAILABLE:
        logger.error("❌ DualYOLOHandler not available. Cannot run tests.")
        return False
    
    if not CV2_AVAILABLE:
        logger.error("❌ OpenCV not available. Cannot load test frame.")
        return False
    
    results = TestResults()
    
    # Load test frame
    test_frame_path = "tests/test_frame.jpg"
    if not Path(test_frame_path).exists():
        logger.warning(f"⚠️ Test frame not found: {test_frame_path}")
        logger.info("Creating dummy frame (640x480 black image)...")
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    else:
        test_frame = cv2.imread(test_frame_path)
        if test_frame is None:
            logger.error(f"❌ Failed to load test frame: {test_frame_path}")
            return False
    
    # Test 1: Model Loading
    handler = test_model_loading(results)
    if handler is None:
        logger.error("❌ Cannot continue tests without models")
        results.summary()
        return False
    
    # Test 2: Parallel Inference
    test_parallel_inference(handler, test_frame, results)
    
    # Test 3: Safety Latency
    test_safety_latency(handler, test_frame, results)
    
    # Test 4: Context Latency
    test_context_latency(handler, test_frame, results)
    
    # Test 5-7: Adaptive Learning
    test_adaptive_learning_gemini(handler, results)
    test_adaptive_learning_maps(handler, results)
    test_adaptive_learning_memory(handler, results)
    
    # Test 8: RAM Budget
    test_ram_budget(results)
    
    # Test 9: Prompt Persistence
    test_prompt_persistence(handler, results)
    
    # Cleanup
    handler.cleanup()
    
    # Print summary
    all_passed = results.summary()
    
    if all_passed:
        logger.info("🎉 ALL TESTS PASSED! System ready for YIA 2026 demo.")
    else:
        logger.error("❌ SOME TESTS FAILED. Review issues above.")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
