"""
Test Router Priority Fix: Layer 2/3 keywords before Layer 1

This test validates the critical fix where "explain what you see" should route to Layer 2
(because "explain" is a Layer 2 priority keyword) instead of Layer 1 (which has "what you see").

The fix ensures more specific keywords (Layer 2/3) are checked BEFORE general keywords (Layer 1).
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.layer3_guide.router import IntentRouter

def test_router_priority_fix():
    """Test that Layer 2/3 keywords are checked before Layer 1."""
    router = IntentRouter()
    
    print("\n" + "="*70)
    print("🧪 ROUTER PRIORITY FIX VALIDATION")
    print("="*70)
    
    test_cases = [
        # Critical edge case: "explain" (L2) should override "what you see" (L1)
        ("explain what you see", "layer2", "🔥 CRITICAL: explain overrides what you see"),
        ("explain this scene", "layer2", "explain triggers L2"),
        ("explain what's happening", "layer2", "explain what's happening triggers L2"),
        
        # Layer 2 keywords without Layer 1 conflicts
        ("describe the scene", "layer2", "describe the scene triggers L2"),
        ("analyze this", "layer2", "analyze triggers L2"),
        ("read this text", "layer2", "read this triggers L2"),
        
        # Layer 1 keywords (should still work when no L2/L3 conflict)
        ("what do you see", "layer1", "what do you see triggers L1"),
        ("identify objects", "layer1", "identify triggers L1"),
        ("count the people", "layer1", "count triggers L1"),
        
        # Layer 3 keywords
        ("where am i", "layer3", "where am i triggers L3"),
        ("navigate to home", "layer3", "navigate triggers L3"),
        ("remember this wallet", "layer3", "remember this triggers L3"),
    ]
    
    passed = 0
    failed = 0
    
    for query, expected_layer, description in test_cases:
        actual_layer = router.route(query)
        status = "✅ PASS" if actual_layer == expected_layer else "❌ FAIL"
        
        if actual_layer == expected_layer:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} | {query:30s} → {actual_layer} (expected {expected_layer})")
        print(f"       {description}")
    
    print("\n" + "="*70)
    print(f"📊 RESULTS: {passed}/{len(test_cases)} passed ({passed/len(test_cases)*100:.1f}%)")
    print("="*70)
    
    if failed > 0:
        print(f"\n❌ {failed} test(s) FAILED")
        return False
    else:
        print(f"\n✅ All tests PASSED")
        return True

if __name__ == "__main__":
    success = test_router_priority_fix()
    sys.exit(0 if success else 1)
