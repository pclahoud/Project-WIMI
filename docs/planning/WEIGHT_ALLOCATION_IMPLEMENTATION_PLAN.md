# Hierarchical Weight Allocation Implementation Plan

**Status:** ✅ Complete (Stages 0–9 landed 2026-05-15 → 2026-05-16; Stage 10 deferred) — last reviewed 2026-05-16
**Created:** 2026-05-15
**Companion docs:** `docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` (design, now ✅ Complete), `docs/planning/POLYHIERARCHY_MIGRATION.md` (schema dependency, landed), `docs/planning/TEST_INFRASTRUCTURE.md` (regression framework)

This document concretizes the seven `🔧 In progress / pending` items of the rework plan into landable stages. The polyhierarchy backend and the per-edge weight columns (`subject_edges.is_anchor`, `relative_weight`, `weight_source`) are already in production via `m004_subject_edges`. The tree-editor weight panel scaffold renders against legacy `subject_nodes` columns and must be cut over to the edge model in lockstep with the new behavior.

## Outcome (as of 2026-05-16)

All ten stages were executed across 2026-05-15 → 2026-05-16. **Nine landed**; Stage 10 (drop legacy `subject_nodes` weight columns) is explicitly deferred until ≥1 stable release lives with the new system, per the plan's own guidance.

| Stage | Status | Commit |
|---|---|---|
| 0 — Edge weight history (`m006`) | ✅ Landed | `ae723ed` |
| 1 — Hamilton allocator (backend) | ✅ Landed | `5db45d0` |
| 2 — Auto-rebalance opt-in | ✅ Landed | `bbb491f` |
| 3 — Edge-anchor bridge & per-edge writer | ✅ Landed | `9216e8d` (Batch D) |
| 4 — Exam length triple (`m007` + wizard) | ✅ Landed | `b357e1d` |
| 5 — Allocation bridge & read-side API | ✅ Landed | `9216e8d` (Batch D) |
| 6 — Dual-unit input + per-edge UX | ✅ Landed | `235fced` |
| 7 — Feasibility checker | ✅ Landed | `8883f12` (Batch F) |
| 8 — CAT exam handling | ✅ Landed | `8883f12` (Batch F) |
| 9 — `weight_source` in analytics | ✅ Landed | `8883f12` (Batch F) |
| 10 — Drop legacy node-level weight columns | 🕑 Deferred | — |

Plus bugfix commits along the way: `8890d8a` (live-render + root q_typical + dim cache), `9ebd77b` (`_compute_parent_q_budget` delegation), `e04e449` (warning dot contrast + breakdown card stylesheet).

**Final test footprint:**
- 114 weight-rework pytest tests pass (Hamilton, edge anchor, exam length, question allocation, explicit weights, feasibility, CAT, per-edge weights, dimension analytics)
- 7 wimi-test regression scenarios (`test_weight_no_silent_rebalance`, `test_anchor_per_edge`, `test_dual_unit_display`, `test_dual_unit_input`, `test_feasibility_badge`, `test_cat_exam_display`, `test_weight_source_markers`)
- Instrumented-slot CI gate: 179/180 paired (1 known exempt)

The remainder of this document — the stage-by-stage plan, dependency graph, recommended landing order, risks — is preserved as a historical record of the rollout. Stage 10's section near the bottom remains the canonical reference for that deferred work.

---

## Glossary and Conventions

- **Edge** = a row in `subject_edges`, identified by `edge_id`. Every weight write/read in this plan is keyed by `edge_id`, never by `(child_id)` alone.
- **Anchor** = `subject_edges.is_anchor=TRUE`. Anchored edges are exempt from sibling rebalance under the same parent. An anchor on edge A→C does **not** affect edge B→C.
- **Allocation** = the per-edge integer question count produced by Hamilton's method when the parent's exam has a `length_typical`.
- **System level** = a top-level subject node (no parent edges). Range semantics (`exam_weight_low/high` on `subject_nodes`) are retained at this level only.
- **`length_typical`** = the planning-baseline integer item count from the new `exam_contexts` length triple. Hamilton consumes this; CAT exams have it but skip rounding.

Architecture reminder: `UserDatabase` and `DatabaseBridge` are mixin compositions. New methods land in domain mixins (`edges.py`, `hierarchy.py`, `analytics_advanced.py`, `exam_contexts.py`, `weights.py` bridge). Mixins never import each other; cross-domain calls go through `self.*`.

---

## Stage 0 — Pre-Flight: Weight History on Edges

### Purpose

Every later stage writes to a weight history table. The current `subject_node_weights` table is keyed on `subject_node_id` and cannot record per-edge anchor toggles or rebalance side-effects under the right parent context. Stage 0 introduces the column we need before any code starts emitting events.

### Dependencies

- None on the rework side. Polyhierarchy migrations `m004` and `m005` are already landed.
- Resolves the rework plan's §4 Migration 3 ambiguity (the plan calls for renaming the table; this stage instead adds an `edge_id` column and leaves the table name untouched, since renaming a table referenced by 8+ existing call sites is a high-risk move with no upside).

### Database changes

New migration `m006_subject_edge_weight_history`:

```sql
-- Add edge_id (nullable for legacy rows) and broaden change_type enum.
ALTER TABLE subject_node_weights ADD COLUMN edge_id INTEGER
    REFERENCES subject_edges(id) ON DELETE SET NULL;

-- SQLite cannot ALTER a CHECK constraint in place. Use the
-- standard rename pattern: rebuild the table with the broader enum,
-- copy rows, drop old, rename new, recreate indexes.
-- Broader enum adds: 'anchor_set', 'anchor_cleared', 'allocation_recompute',
-- 'rebalance_request', 'edge_weight_edit'.

CREATE INDEX IF NOT EXISTS idx_weight_history_by_edge
    ON subject_node_weights (edge_id, edited_date DESC);
```

### Files to modify

- `src/database/migrations/user/m006_subject_edge_weight_history.py` (new)
- `src/database/migrations/user/__init__.py` — add to MIGRATIONS list
- `src/database/domains/hierarchy.py` — every `INSERT INTO subject_node_weights` call site updated to write `edge_id` when an edge context is known (currently 4 sites)

### Bridge / JS / UI

None.

### Test strategy

- `tests/database/migrations/test_m006_edge_weight_history.py`: assert column exists after upgrade, assert idempotency (re-run is safe), assert `change_type` accepts new enum values.
- Fixture update in `tests/database/test_user_db_phase2.py` to include `edge_id` in the schema check.

### Effort

Small (≤1 day).

### Open questions

None blocking.

---

## Stage 1 — Hamilton Allocator (Backend)

### Purpose

Implements §3.1 of the design: integer-question distribution across an edge's siblings using Largest Remainder (Hamilton) with the three-rule tie-break. Lives in the database layer and is the math foundation that every later UI stage consumes.

### Dependencies

- Stage 0 (history table can record `allocation_recompute` change events).
- Stage 4 (exam length triple) for `length_typical`. **However**, the allocator can be written and unit-tested first using a synthetic `length_typical` parameter — the schema dependency only kicks in when the bridge calls it. Stages 1 and 4 therefore run in parallel.
- The polyhierarchy `EdgesMixin` (already landed) for sibling enumeration.
- Open question OQ-1 (weakness-score recency decay) must be answered before tie-break rule 2 has its final form. **Default for v1**: 90-day half-life capped at the user's session_timer rounds for that subject, per §11 of the design doc. Make the half-life a constant in `hierarchy.py` so it can be tuned.

### Files to create / modify

- `src/database/domains/hierarchy.py` — add `allocate_questions_hamilton`, `compute_weakness_scores`, helper `_largest_remainder`
- `src/database/domains/edges.py` — add `get_sibling_edges(parent_id, exclude_edge_id=None)` helper that returns edge rows with `(edge_id, child_id, relative_weight, is_anchor, weight_source)` joined with the cached child name. **Important:** keep the read-side helper in `EdgesMixin` rather than `HierarchyMixin`, since edges.py is the natural home for any pure edge query. Hamilton itself stays in `hierarchy.py` because it composes weakness scores from the entries domain via `self.*`.
- `src/database/exceptions.py` — add `AllocationFeasibilityError` (raised only when input is structurally bad: e.g., negative weights). Infeasibility from rounding is **not** an exception, it is a return value (Stage 7).

### Method signatures

```python
# In HierarchyMixin
def allocate_questions_hamilton(
    self,
    parent_id: int,
    total_questions: int,
    *,
    weakness_lookup: Optional[Callable[[int], float]] = None,
) -> dict[int, int]:
    """Return {edge_id: allocated_q} for every outgoing edge of parent_id.

    `total_questions` is the parent's effective question budget (from
    length_typical * parent's effective relative_weight, computed by
    the caller). When the caller passes the root-level total directly,
    parent_id is the root system node.

    Tie-break order applied to fractional remainders:
      1. Larger fractional remainder (primary)
      2. Lower historical accuracy via weakness_lookup(edge_id)
      3. Lower edge_id (stable last-resort)

    Anchored edges keep their explicit allocation; only non-anchored
    edges participate in remainder distribution.
    """

def compute_weakness_scores(
    self,
    edge_ids: list[int],
    *,
    half_life_days: int = 90,
) -> dict[int, float]:
    """Recency-decayed mistake-rate per edge.

    Returns 1.0 for edges with no mistake history (so they are NOT
    biased toward when ties happen — neutral). Higher score = weaker
    topic = preferred to receive the leftover question.
    """
```

### Bridge changes

None in this stage. Bridge surface lands in Stage 5.

### JS API additions

None in this stage.

### UI changes

None in this stage.

### Test strategy

New file `tests/database/test_hamilton_allocation.py`:

| Scenario | Assertion |
|---|---|
| 10 questions, 3 children with weights 33/33/34 | One child gets 4, two get 3 — and the "4" goes to the heaviest weight (34) |
| 10 questions, 3 equal children | All weights 33.33: leftover goes via tie-break (weakness, then lowest `edge_id`) |
| 10 questions, anchored child fixed at 5 | Remaining 5 distributed across two non-anchored siblings |
| Sum of weights = 0 | Returns `{edge_id: 0}` for all edges; no division-by-zero |
| Single child | Gets all questions |
| Hamilton respects quota rule | Every allocation is `floor(share)` or `floor(share)+1` |
| Determinism | Same inputs ⇒ same outputs across 100 runs (no randomness) |
| Weakness tie-break | When two edges have equal fractional remainder, the one with higher weakness wins |

Coverage target: 95% on the new file (small surface, easy to cover exhaustively).

### Effort

Medium (2-3 days, mostly because the weakness-score query touches `entry_subject_mappings` and needs care to scope mistakes by `primary_parent_id`).

### Open questions

- **OQ-1 (deferred from design doc §11):** Half-life of 90 days is the v1 default. Empirical validation against real mistake distributions is a follow-up after one release.

---

## Stage 2 — Auto-Rebalance Opt-In

### Purpose

Resolves item #5 of the pending list. Currently `_rebalance_sibling_relative_weights` (`src/database/domains/hierarchy.py:1290-1378`) silently mutates every unlocked sibling whenever any child's weight changes, including when the user just typed a number. The fix is structural: *the writer never rebalances*; rebalance is a separate explicit operation.

### Dependencies

- Stage 0 (history records the rebalance event with a distinct `change_type`).
- Independent of Stages 1, 4, 5; can land before any UI work.

### Files to modify

- `src/database/domains/hierarchy.py`:
  - Rename `_rebalance_sibling_relative_weights` → `rebalance_sibling_edge_weights` (now public, edge-aware).
  - Refactor `update_subject_relative_weight` to **never** call rebalance internally. The caller must opt in by separately invoking `rebalance_sibling_edge_weights(parent_id, ...)`.
  - Add `update_edge_relative_weight(edge_id, relative_weight, *, set_anchor=False, source='user_explicit', reason=None)` as the new edge-aware writer. The existing `update_subject_relative_weight` becomes a thin shim delegating to the new method via the node's primary edge — it stays around for one release for backward compatibility, marked deprecated in the docstring.
  - `rebalance_sibling_edge_weights(parent_id, *, exclude_anchored=True)` walks `subject_edges` (not `subject_nodes`), excludes both `weight_locked` (legacy) and `is_anchor` (new) edges from the adjustable set, and writes `change_type='auto_recalculate'` history rows tagged with `edge_id`.

### Database changes

None directly (Stage 0 already broadened `change_type`).

### Bridge surface changes

- `src/app/bridge_domains/weights.py`:
  - Modify `updateRelativeWeight` to no longer rebalance siblings (returns empty `affected_siblings` list). Keep the slot signature stable to avoid JS breakage; document the behavior change in the response payload by always returning `rebalanced: false`.
  - Add `@pyqtSlot(int, str, result=str) rebalanceSiblings(parent_id, reason)` — explicit user-driven rebalance endpoint. Returns `{ok, affected_siblings: [{edge_id, child_id, old_weight, new_weight}, ...]}`.

### JS API additions

- `src/web/js/api/weights.js`:
  - `api.rebalanceSiblings({parentId, reason})` → calls bridge `rebalanceSiblings`.
  - Update `api.updateRelativeWeight` JSDoc to note that siblings are no longer auto-touched.

### UI changes

- `src/web/html/tree_editor.html` — add a "Rebalance siblings" button to the weight panel, gated behind the parent context. Disabled when there are no non-anchored siblings to adjust. Lives next to the existing "Apply Weight" button.
- `src/web/js/weight_editor.js` — wire the new button to `api.rebalanceSiblings`. Show a confirmation toast when adjustments would shift values >5 percentage points on any sibling.
- `src/web/css/weight.css` — minor styling for the new button.

### Test strategy

- `tests/database/test_edge_anchor_semantics.py` (extend Stage 3's planned file): update an edge's weight, then read all sibling edges — assert their weights are unchanged. Then call `rebalance_sibling_edge_weights` explicitly and assert the proportional distribution.
- `wimi_test/scenarios/test_weight_no_silent_rebalance.py` (new MCP-driven regression): open the tree editor, type `30` in one child's weight field, click Apply, reload, assert siblings retained their pre-edit values.

### Effort

Small (1 day backend, 0.5 day UI) — the change is mostly *removing* a call, not adding logic.

### Open questions

- Should the existing `weight_locked` flag be deprecated in favor of `is_anchor`? They overlap conceptually. **Decision for this stage:** keep both; `weight_locked` means "cannot be edited at all," `is_anchor` means "can be edited but won't be auto-mutated." Document the distinction in the migration guide.

---

## Stage 3 — Edge-Anchor Bridge & Per-Edge Writer

### Purpose

Wire the per-edge anchor concept (already in the schema) through the bridge and the JS API so the UI can set/clear anchors and write weights against a specific edge. This is the seam between the schema (already polyhierarchy-aware) and the UI (still node-aware in `weight_editor.js:87-105`).

### Dependencies

- Stage 2 (the writer no longer rebalances, so anchoring no longer needs to be a "fence" against a writer that mutates everything).
- Stage 0 (history captures `anchor_set` / `anchor_cleared`).
- Open question OQ-2 (anchor inheritance to descendants): **decision for v1**: no inheritance. Anchoring an edge does not propagate downward. Document in the bridge response payload so UI can rely on it.

### Files to modify

- `src/database/domains/edges.py`:
  - `set_edge_anchor(edge_id, is_anchor: bool, reason: str = '') -> SubjectEdge` — toggles `is_anchor`, writes a `subject_node_weights` history row with `change_type='anchor_set'` or `'anchor_cleared'` and `edge_id` populated.
  - `set_edge_weight_source(edge_id, source: str) -> None` — explicit setter so the bridge can mark `weight_source='user_explicit'` when the user types a value (Stage 6).

### Bridge surface changes

In `src/app/bridge_domains/weights.py`:

| Slot | Signature | Returns |
|---|---|---|
| `setEdgeAnchor` | `@pyqtSlot(int, bool, str, result=str)` `(edge_id, is_anchor, reason)` | `{ok, edge: {...}, weight_history_id}` |
| `updateEdgeRelativeWeight` | `@pyqtSlot(int, float, str, result=str)` `(edge_id, relative_weight, reason)` | `{ok, edge, old_weight, new_weight}` — does NOT rebalance siblings (per Stage 2). |
| `getEdgesForChild` | `@pyqtSlot(int, result=str)` `(child_id)` | `[{edge_id, parent_id, parent_name, relative_weight, is_anchor, weight_source, ...}]` — fuels the "switch parent" UX |

### JS API additions

In `src/web/js/api/weights.js`:

```js
api.setEdgeAnchor = async function({edgeId, isAnchor, reason}) { ... }
api.updateEdgeRelativeWeight = async function({edgeId, relativeWeight, reason}) { ... }
api.getEdgesForChild = async function(childId) { ... }
```

All three follow the existing `_callBridge` pattern. The first two serialize their args as positional Qt slot args; the third returns the parsed JSON.

### UI changes

Minimal in this stage — just instrument the existing weight panel to read `edge_id` from the selected tree row and pass it through. Full UI work (anchor pin icon, switch-parent affordance) lands in Stage 6.

In `src/web/js/weight_editor.js`:
- Extend `WeightEditorState` with `currentEdgeId` (replacing or supplementing the existing node-id-keyed flow).
- When `init()` is called for a node with an existing primary edge, populate `currentEdgeId` from the result of `api.getEdgesForChild(nodeId)` filtered by `is_primary`.

### Test strategy

- `tests/database/test_edge_anchor_semantics.py` (new):
  - `test_anchor_set_clears_under_one_parent_only` — Hypertension under Cardio and Pregnancy. Anchor edge under Cardio, verify Pregnancy edge `is_anchor` stays false.
  - `test_anchored_edge_survives_sibling_edit` — write to a sibling edge, verify the anchored edge's weight is byte-identical.
  - `test_anchor_history_event_records_edge_id` — assert the history row has the right `edge_id`, `change_type`, and `previous_weight`.
- `tests/app/test_weights_bridge.py` (extend) — slot calls return well-formed JSON and emit the `weightUpdated` Qt signal.

### Effort

Medium (2 days). The complexity is in maintaining the legacy `updateRelativeWeight` slot in parallel until UI fully cuts over.

### Open questions

- **OQ-3 (revert auto-distributed values):** When the user clears all anchors on a parent's children, do we recompute fresh from Hamilton or restore from history? **Decision for v1**: recompute fresh (per design doc §11). The `subject_node_weights` audit log preserves history if the user wants to manually restore a value.

---

## Stage 4 — Exam Length Triple (Schema + Bridge + Wizard)

### Purpose

Adds the `length_kind / length_min / length_max / length_typical / length_note` fields to `exam_contexts` per design §3.2. This is the storage substrate for question-count grounding (Stage 6) and CAT-aware allocation (Stage 8). Resolves item #2 (partially) and #4 (the schema half) of the pending list.

### Dependencies

- Independent of Stages 1, 2, 3. Can run in parallel with all three.

### Database changes

New migration `m007_exam_length_triple`:

```sql
ALTER TABLE exam_contexts ADD COLUMN length_kind TEXT
    CHECK(length_kind IN ('fixed','range','unknown')) NOT NULL DEFAULT 'unknown';
ALTER TABLE exam_contexts ADD COLUMN length_min     INTEGER;
ALTER TABLE exam_contexts ADD COLUMN length_max     INTEGER;
ALTER TABLE exam_contexts ADD COLUMN length_typical INTEGER;
ALTER TABLE exam_contexts ADD COLUMN length_note    TEXT;
```

Idempotent via `add_column_if_missing` (pattern from `m005`).

Application-layer constraint enforcement (not a DB CHECK because SQLite cannot reference multiple columns in a single CHECK without `CHECK(... AND ...)`, but we want to surface a clear validation error rather than a constraint violation):

| `length_kind` | Required | Allowed |
|---|---|---|
| `fixed` | `length_min == length_max == length_typical` | All three populated, equal |
| `range` | `length_min ≤ length_typical ≤ length_max` | All three populated |
| `unknown` | All three NULL | NULL |

Validation lives in `exam_contexts.py::update_exam_length`.

### Files to create / modify

- `src/database/migrations/user/m007_exam_length_triple.py` (new)
- `src/database/migrations/user/__init__.py` (register)
- `src/database/domains/exam_contexts.py`:
  - `update_exam_length(exam_context_id, kind, min, max, typical, note) -> ExamContextConfig` — validates the kind/value invariants from the table above.
  - `get_exam_length(exam_context_id) -> dict` (or extend the existing `get_exam_context_config` return shape).
  - `seed_known_exam_lengths()` — one-shot upgrade helper for the named exams in the design doc table (USMLE Step 1 = fixed/280, NCLEX-RN = range/85-150, etc.). Idempotent: only writes when `length_kind='unknown'` so it does not clobber user edits.
- `src/database/models.py` — `ExamContextConfig` dataclass gains the five new fields.

### Bridge surface changes

- `src/app/bridge_domains/exam_contexts.py` (or wherever exam-context CRUD lives):
  - `@pyqtSlot(int, str, int, int, int, str, result=str) updateExamLength(exam_context_id, kind, min, max, typical, note)` returns `{ok, length: {...}}` or `{ok: false, error: ...}` if validation fails.
  - `@pyqtSlot(int, result=str) getExamLength(exam_context_id)` returns the triple plus note.

### JS API additions

- `src/web/js/api/exam_contexts.js`:
  - `api.updateExamLength({examContextId, kind, min, max, typical, note})`
  - `api.getExamLength(examContextId)`

### UI changes

- `src/web/html/wizards/exam_wizard.html` — new step (or extension of Step 4) capturing the length triple. Three-radio control: `Fixed length` / `Variable length (CAT)` / `Don't know yet`. Conditional inputs based on the selection.
- `src/web/js/exam_wizard.js` — wire the radio + inputs; pre-fill from the seed when the user picks a named exam.
- `src/web/css/wizard.css` — minor styling for the radio group.
- `src/web/html/settings.html` (if it surfaces exam-context editing) — same controls in edit mode.

### Test strategy

- `tests/database/test_exam_length.py` (new):
  - Schema accepts all three `length_kind` values.
  - Validation rejects `kind='fixed'` with mismatched min/max/typical.
  - Validation rejects `kind='range'` with `typical < min` or `typical > max`.
  - `kind='unknown'` enforces all three are NULL.
  - Seeder is idempotent: re-running does not overwrite a `length_kind='fixed'` record.
- `wimi_test/scenarios/test_exam_wizard_length_step.py` — exam wizard renders the new step, `Variable length (CAT)` selection persists round-trip.

### Effort

Medium (2-3 days). UI work in the wizard is the bulk; the schema change is trivial.

### Open questions

- Should `length_typical` for CAT be user-editable or fixed at the recommended value (NCLEX-RN: 100)? **Decision for v1**: user-editable, pre-filled from the seeder. A CAT exam taker who knows their school's pass-rate distribution can tune it.

---

## Stage 5 — Allocation Bridge & Read-Side API

### Purpose

Exposes the Hamilton allocator (Stage 1) and the effective-question-count tree to the bridge so the UI can render `9.2% • ~26 q` (per §7.5 of the design). This is the "thin wiring" stage that makes Stages 1 + 4 visible to JS.

### Dependencies

- Stages 1 (allocator) and 4 (length triple) must both be in.

### Files to modify

- `src/database/domains/hierarchy.py`:
  - `get_effective_question_counts(exam_context_id) -> list[dict]` — recursive walk over `subject_edges`, returns `[{edge_id, child_id, parent_id, parent_path, relative_weight, weight_source, q_typical, q_low, q_high, is_anchor}]`. When `length_kind='unknown'`, `q_typical/low/high` are all NULL.
  - The existing `get_subjects_with_effective_weights` is extended (not replaced) with a `q_typical` field on each subject's `weight` dict so legacy callers keep working.

### Bridge surface changes

In `src/app/bridge_domains/weights.py`:

| Slot | Signature | Returns |
|---|---|---|
| `getQuestionAllocation` | `@pyqtSlot(int, result=str)` `(parent_id)` | `{ok, parent_id, total_q, children: [{edge_id, child_id, allocated_q, low_q, high_q, weight_source, is_anchor}]}` |
| `getEffectiveQuestionCounts` | `@pyqtSlot(int, result=str)` `(exam_context_id)` | Tree with `q_typical/low/high` per node |

`getQuestionAllocation` is the per-parent endpoint the weight panel calls when the user opens a parent's children for editing. `getEffectiveQuestionCounts` is the whole-tree endpoint analytics dashboards consume.

### JS API additions

- `api.getQuestionAllocation(parentId)`
- `api.getEffectiveQuestionCounts(examContextId)`

### UI changes

In `src/web/js/weight_editor.js` and `tree_editor.js`:
- When `length_kind !== 'unknown'`, render `XX.X% • ~N q` next to each weight chip. Implementation: extend `getWeightTooltip()` (line 610) and the chip text in the row renderer (line 532).
- Update the sibling preview chart (`weight_editor.js:909-938` per design doc) to show question counts in the bar tooltips.

In `src/web/js/weight_analysis.js`, `analytics_dashboard.js`, `subject_deep_dive.js`:
- Same dual-display where exam weights are shown.
- For nodes with multiple parent edges, the analytics drill-down adds a parent-context selector (UX text per design doc §7.5).

### Test strategy

- `tests/database/test_question_allocation_bridge.py` — covers the allocator output shape and length-kind awareness.
- `tests/app/test_weights_bridge.py` — slots return well-formed JSON.
- `wimi_test/scenarios/test_dual_unit_display.py` — open the tree, configure exam length to 280, expand a node with three children, assert the rendered chip text matches `\d+\.\d+% • ~\d+ q`.

### Effort

Medium (3 days). Most of the time is in the recursive read-side query and ensuring it walks edges correctly under polyhierarchy.

### Open questions

- For the whole-tree endpoint, do we precompute or compute on demand? **Decision for v1**: compute on demand. WIMI's hierarchies are <10K nodes; the recursive CTE benchmarks under 10ms even at that scale per `POLYHIERARCHY_MIGRATION.md` §11. A precomputed cache adds invalidation complexity for negligible gain.

---

## Stage 6 — Dual-Unit Input + Per-Edge Weight Panel UX

### Purpose

The user-facing payoff. Implements:
- Item #2 (Question-count grounding) — UX side
- Item #7 (Dual-unit input parser) — `%` ↔ `Q` segmented control
- Per-edge weight editor with parent-context disclosure and anchor toggle

### Dependencies

- Stage 3 (edge-anchor bridge) — required for the anchor pin
- Stage 4 (length triple) — required for the segmented control to know whether `Q` mode is available
- Stage 5 (question allocation API) — required for the `%` ↔ `Q` conversion
- Open question OQ-5 (multi-parent UX): per the design doc, v1 uses **per-edge modal with a "switch parent" link**. Tabs would be cleaner for ≤3 parents but break down at 7+ (hypertension). The link approach scales.

### Files to modify

- `src/web/html/tree_editor.html` (lines 312-349):
  - Replace the simple/range toggle markup with a parent-context header (`Weight for {child_name} under {parent_name}`).
  - Add the segmented control (`%` | `Q`) bound to the weight input. Hidden when `length_kind='unknown'`.
  - Add an "Anchor this value" checkbox (defaults checked when the user types).
  - Add a "Switch parent" link, visible when the current child has >1 parent edge.
  - Add an infeasibility badge slot (filled by Stage 7).
- `src/web/js/weight_editor.js`:
  - Refactor `init()` to take `edgeId` instead of `nodeId`. The tree row renderer passes the edge_id from the rendered context (see `tree_editor.js:520-595`).
  - `parseWeightInput(rawInput, currentUnit)` — handles magic suffixes (`10%`, `28q`) per design §3.6. Magnitude inference is rejected; the only cues are explicit suffixes or the segmented-control state.
  - `convertWeightUnit(value, from, to, parentQTypical)` — bidirectional conversion. `Q→%` divides by `parent_q_typical`; `%→Q` multiplies.
  - On Apply, call `api.updateEdgeRelativeWeight` followed by (if the anchor checkbox is checked) `api.setEdgeAnchor`. Order matters: write the value first, then anchor — so the history rows are in the right sequence.
  - Sibling preview chart distinguishes anchored (filled bar) vs auto (striped bar) per design §7.2.
- `src/web/js/tree_editor.js` (lines 520-595):
  - The weight chip's click handler passes the relevant `edge_id` (from `node.primary_edge_id`, populated by the polyhierarchy-aware hierarchy fetch).
  - Add the multi-parent chip on the tree row (`{N} parents`) when `node.parent_count > 1`.
- `src/web/css/weight.css`:
  - Segmented control styles (use existing `tree.css` toggle pattern as basis).
  - Anchor pin icon (filled when anchored, outline when not).
  - Striped bar style for auto-distributed siblings.
  - Status badge variants (OK / under / over) — empty until Stage 7 fills them.

### Bridge surface changes

- `setExplicitWeight` (the canonical user-typed-value endpoint per design §6) is implemented as a thin composition in `weights.py`:
  ```python
  @pyqtSlot(int, float, str, str, result=str)
  def setExplicitWeight(self, edge_id, value, unit, reason):
      # Convert Q to relative_weight if needed
      # Call update_edge_relative_weight with source='user_explicit'
      # Call set_edge_anchor(edge_id, is_anchor=True)
      # Return {ok, applied_relative_weight, applied_question_count}
  ```
  This stays in Stage 6 because it requires the Q↔% conversion, which depends on Stage 5.

### JS API additions

- `api.setExplicitWeight({edgeId, value, unit, reason})` — calls `setExplicitWeight`.
- Helpers in `weight_editor.js` (private): `parseWeightInput`, `convertWeightUnit`.

### Test strategy

- `tests/database/test_explicit_weight_anchors.py` — `setExplicitWeight` always sets `is_anchor=TRUE` and `weight_source='user_explicit'`.
- Unit tests for `parseWeightInput` (JS — add to existing JS test rig if present, otherwise documented as manual test cases until JS testing infrastructure exists):
  - `"10%"` → `{value: 10, unit: '%'}`
  - `"28q"` → `{value: 28, unit: 'Q'}`
  - `"45"` with current unit `%` → `{value: 45, unit: '%'}`
  - `"45"` with current unit `Q` → `{value: 45, unit: 'Q'}`
  - `"abc"` → `null` (validation fails; UI keeps focus and shows error)
- `wimi_test/scenarios/test_dual_unit_input.py`:
  - Configure exam at 280 questions, type `28q` in Cardio's edit field, click Apply, reload, assert the displayed value is `10.0% • ~28 q` and the anchor pin is filled.
  - Configure exam at `length_kind='unknown'`, open the same panel, assert the segmented control is hidden and the input only accepts `%`.

### Effort

Large (1-2 weeks). This is the user-facing centerpiece and has the highest UX surface area.

### Open questions

- **OQ-4 (default `relative_weight` for newly attached edges):** When a user attaches an existing node to a new parent (creating a new edge), v1 uses NULL = uncategorized; the next read fills via Hamilton; the user can override. Confirm UX copy when the user opens the editor for an uncategorized edge: "No weight set — system will compute one when you save."
- The "switch parent" link's destination: same modal, swap the edge context, OR new modal? **Decision for v1**: same modal, swap context (lighter perceived weight for the user).

---

## Stage 7 — Interval-Rounding Feasibility Checker

### Purpose

Item #6 of the pending list. Surfaces the warning when `Σ⌈child_lo·N/100⌉ > ⌊parent_hi·N/100⌋` (mathematically impossible to satisfy). Save-then-warn per design §3.5 — never blocks save.

### Dependencies

- Stage 4 (length triple) — `length_typical` and the parent's range are needed.
- Stage 6 (UI badge slot exists) — the warning chip lands in the slot Stage 6 created.

### Files to modify

- `src/database/domains/hierarchy.py`:
  - `validate_hierarchy_feasibility(parent_id, length_typical) -> dict` — returns `{status, parent_low_q, parent_high_q, children_low_sum_q, children_high_sum_q, violators}`. `status` is one of `'ok' | 'under' | 'over' | 'infeasible'`. `'infeasible'` is the rounding-class violation; `'under'`/`'over'` are the simple percentage-sum cases.
  - `validate_hierarchy_feasibility_recursive(exam_context_id) -> dict[parent_id, FeasibilityReport]` — for whole-tree badge rendering.

### Bridge surface changes

- `src/app/bridge_domains/weights.py`:
  - `@pyqtSlot(int, result=str) getFeasibilityReport(parent_id)`
  - `@pyqtSlot(int, result=str) getAllFeasibilityReports(exam_context_id)`

### JS API additions

- `api.getFeasibilityReport(parentId)`
- `api.getAllFeasibilityReports(examContextId)`

### UI changes

- `src/web/js/weight_editor.js`:
  - On panel open, call `getFeasibilityReport(parent_id)` and render the badge.
  - Tooltip copy:
    - `under`: *"Children sum to {X}% — {Y}% remaining. Add more children or increase a weight."*
    - `over`: *"Children sum to {X}% — {Y}% over. Reduce a weight or remove a child."*
    - `infeasible`: *"Can't fit child minimums (≥{N} q) into parent maximum ({M} q). Round more aggressively or reduce a child range."*
  - The badge does not block save; it's purely informational.
- `src/web/js/tree_editor.js`:
  - Tree rows show a small warning dot when their parent has a non-`ok` feasibility status. Click navigates to the affected parent's weight panel.

### Test strategy

- `tests/database/test_edge_feasibility_report.py`:
  - Children sum to 95% → `status='under'`, `parent_low_q - children_low_sum_q == ⌊5%·N⌋`.
  - Children sum to 105% → `status='over'`.
  - Five children each with `low=20%` under a parent with `high=80%` and N=10 → `Σ⌈2⌉ = 10` vs `⌊8⌋ = 8` → `status='infeasible'`.
  - Save still succeeds when status is non-ok (assert the row is in the database after the call).
- `wimi_test/scenarios/test_feasibility_badge.py` — load a fixture with a known infeasible config, assert the warning chip renders with the right copy.

### Effort

Medium (2 days). The math is small; the recursive whole-tree report has the bulk of the complexity.

### Open questions

- Should the badge be color-coded (yellow for over/under, red for infeasible)? **Decision for v1**: yellow for all warnings; red is reserved for save failures and we are explicitly never failing the save here. Avoids alarm fatigue.

---

## Stage 8 — CAT (Variable-Length Exam) Handling

### Purpose

Item #4 of the pending list. NCLEX-RN and similar adaptive exams have no fixed length. The allocator should not force a fictional static length; instead it should use `length_typical` as a planning baseline but skip integer rounding (return floats) so the analytics layer doesn't lie about precision.

### Dependencies

- Stage 4 (length triple, where `length_kind='range'` indicates CAT).
- Stage 1 (allocator), which gets a new `is_adaptive` parameter.
- Stage 6 (UI), which gates the segmented control on `length_kind` (already done in Stage 6 as a side benefit).

### Files to modify

- `src/database/domains/hierarchy.py`:
  - `allocate_questions_hamilton` gets an optional `is_adaptive` flag; when `True`, returns `dict[edge_id, float]` (raw `share` values from step 1 of Hamilton, no flooring or remainder distribution).
  - `get_effective_question_counts` reads `length_kind` and passes `is_adaptive` through.
- `src/database/domains/exam_contexts.py`:
  - Helper `is_adaptive_exam(exam_context_id) -> bool` returning `length_kind == 'range'`.

### Bridge / JS API

No new slots; the existing `getQuestionAllocation` and `getEffectiveQuestionCounts` returns gain an `is_adaptive: bool` field and float values where appropriate. Document the behavior change in the JSDoc.

### UI changes

- `src/web/js/weight_editor.js`:
  - When `is_adaptive=true`, render question counts as `~26.4 q (planning estimate)` instead of integer `~26 q`.
  - Help text under the input: *"Planning baseline: ~{typical} items (actual exam: {min}–{max}). Use this to budget your study allocation; the real exam ends when the algorithm reaches a confident decision."* (Copy from design §7.4.)
- `src/web/js/exam_wizard.js`:
  - The "Variable length (CAT)" radio reveals the planning-baseline copy.

### Test strategy

- `tests/database/test_cat_allocation.py`:
  - NCLEX exam with `length_kind='range'`, `length_typical=100`, three children with weights 40/35/25 → returns `{40.0, 35.0, 25.0}` floats, **not** integer-rounded.
  - The same exam with `length_kind='fixed'`, same children → integer Hamilton output.
  - `is_adaptive_exam` returns the right boolean for each `length_kind`.
- `wimi_test/scenarios/test_cat_exam_display.py`:
  - Configure an NCLEX context, open the weight panel, assert the planning-baseline copy is rendered and counts are floats.

### Effort

Small (1-2 days). Most of the work is conditional rendering; the math change is one branch in the allocator.

### Open questions

- For CAT exams, should the analytics quadrant categorization use the planning baseline or the range bounds? **Decision for v1**: range bounds (already what `_categorize_subject_quadrant` does in `analytics_advanced.py:1043-1089`). CAT just means the user shouldn't trust the integer counts.

---

## Stage 9 — Three-State `weight_source` in Analytics

### Purpose

Item #3 of the pending list. The schema already accepts `'official' | 'derived' | 'user_estimate' | 'user_defined' | 'user_explicit'` per the migration. The analytics layer needs to read these and treat user-typed anchors more confidently than system-derived estimates and less confidently than official outline values.

### Dependencies

- Stage 6 (the user can now create `user_explicit` entries via `setExplicitWeight`; otherwise this stage is academic).

### Files to modify

- `src/database/domains/analytics_advanced.py`:
  - `_calculate_efficiency_score` (line 1091) currently weights confidence purely by range width. Add a `weight_source` factor:

    | `weight_source` | Confidence multiplier |
    |---|---|
    | `official` | 1.0 |
    | `user_explicit` | 0.7 |
    | `user_defined` | 0.55 |
    | `derived` | 0.5 |
    | `user_estimate` | 0.4 |

    Final confidence = min(range-derived, source-derived). Rationale: range-narrow + system-derived is still less trustworthy than range-narrow + official.
  - `get_subject_exam_weight_analysis` (line 903): the SQL must join through `subject_edges` to read `weight_source` per edge (currently reads from `subject_nodes.weight_source` at line 60). Tag each subject row with its dominant `weight_source` (the edge with the highest absolute weight wins when a node has multiple edges).
  - Add `get_weight_source_breakdown(exam_context_id) -> dict` for analytics dashboard ("12 subjects user-anchored, 30 system-derived, ...").
- `src/database/domains/analytics.py` — same pattern for any other code path that consumes `relative_weight` or `weight_source` (audit pass; touch points should be small since most analytics queries already go through the `analytics_advanced.py` helpers).

### Bridge / JS / UI

- `getSubjectExamWeightAnalysis` already exists; no new slot, but the response payload gains `weight_source_distribution`.
- `src/web/js/weight_analysis.js` and `analytics_dashboard.js`:
  - Render small per-subject markers showing the source (filled circle for `official`, anchor pin for `user_explicit`, dashed circle for `derived`, etc.).
  - Add a "Confidence breakdown" card on the analytics dashboard showing the source distribution.

### Test strategy

- `tests/database/test_dimension_analytics.py` (extend): assert that an analysis with mixed `weight_source` values produces a different efficiency score than the same analysis with all `derived`. Specifically, `user_explicit` should reduce the penalty contribution by the new confidence multiplier.
- `tests/database/test_per_edge_weights.py` (new per design §9.1): single child with two parent edges, different `weight_source` per edge. Assert the analytics row reflects the dominant source per the rule above.

### Effort

Medium (3 days). The audit of all weight-consuming analytics code paths is the bulk; the actual confidence-multiplier change is small.

### Open questions

- **OQ-6 (new):** When the user has both an `is_anchor=TRUE` edge and `weight_source='user_explicit'` on the same edge (the normal case after Stage 6), do we count that as one source or two for confidence? **Decision for v1**: one — `weight_source` is the canonical signal. `is_anchor` is a behavioral flag (don't auto-mutate) and doesn't independently affect confidence.

---

## Stage 10 — Drop Legacy Node-Level Weight Columns (Deferred)

### Purpose

Per design §8 step 4. After one stable release with all read paths cut over to `subject_edges`, drop `subject_nodes.relative_weight`, `subject_nodes.weight_source`, and `subject_nodes.display_order`. This stage is **explicitly deferred** — list it here so it doesn't get forgotten, but do not schedule it until at least one production release has run with the new system.

### Dependencies

- All other stages (1-9) landed and stable for ≥1 release.
- Audit confirming no code reads `subject_nodes.relative_weight` directly.

### Database changes

New migration `m008_drop_legacy_weight_columns_on_nodes`:

```sql
-- SQLite cannot DROP COLUMN with CHECK constraints intact. Use the
-- standard rename pattern: build a replacement subject_nodes without
-- the three columns, copy data, drop original, rename, recreate
-- indexes and triggers.
```

### Files to modify

- `src/database/migrations/user/m008_*.py` (new)
- Code audit pass to remove dead reads.

### Effort

Small (1 day) once the dead-code audit confirms no remaining references.

---

## Dependency Graph

```
                                 +---------------------+
                                 | Stage 0             |
                                 | Edge weight history |
                                 +----------+----------+
                                            |
              +-----------------------------+-----------------------------+
              |                                                           |
              v                                                           v
   +---------------------+    +---------------------+    +---------------------+
   | Stage 1             |    | Stage 2             |    | Stage 4             |
   | Hamilton allocator  |    | Auto-rebalance      |    | Exam length triple  |
   |                     |    | opt-in              |    |                     |
   +----+----------------+    +----------+----------+    +----------+----------+
        |                                |                          |
        |                                v                          |
        |                     +---------------------+               |
        |                     | Stage 3             |               |
        |                     | Edge-anchor bridge  |               |
        |                     +----------+----------+               |
        |                                |                          |
        +-----------------+--------------+----------+               |
                          |                         |               |
                          v                         v               v
                +---------------------+    +---------------------+
                | Stage 5             |    | Stage 7             |
                | Allocation bridge   |    | Feasibility checker |
                +----------+----------+    +---------------------+
                           |                         ^
                           v                         |
                +---------------------+              |
                | Stage 6             +--------------+
                | Dual-unit input +   |
                | edge weight panel   |
                +----------+----------+
                           |
              +------------+------------+
              |                         |
              v                         v
   +---------------------+    +---------------------+
   | Stage 8             |    | Stage 9             |
   | CAT exam handling   |    | weight_source in    |
   |                     |    | analytics           |
   +---------------------+    +---------------------+
                           |
                           v
                +---------------------+
                | Stage 10 (DEFERRED) |
                | Drop legacy columns |
                +---------------------+
```

**Parallelism:**
- Stages 1, 2, 4 can land in parallel after Stage 0.
- Stage 3 needs Stage 2 only.
- Stages 5 and 7 need Stages 1 + 4. Stage 7 also needs Stage 6's UI badge slot, but the backend half can land before Stage 6.
- Stage 8 piggybacks on Stages 4 and 6.
- Stage 9 only needs Stage 6 (the substrate that produces `user_explicit` rows in the wild).

## Recommended Landing Order

1. **Stage 0** (history) — gate for everything that writes.
2. **Stages 1, 2, 4** in parallel (separate PRs).
3. **Stage 3** — wires Stage 2 to the bridge.
4. **Stage 5** — exposes Stage 1's output.
5. **Stage 7 backend** — depends on Stage 4; the badge slot lands empty in the UI until Stage 6.
6. **Stage 6** — the UX centerpiece. Heaviest stage; worth its own milestone. Stage 7's UI badge wires up here.
7. **Stage 8** — small additive change; can land any time after Stages 4+6.
8. **Stage 9** — analytics polish; can land after Stage 6 once `user_explicit` rows exist in real data.
9. **Stage 10** (deferred ≥1 release).

**Reasoning:** Stage 6 is the user-visible behavior change, and it cannot land without the substrate from Stages 1, 3, 4, 5. Stages 7-9 are polish that builds on Stage 6 and can ship piecemeal. Treating Stages 0-5 as a coordinated branch (matches the polyhierarchy plan's §12 advice) avoids a confusing intermediate state where the bridge knows about edges but the UI still writes to nodes.

## Risks and Unknowns

### Architectural

- **Bridge backward-compatibility surface.** The existing `updateRelativeWeight` slot is callable from JS today and silently mutates siblings. Stage 2 changes that behavior without changing the slot signature. Any caller (JS or otherwise) relying on the side effect will silently lose it. Audit `src/web/js/` for `updateRelativeWeight` usage before landing Stage 2 — the Grep on `updateRelativeWeight` hit only `weight_editor.js` and `api/weights.js`, but a fresh sweep at land time is non-negotiable.
- **`weight_locked` vs `is_anchor` overlap.** Both flags currently exclude an edge from rebalance. Stage 2's decision (keep both, distinct semantics) is workable but creates a UX puzzle: which icon means what? Recommend a single deprecation pass in a follow-up where `weight_locked` becomes "edit-protected" only, and `is_anchor` is the sole rebalance fence.

### Empirical investigation needed

- **Weakness-score query performance.** Stage 1's tie-break consults `entry_subject_mappings` filtered by `primary_parent_id`. At >100 children per parent (rare but possible), this is O(N) joins per allocation. Benchmark against a synthetic dataset with 500 children before committing to the half-life-decay implementation. If it's slow, cache weakness scores per parent on a 5-minute TTL.
- **Recursive CTE depth on deep polyhierarchy.** `validate_hierarchy_feasibility_recursive` (Stage 7) and `get_effective_question_counts` (Stage 5) both walk the full edge graph. SQLite's default recursion depth is 1000; deeply nested hierarchies (a USMLE outline can reach 6 levels but a custom user hierarchy could go 10+) might trip this. Set `PRAGMA recursive_triggers=ON;` and `PRAGMA max_recursion_depth=...;` defensively.

### Design ambiguities flagged in the rework doc but not yet resolved

- **OQ-1 (weakness half-life):** 90 days is the v1 default. Empirical validation post-launch.
- **OQ-2 (anchor inheritance):** v1 says no inheritance; needs user testing to confirm the behavior matches mental models.
- **OQ-3 (revert behavior on full anchor clear):** v1 recomputes fresh; alternative is restoring from history.
- **OQ-4 (default `relative_weight` for new edges):** v1 NULL-then-Hamilton; needs UX validation on the "uncategorized" copy.
- **OQ-5 (multi-parent UX):** v1 uses per-edge modal with switch-parent link; tabs may be revisited if user count of parents-per-leaf trends low.

### Migration risk

- The `subject_node_weights` history table is `ALTER`ed in Stage 0 to gain `edge_id`. Existing rows have `edge_id=NULL`. Any downstream report that joins on `edge_id` must use `LEFT JOIN` or filter `WHERE edge_id IS NOT NULL`. Audit the reports in `analytics_advanced.py` and `dimension_analytics.py` (note: the latter does not exist as a separate file — dimension analytics live in `dimensions.py` and `analytics.py`; correct the design doc reference accordingly when wiring Stage 9).
- Seed exam template migration in design doc §8 step 9 ("Migration of seed exam templates to declare `length_kind` for known exams") is folded into Stage 4's `seed_known_exam_lengths()` helper. It runs idempotently on app startup so existing user data is not clobbered.

## Testing Infrastructure Note

The `wimi_test/` regression framework (Phase 2 of `docs/planning/TEST_INFRASTRUCTURE.md`) is now operational with smoke tests passing per `tests/wimi_test/test_smoke_phase2.py`. The MCP facade (`wimi-test`) is also live (mentioned in MCP server instructions). Recommended scenario coverage by stage:

| Stage | Recommended `wimi_test` scenario |
|---|---|
| 1 | None — pure backend math, covered by pytest |
| 2 | `test_weight_no_silent_rebalance.py` — type a weight, reload, assert siblings unchanged |
| 3 | `test_anchor_per_edge.py` — anchor under one parent, edit a sibling under another parent, assert no cross-talk |
| 4 | `test_exam_wizard_length_step.py` — wizard renders + persists the triple |
| 5 | `test_dual_unit_display.py` — dual `% • ~q` chips render at the right precision |
| 6 | `test_dual_unit_input.py` — magic-suffix parser, segmented control, anchor pin behavior |
| 7 | `test_feasibility_badge.py` — badge renders with the right copy for each violation class |
| 8 | `test_cat_exam_display.py` — CAT exam shows planning copy, hides the segmented control gracefully |
| 9 | `test_weight_source_markers.py` — analytics dashboard shows source markers and the breakdown card |

For Stages 1, 7 backend, and 9, prefer the `mcp__wimi-db` toolset for assertion; the seeded fixtures from `wimi_test/db/seeders.py` (specifically the `seed_usmle_outline` helper, which leverages the polyhierarchy fixture at `tests/fixtures/usmle_step1_outline.txt`) provide realistic multi-parent topology and are the right reference data for Stage 6 and beyond.

For each scenario, follow the locator preference order from `docs/testing/UI_AUDIT.md` (role+name → testid → CSS). When new testids are needed, name them `tree-weight-edge-{edge_id}-anchor-pin`, `tree-weight-edge-{edge_id}-unit-toggle`, `tree-weight-feasibility-badge`, etc., to mirror the existing `tree-node-weight-{node_id}` convention from `tree_editor.js:592`.

### Critical Files for Implementation

The five files most load-bearing for landing this plan:

- `src/database/domains/hierarchy.py`
- `src/database/domains/edges.py`
- `src/app/bridge_domains/weights.py`
- `src/web/js/weight_editor.js`
- `src/database/domains/analytics_advanced.py`
