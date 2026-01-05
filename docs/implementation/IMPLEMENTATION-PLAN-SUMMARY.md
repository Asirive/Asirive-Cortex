# Project Cortex v2.0 - Implementation Plan Summary

**Date:** December 31, 2025  
**Status:** 🟢 READY FOR REVIEW

---

## 📊 QUICK OVERVIEW

### What We're Building
1. **Web Dashboard** for RPi 5 (accessible from any device via `http://<RPi_IP>:5000`)
2. **Model Benchmarking System** to validate 4-5x NCNN speedup claims
3. **Complete Integration** of all 5 AI layers with performance monitoring

### Why This Matters for YIA 2026
- **Professional Demo:** Judges can view system from tablets/phones
- **Performance Proof:** Real benchmark data (not just claims)
- **Cost Advantage:** Show $150 RPi 5 achieving <100ms detection

---

## 🎯 3-PHASE APPROACH

### Phase 1: Complete Dashboard (4-6 hours)
**Add missing features:**
- YOLOE 3-mode selector (Prompt-Free, Text Prompts, Visual Prompts)
- Spatial audio toggle
- Memory store/recall with bounding boxes
- VAD (Voice Activity Detection) integration
- Performance metrics display

**Optimize for RPi 5:**
- Network binding (`0.0.0.0` instead of `localhost`)
- Auto-detect picamera2 vs webcam
- Graceful degradation (if API fails)
- Resource limits (640x480 @ 15 FPS on RPi)

### Phase 2: Model Benchmarking (3-4 hours) ⭐ **CRITICAL**
**Create benchmarking framework:**
```python
# Tests to run:
1. YOLO11n PyTorch vs NCNN vs OpenVINO
2. YOLO11s PyTorch vs NCNN
3. YOLO11x PyTorch vs NCNN
4. YOLOE-11s PyTorch vs NCNN
5. YOLOE-11m PyTorch vs NCNN

# Expected validation:
- YOLO11n-NCNN: ~94ms (meets <100ms target!) ✅
- YOLO11s-NCNN: ~222ms (4.9x faster than PyTorch)
- YOLOE-11s-NCNN: ~220ms (4.5x faster)
```

**Generate visual report:**
- Bar charts comparing formats
- Speedup table (PyTorch → NCNN)
- Recommendation summary for YIA 2026 demo

### Phase 3: Dashboard + Benchmarks (2-3 hours)
**Add benchmark tab to dashboard:**
- Run benchmarks from web UI
- Live FPS counter
- Latency graph (last 100 frames)
- Export results (JSON/CSV)

---

## 📈 EXPECTED RESULTS

### Performance Targets (RPi 5, 640x640)
| Model | Current (PyTorch) | After NCNN | Speedup | Layer | Target Met |
|-------|-------------------|------------|---------|-------|------------|
| YOLO11n | 388ms | **94ms** | 4.1x | Layer 0 | ✅ **YES** |
| YOLO11s | 1085ms | **222ms** | 4.9x | Layer 0 | ⚠️ Close |
| YOLOE-11s | 1000ms | **220ms** | 4.5x | Layer 1 | ✅ **YES** |

### Impact on Project Cortex
- **Before:** YOLO11x @ 800-1000ms (❌ fails <100ms requirement)
- **After:** YOLO11n-NCNN @ 94ms (✅ **MEETS requirement!**)
- **Benefit:** Real-time safety detection + $150 total cost = **Disruptive advantage**

---

## 🔬 RESEARCH FINDINGS (from Ultralytics + Context7)

### Confirmed Facts
1. **NCNN is 4-5x faster than PyTorch on RPi 5** (official benchmarks)
2. **OpenVINO is 5-10% faster than NCNN** (but more complex)
3. **NiceGUI supports background tasks** via `run.cpu_bound()` and `run.io_bound()`
4. **Browser WebAudio API** works for voice commands (Chrome, Firefox, Safari)
5. **RPi 5 Lite OS** supports headless operation (SSH + web dashboard)

### Best Practices (from NiceGUI docs)
- Use `ui.timer()` for video streaming (not while loops)
- Use `asyncio.create_task()` for async operations
- Use `run.io_bound()` for camera capture (threaded)
- Use `run.cpu_bound()` for YOLO inference (separate process)
- Set `host='0.0.0.0'` for LAN access

---

## ⚠️ CRITICAL DECISIONS NEEDED

### Decision 1: Which Phase First?
**Recommendation:** **Phase 2 (Benchmarking)** first
- **Why:** Need hard data before YIA 2026 demo
- **Why:** Can run on laptop (don't need RPi 5 ready yet)
- **Duration:** 3-4 hours
- **Output:** Benchmark report with charts

**Alternative:** Phase 1 first (if RPi 5 is already ready for testing)

### Decision 2: Model Selection for Layer 0
**Current:** YOLO11x (2.5GB RAM, ~800-1000ms PyTorch)
**Recommended:** YOLO11n-NCNN (300MB RAM, ~94ms)
- **Trade-off:** Lower accuracy (but still 80 COCO classes)
- **Benefit:** Meets <100ms target
- **Alternative:** YOLO11s-NCNN (222ms, better accuracy, but 2.2x over target)

### Decision 3: OpenVINO vs NCNN
**NCNN:** Simpler, smaller, 94ms
**OpenVINO:** Faster (85ms), but 2x larger files
- **Recommendation:** Start with NCNN, upgrade to OpenVINO later if needed

---

## 📅 TIMELINE OPTIONS

### Option A: Fast Track (3 days)
- Day 1: Phase 2 (Benchmarking) - 4 hours
- Day 2: Phase 1 (Dashboard) - 6 hours
- Day 3: Phase 3 (Integration) - 3 hours
- **Total:** 13 hours across 3 days

### Option B: Steady Pace (7 days)
- Days 1-3: Phase 1 (Dashboard + testing)
- Days 4-5: Phase 2 (Benchmarking)
- Days 6-7: Phase 3 (Integration)
- **Total:** 24-30 hours across 7 days (4-6 hours/day)

### Option C: Benchmark Only (1 day)
- Focus on Phase 2 only (get hard data)
- Skip dashboard changes for now
- **Total:** 3-4 hours

---

## 🎯 RECOMMENDED NEXT STEPS

### Immediate (Today)
1. **Review this plan** (5 minutes)
2. **Approve Phase 2** (benchmarking)
3. **Run model conversion script:**
   ```bash
   python3 convert_models_to_ncnn.py
   ```
4. **Start benchmarking:**
   ```bash
   python3 tests/benchmark_models.py --model yolo11n --format ncnn
   ```

### Short-term (This Week)
5. Complete Phase 2 (benchmark all models)
6. Generate visual report for YIA 2026
7. Update `.env` to use YOLO11n-NCNN

### Medium-term (Next Week)
8. Complete Phase 1 (dashboard features)
9. Test on RPi 5 headless
10. Complete Phase 3 (dashboard + benchmarks)

---

## 🤝 WHAT I NEED FROM YOU

Please confirm:
1. **Do you approve this 3-phase plan?** (Yes/No)
2. **Which phase should we start with?** (1, 2, or 3)
3. **Timeline preference?** (Fast track, steady pace, or benchmark-only)
4. **Do you have RPi 5 ready for testing?** (Yes/No/Soon)

**Example Response:**
```
Approved! Start with Phase 2 (Benchmarking).
Timeline: Fast track (3 days).
RPi 5: Not ready yet, will arrive next week.
```

---

## 📚 REFERENCE DOCUMENTS

Created in this session:
1. ✅ [RPI5-COMPLETE-SETUP-GUIDE.md](./RPI5-COMPLETE-SETUP-GUIDE.md) - Full setup instructions
2. ✅ [MODEL-OPTIMIZATION-GUIDE.md](./MODEL-OPTIMIZATION-GUIDE.md) - NCNN conversion guide
3. ✅ [DASHBOARD-IMPLEMENTATION-PLAN.md](./DASHBOARD-IMPLEMENTATION-PLAN.md) - Detailed plan (28 pages)
4. ✅ [convert_models_to_ncnn.py](../../convert_models_to_ncnn.py) - Automated conversion script

---

**Status:** 🟢 READY TO START  
**Waiting for your approval to proceed! 🚀**
