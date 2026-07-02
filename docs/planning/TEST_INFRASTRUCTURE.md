# WIMI Test Infrastructure: `wimi_test` Library + `wimi-test` MCP Facade

**Status:** Proposed (design complete; pre-implementation)
**Created:** 2026-05-07
**Companion docs:** `docs/testing/UI_AUDIT.md` (locator strategy & testid scheme), `docs/planning/POLYHIERARCHY_MIGRATION.md`, `docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`, `docs/planning/PYCHROME_MIGRATION.md` (the Playwright→pychrome migration that supersedes parts of §4, §6, and §8)

> **Migration note (2026-05):** This document was updated when the Playwright→pychrome migration landed. The original design assumed Playwright Python's sync API would drive QtWebEngine over CDP, but Qt's CDP server implements only `Page`/`Runtime`/`DOM`/`Network`/`Input`/`Target` — not the `Browser` domain that Playwright's `connect_over_cdp` requires — so the connection setup always failed against Qt. The migration replaces Playwright with `pychrome` (a thin CDP client) while preserving the public API of `WimiPage`, `WimiLocator`, `WimiTestSession`, the pytest fixtures, and the MCP tool surface. See `PYCHROME_MIGRATION.md` for the rationale, the per-task breakdown (M1.1–M3.5), and the per-domain CDP support matrix.

## 1. Goals & Non-Goals

**Goals**

- Layered testing: a regression suite (pytest) and Claude-driven exploratory testing (MCP), built on the same primitives so they never diverge.
- Industrial-strength UI control via Chrome DevTools Protocol — pychrome (a thin CDP client) talking to QtWebEngine remote debugging. (Originally specced as Playwright Python over CDP; see `PYCHROME_MIGRATION.md` §3 for why that didn't work against Qt's partial CDP surface.)
- Per-test isolation backed by WIMI's existing per-user-database architecture.
- Always-on capture of console messages, network events, and bridge calls. Failure reports include screenshot, console log, network log, and bridge log.
- Reliable locators following the role+name → testid → CSS preference order documented in `docs/testing/UI_AUDIT.md`.

**Non-Goals**

- No process-reuse optimization for v1. Function-scope tests get a fresh subprocess; we'll measure pain before adding class-scope.
- No browser-driver dependencies. We drive the existing QtWebEngine via CDP using pychrome, which talks to Qt's already-running CDP server — no Chromium/Firefox/WebKit download. (Originally specced as "Playwright bundled browsers are skipped" — same goal, different client; see `PYCHROME_MIGRATION.md`.)
- No async test support for v1. Library and pytest are sync; only the MCP facade's request handlers are async.
- No headless-only mode. `--test-mode` defaults to headed; CI sets headless via existing Qt offscreen platform.

## 2. Architecture Overview

```
┌──────────────────────────────┐    ┌──────────────────────────────┐
│  Claude (interactive)        │    │  pytest (regression)         │
└────────────┬─────────────────┘    └────────────┬─────────────────┘
             │ MCP (stdio or SSE)                │ import
             ▼                                   ▼
┌──────────────────────────────┐    ┌──────────────────────────────┐
│  wimi-test MCP server        │    │   ─────►                      │
│  (thin facade)               │───►│   wimi_test Python library    │
└──────────────────────────────┘    │   (TestSession, locators,     │
                                    │    captures, fixtures)        │
                                    └────────────┬─────────────────┘
                                                 │
                              ┌──────────────────┼──────────────────┐
                              ▼                                     ▼
                    ┌──────────────────┐                ┌──────────────────┐
                    │ MasterDatabase   │                │  pychrome / CDP  │
                    │ (test fixtures)  │                │  → QWebEngineView│
                    └──────────────────┘                └──────────────────┘
```

The MCP server is a thin shim. All real work — process management, locators, fixtures, captures — lives in `wimi_test` as a regular Python package. pytest imports it directly. The MCP server wraps the same primitives. They share one source of truth.

## 3. Package Layout

```
Project_WIMI_Dev/
├── wimi_test/                         # Library — imported by pytest, by MCP facade, by ad-hoc scripts
│   ├── __init__.py                    # Re-exports: WimiTestSession, WimiPage, WimiLocator, fixtures
│   ├── session.py                     # WimiTestSession: lifecycle owner. Hub for process / page / capture / db.
│   ├── process.py                     # WimiProcess: subprocess management — spawn, port pick, ready signal, kill.
│   ├── page.py                        # WimiPage: thin wrapper over a pychrome WimiTab. Route-name navigation. (Originally specced over playwright.sync_api.Page; see PYCHROME_MIGRATION.md §5.2.)
│   ├── locator.py                     # WimiLocator: enforces role+name → testid → CSS preference + auto-waiting.
│   ├── routes.py                      # Logical-name → URL map. Single source of truth.
│   ├── errors.py                      # Exception hierarchy.
│   ├── config.py                      # TestConfig dataclass.
│   ├── capture/
│   │   ├── __init__.py                # Re-exports ConsoleCapture, NetworkCapture, BridgeCapture, CaptureBundle.
│   │   ├── console.py                 # ConsoleCapture: subscribes to Runtime.consoleAPICalled / Runtime.exceptionThrown via tab.set_listener (originally page.on("console"), pageerror; see PYCHROME_MIGRATION.md §5.4).
│   │   ├── network.py                 # NetworkCapture: CDP Network.* domain subscription via tab.set_listener.
│   │   ├── bridge.py                  # BridgeCapture: polls instrumented bridge call buffer via tab.evaluate(expression).
│   │   └── bundle.py                  # CaptureBundle: composes all three streams; serializes for failure reports.
│   ├── db/
│   │   ├── __init__.py                # Re-exports TestUser, seeders, db helpers.
│   │   ├── test_user.py               # TestUser: per-test user wrapper around MasterDatabase.create_user.
│   │   ├── seeders.py                 # Named seeder registry: seed_minimal, seed_usmle_outline, etc.
│   │   └── assertions.py              # DB-side assertion helpers (assert_entry_count, assert_subject_tree, ...).
│   ├── fixtures/
│   │   ├── __init__.py                # pytest plugin entry point.
│   │   ├── core.py                    # wimi_session, test_user, seeded_user fixtures.
│   │   ├── capture.py                 # console_log, network_log fixtures + autouse screenshot_on_failure hook.
│   │   └── markers.py                 # Custom markers (@pytest.mark.wimi_scenario, etc).
│   └── _internal/
│       ├── cdp_client.py              # pychrome wrapper: WimiBrowser, WimiTab, open_session(port), wait_for_wimi_api. Single seam over pychrome.
│       ├── runid.py                   # Monotonic per-process run-id (pid + counter) for test-user names.
│       └── async_bridge.py            # Sync→async bridge for MCP facade. The one place threading bites.
│
└── src/
    ├── app/
    │   ├── test_mode.py               # NEW. TestModeQWebEnginePage subclass + IS_ACTIVE state + helpers.
    │   ├── bridge_test_instrumentation.py   # NEW. Instrumentation decorator for @pyqtSlot calls.
    │   ├── main.py                    # MODIFIED. --test-mode flag flow.
    │   └── ...
    ├── wimi_test_mcp/                 # MCP facade — every tool is a 5–15 line shim
    │   ├── __init__.py
    │   ├── server.py                  # FastMCP("wimi-test") + tool registrations.
    │   ├── registry.py                # SessionRegistry: at-most-one active session.
    │   ├── adapters.py                # CaptureBundle → JSON; exceptions → structured error replies.
    │   └── tools/
    │       ├── __init__.py            # Tool group registration helper.
    │       ├── lifecycle.py           # start_session, end_session, get_session_status.
    │       ├── navigation.py          # navigate_to, wait_for, eval_js.
    │       ├── interaction.py         # click, fill, screenshot.
    │       └── inspection.py          # get_console_log, get_network_log, get_bridge_log, dump_dom.
    └── mcp_server.py                  # Existing wimi-db read-only server. Untouched.
```

Total: ~24 new files. Library carries the weight; MCP facade is intentionally thin so it can change without library churn.

### Module responsibility matrix

| Module | Owns | Imports from | Imported by |
|---|---|---|---|
| `wimi_test.session` | End-to-end session: spawn → attach → capture → teardown. The single object pytest and MCP both hold. | `process`, `page`, `capture`, `db.test_user`, `config`, `errors` | `fixtures.core`, `wimi_test_mcp.tools.lifecycle` |
| `wimi_test.process` | OS subprocess concerns. Launches `python run_wimi.py --test-mode`, picks free port, watches stdout for ready signal, ensures kill on teardown. | `config`, `errors` | `session` |
| `wimi_test.page` | pychrome `WimiTab` wrapper (originally specced as a Playwright `Page` wrapper; see `PYCHROME_MIGRATION.md` §5.2). Maps logical routes to file:// URLs, waits for `window._wimiApi`, exposes locator factory. | `routes`, `locator`, `errors`, `_internal.cdp_client` | `session` |
| `wimi_test.locator` | role+name → testid → CSS resolution + auto-waiting via `Runtime.evaluate` polling and `Input.dispatchMouseEvent` (originally Playwright's locator + auto-wait; see `PYCHROME_MIGRATION.md` §5.3). The most-touched test-author file. | `errors`, `_internal.cdp_client` | `page`, tests |
| `wimi_test.capture.console` | `Runtime.consoleAPICalled` + `Runtime.exceptionThrown` subscription via `tab.set_listener` (originally `page.on("console")` + `pageerror`). Ring buffer, severity classification. | `errors` | `session`, `fixtures.capture` |
| `wimi_test.capture.network` | CDP `Network.*` domain subscription via `tab.set_listener` with URL-based filtering and header redaction. | `errors` | `session`, `fixtures.capture` |
| `wimi_test.capture.bridge` | Polls the instrumented bridge call buffer via `tab.evaluate("getTestModeBridgeCalls(...)")` (originally `page.evaluate(fn, args)`). | `errors` | `session`, `fixtures.capture` |
| `wimi_test.capture.bundle` | Composes the three streams into a single `CaptureBundle` for failure reports and MCP tool returns. | `console`, `network`, `bridge` | `fixtures.capture`, `wimi_test_mcp.adapters` |
| `wimi_test.db.test_user` | Per-test user. Creates via `MasterDatabase.create_user('test_<scenario>_<runid>')`, points at `app_data_test/`, drops on teardown. | `src/database/master_db.py`, `src/database/user_db.py`, `_internal.runid` | `session`, `fixtures.core` |
| `wimi_test.db.seeders` | Named-function seeder registry. Reused by pytest's `seeded_user(scenario)` and MCP `start_session(scenario=...)`. | `src/database/user_db.py` | `fixtures.core`, `wimi_test_mcp.tools.lifecycle` |
| `wimi_test.db.assertions` | DB-side assertion helpers. Pure leaf. | `src/database/*` | tests, `wimi_test_mcp.tools.inspection` |
| `wimi_test.fixtures.core` | Pytest fixtures (`wimi_session`, `test_user`, `seeded_user`). Glue layer. | `session`, `db.*`, `capture` | pytest collection |
| `wimi_test.fixtures.capture` | Capture fixtures + autouse `screenshot_on_failure` hook. | `capture`, `session` | pytest collection |
| `wimi_test.routes` | Logical name → URL map. Decoupled so `src/web/html/` renames are one-line. | (none) | `page`, MCP nav tools |
| `wimi_test.errors` | Exception hierarchy: `WimiTestError`, `ProcessSpawnError`, `AttachTimeout`, `LocatorAmbiguous`, `AssertionFailureWithCapture`. | (none) | everywhere |
| `wimi_test.config` | `TestConfig` dataclass. Resolves env vars + pytest CLI flags. | (none) | `session`, `process`, MCP server |
| `wimi_test._internal.async_bridge` | Sync↔async bridge for MCP. Encapsulates the threading concern in one place. | (stdlib) | `wimi_test_mcp.server` |
| `src/app/test_mode.py` | `TestModeQWebEnginePage` subclass + `IS_ACTIVE` state + ready-signal emit + console buffer access. | (Qt) | `src/app/main.py` |
| `src/app/bridge_test_instrumentation.py` | `@instrumented_slot` decorator wrapping `@pyqtSlot` for bridge call capture. | (PyQt) | every `bridge_domains/*.py` mixin |
| `src/wimi_test_mcp.server` | FastMCP app, lifespan hooks, registry wiring. | `wimi_test`, `registry`, `tools.*` | (entry point) |
| `src/wimi_test_mcp.registry` | `SessionRegistry`: at-most-one active session, idle timeout, idempotent shutdown. | `wimi_test.session` | server, tools |
| `src/wimi_test_mcp.tools.*` | One MCP function per tool. No business logic; adapter shims only. | `wimi_test.*`, `registry`, `adapters` | `server` |
| `src/wimi_test_mcp.adapters` | Capture/exception → JSON-serializable. Pure leaf. | `wimi_test.capture.bundle`, `wimi_test.errors` | `tools.*` |

**Leaves** (no internal imports): `errors`, `config`, `routes`, `_internal.runid`, `_internal.async_bridge`, `_internal.cdp_client` (its only external import is `pychrome`), `db.assertions`, `wimi_test_mcp.adapters`.
**Hubs:** `session.py` is the only place that knows about all of process / page / capture / DB at once. Everything else stays single-concern.

## 4. Public API Contracts

### `WimiTestSession` — `wimi_test/session.py`

```python
class WimiTestSession:
    """End-to-end test session. Spawns WIMI, attaches via CDP, owns captures and the test user."""

    def __init__(self, *, scenario: str, config: TestConfig | None = None) -> None: ...
    def start(self) -> None:
        """Spawn WIMI subprocess, attach CDP, create test user, install captures. Idempotent."""
    def stop(self, *, drop_user: bool = True) -> None:
        """Tear down captures, kill subprocess, optionally drop test user. Always safe to call."""

    @property
    def page(self) -> "WimiPage": ...
    @property
    def user(self) -> "TestUser": ...
    @property
    def captures(self) -> "CaptureBundle": ...

    def __enter__(self) -> "WimiTestSession": ...
    def __exit__(self, *exc) -> None: ...
```

### `WimiPage` — `wimi_test/page.py`

```python
class WimiPage:
    """WIMI-aware wrapper over a pychrome Tab (`WimiTab`). Knows logical routes and bridge readiness.

    Note: originally specced as a wrapper over playwright.sync_api.Page; see PYCHROME_MIGRATION.md §5.2.
    """

    def __init__(self, tab: "WimiTab", routes: RouteTable) -> None: ...
    def goto(self, route: str, *, wait_for_bridge: bool = True) -> None:
        """Navigate by logical route name (e.g. 'dashboard', 'entry-form'). Waits for window._wimiApi."""
    def locator(self, *, role: str | None = None, name: str | None = None,
                testid: str | None = None, css: str | None = None) -> "WimiLocator":
        """Build a locator using preference order. Exactly one of (role+name)/testid/css must be given."""
    def screenshot(self, path: Path | None = None, *, full_page: bool = False) -> bytes: ...
    def eval_js(self, expression: str) -> object:
        """Evaluate JS in the page via Runtime.evaluate. Gated behind TestConfig.allow_eval_js (default True in test mode)."""
    def wait_for_bridge_call(self, method: str, *, timeout_ms: int = 5000) -> object:
        """Wait for a bridge method call to complete. Used when JS-side code defers DB writes."""
```

### `WimiLocator` — `wimi_test/locator.py`

```python
class WimiLocator:
    """Auto-waiting locator that respects role+name → testid → CSS preference order."""

    def click(self, *, timeout_ms: int | None = None) -> None: ...
    def fill(self, value: str, *, timeout_ms: int | None = None) -> None: ...
    def expect_visible(self, *, timeout_ms: int | None = None) -> None: ...
    def text(self) -> str: ...
    def attribute(self, name: str) -> str | None: ...
```

### `ConsoleCapture` — `wimi_test/capture/console.py`

```python
class ConsoleCapture:
    """Always-on capture of JS console messages. Ring-buffered, severity-classified."""

    def __init__(self, *, max_messages: int = 10_000) -> None: ...
    def attach(self, tab: "WimiTab") -> None:
        """Subscribe to Runtime.consoleAPICalled and Runtime.exceptionThrown via tab.set_listener.
        (Originally page.on('console') / page.on('pageerror'); see PYCHROME_MIGRATION.md §5.4.) Idempotent."""
    def detach(self) -> None: ...
    def snapshot(self, *, level_min: str = "warning",
                 since_ts: float | None = None) -> list["ConsoleEntry"]:
        """Filtered view; level_min filters by severity, since_ts slices by time (per-test segmentation)."""
    def flush(self) -> list["ConsoleEntry"]: ...
```

### `NetworkCapture` — `wimi_test/capture/network.py`

```python
class NetworkCapture:
    """CDP Network.* subscription. Requests, responses, failures, with redaction."""

    def __init__(self, *, max_events: int = 5_000,
                 url_filter: Callable[[str], bool] | None = None,
                 redact_headers: Callable[[dict], dict] | None = None) -> None: ...
    def attach(self, tab: "WimiTab") -> None:
        """Calls tab.Network.enable() and subscribes via tab.set_listener('Network.requestWillBeSent', ...) etc.
        (Originally took a Playwright CDPSession; see PYCHROME_MIGRATION.md §5.4. Under pychrome the Tab itself
        is the CDP handle — there's no separate session object.)"""
    def detach(self) -> None: ...
    def snapshot(self, *, url_substr: str | None = None,
                 since_ts: float | None = None) -> list["NetworkEvent"]: ...
    def flush(self) -> list["NetworkEvent"]: ...
```

### `BridgeCapture` — `wimi_test/capture/bridge.py`

```python
class BridgeCapture:
    """Reads the instrumented bridge call buffer via the test-mode bridge slot."""

    def __init__(self, *, max_calls: int = 2_000) -> None: ...
    def attach(self, tab: "WimiTab") -> None:
        """Periodically poll getTestModeBridgeCalls() via tab.evaluate(expression).
        (Originally page.evaluate(fn, args); see PYCHROME_MIGRATION.md §5.4.)"""
    def snapshot(self, *, method_substr: str | None = None,
                 since_ts: float | None = None) -> list["BridgeCall"]: ...
    def flush(self) -> list["BridgeCall"]: ...
```

### `TestUser` — `wimi_test/db/test_user.py`

```python
class TestUser:
    """Per-session WIMI user backed by a fresh user DB under app_data_test/."""

    def __init__(self, master: "MasterDatabase", *, scenario: str, run_id: str) -> None: ...
    @property
    def username(self) -> str: ...
    @property
    def db(self) -> "UserDatabase": ...
    def seed(self, name: str, **kwargs) -> None:
        """Run a registered seeder by name (delegates to db.seeders)."""
    def drop(self) -> None:
        """Delete user + database file. Idempotent."""
```

### `SessionRegistry` — `src/wimi_test_mcp/registry.py`

```python
class SessionRegistry:
    """At-most-one active WimiTestSession in the MCP server process."""

    def __init__(self, *, idle_timeout_s: int = 600) -> None: ...
    def start(self, *, scenario: str, seed: str | None) -> str: ...
    def get(self) -> "WimiTestSession": ...
    def end(self) -> None: ...
    def heartbeat(self) -> None:
        """Reset idle-timeout countdown. Called on every tool invocation."""
```

## 5. `--test-mode` Launch Flag

### CLI surface (`run_wimi.py`)

```python
parser.add_argument('--test-mode', action='store_true',
                    help='Enable test mode: CDP, isolated app_data, no demo user, ready signal')
parser.add_argument('--debug-port', type=int, default=None,
                    help='CDP port (default: random free port from 12000-12100 range)')
parser.add_argument('--app-data-dir', type=str, default=None,
                    help='Override app_data directory (test-mode default: app_data_test/)')
parser.add_argument('--test-mcp-server', action='store_true',
                    help='Run as wimi-test MCP server (mirrors --mcp-server pattern)')
```

### Order of operations in `src/app/main.py`

The order is critical — `QTWEBENGINE_REMOTE_DEBUGGING` must be set *before* `QApplication()` is constructed.

```
1. Parse CLI args
2. If --test-mode:
     - Resolve --debug-port (pick free port from range if None)
     - os.environ['QTWEBENGINE_REMOTE_DEBUGGING'] = str(port)
     - os.environ['QT_LOGGING_RULES'] = 'qt.webenginecontext.info=false'
     - Resolve app_data_dir to --app-data-dir or 'app_data_test/'
     - Set wimi_test_mode.IS_ACTIVE = True
     - Set wimi_test_mode.DEBUG_PORT = port
3. Create QApplication
4. Detect frozen vs dev (existing code)
5. Initialize plugin system, register media:// scheme (existing code)
6. If test mode:
     - Install TestModeQWebEnginePage on the main view
     - Disable F5 reload (or rebind to no-op)
     - Skip demo-user creation in startup
7. Show window
8. After QWebChannel bridgeReady signal:
     If test mode:
       sys.stdout.write(f"TEST_MODE_READY:port={port}\n"); sys.stdout.flush()
9. Enter Qt event loop
```

### What test mode disables / changes

- **F5 reload** — bound to no-op so a test that triggers it accidentally doesn't reload mid-scenario.
- **F12 dev tools** — kept enabled (useful when developing tests).
- **Demo-user setup flow** — skipped; tests create their own user via `TestUser`.
- **Native `confirm()` dialogs** — pychrome doesn't auto-handle these (originally Playwright did via `page.on("dialog")`; see `PYCHROME_MIGRATION.md` §3 for the surface-area diff). The bridge slot `setTestModeAutoDismiss(True)` is exposed so settings.js's reset/uninstall confirmations don't block; tests should rely on that or replace native confirms with HTML modals.
- **Window size** — clamps to 1280×800 by default for screenshot consistency (overridable via `WIMI_TEST_WINDOW_SIZE` env).

### New file: `src/app/test_mode.py`

```python
IS_ACTIVE: bool = False
DEBUG_PORT: int | None = None
APP_DATA_DIR: Path | None = None

class TestModeQWebEnginePage(QWebEnginePage):
    """QWebEnginePage subclass that buffers all JS console messages."""
    def javaScriptConsoleMessage(self, level, message, line, source): ...

def emit_ready_signal(port: int) -> None: ...
def install_on_view(view: QWebEngineView) -> None: ...
def get_console_buffer() -> list[ConsoleEntry]: ...  # exposed via bridge slot
```

## 6. Capture Pipeline

Three capture streams, all attached to every test session, all sliced by timestamp for per-test segmentation. None of them reset between tests — failure reports get the slice newer than `session.start_ts`.

### 6.1 Console capture

**Two layers, each useful at different times.**

**Layer 1 — Python QWebEnginePage subclass (always-on safety net).** `TestModeQWebEnginePage` overrides `javaScriptConsoleMessage(level, message, line, source)` and appends to a ring buffer (default 10,000). Alive *from app start* — captures startup errors, plugin-load warnings, anything before the test client attaches via CDP. Exposed via:
- New bridge slot `getTestModeConsoleBuffer()` returning JSON (registered only when `IS_ACTIVE`).
- Crash handler: on uncaught exception or non-zero Qt event-loop exit, dumps to `app_data_test/last_crash_console.json`.

**Layer 2 — pychrome `Runtime.consoleAPICalled` / `Runtime.exceptionThrown` (per-test, fine-grained).** Primary capture during a test. Subscribes when `WimiTestSession` attaches; detaches on `session.stop()`. Catches `console.log`/`warn`/`error` plus uncaught exceptions. (Originally specced as Playwright `page.on("console")` + `page.on("pageerror")`; the migration swapped to pychrome's listener API — see `PYCHROME_MIGRATION.md` §5.4.)

```python
class ConsoleCapture:
    def attach(self, tab) -> None:
        tab.set_listener("Runtime.consoleAPICalled", self._on_console)
        tab.set_listener("Runtime.exceptionThrown", self._on_pageerror)
```

**Per-test segmentation.** Timestamp-based slicing. `WimiTestSession.start()` records `t_start`; `snapshot(since_ts=t_start)` returns events newer than that. No buffer reset between tests; same session-long buffer, sliced.

**`fail_on_console_error` mode.** Optional config knob (default off, on for CI). When enabled, the autouse `screenshot_on_failure` fixture also fails any test that emitted a `console.error` or `pageerror`, even if all assertions passed. Catches the silent-error class of bugs.

### 6.2 Network capture

CDP `Network.*` domain subscription via the pychrome tab. (Originally specced over Playwright's `CDPSession`; under pychrome the `Tab` itself is the CDP handle, so there's no separate session object — see `PYCHROME_MIGRATION.md` §5.4.)

```python
class NetworkCapture:
    def attach(self, tab) -> None:
        tab.Network.enable()
        tab.set_listener("Network.requestWillBeSent", self._on_request)
        tab.set_listener("Network.responseReceived", self._on_response)
        tab.set_listener("Network.loadingFailed", self._on_failure)
```

**What's captured:** HTTP/HTTPS, `media://` (custom scheme — useful for verifying media loads), `file://` and `qrc://` (filtered out by default — noisy).

**What's NOT captured:** **QWebChannel bridge calls do not appear in CDP Network events** because the QWebChannel transport bypasses the network stack. This is the most important traffic for testing. Hence the third stream below.

### 6.3 Bridge call capture

QWebChannel calls require separate instrumentation. A new file `src/app/bridge_test_instrumentation.py` provides:

```python
def instrumented_slot(slot_func):
    """Decorator wrapping @pyqtSlot. No-op outside test mode; logs call when IS_ACTIVE."""
    @functools.wraps(slot_func)
    def wrapper(self, *args, **kwargs):
        if not test_mode.IS_ACTIVE:
            return slot_func(self, *args, **kwargs)
        t0 = time.time()
        try:
            result = slot_func(self, *args, **kwargs)
            self._log_bridge_call(slot_func.__name__, args, result, (time.time() - t0) * 1000, error=False)
            return result
        except Exception as e:
            self._log_bridge_call(slot_func.__name__, args, str(e), (time.time() - t0) * 1000, error=True)
            raise
    return wrapper
```

**Application convention.** Every `@pyqtSlot` in `src/app/bridge_domains/*.py` gets a paired `@instrumented_slot` (decorator order: `@pyqtSlot` outermost, `@instrumented_slot` inner). A CI check (`scripts/check_instrumented_slots.py`) walks the bridge domain files and asserts pairing — fails the build if any new slot is missing the instrumentation.

**Buffer access.** Bridge slot `getTestModeBridgeCalls(since_ts)` returns the buffer as JSON. `BridgeCapture.attach()` polls this slot at low frequency via `tab.evaluate(expression)` (originally `page.evaluate(fn, args)` under Playwright; see `PYCHROME_MIGRATION.md` §5.4). If a future signal-based push is added, subscribes instead.

**Decorator vs runtime patching:** decorator chosen for explicitness, greppability, and resilience against PyQt internals changes. The audit cost (~190 slots × seconds-each ≈ a few hours one-time) is worth permanent stability.

### 6.4 Failure attachment

Single autouse fixture in `wimi_test/fixtures/capture.py`:

```python
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed:
        session = getattr(item, "_wimi_session", None)
        if session is not None:
            png = session.page.screenshot()
            console = format_console(session.captures.console.snapshot(since_ts=session.start_ts))
            network = format_network(session.captures.network.snapshot(since_ts=session.start_ts))
            bridge = format_bridge(session.captures.bridge.snapshot(since_ts=session.start_ts))
            rep.extras = (rep.extras or []) + [
                pytest_html.extras.image(png, "screenshot"),
                pytest_html.extras.text(console, "console"),
                pytest_html.extras.text(network, "network"),
                pytest_html.extras.text(bridge, "bridge"),
            ]
```

When pytest-html is configured, every failure produces a single HTML page with screenshot, three log streams, and the assertion traceback. For terminal-only runs, the same captures get written to `pytest_artifacts/<test_id>/`.

## 7. Pytest Fixtures

| Fixture | Scope | Returns | Cleanup |
|---|---|---|---|
| `wimi_config` | session | `TestConfig` resolved from env + pytest CLI flags (`--wimi-headed`, `--wimi-keep-app-data`) | none |
| `wimi_master_db` | session | `MasterDatabase` rooted at `app_data_test/`, created once and reused | drops `app_data_test/` at session end (configurable) |
| `test_user` | function | Fresh `TestUser` (no seeded data) | `TestUser.drop()` — removes user row and DB file |
| `seeded_user` | function | Factory: `seeded_user("usmle_step1_outline")` returns `TestUser` with seeder applied | same as `test_user` |
| `wimi_session` | function | Started `WimiTestSession` bound to `test_user` | `session.stop()` — kills subprocess, drops user, flushes captures |
| `console_log` | function | Live `ConsoleCapture` view (handle, owned by session) | none |
| `network_log` | function | Live `NetworkCapture` view | none |
| `bridge_log` | function | Live `BridgeCapture` view | none |
| `screenshot_on_failure` | function (autouse) | None — hooks `pytest_runtest_makereport` | none |
| `wimi_page` | function | Convenience: `wimi_session.page` | delegated |

**Scope rationale.** Function scope by default — class-scope opt-in deferred. `wimi_master_db` is session-scoped because creating the master DB and the `app_data_test/` directory is non-trivial; per-user isolation within is sufficient.

## 8. MCP Facade Structure

The `wimi-test` server is a thin adapter, not a parallel implementation. Each tool is essentially:

```python
def click(role=None, name=None, testid=None, css=None) -> dict:
    session = registry.get()
    session.page.locator(role=role, name=name, testid=testid, css=css).click()
    return {"ok": True, "captures": adapters.recent(session.captures)}
```

### Registry

`SessionRegistry` holds at most one active `WimiTestSession`. Rationale: Claude conversations are inherently single-threaded interactive sessions. Allowing multiple concurrent sessions invites subprocess port conflicts and ambiguous "which session do you mean?" errors. The registry tracks an idle timer (default 10 minutes) and auto-ends abandoned sessions on the next tool call.

### Tool ↔ library mapping

Every MCP tool is a 1-call shim:

| MCP tool | Library call |
|---|---|
| `start_session(scenario, seed=None)` | `registry.start(scenario=..., seed=...)` |
| `end_session()` | `registry.end()` |
| `navigate_to(route)` | `registry.get().page.goto(route)` |
| `click(role?, name?, testid?, css?)` | `registry.get().page.locator(...).click()` |
| `fill(value, ...)` | `registry.get().page.locator(...).fill(value)` |
| `screenshot(full_page=False)` | `registry.get().page.screenshot(full_page=...)` (returned as base64) |
| `wait_for(role?, name?, testid?, css?)` | `registry.get().page.locator(...).expect_visible()` |
| `get_console_log(level_min, since_ts)` | `adapters.console(registry.get().captures.console.snapshot(...))` |
| `get_network_log(url_substr?, since_ts)` | `adapters.network(registry.get().captures.network.snapshot(...))` |
| `get_bridge_log(method_substr?, since_ts)` | `adapters.bridge(registry.get().captures.bridge.snapshot(...))` |
| `eval_js(expression)` | `registry.get().page.eval_js(expression)` (gated by `TestConfig.allow_eval_js`, default `True`) |
| `dump_dom()` | `registry.get().page.eval_js("document.documentElement.outerHTML")` |

### Threading

Three threads exist; the bridge is small and lives in one place.

1. **MCP server thread** — FastMCP's asyncio loop. Tools are `async def`. Receives JSON-RPC, returns JSON.
2. **CDP/test-orchestration thread** — single dedicated worker thread owned by `SessionRegistry`. All pychrome calls run here (originally Playwright sync API calls; see `PYCHROME_MIGRATION.md` §5.5). Created at first `start_session`, joined on `end_session`. Tools dispatch via `asyncio.to_thread` (wrapped by `_internal/async_bridge.run_on_session_thread`).
3. **WIMI Qt UI thread** — inside the WIMI subprocess, not our process. We talk to it only via CDP; no direct synchronization on our side.

**Synchronization rule:** only the registry's worker thread touches the pychrome `Tab` (or any CDP-bound object). MCP async handlers never call pychrome directly. Pytest doesn't need this bridge — it runs single-threaded.

### Failure surfaces

Library exceptions (`LocatorAmbiguous`, `AttachTimeout`) are caught at the tool boundary by `adapters.exception_to_dict` and returned as structured `{"ok": false, "error": {...}, "captures": {...}}` payloads, so Claude can react without seeing Python tracebacks. Captures are *always* attached on failure responses.

## 9. Configuration (`wimi_test/config.py`)

```python
@dataclass(frozen=True)
class TestConfig:
    headed: bool = False                          # show WIMI window during tests
    cdp_port_range: tuple[int, int] = (12000, 12100)
    app_data_dir: Path = Path("app_data_test")
    console_buffer_size: int = 10_000
    network_buffer_size: int = 5_000
    bridge_buffer_size: int = 2_000
    fail_on_console_error: bool = False           # promote any console.error to test failure
    fail_on_uncaught_exception: bool = True       # JS uncaught exceptions always fail
    network_url_filter: Callable[[str], bool] = default_url_filter
    timeout_default_ms: int = 5_000
    timeout_attach_s: int = 30
    allow_eval_js: bool = True                    # gate for MCP eval_js tool
    test_user_isolation: Literal["session", "test"] = "session"  # see §10 Q3
```

Every knob has an env-var override (`WIMI_TEST_HEADED=1`, etc.) and a pytest CLI flag (`--wimi-headed`).

## 10. Resolved Design Decisions

The eight design decisions resolved during specification, recorded so future readers know what was decided and why.

| Q | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Session scope: function vs class | **Function scope only for v1** | Process-reuse is a premature optimization without measured pain. Dual-mode infrastructure adds significant complexity. Revisit if test-suite duration becomes intolerable. |
| 2 | `eval_js` exposure in MCP | **Unrestricted, gated behind `TestConfig.allow_eval_js=True` (default true)** | Test infra is local-only, opt-in, and runs against an isolated test user. Blast radius of a bad eval is small (kill subprocess, drop user). Discoverable in config. |
| 3 | Per-test app_data isolation | **Shared `app_data_test/`, drop `test_*` users between tests (option a)** | Simpler than per-test tempdirs. Crashed-run leaks are acceptable; a cleanup script can reap orphan `test_*` users. Revisit if parallel tests come up or maintenance pain emerges. |
| 4 | CDP attach signal | **stdout `TEST_MODE_READY:port=N`** | No timing race, no timeout tuning. Three lines of code in `main.py`. Polling kept as 30s fallback. |
| 5 | MCP packaging | **`--test-mcp-server` flag on `run_wimi.py`** | Mirrors existing `--mcp-server`. No separate packaging needed; `wimi-test` ships with WIMI. Splitting later is mechanical. |
| 6 | Bridge instrumentation | **Decorator (`@instrumented_slot` paired with `@pyqtSlot`)** | Explicit, greppable, resilient to PyQt internals changes. CI check enforces pairing. Audit cost is one-time. |
| 7 | QWebEnginePage subclass install | **Test-mode only** | Cleaner test/prod boundary. Always-on for dev bug reports is a separate explicit feature for later. |
| 8 | Async test support | **Sync-only for v1** | WIMI tests are conceptually sync. pytest-asyncio adds fixture-scope and error-reporting complexity for no test-author benefit. |

## 11. Implementation Roadmap

### Phase 1 — Foundation (smallest end-to-end slice)

**Goal:** prove the architecture works before building the broad surface.

1. `--test-mode` flag in `run_wimi.py` + `src/app/main.py`, with stdout ready signal.
2. `src/app/test_mode.py` — QWebEnginePage subclass + helpers.
3. `wimi_test/config.py`, `wimi_test/process.py` — subprocess management, port pick, ready-signal parsing.
4. **One smoke test:** launch WIMI in test mode → attach via CDP → navigate to dashboard → screenshot → kill.

If that scenario passes, the whole stack works.

### Phase 2 — Library core

5. `wimi_test/session.py`, `wimi_test/page.py`, `wimi_test/locator.py` — primary API.
6. `wimi_test/db/test_user.py`, `wimi_test/db/seeders.py` — DB isolation + seeders.
7. `wimi_test/fixtures/core.py` — pytest fixtures.
8. **Three pytest scenarios** that pass:
   - `test_smoke_create_user_and_log_out`
   - `test_create_entry_and_assert_db_row`
   - `test_browser_shows_seeded_entries`

### Phase 3 — Capture pipeline

9. `wimi_test/capture/console.py`, `network.py`, `bundle.py` — CDP-side capture via pychrome listeners (originally Playwright `page.on(...)`; see `PYCHROME_MIGRATION.md`).
10. `src/app/bridge_test_instrumentation.py` — decorator + scripts/check_instrumented_slots.py CI check.
11. Decorator audit: pair `@instrumented_slot` to every `@pyqtSlot` in `src/app/bridge_domains/`.
12. `wimi_test/capture/bridge.py` — reads instrumented buffer.
13. `wimi_test/fixtures/capture.py` — autouse `screenshot_on_failure`.

### Phase 4 — UI testid migration

14. Implement `data-testid` additions per `docs/testing/UI_AUDIT.md`, page by page.
15. Order: `question_entry.html` → `tree_editor.html` → `entry_browser.html` → `exam_wizard.html` → others.
16. Add D3 chart testids inline in `sunburst_chart.js`, `heatmap_chart.js`, `dimension_heatmap.js`.

### Phase 5 — MCP facade

17. `src/wimi_test_mcp/server.py`, `registry.py`, `adapters.py`, `tools/*.py`.
18. `--test-mcp-server` flag in `run_wimi.py`.
19. Add `wimi-test` server to local `.mcp.json` for Claude Code use.
20. Validate by asking Claude to run a scenario interactively.

### Phase 6 — CI + scenario library

21. Headless CI integration (offscreen Qt platform).
22. Build out scenario library — start with recently-fixed bugs from `docs/bugs/bugs.md`.
23. Visual regression / snapshot diffing if needed.

Each phase is independently shippable. Phase 1 is the highest-risk gate.

## 12. Open Questions (still undecided)

These items are flagged but defer to implementation-time judgment.

- **Decorator audit ordering.** Should we instrument all 19 bridge mixins in one PR, or one mixin per PR? One-PR is reviewable but large; per-mixin is safer but takes time. Recommend: one PR per "logical group" (e.g., entries+sessions together, analytics+goals together). Roughly 4-5 PRs.
- **CI environment for QtWebEngine.** Linux runners need `QT_QPA_PLATFORM=offscreen` plus EGL libraries. macOS and Windows runners need a real display or virtual display setup. Test on real CI before assuming it works.
- **Visual regression baseline storage.** If/when snapshot diffing lands, where do baseline screenshots live? Dedicated branch? Git LFS? `tests/baselines/`? Defer until needed.
- **`pytest_artifacts/` retention.** Tests that don't fail produce no artifacts. Failed-test artifacts accumulate over time. Auto-cleanup policy or manual?
- **Async-test escape hatch.** If a test genuinely needs async (e.g., to wait for two events concurrently), do we add minimal `pytest-asyncio` support later? Probably yes when the need is concrete.

## 13. References

- `docs/testing/UI_AUDIT.md` — locator strategy and complete `data-testid` scheme across all 11 HTML pages
- `docs/planning/POLYHIERARCHY_MIGRATION.md` — companion migration affecting the tree editor and analytics queries
- `docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` — companion plan with shared scope concerns
- `docs/planning/PYCHROME_MIGRATION.md` — the Playwright→pychrome migration plan and rationale (supersedes parts of §4, §6, §8)
- pychrome (CDP client): https://pypi.org/project/pychrome/
- Chrome DevTools Protocol: https://chromedevtools.github.io/devtools-protocol/
- QtWebEngine remote debugging: https://doc.qt.io/qt-6/qtwebengine-debugging.html
- pytest hookspec for `pytest_runtest_makereport`: https://docs.pytest.org/en/stable/reference/reference.html
- (Originally referenced) Playwright Python sync API: https://playwright.dev/python/docs/api/class-playwright — kept for historical context; the migration moved off this dependency.

## 14. File Inventory (touched by this plan)

**New files**

- `wimi_test/__init__.py` and 17 sibling modules (per §3 directory tree)
- `src/app/test_mode.py`
- `src/app/bridge_test_instrumentation.py`
- `src/wimi_test_mcp/server.py` and 6 sibling modules (per §3 directory tree)
- `scripts/check_instrumented_slots.py` — CI check script
- `tests/wimi_test/test_*.py` — pytest scenarios (built in Phase 2)

**Modified files**

- `run_wimi.py` — `--test-mode`, `--debug-port`, `--app-data-dir`, `--test-mcp-server` flags
- `src/app/main.py` — flag flow, env var setup, subclass install, ready-signal emit, demo-user skip
- `src/app/bridge_domains/*.py` (all 19 mixins) — `@instrumented_slot` decorator paired with each `@pyqtSlot`
- `src/web/html/*.html` (all 11 pages) — `data-testid` additions per `UI_AUDIT.md`
- `src/web/js/*.js` (render-time additions) — `data-testid` insertion in dynamic-element render functions per `UI_AUDIT.md`
- `.mcp.json` — `wimi-test` server entry (Phase 5)
- `pyproject.toml` (or equivalent) — `pychrome>=0.2.4` dev dependency (originally specced as `playwright`; see `PYCHROME_MIGRATION.md` §4 and §6), `wimi_test` pytest plugin entry

**Estimated scope**

- ~24 new files in `wimi_test/` and `src/wimi_test_mcp/`
- ~190 `@pyqtSlot` decorator additions across 19 bridge mixins
- ~11 HTML pages + ~15 JS modules requiring `data-testid` additions
- ~2-3 new tests per phase (Phase 2 baseline, expanding through Phase 6)

Total estimated effort: 6-8 weeks of focused work, but each phase is independently shippable, so usable infrastructure is online after Phase 2 (~2 weeks).
