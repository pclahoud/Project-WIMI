#!/bin/bash
# ============================================
# WIMI macOS Build Script
# ============================================

echo ""
echo "========================================"
echo "   WIMI Build Script for macOS"
echo "========================================"
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

# Clean previous builds
echo ""
echo "[1/5] Cleaning previous builds..."
rm -rf build dist

# Run PyInstaller
echo ""
echo "[2/5] Building with PyInstaller..."
echo "      This may take several minutes..."
echo ""
pyinstaller wimi_macos.spec --noconfirm

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
echo "[3/4] Setting up distribution..."
rm -rf "dist/WIMI"
mkdir -p "dist/WIMI"
mv "dist/WIMI.app" "dist/WIMI/WIMI.app"
mkdir -p "dist/WIMI/app_data"
mkdir -p "dist/WIMI/logs"

# Generate First Launch.command for recipients to bypass Gatekeeper without terminal
echo ""
echo "[4/5] Generating First Launch.command..."
cat > "dist/WIMI/First Launch.command" <<'LAUNCHER'
#!/bin/bash
cd "$(dirname "$0")"
echo "Preparing WIMI for first launch..."
xattr -cr WIMI.app
echo "Done. Launching WIMI."
open WIMI.app
LAUNCHER
chmod +x "dist/WIMI/First Launch.command"

# Finalize
echo ""
echo "[5/5] Finalizing..."

echo ""
echo "========================================"
echo "   BUILD COMPLETE!"
echo "========================================"
echo ""
echo "Output location: dist/WIMI/"
echo "Application:     dist/WIMI/WIMI.app"
echo "First-run helper: dist/WIMI/First Launch.command"
echo ""
echo "To run locally (your machine):"
echo "  open dist/WIMI/WIMI.app"
echo ""
echo "To distribute:"
echo "  cd dist && zip -r WIMI-macOS.zip WIMI"
echo "  Recipients unzip, then right-click 'First Launch.command' -> Open"
echo "  (one-time step; afterwards WIMI.app launches normally)"
echo ""
