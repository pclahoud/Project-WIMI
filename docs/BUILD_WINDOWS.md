# WIMI Windows Build Guide

**Last Updated:** January 3, 2026

---

## Quick Start

```powershell
# From project root
.\build_windows.bat
```

Output will be in `dist\WIMI\WIMI.exe`

---

## Prerequisites

1. **Python 3.11+** installed and in PATH
2. **Virtual environment** set up with all dependencies
3. **PyInstaller** (auto-installed by build script)

---

## Build Options

### Option 1: Automated Build (Recommended)

```powershell
cd C:\path\to\Project_WIMI_Dev
.\build_windows.bat
```

### Option 2: Manual Build

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install PyInstaller if needed
pip install pyinstaller

# Build
pyinstaller wimi.spec --noconfirm
```

### Option 3: One-File Build (Slower startup, simpler distribution)

```powershell
pyinstaller --onefile --windowed --name WIMI ^
    --add-data "src/web/html;web/html" ^
    --add-data "src/web/css;web/css" ^
    --add-data "src/web/js;web/js" ^
    --add-data "src/database/schema;database/schema" ^
    --hidden-import PyQt6.QtWebEngineWidgets ^
    --hidden-import PyQt6.QtWebChannel ^
    src/app/main.py
```

---

## Output Structure

After building, `dist\WIMI\` contains:

```
dist/WIMI/
├── WIMI.exe              # Main executable
├── app_data/             # User data (created on first run)
│   ├── users.db          # Master database
│   ├── media/            # User media files
│   └── user_*.db         # Per-user databases
├── logs/                 # Application logs
├── web/                  # Bundled web assets
│   ├── html/
│   ├── css/
│   └── js/
├── PyQt6/                # Qt libraries
├── *.dll                 # Windows DLLs
└── [other support files]
```

---

## Distribution Methods

### Method 1: ZIP Archive (Simplest)

1. Build the application
2. Zip the entire `dist\WIMI` folder
3. Users extract and run `WIMI.exe`

```powershell
# Create ZIP
Compress-Archive -Path "dist\WIMI" -DestinationPath "WIMI-v1.0-windows.zip"
```

### Method 2: Inno Setup Installer (Professional)

1. Download [Inno Setup](https://jrsoftware.org/isinfo.php)
2. Create an installer script (see below)
3. Compile to create `WIMI-Setup.exe`

**Basic Inno Setup Script (`wimi_installer.iss`):**

```iss
[Setup]
AppName=WIMI
AppVersion=1.0
DefaultDirName={autopf}\WIMI
DefaultGroupName=WIMI
OutputBaseFilename=WIMI-Setup
Compression=lzma2
SolidCompression=yes

[Files]
Source: "dist\WIMI\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\WIMI"; Filename: "{app}\WIMI.exe"
Name: "{commondesktop}\WIMI"; Filename: "{app}\WIMI.exe"

[Run]
Filename: "{app}\WIMI.exe"; Description: "Launch WIMI"; Flags: postinstall nowait
```

### Method 3: NSIS Installer (Alternative)

Similar to Inno Setup but with different syntax.

---

## Troubleshooting

### Issue: "Missing DLL" errors

**Solution:** Ensure all PyQt6 dependencies are included:

```powershell
pip install PyQt6 PyQt6-WebEngine PyQt6-Qt6 PyQt6-WebEngine-Qt6
```

### Issue: "No module named X" at runtime

**Solution:** Add to `hiddenimports` in `wimi.spec`:

```python
hiddenimports = [
    # ... existing imports ...
    'missing_module_name',
]
```

### Issue: Web content not loading

**Solution:** Verify web assets are bundled correctly:

```python
# In wimi.spec, ensure datas includes:
datas = [
    ('src/web/html', 'web/html'),
    ('src/web/css', 'web/css'),
    ('src/web/js', 'web/js'),
]
```

### Issue: QtWebEngine crashes

**Solution:** PyQt6-WebEngine requires specific Visual C++ redistributables:
- Download [VC++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)
- Include in installer or instruct users to install

### Issue: Application data location

The built app needs to handle paths differently. Modify `main.py`:

```python
import sys
from pathlib import Path

def get_app_data_dir():
    """Get appropriate data directory for bundled or dev mode."""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return Path(sys.executable).parent / 'app_data'
    else:
        # Running in development
        return Path(__file__).parent.parent.parent / 'app_data'
```

---

## Code Signing (Optional but Recommended)

Unsigned executables trigger Windows SmartScreen warnings.

### Self-Signed Certificate (Testing)

```powershell
# Create self-signed certificate
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=WIMI Developer" -CertStoreLocation Cert:\CurrentUser\My

# Sign executable
Set-AuthenticodeSignature -FilePath "dist\WIMI\WIMI.exe" -Certificate $cert
```

### Purchased Certificate (Production)

Purchase from DigiCert, Sectigo, or similar CA for ~$200-500/year.

---

## Build Optimization

### Reduce Size

1. Use UPX compression (already in spec file)
2. Exclude unnecessary packages:

```python
excludes=[
    'tkinter',
    'unittest',
    'email',
    'xml',
    'pydoc',
]
```

### Faster Startup

Avoid `--onefile` mode; folder mode starts faster.

---

## Automated CI/CD Build

**GitHub Actions Example (`.github/workflows/build.yml`):**

```yaml
name: Build Windows

on:
  push:
    tags: ['v*']

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pyinstaller
          
      - name: Build
        run: pyinstaller wimi.spec --noconfirm
        
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: WIMI-Windows
          path: dist/WIMI/
```

---

## Version Checklist

Before building a release:

- [ ] Update version number in application
- [ ] Run full test suite: `pytest`
- [ ] Test on clean Windows VM
- [ ] Check all web assets load correctly
- [ ] Verify database creation works
- [ ] Test media upload/display
- [ ] Check error logging works

---

## File Size Expectations

| Component | Approximate Size |
|-----------|-----------------|
| PyQt6 + WebEngine | ~150-200 MB |
| Python runtime | ~30-40 MB |
| Application code | ~5-10 MB |
| **Total** | **~200-250 MB** |

The large size is primarily due to the embedded Chromium browser (QtWebEngine).

---

## Alternative: Lighter Build Without WebEngine

If size is critical, consider rewriting the UI with:
- **Native PyQt6 widgets** (no web view)
- **PySide6** (similar, MIT licensed)
- **Tauri** (Rust-based, uses system WebView)
- **Electron** (larger but more common)

However, this would require significant refactoring of the existing HTML/CSS/JS frontend.
