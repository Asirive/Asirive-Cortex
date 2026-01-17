"""
Configuration module for ProjectCortex RPi5

Loads configuration from config.yaml and provides get_config() function.

Author: Haziq (@IRSPlays)
Date: January 8, 2026
"""

import os
from pathlib import Path
from typing import Any, Dict

import yaml


# Default configuration path
CONFIG_PATH = Path(__file__).parent / "config.yaml"

# Cache for loaded config
_config_cache: Dict[str, Any] = {}


def load_config(config_path: str = None) -> Dict[str, Any]:
    """Load configuration from YAML file"""
    global _config_cache

    if config_path is None:
        config_path = str(CONFIG_PATH)

    # Return cached config if available
    if config_path in _config_cache:
        return _config_cache[config_path]

    default_config = {
        'supabase': {
            'url': os.getenv('SUPABASE_URL', ''),
            'anon_key': os.getenv('SUPABASE_KEY', ''),
            'device_id': os.getenv('DEVICE_ID', 'rpi5-cortex-001'),
            'sync_interval_seconds': 60,
            'batch_size': 100,
            'local_cache_size': 1000,
            'local_db_path': 'local_cortex.db'
        },
        'layer0': {
            'model_path': 'models/yolo11n_ncnn_model',
            'device': 'cpu',
            'confidence': 0.5,
            'enable_haptic': True,
            'gpio_pin': 18
        },
        'layer1': {
            'model_path': 'models/yoloe-11s-seg_ncnn_model',
            'device': 'cpu',
            'confidence': 0.25,
            'mode': 'TEXT_PROMPTS'
        },
        'layer2': {
            'gemini_api_key': os.getenv('GEMINI_API_KEY', ''),
            'model': 'gemini-2.0-flash-exp',
            'enable_live_api': True
        },
        'camera': {
            'device_id': 0,
            'use_picamera': True,
            'resolution': [1920, 1080],
            'fps': 30
        },
        'laptop_server': {
            'host': os.getenv('LAPTOP_HOST', 'localhost'),
            'port': int(os.getenv('LAPTOP_PORT', 8765))
        }
    }

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Merge with defaults
        for key in default_config:
            if key not in config:
                config[key] = default_config[key]

        _config_cache[config_path] = config
        return config

    except FileNotFoundError:
        print(f"Config file not found: {config_path}, using defaults")
        _config_cache[config_path] = default_config
        return default_config
    except Exception as e:
        print(f"Error loading config: {e}, using defaults")
        _config_cache[config_path] = default_config
        return default_config


def get_config() -> Dict[str, Any]:
    """Get configuration (loads from default path if not cached)"""
    return load_config()


def save_config(config: Dict[str, Any], config_path: str = None):
    """Save configuration to YAML file"""
    if config_path is None:
        config_path = str(CONFIG_PATH)

    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, indent=2)

    # Update cache
    _config_cache[config_path] = config


__all__ = ["load_config", "get_config", "save_config"]
