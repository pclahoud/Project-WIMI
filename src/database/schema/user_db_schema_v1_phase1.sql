-- User Database Schema v1.0.0 - Phase 1
-- Core tables for question analysis and metacognition
-- Author: WIMI Development Team
-- Date: 2024

-- ==============================================================================
-- TABLE 1: user_preferences
-- Stores user-specific UI and behavior preferences
-- ==============================================================================
CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    
    -- UI/Display Preferences
    theme_name VARCHAR(50) DEFAULT 'default',
    language_code VARCHAR(10) DEFAULT 'en',
    font_size_scale REAL DEFAULT 1.0 CHECK (font_size_scale >= 0.5 AND font_size_scale <= 3.0),
    show_animations BOOLEAN DEFAULT TRUE,
    
    -- Study Session Defaults
    default_session_duration_minutes INTEGER DEFAULT 60 CHECK (default_session_duration_minutes >= 15 AND default_session_duration_minutes <= 480),
    default_break_interval_minutes INTEGER DEFAULT 25 CHECK (default_break_interval_minutes >= 5 AND default_break_interval_minutes <= 60),
    default_long_break_minutes INTEGER DEFAULT 15 CHECK (default_long_break_minutes >= 10 AND default_long_break_minutes <= 60),
    long_break_interval_rounds INTEGER DEFAULT 4 CHECK (long_break_interval_rounds >= 2 AND long_break_interval_rounds <= 10),
    timer_display_size TEXT DEFAULT 'normal' CHECK (timer_display_size IN ('normal', 'large')),
    hotkey_timer_pause_resume TEXT DEFAULT 'Alt+P',
    hotkey_timer_new_round TEXT DEFAULT 'Alt+N',
    hotkey_timer_end_round TEXT DEFAULT 'Alt+E',

    -- Dashboard Settings
    dashboard_auto_refresh_seconds INTEGER DEFAULT 300 CHECK (dashboard_auto_refresh_seconds >= 30 AND dashboard_auto_refresh_seconds <= 3600),
    show_progress_graphs BOOLEAN DEFAULT TRUE,
    show_mistake_heatmap BOOLEAN DEFAULT TRUE,
    
    -- Calendar Settings
    calendar_time_slot_minutes INTEGER DEFAULT 30 CHECK (calendar_time_slot_minutes IN (15, 30, 60)),
    calendar_default_view VARCHAR(20) DEFAULT 'week' CHECK (calendar_default_view IN ('day', 'week', 'month')),
    
    -- Subject Hierarchy Settings
    child_subject_weight_inheritance_fraction REAL DEFAULT 1.0 CHECK (child_subject_weight_inheritance_fraction >= 0.1 AND child_subject_weight_inheritance_fraction <= 1.0),
    
    -- Entry Review Settings
    entry_review_items_per_page INTEGER DEFAULT 25 CHECK (entry_review_items_per_page >= 10 AND entry_review_items_per_page <= 100),
    entry_review_default_sort VARCHAR(50) DEFAULT 'date_desc',
    
    -- Anki Integration Settings
    ankiconnect_enabled BOOLEAN DEFAULT FALSE,
    ankiconnect_host VARCHAR(255) DEFAULT 'localhost',
    ankiconnect_port INTEGER DEFAULT 8765 CHECK (ankiconnect_port >= 1000 AND ankiconnect_port <= 65535),
    anki_cache_refresh_interval_minutes INTEGER DEFAULT 60 CHECK (anki_cache_refresh_interval_minutes >= 1 AND anki_cache_refresh_interval_minutes <= 1440),
    
    -- Backup Settings
    backup_frequency_hours INTEGER DEFAULT 24 CHECK (backup_frequency_hours >= 1 AND backup_frequency_hours <= 168),
    backup_retention_days INTEGER DEFAULT 30 CHECK (backup_retention_days >= 7 AND backup_retention_days <= 365),
    
    -- Performance Settings
    realtime_update_delay_ms INTEGER DEFAULT 500 CHECK (realtime_update_delay_ms >= 100 AND realtime_update_delay_ms <= 5000),
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences(user_id);

-- ==============================================================================
-- TABLE 2: subject_nodes
-- Hierarchical subject/topic structure for organizing questions
-- Supports hybrid weight system with official ranges and relative weights
-- ==============================================================================
CREATE TABLE IF NOT EXISTS subject_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_context VARCHAR(50) NOT NULL,  -- e.g., 'SAT', 'GRE', 'ACT'
    parent_id INTEGER REFERENCES subject_nodes(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    level_type VARCHAR(50) NOT NULL,  -- e.g., 'Domain', 'Topic', 'Subtopic'
    sort_order INTEGER DEFAULT 1,
    
    -- Exam weight information (absolute weights - for official/top-level)
    exam_weight_low REAL,   -- Lower bound of weight range (e.g., 20 for "20%-25%")
    exam_weight_high REAL,  -- Upper bound of weight range (e.g., 25 for "20%-25%")
    exam_source VARCHAR(255),  -- Source document for weight info (e.g., "NBME Content Outline 2024")
    
    -- Relative weight (for children within a parent with official weights)
    -- Represents percentage of parent's weight (0-100)
    relative_weight REAL CHECK (relative_weight IS NULL OR (relative_weight >= 0 AND relative_weight <= 100)),
    
    -- Weight metadata
    -- 'official' = imported from authoritative source (NBME, ETS, etc.)
    -- 'derived' = calculated from parent/children
    -- 'user_estimate' = user's estimate for children of official-weighted parents
    -- 'user_defined' = user created from scratch
    weight_source VARCHAR(50) DEFAULT 'user_defined'
        CHECK (weight_source IN ('official', 'derived', 'user_estimate', 'user_defined')),
    
    -- Whether this weight can be edited (official weights should be locked)
    weight_locked BOOLEAN DEFAULT FALSE,
    
    -- Other metadata
    outline_type VARCHAR(50) DEFAULT 'content',  -- 'content', 'competency', etc.
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'archived', 'deprecated')),
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(exam_context, name, parent_id)
);

CREATE INDEX IF NOT EXISTS idx_subject_nodes_exam ON subject_nodes(exam_context);
CREATE INDEX IF NOT EXISTS idx_subject_nodes_parent ON subject_nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_subject_nodes_status ON subject_nodes(status);
CREATE INDEX IF NOT EXISTS idx_subject_nodes_weight_source ON subject_nodes(exam_context, weight_source);

-- ==============================================================================
-- TABLE 3: question_analyses
-- Core table for storing incorrect question analyses with metacognition
-- ==============================================================================
CREATE TABLE IF NOT EXISTS question_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_context VARCHAR(50) NOT NULL,
    question_source VARCHAR(255) NOT NULL,  -- e.g., "Official SAT Practice Test 1"
    question_source_id VARCHAR(255) NOT NULL,  -- e.g., "Section3_Q15"
    
    -- Question details
    answered_incorrectly_date DATE NOT NULL,
    user_selected_answer VARCHAR(10),
    correct_answer VARCHAR(10),
    perceived_difficulty INTEGER CHECK (perceived_difficulty >= 1 AND perceived_difficulty <= 5),
    
    -- Metacognitive reflection
    metacognitive_reflection TEXT,
    question_explanation TEXT,
    user_notes TEXT,
    
    -- Question metadata
    time_spent_on_question INTEGER,  -- seconds
    confidence_before_answer INTEGER CHECK (confidence_before_answer >= 1 AND confidence_before_answer <= 5),
    mistake_category VARCHAR(50),  -- e.g., 'knowledge_gap', 'careless_mistake'
    
    -- Review tracking
    review_status VARCHAR(50) DEFAULT 'pending_review' CHECK (review_status IN ('pending_review', 'reviewing', 'mastered', 'skipped')),
    last_reviewed_at TIMESTAMP,
    times_reviewed INTEGER DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(exam_context, question_source, question_source_id)
);

CREATE INDEX IF NOT EXISTS idx_question_analyses_exam ON question_analyses(exam_context);
CREATE INDEX IF NOT EXISTS idx_question_analyses_date ON question_analyses(answered_incorrectly_date);
CREATE INDEX IF NOT EXISTS idx_question_analyses_category ON question_analyses(mistake_category);
CREATE INDEX IF NOT EXISTS idx_question_analyses_status ON question_analyses(review_status);

-- ==============================================================================
-- TABLE 4: question_topic_assignments
-- Links questions to subject nodes (topics)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS question_topic_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_analysis_id INTEGER NOT NULL REFERENCES question_analyses(id) ON DELETE CASCADE,
    subject_node_id INTEGER NOT NULL REFERENCES subject_nodes(id) ON DELETE CASCADE,
    exam_context VARCHAR(50) NOT NULL,
    
    -- Assignment metadata
    assignment_type VARCHAR(20) DEFAULT 'primary' CHECK (assignment_type IN ('primary', 'secondary')),
    assigned_by VARCHAR(20) DEFAULT 'user' CHECK (assigned_by IN ('user', 'auto_suggested')),
    confidence_score REAL,  -- For auto-suggested assignments
    
    -- Timestamps
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(question_analysis_id, subject_node_id)
);

CREATE INDEX IF NOT EXISTS idx_qta_question ON question_topic_assignments(question_analysis_id);
CREATE INDEX IF NOT EXISTS idx_qta_subject ON question_topic_assignments(subject_node_id);
CREATE INDEX IF NOT EXISTS idx_qta_exam ON question_topic_assignments(exam_context);

-- ==============================================================================
-- TABLE 5: tags
-- User-created tags for organizing and filtering questions
-- ==============================================================================
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_context VARCHAR(50) NOT NULL,
    tag_name VARCHAR(100) NOT NULL,
    tag_category VARCHAR(50) DEFAULT 'other',  -- e.g., 'mistake_type', 'study_method', 'difficulty'
    color_hex VARCHAR(7) DEFAULT '#2196F3',  -- Hex color for UI display
    description TEXT,
    
    -- Usage tracking
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(exam_context, tag_name)
);

CREATE INDEX IF NOT EXISTS idx_tags_exam ON tags(exam_context);
CREATE INDEX IF NOT EXISTS idx_tags_category ON tags(tag_category);
CREATE INDEX IF NOT EXISTS idx_tags_active ON tags(is_active);

-- ==============================================================================
-- TABLE 6: question_tags
-- Links questions to tags (many-to-many relationship)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS question_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_analysis_id INTEGER NOT NULL REFERENCES question_analyses(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    exam_context VARCHAR(50) NOT NULL,
    
    -- Tag application metadata
    assigned_by VARCHAR(20) DEFAULT 'user' CHECK (assigned_by IN ('user', 'auto_suggested')),
    
    -- Timestamps
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(question_analysis_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_question_tags_question ON question_tags(question_analysis_id);
CREATE INDEX IF NOT EXISTS idx_question_tags_tag ON question_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_question_tags_exam ON question_tags(exam_context);
