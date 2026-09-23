"""WIMI subject-tree import: one planner, a preview and an apply (issue #67).

Re-importing a corrected outline used to duplicate the tree. ``import_node``
called :meth:`create_subject_node` unconditionally for every node in the
file, so the only thing standing between the student and a doubled
hierarchy was that method's duplicate-name check — a **partial merge by
name** whose outcome depended on which nodes happened to have been
renamed. Correcting 23 defects in a 2,211-subject outline and re-importing
it produced a tree containing both versions of everything that moved or was
renamed, and a hard ``Subject node already exists`` error for everything
that had not.

This module replaces that with a merge, and the decisions recorded in
issue #67 are what it implements:

**Decision 1 — an optional stable ``id``, and a preview before anything
happens.** A file node may carry ``id``; it is stored on
``subject_nodes.import_id`` (m020) and is what a re-import matches on, so a
renamed subject is understood as a rename rather than a delete plus a
create. Where there is no id, matching falls back to name-and-path, which
*cannot* see a rename — the preview says so in as many words rather than
letting the student find out afterwards.

Preview and execution share :meth:`plan_subject_import`, exactly as
:meth:`plan_subject_delete` is shared by the delete preview and the delete
itself (issue #15). :meth:`apply_subject_import` does not re-derive
anything: it calls the planner and executes its output. The two cannot
drift because there is only one of them.

**Decision 3 — a subject carrying entries is never removed.** The
student's own history outranks the blueprint. An unmatched subject with
entries on it is *kept* and flagged ``kept_in_use``, with the entry count
and ids the preview needs to link the student at their own entries. An
unmatched subject with nothing on it, and nothing surviving beneath it, is
removed — through :meth:`delete_subject_subtree`, so an import's removals
are the same soft delete, the same edge handling and the same restore
journal as a manual one (issues #15 / #37), not a second set of rules.

**What survives is computed bottom-up, not guessed.** A subject survives
the import if the file still lists it, *or* it carries entries, *or*
anything beneath it survives. That last clause is what stops an import
archiving a chapter the file dropped while the student still has entries on
one of its topics: removing the chapter would leave that topic rolling up
nowhere, which is precisely the silent-rollup-loss issue #15 exists to
prevent.

**Edges the file does not mention are left alone.** A second parent the
student added by hand (polyhierarchy) is not in the blueprint and is not
the blueprint's business; only the *primary* edge follows the file.

Weight semantics (issue #64)
----------------------------

The decisions below were settled in issue #64 on 2026-09-15 and are stated
for students in ``docs/examples/subject_tree_import_format.md``. What they
mean *here* is mostly what this module deliberately does **not** do:

1. **A weight is a percentage of the whole exam, at every depth** — never a
   share of its parent. Two consequences are load-bearing absences: absolute
   weights are accepted at any level, and **a child may exceed its parent**.
   The nesting comes from the student's tree rather than the blueprint: Step
   2 CK publishes Nutrition (15–20%) and Multisystem Processes & Disorders
   (4–8%) as *sibling* rows, so a student who files nutrition under
   multisystem lands a 15–20% child inside a 4–8% parent using two real
   published numbers. It also follows from the rule itself with no example
   at all: the three Step 2 CK tables are overlapping partitions of the same
   items (84–153%, 78–113%, 97–142%), so any tree mixing axes cross-cuts.
   There is no parent/child comparison anywhere below, and adding one would
   be the bug.
2. **Coverage is surfaced, never corrected.** Official ranges summed to
   78–113% in one real file and 84–153% in another, because an item can
   classify to several disciplines at once — USMLE's own Clinical Science
   table exceeds 100% by design. :meth:`_import_weight_coverage` reports the
   total and :meth:`_import_weight_warnings` complains only when the file's
   top-level range does not span 100% at all. **Nothing rescales**:
   normalising would store numbers that do not match the document the
   student copied from, which silently falsifies a published source.
3. **An omitted weight is 0% on import** — the blueprint did not weight this
   subject. That is the opposite of the tree editor's empty weight field,
   which means "share out the remainder", and it is why
   :meth:`_import_weight_bounds` returns ``(0, 0)`` rather than ``None``.
4. **``0`` is data, not an error** (Step 2 CK publishes two tasks at 0%), and
   ``derived`` says only that WIMI computed the number — it never implies
   ``locked``.
5. **Locked wins over auto-balance**, which needs no code here:
   ``rebalance_sibling_edge_weights`` is opt-in and already excludes anchored
   and ``weight_locked`` edges.

Everything checkable from decisions 1–4 is a **warning**, not an error. A
real blueprint can legitimately break the arithmetic, and refusing a
2,211-subject outline over one transposed pair helps nobody.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..exceptions import (
    CircularReferenceError,
    SubjectNodeError,
    ValidationError,
)
from app_logging import ErrorCategory


# How many sample entry ids to carry per kept-in-use subject. The preview
# links the student at the entry browser filtered by subject, so it needs
# the subject id rather than the entries; the ids are here for tests and
# for a caller that wants to show a couple of titles without a second
# round trip. Capped so a subject with 400 entries does not inflate the
# payload.
_ENTRY_SAMPLE_LIMIT = 10

# How many per-subject weight warnings to spell out before collapsing the
# rest into a count. The frontend raises one toast per warning, so an
# outline with 400 malformed weights would otherwise bury the screen in
# toasts and tell the student nothing they could act on.
_WEIGHT_WARNING_LIMIT = 10


def _as_number(value: Any) -> Optional[float]:
    """``value`` as a float, or None if it is not a number.

    A weight is whatever the file put there. ``"11%"`` and ``None`` both
    reach the warning code, and neither may raise — the import must not
    die of a typo it is trying to report.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class SubjectImportMixin:
    """Plan and apply a subject-tree import. Composed into UserDatabase."""

    # ------------------------------------------------------------------
    # Reading the file
    # ------------------------------------------------------------------

    @staticmethod
    def _import_weight_bounds(node_data: Dict[str, Any]) -> Tuple[float, float]:
        """``weight`` in the file is a number or a ``{low, high}`` object.

        Kept byte-identical to what the old ``import_node`` did, including
        the ``value`` spelling, so no file that imported before imports
        differently now.
        """
        weight_data = node_data.get('weight')
        if isinstance(weight_data, dict):
            if 'value' in weight_data:
                low = weight_data['value']
                return low, low
            low = weight_data.get('low', 0)
            return low, weight_data.get('high', low)
        low = weight_data if weight_data else 0
        return low, low

    @staticmethod
    def _normalise_import_aliases(raw: Any) -> List[Dict[str, Any]]:
        """The file's ``aliases`` array, cleaned and de-duplicated.

        Normalising in the planner rather than at write time is what lets
        the preview count alias additions: an import that adds three
        eponyms to an otherwise untouched subject is not "unchanged", and
        saying so would be the preview drifting from the apply.
        """
        cleaned: List[Dict[str, Any]] = []
        seen: set = set()
        for alias_data in (raw or []):
            if not isinstance(alias_data, dict):
                continue
            name = str(alias_data.get('name', '') or '').strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            alias_type = alias_data.get('type', 'alternate_name')
            if alias_type not in (
                'eponym', 'acronym', 'alternate_name', 'colloquial'
            ):
                alias_type = 'alternate_name'
            cleaned.append({
                'name': name,
                'type': alias_type,
                'is_primary': bool(alias_data.get('is_primary', False)),
                'notes': alias_data.get('notes'),
            })
        return cleaned

    @staticmethod
    def _import_id_of(node_data: Dict[str, Any]) -> Optional[str]:
        """The file node's stable id, or None.

        Numbers are accepted and stringified — outline ids look like
        ``1.2.3`` and a hand-written file may well spell a top-level one
        as the bare number ``2``. Blank strings are not ids.
        """
        raw = node_data.get('id')
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    def _flatten_import_file(
        self,
        root_nodes: List[Dict[str, Any]],
        exam_context_id: int,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Pre-order flatten of the file into plan records.

        Pre-order matters: :meth:`apply_subject_import` walks this list
        once and resolves each node's parent from the map it has already
        filled, so a parent must always appear before its children.

        Returns ``(records, errors)``. An error is a file defect that
        stops the import — a node with no name, or two nodes claiming the
        same ``id``. Those are reported rather than silently skipped: an
        import that quietly drops half a file is how #61 happened.
        """
        levels = self.get_hierarchy_levels(exam_context_id)
        records: List[Dict[str, Any]] = []
        errors: List[str] = []
        seen_ids: Dict[str, int] = {}

        def walk(
            node_data: Dict[str, Any],
            parent_ref: Optional[int],
            level: int,
            position: int,
            path: List[str],
        ) -> None:
            if not isinstance(node_data, dict):
                errors.append(f"Entry at {'/'.join(path) or 'root'} is not an object")
                return
            name = str(node_data.get('name', '') or '').strip()
            if not name:
                errors.append(
                    f"A subject under {'/'.join(path) or 'the root'} has no name"
                )
                return

            node_path = path + [name]
            import_id = self._import_id_of(node_data)
            if import_id is not None:
                if import_id in seen_ids:
                    errors.append(
                        f'Two subjects share id "{import_id}": '
                        f'"{records[seen_ids[import_id]]["name"]}" and "{name}"'
                    )
                    return
                seen_ids[import_id] = len(records)

            level_name = (
                levels[level - 1].level_name
                if level <= len(levels)
                else f'Level {level}'
            )
            low, high = self._import_weight_bounds(node_data)

            ref = len(records)
            records.append({
                'ref': ref,
                'parent_ref': parent_ref,
                'name': name,
                'path': node_path,
                'import_id': import_id,
                'level_type': node_data.get('level_type', level_name),
                'weight_low': low,
                'weight_high': high,
                'sort_order': node_data.get('sort_order', position),
                'aliases': self._normalise_import_aliases(node_data.get('aliases')),
                # Filled in by the matcher.
                'node_id': None,
                'matched_by': None,
                'action': 'add',
                'changes': {},
                'new_aliases': [],
            })

            children = node_data.get('children') or []
            for child_position, child_data in enumerate(children, start=1):
                walk(child_data, ref, level + 1, child_position, node_path)

        for root_position, node_data in enumerate(root_nodes or [], start=1):
            walk(node_data, None, 1, root_position, [])

        return records, errors

    # ------------------------------------------------------------------
    # Reading what is already there
    # ------------------------------------------------------------------

    def _import_scope(
        self,
        exam_name: str,
        dimension_id: Optional[int],
    ) -> Dict[str, Any]:
        """The active subjects an import into this scope may touch.

        Scope is *exam context plus dimension*, never the exam alone. A
        multi-dimensional exam imports one dimension at a time, and an
        import into "Systems" that judged "Disciplines" absent-from-the-
        file would delete the other half of the tree.
        """
        if dimension_id is None:
            rows = self.fetchall(
                "SELECT id, name, level_type, sort_order, exam_weight_low, "
                "       exam_weight_high, import_id, parent_id "
                "FROM subject_nodes "
                "WHERE exam_context = ? AND dimension_id IS NULL "
                "  AND status = 'active'",
                (exam_name,),
            )
        else:
            rows = self.fetchall(
                "SELECT id, name, level_type, sort_order, exam_weight_low, "
                "       exam_weight_high, import_id, parent_id "
                "FROM subject_nodes "
                "WHERE exam_context = ? AND dimension_id = ? "
                "  AND status = 'active'",
                (exam_name, dimension_id),
            )

        nodes = {row['id']: dict(row) for row in rows}
        if not nodes:
            return {
                'nodes': {},
                'children_of': {},
                'primary_parent_of': {},
                'by_import_id': {},
                'by_parent_name': {},
                'aliases_of': {},
            }

        ids = tuple(sorted(nodes))
        placeholders = ','.join(['?'] * len(ids))

        # Children of scope nodes, whatever dimension the child is in:
        # an out-of-scope child still *survives*, and a parent with a
        # surviving child must not be removed.
        children_of: Dict[int, List[int]] = {}
        primary_parent_of: Dict[int, int] = {}
        for row in self.fetchall(
            f"""
            SELECT se.parent_id AS parent_id, se.child_id AS child_id,
                   se.is_primary AS is_primary
            FROM subject_edges se
            JOIN subject_nodes c ON c.id = se.child_id
            WHERE c.status = 'active'
              AND (se.parent_id IN ({placeholders})
                   OR se.child_id IN ({placeholders}))
            """,
            ids + ids,
        ):
            children_of.setdefault(row['parent_id'], []).append(row['child_id'])
            if row['is_primary']:
                primary_parent_of[row['child_id']] = row['parent_id']

        by_import_id = {
            node['import_id']: nid
            for nid, node in nodes.items()
            if node.get('import_id')
        }
        by_parent_name: Dict[Tuple[Optional[int], str], int] = {}
        for nid, node in nodes.items():
            lowered = node['name'].strip().lower()
            # First writer wins; a tree with two identically-named
            # siblings is already malformed and the duplicate simply
            # stays unmatched (and is then judged on its entries).
            by_parent_name.setdefault((primary_parent_of.get(nid), lowered), nid)
            # Also index under the legacy ``parent_id`` column, because
            # that is the column ``create_subject_node`` checks before
            # refusing a duplicate. A node whose primary edge was moved
            # without the legacy mirror following would otherwise fail to
            # match here and then fail to create there — the plan would
            # promise an add the apply could not make.
            by_parent_name.setdefault((node.get('parent_id'), lowered), nid)

        aliases_of: Dict[int, set] = {}
        ids_placeholders = ','.join(['?'] * len(ids))
        for row in self.fetchall(
            f"SELECT subject_node_id, alias_name FROM subject_aliases "
            f"WHERE subject_node_id IN ({ids_placeholders})",
            ids,
        ):
            aliases_of.setdefault(row['subject_node_id'], set()).add(
                (row['alias_name'] or '').strip().lower()
            )

        return {
            'nodes': nodes,
            'children_of': children_of,
            'primary_parent_of': primary_parent_of,
            'by_import_id': by_import_id,
            'by_parent_name': by_parent_name,
            'aliases_of': aliases_of,
        }

    def _import_entry_counts(self, node_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """``{node_id: {'count': n, 'entry_ids': [...]}}`` for subjects with entries.

        Counts **all** mappings, primary and secondary. This is a
        "does anything point here" question, not a measurement — #13's
        counting-is-primary-only rule governs totals, and removing a
        subject that only ever appears as a secondary tag would still
        take that tag away from the student's entries.
        """
        if not node_ids:
            return {}
        counts: Dict[int, Dict[str, Any]] = {}
        chunk = 400
        for start in range(0, len(node_ids), chunk):
            slice_ids = node_ids[start:start + chunk]
            placeholders = ','.join(['?'] * len(slice_ids))
            for row in self.fetchall(
                f"""
                SELECT subject_node_id, question_entry_id
                FROM entry_subject_mappings
                WHERE subject_node_id IN ({placeholders})
                ORDER BY subject_node_id, question_entry_id
                """,
                tuple(slice_ids),
            ):
                bucket = counts.setdefault(
                    row['subject_node_id'], {'count': 0, 'entry_ids': []}
                )
                bucket['count'] += 1
                if len(bucket['entry_ids']) < _ENTRY_SAMPLE_LIMIT:
                    bucket['entry_ids'].append(row['question_entry_id'])
        return counts

    # ------------------------------------------------------------------
    # The planner
    # ------------------------------------------------------------------

    def plan_subject_import(
        self,
        exam_context_id: int,
        root_nodes: List[Dict[str, Any]],
        dimension_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Work out exactly what importing ``root_nodes`` would do. Read-only.

        Single source of truth for import semantics: the preview slot and
        :meth:`apply_subject_import` both consume it, so what the student
        is shown is what runs.

        **Matching, in order.** A file node with an ``id`` matches the
        active subject in scope carrying that ``import_id``, wherever it
        currently sits — that is what makes a rename a rename and a move
        a move. Failing that (and for a file node with no id at all) it
        matches by name under its matched parent. A node matched by name
        while carrying an id **adopts** that id, which is how a tree
        imported before ids existed acquires them.

        **Survival, bottom-up.** Every matched subject survives. An
        unmatched one survives if it carries entries (decision 3) or if
        anything beneath it survives; otherwise it is removed.

        Returns a dict of:

        - ``nodes`` — the flattened file, in pre-order, each record
          carrying ``action`` (``'add'`` / ``'update'`` / ``'unchanged'``),
          the matched ``node_id`` and ``matched_by``, and a ``changes``
          map of ``field -> [old, new]``. This is the execution script.
        - ``added`` / ``updated`` / ``unchanged`` — views of the above.
          ``renamed`` and ``moved`` are *subsets of* ``updated``, not
          separate categories, so the counts never double-count a subject
          that was both.
        - ``removed`` — subjects the import will soft-delete.
        - ``kept_in_use`` — unmatched subjects kept because entries point
          at them, with ``entry_count`` and a sample of ``entry_ids``.
        - ``kept_as_ancestor`` — unmatched subjects kept only because
          something beneath them survives.
        - ``entries_affected`` — how many entries sit on ``kept_in_use``
          subjects, i.e. how many the student may want to re-tag.
        - ``entry_contexts_cleared`` — mappings whose ``primary_parent_id``
          points into the removed set and will be nulled (#15 decision 3).
        - ``rename_blind`` — True when the file carries no ids *and* the
          import both adds and removes, i.e. when a rename in the file
          will land as a remove-plus-add and the student should be told.
        - ``errors`` — file defects that stop the import.
        - ``coverage`` — the summed low/high of the file's **top-level**
          weights, how many of them carry one, and whether that band
          spans 100%. Reported, never acted on (issue #64 decision 2).
        - ``warnings`` — weight problems worth saying out loud. Never
          fatal; :meth:`apply_subject_import` starts its own warning list
          from this one.

        Raises:
            SubjectNodeError: if ``exam_context_id`` names no exam.
        """
        config = self.get_exam_context_config(exam_context_id)
        if not config:
            raise SubjectNodeError(f"Exam context {exam_context_id} not found")
        exam_name = config.exam_name

        records, errors = self._flatten_import_file(root_nodes, exam_context_id)
        scope = self._import_scope(exam_name, dimension_id)
        nodes = scope['nodes']
        primary_parent_of = scope['primary_parent_of']

        by_ref: Dict[int, Dict[str, Any]] = {r['ref']: r for r in records}
        claimed: set = set()

        # Pass 1: **ids first, before any name can claim a subject.**
        # An id match ignores position — that is what makes a rename a
        # rename and a move a move — so it needs no parent resolved and
        # can run in one sweep. Running it first is not a tidiness
        # choice: if a name match could claim a subject out from under
        # the file node carrying that subject's id, that file node would
        # fall through to "add", and the add would try to write an
        # ``import_id`` the claimed subject still holds — a unique-index
        # failure that aborts the whole import over a file that is
        # perfectly well-formed.
        for record in records:
            if not record['import_id']:
                continue
            candidate = scope['by_import_id'].get(record['import_id'])
            if candidate is not None and candidate not in claimed:
                claimed.add(candidate)
                record['node_id'] = candidate
                record['matched_by'] = 'id'

        # Pass 2: everything else, in pre-order, because name-and-path
        # matching needs the parent's identity and the parent is always
        # earlier in the list.
        for record in records:
            parent_record = (
                by_ref.get(record['parent_ref'])
                if record['parent_ref'] is not None else None
            )
            expected_parent = parent_record['node_id'] if parent_record else None
            record['expected_parent_id'] = expected_parent

            matched: Optional[int] = record['node_id']
            matched_by: Optional[str] = record['matched_by']

            if matched is None:
                # Name-and-path. A file node whose parent is itself new
                # cannot match anything by path, and must not fall back
                # to "some node of that name somewhere" — that is how a
                # merge silently re-parents half a tree.
                if parent_record is None or expected_parent is not None:
                    key = (expected_parent, record['name'].strip().lower())
                    candidate = scope['by_parent_name'].get(key)
                    if candidate is not None and candidate not in claimed:
                        matched, matched_by = candidate, 'name'
                        claimed.add(matched)
                        record['node_id'] = matched
                        record['matched_by'] = matched_by

            if matched is None:
                record['action'] = 'add'
                record['new_aliases'] = list(record['aliases'])
                continue

            existing = nodes[matched]

            changes: Dict[str, List[Any]] = {}
            if existing['name'] != record['name']:
                changes['name'] = [existing['name'], record['name']]
            if (existing['level_type'] or '') != (record['level_type'] or ''):
                changes['level_type'] = [existing['level_type'], record['level_type']]
            if self._weights_differ(existing['exam_weight_low'], record['weight_low']):
                changes['exam_weight_low'] = [
                    existing['exam_weight_low'], record['weight_low']
                ]
            if self._weights_differ(existing['exam_weight_high'], record['weight_high']):
                changes['exam_weight_high'] = [
                    existing['exam_weight_high'], record['weight_high']
                ]
            if (existing['sort_order'] or 0) != (record['sort_order'] or 0):
                changes['sort_order'] = [existing['sort_order'], record['sort_order']]
            current_parent = primary_parent_of.get(matched)
            if current_parent != expected_parent:
                changes['parent_id'] = [current_parent, expected_parent]
            if record['import_id'] and not existing.get('import_id'):
                changes['import_id'] = [None, record['import_id']]

            have = scope['aliases_of'].get(matched, set())
            new_aliases = [
                alias for alias in record['aliases']
                if alias['name'].lower() not in have
            ]
            record['new_aliases'] = new_aliases
            if new_aliases:
                changes['aliases_added'] = [
                    [], [alias['name'] for alias in new_aliases]
                ]

            record['changes'] = changes
            record['action'] = 'update' if changes else 'unchanged'

        # ---- what is left over -------------------------------------
        #
        # An **empty file removes nothing.** "Every subject is absent
        # from this file" and "this file lists no subjects" are the same
        # sentence to the matcher and opposite intentions to the student:
        # the first is a corrected outline, the second is a typo in the
        # top-level key, a truncated download, or a file for a format
        # WIMI does not read. The destructive reading of an empty file is
        # never the one the student meant, and deleting a whole tree is
        # what the delete modal is for. Note this is *empty*, not
        # *unparseable* — a file with a misspelled ``root_nodes`` key
        # reaches here as an empty list, which is exactly the case this
        # guards.
        empty_file = not records
        matched_ids = {r['node_id'] for r in records if r['node_id'] is not None}
        unmatched = (
            [] if empty_file
            else [nid for nid in sorted(nodes) if nid not in matched_ids]
        )
        entry_counts = self._import_entry_counts(unmatched)

        survives: Dict[int, bool] = {}

        def survives_node(nid: int, seen: Optional[set] = None) -> bool:
            """Bottom-up survival, memoised, cycle-guarded.

            A child outside the scope (another dimension) is not in
            ``nodes``; it is still alive, so it counts as surviving.
            """
            if nid in survives:
                return survives[nid]
            if nid not in nodes:
                return True
            seen = set() if seen is None else seen
            if nid in seen:
                # A cycle can only exist through bad data; treat it as
                # "do not remove" rather than recursing forever.
                return True
            seen = seen | {nid}
            if empty_file or nid in matched_ids:
                survives[nid] = True
            elif entry_counts.get(nid, {}).get('count'):
                survives[nid] = True
            else:
                survives[nid] = any(
                    survives_node(child, seen)
                    for child in scope['children_of'].get(nid, [])
                )
            return survives[nid]

        for nid in nodes:
            survives_node(nid)

        removed_ids = [nid for nid in sorted(nodes) if not survives[nid]]
        kept_in_use = [
            nid for nid in unmatched if entry_counts.get(nid, {}).get('count')
        ]
        kept_as_ancestor = [
            nid for nid in unmatched
            if survives[nid] and nid not in kept_in_use
        ]

        entries_affected = 0
        if kept_in_use:
            placeholders = ','.join(['?'] * len(kept_in_use))
            row = self.fetchone(
                f"SELECT COUNT(DISTINCT question_entry_id) AS c "
                f"FROM entry_subject_mappings "
                f"WHERE subject_node_id IN ({placeholders})",
                tuple(kept_in_use),
            )
            entries_affected = row['c'] if row else 0

        entry_contexts_cleared = 0
        if removed_ids:
            placeholders = ','.join(['?'] * len(removed_ids))
            row = self.fetchone(
                f"SELECT COUNT(*) AS c FROM entry_subject_mappings "
                f"WHERE primary_parent_id IN ({placeholders})",
                tuple(removed_ids),
            )
            entry_contexts_cleared = row['c'] if row else 0

        def describe(nid: int) -> Dict[str, Any]:
            return {
                'id': nid,
                'name': nodes[nid]['name'],
                'path': self._import_scope_path(scope, nid),
            }

        added = [r for r in records if r['action'] == 'add']
        updated = [r for r in records if r['action'] == 'update']
        unchanged = [r for r in records if r['action'] == 'unchanged']
        renamed = [r for r in updated if 'name' in r['changes']]
        moved = [r for r in updated if 'parent_id' in r['changes']]

        with_id = sum(1 for r in records if r['import_id'])
        rename_blind = bool(added) and bool(removed_ids or kept_in_use) and not with_id

        # Weight coverage and the warnings drawn from it (issue #64).
        # Computed in the planner rather than at write time for the same
        # reason everything else is: the preview and the apply must be
        # able to say the same thing, and the apply reads this list
        # straight out of the plan.
        coverage = self._import_weight_coverage(records)
        weight_warnings = self._import_weight_warnings(records, coverage)

        return {
            'exam_context_id': exam_context_id,
            'exam_name': exam_name,
            'dimension_id': dimension_id,
            'nodes': records,
            'file_node_count': len(records),
            'file_nodes_with_id': with_id,
            'file_uses_ids': with_id > 0,
            'added': [
                {'ref': r['ref'], 'name': r['name'], 'path': r['path']}
                for r in added
            ],
            'updated': [
                {
                    'ref': r['ref'], 'node_id': r['node_id'], 'name': r['name'],
                    'path': r['path'], 'matched_by': r['matched_by'],
                    'changes': r['changes'],
                }
                for r in updated
            ],
            'unchanged': [
                {'ref': r['ref'], 'node_id': r['node_id'], 'name': r['name']}
                for r in unchanged
            ],
            'renamed': [
                {
                    'node_id': r['node_id'],
                    'from': r['changes']['name'][0],
                    'to': r['changes']['name'][1],
                    'matched_by': r['matched_by'],
                }
                for r in renamed
            ],
            'moved': [
                {'node_id': r['node_id'], 'name': r['name'], 'path': r['path']}
                for r in moved
            ],
            'removed': [describe(nid) for nid in removed_ids],
            'kept_in_use': [
                dict(
                    describe(nid),
                    entry_count=entry_counts[nid]['count'],
                    entry_ids=entry_counts[nid]['entry_ids'],
                )
                for nid in kept_in_use
            ],
            'kept_as_ancestor': [describe(nid) for nid in kept_as_ancestor],
            'entries_affected': entries_affected,
            'entry_contexts_cleared': entry_contexts_cleared,
            'rename_blind': rename_blind,
            'empty_file': empty_file,
            'errors': errors,
            'coverage': coverage,
            'warnings': weight_warnings,
            'counts': {
                'added': len(added),
                'updated': len(updated),
                'unchanged': len(unchanged),
                'renamed': len(renamed),
                'moved': len(moved),
                'removed': len(removed_ids),
                'kept_in_use': len(kept_in_use),
                'kept_as_ancestor': len(kept_as_ancestor),
                'entries_affected': entries_affected,
            },
        }

    @staticmethod
    def _weights_differ(existing: Optional[float], incoming: Optional[float]) -> bool:
        """Compare weights the way the file writes them.

        The file's ``weight`` defaults to 0 where the old importer wrote
        0, so ``None`` and ``0`` are the same statement about a subject
        with no official weight — treating them as a difference would
        report every weightless subject as "updated" on every re-import.
        """
        left = 0.0 if existing is None else float(existing)
        right = 0.0 if incoming is None else float(incoming)
        return abs(left - right) > 1e-9

    @staticmethod
    def _import_weight_coverage(records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """How much of the exam the file's **top-level** weights claim.

        A weight is a percentage of the whole exam (issue #64 decision 1),
        so coverage is the sum over the roots and nothing deeper — adding
        the descendants in would double-count every subject twice over.

        ``spans_100`` is the only judgement made here: True when the
        summed low–high band contains 100, which both real USMLE files
        (78–113% and 84–153%) satisfy and a dropped digit does not.
        ``weighted_roots`` is 0 for a file that carries no weights at all,
        and the caller skips the check rather than telling a deliberately
        unweighted outline that it covers 0% of the exam.
        """
        roots = [r for r in records if r['parent_ref'] is None]
        low = 0.0
        high = 0.0
        weighted = 0
        for record in roots:
            record_low = _as_number(record['weight_low']) or 0.0
            record_high = _as_number(record['weight_high'])
            if record_high is None:
                record_high = record_low
            low += record_low
            high += record_high
            if record_low or record_high:
                weighted += 1
        return {
            'low': round(low, 4),
            'high': round(high, 4),
            'weighted_roots': weighted,
            'root_count': len(roots),
            'spans_100': bool(weighted) and low <= 100.0 <= high,
        }

    @staticmethod
    def _import_weight_warnings(
        records: List[Dict[str, Any]],
        coverage: Dict[str, Any],
    ) -> List[str]:
        """Weight problems worth saying out loud. Never fatal (issue #64).

        Three per-subject checks — a weight that is not a number, a ``low``
        above its ``high``, and a percentage outside 0–100 — plus one
        whole-file check on coverage. Each is a **warning**: the file
        imports exactly as written, because every one of these can be a
        faithful transcription of a document that is itself odd, and
        because rejecting a whole outline over one of them would cost the
        student the other 2,210 subjects.

        Deliberately absent: any comparison between a subject's weight and
        its parent's. A child heavier than its parent is correct data.
        """
        problems: List[str] = []
        for record in records:
            name = record['name']
            low = _as_number(record['weight_low'])
            high = _as_number(record['weight_high'])
            if low is None or high is None:
                problems.append(
                    f'"{name}" has a weight that is not a number '
                    f'({record["weight_low"]!r}); imported as 0%'
                )
                continue
            if low > high:
                problems.append(
                    f'"{name}" has a weight low of {low:g} above its high of '
                    f'{high:g}; imported as written'
                )
            if low < 0 or high > 100:
                problems.append(
                    f'"{name}" has a weight of {low:g}–{high:g}%, outside '
                    f'0–100%; imported as written'
                )

        warnings = problems[:_WEIGHT_WARNING_LIMIT]
        if len(problems) > _WEIGHT_WARNING_LIMIT:
            warnings.append(
                f'… and {len(problems) - _WEIGHT_WARNING_LIMIT} more subjects '
                f'with weights that look wrong'
            )

        if coverage['weighted_roots'] and not coverage['spans_100']:
            warnings.append(
                f"The file's top-level weights total "
                f"{coverage['low']:g}–{coverage['high']:g}% of the exam, which "
                f"does not span 100%. WIMI imports the numbers as written and "
                f"never rescales them — check the file if that is not what the "
                f"blueprint says."
            )
        return warnings

    @staticmethod
    def _import_scope_path(scope: Dict[str, Any], node_id: int) -> List[str]:
        """Root → node names, following primary edges inside the scope."""
        names: List[str] = []
        seen: set = set()
        current: Optional[int] = node_id
        while current is not None and current in scope['nodes'] and current not in seen:
            seen.add(current)
            names.append(scope['nodes'][current]['name'])
            current = scope['primary_parent_of'].get(current)
        return list(reversed(names))

    # ------------------------------------------------------------------
    # The apply
    # ------------------------------------------------------------------

    def apply_subject_import(
        self,
        exam_context_id: int,
        root_nodes: List[Dict[str, Any]],
        dimension_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute :meth:`plan_subject_import`'s plan.

        Nothing is re-derived here — every decision was made by the
        planner, and this method only carries it out, which is what
        guarantees the preview and the import agree.

        Order: create and update first, remove last. A subject the file
        moved out of a doomed branch must have moved *before* the branch
        is judged empty, or the move would be undone by the removal.

        Atomicity is best-effort, matching the rest of this layer:
        ``create_subject_node``, ``add_edge`` and
        ``delete_subject_subtree`` each open their own transaction, and
        ``BaseDatabase.transaction`` commits rather than nesting a
        savepoint, so a failure midway leaves the work done so far
        committed. That was true of the old importer too; making it
        genuinely atomic is a change to ``BaseDatabase``, not to import.

        Returns the plan, plus:

        - ``imported_count`` — file nodes applied (added + updated +
          unchanged), i.e. what the old slot reported.
        - ``created_ids`` / ``updated_ids`` / ``removed_ids``
        - ``delete_batch_ids`` — one per removal cascade, for #37.
        - ``warnings`` — the plan's weight warnings (issue #64), plus
          moves refused as cycles and aliases that would not write. None
          of them aborts an import.
        """
        plan = self.plan_subject_import(exam_context_id, root_nodes, dimension_id)
        if plan['errors']:
            raise ValidationError('; '.join(plan['errors']))

        config = self.get_exam_context_config(exam_context_id)
        exam_name = config.exam_name

        ref_to_node_id: Dict[int, int] = {
            r['ref']: r['node_id']
            for r in plan['nodes'] if r['node_id'] is not None
        }
        created_ids: List[int] = []
        updated_ids: List[int] = []
        # Seeded from the plan so the weight warnings the preview computed
        # (issue #64) reach the student, rather than being recomputed here
        # and risking a different answer.
        warnings: List[str] = list(plan['warnings'])

        # Phase 1 — rename and re-value the subjects that already exist.
        #
        # **Before the adds, not after.** A file that renames "Alpha" to
        # "Beta" and introduces a different subject also called "Alpha"
        # is a perfectly ordinary correction, and creating the new
        # "Alpha" while the old row is still called that hits
        # ``create_subject_node``'s duplicate-name check — the import
        # fails on a file with nothing wrong with it. Column writes carry
        # no parent dependency, so they can all go first.
        for record in plan['nodes']:
            if record['action'] == 'update':
                self._apply_import_update_columns(record)
                updated_ids.append(record['node_id'])

        # Phase 2 — create what is new, in pre-order so a new parent
        # exists before its new children.
        for record in plan['nodes']:
            if record['action'] != 'add':
                continue
            parent_ref = record['parent_ref']
            parent_node_id = (
                ref_to_node_id.get(parent_ref) if parent_ref is not None else None
            )
            node = self.create_subject_node(
                exam_context=exam_name,
                name=record['name'],
                level_type=record['level_type'],
                parent_id=parent_node_id,
                exam_weight_low=record['weight_low'],
                exam_weight_high=record['weight_high'],
                sort_order=record['sort_order'],
                dimension_id=dimension_id,
            )
            if record['import_id']:
                with self.transaction():
                    self.execute(
                        "UPDATE subject_nodes SET import_id = ?, "
                        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (record['import_id'], node.id),
                    )
            ref_to_node_id[record['ref']] = node.id
            created_ids.append(node.id)

        # Phase 3 — re-parent what moved, now that every node the file
        # names exists. A subject can legitimately move *under a subject
        # this same import created*, which is only possible once phase 2
        # has run.
        for record in plan['nodes']:
            if record['action'] != 'update' or 'parent_id' not in record['changes']:
                continue
            parent_ref = record['parent_ref']
            parent_node_id = (
                ref_to_node_id.get(parent_ref) if parent_ref is not None else None
            )
            self._apply_import_move(
                record['node_id'], record, parent_node_id, warnings
            )

        # Phase 4 — aliases, for new and existing subjects alike. The
        # planner worked out which ones are missing; this only writes.
        for record in plan['nodes']:
            node_id = ref_to_node_id.get(record['ref'])
            if node_id is not None:
                self._apply_import_aliases(node_id, exam_name, record, warnings)

        # Removals last, and top-down: ``delete_subject_subtree``
        # cascades to descendants left without a surviving parent, so a
        # removal root usually takes its branch with it and the ones
        # below it are already archived by the time the loop reaches
        # them. Re-reading ``status`` before each call is what makes that
        # safe — it is also #57's no-op guard, but relying on the guard
        # instead of checking would journal empty batches.
        removed_ids: List[int] = []
        delete_batch_ids: List[str] = []
        for item in self._import_removal_order(plan):
            row = self.fetchone(
                "SELECT status FROM subject_nodes WHERE id = ?", (item['id'],)
            )
            if row is None or row['status'] != 'active':
                removed_ids.append(item['id'])
                continue
            result = self.delete_subject_subtree(item['id'], promote_children=False)
            removed_ids.append(item['id'])
            if result.get('batch_id'):
                delete_batch_ids.append(result['batch_id'])

        if self.error_logger:
            self.error_logger.info(
                f"Subject import into exam {exam_context_id} "
                f"(dimension {dimension_id}): "
                f"{len(created_ids)} added, {len(updated_ids)} updated, "
                f"{plan['counts']['unchanged']} unchanged, "
                f"{len(removed_ids)} removed, "
                f"{plan['counts']['kept_in_use']} kept because entries "
                f"point at them",
                category=ErrorCategory.DATABASE,
            )

        result = dict(plan)
        result.update({
            'imported_count': plan['file_node_count'],
            'created_ids': created_ids,
            'updated_ids': updated_ids,
            'removed_ids': removed_ids,
            'delete_batch_ids': delete_batch_ids,
            'warnings': warnings,
        })
        return result

    @staticmethod
    def _import_removal_order(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Removals shallowest-first, so a cascade covers what follows."""
        return sorted(plan['removed'], key=lambda item: len(item['path']))

    def _apply_import_update_columns(self, record: Dict[str, Any]) -> None:
        """Write one matched subject's changed columns. No edge work.

        Separate from :meth:`_apply_import_move` because re-parenting is
        edge work with a cycle check, and a refused move must not stop a
        rename from landing — and because the two run in different
        phases, renames before the adds and moves after them.
        """
        node_id = record['node_id']
        changes = record['changes']
        columns = [
            ('name', record['name']),
            ('level_type', record['level_type']),
            ('exam_weight_low', record['weight_low']),
            ('exam_weight_high', record['weight_high']),
            ('sort_order', record['sort_order']),
        ]
        sets = [(col, value) for col, value in columns if col in changes]
        if 'import_id' in changes:
            sets.append(('import_id', record['import_id']))

        if sets:
            assignments = ', '.join(f"{col} = ?" for col, _ in sets)
            with self.transaction():
                self.execute(
                    f"UPDATE subject_nodes SET {assignments}, "
                    f"updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    tuple(value for _, value in sets) + (node_id,),
                )

        if 'parent_id' not in changes and 'sort_order' in changes:
            parent_id = self.fetchone(
                "SELECT parent_id FROM subject_edges "
                "WHERE child_id = ? AND is_primary = TRUE",
                (node_id,),
            )
            if parent_id is not None:
                self._sync_import_edge_order(
                    parent_id['parent_id'], node_id, record['sort_order']
                )

    def _apply_import_move(
        self,
        node_id: int,
        record: Dict[str, Any],
        parent_node_id: Optional[int],
        warnings: List[str],
    ) -> None:
        """Re-point one matched subject's **primary** edge at the parent
        the file gives it.

        Only the primary edge: a second parent the student added by hand
        (polyhierarchy) is not in the blueprint and is not the
        blueprint's to remove. A move refused as a cycle is a warning,
        not a failed import — the subject stays where it was and the
        student is told.
        """
        old_parent = record['changes']['parent_id'][0]
        try:
            if parent_node_id is not None:
                existing = self.fetchone(
                    "SELECT id FROM subject_edges "
                    "WHERE parent_id = ? AND child_id = ?",
                    (parent_node_id, node_id),
                )
                if existing is None:
                    self.add_edge(parent_node_id, node_id, is_primary=True)
                else:
                    self.set_primary_parent(node_id, parent_node_id)
                self._sync_import_edge_order(
                    parent_node_id, node_id, record['sort_order']
                )
        except (CircularReferenceError, ValidationError, SubjectNodeError) as exc:
            warnings.append(
                f'Could not move "{record["name"]}" under its new parent: {exc}'
            )
            return

        # The old primary edge goes only once the new home exists, and
        # only the *primary* one: a second parent the student added by
        # hand is not the file's to remove.
        if old_parent is not None and old_parent != parent_node_id:
            row = self.fetchone(
                "SELECT id FROM subject_edges "
                "WHERE parent_id = ? AND child_id = ?",
                (old_parent, node_id),
            )
            if row is not None:
                self.remove_edge(row['id'])

        with self.transaction():
            self.execute(
                "UPDATE subject_nodes SET parent_id = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (parent_node_id, node_id),
            )

    def _sync_import_edge_order(
        self, parent_id: int, child_id: int, sort_order: int
    ) -> None:
        """Keep ``subject_edges.display_order`` with ``sort_order``.

        ``get_subject_hierarchy`` orders children by the *edge* column
        first (issue #62), so a re-import that moved a subject up the
        list has to write both or nothing changes on screen.
        """
        with self.transaction():
            self.execute(
                "UPDATE subject_edges SET display_order = ?, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE parent_id = ? AND child_id = ?",
                (sort_order or 0, parent_id, child_id),
            )

    def _apply_import_aliases(
        self,
        node_id: int,
        exam_name: str,
        record: Dict[str, Any],
        warnings: List[str],
    ) -> None:
        """Create the aliases the plan said were missing.

        ``new_aliases`` was worked out by the planner against the aliases
        the subject already has, so this writes exactly what the preview
        counted — no second opinion here.

        An alias that will not write is a warning, never a failure — the
        old importer logged and carried on for exactly the same reason,
        and a whole outline should not be refused over one duplicate
        eponym.
        """
        for alias in record.get('new_aliases') or []:
            try:
                self.create_subject_alias(
                    subject_node_id=node_id,
                    exam_context=exam_name,
                    alias_name=alias['name'],
                    alias_type=alias['type'],
                    is_primary=alias['is_primary'],
                    notes=alias['notes'],
                )
            except Exception as exc:  # noqa: BLE001 — reported, never fatal
                warnings.append(
                    f'Could not import alias "{alias["name"]}" for '
                    f'"{record["name"]}": {exc}'
                )
                if self.error_logger:
                    self.error_logger.warning(
                        f'Subject import could not create alias '
                        f'"{alias["name"]}" on node {node_id}: {exc}',
                        category=ErrorCategory.DATABASE,
                    )
