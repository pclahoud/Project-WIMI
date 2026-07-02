"""Tests for user-DB migration v1 (baseline).

The baseline migration captures the cumulative pre-runner shape of the
per-user database. These tests verify the schema landing-place against
both fresh DBs and DBs that were partially populated before the runner
was introduced.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner
from database.migrations._helpers import (
    get_column_names,
    get_table_names,
    read_schema_file,
)
from database.migrations.user import m001_baseline


def _make_runner(conn: sqlite3.Connection) -> MigrationRunner:
    from database.migration_runner import build_migration

    return MigrationRunner(
        conn,
        registry=[build_migration(m001_baseline)],
        scope="user",
    )


def test_fresh_db_gets_full_v1_schema(fresh_conn):
    """Fresh DB → baseline runs → all the cumulative tables/columns exist."""
    _make_runner(fresh_conn).apply_pending()

    tables = get_table_names(fresh_conn)
    expected_tables = {
        # Phase 1
        "user_preferences",
        "subject_nodes",
        "question_analyses",
        "question_topic_assignments",
        "tags",
        "question_tags",
        # Subject aliases
        "subject_aliases",
        # Phase 2
        "exam_contexts",
        # Phase 4
        "question_sources",
        "review_sessions",
        "question_entries",
        "entry_subject_mappings",
        "entry_tags",
        "entry_media",
        # Decoupling
        "entry_media_mapping",
        # Phase 9
        "entry_notes",
        # Misc additive
        "saved_delimiters",
        "import_mapping_profiles",
        "session_timer_rounds",
        "plugin_data",
    }
    missing = expected_tables - tables
    assert not missing, f"baseline didn't create: {sorted(missing)}"

    # Column-level additions added on top of the bundled SQL.
    subject_cols = get_column_names(fresh_conn, "subject_nodes")
    assert "relative_weight" in subject_cols
    assert "weight_source" in subject_cols
    assert "weight_locked" in subject_cols
    assert "dimension_id" in subject_cols

    rs_cols = get_column_names(fresh_conn, "review_sessions")
    assert "session_duration_minutes" in rs_cols
    assert "total_break_seconds" in rs_cols
    assert "timer_paused_at" in rs_cols

    ec_cols = get_column_names(fresh_conn, "exam_contexts")
    assert "analytics_config" in ec_cols

    qe_cols = get_column_names(fresh_conn, "question_entries")
    assert "explanation_json" in qe_cols
    assert "reflection_json" in qe_cols
    assert "notes_json" in qe_cols

    em_cols = get_column_names(fresh_conn, "entry_media")
    assert "dimension_id" in em_cols
    assert "is_active" in em_cols
    assert "user_id" in em_cols


def test_baseline_is_idempotent(fresh_conn):
    """Running baseline twice does not error and does not change table count."""
    runner = _make_runner(fresh_conn)
    runner.apply_pending()

    tables_first = get_table_names(fresh_conn)

    # Manually re-invoke the upgrade against the same conn (bypass the
    # ledger so we actually re-execute the body, not just no-op via
    # ``pending()``).
    m001_baseline.upgrade(fresh_conn)

    tables_second = get_table_names(fresh_conn)
    assert tables_first == tables_second


def test_baseline_adopts_pre_runner_db_without_data_loss(fresh_conn):
    """Manually populate phase1 + insert a row; run baseline; row survives."""
    fresh_conn.executescript(read_schema_file("user_db_schema_v1_phase1.sql"))

    fresh_conn.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type) "
        "VALUES (?, ?, ?)",
        ("USMLE", "Cardiology", "Domain"),
    )
    fresh_conn.commit()

    pre_count = fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_nodes"
    ).fetchone()[0]
    assert pre_count == 1

    _make_runner(fresh_conn).apply_pending()

    # Original row survived:
    post_count = fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_nodes"
    ).fetchone()[0]
    assert post_count == 1

    surviving = fresh_conn.execute(
        "SELECT name FROM subject_nodes WHERE exam_context = 'USMLE'"
    ).fetchone()
    assert surviving[0] == "Cardiology"

    # New columns landed on the existing row:
    cols = get_column_names(fresh_conn, "subject_nodes")
    for col in ("relative_weight", "weight_source", "weight_locked", "dimension_id"):
        assert col in cols

    # weight_source backfill ran:
    src = fresh_conn.execute(
        "SELECT weight_source FROM subject_nodes WHERE name = 'Cardiology'"
    ).fetchone()[0]
    assert src == "user_defined"

    # New tables exist:
    tables = get_table_names(fresh_conn)
    assert "exam_contexts" in tables  # added by phase2 step
    assert "question_entries" in tables  # added by phase4 step
    assert "entry_notes" in tables  # added by phase9 step


def test_baseline_legacy_notes_migration(fresh_conn):
    """Legacy question_entries.notes rows get copied into entry_notes with is_migrated=1."""
    # Build only the subset we need: phase1 (for tags etc), phase2
    # (exam_contexts FK target), phase4 (sessions, question_entries).
    fresh_conn.executescript(read_schema_file("user_db_schema_v1_phase1.sql"))
    fresh_conn.executescript(read_schema_file("user_db_schema_v1_phase2.sql"))
    fresh_conn.executescript(read_schema_file("user_db_schema_v1_phase4.sql"))

    fresh_conn.execute(
        "INSERT INTO exam_contexts (user_id, exam_name) VALUES (1, 'USMLE Step 1')"
    )
    fresh_conn.execute(
        "INSERT INTO review_sessions "
        "(user_id, exam_context_id, total_questions, total_incorrect) "
        "VALUES (1, 1, 10, 3)"
    )
    fresh_conn.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer, notes) "
        "VALUES (1, 1, 'A', 'B', 'legacy text')"
    )
    fresh_conn.commit()

    _make_runner(fresh_conn).apply_pending()

    rows = fresh_conn.execute(
        "SELECT question_entry_id, content_html, is_migrated FROM entry_notes"
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == 1
    assert row[1] == "legacy text"
    assert row[2] == 1


def test_baseline_uses_legacy_user_db_path(legacy_user_db_path):
    """Quick smoke that the legacy_user_db_path fixture lands a fully-migrated DB."""
    conn = sqlite3.connect(str(legacy_user_db_path))
    try:
        applied = {
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }
        # Baseline must be present; later versions present too since the
        # full registry is wired into UserDatabase.__init__.
        assert 1 in applied

        tables = get_table_names(conn)
        assert "subject_nodes" in tables
        assert "entry_notes" in tables
    finally:
        conn.close()
