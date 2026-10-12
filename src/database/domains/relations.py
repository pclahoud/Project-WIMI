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

**Relation types (owner, 2026-10-03; m026) — this reverses decision 3.**
Per exam, the student owns a fixed list of types, each with a forward and
a reverse label so decision 4's both-ends rendering survives; a type may
be symmetric. The labels live only in ``relation_types``, so a rename
reaches every relation at once. Existing relations stay **untyped** until
edited — nothing is guessed, and an untyped relation renders exactly as
before. A type in use is renamed or retired, **never deleted**: retiring
hides it from new choices while every relation using it keeps rendering.
So every read of ``relation_types`` says which of those it is — a status
filter, or an ``includes-retired`` marker — and a sweep test enforces it.
Decision 2 is untouched: type *and* sentence.

A symmetric relation is stored once, as ``(min id, max id)``; m026's
triggers refuse the other spelling. Decision 7 still holds for every
asymmetric type.

Mixin pattern: this class never imports other mixins. It is composed
into ``UserDatabase`` and reaches shared helpers through ``self.*``.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app_logging import ErrorCategory

from ..exceptions import SubjectNodeError, ValidationError
from ..migrations.user.m026_relation_types import seed_relation_types


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

#: An extracted relation the student has not confirmed is **not shown**
#: (owner's decision, 2026-10-05). It exists as a row the moment #60 proposes
#: it -- m019 designed ``origin``/``confirmed_at`` for exactly that -- but a
#: proposal is not a relation until a human says so, and showing it beside
#: confirmed ones would breach #14's decision 10 (*a student who never touches
#: this must never notice it exists*) and decision 11 (*degrade to absent, not
#: to an empty card*).
#:
#: A **user**-authored relation is confirmed at creation, because writing the
#: reason is the confirmation, so this predicate never hides one.
#:
#: Written once and interpolated, because partial adoption is worse than none:
#: miss one display read and an unconfirmed proposal appears somewhere,
#: silently. That is the lesson
#: ``test_dimension_soft_delete.py::test_every_read_of_exam_dimensions_filters_on_status``
#: exists for, and the guard here is its sibling. A read that legitimately
#: wants unconfirmed rows carries an ``includes-unconfirmed`` marker and is
#: exempt by name.
UNCONFIRMED_IS_HIDDEN = (
    "(r.origin <> 'extracted' OR r.confirmed_at IS NOT NULL)"
)

#: The same predicate for a query with no table alias.
#:
#: Two constants rather than one because the reads differ: the panel joins
#: several tables and aliases ``subject_relations`` as ``r``, while the
#: candidate picker's exclusion subqueries select from it alone, where ``r.``
#: would be a syntax error.
#:
#: The name deliberately contains ``UNCONFIRMED_IS_HIDDEN``, because the
#: sweep in ``tests/database/test_unconfirmed_extraction_is_hidden.py``
#: renders an f-string's interpolation as the **name** of what was
#: interpolated rather than its value -- so a predicate reaching a query
#: through a differently-named local is invisible to it, however correct it
#: is at runtime. That is not a weakness to work around: it is what makes the
#: guard readable, since the name is what a human finds too.
#: ``test_the_two_spellings_are_one_predicate`` keeps them from drifting.
UNCONFIRMED_IS_HIDDEN_NO_ALIAS = (
    "(origin <> 'extracted' OR confirmed_at IS NOT NULL)"
)

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

# A relation-type label is a verb phrase ("risk factor for"), not prose.
MAX_TYPE_LABEL_LENGTH = 60

RELATION_TYPE_ACTIVE = 'active'
RELATION_TYPE_RETIRED = 'retired'


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

        Visible means: not stamped by a delete batch (decision 9), both
        endpoints still active, and **not an unconfirmed extraction**
        (owner's decision, 2026-10-05 — see
        :data:`UNCONFIRMED_IS_HIDDEN`). The status join is belt and
        braces — a relation should always be stamped when its subject is
        archived — but a stamp that went missing must not resurrect a
        relation into a subject the user cannot see.
        """
        rows = self.fetchall(
            f"""
            SELECT
                r.id                AS relation_id,
                r.from_subject_id   AS from_subject_id,
                r.to_subject_id     AS to_subject_id,
                r.reason            AS reason,
                r.strength          AS strength,
                r.origin            AS origin,
                r.source_entry_id   AS source_entry_id,
                r.created_at        AS created_at,
                r.confirmed_at      AS confirmed_at,
                r.relation_type_id  AS relation_type_id,
                t.label             AS type_label,
                t.reverse_label     AS type_reverse_label,
                t.is_symmetric      AS type_is_symmetric,
                t.status            AS type_status
            FROM subject_relations r
            JOIN subject_nodes sf ON sf.id = r.from_subject_id
            JOIN subject_nodes st ON st.id = r.to_subject_id
            -- includes-retired: a relation keeps rendering after its type
            -- is retired. Retiring only removes the type from new choices.
            LEFT JOIN relation_types t ON t.id = r.relation_type_id
            WHERE r.hidden_batch_id IS NULL
              AND sf.status = 'active'
              AND st.status = 'active'
              AND {UNCONFIRMED_IS_HIDDEN}
              AND (r.from_subject_id = ? OR r.to_subject_id = ?)
            """,
            (subject_id, subject_id),
        )
        return [dict(row) for row in rows]

    def _incoming_counts(self, subject_ids: Sequence[int]) -> Dict[int, int]:
        """Visible incoming relation count per subject, for the fan-in cap.

        Unconfirmed extractions are excluded for the same reason they are
        excluded from the panel: a relation nobody can see must not push a
        subject over a cap that decides what is rendered. Counting them would
        make the panel's own contents depend on rows absent from it.
        """
        ids = [int(n) for n in dict.fromkeys(subject_ids)]
        if not ids:
            return {}
        placeholders = ','.join('?' * len(ids))
        # A symmetric relation points at neither end -- it is stored with
        # the larger id as ``to_subject_id`` only by convention -- so it is
        # not fan-in and is not counted.
        rows = self.fetchall(
            f"""
            SELECT r.to_subject_id AS subject_id, COUNT(*) AS n
            FROM subject_relations r
            JOIN subject_nodes sf ON sf.id = r.from_subject_id
            -- includes-retired: a retired type's relations still count.
            LEFT JOIN relation_types t ON t.id = r.relation_type_id
            WHERE r.hidden_batch_id IS NULL
              AND sf.status = 'active'
              AND r.strength <> {STRENGTH_REFUTED}
              AND {UNCONFIRMED_IS_HIDDEN}
              AND COALESCE(t.is_symmetric, 0) = 0
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
                for row in self.fetchall(
                    "SELECT id, name FROM exam_dimensions WHERE status = 'active'")
            }
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Relation types (m026)
    # ------------------------------------------------------------------

    def _exam_id_for_subject(self, subject_id: int) -> Optional[int]:
        """The ``exam_contexts.id`` a subject belongs to, or ``None``.

        ``subject_nodes`` names its exam by ``exam_context`` (the exam's
        name), while ``relation_types`` is keyed by id, as
        ``exam_dimensions`` is.
        """
        row = self.fetchone(
            "SELECT ec.id AS exam_id FROM subject_nodes sn "
            "JOIN exam_contexts ec ON ec.exam_name = sn.exam_context "
            "WHERE sn.id = ?",
            (subject_id,),
        )
        return row['exam_id'] if row is not None else None

    @staticmethod
    def _relation_type_dict(row) -> Dict[str, Any]:
        return {
            'id': row['id'],
            'exam_id': row['exam_id'],
            'label': row['label'],
            'reverse_label': row['reverse_label'],
            'is_symmetric': bool(row['is_symmetric']),
            'status': row['status'],
            'is_retired': row['status'] == RELATION_TYPE_RETIRED,
            'sort_order': row['sort_order'],
        }

    def _relation_type_row(self, type_id: int):
        """One type, retired or not, or raise ``ValidationError``."""
        row = self.fetchone(
            "SELECT * FROM relation_types WHERE id = ? "
            "/* includes-retired: callers decide what a retired type may do */",
            (type_id,)
        )
        if row is None:
            raise ValidationError(f"There is no relation type {type_id}.")
        return row

    def seed_relation_types_for_exam(self, exam_id: int) -> int:
        """Give a new exam the owner's seed list. A no-op if it has one.

        Called from ``ExamContextMixin.create_exam_context`` inside its
        transaction, so it opens none of its own.
        """
        return seed_relation_types(self.conn, exam_id)

    def get_relation_types(
        self,
        exam_id: Optional[int] = None,
        *,
        subject_id: Optional[int] = None,
        include_retired: bool = False,
    ) -> List[Dict[str, Any]]:
        """An exam's relation types, in display order.

        Pass ``exam_id`` or ``subject_id`` (the exam is looked up from the
        subject). **Retired types are excluded unless asked for**: this is
        what a new-relation picker reads, and a retired type must not be
        offered there.
        """
        if exam_id is None and subject_id is not None:
            exam_id = self._exam_id_for_subject(subject_id)
        if exam_id is None:
            return []
        if include_retired:
            rows = self.fetchall(
                "SELECT * FROM relation_types WHERE exam_id = ? "
                "ORDER BY status = 'retired', sort_order, id "
                "/* includes-retired: the caller asked for the whole list */",
                (exam_id,),
            )
        else:
            rows = self.fetchall(
                "SELECT * FROM relation_types WHERE exam_id = ? AND status = ? "
                "ORDER BY sort_order, id",
                (exam_id, RELATION_TYPE_ACTIVE),
            )
        return [self._relation_type_dict(row) for row in rows]

    @staticmethod
    def _clean_label(value: Optional[str], what: str) -> str:
        text = ' '.join((value or '').split())
        if not text:
            raise ValidationError(f"A relation type needs a {what}.")
        if len(text) > MAX_TYPE_LABEL_LENGTH:
            raise ValidationError(
                f"That {what} is {len(text)} characters; keep it under "
                f"{MAX_TYPE_LABEL_LENGTH}.")
        return text

    def _refuse_active_label_clash(self, exam_id: int, label: str,
                                   except_id: int) -> None:
        clash = self.fetchone(
            "SELECT id FROM relation_types WHERE exam_id = ? AND status = ? "
            "AND label = ? COLLATE NOCASE AND id <> ?",
            (exam_id, RELATION_TYPE_ACTIVE, label, except_id),
        )
        if clash is not None:
            raise ValidationError(
                f'This exam already has a relation type called "{label}".')

    def rename_relation_type(
        self,
        type_id: int,
        *,
        label: Optional[str] = None,
        reverse_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rename a type. Every relation using it shows the new labels.

        A symmetric type has one label, used from both ends, so its
        reverse label always follows the forward one and is not settable.
        """
        row = self._relation_type_row(type_id)
        new_label = self._clean_label(label, 'label') if label is not None else row['label']
        if row['is_symmetric']:
            new_reverse = new_label
        elif reverse_label is not None:
            new_reverse = self._clean_label(reverse_label, 'reverse label')
        else:
            new_reverse = row['reverse_label']
        if row['status'] == RELATION_TYPE_ACTIVE:
            self._refuse_active_label_clash(row['exam_id'], new_label, type_id)
        with self.transaction():
            self.execute(
                "UPDATE relation_types SET label = ?, reverse_label = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_label, new_reverse, type_id),
            )
        return self._relation_type_dict(self._relation_type_row(type_id))

    def retire_relation_type(self, type_id: int) -> Dict[str, Any]:
        """Hide a type from new relations. Its relations keep rendering.

        There is deliberately no delete (owner's decision): a relation's
        type is part of what the student wrote, and archive-not-delete is
        how WIMI treats everything else a student authored (#15, #210).
        """
        self._relation_type_row(type_id)
        with self.transaction():
            self.execute(
                "UPDATE relation_types SET status = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (RELATION_TYPE_RETIRED, type_id),
            )
        return self._relation_type_dict(self._relation_type_row(type_id))

    def reinstate_relation_type(self, type_id: int) -> Dict[str, Any]:
        """Undo :meth:`retire_relation_type`, unless the label was reused."""
        row = self._relation_type_row(type_id)
        if row['status'] != RELATION_TYPE_ACTIVE:
            self._refuse_active_label_clash(row['exam_id'], row['label'], type_id)
        with self.transaction():
            self.execute(
                "UPDATE relation_types SET status = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (RELATION_TYPE_ACTIVE, type_id),
            )
        return self._relation_type_dict(self._relation_type_row(type_id))

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
            (``'outgoing'``/``'incoming'``, or ``'symmetric'`` for a
            symmetric type), ``relation_type_id`` / ``relation_type_label``
            (``None`` when untyped), ``relation_label`` (the type's label as
            read from this subject: forward when outgoing or symmetric,
            reverse when incoming; ``None`` when untyped),
            ``relation_type_retired``, the other subject's
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
            other_path = self._build_subject_path_info(other_id)
            # The other subject's live contexts that are also *this*
            # subject's parents. Order follows parent_ids so the panel
            # can name them predictably.
            reachable = ancestors.get(other_id, set())
            context_parent_ids = [p for p in parent_ids if p in reachable]
            outgoing = row['from_subject_id'] == subject_id
            typed = row['relation_type_id'] is not None
            symmetric = typed and bool(row['type_is_symmetric'])
            if symmetric:
                direction = 'symmetric'
            else:
                direction = 'outgoing' if outgoing else 'incoming'
            if not typed:
                # Untyped: the page keeps rendering "Leads to"/"Caused by"
                # as it always has. Nothing is guessed for it.
                relation_label = None
            elif symmetric or outgoing:
                relation_label = row['type_label']
            else:
                relation_label = row['type_reverse_label']
            relations.append({
                'relation_id': row['relation_id'],
                'direction': direction,
                'relation_type_id': row['relation_type_id'],
                'relation_type_label': row['type_label'],
                # The label as read from *this* subject's page.
                'relation_label': relation_label,
                'relation_type_retired': (
                    typed and row['type_status'] == RELATION_TYPE_RETIRED),
                'from_subject_id': row['from_subject_id'],
                'to_subject_id': row['to_subject_id'],
                'other_subject_id': other_id,
                'other_subject_name': other['name'] if other else f'#{other_id}',
                'other_subject_path': other_path['path'],
                # #301: present only when the path was actually shortened, so
                # the panel's tooltip appears only where it has something to
                # say. The panel already labels the other subject's dimension
                # when it differs; this is the same shape of caveat.
                'other_subject_path_omitted_ancestors': (
                    other_path['omitted_ancestors'] or None
                ),
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
        relation_type_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Candidates for a new relation from ``subject_id``.

        **The exclusion is per type** (m026). *A causes B* existing must not
        hide B when the student is writing *A confused with B*, so only
        partners already related *by the requested type* in the requested
        direction are hidden. ``relation_type_id=None`` means an untyped
        relation and hides only untyped partners. A symmetric type has no
        direction: a partner related by it from either end is hidden.

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

        symmetric = False
        if relation_type_id is not None:
            symmetric = bool(self._relation_type_row(relation_type_id)['is_symmetric'])
        if symmetric:
            direction = 'symmetric'

        # ``IS`` rather than ``=`` so that ``None`` matches untyped rows.
        #
        # **An unconfirmed extraction does NOT hide its partner**, and that
        # reversed with #382. This comment used to say the opposite, with a
        # reason that was correct at the time: such a row occupies the pair
        # under m026's UNIQUE, so offering the subject again would have walked
        # the student into a refusal from ``create_subject_relation``.
        #
        # That refusal is gone. The owner's decision is that writing the
        # relation by hand **adopts** the proposal, so the exclusion is no
        # longer protecting anybody -- it is the thing preventing the fix.
        # Measured before changing it: with an unconfirmed ``causes`` proposal
        # between two subjects, this method returned **no candidates** for
        # that type and direction, so the adoption path was unreachable from
        # the panel and the student saw the partner silently missing from the
        # list rather than any explanation at all.
        #
        # So this now carries the hiding predicate on its own merit, and the
        # name says so.
        # The predicate is appended at each of the three read sites below
        # rather than folded in here, and the sweep is why: it renders an
        # f-string's interpolation as the NAME of what was interpolated,
        # so a predicate arriving through two levels of local is invisible
        # to it however correct it is at runtime. That turns out to be the
        # more readable shape anyway -- each query says on its own line
        # that it hides unconfirmed extractions.
        same_type = "relation_type_id IS ? AND hidden_batch_id IS NULL"
        if direction == 'outgoing':
            already = self.fetchall(
                "SELECT to_subject_id AS other_id FROM subject_relations "
                f"WHERE from_subject_id = ? AND {same_type} AND {UNCONFIRMED_IS_HIDDEN_NO_ALIAS}",
                (subject_id, relation_type_id),
            )
        elif direction == 'incoming':
            already = self.fetchall(
                "SELECT from_subject_id AS other_id FROM subject_relations "
                f"WHERE to_subject_id = ? AND {same_type} AND {UNCONFIRMED_IS_HIDDEN_NO_ALIAS}",
                (subject_id, relation_type_id),
            )
        elif direction == 'symmetric':
            already = self.fetchall(
                "SELECT CASE WHEN from_subject_id = ? THEN to_subject_id "
                "            ELSE from_subject_id END AS other_id "
                "FROM subject_relations "
                f"WHERE (from_subject_id = ? OR to_subject_id = ?) AND {same_type} AND {UNCONFIRMED_IS_HIDDEN_NO_ALIAS}",
                (subject_id, subject_id, subject_id, relation_type_id),
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
                # #301 filters this; no omitted-ancestors key travels with
                # it, for the same reason as the entry form's subject
                # search -- these are the relation picker's result buttons,
                # and a tooltip host inside each would add a tab stop per
                # result. The panel that renders the *chosen* relation does
                # carry the note (`other_subject_path_omitted_ancestors`).
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

    def _usable_relation_type(self, relation_type_id: int, subject_id: int):
        """The type row, or a sentence saying why it may not be used.

        Two checks, and both are about the *student's* list rather than the
        schema: a retired type is one they said they no longer want, and a
        type from another exam is not in this exam's vocabulary at all.
        m026 enforces neither, so without this they surface as a wrong row
        written successfully.

        Shared by ``create_subject_relation`` and
        ``confirm_subject_relation`` because a type that may not be chosen for
        a new relation may not be chosen while confirming one either -- two
        copies of that rule is how one of them ends up permitting a retired
        type.
        """
        row = self._relation_type_row(int(relation_type_id))
        if row['status'] != RELATION_TYPE_ACTIVE:
            raise ValidationError(
                f'"{row["label"]}" has been retired, so it is not '
                f"offered for new relations.")
        if row['exam_id'] != self._exam_id_for_subject(subject_id):
            raise ValidationError(
                f'"{row["label"]}" belongs to another exam\'s list '
                f"of relation types.")
        return row

    def _validated_reason(self, reason: Optional[str]) -> str:
        """A non-blank reason within the length cap, or a sentence.

        Decision 2's enforcement, shared by the create and confirm paths. The
        confirm path needs it because the student may edit the prefilled
        passage down to nothing before pressing the button, and "" must be
        refused there for exactly the reason it is refused at creation.
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
        return text

    def create_subject_relation(
        self,
        from_subject_id: int,
        to_subject_id: int,
        reason: str,
        *,
        strength: int = STRENGTH_LIKELY,
        origin: str = 'user',
        source_entry_id: Optional[int] = None,
        relation_type_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Record one relation. The reason is mandatory.

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
            relation_type_id: one of the exam's **active** types, or
                ``None`` for an untyped relation. A symmetric type is
                stored in canonical order (smaller subject id first)
                whichever page it was written from, so the stored
                ``from``/``to`` may be the reverse of what was passed.

        Returns:
            The created row as a dict.

            **Or an adopted one.** When ``origin='user'`` lands on a pair and
            type already held by an *unconfirmed extraction*, that row is
            confirmed with this caller's reason and strength instead of a
            second one being created (#382). The returned dict then carries
            two keys that are **not columns**: ``adopted_proposal: True`` and
            ``adopted_from_entry_id``, so the caller can say what happened
            rather than reporting a plain save. Nothing else sets them, and
            ``get_subject_relation`` never does.

        Raises:
            ValidationError: blank/oversized reason, bad strength or
                origin, a self-loop, a duplicate that is **not** an
                unconfirmed extraction, or a type that is unknown, retired,
                or belongs to another exam.
            SubjectNodeError: either endpoint missing or archived.
        """
        text = self._validated_reason(reason)
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

        type_row = None
        if relation_type_id is not None:
            type_row = self._usable_relation_type(
                int(relation_type_id), from_subject_id)
            if type_row['is_symmetric'] and from_subject_id > to_subject_id:
                # One relation, one row: m026's triggers refuse the other
                # spelling, so canonicalise here rather than fail there.
                from_subject_id, to_subject_id = to_subject_id, from_subject_id

        # includes-unconfirmed, and it has to: m026's
        # UNIQUE(from, to, relation_type_id) means the row physically blocks a
        # second one whether or not anybody can see it, so filtering here
        # would turn a clear ValidationError into an IntegrityError from three
        # frames down -- which #66 2.2 forbids. The message is the part that
        # needs deciding, not the predicate.
        existing = self.fetchone(
            "SELECT id, origin, confirmed_at, source_entry_id "
            "FROM subject_relations "
            "WHERE from_subject_id = ? AND to_subject_id = ? "
            "AND relation_type_id IS ?",
            (from_subject_id, to_subject_id, relation_type_id),
        )
        if existing is not None:
            # An UNCONFIRMED EXTRACTION is adopted, not refused (#382,
            # owner's decision 2026-10-05). The student has written a reason
            # for exactly this pair and type, and #14's decision 2 says
            # writing the reason IS the confirmation -- so they have already
            # done what confirming requires, and refusing them would be
            # refusing on the strength of a row they cannot see.
            #
            # Their words replace the extracted passage and their strength
            # replaces the default, while ``origin`` and ``source_entry_id``
            # stay: the entry really is where this pair was first noticed,
            # and that is a true statement worth keeping rather than a claim
            # about who wrote the sentence -- which ``reason`` and
            # ``confirmed_at`` now answer.
            #
            # Note this can only be the SAME type, because m026's UNIQUE is
            # per (from, to, relation_type_id): a ``causes`` proposal does
            # not block a manual ``risk factor for``. So there is no
            # retyping to do here.
            if (origin == 'user'
                    and existing['origin'] == 'extracted'
                    and existing['confirmed_at'] is None):
                # One transaction over both writes: a confirmation that
                # landed without the student's strength would be a relation
                # carrying their sentence and the extractor's default.
                with self.transaction():
                    self.confirm_subject_relation(existing['id'], reason=text)
                    self.execute(
                        "UPDATE subject_relations SET strength = ? WHERE id = ?",
                        (strength, existing['id']),
                    )
                adopted = self.get_subject_relation(existing['id'])
                adopted['adopted_proposal'] = True
                adopted['adopted_from_entry_id'] = existing['source_entry_id']
                if self.error_logger:
                    self.error_logger.info(
                        f"adopted extracted relation {existing['id']} as the "
                        f"student's own: {from_subject_id} -> {to_subject_id}",
                        category=ErrorCategory.DATABASE,
                    )
                return adopted

            if type_row is None:
                # "Edit or remove it" named an action that exists at no
                # layer (#484): this domain has create / confirm / delete and
                # NO update, there is no bridge slot, and the panel row's only
                # action is Remove. #174's rule applies to a message as much
                # as to a control -- so it names the route that exists, and
                # says what that route costs, because remove-and-rewrite is
                # not a free substitute for an edit.
                raise ValidationError(
                    "Those two subjects already carry a relation in that "
                    "direction. Remove it from the panel and write it again "
                    "to change what it says; the new one starts its own "
                    "history."
                )
            # The typed variant, same correction (#484).
            raise ValidationError(
                f'Those two subjects are already related by "{type_row["label"]}"'
                + ("." if type_row['is_symmetric'] else " in that direction.")
                + " Remove it from the panel and write it again to change what"
                + " it says; the new one starts its own history."
            )

        with self.transaction():
            cursor = self.execute(
                "INSERT INTO subject_relations "
                "(from_subject_id, to_subject_id, reason, strength, origin, "
                " source_entry_id, relation_type_id, confirmed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, "
                "        CASE WHEN ? = 'user' THEN CURRENT_TIMESTAMP ELSE NULL END)",
                (
                    from_subject_id, to_subject_id, text, strength, origin,
                    source_entry_id, relation_type_id, origin,
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

    def confirm_subject_relation(
        self,
        relation_id: int,
        *,
        reason: Optional[str] = None,
        relation_type_id: Optional[int] = None,
        change_type: bool = False,
    ) -> Dict[str, Any]:
        """Endorse an extracted relation, optionally editing it first (#60).

        Owner's decision (#5494): *"the reason is the passage, prefilled and
        editable, and confirming is a separate act"*. An extracted relation is
        inserted with the passage as its reason and ``confirmed_at`` NULL, and
        is **invisible** until this runs -- ``UNCONFIRMED_IS_HIDDEN`` keeps it
        out of the panel and out of the incoming counts. So this method is the
        only thing that makes a proposal into a relation the student sees.

        That is why it does not touch #14's decision 2. *The reason exists*
        and *a human has endorsed it* are different facts, and m019 separated
        them before #60 existed. The reason stays ``NOT NULL`` at insert, so
        there is still no explain-later state; what was missing was a record
        of the endorsement.

        Args:
            relation_id: the relation to confirm.
            reason: the edited reason. ``None`` keeps the stored one (the
                prefilled passage). A reason the student edited down to blank
                is refused, exactly as at creation.
            relation_type_id: a different type, or ``None`` **with**
                ``change_type=True`` to make it untyped.
            change_type: whether ``relation_type_id`` is meant at all. Needed
                because ``None`` is a legitimate *value* for that column, so
                a bare default could not distinguish "leave the type alone"
                from "make it untyped" -- and silently doing the wrong one of
                those would retype a relation the student did not retype.

        Changing the type at confirmation is not a convenience: #4904 measured
        **11 of 31 rejections as "right pair, wrong type"**, and those are
        fixed by choosing the right type rather than by rejecting a true pair.

        Returns:
            The confirmed row. Idempotent -- confirming an already-confirmed
            relation returns it unchanged rather than raising, because the
            student pressing twice has not done anything wrong, and a second
            press must not restamp ``confirmed_at`` to a later time than the
            moment they actually endorsed it.

        Raises:
            SubjectNodeError: no such relation.
            ValidationError: a blank or oversized reason, a retired or
                foreign type, or a type change that would collide with a
                relation that already exists.
        """
        row = self.fetchone(
            "SELECT * FROM subject_relations WHERE id = ? "
            "/* includes-unconfirmed: this is the method that confirms one */",
            (relation_id,),
        )
        if row is None:
            raise SubjectNodeError(f"Relation {relation_id} not found")

        if row['confirmed_at'] is not None and reason is None and not change_type:
            return self.get_subject_relation(relation_id)

        from_id, to_id = row['from_subject_id'], row['to_subject_id']
        new_type = row['relation_type_id']
        if change_type:
            new_type = int(relation_type_id) if relation_type_id is not None else None
            if new_type is not None:
                type_row = self._usable_relation_type(new_type, from_id)
                if type_row['is_symmetric'] and from_id > to_id:
                    # A symmetric type is one relation stored as (min, max).
                    # Retyping an asymmetric relation to a symmetric type can
                    # therefore require reversing the stored direction, which
                    # m026's triggers would otherwise refuse.
                    from_id, to_id = to_id, from_id
            if (from_id, to_id, new_type) != (
                    row['from_subject_id'], row['to_subject_id'],
                    row['relation_type_id']):
                clash = self.fetchone(
                    "SELECT id FROM subject_relations "
                    "WHERE from_subject_id = ? AND to_subject_id = ? "
                    "AND relation_type_id IS ? AND id <> ? "
                    "/* includes-unconfirmed: the UNIQUE does not filter */",
                    (from_id, to_id, new_type, relation_id),
                )
                if clash is not None:
                    label = type_row['label'] if new_type is not None else 'that type'
                    raise ValidationError(
                        f'Those two subjects already carry a relation by '
                        f'"{label}". Remove that one first, or reject this '
                        f'proposal instead of retyping it.'
                    )

        text = self._validated_reason(
            reason if reason is not None else row['reason'])

        with self.transaction():
            self.execute(
                "UPDATE subject_relations SET reason = ?, relation_type_id = ?, "
                "from_subject_id = ?, to_subject_id = ?, "
                "confirmed_at = COALESCE(confirmed_at, CURRENT_TIMESTAMP) "
                "WHERE id = ?",
                (text, new_type, from_id, to_id, relation_id),
            )

        if self.error_logger:
            # ``.info``, not ``.log``: ErrorLogger.log takes level as its
            # FIRST POSITIONAL argument, so log(message, level='INFO')
            # binds the message to ``level`` and then collides with the
            # keyword -- TypeError, at the moment a student saves. It
            # survived 167 passing tests because every fixture in this
            # suite builds its UserDatabase with error_logger=None, so
            # the guard above is false and the call never runs.
            self.error_logger.info(
                f"confirmed subject relation {relation_id}: {from_id} -> {to_id}",
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

    # ------------------------------------------------------------------
    # What the extractor is allowed to name (#60, #380 decision 2)
    # ------------------------------------------------------------------

    def get_extraction_source(self, entry_id: int) -> Dict[str, Any]:
        """The entry's explanation and the exam it belongs to.

        One query rather than ``get_question_entry``, which additionally loads
        the entry's subjects, tags, media and notes -- none of which this
        feature reads, and all of which are extra queries on a path the
        student is waiting on.

        **``explanation`` is HTML**, exactly as stored:
        ``question_entry.js`` saves ``explanationEditor.getContent().html``.
        It is returned raw and the caller passes it through
        :func:`~app.relation_extraction.runtime.plain_text`, because deciding
        what the model sees belongs with the model rather than in a SELECT.

        Raises:
            SubjectNodeError: no such entry. A sentence rather than ``None``,
                because every caller would have to turn ``None`` into one.
        """
        row = self.fetchone(
            "SELECT qe.id, qe.explanation, qe.reflection, qe.is_draft, "
            "       ec.exam_name AS exam_context, ec.id AS exam_id "
            "FROM question_entries qe "
            "JOIN review_sessions rs ON rs.id = qe.review_session_id "
            "LEFT JOIN exam_contexts ec ON ec.id = rs.exam_context_id "
            "WHERE qe.id = ?",
            (entry_id,),
        )
        if row is None:
            raise SubjectNodeError(f"Entry {entry_id} not found")
        return {
            'entry_id': row['id'],
            'explanation': row['explanation'],
            'exam_context': row['exam_context'],
            'exam_id': row['exam_id'],
            'is_draft': bool(row['is_draft']),
        }

    def get_extraction_vocabulary(
        self,
        exam_context: str,
    ) -> List[Dict[str, Any]]:
        """Every active subject in an exam, with its aliases, for span matching.

        Owner's decision (#380, 2026-10-05): a model mention may name **any
        active subject in the entry's exam, across all dimensions**, matched
        against its own name or one of its ``subject_aliases``. Not the
        entry's tagged subjects only -- ``search_relatable_subjects`` (the
        manual picker) is already exam-wide, so a narrower proposal scope
        would mean pairs a student can relate by hand but that can never be
        proposed.

        Returns rows of ``{'id', 'name', 'dimension_id', 'aliases'}``, shaped
        for :meth:`app.relation_extraction.matching.Vocabulary.from_subjects`,
        which is where the matching rule itself lives.

        **Two queries, not one per subject.** ``get_all_subjects_with_aliases_for_exam``
        already answers almost this question and is the wrong tool here: it
        builds the whole hierarchy and then calls ``get_aliases_for_subject``
        **once per node**, which is the N+1 shape #201 exists about. This runs
        on every extraction, so it reads the aliases in one pass and joins in
        Python.

        ``status = 'active'`` is not optional. An archived subject's relations
        are hidden by decision 9, so proposing one would write a row nobody
        can see -- the same reason ``_relation_subject_row`` refuses an
        archived endpoint.
        """
        subjects = self.fetchall(
            "SELECT id, name, dimension_id FROM subject_nodes "
            "WHERE exam_context = ? AND status = 'active' "
            "ORDER BY id",
            (exam_context,),
        )
        aliases = self.fetchall(
            "SELECT sa.subject_node_id AS subject_id, sa.alias_name "
            "FROM subject_aliases sa "
            "JOIN subject_nodes sn ON sn.id = sa.subject_node_id "
            "WHERE sn.exam_context = ? AND sn.status = 'active'",
            (exam_context,),
        )

        by_subject: Dict[int, List[str]] = {}
        for row in aliases:
            by_subject.setdefault(row['subject_id'], []).append(row['alias_name'])

        return [
            {
                'id': row['id'],
                'name': row['name'],
                'dimension_id': row['dimension_id'],
                'aliases': by_subject.get(row['id'], []),
            }
            for row in subjects
        ]

    def discard_unconfirmed_proposals_for_entry(self, entry_id: int) -> int:
        """Drop an entry's own unconfirmed extractions. Returns how many.

        Owner's decision (#382, 2026-10-05): proposals expire **only when
        that entry's extraction is run again**, and never on a timer. Running
        it again already says the previous proposals are stale, whereas a
        startup sweep would need a number nobody has and would delete
        something the student might have been meaning to get to.

        Three predicates, and dropping any one of them loses the student's
        work:

        * ``origin = 'extracted'`` -- a relation they wrote by hand is not a
          proposal, whatever entry it names;
        * ``confirmed_at IS NULL`` -- a confirmed extraction is a relation
          they endorsed, and is on the panel;
        * ``source_entry_id = ?`` -- an entry's re-run says nothing about
          proposals made from a different explanation.

        **A rejection is not affected and must not be.** m027 rows are their
        own table, so re-running cannot resurrect a pair the student rejected
        -- the next pass filters it out again through
        :meth:`rejected_pairs_for_entry`.

        Opens no transaction of its own: the caller runs it in the same one
        as the writes that replace these rows, so a failure cannot leave the
        entry with neither.
        """
        cursor = self.execute(
            "DELETE FROM subject_relations "
            "WHERE source_entry_id = ? AND origin = 'extracted' "
            "AND confirmed_at IS NULL "
            "/* includes-unconfirmed: unconfirmed is precisely what this "
            "   removes, and nothing else */",
            (entry_id,),
        )
        return cursor.rowcount or 0

    def existing_relation_pairs(self, exam_context: str) -> set:
        """``(from, to, relation_type_id)`` triples already carrying a relation.

        **Includes unconfirmed extractions, and must.** m026's
        ``UNIQUE(from_subject_id, to_subject_id, relation_type_id)`` is
        enforced against the row whether or not anybody can see it, so a
        proposal for a pair that already holds an unconfirmed one would reach
        ``create_subject_relation`` and be refused -- a refusal the student
        did not cause. The extractor unions this with
        :meth:`rejected_pairs_for_entry` and never proposes either.

        Hidden relations are included for the same reason: ``hidden_batch_id``
        does not release the UNIQUE.

        Symmetric types are already stored canonically (m026), so these
        triples are in the same order
        :func:`~app.relation_extraction.matching.canonical_pair` produces.
        """
        rows = self.fetchall(
            "SELECT r.from_subject_id, r.to_subject_id, r.relation_type_id "
            "FROM subject_relations r "
            "JOIN subject_nodes sn ON sn.id = r.from_subject_id "
            "WHERE sn.exam_context = ? "
            "/* includes-unconfirmed: the UNIQUE is enforced regardless, so a "
            "   filtered read here would walk the student into a refusal */",
            (exam_context,),
        )
        return {
            (row['from_subject_id'], row['to_subject_id'],
             row['relation_type_id'])
            for row in rows
        }

    def pending_proposals_elsewhere(
        self, exam_context: str, entry_id: int,
    ) -> Dict[Tuple[int, int, Optional[int]], Dict[str, Any]]:
        """Unanswered proposals on OTHER entries, keyed by their triple (#390).

        :meth:`existing_relation_pairs` suppresses a pair whenever any row
        holds it, and that is right -- m026's UNIQUE would refuse the insert.
        But a suppressed pair is in one of three states, and only one of them
        is something to tell the student about (owner's decision on #390: say
        so on the card):

        * **an unconfirmed extraction from another entry** -- returned here,
          with that entry's session and question number so the card can name
          it;
        * a **confirmed** relation -- already on the deep-dive panel, and a
          hand-written one has no entry to name at all;
        * a **hidden** relation, whose subject was archived (#15).

        The last two are filtered out by the predicates, not by the caller, so
        a card can never say "waiting on another entry" about a relation the
        student can already see or a subject they archived. Rejections are a
        separate table and are not this method's business; the caller drops
        any triple that is also rejected before rendering anything.

        Returns:
            ``{(from, to, relation_type_id): {'entry_id', 'session_name',
            'entry_order'}}``. Triples are canonical, as stored.
        """
        rows = self.fetchall(
            "SELECT r.from_subject_id, r.to_subject_id, r.relation_type_id, "
            "       r.source_entry_id, qe.entry_order, rs.session_name "
            "FROM subject_relations r "
            "JOIN subject_nodes sn ON sn.id = r.from_subject_id "
            "JOIN question_entries qe ON qe.id = r.source_entry_id "
            "JOIN review_sessions rs ON rs.id = qe.review_session_id "
            "WHERE sn.exam_context = ? "
            "  AND r.origin = 'extracted' "
            "  AND r.confirmed_at IS NULL "
            "  AND r.hidden_batch_id IS NULL "
            "  AND r.source_entry_id <> ? "
            "/* includes-unconfirmed: unconfirmed proposals elsewhere are "
            "   precisely what this reports, and nothing else (#390) */",
            (exam_context, entry_id),
        )
        return {
            (row['from_subject_id'], row['to_subject_id'],
             row['relation_type_id']): {
                'entry_id': row['source_entry_id'],
                'session_name': row['session_name'],
                'entry_order': row['entry_order'],
            }
            for row in rows
        }

    # ------------------------------------------------------------------
    # Rejected proposals (m027, #60)
    #
    # #14's decision 8 proposed ``strength = -1`` on ``subject_relations``
    # for "checked: not related". m027 records why that is the wrong
    # mechanism for #60: of 45 rejections in that issue's adjudication,
    # **25 meant "you misread my sentence"**, not "these two are
    # unrelated" -- and the two have different SCOPES. A sentinel would
    # have globally suppressed 25 true pairs on the strength of one badly
    # parsed sentence.
    #
    # So the scope rule is the whole point of this section:
    #
    #   misread      -> suppressed for its own entry only. A statement
    #                   about one piece of text; the same pair may extract
    #                   perfectly from a different explanation tomorrow.
    #   not_related  -> suppressed everywhere. A claim about the two
    #                   subjects, true whatever any explanation says.
    # ------------------------------------------------------------------

    REJECTION_MISREAD = 'misread'
    REJECTION_NOT_RELATED = 'not_related'
    VALID_REJECTION_KINDS = (REJECTION_MISREAD, REJECTION_NOT_RELATED)

    def _canonical_rejection_pair(
        self,
        from_subject_id: int,
        to_subject_id: int,
        relation_type_id: Optional[int],
    ) -> tuple:
        """Order the pair the way m027's triggers require.

        A symmetric type is stored once as ``(min id, max id)``, exactly as
        m026 does for the relation itself, and m027 repeats the same two
        triggers against the same predicate. Canonicalising here rather than
        letting the trigger fire is the #66 2.2 rule: the caller gets a
        sentence, not ``RAISE(ABORT)`` surfacing as an opaque
        ``DatabaseIntegrityError``.

        It is also what makes the suppression correct rather than merely
        tidy. Without it, rejecting *A confused with B* would leave
        *B confused with A* live, and the student would be asked the same
        question again from the other end.
        """
        if relation_type_id is None:
            return from_subject_id, to_subject_id
        row = self._relation_type_row(relation_type_id)
        if row is not None and row['is_symmetric'] and from_subject_id > to_subject_id:
            return to_subject_id, from_subject_id
        return from_subject_id, to_subject_id

    def record_relation_rejection(
        self,
        from_subject_id: int,
        to_subject_id: int,
        *,
        kind: str,
        relation_type_id: Optional[int] = None,
        source_entry_id: Optional[int] = None,
        passage: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Remember that the student rejected a proposal, and which kind it was.

        Args:
            from_subject_id: the proposal's head subject.
            to_subject_id: its tail subject.
            kind: ``'misread'`` or ``'not_related'``. **Not optional and with
                no default**, because a rejection whose kind nobody recorded
                cannot be scoped -- and guessing is exactly how the sentinel
                this table replaces behaved.
            relation_type_id: the proposed type, or ``None`` for an untyped
                proposal. A symmetric type canonicalises the pair.
            source_entry_id: the entry whose explanation produced the
                proposal. **Required for ``misread``**, which is a statement
                about one piece of text; a misread with no entry could never
                be matched by the suppression query and would sit there
                suppressing nothing, silently.
            passage: the text the proposal came from, kept for provenance.

        Raises:
            ValidationError: unknown ``kind``, a self-loop, or a ``misread``
                with no entry.
            SubjectNodeError: either endpoint missing.
        """
        if kind not in self.VALID_REJECTION_KINDS:
            raise ValidationError(
                f"Unknown rejection kind {kind!r}. Valid kinds: "
                f"{list(self.VALID_REJECTION_KINDS)}. 'misread' means the "
                f"extractor read this sentence wrongly; 'not_related' means "
                f"the two subjects are not related at all. They are scoped "
                f"differently, so there is no safe default."
            )
        if from_subject_id == to_subject_id:
            raise ValidationError(
                "A subject cannot be rejected as related to itself.")
        if kind == self.REJECTION_MISREAD and source_entry_id is None:
            raise ValidationError(
                "A 'misread' rejection needs the entry it came from: it says "
                "this sentence was parsed wrongly, so without the entry it "
                "would suppress nothing. Use 'not_related' for a judgement "
                "about the two subjects themselves."
            )

        # Both endpoints must exist. Archived is allowed, deliberately: the
        # student's judgement about a pair did not stop being true while one
        # of them was archived, and m027 keeps no cascade for that reason.
        self._relation_subject_row(from_subject_id)
        self._relation_subject_row(to_subject_id)
        if relation_type_id is not None and self._relation_type_row(relation_type_id) is None:
            raise ValidationError(
                f"Relation type {relation_type_id} does not exist.")

        # The entry is checked here for the same reason the misread CHECK is:
        # m027 declares `source_entry_id REFERENCES question_entries(id)`, so
        # a bad id already fails -- as a DatabaseIntegrityError saying
        # "FOREIGN KEY constraint failed", three frames down, naming neither
        # the column nor the value. #66 2.2 asks for a sentence instead.
        #
        # This was found by my own test fixture inventing entry ids: five
        # tests failed with exactly that opaque message. The constraint was
        # working; the diagnosis was the problem.
        if source_entry_id is not None:
            entry = self.fetchone(
                "SELECT id FROM question_entries WHERE id = ?",
                (source_entry_id,),
            )
            if entry is None:
                raise ValidationError(
                    f"Entry {source_entry_id} does not exist, so a rejection "
                    f"cannot be recorded against it."
                )

        head, tail = self._canonical_rejection_pair(
            from_subject_id, to_subject_id, relation_type_id)

        with self.transaction():
            cursor = self.execute(
                "INSERT INTO subject_relation_rejections "
                "(from_subject_id, to_subject_id, relation_type_id, kind, "
                " source_entry_id, passage) VALUES (?, ?, ?, ?, ?, ?)",
                (head, tail, relation_type_id, kind, source_entry_id, passage),
            )
            rejection_id = cursor.lastrowid

        if self.error_logger:
            # ``.info``, not ``.log``: ErrorLogger.log takes level as its
            # FIRST POSITIONAL argument, so log(message, level='INFO')
            # binds the message to ``level`` and then collides with the
            # keyword -- TypeError, at the moment a student saves. It
            # survived 167 passing tests because every fixture in this
            # suite builds its UserDatabase with error_logger=None, so
            # the guard above is false and the call never runs.
            self.error_logger.info(
                f"relation proposal rejected as {kind}: {head} -> {tail}",
                category=ErrorCategory.DATABASE,
            )
        return self.get_relation_rejection(rejection_id)

    def get_relation_rejection(self, rejection_id: int) -> Optional[Dict[str, Any]]:
        """One rejection by id, or ``None``."""
        row = self.fetchone(
            "SELECT * FROM subject_relation_rejections WHERE id = ?",
            (rejection_id,),
        )
        return dict(row) if row is not None else None

    def delete_relation_rejection(self, rejection_id: int) -> bool:
        """Undo a rejection. ``False`` if it was already gone.

        A hard delete, like ``delete_subject_relation``: the row records one
        judgement the student made and can unmake. Keeping a tombstone would
        mean a student who changed their mind could never be offered the
        proposal again, which is the sentinel's failure mode in a third hat.
        """
        row = self.fetchone(
            "SELECT id FROM subject_relation_rejections WHERE id = ?",
            (rejection_id,),
        )
        if row is None:
            return False
        with self.transaction():
            self.execute(
                "DELETE FROM subject_relation_rejections WHERE id = ?",
                (rejection_id,),
            )
        return True

    def list_relation_rejections(
        self,
        *,
        source_entry_id: Optional[int] = None,
        kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Rejections, newest first. For inspection and for tests.

        ``source_entry_id`` filters to rejections recorded against that entry,
        which is **not** the same question as *what is suppressed for that
        entry* -- a ``not_related`` recorded elsewhere suppresses here too.
        Use :meth:`rejected_pairs_for_entry` for suppression.
        """
        clauses = []
        params: List[Any] = []
        if source_entry_id is not None:
            clauses.append("source_entry_id = ?")
            params.append(source_entry_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.fetchall(
            f"SELECT * FROM subject_relation_rejections {where} "
            f"ORDER BY id DESC",
            tuple(params),
        )
        return [dict(row) for row in rows]

    def rejected_pairs_for_entry(self, source_entry_id: Optional[int]) -> set:
        """Everything suppressed when extracting from ``source_entry_id``.

        Returns a set of ``(from_subject_id, to_subject_id, relation_type_id)``
        in **canonical** order, so a caller canonicalises its candidate the
        same way and asks one ``in``.

        This is the scope rule, and it is the whole reason m027 is a table
        rather than #14's sentinel:

        * every ``not_related`` row, whatever entry it was recorded against;
        * the ``misread`` rows belonging to **this** entry only.

        ``source_entry_id=None`` means "not extracting from any entry", so
        only the global ``not_related`` rows apply -- a ``misread`` is a
        statement about a specific text and there is none here.

        One query rather than two, because the two clauses share the index
        m027 built on (pair, type, kind).
        """
        rows = self.fetchall(
            "SELECT from_subject_id, to_subject_id, relation_type_id "
            "FROM subject_relation_rejections "
            "WHERE kind = ? OR (kind = ? AND source_entry_id IS ?)",
            (self.REJECTION_NOT_RELATED, self.REJECTION_MISREAD,
             source_entry_id),
        )
        return {
            (row['from_subject_id'], row['to_subject_id'],
             row['relation_type_id'])
            for row in rows
        }

    def is_relation_rejected(
        self,
        from_subject_id: int,
        to_subject_id: int,
        *,
        relation_type_id: Optional[int] = None,
        source_entry_id: Optional[int] = None,
    ) -> bool:
        """Would this proposal be suppressed? Canonicalises before asking.

        The single-pair form of :meth:`rejected_pairs_for_entry`. Prefer that
        one when filtering a batch: this issues a type lookup and a query per
        call, which is the N+1 shape #201 exists about.
        """
        head, tail = self._canonical_rejection_pair(
            from_subject_id, to_subject_id, relation_type_id)
        return (head, tail, relation_type_id) in self.rejected_pairs_for_entry(
            source_entry_id)

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
            -- includes-unconfirmed, deliberately. Archiving a subject must
            -- stamp its unconfirmed extractions too: a row left unstamped
            -- would survive the archive and reappear the moment the student
            -- confirmed it, pointing at a subject the tree no longer shows.
            -- The journal is also what #37's restore replays, so an omitted
            -- row would come back unrestorable.
            SELECT id, from_subject_id, to_subject_id, reason, strength,
                   origin, source_entry_id, relation_type_id
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
                        # m026. Restore un-stamps the row by id and never
                        # reads this; it is journalled so the payload stays
                        # a complete record of what was hidden.
                        'relation_type_id': row['relation_type_id'],
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
