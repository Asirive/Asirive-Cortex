"""
Test Router Fix - Verify Layer Routing Logic

This test validates that the IntentRouter correctly routes voice commands
to the appropriate layer using priority keywords and fuzzy matching.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - Router Fix Validation
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from layer3_guide.router import IntentRouter

def test_router():
    """Test router with Layer 1, 2, and 3 queries"""
    router = IntentRouter()
    
    print("=" * 80)
    print("🧪 ROUTER FIX VALIDATION TEST")
    print("=" * 80)
    
    # =========================================================================
    # TEST SUITE 1: Layer 1 Priority Keywords (Should ALL route to Layer 1)
    # =========================================================================
    print("\n🔵 TEST SUITE 1: Layer 1 Priority Keywords")
    print("-" * 80)
    
    layer1_tests = [
        "what do you see",
        "what u see",
        "what you see",
        "what can you see",
        "see",
        "look",
        "show me",
        "list objects",
        "what objects",
        "identify",
        "detect",
        "count",
        "how many",
        "what's in front",
        "what's ahead",
        "whats in front",
        "whats ahead"
    ]
    
    layer1_passed = 0
    layer1_failed = 0
    
    for query in layer1_tests:
        result = router.route(query)
        expected = "layer1"
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        if result == expected:
            layer1_passed += 1
        else:
            layer1_failed += 1
        
        print(f"{status} | Query: '{query}' → {result} (expected: {expected})")
    
    print(f"\n📊 Layer 1 Tests: {layer1_passed}/{len(layer1_tests)} passed ({layer1_failed} failed)")
    
    # =========================================================================
    # TEST SUITE 2: Layer 2 Queries (Deep analysis, OCR, reasoning)
    # =========================================================================
    print("\n🔵 TEST SUITE 2: Layer 2 Deep Analysis Queries")
    print("-" * 80)
    
    layer2_tests = [
        "describe the entire scene",
        "describe the room",
        "describe everything",
        "analyze the scene",
        "read this",
        "read text",
        "what does it say",
        "explain what's happening",
        "tell me about this scene",
        "is this safe to",
        "should i",
        "what kind of place"
    ]
    
    layer2_passed = 0
    layer2_failed = 0
    
    for query in layer2_tests:
        result = router.route(query)
        expected = "layer2"
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        if result == expected:
            layer2_passed += 1
        else:
            layer2_failed += 1
        
        print(f"{status} | Query: '{query}' → {result} (expected: {expected})")
    
    print(f"\n📊 Layer 2 Tests: {layer2_passed}/{len(layer2_tests)} passed ({layer2_failed} failed)")
    
    # =========================================================================
    # TEST SUITE 3: Layer 3 Queries (Navigation, Spatial Audio, Memory)
    # =========================================================================
    print("\n🔵 TEST SUITE 3: Layer 3 Navigation Queries")
    print("-" * 80)
    
    layer3_tests = [
        "where am i",
        "navigate to the store",
        "take me to the exit",
        "remember this object",
        "where is the door",
        "where's the person",
        "locate the chair",
        "guide me to the couch",
        "which direction is the table"
    ]
    
    layer3_passed = 0
    layer3_failed = 0
    
    for query in layer3_tests:
        result = router.route(query)
        expected = "layer3"
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        if result == expected:
            layer3_passed += 1
        else:
            layer3_failed += 1
        
        print(f"{status} | Query: '{query}' → {result} (expected: {expected})")
    
    print(f"\n📊 Layer 3 Tests: {layer3_passed}/{len(layer3_tests)} passed ({layer3_failed} failed)")
    
    # =========================================================================
    # TEST SUITE 4: Fuzzy Matching (Typos and variations)
    # =========================================================================
    print("\n🔵 TEST SUITE 4: Fuzzy Matching (Typos & Variations)")
    print("-" * 80)
    
    fuzzy_tests = [
        ("wat do u c", "layer1"),  # Extreme typo of "what do you see"
        ("wat u see", "layer1"),   # Typo of "what u see"
        ("discribe the room", "layer2"),  # Typo of "describe"
        ("reed text", "layer2"),   # Typo of "read text"
        ("wher am i", "layer3"),   # Typo of "where am i"
        ("navgate to store", "layer3"),  # Typo of "navigate"
    ]
    
    fuzzy_passed = 0
    fuzzy_failed = 0
    
    for query, expected in fuzzy_tests:
        result = router.route(query)
        status = "✅ PASS" if result == expected else "⚠️ FUZZY"
        
        if result == expected:
            fuzzy_passed += 1
        else:
            fuzzy_failed += 1
        
        print(f"{status} | Query: '{query}' → {result} (expected: {expected})")
    
    print(f"\n📊 Fuzzy Tests: {fuzzy_passed}/{len(fuzzy_tests)} passed ({fuzzy_failed} failed)")
    
    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    total_tests = len(layer1_tests) + len(layer2_tests) + len(layer3_tests) + len(fuzzy_tests)
    total_passed = layer1_passed + layer2_passed + layer3_passed + fuzzy_passed
    total_failed = layer1_failed + layer2_failed + layer3_failed + fuzzy_failed
    
    print("\n" + "=" * 80)
    print("📊 FINAL SUMMARY")
    print("=" * 80)
    print(f"Total Tests: {total_tests}")
    print(f"✅ Passed: {total_passed} ({total_passed/total_tests*100:.1f}%)")
    print(f"❌ Failed: {total_failed} ({total_failed/total_tests*100:.1f}%)")
    
    if total_failed == 0:
        print("\n🎉 ALL TESTS PASSED! Router is working correctly.")
    else:
        print(f"\n⚠️ {total_failed} TESTS FAILED! Router needs adjustment.")
        
        # Provide diagnostic info
        print("\n🔍 DIAGNOSTICS:")
        if layer1_failed > 0:
            print(f"   - Layer 1 failures: {layer1_failed} (priority keywords may not be working)")
        if layer2_failed > 0:
            print(f"   - Layer 2 failures: {layer2_failed} (fuzzy matching may be too aggressive)")
        if layer3_failed > 0:
            print(f"   - Layer 3 failures: {layer3_failed} (spatial audio patterns may be misrouted)")
        if fuzzy_failed > 0:
            print(f"   - Fuzzy matching failures: {fuzzy_failed} (threshold may be too high)")
    
    print("=" * 80)

if __name__ == "__main__":
    test_router()
