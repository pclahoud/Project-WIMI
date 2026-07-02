-- User Database Schema - Subject Aliases
-- Provides alias support for improved subject searchability
-- Author: WIMI Development Team
-- Date: January 2026

-- ==============================================================================
-- TABLE: subject_aliases
-- Stores alternative names for subjects to improve search discoverability
-- Supports eponyms, acronyms, alternate names, and colloquial terms
-- ==============================================================================
CREATE TABLE IF NOT EXISTS subject_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_node_id INTEGER NOT NULL,           -- FK to subject_nodes.id
    exam_context VARCHAR(50) NOT NULL,          -- Matches subject_nodes.exam_context for efficiency
    alias_name VARCHAR(255) NOT NULL,           -- The alternative name
    alias_type VARCHAR(50) NOT NULL DEFAULT 'alternate_name'
        CHECK (alias_type IN ('eponym', 'acronym', 'alternate_name', 'colloquial')),
    is_primary BOOLEAN DEFAULT FALSE,           -- If true, prefer this alias in display
    usage_count INTEGER DEFAULT 0,              -- Track how often this alias is searched
    notes TEXT,                                 -- Optional notes about the alias
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key
    FOREIGN KEY (subject_node_id) REFERENCES subject_nodes(id) ON DELETE CASCADE,

    -- Each alias must be unique per subject
    UNIQUE(subject_node_id, alias_name)
);

-- Index for fast alias lookups (case-insensitive via COLLATE NOCASE)
CREATE INDEX IF NOT EXISTS idx_subject_aliases_name ON subject_aliases(alias_name COLLATE NOCASE);

-- Index for getting all aliases for a subject
CREATE INDEX IF NOT EXISTS idx_subject_aliases_subject ON subject_aliases(subject_node_id);

-- Index for getting all aliases in an exam context
CREATE INDEX IF NOT EXISTS idx_subject_aliases_exam ON subject_aliases(exam_context);

-- Compound index for exam-scoped alias searches
CREATE INDEX IF NOT EXISTS idx_subject_aliases_exam_name ON subject_aliases(exam_context, alias_name COLLATE NOCASE);
