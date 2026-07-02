# Handoff: Phase 9 — Assignable Entry Notes

**Date:** February 7, 2026
**Status:** ✅ Complete
**Priority:** Normal

---

## Summary

Implemented a multi-note system for question entries. Each entry can now have multiple discrete notes, each independently assignable to specific subjects via `linked_subject_ids` JSON. This mirrors the `entry_media` pattern.

## What Was Done

### New Files (2)
- `src/database/schema/user_db_schema_v1_phase9_notes.sql` — Table schema
- `tests/database/test_entry_notes.py` — 22 unit tests

### Modified Files (9)
- `src/database/models.py` — `EntryNote` dataclass + `notes_list` on `QuestionEntry`
- `src/database/user_db.py` — Migration + 6 CRUD methods + wired into getters
- `src/app/bridge.py` — 6 `@pyqtSlot` methods + `_serialize_entry_note`
- `src/web/js/api.js` — 6 API wrappers
- `src/web/html/question_entry.html` — Note card container
- `src/web/js/question_entry.js` — Multi-note state, card management, save sync
- `src/web/html/entry_detail.html` — Tabbed notes panel
- `src/web/js/entry_detail.js` — Tabbed rendering with subject grouping
- `src/web/css/entry.css` + `src/web/css/detail.css` — Styles

### Database Schema

```sql
CREATE TABLE IF NOT EXISTS entry_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_entry_id INTEGER NOT NULL REFERENCES question_entries(id) ON DELETE CASCADE,
    content_html TEXT,
    content_json TEXT,
    sort_order INTEGER DEFAULT 0,
    linked_subject_ids TEXT CHECK (json_valid(linked_subject_ids) OR linked_subject_ids IS NULL),
    is_migrated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Auto-Migration

On first run, existing `question_entries.notes` content is automatically copied to `entry_notes` with `is_migrated=TRUE`. The migration is idempotent.

## Test Results

- 22/22 entry notes tests passing
- 40/40 existing database tests passing (no regressions)

## Known Limitations

- Legacy `question_entries.notes` field is still preserved (not removed) for backward compatibility
- The entry form `collectFormData()` now sets `notes` and `notes_json` to empty strings (all note content lives in `notesList`)
- The detail view falls back to legacy `entry.notes` rendering if `notes_list` is empty

## Next Steps

- Media Link System (shared image support) is the next high-priority feature
- Phase 7.7 Polish & Optimization
