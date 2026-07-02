-- Phase 9: Entry Notes Schema
-- Multiple discrete notes per question entry with optional subject linking

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
