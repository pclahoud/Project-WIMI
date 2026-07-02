"""User DB migration v4 — subject_edges junction table (polyhierarchy).

Foundation of the polyhierarchy migration described in
``docs/planning/POLYHIERARCHY_MIGRATION.md``. Creates the
``subject_edges`` junction table that allows a subject node to have
multiple parents within the same exam dimension, then backfills it
with one ``is_primary=TRUE`` edge per existing ``subject_nodes.parent_id``
relationship.

This migration is intentionally *additive*:

- It does NOT drop ``subject_nodes.parent_id``. That happens in a
  follow-up migration (§4 Migration 3 of the plan), after one stable
  release with all read paths cut over to ``subject_edges``.
- ``CREATE TABLE IF NOT EXISTS`` and ``CREATE INDEX IF NOT EXISTS`` make
  the DDL re-runnable; the ``INSERT OR IGNORE`` pairs with the
  ``UNIQUE(parent_id, child_id)`` constraint to make the backfill safe
  to re-run if interrupted partway through.

Per-edge weight metadata columns (``is_anchor``, ``relative_weight``,
``weight_source``) are created here even though they are consumed by
the companion ``HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`` plan that
lands in a later migration. Defining them in v4 keeps the table shape
stable and avoids a follow-up ``ALTER TABLE`` for the weight rework.
"""
from __future__ import annotations

import sqlite3

VERSION = 4
NAME = "subject_edges"


def upgrade(conn: sqlite3.Connection) -> None:
    # ---- Create subject_edges table (idempotent) ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subject_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER NOT NULL REFERENCES subject_nodes(id) ON DELETE CASCADE,
            child_id  INTEGER NOT NULL REFERENCES subject_nodes(id) ON DELETE CASCADE,

            -- per-edge attributes (some consumed by HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md)
            is_primary       BOOLEAN NOT NULL DEFAULT FALSE,
            display_order    INTEGER NOT NULL DEFAULT 0,
            is_anchor        BOOLEAN NOT NULL DEFAULT FALSE,
            relative_weight  REAL,
            weight_source    TEXT NOT NULL DEFAULT 'derived'
                CHECK(weight_source IN ('official','derived','user_estimate','user_defined','user_explicit')),

            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(parent_id, child_id),
            CHECK(parent_id != child_id)
        )
        """
    )

    # ---- Indexes (idempotent) ----
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subject_edges_parent "
        "ON subject_edges(parent_id, display_order)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subject_edges_child "
        "ON subject_edges(child_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subject_edges_primary "
        "ON subject_edges(child_id) WHERE is_primary = TRUE"
    )

    # ---- Backfill: one is_primary=TRUE edge per (parent_id, child) pair ----
    # OR IGNORE makes this safe to re-run; the UNIQUE(parent_id, child_id)
    # constraint prevents duplicates if a partial backfill was interrupted.
    conn.execute(
        """
        INSERT OR IGNORE INTO subject_edges (parent_id, child_id, is_primary, display_order)
        SELECT parent_id, id, TRUE, COALESCE(sort_order, 0)
        FROM subject_nodes
        WHERE parent_id IS NOT NULL
        """
    )
