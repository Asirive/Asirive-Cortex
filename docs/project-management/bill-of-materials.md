# Project-Cortex v2.0 - Bill of Materials (BOM)

**Target Cost:** <$150 USD  
**Last Updated:** November 16, 2025  
**Configuration:** YIA 2026 Competition Prototype  

---

## 🎯 Cost Breakdown Summary

| Category | Estimated Cost | Percentage |
|----------|---------------|------------|
| Compute & Vision | $75-95 | 50-63% |
| Power System | $25-35 | 17-23% |
| Audio I/O | $15-25 | 10-17% |
| Enclosure & Misc | $10-20 | 7-13% |
| **TOTAL** | **$125-175** | **100%** |

> **Note:** We're targeting the lower end ($125-140) to maintain competitive pricing.

---

## 📦 Core Components (Required)

### 1. Compute & Vision Platform

| Component | Specification | Qty | Unit Price | Total | Source |
|-----------|--------------|-----|------------|-------|--------|
| **Raspberry Pi 5** | 4GB RAM model | 1 | $60 | $60 | Official Distributors |
| **IMX415 Camera Module** | 8MP, MIPI CSI-2, Low-Light | 1 | $25-35 | $30 | Arducam/Waveshare |
| **Official Active Cooler** | RPi 5 Compatible | 1 | $5 | $5 | Raspberry Pi Foundation |
| **microSD Card** | 64GB, Class 10, A2 Rating | 1 | $8-12 | $10 | SanDisk/Samsung |

**Subtotal:** $105

### 2. Power System

| Component | Specification | Qty | Unit Price | Total | Source |
|-----------|--------------|-----|------------|-------|--------|
| **USB-C PD Power Bank** | 30,000mAh, 65W Output, PD 3.0 | 1 | $30-40 | $35 | Anker/Baseus |
| **USB-C to USB-C Cable** | 100W Rated, 1m Length | 1 | $5-8 | $6 | Generic/Anker |

**Subtotal:** $41

### 3. Audio Interface

| Component | Specification | Qty | Unit Price | Total | Source |
|-----------|--------------|-----|------------|-------|--------|
| **USB Audio Adapter** | USB-A to 3.5mm, DAC | 1 | $8-12 | $10 | UGREEN/Sabrent |
| **Bone Conduction Headphones** | Open-ear, 3.5mm jack | 1 | $20-35 | $25 | AfterShokz/Generic |
| **Mini Microphone** | 3.5mm TRRS, omnidirectional | 1 | $5-8 | $6 | Lavalier Mic |

**Subtotal:** $41

### 4. Physical Integration

| Component | Specification | Qty | Unit Price | Total | Source |
|-----------|--------------|-----|------------|-------|--------|
| **Enclosure Materials** | 3D Printed PLA/PETG | 1 | $8-15 | $12 | Local Makerspace |
| **Velcro Straps** | Adjustable, head-mountable | 2 | $3-5 | $4 | Amazon/Hardware Store |
| **Push Button (GPIO)** | Tactile, 12mm, momentary | 2 | $1-2 | $2 | Electronics Supplier |
| **Jumper Wires** | Female-Female, 20cm | 10 | $0.10 | $1 | Electronics Supplier |

**Subtotal:** $19

---

## 🔧 Optional Components (Enhanced Features)

| Component | Specification | Purpose | Unit Price |
|-----------|--------------|---------|------------|
| **USB GPS Module** | U-blox NEO-6M/7M | Layer 3 Navigation | $12-18 |
| **Coral USB Accelerator** | Edge TPU, USB 3.0 | Faster YOLO Inference | $60-75 |
| **IMU Sensor** | MPU6050, I2C | Head orientation tracking | $3-5 |
| **Haptic Motor** | Vibration feedback | Tactile alerts | $2-4 |
| **Li-Po Battery Pack** | Custom 18650 cells, BMS | Lighter alternative to power bank | $25-35 |

> **Decision:** Skipped for YIA prototype to stay under $150. GPS can use smartphone hotspot's location services.

---

## 💾 Software & Services (Free/Low-Cost)

| Service | Tier | Monthly Cost | Purpose |
|---------|------|--------------|---------|
| **Google Gemini API** | Free Tier | $0 (1M tokens/month) | Layer 2 Scene Analysis |
| **Murf AI TTS** | Free Tier | $0 (10 min/month) | High-quality voice synthesis |
| **Hugging Face API** | Free Tier | $0 (limited) | Whisper STT |
| **GitHub** | Free | $0 | Code hosting |
| **Vercel/Netlify** | Free Tier | $0 | Dashboard hosting |

**Total Software Cost:** $0/month for prototype phase

---

## 📊 Total Cost Analysis

### Minimum Viable Prototype (MVP)
**Required Components Only:** $206  
**Optimization Path:** Use 4GB Pi model, generic audio, DIY enclosure → **~$135**

### Competition-Ready Build (Recommended)
**Core + Polished Enclosure:** $150-165  
**Includes:** Professional 3D print, branded packaging, spare components

### Full-Featured Build (Stretch)
**With GPS + IMU:** $170-185  
**For future iterations post-competition**

---

## 🛒 Purchasing Strategy

### Phase 1: Immediate (Week 1)
1. Raspberry Pi 5 (4GB) - **Critical path item**
2. IMX415 Camera Module
3. Active Cooler
4. microSD Card
5. Power Bank

**Subtotal:** ~$145

### Phase 2: Audio & Integration (Week 2)
1. USB Audio Adapter
2. Bone Conduction Headphones
3. Microphone
4. Enclosure materials

**Subtotal:** ~$40

### Phase 3: Polish (Week 3-4)
1. Backup microSD card
2. Extra cables/connectors
3. Presentation materials

**Subtotal:** ~$15

---

## 🔍 Component Justifications

### Why Raspberry Pi 5 (not Pi 4)?
- **40% faster CPU** → Better YOLO inference
- **Improved power delivery** → Stable under AI load
- **Better thermal design** → No throttling with active cooler
- **PCIe support** → Future Coral TPU upgrade path

### Why IMX415 (not OV5647)?
- **4x better low-light** → Critical for indoor use
- **8MP vs 5MP** → Better OCR/text reading
- **Modern MIPI CSI-2** → Lower latency than older sensors

### Why 30,000mAh Power Bank (not smaller)?
- **6-8 hour runtime** → Full day usage
- **PD 3.0 support** → Meets RPi 5's 5V/5A requirement
- **Reusable** → User likely already owns one

---

## 📝 Sourcing Notes

### Recommended Vendors (Malaysia Context)
- **Cytron Technologies** - Local RPi distributor, fast shipping
- **Shopee/Lazada** - Power banks, audio equipment
- **AliExpress** - IMX415 camera (2-3 weeks shipping)
- **Local Makerspaces** - 3D printing services

### Import Considerations
- **No import taxes** for components <RM500 (~$110 USD)
- **Shipping time** - Plan 2-4 weeks for camera module
- **Warranty** - Prefer local sellers for Pi 5 (warranty support)

---

## 🔄 Version History

| Version | Date | Changes | Total Cost |
|---------|------|---------|------------|
| 2.0-alpha | Nov 16, 2025 | Initial BOM for clean slate | $135-165 |
| 1.0 | Oct 2025 | ESP32-CAM build (archived) | $45 |

---

## 📞 Questions?

If component availability or pricing changes, update this file and notify the team. For alternative part suggestions, open an issue with "[BOM]" prefix.

**Last Verified:** November 16, 2025  
**Next Review:** December 1, 2025 (pre-purchase audit)
