"""User DB migration v25 — ``exam_dimensions.import_id`` (#66 decision 2.3).

The dimension-level mirror of ``subject_nodes.import_id`` (m020). The
whole-exam import file names its dimensions, and this is where that name is
kept so a re-import recognises the axis it already created.

**Why it matters more here than for a subject.** Without a stable id a
renamed dimension is a remove-plus-add — #67's ``rename_blind`` — and at this
level that takes the axis's entire subject tree with it. #210 made a
dimension removal soft and journalled rather than destructive, but a rename
misread as a removal is still every subject in that axis archived for the
sake of a spelling change.

**Why the partial index can carry ``status`` here, and could not before.**

```sql
CREATE UNIQUE INDEX ... ON exam_dimensions(exam_id, import_id)
WHERE import_id IS NOT NULL AND status = 'active'
```

The ``status = 'active'`` predicate exists only because #210 chose option
(b), soft delete. Under (a) — "import never removes a dimension" — there
would be no such column, and the index would have had to constrain archived
rows too: a dimension the import removed keeps its row *and* its id, and
re-importing a file that lists it again must be free to create it rather than
fail against a row nothing can see. That is m020's reasoning, one level up,
and it is one more way (b) was the coherent choice.

**One difference from m020.** That index wraps its nullable ``dimension_id``
in ``COALESCE(..., -1)``, because NULL never equals NULL in an index and the
no-dimension case still has to be constrained. ``exam_dimensions.exam_id`` is
``NOT NULL``, so there is no analogue and none is added.

**Nothing populates this column yet.** Adoption on first sight, and export
writing the id back out as the file's ``id`` rather than ``exam_dimensions.id``,
both belong to the importer — #66 Wave 3 — because an identifier in a file
format means nothing until something reads it. This migration is the schema
that work needs, landed in Wave 2 where the milestone puts it. Mirroring m020
exactly: that column is also written only by the importer, and a hand-built
tree exports id-free.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 25
NAME = "dimension_import_id"


def upgrade(conn: sqlite3.Connection) -> None:
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    }
    # `exam_dimensions` is created by the legacy `_ensure_phase7_schema`, not
    # by a numbered migration, so a database that has never opened Phase 7
    # does not have it. The ensure path creates the column itself in that
    # case — the same split m024 had to handle.
    if 'exam_dimensions' not in tables:
        return

    add_column_if_missing(conn, "exam_dimensions", "import_id", "TEXT")

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_exam_dimensions_import_id "
        "ON exam_dimensions(exam_id, import_id) "
        "WHERE import_id IS NOT NULL AND status = 'active'"
    )
