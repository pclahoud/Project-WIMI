"""User DB migration v9 — entry_note_attachments junction table (many-to-many notes).

Version 8 was claimed by ``m008_assessments`` on the
``feat/psychometric-assessment`` branch (commit ca63e69) and may already
be applied to dev DBs that touched that branch. This file lives at v9
to avoid colliding with that registration.


Foundation of the Wave R3 "Reuse from other entries" UX: a single
``entry_notes`` row may now be attached to multiple ``question_entries``.

Mirrors the ``entry_media_mapping`` precedent introduced by
``m001_baseline._ensure_media_decoupling`` (see ``m001_baseline.py``
around line 180). Same shape, same semantics — junction table with
``ON DELETE CASCADE`` against both parents so a deleted entry simply
drops its attachment row(s), and a deleted note removes every entry's
view of it.

Three operations, all idempotent:

1. ``CREATE TABLE IF NOT EXISTS entry_note_attachments`` with composite
   primary key ``(question_entry_id, note_id)``. The composite PK both
   enforces "the same note cannot be attached to the same entry twice"
   and gives us a covering index for the entry-side read path.
2. Secondary index on ``note_id`` for the reverse lookup (the
   ``attachment_count`` aggregate and the "where else is this note
   used?" hovercard).
3. Backfill from the legacy 1:1 ``entry_notes.question_entry_id`` column
   via ``INSERT OR IGNORE`` so re-running the migration on an
   already-backfilled DB is a no-op.

The ``entry_notes.question_entry_id`` column is intentionally LEFT in
place with its existing ``NOT NULL ... ON DELETE CASCADE`` constraint
(originally from ``user_db_schema_v1_phase9_notes.sql:6``). Two reasons
for not relaxing it to ``ON DELETE SET NULL`` via a table rebuild here:

- **Risk:** SQLite has no in-place ALTER for foreign keys, so relaxing
  would require copying every note row into a replacement table and
  swapping. The existing migrations that DO take this path (m006) are
  forced into it because they need a wider CHECK constraint. We do not
  need it here.
- **Semantics:** The "delete the entry that originally produced this
  note → delete the note" behaviour is *acceptable* and arguably the
  least surprising default for the existing UX (the originating entry
  remains the note's canonical owner). The Wave R3 "attach to other
  entries" flow only ever writes to ``entry_note_attachments``; the
  per-attachment row carries its own ``ON DELETE CASCADE`` against the
  *attaching* entry, so deleting entry B never deletes a note whose
  originating ``question_entry_id`` was entry A. The cascade only fires
  when the originator itself is deleted, which matches the current
  behaviour byte-for-byte. A future migration can revisit this if a
  product reason emerges (e.g. "let the user reassign ownership"), but
  carrying the table-rebuild risk today buys nothing.

After this migration the read path (``_get_entry_notes`` in
``_base.py``) switches to a JOIN through ``entry_note_attachments``, so
a single note row backfilled from its originating entry continues to
show up on that entry transparently — and also shows up on any other
entry it gets attached to.
"""
from __future__ import annotations

import sqlite3

from .._helpers import get_table_names

VERSION = 9
NAME = "entry_note_attachments"


def upgrade(conn: sqlite3.Connection) -> None:
    # Defensive: in the normal migration order, m001 always creates
    # entry_notes before m008 runs. Guard so isolated-migration tests
    # don't trip over a missing table.
    tables = get_table_names(conn)
    if "entry_notes" not in tables or "question_entries" not in tables:
        return

    # 1. Junction table. Composite PK doubles as the entry-side covering
    #    index — no separate index needed for ``WHERE question_entry_id = ?``.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entry_note_attachments (
            question_entry_id INTEGER NOT NULL
                REFERENCES question_entries(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL
                REFERENCES entry_notes(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            attached_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (question_entry_id, note_id)
        )
        """
    )

    # 2. Reverse-direction index for ``WHERE note_id = ?`` lookups
    #    (used by attachment_count and the "where else is this note
    #    used?" hovercard).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ena_note "
        "ON entry_note_attachments(note_id)"
    )

    # 3. Backfill from the legacy 1:1 column. ``INSERT OR IGNORE`` makes
    #    this safe to re-run — the composite PK rejects duplicates
    #    silently. We preserve sort_order so the UI ordering is stable
    #    across the migration.
    conn.execute(
        """
        INSERT OR IGNORE INTO entry_note_attachments
            (question_entry_id, note_id, sort_order)
        SELECT question_entry_id, id, COALESCE(sort_order, 0)
        FROM entry_notes
        WHERE question_entry_id IS NOT NULL
        """
    )
