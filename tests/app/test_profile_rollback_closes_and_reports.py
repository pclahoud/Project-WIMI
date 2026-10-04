"""The import rollback's two halves of #292, at the surface that owns them.

``install_profile_as_new`` documents its rollback as leaving **zero
residue**. On Windows it left the copied user database behind, and said
nothing. Two independent things made that possible, and only one of them is
Windows-shaped:

1. The verify-open's ``UserDatabase`` raised from inside its constructor,
   so the connection stayed open *and* ``verify_db`` was never assigned —
   the rollback's ``if verify_db is not None: verify_db.close()`` is dead
   exactly when there is something to close. Fixed in ``UserDatabase``
   itself (``tests/database/test_user_db_constructor_failure.py`` owns the
   mechanism); the first test here asserts the consequence this module
   depends on: by the time the unlink runs, nothing holds the file.

2. ``_remove_db_artifacts`` swallowed ``OSError`` without a word. **That
   half is platform-independent**, and it is why this went unnoticed
   through every Windows run to date: on POSIX the unlink happens to
   succeed, so the silence has never been tested anywhere either.

The orphan file itself is not observable here. ``test_profile_import_logging``'s
rollback test passes on Linux and on macOS (measured, #292 comment) and
fails only on Windows, because POSIX unlinks an open file freely. So these
tests assert the two *causes* rather than the symptom, which is also what
makes them meaningful on a platform that cannot show the symptom.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

import app.profile_archive as profile_archive
from app.profile_archive import (
    ProfileImportError,
    _remove_db_artifacts,
    build_profile_archive,
    install_profile_as_new,
)
from database.master_db import MasterDatabase
from database.migration_runner import Migration
from database.user_db import UserDatabase


# ==================== helpers ====================

def _failing_registry(real_registry):
    """The real registry plus one migration that always raises (v26+ is free)."""
    def explode(conn):
        raise sqlite3.OperationalError("deliberate failure from the test")

    return list(real_registry) + [
        Migration(version=26, name="deliberate_failure", upgrade_fn=explode)
    ]


def _seed(master: MasterDatabase, user) -> None:
    db = UserDatabase(
        db_path=master.ensure_user_database(user.id),
        user_id=user.id,
        username=user.username,
    )
    try:
        with db.transaction():
            db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, "Sample Exam"),
            )
    finally:
        db.close()


# ==================== fixtures ====================

@pytest.fixture
def source_master(tmp_path):
    db = MasterDatabase(data_dir=tmp_path / "source", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def dest_master(tmp_path):
    db = MasterDatabase(data_dir=tmp_path / "dest", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def archive(source_master, tmp_path):
    user = source_master.create_user(username="dana", display_name="Dana")
    _seed(source_master, user)
    dest = tmp_path / "dana.wimi"
    build_profile_archive(source_master, user.id, dest, include_media=False)
    return dest


@pytest.fixture
def failing_migrations(monkeypatch):
    import database.migrations.user as user_migrations

    monkeypatch.setattr(
        user_migrations,
        "MIGRATIONS",
        _failing_registry(user_migrations.MIGRATIONS),
    )


# ==================== 1. nothing holds the file when the unlink runs =========

def test_a_failed_import_has_released_the_file_before_it_unlinks(
    dest_master, archive, failing_migrations, monkeypatch
):
    """The Windows precondition, measured on a platform that cannot fail.

    Linux unlinks an open file, so the leftover-file assertion in
    ``test_profile_import_logging`` can never go red here. What *can* be
    checked is whether the handle is still open at the moment the rollback
    reaches for the unlink — which is the whole of why Windows refused.
    """
    opened = []
    real_connect = sqlite3.connect

    def spy(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        if args and str(args[0]).endswith(".db"):
            opened.append((str(args[0]), conn))
        return conn

    monkeypatch.setattr(sqlite3, "connect", spy)

    still_open_at_unlink = []
    real_remove = profile_archive._remove_db_artifacts

    def recording_remove(db_path: Path) -> None:
        for path, conn in opened:
            if path != str(db_path):
                continue
            try:
                conn.execute("SELECT 1").fetchone()
                still_open_at_unlink.append(path)
            except sqlite3.ProgrammingError:
                pass
        real_remove(db_path)

    monkeypatch.setattr(
        profile_archive, "_remove_db_artifacts", recording_remove
    )

    with pytest.raises(ProfileImportError):
        install_profile_as_new(dest_master, archive)

    assert still_open_at_unlink == [], (
        "the rollback tried to unlink a database this process still had "
        "open; on Windows that raises PermissionError and leaves an orphan "
        "user_NNN_<name>.db behind (#292)"
    )


# ==================== 2. a removal that fails says so ======================

def test_an_artifact_that_cannot_be_removed_is_logged(tmp_path, caplog):
    """The platform-independent half.

    ``PermissionError`` is what Windows raises for a file something still
    holds open, and it is an ``OSError``, so the old bare ``except OSError:
    pass`` caught it. Simulated rather than provoked, because provoking it
    needs an OS that refuses — the point of the fix is that *any* platform
    now reports it.
    """
    victim = tmp_path / "user_001_dana.db"
    victim.write_bytes(b"not really a database")

    def refuse(self, *args, **kwargs):
        raise PermissionError(
            13, "The process cannot access the file because it is being "
                "used by another process"
        )

    with caplog.at_level(logging.WARNING, logger="app.profile_archive"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "unlink", refuse)
            _remove_db_artifacts(victim)  # best-effort: must not raise

    assert victim.exists(), "the simulation is wrong if the file went away"

    messages = [r.getMessage() for r in caplog.records]
    assert any(victim.name in m for m in messages), (
        f"the failed removal named no path; records were {messages}"
    )
    assert any("used by another process" in m for m in messages), (
        f"the failed removal did not carry the OS error; records were "
        f"{messages}"
    )


def test_a_removal_that_succeeds_says_nothing(tmp_path, caplog):
    """Negative control.

    Without it, a mutant that logged on every call — or logged outside the
    ``except`` — would pass the test above while saying nothing about
    whether anything actually failed. Three of the four candidate files
    here do not exist at all, which is the ordinary case and must also be
    silent.
    """
    victim = tmp_path / "user_001_dana.db"
    victim.write_bytes(b"not really a database")

    with caplog.at_level(logging.WARNING, logger="app.profile_archive"):
        _remove_db_artifacts(victim)

    assert not victim.exists()
    assert [r.getMessage() for r in caplog.records] == []
