@echo off
REM Quick sync to RPi5 (192.168.0.92)
REM Use this for fast iteration during development
REM Syncs: rpi5/, models/, TTS Model/, requirements.txt
REM Uses Git Bash to ensure SSH keys are properly loaded

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

REM Find Git Bash installation
set GIT_BASH=
set GIT_USR_BIN=

if exist "C:\Program Files\Git\bin\bash.exe" (
    set "GIT_BASH=C:\Program Files\Git\bin\bash.exe"
    set "GIT_USR_BIN=C:\Program Files\Git\usr\bin"
) else if exist "C:\Program Files (x86)\Git\bin\bash.exe" (
    set "GIT_BASH=C:\Program Files (x86)\Git\bin\bash.exe"
    set "GIT_USR_BIN=C:\Program Files (x86)\Git\usr\bin"
) else if exist "%USERPROFILE%\AppData\Local\Programs\Git\bin\bash.exe" (
    set "GIT_BASH=%USERPROFILE%\AppData\Local\Programs\Git\bin\bash.exe"
    set "GIT_USR_BIN=%USERPROFILE%\AppData\Local\Programs\Git\usr\bin"
)

if "%GIT_BASH%"=="" (
    echo ERROR: Git Bash not found!
    echo.
    echo Please install Git for Windows from:
    echo https://git-scm.com/download/win
    echo.
    pause
    exit /b 1
)

echo Using Git Bash: %GIT_BASH%
echo.

REM Get current directory in Unix format for rsync
cd /d "%~dp0"
for /f "delims=" %%i in ('powershell -Command "(Get-Location).Path -replace '\\\\','/'"') do set "CUR_DIR_UNIX=%%i"
if "%CUR_DIR_UNIX:~-1%"=="/" set CUR_DIR_UNIX=%CUR_DIR_UNIX:~0,-1%

REM Create temporary rsync filter file
set FILTER_FILE=%TEMP%\rsync_filter_%RANDOM%.txt
echo # Rsync filter rules > "%FILTER_FILE%"
echo # Include directories >> "%FILTER_FILE%"
echo + /rpi5/ >> "%FILTER_FILE%"
echo + /rpi5/** >> "%FILTER_FILE%"
echo + /models/ >> "%FILTER_FILE%"
echo + /models/** >> "%FILTER_FILE%"
echo + /models/**/*.ncnn_model/ >> "%FILTER_FILE%"
echo + /models/*.onnx >> "%FILTER_FILE%"
echo + /models/*.pt >> "%FILTER_FILE%"
echo + /shared/ >> "%FILTER_FILE%"
echo + /shared/** >> "%FILTER_FILE%"
echo + /TTS\ Model/ >> "%FILTER_FILE%"
echo + /TTS\ Model/** >> "%FILTER_FILE%"
echo + /requirements.txt >> "%FILTER_FILE%"
echo + /**.md >> "%FILTER_FILE%"
echo # Exclude everything else >> "%FILTER_FILE%"
echo - * >> "%FILTER_FILE%"
echo # Exclude specific patterns >> "%FILTER_FILE%"
echo - /**/__pycache__/** >> "%FILTER_FILE%"
echo - /**.pyc >> "%FILTER_FILE%"
echo - /**.pyo >> "%FILTER_FILE%"
echo - /**.db >> "%FILTER_FILE%"
echo - /**.db-journal >> "%FILTER_FILE%"
echo - /**.log >> "%FILTER_FILE%"
echo - /**/logs/** >> "%FILTER_FILE%"
echo - /**/debug/** >> "%FILTER_FILE%"
echo - /**/recordings/** >> "%FILTER_FILE%"

echo Syncing via Git Bash (SSH keys will be loaded)...
echo.

REM Run rsync through Git Bash with SSH proper configuration
"%GIT_BASH%" -c "export PATH='%GIT_USR_BIN%:\$PATH' && rsync -avz --progress --delete --filter='merge %FILTER_FILE%' '%CUR_DIR_UNIX%/' '%RPI_USER@%RPI_HOST:%RPI_DIR%/'"

set RSYNC_RESULT=%ERRORLEVEL%

REM Clean up filter file
del "%FILTER_FILE%" 2>nul

if %RSYNC_RESULT% EQU 0 (
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
    echo ERROR: Sync failed (exit code: %RSYNC_RESULT%)!
    echo.
    echo Troubleshooting:
    echo   1. Verify RPi5 is reachable: ping %RPI_HOST%
    echo   2. Check SSH keys: ssh %RPI_USER%@%RPI_HOST% echo 'test'
    echo   3. Verify Git Bash paths above
    echo.
)

pause
