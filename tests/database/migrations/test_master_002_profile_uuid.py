"""Tests for master-DB migration v2 (``users.profile_uuid``, issue #129).

Master was at m001 (baseline only) before this. Three decisions are
pinned here because each is easy to "correct" in the wrong direction:

- The column is **not UNIQUE**. Two installs of the same archive are a
  supported outcome — ``install_profile_as_new()`` forks on a name
  collision by design, and #22 comment #1454 decided "keep both" is one
  of the two options a student is offered at first connect. A unique
  index would turn that decision into an ``IntegrityError``.
- It is **not backfilled**. Minting ids here would put the authority in
  the wrong database: master would claim an id the user database has
  never heard of.
- The index is **partial**, so the common pre-mirror ``NULL`` costs
  nothing.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner, build_migration
from database.migrations._helpers import get_column_names
from database.migrations.master import MIGRATIONS
from database.migrations.master import m001_baseline as master_m001


def _runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="master")


def _runner_through_v1(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(
        conn, registry=[build_migration(master_m001)], scope="master"
    )


def _a_user(conn: sqlite3.Connection, username: str, **extra) -> int:
    cols = "username, display_name, user_type, database_filename"
    vals = [username, username.title(), '["student"]', f"user_{username}.db"]
    for key, value in extra.items():
        cols += f", {key}"
        vals.append(value)
    placeholders = ", ".join("?" * len(vals))
    return conn.execute(
        f"INSERT INTO users ({cols}) VALUES ({placeholders})", tuple(vals)
    ).lastrowid


def test_registry_has_v2():
    versions = [m.version for m in MIGRATIONS]
    assert versions == [1, 2]
    assert {m.version: m.name for m in MIGRATIONS}[2] == "profile_uuid"


def test_pre_v2_master_has_no_profile_uuid_column(fresh_conn):
    _runner_through_v1(fresh_conn).apply_pending()
    assert "profile_uuid" not in get_column_names(fresh_conn, "users")


def test_apply_pending_adds_the_column_and_the_partial_index(fresh_conn):
    _runner_through_v1(fresh_conn).apply_pending()
    _runner(fresh_conn).apply_pending()

    assert "profile_uuid" in get_column_names(fresh_conn, "users")
    index_sql = fresh_conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'idx_users_profile_uuid'"
    ).fetchone()[0]
    assert "WHERE profile_uuid IS NOT NULL" in index_sql
    assert "UNIQUE" not in index_sql.upper()
    assert 2 in {
        r[0] for r in fresh_conn.execute("SELECT version FROM schema_migrations")
    }


def test_existing_rows_are_not_backfilled(fresh_conn):
    """The authority is the user database; master must not invent one."""
    _runner_through_v1(fresh_conn).apply_pending()
    user_id = _a_user(fresh_conn, "alice")
    _runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT profile_uuid FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    assert row[0] is None


def test_two_profiles_may_share_an_identifier(fresh_conn):
    """Installing the same archive twice is a fork, not a corruption.

    The duplicate is detected and reported by the import path; choosing
    between the copies is #124's job. A UNIQUE index here would make the
    choice impossible to reach.
    """
    _runner(fresh_conn).apply_pending()
    shared = "11111111-2222-3333-4444-555555555555"
    first = _a_user(fresh_conn, "alice", profile_uuid=shared)
    second = _a_user(fresh_conn, "alice_2", profile_uuid=shared)

    rows = fresh_conn.execute(
        "SELECT id FROM users WHERE profile_uuid = ? ORDER BY id", (shared,)
    ).fetchall()
    assert [r[0] for r in rows] == [first, second]


def test_many_nulls_coexist(fresh_conn):
    """Every profile is NULL until it has been opened once."""
    _runner(fresh_conn).apply_pending()
    _a_user(fresh_conn, "alice")
    _a_user(fresh_conn, "bob")
    count = fresh_conn.execute(
        "SELECT COUNT(*) FROM users WHERE profile_uuid IS NULL"
    ).fetchone()[0]
    assert count == 2


def test_migration_is_idempotent(fresh_conn):
    _runner(fresh_conn).apply_pending()
    from database.migrations.master import m002_profile_uuid
    m002_profile_uuid.upgrade(fresh_conn)
    assert "profile_uuid" in get_column_names(fresh_conn, "users")
