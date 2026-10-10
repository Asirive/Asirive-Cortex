# YOLOE Three Modes - Quick Reference
**Project-Cortex v2.0 - Layer 1 Learner**

## 🎯 Three Detection Modes

### 1. PROMPT-FREE 🔍 "Show me everything"
```python
learner = YOLOELearner(
    model_path="models/yoloe-11l-seg-pf.pt",
    mode=YOLOEMode.PROMPT_FREE
)
detections = learner.detect(frame)  # 4585+ classes, zero setup!
```
- **Vocabulary:** 4,585+ classes (built-in)
- **Setup:** None required
- **Use Case:** General exploration, discovery
- **Best For:** "What objects do you see?"

### 2. TEXT PROMPTS 🧠 "Learn from conversation"
```python
learner = YOLOELearner(
    model_path="models/yoloe-11m-seg.pt",
    mode=YOLOEMode.TEXT_PROMPTS  # Default
)

# Learn from Gemini
learner.set_classes(["person", "fire extinguisher", "exit sign"])
detections = learner.detect(frame)
```
- **Vocabulary:** 15-100 classes (adaptive)
- **Setup:** Learns from Gemini/Maps/Memory
- **Use Case:** Contextual awareness
- **Best For:** "Describe the scene"

### 3. VISUAL PROMPTS 👁️ "Remember MY objects"
```python
learner = YOLOELearner(
    model_path="models/yoloe-11m-seg.pt",
    mode=YOLOEMode.VISUAL_PROMPTS
)

# User draws box around wallet
learner.set_visual_prompts(
    bboxes=np.array([[221, 405, 344, 857]]),
    cls=np.array([0]),
    reference_image=frame  # Permanent recognition
)
detections = learner.detect(new_frame)  # Finds user's specific wallet!
```
- **Vocabulary:** User-defined (mark objects)
- **Setup:** User draws bounding boxes
- **Use Case:** Personal object recognition
- **Best For:** "Find my wallet"

## 🔄 Dynamic Mode Switching
```python
# Adapt based on user intent
learner.switch_mode(YOLOEMode.PROMPT_FREE)    # "Show me everything"
learner.switch_mode(YOLOEMode.TEXT_PROMPTS)   # "Describe scene"
learner.switch_mode(YOLOEMode.VISUAL_PROMPTS) # "Remember this"
```

## 📊 Performance Comparison

| Mode | Classes | Latency | RAM | Setup |
|------|---------|---------|-----|-------|
| Prompt-Free | 4585+ | 90-130ms | 0.8GB | None ✅ |
| Text Prompts | 15-100 | 90-130ms | 0.9GB | <50ms |
| Visual Prompts | User | 100-150ms | 0.9GB | User draws boxes |

## 🏆 Innovation Impact

**First AI wearable with:**
1. ✅ 4585+ class discovery (no setup)
2. ✅ Real-time contextual learning
3. ✅ Personal object recognition

**No commercial wearable has this!** (OrCam, eSight, NuEyes)

## 📖 Full Documentation
See: `docs/implementation/YOLOE-THREE-MODES-GUIDE.md`

## 🧪 Run Demo
```bash
python tests/demo_three_modes.py
```

---
**Status:** ✅ IMPLEMENTED  
**Author:** Haziq (@IRSPlays) + GitHub Copilot  
**Date:** December 28, 2025
