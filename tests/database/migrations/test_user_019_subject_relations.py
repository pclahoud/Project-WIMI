"""Tests for user-DB migration v19 (student-authored subject relations).

m019 lands issue #14's schema: a ``subject_relations`` table and a
fourth ``subject_delete_batch_items.item_type``. What is asserted here
is the shape, the idempotence, and the constraints that carry a
*decision* rather than a convenience — because a constraint quietly
relaxed later would take the decision with it:

- ``reason`` is ``NOT NULL`` and non-blank (decision 2).
- ``strength`` admits the refuted sentinel and nothing outside the
  grade (decision 8).
- there is no ``dimension_id`` (decision 6).
- ``A->B`` and ``B->A`` both insert (decision 7); only a self-loop is
  refused.
- renaming a subject leaves the relation attached (stable ids).
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names, get_table_names
from database.migrations.user import MIGRATIONS, m019_subject_relations


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v18(conn: sqlite3.Connection) -> MigrationRunner:
    """A database from just before the relations work landed."""
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version <= 18],
        scope="user",
    )


def _ledger_versions(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def _two_subjects(conn: sqlite3.Connection) -> tuple[int, int]:
    ids = []
    for name in ("Hypertension", "Hypertensive Nephrosclerosis"):
        cur = conn.execute(
            "INSERT INTO subject_nodes (exam_context, name, level_type) "
            "VALUES ('USMLE', ?, 'Topic')",
            (name,),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids[0], ids[1]


def _relate(conn, a, b, *, reason="Chronic HTN damages the afferent arteriole.",
            strength=2, origin="user"):
    return conn.execute(
        "INSERT INTO subject_relations "
        "(from_subject_id, to_subject_id, reason, strength, origin) "
        "VALUES (?, ?, ?, ?, ?)",
        (a, b, reason, strength, origin),
    )


# ---------------------------------------------------------------- tests


def test_registry_has_v19_and_keeps_the_gaps():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert 19 in versions
    # m008 is reserved for the assessments branch; v11-v14 are stamped
    # into real databases by the capture feature branch (paused, #145), and the runner
    # treats a stamped version as applied.
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[19] == "subject_relations"


def test_pre_v19_database_has_no_relations_table(fresh_conn):
    _runner_through_v18(fresh_conn).apply_pending()
    assert 'subject_relations' not in get_table_names(fresh_conn)


def test_apply_pending_creates_the_table_and_stamps_the_ledger(fresh_conn):
    _runner_through_v18(fresh_conn).apply_pending()

    applied = _full_runner(fresh_conn).apply_pending()

    # ``in``, not ``==``: this test is about v19 being applied, and the
    # registry grows. Pinning the whole list makes every later migration
    # fail a test that has nothing to do with it (m020 did).
    assert 19 in applied
    assert 'subject_relations' in get_table_names(fresh_conn)
    assert 19 in _ledger_versions(fresh_conn)


def test_relation_carries_no_dimension(fresh_conn):
    """Decision 6: a relation is between two subject nodes, and which
    dimensions they sit in is not the relation's business. A
    ``dimension_id`` column would invite a filter that decision 6
    rejects."""
    _full_runner(fresh_conn).apply_pending()
    cols = get_column_names(fresh_conn, "subject_relations")
    assert 'dimension_id' not in cols
    assert {'from_subject_id', 'to_subject_id', 'reason', 'strength',
            'origin', 'source_entry_id', 'hidden_batch_id',
            'created_at', 'confirmed_at'} <= cols


def test_a_relation_without_a_reason_is_refused(fresh_conn):
    """Decision 2, in the schema rather than only in the UI. A bridge
    slot, an import, or #60's extractor must not be able to write an
    unexplained edge."""
    _full_runner(fresh_conn).apply_pending()
    a, b = _two_subjects(fresh_conn)

    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO subject_relations (from_subject_id, to_subject_id) "
            "VALUES (?, ?)",
            (a, b),
        )
    with pytest.raises(sqlite3.IntegrityError):
        _relate(fresh_conn, a, b, reason="")
    with pytest.raises(sqlite3.IntegrityError):
        _relate(fresh_conn, a, b, reason="   \n\t ")

    _relate(fresh_conn, a, b)
    fresh_conn.commit()
    assert fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_relations"
    ).fetchone()[0] == 1


def test_strength_admits_the_refuted_sentinel_and_nothing_else(fresh_conn):
    """Decision 8: a graded strength with a sentinel for 'checked - NOT
    related'. Retrofitting the sentinel would mean re-reviewing every
    edge, so it is in from the start."""
    _full_runner(fresh_conn).apply_pending()
    a, b = _two_subjects(fresh_conn)

    for value in (-1, 1, 2, 3):
        fresh_conn.execute("DELETE FROM subject_relations")
        _relate(fresh_conn, a, b, strength=value)
    fresh_conn.commit()

    for bad in (0, 4, -2, 99):
        with pytest.raises(sqlite3.IntegrityError):
            _relate(fresh_conn, b, a, strength=bad)


def test_cycles_are_allowed_but_self_loops_are_not(fresh_conn):
    """Decision 7. *A causes B* and *B exacerbates A* can both be true,
    so no cycle validator. A self-loop is a different thing: not a cycle
    between two subjects, just a row with no content."""
    _full_runner(fresh_conn).apply_pending()
    a, b = _two_subjects(fresh_conn)

    _relate(fresh_conn, a, b, reason="HTN damages the glomerulus.")
    _relate(fresh_conn, b, a, reason="Nephrosclerosis raises blood pressure.")
    fresh_conn.commit()
    assert fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_relations"
    ).fetchone()[0] == 2

    with pytest.raises(sqlite3.IntegrityError):
        _relate(fresh_conn, a, a)

    # ...and the same ordered pair cannot be stated twice.
    with pytest.raises(sqlite3.IntegrityError):
        _relate(fresh_conn, a, b, reason="Said it again.")


def test_renaming_a_subject_does_not_orphan_the_relation(fresh_conn):
    """Metacademy's explicit design decision, and the issue's 'stable ids
    separate from human labels'. The relation points at
    ``subject_nodes.id``; the label is resolved at read time."""
    _full_runner(fresh_conn).apply_pending()
    a, b = _two_subjects(fresh_conn)
    _relate(fresh_conn, a, b)
    fresh_conn.commit()

    fresh_conn.execute(
        "UPDATE subject_nodes SET name = 'Essential hypertension' WHERE id = ?",
        (a,),
    )
    fresh_conn.commit()

    row = fresh_conn.execute(
        "SELECT r.id, sn.name FROM subject_relations r "
        "JOIN subject_nodes sn ON sn.id = r.from_subject_id"
    ).fetchone()
    assert row is not None
    assert row[1] == 'Essential hypertension'


def test_losing_the_source_entry_keeps_the_relation(fresh_conn):
    """``source_entry_id`` is the metacognitive trail, not the anchor."""
    _full_runner(fresh_conn).apply_pending()
    a, b = _two_subjects(fresh_conn)
    exam = fresh_conn.execute(
        "INSERT INTO exam_contexts (user_id, exam_name) VALUES (1, 'USMLE')"
    ).lastrowid
    session = fresh_conn.execute(
        "INSERT INTO review_sessions (user_id, session_name, date_encountered, "
        "exam_context_id, total_questions, total_incorrect) "
        "VALUES (1, 's', DATE('now'), ?, 1, 1)",
        (exam,),
    ).lastrowid
    cur = fresh_conn.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer) VALUES (?, 1, 'A', 'B')",
        (session,),
    )
    entry_id = cur.lastrowid
    fresh_conn.execute(
        "INSERT INTO subject_relations (from_subject_id, to_subject_id, reason, "
        "source_entry_id) VALUES (?, ?, 'Missed the link.', ?)",
        (a, b, entry_id),
    )
    fresh_conn.commit()

    fresh_conn.execute("DELETE FROM question_entries WHERE id = ?", (entry_id,))
    fresh_conn.commit()

    row = fresh_conn.execute(
        "SELECT source_entry_id, reason FROM subject_relations"
    ).fetchone()
    assert row is not None
    assert row[0] is None
    assert row[1] == 'Missed the link.'


def test_batch_items_accept_relation_hidden_and_still_reject_typos(fresh_conn):
    """Decision 9 needs a fourth journal item type. m018 constrained
    ``item_type`` to three values and SQLite cannot alter a CHECK, so
    m019 rebuilds the table — the point of this test is that the rebuild
    *widened* the constraint rather than dropping it."""
    _full_runner(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO subject_delete_batches (id, root_node_id) VALUES ('b1', 1)"
    )

    for kind in ('node_archived', 'edge_removed', 'primary_parent_cleared',
                 'relation_hidden'):
        fresh_conn.execute(
            "INSERT INTO subject_delete_batch_items (batch_id, item_type) "
            "VALUES ('b1', ?)",
            (kind,),
        )
    fresh_conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO subject_delete_batch_items (batch_id, item_type) "
            "VALUES ('b1', 'relation_hiden')"
        )


def test_the_rebuild_preserves_existing_journal_rows_and_the_cascade(fresh_conn):
    """A database that already recorded deletes must not lose its
    journal when the CHECK is widened — restore (#37) reads it."""
    _runner_through_v18(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO subject_delete_batches (id, root_node_id, root_node_name) "
        "VALUES ('old', 42, 'Renal')"
    )
    fresh_conn.execute(
        "INSERT INTO subject_delete_batch_items "
        "(batch_id, item_type, subject_node_id, payload) "
        "VALUES ('old', 'node_archived', 42, '{\"previous_status\": \"active\"}')"
    )
    fresh_conn.commit()

    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT batch_id, item_type, subject_node_id, payload "
        "FROM subject_delete_batch_items"
    ).fetchone()
    assert tuple(row) == ('old', 'node_archived', 42,
                          '{"previous_status": "active"}')

    # The FK and its cascade survived the rebuild.
    fresh_conn.execute("DELETE FROM subject_delete_batches WHERE id = 'old'")
    fresh_conn.commit()
    assert fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_delete_batch_items"
    ).fetchone()[0] == 0


def test_hidden_batch_id_is_not_a_foreign_key(fresh_conn):
    """Same reasoning as m018's ``deleted_batch_id``: the purge path
    (#38) drops batches, and a dangling id must degrade to 'no batch
    known' rather than cascading into a delete of the relation."""
    _full_runner(fresh_conn).apply_pending()
    a, b = _two_subjects(fresh_conn)

    fk_targets = {
        r["from"]
        for r in fresh_conn.execute("PRAGMA foreign_key_list(subject_relations)")
    }
    assert "hidden_batch_id" not in fk_targets

    fresh_conn.execute(
        "INSERT INTO subject_relations (from_subject_id, to_subject_id, reason, "
        "hidden_batch_id) VALUES (?, ?, 'x', 'no-such-batch')",
        (a, b),
    )
    fresh_conn.commit()
    assert fresh_conn.execute(
        "SELECT hidden_batch_id FROM subject_relations"
    ).fetchone()[0] == 'no-such-batch'


def test_rerun_is_idempotent(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    a, b = _two_subjects(fresh_conn)
    _relate(fresh_conn, a, b)
    fresh_conn.execute(
        "INSERT INTO subject_delete_batches (id, root_node_id) VALUES ('b1', 1)"
    )
    fresh_conn.execute(
        "INSERT INTO subject_delete_batch_items (batch_id, item_type) "
        "VALUES ('b1', 'relation_hidden')"
    )
    fresh_conn.commit()
    before = get_column_names(fresh_conn, "subject_relations")

    m019_subject_relations.upgrade(fresh_conn)  # must not raise
    m019_subject_relations.upgrade(fresh_conn)
    fresh_conn.commit()

    assert get_column_names(fresh_conn, "subject_relations") == before
    # The rebuild is skipped on a second pass, so nothing is duplicated
    # or lost.
    assert fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_delete_batch_items"
    ).fetchone()[0] == 1
    assert fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_relations"
    ).fetchone()[0] == 1


def test_upgrade_noop_on_a_database_without_the_journal():
    """Defensive: a bare database gets the relations table and skips the
    rebuild rather than raising."""
    conn = sqlite3.connect(":memory:")
    try:
        m019_subject_relations.upgrade(conn)
        assert 'subject_relations' in get_table_names(conn)
        assert 'subject_delete_batch_items' not in get_table_names(conn)
    finally:
        conn.close()


def test_carried_over_database_with_v11_to_v14_stamped_still_migrates(fresh_conn):
    """The reason for the numbering gap, exercised for v19."""
    _runner_through_v18(fresh_conn).apply_pending()
    for version, name in ((11, "capture_a"), (12, "capture_b"),
                          (13, "capture_c"), (14, "capture_d")):
        fresh_conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, name, checksum) "
            "VALUES (?, ?, 'carried-over-from-capture-branch')",
            (version, name),
        )
    fresh_conn.commit()

    applied = _full_runner(fresh_conn).apply_pending()

    assert 19 in applied
    # The stamped-but-absent versions stay skipped, which is the point of
    # this test — a later migration in the registry is not.
    assert not ({8, 11, 12, 13, 14} & set(applied))
    assert 'subject_relations' in get_table_names(fresh_conn)


def test_fresh_user_database_reaches_v19(legacy_user_db_path):
    """The UserDatabase adoption path applies it — which is what makes
    the relation slots safe to call on a database opened today."""
    conn = sqlite3.connect(legacy_user_db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert 19 in _ledger_versions(conn)
        assert 'subject_relations' in get_table_names(conn)
    finally:
        conn.close()
