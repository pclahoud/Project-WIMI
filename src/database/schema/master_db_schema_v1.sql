-- Master Database Schema v1.0.0
-- Contains user registry and cross-user relationships

-- ======================
-- TABLE 1: users
-- ======================
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    user_type TEXT NOT NULL CHECK (json_valid(user_type)), -- JSON: ["student", "power_user", "admin"]
    database_filename VARCHAR(255) UNIQUE NOT NULL, -- "user_001_john.db"
    profile_image_path VARCHAR(500),
    account_status TEXT NOT NULL DEFAULT 'active' CHECK (account_status IN ('active', 'suspended', 'disabled', 'soft_deleted')),
    is_primary_admin BOOLEAN DEFAULT FALSE,
    cloud_sync_enabled BOOLEAN DEFAULT FALSE,
    cloud_user_id VARCHAR(100) NULL,
    last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    soft_deleted_at TIMESTAMP NULL,
    deletion_confirmed BOOLEAN DEFAULT FALSE,
    registered_devices TEXT CHECK (json_valid(registered_devices)),
    notification_tokens TEXT CHECK (json_valid(notification_tokens)),
    database_encryption_enabled BOOLEAN DEFAULT FALSE,
    can_manage_users BOOLEAN DEFAULT FALSE,
    can_view_all_statistics BOOLEAN DEFAULT FALSE,
    can_export_all_data BOOLEAN DEFAULT FALSE,
    can_manage_app_settings BOOLEAN DEFAULT FALSE,
    current_schema_version VARCHAR(20) DEFAULT '1.0.0',
    last_schema_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    schema_migration_history TEXT CHECK (json_valid(schema_migration_history))
);

CREATE UNIQUE INDEX idx_single_primary_admin ON users (is_primary_admin) WHERE is_primary_admin = TRUE;
CREATE INDEX idx_users_active ON users (account_status, last_active_at) WHERE account_status = 'active';
CREATE INDEX idx_users_cloud_sync ON users (cloud_sync_enabled, cloud_user_id) WHERE cloud_sync_enabled = TRUE;

-- ======================
-- TABLE 2: power_user_relationships
-- ======================
CREATE TABLE IF NOT EXISTS power_user_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    power_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    child_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    relationship_status TEXT NOT NULL DEFAULT 'pending' CHECK (relationship_status IN ('pending', 'active', 'revocation_requested', 'terminated')),
    permissions_granted TEXT NOT NULL CHECK (json_valid(permissions_granted)), -- JSON array
    relationship_label VARCHAR(100), -- "Math Tutor", "Parent"
    established_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_interaction_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revocation_requested_by TEXT CHECK (revocation_requested_by IN ('power_user', 'child')),
    revocation_requested_at TIMESTAMP NULL,
    both_parties_agree_revocation BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    CHECK (power_user_id != child_user_id)
);

CREATE UNIQUE INDEX idx_unique_power_user_relationship ON power_user_relationships (power_user_id, child_user_id);

-- ======================
-- TABLE 3: power_user_permission_requests
-- ======================
CREATE TABLE IF NOT EXISTS power_user_permission_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    power_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    child_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requested_permissions TEXT NOT NULL CHECK (json_valid(requested_permissions)), -- JSON array
    request_message TEXT,
    request_status TEXT NOT NULL DEFAULT 'pending' CHECK (request_status IN ('pending', 'accepted', 'rejected', 'revocation_requested')),
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP NULL,
    response_message TEXT,
    revocation_requested_by TEXT CHECK (revocation_requested_by IN ('child', 'power_user')),
    revocation_requested_at TIMESTAMP NULL,
    revocation_reason TEXT,
    both_parties_agree_revocation BOOLEAN DEFAULT FALSE
);

-- ======================
-- TABLE 4: app_settings
-- ======================
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value TEXT,
    setting_type TEXT NOT NULL CHECK (setting_type IN ('string', 'integer', 'boolean', 'json')),
    description TEXT,
    is_system_setting BOOLEAN DEFAULT FALSE,
    requires_admin BOOLEAN DEFAULT FALSE,
    updated_by_user_id INTEGER REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ======================
-- TABLE 5: user_database_schemas
-- ======================
CREATE TABLE IF NOT EXISTS user_database_schemas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    database_filename VARCHAR(255) NOT NULL,
    current_schema_version VARCHAR(20) NOT NULL,
    last_migration_applied VARCHAR(50),
    migration_history TEXT CHECK (json_valid(migration_history)),
    needs_migration BOOLEAN DEFAULT FALSE,
    migration_backup_created BOOLEAN DEFAULT FALSE,
    last_migration_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ======================
-- TABLE 6: calendar_sharing
-- ======================
CREATE TABLE IF NOT EXISTS calendar_sharing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calendar_owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shared_with_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exam_context VARCHAR(100),
    sharing_permissions TEXT CHECK (json_valid(sharing_permissions)), -- JSON array
    sharing_type TEXT CHECK (sharing_type IN ('power_user_access', 'peer_sharing', 'collaborative', 'tutor_management')),
    can_view_completed_events BOOLEAN DEFAULT TRUE,
    can_view_private_events BOOLEAN DEFAULT FALSE,
    can_suggest_events BOOLEAN DEFAULT FALSE,
    can_create_events BOOLEAN DEFAULT FALSE,
    can_edit_events BOOLEAN DEFAULT FALSE,
    can_view_analytics BOOLEAN DEFAULT FALSE,
    create_permission_requested BOOLEAN DEFAULT FALSE,
    create_permission_granted BOOLEAN DEFAULT FALSE,
    edit_permission_requested BOOLEAN DEFAULT FALSE,
    edit_permission_granted BOOLEAN DEFAULT FALSE,
    permission_request_message TEXT,
    permission_response_message TEXT,
    permissions_last_updated TIMESTAMP,
    shared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    sharing_notes TEXT
);

-- ======================
-- TABLE 7: calendar_permission_requests
-- ======================
CREATE TABLE IF NOT EXISTS calendar_permission_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requesting_user_id INTEGER NOT NULL REFERENCES users(id),
    target_user_id INTEGER NOT NULL REFERENCES users(id),
    requested_permissions TEXT CHECK (json_valid(requested_permissions)),
    request_message TEXT,
    request_status TEXT CHECK (request_status IN ('pending', 'approved', 'rejected', 'expired')),
    exam_contexts TEXT CHECK (json_valid(exam_contexts)),
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP NULL,
    response_message TEXT,
    expires_at TIMESTAMP
);

-- ======================
-- TABLE 8: table_backups
-- ======================
CREATE TABLE IF NOT EXISTS table_backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name VARCHAR(100) NOT NULL,
    backup_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    backup_file_path VARCHAR(255) NOT NULL,
    backup_size_bytes INTEGER,
    backup_type TEXT CHECK (backup_type IN ('full', 'incremental', 'schema_only')),
    created_by_user_id INTEGER REFERENCES users(id),
    restore_tested BOOLEAN DEFAULT FALSE,
    notes TEXT
);

-- ======================
-- TABLE 9: cross_user_notifications
-- ======================
CREATE TABLE IF NOT EXISTS cross_user_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_type TEXT NOT NULL CHECK (notification_type IN (
        'permission_request', 'permission_granted', 'permission_revoked',
        'calendar_share_invite', 'calendar_event_suggestion', 'power_user_message',
        'goal_milestone_shared', 'study_reminder_shared', 'system_announcement'
    )),
    sender_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    recipient_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    message TEXT,
    action_required BOOLEAN DEFAULT FALSE,
    action_type VARCHAR(50), -- 'approve_permission', 'accept_invite', etc.
    action_data TEXT CHECK (json_valid(action_data)),
    priority TEXT CHECK (priority IN ('low', 'medium', 'high', 'urgent')) DEFAULT 'medium',
    is_read BOOLEAN DEFAULT FALSE,
    is_archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP NULL,
    archived_at TIMESTAMP NULL,
    expires_at TIMESTAMP NULL
);

CREATE INDEX idx_notifications_recipient ON cross_user_notifications (recipient_user_id, is_read, created_at);
CREATE INDEX idx_notifications_unread ON cross_user_notifications (recipient_user_id, is_read) WHERE is_read = FALSE;
