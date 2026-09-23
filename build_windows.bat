@echo off
REM setlocal: WIMI_BUILD_VARIANT must not outlive this script. Left set in
REM the console, a later bare `pyinstaller wimi.spec` would silently make a
REM test build (#144).
setlocal
REM ============================================
REM WIMI Windows Build Script
REM ============================================
echo.
echo ========================================
echo    WIMI Build Script for Windows
echo ========================================
echo.

REM Build variant (#144). No argument makes the RELEASE build, which refuses
REM --test-mode. "build_windows.bat test" makes the TEST build: identical
REM except for one runtime hook, and the only build that accepts --test-mode
REM (a Chromium remote debugger). Point WIMI_TEST_BINARY at a test build.
REM Never distribute one.
set "WIMI_BUILD_VARIANT=release"
set "DIST_NAME=WIMI"
if /i "%~1"=="test" (
    set "WIMI_BUILD_VARIANT=test"
    set "DIST_NAME=WIMI-test"
) else if not "%~1"=="" (
    echo [ERROR] Unknown argument "%~1".
    echo         No argument makes a release build; "test" makes a test build.
    exit /b 1
)
echo Variant: %WIMI_BUILD_VARIANT%  (output: dist\%DIST_NAME%\)
echo.

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv .venv
    echo Then: .venv\Scripts\activate
    echo Then: pip install -r requirements-prod.txt
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

REM Verify the environment matches requirements-prod.txt before building.
REM The Windows machine once drifted to PyQt6 6.10.1 while the pin said 6.9.1,
REM and the drifted Qt shipped inside dist\WIMI\_internal -- so the binary ran
REM a browser engine no test had ever exercised (#135, and #134/#136 for what
REM that broke). A pin nobody checks is a comment.
echo.
echo [1/5] Checking build environment...
python scripts\check_build_env.py
if errorlevel 1 (
    echo.
    echo [ERROR] Build environment does not match requirements-prod.txt.
    echo         Fix it with: pip install -r requirements-prod.txt
    echo         Do NOT ship a build made from a mismatched environment.
    pause
    exit /b 1
)

REM Clean the previous build of THIS variant only, so a test build does not
REM wipe a release build sitting beside it (or the other way round).
echo.
echo [2/5] Cleaning previous %WIMI_BUILD_VARIANT% build...
if exist "build\%WIMI_BUILD_VARIANT%" rmdir /s /q "build\%WIMI_BUILD_VARIANT%"
if exist "dist\%DIST_NAME%" rmdir /s /q "dist\%DIST_NAME%"

REM Run PyInstaller
echo.
echo [3/5] Building with PyInstaller...
echo      This may take several minutes...
echo.
pyinstaller wimi.spec --noconfirm --workpath "build\%WIMI_BUILD_VARIANT%"

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

REM Create app_data directory in dist
echo.
echo [4/5] Setting up distribution...
mkdir "dist\%DIST_NAME%\app_data" 2>nul
mkdir "dist\%DIST_NAME%\logs" 2>nul

REM Copy any additional files
echo.
echo [5/5] Finalizing...

echo.
echo ========================================
echo    BUILD COMPLETE!
echo ========================================
echo.
echo Output location: dist\%DIST_NAME%\
echo Executable: dist\%DIST_NAME%\WIMI.exe
echo.
echo To run: dist\%DIST_NAME%\WIMI.exe
echo.
if /i "%WIMI_BUILD_VARIANT%"=="test" (
    echo This is a TEST build: it accepts --test-mode, which starts a remote
    echo debugger. Use it for WIMI_TEST_BINARY. Do NOT distribute it.
) else (
    echo To distribute:
    echo   - Zip the entire dist\WIMI folder
    echo   - Or use an installer creator (NSIS, Inno Setup^)
)
echo.
pause
