-- User Database Schema v1.0.0 - Phase 7
-- Multi-Dimensional Hierarchies for Complex Standardized Exams
-- Author: WIMI Development Team
-- Date: January 2026

-- ==============================================================================
-- TABLE: exam_dimensions
-- Defines categorical dimensions for each exam (e.g., Site of Care, Physician Task, System)
-- Only used for multi-dimensional exams; simple exams do not use this table
-- ==============================================================================
CREATE TABLE IF NOT EXISTS exam_dimensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL,                   -- FK to exam_contexts.id (the exam this dimension belongs to)
    name TEXT NOT NULL,                         -- e.g., "Site of Care", "Physician Task", "System"
    display_order INTEGER NOT NULL,             -- UI ordering (1, 2, 3, ...)
    is_required INTEGER DEFAULT 1,              -- Must tag in this dimension? (1=yes, 0=no)
    allow_multiple INTEGER DEFAULT 0,           -- Can select multiple items? (1=yes, 0=no)
    description TEXT,                           -- Help text for users
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    FOREIGN KEY (exam_id) REFERENCES exam_contexts(id) ON DELETE CASCADE,
    UNIQUE(exam_id, name),                      -- Dimension names unique within exam
    UNIQUE(exam_id, display_order)              -- Display order unique within exam
);

-- Indexes for exam_dimensions
CREATE INDEX IF NOT EXISTS idx_dimensions_exam ON exam_dimensions(exam_id);
CREATE INDEX IF NOT EXISTS idx_dimensions_order ON exam_dimensions(exam_id, display_order);

-- ==============================================================================
-- TABLE: question_hierarchy_tags
-- Links questions (entries) to hierarchy nodes with dimension context
-- This enables multi-dimensional tagging where a question can be tagged
-- with one node per dimension (or multiple if allow_multiple=1)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS question_hierarchy_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,                  -- FK to question_entries.id (the question entry)
    hierarchy_id INTEGER NOT NULL,              -- FK to subject_nodes.id (the hierarchy node)
    dimension_id INTEGER NOT NULL,              -- FK to exam_dimensions.id (which dimension this tag is in)
    tagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign keys
    FOREIGN KEY (entry_id) REFERENCES question_entries(id) ON DELETE CASCADE,
    FOREIGN KEY (hierarchy_id) REFERENCES subject_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (dimension_id) REFERENCES exam_dimensions(id) ON DELETE CASCADE,
    
    -- Prevent duplicate tags (same entry, same dimension, same hierarchy node)
    UNIQUE(entry_id, dimension_id, hierarchy_id)
);

-- Indexes for question_hierarchy_tags
CREATE INDEX IF NOT EXISTS idx_tags_entry ON question_hierarchy_tags(entry_id);
CREATE INDEX IF NOT EXISTS idx_tags_hierarchy ON question_hierarchy_tags(hierarchy_id);
CREATE INDEX IF NOT EXISTS idx_tags_dimension ON question_hierarchy_tags(dimension_id);
-- Unique index to enforce one tag per dimension per entry (unless allow_multiple)
-- Note: This is enforced at application level since allow_multiple is per-dimension
CREATE INDEX IF NOT EXISTS idx_tags_entry_dimension ON question_hierarchy_tags(entry_id, dimension_id);
