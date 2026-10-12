"""User DB migration v26 — relations get types (#14, #60).

Owner's decision, 2026-10-03, after #60's adjudication: every proposed
relation read "A leads to B", because m019's relation is one untyped arrow,
and that was judged too vague to describe most relations. So:

* per **exam**, the student owns a fixed list of relation types, seeded
  with *causes / risk factor for / complication of / treats / presents
  with / confused with*;
* each type has a **forward and a reverse label** (``causes`` /
  ``caused by``), which is how #14 decision 4's both-ends rendering
  survives; a type may be **symmetric** (``confused with``), reading the
  same from both ends with no direction;
* existing relations **stay untyped** until the student edits them --
  nothing is guessed, so there is deliberately no backfill;
* a type in use is **renamed or retired, never deleted**.

The reason sentence stays mandatory (#14 decision 2). This is type *and*
sentence.

``relation_types``
------------------
Keyed by ``exam_contexts.id``, like ``exam_dimensions.exam_id``. The labels
live here and nowhere else, so a rename reaches every relation at once.

- ``status`` is ``'active'`` or ``'retired'``. No CHECK, matching
  ``subject_nodes.status`` and m024's ``exam_dimensions.status``: widening
  a CHECK means rebuilding the table.
- A symmetric type must have ``reverse_label = label`` -- a CHECK, because
  a symmetric type with two labels would render differently from its two
  ends, which is exactly what symmetric means it must not do.
- Active labels are unique per exam, case-insensitively, by a **partial**
  index, so a retired type does not hold its label hostage.

``subject_relations`` is rebuilt
--------------------------------
m019 declared ``UNIQUE(from_subject_id, to_subject_id)``. It forbids *A
causes B* and *A confused with B* from coexisting, which the seed list
makes ordinary, and SQLite cannot drop a table constraint in place. So:
create-copy-drop-rename, the shape m019 itself used to widen a CHECK on
``subject_delete_batch_items``. Safe with foreign keys on: nothing
references ``subject_relations`` (#37 addresses relations by id through the
journal's JSON payload, not by a foreign key), and ids are copied
explicitly so that payload stays valid.

Every column is copied, ``hidden_batch_id`` above all -- losing it would
resurrect hidden relations and break #37's restore without an error.

The new uniqueness is two rules:

- ``UNIQUE(from_subject_id, to_subject_id, relation_type_id)`` for typed
  rows.
- A **partial unique index on (from, to) WHERE relation_type_id IS NULL**.
  SQLite treats NULLs as distinct in a UNIQUE constraint, so without it
  untyped rows would no longer be constrained at all. Keeping m019's rule
  for them was chosen because every existing row is untyped and was
  written under that rule: the migration should not make a duplicate
  legal that was illegal the day before, and two untyped rows for one pair
  would render as two identical "Leads to" lines.

Symmetric relations are stored once, in canonical order
--------------------------------------------------------
``A confused with B`` and ``B confused with A`` are one relation, stored
as ``(min id, max id)``. The domain layer canonicalises; two triggers
refuse a non-canonical symmetric row on INSERT and UPDATE, so the UNIQUE
constraint alone is enough to stop the pair being stored twice even from
a path that forgot. This does not contradict #14 decision 7 (cycles are
allowed): asymmetric types keep both directions as two legal rows.

Idempotent: the rebuild is skipped once ``relation_type_id`` exists, and
seeding only touches an exam that has no types at all.
"""
from __future__ import annotations

import sqlite3

from .._helpers import get_column_names, get_table_names

VERSION = 26
NAME = "relation_types"


#: The owner's seed list, in display order: (label, reverse label, symmetric).
#: ``RelationsMixin`` seeds new exams from this same tuple -- one definition.
SEED_RELATION_TYPES = (
    ('causes', 'caused by', False),
    ('risk factor for', 'has risk factor', False),
    ('complication of', 'has complication', False),
    ('treats', 'treated by', False),
    ('presents with', 'presenting feature of', False),
    ('confused with', 'confused with', True),
)


def seed_relation_types(conn: sqlite3.Connection, exam_id: int) -> int:
    """Seed one exam's list, if it has never had one. Returns rows written.

    "Never had one" counts retired rows: a student who retired every type
    has a list -- an empty active one -- and must not have it reseeded.
    """
    if conn.execute(
        # includes-retired: any row at all means the exam has a list.
        "SELECT 1 FROM relation_types WHERE exam_id = ? LIMIT 1", (exam_id,)
    ).fetchone():
        return 0
    for order, (label, reverse, symmetric) in enumerate(SEED_RELATION_TYPES, start=1):
        conn.execute(
            "INSERT INTO relation_types "
            "(exam_id, label, reverse_label, is_symmetric, sort_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (exam_id, label, reverse, 1 if symmetric else 0, order),
        )
    return len(SEED_RELATION_TYPES)


_RELATIONS_DDL = """
    CREATE TABLE {table} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        from_subject_id INTEGER NOT NULL
            REFERENCES subject_nodes(id) ON DELETE CASCADE,
        to_subject_id INTEGER NOT NULL
            REFERENCES subject_nodes(id) ON DELETE CASCADE,

        -- #14 decision 2, unchanged by typing: the student's sentence.
        reason TEXT NOT NULL CHECK (
            length(trim(reason, char(32) || char(9) || char(10) || char(13))) > 0
        ),

        strength INTEGER NOT NULL DEFAULT 2
            CHECK (strength IN (-1, 1, 2, 3)),

        origin TEXT NOT NULL DEFAULT 'user'
            CHECK (origin IN ('user', 'extracted')),

        source_entry_id INTEGER
            REFERENCES question_entries(id) ON DELETE SET NULL,

        hidden_batch_id TEXT,

        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TIMESTAMP,

        -- m026. NULL is "untyped", the state every pre-m026 relation keeps
        -- until the student edits it. SET NULL only matters if an exam
        -- itself is deleted; a type is otherwise never deleted.
        relation_type_id INTEGER
            REFERENCES relation_types(id) ON DELETE SET NULL,

        CHECK (from_subject_id <> to_subject_id),
        UNIQUE (from_subject_id, to_subject_id, relation_type_id)
    )
"""

_COPIED_COLUMNS = (
    "id, from_subject_id, to_subject_id, reason, strength, origin, "
    "source_entry_id, hidden_batch_id, created_at, confirmed_at"
)


def _create_relation_types(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS relation_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL
                REFERENCES exam_contexts(id) ON DELETE CASCADE,
            label TEXT NOT NULL CHECK (length(trim(label)) > 0),
            reverse_label TEXT NOT NULL CHECK (length(trim(reverse_label)) > 0),
            is_symmetric INTEGER NOT NULL DEFAULT 0 CHECK (is_symmetric IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'active',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (is_symmetric = 0 OR reverse_label = label)
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_relation_types_active_label "
        "ON relation_types(exam_id, label COLLATE NOCASE) WHERE status = 'active'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_relation_types_exam "
        "ON relation_types(exam_id, status, sort_order)"
    )


def _rebuild_subject_relations(conn: sqlite3.Connection) -> None:
    if 'subject_relations' not in get_table_names(conn):
        return
    if 'relation_type_id' in get_column_names(conn, 'subject_relations'):
        return

    conn.execute("DROP TABLE IF EXISTS subject_relations_m026")
    conn.execute(_RELATIONS_DDL.format(table="subject_relations_m026"))
    conn.execute(
        f"INSERT INTO subject_relations_m026 ({_COPIED_COLUMNS}) "
        f"SELECT {_COPIED_COLUMNS} FROM subject_relations"
    )
    # AUTOINCREMENT keeps its high-water mark in sqlite_sequence. Carry it
    # over so a deleted relation's id is never reissued -- the #37 journal
    # names relations by id.
    seq = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'subject_relations'"
    ).fetchone()
    conn.execute("DROP TABLE subject_relations")
    conn.execute("ALTER TABLE subject_relations_m026 RENAME TO subject_relations")
    if seq is not None:
        conn.execute(
            "UPDATE sqlite_sequence SET seq = max(seq, ?) WHERE name = 'subject_relations'",
            (seq[0],),
        )


def _create_relation_indexes(conn: sqlite3.Connection) -> None:
    # m019's four, which the drop took with the old table.
    for name, column in (
        ('idx_subject_relations_from', 'from_subject_id'),
        ('idx_subject_relations_to', 'to_subject_id'),
        ('idx_subject_relations_hidden', 'hidden_batch_id'),
        ('idx_subject_relations_source_entry', 'source_entry_id'),
    ):
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON subject_relations({column})")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subject_relations_type "
        "ON subject_relations(relation_type_id)"
    )
    # m019's one-per-ordered-pair rule, kept for untyped rows -- see the
    # module docstring for why it is not simply dropped.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_subject_relations_untyped_pair "
        "ON subject_relations(from_subject_id, to_subject_id) "
        "WHERE relation_type_id IS NULL"
    )


def _create_symmetric_triggers(conn: sqlite3.Connection) -> None:
    condition = (
        "NEW.relation_type_id IS NOT NULL "
        "AND NEW.from_subject_id > NEW.to_subject_id "
        # includes-retired: a retired symmetric type is still symmetric.
        "AND (SELECT is_symmetric FROM relation_types "
        "     WHERE id = NEW.relation_type_id) = 1"
    )
    message = ("a symmetric relation is stored once, in canonical order "
               "(from_subject_id < to_subject_id)")
    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_subject_relations_symmetric_insert
        BEFORE INSERT ON subject_relations
        WHEN {condition}
        BEGIN SELECT RAISE(ABORT, '{message}'); END
        """
    )
    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_subject_relations_symmetric_update
        BEFORE UPDATE OF from_subject_id, to_subject_id, relation_type_id
        ON subject_relations
        WHEN {condition}
        BEGIN SELECT RAISE(ABORT, '{message}'); END
        """
    )


def upgrade(conn: sqlite3.Connection) -> None:
    _create_relation_types(conn)
    _rebuild_subject_relations(conn)
    if 'subject_relations' in get_table_names(conn):
        _create_relation_indexes(conn)
        _create_symmetric_triggers(conn)
    if 'exam_contexts' in get_table_names(conn):
        for (exam_id,) in conn.execute("SELECT id FROM exam_contexts").fetchall():
            seed_relation_types(conn, exam_id)
