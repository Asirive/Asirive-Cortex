@echo off
REM Quick sync to RPi5 (192.168.0.91)
REM Use this for fast iteration during development
REM Syncs: rpi5/, models/, TTS Model/, requirements.txt

echo.
echo ============================================
echo   ProjectCortex - Quick Sync to RPi5
echo ============================================
echo.

REM Configuration
set RPI_USER=cortex
set RPI_HOST=192.168.0.92
set RPI_DIR=~/ProjectCortex

echo Syncing to: %RPI_USER%@%RPI_HOST%
echo.

REM Find Git Bash's rsync (not in regular PATH)
set RSYNC_EXE=
for %%f in (rsync.exe) do set RSYNC_EXE=%%~$PATH:f

REM If not in PATH, try Git installation paths
if "%RSYNC_EXE%"=="" (
    if exist "C:\Program Files\Git\usr\bin\rsync.exe" (
        set "RSYNC_EXE=C:\Program Files\Git\usr\bin\rsync.exe"
    ) else if exist "C:\Program Files (x86)\Git\usr\bin\rsync.exe" (
        set "RSYNC_EXE=C:\Program Files (x86)\Git\usr\bin\rsync.exe"
    ) else if exist "%USERPROFILE%\AppData\Local\Programs\Git\usr\bin\rsync.exe" (
        set "RSYNC_EXE=%USERPROFILE%\AppData\Local\Programs\Git\usr\bin\rsync.exe"
    )
)

if "%RSYNC_EXE%"=="" (
    echo ERROR: rsync not found!
    echo.
    echo Git Bash is installed but rsync cannot be located.
    echo Please use Git Bash directly, or install Git for Windows from:
    echo https://git-scm.com/download/win
    echo.
    pause
    exit /b 1
)

echo Using rsync: %RSYNC_EXE%
echo.

REM Create a temporary include/exclude file for rsync
echo Syncing RPi5-specific folders...
echo.

REM Sync to RPi5
"%RSYNC_EXE%" -avz --progress ^
  --include="rpi5/" ^
  --include="rpi5/**" ^
  --include="models/" ^
  --include="models/**" ^
  --include="models/*.ncnn_model/" ^
  --include="models/*.onnx" ^
  --include="models/*.pt" ^
  --include="TTS Model/" ^
  --include="TTS Model/**" ^
  --include="requirements.txt" ^
  --exclude="__pycache__/" ^
  --exclude="*.pyc" ^
  --exclude=".git/" ^
  --exclude=".git/**" ^
  --exclude="*.db" ^
  --exclude="*.db-journal" ^
  --exclude="laptop/" ^
  --exclude="laptop/**" ^
  --exclude="tests/" ^
  --exclude="tests/**" ^
  --exclude="docs/" ^
  --exclude="docs/**" ^
  --exclude="examples/" ^
  --exclude="examples/**" ^
  --exclude="*.mp4" ^
  --exclude="*.mov" ^
  --exclude="*.zip" ^
  --exclude="*.log" ^
  --exclude="logs/**" ^
  --exclude="debug/**" ^
  --exclude="recordings/**" ^
  --exclude="supabase/**" ^
  --exclude="sync*.bat" ^
  --exclude="sync*.ps1" ^
  --exclude="sync*.sh" ^
  --include="*.md" ^
  . %RPI_USER%@%RPI_HOST%:%RPI_DIR%/

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================
    echo   Sync Complete!
    echo ============================================
    echo.
    echo Synced folders:
    echo   - rpi5/          (main application code)
    echo   - models/        (YOLO detection models)
    echo   - TTS Model/     (Kokoro TTS voice model)
    echo   - requirements.txt
    echo.
    echo Run on RPi5:
    echo   ssh %RPI_USER%@%RPI_HOST%
    echo   cd ~/ProjectCortex
    echo   pip install -r requirements.txt
    echo   cd rpi5
    echo   python main.py
    echo.
) else (
    echo.
    echo ERROR: Sync failed!
    echo.
)

pause
