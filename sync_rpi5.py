#!/usr/bin/env python3
"""
Sync Project Cortex to Raspberry Pi 5 via rsync or scp.
Installs dependencies on RPi5 after sync.

Network Configuration:
- RPi5 IP: 192.168.0.92
- Laptop IP: 192.168.0.171
- RPi5 Password: Haziqshah21

Usage:
    python sync_rpi5.py full

Requirements:
    - rsync (Linux/Mac/Git Bash): Preferred for large syncs
    - sshpass (optional): For automatic password entry
    - OR scp (Windows native): Fallback if rsync not available

Environment Variables:
    RPI_PASSWORD - Password for RPi5 (if not set, will prompt)
"""
import os
import subprocess
import sys
import shutil
import tarfile
import tempfile
import time
import getpass

try:
    import paramiko
    # from scp import SCPClient  <-- caused ImportError, not required for SFTP
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False
    # If paramiko is missing, we can try to install it or just warn
    # print("Paramiko not found. Install with: pip install paramiko scp")

def load_rpi_config():
    """Load RPi5 configuration from config.yaml."""
    import yaml
    from pathlib import Path
    
    config_paths = [
        Path(__file__).parent / "rpi5" / "config" / "config.yaml",
        Path(__file__).parent.parent / "ProjectCortex" / "rpi5" / "config" / "config.yaml",
    ]
    
    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                
                rpi_config = config.get('rpi5_device', {})
                return {
                    'host': rpi_config.get('host', '10.52.86.31'),
                    'user': rpi_config.get('user', 'cortex'),
                    'path': rpi_config.get('path', '/home/cortex/ProjectCortex'),
                }
            except Exception as e:
                print(f"Warning: Could not load config from {config_path}: {e}")
    
    # Fallback to defaults
    print("Warning: Could not load config.yaml, using defaults")
    return {
        'host': '10.52.86.31',
        'user': 'cortex',
        'path': '/home/cortex/ProjectCortex',
    }

# Load configuration from config.yaml
_rpi_config = load_rpi_config()

# Configuration (loaded from config.yaml or defaults)
RPI_HOST_IP = _rpi_config['host']
RPI_USER = _rpi_config['user']
RPI_HOST = f"{RPI_USER}@{RPI_HOST_IP}"
RPI_PATH = _rpi_config['path']
LAPTOP_PATH = os.path.dirname(os.path.abspath(__file__))

# Get password from environment or prompt
def get_rpi_password():
    """Get RPi5 password (hardcoded for automation)."""
    # Use env var if set, otherwise use hardcoded password
    return os.environ.get("RPI_PASSWORD", "Haziqshah21")

RPI_PASSWORD = get_rpi_password()

# Directories/Files to sync
SYNC_PATHS = [
    "rpi5/",
    "laptop/",
    "shared/",
    "models/",  # Sync all models including .pt files
    "requirements.txt",
    ".env",  # Sync environment variables (API keys)
]

# Files to exclude from sync
EXCLUDE_PATTERNS = [
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".git/",
    ".gitignore",
    "logs/",
    "*.log",
    "*.db",
    "laptop/gui/__pycache__/",
    "rpi5/__pycache__/",
    "shared/api/__pycache__/",
    "shared/config/__pycache__/",
]

# RPi5-specific install script
RPI_INSTALL_SCRIPT = """#!/bin/bash
cd /home/cortex/ProjectCortex
echo "Installing dependencies..."
pip install -r requirements.txt
echo "Done!"
"""

def run_command(cmd, check=True, verbose=True):
    """Run a shell command."""
    if verbose:
        print(f"  Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  Output: {result.stdout.strip()}")
    if check and result.returncode != 0:
        print(f"  ERROR: {result.stderr}")
        return False
    return True

def has_rsync():
    """Check if rsync is available."""
    return shutil.which("rsync") is not None

def has_sshpass():
    """Check if sshpass is available."""
    return shutil.which("sshpass") is not None

def get_ssh_cmd():
    """Get SSH command with password."""
    if has_sshpass():
        return f"sshpass -p {RPI_PASSWORD} ssh -o StrictHostKeyChecking=no"
    else:
        return f"ssh -o StrictHostKeyChecking=no"

def get_scp_cmd():
    """Get SCP command with password."""
    if has_sshpass():
        return f"sshpass -p {RPI_PASSWORD} scp -o StrictHostKeyChecking=no"
    else:
        return f"scp -o StrictHostKeyChecking=no"

def create_ssh_client():
    """Create a paramiko SSH client."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(RPI_HOST_IP, username=RPI_USER, password=RPI_PASSWORD, timeout=10)
        return client
    except Exception as e:
        print(f"SSH Connection Failed: {e}")
        return None

def sync_with_paramiko():
    """Sync using Paramiko (Python SSH/SCP implementation)."""
    print("\nUsing Paramiko for sync...")
    
    # Create tarball first (efficient transfer)
    timestamp = int(time.time())
    tar_name = f"cortex_sync_{timestamp}.tar.gz"
    temp_dir = tempfile.gettempdir()
    tar_path = os.path.join(temp_dir, tar_name)
    
    print(f"Creating tarball: {tar_name}")
    try:
        with tarfile.open(tar_path, "w:gz") as tar:
            for sync_path in SYNC_PATHS:
                full_path = os.path.join(LAPTOP_PATH, sync_path)
                if os.path.exists(full_path):
                    tar.add(full_path, arcname=sync_path)
                    print(f"  Added: {sync_path}")
            # Also add .env file explicitly if needed
            env_path = os.path.join(LAPTOP_PATH, ".env")
            if os.path.exists(env_path):
                 tar.add(env_path, arcname=".env")
                 print(f"  Added: .env")
        
        print(f"Tarball created: {os.path.getsize(tar_path) / (1024*1024):.1f} MB")
        
        # Connect via SSH
        print(f"Connecting to {RPI_HOST_IP}...")
        ssh = create_ssh_client()
        if not ssh:
            return False
            
        # Upload tarball
        print("Uploading tarball...")
        sftp = ssh.open_sftp()
        sftp.put(tar_path, f"/tmp/{tar_name}")
        sftp.close()
        print("Upload complete!")
        
        # Extract on RPi
        print("Extracting on RPi5...")
        remote_cmd = f"mkdir -p {RPI_PATH} && rm -rf {RPI_PATH}/rpi5 {RPI_PATH}/laptop {RPI_PATH}/shared {RPI_PATH}/models {RPI_PATH}/.env && cd {RPI_PATH} && tar -xzf /tmp/{tar_name} && rm /tmp/{tar_name}"
        stdin, stdout, stderr = ssh.exec_command(remote_cmd)
        exit_status = stdout.channel.recv_exit_status()
        
        if exit_status == 0:
            print("Extraction successful!")
        else:
            print(f"Extraction failed: {stderr.read().decode()}")
            ssh.close()
            return False
            
        ssh.close()
        
        # Cleanup local tarball
        os.remove(tar_path)
        
        print("Sync SUCCESS!")
        return True
        
    except Exception as e:
        print(f"Paramiko Sync Error: {e}")
        if os.path.exists(tar_path):
            os.remove(tar_path)
        return False

def sync_to_rpi():
    """Sync files to Raspberry Pi."""
    print("\n" + "="*60)
    print("SYNCING TO RASPBERRY PI 5")
    print("="*60)

    # Prefer Paramiko if available (supports password)
    if PARAMIKO_AVAILABLE:
        return sync_with_paramiko()
        
    # Fallback to rsync if available
    if has_rsync():
        print("Using rsync (preferred)")
        return sync_with_rsync()
    else:
        print("rsync not found, using scp+tar (fallback)")
        return sync_with_scp()

def sync_with_rsync():
    """Sync using rsync (Linux/Mac/Git Bash)."""
    rsync_paths = " ".join(SYNC_PATHS)
    exclude_args = " ".join(f"--exclude={p}" for p in EXCLUDE_PATTERNS)
    ssh_cmd = get_ssh_cmd()
    cmd = (
        f"rsync -avz --delete --progress "
        f"{exclude_args} "
        f"-e '{ssh_cmd}' "
        f"{rsync_paths} "
        f"{RPI_HOST}:{RPI_PATH}/"
    )

    print(f"\nTarget: {RPI_HOST}:{RPI_PATH}/")
    print(f"Syncing: {', '.join(SYNC_PATHS)}")
    if not run_command(cmd):
        print("Sync FAILED!")
        return False

    print("Sync SUCCESS!")
    return True

def sync_with_scp():
    """Sync using scp+tar (Windows native fallback).

    Creates a tarball locally, transfers it, and extracts on RPi5.
    """
    # Create tarball name
    timestamp = int(time.time())
    tar_name = f"cortex_sync_{timestamp}.tar.gz"
    temp_dir = tempfile.gettempdir()
    tar_path = os.path.join(temp_dir, tar_name)

    print(f"\nCreating tarball: {tar_name}")

    try:
        # Create tarball (excluding unwanted patterns)
        with tarfile.open(tar_path, "w:gz") as tar:
            for sync_path in SYNC_PATHS:
                full_path = os.path.join(LAPTOP_PATH, sync_path)
                if os.path.exists(full_path):
                    # Add base name to archive
                    tar.add(full_path, arcname=sync_path)
                    print(f"  Added: {sync_path}")
            # Also add .env file explicitly
            env_path = os.path.join(LAPTOP_PATH, ".env")
            if os.path.exists(env_path):
                tar.add(env_path, arcname=".env")
                print(f"  Added: .env")

        print(f"Tarball created: {os.path.getsize(tar_path) / (1024*1024):.1f} MB")

        # Copy tarball to RPi5
        print(f"\nTransferring to RPi5...")
        # Note: scp on Windows will prompt for password if sshpass is missing
        # This is why we prefer Paramiko
        scp_full_cmd = get_scp_cmd()
        scp_cmd = f'{scp_full_cmd} "{tar_path}" {RPI_HOST}:/tmp/'
        if not run_command(scp_cmd):
            return False

        # Verify tarball exists on RPi5
        print("Verifying transfer...")
        # Use double quotes for the SSH command to avoid quote nesting issues
        ssh_full_cmd = get_ssh_cmd()
        check_cmd = f'{ssh_full_cmd} {RPI_HOST} "ls -lh /tmp/{tar_name} && stat -c%s /tmp/{tar_name}"'
        if not run_command(check_cmd):
            print("Tarball transfer FAILED! File not found on RPi5.")
            return False
        print("  Transfer verified successfully!")

        # Extract on RPi5
        print("Extracting on RPi5...")
        ssh_full_cmd = get_ssh_cmd()
        extract_cmd = f'{ssh_full_cmd} {RPI_HOST} "mkdir -p {RPI_PATH} && rm -rf {RPI_PATH}/rpi5 {RPI_PATH}/laptop {RPI_PATH}/shared {RPI_PATH}/models/converted {RPI_PATH}/.env && cd {RPI_PATH} && tar -xzf /tmp/{tar_name} && rm /tmp/{tar_name}"'
        if not run_command(extract_cmd):
            print("Extraction FAILED!")
            return False

        # Cleanup local tarball
        os.remove(tar_path)

        print("Sync SUCCESS!")
        return True

    except Exception as e:
        print(f"Sync ERROR: {e}")
        # Cleanup on error
        if os.path.exists(tar_path):
            os.remove(tar_path)
        return False

def install_deps_on_rpi():
    """Install dependencies on RPi5."""
    print("\n" + "="*60)
    print("INSTALLING DEPENDENCIES ON RPI5")
    print("="*60)

    if PARAMIKO_AVAILABLE:
        print("Using Paramiko for remote installation...")
        ssh = create_ssh_client()
        if not ssh:
            return False
            
        print("Installing dependencies (this may take a while)...")
        # Run pip install directly via SSH
        cmd = f"cd {RPI_PATH} && pip install -r requirements.txt"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        
        # Stream output
        while True:
            line = stdout.readline()
            if not line:
                break
            print(line.strip())
            
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            print(f"Dependency install failed: {stderr.read().decode()}")
            ssh.close()
            return False
            
        print("Dependencies installed successfully!")
        ssh.close()
        return True

    # Use existing scp/ssh method (will prompt for password)
    # Create install script locally first (Windows temp)
    local_script = os.path.join(tempfile.gettempdir(), "rpi_install.sh")
    with open(local_script, "w") as f:
        f.write(RPI_INSTALL_SCRIPT)

    # Copy script to RPi5
    print("Copying install script to RPi5...")
    scp_full_cmd = get_scp_cmd()
    cmd = f'{scp_full_cmd} "{local_script}" {RPI_HOST}:/tmp/rpi_install.sh'
    if not run_command(cmd):
        return False

    # Run install script
    print("Running install script...")
    ssh_full_cmd = get_ssh_cmd()
    cmd = f'{ssh_full_cmd} {RPI_HOST} "chmod +x /tmp/rpi_install.sh && bash /tmp/rpi_install.sh"'
    if not run_command(cmd):
        print("Dep install FAILED!")
        return False

    # Cleanup local script
    os.remove(local_script)

    print("Dependencies installed!")
    return True

def sync_from_rpi():
    """Sync files FROM Raspberry Pi (for getting logs/data)."""
    print("\n" + "="*60)
    print("SYNCING FROM RASPBERRY PI 5")
    print("="*60)

    if PARAMIKO_AVAILABLE:
        print("Using Paramiko for download...")
        ssh = create_ssh_client()
        if not ssh:
            return False
            
        sftp = ssh.open_sftp()
        try:
            # Recursive download is tricky with paramiko sftp, 
            # might be easier to zip regarding folders and download
            print("Downloading logs (zipping remote first)...")
            ssh.exec_command(f"cd {RPI_PATH} && tar -czf /tmp/logs.tar.gz logs")
            
            local_tar = os.path.join(LAPTOP_PATH, "logs.tar.gz")
            sftp.get("/tmp/logs.tar.gz", local_tar)
            
            # Extract local
            with tarfile.open(local_tar, "r:gz") as tar:
                tar.extractall(LAPTOP_PATH)
            
            os.remove(local_tar)
            ssh.exec_command("rm /tmp/logs.tar.gz")
            print("Logs downloaded!")
            return True
        except Exception as e:
            print(f"Download failed: {e}")
            return False

    # Only sync logs and data folders
    ssh_full_cmd = get_ssh_cmd()
    cmd = (
        f"rsync -avz --progress "
        f"-e '{ssh_full_cmd}' "
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
    print(f"Laptop IP: 192.168.0.171")
    print(f"Local Path: {LAPTOP_PATH}")
    print(f"Paramiko Available: {PARAMIKO_AVAILABLE}")
    if PARAMIKO_AVAILABLE:
        print("  -> Password-based auth ENABLED (No manual entry required)")

    if len(sys.argv) < 2:
        print("\nUsage: python sync_rpi5.py <command>")
        print("\nCommands:")
        print("  to-rpi      - Sync files TO RPi5 (default)")
        print("  from-rpi    - Sync files FROM RPi5 (logs)")
        print("  install     - Install dependencies on RPi5")
        print("  full        - Sync to RPi5 AND install deps")
        print("\nSync paths:")
        for path in SYNC_PATHS:
            print(f"  - {path}")
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
