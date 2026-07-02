"""Tests for user-DB migration v5 (entry_subject_mappings.primary_parent_id).

Adds the optional parent-context column described in §3.3 of
``docs/planning/POLYHIERARCHY_MIGRATION.md``.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner, build_migration
from database.migrations._helpers import get_column_names
from database.migrations.user import (
    m001_baseline,
    m002_phase6_goals,
    m003_phase7_dimensions,
    m004_subject_edges,
    m005_primary_parent_id,
)


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(
        conn,
        registry=[
            build_migration(m001_baseline),
            build_migration(m002_phase6_goals),
            build_migration(m003_phase7_dimensions),
            build_migration(m004_subject_edges),
            build_migration(m005_primary_parent_id),
        ],
        scope="user",
    )


def test_column_added(fresh_conn):
    """Fresh DB after m005 → primary_parent_id column on entry_subject_mappings."""
    _full_runner(fresh_conn).apply_pending()

    cols = get_column_names(fresh_conn, "entry_subject_mappings")
    assert "primary_parent_id" in cols


def test_idempotent(fresh_conn):
    """Re-running v5 against an already-migrated DB does not error."""
    _full_runner(fresh_conn).apply_pending()

    # Manually re-invoke the upgrade body — bypass the ledger so the
    # function actually runs again rather than no-op'ing via pending().
    m005_primary_parent_id.upgrade(fresh_conn)

    cols = get_column_names(fresh_conn, "entry_subject_mappings")
    assert "primary_parent_id" in cols

    # Confirm it didn't double-add (would raise sqlite3.OperationalError
    # via add_column_if_missing's idempotency check).
    m005_primary_parent_id.upgrade(fresh_conn)
    cols = get_column_names(fresh_conn, "entry_subject_mappings")
    # Still just one primary_parent_id column.
    pp_count = sum(1 for c in cols if c == "primary_parent_id")
    assert pp_count == 1
