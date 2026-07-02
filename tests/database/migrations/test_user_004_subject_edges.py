"""Tests for user-DB migration v4 (subject_edges junction table).

Foundation of the polyhierarchy migration described in
``docs/planning/POLYHIERARCHY_MIGRATION.md``. Verifies the table is
created, the backfill produces exactly one ``is_primary=TRUE`` edge per
existing ``subject_nodes.parent_id`` relationship, ``sort_order`` is
preserved as ``display_order``, and the migration is idempotent.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner, build_migration
from database.migrations._helpers import get_column_names, get_table_names
from database.migrations.user import (
    m001_baseline,
    m002_phase6_goals,
    m003_phase7_dimensions,
    m004_subject_edges,
)


def _runner_with(conn: sqlite3.Connection, *modules) -> MigrationRunner:
    return MigrationRunner(
        conn,
        registry=[build_migration(m) for m in modules],
        scope="user",
    )


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return _runner_with(
        conn,
        m001_baseline,
        m002_phase6_goals,
        m003_phase7_dimensions,
        m004_subject_edges,
    )


def test_subject_edges_table_created(fresh_conn):
    """Baseline + v2 + v3 + v4 → subject_edges exists with the right columns."""
    _full_runner(fresh_conn).apply_pending()

    tables = get_table_names(fresh_conn)
    assert "subject_edges" in tables

    cols = get_column_names(fresh_conn, "subject_edges")
    expected = {
        "id",
        "parent_id",
        "child_id",
        "is_primary",
        "display_order",
        "is_anchor",
        "relative_weight",
        "weight_source",
        "created_at",
        "updated_at",
    }
    missing = expected - cols
    assert not missing, f"subject_edges missing columns: {sorted(missing)}"

    # Indexes also exist.
    index_rows = fresh_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='subject_edges'"
    ).fetchall()
    index_names = {row[0] for row in index_rows}
    assert "idx_subject_edges_parent" in index_names
    assert "idx_subject_edges_child" in index_names
    assert "idx_subject_edges_primary" in index_names


def test_backfill_creates_one_primary_edge_per_existing_child(fresh_conn):
    """Several subject_nodes with parent_id → one is_primary=TRUE edge per child."""
    # Apply only baseline + v2 + v3 first so we can populate subject_nodes
    # without v4 having backfilled anything yet.
    _runner_with(
        fresh_conn,
        m001_baseline,
        m002_phase6_goals,
        m003_phase7_dimensions,
    ).apply_pending()

    # Build a small tree:  Root  → ChildA, ChildB; ChildA → Grandchild
    fresh_conn.execute(
        "INSERT INTO subject_nodes (id, exam_context, name, level_type, parent_id, sort_order) "
        "VALUES (1, 'USMLE', 'Root',       'System',  NULL, 0)"
    )
    fresh_conn.execute(
        "INSERT INTO subject_nodes (id, exam_context, name, level_type, parent_id, sort_order) "
        "VALUES (2, 'USMLE', 'ChildA',     'Topic',   1,    0)"
    )
    fresh_conn.execute(
        "INSERT INTO subject_nodes (id, exam_context, name, level_type, parent_id, sort_order) "
        "VALUES (3, 'USMLE', 'ChildB',     'Topic',   1,    1)"
    )
    fresh_conn.execute(
        "INSERT INTO subject_nodes (id, exam_context, name, level_type, parent_id, sort_order) "
        "VALUES (4, 'USMLE', 'Grandchild', 'Subtopic', 2,   0)"
    )
    fresh_conn.commit()

    # Now apply v4.
    MigrationRunner(
        fresh_conn,
        registry=[build_migration(m004_subject_edges)],
        scope="user",
    ).apply_pending()

    edges = fresh_conn.execute(
        "SELECT parent_id, child_id, is_primary FROM subject_edges "
        "ORDER BY child_id"
    ).fetchall()

    # Three children had non-NULL parent_id, so three edges:
    assert len(edges) == 3

    # Each child has exactly one is_primary=TRUE edge.
    for child_id in (2, 3, 4):
        primary_count = fresh_conn.execute(
            "SELECT COUNT(*) FROM subject_edges "
            "WHERE child_id = ? AND is_primary = TRUE",
            (child_id,),
        ).fetchone()[0]
        assert primary_count == 1, f"child {child_id} did not get exactly 1 primary edge"

    # And parent_id matches the original subject_nodes.parent_id.
    edge_map = {row[1]: row[0] for row in edges}
    assert edge_map[2] == 1
    assert edge_map[3] == 1
    assert edge_map[4] == 2

    # Root (no parent) has no incoming edges.
    root_edge_count = fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_edges WHERE child_id = 1"
    ).fetchone()[0]
    assert root_edge_count == 0


def test_backfill_preserves_sort_order_as_display_order(fresh_conn):
    """subject_edges.display_order == subject_nodes.sort_order for backfilled rows."""
    _runner_with(
        fresh_conn,
        m001_baseline,
        m002_phase6_goals,
        m003_phase7_dimensions,
    ).apply_pending()

    fresh_conn.execute(
        "INSERT INTO subject_nodes (id, exam_context, name, level_type, parent_id, sort_order) "
        "VALUES (10, 'USMLE', 'Root', 'System', NULL, 0)"
    )
    # Children with various sort_order values.
    for child_id, sort_order in [(11, 5), (12, 17), (13, 0), (14, 99)]:
        fresh_conn.execute(
            "INSERT INTO subject_nodes (id, exam_context, name, level_type, parent_id, sort_order) "
            "VALUES (?, 'USMLE', ?, 'Topic', 10, ?)",
            (child_id, f"Child{child_id}", sort_order),
        )
    fresh_conn.commit()

    MigrationRunner(
        fresh_conn,
        registry=[build_migration(m004_subject_edges)],
        scope="user",
    ).apply_pending()

    rows = fresh_conn.execute(
        "SELECT child_id, display_order FROM subject_edges WHERE parent_id = 10"
    ).fetchall()
    actual = {row[0]: row[1] for row in rows}
    assert actual == {11: 5, 12: 17, 13: 0, 14: 99}


def test_v4_is_idempotent(fresh_conn):
    """Re-running v4 against an already-migrated DB does not error or duplicate."""
    _full_runner(fresh_conn).apply_pending()

    # Insert a parent + child to give the backfill something to operate on.
    fresh_conn.execute(
        "INSERT INTO subject_nodes (id, exam_context, name, level_type, parent_id, sort_order) "
        "VALUES (100, 'USMLE', 'Root', 'System', NULL, 0)"
    )
    fresh_conn.execute(
        "INSERT INTO subject_nodes (id, exam_context, name, level_type, parent_id, sort_order) "
        "VALUES (101, 'USMLE', 'Child', 'Topic', 100, 3)"
    )
    fresh_conn.commit()

    # Manually invoke the upgrade body again — bypass the ledger so we
    # actually re-execute the body, not just no-op via ``pending()``.
    m004_subject_edges.upgrade(fresh_conn)

    # The pre-existing edges from the runner's first pass remain; the
    # new (100, 101) pair gets backfilled exactly once.
    edge_count = fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_edges WHERE parent_id = 100 AND child_id = 101"
    ).fetchone()[0]
    assert edge_count == 1

    # Run it a third time — still no duplicates.
    m004_subject_edges.upgrade(fresh_conn)
    edge_count2 = fresh_conn.execute(
        "SELECT COUNT(*) FROM subject_edges WHERE parent_id = 100 AND child_id = 101"
    ).fetchone()[0]
    assert edge_count2 == 1
