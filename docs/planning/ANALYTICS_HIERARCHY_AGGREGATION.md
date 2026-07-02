# Analytics Hierarchy Aggregation Fix

**Status:** Stages 1-3 Complete (Manual Testing Pending)
**Created:** 2026-01-21
**Type:** Bug Fix / Enhancement
**Priority:** High

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Current Behavior](#current-behavior)
3. [Expected Behavior](#expected-behavior)
4. [Tree Analysis](#tree-analysis)
5. [Solution Approach](#solution-approach)
6. [Implementation Plan](#implementation-plan)
7. [Affected Methods](#affected-methods)
8. [Testing Strategy](#testing-strategy)
9. [Performance Considerations](#performance-considerations)

---

## Problem Statement

Analytics methods currently count only entries **directly mapped** to a subject node. They do not aggregate counts from child nodes in the hierarchy.

**Example:** If an entry is tagged to "Valves" (a Subtopic under Heart → Cardiovascular System), it will:
- ✅ Count in "Valves" analytics
- ❌ NOT count in "Heart" analytics
- ❌ NOT count in "Cardiovascular System" analytics

This renders parent-level analytics meaningless, as most entries are tagged to leaf nodes (Subtopics).

---

## Current Behavior

All analytics methods join `entry_subject_mappings` directly to `subject_nodes`:

```sql
-- Example from get_dimension_performance() at user_db.py:7567
SELECT
    sn.id as hierarchy_id,
    sn.name,
    COUNT(DISTINCT esm.question_entry_id) as total_entries,
    ...
FROM subject_nodes sn
LEFT JOIN entry_subject_mappings esm ON esm.subject_node_id = sn.id
LEFT JOIN question_entries qe ON qe.id = esm.question_entry_id
WHERE sn.dimension_id = ?
GROUP BY sn.id, sn.name
```

The join condition `esm.subject_node_id = sn.id` only matches **direct** mappings.

---

## Expected Behavior

When querying analytics for a parent node, counts should include:
1. Entries directly tagged to that node
2. Entries tagged to any descendant node (children, grandchildren, etc.)

**Example with corrected behavior:**
```
Cardiovascular System (total: 45 entries)
├── Heart (total: 30 entries)
│   ├── Valves (direct: 15 entries)
│   └── Chambers (direct: 15 entries)
└── Blood Vessels (total: 15 entries)
    ├── Arteries (direct: 10 entries)
    └── Veins (direct: 5 entries)
```

---

## Tree Analysis

Analysis of the actual `subject_nodes` data (Surgery Shelf Exam, 3099 nodes):

| Metric | Value | Implication |
|--------|-------|-------------|
| **Total nodes** | 3099 | Large but manageable |
| **Max depth** | 3 | Shallow tree (4 levels: 0-3) |
| **Root nodes** | 27 | Systems |
| **Leaf nodes** | 2523 (81%) | Most entries tagged here |
| **Interior nodes** | 576 (19%) | Need aggregation |
| **Avg branching** | 5.3 | Moderate |
| **Largest subtree** | 406 nodes | Nervous System |

### Depth Distribution

| Level | Type | Count |
|-------|------|-------|
| 0 | System | 27 |
| 1 | Subsystem | 214 |
| 2 | Topic | 1154 |
| 3 | Subtopic | 1704 |

### Performance Implication

With max depth of 3, recursive CTEs require only 3 iterations. Even the largest subtree (406 nodes) is a small result set for SQLite.

---

## Solution Approach

**Hybrid approach:** Use the method appropriate for each query pattern.

### Pattern A: Single-Node Queries
**Use:** SQL WITH RECURSIVE CTE

For queries like "get analytics for Cardiovascular System", use a CTE to find all descendants:

```sql
WITH RECURSIVE descendants AS (
    -- Base case: the node itself
    SELECT id FROM subject_nodes WHERE id = :node_id
    UNION ALL
    -- Recursive case: children of current set
    SELECT sn.id
    FROM subject_nodes sn
    JOIN descendants d ON sn.parent_id = d.id
)
SELECT COUNT(DISTINCT esm.question_entry_id) as total_entries
FROM entry_subject_mappings esm
WHERE esm.subject_node_id IN (SELECT id FROM descendants)
```

### Pattern B: Dashboard/Bulk Queries
**Use:** Python post-processing

For queries that return analytics for ALL nodes (dashboards), fetch direct counts then aggregate in Python:

```python
def aggregate_hierarchy_counts(nodes_with_direct_counts):
    """
    Bottom-up aggregation of counts through the hierarchy.

    Args:
        nodes_with_direct_counts: List of dicts with 'id', 'parent_id', 'direct_count'

    Returns:
        Dict mapping node_id -> total_count (including descendants)
    """
    # Build lookup structures
    nodes = {n['id']: n for n in nodes_with_direct_counts}
    children = defaultdict(list)
    for n in nodes_with_direct_counts:
        if n['parent_id']:
            children[n['parent_id']].append(n['id'])

    # Calculate depths for topological ordering
    def get_depth(node_id, memo={}):
        if node_id not in nodes:
            return -1
        if node_id in memo:
            return memo[node_id]
        parent_id = nodes[node_id]['parent_id']
        if parent_id is None:
            memo[node_id] = 0
        else:
            memo[node_id] = get_depth(parent_id, memo) + 1
        return memo[node_id]

    depths = {nid: get_depth(nid) for nid in nodes}

    # Process bottom-up (deepest first)
    totals = {}
    for node_id in sorted(nodes.keys(), key=lambda x: -depths[x]):
        direct = nodes[node_id]['direct_count']
        child_sum = sum(totals.get(cid, 0) for cid in children[node_id])
        totals[node_id] = direct + child_sum

    return totals
```

**Why this works well:**
- Single SQL query fetches all direct counts (fast)
- Python aggregation is O(n) with ~3000 nodes (milliseconds)
- No repeated database round-trips
- Tree is shallow (max depth 3), so algorithm is simple

---

## Implementation Plan

### Stage 1: Create Helper Functions

**File:** `src/database/user_db.py`

#### 1.1 Add CTE helper for single-node descendant queries

```python
def _get_descendant_ids_cte(self, node_id: int) -> str:
    """
    Returns SQL CTE clause for finding all descendants of a node.

    Usage:
        cte = self._get_descendant_ids_cte(node_id)
        query = f"{cte} SELECT ... WHERE subject_node_id IN (SELECT id FROM descendants)"
    """
    return f"""
    WITH RECURSIVE descendants AS (
        SELECT id FROM subject_nodes WHERE id = {node_id}
        UNION ALL
        SELECT sn.id FROM subject_nodes sn
        JOIN descendants d ON sn.parent_id = d.id
        WHERE sn.status = 'active'
    )
    """
```

#### 1.2 Add Python aggregation helper

```python
def _aggregate_hierarchy_counts(self, nodes_with_direct_counts: list) -> dict:
    """
    Aggregates direct counts up through the hierarchy.

    Args:
        nodes_with_direct_counts: List of dicts with keys:
            - 'id': node ID
            - 'parent_id': parent node ID (None for roots)
            - 'direct_count': count of entries directly mapped to this node

    Returns:
        Dict mapping node_id -> total_count (including all descendants)
    """
    from collections import defaultdict

    if not nodes_with_direct_counts:
        return {}

    # Build lookup structures
    nodes = {n['id']: n for n in nodes_with_direct_counts}
    children = defaultdict(list)
    for n in nodes_with_direct_counts:
        if n['parent_id']:
            children[n['parent_id']].append(n['id'])

    # Calculate depths
    depth_memo = {}
    def get_depth(node_id):
        if node_id in depth_memo:
            return depth_memo[node_id]
        if node_id not in nodes:
            return -1
        parent_id = nodes[node_id]['parent_id']
        if parent_id is None:
            depth_memo[node_id] = 0
        else:
            depth_memo[node_id] = get_depth(parent_id) + 1
        return depth_memo[node_id]

    for nid in nodes:
        get_depth(nid)

    # Bottom-up aggregation (deepest nodes first)
    totals = {}
    for node_id in sorted(nodes.keys(), key=lambda x: -depth_memo.get(x, 0)):
        direct = nodes[node_id].get('direct_count', 0)
        child_sum = sum(totals.get(cid, 0) for cid in children[node_id])
        totals[node_id] = direct + child_sum

    return totals
```

---

### Stage 2: Update Analytics Methods

Each method needs to be updated based on its query pattern.

#### 2.1 `get_subject_analytics()` (line ~3849)

**Pattern:** Dashboard - returns all subjects
**Solution:** Python post-processing

**Changes:**
1. Query returns `direct_count` per node
2. Call `_aggregate_hierarchy_counts()`
3. Add `total_count` (aggregated) to results alongside `direct_count`

#### 2.2 `get_dimension_performance()` (line ~7567)

**Pattern:** Dashboard - returns all nodes in a dimension
**Solution:** Python post-processing

**Changes:**
1. Query returns direct counts
2. Aggregate with helper function
3. Return both `direct_entries` and `total_entries`

#### 2.3 `get_cross_dimension_performance()` (line ~7705)

**Pattern:** Pairwise combinations
**Solution:** This is complex - aggregation needs to happen for BOTH dimensions

**Approach:**
1. Get all ancestor relationships for nodes in both dimensions
2. Expand entries to all ancestor combinations
3. Group and count

**Alternative:** Keep as direct-only for cross-dimension (acceptable trade-off for complexity)

#### 2.4 `get_triple_dimension_performance()` (line ~7793)

**Pattern:** Triple combinations
**Solution:** Same complexity as cross-dimension

**Recommendation:** Keep as direct-only or implement if specifically needed

#### 2.5 `get_subject_hierarchy_with_mistakes_by_dimension()` (line ~7630)

**Pattern:** Already aggregates in Python
**Solution:** No changes needed - this is the reference implementation

---

### Stage 3: Update API Responses

Ensure the bridge and frontend handle new fields:

| Field | Meaning |
|-------|---------|
| `direct_count` / `direct_entries` | Entries mapped directly to this node |
| `total_count` / `total_entries` | Entries mapped to this node OR any descendant |

Frontend should display `total_count` by default with option to see `direct_count`.

---

### Stage 4: Testing

See [Testing Strategy](#testing-strategy) section below.

---

## Affected Methods

| Method | Location | Query Pattern | Solution |
|--------|----------|---------------|----------|
| `get_subject_analytics()` | user_db.py:3849 | Dashboard | Python post-process |
| `get_dimension_performance()` | user_db.py:7567 | Dashboard | Python post-process |
| `get_cross_dimension_performance()` | user_db.py:7705 | Pairwise | Keep direct / Complex |
| `get_triple_dimension_performance()` | user_db.py:7793 | Triple | Keep direct / Complex |
| `get_subject_hierarchy_with_mistakes_by_dimension()` | user_db.py:7630 | Hierarchy | Already done ✅ |
| `get_interaction_effects()` | user_db.py:7850+ | Analysis | Evaluate if needed |
| `get_study_recommendations()` | user_db.py:7900+ | Analysis | Evaluate if needed |

---

## Testing Strategy

### Unit Tests

Create `tests/database/test_hierarchy_aggregation.py`:

```python
def test_aggregate_hierarchy_counts_simple():
    """Test basic parent-child aggregation."""
    nodes = [
        {'id': 1, 'parent_id': None, 'direct_count': 5},
        {'id': 2, 'parent_id': 1, 'direct_count': 10},
        {'id': 3, 'parent_id': 1, 'direct_count': 15},
    ]
    result = db._aggregate_hierarchy_counts(nodes)
    assert result[1] == 30  # 5 + 10 + 15
    assert result[2] == 10  # leaf
    assert result[3] == 15  # leaf

def test_aggregate_hierarchy_counts_deep():
    """Test multi-level aggregation."""
    nodes = [
        {'id': 1, 'parent_id': None, 'direct_count': 1},   # root
        {'id': 2, 'parent_id': 1, 'direct_count': 2},      # level 1
        {'id': 3, 'parent_id': 2, 'direct_count': 3},      # level 2
        {'id': 4, 'parent_id': 3, 'direct_count': 4},      # level 3 (leaf)
    ]
    result = db._aggregate_hierarchy_counts(nodes)
    assert result[4] == 4       # leaf
    assert result[3] == 7       # 3 + 4
    assert result[2] == 9       # 2 + 3 + 4
    assert result[1] == 10      # 1 + 2 + 3 + 4

def test_aggregate_hierarchy_counts_wide():
    """Test node with many children."""
    nodes = [
        {'id': 1, 'parent_id': None, 'direct_count': 0},
    ] + [
        {'id': i, 'parent_id': 1, 'direct_count': 1} for i in range(2, 102)
    ]
    result = db._aggregate_hierarchy_counts(nodes)
    assert result[1] == 100  # 0 + 100 children

def test_subject_analytics_includes_descendants():
    """Integration test: subject analytics aggregates children."""
    # Setup: Create hierarchy with entries at leaf level
    # Verify: Parent node shows aggregated count

def test_dimension_performance_includes_descendants():
    """Integration test: dimension performance aggregates children."""
    # Setup: Create dimension hierarchy with entries at various levels
    # Verify: Parent nodes show aggregated counts
```

### Manual Testing

1. Create test entries tagged to Subtopics only
2. View analytics for parent System
3. Verify count includes all descendant entries
4. Compare with `get_subject_hierarchy_with_mistakes_by_dimension()` sunburst (already aggregates)

---

## Performance Considerations

### Benchmarks to Verify

Before deployment, benchmark with real data:

```python
import time

# Test dashboard query performance
start = time.time()
result = db.get_dimension_performance(exam_context, dimension_id)
print(f"Dashboard query: {time.time() - start:.3f}s")

# Should be < 500ms for 3000 nodes
```

### Expected Performance

| Operation | Expected Time |
|-----------|---------------|
| Single CTE query (406 node subtree) | < 20ms |
| Dashboard with Python aggregation (3000 nodes) | < 200ms |
| Full analytics page load | < 500ms |

### If Performance Issues Arise

Fallback options (in order of preference):

1. **Add index on parent_id** (if not exists):
   ```sql
   CREATE INDEX IF NOT EXISTS idx_subject_nodes_parent
   ON subject_nodes(parent_id) WHERE status = 'active';
   ```

2. **Cache aggregated results** with invalidation on entry changes

3. **Denormalize ancestor mappings** (last resort - adds complexity)

---

## Implementation Checklist

- [x] Stage 1: Helper Functions (Completed 2026-01-21)
  - [x] Add `_build_descendant_cte()` method
  - [x] Add `_aggregate_hierarchy_counts()` method
  - [x] Unit tests for helper functions (17 tests)

- [x] Stage 2: Update Analytics Methods (Completed 2026-01-21)
  - [x] Update `get_subject_analytics()` - Added `total_mistake_count` field, aggregates children
  - [x] Update `get_dimension_performance()` - Added `include_children` param, returns `direct_entries` and `total_entries`
  - [x] Evaluate `get_cross_dimension_performance()` - **Decision: Keep direct-only** (complexity too high)
  - [x] Evaluate `get_triple_dimension_performance()` - **Decision: Keep direct-only** (complexity too high)
  - [x] Update `get_intersection_entries()` - Added `include_children` param with CTE support
  - [x] Unit tests for updated methods (10 additional tests, 27 total)

- [x] Stage 3: API Updates (Completed 2026-01-21)
  - [x] Update bridge methods - Added `include_children` param to `getDimensionPerformance` and `getIntersectionEntries`
  - [x] Update `api.js` - Updated wrappers to pass `includeChildren` parameter
  - [x] Verify frontend uses aggregated fields - `dimension_analytics.js` uses `total_entries`, sunburst already aggregates

- [x] Stage 4: Testing (Partial - unit/integration complete)
  - [x] Unit tests for aggregation logic
  - [x] Integration tests for analytics methods
  - [ ] Manual testing with real data
  - [ ] Performance benchmarks

- [x] Documentation
  - [x] Update method docstrings (all affected methods updated)
  - [ ] Update API documentation if needed

---

## Decisions Made

1. **Cross-dimension aggregation:** **Decided: Keep direct-only.**
   - `get_cross_dimension_performance()` and `get_triple_dimension_performance()` only count direct mappings
   - Reasoning: Aggregating both dimensions simultaneously increases complexity significantly and may obscure specific problem areas
   - Docstrings updated to document this behavior

2. **Drill-down with hierarchy:** `get_intersection_entries()` supports `include_children=True` (default) to find entries in descendant nodes when drilling down from a heatmap cell.

## Open Questions

1. **UI display:** Should the UI show both `direct_count` and `total_count`, or just `total_count`? Consider:
   - Default to `total_count` with tooltip showing direct
   - Toggle between views
   - Always show both

2. **Backward compatibility:** The updated methods add new fields but retain existing ones. `get_subject_analytics()` now returns both `mistake_count` (direct) and `total_mistake_count` (aggregated). Frontend may need updates to use the new fields.

---

## References

- Current analytics implementation: `src/database/user_db.py`
- Working aggregation example: `get_subject_hierarchy_with_mistakes_by_dimension()` at line ~7630
- Subject nodes schema: `src/database/schema/user_db_schema_v1_phase1.sql`
- Entry mappings schema: `src/database/schema/user_db_schema_v1_phase4.sql`
- Tree analysis data: `examples/subject_nodes.csv`
