# WIMI Future Vision & Ideas

**Document Version:** 3.3
**Created:** January 20, 2026
**Last Updated:** May 16, 2026

---

## Purpose

This document consolidates all future plans, ideas, and aspirations for WIMI (What I Missed It). It serves as:
1. A single source of truth for the project's future direction
2. A place to capture spontaneous ideas before they're forgotten
3. A reference for prioritization and planning discussions

---

## Table of Contents

1. [Current State Summary](#current-state-summary)
2. [Immediate Roadmap (Next 1-3 Months)](#immediate-roadmap)
3. [Near-Term Vision (3-6 Months)](#near-term-vision)
4. [Mid-Term Vision (6-12 Months)](#mid-term-vision)
5. [Long-Term Vision (1+ Years)](#long-term-vision)
6. [Idea Parking Lot](#idea-parking-lot)
7. [Technical Debt & Improvements](#technical-debt--improvements)
8. [Open Questions](#open-questions)

---

## Current State Summary

**As of May 16, 2026:**

WIMI is **production-ready for personal use** with comprehensive exam preparation and mistake analysis capabilities. Cross-platform (Windows + macOS), with a full automated test infrastructure, a versioned migration system, and a complete polyhierarchy + per-edge weight stack. The Hierarchical Weight Allocation Rework (Arc 1) wrapped on 2026-05-16 — Stages 0–9 landed; Stage 10 (drop legacy columns) deferred.

### Completed Features
- ✅ User accounts and authentication
- ✅ Exam setup wizard (simple and multi-dimensional)
- ✅ Question entry with metacognitive reflection
- ✅ Media attachments (images, screenshots)
- ✅ Entry browsing, filtering, and search
- ✅ Comprehensive analytics dashboard
- ✅ Multi-dimensional analytics with D3.js visualizations
- ✅ Hybrid weight system (official + relative weights)
- ✅ Rich text editing (TinyMCE) for notes, explanation, reflection
- ✅ 10 pre-configured exam templates
- ✅ Assignable entry notes (multiple notes per entry, subject linking)
- ✅ Multi-round session timer with break tracking
- ✅ Global settings page with theme system
- ✅ Session import with user-specified duration
- ✅ Reusable subject search widget
- ✅ Tree editor search bar
- ✅ Heatmap cell click navigation with drill-down
- ✅ Windows executable build
- ✅ macOS universal binary build
- ✅ Entry & Subject Improvements (add entries, edit sessions, image/notes subject search)
- ✅ Media Link System — decoupled media with junction table, link/unlink/delete, global search
- ✅ Global media search with cross-exam reuse
- ✅ Plugin/Addon System with install/uninstall flow, scoped API, per-plugin settings
- ✅ Test Infrastructure — `wimi_test/` driver library, `wimi-test` MCP server, CI on Ubuntu/Python 3.11, regression scenario library
- ✅ Versioned Migration Runner (replaces `_ensure_*_schema()` chain)
- ✅ Polyhierarchy backend — `subject_edges` table, `EdgesMixin` / `GraphMixin`, CTE rewrites, tree-editor parents-management UI
- ✅ **Hierarchical Weight Allocation Rework (Arc 1)** — Hamilton allocator, per-edge anchor semantics, exam length triple with wizard step, dual-unit input (`%` ↔ `Q` segmented control with magic suffixes), feasibility checker (yellow badges + tree warning dots), CAT-aware allocation (variable-length adaptive exams), `weight_source` confidence multiplier in analytics, per-subject source markers + "Weight Sources" breakdown card

### Recently Completed (Mar-May 2026)
- ✅ Plugin/Addon System (March 16, 2026) — Install/uninstall flow, zip distribution, scoped API, per-plugin settings, file storage permission, theme persistence
- ✅ Media Link System (April 9, 2026) — `entry_media_mapping` junction table, link/unlink/delete UI, global search, cross-exam reuse, dark mode readability
- ✅ Status Audit (April 15-20, 2026) — FUTURE_VISION v3.1, form section switching bug fixed
- ✅ Test Infrastructure (May 7-8, 2026) — `wimi_test/` library + `wimi_test_mcp` MCP server, `@instrumented_slot` on 33 bridge slots, `data-testid` on all 11 HTML pages, CI workflow, initial regression scenarios from bugs.md
- ✅ Playwright → pychrome Migration (May 7-8, 2026) — Full rewrite of test driver because Qt's CDP surface lacks the `Browser` domain Playwright needs
- ✅ Migration Runner (May 9, 2026) — Versioned `MigrationRunner`, `schema_migrations` tracking, migrations CLI, dead `_ensure_*` methods removed
- ✅ Polyhierarchy Backend (May 9, 2026) — `m004_subject_edges` + `m005_primary_parent_id`, `EdgesMixin` (cycle prevention, primary-parent invariant), `GraphMixin` (DAG traversal), `get_subject_hierarchy` / `getDimensionHierarchy` rewritten onto edges, USMLE seeder polyhierarchy parse
- ✅ Tree Editor Polyhierarchy UX (May 9, 2026) — Parents-management panel, alias chip on non-primary appearances, auto-reveal new appearance after add-parent / switch-primary, dimension cache busted before edge-mutation refresh
- ✅ Tree Editor Inspector Polish (May 9, 2026) — Details panel reads as a real inspector, panels own their scrollbars, weight algorithm-info layout fixes, weight siblings responsive grid
- ✅ Build/Packaging Cleanup (May 7-9, 2026) — PyInstaller specs tracked, migrations bundled, frontend D3 bundled locally, Python requirements consolidated and pinned

### Recently Completed (May 15-16, 2026)
- ✅ **Hierarchical Weight Allocation Rework — Arc 1** (May 15-16, 2026) — 10-stage rollout in two sprint days. Stages 0-9 landed (history table, Hamilton allocator, opt-in rebalance, edge-anchor bridge, exam length triple, allocation read-side, dual-unit input UX, feasibility checker, CAT handling, weight_source analytics); Stage 10 deferred. 114 pytest tests + 7 wimi-test regression scenarios. See `docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md` (✅ Complete) and `docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md`.
- ✅ **Multi-parent context selector follow-up** (May 16, 2026) — Wired `primary_parent_id` through `getSubjectDeepDive` (DB + bridge + JS api + page JS); selector change now refetches with lenient parent-context filter. 4 pytest tests + 1 wimi-test regression scenario. Note: lenient filter is structurally a no-op for the typical leaf-with-multiple-parents deep-dive case until per-entry `primary_parent_id` is actually populated by users — see the Tag context pill follow-up below.

### In Progress / Next Up
- 🕑 **Weight Rework Stage 10** (deferred) — Drop legacy `subject_nodes.relative_weight` / `weight_source` / `display_order` columns. Wait until ≥1 stable release lives with the new system.
- 🟡 **Tag context pill** (per-entry `primary_parent_id` UX) — `POLYHIERARCHY_MIGRATION.md §7.3`. **Landed on `question_entry.html`** (May 16, 2026): pill renders below each primary-subject chip whose leaf has ≥2 parents, click opens a parent picker, choice persists via `setPrimaryParentForEntry` on save. Regression scenario `tests/wimi_test/scenarios/test_tag_context_pill.py`. **Policy (May 16, 2026):** every multi-parent subject on a new entry gets a non-NULL `primary_parent_id` on save — the canonical primary if the user doesn't touch the pill. NULL is now legacy-only (entries created before this commit); the deep-dive selector treats NULL leniently for backward-compat. **Still deferred:** edit-mode pill on `entry_detail.html` (the same pattern fork; reusing the question-entry helpers would let it land as one extension rather than a rewrite). Also deferred: backfill UX for legacy NULL entries on multi-parent subjects (would let users assign contexts to pre-policy data).
- 🔧 **Polyhierarchy UX completion** — Cross-dimensional edges, breadcrumb disambiguation in analytics drilldowns (parent-context tagging is now tracked separately above).
- 🔧 **Media Link System** — minor remaining items: `getMediaFileUsage()`, `getOrphanedMedia()`, usage indicators in image browser
- 🔧 **`hierarchy.py` refactor** — at ~3000 lines after Arc 1; splitting weights/allocation into its own mixin (`weights.py` DB-domain) would lower cognitive load for future weight work.
- 🔧 **Phase 7.7: Polish & Optimization** — Now unblocked by test infra: perf benchmarks against polyhierarchy CTEs, query caching where slow

---

## Immediate Roadmap

**Timeline:** Next 1-3 Months

### 1. Template System (Phase 7.2 Stage 2.4) ✅ COMPLETE

**Priority:** High | **Completed:** January 24, 2026

Pre-configured exam templates to streamline exam creation:

| Template | Type | Target Users |
|----------|------|--------------|
| NBME Shelf: Internal Medicine | Multi-dimensional | Medical students (MS3/MS4) |
| NBME Shelf: Surgery | Multi-dimensional | Medical students (MS3/MS4) |
| USMLE Step 1 | Multi-dimensional | Medical students (MS1/MS2) |
| USMLE Step 2 CK | Multi-dimensional | Medical students (MS3/MS4) |
| MCAT | Multi-dimensional | Pre-med students |
| SAT | Simple | High school students |
| ACT | Simple | High school students |
| GRE General | Simple | Graduate applicants |
| LSAT | Simple | Law school applicants |
| CPA Exam | Multi-dimensional | Accounting candidates |

**Implementation Completed:**
- [x] Created `exam_templates.json` data structure with schema documentation
- [x] Added template selection step to exam wizard (searchable, filterable)
- [x] Auto-populate dimensions and hierarchy levels from templates
- [x] Allow full customization after template selection
- [x] Created 10 initial templates covering medical, graduate, undergraduate, and professional exams
- [x] Template indicators and "Reset to template" functionality
- [x] Category filtering and search in template selection UI

**Files Added/Modified:**
- `src/web/data/exam_templates.json` (new - 10 templates, 1067 lines)
- `src/web/data/exam_templates.schema.md` (new - schema documentation)
- `src/web/js/exam_wizard.js` (+865 lines - template loading, selection, population)
- `src/web/html/wizards/exam_wizard.html` (+80 lines - template step UI)
- `src/web/css/wizard.css` (+461 lines - template card styling)

**Bugs Fixed During Integration Testing:**
1. Review step now displays template name when exam was created from template
2. Info form fields properly cleared when switching to "Start from scratch"
3. Reset template button now has proper click event handler

### 2. Question Entry Form Improvements ✅ COMPLETE

**Priority:** High | **Completed:** January 24, 2026

Workflow enhancements for the question entry form to reduce friction and improve efficiency.

| Feature | Description | Status |
|---------|-------------|--------|
| Auto-fill from Question ID | Auto-populate form fields based on previously entered data for the same question ID | ✅ Complete - Now auto-fills correct answer, explanation, notes, subjects, and tags |
| Quick Hierarchy Management | Add hierarchy editing controls directly in Section B of the response form | ✅ Complete - Parent selector now uses searchable dropdown with fuzzy search and proper CSS styling |
| Subject-Based Image Auto-Population | Auto-fill image fields with images already assigned to matching primary subjects | ✅ Complete - Now filters by dimension, includes "Don't Ask Again" option to dismiss for session |
| Dimension-Specific Media Assignment | For multi-dimensional entries, allow users to assign images/notes to specific dimensions | ✅ Complete - Dimension selector appears on media thumbnails for multi-dimensional exams |
| Image Search Browser | Replace file explorer with searchable image browser querying by renamed titles | ✅ Complete (UI only - see Media Link System for persistence) |
| Entry Navigation Dots Bug Fix | Dots now scroll properly for 20+ entries, enabling navigation to all entries | ✅ Complete |

**Files Added/Modified:**
- `src/web/js/image_browser.js` (new - searchable image browser component)
- `src/web/js/question_entry.js` (+300 lines - auto-fill, quick add subject, image suggestions)
- `src/web/js/media_upload.js` (+50 lines - browse existing images button)
- `src/web/js/api.js` (+40 lines - new API methods)
- `src/web/css/entry.css` (+120 lines - auto-fill prompts, quick add modal, scrollable dots)
- `src/web/css/media.css` (+180 lines - image browser modal styling)
- `src/web/html/question_entry.html` (+30 lines - quick add subject modal)
- `src/app/bridge.py` (+100 lines - new bridge methods)
- `src/database/user_db.py` (+120 lines - new database methods)
- `src/database/models.py` (+3 lines - dimension_id field)

### 3. Phase 7.7: Polish & Optimization

**Priority:** Medium | **Effort:** 2-3 weeks

| Task | Description |
|------|-------------|
| Query caching | Cache frequently-used analytics queries |
| Performance testing | Test with large datasets (1000+ entries) |
| UI/UX refinements | Based on usage feedback |
| Integration tests | End-to-end test coverage |
| User documentation | Help pages, tooltips, onboarding |

**Template System Enhancements (from integration testing):**
| Enhancement | Description | Priority |
|-------------|-------------|----------|
| Reset confirmation modal | Replace basic `confirm()` with styled modal for consistency | Low |
| Template preview modal | Add "Preview" button on template cards to show full details before selection | Low |
| Template loading indicator | Add loading spinner while templates are fetched | Low |
| Sample hierarchy import | Use template's `sampleHierarchy` to pre-populate subject tree | Medium |

### 4. Rich Text Editor for Entry Fields

**Priority:** High | **Effort:** 2-3 weeks
**Status:** ✅ 100% Complete (2026-01-24) - All bugs fixed

Add rich text formatting to the notes, explanation, and reflection fields in the question entry form.

#### Library Selection: **Quill**

| Criteria | Value |
|----------|-------|
| License | BSD-3 (no restrictions) |
| Bundle Size | ~43 KB minified + gzipped |
| Output Format | Delta JSON + HTML |
| Offline Support | Excellent (no CDN needed) |

**Why Quill:**
- Lightweight and fast (perfect for PyQt6 WebEngine)
- Mature, battle-tested library
- Clean JSON Delta format ideal for SQLite storage
- Works perfectly offline
- Easy to customize and theme
- Excellent documentation

#### Features to Implement

**Tier 1 - Core Formatting:**
| Feature | Toolbar Icon | Shortcut |
|---------|--------------|----------|
| Bold | **B** | Ctrl+B |
| Italic | *I* | Ctrl+I |
| Underline | U̲ | Ctrl+U |
| Strikethrough | ~~S~~ | Ctrl+Shift+X |
| Headers | H1/H2/H3 dropdown | Ctrl+Alt+1-3 |
| Bulleted list | • | Ctrl+Shift+8 |
| Numbered list | 1. | Ctrl+Shift+7 |
| Hyperlinks | 🔗 | Ctrl+K |

**Tier 2 - Advanced Features:**
| Feature | Description | Implementation |
|---------|-------------|----------------|
| Text highlighting | User-selectable colors | Color picker in toolbar |
| Math equations | LaTeX rendering | Quill + KaTeX extension |
| Tables | Insert/edit tables | quill-table-better extension (Quill 2.x compatible) |
| Code blocks | Syntax highlighted | Quill code-block module |
| Blockquotes | Indented quotes | Built-in Quill |

**Features NOT Included (by design):**
- Font selection (consistent typography)
- Text alignment beyond left
- Inline images (kept in separate media section)
- Complex nested tables

#### UI/UX Design

**Toolbar Layout:**
```
┌──────────────────────────────────────────────────────────────┐
│ [H▾] │ B  I  U  S │ • 1. │ "" │ </> │ 🔗 │ 📊 │ ∑ │ ⎘ │ ↩ ↪ │
└──────────────────────────────────────────────────────────────┘
  │      │           │   │    │    │    │    │   │    └─ Undo/Redo
  │      │           │   │    │    │    │    │   └─ Clear formatting
  │      │           │   │    │    │    │    └─ Math equation (LaTeX)
  │      │           │   │    │    │    └─ Insert table
  │      │           │   │    │    └─ Insert link
  │      │           │   │    └─ Code block
  │      │           │   └─ Blockquote
  │      │           └─ Lists (bullet/numbered)
  │      └─ Text formatting (Bold/Italic/Underline/Strike)
  └─ Heading level dropdown (H1/H2/H3/H4/H5/H6/Normal)
```

*Note: Highlight color picker was removed due to Quill picker incompatibility with PyQt6 WebEngine.*

**Keyboard Shortcuts (all standard):**
- `Ctrl+B` Bold, `Ctrl+I` Italic, `Ctrl+U` Underline
- `Ctrl+K` Insert/edit link
- `Ctrl+Z` Undo, `Ctrl+Shift+Z` Redo
- `Ctrl+Shift+V` Paste without formatting
- `Tab` Indent list, `Shift+Tab` Outdent

**Auto-formatting (Markdown shortcuts):**
- `# ` → Heading 1, `## ` → Heading 2, `### ` → Heading 3, `#### `→ Heading 4, etc...
- `- ` or `* ` → Bullet list
- `1. ` → Numbered list
- `> ` → Blockquote
- ` ``` ` → Code block

**Math Equation Support:**
- Inline: `$E=mc^2$` renders inline
- Block: `$$\frac{-b \pm \sqrt{b^2-4ac}}{2a}$$` renders centered
- Uses KaTeX for fast client-side rendering
- No server-side processing needed

**Table Support:**
- Insert table button opens size picker (rows × columns)
- Tab to move between cells
- Right-click context menu for add/delete rows/columns
- Header row toggle

#### Storage Strategy

```sql
-- Modify existing fields to store both formats
ALTER TABLE question_entries ADD COLUMN explanation_json TEXT;
ALTER TABLE question_entries ADD COLUMN reflection_json TEXT;
ALTER TABLE question_entries ADD COLUMN notes_json TEXT;

-- Existing _html fields store rendered HTML for search/display
-- New _json fields store Quill Delta for editing
```

**Save format:**
```javascript
// On save
const content = {
    delta: quill.getContents(),  // JSON for editing
    html: quill.root.innerHTML   // HTML for search/display
};
bridge.saveEntryField(entryId, 'explanation', JSON.stringify(content));
```

**Load format:**
```javascript
// On load
const content = JSON.parse(savedContent);
quill.setContents(content.delta);  // Restore exact formatting
```

#### File Structure

```
src/web/
├── lib/
│   └── quill/
│       ├── quill.min.js          # Core editor
│       ├── quill.snow.css        # Snow theme
│       ├── katex.min.js          # Math rendering
│       ├── katex.min.css
│       ├── quill-table-better.min.js  # Table extension (Quill 2.x compatible)
│       ├── quill-table-better.css
│       └── markdownShortcuts.js       # Markdown auto-formatting
├── js/
│   └── rich_editor.js            # WIMI editor wrapper component
└── css/
    └── rich_editor.css           # Custom styling overrides
```

#### Implementation Checklist

**Phase 1: Library Integration** ✅ Complete (2026-01-24)
- [x] Download and bundle Quill + extensions locally
- [x] Download KaTeX for math support
- [x] Download quill-table-better for tables (Quill 2.x compatible)
- [x] Create `rich_editor.js` wrapper component
- [x] Create `rich_editor.css` for theme customization
- [x] Test in PyQt6 WebEngine (frozen mode) - ⚠️ Table issues discovered

**Phase 2: Database Updates** ✅ Complete (2026-01-24)
- [x] Add `_json` columns to `question_entries` table
- [x] Write migration script (auto-migration in user_db.py)
- [x] Update `user_db.py` save/load methods
- [x] Update bridge methods for JSON content

**Phase 3: Question Entry Integration** ✅ Complete (2026-01-24)
- [x] Replace textarea with Quill editor for `explanation` field
- [x] Replace textarea with Quill editor for `reflection` field
- [x] Replace textarea with Quill editor for `notes` field
- [x] Ensure uniform editor config across all three fields
- [x] Handle paste sanitization
- [x] Test undo/redo behavior

**Phase 4: Math & Table Support** ✅ Complete (2026-01-24)
- [x] Integrate KaTeX module for math equations
- [x] Add math equation button to toolbar
- [x] Integrate quill-table-better
- [x] Fix table insert button in PyQt6 WebEngine (fixed 2026-01-24 - UMD module compatibility shim)
- [x] Test complex equations (fractions, integrals, etc.)

**Phase 5: Polish** ✅ Complete (2026-01-24)
- [x] Keyboard shortcut documentation/tooltips
- [x] Auto-formatting behaviors (markdown shortcuts)
- [x] Fix color picker dropdown closing (fixed 2026-01-24 - document click handler)
- [x] Mobile-friendly touch targets (44px)
- [x] Accessibility (aria-labels, keyboard nav, focus states)
- [x] Add header levels 4-6 (fixed 2026-01-24 - toolbar config updated)

#### Files to Modify

| File | Changes |
|------|---------|
| `src/web/lib/quill/` | New directory with bundled libraries |
| `src/web/js/rich_editor.js` | New - Editor wrapper component |
| `src/web/css/rich_editor.css` | New - Custom styling |
| `src/web/html/question_entry.html` | Replace textareas with editor containers |
| `src/web/js/question_entry.js` | Initialize editors, handle save/load |
| `src/database/user_db.py` | Update save/load for JSON content |
| `src/app/bridge.py` | Handle JSON content serialization |
| `src/database/schema/` | Migration for new columns |

#### Known Issues / Bugs - RESOLVED (2026-01-24)

| Issue | Description | Status | Resolution |
|-------|-------------|--------|------------|
| Table insertion not working | The table button in toolbar does not insert tables in PyQt6 WebEngine | ✅ Fixed | UMD module exports to `self` not `window` in PyQt6 - added compatibility shim + custom table size dialog |
| Highlight color picker not closing | The background color dropdown doesn't close after selection in PyQt6 WebEngine | ❌ Removed | Feature removed - Quill picker incompatible with PyQt6 WebEngine event handling |
| Missing header levels 4-6 | Only H1-H3 available in header dropdown | ✅ Fixed | Updated toolbar config to `[1, 2, 3, 4, 5, 6, false]` + CSS styling |

**Resolutions Applied:**
- **Table insertion:** Added PyQt6 WebEngine compatibility shim in `question_entry.html` to copy `self.QuillTableBetter` to `window.QuillTableBetter`. Created custom 8x8 table size dialog that bypasses quill-table-better's built-in picker.
- **Highlight color picker:** Removed from toolbar. The Quill picker dropdown has deep incompatibilities with PyQt6 WebEngine's event handling that prevent it from closing properly. Multiple fix attempts (capture phase handlers, stopImmediatePropagation, manual format application) all failed due to Quill's internal event handling.
- **Header levels:** Updated toolbar config and added CSS styling for h4, h5, h6 in both editor content and toolbar picker dropdown.

---

### 5. Media Link System (Shared Image Support) ✅ ~90% COMPLETE

**Priority:** High | **Effort:** 1-2 weeks
**Status:** ✅ Core implementation complete (April 2026)

Implemented many-to-many relationship between entries and media files, enabling true image reuse with separate Remove (unlink) and Delete (permanent) actions. The `entry_media` table stores media records and `entry_media_mapping` junction table links them to entries.

**What was implemented:**
- `entry_media_mapping` junction table with migration from old schema
- `link_media_to_entry`, `removeMediaFromEntry`, `delete_entry_media` (full link/unlink/delete flow)
- `attachMediaToEntry` bridge method for cross-entry reuse
- `searchMedia`, `getMediaBySubject` for global media search
- Remove/Delete confirmation modal in `media_upload.js` with two-option UI
- 11 JavaScript API wrappers in `src/web/js/api/media.js`

**Remaining minor items:**
- [ ] `getMediaFileUsage(mediaId)` — query how many entries use a given media file
- [ ] `getOrphanedMedia()` — find media with no active entry links
- [ ] Usage indicators in `image_browser.js` (show how many entries use each image)

#### Original Design (for reference)

The original design called for `media_files` and `entry_media_links` tables. The actual implementation uses the repurposed `entry_media` table plus `entry_media_mapping` junction table, achieving the same architecture with slightly different naming.

#### Key Implementation Files

| File | Role |
|------|------|
| `src/database/domains/media.py` | Database methods: link/unlink/delete, search, reorder |
| `src/database/domains/schema_migrations.py` | `_ensure_media_decoupling_schema()` creates junction table |
| `src/app/bridge_domains/media.py` | 11 bridge methods for media operations |
| `src/web/js/api/media.js` | 11 JavaScript API wrappers |
| `src/web/js/media_upload.js` | Remove/Delete modal UI, thumbnail actions |
| `src/web/js/image_browser.js` | Searchable image browser (needs usage indicators)

---

### 6. Phase 9: Assignable Entry Notes

**Priority:** High | **Completed:** February 7, 2026

Multiple discrete notes per question entry, each independently assignable to specific subjects. Mirrors the `entry_media` pattern with `linked_subject_ids` JSON column.

**Features Implemented:**
- New `entry_notes` table with auto-migration of legacy `question_entries.notes` field
- `EntryNote` dataclass with `from_db_row()`, `is_general` property, `to_dict()`
- Full CRUD: `add_entry_note`, `get_entry_notes_list`, `update_entry_note`, `delete_entry_note`, `clear_entry_note`
- 6 `@pyqtSlot` bridge methods + 6 JavaScript API wrappers
- Multi-note card UI in entry form: each card has TinyMCE editor + subject chips + inline subject popover
- Tabbed notes display in detail view: General tab + per-subject tabs
- Subject sync: note chips update when entry subjects change
- Cascade delete when parent entry is deleted
- 22 unit tests, all passing

**Files Added/Modified:**

| File | Changes |
|------|---------|
| `src/database/schema/user_db_schema_v1_phase9_notes.sql` | **NEW** — entry_notes table |
| `src/database/models.py` | Add `EntryNote` dataclass, `notes_list` field on `QuestionEntry` |
| `src/database/user_db.py` | Migration + 6 CRUD methods + wire into existing getters |
| `src/app/bridge.py` | 6 new `@pyqtSlot` methods + serialization |
| `src/web/js/api.js` | 6 new API wrapper methods |
| `src/web/html/question_entry.html` | Replace single editor with note card container |
| `src/web/js/question_entry.js` | Multi-note state, card management, save sync |
| `src/web/html/entry_detail.html` | Tabbed notes panel |
| `src/web/js/entry_detail.js` | Tabbed rendering with subject grouping |
| `src/web/css/entry.css` | Note card styles |
| `src/web/css/detail.css` | Tab styles |
| `tests/database/test_entry_notes.py` | **NEW** — 22 tests |

---

## Near-Term Vision

### 7. Phase 10: Subject Hierarchy Notes

**Priority:** Medium | **Effort:** 4-6 weeks
**Design Document:** `docs/planning/Notes_Integration.md`

Dedicated notes system integrated with subject hierarchy.

| Feature | Description | Priority |
|---------|-------------|----------|
| Hierarchical Notes | Notes at user-defined hierarchy levels | High |
| Rich Text Editor | Bold, italic, lists, headings, code blocks | High |
| Entry Field Formatting | Add rich text formatting to explanation, reflection, and notes fields in question entry | High |
| Markdown Table Support | Full markdown table rendering and editing in notes sections | High |
| Template System | Built-in and custom note templates | High |
| Media Support | Images, links, file attachments | Medium |
| Anki Linking | Associate notes with Anki cards | Medium |
| Note Inheritance | Configurable aggregation/inheritance | Medium |
| Notes Dashboard | Cross-subject notes browser | Low |

**Implementation Phases:**
1. Foundation (DB, models, bridge, wizard config)
2. Tree Editor Integration (notes tab in details panel)
3. Dedicated Notes Page (full-featured editor)
4. Template System (create, manage, apply templates)
5. Anki Integration (link notes to cards)
6. Inheritance & Advanced Features



**Timeline:** 3-6 Months

### 8. Anki Integration

**Priority:** High | **Effort:** 3-4 weeks

Connect WIMI with Anki for spaced repetition correlation.

| Feature | Description | Priority |
|---------|-------------|----------|
| AnkiConnect Setup | Configure connection to local Anki | High |
| Deck/Tag Mapping | Map Anki decks/tags to WIMI exams | High |
| Card Linking | Link WIMI entries to specific Anki cards | Medium |
| Performance Correlation | Show Anki review stats alongside WIMI data | Medium |
| Sync Status | Display last sync time, card counts | Low |

**Technical Approach:**
- Use AnkiConnect plugin (HTTP API on localhost:8765)
- Store Anki card IDs in WIMI database
- Periodic sync to pull review statistics

### 9. Calendar & Scheduling

**Priority:** Medium | **Effort:** 3-4 weeks

Study planning and session scheduling.

| Feature | Description | Priority |
|---------|-------------|----------|
| Calendar View | Monthly/weekly calendar of study sessions | High |
| Session Scheduling | Plan future review sessions | High |
| Goal Integration | Link calendar events to weekly goals | Medium |
| Reminders | Desktop notifications for scheduled sessions | Medium |
| Session Templates | Reusable session configurations | Low |
| iCal Export | Export to Google Calendar, Outlook | Low |

**Design Considerations:**
- Integrate with existing goal system from Phase 6
- Show past sessions and planned sessions on same calendar
- Color-code by exam or session type

---

## Mid-Term Vision

**Timeline:** 6-12 Months

### 8. Enhanced Import/Export

**Priority:** Medium | **Effort:** 2-3 weeks

| Feature | Description |
|---------|-------------|
| CSV Import | Import entries from spreadsheets |
| Entry Export | Export entries to CSV/JSON/PDF |
| Official Outline Import | Import USMLE/NBME content outlines |
| Backup/Restore | Full database backup and restore |
| Template Sharing | Export/import exam templates |

### 9. Advanced Search & Filtering

**Priority:** Medium | **Effort:** 2-3 weeks

| Feature | Description |
|---------|-------------|
| Dimension Filters | Use `dimension:` prefix filters in subject mapping searches (e.g., `dimension:system cardiology`) |
| Subject Aliases | Allow eponyms, acronyms, and pseudonyms for subjects to improve search discoverability |
| Saved Filters | Save and reuse filter configurations |
| Search Operators | AND, OR, NOT, quotes for exact match |
| Cross-Exam Search | Search across all exams |
| Search History | Recent searches with quick access |

---

## Long-Term Vision

**Timeline:** 1+ Years

### 8. AI-Powered Features

| Feature | Description | Complexity |
|---------|-------------|------------|
| Auto-Tagging | NLP-based tag suggestions from question text | High |
| Subject Suggestions | Suggest subjects based on content | High |
| Reflection Prompts | AI-generated reflection questions | Medium |
| Pattern Insights | AI-enhanced pattern detection | High |
| Study Recommendations | Personalized study plan generation | High |

### 9. Collaboration Features

| Feature | Description |
|---------|-------------|
| Share Hierarchies | Share exam outlines with others |
| Template Library | Community-contributed note templates |
| Study Groups | Collaborative mistake review |
| Mentor Mode | Tutors can review student progress |

### 10. Mobile & Cross-Platform

| Feature | Description |
|---------|-------------|
| Web Version/PWA | Browser-based access via a PWA |
| Cloud Sync | Cross-device synchronization |
| Offline Mode | Work without internet, sync later |

### 11. Advanced Analytics

| Feature | Description |
|---------|-------------|
| Predictive Analytics | Predict exam readiness |
| Comparison Analytics | Compare progress to anonymized peers |
| Learning Curve Analysis | Track improvement over time |
| Forgetting Curve | Predict when topics need review |

### 12. Integrations

| Integration | Description |
|-------------|-------------|
| Notion | Import/export notes |
| Obsidian | Bidirectional sync |
| Google Drive | Encrypted Cloud backup |
| UWorld/Amboss | Import question data (if APIs available) |

---

## Idea Parking Lot

**Purpose:** Capture spontaneous ideas before they're lost. Review periodically to promote to roadmap or archive.

### Unorganized Ideas

*Add new ideas here with date. Move to appropriate section during planning sessions.*

```
Format: [DATE] - Idea description
```

| Date | Idea | Notes |
|------|------|-------|
| | *(All ideas organized on 1/24/26 - see sections above)* | |

### Recently Captured

*Ideas captured in recent sessions, pending categorization:*

- [ ] 
- [ ] 
- [ ] 

### Under Consideration

*Ideas being actively evaluated:*

| Idea | Pros | Cons | Decision |
|------|------|------|----------|
| | | | |

### Archived Ideas

*Ideas evaluated and deferred or rejected:*

| Idea | Reason | Date Archived |
|------|--------|---------------|
| | | |

---

## Technical Debt & Improvements

### High Priority

| Item | Description | Effort |
|------|-------------|--------|
| ~~Entry form scrolling dots bug~~ | ~~Dots don't scroll properly after 20+ entries~~ | ✅ Fixed 2026-01-24 |
| Entry form auto-scroll bug | Screen automatically scrolls up while typing in explanation, notes, or media sections | Medium |
| Form section switching bug | Clicking between form sections (from open to closed) requires multiple clicks; first click closes the target section | Medium |
| Image dialog subject bug | After returning to an entry, image dialog shows "No subjects assigned" even though subjects exist; only fixed after reassigning a subject | Medium |
| Entry save not persisting media/tables | Entry saves not saving associated images or tables in notes when moving to next entry | High |
| Related images dialog false positive | Related images dialog pops up for subjects that don't have images assigned to them | Low |
| Table multi-selection lost on right-click | Multi-selection of cells in tables works, but selection is removed when user right-clicks | Medium |
| Table right-click functions broken | Right-click context menu functions in tables do not work | Medium |
| Subject deep dive page fix | Parent nodes show empty even when children have data; needs UX clarification | Medium |
| Query caching | Cache analytics queries for performance | Medium |
| Test coverage | Increase from 83% to 90%+ | Medium |
| Error handling | Standardize error handling across bridge | Medium |

### Medium Priority

| Item | Description | Effort |
|------|-------------|--------|
| Schema manager coverage | Currently 32%, target 80% | Medium |
| Large file handling | Implement temp file + path for media >5MB | Low |
| Logging improvements | Structured logging with log levels | Low |

### Low Priority

| Item | Description | Effort |
|------|-------------|--------|
| CSS loading investigation | Why external CSS sometimes not applied in QWebEngineView | Low |
| Drag-drop tree reordering | Deferred from Phase 3 | Medium |
| Keyboard shortcuts | Global keyboard navigation | Low |

---

## Open Questions

### Product Questions

1. **Should dimensions be nestable?** (e.g., Site of Care > Specific Location)
2. **Should dimensions have weights?** (some dimensions more important than others)
3. **Multiple tags per dimension?** (currently single selection)
4. **Shared dimensions across exams?** (reuse dimension definitions)
5. **Auto-tagging suggestions?** (based on question text analysis)

### Technical Questions

1. ~~**Rich text editor library?**~~ → **Resolved: TinyMCE** (lightweight, MIT license, offline-capable)
2. **Mobile framework?** (React Native, Flutter, PWA)
3. **Cloud sync architecture?** (Firebase, custom backend, P2P)
4. **AI/ML integration approach?** (local models, API calls, hybrid)

### Business Questions

1. **Monetization model?** (free, freemium, subscription, one-time purchase)
2. **Target market expansion?** (beyond standardized exams)
3. **Community features scope?** (templates only vs full collaboration)

---

## Document Maintenance

### Review Schedule

| Frequency | Action |
|-----------|--------|
| Weekly | Add new ideas to Parking Lot |
| Monthly | Review Parking Lot, promote/archive ideas |
| Quarterly | Review entire document, update timelines |

### Related Documents

| Document | Purpose |
|----------|---------|
| `docs/planning/ROADMAP.md` | Detailed phase-by-phase roadmap |
| `docs/planning/Notes_Integration.md` | Phase 10 design document |
| `docs/planning/PHASE7_MULTI_DIMENSIONAL_HIERARCHY.md` | Phase 7 design document |
| `docs/QUICK_START_PHASE7.md` | Current phase implementation guide |

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| May 16, 2026 | 3.3 | **Arc 1 (Hierarchical Weight Allocation Rework) complete.** 10-stage rollout: Stages 0-9 landed across May 15-16; Stage 10 (drop legacy node-level weight columns) deferred ≥1 release. New features: Hamilton allocator, per-edge anchor semantics, exam length triple + wizard step, dual-unit input UX (`%` ↔ `Q` segmented control + magic suffixes), feasibility checker (badges + warning dots), CAT exam handling, weight_source confidence multiplier in analytics, "Weight Sources" breakdown card, structural multi-parent context selector. Replaced "In Progress / Next Up" with new live items: Stage 10 (deferred), polyhierarchy UX completion, Media Link tail, multi-parent drill-down filter follow-up, hierarchy.py split, Phase 7.7 polish. |
| May 15, 2026 | 3.2 | **Quarter-on review.** Recorded Plugin/Addon System (Mar 16), Test Infrastructure + pychrome migration (May 7-8), Migration Runner (May 9), Polyhierarchy backend + tree-editor parents-management UI (May 9), tree-editor inspector polish, build cleanup. Replaced "In Progress / Next Up" with current live arcs: Hierarchical Weight Allocation Rework (top priority), polyhierarchy UX completion, Phase 7.7 polish (now unblocked by test infra). |
| Apr 15, 2026 | 3.1 | **Status audit.** Marked Entry & Subject Improvements as complete (add entries, edit session, image/notes subject search with reusable widget). Marked Media Link System as ~90% complete (junction table, link/unlink/delete, global search, cross-exam reuse all working; remaining: getMediaFileUsage, getOrphanedMedia, image browser usage indicators). Condensed Media Link section to reflect actual implementation vs original design. |
| Mar 6, 2026 | 3.0 | **Major update.** Added multi-round session timer, global settings/theming, macOS build support, session import duration, heatmap click navigation, tree editor search, subject search widget, browser/entry fixes. Updated codebase metrics (588 tests, 21K Python / 30K JS lines). Cross-platform (Windows + macOS). |
| Feb 7, 2026 | 2.0 | **Phase 9: Assignable Entry Notes Complete.** Multiple discrete notes per entry with subject linking, multi-note card UI, tabbed detail view, 22 tests. Documentation consolidated. Updated current state summary and phase status. |
| Jan 27, 2026 | 1.9 | **Entry Form Bugs Added:** Added 7 bugs to Technical Debt from user-reported issues: auto-scroll, section switching, image dialog subject bug, media/tables not persisting, related images false positive, table multi-selection, table right-click functions |
| Jan 24, 2026 | 1.8 | **Rich Text Editor 100% Complete:** Fixed all 3 bugs: (1) Table insertion in PyQt6 WebEngine - added UMD module compatibility shim for `self` vs `window`, (2) Color picker dropdown not closing - added `_setupPickerCloseHandler()` with document click listener, (3) Added header levels 4-6 with CSS styling |
| Jan 24, 2026 | 1.7 | **Rich Text Editor 90% Implemented:** Quill 2.0.3 + KaTeX + quill-table-better integrated. Created rich_editor.js wrapper, rich_editor.css theme, database schema with _json columns, question entry form integration. **3 bugs discovered:** table insertion not working in PyQt6, highlight color picker not closing, missing H4-H6 headers |
| Jan 24, 2026 | 1.6 | **Rich Text Editor Specification:** Added detailed implementation plan for Quill-based rich text editing in notes/explanation/reflection fields with math equations (KaTeX), tables, highlighting, and standard formatting |
| Jan 24, 2026 | 1.5 | **Question Entry Form Improvements Completed:** Fixed Auto-fill to include all fields (correct answer, explanation, notes), added searchable parent selector to Quick Add Subject, implemented dimension dropdown on media thumbnails, added dimension filtering to image suggestions with "Don't Ask Again" option |
| Jan 24, 2026 | 1.4 | **Media Link System Design:** Added implementation plan for shared image support with Remove (unlink) vs Delete (permanent) actions, many-to-many entry-media relationships via junction table |
| Jan 24, 2026 | 1.3 | **Question Entry Form Improvements Complete:** Auto-fill from Question ID, Quick Hierarchy Management, Subject-Based Image Auto-Population, Dimension-Specific Media Assignment, Image Search Browser, and Entry Navigation Dots bug fix |
| Jan 24, 2026 | 1.2 | **Template System Complete:** Phase 7.2 Stage 2.4 implemented with 10 exam templates, searchable template selection UI, auto-population of dimensions/hierarchy/weights, and full customization support |
| Jan 24, 2026 | 1.1 | Organized 11 unorganized ideas: 2 bug fixes to Technical Debt, 5 features to new Question Entry Improvements section, 2 to Advanced Search, 2 to Phase 10 Notes |
| Jan 20, 2026 | 1.0 | Initial document created, consolidated from existing planning docs |

---

**END OF FUTURE VISION DOCUMENT**
