# Regression Scenarios

This directory holds **regression test scenarios** derived from
`docs/bugs/bugs.md`. Each scenario is a pytest module that:

1. Names the bug it guards against (link or quote in the module
   docstring).
2. Reproduces the failure path with as little setup as possible.
3. Asserts the *fixed* behaviour. When a fix lands, the test should
   start passing without further edits.

The scenarios complement the smoke tests in `tests/wimi_test/` (which
prove the test infrastructure itself is wired correctly) — these tests
prove specific *application* behaviours.

This is the initial slice of task **T6.2** in
`docs/planning/TEST_INFRASTRUCTURE_TASKS.md`. Subsequent PRs will add
one scenario per closed bug.

---

## Naming convention

```
test_<bug_descriptor>.py
```

- `test_` prefix is mandatory (pytest collection).
- `<bug_descriptor>` is a short snake_case slug summarising the bug.
  Match the spirit of the section heading in `bugs.md`, not its
  literal text. Examples:
  - `test_subject_hierarchy_alias_overflow.py`
  - `test_complete_review_stops_timer.py`
- One scenario per file. If a bug has multiple sub-cases, add multiple
  test functions inside one file rather than splitting files.

---

## Standard structure

Every scenario file follows this layout:

1. **Module docstring** — a short reproduction of the bug:
   - Cite the source: `docs/bugs/bugs.md` plus a stable identifier
     (section heading or, when one is added, an issue ID).
   - Quote the relevant lines so the scenario survives if the bug
     entry is later moved or removed.
   - Briefly explain *why* the test fails today and what a fix needs to
     change.
2. **Markers** — every scenario carries:
   - `@pytest.mark.slow` (real WIMI subprocess; eligible for `-m "not slow"`).
   - `@pytest.mark.regression` (custom marker; **not** registered in
     `pytest.ini` per the T6.2 task scope — pytest emits an
     `PytestUnknownMarkWarning` but still runs the test). When the wider
     regression-suite project lands, register the marker in
     `pytest.ini` under `[pytest] markers`.
3. **Fixtures** — prefer the documented fixtures from
   `wimi_test.fixtures.core`:
   - `wimi_session` for full UI flows.
   - `wimi_page` for navigation + locator calls.
   - `seeded_user("<seeder_name>")` when a named seeder covers the
     scenario's data needs.
   - `test_user` when the scenario seeds bespoke data that no named
     seeder produces (the example scenarios in this directory both
     seed manually for that reason).
   - `console_log`, `network_log`, `bridge_log` once T3.8 lands; until
     then they are `None`.
4. **Arrange / Act / Assert** sections marked with section comments
   (`# ---- Arrange ----------`, etc.). Keep arrange small — favour
   raw DB seeding through `wimi_session.user.db` over multi-step UI
   navigation when the UI step isn't what's under test.
5. **Bug-context comment block** at the bottom of the test (or inline
   inside the assertion block) explaining what the bug was, what the
   fix changes, and why each assertion catches the regression.

### Locator strategy

Per `docs/testing/UI_AUDIT.md` §"Locator Strategy", prefer in this
order:

1. `wimi_page.locator(role="...", name="...")`
2. `wimi_page.locator(testid="...")` — every page has testids per
   Phase 4 (T4.1–T4.11). Cross-reference the audit before falling back.
3. `wimi_page.locator(css="...")` — last resort.
4. `wimi_page.eval_js(...)` — only for assertions that require layout
   geometry, computed style, or other browser-side facts that no
   selector can return.

Never use `time.sleep()`. The Phase 2 escape hatch
`wimi_page.pw_page.wait_for_timeout(N)` is acceptable until T3.6 ships
`wait_for_bridge_call`. When you use the escape hatch, leave a
`# TODO(Phase 3 / T3.6):` comment with the eventual replacement.

### DB-side assertions

Use the helpers in `wimi_test.db.assertions`:

- `assert_entry_count(db, expected, *, exam_context_id=None, session_id=None)`
- `assert_subject_exists(db, name, *, exam_context_id=None)`
- `assert_session_completed(db, session_id)`

They raise `AssertionFailureWithCapture` with rich messages and will
have a `CaptureBundle` attached automatically once T3.9 wires the
pytest failure hook.

---

## Adding a new scenario when a bug is fixed (or filed)

1. **Pick a tracked bug.** Open `docs/bugs/bugs.md` and find a bug that
   is testable through the UI (most are). Bugs that require manual
   environmental setup beyond what `seeded_user` produces should be
   deferred until a matching seeder lands.
2. **Decide on the descriptor.** Keep it short and snake_case. Match
   the bug's intent, not its literal heading.
3. **Copy an existing scenario as a template.**
   `test_subject_hierarchy_alias_overflow.py` is the template for
   layout/CSS bugs; `test_complete_review_stops_timer.py` is the
   template for click-handler / lifecycle bugs.
4. **Write the test.** Follow the standard structure above. The
   docstring is *load-bearing* — write it before the body so the
   reproduction is anchored before you start fitting code to it.
5. **Run locally** with `pytest tests/wimi_test/scenarios/test_<your_file>.py -v`.
   The first run typically *fails* (that's the point — it's a
   regression test for an open bug). Annotate the failure mode in the
   PR so the reviewer knows the test is expected to start passing only
   after the fix lands.
6. **Cross-reference the bug entry.** Once the fix lands and the test
   goes green, add a single-line cross-reference in `bugs.md` (or
   delete the bug entry if `bugs.md` is the issue tracker for now).

---

## File size budget

Each scenario should land between **80–150 lines** including the
docstring. If a scenario exceeds 150 lines, it's usually doing too
much: split it into multiple test functions (still one file per bug),
or extract shared seed setup into a helper module under
`tests/wimi_test/scenarios/_helpers/` (no `__init__.py` needed —
pytest discovers helpers via direct import once the path is on
`sys.path`).
