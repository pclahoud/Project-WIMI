@echo off
echo.
echo ========================================
echo   WIMI - What I Missed It
echo   Starting Application...
echo ========================================
echo.

cd /d "%~dp0"
python run_wimi.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo   Application exited with an error
    echo ========================================
    pause
)
