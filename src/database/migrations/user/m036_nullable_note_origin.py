"""User DB migration v36 -- a note's origin may be NULL (#848 Wave 0).

Reserved for #848 on its comment #11566 before it was written; the owner's
decision 1 (2026-11-04) is *nullable origin on ``entry_notes``, no separate
table*.

Until now ``entry_notes.question_entry_id`` was ``NOT NULL REFERENCES
question_entries(id) ON DELETE CASCADE`` (``user_db_schema_v1_phase9_notes.sql``),
so a note could only ever be born on an entry and died with it, off every
other entry the m009 junction had attached it to. This rebuilds the table with

    question_entry_id INTEGER REFERENCES question_entries(id) ON DELETE SET NULL

and changes nothing else: every other column, the ``json_valid`` CHECK on
``linked_subject_ids``, every row and every id are kept.

``ON DELETE SET NULL`` rather than a bare nullable ``CASCADE`` is deliberate
(operator's Wave 0 notes on #848): decision 2's rule -- delete the note when the
deleted entry was its only attachment, free it otherwise -- is application code
in every entry-delete path (``NotesMixin.release_notes_from_entries``). A path
the code misses then leaves a stray free note the student can see and delete;
the other clause would make a missed path destroy a shared note silently, which
is the loss this issue exists to end.

Why the rebuild is not m019's create-copy-drop-rename
-----------------------------------------------------
``entry_note_attachments.note_id REFERENCES entry_notes(id) ON DELETE CASCADE``
(m009). Foreign keys are ON, and this migration runs inside one transaction
(see the next section), so ``PRAGMA foreign_keys`` cannot be switched off here
-- the pragma is a no-op inside a transaction. With foreign keys on, ``DROP
TABLE entry_notes`` performs an implicit ``DELETE FROM entry_notes`` first, and
that cascades through the junction and empties it: every *attached elsewhere*
relationship in the profile gone, with no error. And ``ALTER TABLE ... RENAME``
rewrites the junction's ``REFERENCES`` to the renamed name, so renaming the old
table aside is no escape either. m019's rebuild was safe only because nothing
referenced its table, and its docstring says so.

So the child is taken out of the way first:

1. copy ``entry_note_attachments``' rows to a holding table;
2. drop the junction (its index ``idx_ena_note`` goes with it);
3. rebuild ``entry_notes``: create new, copy every row by column, drop old,
   rename new into place, carry the AUTOINCREMENT sequence so a deleted note's
   id is never reused;
4. recreate ``entry_note_attachments`` with exactly m009's definition and
   ``idx_ena_note``;
5. copy the rows back and drop the holding table.

No ``executescript`` (it commits implicitly and would end the transaction;
CLAUDE.md). ``PRAGMA foreign_key_check`` is empty afterwards, asserted by
``tests/database/migrations/test_user_036_nullable_note_origin.py``.

The transaction is opened HERE, not by the runner
-------------------------------------------------
``MigrationRunner._apply_one`` issues no ``BEGIN``; it only commits or rolls
back. Under the connection's legacy transaction control Python opens the
implicit transaction at the first INSERT/UPDATE/DELETE, and **every DDL
statement before that autocommits on its own**. For this rebuild that would
have meant the holding-table copy and ``DROP TABLE entry_note_attachments``
were each committed individually, and the runner's ``rollback()`` reached back
only as far as the ``INSERT INTO entry_notes_m036``. Measured (PR #861 review):
``in_transaction`` was False for every statement up to and including that
INSERT. A failure anywhere after step 2 -- disk full, ``database is locked``, a
``FOREIGN KEY constraint failed`` from a dangling origin in an installed
profile, the process killed -- then left the junction gone and committed, the
holding table as the only copy of its rows, and v36 unstamped; and the retry's
first statement dropped the holding table, so every attachment was lost with no
error anywhere. m019 and m006 never met this because their one destructive
``DROP`` comes after their ``INSERT``, inside the implicit transaction; this is
the first rebuild whose destructive step precedes all DML.

So ``upgrade()`` executes ``BEGIN`` itself when no transaction is open, and the
runner's existing ``commit()`` / ``rollback()`` then cover the whole rebuild:
a failed m036 leaves the database exactly as it was. The ``BEGIN`` is deliberately
local to this module rather than in ``_apply_one``: m001 (``run_schema_script``),
m003, m032, m033, m034 and m035 all call ``executescript``, which would commit a
runner-level ``BEGIN`` part-way through them.

Idempotent, and a leftover is the source of truth
-------------------------------------------------
A database whose ``question_entry_id`` is already nullable is left alone. If the
holding table exists while the junction does not -- the state a pre-``BEGIN``
build of this migration could leave behind -- the holding table is treated as
the junction's rows and the junction is rebuilt from it; it is never dropped
before its rows are back where they belong.

A fresh database takes this path too: m001 creates ``entry_notes`` from the
schema file with the NOT NULL, m009 adds the junction, and this rebuilds, so
fresh and migrated databases share one structure (#593's fingerprint).

A row the old schema could not have written is repaired, not refused
--------------------------------------------------------------------
WIMI's connections enforce foreign keys and the old clause cascaded, so WIMI
itself never wrote a note whose origin names an entry that is gone. A database
another writer touched with foreign keys off can carry one, and SQLite checks
a foreign key on write only, so the old schema tolerated it silently. The copy
into the rebuilt table enforces its ``REFERENCES``, and a dangling origin
would fail it: ``MigrationFailedError`` on every launch, a profile that never
opens again. So the origin is copied only when its entry exists (a ``CASE``
with no ``ELSE`` is NULL) -- under this wave's own rule a note whose entry is
gone is a free note -- and a junction row naming a vanished entry or note is
not carried over, since it attached nothing to nothing. Operator's edit on PR
#861; ``test_a_dangling_origin_becomes_a_free_note_instead_of_refusing_the_profile``.
"""
from __future__ import annotations

import sqlite3

from .._helpers import get_table_names

VERSION = 36
NAME = "nullable_note_origin"

_HOLDING_TABLE = "entry_note_attachments_m036"


# The new entry_notes. Everything but the first REFERENCES clause is the
# phase 9 schema file, column for column.
_ENTRY_NOTES_DDL = """
    CREATE TABLE {table} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_entry_id INTEGER REFERENCES question_entries(id) ON DELETE SET NULL,
        content_html TEXT,
        content_json TEXT,
        sort_order INTEGER DEFAULT 0,
        linked_subject_ids TEXT CHECK (json_valid(linked_subject_ids) OR linked_subject_ids IS NULL),
        is_migrated BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

_ENTRY_NOTES_COLUMNS = (
    "id, question_entry_id, content_html, content_json, sort_order, "
    "linked_subject_ids, is_migrated, created_at, updated_at"
)

# What is SELECTed into the new table: the same columns, except that an origin
# naming an entry that no longer exists becomes NULL rather than failing the
# new REFERENCES (module docstring, last section).
_ENTRY_NOTES_COPY = (
    "id, "
    "CASE WHEN question_entry_id IN (SELECT id FROM question_entries) "
    "THEN question_entry_id END, "
    "content_html, content_json, sort_order, "
    "linked_subject_ids, is_migrated, created_at, updated_at"
)

# m009's definition, verbatim, so the recreated junction is the one every
# read path already knows.
_JUNCTION_DDL = """
    CREATE TABLE entry_note_attachments (
        question_entry_id INTEGER NOT NULL
            REFERENCES question_entries(id) ON DELETE CASCADE,
        note_id INTEGER NOT NULL
            REFERENCES entry_notes(id) ON DELETE CASCADE,
        sort_order INTEGER NOT NULL DEFAULT 0,
        attached_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (question_entry_id, note_id)
    )
"""

_JUNCTION_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_ena_note ON entry_note_attachments(note_id)"
)


def _origin_is_nullable(conn: sqlite3.Connection) -> bool:
    for row in conn.execute("PRAGMA table_info(entry_notes)"):
        if row[1] == "question_entry_id":
            return row[3] == 0
    return False


def _entry_notes_index_ddl(conn: sqlite3.Connection) -> list[str]:
    """The CREATE INDEX text of every named index on entry_notes.

    The schema file declares none, but a profile may carry one from a build
    this registry never saw, and a rebuild must not silently drop it.
    """
    rows = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'index' AND tbl_name = 'entry_notes' AND sql IS NOT NULL"
    ).fetchall()
    return [r[0] for r in rows]


def upgrade(conn: sqlite3.Connection) -> None:
    tables = get_table_names(conn)
    if "entry_notes" not in tables or "question_entries" not in tables:
        # Isolated-migration tests run partial registries; nothing to shape.
        return
    if _origin_is_nullable(conn):
        return

    # The whole rebuild in one transaction, or none of it. The runner does not
    # BEGIN, and DDL autocommits until something does (module docstring).
    if not conn.in_transaction:
        conn.execute("BEGIN")

    junction_exists = "entry_note_attachments" in tables
    holding_exists = _HOLDING_TABLE in tables

    # 1. The child out of the way: hold its rows, then drop it. The holding
    #    table has no constraints of its own (CREATE TABLE ... AS SELECT), so
    #    nothing references entry_notes while it is rebuilt.
    if junction_exists:
        conn.execute(f"DROP TABLE IF EXISTS {_HOLDING_TABLE}")
        conn.execute(
            f"CREATE TABLE {_HOLDING_TABLE} AS "
            "SELECT question_entry_id, note_id, sort_order, attached_at "
            "FROM entry_note_attachments"
        )
        conn.execute("DROP TABLE entry_note_attachments")
        restore_junction = True
    elif holding_exists:
        # A previous attempt got as far as dropping the junction and no
        # further. Its rows are in the holding table and nowhere else; the
        # junction is rebuilt from them below.
        restore_junction = True
    else:
        # A partial registry without m009: no junction to carry.
        restore_junction = False

    # 2. The rebuild. Indexes and the AUTOINCREMENT sequence are read before
    #    the drop takes them.
    index_ddl = _entry_notes_index_ddl(conn)
    seq_row = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'entry_notes'"
    ).fetchone()

    conn.execute("DROP TABLE IF EXISTS entry_notes_m036")
    conn.execute(_ENTRY_NOTES_DDL.format(table="entry_notes_m036"))
    conn.execute(
        f"INSERT INTO entry_notes_m036 ({_ENTRY_NOTES_COLUMNS}) "
        f"SELECT {_ENTRY_NOTES_COPY} FROM entry_notes"
    )
    conn.execute("DROP TABLE entry_notes")
    conn.execute("ALTER TABLE entry_notes_m036 RENAME TO entry_notes")

    for ddl in index_ddl:
        conn.execute(ddl)

    if seq_row is not None:
        # Copying rows with explicit ids leaves seq at MAX(id); the old table's
        # sequence may be higher because notes were deleted, and reusing a
        # deleted note's id would hand its graph node to a new note.
        # sqlite_sequence has no unique key, so no upsert: the copy above
        # created the row whenever a note exists, and an empty table did not.
        if conn.execute(
            "SELECT 1 FROM sqlite_sequence WHERE name = 'entry_notes'"
        ).fetchone():
            conn.execute(
                "UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'entry_notes'",
                (seq_row[0],),
            )
        else:
            conn.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES ('entry_notes', ?)",
                (seq_row[0],),
            )

    # 3. The child back, exactly as m009 made it, with its rows.
    if restore_junction:
        conn.execute(_JUNCTION_DDL)
        conn.execute(_JUNCTION_INDEX)
        conn.execute(
            "INSERT INTO entry_note_attachments "
            "(question_entry_id, note_id, sort_order, attached_at) "
            "SELECT question_entry_id, note_id, sort_order, attached_at "
            f"FROM {_HOLDING_TABLE} "
            "WHERE question_entry_id IN (SELECT id FROM question_entries) "
            "AND note_id IN (SELECT id FROM entry_notes)"
        )
        conn.execute(f"DROP TABLE {_HOLDING_TABLE}")
