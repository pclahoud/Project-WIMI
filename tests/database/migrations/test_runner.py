"""Tests for the generic ``MigrationRunner``.

These tests construct ``Migration`` objects from inline named functions
(NOT lambdas — ``inspect.getsource`` doesn't behave cleanly on lambdas
defined inside test bodies) so the runner-only invariants can be
exercised without pulling in the real user/master migration registries.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import (
    Migration,
    MigrationChecksumMismatchError,
    MigrationFailedError,
    MigrationRunner,
)


# ---------------------------------------------------------------------- helpers

def _trivial_upgrade(conn: sqlite3.Connection) -> None:
    """A no-op migration body suitable for lightweight tests."""
    conn.execute("CREATE TABLE IF NOT EXISTS trivial_marker (id INTEGER)")


def _make(version: int, name: str, fn) -> Migration:
    return Migration(version=version, name=name, upgrade_fn=fn)


class _RealShapeLogger:
    """Mimics ``ErrorLogger``'s call shape to catch category-handling regressions.

    The real logger expects ``category`` to be an ``ErrorCategory``
    enum — it calls ``category.value`` inside ``_hash_error``. A
    runner that passes a plain string crashes deep inside the logger
    with ``AttributeError`` rather than a clean failure at the
    boundary. This shim asserts the same contract so tests catch the
    regression at the runner level.
    """

    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []

    def _record(self, level, message, category=None):
        if category is not None:
            # Will raise AttributeError if category is a plain string.
            _ = category.value
        self.calls.append((level, message, category))

    def debug(self, message, category=None):
        self._record("debug", message, category)

    def info(self, message, category=None):
        self._record("info", message, category)

    def warning(self, message, category=None):
        self._record("warning", message, category)

    def error(self, message, category=None, error=None):
        self._record("error", message, category)


# ---------------------------------------------------------------------- tests

def test_apply_pending_creates_schema_migrations_table(fresh_conn):
    """Instantiating the runner alone creates the ledger table (idempotent)."""
    MigrationRunner(fresh_conn, registry=[], scope="user")

    tables = {
        row[0]
        for row in fresh_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "schema_migrations" in tables

    # Re-instantiating against the same conn must not error (CREATE IF NOT EXISTS).
    MigrationRunner(fresh_conn, registry=[], scope="user")


def test_apply_pending_applies_in_version_order(fresh_conn):
    """Registry given out of order is sorted by version then applied 1, 2, 3."""

    def up_v1(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE order_marker_v1 (id INTEGER)")

    def up_v2(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE order_marker_v2 (id INTEGER)")

    def up_v3(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE order_marker_v3 (id INTEGER)")

    # Intentionally out of order:
    registry = [
        _make(3, "v3", up_v3),
        _make(1, "v1", up_v1),
        _make(2, "v2", up_v2),
    ]
    runner = MigrationRunner(fresh_conn, registry=registry, scope="user")
    applied = runner.apply_pending()

    assert applied == [1, 2, 3]
    records = runner.applied_records()
    assert sorted(records.keys()) == [1, 2, 3]
    assert records[1]["name"] == "v1"
    assert records[2]["name"] == "v2"
    assert records[3]["name"] == "v3"


def test_apply_pending_records_checksum_and_duration(fresh_conn):
    """Applied row carries the migration's checksum and a non-null duration_ms."""
    migration = _make(1, "trivial", _trivial_upgrade)
    runner = MigrationRunner(fresh_conn, registry=[migration], scope="user")
    runner.apply_pending()

    row = fresh_conn.execute(
        "SELECT version, name, checksum, duration_ms FROM schema_migrations "
        "WHERE version = 1"
    ).fetchone()
    assert row is not None
    assert row[0] == 1
    assert row[1] == "trivial"
    assert row[2] == migration.checksum
    assert row[3] is not None  # duration_ms recorded
    assert isinstance(row[3], int)
    assert row[3] >= 0


def test_apply_pending_is_idempotent(fresh_conn):
    """Second apply_pending() returns [] and doesn't double-record."""
    migration = _make(1, "trivial", _trivial_upgrade)
    runner = MigrationRunner(fresh_conn, registry=[migration], scope="user")

    first = runner.apply_pending()
    assert first == [1]

    second = runner.apply_pending()
    assert second == []

    count = fresh_conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
    ).fetchone()[0]
    assert count == 1


def test_failed_migration_rolls_back_and_blocks_subsequent(fresh_conn):
    """Failure in v2 rolls back v2's DML writes, records v1, and never tries v3."""

    # Pre-create a table that v2 will write into; that write must be
    # rolled back when v2 raises. Using a DML INSERT (rather than a DDL
    # CREATE TABLE) makes the rollback observable — Python's sqlite3
    # module manages an implicit transaction around DML but auto-commits
    # DDL.
    fresh_conn.execute("CREATE TABLE rollback_target (id INTEGER PRIMARY KEY, marker TEXT)")
    fresh_conn.commit()

    def up_v1(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO rollback_target (marker) VALUES ('v1_committed')")

    def up_v2_bad(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO rollback_target (marker) VALUES ('v2_should_be_rolled_back')")
        raise RuntimeError("boom")

    def up_v3(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO rollback_target (marker) VALUES ('v3_never_runs')")

    registry = [
        _make(1, "good_v1", up_v1),
        _make(2, "bad_v2", up_v2_bad),
        _make(3, "good_v3", up_v3),
    ]
    runner = MigrationRunner(fresh_conn, registry=registry, scope="user")

    with pytest.raises(MigrationFailedError) as excinfo:
        runner.apply_pending()

    assert excinfo.value.version == 2
    assert excinfo.value.name == "bad_v2"

    markers = {
        row[0]
        for row in fresh_conn.execute(
            "SELECT marker FROM rollback_target"
        ).fetchall()
    }
    # v1 succeeded and was committed:
    assert "v1_committed" in markers
    # v2's DML write was rolled back:
    assert "v2_should_be_rolled_back" not in markers
    # v3 was never attempted:
    assert "v3_never_runs" not in markers

    applied = runner.applied_versions()
    assert applied == {1}


def test_checksum_mismatch_hard_fails_at_verify(fresh_conn):
    """A registry whose v1 source differs from the recorded checksum raises."""
    # Apply original v1.
    def original_v1(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE checksum_marker (id INTEGER)")

    runner = MigrationRunner(
        fresh_conn,
        registry=[_make(1, "v1", original_v1)],
        scope="user",
    )
    runner.apply_pending()

    # Now build a NEW migration with the same version but a different
    # function source — that's what the runner is supposed to detect.
    def edited_v1(conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS checksum_marker (id INTEGER, extra TEXT)"
        )

    edited_runner = MigrationRunner(
        fresh_conn,
        registry=[_make(1, "v1", edited_v1)],
        scope="user",
    )

    with pytest.raises(MigrationChecksumMismatchError) as excinfo:
        edited_runner.apply_pending()

    assert excinfo.value.version == 1
    assert excinfo.value.name == "v1"
    assert excinfo.value.recorded_checksum != excinfo.value.current_checksum


def test_apply_specific_works_and_blocks_double_apply(fresh_conn):
    """apply_specific applies an unapplied version once and rejects re-apply / unknowns."""

    def up_a(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE specific_a (id INTEGER)")

    def up_b(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE specific_b (id INTEGER)")

    runner = MigrationRunner(
        fresh_conn,
        registry=[_make(1, "a", up_a), _make(2, "b", up_b)],
        scope="user",
    )

    runner.apply_specific(1)
    assert runner.applied_versions() == {1}

    # Double-apply: must raise ValueError.
    with pytest.raises(ValueError):
        runner.apply_specific(1)

    # Unregistered version: must raise KeyError.
    with pytest.raises(KeyError):
        runner.apply_specific(99)


def test_duplicate_versions_in_registry_rejected(fresh_conn):
    """Constructor raises ValueError when two migrations share a version."""
    def up_x(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE dup_x (id INTEGER)")

    def up_y(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE dup_y (id INTEGER)")

    with pytest.raises(ValueError):
        MigrationRunner(
            fresh_conn,
            registry=[_make(1, "x", up_x), _make(1, "y", up_y)],
            scope="user",
        )


def test_log_passes_errorcategory_enum_not_string(fresh_conn):
    """Regression: the runner's _log must pass an ErrorCategory enum.

    The real ``ErrorLogger`` calls ``category.value`` inside
    ``_hash_error``. An earlier version passed ``category="DATABASE"``
    as a string, which crashed deep inside the logger with
    ``AttributeError`` rather than failing cleanly at the boundary.
    The previous try/except for ``TypeError`` didn't catch it because
    the kwarg is accepted at the call site. This test uses a logger
    shim that asserts the same contract — if the runner regresses to
    passing a string, the shim's ``_record`` raises and the test
    fails.
    """
    logger = _RealShapeLogger()
    runner = MigrationRunner(
        fresh_conn,
        registry=[_make(1, "trivial", _trivial_upgrade)],
        scope="user",
        error_logger=logger,
    )
    runner.apply_pending()
    # We expect at least the two info log lines from _apply_one
    # ("Applying ...", "Applied ...").
    assert any(
        call[0] == "info" and "Applying" in call[1] for call in logger.calls
    ), f"Expected an 'Applying ...' info log; got {logger.calls!r}"
    assert any(
        call[0] == "info" and "Applied" in call[1] for call in logger.calls
    ), f"Expected an 'Applied ...' info log; got {logger.calls!r}"
