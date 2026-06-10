"""
Dashboard state holder for the Asirive Cortex live dashboard.

Thread-safe state snapshot + history deques. Both the 2.4 mode (print)
and the FULL mode (Textual) read from the same DashboardState instance.

The CortexSystem owns one of these, calls `update(...)` from its various
callbacks (camera thread, L0/L1 thread, audio thread), and `record_sample(...)`
from the main loop at 1Hz. The dashboard reads `snapshot()` and `history()`
to render.

Design notes:
  - `update()` and `snapshot()` use a single internal lock to keep state
    internally consistent (you never see a half-updated state).
  - History deques are bounded (60 samples by default) so memory is
    constant. 60 samples × 1Hz = 1 minute of history.
  - `snapshot()` returns a deep copy so the UI can hold the dict without
    worrying about concurrent mutation.
"""

from __future__ import annotations

import copy
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional


# Default field values for every dashboard field. Anything not in this
# template is ignored on update (defensive — the dict shape is stable
# so widgets can rely on the keys).
def _default_state() -> Dict[str, Any]:
    return {
        # mode / fps
        "mode": "DEV",                    # "DEV" | "PRODUCTION"
        "fps": 0.0,
        "frame_seq": 0,                    # monotonic frame counter
        "frames_processed": 0,
        "loop_iterations": 0,
        "uptime_s": 0.0,

        # System metrics (psutil-sourced, refreshed ~1Hz)
        "system": {
            "cpu_percent": 0.0,
            "cpu_temp_c": 0.0,
            "ram_used_mb": 0,
            "ram_total_mb": 0,
            "ram_percent": 0.0,
            "load_avg_1m": 0.0,
        },

        # Disk usage (psutil-sourced, refreshed ~1Hz)
        "disk": {
            "used_gb": 0.0,
            "total_gb": 0.0,
            "percent": 0.0,
            "free_gb": 0.0,
        },

        # Camera
        "camera": {
            "available": False,
            "backend": "",                  # "picamera2" | "opencv"
            "resolution": [0, 0],
            "fps_target": 0.0,
        },

        # Recent STT (last 5 utterances)
        "stt_recent": [],                   # [{"text": str, "ts": float, "confidence": float}]

        # Recent safety alerts (last 5)
        "safety_recent": [],                # [{"type": str, "distance_m": float, "ts": float, "tier": int}]

        # Scene change detector
        "scene": {
            "last_change_ts": 0.0,
            "last_change_type": "",         # "appearance" | "disappearance" | "moved"
        },

        # Button (physical GPIO button)
        "button": {
            "last_press_ts": 0.0,
            "last_press_type": "",          # "short" | "long"
        },

        # Connectivity monitor (per-service)
        "services": {
            "supabase": {"ok": False, "last_check_s": 0.0},
            "gemini": {"ok": False, "last_check_s": 0.0},
            "google_maps": {"ok": False, "last_check_s": 0.0},
            "phone_gps": {"ok": False, "last_check_s": 0.0},
        },
        # detection
        "l0_count": 0,
        "l0_classes": [],                  # [str, ...]
        "l0_latency_ms": 0.0,
        "l1_count": 0,
        "l1_classes": [],
        "l1_latency_ms": 0.0,
        "l1_mode": "",                     # e.g. "TEXT_PROMPTS"
        "hailo_depth_fps": 0.0,
        "hailo_ocr_state": "idle",         # "idle" | "running" | "error"
        # sensors
        "gps": {
            "fix": 0,                      # 0=no fix, 1=GPS, 2=DGPS, 3=PPS
            "sats": 0,
            "lat": 0.0,
            "lon": 0.0,
            "source": "",                  # "m8u" | "phone" | ""
        },
        "imu": {
            "heading": 0.0,
            "cal": [0, 0, 0, 0],          # sys, gyro, accel, mag
        },
        "environment": "unknown",          # "indoor" | "outdoor" | "unknown"
        "bt": {
            "connected": False,
            "device": "",                  # human-readable, e.g. "F-16"
            "earbuds": "",                 # "CMF Buds" | "UGREEN HiTune S3" | ""
            "battery_pct": -1,            # -1 = unknown
        },
        "hailo": {
            "depth_fps": 0.0,
            "ocr_state": "idle",
        },
        # AI / routing
        "ai": {
            "active": False,               # True = Gemini routing, False = local
            "last_call": "",
        },
        # Layer 2 (Gemini Live)
        "l2": {
            "connected": False,
            "uptime_s": 0.0,
            "model": "",
            "voice": "",
            "lang": "",
            "last_heard": "",
            "last_said": "",
            "transcript": [],              # [str, ...] — last 4 turns ("YOU: ..." or "CORTEX: ...")
            "tool_calls": 0,
            "google_searches": 0,
            # NEW: live audio input level (0..1, used for VU meter)
            "audio_input_level": 0.0,
            # NEW: latency stats (ms) for the last minute of L2 calls
            "latency_ms": {"avg": 0.0, "p95": 0.0, "ttfb": 0.0},
            # NEW: tool call history (last 10)
            "tool_call_log": [],           # [{"name": str, "args_preview": str, "result_preview": str, "ts": float}]
        },
        # Layer 3 (Navigation / Bus / Connectivity)
        # NavMode (physical context):  "idle" | "outdoor" | "indoor" | "bus_stop" | "transit"
        # NavState (session state):    "inactive" | "loading_route" | "navigating" |
        #                                "arrived" | "paused" | "waiting_for_bus" |
        #                                "on_vehicle" | "error"
        # LegType (per-leg route type): "walking" | "bus" | "mrt" | "" (if no active leg)
        "nav": {
            # Headline
            "mode": "idle",                # NavMode value (lowercase)
            "state": "inactive",          # NavState value (lowercase)
            "destination": "",
            # Instruction + progress
            "next_instruction": "",
            "waypoint_index": 0,
            "total_waypoints": 0,
            "distance_to_waypoint_m": 0.0,
            "distance_to_destination_m": 0.0,
            "bearing_to_waypoint": 0.0,
            # Active leg
            "current_leg_type": "",       # LegType value or "" if no active leg
            "current_leg_distance_m": 0.0,
            "current_leg_duration_s": 0.0,
            "current_leg_instruction": "",
            # Transit info (only when leg_type is BUS or MRT)
            "transit_service_no": "",
            "transit_line_name": "",
            "transit_line_color": "",
            "transit_departure_stop": "",
            "transit_arrival_stop": "",
            "transit_num_stops": 0,
            "transit_headsign": "",
            # Saved locations (loaded from config)
            "saved_locations": [],         # [{"name": str, "address": str, "default": bool}]
            "last_nav_destination": "",
            # Bus subsystem
            "bus_state": "idle",           # "idle" | "querying" | "active"
            "lta_ok": False,
        },
        "connectivity": {
            "online": False,
            "ping_ms": 0,
            "supabase_ok": False,
            "last_supabase_sync_s": 0.0,
        },
        # TTS + Voice
        "tts": {
            "engine": "",                  # "cartesia" | "supertonic" | "gemini"
            "state": "idle",               # "idle" | "speaking" | "fallback"
            "fallback_engine": "",
            "speed": 1.0,
            "muted": False,
        },
        "voice": {
            "listening": False,
            "vad_active": False,
        },
        # Safety
        "safety": {
            "tier": 0,                     # 0 (no alert) | 1 | 2 | 3
            "alert_type": "",              # "overhang" | "stairs_up" | "incoming_fast" | ...
            "distance_m": 0.0,
            "alerts_last_60s": 0,          # counter, reset every minute
        },
        # Memory (L4)
        "l4": {
            "local_rows": 0,
            "last_sync_age_s": -1,         # -1 = never
            "next_sync_in_s": 60,
            "sync_status": "idle",         # "idle" | "syncing" | "error"
            "detections_stored": 0,
            "events_stored": 0,
            "upload_queue": 0,
            "upload_failed": 0,
        },
        # Session AV recorder
        "recorder": {
            "is_recording": False,
            "toggle_key": "b",
        },
        # Flags
        "privacy_mode": False,
        "running": True,
    }


# Default history shape (all deques, bounded).
def _default_history() -> Dict[str, Deque[float]]:
    return {
        "fps": deque(maxlen=60),
        "l0_count": deque(maxlen=60),
        "l0_latency_ms": deque(maxlen=60),
        "l2_latency_ms": deque(maxlen=60),  # NEW: L2 round-trip latency
        "alerts_per_s": deque(maxlen=60),
    }


class DashboardState:
    """Thread-safe state + bounded history for the dashboard UI.

    Public surface (the only thing the UI / CortexSystem need to know):
      - `update(**kwargs)` — merge fields into the state.
      - `record_sample(**kwargs)` — append a value to the matching history deque.
      - `snapshot()` — deep-copied state dict (UI holds this freely).
      - `history()` — shallow-copied history deques as lists.
      - `keys()` / `__contains__` — for introspection / tests.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = _default_state()
        self._history: Dict[str, Deque[float]] = _default_history()
        self._started_at: float = time.time()

    # --- read ---

    def snapshot(self) -> Dict[str, Any]:
        """Return a deep-copied state dict. Safe to hold, no aliasing."""
        with self._lock:
            return copy.deepcopy(self._state)

    def history(self) -> Dict[str, List[float]]:
        """Return a shallow-copied history dict (lists, not deques)."""
        with self._lock:
            return {k: list(v) for k, v in self._history.items()}

    def uptime_s(self) -> float:
        return time.time() - self._started_at

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._state.keys())

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._state

    # --- write ---

    def update(self, **kwargs: Any) -> None:
        """Merge fields into the state. Unknown keys are silently ignored.

        For dict-valued fields (e.g. "gps", "bt", "l2"), this performs a
        shallow merge — you can update individual sub-fields without
        resending the whole dict.

        Examples:
            state.update(fps=20.5, l0_count=3)
            state.update(gps={"fix": 1, "sats": 8}, bt={"connected": True})
        """
        with self._lock:
            for k, v in kwargs.items():
                if k not in self._state:
                    continue
                cur = self._state[k]
                if isinstance(cur, dict) and isinstance(v, dict):
                    cur.update(v)
                else:
                    self._state[k] = v

    def record_sample(self, **kwargs: float) -> None:
        """Append a value to a history deque. Unknown keys are ignored.

        Examples:
            state.record_sample(fps=20.5, l0_count=3, l0_latency_ms=47.0)
        """
        with self._lock:
            for k, v in kwargs.items():
                dq = self._history.get(k)
                if dq is not None:
                    dq.append(float(v))

    def reset(self) -> None:
        """Reset state and history to defaults. Test helper, not for production use."""
        with self._lock:
            self._state = _default_state()
            self._history = _default_history()
            self._started_at = time.time()
