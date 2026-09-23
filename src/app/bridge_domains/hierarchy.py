"""WIMI Subject Hierarchy bridge operations."""
import json
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class HierarchyBridgeMixin:
    """Bridge mixin for subject hierarchy operations. Composed into DatabaseBridge."""

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getSubjectHierarchy(self, exam_context_id: int) -> str:
        """
        Get full subject hierarchy as nested JSON.

        Args:
            exam_context_id: ID of the exam context

        Returns:
            JSON response with nested hierarchy
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            root_nodes = self.user_db.get_subject_hierarchy(config.exam_name)

            # Batch-load aliases for the whole exam (one query) and group by
            # subject_node_id so node_to_dict can attach them without N+1.
            # Used by tree-editor and entry-browser search to match by alias.
            aliases_by_subject: dict = {}
            for alias in self.user_db.get_aliases_for_exam(config.exam_name):
                aliases_by_subject.setdefault(
                    alias.subject_node_id, []
                ).append(alias.alias_name)

            def node_to_dict(node):
                node_aliases = aliases_by_subject.get(node.id, [])
                return {
                    'id': node.id,
                    'name': node.name,
                    'level_type': node.level_type,
                    'sort_order': node.sort_order,
                    # Issue #67: the stable id the import file gave this
                    # subject, if any. Export writes it back out as the
                    # file's ``id`` so a round trip stays matchable;
                    # ``id`` above is the database row id and is not it.
                    'import_id': getattr(node, 'import_id', None),
                    'weight': node.exam_weight_low or 0,
                    'exam_weight_low': node.exam_weight_low,
                    'exam_weight_high': node.exam_weight_high,
                    'aliases': node_aliases,
                    'aliasesString': ' '.join(node_aliases),
                    # Polyhierarchy: TRUE when this row is a non-primary
                    # appearance of a multi-parent node. The renderer
                    # should mark these with an "alias chip" — the
                    # canonical/primary appearance lives elsewhere in
                    # the same tree response. See POLYHIERARCHY_MIGRATION
                    # §7.1.
                    'is_alias_appearance': getattr(
                        node, 'is_alias_appearance', False
                    ),
                    'children': [node_to_dict(c) for c in (node.children or [])]
                }

            data = {
                'exam_context_id': exam_context_id,
                'exam_name': config.exam_name,
                'root_nodes': [node_to_dict(n) for n in root_nodes]
            }

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(f'Error getting subject hierarchy: {e}', {'exam_context_id': exam_context_id})
            return serialize_response(False, error=f'Failed to get hierarchy: {e}')

    def _derive_child_level_type(
        self, exam_context_id: Optional[int], parent_id: Optional[int]
    ) -> Optional[str]:
        """The level a new child of ``parent_id`` should be stored at.

        Issue #82: the child's level is one step below the parent's
        **stored** ``level_type``, never its depth — in a polyhierarchy a
        node has no single depth, so a depth-derived level is ambiguous
        as well as inaccurate. Both fall-throughs repeat the parent's own
        level rather than inventing one:

        - the parent is already at the bottom of the list, so there is no
          next level;
        - the parent's ``level_type`` is not in the list at all. An
          imported outline brings its own vocabulary (Section / Domain /
          Skill), and ``update_hierarchy_level`` renames a level without
          back-filling ``subject_nodes``, so every existing node is
          instantly carrying a name the list no longer has. This branch
          used to swallow the ``ValueError`` and fall through to the
          literal ``'System'`` — substituting the app's vocabulary for
          the user's. There is no derivable "one below Domain";
          repeating it is the honest answer, and it is what the tree
          editor's Add Child modal pre-selects too
          (``suggestChildLevelName`` in tree_editor.js).

        Returns ``None`` when there is nothing to derive from — no
        parent, no such active parent, or a parent with no stored level —
        leaving the caller's own default in place.

        Issue #106: this is a shared helper rather than a private step of
        ``createSubjectNode`` because ``createSubjectNodeWithWeight``
        (``bridge_domains/weights.py``) needs the same answer, and had
        been defaulting an omitted ``level_type`` to the literal
        ``'System'`` — so a child of a ``Topic`` was created as a
        ``System`` through one slot and a ``Subtopic`` through the other.
        Mixins share the composed instance, so it is reachable there as
        ``self._derive_child_level_type(...)`` with no import. Keep the
        two callers in step: any change here must hold for both.
        """
        if not parent_id:
            return None

        parent_row = self.user_db.fetchone(
            "SELECT level_type FROM subject_nodes "
            "WHERE id = ? AND status = 'active'",
            (parent_id,)
        )
        if not parent_row or not parent_row['level_type']:
            return None

        parent_level = parent_row['level_type']
        levels = self.user_db.get_hierarchy_levels(exam_context_id)
        level_names = [l.level_name for l in levels]
        if parent_level in level_names:
            parent_idx = level_names.index(parent_level)
            if parent_idx + 1 < len(level_names):
                return level_names[parent_idx + 1]
        return parent_level

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createSubjectNode(self, node_data_json: str) -> str:
        """
        Create a new subject node.

        Args:
            node_data_json: JSON string with node data

        Returns:
            JSON response with created node
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(node_data_json)

            exam_context_id = data.get('exam_context_id')
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            parent_id = data.get('parent_id')
            dimension_id = data.get('dimension_id')

            if parent_id and not dimension_id:
                parent_row = self.user_db.fetchone(
                    "SELECT dimension_id FROM subject_nodes WHERE id = ? AND status = 'active'",
                    (parent_id,)
                )
                if parent_row and parent_row['dimension_id']:
                    dimension_id = parent_row['dimension_id']

            if parent_id and 'level_type' not in data:
                derived_level = self._derive_child_level_type(
                    exam_context_id, parent_id
                )
                if derived_level:
                    data['level_type'] = derived_level

            node = self.user_db.create_subject_node(
                exam_context=config.exam_name,
                name=data['name'],
                level_type=data.get('level_type', 'System'),
                parent_id=parent_id,
                exam_weight_low=data.get('weight', 0),
                exam_weight_high=data.get('weight', 0),
                sort_order=data.get('sort_order', 1),
                dimension_id=dimension_id
            )

            return serialize_response(True, data={
                'id': node.id,
                'name': node.name,
                'level_type': node.level_type,
                'parent_id': node.parent_id,
                'weight': node.exam_weight_low or 0,
                'sort_order': node.sort_order
            })

        except Exception as e:
            self._log_error(
                f'Error creating subject node: {e}',
                {
                    'node_data_json_len': len(node_data_json) if node_data_json else 0,
                },
            )
            return serialize_response(False, error=f'Failed to create node: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateSubjectNode(self, node_id: int, updates_json: str) -> str:
        """
        Update subject node properties.

        Args:
            node_id: ID of the node to update
            updates_json: JSON string with updates

        Returns:
            JSON response with updated node
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            updates = json.loads(updates_json)

            node = self.user_db.get_subject_node(node_id)
            if not node:
                return serialize_response(False, error='Subject node not found')

            update_fields = []
            params = []

            if 'name' in updates:
                update_fields.append('name = ?')
                params.append(updates['name'])
            if 'sort_order' in updates:
                update_fields.append('sort_order = ?')
                params.append(updates['sort_order'])
            if 'level_type' in updates:
                update_fields.append('level_type = ?')
                params.append(updates['level_type'])
            if 'exam_weight_low' in updates:
                update_fields.append('exam_weight_low = ?')
                params.append(updates['exam_weight_low'])
            if 'exam_weight_high' in updates:
                update_fields.append('exam_weight_high = ?')
                params.append(updates['exam_weight_high'])
            if 'weight_source' in updates:
                update_fields.append('weight_source = ?')
                params.append(updates['weight_source'])
            if 'weight_locked' in updates:
                update_fields.append('weight_locked = ?')
                params.append(1 if updates['weight_locked'] else 0)

            if update_fields:
                update_fields.append('updated_at = CURRENT_TIMESTAMP')
                params.append(node_id)

                with self.user_db.transaction():
                    self.user_db.execute(f"""
                        UPDATE subject_nodes
                        SET {', '.join(update_fields)}
                        WHERE id = ?
                    """, tuple(params))

                    weight_changed = 'exam_weight_low' in updates or 'exam_weight_high' in updates
                    if weight_changed:
                        old_low = node.exam_weight_low
                        old_high = node.exam_weight_high
                        new_low = updates.get('exam_weight_low', old_low)
                        new_high = updates.get('exam_weight_high', old_high)

                        if new_low != new_high:
                            weight_value = (new_low + new_high) / 2
                            reason = f"Weight range updated: {old_low}%-{old_high}% → {new_low}%-{new_high}%"
                        else:
                            weight_value = new_low
                            reason = f"Weight updated: {old_low}% → {new_low}%"

                        try:
                            self.user_db.execute("""
                                INSERT INTO subject_node_weights (
                                    subject_node_id, weight_value, edited_by, edited_reason,
                                    previous_weight, change_type, affected_siblings
                                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                node_id,
                                weight_value,
                                'user',
                                reason,
                                old_low or 0,
                                'manual_edit',
                                '[]'
                            ))
                        except Exception as e:
                            self._log_error(
                                f'Could not record weight history: {e}',
                                {
                                    'node_id': node_id,
                                    'weight_value': weight_value,
                                    'previous_weight': old_low or 0,
                                },
                            )

            node = self.user_db.get_subject_node(node_id)

            # Graph dual-write for name or level_type changes
            if 'name' in updates or 'level_type' in updates:
                _node_id = node_id
                _new_name = node.name
                _new_level_type = node.level_type
                _full_path = self.user_db._build_subject_path(node_id)

                def _graph_write():
                    self.user_db._graph_execute(
                        "MATCH (s:Subject {sqlite_id: $id}) "
                        "SET s.name = $name, s.level_type = $level_type, s.full_path = $path",
                        {"id": _node_id, "name": _new_name,
                         "level_type": _new_level_type, "path": _full_path}
                    )
                    # If name changed, update full_path on all descendants
                    if 'name' in updates:
                        desc_result = self.user_db._graph_execute(
                            "MATCH (s:Subject {sqlite_id: $id})-[:HAS_CHILD*1..20]->(child:Subject) "
                            "RETURN child.sqlite_id",
                            {"id": _node_id}
                        )
                        desc_rows = self.user_db._graph_collect(desc_result)
                        for row in desc_rows:
                            child_id = row[0]
                            child_path = self.user_db._build_subject_path(child_id)
                            self.user_db._graph_execute(
                                "MATCH (s:Subject {sqlite_id: $id}) SET s.full_path = $path",
                                {"id": child_id, "path": child_path}
                            )
                self.user_db._dual_write_graph("update_subject_node", _graph_write)

            return serialize_response(True, data={
                'id': node.id,
                'name': node.name,
                'level_type': node.level_type,
                'parent_id': node.parent_id,
                'weight': node.exam_weight_low or 0,
                'exam_weight_low': node.exam_weight_low,
                'exam_weight_high': node.exam_weight_high,
                'weight_source': node.weight_source,
                'weight_locked': node.weight_locked,
                'sort_order': node.sort_order
            })

        except Exception as e:
            self._log_error(
                f'Error updating subject node: {e}',
                {
                    'node_id': node_id,
                    'updates_json_len': len(updates_json) if updates_json else 0,
                },
            )
            return serialize_response(False, error=f'Failed to update node: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getSubjectDeletePreview(self, node_id: int) -> str:
        """
        What deleting ``node_id`` would actually do. Read-only.

        Safe to call when the confirmation modal opens — it mutates
        nothing. Issue #15's decision 5: the modal has to state truthfully
        what will happen before the user confirms, and it used to warn
        with the *rendered* child count while the backend deleted a
        different set entirely.

        Args:
            node_id: ID of the node the user is about to delete

        Returns:
            JSON response with ``exclusive_direct_children``,
            ``shared_direct_children`` and a ``modes`` object holding the
            full plan for both the delete and the promote answer to the
            "keep direct children" question. See
            ``HierarchyMixin.get_subject_delete_preview``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            node = self.user_db.get_subject_node(node_id)
            if not node:
                return serialize_response(False, error='Subject node not found')

            return serialize_response(
                True, data=self.user_db.get_subject_delete_preview(node_id)
            )
        except Exception as e:
            self._log_error(
                f'Error building subject delete preview: {e}',
                {'node_id': node_id},
            )
            return serialize_response(False, error=f'Failed to preview delete: {e}')

    @pyqtSlot(int, result=str)
    @pyqtSlot(int, bool, result=str)
    @instrumented_slot
    def deleteSubjectNode(self, node_id: int, promote_children: bool = False) -> str:
        """
        Soft-delete a subject node, cascading by edges rather than by the
        legacy ``parent_id`` column.

        Two registered signatures on purpose. ``deleteSubjectNode(int)``
        predates issue #15 and is still called from
        ``src/web/js/import_export.js`` (replace-mode import), so it keeps
        working unchanged and means "delete the exclusive children too".
        ``deleteSubjectNode(int, bool)`` is the tree editor's confirmation
        modal passing decision 2's single global choice. QWebChannel
        publishes both arities plus the bare name and resolves by argument
        count, so JS may call either.

        The semantics live in ``HierarchyMixin.delete_subject_subtree``;
        this slot only unwraps them. Notably the delete no longer walks
        ``subject_nodes.parent_id``: that column has been legacy since
        m004, so an edge-only child was never found and was left orphaned
        — still active, still holding an edge from an archived parent, and
        therefore invisible to every read path.

        Args:
            node_id: ID of the node to delete
            promote_children: keep the node's direct children and move
                them to the top level instead of deleting them

        Returns:
            JSON response carrying the executed plan: ``batch_id``,
            ``archived``, ``detached``, ``promoted`` and
            ``entries_unscoped``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            node = self.user_db.get_subject_node(node_id)
            if not node:
                return serialize_response(False, error='Subject node not found')

            # Collect all descendant IDs before deletion for graph cleanup
            descendant_ids = []
            if hasattr(self.user_db, '_graph_available') and self.user_db._graph_available:
                desc_result = self.user_db._graph_execute(
                    "MATCH (s:Subject {sqlite_id: $id})-[:HAS_CHILD*1..20]->(child:Subject) "
                    "RETURN child.sqlite_id",
                    {"id": node_id}
                )
                desc_rows = self.user_db._graph_collect(desc_result)
                descendant_ids = [row[0] for row in desc_rows]

            result = self.user_db.delete_subject_subtree(
                node_id, promote_children=bool(promote_children)
            )

            # Graph dual-write: DETACH DELETE only what SQLite archived.
            # A promoted or detached child survives in SQLite and must
            # survive in the graph too, so intersect the legacy descendant
            # list with the plan's archived set rather than deleting the
            # whole subtree.
            archived_ids = {item['id'] for item in result['archived']}
            _node_id = node_id
            _descendant_ids = [d for d in descendant_ids if d in archived_ids]

            def _graph_write():
                # Delete descendants first (leaf to root order not required
                # with DETACH DELETE, but we delete each explicitly)
                for desc_id in _descendant_ids:
                    self.user_db._graph_execute(
                        "MATCH (s:Subject {sqlite_id: $id}) DETACH DELETE s",
                        {"id": desc_id}
                    )
                # Delete the target node itself
                self.user_db._graph_execute(
                    "MATCH (s:Subject {sqlite_id: $id}) DETACH DELETE s",
                    {"id": _node_id}
                )
            self.user_db._dual_write_graph("delete_subject_node", _graph_write)

            return serialize_response(True, data={
                'id': node_id,
                'deleted': True,
                'batch_id': result['batch_id'],
                'promote_children': result['promote_children'],
                'archived': result['archived'],
                'detached': result['detached'],
                'promoted': result['promoted'],
                'entries_unscoped': result['entries_unscoped'],
            })

        except Exception as e:
            self._log_error(
                f'Error deleting subject node: {e}',
                {'node_id': node_id, 'promote_children': bool(promote_children)},
            )
            return serialize_response(False, error=f'Failed to delete node: {e}')

    # ------------------------------------------------------------------
    # Subject-tree import (issue #67)
    #
    # Import is a *merge* behind a preview, not an append. Both slots
    # read the file through ``_read_import_request`` and then call
    # ``plan_subject_import`` / ``apply_subject_import``, which share one
    # planner — the same arrangement #15 uses for subject delete, and for
    # the same reason: a preview that can disagree with the mutation is
    # worse than no preview, because the student acts on it.
    # ------------------------------------------------------------------

    def _read_import_request(self, hierarchy_json: str) -> Dict[str, Any]:
        """Parse an import file into ``{root_nodes, dimension_id, file_exam_name}``.

        Issue #61: the published import spec documents the top-level
        array as ``subjects``; ``exportSubjectHierarchy`` writes
        ``root_nodes``. ``root_nodes`` stays canonical so a round-trip of
        WIMI's own export is never reinterpreted, but a file written to
        the spec has to import too. Both slots below converge here, so
        the two spellings are still reconciled in exactly one place — the
        frontend reads whichever key the file used through
        ``api.getImportRootNodes`` and passes the file through untouched.

        Issue #103: the published format documents ``exam_context`` as an
        *object* (``{"name": ..., "description": ..., "source": {...}}``),
        so the name has to be dug out of it. Handing the whole dict on as
        ``file_exam_name`` made every guide-shaped file fail the
        string comparison in ``_import_preview_payload`` and render as
        ``[object Object]`` in the modal. A bare string is still accepted
        because files may spell it either way, and anything else (a list,
        a number, an object with no ``name``) degrades to ``None``, which
        is the "file does not say" case and shows no note.
        """
        data = json.loads(hierarchy_json) if hierarchy_json else {}
        if not isinstance(data, dict):
            return {'root_nodes': [], 'dimension_id': None, 'file_exam_name': None}
        root_nodes = data.get('root_nodes')
        if not isinstance(root_nodes, list):
            root_nodes = data.get('subjects')
        if not isinstance(root_nodes, list):
            root_nodes = []
        raw_exam_context = data.get('exam_context')
        if isinstance(raw_exam_context, dict):
            file_exam_name = raw_exam_context.get('name')
        else:
            file_exam_name = raw_exam_context
        if not isinstance(file_exam_name, str) or not file_exam_name.strip():
            file_exam_name = None
        return {
            'root_nodes': root_nodes,
            'dimension_id': data.get('dimension_id'),
            'file_exam_name': file_exam_name,
        }

    @staticmethod
    def _import_preview_payload(
        plan: Dict[str, Any],
        file_exam_name: Optional[str],
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Trim a plan down to what a modal can render.

        The plan carries one record per file node — 2,211 of them for the
        outline that prompted this issue — and the execution script is of
        no use to the UI. Counts are whole; the lists are capped and each
        carries its own ``*_total`` so the modal can say "and 37 more"
        rather than implying the cap is the number.
        """
        def cap(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return items[:limit]

        return {
            'exam_context_id': plan['exam_context_id'],
            'exam_name': plan['exam_name'],
            'dimension_id': plan['dimension_id'],
            # Decision 2: a file naming an exam that already exists is a
            # re-import of it. The only import path targets the exam the
            # student already has open, so the merge is automatic — but
            # if the file names a *different* exam, saying so is cheap
            # and stops a file being merged into the wrong tree.
            'file_exam_name': file_exam_name,
            'file_exam_matches': (
                file_exam_name is None
                or str(file_exam_name).strip().lower()
                == str(plan['exam_name']).strip().lower()
            ),
            'file_node_count': plan['file_node_count'],
            'file_nodes_with_id': plan['file_nodes_with_id'],
            'file_uses_ids': plan['file_uses_ids'],
            'rename_blind': plan['rename_blind'],
            'empty_file': plan['empty_file'],
            'counts': plan['counts'],
            'entries_affected': plan['entries_affected'],
            'entry_contexts_cleared': plan['entry_contexts_cleared'],
            'added': cap(plan['added']),
            'added_total': len(plan['added']),
            'updated': cap(plan['updated']),
            'updated_total': len(plan['updated']),
            'renamed': cap(plan['renamed']),
            'renamed_total': len(plan['renamed']),
            'moved': cap(plan['moved']),
            'moved_total': len(plan['moved']),
            'removed': cap(plan['removed']),
            'removed_total': len(plan['removed']),
            'kept_in_use': cap(plan['kept_in_use']),
            'kept_in_use_total': len(plan['kept_in_use']),
            'kept_as_ancestor': cap(plan['kept_as_ancestor']),
            'kept_as_ancestor_total': len(plan['kept_as_ancestor']),
            'errors': plan['errors'],
        }

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def previewSubjectHierarchyImport(
        self, exam_context_id: int, hierarchy_json: str
    ) -> str:
        """What importing this file would do, without doing any of it.

        Read-only. Issue #67 decision 1: import is destructive and used
        to be silent about it, so the counts of what will be added,
        updated, renamed, removed and kept — and how many entries are
        affected — are shown first.

        Args:
            exam_context_id: ID of the exam context to import into
            hierarchy_json: the import file, verbatim

        Returns:
            JSON response with the trimmed plan
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            request = self._read_import_request(hierarchy_json)
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            plan = self.user_db.plan_subject_import(
                exam_context_id,
                request['root_nodes'],
                dimension_id=request['dimension_id'],
            )
            return serialize_response(True, data=self._import_preview_payload(
                plan, request['file_exam_name']
            ))

        except Exception as e:
            self._log_error(
                f'Error previewing hierarchy import: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'hierarchy_json_len': len(hierarchy_json) if hierarchy_json else 0,
                },
            )
            return serialize_response(False, error=f'Failed to preview import: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def importSubjectHierarchy(self, exam_context_id: int, hierarchy_json: str) -> str:
        """
        Merge a subject hierarchy from JSON into an exam context.

        Re-importable: a file imported twice is a no-op the second time
        (issue #67). Matching is on each subject's optional ``id``, and
        by name-and-path where there is none. A subject the file no
        longer lists is removed **unless** entries are tagged to it, in
        which case it is kept and reported.

        Args:
            exam_context_id: ID of the exam context
            hierarchy_json: JSON string with hierarchy data

        Returns:
            JSON response with the import result — the same shape the
            preview returned, plus ``imported_count`` (unchanged from the
            pre-merge contract: file nodes applied) and ``warnings``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            request = self._read_import_request(hierarchy_json)
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            result = self.user_db.apply_subject_import(
                exam_context_id,
                request['root_nodes'],
                dimension_id=request['dimension_id'],
            )

            payload = self._import_preview_payload(
                result, request['file_exam_name']
            )
            payload.update({
                'imported_count': result['imported_count'],
                'created_ids': result['created_ids'],
                'updated_ids': result['updated_ids'],
                'removed_ids': result['removed_ids'],
                'delete_batch_ids': result['delete_batch_ids'],
                'warnings': result['warnings'],
            })
            return serialize_response(True, data=payload)

        except Exception as e:
            self._log_error(
                f'Error importing hierarchy: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'hierarchy_json_len': len(hierarchy_json) if hierarchy_json else 0,
                },
            )
            return serialize_response(False, error=f'Failed to import: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def exportSubjectHierarchy(self, exam_context_id: int) -> str:
        """
        Export subject hierarchy as JSON.

        Args:
            exam_context_id: ID of the exam context

        Returns:
            JSON response with hierarchy data
        """
        return self.getSubjectHierarchy(exam_context_id)
