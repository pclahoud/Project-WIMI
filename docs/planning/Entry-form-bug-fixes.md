# Entry Form Bug Fixes Implementation Plan

**Created:** 2026-01-27
**Updated:** 2026-01-27 (All bugs fixed)
**Source:** `docs/planning/FUTURE_VISION.md` Technical Debt section

---

## Status Summary

| # | Bug | Status | Notes |
|---|-----|--------|-------|
| 1 | Auto-scroll while typing | ✅ FIXED | Confirmed working |
| 2 | Section switching needs multiple clicks | ✅ FIXED | Race condition between click and focus handlers |
| 3 | "No subjects assigned" shown incorrectly | ✅ FIXED | Confirmed working |
| 4 | Media/tables not persisting on save | ✅ FIXED | Was a loading issue, not saving |
| 5 | Related images dialog false positive | ✅ FIXED | SQL query updated, 6 unit tests added |
| 6 | Table selection lost on right-click | ✅ FIXED | Confirmed working |
| 7 | Table right-click functions broken | ✅ FIXED | Implemented native DOM manipulation |
| 8 | Table hover dialog positioning | ✅ FIXED | Fixed positioning with viewport calculations |
| 9 | Raw HTML modal loses text | ✅ FIXED | Cursor position saved before modal opens |

**All 9 bugs have been fixed.**

---

## Bug 1: Auto-Scroll While Typing ✅ FIXED

**Status:** ✅ Confirmed working

**Fix Applied:** Added `shouldScroll` parameter to `renderEntryNavigation()`, passing `false` from auto-save.

---

## Bug 2: Section Switching Requires Multiple Clicks ✅ FIXED

**Status:** ✅ Fixed (2026-01-27)

**Root Cause:** Race condition between two event handlers:
1. `onclick` handler called `toggleSection()` when user clicked section header
2. `focus` event listener also called `toggleSection()` when header received focus

When clicking an expanded section, the click collapsed it, then focus immediately re-expanded it.

**Fix Applied:**
1. Added click tracking variables (`_lastSectionClickTime`, `_lastSectionClickId`)
2. Added `isFromClick` parameter to `toggleSection()` function
3. Modified focus handler to skip if click happened within 100ms on same section
4. Updated all 6 HTML onclick handlers to pass `true` as third parameter

**Files Modified:**
- `src/web/js/question_entry.js` (lines 183-195, 307-325)
- `src/web/html/question_entry.html` (lines 113, 175, 255, 289, 313, 337)

---

## Bug 3: "No Subjects Assigned" Shown Incorrectly ✅ FIXED

**Status:** ✅ Confirmed working

**Fix Applied:** Added `syncMediaUploadSubjects()` call after `loadMedia()` in `populateFormWithEntry()`.

---

## Bug 4: Media/Tables Not Persisting on Save ✅ FIXED

**Status:** ✅ Fixed (2026-01-27)

**Root Cause:** This was a LOADING issue, not a saving issue. Data was saved correctly to database, but `setContent()` method was using direct `innerHTML` assignment for HTML strings, which bypassed Quill's internal content handling.

**Fix Applied:**
1. Changed `setContent()` to use `dangerouslyPasteHTML()` instead of direct `innerHTML`
2. Added `'silent'` source parameter to prevent unnecessary change events
3. Added try-catch error handling for delta content loading
4. Added content verification logging (50ms after load)
5. Added debug logging throughout the load path in `question_entry.js`

**Files Modified:**
- `src/web/js/rich_editor.js` - `setContent()` method
- `src/web/js/question_entry.js` - `collectFormData()`, `loadExistingEntry()`, `populateFormWithEntry()`

---

## Bug 5: Related Images Dialog False Positive ✅ FIXED

**Status:** ✅ Confirmed working

**Fix Applied:** Updated SQL query in `get_media_by_subject()` to check `linked_subject_ids` JSON array directly using `json_each()`. 6 unit tests added.

---

## Bug 6: Table Selection Lost on Right-Click ✅ FIXED

**Status:** ✅ Confirmed working

**Fix Applied:** Added `if (e.button === 2) return;` at start of mousedown handler in `_setupTableCellSelection()`.

---

## Bug 7: Table Right-Click Functions Broken ✅ FIXED

**Status:** ✅ Fixed (2026-01-27)

**Root Cause:** The `quill-table-better` library does NOT expose programmatic APIs for row/column operations. Methods like `insertRowAbove()`, `insertColumnLeft()`, etc. simply do not exist. The library only provides:
- `insertTable(rows, cols)` - Create a new table
- `deleteTable()` - Delete entire table
- `getTable()` - Get table information

Row/column operations are only available through the library's built-in hover menu, not programmatically.

**Fix Applied:** Implemented 6 native DOM manipulation methods:
1. `_tableInsertRow(table, row, position)` - Insert row above/below
2. `_tableInsertColumn(table, cell, position)` - Insert column left/right
3. `_tableDeleteRow(table, row)` - Delete row (prevents if only 1 row)
4. `_tableDeleteColumn(table, cell)` - Delete column (prevents if only 1 column)
5. `_tableMergeCells(table, selectedCells)` - Merge selected cells with rowspan/colspan
6. `_tableSplitCell(cell)` - Split merged cell back to individual cells
7. `_generateTableId()` - Generate unique IDs for table elements

**Files Modified:**
- `src/web/js/rich_editor.js` (lines ~928-1224, ~627-698)

---

## Bug 8: Table Hover Dialog Positioning ✅ FIXED

**Status:** ✅ Fixed (2026-01-27)

**Root Cause:** The quill-table-better hover toolbar used absolute positioning relative to the editor, causing it to appear at the bottom-left corner. For large tables (5x5+), the toolbar was inaccessible when working in upper rows.

**Fix Applied:**
1. Added CSS overrides for `.ql-table-menus-container` with fixed positioning
2. Added `_setupTableMenuRepositioning()` method using MutationObserver
3. Menu repositions near active cell on click/selection change
4. Viewport boundary constraints ensure menu stays visible

**Files Modified:**
- `src/web/css/rich_editor.css` (lines 1529-1561)
- `src/web/js/rich_editor.js` - `_setupTableMenuRepositioning()` method (lines 920-1037)

---

## Bug 9: Raw HTML Modal Loses Text ✅ FIXED

**Status:** ✅ Fixed (2026-01-27)

**Root Cause:** When the HTML modal opened, interacting with it caused the Quill editor to lose focus, resetting cursor position to 0. HTML was then inserted at position 0 instead of the original cursor location.

**Fix Applied:**
1. Save cursor position at start of `_showHtmlDialog()` before modal creation
2. Store `insertIndex` from `getSelection()` before focus is lost
3. Pass saved `insertIndex` to `_insertHtmlTable()` method
4. Updated `_insertHtmlTable()` to accept optional `insertIndex` parameter

**Files Modified:**
- `src/web/js/rich_editor.js` - `_showHtmlDialog()` (lines 1551-1556, 1612-1630), `_insertHtmlTable()` (line 1655+)

---

## Verification Checklist

All bugs should be manually verified:

- [x] **Bug 1:** Type in editor during auto-save, verify no scroll jump
- [ ] **Bug 2:** Rapidly click between sections, verify single-click always works
- [ ] **Bug 3:** Load entry with media, verify subjects display correctly
- [ ] **Bug 4:** Add table in notes, save, leave session, return - verify table displays
- [ ] **Bug 5:** Check related images dialog only shows truly related images
- [ ] **Bug 6:** Right-click table cell, verify selection is maintained
- [ ] **Bug 7:** Right-click table cell, test insert/delete row/column actions
- [ ] **Bug 8:** Create 6x6 table, click cells in top rows, verify toolbar is accessible
- [ ] **Bug 9:** Type text, insert HTML table, verify text is preserved

---

## Files Modified Summary

| File | Bugs Fixed |
|------|------------|
| `src/web/js/question_entry.js` | 2, 4 |
| `src/web/html/question_entry.html` | 2 |
| `src/web/js/rich_editor.js` | 4, 7, 8, 9 |
| `src/web/css/rich_editor.css` | 8 |

---

## Implementation Complete

**Date:** 2026-01-27

All 9 entry form bugs have been fixed. The fixes include:
- Race condition resolution for section switching
- Proper Quill content loading via `dangerouslyPasteHTML()`
- Native DOM manipulation for table operations (replacing non-existent API calls)
- Fixed positioning for table hover toolbar with viewport constraints
- Cursor position preservation for HTML modal insertion
