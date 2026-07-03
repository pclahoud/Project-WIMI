# Building WIMI for macOS

## Prerequisites

- Python 3.10 or later
- A virtual environment with project dependencies installed
- macOS 11 (Big Sur) or later recommended

## Quick Build

```bash
# From the project root directory
chmod +x build_macos.sh
./build_macos.sh
```

## Manual Build Steps

```bash
# 1. Create and activate virtual environment
# (python.org universal2 Python recommended; Homebrew/uv Pythons are
# single-arch — see "Universal Binary" below)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-prod.txt   # includes PyInstaller

# 2. Build
pyinstaller wimi_macos.spec --noconfirm

# 3. Create data directories next to the .app
mkdir -p dist/WIMI/app_data
mkdir -p dist/WIMI/logs
```

## Output Structure

```
dist/WIMI/
├── WIMI.app          # The application bundle
├── app_data/         # User data (databases, media)
└── logs/             # Application logs
```

## Running the App

Since the app is unsigned, macOS Gatekeeper will block it on first launch. To bypass:

```bash
# Clear quarantine attribute (required once after build or download)
xattr -cr dist/WIMI/WIMI.app

# Launch
open dist/WIMI/WIMI.app
```

Alternatively, right-click the app and select "Open" from the context menu, then click "Open" in the dialog.

## Distribution

1. Zip the entire `dist/WIMI/` folder
2. Share the zip file
3. Recipients should extract and run:
   ```bash
   xattr -cr WIMI.app
   open WIMI.app
   ```

## Universal Binary

The build produces a universal binary (`universal2`) that runs natively on both:
- **Apple Silicon** (M1/M2/M3/M4)
- **Intel** (x86_64)

This increases the app size but ensures compatibility across all Mac hardware.

## Troubleshooting

### Blank/White Screen on Launch
PyQt6 WebEngine (Chromium) requires JIT entitlements on macOS. The build includes `entitlements.plist` which grants these permissions. If you see a blank screen:
- Verify `entitlements.plist` exists in the project root
- Rebuild with `./build_macos.sh`

### App Won't Open (Gatekeeper)
Run `xattr -cr WIMI.app` to clear the quarantine flag.

### Large App Size
The universal binary is roughly 2x the size of an architecture-specific build. To build for only your current architecture, edit `wimi_macos.spec` and change `target_arch='universal2'` to `target_arch=None`.

### Database/Logs Not Created
The `app_data/` and `logs/` directories must be next to `WIMI.app`, not inside it. The build script creates these automatically. If distributing, ensure the entire `dist/WIMI/` folder is included.
