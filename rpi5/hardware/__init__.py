"""
rpi5.hardware — Physical peripheral drivers

Provides drivers for sensors and actuators connected to the Raspberry Pi 5 GPIO:

    GPSHandler    — NEO-6M / GT-U7 UART serial GPS reader
    IMUHandler    — BNO055 9-axis IMU (I2C, NDOF fusion mode)
    ButtonHandler — Momentary push-button (short/long press detection)

The vibration motor is handled by the existing
rpi5.layer0_guardian.haptic_controller.HapticController.

All drivers support mock mode — they degrade gracefully when running on
a laptop without the actual hardware (RPi.GPIO / pyserial /
adafruit-circuitpython-bno055 not installed).
"""

from .gps_handler import GPSHandler, GPSFix
from .fused_gps import FusedGPSHandler
from .imu_handler import IMUHandler, IMUReading
from .button_handler import ButtonHandler

__all__ = [
    "GPSHandler",
    "GPSFix",
    "FusedGPSHandler",
    "IMUHandler",
    "IMUReading",
    "ButtonHandler",
]
