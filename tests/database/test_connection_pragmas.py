"""The connection's durability, transaction-control and ANALYZE settings.

Three settings that are invisible until they are wrong, and one of them
(`autocommit`) is scheduled to change underneath this code in a future
Python release. Each is asserted against a real connection rather than by
reading the source, because the failure mode for all three is "the pragma
silently did not take".

The rejected alternative is tested too. `autocommit=False` (PEP 249
mode) is what CPython's docs recommend in general, and it is wrong *here*
for two measured reasons -- see `test_pep249_mode_would_break_wal_setup`
and `test_pep249_mode_would_pin_a_read_snapshot`. Those two tests exist
so that "the docs recommend False" does not quietly become a change
somebody makes on a reasonable-looking afternoon.
"""

from __future__ import annotations

import sqlite3

import pytest

from database.base_db import BaseDatabase


@pytest.fixture
def db(tmp_path):
    """A connected BaseDatabase on a real file (WAL needs one)."""
    database = BaseDatabase(tmp_path / "pragmas.db")
    yield database
    if database.conn is not None:
        database.close()


@pytest.mark.database
def test_wal_mode_is_on(db):
    assert db.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


@pytest.mark.database
def test_synchronous_is_normal(db):
    """FULL syncs the WAL on every commit; WIMI commits per field edit."""
    # 0=OFF, 1=NORMAL, 2=FULL. NORMAL is safe under WAL -- it cannot
    # corrupt the database, it can only lose the last commits on a power
    # cut. OFF can corrupt, and must never appear here.
    assert db.conn.execute("PRAGMA synchronous").fetchone()[0] == 1


@pytest.mark.database
def test_foreign_keys_are_on(db):
    assert db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


@pytest.mark.database
def test_analysis_limit_is_bounded(db):
    """An un-capped PRAGMA optimize could stall close() on SQLite < 3.46."""
    assert db.conn.execute("PRAGMA analysis_limit").fetchone()[0] == 1000


@pytest.mark.database
@pytest.mark.skipif(
    not hasattr(sqlite3, "LEGACY_TRANSACTION_CONTROL"),
    reason="autocommit arrived in Python 3.12; CI still runs 3.11",
)
def test_transaction_control_is_pinned_to_legacy(db):
    """The stdlib default is documented as flipping to False later.

    `transaction()` is written against legacy control -- it is why the
    explicit BEGIN at depth 1 exists (#95). Inheriting the default would
    let a Python upgrade change that without a diff.
    """
    assert db.conn.autocommit == sqlite3.LEGACY_TRANSACTION_CONTROL


@pytest.mark.database
def test_close_runs_optimize_and_closes(db):
    """ANALYZE on close is what keeps the planner's stats from going stale.

    Observed with a trace callback rather than by patching ``execute`` --
    ``sqlite3.Connection.execute`` is read-only and cannot be replaced.
    """
    executed: list[str] = []
    db.conn.set_trace_callback(executed.append)

    db.close()

    assert any("optimize" in sql.lower() for sql in executed), executed
    assert db.conn is None, "close() must still release the connection"


@pytest.mark.database
def test_close_survives_a_failing_optimize(db):
    """A leaked handle is a real problem on Windows; stale stats are not.

    The failure is staged the way it would really arrive: the connection
    is already unusable by the time close() is reached, which is exactly
    the case where close() matters most.
    """
    db.conn.close()  # the connection is dead before close() is called

    db.close()  # must not raise

    assert db.conn is None


@pytest.mark.database
def test_optimize_actually_writes_planner_statistics(db):
    """The point of the pragma, not just that the statement was issued."""
    db.conn.execute("CREATE TABLE widget(id INTEGER PRIMARY KEY, kind TEXT)")
    db.conn.execute("CREATE INDEX idx_widget_kind ON widget(kind)")
    db.conn.executemany(
        "INSERT INTO widget(kind) VALUES (?)",
        [("a",) if i % 3 else ("b",) for i in range(200)],
    )
    db.conn.commit()
    # PRAGMA optimize only analyses tables the session actually used.
    db.conn.execute("SELECT * FROM widget WHERE kind = 'a'").fetchall()

    path = db.db_path
    db.close()

    reopened = sqlite3.connect(str(path))
    try:
        stats = reopened.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'sqlite_stat1'"
        ).fetchone()[0]
    finally:
        reopened.close()

    assert stats == 1, (
        "close() issued PRAGMA optimize but no statistics were written; "
        "the planner is still working from nothing"
    )


# --------------------------------------------------------------------------
# Why autocommit=False is NOT used, measured rather than asserted by comment.
# --------------------------------------------------------------------------

@pytest.mark.database
@pytest.mark.skipif(
    not hasattr(sqlite3, "LEGACY_TRANSACTION_CONTROL"),
    reason="autocommit arrived in Python 3.12",
)
def test_pep249_mode_would_break_wal_setup(tmp_path):
    """Reason 1: WAL cannot be entered from inside a transaction.

    PEP 249 mode keeps one open at all times, so `_connect`'s own
    `PRAGMA journal_mode = WAL` would raise.
    """
    conn = sqlite3.connect(str(tmp_path / "pep249.db"), autocommit=False)
    try:
        with pytest.raises(sqlite3.OperationalError, match="wal mode"):
            conn.execute("PRAGMA journal_mode = WAL")
    finally:
        conn.close()


@pytest.mark.database
@pytest.mark.skipif(
    not hasattr(sqlite3, "LEGACY_TRANSACTION_CONTROL"),
    reason="autocommit arrived in Python 3.12",
)
def test_pep249_mode_would_pin_a_read_snapshot(tmp_path):
    """Reason 2, the serious one: it would make #155 the normal case.

    With a transaction always open, a bare SELECT holds a read snapshot
    until the next commit. A held snapshot blocks a TRUNCATE checkpoint
    (busy=1), and a blocked checkpoint is what leaves a copied database
    missing its WAL tail. A GUI process holding one connection for hours
    would be in that state almost permanently.
    """
    path = tmp_path / "snapshot.db"
    setup = sqlite3.connect(str(path))
    setup.execute("PRAGMA journal_mode = WAL")
    setup.execute("CREATE TABLE t(a)")
    setup.commit()
    setup.close()

    reader = sqlite3.connect(str(path), autocommit=False)
    writer = sqlite3.connect(str(path))
    try:
        reader.execute("SELECT * FROM t").fetchall()  # pins the snapshot
        assert reader.in_transaction, "PEP 249 mode should hold a transaction"

        for i in range(200):
            writer.execute("INSERT INTO t VALUES (?)", (i,))
        writer.commit()

        busy, _log, _ckpt = writer.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        assert busy == 1, (
            "expected the pinned read snapshot to block the checkpoint; if "
            "this ever stops being true, the reason for pinning legacy "
            "transaction control is worth re-measuring"
        )
    finally:
        reader.close()
        writer.close()


@pytest.mark.database
def test_legacy_mode_does_not_pin_a_read_snapshot(tmp_path):
    """The negative control: today's mode leaves the checkpoint free."""
    path = tmp_path / "legacy_snapshot.db"
    setup = sqlite3.connect(str(path))
    setup.execute("PRAGMA journal_mode = WAL")
    setup.execute("CREATE TABLE t(a)")
    setup.commit()
    setup.close()

    reader = sqlite3.connect(str(path))
    writer = sqlite3.connect(str(path))
    try:
        reader.execute("SELECT * FROM t").fetchall()
        assert not reader.in_transaction

        for i in range(200):
            writer.execute("INSERT INTO t VALUES (?)", (i,))
        writer.commit()

        busy, _log, _ckpt = writer.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        assert busy == 0, "a bare SELECT must not hold the checkpoint off"
    finally:
        reader.close()
        writer.close()
