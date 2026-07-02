@echo off
REM Batch file to run the Error Logger Demo on Windows

echo ========================================
echo Student App - Error Logger Demo
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.8 or higher
    pause
    exit /b 1
)

REM Show Python version
echo Python version:
python --version
echo.

REM Check if virtual environment exists
if exist "venv\" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo No virtual environment found.
    echo Consider creating one with: python -m venv venv
    echo.
)

REM Install requirements if needed
echo Checking dependencies...
python -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo Failed to install requirements
        pause
        exit /b 1
    )
)

REM Run the demo
echo.
echo Starting Error Logger Demo...
echo ----------------------------------------
python run_error_logger_demo.py

echo.
echo ========================================
echo Demo finished
echo ========================================
pause
