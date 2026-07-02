# CI Setup for the WIMI Test Infrastructure

This document explains the headless CI pipeline that runs the
`wimi_test` pytest suite on every push to `master` and every pull
request targeting `master`. The workflow definition lives at
`.github/workflows/test-infrastructure.yml`. This file explains *why* it
looks the way it does so future maintainers don't have to reverse-
engineer the apt-get list.

It is the implementation artifact of task **T6.1** in
`docs/planning/TEST_INFRASTRUCTURE_TASKS.md`.

## What `QT_QPA_PLATFORM=offscreen` does

Qt selects a "platform plugin" at startup that owns the bridge to the
host windowing system — `xcb` on Linux/X11, `wayland` on Linux/Wayland,
`cocoa` on macOS, `windows` on Windows. The `offscreen` plugin is a
software-only replacement: Qt creates real `QWindow`/`QWidget`/
`QWebEngineView` objects and renders into in-memory buffers instead of
real windows, with no contact with any display server. From the
application's point of view nothing changes — `show()`, `raise_()`,
event handling, painting, screenshots all work — but no pixels reach a
monitor.

The flag is set two ways in this repository:

- **`conftest.py`** sets `os.environ["QT_QPA_PLATFORM"] = "offscreen"`
  at import time when `CI=true` and the variable isn't already set.
  This is what makes `pytest` runs work locally if a developer wants to
  reproduce CI behaviour with `CI=true pytest`.
- **The workflow** sets it at the job level via `env:`. This is
  belt-and-suspenders: it guarantees that subprocesses spawned by the
  WIMI test fixtures (which `os.environ.copy()` from the parent) see it
  even if Python imports for the parent process somehow get reordered.

## Why CI needs it

GitHub-hosted Ubuntu runners ship without a display server. Without
`QT_QPA_PLATFORM=offscreen`, `QApplication()` fails with:

```
qt.qpa.plugin: Could not find the Qt platform plugin "xcb" in ""
This application failed to start because no Qt platform plugin could be initialized.
```

The fix is one of:

1. Run a virtual X server (`xvfb-run pytest …`). Works, but adds a
   dependency and is slower because every paint round-trips through X.
2. Use `QT_QPA_PLATFORM=offscreen`. Native, in-process, faster, and
   what we use.

QtWebEngine specifically still needs the EGL/GLX/Mesa stack present on
disk even in offscreen mode (it uses them for software-rasterised GL
contexts), which is what the system-package list below installs.

## Ubuntu system packages

These are installed in the workflow before `pip install`. One-line
explanation per package:

| Package | Why we need it |
|---|---|
| `libegl1` | EGL loader; QtWebEngine's GPU process opens it even in software mode. |
| `libglib2.0-0` | GLib runtime; Qt's event loop and signal/slot plumbing on Linux. |
| `libdbus-1-3` | D-Bus client; Qt uses it for accessibility and theme detection. |
| `libxkbcommon0` | XKB common runtime; required for keyboard handling. |
| `libxkbcommon-x11-0` | X11 bridge for `libxkbcommon`; loaded transitively. |
| `libxcb-icccm4` | XCB ICCCM helpers; window-manager protocol primitives. |
| `libxcb-image0` | XCB image extension; used by Qt for pixmap transport. |
| `libxcb-keysyms1` | XCB keysym helpers; keysym ↔ keycode translation. |
| `libxcb-randr0` | XCB RandR; screen-geometry queries. |
| `libxcb-render-util0` | XCB render helpers; antialiased glyph rendering. |
| `libxcb-shape0` | XCB shape extension; non-rectangular windows. |
| `libxcb-sync1` | XCB sync extension; frame pacing primitives. |
| `libxcb-xfixes0` | XCB Xfixes extension; cursor/region operations. |
| `libxcb-xinerama0` | XCB Xinerama; multi-monitor geometry. |
| `libxcb-xkb1` | XCB XKB extension; pairs with `libxkbcommon-x11-0`. |
| `libxcomposite1` | X composite extension; compositor support. |
| `libxdamage1` | X damage extension; partial-redraw notifications. |
| `libxrandr2` | X RandR client; screen-geometry queries (non-XCB). |
| `libxtst6` | X test extension; synthetic input events. |
| `libnss3` | NSS crypto stack; QtWebEngine's network stack uses it for TLS. |
| `libasound2t64` | ALSA runtime; QtWebEngine media pipeline initialises it even when muted. (Ubuntu 24.04+ name; on 22.04 it is `libasound2`.) |

If a future Qt point-release adds a new transitive `.so` dependency, the
failure mode is a clean `Could not load the Qt platform plugin
"offscreen"` error message that names the missing library — append it
to the list and the table above.

## Adding macOS and Windows runners later

The starter workflow runs Ubuntu only. Adding the other platforms is a
matrix expansion plus a couple of conditional steps:

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, macos-latest, windows-latest]
runs-on: ${{ matrix.os }}
```

Then make these adjustments:

- **macOS.** No `apt-get` step; remove or guard with
  `if: runner.os == 'Linux'`. macOS runners *do* have a real display
  available to the running user session, so you can leave
  `QT_QPA_PLATFORM` unset and Qt will pick `cocoa`. If you want
  reproducibility with the Linux job set `QT_QPA_PLATFORM=offscreen`
  there too — Qt's macOS offscreen plugin is supported.
- **Windows.** Same: skip `apt-get`. Windows runners have a session
  desktop; `QT_QPA_PLATFORM=offscreen` is supported and recommended for
  consistency, but `windows` (the default) also works. Be aware that
  PyQt6 wheels on Windows ship the Qt DLLs, so no extra system install
  is required there.
- **Caching.** `actions/setup-python@v5` already caches pip across runs
  via the `cache: pip` setting we use; that flag works on all three OSes
  unchanged.
- **Per-OS marker filtering.** If a particular slow test misbehaves on
  one OS, prefer marking it with a custom marker
  (`@pytest.mark.skip_on_windows`) rather than branching the workflow.

## pychrome: a single-wheel CDP client (no post-install step)

The slow-marked tests use the `pychrome` Python package as a CDP
client to drive the existing QtWebEngine instance — they do *not*
spawn Chromium, Firefox, or WebKit. Concretely:

- `pip install pychrome` is required (the workflow does this).
- There is **no** post-install step. pychrome is a pure-Python wheel
  that talks directly to Qt's already-running CDP server; it has no
  bundled browsers and nothing analogous to `playwright install`.

If a future test ever needs a real Chromium (e.g. for a non-WIMI fixture
or a visual-diff helper), prefer adding a step gated on the specific
test path rather than installing browsers unconditionally for the
default suite.

### Why pychrome instead of Playwright

The original test-infrastructure design used the Playwright Python
sync API as the CDP client. Playwright's `chromium.connect_over_cdp`
issues `Browser.setDownloadBehavior` during connection setup, but
Qt's CDP server only implements `Page`, `Runtime`, `DOM`, `Network`,
`Input`, and partial `Target` — not the `Browser` domain — so the
connection always failed against Qt. The migration to pychrome (a thin
CDP client without the `Browser.*` setup calls) is documented in
`docs/planning/PYCHROME_MIGRATION.md`.

During the migration window the workflow installs both `pychrome` and
`playwright` so the existing imports keep loading; M3.5 in the
migration tracker drops `playwright` once the live smoke tests confirm
pychrome is sufficient end-to-end.

The CDP-vs-bundled-browsers relationship is also documented in
`docs/planning/TEST_INFRASTRUCTURE.md` §4 (which was updated when the
migration landed).

## Failure artifacts

Failed runs upload `pytest_artifacts/` via `actions/upload-artifact@v4`
with `if-no-files-found: ignore` (so a green run doesn't error trying
to upload an empty directory) and `retention-days: 14`. Successful runs
deliberately upload nothing, both because there's typically nothing to
look at and because storage adds up.

The 14-day retention is a guess — see Open Questions below.

## Still TBD

See `docs/planning/TEST_INFRASTRUCTURE.md` §11 ("Open Questions") for
items the CI pipeline will eventually need to answer:

- **Visual regression baseline storage.** If/when snapshot diffing
  lands, where do the baseline screenshots live (dedicated branch, Git
  LFS, `tests/baselines/` committed directly)? The workflow makes no
  provision for this yet.
- **`pytest_artifacts/` retention policy.** 14 days is a placeholder;
  the right answer depends on how often we actually go look at failed
  runs from a week ago.
- **Cross-OS coverage.** macOS and Windows runners are deferred until
  the Linux pipeline is stable enough that adding two more platforms
  doesn't drown the signal in noise.
