"""Tests for master-DB migration v1 (baseline)."""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner, build_migration
from database.migrations._helpers import (
    get_column_names,
    get_table_names,
    read_schema_file,
)
from database.migrations.master import m001_baseline as master_m001


def _make_master_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(
        conn,
        registry=[build_migration(master_m001)],
        scope="master",
    )


def test_master_baseline_creates_users_table(fresh_conn):
    """Fresh DB → master baseline → users table + key columns present."""
    _make_master_runner(fresh_conn).apply_pending()

    tables = get_table_names(fresh_conn)
    assert "users" in tables
    assert "app_settings" in tables

    user_cols = get_column_names(fresh_conn, "users")
    for required in (
        "id",
        "username",
        "display_name",
        "email",
        "user_type",
        "database_filename",
        "account_status",
        "is_primary_admin",
    ):
        assert required in user_cols, f"users.{required} missing"


def test_master_baseline_is_idempotent(fresh_conn):
    """Re-running baseline does nothing harmful."""
    runner = _make_master_runner(fresh_conn)
    runner.apply_pending()

    tables_first = get_table_names(fresh_conn)

    # Bypass the ledger and re-invoke directly.
    master_m001.upgrade(fresh_conn)

    tables_second = get_table_names(fresh_conn)
    assert tables_first == tables_second


def test_master_baseline_adopts_pre_runner_db(fresh_conn):
    """If users table is already present, baseline no-ops without touching it."""
    fresh_conn.executescript(read_schema_file("master_db_schema_v1.sql"))

    fresh_conn.execute(
        "INSERT INTO users (username, display_name, user_type, database_filename) "
        "VALUES (?, ?, ?, ?)",
        ("preexisting", "Existing User", '["student"]', "user_001_preexisting.db"),
    )
    fresh_conn.commit()

    pre_count = fresh_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert pre_count == 1

    _make_master_runner(fresh_conn).apply_pending()

    # Pre-existing row survived:
    post = fresh_conn.execute(
        "SELECT username FROM users WHERE database_filename = 'user_001_preexisting.db'"
    ).fetchone()
    assert post is not None
    assert post[0] == "preexisting"

    # Ledger now records v1:
    applied = {
        row[0]
        for row in fresh_conn.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall()
    }
    assert 1 in applied
