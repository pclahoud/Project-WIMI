"""``BaseDatabase.transaction()`` nests for real — issue #95.

Before this, ``transaction()`` was a plain ``@contextmanager`` that
``commit()``-ed on exit with no depth counter and no ``SAVEPOINT``. One
method that opened a transaction calling another that did the same — the
normal shape of this layer, ``create_subject_node`` / ``add_edge`` /
``delete_subject_subtree`` are all called from inside other ``with
self.transaction()`` blocks — meant the **inner** ``commit()`` committed
the outer method's work, and the outer ``rollback()`` could only discard
whatever happened after that point.

The fix is a per-connection depth counter plus savepoints:

* depth 1 issues an explicit ``BEGIN`` (guarded on ``in_transaction``)
  and is the only level that ``COMMIT``s,
* depth ≥ 2 issues ``SAVEPOINT`` and exits through ``RELEASE`` or
  ``ROLLBACK TO``.

The explicit ``BEGIN`` is load-bearing rather than tidy: a ``SAVEPOINT``
with no enclosing ``BEGIN`` *starts* a transaction, and SQLite commits
that transaction when the outermost savepoint is ``RELEASE``d. An outer
``with`` block that had not yet issued any DML when the inner one opened
would therefore have been committed by the inner ``RELEASE`` — the same
bug wearing a savepoint. ``test_inner_release_does_not_commit_when_outer_has_not_written_yet``
is the regression test for exactly that.

The first test below is issue #95's reproduction, verbatim.
"""
from __future__ import annotations

import logging
import sqlite3
import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.base_db import BaseDatabase


pytestmark = pytest.mark.database


# ==================== Fixtures ====================

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def test_user(master_db):
    return master_db.create_user(
        username="txn_user",
        display_name="Transaction Nesting User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    yield db
    db.close()


@pytest.fixture
def plain_db(temp_dir):
    """A bare ``BaseDatabase`` with one scratch table.

    The synthetic cases want the transaction machinery with none of the
    schema, triggers or migrations around it, so a failure here points at
    ``base_db.py`` and nothing else.
    """
    db = BaseDatabase(temp_dir / "plain.db")
    db.conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT NOT NULL)")
    db.conn.commit()
    yield db
    db.close()


def _rows(db) -> list:
    return [r["v"] for r in db.fetchall("SELECT v FROM t ORDER BY id")]


def _committed_rows(db) -> list:
    """Read ``t`` through a *second* connection.

    Anything this sees has actually been committed; anything it cannot
    see is still inside the writer's open transaction. Reading through
    ``db`` itself cannot tell the two apart.
    """
    other = sqlite3.connect(str(db.db_path))
    try:
        return [r[0] for r in other.execute("SELECT v FROM t ORDER BY id")]
    finally:
        other.close()


# ==================== Issue #95's reproduction ====================

@pytest.mark.integration
def test_outer_rollback_discards_a_nested_domain_write(user_db):
    """Issue #95's reproduction, verbatim.

    ``with db.transaction():`` → ``db.create_subject_node(...)`` (which
    opens and, before the fix, *committed* its own) → raise. The outer
    rollback must leave no node behind.
    """
    user_db.create_exam_context(exam_name="TXN", exam_description="issue #95")

    with pytest.raises(RuntimeError, match="boom"):
        with user_db.transaction():
            user_db.create_subject_node(
                exam_context="TXN",
                name="Ghost Subject",
                level_type="Domain",
            )
            raise RuntimeError("boom")

    survivors = user_db.fetchall(
        "SELECT id FROM subject_nodes WHERE name = 'Ghost Subject'"
    )
    assert survivors == [], (
        "the node created before the raise survived the outer rollback — "
        "the inner transaction committed it (issue #95)"
    )


# ==================== Synthetic nesting matrix ====================

@pytest.mark.unit
def test_single_level_still_commits(plain_db):
    with plain_db.transaction() as conn:
        conn.execute("INSERT INTO t (v) VALUES ('solo')")
    assert _committed_rows(plain_db) == ["solo"]


@pytest.mark.unit
def test_single_level_failure_still_rolls_back(plain_db):
    with pytest.raises(RuntimeError):
        with plain_db.transaction() as conn:
            conn.execute("INSERT INTO t (v) VALUES ('doomed')")
            raise RuntimeError("nope")
    assert _committed_rows(plain_db) == []


@pytest.mark.unit
def test_nested_success_commits_once_at_the_outermost_exit(plain_db):
    with plain_db.transaction() as conn:
        conn.execute("INSERT INTO t (v) VALUES ('outer')")
        with plain_db.transaction() as inner:
            inner.execute("INSERT INTO t (v) VALUES ('inner')")
        # The inner block has exited. Nothing may be visible yet.
        assert _committed_rows(plain_db) == [], (
            "the inner exit committed — nesting is not real"
        )
    assert _committed_rows(plain_db) == ["outer", "inner"]


@pytest.mark.unit
def test_outer_failure_discards_inner_work_too(plain_db):
    with pytest.raises(RuntimeError):
        with plain_db.transaction() as conn:
            conn.execute("INSERT INTO t (v) VALUES ('outer')")
            with plain_db.transaction() as inner:
                inner.execute("INSERT INTO t (v) VALUES ('inner')")
            raise RuntimeError("outer blew up after the inner succeeded")
    assert _committed_rows(plain_db) == []


@pytest.mark.unit
def test_inner_failure_rolls_back_only_the_inner_work(plain_db):
    """The outer transaction survives an inner one's failure and decides."""
    with plain_db.transaction() as conn:
        conn.execute("INSERT INTO t (v) VALUES ('before')")
        with pytest.raises(ValueError):
            with plain_db.transaction() as inner:
                inner.execute("INSERT INTO t (v) VALUES ('discarded')")
                raise ValueError("inner blew up")
        # The outer transaction is still alive and can keep writing.
        conn.execute("INSERT INTO t (v) VALUES ('after')")

    assert _committed_rows(plain_db) == ["before", "after"]


@pytest.mark.unit
def test_three_levels_deep(plain_db):
    with plain_db.transaction() as c1:
        c1.execute("INSERT INTO t (v) VALUES ('L1')")
        with plain_db.transaction() as c2:
            c2.execute("INSERT INTO t (v) VALUES ('L2')")
            with plain_db.transaction() as c3:
                c3.execute("INSERT INTO t (v) VALUES ('L3')")
            assert _committed_rows(plain_db) == []
        assert _committed_rows(plain_db) == []
    assert _committed_rows(plain_db) == ["L1", "L2", "L3"]


@pytest.mark.unit
def test_three_levels_middle_failure_keeps_level_one(plain_db):
    """A failure at level 2 discards levels 2 and 3, never level 1."""
    with plain_db.transaction() as c1:
        c1.execute("INSERT INTO t (v) VALUES ('L1')")
        with pytest.raises(ValueError):
            with plain_db.transaction() as c2:
                c2.execute("INSERT INTO t (v) VALUES ('L2')")
                with plain_db.transaction() as c3:
                    c3.execute("INSERT INTO t (v) VALUES ('L3')")
                raise ValueError("level 2 blew up")
        c1.execute("INSERT INTO t (v) VALUES ('L1-after')")

    assert _committed_rows(plain_db) == ["L1", "L1-after"]


@pytest.mark.unit
def test_exception_escaping_the_outermost_propagates_to_the_caller(plain_db):
    """The inner re-raise must not be swallowed on its way out."""
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with plain_db.transaction() as conn:
            conn.execute("INSERT INTO t (v) VALUES ('a')")
            with plain_db.transaction() as inner:
                inner.execute("INSERT INTO t (v) VALUES ('b')")
                raise Boom("all the way up")

    assert _committed_rows(plain_db) == []
    assert plain_db.transaction_depth == 0
    assert plain_db.conn.in_transaction is False


@pytest.mark.unit
def test_inner_release_does_not_commit_when_outer_has_not_written_yet(plain_db):
    """The trap the explicit ``BEGIN`` exists to close.

    A ``SAVEPOINT`` issued with no transaction open starts one, and
    SQLite *commits* when the outermost savepoint is released. An outer
    block whose first act is to call an inner writer would therefore be
    committed by that inner writer's exit. Verified empirically against
    Python 3.12 / SQLite 3.45 before the fix was designed.
    """
    with plain_db.transaction():
        # Not a single statement yet at the outer level.
        with plain_db.transaction() as inner:
            inner.execute("INSERT INTO t (v) VALUES ('first write is the inner one')")
        assert _committed_rows(plain_db) == [], (
            "the inner RELEASE committed because no BEGIN was open above it"
        )
        assert plain_db.conn.in_transaction is True
    assert _committed_rows(plain_db) == ["first write is the inner one"]


@pytest.mark.unit
def test_sibling_inner_blocks_are_independent(plain_db):
    """Two inner blocks in a row: one fails, the other still counts."""
    with plain_db.transaction() as conn:
        with pytest.raises(ValueError):
            with plain_db.transaction() as a:
                a.execute("INSERT INTO t (v) VALUES ('sibling-a')")
                raise ValueError("a fails")
        with plain_db.transaction() as b:
            b.execute("INSERT INTO t (v) VALUES ('sibling-b')")
        conn.execute("INSERT INTO t (v) VALUES ('outer')")

    assert _committed_rows(plain_db) == ["sibling-b", "outer"]


@pytest.mark.unit
def test_depth_returns_to_zero_on_both_paths(plain_db):
    assert plain_db.transaction_depth == 0

    with plain_db.transaction():
        assert plain_db.transaction_depth == 1
        with plain_db.transaction():
            assert plain_db.transaction_depth == 2
        assert plain_db.transaction_depth == 1
    assert plain_db.transaction_depth == 0

    with pytest.raises(RuntimeError):
        with plain_db.transaction():
            with plain_db.transaction():
                raise RuntimeError("x")
    assert plain_db.transaction_depth == 0


@pytest.mark.unit
def test_consecutive_top_level_transactions_still_work(plain_db):
    """No leaked BEGIN: a second top-level block must open cleanly."""
    for value in ("one", "two", "three"):
        with plain_db.transaction() as conn:
            conn.execute("INSERT INTO t (v) VALUES (?)", (value,))
        assert plain_db.conn.in_transaction is False

    assert _committed_rows(plain_db) == ["one", "two", "three"]


@pytest.mark.unit
def test_integrity_error_inside_an_inner_block_leaves_the_outer_usable(plain_db):
    """A statement-level constraint failure is still just an exception.

    SQLite does not abandon the transaction for a failed statement, so
    ``ROLLBACK TO`` is a valid recovery and the outer level keeps going.
    """
    with plain_db.transaction() as conn:
        conn.execute("INSERT INTO t (id, v) VALUES (1, 'keep')")
        with pytest.raises(sqlite3.IntegrityError):
            with plain_db.transaction() as inner:
                inner.execute("INSERT INTO t (id, v) VALUES (1, 'dup')")
        conn.execute("INSERT INTO t (id, v) VALUES (2, 'also keep')")

    assert _committed_rows(plain_db) == ["keep", "also keep"]


@pytest.mark.unit
def test_foreign_keys_are_still_enforced_inside_a_nested_block(plain_db):
    """WAL + ``PRAGMA foreign_keys=ON`` still bite inside a savepoint."""
    plain_db.conn.execute("CREATE TABLE par (id INTEGER PRIMARY KEY)")
    plain_db.conn.execute(
        "CREATE TABLE ch (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES par(id))"
    )
    plain_db.conn.commit()

    with plain_db.transaction() as conn:
        conn.execute("INSERT INTO par (id) VALUES (1)")
        with pytest.raises(sqlite3.IntegrityError):
            with plain_db.transaction() as inner:
                inner.execute("INSERT INTO ch (pid) VALUES (999)")
        conn.execute("INSERT INTO ch (pid) VALUES (1)")

    assert _committed_rows(plain_db) == []  # table t untouched
    rows = plain_db.fetchall("SELECT pid FROM ch")
    assert [r["pid"] for r in rows] == [1]


# ==================== Logging ====================

@pytest.mark.unit
def test_both_levels_log_a_rollback_and_say_which(plain_db, caplog):
    """CLAUDE.md: this line is usually the only evidence a write failed."""
    with caplog.at_level(logging.ERROR, logger="database.base_db"):
        with pytest.raises(ValueError):
            with plain_db.transaction() as conn:
                conn.execute("INSERT INTO t (v) VALUES ('x')")
                with plain_db.transaction():
                    raise ValueError("inner")

    messages = [r.getMessage() for r in caplog.records]
    assert any("savepoint" in m for m in messages), messages
    assert any("Transaction failed, rolled back" in m for m in messages), messages


# ==================== A real composite through the domain layer ====================

@pytest.mark.integration
def test_delete_subject_subtree_is_atomic_inside_a_caller_transaction(user_db):
    """``delete_subject_subtree`` opens its own transaction and is a
    multi-mutation composite (archive, unwire edges, null pinned parents,
    hide relations). Wrapped in a caller's transaction that then fails,
    none of it may survive.
    """
    user_db.create_exam_context(exam_name="TXN", exam_description="issue #95")
    root = user_db.create_subject_node(
        exam_context="TXN", name="Root", level_type="Domain"
    )
    child = user_db.create_subject_node(
        exam_context="TXN", name="Child", level_type="Topic", parent_id=root.id
    )

    before = user_db.fetchone(
        "SELECT status FROM subject_nodes WHERE id = ?", (child.id,)
    )
    assert before["status"] == "active"

    with pytest.raises(RuntimeError, match="composite blew up"):
        with user_db.transaction():
            user_db.delete_subject_subtree(root.id)
            raise RuntimeError("composite blew up")

    after_root = user_db.fetchone(
        "SELECT status FROM subject_nodes WHERE id = ?", (root.id,)
    )
    after_child = user_db.fetchone(
        "SELECT status FROM subject_nodes WHERE id = ?", (child.id,)
    )
    assert after_root["status"] == "active", "the archive survived the rollback"
    assert after_child["status"] == "active", "the cascade survived the rollback"

    batches = user_db.fetchall("SELECT id FROM subject_delete_batches")
    assert batches == [], "the delete journal survived the rollback"

    edges = user_db.fetchall(
        "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
        (root.id, child.id),
    )
    assert len(edges) == 1, "the unwired edge was not restored"


@pytest.mark.integration
def test_delete_subject_subtree_alone_still_commits(user_db):
    """The counterpart: unwrapped, the same call must still land."""
    user_db.create_exam_context(exam_name="TXN", exam_description="issue #95")
    root = user_db.create_subject_node(
        exam_context="TXN", name="Root", level_type="Domain"
    )

    user_db.delete_subject_subtree(root.id)

    other = sqlite3.connect(str(user_db.db_path))
    try:
        status = other.execute(
            "SELECT status FROM subject_nodes WHERE id = ?", (root.id,)
        ).fetchone()[0]
    finally:
        other.close()
    assert status == "archived"
