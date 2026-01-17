#!/usr/bin/env python3
"""
Sync Project Cortex to Raspberry Pi 5 via rsync.
Installs dependencies on RPi5 after sync.
"""
import os
import subprocess
import sys

# Configuration
RPI_HOST = "pi@raspberrypi.local"  # or IP like "pi@192.168.1.100"
RPI_PATH = "/home/pi/ProjectCortex"
LAPTOP_PATH = os.path.dirname(os.path.abspath(__file__))

# Directories/Files to sync
SYNC_PATHS = [
    "rpi5/",
    "models/converted/",
    "requirements.txt",
    "sync.bat",
]

# RPi5-specific install script
RPI_INSTALL_SCRIPT = """#!/bin/bash
cd /home/pi/ProjectCortex
echo "Installing dependencies..."
pip install -r requirements.txt
echo "Done!"
"""

def run_command(cmd, check=True):
    """Run a shell command."""
    print(f"  Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  ERROR: {result.stderr}")
        return False
    return True

def sync_to_rpi():
    """Sync files to Raspberry Pi."""
    print("\n" + "="*60)
    print("SYNCING TO RASPBERRY PI 5")
    print("="*60)

    # Build rsync command
    rsync_paths = " ".join(SYNC_PATHS)
    cmd = (
        f"rsync -avz --delete --progress "
        f"-e ssh -o StrictHostKeyChecking=no "
        f"{rsync_paths} "
        f"{RPI_HOST}:{RPI_PATH}/"
    )

    print(f"\nTarget: {RPI_HOST}:{RPI_PATH}/")
    if not run_command(cmd):
        print("Sync FAILED!")
        return False

    print("Sync SUCCESS!")
    return True

def install_deps_on_rpi():
    """Install dependencies on RPi5."""
    print("\n" + "="*60)
    print("INSTALLING DEPENDENCIES ON RPI5")
    print("="*60)

    # Create install script on RPi5
    script_path = "/tmp/rpi_install.sh"
    with open(script_path, "w") as f:
        f.write(RPI_INSTALL_SCRIPT)

    # Copy script to RPi5
    cmd = f"scp -o StrictHostKeyChecking=no {script_path} {RPI_HOST}:/tmp/"
    if not run_command(cmd):
        return False

    # Run install script
    cmd = f"ssh -o StrictHostKeyChecking=no {RPI_HOST} 'chmod +x /tmp/rpi_install.sh && bash /tmp/rpi_install.sh'"
    if not run_command(cmd):
        print("Dep install FAILED!")
        return False

    print("Dependencies installed!")
    return True

def sync_from_rpi():
    """Sync files FROM Raspberry Pi (for getting logs/data)."""
    print("\n" + "="*60)
    print("SYNCING FROM RASPBERRY PI 5")
    print("="*60)

    # Only sync logs and data folders
    cmd = (
        f"rsync -avz --progress "
        f"-e ssh -o StrictHostKeyChecking=no "
        f"{RPI_HOST}:{RPI_PATH}/logs/ "
        f"{LAPTOP_PATH}/logs/"
    )

    print(f"Source: {RPI_HOST}:{RPI_PATH}/logs/")
    return run_command(cmd)

def main():
    print("="*60)
    print("Project Cortex - RPi5 Sync Tool")
    print("="*60)
    print(f"RPi5 Host: {RPI_HOST}")
    print(f"Local Path: {LAPTOP_PATH}")

    if len(sys.argv) < 2:
        print("\nUsage: python sync_rpi5.py <command>")
        print("\nCommands:")
        print("  to-rpi      - Sync files TO RPi5 (default)")
        print("  from-rpi    - Sync files FROM RPi5 (logs)")
        print("  install     - Install dependencies on RPi5")
        print("  full        - Sync to RPi5 AND install deps")
        print("\nExamples:")
        print("  python sync_rpi5.py full")
        print("  python sync_rpi5.py to-rpi")

    command = sys.argv[1] if len(sys.argv) > 1 else "to-rpi"

    if command == "to-rpi":
        sync_to_rpi()
    elif command == "from-rpi":
        sync_from_rpi()
    elif command == "install":
        install_deps_on_rpi()
    elif command == "full":
        if sync_to_rpi():
            install_deps_on_rpi()
    else:
        print(f"Unknown command: {command}")

if __name__ == "__main__":
    main()
