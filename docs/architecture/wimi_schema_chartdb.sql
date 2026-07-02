-- WIMI Database Schema for ChartDB (PostgreSQL dialect)

-- ========================
-- MASTER DATABASE: users.db
-- ========================

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    user_type TEXT NOT NULL,
    database_filename VARCHAR(255) UNIQUE NOT NULL,
    profile_image_path VARCHAR(500),
    account_status TEXT NOT NULL DEFAULT 'active',
    is_primary_admin INTEGER DEFAULT 0,
    cloud_sync_enabled INTEGER DEFAULT 0,
    cloud_user_id VARCHAR(100),
    last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    soft_deleted_at TIMESTAMP,
    deletion_confirmed INTEGER DEFAULT 0,
    registered_devices TEXT,
    notification_tokens TEXT,
    database_encryption_enabled INTEGER DEFAULT 0,
    can_manage_users INTEGER DEFAULT 0,
    can_view_all_statistics INTEGER DEFAULT 0,
    can_export_all_data INTEGER DEFAULT 0,
    can_manage_app_settings INTEGER DEFAULT 0,
    current_schema_version VARCHAR(20) DEFAULT '1.0.0',
    last_schema_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    schema_migration_history TEXT
);

CREATE TABLE power_user_relationships (
    id SERIAL PRIMARY KEY,
    power_user_id INTEGER NOT NULL REFERENCES users(id),
    child_user_id INTEGER NOT NULL REFERENCES users(id),
    relationship_status TEXT NOT NULL DEFAULT 'pending',
    permissions_granted TEXT NOT NULL,
    relationship_label VARCHAR(100),
    established_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_interaction_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revocation_requested_by TEXT,
    revocation_requested_at TIMESTAMP,
    both_parties_agree_revocation INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE power_user_permission_requests (
    id SERIAL PRIMARY KEY,
    power_user_id INTEGER NOT NULL REFERENCES users(id),
    child_user_id INTEGER NOT NULL REFERENCES users(id),
    requested_permissions TEXT NOT NULL,
    request_message TEXT,
    request_status TEXT NOT NULL DEFAULT 'pending',
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP,
    response_message TEXT,
    revocation_requested_by TEXT,
    revocation_requested_at TIMESTAMP,
    revocation_reason TEXT,
    both_parties_agree_revocation INTEGER DEFAULT 0
);

CREATE TABLE app_settings (
    id SERIAL PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value TEXT,
    setting_type TEXT NOT NULL,
    description TEXT,
    is_system_setting INTEGER DEFAULT 0,
    requires_admin INTEGER DEFAULT 0,
    updated_by_user_id INTEGER REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_database_schemas (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    database_filename VARCHAR(255) NOT NULL,
    current_schema_version VARCHAR(20) NOT NULL,
    last_migration_applied VARCHAR(50),
    migration_history TEXT,
    needs_migration INTEGER DEFAULT 0,
    migration_backup_created INTEGER DEFAULT 0,
    last_migration_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE calendar_sharing (
    id SERIAL PRIMARY KEY,
    calendar_owner_id INTEGER NOT NULL REFERENCES users(id),
    shared_with_user_id INTEGER NOT NULL REFERENCES users(id),
    exam_context VARCHAR(100),
    sharing_permissions TEXT,
    sharing_type TEXT,
    can_view_completed_events INTEGER DEFAULT 1,
    can_view_private_events INTEGER DEFAULT 0,
    can_suggest_events INTEGER DEFAULT 0,
    can_create_events INTEGER DEFAULT 0,
    can_edit_events INTEGER DEFAULT 0,
    can_view_analytics INTEGER DEFAULT 0,
    create_permission_requested INTEGER DEFAULT 0,
    create_permission_granted INTEGER DEFAULT 0,
    edit_permission_requested INTEGER DEFAULT 0,
    edit_permission_granted INTEGER DEFAULT 0,
    permission_request_message TEXT,
    permission_response_message TEXT,
    permissions_last_updated TIMESTAMP,
    shared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    sharing_notes TEXT
);

CREATE TABLE calendar_permission_requests (
    id SERIAL PRIMARY KEY,
    requesting_user_id INTEGER NOT NULL REFERENCES users(id),
    target_user_id INTEGER NOT NULL REFERENCES users(id),
    requested_permissions TEXT,
    request_message TEXT,
    request_status TEXT,
    exam_contexts TEXT,
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP,
    response_message TEXT,
    expires_at TIMESTAMP
);

CREATE TABLE table_backups (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    backup_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    backup_file_path VARCHAR(255) NOT NULL,
    backup_size_bytes INTEGER,
    backup_type TEXT,
    created_by_user_id INTEGER REFERENCES users(id),
    restore_tested INTEGER DEFAULT 0,
    notes TEXT
);

CREATE TABLE cross_user_notifications (
    id SERIAL PRIMARY KEY,
    notification_type TEXT NOT NULL,
    sender_user_id INTEGER REFERENCES users(id),
    recipient_user_id INTEGER NOT NULL REFERENCES users(id),
    title VARCHAR(255) NOT NULL,
    message TEXT,
    action_required INTEGER DEFAULT 0,
    action_type VARCHAR(50),
    action_data TEXT,
    priority TEXT DEFAULT 'medium',
    is_read INTEGER DEFAULT 0,
    is_archived INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP,
    archived_at TIMESTAMP,
    expires_at TIMESTAMP
);

-- ============================
-- USER DATABASE: user_XXX.db
-- ============================

CREATE TABLE user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    theme_name VARCHAR(50) DEFAULT 'default',
    language_code VARCHAR(10) DEFAULT 'en',
    font_size_scale REAL DEFAULT 1.0,
    show_animations INTEGER DEFAULT 1,
    default_session_duration_minutes INTEGER DEFAULT 60,
    default_break_interval_minutes INTEGER DEFAULT 25,
    default_long_break_minutes INTEGER DEFAULT 15,
    long_break_interval_rounds INTEGER DEFAULT 4,
    timer_display_size TEXT DEFAULT 'normal',
    hotkey_timer_pause_resume TEXT DEFAULT 'Alt+P',
    hotkey_timer_new_round TEXT DEFAULT 'Alt+N',
    hotkey_timer_end_round TEXT DEFAULT 'Alt+E',
    dashboard_auto_refresh_seconds INTEGER DEFAULT 300,
    show_progress_graphs INTEGER DEFAULT 1,
    show_mistake_heatmap INTEGER DEFAULT 1,
    calendar_time_slot_minutes INTEGER DEFAULT 30,
    calendar_default_view VARCHAR(20) DEFAULT 'week',
    child_subject_weight_inheritance_fraction REAL DEFAULT 1.0,
    entry_review_items_per_page INTEGER DEFAULT 25,
    entry_review_default_sort VARCHAR(50) DEFAULT 'date_desc',
    ankiconnect_enabled INTEGER DEFAULT 0,
    ankiconnect_host VARCHAR(255) DEFAULT 'localhost',
    ankiconnect_port INTEGER DEFAULT 8765,
    anki_cache_refresh_interval_minutes INTEGER DEFAULT 60,
    backup_frequency_hours INTEGER DEFAULT 24,
    backup_retention_days INTEGER DEFAULT 30,
    realtime_update_delay_ms INTEGER DEFAULT 500,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE exam_contexts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    exam_name VARCHAR(255) NOT NULL,
    exam_description TEXT,
    exam_date DATE,
    created_date DATE,
    is_active INTEGER DEFAULT 1,
    default_hierarchy_levels TEXT,
    weight_validation_rules TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE exam_dimensions (
    id SERIAL PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exam_contexts(id),
    name TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    is_required INTEGER DEFAULT 1,
    allow_multiple INTEGER DEFAULT 0,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE subject_nodes (
    id SERIAL PRIMARY KEY,
    exam_context VARCHAR(50) NOT NULL,
    parent_id INTEGER REFERENCES subject_nodes(id),
    name VARCHAR(255) NOT NULL,
    level_type VARCHAR(50) NOT NULL,
    sort_order INTEGER DEFAULT 1,
    exam_weight_low REAL,
    exam_weight_high REAL,
    exam_source VARCHAR(255),
    relative_weight REAL,
    weight_source VARCHAR(50) DEFAULT 'user_defined',
    weight_locked INTEGER DEFAULT 0,
    outline_type VARCHAR(50) DEFAULT 'content',
    status VARCHAR(20) DEFAULT 'active',
    dimension_id INTEGER REFERENCES exam_dimensions(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE hierarchy_level_definitions (
    id SERIAL PRIMARY KEY,
    exam_context_id INTEGER NOT NULL REFERENCES exam_contexts(id),
    level_name VARCHAR(100) NOT NULL,
    level_order INTEGER NOT NULL,
    is_required INTEGER DEFAULT 0,
    display_name_template VARCHAR(255),
    is_custom_level INTEGER DEFAULT 0,
    created_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE subject_node_weights (
    id SERIAL PRIMARY KEY,
    subject_node_id INTEGER NOT NULL REFERENCES subject_nodes(id),
    weight_value REAL NOT NULL,
    edited_date DATE,
    edited_by TEXT NOT NULL DEFAULT 'user',
    edited_reason TEXT,
    previous_weight REAL,
    change_type TEXT NOT NULL DEFAULT 'initial',
    affected_siblings TEXT DEFAULT '[]',
    user_notes TEXT,
    relative_weight_value REAL,
    weight_type VARCHAR(20) DEFAULT 'absolute',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE subject_aliases (
    id SERIAL PRIMARY KEY,
    subject_node_id INTEGER NOT NULL REFERENCES subject_nodes(id),
    exam_context VARCHAR(50) NOT NULL,
    alias_name VARCHAR(255) NOT NULL,
    alias_type VARCHAR(50) NOT NULL DEFAULT 'alternate_name',
    is_primary INTEGER DEFAULT 0,
    usage_count INTEGER DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE question_sources (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    source_name VARCHAR(255) NOT NULL,
    source_type TEXT DEFAULT 'other',
    exam_context VARCHAR(100),
    description TEXT,
    url VARCHAR(500),
    total_questions INTEGER,
    user_rating INTEGER,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE review_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    exam_context_id INTEGER NOT NULL REFERENCES exam_contexts(id),
    question_source_id INTEGER REFERENCES question_sources(id),
    session_name VARCHAR(255),
    date_encountered DATE,
    total_questions INTEGER NOT NULL,
    total_incorrect INTEGER NOT NULL,
    entries_completed INTEGER DEFAULT 0,
    session_status TEXT DEFAULT 'in_progress',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE session_timer_rounds (
    id SERIAL PRIMARY KEY,
    review_session_id INTEGER NOT NULL REFERENCES review_sessions(id),
    round_number INTEGER NOT NULL,
    duration_minutes INTEGER NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    actual_studied_seconds INTEGER DEFAULT 0,
    total_break_seconds INTEGER DEFAULT 0,
    timer_paused_at TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE question_entries (
    id SERIAL PRIMARY KEY,
    review_session_id INTEGER NOT NULL REFERENCES review_sessions(id),
    entry_order INTEGER NOT NULL,
    question_id VARCHAR(255),
    user_answer TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    perceived_difficulty INTEGER,
    time_spent_seconds INTEGER,
    reflection TEXT,
    explanation TEXT,
    notes TEXT,
    is_draft INTEGER DEFAULT 1,
    draft_missing_fields TEXT,
    explanation_json TEXT,
    reflection_json TEXT,
    notes_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE entry_subject_mappings (
    id SERIAL PRIMARY KEY,
    question_entry_id INTEGER NOT NULL REFERENCES question_entries(id),
    subject_node_id INTEGER NOT NULL REFERENCES subject_nodes(id),
    mapping_type TEXT DEFAULT 'primary',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    exam_context VARCHAR(50) NOT NULL,
    tag_name VARCHAR(100) NOT NULL,
    tag_category VARCHAR(50) DEFAULT 'other',
    color_hex VARCHAR(7) DEFAULT '#2196F3',
    description TEXT,
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE entry_tags (
    id SERIAL PRIMARY KEY,
    question_entry_id INTEGER NOT NULL REFERENCES question_entries(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE entry_media (
    id SERIAL PRIMARY KEY,
    question_entry_id INTEGER NOT NULL REFERENCES question_entries(id),
    file_uuid VARCHAR(36) NOT NULL,
    original_filename VARCHAR(255),
    user_filename VARCHAR(255),
    mime_type VARCHAR(100),
    file_size_bytes INTEGER,
    sort_order INTEGER DEFAULT 0,
    linked_subject_ids TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE entry_notes (
    id SERIAL PRIMARY KEY,
    question_entry_id INTEGER NOT NULL REFERENCES question_entries(id),
    content_html TEXT,
    content_json TEXT,
    sort_order INTEGER DEFAULT 0,
    linked_subject_ids TEXT,
    is_migrated INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE question_hierarchy_tags (
    id SERIAL PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES question_entries(id),
    hierarchy_id INTEGER NOT NULL REFERENCES subject_nodes(id),
    dimension_id INTEGER NOT NULL REFERENCES exam_dimensions(id),
    tagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE question_analyses (
    id SERIAL PRIMARY KEY,
    exam_context VARCHAR(50) NOT NULL,
    question_source VARCHAR(255) NOT NULL,
    question_source_id VARCHAR(255) NOT NULL,
    answered_incorrectly_date DATE NOT NULL,
    user_selected_answer VARCHAR(10),
    correct_answer VARCHAR(10),
    perceived_difficulty INTEGER,
    metacognitive_reflection TEXT,
    question_explanation TEXT,
    user_notes TEXT,
    time_spent_on_question INTEGER,
    confidence_before_answer INTEGER,
    mistake_category VARCHAR(50),
    review_status VARCHAR(50) DEFAULT 'pending_review',
    last_reviewed_at TIMESTAMP,
    times_reviewed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE question_tags (
    id SERIAL PRIMARY KEY,
    question_analysis_id INTEGER NOT NULL REFERENCES question_analyses(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    exam_context VARCHAR(50) NOT NULL,
    assigned_by VARCHAR(20) DEFAULT 'user',
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE question_topic_assignments (
    id SERIAL PRIMARY KEY,
    question_analysis_id INTEGER NOT NULL REFERENCES question_analyses(id),
    subject_node_id INTEGER NOT NULL REFERENCES subject_nodes(id),
    exam_context VARCHAR(50) NOT NULL,
    assignment_type VARCHAR(20) DEFAULT 'primary',
    assigned_by VARCHAR(20) DEFAULT 'user',
    confidence_score REAL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_goals (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    goal_type TEXT NOT NULL DEFAULT 'weekly_entries',
    target_value INTEGER NOT NULL,
    exam_context_id INTEGER REFERENCES exam_contexts(id),
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE goal_periods (
    id SERIAL PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES user_goals(id),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    target_value INTEGER NOT NULL,
    achieved_value INTEGER DEFAULT 0,
    is_complete INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE reflection_themes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    exam_context_id INTEGER REFERENCES exam_contexts(id),
    theme TEXT NOT NULL,
    theme_type TEXT DEFAULT 'general',
    frequency INTEGER DEFAULT 0,
    sample_entry_ids TEXT,
    related_tag_ids TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE import_mapping_profiles (
    id SERIAL PRIMARY KEY,
    profile_name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'custom',
    field_mappings TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE plugin_data (
    id SERIAL PRIMARY KEY,
    plugin_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE saved_delimiters (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    hotkey TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE schema_version (
    id SERIAL PRIMARY KEY,
    version VARCHAR(20) NOT NULL,
    description TEXT NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    migration_metadata TEXT
);
