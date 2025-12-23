# 🚨 PyTorch DLL Error - QUICK FIX

**Error:** `OSError: [WinError 1114] A dynamic link library (DLL) initialization routine failed`

---

## 🔧 ROOT CAUSE

PyTorch requires **Visual C++ Redistributable** runtime libraries that are not installed on your system.

---

## ✅ SOLUTION (5 Minutes)

### **Step 1: Download Visual C++ Redistributables**

Download the **latest version** from Microsoft:

**Direct Link:** https://aka.ms/vs/17/release/vc_redist.x64.exe

Or go to: https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist

---

### **Step 2: Install**

1. Run the downloaded `vc_redist.x64.exe`
2. Click "Install"
3. Restart your computer (required!)

---

### **Step 3: Verify PyTorch**

After restart, run:

```powershell
cd C:\Users\Haziq\Documents\ProjectCortex
python tests/check_pytorch.py
```

**Expected output:**
```
PyTorch Version: 2.9.1+cu128
CUDA Available: True
CUDA Device: NVIDIA GeForce RTX 2050
CUDA Version: 12.8
```

---

## 🚀 ALTERNATIVE: Use CPU-Only Mode (Temporary)

If you want to test the memory feature **right now** without waiting for PyTorch:

1. **Comment out PyTorch imports** in cortex_gui.py (temporarily)
2. **Run memory test** (doesn't need PyTorch):
   ```powershell
   python tests/test_memory_storage.py
   ```

---

## 📊 WHAT WORKS WITHOUT PYTORCH?

✅ **Memory Storage System** (SQLite + images)
✅ **Voice Activation** (Silero VAD - uses ONNX runtime)
✅ **Text-to-Speech** (Kokoro doesn't need PyTorch for inference)
✅ **Gemini API** (cloud-based, no local GPU)

❌ **YOLO Object Detection** (needs PyTorch/CUDA)
❌ **Whisper STT** (needs PyTorch for GPU acceleration)

---

## 🎯 RECOMMENDED ACTION

1. **Install Visual C++ Redistributables** (5 minutes)
2. **Restart computer**
3. **Test PyTorch:** `python tests/check_pytorch.py`
4. **Launch GUI:** `python tests/launch_cortex.py`

---

## 🔍 VERIFICATION CHECKLIST

After installing VC++ Redistributables:

- [ ] Restart computer
- [ ] Run `python tests/check_pytorch.py` → Should show CUDA: True
- [ ] Run `python tests/test_memory_storage.py` → All 5 tests pass
- [ ] Run `python tests/launch_cortex.py` → GUI launches without errors

---

## 📞 IF STILL BROKEN

If you still get DLL errors after installing VC++ Redistributables:

1. **Reinstall PyTorch:**
   ```powershell
   python -m pip uninstall torch torchvision
   python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
   ```

2. **Check NVIDIA drivers:**
   ```powershell
   nvidia-smi
   ```
   Should show CUDA Version 12.x

3. **Try CPU-only PyTorch** (slower but works):
   ```powershell
   python -m pip install torch torchvision
   ```

---

**Built by Haziq + AI CTO**  
**December 19, 2025**
