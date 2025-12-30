# GUI Testing Workflow for 3-Mode YOLOE Architecture

**Version:** 2.0  
**Author:** Haziq (@IRSPlays)  
**Date:** December 29, 2025  
**Project:** Project-Cortex - YIA 2026  
**Status:** Phase 3 Implementation Complete

---

## 🎯 TESTING OBJECTIVES

This document outlines comprehensive GUI testing procedures for the **3-Mode YOLOE Learner** architecture. We validate:

1. **Adaptive Learning (Layer 2→Layer 1)**: Gemini teaches Layer 1 new objects
2. **Visual Prompts (Remember→Recall)**: Personal object tracking with cross-session persistence
3. **Mode Switching Intelligence**: Automatic mode selection based on query intent
4. **Cross-Session Persistence**: Visual prompts survive app restarts
5. **Confidence Validation**: Detection quality metrics per mode

---

## 📊 3-MODE ARCHITECTURE OVERVIEW

### **MODE 1: PROMPT-FREE (Discovery Mode)** 🔍
- **Trigger Patterns:** "show me everything", "scan area", "describe scene"
- **Vocabulary:** 4585+ built-in classes (no setup)
- **Expected Confidence:** 0.3-0.6 (zero-shot detection)
- **Latency:** 122ms (same as other modes)
- **Use Case:** General exploration, discovering unknown objects

### **MODE 2: TEXT PROMPTS (Contextual Learning)** 🧠
- **Trigger Patterns:** "what do you see", "identify this", "is there a"
- **Vocabulary:** 15-100 adaptive classes (Gemini/Maps/Memory learned)
- **Expected Confidence:** 0.7-0.9 (context-aware)
- **Latency:** 122ms + ~50ms mode switch overhead
- **Use Case:** Targeted object identification with learned vocabulary

### **MODE 3: VISUAL PROMPTS (Personal Objects)** 👁️
- **Trigger Patterns:** "where's my wallet", "find my keys"
- **Vocabulary:** User-marked personal items (bounding boxes)
- **Expected Confidence:** 0.6-0.95 (highest accuracy)
- **Latency:** 122ms + ~50ms mode switch + <50ms .npz loading
- **Use Case:** Personalized item tracking with SLAM coordinates

---

## 🧪 TEST SUITE

### **TEST 1: ADAPTIVE LEARNING (Layer 2→Layer 1 Integration)**

**Objective:** Validate that Gemini can teach Layer 1 new objects without retraining.

#### **Prerequisites:**
- Clean `memory/adaptive_prompts.json` (backup existing file)
- Camera pointed at unique objects (e.g., fire extinguisher, yellow dumbbell)
- Layer 2 (Gemini 2.5 Flash) API key configured

#### **Test Steps:**
1. **Launch Application:**
   ```powershell
   python src/cortex_gui.py
   ```
   - Wait for initialization (check logs for "✅ Layer 1 Learner initialized")

2. **Trigger Layer 2 Analysis:**
   - Say (or type): **"explain what you see"**
   - **Expected Behavior:**
     - Router logs: `🎯 Layer 2 priority keyword found: 'explain' → Forcing Layer 2`
     - Layer 2 processes frame with Gemini Live API
     - Gemini describes scene including unique objects
     - Layer 2 extracts nouns from Gemini response

3. **Verify Noun Extraction:**
   - Check logs for:
     ```
     🧠 [LAYER 2] Learned new classes: ['fire extinguisher', 'yellow dumbbell', 'water bottle']
     📝 [ADAPTIVE] Saved 3 new classes to adaptive_prompts.json
     ```
   - Open `memory/adaptive_prompts.json` and verify new classes added

4. **Test Layer 1 with New Vocabulary:**
   - Say (or type): **"what do you see"**
   - **Expected Behavior:**
     - Router logs: `🎯 [MODE DETECTION] Learning query detected: 'what' → TEXT_PROMPTS`
     - Mode switch logs: `🔄 [MODE SWITCH] PROMPT_FREE → TEXT_PROMPTS`
     - Layer 1 loads adaptive vocabulary from `adaptive_prompts.json`
     - Layer 1 detects objects using TEXT_PROMPTS mode

5. **Validate Detection:**
   - Check logs for:
     ```
     🎯 [LAYER 1] Detected 3 objects in 122.5ms (mode=text_prompts, avg_conf=0.82)
        Detections: fire extinguisher (0.87), yellow dumbbell (0.79), water bottle (0.81)
     ```
   - Response text should mention fire extinguisher and yellow dumbbell

#### **Success Criteria:**
- ✅ Gemini noun extraction logs appear
- ✅ `adaptive_prompts.json` contains new classes
- ✅ Layer 1 detects new objects with confidence >0.7
- ✅ Total workflow <3 seconds (Layer 2: ~2s, Layer 1: ~0.2s)

#### **Expected Logs (Sample):**
```
[2025-12-29 14:32:15] 🎯 [ROUTER] explain what you see → layer2
[2025-12-29 14:32:16] 🧠 [LAYER 2] Gemini analyzing scene...
[2025-12-29 14:32:17] 🧠 [LAYER 2] Learned new classes: ['fire extinguisher', 'yellow dumbbell']
[2025-12-29 14:32:17] 📝 [ADAPTIVE] Saved 2 new classes to adaptive_prompts.json
[2025-12-29 14:32:18] 🎯 [MODE DETECTION] Learning query detected: 'what' → TEXT_PROMPTS
[2025-12-29 14:32:18] 🔄 [MODE SWITCH] PROMPT_FREE → TEXT_PROMPTS
[2025-12-29 14:32:18] 🎯 [LAYER 1] Detected 2 objects in 125.3ms (mode=text_prompts, avg_conf=0.83)
[2025-12-29 14:32:18]    Detections: fire extinguisher (0.87), yellow dumbbell (0.79)
```

---

### **TEST 2: VISUAL PROMPTS (Remember→Recall)**

**Objective:** Validate personal object tracking with visual embeddings and SLAM coordinates.

#### **Prerequisites:**
- Unique personal item (e.g., specific wallet, keys, glasses)
- Camera pointed at item with clear view
- Layer 4 (Memory Storage) database initialized

#### **Test Steps:**

##### **Phase A: REMEMBER (Save Visual Prompt)**

1. **Position Object in Frame:**
   - Hold wallet/keys in camera view
   - Ensure good lighting and clear bounding box possible

2. **Trigger Memory Storage:**
   - Say (or type): **"remember this wallet"**
   - **Expected Behavior:**
     - System captures current frame
     - GUI shows bounding box drawing interface (if implemented)
     - User draws bounding box around wallet
     - System extracts visual embedding via `YOLOEVPSegPredictor`

3. **Verify Storage:**
   - Check logs for:
     ```
     💾 [VISUAL PROMPT] Saving visual prompt for 'wallet'
     💾 [VISUAL PROMPT] Bounding box: [[x1, y1, x2, y2]]
     💾 [VISUAL PROMPT] Visual embedding saved: memory_storage/wallet_001/visual_embedding.npz
     💾 [VISUAL PROMPT] SLAM coordinates: [0.0, 0.0, 0.0] (placeholder)
     ✅ [LAYER 4] Memory 'wallet_001' saved to database
     ```
   - Check filesystem:
     - `memory_storage/wallet_001/visual_embedding.npz` exists (~15KB)
     - `memory_storage/wallet_001/visual_prompt.json` contains bbox

4. **Verify Database Entry:**
   - Query `memories.db`:
     ```sql
     SELECT memory_id, object_name, visual_embedding_path, slam_coordinates 
     FROM memories WHERE object_name = 'wallet';
     ```
   - Expected result: `wallet_001`, path to .npz, SLAM coords

##### **Phase B: RECALL (Load Visual Prompt)**

5. **Move Object (Optional):**
   - Physically move wallet to different location
   - Or close/restart app for cross-session test

6. **Trigger Recall Query:**
   - Say (or type): **"where's my wallet"**
   - **Expected Behavior:**
     - Router logs: `🎯 [MODE DETECTION] Personal query detected: 'where's my' → VISUAL_PROMPTS`
     - Mode switch logs: `🔄 [MODE SWITCH] TEXT_PROMPTS → VISUAL_PROMPTS`
     - System extracts object name: "wallet"
     - System queries Layer 4 for `wallet_001` memory
     - Loads visual embedding from `.npz` file
     - Layer 1 detects wallet using visual prompts

7. **Validate Detection:**
   - Check logs for:
     ```
     🔍 [MEMORY] Searching for: wallet (id: wallet_001)
     🔄 [MODE SWITCH] TEXT_PROMPTS → VISUAL_PROMPTS
        Loading visual prompts for memory_id: wallet_001
     📂 [VISUAL PROMPT] Loaded visual prompt: wallet_001
     🎯 [LAYER 1] Detected 1 objects in 126.8ms (mode=visual_prompts, avg_conf=0.89)
        Detections: wallet (0.89)
     ```
   - Response text should say: "I can see your wallet right now."

#### **Success Criteria:**
- ✅ Visual embedding `.npz` file created (~15KB)
- ✅ Database entry contains `visual_embedding_path` and `slam_coordinates`
- ✅ Recall query switches to VISUAL_PROMPTS mode
- ✅ Wallet detected with confidence >0.8
- ✅ Mode switch latency <50ms
- ✅ Visual prompt loading <50ms

#### **Expected Logs (Sample):**
```
[2025-12-29 14:45:10] 💾 [VISUAL PROMPT] Saving visual prompt for 'wallet'
[2025-12-29 14:45:10] 💾 [VISUAL PROMPT] Bounding box: [[150, 200, 300, 450]]
[2025-12-29 14:45:11] 💾 [VISUAL PROMPT] Visual embedding saved: memory_storage/wallet_001/visual_embedding.npz
[2025-12-29 14:45:11] ✅ [LAYER 4] Memory 'wallet_001' saved to database
[2025-12-29 14:46:00] 🔍 [MEMORY] Searching for: wallet (id: wallet_001)
[2025-12-29 14:46:00] 🔄 [MODE SWITCH] TEXT_PROMPTS → VISUAL_PROMPTS (completed in 42.3ms)
[2025-12-29 14:46:00] 📂 [VISUAL PROMPT] Loaded visual prompt: wallet_001 (<50ms)
[2025-12-29 14:46:00] 🎯 [LAYER 1] Detected 1 objects in 128.1ms (mode=visual_prompts, avg_conf=0.91)
[2025-12-29 14:46:00]    Detections: wallet (0.91)
```

---

### **TEST 3: MODE SWITCHING VALIDATION**

**Objective:** Validate intelligent mode detection and zero-overhead switching.

#### **Test Sequence:**

| **Step** | **Query** | **Expected Mode** | **Confidence Range** | **Latency Target** |
|----------|-----------|-------------------|----------------------|--------------------|
| 1 | "what do you see" | TEXT_PROMPTS | 0.7-0.9 | <150ms |
| 2 | "scan everything" | PROMPT_FREE | 0.3-0.6 | <150ms |
| 3 | "where's my keys" | VISUAL_PROMPTS | 0.6-0.95 | <200ms |
| 4 | "identify this" | TEXT_PROMPTS | 0.7-0.9 | <150ms |

#### **Validation Points:**
1. **Mode Detection Accuracy:**
   - Each query triggers correct mode (check router logs)
   
2. **Mode Switch Latency:**
   - All mode switches <50ms (check `[MODE SWITCH] completed in X ms`)
   - Log WARNING if any switch >50ms

3. **RAM Stability:**
   - Monitor RAM during all switches
   - Should stay constant (~3.5GB) - no memory leaks

4. **Confidence Validation:**
   - Prompt-Free detections: avg_conf ≈ 0.4-0.5
   - Text Prompts detections: avg_conf ≈ 0.7-0.8
   - Visual Prompts detections: avg_conf ≈ 0.8-0.9

#### **Success Criteria:**
- ✅ All 4 queries route to correct mode
- ✅ Mode switch overhead <50ms (average)
- ✅ No RAM increase during switches
- ✅ Confidence ranges match expected values

---

### **TEST 4: CROSS-SESSION PERSISTENCE**

**Objective:** Validate that visual prompts survive app restarts (cold-start test).

#### **Test Steps:**

1. **Save Visual Prompt:**
   - Follow TEST 2 Phase A to save "glasses" visual prompt

2. **Verify Persistence:**
   - Close application completely
   - Check filesystem: `memory_storage/glasses_001/` exists
   - Check database: `memories.db` contains `glasses_001` entry

3. **Cold Start Test:**
   - Restart application: `python src/cortex_gui.py`
   - Wait for full initialization

4. **Test Recall (Cold):**
   - Say: **"where's my glasses"**
   - **Expected Behavior:**
     - System queries database for `glasses_001`
     - Loads `.npz` file from disk
     - Switches to VISUAL_PROMPTS mode
     - Detects glasses using loaded visual prompt

5. **Validate Performance:**
   - First recall (cold): <200ms (includes disk I/O)
   - Subsequent recalls (warm): <150ms (cached)

#### **Success Criteria:**
- ✅ Visual prompts loaded from database on app restart
- ✅ Glasses detected after cold start
- ✅ Cold-start detection latency <200ms
- ✅ No errors loading .npz files

---

### **TEST 5: CONFIDENCE THRESHOLD VALIDATION**

**Objective:** Statistical validation of detection confidence across all modes.

#### **Data Collection:**

Run 100 frames of detection across all 3 modes (33 frames per mode):

1. **Prompt-Free Mode:**
   - Run: "scan everything" 33 times
   - Log all confidence scores

2. **Text Prompts Mode:**
   - Run: "what do you see" 33 times
   - Log all confidence scores

3. **Visual Prompts Mode:**
   - Run: "where's my [object]" 34 times (3 different objects)
   - Log all confidence scores

#### **Analysis:**

Extract confidence distributions:

```python
# From logs: "[LAYER 1] Detected X objects (avg_conf=Y.ZZ)"
prompt_free_confs = [0.45, 0.38, 0.52, ...]  # 33 samples
text_prompts_confs = [0.78, 0.81, 0.74, ...]  # 33 samples
visual_prompts_confs = [0.87, 0.92, 0.85, ...]  # 34 samples

# Validate ranges
assert 0.3 <= mean(prompt_free_confs) <= 0.6
assert 0.7 <= mean(text_prompts_confs) <= 0.9
assert 0.6 <= mean(visual_prompts_confs) <= 0.95
```

#### **Success Criteria:**
- ✅ Prompt-Free: Mean confidence 0.4-0.5 (±0.15 std dev)
- ✅ Text Prompts: Mean confidence 0.75-0.85 (±0.10 std dev)
- ✅ Visual Prompts: Mean confidence 0.85-0.90 (±0.08 std dev)
- ✅ No detections with confidence <0.25 (quality threshold)

---

## 📋 DEBUG LOG CHECKLIST

### **Essential Logs to Monitor:**

#### **Mode Detection (Router):**
```
🎯 [MODE DETECTION] Personal query detected: 'where's my' → VISUAL_PROMPTS
🎯 [MODE DETECTION] Discovery query detected: 'scan' → PROMPT_FREE
🎯 [MODE DETECTION] Learning query detected: 'what' → TEXT_PROMPTS
```

#### **Mode Switching (YOLOELearner):**
```
🔄 [MODE SWITCH] TEXT_PROMPTS → VISUAL_PROMPTS
   Loading visual prompts for memory_id: wallet_001
✅ [MODE SWITCH] Mode switch completed in 42.3ms
⚠️ [PERFORMANCE] Mode switch exceeded 50ms target (67.8ms)
```

#### **Confidence Validation (YOLOELearner):**
```
   Detected: fire extinguisher (conf=0.870, mode=text_prompts)
⚠️ Low confidence in Text Prompts mode: unknown_object (0.420) - Expected: 0.7-0.9
```

#### **Performance Metrics (YOLOELearner):**
```
🎯 [LAYER 1] Detected 3 objects in 122.5ms (mode=text_prompts, avg_conf=0.82)
   Detections: person (0.85), car (0.79), phone (0.82)
```

#### **Adaptive Learning (Layer 2):**
```
🧠 [LAYER 2] Learned new classes: ['fire extinguisher', 'yellow dumbbell']
📝 [ADAPTIVE] Saved 2 new classes to adaptive_prompts.json
```

#### **Visual Prompts (VisualPromptManager):**
```
💾 [VISUAL PROMPT] Saving visual prompt for 'wallet'
💾 [VISUAL PROMPT] Visual embedding saved: memory_storage/wallet_001/visual_embedding.npz
📂 [VISUAL PROMPT] Loaded visual prompt: wallet_001 (<50ms)
```

---

## 🚨 COMMON ISSUES & TROUBLESHOOTING

### **Issue 1: Mode Switch >50ms**
**Symptom:** Log shows `⚠️ [PERFORMANCE] Mode switch exceeded 50ms target`

**Causes:**
- Disk I/O bottleneck (loading .npz files)
- Text embedding generation lag
- Model not cached properly

**Solutions:**
1. Use SSD for `memory_storage/` directory
2. Pre-cache visual embeddings on startup
3. Optimize `get_text_pe()` call (batch processing)

---

### **Issue 2: Low Confidence in Text Prompts Mode**
**Symptom:** `⚠️ Low confidence in Text Prompts mode: X (0.45) - Expected: 0.7-0.9`

**Causes:**
- Object not in adaptive vocabulary
- Poor lighting/blurry frame
- Object too small/far

**Solutions:**
1. Run "explain what you see" to teach Gemini about object
2. Check if object in `adaptive_prompts.json`
3. Improve camera angle/lighting

---

### **Issue 3: Visual Prompts Not Loading**
**Symptom:** `❌ [MODE SWITCH] Failed to load visual prompts: FileNotFoundError`

**Causes:**
- .npz file deleted/corrupted
- Database entry missing `visual_embedding_path`
- Memory ID mismatch

**Solutions:**
1. Check if `memory_storage/[object]_001/visual_embedding.npz` exists
2. Query database: `SELECT * FROM memories WHERE memory_id = 'wallet_001';`
3. Re-run "remember this wallet" to regenerate

---

### **Issue 4: Mode Detection Wrong**
**Symptom:** "scan everything" → TEXT_PROMPTS instead of PROMPT_FREE

**Causes:**
- Router pattern matching failed
- Query preprocessing removed keyword
- Default mode fallback triggered

**Solutions:**
1. Check router logs: `🎯 [MODE DETECTION] ...`
2. Add missing patterns to `discovery_patterns` list
3. Verify query normalization (lowercase, strip)

---

## 📊 PERFORMANCE BENCHMARKS (Target vs Actual)

| **Metric** | **Target** | **Measured** | **Status** |
|------------|------------|--------------|------------|
| **RAM Usage (Total)** | <3.9GB | TBD | ⏳ |
| **Layer 1 Latency (Prompt-Free)** | <150ms | TBD | ⏳ |
| **Layer 1 Latency (Text Prompts)** | <150ms | TBD | ⏳ |
| **Layer 1 Latency (Visual Prompts)** | <200ms | TBD | ⏳ |
| **Mode Switch Overhead** | <50ms | TBD | ⏳ |
| **Visual Prompt Loading** | <50ms | TBD | ⏳ |
| **Confidence (Prompt-Free)** | 0.3-0.6 | TBD | ⏳ |
| **Confidence (Text Prompts)** | 0.7-0.9 | TBD | ⏳ |
| **Confidence (Visual Prompts)** | 0.6-0.95 | TBD | ⏳ |

*(Update after testing)*

---

## ✅ TEST COMPLETION CHECKLIST

- [ ] TEST 1: Adaptive Learning (Layer 2→Layer 1)
- [ ] TEST 2: Visual Prompts (Remember→Recall)
- [ ] TEST 3: Mode Switching Validation
- [ ] TEST 4: Cross-Session Persistence
- [ ] TEST 5: Confidence Threshold Validation
- [ ] Performance validation and optimization
- [ ] Create test results summary report

---

## 📝 NOTES FOR HAZIQ

1. **Start with TEST 1** - This validates the entire Gemini→Layer 1 learning pipeline
2. **Debug logs are VERBOSE** - Use `Ctrl+F` to search for specific patterns
3. **Performance warnings (<50ms)** - These are informational, not failures
4. **Confidence ranges** - These are statistical guidelines, outliers are expected
5. **Cross-session test** - Close app completely (not just minimize)
6. **RAM monitoring** - Use Task Manager (Windows) or `htop` (Linux) during tests

---

**Last Updated:** December 29, 2025  
**Next Review:** After Phase 3 implementation complete  
**Status:** Ready for manual GUI testing 🚀
