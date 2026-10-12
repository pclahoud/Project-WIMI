"""User DB migration v27 — a rejected proposal is remembered, and how (#60).

#60 proposes relations by parsing the student's own explanation, and its
acceptance requires that **a rejected proposal is not re-proposed for the same
entry**. This table is where a rejection goes.

Why not #14 decision 8's ``strength = -1``
------------------------------------------
That decision proposed a sentinel on ``subject_relations`` meaning "checked:
NOT related". It is recorded in CLAUDE.md as the wrong mechanism for #60, and
the measurement says why: of 45 rejections in #60's adjudication, **25 meant
"you misread my sentence"**, not "these two are unrelated".

The sentinel cannot express that difference, and the difference is not a
nicety — **the two kinds have different scopes**:

``misread``
    The extractor misread *this passage*. It is a statement about one piece of
    text, and the same pair may extract perfectly well from a different
    explanation tomorrow. Suppressing it anywhere else would throw away a true
    relation because one sentence was parsed badly.

``not_related``
    A claim about the two subjects themselves, true regardless of what any
    explanation says. Suppressing it only for one entry would re-ask a question
    the student has already answered, every time they write about either
    subject.

So a sentinel would have globally suppressed **25 of those 45 pairs** on the
strength of one badly-parsed sentence. That is the whole argument for a table,
and it is why ``kind`` is NOT NULL with no default: a rejection whose kind
nobody recorded cannot be scoped, and guessing is how the sentinel behaved.

The CHECK is the scope rule, in the schema
------------------------------------------
``CHECK (kind <> 'misread' OR source_entry_id IS NOT NULL)``

A *misread* is about a specific text, so a misread row with no entry is
meaningless — it could never be matched by the suppression query and would sit
there suppressing nothing, silently. ``not_related`` keeps ``source_entry_id``
when it has one, for provenance, but the suppression query ignores it.

What is deliberately NOT a kind
-------------------------------
**"Right pair, wrong type" is not a rejection.** The student should correct the
type and accept, and the proposal UI should let them. Modelling it here would
push people to reject something they actually wanted, and would then suppress
it — the sentinel's failure mode wearing a third hat.

Symmetric types canonicalise, exactly as m026's relations do
------------------------------------------------------------
m026 stores a symmetric relation once as ``(min id, max id)`` and enforces it
with triggers. Rejections must agree: without canonicalisation, rejecting
*A confused with B* leaves *B confused with A* live, and the student is asked
again in the other direction. The same two triggers are therefore repeated
here against the same predicate.

``ON DELETE`` and soft deletes
------------------------------
The subject columns carry no cascade on purpose. Subject deletion is **soft**
(#15) — ``delete_subject_subtree`` archives rows and the FK never fires — so a
cascade here would be dead code implying a behaviour that does not exist. A
restored subject keeps its rejections, which is correct: the student's
judgement about it did not stop being true while it was archived.

``relation_type_id`` and ``source_entry_id`` do cascade, because a retired type
is *retired* rather than deleted (m026) and an entry that is genuinely gone
takes its misread rows with it.
"""
from __future__ import annotations

import sqlite3

from .._helpers import get_table_names

VERSION = 27
NAME = "relation_rejections"

_TABLE = "subject_relation_rejections"

_DDL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_subject_id INTEGER NOT NULL
        REFERENCES subject_nodes(id),
    to_subject_id INTEGER NOT NULL
        REFERENCES subject_nodes(id),
    relation_type_id INTEGER
        REFERENCES relation_types(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('misread', 'not_related')),
    source_entry_id INTEGER
        REFERENCES question_entries(id) ON DELETE CASCADE,
    passage TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (from_subject_id <> to_subject_id),
    CHECK (kind <> 'misread' OR source_entry_id IS NOT NULL)
)
"""

#: The suppression query reads (pair, type) for `not_related` and
#: (pair, type, entry) for `misread`, so both are covered by one index on the
#: pair plus the discriminators.
_INDEXES = (
    (
        "idx_relation_rejections_pair",
        f"{_TABLE}(from_subject_id, to_subject_id, relation_type_id, kind)",
    ),
    (
        "idx_relation_rejections_entry",
        f"{_TABLE}(source_entry_id)",
    ),
)

#: Same predicate as m026's triggers: the type is symmetric and the row is not
#: in canonical order. Written out rather than shared because a migration is
#: a historical record -- importing m026's string would make this module's
#: behaviour change if that one were ever edited, and an applied migration's
#: checksum must not move.
_SYMMETRIC_VIOLATION = (
    "NEW.relation_type_id IS NOT NULL "
    "AND NEW.from_subject_id > NEW.to_subject_id "
    "AND (SELECT is_symmetric FROM relation_types "
    "     WHERE id = NEW.relation_type_id) = 1"
)

#: No apostrophe, and that is not a style choice: this string is interpolated
#: into a single-quoted SQL literal inside RAISE(ABORT, '...'), so an
#: apostrophe closes it and the trigger fails to compile. m026's message avoids
#: one for the same reason.
_SYMMETRIC_MESSAGE = (
    "a rejection of a symmetric relation is stored once, in canonical order "
    "(min id, max id)"
)


def _create_triggers(conn: sqlite3.Connection) -> None:
    for when in ("INSERT", "UPDATE"):
        conn.execute(f"""
            CREATE TRIGGER IF NOT EXISTS
                trg_relation_rejections_symmetric_{when.lower()}
            BEFORE {when} ON {_TABLE}
            FOR EACH ROW WHEN {_SYMMETRIC_VIOLATION}
            BEGIN
                SELECT RAISE(ABORT, '{_SYMMETRIC_MESSAGE}');
            END
        """)


def upgrade(conn: sqlite3.Connection) -> None:
    """Create the rejection table, its indexes and its symmetry triggers.

    Depends on m026 for ``relation_types``: the FK and the triggers both name
    it. The runner applies in version order, so that is guaranteed rather than
    checked -- but the table-name guard below keeps this importable against a
    database where the relations feature never existed at all.
    """
    tables = get_table_names(conn)
    if 'subject_nodes' not in tables or 'relation_types' not in tables:
        # A database without the relations feature has nothing to reject
        # against. m019 and m026 are both unconditional on a real profile;
        # this guard exists for partial registries in the migration tests.
        return

    conn.execute(_DDL)
    for name, target in _INDEXES:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")
    _create_triggers(conn)
