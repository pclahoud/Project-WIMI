"""Tests for user-DB migration v3 (Phase 7: multi-dimensional hierarchies)."""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner, build_migration
from database.migrations._helpers import get_table_names
from database.migrations.user import (
    m001_baseline,
    m002_phase6_goals,
    m003_phase7_dimensions,
)


def _runner_with(conn: sqlite3.Connection, *modules) -> MigrationRunner:
    return MigrationRunner(
        conn,
        registry=[build_migration(m) for m in modules],
        scope="user",
    )


def test_phase7_creates_dimension_tables(fresh_conn):
    """Baseline + v2 + v3 → exam_dimensions and question_hierarchy_tags exist."""
    _runner_with(
        fresh_conn,
        m001_baseline,
        m002_phase6_goals,
        m003_phase7_dimensions,
    ).apply_pending()

    tables = get_table_names(fresh_conn)
    assert "exam_dimensions" in tables
    assert "question_hierarchy_tags" in tables


def test_phase7_idempotent(fresh_conn):
    """Re-running v3 against an already-migrated DB is a no-op."""
    runner = _runner_with(
        fresh_conn,
        m001_baseline,
        m002_phase6_goals,
        m003_phase7_dimensions,
    )
    runner.apply_pending()

    tables_first = get_table_names(fresh_conn)

    # Manually re-invoke the upgrade body — bypass the ledger so the
    # function actually runs again rather than being filtered out by
    # ``pending()``.
    m003_phase7_dimensions.upgrade(fresh_conn)

    tables_second = get_table_names(fresh_conn)
    assert tables_first == tables_second
