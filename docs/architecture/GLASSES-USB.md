# Glasses ↔ box over USB

The glasses' ESP32-S3 is a bridge with no AI. It connects to the box with one USB cable, which also powers it. The
box sees one composite full-speed device with three functions:

| Function | USB class | Box side | Owner on the box |
|:--|:--|:--|:--|
| Camera (OV5640) | UVC 1.5, MJPEG 640×480 at up to 10 fps, bulk | `/dev/cortex-glasses-camera` (V4L2) | brain (perception) |
| Mics (2× MP34DT01) and speaker (MAX98357A) | UAC2, 16 kHz 16-bit: mic stereo in (L mouth, R ambient), speaker mono out | ALSA card "Asirive Glasses" (`arecord -l`) | brain (voice) |
| Safety channel | CDC-ACM | `/dev/cortex-glasses-safety` | `safety` service only |

The udev rule `core/deploy/udev/70-cortex-glasses.rules` creates both symlinks.

The firmware is in `firmware/glasses/` and the box side of the safety channel is in
`core/cortex_core/safety/glasses.py`. **Nothing here has run on hardware yet.**

## Why the safety channel is its own interface

`safety` must not depend on the brain (`core/AGENTS.md`, section 3). The safety channel therefore has its own
interface, port and process:

- ToF frames go straight to `safety`.
- Haptic patterns come straight from it.
- A crashed brain cannot block it.

Button presses also arrive on this channel. `safety` forwards each press to the brain through a named pipe
(`/run/cortex/button.fifo`, one line per press: `tap 12.345` or `long 12.345`). The write never blocks, so a
missing or slow brain drops the press and does not stall safety. The glasses tick the motors on every press
themselves, so the wearer always feels it.

## Endpoint budget

The ESP32-S3's USB controller has 6 endpoints besides EP0, and at most 5 of all endpoints (EP0 included) can be IN.
The tests in `core/tests/test_glasses_firmware.py` check every number in this table.

| EP | Dir | Type | Size | Use |
|:--|:--|:--|--:|:--|
| 0x81 | IN | bulk | 64 | video |
| 0x82 | IN | iso, async | 68 | mic: 16 samples × 2 ch × 2 B per ms, plus one spare sample |
| 0x02 | OUT | iso, adaptive | 34 | speaker |
| 0x83 | IN | interrupt | 8 | CDC notify |
| 0x84 | IN | bulk | 64 | CDC data |
| 0x04 | OUT | bulk | 64 | CDC data |

There is no IN endpoint left for speaker feedback. The speaker is adaptive: the I2S clock and the host's clock
drift against each other, and the speaker task pads or drops a few milliseconds when its buffer runs out or fills.

Bandwidth on full speed (12 Mbit/s, about 1 MB/s usable):

| Stream | Rate |
|:--|--:|
| Audio (iso, reserved every frame) | ~100 kB/s |
| ToF frames | ~4 kB/s (240 B × 15 Hz) |
| Video | the rest, about 0.8 MB/s at best |

A 640×480 JPEG is about 25–45 kB, so 10 fps is what the UVC descriptor declares. The real rate has not been measured.

## Safety channel protocol (version 1)

Every message is one frame: `COBS(type u8, seq u8, payload, crc16 LE)` followed by a `0x00` delimiter.

- **CRC:** CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over type, seq and payload.
- **Byte order:** all integers little-endian, floats IEEE-754 single.
- **Errors:** a frame with a bad CRC or bad COBS is dropped and counted. The receiver resyncs at the next `0x00`.
- **Frame size:** at most 512 bytes encoded.

### Glasses → box

| Type | Name | Payload (`struct` format) | When |
|:--|:--|:--|:--|
| 0x01 | TOF | `<I3f3fH64H64B` (222 B), described below | every ToF frame, 15 Hz |
| 0x02 | STATUS | `<HHIHHH`: fw_version, flags, uptime_ms, tof_errors, imu_errors, usb_drops | 1 Hz |
| 0x03 | BUTTON | `<IB`: t_us, kind (1 tap, 2 long) | each press |
| 0x04 | HELLO | `<HH16s`: protocol version, fw_version, build string | port opened, or beats resume |

The TOF payload fields:

- **t_us:** time the frame was read, on the glasses' clock in µs. It wraps at 2³², and the box unwraps it.
- **accel:** mean specific force over the frame, in g, chip axes.
- **dtheta:** rotation summed over the frame from the gyro, in rad, chip axes.
- **imu_n:** number of IMU samples in those sums. 0 means no IMU data: accel is (0,0,0) and the box's tilt filter
  holds its last estimate.
- **mm[64]:** distance per zone in the ULD's zone order. 0 means no target.
- **status[64]:** the ULD target status. The box keeps statuses 5 and 9 only.

The STATUS flags:

| Bit | Flag | Meaning |
|--:|:--|:--|
| 0 | TOF | sensor ranging |
| 1 | IMU | IMU found |
| 2 | CAM | camera ready |
| 3 | MIC | mics ready |
| 4 | AMP | amp ready |
| 5 | HOST | box beats arriving |
| 6 | FAILSAFE | box beats lost |

### Box → glasses

| Type | Name | Payload | When |
|:--|:--|:--|:--|
| 0x10 | HAPTIC | prio u8, n u8 (≤ 12), then n × (left u8, right u8, ms u16) | each warning |
| 0x11 | BEAT | empty | every 0.5 s while `safety` runs |

**HAPTIC priority:** 0 is info (tick), 1 is a warning, 2 is degraded. A pattern of equal or higher priority
replaces the one playing; a lower one is dropped. Left and right are PWM duty values from 0 to 255.

**Fail-safe.** After the first BEAT, if no BEAT arrives for 1.5 s (three missed), the glasses vibrate "degraded"
on their own and repeat it every 5 s until beats resume. The pattern is long, short, long on both motors, the same
as `glasses.pattern("degraded")`. The glasses never fire this before the first BEAT, so a box that has not started
`safety` yet causes no false alarm.

## Mounting maps (unverified)

The box turns ULD zone order and chip axes into the safety engine's frame using the constants at the top of
`glasses.py`: `ZONE_FLIP_LR`, `ZONE_FLIP_UD`, `ZONE_TRANSPOSE` and `IMU_AXES`. They are set to identity until
someone checks them on the first assembled glasses:

```
python -m cortex_core.safety.glasses --grid   # hand at the top-left of view: the top-left of the grid must drop
python -m cortex_core.safety.glasses --imu    # look up: pitch goes positive; right ear down: roll goes positive
python -m cortex_core.safety.glasses --buzz --side left
```
