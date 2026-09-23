"""User DB migration v18 — subject delete batches (the delete journal).

Deleting a subject is a *soft* delete: the node's ``status`` flips to
``'archived'`` and the row stays. Issue #15 decision 4 makes that delete
undoable, and undoable at the granularity of the whole operation rather
than a single row — "restore" has to mean *undo that deletion*, not
*un-archive this one node*. A delete can archive a subtree, strip the
edges that attached surviving children to it, and clear the parent
context off entry mappings, so a per-row flag cannot describe it.

Three things land here:

``subject_nodes.deleted_batch_id``
    The stamp. NULL for every node that was never deleted; set to the
    batch id of the operation that archived it. Deliberately **not** a
    foreign key: the purge path (#38) must be free to drop a batch
    without either being blocked by, or cascading into, the nodes it
    names. The same reasoning as ``user_preferences.pane_default_source_id``
    in m016 — a dangling id degrades to "no batch known", which is a
    recoverable state, while a cascade would be data loss.

``subject_delete_batches``
    One row per delete. Records what the user asked for: which node,
    and whether they chose to promote its direct children to the top
    level rather than delete them (decision 2's modal shape A).

``subject_delete_batch_items``
    The journal of reversible side effects, one row per mutation:

    - ``node_archived`` — ``subject_node_id`` flipped to archived.
    - ``edge_removed`` — the ``subject_edges`` row named by
      ``parent_id``/``subject_node_id`` was deleted. ``payload`` carries
      the full edge snapshot (``is_primary``, ``display_order``,
      ``relative_weight``, ``weight_source``, ``is_anchor``) so restore
      can rebuild the edge byte-identical rather than with defaults,
      plus ``promoted``: #37 re-attaches a merely-detached shared child
      but deliberately does not re-parent one the user chose to promote,
      and which of the two it was is only knowable at delete time.
    - ``primary_parent_cleared`` — ``entry_subject_mappings.primary_parent_id``
      was nulled on the mapping named by ``entry_subject_mapping_id``;
      ``parent_id`` records the value that was cleared.

    ``item_type`` is constrained so a typo fails loudly at insert time
    instead of producing journal rows restore will silently skip.

**This migration ships the schema only.** Nothing reads the journal yet
— #37 (restore + the Archived panel) and #38 (purge) are separate
issues that depend on this one. It is here because the batch id has to
exist in the schema *before* deletes start happening, or the first
restore has nothing to undo for every deletion made in the meantime.

Idempotent: ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT
EXISTS`` for the DDL, ``add_column_if_missing`` for the column.

Versions 8 and 11-14 are absent from the registry by design — see
m015's docstring — so this follows m017 without a gap of its own.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing, get_column_names

VERSION = 18
NAME = "subject_delete_batches"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subject_delete_batches (
            id               TEXT PRIMARY KEY,
            root_node_id     INTEGER NOT NULL,
            root_node_name   TEXT,
            promote_children BOOLEAN NOT NULL DEFAULT FALSE,
            created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subject_delete_batch_items (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL
                REFERENCES subject_delete_batches(id) ON DELETE CASCADE,
            item_type TEXT NOT NULL CHECK(item_type IN (
                'node_archived', 'edge_removed', 'primary_parent_cleared'
            )),

            -- node_archived: the archived node.
            -- edge_removed:  the edge's child.
            -- primary_parent_cleared: the mapping's subject.
            subject_node_id INTEGER,
            -- edge_removed: the edge's parent.
            -- primary_parent_cleared: the value that was nulled.
            parent_id INTEGER,
            -- primary_parent_cleared: entry_subject_mappings.id.
            entry_subject_mapping_id INTEGER,

            -- JSON snapshot of whatever else restore needs (edge
            -- weights, the status the node held before archiving).
            payload TEXT NOT NULL DEFAULT '{}',

            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sdb_items_batch "
        "ON subject_delete_batch_items(batch_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sdb_items_node "
        "ON subject_delete_batch_items(subject_node_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sdb_root "
        "ON subject_delete_batches(root_node_id)"
    )

    add_column_if_missing(conn, "subject_nodes", "deleted_batch_id", "TEXT")
    # Guarded: ``add_column_if_missing`` is a silent no-op when the table
    # itself is absent (a bare database in an early test setup), and an
    # unguarded CREATE INDEX on a missing column would then raise.
    if "deleted_batch_id" in get_column_names(conn, "subject_nodes"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_subject_nodes_deleted_batch "
            "ON subject_nodes(deleted_batch_id)"
        )
