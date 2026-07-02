# Phase 3: Subject Hierarchy Editor & Outline Building

**Document Version:** 1.5  
**Created:** December 26, 2025  
**Last Updated:** December 26, 2025  
**Status:** ✅ ALL STAGES COMPLETE

---

## Table of Contents

1. [Phase 3 Overview](#phase-3-overview)
2. [Prerequisites](#prerequisites)
3. [Implementation Stages](#implementation-stages)
4. [Stage 1: Landing Page Enhancement](#stage-1-landing-page-enhancement)
5. [Stage 2: Subject Tree Editor](#stage-2-subject-tree-editor)
6. [Stage 3: Weight Editing Interface](#stage-3-weight-editing-interface)
7. [Stage 4: Import/Export Functionality](#stage-4-importexport-functionality)
8. [Stage 5: Testing & Polish](#stage-5-testing--polish)
9. [UI/UX Specifications](#uiux-specifications)
10. [API Requirements](#api-requirements)
11. [Timeline Estimate](#timeline-estimate)
12. [Success Criteria](#success-criteria)

---

## Phase 3 Overview

### Goals

Phase 3 focuses on **Subject Hierarchy Management** - enabling users to build, edit, and visualize their exam subject outlines. This is the core functionality that allows students to organize their study topics with weighted importance.

### Key Features

| Feature | Description | Priority |
|---------|-------------|----------|
| **Landing Page** | Display existing exams, create new, edit, delete | High |
| **Tree View Editor** | Visual hierarchical editor for subject nodes | High |
| **Node CRUD Operations** | Add, edit, rename, delete subject nodes | High |
| **Weight Editor** | Edit weights with real-time sibling balancing | High |
| **Drag & Drop** | Reorder and reparent nodes via drag-and-drop | Medium |
| **Import/Export** | JSON import/export for subject hierarchies | Medium |
| **Search & Filter** | Find nodes within large hierarchies | Low |
| **Bulk Operations** | Multi-select for bulk delete/move | Low |

### User Stories

1. **As a student**, I want to see all my exams on the landing page so I can choose which one to work on.
2. **As a student**, I want to create a subject hierarchy that matches my exam's content outline.
3. **As a student**, I want to assign weights to topics based on their exam importance.
4. **As a student**, I want the system to automatically balance sibling weights when I edit one.
5. **As a student**, I want to import a pre-made outline so I don't have to build from scratch.
6. **As a student**, I want to export my outline to share with classmates or back up my work.

---

## Prerequisites

### Completed in Phase 2 ✅

- [x] Database schema with `exam_contexts`, `hierarchy_level_definitions`, `subject_node_weights`
- [x] `UserDatabase` class with exam context CRUD methods
- [x] `UserDatabase` class with weight balancing algorithms
- [x] PyQt6 main window with QWebEngineView
- [x] Python-JavaScript bridge via WebChannel
- [x] JavaScript API wrapper (`api.js`)
- [x] Exam Setup Wizard
- [x] Base CSS design system with custom components

### Required Before Starting Phase 3

- [x] All Phase 2 bugs fixed
- [x] Exam creation working end-to-end
- [x] Database has at least one test exam context

---

## Implementation Stages

```
Stage 1: Landing Page Enhancement
    ↓
Stage 2: Subject Tree Editor (Core)
    ↓
Stage 3: Weight Editing Interface
    ↓
Stage 4: Import/Export Functionality
    ↓
Stage 5: Testing & Polish
```

---

## Stage 1: Landing Page Enhancement ✅ COMPLETE

**Duration:** 4-6 hours

### 1.1 Landing Page Features

The landing page (`index.html`) needs to display:

1. **Welcome Header** - App branding and user greeting
2. **Exam Cards Grid** - Visual cards for each exam context
3. **Create New Button** - Link to exam wizard
4. **Empty State** - Friendly message when no exams exist

### 1.2 Exam Card Design

Each exam card displays:

```
┌─────────────────────────────────────┐
│  📚 USMLE Step 1                    │
│                                     │
│  Medical licensing exam preparation │
│                                     │
│  📅 Exam Date: June 15, 2026       │
│  📊 Subjects: 12 topics            │
│  ⚖️  Weights: Configured           │
│                                     │
│  [Open]  [Edit]  [Delete]          │
└─────────────────────────────────────┘
```

### 1.3 Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/web/html/index.html` | Modify | Add exam cards grid, empty state |
| `src/web/css/landing.css` | Create | Landing page specific styles |
| `src/web/js/landing.js` | Create | Load exams, handle card actions |
| `src/app/bridge.py` | Modify | Add `getAllExamContexts`, `deleteExamContext` |
| `src/web/js/api.js` | Modify | Add corresponding API methods |

### 1.4 Bridge Methods Required

```python
@pyqtSlot(bool, result=str)
def getAllExamContexts(self, active_only: bool) -> str:
    """Get all exam contexts for the current user"""
    
@pyqtSlot(int, result=str)
def deleteExamContext(self, exam_context_id: int) -> str:
    """Soft-delete an exam context"""
    
@pyqtSlot(int, result=str)
def getExamContextStats(self, exam_context_id: int) -> str:
    """Get statistics (subject count, etc.) for an exam"""
```

### 1.5 Acceptance Criteria ✅ COMPLETE

- [x] Landing page loads and displays all exam contexts
- [x] Empty state shown when no exams exist
- [x] "Create New Exam" button opens wizard
- [x] Exam cards show name, description, date, stats
- [x] "Open" button navigates to tree editor
- [x] "Edit" button opens wizard in edit mode with pre-filled data
- [x] "Delete" button shows confirmation, then soft-deletes
- [x] Cards update after creating new exam
- [x] Global function exposure for onclick handlers (Bug Fix #1)

---

## Stage 1.5: Bug Fixes & Enhancements ✅ COMPLETE

**Duration:** 1-2 hours

### Bug Fixes Applied

| Issue | Problem | Solution | File(s) Modified |
|-------|---------|----------|------------------|
| Delete Button | `onclick` handlers couldn't access functions | Added `window.` global assignments | `landing.js` |
| Node Click Expand | Users had to click small caret to expand | Modified `selectNode()` to expand on click | `tree_editor.js` |
| Empty Details Panel | "Select a node" shown when nothing selected | Added `showExamOverview()` with pie chart | `tree_editor.js`, `tree.css` |
| Edit Exam Pre-fill | Wizard opened with empty fields | Added edit mode detection and data loading | `exam_wizard.js` |

### New Features Added

1. **Exam Overview Panel** - Shows when no node is selected:
   - Total subjects count
   - Root topics count  
   - Total weight percentage
   - Subjects by level breakdown
   - Interactive pie chart for root-level weight distribution
   - Clickable legend items that select nodes

2. **Edit Mode for Wizard** - Pre-fills existing exam data:
   - Detects `?edit=ID` URL parameter
   - Loads exam via `api.getExamContext()`
   - Populates all form fields
   - Changes button text to "Save Changes"
   - Calls `updateExamContextSettings()` on save

3. **Click-to-Expand Behavior** (Option D):
   - Single click selects AND expands nodes with children
   - Clicking same node again toggles expand/collapse
   - More intuitive file explorer-like behavior

---

## Stage 2: Subject Tree Editor ✅ COMPLETE

**Duration:** 8-12 hours

### 2.1 Tree Editor Layout

```
┌──────────────────────────────────────────────────────────────┐
│  ← Back to Exams    USMLE Step 1 - Subject Hierarchy    [⋮] │
├──────────────────────────────────────────────────────────────┤
│  [+ Add Root]  [Import]  [Export]  [Expand All] [Collapse]  │
├────────────────────────────────┬─────────────────────────────┤
│                                │                             │
│  📁 Cardiovascular (25%)       │  SELECTED NODE DETAILS      │
│    📁 Anatomy (40%)            │                             │
│      📄 Heart Chambers (50%)   │  Name: Heart Chambers       │
│      📄 Blood Vessels (50%)    │  Level: Topic               │
│    📁 Physiology (35%)         │  Weight: 50%                │
│    📁 Pathology (25%)          │  Parent: Anatomy            │
│  📁 Respiratory (20%)          │                             │
│    📄 ...                      │  [Rename] [Delete]          │
│  📁 Renal (15%)                │                             │
│  📁 GI (15%)                   │  ──────────────────────     │
│  📁 Neurology (25%)            │  CHILDREN                   │
│                                │  [+ Add Child]              │
│                                │                             │
└────────────────────────────────┴─────────────────────────────┘
```

### 2.2 Tree Node Structure

Each tree node displays:

- **Expand/Collapse Icon** - For nodes with children
- **Level Icon** - Folder (has children) or document (leaf)
- **Node Name** - Editable on double-click
- **Weight Badge** - Shows relative weight percentage
- **Action Buttons** - Add child, delete (on hover)

### 2.3 Tree Interactions

| Interaction | Action |
|-------------|--------|
| Single Click | Select node, show details panel |
| Double Click | Inline rename |
| Right Click | Context menu (add child, delete, copy, cut, paste) |
| Drag Node | Reorder or reparent |
| Click Expand | Toggle children visibility |
| Hover | Show quick action buttons |

### 2.4 Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/web/html/tree_editor.html` | Create | Tree editor page |
| `src/web/css/tree.css` | Create | Tree-specific styles |
| `src/web/js/tree_editor.js` | Create | Tree rendering, interactions |
| `src/web/js/tree_node.js` | Create | TreeNode class |
| `src/app/bridge.py` | Modify | Add subject node CRUD methods |
| `src/web/js/api.js` | Modify | Add subject node API methods |

### 2.5 Bridge Methods Required

```python
@pyqtSlot(int, result=str)
def getSubjectHierarchy(self, exam_context_id: int) -> str:
    """Get full subject hierarchy as nested JSON"""

@pyqtSlot(str, result=str)
def createSubjectNode(self, node_data_json: str) -> str:
    """Create a new subject node"""

@pyqtSlot(int, str, result=str)
def updateSubjectNode(self, node_id: int, updates_json: str) -> str:
    """Update subject node (name, sort_order, etc.)"""

@pyqtSlot(int, result=str)
def deleteSubjectNode(self, node_id: int) -> str:
    """Delete a subject node and its children"""

@pyqtSlot(int, int, int, result=str)
def moveSubjectNode(self, node_id: int, new_parent_id: int, new_sort_order: int) -> str:
    """Move node to new parent or reorder within siblings"""
```

### 2.6 Tree Data Structure (JSON)

```json
{
  "exam_context_id": 1,
  "exam_name": "USMLE Step 1",
  "root_nodes": [
    {
      "id": 1,
      "name": "Cardiovascular",
      "level_type": "System",
      "level_order": 1,
      "weight": 25.0,
      "sort_order": 1,
      "children": [
        {
          "id": 2,
          "name": "Anatomy",
          "level_type": "Subsystem",
          "level_order": 2,
          "weight": 40.0,
          "sort_order": 1,
          "children": [
            {
              "id": 5,
              "name": "Heart Chambers",
              "level_type": "Topic",
              "level_order": 3,
              "weight": 50.0,
              "sort_order": 1,
              "children": []
            }
          ]
        }
      ]
    }
  ]
}
```

### 2.7 Acceptance Criteria ✅ COMPLETE

- [x] Tree editor page loads with exam context
- [x] Full hierarchy renders as expandable tree
- [x] Nodes display name, weight, level icon
- [x] Single click selects node, shows details panel, AND expands if has children
- [x] Double click enables inline rename
- [x] "Add Root" creates top-level node
- [x] "Add Child" creates child under selected node
- [x] Delete removes node (with confirmation for nodes with children)
- [x] Expand/collapse works correctly
- [x] "Expand All" and "Collapse All" buttons work
- [x] Back button returns to landing page
- [x] Tree state persists (expanded nodes) during session
- [x] Exam overview with pie chart shown when no node selected
- [x] Global function exposure for onclick handlers

---

## Stage 3: Weight Editing Interface ✅ COMPLETE

**Duration:** 6-8 hours

### 3.1 Weight Editor Design

The weight editor appears in the details panel when a node is selected:

```
┌─────────────────────────────────┐
│  WEIGHT SETTINGS                │
├─────────────────────────────────┤
│                                 │
│  Current Weight: [====|---] 40% │
│                                 │
│  Sibling Weights:               │
│  ├─ Anatomy      40%  ████░░░░  │
│  ├─ Physiology   35%  ███░░░░░  │
│  └─ Pathology    25%  ██░░░░░░  │
│                       ─────────  │
│                       Total: 100%│
│                                 │
│  [Apply]  [Reset]               │
└─────────────────────────────────┘
```

### 3.2 Weight Editor Features

1. **Slider Control** - Drag to adjust weight (respects precision setting)
2. **Number Input** - Direct entry with validation
3. **Sibling Visualization** - Bar chart showing all siblings
4. **Real-time Preview** - Shows how siblings will be affected
5. **Auto-balance Indicator** - Shows algorithm being used
6. **Total Validation** - Warns if total ≠ 100%

### 3.3 Weight Update Flow

```
User Adjusts Slider
        ↓
Preview: Calculate new sibling weights (no DB write)
        ↓
User Clicks "Apply"
        ↓
API Call: updateSubjectNodeWeight()
        ↓
Backend: Update node + auto-balance siblings
        ↓
Response: Updated node + affected siblings
        ↓
UI: Refresh tree with new weights
```

### 3.4 Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/web/js/weight_editor.js` | Create | Weight editor component |
| `src/web/css/weight.css` | Create | Weight editor styles |
| `src/web/js/tree_editor.js` | Modify | Integrate weight editor |

### 3.5 Files Created in Stage 3

| File | Purpose | Lines |
|------|---------|-------|
| `src/web/css/weight.css` | Enhanced weight editor styling | ~450 |
| `src/web/js/weight_editor.js` | Weight editor module with preview | ~775 |

### 3.6 Enhanced Features Implemented

1. **Enhanced Weight Display** - Large value, delta indicator, precision badge
2. **Improved Slider** - Precision-aware, visual markers, preview mode styling
3. **Algorithm Info** - Shows balancing algorithm and description
4. **Enhanced Siblings Preview** - Grid layout, current vs preview bars, change indicators
5. **Total Validation** - Color-coded totals, validation messages
6. **Weight History** - Collapsible history section with change details
7. **Action Buttons** - Apply/Reset with loading states

### 3.7 Acceptance Criteria ✅ COMPLETE

- [x] Weight slider appears for selected node
- [x] Slider respects precision setting (0, 1, or 2 decimals)
- [x] Sibling weights shown as visual bars
- [x] Preview shows expected sibling changes before apply
- [x] "Apply" saves to database and refreshes tree
- [x] "Reset" reverts to last saved value
- [x] Weight history displayed (via collapsible section)
- [x] Total validation shows warning if ≠ 100%
- [x] Works with both proportional and even algorithms

---

## Stage 4: Import/Export Functionality ✅ COMPLETE

**Duration:** 4-6 hours

### 4.1 Export Feature

Export entire subject hierarchy as JSON file:

```javascript
// Export button click
async function exportHierarchy() {
    const data = await api.getSubjectHierarchy(examContextId);
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = `${examName}_hierarchy.json`;
    a.click();
}
```

### 4.2 Import Feature

Import hierarchy from JSON file:

1. User clicks "Import"
2. File picker opens (accept `.json`)
3. File parsed and validated
4. Preview shown with node count
5. User confirms import
6. Nodes created in database
7. Tree refreshes

### 4.3 Import Validation

```javascript
function validateImportData(data) {
    const errors = [];
    
    // Check required fields
    if (!data.root_nodes || !Array.isArray(data.root_nodes)) {
        errors.push('Missing root_nodes array');
    }
    
    // Validate each node recursively
    function validateNode(node, path) {
        if (!node.name) errors.push(`Missing name at ${path}`);
        if (node.weight < 0 || node.weight > 100) {
            errors.push(`Invalid weight at ${path}`);
        }
        if (node.children) {
            node.children.forEach((child, i) => {
                validateNode(child, `${path}.children[${i}]`);
            });
        }
    }
    
    data.root_nodes.forEach((node, i) => {
        validateNode(node, `root_nodes[${i}]`);
    });
    
    return errors;
}
```

### 4.4 Bridge Methods Required

```python
@pyqtSlot(int, str, result=str)
def importSubjectHierarchy(self, exam_context_id: int, hierarchy_json: str) -> str:
    """Import subject hierarchy from JSON, replacing existing"""

@pyqtSlot(int, result=str)
def exportSubjectHierarchy(self, exam_context_id: int) -> str:
    """Export subject hierarchy as JSON"""
```

### 4.5 Files Created in Stage 4

| File | Purpose | Lines |
|------|---------|-------|
| `src/web/js/import_export.js` | Import/export module with preview and validation | ~550 |
| `src/web/css/import_export.css` | Import/export modal styling | ~320 |

### 4.6 Enhanced Features Implemented

1. **Enhanced Export** - Includes metadata, formatted JSON, smart filename
2. **Import Preview Modal** - Shows file info, metadata, preview tree, warnings
3. **Validation System** - Comprehensive validation with errors and warnings
4. **Import Modes** - Merge (add to existing) or Replace (delete and import)
5. **Error Handling** - Error modal for critical validation failures
6. **Keyboard Support** - Escape key closes modals

### 4.7 Acceptance Criteria ✅ COMPLETE

- [x] "Export" downloads JSON file with full hierarchy
- [x] Export includes metadata (timestamp, source, exam info)
- [x] "Import" opens file picker for JSON files
- [x] Invalid JSON shows error message
- [x] Valid JSON shows preview with node count
- [x] Preview shows visual tree of subjects
- [x] User can cancel import after preview
- [x] Import mode: "Merge" adds to existing
- [x] Import mode: "Replace" removes existing first
- [x] Validation warnings shown but don't block import
- [x] Critical errors prevent import with error modal
- [x] Tree refreshes after successful import

---

## Stage 5: Testing & Polish ✅ COMPLETE

**Duration:** 4-6 hours

### 5.1 Testing Completed

#### Bridge Tests Created (`tests/app/test_bridge.py`)

| Test Class | Tests | Coverage |
|------------|-------|----------|
| `TestSerializeResponse` | 3 | JSON response formatting |
| `TestBridgeConnection` | 3 | Connection status checks |
| `TestExamContextBridge` | 10 | Exam CRUD operations |
| `TestHierarchyLevelsBridge` | 2 | Hierarchy level management |
| `TestSubjectNodeBridge` | 6 | Subject node CRUD |
| `TestWeightManagementBridge` | 2 | Weight updates, history |
| `TestImportExportBridge` | 2 | Import/export operations |
| `TestBridgeErrorHandling` | 4 | Error cases |
| `TestBridgeIntegration` | 1 | Complete workflow |

**Total: 33 test cases**

#### Test Infrastructure

- Created root `conftest.py` for pytest path configuration
- Fixed all import path inconsistencies (`from database import ...`)
- Updated legacy schema tests for current database structure
- Created manual test checklist (`docs/testing/PHASE3_MANUAL_TEST_CHECKLIST.md`)

#### Final Test Results

```
=================== test session starts ===================
collected 259 items

256 passed, 3 skipped in 17.50s

Coverage: 83.43%
```

### 5.2 Bug Fixes Applied

| Bug | Problem | Solution |
|-----|---------|----------|
| Delete constraint | `status='deleted'` not in CHECK constraint | Changed to `status='archived'` |
| Null element error | Weight elements may be null | Added null checks |
| Import format | Only accepted "root_nodes" key | Now accepts both "subjects" and "root_nodes" |

### 5.3 Polish Items Status

- [x] Loading states during API calls (implemented in weight editor)
- [x] Error messages with toast notifications
- [x] Empty state when no subjects exist (shows exam overview)
- [x] Escape key closes modals
- [ ] Arrow key navigation (future enhancement)
- [ ] Undo/redo (stretch goal - not implemented)
- [x] Tooltips on weight badges
- [x] Responsive layout basics

---

## UI/UX Specifications

### Color Scheme (from existing design system)

```css
/* Node level colors */
--level-1-color: #2563eb;  /* System - Blue */
--level-2-color: #7c3aed;  /* Subsystem - Purple */
--level-3-color: #059669;  /* Topic - Green */
--level-4-color: #d97706;  /* Subtopic - Amber */
--level-5-color: #dc2626;  /* Child - Red */
```

### Tree Node Spacing

```css
.tree-node {
    padding: 8px 12px;
    margin-left: 24px;  /* Per level indent */
    border-radius: 6px;
}

.tree-node:hover {
    background: var(--bg-tertiary);
}

.tree-node.selected {
    background: var(--color-primary-bg);
    border-left: 3px solid var(--color-primary);
}
```

### Weight Badge Styles

```css
.weight-badge {
    display: inline-flex;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 500;
    border-radius: 12px;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
}

.weight-badge.high {  /* >30% */
    background: var(--color-success-bg);
    color: var(--color-success);
}

.weight-badge.low {  /* <10% */
    background: var(--color-warning-bg);
    color: var(--color-warning);
}
```

---

## API Requirements

### New Bridge Methods Summary

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `getAllExamContexts` | `active_only: bool` | List of exam contexts | Landing page |
| `deleteExamContext` | `exam_context_id: int` | Success/error | Soft delete |
| `getExamContextStats` | `exam_context_id: int` | Stats object | Card stats |
| `getSubjectHierarchy` | `exam_context_id: int` | Nested tree JSON | Tree editor |
| `createSubjectNode` | `node_data: json` | Created node | Add node |
| `updateSubjectNode` | `node_id, updates: json` | Updated node | Edit node |
| `deleteSubjectNode` | `node_id: int` | Success/error | Delete node |
| `moveSubjectNode` | `node_id, parent_id, sort` | Updated node | Drag-drop |
| `importSubjectHierarchy` | `exam_id, json` | Import result | Import |
| `exportSubjectHierarchy` | `exam_id: int` | Full hierarchy JSON | Export |

### JavaScript API Methods

```javascript
// api.js additions

async getAllExamContexts(activeOnly = true) { }
async deleteExamContext(examContextId) { }
async getExamContextStats(examContextId) { }
async getSubjectHierarchy(examContextId) { }
async createSubjectNode(nodeData) { }
async updateSubjectNode(nodeId, updates) { }
async deleteSubjectNode(nodeId) { }
async moveSubjectNode(nodeId, newParentId, newSortOrder) { }
async importSubjectHierarchy(examContextId, hierarchyJson) { }
async exportSubjectHierarchy(examContextId) { }
```

---

## Timeline Estimate

### Optimistic Timeline (Full-time Development)

| Stage | Duration | Cumulative |
|-------|----------|------------|
| Stage 1: Landing Page | 4-6 hours | 4-6 hours |
| Stage 2: Tree Editor | 8-12 hours | 12-18 hours |
| Stage 3: Weight Editor | 6-8 hours | 18-26 hours |
| Stage 4: Import/Export | 4-6 hours | 22-32 hours |
| Stage 5: Testing & Polish | 4-6 hours | 26-38 hours |
| **Total** | **26-38 hours** | **~4-6 days** |

### Realistic Timeline (Part-time Development)

- **3-4 weeks** at 10-15 hours per week
- Includes debugging, iteration, and polish

### Suggested Order of Implementation

1. **Day 1-2:** Stage 1 (Landing Page)
2. **Day 3-5:** Stage 2 (Tree Editor Core)
3. **Day 6-7:** Stage 3 (Weight Editor)
4. **Day 8:** Stage 4 (Import/Export)
5. **Day 9-10:** Stage 5 (Testing & Polish)

---

## Success Criteria

Phase 3 is complete when:

### Must Have ✅ ALL COMPLETE

- [x] Landing page displays all exam contexts as cards
- [x] Users can create, edit, delete exam contexts
- [x] Tree editor renders full subject hierarchy
- [x] Users can add, rename, delete subject nodes
- [x] Users can add child nodes at any level
- [x] Weight editing works with auto-balancing
- [x] Weight changes reflect immediately in tree
- [x] Export downloads valid JSON file
- [x] Import creates nodes from JSON file

### Should Have ✅ MOSTLY COMPLETE

- [ ] Drag-and-drop reordering within siblings (future)
- [x] Expand/collapse all buttons
- [x] Details panel shows node information
- [x] Weight visualization with bar chart
- [ ] Full keyboard navigation (partial - Escape works)

### Nice to Have ✅ PARTIALLY COMPLETE

- [ ] Drag-and-drop reparenting (future)
- [ ] Undo/redo functionality (stretch goal)
- [ ] Search within hierarchy (future)
- [ ] Bulk select and delete (future)
- [x] Import merge (vs replace) option

---

## Files Created/Modified Summary

### New Files

| File | Purpose |
|------|---------|
| `src/web/html/tree_editor.html` | Tree editor page |
| `src/web/css/landing.css` | Landing page styles |
| `src/web/css/tree.css` | Tree editor styles |
| `src/web/css/weight.css` | Weight editor styles |
| `src/web/js/landing.js` | Landing page logic |
| `src/web/js/tree_editor.js` | Tree editor logic |
| `src/web/js/tree_node.js` | TreeNode component |
| `src/web/js/weight_editor.js` | Weight editor component |
| `tests/database/test_subject_nodes.py` | Unit tests |
| `tests/integration/test_tree_editor.py` | Integration tests |

### Modified Files

| File | Changes |
|------|---------|
| `src/web/html/index.html` | Exam cards grid, empty state |
| `src/app/bridge.py` | New CRUD methods for subjects |
| `src/web/js/api.js` | New API wrapper methods |
| `src/database/user_db.py` | May need additional helper methods |

---

## Dependencies

### External Libraries (Already Installed)

- PyQt6 / PyQt6-WebEngine
- SQLite3 (standard library)

### Potential New Dependencies

| Library | Purpose | Required? |
|---------|---------|-----------|
| None | Phase 3 uses vanilla JS | - |

### Future Considerations

- **SortableJS** - If drag-drop becomes complex
- **D3.js** - If weight visualization needs enhancement

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Large hierarchy performance | Medium | Lazy loading, virtual scroll |
| Weight calculation edge cases | Medium | Extensive unit tests |
| Drag-drop complexity | Low | Start with reorder only, add reparent later |
| Import data validation | Medium | Strict schema validation |

---

## Related Documents

- `docs/phases/PHASE2_UI_STATUS.md` - Phase 2 completion status
- `docs/planning/PHASE2_IMPLEMENTATION_PLAN.md` - Original Phase 2 plan
- `docs/architecture/completed_database_tables.md` - Database schema
- `docs/planning/PHASE2_JSON_EXAMPLES.md` - JSON structure examples
- `docs/Claude_Project_WIMI_context.md` - Project overview

---

**Document Version:** 1.5  
**Created:** December 26, 2025  
**Last Updated:** December 26, 2025  
**Author:** Claude (AI Assistant)  
**Status:** ✅ ALL STAGES COMPLETE - Phase 3 Finished
