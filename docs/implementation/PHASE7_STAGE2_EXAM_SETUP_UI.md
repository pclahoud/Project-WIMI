# Phase 7.2: Exam Setup UI Implementation Plan

**Status:** 🚀 Ready to Begin  
**Prerequisites:** Phase 7.1 (Foundation & Schema) ✅ Complete  
**Estimated Duration:** 2-3 weeks  
**Created:** January 14, 2026

---

## Table of Contents

1. [Overview](#overview)
2. [Goals & Deliverables](#goals--deliverables)
3. [Implementation Stages](#implementation-stages)
4. [UI Components](#ui-components)
5. [Database Integration](#database-integration)
6. [Bridge Layer Methods](#bridge-layer-methods)
7. [Testing Requirements](#testing-requirements)
8. [Files to Create/Modify](#files-to-createmodify)
9. [Implementation Order](#implementation-order)
10. [Success Criteria](#success-criteria)

---

## Overview

Phase 7.2 enables users to create **multi-dimensional exams** through the Exam Setup Wizard. This phase builds upon the database foundation from Phase 7.1 to provide:

1. **Exam Type Selection** - Users choose between simple (single hierarchy) and multi-dimensional exams
2. **Dimension Definition** - For multi-dimensional exams, users define independent categorization dimensions
3. **Per-Dimension Hierarchy Builder** - Each dimension gets its own hierarchy of categories
4. **Template System Foundation** - Pre-built exam structures for common standardized tests

---

## Goals & Deliverables

### Primary Goals

| # | Goal | Description |
|---|------|-------------|
| 1 | Exam Type Selection | Users can choose between simple and multi-dimensional exam types |
| 2 | Dimension Definition UI | Create/edit/delete dimensions with metadata (name, order, required, allow_multiple) |
| 3 | Per-Dimension Hierarchy | Build separate hierarchies for each dimension |
| 4 | Template System | Import pre-built exam structures |
| 5 | Review & Create | Summary view before finalizing exam creation |

### Deliverables Checklist

- [ ] **UI: Exam Type Selection Screen**
  - [ ] Radio buttons for Simple vs Multi-Dimensional
  - [ ] "Learn More" modals explaining each type
  - [ ] Visual examples of each structure

- [ ] **UI: Dimension Definition Screen**
  - [ ] Add/edit/delete dimension form
  - [ ] Drag-and-drop reordering
  - [ ] Validation (unique names, required fields)
  - [ ] Display order management

- [ ] **UI: Per-Dimension Hierarchy Builder**
  - [ ] Tab or dropdown to switch dimensions
  - [ ] Reuse existing tree_editor component
  - [ ] Link nodes to dimension_id
  - [ ] Weight range input per node

- [ ] **UI: Template Selection**
  - [ ] Template library grid/list
  - [ ] Template preview modal
  - [ ] Import and customize flow

- [ ] **Bridge Layer**
  - [ ] `createDimension()` method
  - [ ] `getDimensions()` method
  - [ ] `updateDimension()` method
  - [ ] `deleteDimension()` method
  - [ ] `reorderDimensions()` method
  - [ ] `createHierarchyNodeWithDimension()` method
  - [ ] `getTemplates()` method
  - [ ] `importTemplate()` method
  - [ ] `examUsesDimensions()` method

- [ ] **Templates**
  - [ ] NBME Shelf Exam template (JSON)
  - [ ] SAT Math template (JSON)
  - [ ] GRE Verbal template (JSON)
  - [ ] Template parser and validator

---

## Implementation Stages

### Stage 2.1: Exam Type Selection (Days 1-3)

**Goal:** Add exam type selection to the existing wizard

**Tasks:**
1. Modify `exam_wizard.html` to add type selection as Step 0 (before current Step 1)
2. Create exam type selection component with radio buttons
3. Add "Learn More" modal dialogs
4. Store exam type in wizard state
5. Conditionally show dimension step based on type

**Files to Modify:**
- `src/web/html/wizards/exam_wizard.html`
- `src/web/js/exam_wizard.js`
- `src/web/css/wizard.css`

### Stage 2.2: Dimension Definition UI (Days 4-7)

**Goal:** Allow users to define dimensions for multi-dimensional exams

**Tasks:**
1. Create dimension definition step (new Step 2 for multi-dim exams)
2. Build dimension card component (name, description, required toggle, allow_multiple toggle)
3. Implement add/edit/delete dimension functionality
4. Add drag-and-drop reordering with display_order updates
5. Validate dimension uniqueness within exam

**New Components:**
- Dimension card with form fields
- Dimension list with drag-and-drop
- Dimension validation

### Stage 2.3: Per-Dimension Hierarchy Builder (Days 8-11)

**Goal:** Build separate hierarchies for each dimension

**Tasks:**
1. Create dimension tab/dropdown selector
2. Modify tree editor to work within dimension context
3. Link hierarchy nodes to dimension_id
4. Handle dimension switching with state preservation
5. Validate each dimension's hierarchy independently

**Integration Points:**
- Reuse `tree_editor.js` component
- Extend to support dimension context
- Connect to new bridge methods

### Stage 2.4: Template System Foundation (Days 12-14)

**Goal:** Enable template-based exam creation

**Tasks:**
1. Create template JSON schema
2. Build 2-3 initial templates (NBME Shelf, SAT, GRE)
3. Create template library UI
4. Implement template preview modal
5. Build template import logic
6. Allow customization after import

**Template Structure:**
```json
{
  "template_id": "nbme_shelf_internal_med_v1",
  "template_name": "NBME Shelf - Internal Medicine",
  "template_type": "multi_dimensional",
  "dimensions": [...],
  "hierarchies": {...}
}
```

### Stage 2.5: Review & Bridge Integration (Days 15-17)

**Goal:** Complete the wizard flow and connect to database

**Tasks:**
1. Update review/summary screen for multi-dimensional exams
2. Implement all bridge layer methods
3. Connect UI to backend via bridge
4. Handle exam creation with dimensions
5. Error handling and validation feedback

---

## UI Components

### 1. Exam Type Selector

**Location:** New step 0 in wizard (before exam info)

```html
<div class="wizard-step" id="step-type">
    <h2 class="step-title">Choose Exam Type</h2>
    <p class="step-description">Select the structure that best fits your exam</p>
    
    <div class="exam-type-cards">
        <!-- Simple Exam Card -->
        <div class="exam-type-card" data-type="simple">
            <div class="card-radio">
                <input type="radio" name="exam-type" id="type-simple" value="simple" checked>
            </div>
            <div class="card-content">
                <h3>Simple Exam</h3>
                <p>Single topic hierarchy</p>
                <p class="examples">e.g., SAT Math, GRE Verbal</p>
                <div class="hierarchy-preview">
                    <div class="preview-node">Math</div>
                    <div class="preview-node level-1">├─ Algebra</div>
                    <div class="preview-node level-2">│  └─ Quadratics</div>
                    <div class="preview-node level-1">└─ Geometry</div>
                </div>
                <button type="button" class="btn-learn-more" data-type="simple">
                    Learn More
                </button>
            </div>
        </div>
        
        <!-- Multi-Dimensional Exam Card -->
        <div class="exam-type-card" data-type="multi_dimensional">
            <div class="card-radio">
                <input type="radio" name="exam-type" id="type-multi" value="multi_dimensional">
            </div>
            <div class="card-content">
                <h3>Multi-Dimensional Exam</h3>
                <p>Multiple independent dimensions</p>
                <p class="examples">e.g., NBME Shelf, USMLE</p>
                <div class="dimension-preview">
                    <div class="preview-dimension">Site of Care</div>
                    <div class="preview-dimension">Physician Task</div>
                    <div class="preview-dimension">System</div>
                </div>
                <button type="button" class="btn-learn-more" data-type="multi_dimensional">
                    Learn More
                </button>
            </div>
        </div>
    </div>
</div>
```

### 2. Dimension Definition Component

**New step for multi-dimensional exams:**

```html
<div class="wizard-step" id="step-dimensions">
    <h2 class="step-title">Define Dimensions</h2>
    <p class="step-description">
        Create independent categories for classifying your questions
    </p>
    
    <div class="dimensions-container" id="dimensions-list">
        <!-- Dimension cards will be rendered here -->
    </div>
    
    <button type="button" class="btn btn-secondary" id="btn-add-dimension">
        + Add Dimension
    </button>
    
    <div class="alert alert-info">
        <strong>💡 Example:</strong> NBME Shelf exams use 3 dimensions:
        Site of Care, Physician Task, and System.
    </div>
</div>
```

**Dimension Card Template:**

```html
<div class="dimension-card" data-dimension-index="${index}" draggable="true">
    <div class="dimension-header">
        <span class="drag-handle">⋮⋮</span>
        <span class="dimension-number">Dimension ${index + 1}</span>
        <button type="button" class="btn-delete-dimension" title="Delete dimension">
            ✕
        </button>
    </div>
    <div class="dimension-body">
        <div class="form-group">
            <label>Name <span class="required">*</span></label>
            <input type="text" class="dimension-name" placeholder="e.g., Site of Care" required>
        </div>
        <div class="form-group">
            <label>Description</label>
            <input type="text" class="dimension-description" placeholder="e.g., Where the patient encounter occurs">
        </div>
        <div class="form-row">
            <label class="checkbox-label">
                <input type="checkbox" class="dimension-required" checked>
                Required
            </label>
            <label class="checkbox-label">
                <input type="checkbox" class="dimension-allow-multiple">
                Allow multiple selections
            </label>
        </div>
    </div>
</div>
```

### 3. Per-Dimension Hierarchy Tab Interface

```html
<div class="wizard-step" id="step-dimension-hierarchies">
    <h2 class="step-title">Build Hierarchies</h2>
    <p class="step-description">
        Create the hierarchy structure for each dimension
    </p>
    
    <!-- Dimension Tabs -->
    <div class="dimension-tabs" id="dimension-tabs">
        <!-- Tabs generated dynamically -->
    </div>
    
    <!-- Hierarchy Editor Container -->
    <div class="hierarchy-editor-container" id="dimension-hierarchy-editor">
        <!-- Reused tree editor component -->
    </div>
    
    <div class="dimension-nav">
        <button type="button" class="btn btn-secondary" id="btn-prev-dimension" disabled>
            ← Previous Dimension
        </button>
        <button type="button" class="btn btn-primary" id="btn-next-dimension">
            Next Dimension →
        </button>
    </div>
</div>
```

### 4. Template Library Modal

```html
<div class="modal-backdrop hidden" id="template-modal">
    <div class="modal modal-large">
        <div class="modal-header">
            <h2>Choose Template</h2>
            <button type="button" class="modal-close" id="btn-close-template">✕</button>
        </div>
        <div class="modal-body">
            <div class="template-filters">
                <button class="filter-btn active" data-filter="all">All</button>
                <button class="filter-btn" data-filter="simple">Simple</button>
                <button class="filter-btn" data-filter="multi_dimensional">Multi-Dimensional</button>
            </div>
            
            <div class="template-grid" id="template-grid">
                <!-- Template cards rendered here -->
            </div>
        </div>
    </div>
</div>
```

---

## Database Integration

### Using Phase 7.1 Methods

Phase 7.2 will use the database methods created in Phase 7.1:

| Method | Purpose |
|--------|---------|
| `create_dimension()` | Create new dimension for exam |
| `get_exam_dimensions()` | Get all dimensions for exam |
| `get_dimension()` | Get single dimension by ID |
| `update_dimension()` | Update dimension properties |
| `delete_dimension()` | Delete dimension (cascades to tags) |
| `exam_uses_dimensions()` | Check if exam is multi-dimensional |

### New Methods Needed (user_db.py)

```python
def create_hierarchy_node_with_dimension(
    self,
    exam_context_id: int,
    name: str,
    dimension_id: int,
    parent_id: Optional[int] = None,
    weight_min: Optional[float] = None,
    weight_max: Optional[float] = None
) -> SubjectNode:
    """Create hierarchy node linked to a dimension"""
    # Similar to create_subject_node but with dimension_id
    pass

def get_dimension_hierarchy(
    self,
    exam_context_id: int,
    dimension_id: int
) -> List[SubjectNode]:
    """Get all hierarchy nodes for a specific dimension"""
    pass

def reorder_dimensions(
    self,
    exam_context_id: int,
    dimension_order: List[int]
) -> bool:
    """Update display_order for multiple dimensions"""
    pass
```

---

## Bridge Layer Methods

### New Bridge Methods (bridge.py)

```python
# =========================================================================
# Multi-Dimensional Exam Operations
# =========================================================================

@pyqtSlot(int, result=str)
def examUsesDimensions(self, exam_context_id: int) -> str:
    """
    Check if an exam uses multi-dimensional categorization.
    
    Args:
        exam_context_id: ID of the exam context
        
    Returns:
        JSON response with boolean 'uses_dimensions'
    """
    pass

@pyqtSlot(int, str, int, bool, bool, str, result=str)
def createDimension(
    self,
    exam_context_id: int,
    name: str,
    display_order: int,
    is_required: bool = True,
    allow_multiple: bool = False,
    description: str = ''
) -> str:
    """
    Create a new dimension for an exam.
    
    Returns:
        JSON response with created dimension data
    """
    pass

@pyqtSlot(int, result=str)
def getDimensions(self, exam_context_id: int) -> str:
    """
    Get all dimensions for an exam.
    
    Returns:
        JSON response with list of dimensions
    """
    pass

@pyqtSlot(int, str, result=str)
def updateDimension(self, dimension_id: int, updates_json: str) -> str:
    """
    Update dimension properties.
    
    Args:
        dimension_id: ID of dimension to update
        updates_json: JSON string with fields to update
        
    Returns:
        JSON response with updated dimension data
    """
    pass

@pyqtSlot(int, result=str)
def deleteDimension(self, dimension_id: int) -> str:
    """
    Delete a dimension.
    
    Returns:
        JSON response with success/failure
    """
    pass

@pyqtSlot(int, str, result=str)
def reorderDimensions(self, exam_context_id: int, order_json: str) -> str:
    """
    Reorder dimensions.
    
    Args:
        exam_context_id: ID of the exam
        order_json: JSON array of dimension IDs in new order
        
    Returns:
        JSON response with success/failure
    """
    pass

@pyqtSlot(int, str, int, int, float, float, result=str)
def createHierarchyNodeWithDimension(
    self,
    exam_context_id: int,
    name: str,
    dimension_id: int,
    parent_id: int = -1,  # Use -1 for None since pyqtSlot doesn't handle Optional
    weight_min: float = -1,
    weight_max: float = -1
) -> str:
    """
    Create a hierarchy node linked to a dimension.
    
    Returns:
        JSON response with created node data
    """
    pass

@pyqtSlot(int, int, result=str)
def getDimensionHierarchy(self, exam_context_id: int, dimension_id: int) -> str:
    """
    Get hierarchy nodes for a specific dimension.
    
    Returns:
        JSON response with hierarchy tree
    """
    pass

# =========================================================================
# Template Operations
# =========================================================================

@pyqtSlot(str, result=str)
def getTemplates(self, filter_type: str = 'all') -> str:
    """
    Get available exam templates.
    
    Args:
        filter_type: 'all', 'simple', or 'multi_dimensional'
        
    Returns:
        JSON response with template list
    """
    pass

@pyqtSlot(str, result=str)
def getTemplatePreview(self, template_id: str) -> str:
    """
    Get full template details for preview.
    
    Returns:
        JSON response with template structure
    """
    pass

@pyqtSlot(str, str, result=str)
def importTemplate(self, template_id: str, exam_name: str) -> str:
    """
    Create exam from template.
    
    Args:
        template_id: ID of template to import
        exam_name: Name for the new exam
        
    Returns:
        JSON response with created exam data
    """
    pass
```

---

## Testing Requirements

### Unit Tests (test_user_db.py)

```python
class TestDimensionOperations(unittest.TestCase):
    """Tests for dimension-related database operations"""
    
    def test_create_dimension(self):
        """Test creating a dimension"""
        pass
    
    def test_create_dimension_duplicate_name(self):
        """Test duplicate dimension name validation"""
        pass
    
    def test_get_exam_dimensions_ordered(self):
        """Test dimensions are returned in display_order"""
        pass
    
    def test_update_dimension(self):
        """Test updating dimension properties"""
        pass
    
    def test_delete_dimension(self):
        """Test deleting dimension"""
        pass
    
    def test_reorder_dimensions(self):
        """Test reordering dimensions"""
        pass

class TestHierarchyWithDimension(unittest.TestCase):
    """Tests for hierarchy operations with dimensions"""
    
    def test_create_node_with_dimension(self):
        """Test creating hierarchy node linked to dimension"""
        pass
    
    def test_get_dimension_hierarchy(self):
        """Test getting hierarchy for specific dimension"""
        pass
    
    def test_dimension_hierarchy_isolation(self):
        """Test hierarchies are isolated per dimension"""
        pass
```

### Integration Tests

```python
class TestExamWizardIntegration(unittest.TestCase):
    """Integration tests for exam wizard with dimensions"""
    
    def test_create_simple_exam(self):
        """Test creating simple exam (no dimensions)"""
        pass
    
    def test_create_multi_dimensional_exam(self):
        """Test creating multi-dimensional exam with 3 dimensions"""
        pass
    
    def test_import_template(self):
        """Test importing exam from template"""
        pass
```

### Manual Testing Checklist

- [ ] Create simple exam (existing flow still works)
- [ ] Select multi-dimensional exam type
- [ ] Add 3 dimensions with names and descriptions
- [ ] Reorder dimensions via drag-and-drop
- [ ] Delete a dimension
- [ ] Build hierarchy for each dimension
- [ ] Switch between dimension tabs
- [ ] Review summary shows all dimensions
- [ ] Create exam successfully
- [ ] Verify database records created correctly
- [ ] Open template library
- [ ] Preview template
- [ ] Import template and customize

---

## Files to Create/Modify

### New Files

| File | Purpose |
|------|---------|
| `src/web/css/exam_type_selector.css` | Styles for exam type selection |
| `src/web/css/dimension_editor.css` | Styles for dimension cards |
| `src/web/js/dimension_editor.js` | Dimension management component |
| `src/web/js/template_library.js` | Template browsing and import |
| `src/templates/nbme_shelf_im.json` | NBME Shelf Internal Med template |
| `src/templates/sat_math.json` | SAT Math template |
| `src/templates/gre_verbal.json` | GRE Verbal template |
| `tests/test_dimensions.py` | Dimension unit tests |

### Modified Files

| File | Changes |
|------|---------|
| `src/web/html/wizards/exam_wizard.html` | Add type selection, dimension steps |
| `src/web/js/exam_wizard.js` | Multi-step logic for multi-dim exams |
| `src/web/css/wizard.css` | Wizard styling updates |
| `src/app/bridge.py` | Add dimension bridge methods |
| `src/database/user_db.py` | Add dimension hierarchy methods |
| `src/web/js/api.js` | Add dimension API wrapper functions |

---

## Implementation Order

### Week 1: Core UI Components

| Day | Tasks |
|-----|-------|
| 1 | Modify wizard HTML for exam type selection |
| 2 | Implement exam type selection JS logic |
| 3 | Create exam type CSS styling |
| 4 | Build dimension card component (HTML/CSS) |
| 5 | Implement dimension editor JS (add/edit/delete) |

### Week 2: Hierarchy & Backend Integration

| Day | Tasks |
|-----|-------|
| 6 | Implement drag-and-drop dimension reordering |
| 7 | Create dimension tabs/selector for hierarchy step |
| 8 | Modify tree editor for dimension context |
| 9 | Implement bridge layer methods |
| 10 | Connect UI to bridge layer |

### Week 3: Templates & Polish

| Day | Tasks |
|-----|-------|
| 11 | Create template JSON schema and examples |
| 12 | Build template library UI |
| 13 | Implement template import logic |
| 14 | Update review/summary screen |
| 15 | Testing, bug fixes, documentation |

---

## Success Criteria

Phase 7.2 is complete when:

✅ **Exam Type Selection**
- Users can choose between simple and multi-dimensional exam types
- "Learn More" modals explain each type clearly
- Selection persists through wizard navigation

✅ **Dimension Definition**
- Users can add, edit, delete dimensions
- Drag-and-drop reordering works
- Validation prevents duplicate names
- Display order updates correctly

✅ **Per-Dimension Hierarchy**
- Tab interface allows switching between dimensions
- Tree editor works within dimension context
- Hierarchy nodes correctly linked to dimension_id
- Each dimension's hierarchy is independent

✅ **Template System**
- At least 2 templates available (1 simple, 1 multi-dim)
- Template preview shows full structure
- Import creates exam with correct structure
- Imported exams can be customized

✅ **Backend Integration**
- All bridge methods implemented and working
- Database operations complete successfully
- Error handling provides clear feedback

✅ **Testing**
- Unit tests passing for new methods
- Manual testing checklist complete
- No regressions in existing functionality

---

## Notes for Implementation

### Key Design Decisions

1. **Wizard Step Modification**: The existing 4-step wizard becomes:
   - Simple exams: Type → Info → Hierarchy → Weights → Review (5 steps)
   - Multi-dim exams: Type → Info → Dimensions → Hierarchies → Weights → Review (6 steps)

2. **Hierarchy Editor Reuse**: The existing `tree_editor.js` should be reused with minimal modifications. Add a `dimensionId` parameter to hierarchy operations.

3. **Template Storage**: Templates are stored as JSON files in a `templates/` directory. Future phases may allow user-created templates.

4. **Progressive Disclosure**: Don't show all options at once. Start simple, reveal complexity only when needed.

### Potential Challenges

1. **Tree Editor Modification**: The existing tree editor may need significant refactoring to support dimension context. Plan for extra time here.

2. **State Management**: Managing state across multiple dimensions while switching tabs requires careful design.

3. **Validation Complexity**: Validating hierarchies per dimension while maintaining overall exam consistency.

### Dependencies

- Phase 7.1 database methods must be complete and tested
- Existing wizard components must remain functional
- No changes to existing simple exam flow

---

## Quick Reference

### Database Method Mapping

| Bridge Method | Database Method |
|---------------|-----------------|
| `examUsesDimensions()` | `exam_uses_dimensions()` |
| `createDimension()` | `create_dimension()` |
| `getDimensions()` | `get_exam_dimensions()` |
| `updateDimension()` | `update_dimension()` |
| `deleteDimension()` | `delete_dimension()` |
| `reorderDimensions()` | `reorder_dimensions()` (new) |
| `createHierarchyNodeWithDimension()` | `create_hierarchy_node_with_dimension()` (new) |
| `getDimensionHierarchy()` | `get_dimension_hierarchy()` (new) |

### API Wrapper Functions (api.js)

```javascript
// Dimension operations
window.wimiAPI.examUsesDimensions(examContextId)
window.wimiAPI.createDimension(examContextId, name, displayOrder, isRequired, allowMultiple, description)
window.wimiAPI.getDimensions(examContextId)
window.wimiAPI.updateDimension(dimensionId, updates)
window.wimiAPI.deleteDimension(dimensionId)
window.wimiAPI.reorderDimensions(examContextId, orderArray)

// Dimension hierarchy operations
window.wimiAPI.createHierarchyNodeWithDimension(examContextId, name, dimensionId, parentId, weightMin, weightMax)
window.wimiAPI.getDimensionHierarchy(examContextId, dimensionId)

// Template operations
window.wimiAPI.getTemplates(filterType)
window.wimiAPI.getTemplatePreview(templateId)
window.wimiAPI.importTemplate(templateId, examName)
```

---

**Document Version:** 1.0  
**Created:** January 14, 2026  
**Last Updated:** January 14, 2026  
**Next Phase:** 7.3 (Question Entry UI)
