@echo off
setlocal
cd /d "%~dp0"

echo Installing / updating Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo pip install failed. Check that Python is installed and on PATH.
    pause
    exit /b 1
)

echo.
echo Starting OBS Controller...
python -m obs_controller_app.main
if errorlevel 1 pause
