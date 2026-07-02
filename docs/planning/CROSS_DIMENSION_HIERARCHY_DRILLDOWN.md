# Cross-Dimension Hierarchy Drill-Down UI

**Status:** ✅ Implemented
**Created:** 2026-01-21
**Implemented:** 2026-01-21
**Type:** UX Enhancement
**Priority:** High

---

## Problem Statement

The cross-dimension analysis heatmap currently displays ALL nodes from each selected dimension. For dimensions like "Systems" with 3000+ nodes, this creates an unusable UI - the heatmap becomes too large and cells too small to interpret.

**Current Behavior:**
- User selects Dimension A (e.g., "Systems") and Dimension B (e.g., "Site of Care")
- Heatmap shows ALL 3000+ System nodes × 3 Site of Care nodes
- Result: Unreadable, overwhelming visualization

**Desired Behavior:**
- User selects dimension AND hierarchy level (System → Subsystem → Topic → Subtopic)
- User can optionally filter to a specific parent node's children
- Heatmap shows manageable subset (e.g., 27 root Systems × 3 Sites of Care)
- User can drill down to see more detail (e.g., Cardiovascular's 19 Subsystems × 3 Sites)

---

## Proposed UX Flow

### Step 1: Dimension Selection with Level Picker

For each dimension dropdown, add a secondary "Level" selector:

```
Dimension A: [Systems ▼]  Level: [System ▼]
Dimension B: [Site of Care ▼]  Level: [System ▼]
```

Level options are the hierarchy levels defined for that exam:
- System (root level, ~27 nodes)
- Subsystem (~200 nodes)
- Topic (~1100 nodes)
- Subtopic (~1700 nodes)

### Step 2: Optional Parent Filter (Drill-Down)

When user wants to drill down into a specific node:

```
Dimension A: [Systems ▼]  Level: [Subsystem ▼]  Parent: [Cardiovascular ▼]
```

This would show only Cardiovascular's 19 Subsystems in the heatmap.

### Step 3: Click-to-Drill Interaction

Clicking a heatmap cell or row/column header could trigger drill-down:
- Click "Cardiovascular" row header → Drill down to show its Subsystems
- Click "Emergency Room" column header → Keep that column, drill down rows
- Click cell → Show entries at that intersection (existing behavior)

---

## Implementation Plan

### Stage 1: Backend - Add Hierarchy Level Filter

**File:** `src/database/user_db.py`

Update `get_cross_dimension_performance()` to accept optional parameters:

```python
def get_cross_dimension_performance(
    self,
    exam_context_id: int,
    dimension_a_id: int,
    dimension_b_id: int,
    min_entries: int = 1,
    level_type_a: str = None,      # NEW: Filter by hierarchy level
    level_type_b: str = None,      # NEW: Filter by hierarchy level
    parent_node_a_id: int = None,  # NEW: Filter to children of this node
    parent_node_b_id: int = None   # NEW: Filter to children of this node
) -> Dict[str, Any]:
```

**Query Changes:**
```sql
-- Add to WHERE clause for dimension A nodes:
AND (? IS NULL OR sn_a.level_type = ?)
AND (? IS NULL OR sn_a.parent_id = ?)

-- Same for dimension B nodes
```

**New Helper Method:**
```python
def get_hierarchy_levels_for_dimension(self, exam_context_id: int, dimension_id: int) -> List[str]:
    """Return distinct level_types used in this dimension, ordered by depth."""
    # Returns: ['System', 'Subsystem', 'Topic', 'Subtopic']
```

### Stage 2: Bridge Updates

**File:** `src/app/bridge.py`

Update `getCrossDimensionPerformance` to accept new parameters:

```python
@pyqtSlot(str, result=str)
def getCrossDimensionPerformance(self, params_json: str) -> str:
    # Add new params:
    level_type_a = params.get('level_type_a')
    level_type_b = params.get('level_type_b')
    parent_node_a_id = params.get('parent_node_a_id')
    parent_node_b_id = params.get('parent_node_b_id')
```

**New Bridge Method:**
```python
@pyqtSlot(str, result=str)
def getHierarchyLevelsForDimension(self, params_json: str) -> str:
    """Get available hierarchy levels for a dimension."""
```

### Stage 3: API Updates

**File:** `src/web/js/api.js`

Update `getCrossDimensionPerformance`:

```javascript
async getCrossDimensionPerformance({
    examContextId,
    dimensionAId,
    dimensionBId,
    minEntries = 1,
    levelTypeA = null,      // NEW
    levelTypeB = null,      // NEW
    parentNodeAId = null,   // NEW
    parentNodeBId = null    // NEW
} = {}) {
```

Add new method:
```javascript
async getHierarchyLevelsForDimension({ examContextId, dimensionId } = {}) {
    // Returns ['System', 'Subsystem', 'Topic', 'Subtopic']
}
```

### Stage 4: Frontend UI Updates

**File:** `src/web/js/analytics_dashboard.js`

#### 4.1 Add Level Selectors

After dimension dropdowns, add level dropdowns:

```html
<div class="dimension-selector">
    <select id="dimensionASelect">...</select>
    <select id="levelASelect">
        <option value="">All Levels</option>
        <!-- Populated dynamically -->
    </select>
    <select id="parentASelect" style="display:none">
        <!-- Shows when drilling down -->
    </select>
</div>
```

#### 4.2 Update Heatmap Loading Logic

```javascript
async loadCrossDimensionHeatmap() {
    const dimensionAId = this.getDimensionAId();
    const dimensionBId = this.getDimensionBId();
    const levelTypeA = document.getElementById('levelASelect').value || null;
    const levelTypeB = document.getElementById('levelBSelect').value || null;
    const parentNodeAId = this.selectedParentA || null;
    const parentNodeBId = this.selectedParentB || null;

    const data = await api.getCrossDimensionPerformance({
        examContextId: this.currentExamFilter,
        dimensionAId,
        dimensionBId,
        levelTypeA,
        levelTypeB,
        parentNodeAId,
        parentNodeBId
    });

    this.dimensionHeatmap.render(data);
}
```

#### 4.3 Add Drill-Down Interaction

```javascript
// In heatmap click handler
onRowHeaderClick(nodeId, nodeName) {
    // Set as parent filter and refresh
    this.selectedParentA = nodeId;
    this.currentDrillPathA.push({ id: nodeId, name: nodeName });

    // Move to next level
    const currentLevel = document.getElementById('levelASelect').value;
    const nextLevel = this.getNextLevel(currentLevel);
    document.getElementById('levelASelect').value = nextLevel;

    this.loadCrossDimensionHeatmap();
    this.updateBreadcrumb();
}

// Breadcrumb for navigation back up
updateBreadcrumb() {
    // Show: Systems > Cardiovascular > [current view]
    // Clicking "Systems" resets to root level
}
```

**File:** `src/web/js/dimension_heatmap.js`

Add click handlers for row/column headers:

```javascript
// When rendering headers, add click handlers
svg.selectAll('.row-label')
    .on('click', (event, d) => {
        if (this.options.onRowHeaderClick) {
            this.options.onRowHeaderClick(d.id, d.name);
        }
    });
```

### Stage 5: CSS Styling

**File:** `src/web/css/analytics.css`

```css
.dimension-selector {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
}

.level-select {
    min-width: 120px;
}

.parent-select {
    min-width: 150px;
}

.drill-breadcrumb {
    font-size: 12px;
    color: var(--text-secondary);
    margin-bottom: 8px;
}

.drill-breadcrumb a {
    cursor: pointer;
    color: var(--primary);
}

.drill-breadcrumb a:hover {
    text-decoration: underline;
}

/* Clickable headers */
.heatmap .row-label,
.heatmap .col-label {
    cursor: pointer;
}

.heatmap .row-label:hover,
.heatmap .col-label:hover {
    fill: var(--primary);
    font-weight: bold;
}
```

---

## Data Structure Examples

### Hierarchy Levels Response
```json
{
    "dimension_id": 6,
    "dimension_name": "Systems",
    "levels": [
        {"level_type": "System", "count": 27, "depth": 0},
        {"level_type": "Subsystem", "count": 214, "depth": 1},
        {"level_type": "Topic", "count": 1154, "depth": 2},
        {"level_type": "Subtopic", "count": 1704, "depth": 3}
    ]
}
```

### Cross-Dimension with Level Filter
Request:
```json
{
    "exam_context_id": 5,
    "dimension_a_id": 6,
    "dimension_b_id": 4,
    "level_type_a": "System",
    "level_type_b": null,
    "parent_node_a_id": null
}
```

Response includes only System-level nodes for dimension A (27 instead of 3090).

### Cross-Dimension with Parent Filter (Drill-Down)
Request:
```json
{
    "exam_context_id": 5,
    "dimension_a_id": 6,
    "dimension_b_id": 4,
    "level_type_a": "Subsystem",
    "parent_node_a_id": 1314
}
```

Response includes only Cardiovascular's Subsystems (19 nodes).

---

## UI Wireframe

```
┌─────────────────────────────────────────────────────────────────┐
│ Cross-Dimension Analysis                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Dimension A: [Systems ▼]  Level: [Subsystem ▼]                │
│  Showing: Cardiovascular > Subsystems                          │
│  [← Back to Systems]                                           │
│                                                                 │
│  Dimension B: [Site of Care ▼]  Level: [All ▼]                 │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│              │ Emergency │ In-patient │ Operating │             │
│  ────────────┼───────────┼────────────┼───────────┤             │
│  Dysrhythmias│     1     │     0      │     0     │  ← click   │
│  Heart Fail  │     1     │     0      │     0     │    to      │
│  Valvular HD │     0     │     0      │     3     │    drill   │
│  Infectious  │     1     │     1      │     0     │    down    │
│  ...         │           │            │           │             │
│                                                                 │
│  [Click row header to drill down to Topics]                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Testing Checklist

- [ ] Level selector shows correct levels for each dimension
- [ ] Selecting a level filters the heatmap correctly
- [ ] Parent filter shows only children of selected node
- [ ] Drill-down via header click works
- [ ] Breadcrumb navigation allows going back up
- [ ] Entry counts aggregate correctly at each level
- [ ] Cell click still shows intersection entries
- [ ] Performance is acceptable with large hierarchies
- [ ] Empty states handled (no data at selected level)

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/database/user_db.py` | Add level/parent filters to `get_cross_dimension_performance()`, add `get_hierarchy_levels_for_dimension()` |
| `src/app/bridge.py` | Update bridge method, add new method |
| `src/web/js/api.js` | Update API method, add new method |
| `src/web/js/analytics_dashboard.js` | Add level selectors, drill-down logic, breadcrumb |
| `src/web/js/dimension_heatmap.js` | Add header click handlers |
| `src/web/css/analytics.css` | Style new UI elements |
| `src/web/html/analytics_dashboard.html` | Add level selector elements |

---

## Considerations

1. **Default Behavior:** Start at root level (System) for large hierarchies, show all levels for small ones
2. **Aggregation:** Counts should aggregate children (already implemented in previous session)
3. **Performance:** Level filter should happen in SQL, not post-processing
4. **Mobile:** Ensure selectors work on smaller screens
5. **State Persistence:** Consider saving drill-down state in URL params for sharing

---

## Related Work

- Hierarchy aggregation was implemented in the previous session (see `HANDOFF_2026-01-21_ANALYTICS_HIERARCHY_AGGREGATION.md`)
- `get_dimension_performance()` already supports hierarchy aggregation
- The `_aggregate_hierarchy_counts()` helper can be reused

---

**Document Created By:** Claude Code Agent
**Purpose:** Instructions for implementing cross-dimension hierarchy drill-down UI
