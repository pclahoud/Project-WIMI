"""Tests for user-DB migration v36 (a note's origin may be NULL; #848 Wave 0).

m036 rebuilds ``entry_notes`` so ``question_entry_id`` is nullable with
``ON DELETE SET NULL``. The rebuild is the dangerous part, not the column:
``entry_note_attachments.note_id`` references ``entry_notes(id) ON DELETE
CASCADE`` and foreign keys are on, so a plain create-copy-drop-rename empties
the junction at the ``DROP`` with no error. And the runner opens no
transaction of its own -- DDL autocommits until the migration's own ``BEGIN``
-- so the last five tests here are about a run that fails part-way.
What is asserted here is therefore mostly about what the rebuild *kept*: every
row, every id, every (entry, note) attachment pair, the junction's index, the
CHECK, and the AUTOINCREMENT sequence; and that ``PRAGMA foreign_key_check``
is empty afterwards.

Also the registry snapshot moved here from m035's test, as it instructs.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationFailedError, MigrationRunner
from database.migrations._helpers import get_table_names
from database.migrations.user import MIGRATIONS, m036_nullable_note_origin


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v35(conn: sqlite3.Connection) -> MigrationRunner:
    """A database from just before this wave landed."""
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version <= 35],
        scope="user",
    )


def _seed(conn: sqlite3.Connection) -> dict:
    """Two entries and three notes, one attached to both entries.

    Note C is the case the rebuild exists to protect: written on entry 1 and
    attached to entry 2 through the junction. Note D is inserted and deleted
    so the AUTOINCREMENT sequence sits above MAX(id).
    """
    exam = conn.execute(
        "INSERT INTO exam_contexts (user_id, exam_name) VALUES (1, 'Exam')").lastrowid
    session = conn.execute(
        "INSERT INTO review_sessions (user_id, exam_context_id, date_encountered, "
        "total_questions, total_incorrect) VALUES (1, ?, '2026-11-05', 5, 1)",
        (exam,)).lastrowid
    e1 = conn.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, user_answer, "
        "correct_answer) VALUES (?, 1, 'A', 'B')", (session,)).lastrowid
    e2 = conn.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, user_answer, "
        "correct_answer) VALUES (?, 2, 'C', 'D')", (session,)).lastrowid

    def note(entry, html, subjects):
        return conn.execute(
            "INSERT INTO entry_notes (question_entry_id, content_html, sort_order, "
            "linked_subject_ids) VALUES (?, ?, 0, ?)",
            (entry, html, subjects)).lastrowid

    a = note(e1, '<p>A</p>', '[1]')
    b = note(e2, '<p>B</p>', None)
    c = note(e1, '<p>C</p>', '[1, 2]')
    d = note(e2, '<p>D</p>', None)
    conn.execute("DELETE FROM entry_notes WHERE id = ?", (d,))

    for entry, nid in ((e1, a), (e2, b), (e1, c), (e2, c)):
        conn.execute(
            "INSERT OR IGNORE INTO entry_note_attachments "
            "(question_entry_id, note_id, sort_order) VALUES (?, ?, 0)",
            (entry, nid))
    conn.commit()
    return {'e1': e1, 'e2': e2, 'a': a, 'b': b, 'c': c, 'd': d}


def _notes(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT id, question_entry_id, content_html, content_json, sort_order, "
        "linked_subject_ids, is_migrated, created_at, updated_at "
        "FROM entry_notes ORDER BY id")]


def _pairs(conn):
    return sorted(
        (r[0], r[1], r[2], r[3]) for r in conn.execute(
            "SELECT question_entry_id, note_id, sort_order, attached_at "
            "FROM entry_note_attachments"))


def _column(conn, table, name):
    for row in conn.execute(f"PRAGMA table_info({table})"):
        if row[1] == name:
            return row
    raise AssertionError(f"{table}.{name} is missing")


def _fks(conn, table):
    return {(r[2], r[3], r[4], r[6]) for r in conn.execute(
        f"PRAGMA foreign_key_list({table})")}


def _indexes(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA index_list({table})")}


@pytest.fixture
def before(fresh_conn):
    _runner_through_v35(fresh_conn).apply_pending()
    ids = _seed(fresh_conn)
    return fresh_conn, ids


# ---------------------------------------------------------------- tests


# The registry snapshot moved to test_user_037_exam_name_debris.py when m037
# landed (#884), as its docstring instructed.


def test_before_v36_the_origin_is_not_null(before):
    conn, _ = before
    assert _column(conn, 'entry_notes', 'question_entry_id')[3] == 1
    assert 36 not in {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def test_the_naive_rebuild_would_empty_the_junction(before):
    """The hazard the migration's order answers, shown rather than asserted
    in prose: with foreign keys on, DROP TABLE entry_notes cascades through
    the junction. A reader who simplifies m036 to m019's shape should find
    this test and understand what it costs."""
    conn, _ = before
    assert len(_pairs(conn)) == 4
    conn.execute("CREATE TABLE scratch AS SELECT * FROM entry_notes")
    conn.execute("DROP TABLE entry_notes")
    assert conn.execute("SELECT COUNT(*) FROM entry_note_attachments").fetchone()[0] == 0
    conn.rollback()


def test_apply_keeps_every_row_id_and_attachment(before):
    conn, ids = before
    notes_before = _notes(conn)
    pairs_before = _pairs(conn)
    assert len(notes_before) == 3 and len(pairs_before) == 4

    applied = _full_runner(conn).apply_pending()

    assert 36 in applied
    assert _notes(conn) == notes_before
    assert _pairs(conn) == pairs_before
    assert {(p[0], p[1]) for p in _pairs(conn)} == {
        (ids['e1'], ids['a']), (ids['e2'], ids['b']),
        (ids['e1'], ids['c']), (ids['e2'], ids['c'])}


def test_the_origin_is_nullable_and_sets_null(before):
    conn, _ = before
    _full_runner(conn).apply_pending()
    assert _column(conn, 'entry_notes', 'question_entry_id')[3] == 0
    assert ('question_entries', 'question_entry_id', 'id', 'SET NULL') in _fks(conn, 'entry_notes')


def test_every_other_column_definition_is_kept(before):
    """Only ``notnull`` on ``question_entry_id`` may change. The fingerprint
    test cannot see a drift here, because a fresh database also ends in
    m036's DDL, so both sides would carry the same mistake (#862 item 3)."""
    conn, _ = before
    cols = lambda: [tuple(r) for r in conn.execute("PRAGMA table_info(entry_notes)")]
    old = cols()
    _full_runner(conn).apply_pending()
    new = cols()
    expected = [r if r[1] != 'question_entry_id' else r[:3] + (0,) + r[4:] for r in old]
    assert new == expected


def test_the_junction_is_m009s_again(before):
    conn, _ = before
    _full_runner(conn).apply_pending()
    fks = _fks(conn, 'entry_note_attachments')
    assert ('entry_notes', 'note_id', 'id', 'CASCADE') in fks
    assert ('question_entries', 'question_entry_id', 'id', 'CASCADE') in fks
    assert 'idx_ena_note' in _indexes(conn, 'entry_note_attachments')
    cols = [r[1] for r in conn.execute("PRAGMA table_info(entry_note_attachments)")]
    assert cols == ['question_entry_id', 'note_id', 'sort_order', 'attached_at']
    # The composite primary key still refuses a duplicate attachment.
    e1, a = conn.execute(
        "SELECT question_entry_id, note_id FROM entry_note_attachments LIMIT 1").fetchone()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO entry_note_attachments (question_entry_id, note_id) "
                     "VALUES (?, ?)", (e1, a))


def test_foreign_key_check_is_empty_and_nothing_is_left_behind(before):
    conn, _ = before
    _full_runner(conn).apply_pending()
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    tables = get_table_names(conn)
    assert 'entry_note_attachments_m036' not in tables
    assert 'entry_notes_m036' not in tables


def test_every_entry_notes_index_survives(before):
    """The schema file declares none, so one is planted to prove the rebuild
    carries whatever it finds rather than only what it expects."""
    conn, _ = before
    conn.execute("CREATE INDEX idx_planted_note_origin ON entry_notes(question_entry_id)")
    conn.commit()
    _full_runner(conn).apply_pending()
    assert 'idx_planted_note_origin' in _indexes(conn, 'entry_notes')


def test_the_json_check_still_refuses_invalid_json(before):
    conn, ids = before
    _full_runner(conn).apply_pending()
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO entry_notes (question_entry_id, content_html, linked_subject_ids) "
            "VALUES (?, 'x', 'not json')", (ids['e1'],))


def test_a_deleted_notes_id_is_not_reused(before):
    """Note D was deleted before the rebuild; the sequence must still sit
    above it, or the next note takes D's id and D's graph node with it."""
    conn, ids = before
    _full_runner(conn).apply_pending()
    new_id = conn.execute(
        "INSERT INTO entry_notes (question_entry_id, content_html) VALUES (?, 'E')",
        (ids['e1'],)).lastrowid
    assert new_id > ids['d']


def test_a_free_note_can_now_be_written(before):
    conn, _ = before
    _full_runner(conn).apply_pending()
    nid = conn.execute(
        "INSERT INTO entry_notes (question_entry_id, content_html) VALUES (NULL, 'free')"
    ).lastrowid
    assert conn.execute(
        "SELECT question_entry_id FROM entry_notes WHERE id = ?", (nid,)).fetchone()[0] is None


def test_deleting_the_origin_sets_null_at_the_schema_level(before):
    """What the column does on its own. Decision 2's rule -- delete a note
    held nowhere else -- is application code above this, tested in
    tests/database/test_free_notes.py; the clause is the fallback for a
    path that forgets, and it must free rather than destroy."""
    conn, ids = before
    _full_runner(conn).apply_pending()
    conn.execute("DELETE FROM question_entries WHERE id = ?", (ids['e1'],))
    rows = {r[0]: r[1] for r in conn.execute(
        "SELECT id, question_entry_id FROM entry_notes")}
    assert rows[ids['a']] is None and rows[ids['c']] is None
    assert rows[ids['b']] == ids['e2']
    assert {(p[0], p[1]) for p in _pairs(conn)} == {
        (ids['e2'], ids['b']), (ids['e2'], ids['c'])}


def test_a_dangling_origin_becomes_a_free_note_instead_of_refusing_the_profile(before):
    """A note whose origin names an entry that no longer exists cannot be
    written by WIMI -- foreign keys are on and the old clause cascaded -- but a
    database another writer touched with them off can carry one, and the old
    schema tolerated it silently (SQLite checks a foreign key on write, never
    on existing rows). The copy into the rebuilt table enforces its
    REFERENCES, so such a row made m036 raise on every launch and the profile
    never opened again. It is copied with its origin NULL instead, which is
    what this wave's own rule makes of a note whose entry is gone; a junction
    row naming a vanished entry or note is dropped, since it attached nothing
    to nothing. Operator's edit on PR #861."""
    conn, ids = before
    conn.execute("PRAGMA foreign_keys = OFF")
    stray = conn.execute(
        "INSERT INTO entry_notes (question_entry_id, content_html) "
        "VALUES (999999, '<p>stray</p>')").lastrowid
    conn.execute(
        "INSERT INTO entry_note_attachments (question_entry_id, note_id, sort_order) "
        "VALUES (999999, ?, 0)", (ids['a'],))
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    assert conn.execute("PRAGMA foreign_key_check").fetchall(), "the premise of this test"
    good_pairs = {(ids['e1'], ids['a']), (ids['e2'], ids['b']),
                  (ids['e1'], ids['c']), (ids['e2'], ids['c'])}

    applied = _full_runner(conn).apply_pending()

    assert 36 in applied
    row = conn.execute(
        "SELECT question_entry_id, content_html FROM entry_notes WHERE id = ?",
        (stray,)).fetchone()
    assert row is not None, "the stray note was lost"
    assert row[0] is None and row[1] == '<p>stray</p>'
    assert {(p[0], p[1]) for p in _pairs(conn)} == good_pairs
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_upgrade_is_idempotent(before):
    conn, _ = before
    _full_runner(conn).apply_pending()
    notes, pairs = _notes(conn), _pairs(conn)
    m036_nullable_note_origin.upgrade(conn)
    assert _notes(conn) == notes
    assert _pairs(conn) == pairs
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_partial_registry_without_the_junction_still_rebuilds(fresh_conn):
    """Isolated-migration tests run registries that skip m009; the rebuild
    must not assume the junction exists."""
    MigrationRunner(
        fresh_conn,
        registry=[m for m in MIGRATIONS if m.version <= 7 or m.version == 36],
        scope="user",
    ).apply_pending()
    assert 'entry_note_attachments' not in get_table_names(fresh_conn)
    assert _column(fresh_conn, 'entry_notes', 'question_entry_id')[3] == 0


# ------------------------------------------------- a partial run (PR #861 review)
#
# The runner issues no BEGIN, and under legacy transaction control DDL
# autocommits until the first DML. Before the fix, the junction drop was
# committed on its own, a failure later in the rebuild left the holding table
# as the only copy of the attachments, and the retry's first statement dropped
# it: every attachment gone, v36 stamped, no error anywhere. The tests below
# are the ones that would have caught it; ``test_upgrade_is_idempotent`` only
# re-runs after success and hits the early return.


class _FailingOn:
    """A connection that raises on the first statement containing ``needle``.

    Everything else -- commit, rollback, in_transaction, the runner's own
    ``schema_migrations`` writes -- reaches the real connection.
    """

    def __init__(self, conn, needle):
        self._conn = conn
        self._needle = needle
        self.tripped = False

    def execute(self, sql, *args):
        if self._needle in sql:
            self.tripped = True
            raise sqlite3.OperationalError(f"injected failure at {self._needle!r}")
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.mark.parametrize("needle", [
    "RENAME TO entry_notes",               # after the junction drop, before the junction is back
    "INSERT INTO entry_note_attachments",  # the junction exists again but is empty
])
def test_a_failed_upgrade_leaves_the_database_as_it_was(before, needle):
    conn, _ = before
    notes_before, pairs_before = _notes(conn), _pairs(conn)
    assert len(pairs_before) == 4

    failing = _FailingOn(conn, needle)
    with pytest.raises(MigrationFailedError):
        MigrationRunner(failing, registry=MIGRATIONS, scope="user").apply_pending()
    assert failing.tripped, "the injected failure never fired, so this proves nothing"

    tables = get_table_names(conn)
    assert 'entry_note_attachments' in tables, (
        "the junction drop was committed before the rollback could reach it")
    assert _pairs(conn) == pairs_before
    assert _notes(conn) == notes_before
    assert 'entry_note_attachments_m036' not in tables
    assert 'entry_notes_m036' not in tables
    assert _column(conn, 'entry_notes', 'question_entry_id')[3] == 1
    assert 36 not in {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    assert not conn.in_transaction


@pytest.mark.parametrize("needle", [
    "RENAME TO entry_notes",
    "INSERT INTO entry_note_attachments",
])
def test_the_retry_after_a_failure_is_lossless(before, needle):
    conn, ids = before
    notes_before, pairs_before = _notes(conn), _pairs(conn)

    with pytest.raises(MigrationFailedError):
        MigrationRunner(
            _FailingOn(conn, needle), registry=MIGRATIONS, scope="user").apply_pending()

    applied = _full_runner(conn).apply_pending()

    assert 36 in applied
    assert _pairs(conn) == pairs_before
    assert {(p[0], p[1]) for p in _pairs(conn)} == {
        (ids['e1'], ids['a']), (ids['e2'], ids['b']),
        (ids['e1'], ids['c']), (ids['e2'], ids['c'])}
    assert _notes(conn) == notes_before
    assert _column(conn, 'entry_notes', 'question_entry_id')[3] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    tables = get_table_names(conn)
    assert 'entry_note_attachments_m036' not in tables
    assert 'entry_notes_m036' not in tables


def test_the_upgrade_runs_inside_one_transaction(before):
    """Every statement after the early returns is inside the transaction the
    runner commits -- the property the two tests above depend on. Read off
    the connection at each statement rather than asserted from the module."""
    conn, _ = before
    seen = []

    class Recording(_FailingOn):
        def execute(self, sql, *args):
            seen.append((sql.strip()[:40], self._conn.in_transaction))
            return self._conn.execute(sql, *args)

    MigrationRunner(Recording(conn, "\\0never"), registry=MIGRATIONS, scope="user").apply_pending()

    begin_at = next(i for i, s in enumerate(seen) if s[0] == "BEGIN")
    # Up to the runner's stamp of v36: a later migration (m037 onward) opens
    # its own transaction after the runner commits this one.
    stamp_at = next(i for i, s in enumerate(seen)
                    if i > begin_at and s[0].startswith("INSERT INTO schema_migrations"))
    m036_statements = seen[begin_at + 1:stamp_at]
    destructive = [s for s in m036_statements if s[0].startswith("DROP TABLE")]
    assert len(destructive) >= 3, m036_statements
    assert all(in_tx for _, in_tx in m036_statements), (
        f"a statement ran outside the transaction: {m036_statements!r}")
    assert not conn.in_transaction


def test_a_leftover_holding_table_is_the_source_of_truth(before):
    """The state a pre-BEGIN build of this migration could leave: junction
    dropped and committed, its rows in the holding table, v36 unstamped.
    The rebuild must take the holding table as the junction's rows, not
    drop it as debris."""
    conn, ids = before
    pairs_before = _pairs(conn)
    conn.execute(
        "CREATE TABLE entry_note_attachments_m036 AS "
        "SELECT question_entry_id, note_id, sort_order, attached_at "
        "FROM entry_note_attachments")
    conn.execute("DROP TABLE entry_note_attachments")
    conn.commit()
    assert 'entry_note_attachments' not in get_table_names(conn)

    _full_runner(conn).apply_pending()

    assert _pairs(conn) == pairs_before
    assert {(p[0], p[1]) for p in _pairs(conn)} == {
        (ids['e1'], ids['a']), (ids['e2'], ids['b']),
        (ids['e1'], ids['c']), (ids['e2'], ids['c'])}
    assert 'idx_ena_note' in _indexes(conn, 'entry_note_attachments')
    assert ('entry_notes', 'note_id', 'id', 'CASCADE') in _fks(conn, 'entry_note_attachments')
    assert 'entry_note_attachments_m036' not in get_table_names(conn)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
