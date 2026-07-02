Excellent! Let's move to implementation planning.

---

## Implementation Plan: Stage 4

### Overview

| Feature | Files to Create/Modify | Estimated Time |
|---------|----------------------|----------------|
| Fuse.js Integration | 3 files | 1.5-2 hours |
| Keyboard Navigation | 2 files | 1.5-2 hours |
| Inline Tag Creation | 4 files | 2-3 hours |
| Testing & Polish | 2 files | 1-1.5 hours |
| **Total** | | **6-8.5 hours** |

---

### Task Breakdown

#### Task 1: Fuse.js Integration (Foundation)

**1.1 Add Fuse.js Library**
```
File: src/web/html/question_entry.html
Action: Add CDN script tag
```

**1.2 Create New Bridge Method**
```
File: src/app/bridge.py
Action: Add getAllSubjectsForExam() method
Returns: Flat list of all subjects with paths for client-side caching
```

**1.3 Create Fuzzy Search Module**
```
File: src/web/js/fuzzy_search.js (NEW)
Contents:
  - FuzzySearch class wrapping Fuse.js
  - initSubjectIndex(subjects)
  - initTagIndex(tags) 
  - searchSubjects(query, limit)
  - searchTags(query, limit)
  - highlightMatches(text, query)
```

**1.4 Update Question Entry JS**
```
File: src/web/js/question_entry.js
Changes:
  - Load all subjects on init
  - Replace debounced API search with local Fuse search
  - Add match highlighting to dropdown rendering
```

---

#### Task 2: Keyboard Navigation

**2.1 Create Keyboard Navigation Module**
```
File: src/web/js/dropdown_keyboard.js (NEW)
Contents:
  - DropdownKeyboard class
  - attach(input, dropdown, onSelect)
  - handleKeydown(event)
  - selectNext() / selectPrev()
  - confirmSelection()
  - getSelectedItem()
  - setSelectedIndex(index)
  - ARIA attribute management
```

**2.2 Update Dropdown Rendering**
```
File: src/web/js/question_entry.js
Changes:
  - Add role="listbox" to dropdowns
  - Add role="option" and aria-selected to items
  - Add unique IDs to options
  - Integrate DropdownKeyboard for subject search
  - Integrate DropdownKeyboard for tag search
```

**2.3 Add Keyboard Hint Footer**
```
File: src/web/css/entry.css
Changes:
  - .dropdown-hint styles
  - Dismissible hint logic (localStorage flag)
```

---

#### Task 3: Inline Tag Creation

**3.1 Add Bridge Methods**
```
File: src/app/bridge.py
Action: Add createTag() method
Parameters: exam_context, tag_name, parent_group_id
Returns: New tag object
```

**3.2 Add Database Method (if needed)**
```
File: src/database/user_db.py
Action: Verify create_tag() supports adding to existing group
May need: Minor adjustments for parent_id handling
```

**3.3 Update Tag Picker UI**
```
File: src/web/js/question_entry.js
Changes:
  - Convert tag hierarchy to searchable dropdown
  - Add "Create new tag" option in results
  - Add inline creation form (expandable)
  - Handle create flow with group selection
  - Refresh tag index after creation
```

**3.4 Add Tag Creation Styles**
```
File: src/web/css/entry.css
Changes:
  - .tag-create-option styles
  - .tag-create-form styles (inline expandable)
  - .tag-group-radio styles
```

---

#### Task 4: Testing & Polish

**4.1 Manual Test Checklist**
```
File: docs/testing/PHASE4_STAGE4_MANUAL_TEST_CHECKLIST.md (NEW)
Contents: Test cases for all three features
```

**4.2 Update Implementation Plan**
```
File: docs/phases/PHASE4_IMPLEMENTATION_PLAN.md
Action: Mark Stage 4 complete, update status
```

---

### File Summary

| File | Action | Description |
|------|--------|-------------|
| `src/web/html/question_entry.html` | Modify | Add Fuse.js CDN |
| `src/web/js/fuzzy_search.js` | **Create** | Fuse.js wrapper module |
| `src/web/js/dropdown_keyboard.js` | **Create** | Keyboard navigation module |
| `src/web/js/question_entry.js` | Modify | Integrate fuzzy search, keyboard nav, tag creation |
| `src/web/js/api.js` | Modify | Add `getAllSubjectsForExam` method |
| `src/web/css/entry.css` | Modify | Dropdown, keyboard hint, tag creation styles |
| `src/app/bridge.py` | Modify | Add `getAllSubjectsForExam`, `createTag` methods |
| `src/database/user_db.py` | Verify/Modify | Ensure tag creation supports parent_id |
| `docs/testing/PHASE4_STAGE4_MANUAL_TEST_CHECKLIST.md` | **Create** | Test cases |
| `docs/phases/PHASE4_IMPLEMENTATION_PLAN.md` | Modify | Update status |

---

### Implementation Order

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: Foundation (Fuse.js)                                  │
│  ─────────────────────────────────────────────────────────────  │
│  1. Add Fuse.js CDN to HTML                                     │
│  2. Create getAllSubjectsForExam bridge method                  │
│  3. Create fuzzy_search.js module                               │
│  4. Integrate into subject search (replace API calls)           │
│  5. Test subject search works                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2: Keyboard Navigation                                   │
│  ─────────────────────────────────────────────────────────────  │
│  1. Create dropdown_keyboard.js module                          │
│  2. Add ARIA attributes to subject dropdown                     │
│  3. Integrate keyboard nav into subject search                  │
│  4. Add keyboard hint footer                                    │
│  5. Test keyboard navigation                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3: Tag Search Enhancement                                │
│  ─────────────────────────────────────────────────────────────  │
│  1. Add tag index to fuzzy_search.js                            │
│  2. Convert tag section to searchable dropdown                  │
│  3. Integrate keyboard nav into tag search                      │
│  4. Test tag search works                                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 4: Inline Tag Creation                                   │
│  ─────────────────────────────────────────────────────────────  │
│  1. Add createTag bridge method                                 │
│  2. Add "Create new tag" option to dropdown                     │
│  3. Build inline creation form UI                               │
│  4. Handle create flow + refresh index                          │
│  5. Test tag creation                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 5: Polish & Documentation                                │
│  ─────────────────────────────────────────────────────────────  │
│  1. Add CSS polish (transitions, hover states)                  │
│  2. Create manual test checklist                                │
│  3. Run all test cases                                          │
│  4. Fix any bugs                                                │
│  5. Update PHASE4_IMPLEMENTATION_PLAN.md                        │
└─────────────────────────────────────────────────────────────────┘
```

---
