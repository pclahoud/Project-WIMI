"""Opening a profile writes planner statistics (#218).

`close()`'s `PRAGMA optimize` was the only thing in the codebase that ever
wrote `sqlite_stat1`, so a profile had **no statistics for the whole of its
first session** — a new profile, one installed from a `.wimi`, one taken from
a sync folder (#151). Measured on a real 13,967-node profile, that cost
`get_subject_hierarchy` on the active exam **6,141 ms instead of 60 ms**, with
a byte-identical payload.

`UserDatabase.__init__` now ends with `write_planner_statistics()`.

The load-bearing test here is the negative control
---------------------------------------------------
`test_pragma_optimize_would_write_nothing_here` is the reason this file
exists. #218's own proposed fix was "`PRAGMA optimize` at open", which looks
equivalent and is **not**: on SQLite 3.45 (what Python 3.12 bundles) optimize
analyses a table only if a query in the same connection has already used an
index on it, and WIMI's open path never queries the big tables. So it writes
zero rows at every database size and changes no plan.

That makes `ANALYZE` look gratuitously heavy to a future reader holding
SQLite's own advice to prefer `PRAGMA optimize`. Without a test pinning the
difference, swapping them is a reasonable-looking afternoon's change that
silently reverts the fix — the same hazard
`test_connection_pragmas.py::test_pep249_mode_would_break_wal_setup` exists
for.
"""

from __future__ import annotations

import sqlite3

import pytest

from database.base_db import BaseDatabase


# The tables whose statistics actually matter: every measured regression in
# #218 was a plan over these four.
HOT_TABLES = (
    "subject_nodes",
    "subject_edges",
    "question_entries",
    "entry_subject_mappings",
)


def _stat1_tables(conn) -> set:
    """Table names named in ``sqlite_stat1``, or an empty set if absent."""
    present = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE name = 'sqlite_stat1'"
    ).fetchone()[0]
    if not present:
        return set()
    return {r[0] for r in conn.execute("SELECT DISTINCT tbl FROM sqlite_stat1")}


def _seed(db) -> None:
    """Enough rows in the hot tables that ANALYZE has something to say.

    ANALYZE writes no row for an empty table, so a fresh profile legitimately
    gets almost nothing — the benefit lands on the *next* open, and on the
    import and sync-install paths where data is already in the file. Seeding
    here is what makes the assertions about the hot tables meaningful.
    """
    from datetime import date

    exam = db.create_exam_context(exam_name="Stats", exam_description="")
    parent = db.create_subject_node(
        exam_context=exam.exam_name, name="Root", level_type="System"
    )
    # `create_subject_node(parent_id=...)` writes the edge itself; adding one
    # here too trips UNIQUE(parent_id, child_id).
    children = [
        db.create_subject_node(
            exam_context=exam.exam_name,
            name=f"Child {i}",
            parent_id=parent.id,
            level_type="Topic",
        )
        for i in range(40)
    ]

    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=40,
        total_incorrect=20,
        session_name="Stats session",
        date_encountered=date.today(),
    )
    # Entries carrying subjects, so `question_entries` and
    # `entry_subject_mappings` are non-empty -- ANALYZE writes no row for an
    # empty table, and those two are half of HOT_TABLES.
    for i, child in enumerate(children[:20]):
        db.create_question_entry(
            review_session_id=session.id,
            user_answer=f"A{i}",
            correct_answer=f"B{i}",
            primary_subject_ids=[child.id],
        )
    db.conn.commit()


@pytest.fixture
def populated(tmp_path):
    """A profile with data in it, closed cleanly, ready to be reopened.

    The close is deliberate: it is the shape a student's second launch takes,
    and it also proves the assertions below are not accidentally measuring
    `close()`'s own `PRAGMA optimize`.
    """
    from database import UserDatabase

    path = tmp_path / "user_stats.db"
    db = UserDatabase(db_path=path, user_id=1, username="stats")
    _seed(db)
    db.close()
    return path


@pytest.mark.database
def test_opening_a_profile_writes_statistics_for_the_hot_tables(populated):
    """The fix, asserted against a live connection rather than the source."""
    from database import UserDatabase

    db = UserDatabase(db_path=populated, user_id=1, username="stats")
    try:
        tables = _stat1_tables(db.conn)
        assert tables, (
            "sqlite_stat1 is empty or absent immediately after opening a "
            "populated profile, so the planner is working blind for the whole "
            "session -- #218"
        )
        missing = [t for t in HOT_TABLES if t not in tables]
        assert not missing, (
            f"no planner statistics for {missing}. Every plan regression "
            f"measured in #218 was over these tables, so statistics that "
            f"miss them do not fix anything"
        )
    finally:
        db.close()


@pytest.mark.database
def test_pragma_optimize_would_write_nothing_here(populated):
    """The negative control, and the reason this file exists (#218).

    This is what #218 originally proposed. It is measured to be a no-op in
    WIMI's open path on SQLite 3.45, because `PRAGMA optimize` analyses a
    table only when a query in the same connection has already used an index
    on it. If this test ever fails, SQLite's behaviour changed (3.46+ adds a
    real "analyze all" bit) and the choice in
    `write_planner_statistics` is worth revisiting -- but until then, this is
    what stops ANALYZE being "simplified" into optimize.
    """
    conn = sqlite3.connect(populated)
    try:
        conn.execute("PRAGMA analysis_limit = 1000")
        before = _stat1_tables(conn)
        conn.execute("PRAGMA optimize")
        after = _stat1_tables(conn)

        assert not (after - before) & set(HOT_TABLES), (
            "PRAGMA optimize wrote statistics for a hot table without any "
            "prior index-using query. That contradicts the measurement "
            "write_planner_statistics() is built on -- re-read #218 before "
            "changing the statement it runs"
        )
    finally:
        conn.close()


@pytest.mark.database
def test_an_analyze_failure_is_swallowed(tmp_path):
    """Best-effort, for the same reason ``close()``'s pragma is.

    A read-only file or a short-lived verify-open must not fail because the
    planner would like better statistics. A permanently unopenable profile is
    a far worse bug than a slow query.

    The stub is a stand-in for a real read-only connection because
    ``sqlite3.Connection`` is an immutable type and its ``execute`` cannot be
    patched; what is under test is the ``except sqlite3.Error`` around the
    statement, and that is exercised either way.
    """

    class _ReadOnly:
        def execute(self, sql, *args, **kwargs):
            raise sqlite3.OperationalError("attempt to write a readonly database")

    db = BaseDatabase(tmp_path / "ro.db")
    real_conn = db.conn
    try:
        db.conn = _ReadOnly()
        db.write_planner_statistics()  # must return, not raise
    finally:
        db.conn = real_conn
        db.close()


@pytest.mark.database
def test_the_open_path_actually_calls_it(populated, monkeypatch):
    """The wiring, separately from the statement.

    `write_planner_statistics` being correct is no use if nothing calls it,
    and that is exactly how #218's defect existed in the first place:
    `close()`'s pragma was right and ran too late to help the session that
    needed it.
    """
    from database import UserDatabase

    calls = []
    real = BaseDatabase.write_planner_statistics

    def spy(self):
        calls.append(self.db_path)
        return real(self)

    monkeypatch.setattr(BaseDatabase, "write_planner_statistics", spy)

    db = UserDatabase(db_path=populated, user_id=1, username="stats")
    try:
        assert calls == [populated], (
            "opening a UserDatabase did not write planner statistics, so the "
            "first session runs on an empty sqlite_stat1 again (#218)"
        )
    finally:
        db.close()


@pytest.mark.database
def test_statistics_do_not_change_what_a_query_returns(populated):
    """A plan change that changes the answer is a corruption, not a speedup.

    #218's method throughout: toggle only the statistics, compare row sets
    for identity. Cheap to assert here and the thing one would most regret
    not having asserted.
    """
    from database import UserDatabase

    def roots(db):
        return [(n.id, n.name) for n in db.get_subject_hierarchy("Stats")]

    # With statistics: the ordinary open path.
    db = UserDatabase(db_path=populated, user_id=1, username="stats")
    try:
        with_stats = roots(db)
    finally:
        db.close()

    # Without: strip them and read on a *fresh* connection. Deleting the rows
    # on the open connection is not enough -- the planner has already loaded
    # them, so the comparison would be against the same plan twice and the
    # test would pass vacuously.
    bare = sqlite3.connect(populated)
    bare.execute("DROP TABLE IF EXISTS sqlite_stat1")
    bare.commit()
    bare.close()

    db = UserDatabase(db_path=populated, user_id=1, username="stats")
    try:
        # The open path would put them straight back, so drop again on this
        # connection and reconnect underneath the same object.
        db.conn.execute("DROP TABLE IF EXISTS sqlite_stat1")
        db.conn.commit()
        db.conn.close()
        db.conn = sqlite3.connect(populated)
        db.conn.row_factory = sqlite3.Row
        assert not _stat1_tables(db.conn), "sqlite_stat1 survived the drop"
        without = roots(db)
    finally:
        db.close()

    assert with_stats == without, (
        "the subject hierarchy differs depending on whether planner "
        "statistics exist, which means a plan is changing the result and not "
        "just the speed"
    )
    assert with_stats, "the fixture produced no roots, so this asserts nothing"
