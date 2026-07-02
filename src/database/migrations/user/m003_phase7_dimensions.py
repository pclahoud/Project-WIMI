"""User DB migration v3 — Phase 7 (multi-dimensional hierarchies).

Was previously created lazily by ``_ensure_phase7_schema()``, called at
the top of every dimensions operation. Now applied eagerly at DB init.

Tables created:

- ``exam_dimensions``
- ``question_hierarchy_tags``

(``subject_nodes.dimension_id`` is added by the baseline migration —
that column has been part of the v1 shape for a while now.)

Idempotent — falls back to inline SQL if the schema file is missing,
matching the historical behavior of ``_ensure_phase7_schema``.
"""
from __future__ import annotations

import sqlite3

from .._helpers import (
    get_table_names,
    read_schema_file,
    run_schema_script,
)

VERSION = 3
NAME = "phase7_dimensions"


def upgrade(conn: sqlite3.Connection) -> None:
    phase7_tables = {"exam_dimensions", "question_hierarchy_tags"}
    if phase7_tables.issubset(get_table_names(conn)):
        return
    try:
        run_schema_script(conn, "user_db_schema_v1_phase7.sql")
    except FileNotFoundError:
        # Schema file missing in this build — fall back to the inline
        # SQL the original ``_ensure_phase7_schema`` used as a safety
        # net. Kept verbatim so the checksum locks in the same shape.
        _create_phase7_inline(conn)


def _create_phase7_inline(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS exam_dimensions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            display_order INTEGER NOT NULL,
            is_required INTEGER DEFAULT 1,
            allow_multiple INTEGER DEFAULT 0,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (exam_id) REFERENCES exam_contexts(id) ON DELETE CASCADE,
            UNIQUE(exam_id, name),
            UNIQUE(exam_id, display_order)
        );
        CREATE INDEX IF NOT EXISTS idx_dimensions_exam
            ON exam_dimensions(exam_id);
        CREATE INDEX IF NOT EXISTS idx_dimensions_order
            ON exam_dimensions(exam_id, display_order);

        CREATE TABLE IF NOT EXISTS question_hierarchy_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            hierarchy_id INTEGER NOT NULL,
            dimension_id INTEGER NOT NULL,
            tagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (entry_id) REFERENCES question_entries(id) ON DELETE CASCADE,
            FOREIGN KEY (hierarchy_id) REFERENCES subject_nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (dimension_id) REFERENCES exam_dimensions(id) ON DELETE CASCADE,
            UNIQUE(entry_id, dimension_id, hierarchy_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tags_entry
            ON question_hierarchy_tags(entry_id);
        CREATE INDEX IF NOT EXISTS idx_tags_hierarchy
            ON question_hierarchy_tags(hierarchy_id);
        CREATE INDEX IF NOT EXISTS idx_tags_dimension
            ON question_hierarchy_tags(dimension_id);
        CREATE INDEX IF NOT EXISTS idx_tags_entry_dimension
            ON question_hierarchy_tags(entry_id, dimension_id);
        """
    )
