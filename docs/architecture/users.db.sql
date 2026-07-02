BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS "app_settings" (
	"id"	INTEGER,
	"setting_key"	VARCHAR(100) NOT NULL UNIQUE,
	"setting_value"	TEXT,
	"setting_type"	TEXT NOT NULL CHECK("setting_type" IN ('string', 'integer', 'boolean', 'json')),
	"description"	TEXT,
	"is_system_setting"	BOOLEAN DEFAULT FALSE,
	"requires_admin"	BOOLEAN DEFAULT FALSE,
	"updated_by_user_id"	INTEGER,
	"updated_at"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY("id" AUTOINCREMENT),
	FOREIGN KEY("updated_by_user_id") REFERENCES "users"("id")
);
CREATE TABLE IF NOT EXISTS "calendar_permission_requests" (
	"id"	INTEGER,
	"requesting_user_id"	INTEGER NOT NULL,
	"target_user_id"	INTEGER NOT NULL,
	"requested_permissions"	TEXT CHECK(json_valid("requested_permissions")),
	"request_message"	TEXT,
	"request_status"	TEXT CHECK("request_status" IN ('pending', 'approved', 'rejected', 'expired')),
	"exam_contexts"	TEXT CHECK(json_valid("exam_contexts")),
	"requested_at"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"responded_at"	TIMESTAMP,
	"response_message"	TEXT,
	"expires_at"	TIMESTAMP,
	PRIMARY KEY("id" AUTOINCREMENT),
	FOREIGN KEY("requesting_user_id") REFERENCES "users"("id"),
	FOREIGN KEY("target_user_id") REFERENCES "users"("id")
);
CREATE TABLE IF NOT EXISTS "calendar_sharing" (
	"id"	INTEGER,
	"calendar_owner_id"	INTEGER NOT NULL,
	"shared_with_user_id"	INTEGER NOT NULL,
	"exam_context"	VARCHAR(100),
	"sharing_permissions"	TEXT CHECK(json_valid("sharing_permissions")),
	"sharing_type"	TEXT CHECK("sharing_type" IN ('power_user_access', 'peer_sharing', 'collaborative', 'tutor_management')),
	"can_view_completed_events"	BOOLEAN DEFAULT TRUE,
	"can_view_private_events"	BOOLEAN DEFAULT FALSE,
	"can_suggest_events"	BOOLEAN DEFAULT FALSE,
	"can_create_events"	BOOLEAN DEFAULT FALSE,
	"can_edit_events"	BOOLEAN DEFAULT FALSE,
	"can_view_analytics"	BOOLEAN DEFAULT FALSE,
	"create_permission_requested"	BOOLEAN DEFAULT FALSE,
	"create_permission_granted"	BOOLEAN DEFAULT FALSE,
	"edit_permission_requested"	BOOLEAN DEFAULT FALSE,
	"edit_permission_granted"	BOOLEAN DEFAULT FALSE,
	"permission_request_message"	TEXT,
	"permission_response_message"	TEXT,
	"permissions_last_updated"	TIMESTAMP,
	"shared_at"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"is_active"	BOOLEAN DEFAULT TRUE,
	"sharing_notes"	TEXT,
	PRIMARY KEY("id" AUTOINCREMENT),
	FOREIGN KEY("calendar_owner_id") REFERENCES "users"("id") ON DELETE CASCADE,
	FOREIGN KEY("shared_with_user_id") REFERENCES "users"("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "cross_user_notifications" (
	"id"	INTEGER,
	"notification_type"	TEXT NOT NULL CHECK("notification_type" IN ('permission_request', 'permission_granted', 'permission_revoked', 'calendar_share_invite', 'calendar_event_suggestion', 'power_user_message', 'goal_milestone_shared', 'study_reminder_shared', 'system_announcement')),
	"sender_user_id"	INTEGER,
	"recipient_user_id"	INTEGER NOT NULL,
	"title"	VARCHAR(255) NOT NULL,
	"message"	TEXT,
	"action_required"	BOOLEAN DEFAULT FALSE,
	"action_type"	VARCHAR(50),
	"action_data"	TEXT CHECK(json_valid("action_data")),
	"priority"	TEXT DEFAULT 'medium' CHECK("priority" IN ('low', 'medium', 'high', 'urgent')),
	"is_read"	BOOLEAN DEFAULT FALSE,
	"is_archived"	BOOLEAN DEFAULT FALSE,
	"created_at"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"read_at"	TIMESTAMP,
	"archived_at"	TIMESTAMP,
	"expires_at"	TIMESTAMP,
	PRIMARY KEY("id" AUTOINCREMENT),
	FOREIGN KEY("recipient_user_id") REFERENCES "users"("id") ON DELETE CASCADE,
	FOREIGN KEY("sender_user_id") REFERENCES "users"("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "power_user_permission_requests" (
	"id"	INTEGER,
	"power_user_id"	INTEGER NOT NULL,
	"child_user_id"	INTEGER NOT NULL,
	"requested_permissions"	TEXT NOT NULL CHECK(json_valid("requested_permissions")),
	"request_message"	TEXT,
	"request_status"	TEXT NOT NULL DEFAULT 'pending' CHECK("request_status" IN ('pending', 'accepted', 'rejected', 'revocation_requested')),
	"requested_at"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"responded_at"	TIMESTAMP,
	"response_message"	TEXT,
	"revocation_requested_by"	TEXT CHECK("revocation_requested_by" IN ('child', 'power_user')),
	"revocation_requested_at"	TIMESTAMP,
	"revocation_reason"	TEXT,
	"both_parties_agree_revocation"	BOOLEAN DEFAULT FALSE,
	PRIMARY KEY("id" AUTOINCREMENT),
	FOREIGN KEY("child_user_id") REFERENCES "users"("id") ON DELETE CASCADE,
	FOREIGN KEY("power_user_id") REFERENCES "users"("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "power_user_relationships" (
	"id"	INTEGER,
	"power_user_id"	INTEGER NOT NULL,
	"child_user_id"	INTEGER NOT NULL,
	"relationship_status"	TEXT NOT NULL DEFAULT 'pending' CHECK("relationship_status" IN ('pending', 'active', 'revocation_requested', 'terminated')),
	"permissions_granted"	TEXT NOT NULL CHECK(json_valid("permissions_granted")),
	"relationship_label"	VARCHAR(100),
	"established_at"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"last_interaction_at"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"revocation_requested_by"	TEXT CHECK("revocation_requested_by" IN ('power_user', 'child')),
	"revocation_requested_at"	TIMESTAMP,
	"both_parties_agree_revocation"	BOOLEAN DEFAULT FALSE,
	"is_active"	BOOLEAN DEFAULT TRUE,
	PRIMARY KEY("id" AUTOINCREMENT),
	FOREIGN KEY("child_user_id") REFERENCES "users"("id") ON DELETE CASCADE,
	FOREIGN KEY("power_user_id") REFERENCES "users"("id") ON DELETE CASCADE,
	CHECK("power_user_id" != "child_user_id")
);
CREATE TABLE IF NOT EXISTS "table_backups" (
	"id"	INTEGER,
	"table_name"	VARCHAR(100) NOT NULL,
	"backup_timestamp"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"backup_file_path"	VARCHAR(255) NOT NULL,
	"backup_size_bytes"	INTEGER,
	"backup_type"	TEXT CHECK("backup_type" IN ('full', 'incremental', 'schema_only')),
	"created_by_user_id"	INTEGER,
	"restore_tested"	BOOLEAN DEFAULT FALSE,
	"notes"	TEXT,
	PRIMARY KEY("id" AUTOINCREMENT),
	FOREIGN KEY("created_by_user_id") REFERENCES "users"("id")
);
CREATE TABLE IF NOT EXISTS "user_database_schemas" (
	"id"	INTEGER,
	"user_id"	INTEGER NOT NULL,
	"database_filename"	VARCHAR(255) NOT NULL,
	"current_schema_version"	VARCHAR(20) NOT NULL,
	"last_migration_applied"	VARCHAR(50),
	"migration_history"	TEXT CHECK(json_valid("migration_history")),
	"needs_migration"	BOOLEAN DEFAULT FALSE,
	"migration_backup_created"	BOOLEAN DEFAULT FALSE,
	"last_migration_check"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"created_at"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY("id" AUTOINCREMENT),
	FOREIGN KEY("user_id") REFERENCES "users"("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "users" (
	"id"	INTEGER,
	"username"	VARCHAR(100) NOT NULL UNIQUE,
	"display_name"	VARCHAR(255) NOT NULL,
	"email"	VARCHAR(255) UNIQUE,
	"user_type"	TEXT NOT NULL CHECK(json_valid("user_type")),
	"database_filename"	VARCHAR(255) NOT NULL UNIQUE,
	"profile_image_path"	VARCHAR(500),
	"account_status"	TEXT NOT NULL DEFAULT 'active' CHECK("account_status" IN ('active', 'suspended', 'disabled', 'soft_deleted')),
	"is_primary_admin"	BOOLEAN DEFAULT FALSE,
	"cloud_sync_enabled"	BOOLEAN DEFAULT FALSE,
	"cloud_user_id"	VARCHAR(100),
	"last_active_at"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"created_at"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"soft_deleted_at"	TIMESTAMP,
	"deletion_confirmed"	BOOLEAN DEFAULT FALSE,
	"registered_devices"	TEXT CHECK(json_valid("registered_devices")),
	"notification_tokens"	TEXT CHECK(json_valid("notification_tokens")),
	"database_encryption_enabled"	BOOLEAN DEFAULT FALSE,
	"can_manage_users"	BOOLEAN DEFAULT FALSE,
	"can_view_all_statistics"	BOOLEAN DEFAULT FALSE,
	"can_export_all_data"	BOOLEAN DEFAULT FALSE,
	"can_manage_app_settings"	BOOLEAN DEFAULT FALSE,
	"current_schema_version"	VARCHAR(20) DEFAULT '1.0.0',
	"last_schema_check"	TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	"schema_migration_history"	TEXT CHECK(json_valid("schema_migration_history")),
	PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE INDEX IF NOT EXISTS "idx_notifications_recipient" ON "cross_user_notifications" (
	"recipient_user_id",
	"is_read",
	"created_at"
);
CREATE INDEX IF NOT EXISTS "idx_notifications_unread" ON "cross_user_notifications" (
	"recipient_user_id",
	"is_read"
) WHERE "is_read" = FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS "idx_single_primary_admin" ON "users" (
	"is_primary_admin"
) WHERE "is_primary_admin" = TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS "idx_unique_power_user_relationship" ON "power_user_relationships" (
	"power_user_id",
	"child_user_id"
);
CREATE INDEX IF NOT EXISTS "idx_users_active" ON "users" (
	"account_status",
	"last_active_at"
) WHERE "account_status" = 'active';
CREATE INDEX IF NOT EXISTS "idx_users_cloud_sync" ON "users" (
	"cloud_sync_enabled",
	"cloud_user_id"
) WHERE "cloud_sync_enabled" = TRUE;
COMMIT;
