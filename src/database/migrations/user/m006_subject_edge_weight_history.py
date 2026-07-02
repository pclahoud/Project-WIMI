"""User DB migration v6 — subject_node_weights gains edge_id + broader change_type enum.

Stage 0 of the Hierarchical Weight Allocation Implementation Plan
(``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``). Every
later stage in that plan needs to record per-edge weight history (anchor
toggles, allocation recomputes, rebalance requests). The legacy
``subject_node_weights`` table is keyed only on ``subject_node_id`` and
its ``change_type`` CHECK constraint does not permit the new event
classes. This migration adds:

1. ``edge_id INTEGER REFERENCES subject_edges(id) ON DELETE SET NULL``
   nullable so historical rows (and any node-level event without a
   specific parent context) can still be recorded.
2. A broader ``change_type`` CHECK enum that adds:
   ``'anchor_set'``, ``'anchor_cleared'``, ``'allocation_recompute'``,
   ``'rebalance_request'``, ``'edge_weight_edit'``.
3. ``idx_weight_history_by_edge`` for efficient per-edge lookups.

SQLite cannot ``ALTER`` a CHECK constraint in place, so the
change_type widening uses the standard rebuild pattern: create a
replacement table, copy rows across, drop the original, rename the
replacement, recreate every original index. The plan explicitly
chose to *not* rename the table itself — the existing call sites in
``hierarchy.py`` and the bridge layer would all need updating, with
no offsetting benefit.

Idempotent: re-running on an already-migrated DB is a no-op. The
column-add is gated on a ``PRAGMA table_info`` lookup, the table
rebuild is skipped when the new ``change_type`` values are already
accepted, and the index uses ``CREATE INDEX IF NOT EXISTS``.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing, get_column_names, get_table_names

VERSION = 6
NAME = "subject_edge_weight_history"


# Original change_type values from user_db_schema_v1_phase2.sql.
_LEGACY_CHANGE_TYPES = (
    "initial",
    "manual_edit",
    "auto_recalculate",
    "parent_redistribution",
    "import",
    "bulk_update",
)

# New per-edge event classes added by this migration.
_NEW_CHANGE_TYPES = (
    "anchor_set",
    "anchor_cleared",
    "allocation_recompute",
    "rebalance_request",
    "edge_weight_edit",
)

_ALL_CHANGE_TYPES = _LEGACY_CHANGE_TYPES + _NEW_CHANGE_TYPES


def _change_type_check_already_widened(conn: sqlite3.Connection) -> bool:
    """Return True when subject_node_weights already accepts the new enum.

    We probe the CHECK constraint by inspecting the table's CREATE
    statement in sqlite_master — cheaper than a SAVEPOINT/INSERT round
    trip and side-effect free.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='subject_node_weights'"
    ).fetchone()
    if row is None:
        return False
    sql = row[0] or ""
    # Presence of any single new value implies the rebuild has run.
    return "anchor_set" in sql


def _rebuild_table_with_widened_check(conn: sqlite3.Connection) -> None:
    """Rebuild subject_node_weights with the broader change_type CHECK.

    Standard SQLite ``ALTER CHECK`` workaround: create a new table with
    the desired schema, copy rows, drop the old, rename. We preserve
    every existing column (including ``edge_id`` if added earlier in
    this same migration run) so the rebuild is order-independent
    relative to the column-add step.
    """
    existing_cols = get_column_names(conn, "subject_node_weights")
    has_edge_id = "edge_id" in existing_cols

    # Build the column list and foreign-key clauses for the new table.
    # Mirror the v1 phase2 schema; only the change_type CHECK and the
    # optional edge_id column differ.
    edge_id_col_def = (
        "    edge_id INTEGER REFERENCES subject_edges(id) ON DELETE SET NULL,\n"
        if has_edge_id
        else ""
    )
    change_type_values = ", ".join(f"'{v}'" for v in _ALL_CHANGE_TYPES)

    conn.execute(
        f"""
        CREATE TABLE subject_node_weights_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_node_id INTEGER NOT NULL
                REFERENCES subject_nodes(id) ON DELETE CASCADE,

            weight_value DECIMAL(6,3) NOT NULL CHECK (weight_value >= 0 AND weight_value <= 100),
            edited_date DATE NOT NULL DEFAULT (date('now')),

            edited_by TEXT NOT NULL DEFAULT 'user'
                CHECK (edited_by IN ('user', 'system', 'import', 'migration')),
            edited_reason TEXT,

            previous_weight DECIMAL(6,3),

            change_type TEXT NOT NULL DEFAULT 'initial'
                CHECK (change_type IN ({change_type_values})),

            affected_siblings TEXT DEFAULT '[]' CHECK (json_valid(affected_siblings)),

            user_notes TEXT,

        {edge_id_col_def}    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Copy rows. Use only the columns that exist in the *old* table to
    # stay compatible with whatever stray columns the live schema may
    # have accumulated — e.g. ``relative_weight_value`` / ``weight_type``
    # that some hierarchy.py call sites probe defensively even though
    # the schema does not declare them. We list the canonical columns
    # explicitly so the SELECT order matches the new table's INSERT.
    canonical_old_cols = [
        "id",
        "subject_node_id",
        "weight_value",
        "edited_date",
        "edited_by",
        "edited_reason",
        "previous_weight",
        "change_type",
        "affected_siblings",
        "user_notes",
    ]
    if has_edge_id:
        canonical_old_cols.append("edge_id")
    canonical_old_cols.append("created_at")

    # Filter to columns that actually exist (defensive — every entry in
    # the canonical list should be present, but the table may pre-date
    # some columns on a partially-migrated DB).
    copy_cols = [c for c in canonical_old_cols if c in existing_cols]
    cols_csv = ", ".join(copy_cols)
    conn.execute(
        f"INSERT INTO subject_node_weights_new ({cols_csv}) "
        f"SELECT {cols_csv} FROM subject_node_weights"
    )

    # The phase2 schema defines a view ``v_weight_change_summary`` that
    # references ``subject_node_weights``. SQLite refuses to RENAME a
    # table out from under a view, so drop the view first and rebuild
    # it after the rename. The view definition is byte-identical to
    # phase2 — keep it in sync if either side ever changes shape.
    conn.execute("DROP VIEW IF EXISTS v_weight_change_summary")

    conn.execute("DROP TABLE subject_node_weights")
    conn.execute("ALTER TABLE subject_node_weights_new RENAME TO subject_node_weights")

    conn.execute(
        """
        CREATE VIEW IF NOT EXISTS v_weight_change_summary AS
        SELECT
            snw.subject_node_id,
            sn.name as subject_name,
            sn.exam_context,
            COUNT(*) as change_count,
            MIN(snw.edited_date) as first_change_date,
            MAX(snw.edited_date) as last_change_date,
            SUM(CASE WHEN snw.change_type = 'manual_edit' THEN 1 ELSE 0 END) as manual_edits,
            SUM(CASE WHEN snw.change_type = 'auto_recalculate' THEN 1 ELSE 0 END) as auto_adjustments
        FROM subject_node_weights snw
        JOIN subject_nodes sn ON snw.subject_node_id = sn.id
        GROUP BY snw.subject_node_id
        """
    )

    # Recreate the original indexes from phase2.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_weight_history_by_node "
        "ON subject_node_weights (subject_node_id, edited_date DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_weight_changes_by_date "
        "ON subject_node_weights (edited_date DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_weight_changes_by_type "
        "ON subject_node_weights (change_type, edited_date DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_weight_changes "
        "ON subject_node_weights (edited_by, edited_date DESC) "
        "WHERE edited_by = 'user'"
    )


def upgrade(conn: sqlite3.Connection) -> None:
    # The Phase 2 baseline migration creates subject_node_weights, so
    # under normal flow the table is always present. Guard defensively
    # for tests that may invoke this migration in isolation.
    if "subject_node_weights" not in get_table_names(conn):
        return

    # 1. Add the nullable edge_id column (idempotent).
    add_column_if_missing(
        conn,
        "subject_node_weights",
        "edge_id",
        "INTEGER REFERENCES subject_edges(id) ON DELETE SET NULL",
    )

    # 2. Widen the change_type CHECK constraint via table rebuild
    #    (idempotent — gated on whether the new values already appear
    #    in the table's CREATE statement).
    if not _change_type_check_already_widened(conn):
        _rebuild_table_with_widened_check(conn)

    # 3. New index for per-edge history lookups.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_weight_history_by_edge "
        "ON subject_node_weights (edge_id, edited_date DESC)"
    )
