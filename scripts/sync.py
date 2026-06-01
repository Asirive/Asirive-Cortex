#!/usr/bin/env python3
"""
Cortex Sync — Modern RPi5 ↔ Laptop Synchronization Tool

Replaces: python sync_rpi5.py full
Usage:    python -m scripts.sync <command> [options]
          cortex sync <command> [options]   (when integrated)

Commands:
  to        Sync code TO RPi5
  from      Sync data FROM RPi5 (logs, recordings)
  install   Install/update deps on RPi5
  full      to + install in one step
  check     Test SSH connection without syncing
  status    Show what would be synced (dry-run)

Examples:
  python -m scripts.sync to                    # Fast code-only sync
  python -m scripts.sync to --models           # Include models/
  python -m scripts.sync from --logs           # Download only logs
  python -m scripts.sync full --models         # Everything
  python -m scripts.sync check                 # Verify connectivity
  python -m scripts.sync status                # Preview changes

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — YIA 2026
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ─── ANSI Colors ──────────────────────────────────────────────────
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"

def _c(text: str, color: str) -> str:
    return f"{color}{text}{Colors.RESET}"

# ─── Configuration ────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
RPI5_DIR = PROJECT_ROOT / "rpi5"
CONFIG_PATH = RPI5_DIR / "config" / "config.yaml"

def load_config() -> Dict:
    """Load network config from config.yaml."""
    if CONFIG_PATH.exists():
        try:
            import yaml
            with open(CONFIG_PATH) as f:
                cfg = yaml.safe_load(f)
            return {
                "host": cfg.get("rpi5_device", {}).get("host", "10.41.240.31"),
                "user": cfg.get("rpi5_device", {}).get("user", "cortex"),
                "path": cfg.get("rpi5_device", {}).get("path", "/home/cortex/ProjectCortex"),
                "laptop_host": cfg.get("laptop_server", {}).get("host", "10.41.240.101"),
            }
        except Exception as e:
            print(_c(f"Warning: could not load config.yaml: {e}", Colors.YELLOW))
    
    return {
        "host": "10.41.240.31",
        "user": "cortex",
        "path": "/home/cortex/ProjectCortex",
        "laptop_host": "10.41.240.101",
    }

_cfg = load_config()
RPI_HOST = _cfg["host"]
RPI_USER = _cfg["user"]
RPI_PATH = _cfg["path"]
LAPTOP_PATH = str(PROJECT_ROOT)
SSH_TARGET = f"{RPI_USER}@{RPI_HOST}"

# Get password
RPI_PASSWORD = os.environ.get("RPI_PASSWORD", "Haziqshah21")

# Sync paths
CODE_PATHS = [
    "rpi5/",
    "laptop/",
    "shared/",
    "tests/",
    "scripts/",
    "requirements.txt",
    ".env",
    "cortex",
    "cortex.py",
    "cortex.bat",
]

MODEL_PATHS = [
    "models/converted/",
    "models/hailo/",
]

DOWNLOAD_PATHS = [
    "logs/",
    "tts_recordings/",
    "memory_images/",
    "recordings/",
    "nav_cache.db",
    "local_cortex.db",
]

EXCLUDE = [
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".git/",
    "*.log",
    "*.db-shm",
    "*.db-wal",
    "venv/",
    ".venv/",
    "node_modules/",
]

# ─── Paramiko Detection ───────────────────────────────────────────
try:
    import paramiko
    PARAMIKO_OK = True
except ImportError:
    PARAMIKO_OK = False

# ─── Helpers ──────────────────────────────────────────────────────
def has_tool(name: str) -> bool:
    return shutil.which(name) is not None

def run_shell(cmd: str, check: bool = True, capture: bool = True) -> Tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result.returncode, result.stdout, result.stderr

def human_size(bytes_size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} TB"

def format_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"

def ssh_cmd(password: str = RPI_PASSWORD) -> str:
    if has_tool("sshpass"):
        return f"sshpass -p '{password}' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5"
    return "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5"

def scp_cmd(password: str = RPI_PASSWORD) -> str:
    if has_tool("sshpass"):
        return f"sshpass -p '{password}' scp -o StrictHostHostKeyChecking=no -o ConnectTimeout=5"
    return "scp -o StrictHostKeyChecking=no -o ConnectTimeout=5"

def print_banner():
    print(f"""
{_c('   ╔══════════════════════════════════════════════════════════╗', Colors.CYAN)}
{_c('   ║           CORTEX SYNC  —  RPi5 ↔ Laptop                 ║', Colors.CYAN)}
{_c('   ╚══════════════════════════════════════════════════════════╝', Colors.CYAN)}
   RPi5:   {_c(RPI_HOST, Colors.GREEN)}  |  Laptop: {_c(_cfg['laptop_host'], Colors.GREEN)}
""")

# ─── SSH Client ───────────────────────────────────────────────────
class RPiSSH:
    """SSH connection manager for RPi5."""
    
    def __init__(self):
        self.client: Optional[paramiko.SSHClient] = None
    
    def connect(self) -> bool:
        if not PARAMIKO_OK:
            print(_c("❌ paramiko not installed. Run: pip install paramiko", Colors.RED))
            return False
        
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.client.connect(
                RPI_HOST,
                username=RPI_USER,
                password=RPI_PASSWORD,
                timeout=10,
                banner_timeout=10,
            )
            return True
        except Exception as e:
            print(_c(f"❌ SSH connection failed: {e}", Colors.RED))
            return False
    
    def exec(self, cmd: str, verbose: bool = True) -> Tuple[int, str, str]:
        if not self.client:
            raise RuntimeError("Not connected")
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=300)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if verbose and out.strip():
            for line in out.strip().splitlines():
                print(f"   {_c('→', Colors.DIM)} {line}")
        return exit_code, out, err
    
    def sftp(self):
        if not self.client:
            raise RuntimeError("Not connected")
        return self.client.open_sftp()
    
    def close(self):
        if self.client:
            self.client.close()
            self.client = None
    
    def __enter__(self):
        if not self.connect():
            raise ConnectionError("Failed to connect to RPi5")
        return self
    
    def __exit__(self, *args):
        self.close()

# ─── Tarball Sync ─────────────────────────────────────────────────
def make_tarball(paths: List[str], exclude: List[str] = None) -> str:
    """Create a gzipped tarball of the given paths."""
    ts = int(time.time())
    tar_path = tempfile.mktemp(suffix=f"_cortex_{ts}.tar.gz")
    
    print(_c(f"\n📦 Creating tarball...", Colors.BOLD))
    
    with tarfile.open(tar_path, "w:gz") as tar:
        for rel_path in paths:
            full = PROJECT_ROOT / rel_path
            if full.exists():
                # Handle files vs directories
                if full.is_file():
                    tar.add(full, arcname=rel_path)
                else:
                    for item in full.rglob("*"):
                        # Skip excluded patterns
                        skip = False
                        for pat in (exclude or EXCLUDE):
                            if pat.endswith("/"):
                                if item.is_dir() and item.name == pat[:-1]:
                                    skip = True
                                    break
                            else:
                                if item.match(pat):
                                    skip = True
                                    break
                        if not skip and item.is_file():
                            arcname = str(item.relative_to(PROJECT_ROOT))
                            tar.add(item, arcname=arcname)
                print(f"   {_c('✓', Colors.GREEN)} {rel_path}")
            else:
                print(f"   {_c('○', Colors.DIM)} {rel_path} (not found, skipped)")
    
    size = os.path.getsize(tar_path)
    print(f"   {_c('→', Colors.CYAN)} Tarball: {human_size(size)}")
    return tar_path

def upload_and_extract(tar_path: str, ssh: RPiSSH) -> bool:
    """Upload tarball to RPi5 and extract it."""
    remote_tar = f"/tmp/{os.path.basename(tar_path)}"
    
    print(_c(f"\n🚀 Uploading to {SSH_TARGET}...", Colors.BOLD))
    sftp = ssh.sftp()
    
    # Upload with progress
    local_size = os.path.getsize(tar_path)
    uploaded = 0
    
    def progress_callback(sent, total):
        nonlocal uploaded
        uploaded = sent
        pct = (sent / total) * 100
        bar = "█" * int(pct // 5) + "░" * (20 - int(pct // 5))
        sys.stdout.write(f"\r   {_c('→', Colors.CYAN)} [{bar}] {pct:.0f}% ({human_size(sent)} / {human_size(total)})")
        sys.stdout.flush()
    
    sftp.put(tar_path, remote_tar, callback=progress_callback)
    sftp.close()
    print()  # newline after progress
    
                # Extract
    print(_c(f"\n📂 Extracting on RPi5...", Colors.BOLD))
    # Preserve .env separately so we don't overwrite with an old one
    cmd = (
        f"cd {RPI_PATH} && "
        f"cp .env /tmp/cortex_env_backup 2>/dev/null; true && "
        f"tar -xzf {remote_tar} && "
        f"mv /tmp/cortex_env_backup .env 2>/dev/null; true && "
        f"chmod +x cortex 2>/dev/null; true && "
        f"rm -f {remote_tar}"
    )
    exit_code, out, err = ssh.exec(cmd)
    
    if exit_code == 0:
        print(_c("   ✓ Extraction complete", Colors.GREEN))
        return True
    else:
        print(_c(f"   ✗ Extraction failed: {err}", Colors.RED))
        return False

# ─── Commands ─────────────────────────────────────────────────────
def cmd_check(args):
    """Test SSH connectivity without syncing."""
    print_banner()
    
    print(_c("🔍 Testing connectivity to RPi5...\n", Colors.BOLD))
    
    # Test 1: Ping
    print(f"   {_c('Ping', Colors.BOLD)} {RPI_HOST}...")
    try:
        run_shell(f"ping -c 1 -W 2 {RPI_HOST}", check=True, capture=True)
        print(f"   {_c('✅', Colors.GREEN)} Host is reachable")
    except subprocess.CalledProcessError:
        print(f"   {_c('❌', Colors.RED)} Host unreachable")
        return 1
    
    # Test 2: SSH
    print(f"\n   {_c('SSH', Colors.BOLD)} {SSH_TARGET}...")
    if PARAMIKO_OK:
        try:
            with RPiSSH() as ssh:
                exit_code, out, _ = ssh.exec("uname -a", verbose=False)
                print(f"   {_c('✅', Colors.GREEN)} SSH OK — {out.strip()[:60]}...")
                
                # Check disk space
                exit_code, out, _ = ssh.exec("df -h . | tail -1", verbose=False)
                parts = out.strip().split()
                if len(parts) >= 4:
                    print(f"   {_c('💾', Colors.CYAN)} Disk: {parts[3]} available on {RPI_PATH}")
                
                # Check Python
                exit_code, out, _ = ssh.exec("python3 --version", verbose=False)
                print(f"   {_c('🐍', Colors.CYAN)} Python: {out.strip()}")
                
                # Check if cortex is installed
                exit_code, out, _ = ssh.exec(f"ls {RPI_PATH}/cortex 2>/dev/null && echo yes || echo no", verbose=False)
                has_cortex = out.strip() == "yes"
                print(f"   {_c('🎮', Colors.CYAN)} CLI: {'installed' if has_cortex else 'not installed'}")
        except Exception as e:
            print(f"   {_c('❌', Colors.RED)} SSH failed: {e}")
            return 1
    else:
        print(f"   {_c('⚠️', Colors.YELLOW)} paramiko not installed — skipping SSH test")
    
    print(_c(f"\n✅ All connectivity checks passed!", Colors.GREEN))
    return 0

def cmd_status(args):
    """Show what would be synced (dry-run)."""
    print_banner()
    
    paths = CODE_PATHS.copy()
    if args.models:
        paths.extend(MODEL_PATHS)
    
    print(_c(f"\n📋 Sync Preview (dry-run)\n", Colors.BOLD))
    
    total_files = 0
    total_size = 0
    
    for rel_path in paths:
        full = PROJECT_ROOT / rel_path
        if not full.exists():
            print(f"   {_c('○', Colors.DIM)} {rel_path:<30s} (not found)")
            continue
        
        if full.is_file():
            size = full.stat().st_size
            total_files += 1
            total_size += size
            print(f"   {_c('✓', Colors.GREEN)} {rel_path:<30s} {human_size(size):>10s}")
        else:
            file_count = 0
            dir_size = 0
            for item in full.rglob("*"):
                if item.is_file():
                    skip = False
                    for pat in EXCLUDE:
                        if pat.endswith("/"):
                            if any(part == pat[:-1] for part in item.parts):
                                skip = True
                                break
                        else:
                            if item.match(pat):
                                skip = True
                                break
                    if not skip:
                        file_count += 1
                        dir_size += item.stat().st_size
            total_files += file_count
            total_size += dir_size
            print(f"   {_c('✓', Colors.GREEN)} {rel_path:<30s} {human_size(dir_size):>10s} ({file_count} files)")
    
    print(f"\n   {_c('─'*50, Colors.DIM)}")
    print(f"   {_c('Total:', Colors.BOLD)} {total_files} files, {human_size(total_size)}")
    
    if args.models:
        print(_c(f"\n⚠️ Including models/ will add ~500MB+ to the sync", Colors.YELLOW))
    
    return 0

def cmd_to(args):
    """Sync code TO RPi5."""
    print_banner()
    
    paths = CODE_PATHS.copy()
    if args.models:
        paths.extend(MODEL_PATHS)
    
    # Build tarball
    tar_path = make_tarball(paths, exclude=EXCLUDE)
    
    if args.dry_run:
        print(_c(f"\n🏁 Dry-run mode — skipping upload", Colors.YELLOW))
        os.remove(tar_path)
        return 0
    
    # Upload
    start = time.time()
    success = False
    
    if PARAMIKO_OK:
        try:
            with RPiSSH() as ssh:
                success = upload_and_extract(tar_path, ssh)
                
                # Verify
                if success:
                    print(_c(f"\n🔍 Verifying sync...", Colors.BOLD))
                    
                    # Check cortex.py
                    exit_code, out, _ = ssh.exec(f"ls -la {RPI_PATH}/cortex.py 2>/dev/null && echo OK || echo MISSING", verbose=False)
                    if "OK" in out:
                        print(_c("   ✅ cortex.py", Colors.GREEN))
                    else:
                        print(_c("   ⚠️ cortex.py missing", Colors.YELLOW))
                    
                    # Check cortex (Unix wrapper)
                    exit_code, out, _ = ssh.exec(f"test -x {RPI_PATH}/cortex && echo OK || echo MISSING", verbose=False)
                    if "OK" in out:
                        print(_c("   ✅ cortex (executable)", Colors.GREEN))
                    else:
                        print(_c("   ⚠️ cortex not found or not executable", Colors.YELLOW))
                        # Fix it
                        ssh.exec(f"chmod +x {RPI_PATH}/cortex 2>/dev/null; true", verbose=False)
        except Exception as e:
            print(_c(f"\n❌ Sync failed: {e}", Colors.RED))
            success = False
    else:
        print(_c("\n❌ paramiko required for sync. Install: pip install paramiko", Colors.RED))
    
    # Cleanup
    if os.path.exists(tar_path):
        os.remove(tar_path)
    
    elapsed = time.time() - start
    
    if success:
        print(_c(f"\n✅ Sync complete in {format_time(elapsed)}", Colors.GREEN))
        print(_c(f"   Run 'python -m scripts.sync install' to update dependencies", Colors.DIM))
        return 0
    else:
        print(_c(f"\n❌ Sync failed after {format_time(elapsed)}", Colors.RED))
        return 1

def cmd_from(args):
    """Sync data FROM RPi5 (logs, recordings)."""
    print_banner()
    
    paths = args.paths.split(",") if args.paths else DOWNLOAD_PATHS
    
    print(_c(f"\n📥 Downloading from {SSH_TARGET}\n", Colors.BOLD))
    
    if not PARAMIKO_OK:
        print(_c("❌ paramiko required. Install: pip install paramiko", Colors.RED))
        return 1
    
    start = time.time()
    total_bytes = 0
    total_files = 0
    
    try:
        with RPiSSH() as ssh:
            for rel_path in paths:
                rel = rel_path.strip().rstrip("/")
                print(f"   {_c('→', Colors.CYAN)} Downloading {rel}/...")
                
                # Tar remote directory
                remote_tar = f"/tmp/rpi_dl_{int(time.time())}.tar.gz"
                exit_code, _, _ = ssh.exec(
                    f"cd {RPI_PATH} && tar -czf {remote_tar} {rel} 2>/dev/null; true",
                    verbose=False,
                )
                
                # Download
                local_tar = tempfile.mktemp(suffix=".tar.gz")
                sftp = ssh.sftp()
                try:
                    sftp.get(remote_tar, local_tar)
                except Exception:
                    print(f"      {_c('○', Colors.DIM)} Not present on RPi5")
                    sftp.close()
                    continue
                sftp.close()
                
                # Extract
                try:
                    with tarfile.open(local_tar, "r:gz") as tar:
                        members = tar.getmembers()
                        tar.extractall(PROJECT_ROOT)
                        bytes_extracted = sum(m.size for m in members)
                        total_bytes += bytes_extracted
                        total_files += len([m for m in members if m.isfile()])
                        print(f"      {_c('✓', Colors.GREEN)} {len([m for m in members if m.isfile()])} files ({human_size(bytes_extracted)})")
                except Exception:
                    print(f"      {_c('✗', Colors.RED)} Extract failed")
                
                # Cleanup
                ssh.exec(f"rm -f {remote_tar}", verbose=False)
                if os.path.exists(local_tar):
                    os.remove(local_tar)
    
    except Exception as e:
        print(_c(f"\n❌ Download failed: {e}", Colors.RED))
        return 1
    
    elapsed = time.time() - start
    print(_c(f"\n✅ Downloaded {total_files} files ({human_size(total_bytes)}) in {format_time(elapsed)}", Colors.GREEN))
    return 0

def cmd_install(args):
    """Install/update dependencies on RPi5."""
    print_banner()
    
    print(_c(f"\n📦 Installing dependencies on {SSH_TARGET}\n", Colors.BOLD))
    
    if not PARAMIKO_OK:
        print(_c("❌ paramiko required. Install: pip install paramiko", Colors.RED))
        return 1
    
    start = time.time()
    
    try:
        with RPiSSH() as ssh:
            # Check current packages
            print(f"   {_c('Checking current environment...', Colors.DIM)}")
            exit_code, out, _ = ssh.exec("pip list | grep -iE 'supertonic|cartesia|ultralytics|onnxruntime' || true", verbose=False)
            
            # Install
            print(f"\n   {_c('Running pip install...', Colors.BOLD)}")
            exit_code, out, err = ssh.exec(
                f"cd {RPI_PATH} && pip install -r requirements.txt",
                verbose=False,
            )
            
            # Stream output
            print(out)
            if err.strip():
                print(_c(f"   stderr: {err.strip()[:200]}", Colors.YELLOW))
            
            if exit_code == 0:
                elapsed = time.time() - start
                print(_c(f"\n✅ Dependencies installed in {format_time(elapsed)}", Colors.GREEN))
                return 0
            else:
                print(_c(f"\n❌ pip install failed (exit code {exit_code})", Colors.RED))
                return 1
    
    except Exception as e:
        print(_c(f"\n❌ Install failed: {e}", Colors.RED))
        return 1

def cmd_full(args):
    """Sync TO RPi5 + install deps (one step)."""
    print_banner()
    
    ret = cmd_to(args)
    if ret == 0:
        print()
        ret = cmd_install(args)
    return ret

# ─── Main ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="cortex-sync",
        description="Sync Project Cortex between Laptop and RPi5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.sync check              # Verify connectivity
  python -m scripts.sync status             # Preview what would sync
  python -m scripts.sync to                 # Fast code-only sync
  python -m scripts.sync to --models        # Include models/ (~500MB)
  python -m scripts.sync from               # Download logs, recordings
  python -m scripts.sync from --paths logs  # Download only logs/
  python -m scripts.sync install            # Update deps on RPi5
  python -m scripts.sync full               # to + install in one step
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # check
    subparsers.add_parser("check", help="Test SSH connectivity")
    
    # status
    status_parser = subparsers.add_parser("status", help="Preview sync (dry-run)")
    status_parser.add_argument("--models", action="store_true", help="Include models/")
    
    # to
    to_parser = subparsers.add_parser("to", help="Sync code TO RPi5")
    to_parser.add_argument("--models", action="store_true", help="Include models/ (~500MB)")
    to_parser.add_argument("--dry-run", "-n", action="store_true", help="Show what would sync without uploading")
    to_parser.add_argument("--verify", "-v", action="store_true", help="Verify after sync")
    
    # from
    from_parser = subparsers.add_parser("from", help="Sync data FROM RPi5")
    from_parser.add_argument("--paths", type=str, help="Comma-separated paths to download (default: all)")
    
    # install
    subparsers.add_parser("install", help="Install deps on RPi5")
    
    # full
    full_parser = subparsers.add_parser("full", help="Sync TO + install (one step)")
    full_parser.add_argument("--models", action="store_true", help="Include models/")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    return COMMANDS[args.command](args)


# Module-level command registry (for external callers like cortex.py)
COMMANDS = {
    "check": cmd_check,
    "status": cmd_status,
    "to": cmd_to,
    "from": cmd_from,
    "install": cmd_install,
    "full": cmd_full,
}

# Alias for external access
commands = COMMANDS

if __name__ == "__main__":
    sys.exit(main())
