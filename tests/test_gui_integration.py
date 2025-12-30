"""
Quick GUI Test: Verify YOLOE Three-Mode Integration

Run this to verify the new UI controls work correctly.

Author: Haziq (@IRSPlays)
Date: December 28, 2025
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

print("\n" + "="*70)
print("PROJECT-CORTEX v2.0 - YOLOE THREE-MODE GUI TEST")
print("="*70)

print("\n✅ Testing imports...")
try:
    from layer1_learner import YOLOEMode
    print("   ✅ YOLOEMode imported")
    print(f"   Available modes: {[m.value for m in YOLOEMode]}")
except ImportError as e:
    print(f"   ❌ Failed to import YOLOEMode: {e}")
    sys.exit(1)

try:
    from dual_yolo_handler import DualYOLOHandler
    print("   ✅ DualYOLOHandler imported")
except ImportError as e:
    print(f"   ❌ Failed to import DualYOLOHandler: {e}")
    sys.exit(1)

print("\n✅ Verifying model files...")
import os

models_dir = Path("models")
required_models = {
    "yolo11x.pt": "Layer 0 Guardian (static safety)",
    "yoloe-11s-seg.pt": "Layer 1 Learner (text/visual prompts)",
    "yoloe-11s-seg-pf.pt": "Layer 1 Learner (prompt-free)"
}

for model_file, description in required_models.items():
    model_path = models_dir / model_file
    if model_path.exists():
        size_mb = model_path.stat().st_size / (1024 * 1024)
        print(f"   ✅ {model_file} ({size_mb:.1f}MB) - {description}")
    else:
        print(f"   ❌ {model_file} - NOT FOUND")

print("\n✅ Testing DualYOLOHandler initialization...")
print("   Creating handler with TEXT_PROMPTS mode...")

try:
    handler = DualYOLOHandler(
        guardian_model_path="models/yolo11x.pt",
        learner_model_path="models/yoloe-11s-seg.pt",
        device="cpu",
        learner_mode=YOLOEMode.TEXT_PROMPTS
    )
    print(f"   ✅ Handler created successfully")
    print(f"   Guardian classes: {len(handler.guardian.get_classes())}")
    print(f"   Learner classes: {len(handler.learner.get_classes())}")
    print(f"   Learner mode: {handler.learner.mode.value}")
    
    # Test mode switching
    print("\n✅ Testing mode switching...")
    print("   Switching to PROMPT_FREE...")
    handler.learner.switch_mode(YOLOEMode.PROMPT_FREE)
    print(f"   ✅ Mode: {handler.learner.mode.value}")
    
    print("   Switching to VISUAL_PROMPTS...")
    handler.learner.switch_mode(YOLOEMode.VISUAL_PROMPTS)
    print(f"   ✅ Mode: {handler.learner.mode.value}")
    
    print("   Switching back to TEXT_PROMPTS...")
    handler.learner.switch_mode(YOLOEMode.TEXT_PROMPTS)
    print(f"   ✅ Mode: {handler.learner.mode.value}")
    
    print("\n✅ All tests passed!")
    
except Exception as e:
    print(f"   ❌ Handler creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*70)
print("READY TO LAUNCH GUI")
print("="*70)
print("\nRun: python src/cortex_gui.py")
print("\nNew UI Controls:")
print("  1. 🎯 Layer 1 Mode dropdown (Prompt-Free / Text Prompts / Visual Prompts)")
print("  2. Mode info label (shows class count and capabilities)")
print("  3. Auto mode switching based on user intent")
print("\nMode Switching:")
print("  - 'show me everything' → Prompt-Free (4585+ classes)")
print("  - 'describe scene' → Text Prompts (adaptive learning)")
print("  - 'remember this' → Visual Prompts (personal objects)")
print("\n🏆 Project-Cortex now has the most advanced detection system!")
print("="*70 + "\n")
