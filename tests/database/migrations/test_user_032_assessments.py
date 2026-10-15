"""Tests for user-DB migration v8 (psychometric assessment tables).

Stage 0 of the Psychometric Assessment Implementation Plan
(``docs/planning/PSYCHOMETRIC_ASSESSMENT_IMPLEMENTATION_PLAN.md``).
Verifies the three new tables, the partial in-flight index, the cadence
CHECK constraint, the UNIQUE on ``(assessment_id, item_code)``, the
ON DELETE CASCADE, and idempotency.
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
    m032_assessments,
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
            build_migration(m032_assessments),
        ],
        scope="user",
    )


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    return {row[0] for row in rows}


# ---------------------------------------------------------------- tests


def test_creates_three_tables(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    tables = _table_names(fresh_conn)
    assert "user_assessments" in tables
    assert "user_assessment_responses" in tables
    assert "user_assessment_preferences" in tables


def test_creates_in_flight_partial_index(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    assert "idx_user_assessments_in_flight" in _index_names(fresh_conn)
    # And confirm it's actually partial (WHERE clause survived).
    sql = fresh_conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='idx_user_assessments_in_flight'"
    ).fetchone()[0]
    assert "WHERE is_complete = 0" in sql


def test_creates_supporting_indices(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    indices = _index_names(fresh_conn)
    assert "idx_user_assessments_user_complete" in indices
    assert "idx_responses_assessment" in indices
    assert "idx_responses_by_item_code" in indices


def test_migration_is_idempotent(fresh_conn):
    """Re-running m032 against an already-migrated DB is a no-op."""
    _full_runner(fresh_conn).apply_pending()
    tables_before = _table_names(fresh_conn)
    indices_before = _index_names(fresh_conn)

    # Manually re-invoke the upgrade body — bypass the ledger so the
    # function actually runs again rather than no-op'ing via pending().
    m032_assessments.upgrade(fresh_conn)
    m032_assessments.upgrade(fresh_conn)

    assert _table_names(fresh_conn) == tables_before
    assert _index_names(fresh_conn) == indices_before


def test_cadence_check_rejects_too_low(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO user_assessment_preferences (user_id, cadence_days) "
            "VALUES (?, ?)",
            (1, 29),
        )


def test_cadence_check_rejects_too_high(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO user_assessment_preferences (user_id, cadence_days) "
            "VALUES (?, ?)",
            (1, 731),
        )


def test_cadence_check_accepts_default(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO user_assessment_preferences (user_id) VALUES (?)",
        (1,),
    )
    row = fresh_conn.execute(
        "SELECT cadence_days, snooze_count FROM user_assessment_preferences "
        "WHERE user_id = ?",
        (1,),
    ).fetchone()
    assert row[0] == 180
    assert row[1] == 0


def test_responses_unique_per_assessment_item(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO user_assessments (user_id, instrument_version) "
        "VALUES (?, ?)",
        (1, "v1"),
    )
    fresh_conn.execute(
        "INSERT INTO user_assessment_responses "
        "(assessment_id, item_code, raw_response) VALUES (?, ?, ?)",
        (1, "nfc_01", 3),
    )
    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO user_assessment_responses "
            "(assessment_id, item_code, raw_response) VALUES (?, ?, ?)",
            (1, "nfc_01", 4),
        )


def test_responses_cascade_delete(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO user_assessments (user_id, instrument_version) "
        "VALUES (?, ?)",
        (1, "v1"),
    )
    fresh_conn.execute(
        "INSERT INTO user_assessment_responses "
        "(assessment_id, item_code, raw_response) VALUES (?, ?, ?)",
        (1, "nfc_01", 3),
    )
    fresh_conn.execute("DELETE FROM user_assessments WHERE id = ?", (1,))
    count = fresh_conn.execute(
        "SELECT COUNT(*) FROM user_assessment_responses"
    ).fetchone()[0]
    assert count == 0


def test_default_is_complete_is_zero(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    cur = fresh_conn.execute(
        "INSERT INTO user_assessments (user_id, instrument_version) "
        "VALUES (?, ?)",
        (1, "v1"),
    )
    row = fresh_conn.execute(
        "SELECT is_complete, started_at FROM user_assessments WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    assert row[0] == 0
    assert row[1] is not None  # CURRENT_TIMESTAMP default fired


def test_registry_has_v32_and_keeps_the_gaps():
    """The registry snapshot, moved here from m031's test as it instructs.

    **A new migration will make this fail, and the fix is to MOVE these lines
    into its test, not to loosen them.** Carried m023 -> ... -> m031 -> here.

    m032 was pre-assigned on #766 when this feature resumed. **8 is in the
    skipped set because it was THIS migration's original number**: the work
    was authored as m008 on feat/psychometric-assessment and renumbered when
    the registry had already reached 31 -- a number below the maximum applies
    out of order, and v8 is reserved for the databases that took it from that
    branch. 29 stays skipped for the same monotonicity reason (see m030).
    """
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert versions[versions.index(32) - 1] == 31
    for skipped in (8, 11, 12, 13, 14, 29):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[32] == "assessments"
    # The max(versions) snapshot moved to m033's test, as instructed above.
