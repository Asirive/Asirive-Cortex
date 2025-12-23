"""
Project-Cortex Memory Storage System - Test Script

Tests the memory storage functionality with voice commands:
- "Remember this wallet"
- "Where is my keys?"
- "What do you remember?"

Author: Haziq (@IRSPlays) + AI CTO
Date: December 19, 2025
"""

import sys
from pathlib import Path
import logging

# Add server directory to path
sys.path.append(str(Path(__file__).parent.parent / "server"))

from memory_storage import get_memory_storage
from io import BytesIO
from PIL import Image
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_test_image(text: str) -> bytes:
    """Create a simple test image with text."""
    img = Image.new('RGB', (640, 480), color=(73, 109, 137))
    
    # Save to bytes
    buffer = BytesIO()
    img.save(buffer, format='JPEG', quality=95)
    return buffer.getvalue()

def test_store_memory():
    """Test storing a memory."""
    print("\n" + "="*60)
    print("TEST 1: Store Memory (Remember this wallet)")
    print("="*60)
    
    storage = get_memory_storage()
    
    # Create test image
    image_data = create_test_image("Wallet Image")
    
    # Store memory
    detections = {
        "detections": "wallet (0.92), keys (0.78)",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    success, memory_id, message = storage.store_memory(
        object_name="wallet",
        image_data=image_data,
        detections=detections,
        metadata={"query": "remember this wallet"},
        location_estimate="on the desk"
    )
    
    if success:
        print(f"✅ SUCCESS: {message}")
        print(f"   Memory ID: {memory_id}")
    else:
        print(f"❌ FAILED: {message}")
    
    return success

def test_recall_memory():
    """Test recalling a memory."""
    print("\n" + "="*60)
    print("TEST 2: Recall Memory (Where is my wallet?)")
    print("="*60)
    
    storage = get_memory_storage()
    
    # Recall memory
    memory_data = storage.recall_memory("wallet")
    
    if memory_data:
        print(f"✅ SUCCESS: Memory found!")
        print(f"   Memory ID: {memory_data['memory_id']}")
        print(f"   Object: {memory_data['object_name']}")
        print(f"   Timestamp: {memory_data['timestamp']}")
        print(f"   Location: {memory_data['location_estimate']}")
        print(f"   Detections: {memory_data['detections']}")
        return True
    else:
        print(f"❌ FAILED: Memory not found")
        return False

def test_list_memories():
    """Test listing all memories."""
    print("\n" + "="*60)
    print("TEST 3: List All Memories (What do you remember?)")
    print("="*60)
    
    storage = get_memory_storage()
    
    # List all memories
    memories = storage.list_memories()
    
    if memories:
        print(f"✅ SUCCESS: Found {len(memories)} memory groups")
        for mem in memories:
            print(f"   - {mem['object_name']}: {mem['count']} items, last seen {mem['last_seen']}")
        return True
    else:
        print(f"⚠️  No memories stored yet")
        return False

def test_store_multiple():
    """Test storing multiple objects."""
    print("\n" + "="*60)
    print("TEST 4: Store Multiple Objects")
    print("="*60)
    
    storage = get_memory_storage()
    objects = ["keys", "phone", "glasses"]
    
    for obj in objects:
        image_data = create_test_image(f"{obj.capitalize()} Image")
        detections = {
            "detections": f"{obj} (0.95)",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        success, memory_id, message = storage.store_memory(
            object_name=obj,
            image_data=image_data,
            detections=detections,
            metadata={"query": f"remember this {obj}"}
        )
        
        if success:
            print(f"✅ Stored: {memory_id}")
        else:
            print(f"❌ Failed: {obj} - {message}")
            return False
    
    return True

def run_all_tests():
    """Run all memory storage tests."""
    print("\n" + "🧪 " * 30)
    print("PROJECT-CORTEX MEMORY STORAGE TEST SUITE")
    print("🧪 " * 30)
    
    tests = [
        ("Store Memory", test_store_memory),
        ("Recall Memory", test_recall_memory),
        ("List Memories", test_list_memories),
        ("Store Multiple", test_store_multiple),
        ("List After Multiple", test_list_memories)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            if result:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ EXCEPTION in {test_name}: {e}")
            logger.exception(f"Test failed: {test_name}")
            failed += 1
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"✅ Passed: {passed}/{len(tests)}")
    print(f"❌ Failed: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! Memory system is working!")
    else:
        print(f"\n⚠️  {failed} test(s) failed. Check logs above.")
    
    print("="*60)

if __name__ == "__main__":
    run_all_tests()
