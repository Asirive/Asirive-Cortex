@echo off
REM Simple sync using Windows built-in SCP (no rsync needed)
REM Works on Windows 10/11

echo.
echo ============================================
echo   ProjectCortex - SCP Sync to RPi5
echo   Using Windows built-in SCP
echo ============================================
echo.

set RPI_USER=cortex
set RPI_HOST=192.168.0.91
set RPI_DIR=~/ProjectCortex

echo Syncing to: %RPI_USER%@%RPI_HOST%
echo.

REM Check SCP exists
where scp >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: scp not found!
    echo SCP is available on Windows 10/11
    echo.
    pause
    exit /b 1
)

echo Syncing files (slower than rsync, no progress bar)...
echo.

REM Sync directories recursively
scp -r rpi5 %RPI_USER%@%RPI_HOST%:%RPI_DIR%/
scp -r supabase %RPI_USER%@%RPI_HOST%:%RPI_DIR%/

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================
    echo   Sync Complete!
    echo ============================================
    echo.
    echo Run on RPi5:
    echo   ssh %RPI_USER%@%RPI_HOST%
    echo   cd ~/ProjectCortex/rpi5
    echo   python main.py
    echo.
) else (
    echo.
    echo ERROR: Sync failed!
    echo.
)

pause
