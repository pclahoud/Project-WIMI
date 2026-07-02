@echo off
REM ============================================
REM WIMI Windows Build Script
REM ============================================
echo.
echo ========================================
echo    WIMI Build Script for Windows
echo ========================================
echo.

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv .venv
    echo Then: .venv\Scripts\activate
    echo Then: pip install -r requirements.txt
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Check if PyInstaller is installed
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    pip install pyinstaller
)

REM Clean previous builds
echo.
echo [1/4] Cleaning previous builds...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

REM Run PyInstaller
echo.
echo [2/4] Building with PyInstaller...
echo      This may take several minutes...
echo.
pyinstaller wimi.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

REM Create app_data directory in dist
echo.
echo [3/4] Setting up distribution...
mkdir "dist\WIMI\app_data" 2>nul
mkdir "dist\WIMI\logs" 2>nul

REM Copy any additional files
echo.
echo [4/4] Finalizing...

echo.
echo ========================================
echo    BUILD COMPLETE!
echo ========================================
echo.
echo Output location: dist\WIMI\
echo Executable: dist\WIMI\WIMI.exe
echo.
echo To run: dist\WIMI\WIMI.exe
echo.
echo To distribute:
echo   - Zip the entire dist\WIMI folder
echo   - Or use an installer creator (NSIS, Inno Setup)
echo.
pause
