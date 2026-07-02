# Database Architecture Overview

This application uses a **multi-database architecture**:
- **Master Database (`users.db`)**: User registry and cross-user relationships
- **Individual User Databases (`user_XXX_username.db`)**: Isolated per-user data

---

## MASTER DATABASE TABLES (users.db)

### 1. users

**Purpose**: User account management and profile information

```sql
users
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── username (VARCHAR(100) UNIQUE NOT NULL)
├── display_name (VARCHAR(255) NOT NULL)
├── email (VARCHAR(255) UNIQUE)
├── user_type (TEXT NOT NULL CHECK (json_valid(user_type))) -- JSON: [\"student\", \"power_user\", \"admin\"]
├── database_filename (VARCHAR(255) UNIQUE NOT NULL) -- \"user_001_john.db\"
├── profile_image_path (VARCHAR(500))
├── account_status (TEXT NOT NULL DEFAULT 'active' CHECK (account_status IN ('active', 'suspended', 'disabled', 'soft_deleted')))
├── is_primary_admin (BOOLEAN DEFAULT FALSE)
├── cloud_sync_enabled (BOOLEAN DEFAULT FALSE)
├── cloud_user_id (VARCHAR(100) NULL)
├── last_active_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── soft_deleted_at (TIMESTAMP NULL)
├── deletion_confirmed (BOOLEAN DEFAULT FALSE)
├── registered_devices (TEXT CHECK (json_valid(registered_devices)))
├── notification_tokens (TEXT CHECK (json_valid(notification_tokens)))
├── database_encryption_enabled (BOOLEAN DEFAULT FALSE)
├── can_manage_users (BOOLEAN DEFAULT FALSE)
├── can_view_all_statistics (BOOLEAN DEFAULT FALSE)
├── can_export_all_data (BOOLEAN DEFAULT FALSE)
├── can_manage_app_settings (BOOLEAN DEFAULT FALSE)
├── current_schema_version (VARCHAR(20) DEFAULT '1.0.0')
├── last_schema_check (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── schema_migration_history (TEXT CHECK (json_valid(schema_migration_history)))

-- Constraints
CREATE UNIQUE INDEX idx_single_primary_admin ON users (is_primary_admin) WHERE is_primary_admin = TRUE;
CREATE INDEX idx_users_active ON users (account_status, last_active_at) WHERE account_status = 'active';
CREATE INDEX idx_users_cloud_sync ON users (cloud_sync_enabled, cloud_user_id) WHERE cloud_sync_enabled = TRUE;
```

---

### 2. power_user_relationships

**Purpose**: Track approved power user oversight relationships

```sql
power_user_relationships
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── power_user_id (INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE)
├── child_user_id (INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE)
├── relationship_status (TEXT NOT NULL DEFAULT 'pending' CHECK (relationship_status IN ('pending', 'active', 'revocation_requested', 'terminated')))
├── permissions_granted (TEXT NOT NULL CHECK (json_valid(permissions_granted))) -- JSON array
├── relationship_label (VARCHAR(100)) -- \"Math Tutor\", \"Parent\"
├── established_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── last_interaction_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── revocation_requested_by (TEXT CHECK (revocation_requested_by IN ('power_user', 'child')))
├── revocation_requested_at (TIMESTAMP NULL)
├── both_parties_agree_revocation (BOOLEAN DEFAULT FALSE)
└── is_active (BOOLEAN DEFAULT TRUE)

CREATE UNIQUE INDEX idx_unique_power_user_relationship ON power_user_relationships (power_user_id, child_user_id);
ALTER TABLE power_user_relationships ADD CONSTRAINT no_self_relationship CHECK (power_user_id != child_user_id);
```

---

### 3. power_user_permission_requests

**Purpose**: Handle permission requests from power users to child users

```sql
power_user_permission_requests
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── power_user_id (INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE)
├── child_user_id (INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE)
├── requested_permissions (TEXT NOT NULL CHECK (json_valid(requested_permissions))) -- JSON array
├── request_message (TEXT)
├── request_status (TEXT NOT NULL DEFAULT 'pending' CHECK (request_status IN ('pending', 'accepted', 'rejected', 'revocation_requested')))
├── requested_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── responded_at (TIMESTAMP NULL)
├── response_message (TEXT)
├── revocation_requested_by (TEXT CHECK (revocation_requested_by IN ('child', 'power_user')))
├── revocation_requested_at (TIMESTAMP NULL)
├── revocation_reason (TEXT)
└── both_parties_agree_revocation (BOOLEAN DEFAULT FALSE)
```

---

### 4. app_settings

**Purpose**: Application-level configuration settings

```sql
app_settings
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── setting_key (VARCHAR(100) UNIQUE NOT NULL)
├── setting_value (TEXT)
├── setting_type (TEXT NOT NULL CHECK (setting_type IN ('string', 'integer', 'boolean', 'json')))
├── description (TEXT)
├── is_system_setting (BOOLEAN DEFAULT FALSE)
├── requires_admin (BOOLEAN DEFAULT FALSE)
├── updated_by_user_id (INTEGER REFERENCES users(id))
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 5. user_database_schemas

**Purpose**: Track schema versions for individual user databases

```sql
user_database_schemas
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE)
├── database_filename (VARCHAR(255) NOT NULL)
├── current_schema_version (VARCHAR(20) NOT NULL)
├── last_migration_applied (VARCHAR(50))
├── migration_history (TEXT CHECK (json_valid(migration_history)))
├── needs_migration (BOOLEAN DEFAULT FALSE)
├── migration_backup_created (BOOLEAN DEFAULT FALSE)
├── last_migration_check (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 6. calendar_sharing

**Purpose**: Manage calendar sharing between users

```sql
calendar_sharing
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── calendar_owner_id (INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE)
├── shared_with_user_id (INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE)
├── exam_context (VARCHAR(100))
├── sharing_permissions (TEXT CHECK (json_valid(sharing_permissions))) -- JSON array
├── sharing_type (TEXT CHECK (sharing_type IN ('power_user_access', 'peer_sharing', 'collaborative', 'tutor_management')))
├── can_view_completed_events (BOOLEAN DEFAULT TRUE)
├── can_view_private_events (BOOLEAN DEFAULT FALSE)
├── can_suggest_events (BOOLEAN DEFAULT FALSE)
├── can_create_events (BOOLEAN DEFAULT FALSE)
├── can_edit_events (BOOLEAN DEFAULT FALSE)
├── can_view_analytics (BOOLEAN DEFAULT FALSE)
├── create_permission_requested (BOOLEAN DEFAULT FALSE)
├── create_permission_granted (BOOLEAN DEFAULT FALSE)
├── edit_permission_requested (BOOLEAN DEFAULT FALSE)
├── edit_permission_granted (BOOLEAN DEFAULT FALSE)
├── permission_request_message (TEXT)
├── permission_response_message (TEXT)
├── permissions_last_updated (TIMESTAMP)
├── shared_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── is_active (BOOLEAN DEFAULT TRUE)
└── sharing_notes (TEXT)
```

---

### 7. calendar_permission_requests

**Purpose**: Track permission requests for calendar access

```sql
calendar_permission_requests
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── requesting_user_id (INTEGER NOT NULL REFERENCES users(id))
├── target_user_id (INTEGER NOT NULL REFERENCES users(id))
├── requested_permissions (TEXT CHECK (json_valid(requested_permissions)))
├── request_message (TEXT)
├── request_status (TEXT CHECK (request_status IN ('pending', 'approved', 'rejected', 'expired')))
├── exam_contexts (TEXT CHECK (json_valid(exam_contexts)))
├── requested_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── responded_at (TIMESTAMP NULL)
├── response_message (TEXT)
└── expires_at (TIMESTAMP)
```

---

### 8. table_backups

**Purpose**: Track granular table backups for restoration

```sql
table_backups
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── table_name (VARCHAR(100) NOT NULL)
├── backup_timestamp (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── backup_file_path (VARCHAR(255) NOT NULL)
├── operation_trigger (VARCHAR(50))
├── operation_description (TEXT)
├── rows_affected (INTEGER)
├── file_size_bytes (INTEGER)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── cleanup_eligible_after (TIMESTAMP)
```

---

### 9. backup_cleanup_log

**Purpose**: Track backup maintenance operations

```sql
backup_cleanup_log
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── cleanup_date (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── files_removed (INTEGER)
├── total_space_freed (INTEGER)
├── retention_policy_days (INTEGER DEFAULT 10)
└── cleanup_trigger (VARCHAR(50))
```

---

## INDIVIDUAL USER DATABASE TABLES

Each user has their own isolated database file containing the following tables:

---

### 10. user_preferences

**Purpose**: Comprehensive user configuration and preferences (67 preference fields covering all aspects of the application)

```sql
user_preferences
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── -- UI/Visual Preferences
├── theme_name (VARCHAR(50) DEFAULT 'default')
├── primary_color_hex (VARCHAR(7) DEFAULT '#2196F3')
├── secondary_color_hex (VARCHAR(7) DEFAULT '#FFC107')
├── font_family (VARCHAR(100) DEFAULT 'system')
├── font_size_scale (DECIMAL(3,2) DEFAULT 1.0 CHECK (font_size_scale BETWEEN 0.5 AND 3.0))
├── ui_density (TEXT DEFAULT 'comfortable' CHECK (ui_density IN ('compact', 'comfortable', 'spacious')))
├── show_animations (BOOLEAN DEFAULT TRUE)
├── -- Question Review Session Defaults
├── default_session_duration_minutes (INTEGER DEFAULT 60 CHECK (default_session_duration_minutes BETWEEN 15 AND 480))
├── default_break_interval_minutes (INTEGER DEFAULT 25 CHECK (default_break_interval_minutes BETWEEN 5 AND 60))
├── default_long_break_minutes (INTEGER DEFAULT 15 CHECK (default_long_break_minutes BETWEEN 10 AND 60))
├── manual_break_control (BOOLEAN DEFAULT TRUE) -- User manually initiates and ends breaks
├── -- Analytics & Reporting
├── analytics_detail_level (TEXT DEFAULT 'detailed' CHECK (analytics_detail_level IN ('basic', 'detailed', 'comprehensive')))
├── dashboard_auto_refresh_seconds (INTEGER DEFAULT 300 CHECK (dashboard_auto_refresh_seconds BETWEEN 30 AND 3600))
├── show_performance_trends (BOOLEAN DEFAULT TRUE)
├── show_mistake_patterns (BOOLEAN DEFAULT TRUE)
├── show_subject_breakdown (BOOLEAN DEFAULT TRUE)
├── show_time_analytics (BOOLEAN DEFAULT TRUE)
├── include_deleted_data_in_analytics (BOOLEAN DEFAULT FALSE)
├── -- Calendar & Task Management
├── calendar_default_view (TEXT DEFAULT 'week' CHECK (calendar_default_view IN ('day', 'week', 'month')))
├── calendar_start_time (TIME DEFAULT '06:00:00')
├── calendar_end_time (TIME DEFAULT '22:00:00')
├── calendar_time_slot_minutes (INTEGER DEFAULT 30 CHECK (calendar_time_slot_minutes IN (15, 30, 60)))
├── show_weekend_in_calendar (BOOLEAN DEFAULT TRUE)
├── track_calendar_adherence (BOOLEAN DEFAULT TRUE)
├── -- Urgency & Priority System
├── urgency_color_scheme (TEXT DEFAULT 'traffic_light' CHECK (urgency_color_scheme IN ('traffic_light', 'heat_map', 'custom')))
├── show_urgency_scores_in_analytics (BOOLEAN DEFAULT TRUE)
├── show_urgency_colors_in_calendar (BOOLEAN DEFAULT TRUE)
├── urgency_recalculation_frequency (TEXT DEFAULT 'daily' CHECK (urgency_recalculation_frequency IN ('real_time', 'hourly', 'daily')))
├── weight_calculation_user_configurable (BOOLEAN DEFAULT TRUE)
├── child_subject_weight_inheritance_fraction (DECIMAL(3,2) DEFAULT 0.5 CHECK (child_subject_weight_inheritance_fraction BETWEEN 0.1 AND 1.0))
├── -- Notification Preferences
├── enable_desktop_notifications (BOOLEAN DEFAULT TRUE)
├── enable_system_tray_alerts (BOOLEAN DEFAULT TRUE)
├── enable_in_app_reminders (BOOLEAN DEFAULT TRUE)
├── notification_sound_enabled (BOOLEAN DEFAULT TRUE)
├── notification_sound_file (VARCHAR(255) DEFAULT 'default')
├── quiet_hours_start (TIME DEFAULT '22:00:00')
├── quiet_hours_end (TIME DEFAULT '08:00:00')
├── -- Power User Oversight Settings
├── share_analytics_with_power_user (BOOLEAN DEFAULT FALSE)
├── allow_power_user_goal_setting (BOOLEAN DEFAULT FALSE)
├── allow_power_user_calendar_access (BOOLEAN DEFAULT FALSE)
├── notify_power_user_of_missed_sessions (BOOLEAN DEFAULT FALSE)
├── power_user_report_frequency (TEXT DEFAULT 'never' CHECK (power_user_report_frequency IN ('daily', 'weekly', 'monthly', 'never')))
├── -- Entry Review Window
├── entry_review_items_per_page (INTEGER DEFAULT 25 CHECK (entry_review_items_per_page BETWEEN 10 AND 100))
├── entry_review_default_sort_field (VARCHAR(100) DEFAULT 'answered_incorrectly_date')
├── entry_review_default_sort_direction (TEXT DEFAULT 'desc' CHECK (entry_review_default_sort_direction IN ('asc', 'desc')))
├── entry_review_group_by_subject (BOOLEAN DEFAULT FALSE)
├── entry_review_show_deleted (BOOLEAN DEFAULT FALSE)
├── entry_review_search_fuzzy_matching (BOOLEAN DEFAULT TRUE)
├── entry_review_enable_bulk_calendar_assignment (BOOLEAN DEFAULT TRUE)
├── -- AnkiConnect Integration
├── anki_integration_enabled (BOOLEAN DEFAULT FALSE)
├── ankiconnect_port (INTEGER DEFAULT 8765 CHECK (ankiconnect_port BETWEEN 1000 AND 65535))
├── ankiconnect_auto_connect_startup (BOOLEAN DEFAULT TRUE)
├── anki_cache_refresh_interval_minutes (INTEGER DEFAULT 15 CHECK (anki_cache_refresh_interval_minutes BETWEEN 1 AND 1440))
├── anki_cache_specified_decks_only (BOOLEAN DEFAULT TRUE)
├── anki_show_stats_in_urgency_calculation (BOOLEAN DEFAULT TRUE)
├── anki_auto_suspend_cards (BOOLEAN DEFAULT FALSE)
├── anki_cache_refresh_on_demand (BOOLEAN DEFAULT TRUE)
├── -- Obsidian Integration
├── obsidian_integration_enabled (BOOLEAN DEFAULT FALSE)
├── obsidian_vault_path (VARCHAR(500))
├── obsidian_auto_export_enabled (BOOLEAN DEFAULT FALSE)
├── obsidian_export_format (TEXT DEFAULT 'markdown' CHECK (obsidian_export_format IN ('markdown', 'json')))
├── obsidian_bidirectional_sync (BOOLEAN DEFAULT TRUE)
├── -- Data Management & Backup
├── auto_backup_enabled (BOOLEAN DEFAULT TRUE)
├── backup_frequency_hours (INTEGER DEFAULT 24 CHECK (backup_frequency_hours BETWEEN 1 AND 168))
├── backup_retention_days (INTEGER DEFAULT 30 CHECK (backup_retention_days BETWEEN 7 AND 365))
├── cloud_sync_enabled (BOOLEAN DEFAULT FALSE)
├── export_include_charts_in_pdf (BOOLEAN DEFAULT TRUE)
├── export_include_images_in_pdf (BOOLEAN DEFAULT TRUE)
├── default_export_format (TEXT DEFAULT 'pdf' CHECK (default_export_format IN ('csv', 'pdf', 'json')))
├── csv_include_metadata (BOOLEAN DEFAULT TRUE)
├── export_date_format (VARCHAR(20) DEFAULT 'YYYY-MM-DD')
├── -- Real-time & Performance
├── realtime_update_delay_ms (INTEGER DEFAULT 1500 CHECK (realtime_update_delay_ms BETWEEN 100 AND 5000))
├── enable_cross_device_sync (BOOLEAN DEFAULT TRUE)
├── subscribe_to_all_table_changes (BOOLEAN DEFAULT TRUE)
├── -- Accessibility
├── high_contrast_mode (BOOLEAN DEFAULT FALSE)
├── screen_reader_support (BOOLEAN DEFAULT FALSE)
├── keyboard_navigation_hints (BOOLEAN DEFAULT TRUE)
├── enable_custom_keyboard_shortcuts (BOOLEAN DEFAULT TRUE)
├── -- Timestamps & Sync
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
├── global_uuid (VARCHAR(36) UNIQUE)
├── sync_status (VARCHAR(20) DEFAULT 'local')
└── last_synced_at (TIMESTAMP NULL)
```

---

### 11. keyboard_shortcuts

**Purpose**: User-customizable keyboard shortcuts

```sql
keyboard_shortcuts
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── action_name (VARCHAR(100) NOT NULL)
├── shortcut_key_combination (VARCHAR(50) NOT NULL)
├── context (VARCHAR(50))
├── is_active (BOOLEAN DEFAULT TRUE)
├── is_custom (BOOLEAN DEFAULT FALSE)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 12. dashboard_layouts

**Purpose**: Configurable analytics dashboard layouts

```sql
dashboard_layouts
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── layout_name (VARCHAR(100) NOT NULL)
├── is_active (BOOLEAN DEFAULT FALSE)
├── is_default (BOOLEAN DEFAULT FALSE)
├── grid_columns (INTEGER DEFAULT 12)
├── grid_rows (INTEGER DEFAULT 8)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 13. dashboard_widgets

**Purpose**: Individual widgets within dashboard layouts

```sql
dashboard_widgets
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── dashboard_layout_id (INTEGER NOT NULL REFERENCES dashboard_layouts(id) ON DELETE CASCADE)
├── widget_type (TEXT CHECK (widget_type IN ('mistake_trends', 'subject_performance', 'study_time', 'calendar_upcoming', 'tag_cloud', 'progress_chart')))
├── widget_title (VARCHAR(100))
├── grid_x (INTEGER)
├── grid_y (INTEGER)
├── grid_width (INTEGER)
├── grid_height (INTEGER)
├── widget_config (TEXT CHECK (json_valid(widget_config)))
├── is_visible (BOOLEAN DEFAULT TRUE)
├── sort_order (INTEGER)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 14. export_templates

**Purpose**: User-defined export configurations

```sql
export_templates
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── template_name (VARCHAR(100) NOT NULL)
├── template_description (TEXT)
├── export_format (TEXT CHECK (export_format IN ('csv', 'pdf', 'json')))
├── is_active (BOOLEAN DEFAULT TRUE)
├── is_default (BOOLEAN DEFAULT FALSE)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 15. export_template_fields

**Purpose**: Fields included in export templates

```sql
export_template_fields
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── export_template_id (INTEGER NOT NULL REFERENCES export_templates(id) ON DELETE CASCADE)
├── field_name (VARCHAR(100) NOT NULL)
├── field_display_name (VARCHAR(100))
├── field_type (TEXT CHECK (field_type IN ('text', 'number', 'date', 'boolean', 'image')))
├── include_in_export (BOOLEAN DEFAULT TRUE)
├── field_order (INTEGER)
├── formatting_options (TEXT CHECK (json_valid(formatting_options)))
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 16. export_template_filters

**Purpose**: Filters for export templates

```sql
export_template_filters
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── export_template_id (INTEGER NOT NULL REFERENCES export_templates(id) ON DELETE CASCADE)
├── filter_field (VARCHAR(100) NOT NULL)
├── filter_operator (TEXT CHECK (filter_operator IN ('equals', 'contains', 'greater_than', 'less_than', 'between', 'in')))
├── filter_value (TEXT)
├── is_active (BOOLEAN DEFAULT TRUE)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 17. user_weight_configurations

**Purpose**: User-customizable weight factors for urgency calculation

```sql
user_weight_configurations
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── exam_context (VARCHAR(100))
├── weight_factor_exam_importance (DECIMAL(3,2) DEFAULT 0.30 CHECK (weight_factor_exam_importance BETWEEN 0.0 AND 1.0))
├── weight_factor_recent_mistakes (DECIMAL(3,2) DEFAULT 0.20 CHECK (weight_factor_recent_mistakes BETWEEN 0.0 AND 1.0))
├── weight_factor_anki_performance (DECIMAL(3,2) DEFAULT 0.30 CHECK (weight_factor_anki_performance BETWEEN 0.0 AND 1.0))
├── weight_factor_time_since_review (DECIMAL(3,2) DEFAULT 0.20 CHECK (weight_factor_time_since_review BETWEEN 0.0 AND 1.0))
├── is_active (BOOLEAN DEFAULT TRUE)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

-- Constraint
CHECK (ABS((weight_factor_exam_importance + weight_factor_recent_mistakes + weight_factor_anki_performance + weight_factor_time_since_review) - 1.0) < 0.001)
```

---

### 18. tag_suggestion_preferences

**Purpose**: User preferences for tag auto-suggestions

```sql
tag_suggestion_preferences
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── enable_auto_suggestions (BOOLEAN DEFAULT TRUE)
├── confidence_threshold (DECIMAL(5,2) DEFAULT 0.75)
├── max_suggestions_per_question (INTEGER DEFAULT 5)
├── preferred_tag_categories (TEXT CHECK (json_valid(preferred_tag_categories)))
├── excluded_tag_ids (TEXT CHECK (json_valid(excluded_tag_ids)))
├── learning_rate (DECIMAL(5,2) DEFAULT 0.1)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 19. study_suggestion_preferences

**Purpose**: User preferences for study session suggestions

```sql
study_suggestion_preferences
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── enable_study_suggestions (BOOLEAN DEFAULT TRUE)
├── suggestion_frequency (TEXT DEFAULT 'weekly' CHECK (suggestion_frequency IN ('daily', 'weekly', 'on_demand')))
├── preferred_session_length_minutes (INTEGER DEFAULT 60)
├── max_questions_per_session (INTEGER DEFAULT 10)
├── include_spaced_repetition (BOOLEAN DEFAULT TRUE)
├── focus_on_weak_areas (BOOLEAN DEFAULT TRUE)
├── balance_subjects_equally (BOOLEAN DEFAULT FALSE)
├── minimum_confidence_for_mastery (INTEGER DEFAULT 4 CHECK (minimum_confidence_for_mastery BETWEEN 1 AND 5)) 
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 20. notification_rules

**Purpose**: User-defined notification rules and triggers

```sql
notification_rules
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── rule_name (VARCHAR(100) NOT NULL)
├── trigger_type (TEXT CHECK (trigger_type IN ('calendar_event', 'study_goal', 'pattern_detection', 'scheduled')))
├── trigger_conditions (TEXT CHECK (json_valid(trigger_conditions)))
├── notification_channels (TEXT CHECK (json_valid(notification_channels)))
├── notification_message_template (TEXT)
├── urgency_level (INTEGER CHECK (urgency_level BETWEEN 1 AND 5))
├── advance_notice_minutes (INTEGER)
├── repeat_interval_minutes (INTEGER DEFAULT 0)
├── max_repeats (INTEGER DEFAULT 1)
├── is_active (BOOLEAN DEFAULT TRUE)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 21. integration_configs

**Purpose**: External integration configurations (Anki, Obsidian)

```sql
integration_configs
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── integration_type (TEXT CHECK (integration_type IN ('anki', 'obsidian', 'calendar_export')))
├── config_name (VARCHAR(100))
├── connection_settings (TEXT CHECK (json_valid(connection_settings)))
├── sync_settings (TEXT CHECK (json_valid(sync_settings)))
├── last_sync_timestamp (TIMESTAMP NULL)
├── last_sync_status (TEXT CHECK (last_sync_status IN ('success', 'error', 'pending')))
├── last_sync_message (TEXT)
├── is_active (BOOLEAN DEFAULT FALSE)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 22. subject_nodes

**Purpose**: Hierarchical subject organization with exam weights

```sql
subject_nodes
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── exam_context (VARCHAR(100) NOT NULL)
├── name (VARCHAR(255) NOT NULL)
├── parent_id (INTEGER REFERENCES subject_nodes(id))
├── level_type (VARCHAR(50) NOT NULL)
├── sort_order (INTEGER DEFAULT 1)
├── exam_weight_low (DECIMAL(5,2))
├── exam_weight_high (DECIMAL(5,2))
├── exam_source (VARCHAR(255))
├── -- Outline versioning and classification
├── outline_type (TEXT CHECK (outline_type IN ('content', 'competency', 'integrated', 'user_defined')))
├── outline_version (VARCHAR(20))
├── outline_effective_date (DATE)
├── outline_deprecated_date (DATE)
├── is_official_topic (BOOLEAN DEFAULT TRUE)
├── user_added (BOOLEAN DEFAULT FALSE)
├── user_added_rationale (TEXT)
├── status (TEXT DEFAULT 'active' CHECK (status IN ('active', 'deleted')))
├── deleted_at (TIMESTAMP NULL)
├── retain_for_statistics (BOOLEAN DEFAULT FALSE)
├── statistics_changed_at (TIMESTAMP NULL)
├── deletion_context (TEXT CHECK (json_valid(deletion_context)))
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
├── -- Future-proofing fields
├── created_by (VARCHAR(255))
├── institution_id (VARCHAR(255))
├── sharing_permissions (TEXT CHECK (json_valid(sharing_permissions)))
├── version_number (INTEGER DEFAULT 1)
├── sync_status (VARCHAR(20) DEFAULT 'local')
├── global_uuid (VARCHAR(36) UNIQUE)
├── last_modified (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── sync_version (INTEGER DEFAULT 1)
└── sync_hash (VARCHAR(64))

CREATE UNIQUE INDEX idx_unique_exam_hierarchy ON subject_nodes (exam_context, name, parent_id);
CREATE INDEX idx_subject_nodes_exam_parent ON subject_nodes(exam_context, parent_id);
CREATE INDEX idx_subject_nodes_exam_level ON subject_nodes(exam_context, level_type);
CREATE INDEX idx_subject_nodes_weights ON subject_nodes(exam_weight_low, exam_weight_high);
CREATE INDEX idx_subject_nodes_status ON subject_nodes(status, exam_context);
```

---

### 23. exam_contexts **(NEW - Phase 2)**

**Purpose**: Store exam contexts (exams the user is studying for) with configuration settings

```sql
exam_contexts
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── exam_name (VARCHAR(255) UNIQUE NOT NULL) -- e.g., "USMLE Step 1", "SAT"
├── exam_description (TEXT)
├── exam_date (DATE) -- Scheduled exam date (if known)
├── created_date (DATE DEFAULT CURRENT_DATE)
├── is_active (BOOLEAN DEFAULT TRUE)
├── default_hierarchy_levels (TEXT CHECK (json_valid(default_hierarchy_levels))) -- JSON array: ["System", "Subsystem", "Topic", "Subtopic", "Child"]
├── weight_validation_rules (TEXT CHECK (json_valid(weight_validation_rules))) -- JSON object with validation settings
├── notes (TEXT)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

CREATE UNIQUE INDEX idx_unique_exam_name_per_user ON exam_contexts (user_id, exam_name);
CREATE INDEX idx_active_exams ON exam_contexts (user_id, is_active) WHERE is_active = TRUE;
```

**default_hierarchy_levels JSON Structure:**
```json
["System", "Subsystem", "Topic", "Subtopic", "Child"]
```
- Default 5 levels for all exams
- Can be extended with custom levels beyond these 5
- Custom levels stored as "Level 6", "Level 7", etc. in hierarchy_level_definitions table

**weight_validation_rules JSON Structure:**
```json
{
    "autonomous_weight_balancing": true,
    "allow_absolute_weight_editing": false,
    "precision_decimal_places": 1,
    "require_exact_100": true,
    "balancing_algorithm": "proportional"
}
```

**Field Descriptions:**
- `autonomous_weight_balancing` (boolean, default: true): When enabled, editing one child's weight automatically adjusts siblings to maintain 100%. When disabled, user must manually balance weights and system only validates.
- `allow_absolute_weight_editing` (boolean, default: false): When enabled, user can directly edit absolute weights (% of root). System recalculates relative weights. When disabled, only relative weights are editable.
- `precision_decimal_places` (integer, default: 1): Decimal precision for weight percentages (1 = 0.1%, 2 = 0.01%)
- `require_exact_100` (boolean, default: true): Whether children weights must sum exactly to 100% or allow small rounding differences
- `balancing_algorithm` (string, default: "proportional"): Algorithm for autonomous balancing
  - "proportional": Distribute changes proportionally based on current sibling weights (prevents zero weights)
  - "even": Distribute changes evenly across all siblings (simpler but can create zeros)

**UI Behavior Based on Settings:**
- When `autonomous_weight_balancing = true`: Show only relative percentages, auto-adjust siblings
- When `autonomous_weight_balancing = false`: Show both relative AND absolute percentages, validate but don't auto-adjust

---

### 24. hierarchy_level_definitions **(NEW - Phase 2)**

**Purpose**: Define custom hierarchy levels for each exam context beyond the default 5 levels

```sql
hierarchy_level_definitions
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── exam_context_id (INTEGER NOT NULL REFERENCES exam_contexts(id) ON DELETE CASCADE)
├── level_name (VARCHAR(100) NOT NULL) -- e.g., "System", "Subsystem", "Level 6", "Level 7"
├── level_order (INTEGER NOT NULL) -- 1, 2, 3, 4, 5, 6, 7...
├── is_required (BOOLEAN DEFAULT FALSE) -- Must this level exist in the hierarchy?
├── display_name_template (VARCHAR(255)) -- For levels > 5: "Daughter of {parent_name}"
├── is_custom_level (BOOLEAN DEFAULT FALSE) -- TRUE for levels beyond default 5
├── created_date (DATE DEFAULT CURRENT_DATE)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

CREATE UNIQUE INDEX idx_unique_level_per_exam ON hierarchy_level_definitions (exam_context_id, level_order);
CREATE INDEX idx_exam_levels_ordered ON hierarchy_level_definitions (exam_context_id, level_order);
```

**Notes:**
- Default 5 levels: System (1), Subsystem (2), Topic (3), Subtopic (4), Child (5)
- Custom levels beyond 5: Stored as "Level 6", "Level 7", etc.
- Frontend displays custom levels using `display_name_template`: "Daughter of [Parent Name]"

---

### 25. subject_node_weights **(NEW - Phase 2)**

**Purpose**: Track weight change history for audit trail and undo capability

```sql
subject_node_weights
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── subject_node_id (INTEGER NOT NULL REFERENCES subject_nodes(id) ON DELETE CASCADE)
├── weight_value (DECIMAL(5,2) NOT NULL) -- The weight percentage
├── edited_date (DATE NOT NULL DEFAULT CURRENT_DATE)
├── edited_by (TEXT DEFAULT 'user') -- 'user' or 'system'
├── edited_reason (TEXT) -- Optional explanation for change
├── previous_weight (DECIMAL(5,2)) -- Weight before this change
├── change_type (TEXT CHECK (change_type IN ('initial', 'manual_edit', 'auto_recalculate', 'parent_redistribution')))
├── affected_siblings (TEXT CHECK (json_valid(affected_siblings))) -- JSON array of sibling IDs affected
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── user_notes (TEXT)

CREATE INDEX idx_weight_history_by_node ON subject_node_weights (subject_node_id, edited_date DESC);
CREATE INDEX idx_weight_changes_by_date ON subject_node_weights (edited_date DESC);
```

**change_type Values:**
- `initial` - First weight assignment when node created
- `manual_edit` - User manually changed the weight
- `auto_recalculate` - System automatically recalculated due to sibling changes
- `parent_redistribution` - Parent's weight changed, affecting this node

**affected_siblings JSON Structure:**
```json
[123, 456, 789]  // Array of subject_node IDs whose weights were also adjusted
```

**Example Weight Change Scenarios:**

*Scenario 1: Initial Weight Assignment*
```json
{
    "subject_node_id": 101,
    "weight_value": 33.3,
    "edited_date": "2025-11-08",
    "edited_by": "system",
    "edited_reason": "Initial even distribution among 3 children",
    "previous_weight": null,
    "change_type": "initial",
    "affected_siblings": [102, 103]
}
```

*Scenario 2: User Manual Edit with Proportional Balancing*
```json
{
    "subject_node_id": 101,
    "weight_value": 50.0,
    "edited_date": "2025-11-08",
    "edited_by": "user",
    "edited_reason": "User prioritized this topic for exam prep",
    "previous_weight": 33.3,
    "change_type": "manual_edit",
    "affected_siblings": [102, 103],
    "user_notes": "This topic appears frequently on practice exams"
}
```
*In this scenario, siblings 102 and 103 were automatically adjusted from 33.3% each to 25.0% each (proportional distribution of the -16.7% change)*

*Scenario 3: Auto-recalculation Due to Sibling Change*
```json
{
    "subject_node_id": 102,
    "weight_value": 25.0,
    "edited_date": "2025-11-08",
    "edited_by": "system",
    "edited_reason": "Auto-adjusted due to sibling 101 weight change",
    "previous_weight": 33.3,
    "change_type": "auto_recalculate",
    "affected_siblings": [103]
}
```

---

### 26. level_types

**Purpose**: User-customizable hierarchy level definitions

```sql
level_types
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── name (VARCHAR(100) NOT NULL)
├── level_order (INTEGER NOT NULL)
├── is_weight_bearing (BOOLEAN DEFAULT FALSE)
├── is_active (BOOLEAN DEFAULT TRUE)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 24. question_analyses

**Purpose**: Storage for incorrectly answered questions with metacognitive reflection

```sql
question_analyses
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── exam_context (VARCHAR(100) NOT NULL)
├── question_source (VARCHAR(255) NOT NULL)
├── question_source_id (VARCHAR(100) NOT NULL)
├── source_reference (VARCHAR(500))
├── answered_incorrectly_date (DATE NOT NULL)
├── user_selected_answer (VARCHAR(10))
├── correct_answer (VARCHAR(10))
├── perceived_difficulty (INTEGER CHECK (perceived_difficulty BETWEEN 1 AND 5))
├── metacognitive_reflection (TEXT)
├── question_explanation (TEXT)
├── user_notes (TEXT)
├── time_spent_on_question (INTEGER)
├── confidence_before_answer (INTEGER CHECK (confidence_before_answer BETWEEN 1 AND 5))
├── mistake_category (TEXT CHECK (mistake_category IN ('knowledge_gap', 'misread_question', 'silly_mistake', 'time_pressure', 'misunderstanding', 'memory_failure', 'calculation_error', 'wrong_approach', 'incomplete_solution', 'anxiety_related', 'second_guessing', 'elimination_error', 'careless_mistake', 'focus_problem', 'fatigue_related', 'poor_prioritization', 'wrong_guess_strategy', 'test_strategy_error')))
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
├── -- Future-proofing
├── global_uuid (VARCHAR(36) UNIQUE)
├── sync_status (VARCHAR(20) DEFAULT 'local')
└── review_status (TEXT DEFAULT 'pending_review' CHECK (review_status IN ('pending_review', 'reviewed', 'mastered')))
```

---

### 25. question_topic_assignments

**Purpose**: Many-to-many relationship between questions and subject nodes

```sql
question_topic_assignments
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── question_analysis_id (INTEGER NOT NULL REFERENCES question_analyses(id) ON DELETE CASCADE)
├── subject_node_id (INTEGER NOT NULL REFERENCES subject_nodes(id) ON DELETE CASCADE)
├── exam_context (VARCHAR(100) NOT NULL)
├── assignment_type (TEXT CHECK (assignment_type IN ('primary', 'secondary')))
├── relevance_score (INTEGER CHECK (relevance_score BETWEEN 1 AND 5))
├── assigned_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── assigned_by (TEXT CHECK (assigned_by IN ('user', 'auto_suggested')))
├── -- Migration tracking
├── migrated_from_node_id (INTEGER REFERENCES subject_nodes(id))
├── migration_date (TIMESTAMP)
├── needs_review (BOOLEAN DEFAULT FALSE)
└── review_reason (TEXT)
```

---

### 26. question_media

**Purpose**: User-added media files for questions

```sql
question_media
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── question_analysis_id (INTEGER NOT NULL REFERENCES question_analyses(id) ON DELETE CASCADE)
├── media_type (TEXT CHECK (media_type IN ('image', 'diagram', 'screenshot', 'audio_note', 'pdf_excerpt', 'video_clip')))
├── file_name (VARCHAR(255) NOT NULL)
├── file_path (VARCHAR(500) NOT NULL)
├── description (VARCHAR(500))
├── file_size_bytes (INTEGER)
├── mime_type (VARCHAR(100))
├── display_order (INTEGER DEFAULT 1)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── source_description (VARCHAR(255))
```

---

### 27. question_sources

**Purpose**: Catalog of question banks

```sql
question_sources
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── source_name (VARCHAR(255) NOT NULL)
├── source_type (TEXT CHECK (source_type IN ('official_prep', 'commercial_prep', 'textbook', 'online_platform', 'practice_tests', 'tutoring_materials', 'flashcard_system', 'video_course', 'study_group', 'previous_exams', 'other')))
├── exam_context (VARCHAR(100))
├── total_questions (INTEGER)
├── user_rating (INTEGER CHECK (user_rating BETWEEN 1 AND 5))
└── added_date (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 28. tags

**Purpose**: Flexible tagging system for cross-cutting categorization

```sql
tags
tags
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── exam_context (VARCHAR(100) NOT NULL)
├── tag_name (VARCHAR(100) NOT NULL)
├── tag_category (TEXT CHECK (tag_category IN ('mistake_type', 'study_method', 'content_type', 'difficulty', 'strategy', 'personal', 'other')))
├── color_hex (VARCHAR(7) DEFAULT '#2196F3')
├── description (TEXT)
├── usage_count (INTEGER DEFAULT 0)
├── is_active (BOOLEAN DEFAULT TRUE)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── last_used_at (TIMESTAMP)
├── -- Future-proofing
├── global_uuid (VARCHAR(36) UNIQUE)
└── sync_status (VARCHAR(20) DEFAULT 'local')

CREATE UNIQUE INDEX idx_unique_tag_per_exam ON tags (exam_context, tag_name);
CREATE INDEX idx_tags_exam_context ON tags(exam_context, tag_name);
CREATE INDEX idx_tags_category ON tags(tag_category, is_active);
```

---

### 29. question_tags

**Purpose**: Many-to-many relationship between questions and tags

```sql
question_tags
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── question_analysis_id (INTEGER NOT NULL REFERENCES question_analyses(id) ON DELETE CASCADE)
├── tag_id (INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE)
├── exam_context (VARCHAR(100) NOT NULL)
├── assigned_by (TEXT CHECK (assigned_by IN ('user', 'auto_suggestion', 'pattern_detection')))
├── confidence_score (DECIMAL(5,2))
├── assigned_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── last_reviewed_at (TIMESTAMP)

CREATE INDEX idx_question_tags_lookup ON question_tags(question_analysis_id, tag_id);
CREATE INDEX idx_question_tags_by_tag ON question_tags(tag_id, assigned_at DESC);
```

---

### 30. tag_suggestion_rules

**Purpose**: Rules for auto-suggesting tags based on patterns

```sql
tag_suggestion_rules
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── exam_context (VARCHAR(100))
├── rule_name (VARCHAR(255) NOT NULL)
├── rule_type (TEXT CHECK (rule_type IN ('text_pattern', 'behavioral_pattern', 'performance_pattern', 'contextual_pattern')))
├── trigger_conditions (TEXT CHECK (json_valid(trigger_conditions)))
├── suggested_tag_ids (TEXT CHECK (json_valid(suggested_tag_ids)))
├── confidence_score (DECIMAL(5,2))
├── min_data_points (INTEGER DEFAULT 3)
├── success_rate (DECIMAL(5,2))
├── is_active (BOOLEAN DEFAULT TRUE)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── last_validated_at (TIMESTAMP)
```

---

### 31. tag_suggestion_feedback

**Purpose**: Track user responses to tag suggestions for learning

```sql
tag_suggestion_feedback
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── question_analysis_id (INTEGER NOT NULL REFERENCES question_analyses(id) ON DELETE CASCADE)
├── suggested_tag_id (INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE)
├── rule_id (INTEGER REFERENCES tag_suggestion_rules(id))
├── suggestion_confidence (DECIMAL(5,2))
├── user_action (TEXT CHECK (user_action IN ('accepted', 'rejected', 'modified', 'ignored')))
├── user_feedback (TEXT)
├── suggested_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── responded_at (TIMESTAMP)
```

---

### 32. tag_analytics

**Purpose**: Performance analytics for tag effectiveness

```sql
tag_analytics
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── tag_id (INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE)
├── exam_context (VARCHAR(100))
├── analysis_period_start (DATE)
├── analysis_period_end (DATE)
├── total_questions_tagged (INTEGER)
├── improvement_rate (DECIMAL(5,2))
├── average_review_frequency (DECIMAL(5,2))
├── resolution_rate (DECIMAL(5,2))
├── most_effective_study_method (VARCHAR(100))
├── average_time_to_mastery (INTEGER)
├── correlation_with_other_tags (TEXT CHECK (json_valid(correlation_with_other_tags)))
├── recommendations (TEXT) -- FUTURE: AI-generated study recommendations
├── calculated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── next_calculation_due (TIMESTAMP)
```

---

### 33. tag_relationships

**Purpose**: Track relationships between tags

```sql
tag_relationships
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── tag_1_id (INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE)
├── tag_2_id (INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE)
├── exam_context (VARCHAR(100))
├── relationship_type (TEXT CHECK (relationship_type IN ('frequently_together', 'mutually_exclusive', 'causal', 'sequential')))
├── co_occurrence_count (INTEGER)
├── relationship_strength (DECIMAL(5,2) CHECK (relationship_strength BETWEEN 0.0 AND 1.0))
├── relationship_description (TEXT)
├── discovered_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── last_validated_at (TIMESTAMP)
└── confidence_score (DECIMAL(5,2))
```

---

### 34. question_review_sessions

**Purpose**: Track question review sessions with break management

```sql
question_review_sessions
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── session_title (VARCHAR(255))
├── start_time (TIMESTAMP NOT NULL)
├── end_time (TIMESTAMP)
├── total_duration_minutes (INTEGER)
├── total_break_time_minutes (INTEGER DEFAULT 0)
├── effective_study_time_minutes (INTEGER)
├── questions_reviewed_count (INTEGER DEFAULT 0)
├── session_status (TEXT CHECK (session_status IN ('active', 'paused', 'completed', 'abandoned')))
├── last_activity_timestamp (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
├── -- Link to calendar if session was planned
├── calendar_event_id (INTEGER REFERENCES calendar_events(id))
├── -- Future-proofing
├── global_uuid (VARCHAR(36) UNIQUE)
└── sync_status (VARCHAR(20) DEFAULT 'local')
```

---

### 35. session_breaks

**Purpose**: Detailed break tracking within review sessions

```sql
session_breaks
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── review_session_id (INTEGER NOT NULL REFERENCES question_review_sessions(id) ON DELETE CASCADE)
├── break_start_time (TIMESTAMP NOT NULL)
├── break_end_time (TIMESTAMP)
├── break_duration_minutes (INTEGER)
├── break_reason (VARCHAR(255))
├── break_type (TEXT DEFAULT 'manual' CHECK (break_type IN ('manual', 'auto_detected', 'scheduled')))
├── planned_duration_minutes (INTEGER)
├── break_quality_rating (INTEGER CHECK (break_quality_rating BETWEEN 1 AND 5))
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 36. session_question_analyses

**Purpose**: Link questions reviewed to sessions with timing

```sql
session_question_analyses
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── review_session_id (INTEGER NOT NULL REFERENCES question_review_sessions(id) ON DELETE CASCADE)
├── question_analysis_id (INTEGER NOT NULL REFERENCES question_analyses(id) ON DELETE CASCADE)
├── analysis_order (INTEGER)
├── time_spent_minutes (INTEGER)
├── review_type (TEXT CHECK (review_type IN ('first_analysis', 'follow_up_review', 'spaced_repetition')))
├── understanding_before (INTEGER CHECK (understanding_before BETWEEN 1 AND 5))
├── understanding_after (INTEGER CHECK (understanding_after BETWEEN 1 AND 5))
├── insights_generated (TEXT)
├── needs_further_review (BOOLEAN DEFAULT FALSE)
├── next_review_priority (TEXT CHECK (next_review_priority IN ('high', 'medium', 'low')))
└── added_to_session_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 37. learning_insights

**Purpose**: Capture learning moments and action plans

```sql
learning_insights
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── question_analysis_id (INTEGER NOT NULL REFERENCES question_analyses(id) ON DELETE CASCADE)
├── insight_type (TEXT CHECK (insight_type IN ('knowledge_gap_filled', 'concept_clarified', 'pattern_recognized', 'strategy_improved')))
├── insight_description (TEXT NOT NULL)
├── action_plan (TEXT)
├── confidence_level (INTEGER CHECK (confidence_level BETWEEN 1 AND 5))
├── evidence (TEXT)
├── related_questions_count (INTEGER DEFAULT 1)
├── impact_assessment (TEXT CHECK (impact_assessment IN ('high', 'medium', 'low')))
├── completed_action (BOOLEAN DEFAULT FALSE)
├── completion_date (TIMESTAMP)
├── effectiveness_rating (INTEGER CHECK (effectiveness_rating BETWEEN 1 AND 5))
└── recorded_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 38. mistake_patterns

**Purpose**: Auto-detected patterns across multiple mistakes

```sql
mistake_patterns
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── exam_context (VARCHAR(100))
├── pattern_type (TEXT CHECK (pattern_type IN ('subject_weakness', 'question_type_issue', 'time_management', 'reading_comprehension')))
├── pattern_description (TEXT NOT NULL)
├── questions_affected (INTEGER)
├── first_identified (DATE)
├── improvement_trend (TEXT CHECK (improvement_trend IN ('worsening', 'stable', 'improving')))
├── confidence_score (DECIMAL(5,2))
└── last_calculated (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 39. review_schedule

**Purpose**: Simple review scheduling for non-Anki users

```sql
review_schedule
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── question_analysis_id (INTEGER NOT NULL REFERENCES question_analyses(id) ON DELETE CASCADE)
├── review_type (TEXT CHECK (review_type IN ('immediate', 'next_day', 'weekly', 'monthly', 'custom')))
├── scheduled_review_date (DATE NOT NULL)
├── actual_review_date (DATE)
├── review_outcome (TEXT CHECK (review_outcome IN ('still_confused', 'somewhat_clear', 'confident', 'mastered')))
├── review_notes (TEXT)
├── next_review_interval_days (INTEGER)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 40. calendar_events

**Purpose**: Comprehensive calendar system for study planning

```sql
calendar_events
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── exam_context (VARCHAR(100) NOT NULL)
├── event_title (VARCHAR(255) NOT NULL)
├── event_description (TEXT)
├── event_category (TEXT CHECK (event_category IN ('study_session', 'content_review', 'assignment', 'exam_prep', 'practice_test', 'custom')))
├── -- Scheduling
├── scheduled_date (DATE NOT NULL)
├── start_time (TIME)
├── end_time (TIME)
├── estimated_duration_minutes (INTEGER)
├── is_flexible_scheduling (BOOLEAN DEFAULT TRUE)
├── is_time_blocked (BOOLEAN DEFAULT FALSE)
├── -- Recurring Events
├── is_recurring (BOOLEAN DEFAULT FALSE)
├── recurrence_pattern (TEXT CHECK (json_valid(recurrence_pattern)))
├── parent_recurring_event_id (INTEGER REFERENCES calendar_events(id))
├── -- Event Status
├── event_status (TEXT CHECK (event_status IN ('scheduled', 'in_progress', 'completed', 'cancelled', 'rescheduled')))
├── completion_percentage (INTEGER DEFAULT 0 CHECK (completion_percentage BETWEEN 0 AND 100))
├── -- Time Tracking
├── actual_start_time (TIMESTAMP)
├── actual_end_time (TIMESTAMP)
├── actual_duration_minutes (INTEGER)
├── total_break_time_minutes (INTEGER DEFAULT 0)
├── effective_work_time_minutes (INTEGER)
├── -- Resources & Context
├── resource_urls (TEXT CHECK (json_valid(resource_urls)))
├── event_notes (TEXT)
├── completion_notes (TEXT)
├── -- Reminders
├── reminder_settings (TEXT CHECK (json_valid(reminder_settings)))
├── -- Sharing & Visibility
├── is_shared_with_power_users (BOOLEAN DEFAULT FALSE)
├── shared_with_user_ids (TEXT CHECK (json_valid(shared_with_user_ids)))
├── visibility_level (TEXT CHECK (visibility_level IN ('private', 'shared', 'power_user_visible')))
├── -- Templates & Bulk Operations
├── created_from_template_id (INTEGER REFERENCES event_templates(id))
├── is_template (BOOLEAN DEFAULT FALSE)
├── template_name (VARCHAR(255))
├── -- Urgency & Priority (User-driven)
├── user_priority (INTEGER CHECK (user_priority BETWEEN 1 AND 5))
├── urgency_notes (TEXT)
├── -- Metadata
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
├── rescheduled_from_event_id (INTEGER REFERENCES calendar_events(id))
├── rescheduled_reason (TEXT)
├── -- Cloud Sync
├── global_uuid (VARCHAR(36) UNIQUE)
├── sync_status (VARCHAR(20) DEFAULT 'local')
└── last_synced_at (TIMESTAMP)
```

---

### 41. event_tasks

**Purpose**: Sub-tasks within calendar events

```sql
event_tasks
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── calendar_event_id (INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE)
├── task_title (VARCHAR(255) NOT NULL)
├── task_description (TEXT)
├── task_type (TEXT CHECK (task_type IN ('review_questions', 'complete_questions', 'read_material', 'watch_video', 'practice_problems', 'custom')))
├── -- Task Specifications
├── target_quantity (INTEGER)
├── target_subject_nodes (TEXT CHECK (json_valid(target_subject_nodes)))
├── estimated_time_minutes (INTEGER)
├── -- Task Status
├── task_status (TEXT CHECK (task_status IN ('not_started', 'in_progress', 'completed', 'skipped')))
├── completion_percentage (INTEGER DEFAULT 0 CHECK (completion_percentage BETWEEN 0 AND 100))
├── actual_time_spent_minutes (INTEGER)
├── -- Task Results
├── questions_completed (INTEGER DEFAULT 0)
├── questions_correct (INTEGER DEFAULT 0)
├── materials_reviewed (TEXT CHECK (json_valid(materials_reviewed)))
├── task_completion_notes (TEXT)
├── -- Rescheduling
├── can_be_rescheduled (BOOLEAN DEFAULT TRUE)
├── rescheduled_to_event_id (INTEGER REFERENCES calendar_events(id))
├── rescheduled_at (TIMESTAMP)
├── rescheduled_reason (TEXT)
├── rescheduling_options (TEXT CHECK (json_valid(rescheduling_options)))
├── original_task_data (TEXT CHECK (json_valid(original_task_data)))
├── rescheduling_history (TEXT CHECK (json_valid(rescheduling_history)))
├── -- Metadata
├── task_order (INTEGER DEFAULT 1)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 42. event_breaks

**Purpose**: Track breaks during calendar events

```sql
event_breaks
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── calendar_event_id (INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE)
├── break_start_time (TIMESTAMP NOT NULL)
├── break_end_time (TIMESTAMP)
├── break_duration_minutes (INTEGER)
├── break_reason (VARCHAR(255))
├── planned_break (BOOLEAN DEFAULT TRUE)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 43. event_templates

**Purpose**: Reusable event templates with categorization

```sql
event_templates
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── template_name (VARCHAR(255) NOT NULL)
├── template_description (TEXT)
├── template_category (TEXT CHECK (template_category IN ('study_session', 'content_review', 'assignment', 'exam_prep', 'practice_test', 'custom')))
├── -- Template Organization
├── template_tags (TEXT CHECK (json_valid(template_tags)))
├── template_subject_areas (TEXT CHECK (json_valid(template_subject_areas)))
├── difficulty_level (INTEGER CHECK (difficulty_level BETWEEN 1 AND 5))
├── recommended_time_of_day (TEXT CHECK (recommended_time_of_day IN ('morning', 'afternoon', 'evening', 'flexible')))
├── -- Default Event Settings
├── default_duration_minutes (INTEGER)
├── default_priority (INTEGER CHECK (default_priority BETWEEN 1 AND 5))
├── default_reminder_settings (TEXT CHECK (json_valid(default_reminder_settings)))
├── -- Template Tasks
├── template_tasks (TEXT CHECK (json_valid(template_tasks)))
├── -- Usage & Sharing
├── times_used (INTEGER DEFAULT 0)
├── is_shared_template (BOOLEAN DEFAULT FALSE)
├── shared_with_user_ids (TEXT CHECK (json_valid(shared_with_user_ids)))
├── original_creator_id (INTEGER)
├── template_rating (DECIMAL(3,2))
├── -- Search & Discovery
├── is_featured_template (BOOLEAN DEFAULT FALSE)
├── template_keywords (TEXT)
├── -- Metadata
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
└── last_used_at (TIMESTAMP)
```

---

### 44. template_categories

**Purpose**: Hierarchical categorization for templates

```sql
template_categories
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── category_name (VARCHAR(100) UNIQUE NOT NULL)
├── category_description (TEXT)
├── parent_category_id (INTEGER REFERENCES template_categories(id))
├── category_color (VARCHAR(7) DEFAULT '#2196F3')
├── display_order (INTEGER DEFAULT 1)
├── is_system_category (BOOLEAN DEFAULT FALSE)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 45. template_category_assignments

**Purpose**: Many-to-many template categorization

```sql
template_category_assignments
├── template_id (INTEGER NOT NULL REFERENCES event_templates(id) ON DELETE CASCADE)
├── category_id (INTEGER NOT NULL REFERENCES template_categories(id) ON DELETE CASCADE)
├── PRIMARY KEY (template_id, category_id)
└── assigned_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 46. recurring_event_patterns

**Purpose**: Reusable recurring pattern definitions

```sql
recurring_event_patterns
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── pattern_name (VARCHAR(255) NOT NULL)
├── pattern_description (TEXT)
├── pattern_json (TEXT CHECK (json_valid(pattern_json)))
├── pattern_type (TEXT CHECK (pattern_type IN ('simple', 'complex', 'custom')))
├── is_predefined_pattern (BOOLEAN DEFAULT FALSE)
├── created_by_user_id (INTEGER)
├── usage_count (INTEGER DEFAULT 0)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 47. event_suggestions

**Purpose**: System-generated study suggestions for calendar

```sql
event_suggestions
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── exam_context (VARCHAR(100))
├── suggestion_type (TEXT CHECK (suggestion_type IN ('review_mistakes', 'practice_weak_areas', 'maintenance_review', 'exam_prep')))
├── suggested_subject_nodes (TEXT CHECK (json_valid(suggested_subject_nodes)))
├── suggestion_title (VARCHAR(255))
├── suggestion_description (TEXT)
├── estimated_duration_minutes (INTEGER)
├── suggested_priority (INTEGER CHECK (suggested_priority BETWEEN 1 AND 5))
├── -- Suggestion Logic
├── based_on_data (TEXT CHECK (json_valid(based_on_data)))
├── confidence_score (DECIMAL(3,2))
├── expires_at (TIMESTAMP)
├── -- User Interaction
├── suggestion_status (TEXT CHECK (suggestion_status IN ('pending', 'accepted', 'dismissed', 'scheduled')))
├── scheduled_to_event_id (INTEGER REFERENCES calendar_events(id))
├── user_feedback (TEXT)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 48. ical_export_configs

**Purpose**: iCal export configurations with full metadata

```sql
ical_export_configs
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── export_name (VARCHAR(255))
├── exam_contexts (TEXT CHECK (json_valid(exam_contexts)))
├── -- Export Options
├── include_tasks (BOOLEAN DEFAULT TRUE)
├── include_break_tracking (BOOLEAN DEFAULT TRUE)
├── include_completion_status (BOOLEAN DEFAULT TRUE)
├── include_time_estimates (BOOLEAN DEFAULT TRUE)
├── include_notes (BOOLEAN DEFAULT TRUE)
├── include_resource_urls (BOOLEAN DEFAULT TRUE)
├── include_private_events (BOOLEAN DEFAULT FALSE)
├── -- Format Options
├── export_format (TEXT CHECK (export_format IN ('ical', 'outlook', 'google_calendar')))
├── timezone_setting (VARCHAR(50) DEFAULT 'local')
├── event_title_format (VARCHAR(255) DEFAULT '{title} ({completion_status})')
├── -- Export History
├── last_exported_at (TIMESTAMP)
├── export_count (INTEGER DEFAULT 0)
├── auto_export_enabled (BOOLEAN DEFAULT FALSE)
├── auto_export_frequency_hours (INTEGER DEFAULT 24)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 49. ical_import_logs

**Purpose**: Track iCal import operations

```sql
ical_import_logs
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── import_filename (VARCHAR(255))
├── events_imported (INTEGER)
├── events_skipped (INTEGER)
├── import_conflicts (TEXT CHECK (json_valid(import_conflicts)))
├── import_status (TEXT CHECK (import_status IN ('success', 'partial', 'failed')))
├── import_notes (TEXT)
└── imported_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 50. anki_connection_config

**Purpose**: AnkiConnect configuration per user

```sql
anki_connection_config
├── user_id (INTEGER PRIMARY KEY NOT NULL)
├── ankiconnect_port (INTEGER DEFAULT 8765)
├── anki_profile_name (VARCHAR(255))
├── connection_status (TEXT CHECK (connection_status IN ('connected', 'disconnected', 'error')))
├── last_connection_test (TIMESTAMP)
├── api_version (VARCHAR(20))
├── auto_connect_on_startup (BOOLEAN DEFAULT TRUE)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 51. anki_deck_mappings

**Purpose**: Map Anki decks to subject nodes

```sql
anki_deck_mappings
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── anki_deck_name (VARCHAR(255) NOT NULL)
├── subject_node_id (INTEGER REFERENCES subject_nodes(id))
├── mapping_confidence (DECIMAL(5,2))
├── is_active (BOOLEAN DEFAULT TRUE)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

---

### 52. anki_deck_configurations

**Purpose**: Configure which Anki decks to cache

```sql
anki_deck_configurations
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── anki_deck_name (VARCHAR(255) NOT NULL)
├── include_in_cache (BOOLEAN DEFAULT TRUE)
├── map_to_subject_node_id (INTEGER REFERENCES subject_nodes(id))
├── deck_priority (INTEGER DEFAULT 1)
├── last_cached_at (TIMESTAMP)
├── cache_status (TEXT CHECK (cache_status IN ('active', 'inactive', 'error')))
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

---

### 53. anki_realtime_cache

**Purpose**: Cached Anki card data for performance

```sql
anki_realtime_cache
├── user_id (INTEGER NOT NULL)
├── card_id (BIGINT NOT NULL)
├── note_id (BIGINT NOT NULL)
├── deck_name (VARCHAR(255))
├── card_question (TEXT)
├── card_answer (TEXT)
├── card_tags (TEXT CHECK (json_valid(card_tags)))
├── due_date (DATE)
├── ease_factor (INTEGER)
├── interval_days (INTEGER)
├── review_count (INTEGER)
├── lapse_count (INTEGER)
├── card_type (INTEGER)
├── card_queue (INTEGER)
├── last_review_date (DATE)
├── total_study_time_ms (BIGINT)
├── cached_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── needs_refresh (BOOLEAN DEFAULT FALSE)
└── PRIMARY KEY (user_id, card_id)
```

---

### 54. anki_tag_mappings

**Purpose**: Map local tags to Anki tags

```sql
anki_tag_mappings
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── local_tag_id (INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE)
├── anki_tag_pattern (VARCHAR(255) NOT NULL)
├── anki_deck_filter (VARCHAR(255))
├── mapping_type (TEXT CHECK (mapping_type IN ('exact_match', 'contains', 'regex')))
├── is_active (BOOLEAN DEFAULT TRUE)
├── user_approved (BOOLEAN DEFAULT FALSE) -- User must approve all mappings
├── auto_detected (BOOLEAN DEFAULT FALSE) -- Was this mapping suggested by system?
├── approved_at (TIMESTAMP NULL)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

### 55. outline_versions

**Purpose**: Track different versions of exam content outlines

```sql
outline_versions
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── exam_context (VARCHAR(100) NOT NULL)
├── outline_type (TEXT CHECK (outline_type IN ('content', 'competency', 'integrated', 'user_defined')))
├── version_name (VARCHAR(50) NOT NULL)
├── effective_date (DATE NOT NULL)
├── deprecated_date (DATE)
├── source_document_name (VARCHAR(255))
├── source_document_url (VARCHAR(500))
├── is_current (BOOLEAN DEFAULT FALSE)
├── migration_notes (TEXT)
├── total_topics (INTEGER DEFAULT 0)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

CREATE UNIQUE INDEX idx_unique_outline_version ON outline_versions (exam_context, outline_type, version_name);
CREATE INDEX idx_current_outlines ON outline_versions (exam_context, outline_type, is_current) WHERE is_current = TRUE;
```

---

### 56. weight_distribution_rules

**Purpose**: Define how weights cascade through the hierarchy

```sql
weight_distribution_rules
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── exam_context (VARCHAR(100) NOT NULL)
├── outline_type (TEXT CHECK (outline_type IN ('content', 'competency', 'integrated', 'user_defined')))
├── distribution_method (TEXT CHECK (distribution_method IN ('equal_split', 'manual', 'proportional_to_items')) DEFAULT 'equal_split')
├── parent_weight_inheritance_fraction (DECIMAL(3,2) DEFAULT 1.0 CHECK (parent_weight_inheritance_fraction BETWEEN 0.0 AND 1.0))
├── auto_recalculate_on_change (BOOLEAN DEFAULT TRUE)
├── round_weights_to_decimal_places (INTEGER DEFAULT 2)
├── is_active (BOOLEAN DEFAULT TRUE)
├── notes (TEXT)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

CREATE UNIQUE INDEX idx_unique_weight_rules ON weight_distribution_rules (exam_context, outline_type) WHERE is_active = TRUE;
```

---

### 57. user_exam_contexts

**Purpose**: To store the exams the user is studying for, the users goal for the exam, and exam date.

```sql
user_exam_contexts
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── user_id (INTEGER NOT NULL)
├── exam_context_code (VARCHAR(100) UNIQUE NOT NULL) -- "SAT", "GRE", "LSAT", "USMLE_Step1"
├── exam_full_name (VARCHAR(255) NOT NULL) -- "SAT Reasoning Test"
├── exam_date (DATE) -- Actual exam date (if scheduled)
├── exam_organization (VARCHAR(255)) -- "College Board", "ETS", "NBME"
├── is_active (BOOLEAN DEFAULT TRUE) -- Currently studying for this exam
├── priority_level (INTEGER CHECK (priority_level BETWEEN 1 AND 5))
├── notes (TEXT)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── archived_at (TIMESTAMP NULL) -- When user finished/stopped preparing
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

CREATE UNIQUE INDEX idx_unique_exam_context_per_user ON user_exam_contexts (user_id, exam_context_code);
CREATE INDEX idx_active_exam_contexts ON user_exam_contexts (user_id, is_active) WHERE is_active = TRUE;
```

---

### 58. exam_outline_requirements

**Purpose**: Define which outline types are required for each exam and their selection order

```sql
exam_outline_requirements
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── exam_context (VARCHAR(100) NOT NULL)
├── outline_type (TEXT CHECK (outline_type IN ('content', 'competency', 'integrated', 'user_defined')))
├── is_required (BOOLEAN DEFAULT TRUE)
├── selection_order (INTEGER NOT NULL) -- Order in which user selects from outlines (1, 2, 3...)
├── weight_percentage (DECIMAL(5,2) CHECK (weight_percentage BETWEEN 0 AND 100))
├── allow_multiple_selections (BOOLEAN DEFAULT TRUE)
├── min_selections (INTEGER DEFAULT 1)
├── max_selections (INTEGER)
├── validation_message (TEXT) -- Message shown if requirement not met
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

CREATE UNIQUE INDEX idx_unique_exam_outline_req ON exam_outline_requirements (exam_context, outline_type);
CREATE INDEX idx_outline_selection_order ON exam_outline_requirements (exam_context, selection_order);
```
---

### 59. outline_migration_mappings

**Purpose**: Track outline version migrations and node mappings

```sql
outline_migration_mappings
├── id (INTEGER PRIMARY KEY AUTOINCREMENT)
├── exam_context (VARCHAR(100) NOT NULL)
├── outline_type (TEXT CHECK (outline_type IN ('content', 'competency', 'integrated', 'user_defined')))
├── old_version (VARCHAR(20) NOT NULL)
├── new_version (VARCHAR(20) NOT NULL)
├── old_node_id (INTEGER REFERENCES subject_nodes(id))
├── new_node_id (INTEGER REFERENCES subject_nodes(id))
├── mapping_type (TEXT CHECK (mapping_type IN ('exact_match', 'renamed', 'merged', 'split', 'deprecated', 'new_topic')))
├── confidence_score (DECIMAL(3,2) CHECK (confidence_score BETWEEN 0 AND 1))
├── user_verified (BOOLEAN DEFAULT FALSE)
├── verified_at (TIMESTAMP)
├── notes (TEXT)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

CREATE INDEX idx_migration_mappings ON outline_migration_mappings (exam_context, outline_type, old_version, new_version);
CREATE INDEX idx_unverified_migrations ON outline_migration_mappings (user_verified, confidence_score) WHERE user_verified = FALSE;
```

---

## Summary Statistics

**Total Tables Designed: 67** (Updated for Phase 4)

**Master Database (users.db): 9 tables**
- User management and relationships
- Cross-user features (calendar sharing, permissions)
- Application-level settings
- Backup tracking

**Individual User Databases: 58 tables per user** (6 new Phase 4 tables added)
- User preferences and configurations (10 tables)
- Subject hierarchy (5 tables) **[+3 Phase 2 tables]**
- Question analysis and learning (9 tables)
- Tagging system (6 tables) **[enhanced with hierarchy columns]**
- Study sessions (4 tables)
- Calendar and planning (13 tables)
- AnkiConnect integration (5 tables)
- Supporting/analytics (11 tables)
- **Question Entry System (6 tables) [NEW - Phase 4]**
  - question_sources (enhanced)
  - review_sessions
  - question_entries
  - entry_subject_mappings
  - entry_tags
  - entry_media

---

## Tables Still Requiring Design or Revision

Based on comprehensive revision list:
1. **progress_tracking** - Long-term analytics
2. **study_goals** - User objectives and milestones
3. **notification_queue** - Cross-window notifications
4. Tables requiring revision/simplification per revision list

---

## File Organization (Continued)

```
Project Structure:
app_data/
├── users.db (Master Database - 9 tables)
├── user_databases/
│   ├── user_001_john.db (45 tables)
│   ├── user_002_sarah.db (45 tables)
│   └── user_003_mike.db (45 tables)
├── migrations/
│   ├── 1.0.0_to_1.1.0_add_calendar_urgency.sql
│   ├── 1.1.0_to_1.2.0_add_anki_fsrs_fields.sql
│   └── migration_manifest.json
├── exports/
│   ├── hierarchies/
│   ├── reports/
│   └── ical/
├── backups/
│   ├── master_db/
│   │   └── users_backup_20241201.db
│   └── user_databases/
│       ├── user_001_john_backup_20241201.db
│       └── user_002_sarah_backup_20241201.db
└── logs/
    ├── application.log
    ├── migration.log
    └── sync.log
```

---

## Index Strategy Summary

### Master Database Indexes
```sql
-- users table
CREATE UNIQUE INDEX idx_single_primary_admin ON users (is_primary_admin) WHERE is_primary_admin = TRUE;
CREATE INDEX idx_users_active ON users (account_status, last_active_at) WHERE account_status = 'active';
CREATE INDEX idx_users_cloud_sync ON users (cloud_sync_enabled, cloud_user_id) WHERE cloud_sync_enabled = TRUE;

-- power_user_relationships
CREATE UNIQUE INDEX idx_unique_power_user_relationship ON power_user_relationships (power_user_id, child_user_id);
```

### User Database Indexes
```sql
-- subject_nodes
CREATE UNIQUE INDEX idx_unique_exam_hierarchy ON subject_nodes (exam_context, name, parent_id);
CREATE INDEX idx_subject_nodes_exam_parent ON subject_nodes(exam_context, parent_id);
CREATE INDEX idx_subject_nodes_exam_level ON subject_nodes(exam_context, level_type);
CREATE INDEX idx_subject_nodes_weights ON subject_nodes(exam_weight_low, exam_weight_high);
CREATE INDEX idx_subject_nodes_status ON subject_nodes(status, exam_context);

-- tags
CREATE UNIQUE INDEX idx_unique_tag_per_exam ON tags (exam_context, tag_name);
CREATE INDEX idx_tags_exam_context ON tags(exam_context, tag_name);
CREATE INDEX idx_tags_category ON tags(tag_category, is_active);

-- question_tags
CREATE INDEX idx_question_tags_lookup ON question_tags(question_analysis_id, tag_id);
CREATE INDEX idx_question_tags_relevance ON question_tags(tag_id, relevance_score DESC);

-- Full-text search for templates
CREATE VIRTUAL TABLE IF NOT EXISTS template_search_index USING fts5(
    template_id,
    template_name,
    template_description,
    template_keywords,
    template_tags,
    content='event_templates'
);
```

---

## Data Validation Constraints Summary

### User Preferences Constraints
```sql
ALTER TABLE user_preferences ADD CONSTRAINT check_font_size_range 
    CHECK (font_size_scale BETWEEN 0.5 AND 3.0);

ALTER TABLE user_preferences ADD CONSTRAINT check_session_duration_range 
    CHECK (default_session_duration_minutes BETWEEN 15 AND 480);

ALTER TABLE user_preferences ADD CONSTRAINT check_break_intervals 
    CHECK (default_break_interval_minutes BETWEEN 5 AND 60 
           AND default_long_break_minutes BETWEEN 10 AND 60);

ALTER TABLE user_preferences ADD CONSTRAINT check_dashboard_refresh 
    CHECK (dashboard_auto_refresh_seconds BETWEEN 30 AND 3600);

ALTER TABLE user_preferences ADD CONSTRAINT check_calendar_slots 
    CHECK (calendar_time_slot_minutes IN (15, 30, 60));

ALTER TABLE user_preferences ADD CONSTRAINT check_child_weight_inheritance 
    CHECK (child_subject_weight_inheritance_fraction BETWEEN 0.1 AND 1.0);

ALTER TABLE user_preferences ADD CONSTRAINT check_entry_review_pagination 
    CHECK (entry_review_items_per_page BETWEEN 10 AND 100);

ALTER TABLE user_preferences ADD CONSTRAINT check_anki_port_range 
    CHECK (ankiconnect_port BETWEEN 1000 AND 65535);

ALTER TABLE user_preferences ADD CONSTRAINT check_anki_cache_interval 
    CHECK (anki_cache_refresh_interval_minutes BETWEEN 1 AND 1440);

ALTER TABLE user_preferences ADD CONSTRAINT check_backup_settings 
    CHECK (backup_frequency_hours BETWEEN 1 AND 168 
           AND backup_retention_days BETWEEN 7 AND 365);

ALTER TABLE user_preferences ADD CONSTRAINT check_realtime_delay 
    CHECK (realtime_update_delay_ms BETWEEN 100 AND 5000);
```

### Weight Configuration Constraints
```sql
ALTER TABLE user_weight_configurations ADD CONSTRAINT check_weight_factors_sum_to_one
    CHECK (ABS((weight_factor_exam_importance + weight_factor_recent_mistakes + 
               weight_factor_anki_performance + weight_factor_time_since_review) - 1.0) < 0.001);

ALTER TABLE user_weight_configurations ADD CONSTRAINT check_individual_weight_ranges
    CHECK (weight_factor_exam_importance BETWEEN 0.0 AND 1.0
           AND weight_factor_recent_mistakes BETWEEN 0.0 AND 1.0  
           AND weight_factor_anki_performance BETWEEN 0.0 AND 1.0
           AND weight_factor_time_since_review BETWEEN 0.0 AND 1.0);
```

### Relationship Constraints
```sql
-- Prevent self-relationships in power user system
ALTER TABLE power_user_relationships ADD CONSTRAINT no_self_relationship 
    CHECK (power_user_id != child_user_id);
```

---

## JSON Field Structures

### Common JSON Patterns Used Throughout

#### user_type (users table)
```json
["student", "power_user", "admin"]
```

#### permissions_granted (power_user_relationships)
```json
["view_analytics", "set_goals", "manage_calendar", "create_events"]
```

#### recurrence_pattern (calendar_events)
```json
{
    "frequency": "weekly",
    "interval": 1,
    "days": [1, 3, 5],
    "duration_weeks": 8,
    "start_date": "2024-09-15",
    "end_date": "2024-11-10"
}
```

#### resource_urls (calendar_events)
```json
[
    {
        "title": "Khan Academy Video",
        "url": "https://khanacademy.org/...",
        "type": "video"
    },
    {
        "title": "Practice Problems",
        "url": "https://example.com/problems",
        "type": "document"
    }
]
```

#### reminder_settings (calendar_events)
```json
[
    {
        "minutes_before": 1440,
        "channels": ["desktop", "system_tray"]
    },
    {
        "minutes_before": 60,
        "channels": ["desktop", "system_tray", "in_app"]
    }
]
```

#### rescheduling_options (event_tasks)
```json
{
    "retain_notes": true,
    "retain_time_estimate": false,
    "retain_subject_links": true,
    "retain_resource_urls": true,
    "reset_completion_status": true,
    "retain_priority": false
}
```

#### target_subject_nodes (event_tasks)
```json
[123, 456, 789]  // Array of subject_node_id values
```

#### trigger_conditions (tag_suggestion_rules)
```json
{
    "mistake_category": "time_pressure",
    "time_spent_on_question": {
        "operator": "<",
        "value": 60
    },
    "confidence_before_answer": {
        "operator": ">=",
        "value": 3
    }
}
```

#### widget_config (dashboard_widgets)
```json
{
    "chart_type": "line",
    "time_range": "last_30_days",
    "subjects": [123, 456],
    "show_legend": true,
    "color_scheme": "blue_gradient"
}
```

---

## Enum Value Documentation

### account_status (users)
- `active` - User can access the application
- `suspended` - Temporarily disabled by admin
- `disabled` - Permanently disabled
- `soft_deleted` - Marked for deletion, awaiting confirmation

### relationship_status (power_user_relationships)
- `pending` - Request sent, awaiting acceptance
- `active` - Relationship established and active
- `revocation_requested` - One party wants to end relationship
- `terminated` - Relationship ended

### mistake_category (question_analyses)
- `knowledge_gap` - Don't know the content
- `misread_question` - Didn't read carefully
- `silly_mistake` - Careless error
- `time_pressure` - Rushed due to time
- `misunderstanding` - Wrong conceptual understanding
- `memory_failure` - Forgot something known
- `calculation_error` - Arithmetic mistake
- `wrong_approach` - Used incorrect method
- `incomplete_solution` - Didn't finish
- `anxiety_related` - Stress affected performance
- `second_guessing` - Changed correct answer
- `elimination_error` - Wrong process of elimination
- `careless_mistake` - Simple oversight
- `focus_problem` - Distracted
- `fatigue_related` - Tired, low energy
- `poor_prioritization` - Time management issue
- `wrong_guess_strategy` - Bad guessing
- `test_strategy_error` - Poor test management

### tag_category (tags)
- `mistake_type` - Type of error made
- `study_method` - Learning approach needed
- `content_type` - Question characteristics
- `difficulty` - Personal difficulty assessment
- `strategy` - Test-taking strategies
- `personal` - Individual learning patterns
- `other` - Custom categories

### session_status (question_review_sessions)
- `active` - Session currently in progress
- `paused` - Session temporarily stopped
- `completed` - Session finished normally
- `abandoned` - Session ended without completion

### event_status (calendar_events)
- `scheduled` - Event planned for future
- `in_progress` - Event currently happening
- `completed` - Event finished
- `cancelled` - Event cancelled
- `rescheduled` - Event moved to different time

### task_status (event_tasks)
- `not_started` - Task not begun
- `in_progress` - Task being worked on
- `completed` - Task finished
- `skipped` - Task intentionally not done

### user_action (tag_suggestion_feedback)
- `accepted` - User agreed with suggestion
- `rejected` - User disagreed with suggestion
- `modified` - User changed the suggestion
- `ignored` - User didn't respond

### improvement_trend (mistake_patterns)
- `worsening` - Getting worse over time
- `stable` - No change
- `improving` - Getting better

### review_outcome (review_schedule)
- `still_confused` - Still don't understand
- `somewhat_clear` - Partial understanding
- `confident` - Good understanding
- `mastered` - Complete mastery

---

## Foreign Key Relationships

### Master Database Relationships
```
users (id) ← power_user_relationships (power_user_id)
users (id) ← power_user_relationships (child_user_id)
users (id) ← power_user_permission_requests (power_user_id)
users (id) ← power_user_permission_requests (child_user_id)
users (id) ← calendar_sharing (calendar_owner_id)
users (id) ← calendar_sharing (shared_with_user_id)
users (id) ← calendar_permission_requests (requesting_user_id)
users (id) ← calendar_permission_requests (target_user_id)
users (id) ← user_database_schemas (user_id)
users (id) ← app_settings (updated_by_user_id)
```

### User Database Relationships (Key Chains)

#### Subject Hierarchy Chain
```
subject_nodes (id) ← subject_nodes (parent_id) [self-referencing]
subject_nodes (id) ← question_topic_assignments (subject_node_id)
```

#### Question Analysis Chain
```
question_analyses (id) ← question_topic_assignments (question_analysis_id)
question_analyses (id) ← question_media (question_analysis_id)
question_analyses (id) ← question_tags (question_analysis_id)
question_analyses (id) ← learning_insights (question_analysis_id)
question_analyses (id) ← review_schedule (question_analysis_id)
question_analyses (id) ← session_question_analyses (question_analysis_id)
```

#### Tags Chain
```
tags (id) ← question_tags (tag_id)
tags (id) ← tag_analytics (tag_id)
tags (id) ← tag_relationships (tag_1_id)
tags (id) ← tag_relationships (tag_2_id)
tags (id) ← tag_suggestion_rules (suggested_tag_ids) [JSON array]
tags (id) ← tag_suggestion_feedback (suggested_tag_id)
tags (id) ← anki_tag_mappings (local_tag_id)
```

#### Session Chain
```
question_review_sessions (id) ← session_breaks (review_session_id)
question_review_sessions (id) ← session_question_analyses (review_session_id)
```

#### Calendar Chain
```
calendar_events (id) ← calendar_events (parent_recurring_event_id) [self-referencing]
calendar_events (id) ← calendar_events (rescheduled_from_event_id) [self-referencing]
calendar_events (id) ← event_tasks (calendar_event_id)
calendar_events (id) ← event_breaks (calendar_event_id)
calendar_events (id) ← event_suggestions (scheduled_to_event_id)
calendar_events (id) ← question_review_sessions (calendar_event_id)

event_templates (id) ← calendar_events (created_from_template_id)
event_templates (id) ← template_category_assignments (template_id)

template_categories (id) ← template_categories (parent_category_id) [self-referencing]
template_categories (id) ← template_category_assignments (category_id)

event_tasks (id) ← event_tasks (rescheduled_to_event_id) [self-referencing]
```

#### Dashboard Chain
```
dashboard_layouts (id) ← dashboard_widgets (dashboard_layout_id)
```

#### Export Chain
```
export_templates (id) ← export_template_fields (export_template_id)
export_templates (id) ← export_template_filters (export_template_id)
```

---

## Cascade Delete Behavior

### ON DELETE CASCADE (child records deleted automatically)
```sql
power_user_relationships: power_user_id, child_user_id → CASCADE
power_user_permission_requests: power_user_id, child_user_id → CASCADE
calendar_sharing: calendar_owner_id, shared_with_user_id → CASCADE
user_database_schemas: user_id → CASCADE

question_topic_assignments: question_analysis_id, subject_node_id → CASCADE
question_media: question_analysis_id → CASCADE
question_tags: question_analysis_id, tag_id → CASCADE
question_analyses: (parent to many children) → CASCADE

dashboard_widgets: dashboard_layout_id → CASCADE
export_template_fields: export_template_id → CASCADE
export_template_filters: export_template_id → CASCADE

session_breaks: review_session_id → CASCADE
session_question_analyses: review_session_id → CASCADE

event_tasks: calendar_event_id → CASCADE
event_breaks: calendar_event_id → CASCADE
template_category_assignments: template_id, category_id → CASCADE
```

### ON DELETE RESTRICT (prevent deletion if children exist)
Would apply to user management to prevent accidental data loss.

### ON DELETE SET NULL (orphan child records)
Not currently used in this schema; we prefer CASCADE or RESTRICT for data integrity.

---

## Timestamp and Audit Fields

### Standard Timestamps (most tables)
```sql
created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
```

### Deletion Tracking
```sql
deleted_at (TIMESTAMP NULL)
soft_deleted_at (TIMESTAMP NULL)
deletion_confirmed (BOOLEAN DEFAULT FALSE)
```

### Activity Tracking
```sql
last_active_at (TIMESTAMP)
last_used_at (TIMESTAMP)
last_interaction_at (TIMESTAMP)
last_synced_at (TIMESTAMP)
last_modified (TIMESTAMP)
```

### Review and Schedule Tracking
```sql
last_reviewed_at (TIMESTAMP)
scheduled_review_date (DATE)
actual_review_date (DATE)
```

---

## Cloud Sync Fields (Future-Proofing)

Present in most major tables for future cloud integration:

```sql
global_uuid (VARCHAR(36) UNIQUE)         -- Universal unique identifier
sync_status (VARCHAR(20) DEFAULT 'local') -- 'local', 'synced', 'conflict', 'pending'
last_synced_at (TIMESTAMP NULL)          -- When last synced to cloud
sync_version (INTEGER DEFAULT 1)         -- Version for conflict resolution
sync_hash (VARCHAR(64))                  -- Content hash for change detection
```

---

## Database Schema Versioning

### Current Schema Version
```
v1.0.0 - Initial release
```

### Migration Tracking
Each user database tracks its own schema version via:
- `user_database_schemas` table in master database
- `schema_migration_history` JSON field in users table

### Migration Process
1. Check user database schema version
2. If outdated, create backup
3. Apply migration scripts in sequence
4. Update schema version
5. Log migration completion

---

## Performance Considerations

### Indexing Strategy
- Primary keys on all tables (automatic B-tree indexes)
- Foreign key indexes for JOIN operations
- Composite indexes for common query patterns
- Full-text search indexes for templates

### Query Optimization
- Use indexed columns in WHERE clauses
- Avoid SELECT * when specific columns needed
- Use EXPLAIN QUERY PLAN for complex queries
- Consider materialized views for complex analytics

### Data Size Management
- Regular cleanup of soft-deleted records (after 30 days)
- Archive old review sessions (after 1 year)
- Compress backup files
- Monitor database file sizes

---

## Security Considerations

### Data Protection
- Optional database encryption per user
- Separate database files per user (data isolation)
- No plaintext password storage (future cloud auth)
- Secure file permissions on database files

### Access Control
- Power user permissions require mutual consent
- Granular permission levels for calendar sharing
- Audit trails via created_by and updated_by fields
- Soft deletion prevents accidental data loss

---

## Backup Strategy

### Automatic Backups
- Daily automatic backups (configurable per user)
- Backup before any schema migration
- Backup before bulk operations (imports, deletions)
- 30-day retention by default

### Backup Types
1. **Full database backup** - Complete copy of database file
2. **Granular table backups** - Individual table snapshots
3. **Migration backups** - Pre-migration state preservation
4. **Export backups** - User-initiated data exports

### Restore Process
1. Validate backup file integrity
2. Create current state backup before restore
3. Replace database file or tables
4. Verify schema compatibility
5. Update schema version if needed

---

## Known Limitations and Future Enhancements

### Current Limitations
1. Single Anki profile support (multi-profile planned for future)
2. Local-only operation (cloud sync in development)
3. SQLite limitations on concurrent writes (mitigated by single-user per database)

### Planned Enhancements
1. Full cloud synchronization with Supabase
2. Multi-device real-time updates
3. Advanced analytics and machine learning insights
4. Social features (study groups, shared question banks)
5. Mobile app integration

---

## Development Notes

### Database Creation Order
1. Create master database (users.db)
2. Initialize with app_settings
3. Create first user (primary admin)
4. Create user's database file
5. Populate with default data (level_types, tags, templates)

### Testing Strategy
- Unit tests for CRUD operations
- Integration tests for foreign key relationships
- Migration tests for schema updates
- Performance tests for common queries
- Data integrity tests for constraints

---

## Document Version
**Version:** 1.2  
**Last Updated:** December 26, 2025  
**Total Tables Documented:** 67 (Phase 4 update: +6 tables)  
**Database Architecture:** Multi-database (1 master + N user databases)

### Version History
- **v1.2** (Dec 26, 2025): Added 6 Phase 4 tables for Question Entry System: question_sources (enhanced), review_sessions, question_entries, entry_subject_mappings, entry_tags, entry_media. Added tag hierarchy columns.
- **v1.1** (Nov 7, 2025): Added 3 Phase 2 tables: exam_contexts, hierarchy_level_definitions, subject_node_weights
- **v1.0** (Dec 2024): Initial documentation of 58 tables

---

## Related Documentation
- Database Migration Guide (to be created)
- API Documentation (to be created)
- User Guide (to be created)
- Developer Setup Guide (exists: Project Wimi workflow.md)

---

END OF COMPLETED TABLES DOCUMENTATION
