@echo off
REM Sync using Git Bash's rsync (full path)
REM Works from regular CMD/PowerShell

echo.
echo ============================================
echo   ProjectCortex - Sync to RPi5
echo   Using Git Bash rsync
echo ============================================
echo.

REM Find Git installation
where git >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Git not found in PATH
    echo Please install Git for Windows: https://git-scm.com/download/win
    pause
    exit /b 1
)

REM Get Git installation path
for /f "delims=" %%i in ('where git') do set GIT_PATH=%%i
for /f "delims=" %%i in ("%GIT_PATH%") do set GIT_DIR=%%~dpi
set GIT_DIR=%GIT_DIR:~0,-5%

REM Rsync is in Git/usr/bin
set RSYNC="%GIT_DIR%usr\bin\rsync.exe"

echo Git found at: %GIT_DIR%
echo Rsync path: %RSYNC%
echo.

REM Test rsync
%RSYNC% --version >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: rsync.exe not found at %RSYNC%
    pause
    exit /b 1
)

echo Syncing files to RPi5 (192.168.0.91)...
echo.

%RSYNC% -avz --progress ^
  --exclude=__pycache__/ ^
  --exclude=*.pyc ^
  --exclude=.git/ ^
  --exclude=*.db ^
  --exclude=laptop/ ^
  --exclude=tests/ ^
  --exclude=docs/ ^
  --exclude=examples/ ^
  --exclude=*.mp4 ^
  --exclude=*.mov ^
  ./ pi@192.168.0.91:~/ProjectCortex/

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================
    echo   Sync Complete!
    echo ============================================
    echo.
    echo Run on RPi5:
    echo   ssh pi@192.168.0.91
    echo   cd ~/ProjectCortex/rpi5
    echo   python main.py
    echo.
) else (
    echo.
    echo ERROR: Sync failed!
    echo.
)

pause
