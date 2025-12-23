# 📚 Project-Cortex Documentation

**Last Updated:** 2025-12-22  
**Status:** Organized & Production-Ready

---

## 📁 Documentation Structure

### 🏛️ **architecture/**
System design and architectural decisions.

- **system-architecture.md** - Overall system design (4-layer architecture)
- **hybrid-ai-design.md** - Hybrid AI implementation (local + cloud)

### 🔬 **research/**
Research findings and planning documents.

- **initial-findings.md** - Early research on RPi 5, cameras, and AI models
- **slam-vio-navigation.md** - SLAM/VIO system research (VIO + GPS + IMU)
- **memory-slam-navigation.md** - Memory + SLAM integration with Google Maps

### 🛠️ **implementation/**
Implementation plans and integration guides.

- **layer1-reflex-plan.md** - Layer 1 (Reflex) implementation details
- **spatial-audio-guide.md** - 3D spatial audio system (PyOpenAL + HRTF)
- **gemini-tts-integration.md** - Google Gemini 2.5 Flash TTS integration
- **voice-navigation-plan.md** - Voice-guided spatial navigation

### 🔧 **troubleshooting/**
Bug fixes and debugging guides.

- **fixes-applied.md** - Historical bug fixes and patches
- **flickering-fix.md** - GUI flickering resolution
- **vad-debugging.md** - Voice Activity Detection debugging guide

### 📋 **project-management/**
Project tracking, changelogs, and BOMs.

- **bill-of-materials.md** - Hardware components and costs
- **changelog-2025-11-17.md** - Version 2.0 changelog
- **todo-full-implementation.md** - Full implementation roadmap
- **migration-summary.md** - v1.0 → v2.0 migration summary

### 🧪 **testing/**
Testing protocols and validation procedures.

- **test-protocol.md** - Comprehensive testing procedures

---

## 🗺️ Quick Navigation

### New to Project-Cortex?
1. Start with [architecture/system-architecture.md](architecture/system-architecture.md)
2. Review [project-management/bill-of-materials.md](project-management/bill-of-materials.md)
3. Check [implementation/layer1-reflex-plan.md](implementation/layer1-reflex-plan.md)

### Working on SLAM/Navigation?
1. [research/slam-vio-navigation.md](research/slam-vio-navigation.md) - VIO system research
2. [research/memory-slam-navigation.md](research/memory-slam-navigation.md) - Navigation integration
3. [implementation/spatial-audio-guide.md](implementation/spatial-audio-guide.md) - 3D audio

### Debugging Issues?
1. [troubleshooting/vad-debugging.md](troubleshooting/vad-debugging.md) - Voice detection issues
2. [troubleshooting/flickering-fix.md](troubleshooting/flickering-fix.md) - GUI problems
3. [troubleshooting/fixes-applied.md](troubleshooting/fixes-applied.md) - Historical fixes

### Planning Next Steps?
1. [project-management/todo-full-implementation.md](project-management/todo-full-implementation.md)
2. [research/memory-slam-navigation.md](research/memory-slam-navigation.md) - Next features
3. [testing/test-protocol.md](testing/test-protocol.md) - Validation checklist

---

## 📊 Documentation Coverage

| Category | Files | Status |
|----------|-------|--------|
| Architecture | 2 | ✅ Complete |
| Research | 3 | ✅ Complete |
| Implementation | 4 | ✅ Complete |
| Troubleshooting | 3 | ✅ Complete |
| Project Management | 4 | ✅ Complete |
| Testing | 1 | ✅ Complete |
| **TOTAL** | **17** | **✅ Organized** |

---

## 🔄 Naming Conventions

- **Folders:** lowercase-with-hyphens
- **Files:** lowercase-with-hyphens.md
- **Internal References:** Use relative paths (e.g., `[Link](../research/slam-vio-navigation.md)`)

---

## 🚀 Quick Links

### External Documentation
- [Raspberry Pi 5 Docs](https://www.raspberrypi.com/documentation/computers/raspberry-pi-5.html)
- [Google Gemini API](https://ai.google.dev/docs)
- [OpenAL-Soft](https://github.com/kcat/openal-soft)
- [YOLOv8 Ultralytics](https://docs.ultralytics.com/)

### Project Resources
- **GitHub Repo:** [IRSPlays/ProjectCortexV2](https://github.com/IRSPlays/ProjectCortexV2)
- **Main README:** [../README.md](../README.md)
- **Source Code:** [../src/](../src/)

---

**Founder:** Haziq (@IRSPlays)  
**Mission:** Gold Medal @ YIA 2026 🏆
