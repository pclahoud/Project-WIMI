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

import uuid
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

    @staticmethod
    def _empty_import_scope() -> Dict[str, Any]:
        """A scope with nothing in it.

        Two callers, and the second is the reason this is a method rather
        than a literal in one place. :meth:`_import_scope` returns it when
        the query found no rows, and :meth:`plan_whole_exam_import` uses it
        for an axis **the file creates** (#241): a dimension that does not
        exist yet holds no subjects, so every file node under it is an add
        and there is nothing for it to remove.

        ``dimension_id=None`` cannot say that. ``None`` is the
        *dimensionless* scope — the legacy subjects of an exam that predates
        dimensions — and it holds real rows. Planning a new axis against it
        would match that axis's subjects to dimensionless ones and judge the
        rest absent from the file.
        """
        return {
            'nodes': {},
            'children_of': {},
            'primary_parent_of': {},
            'by_import_id': {},
            'by_parent_name': {},
            'aliases_of': {},
        }

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

        This partition is also what keeps a whole-exam import's axes from
        bleeding into each other (#241) and what leaves the dimensionless
        subjects alone: the ``dimension_id IS NULL`` branch is reachable
        only by asking for it, and the whole-exam planner never does.
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
            return self._empty_import_scope()

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

        return self._plan_subject_tree(
            exam_context_id,
            exam_name,
            root_nodes,
            self._import_scope(exam_name, dimension_id),
            dimension_id=dimension_id,
        )

    def _plan_subject_tree(
        self,
        exam_context_id: int,
        exam_name: str,
        root_nodes: List[Dict[str, Any]],
        scope: Dict[str, Any],
        *,
        dimension_id: Optional[int] = None,
        axis_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Plan one tree against an already-built ``scope``. Read-only.

        Everything :meth:`plan_subject_import` documents happens here. The
        split exists so a whole-exam import (#241) can plan **each axis
        through this same code** rather than growing a second planner: its
        only differences are which scope an axis is planned against and
        whose name a coverage warning carries.

        That is the difference between threading a dimension through the
        planner and forking it. #67's guarantee is that the preview and the
        apply cannot disagree because there is one planner; a multi-axis
        planner that re-derived any of the above would reintroduce exactly
        the drift #67 closed, one level up.

        ``scope`` comes from :meth:`_import_scope` for an axis that exists
        and :meth:`_empty_import_scope` for one the file is about to create.
        ``axis_name`` only ever changes wording: a coverage warning about a
        file with three axes has to say which one it is about.
        """
        records, errors = self._flatten_import_file(root_nodes, exam_context_id)
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
        weight_warnings = self._import_weight_warnings(
            records, coverage, axis_name=axis_name
        )

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
        axis_name: Optional[str] = None,
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

        ``axis_name`` names the axis in the coverage sentence for a
        whole-exam file (#241). Coverage is **per axis and never summed** —
        the axes are overlapping partitions of the same items, which is why
        the three Step 2 CK tables total 84–153%, 78–113% and 97–142% — so
        three separate sentences are informative and one combined number
        would be rescaling by another name. Left ``None`` the wording is
        byte-identical to the single-tree wording, because a single-tree
        import has no axis to name.
        """
        def subject(name: str) -> str:
            # Labelled once, here, rather than by prefixing the finished
            # strings at the whole-exam level. Prefixing would double-label
            # the coverage sentence below, which already names the axis
            # because its *claim* is about the axis rather than the file.
            if axis_name is None:
                return f'"{name}"'
            return f'"{name}" in the "{axis_name}" axis'

        problems: List[str] = []
        for record in records:
            name = record['name']
            low = _as_number(record['weight_low'])
            high = _as_number(record['weight_high'])
            if low is None or high is None:
                problems.append(
                    f'{subject(name)} has a weight that is not a number '
                    f'({record["weight_low"]!r}); imported as 0%'
                )
                continue
            if low > high:
                problems.append(
                    f'{subject(name)} has a weight low of {low:g} above its '
                    f'high of {high:g}; imported as written'
                )
            if low < 0 or high > 100:
                problems.append(
                    f'{subject(name)} has a weight of {low:g}–{high:g}%, '
                    f'outside 0–100%; imported as written'
                )

        warnings = problems[:_WEIGHT_WARNING_LIMIT]
        if len(problems) > _WEIGHT_WARNING_LIMIT:
            warnings.append(
                f'… and {len(problems) - _WEIGHT_WARNING_LIMIT} more subjects '
                f'with weights that look wrong'
            )

        if coverage['weighted_roots'] and not coverage['spans_100']:
            whose = (
                "The file's top-level weights" if axis_name is None
                else f'The "{axis_name}" axis\'s top-level weights'
            )
            warnings.append(
                f"{whose} total "
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

        **The whole apply is atomic** (#239). One ``self.transaction()``
        spans all four phases and the removals, so an import applies
        wholly or not at all.

        This docstring used to say the opposite, and gave a reason that
        was false by the time anyone read it: *"``BaseDatabase.transaction``
        commits rather than nesting a savepoint … making it genuinely
        atomic is a change to ``BaseDatabase``, not to import."*
        ``transaction()`` has been **re-entrant since #95**, which landed
        five hours after that sentence was written (``55a7fa4`` 17:28,
        ``2d64b5c`` 22:48, both 2026-09-16) and never updated it. Depth
        ≥ 2 issues a ``SAVEPOINT``; only the outermost block commits. So
        ``create_subject_node``, ``add_edge`` and
        ``delete_subject_subtree`` opening their own transactions is
        exactly what makes this work, rather than what prevented it.

        The note it replaced was right about one thing and it is kept:
        the *old* importer was not atomic either, so this is a new
        guarantee rather than a restored one.

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
        outcome = self._apply_subject_plan(
            plan, config.exam_name, dimension_id=dimension_id
        )

        if self.error_logger:
            self.error_logger.info(
                f"Subject import into exam {exam_context_id} "
                f"(dimension {dimension_id}): "
                f"{len(outcome['created_ids'])} added, "
                f"{len(outcome['updated_ids'])} updated, "
                f"{plan['counts']['unchanged']} unchanged, "
                f"{len(outcome['removed_ids'])} removed, "
                f"{plan['counts']['kept_in_use']} kept because entries "
                f"point at them",
                category=ErrorCategory.DATABASE,
            )

        result = dict(plan)
        result.update(outcome)
        return result

    def _apply_subject_plan(
        self,
        plan: Dict[str, Any],
        exam_name: str,
        *,
        dimension_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute one already-computed subject plan. The only write path.

        Split out of :meth:`apply_subject_import` so a whole-exam import
        (#241) can execute **the plan the student was shown** for each axis
        instead of calling the public apply and re-planning. Re-planning
        would be the drift #67 closed, reintroduced one level up: the plan
        that ran would be a second derivation of the plan that was
        previewed, and the two could differ — a whole-exam apply creates
        dimensions and archives others between the preview and the writes,
        so the second derivation would not even be against the same state.

        ``dimension_id`` is passed rather than read from ``plan`` for one
        reason: an axis the file **creates** has no id at plan time, so
        ``plan['dimension_id']`` is ``None`` there and the caller supplies
        the id it got from :meth:`create_dimension`. It is the single value
        the apply legitimately knows better than the plan.

        Returns ``{imported_count, created_ids, updated_ids, removed_ids,
        delete_batch_ids, warnings}``.
        """
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

        # ONE transaction spanning every write (#239). The four phases and
        # the removals are a single composite: a failure that left three
        # subjects renamed, none created and the removal pass unreached is a
        # state no student can see or undo, and the whole-exam import makes
        # that composite much larger.
        #
        # Everything called from inside here opens its own transaction and
        # nests as a SAVEPOINT -- `create_subject_node`, `add_edge`,
        # `delete_subject_subtree`, and the narrow blocks in the helpers. That
        # is #95's re-entrancy, and
        # `tests/database/test_no_bare_commit_inside_a_transaction.py` is what
        # keeps it true: a bare `conn.commit()` becoming reachable from here
        # would end this block and make its rollback a no-op silently.
        with self.transaction():
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

        return {
            'imported_count': plan['file_node_count'],
            'created_ids': created_ids,
            'updated_ids': updated_ids,
            'removed_ids': removed_ids,
            'delete_batch_ids': delete_batch_ids,
            'warnings': warnings,
        }

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

    # ------------------------------------------------------------------
    # The whole-exam import (#66 Wave 3, issue #241)
    #
    # One file describes the whole exam: a top-level ``dimensions`` list,
    # each entry an axis carrying its own identity and its own tree. Real
    # blueprints classify the same questions along several axes at once --
    # Step 2 CK publishes System, Discipline and Physician Task as three
    # tables over one item pool -- and importing them one axis at a time
    # means the student re-runs the same dialog three times and WIMI never
    # learns that the axes belong together.
    #
    # **Everything here delegates.** Axis matching is the only new
    # semantics; the subjects under each axis are planned by
    # ``_plan_subject_tree`` and written by ``_apply_subject_plan``, the
    # same two methods a single-tree import uses. That is #67's guarantee
    # -- one planner, and an apply that re-derives nothing -- held one
    # level up. A multi-axis planner that re-implemented survival, matching
    # or removal would reintroduce exactly the preview/apply drift #67
    # closed, and it would do it in the path that can archive three trees
    # at once.
    # ------------------------------------------------------------------

    def _read_axis_declarations(
        self,
        dimensions: Any,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Read the file's ``dimensions`` list into axis records.

        Defects are **errors**, not skips, for #61's reason: an import that
        quietly drops half a file is how that bug happened.

        Two of them have no subject-level counterpart, and both come from
        the schema rather than from taste. ``exam_dimensions`` carries
        ``UNIQUE(exam_id, name)``, so two axes sharing a name is a file
        asking for something the table cannot hold -- where two *subjects*
        sharing a name is merely a tree the matcher leaves unmatched. And
        two axes sharing an ``id`` is refused for the same reason two
        subjects sharing one is: the second would fall through to a create
        that then writes an ``import_id`` the first already holds.

        Inside an axis, ``root_nodes`` and ``subjects`` are both accepted.
        #61 reconciled those two spellings at the top level and the same
        file conventions apply one level down; reconciling them here keeps
        that in one place per level rather than per caller.
        """
        axes: List[Dict[str, Any]] = []
        errors: List[str] = []
        seen_ids: Dict[str, str] = {}
        seen_names: Dict[str, str] = {}

        for index, raw in enumerate(dimensions or []):
            where = f'Dimension {index + 1} in the file'
            if not isinstance(raw, dict):
                errors.append(f'{where} is not an object')
                continue
            name = str(raw.get('name', '') or '').strip()
            if not name:
                errors.append(f'{where} has no name')
                continue

            import_id = self._import_id_of(raw)
            if import_id is not None and import_id in seen_ids:
                errors.append(
                    f'Two dimensions share id "{import_id}": '
                    f'"{seen_ids[import_id]}" and "{name}"'
                )
                continue
            lowered = name.lower()
            if lowered in seen_names:
                errors.append(
                    f'Two dimensions in the file are named "{name}". An exam '
                    f'cannot have two dimensions with the same name.'
                )
                continue
            if import_id is not None:
                seen_ids[import_id] = name
            seen_names[lowered] = name

            root_nodes = raw.get('root_nodes')
            if not isinstance(root_nodes, list):
                root_nodes = raw.get('subjects')
            if not isinstance(root_nodes, list):
                root_nodes = []

            description = raw.get('description')
            if description is not None and not isinstance(description, str):
                description = str(description)

            axes.append({
                'file_index': index,
                'name': name,
                'import_id': import_id,
                # Which keys the file actually spelled. An omitted flag on
                # an axis that already exists must mean "leave it alone",
                # not "reset it to the default" -- the file is a blueprint
                # of the exam's structure, not of every setting the student
                # has since changed. On a *new* axis there is nothing to
                # leave alone, so `create_dimension`'s defaults apply.
                'declared': [
                    key for key in
                    ('display_order', 'is_required', 'allow_multiple',
                     'description')
                    if key in raw
                ],
                'display_order': raw.get('display_order'),
                'is_required': bool(raw.get('is_required', True)),
                'allow_multiple': bool(raw.get('allow_multiple', False)),
                'description': description,
                'root_nodes': root_nodes,
                # A misspelled `root_nodes` key arrives as an empty list,
                # and "this axis lists no subjects" must never read as
                # "archive this axis's whole tree" (#67's hazard, one level
                # up). `_plan_subject_tree`'s `empty_file` already makes it
                # remove nothing; this is the flag that lets the preview
                # *say* so instead of reporting a silent no-op.
                'declares_no_subjects': not root_nodes,
            })

        return axes, errors

    def _dimension_entry_counts(
        self,
        dimension_ids: List[int],
    ) -> Dict[int, Dict[str, int]]:
        """``{dimension_id: {'subjects': n, 'entries': n}}`` over active rows.

        ``entries`` counts **distinct** entries, and counts every mapping
        type rather than only ``primary``. This is a "does anything point
        into this axis" question, not a measurement -- #13's
        counting-is-primary-only rule governs totals, and archiving an axis
        whose subjects only ever appear as secondary tags would still take
        those tags away from the student's entries.
        """
        if not dimension_ids:
            return {}
        placeholders = ','.join(['?'] * len(dimension_ids))
        out = {
            did: {'subjects': 0, 'entries': 0} for did in dimension_ids
        }
        for row in self.fetchall(
            f"SELECT dimension_id, COUNT(*) AS n FROM subject_nodes "
            f"WHERE dimension_id IN ({placeholders}) AND status = 'active' "
            f"GROUP BY dimension_id",
            tuple(dimension_ids),
        ):
            out[row['dimension_id']]['subjects'] = row['n']
        for row in self.fetchall(
            f"""
            SELECT sn.dimension_id AS dimension_id,
                   COUNT(DISTINCT esm.question_entry_id) AS n
            FROM subject_nodes sn
            JOIN entry_subject_mappings esm ON esm.subject_node_id = sn.id
            WHERE sn.dimension_id IN ({placeholders})
              AND sn.status = 'active'
            GROUP BY sn.dimension_id
            """,
            tuple(dimension_ids),
        ):
            out[row['dimension_id']]['entries'] = row['n']
        return out

    def plan_whole_exam_import(
        self,
        exam_context_id: int,
        dimensions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Work out exactly what importing a whole-exam file would do. Read-only.

        Single source of truth for the multi-axis case, the way
        :meth:`plan_subject_import` is for one tree:
        :meth:`apply_whole_exam_import` consumes this and re-derives
        nothing (#67, decision 2.4).

        **Axis matching, in order.** An axis with an ``id`` matches the
        active dimension carrying that ``import_id`` (m025), whatever it is
        currently called -- that is what makes a renamed axis a rename
        rather than a remove-plus-add, which at this level would archive
        every tree under it. Failing that it matches by name, and an axis
        matched by name while carrying an id **adopts** it, so an exam set
        up before the field existed is not stranded (decision 2.3).

        **Axis survival, bottom-up (decision 2.1).** An axis survives if
        the file declares it, or any subject in it carries entries. #67's
        third clause -- *or anything beneath it survives* -- collapses into
        the second one here rather than being omitted: every subject in an
        axis's tree is itself in that axis, because cross-dimensional edges
        are a Non-Goal, so "something beneath it survives" and "some
        subject in it carries entries" select the same axes. Kept axes are
        reported as ``dimensions_kept_in_use``, the way ``kept_in_use``
        reports kept subjects.

        **A file declaring no dimensions removes none.** #67's *"an empty
        file removes nothing"* one level up. This is the destructive
        reading of a truncated download or a mis-typed key, and it is never
        the one the student meant.

        **Per-axis scope, with no bleed.** Each axis is planned against
        ``_import_scope(exam_name, its dimension)``, or
        ``_empty_import_scope()`` for an axis the file creates. A subject
        in the System tree is therefore not a match candidate for a subject
        in the Task tree even with an identical name, and the dimensionless
        subjects -- the ``dimension_id IS NULL`` partition -- are in no
        axis's scope at all and are never touched.

        **Coverage is per axis and is never summed** (#64, and §10 of
        ``WHOLE_EXAM_IMPORT.md``). The axes are overlapping partitions of
        one item pool, which is why the three real Step 2 CK tables total
        84-153%, 78-113% and 97-142%. A combined number would be rescaling
        by another name, so there is deliberately **no top-level
        ``coverage`` key** -- an absence, and
        ``tests/database/test_whole_exam_import.py`` asserts it.

        **``display_order`` is resolved here, not reported as a change.**
        ``exam_dimensions`` carries ``UNIQUE(exam_id, display_order)`` as
        well as ``UNIQUE(exam_id, name)``, and a file whose orders collide
        with a kept axis must be resolved by the planner rather than
        surfaced as an ``IntegrityError`` (decision 2.2). So the plan
        carries ``final_order``: the declared axes in the order the file
        asks for, then the kept axes in the order they already had,
        numbered 1..N. The apply writes it with
        :meth:`reorder_dimensions`, which is #211's park-and-assign --
        reusing that scheme rather than inventing a second one.

        Returns a dict of:

        - ``axes`` -- one record per declared axis, each carrying its
          ``action`` (``'add'``/``'update'``/``'unchanged'``), its matched
          ``dimension_id`` and ``matched_by``, a ``changes`` map, its own
          ``coverage``, and ``plan`` -- the full subject plan for that axis,
          exactly as :meth:`plan_subject_import` would return it.
        - ``dimensions_added`` / ``dimensions_updated`` /
          ``dimensions_unchanged`` -- views of the above.
        - ``dimensions_removed`` -- axes the import will archive, with the
          subject count that goes with each.
        - ``dimensions_kept_in_use`` -- axes kept because entries point
          into them, with ``entry_count`` and ``subject_count``.
        - ``final_order`` -- every surviving axis and the ``display_order``
          it will hold.
        - ``declares_no_dimensions`` -- the empty-list case, which removes
          nothing.
        - ``dimensionless_subject_count`` -- active subjects in no
          dimension. Left alone; reported so that is visible rather than
          silent.
        - ``errors`` -- file defects that stop the import.
        - ``warnings`` -- every axis's weight warnings, each already naming
          its axis, plus a note when subjects sit outside every axis.
        - ``counts`` -- axis counts, and the subject counts summed across
          axes. ``entries_affected`` is counted **distinct across all
          axes**, never summed: one entry tagged in both System and Task
          sits on a kept subject in each, and adding the two would report
          it twice.

        Raises:
            SubjectNodeError: if ``exam_context_id`` names no exam.
        """
        config = self.get_exam_context_config(exam_context_id)
        if not config:
            raise SubjectNodeError(f"Exam context {exam_context_id} not found")
        exam_name = config.exam_name

        axes, errors = self._read_axis_declarations(dimensions)
        declares_no_dimensions = not axes

        existing = self.get_exam_dimensions(exam_context_id)
        by_id = {row['id']: row for row in existing}
        by_import_id: Dict[str, int] = {}
        by_name: Dict[str, int] = {}
        for row in existing:
            if row.get('import_id'):
                by_import_id.setdefault(str(row['import_id']), row['id'])
            by_name.setdefault((row['name'] or '').strip().lower(), row['id'])

        claimed: set = set()

        # Pass 1 -- ids, before any name can claim a dimension. Same
        # ordering argument as the subject matcher: a name match that took
        # a dimension out from under the axis carrying its import_id would
        # send that axis to "add", and the add would write an import_id the
        # claimed row still holds -- a unique-index failure on a file with
        # nothing wrong with it.
        for axis in axes:
            axis['dimension_id'] = None
            axis['matched_by'] = None
            if not axis['import_id']:
                continue
            candidate = by_import_id.get(axis['import_id'])
            if candidate is not None and candidate not in claimed:
                claimed.add(candidate)
                axis['dimension_id'] = candidate
                axis['matched_by'] = 'id'

        # Pass 2 -- name.
        for axis in axes:
            if axis['dimension_id'] is not None:
                continue
            candidate = by_name.get(axis['name'].lower())
            if candidate is not None and candidate not in claimed:
                claimed.add(candidate)
                axis['dimension_id'] = candidate
                axis['matched_by'] = 'name'

        # ---- what each declared axis does to its dimension row ---------
        for axis in axes:
            if axis['dimension_id'] is None:
                axis['action'] = 'add'
                axis['changes'] = {}
                continue
            current = by_id[axis['dimension_id']]
            changes: Dict[str, List[Any]] = {}
            if (current['name'] or '') != axis['name']:
                changes['name'] = [current['name'], axis['name']]
            for key in ('is_required', 'allow_multiple'):
                if key not in axis['declared']:
                    continue
                if bool(current[key]) != bool(axis[key]):
                    changes[key] = [bool(current[key]), bool(axis[key])]
            if 'description' in axis['declared']:
                was = current['description'] or None
                now = axis['description'] or None
                if was != now:
                    changes['description'] = [current['description'],
                                              axis['description']]
            if axis['import_id'] and not current.get('import_id'):
                changes['import_id'] = [None, axis['import_id']]
            # `display_order` is deliberately absent from `changes`. It is
            # resolved into `final_order` below and written by
            # `reorder_dimensions`, because writing it one row at a time is
            # what UNIQUE(exam_id, display_order) refuses (#211).
            axis['changes'] = changes
            axis['action'] = 'update' if changes else 'unchanged'

        # ---- axes the file did not declare -----------------------------
        unmatched = [row for row in existing if row['id'] not in claimed]
        axis_stats = self._dimension_entry_counts([row['id'] for row in unmatched])

        dimensions_kept_in_use: List[Dict[str, Any]] = []
        dimensions_removed: List[Dict[str, Any]] = []
        if not declares_no_dimensions:
            for row in unmatched:
                stats = axis_stats.get(row['id'], {'subjects': 0, 'entries': 0})
                record = {
                    'dimension_id': row['id'],
                    'name': row['name'],
                    'display_order': row['display_order'],
                    'subject_count': stats['subjects'],
                    'entry_count': stats['entries'],
                }
                if stats['entries']:
                    dimensions_kept_in_use.append(record)
                else:
                    dimensions_removed.append(record)

        # ---- the order every surviving axis ends up in (decision 2.2) ---
        def file_order_key(axis: Dict[str, Any]) -> Tuple[int, float, int]:
            declared = _as_number(axis['display_order'])
            return (
                0 if declared is not None else 1,
                declared if declared is not None else 0.0,
                axis['file_index'],
            )

        final_order: List[Dict[str, Any]] = []
        for axis in sorted(axes, key=file_order_key):
            final_order.append({
                'file_index': axis['file_index'],
                'dimension_id': axis['dimension_id'],
                'name': axis['name'],
                'source': 'file',
            })
        for record in sorted(
            dimensions_kept_in_use,
            key=lambda r: (r['display_order'] or 0, r['dimension_id']),
        ):
            final_order.append({
                'file_index': None,
                'dimension_id': record['dimension_id'],
                'name': record['name'],
                'source': 'kept',
            })
        for position, item in enumerate(final_order, start=1):
            item['display_order'] = position

        # A name the schema cannot hold, reported as a sentence rather than
        # left to surface as an IntegrityError from three frames down
        # (decision 2.2, and the courtesy `create_subject_relation`
        # extends). The file's own duplicates were caught in
        # `_read_axis_declarations`; what is left is a declared axis whose
        # name a KEPT axis is still using.
        final_names: Dict[str, str] = {}
        for item in final_order:
            key = item['name'].strip().lower()
            if key in final_names:
                errors.append(
                    f'The file gives a dimension the name "{item["name"]}", '
                    f'which another dimension of this exam is already using '
                    f'and the import is keeping because entries point into '
                    f'it. Rename one of them.'
                )
            final_names[key] = item['name']

        # ---- the subjects under each axis, through the shared planner ---
        for axis in axes:
            scope = (
                self._import_scope(exam_name, axis['dimension_id'])
                if axis['dimension_id'] is not None
                else self._empty_import_scope()
            )
            plan = self._plan_subject_tree(
                exam_context_id,
                exam_name,
                axis['root_nodes'],
                scope,
                dimension_id=axis['dimension_id'],
                axis_name=axis['name'],
            )
            axis['plan'] = plan
            axis['coverage'] = plan['coverage']
            for message in plan['errors']:
                errors.append(f'"{axis["name"]}": {message}')

        warnings: List[str] = []
        for axis in axes:
            warnings.extend(axis['plan']['warnings'])

        # Subjects in no dimension at all are in no axis's scope, so this
        # import cannot add to them, update them or remove them. Said out
        # loud because #67's rules are enforced by absences and an unstated
        # rule is the one that gets "fixed" back -- and because a student
        # whose legacy tree is invisible to a whole-exam file deserves to
        # know that rather than conclude the import lost it.
        dimensionless = self.fetchone(
            "SELECT COUNT(*) AS n FROM subject_nodes "
            "WHERE exam_context = ? AND dimension_id IS NULL "
            "  AND status = 'active'",
            (exam_name,),
        )
        dimensionless_subject_count = dimensionless['n'] if dimensionless else 0
        if dimensionless_subject_count and not declares_no_dimensions:
            warnings.append(
                f'This exam has {dimensionless_subject_count} '
                f'subject{"s" if dimensionless_subject_count != 1 else ""} '
                f'that are not in any dimension. A whole-exam file describes '
                f'the dimensions, so they are left exactly as they are -- '
                f'neither updated nor removed.'
            )

        # `entries_affected` is DISTINCT across every axis, never the sum.
        # An entry tagged in both System and Task sits on a kept subject in
        # each, and summing the per-axis figures would count it twice --
        # the same non-additivity the subject sunburst carries a tooltip
        # for (#6).
        kept_subject_ids: List[int] = []
        for axis in axes:
            kept_subject_ids.extend(
                item['id'] for item in axis['plan']['kept_in_use']
            )
        entries_affected = 0
        if kept_subject_ids:
            placeholders = ','.join(['?'] * len(kept_subject_ids))
            row = self.fetchone(
                f"SELECT COUNT(DISTINCT question_entry_id) AS c "
                f"FROM entry_subject_mappings "
                f"WHERE subject_node_id IN ({placeholders})",
                tuple(kept_subject_ids),
            )
            entries_affected = row['c'] if row else 0

        def summed(key: str) -> int:
            return sum(axis['plan']['counts'][key] for axis in axes)

        added = [a for a in axes if a['action'] == 'add']
        updated = [a for a in axes if a['action'] == 'update']
        unchanged = [a for a in axes if a['action'] == 'unchanged']

        def describe_axis(axis: Dict[str, Any]) -> Dict[str, Any]:
            return {
                'file_index': axis['file_index'],
                'dimension_id': axis['dimension_id'],
                'name': axis['name'],
                'import_id': axis['import_id'],
                'matched_by': axis['matched_by'],
                'changes': axis['changes'],
                'declares_no_subjects': axis['declares_no_subjects'],
                'coverage': axis['coverage'],
                'counts': axis['plan']['counts'],
            }

        return {
            'exam_context_id': exam_context_id,
            'exam_name': exam_name,
            'whole_exam': True,
            'axes': axes,
            'axis_count': len(axes),
            'declares_no_dimensions': declares_no_dimensions,
            'dimensions_added': [describe_axis(a) for a in added],
            'dimensions_updated': [describe_axis(a) for a in updated],
            'dimensions_unchanged': [describe_axis(a) for a in unchanged],
            'dimensions_removed': dimensions_removed,
            'dimensions_kept_in_use': dimensions_kept_in_use,
            'final_order': final_order,
            'dimensionless_subject_count': dimensionless_subject_count,
            'entries_affected': entries_affected,
            'errors': errors,
            'warnings': warnings,
            'counts': {
                'dimensions_added': len(added),
                'dimensions_updated': len(updated),
                'dimensions_unchanged': len(unchanged),
                'dimensions_removed': len(dimensions_removed),
                'dimensions_kept_in_use': len(dimensions_kept_in_use),
                'added': summed('added'),
                'updated': summed('updated'),
                'unchanged': summed('unchanged'),
                'renamed': summed('renamed'),
                'moved': summed('moved'),
                'removed': summed('removed'),
                'kept_in_use': summed('kept_in_use'),
                'kept_as_ancestor': summed('kept_as_ancestor'),
                'entries_affected': entries_affected,
            },
        }

    def apply_whole_exam_import(
        self,
        exam_context_id: int,
        dimensions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute :meth:`plan_whole_exam_import`'s plan.

        Nothing is re-derived. Each axis's subjects are written by
        :meth:`_apply_subject_plan` from **the plan object the preview was
        built from**, not from a fresh call to the planner -- which is why
        that method was split out. Re-planning here would be #67's drift
        reintroduced at the worst possible level: this apply creates
        dimensions and archives others, so a second derivation would not
        even be against the same state as the first.

        **The whole thing is one transaction**, for #239's reason scaled up.
        A whole-exam apply is a far larger composite than a single tree --
        three axes created, one tree filled, another archived -- and a
        half-applied blueprint is a state no student can see or undo.
        Everything called from inside nests as a ``SAVEPOINT`` (#95).

        Six phases, and the order of the first two is load-bearing:

        **A. Park the names that are changing.** ``exam_dimensions`` has
        ``UNIQUE(exam_id, name)``. A file can legitimately swap two axes'
        names, or rename an axis and introduce a new one with the old name
        -- reachable whenever the file matches a dimension by ``import_id``
        and then declares a second axis under the name that dimension is
        currently using. Both land on the constraint if the writes go
        straight in. This is the same park-and-assign shape #211 needed for
        ``display_order``, for the same underlying reason: SQLite checks a
        UNIQUE index per row as the statement runs and has no deferred
        constraints. Parking is unconditional on a rename rather than
        conditional on a detected collision, because the case analysis is
        exactly what gets it wrong.

        **B. Create the axes the exam does not have**, at temporary orders
        above everything in use. A real order cannot be assigned yet for
        the same UNIQUE reason, and phase F assigns it properly.

        **C. The matched axes' own columns**, including adopting an
        ``import_id`` (m025) and taking the final name out of the park.

        **D. The subjects under each axis**, through
        :meth:`_apply_subject_plan`. ``dimension_id`` is supplied by this
        method rather than read from the axis plan, because an axis the file
        creates had no id when it was planned.

        **E. Archive the axes the file dropped**, through
        :meth:`archive_dimension` -- which is itself composed of
        :meth:`delete_subject_subtree` calls, so #67's *never a second path*
        holds at both levels. Removals last, mirroring the single-tree
        apply.

        **F. One :meth:`reorder_dimensions` over the survivors**, which is
        #211's park-and-assign. The plan already decided the order; this
        writes it.

        Returns the plan, plus ``created_dimension_ids``,
        ``updated_dimension_ids``, ``removed_dimension_ids``,
        ``dimension_delete_batch_ids``, the subject-level ``created_ids`` /
        ``updated_ids`` / ``removed_ids`` / ``delete_batch_ids`` pooled
        across axes, ``axis_results`` (the same figures per axis),
        ``imported_count`` and ``warnings``.
        """
        plan = self.plan_whole_exam_import(exam_context_id, dimensions)
        if plan['errors']:
            raise ValidationError('; '.join(plan['errors']))

        config = self.get_exam_context_config(exam_context_id)
        exam_name = config.exam_name

        warnings: List[str] = list(plan['warnings'])
        created_dimension_ids: List[int] = []
        updated_dimension_ids: List[int] = []
        removed_dimension_ids: List[int] = []
        dimension_delete_batch_ids: List[str] = []
        created_ids: List[int] = []
        updated_ids: List[int] = []
        removed_ids: List[int] = []
        delete_batch_ids: List[str] = []
        axis_results: List[Dict[str, Any]] = []
        imported_count = 0

        # file_index -> the dimension this axis ends up in. Seeded with the
        # matches the planner made; phase B fills in the rest. Kept here
        # rather than written back into the plan, so the plan stays the
        # read-only thing the preview showed.
        resolved: Dict[int, int] = {
            axis['file_index']: axis['dimension_id']
            for axis in plan['axes'] if axis['dimension_id'] is not None
        }

        with self.transaction():
            # Phase A -- park every name that is about to change.
            for axis in plan['axes']:
                if 'name' in axis['changes']:
                    self.update_dimension(
                        axis['dimension_id'],
                        name=f'__wimi_import_{uuid.uuid4().hex}',
                    )

            # Phase B -- create the axes the exam does not have, at orders
            # nothing can already hold. `MAX` is taken over every row of the
            # exam including archived ones, whose parked `-id` orders are in
            # the same UNIQUE index (#210).
            highest = self.fetchone(
                '-- includes-archived (#210): a temporary order must clear '
                'every row in the UNIQUE index, parked ones included\n'
                'SELECT MAX(display_order) AS hi FROM exam_dimensions '
                'WHERE exam_id = ?',
                (exam_context_id,),
            )
            next_free = int((highest['hi'] if highest else 0) or 0) + 1
            for axis in plan['axes']:
                if axis['action'] != 'add':
                    continue
                dimension_id = self.create_dimension(
                    exam_id=exam_context_id,
                    name=axis['name'],
                    display_order=next_free,
                    is_required=axis['is_required'],
                    allow_multiple=axis['allow_multiple'],
                    description=axis['description'],
                )
                next_free += 1
                if axis['import_id']:
                    self._write_dimension_import_id(
                        dimension_id, axis['import_id'])
                resolved[axis['file_index']] = dimension_id
                created_dimension_ids.append(dimension_id)

            # Phase C -- the matched axes' own columns.
            for axis in plan['axes']:
                if axis['action'] != 'update':
                    continue
                changes = axis['changes']
                fields: Dict[str, Any] = {}
                if 'name' in changes:
                    fields['name'] = axis['name']
                if 'is_required' in changes:
                    fields['is_required'] = axis['is_required']
                if 'allow_multiple' in changes:
                    fields['allow_multiple'] = axis['allow_multiple']
                if 'description' in changes:
                    fields['description'] = axis['description']
                if fields:
                    self.update_dimension(axis['dimension_id'], **fields)
                if 'import_id' in changes:
                    self._write_dimension_import_id(
                        axis['dimension_id'], axis['import_id'])
                updated_dimension_ids.append(axis['dimension_id'])

            # Phase D -- the subjects under each axis, through the same
            # apply a single-tree import uses.
            for axis in plan['axes']:
                dimension_id = resolved[axis['file_index']]
                outcome = self._apply_subject_plan(
                    axis['plan'], exam_name, dimension_id=dimension_id
                )
                created_ids.extend(outcome['created_ids'])
                updated_ids.extend(outcome['updated_ids'])
                removed_ids.extend(outcome['removed_ids'])
                delete_batch_ids.extend(outcome['delete_batch_ids'])
                imported_count += outcome['imported_count']
                for message in outcome['warnings']:
                    if message not in warnings:
                        warnings.append(message)
                axis_results.append({
                    'file_index': axis['file_index'],
                    'name': axis['name'],
                    'dimension_id': dimension_id,
                    'created_ids': outcome['created_ids'],
                    'updated_ids': outcome['updated_ids'],
                    'removed_ids': outcome['removed_ids'],
                    'delete_batch_ids': outcome['delete_batch_ids'],
                    'imported_count': outcome['imported_count'],
                })

            # Phase E -- archive the axes the file dropped, trees and all.
            for record in plan['dimensions_removed']:
                result = self.archive_dimension(record['dimension_id'])
                removed_dimension_ids.append(record['dimension_id'])
                if result.get('batch_id'):
                    dimension_delete_batch_ids.append(result['batch_id'])

            # Phase F -- one park-and-assign over the survivors (#211).
            final_ids = [
                resolved[item['file_index']] if item['file_index'] is not None
                else item['dimension_id']
                for item in plan['final_order']
            ]
            if final_ids:
                self.reorder_dimensions(exam_context_id, final_ids)

        if self.error_logger:
            self.error_logger.info(
                f"Whole-exam import into exam {exam_context_id}: "
                f"{len(created_dimension_ids)} dimensions added, "
                f"{len(updated_dimension_ids)} updated, "
                f"{len(removed_dimension_ids)} archived, "
                f"{plan['counts']['dimensions_kept_in_use']} kept because "
                f"entries point into them; "
                f"{len(created_ids)} subjects added, "
                f"{len(updated_ids)} updated, {len(removed_ids)} removed",
                category=ErrorCategory.DATABASE,
            )

        result = dict(plan)
        result.update({
            'imported_count': imported_count,
            'created_dimension_ids': created_dimension_ids,
            'updated_dimension_ids': updated_dimension_ids,
            'removed_dimension_ids': removed_dimension_ids,
            'dimension_delete_batch_ids': dimension_delete_batch_ids,
            'created_ids': created_ids,
            'updated_ids': updated_ids,
            'removed_ids': removed_ids,
            'delete_batch_ids': delete_batch_ids,
            'axis_results': axis_results,
            'warnings': warnings,
        })
        return result

    def _write_dimension_import_id(self, dimension_id: int, import_id: str) -> None:
        """Set ``exam_dimensions.import_id`` (m025).

        A direct write because neither ``create_dimension`` nor
        ``update_dimension`` carries the column, and widening their
        signatures for a field only the importer writes would advertise it
        to the exam wizard, which has no stable id to offer. This mirrors
        what the subject apply does for ``subject_nodes.import_id``.
        """
        self.execute(
            'UPDATE exam_dimensions SET import_id = ? WHERE id = ?',
            (import_id, dimension_id),
        )
