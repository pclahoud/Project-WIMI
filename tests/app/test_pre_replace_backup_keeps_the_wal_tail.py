"""The pre-replace safety backup keeps the WAL tail, or it refuses (#155).

`replace_profile` copies the target's database aside before it overwrites it.
That copy is the *safety net*: the only moment it is ever read is the moment a
replace has already gone wrong. It used to be made by

    _checkpoint_wal(target_db)              # return value discarded
    shutil.copy2(target_db, backup_db)      # the .db alone, no -wal

and `PRAGMA wal_checkpoint(TRUNCATE)` returns `(busy, log_frames,
checkpointed_frames)` where `busy = 1` means the checkpoint was **blocked and
did not complete**. A blocked checkpoint followed by a single-file copy is a
backup missing every commit still sitting in the WAL -- silently, with no
error, in the file a student falls back to when they have already lost
something.

`test_a_pinned_reader_blocks_a_truncate_checkpoint` is the premise and the
negative control for the rest of the file: it builds the busy condition
deliberately and measures both halves (the checkpoint reports busy; a raw copy
of the `.db` alone loses the newest row). If SQLite ever stops behaving that
way, that test fails and says so, rather than leaving the one below passing for
free.

The construction is deterministic, not opportunistic. A checkpoint may not copy
WAL frames past the oldest reader's mark -- doing so would show a reader newer
data than its snapshot -- so pinning a snapshot *before* committing the sentinel
guarantees the sentinel's frames cannot be checkpointed at all. Measured on
Python 3.12.3 / SQLite 3.45.1: `(busy=1, log_frames=1, checkpointed=0)`.
"""
import ast
import sqlite3
import sys
from pathlib import Path

import pytest

from database.master_db import MasterDatabase
from database.user_db import UserDatabase
from app import profile_archive
from app.profile_archive import (
    ProfileImportError,
    build_profile_archive,
    replace_profile,
)

SENTINEL = "answer_committed_into_the_wal"


# ==================== fixtures ====================
# Deliberately local rather than imported from `test_profile_archive.py`:
# `tests/app/` is not a package, so a cross-module fixture import does not
# resolve, and this file is readable on its own.

@pytest.fixture
def source_master(tmp_path):
    """Master DB 'A' -- the export side."""
    db = MasterDatabase(data_dir=tmp_path / "data_a", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def dest_master(tmp_path):
    """A second, fresh master DB 'B' -- the replace side."""
    db = MasterDatabase(data_dir=tmp_path / "data_b", error_logger=None)
    yield db
    db.close()


def _seed_user_db(master_db, user, n_entries: int = 3) -> None:
    """Open the user's DB (runs migrations) and seed exam/session/entries."""
    db = UserDatabase(
        db_path=master_db.ensure_user_database(user.id),
        user_id=user.id,
        username=user.username,
    )
    try:
        with db.transaction():
            cur = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, "Sample Exam"),
            )
            exam_id = cur.lastrowid
            cur = db.execute(
                "INSERT INTO review_sessions "
                "(user_id, exam_context_id, total_questions, total_incorrect) "
                "VALUES (?, ?, ?, ?)",
                (user.id, exam_id, 10, n_entries),
            )
            session_id = cur.lastrowid
            for i in range(1, n_entries + 1):
                db.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, i, f"answer_{i}", f"correct_{i}"),
                )
    finally:
        db.close()


@pytest.fixture
def alice_archive(source_master, tmp_path):
    """A valid `.wimi` with three entries, to replace the target with."""
    alice = source_master.create_user(
        username="alice", display_name="Alice Example", email="alice@example.com"
    )
    _seed_user_db(source_master, alice, n_entries=3)
    dest = tmp_path / "alice.wimi"
    build_profile_archive(source_master, alice.id, dest, include_media=False)
    return dest


def _entry_count(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
    finally:
        conn.close()


# ==================== helpers ====================

def _bob(dest_master):
    """A replace target with one entry, and a second profile to be 'active'."""
    bob = dest_master.create_user(
        username="bob", display_name="Bob Target", email="bob@example.com"
    )
    _seed_user_db(dest_master, bob, n_entries=1)
    carol = dest_master.create_user(username="carol", display_name="Carol Active")
    return bob, carol


def _pin_a_snapshot_then_commit_a_sentinel(db_path: Path):
    """Leave the sentinel committed in the WAL and un-checkpointable.

    Returns (reader, writer); both must be closed by the caller.

    Order is the whole trick: the reader pins its snapshot *before* the
    sentinel is committed, so the sentinel's WAL frames sit past the reader's
    mark where no checkpoint may copy them.
    """
    writer = sqlite3.connect(str(db_path))
    reader = sqlite3.connect(str(db_path))
    if hasattr(sqlite3, "LEGACY_TRANSACTION_CONTROL"):
        # The same transaction control `BaseDatabase._connect` pins, so the
        # snapshot here is held by an explicit BEGIN rather than by PEP 249
        # mode -- which would pin one on any bare SELECT (issue #155's own
        # measurement, and part of why that pin exists).
        reader.autocommit = sqlite3.LEGACY_TRANSACTION_CONTROL
        writer.autocommit = sqlite3.LEGACY_TRANSACTION_CONTROL

    assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal", (
        "the fixture's UserDatabase should have left the file in WAL mode; "
        "without a WAL there is nothing for this test to lose"
    )

    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM question_entries").fetchone()

    session_id = writer.execute(
        "SELECT id FROM review_sessions ORDER BY id LIMIT 1"
    ).fetchone()[0]
    writer.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, ?, ?)",
        (session_id, 99, SENTINEL, "correct_99"),
    )
    writer.commit()

    assert Path(str(db_path) + "-wal").exists(), "the sentinel should be in a WAL"
    return reader, writer


def _sentinel_rows(db_path: Path) -> int:
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM question_entries WHERE user_answer = ?",
            (SENTINEL,),
        ).fetchone()[0]
    finally:
        conn.close()


def _sabotage_whatever_writes_the_backup(monkeypatch, sabotage):
    """Make the safety-backup write misbehave, on either implementation.

    Two patches, because the thing that writes that file is exactly what this
    change replaces: `shutil.copy2` before the fix, `_snapshot_database`
    after. Patching only one would make these tests "pass" before the fix by
    never firing -- a DID NOT RAISE that proves nothing -- so both are
    installed and the inactive one is simply never reached.

    `sabotage(real_writer, source, dest)` is called in place of the write.
    """
    real_copy2 = profile_archive.shutil.copy2
    real_snapshot = profile_archive._snapshot_database

    def copy2(src, dst, *args, **kwargs):
        if Path(dst).name.startswith("pre_replace_"):
            return sabotage(real_copy2, src, dst)
        return real_copy2(src, dst, *args, **kwargs)

    def snapshot(source_db_path, dest_path):
        return sabotage(real_snapshot, source_db_path, dest_path)

    monkeypatch.setattr(profile_archive.shutil, "copy2", copy2)
    monkeypatch.setattr(profile_archive, "_snapshot_database", snapshot)


def _release_the_extra_connections_after_the_backup(monkeypatch, *conns):
    """Close `conns` at the first moment they no longer matter.

    The busy condition has to hold *while the backup is taken* and nowhere
    else, so the two spare connections are dropped on the install copy --
    `shutil.copy2(db_temp, <target>.importing)`, the first statement after the
    backup block. A second handle held past that point would make
    `os.replace` fail on Windows, which is a different bug than this file is
    about (CLAUDE.md, #151).
    """
    real_copy2 = profile_archive.shutil.copy2

    def copy2(src, dst, *args, **kwargs):
        if str(dst).endswith(".importing"):
            for conn in conns:
                conn.close()
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(profile_archive.shutil, "copy2", copy2)


# ==================== the premise ====================

def test_a_pinned_reader_blocks_a_truncate_checkpoint(dest_master):
    """The negative control: without this, the test below proves nothing.

    Two measurements, not one. The checkpoint must report `busy` *and* the
    single-file copy must actually lose the row -- a blocked checkpoint that
    still left the data in the `.db` would make this a cosmetic issue.
    """
    bob, _carol = _bob(dest_master)
    db_path = dest_master.users_dir / bob.database_filename
    reader, writer = _pin_a_snapshot_then_commit_a_sentinel(db_path)
    try:
        probe = sqlite3.connect(str(db_path))
        try:
            busy, _log_frames, checkpointed = probe.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
        finally:
            probe.close()

        assert busy == 1, (
            "a pinned read snapshot no longer blocks a TRUNCATE checkpoint on "
            "this SQLite build, so this file's whole construction has stopped "
            "reproducing #155 -- the fix may still be right, but these tests "
            "are no longer evidence for it"
        )
        assert checkpointed == 0, (
            "the blocked checkpoint copied frames anyway; if it can copy the "
            "sentinel's frames the sentinel is no longer a sentinel"
        )

        # The other half: the loss is real, not merely possible.
        raw = dest_master.archive_dir / "raw_copy_of_the_db_alone.db"
        profile_archive.shutil.copyfile(str(db_path), str(raw))
        assert _sentinel_rows(raw) == 0, (
            "a copy of the .db without its -wal should be missing the "
            "committed-but-unCheckpointed row; if it is not, the busy "
            "checkpoint is harmless and #155 is not a bug"
        )
    finally:
        reader.close()
        writer.close()


# ==================== the regression ====================

def test_the_safety_backup_keeps_a_commit_still_in_the_wal(
    alice_archive, dest_master, monkeypatch
):
    """The backup `replace_profile` keeps must hold everything committed.

    Fails before the fix: the discarded `busy=1` meant the checkpoint copied
    nothing and the following `copy2` wrote a `.db` without the WAL tail, so
    the student's own last entry was absent from the only copy of it left.
    """
    bob, carol = _bob(dest_master)
    db_path = dest_master.users_dir / bob.database_filename
    reader, writer = _pin_a_snapshot_then_commit_a_sentinel(db_path)
    _release_the_extra_connections_after_the_backup(monkeypatch, reader, writer)

    try:
        result = replace_profile(
            dest_master,
            alice_archive,
            target_user_id=bob.id,
            active_user_id=carol.id,
            confirm_replace=True,
        )
    finally:
        for conn in (reader, writer):
            try:
                conn.close()
            except sqlite3.Error:
                pass

    backup = Path(result["backup_db_path"])
    assert backup.exists()
    assert _sentinel_rows(backup) == 1, (
        "the pre-replace backup is missing a transaction that was committed "
        "before the replace started -- the WAL tail was dropped on the floor "
        "(#155). This is the file the student restores from."
    )
    # And the replace itself still worked, so the assertion above is not
    # passing because the whole operation blew up early.
    assert result["entries"] == 3
    assert _entry_count(dest_master.users_dir / bob.database_filename) == 3


def test_the_backup_is_one_self_contained_file(
    alice_archive, dest_master, monkeypatch
):
    """No `-wal`/`-shm` beside the backup, because the rollback is one move.

    `replace_profile`'s rollback restores with a single
    `os.replace(backup_db, target_db)`. A backup that needed its sidecars to
    be complete would make that restore silently partial -- a `.db` paired
    with a WAL from another generation is a worse failure than the one #155
    describes, so the backup has to stand alone rather than travel as a
    triplet.
    """
    bob, carol = _bob(dest_master)
    db_path = dest_master.users_dir / bob.database_filename
    reader, writer = _pin_a_snapshot_then_commit_a_sentinel(db_path)
    _release_the_extra_connections_after_the_backup(monkeypatch, reader, writer)

    try:
        result = replace_profile(
            dest_master,
            alice_archive,
            target_user_id=bob.id,
            active_user_id=carol.id,
            confirm_replace=True,
        )
    finally:
        for conn in (reader, writer):
            try:
                conn.close()
            except sqlite3.Error:
                pass

    backup = Path(result["backup_db_path"])
    strays = sorted(
        p.name for p in backup.parent.iterdir()
        if p.name.startswith(backup.name) and p.name != backup.name
    )
    assert strays == [], (
        f"the backup left sidecar files behind: {strays}. The rollback moves "
        "one file, so anything the backup needs beside it is lost on restore."
    )
    assert _sentinel_rows(backup) == 1, "and it is complete without them"


# ==================== refusing beats a silent partial ====================

def test_a_backup_that_cannot_be_taken_refuses_instead_of_proceeding(
    alice_archive, dest_master, monkeypatch
):
    """And it must not destroy the database it was taken to protect.

    The rollback reads `backup_db is not None` as authority to delete the live
    database before restoring from it:

        if installed_db or backup_db is not None:
            _remove_db_artifacts(target_db)
            if backup_db is not None and backup_db.exists():
                os.replace(backup_db, target_db)

    Reserving the backup's *name* before the copy succeeded therefore turned a
    failed backup into a deleted profile with nothing to restore (#297, filed
    separately and fixed here). The name is now assigned only once the file
    exists and has been read back.
    """
    bob, carol = _bob(dest_master)
    db_path = dest_master.users_dir / bob.database_filename
    entries_before = _entry_count(db_path)

    def explode(_real_writer, _source, dest):
        # Write a plausible-looking partial file first: a truncated
        # `pre_replace_*.db` left in archive_dir reads as a real safety
        # backup to anyone browsing the folder.
        Path(dest).write_bytes(b"SQLite format 3\x00truncated")
        raise OSError("No space left on device")

    _sabotage_whatever_writes_the_backup(monkeypatch, explode)

    with pytest.raises(ProfileImportError) as excinfo:
        replace_profile(
            dest_master,
            alice_archive,
            target_user_id=bob.id,
            active_user_id=carol.id,
            confirm_replace=True,
        )
    assert "No space left on device" in str(excinfo.value)

    assert db_path.exists(), (
        "the live profile database was deleted by the rollback after its "
        "safety backup failed, and there was no backup to put back"
    )
    try:
        surviving = _entry_count(db_path)
    except sqlite3.DatabaseError as exc:
        pytest.fail(
            f"the live profile database is not a database any more ({exc}). "
            "The rollback moved the half-written safety backup on top of it, "
            "because a reserved name counted as a backup."
        )
    assert surviving == entries_before, "and it is untouched"
    assert sorted(dest_master.archive_dir.glob("pre_replace_*.db")) == [], (
        "a half-written file was left where a safety backup belongs"
    )


def test_a_short_backup_refuses_rather_than_reading_as_success(
    alice_archive, dest_master, monkeypatch
):
    """The copy is read back, because `backup()` succeeding is not proof.

    `Connection.backup()` cannot drop the WAL tail, which is what made it the
    fix. It can still produce a file that is short for some other reason, and
    the whole lesson of #155 is that this particular file must never be
    quietly incomplete -- it is read only when something has already failed.
    """
    bob, carol = _bob(dest_master)
    db_path = dest_master.users_dir / bob.database_filename

    def write_then_lose_a_row(real_writer, source, dest):
        real_writer(source, dest)
        conn = sqlite3.connect(str(dest))
        try:
            conn.execute("DELETE FROM question_entries")
            conn.commit()
        finally:
            conn.close()

    _sabotage_whatever_writes_the_backup(monkeypatch, write_then_lose_a_row)

    with pytest.raises(ProfileImportError) as excinfo:
        replace_profile(
            dest_master,
            alice_archive,
            target_user_id=bob.id,
            active_user_id=carol.id,
            confirm_replace=True,
        )
    message = str(excinfo.value)
    assert "safety backup" in message.lower()
    assert db_path.exists() and _entry_count(db_path) == 1


def test_the_discarded_checkpoint_helper_is_gone():
    """A source check: nothing may reintroduce the pattern quietly.

    `_checkpoint_wal` had exactly one caller -- the backup this file is about
    -- and `Connection.backup()` needs no checkpoint, so leaving a hardened
    version behind would be code that reads as live and is not (#71's lesson).
    Its absence is the guard.
    """
    assert not hasattr(profile_archive, "_checkpoint_wal"), (
        "_checkpoint_wal is back. A checkpoint before a Connection.backup() "
        "buys nothing, and the only thing it ever protected was a raw file "
        "copy of a live database -- which is #155."
    )

    # Docstrings are excluded, the way `test_root_predicates_agree.py` does
    # it: the prose that explains the defect names the pragma, so a raw text
    # scan flags the very comment that fixed it.
    tree = ast.parse(Path(profile_archive.__file__).read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))

    offenders = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and "wal_checkpoint" in node.value
    ]
    assert offenders == [], (
        f"a wal_checkpoint pragma is back in profile_archive.py at line(s) "
        f"{offenders}. Read its return value if you need one: busy=1 means "
        "it did nothing, and that is the whole of #155."
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v", "--no-cov"]))
