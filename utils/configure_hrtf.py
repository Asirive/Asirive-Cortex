#!/usr/bin/env python3
"""
Project-Cortex v2.0 - OpenAL-Soft HRTF Configuration Helper

This script helps configure OpenAL-Soft for optimal HRTF spatial audio.

OpenAL-Soft requires specific settings in alsoft.ini for proper HRTF:
- hrtf = true (enables HRTF processing)
- stereo-encoding = hrtf (applies HRTF to stereo output)
- hrtf-mode = full (best quality HRTF)

Author: Haziq (@IRSPlays)
"""

import os
import sys
from pathlib import Path


def get_alsoft_ini_path() -> Path:
    """Get the path to alsoft.ini config file based on OS."""
    if sys.platform == 'win32':
        # Windows: %APPDATA%\alsoft.ini
        appdata = os.environ.get('APPDATA', '')
        if appdata:
            return Path(appdata) / 'alsoft.ini'
        return Path.home() / 'AppData' / 'Roaming' / 'alsoft.ini'
    elif sys.platform == 'darwin':
        # macOS: ~/Library/Preferences/alsoft.ini
        return Path.home() / 'Library' / 'Preferences' / 'alsoft.ini'
    else:
        # Linux: ~/.alsoftrc or /etc/openal/alsoft.conf
        linux_path = Path.home() / '.alsoftrc'
        if linux_path.exists():
            return linux_path
        return Path('/etc/openal/alsoft.conf')


def get_optimal_hrtf_config() -> str:
    """Get optimal OpenAL-Soft configuration for HRTF spatial audio."""
    return """# OpenAL-Soft Configuration for Project-Cortex Spatial Audio
# =============================================================
# This configuration optimizes HRTF for assistive technology use.
# 
# HRTF (Head-Related Transfer Function) enables realistic 3D audio
# positioning through regular stereo headphones.

[general]
# Enable HRTF for binaural 3D audio
hrtf = true

# Use HRTF for stereo output (required for headphones)
stereo-encoding = hrtf

# HRTF rendering mode:
#   full   = best quality, unique HRIR per source
#   ambi1  = first-order ambisonic (lower CPU)
#   ambi2  = second-order ambisonic
#   ambi3  = third-order ambisonic
hrtf-mode = full

# Sample rate (44100 is standard)
frequency = 44100

# Period size for low latency (256-1024 recommended)
period_size = 512

# Number of periods (2-4 recommended)
periods = 4

# Resampler quality (linear, sinc4, sinc8, bsinc12, bsinc24)
resampler = sinc8

# Output channels (stereo for headphones)
channels = stereo

[reverb]
# Disable reverb for clarity in assistive audio
boost = 0

[decoder]
# Decoder settings for HRTF
quad = off
surround51 = off
surround61 = off
surround71 = off

"""


def check_current_config() -> dict:
    """Check the current OpenAL-Soft configuration."""
    config_path = get_alsoft_ini_path()
    result = {
        'path': str(config_path),
        'exists': config_path.exists(),
        'hrtf_enabled': False,
        'stereo_encoding': None,
        'hrtf_mode': None,
        'issues': []
    }
    
    if not config_path.exists():
        result['issues'].append("No alsoft.ini found - OpenAL-Soft uses defaults")
        return result
    
    try:
        content = config_path.read_text()
        lines = content.lower().split('\n')
        
        for line in lines:
            line = line.strip()
            if line.startswith('hrtf') and '=' in line:
                value = line.split('=')[1].strip()
                result['hrtf_enabled'] = value in ('true', '1', 'yes')
            elif line.startswith('stereo-encoding') and '=' in line:
                result['stereo_encoding'] = line.split('=')[1].strip()
            elif line.startswith('hrtf-mode') and '=' in line:
                result['hrtf_mode'] = line.split('=')[1].strip()
        
        if not result['hrtf_enabled']:
            result['issues'].append("HRTF is not enabled")
        if result['stereo_encoding'] != 'hrtf':
            result['issues'].append("stereo-encoding is not set to 'hrtf'")
        if result['hrtf_mode'] not in ('full', None):
            result['issues'].append(f"hrtf-mode is '{result['hrtf_mode']}' (recommend 'full')")
            
    except Exception as e:
        result['issues'].append(f"Error reading config: {e}")
    
    return result


def create_optimal_config(backup: bool = True) -> bool:
    """Create optimal alsoft.ini configuration."""
    config_path = get_alsoft_ini_path()
    
    try:
        # Backup existing config
        if backup and config_path.exists():
            backup_path = config_path.with_suffix('.ini.backup')
            config_path.rename(backup_path)
            print(f"  📋 Backed up existing config to: {backup_path}")
        
        # Write new config
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(get_optimal_hrtf_config())
        print(f"  ✅ Created optimal HRTF config at: {config_path}")
        return True
        
    except Exception as e:
        print(f"  ❌ Failed to create config: {e}")
        return False


def main():
    print("=" * 70)
    print("🎧 OpenAL-Soft HRTF Configuration Helper")
    print("   For Project-Cortex Spatial Audio")
    print("=" * 70)
    print()
    
    # Check current configuration
    print("📋 Checking current OpenAL-Soft configuration...")
    config = check_current_config()
    print(f"   Config path: {config['path']}")
    print(f"   Config exists: {config['exists']}")
    
    if config['exists']:
        print(f"   HRTF enabled: {config['hrtf_enabled']}")
        print(f"   Stereo encoding: {config['stereo_encoding']}")
        print(f"   HRTF mode: {config['hrtf_mode']}")
    
    print()
    
    if config['issues']:
        print("⚠️  Issues found:")
        for issue in config['issues']:
            print(f"   - {issue}")
        print()
        
        response = input("Would you like to create an optimal HRTF config? (y/n): ").strip().lower()
        if response == 'y':
            print()
            print("Creating optimal HRTF configuration...")
            if create_optimal_config():
                print()
                print("✅ Configuration complete!")
                print()
                print("⚠️  IMPORTANT: You may need to restart any applications")
                print("   using OpenAL for the changes to take effect.")
            else:
                print("❌ Failed to create configuration")
    else:
        print("✅ OpenAL-Soft is properly configured for HRTF!")
    
    print()
    print("-" * 70)
    print("📖 Configuration explained:")
    print("-" * 70)
    print("""
    hrtf = true
        Enables Head-Related Transfer Function processing.
        This simulates how sound reaches your ears in 3D space.
    
    stereo-encoding = hrtf
        Applies HRTF to stereo output (required for headphones).
    
    hrtf-mode = full
        Uses full HRTF processing with unique impulse response
        per audio source. This gives the clearest directional cues.
    """)


if __name__ == "__main__":
    main()
