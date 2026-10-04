"""A ``UserDatabase`` whose ``__init__`` fails must not leave a handle open
(#292) and must not then raise a second, irrelevant exception (#281).

Both issues are one defect. ``__init__`` connects at ``user_db.py``'s
``super().__init__(db_path)`` and *then* runs the migration runner, claims
m021's handover row, initialises the graph and writes planner statistics. A
failure anywhere after the connect escapes the constructor with the
connection live, and — because the exception escapes before the assignment
completes — **the caller is never handed the object it would have to close**.
``profile_archive.install_profile_as_new``'s rollback is written correctly
against an object it cannot get: ``if verify_db is not None`` is False
precisely when there is something to close.

Why these tests and not the one that is already red on Windows
--------------------------------------------------------------
``tests/app/test_profile_import_logging.py``'s rollback test fails on
Windows and passes on Linux and macOS, because POSIX unlinks an open file
freely (#292 comment, measured on an M4). So the *orphan file* is not
observable here. What is observable on every platform is the **mechanism**:
the connection the constructor opened. That is what Windows needs closed,
and asserting it directly is both portable and closer to the defect than
asserting on a directory listing.

How the connection is observed
------------------------------
``self.conn is None`` would be satisfied by an implementation that merely
dropped the reference, which is exactly the thing that does not help
Windows. So ``sqlite3.connect`` is spied on and the real connection object
is interrogated afterwards: a closed one raises ``ProgrammingError``. The
half-built instance itself is recovered the way #281 says it stays
reachable — through ``exc.__traceback__`` → the constructor's frame →
``self``.

``gc.collect()`` is deliberately not used as a fix anywhere here; #281
comment #4076 measured that it does not release the handle, because the
exception keeps the frame alive.

Two instances beyond the filed ones
-----------------------------------
#281 asked to "check the same question for the other attributes
``__init__`` sets after the runner, and for ``BaseDatabase.__del__``
generally". Doing so found two more, both covered below and both fixed by
the same two changes:

* ``MasterDatabase.__init__`` has the identical connect-then-migrate
  ordering, so a failing *master* migration left ``users.db`` open.
* ``BaseDatabase.close()`` reads ``self.conn``, which is absent on an
  instance that never entered ``BaseDatabase.__init__`` — reachable,
  measured, through ``MasterDatabase``'s three ``mkdir`` calls, which run
  before ``super().__init__``.
"""
from __future__ import annotations

import gc
import sqlite3
import sys

import pytest

from database.master_db import MasterDatabase
from database.migration_runner import Migration
from database.user_db import UserDatabase


# ==================== helpers ====================

def _failing_registry(real_registry):
    """The real registry plus one migration that always raises.

    Same technique as ``tests/database/migrations/`` and
    ``tests/app/test_profile_import_logging.py``: the failure branch is
    otherwise hard to reach, because every shipped migration is idempotent
    and ``preflight_schema`` intercepts the two real hard failures before
    any open happens.

    v26 is pending on every database — CLAUDE.md reserves 26 and up for
    exactly this reason, m025 being the highest shipped.
    """
    def explode(conn):
        raise sqlite3.OperationalError("deliberate failure from the test")

    return list(real_registry) + [
        Migration(version=26, name="deliberate_failure", upgrade_fn=explode)
    ]


class _ConnectionSpy:
    """Records the real ``sqlite3.Connection`` objects opened for one path."""

    def __init__(self, monkeypatch, db_path):
        self.opened = []
        real_connect = sqlite3.connect
        wanted = str(db_path)

        def spy(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            if args and str(args[0]) == wanted:
                self.opened.append(conn)
            return conn

        monkeypatch.setattr(sqlite3, "connect", spy)

    @property
    def only(self):
        assert len(self.opened) == 1, (
            f"expected exactly one connection to the user database, "
            f"got {len(self.opened)}"
        )
        return self.opened[0]

    @staticmethod
    def is_open(conn) -> bool:
        try:
            conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.ProgrammingError:
            return False


def _half_built_from(exc):
    """The ``UserDatabase`` ``__init__`` was building when ``exc`` escaped.

    #281 names this reachability chain as the reason the object — and so
    the handle — outlives the constructor: the exception holds the
    traceback, the traceback holds the frame, the frame holds ``self``.
    """
    found = None
    tb = exc.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        if frame.f_code.co_name == "__init__":
            candidate = frame.f_locals.get("self")
            if isinstance(candidate, UserDatabase):
                found = candidate
        tb = tb.tb_next
    return found


# ==================== fixtures ====================

@pytest.fixture
def master(tmp_path):
    db = MasterDatabase(data_dir=tmp_path / "master", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def user_db_path(master):
    """A real, fully migrated user database file to open again."""
    user = master.create_user(username="dana", display_name="Dana")
    return master.ensure_user_database(user.id), user


@pytest.fixture
def failing_migrations(monkeypatch):
    """Make the next ``UserDatabase(...)`` fail after it has connected."""
    import database.migrations.user as user_migrations

    monkeypatch.setattr(
        user_migrations,
        "MIGRATIONS",
        _failing_registry(user_migrations.MIGRATIONS),
    )


# ==================== #292: the handle ====================

def test_a_failed_constructor_closes_the_connection_it_opened(
    user_db_path, failing_migrations, monkeypatch
):
    """The thing Windows actually needs, asserted on the real connection.

    Unfixed, this is the leaked handle that makes
    ``_remove_db_artifacts``' unlink raise ``PermissionError(13)`` there
    and leaves an orphan ``user_NNN_<name>.db`` with the registry row
    already gone.
    """
    db_path, user = user_db_path
    spy = _ConnectionSpy(monkeypatch, db_path)

    # `as excinfo` is load-bearing, not habit. Without a binding, pytest's
    # ExceptionInfo dies at the end of the `with`, and with it the
    # traceback -> frame -> `self` chain; CPython then refcounts the
    # half-built object away immediately and `__del__` -> `close()` closes
    # the connection *for* the test. That version of this test PASSES
    # against the unfixed code -- measured, on the master-database twin
    # below, which was written without the binding first. Holding the
    # exception is also the honest shape: it is exactly what a caller's
    # `except` block does, and it is why #281 says the handle outlives the
    # constructor.
    with pytest.raises(Exception) as excinfo:
        UserDatabase(db_path=db_path, user_id=user.id, username=user.username)

    assert not spy.is_open(spy.only), (
        "the constructor failed with its SQLite connection still open; on "
        "Windows the import rollback cannot unlink the file (#292)"
    )
    assert excinfo.value is not None  # keep the traceback alive to here


def test_the_half_built_object_reports_no_connection(
    user_db_path, failing_migrations
):
    """The same fact from the object's side, and the weaker of the two.

    Kept because it is the assertion a reader of ``close()`` would reach
    for, and because it pins ``close()`` having been *entered* rather than
    the attribute having been cleared by hand — ``BaseDatabase.close``
    sets ``conn = None`` only after ``conn.close()``.
    """
    db_path, user = user_db_path

    try:
        UserDatabase(db_path=db_path, user_id=user.id, username=user.username)
    except Exception as exc:
        half = _half_built_from(exc)
    else:  # pragma: no cover - the fixture guarantees a failure
        pytest.fail("the constructor was expected to fail")

    assert half is not None, (
        "could not recover the half-built instance from the traceback; "
        "#281's reachability claim no longer holds and this file's "
        "reasoning needs re-reading"
    )
    assert half.conn is None


def test_a_successful_constructor_leaves_the_connection_open(
    user_db_path, monkeypatch
):
    """Negative control, and the one that matters most.

    Every other test here is satisfied by a mutant that closes the
    connection unconditionally — which would break the whole application
    while turning this file green. No ``failing_migrations`` fixture: this
    is the ordinary open path.
    """
    db_path, user = user_db_path
    spy = _ConnectionSpy(monkeypatch, db_path)

    db = UserDatabase(
        db_path=db_path, user_id=user.id, username=user.username
    )
    try:
        assert db.conn is not None
        assert spy.is_open(spy.only)
        assert db.fetchone("SELECT 1 AS n")["n"] == 1
    finally:
        db.close()

    assert not spy.is_open(spy.only)


def test_the_caller_still_sees_the_original_failure(
    user_db_path, failing_migrations
):
    """Cleanup must never replace the diagnosis.

    A close that raised inside the new handler would surface instead of
    the migration error, which is #281's complaint — an irrelevant
    exception at the worst possible moment — reintroduced by the fix for
    it. The runner wraps the test's ``OperationalError`` in
    ``MigrationFailedError``; both the version and the cause must survive.
    """
    from database.migration_runner import MigrationFailedError

    db_path, user = user_db_path

    with pytest.raises(MigrationFailedError) as excinfo:
        UserDatabase(db_path=db_path, user_id=user.id, username=user.username)

    assert "026" in str(excinfo.value)
    assert "deliberate_failure" in str(excinfo.value)


# ==================== #281: the misleading AttributeError ====================

def test_close_graph_tolerates_an_instance_that_never_reached_init_graph():
    """``_close_graph`` is reached from ``__del__`` on a half-built object.

    ``_init_graph`` is what assigns ``_graph_conn``, and it runs *after*
    the migration runner, so the attribute is simply absent on this path.
    No database is opened here: the point is that the attribute read must
    not depend on ``__init__`` having completed, and ``object.__new__``
    states that as narrowly as it can be stated.
    """
    orphan = object.__new__(UserDatabase)

    orphan._close_graph()  # must not raise AttributeError

    assert orphan._graph_conn is None
    assert orphan._graph_db is None


def test_close_tolerates_an_instance_that_never_entered_base_init(tmp_path):
    """#281's own follow-up question, answered: the same bug one level down.

    That issue asked to "check the same question for the other attributes
    ``__init__`` sets after the runner, and for ``BaseDatabase.__del__``
    generally: a ``__del__`` that assumes a complete ``__init__`` is the
    general shape of this bug". It is, and the second instance was
    **reachable in production**, measured:

    ``MasterDatabase.__init__`` runs three ``mkdir`` calls *before*
    ``super().__init__``, so ``--app-data-dir`` pointing at a path under a
    **file** raises ``NotADirectoryError`` with ``self.conn`` never
    assigned. ``__del__`` then printed ``AttributeError: 'MasterDatabase'
    object has no attribute 'conn'`` on top of the real error — the same
    irrelevant-diagnostic-at-the-worst-moment #281 is about, by another
    route. Fixed the way ``_txn_depth`` already was: a class-level
    default.
    """
    blocker = tmp_path / "not_a_dir"
    blocker.write_bytes(b"i am a file, not a directory")

    with pytest.raises(OSError):
        MasterDatabase(data_dir=blocker / "wimi", error_logger=None)

    # The narrow statement, independent of when the interpreter collects:
    # close() must survive an instance that never reached BaseDatabase's
    # own __init__, which is the only state in which `conn` is absent.
    orphan = object.__new__(MasterDatabase)
    orphan.close()
    assert orphan.conn is None


def test_collecting_a_failed_userdatabase_raises_nothing(
    user_db_path, failing_migrations, monkeypatch
):
    """End-to-end: the ``AttributeError`` on stderr, gone.

    Its cost was never lost data — it is that a failed import printed a
    traceback naming the *graph* subsystem, which is not what went wrong.
    ``sys.unraisablehook`` is installed directly rather than relying on
    pytest's own unraisable plugin, so the collection point is inside the
    test and the assertion is about this constructor rather than about
    whenever the interpreter got round to it.
    """
    db_path, user = user_db_path

    seen = []
    monkeypatch.setattr(sys, "unraisablehook", seen.append)

    try:
        UserDatabase(db_path=db_path, user_id=user.id, username=user.username)
    except Exception:
        pass  # the traceback, and with it the frame holding `self`, dies here

    gc.collect()

    assert [str(u.exc_value) for u in seen] == []


def test_collecting_a_failed_masterdatabase_raises_nothing(
    tmp_path, monkeypatch
):
    """The reachable half of the above, end to end.

    A student can produce this one: ``--app-data-dir`` naming a path under
    a file. What they should see is ``NotADirectoryError`` naming the
    path, and nothing else.
    """
    blocker = tmp_path / "not_a_dir"
    blocker.write_bytes(b"i am a file, not a directory")

    seen = []
    monkeypatch.setattr(sys, "unraisablehook", seen.append)

    try:
        MasterDatabase(data_dir=blocker / "wimi", error_logger=None)
    except OSError:
        pass

    gc.collect()

    assert [str(u.exc_value) for u in seen] == []


# ==================== the master database has the same shape ================

def test_a_failed_master_init_closes_its_connection(tmp_path, monkeypatch):
    """Not the issue that was filed, and the same two lines.

    #292 is about the per-user database, because that is where a rollback
    has to unlink the file. ``MasterDatabase.__init__`` has the identical
    connect-then-migrate ordering, so a failing *master* migration left
    ``users.db`` open for the life of the process — and on Windows a
    leaked handle on ``users.db`` is what turns one failing test into a
    failure plus a teardown error (CLAUDE.md, Testing).
    """
    opened = []
    real_connect = sqlite3.connect

    def spy(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        if args and str(args[0]).endswith("users.db"):
            opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", spy)

    def explode(self):
        raise sqlite3.OperationalError("deliberate failure from the test")

    monkeypatch.setattr(MasterDatabase, "_initialize_schema", explode)

    # `as excinfo` for the reason spelled out on the UserDatabase test
    # above: this test is where that was found. Written without the
    # binding it passed against the unfixed code, because dropping the
    # exception let `__del__` close the connection before the assertion
    # ran. `MasterDatabase` has no `GraphMixin`, so nothing interrupted
    # its `close()` -- which is why the same omission on the user-database
    # test was still red there and the hole was invisible from that side.
    with pytest.raises(sqlite3.OperationalError) as excinfo:
        MasterDatabase(data_dir=tmp_path / "master", error_logger=None)

    assert len(opened) == 1
    assert not _ConnectionSpy.is_open(opened[0])
    assert excinfo.value is not None  # keep the traceback alive to here
