# pychrome Migration: Replacing Playwright in `wimi_test`

**Status:** Proposed (post-spike, pre-implementation)
**Created:** 2026-05-07
**Companion docs:** `docs/planning/TEST_INFRASTRUCTURE.md` (the original plan; this migration revises §6 and §8), `docs/planning/TEST_INFRASTRUCTURE_TASKS.md` (the task tracker; new tasks appended at the end).

## 1. Background

The original `TEST_INFRASTRUCTURE.md` design assumed **Playwright over Chrome DevTools Protocol** would drive WIMI's `QWebEngineView` transparently. It doesn't. Playwright's `chromium.connect_over_cdp` issues `Browser.setDownloadBehavior` during connection setup, and Qt's CDP server returns:

```
Protocol error (Browser.setDownloadBehavior):
Browser context management is not supported.
```

Qt 6's QtWebEngine implements a **subset** of CDP — `Page`, `Runtime`, `DOM`, `Network`, `Input` — but does not implement the `Browser` domain methods Playwright requires. There is no opt-out flag in Playwright; the call is hardcoded into the connection setup. Result: `WimiTestSession.start()` always fails after `wait_for_ready()` succeeds, taking the entire MCP facade and pytest fixture chain down with it. The infrastructure was correctly built but on a foundation that doesn't load.

A spike of `pychrome` (a thin CDP wrapper) confirmed:

- ✅ Connects to Qt's CDP without issuing `Browser.*` setup calls.
- ✅ `Page.navigate`, `Page.captureScreenshot` (219 KB PNG), `Runtime.evaluate`, `Network.enable`, `Input.dispatchMouseEvent` all work.
- ✅ `qt.webChannelTransport` and the `QWebChannel` constructor are visible from CDP, so the bridge layer is reachable.
- ⚠️ `window._wimiApi` was `undefined` at the moment of check, despite the loader scripts being present. Most likely an async-handshake timing issue, not a fundamental block.

This document is the migration plan to replace Playwright with pychrome across the test infrastructure with minimum disruption.

## 2. Goals & Non-Goals

**Goals**

- Restore end-to-end functionality of `WimiTestSession.start()` and the entire MCP facade.
- Keep the public API of `WimiPage`, `WimiLocator`, `WimiTestSession`, the pytest fixtures, and the 13 MCP tools **unchanged** — every consumer of the library should be untouched.
- Build a minimal, debuggable locator/auto-wait layer that we own (rather than depending on a brittle external dependency that may break against Qt again).
- Keep the capture pipeline (`ConsoleCapture`, `NetworkCapture`, `BridgeCapture`) intact; only the underlying event subscription changes.

**Non-Goals**

- No public-API changes. Existing tests, fixtures, and MCP tool contracts stay identical.
- No replacement of WimiProcess, the test_mode flag flow, or anything below the Playwright layer. The WIMI-side instrumentation (`@instrumented_slot`, ready signal, etc.) is unaffected.
- No support for full-Chromium features Playwright offers (download interception, multiple contexts, web-first assertions). We only need what Qt's CDP subset exposes.
- No rebuild on raw websockets unless pychrome itself proves inadequate during the migration.

## 3. The Constraint That Drove This

QtWebEngine's CDP subset, observed from the spike:

| Domain | Status | Notes |
|---|---|---|
| `Page` | ✅ Works | navigate, captureScreenshot, enable |
| `Runtime` | ✅ Works | evaluate (sync + async), enable |
| `DOM` | ✅ Works | document, document.documentElement.outerHTML |
| `Network` | ✅ Works | enable, requestWillBeSent, responseReceived, loadingFailed |
| `Input` | ✅ Works | dispatchMouseEvent, dispatchKeyEvent (untested in spike but documented in Qt) |
| `Browser` | ❌ Not supported | `Browser.setDownloadBehavior`, `Browser.getVersion` partial. Playwright's connection setup hits this immediately. |
| `Target` | ❓ Partial | `Target.attachToTarget` works for `target_id` resolution but full target management (creating new contexts) does not. |
| `Storage`, `ServiceWorker`, etc. | Unknown / unneeded | Not in scope. |

Anything in the migration that touches `Browser.*`, `Target` context creation, or download interception will need to be redesigned or skipped.

## 4. Affected Files

Files that need changes, grouped by risk:

### High-impact (architectural)
- **`wimi_test/page.py`** — `WimiPage` is built on `playwright.sync_api.Page`. Swap to a pychrome-backed implementation.
- **`wimi_test/locator.py`** — `WimiLocator` wraps `playwright.sync_api.Locator`. Replace with our own selector + auto-wait built on `Runtime.evaluate`.
- **`wimi_test/session.py`** — Replaces the `sync_playwright().start()` and `chromium.connect_over_cdp(...)` block with pychrome `Browser(url=...)`. The capture wiring switches from Playwright `page.on(...)` to pychrome event listeners.

### Medium-impact (capture pipeline)
- **`wimi_test/capture/console.py`** — Subscribes to `Runtime.consoleAPICalled` and `Runtime.exceptionThrown` via pychrome's `set_listener`. Slightly different API than Playwright's `page.on("console", ...)`.
- **`wimi_test/capture/network.py`** — Same swap: subscribe via pychrome's `set_listener("Network.requestWillBeSent", ...)` etc.
- **`wimi_test/capture/bridge.py`** — Polls `getTestModeBridgeCalls` via `tab.Runtime.evaluate` instead of `page.evaluate`. Minor.

### Low-impact (drop-ins)
- **`src/wimi_test_mcp/tools/interaction.py`** — Already calls `session.page.locator(...).click()`. As long as `WimiLocator.click()` keeps its signature, no change.
- **`src/wimi_test_mcp/tools/navigation.py`** — Same; uses `session.page.goto(route)`.
- **`src/wimi_test_mcp/tools/inspection.py`** — `dump_dom` uses `session.page.eval_js(...)`; signature preserved.

### Touched only for dependency declarations
- **`requirements-prod.txt` / `requirements-dev.txt`** (whichever lists test deps): drop `playwright`, add `pychrome>=0.2.4`.
- **`docs/testing/CI_SETUP.md`**: remove the "playwright is installed but skip browser download" note; replace with "pychrome installs cleanly with no extra step".

### Tests that need updating
- **`tests/wimi_test/test_smoke_phase1.py`** — Uses raw Playwright via `connect_over_cdp`. Rewrite to use pychrome directly (the test predates the library).
- **`tests/wimi_test/test_smoke_phase2.py`** — Uses fixtures only; no direct Playwright calls. Should pass without changes once the library underneath works.
- **`tests/wimi_test/test_capture.py`** — Same; fixture-only.
- **`tests/wimi_test_mcp/test_facade_smoke.py`** — Uses MCP client; unaffected.
- **`tests/wimi_test/scenarios/*.py`** — Two regression scenarios; fixture-only.

Total estimated diff: **~800–1,200 lines changed**, concentrated in 6 files. Roughly half is in `page.py` and `locator.py` rebuilds.

## 5. New Architecture

### 5.1 Connection layer

```python
# wimi_test/page.py (sketch)
import pychrome

class WimiBrowser:
    """Wraps pychrome.Browser — owns the WS connection lifecycle."""

    def __init__(self, port: int):
        self._client = pychrome.Browser(url=f"http://127.0.0.1:{port}")

    def primary_tab(self) -> "WimiTab":
        """Pick the page-type tab. WIMI exposes 1–2 tabs; we want the
        first 'page' type with WIMI's loader scripts present."""
        for t in self._client.list_tab():
            t.start()
            r = t.Runtime.evaluate(expression="document.scripts.length > 0")
            if r.get("result", {}).get("value"):
                return WimiTab(t)
            t.stop()
        raise WimiTestError("No usable WIMI tab found")
```

### 5.2 Page wrapper

`WimiPage` keeps the same public surface but delegates to a pychrome `Tab`:

```python
class WimiPage:
    def __init__(self, tab: "pychrome.Tab", *, app_root: Path, config: TestConfig):
        self._tab = tab
        self._app_root = app_root
        self._config = config

    def goto(self, route: str, *, wait_for_bridge: bool = True) -> None:
        url = resolve(route, self._app_root)
        self._tab.Page.navigate(url=url)
        if wait_for_bridge:
            self._wait_for_wimi_api()

    def _wait_for_wimi_api(self, timeout_ms: int = 5000) -> None:
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            r = self._tab.Runtime.evaluate(
                expression="typeof window._wimiApi"
            )
            if r.get("result", {}).get("value") == "object":
                return
            time.sleep(0.1)
        raise WimiTestError("window._wimiApi never became available")

    def locator(self, *, role=None, name=None, testid=None, css=None) -> "WimiLocator":
        return build_locator(self._tab, role=role, name=name, testid=testid, css=css)

    def screenshot(self, path=None, *, full_page=False) -> bytes:
        kwargs = {"format": "png"}
        if full_page:
            # Qt CDP supports clip; full-page would need viewport math.
            # For v1, full_page param is accepted but treated as viewport.
            # TODO: implement full_page via DOM.getBoxModel + multiple captures.
            pass
        r = self._tab.Page.captureScreenshot(**kwargs)
        b = base64.b64decode(r.get("data", ""))
        if path:
            Path(path).write_bytes(b)
        return b

    def eval_js(self, expression: str) -> object:
        if not self._config.allow_eval_js:
            raise WimiTestError("eval_js is disabled by TestConfig.allow_eval_js=False")
        r = self._tab.Runtime.evaluate(expression=expression, returnByValue=True)
        if r.get("exceptionDetails"):
            raise WimiTestError(f"eval_js error: {r['exceptionDetails'].get('text')}")
        return r.get("result", {}).get("value")
```

### 5.3 Locator engine

Replace Playwright's locator with a small JS-backed matcher. Each strategy resolves to a JS expression that returns a unique element handle:

```python
class WimiLocator:
    def __init__(self, tab: "pychrome.Tab", strategy: LocatorStrategy, selector_js: str):
        self._tab = tab
        self._strategy = strategy
        self._js = selector_js   # a JS expression that returns the element

    def click(self, *, timeout_ms: int | None = None) -> None:
        timeout_ms = timeout_ms or 5000
        deadline = time.time() + timeout_ms / 1000
        # Auto-wait: poll until visible+enabled
        while time.time() < deadline:
            r = self._tab.Runtime.evaluate(expression=f"""
                (() => {{
                    const el = {self._js};
                    if (!el) return {{ ready: false, reason: "not_found" }};
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0)
                        return {{ ready: false, reason: "not_visible" }};
                    if (el.disabled)
                        return {{ ready: false, reason: "disabled" }};
                    return {{ ready: true, x: rect.left + rect.width/2, y: rect.top + rect.height/2 }};
                }})()
            """, returnByValue=True)
            v = r.get("result", {}).get("value", {})
            if v.get("ready"):
                # Dispatch a click via Input domain (more reliable than el.click())
                x, y = v["x"], v["y"]
                self._tab.Input.dispatchMouseEvent(type="mousePressed", x=x, y=y, button="left", clickCount=1)
                self._tab.Input.dispatchMouseEvent(type="mouseReleased", x=x, y=y, button="left", clickCount=1)
                return
            time.sleep(0.05)
        raise AssertionFailureWithCapture(
            f"Locator {self._strategy.value} did not become clickable within {timeout_ms}ms",
            captures=None,
        )
```

The selector compiler:

```python
def build_locator(tab, *, role=None, name=None, testid=None, css=None) -> WimiLocator:
    if testid:
        js = f"document.querySelector('[data-testid=\"{escape(testid)}\"]')"
        return WimiLocator(tab, LocatorStrategy.TESTID, js)
    if css:
        js = f"document.querySelector(`{escape(css)}`)"
        return WimiLocator(tab, LocatorStrategy.CSS, js)
    if role and name:
        # Build a small JS query that searches for elements with the right
        # ARIA role and matching accessible name. Accessible-name resolution
        # is non-trivial; for v1 we support: button text content, input
        # associated <label>, and aria-label. Document the limitations.
        js = f"""
            Array.from(document.querySelectorAll('*')).find(el => {{
                const r = el.getAttribute('role') || el.tagName.toLowerCase();
                if (r !== '{role}') return false;
                const name = (
                    el.getAttribute('aria-label') ||
                    el.textContent?.trim() ||
                    el.value ||
                    ''
                );
                return name === '{escape(name)}';
            }})
        """
        return WimiLocator(tab, LocatorStrategy.ROLE_AND_NAME, js)
    raise ValueError("Provide exactly one of (role+name), testid, or css")
```

The role+name resolution is **less complete** than Playwright's. For v1, we accept this and rely on testids for everything that doesn't fit the simple cases. Phase 4's testid migration ensures this is workable.

### 5.4 Capture pipeline

pychrome exposes events via `tab.set_listener(event_name, handler)`. The translation is mechanical:

```python
# Before (Playwright):
pw_page.on("console", self._on_console)

# After (pychrome):
self._tab = tab
self._tab.set_listener("Runtime.consoleAPICalled", self._on_console)
self._tab.set_listener("Runtime.exceptionThrown", self._on_pageerror)

# Event payload differs slightly. pychrome passes kwargs:
def _on_console(self, type, args, **kw):
    text = " ".join(self._stringify(a) for a in args)
    self.buffer.append(ConsoleEntry(timestamp=time.time(), level=type, text=text, location=None))
```

Same pattern for `NetworkCapture`: `tab.set_listener("Network.requestWillBeSent", ...)`, etc. The `Network.enable` call happens at attach time.

### 5.5 Session wiring

```python
# wimi_test/session.py — relevant section
from wimi_test.page import WimiBrowser

def start(self) -> None:
    # ... existing code: master_db, test_user, WimiProcess.spawn, wait_for_ready ...

    self._browser_wrapper = WimiBrowser(port=self._proc.picked_port)
    tab = self._browser_wrapper.primary_tab()
    self._page = WimiPage(tab._tab, app_root=Path(...), config=self.config)

    # captures attach to the same tab
    console = ConsoleCapture(...)
    console.attach(tab._tab)
    network = NetworkCapture(...)
    network.attach(tab._tab)
    bridge = BridgeCapture(...)
    bridge.attach(tab._tab)
    self._captures = CaptureBundle(console=console, network=network, bridge=bridge)

    self._start_ts = time.time()
    self._started = True
```

The `SessionThreadExecutor` thread-affinity rule **stays**. pychrome's `Tab` object is also not safe to share across threads — the dedicated worker still owns it.

## 6. Migration Sequence

Eight tasks, dispatched in three waves:

### Wave 1 — Foundation (parallel)
- **M1.1 Spike → spec**: turn the working spike into `wimi_test/_internal/cdp_client.py` — a thin pychrome wrapper that hides pychrome's quirks (the noisy `_recv_loop` JSON warnings, the two-tab disambiguation, the start/stop lifecycle). Single seam everything else uses.
- **M1.2 Locator engine**: rewrite `wimi_test/locator.py` to use the JS-backed selector pattern from §5.3. Includes the existing 17-test mock suite, updated to mock pychrome instead of Playwright.

### Wave 2 — Page + captures (parallel after Wave 1)
- **M2.1 Rewrite `WimiPage`**: replaces Playwright internals with the pychrome tab from M1.1. Public API unchanged.
- **M2.2 Rewrite `ConsoleCapture`**: subscribes to `Runtime.consoleAPICalled` / `Runtime.exceptionThrown`. Output dataclass shape preserved.
- **M2.3 Rewrite `NetworkCapture`**: subscribes via pychrome's `set_listener`. Same `NetworkEvent` shape.
- **M2.4 Rewrite `BridgeCapture`**: polls via `tab.Runtime.evaluate(...)` instead of Playwright's `page.evaluate`.

### Wave 3 — Session + tests
- **M3.1 Rewrite `WimiTestSession.start()`**: swap the Playwright block for `WimiBrowser` + tab acquisition. Cleanup path mirrors current `stop()`.
- **M3.2 Rewrite Phase 1 smoke test**: `tests/wimi_test/test_smoke_phase1.py` already uses raw Playwright; convert to pychrome.
- **M3.3 Verify Phase 2/3/MCP smoke tests**: should run unchanged. Live-execute each and triage any breakage.
- **M3.4 Update CI workflow + docs**: drop the playwright install line; replace with `pip install pychrome`. Update `CI_SETUP.md`.
- **M3.5 Drop Playwright from requirements**: only after M3.3 passes end-to-end.

Each task gets a dedicated commit. Each wave gates the next.

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **`window._wimiApi` doesn't appear under CDP**, even with proper waits | Medium | Critical | Investigate as part of M2.1 — early. If the bridge truly doesn't expose to CDP, fall back to: (a) drive UI via raw DOM events, (b) poll the JS-side bridge call buffer via Runtime.evaluate to side-step QWebChannel. M2.1 must validate before we sink work into it. |
| pychrome's noisy `_recv_loop` JSON warnings drown out real errors | High | Low | Wrap pychrome in `wimi_test/_internal/cdp_client.py` and silence the noise via custom `logging` filter. |
| pychrome's role+name resolution misses elements Playwright would have caught | Medium | Medium | Accept v1 limitation; document in `UI_AUDIT.md` that reliance on testids is now even more important. Add a `data-testid` to anything that fails the simple role+name JS query. |
| Two-tab issue: which is the "real" page? | Low | Low | The first tab with `document.scripts.length > 0` is the WIMI page. Document and gate on that. |
| pychrome 0.2.4 is unmaintained (last release 2018) | Medium | High long-term | Add a fallback plan in this doc: if pychrome breaks against future Qt, switch to raw `websockets` + json (which the spike effectively used). The pychrome surface area we use is small (~5 methods), so the swap is mechanical. |
| Async pattern collision with `SessionThreadExecutor` | Low | Medium | pychrome is sync; same threading rules as Playwright. The executor pattern stays. |
| Auto-wait polling hammers CPU at 50ms intervals | Low | Low | Configurable; default to 100ms. |

## 8. Open Questions

1. **Is `window._wimiApi` actually reachable from CDP under proper async wait?** The spike checked too early; we don't yet know if it's a timing issue or a fundamental Qt/CDP barrier. **M2.1 must establish this in the first hour.** If it isn't, the migration plan needs to add a "drive WIMI without `_wimiApi`" sub-track.
2. **Headless support.** Qt's offscreen platform (`QT_QPA_PLATFORM=offscreen`) is set in CI. Does Qt still expose CDP under offscreen? Spike from interactive — we don't know. Test in M3.4.
3. **Multi-process WIMI cleanup.** When pychrome disconnects via `Tab.stop()`, does the QtWebEngineProcess child die cleanly, or do we accumulate zombies? `WimiProcess.terminate()` already kills the child process group; verify it covers the pychrome side.
4. **Locator escape sequences in JS strings.** Naïve f-string interpolation of `name` / `selector` is vulnerable to test authors writing `name="Save'); delete everything; ('"`. v1 ships with simple escaping (replace `'`/`"`/backticks); revisit if it causes test author friction.
5. **DOM API for `dump_dom`.** Currently uses `Runtime.evaluate("document.documentElement.outerHTML")`. pychrome's `DOM.getDocument` + `DOM.getOuterHTML` is more correct but more verbose. Stick with Runtime for v1.

## 9. Test Plan

**Pre-migration baseline**: every test currently fails at `WimiTestSession.start()` because of the Playwright/Qt incompatibility. The migration's success criterion is: each test that passed at the import-only level should now pass at runtime.

**Post-Wave 1**: M1.2's locator unit tests pass (17 mocked tests).

**Post-Wave 2**: a manual smoke — fresh-Python `WimiTestSession.__enter__` succeeds, `session.page.goto("dashboard")` returns, `session.page.screenshot()` returns non-empty PNG bytes. Build this as `tests/wimi_test/test_pychrome_smoke.py` (new). The existing `test_smoke_phase1.py` is rewritten in M3.2.

**Post-Wave 3**:
- `pytest tests/wimi_test/test_smoke_phase1.py` passes.
- `pytest tests/wimi_test/test_smoke_phase2.py` passes (3 scenarios).
- `pytest tests/wimi_test/test_capture.py` passes (3 scenarios).
- `pytest tests/wimi_test_mcp/test_facade_smoke.py` passes (2 scenarios).
- Manual: via the live `wimi-test` MCP server, `start_session(scenario="manual_test", seed="minimal")` returns success in <10s.

**Acceptance gate**: the manual MCP-server smoke succeeds. That was the original goal; it's the goal of the migration.

## 10. Rollback Plan

The migration replaces internals; the public API is preserved. If pychrome turns out to be inadequate mid-migration:

1. **Fallback to raw websockets + json.** pychrome's surface area we use is small. Replacing it with `websockets`-based code is ~150 lines. Same `_internal/cdp_client.py` shim absorbs the difference.
2. **Skip UI driving entirely.** Reframe the test infrastructure as bridge-layer tests + screenshots only. This was Option C from the post-spike discussion. We'd lose interaction tests but keep most of the value.
3. **Dual-driver approach.** Keep Playwright as a stub that always raises `WimiTestError("UI driving disabled")` and gate every interaction tool on a config flag. Painful but unblocks everything else.

The choice point is when M2.1 reports on `_wimiApi` reachability. If that's clean, we proceed; if it's a hard block, we fall back.

## 11. Estimated Effort

- Wave 1: 1 day (locator engine is the bulk).
- Wave 2: 1.5 days (one engineer-day on `WimiPage`; another half-day across the three captures).
- Wave 3: 1 day (sessions wiring, smoke test rewrite, CI doc, dependency drop).

**Total: ~3.5 days of focused work**, with the Wave 1 risk gate determining whether the rest happens.

## 12. References

- `docs/planning/TEST_INFRASTRUCTURE.md` — original architecture (sections 4, 6, 8 are obsoleted by this migration).
- `docs/planning/TEST_INFRASTRUCTURE_TASKS.md` — task tracker; new tasks `M1.1–M3.5` will be appended.
- `docs/testing/UI_AUDIT.md` — locator strategy preference (still applies; testids become even more important under pychrome's lighter role+name engine).
- pychrome on PyPI: <https://pypi.org/project/pychrome/>
- Qt's CDP support: documented behavior in QtWebEngine 6.x — implements `Page`, `Runtime`, `DOM`, `Network`, `Input`. No `Browser`, partial `Target`.
