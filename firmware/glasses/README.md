# Glasses firmware (ESP32-S3-N16R8)

The glasses are a USB bridge with no AI. This firmware:

- streams the camera (UVC), the mics (UAC2) and ToF + IMU frames (CDC) to the box;
- plays the speaker audio and haptic patterns the box sends;
- makes one decision on its own: if the box's safety loop stops beating, it vibrates "degraded".

The protocol and USB layout are in `docs/architecture/GLASSES-USB.md`.

**Status (2026-11-26).** Builds with ESP-IDF 5.5.6 (Docker `espressif/idf:release-v5.5`, and in CI:
`.github/workflows/firmware.yml`): 0 warnings, app image 484 kB (6% of a 7.9 MB slot). Never run on hardware.

What has been tested on the server:

- the portable parts (framing, haptic player, fail-safe, button debouncer, USB descriptors), compiled with gcc;
- the box side, in `core/tests/test_glasses_link.py` and `core/tests/test_glasses_firmware.py`.

The first build needed only a missing FreeRTOS include in `imu.c`. Compiling says nothing about whether the
hardware modules (`tof.c`, `imu.c`, `camera.c`, `audio.c`, `haptic.c`) drive the real parts correctly.

Build without installing ESP-IDF (Docker, from this folder):

```
./scripts/fetch_uld.sh
docker run --rm -v "$PWD":/project -w /project espressif/idf:release-v5.5 \
  bash -c '. $IDF_PATH/export.sh && idf.py set-target esp32s3 && idf.py build'
```

## Parts (chosen 2026-11, nothing bought for the IMU or motors yet)

| Part | Choice | Why |
|:--|:--|:--|
| MCU | ESP32-S3-WROOM-1-N16R8 | USB OTG (full speed), DVP camera port, PDM, 8 MB PSRAM for JPEG buffers |
| ToF | VL53L7CX (nose bridge) | 8×8 zones, 60° square field of view, up to 3.5 m |
| IMU | LSM6DSO | 6-axis with a FIFO: the ESP drains it once per ToF frame, so the shared I2C bus never misses samples |
| Camera | OV5640 (DVP, 78 mm flex) | JPEG on the sensor, so no JPEG encoding on the ESP |
| Mics | 2× MP34DT01 (PDM) | one on the mouth side (left slot), one ambient (right slot) |
| Amp | MAX98357A + 2× 1511 speakers | I2S in, mono |
| Motors | 2× coin ERM (left and right temple), each through an AO3400 N-MOSFET with a BAT54 flyback diode | GPIO PWM at 20 kHz, no driver IC |
| Button | tactile switch to GND | internal pull-up |

## Pin map (proposed; the same table is in `main/board.h`)

| Function | GPIO | Notes |
|:--|:--|:--|
| Camera XCLK | 15 | LEDC timer 0, channel 0 |
| Camera SIOD / SIOC | 4 / 5 | SCCB on I2C1 |
| Camera D0–D7 | 11, 9, 8, 10, 12, 18, 17, 16 | ESP32-S3-EYE layout |
| Camera VSYNC / HREF / PCLK | 6 / 7 / 13 | |
| Camera PWDN / RESET | not wired | the module's pull-ups keep it on |
| I2C0 SDA / SCL (ToF + IMU) | 1 / 2 | 2.2 kΩ pull-ups (ToF at 1 MHz, IMU at 400 kHz) |
| ToF INT | 21 | 10 kΩ pull-up; ToF LPn tied high |
| IMU address | 0x6A | SDO/SA0 to GND |
| PDM CLK / DATA | 38 / 39 | mouth mic L/R pin to GND, ambient mic L/R pin to VDD |
| Amp BCLK / WS / DIN | 40 / 41 / 42 | SD_MODE high through 1 MΩ |
| Motor L / R | 47 / 48 | to the MOSFET gates (100 Ω series, 100 kΩ pull-down) |
| Button | 14 | to GND |
| USB D− / D+ | 19 / 20 | the cable to the box |
| UART0 TX / RX | 43 / 44 | test pads: logs, 115200 baud |
| BOOT | 0 | test pad: hold to GND at power-up to flash |

Avoid these pins:

- 26–32 (flash);
- 33–37 (octal PSRAM).

Spare pins: 3, 45 and 46. All three are strapping pins, so leave them unconnected at boot.

## Build and flash

You need ESP-IDF v5.5 (or 5.4 or later). Installing it is a one-time step that Haziq runs:

```
git clone -b release/v5.5 --recursive https://github.com/espressif/esp-idf ~/esp/esp-idf
~/esp/esp-idf/install.sh esp32s3
```

Then:

```
. ~/esp/esp-idf/export.sh
cd firmware/glasses
./scripts/fetch_uld.sh          # ST's VL53L7CX driver (BSD-3, not committed: it carries an 84 kB sensor blob)
idf.py build
idf.py -p /dev/ttyACM0 flash    # hold BOOT (GPIO0) while plugging in: the ROM's USB download mode
idf.py -p /dev/ttyUSB0 monitor  # logs come out on UART0 (43/44), not USB
```

After that, the box updates the firmware over A/B slots (`partitions.csv`). A new image that crashes before
`app_main` finishes is rolled back by the bootloader. The update path from the box (`ARTIFACT_KIND_MCU_FIRMWARE`
over USB) is **not built**.

## Bring-up on the first assembled glasses

1. `lsusb` shows `303a:8a51 Asirive Glasses`.
2. Install the udev rule: `core/deploy/udev/70-cortex-glasses.rules`. Then `/dev/cortex-glasses-safety` and
   `/dev/cortex-glasses-camera` appear.
3. `python -m cortex_core.safety.glasses --grid`: hold a hand at the top-left of the view; the top-left zones must
   drop. If the wrong zones drop, set `ZONE_FLIP_LR`, `ZONE_FLIP_UD` or `ZONE_TRANSPOSE` in `glasses.py`.
4. `python -m cortex_core.safety.glasses --imu`: look up and pitch goes positive; right ear down and roll goes
   positive. If not, fix `IMU_AXES`.
5. `python -m cortex_core.safety.glasses --buzz --side left`: the left motor runs.
6. Camera: `ffplay /dev/cortex-glasses-camera`. Record the real frame rate.
7. Audio: find the card with `arecord -l`, then `arecord -D hw:N -c 2 -r 16000 -f S16_LE x.wav` and `aplay -D hw:N` back.
8. Stop `cortex-safety` while the glasses are attached. Within 1.5 s they vibrate long-short-long, and again every
   5 s.

## Known gaps

- **OV5640 autofocus** is not driven. esp32-camera does not upload the AF firmware, so the lens stays at its rest
  position.
- **Firmware update** from the box over USB is not built. Only the A/B partitions and rollback are in place.
- **Component versions build, but are untested on hardware.** `dependencies.lock` pins IDF 5.5.6,
  `espressif/tinyusb 0.21.0~6` and `esp32-camera 2.2.0`. esp32-camera must use the new `i2c_master` driver: ESP-IDF refuses to run the legacy and
  new I2C drivers in one image, and the ToF/IMU bus uses the new one.
- **USB PID** 0x8A51 is a placeholder under Espressif's VID.
