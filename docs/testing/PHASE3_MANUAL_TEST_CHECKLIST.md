# Phase 3 Manual Test Checklist

**Version:** 1.0  
**Created:** December 26, 2025  
**Purpose:** Manual testing guide for Phase 3 UI functionality

---

## Pre-Test Setup

1. [ ] Start the application: `python run_wimi.py`
2. [ ] Open developer tools (F12) to monitor for JavaScript errors
3. [ ] Clear any existing test data if needed

---

## 1. Landing Page Tests

### 1.1 Empty State
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Empty state display | Start with no exams | Shows "No exams yet" message with create button | |
| Create first exam | Click create button in empty state | Opens exam wizard | |

### 1.2 Exam Cards
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Cards display | Create 2-3 exams | All exams show as cards in grid | |
| Card info | View card | Shows name, description, date, subject count | |
| Open exam | Click "Open" on card | Navigates to tree editor | |
| Edit exam | Click "Edit" on card | Opens wizard with pre-filled data | |
| Delete exam | Click "Delete" on card | Shows confirmation, then removes card | |
| Refresh after create | Create new exam | Landing page shows new card | |

### 1.3 Navigation
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Hot reload | Press F5 | Page reloads, state preserved | |
| Back from wizard | Click back/cancel in wizard | Returns to landing | |

---

## 2. Exam Wizard Tests

### 2.1 Create Mode
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Step 1 - Basic info | Enter name, description | Fields accept input, Next enabled | |
| Step 2 - Hierarchy | Keep defaults or customize | Level names shown correctly | |
| Step 3 - Weights | Adjust precision, algorithm | Settings saved | |
| Step 4 - Summary | Review all settings | All entered data shown | |
| Create exam | Click Create | Success toast, redirects to tree editor | |

### 2.2 Edit Mode
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Pre-filled data | Open edit mode | All fields show existing values | |
| Update name | Change exam name | Saves correctly | |
| Update settings | Change weight settings | Saves correctly | |
| Cancel edit | Click Cancel | Returns to landing, no changes | |

---

## 3. Tree Editor Tests

### 3.1 Initial Load
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Empty tree | Open exam with no subjects | Shows empty state with "Add Root" prompt | |
| Loaded tree | Open exam with subjects | Tree renders with all nodes | |
| Header info | Check header | Shows exam name and badge | |
| Stats display | Check toolbar | Shows node count and weight total | |

### 3.2 Exam Overview (No Selection)
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Overview display | Deselect any node | Shows exam overview panel | |
| Pie chart | View chart | Shows weight distribution of root nodes | |
| Click pie slice | Click on pie section | Selects corresponding node | |
| Stats accuracy | Check numbers | Matches actual node count and weights | |

### 3.3 Node Selection & Details
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Select node | Click on node | Node highlighted, details panel shows | |
| Details accuracy | Check panel | Shows correct name, level, weight | |
| Edit name | Change name in details | Saves and updates tree | |
| Parent display | Check parent field | Shows correct parent or "(Root Level)" | |
| Children list | Check children section | Lists all direct children | |

### 3.4 Node CRUD Operations
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Add root node | Click "+ Add Root Subject" | Modal opens, can create | |
| Add child node | Select node, click "+ Add Child" | Modal opens with correct parent | |
| Rename node | Double-click node name | Inline edit activates | |
| Inline edit save | Press Enter after edit | Name updated in tree | |
| Inline edit cancel | Press Escape during edit | Reverts to original | |
| Delete leaf node | Delete node without children | Node removed, no warning | |
| Delete parent node | Delete node with children | Warning shown about children | |
| Confirm delete | Click confirm in modal | Node and children removed | |
| Cancel delete | Click cancel in modal | Node remains | |

### 3.5 Tree Navigation
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Expand node | Click node with children | Node expands, shows children | |
| Collapse node | Click expanded node again | Node collapses | |
| Expand All | Click "Expand All" | All nodes expanded | |
| Collapse All | Click "Collapse All" | All nodes collapsed | |
| Click-to-expand | Single click on parent node | Selects AND expands | |

---

## 4. Weight Editor Tests

### 4.1 Basic Weight Editing
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Slider display | Select node | Weight slider shows current value | |
| Slider movement | Drag slider | Value updates in real-time | |
| Direct input | Type in weight field | Slider updates to match | |
| Precision respect | Check decimal places | Matches exam precision setting | |

### 4.2 Sibling Balancing Preview
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Sibling display | Select node with siblings | Shows all siblings with bars | |
| Preview update | Adjust slider | Preview shows new sibling values | |
| Current highlight | Check current node | Highlighted differently | |
| Total validation | Check total | Shows if sum equals 100% | |

### 4.3 Apply/Reset
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Apply changes | Click Apply | Weight saved, siblings updated | |
| Reset button | Change slider, click Reset | Reverts to original value | |
| No change apply | Click Apply without changes | Shows "No Change" message | |
| Tree refresh | Apply weight change | Tree badges update immediately | |

### 4.4 Weight History
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| History display | Open history section | Shows previous changes | |
| History entries | Make changes, check history | New entries appear | |
| Manual vs Auto | Check entry types | User edits vs system adjustments labeled | |

---

## 5. Import/Export Tests

### 5.1 Export
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Export button | Click Export | Downloads JSON file | |
| File name | Check downloaded file | Named with exam name and date | |
| File content | Open JSON | Contains metadata and root_nodes | |
| Complete export | Check all nodes | All nodes and weights included | |

### 5.2 Import - Valid File
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Import button | Click Import | File picker opens | |
| Preview modal | Select valid JSON | Preview modal appears | |
| Preview tree | Check preview | Shows hierarchy structure | |
| Node count | Check count | Correct number displayed | |
| Merge mode | Select Merge, import | Adds to existing nodes | |
| Replace mode | Select Replace, import | Removes existing, adds new | |
| Success toast | Complete import | Success message shown | |
| Tree refresh | After import | New nodes appear in tree | |

### 5.3 Import - Invalid File
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Invalid JSON | Select non-JSON file | Error toast shown | |
| Missing root_nodes | Import file without root_nodes | Error modal shown | |
| Validation warnings | Import with minor issues | Warnings shown but import allowed | |
| Cancel import | Click Cancel in preview | Modal closes, no import | |

### 5.4 Import Format Flexibility
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| "subjects" key | Import file with "subjects" key | Auto-converts, shows info | |
| Extra fields | Import with aliases, metadata | Ignores extra, imports correctly | |

---

## 6. Error Handling & Edge Cases

### 6.1 Error Messages
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| API error | Trigger backend error | Toast shows error message | |
| Validation error | Enter invalid weight | Warning displayed | |
| Network simulation | (If applicable) | Graceful degradation | |

### 6.2 Edge Cases
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Single root node | Only one root | Weight editing still works | |
| Deep nesting | Create 6+ level hierarchy | All levels render correctly | |
| Long names | Create node with very long name | Truncates properly, tooltip shows full | |
| Special characters | Use special chars in names | Handles correctly | |
| Zero weight | Set weight to 0% | Allowed, siblings adjust | |
| 100% weight | Set single sibling to 100% | Others go to 0% | |

---

## 7. Cross-Browser & Performance

### 7.1 Performance
| Test | Steps | Expected Result | Pass/Fail |
|------|-------|-----------------|-----------|
| Large hierarchy | Import 50+ nodes | Renders without lag | |
| Rapid clicks | Click multiple nodes quickly | No errors, correct selection | |
| Memory leaks | Use app for extended period | No significant memory growth | |

---

## 8. Keyboard Shortcuts

| Shortcut | Action | Expected Result | Pass/Fail |
|----------|--------|-----------------|-----------|
| F5 | Any page | Reloads current page | |
| F12 | Any page | Opens dev tools | |
| Escape | In modal | Closes modal | |
| Enter | Inline edit | Saves changes | |
| Escape | Inline edit | Cancels edit | |

---

## Test Summary

| Section | Total Tests | Passed | Failed | Notes |
|---------|-------------|--------|--------|-------|
| Landing Page | | | | |
| Exam Wizard | | | | |
| Tree Editor | | | | |
| Weight Editor | | | | |
| Import/Export | | | | |
| Error Handling | | | | |
| Performance | | | | |
| **TOTAL** | | | | |

---

## Issues Found

| # | Description | Severity | Status |
|---|-------------|----------|--------|
| 1 | | | |
| 2 | | | |
| 3 | | | |

---

## Notes

- 
- 
- 

---

**Tested By:** ________________  
**Date:** ________________  
**Build/Version:** ________________
