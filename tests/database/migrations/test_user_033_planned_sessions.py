"""Tests for user-DB migration v33 (planned sessions, templates, exam colour; #778 Wave 0).

Verifies the two new tables and their constraints, the partial unique index
on active template names (NULL exam coalesced), the occurrence uniqueness
per series, the series/occurrence exclusivity CHECK, ON DELETE behaviour,
the ``exam_contexts.color_hex`` column, idempotency, and the registry
snapshot moved here from m032's test.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner, build_migration
from database.migrations.user import (
    MIGRATIONS,
    m001_baseline,
    m002_phase6_goals,
    m003_phase7_dimensions,
    m004_subject_edges,
    m005_primary_parent_id,
    m006_subject_edge_weight_history,
    m007_exam_length_triple,
    m033_planned_sessions,
)


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(
        conn,
        registry=[
            build_migration(m001_baseline),
            build_migration(m002_phase6_goals),
            build_migration(m003_phase7_dimensions),
            build_migration(m004_subject_edges),
            build_migration(m005_primary_parent_id),
            build_migration(m006_subject_edge_weight_history),
            build_migration(m007_exam_length_triple),
            build_migration(m033_planned_sessions),
        ],
        scope="user",
    )


def _names(conn, kind):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type=?", (kind,))}


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _seed_exam(conn, user_id=1):
    cur = conn.execute("INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)", (user_id, "Exam"))
    return cur.lastrowid


@pytest.fixture
def migrated(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    return fresh_conn


def test_creates_both_tables_and_the_exam_colour_column(migrated):
    assert {"planned_sessions", "session_templates"} <= _names(migrated, "table")
    assert "color_hex" in _columns(migrated, "exam_contexts")
    assert {"idx_session_templates_active_name", "idx_planned_sessions_occurrence",
            "idx_planned_sessions_user_date", "idx_planned_sessions_due"} <= _names(migrated, "index")


def test_upgrade_is_idempotent(migrated):
    m033_planned_sessions.upgrade(migrated)
    m033_planned_sessions.upgrade(migrated)
    assert "planned_sessions" in _names(migrated, "table")


def test_planned_date_has_no_default(migrated):
    """#286: the day is written by Python, never defaulted by date('now')."""
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute("INSERT INTO planned_sessions (uid, user_id) VALUES ('u1', 1)")


def test_status_check_and_time_glob(migrated):
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, status) "
                         "VALUES ('u1', 1, '2026-10-14', 'done')")
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, planned_start_time) "
                         "VALUES ('u2', 1, '2026-10-14', '9am')")
    migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, planned_start_time) "
                     "VALUES ('u3', 1, '2026-10-14', '09:00')")


def test_a_row_cannot_be_both_a_series_and_an_occurrence(migrated):
    migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, recurrence_rule) "
                     "VALUES ('s', 1, '2026-10-13', 'FREQ=WEEKLY;BYDAY=TU')")
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, recurrence_rule, "
                         "recurrence_parent_id) VALUES ('x', 1, '2026-10-20', 'FREQ=WEEKLY', 1)")


def test_one_materialised_occurrence_per_series_and_date(migrated):
    migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, recurrence_rule) "
                     "VALUES ('s', 1, '2026-10-13', 'FREQ=WEEKLY;BYDAY=TU')")
    migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, recurrence_parent_id) "
                     "VALUES ('o1', 1, '2026-10-20', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, recurrence_parent_id) "
                         "VALUES ('o2', 1, '2026-10-20', 1)")


def test_deleting_a_series_cascades_to_its_occurrences(migrated):
    migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, recurrence_rule) "
                     "VALUES ('s', 1, '2026-10-13', 'FREQ=WEEKLY;BYDAY=TU')")
    migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, recurrence_parent_id) "
                     "VALUES ('o1', 1, '2026-10-20', 1)")
    migrated.execute("DELETE FROM planned_sessions WHERE id = 1")
    assert migrated.execute("SELECT COUNT(*) FROM planned_sessions").fetchone()[0] == 0


def test_deleting_the_real_session_sets_the_link_null(migrated):
    exam = _seed_exam(migrated)
    cur = migrated.execute(
        "INSERT INTO review_sessions (user_id, exam_context_id, date_encountered, total_questions, "
        "total_incorrect) VALUES (1, ?, '2026-10-14', 10, 2)", (exam,))
    migrated.execute("INSERT INTO planned_sessions (uid, user_id, exam_context_id, planned_date, status, "
                     "review_session_id) VALUES ('p', 1, ?, '2026-10-14', 'started', ?)", (exam, cur.lastrowid))
    migrated.execute("DELETE FROM review_sessions WHERE id = ?", (cur.lastrowid,))
    row = migrated.execute("SELECT status, review_session_id FROM planned_sessions").fetchone()
    assert row[0] == "started" and row[1] is None


def test_deleting_an_exam_cascades_plans_and_templates(migrated):
    exam = _seed_exam(migrated)
    migrated.execute("INSERT INTO planned_sessions (uid, user_id, exam_context_id, planned_date) "
                     "VALUES ('p', 1, ?, '2026-10-14')", (exam,))
    migrated.execute("INSERT INTO session_templates (user_id, exam_context_id, name) VALUES (1, ?, 'T')", (exam,))
    migrated.execute("DELETE FROM exam_contexts WHERE id = ?", (exam,))
    assert migrated.execute("SELECT COUNT(*) FROM planned_sessions").fetchone()[0] == 0
    assert migrated.execute("SELECT COUNT(*) FROM session_templates").fetchone()[0] == 0


def test_template_names_are_unique_over_active_rows_only_and_null_exam_counts(migrated):
    migrated.execute("INSERT INTO session_templates (user_id, name) VALUES (1, 'Morning')")
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute("INSERT INTO session_templates (user_id, name) VALUES (1, 'Morning')")
    migrated.execute("UPDATE session_templates SET is_active = 0 WHERE name = 'Morning'")
    # Archiving frees the name (#244's lesson, by partial index not parking).
    migrated.execute("INSERT INTO session_templates (user_id, name) VALUES (1, 'Morning')")
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute("INSERT INTO session_templates (user_id, name) VALUES (1, '   ')")


def test_updated_at_triggers_fire(migrated):
    migrated.execute("INSERT INTO planned_sessions (uid, user_id, planned_date, updated_at) "
                     "VALUES ('p', 1, '2026-10-14', '2000-01-01 00:00:00')")
    migrated.execute("UPDATE planned_sessions SET title = 'x' WHERE id = 1")
    assert migrated.execute("SELECT updated_at FROM planned_sessions").fetchone()[0] != "2000-01-01 00:00:00"


def test_registry_has_v33_and_keeps_the_gaps():
    """The registry snapshot, moved here from m032's test as it instructs.

    **A new migration will make this fail, and the fix is to MOVE these lines
    into its test, not to loosen them.** Carried m023 -> ... -> m032 -> here.

    m033 was pre-assigned on #778 (and m034 to #784's Anki work, which waits
    for this one to reach master because the runner has no ordering guard).
    8 and 29 stay skipped for the reasons m032's and m030's tests record.
    """
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert versions[versions.index(33) - 1] == 32
    for skipped in (8, 11, 12, 13, 14, 29):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[33] == "planned_sessions"
    # The max(versions) snapshot moved to m034's test, as instructed above.
