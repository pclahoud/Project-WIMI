"""Tests for user-DB migration v6 (subject_node_weights edge_id + change_type).

Stage 0 of ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.
Verifies the new ``edge_id`` column, the broadened ``change_type`` CHECK
enum, the per-edge index, idempotency, and that the legacy enum values
still pass.
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
    m006_subject_edge_weight_history,
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
            build_migration(m006_subject_edge_weight_history),
        ],
        scope="user",
    )


# ---------------------------------------------------------------- helpers


def _seed_subject_node(conn: sqlite3.Connection, node_id: int = 1) -> int:
    """Insert a minimal subject_nodes row so weight rows can FK to it."""
    conn.execute(
        "INSERT INTO subject_nodes (id, exam_context, name, level_type, parent_id) "
        "VALUES (?, 'USMLE', ?, 'System', NULL)",
        (node_id, f"Node{node_id}"),
    )
    conn.commit()
    return node_id


def _seed_subject_edge(
    conn: sqlite3.Connection,
    parent_id: int,
    child_id: int,
) -> int:
    """Insert a subject_edges row and return its id."""
    cur = conn.execute(
        "INSERT INTO subject_edges (parent_id, child_id, is_primary) "
        "VALUES (?, ?, TRUE)",
        (parent_id, child_id),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------- tests


def test_migration_adds_edge_id_column(fresh_conn):
    """Fresh DB after m006 → edge_id column on subject_node_weights."""
    _full_runner(fresh_conn).apply_pending()

    cols = get_column_names(fresh_conn, "subject_node_weights")
    assert "edge_id" in cols


def test_migration_is_idempotent(fresh_conn):
    """Re-running m006 against an already-migrated DB is a no-op."""
    _full_runner(fresh_conn).apply_pending()

    cols_before = get_column_names(fresh_conn, "subject_node_weights")

    # Manually re-invoke the upgrade body — bypass the ledger so the
    # function actually runs again rather than being skipped via
    # pending().
    m006_subject_edge_weight_history.upgrade(fresh_conn)
    m006_subject_edge_weight_history.upgrade(fresh_conn)

    cols_after = get_column_names(fresh_conn, "subject_node_weights")
    assert cols_before == cols_after

    # Still exactly one edge_id column (would be a duplicate-add error
    # otherwise, swallowed by add_column_if_missing).
    edge_id_count = sum(1 for c in cols_after if c == "edge_id")
    assert edge_id_count == 1


def test_change_type_accepts_new_values(fresh_conn):
    """The broadened CHECK enum accepts the new per-edge event classes."""
    _full_runner(fresh_conn).apply_pending()
    parent_id = _seed_subject_node(fresh_conn, node_id=1)
    child_id = _seed_subject_node(fresh_conn, node_id=2)
    edge_id = _seed_subject_edge(fresh_conn, parent_id, child_id)

    new_values = (
        "anchor_set",
        "anchor_cleared",
        "allocation_recompute",
        "rebalance_request",
        "edge_weight_edit",
    )
    for change_type in new_values:
        fresh_conn.execute(
            "INSERT INTO subject_node_weights "
            "(subject_node_id, weight_value, change_type, edge_id) "
            "VALUES (?, ?, ?, ?)",
            (child_id, 25.0, change_type, edge_id),
        )
    fresh_conn.commit()

    rows = fresh_conn.execute(
        "SELECT change_type FROM subject_node_weights WHERE subject_node_id = ?",
        (child_id,),
    ).fetchall()
    actual = {row[0] for row in rows}
    assert actual == set(new_values)


def test_legacy_change_type_still_works(fresh_conn):
    """The original change_type enum values must continue to be accepted."""
    _full_runner(fresh_conn).apply_pending()
    node_id = _seed_subject_node(fresh_conn, node_id=1)

    legacy_values = (
        "initial",
        "manual_edit",
        "auto_recalculate",
        "parent_redistribution",
        "import",
        "bulk_update",
    )
    for change_type in legacy_values:
        fresh_conn.execute(
            "INSERT INTO subject_node_weights "
            "(subject_node_id, weight_value, change_type) "
            "VALUES (?, ?, ?)",
            (node_id, 12.5, change_type),
        )
    fresh_conn.commit()

    rows = fresh_conn.execute(
        "SELECT change_type FROM subject_node_weights WHERE subject_node_id = ?",
        (node_id,),
    ).fetchall()
    actual = {row[0] for row in rows}
    assert actual == set(legacy_values)


def test_change_type_rejects_unknown_value(fresh_conn):
    """Sanity: the CHECK still rejects values outside the union of legacy + new."""
    _full_runner(fresh_conn).apply_pending()
    node_id = _seed_subject_node(fresh_conn, node_id=1)

    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO subject_node_weights "
            "(subject_node_id, weight_value, change_type) "
            "VALUES (?, ?, ?)",
            (node_id, 10.0, "totally_made_up_event"),
        )


def test_edge_id_index_exists(fresh_conn):
    """The new per-edge history index is created."""
    _full_runner(fresh_conn).apply_pending()

    rows = fresh_conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND tbl_name='subject_node_weights'"
    ).fetchall()
    index_names = {row[0] for row in rows}
    assert "idx_weight_history_by_edge" in index_names

    # Pre-existing indexes survive the table rebuild.
    assert "idx_weight_history_by_node" in index_names
    assert "idx_weight_changes_by_date" in index_names
    assert "idx_weight_changes_by_type" in index_names


def test_edge_id_nullable(fresh_conn):
    """edge_id is nullable so legacy/node-level rows still write cleanly."""
    _full_runner(fresh_conn).apply_pending()
    node_id = _seed_subject_node(fresh_conn, node_id=1)

    fresh_conn.execute(
        "INSERT INTO subject_node_weights "
        "(subject_node_id, weight_value, change_type, edge_id) "
        "VALUES (?, ?, 'manual_edit', NULL)",
        (node_id, 33.3),
    )
    fresh_conn.commit()

    row = fresh_conn.execute(
        "SELECT edge_id FROM subject_node_weights WHERE subject_node_id = ?",
        (node_id,),
    ).fetchone()
    assert row[0] is None


def test_edge_id_set_null_on_edge_delete(fresh_conn):
    """Deleting a subject_edges row nulls out edge_id on referencing history rows."""
    _full_runner(fresh_conn).apply_pending()
    parent_id = _seed_subject_node(fresh_conn, node_id=1)
    child_id = _seed_subject_node(fresh_conn, node_id=2)
    edge_id = _seed_subject_edge(fresh_conn, parent_id, child_id)

    fresh_conn.execute(
        "INSERT INTO subject_node_weights "
        "(subject_node_id, weight_value, change_type, edge_id) "
        "VALUES (?, ?, 'edge_weight_edit', ?)",
        (child_id, 20.0, edge_id),
    )
    fresh_conn.commit()

    fresh_conn.execute("DELETE FROM subject_edges WHERE id = ?", (edge_id,))
    fresh_conn.commit()

    row = fresh_conn.execute(
        "SELECT edge_id FROM subject_node_weights WHERE subject_node_id = ?",
        (child_id,),
    ).fetchone()
    assert row[0] is None
