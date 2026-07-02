"""Tests for user-DB migration v7 (exam_contexts length triple).

Stage 4 of ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.
Verifies the five new columns, the kind-discriminant CHECK constraint,
the default value, and idempotency.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner, build_migration
from database.migrations._helpers import get_column_names
from database.migrations.user import (
    m001_baseline,
    m002_phase6_goals,
    m003_phase7_dimensions,
    m004_subject_edges,
    m005_primary_parent_id,
    m006_subject_edge_weight_history,
    m007_exam_length_triple,
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
        ],
        scope="user",
    )


def _seed_exam_context(conn: sqlite3.Connection, name: str = "Test Exam") -> int:
    """Insert a minimal exam_contexts row and return its id."""
    cur = conn.execute(
        "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
        (1, name),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------- tests


def test_migration_adds_all_five_columns(fresh_conn):
    """Fresh DB after m007 → all five length-triple columns present."""
    _full_runner(fresh_conn).apply_pending()

    cols = get_column_names(fresh_conn, "exam_contexts")
    assert "length_kind" in cols
    assert "length_min" in cols
    assert "length_max" in cols
    assert "length_typical" in cols
    assert "length_note" in cols


def test_default_length_kind_is_unknown(fresh_conn):
    """Existing exam_contexts rows default to length_kind='unknown'."""
    _full_runner(fresh_conn).apply_pending()
    exam_id = _seed_exam_context(fresh_conn)

    row = fresh_conn.execute(
        "SELECT length_kind, length_min, length_max, length_typical, length_note "
        "FROM exam_contexts WHERE id = ?",
        (exam_id,),
    ).fetchone()
    assert row[0] == 'unknown'
    assert row[1] is None
    assert row[2] is None
    assert row[3] is None
    assert row[4] is None


def test_check_accepts_all_three_kinds(fresh_conn):
    """The length_kind CHECK accepts each of fixed / range / unknown."""
    _full_runner(fresh_conn).apply_pending()

    for kind in ('fixed', 'range', 'unknown'):
        cur = fresh_conn.execute(
            "INSERT INTO exam_contexts (user_id, exam_name, length_kind) "
            "VALUES (?, ?, ?)",
            (1, f"Exam-{kind}", kind),
        )
        assert cur.lastrowid is not None
    fresh_conn.commit()


def test_check_rejects_unknown_kind(fresh_conn):
    """Sanity: the CHECK rejects values outside the discriminant enum."""
    _full_runner(fresh_conn).apply_pending()

    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO exam_contexts (user_id, exam_name, length_kind) "
            "VALUES (?, ?, ?)",
            (1, "Bad Exam", "totally_made_up_kind"),
        )


def test_migration_is_idempotent(fresh_conn):
    """Re-running m007 against an already-migrated DB is a no-op."""
    _full_runner(fresh_conn).apply_pending()
    cols_before = get_column_names(fresh_conn, "exam_contexts")

    # Manually re-invoke the upgrade body — bypass the ledger so the
    # function actually runs again rather than no-op'ing via pending().
    m007_exam_length_triple.upgrade(fresh_conn)
    m007_exam_length_triple.upgrade(fresh_conn)

    cols_after = get_column_names(fresh_conn, "exam_contexts")
    assert cols_before == cols_after

    # Still exactly one of each new column (would be a duplicate-add
    # error otherwise, swallowed by add_column_if_missing).
    for new_col in ("length_kind", "length_min", "length_max", "length_typical", "length_note"):
        count = sum(1 for c in cols_after if c == new_col)
        assert count == 1, f"column {new_col!r} appears {count}x after re-run"


def test_length_columns_writable_with_integers(fresh_conn):
    """Numeric INSERT/UPDATE roundtrips work for the integer columns."""
    _full_runner(fresh_conn).apply_pending()
    exam_id = _seed_exam_context(fresh_conn)

    fresh_conn.execute(
        "UPDATE exam_contexts SET length_kind=?, length_min=?, length_max=?, "
        "length_typical=?, length_note=? WHERE id = ?",
        ('range', 85, 150, 100, 'CAT exam', exam_id),
    )
    fresh_conn.commit()

    row = fresh_conn.execute(
        "SELECT length_kind, length_min, length_max, length_typical, length_note "
        "FROM exam_contexts WHERE id = ?",
        (exam_id,),
    ).fetchone()
    assert row[0] == 'range'
    assert row[1] == 85
    assert row[2] == 150
    assert row[3] == 100
    assert row[4] == 'CAT exam'
