# Phase 4 Stage 2: Session Setup - Manual Test Checklist

**Version:** 1.0  
**Created:** December 27, 2025  
**Purpose:** Manual testing guide for Phase 4 Stage 2 - Session Setup UI

---

## Pre-Test Setup

1. [x] Start the application: `python run_wimi.py`
2. [x] Open developer tools (F12) to monitor for JavaScript errors
3. [x] Ensure you have at least one exam created (for testing)
4. [x] Clear any previous test sessions if needed

---

## 1. Navigation to Session Setup

### 1.1 From Landing Page
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 1.1.1 | New Review button exists | View exam card on landing page | "📝 New Review" button visible |P | |
| 1.1.2 | Navigate to session setup | Click "📝 New Review" button | Navigates to session_setup.html with exam_id param |P | |
| 1.1.3 | Exam name displays | View session setup header | Correct exam name shown in header |P | |
| 1.1.4 | Back button works | Click "← Back" | Returns to landing page |P | |

### 1.2 Direct URL Access
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 1.2.1 | Missing exam_id | Navigate to session_setup.html (no params) | Error toast, redirects to landing | | |
| 1.2.2 | Invalid exam_id | Navigate with invalid exam_id | Error handling (toast or redirect) | | |

---

## 2. Previous Sessions Display

### 2.1 Empty State
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 2.1.1 | No previous sessions | Open session setup for exam with no sessions | "No previous review sessions" message shown |P | |
| 2.1.2 | Loading indicator | Observe during page load | Loading spinner appears briefly |P | |

### 2.2 Session Cards (After Creating Sessions)
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 2.2.1 | Session card display | Create a session, return to setup | Card shows session name, date, stats |P | |
| 2.2.2 | Progress bar | View card for incomplete session | Progress bar shows X% complete |P | |
| 2.2.3 | Completion badge | View completed vs in-progress sessions | Correct status badges shown |P | |
| 2.2.4 | Continue button | View incomplete session card | "Continue" button visible |P | |
| 2.2.5 | View button | View completed session card | "View" button visible | | |
| 2.2.6 | Delete button | View any session card | "Delete" button visible | P| |
| 2.2.7 | Multiple sessions | Create 3+ sessions | All cards display correctly |P | |
| 2.2.8 | Horizontal scroll | Create many sessions | Container scrolls horizontally |P | |

### 2.3 Session Card Actions
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 2.3.1 | Continue session | Click "Continue" on incomplete session | Navigates to question_entry.html with session_id | | |
| 2.3.2 | View session | Click "View" on completed session | Navigates to question_entry with mode=view | | |
| 2.3.3 | Delete confirmation | Click "Delete" on session | Delete confirmation modal appears |P | |
| 2.3.4 | Cancel delete | Click "Cancel" in delete modal | Modal closes, session remains |P | |
| 2.3.5 | Confirm delete | Click "Delete Session" in modal | Session deleted, card removed, toast shown |P | |

---

## 3. New Session Form

### 3.1 Form Fields Display
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 3.1.1 | Exam context field | View form | Exam name shown, field is disabled/readonly |P | |
| 3.1.2 | Question source dropdown | View form | Dropdown with "Select a source..." default |P | |
| 3.1.3 | Date encountered field | View form | Date picker with today's date as default |P | |
| 3.1.4 | Total questions field | View form | Number input with placeholder |P | |
| 3.1.5 | Questions incorrect field | View form | Number input with placeholder |P | |
| 3.1.6 | Session name field | View form | Optional text field with placeholder |P | |
| 3.1.7 | Required indicators | View form | Red asterisks on required fields |P | |
| 3.1.8 | Help text | View form | Help text visible under each field |P | |

### 3.2 Form Validation
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 3.2.1 | Start button disabled | Load page with empty form | "Start Session" button disabled |P | |
| 3.2.2 | All required filled | Fill all required fields | Button becomes enabled |P | |
| 3.2.3 | Incorrect > Total | Set incorrect > total questions | Error message shown, button disabled |P | |
| 3.2.4 | Zero total questions | Enter 0 for total questions | Error message shown |P | |
| 3.2.5 | Negative incorrect | Enter negative value | Error message or input rejection |P | |
| 3.2.6 | Clear required field | Fill form, then clear a field | Button becomes disabled |P | |

### 3.3 Start Session
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 3.3.1 | Create session success | Fill form, click "Start Session" | Success toast, navigates to question_entry |P | |
| 3.3.2 | Auto-generated name | Leave session name empty | Name generated as "{Source} - {Date}" |P | |
| 3.3.3 | Custom session name | Enter custom name | Session created with custom name |P | |
| 3.3.4 | Loading state | Click "Start Session" | Button shows spinner during creation |P | |
| 3.3.5 | Session appears in list | Create session, go back to setup | New session card visible |P | |

---

## 4. Question Source Management

### 4.1 Add New Source (Inline)
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 4.1.1 | Add button visible | View source dropdown area | "+ Add New" button visible |P | |
| 4.1.2 | Open add modal | Click "+ Add New" | Add source modal opens |P | |
| 4.1.3 | Modal fields | View add source modal | Name, Type, Description fields present |P | |
| 4.1.4 | Cancel add | Click "Cancel" | Modal closes, no source added |P | |
| 4.1.5 | Add source success | Fill name, click "Add Source" | Modal closes, source added to dropdown |P | |
| 4.1.6 | New source selected | Add source | Newly added source auto-selected |P | |
| 4.1.7 | Empty name error | Click "Add Source" with empty name | Error toast shown |P | |
| 4.1.8 | All source types | Open type dropdown | All 11 source types available |P | |

### 4.2 Manage Sources Modal
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 4.2.1 | Open manage modal | Click "Manage Sources" | Modal opens with sources list |P | |
| 4.2.2 | Empty sources state | Open with no sources | "No question sources yet" message |P | |
| 4.2.3 | Sources listed | Open with existing sources | All sources shown with edit buttons |P | |
| 4.2.4 | Add from manage | Click "+ Add New Source" in modal | Add modal opens (manage modal closes) |P | |
| 4.2.5 | Close modal | Click "Close" | Modal closes |P | |
| 4.2.6 | Backdrop click close | Click outside modal | Modal closes |P | |
| 4.2.7 | ESC key close | Press Escape | Modal closes |P | |

### 4.3 Edit Source
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 4.3.1 | Open edit modal | Click edit (✏️) on a source | Edit modal opens with pre-filled data |P | |
| 4.3.2 | Edit name | Change name, save | Name updated in dropdown |P | |
| 4.3.3 | Edit type | Change type, save | Type updated |P | |
| 4.3.4 | Edit description | Change description, save | Description updated |P | |
| 4.3.5 | Cancel edit | Click "Cancel" | Returns to manage modal, no changes |P | |
| 4.3.6 | Save changes | Click "Save Changes" | Success toast, returns to manage |P | |
| 4.3.7 | Empty name error | Clear name, save | Error toast shown |P | |

### 4.4 Delete Source
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 4.4.1 | Delete button | Open edit modal | "Delete" button visible (red) |P | |
| 4.4.2 | Delete confirmation | Click "Delete" | Confirmation modal appears |P | |
| 4.4.3 | Cancel delete | Click "Cancel" in confirmation | Returns to edit modal |P | |
| 4.4.4 | Confirm delete | Click "Delete" in confirmation | Source removed, returns to manage |P | |
| 4.4.5 | Dropdown updated | Delete a source | Source removed from dropdown |P | |
| 4.4.6 | Selected source deleted | Delete currently selected source | Dropdown resets to "Select a source..." |P | |

---

## 5. UI/UX Quality

### 5.1 Visual Design
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 5.1.1 | Consistent styling | View entire page | Matches WIMI design system |P | |
| 5.1.2 | Card shadows | View session cards | Proper shadows and hover effects |P | |
| 5.1.3 | Button styles | View all buttons | Consistent primary/secondary styling |P | |
| 5.1.4 | Form styling | View form fields | Consistent input styling |P | |
| 5.1.5 | Progress bars | View session progress | Smooth gradient, correct colors |P | |
| 5.1.6 | Badges | View status badges | Correct colors for each status |P | |

### 5.2 Responsive Behavior
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 5.2.1 | Form row layout | View question count fields | Side-by-side on desktop |P | |
| 5.2.2 | Modal sizing | Open any modal | Modal properly sized, not cut off |P | |
| 5.2.3 | Long session name | Create session with very long name | Name truncates properly in card |P | |

### 5.3 Loading States & Feedback
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 5.3.1 | Page load spinner | Observe page load | Loading indicators during fetch |P | |
| 5.3.2 | Button spinners | Submit any form | Spinner in button during submission |P | |
| 5.3.3 | Success toasts | Complete any action | Green success toast appears |P | |
| 5.3.4 | Error toasts | Trigger any error | Red error toast with message |P | |
| 5.3.5 | Toast auto-dismiss | Observe toast | Disappears after ~4 seconds |P | |
| 5.3.6 | Toast close button | Click X on toast | Toast closes immediately |P | |

---

## 6. Error Handling

### 6.1 Network/API Errors
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 6.1.1 | API not ready | (Hard to test) Check console | No unhandled exceptions |P | |
| 6.1.2 | Database error | (If testable) Simulate error | Error toast with message |P | |

### 6.2 Input Edge Cases
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 6.2.1 | Special characters in name | Create source with &, <, >, quotes | Handles properly (escaped) |P | |
| 6.2.2 | Very long source name | Create source with 100+ chars | Truncates or wraps properly |P | |
| 6.2.3 | Unicode characters | Enter emoji or unicode in names | Displays correctly |P | |
| 6.2.4 | Large numbers | Enter 99999 for question counts | Accepts or shows appropriate limit |P | |

---

## 7. Integration Points

### 7.1 Database Persistence
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 7.1.1 | Session persists | Create session, refresh page | Session still exists |P | |
| 7.1.2 | Source persists | Create source, refresh page | Source still in dropdown |P | |
| 7.1.3 | Session deletion | Delete session, refresh | Session stays deleted |P | |
| 7.1.4 | Source deletion | Delete source, refresh | Source stays deleted |P | |

### 7.2 Navigation Integration
| # | Test | Steps | Expected Result | Pass/Fail | Notes |
|---|------|-------|-----------------|-----------|-------|
| 7.2.1 | Question entry redirect | Start session | Correct session_id in URL |P | |
| 7.2.2 | Question entry loads | Navigate to question entry | Page loads (placeholder is OK) |P | |
| 7.2.3 | Session ID passed | Check question entry debug info | Shows correct session data |P | |

---

## 8. Keyboard Accessibility

| # | Shortcut | Action | Expected Result | Pass/Fail |
|---|----------|--------|-----------------|-----------|
| 8.1 | Tab | Navigate form | Focus moves through fields |P, Tabbing from one card leads to the draft button, not the next card |
| 8.2 | Enter | In text fields | Submits form if valid |P |
| 8.3 | Escape | In modal | Closes modal |P |
| 8.4 | Enter | In source name field (add modal) | Adds source |P |

---

## Test Summary

| Section | Total Tests | Passed | Failed | Blocked | Notes |
|---------|-------------|--------|--------|---------|-------|
| 1. Navigation | 6 | | | | |
| 2. Previous Sessions | 13 | | | | |
| 3. New Session Form | 14 | | | | |
| 4. Source Management | 20 | | | | |
| 5. UI/UX Quality | 12 | | | | |
| 6. Error Handling | 6 | | | | |
| 7. Integration | 6 | | | | |
| 8. Keyboard | 4 | | | | |
| **TOTAL** | **81** | | | | |

---

## Issues Found

| # | Test ID | Description | Severity | Status |
|---|---------|-------------|----------|--------|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |

**Severity Levels:** Critical, High, Medium, Low, Cosmetic

---

## Environment

- **OS:** Windows 10
- **Python Version:** ___________
- **PyQt6 Version:** ___________
- **Browser (DevTools):** ___________

---

## Notes & Observations

- 
- 
- 

---

**Tested By:** ________________  
**Date:** ________________  
**Build/Version:** ________________
