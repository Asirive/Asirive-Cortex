# V2 to V3 Hardware Evolution Guide

## Executive Summary

ProjectCortex V2 established the core AI pipeline for a wearable navigation assistant for the visually impaired. V3 evolves the hardware from a bulky development prototype into a refined, production-ready wearable device.

---

## Problem Statement: V2 Hardware Limitations

### 1. Size & Bulk

| Component | V2 Problem | Impact |
|-----------|------------|--------|
| Raspberry Pi 5 | Full-size board (90x70mm) | Heavy, uncomfortable head mounting |
| Hailo-8L AI Accelerator | Separate M.2 module + heatsink | Adds 60x20mm, thermal issues |
| Camera Module 3 Wide | Cable-connected, exposed | Vulnerable to damage |
| Power Bank | External 5000mAh LiPo | Must be carried separately |
| All interconnect cables | Dupont/jumper wires | Unreliable, messy |

**V2 Total Volume:** ~350cm³ (without battery)
**V2 Total Weight:** ~280g (with battery)

---

### 2. Ergonomics Issues

| Issue | V2 Reality | User Impact |
|-------|-------------|------------|
| Head mounting | Ad-hoc 3D printed bracket | Unstable, shifts during walking |
| Balance | Heavy front (camera) vs back (RPi) | Neck strain over time |
| Cable management | No routing channels | Wires catch on clothing |
| Heat dissipation | Passive heatsink only | Device warms against head |
| Privacy | No physical shutter | User can't confirm camera off |

---

### 3. Audio System

| Component | V2 Problem | Impact |
|-----------|------------|--------|
| Earpiece | Consumer bone conduction (Aftershokz) | Not designed for wearable integration |
| Microphone | Separate USB lavalier | Extra wire, easy to disconnect |
| Bluetooth | A2DP/HFP conflict | Frequent audio routing issues |
| Spatial audio | Head tracking latency >50ms | Sound direction drifts |

---

### 4. Power System

| Issue | V2 Reality | Impact |
|-------|-------------|--------|
| Battery | External LiPo pack | Must be managed separately |
| Charging | Micro USB, 5V/3A only | 2-3 hour charge time |
| Runtime | ~4 hours active | Insufficient for full day |
| Thermal | No active thermal management | Performance throttling |

---

### 5. Connectivity

| Issue | V2 Reality | Impact |
|-------|-------------|--------|
| GPS | Phone tethering required | Dependency on phone battery |
| WiFi | RPi built-in (2.4GHz only) | Slow updates, poor range |
| Cellular | None | No standalone connectivity |
| USB | Multiple loose connections | Fragile, must be assembled carefully |

---

### 6. Reliability

| Issue | V2 Reality | Impact |
|-------|-------------|--------|
| Cable fatigue | Dupont pins loosen over time | Intermittent failures |
| SD card | Wear from logging | Data corruption risk |
| IMU I2C | Bus conflicts on RPi | Heading drift/failures |
| Camera | Ribbon cable damage | Complete failure |

---

## V3 Hardware Architecture

### Design Philosophy

```
V3 Goals:
1. Integrate all components onto custom PCB
2. Minimize form factor by 70%
3. Single head-worn unit under 150g
4. 8+ hour battery life
5. Industrial-grade reliability
6. Seamless user experience (via apps and voice)
```

---

### V3 Block Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      V3 WEARABLE UNIT                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    │
│  │   Camera    │    │   IMU+GPS   │    │   Battery   │    │
│  │ Module 3   │    │   (BNO085)  │    │  (LiPo 3S) │    │
│  │   Wide     │    │             │    │   3000mAh   │    │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    │
│         │                   │                   │            │
│         │    Custom PCB    │                   │            │
│         └─────────────────┼───────────────────┘            │
│                           │                                 │
│              ┌────────────┴────────────┐                   │
│              │                         │                   │
│              │   ┌─────────────────┐   │                   │
│              │   │  RP2350 MCU     │   │                   │
│              │   │  (Secondary)    │   │                   │
│              │   │  - Audio I/O    │   │                   │
│              │   │  - Sensor Fus.  │   │                   │
│              │   │  - Power Mgmt   │   │                   │
│              │   └────────┬────────┘   │                   │
│              │            │            │                   │
│              │   ┌────────┴────────┐   │                   │
│              │   │  Hailo-8L       │   │                   │
│              │   │  (Integrated)    │   │                   │
│              │   │  Neural Engine  │   │                   │
│              │   └────────┬────────┘   │                   │
│              │            │            │                   │
│              │   ┌────────┴────────┐   │                   │
│              │   │  ESP32-S3      │   │                   │
│              │   │  (Wireless)    │   │                   │
│              │   │  - BT 5.3      │   │                   │
│              │   │  - WiFi 6      │   │                   │
│              │   │  - BLE Audio   │   │                   │
│              │   └────────────────┘   │                   │
│              └────────────┬───────────┘                   │
│                           │                                │
│              ┌────────────┴────────────┐                   │
│              │    Integrated Audio      │                   │
│              │  ┌──────────────────┐   │                   │
│              │  │ Bone Conduction  │   │                   │
│              │  │  Driver (L+R)   │   │                   │
│              │  ├──────────────────┤   │                   │
│              │  │   Dual MEMS     │   │                   │
│              │  │   Microphones   │   │                   │
│              │  │  (Beamforming)  │   │                   │
│              │  └──────────────────┘   │                   │
│              └─────────────────────────┘                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## V3 Component Specifications

### 1. Custom PCB

| Feature | V2 | V3 | Improvement |
|---------|-----|-----|-------------|
| Board size | ~100x80mm (multiple) | 60x45mm (single) | 75% smaller |
| Connectors | Dupont, JST | Board-to-board FPC | Zero loose cables |
| Layers | 2 (protoboard) | 6 (production) | EMI optimized |

**PCB Stack:**
```
Layer 1 (Top): Components, camera connector
Layer 2: Ground plane
Layer 3: Signal routing
Layer 4: Power distribution
Layer 5: Signal routing  
Layer 6 (Bottom): Connectors, heatsink pad
```

---

### 2. Processor Options

| Option | Compute | Power | Use Case |
|--------|---------|-------|----------|
| **RP2350** | 2x Cortex-M33 | 300mW | Sensor fusion, audio I/O |
| **Hailo-8L (Integrated)** | 4 TOPS | 2W | Neural inference |
| **ESP32-S3** | Xtensa LX7 | 500mW | Wireless, BT audio |

**V3 Mode Distribution:**
- Always ON: RP2350 (sensor fusion, power management)
- AI Mode: Hailo-8L (activated on wake word)
- Comms: ESP32-S3 (BT audio, WiFi fallback)

---

### 3. Camera Integration

| Feature | V2 | V3 |
|---------|-----|-----|
| Module | Camera Module 3 Wide (separate) | OV5648 custom module |
| Connection | Ribbon cable (fragile) | Board-to-board FPC |
| Mounting | 3D printed bracket | Flush mount in frame |
| Privacy | No physical shutter | Hardware shutter (GPIO) |

**V3 Camera Module Specs:**
- Sensor: OV5648 (5MP, fixed focus)
- Lens: 120° FOV (widen than V2's 120°)
- Interface: MIPI CSI-2 (2-lane)
- Shutter: Normally-closed, opens on power
- Size: 8x8x4mm (integrated)

---

### 4. Audio System (Fully Integrated)

| Feature | V2 | V3 |
|---------|-----|-----|
| Earpiece | Aftershokz (external) | Dual bone conduction drivers |
| Mic | USB lavalier | Dual MEMS with beamforming |
| Amp | Class D (discrete) | Class D (integrated in RP2350) |
| BT Audio | BT 5.0 A2DP | BT 5.3 LE Audio |
| Spatial Audio | OpenAL HRTF | Hardware DSP |

**V3 Audio Specs:**
```
Bone Conduction:
- Frequency response: 100Hz - 15kHz
- Max SPL: 40dB @ 1cm
- Driver size: 13mm (x2, L+R)

Microphones:
- Pattern: Cardioid (beamforming pair)
- SNR: 65dB
- Sample rate: 16/32/48kHz configurable
- Beamforming: Fixed NULL toward rear

Bluetooth Audio:
- Standard: BT 5.3 LE Audio
- Codecs: LC3, LC3plus
- Latency: <30ms (vs 150ms in V2)
```

---

### 5. IMU + GPS Fusion

| Feature | V2 | V3 |
|---------|-----|-----|
| IMU | BNO055 (external) | BMI270 (integrated) |
| GPS | Phone tethering | u-blox M10S (integrated) |
| Fusion | Simple Kalman | Extended Kalman (RP2350) |
| Heading accuracy | ±5° | ±1° |

**V3 Sensor Specs:**
```
IMU (BMI270):
- Accelerometer: ±16g, 0.1mg resolution
- Gyroscope: ±2000°/s, 0.01°/s resolution
- Magnetometer: None (reliable only outdoors)

GPS (u-blox M10S):
- Channels: 72 tracking
- Accuracy: 1.5m CEP
- Update rate: 18Hz
- Cold start: 15s
- Warm start: 2s

Sensor Fusion (EKF on RP2350):
- State: [position, velocity, heading, bias]
- Update: GPS (5Hz) + IMU (100Hz)
- Dead reckoning: 30s max without GPS
```

---

### 6. Power System

| Feature | V2 | V3 |
|---------|-----|-----|
| Battery | External 5000mAh LiPo | Integrated 3000mAh LiPo |
| Capacity | 18.5Wh | 11.1Wh |
| Form factor | Cylindrical | Prismatic (thin) |
| Protection | Basic PCM | Full BMS (temp, current, voltage) |
| Charging | Micro USB 5V/2A | USB-C PD 9V/2A |
| Runtime | 4 hours | 8 hours (AI on 30% duty) |

**V3 Power Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│                     POWER MANAGEMENT                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   USB-C PD ──► BQ25720 (Charger IC) ──► 3.3V/1.8V/1.2V  │
│                                    │                          │
│                                    ▼                          │
│                              LiPo Battery                   │
│                              (3S1P)                        │
│                              3000mAh                       │
│                                    │                          │
│                    ┌─────────────┼─────────────┐           │
│                    ▼             ▼             ▼             │
│               RP2350        Hailo-8L      ESP32-S3         │
│               (Sleep)        (AI Mode)     (Always-on BT)  │
│                                                              │
│   ┌─────────────────────────────────────────────────────┐  │
│   │                 DYNAMIC POWER GATING                 │  │
│   │  Mode          │ Hailo │  RP2350  │  ESP32  │ Total │  │
│   │  ───────────────────────────────────────────────────│  │
│   │  Sleep         │ OFF   │  5mW     │  3mW    │  8mW  │  │
│   │  Idle          │ OFF   │  50mW    │  50mW   │ 100mW │  │
│   │  AI Active     │ 2W    │  100mW   │  50mW   │ 2.15W │  │
│   │  Transit       │ OFF   │  80mW    │  80mW   │ 160mW │  │
│   └─────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

### 7. Structural & Ergonomics

| Feature | V2 | V3 |
|---------|-----|-----|
| Frame | 3D printed PLA | CNC aluminum + silicone |
| Weight | ~280g (with battery) | ~120g (with battery) |
| Balance | Front-heavy | Center of gravity at ear |
| Adjustment | Fixed bracket | 3-axis adjustment |
| Comfort | Hard pressure points | Distributed load |
| Weather | None | IP54 rated |

**V3 Frame Design:**
```
                    ┌─────────────────────┐
                    │                     │
                    │   Camera Module     │
                    │   (centered)       │
                    │                     │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
         ┌────────┐      ┌────────┐      ┌────────┐
         │  IMU   │      │  PCB   │      │ Battery│
         │  +GPS  │      │ (main) │      │ (rear) │
         └────────┘      └────────┘      └────────┘
              │                │                │
              └────────────────┼────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    │   Bone Conduction   │
                    │   Earpiece (L+R)    │
                    │                     │
                    └─────────────────────┘
```

---

### 8. Thermal Management

| Feature | V2 | V3 |
|---------|-----|-----|
| Heatsink | External aluminum | Thermal pad to frame |
| Active cooling | None | Micro fan (optional) |
| Thermal throttling | 100% (no management) | Dynamic (reduce clock if >70°C) |
| User protection | None | Temperature feedback via audio |

**V3 Thermal Zones:**
```
Zone 1 (Hailo-8L): Max 85°C, throttle at 75°C
Zone 2 (RP2350): Max 85°C, throttle at 80°C  
Zone 3 (Battery): Max 45°C, stop charging at 40°C
```

---

## V3 Connectivity Architecture

### Wireless Options

| Feature | V2 | V3 |
|---------|-----|-----|
| WiFi | RPi built-in (2.4GHz) | ESP32-S3 (WiFi 6) |
| Bluetooth | USB BT adapter | ESP32-S3 native |
| Cellular | None | Optional LTE module |
| GPS | Phone only | u-blox M10S (integrated) |

### V3 Communication Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        V3 COMMUNICATIONS                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐         ┌──────────────┐                   │
│   │   WiFi 6    │         │  BT 5.3     │                   │
│   │  (ESP32)    │         │  LE Audio   │                   │
│   │              │         │              │                   │
│   │ -OTA updates │         │ -Gemini Live │                   │
│   │ -Dashboard   │         │ -Audio stream│                   │
│   │ -Cloud sync  │         │ -Voice cmds  │                   │
│   └───────┬──────┘         └───────┬──────┘                   │
│           │                         │                          │
│           └────────────┬────────────┘                          │
│                        │                                       │
│              ┌─────────┴─────────┐                            │
│              │   RP2350 MCU      │                            │
│              │   (Router)        │                            │
│              └─────────┬─────────┘                            │
│                        │                                       │
│         ┌──────────────┼──────────────┐                       │
│         │              │              │                          │
│         ▼              ▼              ▼                          │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│   │  Hailo   │  │  Camera  │  │  Sensors │                   │
│   │  -8L     │  │  Module  │  │  IMU/GPS │                   │
│   └──────────┘  └──────────┘  └──────────┘                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## V3 vs V2 Comparison

| Metric | V2 | V3 | Improvement |
|--------|-----|-----|-------------|
| Total weight | 280g | 120g | **57% lighter** |
| Volume | 350cm³ | 80cm³ | **77% smaller** |
| Battery life | 4 hours | 8 hours | **2x longer** |
| Head tracking latency | 50ms | 15ms | **70% faster** |
| Audio latency | 150ms | 30ms | **80% faster** |
| Cable count | 12 | 0 | **Zero loose cables** |
| IMU accuracy | ±5° | ±1° | **5x better** |
| GPS accuracy | Phone only | 1.5m CEP | **Standalone** |
| Thermal throttle | 100% (none) | Dynamic | **Sustained perf** |
| MTBF (est.) | 500 hours | 5000 hours | **10x reliability** |

---

## V3 Manufacturing Cost Estimate

| Component | Unit Cost (USD) | Quantity | Total |
|-----------|-----------------|----------|-------|
| Custom PCB (6-layer) | $25 | 1 | $25 |
| RP2350 MCU | $3 | 1 | $3 |
| Hailo-8L (integrated) | $30 | 1 | $30 |
| ESP32-S3 | $2 | 1 | $2 |
| OV5648 Camera | $8 | 1 | $8 |
| BMI270 IMU | $2 | 1 | $2 |
| u-blox M10S GPS | $6 | 1 | $6 |
| Bone conduction drivers | $4 | 2 | $8 |
| MEMS microphones | $1.50 | 2 | $3 |
| LiPo battery (3000mAh) | $8 | 1 | $8 |
| PCB connectors/FPC | $5 | - | $5 |
| CNC aluminum frame | $15 | 1 | $15 |
| Misc (resistors, caps) | $5 | - | $5 |
| **Total BOM** | | | **$120** |

**V3 Target Price: $349 (vs V2 ~$280 component cost alone)**

---

## V3 Development Roadmap

### Phase 1: Core Integration (Months 1-2)
- [ ] Design custom PCB with all components
- [ ] Prototype PCB fabrication
- [ ] Integrate Hailo-8L firmware
- [ ] Basic audio routing

### Phase 2: Sensor Fusion (Month 2-3)
- [ ] IMU calibration and fusion
- [ ] GPS integration
- [ ] Power management optimization
- [ ] Thermal testing

### Phase 3: Audio Refinement (Month 3-4)
- [ ] Beamforming microphone tuning
- [ ] Bone conduction driver calibration
- [ ] Spatial audio optimization
- [ ] BT LE Audio codec integration

### Phase 4: Industrial Design (Month 4-5)
- [ ] Frame ergonomics testing
- [ ] Heat dissipation validation
- [ ] IP54 weather sealing
- [ ] User comfort testing

### Phase 5: Production Prep (Month 5-6)
- [ ] FCC/CE certification testing
- [ ] Burn-in testing (1000 hours)
- [ ] User acceptance testing
- [ ] Documentation and certification

---

## Appendix: V3 Pinout Reference

### PCB Edge Connectors

| Pin | Function | Voltage |
|-----|----------|---------|
| 1 | 5V USB-C PD Input | 5-20V |
| 2 | GND | 0V |
| 3 | USB-C D+ | 0-3.3V |
| 4 | USB-C D- | 0-3.3V |
| 5 | Debug UART | 3.3V |
| 6 | SWDIO (RP2350) | 3.3V |
| 7 | SWCLK (RP2350) | 3.3V |
| 8 | FPC Camera (MIPI CSI) | 1.2V |

### Internal FPC Connections

| FPC | From | To |
|-----|------|-----|
| FPC1 | Camera Module | PCB CSI Connector |
| FPC2 | IMU/GPS Module | PCB Sensor Header |

---

## Summary

V3 transforms ProjectCortex from a research prototype into a production-ready wearable device:

1. **75% smaller** through custom PCB integration
2. **57% lighter** with optimized component selection
3. **Zero loose cables** via board-to-board connections
4. **8+ hour battery** with smart power gating
5. **Integrated audio** with bone conduction + beamforming mics
6. **Standalone GPS** without phone dependency
7. **IP54 weather resistance** for outdoor use
8. **10x reliability** through industrial design

---

**Author:** Haziq (@IRSPlays)
**Project:** ProjectCortex
**Document Version:** 1.0
**Last Updated:** March 2026
