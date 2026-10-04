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
REM
REM "relations" is a SECOND, ORTHOGONAL flag (#60): it bundles the
REM relation-extraction runtime (torch / transformers / gliner2), which WIMI
REM ships as its own artifact rather than in everyone's download. The two
REM compose, in any order and in either combination:
REM
REM   build_windows.bat                 -> dist\WIMI
REM   build_windows.bat test            -> dist\WIMI-test
REM   build_windows.bat relations       -> dist\WIMI-relations
REM   build_windows.bat test relations  -> dist\WIMI-test-relations
REM
REM A shift loop rather than a four-way compare, deliberately: the names
REM compose because the flags do, and a compare over the combinations is the
REM enum this design rejected (see wimi.spec's variant block).
set "WIMI_BUILD_VARIANT=release"
set "WIMI_BUILD_RELATIONS=0"
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="test" (
    set "WIMI_BUILD_VARIANT=test"
) else if /i "%~1"=="relations" (
    set "WIMI_BUILD_RELATIONS=1"
) else (
    echo [ERROR] Unknown argument "%~1".
    echo         No argument makes a release build without the
    echo         relation-extraction runtime. "test" makes a test build;
    echo         "relations" bundles that runtime. Both may be given.
    exit /b 1
)
shift
goto parse_args
:args_done

REM One line per flag, so the composition is diffable by eye against
REM build_macos.sh's three equivalent lines. WIMI_BUILD_RELATIONS is set
REM BEFORE check_build_env.py runs below: the gate reads it to decide whether
REM to verify requirements-relations.txt and that torch is the CPU build, so
REM that call needs no extra argument (#60).
set "DIST_NAME=WIMI"
if /i "%WIMI_BUILD_VARIANT%"=="test" set "DIST_NAME=%DIST_NAME%-test"
if "%WIMI_BUILD_RELATIONS%"=="1" set "DIST_NAME=%DIST_NAME%-relations"

REM PyInstaller's workpath needs the relations flag too, or a relations build
REM and a default build share build\release -- so each would wipe the other's
REM intermediate work, which is what the clean step below says it does NOT do.
REM The existing build\release and build\test paths are unchanged.
set "BUILD_TAG=%WIMI_BUILD_VARIANT%"
if "%WIMI_BUILD_RELATIONS%"=="1" set "BUILD_TAG=%BUILD_TAG%-relations"
echo Variant: %WIMI_BUILD_VARIANT%  relations: %WIMI_BUILD_RELATIONS%  (output: dist\%DIST_NAME%\)
echo.

REM Check if virtual environment exists.
REM NOTE: this only proves the file is THERE. It does not prove activation
REM works -- a renamed or moved venv leaves an activate script that exists,
REM runs, and silently leaves the system Python on PATH (#183). The real
REM check is check_build_env.py's check_interpreter, which compares
REM sys.prefix against this checkout's .venv and refuses on a mismatch.
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
echo [1/6] Checking build environment...
python scripts\check_build_env.py
if errorlevel 1 (
    echo.
    echo [ERROR] Build environment does not match requirements-prod.txt.
    echo         Fix it with: pip install -r requirements-prod.txt
    echo         Do NOT ship a build made from a mismatched environment.
    pause
    exit /b 1
)

REM Fetch the vendored whisper.cpp engine for speech-to-text (#59). The script
REM verifies the release asset's sha256, refuses an archive whose CPU-variant
REM set has drifted from its pin, and re-fetches an installation that is
REM incomplete, so running it every build is the check as well as the fetch.
REM
REM Both variants need it: a test build must be the release build plus one
REM runtime hook (#144), and a test build missing the engine would be evidence
REM about a binary nobody ships.
REM
REM This fetches the BINARY only. Model weights download on first run into
REM app_data\models\ (owner decision D2) and must never enter the installer.
echo.
echo [2/6] Fetching whisper.cpp engine...
python scripts\fetch_whisper.py --platform windows
if errorlevel 1 (
    echo.
    echo [ERROR] whisper.cpp fetch failed - cannot build without the engine.
    echo         wimi.spec refuses to build without vendor\whisper\windows\,
    echo         so this would have failed a minute later with less to go on.
    pause
    exit /b 1
)

REM Clean the previous build of THIS variant only, so a test build does not
REM wipe a release build sitting beside it (or the other way round).
echo.
echo [3/6] Cleaning previous %BUILD_TAG% build...
if exist "build\%BUILD_TAG%" rmdir /s /q "build\%BUILD_TAG%"
if exist "dist\%DIST_NAME%" rmdir /s /q "dist\%DIST_NAME%"

REM Run PyInstaller
echo.
echo [4/6] Building with PyInstaller...
echo      This may take several minutes...
echo.
pyinstaller wimi.spec --noconfirm --workpath "build\%BUILD_TAG%"

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

REM Create app_data directory in dist
echo.
echo [5/6] Setting up distribution...
mkdir "dist\%DIST_NAME%\app_data" 2>nul
mkdir "dist\%DIST_NAME%\logs" 2>nul

REM Licence texts and the corresponding-source notice (#272). GPL-3.0 s4
REM requires the licence to be conveyed WITH the program and s6 requires the
REM source to be obtainable from a stated place; Settings -> About names the
REM licences but naming is not conveying, and until this the bundle carried no
REM copyleft text at all. Identical line in build_macos.sh -- the logic is in
REM the Python so the two scripts cannot drift the way CLAUDE.md records the
REM two .spec files can.
python scripts\stage_license_files.py "dist\%DIST_NAME%"
if errorlevel 1 (
    echo ERROR: Failed to stage licence files.
    exit /b 1
)
echo.
echo [6/6] Finalizing...

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
) else if "%WIMI_BUILD_RELATIONS%"=="1" (
    REM Asset naming follows the existing WIMI_win_v0.1.0-beta.zip shape (#60).
    REM Provisional but committed: the owner has approved this shape and will
    REM write the release-page copy that explains what the larger download buys.
    echo To distribute:
    echo   - Zip the entire dist\%DIST_NAME% folder as
    echo     WIMI_win_relations_v^<version^>.zip
    echo.
    echo This is the RELATIONS artifact: it carries the relation-extraction
    echo runtime and is roughly twice the size of the default one. It is a
    echo SEPARATE download, not a replacement -- publish both, and do not let
    echo this one take the default artifact's name.
) else (
    echo To distribute:
    echo   - Zip the entire dist\WIMI folder as WIMI_win_v^<version^>.zip
    echo   - Or use an installer creator (NSIS, Inno Setup^)
)
echo.
pause
