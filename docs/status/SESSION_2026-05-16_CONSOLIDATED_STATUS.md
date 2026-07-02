# Project Status — May 16, 2026

**Consolidated status update covering the Hierarchical Weight Allocation Rework (Arc 1).** Spans 2026-05-15 through 2026-05-16.

The headline: **Arc 1 wrapped.** 10-stage rollout executed in two sprint days. Stages 0–9 landed; Stage 10 (drop legacy `subject_nodes` weight columns) deferred per plan until at least one stable release lives with the new system.

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
| 7.4-7.6 | Multi-Dimensional Analytics | ✅ Complete | Jan 18, 2026 |
| 7.7 | Polish & Optimization | 🚀 Not Started | - |
| 8 | Anki Integration | 📋 Planned | - |
| 9 | Assignable Entry Notes | ✅ Complete | Feb 7, 2026 |
| 10 | Subject Hierarchy Notes | 📋 Planned | - |
| Plugin/Addon System | Install/uninstall, scoped API, per-plugin settings | ✅ Complete | Mar 16, 2026 |
| Media Link System | Junction table, link/unlink/delete, global search | ✅ Complete | Apr 9, 2026 |
| Migration Runner | Versioned `MigrationRunner` | ✅ Complete | May 9, 2026 |
| Test Infrastructure | `wimi_test/` + MCP server + CI | ✅ Complete | May 9, 2026 |
| Polyhierarchy Backend | `subject_edges`, EdgesMixin, GraphMixin, CTE rewrites | ✅ Complete | May 9, 2026 |
| **Arc 1: Weight Allocation Rework** | **10-stage rework — Stages 0-9** | **✅ Complete** | **May 16, 2026** |
| Arc 1: Stage 10 | Drop legacy node-level weight columns | 🕑 Deferred | ≥1 release later |

---

## Arc 1 Stage-by-Stage Summary

| Stage | What landed | Commit |
|---|---|---|
| 0 — Edge weight history | `m006_subject_edge_weight_history`: nullable `edge_id` on `subject_node_weights`, broadened `change_type` enum (5 new values: `anchor_set`, `anchor_cleared`, `allocation_recompute`, `rebalance_request`, `edge_weight_edit`); idempotent migration with view rebuild | `ae723ed` |
| 1 — Hamilton allocator | `allocate_questions_hamilton` (Largest Remainder + weakness tie-break), `compute_weakness_scores` (90-day half-life), `get_sibling_edges` on `EdgesMixin`, `AllocationFeasibilityError` | `5db45d0` |
| 2 — Auto-rebalance opt-in | Behavior change: `update_subject_relative_weight` no longer silently mutates siblings; explicit `rebalance_sibling_edge_weights` + `rebalanceSiblings` bridge slot + "Rebalance siblings" UI button; new `update_edge_relative_weight` edge-aware writer | `bbb491f` |
| 3 — Edge-anchor bridge | `set_edge_anchor` / `set_edge_weight_source` / `get_edges_for_child` on `EdgesMixin`; bridge slots `setEdgeAnchor`, `updateEdgeRelativeWeight`, `getEdgesForChild`; `currentEdgeId` wired through `WeightEditorState` | `9216e8d` (Batch D) |
| 4 — Exam length triple | `m007_exam_length_triple`: `length_kind` enum + `length_min/max/typical/note` on `exam_contexts`; new exam-wizard length step (3-radio Fixed/CAT/Unknown); `seed_known_exam_lengths` for USMLE/NCLEX/MCAT/GRE/NBME | `b357e1d` |
| 5 — Allocation read-side | `get_effective_question_counts` (with synthetic root rows); `getQuestionAllocation` + `getEffectiveQuestionCounts` slots; dual-unit `XX.X% • ~N q` chip display via `enrichNodesWithQuestionCounts` (mirrored to both `loadHierarchy` and `loadDimensionHierarchy`) | `9216e8d` (Batch D) |
| 6 — Dual-unit input UX | The centerpiece. `parseWeightInput` magic-suffix parser, segmented `%` / `Q` control, anchor checkbox, switch-parent affordance, parent-context header, anchored vs auto sibling bars, canonical `setExplicitWeight` bridge slot | `235fced` |
| 7 — Feasibility checker | `validate_hierarchy_feasibility` + recursive variant; `getFeasibilityReport` + `getAllFeasibilityReports` slots; yellow feasibility badge on the weight panel + warning dots on tree rows (mirrored to dimension path) | `8883f12` (Batch F) |
| 8 — CAT exam handling | `allocate_questions_hamilton` gets `is_adaptive` flag (skips integer rounding for `length_kind='range'`); `is_adaptive_exam` helper; chips render `~26.4 q (planning estimate)` floats; wizard CAT-radio planning-baseline copy | `8883f12` (Batch F) |
| 9 — `weight_source` in analytics | `_WEIGHT_SOURCE_CONFIDENCE` multiplier table feeds `_calculate_efficiency_score`; `get_subject_exam_weight_analysis` reads dominant edge's source; per-row source markers (●⚓○⊘); "Weight Sources" breakdown card; structural multi-parent context selector (MVP) | `8883f12` (Batch F) |
| 10 — Drop legacy columns | Deferred per plan | — |

**Bugfix commits along the way:**

| Commit | What |
|---|---|
| `8890d8a` | Live-render after Rebalance siblings (dimension cache invalidation); root System nodes get synthetic `q_typical` row so chips show `11–15% • ~36 q`; Apply Weight auto-anchors |
| `9ebd77b` | `_compute_parent_q_budget` delegates to `get_effective_question_counts` so Histology under Anatomy under GI reports ~3 q instead of 280 q |
| `e04e449` | Warning dot CSS contrast (filled yellow circle instead of yellow-on-yellow); `weight.css` loaded on analytics dashboard so Stage 9 breakdown card actually styles |

---

## Bug fix details (in-flight bugs surfaced by manual testing)

| # | Bug | Cause | Fix |
|---|---|---|---|
| 1 | After "Rebalance siblings", chip values don't update until F5 | `loadDimensionHierarchy` cache served stale post-write data | Bust `TreeState.dimensionHierarchies[id]` before reload |
| 2 | System chips ("Cardiovascular 11-15%") don't show `~q` after wizard sets length | `get_effective_question_counts` emitted one row per edge; roots have no incoming edge | Append synthetic root rows with `edge_id=None` |
| 3 | Apply Weight then Rebalance overwrote typed value | Writer didn't anchor; rebalance treated it as adjustable | JS hot patch: `setEdgeAnchor` after `updateRelativeWeight`; replaced in Stage 6 by `setExplicitWeight` |
| 4 | Bridge "Relative weight must be between 0 and 100" on out-of-range Q input | Apply re-parsed input directly; blur silently clamped to 100 | Apply now trusts `WeightEditorState.currentWeight` (canonical %); blur shows error toast with parent context |
| 5 | Q-mode showed ~93 q for Histology (parent had ~280 q budget) | `_compute_parent_q_budget` fell back to whole exam length on uncategorized ancestor edge | Delegate to `get_effective_question_counts` (uses Hamilton + legacy node fallback) |
| 6 | Warning dot visually invisible | Yellow background + yellow text + yellow border | Filled yellow circle, dark glyph, halo |
| 7 | "Weight Sources" card had no styling | `weight.css` not loaded on analytics_dashboard.html | Added `<link>` |

---

## Codebase Metrics

| Metric | Value | Δ since May 15 |
|--------|-------|----------------|
| Python (src/) | ~33,000 lines | +3,000 |
| JavaScript (src/web/) | ~34,000 lines | +1,700 |
| Test files | 73 | +9 |
| Test functions | ~1,100 | +109 (Arc 1 added: 26 Hamilton, 11 edge anchor, 21 exam length+migration, 16 question allocation, 8 explicit weights, 8 feasibility, 13 CAT, 6 per-edge) |
| `@instrumented_slot`-paired `@pyqtSlot` | 179/180 | +9 (Arc 1 added 9 new bridge slots) |
| Migrations applied | m001–m007 (user) | +2 (m006 history, m007 length) |
| `hierarchy.py` | ~3,000 lines | +1,500 (Arc 1's largest concentration) |
| `wimi-test` regression scenarios | 7 | +6 (Arc 1 added all but the original `test_complete_review_stops_timer`) |

`hierarchy.py` growth is significant. Splitting weights/allocation into its own DB-domain mixin (`weights.py`) would lower cognitive load for any future weight work. Tagged as a follow-up under Recently Completed / Polish.

---

## Recent Work — Arc 1 Timeline

### 2026-05-15 — Sprint Day 1: Stages 0–6 + bugfix

- **Morning:** Implementation plan (`WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md`) authored from the rework doc's 7 pending items. 10-stage breakdown with dependency graph + recommended landing order.
- **Stages 0, 1, 4 in parallel.** Stage 0 (history table) landed first; Stages 1 (Hamilton allocator backend) and 4 (exam length triple + wizard) ran simultaneously without conflict.
- **Stage 2 sequentially.** Auto-rebalance opt-in needed the rebalance refactor on `hierarchy.py` after Stage 1's allocator code settled.
- **Stages 3 + 5 in parallel (Batch D).** Edge-anchor bridge + allocation read-side; both append to `weights.py` bridge / `api/weights.js` at clean boundaries; merged into a single commit.
- **Stage 6 alone.** UX centerpiece — segmented control, anchor pin, switch-parent, dual-unit input parser, canonical `setExplicitWeight`. Largest single stage; ~1700 lines.
- **Manual testing surfaced 4 bugs** (live-render, root q_typical, anchor-on-Apply, Q range silent-clamp). Bugfix commit `8890d8a` landed same day.

### 2026-05-16 — Sprint Day 2: q_budget fix + Stages 7–9 + polish

- **`_compute_parent_q_budget` fix** (`9ebd77b`) — replaced the broken walk-up with delegation to Stage 5's `get_effective_question_counts`. Histology now reports ~3 q.
- **Stages 7, 8, 9 in parallel (Batch F).** Strict scope discipline on shared files (`hierarchy.py`: 7 adds NEW functions, 8 modifies existing; `weight_editor.js`: 7 owns feasibility badge, 8 owns adaptive chip rendering). All three merged cleanly.
- **Manual testing surfaced 2 CSS-only bugs** (warning dot contrast, missing weight.css link on dashboard). Polish commit `e04e449`.
- **Planning docs refreshed** (this session): rework doc + implementation plan marked ✅; FUTURE_VISION bumped to v3.3; this status doc created.

---

## Known Issues (Technical Debt)

| Priority | Issue | Description | Notes |
|----------|-------|-------------|-------|
| HIGH | Entry save not persisting media/tables | Media and tables in notes not saved when navigating | Outstanding since Mar 6 — not touched by Arc 1 |
| HIGH | Entry form auto-scroll | Screen scrolls up while typing in lower sections | Outstanding since Mar 6 |
| MEDIUM | Image dialog subject bug | Shows "No subjects" after returning to entry | Outstanding since Mar 6 |
| MEDIUM | Table multi-selection | Selection lost on right-click | Outstanding since Mar 6 |
| MEDIUM | Table right-click functions | Context menu functions broken | Outstanding since Mar 6 |
| MEDIUM | Multi-parent context selector (subject deep-dive) | Renders but doesn't refilter the drill-down | Stage 9 MVP — needs `primary_parent_id` parameter on `getSubjectDeepDive` |
| MEDIUM | `hierarchy.py` ~3000 lines | Mixin pattern protects callers but the file is unwieldy | Natural to split into `weights.py` DB mixin |
| MEDIUM | Cross-dimensional polyhierarchy | Both parents of a multi-parent leaf must share `dimension_id` | From polyhierarchy plan; not a regression |
| MEDIUM | `getMediaFileUsage()` / `getOrphanedMedia()` | Media Link System tail items | Carried over |
| LOW | Related images dialog false positive | Dialog appears for subjects without images | Outstanding since Mar 6 |
| ✅ | Form section switching (Apr 20) | First click closed instead of opening | Fixed pre-Arc-1 |
| ✅ | Complete-review timer + alias overflow (May 8) | Fixed pre-Arc-1 |
| ✅ | All 7 Arc 1 in-flight bugs above | — | Fixed |

---

## Next Priorities

1. **Stage 10 (Arc 1)** — Drop legacy `subject_nodes.relative_weight` / `weight_source` / `display_order` columns. Defer until ≥1 stable release lives with Stages 0–9 in production.
2. **Multi-parent context selector follow-up** — Extend `getSubjectDeepDive` with `primary_parent_id`, wire the selector to refilter. Small follow-up.
3. **`hierarchy.py` refactor** — Split weights/allocation into a new DB-domain mixin so the file stops growing toward 5000 lines.
4. **Polyhierarchy UX completion** — Cross-dimensional edges (currently a Non-Goal), optional parent-context tagging on entries, breadcrumb disambiguation in analytics drilldowns.
5. **Phase 7.7: Polish & Optimization** — Now genuinely unblocked: perf benchmarks against the polyhierarchy CTEs + new feasibility recursive walker; query caching where slow.
6. **Outstanding pre-Arc-1 tech debt bugs** — 5 still open (entry save persistence, auto-scroll, image dialog, table selection, table context menu).
7. **Anki Integration (Phase 8)** — Greenfield product work. `anki-mcp` already connected at the harness level.

Separately: the `feat/psychometric-assessment` branch was started this session (Stage 0 m008 + Stage 1 AssessmentsMixin). Continuing it is its own arc.

---

## Key Architecture Notes

- **Per-edge weights are the source of truth.** `subject_edges.relative_weight` + `is_anchor` + `weight_source`. The legacy `subject_nodes.relative_weight` is mirrored for chip-render compatibility but is scheduled for removal in Stage 10.
- **The Hamilton allocator owns integer rounding.** `allocate_questions_hamilton(parent_id, total_questions, *, weakness_lookup=None, is_adaptive=False)`. Three-rule tie-break (fractional remainder → weakness score → edge_id). CAT exams skip rounding (`is_adaptive=True` returns floats).
- **The dimensional code path matters.** Per `feedback_dimension_code_paths.md`, any change to `loadHierarchy()` must mirror to `loadDimensionHierarchy()`. Both enrichment functions (`enrichNodesWithQuestionCounts`, `enrichNodesWithFeasibility`) and the dimension cache invalidation are wired in both paths. IM Shelf / USMLE / NCLEX all use dimensions — it's the common case, not the edge case.
- **Canonical user-typed-value path:** `setExplicitWeight(edge_id, value, unit, reason)`. Single atomic call: writes `subject_edges.relative_weight`, sets `is_anchor=TRUE`, sets `weight_source='user_explicit'`, mirrors to `subject_nodes.relative_weight` for legacy reads. Replaces the pre-Stage-6 two-call hot patch.
- **Feasibility is save-then-warn.** `validate_hierarchy_feasibility` never blocks writes; the UI surfaces a yellow badge + tree warning dot. Status precedence: `over` → `infeasible` → `under` → `ok`. Red is reserved for save failures.
- **Confidence multiplier:** `official=1.0 > user_explicit=0.7 > user_defined=0.55 > derived=0.5 > user_estimate=0.4`. Final analytics confidence is `min(range_conf, source_conf)`.

---

## Documentation Map

| Document | Purpose | Last Updated |
|----------|---------|--------------|
| `CLAUDE.md` (root) | Quick reference for AI agents | May 15, 2026 |
| `docs/planning/FUTURE_VISION.md` | Primary roadmap & status (v3.3) | May 16, 2026 |
| `docs/status/SESSION_2026-05-16_CONSOLIDATED_STATUS.md` | This document | May 16, 2026 |
| `docs/status/SESSION_2026-05-15_CONSOLIDATED_STATUS.md` | Previous status snapshot | May 15, 2026 |
| `docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` | Arc 1 design doc (✅ Complete) | May 16, 2026 |
| `docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md` | Arc 1 stage rollout (✅ Complete) | May 16, 2026 |
| `docs/planning/POLYHIERARCHY_MIGRATION.md` | DAG migration plan (🟡 partially landed) | May 15, 2026 |
| `docs/planning/MIGRATION_RUNNER.md` | Versioned runner design | May 9, 2026 |
| `docs/planning/PYCHROME_MIGRATION.md` | Playwright→pychrome rewrite | May 8, 2026 |
| `docs/planning/TEST_INFRASTRUCTURE.md` | Test infra design + §8 wimi_test | May 7, 2026 |
| `docs/PLUGIN_DEVELOPMENT.md` | Plugin development guide | Mar 16, 2026 |
| `docs/BUILD_WINDOWS.md` | Windows build instructions | Jan 3, 2026 |
| `docs/BUILD_MACOS.md` | macOS build instructions | Feb 18, 2026 |
| `docs/architecture/completed_database_tables.md` | Database schema reference | Jan 2026 |
| `docs/guides/SHARED_SUBJECTS.md` | Polyhierarchy concept explainer | May 7, 2026 |
| `docs/guides/BRIDGE_METHODS_HYBRID_WEIGHTS.md` | Weight bridge surface reference | Jan 2026 |
