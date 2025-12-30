"""
Project-Cortex v2.0 - YOLOE Three Modes Demo

Demonstrates all three YOLOE detection modes:
1. Prompt-Free: 4585+ classes, zero setup
2. Text Prompts: Adaptive learning from text
3. Visual Prompts: Personal object recognition

Run this to verify the new mode system works correctly.

Author: Haziq (@IRSPlays)
Date: December 28, 2025
"""

import sys
from pathlib import Path
import numpy as np
import cv2

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from layer1_learner import YOLOELearner, YOLOEMode

def demo_prompt_free():
    """Demo Mode 1: Prompt-Free (4585+ classes)"""
    print("\n" + "="*70)
    print("DEMO 1: PROMPT-FREE MODE (Discovery)")
    print("="*70)
    
    print("\n📋 Loading model...")
    learner = YOLOELearner(
        model_path="models/yoloe-11m-seg.pt",
        device="cpu",
        mode=YOLOEMode.PROMPT_FREE
    )
    
    print("\n✅ Model loaded - NO SETUP REQUIRED!")
    print("   Available classes: 4585+ (built-in vocabulary)")
    
    # Load test frame
    frame = cv2.imread("tests/test_frame.jpg")
    if frame is None:
        print("⚠️ Test frame not found, skipping detection demo")
        return
    
    print("\n🔍 Running detection...")
    detections = learner.detect(frame)
    
    print(f"\n✅ Detection complete: {len(detections)} objects found")
    for det in detections[:5]:  # Show first 5
        print(f"   {det['class']}: {det['confidence']:.2f} (source: {det['source']})")
    
    print("\n💡 Use Case: 'Show me everything around me'")
    learner.cleanup()


def demo_text_prompts():
    """Demo Mode 2: Text Prompts (Adaptive Learning)"""
    print("\n" + "="*70)
    print("DEMO 2: TEXT PROMPTS MODE (Contextual Learning)")
    print("="*70)
    
    print("\n📋 Loading model...")
    learner = YOLOELearner(
        model_path="models/yoloe-11m-seg.pt",
        device="cpu",
        mode=YOLOEMode.TEXT_PROMPTS
    )
    
    print("\n✅ Model loaded with BASE vocabulary")
    print(f"   Initial classes: {len(learner.get_classes())}")
    print(f"   Classes: {learner.get_classes()[:5]}...")
    
    # Simulate learning from Gemini
    print("\n🧠 Simulating Gemini response...")
    print("   User: 'Describe what you see'")
    print("   Gemini: 'I see a fire extinguisher, water fountain, and exit signs'")
    
    # Extract and add new objects
    new_objects = ["fire extinguisher", "water fountain", "exit sign"]
    print(f"\n📝 Learning new objects: {new_objects}")
    
    current_classes = learner.get_classes()
    learner.set_classes(current_classes + new_objects)
    
    print(f"\n✅ Vocabulary updated!")
    print(f"   Total classes: {len(learner.get_classes())}")
    
    # Load test frame
    frame = cv2.imread("tests/test_frame.jpg")
    if frame is None:
        print("⚠️ Test frame not found, skipping detection demo")
        return
    
    print("\n🔍 Running detection with updated vocabulary...")
    detections = learner.detect(frame)
    
    print(f"\n✅ Detection complete: {len(detections)} objects found")
    for det in detections[:5]:
        print(f"   {det['class']}: {det['confidence']:.2f} (source: {det['source']})")
    
    print("\n💡 Use Case: 'Describe the scene' (learns from conversation)")
    learner.cleanup()


def demo_visual_prompts():
    """Demo Mode 3: Visual Prompts (Personal Objects)"""
    print("\n" + "="*70)
    print("DEMO 3: VISUAL PROMPTS MODE (Personal Object Recognition)")
    print("="*70)
    
    print("\n📋 Loading model...")
    learner = YOLOELearner(
        model_path="models/yoloe-11m-seg.pt",
        device="cpu",
        mode=YOLOEMode.VISUAL_PROMPTS
    )
    
    print("\n✅ Model loaded - Ready for visual prompts")
    
    # Load test frame
    frame = cv2.imread("tests/test_frame.jpg")
    if frame is None:
        print("⚠️ Test frame not found, skipping demo")
        return
    
    print("\n👁️ Simulating user marking objects...")
    print("   User draws box around wallet: [221, 405, 344, 857]")
    print("   User draws box around glasses: [120, 425, 160, 445]")
    
    # Create visual prompts (simulated bounding boxes)
    visual_prompts = {
        "bboxes": np.array([
            [221, 405, 344, 857],  # Wallet
            [120, 425, 160, 445]   # Glasses
        ]),
        "cls": np.array([0, 1])
    }
    
    print("\n📝 Setting visual prompts WITHOUT reference image...")
    print("   (One-time detection in current frame)")
    learner.set_visual_prompts(
        bboxes=visual_prompts["bboxes"],
        cls=visual_prompts["cls"]
    )
    
    print("\n🔍 Running detection with visual prompts...")
    detections = learner.detect(frame)
    
    print(f"\n✅ Detection complete: {len(detections)} objects found")
    for det in detections[:5]:
        print(f"   {det['class']}: {det['confidence']:.2f} (source: {det['source']})")
    
    print("\n💡 Use Case 1: 'What's in this area?' (one-time, no reference)")
    
    # Now with reference image
    print("\n" + "-"*70)
    print("🔄 Now with REFERENCE IMAGE (permanent prompts)...")
    learner.set_visual_prompts(
        bboxes=visual_prompts["bboxes"],
        cls=visual_prompts["cls"],
        reference_image=frame  # Store visual signature
    )
    
    print("\n✅ Visual prompts stored permanently")
    print("   Future frames will search for these specific objects")
    print("\n💡 Use Case 2: 'Remember my wallet' (persistent recognition)")
    
    learner.cleanup()


def demo_mode_switching():
    """Demo: Dynamic Mode Switching"""
    print("\n" + "="*70)
    print("DEMO 4: DYNAMIC MODE SWITCHING")
    print("="*70)
    
    print("\n📋 Starting in TEXT_PROMPTS mode...")
    learner = YOLOELearner(
        model_path="models/yoloe-11m-seg.pt",
        device="cpu",
        mode=YOLOEMode.TEXT_PROMPTS
    )
    
    print(f"✅ Current mode: {learner.mode.value}")
    
    # Switch to prompt-free
    print("\n🔄 User: 'Show me everything around me'")
    print("   → Switching to PROMPT_FREE mode...")
    learner.switch_mode(YOLOEMode.PROMPT_FREE)
    print(f"✅ Current mode: {learner.mode.value}")
    
    # Switch to visual prompts
    print("\n🔄 User: 'Remember this wallet' (draws box)")
    print("   → Switching to VISUAL_PROMPTS mode...")
    learner.switch_mode(YOLOEMode.VISUAL_PROMPTS)
    print(f"✅ Current mode: {learner.mode.value}")
    
    # Switch back to text prompts
    print("\n🔄 User: 'Describe what you see'")
    print("   → Switching back to TEXT_PROMPTS mode...")
    learner.switch_mode(YOLOEMode.TEXT_PROMPTS)
    print(f"✅ Current mode: {learner.mode.value}")
    
    print("\n💡 System adapts mode based on user intent!")
    learner.cleanup()


if __name__ == "__main__":
    print("\n" + "="*70)
    print("PROJECT-CORTEX v2.0 - YOLOE THREE MODES DEMO")
    print("="*70)
    print("\nThis demo showcases the new three-mode detection system:")
    print("1. Prompt-Free: 4585+ classes, zero setup")
    print("2. Text Prompts: Learn from conversation (Gemini/Maps/Memory)")
    print("3. Visual Prompts: Recognize user's specific objects")
    
    try:
        # Run all demos
        demo_prompt_free()
        demo_text_prompts()
        demo_visual_prompts()
        demo_mode_switching()
        
        print("\n" + "="*70)
        print("✅ ALL DEMOS COMPLETE")
        print("="*70)
        print("\n📖 See docs/implementation/YOLOE-THREE-MODES-GUIDE.md for details")
        print("\n🏆 Project-Cortex is now the FIRST AI wearable with:")
        print("   1. 4585+ class discovery (no setup)")
        print("   2. Real-time contextual learning")
        print("   3. Personal object recognition")
        print("\n💡 No commercial wearable has this flexibility!")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
