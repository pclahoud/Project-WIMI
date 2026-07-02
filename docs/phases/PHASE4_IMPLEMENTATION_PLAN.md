# Phase 4: Question Entry System (WIMI Core)

**Document Version:** 1.5  
**Created:** December 26, 2025  
**Last Updated:** December 27, 2025  
**Status:** 🚧 IN PROGRESS - Stages 1-5 Complete, Stage 6 In Progress

---

## Table of Contents

1. [Phase 4 Overview](#phase-4-overview)
2. [Prerequisites](#prerequisites)
3. [Workflow Design](#workflow-design)
4. [Screen Specifications](#screen-specifications)
5. [Database Schema Changes](#database-schema-changes)
6. [Implementation Stages](#implementation-stages)
7. [UI/UX Specifications](#uiux-specifications)
8. [API Requirements](#api-requirements)
9. [Timeline Estimate](#timeline-estimate)
10. [Success Criteria](#success-criteria)

---

## Phase 4 Overview

### Goals

Phase 4 implements the **Question Entry System** - the core metacognitive reflection feature that makes WIMI unique. This enables students to document incorrect answers, reflect on their thought processes, categorize errors, and build a searchable knowledge base of their mistakes.

### Core Value Proposition

WIMI's differentiation comes from structured metacognitive reflection. When students analyze WHY they got a question wrong (not just WHAT the right answer was), they build deeper understanding and reduce repeated mistakes.

### Key Features

| Feature | Description | Priority |
|---------|-------------|----------|
| **Session-Based Entry** | Create review sessions from practice tests | High |
| **Question Entry Form** | Comprehensive form for documenting mistakes | High |
| **Subject Mapping** | Link questions to subject hierarchy | High |
| **Hierarchical Tags** | Categorize mistakes with nested tag groups | High |
| **Metacognitive Reflection** | Free-text reflection (required) | High |
| **Explanation Field** | Document correct answer reasoning (required) | High |
| **Media Attachments** | Paste/upload images and screenshots | High |
| **Draft Management** | Save incomplete entries, return later | High |
| **Session Continuation** | Resume incomplete sessions | High |
| **Auto-Save** | Periodic draft saving | Medium |

### User Stories

1. **As a student**, I want to start a review session after completing a practice test so I can log all my mistakes in one workflow.
2. **As a student**, I want to quickly enter basic info and come back later for deeper reflection.
3. **As a student**, I want to categorize my mistakes so I can identify patterns over time.
4. **As a student**, I want to link questions to specific topics so I know what to study.
5. **As a student**, I want to paste screenshots of questions for reference.
6. **As a student**, I want to continue an incomplete session from where I left off.

---

## Prerequisites

### Completed in Phase 3 ✅

- [x] Landing page with exam cards
- [x] Subject hierarchy tree editor
- [x] Weight management system
- [x] Import/export functionality
- [x] 256 tests passing, 83% coverage

### Required Before Starting Phase 4

- [x] Phase 4 design document finalized
- [x] Database schema changes planned
- [x] All Phase 3 features working

---

## Workflow Design

### Complete User Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MAIN SCREEN                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │
│  │  USMLE Step 1│  │     SAT      │  │     GRE      │                   │
│  │              │  │              │  │              │                   │
│  │ [New Review  │  │ [New Review  │  │ [New Review  │                   │
│  │   Session]   │  │   Session]   │  │   Session]   │                   │
│  └──────────────┘  └──────────────┘  └──────────────┘                   │
└─────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      SESSION SETUP SCREEN                                │
│                                                                          │
│  ┌─ Previous Sessions ──────────────────────────────────────────────┐   │
│  │ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐         │   │
│  │ │ UWorld Dec 24  │ │ Amboss Dec 20  │ │ UWorld Dec 18  │   ...   │   │
│  │ │ 3/12 complete  │ │ 8/8 complete   │ │ 5/10 complete  │         │   │
│  │ │ [Continue]     │ │ [Review]       │ │ [Continue]     │         │   │
│  │ └────────────────┘ └────────────────┘ └────────────────┘         │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌─ New Session ────────────────────────────────────────────────────┐   │
│  │  Exam Context:        [USMLE Step 1      ▼]  (pre-filled)        │   │
│  │  Question Source:     [UWorld            ▼]  [+ Add New]         │   │
│  │  Date Encountered:    [2025-12-26        📅]  (editable)         │   │
│  │  Total Questions:     [___40___]                                  │   │
│  │  Total Incorrect:     [___12___]                                  │   │
│  │                                                                   │   │
│  │  Session Name:        [________________________] (optional)       │   │
│  │                                                                   │   │
│  │  [Manage Sources]                       [Start Session]          │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [← Back]                QUESTION ENTRY SCREEN                           │
│  Session: UWorld Practice - Dec 26, 2025          Entry 1 of 12         │
│  Exam: USMLE Step 1 (read-only)                                         │
│─────────────────────────────────────────────────────────────────────────│
│                                                                          │
│  ┌─ Section A: Question Info ─────────────────────────────────────┐     │
│  │  Question ID: [________]     Perceived Difficulty: ○○○○○       │     │
│  │  Your Answer: [________]     Time Spent: [____] minutes        │     │
│  │  Correct Answer: [________]                                     │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌─ Section B: Subject Mapping ───────────────────────────────────┐     │
│  │  Primary Subject(s):   [Search subjects...          ] [Browse] │     │
│  │  Selected: [Cardiology > Arrhythmias > AFib ×]                 │     │
│  │                                                                 │     │
│  │  Secondary Subject(s): [Search subjects...          ] [Browse] │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌─ Section C: Tags ──────────────────────────────────────────────┐     │
│  │  [Search tags...                                      ]        │     │
│  │  Selected: [Knowledge Gap ×] [Time Pressure ×]                 │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌─ Section D: Reflection ⭐ ─────────────────────────────────────┐     │
│  │  ┌──────────────────────────────────────────────────────────┐ │     │
│  │  │                                                          │ │     │
│  │  │  (Free text reflection on why you got this wrong...)     │ │     │
│  │  │                                                          │ │     │
│  │  └──────────────────────────────────────────────────────────┘ │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌─ Section E: Explanation ⭐ ────────────────────────────────────┐     │
│  │  ┌──────────────────────────────────────────────────────────┐ │     │
│  │  │                                                          │ │     │
│  │  │  (Why the correct answer is correct...)                  │ │     │
│  │  │                                                          │ │     │
│  │  └──────────────────────────────────────────────────────────┘ │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌─ Section F: Notes & Media ─────────────────────────────────────┐     │
│  │  Notes: [Optional personal notes...]                           │     │
│  │                                                                 │     │
│  │  Media: [Drop images here or paste from clipboard]             │     │
│  │  ┌─────┐ ┌─────┐ ┌─────┐                                       │     │
│  │  │ 📷  │ │ 📷  │ │  +  │  [Sort by Name]                       │     │
│  │  └─────┘ └─────┘ └─────┘                                       │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│       [Save as Draft]                              [Save & Next →]      │
│                                                                          │
│                        Auto-saved at 2:34 PM                            │
└─────────────────────────────────────────────────────────────────────────┘
```

### Back Button Behavior

```
User clicks [← Back]
    │
    ├─ If current entry has unsaved changes:
    │      │
    │      ├─ If all required fields complete:
    │      │      → Prompt: "Save entry before leaving?"
    │      │        [Save & Exit] [Discard & Exit] [Cancel]
    │      │
    │      └─ If required fields missing:
    │             → Prompt: "Save as draft before leaving?"
    │             [Save Draft & Exit] [Discard & Exit] [Cancel]
    │
    └─ If no unsaved changes:
           → Return to main screen
```

---

## Screen Specifications

### Screen 1: Session Setup

#### Previous Sessions Card

| Element | Description |
|---------|-------------|
| Session cards | Horizontal scrollable list of recent sessions for this exam |
| Card content | Session name, date, completion status (X/Y complete) |
| [Continue] button | Shown if incomplete entries remain; resumes at next incomplete entry |
| [Review] button | Shown if all entries complete; opens read-only view (future feature) |

#### New Session Form

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| Exam Context | Dropdown | ✅ Yes | Pre-filled from exam card | Editable |
| Question Source | Dropdown + Add New | ✅ Yes | None | From `question_sources` table |
| Date Encountered | Date picker | ✅ Yes | Today | Editable, applies to all entries |
| Total Questions | Number input | ✅ Yes | None | Total in practice session |
| Total Incorrect | Number input | ✅ Yes | None | Determines entry count |
| Session Name | Text input | ❌ No | Auto-generate | "{Source} - {Date}" if blank |

#### Buttons

| Button | Action |
|--------|--------|
| [Manage Sources] | Opens modal to add/edit/delete question sources |
| [Start Session] | Validates form, creates session record, navigates to entry screen |

---

### Screen 2: Question Entry

#### Header Elements

| Element | Description |
|---------|-------------|
| [← Back] | Returns to main screen with save prompt |
| Session info | Session name and date |
| Entry counter | "Entry X of Y" |
| Exam context | Read-only display of exam name |

#### Section A: Question Information

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Question ID | Text | ❌ No | Reference number, page, URL |
| Your Answer | Text | ✅ Yes | Supports short or long answers |
| Correct Answer | Text | ✅ Yes | Supports short or long answers |
| Perceived Difficulty | 1-5 rating | ❌ No | Visual dot selector |
| Time Spent | Number + unit | ❌ No | Minutes or seconds toggle |

#### Section B: Subject Mapping

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Primary Subject(s) | Multi-select search | ✅ Yes (≥1) | Search with auto-suggest |
| Secondary Subject(s) | Multi-select search | ❌ No | Related but not primary |

**Search Behavior:**
- Fuzzy matching as user types
- 10 results visible, scrollable for more
- Results show full path: `Cardiology > Arrhythmias > AFib`
- Optional tree browser toggle
- Configurable result limit in settings

#### Section C: Tags

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Tags | Hierarchical multi-select | ❌ No | Only leaf nodes selectable |

**Tag Picker Behavior:**
- Search surfaces matching tags as user types
- Shows tag hierarchy path
- Groups not selectable, only leaf tags
- User can create new tags inline
- User can create new groups in settings

#### Section D: Reflection ⭐ (Required)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Reflection | Large textarea | ✅ Yes* | Free text, no prompts |

*Required to complete entry, but drafts allowed without it.

#### Section E: Explanation ⭐ (Required)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Explanation | Large textarea | ✅ Yes | Why correct answer is correct |

#### Section F: Notes & Media

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Notes | Textarea | ❌ No | Personal notes about question |
| Media | File upload area | ❌ No | Paste, drag-drop, or browse |

**Media Handling:**
- Clipboard paste (Ctrl+V)
- Drag and drop
- File picker (browse)
- Formats: PNG, JPG, JPEG, GIF, WebP, BMP, SVG
- No file count limits
- No file size limits
- Thumbnail preview
- Deletable from within app
- Renameable (custom filename)
- Sortable by name
- Auto-linked to entry's primary subject(s)

#### Action Buttons

| Button | Availability | Action |
|--------|--------------|--------|
| **Save & Next →** | All required fields complete | Save as complete, advance to next entry |
| **Save as Draft** | Always | Save current state as draft |

#### Section Collapse Behavior

- **Trigger:** Tab navigation moves to next section header
- **Auto-collapse:** Previous section collapses automatically
- **Auto-expand:** Section expands when header receives focus
- **Keyboard:** Enter/Space on header toggles section and focuses first input
- **Manual control:** User can click any section header to expand/collapse
- **Tab flow:** Tab from last field in section → next section header

#### Auto-Save

- Periodic auto-save (default: 30 seconds)
- Configurable interval in user settings (10-300 seconds)
- Always saves as draft
- Shows "Auto-saved at HH:MM" indicator

---

## Database Schema Changes

### 1. Modify `tags` Table for Hierarchy

```sql
-- Add hierarchy support
ALTER TABLE tags ADD COLUMN parent_id INTEGER REFERENCES tags(id) NULL;
ALTER TABLE tags ADD COLUMN is_group BOOLEAN DEFAULT FALSE;
ALTER TABLE tags ADD COLUMN display_order INTEGER DEFAULT 0;

-- Add indexes
CREATE INDEX idx_tags_parent ON tags(parent_id);
CREATE INDEX idx_tags_hierarchy ON tags(exam_context, parent_id, display_order);
```

**Tag Structure:**
- `is_group = TRUE` → Folder/group (not selectable)
- `is_group = FALSE` → Leaf tag (selectable)
- `parent_id = NULL` → Top-level group
- Maximum nesting depth: 3 levels (Group > Subgroup > Tag)

### 2. Modify `question_media` Table

```sql
-- Add new fields
ALTER TABLE question_media ADD COLUMN user_filename VARCHAR(255);
ALTER TABLE question_media ADD COLUMN linked_subject_ids TEXT CHECK (json_valid(linked_subject_ids));
ALTER TABLE question_media ADD COLUMN sort_order INTEGER DEFAULT 0;
```

### 3. Modify `question_review_sessions` Table

```sql
-- Add session tracking fields
ALTER TABLE question_review_sessions ADD COLUMN total_questions INTEGER;
ALTER TABLE question_review_sessions ADD COLUMN total_incorrect INTEGER;
ALTER TABLE question_review_sessions ADD COLUMN question_source_id INTEGER REFERENCES question_sources(id);
ALTER TABLE question_review_sessions ADD COLUMN date_encountered DATE;
ALTER TABLE question_review_sessions ADD COLUMN entries_completed INTEGER DEFAULT 0;
```

### 4. Modify `question_analyses` Table

```sql
-- Add draft and session tracking
ALTER TABLE question_analyses ADD COLUMN is_draft BOOLEAN DEFAULT FALSE;
ALTER TABLE question_analyses ADD COLUMN draft_missing_fields TEXT CHECK (json_valid(draft_missing_fields));
ALTER TABLE question_analyses ADD COLUMN review_session_id INTEGER REFERENCES question_review_sessions(id);
ALTER TABLE question_analyses ADD COLUMN entry_order INTEGER;
```

### 5. Modify `user_preferences` Table

```sql
-- Add Phase 4 preferences
ALTER TABLE user_preferences ADD COLUMN auto_save_interval_seconds INTEGER DEFAULT 30 
    CHECK (auto_save_interval_seconds BETWEEN 10 AND 300);
ALTER TABLE user_preferences ADD COLUMN subject_search_results_limit INTEGER DEFAULT 10 
    CHECK (subject_search_results_limit BETWEEN 5 AND 50);
ALTER TABLE user_preferences ADD COLUMN show_subject_tree_browser BOOLEAN DEFAULT TRUE;
```

---

## Default Tag Hierarchy (Seeded Per-User)

Tags are seeded per-user when they create their first exam. Users can fully customize.

```
📁 Knowledge Issues (is_group=TRUE, parent_id=NULL)
   ├── Knowledge Gap (is_group=FALSE)
   ├── Memory Failure (is_group=FALSE)
   └── Misunderstanding (is_group=FALSE)

📁 Reading & Interpretation (is_group=TRUE, parent_id=NULL)
   └── Misread Question (is_group=FALSE)

📁 Execution Errors (is_group=TRUE, parent_id=NULL)
   ├── Calculation Error (is_group=FALSE)
   ├── Careless Mistake (is_group=FALSE)
   ├── Incomplete Solution (is_group=FALSE)
   └── Wrong Approach (is_group=FALSE)

📁 Test Strategy (is_group=TRUE, parent_id=NULL)
   ├── Time Pressure (is_group=FALSE)
   ├── Second-Guessing (is_group=FALSE)
   ├── Elimination Error (is_group=FALSE)
   ├── Poor Prioritization (is_group=FALSE)
   └── Wrong Guess Strategy (is_group=FALSE)

📁 Mental & Physical State (is_group=TRUE, parent_id=NULL)
   ├── Anxiety Related (is_group=FALSE)
   ├── Focus Problem (is_group=FALSE)
   └── Fatigue Related (is_group=FALSE)
```

---

## Implementation Stages

```
Stage 1: Database & Backend       ✅ COMPLETE
    ↓
Stage 2: Session Setup UI         ✅ COMPLETE
    ↓
Stage 3: Question Entry UI        ✅ COMPLETE
    ↓
Stage 4: Subject Search & Tag Picker (Enhancements)  ✅ COMPLETE
    ↓
Stage 5: Media Handling
    ↓
Stage 6: Testing & Polish
```

---

### Stage 1: Database & Backend ✅ COMPLETE

**Duration:** 4-6 hours  
**Completed:** December 26, 2025

#### Tasks

1. ✅ Create database migration for all schema changes
2. ✅ Add tag hierarchy management methods to `UserDatabase`
3. ✅ Add session CRUD methods to `UserDatabase`
4. ✅ Add question entry CRUD methods to `UserDatabase`
5. ✅ Add question source management methods
6. ✅ Add media file management utilities (database layer)
7. ✅ Create seed data function for default tags
8. ✅ Write unit tests for all new methods

#### Files Created/Modified

| File | Action | Description | Status |
|------|--------|-------------|--------|
| `src/database/schema/user_db_schema_v1_phase4.sql` | Created | Phase 4 schema (~180 lines) | ✅ |
| `src/database/user_db.py` | Modified | +30 methods (~1,280 lines) | ✅ |
| `src/database/models.py` | Modified | +6 dataclasses (~310 lines) | ✅ |
| `src/database/exceptions.py` | Modified | +6 exception types | ✅ |
| `tests/database/test_user_db_phase4.py` | Created | 25+ test cases (~450 lines) | ✅ |

#### Acceptance Criteria

- [x] All schema migrations apply cleanly
- [x] Tag hierarchy CRUD works with 3-level nesting
- [x] Session CRUD works correctly
- [x] Question entry CRUD with draft support works
- [x] Default tags seed correctly
- [x] Media file utilities work (database layer)
- [x] All unit tests written (25+ cases)

---

### Stage 2: Session Setup UI ✅ COMPLETE

**Duration:** 6-8 hours  
**Completed:** December 27, 2025

#### Tasks

1. ✅ Create session setup page HTML/CSS
2. ✅ Implement previous sessions card display
3. ✅ Implement new session form
4. ✅ Create question source management modal
5. ✅ Add bridge methods for session operations
6. ✅ Wire up navigation from exam cards
7. ✅ Testing and bug fixes (81 manual test cases)

#### Files Created

| File | Action | Description | Status |
|------|--------|-------------|--------|
| `src/web/html/session_setup.html` | Created | Session setup page (~280 lines) | ✅ |
| `src/web/css/session.css` | Created | Session-related styles (~580 lines) | ✅ |
| `src/web/js/session_setup.js` | Created | Session setup logic (~400 lines) | ✅ |

#### Files Modified

| File | Changes | Status |
|------|---------|--------|
| `src/web/js/api.js` | Added Phase 4 Stage 2 API methods | ✅ |
| `src/app/bridge.py` | Added Phase 4 Stage 2 bridge methods | ✅ |
| `src/web/js/landing.js` | Added "New Review Session" button | ✅ |

#### Acceptance Criteria

- [x] Session setup page loads from exam card click
- [x] Previous sessions display with correct status
- [x] [Continue] button resumes incomplete sessions
- [x] New session form validates correctly
- [x] Question source dropdown populates
- [x] [+ Add New] creates new source inline
- [x] [Manage Sources] opens management modal
- [x] [Start Session] creates session and navigates to entry screen

---

### Stage 3: Question Entry UI (Core Form) ✅ COMPLETE

**Duration:** 8-10 hours  
**Completed:** December 27, 2025

#### Tasks

1. ✅ Create question entry page HTML structure
2. ✅ Implement all form sections with collapse behavior
3. ✅ Create difficulty rating component
4. ✅ Create time spent input with unit toggle
5. ✅ Implement Your Answer / Correct Answer fields
6. ✅ Implement Reflection and Explanation textareas
7. ✅ Implement Notes textarea
8. ✅ Add entry counter and navigation
9. ✅ Implement save buttons and back button logic
10. ✅ Implement keyboard navigation between sections
11. ✅ Add subject search with autocomplete
12. ✅ Add hierarchical tag picker
13. ✅ Implement auto-save functionality

#### Files Created

| File | Action | Description | Status |
|------|--------|-------------|--------|
| `src/web/html/question_entry.html` | Created | Question entry page (~280 lines) | ✅ |
| `src/web/css/entry.css` | Created | Entry form styles (~600 lines) | ✅ |
| `src/web/js/question_entry.js` | Created | Entry form logic (~800 lines) | ✅ |

#### Files Modified

| File | Changes | Status |
|------|---------|--------|
| `src/web/js/api.js` | Added Stage 3 API methods | ✅ |
| `src/app/bridge.py` | Added Stage 3 bridge methods (~270 lines) | ✅ |

#### New Bridge Methods (Stage 3)

```python
# Question Entry Operations
def _serialize_question_entry(self, entry) -> dict
def createQuestionEntry(self, entry_data_json: str) -> str
def getQuestionEntry(self, entry_id: int) -> str
def getSessionEntries(self, session_id: int) -> str
def updateQuestionEntry(self, entry_id: int, updates_json: str) -> str
def deleteQuestionEntry(self, entry_id: int) -> str

# Subject Search & Tag Operations
def searchSubjects(self, exam_context_id: int, query: str, limit: int) -> str
def getTagHierarchy(self, exam_context: str) -> str
def seedDefaultTags(self, exam_context: str) -> str
```

#### Features Implemented

| Feature | Status |
|---------|--------|
| 6 collapsible form sections (A-F) | ✅ |
| Keyboard tab navigation between sections | ✅ |
| Section auto-expand on focus | ✅ |
| Difficulty rating (1-5 dots) | ✅ |
| Time spent with minutes/seconds toggle | ✅ |
| Subject search with autocomplete dropdown | ✅ |
| Primary/Secondary subject distinction | ✅ |
| Hierarchical tag picker | ✅ |
| Tag search filtering | ✅ |
| Required field validation | ✅ |
| Draft vs Complete save | ✅ |
| Auto-save (30s interval) | ✅ |
| Entry navigation (prev/next) | ✅ |
| Entry dots showing status | ✅ |
| Unsaved changes modal | ✅ |
| Session complete modal | ✅ |
| Character count on textareas | ✅ |
| Accessibility (ARIA attributes) | ✅ |

#### Acceptance Criteria

- [x] Entry page loads with session context
- [x] All sections render correctly
- [x] Sections collapse on tab navigation
- [x] Manual expand/collapse works
- [x] Keyboard navigation (Tab) flows through sections
- [x] Enter/Space on section header expands and focuses first input
- [x] Required field validation works
- [x] [Save & Next] saves and advances (disabled until valid)
- [x] [Save as Draft] saves draft
- [x] [← Back] shows appropriate save prompt
- [x] Entry counter updates correctly
- [x] Auto-save triggers periodically
- [x] Subject search returns results
- [x] Tag hierarchy displays correctly

---

### Stage 4: Subject Search & Tag Picker (Enhancements) ✅ COMPLETE

**Duration:** 4-6 hours  
**Completed:** December 27, 2025

#### Tasks Completed

1. ✅ Fuse.js fuzzy search integration (bundled locally)
2. ✅ Keyboard navigation module for dropdowns (ARIA-compliant)
3. ✅ Enhanced tag search with hierarchical display
4. ✅ Inline tag creation UI with group selection
5. ✅ Subject search autocomplete improvements
6. ✅ Fixed WebChannel Promise handling in api.js
7. ✅ Fixed tag hierarchy loading from database

#### Files Created

| File | Action | Description | Status |
|------|--------|-------------|--------|
| `src/web/js/fuse.min.js` | Created | Fuse.js v7.1.0 library (~26KB) | ✅ |
| `src/web/js/fuzzy_search.js` | Created | Fuse.js wrapper with fallback (~320 lines) | ✅ |
| `src/web/js/dropdown_keyboard.js` | Created | Keyboard navigation module (~220 lines) | ✅ |

#### Files Modified

| File | Changes | Status |
|------|---------|--------|
| `src/web/html/question_entry.html` | Local Fuse.js script reference | ✅ |
| `src/web/js/question_entry.js` | Tag search, inline creation, fuzzy integration (~200 lines added) | ✅ |
| `src/web/js/api.js` | **Critical fix**: WebChannel Promise handling with `await` | ✅ |
| `src/web/css/entry.css` | Dropdown styles, keyboard hints, overflow fixes (~150 lines added) | ✅ |
| `src/app/bridge.py` | `getAllSubjectsForExam`, `createTagInGroup` methods | ✅ |

#### Key Bug Fixes

1. **WebChannel Promise Handling (Critical)**
   - Issue: `api.js` `_callBridge()` wasn't awaiting Promise from WebChannel
   - Symptom: All bridge calls returned empty/failed silently
   - Fix: Added `await` to `this.bridge[methodName](...args)`
   
2. **Tag Hierarchy Flattening**
   - Issue: `_flattenTagHierarchy()` used incorrect `is_group` detection
   - Symptom: No tags appeared in search results
   - Fix: Check both `is_group === true` AND presence of children

3. **CSS Overflow Clipping**
   - Issue: `.entry-section { overflow: hidden }` clipped dropdowns
   - Fix: Only apply overflow:hidden when section is collapsed

#### New Bridge Methods (Stage 4)

```python
@pyqtSlot(int, result=str)
def getAllSubjectsForExam(self, exam_context_id: int) -> str:
    """Get all subjects for client-side fuzzy search"""

@pyqtSlot(str, str, int, result=str)  
def createTagInGroup(self, exam_context: str, tag_name: str, group_id: int) -> str:
    """Create a new tag within an existing group (inline creation)"""
```

#### Features Implemented

| Feature | Status | Notes |
|---------|--------|-------|
| Fuse.js fuzzy search integration | ✅ | Bundled locally (v7.1.0, ~26KB) |
| Typo-tolerant search | ✅ | "knolwedge" matches "Knowledge" |
| Simple text search fallback | ✅ | Scoring algorithm if Fuse.js fails to load |
| Keyboard navigation (Arrow keys) | ✅ | Up/Down, Enter to select, Escape to close |
| ARIA accessibility attributes | ✅ | role="listbox", aria-selected, aria-activedescendant |
| Tag hierarchy from database | ✅ | 5 groups, 16 leaf tags loaded correctly |
| Tag search with group context | ✅ | Shows "Group > Tag" format |
| Inline tag creation UI | ✅ | Appears when no exact match found |
| Group selection for new tags | ✅ | Radio buttons with color indicators |
| Match highlighting in results | ✅ | `<mark>` tags around matched text |
| Keyboard hint footer | ✅ | "Use ↑↓ to navigate, Enter to select" |

#### Acceptance Criteria

- [x] Subject search returns fuzzy matches (or simple filter fallback)
- [x] Tag search shows hierarchical tags with group names
- [x] Arrow keys navigate dropdown results
- [x] Enter selects highlighted item
- [x] Escape closes dropdown
- [x] ARIA attributes for screen readers
- [x] Inline tag creation shows when no exact match
- [x] New tags can be created in any existing group
- [x] Tag hierarchy loads from SQLite database correctly
- [x] WebChannel bridge calls work properly

#### Known Limitations

1. **No tree browser modal**: Subject tree browser was descoped to future enhancement.

---

### Stage 5: Media Handling ✅ COMPLETE

**Duration:** 4-6 hours  
**Completed:** December 27, 2025

#### Tasks Completed

1. ✅ Implement clipboard paste (Ctrl+V)
2. ✅ Implement drag and drop
3. ✅ Implement file picker
4. ✅ Create thumbnail display with actions (120x120)
5. ✅ Implement rename functionality
6. ✅ Implement delete functionality
7. ✅ Implement sort by name
8. ✅ Create media storage utilities (MediaManager)
9. ✅ Create custom URL scheme handler (wimi-media://)

#### Files Created

| File | Action | Description | Status |
|------|--------|-------------|--------|
| `src/app/media_manager.py` | Created | Media file storage and thumbnails (~380 lines) | ✅ |
| `src/app/media_scheme_handler.py` | Created | Custom URL scheme handler (~130 lines) | ✅ |
| `src/web/js/media_upload.js` | Created | Media upload component (~580 lines) | ✅ |
| `src/web/css/media.css` | Created | Media component styles (~280 lines) | ✅ |

#### Files Modified

| File | Changes | Status |
|------|---------|--------|
| `src/app/main.py` | Register wimi-media:// scheme before QApplication | ✅ |
| `src/app/main_window.py` | Initialize MediaManager, install scheme handler | ✅ |
| `src/app/bridge.py` | 5 media bridge methods added | ✅ |
| `src/database/user_db.py` | 3 new media database methods | ✅ |
| `src/web/js/api.js` | 5 media API methods added | ✅ |
| `src/web/js/question_entry.js` | MediaUpload integration | ✅ |
| `src/web/html/question_entry.html` | Media container and script/css links | ✅ |
| `requirements.txt` | Added Pillow>=10.0.0 | ✅ |

#### New Bridge Methods

```python
@pyqtSlot(int, str, str, str, result=str)
def addQuestionMedia(self, entry_id: int, base64_data: str, filename: str, mime_type: str) -> str

@pyqtSlot(int, result=str)
def getQuestionMedia(self, entry_id: int) -> str

@pyqtSlot(int, str, result=str)
def renameMedia(self, media_id: int, new_name: str) -> str

@pyqtSlot(int, int, result=str)
def deleteMedia(self, entry_id: int, media_id: int) -> str

@pyqtSlot(int, str, result=str)
def reorderMedia(self, entry_id: int, order_json: str) -> str
```

#### Storage Structure

```
app_data/
└── media/
    └── user_{id}_{username}/
        └── entry_{entry_id}/
            ├── {uuid1}.png
            ├── {uuid1}_thumb.jpg
            ├── {uuid2}.jpg
            └── {uuid2}_thumb.jpg
```

#### Features Implemented

| Feature | Status | Notes |
|---------|--------|-------|
| Clipboard paste (Ctrl+V) | ✅ | Global handler when component visible |
| Drag and drop | ✅ | Drop zone with visual feedback |
| File picker | ✅ | Browse button triggers file input |
| Thumbnail generation | ✅ | 120x120 JPEG via Pillow |
| Full-size modal | ✅ | Click to view, Escape to close |
| Rename modal | ✅ | Edit user filename, preserve extension |
| Delete confirmation | ✅ | Modal with cancel/confirm |
| Sort by name | ✅ | Alphabetical with database persistence |
| Custom URL scheme | ✅ | wimi-media://entry_{id}/{uuid} |
| MIME type validation | ✅ | PNG, JPEG, GIF, WebP, BMP, SVG |

#### Acceptance Criteria

- [x] Ctrl+V pastes clipboard images
- [x] Drag and drop works
- [x] File picker works
- [x] All common formats supported
- [x] Thumbnails display correctly (120x120)
- [x] Click thumbnail for full view
- [x] Rename functionality works
- [x] Delete removes file and record
- [x] Sort by name works
- [x] Media loads when switching entries

#### Known Limitations

1. **Large file transfer**: Base64 works for typical screenshots (<1MB). Temp file + path for larger files is TODO.
2. **SVG thumbnails**: SVG files display at full size (no thumbnail generation).

---

### Stage 6: Testing & Polish

**Duration:** 4-6 hours

#### Tasks

1. Write bridge layer tests for all new methods
2. Write integration tests for complete workflows
3. Create manual test checklist for Stage 3
4. Fix any bugs discovered
5. Add loading states and error handling
6. Polish UI transitions and feedback
7. Update documentation

#### Files to Create

| File | Description |
|------|-------------|
| `tests/app/test_bridge_phase4.py` | Bridge tests for Phase 4 |
| `docs/testing/PHASE4_STAGE3_MANUAL_TEST_CHECKLIST.md` | Manual testing guide |

#### Acceptance Criteria

- [ ] All new tests pass
- [ ] Coverage remains above 80%
- [ ] Manual test checklist complete
- [ ] All loading states implemented
- [ ] Error messages display correctly
- [ ] No console errors in normal usage

---

## UI/UX Specifications

### Color Scheme (Existing Design System)

```css
/* Use existing variables from styles.css */
--color-primary: #2563eb;
--color-success: #10b981;
--color-warning: #f59e0b;
--color-danger: #ef4444;
--bg-primary: #ffffff;
--bg-secondary: #f9fafb;
--text-primary: #111827;
--text-secondary: #6b7280;
```

### Form Section Styles

```css
.entry-section {
    border: 1px solid var(--border-color);
    border-radius: 8px;
    margin-bottom: 16px;
    overflow: hidden;
}

.entry-section-header {
    padding: 12px 16px;
    background: var(--bg-secondary);
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.entry-section-header:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: -2px;
}

.entry-section-header.required::after {
    content: '*';
    color: var(--color-danger);
    margin-left: 4px;
}

.entry-section-content {
    padding: 16px;
    display: none;
}

.entry-section.expanded .entry-section-content {
    display: block;
}

.entry-section.collapsed .entry-section-header {
    border-bottom: none;
}
```

### Tag Chip Styles

```css
.tag-chip {
    display: inline-flex;
    align-items: center;
    padding: 4px 8px;
    margin: 2px;
    border-radius: 16px;
    font-size: 13px;
    background: var(--bg-tertiary);
}

.tag-chip .remove {
    margin-left: 6px;
    cursor: pointer;
    opacity: 0.6;
}

.tag-chip .remove:hover {
    opacity: 1;
}

.tag-chip.primary {
    background: var(--color-primary-bg);
    border: 1px solid var(--color-primary);
}

.tag-chip.secondary {
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
}
```

### Media Thumbnail Styles

```css
.media-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
    gap: 12px;
}

.media-thumbnail {
    position: relative;
    aspect-ratio: 1;
    border-radius: 8px;
    overflow: hidden;
    cursor: pointer;
}

.media-thumbnail img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.media-thumbnail .actions {
    position: absolute;
    top: 4px;
    right: 4px;
    opacity: 0;
    transition: opacity 0.2s;
}

.media-thumbnail:hover .actions {
    opacity: 1;
}
```

---

## API Requirements

### New Bridge Methods Summary

| Method | Parameters | Returns | Stage | Status |
|--------|------------|---------|-------|--------|
| `createReviewSession` | `session_data: json` | Session object | 2 | ✅ |
| `getReviewSessions` | `exam_id, include_complete` | List of sessions | 2 | ✅ |
| `getReviewSession` | `session_id` | Session object | 2 | ✅ |
| `updateReviewSession` | `session_id, updates` | Updated session | 2 | ✅ |
| `deleteReviewSession` | `session_id` | Success/error | 2 | ✅ |
| `createQuestionSource` | `source_data: json` | Source object | 2 | ✅ |
| `getQuestionSources` | `exam_context` | List of sources | 2 | ✅ |
| `updateQuestionSource` | `source_id, updates` | Updated source | 2 | ✅ |
| `deleteQuestionSource` | `source_id` | Success/error | 2 | ✅ |
| `createQuestionEntry` | `entry_data: json` | Entry object | 3 | ✅ |
| `getQuestionEntry` | `entry_id` | Entry object | 3 | ✅ |
| `getSessionEntries` | `session_id` | List of entries | 3 | ✅ |
| `updateQuestionEntry` | `entry_id, updates` | Updated entry | 3 | ✅ |
| `deleteQuestionEntry` | `entry_id` | Success/error | 3 | ✅ |
| `searchSubjects` | `exam_id, query, limit` | List of subjects | 3 | ✅ |
| `getTagHierarchy` | `exam_context` | Nested tag tree | 3 | ✅ |
| `seedDefaultTags` | `exam_context` | Success/error | 3 | ✅ |
| `createTag` | `exam_context, name, group_id` | Tag object | 4 | ✅ |
| `createTagGroup` | `exam_context, name, parent_id` | Group object | 4 | ✅ |
| `getAllSubjectsForExam` | `exam_context_id` | Subject list | 4 | ✅ |
| `createTagInGroup` | `exam_context, tag_name, group_id` | Tag object | 4 | ✅ |
| `addQuestionMedia` | `question_id, data, filename` | Media object | 5 | ⏳ |
| `getQuestionMedia` | `question_id` | List of media | 5 | ⏳ |
| `renameMedia` | `media_id, new_name` | Updated media | 5 | ⏳ |
| `deleteMedia` | `media_id` | Success/error | 5 | ⏳ |
| `reorderMedia` | `question_id, order` | Success/error | 5 | ⏳ |

---

## Timeline Estimate

### Actual Progress

| Stage | Estimated | Actual | Status |
|-------|-----------|--------|--------|
| Stage 1: Database & Backend | 4-6 hours | ~5 hours | ✅ Complete |
| Stage 2: Session Setup UI | 6-8 hours | ~7 hours | ✅ Complete |
| Stage 3: Question Entry UI | 8-10 hours | ~9 hours | ✅ Complete |
| Stage 4: Subject/Tag Enhancements | 4-6 hours | ~5 hours | ✅ Complete |
| Stage 5: Media Handling | 4-6 hours | - | ⏳ Next |
| Stage 6: Testing & Polish | 4-6 hours | - | ⏳ Pending |
| **Total** | **30-42 hours** | **~26 hours** | **67% Complete** |

---

## Success Criteria

### Must Have

- [x] Session setup creates review sessions correctly
- [x] Previous sessions display with continuation support
- [x] Question entry form captures all required fields
- [x] Subject search with auto-suggest works
- [x] Tag picker with hierarchy works
- [x] Reflection and Explanation required for completion
- [x] Draft saving allows incomplete entries
- [ ] Media paste/upload works (Stage 5)
- [x] Auto-save functions correctly
- [x] Back button with save prompts works

### Should Have

- [ ] Subject tree browser toggle (Stage 4)
- [ ] Inline tag creation (Stage 4)
- [ ] Media rename/delete/sort (Stage 5)
- [x] Configurable auto-save interval
- [x] Loading states on all actions

### Nice to Have

- [x] Keyboard shortcuts for navigation (Tab between sections)
- [ ] Bulk entry operations
- [ ] Entry templates

---

## Related Documents

- `docs/phases/PHASE3_COMPLETE.md` - Phase 3 completion summary
- `docs/planning/ROADMAP.md` - Project roadmap
- `docs/architecture/completed_database_tables.md` - Database schema
- `docs/phases/PHASE3_IMPLEMENTATION_PLAN.md` - Phase 3 reference
- `docs/testing/PHASE4_STAGE2_MANUAL_TEST_CHECKLIST.md` - Stage 2 testing (81 cases)

---

**Document Version:** 1.4  
**Created:** December 26, 2025  
**Last Updated:** December 27, 2025  
**Author:** Claude (AI Assistant)  
**Status:** 🚧 IN PROGRESS - Stages 1-4 Complete
