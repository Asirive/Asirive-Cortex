"""The safety loop: ToF frame + IMU in, vibration out. Head-level and silent obstacles only (the cane has the rest).

Invariants (core/AGENTS.md section 3):
- inputs are the ToF frame and its IMU only; nothing here waits on the AI, network or phone
- heartbeat every step, before anything that could stall
- never silent when blind: no frames, sensor errors, or a covered lens -> "degraded" vibration + the baked-in
  audio cue (the one cue that is not vibration), repeated until the sensor is back
- warnings are vibration only: ("ahead" | "close") on ("left" | "right" | "both")
- a bad config is the safe defaults, never off
"""
import math
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence

from cortex_core.safety import config as C
from cortex_core.safety.perceive import Perception, Tilt
from cortex_core.safety.warn import Warner

DEGRADED_REPEAT_S = 5.0
MAX_BAD_READS = 3


class SensorError(Exception): ...


@dataclass
class Frame:
    t: float                              # sensor clock, s
    dist_mm: Sequence[Optional[float]]    # 64 zones, row 0 top, column 0 user's left; None = no target
    accel: Sequence[float] = (0.0, 0.0, 1.0)   # g, mean over the frame
    dtheta: Sequence[float] = (0.0, 0.0, 0.0)  # rad, summed over the frame


class Sensor(Protocol):
    def read(self) -> Optional[Frame]:
        """The next frame, or None if none arrived within the read timeout. May raise SensorError."""


class Output(Protocol):
    def haptic(self, pattern: str, side: str = "both") -> None: ...
    def cue(self, cue_id: str) -> None:
        """Baked-in audio cue (pre-rendered, no TTS, no model). Only for 'safety degraded'."""


class SafetyService:
    def __init__(self, sensor: Sensor, out: Output, beat: Callable[[], None], cfg: Optional[dict] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.sensor, self.out, self.beat, self.clock = sensor, out, beat, clock
        self.cfg = C.load(cfg)
        self.perc = Perception(self.cfg)
        self.tilt = Tilt()
        self.warner = Warner(self.cfg)
        self.bad_reads = 0
        self.degraded = False
        self.reason = ""
        self._last_degraded = -1e9
        self._last_frame = clock()
        self._blocked_since: Optional[float] = None
        self._prev_t: Optional[float] = None

    def _blind(self, now: float, reason: str) -> None:
        self.degraded, self.reason = True, reason
        if now - self._last_degraded >= DEGRADED_REPEAT_S:  # never silent: repeat until the sensor is back
            self._last_degraded = now
            self.out.haptic("degraded", "both")
            self.out.cue("safety_degraded")

    def step(self) -> list[tuple[str, str]]:
        """One iteration. Heartbeat first, so a stall anywhere after it shows up as a missed beat."""
        self.beat()
        now = self.clock()
        try:
            f = self.sensor.read()
        except Exception:  # any sensor fault: count it, never propagate
            self.bad_reads += 1
            if self.bad_reads >= MAX_BAD_READS:
                self._blind(now, "sensor error")
            return []
        if f is None:
            if now - self._last_frame > self.cfg["stale_s"]:
                self._blind(now, "no frames")
            return []
        self.bad_reads = 0
        self._last_frame = now
        if len(f.dist_mm) != len(self.perc.dirs):
            self.bad_reads += 1
            return []
        pitch, roll = self.tilt.update(f.accel, f.dtheta)
        obs = self.perc.process(f.dist_mm, pitch, roll)
        if obs.blocked:
            self._blocked_since = self._blocked_since if self._blocked_since is not None else now
            if now - self._blocked_since >= self.cfg["blocked_s"]:
                self._blind(now, "sensor covered")
            return []
        self._blocked_since = None
        self.degraded, self.reason = False, ""
        dt = f.t - self._prev_t if self._prev_t is not None and f.t > self._prev_t else 1 / 15
        self._prev_t = f.t
        yaw_dps = math.degrees(f.dtheta[2]) / dt
        fired = self.warner.update(f.t, obs, yaw_dps, f.dtheta[2])
        for pattern, side in fired:
            self.out.haptic(pattern, side)
        return fired

    def run(self, should_stop: Callable[[], bool], sleep: Callable[[float], None] = time.sleep) -> None:
        """sensor.read() paces the loop (it waits for the next frame up to its timeout)."""
        while not should_stop():
            try:
                self.step()
                if self.bad_reads:
                    sleep(0.05)  # a sensor that fails at once must not spin the core
            except Exception:  # an output fault must not kill the loop; the next step retries
                sleep(0.01)
