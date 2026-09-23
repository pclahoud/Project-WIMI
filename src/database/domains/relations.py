"""WIMI student-authored semantic relations between subjects (issue #14).

A subject can be related to another in ways the containment hierarchy
cannot express: *hypertension leads to hypertensive nephrosclerosis*.
``subject_edges`` is a navigational DAG carrying weight semantics and
must not be overloaded with that, so relations live in their own table
(``subject_relations``, migration m019).

The decisions this module implements, so that a later reader can tell
what is load-bearing and what is incidental:

**Decision 2 — the reason is mandatory.** :meth:`create_subject_relation`
rejects a blank one before the schema's ``CHECK`` gets a chance to, so
the bridge returns a sentence a user can act on rather than an
``IntegrityError``. There is no "explain later" state.

**Decision 4 — directional, rendered from both ends.** One row, one
direction. :meth:`get_subject_relations` returns it to the ``from``
subject as ``direction='outgoing'`` and to the ``to`` subject as
``direction='incoming'``; the page labels those "leads to" and "caused
by".

**Decision 5 — subject-wide, ordered by context, never filtered.** Both
*hypertension → eclampsia* and *hypertension → RPGN* are true of
hypertension. What differs is relevance, so ``primary_parent_id``
reorders and never narrows: the returned set is identical for every
context. Hiding a true relation is the expensive error in a mistakes
log, and filtering would contradict the deep dive's deliberate
divergence from polyhierarchy §5.4 ("show everything always"). See
``_context_rank`` for the three tiers.

**Decision 6 — relations may cross dimensions.** The row carries no
``dimension_id``. The payload labels the *other* subject's dimension
when it differs from this one's, which is a rendering fact, not a
filter.

**Decision 7 — cycles are allowed.** Nothing here validates for them.
*A causes B* while *B exacerbates A* can both be true; the prerequisite-
graph lesson does not transfer to semantic relations.

**Decision 8 — graded strength with a refuted sentinel.**
:data:`STRENGTH_REFUTED` is "checked — NOT related", which is itself
metacognitive content and is what stops #60 re-proposing a pair forever.

**Decision 9 — archiving hides and journals.**
:meth:`hide_relations_for_delete_batch` is called from
``HierarchyMixin.delete_subject_subtree`` inside its transaction.

Mixin pattern: this class never imports other mixins. It is composed
into ``UserDatabase`` and reaches shared helpers through ``self.*``.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from app_logging import ErrorCategory

from ..exceptions import SubjectNodeError, ValidationError


# --------------------------------------------------------------------------
# Decision 8 — the strength grade. ``-1`` is the sentinel: the student
# checked the pair and found them *not* related. It is stored as a
# relation (with a reason) rather than as an absence, because an absence
# is indistinguishable from "never looked".
# --------------------------------------------------------------------------
STRENGTH_REFUTED = -1
STRENGTH_POSSIBLE = 1
STRENGTH_LIKELY = 2
STRENGTH_CERTAIN = 3

STRENGTH_LABELS: Dict[int, str] = {
    STRENGTH_REFUTED: 'Checked — not related',
    STRENGTH_POSSIBLE: 'Possible',
    STRENGTH_LIKELY: 'Likely',
    STRENGTH_CERTAIN: 'Certain',
}

VALID_STRENGTHS = tuple(sorted(STRENGTH_LABELS))
VALID_ORIGINS = ('user', 'extracted')

# Math Academy's heuristic: three or four incoming edges is where
# cognitive congestion starts. Soft — nothing is refused, the UI just
# says so. Advisory caps that block are how a true relation ends up
# unrecorded.
FANIN_SOFT_CAP = 4

# Context tiers for decision 5's ordering. Lower sorts first.
_CONTEXT_RANK_ACTIVE = 0      # the other subject sits under the chosen parent
_CONTEXT_RANK_NEUTRAL = 1     # it sits under none of this subject's parents
_CONTEXT_RANK_ELSEWHERE = 2   # it sits under a *different* parent of this subject

# Reasons longer than this are almost certainly a paste accident, and
# the panel has nowhere to put them. Generous on purpose.
MAX_REASON_LENGTH = 2000


class RelationsMixin:
    """Mixin for ``subject_relations``. Composed into ``UserDatabase``."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _relation_subject_row(self, subject_id: int):
        """Fetch a subject for relation work, or raise.

        Archived subjects are refused as *endpoints of a new relation*:
        decision 9 hides a relation whose subject is archived, so
        creating one there would write a row nobody can see.
        """
        row = self.fetchone(
            "SELECT id, name, exam_context, dimension_id, status "
            "FROM subject_nodes WHERE id = ?",
            (subject_id,),
        )
        if row is None:
            raise SubjectNodeError(f"Subject node {subject_id} not found")
        return row

    def _ancestor_sets(self, node_ids: Sequence[int]) -> Dict[int, set]:
        """Map each id in ``node_ids`` to ``{itself} | its active ancestors``.

        One recursive CTE for the whole batch, walking ``subject_edges``
        upward and carrying the seed along so every seed's chain stays
        attributable. Archived parents are skipped — an edge from an
        archived node is not a live context.
        """
        ids = [int(n) for n in dict.fromkeys(node_ids)]
        if not ids:
            return {}
        placeholders = ','.join('?' * len(ids))
        rows = self.fetchall(
            f"""
            WITH RECURSIVE upward(seed, node_id) AS (
                SELECT id, id FROM subject_nodes WHERE id IN ({placeholders})
                UNION
                SELECT u.seed, se.parent_id
                FROM subject_edges se
                JOIN upward u ON se.child_id = u.node_id
                JOIN subject_nodes p ON p.id = se.parent_id
                WHERE p.status = 'active'
            )
            SELECT seed, node_id FROM upward
            """,
            tuple(ids),
        )
        out: Dict[int, set] = {nid: set() for nid in ids}
        for row in rows:
            out.setdefault(row['seed'], set()).add(row['node_id'])
        return out

    def _parent_ids_of(self, subject_id: int) -> List[int]:
        """Active parent ids of ``subject_id``, primary first.

        Deliberately its own small query rather than a call into
        ``EdgesMixin.get_edges_for_child``: all that is needed here is
        the id list, and the ordering only has to be deterministic.
        """
        return [
            row['parent_id']
            for row in self.fetchall(
                """
                SELECT se.parent_id AS parent_id
                FROM subject_edges se
                JOIN subject_nodes p ON p.id = se.parent_id
                WHERE se.child_id = ? AND p.status = 'active'
                ORDER BY se.is_primary DESC, se.parent_id ASC
                """,
                (subject_id,),
            )
        ]

    @staticmethod
    def _context_rank(
        context_parent_ids: Sequence[int],
        active_parent_id: Optional[int],
    ) -> int:
        """Decision 5's ordering tier for one relation. **Never a filter.**

        ``context_parent_ids`` is the subset of *this* subject's parents
        whose subtree contains the other subject.

        - The other subject sits under the parent currently being viewed
          → :data:`_CONTEXT_RANK_ACTIVE`. Viewing hypertension under
          Pregnancy puts eclampsia first.
        - It sits under none of this subject's parents → neutral. It is
          not evidence for or against the current context.
        - It sits under a *different* parent of this subject → demoted.
          This is what makes viewing hypertension under Cardiovascular
          surface RPGN (neutral) above eclampsia (belongs to the
          Pregnancy context), which is the issue's worked example.

        With no context selected every relation is neutral, so the list
        falls back to strength and recency — and still contains
        everything.
        """
        if active_parent_id is None:
            return _CONTEXT_RANK_NEUTRAL
        if active_parent_id in context_parent_ids:
            return _CONTEXT_RANK_ACTIVE
        if not context_parent_ids:
            return _CONTEXT_RANK_NEUTRAL
        return _CONTEXT_RANK_ELSEWHERE

    def _visible_relations_for(self, subject_id: int) -> List[Dict[str, Any]]:
        """Raw visible relation rows touching ``subject_id``, either way.

        Visible means: not stamped by a delete batch (decision 9) and
        both endpoints still active. The status join is belt and braces
        — a relation should always be stamped when its subject is
        archived — but a stamp that went missing must not resurrect a
        relation into a subject the user cannot see.
        """
        rows = self.fetchall(
            """
            SELECT
                r.id                AS relation_id,
                r.from_subject_id   AS from_subject_id,
                r.to_subject_id     AS to_subject_id,
                r.reason            AS reason,
                r.strength          AS strength,
                r.origin            AS origin,
                r.source_entry_id   AS source_entry_id,
                r.created_at        AS created_at,
                r.confirmed_at      AS confirmed_at
            FROM subject_relations r
            JOIN subject_nodes sf ON sf.id = r.from_subject_id
            JOIN subject_nodes st ON st.id = r.to_subject_id
            WHERE r.hidden_batch_id IS NULL
              AND sf.status = 'active'
              AND st.status = 'active'
              AND (r.from_subject_id = ? OR r.to_subject_id = ?)
            """,
            (subject_id, subject_id),
        )
        return [dict(row) for row in rows]

    def _incoming_counts(self, subject_ids: Sequence[int]) -> Dict[int, int]:
        """Visible incoming relation count per subject, for the fan-in cap."""
        ids = [int(n) for n in dict.fromkeys(subject_ids)]
        if not ids:
            return {}
        placeholders = ','.join('?' * len(ids))
        rows = self.fetchall(
            f"""
            SELECT r.to_subject_id AS subject_id, COUNT(*) AS n
            FROM subject_relations r
            JOIN subject_nodes sf ON sf.id = r.from_subject_id
            WHERE r.hidden_batch_id IS NULL
              AND sf.status = 'active'
              AND r.strength <> {STRENGTH_REFUTED}
              AND r.to_subject_id IN ({placeholders})
            GROUP BY r.to_subject_id
            """,
            tuple(ids),
        )
        counts = {nid: 0 for nid in ids}
        for row in rows:
            counts[row['subject_id']] = row['n']
        return counts

    def _dimension_names(self) -> Dict[int, str]:
        """``{dimension_id: name}`` for the whole user DB.

        Small table, and the alternative is a join that has to survive
        ``exam_dimensions`` being absent on a database that never
        enabled dimensions.
        """
        try:
            return {
                row['id']: row['name']
                for row in self.fetchall("SELECT id, name FROM exam_dimensions")
            }
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_subject_relations(
        self,
        subject_id: int,
        primary_parent_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Every visible relation touching ``subject_id``, context-ordered.

        Args:
            subject_id: the subject whose panel is being drawn.
            primary_parent_id: the parent context currently selected on
                the deep dive, or ``None`` for "All parents". **This
                orders the list; it never shortens it** (decision 5).

        Returns:
            ``{'subject_id', 'subject_name', 'dimension_id',
            'relations': [...], 'incoming_count', 'outgoing_count',
            'fanin_soft_cap', 'fanin_over_cap'}``.

            Each relation carries ``relation_id``, ``direction``
            (``'outgoing'``/``'incoming'``), the other subject's
            ``other_subject_id`` / ``other_subject_name`` /
            ``other_subject_path``, its ``other_dimension_id`` /
            ``other_dimension_name`` and ``crosses_dimension``, plus
            ``reason``, ``strength``, ``strength_label``, ``is_refuted``,
            ``origin``, ``source_entry_id``, ``created_at``,
            ``confirmed_at``, ``context_rank`` and
            ``context_parent_ids``.

            An empty ``relations`` list is the normal state for months
            (decision 11) — the caller renders nothing at all rather
            than an empty card.

        Raises:
            SubjectNodeError: if ``subject_id`` does not exist.
        """
        subject = self._relation_subject_row(subject_id)
        rows = self._visible_relations_for(subject_id)
        if not rows:
            return {
                'subject_id': subject_id,
                'subject_name': subject['name'],
                'dimension_id': subject['dimension_id'],
                'relations': [],
                'incoming_count': 0,
                'outgoing_count': 0,
                'fanin_soft_cap': FANIN_SOFT_CAP,
                'fanin_over_cap': False,
            }

        other_ids = [
            row['to_subject_id'] if row['from_subject_id'] == subject_id
            else row['from_subject_id']
            for row in rows
        ]
        ancestors = self._ancestor_sets(other_ids)
        parent_ids = self._parent_ids_of(subject_id)
        dimension_names = self._dimension_names()

        placeholders = ','.join('?' * len(set(other_ids)))
        other_rows = {
            row['id']: row
            for row in self.fetchall(
                f"SELECT id, name, dimension_id FROM subject_nodes "
                f"WHERE id IN ({placeholders})",
                tuple(sorted(set(other_ids))),
            )
        }

        relations: List[Dict[str, Any]] = []
        for row, other_id in zip(rows, other_ids):
            other = other_rows.get(other_id)
            other_dim = other['dimension_id'] if other else None
            # The other subject's live contexts that are also *this*
            # subject's parents. Order follows parent_ids so the panel
            # can name them predictably.
            reachable = ancestors.get(other_id, set())
            context_parent_ids = [p for p in parent_ids if p in reachable]
            outgoing = row['from_subject_id'] == subject_id
            relations.append({
                'relation_id': row['relation_id'],
                'direction': 'outgoing' if outgoing else 'incoming',
                'from_subject_id': row['from_subject_id'],
                'to_subject_id': row['to_subject_id'],
                'other_subject_id': other_id,
                'other_subject_name': other['name'] if other else f'#{other_id}',
                'other_subject_path': self._build_subject_path(other_id),
                'other_dimension_id': other_dim,
                'other_dimension_name': dimension_names.get(other_dim),
                # Decision 6 — a rendering fact, never a filter. True
                # only when both sides actually declare a dimension and
                # they differ, so a single-dimension exam never shows a
                # label it cannot explain.
                'crosses_dimension': bool(
                    other_dim is not None
                    and subject['dimension_id'] is not None
                    and other_dim != subject['dimension_id']
                ),
                'reason': row['reason'],
                'strength': row['strength'],
                'strength_label': STRENGTH_LABELS.get(row['strength'], 'Unknown'),
                'is_refuted': row['strength'] == STRENGTH_REFUTED,
                'origin': row['origin'],
                'source_entry_id': row['source_entry_id'],
                'created_at': row['created_at'],
                'confirmed_at': row['confirmed_at'],
                'context_rank': self._context_rank(
                    context_parent_ids, primary_parent_id
                ),
                'context_parent_ids': context_parent_ids,
            })

        # Two stable passes rather than one composite key, because
        # ``created_at`` is a string that has to sort *descending* while
        # everything around it sorts ascending. Pass one puts the newest
        # first; pass two reorders by the tiers, and Python's stable sort
        # keeps recency as the tie-break inside each tier.
        relations.sort(key=lambda r: (str(r['created_at'] or ''), r['relation_id']),
                       reverse=True)
        # Refuted notes sink below real relations regardless of context —
        # they are annotations about an absence, not related topics.
        # Within that, decision 5's context tier leads, then strength.
        relations.sort(key=lambda r: (
            r['is_refuted'],
            r['context_rank'],
            -r['strength'],
        ))

        incoming = sum(
            1 for r in relations
            if r['direction'] == 'incoming' and not r['is_refuted']
        )
        return {
            'subject_id': subject_id,
            'subject_name': subject['name'],
            'dimension_id': subject['dimension_id'],
            'relations': relations,
            'incoming_count': incoming,
            'outgoing_count': sum(
                1 for r in relations
                if r['direction'] == 'outgoing' and not r['is_refuted']
            ),
            'fanin_soft_cap': FANIN_SOFT_CAP,
            'fanin_over_cap': incoming >= FANIN_SOFT_CAP,
        }

    def search_relatable_subjects(
        self,
        subject_id: int,
        query: str,
        limit: int = 10,
        direction: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Candidates for a new relation from ``subject_id``.

        Scoped to the same exam context and to active subjects, minus
        the subject itself and minus anything the requested *direction*
        already covers.

        The direction matters, and getting it wrong is how decision 7
        quietly dies. ``A→B`` existing says nothing about ``B→A``: *A
        causes B* and *B exacerbates A* can both be true, and closing
        that loop from the second subject's page is the natural way a
        student writes it. Excluding every existing partner regardless
        of direction would leave the cycle authorable only through the
        database. So ``direction='outgoing'`` hides only subjects this
        one already points at, ``'incoming'`` only the ones already
        pointing here, and ``None`` hides neither — the same ordered
        pair twice is still refused at write time, with a message that
        says so.

        **Not scoped to a dimension** (decision 6): a topic in one
        dimension relating to a technique in another is the capability
        containment cannot express. Each result reports its dimension so
        the picker can say when a choice would cross one, and its
        current incoming count so the picker can warn near the soft
        fan-in cap.
        """
        subject = self._relation_subject_row(subject_id)
        term = (query or '').strip()

        if direction == 'outgoing':
            already = self.fetchall(
                "SELECT to_subject_id AS other_id FROM subject_relations "
                "WHERE from_subject_id = ? AND hidden_batch_id IS NULL",
                (subject_id,),
            )
        elif direction == 'incoming':
            already = self.fetchall(
                "SELECT from_subject_id AS other_id FROM subject_relations "
                "WHERE to_subject_id = ? AND hidden_batch_id IS NULL",
                (subject_id,),
            )
        else:
            already = []
        excluded = {row['other_id'] for row in already} | {subject_id}

        rows = self.fetchall(
            """
            SELECT id, name, dimension_id
            FROM subject_nodes
            WHERE exam_context = ?
              AND status = 'active'
              AND name LIKE ?
            ORDER BY LENGTH(name) ASC, name ASC
            LIMIT ?
            """,
            (subject['exam_context'], f"%{term}%", max(int(limit), 1) + len(excluded)),
        )
        candidates = [row for row in rows if row['id'] not in excluded][:max(int(limit), 1)]
        if not candidates:
            return []

        dimension_names = self._dimension_names()
        counts = self._incoming_counts([row['id'] for row in candidates])
        return [
            {
                'id': row['id'],
                'name': row['name'],
                'path': self._build_subject_path(row['id']),
                'dimension_id': row['dimension_id'],
                'dimension_name': dimension_names.get(row['dimension_id']),
                'crosses_dimension': bool(
                    row['dimension_id'] is not None
                    and subject['dimension_id'] is not None
                    and row['dimension_id'] != subject['dimension_id']
                ),
                'incoming_count': counts.get(row['id'], 0),
                'fanin_soft_cap': FANIN_SOFT_CAP,
                'fanin_over_cap': counts.get(row['id'], 0) >= FANIN_SOFT_CAP,
            }
            for row in candidates
        ]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create_subject_relation(
        self,
        from_subject_id: int,
        to_subject_id: int,
        reason: str,
        *,
        strength: int = STRENGTH_LIKELY,
        origin: str = 'user',
        source_entry_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Record one directional relation. The reason is mandatory.

        Decision 2 is enforced here as well as in the schema so the
        caller gets an explanation rather than an ``IntegrityError``.
        There is deliberately no way to create a relation and supply the
        reason afterwards: an unexplained link reads as "people who
        bought this also bought", and a backlog of them is exactly how
        the feature would stop being metacognitive.

        Decision 7 means no cycle check: ``A→B`` and ``B→A`` are both
        accepted. The only structural refusal is a self-loop.

        Args:
            from_subject_id: the subject the relation starts at.
            to_subject_id: the subject it points to.
            reason: the student's sentence. Required, non-blank.
            strength: one of :data:`VALID_STRENGTHS`; ``-1`` records
                "checked — not related" (decision 8).
            origin: ``'user'`` or ``'extracted'`` (#60). A user-authored
                relation is confirmed at creation, because writing the
                reason *is* the confirmation; an extracted one stays
                unconfirmed until a human says so.
            source_entry_id: the mistake that prompted it, if any.

        Returns:
            The created row as a dict.

        Raises:
            ValidationError: blank/oversized reason, bad strength or
                origin, or a self-loop.
            SubjectNodeError: either endpoint missing or archived.
        """
        text = (reason or '').strip()
        if not text:
            raise ValidationError(
                "A relation needs a reason: say in your own words how the "
                "two subjects are related. This is the point of the feature."
            )
        if len(text) > MAX_REASON_LENGTH:
            raise ValidationError(
                f"That reason is {len(text)} characters; keep it under "
                f"{MAX_REASON_LENGTH}."
            )
        if strength not in VALID_STRENGTHS:
            raise ValidationError(
                f"Unknown relation strength {strength!r}. "
                f"Valid values: {list(VALID_STRENGTHS)}."
            )
        if origin not in VALID_ORIGINS:
            raise ValidationError(
                f"Unknown relation origin {origin!r}. "
                f"Valid values: {list(VALID_ORIGINS)}."
            )
        if from_subject_id == to_subject_id:
            raise ValidationError(
                "A subject cannot be related to itself. (Two subjects "
                "relating to each other in both directions is fine.)"
            )

        for node_id in (from_subject_id, to_subject_id):
            row = self._relation_subject_row(node_id)
            if row['status'] != 'active':
                raise SubjectNodeError(
                    f"Subject node {node_id} is {row['status']}; a relation "
                    f"to it would be hidden the moment it was written."
                )

        existing = self.fetchone(
            "SELECT id FROM subject_relations "
            "WHERE from_subject_id = ? AND to_subject_id = ?",
            (from_subject_id, to_subject_id),
        )
        if existing is not None:
            raise ValidationError(
                "Those two subjects already carry a relation in that "
                "direction. Edit or remove it rather than stating it twice."
            )

        with self.transaction():
            cursor = self.execute(
                "INSERT INTO subject_relations "
                "(from_subject_id, to_subject_id, reason, strength, origin, "
                " source_entry_id, confirmed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, "
                "        CASE WHEN ? = 'user' THEN CURRENT_TIMESTAMP ELSE NULL END)",
                (
                    from_subject_id, to_subject_id, text, strength, origin,
                    source_entry_id, origin,
                ),
            )
            relation_id = cursor.lastrowid

        if self.error_logger:
            self.error_logger.info(
                f"Created subject relation {relation_id}: "
                f"{from_subject_id} -> {to_subject_id} (strength {strength})",
                category=ErrorCategory.DATABASE,
            )
        return self.get_subject_relation(relation_id)

    def get_subject_relation(self, relation_id: int) -> Optional[Dict[str, Any]]:
        """One relation row as a dict, or ``None``."""
        row = self.fetchone(
            "SELECT * FROM subject_relations WHERE id = ?", (relation_id,)
        )
        return dict(row) if row is not None else None

    def delete_subject_relation(self, relation_id: int) -> bool:
        """Remove a relation outright. Returns False if it was already gone.

        A hard delete, unlike a subject: the row is one sentence the
        student wrote and can unwrite, and there is no downstream
        rollup that would be confused by its absence. Getting a
        mis-stated relation back out is what keeps the panel worth
        reading.
        """
        row = self.fetchone(
            "SELECT id FROM subject_relations WHERE id = ?", (relation_id,)
        )
        if row is None:
            return False
        with self.transaction():
            self.execute("DELETE FROM subject_relations WHERE id = ?", (relation_id,))
        return True

    def hide_relations_for_delete_batch(
        self,
        batch_id: str,
        archived_ids: Sequence[int],
    ) -> int:
        """Decision 9 — hide and journal the relations a delete archived.

        Called by ``HierarchyMixin.delete_subject_subtree`` **inside its
        transaction**, so this method opens none of its own.

        Every visible relation with either endpoint in ``archived_ids``
        is stamped with ``hidden_batch_id`` and journalled as a
        ``relation_hidden`` item on the batch. The stamp is what the
        read path checks; the journal is what #37's restore replays, and
        it carries the relation's content so a restore does not have to
        re-derive anything from a row a purge may since have dropped.

        Returns:
            The number of relations hidden.
        """
        ids = [int(n) for n in dict.fromkeys(archived_ids)]
        if not ids:
            return 0
        placeholders = ','.join('?' * len(ids))
        rows = self.fetchall(
            f"""
            SELECT id, from_subject_id, to_subject_id, reason, strength,
                   origin, source_entry_id
            FROM subject_relations
            WHERE hidden_batch_id IS NULL
              AND (from_subject_id IN ({placeholders})
                   OR to_subject_id IN ({placeholders}))
            ORDER BY id ASC
            """,
            tuple(ids) * 2,
        )
        archived = set(ids)
        for row in rows:
            self.execute(
                "INSERT INTO subject_delete_batch_items "
                "(batch_id, item_type, subject_node_id, parent_id, payload) "
                "VALUES (?, 'relation_hidden', ?, ?, ?)",
                (
                    batch_id,
                    row['from_subject_id'],
                    row['to_subject_id'],
                    json.dumps({
                        'relation_id': row['id'],
                        'reason': row['reason'],
                        'strength': row['strength'],
                        'origin': row['origin'],
                        'source_entry_id': row['source_entry_id'],
                        # Which end this delete took. A relation between
                        # two subjects the same batch archived names
                        # both; restore needs to know it is not
                        # resurrecting half a pair.
                        'archived_endpoints': sorted(
                            {row['from_subject_id'], row['to_subject_id']} & archived
                        ),
                    }),
                ),
            )
            self.execute(
                "UPDATE subject_relations SET hidden_batch_id = ? WHERE id = ?",
                (batch_id, row['id']),
            )
        return len(rows)
