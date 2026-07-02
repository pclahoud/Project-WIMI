"""WIMI Subject Hierarchy bridge operations."""
import json

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

            if parent_id and (not dimension_id or 'level_type' not in data):
                parent_row = self.user_db.fetchone(
                    "SELECT dimension_id, level_type FROM subject_nodes WHERE id = ? AND status = 'active'",
                    (parent_id,)
                )
                if parent_row:
                    if not dimension_id and parent_row['dimension_id']:
                        dimension_id = parent_row['dimension_id']
                    if 'level_type' not in data and parent_row['level_type']:
                        levels = self.user_db.get_hierarchy_levels(exam_context_id)
                        level_names = [l.level_name for l in levels]
                        try:
                            parent_idx = level_names.index(parent_row['level_type'])
                            if parent_idx + 1 < len(level_names):
                                data['level_type'] = level_names[parent_idx + 1]
                            else:
                                data['level_type'] = parent_row['level_type']
                        except ValueError:
                            pass

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
    def deleteSubjectNode(self, node_id: int) -> str:
        """
        Delete a subject node and all its children.

        Args:
            node_id: ID of the node to delete

        Returns:
            JSON response with success status
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

            with self.user_db.transaction():
                self._delete_node_recursive(node_id)

            # Graph dual-write: DETACH DELETE the node and all descendants
            _node_id = node_id
            _descendant_ids = descendant_ids

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
                'deleted': True
            })

        except Exception as e:
            self._log_error(f'Error deleting subject node: {e}', {'node_id': node_id})
            return serialize_response(False, error=f'Failed to delete node: {e}')

    def _delete_node_recursive(self, node_id: int):
        """Recursively soft-delete a node and its children"""
        children = self.user_db.fetchall(
            "SELECT id FROM subject_nodes WHERE parent_id = ? AND status = 'active'",
            (node_id,)
        )

        for child in children:
            self._delete_node_recursive(child['id'])

        self.user_db.execute(
            "UPDATE subject_nodes SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (node_id,)
        )

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def importSubjectHierarchy(self, exam_context_id: int, hierarchy_json: str) -> str:
        """
        Import subject hierarchy from JSON.

        Args:
            exam_context_id: ID of the exam context
            hierarchy_json: JSON string with hierarchy data

        Returns:
            JSON response with import result
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(hierarchy_json)
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            root_nodes = data.get('root_nodes', [])
            dimension_id = data.get('dimension_id')
            imported_count = 0

            def import_node(node_data, parent_id=None, level=1):
                nonlocal imported_count

                levels = self.user_db.get_hierarchy_levels(exam_context_id)
                level_name = levels[level - 1].level_name if level <= len(levels) else f'Level {level}'

                weight_data = node_data.get('weight')
                if isinstance(weight_data, dict):
                    if 'value' in weight_data:
                        weight_low = weight_data['value']
                        weight_high = weight_data['value']
                    else:
                        weight_low = weight_data.get('low', 0)
                        weight_high = weight_data.get('high', weight_low)
                else:
                    weight_low = weight_data if weight_data else 0
                    weight_high = weight_low

                node = self.user_db.create_subject_node(
                    exam_context=config.exam_name,
                    name=node_data['name'],
                    level_type=node_data.get('level_type', level_name),
                    parent_id=parent_id,
                    exam_weight_low=weight_low,
                    exam_weight_high=weight_high,
                    sort_order=node_data.get('sort_order', 1),
                    dimension_id=dimension_id
                )
                imported_count += 1

                # Import aliases for this node
                for alias_data in node_data.get('aliases', []):
                    alias_name = alias_data.get('name', '').strip()
                    if not alias_name:
                        continue
                    alias_type = alias_data.get('type', 'alternate_name')
                    if alias_type not in ('eponym', 'acronym', 'alternate_name', 'colloquial'):
                        alias_type = 'alternate_name'
                    try:
                        self.user_db.create_subject_alias(
                            subject_node_id=node.id,
                            exam_context=config.exam_name,
                            alias_name=alias_name,
                            alias_type=alias_type,
                            is_primary=bool(alias_data.get('is_primary', False)),
                            notes=alias_data.get('notes')
                        )
                    except Exception as alias_err:
                        self._log_error(
                            f'Could not import alias "{alias_name}" for node "{node_data["name"]}": {alias_err}',
                            {
                                'node_id': node.id,
                                'alias_name': alias_name,
                                'alias_type': alias_type,
                                'exam_context_id': exam_context_id,
                            },
                        )

                for child_data in node_data.get('children', []):
                    import_node(child_data, node.id, level + 1)

            with self.user_db.transaction():
                for node_data in root_nodes:
                    import_node(node_data)

            return serialize_response(True, data={
                'imported_count': imported_count
            })

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
