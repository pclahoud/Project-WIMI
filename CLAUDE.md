# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**WIMI (What I Missed It)** is a metacognitive exam preparation tool that helps students analyze their mistakes through reflection. Built with PyQt6 + QWebEngineView for the desktop shell, SQLite for data, and D3.js for visualizations. Cross-platform (Windows + macOS).

Production-ready for personal use. See `docs/planning/FUTURE_VISION.md` for roadmap and status.

## Parked Decisions (owner sign-off required)

These are product decisions the owner has not made yet. They are tracked as issues on the private Forgejo tracker, each assigned to the owner. **Do not implement, "fix", or quietly settle any of them until the owner has recorded a decision in the issue**, even if a fix looks obvious or falls out of adjacent work. When a decision lands, implement it, close the issue, and delete its line here.

- **#154 — how should the capture pane and the question-bank browser pane coexist?** Both put a
  second `QWebEngineView` with its own persistent profile in the right half of `MainWindow`'s
  splitter: master's `browser_pane.py` and the capture branch's `capture_pane.py` (#145). The
  rebase onto master kept **both, unchanged**, adding only index-aware splitter sizing. Options
  (1) capture becomes a mode of the browser pane, (2) separate but mutually exclusive, (3) capture
  replaces it, (4) keep both until capture resumes are in the issue. Until the owner answers, do not
  merge, remove or re-home either pane on `feature/ai-capture`.

## Forgejo Is the Project Tracker

Issues, decisions and cross-machine coordination live on the private Forgejo repo (the `origin` remote), driven through the `forgejo` MCP tools. `docs/bugs/bugs.md` is legacy; do not add to it.

- **Before starting work in an area**, list the open issues for it (`issue_list`, label `Area/<area>`) and re-read *Parked Decisions* above. An issue titled `[decision needed]` or assigned to the owner with that marker is off-limits until the owner has answered in it.
- **Found a bug you are not fixing now?** File it, do not leave a TODO. Follow the shape of #2–#11 and the repo's bug report template: title prefixed `[bug]`, then Surface / What happened / What should have happened / How it was confirmed / How to reproduce / Evidence and starting points. Say which branch and commit you saw it on.
- **Found a product question?** File it as `[decision needed]`, assign it to the owner, lay out the options, and add it to *Parked Decisions*. Never settle it inside another fix.
- **Labels** are `Area/*` (Analytics, Entry Browser, Entry Form, Harness, Hierarchy, Settings), `Kind/*` (Bug, Documentation, Enhancement, Feature, Security, Testing), `Priority/*` (Critical, High, Medium, Low), `Reviewed/*` (Confirmed, Duplicate, Invalid, Won't Fix), `Status/*` (Blocked, Need More Info, Abandoned) and `Compat/Breaking`. The MCP tools accept label names (case-insensitive) or ids; an unknown name is rejected with the list of available labels, so an unlabelled issue is a choice, not an accident.
- **Commits reference issues** (`#N` in the body; `Closes #N` on master closes it). When a fix lands, comment on the issue with the commit hash and what verified it; close only after the verification ran.
- **Two machines share branches through Forgejo.** Fetch before you start, push small commits often, and never rewrite pushed history. The `forgejo` MCP cannot substitute for `git push` (server-side commits get different SHAs).
- The `forgejo` MCP server is the owner's own `forgejo-mcp` project. A capability it lacks is a request to that project, not a reason to script around the API here.

## Build & Run Commands

```bash
# Development mode (F5 reload, F12 dev tools)
python run_wimi.py

# Run all tests (coverage enforced at 80% on src/database).
# --ignore=tests/spike is needed in any fresh environment: those files import the
# removed real_ladybug library at module level and abort collection (see Testing).
pytest --ignore=tests/spike

# Skip end-to-end UI scenarios that spawn WIMI (fast iteration loop)
pytest -m "not regression and not slow" --ignore=tests/spike

# Run only UI regression scenarios (tests/wimi_test/scenarios/). They spawn a real WIMI.
pytest -m regression --no-cov

# Headless needs BOTH variables, and --disable-gpu is not about lacking a GPU:
# under QT_QPA_PLATFORM=offscreen the child dies with SIGTRAP (returncode -5, no
# message even with --enable-logging=stderr) on its first navigation unless GPU
# use is switched off. Verified on a box WITH an Intel HD 530 and /dev/dri
# present; the startup log shows "QRhiGles2: Failed to create context". Reproduced
# on 10cd3f3, so it long predates the browser pane. --no-sandbox does not help;
# --disable-gpu alone is enough. Confirmed working: 26/26 regression scenarios.
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu \
  pytest -m regression --ignore=tests/wimi_test_mcp --ignore=tests/spike --no-cov

# Run a single file or test. Add --no-cov: the 80% coverage gate fails on partial runs.
pytest tests/database/test_user_db_phase1.py --no-cov -v
pytest -k test_name --no-cov

# Broaden coverage to all of src (default scope is src/database per pytest.ini)
pytest --cov=src --cov-report=term-missing

# CI gate — every @pyqtSlot must be paired with @instrumented_slot
python scripts/check_instrumented_slots.py

# CI gate — the subject-import guide's generated copies match their source.
# --write regenerates them after editing docs/examples/subject_tree_import_format.md.
python scripts/check_import_guide_sync.py

# CI gate — no print() in src/ or run_wimi.py may contain a non-ASCII literal.
# Windows encodes print() with the console codepage whenever stdout is
# redirected, so an emoji OR an em dash raises UnicodeEncodeError from inside
# print() and killed the frozen build before its window appeared (#137).
# src/console_encoding.py fixes it at runtime; this stops it coming back.
python scripts/check_ascii_prints.py

# CI gate — no first-party CSS may use `:empty`. QtWebEngine 6.10 stops
# re-invalidating it, so a container that gains its first child keeps
# display:none and renders at ZERO PIXELS with no error (#134, #136, #141).
# Use `:not(:has(*))`, which invalidates correctly on both engines. No
# allowlist by design.
python scripts/check_css_empty_selector.py

# BUILD gate — the environment matches requirements-prod.txt. Both build
# scripts run it first and refuse to build on a mismatch (#135). It also checks
# the RUNTIME Qt/Chromium versions, not just the wheel pins: PyQt6-Qt6 and
# PyQt6-WebEngine-Qt6 carry the binaries that actually get bundled, and they
# were unpinned until a drifted Windows machine shipped Chromium 134 while
# every test ran 130 (#134, #136 for what that broke).
python scripts/check_build_env.py

# Build executables. No argument = RELEASE build, which refuses --test-mode;
# `test` = TEST build (same spec + one runtime hook), the only kind that
# accepts it and the only kind WIMI_TEST_BINARY can drive (#144).
./build_windows.bat          # Windows release → dist/WIMI/WIMI.exe
./build_windows.bat test     # Windows test    → dist/WIMI-test/WIMI.exe (never distribute)
chmod +x build_macos.sh && ./build_macos.sh       # macOS release (arm64 only, #59)
./build_macos.sh test                             # macOS test → dist/WIMI-test/
```

## Architecture

### Three-Layer Design

1. **Backend (Python/SQLite):** `src/database/` — domain mixins composed into `UserDatabase` and `MasterDatabase`
2. **Bridge (PyQt6 WebChannel):** `src/app/bridge.py` — `@pyqtSlot` methods exposed to JavaScript, composed from bridge domain mixins
3. **Frontend (HTML/CSS/JS):** `src/web/` — pages, D3.js visualizations, Fuse.js fuzzy search

### Mixin Composition Pattern (Critical)

Both the database layer and the bridge layer use **mixin composition**, not monolithic classes. This is the most important architectural pattern in the codebase.

**Database layer:** `src/database/user_db.py` (~110 lines) composes 22 mixins from `src/database/domains/`:
- `SharedHelpersMixin`, `SchemaMigrationMixin`, `PreferencesMixin`, `ExamContextMixin`, `HierarchyMixin`, `EdgesMixin`, `TagsMixin`, `SessionsMixin`, `TimerMixin`, `SourcesMixin`, `EntriesMixin`, `MediaMixin`, `NotesMixin`, `AnalyticsMixin`, `AdvancedAnalyticsMixin`, `GoalsMixin`, `DimensionsMixin`, `AliasesMixin`, `ImportExportMixin`, `SubjectImportMixin`, `PluginDataMixin`, `GraphMixin`

**Bridge layer:** `src/app/bridge.py` (~120 lines) composes 28 mixins from `src/app/bridge_domains/`:
- Domain mixins (e.g., `EntryBridgeMixin`, `AnalyticsBridgeMixin`, `MediaBridgeMixin`, `EdgesBridgeMixin`, `WeightBridgeMixin`, `DimensionAnalyticsBridgeMixin`, `TagBridgeMixin`, `ProfileBridgeMixin`, `ProfileTransferBridgeMixin`, `BrowserPaneBridgeMixin`) plus `SerializerMixin`, `UtilityBridgeMixin`, `PluginDispatchMixin`, `PluginManagementMixin`, and `McpServerBridgeMixin`.

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
- A versioned `MigrationRunner` (`src/database/migration_runner.py`) replaces the old chained `_ensure_*_schema()` pattern. Open paths apply pending migrations and stamp `schema_migrations`. See `docs/planning/MIGRATION_RUNNER.md`. Do **not** add new `_ensure_*_schema` methods — write a numbered migration module instead. **Currently at user m001–m007, m009, m010, m015–m022.** The gaps are intentional and must stay: m008 is reserved for the assessments branch, and m011–m014 belong to the **AI capture feature, a paused feature branch** (`feature/ai-capture`, owner's decision on #145): earlier capture builds stamped them into real databases and the runner treats a stamped version as applied, so master never reuses them and **any new migration must be numbered 23 or higher** (m022 is taken). m015's and m021's docstrings still say "abandoned" — they are migration modules, and editing one changes its checksum for every database that applied it. m004 introduced `subject_edges`; m005 `primary_parent_id`; m006 added `edge_id` to weight history + broadened `change_type` enum; m007 added the `length_kind`/`length_min`/`length_max`/`length_typical`/`length_note` triple to `exam_contexts`; m009 added `entry_note_attachments`; m010 backfilled default error-type definitions; m015–m017 added the browser-pane columns (`question_sources.pane_desktop_site`/`pane_last_opened_at`, `user_preferences.pane_*`); m018 added the subject delete journal (`subject_nodes.deleted_batch_id`, `subject_delete_batches`, `subject_delete_batch_items`); m019 added `subject_relations` and rebuilt `subject_delete_batch_items` to widen its `item_type` CHECK with `relation_hidden`; m020 added `subject_nodes.import_id` (the subject-tree import's stable id, uniquely indexed per exam context + dimension and only over `status='active'` rows); m021 added `profile_identity`, `device_settings` and `device_source_settings` (see *Device Identity & Profile Identity* below). m022 added `user_preferences.efficiency_show_confidence_band` (#133). **Master is at m002** — m002 added the `users.profile_uuid` mirror, so a new master migration must be numbered 3 or higher. Migration tests live in `tests/database/migrations/` and run a `MigrationRunner` over a partial registry against the `fresh_conn` fixture.
- All write operations use `self.transaction()` context manager from `BaseDatabase`. **It is re-entrant and only the outermost block commits** (#95): depth 1 issues an explicit `BEGIN`, depth ≥ 2 a `SAVEPOINT`, so a method that opens a transaction may freely call others that open their own and the whole composite is atomic. An inner failure discards only the inner work and leaves the enclosing transaction alive to decide; an outer failure discards everything. The explicit `BEGIN` is load-bearing and not tidiness — a `SAVEPOINT` with no transaction open *starts* one, and SQLite commits it when that outermost savepoint is `RELEASE`d, so without the `BEGIN` an inner block would commit an outer block that had not written yet. `tests/database/test_transaction_nesting.py` asserts the matrix. The one thing it cannot defend against is a bare `self.conn.commit()` called from inside a transaction block; no code path does that today (every bare commit in `src/database` sits in a top-level-only method) and none may start.
- **Connection settings are stated in `_connect`, not inherited.** WAL, `foreign_keys=ON`, `synchronous=NORMAL`, `analysis_limit=1000`, and `autocommit` pinned to `LEGACY_TRANSACTION_CONTROL`; `close()` runs `PRAGMA optimize` (best-effort — a failure there must never stop the close, because a leaked handle is a real problem on Windows and stale planner stats are not). `tests/database/test_connection_pragmas.py` asserts each against a live connection.
  - **`synchronous=NORMAL` is the documented counterpart to WAL.** Writers stop syncing the WAL on every commit, which matters because autosave commits a field at a time. It **cannot corrupt the database**; what it gives up is the last few committed transactions on a power cut or kernel panic. An application crash is still safe. `OFF` can corrupt and must never appear.
  - **`autocommit=False` (PEP 249 mode) was measured and rejected — do not "modernise" it back.** CPython's docs recommend it in general, and it is wrong here twice over. It keeps a transaction open at all times, so `PRAGMA journal_mode = WAL` fails outright (*"cannot change into wal mode from within a transaction"*) — `_connect` itself would raise. Worse, a permanently-open transaction means **any bare `SELECT` pins a read snapshot until the next commit**, and a pinned snapshot makes `PRAGMA wal_checkpoint(TRUNCATE)` return `busy=1` — the exact condition that leaves a copied database missing its WAL tail (#155). In a GUI process holding one connection for hours that would turn a rare race into the normal case. Both halves are pinned by tests, including a negative control proving legacy mode does *not* pin a snapshot. What PEP 249 mode would have bought — making #95's savepoint-commits-the-parent shape impossible — the explicit `BEGIN` already buys.
  - The pin exists because the stdlib default **is documented as changing to `False` in a future Python release**. Stating it means a Python upgrade cannot change this layer's semantics without a diff. It is applied only when `sqlite3.LEGACY_TRANSACTION_CONTROL` exists (3.12+); CI still runs 3.11.
- SQLite uses WAL mode with foreign keys enabled
- Exception types: `BaseDatabaseError`, `DatabaseConnectionError`, `DatabaseIntegrityError`

### Frontend Pages

HTML pages in `src/web/html/`: index (dashboard), question_entry, analytics_dashboard, entry_browser, entry_detail, tree_editor, session_setup, settings, subject_deep_dive, profile_select (launch profile picker), error-viewer, plus `wizards/exam_wizard.html`. Logical route names for tests are in `wimi_test/routes.py` (e.g. `entry-form`, `tree-editor`, `settings`).

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

### Counting vs finding (settled in #13)

> **Counting is primary-only. Finding is all tags.**

A surface that *totals* mistakes — Top Subjects, the sunbursts, the weight quadrant — filters to
`mapping_type='primary'`, so a shared subject cannot inflate its own total through secondary
"also tested" tags. A surface that *retrieves* entries — the entry browser's subject filter,
search — includes secondary tags, because the student looking for their DVT questions wants
every entry that mentions DVT. Listing is not measuring.

The same issue settled what a subject filter means: filtering by S returns entries tagged S
directly **regardless of their chosen parent context**, plus entries on S's descendants that
route through S. The leaf is not an ancestor — it is the subject the entry actually carries, so
a parent context narrows which chain an entry rolls up through without making it stop being
about S.

### Subject delete semantics (settled in #15)

Deleting a subject is a **soft** delete that cascades by edges, never by the legacy
`subject_nodes.parent_id`. `HierarchyMixin.plan_subject_delete` is the single source of truth:
`get_subject_delete_preview` (the modal) and `delete_subject_subtree` (the mutation) both
consume it, so the preview cannot drift from what happens.

- **The cascade is a fixpoint, not a recursive walk.** Archive the target, then repeatedly
  archive any node in its *former* descendant set whose surviving parent set is empty, until a
  pass changes nothing. A node reachable by two paths inside the doomed subtree (`P→A→X`,
  `P→B→X`) is only an orphan after *both* are gone, which no single depth-first pass can know.
  A surviving parent edge means an edge from a node that is still `active`.
- **Shared children are detached, not deleted.** A child is archived only when the deleted
  parent held its last surviving parent edge. The edge from an archived parent to a *surviving*
  child must be removed — a child left holding that row is neither a root (it has an incoming
  edge) nor anybody's child (its parent is filtered by status), i.e. invisible. Every other
  edge is left in place so restore only replays the removed ones.
- **`deleteSubjectNode` has two registered arities.** `(int)` is the pre-#15 contract and still
  means "delete the exclusive children too" — `src/web/js/import_export.js` calls it. `(int,
  bool)` carries the promote choice. QWebChannel publishes both and resolves by argument count;
  don't collapse them.
- **An orphaned `entry_subject_mappings.primary_parent_id` is nulled.** m005 already declares
  the column `ON DELETE SET NULL`; the FK never fires only because the delete is soft. Without
  it those entries roll up *nowhere* — §5.4 scopes a pinned entry to that parent's chain alone,
  and an archived parent is in no scope set.
- **Every delete is stamped with a batch id** and journalled into `subject_delete_batches` /
  `subject_delete_batch_items` (m018). Nothing reads the journal yet: restore + the Archived
  panel are #37, purge is #38. Keep writing it.
### Subject import semantics (settled in #67)

> **Import is a merge behind a preview. Entries outrank the blueprint.**

`SubjectImportMixin.plan_subject_import` (`src/database/domains/subject_import.py`) is
the single source of truth, exactly as `plan_subject_delete` is for delete:
`previewSubjectHierarchyImport` (the modal) and `apply_subject_import` (the mutation)
both consume it, and the apply re-derives nothing.

- **Matching is on the file's optional `id`** (`subject_nodes.import_id`, m020), and on
  name-and-path where there is none. An existing subject **adopts** an id the first time
  a file carries one for it — that is the upgrade path for trees imported before ids
  existed. Without ids a rename is a remove-plus-add, and the preview says so
  (`rename_blind`). Export writes `import_id` back out as the file's `id`; it is **not**
  the database row id.
- **A subject carrying entries is never removed by an import.** Survival is bottom-up: a
  subject survives if the file lists it, *or* it carries entries, *or* anything beneath
  it survives. That last clause is what stops an import archiving a chapter the file
  dropped while entries still sit on one of its topics — the #15 silent-rollup-loss
  class, reached through import. Kept subjects are reported as `kept_in_use` with entry
  counts and ids; the modal links them into the entry browser so the student can re-tag.
  There is no bulk reassign tool (deliberate, per #67's scope note — file it separately).
- **Removals go through `delete_subject_subtree`**, so an import's removals are the same
  soft delete, edge handling and restore journal as a manual one. Never a second path.
- **An empty file removes nothing.** A misspelled `root_nodes` key arrives at the planner
  as an empty list and must not read as "remove every subject".
- **Edges the file does not mention are left alone** — a second parent the student added
  by hand is not the blueprint's business. Only the *primary* edge follows the file.
- **The Merge/Replace radio is gone.** "Merge" meant *append*, which was the bug;
  "Replace" additionally deleted in-use subjects, which decision 3 forbids. Don't
  reintroduce either without reopening #67.
- **The import format guide is generated, not copied (#69).**
  `docs/examples/subject_tree_import_format.md` is the single source. The embed in
  `src/web/html/tree_editor.html` (which the ❓ help modal renders, embedded because a
  frozen build has no `docs/`) and `docs/examples/subject_tree_import.schema.json` (the
  published JSON Schema, lifted from the guide's own `## JSON Schema` section) are both
  produced by `python scripts/check_import_guide_sync.py --write`. The same script with
  no arguments is the gate, and `tests/test_import_guide_sync.py` runs it against the
  real tree. Edit the markdown, regenerate, commit all three. Hand-syncing had already
  failed: #61 and #62 both landed in the embed and never reached `docs/`.
- The modal renders the guide with `parseMarkdown` in `import_export.js` — a regex
  renderer, not a library. **An empty table cell is dropped** (shifting every later
  column), `>` never becomes a blockquote, and each ordered-list run renumbers from 1.
  A test asserts the guide avoids all three; none of them errors, they just render
  wrong in the shipped app.

### Subject import weight semantics (settled in #64)

> **A weight is a percentage of the whole exam, at any depth. Import what the document
> says; warn; never rescale.**

Stated for students in the guide, restated at the top of `subject_import.py`, and
asserted one-test-per-decision in `tests/database/test_subject_import_weight_semantics.py`.
Three of the five are enforced by an **absence**, so they are easy to "fix" back:

- **A child may exceed its parent.** There is no parent/child weight comparison anywhere
  in the planner, and adding one is the bug. The nesting comes from the student's tree,
  not the blueprint: Step 2 CK publishes Nutrition (15–20%) and Multisystem Processes &
  Disorders (4–8%) as **sibling** rows, so a student who files nutrition under
  multisystem lands a 15–20% child inside a 4–8% parent using two real published
  numbers. It also follows from the rule above with no example at all — the three Step 2
  CK tables are overlapping partitions of the same items (84–153%, 78–113%, 97–142%), so
  any tree mixing axes cross-cuts.
- **Coverage is surfaced, never corrected.** `plan_subject_import` returns `coverage`
  (the summed low/high of the file's *top-level* weights) and warns only when that band
  does not span 100%. Real files totalled 78–113% and 84–153%; USMLE's own Clinical
  Science table exceeds 100% by design. Normalising would store numbers that do not
  match the source the student copied from.
- **An omitted weight is 0% on import** — the blueprint did not weight it. The tree
  editor's empty weight field still means "share the remainder"; that text at
  `tree_editor.html`'s weight help is deliberately *not* the same rule.
- `0` is data (Step 2 CK publishes tasks at 0%), and `derived` never implies `locked`.
- **A file's `weight.source` and `weight.locked` are documentation, not data (#104,
  owner's decision (a), 2026-09-22).** The importer reads `value`/`low`/`high` and
  nothing else, so every imported subject is `user_defined` and unlocked; locking is
  done in the tree editor. Another rule enforced by an absence —
  `test_104_source_and_locked_in_a_file_are_not_applied` is the guard.
- Locked wins over auto-balance, which needed no code: `rebalance_sibling_edge_weights`
  is opt-in and already excludes anchored and `weight_locked` edges.

Everything checkable is a **warning** on the plan, carried into the apply's `warnings`
and raised as toasts. Nothing about a weight aborts an import.

### A subject's level comes from `level_type`, never from depth (#49, #82)

> **Read the stored level. Suggest from the stored level. Keep the user's word for it.**

`subject_nodes.level_type` is the level. Tree depth is not, and substituting it is unsound
rather than merely inaccurate: in a polyhierarchy a node has no single depth, and
`buildFlatNodeMap` says itself that `_parent` is "the parent of whichever appearance was
visited last and is best-effort". A depth-derived level is therefore ambiguous (which
appearance won the race?) and inconsistent (one subject wearing two level names in one tree).

- **Displaying** a level: `getNodeLevelName(node, fallbackDepth)` in `tree_editor.js`. #49
  fixed four display sites; `getNodeLevel` remains only as the fallback for a payload with no
  `level_type` at all. Do not reach for it because it is convenient.
- **Suggesting** a level for a new child: `suggestChildLevelName(parentNode)` — the parent's
  stored level, one step along `TreeState.hierarchyLevels`. This is the #82 half, and it is a
  **write** path: the Add Child modal's pre-filled default is what most users accept, so a
  depth-derived suggestion is what actually lands in the column.
- **An unconfigured level name is appended to the dropdown and repeated, not replaced.** An
  imported outline brings its own vocabulary (the in-app SAT example uses Section / Domain /
  Skill) and `update_hierarchy_level` renames a level without back-filling `subject_nodes`, so
  a node carrying a name the list does not have is normal. There is no derivable "one below
  Domain": repeat it. The appended option is for that modal instance only — **never write it
  into `hierarchy_level_definitions`**.
- `HierarchyBridgeMixin._derive_child_level_type` (`src/app/bridge_domains/hierarchy.py`) is the
  **one** backend derivation, with the same two fall-throughs (bottom of the list, name not in
  the list), and returns `None` only when there is nothing to derive from — no parent, no such
  active parent, no stored level — leaving the caller's `'System'` default for a root. **Both**
  create-a-subject slots call it for a caller that omits `level_type`: `createSubjectNode` here
  and `createSubjectNodeWithWeight` in `bridge_domains/weights.py`, reached as `self.` because
  mixins share the composed instance. #82 fixed the first (its `except ValueError: pass` dropped
  through to the literal `'System'`); #106 was the second still doing exactly that, so a child of
  a `Topic` was a `System` through one slot and a `Subtopic` through the other. Don't reintroduce
  a per-slot default — `tests/app/test_bridge_child_level_type.py` parametrises every derivation
  test over both slots for that reason.

### Two totals on the subject sunburst (settled in #6)

The "By Subject" sunburst's **centre is a distinct entry count** — `distinct_entries` in the
`getSubjectHierarchyWithMistakes` payload, read from `get_analytics_overview` so it is literally
the number the "Total Entries" card above it shows and cannot drift from it. The **arcs stay
per-parent rollups**, so they visibly sum to *more* than the centre whenever a shared subject
routes through several parents (11 entries can draw 5 + 6 + 3). That non-additivity is intended
and the ⓘ tooltip in the card header exists to say so. Do not "fix" the arcs to sum to the
centre, and do not re-sum the arcs client-side to produce the centre.

### Weight confidence is not part of the efficiency score (settled in #133)

> **Confidence describes the measuring stick. The score describes the student.
> Show the uncertainty; never price it in.**

`_calculate_efficiency_score` is `100 - Σ(deviation × weight_factor)` and **nothing
else**. Stage 9 multiplied each subject's *penalty* by a confidence factor keyed on
`subject_edges.weight_source`, which inverted the whole thing: a smaller confidence
makes a smaller penalty and therefore a **higher** score, so "we do not know where
this weight came from" was the top-scoring state and the best-provenance input
scored worst. Three errors compounded, and each is now prevented by an **absence**:

- **The direction.** `_WEIGHT_SOURCE_CONFIDENCE` / `_WEIGHT_SOURCE_DEFAULT_CONFIDENCE`
  are deleted. `tests/database/test_efficiency_score_confidence.py` asserts the
  constants are gone and that the score is identical across every `weight_source`
  value *and* with the field absent. That parametrised test is the regression guard —
  do not consolidate it away.
- **The safeguard was the amplifier.** `min(range_confidence, source_confidence)` was
  documented as making "the less certain signal dominate"; given the direction it
  systematically selected whichever factor inflated the score most. `range_confidence`
  (`max(0.5, 1 - range_width/20)` — a vaguer range penalised *less*) went with it, so
  **range width is not in the arithmetic either**. What a range still does is move
  where the deviation is measured from: inside the band, from the midpoint; outside
  it, from the nearest bound.
- **Both "pessimistic" defaults discounted.** `row['node_weight_source'] or 'derived'`
  in `get_subject_exam_weight_analysis` kept the NULL default from ever firing. It
  survives as a **display bucket** for the "Weight Sources" card and nothing more.

**Inverting the multiplier was considered and rejected.** If confidence measures data
quality, inverting it lowers a student's score because their blueprint carried no
provenance metadata — attributing a data problem to the person. It does not belong as
a linear multiplier on the penalty in either direction.

**How the uncertainty is shown is a student setting.** `user_preferences.efficiency_show_confidence_band`
(m022) — **off by default**, because `_get_efficiency_rating`'s bands (`>= 85`
Excellent, …) assume a scalar and defaulting to a band would mean rethinking the
rating vocabulary in the same change. Off is **not a degraded mode**:
`weight_source_distribution` was already bundled into the `get_weight_analysis`
payload for the Confidence breakdown card, so the provenance is on the page either
way. It is **user-level, not device-local** — #126/#129's test is whether a value
denotes a machine, and a display preference does not — so it is deliberately absent
from `DEVICE_LOCAL_SETTING_FIELDS` and travels in a `.wimi`.

`_build_efficiency_band` takes its width **from the weights, not the deviations**:
`half_width = Σ midpoint²/100` over subjects whose `weight_source` is not `official`.
A band derived from the deviations would collapse at perfect alignment, and a student
perfectly aligned against fifteen hand-typed weights has the *least* trustworthy 100
on offer. The payload always carries `efficiency_band`; `weight_analysis.js` decides
whether to draw it, so "off" is never a path that stops computing something.

**This unblocked #104.** The importer writes `weight_source = 'user_defined'` for every
imported subject; deciding #104 in favour of applying `weight.source` would have
flipped those to `official` and visibly dropped every user's efficiency score as an
unannounced side effect of an import change. That coupling is gone — and #104 was
then decided the other way anyway (see *Subject import weight semantics*).

**What this fix did *not* address (#146):** the score still cannot report a bad
result. On a realistic 15-row blueprint every distribution a student could plausibly
produce lands between 88 and 99 and rates **Excellent**; `Fair` and `Needs
Improvement` are unreachable. `weight_factor = midpoint/100` is the cause, so the
score gets *less* discriminating the more granular the blueprint is. And perfect
alignment scores 99.1, not 100, because the blueprint's midpoints sum to 118.5% —
which #64 guarantees will keep happening, since WIMI never rescales. That is a
separate product question about what the score is *for*; do not "fix" it by
normalising inside `_calculate_efficiency_score` without reading #146 and #64.

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

## Device Identity & Profile Identity (settled in #126 / #129)

> **The device id names a machine and must not travel. The profile id names a
> profile and must.**

Two identifiers with opposite travel rules, and swapping them would be a quiet,
serious bug. `ankiconnect_host = 'localhost'` is the canonical case: it
**denotes a different machine on each device**, so copying it is wrong even when
the two values are byte-identical.

| | where it lives | travels in a `.wimi`? |
|---|---|---|
| **device id** | `app_settings` in the **master** database (`MasterDatabase.get_device_id`) | **No** — `users.db` is not packed |
| **profile id** | `profile_identity` in the **user** database (`UserDatabase.get_profile_uuid`) | **Yes** — it rides inside the snapshot |

- **`user_preferences` is user-level only.** m021 moved `pane_last_url`,
  `pane_split_app_pct`, `pane_zoom_pct`, `ankiconnect_enabled`,
  `anki_integration_enabled`, `ankiconnect_host`, `ankiconnect_port`,
  `mcp_server_enabled` and `mcp_server_port` into `device_settings`, keyed by
  device id. The list is `DEVICE_LOCAL_SETTING_FIELDS` in
  `src/database/device_local.py` — **one definition**, imported by both mixins,
  the bridge and `MainWindow`, because a column that is device-local in one
  place and user-level in another is silent either way.
- **`pane_open_mode`, `pane_shortcut_opens` and `pane_default_source_id` stay
  user-level.** The first two are stated preferences with a control. The third
  references a `question_sources` row, and that row travels in the same
  snapshot, so the id denotes the same bank on the other machine. *That* is the
  test — does the value denote a machine? — not "is it pane-shaped".
- **The legacy columns are still on `user_preferences` and `question_sources`.**
  Dropping them means rebuilding tables of real user data. The guard that keeps
  them unread is in code: they are gone from the `UserPreferences` dataclass,
  and `update_preferences` raises a `ValidationError` naming
  `update_device_settings()` if handed one. Don't "finish the job" by dropping
  them without a reason better than tidiness.
- **The UI still sees one flat object.** `get_all_settings()` /
  `update_settings()` on `UserDatabase` merge and route; `getUserPreferences` /
  `updateUserPreferences` call those, so `settings.js` needed no change. The
  split is a storage-and-travel property, not something the page models.
- **m021's handover row.** A migration cannot know the device id (it is in
  another database), so m021 parks the moved values under the reserved device id
  `__pre_m021__`. `UserDatabase.__init__` claims it **immediately after the
  runner**, not lazily on first read: an unclaimed row reaching an archive would
  hand the *receiving* machine the sender's AnkiConnect host, which is the exact
  bug being fixed.
- **`users.profile_uuid` is a mirror, not the authority**, and is deliberately
  **not `UNIQUE`**. Two installs of one archive are a supported outcome —
  `install_profile_as_new()` forks on a name collision by design, and #22
  comment #1454 made "keep both" one of the two first-connect options. Import
  *detects* a duplicate and returns `already_installed_as`; choosing between
  copies is fork resolution (**#124**) and is not done in the import path.
- Every production `UserDatabase(...)` passes `device_id=master_db.get_device_id()`.
  Omitting it falls back to `UNKNOWN_DEVICE_ID`, which is correct for a test or a
  short-lived verify-open and wrong for a profile a student is using.

Files: `src/database/device_local.py`, `src/database/domains/device_settings.py`,
`src/database/migrations/user/m021_device_local_settings.py`,
`src/database/migrations/master/m002_profile_uuid.py`.

## Folder Sync (#123, #124, #147, #148, #149, #151)

A student picks a folder inside whatever cloud client they already run; WIMI
writes sealed, generation-named archives into it. **No provider APIs, no
OAuth.** `src/app/foldersync/`. Verified on two physically distinct Windows
machines against a real Box account on 2026-09-21 — both directions,
byte-identical, `parent_generation` chaining across machines — and the #148 /
#149 lineage model on 2026-09-22 (#148 comment #1947), with Box in the other
of its two storage modes. #151's catch-up — replacing the *open* profile's
database — passed on both Windows machines (#151), which matters because only
Windows refuses to replace a file that anything still holds open.

- **Two devices must never write the same path, and the device NAME cannot
  carry that.** The name is the hostname and hostnames are not unique: one
  corporate image, one VM template or two `DESKTOP-PC`s on one account all
  produce the same slug. Names are therefore
  `profile-<device>-<8 hex of device id>-gen-NNNN.wimi`. This was a real
  defect, not a precaution — two devices collided in testing and one
  generation silently replaced another. **Compare `ParsedName.device_tag`,
  never `.device`.** Names written before the tag parse with an empty tag,
  which is honest rather than invented.
- **The two sides of a fork normally share a generation number**, because
  each device numbered its push against a folder where the other's file had
  not yet appeared. So a fork side is addressed by **blob name** everywhere —
  staging, the report, resolution. A generation number there is a coin flip
  between the copy the student chose and the one they rejected. Three
  separate places had this bug.
- **Threading is part of the contract, not an implementation detail.**
  `prepare_*` and `finish_*` run on the Qt main thread and may touch
  `master_db`; `perform_*` runs on a worker and may touch **only** the sync
  folder. `base_db.py` records that nothing in this application writes from a
  second thread. `tests/app/test_foldersync_threading.py` enforces it by
  handing the worker a `master_db` that raises on any attribute access.
- **Looking must not download (#147).** `verify(allow_hydration=False)` on
  the display path: read the residency flag, do not hash. Measured on Box at
  1,474 ms hydrating against 49.7 ms local — a status check was pulling the
  whole archive to render a generation number. **A not-local blob is not a
  verification failure**; it yields `head_verified=False`, because failing it
  would name an older generation as head and tell a student their newest work
  is missing. `fetch`/`pull` still hashes; that is a pull-time guarantee.
- **Box Drive has two storage modes, and a machine can switch between them
  with no update.** Measured on the same machine and version (2.53.223) twelve
  hours apart (#123 comment #1951). *Streem* mode (overnight 2026-09-21/22):
  zero `SyncRootManager` entries, the Box folder a mount-point junction
  (`0xA0000003`) onto a FAT32-reporting virtual volume, and an evicted file
  `0x3000` (OFFLINE | NOT_CONTENT_INDEXED) with **no recall flag**.
  *Cloud Files* mode (morning 2026-09-22, after a Box restart): one
  `SyncRootManager` entry, the Box folder a Cloud Files root (`0x9000701A`),
  and an evicted file `0x400020` (RECALL_ON_DATA_ACCESS | ARCHIVE) with **no
  OFFLINE**. What makes Box pick one is not known. So `residency`'s mask must
  keep **both** `FILE_ATTRIBUTE_OFFLINE` and the recall flags: narrowed to
  either, it reports every evicted file in the other mode as resident —
  `determinate: True` and wrong. `NOT_CONTENT_INDEXED` carries no signal.
  The FAT32-derived facts (1-second mtimes, `max_component_len 260`) and
  Box's Streem access log belong to Streem mode only; in Cloud Files mode the
  log is empty and non-hydration can only be shown by attributes. The probe's
  `env --folder` reports the mode as `box_mode` — read that rather than
  inferring it from `box_cfctl_present` (shipped in both modes). **The Cloud
  Files filter hides the reparse point from almost everything**: `os.lstat`,
  `GetFileAttributesW` and `FSCTL_GET_REPARSE_POINT` (error 4390) all say
  there is none on a live sync root. Only the root's entry in its *parent's*
  listing (`FindFirstFileW`'s `dwReserved0`) shows the tag, and below the
  root even that reads 0 — so detection walks up to the root and believes
  any source that sees a reparse point (`reparse_signal` in the probe).
- **Fork resolution exports first, always, on every path (#124).** A verified
  export — read back, manifest parsed, entry count matched — or the flow
  aborts. "Keep both" leaves two profiles sharing one `profile_uuid`, which
  is legitimate — but **only one may be linked**, or they publish into one
  segment and fork forever.
- **A push's parent is the device's base, never the folder head (#149).**
  `SyncLink.base_sha256` is what the local copy descends from: the digest it
  last published, or installed from the folder. Reading the head instead let
  a device that had never fetched publish its content as a child of work it
  never had — no fork reported, the other device's newer generation silently
  out of the head. **Seen is not have**: `last_seen_generation` must never
  stand in for the base. Anything that installs a folder generation must
  record it (`install_from_folder`, or `record_install`), or the new
  profile's first push is a root and both devices are told their copies
  share no history.
- **Lineage is by digest; a fork is more than one head (#148).** Manifests
  carry `parents` (content lineage) and `supersedes` (sides a resolution
  chose against), both SHA-256 lists; `parents=None` is a legacy manifest and
  falls back to `parent_generation`. A generation is a head when nothing
  names it; ≥2 heads from ≥2 devices is a fork, and no shared ancestor is
  `first_connect`. **`supersedes` is not optional decoration**: a descendant
  of one side alone leaves the other side a head forever. Every sync archive
  carries a per-push nonce (`build_profile_archive(sync=...)`), because an
  unchanged profile built twice inside one second is otherwise byte-identical
  and would name itself as its own parent.
- **A choice stays on this device until the student sends it (#148, owner's
  decision).** Resolving writes nothing to the folder: it applies locally and
  is stored as `SyncLink.pending` (parents, supersedes, and the heads the
  student saw). The next push *is* the send. A head the student never saw
  makes the send refuse (`FolderMovedSinceResolution`) rather than retire
  unseen work. `keep_remote` onto the folder's only head needs no send and
  records none. The device whose copy was set aside learns it through
  `base_relation == 'superseded'`, offered as a `set_aside` fork through the
  same report and choices — not a second mechanism.
- **`keep_remote` on the open profile closes and reopens it (owner's
  decision).** The bridge's `_released_profile` closes the connection,
  `replace_profile` runs against a closed file (its guard is satisfied, not
  defeated), and `selectProfile` reopens on every exit, failure included.
  It passes `keep_existing_media=True`: sync archives carry no media (#125),
  and the default rename-aside-then-delete **deleted every image** on success.
- **The dashboard notice fires once per profile per launch (owner's
  decision).** `startFolderSyncStartupCheck` keeps the "once" in the bridge;
  the dashboard reloads on every navigation and cannot keep it. It fires only
  for something to act on — a fork, an unsent choice, a set-aside copy, or a
  newer copy to take (#151).
- **Taking a copy with no conflict is two moments, one operation (#151,
  owner's decisions).** A computer's *first* copy comes from the profile
  picker ("Get from a sync folder…"), because it has no profile open; the
  `install` job needs none. It installs, records the installed generation as
  the base, and **links** the profile to that folder. A profile already on
  the computer (same uuid) is never installed again from there — a second
  copy sharing a uuid must not be linked — and the picker offers the copy
  that is here. *Catching up* is `keep_remote` pointed at the head a
  `behind` status names, and needs no send. Before offering it, the panel
  compares this computer with its base (`local_changes`, the fork report's
  own figures via `figures_that_differ`): changes found → name them and offer
  **Send mine first** beside **Use the newer copy anyway**; none found → say
  only what was checked, because an edit to an existing entry moves none of
  those figures. An empty `differs` is never "nothing unsent".
- **`scripts/foldersync_probe.py`** is the two-machine harness. Its docstring
  carries the measured Box procedure: poll for arrivals with `os.listdir`
  (never `discover` or `look`, which open every manifest and so fetch it —
  since #147 neither hashes a blob that is not local), `residency` before
  anything reads, and — for Streem mode's access log — the
  `0x1`-means-different-things-on-a-directory trap.

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

**Images reach the page as base64 data URLs**, built by the bridge:
`_get_media_data_url` (`src/app/bridge_domains/_serializers.py`) calls
`MediaManager.get_thumbnail_as_base64` / `get_file_as_base64`, `bridge_domains/media.py`
puts the results in each attachment's `thumbnail_url` / `full_url`, and
`media_upload.js` sets them as `src`. There is **no custom URL scheme**: a
`wimi-media://` handler existed, was registered at every startup, and nothing ever built
such a URL, so it was deleted (#140, owner's decision). Don't document or reintroduce
one by accident.

The cost of inlining, which nothing else records: a data URL is ~33% larger than the
file, lives in the JS heap, is re-sent across the bridge on every render, and cannot be
cached by Chromium. Defensible for thumbnails; questionable for full-size images on an
entry with several attachments. If that ever bites, #140's option 2 (a scheme for
full-size images only) is the known alternative — a deliberate change that needs the
frozen `_internal/` path verified, which #138 made possible.

Media is stored flat in `app_data/media/` with UUID filenames, decoupled from entries via the `entry_media` / `entry_media_mapping` junction tables — one media row can attach to many entries (cross-exam reuse, global media search). Images can also be linked to dimensions.

**Replacing a profile asks before it deletes images (#150, owner's decision 2026-09-22: a checkbox at import time).** `replace_profile`'s default is still the literal one — rename the media directory aside, copy the archive's media in, delete the renamed original on success — and with a `.wimi` exported *without* media that is a pure deletion with nothing put back. The import preview's **"Keep the images already in this profile"** is ticked whenever the modal opens, and its hint names the count at stake (`replace_targets[].media_file_count`) and what the archive carries, because the checkbox is unanswerable without both. Unticking is the explicit "make the media match this archive exactly" choice and is styled as the warning it is. **An absent `keep_existing_media` means keep**: `executeProfileImport` maps `None → True` so a caller that forgets cannot delete a student's images, which is the difference between this and the folder-sync path, where `keep_remote` passes `True` outright (#148). The `False` branch is a real path with a real test — `test_unticked_box_deletes_them` — so do not "simplify" the flag away.

## Entry Point & Profiles

`run_wimi.py` is the launcher; actual initialization is in `src/app/main.py`. On startup it detects frozen vs dev mode, initializes the plugin system, then resolves the startup profile via `resolve_startup_profile`: honor `profiles.always_ask` → open a valid last-used profile → auto-open a sole active profile (the zero-friction path for legacy single-`demo_user` installs) → otherwise land on `profile_select.html`. Profiles are portable as `.wimi` archives via `ProfileTransferBridgeMixin` (export/validate/install, `src/app/profile_archive.py`); soft-deleted profiles are purged after a grace period during startup housekeeping. Profile slots all work with `self.user_db is None`, because the picker runs before any user database is attached — and because the database is swapped on profile switch, anything that needs it must resolve `self.user_db` at call time rather than capturing it.

`--test-mode --debug-port N --app-data-dir D` (N must be in 12000–12100) is what `wimi_test` spawns: it skips profile resolution, opens CDP, prints `TEST_MODE_READY:port=N`, and the harness attaches a user DB through the `loadTestUserDatabase` slot.

### There are two entry points and one command line (settled in #138)

> **Add a flag to `src/app/cli.py`. Never to an entry point.**

`run_wimi.py` is the dev launcher; **`src/app/main.py` is the frozen entry point** — `wimi.spec:91` and `wimi_macos.spec:91` both name it as the PyInstaller Analysis script, so a shipped binary runs `main.py` as `__main__` and `run_wimi.py` is not in the bundle at all. The parser used to live in `run_wimi.py` and `main.py`'s `__main__` block called `main()` with no arguments, so in every frozen build `--test-mode`, `--debug-port` and `--app-data-dir` were read off a `None` namespace by `getattr(..., default)` and **silently dropped**: CDP never opened, and a caller pointing the binary at a scratch directory quietly got the real `app_data/`. `main()`'s docstring called `args=None` a backward-compatibility path; the defect was that the backward-compatibility path *was* the frozen path.

- Flags, the 12000–12100 port validation and the free-port auto-pick now live in **`src/app/cli.py`**, and both entry points call `parse_cli_args()`. `run_wimi.py` is a shim; `main.py`'s `_entry_point()` is the binary's command line. A parser in either file is the bug coming back.
- **Unknown flags are an error** (`parse_args`, not `parse_known_args`). `--mcp-server` is declared in `app/cli.py` for that reason even though `main()` dispatches it by a `sys.argv` peek before any GUI import. Qt's own command-line arguments are consequently rejected too — set `QT_QPA_PLATFORM` / `QTWEBENGINE_CHROMIUM_FLAGS` in the environment, which is what everything here already does.
- **`--test-mcp-server` is development-checkout only.** `wimi_test_mcp` drives WIMI and is not bundled inside it, so the frozen entry point exits 2 with a message naming `run_wimi.py` rather than repeating #138's accept-and-ignore.
- **`main(args=None)` is now only for programmatic callers** (tests). Nothing may reach it with `None` from a command line.
- **A release build refuses `--test-mode` and `--debug-port` (#144, owner's decision 2026-09-22).** They start a Chromium remote debugger (to which Qt adds `--remote-allow-origins=*`). `parse_cli_args` refuses them with exit 2 in a frozen bundle unless `sys._wimi_test_build` is set — and only `packaging/rthook_test_build.py` sets it, a PyInstaller runtime hook that `wimi.spec` / `wimi_macos.spec` include only when built with `WIMI_BUILD_VARIANT=test` (`build_windows.bat test`, `./build_macos.sh test`). **Nothing at runtime can open the gate** — not an env var, not a flag; don't add one. Development runs are never gated (the harness spawns `run_wimi.py`). `--app-data-dir` opens nothing and stays allowed. The cost, accepted by the owner: the release artifact itself cannot be driven by the suite. Both variants come from **one** spec and differ by that hook alone — keep it that way; a second spec would let them drift. `tests/test_release_build_refuses_test_mode.py` checks a real release build (`WIMI_RELEASE_BINARY`).

### Every entry point configures stdio first (settled in #137)

> **`print()` encodes through the console codepage. A redirected stream is where automation lives.**

`configure_stdio()` in **`src/console_encoding.py`** is the first statement of `app.main.main()`, of `main.py`'s `_entry_point()`, of `run_wimi.main()` and of `database/migrations/__main__.main()`. On Windows a *non-console* stdout (a pipe, `> log.txt`) encodes with cp1252, and a character it cannot represent raises `UnicodeEncodeError` **from inside `print()`** — which killed the frozen build during `register_media_scheme` (a scheme handler since deleted as dead code, #140) before the window appeared. The harness pipes stdout by design, because that is where `TEST_MODE_READY:port=N` arrives, so this and #138 had to be fixed together: neither is observable alone.

- **There is no environment workaround.** `PYTHONIOENCODING` is honoured by an ordinary interpreter and **ignored by the PyInstaller runtime** (measured on Windows with a control, #137 comment #1689). `wimi_test.process` still sets it, for the dev launcher only.
- **The `None` guard is load-bearing, not defensive noise.** `wimi_macos.spec` sets `console=False`, so a macOS `.app` has `sys.stdout is None`; an unguarded `sys.stdout.reconfigure(...)` raises `AttributeError` and crashes the build on the very line added to stop a crash. Windows cannot reach that state and deliberately never will — see the `hide_console` bullet below.
- **stdout gets `errors='replace'`, stderr keeps `'backslashreplace'`.** They differ on purpose, and `errors` must always be passed alongside `encoding` — `io.TextIOWrapper.reconfigure` resets it to `'strict'` otherwise, which would *remove* stderr's existing protection.
- `python scripts/check_ascii_prints.py` is the recurrence gate. **Two of #137's six call sites were an em dash**, so it is an ASCII check, not an emoji check.
- **The Windows build hides the console *window*, it does not drop stdout (#142).** `wimi.spec` keeps `console=True` and adds `hide_console='hide-early'`: PyInstaller hides the window only when the process owns it, so double-clicking from Explorer no longer opens a terminal beside the GUI, while a run from an existing terminal still prints there and a redirected stdout (the harness, `> log.txt`) is untouched. **`console=False` is the wrong fix and must not be reintroduced** — it would take the standard streams away, silencing every `print()` diagnostic *and* `TEST_MODE_READY:port=N`, which is how the harness learns WIMI is up (#138). `hide-early` is chosen so a bootloader failure *before* the archive is found — "the exe will not start at all" — still prints where somebody can read it. **Both build variants carry it**, because a test build differing from the release build in subsystem stops being evidence about it. `tests/test_build_spec_console_window.py` is the guard; the window behaviour itself is only observable on Windows. **Verified on hardware 2026-09-23** (#142): no window on an Explorer double-click, an existing terminal left visible (`IsWindowVisible` before and after), 1,355 bytes of redirected stdout, and the frozen test build still drivable — that last one is what `console=False` would have broken silently. One trap recorded there: reading that redirected output with a cp1252 reader (PowerShell's default) renders correct UTF-8 as `âœ…`, which looks exactly like a #137 relapse. Check the bytes before reopening anything.

## Embedded Browser Pane

A second `QWebEngineView` in the right half of `MainWindow`'s `QSplitter` so a question bank sits beside the entry form (`src/app/browser_pane.py`, `BrowserPaneController`). It has its own persistent `QWebEngineProfile` under `app_data/browser_pane/` so qbank logins survive restarts; a toolbar with one shortcut button per question source that has a `url` (most-recently-opened first, three visible, rest in an overflow menu), URL bar, Back, Reload and stepped zoom; and tabs whose strip is hidden while there is a single tab. Site popups (`createWindow`) become new tabs, which is what SSO sign-in flows expect. Toggle: View menu / Ctrl+B, or the entry form's "Open question bank" button.

- **Controller protocol.** `MainWindow._setup_browser_pane` attaches the controller to the bridge after the web channel exists. `BrowserPaneBridgeMixin`'s `openBrowserPane` / `closeBrowserPane` / `getBrowserPaneStatus` only delegate to `bridge._browser_pane_controller` (`open_pane(url) -> dict`, `close_pane() -> dict`, `get_status() -> dict` with `open`, `url`, `tab_count`). With no controller they return `success=false, error='browser pane not available'`; pages treat that as "feature absent" and hide their toggle — keep that string stable.
- **Data.** Shortcuts are derived from `question_sources.url`, not a second list. Per-source `pane_desktop_site` (default 1: send a desktop user-agent) and `pane_last_opened_at` (millisecond precision, for MRU order) are **per device** since m021 — they live in `device_source_settings`, and `SourcesMixin.get_pane_sources` / `touch_pane_source` / `set_pane_desktop_site` keep their signatures while reading and writing there. Preferences: `pane_open_mode` (`last`|`source`|`blank`), `pane_default_source_id` (deliberately **not** a foreign key — a dangling id degrades to a blank page), `pane_shortcut_opens` (`current`|`new`). Remembered state — `pane_zoom_pct`, `pane_split_app_pct`, `pane_last_url` — is **device-local** (`device_settings`); see *Device Identity & Profile Identity* above. Settings → Question Banks (`initQuestionBanks` in `settings.js`) is the only UI for the per-site facts.
- **Pane → page events.** The pane injects `browser:pane_state` onto `window.eventBus` via `runJavaScript`. See the Testing hazard below before asserting on it from a scenario; the entry-form button also re-reads status on `focus`/`visibilitychange` so its label never claims a state it cannot see.
- **Teardown order.** The pane's page must be deleted before its profile is released (`MainWindow.closeEvent` → `teardown()`), or QtWebEngine warns "Release of profile requested but WebEnginePage still not deleted".

## Related Topics (Subject Relations)

Student-authored semantic relations between subjects — *hypertension leads to hypertensive nephrosclerosis* — rendered as a 1-hop list on the subject deep dive. Issue #14's twelve decisions are recorded in that issue and restated at the top of `src/database/domains/relations.py`; the ones that get "fixed" in the wrong direction:

- **`subject_relations` is its own table, never new `mapping_type` values on `subject_edges`.** `subject_edges` is a navigational DAG carrying weight semantics. m019 created the table, and rebuilt `subject_delete_batch_items` to widen its `item_type` CHECK with `relation_hidden`.
- **The reason is mandatory.** `reason TEXT NOT NULL` with a non-blank CHECK, re-checked in `create_subject_relation` so the caller gets a sentence instead of an `IntegrityError`, and re-checked at the modal's Save button. There is no "explain later" state and no code path may add one.
- **Do not draw a graph.** A list. D3 is already loaded on that page.
- **The parent context ORDERS the panel and never filters it.** `get_subject_relations(subject_id, primary_parent_id)` returns the same set for every context and only changes `context_rank`. This is the opposite of what `primary_parent_id` does to the entry rollups beside it on the same page, which is exactly why it is easy to get wrong.
- **No cycle validator.** `A→B` and `B→A` are both valid; the candidate picker is direction-aware so a cycle stays authorable from either end. Only a self-loop is refused.
- **Relations carry no `dimension_id`** and may cross dimensions; the panel labels the *other* subject's dimension when they differ.
- **Zero relations renders no container** — one quiet "Link a related topic" action into a bare `#relationsMount`, nothing else.
- **Archiving a subject hides its relations**: `delete_subject_subtree` calls `hide_relations_for_delete_batch`, which stamps `subject_relations.hidden_batch_id` and journals a `relation_hidden` item, so #37's restore can replay it.
- **Out of scope for v1:** suggestions of any kind. If they are ever added, persistent dismissal ships in the same release. #59 and #60 build on this and are separate issues.

Files: `src/database/domains/relations.py`, `src/app/bridge_domains/relations.py`, `src/web/js/api/relations.js`, `src/web/js/subject_relations.js`, `src/web/css/subject_relations.css`.

## Error Types (Tags)

Tags are the error types (Knowledge Gap, Misread Question, …), grouped under `tag_groups`, each with a `description` shown as a definition tooltip in the entry-form picker, the analytics legend and the deep-dive lists. `TagBridgeMixin` exposes `createTagInGroup`, `deleteTag` and `updateTagDescription`; the entry form has an inline Create Tag flow and a Manage Error Types modal. `seed_default_tags` seeds definitions for new exam contexts and m010 backfilled them for existing ones without clobbering user-written text. Keep descriptions flowing through `get_tag_analytics` and deep-dive `mistake_types` payloads when touching those.

## The Entry Form Is Inert Until It Is Ready (settled in #114)

> **A page that cannot yet keep what it is given must not accept it.**

`question_entry.html` ships `.entry-page` with the `inert` attribute, and
`markEntryFormReady()` in `question_entry.js` is the one place that removes it.
Until then a click has nowhere to land and a keystroke cannot be typed, which is
the point: `resetFormForNewEntry()` and `populateFormWithEntry()` overwrite every
field, the five footer handlers are bound at the very end of `initializeEntryPage()`,
and both rich text editors flush a queued `''` over whatever is in them when
TinyMCE's `init` fires. Everything done in that window was discarded with
`isDirty` still false, no toast and no console error.

Four things are load-bearing:

- **The gate waits for the editors, not just the end of the init chain.**
  TinyMCE mounts ~130 ms *after* the chain finishes, and the reflection iframe is
  editable for 118–436 ms before its `init` flushes the queued `''`. That tail —
  after the page has stopped looking busy — is where the single most valuable
  field on the page was being wiped. `#47` does not cover it; #47 guards the
  opposite direction (app-set queued content read back empty).
- **`EntryState.isLoading` is cleared by the same function, and nowhere else.**
  It is the flag the harness waits on for "form is ready" (#99, #105) and it used
  to go false 127–147 ms early. One gate owns the flag and the attribute together
  so the flag cannot claim ready while the page still refuses input. Don't move
  the assignment back to the end of the chain.
- **Every exit releases the form.** `markEntryFormReady()` is called from a
  `finally` and from the pre-`try` "no session id" return, and it fails open after
  15 s if the editors never report ready. A permanently inert form is a far worse
  bug than the one this fixes.
- **Test it with real input.** `inert` blocks hit-tested clicks and focus but not
  `el.value = 'x'`, `el.click()` or `body.innerHTML = ...`. A scenario built from
  those passes against a completely ungated page. `tests/wimi_test/scenarios/_helpers/w114_form_ready.py`
  drives `Input.dispatchMouseEvent` / `Input.insertText` and widens the window by
  delaying the page's bridge calls from a `Page.addScriptToEvaluateOnNewDocument`
  hook — not by CPU throttling, which slows the probe as much as the page.

The same defect is filed for settings (#119), session setup (#120), the tree
editor (#121) and the entry browser (#122); `entry_detail.html` is the clean
counter-example — handlers before the first `await`.

## Draft Entries in Analytics (settled in #12)

> **Drafts count everywhere, except goals.**

A draft (`question_entries.is_draft = TRUE`) exists because a question was answered wrong. The mistake happened; an unfinished reflection does not un-happen it, and a student with fifteen unfinished drafts must not be shown an analytics screen implying they have no weaknesses. So no analytics surface filters `is_draft` — not the sunbursts, Top Subjects, the deep dive, `dimensions.py`, related subjects, the weight quadrant, source comparison or performance over time.

Goals are the single exception: "log 20 entries this week" means 20 *finished* entries, so `GoalsMixin._count_entries_in_period` keeps its `is_draft = FALSE`. That exemption is paid for by a qualifier — `get_user_goals` returns `drafts_remaining` (from `_count_drafts_in_period`, the exact complement: same window, same date column, same exam scope) and `goal_widget.js` renders "N drafts remaining". A goal that silently ignores three drafts is the same information gap, just moved.

Weekly goals reach that counter through **`_count_goal_progress_in_period`, the one dispatch point** (settled in #58). Every progress path goes through it, because before #58 four sites each dispatched for themselves, all four sent `weekly_entries` to a question counter, and the draft carve-out above was attached to code nothing called. Don't reintroduce a per-site `if goal_type ...`.

**There is one weekly goal type: `weekly_entries`, entries logged (settled in #71).** The dispatch point used to fork on `weekly_questions`, which counted `review_sessions.total_questions` — a type `user_goals`' CHECK constraint forbids, that nothing has ever created, so the branch was unreachable code that read as live. It and `_count_questions_in_period` are gone; the CHECK constraint was correct already and needs no migration. Questions-based goals would be a new migration widening the constraint plus a way to create the type, not a resurrection of the branch. `_count_goal_progress_in_period` keeps its `goal_type` parameter regardless: it is the funnel a second type would plug into, and nowhere else.

**Goal progress is counted on read, never stored (settled in #70).** The two remaining dispatch sites, `get_user_goals` and `get_goal_history`, are both reads: they recount from the entries every time. `goal_periods` records only **the target the student had set that week** — genuine history, since raising the goal today must not rewrite what last week was measured against. `goal_periods.achieved_value` is legacy, still holding stamps written before #70, and nothing reads it. Before that, `_ensure_goal_period` stamped achievement when the goal was created and `update_goal_progress` — the notifier meant to refresh it — **had no callers anywhere in the repo**, so a goal froze for the whole of the week it was set in and re-saving it did not help. `update_goal_progress` is gone; do not reintroduce a stored progress value or a notifier that every future write path has to remember to call.

This question was re-litigated three times before it was settled (two planning docs deferred it; `d3690b0` added a draft filter to `get_dimension_performance` and reverted it). `tests/database/test_draft_policy_by_surface.py` asserts the policy **one test per surface** for exactly that reason — do not consolidate them, and do not add an `is_draft` predicate to an analytics query without reopening #12.

## Logging

`src/app_logging/error_logger.py` (`ErrorLogger`) is the single logger. Four independent bugs once left every log file at 0 bytes, and fixing fewer than all four fixes nothing, so keep these invariants:

1. The stdlib handler attaches to the package roots `app`, `database`, `wimi`, `wimi_test` — every module logs via `logging.getLogger(__name__)`. Not the root logger (third-party DEBUG noise, and its WARNING default drops INFO).
2. Construct `UserDatabase(..., error_logger=...)` at every site. The database layer guards each log call on `self.error_logger`, so omitting it silently disables all database logging, including the rollback line that is usually the only evidence a transaction failed.
3. `run_application` forwards the one logger to `MainWindow`; never let a component mint a second `ErrorLogger` with its own file.
4. The periodic flush is a daemon-thread ticker, not a `QTimer` — the logger is built before `QApplication` exists, and a `QTimer` created without an event loop never fires.

Records below WARNING are never deduplicated (a repeated INFO is the information); WARNING and above collapse repeats within a 300 s window by `category:message` hash. `cleanup()` is idempotent and runs from Qt's `aboutToQuit` and from `atexit` (with `wait=False`, because joining the executor there races `concurrent.futures`' own atexit hook). Tests for this assert against the file on disk, not the in-memory cache — do the same.

## Testing

Pytest markers: `@pytest.mark.unit`, `.integration`, `.slow`, `.database`. Coverage is enforced at 80% minimum on `src/database`. Key fixtures in `conftest.py`: `temp_dir` (isolated test databases), `master_db`, `admin_user`, `master_db_with_users`.

**Reference fixture:** `tests/fixtures/usmle_step1_outline.txt` (1,327 lines, full 2025 USMLE Step 1 content outline) is available for tests that need a realistic hierarchy with known multi-parent topics (DVT, hypertension, sepsis, etc.). Also exposed through the seeder `seed_usmle_outline` for `wimi_test`-driven regression scenarios.

**UI regression / exploratory testing:** The driver library lives at `wimi_test/` (repo root) — a pychrome-based CDP wrapper that pytest scenarios import directly. `src/wimi_test_mcp/` is a thin MCP server wrapping that same library so Claude Code (via the `wimi-test` MCP) can drive interactive sessions. Pytest scenarios live in `tests/wimi_test/scenarios/` (`@pytest.mark.regression`). See `docs/planning/TEST_INFRASTRUCTURE.md`.

**Driving a frozen build:** set `WIMI_TEST_BINARY` to a built **test** executable (`build_windows.bat test` / `./build_macos.sh test` → `dist/WIMI-test/WIMI`) and `WimiProcess` spawns *that* instead of `python run_wimi.py`, for the whole session. A release build refuses `--test-mode` (#144), so it cannot be driven; `WIMI_RELEASE_BINARY` runs the release-side check instead. `tests/wimi_test/scenarios/test_frozen_binary_smoke.py` is the dedicated smoke test and skips when the variable is unset. This was impossible before #137/#138 — which is why #135's Chromium drift shipped undetected — so a frozen build is worth re-running the suite against before a release rather than only at build time.

**Bridge tests** (`tests/app/test_bridge_*.py`) construct `DatabaseBridge(master_db=..., user_db=...)` directly, call slots as plain methods, and `json.loads` the response — no `QApplication` needed. Use `user_db=None` to test the guard paths. Optional controllers (the browser pane) are plain attributes on the bridge, so a fake with the right methods is enough.

**Scenario conventions** (`tests/wimi_test/scenarios/README.md`): one file per behaviour, 80–150 lines, both `@pytest.mark.slow` and `@pytest.mark.regression`, seed through `wimi_session.user.db` rather than the UI, navigate with `wimi_page.goto(route)`, and poll with `wait_for_timeout` loops — never `time.sleep`. A second `goto` to the same page returns before the new document commits, so mark the old document (a `window` global) and wait for it to vanish before asserting on the reload.

**Hazard — Qt and CDP are different JavaScript worlds** (`docs/planning/TEST_INFRASTRUCTURE.md` §12a): a global written by Qt's `page().runJavaScript()` is invisible to a scenario's `eval_js`, and vice versa, with no error. Never assert from a scenario on state written by injected scripts (e.g. the pane's `browser:pane_state`); verify with a `runJavaScript` result callback before concluding an injection does nothing. The pane's tab strip is Qt chrome, not DOM — `getBrowserPaneStatus().tab_count` is the only handle a scenario has on it.

**Resolved hazard — the harness used to drive a page with no view** (`TEST_INFRASTRUCTURE.md` §12c, fixed 2026-09-11): `install_on_view` left the `QWebEnginePage` it replaced alive, and `primary_tab` picked it by title. Navigation and `eval_js` reported the new page while the window never changed; `Page.captureScreenshot` hung for want of a compositor frame, and CSS transitions never advanced. Those last two were previously written up as permanent Qt limitations — neither was, and both work now. `primary_tab` refuses a target unless it reports `document.visibilityState === "visible"`. If a session ever looks like this again, several screenshots with an identical byte count is the tell. Don't reach for `QWidget.grab()` as a screenshot path: on a `QWebEngineView` it returns a stale delegated frame, capturing the first frame of the session forever, which looks like success.

**Known-broken, do not "fix" by installing anything:** `tests/spike/` and `tests/database/test_graph_*.py` depend on `real_ladybug`, a graph library that was evaluated and removed. The spike files break collection (hence `--ignore=tests/spike`); the graph files fail on `_graph_available` (about 80 failures/errors) in every fresh environment. Ignore both when judging a run.

**CI:** `.github/workflows/test-infrastructure.yml` runs on push/PR to `master` (Ubuntu, Python 3.11). It executes `pytest -m "not slow"` then `pytest -m slow` with `QT_QPA_PLATFORM=offscreen`. On failure, `pytest_artifacts/` (screenshots, console + network logs) is uploaded for 14 days. macOS and Windows runners are deferred — see `docs/testing/CI_SETUP.md`.

**Two unverified things about that workflow**, both worth checking before trusting a green tick. It sets `QT_QPA_PLATFORM: offscreen` but not `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`, and comments that offscreen alone "is enough" — which contradicts the SIGTRAP above, though a GitHub runner with no `/dev/dri` at all may take a different path than a box that has one. And it triggers on push/PR to `master`, while `master` is never pushed to the `github` remote (only `public` snapshots, onto branch `main`), so it may never have run. Nobody has confirmed either way.

## Dependencies

**Python (runtime, `requirements-prod.txt`):** PyQt6, PyQt6-WebEngine, Pillow, python-json-logger, mcp, pyinstaller — versions pinned to the active dev venv; bump deliberately
**Python (test, `requirements-test.txt`):** pytest, pytest-cov, pytest-mock, pytest-timeout, pytest-asyncio (the MCP facade tests use the `asyncio` marker and `--strict-markers` makes its absence a collection error), coverage, pychrome (CDP driver for wimi_test), jsonschema (the import guide's published schema is validated against the guide's own examples; it already arrives with `mcp`, the pin only makes it explicit)
**Frontend (vendored in-repo, no package manager):** D3.js v7 and Fuse.js v7 in `src/web/js/lib/`, TinyMCE and KaTeX in `src/web/lib/`. These directories are deliberately tracked — don't reintroduce a blanket `lib/` gitignore rule (it silently excluded them once; fixed in `4651c33`).

No linter/formatter is wired up — there is no `pyproject.toml`, `.flake8`, or `mypy.ini`. If you want black/mypy/flake8, configure them first.

## MCP Tools Available

- **`wimi-db`** (configured in `.mcp.json`, runs at `127.0.0.1:8000/sse`) — read-only access to user databases for verification and inspection. Tools include `list_users`, `list_entries`, `list_sessions`, `list_exams`, `list_sources`, `get_subject_tree`, `search_subjects`, `get_dimensions`, `get_analytics_overview`, `get_subject_analytics`, `get_tag_analytics`, `get_database_stats`, `get_entry_detail`, `get_entry_notes`, `get_goals`, `get_preferences`, `get_study_streak`, `get_timer_rounds`, `verify_mixin_decomposition`, `check_dimensions_enabled`. Prefer these for verification tasks over writing one-off SQLite queries.
- **`wimi-test`** — spawns WIMI in test mode and drives the UI over CDP (pychrome → QtWebEngine remote debugging). One active session per server. `.mcp.json` launches it with `${WIMI_PYTHON:-python}`; on a machine with no `python` alias (Linux), set `WIMI_PYTHON` to the project venv's interpreter in the `env` block of `.claude/settings.local.json`, alongside `QT_QPA_PLATFORM=offscreen` and `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu` if it is headless. Tools include `start_session`, `end_session`, `get_session_status`, `navigate_to`, `click`, `fill`, `wait_for`, `eval_js`, `dump_dom`, `screenshot`, plus `get_console_log` / `get_network_log` / `get_bridge_log` capture streams. Design docs: `docs/planning/TEST_INFRASTRUCTURE.md` §8, `docs/planning/PYCHROME_MIGRATION.md` (the Playwright→pychrome rewrite since Qt's CDP surface lacks the `Browser` domain).
- **`forgejo`** (user-scope) — read/write access to the private Forgejo remote for repo browsing, PR/issue ops, file CRUD via API, and reading commit history. Cannot substitute for `git push` (creates server-side commits with different SHAs and per-file granularity).

## Remotes & Publishing to GitHub

Two remotes with opposite rules:

- **`origin`** — private Forgejo server. Full `master` history lives here; push freely.
- **`github`** — public mirror (`github.com/pclahoud/Project-WIMI`, branch `main`). Receives **snapshot commits from the `public` branch only** — NEVER push `master` here; its history contains private identities.

To publish: `python scripts/publish_release.py [-m "message"]` (use `--dry-run` to preview). The script snapshots master's committed tree onto the `public` branch under the public noreply identity (`pclahoud`), after scanning the tree against `.publish_denylist.txt` (git-ignored by design, one extended regex per line) and refusing to publish on any match or if the denylist is missing. Never commit the denylist, and don't reintroduce personal identifiers (real names, private IPs, `C:\Users\<name>` paths) into tracked files — the scan will block the next release.

Release tags: use `python scripts/publish_release.py --tag vX.Y.Z`. NEVER run bare `git tag -a` for tags pushed to GitHub — annotated tag objects embed the tagger from the repo-local git config, which is the private identity.

## Documentation

| Document | Purpose |
|----------|---------|
| `docs/planning/FUTURE_VISION.md` | **Primary reference** — roadmap, status, idea parking lot |
| `docs/planning/TEST_INFRASTRUCTURE.md` | wimi_test design, fixture catalogue, CDP hazards (§12a, §12c) |
| `docs/testing/CI_SETUP.md` | Headless Qt on CI and the Ubuntu system-package list |
| `docs/planning/MIGRATION_RUNNER.md` | Versioned migration runner design |
| `docs/planning/ENTRY_AND_SUBJECT_IMPROVEMENTS.md` | Entry-form rework design (add-more-entries, subject search modals); decisions in `my_answers.txt` |
| `docs/PLUGIN_DEVELOPMENT.md` | Plugin development guide |
| `docs/architecture/completed_database_tables.md` | Database schema reference |
| `docs/BUILD_WINDOWS.md` / `docs/BUILD_MACOS.md` | Build instructions |
| `docs/handoff/INDEX.md` | Handoff tracking index |
