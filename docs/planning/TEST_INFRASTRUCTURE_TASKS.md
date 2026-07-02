# Test Infrastructure Implementation: Task Breakdown

**Status:** Ready to dispatch
**Created:** 2026-05-07
**Companion docs:** `TEST_INFRASTRUCTURE.md` (the design — every task here references a section of that doc), `UI_AUDIT.md` (Phase 4 testid scheme)

This document decomposes `TEST_INFRASTRUCTURE.md` into discrete, dependency-tracked tasks suitable for individual agent assignment. Each task has a stable ID, explicit dependencies, scope, files touched, and acceptance criteria.

## How to use this document

1. **Pick tasks whose dependencies are all complete.** "Ready" tasks have no incomplete dependency.
2. **Independent ready tasks run in parallel** — dispatch them in a single message with multiple Agent tool calls.
3. **When a task completes,** verify the acceptance criteria, commit the changes (one commit per task by default), mark the task done in this file, and the next wave becomes available.
4. **Don't change task IDs.** They appear in commit messages and downstream task descriptions.

Each agent will be given:
- The task entry below (verbatim or paraphrased)
- A pointer to the relevant section of `TEST_INFRASTRUCTURE.md`
- The constraint to write only the files in scope and not adjacent code

## Dependency graph (high level)

```
                                 ┌────────────────────┐
                                 │ T1.1 errors.py     │ (leaf)
                                 └──────────┬─────────┘
                                            │
                                            ▼
                                 ┌────────────────────┐
                                 │ T1.2 config.py     │
                                 └──────────┬─────────┘
                                            │
                  ┌─────────────────────────┼────────────────────────┐
                  ▼                         ▼                        ▼
        ┌──────────────────┐    ┌──────────────────┐     ┌──────────────────┐
        │ T1.3 test_mode   │    │ T2.1 routes.py   │     │ T2.2 locator.py  │
        └────────┬─────────┘    └────────┬─────────┘     └────────┬─────────┘
                 │                       │                        │
                 ▼                       └────────┬───────────────┘
        ┌──────────────────┐                     ▼
        │ T1.4 main.py     │           ┌──────────────────┐
        │      flag flow   │           │ T2.3 page.py     │
        └────────┬─────────┘           └────────┬─────────┘
                 │                              │
                 ▼                              │
        ┌──────────────────┐                   │
        │ T1.5 process.py  │                   │
        └────────┬─────────┘                   │
                 │                              │
                 └──────────┬───────────────────┘
                            ▼
                  ┌────────────────────┐    + T2.4 test_user, T2.5 seeders, T2.6 assertions
                  │ T2.7 session.py    │  ◄─┘
                  └──────────┬─────────┘
                             ▼
                  ┌────────────────────┐
                  │ T2.8 fixtures      │
                  └──────────┬─────────┘
                             ▼
                  ┌────────────────────┐
                  │ T1.6/T2.9 smoke    │ ── Phase 1 + 2 gate
                  └────────────────────┘
                             │
       ┌─────────────────────┼─────────────────────┐
       ▼                     ▼                     ▼
   Phase 3 (capture)     Phase 4 (testids)    Phase 5 (MCP facade)
```

The full dependency map is in each task entry.

---

## Phase 1 — Foundation

Smallest end-to-end slice. Goal: launch WIMI in test mode, attach via CDP, screenshot, kill. If this works, the architecture is proven.

### T1.1 — `wimi_test/errors.py` (exception hierarchy)

- **Status:** Done — `3dcb8e4`
- **Dependencies:** none
- **Files (new):** `wimi_test/errors.py`
- **Files (modified):** none
- **Effort:** ~30 min
- **Suggested agent:** general-purpose

**Scope:** Define the exception hierarchy: `WimiTestError` (base), `ProcessSpawnError`, `AttachTimeout`, `LocatorAmbiguous`, `AssertionFailureWithCapture`. All other exceptions inherit from `WimiTestError`. `ProcessSpawnError` carries an `exit_code` attribute and `last_stdout` (last 100 lines). `AttachTimeout` carries the port and the elapsed seconds. `LocatorAmbiguous` carries the strategy used and a list of matched element descriptions. `AssertionFailureWithCapture` carries a reference to a `CaptureBundle` (forward type — use a string annotation).

**Acceptance criteria:**
- File exists, all five classes defined
- `__all__` exports the five public exceptions
- Type stubs only — no logic beyond `__init__` storing attributes
- Module docstring explains intent and references `TEST_INFRASTRUCTURE.md` §3

---

### T1.2 — `wimi_test/config.py` (TestConfig dataclass)

- **Status:** Done — `f775584`
- **Dependencies:** T1.1
- **Files (new):** `wimi_test/config.py`
- **Effort:** ~45 min

**Scope:** Implement `TestConfig` per `TEST_INFRASTRUCTURE.md` §9. Frozen dataclass with all knobs. Class method `TestConfig.resolve(cli_overrides=None)` reads env vars (`WIMI_TEST_HEADED`, `WIMI_TEST_APP_DATA_DIR`, `WIMI_TEST_DEBUG_PORT_RANGE`, etc.), falls back to defaults, and applies CLI overrides last. Provide a `default_url_filter` callable that rejects `file://` and `qrc://`.

**Acceptance criteria:**
- All fields from §9 present, frozen=True
- `resolve()` documented with the precedence order
- No imports from elsewhere in `wimi_test/` — leaf module

---

### T1.3 — `src/app/test_mode.py` (test-mode state and QWebEnginePage subclass)

- **Status:** Done — `2970709`
- **Dependencies:** T1.1
- **Files (new):** `src/app/test_mode.py`
- **Effort:** ~1.5 hr

**Scope:** Module-level state (`IS_ACTIVE: bool = False`, `DEBUG_PORT: int | None = None`, `APP_DATA_DIR: Path | None = None`). Define `TestModeQWebEnginePage(QWebEnginePage)` overriding `javaScriptConsoleMessage(level, message, line, source)` to append to a `collections.deque(maxlen=10000)` of `ConsoleEntry` namedtuples (timestamp, level_name, message, line, source). Provide `install_on_view(view: QWebEngineView) -> None`, `emit_ready_signal(port: int) -> None` (writes `TEST_MODE_READY:port=N\n` to stdout and flushes), `get_console_buffer() -> list[ConsoleEntry]`. Crash handler: register an `atexit` hook that, when `IS_ACTIVE`, dumps the console buffer to `<APP_DATA_DIR>/last_crash_console.json` if the exit code is non-zero.

**Acceptance criteria:**
- Subclass calls `super().javaScriptConsoleMessage(...)` after appending — preserves default behavior
- Module-level state mutation only via explicit setter helpers (don't expose raw assignment)
- `ConsoleEntry` is a `NamedTuple` or frozen dataclass

---

### T1.4 — Wire `--test-mode` CLI flag flow (run_wimi.py + src/app/main.py)

- **Status:** Done — `90432d9`
- **Dependencies:** T1.3
- **Files (modified):** `run_wimi.py`, `src/app/main.py`
- **Effort:** ~2 hr

**Scope:** Per `TEST_INFRASTRUCTURE.md` §5. Add CLI flags to `run_wimi.py`: `--test-mode`, `--debug-port`, `--app-data-dir`, `--test-mcp-server` (the last is a flag; its handler is added in Phase 5 — for now, raise `NotImplementedError`). Pass parsed args to `src/app/main.py`. In `main.py`, follow the §5 order-of-operations exactly: env vars set BEFORE `QApplication`, subclass installed after view creation, ready signal emitted after `bridgeReady`, demo-user setup skipped, F5 rebound to no-op. Free port selection via `socket.socket().bind((host, 0))`.

**Acceptance criteria:**
- `python run_wimi.py --test-mode` launches WIMI with CDP enabled
- `curl http://localhost:<port>/json/version` returns 200 within ~5s of the ready-signal line
- `--app-data-dir foo/` overrides correctly
- `--debug-port 0` is rejected (must be in range 12000-12100 if specified, or auto-pick)
- F12 dev tools still work
- No demo user is created in test mode

---

### T1.5 — `wimi_test/process.py` (WimiProcess subprocess management)

- **Status:** Done — `6527c32`
- **Dependencies:** T1.2, T1.4
- **Files (new):** `wimi_test/process.py`
- **Effort:** ~2.5 hr

**Scope:** `WimiProcess` class manages the WIMI subprocess lifecycle. Methods: `spawn(config: TestConfig) -> int` (returns picked port), `wait_for_ready(timeout_s: int) -> None` (parses stdout for `TEST_MODE_READY:port=N`), `terminate(grace_s: int = 5) -> None` (SIGTERM, then SIGKILL if grace expires), `is_alive() -> bool`, `last_stdout(n: int = 100) -> list[str]`. Spawning runs `python run_wimi.py --test-mode --debug-port=<port> --app-data-dir=<dir>`. On Windows, use `CREATE_NEW_PROCESS_GROUP` so SIGTERM works. Stdout is read line-by-line on a background thread to avoid deadlock; lines tagged with `TEST_MODE_READY` set a thread-safe event.

**Acceptance criteria:**
- `spawn()` returns within 30s or raises `AttachTimeout` (config-driven)
- `terminate()` is idempotent and always cleans up the subprocess (even after exceptions in the test)
- Polling fallback: if the ready signal isn't seen within 30s but the port is responsive, log a warning and proceed
- Cross-platform (Windows + macOS)

---

### T1.6 — Phase 1 smoke test

- **Status:** Done — `c45f2c3` (Phase 1 closed; runs locally pending live verification)
- **Dependencies:** T1.5
- **Files (new):** `tests/wimi_test/test_smoke_phase1.py`
- **Effort:** ~1 hr

**Scope:** Single test that uses `WimiProcess` directly (no library wrapper yet) plus the raw Playwright API to: spawn WIMI in test mode, attach CDP, navigate to dashboard, take a screenshot, terminate. Assert the screenshot is non-empty PNG bytes.

**Acceptance criteria:**
- Test passes locally on at least one of {Windows, macOS}
- Test fixture cleans up the subprocess even on assertion failure (use try/finally or a context manager)
- Saves the screenshot to `tests/wimi_test/artifacts/smoke_phase1.png` for visual confirmation
- Runs in <30s

---

## Phase 2 — Library core

After Phase 1 proves the foundation, build the primary API.

### T2.1 — `wimi_test/routes.py` (route registry)

- **Status:** Done — `1824180`
- **Dependencies:** none
- **Files (new):** `wimi_test/routes.py`
- **Effort:** ~30 min

**Scope:** Define `RouteTable: dict[str, str]` mapping logical names to file URLs. Routes: `dashboard` → `index.html`, `entry-form` → `question_entry.html`, `analytics` → `analytics_dashboard.html`, `entry-browser` → `entry_browser.html`, `entry-detail` → `entry_detail.html`, `tree-editor` → `tree_editor.html`, `session-setup` → `session_setup.html`, `subject-deep-dive` → `subject_deep_dive.html`, `settings` → `settings.html`, `exam-wizard` → `wizards/exam_wizard.html`, `error-viewer` → `error-viewer.html`. Provide `resolve(route: str, app_root: Path) -> str` that returns a `file://` URL.

**Acceptance criteria:**
- All 11 routes mapped
- Function rejects unknown routes with a clear error
- Pure data + one helper function — no other imports

---

### T2.2 — `wimi_test/locator.py` (WimiLocator)

- **Status:** Done — `492144b`
- **Dependencies:** T1.1
- **Files (new):** `wimi_test/locator.py`
- **Effort:** ~3 hr

**Scope:** Per `TEST_INFRASTRUCTURE.md` §4. `WimiLocator` wraps `playwright.sync_api.Locator`. Constructor takes the underlying Playwright locator and a `LocatorStrategy` enum (`ROLE_AND_NAME`, `TESTID`, `CSS`). Public methods: `click()`, `fill(value)`, `expect_visible()`, `text()`, `attribute(name)`. All accept optional `timeout_ms`. Auto-waiting is the default — calls `locator.wait_for(state="visible")` before action. Raises `LocatorAmbiguous` from `errors.py` if more than one element matches when uniqueness is required.

**Acceptance criteria:**
- Locator factory function `build_locator(pw_page, *, role=None, name=None, testid=None, css=None) -> WimiLocator` enforces "exactly one of (role+name) / testid / css"
- Auto-wait is non-overridable for `click`/`fill` (always wait); overridable for `text()`/`attribute()` (read can return None)
- All public methods type-hinted
- Unit tests in `tests/wimi_test/test_locator.py` covering the three resolution strategies (mock the Playwright locator)

---

### T2.3 — `wimi_test/page.py` (WimiPage)

- **Status:** Done — `e9c4e85`
- **Dependencies:** T2.1, T2.2
- **Files (new):** `wimi_test/page.py`
- **Effort:** ~2 hr

**Scope:** Per `TEST_INFRASTRUCTURE.md` §4. `WimiPage` wraps `playwright.sync_api.Page`. Methods: `goto(route)` (resolves via `routes.py`, navigates, waits for `bridgeReady` if `wait_for_bridge=True`), `locator(...)` (delegates to `build_locator`), `screenshot(path=None, full_page=False)`, `eval_js(expression)` (gated by `config.allow_eval_js`), `wait_for_bridge_call(method, timeout_ms)` (uses `BridgeCapture` once available; for now, raise NotImplementedError with a comment that Phase 3 fills it in).

**Acceptance criteria:**
- `goto()` waits for `window._wimiApi !== undefined` as the bridge-ready signal (or whatever the existing convention is — verify via `_loader.js`)
- `screenshot()` returns PNG bytes; writes to `path` if given
- `eval_js` raises `WimiTestError` if `config.allow_eval_js=False`

---

### T2.4 — `wimi_test/db/test_user.py` (TestUser)

- **Status:** Done — `12fcd1c`
- **Dependencies:** T1.2
- **Files (new):** `wimi_test/db/__init__.py`, `wimi_test/db/test_user.py`
- **Effort:** ~2 hr

**Scope:** Per `TEST_INFRASTRUCTURE.md` §4. `TestUser` wraps `MasterDatabase.create_user()` from `src/database/master_db.py`. Constructor takes a `MasterDatabase` instance, scenario name, and run ID; computes username as `test_<scenario>_<runid>`. Property `db` returns the per-user `UserDatabase`. Method `seed(name, **kwargs)` looks up named seeders from T2.5 and applies them. Method `drop()` deletes the user row from the master DB and removes the `.db` file.

**Acceptance criteria:**
- Username collision raises a clear error (run-id should make this rare but possible)
- `drop()` is idempotent — calling twice doesn't error
- Uses the existing `MasterDatabase` and `UserDatabase` classes — no schema changes

---

### T2.5 — `wimi_test/db/seeders.py` (named seeder registry)

- **Status:** Done — `42ff316`
- **Dependencies:** T2.4
- **Files (new):** `wimi_test/db/seeders.py`
- **Effort:** ~2 hr

**Scope:** Define a registry of named seeder functions. Initial seeders: `seed_minimal()` (one exam, no entries — for smoke tests), `seed_usmle_step1_outline()` (parses `tests/fixtures/usmle_step1_outline.txt` and creates the subject hierarchy). Decorator-based registration: `@seeder("name")`. Lookup function `get_seeder(name) -> Callable`.

**Acceptance criteria:**
- Registry decoupled from `TestUser` (so seeders can be registered from anywhere)
- `seed_usmle_step1_outline()` reads from `tests/fixtures/usmle_step1_outline.txt` (the file already exists)
- Both seeders return the seeded `UserDatabase` for chaining

---

### T2.6 — `wimi_test/db/assertions.py` (DB-side assertion helpers)

- **Status:** Done — `e8c1fc5`
- **Dependencies:** T2.4
- **Files (new):** `wimi_test/db/assertions.py`
- **Effort:** ~1 hr

**Scope:** Pure functions for DB assertions: `assert_entry_count(db, expected, *, exam_context_id=None)`, `assert_subject_exists(db, name)`, `assert_session_completed(db, session_id)`. Each raises `AssertionFailureWithCapture` (with a None CaptureBundle for now; Phase 3 wires real captures).

**Acceptance criteria:**
- All helpers take a `UserDatabase` instance, not a session
- Error messages include the actual vs. expected values
- Pure leaf module — no imports from `wimi_test.session`

---

### T2.7 — `wimi_test/session.py` (WimiTestSession)

- **Status:** Done — `e7619f2` (captures property stubs `None`; T3.8 wires real captures)
- **Dependencies:** T1.5, T2.3, T2.4
- **Files (new):** `wimi_test/session.py`
- **Effort:** ~3 hr

**Scope:** Per `TEST_INFRASTRUCTURE.md` §4. The hub. `WimiTestSession.__init__(scenario, config=None)` stores config and prepares state. `start()` orchestrates: spawn process via T1.5, attach Playwright via CDP at the spawned port, create test user via T2.4, set `start_ts`. `stop(drop_user=True)` reverses each step in reverse order. Properties expose `page` (from Playwright), `user`, captures (placeholder for Phase 3 — return None for now). Implements `__enter__`/`__exit__`.

**Acceptance criteria:**
- `start()` is idempotent (calling twice raises if already started, doesn't double-spawn)
- `stop()` is always safe — handles partial-start failure (process spawned but page not attached, etc.)
- Subprocess is killed even on exceptions inside `start()` (cleanup in finally)

---

### T2.8 — `wimi_test/fixtures/core.py` and pytest plugin entry

- **Status:** Done — `8f004ea` + `779ce7e` (gitignore fix; `core.*` pattern was eating `core.py`)
- **Dependencies:** T2.7, T2.5
- **Files (new):** `wimi_test/fixtures/__init__.py`, `wimi_test/fixtures/core.py`, `pyproject.toml` (or equivalent — register pytest plugin)
- **Effort:** ~2 hr

**Scope:** Per `TEST_INFRASTRUCTURE.md` §7. Implement fixtures: `wimi_config` (session), `wimi_master_db` (session), `test_user` (function), `seeded_user` (function — factory pattern), `wimi_session` (function), `wimi_page` (function). Register the package as a pytest plugin via `pyproject.toml`'s `[project.entry-points."pytest11"]` table.

**Acceptance criteria:**
- `pytest --markers` shows the plugin is loaded
- `wimi_session` fixture cleans up subprocess + user even on test failure
- Fixtures stack correctly (`wimi_session` depends on `test_user`, etc.)

---

### T2.9 — Phase 2 smoke tests (3 scenarios)

- **Status:** Done — `99e5cbe` (Phase 2 closed; runtime verification pending Phase 4 testids for cleaner locators)
- **Dependencies:** T2.8
- **Files (new):** `tests/wimi_test/test_smoke_phase2.py`
- **Effort:** ~1.5 hr

**Scope:** Three tests:
1. `test_create_user_and_log_out` — uses `wimi_session`, navigates to dashboard, screenshots, exits.
2. `test_create_entry_and_assert_db_row` — uses `seeded_user("minimal")`, navigates to entry form, fills fields, saves, asserts DB has the row via `assert_entry_count`.
3. `test_browser_shows_seeded_entries` — uses `seeded_user("minimal")`, seeds 5 entries directly via DB, navigates to entry browser, asserts 5 rows visible.

**Acceptance criteria:**
- All three pass locally
- Total runtime under 60s
- Phase 2 is considered complete when these pass

---

## Phase 3 — Capture pipeline

### T3.1 — `wimi_test/capture/console.py`

- **Status:** Done — `8b8003c`
- **Dependencies:** T1.1
- **Files (new):** `wimi_test/capture/__init__.py`, `wimi_test/capture/console.py`
- **Effort:** ~1.5 hr

**Scope:** Per `TEST_INFRASTRUCTURE.md` §6.1, Layer 2. Subscribe to `page.on("console")` and `page.on("pageerror")`. Ring buffer (`collections.deque(maxlen=N)`). `snapshot(level_min, since_ts)` returns filtered copy. `flush()` drains.

---

### T3.2 — `wimi_test/capture/network.py`

- **Status:** Done — `5f47d14`
- **Dependencies:** T1.1
- **Files (new):** `wimi_test/capture/network.py`
- **Effort:** ~2 hr

**Scope:** Per §6.2. Subscribe to `Network.requestWillBeSent`, `Network.responseReceived`, `Network.loadingFailed` via the CDP session. URL filter callable; default rejects `file://` and `qrc://`. Header redaction hook for sensitive auth headers.

---

### T3.3 — `src/app/bridge_test_instrumentation.py` (decorator)

- **Status:** Done — `3b5fc59`
- **Dependencies:** T1.3
- **Files (new):** `src/app/bridge_test_instrumentation.py`
- **Effort:** ~2 hr

**Scope:** Per §6.3. The `@instrumented_slot` decorator. No-op when `test_mode.IS_ACTIVE=False`. When active, wraps the slot to record `(method, args, result_summary, duration_ms, error)` to a thread-safe deque. Adds a `_bridge_call_buffer` attribute to the bridge instance lazily on first call. Provide a `getTestModeBridgeCalls(since_ts)` slot helper that returns the buffer as JSON.

---

### T3.4 — `scripts/check_instrumented_slots.py` (CI check)

- **Status:** Done — `ea4d11f`
- **Dependencies:** T3.3
- **Files (new):** `scripts/check_instrumented_slots.py`
- **Effort:** ~1 hr

**Scope:** Walks `src/app/bridge_domains/*.py`, parses each file with the `ast` module, finds all `@pyqtSlot`-decorated methods, asserts each has a paired `@instrumented_slot`. Exits 0 on success, prints offenders and exits 1 on failure. Wire into CI later.

---

### T3.5a — Decorate entries + sessions + sources mixins

- **Status:** Done — `784e81b` (19 slots)
- **Dependencies:** T3.3, T3.4
- **Files (modified):** `src/app/bridge_domains/entries.py`, `src/app/bridge_domains/sessions.py`, `src/app/bridge_domains/sources.py`
- **Effort:** ~2 hr

**Scope:** Add `@instrumented_slot` paired with each `@pyqtSlot` in these three mixins. Run the T3.4 CI check on these files until it passes for them.

---

### T3.5b — Decorate hierarchy + dimensions + aliases mixins

- **Status:** Done — `efca329` (23 slots)
- **Dependencies:** T3.3, T3.4
- **Files (modified):** `src/app/bridge_domains/hierarchy.py`, `src/app/bridge_domains/dimensions.py`, `src/app/bridge_domains/aliases.py`
- **Effort:** ~2 hr

---

### T3.5c — Decorate analytics + advanced_analytics + goals mixins

- **Status:** Done — `d098a7f` (29 slots; the design doc's `analytics_advanced.py` was actually `dimension_analytics.py`)
- **Dependencies:** T3.3, T3.4
- **Files (modified):** `src/app/bridge_domains/analytics.py`, `src/app/bridge_domains/analytics_advanced.py`, `src/app/bridge_domains/goals.py`
- **Effort:** ~2 hr

---

### T3.5d — Decorate media + notes + tags mixins

- **Status:** Done — `afe7ea9` (20 slots)
- **Dependencies:** T3.3, T3.4
- **Files (modified):** `src/app/bridge_domains/media.py`, `src/app/bridge_domains/notes.py`, `src/app/bridge_domains/tags.py`
- **Effort:** ~2 hr

---

### T3.5e — Decorate timer + preferences + exam_context + plugin + import_export + schema_migrations + shared_helpers mixins

- **Status:** Done — `4c63aff` (36 slots; `exam_context.py` is actually `exam_contexts.py`; `plugin.py` is split into `plugin_dispatch.py` + `plugin_management.py`; `schema_migrations.py` and `shared_helpers.py` don't exist as bridge mixins and were correctly skipped)
- **Dependencies:** T3.3, T3.4
- **Files (modified):** seven mixin files in `src/app/bridge_domains/`
- **Effort:** ~3 hr

---

### T3.6 — `wimi_test/capture/bridge.py` (BridgeCapture)

- **Status:** Done — `01abc13` (capture works defensively; full operation depends on a follow-up task to expose `get_test_mode_bridge_calls` as a `@pyqtSlot`)
- **Dependencies:** T3.3
- **Files (new):** `wimi_test/capture/bridge.py`
- **Effort:** ~1.5 hr

**Scope:** Polls the `getTestModeBridgeCalls()` bridge slot at low frequency (default 500ms via Playwright's `page.evaluate`). Maintains its own deque mirroring the buffer. `snapshot()` and `flush()` follow the same pattern as console/network.

---

### T3.7 — `wimi_test/capture/bundle.py` (CaptureBundle)

- **Status:** Done — `eddc503` (landed early; bridge stream slot stays optional until T3.6)
- **Dependencies:** T3.1, T3.2, T3.6
- **Files (new):** `wimi_test/capture/bundle.py`
- **Effort:** ~1 hr

**Scope:** Composes the three streams into a single object. `to_dict()` produces a JSON-serializable representation for failure reports and MCP responses. `flush_all()` drains all three.

---

### T3.8 — Wire captures into `wimi_test/session.py`

- **Status:** Done — `7bc89d8`
- **Dependencies:** T2.7, T3.7
- **Files (modified):** `wimi_test/session.py`
- **Effort:** ~1 hr

**Scope:** Update `WimiTestSession.start()` to instantiate the three captures and call `attach()` on each after the page is ready. `stop()` calls `detach()`. `captures` property returns the bundle.

---

### T3.9 — `wimi_test/fixtures/capture.py` (autouse failure hook)

- **Status:** Done — `9a925e8`
- **Dependencies:** T3.8, T2.8
- **Files (new):** `wimi_test/fixtures/capture.py`
- **Files (modified):** `wimi_test/fixtures/__init__.py` (re-export)
- **Effort:** ~2 hr

**Scope:** Per `TEST_INFRASTRUCTURE.md` §6.4. The `pytest_runtest_makereport` hook. Attaches screenshot + console + network + bridge logs as pytest-html `extras` on failure. Falls back to writing files under `pytest_artifacts/<test_id>/` when pytest-html isn't installed.

---

### T3.10 — Phase 3 capture verification test

- **Status:** Done — `f9d9ff3`
- **Dependencies:** T3.9
- **Files (new):** `tests/wimi_test/test_capture.py`
- **Effort:** ~1.5 hr

**Scope:** Three tests:
1. `test_console_log_captures_messages` — eval JS that calls `console.warn("hi")`, assert the snapshot contains it.
2. `test_network_log_captures_media_load` — load an entry with media, assert the network log contains the `media://` URL.
3. `test_bridge_log_captures_call` — call a bridge method via `eval_js`, assert the bridge log contains the call name.

---

## Phase 4 — UI testid migration

All Phase 4 tasks are independent of each other and can run in parallel after Phase 2 smoke tests pass. The reference for every testid is `docs/testing/UI_AUDIT.md`.

### T4.1 — `question_entry.html` testids (recommended first)

- **Status:** Done — `9a118fd`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/question_entry.html`, `src/web/js/question_entry.js`, `src/web/js/media_upload.js`, `src/web/js/rich_editor.js`, `src/web/js/image_browser.js`
- **Effort:** ~4 hr (most complex page; gets the most dynamic testid additions)

**Scope:** Add `data-testid` attributes per `UI_AUDIT.md` §"question_entry.html" — both static markup additions and the JS-render-time additions for chips, dropdowns, dots, note cards, and media thumbnails.

**Acceptance criteria:**
- Every testid listed in the audit is present
- No CSS regressions (testids don't affect layout)
- The Phase 2 smoke test `test_create_entry_and_assert_db_row` is updated to use the new testids and still passes

---

### T4.2 — `tree_editor.html` testids

- **Status:** Done — `7edc05b`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/tree_editor.html`, `src/web/js/tree_editor.js`, `src/web/js/weight_editor.js`, `src/web/js/subject_search_widget.js`
- **Effort:** ~3 hr

**Scope:** Per `UI_AUDIT.md` §"tree_editor.html". Recursive node testid pattern is the most important one in the codebase — get the `tree-node-{nodeId}` pattern right (with future-aware comment about the polyhierarchy migration's `-under-{parentId}` extension).

---

### T4.3 — `entry_browser.html` testids

- **Status:** Done — `74f1b6f`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/entry_browser.html`, `src/web/js/entry_browser.js`
- **Effort:** ~2.5 hr

---

### T4.4 — `wizards/exam_wizard.html` testids

- **Status:** Done — `437b7f7`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/wizards/exam_wizard.html`, `src/web/js/wizards/exam_wizard.js`
- **Effort:** ~3 hr

**Scope:** Reserve future-aware patterns for the planned exam-length step (`HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`).

---

### T4.5 — `entry_detail.html` testids

- **Status:** Done — `7136032`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/entry_detail.html`, `src/web/js/entry_detail.js`
- **Effort:** ~2 hr

**Scope:** Also pair with `aria-label` additions for lightbox prev/next per the audit.

---

### T4.6 — `analytics_dashboard.html` testids + D3 chart testid render-time additions

- **Status:** Done — `7c2e41f`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/analytics_dashboard.html`, `src/web/js/analytics_dashboard.js`, `src/web/js/sunburst_chart.js`, `src/web/js/heatmap_chart.js`, `src/web/js/dimension_heatmap.js`
- **Effort:** ~3 hr

**Scope:** The three highest-leverage code adds (per `UI_AUDIT.md` cross-cutting issue #2): `sunburst_chart.js:123`, `heatmap_chart.js:184`, `dimension_heatmap.js:187` get `.attr('data-testid', d => ...)` insertions.

---

### T4.7 — `index.html` (dashboard) testids

- **Status:** Done — `f7709c2`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/index.html`, `src/web/js/landing.js`, `src/web/js/analytics_preview.js`
- **Effort:** ~2 hr

---

### T4.8 — `session_setup.html` testids

- **Status:** Done — `dbbbed3`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/session_setup.html`, `src/web/js/session_setup.js`, `src/web/js/session_import.js`
- **Effort:** ~3 hr

---

### T4.9 — `settings.html` testids

- **Status:** Done — `3c331ce`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/settings.html`, `src/web/js/settings.js`, `src/web/js/api/_loader.js`
- **Effort:** ~2.5 hr

**Scope:** Includes the in-flight WIP changes (hotkey UI, MCP panel, addon management). Verify state on disk vs git HEAD before adding testids.

---

### T4.10 — `subject_deep_dive.html` testids

- **Status:** Done — `c04eabc`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/subject_deep_dive.html`, `src/web/js/subject_deep_dive.js`
- **Effort:** ~1.5 hr

---

### T4.11 — `error-viewer.html` testids

- **Status:** Done — `77ad6ee`
- **Dependencies:** T2.9
- **Files (modified):** `src/web/html/error-viewer.html`, `src/web/js/error-logger.js`
- **Effort:** ~1 hr (smallest page)

---

## Phase 5 — MCP facade

### T5.1 — `wimi_test/_internal/async_bridge.py`

- **Status:** Done — `f04f52c`
- **Dependencies:** T2.7
- **Files (new):** `wimi_test/_internal/__init__.py`, `wimi_test/_internal/runid.py`, `wimi_test/_internal/async_bridge.py`
- **Effort:** ~2 hr

**Scope:** Per §8 threading rules. `run_on_session_thread(callable, *args, **kwargs)` dispatches to a dedicated worker thread owned by the registry. Uses `concurrent.futures.ThreadPoolExecutor(max_workers=1)`. Also: `runid.py` provides `next_run_id() -> str` (pid + monotonic counter).

---

### T5.2 — `src/wimi_test_mcp/registry.py` (SessionRegistry)

- **Status:** Done — `accf641`
- **Dependencies:** T2.7, T5.1
- **Files (new):** `src/wimi_test_mcp/__init__.py`, `src/wimi_test_mcp/registry.py`
- **Effort:** ~2 hr

**Scope:** Per `TEST_INFRASTRUCTURE.md` §8 and §4. At-most-one active session, idle timer, idempotent shutdown.

---

### T5.3 — `src/wimi_test_mcp/adapters.py`

- **Status:** Done — `7bc0de7`
- **Dependencies:** T3.7
- **Files (new):** `src/wimi_test_mcp/adapters.py`
- **Effort:** ~1 hr

**Scope:** `capture_bundle_to_dict`, `exception_to_dict`, `recent(captures, limit=20)`. Pure leaf module.

---

### T5.4 — `src/wimi_test_mcp/server.py` (FastMCP entry)

- **Status:** Done — `f09f861` + `c57b072` (tool-import wireup)
- **Dependencies:** T5.2, T5.3
- **Files (new):** `src/wimi_test_mcp/server.py`
- **Effort:** ~1.5 hr

**Scope:** FastMCP("wimi-test") instance, lifespan hook to clean up the registry on shutdown, tool registration entry points (tool modules wired in T5.5–T5.8).

---

### T5.5 — `src/wimi_test_mcp/tools/lifecycle.py`

- **Status:** Done — `281bd25`
- **Dependencies:** T5.4
- **Files (new):** `src/wimi_test_mcp/tools/__init__.py`, `src/wimi_test_mcp/tools/lifecycle.py`
- **Effort:** ~1.5 hr

**Scope:** `start_session`, `end_session`, `get_session_status` tools.

---

### T5.6 — `src/wimi_test_mcp/tools/navigation.py`

- **Status:** Done — `8247f64`
- **Dependencies:** T5.4
- **Files (new):** `src/wimi_test_mcp/tools/navigation.py`
- **Effort:** ~1.5 hr

**Scope:** `navigate_to`, `wait_for`, `eval_js` (gated).

---

### T5.7 — `src/wimi_test_mcp/tools/interaction.py`

- **Status:** Done — `12a1c83`
- **Dependencies:** T5.4
- **Files (new):** `src/wimi_test_mcp/tools/interaction.py`
- **Effort:** ~1 hr

**Scope:** `click`, `fill`, `screenshot`.

---

### T5.8 — `src/wimi_test_mcp/tools/inspection.py`

- **Status:** Done — `bd98447`
- **Dependencies:** T5.4
- **Files (new):** `src/wimi_test_mcp/tools/inspection.py`
- **Effort:** ~1.5 hr

**Scope:** `get_console_log`, `get_network_log`, `get_bridge_log`, `dump_dom`.

---

### T5.9 — Wire `--test-mcp-server` into `run_wimi.py`

- **Status:** Done — `ba4bc86`
- **Dependencies:** T5.5, T5.6, T5.7, T5.8
- **Files (modified):** `run_wimi.py`
- **Effort:** ~30 min

**Scope:** Replace the `NotImplementedError` from T1.4 with the actual entry point — calls `wimi_test_mcp.server.run()`.

---

### T5.10 — Add `wimi-test` MCP server entry to `.mcp.json`

- **Status:** Done — `97a19f0`
- **Dependencies:** T5.9
- **Files (modified):** `.mcp.json`
- **Effort:** ~15 min

---

### T5.11 — Phase 5 verification

- **Status:** Done — `3b95c65`
- **Dependencies:** T5.10
- **Files (new):** `tests/wimi_test_mcp/test_facade_smoke.py`
- **Effort:** ~2 hr

**Scope:** Smoke test that uses the MCP server (via stdio transport) to start a session, navigate to dashboard, screenshot, end session.

---

## Phase 6 — CI + scenario library

(Tracked separately once Phases 1-5 land.)

### T6.1 — Headless CI environment

- **Status:** Done — `973d39e` (Linux runner only; macOS/Windows deferred)
- **Dependencies:** T2.9
- **Effort:** ~3 hr (varies by CI provider)

### T6.2 — Scenario library from bugs.md

- **Status:** Initial slice done — `67e0323` (2 starter scenarios + README; ongoing per the open-ended scope)
- **Dependencies:** All Phase 4 tasks (testids); T2.9
- **Effort:** Open-ended — one PR per bug-derived scenario.

---

## Dispatch Strategy

### Wave 1 (after this doc commits)

Tasks with zero dependencies — dispatchable in parallel right now:

- **T1.1** — `wimi_test/errors.py`
- **T2.1** — `wimi_test/routes.py`

Both are small leaf modules. They can run as two parallel agents in one Agent-tool-call message.

### Wave 2 (after T1.1)

- **T1.2** — `wimi_test/config.py`
- **T1.3** — `src/app/test_mode.py`
- **T2.2** — `wimi_test/locator.py`
- **T3.1** — `wimi_test/capture/console.py`
- **T3.2** — `wimi_test/capture/network.py`

All independent of each other; parallel-dispatchable.

### Wave 3 (after T1.2 + T1.3)

- **T1.4** — `main.py` flag flow (the gating Phase 1 task)
- **T2.4** — `TestUser` (parallel with T1.4)
- **T3.3** — bridge instrumentation decorator (parallel)

### Wave 4 (after T2.2 + T2.1)

- **T2.3** — `WimiPage`

…and so on. The full wave plan continues per the dependency graph at the top.

### Parallelism notes

- Phase 4 tasks (T4.1–T4.11) are mutually independent and can all run in parallel after T2.9. Eleven agents in one message.
- Phase 3 mixin decoration tasks (T3.5a–T3.5e) are likewise independent — five agents in parallel.
- Phase 5 tool modules (T5.5–T5.8) are independent — four agents in parallel.

These three batches are the largest parallelism opportunities in the project.

---

## Status tracking

This file is the source of truth for task status. As tasks complete:

1. Verify acceptance criteria manually (for now; Phase 6 adds CI).
2. Commit (one commit per task by default).
3. Update the task's **Status** line to `Done` with the commit SHA, e.g. `Done — 8930081`.
4. Optionally check the dependency graph for newly-ready tasks.

A future enhancement: a small script that parses this file and prints "ready to dispatch" tasks. Not building it now; the manual scan is fine for the current task count (~50).

---

## Pychrome migration (M-series)

Tasks tracking the Playwright→pychrome migration that replaced the CDP client underneath `wimi_test`. See `docs/planning/PYCHROME_MIGRATION.md` for full migration details — rationale, the per-domain CDP support matrix, the per-file impact assessment, and the rollback plan.

The migration was triggered by the discovery that Playwright's `chromium.connect_over_cdp` issues `Browser.setDownloadBehavior` during connection setup, which Qt's CDP server does not implement. The connection always failed against Qt regardless of the pre-existing `wimi_test` design quality.

Public API (`WimiPage`, `WimiLocator`, `WimiTestSession`, the pytest fixtures, and the 13 MCP tools) was preserved across all M-series tasks.

- [x] **M1.1** — `wimi_test/_internal/cdp_client.py` pychrome wrapper (`WimiBrowser`, `WimiTab`, `open_session(port)`, `wait_for_wimi_api`). Single seam over pychrome's quirks. — `48595be`
- [x] **M1.2** — `wimi_test/locator.py` rewritten on pychrome (`Runtime.evaluate` polling for auto-wait, `Input.dispatchMouseEvent` for clicks). — `04d98f2`
- [x] **M2.1** — `wimi_test/page.py` now wraps `WimiTab` instead of `playwright.sync_api.Page`. Public API preserved. — `d89dfd4`
- [x] **M2.2** — `wimi_test/capture/console.py` subscribes to `Runtime.consoleAPICalled` / `Runtime.exceptionThrown` via `tab.set_listener`. — `d27fc0b`
- [x] **M2.3** — `wimi_test/capture/network.py` subscribes to `Network.{requestWillBeSent,responseReceived,loadingFailed}` via `tab.set_listener`. — `015c9eb`
- [x] **M2.4** — `wimi_test/capture/bridge.py` polls via `tab.evaluate(expression)` instead of `page.evaluate(fn, args)`. — `6a3caf0`
- [x] **M3.1** — `wimi_test/session.py` uses `cdp_client.open_session(port)` instead of `playwright.sync_api.connect_over_cdp`. `WimiTab` is the raw CDP handle and serves as both the page driver and the capture sink (no separate `CDPSession`). — `10e50b8`
- [x] **M3.2** — Live MCP smoke validated end-to-end after restart: `start_session` succeeds in <10s, `eval_js` works (proves `tab.evaluate`), `ConsoleCapture` collects 18 entries with stack traces and levels (proves `Runtime.consoleAPICalled` subscription). Required `stdin=subprocess.DEVNULL` fix in `WimiProcess` — when the parent is the MCP stdio server, the child raced for protocol bytes.
- [x] **M3.3** — Scenario verification: pre-existing pytest fixture-plugin bugs (`pytest_addoption` not re-exported from `wimi_test/fixtures/__init__.py`; `regression` marker not registered in `pytest.ini`) fixed; the two regression scenarios collect under HEAD. They don't run to completion because they depend on the `getTestModeBridgeCalls` `@pyqtSlot` (still pending) and on test-mode user-DB connection (broken pre-migration). Neither gap was caused by the pychrome migration.
- [x] **M3.4** — CI + docs update: drop `playwright install`-style instructions, add pychrome to install commands, mark `TEST_INFRASTRUCTURE.md` and `CI_SETUP.md` with the migration note (this task)
- [x] **M3.5** — Dropped `playwright` from `requirements-test.txt` and `.github/workflows/test-infrastructure.yml`. Deleted vestigial `tests/wimi_test/test_smoke_phase1.py` (Phase 1 gating test built on raw Playwright; superseded by M3.2 live smoke).

