# Hybrid Weight System Implementation Status

## Implementation Date: January 8, 2026

---

## Completed Components

### 1. Schema Changes ✅

**File:** `src/database/schema/user_db_schema_v1_phase1.sql`

Added to `subject_nodes` table:
- `relative_weight REAL` - Percentage of parent's weight (0-100)
- `weight_source VARCHAR(50)` - 'official', 'derived', 'user_estimate', 'user_defined'
- `weight_locked BOOLEAN` - Whether weight can be edited
- Index on `(exam_context, weight_source)` for efficient queries

### 2. Migration Script ✅

**File:** `src/database/migrations/migration_hybrid_weights.sql`

- ALTER TABLE statements for adding columns to existing databases
- Data migration for existing weights (set to 'user_defined')
- Safe for re-running (idempotent)

### 3. Model Updates ✅

**File:** `src/database/models.py`

`SubjectNode` dataclass updated with:
- `relative_weight: Optional[float]` field
- `weight_source: str` field (default: 'user_defined')
- `weight_locked: bool` field (default: False)
- Properties:
  - `has_absolute_weight` - True if has exam_weight_low
  - `has_weight_range` - True if low != high
  - `has_relative_weight` - True if relative_weight is set
  - `weight_midpoint` - Average of low/high
  - `weight_range_width` - Difference between high and low
  - `weight_display` - Formatted string for UI
  - `is_official_weight` - True if source is 'official'
  - `can_edit_weight` - True if not locked
- Method:
  - `get_effective_weight(parent_midpoint)` - Calculate absolute from relative

### 4. Database Methods ✅

**File:** `src/database/user_db.py`

New methods added:

#### Import Official Weights
```python
def import_official_weights(
    self,
    exam_context_id: int,
    weights_data: List[Dict[str, Any]],
    source_name: str,
    source_url: Optional[str] = None
) -> Dict[str, Any]
```
- Imports official weight ranges from authoritative sources
- Creates/updates subject nodes with locked weights
- Returns import results with counts and errors

#### Update Relative Weight with Rebalancing
```python
def update_subject_relative_weight(
    self,
    node_id: int,
    relative_weight: float,
    reason: Optional[str] = None
) -> Dict[str, Any]
```
- Updates relative weight for child subjects
- Automatically rebalances unlocked siblings proportionally
- Respects locked weights during rebalancing

#### Get Subjects with Effective Weights
```python
def get_subjects_with_effective_weights(
    self,
    exam_context_id: int,
    include_children: bool = True
) -> List[Dict[str, Any]]
```
- Recursively calculates effective weights
- For children: effective = parent_midpoint × (relative_weight / 100)
- Includes confidence levels based on weight source

#### Get Weight Configuration
```python
def get_weight_config_for_exam(
    self,
    exam_context_id: int
) -> Dict[str, Any]
```
- Returns weight mode ('official_ranges', 'official_fixed', 'user_defined')
- Counts official vs user-defined weights
- Calculates if weights sum to 100%

#### Create Subject with Full Weight Config
```python
def create_subject_node_with_weight(
    self,
    exam_context: str,
    name: str,
    level_type: str,
    parent_id: Optional[int] = None,
    exam_weight_low: Optional[float] = None,
    exam_weight_high: Optional[float] = None,
    relative_weight: Optional[float] = None,
    weight_source: str = 'user_defined',
    weight_locked: bool = False,
    ...
) -> SubjectNode
```
- Enhanced version of create_subject_node
- Supports all hybrid weight fields

#### Migration Helper
```python
def ensure_hybrid_weight_columns(self) -> bool
```
- Adds missing columns for existing databases
- Sets defaults for existing weights
- Safe to run multiple times

### 5. Unit Tests ✅ **ALL PASSING**

**File:** `tests/database/test_user_db_hybrid_weights.py`

**Test Results:** 19/19 passed (100%)

Test coverage includes:
- Import official weights (new and update) ✅
- Import with parent relationships ✅
- Error handling for missing parents ✅
- Relative weight updates ✅
- Proportional sibling rebalancing ✅
- Locked weight protection ✅
- Effective weight calculations ✅
- Confidence level assignment ✅
- Weight configuration retrieval ✅
- Subject creation with weights ✅
- Migration support ✅
- Full USMLE-style integration test ✅

**Schema Fix Applied:** `_ensure_phase1_schema()` now properly executes schema SQL with `executescript()` and `commit()`.

### 6. Bridge Methods ✅ **IMPLEMENTED**

**File:** `src/app/bridge.py`

New PyQt bridge methods added:

#### `importOfficialWeights(exam_context_id, weights_json, source_name, source_url)`
- Imports official weight ranges from JSON
- Returns import results with subjects converted to dicts
- Handles ValueError for invalid JSON input

#### `updateRelativeWeight(node_id, relative_weight, reason)`
- Updates relative weight with sibling rebalancing
- Returns affected siblings with old/new weights
- Error handling for `SubjectNodeError` and `WeightValidationError`
- Emits `weightUpdated` signal for UI updates

#### `getSubjectsWithEffectiveWeights(exam_context_id, include_children)`
- Returns subjects with calculated effective weights
- Includes confidence levels and locked status
- Recursive children if requested

#### `getWeightConfig(exam_context_id)`
- Returns weight mode and configuration
- Includes official/user-defined counts
- Shows if weights sum to 100%

#### `createSubjectNodeWithWeight(node_data_json)`
- Creates subject with full weight configuration
- Supports all hybrid weight fields
- Looks up exam_name from exam_context_id

#### `_subject_node_to_dict(node)` Helper
- Converts SubjectNode to JSON-serializable dict
- Includes all weight-related properties

### 7. Frontend Components ✅ **IMPLEMENTED**

**Files Updated:**
- `src/web/js/api.js` - Added hybrid weight API methods
- `src/web/js/weight_editor.js` - Enhanced weight editor with hybrid support
- `src/web/js/tree_editor.js` - Updated tree display with weight indicators
- `src/web/html/tree_editor.html` - Added import weights button and config badge
- `src/web/css/weight.css` - Hybrid weight styling
- `src/web/css/tree.css` - Tree node weight indicators

#### API Methods Added (`api.js`)
```javascript
importOfficialWeights({ examContextId, weightsData, sourceName, sourceUrl })
updateRelativeWeight({ nodeId, relativeWeight, reason })
getSubjectsWithEffectiveWeights({ examContextId, includeChildren })
getWeightConfig(examContextId)
createSubjectNodeWithWeight(nodeData)
```

#### Weight Editor Enhancements (`weight_editor.js`)
- **Weight Status Header**: Shows weight type (Absolute/Relative), confidence badge (High/Medium/Low), lock status
- **Official Range Display**: Shows "20%–25%" for official weight ranges with source attribution
- **Effective Weight Calculation**: Real-time calculation of effective weight from relative weight
- **Lock Protection**: Disabled editing for locked weights with explanation message
- **Confidence Indicators**: Color-coded badges based on weight source
- **Locked Sibling Handling**: Excludes locked siblings from rebalancing preview

#### Tree Editor Enhancements (`tree_editor.js`)
- **Import Weights Modal**: Full modal for importing official weight JSON
  - Source name and URL input
  - JSON validation with live preview
  - Import progress and results display
- **Weight Config Badge**: Toolbar badge showing official/user-defined status
- **Node Weight Display**: Shows ranges (20–25%), lock icons, confidence colors
- **Tooltip Enhancement**: Detailed weight info on hover

#### UI Components
- **Import Weights Button**: Purple gradient button in toolbar
- **Weight Config Badge**: Shows "📋 NBME Outline..." or "⚙️ User Defined"
- **Confidence Indicators**: Border colors (green=high, yellow=medium, gray=low)
- **Lock Icons**: 🔒 displayed for locked weights
- **Range Display**: "20–25%" format for weight ranges

#### CSS Updates
- Weight status header styling
- Confidence badge colors
- Weight range display styling
- Effective weight display
- Locked state styling
- Import weights modal styling

---

## Next Steps

### 1. Analytics Integration (Not Started)
- Use effective weights in quadrant analysis
- Range-aware categorization
- Confidence-weighted recommendations

---

## Usage Examples

### Importing USMLE Weights

```python
exam_config = user_db.get_exam_context_by_name("USMLE Step 1")

weights = [
    {'name': 'Gastrointestinal System', 'level_type': 'System', 'weight_low': 20, 'weight_high': 25},
    {'name': 'Cardiovascular System', 'level_type': 'System', 'weight_low': 10, 'weight_high': 15},
    {'name': 'Respiratory System', 'level_type': 'System', 'weight_low': 12, 'weight_high': 16},
]

result = user_db.import_official_weights(
    exam_context_id=exam_config.id,
    weights_data=weights,
    source_name="NBME Content Outline 2024"
)
# result: {'imported': 3, 'updated': 0, 'errors': [], 'subjects': [...]}
```

### Adding Child Relative Weights

```python
# Get the GI system
gi = next(s for s in user_db.get_subject_hierarchy("USMLE Step 1") 
          if s.name == "Gastrointestinal System")

# Add child topics with relative weights
user_db.create_subject_node_with_weight(
    exam_context="USMLE Step 1",
    name="Esophagus",
    level_type="Topic",
    parent_id=gi.id,
    relative_weight=15,  # 15% of GI's weight
    weight_source='user_estimate'
)
```

### Getting Effective Weights for Analysis

```python
subjects = user_db.get_subjects_with_effective_weights(exam_config.id)

for subject in subjects:
    print(f"{subject['name']}:")
    print(f"  Effective: {subject['weight']['effective']}%")
    print(f"  Range: {subject['weight']['effective_low']}-{subject['weight']['effective_high']}%")
    print(f"  Confidence: {subject['weight']['confidence']}")
```

---

## Architecture Notes

### Weight Calculation Flow

```
Official Weight Import
        │
        ▼
┌─────────────────────┐
│  Top-Level Subject  │
│  exam_weight_low=20 │
│  exam_weight_high=25│
│  source='official'  │
│  locked=True        │
└─────────────────────┘
        │
        │ Parent midpoint = 22.5%
        │
        ▼
┌─────────────────────┐
│   Child Subject     │
│  relative_weight=15 │
│  source='user_est'  │
│  locked=False       │
│                     │
│  effective=3.375%   │
│  (22.5 × 15/100)    │
└─────────────────────┘
```

### Sibling Rebalancing Algorithm

When updating a relative weight:
1. Calculate weight change (new - old)
2. Get unlocked siblings
3. Calculate proportional share for each sibling
4. Apply inverse change (if node goes up, siblings go down)
5. Ensure total remains 100%

```python
# Example: Esophagus 15% → 25%
# Siblings: Stomach=25%, Small Intestine=35%, Colon=25%
# Total siblings = 85%, Change = +10%

# Stomach: 25/85 = 29.4% of siblings → loses 2.94%
# Small Intestine: 35/85 = 41.2% → loses 4.12%
# Colon: 25/85 = 29.4% → loses 2.94%

# New: Stomach=22.06%, SI=30.88%, Colon=22.06%
# Total = 25 + 22.06 + 30.88 + 22.06 = 100% ✓
```
