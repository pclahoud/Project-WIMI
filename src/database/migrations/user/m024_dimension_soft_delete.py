"""User DB migration v24 — dimensions get a soft delete and a journal (#210).

`delete_dimension` was a hard `DELETE FROM exam_dimensions`, and
`subject_nodes.dimension_id` was added by a bare `ALTER TABLE` with **no
FOREIGN KEY and no ON DELETE clause**. So deleting a dimension left every
subject in it pointing at a row that no longer existed:

* absent from every dimension's view, because the dimension it names is not
  listed any more;
* absent from the no-dimension view, because `dimension_id` is not `NULL` --
  which is the predicate that path uses.

The rows survive and no entry data is lost. What is lost is **reachability**:
the subjects carry entries and cannot be selected, renamed, re-weighted or
deleted through the tree editor. Irreversibly, and with nothing said.

The owner chose (b): soft delete plus a journal, mirroring #67 literally
rather than in spirit. (a) -- "import never removes a dimension" -- would
have created the second removal path #67 explicitly forbids.

Why a separate journal table rather than reusing the subject one
----------------------------------------------------------------
A dimension archive produces **one dimension-level event plus N subject
batches**, one per root in that dimension. #37 restores *a batch*, so the two
levels have to be related somehow. Two shapes were available:

1. **Span one batch across both levels.** `subject_delete_batches.root_node_id`
   is `NOT NULL` and a dimension event has no root node, so this means
   relaxing that constraint -- which SQLite cannot do in place, making it a
   create-copy-drop-rename of a table holding **real journal rows**. And
   `subject_delete_batch_items.item_type` is a closed CHECK, so adding
   `'dimension_archived'` is a *second* rebuild of a live table. m019 already
   had to do exactly that once to add `'relation_hidden'`.

2. **A separate table referencing the subject batches.** Purely additive.
   Rebuilds nothing.

(2), on the grounds that rebuilding two tables of real journal data to avoid
one new table is the worse trade. The relation is explicit
(`dimension_delete_batch_subjects`) rather than implied by a timestamp,
because #37 has to restore exactly the right set and "the batches created in
the same second" is not a relation.

`display_order` and the UNIQUE constraint
-----------------------------------------
`exam_dimensions` carries `UNIQUE(exam_id, display_order)`, and an archived
dimension that kept its slot would block a new dimension from taking it --
and would collide with #211's reorder, which assigns 1..N over the active
set. So archiving moves the row to `display_order = -id`: negative, so it can
never meet the positive range the reorder assigns into, and unique because
`id` is. Restoring (#37) has to pick a fresh order; there is no slot reserved.

This migration does not make anything restorable. #37 is what reads a
journal, and it is open. What changes today is the state a delete leaves
behind -- from *subjects active, referenced by nothing, editable by nobody*
to *subjects consistently archived alongside their dimension*, which is the
state #37 is being built to unwind.
"""
from __future__ import annotations

import sqlite3

VERSION = 24
NAME = "dimension_soft_delete"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def upgrade(conn: sqlite3.Connection) -> None:
    # `exam_dimensions` is created by the legacy `_ensure_phase7_schema`, not
    # by a numbered migration, so a database that has never opened Phase 7 may
    # not have it. Nothing to do there -- the ensure path creates the table
    # with these columns once this migration's VERSION is stamped.
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    }
    if 'exam_dimensions' in tables:
        existing = _columns(conn, 'exam_dimensions')

        if 'status' not in existing:
            # Mirrors `subject_nodes.status`: TEXT, defaulting to 'active'.
            # Not a CHECK constraint, for the same reason `subject_nodes`
            # has none -- adding a value later would mean rebuilding the
            # table, and #37 may well need one.
            conn.execute(
                "ALTER TABLE exam_dimensions "
                "ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
            )

        if 'archived_batch_id' not in existing:
            # Mirrors `subject_nodes.deleted_batch_id`. Names the dimension
            # batch that archived this row, so #37 can find the rows a batch
            # touched without a second index of its own.
            conn.execute(
                "ALTER TABLE exam_dimensions ADD COLUMN archived_batch_id TEXT"
            )

        # Every read of this table filters on status now, and the common one
        # is "the active dimensions of this exam".
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_exam_dimensions_exam_status "
            "ON exam_dimensions(exam_id, status)"
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dimension_delete_batches (
            id             TEXT PRIMARY KEY,
            dimension_id   INTEGER NOT NULL,
            dimension_name TEXT,
            exam_id        INTEGER NOT NULL,
            created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # The relation to the subject batches this archive produced -- one row per
    # root that was archived. Explicit rather than inferred, because #37 must
    # restore exactly this set and nothing else.
    #
    # No FOREIGN KEY to `subject_delete_batches`: a purge (#38) may remove a
    # subject batch while the dimension event stays as a record that the
    # archive happened, and a hard FK would either block that or cascade the
    # dimension event away with it. The journal is a log, not a graph.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dimension_delete_batch_subjects (
            dimension_batch_id TEXT NOT NULL,
            subject_batch_id   TEXT NOT NULL,
            root_node_id       INTEGER NOT NULL,
            PRIMARY KEY (dimension_batch_id, subject_batch_id),
            FOREIGN KEY (dimension_batch_id)
                REFERENCES dimension_delete_batches(id) ON DELETE CASCADE
        )
        """
    )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dimension_delete_batches_dimension "
        "ON dimension_delete_batches(dimension_id)"
    )
