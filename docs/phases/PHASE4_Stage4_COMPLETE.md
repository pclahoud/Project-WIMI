# Phase 4 Stage 4: Subject Search & Tag Picker Enhancements

**Status:** ✅ COMPLETE  
**Completed:** December 27, 2025

---

## Overview

Stage 4 implemented enhanced search functionality for subjects and tags, including fuzzy matching with Fuse.js, keyboard navigation, and inline tag creation.

---

## Implementation Summary

### Features Implemented

| Feature | Description | Status |
|---------|-------------|--------|
| Fuse.js Fuzzy Search | Bundled locally for typo-tolerant search | ✅ |
| Keyboard Navigation | Arrow keys, Enter, Escape for dropdowns | ✅ |
| ARIA Accessibility | role="listbox", aria-selected, aria-activedescendant | ✅ |
| Tag Search Enhancement | Search across hierarchical tags | ✅ |
| Inline Tag Creation | Create new tags within existing groups | ✅ |
| Match Highlighting | Visual highlighting of matched text | ✅ |
| Database Tag Loading | Tags load from SQLite via WebChannel | ✅ |

### Files Created

| File | Size/Lines | Description |
|------|------------|-------------|
| `src/web/js/fuse.min.js` | ~26KB | Fuse.js v7.1.0 fuzzy search library |
| `src/web/js/fuzzy_search.js` | ~320 lines | Fuse.js wrapper with fallback search |
| `src/web/js/dropdown_keyboard.js` | ~220 lines | Keyboard navigation module |

### Files Modified

| File | Changes |
|------|---------|
| `src/web/html/question_entry.html` | Added local Fuse.js script reference |
| `src/web/js/question_entry.js` | Tag search, inline creation (~200 lines) |
| `src/web/js/api.js` | **Critical fix**: WebChannel Promise handling |
| `src/web/css/entry.css` | Dropdown styles, keyboard hints (~150 lines) |
| `src/app/bridge.py` | `getAllSubjectsForExam`, `createTagInGroup` methods |

---

## Fuse.js Integration

### Why Bundled Locally

Initially attempted to load Fuse.js from CDN (jsdelivr.net), but network restrictions in the PyQt environment blocked external requests. Solution: bundle Fuse.js locally.

### Capabilities

- **Typo tolerance**: "knolwedge" matches "Knowledge"
- **Partial matching**: "cardio" matches "Cardiovascular"  
- **Weighted scoring**: Name matches ranked higher than path matches
- **Configurable thresholds**: Balance between precision and recall

### Configuration

```javascript
// Tag search config
tagFuseOptions = {
    keys: [
        { name: 'name', weight: 0.7 },
        { name: 'groupName', weight: 0.3 }
    ],
    threshold: 0.5,      // More lenient for tags
    distance: 100,
    minMatchCharLength: 2,
    includeScore: true,
    includeMatches: true
};
```

---

## Critical Bug Fixes

### 1. WebChannel Promise Handling

**Problem:** All bridge calls returned empty or failed silently.

**Root Cause:** `api.js` `_callBridge()` method wasn't awaiting the Promise returned by PyQt WebChannel.

**Before (broken):**
```javascript
const responseJson = this.bridge[methodName](...args);
return this._handleResponse(responseJson);  // responseJson was a Promise object!
```

**After (fixed):**
```javascript
const responseJson = await this.bridge[methodName](...args);
return this._handleResponse(responseJson);  // Now properly awaits the Promise
```

### 2. Tag Hierarchy Flattening

**Problem:** No tags appeared in search results even though database had 21 tags.

**Root Cause:** `_flattenTagHierarchy()` checked `is_group === false` but database used `is_group: true` for groups and `undefined` for leaf tags.

**Fix:** Check both `is_group === true` AND presence of children:
```javascript
const isGroup = item.is_group === true || (item.children && item.children.length > 0);
```

### 3. CSS Overflow Clipping

**Problem:** Tag dropdown was clipped by parent `.entry-section` container.

**Fix:** Only apply `overflow: hidden` when section is collapsed:
```css
.entry-section:not(.expanded) {
    overflow: hidden;
}
```

---

## New Bridge Methods

```python
@pyqtSlot(int, result=str)
def getAllSubjectsForExam(self, exam_context_id: int) -> str:
    """
    Get all subjects for an exam context (for client-side fuzzy search).
    Returns flat list of all subjects with their full paths.
    """

@pyqtSlot(str, str, int, result=str)
def createTagInGroup(self, exam_context: str, tag_name: str, group_id: int) -> str:
    """
    Create a new tag within an existing group (for inline tag creation).
    Inherits color from parent group.
    """
```

---

## Simple Search Fallback

If Fuse.js fails to load for any reason, a fallback simple search is available:

```javascript
// Scoring (lower is better):
// 0.0 - Exact match
// 0.1 - Starts with query
// 0.3 - Contains query as phrase
// 0.5 - Contains all query words (any order)
// 0.7 - Contains any query word
// 1.0 - No match
```

---

## Keyboard Navigation

| Key | Action |
|-----|--------|
| `↓` Arrow Down | Move to next result |
| `↑` Arrow Up | Move to previous result |
| `Enter` | Select highlighted item |
| `Escape` | Close dropdown |
| `Tab` | Move to next field |

---

## Testing

### Console Log Verification

Successful load shows:
```
🏷️ Loading tag hierarchy for: USMLE Step 1
📋 Tag hierarchy received: (5) [{…}, {…}, {…}, {…}, {…}]
🔄 Initializing fuzzy search tag index...
📋 Flattened 16 tags from hierarchy
✅ Tag index ready, tags: 16
```

With Fuse.js loaded (no warnings about fallback):
```
✅ Subject index initialized with X subjects
✅ Tag index initialized with 16 tags
```

### Manual Tests Passed

- [x] Tag groups display below search input (5 groups)
- [x] Typing in search shows filtered results
- [x] Typo-tolerant search works ("knolwedge" → "Knowledge")
- [x] Arrow keys navigate dropdown
- [x] Enter selects highlighted tag
- [x] Selected tags appear as chips
- [x] Chips can be removed with × button
- [x] "Create tag" option appears for new terms
- [x] Inline creation form shows group radio buttons
- [x] New tags save to database (via bridge)

---

## Known Limitations

1. **No tree browser modal**: Subject tree browser was descoped to future enhancement. Users can still search and select subjects effectively.

---

## Next Steps

**Stage 5: Media Handling** will implement:
- Clipboard paste (Ctrl+V) for images
- Drag and drop file upload
- File picker browser
- Thumbnail preview with actions
- Rename/delete/reorder functionality

---

**Completed:** December 27, 2025
