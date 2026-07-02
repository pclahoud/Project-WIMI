# Auto-Updater Feature Plan

**Last Updated:** 2026-02-25

---

## Context

WIMI has no update mechanism. When a new version is built, users must manually download and replace the entire app folder. The app is distributed as a PyInstaller bundle (~200-250MB) on Windows (and eventually macOS). The version is hardcoded in 3 places ('0.4.0' in two, '0.2.0' in the About dialog).

**Hosting:** The download source is TBD (the private development git server is not publicly accessible). The updater will use a **manifest JSON pattern** so the download source is swappable — any public URL (GitHub Releases, Google Drive, CDN, etc.) can serve the files.

**Goal:** Add an auto-updater that checks for new versions (on startup + manual), downloads the update, and applies it via restart. Support both Windows and macOS.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Update UI | Web components (HTML/CSS/JS) | Visual consistency with existing WIMI UI |
| Update preferences | Global in `users.db` `app_settings` table | Uses existing `get_setting()`/`set_setting()` API with JSON type support |
| Update source | Manifest JSON file at configurable URL | Decouples version checking from download hosting; source-agnostic |
| File swap mechanism | Platform-specific scripts (.bat / .sh) | Python runtime lives inside `_internal/` — can't use Python to replace itself |
| macOS support | Shell script equivalent of batch script | Same logic: wait for exit, swap, rollback on failure, relaunch |
| Version source | Single `src/version.py` | Replaces 3 hardcoded locations |
| Initial version | `0.5.0` | Next version after current `0.4.0` |
| Dependencies | None new — `urllib.request` (stdlib) | No new packages needed |

---

## Manifest JSON Pattern

The app fetches a small JSON manifest from a known public URL to check for updates. The manifest points to the actual download location, which can be anywhere.

```json
{
  "latest_version": "0.6.0",
  "min_app_version": "0.5.0",
  "releases": {
    "windows": {
      "download_url": "https://example.com/WIMI-v0.6.0-win64.zip",
      "sha256": "abc123...",
      "size_bytes": 250000000
    },
    "macos": {
      "download_url": "https://example.com/WIMI-v0.6.0-macos.zip",
      "sha256": "def456...",
      "size_bytes": 230000000
    }
  },
  "changelog": "### v0.6.0\n- Bug fixes\n- New features",
  "mandatory": false
}
```

**To release a new version:** Upload the zip(s) to whatever host you're using, then update the manifest JSON with the new version, URLs, and hashes.

**To switch hosting:** Change the `download_url` values in the manifest. The app logic doesn't change.

---

## New Files

| File | Purpose |
|------|---------|
| `src/version.py` | Single source of truth for app version |
| `src/app/update_config.py` | Configurable manifest URL, timeouts, settings |
| `src/app/updater.py` | UpdateChecker class — check, download, verify, stage |
| `src/web/html/update_dialog.html` | Web-based update UI (available, progress, restart) |
| `src/web/css/update_dialog.css` | Styles for update dialog components |
| `src/web/js/update_dialog.js` | JavaScript for update dialog interactions |
| `tests/app/test_updater.py` | Unit tests for version comparison, manifest parsing, hash verification |

## Files to Modify

| File | Change |
|------|--------|
| `src/app/main_window.py` | Import version; add "Check for Updates" menu item; startup check trigger; closeEvent launches swap script if update staged |
| `src/app/bridge.py` | Replace hardcoded version with import from `version.py`; add update-related `@pyqtSlot` methods |
| `src/web/js/api.js` | Add JavaScript API wrappers for update bridge methods |
| `src/app/main.py` | Import version for startup banner; detect previously staged update on launch |
| `src/database/master_db.py` | No schema changes — uses existing `app_settings` table |
| `build_windows.bat` | Add step to zip `dist\WIMI\` and compute SHA-256 hash |
| `wimi.spec` | No changes needed — `version.py` is auto-collected via `pathex=[src/]` |

---

## Implementation Stages

### Stage 1: Version Consolidation

Create `src/version.py` and replace all hardcoded version references:

```python
__version__ = '0.5.0'
```

Update the 3 hardcoded version references to import from here:
- `main_window.py:340` — About dialog
- `main_window.py:400` — `app.setApplicationVersion()`
- `bridge.py:1029` — `getAppInfo()`

---

### Stage 2: Update Config + Core Logic

**Create `src/app/update_config.py`:**

- `MANIFEST_URL` — Public URL to the manifest JSON (placeholder until hosting is decided)
- `REQUEST_TIMEOUT` — seconds (default 15)
- `UPDATE_STAGING_DIR` — `"_update_staging"` (relative to app root)

**Create `src/app/updater.py` — UpdateChecker class:**

Class `UpdateChecker(QObject)` using QThread workers for non-blocking operations.

**Signals:**
- `update_available(str)` — JSON with version, changelog, download URL, hash, size
- `update_not_available()`
- `check_error(str)`
- `download_progress(int, int)` — bytes downloaded, total bytes
- `download_complete(str)` — staging path
- `download_error(str)`

**Key methods:**

1. `check_for_updates()` — GET manifest JSON, compare `latest_version` against `__version__` using simple tuple comparison, check platform-specific release entry, emit result
2. `download_update(url, expected_hash)` — Download zip in 64KB chunks with progress, verify SHA-256 hash, extract to staging dir
3. `apply_update_on_exit(app_dir, staging_dir)` — Detect platform, write appropriate swap script (`.bat` or `.sh`) to temp dir, launch as detached process

**Version comparison** — simple semver tuple compare (no new dependency):
```python
def compare_versions(current, remote):
    c = tuple(int(x) for x in current.lstrip('v').split('.'))
    r = tuple(int(x) for x in remote.lstrip('v').split('.'))
    return (r > c) - (r < c)
```

**Manifest fetch** — `urllib.request` (stdlib). Parse JSON, select platform entry (`sys.platform`).

---

### Stage 3: Web-Based Update UI

All update dialogs as web components within the existing QWebEngineView, following WIMI's UI patterns.

**Components:**

1. **Update Available Dialog:**
   - Shows current version vs new version
   - Changelog text area (from manifest `changelog` field)
   - Download size indicator
   - Buttons: "Download & Install", "Remind Me Later", "Skip This Version"

2. **Download Progress:**
   - Progress bar with bytes/total and percentage
   - Cancel button
   - Connected to `download_progress` signal via bridge

3. **Restart Prompt:**
   - "Update ready. Restart now to apply?"
   - "Restart Now" / "Restart Later"

**Bridge methods** (new `@pyqtSlot` methods in `bridge.py`):
- `checkForUpdates()` — triggers check, returns result via callback
- `downloadUpdate(url, hash)` — starts download, emits progress via signal
- `applyUpdate()` — stages the swap script
- `skipVersion(version)` — saves skipped version to `app_settings`
- `getUpdatePreferences()` — reads from `app_settings`
- `setUpdatePreferences(json)` — writes to `app_settings`

---

### Stage 4: Main Window Integration

1. **Menu bar** — Add "Check for &Updates..." to Help menu (before About)
2. **Startup check** — After `window.show()`, if not `dev_mode` and auto-check enabled, call `UpdateChecker.check_for_updates()` on background thread
3. **Manual check** — Menu item triggers the same check but shows error dialogs on failure (startup check is silent on failure)
4. **closeEvent** — If an update is staged and user confirmed restart, launch the swap script before accepting the close event

---

### Stage 5: Platform-Specific File Swap Scripts

**Windows (`.bat` template):**

Written to `%TEMP%` at apply time. Flow:
1. Wait for `WIMI.exe` to exit (tasklist polling loop)
2. Rename `_internal` → `_internal.bak` (backup)
3. Copy new `_internal` and `WIMI.exe` from staging
4. On success: delete backup + staging, restart `WIMI.exe`
5. On failure: rollback (`_internal.bak` → `_internal`), restart old version
6. Delete itself (`del %~f0`)

**macOS (`.sh` template):**

Written to `/tmp/` at apply time. Flow:
1. Wait for WIMI process to exit (polling loop)
2. Backup current `.app` bundle contents
3. Copy new files from staging
4. On success: delete backup + staging, relaunch
5. On failure: rollback, relaunch old version
6. Delete itself

**Why scripts, not Python?** Python runtime lives inside `_internal/` — can't use Python to replace the directory containing Python.

**Preserves:** `app_data/` and `logs/` are never touched.

---

### Stage 6: Build Script Changes + Preferences

**Update `build_windows.bat`:**

Add step [5/5] after current [4/4]:
- Read version from `src/version.py` via Python one-liner
- Create `dist\WIMI-v{version}-win64.zip` using PowerShell `Compress-Archive`
- Compute SHA-256 via `certutil -hashfile`
- Print hash for use in manifest JSON

**Update preferences** — stored in `users.db` `app_settings` table:

| Setting Key | Type | Default | Description |
|-------------|------|---------|-------------|
| `update_skipped_version` | `string` | `null` | Suppresses startup notification for this version (not manual checks) |
| `update_last_check_time` | `string` | `null` | ISO 8601 timestamp of last check |
| `update_auto_check_enabled` | `boolean` | `true` | Whether to check on startup |

Uses existing `master_db.get_setting()` / `master_db.set_setting()` API with the `AppSetting` model and `get_typed_value()` for type conversion.

---

### Stage 7: Tests

Unit tests in `tests/app/test_updater.py`:
- Version comparison (equal, newer, older, pre-release tags)
- Manifest JSON parsing (valid, missing fields, wrong platform)
- SHA-256 hash verification (match, mismatch)
- Platform detection for swap script selection
- Update preferences read/write via `app_settings`

---

## Startup Behavior

**On launch** (in `src/app/main.py`):
1. If `_update_staging/` exists with app files inside, prompt user to apply the previously downloaded update
2. If auto-check enabled and not dev mode, check for updates on background thread
3. If update available and version not skipped, show notification in the web UI

---

## Edge Cases

- **Network unreachable on startup:** Silent fail, log debug message
- **Network unreachable on manual check:** Show error dialog
- **Hash mismatch:** Delete download, show error, do not stage
- **Partial download:** Delete and retry from scratch (no resume)
- **Staging dir already exists:** Clean it before new download
- **App in read-only location (e.g. Program Files):** Detect with test write, show "cannot auto-update" message
- **Disk space:** Check ~750MB free (zip + extracted) via `shutil.disk_usage()` before downloading
- **Dev mode:** Skip startup check entirely; menu item still available for testing
- **Manifest URL not configured:** Show "update checking not configured" on manual check; silent skip on startup

---

## Release Workflow (for each new version)

1. Update `__version__` in `src/version.py`
2. Run `build_windows.bat` → produces `dist\WIMI-v{ver}-win64.zip` + SHA-256
3. (Future) Run macOS build script → produces macOS zip + SHA-256
4. Upload zip(s) to download host (TBD)
5. Update manifest JSON with new version, URLs, hashes, changelog
6. `git tag v{ver}` and push tag

---

## Verification

1. **Unit tests:** `pytest tests/app/test_updater.py -v --no-cov` — version comparison, manifest parsing, hash verification
2. **Manual smoke test:** Build app, host a manifest + small dummy zip, launch compiled app, verify:
   - Update notification appears in web UI on startup
   - "Check for Updates" menu item works
   - Download shows progress
   - Swap script replaces files and restarts
3. **Rollback test:** Intentionally corrupt the staged update, verify the swap script rolls back and restarts the old version
4. **Cross-platform:** Test swap script on both Windows and macOS

---

## Open Items

- [ ] **Hosting decision:** Where to host the manifest JSON and release zips (GitHub Releases, Google Drive, CDN, etc.)
- [ ] **macOS build script:** `build_mac.sh` equivalent of `build_windows.bat`
- [ ] **macOS PyInstaller bundle structure:** Determine exact file layout for `.app` bundle swap logic
