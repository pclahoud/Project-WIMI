"""User DB migration v20 — ``subject_nodes.import_id`` (issue #67).

The subject-tree import format gains an optional ``id`` per subject.
This column is where that id is kept, so a re-import can recognise the
row it already created.

**Why a column and not name-and-path matching.** Re-import matched
nothing before this: ``import_node`` called ``create_subject_node``
unconditionally for every node in the file, and the only thing standing
between a user and a doubled tree was ``create_subject_node``'s
duplicate-name check — a *partial* merge whose outcome depended on which
nodes happened to be renamed. Matching on name-and-path instead makes a
rename indistinguishable from "the old subject was deleted and a new one
created", which orphans everything the student attached to it: entries,
weights, and the relations of #14. A stable id carried by the file is
the only thing that can tell a rename from a replacement.

**Scope.** The id is the *file's* identifier, not WIMI's — two different
exams may legitimately both call a subject ``"1.2.3"``. So it is unique
per import scope (exam context + dimension), not globally, and the
partial unique index below says exactly that. ``NULL`` is the normal
state: every node created through the tree editor has no import id, and
so does every node imported from a file that predates the field. A
``NULL`` never collides with another ``NULL`` in a SQLite unique index,
so unmatched nodes are unconstrained.

An existing node **adopts** an id the first time a file carries one for
a subject matched by name-and-path — that is the upgrade path for the
2,211-subject trees imported before ids existed, and the reason the
column is nullable rather than backfilled with something synthetic.
A synthetic backfill would be worse than nothing: it would claim ids no
file will ever mention, and the first real file would then find every
subject already spoken for.

Idempotent: ``add_column_if_missing`` plus ``CREATE INDEX IF NOT
EXISTS``.

Versions 8 and 11-14 are absent from the registry by design — see
m015's docstring — so this follows m019 without a gap of its own.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing, get_column_names

VERSION = 20
NAME = "subject_import_id"


def upgrade(conn: sqlite3.Connection) -> None:
    add_column_if_missing(conn, "subject_nodes", "import_id", "TEXT")

    # Guarded: ``add_column_if_missing`` is a silent no-op when the table
    # itself is absent (a bare database in an early test setup), and an
    # unguarded CREATE INDEX on a missing column would then raise.
    if "import_id" in get_column_names(conn, "subject_nodes"):
        # Partial index: only rows that actually carry an id take part,
        # so the common NULL case costs nothing and cannot collide.
        # ``dimension_id`` is in the key because a multi-dimensional exam
        # imports one dimension at a time and each file names its own
        # ids; ``COALESCE`` because NULL never equals NULL in an index
        # and the no-dimension case must still be constrained.
        #
        # ``status = 'active'`` is in the predicate because deletion is
        # soft: a subject the import removed keeps its row *and* its id,
        # and re-importing a file that lists that subject again must be
        # free to create it rather than fail on an index shared with a
        # row nothing can see. Matching is active-only for the same
        # reason.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_subject_nodes_import_id "
            "ON subject_nodes(exam_context, COALESCE(dimension_id, -1), import_id) "
            "WHERE import_id IS NOT NULL AND status = 'active'"
        )
