# Phase 2: JSON Structure Examples & Usage Guide

**Document Version:** 1.0  
**Last Updated:** November 8, 2025  
**Purpose:** Comprehensive examples of JSON structures used in Phase 2 tables

---

## Table of Contents

1. [exam_contexts JSON Fields](#exam_contexts-json-fields)
2. [subject_node_weights JSON Fields](#subject_node_weights-json-fields)
3. [Complete Usage Examples](#complete-usage-examples)
4. [Weight Calculation Workflows](#weight-calculation-workflows)
5. [Validation Rules](#validation-rules)

---

## exam_contexts JSON Fields

### 1. default_hierarchy_levels

**Purpose**: Define the hierarchy level names for an exam context

**Structure:**
```json
["System", "Subsystem", "Topic", "Subtopic", "Child"]
```

**Default Levels (First 5):**
1. System (Level 1)
2. Subsystem (Level 2)
3. Topic (Level 3)
4. Subtopic (Level 4)
5. Child (Level 5)

**Custom Levels (Beyond 5):**
- Stored as "Level 6", "Level 7", etc. in `hierarchy_level_definitions` table
- Frontend displays as "Daughter of [Parent Name]"

**Example with Custom Levels:**
```json
["System", "Subsystem", "Topic", "Subtopic", "Child"]
```
*Note: Custom levels beyond this are defined in hierarchy_level_definitions table*

---

### 2. weight_validation_rules

**Purpose**: Configure how weights are calculated, validated, and displayed for this exam

**Full Structure with Defaults:**
```json
{
    "autonomous_weight_balancing": true,
    "allow_absolute_weight_editing": false,
    "precision_decimal_places": 1,
    "require_exact_100": true,
    "balancing_algorithm": "proportional"
}
```

#### Field Descriptions:

**autonomous_weight_balancing** (boolean, default: `true`)
- **When `true`**: Editing one child's weight automatically adjusts siblings to maintain 100%
- **When `false`**: User must manually balance weights; system only validates
- **UI Impact**: 
  - `true` → Show only relative percentages
  - `false` → Show both relative AND absolute percentages

**allow_absolute_weight_editing** (boolean, default: `false`)
- **When `true`**: User can directly edit absolute weights (% of root); system recalculates relative weights
- **When `false`**: Only relative weights (% of parent) are editable
- **Use Case**: Advanced users who want to specify exact exam importance percentages

**precision_decimal_places** (integer, default: `1`)
- **Options**: 
  - `0` = whole percentages (40%, 60%)
  - `1` = one decimal (40.5%, 59.5%)
  - `2` = two decimals (40.25%, 59.75%)
- **Impact**: Affects rounding and display precision

**require_exact_100** (boolean, default: `true`)
- **When `true`**: Children must sum to exactly 100.0% (within float precision)
- **When `false`**: Allow small rounding differences (e.g., 99.9% or 100.1% acceptable)

**balancing_algorithm** (string, default: `"proportional"`)
- **Options:**
  - `"proportional"`: Distribute weight changes based on current sibling proportions (prevents zeros)
  - `"even"`: Distribute weight changes evenly across all siblings (simpler but can create zeros)

---

### Example Configurations

**Configuration 1: Strict Mode (Default)**
```json
{
    "autonomous_weight_balancing": true,
    "allow_absolute_weight_editing": false,
    "precision_decimal_places": 1,
    "require_exact_100": true,
    "balancing_algorithm": "proportional"
}
```
*Use Case: Standard user, automatic weight management, high precision*

---

**Configuration 2: Manual Control Mode**
```json
{
    "autonomous_weight_balancing": false,
    "allow_absolute_weight_editing": true,
    "precision_decimal_places": 2,
    "require_exact_100": true,
    "balancing_algorithm": "proportional"
}
```
*Use Case: Advanced user who wants full manual control, sees both relative and absolute weights*

---

**Configuration 3: Relaxed Mode**
```json
{
    "autonomous_weight_balancing": true,
    "allow_absolute_weight_editing": false,
    "precision_decimal_places": 0,
    "require_exact_100": false,
    "balancing_algorithm": "even"
}
```
*Use Case: User wants simple whole number percentages, tolerates rounding differences*

---

**Configuration 4: Power User Mode**
```json
{
    "autonomous_weight_balancing": false,
    "allow_absolute_weight_editing": true,
    "precision_decimal_places": 2,
    "require_exact_100": false,
    "balancing_algorithm": "even"
}
```
*Use Case: Expert user, maximum flexibility, manual validation*

---

## subject_node_weights JSON Fields

### 1. affected_siblings

**Purpose**: Track which sibling nodes had their weights automatically adjusted

**Structure:**
```json
[123, 456, 789]
```

**Example:**
```json
{
    "id": 501,
    "subject_node_id": 101,
    "weight_value": 50.0,
    "edited_date": "2025-11-08",
    "edited_by": "user",
    "edited_reason": "User increased priority",
    "previous_weight": 33.3,
    "change_type": "manual_edit",
    "affected_siblings": [102, 103]
}
```
*Siblings 102 and 103 were auto-adjusted from 33.3% to 25.0% each*

---

## Complete Usage Examples

### Example 1: Creating a New Exam Context

**Step 1: Insert into exam_contexts**
```sql
INSERT INTO exam_contexts (
    user_id, 
    exam_name, 
    exam_description, 
    exam_date,
    default_hierarchy_levels,
    weight_validation_rules
) VALUES (
    1,
    'USMLE Step 1',
    'United States Medical Licensing Examination Step 1',
    '2026-06-15',
    '["System", "Subsystem", "Topic", "Subtopic", "Child"]',
    '{
        "autonomous_weight_balancing": true,
        "allow_absolute_weight_editing": false,
        "precision_decimal_places": 1,
        "require_exact_100": true,
        "balancing_algorithm": "proportional"
    }'
);
```

**Step 2: Create Default Hierarchy Level Definitions**
```sql
-- Level 1: System
INSERT INTO hierarchy_level_definitions (
    exam_context_id, level_name, level_order, is_required, is_custom_level
) VALUES (1, 'System', 1, TRUE, FALSE);

-- Level 2: Subsystem
INSERT INTO hierarchy_level_definitions (
    exam_context_id, level_name, level_order, is_required, is_custom_level
) VALUES (1, 'Subsystem', 2, TRUE, FALSE);

-- Level 3: Topic
INSERT INTO hierarchy_level_definitions (
    exam_context_id, level_name, level_order, is_required, is_custom_level
) VALUES (1, 'Topic', 3, TRUE, FALSE);

-- Level 4: Subtopic
INSERT INTO hierarchy_level_definitions (
    exam_context_id, level_name, level_order, is_required, is_custom_level
) VALUES (1, 'Subtopic', 4, FALSE, FALSE);

-- Level 5: Child
INSERT INTO hierarchy_level_definitions (
    exam_context_id, level_name, level_order, is_required, is_custom_level
) VALUES (1, 'Child', 5, FALSE, FALSE);
```

---

### Example 2: Creating Subject Hierarchy with Auto-Weight Distribution

**Scenario**: Create a root with 2 systems, each system will get 50%

**Step 1: Create Root Node (implicit 100%)**
```sql
INSERT INTO subject_nodes (
    exam_context, name, parent_id, level_type, exam_weight_low, exam_weight_high
) VALUES (
    'USMLE Step 1', 'Root', NULL, 'Root', 100.0, 100.0
);
-- Returns: id = 1
```

**Step 2: Create System A (gets 50%)**
```sql
INSERT INTO subject_nodes (
    exam_context, name, parent_id, level_type, exam_weight_low, exam_weight_high
) VALUES (
    'USMLE Step 1', 'Cardiovascular System', 1, 'System', 50.0, 50.0
);
-- Returns: id = 2
```

**Step 3: Record Initial Weight for System A**
```sql
INSERT INTO subject_node_weights (
    subject_node_id, weight_value, edited_by, edited_reason, 
    previous_weight, change_type, affected_siblings
) VALUES (
    2, 50.0, 'system', 
    'Initial even distribution among 2 children',
    NULL, 'initial', '[3]'
);
```

**Step 4: Create System B (gets 50%)**
```sql
INSERT INTO subject_nodes (
    exam_context, name, parent_id, level_type, exam_weight_low, exam_weight_high
) VALUES (
    'USMLE Step 1', 'Respiratory System', 1, 'System', 50.0, 50.0
);
-- Returns: id = 3
```

**Step 5: Record Initial Weight for System B**
```sql
INSERT INTO subject_node_weights (
    subject_node_id, weight_value, edited_by, edited_reason,
    previous_weight, change_type, affected_siblings
) VALUES (
    3, 50.0, 'system',
    'Initial even distribution among 2 children',
    NULL, 'initial', '[2]'
);
```

---

### Example 3: User Edits Weight with Proportional Balancing

**Scenario**: User changes Cardiovascular System from 50% to 60%

**Current State:**
```
Root (100%)
├─ Cardiovascular (50%)
└─ Respiratory (50%)
```

**User Action**: Edit Cardiovascular to 60%

**Step 1: Calculate Proportional Adjustment**
```python
# Current weights
cardio_old = 50.0
resp_old = 50.0

# New weight for Cardiovascular
cardio_new = 60.0

# Calculate change
change = cardio_new - cardio_old  # +10.0

# Remaining siblings total
remaining_total = resp_old  # 50.0 (only one sibling)

# Proportional distribution (Respiratory gets 100% of the change since it's the only sibling)
resp_new = resp_old - change  # 50.0 - 10.0 = 40.0
```

**Step 2: Update Cardiovascular Node**
```sql
UPDATE subject_nodes 
SET exam_weight_low = 60.0, exam_weight_high = 60.0
WHERE id = 2;
```

**Step 3: Record Cardiovascular Weight Change**
```sql
INSERT INTO subject_node_weights (
    subject_node_id, weight_value, edited_by, edited_reason,
    previous_weight, change_type, affected_siblings, user_notes
) VALUES (
    2, 60.0, 'user', 
    'User increased priority for exam prep',
    50.0, 'manual_edit', '[3]',
    'This system appears more frequently on practice exams'
);
```

**Step 4: Update Respiratory Node**
```sql
UPDATE subject_nodes 
SET exam_weight_low = 40.0, exam_weight_high = 40.0
WHERE id = 3;
```

**Step 5: Record Respiratory Auto-Adjustment**
```sql
INSERT INTO subject_node_weights (
    subject_node_id, weight_value, edited_by, edited_reason,
    previous_weight, change_type, affected_siblings
) VALUES (
    3, 40.0, 'system',
    'Auto-adjusted due to sibling 2 (Cardiovascular) weight change',
    50.0, 'auto_recalculate', '[2]'
);
```

**Final State:**
```
Root (100%)
├─ Cardiovascular (60%)
└─ Respiratory (40%)
```

---

### Example 4: Complex 3-Sibling Proportional Balancing

**Scenario**: User changes one child's weight when there are 3 siblings

**Initial State:**
```
Cardiovascular System (60%)
├─ Anatomy (40% of 60% = 24% absolute)
├─ Physiology (30% of 60% = 18% absolute)
└─ Pathology (30% of 60% = 18% absolute)
```

**User Action**: Change Anatomy from 40% to 60%

**Calculation:**
```python
# Current relative weights (% of parent)
anatomy_old = 40.0
physiology_old = 30.0
pathology_old = 30.0

# New weight for Anatomy
anatomy_new = 60.0

# Calculate change
change = anatomy_new - anatomy_old  # +20.0

# Remaining siblings
remaining_total = physiology_old + pathology_old  # 60.0

# Proportional distribution
physiology_proportion = physiology_old / remaining_total  # 30/60 = 0.5
pathology_proportion = pathology_old / remaining_total    # 30/60 = 0.5

# Apply proportional reduction
physiology_new = physiology_old - (change * physiology_proportion)  # 30 - (20 * 0.5) = 20.0
pathology_new = pathology_old - (change * pathology_proportion)      # 30 - (20 * 0.5) = 20.0
```

**Final State:**
```
Cardiovascular System (60%)
├─ Anatomy (60% of 60% = 36% absolute)
├─ Physiology (20% of 60% = 12% absolute)
└─ Pathology (20% of 60% = 12% absolute)
```

**Weight Change Records:**
```json
// Anatomy - Manual Edit
{
    "subject_node_id": 101,
    "weight_value": 60.0,
    "previous_weight": 40.0,
    "change_type": "manual_edit",
    "affected_siblings": [102, 103]
}

// Physiology - Auto-Adjusted
{
    "subject_node_id": 102,
    "weight_value": 20.0,
    "previous_weight": 30.0,
    "change_type": "auto_recalculate",
    "affected_siblings": [103]
}

// Pathology - Auto-Adjusted
{
    "subject_node_id": 103,
    "weight_value": 20.0,
    "previous_weight": 30.0,
    "change_type": "auto_recalculate",
    "affected_siblings": [102]
}
```

---

### Example 5: Adding Custom Hierarchy Level (Level 6)

**Scenario**: User wants to go deeper than the default 5 levels

**Step 1: Check Current Hierarchy Levels**
```sql
SELECT * FROM hierarchy_level_definitions 
WHERE exam_context_id = 1 
ORDER BY level_order;
```

**Result:**
```
level_order | level_name  | is_custom_level
------------|-------------|----------------
1           | System      | FALSE
2           | Subsystem   | FALSE
3           | Topic       | FALSE
4           | Subtopic    | FALSE
5           | Child       | FALSE
```

**Step 2: Add Level 6**
```sql
INSERT INTO hierarchy_level_definitions (
    exam_context_id,
    level_name,
    level_order,
    is_required,
    display_name_template,
    is_custom_level
) VALUES (
    1,
    'Level 6',
    6,
    FALSE,
    'Daughter of {parent_name}',
    TRUE
);
```

**Step 3: Create a Level 6 Node**
```sql
-- Parent (Level 5 - Child)
INSERT INTO subject_nodes (
    exam_context, name, parent_id, level_type, exam_weight_low, exam_weight_high
) VALUES (
    'USMLE Step 1', 'Arrhythmias', 50, 'Child', 100.0, 100.0
);
-- Returns: id = 51

-- Level 6 child of Arrhythmias
INSERT INTO subject_nodes (
    exam_context, name, parent_id, level_type, exam_weight_low, exam_weight_high
) VALUES (
    'USMLE Step 1', 'Atrial Fibrillation', 51, 'Level 6', 100.0, 100.0
);
-- Returns: id = 52
```

**Frontend Display:**
- Backend stores: `level_type = "Level 6"`
- Frontend displays: "Daughter of Arrhythmias"

---

## Weight Calculation Workflows

### Workflow 1: Even Distribution Algorithm

**When to Use**: `"balancing_algorithm": "even"`

**Process:**
1. User changes node weight
2. Calculate total change amount
3. Divide change evenly among all siblings
4. Apply equal adjustment to each sibling

**Example:**
```python
def even_distribution(siblings, change_amount):
    """Distribute weight change evenly among siblings"""
    per_sibling_change = change_amount / len(siblings)
    
    for sibling in siblings:
        sibling.weight -= per_sibling_change
    
    return siblings
```

**Pros:**
- Simple to understand
- Predictable results
- Fast calculation

**Cons:**
- Can create zero or negative weights if change is large
- Doesn't preserve relative importance between siblings

---

### Workflow 2: Proportional Distribution Algorithm (Default)

**When to Use**: `"balancing_algorithm": "proportional"`

**Process:**
1. User changes node weight
2. Calculate total change amount
3. Calculate each sibling's proportion of remaining weight
4. Distribute change proportionally

**Example:**
```python
def proportional_distribution(siblings, change_amount):
    """Distribute weight change proportionally among siblings"""
    # Calculate total weight of remaining siblings
    total_remaining = sum(s.weight for s in siblings)
    
    # Calculate each sibling's proportion
    for sibling in siblings:
        proportion = sibling.weight / total_remaining
        sibling.weight -= (change_amount * proportion)
    
    return siblings
```

**Pros:**
- Maintains relative importance between siblings
- Prevents zero weights (unless sibling was already zero)
- More mathematically sound

**Cons:**
- Slightly more complex calculation
- Less intuitive for users

---

### Workflow 3: Absolute Weight Editing

**When to Use**: `"allow_absolute_weight_editing": true`

**Process:**
1. User edits absolute weight (% of root)
2. System calculates required relative weight
3. Apply proportional balancing to siblings if needed

**Example:**
```python
def edit_absolute_weight(node, new_absolute_weight):
    """Allow user to edit absolute weight, recalculate relative"""
    # Get parent's absolute weight
    parent_absolute = node.parent.absolute_weight
    
    # Calculate new relative weight
    node.relative_weight = (new_absolute_weight / parent_absolute) * 100
    
    # Balance siblings if autonomous balancing enabled
    if autonomous_balancing_enabled:
        balance_siblings(node.siblings, node.previous_relative - node.relative_weight)
    
    return node
```

---

## Validation Rules

### Rule 1: Children Sum to 100%

**When**: Always (if `require_exact_100 = true`)

**Validation:**
```python
def validate_children_sum(parent_node):
    """Ensure all children weights sum to 100% of parent"""
    children = get_children(parent_node)
    total_weight = sum(child.weight for child in children)
    
    tolerance = 0.01  # Allow 0.01% rounding difference
    
    if abs(total_weight - 100.0) > tolerance:
        raise ValidationError(
            f"Children weights sum to {total_weight}%, must equal 100%"
        )
```

---

### Rule 2: Weight Precision

**When**: Always

**Validation:**
```python
def validate_weight_precision(weight, precision_places):
    """Ensure weight matches configured precision"""
    # Round to specified precision
    rounded = round(weight, precision_places)
    
    if weight != rounded:
        raise ValidationError(
            f"Weight {weight}% exceeds precision of {precision_places} decimal places"
        )
```

---

### Rule 3: Weight Range

**When**: Always

**Validation:**
```python
def validate_weight_range(weight):
    """Ensure weight is between 0 and 100"""
    if weight < 0 or weight > 100:
        raise ValidationError(
            f"Weight {weight}% must be between 0% and 100%"
        )
```

---

### Rule 4: No Orphan Nodes

**When**: Always

**Validation:**
```python
def validate_no_orphans(node):
    """Ensure node has parent (except root)"""
    if node.level_type != 'Root' and node.parent_id is None:
        raise ValidationError(
            f"Node '{node.name}' must have a parent"
        )
```

---

## Python Code Examples

### Complete Weight Update Function

```python
def update_node_weight(
    node_id: int,
    new_weight: float,
    user_id: int,
    reason: str = None
) -> dict:
    """
    Update a node's weight and auto-balance siblings if enabled.
    
    Args:
        node_id: ID of the node to update
        new_weight: New weight value (relative %)
        user_id: ID of user making the change
        reason: Optional reason for the change
        
    Returns:
        dict with updated node and affected siblings
    """
    # Get node and exam context settings
    node = get_subject_node(node_id)
    exam_context = get_exam_context(node.exam_context)
    settings = json.loads(exam_context.weight_validation_rules)
    
    # Validate new weight
    validate_weight_range(new_weight)
    validate_weight_precision(new_weight, settings['precision_decimal_places'])
    
    # Get siblings
    siblings = get_sibling_nodes(node)
    
    # Calculate weight change
    weight_change = new_weight - node.weight
    
    # Auto-balance if enabled
    if settings['autonomous_weight_balancing']:
        if settings['balancing_algorithm'] == 'proportional':
            updated_siblings = proportional_distribution(siblings, weight_change)
        else:
            updated_siblings = even_distribution(siblings, weight_change)
        
        # Validate total sums to 100%
        if settings['require_exact_100']:
            total = new_weight + sum(s.weight for s in updated_siblings)
            if abs(total - 100.0) > 0.01:
                raise ValidationError(f"Total weight {total}% != 100%")
    
    # Update database
    with transaction():
        # Update node
        update_subject_node(node_id, new_weight)
        
        # Record weight history
        insert_weight_history(
            subject_node_id=node_id,
            weight_value=new_weight,
            previous_weight=node.weight,
            edited_by='user',
            edited_reason=reason or 'User manual edit',
            change_type='manual_edit',
            affected_siblings=[s.id for s in updated_siblings]
        )
        
        # Update and record siblings
        for sibling in updated_siblings:
            update_subject_node(sibling.id, sibling.weight)
            insert_weight_history(
                subject_node_id=sibling.id,
                weight_value=sibling.weight,
                previous_weight=sibling.original_weight,
                edited_by='system',
                edited_reason=f'Auto-adjusted due to node {node_id} change',
                change_type='auto_recalculate',
                affected_siblings=[node_id] + [s.id for s in updated_siblings if s.id != sibling.id]
            )
    
    return {
        'updated_node': node,
        'affected_siblings': updated_siblings,
        'total_updates': 1 + len(updated_siblings)
    }
```

---

## JavaScript API Examples

### Fetch Exam Context Settings

```javascript
async function getExamWeightSettings(examContextId) {
    const examContext = await api.getExamContext(examContextId);
    const settings = JSON.parse(examContext.weight_validation_rules);
    
    return {
        autonomousBalancing: settings.autonomous_weight_balancing,
        allowAbsoluteEditing: settings.allow_absolute_weight_editing,
        precision: settings.precision_decimal_places,
        algorithm: settings.balancing_algorithm
    };
}
```

### Update Weight with Validation

```javascript
async function updateNodeWeight(nodeId, newWeight, reason) {
    try {
        // Get settings
        const node = await api.getSubjectNode(nodeId);
        const settings = await getExamWeightSettings(node.exam_context_id);
        
        // Validate precision
        const rounded = parseFloat(newWeight.toFixed(settings.precision));
        if (newWeight !== rounded) {
            throw new Error(
                `Weight must have ${settings.precision} decimal places`
            );
        }
        
        // Call backend
        const result = await api.updateNodeWeight({
            node_id: nodeId,
            new_weight: newWeight,
            reason: reason
        });
        
        // Show success with affected nodes
        showNotification(
            `Updated weight. ${result.total_updates} nodes affected.`
        );
        
        return result;
        
    } catch (error) {
        showError(`Weight update failed: ${error.message}`);
        throw error;
    }
}
```

---

## Summary

This document provides comprehensive examples of all JSON structures used in Phase 2 of the WIMI project. Key takeaways:

1. **exam_contexts** stores configuration as JSON for flexibility
2. **Proportional balancing** is the recommended default algorithm
3. **Weight history** tracks all changes for audit and undo
4. **Validation** ensures data integrity at multiple levels
5. **Both Python and JavaScript** examples provided for implementation

For implementation details, see `PHASE2_IMPLEMENTATION_PLAN.md`.

---

**Document Version:** 1.0  
**Last Updated:** November 8, 2025  
**Related Documents:**
- `completed_database_tables.md` - Full schema documentation
- `PHASE2_IMPLEMENTATION_PLAN.md` - Implementation roadmap
- `Claude_Project_WIMI_context.md` - Project context
