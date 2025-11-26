"""
Project-Cortex v2.0 - Position Calculator

Converts YOLO 2D bounding boxes to 3D audio positions for spatial sound rendering.
Implements the core algorithm for mapping detected objects to OpenAL 3D space.

Coordinate System (OpenAL):
- X-axis: Left (-1) to Right (+1)
- Y-axis: Down (-1) to Up (+1)
- Z-axis: Behind (+) to Front (-), User faces -Z direction

Author: Haziq (@IRSPlays)
"""

from typing import Tuple, Optional, Dict
from dataclasses import dataclass
import math


# Default known object sizes in meters (used for distance estimation)
DEFAULT_OBJECT_SIZES: Dict[str, float] = {
    "person": 0.5,       # Average shoulder width
    "car": 1.8,          # Average car width
    "chair": 0.5,        # Average chair width
    "door": 0.9,         # Standard door width
    "stairs": 1.0,       # Standard staircase width
    "bicycle": 0.6,      # Handlebar width
    "dog": 0.3,          # Average dog body width
    "cat": 0.2,          # Average cat width
    "tv": 1.0,           # Average TV width
    "laptop": 0.35,      # Average laptop width
    "bottle": 0.08,      # Bottle diameter
    "cup": 0.08,         # Cup diameter
    "cell phone": 0.07,  # Phone width
    "book": 0.2,         # Book width
    "backpack": 0.4,     # Backpack width
    "umbrella": 0.3,     # Umbrella width (closed)
    "handbag": 0.3,      # Handbag width
    "suitcase": 0.5,     # Suitcase width
    "traffic light": 0.4, # Traffic light width
    "stop sign": 0.75,   # Standard stop sign width
    "bus": 2.5,          # Bus width
    "truck": 2.4,        # Truck width
    "motorcycle": 0.8,   # Motorcycle width
}


@dataclass
class Position3D:
    """3D position in OpenAL coordinate space."""
    x: float  # Left (-) to Right (+)
    y: float  # Down (-) to Up (+)
    z: float  # Behind (+) to Front (-), user faces -Z
    distance_meters: Optional[float] = None  # Estimated real-world distance
    
    def as_tuple(self) -> Tuple[float, float, float]:
        """Return position as (x, y, z) tuple for OpenAL."""
        return (self.x, self.y, self.z)
    
    def __repr__(self) -> str:
        dist_str = f", ~{self.distance_meters:.1f}m" if self.distance_meters else ""
        return f"Position3D(x={self.x:.2f}, y={self.y:.2f}, z={self.z:.2f}{dist_str})"


class PositionCalculator:
    """
    Converts 2D bounding boxes to 3D audio positions.
    
    The conversion uses:
    - Horizontal position (bbox center X) → X-axis (left/right)
    - Vertical position (bbox center Y) → Y-axis (up/down)
    - Bounding box area → Z-axis (distance estimation)
    
    For more accurate distance, known object sizes can be used with
    the pinhole camera model: Distance = (Real_Width × Focal_Length) / Bbox_Width
    """
    
    def __init__(
        self,
        frame_width: int = 1920,
        frame_height: int = 1080,
        focal_length_pixels: float = 1500.0,
        min_distance: float = 0.5,
        max_distance: float = 10.0,
        object_sizes: Optional[Dict[str, float]] = None,
        smoothing_alpha: float = 0.3
    ):
        """
        Initialize the position calculator.
        
        Args:
            frame_width: Camera frame width in pixels
            frame_height: Camera frame height in pixels
            focal_length_pixels: Camera focal length in pixels (estimate for IMX415: ~1500)
            min_distance: Minimum distance in meters (closest)
            max_distance: Maximum distance in meters (farthest)
            object_sizes: Dict of object class → real-world width in meters
            smoothing_alpha: Smoothing factor for position interpolation (0-1)
        """
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.focal_length = focal_length_pixels
        self.min_distance = min_distance
        self.max_distance = max_distance
        self.object_sizes = object_sizes or DEFAULT_OBJECT_SIZES.copy()
        self.smoothing_alpha = smoothing_alpha
        
        # Position history for smoothing (object_id → last_position)
        self._position_history: Dict[str, Position3D] = {}
        
        # Area thresholds for distance estimation (when no known size)
        self.area_close = 0.4   # Normalized area when object is close
        self.area_far = 0.01   # Normalized area when object is far
    
    def bbox_to_3d(
        self,
        bbox: Tuple[float, float, float, float],
        object_class: Optional[str] = None,
        object_id: Optional[str] = None,
        apply_smoothing: bool = True
    ) -> Position3D:
        """
        Convert a bounding box to 3D audio position.
        
        Args:
            bbox: Bounding box as (x1, y1, x2, y2) in pixels or normalized [0-1]
            object_class: Class name for distance estimation (optional)
            object_id: Unique ID for position smoothing (optional)
            apply_smoothing: Whether to smooth position changes
            
        Returns:
            Position3D with x, y, z coordinates and optional distance estimate
        """
        x1, y1, x2, y2 = bbox
        
        # Normalize bbox to [0, 1] if in pixel coordinates
        if x2 > 1.0 or y2 > 1.0:
            x1 = x1 / self.frame_width
            y1 = y1 / self.frame_height
            x2 = x2 / self.frame_width
            y2 = y2 / self.frame_height
        
        # Calculate center point
        center_x = (x1 + x2) / 2  # Range: 0 to 1
        center_y = (y1 + y2) / 2  # Range: 0 to 1
        
        # Calculate bbox dimensions
        width = x2 - x1
        height = y2 - y1
        area = width * height  # Normalized area
        
        # === HORIZONTAL POSITION (X-axis) ===
        # Map [0, 1] → [-1, +1] (left to right)
        x = (center_x - 0.5) * 2.0
        
        # === VERTICAL POSITION (Y-axis) ===
        # Map [0, 1] → [+1, -1] (top of frame = up in 3D)
        # Note: Image Y increases downward, OpenAL Y increases upward
        y = (0.5 - center_y) * 2.0
        
        # === DEPTH POSITION (Z-axis) ===
        # Try to use known object size for accurate distance
        distance_meters = None
        if object_class and object_class.lower() in self.object_sizes:
            bbox_width_pixels = width * self.frame_width
            distance_meters = self._estimate_distance_from_size(
                bbox_width_pixels, 
                object_class.lower()
            )
            # Convert distance to Z coordinate (negative because user faces -Z)
            z = -max(self.min_distance, min(self.max_distance, distance_meters))
        else:
            # Fallback: use bbox area for rough distance estimate
            z = self._area_to_depth(area)
            # Estimate distance from Z
            distance_meters = abs(z)
        
        # Create position
        position = Position3D(x=x, y=y, z=z, distance_meters=distance_meters)
        
        # Apply smoothing if enabled and we have history
        if apply_smoothing and object_id:
            position = self._smooth_position(object_id, position)
        
        return position
    
    def _estimate_distance_from_size(
        self, 
        bbox_width_pixels: float, 
        object_class: str
    ) -> float:
        """
        Estimate real-world distance using pinhole camera model.
        
        Distance = (Known_Width × Focal_Length) / Bbox_Width
        
        Args:
            bbox_width_pixels: Width of bounding box in pixels
            object_class: Class name for known size lookup
            
        Returns:
            Estimated distance in meters
        """
        if object_class not in self.object_sizes:
            return self.max_distance / 2  # Default to middle distance
        
        known_width = self.object_sizes[object_class]
        
        if bbox_width_pixels <= 0:
            return self.max_distance
        
        distance = (known_width * self.focal_length) / bbox_width_pixels
        
        # Clamp to valid range
        return max(self.min_distance, min(self.max_distance, distance))
    
    def _area_to_depth(self, area: float) -> float:
        """
        Convert normalized bbox area to Z depth.
        
        Larger area = closer = smaller |z|
        
        Args:
            area: Normalized bounding box area (0 to 1)
            
        Returns:
            Z coordinate (negative, user faces -Z)
        """
        # Clamp area to valid range
        area_clamped = max(self.area_far, min(self.area_close, area))
        
        # Inverse mapping: larger area → smaller distance
        # Normalize to [0, 1] where 1 = close, 0 = far
        normalized = (area_clamped - self.area_far) / (self.area_close - self.area_far)
        
        # Map to distance range (close → min_distance, far → max_distance)
        distance = self.min_distance + (1 - normalized) * (self.max_distance - self.min_distance)
        
        # Return as negative Z (user faces -Z direction)
        return -distance
    
    def _smooth_position(self, object_id: str, new_position: Position3D) -> Position3D:
        """
        Apply exponential smoothing to position changes.
        
        This prevents audio sources from "jumping" when object detection
        has slight variations between frames.
        
        Args:
            object_id: Unique identifier for the object
            new_position: Newly calculated position
            
        Returns:
            Smoothed position
        """
        if object_id not in self._position_history:
            # First time seeing this object, no smoothing needed
            self._position_history[object_id] = new_position
            return new_position
        
        old_pos = self._position_history[object_id]
        alpha = self.smoothing_alpha
        
        # Exponential moving average
        smoothed = Position3D(
            x=alpha * new_position.x + (1 - alpha) * old_pos.x,
            y=alpha * new_position.y + (1 - alpha) * old_pos.y,
            z=alpha * new_position.z + (1 - alpha) * old_pos.z,
            distance_meters=(
                alpha * (new_position.distance_meters or 0) + 
                (1 - alpha) * (old_pos.distance_meters or 0)
            ) if new_position.distance_meters else old_pos.distance_meters
        )
        
        self._position_history[object_id] = smoothed
        return smoothed
    
    def clear_object_history(self, object_id: str) -> None:
        """Remove an object from position history (when it leaves frame)."""
        self._position_history.pop(object_id, None)
    
    def clear_all_history(self) -> None:
        """Clear all position history."""
        self._position_history.clear()
    
    def update_frame_size(self, width: int, height: int) -> None:
        """Update frame dimensions (e.g., if camera resolution changes)."""
        self.frame_width = width
        self.frame_height = height
    
    def add_object_size(self, object_class: str, width_meters: float) -> None:
        """Add or update known object size for distance estimation."""
        self.object_sizes[object_class.lower()] = width_meters


def bbox_to_3d_position(
    bbox: Tuple[float, float, float, float],
    frame_width: int = 1920,
    frame_height: int = 1080,
    object_class: Optional[str] = None
) -> Tuple[float, float, float]:
    """
    Convenience function to convert bbox to 3D position tuple.
    
    Args:
        bbox: Bounding box as (x1, y1, x2, y2)
        frame_width: Frame width in pixels
        frame_height: Frame height in pixels
        object_class: Optional class name for distance estimation
        
    Returns:
        (x, y, z) tuple for OpenAL
    """
    calc = PositionCalculator(frame_width, frame_height)
    position = calc.bbox_to_3d(bbox, object_class)
    return position.as_tuple()


def estimate_distance_meters(
    bbox_width_pixels: float,
    object_class: str,
    focal_length_pixels: float = 1500.0
) -> Optional[float]:
    """
    Convenience function to estimate distance from bbox width.
    
    Args:
        bbox_width_pixels: Width of bounding box in pixels
        object_class: Class name for known size lookup
        focal_length_pixels: Camera focal length in pixels
        
    Returns:
        Estimated distance in meters, or None if class unknown
    """
    object_class = object_class.lower()
    if object_class not in DEFAULT_OBJECT_SIZES:
        return None
    
    known_width = DEFAULT_OBJECT_SIZES[object_class]
    
    if bbox_width_pixels <= 0:
        return None
    
    distance = (known_width * focal_length_pixels) / bbox_width_pixels
    return max(0.3, min(20.0, distance))


# ============================================================================
# Unit Tests (run with: python -m pytest src/layer3_guide/spatial_audio/position_calculator.py)
# ============================================================================

if __name__ == "__main__":
    print("Testing PositionCalculator...")
    
    calc = PositionCalculator(frame_width=1920, frame_height=1080)
    
    # Test 1: Object in center
    center_bbox = (860, 440, 1060, 640)  # Center of 1920x1080
    pos = calc.bbox_to_3d(center_bbox)
    print(f"Center object: {pos}")
    assert abs(pos.x) < 0.1, f"Expected x ≈ 0, got {pos.x}"
    assert abs(pos.y) < 0.1, f"Expected y ≈ 0, got {pos.y}"
    
    # Test 2: Object on left
    left_bbox = (0, 440, 200, 640)
    pos = calc.bbox_to_3d(left_bbox)
    print(f"Left object: {pos}")
    assert pos.x < -0.5, f"Expected x < -0.5, got {pos.x}"
    
    # Test 3: Object on right
    right_bbox = (1720, 440, 1920, 640)
    pos = calc.bbox_to_3d(right_bbox)
    print(f"Right object: {pos}")
    assert pos.x > 0.5, f"Expected x > 0.5, got {pos.x}"
    
    # Test 4: Large object (close) vs small object (far)
    large_bbox = (200, 100, 1720, 980)  # Takes up most of frame
    small_bbox = (900, 500, 1020, 580)  # Small in center
    
    pos_large = calc.bbox_to_3d(large_bbox)
    pos_small = calc.bbox_to_3d(small_bbox)
    print(f"Large (close): {pos_large}")
    print(f"Small (far): {pos_small}")
    assert abs(pos_large.z) < abs(pos_small.z), "Large bbox should be closer"
    
    # Test 5: Distance estimation with known object
    person_bbox = (760, 0, 1160, 1080)  # Person taking up ~400px width
    pos = calc.bbox_to_3d(person_bbox, object_class="person")
    print(f"Person: {pos}")
    assert pos.distance_meters is not None, "Should estimate distance for known object"
    
    # Test 6: Standalone distance function
    dist = estimate_distance_meters(375, "person", 1500)
    print(f"Person at ~2m (bbox=375px): {dist:.2f}m")
    assert dist is not None and 1.5 < dist < 2.5, f"Expected ~2m, got {dist}"
    
    print("\n✅ All tests passed!")
