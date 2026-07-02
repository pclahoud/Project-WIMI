# Bridge Methods Implementation Guide
**For:** Hybrid Weight System Frontend Integration  
**Status:** Database layer complete, ready for bridge implementation

---

## Overview

The database layer provides 6 main methods for hybrid weight management. This guide shows how to implement the corresponding bridge methods in `src/app/bridge_methods.py` following WIMI's established patterns.

---

## Pattern Reference

### Standard Bridge Method Structure
```python
@pyqtSlot(<input_types>, result=str)
def methodName(self, <parameters>) -> str:
    """Brief description.
    
    Args:
        param1: Description
        param2: Description
        
    Returns:
        JSON string with result or error
    """
    try:
        # 1. Parse JSON inputs if needed
        data = json.loads(json_string) if json_string else None
        
        # 2. Call database method
        result = self.user_db.database_method(
            param1=value1,
            param2=value2
        )
        
        # 3. Convert result to dict/list
        result_dict = {
            'success': True,
            'data': result.to_dict() if hasattr(result, 'to_dict') else result
        }
        
        # 4. Return JSON string
        return json.dumps(result_dict)
        
    except Exception as e:
        # Log error
        self._log_error(
            f"methodName failed: {str(e)}",
            category=ErrorCategory.BRIDGE,
            error=e
        )
        
        # Return error JSON
        return json.dumps({
            'success': False,
            'error': str(e)
        })
```

---

## Method 1: Import Official Weights

### Database Method Signature
```python
def import_official_weights(
    self,
    exam_context_id: int,
    weights_data: List[Dict[str, Any]],
    source_name: str,
    source_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Returns:
        {
            'imported': int,
            'updated': int,
            'errors': List[str],
            'subjects': List[SubjectNode]
        }
    """
```

### Bridge Method Implementation
```python
@pyqtSlot(int, str, str, str, result=str)
def importOfficialWeights(
    self,
    exam_context_id: int,
    weights_json: str,
    source_name: str,
    source_url: str = ""
) -> str:
    """Import official exam weight ranges.
    
    Args:
        exam_context_id: ID of exam context
        weights_json: JSON array of weight data
            [
                {
                    'name': 'System Name',
                    'level_type': 'System',
                    'weight_low': 20,
                    'weight_high': 25,
                    'parent_name': 'Parent Name' (optional)
                },
                ...
            ]
        source_name: Name of official source (e.g., "NBME Content Outline 2024")
        source_url: URL to source document (optional)
        
    Returns:
        JSON string: {
            'success': bool,
            'data': {
                'imported': int,
                'updated': int,
                'errors': [str],
                'subjects': [{id, name, exam_weight_low, exam_weight_high, ...}]
            }
        } or error
    """
    try:
        # Parse weights data
        weights_data = json.loads(weights_json)
        
        # Validate input
        if not isinstance(weights_data, list):
            raise ValueError("weights_json must be an array")
        
        # Import weights
        result = self.user_db.import_official_weights(
            exam_context_id=exam_context_id,
            weights_data=weights_data,
            source_name=source_name,
            source_url=source_url if source_url else None
        )
        
        # Convert SubjectNode objects to dicts
        result['subjects'] = [
            subject.to_dict() for subject in result['subjects']
        ]
        
        return json.dumps({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        self._log_error(
            f"importOfficialWeights failed: {str(e)}",
            category=ErrorCategory.BRIDGE,
            error=e,
            context={
                'exam_context_id': exam_context_id,
                'source_name': source_name
            }
        )
        return json.dumps({
            'success': False,
            'error': str(e)
        })
```

### JavaScript Usage
```javascript
async function importOfficialWeights(examContextId, weightsData, sourceName, sourceUrl = '') {
    const weightsJson = JSON.stringify(weightsData);
    const resultJson = await window.pythonBridge.importOfficialWeights(
        examContextId,
        weightsJson,
        sourceName,
        sourceUrl
    );
    
    const result = JSON.parse(resultJson);
    if (!result.success) {
        throw new Error(result.error);
    }
    
    return result.data; // {imported, updated, errors, subjects}
}

// Example usage
const weightsData = [
    {name: 'Gastrointestinal System', level_type: 'System', weight_low: 20, weight_high: 25},
    {name: 'Cardiovascular System', level_type: 'System', weight_low: 10, weight_high: 15}
];

const result = await importOfficialWeights(
    examContextId,
    weightsData,
    "NBME Content Outline 2024",
    "https://www.usmle.org/content-outline"
);

console.log(`Imported: ${result.imported}, Updated: ${result.updated}`);
if (result.errors.length > 0) {
    console.error('Import errors:', result.errors);
}
```

---

## Method 2: Update Relative Weight

### Database Method Signature
```python
def update_subject_relative_weight(
    self,
    node_id: int,
    relative_weight: float,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Returns:
        {
            'old_weight': float,
            'new_weight': float,
            'updated_node': SubjectNode,
            'rebalanced': bool,
            'affected_siblings': List[Dict]
        }
    """
```

### Bridge Method Implementation
```python
@pyqtSlot(int, float, str, result=str)
def updateRelativeWeight(
    self,
    node_id: int,
    relative_weight: float,
    reason: str = ""
) -> str:
    """Update relative weight with automatic sibling rebalancing.
    
    Args:
        node_id: ID of subject node to update
        relative_weight: New relative weight (0-100)
        reason: Optional reason for change (for audit trail)
        
    Returns:
        JSON string: {
            'success': bool,
            'data': {
                'old_weight': float,
                'new_weight': float,
                'updated_node': {...},
                'rebalanced': bool,
                'affected_siblings': [
                    {'id': int, 'name': str, 'old_weight': float, 'new_weight': float},
                    ...
                ]
            }
        } or error
    """
    try:
        result = self.user_db.update_subject_relative_weight(
            node_id=node_id,
            relative_weight=relative_weight,
            reason=reason if reason else None
        )
        
        # Convert SubjectNode to dict
        result['updated_node'] = result['updated_node'].to_dict()
        
        return json.dumps({
            'success': True,
            'data': result
        })
        
    except SubjectNodeError as e:
        # Specific error for locked weights or other subject issues
        self._log_error(
            f"updateRelativeWeight failed: {str(e)}",
            category=ErrorCategory.BRIDGE,
            error=e,
            context={'node_id': node_id, 'relative_weight': relative_weight}
        )
        return json.dumps({
            'success': False,
            'error': str(e),
            'error_type': 'SubjectNodeError'
        })
        
    except WeightValidationError as e:
        # Specific error for invalid weights
        self._log_error(
            f"updateRelativeWeight validation failed: {str(e)}",
            category=ErrorCategory.BRIDGE,
            error=e,
            context={'node_id': node_id, 'relative_weight': relative_weight}
        )
        return json.dumps({
            'success': False,
            'error': str(e),
            'error_type': 'WeightValidationError'
        })
        
    except Exception as e:
        self._log_error(
            f"updateRelativeWeight failed: {str(e)}",
            category=ErrorCategory.BRIDGE,
            error=e,
            context={'node_id': node_id}
        )
        return json.dumps({
            'success': False,
            'error': str(e)
        })
```

### JavaScript Usage
```javascript
async function updateRelativeWeight(nodeId, relativeWeight, reason = '') {
    const resultJson = await window.pythonBridge.updateRelativeWeight(
        nodeId,
        relativeWeight,
        reason
    );
    
    const result = JSON.parse(resultJson);
    if (!result.success) {
        if (result.error_type === 'SubjectNodeError') {
            throw new Error(`Cannot update weight: ${result.error}`);
        } else if (result.error_type === 'WeightValidationError') {
            throw new Error(`Invalid weight: ${result.error}`);
        }
        throw new Error(result.error);
    }
    
    return result.data;
}

// Example: Update Esophagus from 15% to 20%
const result = await updateRelativeWeight(
    esophagusId,
    20,
    "Increased based on exam analysis"
);

console.log(`Weight changed: ${result.old_weight}% → ${result.new_weight}%`);
if (result.rebalanced) {
    console.log('Affected siblings:', result.affected_siblings);
}
```

---

## Method 3: Get Subjects with Effective Weights

### Database Method Signature
```python
def get_subjects_with_effective_weights(
    self,
    exam_context_id: int,
    include_children: bool = True
) -> List[Dict[str, Any]]:
    """
    Returns list of dicts with structure:
        {
            'id': int,
            'name': str,
            'level_type': str,
            'weight': {
                'absolute_low': float or None,
                'absolute_high': float or None,
                'relative': float or None,
                'effective': float,
                'effective_low': float,
                'effective_high': float,
                'source': str,
                'confidence': str ('high', 'medium', 'low'),
                'locked': bool
            },
            'children': [...]
        }
    """
```

### Bridge Method Implementation
```python
@pyqtSlot(int, bool, result=str)
def getSubjectsWithEffectiveWeights(
    self,
    exam_context_id: int,
    include_children: bool = True
) -> str:
    """Get subjects with calculated effective weights.
    
    Args:
        exam_context_id: ID of exam context
        include_children: Whether to include child subjects recursively
        
    Returns:
        JSON string: {
            'success': bool,
            'data': [
                {
                    'id': int,
                    'name': str,
                    'level_type': str,
                    'weight': {
                        'absolute_low': float or null,
                        'absolute_high': float or null,
                        'relative': float or null,
                        'effective': float,
                        'effective_low': float,
                        'effective_high': float,
                        'source': str,
                        'confidence': str,
                        'locked': bool
                    },
                    'children': [...]
                },
                ...
            ]
        } or error
    """
    try:
        subjects = self.user_db.get_subjects_with_effective_weights(
            exam_context_id=exam_context_id,
            include_children=include_children
        )
        
        return json.dumps({
            'success': True,
            'data': subjects
        })
        
    except Exception as e:
        self._log_error(
            f"getSubjectsWithEffectiveWeights failed: {str(e)}",
            category=ErrorCategory.BRIDGE,
            error=e,
            context={'exam_context_id': exam_context_id}
        )
        return json.dumps({
            'success': False,
            'error': str(e)
        })
```

### JavaScript Usage
```javascript
async function getSubjectsWithEffectiveWeights(examContextId, includeChildren = true) {
    const resultJson = await window.pythonBridge.getSubjectsWithEffectiveWeights(
        examContextId,
        includeChildren
    );
    
    const result = JSON.parse(resultJson);
    if (!result.success) {
        throw new Error(result.error);
    }
    
    return result.data;
}

// Example: Display subjects with weights
const subjects = await getSubjectsWithEffectiveWeights(examContextId);

subjects.forEach(subject => {
    console.log(`${subject.name}:`);
    console.log(`  Effective: ${subject.weight.effective.toFixed(2)}%`);
    console.log(`  Range: ${subject.weight.effective_low.toFixed(2)}%-${subject.weight.effective_high.toFixed(2)}%`);
    console.log(`  Confidence: ${subject.weight.confidence}`);
    
    if (subject.children && subject.children.length > 0) {
        subject.children.forEach(child => {
            console.log(`    ${child.name}: ${child.weight.effective.toFixed(2)}%`);
        });
    }
});
```

---

## Method 4: Get Weight Configuration

### Database Method Signature
```python
def get_weight_config_for_exam(
    self,
    exam_context_id: int
) -> Dict[str, Any]:
    """
    Returns:
        {
            'weight_mode': str ('official_ranges', 'official_fixed', 'user_defined'),
            'has_official_weights': bool,
            'official_weight_count': int,
            'user_defined_count': int,
            'total_weight_sum': float,
            'weights_sum_to_100': bool,
            'source_name': str or None,
            'source_url': str or None
        }
    """
```

### Bridge Method Implementation
```python
@pyqtSlot(int, result=str)
def getWeightConfig(
    self,
    exam_context_id: int
) -> str:
    """Get weight configuration for exam.
    
    Args:
        exam_context_id: ID of exam context
        
    Returns:
        JSON string: {
            'success': bool,
            'data': {
                'weight_mode': str,
                'has_official_weights': bool,
                'official_weight_count': int,
                'user_defined_count': int,
                'total_weight_sum': float,
                'weights_sum_to_100': bool,
                'source_name': str or null,
                'source_url': str or null
            }
        } or error
    """
    try:
        config = self.user_db.get_weight_config_for_exam(
            exam_context_id=exam_context_id
        )
        
        return json.dumps({
            'success': True,
            'data': config
        })
        
    except Exception as e:
        self._log_error(
            f"getWeightConfig failed: {str(e)}",
            category=ErrorCategory.BRIDGE,
            error=e,
            context={'exam_context_id': exam_context_id}
        )
        return json.dumps({
            'success': False,
            'error': str(e)
        })
```

### JavaScript Usage
```javascript
async function getWeightConfig(examContextId) {
    const resultJson = await window.pythonBridge.getWeightConfig(examContextId);
    
    const result = JSON.parse(resultJson);
    if (!result.success) {
        throw new Error(result.error);
    }
    
    return result.data;
}

// Example: Display weight configuration status
const config = await getWeightConfig(examContextId);

console.log(`Weight Mode: ${config.weight_mode}`);
console.log(`Official Weights: ${config.official_weight_count}`);
console.log(`User-Defined: ${config.user_defined_count}`);
console.log(`Total Sum: ${config.total_weight_sum.toFixed(2)}%`);
console.log(`Sums to 100%: ${config.weights_sum_to_100}`);

if (config.source_name) {
    console.log(`Source: ${config.source_name}`);
}

// UI display logic
if (config.weight_mode === 'official_ranges') {
    displayOfficialWeightUI(config);
} else if (config.weight_mode === 'user_defined') {
    displayUserDefinedWeightUI(config);
}
```

---

## Testing Bridge Methods

### Unit Test Pattern
```python
def test_import_official_weights_bridge(self, bridge_manager, test_exam_context):
    """Test importOfficialWeights bridge method."""
    weights_data = [
        {'name': 'Test System', 'level_type': 'System', 'weight_low': 20, 'weight_high': 25}
    ]
    weights_json = json.dumps(weights_data)
    
    result_json = bridge_manager.importOfficialWeights(
        exam_context_id=test_exam_context.id,
        weights_json=weights_json,
        source_name="Test Source",
        source_url=""
    )
    
    result = json.loads(result_json)
    assert result['success'] == True
    assert result['data']['imported'] == 1
    assert len(result['data']['subjects']) == 1
```

### Manual Testing Checklist
- [ ] Import official weights successfully
- [ ] Handle import errors gracefully
- [ ] Update relative weight with rebalancing
- [ ] Prevent updating locked weights
- [ ] Reject invalid weight values
- [ ] Calculate effective weights correctly
- [ ] Display weight configuration
- [ ] Create subjects with weights
- [ ] Handle validation errors

---

## Error Handling

### Exception Types to Handle
1. `SubjectNodeError` - Invalid node operations, locked weights
2. `WeightValidationError` - Invalid weight values
3. `ValidationError` - General validation failures
4. `DatabaseIntegrityError` - Database constraint violations

### Error Response Format
```json
{
    "success": false,
    "error": "Human-readable error message",
    "error_type": "WeightValidationError"
}
```

---

## Integration with Existing Bridge

Add these methods to the existing `BridgeManager` class in `src/app/bridge_methods.py`. They follow the same patterns as existing methods like `createSubjectNode`, `getSubjectHierarchy`, etc.

### Location in Bridge Class
Place these methods in a new section:
```python
# ==================== Weight Management ====================
def importOfficialWeights(self, ...):
    ...

def updateRelativeWeight(self, ...):
    ...

def getSubjectsWithEffectiveWeights(self, ...):
    ...

def getWeightConfig(self, ...):
    ...
```
