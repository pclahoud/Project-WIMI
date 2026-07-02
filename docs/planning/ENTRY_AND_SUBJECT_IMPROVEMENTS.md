# Entry Page & Subject Selection Improvements

**Last Updated:** 2026-02-25

---

## Overview

Three related improvements to the entry form and subject selection experience:

1. **Add More Entries** — Ability to add entries beyond the initial session count, plus edit session details from session cards
2. **Image Subject Search** — Search for and assign subjects from the full exam hierarchy in the media subject assignment modal
3. **Notes Subject Search** — Same search capability in the notes subject selection (converted to a modal)

Features 2 and 3 share a **reusable subject search + select widget**.

---

## Feature 1: Add More Entries to a Session

### Current Behavior
- User creates a review session specifying total incorrect questions (e.g., 20)
- Entry form creates exactly that many slots, navigated via "Save & Next"
- Once all slots are filled, session is marked "completed"
- No way to add more entries or edit session details after creation

### Changes

#### 1A: "Add Entries" Button on Entry Page

**Location:** Top-right of the entry form, next to the save status icon.

**Behavior:**
1. User clicks "Add Entries" button
2. Small popover/dialog appears: "How many entries to add?" with a number input (default 1, min 1, max 50) and "Add" / "Cancel" buttons
3. On confirm:
   - Update session `total_incorrect` by adding N
   - If session was "completed", revert status to "in_progress" and clear `completed_at`
   - Regenerate navigation dots to include new empty slots
   - Show toast: "Added N entry slots"
4. New slots appear as empty dots in the navigation, user can navigate to them

**Files to modify:**
- `src/web/html/question_entry.html` — Add button in the header area near save status
- `src/web/js/question_entry.js` — Add entries logic, navigation dot regeneration, session update
- `src/web/css/entry.css` — Styling for the add-entries button and popover
- `src/web/js/api.js` — No changes needed (uses existing `updateReviewSession`)
- `src/app/bridge.py` — No changes needed (passes through to `user_db`)
- `src/database/user_db.py` — Add `total_incorrect` and `total_questions` to `update_review_session()` allowed fields

#### 1B: Edit Session from Session Card

**Location:** Session cards in the session setup page (`session_setup.html`).

**Behavior:**
1. Add an "Edit" button (pencil icon) to each session card's action area
2. Clicking opens an edit modal with:
   - Session name (text input, pre-filled)
   - Total incorrect count (number input, pre-filled)
     - Cannot be set below the current `entries_completed` count
   - Save / Cancel buttons
3. On save:
   - Call `updateReviewSession()` with new name and/or total_incorrect
   - If total_incorrect was reduced and equals entries_completed, set status to "completed"
   - If total_incorrect was increased and session was "completed", revert to "in_progress"
   - Refresh session cards list

**Files to modify:**
- `src/web/html/session_setup.html` — Add edit modal HTML
- `src/web/js/session_setup.js` — Edit button handler, modal logic, save logic
- `src/web/css/session.css` — Modal styling (follow existing modal patterns)

#### Database Change

**`src/database/user_db.py` — `update_review_session()`:**

Add `total_incorrect` and `total_questions` to the `allowed_fields` set:
```python
allowed_fields = {
    'session_name', 'session_status', 'entries_completed', 'completed_at',
    'total_incorrect', 'total_questions'
}
```

### Edge Cases

- **Session status sync:** Adding entries to a "completed" session reverts to "in_progress". Reducing entry count to match completed entries marks as "completed".
- **Minimum count:** Cannot set total_incorrect below entries_completed (validated in UI and backend)
- **Navigation dots:** Must dynamically grow/shrink. New dots appear as empty/draft state.
- **Analytics:** Live queries, so adding entries to a completed session naturally updates analytics on next view. No special handling needed.
- **Concurrent edits:** If user has the entry form open and edits session from another tab — unlikely for a local app, but the entry form should reload session info when navigating.

---

## Feature 2: Image Subject Search — Assign Non-Entry Subjects

### Current Behavior
- Media subject assignment modal shows only entry subjects (primary + secondary) as checkboxes, grouped by dimension
- No way to assign a subject that isn't already on the entry
- Modal defined inline in `media_upload.js`

### Changes

**Updated modal layout (top to bottom):**
1. Image preview (existing)
2. "Select which subjects this image relates to:" hint (existing)
3. Entry subjects grouped by dimension as checkboxes (existing)
4. Divider
5. **New: Subject search bar** — "Search for additional subjects..."
6. **New: Search results dropdown** — Shows matching subjects from full exam hierarchy, excluding already-listed subjects
7. **New: Additional subjects section** — Chips for search-added subjects with remove (x) buttons
8. Save / Cancel buttons (existing)

**Search behavior:**
- Uses the existing `FuzzySearch` class and the already-loaded `EntryState.subjects` index (all subjects for the exam, loaded at entry form init)
- Minimum 2 characters to trigger search
- Results show subject name + full path + dimension, with fuzzy highlighting
- Selecting a result adds it to the "additional subjects" section as a chip with a checkbox (checked by default)
- Subjects already in the entry checkbox list are excluded from search results
- Subjects already added via search are excluded from results

**Persistence:**
- Media `linked_subject_ids` already stores an array of subject node IDs — no schema change needed
- Search-added subjects are saved alongside entry subjects in the same `linked_subject_ids` field
- When the modal reopens, subjects in `linked_subject_ids` that aren't entry subjects appear in the "additional subjects" section

**Independence from entry subjects:**
- `syncMediaSubjects()` (called when entry subjects change) must NOT remove search-added subjects
- Need to distinguish entry subjects from search-added subjects: compare `linked_subject_ids` against current entry subjects; any ID not in entry subjects is search-added

**Files to modify:**
- `src/web/js/media_upload.js` — Update `showSubjectAssignmentModal()`, add search input/results, additional subjects section, save logic
- `src/web/css/media.css` — Styles for search bar, results dropdown, additional subjects chips

**Files NOT modified (reuse existing):**
- `src/web/js/fuzzy_search.js` — Already loaded, already has the index
- `src/web/js/api.js` — Existing `updateMediaLinkedSubjects()` works as-is
- `src/app/bridge.py` — Existing `updateMediaLinkedSubjects()` works as-is
- `src/database/user_db.py` — `linked_subject_ids` JSON column already accepts any subject IDs

### Edge Cases

- **Orphaned subject display:** When viewing entry detail or reopening the modal, subjects not on the entry need their names resolved. Current `linked_subject_ids` only stores IDs. The modal must look up names from `EntryState.subjects` (the full exam subject list). If a subject was deleted from the hierarchy, show "Unknown Subject (ID: X)" with option to remove.
- **Duplicate prevention:** Search results exclude IDs already in the entry checkbox list AND already in the additional subjects section.
- **Subject removal from entry:** If a user removes a subject from the entry's primary/secondary list, and that subject was also checked in the media modal, it should move to the "additional subjects" section (not be deleted). The `syncMediaSubjects()` currently auto-removes — this needs to change to preserve independently-added subjects.
- **Modal reopen state:** When reopening the modal for a media item, reconstruct the view: entry subjects as checkboxes (checked if in `linked_subject_ids`), remaining `linked_subject_ids` shown as additional subject chips.
- **Large hierarchies:** Fuse.js search on the existing client-side index is fast (already handles full exam hierarchies). No performance concern.
- **Dimension context:** Search is inherently scoped to the current exam's subjects since `EntryState.subjects` is loaded per-exam.

---

## Feature 3: Notes Subject Search — Assign Non-Entry Subjects

### Current Behavior
- Inline popover shows entry subjects as checkboxes
- No search, no way to pick subjects outside the entry
- Popover is small and inline within the note card

### Changes

**Convert popover to a proper modal** (same pattern as the media subject modal).

**Modal layout (top to bottom):**
1. Note preview/title area (note number or first line of content)
2. "Select which subjects this note relates to:" hint
3. Entry subjects as checkboxes (existing logic, moved to modal)
4. Divider
5. **New: Subject search bar** — Same reusable component as Feature 2
6. **New: Search results dropdown**
7. **New: Additional subjects section** — Chips with remove buttons
8. Save / Cancel buttons

**Shares the same search widget pattern as Feature 2.** The `FuzzySearch` class and `EntryState.subjects` index are already available.

**Persistence:**
- `entry_notes.linked_subject_ids` already stores a JSON array — no schema change needed
- Same independence model as media: search-added subjects persist alongside entry subjects

**Independence from entry subjects:**
- `syncNoteSubjects()` currently filters out subjects removed from entry. Must change to preserve search-added subjects (same logic as Feature 2).

**Files to modify:**
- `src/web/js/question_entry.js` — Replace `editNoteSubjects()` popover with modal, add search + additional subjects section
- `src/web/css/entry.css` — Modal styling for note subject selection
- `src/web/html/question_entry.html` — Add modal HTML container (or generate dynamically)

**Detail view update:**
- `src/web/js/entry_detail.js` — Tab labels for non-entry subjects must resolve names from the database. Currently tabs are built from entry subject names. Need to look up names for any `linked_subject_ids` not in the entry's subject list.

### Edge Cases

- Same as Feature 2 (orphaned subjects, duplicate prevention, sync behavior, modal reopen state)
- **Detail view tabs:** If a note links to a subject not on the entry, the tab must still display the subject name. Requires fetching subject info from the full hierarchy or storing subject names alongside IDs.
- **Empty state:** If the entry has no subjects yet and the user opens the note subject modal, only the search bar appears (no checkbox section). This is valid — user can search and add subjects directly.

---

## Reusable Subject Search Widget

Features 2 and 3 should share the same search component. Extract a reusable pattern:

**Component: `SubjectSearchSelect`**

A self-contained UI component that can be embedded in any modal. Provides:
- Search input with placeholder text
- Fuzzy search dropdown using existing `FuzzySearch` class
- Selected subjects displayed as removable chips
- Exclusion list (to prevent duplicates with parent context)
- Callbacks: `onSubjectAdded(subject)`, `onSubjectRemoved(subjectId)`

**Implementation approach:**
- Define as a JavaScript class in `src/web/js/subject_search_widget.js` (new file)
- Takes a container element, the `FuzzySearch` instance, and an exclusion list
- Renders its own DOM (search input + dropdown + chips)
- Both the media modal and notes modal instantiate it with their respective exclusion lists

**Files:**
- `src/web/js/subject_search_widget.js` — New reusable widget class
- `src/web/css/subject_search_widget.css` — New shared styles for the widget

---

## Implementation Order

| Stage | Feature | Description |
|-------|---------|-------------|
| 1 | 1 (DB) | Add `total_incorrect`, `total_questions` to `update_review_session()` allowed fields |
| 2 | 1A | "Add Entries" button + popover on entry page |
| 3 | 1B | Edit session modal on session cards |
| 4 | Shared | Build `SubjectSearchSelect` reusable widget |
| 5 | 2 | Integrate widget into media subject assignment modal |
| 6 | 3 | Convert notes popover to modal, integrate widget |
| 7 | 3 | Update detail view tab resolution for non-entry subjects |
| 8 | All | Testing |

---

## Testing

### Feature 1
- Add entries to an in-progress session — dots grow, new entries saveable
- Add entries to a completed session — status reverts to in_progress
- Edit session name from card — name updates on card and in entry form header
- Edit entry count from card — cannot go below entries_completed
- Reduce count to match completed — session auto-completes

### Features 2 & 3
- Search returns subjects from full exam hierarchy
- Entry subjects excluded from search results
- Search-added subjects persist after modal close and reopen
- Removing an entry subject doesn't remove it from media/notes if independently added
- Detail view shows correct tab labels for non-entry subjects
- Orphaned subject (deleted from hierarchy) shows graceful fallback
- Empty entry subjects state — search still works in modal

---

## Files Summary

### New Files
| File | Purpose |
|------|---------|
| `src/web/js/subject_search_widget.js` | Reusable subject search + select widget |
| `src/web/css/subject_search_widget.css` | Shared styles for the widget |

### Modified Files
| File | Changes |
|------|---------|
| `src/database/user_db.py` | Add `total_incorrect`, `total_questions` to allowed update fields |
| `src/web/html/question_entry.html` | Add entries button, note subject modal container |
| `src/web/js/question_entry.js` | Add entries logic, replace note subject popover with modal + search |
| `src/web/css/entry.css` | Add entries button/popover styles, note subject modal styles |
| `src/web/html/session_setup.html` | Edit session modal HTML |
| `src/web/js/session_setup.js` | Edit button, modal logic, save/validation |
| `src/web/css/session.css` | Edit modal styles |
| `src/web/js/media_upload.js` | Search bar + additional subjects in media modal |
| `src/web/css/media.css` | Search bar and additional subjects styles |
| `src/web/js/entry_detail.js` | Resolve non-entry subject names for note tabs |
