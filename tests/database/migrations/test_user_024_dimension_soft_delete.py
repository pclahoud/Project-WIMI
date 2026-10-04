"""Tests for user-DB migration v24 — dimension soft delete and its journal.

#210. Two columns on ``exam_dimensions`` and two new tables.

Three properties beyond "the column exists":

* **`exam_dimensions` may be absent.** It is created by the legacy
  ``_ensure_phase7_schema``, not by a numbered migration, so a database that
  has never opened Phase 7 does not have it. The migration must not fail
  there, and the ensure path must then create the table *with* these columns
  — otherwise every status-filtered read breaks on exactly those databases.
* **Existing rows default to `'active'`.** A migration that left them NULL
  would make every dimension in every existing profile invisible at once,
  which is a worse bug than the one being fixed.
* **The journal is additive.** Spanning one batch across the dimension and
  subject levels would have meant relaxing ``subject_delete_batches.root_node_id``
  (NOT NULL, no dimension event has a root) and widening
  ``subject_delete_batch_items.item_type`` (a closed CHECK) — two rebuilds of
  tables holding real journal rows. This rebuilds nothing, and this test says
  so by asserting the old tables are untouched.
"""
from __future__ import annotations

import sqlite3

from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names
from database.migrations.user import MIGRATIONS


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v23(conn: sqlite3.Connection) -> MigrationRunner:
    """A database from just before #210 landed."""
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version <= 23],
        scope="user",
    )


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    }


def test_registry_has_v24_in_order():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert 24 in versions
    # The gaps stay gaps: v8 is the assessments branch, v11-v14 were
    # stamped into real databases by the paused AI-capture branch (#145).
    # Reusing one would silently skip a migration on any database that ran
    # those builds.
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions
    # The newest-migration claim has MOVED to m025's test, as the comment
    # here instructed when m025 landed (#66 2.3). Exactly one file holds it.



def test_it_adds_the_columns_when_the_table_exists(fresh_conn):
    _runner_through_v23(fresh_conn).apply_pending()
    # `fresh_conn` already carries a Phase 7 `exam_dimensions`. Replace it with
    # the pre-#210 shape, which is what a real database at v23 has.
    fresh_conn.execute("DROP TABLE IF EXISTS exam_dimensions")
    fresh_conn.execute(
        """
        CREATE TABLE exam_dimensions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            display_order INTEGER NOT NULL,
            UNIQUE(exam_id, display_order)
        )
        """
    )
    fresh_conn.execute(
        "INSERT INTO exam_dimensions (exam_id, name, display_order) "
        "VALUES (1, 'Site', 1)")

    _full_runner(fresh_conn).apply_pending()

    columns = get_column_names(fresh_conn, "exam_dimensions")
    assert "status" in columns
    assert "archived_batch_id" in columns


def test_an_existing_row_defaults_to_active(fresh_conn):
    """The row was written before the column existed.

    NULL here would hide every dimension in every existing profile the moment
    the reads started filtering — a worse bug than the one #210 fixes.
    """
    _runner_through_v23(fresh_conn).apply_pending()
    fresh_conn.execute("DROP TABLE IF EXISTS exam_dimensions")
    fresh_conn.execute(
        """
        CREATE TABLE exam_dimensions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            display_order INTEGER NOT NULL
        )
        """
    )
    fresh_conn.execute(
        "INSERT INTO exam_dimensions (exam_id, name, display_order) "
        "VALUES (1, 'Site', 1)")

    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT status FROM exam_dimensions WHERE name = 'Site'").fetchone()
    assert row[0] == 'active'


def test_it_survives_the_table_being_absent(fresh_conn):
    """`exam_dimensions` is created by the legacy ensure path, not a migration.

    A database that never opened Phase 7 does not have it, and the runner must
    still stamp v24 rather than raise.

    `fresh_conn` builds a Phase 7 database, so the absence has to be made
    rather than assumed -- which is itself worth knowing: the "may be absent"
    case is not what the standard fixture gives you.
    """
    _runner_through_v23(fresh_conn).apply_pending()
    fresh_conn.execute("DROP TABLE IF EXISTS exam_dimensions")

    _full_runner(fresh_conn).apply_pending()

    assert 'exam_dimensions' not in _tables(fresh_conn)
    stamped = {r[0] for r in fresh_conn.execute(
        "SELECT version FROM schema_migrations")}
    assert 24 in stamped


def test_the_journal_tables_are_created(fresh_conn):
    _full_runner(fresh_conn).apply_pending()

    tables = _tables(fresh_conn)
    assert 'dimension_delete_batches' in tables
    assert 'dimension_delete_batch_subjects' in tables

    link_columns = get_column_names(fresh_conn, 'dimension_delete_batch_subjects')
    # root_node_id is on the link, not only the subject batch, so #37 can say
    # which root a batch came from without joining back through it.
    assert {'dimension_batch_id', 'subject_batch_id', 'root_node_id'} <= set(
        link_columns)


def test_it_rebuilds_nothing(fresh_conn):
    """The whole argument for a separate journal table.

    The alternative needed two create-copy-drop-rename cycles over tables
    holding real journal rows. If a later change makes this migration rebuild
    `subject_delete_batches`, the trade it was chosen on no longer holds.
    """
    _runner_through_v23(fresh_conn).apply_pending()
    before = {
        name: sql
        for name, sql in fresh_conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'subject_delete%'")
    }
    assert before, 'the subject journal tables should exist by v23'

    _full_runner(fresh_conn).apply_pending()

    after = {
        name: sql
        for name, sql in fresh_conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'subject_delete%'")
    }
    assert after == before, 'm024 rebuilt a subject journal table'


def test_it_is_idempotent(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    _full_runner(fresh_conn).apply_pending()

    tables = _tables(fresh_conn)
    assert 'dimension_delete_batches' in tables
