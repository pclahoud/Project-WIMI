"""User DB migration v19 — student-authored semantic relations.

Issue #14. A subject can be related to another subject in ways the
containment hierarchy cannot express: *hypertension leads to
hypertensive nephrosclerosis*. The student writes that relation down,
in their own words, and the deep dive lists it from both ends.

Two things land here.

``subject_relations``
    One row per relation, **directional**: ``from_subject_id`` →
    ``to_subject_id`` (decision 4 — stored once, rendered as "leads to"
    on one subject and "caused by" on the other).

    - ``reason`` is ``NOT NULL`` with a non-blank ``CHECK``. Decision 2:
      no relation exists without the student's sentence. It is both the
      pedagogical payload (constructing a concept map scores g = 0.72 vs
      g = 0.43 for studying one) and the anti-rubber-stamp mechanism, so
      the constraint is in the schema rather than only in the UI — a
      bridge slot, an import, or a future extractor must not be able to
      write an unexplained edge.
    - ``strength`` is graded and carries a **sentinel for "checked —
      NOT related"** (decision 8). ``-1`` is refuted; ``1``/``2``/``3``
      are possible/likely/certain. The refuted value is itself
      metacognitive content, and it is what stops #60 re-proposing the
      same pair forever.
    - ``origin`` is ``'user'`` today and ``'extracted'`` for #60.
      ``confirmed_at`` is set at creation for a user-authored relation
      (the student confirmed it by writing the reason) and stays NULL
      for an extracted one until a human says yes.
    - ``source_entry_id`` is the mistake that prompted the relation —
      the metacognitive trail. ``ON DELETE SET NULL``: losing the entry
      must not lose the relation.
    - ``hidden_batch_id`` is decision 9's stamp; see below.

    **No ``dimension_id``** (decision 6). A relation is between two
    subject nodes; whichever dimensions they sit in is not the
    relation's business, and for a multi-dimensional exam a topic in one
    dimension relating to a technique in another is precisely what
    containment cannot express. The panel labels the other subject's
    dimension when the two differ; the data stays dimension-free.

    **No cycle validator** (decision 7). ``UNIQUE(from, to)`` permits
    both ``A→B`` and ``B→A`` because *A causes B* and *B exacerbates A*
    can both be true. Math Academy's scarring cycle lesson was about
    prerequisites, where a cycle is incoherent; it does not transfer to
    semantic relations. The one thing that *is* rejected is a self-loop
    (``from = to``), which is not a cycle between two subjects but a row
    with no content.

    This is deliberately **not** new ``mapping_type`` values on
    ``subject_edges``. ``subject_edges`` is a navigational DAG carrying
    weight semantics; EMMeT conflated navigational ``skos:broader`` with
    logical subsumption and produced "Abortion Recovery is a kind of
    Abortion", 25% of its inferred subsumptions (355,880) never
    validatable. Relations get their own table.

``subject_delete_batch_items.item_type`` gains ``'relation_hidden'``
    Decision 9: archiving a subject hides its relations and journals
    them into the delete batch, so #37's restore brings them back with
    the subject. m018 constrained ``item_type`` to three values, and
    SQLite cannot alter a ``CHECK``, so the table is rebuilt with the
    fourth. The rebuild is safe with foreign keys on because nothing
    references ``subject_delete_batch_items`` — it is the child end of
    its only relationship.

    A ``relation_hidden`` item records ``subject_node_id`` =
    ``from_subject_id`` and ``parent_id`` = ``to_subject_id`` (the
    generic columns, as m018 already does per item type), with the
    relation id and its payload in ``payload`` so restore does not have
    to re-derive anything.

Idempotent: ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT
EXISTS``, and the batch-items rebuild is skipped once the stored DDL
already mentions ``relation_hidden``.

Versions 8 and 11-14 are absent from the registry by design — see
m015's docstring — so this follows m018 without a gap of its own.
"""
from __future__ import annotations

import sqlite3

from .._helpers import get_table_names

VERSION = 19
NAME = "subject_relations"


# The four journal item types after this migration. m018 shipped the
# first three; ``relation_hidden`` is decision 9's addition.
_BATCH_ITEM_TYPES = (
    'node_archived',
    'edge_removed',
    'primary_parent_cleared',
    'relation_hidden',
)


def _batch_items_ddl(table: str) -> str:
    """m018's ``subject_delete_batch_items`` DDL, plus the new item type."""
    allowed = ", ".join(f"'{t}'" for t in _BATCH_ITEM_TYPES)
    return f"""
        CREATE TABLE {table} (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL
                REFERENCES subject_delete_batches(id) ON DELETE CASCADE,
            item_type TEXT NOT NULL CHECK(item_type IN ({allowed})),

            -- node_archived: the archived node.
            -- edge_removed:  the edge's child.
            -- primary_parent_cleared: the mapping's subject.
            -- relation_hidden: the relation's from_subject_id.
            subject_node_id INTEGER,
            -- edge_removed: the edge's parent.
            -- primary_parent_cleared: the value that was nulled.
            -- relation_hidden: the relation's to_subject_id.
            parent_id INTEGER,
            -- primary_parent_cleared: entry_subject_mappings.id.
            entry_subject_mapping_id INTEGER,

            -- JSON snapshot of whatever else restore needs (edge
            -- weights, the status the node held before archiving, the
            -- relation id and its reason/strength).
            payload TEXT NOT NULL DEFAULT '{{}}',

            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """


def _allows_relation_hidden(conn: sqlite3.Connection) -> bool:
    """True when the stored DDL already permits ``'relation_hidden'``."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='subject_delete_batch_items'"
    ).fetchone()
    if row is None:
        return False
    sql = row[0] or ''
    return 'relation_hidden' in sql


def _extend_batch_item_types(conn: sqlite3.Connection) -> None:
    """Rebuild ``subject_delete_batch_items`` with the fourth item type.

    SQLite has no ``ALTER TABLE ... DROP CONSTRAINT``, so the only way
    to widen a ``CHECK`` is create-copy-drop-rename. Safe with foreign
    keys enabled: this table is referenced by nothing, so the rename
    has no dependent DDL to rewrite, and its own FK to
    ``subject_delete_batches`` is satisfied by rows that already exist.
    """
    if 'subject_delete_batch_items' not in get_table_names(conn):
        return
    if _allows_relation_hidden(conn):
        return

    conn.execute("DROP TABLE IF EXISTS subject_delete_batch_items_m019")
    conn.execute(_batch_items_ddl("subject_delete_batch_items_m019"))
    conn.execute(
        """
        INSERT INTO subject_delete_batch_items_m019
            (id, batch_id, item_type, subject_node_id, parent_id,
             entry_subject_mapping_id, payload, created_at)
        SELECT id, batch_id, item_type, subject_node_id, parent_id,
               entry_subject_mapping_id, payload, created_at
        FROM subject_delete_batch_items
        """
    )
    conn.execute("DROP TABLE subject_delete_batch_items")
    conn.execute(
        "ALTER TABLE subject_delete_batch_items_m019 "
        "RENAME TO subject_delete_batch_items"
    )
    # The rename drops the old indexes with the old table; recreate
    # m018's two so the journal stays queryable by batch and by node.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sdb_items_batch "
        "ON subject_delete_batch_items(batch_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sdb_items_node "
        "ON subject_delete_batch_items(subject_node_id)"
    )


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subject_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            from_subject_id INTEGER NOT NULL
                REFERENCES subject_nodes(id) ON DELETE CASCADE,
            to_subject_id INTEGER NOT NULL
                REFERENCES subject_nodes(id) ON DELETE CASCADE,

            -- Decision 2. The student's sentence, and the only reason
            -- this feature is metacognitive rather than a bookmark list.
            -- One-argument trim() strips spaces only, so a reason of
            -- one tab would satisfy it; the explicit character set
            -- covers space, tab, newline and carriage return.
            reason TEXT NOT NULL CHECK (
                length(trim(reason, char(32) || char(9) || char(10) || char(13))) > 0
            ),

            -- Decision 8. -1 is the "checked - NOT related" sentinel;
            -- 1/2/3 are possible/likely/certain.
            strength INTEGER NOT NULL DEFAULT 2
                CHECK (strength IN (-1, 1, 2, 3)),

            -- 'user' today; 'extracted' is #60's local-model proposal.
            origin TEXT NOT NULL DEFAULT 'user'
                CHECK (origin IN ('user', 'extracted')),

            -- The mistake that prompted the relation. Losing the entry
            -- must not lose the relation.
            source_entry_id INTEGER
                REFERENCES question_entries(id) ON DELETE SET NULL,

            -- Decision 9. Set to the delete batch that hid this
            -- relation; NULL means visible. Deliberately not a foreign
            -- key, for the same reason as subject_nodes.deleted_batch_id
            -- in m018: the purge path (#38) must be free to drop a batch
            -- without being blocked by, or cascading into, what it names.
            hidden_batch_id TEXT,

            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            -- Set at creation for origin='user' (writing the reason is
            -- the confirmation); NULL for an unconfirmed extraction.
            confirmed_at TIMESTAMP,

            -- A self-loop is not a cycle between two subjects, it is a
            -- row with no content. Cycles proper (A->B and B->A) are
            -- explicitly allowed - decision 7.
            CHECK (from_subject_id <> to_subject_id),
            UNIQUE (from_subject_id, to_subject_id)
        )
        """
    )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subject_relations_from "
        "ON subject_relations(from_subject_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subject_relations_to "
        "ON subject_relations(to_subject_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subject_relations_hidden "
        "ON subject_relations(hidden_batch_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subject_relations_source_entry "
        "ON subject_relations(source_entry_id)"
    )

    _extend_batch_item_types(conn)
