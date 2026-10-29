"""Hazard tiers and the fail-safe loop. Skeleton: tier logic is a placeholder until T0-T3 are ported
from v3_core/safety_monitor.py with replay tests; the invariants below are the real part.
"""
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence

# clock positions for 7 forward zones, left to right (clock-position speech only; no spatial audio DSP)
CLOCK = (9, 10, 11, 12, 1, 2, 3)

DEFAULT_THRESHOLDS_MM = {"T0": 2500, "T1": 1500, "T2": 900, "T3": 450}  # baked-in safe defaults
TIER_ORDER = ("T0", "T1", "T2", "T3")  # T3 = most urgent
DEGRADED_REPEAT_S = 5.0
MAX_BAD_READS = 3


class SensorError(Exception): ...


class Sensor(Protocol):
    def read(self) -> Sequence[Optional[float]]:
        """Distance in mm per forward zone (len 7); None = no return. May raise SensorError."""


class Output(Protocol):
    def haptic(self, pattern: str, clock: Optional[int] = None) -> None: ...
    def cue(self, cue_id: str, clock: Optional[int] = None) -> None:
        """Play a baked-in audio cue (pre-rendered, no TTS, no model)."""


@dataclass(frozen=True)
class Alert:
    tier: str
    clock: int
    distance_mm: float


def load_thresholds(cfg: Optional[dict]) -> dict:
    """Validated versioned config; anything malformed falls back to the safe defaults, never to 'off'."""
    try:
        t = {k: float(cfg[k]) for k in TIER_ORDER}  # type: ignore[index]
        vals = [t[k] for k in TIER_ORDER]
        if all(v > 0 for v in vals) and vals == sorted(vals, reverse=True) and len(set(vals)) == 4:
            return t
    except (TypeError, KeyError, ValueError):
        pass
    return dict(DEFAULT_THRESHOLDS_MM)


class SafetyService:
    def __init__(self, sensor: Sensor, out: Output, beat: Callable[[], None], thresholds: Optional[dict] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.sensor, self.out, self.beat, self.clock = sensor, out, beat, clock
        self.th = load_thresholds(thresholds)
        self.bad_reads = 0
        self.degraded = False
        self._last_degraded = -1e9
        self._last_alert: Optional[Alert] = None
        self._last_alert_t = -1e9

    def classify(self, frame: Sequence[Optional[float]]) -> Optional[Alert]:
        worst: Optional[Alert] = None
        for i, d in enumerate(frame):
            if d is None or d != d or d < 0:  # no return, NaN or nonsense: ignore the zone, never crash
                continue
            for tier in reversed(TIER_ORDER):
                if d <= self.th[tier]:
                    a = Alert(tier, CLOCK[i % len(CLOCK)], d)
                    if worst is None or (TIER_ORDER.index(a.tier), -a.distance_mm) > (TIER_ORDER.index(worst.tier), -worst.distance_mm):
                        worst = a
                    break
        return worst

    def step(self) -> Optional[Alert]:
        """One loop iteration. Heartbeat first, so a stall anywhere after it still shows up as a missed beat next time."""
        self.beat()
        now = self.clock()
        try:
            frame = self.sensor.read()
            self.bad_reads = 0
            self.degraded = False
        except Exception:  # any sensor fault: count it, never propagate
            self.bad_reads += 1
            if self.bad_reads >= MAX_BAD_READS:
                self.degraded = True
                if now - self._last_degraded >= DEGRADED_REPEAT_S:  # never silent: repeat until the sensor returns
                    self._last_degraded = now
                    self.out.haptic("degraded")
                    self.out.cue("safety_degraded")
            return None
        a = self.classify(frame)
        if a is None:
            self._last_alert = None
            return None
        escalated = self._last_alert is None or TIER_ORDER.index(a.tier) > TIER_ORDER.index(self._last_alert.tier)
        if escalated or a.tier == "T3" or now - self._last_alert_t >= 1.0:
            self._last_alert, self._last_alert_t = a, now
            self.out.haptic(a.tier, a.clock)
            if a.tier in ("T2", "T3") or escalated:
                self.out.cue(f"hazard_{a.tier.lower()}", a.clock)
        return a

    def run(self, should_stop: Callable[[], bool], period_s: float = 0.02, sleep: Callable[[float], None] = time.sleep) -> None:
        while not should_stop():
            try:
                self.step()
            except Exception:  # an output fault must not kill the loop; the next step retries
                pass
            sleep(period_s)
