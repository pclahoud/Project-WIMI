# Hierarchical Weight Allocation Rework

**Status:** ✅ Complete (Stages 0–9 landed + Stage 9 polish; Stage 10 deferred ≥1 release) — last reviewed 2026-05-16
**Created:** 2026-05-07 (revised same day to align with polyhierarchy migration)
**Related docs:** `WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md` (the 10-stage rollout broken out from this design), `POLYHIERARCHY_MIGRATION.md` (companion plan, fully landed), `PHASE7_MULTI_DIMENSIONAL_HIERARCHY.md`, `ENTRY_AND_SUBJECT_IMPROVEMENTS.md`

## Implementation Status (as of 2026-05-16)

**✅ Landed (Stages 0–9):**
- **Stage 0** — `m006_subject_edge_weight_history`: nullable `edge_id` on `subject_node_weights` + broadened `change_type` enum (`anchor_set` / `anchor_cleared` / `allocation_recompute` / `rebalance_request` / `edge_weight_edit`)
- **Stage 1** — Hamilton allocator (`allocate_questions_hamilton`) with Largest Remainder + weakness-biased tie-break, recency-decayed `compute_weakness_scores` (90-day half-life), edge enumeration via `get_sibling_edges`
- **Stage 2** — Auto-rebalance is now opt-in: `update_subject_relative_weight` no longer silently mutates siblings; new explicit `rebalance_sibling_edge_weights` + `rebalanceSiblings` bridge slot + "Rebalance siblings" UI button
- **Stage 3** — Per-edge anchor & writer: `set_edge_anchor`, `set_edge_weight_source`, `get_edges_for_child` on `EdgesMixin`; bridge slots `setEdgeAnchor` / `updateEdgeRelativeWeight` / `getEdgesForChild`; `currentEdgeId` wired through the weight editor
- **Stage 4** — `m007_exam_length_triple`: `length_kind` enum + `length_min`/`length_max`/`length_typical`/`length_note` on `exam_contexts`; new wizard length step; `seed_known_exam_lengths` for USMLE/NCLEX/MCAT/GRE/NBME
- **Stage 5** — Allocation read-side: `get_effective_question_counts` (with synthetic root rows so System chips get `q_typical`); `getQuestionAllocation` + `getEffectiveQuestionCounts` slots; dual-unit `XX.X% • ~N q` chip display via `enrichNodesWithQuestionCounts` (mirrored to both `loadHierarchy` and `loadDimensionHierarchy`)
- **Stage 6** — Dual-unit input + per-edge weight panel UX (the centerpiece): `parseWeightInput` magic-suffix parser (`10%`, `28q`), segmented `%` / `Q` control, anchor checkbox, switch-parent affordance, parent-context header, anchored vs auto sibling bars, canonical `setExplicitWeight` bridge slot (atomic write + anchor + source)
- **Stage 7** — Save-then-warn feasibility checker: `validate_hierarchy_feasibility` + recursive variant; `getFeasibilityReport` + `getAllFeasibilityReports` slots; yellow feasibility badge on the weight panel + warning dots on tree rows (mirrored to dimension path)
- **Stage 8** — CAT exam handling: `allocate_questions_hamilton` gets `is_adaptive` flag (skips integer rounding for `length_kind='range'`); `is_adaptive_exam` helper; chips render `~26.4 q (planning estimate)` floats; wizard CAT-radio planning-baseline copy
- **Stage 9** — `weight_source` in analytics: `_WEIGHT_SOURCE_CONFIDENCE` multiplier table feeds `_calculate_efficiency_score` (`min(range_conf, source_conf)`); `get_subject_exam_weight_analysis` reads dominant edge's source with `subject_nodes` fallback; per-row source markers (●⚓○⊘); "Weight Sources" breakdown card on the analytics dashboard; structural multi-parent context selector on the subject deep-dive
- **Stage 9 polish** (2026-05-16, commits `9b81e7e` / `41c27ab` / `4aca402`) — Multi-parent context selector now genuinely refilters the deep-dive. `getSubjectDeepDive` accepts a `primary_parent_id` parameter; agg WHERE clause switches to a two-branch "Show everything always" semantic (no filter = all entries tagged on subject; filter = NULL-context entries + entries routing through chosen parent). Payload gains `path_via_parent` (root → chosen parent → ... → subject) so the breadcrumb actually changes on selection, plus `entries_scoped_elsewhere` to drive an explanatory banner under the selector. Tag context pill landed on the question entry form (`POLYHIERARCHY_MIGRATION.md §7.3`): pill renders below each primary-subject chip whose leaf has ≥2 parents and persists through `setPrimaryParentForEntry` on the existing autosave path. **Policy:** every multi-parent subject on a new entry gets a non-NULL `primary_parent_id` on save (canonical primary if the user doesn't touch the pill) — NULL is now legacy-only for new entries; the lenient pass-through in the selector filter is a backward-compat behavior for pre-policy rows.

**Plus bugfixes from manual testing:**
- Live-render after Rebalance siblings (dimension cache invalidation, Bug 8890d8a)
- Root System nodes get synthetic `q_typical` row so chips show "11–15% • ~36 q"
- `_compute_parent_q_budget` now delegates to `get_effective_question_counts` instead of bailing to `length_typical` on the first uncategorized ancestor edge — Histology under Anatomy under GI now reports ~3 q instead of 280 q
- Apply Weight auto-anchors via `setExplicitWeight` (collapses the pre-Stage-6 two-call hot patch)
- Blur handler shows a clear error toast for out-of-range Q conversions instead of silently clamping to 100
- Warning dot CSS contrast (filled yellow circle instead of yellow-on-yellow)
- `weight.css` loaded on the analytics dashboard so Stage 9's breakdown card actually styles

**🕑 Deferred:**
- **Stage 10** — Drop legacy `subject_nodes.relative_weight` / `weight_source` / `display_order` columns. Per the implementation plan, deferred until at least one stable release lives with Stages 0–9 in production.

**🔧 Adjacent follow-ups (not strictly Arc 1, tracked in `FUTURE_VISION.md`):**
- Edit-mode Tag context pill on `entry_detail.html` (reuse the question-entry helpers).
- Backfill UX for legacy NULL entries on multi-parent subjects (one-time assist; not blocking — NULL still works through the lenient deep-dive filter).
- `hierarchy.py` mixin split (~3,000 lines after Arc 1 — purely a code-organization follow-up).

**Bottom line:** The rework is complete in user-facing behavior. The DAG schema, Hamilton allocator, dual-unit input, anchor semantics, feasibility checker, CAT support, weight_source-aware analytics, AND the multi-parent deep-dive view are all live. The only remaining item is Stage 10's column drop, which is intentionally gated on real-world stability.

---

> **Important dependency:** This plan originally placed weight metadata (`is_anchor`, `relative_weight`, `weight_source`, `display_order`) on `subject_nodes`. Empirical analysis of the official USMLE Step 1 content outline (preserved at `tests/fixtures/usmle_step1_outline.txt`) confirms that 12–18% of named clinical topics — and >40% of high-yield common-disease topics — appear under multiple parents within the same outline (DVT, hypertension, diabetes, sepsis, anemia, thyroid disorders, pneumonia, hepatitis, TB, etc.). A subject node will therefore have multiple parents, and the same node can legitimately carry different weights under each parent (PE under Respiratory ≠ PE under Pregnancy Complications). All weight metadata in this plan now lives on `subject_edges`, not `subject_nodes`. See `POLYHIERARCHY_MIGRATION.md` Section 3 for the edge schema this plan depends on.

## 1. Problem Statement

Users assigning weights to subjects in WIMI's exam-content outline have two distinct mental models:

- **Range thinking** (matches official content outlines): "Cardiovascular is 7–11% of USMLE Step 1."
- **Explicit value thinking** (matches study planning): "I expect 7 arrhythmia questions" or "I want Arrhythmias to count as 30% of Cardiovascular."

The current Hybrid Weight System (Phase 7.1) supports both modes via `exam_weight_low/high` ranges and the `relative_weight` column, but four failures prevent users from confidently assigning explicit single values to children:

1. **Auto-rebalance clobbers explicit input.** `_rebalance_sibling_relative_weights` (`hierarchy.py:1230-1315`) silently mutates unlocked siblings whenever any child's weight changes. A user who types "30%" on one child can return to find other siblings have shifted without consent.
2. **`weight_source` conflates intent.** Both "user typed this deliberately" and "system derived this" become `user_estimate`. Analytics cannot down-weight estimates relative to explicit anchors.
3. **No question-count grounding.** Weights are stored as abstract percentages even though students think in terms of "how many questions will this be on the real exam." The schema cannot express "Cardio = 25 questions out of 280."
4. **Single-node weight cannot represent the same topic under multiple parents.** Hypertension has different weight under Cardiovascular than under Pregnancy Complications. Storing weight on the node forces a lie under one parent or the other.

The reviewer of an earlier draft also surfaced four implementation gotchas this plan resolves:

- Integer remainder distribution (10 questions, 3 children → who gets the extra?)
- Computer Adaptive Tests (NCLEX has no fixed length)
- Dual-unit input ambiguity ("45" — questions or percent?)
- Interval rounding feasibility (`Σ⌈child_lo·N/100⌉ > ⌊parent_hi·N/100⌋` is mathematically impossible)

## 2. Goals & Non-Goals

**Goals**

- Let users assign explicit single values (percentage or question count) to any subject node *under a specific parent* without surprise side effects on siblings.
- Express weights in question counts when the exam declares a length, while preserving range semantics from official outlines.
- Distinguish explicit user anchors from system-derived estimates throughout the data model and analytics layer.
- Handle CAT (variable-length) exams without forcing a fictional static length.
- Validate hierarchical sum constraints without blocking saves of in-progress (infeasible) state.
- Honor per-edge weight semantics so a node's importance can differ legitimately under different parents.

**Non-Goals**

- Removing the existing range columns. Top-of-hierarchy nodes ("system" level) still carry official ranges; those stay on `subject_nodes` (a system has only one identity, so no per-edge ambiguity).
- Auto-import of official weights from external sources (separate feature).

## 3. Design Decisions

### 3.1 Allocation method: Largest Remainder (Hamilton) with weakness-biased tie-break

When the system needs to distribute N integer questions across K children whose weights don't divide evenly, use Hamilton:

1. Compute each child's exact share `q_i = N · w_i / Σw`.
2. Floor each share to get a base allocation `⌊q_i⌋`.
3. Award the leftover units one-by-one to children with the largest fractional remainder.

**Tie-break order** (deterministic and stable across edits):

1. Larger fractional remainder
2. Lower historical accuracy (weakness score, computed from the user's mistake history on entries mapped to this subject **under this parent context** — see `entry_subject_mappings.primary_parent_id` in companion plan)
3. Lower stable `subject_edges.id`

The middle rule is the pedagogically interesting one — when remainders tie, the extra question goes to whichever topic the student is weaker on. This routes marginal study toward weak areas without requiring a separate adaptive-allocation feature.

**Rejected alternatives:**
- D'Hondt / Jefferson — biases toward larger children, which over-allocates to already-strong topics. Pedagogically backwards.
- Sainte-Laguë — mathematically least biased, but its divisor mechanic is opaque to users and can violate the quota rule.
- Huntington-Hill — geometric-mean rounding is hard to explain in tooltip copy.

### 3.2 Exam length: triple + kind enum, not a single integer

Replace the previously-proposed `total_questions INTEGER NOT NULL` with a length triple:

```
length_kind     TEXT CHECK(IN ('fixed','range','unknown')) NOT NULL DEFAULT 'unknown'
length_min      INTEGER  -- nullable
length_max      INTEGER  -- nullable
length_typical  INTEGER  -- nullable; the "planning baseline" used for math
length_note     TEXT     -- e.g. "+13 CCS cases"
```

Allocation math reads from `length_typical`. The range is shown only as informational copy. Validation: `kind='fixed'` ⇒ `min=max=typical`; `kind='range'` ⇒ `min≤typical≤max`; `kind='unknown'` ⇒ all NULL.

Reference values:

| Exam | kind | min | max | typical |
|---|---|---|---|---|
| NCLEX-RN | range | 85 | 150 | 100 |
| USMLE Step 1 (May 2026+) | fixed | 280 | 280 | 280 |
| USMLE Step 2 CK | fixed | 318 | 318 | 318 |
| MCAT | fixed | 230 | 230 | 230 |
| GRE General | fixed | 54 | 54 | 54 |
| NBME Shelf | fixed | 110 | 110 | 110 |
| Custom / unknown | unknown | NULL | NULL | NULL |

### 3.3 Anchor flag separate from weight_locked, on the *edge*

`weight_locked` was already overloaded ("cannot be edited"). Anchoring is a different concept: "this child's value should not be mutated by sibling rebalance, but the user can still edit it."

`is_anchor` lives on `subject_edges`, not `subject_nodes`. The same node may be anchored under one parent and auto-distributed under another:

```
subject_edges (parent_id, child_id, is_anchor, relative_weight, weight_source, display_order, ...)
```

The rebalance function exempts anchored edges from the adjustable set:

```python
adjustable_siblings = [e for e in sibling_edges
                      if not e['weight_locked']
                      and not e['is_anchor']]
```

When a user explicitly types a value into a child's weight field *under a specific parent*, the bridge sets `is_anchor = TRUE` on that edge only. A toolbar control lets the user un-anchor.

### 3.4 New `weight_source` value: `'user_explicit'` (on the edge)

Add `'user_explicit'` to the enum (`official | derived | user_estimate | user_defined | user_explicit`) on `subject_edges.weight_source`. Set when the user manually types a value via the new explicit-input flow on that edge. Analytics confidence weighting treats `user_explicit` between `derived` and `official` (more reliable than `user_estimate`, less than `official`).

### 3.5 Save-then-warn on interval infeasibility

Backend writes whatever weights are given. Never refuse to save. Surface the infeasible subset through the soft validation badge. Round outward at leaves (`⌊lo·N/100⌋` for child minimums, `⌈hi·N/100⌉` for child maximums) so intervals widen rather than over-constrain.

### 3.6 Dual-unit input: segmented control + accelerator

UI uses an adjacent segmented control (`%` | `Q`) bound to the weight input, plus magic-suffix parsing as an accelerator (typing `10%` flips the segment to `%`, typing `28q` flips it to `Q`). Magnitude inference is rejected.

When `length_kind='unknown'` (no `length_typical`), the segmented control is hidden and the input is locked to `%` only. The same component degrades gracefully across all three length kinds.

### 3.7 Weight context disclosure in UI

Because the same node may carry different weights under different parents, the weight editor must show *which parent's weight* is being edited. The editor header reads:

> *Weight for **Pulmonary Embolism** under **Respiratory Disorders***
> *(This subject also appears under Pregnancy Complications — switch parent to edit that weight separately.)*

The "switch parent" affordance navigates to the edge editor for the alternate parent, opened in the same modal.

## 4. Schema Changes

### Migration 1 — Exam length triple

```sql
ALTER TABLE exam_contexts ADD COLUMN length_kind TEXT
    CHECK(length_kind IN ('fixed','range','unknown')) NOT NULL DEFAULT 'unknown';
ALTER TABLE exam_contexts ADD COLUMN length_min     INTEGER;
ALTER TABLE exam_contexts ADD COLUMN length_max     INTEGER;
ALTER TABLE exam_contexts ADD COLUMN length_typical INTEGER;
ALTER TABLE exam_contexts ADD COLUMN length_note    TEXT;
```

Add to `src/database/domains/schema_migrations.py` as a versioned migration. Existing rows default to `'unknown'`.

### Migration 2 — Weight metadata on subject_edges

This migration depends on `POLYHIERARCHY_MIGRATION.md` having created `subject_edges`. The columns `is_anchor`, `relative_weight`, `weight_source`, and `display_order` are added to `subject_edges` rather than `subject_nodes`:

```sql
-- Performed as part of subject_edges creation in the polyhierarchy plan, listed here for clarity:
ALTER TABLE subject_edges ADD COLUMN is_anchor BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE subject_edges ADD COLUMN relative_weight REAL;
ALTER TABLE subject_edges ADD COLUMN weight_source TEXT NOT NULL DEFAULT 'derived'
    CHECK(weight_source IN ('official','derived','user_estimate','user_defined','user_explicit'));
ALTER TABLE subject_edges ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0;

-- Backfill from existing subject_nodes during the polyhierarchy migration:
-- For each existing subject_node with relative_weight or weight_source set,
-- copy the value to the subject_edges row representing that node's single (legacy) parent.
```

Existing `subject_nodes.relative_weight` and `subject_nodes.weight_source` are retained read-only during migration, then dropped in a follow-up migration once analytics queries cut over.

### Migration 3 — Weight history table

`subject_node_weights` already audits changes. Rename to `subject_edge_weights` and add `edge_id INTEGER REFERENCES subject_edges(id)`. Extend `change_type` to include `'anchor_set'` and `'anchor_cleared'` for traceability.

## 5. Backend Changes (`src/database/domains/hierarchy.py`)

> **Architecture note:** WIMI uses a mixin-composition pattern. `src/database/user_db.py` is a thin shell (~111 lines) that composes 16+ domain mixins from `src/database/domains/`; `src/app/bridge.py` (~106 lines) composes 19 mixins from `src/app/bridge_domains/`. New methods listed below land in the appropriate domain mixin (e.g., new methods on `hierarchy.py` extend `HierarchyMixin`), not on a monolithic class. Mixins never import each other — cross-domain calls go through `self.*` since they share the composed instance. The JavaScript API in `src/web/js/api/` mirrors this same domain split.

### 5.1 New methods

| Method | Purpose |
|---|---|
| `set_edge_anchor(edge_id, is_anchor: bool, reason: str)` | Toggle anchor flag on an edge, log to weight history |
| `allocate_questions_hamilton(parent_id) -> dict[edge_id, int]` | Compute integer question allocation across a parent's outgoing edges using Hamilton with weakness tie-break |
| `compute_weakness_scores(edge_ids) -> dict[edge_id, float]` | Used by tie-break: returns mistake_count / mapping_count per edge (filtered by `entry_subject_mappings.primary_parent_id` to scope mistakes to the correct parent context), recency-decayed |
| `validate_hierarchy_feasibility(parent_id) -> FeasibilityReport` | Returns `{status: 'ok'|'under'|'over'|'infeasible', violators: [...]}` for UI badge, evaluated over a parent's outgoing edges |
| `get_effective_question_counts(exam_context_id) -> tree` | Recursive: computes `q_typical`, `q_low`, `q_high` per (node, parent_path) from `length_typical` × edge weight |

### 5.2 Modified methods

- **`update_edge_relative_weight`** (replaces `update_subject_relative_weight`) — When called by the bridge with `is_explicit=True`, sets `subject_edges.is_anchor=TRUE` and `subject_edges.weight_source='user_explicit'` for that edge only. Skips rebalance call when the *target* edge is the only edit.
- **`_rebalance_sibling_edge_weights`** (replaces `_rebalance_sibling_relative_weights`) — Operates on edges with the same `parent_id`, not on nodes with the same `parent_id`. Filters `adjustable_siblings` to exclude both `weight_locked` and `is_anchor`. Uses Hamilton when a `length_typical` is present.
- **`get_subjects_with_effective_weights`** — Returns one row per (node, parent_path) tuple. Adds `q_typical` field alongside `effective`. Path is now needed because the same node can appear with different effective weights.

### 5.3 Validation

Constraints checked at write time but **never block save**:

- `length_kind='fixed'` ⇒ `length_min == length_max == length_typical`
- `length_kind='range'` ⇒ `length_min ≤ length_typical ≤ length_max`
- `subject_edges.is_anchor=TRUE` requires `subject_edges.relative_weight IS NOT NULL` OR `subject_nodes.exam_weight_low IS NOT NULL`

If a constraint fails, write the row anyway and emit a warning the bridge surfaces to the UI.

## 6. Bridge Changes (`src/app/bridge_domains/weights.py`)

New `@pyqtSlot` methods:

| Slot | Args | Returns |
|---|---|---|
| `setEdgeAnchor` | `edge_id, is_anchor, reason` | JSON `{ok, weight_history_id}` |
| `setExplicitWeight` | `edge_id, value, unit ('%' \| 'Q'), reason` | JSON `{ok, applied_relative_weight, applied_question_count}` |
| `getQuestionAllocation` | `parent_id` | JSON `{children: [{edge_id, child_id, allocated_q, low_q, high_q, source}]}` |
| `getFeasibilityReport` | `parent_id` | JSON `{status, violators}` |
| `updateExamLength` | `exam_context_id, kind, min, max, typical, note` | JSON `{ok}` |
| `getEdgesForChild` | `child_id` | JSON `[{edge_id, parent_id, parent_name, relative_weight, is_anchor, ...}]` — used by the "switch parent" UX |

`setExplicitWeight` is the canonical entry point for user-typed weights. It:
1. Converts `Q` to `relative_weight` when needed (`(value / parent_q_typical) * 100`).
2. Sets `subject_edges.is_anchor=TRUE` and `subject_edges.weight_source='user_explicit'` on the target edge only.
3. Calls `update_edge_relative_weight` with skip-rebalance-of-anchors semantics.
4. Returns both forms so the UI can show the conversion.

## 7. Frontend Changes

### 7.1 API wrappers (`src/web/js/api/weights.js`)

Add: `setEdgeAnchor`, `setExplicitWeight`, `getQuestionAllocation`, `getFeasibilityReport`, `updateExamLength`, `getEdgesForChild`.

Calls take `{edgeId, ...}` rather than `{nodeId, ...}` for write paths.

### 7.2 Weight editor (`src/web/js/weight_editor.js`)

- The editor takes an `edge_id`, not a `node_id`. The header shows "Weight for **{child_name}** under **{parent_name}**".
- If the child has multiple parent edges, show a "View weights under other parents" link that opens a list of edge rows; selecting one switches the modal to that edge.
- Replace the simple/range toggle with a unit-aware input component.
- Render a segmented control (`%` | `Q`) when `exam.length_kind !== 'unknown'`. Hide when unknown — `%` only.
- On user input, call `setExplicitWeight` (which auto-anchors the edge). Show a small anchor icon next to anchored edges with a tooltip ("This value won't be auto-adjusted under this parent. Click to release.").
- Sibling preview chart (`weight_editor.js:909-938`) operates on edge siblings under the current parent. Distinguish anchored edges visually (filled bar) from auto-distributed ones (striped bar).
- Replace the "Apply will change siblings" implicit behavior with an explicit confirmation when non-anchored siblings *would* shift.

### 7.3 Tree editor modal (`src/web/html/tree_editor.html:267-321`)

- Modal opens scoped to a specific edge. Pass `edge_id` from the tree-row context.
- Remove `modal-weight-range-toggle`. Range mode is reserved for top-level system nodes only and inferred from `exam_source`.
- Add an "Anchor this value" checkbox next to the weight input. Defaults to checked when the user types a value, unchecked when the value is system-derived.
- Add infeasibility badge: a status pill near the weight input that reads `OK` / `Under-allocated (X q remaining)` / `Over-allocated (Y q over)` based on `getFeasibilityReport(parent_id)`.
- For nodes that appear under multiple parents, show a small "{N} parents" chip next to the node name, clickable to open the parent-list modal.

### 7.4 Exam wizard (`src/web/html/wizards/exam_wizard.html`)

Add a new step or extend Step 4 to capture exam length:

- Radio: `Fixed length` / `Variable length (CAT)` / `Don't know yet`
- Conditional inputs based on selection.
- Inline help quoting USMLE/NCLEX/NBME official lengths for common exams.
- Copy for adaptive: *"Planning baseline: ~{typical} items (actual exam: {min}–{max}). Use this to budget your study allocation; the real exam ends when the algorithm reaches a confident decision."*

### 7.5 Analytics rendering

`weight_analysis.js`, `analytics_dashboard.js`, `subject_deep_dive.js`:

- Display effective weight in dual form (`9.2% • ~26 q`) when `length_typical` is set.
- For nodes with multiple parent edges, analytics drill-down shows a parent-context selector ("Show as part of: Respiratory / Pregnancy Complications / All parents").
- Tag user-explicit weights with a small marker so users see which numbers are anchored vs. derived.
- Confidence weighting in `get_subject_exam_weight_analysis` (`analytics_advanced.py:873-1010`) treats `user_explicit` at confidence 0.7 (between `derived` 0.5 and `official` 1.0).

## 8. Migration Strategy for Existing Data

1. Run schema migrations idempotently on app startup (existing pattern in `schema_migrations.py`). Order: polyhierarchy first (creates `subject_edges`), then this plan's migrations.
2. **Backfill weight metadata to edges**: for each existing `subject_node` with `relative_weight` or non-default `weight_source`, write the values to the single `subject_edges` row representing that node's legacy parent. Because pre-migration data is strict-tree, every node has exactly one parent edge — backfill is unambiguous.
3. For existing `exam_contexts`: leave `length_kind='unknown'`. Users opt in by editing exam settings.
4. After successful backfill and a release cycle of read-only access to legacy columns, drop `subject_nodes.relative_weight`, `subject_nodes.weight_source`, and `subject_nodes.display_order`. This is a follow-up migration, not part of the initial rollout.
5. Existing `weight_source='user_estimate'` rows are not migrated to `user_explicit` automatically — we don't know the user's intent retroactively. New explicit edits set `user_explicit` going forward.

No data loss. No behavioral change for existing hierarchies until the user engages with the new UI.

## 9. Testing Plan

### 9.1 New test files

- `tests/database/test_hamilton_allocation.py` — Hamilton math, tie-break ordering, weakness-biased tie-break with stubbed mistake history. Includes a fixture that constructs a small DAG and verifies allocation runs per-edge.
- `tests/database/test_edge_anchor_semantics.py` — Setting/clearing edge anchors, rebalance respects per-edge anchors, anchored edges survive sibling edits *under the same parent*, an anchor on one parent edge does not affect the same node's edge under a different parent.
- `tests/database/test_exam_length.py` — Length triple validation, kind transitions, NULL handling.
- `tests/database/test_edge_feasibility_report.py` — Per-parent under/over/infeasible scenarios, save-doesn't-block on infeasibility.
- `tests/database/test_per_edge_weights.py` — A single child node with two parent edges carrying different `relative_weight` values; effective-weight calculation per parent path; `get_subjects_with_effective_weights` returns multiple rows.

### 9.2 Test fixture: USMLE Step 1 outline

`tests/fixtures/usmle_step1_outline.txt` (full extracted outline, 99KB, 1800+ lines) is retained as a reference fixture. Tests that exercise polyhierarchy and weight-allocation behavior should construct subject hierarchies modeled on this outline so behavior is validated against real-world structures with known multi-parent topics (DVT, hypertension, sepsis, etc.). A helper `tests/fixtures/load_usmle_outline.py` parses the file into a list of `(parent_path, leaf_topic)` tuples for use by tests.

### 9.3 Existing tests to update

- `tests/database/test_dimension_analytics.py` — Confidence weighting changes for `user_explicit` (now per-edge).
- `tests/database/test_user_db_phase1.py` — Schema fixture must include new columns on `subject_edges`.

### 9.4 Manual UI test scripts

- Create a fixed-length exam (USMLE Step 1, 280 q). Set top-level system to range 7–11%. Add three children. Type explicit Q values into two; verify the third auto-fills to balance and the two typed values are preserved across reloads.
- Create a CAT exam (NCLEX, 85–150). Confirm the Q segment is hidden. Confirm planning copy mentions the range.
- Set children that sum over the parent's high range. Confirm save succeeds, badge shows "Over-allocated", analytics still render.
- **Polyhierarchy weight scenario**: Add Hypertension under both Cardiovascular and Pregnancy. Set 10% under Cardio, 2% under Pregnancy. Confirm both values persist and analytics show per-parent breakdown. Anchor under Cardio; edit a Cardio sibling; verify only non-anchored Cardio siblings rebalance and the Pregnancy edge is untouched.

### 9.5 Coverage requirement

Maintain 80%+ coverage threshold (per `pytest.ini`). New modules expected to add ~700 lines of test code (up from the prior 600 estimate due to per-edge tests).

## 10. Rollout Order

This plan layers on top of the polyhierarchy migration:

1. **Polyhierarchy migration** (`POLYHIERARCHY_MIGRATION.md`). Lands first.
2. **Migration 1** — Exam length triple on `exam_contexts`. No behavior change.
3. **Migration 2** — Weight columns on `subject_edges`. Backfilled from legacy node columns.
4. **Backend allocation + edge-anchor methods**. Unit tests, no UI.
5. **Bridge methods**. Smoke-test via dev console.
6. **Weight editor UI** with segmented control, parent-context title, and edge anchor pin.
7. **Exam wizard length step**.
8. **Analytics dual-display** with per-parent effective weights and confidence weighting update.
9. **Migration of seed exam templates** to declare `length_kind` for known exams.
10. **Drop legacy `subject_nodes` weight columns** — follow-up migration after one stable release.

Each step is independently shippable and reversible up through step 10.

## 11. Open Questions

- **Weakness score recency decay** — How aggressively should older mistakes decay in the tie-break score? Suggestion: half-life of 90 days, capped at the user's session_timer rounds for that subject. Needs validation against actual mistake distributions.
- **Anchor inheritance** — When a parent edge is itself anchored, should descendants inherit the anchor? Probably no — anchoring is per-edge — but worth confirming with a user test.
- **Reverting auto-distributed values** — If a user clears all anchors on a parent's edges, do we restore to the most recent system-derived state, or recompute fresh? Suggestion: recompute fresh; the audit log preserves history.
- **Default weight when adding a new parent edge** — When a user attaches an existing node to a new parent (creating a new edge), what is the initial `relative_weight`? Suggestion: NULL (uncategorized); system fills via auto-distribution on next read; user can override.
- **Multi-parent weight UX** — When a user opens the weight editor for a node with 5 parent edges, should the editor show all 5 in tabs, force the user to pick one, or open per-edge as separate modals? Current plan: per-edge modals with a "switch parent" link. Open to refinement.

(The previous "multi-dimensional anchors" question is resolved: per-edge by design.)

## 12. References

- Polyhierarchy migration prerequisite: `POLYHIERARCHY_MIGRATION.md`
- Empirical evidence for per-edge weights: USMLE Step 1 Content Outline 2025 (NBME) — preserved at `tests/fixtures/usmle_step1_outline.txt`. Hypertension under 7 different system sections with materially different weights in each.
- Apportionment methods: [Wikipedia: Mathematics of apportionment](https://en.wikipedia.org/wiki/Mathematics_of_apportionment), [Balinski & Young, Fair Representation]
- Tie-breaking in scheduling: [Asai et al., IJCAI 2018](https://www.ijcai.org/proceedings/2018/0655.pdf)
- Variable-length CATs: [He & Reckase, Item Pool Design for Variable-Length CAT], [NCSBN 2026 NCLEX-RN Test Plan](https://www.ncsbn.org/publications/2026-nclex-rn-test-plan)
- USMLE length update: [USMLE Test Delivery Software Updates May 2026](https://www.usmle.org/usmle-test-delivery-software-updates-coming-2026)
- Dual-unit input UX: [Primer Segmented Control Accessibility](https://primer.style/product/components/segmented-control/accessibility/), [PatternFly Units and Symbols](https://www.patternfly.org/ux-writing/units-and-symbols/)
- Constraint feasibility: [Springer: Minimal infeasible constraint sets](https://link.springer.com/article/10.1007/s10898-009-9443-x)

## 13. File Inventory (touched by this plan)

**Backend**
- `src/database/schema/user_db_schema_v1_phase1.sql` — column additions documented (note: weight columns now on `subject_edges`)
- `src/database/domains/schema_migrations.py` — three new migrations (after polyhierarchy migrations)
- `src/database/domains/edges.py` (new, also created by polyhierarchy plan) — edge weight ops
- `src/database/domains/hierarchy.py` — Hamilton allocation, edge rebalance
- `src/database/domains/analytics_advanced.py` — confidence weighting for `user_explicit` edges
- `src/database/models.py` — `SubjectEdge.is_anchor`, `SubjectEdge.relative_weight`, `SubjectEdge.weight_source`

**Bridge**
- `src/app/bridge_domains/weights.py` — six new edge slots
- `src/app/bridge_domains/exams.py` (or wherever exam_context CRUD lives) — `updateExamLength`

**Frontend**
- `src/web/js/api/weights.js` — wrapper additions (edge_id signatures)
- `src/web/js/weight_editor.js` — segmented control, parent-context title, edge anchor pin, infeasibility badge, "switch parent" affordance
- `src/web/js/tree_editor.js` — modal updates, multi-parent chip, edge-aware weight invocation
- `src/web/js/wizards/exam_wizard.js` — length step
- `src/web/html/tree_editor.html` — modal markup
- `src/web/html/wizards/exam_wizard.html` — length step markup
- `src/web/css/weight.css` — anchor icon, segmented control, status badge styles
- `src/web/js/weight_analysis.js`, `analytics_dashboard.js`, `subject_deep_dive.js` — per-parent dual-display

**Tests**
- New: `test_hamilton_allocation.py`, `test_edge_anchor_semantics.py`, `test_exam_length.py`, `test_edge_feasibility_report.py`, `test_per_edge_weights.py`
- Fixture: `tests/fixtures/usmle_step1_outline.txt`, `tests/fixtures/load_usmle_outline.py`
