# Weight System Hybrid Implementation Plan

## Executive Summary

This document specifies a hybrid weight system that supports both **official exam weight ranges** (imported, locked) and **user-defined relative weights** for child subjects. This approach acknowledges that official exam outlines provide ranges only at certain hierarchy levels, while allowing users to estimate relative importance of sub-topics for deeper analysis.

---

## Problem Statement

### Current Limitations

1. Weight settings assume single-value, user-editable weights
2. No distinction between official (imported) and user-defined weights
3. No mechanism for child weights when parent has official range
4. Autonomous balancing doesn't account for ranges
5. Analytics can't differentiate between authoritative and estimated weights

### Use Cases to Support

| Use Case | Weight Source | Editing | Balancing |
|----------|---------------|---------|-----------|
| USMLE with NBME outline | Official ranges | Locked | Disabled |
| Custom study plan | User-defined | Full | Enabled |
| USMLE with sub-topic estimates | Hybrid | Partial | Relative only |

---

## Design Specification

### Core Concepts

#### 1. Weight Modes

| Mode | Description | Example |
|------|-------------|---------|
| `official_ranges` | Imported from authoritative source, stored as low/high | USMLE: "GI 20%-25%" |
| `official_fixed` | Imported single values, locked | Some exams with exact percentages |
| `user_defined` | User creates and edits freely | Custom study plans |

#### 2. Weight Sources

| Source | Meaning | Editable |
|--------|---------|----------|
| `official` | From exam authority (NBME, ETS, etc.) | No |
| `derived` | Calculated from parent/children | No |
| `user_estimate` | User's best guess for unofficial weights | Yes |
| `user_defined` | User created from scratch | Yes |

#### 3. Weight Types

| Type | Column(s) | Use |
|------|-----------|-----|
| **Absolute Range** | `exam_weight_low`, `exam_weight_high` | Top-level official weights |
| **Relative Weight** | `relative_weight` (NEW) | Child importance within parent |

---

## Schema Changes

### 1. Subject Nodes Table Additions

```sql
-- New columns for subject_nodes
ALTER TABLE subject_nodes ADD COLUMN relative_weight REAL
    CHECK (relative_weight IS NULL OR (relative_weight >= 0 AND relative_weight <= 100));

ALTER TABLE subject_nodes ADD COLUMN weight_source VARCHAR(50)
    DEFAULT 'user_defined'
    CHECK (weight_source IN ('official', 'derived', 'user_estimate', 'user_defined'));

ALTER TABLE subject_nodes ADD COLUMN weight_locked BOOLEAN
    DEFAULT FALSE;

-- Index for weight queries
CREATE INDEX IF NOT EXISTS idx_subject_nodes_weight_source 
    ON subject_nodes(exam_context, weight_source);
```

### 2. Exam Contexts Weight Rules Update

```sql
-- Update default weight_validation_rules structure
-- This is documentation; actual update happens in application code

/*
New weight_validation_rules JSON structure:
{
    "weight_mode": "official_ranges" | "official_fixed" | "user_defined",
    "weight_source_name": "NBME Content Outline 2024",  -- For official modes
    "weight_source_url": "https://...",                 -- Optional reference
    
    "official_weights_locked": true,        -- Prevent editing official weights
    "child_weight_mode": "relative" | "none" | "inherited",
    
    "relative_weight_balancing": true,      -- Siblings' relative weights sum to 100
    "allow_relative_estimates": true,       -- Users can estimate child weights
    
    -- Legacy settings (for user_defined mode)
    "autonomous_weight_balancing": false,
    "precision_decimal_places": 1,
    "require_exact_100": false,
    "balancing_algorithm": "proportional"
}
*/
```

### 3. Weight History Enhancement

```sql
-- Track relative weight changes too
ALTER TABLE subject_node_weights ADD COLUMN relative_weight_value DECIMAL(6,3);
ALTER TABLE subject_node_weights ADD COLUMN weight_type VARCHAR(20)
    DEFAULT 'absolute'
    CHECK (weight_type IN ('absolute', 'relative'));
```

---

## Data Model Updates

### Python Dataclasses

```python
# src/database/models.py

from dataclasses import dataclass, field
from typing import Optional, List, Literal
from enum import Enum


class WeightSource(Enum):
    OFFICIAL = "official"
    DERIVED = "derived"
    USER_ESTIMATE = "user_estimate"
    USER_DEFINED = "user_defined"


class WeightMode(Enum):
    OFFICIAL_RANGES = "official_ranges"
    OFFICIAL_FIXED = "official_fixed"
    USER_DEFINED = "user_defined"


class ChildWeightMode(Enum):
    RELATIVE = "relative"      # Children have relative weights within parent
    NONE = "none"              # Children have no weights
    INHERITED = "inherited"    # Children inherit proportional share (not recommended)


@dataclass
class WeightConfig:
    """Weight configuration for an exam context."""
    weight_mode: WeightMode
    weight_source_name: Optional[str] = None
    weight_source_url: Optional[str] = None
    official_weights_locked: bool = True
    child_weight_mode: ChildWeightMode = ChildWeightMode.RELATIVE
    relative_weight_balancing: bool = True
    allow_relative_estimates: bool = True
    precision_decimal_places: int = 1
    
    @classmethod
    def for_official_ranges(cls, source_name: str, source_url: str = None):
        """Factory for official range mode (e.g., USMLE)."""
        return cls(
            weight_mode=WeightMode.OFFICIAL_RANGES,
            weight_source_name=source_name,
            weight_source_url=source_url,
            official_weights_locked=True,
            child_weight_mode=ChildWeightMode.RELATIVE,
            relative_weight_balancing=True,
            allow_relative_estimates=True
        )
    
    @classmethod
    def for_user_defined(cls):
        """Factory for fully user-defined weights."""
        return cls(
            weight_mode=WeightMode.USER_DEFINED,
            official_weights_locked=False,
            child_weight_mode=ChildWeightMode.RELATIVE,
            relative_weight_balancing=True,
            allow_relative_estimates=True
        )


@dataclass
class SubjectWeight:
    """Complete weight information for a subject node."""
    # Absolute weights (for top-level or official)
    absolute_low: Optional[float] = None
    absolute_high: Optional[float] = None
    
    # Relative weight (for children)
    relative: Optional[float] = None
    
    # Metadata
    source: WeightSource = WeightSource.USER_DEFINED
    locked: bool = False
    
    @property
    def has_absolute(self) -> bool:
        return self.absolute_low is not None
    
    @property
    def has_relative(self) -> bool:
        return self.relative is not None
    
    @property
    def absolute_midpoint(self) -> Optional[float]:
        if self.absolute_low is None:
            return None
        high = self.absolute_high or self.absolute_low
        return (self.absolute_low + high) / 2
    
    @property
    def has_range(self) -> bool:
        return (
            self.absolute_low is not None and
            self.absolute_high is not None and
            self.absolute_low != self.absolute_high
        )
    
    @property
    def display(self) -> str:
        """Human-readable weight display."""
        if self.has_absolute:
            if self.has_range:
                return f"{self.absolute_low}%–{self.absolute_high}%"
            return f"{self.absolute_low}%"
        if self.has_relative:
            return f"{self.relative}% (relative)"
        return "—"


@dataclass
class SubjectNode:
    """Subject node with hybrid weight support."""
    id: int
    exam_context: str
    parent_id: Optional[int]
    name: str
    level_type: str
    sort_order: int
    
    # Weight data
    exam_weight_low: Optional[float] = None
    exam_weight_high: Optional[float] = None
    relative_weight: Optional[float] = None
    weight_source: str = "user_defined"
    weight_locked: bool = False
    
    # Metadata
    exam_source: Optional[str] = None
    status: str = "active"
    
    # Relationships
    children: List['SubjectNode'] = field(default_factory=list)
    
    @property
    def weight(self) -> SubjectWeight:
        """Get structured weight information."""
        return SubjectWeight(
            absolute_low=self.exam_weight_low,
            absolute_high=self.exam_weight_high,
            relative=self.relative_weight,
            source=WeightSource(self.weight_source),
            locked=self.weight_locked
        )
    
    def get_effective_weight(self, parent_weight: Optional[SubjectWeight] = None) -> Optional[float]:
        """
        Calculate effective absolute weight.
        
        For nodes with absolute weights, returns midpoint.
        For nodes with relative weights, calculates from parent.
        """
        if self.exam_weight_low is not None:
            high = self.exam_weight_high or self.exam_weight_low
            return (self.exam_weight_low + high) / 2
        
        if self.relative_weight is not None and parent_weight and parent_weight.has_absolute:
            parent_mid = parent_weight.absolute_midpoint
            return (self.relative_weight / 100) * parent_mid
        
        return None
```

---

## Database Operations

### Weight Management Methods

```python
# src/database/user_database.py (additions)

class UserDatabase:
    
    def update_subject_relative_weight(
        self,
        node_id: int,
        relative_weight: float,
        reason: str = None
    ) -> SubjectNode:
        """
        Update a subject's relative weight within its parent.
        
        Args:
            node_id: Subject node ID
            relative_weight: New relative weight (0-100)
            reason: Optional reason for change
            
        Returns:
            Updated SubjectNode
            
        Raises:
            WeightValidationError: If weight is invalid or node is locked
        """
        node = self.get_subject_node(node_id)
        if not node:
            raise ValidationError(f"Subject node {node_id} not found")
        
        if node.weight_locked:
            raise WeightValidationError("Cannot modify locked official weight")
        
        if relative_weight < 0 or relative_weight > 100:
            raise WeightValidationError("Relative weight must be between 0 and 100")
        
        # Get exam config to check settings
        config = self._get_weight_config_for_node(node_id)
        
        with self.transaction():
            # Update the node
            self.execute("""
                UPDATE subject_nodes 
                SET relative_weight = ?,
                    weight_source = 'user_estimate',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (relative_weight, node_id))
            
            # Record history
            self._record_weight_change(
                node_id=node_id,
                weight_type='relative',
                new_value=relative_weight,
                reason=reason
            )
            
            # Optionally rebalance siblings
            if config.relative_weight_balancing:
                self._rebalance_sibling_relative_weights(node_id, relative_weight)
        
        return self.get_subject_node(node_id)
    
    def import_official_weights(
        self,
        exam_context_id: int,
        weights_data: List[dict],
        source_name: str,
        source_url: str = None
    ) -> dict:
        """
        Import official weights from an authoritative source.
        
        Args:
            exam_context_id: Target exam context
            weights_data: List of weight definitions:
                [
                    {
                        "name": "Gastrointestinal System",
                        "weight_low": 20,
                        "weight_high": 25,
                        "level_type": "System",
                        "children": [...]  # Optional nested children
                    },
                    ...
                ]
            source_name: Name of the source (e.g., "NBME Content Outline 2024")
            source_url: Optional URL reference
            
        Returns:
            Import summary with counts
        """
        config = self.get_exam_context_config(exam_context_id)
        if not config:
            raise ValidationError("Exam context not found")
        
        # Update exam config to official_ranges mode
        self._update_weight_config(exam_context_id, WeightConfig.for_official_ranges(
            source_name=source_name,
            source_url=source_url
        ))
        
        imported = {'total': 0, 'root': 0, 'children': 0}
        
        def import_node(node_data: dict, parent_id: int = None, level: int = 1):
            # Determine if this node has official weights
            has_official_weight = 'weight_low' in node_data or 'weight_high' in node_data
            
            node = self.create_subject_node(
                exam_context=config.exam_name,
                name=node_data['name'],
                level_type=node_data.get('level_type', f'Level {level}'),
                parent_id=parent_id,
                exam_weight_low=node_data.get('weight_low'),
                exam_weight_high=node_data.get('weight_high', node_data.get('weight_low')),
                weight_source='official' if has_official_weight else 'user_defined',
                weight_locked=has_official_weight,
                exam_source=source_name if has_official_weight else None
            )
            
            imported['total'] += 1
            if parent_id is None:
                imported['root'] += 1
            else:
                imported['children'] += 1
            
            # Import children recursively
            for child_data in node_data.get('children', []):
                import_node(child_data, node.id, level + 1)
        
        with self.transaction():
            for node_data in weights_data:
                import_node(node_data)
        
        return imported
    
    def get_subject_with_effective_weights(
        self,
        exam_context_id: int
    ) -> List[dict]:
        """
        Get all subjects with their effective absolute weights calculated.
        
        For subjects with relative weights, calculates absolute weight
        based on parent's weight.
        
        Returns:
            List of subjects with effective_weight field
        """
        config = self.get_exam_context_config(exam_context_id)
        hierarchy = self.get_subject_hierarchy(config.exam_name)
        
        results = []
        
        def process_node(node: SubjectNode, parent_effective_weight: float = None):
            # Calculate effective weight
            if node.exam_weight_low is not None:
                # Has absolute weight
                effective = (node.exam_weight_low + (node.exam_weight_high or node.exam_weight_low)) / 2
            elif node.relative_weight is not None and parent_effective_weight is not None:
                # Calculate from relative weight
                effective = (node.relative_weight / 100) * parent_effective_weight
            else:
                effective = None
            
            results.append({
                'id': node.id,
                'name': node.name,
                'level_type': node.level_type,
                'parent_id': node.parent_id,
                'weight': {
                    'absolute_low': node.exam_weight_low,
                    'absolute_high': node.exam_weight_high,
                    'relative': node.relative_weight,
                    'effective': effective,
                    'source': node.weight_source,
                    'locked': node.weight_locked
                }
            })
            
            for child in node.children or []:
                process_node(child, effective)
        
        for root in hierarchy:
            process_node(root)
        
        return results
    
    def _rebalance_sibling_relative_weights(
        self,
        changed_node_id: int,
        new_weight: float
    ):
        """
        Rebalance sibling relative weights to sum to 100.
        
        Uses proportional adjustment on other siblings.
        """
        # Get the changed node's parent
        node = self.get_subject_node(changed_node_id)
        if node.parent_id is None:
            return  # Root nodes don't have siblings to balance
        
        # Get all siblings (including the changed node)
        siblings = self.fetchall("""
            SELECT id, relative_weight, weight_locked
            FROM subject_nodes
            WHERE parent_id = ? AND status = 'active' AND id != ?
        """, (node.parent_id, changed_node_id))
        
        if not siblings:
            return
        
        # Calculate how much weight is left for siblings
        remaining = 100 - new_weight
        
        # Get total of unlocked siblings' current weights
        unlocked_siblings = [s for s in siblings if not s['weight_locked']]
        current_total = sum(s['relative_weight'] or 0 for s in unlocked_siblings)
        
        if current_total == 0:
            # Distribute equally
            equal_share = remaining / len(unlocked_siblings) if unlocked_siblings else 0
            for sibling in unlocked_siblings:
                self.execute("""
                    UPDATE subject_nodes 
                    SET relative_weight = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (equal_share, sibling['id']))
        else:
            # Proportional adjustment
            scale = remaining / current_total
            for sibling in unlocked_siblings:
                old_weight = sibling['relative_weight'] or 0
                new_sibling_weight = old_weight * scale
                self.execute("""
                    UPDATE subject_nodes 
                    SET relative_weight = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_sibling_weight, sibling['id']))
```

---

## API Layer Updates

### Bridge Methods

```python
# src/app/bridge.py (additions)

@pyqtSlot(str, result=str)
def importOfficialWeights(self, import_data_json: str) -> str:
    """
    Import official weights from authoritative source.
    
    Args:
        import_data_json: JSON with:
            - exam_context_id: int
            - source_name: str (e.g., "NBME Content Outline 2024")
            - source_url: str (optional)
            - weights: array of weight definitions
    """
    if not self.user_db:
        return serialize_response(False, error='No user database connected')
    
    try:
        data = json.loads(import_data_json)
        
        result = self.user_db.import_official_weights(
            exam_context_id=data['exam_context_id'],
            weights_data=data['weights'],
            source_name=data['source_name'],
            source_url=data.get('source_url')
        )
        
        return serialize_response(True, data=result)
        
    except Exception as e:
        self._log_error(f'Error importing official weights: {e}')
        return serialize_response(False, error=str(e))


@pyqtSlot(int, float, str, result=str)
def updateRelativeWeight(
    self,
    node_id: int,
    relative_weight: float,
    reason: str = ''
) -> str:
    """
    Update a subject's relative weight within its parent.
    """
    if not self.user_db:
        return serialize_response(False, error='No user database connected')
    
    try:
        node = self.user_db.update_subject_relative_weight(
            node_id=node_id,
            relative_weight=relative_weight,
            reason=reason if reason else None
        )
        
        return serialize_response(True, data={
            'id': node.id,
            'name': node.name,
            'relative_weight': node.relative_weight,
            'weight_source': node.weight_source
        })
        
    except WeightValidationError as e:
        return serialize_response(False, error=str(e))
    except Exception as e:
        self._log_error(f'Error updating relative weight: {e}')
        return serialize_response(False, error=str(e))


@pyqtSlot(int, result=str)
def getSubjectsWithEffectiveWeights(self, exam_context_id: int) -> str:
    """
    Get all subjects with calculated effective weights.
    """
    if not self.user_db:
        return serialize_response(False, error='No user database connected')
    
    try:
        subjects = self.user_db.get_subject_with_effective_weights(exam_context_id)
        return serialize_response(True, data=subjects)
        
    except Exception as e:
        self._log_error(f'Error getting effective weights: {e}')
        return serialize_response(False, error=str(e))


@pyqtSlot(int, result=str)
def getWeightConfig(self, exam_context_id: int) -> str:
    """
    Get weight configuration for an exam context.
    """
    if not self.user_db:
        return serialize_response(False, error='No user database connected')
    
    try:
        config = self.user_db.get_exam_context_config(exam_context_id)
        if not config:
            return serialize_response(False, error='Exam context not found')
        
        # Parse weight rules
        rules = json.loads(config.weight_validation_rules) if config.weight_validation_rules else {}
        
        return serialize_response(True, data={
            'weight_mode': rules.get('weight_mode', 'user_defined'),
            'weight_source_name': rules.get('weight_source_name'),
            'weight_source_url': rules.get('weight_source_url'),
            'official_weights_locked': rules.get('official_weights_locked', False),
            'child_weight_mode': rules.get('child_weight_mode', 'relative'),
            'relative_weight_balancing': rules.get('relative_weight_balancing', True),
            'allow_relative_estimates': rules.get('allow_relative_estimates', True)
        })
        
    except Exception as e:
        self._log_error(f'Error getting weight config: {e}')
        return serialize_response(False, error=str(e))
```

---

## Frontend Implementation

### Weight Configuration UI

```javascript
// src/web/js/weight_config.js

class WeightConfigPanel {
    constructor(containerId, api) {
        this.container = document.getElementById(containerId);
        this.api = api;
        this.config = null;
    }
    
    async load(examContextId) {
        this.config = await this.api.getWeightConfig(examContextId);
        this.render();
    }
    
    render() {
        const isOfficial = this.config.weight_mode === 'official_ranges';
        
        this.container.innerHTML = `
            <div class="weight-config-panel">
                <div class="config-header">
                    <h3>Weight Configuration</h3>
                    ${isOfficial ? this.renderOfficialBadge() : ''}
                </div>
                
                <div class="config-info">
                    <div class="config-row">
                        <span class="label">Mode:</span>
                        <span class="value">${this.formatMode(this.config.weight_mode)}</span>
                    </div>
                    
                    ${isOfficial ? `
                        <div class="config-row">
                            <span class="label">Source:</span>
                            <span class="value">
                                ${this.config.weight_source_url 
                                    ? `<a href="${this.config.weight_source_url}" target="_blank">${this.config.weight_source_name}</a>`
                                    : this.config.weight_source_name
                                }
                            </span>
                        </div>
                        <div class="config-row">
                            <span class="label">Official weights:</span>
                            <span class="value">${this.config.official_weights_locked ? '🔒 Locked' : 'Editable'}</span>
                        </div>
                    ` : ''}
                    
                    <div class="config-row">
                        <span class="label">Child weights:</span>
                        <span class="value">${this.formatChildMode(this.config.child_weight_mode)}</span>
                    </div>
                </div>
            </div>
        `;
    }
    
    renderOfficialBadge() {
        return `
            <span class="official-badge" title="Weights from official source">
                <svg>...</svg> Official
            </span>
        `;
    }
    
    formatMode(mode) {
        const modes = {
            'official_ranges': 'Official Weight Ranges',
            'official_fixed': 'Official Fixed Weights',
            'user_defined': 'Custom Weights'
        };
        return modes[mode] || mode;
    }
    
    formatChildMode(mode) {
        const modes = {
            'relative': 'Relative (% within parent)',
            'none': 'No child weights',
            'inherited': 'Inherited from parent'
        };
        return modes[mode] || mode;
    }
}
```

### Subject Weight Editor

```javascript
// src/web/js/subject_weight_editor.js

class SubjectWeightEditor {
    constructor(api) {
        this.api = api;
    }
    
    renderWeightCell(subject, config) {
        const weight = subject.weight;
        const isLocked = weight.locked;
        const isOfficial = weight.source === 'official';
        
        // Official absolute weight (locked)
        if (weight.absolute_low !== null && isLocked) {
            return `
                <div class="weight-cell locked">
                    <span class="weight-value">${this.formatAbsoluteWeight(weight)}</span>
                    <span class="lock-icon" title="Official weight (locked)">🔒</span>
                </div>
            `;
        }
        
        // Editable absolute weight
        if (weight.absolute_low !== null && !isLocked) {
            return `
                <div class="weight-cell editable">
                    <input type="number" 
                           class="weight-input absolute-low" 
                           value="${weight.absolute_low}"
                           data-node-id="${subject.id}"
                           data-field="absolute_low">
                    <span class="range-separator">–</span>
                    <input type="number" 
                           class="weight-input absolute-high" 
                           value="${weight.absolute_high || weight.absolute_low}"
                           data-node-id="${subject.id}"
                           data-field="absolute_high">
                    <span class="percent">%</span>
                </div>
            `;
        }
        
        // Relative weight (for children)
        if (config.child_weight_mode === 'relative') {
            const relativeValue = weight.relative !== null ? weight.relative : '';
            const effectiveDisplay = weight.effective !== null 
                ? `≈ ${weight.effective.toFixed(1)}%` 
                : '';
            
            return `
                <div class="weight-cell relative">
                    <input type="number" 
                           class="weight-input relative" 
                           value="${relativeValue}"
                           placeholder="—"
                           data-node-id="${subject.id}"
                           data-field="relative">
                    <span class="percent">%</span>
                    <span class="effective-weight" title="Effective absolute weight">
                        ${effectiveDisplay}
                    </span>
                </div>
            `;
        }
        
        // No weight
        return `<div class="weight-cell none">—</div>`;
    }
    
    formatAbsoluteWeight(weight) {
        if (weight.absolute_low === null) return '—';
        
        const low = weight.absolute_low;
        const high = weight.absolute_high || low;
        
        if (low === high) {
            return `${low}%`;
        }
        return `${low}%–${high}%`;
    }
    
    async handleWeightChange(nodeId, field, value) {
        try {
            if (field === 'relative') {
                await this.api.updateRelativeWeight(nodeId, parseFloat(value));
            } else {
                // Handle absolute weight updates
                await this.api.updateSubjectNodeWeight(nodeId, parseFloat(value));
            }
            
            // Refresh display to show rebalanced siblings
            this.onWeightUpdated?.();
            
        } catch (error) {
            this.showError(error.message);
        }
    }
}
```

### Weight Display in Hierarchy View

```javascript
// src/web/js/subject_hierarchy.js (updates)

renderSubjectRow(subject, config, depth = 0) {
    const indent = depth * 24;
    const weight = subject.weight;
    
    // Determine weight display based on what's available
    let weightDisplay = '';
    let weightClass = '';
    
    if (weight.absolute_low !== null) {
        // Has absolute weight
        weightClass = weight.locked ? 'official' : 'user';
        if (weight.absolute_low !== weight.absolute_high) {
            weightDisplay = `${weight.absolute_low}–${weight.absolute_high}%`;
        } else {
            weightDisplay = `${weight.absolute_low}%`;
        }
    } else if (weight.relative !== null) {
        // Has relative weight
        weightClass = 'relative';
        weightDisplay = `${weight.relative}%`;
        if (weight.effective !== null) {
            weightDisplay += ` <span class="effective">(≈${weight.effective.toFixed(1)}%)</span>`;
        }
    } else {
        weightClass = 'none';
        weightDisplay = '—';
    }
    
    return `
        <div class="subject-row" data-id="${subject.id}" data-depth="${depth}">
            <div class="subject-name" style="padding-left: ${indent}px">
                ${subject.children?.length ? '<span class="expand-icon">▶</span>' : '<span class="spacer"></span>'}
                <span class="name">${subject.name}</span>
                <span class="level-type">${subject.level_type}</span>
            </div>
            <div class="subject-weight ${weightClass}">
                ${weightDisplay}
                ${weight.locked ? '<span class="lock">🔒</span>' : ''}
            </div>
        </div>
    `;
}
```

---

## Analytics Updates

### Effective Weight in Analysis

```python
# src/database/analytics.py (updates)

def get_subject_exam_weight_analysis(self, exam_context_id: int) -> dict:
    """
    Weight analysis using effective weights for all subjects.
    
    - Subjects with absolute weights: use range bounds
    - Subjects with relative weights: calculate effective absolute weight
    """
    subjects = self.get_subject_with_effective_weights(exam_context_id)
    mistake_counts = self._get_mistake_counts_by_subject(exam_context_id)
    
    total_mistakes = sum(mistake_counts.values())
    
    analyzed = []
    for subj in subjects:
        weight = subj['weight']
        mistake_count = mistake_counts.get(subj['id'], 0)
        mistake_pct = (mistake_count / total_mistakes * 100) if total_mistakes > 0 else 0
        
        # Determine quadrant based on available weight info
        if weight['absolute_low'] is not None:
            # Use range-aware quadrant assignment
            quadrant_info = self._assign_quadrant_with_range(
                mistake_pct=mistake_pct,
                weight_low=weight['absolute_low'],
                weight_high=weight['absolute_high'] or weight['absolute_low']
            )
        elif weight['effective'] is not None:
            # Use effective weight as single point
            quadrant_info = self._assign_quadrant_single(
                mistake_pct=mistake_pct,
                weight=weight['effective']
            )
        else:
            # No weight info - can't categorize
            quadrant_info = {
                'quadrant': 'uncategorized',
                'confidence': 'none',
                'reason': 'No weight data available'
            }
        
        analyzed.append({
            'subject_id': subj['id'],
            'subject_name': subj['name'],
            'level_type': subj['level_type'],
            'weight': weight,
            'mistake_count': mistake_count,
            'mistake_percentage': round(mistake_pct, 1),
            **quadrant_info
        })
    
    return {
        'subjects': analyzed,
        'quadrant_analysis': self._group_by_quadrant(analyzed),
        'insights': self._generate_insights(analyzed),
        'total_mistakes': total_mistakes
    }


def _assign_quadrant_with_range(
    self, 
    mistake_pct: float, 
    weight_low: float, 
    weight_high: float
) -> dict:
    """Assign quadrant using range bounds for honest categorization."""
    
    # Definite cases (beyond range bounds)
    if mistake_pct > weight_high:
        return {
            'quadrant': 'priority',
            'confidence': 'high',
            'reason': 'Mistakes exceed highest expected weight'
        }
    
    if mistake_pct < weight_low * 0.5:
        return {
            'quadrant': 'over_studied',
            'confidence': 'high',
            'reason': 'Mistakes well below lowest expected weight'
        }
    
    if mistake_pct < weight_low:
        return {
            'quadrant': 'well_maintained',
            'confidence': 'high',
            'reason': 'Mistakes below expected range'
        }
    
    # Within range (uncertain)
    midpoint = (weight_low + weight_high) / 2
    
    if mistake_pct >= midpoint:
        return {
            'quadrant': 'priority',
            'confidence': 'medium',
            'reason': 'Mistakes in upper half of expected range'
        }
    else:
        return {
            'quadrant': 'well_maintained',
            'confidence': 'medium',
            'reason': 'Mistakes in lower half of expected range'
        }


def _assign_quadrant_single(self, mistake_pct: float, weight: float) -> dict:
    """Assign quadrant for single-point weight (derived from relative)."""
    
    diff = mistake_pct - weight
    
    if diff > 5:
        return {
            'quadrant': 'priority',
            'confidence': 'medium',  # Lower confidence since weight is derived
            'reason': f'Mistakes {diff:.1f}% above estimated weight'
        }
    elif diff < -5:
        return {
            'quadrant': 'well_maintained',
            'confidence': 'medium',
            'reason': f'Mistakes {abs(diff):.1f}% below estimated weight'
        }
    else:
        return {
            'quadrant': 'aligned',
            'confidence': 'medium',
            'reason': 'Mistakes roughly aligned with estimated weight'
        }
```

---

## Migration Guide

### Phase 1: Schema Migration

```sql
-- Run these migrations in order

-- 1. Add new columns to subject_nodes
ALTER TABLE subject_nodes ADD COLUMN relative_weight REAL
    CHECK (relative_weight IS NULL OR (relative_weight >= 0 AND relative_weight <= 100));

ALTER TABLE subject_nodes ADD COLUMN weight_source VARCHAR(50)
    DEFAULT 'user_defined'
    CHECK (weight_source IN ('official', 'derived', 'user_estimate', 'user_defined'));

ALTER TABLE subject_nodes ADD COLUMN weight_locked BOOLEAN DEFAULT FALSE;

-- 2. Add index
CREATE INDEX IF NOT EXISTS idx_subject_nodes_weight_source 
    ON subject_nodes(exam_context, weight_source);

-- 3. Update weight history
ALTER TABLE subject_node_weights ADD COLUMN relative_weight_value DECIMAL(6,3);
ALTER TABLE subject_node_weights ADD COLUMN weight_type VARCHAR(20) DEFAULT 'absolute';
```

### Phase 2: Data Migration

```python
def migrate_existing_weights():
    """
    Migrate existing weight data to new structure.
    
    - Existing weights become 'user_defined' source
    - No locking applied to existing data
    """
    db.execute("""
        UPDATE subject_nodes 
        SET weight_source = 'user_defined',
            weight_locked = FALSE
        WHERE weight_source IS NULL
    """)
```

### Phase 3: Code Deployment

1. Deploy schema changes
2. Run data migration
3. Deploy updated backend code
4. Deploy updated frontend

---

## Testing Plan

### Unit Tests

```python
# tests/test_hybrid_weights.py

class TestHybridWeights:
    
    def test_import_official_ranges(self, user_db):
        """Test importing official weight ranges."""
        result = user_db.import_official_weights(
            exam_context_id=1,
            weights_data=[
                {'name': 'GI System', 'weight_low': 20, 'weight_high': 25},
                {'name': 'Cardiovascular', 'weight_low': 10, 'weight_high': 15}
            ],
            source_name='NBME 2024'
        )
        
        assert result['total'] == 2
        
        # Verify locked
        gi = user_db.get_subject_node_by_name('GI System')
        assert gi.weight_locked == True
        assert gi.weight_source == 'official'
    
    def test_relative_weight_update(self, user_db):
        """Test updating relative weight with sibling rebalancing."""
        # Setup: parent with 3 children, each at 33.3%
        parent = create_test_subject(user_db, weight_low=20, weight_high=25)
        child1 = create_test_subject(user_db, parent_id=parent.id, relative_weight=33.3)
        child2 = create_test_subject(user_db, parent_id=parent.id, relative_weight=33.3)
        child3 = create_test_subject(user_db, parent_id=parent.id, relative_weight=33.3)
        
        # Update child1 to 50%
        user_db.update_subject_relative_weight(child1.id, 50.0)
        
        # Verify siblings rebalanced
        child2_updated = user_db.get_subject_node(child2.id)
        child3_updated = user_db.get_subject_node(child3.id)
        
        # Remaining 50% split between child2 and child3
        assert child2_updated.relative_weight == pytest.approx(25.0, rel=0.1)
        assert child3_updated.relative_weight == pytest.approx(25.0, rel=0.1)
    
    def test_effective_weight_calculation(self, user_db):
        """Test effective weight calculation from relative weights."""
        # Parent: 20-25% (midpoint 22.5%)
        parent = create_test_subject(user_db, weight_low=20, weight_high=25)
        # Child: 40% relative
        child = create_test_subject(user_db, parent_id=parent.id, relative_weight=40)
        
        subjects = user_db.get_subject_with_effective_weights(exam_context_id=1)
        child_data = next(s for s in subjects if s['id'] == child.id)
        
        # Effective = 40% of 22.5% = 9%
        assert child_data['weight']['effective'] == pytest.approx(9.0, rel=0.1)
    
    def test_locked_weight_prevents_editing(self, user_db):
        """Test that locked weights cannot be modified."""
        subject = create_test_subject(
            user_db, 
            weight_low=20, 
            weight_high=25,
            weight_locked=True
        )
        
        with pytest.raises(WeightValidationError):
            user_db.update_subject_relative_weight(subject.id, 50.0)
    
    def test_quadrant_assignment_with_range(self):
        """Test range-aware quadrant assignment."""
        # Mistakes above range = high confidence priority
        result = assign_quadrant_with_range(30.0, 20.0, 25.0)
        assert result['quadrant'] == 'priority'
        assert result['confidence'] == 'high'
        
        # Mistakes within range = medium confidence
        result = assign_quadrant_with_range(22.0, 20.0, 25.0)
        assert result['confidence'] == 'medium'
        
        # Mistakes below range = high confidence well maintained
        result = assign_quadrant_with_range(15.0, 20.0, 25.0)
        assert result['quadrant'] == 'well_maintained'
        assert result['confidence'] == 'high'
```

### Integration Tests

```python
class TestHybridWeightsIntegration:
    
    def test_full_usmle_import_flow(self, app, user_db):
        """Test complete USMLE import and analysis flow."""
        # 1. Create exam context
        exam = user_db.create_exam_context(exam_name='USMLE Step 1')
        
        # 2. Import official weights
        user_db.import_official_weights(
            exam_context_id=exam.id,
            weights_data=USMLE_CONTENT_OUTLINE,
            source_name='NBME Content Outline 2024'
        )
        
        # 3. Add some child relative weights
        gi = user_db.get_subject_node_by_name('Gastrointestinal System')
        user_db.create_subject_node(
            exam_context='USMLE Step 1',
            name='Esophagus',
            parent_id=gi.id,
            relative_weight=15
        )
        
        # 4. Add some mistakes
        create_test_entries(user_db, exam.id, subject_id=gi.id, count=30)
        
        # 5. Run analysis
        analysis = user_db.get_subject_exam_weight_analysis(exam.id)
        
        # Verify GI shows up in analysis with correct weight
        gi_analysis = next(s for s in analysis['subjects'] if s['subject_name'] == 'Gastrointestinal System')
        assert gi_analysis['weight']['absolute_low'] == 20
        assert gi_analysis['weight']['absolute_high'] == 25
        assert gi_analysis['weight']['locked'] == True
```

---

## Summary

| Component | Change | Priority |
|-----------|--------|----------|
| Schema | Add `relative_weight`, `weight_source`, `weight_locked` columns | High |
| Models | Add `WeightConfig`, update `SubjectNode` | High |
| Database | Add import, relative weight, effective weight methods | High |
| Bridge | Add new API methods | High |
| Frontend | Weight config panel, updated editor | Medium |
| Analytics | Use effective weights in analysis | Medium |
| Tests | Unit + integration tests | High |

This hybrid approach allows WIMI to:
1. Import and lock official weight ranges
2. Let users estimate relative importance of sub-topics
3. Calculate effective weights for deeper analysis
4. Provide honest confidence levels in recommendations
