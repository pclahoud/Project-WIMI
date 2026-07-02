# Phase 5 Implementation Plan - Entry Review & Browsing

**Created:** December 30, 2025  
**Status:** Planning  
**Estimated Duration:** 25-35 hours

---

## Overview

Phase 5 implements the "Note"-esque interface for viewing, browsing, filtering, and editing logged question entries. This phase complements Phase 4's entry creation workflow by providing comprehensive review capabilities.

---

## Implementation Stages

| Stage | Focus | Duration | Status |
|-------|-------|----------|--------|
| 1 | Database Methods & API | 4-5 hours | Planned |
| 2 | Entry Browser Page (List View) | 6-8 hours | Planned |
| 3 | Entry Detail View | 5-6 hours | Planned |
| 4 | Filter System | 5-6 hours | Planned |
| 5 | Search & Related Topics | 3-4 hours | Planned |
| 6 | Testing & Polish | 2-4 hours | Planned |

---

## Stage 1: Database Methods & API

### New Database Methods (user_db.py)

```python
# Entry Browsing
def get_entries_paginated(
    exam_context_id: Optional[int] = None,
    session_id: Optional[int] = None,
    subject_ids: Optional[List[int]] = None,
    tag_ids: Optional[List[int]] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    is_draft: Optional[bool] = None,
    sort_by: str = 'date_desc',
    page: int = 1,
    per_page: int = 20
) -> Tuple[List[QuestionEntry], int]  # entries, total_count

def get_entry_with_context(entry_id: int) -> Dict  # Full entry + session + exam info

def get_related_subjects(subject_id: int, limit: int = 4) -> List[SubjectNode]

def search_entries_fulltext(
    query: str,
    exam_context_id: Optional[int] = None,
    limit: int = 50
) -> List[QuestionEntry]

def get_entry_statistics(exam_context_id: Optional[int] = None) -> Dict
```

### New Bridge Methods (bridge.py)

```python
@pyqtSlot(str, result=str)
def getEntriesPaginated(self, params_json: str) -> str

@pyqtSlot(int, result=str)
def getEntryWithContext(self, entry_id: int) -> str

@pyqtSlot(int, int, result=str)
def getRelatedSubjects(self, subject_id: int, limit: int) -> str

@pyqtSlot(str, result=str)
def searchEntriesFulltext(self, params_json: str) -> str

@pyqtSlot(str, result=str)
def getEntryStatistics(self, params_json: str) -> str
```

### New API Methods (api.js)

```javascript
async getEntriesPaginated(params)
async getEntryWithContext(entryId)
async getRelatedSubjects(subjectId, limit)
async searchEntriesFulltext(query, examContextId)
async getEntryStatistics(examContextId)
```

---

## Stage 2: Entry Browser Page (List View)

### Files to Create

| File | Purpose |
|------|---------|
| `src/web/html/entry_browser.html` | Entry browser page |
| `src/web/js/entry_browser.js` | Browser logic |
| `src/web/css/browser.css` | Browser styles |

### Key Components

1. **Header Bar**
   - Back navigation to landing page
   - Exam context badge
   - Entry statistics summary

2. **Filter Bar**
   - Search input with fuzzy search
   - Subject dropdown (hierarchical tree)
   - Tags dropdown (grouped with colors)
   - Date dropdown (presets + calendar)
   - Session dropdown
   - Sort dropdown
   - View toggle (Cards/Table)

3. **Entry Cards**
   - Difficulty indicator
   - Subject path
   - Reflection preview (truncated)
   - Tags (color-coded chips)
   - Media count indicator
   - Draft badge
   - Date

4. **Pagination**
   - Entry count display
   - Load More button
   - Per-page selector

### UI Based on Mockups

From Frame0 mockups:
- Card-based layout (2 columns)
- Filter bar with dropdowns
- Sort by: Date (Newest), Date (Oldest), Difficulty (High/Low), Subject (A-Z)
- Pagination with "Load More" pattern

---

## Stage 3: Entry Detail View

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/web/html/entry_detail.html` | Detail view page |
| `src/web/js/entry_detail.js` | Detail view logic |
| `src/web/css/detail.css` | Detail view styles |

### Key Components

1. **Header**
   - Back to entries link
   - Edit Entry button
   - Delete button (with confirmation)

2. **Metadata Bar**
   - Subject path (full hierarchy)
   - Session info, date, question ID, time spent
   - Difficulty badge
   - Tags (color-coded)

3. **Answer Comparison Section**
   - Your Answer (red background) with ✗
   - Correct Answer (green background) with ✓

4. **Reflection Section**
   - Full reflection text
   - Collapsible for long content

5. **Explanation Section**
   - Full explanation text
   - Collapsible for long content

6. **Attachments & Notes Section**
   - Thumbnail grid (clickable for full-size)
   - Notes text

7. **Related Topics Panel** ⭐ NEW
   - Yellow/amber highlighted section
   - Clickable topic suggestions
   - Based on subject hierarchy siblings/parents
   - Links to filter entries by those topics

### Edit Mode

- Clicking "Edit Entry" navigates to question_entry.html with mode=edit
- Pre-fills all fields from existing entry
- Save updates the entry instead of creating new

---

## Stage 4: Filter System

### Subject Filter

- Search box with fuzzy search
- Hierarchical tree display
- Checkbox multi-select
- "Include child subjects" toggle
- Entry count per subject
- Apply/Clear buttons

### Tags Filter

- Grouped by tag group (Mistake Type, Priority, Status)
- Color-coded chips
- Checkbox multi-select
- Entry count per tag

### Date Filter

- Preset ranges: Today, 7 Days, 30 Days, This Month, All Time
- Custom date range picker
- Mini calendar component

### Session Filter

- Search sessions by name
- Shows session name, date, entry count, status
- Checkbox multi-select

### Sort Options

- Date (Newest) - default
- Date (Oldest)
- Difficulty (High to Low)
- Difficulty (Low to High)
- Subject (A-Z)

---

## Stage 5: Search & Related Topics

### Full-Text Search

- Searches across: reflection, explanation, notes, user_answer, correct_answer
- Fuzzy matching via SQLite LIKE
- Highlights matching text in results
- Debounced input (300ms)

### Related Topics Algorithm

```python
def get_related_subjects(subject_id: int, limit: int = 4) -> List[SubjectNode]:
    """
    Get related subjects for the 'Related Topics to Review' panel.
    
    Strategy:
    1. Get siblings (same parent)
    2. Get parent's siblings (aunts/uncles)
    3. Get children (if any)
    4. Prioritize by entry count (subjects with more mistakes)
    """
```

---

## Stage 6: Testing & Polish

### Test Cases

1. **Entry Browser**
   - Load entries with no filters
   - Apply each filter type individually
   - Combine multiple filters
   - Sort by each option
   - Pagination (Load More)
   - Empty state display

2. **Entry Detail**
   - View complete entry
   - View draft entry
   - Edit mode transition
   - Media display
   - Related topics display

3. **Filter Interactions**
   - Subject tree navigation
   - Tag selection with colors
   - Date range selection
   - Session selection
   - Filter clearing

4. **Edge Cases**
   - No entries match filters
   - Very long reflection/explanation text
   - Many media attachments
   - No related topics available

---

## Navigation Flow

```
Landing Page (index.html)
    ├── "Browse Entries" button on exam card
    │       ↓
    │   Entry Browser (entry_browser.html)
    │       ├── Click entry card → Entry Detail
    │       └── Filter/Search → Filtered results
    │
    └── Entry Detail (entry_detail.html)
            ├── "Edit Entry" → question_entry.html?mode=edit&id=X
            ├── "Back to Entries" → entry_browser.html
            └── Related Topic → entry_browser.html?subject=X
```

---

## Files Summary

### New Files

| File | Type | Purpose |
|------|------|---------|
| `entry_browser.html` | HTML | Browser page |
| `entry_browser.js` | JS | Browser logic |
| `browser.css` | CSS | Browser styles |
| `entry_detail.html` | HTML | Detail view page |
| `entry_detail.js` | JS | Detail view logic |
| `detail.css` | CSS | Detail view styles |

### Modified Files

| File | Changes |
|------|---------|
| `user_db.py` | Add browsing/filtering methods |
| `bridge.py` | Add bridge methods for new DB functions |
| `api.js` | Add API methods for browsing |
| `index.html` | Add "Browse Entries" button to exam cards |
| `landing.js` | Handle Browse Entries navigation |
| `question_entry.js` | Support edit mode (mode=edit&id=X) |

---

## Dependencies

- Existing Phase 4 infrastructure (entries, sessions, media)
- Fuse.js for fuzzy search (already bundled)
- Existing CSS design system

---

## Mockup Reference

The UI is based on Frame0 mockups created in this session:
- Page 1: Entry Browser - List View
- Page 2: Filter Dropdowns (Subject, Tags, Date, Session)
- Page 3: Entry Detail View

---

## Next Steps

1. Start Stage 1: Add database methods to user_db.py
2. Add corresponding bridge methods
3. Add API methods to api.js
4. Create entry_browser.html and basic structure
5. Implement filter components
6. Create entry_detail.html
7. Add related topics feature
8. Testing and polish

---

**END OF IMPLEMENTATION PLAN**
