"""Tests for user-DB migration v26 (relation types, #14 / #60).

The owner's decision of 2026-10-03: relations get **types** from a fixed
list the student owns, per exam. m026 lands the schema for it and has to
do one expensive thing to get there -- rebuild ``subject_relations``,
because m019's ``UNIQUE(from_subject_id, to_subject_id)`` forbids *A
causes B* and *A confused with B* from coexisting, and SQLite cannot drop
a table constraint in place.

So the tests that matter most are the ones about **real rows surviving
the rebuild**: every column, including ``hidden_batch_id``, whose loss
would break #37's restore without any error anywhere.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names, get_table_names
from database.migrations.user import MIGRATIONS, m026_relation_types


SEED_LABELS = [
    'causes', 'risk factor for', 'complication of',
    'treats', 'presents with', 'confused with',
]


def _runner_through(conn: sqlite3.Connection, version: int) -> MigrationRunner:
    return MigrationRunner(
        conn, registry=[m for m in MIGRATIONS if m.version <= version], scope="user")


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _exam(conn, name: str) -> int:
    cur = conn.execute(
        "INSERT INTO exam_contexts (user_id, exam_name) VALUES (1, ?)", (name,))
    return cur.lastrowid


def _subject(conn, name: str, exam: str = 'USMLE') -> int:
    cur = conn.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type) "
        "VALUES (?, ?, 'Topic')", (exam, name))
    return cur.lastrowid


def _types(conn, exam_id: int) -> dict:
    return {
        row['label']: dict(row) for row in conn.execute(
            "SELECT * FROM relation_types WHERE exam_id = ?", (exam_id,))
    }


@pytest.fixture
def v25_with_relations(fresh_conn):
    """A database from just before m026, holding the rows a real student
    would have: relations in both directions between one pair, a refuted
    note, an extracted unconfirmed row, and one hidden by a delete batch."""
    conn = fresh_conn
    conn.row_factory = sqlite3.Row
    _runner_through(conn, 25).apply_pending()
    exam_id = _exam(conn, 'USMLE')
    a, b, c = (_subject(conn, n) for n in ('Hypertension', 'CKD', 'Eclampsia'))
    rows = [
        (a, b, 'HTN scleroses the afferent arteriole.', 3, 'user', None, None, '2026-09-01 10:00:00'),
        (b, a, 'CKD drives renin, which raises pressure.', 2, 'user', None, None, '2026-09-02 10:00:00'),
        (a, c, 'Checked: not the mechanism I thought.', -1, 'user', None, None, '2026-09-03 10:00:00'),
        (c, b, 'Extracted, never confirmed.', 1, 'extracted', None, None, None),
        (c, a, 'Hidden when eclampsia was archived.', 2, 'user', None, 'batch-xyz', '2026-09-04 10:00:00'),
    ]
    for fr, to, reason, strength, origin, src, hidden, confirmed in rows:
        conn.execute(
            "INSERT INTO subject_relations (from_subject_id, to_subject_id, reason, "
            "strength, origin, source_entry_id, hidden_batch_id, confirmed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fr, to, reason, strength, origin, src, hidden, confirmed))
    conn.commit()
    return conn, exam_id, (a, b, c)


def _snapshot(conn) -> list:
    return [tuple(r) for r in conn.execute(
        "SELECT id, from_subject_id, to_subject_id, reason, strength, origin, "
        "source_entry_id, hidden_batch_id, created_at, confirmed_at "
        "FROM subject_relations ORDER BY id")]


# ---------------------------------------------------------------- registry


def test_registry_has_v26_and_keeps_the_gaps():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert 26 in versions
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[26] == "relation_types"
    # The `max(versions)` snapshot claim moved on to m027's test when m027
    # landed, exactly as the note here instructed. It is held by whichever
    # migration is newest and by exactly one file at a time; see
    # test_user_027_relation_rejections.py. Carried m023 -> m024 -> m025 ->
    # m026 -> m027.


# ---------------------------------------------------------------- the rebuild


def test_the_rebuild_loses_nothing(v25_with_relations):
    """Every existing row, every column, byte for byte -- ids included,
    because #37's journal and ``source_entry_id`` consumers address
    relations by id."""
    conn, _, _ = v25_with_relations
    before = _snapshot(conn)
    assert len(before) == 5

    _full_runner(conn).apply_pending()

    assert _snapshot(conn) == before


def test_hidden_batch_id_survives_so_restore_still_finds_it(v25_with_relations):
    conn, _, (a, b, c) = v25_with_relations
    _full_runner(conn).apply_pending()
    hidden = conn.execute(
        "SELECT from_subject_id, to_subject_id FROM subject_relations "
        "WHERE hidden_batch_id = 'batch-xyz'").fetchall()
    assert [tuple(r) for r in hidden] == [(c, a)]


def test_existing_relations_stay_untyped(v25_with_relations):
    """Owner's decision 4: nothing is guessed. Every pre-existing row keeps
    ``relation_type_id`` NULL until the student edits it."""
    conn, _, _ = v25_with_relations
    _full_runner(conn).apply_pending()
    assert 'relation_type_id' in get_column_names(conn, 'subject_relations')
    assert conn.execute(
        "SELECT COUNT(*) FROM subject_relations WHERE relation_type_id IS NOT NULL"
    ).fetchone()[0] == 0


def test_indexes_survive_the_rebuild(v25_with_relations):
    conn, _, _ = v25_with_relations
    _full_runner(conn).apply_pending()
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='subject_relations'")}
    for expected in ('idx_subject_relations_from', 'idx_subject_relations_to',
                     'idx_subject_relations_hidden',
                     'idx_subject_relations_source_entry'):
        assert expected in names


def test_the_migration_is_idempotent(v25_with_relations):
    conn, exam_id, _ = v25_with_relations
    _full_runner(conn).apply_pending()
    before = _snapshot(conn)
    types_before = _types(conn, exam_id)

    m026_relation_types.upgrade(conn)
    conn.commit()

    assert _snapshot(conn) == before
    assert _types(conn, exam_id) == types_before


# ---------------------------------------------------------------- seeding


def test_every_existing_exam_is_seeded_with_the_owner_list(fresh_conn):
    conn = fresh_conn
    _runner_through(conn, 25).apply_pending()
    first, second = _exam(conn, 'USMLE'), _exam(conn, 'Surgery Shelf')
    conn.commit()

    _full_runner(conn).apply_pending()

    for exam_id in (first, second):
        types = _types(conn, exam_id)
        assert sorted(types) == sorted(SEED_LABELS)
        ordered = [r['label'] for r in conn.execute(
            "SELECT label FROM relation_types WHERE exam_id = ? ORDER BY sort_order",
            (exam_id,))]
        assert ordered == SEED_LABELS
        assert all(t['status'] == 'active' for t in types.values())


def test_reverse_labels_and_the_one_symmetric_type(fresh_conn):
    conn = fresh_conn
    _runner_through(conn, 25).apply_pending()
    exam_id = _exam(conn, 'USMLE')
    conn.commit()
    _full_runner(conn).apply_pending()

    types = _types(conn, exam_id)
    assert types['causes']['reverse_label'] == 'caused by'
    assert types['treats']['reverse_label'] == 'treated by'
    symmetric = {label for label, t in types.items() if t['is_symmetric']}
    assert symmetric == {'confused with'}
    assert types['confused with']['reverse_label'] == 'confused with'


def test_a_symmetric_type_must_read_the_same_both_ways(fresh_conn):
    conn = fresh_conn
    _full_runner(conn).apply_pending()
    exam_id = _exam(conn, 'USMLE')
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO relation_types (exam_id, label, reverse_label, is_symmetric, "
            "sort_order) VALUES (?, 'mimics', 'mimicked by', 1, 99)", (exam_id,))


def test_two_active_types_cannot_share_a_label(fresh_conn):
    conn = fresh_conn
    _full_runner(conn).apply_pending()
    exam_id = _exam(conn, 'USMLE')
    conn.execute(
        "INSERT INTO relation_types (exam_id, label, reverse_label, sort_order) "
        "VALUES (?, 'inhibits', 'inhibited by', 1)", (exam_id,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO relation_types (exam_id, label, reverse_label, sort_order) "
            "VALUES (?, 'Inhibits', 'inhibited by', 2)", (exam_id,))
    # ...but a retired one does not hold its label hostage.
    conn.execute("UPDATE relation_types SET status = 'retired' "
                 "WHERE exam_id = ? AND label = 'inhibits'", (exam_id,))
    conn.execute(
        "INSERT INTO relation_types (exam_id, label, reverse_label, sort_order) "
        "VALUES (?, 'inhibits', 'inhibited by', 3)", (exam_id,))


# ---------------------------------------------------------------- uniqueness


def _seeded_exam(conn, name: str) -> int:
    """An exam created after m026 ran -- seeded the way the domain layer
    seeds a new exam, through the migration's own helper."""
    exam_id = _exam(conn, name)
    m026_relation_types.seed_relation_types(conn, exam_id)
    return exam_id


def _typed(conn, exam_id, label):
    return conn.execute(
        "SELECT id FROM relation_types WHERE exam_id = ? AND label = ?",
        (exam_id, label)).fetchone()[0]


def _insert(conn, a, b, type_id, reason='Because.'):
    conn.execute(
        "INSERT INTO subject_relations (from_subject_id, to_subject_id, reason, "
        "relation_type_id) VALUES (?, ?, ?, ?)", (a, b, reason, type_id))


def test_two_types_between_one_pair_coexist(fresh_conn):
    """The whole point of the rebuild: *A causes B* and *A complication of
    B* are different statements about the same ordered pair."""
    conn = fresh_conn
    _full_runner(conn).apply_pending()
    exam_id = _seeded_exam(conn, 'USMLE')
    a, b = _subject(conn, 'A'), _subject(conn, 'B')
    _insert(conn, a, b, _typed(conn, exam_id, 'causes'))
    _insert(conn, a, b, _typed(conn, exam_id, 'risk factor for'))
    _insert(conn, a, b, None)
    assert conn.execute("SELECT COUNT(*) FROM subject_relations").fetchone()[0] == 3


def test_the_same_typed_statement_cannot_be_made_twice(fresh_conn):
    conn = fresh_conn
    _full_runner(conn).apply_pending()
    exam_id = _seeded_exam(conn, 'USMLE')
    a, b = _subject(conn, 'A'), _subject(conn, 'B')
    causes = _typed(conn, exam_id, 'causes')
    _insert(conn, a, b, causes)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, a, b, causes)


def test_untyped_rows_keep_one_per_ordered_pair(fresh_conn):
    """SQLite treats NULLs as distinct in a UNIQUE constraint, so
    ``UNIQUE(from, to, relation_type_id)`` alone would let untyped
    duplicates in. A partial unique index keeps m019's rule for them."""
    conn = fresh_conn
    _full_runner(conn).apply_pending()
    a, b = _subject(conn, 'A'), _subject(conn, 'B')
    _insert(conn, a, b, None)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, a, b, None, reason='Again.')
    # The reverse direction is a different statement (decision 7).
    _insert(conn, b, a, None)


def test_a_symmetric_relation_is_stored_once_in_canonical_order(fresh_conn):
    """``A confused with B`` and ``B confused with A`` are one relation.
    The schema refuses the non-canonical spelling, so the UNIQUE
    constraint is enough to stop the pair being stored twice."""
    conn = fresh_conn
    _full_runner(conn).apply_pending()
    exam_id = _seeded_exam(conn, 'USMLE')
    a, b = _subject(conn, 'A'), _subject(conn, 'B')
    lo, hi = min(a, b), max(a, b)
    confused = _typed(conn, exam_id, 'confused with')
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, hi, lo, confused)
    _insert(conn, lo, hi, confused)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, lo, hi, confused)
    # Asymmetric types keep both directions (decision 7).
    causes = _typed(conn, exam_id, 'causes')
    _insert(conn, hi, lo, causes)
    _insert(conn, lo, hi, causes)


def test_the_canonical_order_is_also_enforced_on_update(fresh_conn):
    conn = fresh_conn
    _full_runner(conn).apply_pending()
    exam_id = _seeded_exam(conn, 'USMLE')
    a, b = _subject(conn, 'A'), _subject(conn, 'B')
    lo, hi = min(a, b), max(a, b)
    _insert(conn, hi, lo, None)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE subject_relations SET relation_type_id = ?",
                     (_typed(conn, exam_id, 'confused with'),))


def test_relation_types_table_exists_after_a_fresh_install(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    assert 'relation_types' in get_table_names(fresh_conn)
    assert {'id', 'exam_id', 'label', 'reverse_label', 'is_symmetric',
            'status', 'sort_order'} <= get_column_names(fresh_conn, 'relation_types')
