"""What the dev TUI shows: live system numbers plus the latest baseline and NPU probe files."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cortex_core.engine import sysinfo


@dataclass
class Snapshot:
    temps_c: dict[str, float]
    mem_used_mb: Optional[float]
    cpu_load: Optional[float]
    power_w: Optional[float]
    baseline: Optional[dict]
    npu: Optional[dict]


def fmt(value: Optional[float], unit: str, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f} {unit}"


def _json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class Collector:
    def __init__(self, state_dir: Path = Path("/var/lib/cortex"), proc: Path = Path("/proc"),
                 thermal: Path = Path("/sys/class/thermal"), power: Path = Path("/sys/class/power_supply")):
        self.state_dir, self.proc, self.thermal, self.power = state_dir, proc, thermal, power
        self._prev_cpu: Optional[tuple[int, int]] = None

    def snapshot(self) -> Snapshot:
        cur = sysinfo.read_cpu_times(self.proc)
        load = sysinfo.cpu_load(self._prev_cpu, cur) if cur and self._prev_cpu else None
        self._prev_cpu = cur
        bench = self.state_dir / "bench"
        return Snapshot(sysinfo.read_temps_c(self.thermal), sysinfo.read_mem_used_mb(self.proc), load,
                        sysinfo.read_power_w(self.power), _json(bench / "latest.json"), _json(bench / "npu.json"))
