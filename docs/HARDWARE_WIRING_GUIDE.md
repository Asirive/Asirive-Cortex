# ProjectCortex v2.0 — Hardware Wiring Guide

**Author:** Haziq (@IRSPlays)  
**Date:** January 2026  
**Target Board:** Raspberry Pi 5 (4GB)

---

## What You're Adding

| Module | Purpose | Interface | Cost (est.) |
|--------|---------|-----------|-------------|
| GPS (NEO-6M / GT-U7) | Location tracking | UART serial | ~RM15–25 |
| 9-axis IMU (BNO055) | Head orientation, fall detection | I2C | ~RM15–30 |
| Vibration Motor | Haptic alerts (already in code) | GPIO PWM | ~RM3–5 |
| Physical Button | Power on/off toggle | GPIO input | ~RM1–2 |

---

## 1. Raspberry Pi 5 GPIO Header Reference

The RPi5 40-pin header — pins you'll use are highlighted:

```
 3V3 [ 1][ 2] 5V
 SDA [ 3][ 4] 5V
 SCL [ 5][ 6] GND
      [ 7][ 8] UART_TX (GPIO 14)
 GND  [ 9][10] UART_RX (GPIO 15)
      [11][12] GPIO 18 ← VIBRATION MOTOR PWM
      ...
 GND  [25][26]
 SDA0 [27][28] SCL0
      [29][30] GND
      [31][32]
      [33][34] GND
      [35][36] GPIO 16 ← BUTTON
      [37][38]
 GND  [39][40]
```

Key pins:
- **Pin 1** = 3.3V power
- **Pin 2/4** = 5V power
- **Pin 6/9/14/20/25/30/34/39** = GND
- **Pin 8** = GPIO 14 (UART TX → GPS RX)
- **Pin 10** = GPIO 15 (UART RX ← GPS TX)
- **Pin 12** = GPIO 18 (PWM → vibration motor)
- **Pin 36** = GPIO 16 (button input)
- **Pin 3** = GPIO 2 (I2C SDA → IMU)
- **Pin 5** = GPIO 3 (I2C SCL → IMU)

---

## 2. GPS Module (NEO-6M or GT-U7)

### What to buy
- **Recommended:** "NEO-6M GPS Module" or "GT-U7 GPS Module" (both ≈RM15–25 on Shopee/Lazada)
- These come on a breakout board with a ceramic antenna — no soldering needed
- They output standard NMEA sentences at 9600 baud over UART (3.3V logic)

### Wiring

```
GPS Module      RPi5 Pins
──────────      ─────────
VCC      ──→   Pin 1  (3.3V)   ← IMPORTANT: use 3.3V not 5V
GND      ──→   Pin 6  (GND)
TX       ──→   Pin 10 (GPIO 15 / UART RX)
RX       ──→   Pin 8  (GPIO 14 / UART TX)
```

> ⚠️ Some NEO-6M boards work at 5V input but their serial logic is 3.3V, so connecting TX/RX directly to RPi5 3.3V GPIO is fine.

### Enable UART on RPi5

```bash
sudo raspi-config
# Interface Options → Serial Port
#   "Would you like a login shell over serial?" → No
#   "Would you like the serial port hardware to be enabled?" → Yes
# Reboot

# Verify device appears:
ls /dev/ttyAMA*   # Expected: /dev/ttyAMA0
# OR
ls /dev/serial*   # May appear as /dev/serial0
```

> On RPi5, the primary UART is `/dev/ttyAMA0`. If you see `/dev/ttyS0`, that also works.

### Install driver

```bash
pip install pyserial
```

### Quick test (after wiring + boot)

```bash
# Connect satellite view GPS — go near a window or outside
python3 -c "
import serial, time
s = serial.Serial('/dev/ttyAMA0', 9600, timeout=1)
for _ in range(20):
    line = s.readline().decode('ascii', errors='replace').strip()
    if line: print(line)
    time.sleep(0.5)
"
```

You should see NMEA sentences like:
```
\$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
\$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47
```

> First satellite fix ("cold start") can take up to 5 minutes outdoors. LED on module should blink every second when locked.

---

## 3. 9-Axis IMU (BNO055)

### What to buy
- **Recommended:** "GY-BNO055 Module" or "Adafruit BNO055" (~RM15–30)
- BNO055 has built-in sensor fusion — it gives you ready-to-use Euler angles and quaternions
- **Alternative:** MPU-9250 (cheaper, ~RM8–12, but requires manual fusion code)
- The software in this project supports **BNO055** natively. For MPU-9250 see note at end.

### Wiring (I2C)

```
BNO055 Module   RPi5 Pins
─────────────   ─────────
VIN / VCC ──→  Pin 1  (3.3V)
GND       ──→  Pin 6  (GND)
SDA       ──→  Pin 3  (GPIO 2 / I2C SDA)
SCL       ──→  Pin 5  (GPIO 3 / I2C SCL)
```

> The ADR/ADDR pin on the BNO055 sets the I2C address:
> - ADR = GND/Low → address **0x28** (default — matches config.yaml)
> - ADR = 3.3V/High → address **0x29**

### Enable I2C on RPi5

```bash
sudo raspi-config
# Interface Options → I2C → Yes
# Reboot

# Verify I2C bus:
ls /dev/i2c*   # Expected: /dev/i2c-1

# Scan for connected devices:
sudo apt install i2c-tools
i2cdetect -y 1
# Should show "28" at address 0x28 if BNO055 connected correctly
```

### Install driver

```bash
pip install adafruit-circuitpython-bno055
# Also needs:
pip install adafruit-blinka  # RPi board abstraction layer
```

Or if using smbus2 only:
```bash
pip install smbus2
```

### Quick test

```python
import board, busio
import adafruit_bno055

i2c = busio.I2C(board.SCL, board.SDA)
sensor = adafruit_bno055.BNO055_I2C(i2c)

print("Accelerometer:", sensor.acceleration)
print("Gyroscope:", sensor.gyro)
print("Magnetometer:", sensor.magnetic)
print("Euler angles:", sensor.euler)  # (heading, roll, pitch)
```

---

## 4. Vibration Motor (already wired in code)

### What to buy
- Any 3V DC vibration motor (~RM3–5) — the kind in mobile phones
- You **need a transistor** to switch it from GPIO (GPIO max is 16mA, motor needs more)

### Wiring

```
Component       Connection
─────────       ──────────
NPN Transistor  (e.g., 2N2222, BC547, S8050 — any general-purpose NPN)

  Base ─── 1kΩ resistor ─── GPIO 18 (Pin 12)
  Collector ─────────────── Motor (+)
  Emitter ────────────────── GND (Pin 6)

Motor (+) ─────────────────── Transistor Collector
Motor (-) ─────────────────── GND

Flyback diode (1N4001 or 1N4148):
  Cathode (+) ─── Motor (+)  [anode side towards GND]
  Anode  (-) ─── Motor (-)
```

Simplified diagram:
```
GPIO18 ──[1kΩ]──► Base(NPN)
                  Collector ──► Motor(+) ──[diode]─┐
                  Emitter ──► GND                  │
                                Motor(-) ──► GND ──┘
```

> The flyback diode protects GPIO from voltage spikes when the motor switches off. DON'T skip it.

Motor power: use **3.3V (Pin 1)** if motor is 3V rated, or **5V (Pin 2)** if 5V rated. Connect that supply rail to the motor (+) instead of the transistor collector directly if motor needs more current than transistor can handle.

### Already in the code
- `rpi5/layer0_guardian/haptic_controller.py` handles this on GPIO 18
- No extra steps needed — just physically wire it up as above

---

## 5. Physical Button (Power On/Off)

### What to buy
- Any momentary push button (~RM1–2)
- Or a latching switch if you want "press to stay on"
- **Use momentary** — software controls shutdown logic

### Wiring

```
Button Pin 1 ──→ GPIO 16 (Pin 36)
Button Pin 2 ──→ GND     (Pin 34)
```

That's it — no resistors needed. The software enables the RPi5's internal pull-up resistor on GPIO 16, so the pin reads HIGH normally and LOW when button is pressed.

```
     GPIO 16 ──── internal pull-up to 3.3V (HIGH normally)
         │
        [Button]
         │
        GND                   ← button press pulls GPIO 16 LOW
```

### Button behavior (implemented in code)
- **Short press** (< 2 seconds): trigger voice command listen (same as speaking to it)
- **Long press** (≥ 3 seconds): graceful system shutdown (runs `sudo shutdown -h now`)

---

## 6. Summary Wiring Table

| Wire | From | To |
|------|------|----|
| GPS VCC | GPS module VCC | RPi5 Pin 1 (3.3V) |
| GPS GND | GPS module GND | RPi5 Pin 6 (GND) |
| GPS TX → RPi RX | GPS module TX | RPi5 Pin 10 (GPIO 15) |
| GPS RX ← RPi TX | GPS module RX | RPi5 Pin 8 (GPIO 14) |
| IMU VCC | BNO055 VIN | RPi5 Pin 1 (3.3V) |
| IMU GND | BNO055 GND | RPi5 Pin 6 (GND) |
| IMU SDA | BNO055 SDA | RPi5 Pin 3 (GPIO 2) |
| IMU SCL | BNO055 SCL | RPi5 Pin 5 (GPIO 3) |
| Motor | Transistor circuit | GPIO 18 (Pin 12) |
| Button | Momentary button | GPIO 16 (Pin 36) ↔ GND |

---

## 7. Software Setup Checklist

```bash
# 1. Enable interfaces
sudo raspi-config  # Enable I2C, enable Serial (no login shell, yes hardware port)
sudo reboot

# 2. Install packages
pip install pyserial smbus2 adafruit-circuitpython-bno055 adafruit-blinka

# 3. Test GPS
python3 -c "import serial; s=serial.Serial('/dev/ttyAMA0',9600,timeout=2); [print(s.readline()) for _ in range(10)]"

# 4. Test IMU
i2cdetect -y 1  # Should show device at 0x28

# 5. Test button (GPIO 16)
python3 -c "
import RPi.GPIO as GPIO, time
GPIO.setmode(GPIO.BCM)
GPIO.setup(16, GPIO.IN, pull_up_down=GPIO.PUD_UP)
print('Press button...')
while True:
    print('State:', GPIO.input(16))
    time.sleep(0.2)
"
```

---

## 8. Notes

- **RPi5 vs RPi4 UART:** RPi5 uses `/dev/ttyAMA0` as the primary UART (not `/dev/ttyS0` like older models).
- **Multiple I2C devices:** You can attach BNO055 and other I2C devices on the same SDA/SCL bus. Each needs a unique address.
- **GPIO numbering:** All pin references use **BCM numbering** (the GPIO number, not physical pin number). The code uses BCM mode.
- **Power:** All sensors here run on 3.3V. Never connect 5V directly to GPIO pins — you'll damage the RPi.
