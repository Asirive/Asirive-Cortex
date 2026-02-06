"""
Configuration for Laptop Dashboard

Centralized configuration for:
- WebSocket server settings
- GUI settings
- Performance tuning
- Logging configuration

Author: Haziq (@IRSPlays)
Date: January 8, 2026
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class DashboardConfig:
    """Laptop dashboard configuration"""

    # WebSocket Server
    ws_host: str = "0.0.0.0"
    ws_port: int = 8765
    ws_max_clients: int = 5
    ws_max_message_size: int = 10 * 1024 * 1024  # 10MB
    ws_ping_interval: int = 30  # seconds
    ws_ping_timeout: int = 10  # seconds

    # GUI Settings
    gui_title: str = "ProjectCortex v2.0 - Dashboard"
    gui_width: int = 1400
    gui_height: int = 900
    gui_theme: str = "dark"  # dark | light
    gui_update_interval: int = 30  # ms (~33 FPS for GUI updates)

    # Video Display
    video_width: int = 640
    video_height: int = 480
    video_fps: int = 30
    video_quality: int = 85  # JPEG quality (1-100)

    # Metrics Display
    metrics_update_interval: int = 1000  # ms (1 second)
    metrics_history_size: int = 60  # Keep last 60 data points

    # Detection Log
    detection_log_max_entries: int = 100
    detection_log_auto_scroll: bool = True

    # System Log
    system_log_max_entries: int = 500
    system_log_auto_scroll: bool = True

    # Performance
    video_decoding_threads: int = 2
    message_queue_size: int = 1000

    # Logging
    log_level: str = "INFO"  # DEBUG | INFO | WARNING | ERROR
    log_file: str = "laptop_dashboard.log"
    log_max_size_mb: int = 10
    log_backup_count: int = 3

    # Features
    enable_video: bool = True
    enable_metrics: bool = True
    enable_detections: bool = True
    enable_gps: bool = False
    enable_audio: bool = False

    # Colors (Dark Theme)
    color_background: str = "#1e1e1e"
    color_foreground: str = "#ffffff"
    color_primary: str = "#007acc"
    color_success: str = "#4ec9b0"
    color_warning: str = "#ce9178"
    color_error: str = "#f48771"
    color_info: str = "#9cdcfe"

    # Supabase (Optional - for historical data)
    supabase_url: str = "https://ziarxgoansbhesdypfic.supabase.co"
    supabase_key: str = "sb_publishable_ErFxooa2JFiE8eXtd4hx3Q_Yll74lv_"
    supabase_fetch_interval: int = 60  # seconds (for historical data)


@dataclass
class YOLOEConfig:
    """YOLOE text-prompt configuration for Layer 1 (Learner) on laptop GPU"""

    # Model
    model_path: str = "models/yoloe-26x-seg.pt"   # Text-prompt variant (NOT -pf)
    device: str = "cuda:0"
    confidence: float = 0.40                       # Raised from 0.25 to reduce false positives
    use_half: bool = True                          # FP16 on GPU

    # ~118 curated classes for visually-impaired navigation
    text_prompts: List[str] = field(default_factory=lambda: [
        # ── People & Body ──
        "person", "child", "baby", "face", "hand",

        # ── Vehicles ──
        "car", "truck", "bus", "van", "motorcycle", "bicycle",
        "scooter", "skateboard", "wheelchair", "stroller", "shopping cart",

        # ── Animals ──
        "dog", "cat", "bird",

        # ── Road & Sidewalk ──
        "traffic light", "stop sign", "fire hydrant", "parking meter",
        "bench", "pole", "bollard", "crosswalk", "curb", "pothole",
        "construction cone", "barrier", "fence", "gate", "wall",

        # ── Doors & Access ──
        "door", "metal gate", "wooden door", "stairs", "step",
        "railing", "handrail", "elevator", "escalator",
        "peephole", "doorbell",

        # ── Indoor Furniture ──
        "chair", "table", "desk", "couch", "bed", "shelf",
        "cabinet", "drawer", "counter", "nightstand",

        # ── Common Carried Objects ──
        "backpack", "handbag", "suitcase", "umbrella", "wallet",
        "keys", "glasses", "sunglasses", "hat", "shoe", "cane", "crutch",

        # ── Kitchen & Food ──
        "bottle", "cup", "glass", "plate", "bowl",
        "fork", "knife", "spoon",
        "oven", "microwave", "refrigerator",

        # ── Bathroom ──
        "sink", "faucet", "toilet", "bathtub", "mirror", "towel",

        # ── Electronics ──
        "phone", "laptop", "monitor", "keyboard", "mouse",
        "remote", "television", "speaker", "camera",

        # ── Household ──
        "book", "clock", "plant", "vase", "lamp", "fan",
        "box", "basket", "trash can", "fire extinguisher",
        "pillow", "blanket", "curtain", "rug",

        # ── Signs ──
        "sign", "banner", "poster", "notice board",

        # ── Singapore: HDB & Home ──
        "blast door", "refuse chute", "bamboo pole",
        "clothes drying rack", "circuit breaker", "letterbox",

        # ── Singapore: Neighbourhood ──
        "stone table", "recycling bin", "electrical box",
        "digital display", "vending machine",

        # ── Singapore: Transport ──
        "card reader", "gantry", "push button", "bus stop",
        "priority seat", "emergency button", "route map",

        # ── Singapore: Malls & Food Courts ──
        "tray return station", "tissue packet",
        "nursing room", "energy label",
    ])


# Default configuration instance
default_config = DashboardConfig()


def load_config(config_file: str = None) -> DashboardConfig:
    """
    Load configuration from file or use defaults

    Args:
        config_file: Path to configuration JSON file (optional)

    Returns:
        DashboardConfig instance
    """
    import json
    from pathlib import Path

    config = DashboardConfig()

    if config_file and Path(config_file).exists():
        with open(config_file, 'r') as f:
            data = json.load(f)
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)

    return config


def save_config(config: DashboardConfig, config_file: str):
    """
    Save configuration to file

    Args:
        config: DashboardConfig instance
        config_file: Path to save configuration
    """
    import json
    from dataclasses import asdict

    with open(config_file, 'w') as f:
        json.dump(asdict(config), f, indent=2)


if __name__ == "__main__":
    # Test configuration
    config = default_config
    print("Dashboard Configuration:")
    print(f"  WebSocket: {config.ws_host}:{config.ws_port}")
    print(f"  Max Clients: {config.ws_max_clients}")
    print(f"  GUI Size: {config.gui_width}x{config.gui_height}")
    print(f"  Video: {config.video_width}x{config.video_height}@{config.video_fps}fps")
    print(f"  Theme: {config.gui_theme}")
