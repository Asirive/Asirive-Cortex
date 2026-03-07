"""
Button Handler - Physical GPIO Momentary Button

Detects short (tap) and long (hold) button presses on a GPIO pin with
proper hardware debounce. Wire a momentary button between the GPIO pin
and GND — the internal pull-up resistor holds the pin HIGH at rest.

HARDWARE:
- Button type: Momentary push-button (normally open)
- GPIO pin:    16 (BCM, RPi5 physical Pin 36)  ← configurable
- GND pin:     Pin 34 (GND)
- No external resistors needed — internal pull-up is used

WIRING:
    Button leg 1 ── GPIO 16 (Pin 36)
    Button leg 2 ── GND     (Pin 34)

BEHAVIOR:
    Short press  (< 2s):  fires on_short_press callback
    Long press   (≥ 3s):  fires on_long_press callback
    Press + hold (≥ 5s):  fires on_very_long_press callback
                          (default: triggers system shutdown)

Author: Haziq (@IRSPlays)
Date: January 2026
"""

import logging
import subprocess
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.info("ℹ️ RPi.GPIO not available — button in mock mode")


class ButtonHandler:
    """
    Physical GPIO button with short/long press detection.

    Runs a background polling thread to monitor button state with
    a 50ms debounce window.

    Usage:
        btn = ButtonHandler(gpio_pin=16)
        btn.on_short_press = lambda: print("short!")
        btn.on_long_press  = lambda: print("long!")
        btn.start()
        # ... system running ...
        btn.stop()
    """

    # Timing thresholds (seconds)
    DEBOUNCE_S        = 0.05   # 50ms debounce
    SHORT_PRESS_MAX   = 2.0    # < 2s   → short press
    LONG_PRESS_MIN    = 3.0    # ≥ 3s   → long press
    VERY_LONG_PRESS   = 5.0    # ≥ 5s   → very long (shutdown)

    def __init__(
        self,
        gpio_pin: int = 16,
        enabled: bool = True,
        auto_shutdown: bool = True,
    ):
        """
        Initialise button handler.

        Args:
            gpio_pin:      BCM GPIO pin number (default 16)
            enabled:       Set False to run in mock mode (laptop dev)
            auto_shutdown: If True, very-long press triggers system shutdown
        """
        self._pin = gpio_pin
        self._enabled = enabled and GPIO_AVAILABLE
        self._auto_shutdown = auto_shutdown

        # Public callbacks — assign before calling start()
        self.on_short_press: Optional[Callable[[], None]] = None
        self.on_long_press: Optional[Callable[[], None]] = None
        self.on_very_long_press: Optional[Callable[[], None]] = None

        self._thread: Optional[threading.Thread] = None
        self._running = False

        if not self._enabled:
            logger.info(f"ℹ️ ButtonHandler GPIO {gpio_pin} in MOCK mode")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Set up GPIO and start the monitoring thread.

        Returns:
            True on success, False on failure.
        """
        if not self._enabled:
            logger.info("🔘 Button mock mode — start() is a no-op")
            return True

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            logger.info(f"✅ Button on GPIO {self._pin} (BCM) with internal pull-up")
        except Exception as exc:
            logger.error(f"❌ Button GPIO setup failed: {exc}")
            self._enabled = False
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="button-monitor"
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop the monitoring thread and release GPIO."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if self._enabled:
            try:
                GPIO.cleanup(self._pin)
            except Exception:
                pass
        logger.info("🛑 Button handler stopped")

    # ------------------------------------------------------------------
    # Background monitoring loop
    # ------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        """
        Poll the button pin state.

        Pin is HIGH at rest (pull-up active).
        Pin goes LOW when button is pressed.
        """
        logger.debug(f"Button monitor thread started on GPIO {self._pin}")
        prev_state = GPIO.HIGH  # Track previous state for edge detection

        while self._running:
            state = GPIO.input(self._pin)

            # Falling edge: button pressed (HIGH → LOW)
            if prev_state == GPIO.HIGH and state == GPIO.LOW:
                time.sleep(self.DEBOUNCE_S)  # Debounce
                if GPIO.input(self._pin) == GPIO.LOW:  # Still pressed after debounce
                    self._handle_press()

            prev_state = state
            time.sleep(0.02)  # 20ms poll interval

        logger.debug("Button monitor thread stopped")

    def _handle_press(self) -> None:
        """
        Measure hold duration and fire the appropriate callback.

        Blocks until button is released or very-long threshold reached.
        """
        press_start = time.monotonic()
        logger.debug("🔘 Button pressed — measuring hold duration")

        # Wait for release (or very-long press timeout)
        while GPIO.input(self._pin) == GPIO.LOW and self._running:
            held = time.monotonic() - press_start
            if held >= self.VERY_LONG_PRESS:
                logger.info(f"🔘 Very-long press ({held:.1f}s) — triggering shutdown")
                self._fire(self.on_very_long_press)
                if self._auto_shutdown:
                    self._do_shutdown()
                # Wait for release so we don't re-trigger
                while GPIO.input(self._pin) == GPIO.LOW:
                    time.sleep(0.1)
                return
            time.sleep(0.05)

        held = time.monotonic() - press_start

        if held < self.DEBOUNCE_S:
            return  # Noise / bounce — ignore

        if held < self.SHORT_PRESS_MAX:
            logger.info(f"🔘 Short press ({held:.2f}s)")
            self._fire(self.on_short_press)
        elif held >= self.LONG_PRESS_MIN:
            logger.info(f"🔘 Long press ({held:.2f}s)")
            self._fire(self.on_long_press)
        else:
            logger.debug(f"🔘 Medium press ({held:.2f}s) — ignored")

    @staticmethod
    def _fire(callback: Optional[Callable]) -> None:
        """Call callback in a daemon thread so it doesn't block monitoring."""
        if callback is None:
            return
        try:
            t = threading.Thread(target=callback, daemon=True)
            t.start()
        except Exception as exc:
            logger.error(f"Button callback error: {exc}")

    @staticmethod
    def _do_shutdown() -> None:
        """Perform a graceful OS shutdown."""
        logger.warning("🛑 System shutdown initiated by button hold")
        try:
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        except Exception as exc:
            logger.error(f"Shutdown command failed: {exc}")
