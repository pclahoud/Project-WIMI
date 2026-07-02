-- User Database Schema v1.3.0 - Phase 6
-- Analytics & Pattern Detection System
-- Author: WIMI Development Team
-- Date: January 2026

-- ==============================================================================
-- PHASE 6 TABLES: Analytics & Goals
-- These tables are ADDITIVE - Phase 1-5 tables remain unchanged
-- ==============================================================================

-- ==============================================================================
-- TABLE P6.1: user_goals
-- Track user-defined goals for study motivation
-- ==============================================================================
CREATE TABLE IF NOT EXISTS user_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    goal_type TEXT NOT NULL DEFAULT 'weekly_entries' CHECK (goal_type IN (
        'weekly_entries', 'daily_entries', 'streak_days', 'subject_focus'
    )),
    target_value INTEGER NOT NULL CHECK (target_value > 0),
    exam_context_id INTEGER REFERENCES exam_contexts(id) ON DELETE SET NULL,
    
    -- Goal status
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_goals_user ON user_goals(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_user_goals_exam ON user_goals(exam_context_id);

-- ==============================================================================
-- TABLE P6.2: goal_periods
-- Track goal completion for each period (week, etc.)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS goal_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES user_goals(id) ON DELETE CASCADE,
    
    -- Period boundaries
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    
    -- Progress tracking
    target_value INTEGER NOT NULL,
    achieved_value INTEGER DEFAULT 0,
    is_complete BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_goal_periods_goal ON goal_periods(goal_id);
CREATE INDEX IF NOT EXISTS idx_goal_periods_dates ON goal_periods(period_start, period_end);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_goal_period ON goal_periods(goal_id, period_start);

-- ==============================================================================
-- TABLE P6.3: reflection_themes
-- Cache common themes/patterns found in reflections
-- ==============================================================================
CREATE TABLE IF NOT EXISTS reflection_themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    exam_context_id INTEGER REFERENCES exam_contexts(id) ON DELETE SET NULL,
    
    -- Theme data
    theme TEXT NOT NULL,
    theme_type TEXT DEFAULT 'general' CHECK (theme_type IN (
        'general', 'causal', 'action', 'recurring_mistake'
    )),
    frequency INTEGER DEFAULT 0,
    
    -- Related entries (JSON array of entry IDs)
    sample_entry_ids TEXT CHECK (json_valid(sample_entry_ids) OR sample_entry_ids IS NULL),
    
    -- Related tags (JSON array of tag IDs)
    related_tag_ids TEXT CHECK (json_valid(related_tag_ids) OR related_tag_ids IS NULL),
    
    -- Timestamps
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reflection_themes_user ON reflection_themes(user_id);
CREATE INDEX IF NOT EXISTS idx_reflection_themes_exam ON reflection_themes(exam_context_id);
CREATE INDEX IF NOT EXISTS idx_reflection_themes_freq ON reflection_themes(frequency DESC);

-- ==============================================================================
-- MODIFICATIONS TO EXISTING TABLES
-- ==============================================================================

-- Add reflection_quality_score to question_entries if not exists
-- This stores cached quality scores for reflections
-- ALTER TABLE question_entries ADD COLUMN reflection_quality_score REAL;

-- ==============================================================================
-- TRIGGERS: Auto-update timestamps
-- ==============================================================================

-- user_goals timestamp trigger
CREATE TRIGGER IF NOT EXISTS tr_user_goals_updated_at
    AFTER UPDATE ON user_goals
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE user_goals 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;

-- reflection_themes timestamp trigger
CREATE TRIGGER IF NOT EXISTS tr_reflection_themes_updated_at
    AFTER UPDATE ON reflection_themes
    FOR EACH ROW
    WHEN NEW.last_updated = OLD.last_updated
BEGIN
    UPDATE reflection_themes 
    SET last_updated = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;

-- ==============================================================================
-- VIEWS: Analytics convenience views
-- ==============================================================================

-- View: Daily activity counts (for heatmap)
CREATE VIEW IF NOT EXISTS v_daily_activity AS
SELECT 
    rs.user_id,
    rs.exam_context_id,
    DATE(qe.created_at) as activity_date,
    COUNT(qe.id) as entry_count,
    AVG(qe.perceived_difficulty) as avg_difficulty
FROM question_entries qe
JOIN review_sessions rs ON qe.review_session_id = rs.id
WHERE qe.is_draft = FALSE
GROUP BY rs.user_id, rs.exam_context_id, DATE(qe.created_at);

-- View: Weekly activity summary
CREATE VIEW IF NOT EXISTS v_weekly_activity AS
SELECT 
    rs.user_id,
    rs.exam_context_id,
    strftime('%Y-%W', qe.created_at) as year_week,
    DATE(qe.created_at, 'weekday 0', '-6 days') as week_start,
    COUNT(qe.id) as entry_count,
    COUNT(DISTINCT DATE(qe.created_at)) as active_days,
    AVG(qe.perceived_difficulty) as avg_difficulty
FROM question_entries qe
JOIN review_sessions rs ON qe.review_session_id = rs.id
WHERE qe.is_draft = FALSE
GROUP BY rs.user_id, rs.exam_context_id, strftime('%Y-%W', qe.created_at);

-- View: Subject mistake counts
CREATE VIEW IF NOT EXISTS v_subject_mistake_counts AS
SELECT 
    rs.user_id,
    rs.exam_context_id,
    esm.subject_node_id,
    sn.name as subject_name,
    sn.parent_id,
    sn.exam_weight_low as exam_weight,
    COUNT(DISTINCT qe.id) as mistake_count,
    AVG(qe.perceived_difficulty) as avg_difficulty,
    MAX(qe.created_at) as last_mistake_date
FROM entry_subject_mappings esm
JOIN question_entries qe ON esm.question_entry_id = qe.id
JOIN review_sessions rs ON qe.review_session_id = rs.id
JOIN subject_nodes sn ON esm.subject_node_id = sn.id
WHERE qe.is_draft = FALSE AND esm.mapping_type = 'primary'
GROUP BY rs.user_id, rs.exam_context_id, esm.subject_node_id;

-- View: Tag usage counts
CREATE VIEW IF NOT EXISTS v_tag_usage_counts AS
SELECT 
    rs.user_id,
    rs.exam_context_id,
    et.tag_id,
    t.tag_name,
    t.color_hex,
    t.parent_id as tag_group_id,
    COUNT(DISTINCT qe.id) as usage_count,
    AVG(qe.perceived_difficulty) as avg_difficulty
FROM entry_tags et
JOIN question_entries qe ON et.question_entry_id = qe.id
JOIN review_sessions rs ON qe.review_session_id = rs.id
JOIN tags t ON et.tag_id = t.id
WHERE qe.is_draft = FALSE
GROUP BY rs.user_id, rs.exam_context_id, et.tag_id;

-- View: Source performance
CREATE VIEW IF NOT EXISTS v_source_performance AS
SELECT 
    rs.user_id,
    rs.exam_context_id,
    rs.question_source_id,
    qs.source_name,
    COUNT(qe.id) as entry_count,
    AVG(qe.perceived_difficulty) as avg_difficulty,
    MIN(qe.created_at) as first_entry,
    MAX(qe.created_at) as last_entry
FROM question_entries qe
JOIN review_sessions rs ON qe.review_session_id = rs.id
LEFT JOIN question_sources qs ON rs.question_source_id = qs.id
WHERE qe.is_draft = FALSE
GROUP BY rs.user_id, rs.exam_context_id, rs.question_source_id;

-- View: Current week goals progress
CREATE VIEW IF NOT EXISTS v_current_goal_progress AS
SELECT 
    ug.id as goal_id,
    ug.user_id,
    ug.goal_type,
    ug.target_value,
    ug.exam_context_id,
    gp.id as period_id,
    gp.period_start,
    gp.period_end,
    gp.achieved_value,
    gp.is_complete,
    CASE 
        WHEN ug.target_value > 0 
        THEN ROUND(CAST(gp.achieved_value AS FLOAT) / ug.target_value * 100, 1)
        ELSE 0
    END as progress_pct
FROM user_goals ug
LEFT JOIN goal_periods gp ON ug.id = gp.goal_id
    AND DATE('now') BETWEEN gp.period_start AND gp.period_end
WHERE ug.is_active = TRUE;
