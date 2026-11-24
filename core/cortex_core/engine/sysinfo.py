"""System numbers for the LFM baseline and the dev TUI: temperatures, memory, CPU load, power.

Every path is a parameter so tests (and Windows dev machines) can point at fake trees. Nothing here
raises: a missing or unreadable file means "unknown" (None or empty).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _kb_field(text: str, name: str) -> Optional[int]:
    for line in text.splitlines():
        if line.startswith(name + ":"):
            try:
                return int(line.split(":", 1)[1].split()[0])
            except (ValueError, IndexError):
                return None
    return None


def read_temps_c(root: Path = Path("/sys/class/thermal")) -> dict[str, float]:
    """{zone type: degrees C} for every readable thermal zone."""
    out: dict[str, float] = {}
    try:
        zones = sorted(root.glob("thermal_zone*"))
    except OSError:
        return out
    for z in zones:
        kind, temp = _read(z / "type"), _read(z / "temp")
        if kind is None or temp is None:
            continue
        try:
            out[kind] = int(temp) / 1000
        except ValueError:
            continue
    return out


def read_peak_rss_mb(pid: int, proc: Path = Path("/proc")) -> Optional[float]:
    """Peak resident memory (VmHWM) of a process in MB."""
    text = _read(proc / str(pid) / "status")
    kb = _kb_field(text, "VmHWM") if text else None
    return None if kb is None else kb / 1024


def read_mem_used_mb(proc: Path = Path("/proc")) -> Optional[float]:
    """System memory in use (MemTotal - MemAvailable) in MB."""
    text = _read(proc / "meminfo")
    if not text:
        return None
    total, avail = _kb_field(text, "MemTotal"), _kb_field(text, "MemAvailable")
    return None if total is None or avail is None else (total - avail) / 1024


def read_cpu_times(proc: Path = Path("/proc")) -> Optional[tuple[int, int]]:
    """(busy, total) jiffies from the aggregate cpu line; idle counts idle + iowait."""
    text = _read(proc / "stat")
    if not text:
        return None
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "cpu":
            try:
                nums = [int(x) for x in parts[1:]]
            except ValueError:
                return None
            total = sum(nums)
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            return total - idle, total
    return None


def cpu_load(prev: tuple[int, int], cur: tuple[int, int]) -> float:
    """Busy fraction (0.0-1.0) between two read_cpu_times samples."""
    dt = cur[1] - prev[1]
    return 0.0 if dt <= 0 else (cur[0] - prev[0]) / dt


def read_power_w(root: Path = Path("/sys/class/power_supply")) -> Optional[float]:
    """Watts from the first online supply reporting a non-zero power_now, else voltage_now x current_now.

    Offline supplies and zero readings are skipped: an idle USB-C port reads 0 V / 0 A, which means
    "not measured here", not "the board draws 0 W".
    """
    try:
        supplies = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return None
    for s in supplies:
        if (_read(s / "online") or "").strip() == "0":
            continue
        p = _read(s / "power_now")
        if p is not None:
            try:
                if int(p) != 0:
                    return abs(int(p)) / 1e6
            except ValueError:
                pass
        v, c = _read(s / "voltage_now"), _read(s / "current_now")
        if v is not None and c is not None:
            try:
                w = abs(int(v) * int(c)) / 1e12
                if w != 0:
                    return w
            except ValueError:
                pass
    return None
