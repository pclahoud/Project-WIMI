-- User Database Schema v1.1.0 - Phase 2
-- Subject Hierarchy Management & Exam Setup Wizard
-- Author: WIMI Development Team
-- Date: 2025

-- ==============================================================================
-- PHASE 2 TABLES: Exam Context & Weight Management
-- These tables are ADDITIVE - Phase 1 tables remain unchanged
-- ==============================================================================

-- ==============================================================================
-- TABLE P2.1: exam_contexts
-- Stores exam configuration, weight rules, and hierarchy definitions
-- ==============================================================================
CREATE TABLE IF NOT EXISTS exam_contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    exam_name VARCHAR(255) NOT NULL,
    exam_description TEXT,
    exam_date DATE,
    created_date DATE DEFAULT (date('now')),
    is_active BOOLEAN DEFAULT TRUE,
    
    -- JSON: Hierarchy level names ["System", "Subsystem", "Topic", "Subtopic", "Child"]
    default_hierarchy_levels TEXT NOT NULL DEFAULT '["System", "Subsystem", "Topic", "Subtopic", "Child"]'
        CHECK (json_valid(default_hierarchy_levels)),
    
    -- JSON: Weight validation rules
    -- {
    --   "autonomous_weight_balancing": true,
    --   "allow_absolute_weight_editing": false,
    --   "precision_decimal_places": 1,
    --   "require_exact_100": true,
    --   "balancing_algorithm": "proportional"
    -- }
    weight_validation_rules TEXT NOT NULL DEFAULT '{
        "autonomous_weight_balancing": true,
        "allow_absolute_weight_editing": false,
        "precision_decimal_places": 1,
        "require_exact_100": true,
        "balancing_algorithm": "proportional"
    }' CHECK (json_valid(weight_validation_rules)),
    
    notes TEXT,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Unique exam name per user
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_exam_name_per_user 
    ON exam_contexts (user_id, exam_name);

-- Index for active exams (commonly queried)
CREATE INDEX IF NOT EXISTS idx_active_exams 
    ON exam_contexts (user_id, is_active) 
    WHERE is_active = TRUE;

-- Index for exam date ordering
CREATE INDEX IF NOT EXISTS idx_exam_contexts_date 
    ON exam_contexts (exam_date);

-- ==============================================================================
-- TABLE P2.2: hierarchy_level_definitions
-- Custom hierarchy level names and configuration per exam context
-- ==============================================================================
CREATE TABLE IF NOT EXISTS hierarchy_level_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_context_id INTEGER NOT NULL 
        REFERENCES exam_contexts(id) ON DELETE CASCADE,
    level_name VARCHAR(100) NOT NULL,
    level_order INTEGER NOT NULL CHECK (level_order >= 1),
    
    -- First 3 levels are always required
    is_required BOOLEAN DEFAULT FALSE,
    
    -- Template for custom level display (e.g., "Daughter of {parent_name}")
    display_name_template VARCHAR(255),
    
    -- Distinguishes built-in levels (1-5) from user-added custom levels
    is_custom_level BOOLEAN DEFAULT FALSE,
    
    -- Metadata
    created_date DATE DEFAULT (date('now')),
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Unique level order per exam context
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_level_per_exam 
    ON hierarchy_level_definitions (exam_context_id, level_order);

-- Index for ordered retrieval
CREATE INDEX IF NOT EXISTS idx_exam_levels_ordered 
    ON hierarchy_level_definitions (exam_context_id, level_order);

-- Index for custom level lookup
CREATE INDEX IF NOT EXISTS idx_custom_levels 
    ON hierarchy_level_definitions (exam_context_id, is_custom_level)
    WHERE is_custom_level = TRUE;

-- ==============================================================================
-- TABLE P2.3: subject_node_weights
-- Complete audit trail of weight changes for undo/history
-- ==============================================================================
CREATE TABLE IF NOT EXISTS subject_node_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_node_id INTEGER NOT NULL 
        REFERENCES subject_nodes(id) ON DELETE CASCADE,
    
    -- Weight information
    weight_value DECIMAL(6,3) NOT NULL CHECK (weight_value >= 0 AND weight_value <= 100),
    edited_date DATE NOT NULL DEFAULT (date('now')),
    
    -- Who/what made this change
    edited_by TEXT NOT NULL DEFAULT 'user' 
        CHECK (edited_by IN ('user', 'system', 'import', 'migration')),
    edited_reason TEXT,
    
    -- Previous weight for undo capability
    previous_weight DECIMAL(6,3),
    
    -- Type of change for analytics
    change_type TEXT NOT NULL DEFAULT 'initial'
        CHECK (change_type IN (
            'initial',           -- First weight assignment
            'manual_edit',       -- User manually edited this node's weight
            'auto_recalculate',  -- System adjusted due to sibling change
            'parent_redistribution', -- Weight redistributed due to parent change
            'import',            -- Imported from external source
            'bulk_update'        -- Part of a bulk operation
        )),
    
    -- JSON: IDs of sibling nodes affected by this change
    affected_siblings TEXT DEFAULT '[]' CHECK (json_valid(affected_siblings)),
    
    -- User-provided notes
    user_notes TEXT,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for weight history by node
CREATE INDEX IF NOT EXISTS idx_weight_history_by_node 
    ON subject_node_weights (subject_node_id, edited_date DESC);

-- Index for changes by date (for analytics)
CREATE INDEX IF NOT EXISTS idx_weight_changes_by_date 
    ON subject_node_weights (edited_date DESC);

-- Index for change type analysis
CREATE INDEX IF NOT EXISTS idx_weight_changes_by_type 
    ON subject_node_weights (change_type, edited_date DESC);

-- Index for user-initiated changes
CREATE INDEX IF NOT EXISTS idx_user_weight_changes 
    ON subject_node_weights (edited_by, edited_date DESC)
    WHERE edited_by = 'user';

-- ==============================================================================
-- TRIGGERS: Auto-update timestamps
-- ==============================================================================

-- exam_contexts timestamp trigger
CREATE TRIGGER IF NOT EXISTS tr_exam_contexts_updated_at
    AFTER UPDATE ON exam_contexts
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE exam_contexts 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;

-- hierarchy_level_definitions timestamp trigger
CREATE TRIGGER IF NOT EXISTS tr_hierarchy_levels_updated_at
    AFTER UPDATE ON hierarchy_level_definitions
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE hierarchy_level_definitions 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;

-- ==============================================================================
-- VIEWS: Convenient data access
-- ==============================================================================

-- View: Active exam contexts with level counts
CREATE VIEW IF NOT EXISTS v_active_exam_contexts AS
SELECT 
    ec.id,
    ec.user_id,
    ec.exam_name,
    ec.exam_description,
    ec.exam_date,
    ec.is_active,
    ec.weight_validation_rules,
    ec.created_at,
    ec.updated_at,
    COUNT(hld.id) as level_count,
    SUM(CASE WHEN hld.is_custom_level THEN 1 ELSE 0 END) as custom_level_count
FROM exam_contexts ec
LEFT JOIN hierarchy_level_definitions hld ON ec.id = hld.exam_context_id
WHERE ec.is_active = TRUE
GROUP BY ec.id;

-- View: Weight change summary by node
CREATE VIEW IF NOT EXISTS v_weight_change_summary AS
SELECT 
    snw.subject_node_id,
    sn.name as subject_name,
    sn.exam_context,
    COUNT(*) as change_count,
    MIN(snw.edited_date) as first_change_date,
    MAX(snw.edited_date) as last_change_date,
    SUM(CASE WHEN snw.change_type = 'manual_edit' THEN 1 ELSE 0 END) as manual_edits,
    SUM(CASE WHEN snw.change_type = 'auto_recalculate' THEN 1 ELSE 0 END) as auto_adjustments
FROM subject_node_weights snw
JOIN subject_nodes sn ON snw.subject_node_id = sn.id
GROUP BY snw.subject_node_id;
