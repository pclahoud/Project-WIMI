#!/bin/bash
# ============================================
# WIMI macOS Build Script
# ============================================

echo ""
echo "========================================"
echo "   WIMI Build Script for macOS"
echo "========================================"
echo ""

# Build variant (#144). No argument makes the RELEASE build, which refuses
# --test-mode. "./build_macos.sh test" makes the TEST build: identical except
# for one runtime hook, and the only build that accepts --test-mode (a
# Chromium remote debugger). Point WIMI_TEST_BINARY at a test build. Never
# distribute one.
VARIANT="release"
DIST_NAME="WIMI"
case "${1:-}" in
    "") ;;
    test) VARIANT="test"; DIST_NAME="WIMI-test" ;;
    *)
        echo "[ERROR] Unknown argument '$1'."
        echo "        No argument makes a release build; 'test' makes a test build."
        exit 1
        ;;
esac
export WIMI_BUILD_VARIANT="$VARIANT"
echo "Variant: $VARIANT  (output: dist/$DIST_NAME/)"
echo ""

# Check if virtual environment exists
if [ ! -f ".venv/bin/activate" ]; then
    echo "[ERROR] Virtual environment not found!"
    echo "Please run: python3 -m venv .venv"
    echo "Then: source .venv/bin/activate"
    echo "Then: pip install -r requirements-prod.txt"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Check if PyInstaller is installed
if ! pip show pyinstaller > /dev/null 2>&1; then
    echo "[INFO] Installing PyInstaller..."
    pip install pyinstaller
fi

# Verify the environment matches requirements-prod.txt before building.
# The Windows machine once drifted to PyQt6 6.10.1 while the pin said 6.9.1,
# and the drifted Qt shipped inside the bundle -- so the binary ran a browser
# engine no test had ever exercised (#135, and #134/#136 for what that broke).
# A pin nobody checks is a comment.
echo ""
echo "[1/6] Checking build environment..."
if ! python scripts/check_build_env.py; then
    echo ""
    echo "[ERROR] Build environment does not match requirements-prod.txt."
    echo "        Fix it with: pip install -r requirements-prod.txt"
    echo "        Do NOT ship a build made from a mismatched environment."
    exit 1
fi

# Clean the previous build of THIS variant only, so a test build does not
# wipe a release build sitting beside it (or the other way round).
echo ""
echo "[2/6] Cleaning previous $VARIANT build..."
rm -rf "build/$VARIANT" "dist/$DIST_NAME" "dist/$DIST_NAME.app"

# Run PyInstaller
echo ""
echo "[3/6] Building with PyInstaller..."
echo "      This may take several minutes..."
echo ""
pyinstaller wimi_macos.spec --noconfirm --workpath "build/$VARIANT"

if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] Build failed!"
    exit 1
fi

# PyInstaller produces:
#   dist/WIMI/      <- COLLECT output (binary + _internal/, redundant once .app exists)
#   dist/WIMI.app   <- BUNDLE output (the actual app)
# We want dist/WIMI/WIMI.app with app_data/ and logs/ as siblings, so
# wipe the redundant COLLECT folder, recreate it as a container, and
# move the .app inside.
echo ""
echo "[4/6] Setting up distribution..."
rm -rf "dist/$DIST_NAME"
mkdir -p "dist/$DIST_NAME"
mv "dist/$DIST_NAME.app" "dist/$DIST_NAME/WIMI.app"
mkdir -p "dist/$DIST_NAME/app_data"
mkdir -p "dist/$DIST_NAME/logs"

# Generate First Launch.command for recipients to bypass Gatekeeper without terminal
echo ""
echo "[5/6] Generating First Launch.command..."
cat > "dist/$DIST_NAME/First Launch.command" <<'LAUNCHER'
#!/bin/bash
cd "$(dirname "$0")"
echo "Preparing WIMI for first launch..."
xattr -cr WIMI.app
echo "Done. Launching WIMI."
open WIMI.app
LAUNCHER
chmod +x "dist/$DIST_NAME/First Launch.command"

# Finalize
echo ""
echo "[6/6] Finalizing..."

echo ""
echo "========================================"
echo "   BUILD COMPLETE!"
echo "========================================"
echo ""
echo "Output location: dist/$DIST_NAME/"
echo "Application:     dist/$DIST_NAME/WIMI.app"
echo "First-run helper: dist/$DIST_NAME/First Launch.command"
echo ""
echo "To run locally (your machine):"
echo "  open dist/$DIST_NAME/WIMI.app"
echo ""
if [ "$VARIANT" = "test" ]; then
    echo "This is a TEST build: it accepts --test-mode, which starts a remote"
    echo "debugger. Use it for WIMI_TEST_BINARY. Do NOT distribute it."
    echo ""
    exit 0
fi
echo "To distribute:"
echo "  cd dist && zip -r WIMI-macOS.zip WIMI"
echo "  Recipients unzip, then right-click 'First Launch.command' -> Open"
echo "  (one-time step; afterwards WIMI.app launches normally)"
echo ""
