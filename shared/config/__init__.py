"""
Configuration Loading Utilities for Project Cortex

Supports both YAML (RPi5) and JSON (Laptop) config files.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from .exceptions import ConfigurationError

# Default config paths
RPI5_CONFIG_PATHS = [
    "rpi5/config/config.yaml",
    "rpi5/config.yaml",
    "config.yaml",
]

LAPTOP_CONFIG_PATHS = [
    "laptop/config.json",
    "laptop/config.py",
    "config.json",
]

SHARED_CONFIG_PATHS = [
    "shared/config.json",
    "shared/config.yaml",
]


def load_yaml_config(path: str) -> Dict[str, Any]:
    """
    Load configuration from YAML file.

    Args:
        path: Path to YAML file.

    Returns:
        Configuration dictionary.

    Raises:
        ConfigurationError: If file not found or invalid.
    """
    try:
        with open(path, 'r') as f:
            config = yaml.safe_load(f)
            return config or {}
    except FileNotFoundError:
        raise ConfigurationError(f"Config file not found: {path}")
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in {path}: {e}")


def load_json_config(path: str) -> Dict[str, Any]:
    """
    Load configuration from JSON file.

    Args:
        path: Path to JSON file.

    Returns:
        Configuration dictionary.

    Raises:
        ConfigurationError: If file not found or invalid.
    """
    try:
        with open(path, 'r') as f:
            config = json.load(f)
            return config
    except FileNotFoundError:
        raise ConfigurationError(f"Config file not found: {path}")
    except json.JSONDecodeError as e:
        raise ConfigurationError(f"Invalid JSON in {path}: {e}")


def load_config(
    paths: list[str],
    device_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Load configuration from a list of possible paths.

    Args:
        paths: List of config file paths to try.
        device_type: Optional device type ('rpi5' or 'laptop') for defaults.

    Returns:
        Configuration dictionary.

    Raises:
        ConfigurationError: If no config file found.
    """
    for path in paths:
        if os.path.exists(path):
            if path.endswith('.yaml') or path.endswith('.yml'):
                return load_yaml_config(path)
            elif path.endswith('.json'):
                return load_json_config(path)

    # Try to infer from device type
    if device_type == 'rpi5':
        for path in RPI5_CONFIG_PATHS:
            if os.path.exists(path):
                return load_yaml_config(path)
    elif device_type == 'laptop':
        for path in LAPTOP_CONFIG_PATHS:
            if os.path.exists(path):
                return load_json_config(path)

    raise ConfigurationError(
        f"No config file found. Searched: {paths}",
        config_key="config_file"
    )


def load_rpi5_config() -> Dict[str, Any]:
    """Load RPi5 configuration."""
    return load_config(RPI5_CONFIG_PATHS, 'rpi5')


def load_laptop_config() -> Dict[str, Any]:
    """Load Laptop configuration."""
    return load_config(LAPTOP_CONFIG_PATHS, 'laptop')


def load_shared_config() -> Dict[str, Any]:
    """Load shared configuration."""
    return load_config(SHARED_CONFIG_PATHS)


def get_device_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract device configuration section."""
    return config.get('device', {})


def get_server_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract server configuration section."""
    return config.get('server', {})


def merge_configs(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge two configuration dictionaries.

    Overlay values override base values. Nested dicts are merged recursively.

    Args:
        base: Base configuration.
        overlay: Override configuration.

    Returns:
        Merged configuration.
    """
    result = base.copy()

    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value

    return result


def apply_env_overrides(config: Dict[str, Any], prefix: str = "CORTEX_") -> Dict[str, Any]:
    """
    Apply environment variable overrides to configuration.

    Environment variables are named as: CORTEX_SECTION_KEY

    Example:
        CORTEX_SERVER_HOST=192.168.1.100 -> config['server']['host'] = '192.168.1.100'

    Args:
        config: Configuration dictionary.
        prefix: Environment variable prefix.

    Returns:
        Configuration with env overrides applied.
    """
    result = config.copy()

    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue

        # Parse key path
        parts = key[len(prefix):].lower().split('_')
        if len(parts) < 2:
            continue

        # Navigate to the right level
        section = parts[0]
        setting = '_'.join(parts[1:])

        if section not in result:
            continue

        # Try to convert to appropriate type
        section_config = result[section]
        if isinstance(section_config, dict) and setting in section_config:
            original = section_config[setting]
            if isinstance(original, bool):
                section_config[setting] = value.lower() in ('true', '1', 'yes')
            elif isinstance(original, int):
                section_config[setting] = int(value)
            elif isinstance(original, float):
                section_config[setting] = float(value)
            else:
                section_config[setting] = value

    return result


def get_default_rpi5_config() -> Dict[str, Any]:
    """Get default RPi5 configuration."""
    return {
        'device': {
            'id': 'rpi5-cortex-001',
            'type': 'rpi5',
            'name': 'Project Cortex Wearable',
        },
        'server': {
            'host': '10.52.86.101',  # Laptop IP
            'port': 8765,
        },
        'camera': {
            'device_id': 0,
            'resolution': [1920, 1080],
            'fps': 30,
            'use_picamera': True,
        },
        'models': {
            'guardian': {
                'model_path': 'models/converted/yolo26n_ncnn_model/model.ncnn',
                'confidence': 0.5,
            },
            'learner': {
                'model_path': 'models/converted/yoloe_26n_seg/model.ncnn',
                'confidence': 0.25,
                'mode': 'TEXT_PROMPTS',
            }
        },
        'supabase': {
            'url': '',
            'anon_key': '',
            'device_id': 'rpi5-cortex-001',
            'sync_interval': 60,
        },
        'logging': {
            'level': 'INFO',
        }
    }


def get_default_laptop_config() -> Dict[str, Any]:
    """Get default Laptop configuration."""
    return {
        'device': {
            'id': 'laptop-dashboard-001',
            'type': 'laptop',
            'name': 'Project Cortex Dashboard',
        },
        'server': {
            'host': '0.0.0.0',
            'port': 8765,
            'max_clients': 5,
        },
        'camera': {
            'device_id': 0,
            'resolution': [1920, 1080],
            'fps': 30,
        },
        'logging': {
            'level': 'INFO',
        },
        'gui': {
            'width': 1280,
            'height': 720,
            'theme': 'dark',
        }
    }


# Re-export exceptions for convenience
from .exceptions import ConfigurationError

__all__ = [
    'load_yaml_config',
    'load_json_config',
    'load_config',
    'load_rpi5_config',
    'load_laptop_config',
    'load_shared_config',
    'get_device_config',
    'get_server_config',
    'merge_configs',
    'apply_env_overrides',
    'get_default_rpi5_config',
    'get_default_laptop_config',
    'ConfigurationError',
    'RPI5_CONFIG_PATHS',
    'LAPTOP_CONFIG_PATHS',
    'SHARED_CONFIG_PATHS',
]
