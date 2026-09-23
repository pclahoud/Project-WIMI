"""Tests for user-DB migration v18 (the subject delete journal).

m018 lands the schema issue #15's decision 4 needs: a ``deleted_batch_id``
stamp on ``subject_nodes``, a ``subject_delete_batches`` row per delete,
and a ``subject_delete_batch_items`` journal of the reversible side
effects. Nothing reads the journal yet — restore is #37, purge is #38 —
so what is asserted here is the shape, the idempotence, and the two
properties that would quietly break the later work: the numbering gap,
and the deliberate absence of a foreign key on the stamp.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names, get_table_names
from database.migrations.user import MIGRATIONS, m018_subject_delete_batches

NEW_TABLES = {'subject_delete_batches', 'subject_delete_batch_items'}


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v17(conn: sqlite3.Connection) -> MigrationRunner:
    """A database from just before the delete-semantics work landed."""
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version <= 17],
        scope="user",
    )


def _ledger_versions(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


# ---------------------------------------------------------------- tests


def test_registry_has_v18_and_keeps_the_gaps():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert 18 in versions
    # m008 is reserved for the assessments branch; v11-v14 are stamped
    # into real databases by the capture feature branch (paused, #145), and the runner
    # treats a stamped version as applied. Reusing one would mean this
    # migration silently never runs on exactly the databases that exist.
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[18] == "subject_delete_batches"


def test_pre_v18_database_has_neither_the_tables_nor_the_stamp(fresh_conn):
    _runner_through_v17(fresh_conn).apply_pending()
    assert not (NEW_TABLES & get_table_names(fresh_conn))
    assert 'deleted_batch_id' not in get_column_names(fresh_conn, "subject_nodes")


def test_apply_pending_creates_the_journal_and_stamps_the_ledger(fresh_conn):
    _runner_through_v17(fresh_conn).apply_pending()

    applied = _full_runner(fresh_conn).apply_pending()

    # Tail-tolerant: every later migration a v17 database is also
    # missing rides along, and this assertion is about v18 arriving,
    # not about being last in the registry.
    assert applied[0] == 18
    assert NEW_TABLES <= get_table_names(fresh_conn)
    assert 'deleted_batch_id' in get_column_names(fresh_conn, "subject_nodes")
    assert 18 in _ledger_versions(fresh_conn)


def test_existing_subjects_are_not_marked_as_deleted(fresh_conn):
    """The stamp must arrive NULL — a non-NULL default would read as
    'every subject you already have was deleted by batch X'."""
    _runner_through_v17(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type) "
        "VALUES ('USMLE', 'Cardiology', 'System')"
    )
    fresh_conn.commit()

    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT status, deleted_batch_id FROM subject_nodes"
    ).fetchone()
    assert row["deleted_batch_id"] is None
    assert row["status"] == "active"


def test_item_type_is_constrained(fresh_conn):
    """A typo in the journal has to fail at insert time. A silently
    accepted item_type would produce rows restore skips without noticing."""
    _full_runner(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO subject_delete_batches (id, root_node_id) VALUES ('b1', 1)"
    )

    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO subject_delete_batch_items (batch_id, item_type) "
            "VALUES ('b1', 'node_arhcived')"
        )

    for kind in ('node_archived', 'edge_removed', 'primary_parent_cleared'):
        fresh_conn.execute(
            "INSERT INTO subject_delete_batch_items (batch_id, item_type) "
            "VALUES ('b1', ?)",
            (kind,),
        )
    fresh_conn.commit()


def test_items_cascade_with_their_batch(fresh_conn):
    """The purge path (#38) drops a batch; its journal must go with it
    rather than accumulating rows pointing at nothing."""
    _full_runner(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO subject_delete_batches (id, root_node_id) VALUES ('b1', 1)"
    )
    fresh_conn.execute(
        "INSERT INTO subject_delete_batch_items (batch_id, item_type, subject_node_id) "
        "VALUES ('b1', 'node_archived', 7)"
    )
    fresh_conn.commit()

    fresh_conn.execute("DELETE FROM subject_delete_batches WHERE id = 'b1'")
    fresh_conn.commit()

    assert fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_delete_batch_items"
    ).fetchone()[0] == 0


def test_deleted_batch_id_is_not_a_foreign_key(fresh_conn):
    """Deliberate, and the same reasoning as m016's
    ``pane_default_source_id``: the purge path must be free to drop a
    batch without being blocked by, or cascading into, the nodes it
    names. A dangling id degrades to "no batch known" — recoverable. A
    cascade would be data loss. The fixture runs with foreign_keys=ON, so
    an FK here would make this insert fail."""
    _full_runner(fresh_conn).apply_pending()

    fk_targets = {
        r["from"] for r in fresh_conn.execute("PRAGMA foreign_key_list(subject_nodes)")
    }
    assert "deleted_batch_id" not in fk_targets

    fresh_conn.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, deleted_batch_id) "
        "VALUES ('USMLE', 'Gone', 'Topic', 'no-such-batch')"
    )
    fresh_conn.commit()
    assert fresh_conn.execute(
        "SELECT deleted_batch_id FROM subject_nodes"
    ).fetchone()[0] == 'no-such-batch'


def test_rerun_is_idempotent(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    before = get_column_names(fresh_conn, "subject_nodes")

    m018_subject_delete_batches.upgrade(fresh_conn)  # must not raise
    m018_subject_delete_batches.upgrade(fresh_conn)
    fresh_conn.commit()

    assert get_column_names(fresh_conn, "subject_nodes") == before
    assert NEW_TABLES <= get_table_names(fresh_conn)


def test_upgrade_noop_on_a_database_without_subject_nodes():
    """Defensive: the column add is skipped and the index it would need
    is not attempted, so a bare database does not raise."""
    conn = sqlite3.connect(":memory:")
    try:
        m018_subject_delete_batches.upgrade(conn)
        assert "subject_nodes" not in get_table_names(conn)
        assert NEW_TABLES <= get_table_names(conn)
    finally:
        conn.close()


def test_carried_over_database_with_v11_to_v14_stamped_still_migrates(fresh_conn):
    """The reason for the numbering gap, exercised for v18."""
    _runner_through_v17(fresh_conn).apply_pending()
    for version, name in ((11, "capture_a"), (12, "capture_b"),
                          (13, "capture_c"), (14, "capture_d")):
        fresh_conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, name, checksum) "
            "VALUES (?, ?, 'carried-over-from-capture-branch')",
            (version, name),
        )
    fresh_conn.commit()

    applied = _full_runner(fresh_conn).apply_pending()

    # Tail-tolerant: every later migration a v17 database is also
    # missing rides along, and this assertion is about v18 arriving,
    # not about being last in the registry.
    assert applied[0] == 18
    assert NEW_TABLES <= get_table_names(fresh_conn)


def test_fresh_user_database_reaches_v18(legacy_user_db_path):
    """The UserDatabase adoption path applies it — which is what makes
    the delete slot safe to call on a database opened today."""
    conn = sqlite3.connect(legacy_user_db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert 18 in _ledger_versions(conn)
        assert NEW_TABLES <= get_table_names(conn)
        assert 'deleted_batch_id' in get_column_names(conn, "subject_nodes")
    finally:
        conn.close()
