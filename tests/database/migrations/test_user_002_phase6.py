"""Tests for user-DB migration v2 (Phase 6: goals + reflection themes)."""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner, build_migration
from database.migrations._helpers import get_table_names, read_schema_file
from database.migrations.user import m001_baseline, m002_phase6_goals


def _runner_with(conn: sqlite3.Connection, *modules) -> MigrationRunner:
    return MigrationRunner(
        conn,
        registry=[build_migration(m) for m in modules],
        scope="user",
    )


def test_phase6_creates_goals_tables(fresh_conn):
    """Baseline + v2 → user_goals, goal_periods, reflection_themes all exist."""
    _runner_with(fresh_conn, m001_baseline, m002_phase6_goals).apply_pending()

    tables = get_table_names(fresh_conn)
    assert "user_goals" in tables
    assert "goal_periods" in tables
    assert "reflection_themes" in tables


def test_phase6_idempotent_when_tables_exist(fresh_conn):
    """If the phase6 tables already exist, running v2 is a safe no-op."""
    # Pre-create the phase6 tables manually by executing the schema file
    # against a fresh conn (no baseline). The migration should detect the
    # tables and short-circuit.
    fresh_conn.executescript(read_schema_file("user_db_schema_v1_phase6.sql"))

    runner = MigrationRunner(
        fresh_conn,
        registry=[build_migration(m002_phase6_goals)],
        scope="user",
    )
    # No exception:
    applied = runner.apply_pending()
    assert applied == [2]

    tables = get_table_names(fresh_conn)
    assert "user_goals" in tables
    assert "goal_periods" in tables
    assert "reflection_themes" in tables
