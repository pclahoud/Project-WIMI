# Phase 7.2 Stage 2.3: Per-Dimension Hierarchy Editor Changes

**Document Purpose:** Outline necessary UI/UX changes to enable editing multi-dimensional exam content outlines  
**Status:** Planning  
**Created:** January 16, 2026  
**Target Files:**
- `src/web/html/tree_editor.html`
- `src/web/js/tree_editor.js`
- `src/web/js/weight_editor.js`

---

## Table of Contents

1. [Overview](#overview)
2. [Current State](#current-state)
3. [Required Changes Summary](#required-changes-summary)
4. [Detailed Changes: tree_editor.html](#detailed-changes-tree_editorhtml)
5. [Detailed Changes: tree_editor.js](#detailed-changes-tree_editorjs)
6. [Detailed Changes: weight_editor.js](#detailed-changes-weight_editorjs)
7. [New CSS Requirements](#new-css-requirements)
8. [API Methods Required](#api-methods-required)
9. [Implementation Order](#implementation-order)
10. [Testing Checklist](#testing-checklist)

---

## Overview

### Goal

Enable users to edit the subject hierarchy for **each dimension separately** in multi-dimensional exams. When a user opens the tree editor for a multi-dimensional exam (e.g., NBME Shelf), they should:

1. See which dimensions exist for this exam
2. Switch between dimensions via tabs or dropdown
3. Build/edit the hierarchy for each dimension independently
4. Understand which dimension they're currently editing

### User Experience Flow

```
User opens Tree Editor for "NBME Shelf - Internal Medicine"
    ↓
System detects exam has 3 dimensions
    ↓
Shows dimension selector: [Site of Care] [Physician Task] [System]
    ↓
User clicks "Site of Care" tab
    ↓
Tree shows only hierarchy for Site of Care dimension:
  - Ambulatory
  - Emergency Department
  - Inpatient
  - Surgical
    ↓
User adds/edits nodes within this dimension
    ↓
User clicks "System" tab
    ↓
Tree shows only hierarchy for System dimension:
  - Cardiovascular
    - Arrhythmias
    - Heart Failure
  - Pulmonary
    - Asthma
    - COPD
  ...etc
```

### Backward Compatibility

- **Simple exams:** No changes to current behavior. No dimension selector shown.
- **Multi-dimensional exams:** Show dimension selector. Each dimension has its own hierarchy tree.

---

## Current State

### tree_editor.html
- Single tree view for the entire exam
- No dimension awareness
- Header shows exam name and badge
- Toolbar has Add Root, Import Weights, Collapse/Expand buttons

### tree_editor.js
- Loads hierarchy via `api.getSubjectHierarchy(examContextId)`
- Stores all nodes in `TreeState.rootNodes` and `TreeState.flatNodes`
- Creates nodes via `api.createSubjectNode()` or `api.createSubjectNodeWithWeight()`
- No concept of dimensions

### weight_editor.js
- Manages weight editing for individual nodes
- Shows sibling weights for comparison
- No dimension-specific behavior needed (weights are per-node regardless of dimension)

---

## Required Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `tree_editor.html` | Add | Dimension selector UI (tabs or dropdown) |
| `tree_editor.html` | Add | Dimension info panel showing current dimension details |
| `tree_editor.html` | Add | Help text explaining dimensions |
| `tree_editor.js` | Add | State for current dimension |
| `tree_editor.js` | Add | Function to detect if exam uses dimensions |
| `tree_editor.js` | Add | Function to load dimensions for exam |
| `tree_editor.js` | Modify | `loadHierarchy()` to filter by dimension |
| `tree_editor.js` | Modify | `saveNewNode()` to include dimension_id |
| `tree_editor.js` | Add | Dimension switching logic |
| `tree_editor.css` | Add | Styles for dimension selector |
| `weight_editor.js` | Minor | No major changes (weights work per-node) |

---

## Detailed Changes: tree_editor.html

### 1. Add Dimension Selector After Header

Insert between `.tree-header` and `.tree-toolbar`:

```html
<!-- Dimension Selector (Multi-Dimensional Exams Only) -->
<div class="dimension-selector hidden" id="dimension-selector">
    <div class="dimension-selector-header">
        <span class="dimension-selector-label">Editing Dimension:</span>
        <span class="dimension-selector-help" title="Each dimension has its own hierarchy. Switch tabs to edit different dimensions.">ⓘ</span>
    </div>
    <div class="dimension-tabs" id="dimension-tabs">
        <!-- Tabs will be rendered dynamically -->
    </div>
</div>
```

### 2. Add Dimension Info Panel

Insert at the top of `.tree-content` or `.tree-panel`:

```html
<!-- Dimension Info (shown when dimension selected) -->
<div class="dimension-info hidden" id="dimension-info">
    <div class="dimension-info-header">
        <span class="dimension-info-icon">📂</span>
        <span class="dimension-info-name" id="dimension-info-name">Site of Care</span>
        <span class="dimension-info-badge" id="dimension-info-badge">Required</span>
    </div>
    <p class="dimension-info-description" id="dimension-info-description">
        Where the patient encounter occurs
    </p>
    <div class="dimension-info-stats" id="dimension-info-stats">
        <span class="dimension-stat"><strong>0</strong> subjects</span>
        <span class="dimension-stat"><strong>0%</strong> total weight</span>
    </div>
</div>
```

### 3. Add Dimension Help in Empty State

Modify `#tree-empty` to include dimension context:

```html
<!-- Empty State -->
<div class="tree-empty" id="tree-empty">
    <div class="tree-empty-icon">🌳</div>
    <h3 class="tree-empty-title">No Subjects Yet</h3>
    <p class="tree-empty-text" id="tree-empty-text">
        Build your exam's subject hierarchy to organize topics and assign weights.
    </p>
    <!-- Dimension-specific hint (shown for multi-dimensional exams) -->
    <p class="tree-empty-dimension-hint hidden" id="tree-empty-dimension-hint">
        You're editing the <strong id="empty-dimension-name">Site of Care</strong> dimension.
        Add subjects that represent options within this category.
    </p>
    <button class="btn btn-primary btn-lg" id="btn-add-first">
        Add Your First Subject
    </button>
</div>
```

### 4. Modify Add Node Modal

Add dimension context to modal (read-only, shows which dimension node will be added to):

```html
<!-- Add to modal, before form fields -->
<div class="modal-dimension-context hidden" id="modal-dimension-context">
    <span class="modal-dimension-label">Adding to dimension:</span>
    <span class="modal-dimension-name" id="modal-dimension-name">Site of Care</span>
</div>
```

### 5. Add Options Explanation Panel

Add a collapsible help section similar to the exam wizard:

```html
<!-- Dimension Options Help (shown for multi-dimensional exams) -->
<div class="dimension-options-help hidden" id="dimension-options-help">
    <button class="dimension-options-toggle" onclick="toggleDimensionOptionsHelp()">
        <span>💡 Understanding Dimensions</span>
        <span class="toggle-icon">▼</span>
    </button>
    <div class="dimension-options-content hidden" id="dimension-options-content">
        <p><strong>What are dimensions?</strong></p>
        <p>Dimensions are independent ways to categorize each question. For example, an NBME Shelf exam question might be categorized by:</p>
        <ul>
            <li><strong>Site of Care</strong> — Where (Emergency, Ambulatory, Inpatient)</li>
            <li><strong>Physician Task</strong> — What (Diagnosis, Treatment, Prevention)</li>
            <li><strong>System</strong> — Which organ system (Cardiovascular, Pulmonary, etc.)</li>
        </ul>
        <p>Each dimension has its own hierarchy that you build separately.</p>
        <hr>
        <p><strong>Dimension Options:</strong></p>
        <ul>
            <li><strong>Required</strong> — Every question must be tagged in this dimension.</li>
            <li><strong>Allow multiple</strong> — Questions can have multiple tags in this dimension (checkboxes vs radio buttons).</li>
        </ul>
    </div>
</div>
```

---

## Detailed Changes: tree_editor.js

### 1. Extend TreeState

```javascript
const TreeState = {
    // ... existing fields ...
    
    // NEW: Multi-dimensional support
    usesDimensions: false,       // Does this exam use multi-dimensional categorization?
    dimensions: [],              // Array of dimension objects
    currentDimensionId: null,    // Currently selected dimension ID
    currentDimension: null,      // Currently selected dimension object
    dimensionHierarchies: {},    // Cache: dimensionId -> { rootNodes, flatNodes }
};
```

### 2. Add Dimension Detection in `initializeTreeEditor()`

```javascript
async function initializeTreeEditor() {
    // ... existing code ...
    
    try {
        await api.ready();
        await loadExamContext();
        await loadHierarchyLevels();
        
        // NEW: Check if exam uses dimensions
        await checkDimensionSupport();
        
        if (TreeState.usesDimensions) {
            // Load dimensions and show selector
            await loadDimensions();
            renderDimensionSelector();
            
            // Select first dimension by default
            if (TreeState.dimensions.length > 0) {
                selectDimension(TreeState.dimensions[0].id);
            }
        } else {
            // Simple exam - load hierarchy normally
            await loadHierarchy();
        }
        
        setupEventListeners();
        console.log('✅ Tree editor initialized');
        
    } catch (error) {
        // ... existing error handling ...
    }
}
```

### 3. Add New Functions

```javascript
/**
 * Check if the current exam uses multi-dimensional categorization
 */
async function checkDimensionSupport() {
    try {
        const result = await api.examUsesDimensions(TreeState.examContextId);
        TreeState.usesDimensions = result.uses_dimensions;
        console.log(`📊 Exam uses dimensions: ${TreeState.usesDimensions}`);
    } catch (error) {
        console.warn('Could not check dimension support:', error);
        TreeState.usesDimensions = false;
    }
}

/**
 * Load all dimensions for the current exam
 */
async function loadDimensions() {
    try {
        TreeState.dimensions = await api.getDimensions(TreeState.examContextId);
        console.log(`📊 Loaded ${TreeState.dimensions.length} dimensions`);
    } catch (error) {
        console.error('Failed to load dimensions:', error);
        TreeState.dimensions = [];
    }
}

/**
 * Render the dimension selector tabs
 */
function renderDimensionSelector() {
    const selector = document.getElementById('dimension-selector');
    const tabsContainer = document.getElementById('dimension-tabs');
    
    if (!selector || !tabsContainer) return;
    
    if (!TreeState.usesDimensions || TreeState.dimensions.length === 0) {
        selector.classList.add('hidden');
        return;
    }
    
    selector.classList.remove('hidden');
    
    tabsContainer.innerHTML = TreeState.dimensions.map(dim => `
        <button class="dimension-tab ${dim.id === TreeState.currentDimensionId ? 'active' : ''}"
                data-dimension-id="${dim.id}"
                onclick="selectDimension(${dim.id})"
                title="${dim.description || dim.name}">
            <span class="dimension-tab-name">${escapeHtml(dim.name)}</span>
            ${dim.is_required ? '<span class="dimension-tab-badge">Required</span>' : ''}
        </button>
    `).join('');
}

/**
 * Select a dimension and load its hierarchy
 * @param {number} dimensionId - Dimension ID to select
 */
async function selectDimension(dimensionId) {
    const dimension = TreeState.dimensions.find(d => d.id === dimensionId);
    if (!dimension) return;
    
    TreeState.currentDimensionId = dimensionId;
    TreeState.currentDimension = dimension;
    
    // Update tab visual state
    document.querySelectorAll('.dimension-tab').forEach(tab => {
        tab.classList.toggle('active', parseInt(tab.dataset.dimensionId) === dimensionId);
    });
    
    // Update dimension info panel
    updateDimensionInfo(dimension);
    
    // Load hierarchy for this dimension
    await loadDimensionHierarchy(dimensionId);
    
    // Render the tree
    renderTree();
    updateStats();
    
    // Clear selection
    TreeState.selectedNodeId = null;
    showExamOverview();
    
    console.log(`📂 Selected dimension: ${dimension.name}`);
}

/**
 * Update the dimension info panel
 * @param {Object} dimension - The selected dimension
 */
function updateDimensionInfo(dimension) {
    const infoPanel = document.getElementById('dimension-info');
    const nameEl = document.getElementById('dimension-info-name');
    const badgeEl = document.getElementById('dimension-info-badge');
    const descEl = document.getElementById('dimension-info-description');
    
    if (!infoPanel) return;
    
    infoPanel.classList.remove('hidden');
    
    if (nameEl) nameEl.textContent = dimension.name;
    if (descEl) descEl.textContent = dimension.description || 'No description provided';
    
    if (badgeEl) {
        const badges = [];
        if (dimension.is_required) badges.push('Required');
        if (dimension.allow_multiple) badges.push('Multi-select');
        badgeEl.textContent = badges.join(' • ') || 'Optional';
        badgeEl.className = `dimension-info-badge ${dimension.is_required ? 'required' : 'optional'}`;
    }
    
    // Update empty state hint
    const emptyHint = document.getElementById('tree-empty-dimension-hint');
    const emptyDimName = document.getElementById('empty-dimension-name');
    if (emptyHint && emptyDimName) {
        emptyHint.classList.remove('hidden');
        emptyDimName.textContent = dimension.name;
    }
}

/**
 * Load hierarchy for a specific dimension
 * @param {number} dimensionId - Dimension ID
 */
async function loadDimensionHierarchy(dimensionId) {
    showLoading(true);
    
    try {
        // Check cache first
        if (TreeState.dimensionHierarchies[dimensionId]) {
            const cached = TreeState.dimensionHierarchies[dimensionId];
            TreeState.rootNodes = cached.rootNodes;
            TreeState.flatNodes = cached.flatNodes;
            showLoading(false);
            return;
        }
        
        // Fetch from API
        const hierarchy = await api.getDimensionHierarchy(TreeState.examContextId, dimensionId);
        
        TreeState.rootNodes = hierarchy?.root_nodes || [];
        buildFlatNodeMap();
        
        // Cache the result
        TreeState.dimensionHierarchies[dimensionId] = {
            rootNodes: TreeState.rootNodes,
            flatNodes: new Map(TreeState.flatNodes)
        };
        
    } catch (error) {
        console.error('Failed to load dimension hierarchy:', error);
        TreeState.rootNodes = [];
        TreeState.flatNodes = new Map();
    } finally {
        showLoading(false);
    }
}

/**
 * Invalidate the cache for a specific dimension
 * @param {number} dimensionId - Dimension ID to invalidate
 */
function invalidateDimensionCache(dimensionId) {
    delete TreeState.dimensionHierarchies[dimensionId];
}
```

### 4. Modify `loadHierarchy()`

Update to handle both simple and multi-dimensional exams:

```javascript
async function loadHierarchy() {
    // For multi-dimensional exams, use dimension-specific loading
    if (TreeState.usesDimensions && TreeState.currentDimensionId) {
        await loadDimensionHierarchy(TreeState.currentDimensionId);
        renderTree();
        updateStats();
        return;
    }
    
    // Original simple exam logic
    showLoading(true);
    
    try {
        const hierarchy = await api.getSubjectHierarchy(TreeState.examContextId);
        TreeState.rootNodes = hierarchy?.root_nodes || [];
        buildFlatNodeMap();
        renderTree();
        updateStats();
        
        if (!TreeState.selectedNodeId) {
            showExamOverview();
        }
    } catch (error) {
        console.log('Hierarchy not yet available:', error);
        TreeState.rootNodes = [];
        renderTree();
        showExamOverview();
    } finally {
        showLoading(false);
    }
}
```

### 5. Modify `showAddNodeModal()`

Add dimension context:

```javascript
function showAddNodeModal(parentId = null) {
    addNodeParentId = parentId;
    
    // ... existing code ...
    
    // NEW: Show dimension context for multi-dimensional exams
    const dimensionContext = document.getElementById('modal-dimension-context');
    const dimensionName = document.getElementById('modal-dimension-name');
    
    if (TreeState.usesDimensions && TreeState.currentDimension) {
        if (dimensionContext) {
            dimensionContext.classList.remove('hidden');
        }
        if (dimensionName) {
            dimensionName.textContent = TreeState.currentDimension.name;
        }
    } else {
        if (dimensionContext) {
            dimensionContext.classList.add('hidden');
        }
    }
    
    // ... rest of existing code ...
}
```

### 6. Modify `saveNewNode()`

Include dimension_id when creating nodes:

```javascript
async function saveNewNode() {
    const name = document.getElementById('modal-node-name').value.trim();
    const levelType = document.getElementById('modal-node-level').value;
    
    // ... existing weight handling code ...
    
    if (!name) {
        Toast.warning('Required', 'Please enter a subject name');
        return;
    }
    
    try {
        const nodeData = {
            exam_context_id: TreeState.examContextId,
            name: name,
            level_type: levelType,
            parent_id: addNodeParentId
        };
        
        // NEW: Add dimension_id for multi-dimensional exams
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            nodeData.dimension_id = TreeState.currentDimensionId;
        }
        
        // ... rest of existing weight handling code ...
        
        let result;
        if (TreeState.usesDimensions && nodeData.dimension_id) {
            // Use dimension-aware creation method
            result = await api.createSubjectNodeWithDimension(nodeData);
        } else if (nodeData.exam_weight_low !== undefined || nodeData.relative_weight !== undefined) {
            result = await api.createSubjectNodeWithWeight(nodeData);
        } else {
            nodeData.weight = simpleWeight || 0;
            result = await api.createSubjectNode(nodeData);
        }
        
        Toast.success('Created', `Added "${name}"`);
        hideAddNodeModal();
        
        // Invalidate cache and reload
        if (TreeState.usesDimensions) {
            invalidateDimensionCache(TreeState.currentDimensionId);
        }
        
        await loadHierarchy();
        
        // ... rest of existing code ...
        
    } catch (error) {
        Toast.error('Error', error.message);
    }
}
```

### 7. Add Global Exports

```javascript
// Add to existing global exports
window.selectDimension = selectDimension;
window.toggleDimensionOptionsHelp = toggleDimensionOptionsHelp;
```

---

## Detailed Changes: weight_editor.js

### Minimal Changes Required

The weight editor works on individual nodes regardless of dimension. The only change needed is to ensure the siblings calculation respects dimension boundaries (siblings must be in the same dimension).

```javascript
/**
 * Get siblings of a node (nodes with the same parent)
 * For multi-dimensional exams, siblings must be in the same dimension
 * @param {Object} node - The current node
 * @returns {Array} Array of sibling nodes including the current node
 */
function getSiblings(node) {
    let siblings;
    
    if (node._parent) {
        siblings = node._parent.children || [];
    } else {
        // Root nodes - for multi-dimensional exams, filter by current dimension
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            siblings = TreeState.rootNodes.filter(n => 
                n.dimension_id === TreeState.currentDimensionId
            );
        } else {
            siblings = TreeState.rootNodes;
        }
    }
    
    return siblings.map(s => ({
        id: s.id,
        name: s.name,
        weight: s.relative_weight ?? s.exam_weight_low ?? s.weight ?? 0,
        isCurrent: s.id === node.id,
        isLocked: s.weight_locked || false,
        weightSource: s.weight_source || 'user_defined'
    }));
}
```

---

## New CSS Requirements

Create or add to `src/web/css/tree.css`:

```css
/* =========================================================================
   Dimension Selector
   ========================================================================= */

.dimension-selector {
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    padding: var(--space-sm) var(--space-lg);
}

.dimension-selector.hidden {
    display: none;
}

.dimension-selector-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-sm);
}

.dimension-selector-label {
    font-size: 0.875rem;
    color: var(--text-secondary);
    font-weight: 500;
}

.dimension-selector-help {
    color: var(--text-tertiary);
    cursor: help;
    font-size: 0.875rem;
}

.dimension-tabs {
    display: flex;
    gap: var(--space-xs);
    flex-wrap: wrap;
}

.dimension-tab {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-sm) var(--space-md);
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: all 0.15s ease;
    font-size: 0.9rem;
}

.dimension-tab:hover {
    background: var(--bg-hover);
    border-color: var(--primary-color);
}

.dimension-tab.active {
    background: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
}

.dimension-tab-name {
    font-weight: 500;
}

.dimension-tab-badge {
    font-size: 0.7rem;
    padding: 2px 6px;
    background: rgba(255, 255, 255, 0.2);
    border-radius: var(--radius-sm);
    text-transform: uppercase;
}

.dimension-tab.active .dimension-tab-badge {
    background: rgba(255, 255, 255, 0.3);
}

/* =========================================================================
   Dimension Info Panel
   ========================================================================= */

.dimension-info {
    background: var(--bg-secondary);
    border-radius: var(--radius-md);
    padding: var(--space-md);
    margin-bottom: var(--space-md);
}

.dimension-info.hidden {
    display: none;
}

.dimension-info-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-xs);
}

.dimension-info-icon {
    font-size: 1.25rem;
}

.dimension-info-name {
    font-weight: 600;
    font-size: 1.1rem;
}

.dimension-info-badge {
    font-size: 0.75rem;
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    background: var(--success-bg);
    color: var(--success-color);
}

.dimension-info-badge.optional {
    background: var(--bg-tertiary);
    color: var(--text-secondary);
}

.dimension-info-description {
    font-size: 0.9rem;
    color: var(--text-secondary);
    margin: 0 0 var(--space-sm) 0;
}

.dimension-info-stats {
    display: flex;
    gap: var(--space-lg);
    font-size: 0.875rem;
    color: var(--text-tertiary);
}

/* =========================================================================
   Dimension Options Help
   ========================================================================= */

.dimension-options-help {
    margin: var(--space-md) 0;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    overflow: hidden;
}

.dimension-options-help.hidden {
    display: none;
}

.dimension-options-toggle {
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-sm) var(--space-md);
    background: var(--bg-secondary);
    border: none;
    cursor: pointer;
    font-size: 0.9rem;
    font-weight: 500;
}

.dimension-options-toggle:hover {
    background: var(--bg-hover);
}

.dimension-options-content {
    padding: var(--space-md);
    background: var(--bg-primary);
    font-size: 0.9rem;
    line-height: 1.6;
}

.dimension-options-content.hidden {
    display: none;
}

.dimension-options-content ul {
    margin: var(--space-sm) 0;
    padding-left: var(--space-lg);
}

.dimension-options-content li {
    margin-bottom: var(--space-xs);
}

.dimension-options-content hr {
    margin: var(--space-md) 0;
    border: none;
    border-top: 1px solid var(--border-color);
}

/* =========================================================================
   Modal Dimension Context
   ========================================================================= */

.modal-dimension-context {
    background: var(--bg-secondary);
    padding: var(--space-sm) var(--space-md);
    border-radius: var(--radius-sm);
    margin-bottom: var(--space-md);
    font-size: 0.9rem;
}

.modal-dimension-context.hidden {
    display: none;
}

.modal-dimension-label {
    color: var(--text-secondary);
}

.modal-dimension-name {
    font-weight: 600;
    color: var(--primary-color);
}

/* =========================================================================
   Empty State - Dimension Hint
   ========================================================================= */

.tree-empty-dimension-hint {
    font-size: 0.9rem;
    color: var(--text-secondary);
    margin-top: var(--space-sm);
}

.tree-empty-dimension-hint.hidden {
    display: none;
}
```

---

## API Methods Required

These methods should already exist from the earlier bridge implementation:

| Method | Purpose | Status |
|--------|---------|--------|
| `api.examUsesDimensions(examContextId)` | Check if exam uses dimensions | ✅ Implemented |
| `api.getDimensions(examContextId)` | Get all dimensions for exam | ✅ Implemented |
| `api.getDimensionHierarchy(examContextId, dimensionId)` | Get hierarchy for specific dimension | ✅ Implemented |
| `api.createSubjectNodeWithDimension(nodeData)` | Create node with dimension_id | ✅ Implemented |

---

## Implementation Order

### Day 1: HTML Structure
1. Add dimension selector markup to tree_editor.html
2. Add dimension info panel markup
3. Add dimension context to modal
4. Add help panel markup

### Day 2: JavaScript - State & Detection
1. Extend TreeState with dimension fields
2. Add `checkDimensionSupport()` function
3. Add `loadDimensions()` function
4. Modify `initializeTreeEditor()` to check dimensions

### Day 3: JavaScript - Dimension Switching
1. Add `renderDimensionSelector()` function
2. Add `selectDimension()` function
3. Add `updateDimensionInfo()` function
4. Add `loadDimensionHierarchy()` function with caching

### Day 4: JavaScript - Node Operations
1. Modify `showAddNodeModal()` for dimension context
2. Modify `saveNewNode()` to include dimension_id
3. Add cache invalidation on node changes
4. Test create/edit/delete within dimensions

### Day 5: CSS & Polish
1. Add all CSS styles
2. Test responsive behavior
3. Test with real multi-dimensional exam
4. Fix edge cases

---

## Testing Checklist

### Setup
- [ ] Create a multi-dimensional exam with 3 dimensions (Site, Task, System)
- [ ] Create a simple exam without dimensions

### Multi-Dimensional Exam Tests
- [ ] Opening tree editor shows dimension selector
- [ ] First dimension is selected by default
- [ ] Clicking dimension tab switches to that dimension
- [ ] Tree shows only nodes for selected dimension
- [ ] Empty state shows dimension-specific hint
- [ ] Adding root node saves with correct dimension_id
- [ ] Adding child node saves with correct dimension_id
- [ ] Switching dimensions loads correct hierarchy
- [ ] Cache works (second visit to dimension loads faster)
- [ ] Modifying node invalidates cache
- [ ] Dimension info panel shows correct details
- [ ] "Required" badge shows for required dimensions
- [ ] "Multi-select" badge shows for allow_multiple dimensions

### Simple Exam Tests
- [ ] Opening tree editor hides dimension selector
- [ ] Tree works as before (no regression)
- [ ] Creating/editing nodes works normally

### Edge Cases
- [ ] Exam with 1 dimension still shows selector
- [ ] Empty dimension shows helpful empty state
- [ ] Rapid dimension switching doesn't cause issues
- [ ] Node operations update stats correctly per dimension

---

## Notes for Implementation

### Key Principles

1. **Don't break simple exams** - All changes should be conditional on `TreeState.usesDimensions`
2. **Clear visual feedback** - User should always know which dimension they're editing
3. **Efficient caching** - Don't re-fetch dimension hierarchies unnecessarily
4. **Consistent patterns** - Follow existing code style in tree_editor.js

### Gotchas to Watch For

1. **Root node siblings** - When calculating sibling weights, root nodes must be filtered by dimension
2. **Cache invalidation** - Any node change must invalidate the cache for that dimension
3. **Modal state** - Ensure dimension context is cleared when modal is closed
4. **Overview stats** - Stats should reflect the current dimension, not all dimensions

---

**Document Version:** 1.0  
**Created:** January 16, 2026  
**Author:** Claude (AI Assistant)
