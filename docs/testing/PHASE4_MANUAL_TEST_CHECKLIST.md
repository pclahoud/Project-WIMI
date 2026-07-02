# Phase 4 Manual Test Checklist

**Document Version:** 1.0  
**Created:** December 27, 2025  
**Phase:** 4 - Question Entry System  
**Stages Covered:** 2-5 (Session Setup, Question Entry, Search/Tags, Media)

---

## How to Use This Checklist

1. Start the application: `python run_wimi.py`
2. Navigate to the USMLE Step 1 exam card on the landing page
3. Work through each test case in order
4. Mark each test: ✅ Pass, ❌ Fail, ⏭️ Skipped
5. Document any bugs found in the Bugs section

---

## Section 1: Session Setup (Stage 2)

### 1.1 Navigation

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.1.1 | Click "New Review Session" on exam card | Session setup page loads P| |
| 1.1.2 | Click "← Back" from session setup | Returns to landing page |P |
| 1.1.3 | Click exam name link in header | Returns to landing page |F |

### 1.2 Previous Sessions Display

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.2.1 | View sessions with incomplete entries | Shows "Continue" button |P |
| 1.2.2 | View sessions with all complete entries | Shows "Review" button |F; USER HAS TO SELECT 'SAVE AS DRAFT' ON THE LAST ENTRY. THE PROGRAM DOESN'T RECOGNIZE COMPLETION AFTER THE USER COMPLETES THE LAST ENTRY |
| 1.2.3 | Click "Continue" on incomplete session | Opens entry at first incomplete |P |
| 1.2.4 | Horizontal scroll when many sessions | Scrolls smoothly |P |
| 1.2.5 | Empty state (no previous sessions) | Shows appropriate message |P |

### 1.3 New Session Form

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.3.1 | Exam context pre-filled | Shows correct exam name |P |
| 1.3.2 | Question source dropdown | Shows available sources |P |
| 1.3.3 | Click "+ Add New" source | Opens inline form |P |
| 1.3.4 | Add new source with name only | Source created, selected |P |
| 1.3.5 | Date picker shows today by default | Today's date shown |P |
| 1.3.6 | Change date encountered | Date updates |P |
| 1.3.7 | Enter total questions | Accepts numeric input |P |
| 1.3.8 | Enter total incorrect | Accepts numeric input |P |
| 1.3.9 | Enter session name (optional) | Accepts text |P |
| 1.3.10 | Leave session name blank | Auto-generates name |P |

### 1.4 Form Validation

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.4.1 | Submit without question source | Shows validation error |P |
| 1.4.2 | Submit with 0 total questions | Shows validation error |P |
| 1.4.3 | Submit with 0 total incorrect | Shows validation error |P |
| 1.4.4 | Total incorrect > total questions | Shows validation error |P |
| 1.4.5 | All fields valid | Start Session enabled |P |

### 1.5 Start Session

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.5.1 | Click "Start Session" | Creates session, opens entry page |P |
| 1.5.2 | Entry counter shows "1 of N" | N = total incorrect |P |
| 1.5.3 | Session name in header | Shows correct name |P |

### 1.6 Question Source Management

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.6.1 | Click "Manage Sources" | Opens modal |P |
| 1.6.2 | Add new source in modal | Source appears in list |P |
| 1.6.3 | Edit existing source | Changes saved |P |
| 1.6.4 | Delete source | Source removed |P |
| 1.6.5 | Close modal | Returns to form |P |

---

## Section 2: Question Entry Form (Stage 3)

### 2.1 Page Load & Header

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.1.1 | Page loads with session context | Shows session name, exam, counter |P |
| 2.1.2 | Entry counter accurate | Shows "Entry X of Y" |P |
| 2.1.3 | Entry dots display | Shows correct number of dots |P |
| 2.1.4 | Click "← Back" | Shows save prompt if changes |P |

### 2.2 Section A: Question Info

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.2.1 | Section A expanded by default | Content visible |P |
| 2.2.2 | Enter Question ID | Accepts text |P |
| 2.2.3 | Enter Your Answer (required) | Accepts text |P |
| 2.2.4 | Enter Correct Answer (required) | Accepts text |P |
| 2.2.5 | Select difficulty (1-5 dots) | Dot highlights, value saved |P |
| 2.2.6 | Click same difficulty dot | Deselects |P |
| 2.2.7 | Enter time spent | Accepts number |P |
| 2.2.8 | Toggle minutes/seconds | Unit changes |P |

### 2.3 Section B: Subject Mapping

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.3.1 | Click section header | Section expands |P |
| 2.3.2 | Type in primary subject search | Dropdown appears |P |
| 2.3.3 | Search returns fuzzy matches | "cardio" finds "Cardiology" |P |
| 2.3.4 | Arrow keys navigate results | Highlight moves |P |
| 2.3.5 | Enter selects highlighted | Subject chip added |P |
| 2.3.6 | Click result | Subject chip added |P |
| 2.3.7 | Click × on chip | Subject removed |P |
| 2.3.8 | Add multiple primary subjects | All show as chips |P |
| 2.3.9 | Secondary subjects work same | Independent selection |P |
| 2.3.10 | At least 1 primary required | Validation indicator shown |P |

### 2.4 Section C: Tags

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.4.1 | Click section header | Section expands |P |
| 2.4.2 | Type in tag search | Dropdown shows matches |P |
| 2.4.3 | Tags show with group context | "Knowledge Issues > Knowledge Gap" |P |
| 2.4.4 | Click leaf tag | Tag chip added |P |
| 2.4.5 | Click group header | Does NOT select (not allowed) |P |
| 2.4.6 | No match shows "Create" option | Inline creation UI appears |P |
| 2.4.7 | Create tag in group | New tag added as chip |P |
| 2.4.8 | Remove tag chip | Tag removed |P |

### 2.5 Section D: Reflection (Required)

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.5.1 | Section shows required indicator | Asterisk or similar |P |
| 2.5.2 | Textarea accepts text | Text entered |P |
| 2.5.3 | Character count displays | Shows current count |P |
| 2.5.4 | Empty blocks "Save & Next" | Button disabled |P |
| 2.5.5 | With text, enables save | Button enabled |P |

### 2.6 Section E: Explanation (Required)

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.6.1 | Section shows required indicator | Asterisk or similar |P |
| 2.6.2 | Textarea accepts text | Text entered |P |
| 2.6.3 | Character count displays | Shows current count |P |
| 2.6.4 | Empty blocks "Save & Next" | Button disabled |P |
| 2.6.5 | With text, enables save | Button enabled |P |

### 2.7 Section F: Notes & Media

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.7.1 | Notes textarea accepts text | Text entered |P |
| 2.7.2 | Media dropzone visible | Shows upload area |P |
| 2.7.3 | (Media tests in Section 4) | | |

### 2.8 Section Collapse Behavior

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.8.1 | Click expanded section header | Section collapses |P |
| 2.8.2 | Click collapsed section header | Section expands |P |
| 2.8.3 | Tab from last field in section | Next section header focused |P |
| 2.8.4 | Enter on focused header | Section expands, first input focused |P |
| 2.8.5 | Space on focused header | Same as Enter |P |
| 2.8.6 | Escape in section | Section collapses (optional) |P |

### 2.9 Save & Navigation

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.9.1 | "Save as Draft" always enabled | Button clickable |P |
| 2.9.2 | Click "Save as Draft" | Entry saved, indicator shown |P |
| 2.9.3 | "Save & Next" disabled if invalid | Button grayed out |P |
| 2.9.4 | Fill all required fields | "Save & Next" enabled |P |
| 2.9.5 | Click "Save & Next" | Entry saved, advances to next |P |
| 2.9.6 | On last entry, "Save & Next" → complete | Session complete modal |F; the last entry has the 'Next' button greyed out. The session complete only registers when clicking on anyother entry and prompts the review pop up. The review pop up should only show when clicking 'Complete review' button on the last entries screen. This button will take users to the review section of the application that we have yet to work on.|
| 2.9.7 | Click "Previous" button | Goes to previous entry |P |
| 2.9.8 | Click entry dot | Goes to that entry |P |
| 2.9.9 | Entry dots show status colors | Draft=yellow, Complete=green |P |

### 2.10 Auto-Save

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.10.1 | Make changes, wait 30 seconds | Auto-save indicator appears |P |
| 2.10.2 | Auto-save doesn't advance entry | Stays on current entry |P |
| 2.10.3 | Auto-saved entry loadable | Changes persist on reload |P |

### 2.11 Unsaved Changes

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.11.1 | Make changes, click "← Back" | Prompt appears |P |
| 2.11.2 | Click "Save & Exit" in prompt | Entry saved, returns to landing |P |
| 2.11.3 | Click "Discard & Exit" | Changes lost, returns to landing |P |
| 2.11.4 | Click "Cancel" | Stays on entry |P |
| 2.11.5 | Navigate with no changes | No prompt, navigates directly |P |

---

## Section 3: Subject Search & Tags (Stage 4)

### 3.1 Fuzzy Search

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 3.1.1 | Type "cardio" | Finds "Cardiology" |P |
| 3.1.2 | Type "knolwedge" (typo) | Finds "Knowledge Gap" |P |
| 3.1.3 | Type "xyz123" (no match) | Shows "No results" |P |
| 3.1.4 | Search is case-insensitive | "CARDIO" finds "Cardiology" |P |
| 3.1.5 | Results show full path | "System > Topic > Subtopic" |P |

### 3.2 Keyboard Navigation

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 3.2.1 | Arrow Down | Next item highlighted |P |
| 3.2.2 | Arrow Up | Previous item highlighted |P |
| 3.2.3 | Arrow Down at bottom | Wraps to top (or stops) |P |
| 3.2.4 | Arrow Up at top | Wraps to bottom (or stops) |P |
| 3.2.5 | Enter on highlighted | Selects item |P |
| 3.2.6 | Escape | Closes dropdown |P |
| 3.2.7 | Tab | Closes dropdown, moves focus |P |

### 3.3 Tag Hierarchy

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 3.3.1 | Groups show as headers | Bold/distinct styling |P |
| 3.3.2 | Leaf tags indented under groups | Visual hierarchy |P |
| 3.3.3 | Clicking group does nothing | No selection |P |
| 3.3.4 | Clicking leaf tag selects | Tag chip added |P |
| 3.3.5 | Search filters both groups and tags | Matching items shown |P |

### 3.4 Inline Tag Creation

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 3.4.1 | Type non-matching text | "Create" option appears |P |
| 3.4.2 | Click "Create" | Group selection shown |P |
| 3.4.3 | Select group | Tag created, chip added |P |
| 3.4.4 | New tag appears in future searches | Persisted to database |P |

---

## Section 4: Media Handling (Stage 5)

### 4.1 Upload Methods

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 4.1.1 | Click "browse" link | File picker opens |P |
| 4.1.2 | Select image file | Uploads, thumbnail appears |P |
| 4.1.3 | Drag image over dropzone | Visual feedback (highlight) |P |
| 4.1.4 | Drop image | Uploads, thumbnail appears |P |
| 4.1.5 | Copy image, Ctrl+V | Uploads, thumbnail appears |P |
| 4.1.6 | Upload multiple files at once | All upload, thumbnails appear |P |

### 4.2 File Type Support

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 4.2.1 | Upload PNG | Success |P |
| 4.2.2 | Upload JPG/JPEG | Success |P |
| 4.2.3 | Upload GIF | Success |P |
| 4.2.4 | Upload WebP | Success | |
| 4.2.5 | Upload BMP | Success | |
| 4.2.6 | Upload SVG | Success (no thumbnail) | |
| 4.2.7 | Upload non-image file | Rejected with error |P |

### 4.3 Thumbnail Display

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 4.3.1 | Thumbnail shows after upload | Visible in grid |P |
| 4.3.2 | Filename shown below thumbnail | Truncated if long |P |
| 4.3.3 | Action buttons visible | View, Rename, Delete icons |P |
| 4.3.4 | Multiple thumbnails in grid | Grid layout adjusts |P |

### 4.4 View Full Size

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 4.4.1 | Click thumbnail | Full-size modal opens |P |
| 4.4.2 | Click view button (eye icon) | Full-size modal opens |P |
| 4.4.3 | Click outside modal | Modal closes |P |
| 4.4.4 | Press Escape | Modal closes |P |
| 4.4.5 | Click × button | Modal closes P| |
| 4.4.6 | Image displays at full resolution | Not pixelated | P|

### 4.5 Rename

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 4.5.1 | Click rename button (pencil) | Rename modal opens |P |
| 4.5.2 | Current name pre-filled | Without extension |P |
| 4.5.3 | Enter new name | Text updates | P|
| 4.5.4 | Click "Save" | Name changes, modal closes |P |
| 4.5.5 | Press Enter | Same as Save |P |
| 4.5.6 | Click "Cancel" | No change, modal closes |P |
| 4.5.7 | Press Escape | Same as Cancel |P |
| 4.5.8 | Extension preserved | .png stays .png |P |

### 4.6 Delete

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 4.6.1 | Click delete button (trash) | Confirmation modal opens |P |
| 4.6.2 | Click "Delete" | File removed, thumbnail gone |P |
| 4.6.3 | Click "Cancel" | No change, modal closes |P |
| 4.6.4 | Deleted file not recoverable | File removed from disk |P |

### 4.7 Sort

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 4.7.1 | "Sort by Name" button visible | When 2+ files |P |
| 4.7.2 | Click "Sort by Name" | Thumbnails reorder alphabetically |P |
| 4.7.3 | Order persists after save | Reload shows same order |P |

### 4.8 Edge Cases

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 4.8.1 | Upload before entry saved | Shows error message |P |
| 4.8.2 | Upload 10+ images | All display correctly |P |
| 4.8.3 | Upload large file (5MB+) | Uploads (may be slow) |P |
| 4.8.4 | Filename with special chars | Handles correctly |P |
| 4.8.5 | Very long filename | Truncates in display |P |

---

## Section 5: Integration & Workflow

### 5.1 Complete Workflow

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 5.1.1 | Create new session | Session created |P |
| 5.1.2 | Complete first entry | Advances to second |P |
| 5.1.3 | Save second as draft | Draft saved |P |
| 5.1.4 | Navigate back to first | First entry loads |P |
| 5.1.5 | Navigate to draft (second) | Draft loads with data |P |
| 5.1.6 | Complete all entries | Session complete modal |P |
| 5.1.7 | Return to landing page | Session shows in "Previous" |P |

### 5.2 Session Continuation

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 5.2.1 | Start session with 5 incorrect | 5 entry slots created |P |
| 5.2.2 | Complete 2, save 1 draft, leave 2 | Session incomplete |P |
| 5.2.3 | Return to landing page | Session shows "Continue" |P |
| 5.2.4 | Click "Continue" | Opens at first incomplete |P |
| 5.2.5 | Complete remaining entries | Session marked complete |P |

### 5.3 Data Persistence

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 5.3.1 | Create entry, restart app | Entry persists |P |
| 5.3.2 | Upload media, restart app | Media persists |P |
| 5.3.3 | Create tag, restart app | Tag persists |P |
| 5.3.4 | Session data survives restart | All data intact |P |

---

## Section 6: Error Handling

### 6.1 Error Messages

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 6.1.1 | Invalid form submission | Helpful error shown |P |
| 6.1.2 | Media upload failure | Error toast/message |P |
| 6.1.3 | Database error | Error handled gracefully |P |
| 6.1.4 | Network-style errors | Appropriate message |P |

### 6.2 Loading States

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 6.2.1 | Session setup page load | Loading indicator |P |
| 6.2.2 | Entry save operation | Button shows loading |P |
| 6.2.3 | Media upload | Upload progress shown |P |
| 6.2.4 | Search loading | Indicator in dropdown |P |

---

## Bugs Found

| # | Description | Severity | Status | Notes |
|---|-------------|----------|--------|-------|
| | | | | |

---

## Test Summary

| Section | Total | Pass | Fail | Skip |
|---------|-------|------|------|------|
| 1. Session Setup | 26 | | | |
| 2. Question Entry | 46 | | | |
| 3. Search & Tags | 17 | | | |
| 4. Media Handling | 32 | | | |
| 5. Integration | 12 | | | |
| 6. Error Handling | 8 | | | |
| **Total** | **141** | | | |

---

**Tester:** _______________  
**Date:** _______________  
**Build/Version:** _______________
