# Project-Cortex v2.0
## AI-Powered Assistive Wearable for the Visually Impaired

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Raspberry Pi 5](https://img.shields.io/badge/Hardware-Raspberry%20Pi%205-red.svg)](https://www.raspberrypi.com/products/raspberry-pi-5/)

---

## 🎯 Project Mission

**Project-Cortex** is a low-cost (<$150), high-impact AI wearable designed to assist visually impaired individuals by providing real-time scene understanding, object detection, and audio navigation. Built for the **Young Innovators Awards (YIA) 2026** competition.

We aim to democratize assistive technology by disrupting the $4,000+ premium device market (OrCam, eSight) using commodity hardware and a novel "Hybrid AI" architecture.

---

## 🏗️ Architecture Overview

### Hardware Platform
- **Compute:** Raspberry Pi 5 (4GB/8GB RAM)
- **Vision:** IMX415 8MP Low-Light Camera (MIPI CSI-2)
- **Power:** 30,000mAh USB-C PD Power Bank
- **Cooling:** Official RPi 5 Active Cooler
- **Audio:** USB Audio Interface + Bone Conduction Headphones
- **Connectivity:** Mobile Hotspot (no dedicated SIM module)

### The "3-Layer AI" Brain

#### Layer 1: The Reflex (Local Inference)
- **Purpose:** Instant safety-critical object detection
- **Model:** YOLOv8n / TensorFlow Lite
- **Latency:** <100ms
- **Power:** 8-12W during inference
- **Location:** `src/layer1_reflex/`

#### Layer 2: The Thinker (Cloud Intelligence)
- **Purpose:** Complex scene analysis, OCR, natural language descriptions
- **Model:** Google Gemini 1.5 Flash (via API)
- **Fallback:** OpenAI GPT-4 Vision
- **Latency:** ~1-3s (network dependent)
- **Location:** `src/layer2_thinker/`

#### Layer 3: The Guide (Integration & UX)
- **Features:** GPS navigation, 3D spatial audio, caregiver dashboard
- **Tech Stack:** FastAPI (backend), React (dashboard), PyOpenAL (audio)
- **Location:** `src/layer3_guide/`

---

## 📁 Repository Structure

```
ProjectCortex/
├── Version_1/                      # Archived ESP32-CAM implementation
│   ├── Docs/                      # v1.0 technical retrospective
│   └── Code/                      # v1.0 Python/Arduino code
├── models/                         # Shared AI models (YOLO variants)
├── TTS Model/                      # Piper TTS model files
├── src/                           # Version 2.0 source code
│   ├── layer1_reflex/             # Local object detection module
│   ├── layer2_thinker/            # Cloud AI integration module
│   ├── layer3_guide/              # Navigation & UI module
│   └── main.py                    # Application entry point
├── config/                         # Configuration files (.yaml, .json)
├── tests/                          # Unit and integration tests
├── docs/                           # Technical documentation
├── utils/                          # Helper scripts and tools
├── .env.example                    # Environment variables template
├── requirements.txt                # Python dependencies
└── README.md                       # This file
```

---

## 🚀 Quick Start

### Prerequisites
- Raspberry Pi 5 (4GB+ RAM) with Raspberry Pi OS (64-bit)
- IMX415 Camera Module (connected via CSI port)
- Python 3.11+
- Active internet connection (for Layer 2)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/IRSPlays/ProjectCortex.git
   cd ProjectCortex
   ```

2. **Set up Python environment:**
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Configure environment variables:**
   ```bash
   cp .env.example .env
   nano .env  # Add your API keys (Gemini, Murf AI, etc.)
   ```

4. **Test camera module:**
   ```bash
   libcamera-hello --camera 0  # Should display camera preview
   ```

5. **Run the application:**
   ```bash
   python src/main.py
   ```

---

## 🔧 Configuration

### Power Management
Add to `/boot/firmware/config.txt`:
```ini
usb_max_current_enable=1
dtoverlay=imx415
```

### Camera Settings
Configure in `config/camera.yaml`:
```yaml
resolution: [1920, 1080]
framerate: 30
format: RGB888
```

### AI Model Selection
Edit `config/models.yaml`:
```yaml
layer1:
  model: "models/yolo11s.pt"
  device: "cpu"  # Change to "cuda" if using Coral TPU
  confidence: 0.5
```

---

## 🧪 Testing

Run unit tests:
```bash
pytest tests/ -v
```

Run integration tests (requires hardware):
```bash
pytest tests/integration/ --hardware
```

---

## 📊 Performance Benchmarks

| Metric | Target | Current Status |
|--------|--------|----------------|
| Layer 1 Latency | <100ms | TBD |
| Layer 2 Latency | <3s | TBD |
| Power Consumption | <20W avg | TBD |
| Battery Life | 6-8 hours | TBD |
| Object Detection Accuracy | >85% mAP | TBD |

---

## 🛠️ Development Roadmap

### Phase 1: Core Infrastructure (Current)
- [x] Repository restructure
- [ ] Camera integration with libcamera
- [ ] Layer 1 YOLO inference pipeline
- [ ] Layer 2 Gemini API integration
- [ ] Audio subsystem (TTS + STT)

### Phase 2: Feature Development
- [ ] GPS navigation module
- [ ] 3D spatial audio engine
- [ ] Caregiver web dashboard
- [ ] Power optimization

### Phase 3: YIA Preparation
- [ ] User testing & feedback
- [ ] Documentation for judges
- [ ] Prototype enclosure design
- [ ] Demonstration video

---

## 📚 Documentation

- **[Bill of Materials (BOM)](docs/BOM.md)** - Complete parts list with costs
- **[Architecture Deep Dive](docs/ARCHITECTURE.md)** - Technical design decisions
- **[API Reference](docs/API.md)** - Code documentation
- **[v1.0 Retrospective](Version_1/Docs/)** - Lessons learned from ESP32-CAM

---

## 🤝 Contributing

This is a competition prototype developed by **Haziq (@IRSPlays)**. For questions or collaboration inquiries, please open an issue.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🏆 Acknowledgments

- **YIA 2026 Organizers** - For the opportunity to innovate
- **Raspberry Pi Foundation** - For affordable, powerful compute
- **Ultralytics** - For accessible YOLO implementations
- **Google Gemini Team** - For multimodal AI API access

---

## 📞 Contact

**Project Lead:** Haziq  
**GitHub:** [@IRSPlays](https://github.com/IRSPlays)  
**Repository:** [ProjectCortex](https://github.com/IRSPlays/ProjectCortex)

---

**Built with 💙 for accessibility. Engineered with 🔥 for excellence.**
