"""
Power / UPS monitor for Asirive Cortex.

Reads battery and UPS state from the host and pushes it to the
DashboardState so the FULL mode TUI can show "how long until this
thing dies?" — a question judges will absolutely ask.

Data sources, in priority order:
  1. Linux sysfs at /sys/class/power_supply/*  — works for almost every
     USB-PD power supply, USB UPS, and most I2C-attached UPS HATs that
     register themselves as a power supply (Geekworm, PiJuice, Waveshare
     UPS HAT, etc.).
  2. psutil.sensors_battery()  — cross-platform fallback (laptop battery,
     generic ACPI). Returns nothing on RPi5.
  3. Manual config overrides via `power.manual` in config.yaml — useful
     for demo / dry-run when no UPS is connected yet.

The monitor is read-only — it never *controls* charging or shutdown. A
separate process (or systemd service) should handle graceful shutdown
when the battery hits the configured low-water mark.

Usage from main.py:
    self.power_monitor = PowerMonitor(self.config.get("power", {}))
    self.power_monitor.publish(self.dashboard_state)   # call @ ~1Hz

Or use the convenience method on CortexSystem (added separately).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Default field shape for the DashboardState `power` field. Anything not in
# this template is silently ignored by DashboardState.update().
def _default_power() -> Dict[str, Any]:
    return {
        "available": False,           # True = a real power source was found
        "source": "none",             # "sysfs" | "psutil" | "manual" | "none"
        "battery_pct": -1,            # 0..100, -1 = unknown
        "voltage_v": 0.0,             # Volts (e.g. 3.7 Li-ion, 4.2 full)
        "current_ma": 0.0,            # mA — positive = charging, negative = discharging
        "power_w": 0.0,               # Watts (V × I / 1000) — easy to read
        "charging": False,            # True = actively charging
        "status": "unknown",          # "charging" | "discharging" | "full" | "not_charging" | "unknown"
        "time_remaining_s": -1,       # seconds remaining at current draw (-1 = unknown)
        "capacity_wh": 0.0,           # full-charge capacity in Watt-hours
        "energy_now_wh": 0.0,         # current energy in Watt-hours
        "power_supply_name": "",      # e.g. "battery", "axp20x-battery", "UPS1"
        "health_pct": -1,             # battery health vs design capacity
        "low_battery": False,         # True = below low-water mark
        "last_update_ts": 0.0,        # time.time() of last successful read
    }


class PowerMonitor:
    """Read battery / UPS state from the host.

    Constructor is cheap; `publish()` is called at ~1Hz from the main loop
    and pushes a fresh snapshot into the DashboardState. All errors are
    caught and logged at debug level so a flaky sensor never kills the
    main loop.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.low_water_pct = float(self.config.get("low_water_pct", 15.0))
        self.manual = self.config.get("manual", None)  # for demo without UPS
        self._last_publish_ts: float = 0.0
        self._publish_interval_s: float = float(self.config.get("publish_interval_s", 1.0))
        self._cached: Dict[str, Any] = _default_power()
        self._platform: str = "unknown"
        # Try to discover what's available at boot — saves 5ms per read.
        self._discover_platform()

    def _discover_platform(self) -> None:
        """Decide where to read power state from. Idempotent."""
        if self.manual is not None:
            self._platform = "manual"
            return
        if sysfs_power_supply_dir().is_dir():
            self._platform = "sysfs"
            return
        try:
            import psutil  # noqa
            self._platform = "psutil"
        except Exception:
            self._platform = "none"

    def publish(self, state) -> float:
        """Push a fresh power snapshot into the DashboardState.

        Args:
            state: DashboardState (or anything with an `update(**kwargs)`
                method). Receives the `power=...` field.

        Returns:
            The age in seconds of the snapshot we just published (0.0 for
            fresh, useful for diagnostics).
        """
        now = time.time()
        snap = self._read()
        snap["last_update_ts"] = now
        # Always show a low-battery flag if we've crossed the water mark
        pct = snap.get("battery_pct", -1)
        if 0 <= pct <= self.low_water_pct and not snap.get("charging", False):
            snap["low_battery"] = True
        if state is not None:
            try:
                state.update(power=snap)
            except Exception as e:
                logger.debug(f"PowerMonitor: state.update failed: {e}")
        self._cached = snap
        self._last_publish_ts = now
        return 0.0

    def snapshot(self) -> Dict[str, Any]:
        """Return the last published snapshot (for tests / health checks)."""
        return dict(self._cached)

    # --- internal read paths ---

    def _read(self) -> Dict[str, Any]:
        """Dispatch to the right reader for this platform."""
        try:
            if self._platform == "sysfs":
                return self._read_sysfs()
            if self._platform == "psutil":
                return self._read_psutil()
            if self._platform == "manual":
                return self._read_manual()
        except Exception as e:
            logger.debug(f"PowerMonitor._read({self._platform}) error: {e}")
        return _default_power()

    def _read_sysfs(self) -> Dict[str, Any]:
        """Read every /sys/class/power_supply/<name>/ entry and pick the
        most informative one (preferring 'battery' type with capacity)."""
        snap = _default_power()
        base = sysfs_power_supply_dir()
        if not base.is_dir():
            return snap
        best = None
        best_score = -1
        for entry in sorted(base.iterdir()):
            type_path = entry / "type"
            try:
                ptype = type_path.read_text().strip() if type_path.exists() else ""
            except Exception:
                continue
            # We want a Battery (Mains/USB are nice for charging state but
            # not for capacity). Score batteries higher.
            if "Battery" in ptype:
                score = 10
            elif "Mains" in ptype or "USB" in ptype:
                score = 1
            else:
                continue
            if score > best_score:
                best = entry
                best_score = score
        if best is None:
            return snap
        snap["available"] = True
        snap["source"] = "sysfs"
        snap["power_supply_name"] = best.name
        # Capacity (percent)
        _try_read_int(best / "capacity", "battery_pct", snap, scale=1.0)
        # Voltage (in µV on sysfs — convert to V)
        if _try_read_int(best / "voltage_now", "voltage_uv", snap):
            snap["voltage_v"] = float(snap.pop("voltage_uv", 0)) / 1_000_000.0
        # Current (in µA on sysfs — positive=charging, negative=discharging
        # per the Linux power_supply convention)
        if _try_read_int(best / "current_now", "current_ua", snap):
            snap["current_ma"] = float(snap.pop("current_ua", 0)) / 1_000.0
        # Power = V × I (W)
        v = snap.get("voltage_v", 0.0)
        i = snap.get("current_ma", 0.0)
        if v > 0 and i != 0:
            snap["power_w"] = abs(v * i / 1000.0)
        # Status
        _try_read_text(best / "status", "status", snap)
        if snap.get("status") == "Charging":
            snap["charging"] = True
        elif snap.get("status") == "Full":
            snap["charging"] = False
            snap["battery_pct"] = max(snap.get("battery_pct", -1), 100)
        # Time to empty / full
        if _try_read_int(best / "time_to_empty_now", "tte_s", snap):
            snap["time_remaining_s"] = int(snap.pop("tte_s", -1))
        elif _try_read_int(best / "time_to_full_now", "ttf_s", snap):
            # If charging, time-to-full is a more useful number
            snap["time_remaining_s"] = int(snap.pop("ttf_s", -1))
        # Energy
        _try_read_int(best / "energy_full_design", "efd_uwh", snap)
        if "efd_uwh" in snap:
            snap["capacity_wh"] = float(snap.pop("efd_uwh")) / 1_000_000.0
        _try_read_int(best / "energy_now", "en_uwh", snap)
        if "en_uwh" in snap:
            snap["energy_now_wh"] = float(snap.pop("en_uwh")) / 1_000_000.0
        # Health
        _try_read_int(best / "health", "health", snap, scale=1.0)
        return snap

    def _read_psutil(self) -> Dict[str, Any]:
        """Fallback: psutil.sensors_battery() (laptop / ACPI)."""
        snap = _default_power()
        try:
            import psutil
            b = psutil.sensors_battery()
            if b is None:
                return snap
            snap["available"] = True
            snap["source"] = "psutil"
            snap["power_supply_name"] = "psutil"
            pct = b.percent
            snap["battery_pct"] = float(pct)
            secs = b.secsleft
            if secs and secs > 0 and secs < (100 * 3600):
                # psutil uses psutil.POWER_TIME_UNLIMITED for "unlimited"
                snap["time_remaining_s"] = int(secs)
            snap["charging"] = bool(b.power_plugged)
            snap["status"] = "charging" if b.power_plugged else "discharging"
        except Exception:
            pass
        return snap

    def _read_manual(self) -> Dict[str, Any]:
        """Demo / dry-run values from config — used when no UPS hardware
        is connected (e.g. on a laptop or in CI)."""
        snap = _default_power()
        if not isinstance(self.manual, dict):
            return snap
        snap["available"] = True
        snap["source"] = "manual"
        snap["power_supply_name"] = "manual"
        snap.update({
            k: v for k, v in self.manual.items() if k in snap
        })
        return snap


# --- helpers ---


def sysfs_power_supply_dir() -> Path:
    """Path to /sys/class/power_supply on Linux, or a non-existent path
    on other platforms (so .is_dir() returns False cleanly)."""
    return Path("/sys/class/power_supply")


def _try_read_int(path: Path, key: str, out: Dict[str, Any], scale: float = 1.0) -> bool:
    """Read an integer from a sysfs file, store in out[key] * scale. Returns
    True on success, False on any error (file missing, NaN, permission)."""
    try:
        if not path.exists():
            return False
        raw = path.read_text().strip()
        if not raw:
            return False
        out[key] = int(float(raw)) * scale
        return True
    except Exception:
        return False


def _try_read_text(path: Path, key: str, out: Dict[str, Any]) -> bool:
    try:
        if not path.exists():
            return False
        out[key] = path.read_text().strip()
        return True
    except Exception:
        return False
