"""Tests for user-DB migration v20 (``subject_nodes.import_id``).

m020 lands the column issue #67 matches re-imports on. Three things are
worth pinning, because each of them encodes a decision that a later
"tidy-up" could quietly reverse:

- The column is **nullable and not backfilled**. Every subject created in
  the tree editor has no import id, and so does every subject imported
  before the field existed. A synthetic backfill would claim ids no file
  will ever mention, and the first real file would then find every
  subject already spoken for.
- The unique index is scoped to **exam context plus dimension**, not
  global. Two exams may legitimately both call a subject ``"1.2.3"``.
- The index is **active-only**. Deletion is soft, so a subject an import
  removed keeps its row and its id; re-importing a file that lists it
  again must be free to create it rather than fail on an index shared
  with a row nothing can see.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names
from database.migrations.user import MIGRATIONS


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v19(conn: sqlite3.Connection) -> MigrationRunner:
    """A database from just before the import merge landed."""
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version <= 19],
        scope="user",
    )


def _ledger_versions(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def _subject(conn, name, *, import_id=None, exam="USMLE", dimension=None,
             status="active"):
    return conn.execute(
        "INSERT INTO subject_nodes "
        "(exam_context, name, level_type, import_id, dimension_id, status) "
        "VALUES (?, ?, 'Topic', ?, ?, ?)",
        (exam, name, import_id, dimension, status),
    ).lastrowid


# ---------------------------------------------------------------- tests


def test_registry_has_v20_and_keeps_the_gaps():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert 20 in versions
    # m008 is reserved for the assessments branch; v11-v14 are stamped
    # into real databases by the capture feature branch (paused, #145), and the runner
    # treats a stamped version as applied.
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[20] == "subject_import_id"


def test_pre_v20_database_has_no_import_id_column(fresh_conn):
    _runner_through_v19(fresh_conn).apply_pending()
    assert 'import_id' not in get_column_names(fresh_conn, 'subject_nodes')


def test_apply_pending_adds_the_column_and_stamps_the_ledger(fresh_conn):
    _runner_through_v19(fresh_conn).apply_pending()
    _full_runner(fresh_conn).apply_pending()

    assert 'import_id' in get_column_names(fresh_conn, 'subject_nodes')
    assert 20 in _ledger_versions(fresh_conn)


def test_existing_subjects_are_left_without_an_id(fresh_conn):
    _runner_through_v19(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type) "
        "VALUES ('USMLE', 'Cardiovascular', 'System')"
    )
    fresh_conn.commit()

    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT import_id FROM subject_nodes WHERE name = 'Cardiovascular'"
    ).fetchone()
    assert row['import_id'] is None, (
        "the migration invented an id for a subject no file had named"
    )


def test_applying_twice_is_a_no_op(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    _full_runner(fresh_conn).apply_pending()
    assert 'import_id' in get_column_names(fresh_conn, 'subject_nodes')


def test_two_active_subjects_cannot_share_an_id_in_one_scope(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    _subject(fresh_conn, "First", import_id="1.2.3")

    with pytest.raises(sqlite3.IntegrityError):
        _subject(fresh_conn, "Second", import_id="1.2.3")


def test_the_same_id_is_free_in_another_exam_or_dimension(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    _subject(fresh_conn, "First", import_id="1.2.3")
    _subject(fresh_conn, "Other exam", import_id="1.2.3", exam="MCAT")
    _subject(fresh_conn, "Other dimension", import_id="1.2.3", dimension=7)
    fresh_conn.commit()

    count = fresh_conn.execute(
        "SELECT COUNT(*) AS c FROM subject_nodes WHERE import_id = '1.2.3'"
    ).fetchone()['c']
    assert count == 3


def test_an_archived_subject_does_not_hold_its_id_against_a_new_one(fresh_conn):
    """Deletion is soft, so the removed row keeps its id forever.

    Without ``status = 'active'`` in the index predicate, re-importing a
    file that lists a subject a previous import removed would fail on a
    collision with a row the user cannot see or delete.
    """
    _full_runner(fresh_conn).apply_pending()
    _subject(fresh_conn, "Removed once", import_id="2.4", status="archived")

    _subject(fresh_conn, "Back again", import_id="2.4")
    fresh_conn.commit()


def test_null_ids_never_collide(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    for name in ("A", "B", "C"):
        _subject(fresh_conn, name)
    fresh_conn.commit()
