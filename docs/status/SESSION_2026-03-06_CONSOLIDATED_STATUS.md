# Project Status - March 6, 2026

**Consolidated status update covering all work since February 7, 2026.**

---

## Phase Completion Matrix

| Phase | Description | Status | Completed |
|-------|-------------|--------|-----------|
| 1 | Database & Models | ✅ Complete | 2025 |
| 2 | Core UI | ✅ Complete | 2025 |
| 3 | Exam Setup Wizard | ✅ Complete | 2025 |
| 4 | Question Entry | ✅ Complete | Dec 2025 |
| 5 | Entry Browser | ✅ Complete | Jan 2026 |
| 6 | Analytics Dashboard | ✅ Complete | Jan 2026 |
| 7.1 | Foundation & Schema, Hybrid Weights | ✅ Complete | Jan 8, 2026 |
| 7.2 | Exam Setup UI (5 stages) | ✅ Complete | Jan 24, 2026 |
| 7.3 | Question Entry UI | ⚠️ Not needed | - |
| 7.4-7.6 | Multi-Dimensional Analytics | ✅ Complete | Jan 18, 2026 |
| 7.7 | Polish & Optimization | 🚀 Not Started | - |
| 8 | Anki Integration | 📋 Planned | - |
| 9 | Assignable Entry Notes | ✅ Complete | Feb 7, 2026 |
| 10 | Subject Hierarchy Notes | 📋 Planned | - |
| Rich Text | TinyMCE Editor | ✅ Complete | Jan 24, 2026 |
| Templates | Exam Template System | ✅ Complete | Jan 24, 2026 |
| Form UX | Question Entry Improvements | ✅ Complete | Jan 24, 2026 |
| Session Timer | Multi-Round Timer with Break Tracking | ✅ Complete | Feb 25, 2026 |
| Global Settings | Settings Page + Theme System | ✅ Complete | Feb 25, 2026 |
| MacOS Build | Universal Binary Support | ✅ Complete | Feb 18, 2026 |
| Session Import | Import with User-Specified Duration | ✅ Complete | Mar 1, 2026 |

---

## Codebase Metrics

| Metric | Value |
|--------|-------|
| Python code | ~21,300 lines |
| JavaScript code | ~30,700 lines |
| Source files | 114 (Python, JS, HTML, CSS) |
| HTML pages | 10 + wizard sub-pages |
| JavaScript files | 39 |
| CSS files | 26 |
| Total tests | 588 |
| `bridge.py` | ~5,600 lines |
| `user_db.py` | ~10,400 lines |
| Platforms | Windows + macOS |

---

## Recent Work (Since February 7, 2026)

### Session Import System (Feb 10-12, 2026)
- Incorporating session import functionality
- Database test for session import
- Fixed export/import functions for multi-dimensional exams
- Plans created for global settings and an updater

### Global Settings Page (Feb 15, 2026)
- New `settings.html` page with global application settings
- Theme configuration and persistence

### MacOS Compatibility (Feb 18, 2026)
- `build_macos.sh` build script for macOS app bundle
- Universal binary (`universal2`) supporting Apple Silicon + Intel
- `entitlements.plist` for PyQt6 WebEngine JIT permissions
- `docs/BUILD_MACOS.md` documentation
- `main.py` and `main_window.py` updated for macOS paths

### Browser & Search Improvements (Feb 12-20, 2026)
- Fixed browser page bugs
- Added search filter capabilities to browser
- Note subject modal and edit session modal display fixes
- Tree editor search bar for subject hierarchy navigation
- Removed unused Import Weights feature (cleaned up ~866 lines)

### Analytics UX Improvements (Feb 22, 2026)
- Heatmap cell click navigation with drill-down to entries
- Empty drilldown state shows toast notification
- Analytics chart visibility settings now properly applied
- `analytics_dashboard.js` significantly expanded (+375 lines)

### Multi-Round Session Timer (Feb 25, 2026)
- New `session_timer_rounds` table (schema: `user_db_schema_v1_timer_rounds.sql`)
- Multiple independent timed rounds per review session
- Per-round break tracking (actual studied seconds, total break seconds)
- Timer UI in question entry form header
- Bridge methods for timer round CRUD
- 346-line test suite (`test_session_timer.py`)

### Theme System (Feb 25-28, 2026)
- Theme applied across all pages: analytics, browser, detail, entry, error-viewer, tree editor, settings, rich editor, weight analysis
- Theme-aware chart rendering for D3.js visualizations (heatmap, source chart, sunburst, subject deep dive)
- ~971 lines changed in CSS and JS for theme integration

### Session Import Duration (Mar 1, 2026)
- Users can now specify study session duration for imported sessions
- Duration input added to session import UI
- Bridge method updated to pass duration

### Entry Form Fixes (Mar 3-6, 2026)
- Corrected addition of new topics from question entry modal
- Fixed timer to auto-pause when user leaves entry page
- Fixed media handling and subject search modal in question entry form

### Subject Search Widget (Ongoing)
- New reusable `subject_search_widget.js` component
- `subject_search_widget.css` shared styles
- Planned integration into media and notes subject assignment modals
- Design document: `docs/planning/ENTRY_AND_SUBJECT_IMPROVEMENTS.md`

---

## New Files Added (Since Feb 7, 2026)

| File | Purpose |
|------|---------|
| `src/database/schema/user_db_schema_v1_timer_rounds.sql` | Session timer rounds table |
| `src/web/js/subject_search_widget.js` | Reusable subject search + select widget |
| `src/web/css/subject_search_widget.css` | Shared styles for subject search widget |
| `tests/database/test_session_timer.py` | Session timer round tests (346 lines) |
| `build_macos.sh` | macOS build script |
| `entitlements.plist` | macOS JIT entitlements |
| `docs/BUILD_MACOS.md` | macOS build documentation |
| `docs/planning/ENTRY_AND_SUBJECT_IMPROVEMENTS.md` | Entry page & subject search improvements plan |

---

## Known Issues (Technical Debt)

| Priority | Issue | Description |
|----------|-------|-------------|
| HIGH | Entry save not persisting media/tables | Media and tables in notes not saved when navigating |
| HIGH | Entry form auto-scroll | Screen scrolls up while typing in lower sections |
| MEDIUM | Form section switching | First click on collapsed section closes it instead of opening |
| MEDIUM | Image dialog subject bug | Shows "No subjects" after returning to entry |
| MEDIUM | Table multi-selection | Selection lost on right-click |
| MEDIUM | Table right-click functions | Context menu functions broken |
| LOW | Related images false positive | Dialog appears for subjects without images |

---

## Next Priorities

1. **Media Link System** -- Many-to-many entry-media relationships (design complete in FUTURE_VISION.md)
2. **Entry & Subject Improvements** -- Add entries to sessions, subject search in media/notes modals (design in ENTRY_AND_SUBJECT_IMPROVEMENTS.md)
3. **Phase 7.7: Polish** -- Query caching, performance testing, integration tests
4. **Technical debt** -- Fix the 7 known bugs listed above
5. **Anki Integration** -- Connect with Anki for spaced repetition

---

## Key Architecture Notes

- **Analytics data source:** Queries use `entry_subject_mappings` + `subject_nodes.dimension_id`, NOT `question_hierarchy_tags`
- **Entry notes pattern:** Follows `entry_media` pattern with `linked_subject_ids` JSON column
- **Rich text storage:** Both HTML and JSON stored (`content_html` + `content_json` columns)
- **Session timer:** `session_timer_rounds` tracks multiple rounds per session with break time
- **Theme system:** CSS variables + JS theme application across all pages
- **Subject search widget:** Reusable component for fuzzy subject search with chip selection
- **Test database:** exam_context_id=5 (Usmle 3) with 20 entries across 3 dimensions
- **Cross-platform:** Windows (PyInstaller) + macOS (universal binary with entitlements)

---

## Documentation Map

| Document | Purpose | Last Updated |
|----------|---------|--------------|
| `CLAUDE.md` (root) | Quick reference for AI agents | Mar 6, 2026 |
| `docs/planning/FUTURE_VISION.md` | Primary roadmap & status (v3.0) | Mar 6, 2026 |
| `docs/status/SESSION_2026-03-06_CONSOLIDATED_STATUS.md` | This document | Mar 6, 2026 |
| `docs/handoff/INDEX.md` | Handoff tracking | Mar 6, 2026 |
| `docs/BUILD_WINDOWS.md` | Windows build instructions | Jan 3, 2026 |
| `docs/BUILD_MACOS.md` | macOS build instructions | Feb 18, 2026 |
| `docs/planning/ENTRY_AND_SUBJECT_IMPROVEMENTS.md` | Entry page improvements plan | Feb 25, 2026 |
| `docs/architecture/completed_database_tables.md` | Database schema | Jan 2026 |
