-- Import Mapping Profiles Schema
-- User-specific saved field mapping profiles for session import wizard

CREATE TABLE IF NOT EXISTS import_mapping_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'custom',
    field_mappings TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
