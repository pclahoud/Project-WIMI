"""Reading the delete journal back: restore a delete batch (issue #37).

Deleting a subject has been a *soft* delete since #15 — the row stays,
``status`` flips to ``'archived'``, and every reversible side effect is
journalled under one **batch id** (m018). Nothing ever read that journal.
So the archived rows persisted forever, invisibly, with no way to get them
back: the worst of both worlds, as #37 puts it. This module is the read
side.

**Restore is the undo of an operation, not of a row.** A single delete can
archive a subtree, strip the edges that attached surviving children to it,
clear the parent context off entry mappings and hide semantic relations
(#14 decision 9). No per-row flag describes that, so restore acts on the
batch and replays its journal.

One planner, one apply
----------------------
:meth:`plan_batch_restore` decides everything; :meth:`restore_subject_delete_batch`
executes its output and re-derives nothing. The same split as
``plan_subject_delete`` / ``delete_subject_subtree`` (#15) and
``plan_subject_import`` / ``apply_subject_import`` (#67), and for the same
reason: the panel's preview and the mutation cannot disagree because there
is only one of them.

The owner's two decisions (2026-09-14)
-------------------------------------
**Membership comes from ``subject_delete_batch_items``, never from
``subject_nodes.deleted_batch_id``.** A node can be deleted, restored and
deleted again, or deleted a second time directly; #15 opens a new batch and
re-stamps the column, so the node's *current* batch is the later one while
the journal still lists it under the first. That is correct and must not be
guarded against in #15 — the most recent delete is the more recent
statement of intent.

**So restoring an older batch must not resurrect a node deleted again
afterwards, and must say so.** Each member is restored only if its current
stamp still names this batch; the rest are reported with a reason. *"2 of 3
subjects restored. 1 was deleted again later and stays archived."* A
partial restore that looks like a complete one is the only genuinely wrong
outcome here.

Which batches are listed is a different question, and uses the stamp
-------------------------------------------------------------------
:meth:`list_archived_batches` drives off ``subject_nodes.deleted_batch_id``,
which looks like a violation of the rule above and is not. The two reads
answer different questions:

* *What does restoring this batch cover?* — the journal, because the journal
  is the record of the operation.
* *Is there anything left to restore?* — the stamp, because it is the only
  thing that changes when a restore succeeds.

That second point is why **no migration is needed to know a batch was
already restored.** Restore clears ``deleted_batch_id`` on every node it
un-archives, so a fully-resolved batch has no claimants left and drops out
of the listing by itself. A batch whose every member was deleted again
drops out too, which is also right: the later batch owns those nodes and
restoring this one would do nothing. A ``restored_at`` column would have
been a second source of truth for a fact the data already carries.

What the journal gives us, verified rather than assumed
------------------------------------------------------
``edge_removed`` carries a full snapshot (``is_primary``, ``display_order``,
``is_anchor``, ``relative_weight``, ``weight_source``) so an edge rebuilds
**byte-identical** rather than with defaults, plus ``promoted`` — because a
merely-detached shared child gets its edge back and one the user chose to
promote deliberately does not. Whether the child had another parent is only
knowable at delete time, which is why #15 records it.

Four hazards this has to handle, none of them in #37's original scope
--------------------------------------------------------------------
1. **A restored node may have no active parent, and #260 made that safe.**
   It used to be fatal. ``hierarchy.py``'s root predicate was "no incoming
   edge at all", with no status filter on the parent, so a node holding an
   edge from an *archived* parent was neither a root nor anybody's child —
   invisible. Reachable only through restore: delete a child (its edge
   survives, because the parent is still active), then delete the parent (the
   edge survives again, because the child is not *surviving*), then restore
   the child.

   The first version of this module refused that restore. **#260 fixed the
   predicate instead**, so all three root-finding queries now agree that a
   root is a node with no incoming edge *from an active parent* and the
   invisible state is unreachable by construction. What was a refusal is now
   a **note** on the plan (``will_appear_at_top_level``): the subject comes
   back at the top level, and restoring the parent's deletion moves it back
   underneath **by itself**, because the edge was never removed. That last
   part is why the other option considered — delete the dangling edge, the
   way #15 does at delete time — was rejected: it would have lost the
   relationship for good.
2. **``subject_edges`` is ``UNIQUE(parent_id, child_id)``.** A student may
   have re-added an edge the delete removed. The plan reports it skipped and
   keeps theirs, rather than raising from inside an INSERT.
3. **``primary_parent_cleared`` must not clobber a newer choice.** The
   journal holds the value that was nulled, but the entry may have been
   re-tagged since. Restored only where the column is *still* NULL.
4. **A batch belonging to a dimension archive is not independently
   restorable.** One dimension archive produces N subject batches (m024), so
   restoring one alone puts active subjects inside an archived dimension —
   hazard 1 one level up. ``dimension_delete_batch_subjects`` makes such a
   batch *owned*, and Wave 2's dimension restore is the way to bring it
   back.

Purge is #38 and is deliberately elsewhere: restore is non-destructive and
permanent deletion is not.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple

from ..exceptions import SubjectRestoreError

try:  # pragma: no cover - import shape mirrors the other domains
    from ..error_types import ErrorCategory
except Exception:  # pragma: no cover
    ErrorCategory = None  # type: ignore[assignment]


# Item types m018/m019 define. Named here so a typo in a query is a
# NameError at import rather than a silently empty result set.
_NODE_ARCHIVED = 'node_archived'
_EDGE_REMOVED = 'edge_removed'
_PRIMARY_CLEARED = 'primary_parent_cleared'
_RELATION_HIDDEN = 'relation_hidden'


class SubjectRestoreMixin:
    """Restore a subject delete batch, and list what is restorable.

    Composed into ``UserDatabase``. Like every domain mixin it imports no
    sibling and reaches cross-domain behaviour through ``self.*``.
    """

    # ------------------------------------------------------------------
    # Internal: journal reads
    # ------------------------------------------------------------------
    def _batch_row(self, batch_id: str) -> Optional[Dict[str, Any]]:
        return self.fetchone(
            "SELECT id, root_node_id, root_node_name, promote_children, "
            "       created_at "
            "FROM subject_delete_batches WHERE id = ?",
            (batch_id,),
        )

    def _batch_items(self, batch_id: str, item_type: str) -> List[Dict[str, Any]]:
        """Journal rows of one kind, oldest first, payload already decoded."""
        rows = self.fetchall(
            "SELECT id, item_type, subject_node_id, parent_id, "
            "       entry_subject_mapping_id, payload "
            "FROM subject_delete_batch_items "
            "WHERE batch_id = ? AND item_type = ? "
            "ORDER BY id ASC",
            (batch_id, item_type),
        )
        for row in rows:
            try:
                row['payload'] = json.loads(row['payload'] or '{}')
            except (TypeError, ValueError):
                # A malformed payload must not take the whole restore down;
                # the per-item defaults below are all recoverable, and the
                # alternative is a batch nobody can ever restore.
                row['payload'] = {}
        return rows

    def _owning_dimension_batch(self, batch_id: str) -> Optional[str]:
        """The dimension archive this subject batch belongs to, if any.

        Hazard 4. ``dimension_delete_batch_subjects`` (m024) is the explicit
        relation -- deliberately not a timestamp correlation, because #37
        has to restore exactly the right set and "the batches created in the
        same second" is not a relation.
        """
        row = self.fetchone(
            "SELECT dimension_batch_id FROM dimension_delete_batch_subjects "
            "WHERE subject_batch_id = ?",
            (batch_id,),
        )
        return row['dimension_batch_id'] if row else None

    def _node_names(self, ids) -> Dict[int, str]:
        ids = [int(i) for i in dict.fromkeys(i for i in ids if i is not None)]
        if not ids:
            return {}
        placeholders = ','.join('?' * len(ids))
        return {
            row['id']: row['name']
            for row in self.fetchall(
                f"SELECT id, name FROM subject_nodes WHERE id IN ({placeholders})",
                tuple(ids),
            )
        }

    # ------------------------------------------------------------------
    # Planner
    # ------------------------------------------------------------------
    def plan_batch_restore(
        self,
        batch_id: str,
        *,
        as_part_of_dimension_batch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Work out exactly what restoring ``batch_id`` would do. Read-only.

        Single source of truth, consumed by the Archived panel's preview and
        by :meth:`restore_subject_delete_batch`. Returns a plan whose
        ``blocked`` list is empty when the restore can proceed; every entry
        in it is a sentence naming what to do instead.

        Per-item ``skip_reason`` values are *not* blocking -- they are the
        owner's "report what it skipped" decision, and a restore with skips
        still runs. The distinction matters: a skipped node leaves the rest
        of the batch coherent, while a blocking error means running would
        produce a state the tree editor cannot render.

        ``as_part_of_dimension_batch`` is how Wave 2 restores the trees a
        dimension archive took with it. A batch owned by a dimension event is
        refused on its own (hazard 4) -- restoring one axis of a multi-axis
        archive leaves active subjects inside an archived dimension. Passing
        the owning batch id says "the dimension is coming back in the same
        transaction", which is the one context where it is safe. It is
        deliberately not a boolean: a caller has to name *which* dimension
        event it is acting for, so passing it by mistake cannot silently
        disable the guard for an unrelated batch.
        """
        batch = self._batch_row(batch_id)
        if batch is None:
            return {
                'batch_id': batch_id,
                'kind': 'subject',
                'exists': False,
                'blocked': [{
                    'code': 'unknown_batch',
                    'message': (
                        f"No delete batch {batch_id!r} is journalled. It may "
                        f"have been purged."
                    ),
                }],
                'restorable': False,
                'notes': [],
                'nodes': [], 'edges': [], 'entry_mappings': [], 'relations': [],
                'counts': {
                    'nodes_to_restore': 0, 'nodes_skipped': 0,
                    'edges_to_restore': 0, 'edges_skipped': 0,
                    'entry_mappings_to_restore': 0, 'entry_mappings_skipped': 0,
                    'relations_to_restore': 0, 'relations_skipped': 0,
                },
            }

        blocked: List[Dict[str, Any]] = []

        owning = self._owning_dimension_batch(batch_id)
        if owning is not None and owning != as_part_of_dimension_batch:
            # Hazard 4. Restoring one tree of a multi-axis archive would put
            # active subjects inside an archived dimension.
            dim = self.fetchone(
                "SELECT dimension_name FROM dimension_delete_batches WHERE id = ?",
                (owning,),
            )
            dim_name = (dim or {}).get('dimension_name') or 'a dimension'
            blocked.append({
                'code': 'owned_by_dimension_batch',
                'dimension_batch_id': owning,
                'message': (
                    f"This tree was archived as part of the dimension "
                    f"“{dim_name}”. Restore that dimension to bring "
                    f"its trees back together — restoring this one alone "
                    f"would leave its subjects inside an archived dimension, "
                    f"where nothing can reach them."
                ),
            })

        # ---- nodes -------------------------------------------------------
        node_items = self._batch_items(batch_id, _NODE_ARCHIVED)
        node_ids = [row['subject_node_id'] for row in node_items]
        current = {
            row['id']: row
            for row in self.fetchall(
                "SELECT id, name, status, deleted_batch_id, dimension_id "
                "FROM subject_nodes WHERE id IN "
                f"({','.join('?' * len(node_ids)) or 'NULL'})",
                tuple(node_ids),
            )
        } if node_ids else {}

        nodes: List[Dict[str, Any]] = []
        restore_ids: Set[int] = set()
        for item in node_items:
            nid = item['subject_node_id']
            row = current.get(nid)
            entry: Dict[str, Any] = {
                'id': nid,
                'name': (row or {}).get('name'),
                'previous_status': item['payload'].get('previous_status') or 'active',
                'restore': False,
                'skip_reason': None,
                'skip_detail': None,
            }
            if row is None:
                entry['skip_reason'] = 'node_gone'
                entry['skip_detail'] = 'the row no longer exists'
            elif row['status'] == 'active':
                entry['skip_reason'] = 'already_active'
                entry['skip_detail'] = 'it is already active'
            elif row['deleted_batch_id'] != batch_id:
                # The owner's decision, and the reason membership is read
                # from the journal: the later delete wins.
                entry['skip_reason'] = 'deleted_again'
                entry['skip_detail'] = 'it was deleted again later and stays archived'
            else:
                entry['restore'] = True
                restore_ids.add(nid)
            nodes.append(entry)

        if not restore_ids and not blocked:
            blocked.append({
                'code': 'nothing_to_restore',
                'message': (
                    "Nothing in this deletion can be restored: every subject "
                    "in it was either deleted again afterwards or is already "
                    "active."
                ),
            })

        # ---- edges -------------------------------------------------------
        edge_items = self._batch_items(batch_id, _EDGE_REMOVED)
        edges: List[Dict[str, Any]] = []
        planned_edges: List[Tuple[int, int]] = []
        for item in edge_items:
            child_id = item['subject_node_id']
            parent_id = item['parent_id']
            payload = item['payload']
            entry = {
                'parent_id': parent_id,
                'child_id': child_id,
                'is_primary': bool(payload.get('is_primary')),
                'display_order': payload.get('display_order') or 0,
                'is_anchor': bool(payload.get('is_anchor')),
                'relative_weight': payload.get('relative_weight'),
                'weight_source': payload.get('weight_source') or 'derived',
                'restore': False,
                'skip_reason': None,
                'skip_detail': None,
            }
            if payload.get('promoted'):
                # #37, explicitly: promotion created a fact the user chose.
                # Re-attaching it behind their back would surprise.
                entry['skip_reason'] = 'promoted'
                entry['skip_detail'] = (
                    'it was promoted to the top level, which was a choice; '
                    'restore does not undo it'
                )
            elif self.fetchone(
                "SELECT 1 FROM subject_edges WHERE parent_id = ? AND child_id = ?",
                (parent_id, child_id),
            ) is not None:
                # Hazard 2. UNIQUE(parent_id, child_id) -- keep theirs.
                entry['skip_reason'] = 'edge_exists'
                entry['skip_detail'] = 'that link has since been re-created by hand'
            else:
                entry['restore'] = True
                planned_edges.append((parent_id, child_id))
            edges.append(entry)

        # ---- hazard 1: would any restored node be invisible? -------------
        # A node with at least one incoming edge whose every parent is
        # archived is neither a root (hierarchy.py's predicate is "no
        # incoming edge at all") nor anybody's child. See #260.
        invisible: List[Dict[str, Any]] = []
        for nid in sorted(restore_ids):
            incoming = self.fetchall(
                "SELECT se.parent_id, p.name AS parent_name, p.status AS parent_status "
                "FROM subject_edges se "
                "JOIN subject_nodes p ON p.id = se.parent_id "
                "WHERE se.child_id = ?",
                (nid,),
            )
            incoming_parents = [
                (row['parent_id'], row['parent_name'], row['parent_status'])
                for row in incoming
            ]
            # Edges this restore will re-create count as incoming too, and
            # their parents are normally archived-in-this-batch.
            for parent_id, child_id in planned_edges:
                if child_id == nid:
                    prow = self.fetchone(
                        "SELECT id, name, status FROM subject_nodes WHERE id = ?",
                        (parent_id,),
                    )
                    if prow is not None:
                        incoming_parents.append(
                            (prow['id'], prow['name'], prow['status'])
                        )
            if not incoming_parents:
                continue  # a legitimate top-level root
            reachable = any(
                status == 'active' or pid in restore_ids
                for pid, _name, status in incoming_parents
            )
            if not reachable:
                invisible.append({
                    'id': nid,
                    'name': current.get(nid, {}).get('name'),
                    'parents': [
                        {'id': pid, 'name': name}
                        for pid, name, _status in incoming_parents
                    ],
                })

        notes: List[Dict[str, Any]] = []
        if invisible:
            names = ', '.join(
                f"“{p['name']}”"
                for item in invisible for p in item['parents']
            )
            subjects = ', '.join(f"“{i['name']}”" for i in invisible)
            # A note, not a refusal, since #260 aligned the root predicates:
            # such a node now renders at the top level instead of vanishing.
            # The edge is deliberately left in place, which is what makes the
            # last sentence true -- restoring the parent re-attaches it with no
            # journal replay at all.
            notes.append({
                'code': 'will_appear_at_top_level',
                'subjects': invisible,
                'message': (
                    f"{subjects} comes back at the top level for now, because "
                    f"its parent ({names}) is still archived. Restore that "
                    f"deletion too and it moves back underneath on its own — "
                    f"the link was never removed."
                ),
            })

        # ---- entry mappings ---------------------------------------------
        mapping_items = self._batch_items(batch_id, _PRIMARY_CLEARED)
        entry_mappings: List[Dict[str, Any]] = []
        for item in mapping_items:
            mapping_id = item['entry_subject_mapping_id']
            row = self.fetchone(
                "SELECT id, subject_node_id, primary_parent_id "
                "FROM entry_subject_mappings WHERE id = ?",
                (mapping_id,),
            )
            entry = {
                'mapping_id': mapping_id,
                'subject_node_id': item['subject_node_id'],
                'primary_parent_id': item['parent_id'],
                'restore': False,
                'skip_reason': None,
                'skip_detail': None,
            }
            if row is None:
                entry['skip_reason'] = 'mapping_gone'
                entry['skip_detail'] = 'the entry no longer carries that subject'
            elif row['primary_parent_id'] is not None:
                # Hazard 3. A later re-tag is a deliberate choice.
                entry['skip_reason'] = 'mapping_reassigned'
                entry['skip_detail'] = (
                    'the entry has been given a parent context since, which '
                    'restore does not overwrite'
                )
            else:
                entry['restore'] = True
            entry_mappings.append(entry)

        # ---- relations ---------------------------------------------------
        relation_items = self._batch_items(batch_id, _RELATION_HIDDEN)
        relations: List[Dict[str, Any]] = []
        for item in relation_items:
            payload = item['payload']
            relation_id = payload.get('relation_id')
            row = self.fetchone(
                "SELECT id, hidden_batch_id FROM subject_relations WHERE id = ?",
                (relation_id,),
            ) if relation_id is not None else None
            entry = {
                'relation_id': relation_id,
                'from_subject_id': item['subject_node_id'],
                'to_subject_id': item['parent_id'],
                'restore': False,
                'skip_reason': None,
                'skip_detail': None,
            }
            if row is None:
                entry['skip_reason'] = 'relation_gone'
                entry['skip_detail'] = 'the related-topic link no longer exists'
            elif row['hidden_batch_id'] != batch_id:
                entry['skip_reason'] = 'relation_rehidden'
                entry['skip_detail'] = 'it was hidden again by a later deletion'
            else:
                entry['restore'] = True
            relations.append(entry)

        def _count(items, want_restore: bool) -> int:
            return sum(1 for i in items if bool(i['restore']) is want_restore)

        return {
            'batch_id': batch_id,
            'kind': 'subject',
            'exists': True,
            'root_node_id': batch['root_node_id'],
            'root_node_name': batch['root_node_name'],
            'promote_children': bool(batch['promote_children']),
            'deleted_at': batch['created_at'],
            'owned_by_dimension_batch': owning,
            'blocked': blocked,
            'notes': notes,
            'restorable': not blocked,
            'nodes': nodes,
            'edges': edges,
            'entry_mappings': entry_mappings,
            'relations': relations,
            'counts': {
                'nodes_to_restore': _count(nodes, True),
                'nodes_skipped': _count(nodes, False),
                'edges_to_restore': _count(edges, True),
                'edges_skipped': _count(edges, False),
                'entry_mappings_to_restore': _count(entry_mappings, True),
                'entry_mappings_skipped': _count(entry_mappings, False),
                'relations_to_restore': _count(relations, True),
                'relations_skipped': _count(relations, False),
            },
        }

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    def restore_subject_delete_batch(
        self,
        batch_id: str,
        *,
        as_part_of_dimension_batch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Undo the delete ``batch_id`` recorded. Executes the plan verbatim.

        Raises :class:`SubjectRestoreError` when the plan is blocked, so a
        refused restore reaches the bridge as ``success=false`` with a
        sentence rather than as a success carrying a quiet complaint. That
        distinction is the whole of #240's lesson: a call that reports
        ``0 restored`` and ``success`` is indistinguishable from one that
        worked.

        Everything runs in one transaction. A half-restored batch -- nodes
        active but their edges missing -- is exactly the incoherent shape
        this is supposed to unwind.

        Returns the plan with ``restored=True`` and a ``summary`` sentence
        suitable for a toast.
        """
        # The apply re-calls the planner rather than taking a plan argument, so
        # the ownership release has to travel with it -- otherwise a dimension
        # restore plans its members as restorable and then refuses them one
        # frame down. ``as_part_of_dimension_batch`` is threaded rather than
        # dropped for exactly that reason.
        plan = self.plan_batch_restore(
            batch_id, as_part_of_dimension_batch=as_part_of_dimension_batch)
        if plan['blocked']:
            raise SubjectRestoreError(
                ' '.join(item['message'] for item in plan['blocked'])
            )

        with self.transaction():
            for node in plan['nodes']:
                if not node['restore']:
                    continue
                # ``previous_status`` comes from the journal rather than a
                # hardcoded 'active': #15 records what the row held, and a
                # future status value would otherwise be flattened here.
                self.execute(
                    "UPDATE subject_nodes "
                    "SET status = ?, deleted_batch_id = NULL, "
                    "    updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (node['previous_status'], node['id']),
                )

            for edge in plan['edges']:
                if not edge['restore']:
                    continue
                # Rebuilt from the snapshot, not with defaults, so a
                # restored edge carries the weight and provenance it had.
                self.execute(
                    "INSERT INTO subject_edges "
                    "(parent_id, child_id, is_primary, display_order, "
                    " is_anchor, relative_weight, weight_source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        edge['parent_id'], edge['child_id'],
                        1 if edge['is_primary'] else 0,
                        edge['display_order'],
                        1 if edge['is_anchor'] else 0,
                        edge['relative_weight'],
                        edge['weight_source'],
                    ),
                )

            for mapping in plan['entry_mappings']:
                if not mapping['restore']:
                    continue
                # Guarded on IS NULL a second time: the planner checked, but
                # the check and the write are what must agree, and this costs
                # nothing.
                self.execute(
                    "UPDATE entry_subject_mappings SET primary_parent_id = ? "
                    "WHERE id = ? AND primary_parent_id IS NULL",
                    (mapping['primary_parent_id'], mapping['mapping_id']),
                )

            for relation in plan['relations']:
                if not relation['restore']:
                    continue
                self.execute(
                    "UPDATE subject_relations SET hidden_batch_id = NULL "
                    "WHERE id = ? AND hidden_batch_id = ?",
                    (relation['relation_id'], batch_id),
                )

        result = dict(plan)
        result['restored'] = True
        result['summary'] = self._restore_summary(plan)

        if self.error_logger and ErrorCategory is not None:
            counts = plan['counts']
            self.error_logger.info(
                f"Restored delete batch {batch_id}: "
                f"{counts['nodes_to_restore']} subjects, "
                f"{counts['edges_to_restore']} edges, "
                f"{counts['entry_mappings_to_restore']} entry contexts, "
                f"{counts['relations_to_restore']} relations; "
                f"{counts['nodes_skipped']} subjects skipped",
                category=ErrorCategory.DATABASE,
            )
        return result

    @staticmethod
    def _restore_summary(plan: Dict[str, Any]) -> str:
        """One sentence for the panel, naming skips rather than hiding them.

        The owner's decision is that a partial restore must not read as a
        complete one, so the skipped count is in the same sentence as the
        restored count and carries its reason.
        """
        counts = plan['counts']
        restored = counts['nodes_to_restore']
        skipped = counts['nodes_skipped']
        total = restored + skipped
        noun = 'subject' if restored == 1 else 'subjects'

        if not skipped:
            return f"Restored {restored} {noun}."

        reasons: Dict[str, int] = {}
        for node in plan['nodes']:
            if not node['restore'] and node['skip_reason']:
                reasons[node['skip_detail'] or node['skip_reason']] = (
                    reasons.get(node['skip_detail'] or node['skip_reason'], 0) + 1
                )
        detail = '; '.join(
            f"{n} {'was' if n == 1 else 'were'} skipped because {why}"
            for why, n in sorted(reasons.items(), key=lambda kv: -kv[1])
        )
        return f"Restored {restored} of {total} subjects. {detail}."

    # ------------------------------------------------------------------
    # Listing (the Archived panel's data)
    # ------------------------------------------------------------------
    def list_archived_batches(
        self,
        exam_context_id: Optional[int] = None,
        *,
        include_dimension_owned: bool = False,
    ) -> List[Dict[str, Any]]:
        """Delete batches that still hold archived subjects, newest first.

        Driven off ``subject_nodes.deleted_batch_id`` rather than the journal
        -- see the module docstring on why that is not a violation of the
        owner's membership rule. A batch whose nodes have all been restored,
        or all been re-deleted into a later batch, has no claimants and is
        correctly absent.

        ``include_dimension_owned`` is ``False`` by default: a batch that
        belongs to a dimension archive is not independently restorable
        (hazard 4), and listing it beside the dimension's own entry would
        show one archive event as several. Wave 2 lists the dimension events
        themselves.

        Each entry carries ``parents`` -- what the deleted root was under --
        so the panel can render #37's *"was under Cardiovascular System,
        deleted 3 days ago"* without a second round trip.
        """
        # ``subject_nodes.exam_context`` holds the exam **name**, while
        # ``dimension_delete_batches.exam_id`` holds the id -- so the two
        # halves of this listing need *different* values for the same scope.
        # Resolving here means callers pass one thing (the id, which is what
        # the tree editor and the bridge have), rather than both.
        #
        # This was a real bug: the parameter is named ``exam_context_id`` and
        # was compared straight against ``n.exam_context``, matching nothing.
        # Wave 1's tests stored the id in that column, so they passed -- an
        # unrepresentative fixture hiding a scoping defect, caught only once a
        # bridge test built the row the way production does.
        params: List[Any] = []
        scope = ''
        if exam_context_id is not None:
            exam_config = self.get_exam_context_config(exam_context_id)
            if exam_config is None:
                return []
            scope = 'AND n.exam_context = ? '
            params.append(exam_config.exam_name)

        rows = self.fetchall(
            "SELECT b.id AS batch_id, b.root_node_id, b.root_node_name, "
            "       b.promote_children, b.created_at, "
            "       COUNT(n.id) AS node_count "
            "FROM subject_delete_batches b "
            "JOIN subject_nodes n ON n.deleted_batch_id = b.id "
            f"WHERE n.status = 'archived' {scope}"
            "GROUP BY b.id "
            "ORDER BY b.created_at DESC, b.id DESC",
            tuple(params),
        )

        out: List[Dict[str, Any]] = []
        for row in rows:
            owning = self._owning_dimension_batch(row['batch_id'])
            if owning is not None and not include_dimension_owned:
                continue
            parents = self.fetchall(
                "SELECT p.id, p.name, p.status "
                "FROM subject_edges se "
                "JOIN subject_nodes p ON p.id = se.parent_id "
                "WHERE se.child_id = ? "
                "ORDER BY se.display_order, p.name",
                (row['root_node_id'],),
            )
            out.append({
                'batch_id': row['batch_id'],
                'kind': 'subject',
                'root_node_id': row['root_node_id'],
                'root_node_name': row['root_node_name'],
                'promote_children': bool(row['promote_children']),
                'deleted_at': row['created_at'],
                'node_count': row['node_count'],
                'owned_by_dimension_batch': owning,
                'parents': [
                    {'id': p['id'], 'name': p['name'], 'status': p['status']}
                    for p in parents
                ],
            })

        out.extend(self._archived_dimension_entries(exam_context_id))
        # One list, newest first, across both kinds -- the panel shows archive
        # *events* and a dimension archive is one event, not N+1 of them.
        out.sort(key=lambda e: (e['deleted_at'] or '', e['batch_id']), reverse=True)
        return out

    def _archived_dimension_entries(
        self, exam_context_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Dimension archives that still hold an archived dimension row.

        Same derivation as the subject side: ``archived_batch_id`` is cleared
        by a restore, so a resolved event has no claimant and is absent. The
        join onto ``exam_dimensions`` is what filters on status, which keeps
        the #210 sweep satisfied without a marker.
        """
        params: List[Any] = []
        scope = ''
        if exam_context_id is not None:
            scope = 'AND b.exam_id = ? '
            params.append(exam_context_id)

        rows = self.fetchall(
            "SELECT b.id AS batch_id, b.dimension_id, b.dimension_name, "
            "       b.exam_id, b.created_at, "
            "       (SELECT COUNT(*) FROM dimension_delete_batch_subjects s "
            "        WHERE s.dimension_batch_id = b.id) AS tree_count "
            "FROM dimension_delete_batches b "
            "JOIN exam_dimensions d ON d.id = b.dimension_id "
            f"WHERE d.status = 'archived' AND d.archived_batch_id = b.id {scope}"
            "ORDER BY b.created_at DESC",
            tuple(params),
        )
        return [{
            'batch_id': row['batch_id'],
            'kind': 'dimension',
            'dimension_id': row['dimension_id'],
            'dimension_name': row['dimension_name'],
            'root_node_name': row['dimension_name'],
            'exam_id': row['exam_id'],
            'deleted_at': row['created_at'],
            'tree_count': row['tree_count'],
            'node_count': self.fetchone(
                "SELECT COUNT(*) AS c FROM subject_nodes n "
                "JOIN dimension_delete_batch_subjects s "
                "  ON s.subject_batch_id = n.deleted_batch_id "
                "WHERE s.dimension_batch_id = ? AND n.status = 'archived'",
                (row['batch_id'],),
            )['c'],
            'owned_by_dimension_batch': None,
            'parents': [],
        } for row in rows]

    # ------------------------------------------------------------------
    # Wave 2: dimension batches
    # ------------------------------------------------------------------
    def _dimension_batch_row(self, batch_id: str) -> Optional[Dict[str, Any]]:
        return self.fetchone(
            "SELECT id, dimension_id, dimension_name, exam_id, created_at "
            "FROM dimension_delete_batches WHERE id = ?",
            (batch_id,),
        )

    def plan_dimension_batch_restore(self, batch_id: str) -> Dict[str, Any]:
        """Work out what restoring a whole dimension archive would do. Read-only.

        A dimension archive is **one event and N subject batches** (m024): the
        dimension row was parked and each root in it went through
        :meth:`delete_subject_subtree`. So restoring it has to unpark the row
        *and* replay exactly the subject batches
        ``dimension_delete_batch_subjects`` names -- not each one
        independently, which is #37 comment #2826's point and why that table
        is an explicit relation rather than a timestamp correlation.

        Three things are specific to this level, all of them from m024's own
        parking scheme:

        **The name comes from the journal, never from the parked row.**
        Archiving rewrites ``name`` to ``name || ' (archived #' || id || ')'``
        because ``UNIQUE(exam_id, name)`` is checked against archived rows
        (#244). The ``INSERT INTO dimension_delete_batches`` runs *before*
        that UPDATE, so the journal holds the name the student chose.
        Recovering it by stripping the suffix off the parked spelling would be
        parsing our own formatting, and would produce the wrong answer for a
        dimension the student had genuinely named "System (archived #4)".

        **There is no slot reserved, so a fresh ``display_order`` is chosen.**
        Archiving parks it at ``-id``, and #211's reorder owns ``1..N`` over
        the active set, so restore appends rather than trying to reclaim a
        position that has since been filled.

        **A new dimension may have taken the name.** That is a plan error with
        a sentence, not an ``IntegrityError`` from inside the UPDATE -- the
        rule #66 2.2 states for the import's axis collisions, which this is
        the same shape as.
        """
        batch = self._dimension_batch_row(batch_id)
        if batch is None:
            return {
                'batch_id': batch_id,
                'kind': 'dimension',
                'exists': False,
                'blocked': [{
                    'code': 'unknown_batch',
                    'message': (
                        f"No dimension archive {batch_id!r} is journalled. It "
                        f"may have been purged."
                    ),
                }],
                'restorable': False,
                'subject_batches': [],
                'counts': {'subject_batches_to_restore': 0,
                           'subject_batches_skipped': 0,
                           'nodes_to_restore': 0},
            }

        blocked: List[Dict[str, Any]] = []
        dimension_id = batch['dimension_id']
        restored_name = batch['dimension_name']

        row = self.fetchone(
            "SELECT id, name, display_order, status, exam_id "
            "FROM exam_dimensions WHERE id = ? AND status = 'archived'",
            (dimension_id,),
        )
        if row is None:
            live = self.fetchone(
                "SELECT id, status FROM exam_dimensions WHERE id = ? "
                "AND status = 'active'",
                (dimension_id,),
            )
            blocked.append({
                'code': 'not_archived' if live else 'dimension_gone',
                'message': (
                    f"“{restored_name}” is not archived any more, so "
                    f"there is nothing to restore."
                    if live else
                    f"The dimension row for “{restored_name}” no "
                    f"longer exists."
                ),
            })

        # ``UNIQUE(exam_id, name)`` is checked against archived rows too, so
        # the collision check has to see them -- hence the marker the #210
        # sweep test looks for. Excluding this dimension itself, which still
        # holds the parked spelling rather than the name being restored.
        clash = self.fetchone(
            '-- includes-archived (#210): UNIQUE(exam_id, name) is enforced '
            'against archived rows, so a name collision must consider them\n'
            'SELECT id, name FROM exam_dimensions '
            'WHERE exam_id = ? AND name = ? AND id <> ?',
            (batch['exam_id'], restored_name, dimension_id),
        )
        if clash is not None:
            blocked.append({
                'code': 'name_taken',
                'conflicting_dimension_id': clash['id'],
                'message': (
                    f"Another dimension in this exam is already called "
                    f"“{restored_name}”, and two cannot share a name. "
                    f"Rename that one first, then restore this."
                ),
            })

        highest = self.fetchone(
            "SELECT MAX(display_order) AS hi FROM exam_dimensions "
            "WHERE exam_id = ? AND status = 'active'",
            (batch['exam_id'],),
        )
        new_order = int((highest or {}).get('hi') or 0) + 1

        # The exact set this archive produced. Each is planned with the
        # ownership guard released for *this* event only.
        members = self.fetchall(
            "SELECT subject_batch_id, root_node_id "
            "FROM dimension_delete_batch_subjects "
            "WHERE dimension_batch_id = ? ORDER BY root_node_id",
            (batch_id,),
        )
        subject_batches: List[Dict[str, Any]] = []
        nodes_total = 0
        for member in members:
            sub = self.plan_batch_restore(
                member['subject_batch_id'],
                as_part_of_dimension_batch=batch_id,
            )
            # A sub-batch that cannot run is **skipped, not blocking.** Its
            # nodes simply stay archived, and archived subjects inside an
            # active dimension are an ordinary state -- whereas refusing the
            # whole restore would leave the dimension archived forever because
            # one of its trees had been re-deleted since.
            entry = {
                'batch_id': member['subject_batch_id'],
                'root_node_id': member['root_node_id'],
                'root_node_name': sub.get('root_node_name'),
                'restore': bool(sub.get('restorable')),
                'skip_reason': (
                    None if sub.get('restorable')
                    else (sub['blocked'][0]['code'] if sub.get('blocked') else 'unknown')
                ),
                'skip_detail': (
                    None if sub.get('restorable')
                    else (sub['blocked'][0]['message'] if sub.get('blocked') else None)
                ),
                'nodes_to_restore': sub.get('counts', {}).get('nodes_to_restore', 0),
            }
            if entry['restore']:
                nodes_total += entry['nodes_to_restore']
            subject_batches.append(entry)

        return {
            'batch_id': batch_id,
            'kind': 'dimension',
            'exists': True,
            'dimension_id': dimension_id,
            'dimension_name': restored_name,
            'restored_name': restored_name,
            'exam_id': batch['exam_id'],
            'deleted_at': batch['created_at'],
            'new_display_order': new_order,
            'blocked': blocked,
            'restorable': not blocked,
            'subject_batches': subject_batches,
            'counts': {
                'subject_batches_to_restore': sum(
                    1 for b in subject_batches if b['restore']),
                'subject_batches_skipped': sum(
                    1 for b in subject_batches if not b['restore']),
                'nodes_to_restore': nodes_total,
            },
        }

    def restore_dimension_delete_batch(self, batch_id: str) -> Dict[str, Any]:
        """Un-archive a dimension and the trees archived with it. One transaction.

        Order matters and mirrors :meth:`DimensionsMixin.archive_dimension`
        reversed: the dimension row is unparked **first**, so that by the time
        the subject batches replay, their subjects are landing in an *active*
        dimension rather than briefly inside an archived one. Nothing observes
        the intermediate state inside a transaction, but the ordering is what
        makes the invariant readable rather than incidental.

        Raises :class:`SubjectRestoreError` when the plan is blocked, so a
        refused restore reaches the bridge as ``success=false`` with a
        sentence.
        """
        plan = self.plan_dimension_batch_restore(batch_id)
        if plan['blocked']:
            raise SubjectRestoreError(
                ' '.join(item['message'] for item in plan['blocked'])
            )

        with self.transaction():
            self.execute(
                "UPDATE exam_dimensions "
                "SET status = 'active', archived_batch_id = NULL, "
                "    name = ?, display_order = ? "
                "WHERE id = ?",
                (plan['restored_name'], plan['new_display_order'],
                 plan['dimension_id']),
            )
            for member in plan['subject_batches']:
                if not member['restore']:
                    continue
                # Nested: this opens a SAVEPOINT rather than a transaction
                # (#95), so the whole dimension restore is still atomic.
                self.restore_subject_delete_batch(
                    member['batch_id'], as_part_of_dimension_batch=batch_id)

        result = dict(plan)
        result['restored'] = True
        result['summary'] = self._dimension_restore_summary(plan)

        if self.error_logger and ErrorCategory is not None:
            counts = plan['counts']
            self.error_logger.info(
                f"Restored dimension archive {batch_id} "
                f"(“{plan['restored_name']}”): "
                f"{counts['subject_batches_to_restore']} trees, "
                f"{counts['nodes_to_restore']} subjects; "
                f"{counts['subject_batches_skipped']} trees skipped",
                category=ErrorCategory.DATABASE,
            )
        return result

    @staticmethod
    def _dimension_restore_summary(plan: Dict[str, Any]) -> str:
        """One sentence, naming skipped trees rather than hiding them."""
        counts = plan['counts']
        trees = counts['subject_batches_to_restore']
        skipped = counts['subject_batches_skipped']
        nodes = counts['nodes_to_restore']
        name = plan['restored_name']
        tree_noun = 'tree' if trees == 1 else 'trees'
        node_noun = 'subject' if nodes == 1 else 'subjects'
        base = (
            f"Restored “{name}” with {trees} {tree_noun} "
            f"({nodes} {node_noun})."
        )
        if not skipped:
            return base
        names = ', '.join(
            f"“{b['root_node_name']}”"
            for b in plan['subject_batches'] if not b['restore']
        )
        return (
            f"{base} {skipped} could not be restored and stays archived: {names}."
        )
