# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**WIMI (What I Missed It)** is a metacognitive exam preparation tool that helps students analyze their mistakes through reflection. Built with PyQt6 + QWebEngineView for the desktop shell, SQLite for data, and D3.js for visualizations. Cross-platform (Windows + macOS).

Production-ready for personal use. See `docs/planning/FUTURE_VISION.md` for roadmap and status.

## Build & Run Commands

```bash
# Development mode (F5 reload, F12 dev tools)
python run_wimi.py

# Run all tests (coverage enforced at 80% on src/database)
pytest

# Skip end-to-end UI scenarios that spawn WIMI (fast iteration loop)
pytest -m "not regression and not slow"

# Run only UI regression scenarios (tests/wimi_test/scenarios/, requires QtWebEngine; CI runs them with QT_QPA_PLATFORM=offscreen)
pytest -m regression

# Run specific test file or pattern
pytest tests/database/test_user_db_phase1.py -v
pytest -k test_name

# Broaden coverage to all of src (default scope is src/database per pytest.ini)
pytest --cov=src --cov-report=term-missing

# CI gate — every @pyqtSlot must be paired with @instrumented_slot
python scripts/check_instrumented_slots.py

# Build executables
./build_windows.bat          # Windows → dist/WIMI/WIMI.exe
chmod +x build_macos.sh && ./build_macos.sh  # macOS universal binary
```

## Architecture

### Three-Layer Design

1. **Backend (Python/SQLite):** `src/database/` — domain mixins composed into `UserDatabase` and `MasterDatabase`
2. **Bridge (PyQt6 WebChannel):** `src/app/bridge.py` — `@pyqtSlot` methods exposed to JavaScript, composed from bridge domain mixins
3. **Frontend (HTML/CSS/JS):** `src/web/` — pages, D3.js visualizations, Fuse.js fuzzy search

### Mixin Composition Pattern (Critical)

Both the database layer and the bridge layer use **mixin composition**, not monolithic classes. This is the most important architectural pattern in the codebase.

**Database layer:** `src/database/user_db.py` (~110 lines) composes 21 mixins from `src/database/domains/`:
- `SharedHelpersMixin`, `SchemaMigrationMixin`, `PreferencesMixin`, `ExamContextMixin`, `HierarchyMixin`, `EdgesMixin`, `TagsMixin`, `SessionsMixin`, `TimerMixin`, `SourcesMixin`, `EntriesMixin`, `MediaMixin`, `NotesMixin`, `AnalyticsMixin`, `AdvancedAnalyticsMixin`, `GoalsMixin`, `DimensionsMixin`, `AliasesMixin`, `ImportExportMixin`, `PluginDataMixin`, `GraphMixin`

**Bridge layer:** `src/app/bridge.py` (~115 lines) composes 25 mixins from `src/app/bridge_domains/`:
- Domain mixins (e.g., `EntryBridgeMixin`, `AnalyticsBridgeMixin`, `MediaBridgeMixin`, `EdgesBridgeMixin`, `WeightBridgeMixin`, `DimensionAnalyticsBridgeMixin`) plus `SerializerMixin`, `PluginDispatchMixin`, `PluginManagementMixin`, and `McpServerBridgeMixin`.

**Key rule:** Mixins never import each other. All cross-domain calls use `self.*` since they share the composed instance.

**JavaScript API layer:** `src/web/js/api/` mirrors the Python domain structure with one module per domain. `_bridge.js` provides the core `api._callBridge()` infrastructure, and `_loader.js` loads all modules on startup. Methods attach to `window._wimiApi`.

### Adding New Features

1. Add database methods in a mixin in `src/database/domains/`
2. Expose via `@pyqtSlot` in a bridge mixin in `src/app/bridge_domains/`. Every `@pyqtSlot` MUST be paired with `@instrumented_slot` (decorator from `src/app/bridge_test_instrumentation.py`) — `scripts/check_instrumented_slots.py` is a CI gate.
3. Add JavaScript wrapper in `src/web/js/api/`
4. Implement UI in `src/web/html/`, `src/web/css/`, `src/web/js/`
5. Add tests in `tests/`

**Per-page CSS link gotcha:** Stylesheets are loaded by individual HTML pages, not project-wide. Adding new classes to (say) `weight.css` means **every page that consumes those classes also needs `<link rel="stylesheet" href="../css/weight.css">`**. Otherwise the page silently renders with browser defaults. This bit Stage 9's "Weight Sources" card on the analytics dashboard — the rules existed in `weight.css` but the page didn't link it, so the card came up as a bulleted list. Always check the `<link>` block when adding cross-page styles.

All `@pyqtSlot` methods return JSON strings via `serialize_response()`. The response contract is `{"success": true/false, "data": {...}, "error": "msg"}`. Pattern: check `self.user_db` → call db method → serialize result. Uses `DateTimeEncoder` for datetime fields.

On the JS side, `api._callBridge(methodName, ...args)` awaits `api.ready()`, calls the PyQt slot, parses the JSON response, and throws on `success=false`.

### Database Architecture

- **Master Database (`users.db`)**: User registry, cross-user data
- **Per-User Databases (`user_XXX_username.db`)**: Isolated user data with full schema
- Schema files in `src/database/schema/`, migrations in `src/database/migrations/{user,master}/` as numbered modules (`m00N_*.py`) each exposing `VERSION`, `NAME`, `upgrade(conn)`
- A versioned `MigrationRunner` (`src/database/migration_runner.py`) replaces the old chained `_ensure_*_schema()` pattern. Open paths apply pending migrations and stamp `schema_migrations`. See `docs/planning/MIGRATION_RUNNER.md`. Do **not** add new `_ensure_*_schema` methods — write a numbered migration module instead. **Currently at user m001–m007 + m009** (no m008 — numbering gap is intentional). m004 introduced `subject_edges`; m005 `primary_parent_id`; m006 added `edge_id` to weight history + broadened `change_type` enum; m007 added the `length_kind`/`length_min`/`length_max`/`length_typical`/`length_note` triple to `exam_contexts`; m009 added `entry_note_attachments`. Master is at m001 (baseline only).
- All write operations use `self.transaction()` context manager from `BaseDatabase`
- SQLite uses WAL mode with foreign keys enabled
- Exception types: `BaseDatabaseError`, `DatabaseConnectionError`, `DatabaseIntegrityError`

### Frontend Pages

HTML pages in `src/web/html/`: index (dashboard), question_entry, analytics_dashboard, entry_browser, entry_detail, tree_editor, session_setup, settings, subject_deep_dive, error-viewer, plus `wizards/exam_wizard.html`.

### Theme System

CSS custom properties defined in `src/web/css/styles.css` (18+ variables: `--bg-primary`, `--text-primary`, `--color-primary`, `--radius-lg`, etc.). Light and dark themes. All new CSS must use these variables, not hardcoded colors.

### Plugin System

Plugins live in `app_data/plugins/` with a `manifest.json`. Backend plugins (Python) get a scoped API with permission-gated access. Frontend plugins (JS/CSS) are injected on every page with access to `window._wimiApi` and `window.eventBus`. See `docs/PLUGIN_DEVELOPMENT.md` for the full guide.

Key files: `src/app/plugin_manager.py`, `src/app/plugin_api.py`, `src/app/plugin_manifest.py`

## Subject Polyhierarchy & Weight Allocation

The subject hierarchy is a DAG (Stages 0–9 of the Hierarchical Weight Allocation Rework + Stage 9 polish, complete as of 2026-05-16). Treat `subject_edges` as the canonical source of truth; `subject_nodes.parent_id` is legacy. `subject_nodes.relative_weight` / `weight_source` are mirrored for chip-render compatibility but scheduled for removal in deferred Stage 10.

### Schema

- **`subject_edges`** (`m004_subject_edges`) holds `(parent_id, child_id, dimension_id, is_anchor, relative_weight, weight_source, sort_order)`. Managed by `EdgesMixin` (`src/database/domains/edges.py`) with cycle prevention and primary-parent invariant. `GraphMixin` (`graph.py`) layers DAG traversal on top.
- **`exam_contexts`** gained the length triple in `m007`: `length_kind` (`'fixed'|'range'|'unknown'`) + `length_min`/`length_max`/`length_typical`/`length_note`. `'range'` is the CAT signal (variable-length adaptive exams).
- **`subject_node_weights`** is the audit log; `m006` added `edge_id` so per-edge writes are attributable.

### Allocator & writers (DB layer)

- **Hamilton allocator:** `HierarchyMixin.allocate_questions_hamilton(parent_id, total_questions, *, weakness_lookup=None, is_adaptive=False)`. Largest Remainder + three-rule tie-break (fractional remainder → weakness score → `edge_id`). `is_adaptive=True` (for `length_kind='range'`) returns floats instead of integer-rounding.
- **Per-edge writer:** `HierarchyMixin.update_edge_relative_weight(edge_id, relative_weight, *, set_anchor, source, reason)`. The legacy `update_subject_relative_weight` is a thin shim that mirrors to both `subject_edges.relative_weight` and `subject_nodes.relative_weight` for read-path compatibility.
- **Rebalance is opt-in:** writers NEVER auto-mutate siblings. Call `rebalance_sibling_edge_weights(parent_id)` explicitly. Anchored (`is_anchor=TRUE`) and legacy `weight_locked` edges are excluded from the adjustable set.
- **Effective q_typical:** use `get_effective_question_counts(exam_context_id)` for any Q-budget lookup. It walks the tree via the Hamilton allocator and handles uncategorized ancestor edges via legacy node fallback. The bridge helper `_compute_parent_q_budget` delegates to this — **do not re-implement the walk**; an earlier attempt fell back to `length_typical` on the first uncategorized edge and made deeply-nested Q displays absurd (Histology under Anatomy reporting ~280 q instead of ~3 q).

### Canonical user-typed-value bridge slot

`setExplicitWeight(edge_id, value, unit, reason)` is the single atomic call from JS for any user-typed weight. It converts `Q→%` when needed (using `_compute_parent_q_budget`), writes `subject_edges.relative_weight`, sets `is_anchor=TRUE`, sets `weight_source='user_explicit'`, and mirrors to `subject_nodes` for legacy reads. Replaces the historical two-call `updateRelativeWeight` + `setEdgeAnchor` pattern — use this slot for any new "user types a weight" flow.

Other bridge surface added by Arc 1 (`src/app/bridge_domains/weights.py`): `rebalanceSiblings`, `setEdgeAnchor`, `updateEdgeRelativeWeight`, `getEdgesForChild`, `getQuestionAllocation`, `getEffectiveQuestionCounts`, `getFeasibilityReport`, `getAllFeasibilityReports`, `getWeightSourceBreakdown`.

### Multi-parent deep-dive view (Stage 9 polish, May 16 2026)

The subject deep-dive page's "Show as part of" selector and the Tag context pill on the entry form are coupled — they implement per-entry parent-context disambiguation end-to-end. Two load-bearing things:

1. **The deep-dive view diverges from polyhierarchy §5.4 *by design*.** `get_subject_deep_dive` uses a two-branch agg WHERE: no filter → "show every entry tagged on the subject or routing into its subtree" (most permissive, what users expect from a deep-dive page); filter=P → NULL-context entries on the subject + entries routing through P's subtree. This is the "Show everything always" semantic. The strict §5.4 rollup ("primary_parent_id scopes entries to that chain only") still governs parent-page rollups elsewhere — just not the deep-dive's own view of its subject. **Do not "fix" this back to strict §5.4** without re-reading this decision (`HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` §"Stage 9 polish"). The payload also carries `path_via_parent` (root → chosen parent → subject, used to swap the breadcrumb on selection) and `entries_scoped_elsewhere` (count of entries hidden by the current view, used by the explanatory banner).

2. **Multi-parent subjects always get a non-NULL `primary_parent_id` on save.** `selectTagContext` / `syncTagContextChoices` in `question_entry.js` enforce this: every multi-parent primary subject on a new entry writes via `setPrimaryParentForEntry` on the existing autosave, defaulting to the canonical primary (first edge from `getEdgesForChild`) if the user doesn't touch the pill. Single-parent subjects skip the write (NULL is unambiguous there). NULL is now **legacy-only** for new entries — the lenient NULL pass-through in the deep-dive's filter exists for backward-compat with pre-policy rows. New `@pyqtSlot` work in this area should preserve this guarantee; don't write a NULL `primary_parent_id` for a multi-parent subject from any new code path.

### Dimension code path symmetry (load-bearing gotcha)

Tree editor has TWO load paths: `loadHierarchy()` (single-dimension or no-dimension view) and `loadDimensionHierarchy()` (multi-dimensional exams like USMLE/IM Shelf — the **common case**, not the edge case). Both must enrich the same way and both must respect the dimension cache.

When you change anything in this area:
- Mirror enrichment helpers (`enrichNodesWithQuestionCounts`, `enrichNodesWithFeasibility`) to both paths.
- After any DB write that affects displayed weight, call `invalidateDimensionCache(TreeState.currentDimensionId)` BEFORE `loadHierarchy()` — otherwise the dimensional cache serves stale data and the UI shows pre-write values until F5.
- Backend pytest won't catch dimension-cache issues — they're frontend-only. Write a `wimi-test` regression scenario when asserting "after write X, UI shows new state."

### Reference docs

- `docs/planning/POLYHIERARCHY_MIGRATION.md` — DAG migration design (🟡 partially landed; cross-dimensional edges still a Non-Goal)
- `docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` — Arc 1 design doc (✅ Complete)
- `docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md` — Arc 1 10-stage rollout (✅ Complete, Stage 10 deferred)
- `docs/guides/SHARED_SUBJECTS.md` — student-facing polyhierarchy explainer
- `docs/guides/BRIDGE_METHODS_HYBRID_WEIGHTS.md` — weight bridge surface reference

## Frozen Mode (Critical)

Always use this pattern for file access — the app runs both in dev and as a PyInstaller executable:

```python
if getattr(sys, 'frozen', False):
    base_path = Path(sys.executable).parent
    internal_dir = base_path / '_internal'
else:
    base_path = Path(__file__).parent.parent
```

- **Development:** Web assets at `src/web/`, F5 reload, F12 dev tools enabled
- **Frozen:** Web assets at `_internal/web/`, dev tools disabled

### Media Handling

Custom `media://` URL scheme served by `MediaSchemeHandler`. Media stored in `app_data/media/` with UUID filenames. Images can be linked to entries and dimensions.

## Entry Point

`run_wimi.py` is the launcher; actual initialization is in `src/app/main.py`. On startup it detects frozen vs dev mode, sets up a demo user, initializes the plugin system, and registers the `media://` URL scheme **before** creating `QApplication`.

## Testing

Pytest markers: `@pytest.mark.unit`, `.integration`, `.slow`, `.database`. Coverage is enforced at 80% minimum on `src/database`. Key fixtures in `conftest.py`: `temp_dir` (isolated test databases), `master_db`, `admin_user`, `master_db_with_users`.

**Reference fixture:** `tests/fixtures/usmle_step1_outline.txt` (1,327 lines, full 2025 USMLE Step 1 content outline) is available for tests that need a realistic hierarchy with known multi-parent topics (DVT, hypertension, sepsis, etc.). Also exposed through the seeder `seed_usmle_outline` for `wimi_test`-driven regression scenarios.

**UI regression / exploratory testing:** The driver library lives at `wimi_test/` (repo root) — a pychrome-based CDP wrapper that pytest scenarios import directly. `src/wimi_test_mcp/` is a thin MCP server wrapping that same library so Claude Code (via the `wimi-test` MCP) can drive interactive sessions. Pytest scenarios live in `tests/wimi_test/scenarios/` (`@pytest.mark.regression`). See `docs/planning/TEST_INFRASTRUCTURE.md`.

**CI:** `.github/workflows/test-infrastructure.yml` runs on push/PR to `master` (Ubuntu, Python 3.11). It executes `pytest -m "not slow"` then `pytest -m slow` with `QT_QPA_PLATFORM=offscreen`. On failure, `pytest_artifacts/` (screenshots, console + network logs) is uploaded for 14 days. macOS and Windows runners are deferred — see `docs/testing/CI_SETUP.md`.

## Dependencies

**Python (runtime, `requirements-prod.txt`):** PyQt6, PyQt6-WebEngine, Pillow, python-json-logger, mcp, pyinstaller — versions pinned to the active dev venv; bump deliberately
**Python (test, `requirements-test.txt`):** pytest, pytest-cov, pytest-mock, pytest-timeout, coverage, pychrome (CDP driver for wimi_test)
**Frontend (bundled):** D3.js v7 (visualizations), Fuse.js v7 (fuzzy search), TinyMCE (rich text), KaTeX (math rendering)

No linter/formatter is wired up — there is no `pyproject.toml`, `.flake8`, or `mypy.ini`. If you want black/mypy/flake8, configure them first.

## MCP Tools Available

- **`wimi-db`** (configured in `.mcp.json`, runs at `127.0.0.1:8000/sse`) — read-only access to user databases for verification and inspection. Tools include `list_users`, `list_entries`, `list_sessions`, `list_exams`, `list_sources`, `get_subject_tree`, `search_subjects`, `get_dimensions`, `get_analytics_overview`, `get_subject_analytics`, `get_tag_analytics`, `get_database_stats`, `get_entry_detail`, `get_entry_notes`, `get_goals`, `get_preferences`, `get_study_streak`, `get_timer_rounds`, `verify_mixin_decomposition`, `check_dimensions_enabled`. Prefer these for verification tasks over writing one-off SQLite queries.
- **`wimi-test`** — spawns WIMI in test mode and drives the UI over CDP (pychrome → QtWebEngine remote debugging). One active session per server. Tools include `start_session`, `end_session`, `get_session_status`, `navigate_to`, `click`, `fill`, `wait_for`, `eval_js`, `dump_dom`, `screenshot`, plus `get_console_log` / `get_network_log` / `get_bridge_log` capture streams. Design docs: `docs/planning/TEST_INFRASTRUCTURE.md` §8, `docs/planning/PYCHROME_MIGRATION.md` (the Playwright→pychrome rewrite since Qt's CDP surface lacks the `Browser` domain).
- **`forgejo`** (user-scope) — read/write access to the private Forgejo remote for repo browsing, PR/issue ops, file CRUD via API, and reading commit history. Cannot substitute for `git push` (creates server-side commits with different SHAs and per-file granularity).

## Documentation

| Document | Purpose |
|----------|---------|
| `docs/planning/FUTURE_VISION.md` | **Primary reference** — roadmap, status, idea parking lot |
| `docs/PLUGIN_DEVELOPMENT.md` | Plugin development guide |
| `docs/architecture/completed_database_tables.md` | Database schema reference |
| `docs/BUILD_WINDOWS.md` / `docs/BUILD_MACOS.md` | Build instructions |
| `docs/handoff/INDEX.md` | Handoff tracking index |
