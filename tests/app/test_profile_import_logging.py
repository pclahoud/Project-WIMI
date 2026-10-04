"""A profile import's verify-open must leave evidence in the log file (#131).

`install_profile_as_new` and `replace_profile` each open the freshly copied
user database to run pending migrations and read the profile id back. Both
constructed that `UserDatabase` **without** `error_logger`, against
CLAUDE.md's *Logging* invariant 2.

What that actually costs, measured rather than assumed
------------------------------------------------------
#131 says the omission loses "the rollback line that is usually the only
evidence a transaction failed". It does not, and neither does CLAUDE.md's
wording for that invariant: `BaseDatabase` has **no** `error_logger` at all
(zero occurrences), and `transaction()`'s rollback line is
`logging.getLogger(__name__).error(...)` in `base_db.py`. That reaches the
file through the stdlib handler invariant 1 attaches to the `database`
package root, so it survives `error_logger=None` intact — verified by
constructing a `UserDatabase` with no logger, failing a transaction, and
finding `Transaction failed, rolled back` in the file anyway.

What the omission really loses is the **migration runner's** narrative.
`MigrationRunner._log` returns immediately when its logger is `None`, and
`migration_runner.py` has no stdlib logger of its own — it does not even
import `logging`. So with no logger the verify-open records nothing about
which migrations it applied, and nothing about one that failed. Measured on
one import of an older-schema archive: 6 log lines without a logger, 46
with, the difference being the whole `Applying/Applied user migration vNNN`
trail.

That matters here more than anywhere else, because the verify-open is
exactly the step that upgrades an archive built by an older WIMI, and it
sits inside the import's rollback handler.

Why the tests below take the shapes they do
-------------------------------------------
The trail test uses a real older-schema archive and no patching, because
that is the reachable, everyday consequence of the fix.

The failure test substitutes the migration registry, and does so because
the failure branch is genuinely hard to reach otherwise — which is a
compliment to the code around it, not a gap in the test. `preflight_schema`
deliberately intercepts the two hard failures (a newer schema, a checksum
divergence) *before* any verify-open, turning them into friendly verdicts;
and every shipped migration is idempotent (`add_column_if_missing` returns
`False` on a missing table, the DDL uses `CREATE TABLE IF NOT EXISTS`, and
m019 clears its own scratch table), so re-running one against a
half-applied database succeeds. Three realistic corruptions were tried
against the real registry and all three imported cleanly. Substituting the
registry is the same technique `tests/database/migrations/` already uses.

Both are asserted against the log **file on disk**, per CLAUDE.md, not the
in-memory buffer.
"""
from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from app_logging import ErrorLogger
from app.profile_archive import (
    ProfileImportError,
    build_profile_archive,
    install_profile_as_new,
    replace_profile,
)
from database.master_db import MasterDatabase
from database.migration_runner import Migration
from database.user_db import UserDatabase

# The repo's `src/`, resolved from this file rather than from the working
# directory. A relative literal here passes under `pytest` from the repo
# root and fails anywhere else -- the same cwd dependence as #257 item 2.
SRC = Path(__file__).resolve().parents[2] / "src"


# ==================== helpers ====================

def _seed(master: MasterDatabase, user) -> None:
    """Open the user's DB (which runs every migration) and add one entry."""
    db = UserDatabase(
        db_path=master.ensure_user_database(user.id),
        user_id=user.id,
        username=user.username,
    )
    try:
        with db.transaction():
            cur = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, "Sample Exam"),
            )
            cur = db.execute(
                "INSERT INTO review_sessions "
                "(user_id, exam_context_id, total_questions, total_incorrect) "
                "VALUES (?, ?, ?, ?)",
                (user.id, cur.lastrowid, 10, 1),
            )
            db.execute(
                "INSERT INTO question_entries "
                "(review_session_id, entry_order, user_answer, correct_answer) "
                "VALUES (?, ?, ?, ?)",
                (cur.lastrowid, 1, "a", "b"),
            )
    finally:
        db.close()


def _rewrite_archive_db(archive: Path, dest: Path, mutate) -> Path:
    """Copy ``archive`` to ``dest`` with ``mutate(conn)`` applied to user.db."""
    work = dest.parent / f"{dest.stem}_work"
    work.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(archive)) as zf:
        zf.extract("user.db", str(work))
    db = work / "user.db"
    conn = sqlite3.connect(str(db))
    try:
        mutate(conn)
        conn.commit()
    finally:
        conn.close()
    with zipfile.ZipFile(str(archive)) as src, \
            zipfile.ZipFile(str(dest), "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            if item.filename != "user.db":
                out.writestr(item, src.read(item.filename))
        out.write(str(db), "user.db")
    return dest


def _forget_migrations_above(version: int):
    """Make an archive look like it came from an older WIMI."""
    def mutate(conn: sqlite3.Connection) -> None:
        conn.execute(
            "DELETE FROM schema_migrations WHERE version > ?", (version,)
        )
    return mutate


def _log_text(log_dir: Path) -> str:
    """Everything the logger has written to disk, as one string."""
    return "\n".join(
        f.read_text(encoding="utf-8") for f in sorted(log_dir.glob("*.log"))
    )


# ==================== fixtures ====================

@pytest.fixture
def log_dir(tmp_path):
    return tmp_path / "logs"


@pytest.fixture
def error_logger(log_dir):
    """A real ErrorLogger writing to a temp directory.

    ``flush_interval`` is short but the tests still call ``flush()``
    explicitly: only ERROR and above are flushed on log(), so a WARNING
    or INFO would otherwise sit in the queue.
    """
    logger = ErrorLogger(
        app_name="ImportLoggingTest",
        log_dir=log_dir,
        mode="production",
        flush_interval=0.1,
    )
    yield logger
    logger.cleanup()


@pytest.fixture
def source_master(tmp_path):
    db = MasterDatabase(data_dir=tmp_path / "source", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def dest_master(tmp_path, error_logger):
    """The import side. Carries the logger, as every production master does."""
    db = MasterDatabase(data_dir=tmp_path / "dest", error_logger=error_logger)
    yield db
    db.close()


@pytest.fixture
def older_archive(source_master, tmp_path):
    """An archive whose database reports an older schema than this WIMI.

    Its migrations above v10 are un-stamped, so the receiving verify-open
    has real work to do and a real narrative to record. The columns are
    all still there, so the re-run is a no-op on the data — what is being
    tested is the logging, not the migrations.
    """
    user = source_master.create_user(username="alice", display_name="Alice")
    _seed(source_master, user)
    pristine = tmp_path / "alice.wimi"
    build_profile_archive(source_master, user.id, pristine, include_media=False)
    return _rewrite_archive_db(
        pristine, tmp_path / "alice_older.wimi", _forget_migrations_above(10)
    )


@pytest.fixture
def current_archive(source_master, tmp_path):
    """An unmodified archive from this same WIMI version."""
    user = source_master.create_user(username="dana", display_name="Dana")
    _seed(source_master, user)
    dest = tmp_path / "dana.wimi"
    build_profile_archive(source_master, user.id, dest, include_media=False)
    return dest


# ==================== the upgrade narrative reaches the file ====================

class TestTheUpgradeIsRecorded:
    """One test per construction site: #131 is a per-site defect.

    `tests/database/test_logger_category_types.py` makes the same point --
    "the failure is per call site, not per behaviour, so exercising one
    path proves nothing about the other six". Install and replace are two
    sites and each was missing the argument independently.
    """

    def test_install_records_the_migrations_its_verify_open_applied(
        self, dest_master, older_archive, log_dir, error_logger
    ):
        result = install_profile_as_new(dest_master, older_archive)
        assert result["entries"] == 1

        error_logger.flush()
        text = _log_text(log_dir)

        # The runner names the scope, so a *user* migration line can only
        # have come from the verify-open -- master's own migrations ran
        # through MasterDatabase, which always had a logger.
        assert "Applying user migration v015" in text
        assert "Applied user migration v025" in text

    def test_replace_records_the_migrations_its_verify_open_applied(
        self, dest_master, older_archive, log_dir, error_logger
    ):
        target = dest_master.create_user(username="bob", display_name="Bob")
        _seed(dest_master, target)
        active = dest_master.create_user(username="carol", display_name="Carol")

        result = replace_profile(
            dest_master,
            older_archive,
            target_user_id=target.id,
            active_user_id=active.id,
            confirm_replace=True,
        )
        assert result["entries"] == 1

        error_logger.flush()
        text = _log_text(log_dir)
        assert "Applying user migration v015" in text
        assert "Applied user migration v025" in text

    def test_a_current_archive_needs_no_upgrade_and_says_nothing(
        self, dest_master, current_archive, log_dir, error_logger
    ):
        """Negative control.

        Without this, a test asserting on the trail would also pass for an
        implementation that logged migration lines unconditionally. An
        archive from this version has nothing pending, so the verify-open
        must be silent about user migrations.
        """
        install_profile_as_new(dest_master, current_archive)

        error_logger.flush()
        assert "user migration" not in _log_text(log_dir)


# ==================== a failed verify-open leaves evidence ====================

def _failing_registry(real_registry):
    """The real registry plus one migration that always raises."""
    def explode(conn):
        raise sqlite3.OperationalError("deliberate failure from the test")

    return list(real_registry) + [
        Migration(version=26, name="deliberate_failure", upgrade_fn=explode)
    ]


class TestAFailedVerifyOpenLeavesEvidence:

    def test_the_log_names_the_migration_that_failed_and_the_import_rolls_back(
        self, dest_master, current_archive, log_dir, error_logger, monkeypatch
    ):
        """The case #131 is really about.

        `UserDatabase.__init__` imports the registry lazily, so patching it
        reaches the verify-open. v26 is pending on any archive, fails, and
        `MigrationRunner._apply_one` logs
        "Migration user/v026 (...) failed: ... Rolled back." through
        `self.error_logger` and through nothing else, before raising.

        Without the fix the student gets `ProfileImportError` naming the
        archive and the log file says nothing at all about the step.
        """
        import database.migrations.user as user_migrations

        monkeypatch.setattr(
            user_migrations,
            "MIGRATIONS",
            _failing_registry(user_migrations.MIGRATIONS),
        )

        with pytest.raises(ProfileImportError):
            install_profile_as_new(dest_master, current_archive)

        error_logger.flush()
        text = _log_text(log_dir)

        assert "Migration user/v026" in text
        assert "deliberate_failure" in text
        assert "Rolled back" in text
        # Logged at ERROR, which is also why it reaches the file promptly:
        # log() flushes ERROR and above immediately.
        assert '"level": "ERROR"' in text

    def test_the_import_still_rolls_back_cleanly(
        self, dest_master, current_archive, monkeypatch
    ):
        """Guard: the logging change must not alter the rollback itself.

        A log call added inside the rollback handler could plausibly throw
        and mask it, so assert the documented "leave zero residue" outcome
        still holds on the failing path.
        """
        import database.migrations.user as user_migrations

        monkeypatch.setattr(
            user_migrations,
            "MIGRATIONS",
            _failing_registry(user_migrations.MIGRATIONS),
        )

        with pytest.raises(ProfileImportError):
            install_profile_as_new(dest_master, current_archive)

        assert dest_master.fetchall("SELECT id FROM users") == []
        leftover = list(dest_master.users_dir.glob("*.db"))
        assert leftover == []


# ==================== the wiring itself ====================

def test_both_verify_opens_pass_the_masters_logger(dest_master, error_logger):
    """The narrow version of the above, kept for its error message.

    The behavioural tests are the real guard, but they fail with "no
    migration line in the log", which does not point at the construction
    site. This one names the invariant directly, the way CLAUDE.md states
    it: the logger a verify-open uses is the master's, never a new one.
    """
    source = (SRC / "app" / "profile_archive.py").read_text(encoding="utf-8")
    assert source.count("verify_db = UserDatabase(") == 2
    assert source.count("error_logger=master_db.error_logger") == 2
    # Invariant 3: never let a component mint a second ErrorLogger.
    assert "ErrorLogger(" not in source

    assert dest_master.error_logger is error_logger
