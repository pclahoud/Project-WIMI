# WIMI Future Features & Roadmap

**Document Version:** 2.0
**Created:** December 26, 2025
**Last Updated:** January 20, 2026

---

## Overview

This document tracks planned features, enhancements, and ideas for future development of WIMI. Items are organized by priority and category.

**Current Status:** 
- Phases 1-6: ✅ **Complete**
- Phase 7.1: ✅ **Complete** (Foundation & Schema, Hybrid Weights)
- Phase 7.2: 🔧 **90% Complete** (Exam Setup UI - Template System remaining)
- Phase 7.3: ⚠️ **May Not Be Needed** (Existing UI handles dimension tagging)
- Phase 7.4-7.6: ✅ **Complete** (Multi-Dimensional Analytics)
- Phase 7.7: 🚀 **Not Started** (Polish & Optimization)

---

## Phase Status Summary

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Database Foundation | ✅ Complete |
| 2 | Exam Setup & UI Foundation | ✅ Complete |
| 3 | Subject Hierarchy Editor | ✅ Complete |
| 4 | Question Entry System | ✅ Complete |
| 5 | Entry Review & Browsing | ✅ Complete |
| 6 | Analytics & Patterns | ✅ **Complete** |
| **7.1** | **Foundation & Schema** | ✅ **Complete** |
| **7.2** | **Exam Setup UI** | 🔧 **90% Complete** |
| **7.3** | **Question Entry UI** | ⚠️ **May Not Be Needed** |
| **7.4-7.6** | **Multi-Dimensional Analytics** | ✅ **Complete** |
| **7.7** | **Polish & Optimization** | 🚀 **Not Started** |
| 8 | Anki Integration | Planned |
| 9 | Calendar & Scheduling | Planned |
| 10 | Subject Hierarchy Notes | 📋 Planning Complete |
| 11 | Cloud Sync (Optional) | Idea |

---

## Production Readiness

**WIMI is production-ready for personal use** with:
- ✅ User accounts and authentication
- ✅ Exam setup wizard (simple and multi-dimensional)
- ✅ Question entry with metacognitive reflection
- ✅ Media attachments
- ✅ Entry browsing and search
- ✅ Comprehensive analytics dashboard
- ✅ Multi-dimensional analytics with D3.js heatmap
- ✅ Windows executable build (PyInstaller)

---

## Phase 7: Multi-Dimensional Hierarchies (MOSTLY COMPLETE)

**Status:** 90% Complete  
**Documentation:** `docs/QUICK_START_PHASE7.md`, `docs/handoff/HANDOFF_2026-01-18_PHASE_7_4_7_6_ANALYTICS.md`

Transform WIMI's hierarchy system to support **optional multi-dimensional categorization** for complex standardized exams (NBME, USMLE) while maintaining simplicity for straightforward exams (SAT, GRE).

### Phase 7 Sub-Phase Status

| Sub-Phase | Description | Status | Completed |
|-----------|-------------|--------|-----------|
| **7.1** | Foundation & Schema | ✅ Complete | Jan 12, 2026 |
| **7.2** | Exam Setup UI | 🔧 90% | Stage 2.4 remaining |
| **7.3** | Question Entry UI | ⚠️ May not be needed | - |
| **7.4-7.6** | Multi-Dimensional Analytics | ✅ Complete | Jan 18, 2026 |
| **7.7** | Polish & Optimization | 🚀 Not Started | - |

### 7.1 Foundation & Schema ✅ Complete

| Feature | Status |
|---------|--------|
| Multi-dimensional hierarchy schema | ✅ |
| `exam_dimensions` table | ✅ |
| `dimension_id` on subject_nodes | ✅ |
| Hybrid weight system (official + relative) | ✅ |
| Weight import from external sources | ✅ |
| Weight locking and confidence indicators | ✅ |

### 7.2 Exam Setup UI 🔧 90% Complete

| Stage | Description | Status |
|-------|-------------|--------|
| 2.1 | Exam Type Selection | ✅ Complete |
| 2.2 | Dimension Definition UI | ✅ Complete |
| 2.3 | Per-Dimension Hierarchy Builder | ✅ Complete |
| **2.4** | **Template System** | 🚀 **Ready to Begin** |
| 2.5 | Bridge Integration | ✅ Complete |

**Stage 2.4 Template System Tasks:**
- Pre-configured exam templates (NBME Shelf, USMLE, SAT, GRE)
- Template selection UI in exam wizard
- Auto-populate dimensions and hierarchy levels
- Allow customization after template selection

### 7.3 Question Entry UI ⚠️ May Not Be Needed

**Key Discovery (Jan 18, 2026):** The current subject mapping UI already supports dimension selection. When users select subjects from dimension-organized hierarchies, the relationships are captured via `entry_subject_mappings` + `subject_nodes.dimension_id`. Analytics confirmed working with this data structure.

**Recommendation:** Evaluate whether explicit dimension selector adds value over current workflow. Defer implementation unless user feedback indicates need.

### 7.4-7.6 Multi-Dimensional Analytics ✅ Complete

**Implemented:** January 18, 2026 (+3,500 lines across 15 files)

| Component | Description | Lines |
|-----------|-------------|-------|
| Database methods (9 new) | Cross-dimension analytics queries | ~600 |
| Bridge methods (9 new) | Python-JS communication | ~200 |
| API wrappers (9 new) | JavaScript API layer | ~100 |
| `dimension_analytics.js` | Dimension selector component | ~250 |
| `dimension_heatmap.js` | D3.js cross-dimension heatmap | ~400 |
| `dimension_insights.js` | Study recommendations, interaction effects | ~300 |
| `test_dimension_analytics.py` | Comprehensive tests (17 tests) | ~500 |

**Analytics Features:**
- Dimension performance overview
- Cross-dimension heatmap visualization (D3.js)
- Triple dimension performance ranking
- Interaction effect detection (10% threshold)
- Weighted study recommendations
- Temporal trends by dimension
- Mistake type analysis by dimension
- CSV export for heatmap data

**Key Technical Note:** Analytics query `entry_subject_mappings` joined with `subject_nodes.dimension_id`, NOT `question_hierarchy_tags`.

### 7.7 Polish & Optimization 🚀 Not Started

| Task | Priority | Status |
|------|----------|--------|
| Query caching for analytics | High | Planned |
| Performance testing with large datasets | Medium | Planned |
| UI/UX refinements | Medium | Planned |
| Integration tests | Medium | Planned |
| User documentation | Low | Planned |

---

## Phase 6: Analytics & Patterns ✅ COMPLETE

**Status:** All 15 Stages Complete (January 3, 2026)  
**Documentation:** `docs/phases/PHASE6_IMPLEMENTATION_PLAN.md`

### Delivered Components

| Component | Description |
|-----------|-------------|
| **Dashboard Overview** | Total entries, this week stats, sessions, avg difficulty |
| **Subject Sunburst** | D3.js hierarchical sunburst chart |
| **Tag Analysis** | Donut chart with legend for mistake types |
| **Activity Trends** | Line chart (7d/30d/90d/all) |
| **Pattern Detection** | Smart insights engine with recommendations |
| **Activity Heatmap** | GitHub-style study calendar |
| **Streak Tracking** | Current/longest streak, active days |
| **Goal Setting** | Weekly goal modal with progress |
| **Source Comparison** | Multi-line D3.js chart + table |
| **Weight Analysis** | Subject vs exam weight with quadrant categorization |
| **Efficiency Score** | Study efficiency calculation |

---

## Phase 5: Entry Review & Browsing ✅ COMPLETE

**Status:** Complete (January 1, 2026)  
**Documentation:** `docs/phases/PHASE5_COMPLETE.md`

### Delivered Features

- Entry list view with card/table toggle
- Advanced filter system (subjects, tags, date, session)
- Full-text search with fuzzy matching
- Entry detail view with edit mode
- Related topics suggestions
- Pagination with "Load More"
- Media gallery view
- Entry statistics display

---

## Phase 4: Question Entry System ✅ COMPLETE

**Status:** Complete (December 29, 2025)  
**Documentation:** `docs/phases/PHASE4_COMPLETE.md`

### Delivered Features

- Session-based entry workflow
- Question entry form with 6 collapsible sections
- Subject search with fuzzy matching (Fuse.js)
- Hierarchical tag picker with inline creation
- Keyboard navigation
- Auto-save (30s interval)
- Draft vs Complete save modes
- Media upload (paste, drag-drop, browse)
- Thumbnail display with actions

---

## Upcoming Phases

### Phase 8: Anki Integration (Planned)

Correlation between WIMI entries and Anki performance.

| Feature | Description | Priority |
|---------|-------------|----------|
| AnkiConnect Setup | Configure connection | High |
| Tag Mapping | Map tags to exams | High |
| Card Linking | Link entries to Anki cards | Medium |
| Performance Correlation | Show Anki stats on entries | Medium |

### Phase 9: Calendar & Scheduling (Planned)

Study planning and session scheduling.

| Feature | Description | Priority |
|---------|-------------|----------|
| Calendar View | Visual calendar of study sessions | High |
| Event Creation | Schedule study sessions | High |
| Reminders | Desktop notifications | Medium |
| iCal Export | Export to external calendars | Low |

### Phase 10: Subject Hierarchy Notes (Planning Complete)

**Status:** 📋 Design Document Complete  
**Documentation:** `docs/planning/Notes_Integration.md`

| Feature | Description | Priority |
|---------|-------------|----------|
| Hierarchical Notes | Notes at user-defined hierarchy levels | High |
| Rich Text Editor | Full formatting support | High |
| Template System | Built-in and custom templates | High |
| Media Support | Images, links, attachments | Medium |
| Anki Linking | Associate notes with Anki cards | Medium |

---

## Technical Improvements

| Item | Description | Priority | Status |
|------|-------------|----------|--------|
| Query caching | Cache analytics queries | High | Planned (7.7) |
| Performance optimization | Large hierarchies, multi-dim queries | Medium | Planned (7.7) |
| Increase test coverage | Target 90%+ coverage | Medium | Ongoing |
| Drag-drop reordering | Tree editor enhancement | Low | Deferred |

---

## Long-Term Ideas

| Feature | Description | Status |
|---------|-------------|--------|
| AI Suggestions | Suggest tags, subjects, dimensions | Idea |
| Auto-Tagging | NLP-based dimension tagging | Idea |
| Mobile App | View on mobile | Idea |
| Cloud Sync | Cross-device synchronization | Idea |
| Study Groups | Collaborative mistake review | Idea |

---

## Document History

| Date | Version | Changes |
|------|---------|---------|
| **Jan 20, 2026** | **2.0** | **Major update: Phase 7.4-7.6 complete, Phase 6 complete, overall status refresh** |
| Jan 12, 2026 | 1.8 | Added Phase 7 planning complete |
| Jan 3, 2026 | 1.7 | Added Phase 9: Subject Hierarchy Notes planning |
| Jan 1, 2026 | 1.6 | Phase 6 Stages 1-2 complete |
| Jan 1, 2026 | 1.5 | Phase 5 complete |
| Dec 29, 2025 | 1.4 | Phase 4 complete |
| Dec 26, 2025 | 1.0 | Initial roadmap created |

---

**END OF ROADMAP DOCUMENT**
