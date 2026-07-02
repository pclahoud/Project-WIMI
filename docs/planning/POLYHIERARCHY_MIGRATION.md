# Polyhierarchy Migration: Strict Tree → Directed Acyclic Graph

**Status:** 🟡 Partially Landed (backend complete, UX in progress) — last reviewed 2026-05-15
**Created:** 2026-05-07
**Companion plan:** `HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` (depends on this one for `subject_edges`)
**Related docs:** `PHASE7_MULTI_DIMENSIONAL_HIERARCHY.md`, `ENTRY_AND_SUBJECT_IMPROVEMENTS.md`

## Implementation Status (as of 2026-05-15)

**✅ Landed:**
- `subject_edges` table (`m004_subject_edges`) with `(parent_id, child_id, dimension_id, is_anchor, relative_weight, weight_source, sort_order)` schema (§3.1)
- `m005_primary_parent_id` migration adds explicit primary-parent tracking
- `EdgesMixin` (`src/database/domains/edges.py`) — edge CRUD, cycle prevention, primary-parent invariant
- `GraphMixin` (`src/database/domains/graph.py`) — DAG traversal layered on top
- `get_subject_hierarchy` and `getDimensionHierarchy` rewritten to walk `subject_edges` (commits `7d4548d`, `f8b51b1`)
- Polyhierarchy bridge slots + JS API (commit `f82c8cd`)
- Tree editor parents-management UI (§7) — add-parent, switch-primary, alias chip on non-primary appearances, auto-reveal new appearance
- USMLE seeder upgraded to full polyhierarchy parse (commit `a6e3f92`)
- Tests: `test_subject_edges`, `test_polyhierarchy_traversal`, `test_get_subject_hierarchy_polyhierarchy`, `test_primary_parent_context`, plus the migration tests

**🔧 In progress / pending:**
- Per-edge weight UX (covered by companion plan `HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`)
- Optional parent-context tagging on entries (§5) — schema exists via `primary_parent_id`, but the entry-form opt-in UI has not landed
- Breadcrumb disambiguation in analytics drilldowns when an entry's leaf has multiple parents
- Cross-dimensional polyhierarchy (still a Non-Goal per §2; both parents must share `dimension_id` in the current implementation)

**Migration path:** Legacy `subject_nodes.parent_id` column still exists but is being phased out. New code MUST walk `subject_edges`; do not read `parent_id` directly.

---

## 1. Problem Statement

WIMI's subject hierarchy is currently a strict tree: each `subject_nodes` row has exactly one `parent_id`. Real exam content outlines are not trees. The official USMLE Step 1 content outline (extracted to `tests/fixtures/usmle_step1_outline.txt`, 99KB, 1,327 lines) explicitly lists topics under multiple parents within the same outline. Concrete examples:

- **DVT / venous thromboembolism** — under `Cardiovascular → Vascular disorders → diseases of the veins` (line 754) AND under `Pregnancy → Systemic disorders affecting pregnancy` (line 1150).
- **Pulmonary embolism** — under `Respiratory System → Pulmonary vascular disorders` (line 834); pregnancy-context PE rolls up via the same VTE listing under Pregnancy.
- **Hypertension** — under Cardiovascular, Pregnancy (preeclampsia/HELLP), Renal, Endocrine, CNS, Eye, and Heart Failure (eight occurrences across seven distinct sections).
- **Sepsis** — under Multisystem/Shock, Pregnancy/Obstetric complications, Puerperium, Endocrine, Blood/spleen, Skin, MSK.
- **Diabetes mellitus** — Endocrine plus three separate Pregnancy entries (gestational, type 1/2, prenatal risk).
- **Anemia, thyroid disorders, asthma, cirrhosis, appendicitis, pancreatitis, heart failure, seizures, obesity, myasthenia, hepatitis, tuberculosis, pneumonia, UTI** — all explicitly listed in 2+ sections of the same outline.

NBME also hand-codes cross-references in the source PDF (`"hereditary nonpolyposis colorectal cancer (gastrointestinal and female reproductive)"`), and the front matter says foundational science is *"distributed throughout the organ systems based on disease process/diagnosis."* The official taxonomy is polyhierarchic by design.

A sample of ~25 high-frequency clinical entities found ~20 with multi-section listings. Extrapolating: **12–18% of named topics appear in multiple sections**, climbing to **>40%** if restricted to the high-yield common-disease subset that exam-prep apps actually prioritize.

The strict tree forces WIMI users to either duplicate leaves (breaking analytics consolidation, fragmenting weight settings, and producing inconsistent breadcrumbs) or pick one home and lose the cross-section retrievability the exam structure intends.

## 2. Goals & Non-Goals

**Goals**

- Allow a single `subject_nodes` row to have multiple parents within the same exam dimension.
- Preserve all current analytics semantics with honest non-additivity (a mistake on a multi-parent leaf counts once across the *union* of ancestors, but separately under each parent's own rollup).
- Allow per-edge weight metadata (consumed by `HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`).
- Give users an optional, non-blocking way to record which parent context an entry was logged under (for analytics framing).
- Prevent cycles in the graph at edit time.
- Remain on SQLite. Recursive CTEs over the new junction table stay performant at WIMI's scale (<10K nodes per user).

**Non-Goals**

- Cross-dimensional polyhierarchy in the initial migration. Both parents of a multi-parent leaf must share the same `dimension_id` for now. (See Open Questions §11.)
- Switching to a graph-database backend. SQLite + recursive CTEs is sufficient.
- A graph-style visual editor. The tree-editor UI continues to render a tree, with shared leaves repeated under each parent (SNOMED-style). See §7.
- Forcing users to choose a parent context at tag time. The choice is optional and additive.

## 3. Schema Design

### 3.1 New table: `subject_edges`

```sql
CREATE TABLE subject_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER NOT NULL REFERENCES subject_nodes(id) ON DELETE CASCADE,
    child_id  INTEGER NOT NULL REFERENCES subject_nodes(id) ON DELETE CASCADE,

    -- per-edge attributes (some consumed by HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md)
    is_primary       BOOLEAN NOT NULL DEFAULT FALSE,  -- canonical parent for breadcrumbs/search
    display_order    INTEGER NOT NULL DEFAULT 0,
    is_anchor        BOOLEAN NOT NULL DEFAULT FALSE,  -- weight rework
    relative_weight  REAL,                            -- weight rework
    weight_source    TEXT NOT NULL DEFAULT 'derived'
        CHECK(weight_source IN ('official','derived','user_estimate','user_defined','user_explicit')),

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(parent_id, child_id),
    CHECK(parent_id != child_id)  -- no self-loops; longer cycles handled at app layer
);

CREATE INDEX idx_subject_edges_parent ON subject_edges(parent_id, display_order);
CREATE INDEX idx_subject_edges_child  ON subject_edges(child_id);
CREATE INDEX idx_subject_edges_primary ON subject_edges(child_id) WHERE is_primary = TRUE;
```

### 3.2 Modifications to `subject_nodes`

`parent_id` is dropped after a one-release deprecation cycle. During migration, both the column and `subject_edges` coexist with `parent_id` read-only.

`relative_weight`, `weight_source`, `display_order`, and `is_anchor` (if any of these existed on `subject_nodes`) are dropped in the follow-up migration after the weight rework cuts over to `subject_edges`. See `HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` Section 8 for the cutover sequence.

### 3.3 Modifications to `entry_subject_mappings`

Add an optional parent-context column:

```sql
ALTER TABLE entry_subject_mappings ADD COLUMN primary_parent_id INTEGER
    REFERENCES subject_nodes(id) ON DELETE SET NULL;
```

When the user tags an entry with a leaf that has multiple parents, the entry form *may* record which parent context the user navigated through (e.g., "this PE question was logged from the Pregnancy Complications view"). NULL means "no specific context — count under all parents." See §6 and §8 for the UX and analytics treatment.

### 3.4 Cycle prevention

SQLite has no native `CYCLE` clause and no cross-table CHECK constraints. Cycles are prevented in the bridge layer at edge-insert time:

```python
def _would_create_cycle(parent_id: int, child_id: int) -> bool:
    # Reject if parent_id is already a descendant of child_id
    cur = self.execute("""
        WITH RECURSIVE descendants(id) AS (
            SELECT child_id FROM subject_edges WHERE parent_id = :child_id
            UNION
            SELECT se.child_id FROM subject_edges se
            JOIN descendants d ON se.parent_id = d.id
        )
        SELECT 1 FROM descendants WHERE id = :parent_id LIMIT 1
    """, {"parent_id": parent_id, "child_id": child_id})
    return cur.fetchone() is not None
```

Read-side queries use `UNION` (not `UNION ALL`) defensively so accidental data cycles do not produce infinite loops in CTEs.

## 4. Migration Steps

### Migration 1 — Create `subject_edges` and backfill

```sql
-- 1. Create subject_edges (definition above).
-- 2. Backfill one edge per existing parent_id, marking it primary:
INSERT INTO subject_edges (parent_id, child_id, is_primary, display_order)
SELECT parent_id, id, TRUE, COALESCE(sort_order, 0)
FROM subject_nodes
WHERE parent_id IS NOT NULL;
-- 3. Leave subject_nodes.parent_id in place, read-only, for one release.
```

### Migration 2 — Add `entry_subject_mappings.primary_parent_id`

```sql
ALTER TABLE entry_subject_mappings ADD COLUMN primary_parent_id INTEGER
    REFERENCES subject_nodes(id) ON DELETE SET NULL;
-- Existing rows default to NULL, meaning "no specific context."
```

### Migration 3 (deferred) — Drop `subject_nodes.parent_id`

After one stable release with all read paths cut over to `subject_edges`. Performed via the standard SQLite table-rename pattern (create new table without the column, copy, drop old, rename, recreate indexes).

## 5. Backend Changes (`src/database/domains/`)

> **Architecture note:** WIMI uses a mixin-composition pattern. `src/database/user_db.py` is a thin shell (~111 lines) that composes 16+ domain mixins from `src/database/domains/`; `src/app/bridge.py` (~106 lines) composes 19 mixins from `src/app/bridge_domains/`. The new `edges.py` file below defines an `EdgesMixin` class that gets added to `UserDatabase`'s mixin list. Existing files like `hierarchy.py`, `analytics_advanced.py`, and `dimensions.py` host their respective mixins — modifications below extend those mixins. Mixins never import each other — cross-domain calls go through `self.*` since they share the composed instance. The JavaScript API in `src/web/js/api/` mirrors this same domain split.

### 5.1 New methods (in new `edges.py` mixin)

| Method | Purpose |
|---|---|
| `add_edge(parent_id, child_id, is_primary=False)` | Create an edge; rejects cycles via `_would_create_cycle` |
| `remove_edge(edge_id)` | Delete an edge; if it was the only edge for a child, the child becomes orphaned (allowed; user can re-parent later) |
| `set_primary_parent(child_id, new_primary_parent_id)` | Atomically clear `is_primary` on existing edges for the child and set it on the new one |
| `get_parents(child_id) -> list[ParentEdge]` | Returns all (parent_id, edge_id, is_primary) for a child |
| `get_paths_to_root(child_id) -> list[list[node_id]]` | Returns every distinct root-to-child path; primary path is first |
| `_would_create_cycle(parent_id, child_id) -> bool` | Internal cycle check |

### 5.2 Recursive CTE rewrites

The codebase audit identified six recursive CTEs that walk the hierarchy via `JOIN subject_nodes ON parent_id`. Each rewrite joins through `subject_edges` and uses `COUNT(DISTINCT entry_id)` to avoid analytics inflation when a leaf is reachable through multiple paths:

| CTE / method | File:line | Rewrite outline |
|---|---|---|
| `_build_descendant_cte` | `src/database/domains/_base.py:94-111` | Join `subject_edges se ON se.parent_id = d.id`; descend via `se.child_id`. |
| `_get_descendant_node_ids` | `src/database/domains/_base.py:76-87` | Same pattern; ensure `DISTINCT` on the result set. |
| `_build_subject_path` | `src/database/domains/_base.py:42-49` | Walks up via `is_primary=TRUE` edges to construct the canonical path. Non-primary paths obtained via `get_paths_to_root` when needed. |
| `get_subject_deep_dive` | `src/database/domains/analytics_advanced.py:74-80` | `JOIN subject_edges se ON sn.id = se.child_id AND se.parent_id = d.id`; aggregate with `COUNT(DISTINCT entry_id)`. |
| `_aggregate_hierarchy_counts` | `src/database/domains/dimensions.py:660-675` | Build `children[parent_id]` by querying `subject_edges` rather than `subject_nodes.parent_id`. |
| `_cross_dimension_query_with_children` | `src/database/domains/dimensions.py:1018-1097` | Both inner CTEs walk `subject_edges`; outer aggregation deduplicates entries with `DISTINCT`. Cross-dimension polyhierarchy is out of scope for the initial migration, so the dual-CTE shape is preserved, just with edge joins. |

### 5.3 Aggregation policy: honest non-additivity (OMOP pattern)

A mistake on a leaf rolls up to **every** ancestor reachable through any path, but each (entry, ancestor) pair is counted **exactly once** via `COUNT(DISTINCT entry_id)`. Consequence: when a node has multiple parents, sums of children may not equal the parent (because the same entry counts once under each parent). This is correct — the same mistake legitimately reflects on both Cardiovascular and Pregnancy when the leaf is shared. UI labels disclose the policy: "12 entries (counted once each in this rollup)."

**Rejected alternative:** fractional attribution (1/N per parent) — biases per-parent rates downward, breaks row-level drill-down (cannot point at "0.5 of a question"), non-deterministic when the user re-parents nodes. Fatal for a metacognitive tool whose value proposition is honest self-reflection.

### 5.4 `primary_parent_id` semantics in analytics

When `entry_subject_mappings.primary_parent_id IS NOT NULL`, the entry rolls up *only* through that parent's ancestors. This lets the user tag a "PE in a pregnant patient" question with PE under Pregnancy context, and the entry will only contribute to Pregnancy-chain analytics, not Respiratory-chain analytics — even though the leaf is shared.

When `primary_parent_id IS NULL` (default for new tags and all legacy entries), the entry rolls up through every ancestor reachable from the leaf. This is the OMOP-style behavior described in §5.3.

### 5.5 Effective-weight queries

`get_subjects_with_effective_weights` returns one row per (node, parent_path) tuple. The same node may appear with different effective weights under different parent paths, reflecting the per-edge weight reality from the companion weight rework plan.

## 6. Bridge Changes

| Slot | Args | Returns |
|---|---|---|
| `addParent` | `child_id, parent_id` | `{ok, edge_id}` or `{error: 'cycle'}` |
| `removeParent` | `edge_id` | `{ok}` |
| `setPrimaryParent` | `child_id, parent_id` | `{ok, edge_id}` |
| `getParents` | `child_id` | `[{edge_id, parent_id, parent_name, is_primary, display_order}]` |
| `getPathsToRoot` | `child_id` | `[[node_id, ...], ...]` (primary path first) |
| `setPrimaryParentForEntry` | `entry_id, subject_node_id, primary_parent_id \| null` | `{ok}` (updates `entry_subject_mappings.primary_parent_id`) |

These additions go alongside the weight-related slots in `HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` Section 6.

## 7. Frontend Changes

### 7.1 Tree editor: SNOMED-style repeated rendering

`src/web/js/tree_editor.js`:

- The `getSubjectHierarchy(examContextId)` API now returns a *forest of paths*, not a single tree. The renderer shows each leaf under every parent it has, marked with a small "alias" chip on non-primary appearances. Same canonical leaf, multiple visual locations.
- A right-click context menu on any leaf offers "Add as child of another parent..." which opens a parent picker and calls `addParent`.
- A "{N} parents" chip on the leaf tooltip lists all parents with an inline "switch primary" affordance.

### 7.2 Breadcrumbs

`src/web/html/entry_form.html`, entry detail view, search results:

- Breadcrumb shows the **primary parent path only** as a single inline trail (per NN/g — stacked breadcrumbs confuse users).
- A small "View {N-1} other contexts" disclosure expands an inline list of alternate paths when the leaf has multiple parents. Clicking switches the page's analytics drill-down context.

### 7.3 Tag-time UX (entry form)

Per the SNOMED/MeSH precedent: do **not** prompt the user to pick a parent at tag time. Tag the canonical leaf and store the navigation context automatically:

- When the entry form's subject typeahead is opened from a specific tree-editor view (e.g., user was browsing Pregnancy Complications), `primary_parent_id` is set to that view's parent.
- When the typeahead is opened from a general "search subjects" affordance, `primary_parent_id` is left NULL ("no specific context").
- Users can override via a "Tag context: {parent_name}" pill below the chosen subject; clicking it offers the leaf's parent list.

### 7.4 Search / typeahead deduplication

`src/web/js/subject_search_widget.js`:

- Search results deduplicate by `subject_nodes.id`. The same leaf appears at most once.
- The displayed path is the primary path. A `(+N paths)` chip is shown when applicable.

### 7.5 Cycle-prevention UI

The "Add parent" dialog disables (with a tooltip) any node that would create a cycle, evaluated on the client via a precomputed descendant set returned with the dialog's payload.

## 8. Analytics Treatment

### 8.1 Default rollup: count-once with parent-context override

For all aggregations (`get_subject_deep_dive`, `get_intersection_entries`, dimension analytics, dashboard counts):

- Base case: `COUNT(DISTINCT entry_id)` over the closure of descendants reached through `subject_edges`. An entry on a multi-parent leaf counts once under each parent's rollup, but only once if the user views a parent that contains the leaf via multiple internal paths.
- Override: when `entry_subject_mappings.primary_parent_id` is set on a row, the entry rolls up *only* through that parent's ancestors, not through the leaf's other parents. This is the primary mechanism by which users can disambiguate "PE in a pregnant patient" from "PE in a post-op patient."

### 8.2 UI disclosure

Every analytics card displaying a multi-parent rollup shows a tooltip:

> *Counted once per entry. The same entry may appear in another parent's rollup if you've shared this subject across parents — sums of sibling rollups will not always equal the total.*

### 8.3 Heatmap and drill-down

Heatmap cells (`heatmap.js`) are keyed by leaf node, not (leaf, parent) pair — one cell per leaf per day. The cell's click target navigates to the entry list for that leaf, filtered by `primary_parent_id` if the user clicked from a specific parent's row in the heatmap.

## 9. Migration Strategy for Existing Data

1. Run schema migrations 1–2 idempotently on app startup. Migration 3 (drop `parent_id`) deferred to a follow-up release.
2. Existing data: every node has at most one parent, so backfill produces exactly one `is_primary=TRUE` edge per child. No ambiguity, no data loss.
3. `entry_subject_mappings.primary_parent_id` defaults to NULL for all existing rows. Behavior for those entries is unchanged (count under all parents — currently their single parent — same as before).
4. Tree editor renders identically until users start adding additional parent edges.
5. Recompute analytics caches (if any are persisted) on first run after migration.

No user-visible behavioral change until users explicitly add a second parent to a node.

## 10. Testing Plan

### 10.1 New test files

- `tests/database/test_subject_edges.py` — Edge CRUD, cycle prevention, primary-parent invariants (exactly zero or one primary per child), backfill correctness.
- `tests/database/test_polyhierarchy_traversal.py` — Recursive CTE rewrites; verify `DISTINCT` aggregation; multi-parent leaf rollups.
- `tests/database/test_primary_parent_context.py` — `entry_subject_mappings.primary_parent_id` semantics; analytics override behavior.
- `tests/database/test_breadcrumb_paths.py` — `get_paths_to_root` returns primary-first; `_build_subject_path` follows primary edges only.

### 10.2 USMLE outline fixture

`tests/fixtures/usmle_step1_outline.txt` (1,327 lines, 99,860 bytes — the full official outline) is retained as a reference fixture. Tests for polyhierarchy correctness construct hierarchies modeled on this outline so they exercise real multi-parent topics. A helper `tests/fixtures/load_usmle_outline.py` parses the file into structured tuples for test setup.

Concrete test scenarios derived from the fixture:
- DVT exists under Cardiovascular and Pregnancy. A mistake on DVT counts once under each parent's rollup, but only once when viewing the union.
- Hypertension exists under seven parents. Effective weight differs per edge. Anchoring HTN's edge under Cardiovascular does not affect HTN's edge under Pregnancy.
- Adding a third parent to DVT must not create a cycle if all three parents are siblings under different system roots.
- Tagging a "32-week pregnant patient with sudden dyspnea" entry against PE with `primary_parent_id` set to Pregnancy: confirm the entry contributes to Pregnancy-chain analytics only, not Respiratory-chain.

### 10.3 Existing tests to update

- `tests/database/test_hierarchy_aggregation.py` — Update fixtures from `parent_id` to `subject_edges`; verify multi-parent rollup counts.
- `tests/database/test_dimension_analytics.py` — Same; verify DISTINCT semantics.
- `tests/database/test_phase7_multi_dimensional.py` — Confirms the cross-dimensional non-goal: nodes still cannot have parents in different dimensions in this initial migration.

### 10.4 Manual UI test scripts

- Build a hierarchy with PE under Respiratory and Pregnancy Complications (modeled on USMLE outline). Tag an entry with PE from the Pregnancy view; confirm `primary_parent_id` is set to Pregnancy. Verify analytics show the entry under Pregnancy's rollup and *not* under Respiratory's when context is set; under both when context is NULL.
- Attempt to add Cardiovascular as a parent of a node already in Cardiovascular's subtree; confirm cycle prevention blocks the action with a clear message.
- Switch the primary parent of a multi-parent leaf; verify breadcrumbs update and search results show the new primary path.

### 10.5 Coverage requirement

Maintain 80%+ threshold (per `pytest.ini`). Estimated 600–800 lines of new test code.

## 11. Open Questions

- **`entry_notes.linked_subject_ids` migration to a junction table**: The same JSON-array-vs-junction-table reasoning that motivates `subject_edges` replacing `subject_nodes.parent_id` applies equally to `entry_notes.linked_subject_ids`, which currently stores note-to-subject relationships as a JSON array. Queries like "find all notes linked to any descendant of Cardiology" parse JSON and run recursive CTEs — exactly the pattern this migration is escaping. Worth a follow-up plan after polyhierarchy lands; not a blocker for the initial migration. (Salvaged from the abandoned graph-migration plan, decision D11.)
- **Cross-dimensional polyhierarchy**: this plan restricts shared parents to the same dimension. Multi-dimensional analytics (Phase 7.4-7.6) currently relies on `subject_nodes.dimension_id`. Allowing cross-dimensional sharing would require moving `dimension_id` to the edge as well, which doubles the migration surface. Recommended deferral to a Phase 8 follow-up.
- **Default `primary_parent_id` policy when context is ambiguous**: three options — count under all parents (most generous; current default), count only under canonical leaf (most conservative), count under the navigated-to parent (context-aware; matches breadcrumb). The plan chooses *navigated-to* when known, NULL otherwise — but the choice could become a configurable setting per user.
- **Breadcrumb display for >2 parents**: a leaf with seven parents (hypertension) cannot show all paths inline. Current plan: primary inline, "View 6 other contexts" disclosure. Alternative: a small subject-detail panel listing all paths in a tree.
- **Bulk operations**: how does deleting a subject node handle its multiple parent edges? Current plan: ON DELETE CASCADE on edges, but the node itself is only deletable when no entries reference it. Worth confirming with user testing.
- **Performance ceiling**: at what node count do recursive CTEs over `subject_edges` start to slow noticeably? Benchmarks at 10K nodes / 30K edges remain sub-millisecond per query in research, but worth measuring on the largest realistic WIMI hierarchy before committing.

## 12. Sequencing with the Weight Rework

This plan and `HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` are co-dependent:

1. **This plan's Migration 1 lands first** — creates `subject_edges` and backfills.
2. **Weight rework's schema migrations land next** — add weight columns to `subject_edges`.
3. **Backend rewrites land in lockstep** — recursive CTE updates here, weight method updates there. They touch overlapping methods in `hierarchy.py`, so a single rollout window is recommended.
4. **UI lands as a unit** — tree editor with multi-parent rendering AND per-edge weight editor. Splitting them produces a confusing intermediate state.
5. **Drop `subject_nodes.parent_id` and legacy weight columns** — follow-up migration after one stable release.

A coordinated branch is recommended for steps 1–4. Step 5 is independently deployable later.

## 13. References

- USMLE Step 1 Content Outline (test fixture): `tests/fixtures/usmle_step1_outline.txt`
- DAG schema patterns: [TeddySmith — SQL Trees](https://teddysmith.io/sql-trees/), [Ackee — Hierarchical models in PostgreSQL](https://www.ackee.agency/blog/hierarchical-models-in-postgresql)
- Closure-table pattern (extended for DAG): [lnagle — Working with Graphs in Postgres](https://lnagle.github.io/extended-closure-table-pattern.html)
- SNOMED CT logical model: [SNOMED International](https://docs.snomed.org/snomed-ct-practical-guides/snomed-ct-starter-guide/5-snomed-ct-logical-model)
- MeSH tree numbers: [NLM MeSH RDF](https://hhs.github.io/meshrdf/tree-numbers)
- OMOP CONCEPT_ANCESTOR aggregation pattern: [OHDSI documentation](https://www.ohdsi.org/web/wiki/doku.php?id=documentation:cdm:concept_ancestor)
- Polyhierarchy UX precedent: [SNOMED Browser](https://medblocks.com/blog/the-snomed-ct-browser-explained), [NN/g — Breadcrumbs guidelines](https://www.nngroup.com/articles/breadcrumbs/)
- Drupal taxonomy multi-parent (cautionary): [Drupal #236404](https://www.drupal.org/node/236404)
- Wikipedia categories (cycle problem): [Cycle detection in PostgreSQL — Mergify](https://articles.mergify.com/cycle-detection-in-postgresql/)
- SQLite recursive CTEs: [SQLite docs — lang_with](https://sqlite.org/lang_with.html)
- Reject fractional attribution: [Bornmann/Mutz on fractional counting bias](https://www.sciencedirect.com/science/article/pii/S1751157718302852)

## 14. File Inventory

**Schema**
- `src/database/schema/user_db_schema_v1_phase1.sql` — `subject_edges` table definition documented; `subject_nodes.parent_id` deprecation note
- `src/database/schema/user_db_schema_v1_phase4.sql` (or wherever entry_subject_mappings lives) — `primary_parent_id` column
- `src/database/domains/schema_migrations.py` — three migrations (create + backfill, primary_parent_id, deferred drop)

**Backend**
- `src/database/domains/_base.py` — recursive CTE helpers rewritten to use `subject_edges`
- `src/database/domains/edges.py` (new) — edge CRUD methods, cycle check
- `src/database/domains/hierarchy.py` — `get_children`/`get_parents`/`get_paths_to_root` updated
- `src/database/domains/analytics_advanced.py` — DISTINCT aggregation in deep-dive queries
- `src/database/domains/dimensions.py` — `_aggregate_hierarchy_counts`, intra-dim polyhierarchy support
- `src/database/domains/entries.py` — entry queries updated to consider `primary_parent_id`
- `src/database/models.py` — `SubjectEdge` class

**Bridge**
- `src/app/bridge_domains/hierarchy.py` (or wherever subject CRUD lives) — six new edge slots
- `src/app/bridge_domains/entries.py` — `setPrimaryParentForEntry`

**Frontend**
- `src/web/js/api/hierarchy.js` — wrapper additions
- `src/web/js/tree_editor.js` — multi-parent rendering, parent picker, primary toggle
- `src/web/js/subject_search_widget.js` — dedup by node id, primary path display, `(+N paths)` chip
- `src/web/js/entry_form.js` — context capture into `primary_parent_id`
- `src/web/js/heatmap.js` — leaf-keyed cells with primary-parent drill-down
- `src/web/html/tree_editor.html` — markup for parent chips and context menu
- `src/web/html/entry_form.html` — tag-context pill markup
- `src/web/css/tree_editor.css` — alias chip, primary-parent indicator styles

**Tests**
- New: `test_subject_edges.py`, `test_polyhierarchy_traversal.py`, `test_primary_parent_context.py`, `test_breadcrumb_paths.py`
- Fixture: `tests/fixtures/usmle_step1_outline.txt`, `tests/fixtures/load_usmle_outline.py`
- Updated: `test_hierarchy_aggregation.py`, `test_dimension_analytics.py`, `test_phase7_multi_dimensional.py`
