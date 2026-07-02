"""WIMI subject-edge (polyhierarchy) operations.

Implements §5.1 of ``docs/planning/POLYHIERARCHY_MIGRATION.md``: edge
CRUD, primary-parent invariant maintenance, cycle prevention via the
recursive descendants CTE, and root-to-child path enumeration.

Mixin pattern: this class never imports other mixins. It expects to be
composed into ``UserDatabase`` alongside ``BaseDatabase`` so it can call
``self.transaction()``, ``self.execute()``, ``self.fetchone()``,
``self.fetchall()`` — all provided by the composed instance.

The ``subject_edges`` table is created by migration v4
(``m004_subject_edges``); these methods assume the table exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..exceptions import (
    CircularReferenceError,
    SubjectNodeError,
    ValidationError,
    WeightValidationError,
)
from ..models import SubjectEdge


@dataclass
class ParentEdgeInfo:
    """View-shaped result for ``EdgesMixin.get_parents``.

    Each row joins ``subject_edges`` with ``subject_nodes`` to surface
    the parent's display name alongside the edge metadata. Returned as
    a small dataclass (rather than a NamedTuple or raw dict) to mirror
    the dataclass convention already used across ``models.py`` for
    bridge-friendly objects with a ``to_dict()`` method.
    """
    edge_id: int
    parent_id: int
    parent_name: str
    is_primary: bool
    display_order: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'edge_id': self.edge_id,
            'parent_id': self.parent_id,
            'parent_name': self.parent_name,
            'is_primary': self.is_primary,
            'display_order': self.display_order,
        }


class EdgesMixin:
    """Mixin for polyhierarchy edge operations on ``subject_edges``."""

    # ---------------------------------------------------------------- internal helpers

    def _would_create_cycle(self, parent_id: int, child_id: int) -> bool:
        """Return True if adding edge (parent_id → child_id) would create a cycle.

        A cycle exists if ``parent_id`` is already a descendant of
        ``child_id`` — i.e., walking down from ``child_id`` through
        existing edges would eventually reach ``parent_id``. The
        recursive CTE uses ``UNION`` (not ``UNION ALL``) defensively so
        a pre-existing data cycle does not loop forever.
        """
        cursor = self.execute(
            """
            WITH RECURSIVE descendants(id) AS (
                SELECT child_id FROM subject_edges WHERE parent_id = :child_id
                UNION
                SELECT se.child_id FROM subject_edges se
                JOIN descendants d ON se.parent_id = d.id
            )
            SELECT 1 FROM descendants WHERE id = :parent_id LIMIT 1
            """,
            {"parent_id": parent_id, "child_id": child_id},
        )
        return cursor.fetchone() is not None

    # ---------------------------------------------------------------- mutating ops

    def add_edge(
        self,
        parent_id: int,
        child_id: int,
        is_primary: bool = False,
    ) -> SubjectEdge:
        """Create a parent → child edge.

        Rejects:

        - Self-loops (``parent_id == child_id``) — raises
          ``ValidationError``. The DB-level CHECK constraint would catch
          this too, but we raise explicitly so callers get a typed
          exception with a clear message.
        - Cycles — raises ``CircularReferenceError`` if ``parent_id`` is
          already a descendant of ``child_id``.

        If ``is_primary=True``, atomically clears the existing primary
        flag on any other edge for the same child and sets it on the new
        one (so the "exactly zero or one primary per child" invariant
        holds).
        """
        if parent_id == child_id:
            raise ValidationError(
                f"Cannot add self-loop edge: parent_id == child_id == {parent_id}"
            )

        if self._would_create_cycle(parent_id, child_id):
            raise CircularReferenceError(
                f"Adding edge {parent_id} -> {child_id} would create a cycle "
                f"(child {child_id} is already an ancestor of {parent_id})."
            )

        with self.transaction():
            if is_primary:
                # Clear existing primary edges for this child first.
                self.execute(
                    "UPDATE subject_edges SET is_primary = FALSE, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE child_id = ? AND is_primary = TRUE",
                    (child_id,),
                )
            cursor = self.execute(
                "INSERT INTO subject_edges (parent_id, child_id, is_primary) "
                "VALUES (?, ?, ?)",
                (parent_id, child_id, bool(is_primary)),
            )
            edge_id = cursor.lastrowid

        row = self.fetchone(
            "SELECT * FROM subject_edges WHERE id = ?", (edge_id,)
        )
        edge = SubjectEdge.from_db_row(row)
        if edge is None:
            # Defensive — INSERT just succeeded so the row should exist.
            raise SubjectNodeError(
                f"Failed to fetch newly-inserted edge with id={edge_id}"
            )
        return edge

    def remove_edge(self, edge_id: int) -> None:
        """Delete an edge by ID.

        If the deleted edge was the only edge for its child, the child
        becomes orphaned (no parents). That is allowed — the user may
        re-parent it later or it may be a top-level node.
        """
        with self.transaction():
            self.execute(
                "DELETE FROM subject_edges WHERE id = ?", (edge_id,)
            )

    def set_primary_parent(
        self,
        child_id: int,
        new_primary_parent_id: int,
    ) -> SubjectEdge:
        """Atomically switch the primary parent for ``child_id``.

        - Clears ``is_primary`` on any existing primary edges for the
          child.
        - Sets ``is_primary=TRUE`` on the (new_primary_parent_id, child_id)
          edge if it exists.
        - Raises ``SubjectNodeError`` if no edge exists between the two
          nodes — callers should ``add_edge`` first.

        Both updates run inside one transaction so the
        "at most one primary per child" invariant is never visibly
        violated.
        """
        with self.transaction():
            existing = self.fetchone(
                "SELECT id FROM subject_edges "
                "WHERE parent_id = ? AND child_id = ?",
                (new_primary_parent_id, child_id),
            )
            if existing is None:
                raise SubjectNodeError(
                    f"No edge exists between parent {new_primary_parent_id} "
                    f"and child {child_id}; call add_edge first."
                )
            # Clear other primary edges for this child.
            self.execute(
                "UPDATE subject_edges SET is_primary = FALSE, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE child_id = ? AND is_primary = TRUE",
                (child_id,),
            )
            # Set primary on the target edge.
            self.execute(
                "UPDATE subject_edges SET is_primary = TRUE, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (existing['id'],),
            )

        row = self.fetchone(
            "SELECT * FROM subject_edges WHERE id = ?", (existing['id'],)
        )
        edge = SubjectEdge.from_db_row(row)
        if edge is None:
            raise SubjectNodeError(
                f"Failed to fetch updated edge id={existing['id']}"
            )
        return edge

    # ---------------------------------------------------------------- read ops

    def get_parents(self, child_id: int) -> List[ParentEdgeInfo]:
        """Return all parent edges for ``child_id`` (primary first).

        Joins ``subject_edges`` with ``subject_nodes`` to surface each
        parent's display name. Ordered by ``is_primary DESC`` then
        ``display_order ASC`` so the canonical parent always leads the
        list.
        """
        rows = self.fetchall(
            """
            SELECT
                se.id            AS edge_id,
                se.parent_id     AS parent_id,
                sn.name          AS parent_name,
                se.is_primary    AS is_primary,
                se.display_order AS display_order
            FROM subject_edges se
            JOIN subject_nodes sn ON sn.id = se.parent_id
            WHERE se.child_id = ?
            ORDER BY se.is_primary DESC, se.display_order ASC, se.id ASC
            """,
            (child_id,),
        )
        return [
            ParentEdgeInfo(
                edge_id=row['edge_id'],
                parent_id=row['parent_id'],
                parent_name=row['parent_name'],
                is_primary=bool(row['is_primary']),
                display_order=row['display_order'],
            )
            for row in rows
        ]

    def get_sibling_edges(
        self,
        parent_id: int,
        exclude_edge_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return all outgoing edges of ``parent_id``, joined with child name.

        Used by the Stage 1 Hamilton allocator
        (``HierarchyMixin.allocate_questions_hamilton``) to enumerate the
        children that should receive a portion of the parent's question
        budget. Lives in ``EdgesMixin`` because it is a pure edge query;
        the allocator composes it from ``hierarchy.py`` via ``self.*``.

        Each returned dict has the keys:

        - ``edge_id``        — ``subject_edges.id``
        - ``child_id``       — ``subject_edges.child_id``
        - ``child_name``     — ``subject_nodes.name`` for the child
        - ``relative_weight`` — float | None (NULL when uncategorized)
        - ``is_anchor``      — bool
        - ``weight_source``  — str (one of the enum values)
        - ``sort_order``     — alias for ``subject_edges.display_order``;
          named ``sort_order`` for parity with the allocator's API copy.

        Ordering is deterministic: ``display_order ASC, id ASC``. When
        ``exclude_edge_id`` is provided, that edge is omitted from the
        result (used by callers that want "all my siblings except me").

        The query reads only ``status='active'`` children — orphaned or
        soft-deleted children should not consume question budget.
        """
        if exclude_edge_id is None:
            rows = self.fetchall(
                """
                SELECT
                    se.id              AS edge_id,
                    se.child_id        AS child_id,
                    sn.name            AS child_name,
                    se.relative_weight AS relative_weight,
                    se.is_anchor       AS is_anchor,
                    se.weight_source   AS weight_source,
                    se.display_order   AS sort_order
                FROM subject_edges se
                JOIN subject_nodes sn ON sn.id = se.child_id
                WHERE se.parent_id = ?
                  AND sn.status = 'active'
                ORDER BY se.display_order ASC, se.id ASC
                """,
                (parent_id,),
            )
        else:
            rows = self.fetchall(
                """
                SELECT
                    se.id              AS edge_id,
                    se.child_id        AS child_id,
                    sn.name            AS child_name,
                    se.relative_weight AS relative_weight,
                    se.is_anchor       AS is_anchor,
                    se.weight_source   AS weight_source,
                    se.display_order   AS sort_order
                FROM subject_edges se
                JOIN subject_nodes sn ON sn.id = se.child_id
                WHERE se.parent_id = ?
                  AND se.id != ?
                  AND sn.status = 'active'
                ORDER BY se.display_order ASC, se.id ASC
                """,
                (parent_id, exclude_edge_id),
            )

        return [
            {
                'edge_id': row['edge_id'],
                'child_id': row['child_id'],
                'child_name': row['child_name'],
                'relative_weight': (
                    float(row['relative_weight'])
                    if row['relative_weight'] is not None
                    else None
                ),
                'is_anchor': bool(row['is_anchor']),
                'weight_source': row['weight_source'],
                'sort_order': row['sort_order'],
            }
            for row in rows
        ]

    def get_paths_to_root(self, child_id: int) -> List[List[int]]:
        """Return every distinct root-to-``child_id`` path.

        Each path is a list of node IDs starting at a root (a node with
        no parent edges) and ending at ``child_id``. The primary path
        — the one assembled by following ``is_primary=TRUE`` edges
        upward — is returned first; remaining paths follow in
        deterministic order (sorted by their tuple representation).

        Implementation: a recursive CTE walks edges *upward* from
        ``child_id``, accumulating the path as a comma-separated string
        (SQLite has no array type). Roots are detected by the absence
        of any incoming edge for the current node. The CTE uses
        ``UNION`` (not ``UNION ALL``) defensively so accidental data
        cycles do not produce infinite recursion.
        """
        # Walk upward: at each step, prepend the parent to the path.
        # We only emit a row when the current node has no further
        # parents (i.e., it's a root in the polyhierarchy graph).
        rows = self.fetchall(
            """
            WITH RECURSIVE upward(node_id, path) AS (
                SELECT :child_id, CAST(:child_id AS TEXT)
                UNION
                SELECT se.parent_id, se.parent_id || ',' || u.path
                FROM subject_edges se
                JOIN upward u ON se.child_id = u.node_id
            )
            SELECT path FROM upward
            WHERE NOT EXISTS (
                SELECT 1 FROM subject_edges se WHERE se.child_id = upward.node_id
            )
            """,
            {"child_id": child_id},
        )
        all_paths = [
            [int(piece) for piece in row['path'].split(',') if piece]
            for row in rows
        ]

        # Compute the primary path: walk up via is_primary edges only.
        primary_path = self._primary_path_to_root(child_id)

        # Order: primary path first (if it appears in all_paths), then
        # the rest in deterministic order.
        primary_tuple = tuple(primary_path) if primary_path else None
        rest = [p for p in all_paths if tuple(p) != primary_tuple]
        rest.sort()

        if primary_tuple is not None and any(tuple(p) == primary_tuple for p in all_paths):
            return [list(primary_tuple)] + rest
        # No primary edges anywhere on the chain (orphaned child) —
        # just return the deterministic order.
        return sorted(all_paths)

    def _primary_path_to_root(self, child_id: int) -> List[int]:
        """Walk upward via ``is_primary=TRUE`` edges only.

        Returns the canonical breadcrumb path. If a node has no primary
        parent edge, traversal stops there (so an orphaned child
        returns ``[child_id]``).
        """
        path: List[int] = [child_id]
        seen: set[int] = {child_id}
        cursor_node = child_id
        # Bound the loop defensively to avoid pathological cycles in
        # case the cycle-prevention check was bypassed.
        for _ in range(1024):
            row = self.fetchone(
                "SELECT parent_id FROM subject_edges "
                "WHERE child_id = ? AND is_primary = TRUE LIMIT 1",
                (cursor_node,),
            )
            if row is None:
                break
            parent_id = row['parent_id']
            if parent_id in seen:
                # Defensive — shouldn't happen if cycle prevention is
                # working, but better to break than to loop forever.
                break
            path.insert(0, parent_id)
            seen.add(parent_id)
            cursor_node = parent_id
        return path

    # ---------------------------------------------------------------- Stage 3: per-edge anchor + source

    def set_edge_anchor(
        self,
        edge_id: int,
        is_anchor: bool,
        reason: str = '',
    ) -> tuple['SubjectEdge', Optional[int]]:
        """Toggle ``subject_edges.is_anchor`` and write a history row.

        Stage 3 of the Hierarchical Weight Allocation Implementation
        Plan (``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``).
        Anchoring an edge marks it as "exempt from sibling rebalance" —
        the value is preserved byte-identical when
        :meth:`HierarchyMixin.rebalance_sibling_edge_weights` runs over
        siblings under the same parent. Anchor scope is **per edge**:
        anchoring (Cardio → Hypertension) does NOT anchor any other
        edge into Hypertension (e.g. (Pregnancy → Hypertension)).

        The anchor toggle is metadata about the edge, not a value
        change, so the history row records ``weight_value`` =
        ``previous_weight`` = the current edge weight (or NULL when
        the edge has none yet). The discriminating signal is
        ``change_type``:

        - ``'anchor_set'`` when ``is_anchor=True``
        - ``'anchor_cleared'`` when ``is_anchor=False``

        Both ``edge_id`` and ``subject_node_id`` (= the edge's
        ``child_id``) are populated in the history row so per-parent
        history queries (``WHERE edge_id = ?``) and per-node history
        queries (``WHERE subject_node_id = ?``) both surface the event.

        Args:
            edge_id: ``subject_edges.id`` to mutate.
            is_anchor: New value for the flag.
            reason: Optional audit-trail reason. Empty string normalizes
                to a default ``'Anchor set'`` / ``'Anchor cleared'``.

        Returns:
            ``(edge, weight_history_id)``: a freshly-fetched
            :class:`SubjectEdge` plus the ``subject_node_weights.id``
            of the row that was just written (or ``None`` if the
            history table is unavailable in this database — defensive
            for very early test setups).

        Raises:
            SubjectNodeError: If ``edge_id`` does not exist.
        """
        edge_row = self.fetchone(
            "SELECT id, parent_id, child_id, relative_weight, is_anchor "
            "FROM subject_edges WHERE id = ?",
            (edge_id,),
        )
        if edge_row is None:
            raise SubjectNodeError(f"Subject edge {edge_id} not found")

        child_id = edge_row['child_id']
        current_weight = (
            float(edge_row['relative_weight'])
            if edge_row['relative_weight'] is not None
            else None
        )
        change_type = 'anchor_set' if is_anchor else 'anchor_cleared'
        default_reason = 'Anchor set' if is_anchor else 'Anchor cleared'

        history_id: Optional[int] = None
        with self.transaction():
            self.execute(
                "UPDATE subject_edges "
                "SET is_anchor = ?, "
                "    updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (bool(is_anchor), edge_id),
            )

            # Anchoring does not change the weight value — record the
            # current value as both ``previous_weight`` and
            # ``weight_value`` so the audit log is consistent. The
            # ``subject_node_weights.weight_value`` column is NOT NULL
            # with a CHECK constraint [0,100]; when the edge has no
            # weight yet we store 0 so the row can land without
            # violating the constraint, while ``previous_weight`` (a
            # nullable column) honestly reports the absence of prior
            # value as NULL.
            stored_value = current_weight if current_weight is not None else 0.0
            try:
                cursor = self.execute(
                    """
                    INSERT INTO subject_node_weights (
                        subject_node_id, weight_value,
                        edited_by, edited_reason,
                        previous_weight, change_type, affected_siblings,
                        edge_id
                    ) VALUES (?, ?, 'user', ?, ?, ?, '[]', ?)
                    """,
                    (
                        child_id,
                        stored_value,
                        reason if reason else default_reason,
                        current_weight,
                        change_type,
                        edge_id,
                    ),
                )
                history_id = cursor.lastrowid
            except Exception:
                # Phase 2 tables may not exist in extremely early test
                # setups. Per the conventions established by
                # ``HierarchyMixin.update_edge_relative_weight``, we
                # swallow the history failure to keep the edge mutation
                # itself authoritative.
                history_id = None

        row = self.fetchone(
            "SELECT * FROM subject_edges WHERE id = ?", (edge_id,)
        )
        edge = SubjectEdge.from_db_row(row)
        if edge is None:
            raise SubjectNodeError(
                f"Failed to fetch updated edge id={edge_id}"
            )
        return edge, history_id

    def set_edge_weight_source(
        self,
        edge_id: int,
        source: str,
    ) -> None:
        """Update ``subject_edges.weight_source`` for a single edge.

        Stage 3 of the Hierarchical Weight Allocation Implementation
        Plan. This is a pure metadata setter: ``weight_source`` records
        *where* the weight value came from (official outline, user
        explicit input, system-derived, etc.) and does not change the
        value itself. Since this is metadata, no
        ``subject_node_weights`` history row is written —
        ``set_edge_anchor`` and ``update_edge_relative_weight`` cover
        the audit-trail surface for events that materially affect
        rebalance / allocation behavior.

        The check constraint on ``subject_edges.weight_source`` already
        rejects unknown values, but we validate against
        :attr:`SubjectEdge.VALID_WEIGHT_SOURCES` here so callers get a
        typed :class:`WeightValidationError` with a clear message
        instead of an opaque SQLite ``IntegrityError``.

        Args:
            edge_id: ``subject_edges.id`` to mutate.
            source: One of ``'official'``, ``'derived'``,
                ``'user_estimate'``, ``'user_defined'``,
                ``'user_explicit'``.

        Raises:
            WeightValidationError: If ``source`` is not a valid enum
                value.
            SubjectNodeError: If ``edge_id`` does not exist.
        """
        if source not in SubjectEdge.VALID_WEIGHT_SOURCES:
            raise WeightValidationError(
                f"Invalid weight_source {source!r}; expected one of "
                f"{sorted(SubjectEdge.VALID_WEIGHT_SOURCES)}"
            )

        edge_row = self.fetchone(
            "SELECT id FROM subject_edges WHERE id = ?", (edge_id,)
        )
        if edge_row is None:
            raise SubjectNodeError(f"Subject edge {edge_id} not found")

        with self.transaction():
            self.execute(
                "UPDATE subject_edges "
                "SET weight_source = ?, "
                "    updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (source, edge_id),
            )

    def get_edges_for_child(self, child_id: int) -> List[Dict[str, Any]]:
        """Return every edge whose ``child_id`` matches, joined with parent name.

        Stage 3 of the Hierarchical Weight Allocation Implementation
        Plan. Fuels Stage 6's "switch parent" UX: when a node has
        multiple parent edges, the weight editor needs to enumerate
        them so the user can choose which parent-context to edit.

        Result is ordered ``is_primary DESC, parent_id ASC`` so the
        canonical primary edge always leads. Each entry contains the
        full per-edge weight metadata required by the editor
        (``relative_weight``, ``is_anchor``, ``weight_source``) plus
        the parent's display name from the join.

        Args:
            child_id: ``subject_nodes.id`` of the child.

        Returns:
            List of dicts with keys ``edge_id``, ``parent_id``,
            ``parent_name``, ``child_id``, ``dimension_id``,
            ``relative_weight``, ``is_anchor``, ``weight_source``,
            ``sort_order``, ``is_primary``. Empty list when the child
            has no parents.
        """
        rows = self.fetchall(
            """
            SELECT
                se.id              AS edge_id,
                se.parent_id       AS parent_id,
                sn.name            AS parent_name,
                se.child_id        AS child_id,
                sn.dimension_id    AS dimension_id,
                se.relative_weight AS relative_weight,
                se.is_anchor       AS is_anchor,
                se.weight_source   AS weight_source,
                se.display_order   AS sort_order,
                se.is_primary      AS is_primary
            FROM subject_edges se
            JOIN subject_nodes sn ON sn.id = se.parent_id
            WHERE se.child_id = ?
            ORDER BY se.is_primary DESC, se.parent_id ASC
            """,
            (child_id,),
        )
        return [
            {
                'edge_id': row['edge_id'],
                'parent_id': row['parent_id'],
                'parent_name': row['parent_name'],
                'child_id': row['child_id'],
                'dimension_id': row['dimension_id'],
                'relative_weight': (
                    float(row['relative_weight'])
                    if row['relative_weight'] is not None
                    else None
                ),
                'is_anchor': bool(row['is_anchor']),
                'weight_source': row['weight_source'],
                'sort_order': row['sort_order'],
                'is_primary': bool(row['is_primary']),
            }
            for row in rows
        ]
