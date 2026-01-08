#!/bin/bash
# sync_to_rpi.sh - Sync ProjectCortex files to RPi5
# Usage: ./sync_to_rpi.sh

# =============================================================================
# CONFIGURATION - Update these values
# =============================================================================

# RPi5 IP address (find with: ping raspberrypi.local or hostname -I on RPi5)
RPI_USER="pi"
RPI_HOST="192.168.1.xxx"  # CHANGE THIS to your RPi5 IP
RPI_PORT="22"

# Directories
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # Current directory
REMOTE_DIR="~/ProjectCortex"  # Where to sync on RPi5

# =============================================================================
# RSYNC OPTIONS
# =============================================================================

# -a: archive mode (preserve permissions, timestamps, etc.)
# -v: verbose (show what's being transferred)
# -z: compress during transfer (faster on slow networks)
# --progress: show progress bar
# --delete: delete files on remote that don't exist locally (USE WITH CAUTION!)
# --exclude: skip these files/directories

RSYNC_OPTIONS="-avz --progress"

# Files/directories to exclude from sync
EXCLUDES=(
    "--exclude=__pycache__/"
    "--exclude=*.pyc"
    "--exclude=.git/"
    "--exclude=*.db"
    "--exclude=.DS_Store"
    "--exclude=*.mp4"
    "--exclude=*.mov"
    "--exclude=tests/"
    "--exclude=docs/"
    "--exclude=examples/"
    "--exclude=laptop/"  # Skip laptop dashboard (runs on laptop only)
)

# =============================================================================
# SYNC DIRECTORIES
# =============================================================================

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     🔄 ProjectCortex → RPi5 File Sync                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "📤 Local:  $LOCAL_DIR"
echo "📥 Remote: $RPI_USER@$RPI_HOST:$REMOTE_DIR"
echo ""

# Test connection first
echo "🔌 Testing connection to RPi5..."
if ! ssh -p "$RPI_PORT" "$RPI_USER@$RPI_HOST" "echo '✅ Connection successful'" 2>/dev/null; then
    echo "❌ Failed to connect to $RPI_USER@$RPI_HOST:$RPI_PORT"
    echo ""
    echo "Troubleshooting:"
    echo "1. Check RPi5 IP address: ping raspberrypi.local"
    echo "2. Check SSH is enabled on RPi5: sudo systemctl status ssh"
    echo "3. Check you can SSH manually: ssh $RPI_USER@$RPI_HOST"
    exit 1
fi

echo ""
echo "📦 Starting sync..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Build rsync command
RSYNC_CMD="rsync $RSYNC_OPTIONS ${EXCLUDE[*]} $LOCAL_DIR/ $RPI_USER@$RPI_HOST:$REMOTE_DIR/"

# Execute rsync
eval $RSYNC_CMD

# Check result
if [ $? -eq 0 ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ Sync complete!"
    echo ""
    echo "🚀 Next steps on RPi5:"
    echo "   ssh $RPI_USER@$RPI_HOST"
    echo "   cd ~/ProjectCortex/rpi5"
    echo "   python main.py"
else
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "❌ Sync failed! Check the error messages above."
    exit 1
fi
