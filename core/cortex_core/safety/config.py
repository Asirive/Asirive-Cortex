"""Safety thresholds: versioned, validated at load. Anything malformed or inconsistent falls back to the baked-in
safe defaults as a whole, never to "off" and never to a half-merged mix (core/AGENTS.md section 3, rule 6)."""
from typing import Any, Optional

VERSION = 1

# name: (default, low, high). Distances in metres, times in seconds.
SPEC: dict[str, tuple[float, float, float]] = {
    "fov_deg": (60.0, 40.0, 80.0),            # VL53L7CX square field of view per axis (confirm on the real part)
    "sensor_height_m": (1.60, 1.0, 2.1),      # eye height, set at fitting (the app asks); refined from the ground
                                              # when the floor is seen within 2.2 m (looking down)
    "band_low_m": (0.80, 0.5, 1.2),           # below this the cane's job, not ours
    "head_margin_m": (0.25, 0.1, 0.5),        # band top = sensor height + this
    "corridor_half_m": (0.40, 0.25, 0.8),     # walking corridor half width
    "centre_half_m": (0.15, 0.05, 0.3),       # centre sector half width (both motors)
    "ground_link_low_m": (0.25, 0.1, 0.5),    # something between these heights under an obstacle = the cane finds it
    "ground_link_high_m": (0.75, 0.4, 1.0),
    "ground_link_depth_m": (0.35, 0.1, 0.8),  # how far behind the obstacle's front that support may be
    "ttc_warn_s": (1.6, 0.8, 3.0),            # "ahead" pulse this long before contact
    "ttc_close_s": (0.7, 0.3, 1.5),           # "close" pattern
    "near_m": (0.8, 0.4, 1.5),                # "ahead" even when not moving
    "close_m": (0.5, 0.25, 1.0),              # "close" even when not moving
    "max_warn_m": (3.0, 1.0, 4.0),
    "min_closing_mps": (0.25, 0.05, 1.0),
    "cooldown_s": (2.5, 0.5, 10.0),           # between two "ahead" warnings
    "close_cooldown_s": (1.0, 0.2, 5.0),
    "lose_s": (0.4, 0.1, 2.0),                # an obstacle unseen this long is gone
    "memory_s": (30.0, 5.0, 120.0),           # a warned obstacle is remembered (direction + distance) this long
    "memory_deg": (20.0, 5.0, 45.0),          # ...and matched within this bearing
    "swing_dps": (150.0, 60.0, 400.0),        # head turning faster than this: no NEW first warnings
    "blocked_s": (2.0, 0.5, 10.0),            # lens covered this long: degraded
    "stale_s": (0.3, 0.1, 2.0),               # no frame this long: degraded
}

DEFAULTS: dict[str, float] = {k: v[0] for k, v in SPEC.items()}


def _consistent(c: dict[str, float]) -> bool:
    return (c["close_m"] < c["near_m"] < c["max_warn_m"] and c["ttc_close_s"] < c["ttc_warn_s"]
            and c["centre_half_m"] < c["corridor_half_m"] and c["ground_link_low_m"] < c["ground_link_high_m"]
            and c["ground_link_high_m"] <= c["band_low_m"])


def load(cfg: Optional[Any]) -> dict[str, float]:
    """cfg = {"version": 1, ...overrides}. Unknown keys, wrong version, bad numbers or an inconsistent set:
    the defaults, whole."""
    if cfg is None:
        return dict(DEFAULTS)
    try:
        if not isinstance(cfg, dict) or cfg.get("version") != VERSION:
            return dict(DEFAULTS)
        out = dict(DEFAULTS)
        for k, v in cfg.items():
            if k == "version":
                continue
            if k not in SPEC or isinstance(v, bool) or not isinstance(v, (int, float)):
                return dict(DEFAULTS)
            lo, hi = SPEC[k][1], SPEC[k][2]
            if not (lo <= float(v) <= hi):
                return dict(DEFAULTS)
            out[k] = float(v)
        return out if _consistent(out) else dict(DEFAULTS)
    except Exception:  # noqa: BLE001 - config must never take safety down
        return dict(DEFAULTS)
