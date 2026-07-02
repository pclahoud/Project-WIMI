-- User Database Schema v1.2.0 - Phase 4
-- Question Entry System & Review Sessions
-- Author: WIMI Development Team
-- Date: December 2025

-- ==============================================================================
-- PHASE 4 TABLES: Question Entry System
-- These tables are ADDITIVE - Phase 1, 2, 3 tables remain unchanged
-- ==============================================================================

-- ==============================================================================
-- MODIFICATIONS TO EXISTING TABLES
-- ==============================================================================

-- Add hierarchy support to tags table
-- Note: Run these only if columns don't exist
-- ALTER TABLE tags ADD COLUMN parent_id INTEGER REFERENCES tags(id) NULL;
-- ALTER TABLE tags ADD COLUMN is_group BOOLEAN DEFAULT FALSE;
-- ALTER TABLE tags ADD COLUMN display_order INTEGER DEFAULT 0;

-- ==============================================================================
-- TABLE P4.1: question_sources
-- Catalog of question sources (question banks, textbooks, etc.)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS question_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    source_name VARCHAR(255) NOT NULL,
    source_type TEXT DEFAULT 'other' CHECK (source_type IN (
        'official_prep', 'commercial_prep', 'textbook', 'online_platform',
        'practice_tests', 'tutoring_materials', 'flashcard_system',
        'video_course', 'study_group', 'previous_exams', 'other'
    )),
    exam_context VARCHAR(100),  -- Optional: link to specific exam
    description TEXT,
    url VARCHAR(500),
    total_questions INTEGER,
    user_rating INTEGER CHECK (user_rating BETWEEN 1 AND 5),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_question_sources_user ON question_sources(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_question_sources_exam ON question_sources(exam_context);

-- ==============================================================================
-- TABLE P4.2: review_sessions
-- Track question review sessions (practice test analysis sessions)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS review_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    exam_context_id INTEGER NOT NULL REFERENCES exam_contexts(id) ON DELETE CASCADE,
    question_source_id INTEGER REFERENCES question_sources(id),
    
    -- Session info
    session_name VARCHAR(255),
    date_encountered DATE NOT NULL DEFAULT (date('now')),
    
    -- Question counts
    total_questions INTEGER NOT NULL CHECK (total_questions > 0),
    total_incorrect INTEGER NOT NULL CHECK (total_incorrect >= 0),
    entries_completed INTEGER DEFAULT 0,
    
    -- Session status
    session_status TEXT DEFAULT 'in_progress' CHECK (session_status IN (
        'in_progress', 'completed', 'abandoned'
    )),
    
    -- Timestamps
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_review_sessions_user ON review_sessions(user_id, session_status);
CREATE INDEX IF NOT EXISTS idx_review_sessions_exam ON review_sessions(exam_context_id);
CREATE INDEX IF NOT EXISTS idx_review_sessions_date ON review_sessions(date_encountered DESC);

-- ==============================================================================
-- TABLE P4.3: question_entries
-- Individual question entries within a review session
-- ==============================================================================
CREATE TABLE IF NOT EXISTS question_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_session_id INTEGER NOT NULL REFERENCES review_sessions(id) ON DELETE CASCADE,
    entry_order INTEGER NOT NULL,
    
    -- Question identification
    question_id VARCHAR(255),  -- User's reference (page #, question #, etc.)
    
    -- Answer information
    user_answer TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    perceived_difficulty INTEGER CHECK (perceived_difficulty BETWEEN 1 AND 5),
    time_spent_seconds INTEGER,
    
    -- Core reflection fields (REQUIRED for completion)
    reflection TEXT,
    explanation TEXT,
    
    -- Additional notes
    notes TEXT,
    
    -- Draft status
    is_draft BOOLEAN DEFAULT TRUE,
    draft_missing_fields TEXT CHECK (json_valid(draft_missing_fields) OR draft_missing_fields IS NULL),
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_question_entries_session ON question_entries(review_session_id, entry_order);
CREATE INDEX IF NOT EXISTS idx_question_entries_draft ON question_entries(is_draft, review_session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_entry_order ON question_entries(review_session_id, entry_order);

-- ==============================================================================
-- TABLE P4.4: entry_subject_mappings
-- Link question entries to subject hierarchy nodes
-- ==============================================================================
CREATE TABLE IF NOT EXISTS entry_subject_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_entry_id INTEGER NOT NULL REFERENCES question_entries(id) ON DELETE CASCADE,
    subject_node_id INTEGER NOT NULL REFERENCES subject_nodes(id) ON DELETE CASCADE,
    mapping_type TEXT DEFAULT 'primary' CHECK (mapping_type IN ('primary', 'secondary')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_entry_subjects_entry ON entry_subject_mappings(question_entry_id);
CREATE INDEX IF NOT EXISTS idx_entry_subjects_node ON entry_subject_mappings(subject_node_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_entry_subject ON entry_subject_mappings(question_entry_id, subject_node_id);

-- ==============================================================================
-- TABLE P4.5: entry_tags
-- Link question entries to tags
-- ==============================================================================
CREATE TABLE IF NOT EXISTS entry_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_entry_id INTEGER NOT NULL REFERENCES question_entries(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_entry_tags_entry ON entry_tags(question_entry_id);
CREATE INDEX IF NOT EXISTS idx_entry_tags_tag ON entry_tags(tag_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_entry_tag ON entry_tags(question_entry_id, tag_id);

-- ==============================================================================
-- TABLE P4.6: entry_media
-- Media attachments for question entries
-- ==============================================================================
CREATE TABLE IF NOT EXISTS entry_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_entry_id INTEGER NOT NULL REFERENCES question_entries(id) ON DELETE CASCADE,
    
    -- File information
    file_uuid VARCHAR(36) NOT NULL,  -- UUID for actual file on disk
    original_filename VARCHAR(255),
    user_filename VARCHAR(255),  -- User can rename
    mime_type VARCHAR(100),
    file_size_bytes INTEGER,
    
    -- Organization
    sort_order INTEGER DEFAULT 0,
    
    -- Subject linking (for future matching)
    linked_subject_ids TEXT CHECK (json_valid(linked_subject_ids) OR linked_subject_ids IS NULL),
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_entry_media_entry ON entry_media(question_entry_id, sort_order);

-- ==============================================================================
-- TRIGGERS: Auto-update timestamps
-- ==============================================================================

-- question_sources timestamp trigger
CREATE TRIGGER IF NOT EXISTS tr_question_sources_updated_at
    AFTER UPDATE ON question_sources
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE question_sources 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;

-- review_sessions timestamp trigger
CREATE TRIGGER IF NOT EXISTS tr_review_sessions_updated_at
    AFTER UPDATE ON review_sessions
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE review_sessions 
    SET updated_at = CURRENT_TIMESTAMP,
        last_activity_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

-- question_entries timestamp trigger
CREATE TRIGGER IF NOT EXISTS tr_question_entries_updated_at
    AFTER UPDATE ON question_entries
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE question_entries 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;

-- entry_media timestamp trigger
CREATE TRIGGER IF NOT EXISTS tr_entry_media_updated_at
    AFTER UPDATE ON entry_media
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE entry_media 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;

-- ==============================================================================
-- VIEWS: Convenient data access
-- ==============================================================================

-- View: Review session summary with completion stats
CREATE VIEW IF NOT EXISTS v_review_session_summary AS
SELECT 
    rs.id,
    rs.user_id,
    rs.exam_context_id,
    ec.exam_name,
    rs.question_source_id,
    qs.source_name,
    rs.session_name,
    rs.date_encountered,
    rs.total_questions,
    rs.total_incorrect,
    rs.entries_completed,
    rs.session_status,
    rs.started_at,
    rs.completed_at,
    rs.last_activity_at,
    CASE 
        WHEN rs.total_incorrect > 0 
        THEN ROUND(CAST(rs.entries_completed AS FLOAT) / rs.total_incorrect * 100, 1)
        ELSE 100
    END as completion_percentage,
    (SELECT COUNT(*) FROM question_entries qe WHERE qe.review_session_id = rs.id AND qe.is_draft = TRUE) as draft_count
FROM review_sessions rs
LEFT JOIN exam_contexts ec ON rs.exam_context_id = ec.id
LEFT JOIN question_sources qs ON rs.question_source_id = qs.id;

-- View: Question entry with related counts
CREATE VIEW IF NOT EXISTS v_question_entry_summary AS
SELECT 
    qe.id,
    qe.review_session_id,
    qe.entry_order,
    qe.question_id,
    qe.user_answer,
    qe.correct_answer,
    qe.perceived_difficulty,
    qe.is_draft,
    qe.created_at,
    qe.updated_at,
    (SELECT COUNT(*) FROM entry_subject_mappings esm WHERE esm.question_entry_id = qe.id AND esm.mapping_type = 'primary') as primary_subject_count,
    (SELECT COUNT(*) FROM entry_subject_mappings esm WHERE esm.question_entry_id = qe.id AND esm.mapping_type = 'secondary') as secondary_subject_count,
    (SELECT COUNT(*) FROM entry_tags et WHERE et.question_entry_id = qe.id) as tag_count,
    (SELECT COUNT(*) FROM entry_media em WHERE em.question_entry_id = qe.id) as media_count
FROM question_entries qe;
