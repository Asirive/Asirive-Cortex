"""
Layer 0: Haptic Controller - GPIO Vibration Motor Control

This module controls the PWM vibration motor for haptic feedback.
Provides proximity-based vibration patterns for safety alerts.

HARDWARE:
- GPIO Pin: 18 (default, configurable)
- Vibration Motor: PWM-controlled (0-100% duty cycle)
- Frequency: 1kHz (standard for vibration motors)

VIBRATION PATTERNS:
- Continuous: 100% intensity (immediate danger)
- Fast Pulse: 70% intensity, 200ms on/off (near objects)
- Slow Pulse: 40% intensity, 500ms on/off (far objects)

LAPTOP MODE:
When running on laptop (not Raspberry Pi), this module uses mock GPIO
to simulate haptic feedback without requiring actual hardware.

Author: Haziq (@IRSPlays)
Competition: Young Innovators Awards (YIA) 2026
"""

import logging
import time
import sys
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import RPi.GPIO (only available on Raspberry Pi)
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.info("ℹ️ RPi.GPIO not available (laptop mode)")


class HapticController:
    """
    Controls PWM vibration motor for safety alerts.
    
    Provides proximity-based haptic feedback patterns.
    """
    
    def __init__(
        self,
        gpio_pin: int = 18,
        pwm_frequency: int = 1000,
        enabled: bool = True
    ):
        """
        Initialize haptic controller.
        
        Args:
            gpio_pin: GPIO pin number (BCM mode)
            pwm_frequency: PWM frequency in Hz (default: 1kHz)
            enabled: Enable GPIO control (False for laptop testing)
        """
        self.gpio_pin = gpio_pin
        self.pwm_frequency = pwm_frequency
        self.enabled = enabled and GPIO_AVAILABLE
        self.pwm = None
        
        if self.enabled:
            try:
                # Setup GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(gpio_pin, GPIO.OUT)
                
                # Initialize PWM
                self.pwm = GPIO.PWM(gpio_pin, pwm_frequency)
                self.pwm.start(0)  # Start with 0% duty cycle (off)
                
                logger.info(f"✅ Haptic Controller initialized (GPIO {gpio_pin}, {pwm_frequency}Hz)")
            except Exception as e:
                logger.error(f"❌ Failed to initialize GPIO: {e}")
                self.enabled = False
        else:
            logger.info("ℹ️ Haptic Controller in MOCK mode (laptop testing)")
    
    def continuous(self, intensity: int = 100) -> None:
        """
        Continuous vibration (immediate danger).
        
        Args:
            intensity: Vibration intensity (0-100%)
        """
        if self.enabled and self.pwm:
            try:
                self.pwm.ChangeDutyCycle(intensity)
                logger.debug(f"🔊 Haptic: CONTINUOUS ({intensity}%)")
            except Exception as e:
                logger.error(f"❌ Haptic control failed: {e}")
        else:
            # Mock mode (laptop)
            logger.info(f"🔊 [MOCK] Haptic: CONTINUOUS ({intensity}%)")
    
    def pulse(
        self,
        intensity: int = 70,
        duration: float = 0.2,
    ) -> None:
        """
        Pulsed vibration (near/far objects). Non-blocking, single pulse.
        
        Args:
            intensity: Vibration intensity (0-100%)
            duration: Pulse duration in seconds
        """
        def _do_pulse():
            if self.enabled and self.pwm:
                try:
                    self.pwm.ChangeDutyCycle(intensity)
                    time.sleep(duration)
                    self.pwm.ChangeDutyCycle(0)
                    logger.debug(f"🔊 Haptic: PULSE ({intensity}%, {duration}s)")
                except Exception as e:
                    logger.error(f"❌ Haptic control failed: {e}")

        if self.enabled and self.pwm:
            threading.Thread(target=_do_pulse, daemon=True).start()
        else:
            # Mock mode (laptop)
            logger.info(f"🔊 [MOCK] Haptic: PULSE ({intensity}%, {duration}s)")
    
    def stop(self) -> None:
        """Stop all vibration."""
        if self.enabled and self.pwm:
            try:
                self.pwm.ChangeDutyCycle(0)
                logger.debug("🔇 Haptic: STOPPED")
            except Exception as e:
                logger.error(f"❌ Haptic control failed: {e}")
        else:
            # Mock mode (laptop)
            logger.debug("🔇 [MOCK] Haptic: STOPPED")
    
    def cleanup(self) -> None:
        """Release GPIO resources."""
        if self.enabled:
            try:
                if self.pwm:
                    self.pwm.stop()
                GPIO.cleanup(self.gpio_pin)
                logger.info("🧹 Haptic Controller cleaned up")
            except Exception as e:
                logger.error(f"❌ GPIO cleanup failed: {e}")
        else:
            logger.info("🧹 [MOCK] Haptic Controller cleaned up")


# Example usage (for testing):
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize haptic controller (mock mode for laptop)
    haptic = HapticController(enabled=False)
    
    print("\n🔊 Testing Haptic Patterns:\n")
    
    # Test continuous vibration (immediate danger)
    print("1. Continuous (immediate danger)...")
    haptic.continuous(intensity=100)
    time.sleep(2)
    haptic.stop()
    time.sleep(1)
    
    # Test fast pulse (near objects)
    print("2. Fast pulse (near objects)...")
    for _ in range(3):
        haptic.pulse(intensity=70, duration=0.2)
    time.sleep(1)
    
    # Test slow pulse (far objects)
    print("3. Slow pulse (far objects)...")
    for _ in range(3):
        haptic.pulse(intensity=40, duration=0.5)
    time.sleep(1)
    
    # Cleanup
    print("\n✅ Test complete")
    haptic.cleanup()
