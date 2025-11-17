# Project-Cortex v2.0 - Windows PowerShell Launcher
# Ensures proper UTF-8 encoding for emoji display
# Author: Haziq (@IRSPlays)
# Date: November 17, 2025

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "🚀 Project-Cortex v2.0 - Assistive AI Wearable" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Set console to UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# Change to script directory
Set-Location $PSScriptRoot

Write-Host "📁 Working Directory: $PWD" -ForegroundColor Yellow
Write-Host "🐍 Python Version:" -ForegroundColor Yellow
python --version
Write-Host ""

Write-Host "🔧 Configuration:" -ForegroundColor Cyan
Write-Host "   - Model: yolo11x.pt (CPU inference)" -ForegroundColor White
Write-Host "   - Device: CPU (Raspberry Pi compatible)" -ForegroundColor White
Write-Host "   - Camera: USB Webcam" -ForegroundColor White
Write-Host ""

Write-Host "▶️  Starting GUI..." -ForegroundColor Green
Write-Host ""

# Run the application
python src/cortex_gui.py

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "✅ Application closed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
