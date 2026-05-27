# IVP Hardware Configuration & Future Implementation Notes

**Date:** May 2026  
**Status:** Hardware ordered, software drivers in progress  
**Next Milestone:** Local safety pipeline (ToF + USB camera + YOLO) operational on RPi5

---

## Hardware Configuration (Locked for IVP)

| Component | Model / Spec | Status | Cost (SGD) |
|---|---|---|---|
| **Compute** | Raspberry Pi 5 (4GB) + Hailo 8L M.2 HAT | Existing | — |
| **Cooling** | Official RPi5 Active Cooler | Existing | — |
| **Power** | 20,000mAh 100W PD power bank | Existing | — |
| **Camera** | USB wide-angle module, 130° FOV, UVC, 1080p30 | Ordered (AliExpress, ~3 weeks) | S$6.42 |
| **ToF Depth** | VL53L5CX, 8×8 zones, I2C, 4m range | Ordered (AliExpress, ~3 weeks) | S$8.88 |
| **Audio In** | Bluetooth lavalier mic | Existing | — |
| **Audio Out** | Premade smart glasses speaker (Bluetooth) | Existing | — |
| **Pouch / Belt** | Running belt with mesh pouch | Existing | — |
| **Cables** | USB-A extension 1m, USB-C 0.2m, velcro ties | Existing | — |
| **Mounting** | Hot glue gun + foam tape | Existing | — |

**Total new hardware cost: ~S$18**

---

## Physical Layout (Final)

```
HEAD
┌─────────────────────────────────────────┐
│  [Premade Smart Glasses]                │
│     │                          │        │
│     ▼                          ▼        │
│  [USB Camera]──USB ext──[BT Speaker]    │
│  (bridge, hot glued)    (temple arms)   │
│     │                                   │
│     │  [VL53L5CX ToF]                   │
│     │  (bridge, pointing down 10°)      │
│     │       │                           │
└─────┼───────┼───────────────────────────┘
      │       │
      ▼       ▼
   Under shirt / behind neck
      │       │
      ▼       ▼
┌─────────────────────────────────────────┐
│  BELT POUCH                             │
│  ┌─────────┐  ┌─────────┐  ┌────────┐ │
│  │  RPi5   │  │ Hailo   │  │ 20k    │ │
│  │ +Active │  │ 8L M.2  │  │ mAh    │ │
│  │ Cooler  │  │ HAT     │  │ PD     │ │
│  └─────────┘  └─────────┘  └────────┘ │
└─────────────────────────────────────────┘
```

**Cable routing:**
- USB camera → 1m extension → RPi5 USB-A port
- ToF → 4-wire I2C dupont (SDA, SCL, VCC, GND) → RPi5 GPIO
- Audio → Bluetooth (no cables)
- Power → Short USB-C → RPi5 USB-C PD port

---

## Software Roadmap (Priority Order)

### Phase 1: Local Safety Pipeline (Current Sprint — Weeks 1-3)
**Goal:** Replace Hailo monocular depth with ToF + USB camera. Free Hailo for YOLO-only.

| Task | File | Description |
|---|---|---|
| ToF I2C driver | `rpi5/sensors/vl53l5cx_handler.py` | Initialize VL53L5CX over I2C, read 8×8 depth grid at 15Hz, classify hazards (wall, drop-off, clear path) |
| USB camera handler | `rpi5/camera/usb_camera_handler.py` | OpenCV VideoCapture backend, drop-in replacement for picamera2 in `main.py` |
| Safety monitor fusion | `rpi5/layer0_guardian/safety_monitor.py` | Fuse ToF depth zones with YOLO detections for directional alerts |
| Main loop integration | `rpi5/main.py` | Swap camera source, add ToF to main loop, remove Hailo depth dependency |

**Acceptance criteria:**
- ToF outputs 8×8 depth map at 15 FPS
- USB camera streams at 640×480, 10 FPS minimum
- Safety monitor triggers "wall ahead" / "drop-off left" / "clear path" alerts via TTS
- Hailo NPU runs **only YOLO** (no depth model), inference <80ms sustained

### Phase 2: Audio Pipeline Hardening (Weeks 2-4)
**Goal:** Robust voice input/output for IVP demo.

| Task | File | Description |
|---|---|---|
| Bluetooth lavalier pairing | `rpi5/audio/bt_lavalier.py` | Auto-pair BT mic on boot, fallback to USB audio if unavailable |
| VAD tuning for close mic | `rpi5/layer1_reflex/vad_handler.py` | Lower threshold (close mic = strong signal), reduce false triggers from ambient noise |
| Glasses speaker output | `rpi5/audio/bt_speaker.py` | Route all TTS / Gemini audio to smart glasses BT speaker, fallback to 3.5mm if needed |
| Echo suppression | `rpi5/voice_coordinator.py` | Skip VAD during system speech output to prevent self-triggering |

### Phase 3: Outdoor Navigation Polish (Weeks 3-5)
**Goal:** Navigation demo ready for SAVH / IVP.

| Task | File | Description |
|---|---|---|
| Breadcrumb retrace | `rpi5/layer3_guide/navigation_engine.py` | "I'm lost" → reverse GPS breadcrumbs with voice guidance |
| Bus stop UX | `rpi5/layer3_guide/bus_handler.py` | Detect bus arrival via ToF (large object approaching) + LTA DataMall |
| Arrival flow | `rpi5/main.py` | Clear arrival announcement, auto-stop navigation, offer next actions |
| Turn prompt timing | `rpi5/layer3_guide/navigation_engine.py` | _speak_critical() already implemented — tune distances based on walking speed |

### Phase 4: Demo & Hardening (Weeks 5-6)
**Goal:** No crashers, smooth 5-minute walkthrough.

| Task | Description |
|---|---|
| Thermal guard | Auto-reduce YOLO resolution if CPU temp >80°C |
| Battery time warnings | Warn at 3h / 3.5h elapsed |
| Graceful degradation | If Gemini disconnects → local TTS fallback → offline mode announcement |
| Crash recovery | `main.py` exception handling: restart camera, restart ToF, log and continue |

---

## Deferred to Post-IVP (Future Implementation)

| Feature | Why Deferred | When |
|---|---|---|
| **Local multimodal copilot** (Hailo audio+video→audio) | Model training agent owns this; `.hef` delivery TBD; not needed for IVP safety demo | Post-IVP, Phase 1 custom PCB |
| **Telephoto camera** | Digital center crop from 1080p wide camera is sufficient for sign reading; dual camera = double USB bandwidth + complexity | Phase 1 if sign-reading accuracy insufficient |
| **Dual-mic beamforming** | Bluetooth lavalier alone eliminates 90% of ambient noise; GCC-PHAT requires wired dual mics | Only if BT mic fails in noisy environments |
| **Custom glasses PCB** | IVP runs on premade sunglasses + hot glue; custom PCB is $50K+ NRE | Phase 1 funding secured |
| **Haptic feedback** | Audio-only alerts sufficient for IVP; haptic needs wrist/chest placement + extra GPIO wiring | Phase 1 if SAVH requests tactile feedback |
| **3-camera setup** (wide + tele + ToF) | RPi5 USB bandwidth and CPU can't sustain 3 streams; needs custom SoM | Phase 2 if compute upgraded |
| **Wireless video streaming** (WiFi 6 / 60GHz) | Cable from head to belt is acceptable for IVP; wireless adds latency + battery drain | Phase 2 if ergonomics critical |
| **IMX291 / IMX678 high-end camera** | S$75-110 camera on S$250 BOM is unjustified; cheap 130° module is 90% as good at 640×480 YOLO input | Only if low-light performance unacceptable |

---

## Key Decisions Log

| Decision | Rationale | Date |
|---|---|---|
| USB camera over CSI Camera Module 3 | CSI ribbon cable too fragile for head mounting; USB cable robust and 1m+ long | May 2026 |
| 130° cheap camera over S$110 SVPRO | YOLO input is 640×480; 4K/0.0001 lux overkill; FOV matters more than sensor quality for navigation | May 2026 |
| VL53L5CX over MaixSense A075V | S$8.88 vs S$122; 8×8 zones sufficient for "wall ahead / clear path"; frees Hailo for YOLO-only | May 2026 |
| ToF on glasses bridge (not chest) | Must point with user's gaze; chest-mount misses overhead branches and misaligns with head orientation | May 2026 |
| Bluetooth lavalier over wired | Eliminates TRRS splitter, cable routing, 3.5mm jack conflict; RPi5 BT 5.0 is reliable | May 2026 |
| Skip haptic for IVP | Audio escalation (beep → "person ahead" → "STOP!") is standard in assistive tech; saves GPIO complexity | May 2026 |
| Belt pouch over chest/neck | RPi5 + Hailo = 350g; belt carries weight without neck strain; mesh pouch + active cooler manages thermals | May 2026 |
| Skip dual-mic beamforming | Single close lavalier is enough; beamforming = 1 week software for 5% gain | May 2026 |
| Skip telephoto camera | Digital center crop from 1080p wide camera at 3× zoom = same pixel density as 640×480 telephoto | May 2026 |

---

## Notes for Future Agents

**When this doc was written:**
- Outdoor nav bug fixes (arrival TTS, _speak_critical, unified start helper) are committed to `main`
- SQLite batch-write optimization is committed
- `python -m rpi5 all` defaults to standalone (no ZMQ/WebSocket)
- Hailo depth estimator is still active in `main.py` — will be **replaced** by ToF when driver is ready

**What to do when hardware arrives:**
1. Flash fresh Raspberry Pi OS if needed
2. `sudo apt install python3-smbus i2c-tools libopencv-dev`
3. Enable I2C: `sudo raspi-config` → Interface Options → I2C → Enable
4. Wire VL53L5CX: VCC→3.3V (Pin 1), GND→GND (Pin 6), SDA→GPIO 2 (Pin 3), SCL→GPIO 3 (Pin 5)
5. Run `i2cdetect -y 1` — should show address `0x52` (VL53L5CX)
6. Plug USB camera, run `ls /dev/video*` — should show `/dev/video0`
7. Install `rpi5/sensors/vl53l5cx_handler.py` and `rpi5/camera/usb_camera_handler.py`
8. Update `main.py` to instantiate both
9. Run `python -m rpi5 all --standalone` and verify TTS alerts for obstacles

---

*Document Owner: RPi5 Software Agent*  
*Last Updated: May 2026*  
*Next Review: When AliExpress hardware arrives (est. 2-3 weeks)*
