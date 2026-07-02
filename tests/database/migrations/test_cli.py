"""Tests for the ``python -m database.migrations`` CLI.

These tests call ``database.migrations.__main__.main`` in-process with
explicit ``argv`` and use pytest's ``capsys`` to capture stdout/stderr.
That choice is deliberate:

- It's faster than ``subprocess.run`` (no Python interpreter spin-up per
  test, important when this directory is run alongside the rest of the
  migration suite).
- The CLI surface under test is ``main(argv)`` plus argparse — calling
  it directly exercises exactly the code path that ``__main__`` invokes.
- Subprocess tests would also require setting ``PYTHONPATH=src`` because
  the repo doesn't ship a ``pyproject.toml`` packaging step; in-process
  reuses the test runner's already-configured ``sys.path`` (set up by
  the project-root ``conftest.py``).

Where checking the actual exit-code return value matters, we read the
return value of ``main()`` directly — equivalent to the ``SystemExit``
code the ``if __name__ == "__main__"`` block raises.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database.migration_runner import MigrationRunner
from database.migrations.__main__ import main as cli_main
from database.migrations.user import MIGRATIONS as USER_MIGRATIONS


# ---------------------------------------------------------------------- fixtures


@pytest.fixture
def fresh_user_db_path(tmp_path) -> Path:
    """A brand-new SQLite file with no schema_migrations table yet."""
    db_path = tmp_path / "user_999_fresh.db"
    # Just creating the file (an empty SQLite DB).
    conn = sqlite3.connect(str(db_path))
    conn.close()
    return db_path


@pytest.fixture
def migrated_user_db_path(tmp_path) -> Path:
    """A user DB with every registered migration applied."""
    db_path = tmp_path / "user_999_migrated.db"
    conn = sqlite3.connect(str(db_path))
    try:
        runner = MigrationRunner(conn, registry=USER_MIGRATIONS, scope="user")
        runner.apply_pending()
    finally:
        conn.close()
    return db_path


@pytest.fixture
def master_db_path_with_users_table(tmp_path) -> Path:
    """A master-shaped DB that has a ``users`` table (auto-detect signal)."""
    db_path = tmp_path / "master.db"
    conn = sqlite3.connect(str(db_path))
    try:
        # The auto-detect heuristic only checks for the ``users`` table;
        # we don't need the full master schema for this test.
        conn.execute(
            "CREATE TABLE users ("
            " user_id INTEGER PRIMARY KEY, "
            " username TEXT NOT NULL"
            ")"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


# ---------------------------------------------------------------------- status


def test_status_on_fresh_db_shows_all_pending(fresh_user_db_path, capsys):
    exit_code = cli_main(["status", str(fresh_user_db_path), "--scope", "user"])
    out = capsys.readouterr().out

    assert exit_code == 0
    # Every registry migration appears as pending.
    for migration in USER_MIGRATIONS:
        line_marker = f"v{migration.version:03d} {migration.name}"
        assert line_marker in out, f"missing line for {line_marker}: {out!r}"
        # And each of those lines must be tagged "pending".
        for line in out.splitlines():
            if line_marker in line:
                assert "pending" in line, f"{line_marker} not pending: {line!r}"
                break
    # No "ok" or "MISMATCH" should appear on a fresh DB.
    assert " ok" not in out
    assert "MISMATCH" not in out


def test_status_on_migrated_db_shows_all_ok(migrated_user_db_path, capsys):
    exit_code = cli_main(["status", str(migrated_user_db_path), "--scope", "user"])
    out = capsys.readouterr().out

    assert exit_code == 0
    for migration in USER_MIGRATIONS:
        marker = f"v{migration.version:03d} {migration.name}"
        for line in out.splitlines():
            if marker in line:
                assert "ok" in line, f"expected ok, got: {line!r}"
                assert "pending" not in line
                break
        else:
            pytest.fail(f"no status line found for {marker}: {out!r}")

    assert "MISMATCH" not in out
    assert "MISSING FROM REGISTRY" not in out


def test_status_detects_checksum_mismatch(migrated_user_db_path, capsys):
    # Tamper: replace the recorded checksum for v1 with garbage.
    conn = sqlite3.connect(str(migrated_user_db_path))
    try:
        conn.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = 1",
            ("deadbeef" * 8,),  # 64 hex chars, definitely not the real one
        )
        conn.commit()
    finally:
        conn.close()

    exit_code = cli_main(
        ["status", str(migrated_user_db_path), "--scope", "user"]
    )
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "CHECKSUM MISMATCH" in out
    # The mismatch row reports the recorded (tampered) and current checksums.
    assert "deadbeef" in out
    # Other migrations should still be ok.
    if len(USER_MIGRATIONS) >= 2:
        v2 = USER_MIGRATIONS[1]
        marker = f"v{v2.version:03d} {v2.name}"
        for line in out.splitlines():
            if marker in line:
                assert "ok" in line
                break


def test_status_auto_detects_master_scope(master_db_path_with_users_table, capsys):
    # No --scope argument; the CLI should detect master from the users table.
    exit_code = cli_main(["status", str(master_db_path_with_users_table)])
    out = capsys.readouterr().out

    assert exit_code == 0
    # Header line should explicitly call out the auto-detected scope.
    assert "scope: master" in out
    assert "auto-detected" in out


def test_status_missing_from_registry_flagged(fresh_user_db_path, capsys):
    """A row in schema_migrations that doesn't match any registered version
    should surface as MISSING FROM REGISTRY and bump the exit code to 1.
    """
    # Set up a baseline-applied DB then inject a phantom row for v999.
    conn = sqlite3.connect(str(fresh_user_db_path))
    try:
        runner = MigrationRunner(conn, registry=USER_MIGRATIONS, scope="user")
        runner.apply_pending()
        conn.execute(
            "INSERT INTO schema_migrations (version, name, checksum, duration_ms) "
            "VALUES (?, ?, ?, ?)",
            (999, "deleted_migration", "0" * 64, 0),
        )
        conn.commit()
    finally:
        conn.close()

    exit_code = cli_main(["status", str(fresh_user_db_path), "--scope", "user"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "MISSING FROM REGISTRY" in out
    assert "v999 deleted_migration" in out


# ---------------------------------------------------------------------- apply


def test_apply_runs_pending_migrations(fresh_user_db_path, capsys):
    exit_code = cli_main(["apply", str(fresh_user_db_path), "--scope", "user"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert f"Applied {len(USER_MIGRATIONS)} migration(s):" in out
    for migration in USER_MIGRATIONS:
        assert f"v{migration.version:03d} {migration.name}" in out

    # Verify the applied state directly in the DB.
    conn = sqlite3.connect(str(fresh_user_db_path))
    try:
        rows = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == [m.version for m in USER_MIGRATIONS]


def test_apply_on_already_migrated_db_is_noop(migrated_user_db_path, capsys):
    exit_code = cli_main(
        ["apply", str(migrated_user_db_path), "--scope", "user"]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "No pending migrations" in out


def test_status_on_missing_db_path_errors(tmp_path, capsys):
    nonexistent = tmp_path / "does_not_exist.db"
    exit_code = cli_main(["status", str(nonexistent), "--scope", "user"])
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "does not exist" in err
