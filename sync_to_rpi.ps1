# sync_to_rpi.ps1 - Sync ProjectCortex files to RPi5 (Windows PowerShell)
# Usage: .\sync_to_rpi.ps1

# =============================================================================
# CONFIGURATION - Update these values
# =============================================================================

# RPi5 connection details
$RPI_USER = "pi"
$RPI_HOST = "192.168.1.xxx"  # CHANGE THIS to your RPi5 IP address
$RPI_PORT = "22"

# Directories
$LOCAL_DIR = "C:\Users\Haziq\Documents\ProjectCortex"
$REMOTE_DIR = "~/ProjectCortex"

# =============================================================================
# FIND RPI5 IP ADDRESS (if not set)
# =============================================================================

if ($RPI_HOST -eq "192.168.1.xxx") {
    Write-Host "🔍 Finding RPi5 IP address..." -ForegroundColor Yellow
    Write-Host "Try these commands on your RPi5:" -ForegroundColor Cyan
    Write-Host "  hostname -I" -ForegroundColor White
    Write-Host "  ip addr show | grep 'inet '" -ForegroundColor White
    Write-Host ""
    Write-Host "Or on your laptop:" -ForegroundColor Cyan
    Write-Host "  ping raspberrypi.local" -ForegroundColor White
    Write-Host ""
    Read-Host "Press Enter after updating RPI_HOST in this script"
    exit
}

# =============================================================================
# CHECK PREREQUISITES
# =============================================================================

Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     🔄 ProjectCortex → RPi5 File Sync (Windows)              ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Check if rsync is available
$HAS_RSYNC = Get-Command rsync -ErrorAction SilentlyContinue

if (-not $HAS_RSYNC) {
    Write-Host "⚠️  rsync not found!" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Install rsync on Windows:" -ForegroundColor Cyan
    Write-Host "Option 1: Install Git for Windows (includes rsync)" -ForegroundColor White
    Write-Host "  Download: https://git-scm.com/download/win" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Option 2: Use WSL (Windows Subsystem for Linux)" -ForegroundColor White
    Write-Host "  wsl --install -d Ubuntu" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Option 3: Use scp (comes with Windows 10+)" -ForegroundColor White
    Write-Host "  See: sync_to_rpi_scp.ps1" -ForegroundColor Gray
    Write-Host ""
    exit 1
}

# =============================================================================
# TEST CONNECTION
# =============================================================================

Write-Host "🔌 Testing connection to RPi5..." -ForegroundColor Cyan

$Result = ssh -p $RPI_PORT "$RPI_USER@$RPI_HOST" "echo 'Connection successful'" 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to connect to $RPI_USER@$RPI_HOST`:$RPI_PORT" -ForegroundColor Red
    Write-Host ""
    Write-Host "Troubleshooting:" -ForegroundColor Yellow
    Write-Host "1. Find RPi5 IP: ping raspberrypi.local" -ForegroundColor White
    Write-Host "2. Check SSH on RPi5: sudo systemctl status ssh" -ForegroundColor White
    Write-Host "3. Test SSH manually: ssh $RPI_USER@$RPI_HOST" -ForegroundColor White
    exit 1
}

Write-Host "✅ Connection successful!" -ForegroundColor Green
Write-Host ""

# =============================================================================
# SYNC FILES
# =============================================================================

Write-Host "📦 Starting sync..." -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray

# Build exclude patterns
$EXCLUDES = @(
    "--exclude=__pycache__/",
    "--exclude=*.pyc",
    "--exclude=.git/",
    "--exclude=*.db",
    "--exclude=.DS_Store",
    "--exclude=*.mp4",
    "--exclude=*.mov",
    "--exclude=tests/",
    "--exclude=docs/",
    "--exclude=examples/",
    "--exclude=laptop/"
)

# Build rsync command
$RSYNC_CMD = "rsync -avz --progress $EXCLUDES $LOCAL_DIR/ ${RPI_USER}@${RPI_HOST}:${REMOTE_DIR}/"

# Execute
Invoke-Expression $RSYNC_CMD

# Check result
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
    Write-Host "✅ Sync complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "🚀 Next steps on RPi5:" -ForegroundColor Cyan
    Write-Host "   ssh $RPI_USER@$RPI_HOST" -ForegroundColor White
    Write-Host "   cd ~/ProjectCortex/rpi5" -ForegroundColor White
    Write-Host "   python main.py" -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
    Write-Host "❌ Sync failed! Check error messages above." -ForegroundColor Red
    exit 1
}
