"""User DB migration v5 — entry_subject_mappings.primary_parent_id.

Adds the optional parent-context column described in §3.3 of
``docs/planning/POLYHIERARCHY_MIGRATION.md``. When the user tags an
entry with a leaf that has multiple parents, the entry form *may*
record which parent context the user navigated through (e.g., "this PE
question was logged from the Pregnancy Complications view"). NULL
means "no specific context — count under all parents."

Idempotent — ``add_column_if_missing`` is a no-op if the column is
already present.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 5
NAME = "primary_parent_id"


def upgrade(conn: sqlite3.Connection) -> None:
    add_column_if_missing(
        conn,
        "entry_subject_mappings",
        "primary_parent_id",
        "INTEGER REFERENCES subject_nodes(id) ON DELETE SET NULL",
    )
