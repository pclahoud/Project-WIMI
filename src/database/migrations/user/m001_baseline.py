"""User DB baseline (v1).

Captures the cumulative state of the per-user database as of the
introduction of the migration runner. Ports the logic that previously
lived in ``SchemaMigrationMixin._ensure_phase{1,2,4}_schema`` plus the
column-and-table-patches those methods chained:

- Phase 1 core: user_preferences, subject_nodes, question_analyses,
  question_topic_assignments, tags, question_tags
- Hybrid weight columns on subject_nodes
- dimension_id on subject_nodes
- subject_aliases table
- 23 preference columns added over time
- Phase 2: exam_contexts, hierarchy_level_definitions, subject_node_weights
- Phase 4: question_sources, review_sessions, question_entries,
  entry_subject_mappings, entry_tags, entry_media
- Tags hierarchy columns (parent_id, is_group, display_order)
- entry_media columns (dimension_id, is_active, user_id)
- entry_media_mapping junction table + backfill + view rewrite
- Rich text JSON columns on question_entries (Phase 8)
- entry_notes table + legacy notes migration (Phase 9)
- saved_delimiters, import_mapping_profiles, session_timer_rounds
- session_duration_minutes, total_break_seconds, timer_paused_at
- analytics_config on exam_contexts
- plugin_data table

For users on a pre-runner DB the schema files use ``CREATE TABLE IF NOT
EXISTS`` and the column adds use ``add_column_if_missing``, so this is
idempotent — running it against a populated DB no-ops every step.
"""
from __future__ import annotations

import sqlite3

from .._helpers import (
    add_column_if_missing,
    get_column_names,
    get_table_names,
    run_schema_script,
)

VERSION = 1
NAME = "baseline"


def upgrade(conn: sqlite3.Connection) -> None:
    # ---- Phase 1: core tables ----
    run_schema_script(conn, "user_db_schema_v1_phase1.sql")

    # ---- Hybrid weight columns on subject_nodes ----
    added_weight_cols = False
    for col, defn in [
        ("relative_weight", "REAL"),
        ("weight_source", "VARCHAR(50) DEFAULT 'user_defined'"),
        ("weight_locked", "BOOLEAN DEFAULT FALSE"),
    ]:
        if add_column_if_missing(conn, "subject_nodes", col, defn):
            added_weight_cols = True
    if added_weight_cols:
        conn.execute(
            "UPDATE subject_nodes SET weight_source = 'user_defined', weight_locked = FALSE "
            "WHERE weight_source IS NULL"
        )

    # ---- dimension_id on subject_nodes (multi-dim hierarchies) ----
    if add_column_if_missing(conn, "subject_nodes", "dimension_id", "INTEGER"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_subject_nodes_dimension "
            "ON subject_nodes(dimension_id)"
        )

    # ---- subject_aliases table ----
    if "subject_aliases" not in get_table_names(conn):
        run_schema_script(conn, "user_db_schema_v1_subject_aliases.sql")

    # ---- 23 preference columns added incrementally over time ----
    _ensure_preferences_columns(conn)

    # ---- Phase 2 ----
    run_schema_script(conn, "user_db_schema_v1_phase2.sql")

    # ---- Phase 4 ----
    run_schema_script(conn, "user_db_schema_v1_phase4.sql")

    # ---- Tags hierarchy columns ----
    add_column_if_missing(
        conn, "tags", "parent_id", "INTEGER REFERENCES tags(id) NULL"
    )
    add_column_if_missing(conn, "tags", "is_group", "BOOLEAN DEFAULT FALSE")
    add_column_if_missing(conn, "tags", "display_order", "INTEGER DEFAULT 0")

    # ---- entry_media: dimension_id, is_active ----
    add_column_if_missing(conn, "entry_media", "dimension_id", "INTEGER NULL")
    add_column_if_missing(conn, "entry_media", "is_active", "INTEGER DEFAULT 1")

    # ---- entry_media decoupling: junction table + backfill + view ----
    _ensure_media_decoupling(conn)

    # ---- Phase 8 rich-text JSON columns on question_entries ----
    for col in ("explanation_json", "reflection_json", "notes_json"):
        add_column_if_missing(conn, "question_entries", col, "TEXT")

    # ---- review_sessions: timer + duration columns ----
    # NOTE: must precede the timer_rounds table block below — the legacy
    # session migration there reads ``review_sessions.total_break_seconds``.
    add_column_if_missing(
        conn, "review_sessions", "session_duration_minutes", "INTEGER DEFAULT NULL"
    )
    add_column_if_missing(
        conn, "review_sessions", "total_break_seconds", "INTEGER DEFAULT 0"
    )
    add_column_if_missing(
        conn, "review_sessions", "timer_paused_at", "TEXT DEFAULT NULL"
    )

    # ---- exam_contexts.analytics_config ----
    add_column_if_missing(
        conn, "exam_contexts", "analytics_config", "TEXT DEFAULT NULL"
    )

    # ---- Phase 9 entry_notes table + legacy notes migration ----
    if "entry_notes" not in get_table_names(conn):
        run_schema_script(conn, "user_db_schema_v1_phase9_notes.sql")
        if "question_entries" in get_table_names(conn):
            _migrate_legacy_notes(conn)

    # ---- saved_delimiters, import_mapping_profiles, session_timer_rounds ----
    if "saved_delimiters" not in get_table_names(conn):
        run_schema_script(conn, "user_db_schema_v1_saved_delimiters.sql")
    if "import_mapping_profiles" not in get_table_names(conn):
        run_schema_script(conn, "user_db_schema_v1_import_mappings.sql")
    if "session_timer_rounds" not in get_table_names(conn):
        run_schema_script(conn, "user_db_schema_v1_timer_rounds.sql")
        if "review_sessions" in get_table_names(conn):
            _migrate_existing_timed_sessions(conn)

    # ---- Plugin data table ----
    if "plugin_data" not in get_table_names(conn):
        run_schema_script(conn, "user_db_schema_v1_plugin_data.sql")


# ---------------------------------------------------------------------- helpers
# These are kept as private helpers within this migration so a checksum
# captures all the logic, not just the top-level upgrade() body. Future
# migrations can rewrite or supersede them without touching this file.


def _ensure_preferences_columns(conn: sqlite3.Connection) -> None:
    """Add the 23 preference columns that accumulated incrementally."""
    if "user_preferences" not in get_table_names(conn):
        return
    for col, defn in [
        ("primary_color_hex", "VARCHAR(7) DEFAULT '#2196F3'"),
        ("secondary_color_hex", "VARCHAR(7) DEFAULT '#FFC107'"),
        ("font_family", "VARCHAR(50) DEFAULT 'system'"),
        ("ui_density", "VARCHAR(20) DEFAULT 'comfortable'"),
        ("manual_break_control", "BOOLEAN DEFAULT 1"),
        ("analytics_detail_level", "VARCHAR(20) DEFAULT 'detailed'"),
        ("show_performance_trends", "BOOLEAN DEFAULT 1"),
        ("show_mistake_patterns", "BOOLEAN DEFAULT 1"),
        ("show_subject_breakdown", "BOOLEAN DEFAULT 1"),
        ("show_time_analytics", "BOOLEAN DEFAULT 1"),
        ("show_weekend_in_calendar", "BOOLEAN DEFAULT 1"),
        ("anki_integration_enabled", "BOOLEAN DEFAULT 0"),
        ("auto_backup_enabled", "BOOLEAN DEFAULT 1"),
        ("cloud_sync_enabled", "BOOLEAN DEFAULT 0"),
        ("entry_review_default_sort_field", "VARCHAR(50) DEFAULT 'answered_incorrectly_date'"),
        ("entry_review_default_sort_direction", "VARCHAR(10) DEFAULT 'desc'"),
        ("long_break_interval_rounds", "INTEGER DEFAULT 4"),
        ("timer_display_size", "TEXT DEFAULT 'normal'"),
        ("hotkey_timer_pause_resume", "TEXT DEFAULT 'Alt+P'"),
        ("hotkey_timer_new_round", "TEXT DEFAULT 'Alt+N'"),
        ("hotkey_timer_end_round", "TEXT DEFAULT 'Alt+E'"),
        ("mcp_server_enabled", "BOOLEAN DEFAULT 0"),
        ("mcp_server_port", "INTEGER DEFAULT 8000"),
    ]:
        add_column_if_missing(conn, "user_preferences", col, defn)


def _ensure_media_decoupling(conn: sqlite3.Connection) -> None:
    """Create entry_media_mapping junction, backfill, add user_id, rewrite summary view."""
    tables = get_table_names(conn)
    if "entry_media_mapping" in tables or "entry_media" not in tables:
        # Either already decoupled, or entry_media doesn't exist yet (fresh DB
        # before phase4 ran — but we always run phase4 above, so this branch
        # is theoretical defensive code).
        return

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entry_media_mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_entry_id INTEGER NOT NULL
                REFERENCES question_entries(id) ON DELETE CASCADE,
            media_id INTEGER NOT NULL
                REFERENCES entry_media(id) ON DELETE CASCADE,
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_emm_entry "
        "ON entry_media_mapping(question_entry_id, sort_order)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_emm_media "
        "ON entry_media_mapping(media_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_emm_unique "
        "ON entry_media_mapping(question_entry_id, media_id)"
    )

    # Backfill from the legacy entry_media.question_entry_id column.
    conn.execute(
        """
        INSERT OR IGNORE INTO entry_media_mapping
            (question_entry_id, media_id, sort_order, is_active)
        SELECT question_entry_id, id, sort_order, COALESCE(is_active, 1)
        FROM entry_media
        WHERE question_entry_id IS NOT NULL
        """
    )

    # Add user_id column to entry_media and backfill from session join.
    if "user_id" not in get_column_names(conn, "entry_media"):
        conn.execute("ALTER TABLE entry_media ADD COLUMN user_id INTEGER")
        conn.execute(
            """
            UPDATE entry_media SET user_id = (
                SELECT rs.user_id
                FROM question_entries qe
                JOIN review_sessions rs ON qe.review_session_id = rs.id
                WHERE qe.id = entry_media.question_entry_id
            )
            WHERE question_entry_id IS NOT NULL AND user_id IS NULL
            """
        )

    # Rewrite v_question_entry_summary to use the junction table.
    conn.execute("DROP VIEW IF EXISTS v_question_entry_summary")
    conn.execute(
        """
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
            (SELECT COUNT(*) FROM entry_subject_mappings esm
             WHERE esm.question_entry_id = qe.id
             AND esm.mapping_type = 'primary') as primary_subject_count,
            (SELECT COUNT(*) FROM entry_subject_mappings esm
             WHERE esm.question_entry_id = qe.id
             AND esm.mapping_type = 'secondary') as secondary_subject_count,
            (SELECT COUNT(*) FROM entry_tags et
             WHERE et.question_entry_id = qe.id) as tag_count,
            (SELECT COUNT(*) FROM entry_media_mapping emm
             WHERE emm.question_entry_id = qe.id
             AND emm.is_active = 1) as media_count
        FROM question_entries qe
        """
    )


def _migrate_legacy_notes(conn: sqlite3.Connection) -> None:
    """Copy legacy ``question_entries.notes`` rows into ``entry_notes``."""
    cursor = conn.execute(
        "SELECT id, notes, notes_json FROM question_entries "
        "WHERE notes IS NOT NULL AND notes != ''"
    )
    rows = cursor.fetchall()
    for row in rows:
        entry_id, notes, notes_json = row[0], row[1], row[2]
        existing = conn.execute(
            "SELECT id FROM entry_notes WHERE question_entry_id = ? AND is_migrated = 1",
            (entry_id,),
        ).fetchone()
        if existing is not None:
            continue
        conn.execute(
            "INSERT INTO entry_notes "
            "(question_entry_id, content_html, content_json, sort_order, is_migrated) "
            "VALUES (?, ?, ?, 0, 1)",
            (entry_id, notes, notes_json),
        )


def _migrate_existing_timed_sessions(conn: sqlite3.Connection) -> None:
    """Create round 1 for legacy timed sessions that pre-date the timer_rounds table."""
    cursor = conn.execute(
        """
        SELECT id, started_at, total_break_seconds, timer_paused_at,
               session_duration_minutes
        FROM review_sessions
        WHERE session_duration_minutes IS NOT NULL
          AND id NOT IN (
              SELECT review_session_id FROM session_timer_rounds
              WHERE round_number = 1
          )
        """
    )
    for row in cursor.fetchall():
        sid, started_at, break_secs, paused_at, duration = row
        conn.execute(
            """
            INSERT INTO session_timer_rounds
                (review_session_id, round_number, duration_minutes,
                 started_at, total_break_seconds, timer_paused_at)
            VALUES (?, 1, ?, ?, ?, ?)
            """,
            (sid, duration, started_at, break_secs or 0, paused_at),
        )
