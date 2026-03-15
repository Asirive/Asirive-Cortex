"""
Safety Monitor — Fusion-Based Threat Classification Engine

Fuses YOLO detections + Hailo depth map + environmental hazards into
tiered safety alerts. Only warns about SILENT dangers — the user wears
transparency-mode headphones and already hears cars, people, etc.

Tiers:
  1. Silent environmental hazards (walls, stairs, curbs, drop-offs) — from Hailo depth
  2. Silent static obstacles (fire hydrant, bench, bollard, etc.) — YOLO + depth < 2m
  3. Fast approaching vehicles (car closing fast) — YOLO + depth velocity (last resort)
  4. No alert (people, dogs, distant objects) — user hears them naturally

Design:
  - Highest-threat-wins: only alert on the most dangerous thing at any moment
  - 3D-positioned warning sounds via SpatialAudioManager.play_directional_alert()
  - TTS voice announcement for first-time Tier 1 hazards ("stairs ahead")
  - Haptic pulse for critical Tier 1 hazards
  - Per-hazard cooldowns prevent alert spam

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — YIA 2026
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── Threat Classification ─────────────────────────────────────────────────

# Tier 2: Silent static obstacles — user can't hear these through transparency
TIER2_SILENT_STATIC = {
    "fire hydrant", "bench", "chair", "potted plant",
    "parking meter", "suitcase", "backpack", "skateboard",
    "stop sign", "traffic light", "umbrella", "handbag",
    "surfboard", "snowboard", "dining table", "toilet",
    "couch", "bed",
}

# Tier 3: Vehicles — user usually hears them, but alert if closing fast
TIER3_VEHICLES = {
    "car", "truck", "bus", "motorcycle", "bicycle", "train",
}

# Everything else (person, dog, cat, ...) → Tier 4 (no alert)


# ─── Data Classes ──────────────────────────────────────────────────────────

@dataclass
class TrackedObject:
    """Velocity tracking for a single detected object."""
    object_id: str
    class_name: str
    distances: Deque[Tuple[float, float]] = field(default_factory=lambda: deque(maxlen=10))
    # (timestamp, distance_m) pairs — most recent at right

    @property
    def approach_velocity(self) -> float:
        """Metres per second the object is approaching (positive = closing in)."""
        if len(self.distances) < 2:
            return 0.0
        t0, d0 = self.distances[0]
        t1, d1 = self.distances[-1]
        dt = t1 - t0
        if dt < 0.05:
            return 0.0
        # Negative Δd/Δt means closing in → return as positive approach rate
        return -(d1 - d0) / dt


@dataclass
class ThreatAlert:
    """A single threat decision ready to be executed."""
    tier: int                   # 1, 2, or 3 — lower = more dangerous
    score: float                # Composite threat score (higher = worse)
    alert_type: str             # e.g. "wall", "stairs_down", "fire hydrant", "car"
    direction: str              # "left", "ahead", "right"
    distance_m: float           # Distance in metres
    position_3d: Optional[Tuple[float, float, float]] = None  # OpenAL (x, y, z)
    bbox: Optional[Tuple[float, ...]] = None
    needs_tts: bool = False     # First-time Tier 1 → TTS voice
    needs_haptic: bool = False  # Critical Tier 1 → vibration


# ─── Safety Monitor ────────────────────────────────────────────────────────

class SafetyMonitor:
    """
    Fusion engine: YOLO + Hailo depth → tiered safety alerts.

    Call process_frame() once per camera frame. It returns 0 or 1 ThreatAlert
    (highest-threat-wins). The caller (main.py) dispatches the alert to
    SpatialAudioManager, AudioAlertManager, and HapticFeedback.
    """

    def __init__(
        self,
        # Distance thresholds (metres)
        tier2_max_distance: float = 2.0,
        tier3_max_distance: float = 4.0,
        tier3_approach_velocity: float = 1.0,  # m/s closing speed
        # Cooldowns (seconds)
        alert_cooldown: float = 3.0,
        tts_cooldown: float = 8.0,
        haptic_cooldown: float = 2.0,
        # Frame geometry (for direction calculation)
        frame_width: int = 1920,
        # IMU for ego-motion / pitch awareness
        imu=None,
    ):
        self.tier2_max_distance = tier2_max_distance
        self.tier3_max_distance = tier3_max_distance
        self.tier3_approach_velocity = tier3_approach_velocity
        self.alert_cooldown = alert_cooldown
        self.tts_cooldown = tts_cooldown
        self.haptic_cooldown = haptic_cooldown
        self.frame_width = frame_width
        self.imu = imu

        # Environment-aware defaults (outdoor)
        self._outdoor_alert_cooldown = alert_cooldown
        self._outdoor_tts_cooldown = tts_cooldown
        self._outdoor_haptic_cooldown = haptic_cooldown
        self._is_indoor = False

        # Velocity tracking  (object_id → TrackedObject)
        self._tracked: Dict[str, TrackedObject] = {}

        # Cooldown timestamps  (alert_key → last alert time)
        self._last_alert: Dict[str, float] = {}
        self._last_tts: Dict[str, float] = {}
        self._last_haptic: float = 0.0

        # Stale-object cleanup timestamp
        self._last_cleanup: float = time.time()

        logger.info("SafetyMonitor initialised "
                     f"(T2<{tier2_max_distance}m, T3<{tier3_max_distance}m @ >{tier3_approach_velocity}m/s)"
                     f", IMU={'yes' if imu else 'no'}")

    # ── Public API ──────────────────────────────────────────────────────

    def process_frame(
        self,
        detections: List[Dict[str, Any]],
        hazards: Optional[List[Any]] = None,
        depth_map: Any = None,
        frame_shape: Optional[Tuple[int, ...]] = None,
    ) -> Optional[ThreatAlert]:
        """
        Run one frame through the safety pipeline.

        Args:
            detections: YOLO detection dicts (class_name, bbox, confidence,
                        distance_m, object_id)
            hazards: List[Hazard] from HailoDepthEstimator.analyze_hazards()
            depth_map: Raw depth map (currently unused — distance is on detections)
            frame_shape: (H, W, C) of original camera frame

        Returns:
            The single highest-priority ThreatAlert, or None if everything is safe.
        """
        now = time.time()
        candidates: List[ThreatAlert] = []

        # ── Tier 1: Environmental hazards from Hailo depth ──────────
        if hazards:
            for h in hazards:
                # Only care about critical / warning severity
                if h.severity.value == "info":
                    continue
                # Walls are expected indoors — suppress if far enough away
                # Close walls (<1.0m) still alert to prevent collisions
                if self._is_indoor and h.type.value == "wall" and h.distance >= 1.0:
                    continue
                key = f"t1_{h.type.value}_{h.direction}"
                if self._on_cooldown(key, now):
                    continue

                # Progressive alerts based on distance:
                #   > 1.5m  → spatial audio only
                #   1.0-1.5m → spatial audio + TTS
                #   < 1.0m  → spatial audio + TTS + haptic
                needs_tts = h.distance < 1.5 and not self._tts_on_cooldown(key, now)
                needs_haptic = h.distance < 1.0 and not self._haptic_on_cooldown(now)

                candidates.append(ThreatAlert(
                    tier=1,
                    score=self._tier1_score(h),
                    alert_type=h.type.value,
                    direction=h.direction,
                    distance_m=h.distance,
                    position_3d=self._direction_to_3d(h.direction, h.distance),
                    needs_tts=needs_tts,
                    needs_haptic=needs_haptic,
                ))

        # ── Tier 2 + 3: YOLO-detected objects ──────────────────────
        for det in detections:
            cls = (det.get("class_name") or det.get("class", "")).lower()
            dist = det.get("distance_m")
            bbox = det.get("bbox", ())

            # Update velocity tracker
            obj_id = det.get("object_id") or self._make_object_id(cls, bbox)
            if dist and dist > 0:
                self._update_tracker(obj_id, cls, dist, now)

            tracker = self._tracked.get(obj_id)
            vel = tracker.approach_velocity if tracker else 0.0

            # ─ Tier 2: Silent static obstacle, close ─
            if cls in TIER2_SILENT_STATIC and dist and dist < self.tier2_max_distance:
                key = f"t2_{obj_id}"
                if self._on_cooldown(key, now):
                    continue
                direction = self._bbox_to_direction(bbox)
                candidates.append(ThreatAlert(
                    tier=2,
                    score=self._tier2_score(dist, cls),
                    alert_type=cls,
                    direction=direction,
                    distance_m=dist,
                    position_3d=self._bbox_to_3d_simple(bbox, dist),
                    bbox=tuple(bbox) if bbox else None,
                ))

            # ─ Tier 3: Vehicle closing fast ─
            elif cls in TIER3_VEHICLES and dist and dist < self.tier3_max_distance:
                if vel > self.tier3_approach_velocity:
                    key = f"t3_{obj_id}"
                    if self._on_cooldown(key, now):
                        continue
                    direction = self._bbox_to_direction(bbox)
                    candidates.append(ThreatAlert(
                        tier=3,
                        score=self._tier3_score(dist, vel),
                        alert_type=cls,
                        direction=direction,
                        distance_m=dist,
                        position_3d=self._bbox_to_3d_simple(bbox, dist),
                        bbox=tuple(bbox) if bbox else None,
                    ))

        # ── Pick highest-threat candidate ───────────────────────────
        if not candidates:
            return None

        # Sort by tier (ascending), then score (descending)
        candidates.sort(key=lambda c: (c.tier, -c.score))
        winner = candidates[0]

        # Record cooldowns
        winner_key = f"t{winner.tier}_{winner.alert_type}_{winner.direction}"
        self._last_alert[winner_key] = now
        if winner.needs_tts:
            tts_key = f"t1_{winner.alert_type}_{winner.direction}"
            self._last_tts[tts_key] = now
        if winner.needs_haptic:
            self._last_haptic = now

        # Periodic cleanup of stale trackers (every 5s)
        if now - self._last_cleanup > 5.0:
            self._cleanup_trackers(now)
            self._last_cleanup = now

        logger.info(f"⚠️  SAFETY T{winner.tier}: {winner.alert_type} "
                     f"{winner.direction} {winner.distance_m:.1f}m "
                     f"(score={winner.score:.2f}"
                     f"{' TTS' if winner.needs_tts else ''}"
                     f"{' HAPTIC' if winner.needs_haptic else ''})")
        return winner

    # ── Scoring ─────────────────────────────────────────────────────

    def _tier1_score(self, hazard) -> float:
        """Score a Tier 1 environmental hazard. Higher = more dangerous."""
        # Closer = worse; critical severity gets a boost
        base = 10.0 / max(hazard.distance, 0.1)
        severity_mult = 2.0 if hazard.severity.value == "critical" else 1.0
        return base * severity_mult

    def _tier2_score(self, distance: float, cls: str) -> float:
        """Score a Tier 2 static obstacle."""
        return 5.0 / max(distance, 0.1)

    def _tier3_score(self, distance: float, velocity: float) -> float:
        """Score a Tier 3 approaching vehicle."""
        # Time-to-contact is the key urgency metric
        ttc = distance / max(velocity, 0.1)
        return 10.0 / max(ttc, 0.1)

    # ── Cooldown helpers ────────────────────────────────────────────

    def _on_cooldown(self, key: str, now: float) -> bool:
        return (now - self._last_alert.get(key, 0)) < self.alert_cooldown

    def _tts_on_cooldown(self, key: str, now: float) -> bool:
        return (now - self._last_tts.get(key, 0)) < self.tts_cooldown

    def _haptic_on_cooldown(self, now: float) -> bool:
        return (now - self._last_haptic) < self.haptic_cooldown

    # ── Velocity tracking ───────────────────────────────────────────

    def _update_tracker(self, obj_id: str, cls: str, dist: float, now: float):
        if obj_id not in self._tracked:
            self._tracked[obj_id] = TrackedObject(object_id=obj_id, class_name=cls)
        self._tracked[obj_id].distances.append((now, dist))

    def _cleanup_trackers(self, now: float):
        """Remove trackers not updated in >3 seconds."""
        stale = [
            oid for oid, t in self._tracked.items()
            if t.distances and (now - t.distances[-1][0]) > 3.0
        ]
        for oid in stale:
            del self._tracked[oid]

    # ── Geometry helpers ────────────────────────────────────────────

    @staticmethod
    def _make_object_id(cls: str, bbox) -> str:
        if bbox and len(bbox) >= 4:
            cx = int((bbox[0] + bbox[2]) / 2 / 50) * 50
            cy = int((bbox[1] + bbox[3]) / 2 / 50) * 50
            return f"{cls}_{cx}_{cy}"
        return f"{cls}_unknown"

    def _bbox_to_direction(self, bbox) -> str:
        """Map bbox horizontal centre to left / ahead / right."""
        if not bbox or len(bbox) < 4:
            return "ahead"
        cx = (bbox[0] + bbox[2]) / 2
        third = self.frame_width / 3
        if cx < third:
            return "left"
        elif cx > 2 * third:
            return "right"
        return "ahead"

    def _bbox_to_3d_simple(self, bbox, distance_m: float) -> Tuple[float, float, float]:
        """Rough 3D position for OpenAL: x=left/right, y=0, z=-distance."""
        if not bbox or len(bbox) < 4:
            return (0.0, 0.0, -distance_m)
        cx = (bbox[0] + bbox[2]) / 2
        # Map [0, frame_width] → [-2.5, +2.5] metres
        x = ((cx / self.frame_width) - 0.5) * 5.0
        return (x, 0.0, -distance_m)

    @staticmethod
    def _direction_to_3d(direction: str, distance_m: float) -> Tuple[float, float, float]:
        """Convert text direction + distance to OpenAL coordinates."""
        x_map = {"left": -2.0, "right": 2.0, "ahead": 0.0, "below": 0.0}
        x = x_map.get(direction, 0.0)
        return (x, 0.0, -distance_m)

    # ── Environment awareness ──────────────────────────────────────────

    def set_environment(self, indoor: bool):
        """Adjust alert cooldowns for indoor vs outdoor."""
        if indoor == self._is_indoor:
            return
        self._is_indoor = indoor
        if indoor:
            self.alert_cooldown = 8.0
            self.tts_cooldown = 20.0
            self.haptic_cooldown = 5.0
        else:
            self.alert_cooldown = self._outdoor_alert_cooldown
            self.tts_cooldown = self._outdoor_tts_cooldown
            self.haptic_cooldown = self._outdoor_haptic_cooldown
        label = "INDOOR" if indoor else "OUTDOOR"
        logger.info(f"SafetyMonitor → {label}: cooldowns alert={self.alert_cooldown}s, "
                    f"tts={self.tts_cooldown}s, haptic={self.haptic_cooldown}s")
