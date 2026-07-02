# Project Status - May 15, 2026

**Consolidated status update covering all work since March 6, 2026.**

---

## Phase Completion Matrix

| Phase | Description | Status | Completed |
|-------|-------------|--------|-----------|
| 1 | Database & Models | ✅ Complete | 2025 |
| 2 | Core UI | ✅ Complete | 2025 |
| 3 | Exam Setup Wizard | ✅ Complete | 2025 |
| 4 | Question Entry | ✅ Complete | Dec 2025 |
| 5 | Entry Browser | ✅ Complete | Jan 2026 |
| 6 | Analytics Dashboard | ✅ Complete | Jan 2026 |
| 7.1 | Foundation & Schema, Hybrid Weights | ✅ Complete | Jan 8, 2026 |
| 7.2 | Exam Setup UI (5 stages) | ✅ Complete | Jan 24, 2026 |
| 7.3 | Question Entry UI | ⚠️ Not needed | - |
| 7.4-7.6 | Multi-Dimensional Analytics | ✅ Complete | Jan 18, 2026 |
| 7.7 | Polish & Optimization | 🚀 Not Started | - |
| 8 | Anki Integration | 📋 Planned | - |
| 9 | Assignable Entry Notes | ✅ Complete | Feb 7, 2026 |
| 10 | Subject Hierarchy Notes | 📋 Planned | - |
| Rich Text | TinyMCE Editor | ✅ Complete | Jan 24, 2026 |
| Templates | Exam Template System | ✅ Complete | Jan 24, 2026 |
| Form UX | Question Entry Improvements | ✅ Complete | Jan 24, 2026 |
| Session Timer | Multi-Round Timer with Break Tracking | ✅ Complete | Feb 25, 2026 |
| Global Settings | Settings Page + Theme System | ✅ Complete | Feb 25, 2026 |
| MacOS Build | Universal Binary Support | ✅ Complete | Feb 18, 2026 |
| Session Import | Import with User-Specified Duration | ✅ Complete | Mar 1, 2026 |
| Plugin/Addon System | Install/uninstall flow + scoped API + per-plugin settings | ✅ Complete | Mar 16, 2026 |
| Media Link System | Junction table, link/unlink/delete, global cross-exam search | ✅ Complete | Apr 9, 2026 |
| Migration Runner | Versioned `MigrationRunner` replaces `_ensure_*_schema()` chain | ✅ Complete | May 9, 2026 |
| Test Infrastructure | `wimi_test/` + `wimi_test_mcp` + CI + scenario library | ✅ Complete | May 9, 2026 |
| Polyhierarchy (DAG) | `subject_edges` backend + tree-editor parents-management UI | 🟡 Partially Landed | May 9, 2026 |
| Weight Allocation Rework | Per-edge weight columns + UI polish | 🔧 In Progress | - |

---

## Codebase Metrics

| Metric | Value | Δ since Mar 6 |
|--------|-------|---------------|
| Python (src/) | ~30,000 lines | +8,700 |
| JavaScript (src/web/) | ~32,300 lines | +1,600 |
| CSS | ~20,300 lines | (not previously tracked) |
| HTML | ~4,000 lines | (not previously tracked) |
| Test files | 64 | +14 |
| Test functions (`def test_*`) | 991 | +403 |
| HTML pages | 10 + wizard sub-pages | unchanged |
| `bridge.py` | 111 lines | -5,489 (now thin shell, 23 mixins compose) |
| `user_db.py` | 121 lines | -10,279 (now thin shell, 20 mixins compose) |
| Migrations applied | m001–m005 (user) | +2 (m004 edges, m005 primary_parent_id) |
| Platforms | Windows + macOS | unchanged |

The dramatic shrinkage of `bridge.py` and `user_db.py` reflects the mixin decomposition that landed in March (`f323a3a`) and was extended in April (`787be28`). Logic now lives in `src/app/bridge_domains/*` (23 modules) and `src/database/domains/*` (20 modules).

---

## Recent Work (Since March 6, 2026)

### Plugin/Addon System Distribution (Mar 12-16, 2026)
- Merged `feature/addon-system` branch — full install/uninstall flow with zip-bundle distribution
- Database operations decomposed into domain mixins (precursor to the wider mixin pattern)
- Plugin scoped API expanded; per-plugin settings slots; file storage API + storage permission
- Plugin initialization race conditions fixed
- Plugin development guide added (`docs/PLUGIN_DEVELOPMENT.md`)
- Theme persistence fixed across page navigation; CSS variables replace remaining hardcoded hex colors
- Pomodoro timer functionality expanded; CSS text-size handling broadened to TinyMCE

### Media Decoupling + Domain-Mixin Sweep (Apr 9, 2026)
- Media storage decoupled from entries via `entry_media_mapping` junction table; flat filesystem layout
- Global media search across all exams; cross-exam media reuse via `attachMediaToEntry`
- Database layer further decomposed into domain mixins (`787be28`)
- Plugin system enhancements (dispatch improvements, settings integration)
- Weight range export flattening fixed; alias import/export added
- Dark mode text readability fixed across all themes

### Status Audit (Apr 19-20, 2026)
- `FUTURE_VISION.md` bumped to v3.1 — Entry/Subject Improvements + Media Link System marked complete
- `CLAUDE.md` refreshed with architecture details
- Form section switching bug fixed (replaced brittle timing guard with click-in-progress flag)

### Test Infrastructure — `wimi_test/` + MCP Server (May 7-8, 2026)
A comprehensive test-driver framework built in a single sustained sprint:
- `wimi_test/` library: `routes`, `locator`, `process`, `page`, `session`, `db/{seeders,test_user,assertions}`, `capture/{console,network,bridge,bundle}`, `errors`, `config`, `_internal/cdp_client.py`
- `@instrumented_slot` decorator paired with `@pyqtSlot` across 33 slots in 5 bridge mixins; pulls a `getTestModeBridgeCalls` window for replay
- `src/app/test_mode.py` + `--test-mode` CLI flag flow through `run_wimi.py` and `main.py`; `TestModeQWebEnginePage`
- `data-testid` attributes added to 11 HTML pages (T4.1–T4.11) for stable locators
- `src/wimi_test_mcp/` FastMCP server exposing lifecycle/navigation/interaction/inspection tools (`start_session`, `click`, `fill`, `wait_for`, `eval_js`, `dump_dom`, `screenshot`, `get_console_log`, `get_network_log`, `get_bridge_log`)
- `.mcp.json` stdio entry for the `wimi-test` MCP
- `.github/workflows/test-infrastructure.yml` CI on Ubuntu/Python 3.11 with `QT_QPA_PLATFORM=offscreen`; `pytest_artifacts/` uploaded on failure
- Initial regression scenario library populated from `bugs.md` (`tests/wimi_test/scenarios/`, `@pytest.mark.regression`)
- `scripts/check_instrumented_slots.py` CI gate ensuring `@pyqtSlot`s carry `@instrumented_slot`

### Playwright → pychrome Migration (May 7-8, 2026)
- Discovered Qt's CDP surface lacks the `Browser` domain Playwright requires; rewrote the entire wimi_test stack on `pychrome` (M1.1 → M3.5)
- `cdp_client.py` thin async wrapper; `WimiLocator`, `WimiPage`, `ConsoleCapture`, `NetworkCapture`, `BridgeCapture`, `WimiTestSession` all rewritten
- Locator robustness fixes: scroll-into-view before click coords, `mouseMoved` before `mousePressed`
- CI updated to install `pychrome` only (no `playwright install` post-step needed)
- Playwright dependency dropped from `requirements-test.txt`
- Migration documented in `docs/planning/PYCHROME_MIGRATION.md`

### Migration Runner (May 9, 2026)
- Versioned `MigrationRunner` (`src/database/migration_runner.py`) replaces the chained `_ensure_*_schema()` pattern
- Per-DB `schema_migrations` table tracks applied versions; pending migrations applied on open
- Migrations are numbered modules (`m00N_*.py`) under `src/database/migrations/{user,master}/` exposing `VERSION`, `NAME`, `upgrade(conn)`
- Migrations CLI (`python -m src.database.migrations`) for ad-hoc inspection/replay
- Dead `_ensure_*` methods removed (`54720d7`)
- Tests for the runner and individual migrations
- Plan documented in `docs/planning/MIGRATION_RUNNER.md`

### Polyhierarchy Backend (May 9, 2026)
The subject hierarchy is mid-migration from strict tree to DAG, motivated by the official USMLE Step 1 outline (12–18% of named clinical topics appear under multiple parents — DVT, hypertension, sepsis, anemia, etc.). What landed:
- Migration `m004_subject_edges`: `subject_edges` table holding `(parent_id, child_id, dimension_id, is_anchor, relative_weight, weight_source, sort_order)`
- Migration `m005_primary_parent_id`: explicit primary-parent tracking
- `EdgesMixin` (`src/database/domains/edges.py`) — cycle prevention, primary-parent invariant, edge CRUD
- `GraphMixin` (`src/database/domains/graph.py`) — DAG traversal layered on top
- `get_subject_hierarchy` and `getDimensionHierarchy` rewritten to walk `subject_edges`, not legacy `parent_id`
- Bridge slots + JS API for edge operations (`f82c8cd`)
- Tree editor: parents-management UI, alias chip on non-primary appearances, auto-reveal new appearance after add-parent / switch-primary, dimension cache busted before edge-mutation refresh
- USMLE seeder upgraded to full polyhierarchy parse
- Plan: `docs/planning/POLYHIERARCHY_MIGRATION.md`

### Tree Editor UX Polish (May 9, 2026)
- Details panel reads as a real inspector
- Panels own their scrollbars, page itself is fixed-viewport
- Weight algorithm-info: description stacked on its own row
- Weight siblings section: responsive grid with wrap-friendly total row

### Build/Packaging Cleanup (May 7-9, 2026)
- PyInstaller specs (`wimi.spec`, `wimi_macos.spec`) tracked in repo
- Migrations bundled into PyInstaller artifacts; test data excluded
- Frontend: D3.js bundled locally instead of CDN; KaTeX bundling documented
- Python requirements consolidated and pinned (`requirements-prod.txt`, `requirements-test.txt`); stale UTF-16-encoded duplicate file dropped
- `phase2`/`phase4` schema eager-init; `phase6` test fixtures repaired

### Bug Fixes (May 8, 2026)
- Two bugs from `bugs.md` fixed: complete-review-stops-timer + alias-overflow (covered by new regression scenarios)
- Scenario gaps closed: bypass modal animation, force section expansion, query-string goto

### CLAUDE.md Refreshes (May 14-15, 2026)
- Updated mixin counts (20 db / 23 bridge), migration runner reference, polyhierarchy status section
- Added regression-marker pytest commands, CI workflow reference, `wimi_test/` vs `src/wimi_test_mcp/` clarification

---

## New Files Added (Since March 6, 2026)

| File / Directory | Purpose |
|------------------|---------|
| `wimi_test/` (root package) | pychrome-based test driver library (locator, page, session, captures, db helpers) |
| `src/wimi_test_mcp/` | FastMCP server wrapping `wimi_test/` for interactive Claude Code sessions |
| `src/app/test_mode.py` | Test-mode state + `TestModeQWebEnginePage` |
| `src/app/bridge_test_instrumentation.py` | `@instrumented_slot` decorator + `getTestModeBridgeCalls` |
| `src/database/migration_runner.py` | Versioned schema migration runner |
| `src/database/migrations/user/m004_subject_edges.py` | Polyhierarchy edges table |
| `src/database/migrations/user/m005_primary_parent_id.py` | Explicit primary-parent tracking |
| `src/database/domains/edges.py` | `EdgesMixin` — edge CRUD with invariants |
| `src/database/domains/graph.py` | `GraphMixin` — DAG traversal |
| `src/app/bridge_domains/edges.py` | `EdgesBridgeMixin` — bridge surface for edges |
| `src/app/bridge_domains/weights.py` | `WeightBridgeMixin` — weight allocation surface |
| `src/app/bridge_domains/dimension_analytics.py` | Dimension-aware analytics surface |
| `tests/fixtures/usmle_step1_outline.txt` | Full 2025 USMLE Step 1 content outline (1,327 lines) |
| `tests/wimi_test/scenarios/` | Regression scenario library (`@pytest.mark.regression`) |
| `tests/database/migrations/` | Per-migration test files |
| `tests/database/test_subject_edges.py` | Edges table tests |
| `tests/database/test_polyhierarchy_traversal.py` | DAG traversal tests |
| `tests/database/test_get_subject_hierarchy_polyhierarchy.py` | Hierarchy CTE rewrite tests |
| `tests/database/test_primary_parent_context.py` | Primary-parent invariant tests |
| `tests/database/test_session_timer.py` | Session timer tests (50 functions) |
| `.github/workflows/test-infrastructure.yml` | CI workflow (Ubuntu, Python 3.11, offscreen Qt) |
| `scripts/check_instrumented_slots.py` | CI gate for `@instrumented_slot` pairing |
| `docs/planning/POLYHIERARCHY_MIGRATION.md` | DAG migration plan |
| `docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` | Per-edge weight rework plan |
| `docs/planning/PYCHROME_MIGRATION.md` | Playwright→pychrome rewrite |
| `docs/planning/MIGRATION_RUNNER.md` | Versioned runner design |
| `docs/planning/TEST_INFRASTRUCTURE.md` | Test infra design + §8 wimi_test |
| `docs/planning/TEST_INFRASTRUCTURE_TASKS.md` | T-tagged task breakdown |
| `docs/guides/SHARED_SUBJECTS.md` | Polyhierarchy concept explainer |
| `docs/guides/BRIDGE_METHODS_HYBRID_WEIGHTS.md` | Weight bridge surface |
| `docs/testing/CI_SETUP.md` | CI configuration notes |
| `docs/testing/UI_AUDIT.md` | UI test locator audit reference |
| `entitlements.plist` | macOS JIT entitlements (carried over) |
| `wimi.spec` / `wimi_macos.spec` | PyInstaller specs (now tracked) |

---

## Known Issues (Technical Debt)

| Priority | Issue | Description | Notes |
|----------|-------|-------------|-------|
| HIGH | Entry save not persisting media/tables | Media and tables in notes not saved when navigating | Outstanding from Mar 6 |
| HIGH | Entry form auto-scroll | Screen scrolls up while typing in lower sections | Outstanding from Mar 6 |
| HIGH | Hamilton allocator + question-count UI | Per-edge weight columns landed, allocator + UX still being shaped | New since Mar 6 |
| MEDIUM | Image dialog subject bug | Shows "No subjects" after returning to entry | Outstanding from Mar 6 |
| MEDIUM | Table multi-selection | Selection lost on right-click | Outstanding from Mar 6 |
| MEDIUM | Table right-click functions | Context menu functions broken | Outstanding from Mar 6 |
| MEDIUM | Cross-dimensional polyhierarchy | Both parents of a multi-parent leaf must share dimension; lifting this is a known limitation | New since Mar 6 |
| MEDIUM | `getMediaFileUsage()` / `getOrphanedMedia()` | Media Link System minor remaining items + image-browser usage indicators | Carried over |
| LOW | Related images false positive | Dialog appears for subjects without images | Outstanding from Mar 6 |
| ✅ | Form section switching | First click on collapsed section closed it instead of opening | Fixed Apr 20 (`baa1e0d`) |
| ✅ | Complete-review timer | Timer didn't stop on review completion | Fixed May 8 (`3842ae3`) |
| ✅ | Alias overflow | Long alias text overflowed chip container | Fixed May 8 (`3842ae3`) |

---

## Next Priorities

1. **Hierarchical Weight Allocation Rework** — Implement Hamilton allocator + question-count input UI per `HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`. Schema columns are already on `subject_edges`; the allocator and UX are the remaining work. This is the largest live arc.
2. **Polyhierarchy UX completion** — Cross-dimensional edges, optional parent-context tagging on entries, breadcrumb disambiguation in analytics drilldowns.
3. **Phase 7.7: Polish** — Now that the test infra exists, run perf benchmarks against the polyhierarchy CTE rewrites and add caching where needed. Lower-effort follow-on.
4. **Tech debt** — Fix the 5 outstanding bugs above (entry save persistence, auto-scroll, table multi-selection, table right-click, image dialog subject).
5. **Anki Integration (Phase 8)** — Greenfield product work; `anki-mcp` is now connected at the harness level so groundwork for inspection exists.

---

## Key Architecture Notes

- **Mixin composition is now the dominant pattern.** `bridge.py` (111 lines) composes 23 bridge mixins; `user_db.py` (121 lines) composes 20 database mixins. Mixins never import each other; cross-domain calls use `self.*` since they share the composed instance.
- **Polyhierarchy source of truth:** `subject_edges` table, NOT `subject_nodes.parent_id` (legacy, being phased out). All new hierarchy code must walk `subject_edges` via `EdgesMixin` / `GraphMixin`.
- **Per-edge weights:** `is_anchor`, `relative_weight`, `weight_source` columns now live on `subject_edges`. Same node can carry different weight under different parents (e.g. PE under Respiratory ≠ PE under Pregnancy).
- **Migration pattern:** Numbered modules under `src/database/migrations/{user,master}/`, each exposing `VERSION`, `NAME`, `upgrade(conn)`. Applied by `MigrationRunner` on DB open. **Do not** add new `_ensure_*_schema` methods.
- **Test instrumentation:** `@instrumented_slot` on every `@pyqtSlot` enables bridge-call replay via `getTestModeBridgeCalls`. CI gate (`scripts/check_instrumented_slots.py`) enforces pairing.
- **CDP driver:** Drives QtWebEngine via `pychrome` (Qt's CDP surface lacks Playwright's required `Browser` domain). One active session per `wimi-test` MCP server.
- **Test database:** `exam_context_id=5` (USMLE 3) with 20 entries across 3 dimensions remains the default seeded fixture. USMLE Step 1 outline available as a 1,327-line polyhierarchy fixture.

---

## Documentation Map

| Document | Purpose | Last Updated |
|----------|---------|--------------|
| `CLAUDE.md` (root) | Quick reference for AI agents | May 15, 2026 |
| `docs/planning/FUTURE_VISION.md` | Primary roadmap & status (v3.2) | May 15, 2026 |
| `docs/status/SESSION_2026-05-15_CONSOLIDATED_STATUS.md` | This document | May 15, 2026 |
| `docs/status/SESSION_2026-03-06_CONSOLIDATED_STATUS.md` | Previous status snapshot | Mar 6, 2026 |
| `docs/handoff/INDEX.md` | Handoff tracking | Mar 6, 2026 |
| `docs/planning/POLYHIERARCHY_MIGRATION.md` | DAG migration plan | May 15, 2026 |
| `docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` | Per-edge weight rework plan | May 15, 2026 |
| `docs/planning/MIGRATION_RUNNER.md` | Versioned runner design | May 9, 2026 |
| `docs/planning/PYCHROME_MIGRATION.md` | Playwright→pychrome rewrite | May 8, 2026 |
| `docs/planning/TEST_INFRASTRUCTURE.md` | Test infra design + §8 wimi_test | May 7, 2026 |
| `docs/PLUGIN_DEVELOPMENT.md` | Plugin development guide | Mar 16, 2026 |
| `docs/BUILD_WINDOWS.md` | Windows build instructions | Jan 3, 2026 |
| `docs/BUILD_MACOS.md` | macOS build instructions | Feb 18, 2026 |
| `docs/architecture/completed_database_tables.md` | Database schema reference | Jan 2026 |
| `docs/guides/SHARED_SUBJECTS.md` | Polyhierarchy concept explainer | May 7, 2026 |
| `docs/guides/BRIDGE_METHODS_HYBRID_WEIGHTS.md` | Weight bridge surface reference | Jan 2026 |
