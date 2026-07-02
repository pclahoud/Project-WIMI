-- Saved Delimiters Schema
-- User-specific saved delimiter presets for the Export Question IDs dialog

CREATE TABLE IF NOT EXISTS saved_delimiters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    hotkey TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
