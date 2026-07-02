"""WIMI Dimension bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class DimensionBridgeMixin:
    """Bridge mixin for dimension operations. Composed into DatabaseBridge."""

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def examUsesDimensions(self, exam_context_id: int) -> str:
        """
        Check if an exam uses multi-dimensional categorization.

        Simple exams (SAT, GRE) use single-path hierarchies.
        Multi-dimensional exams (NBME, USMLE) have dimensions defined.

        Args:
            exam_context_id: ID of the exam context

        Returns:
            JSON response with 'uses_dimensions' boolean
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            uses_dimensions = self.user_db.exam_uses_dimensions(exam_context_id)

            return serialize_response(True, data={
                'uses_dimensions': uses_dimensions,
                'exam_context_id': exam_context_id
            })

        except Exception as e:
            self._log_error(f'Error checking exam dimensions: {e}', {
                'exam_context_id': exam_context_id
            })
            return serialize_response(False, error=f'Failed to check exam dimensions: {e}')

    @pyqtSlot(int, str, int, bool, bool, str, result=str)
    @instrumented_slot
    def createDimension(
        self,
        exam_context_id: int,
        name: str,
        display_order: int,
        is_required: bool = True,
        allow_multiple: bool = False,
        description: str = ''
    ) -> str:
        """
        Create a new dimension for an exam.

        Dimensions define independent categorization axes for multi-dimensional
        exams (e.g., Site of Care, Physician Task, System for NBME).

        Args:
            exam_context_id: ID of the exam context
            name: Name of the dimension (e.g., "Site of Care")
            display_order: UI ordering (1, 2, 3, ...)
            is_required: Whether questions must be tagged in this dimension
            allow_multiple: Whether multiple selections are allowed
            description: Help text for users

        Returns:
            JSON response with created dimension data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            dimension_id = self.user_db.create_dimension(
                exam_id=exam_context_id,
                name=name,
                display_order=display_order,
                is_required=is_required,
                allow_multiple=allow_multiple,
                description=description if description else None
            )

            # Fetch the created dimension to return full data
            dimension = self.user_db.get_dimension(dimension_id)

            return serialize_response(True, data=dimension)

        except Exception as e:
            self._log_error(f'Error creating dimension: {e}', {
                'exam_context_id': exam_context_id,
                'name': name,
                'display_order': display_order,
                'is_required': is_required,
                'allow_multiple': allow_multiple,
                'description_len': len(description) if description else 0,
            })
            return serialize_response(False, error=f'Failed to create dimension: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getDimensions(self, exam_context_id: int) -> str:
        """
        Get all dimensions for an exam, ordered by display_order.

        Args:
            exam_context_id: ID of the exam context

        Returns:
            JSON response with list of dimensions
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            dimensions = self.user_db.get_exam_dimensions(exam_context_id)

            return serialize_response(True, data=dimensions)

        except Exception as e:
            self._log_error(f'Error getting dimensions: {e}', {
                'exam_context_id': exam_context_id
            })
            return serialize_response(False, error=f'Failed to get dimensions: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getDimension(self, dimension_id: int) -> str:
        """
        Get a single dimension by ID.

        Args:
            dimension_id: ID of the dimension

        Returns:
            JSON response with dimension data or error if not found
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            dimension = self.user_db.get_dimension(dimension_id)

            if not dimension:
                return serialize_response(False, error='Dimension not found')

            return serialize_response(True, data=dimension)

        except Exception as e:
            self._log_error(f'Error getting dimension: {e}', {
                'dimension_id': dimension_id
            })
            return serialize_response(False, error=f'Failed to get dimension: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateDimension(self, dimension_id: int, updates_json: str) -> str:
        """
        Update dimension properties.

        Args:
            dimension_id: ID of dimension to update
            updates_json: JSON string with fields to update:
                - name: New name
                - display_order: New display order
                - is_required: New is_required value
                - allow_multiple: New allow_multiple value
                - description: New description

        Returns:
            JSON response with updated dimension data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            updates = json.loads(updates_json)

            # Map JSON keys to method parameters
            rows_affected = self.user_db.update_dimension(
                dimension_id=dimension_id,
                name=updates.get('name'),
                display_order=updates.get('display_order'),
                is_required=updates.get('is_required'),
                allow_multiple=updates.get('allow_multiple'),
                description=updates.get('description')
            )

            if rows_affected == 0:
                return serialize_response(False, error='Dimension not found or no changes made')

            # Fetch updated dimension
            dimension = self.user_db.get_dimension(dimension_id)

            return serialize_response(True, data=dimension)

        except Exception as e:
            self._log_error(f'Error updating dimension: {e}', {
                'dimension_id': dimension_id,
                'updates_json_len': len(updates_json) if updates_json else 0,
            })
            return serialize_response(False, error=f'Failed to update dimension: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteDimension(self, dimension_id: int) -> str:
        """
        Delete a dimension.

        WARNING: This cascades to delete all question_hierarchy_tags for
        this dimension. This operation is irreversible.

        Args:
            dimension_id: ID of dimension to delete

        Returns:
            JSON response with success/failure
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            rows_affected = self.user_db.delete_dimension(dimension_id)

            if rows_affected == 0:
                return serialize_response(False, error='Dimension not found')

            return serialize_response(True, data={
                'id': dimension_id,
                'deleted': True
            })

        except Exception as e:
            self._log_error(f'Error deleting dimension: {e}', {
                'dimension_id': dimension_id
            })
            return serialize_response(False, error=f'Failed to delete dimension: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def reorderDimensions(self, exam_context_id: int, order_json: str) -> str:
        """
        Reorder dimensions by updating their display_order values.

        Args:
            exam_context_id: ID of the exam
            order_json: JSON array of dimension IDs in new order
                        e.g., [3, 1, 2] means dimension 3 becomes order 1,
                        dimension 1 becomes order 2, dimension 2 becomes order 3

        Returns:
            JSON response with success/failure
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            dimension_ids = json.loads(order_json)

            if not isinstance(dimension_ids, list):
                return serialize_response(False, error='order_json must be an array of dimension IDs')

            # Update each dimension's display_order
            with self.user_db.transaction():
                for new_order, dim_id in enumerate(dimension_ids, start=1):
                    self.user_db.update_dimension(
                        dimension_id=dim_id,
                        display_order=new_order
                    )

            # Fetch updated dimensions to return
            dimensions = self.user_db.get_exam_dimensions(exam_context_id)

            return serialize_response(True, data={
                'reordered': True,
                'dimensions': dimensions
            })

        except Exception as e:
            self._log_error(f'Error reordering dimensions: {e}', {
                'exam_context_id': exam_context_id,
                'order_json_len': len(order_json) if order_json else 0,
            })
            return serialize_response(False, error=f'Failed to reorder dimensions: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def getHierarchyNodesByDimension(self, exam_context_id: int, dimension_id: int) -> str:
        """
        Get all hierarchy nodes (subject_nodes) that belong to a specific dimension.

        Useful for populating dimension-specific hierarchy pickers in the UI.

        Args:
            exam_context_id: ID of the exam context
            dimension_id: ID of the dimension

        Returns:
            JSON response with list of hierarchy nodes
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            nodes = self.user_db.get_hierarchy_nodes_by_dimension(
                exam_id=exam_context_id,
                dimension_id=dimension_id
            )

            return serialize_response(True, data=nodes)

        except Exception as e:
            self._log_error(f'Error getting hierarchy nodes by dimension: {e}', {
                'exam_context_id': exam_context_id,
                'dimension_id': dimension_id
            })
            return serialize_response(False, error=f'Failed to get hierarchy nodes: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createSubjectNodeWithDimension(self, node_data_json: str) -> str:
        """
        Create a new subject node linked to a specific dimension.

        This is used for building per-dimension hierarchies in multi-dimensional exams.

        Args:
            node_data_json: JSON string with node data:
                - exam_context_id (required): ID to look up exam_name
                - name (required): Subject name
                - dimension_id (required): ID of the dimension this node belongs to
                - level_type (optional): Hierarchy level type
                - parent_id (optional): Parent node ID
                - exam_weight_low (optional): Low end of weight range
                - exam_weight_high (optional): High end of weight range
                - sort_order (optional): Display sort order

        Returns:
            JSON response with created node data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(node_data_json)

            # Get exam context for the exam_name
            exam_context_id = data.get('exam_context_id')
            if not exam_context_id:
                return serialize_response(False, error='exam_context_id is required')

            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            dimension_id = data.get('dimension_id')
            if not dimension_id:
                return serialize_response(False, error='dimension_id is required')

            # Create the subject node with dimension
            node = self.user_db.create_subject_node(
                exam_context=config.exam_name,
                name=data['name'],
                level_type=data.get('level_type', 'System'),
                parent_id=data.get('parent_id'),
                exam_weight_low=data.get('exam_weight_low', 0),
                exam_weight_high=data.get('exam_weight_high', 0),
                sort_order=data.get('sort_order', 1),
                dimension_id=dimension_id
            )

            return serialize_response(True, data={
                'id': node.id,
                'name': node.name,
                'level_type': node.level_type,
                'parent_id': node.parent_id,
                'dimension_id': dimension_id,
                'weight': node.exam_weight_low or 0,
                'exam_weight_low': node.exam_weight_low,
                'exam_weight_high': node.exam_weight_high,
                'sort_order': node.sort_order
            })

        except Exception as e:
            self._log_error(
                f'Error creating subject node with dimension: {e}',
                {
                    'node_data_json_len': len(node_data_json) if node_data_json else 0,
                },
            )
            return serialize_response(False, error=f'Failed to create node: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def getDimensionHierarchy(self, exam_context_id: int, dimension_id: int) -> str:
        """
        Get hierarchy tree for a specific dimension.

        Returns a nested structure of subject nodes that belong to
        the specified dimension, formatted as a tree. Polyhierarchy-
        aware: a node with multiple parent edges within this dimension
        appears once under each parent. The primary appearance carries
        the subtree; non-primary appearances are flagged with
        ``is_alias_appearance=True`` and have no children, matching the
        contract of ``get_subject_hierarchy`` per
        ``docs/planning/POLYHIERARCHY_MIGRATION.md`` §5.2 / §7.1.

        Tree shape is built from ``subject_edges`` (NOT from the legacy
        ``subject_nodes.parent_id`` column). Edges where parent or child
        is outside this dimension are ignored — the m004 migration
        backfilled an edge for every pre-runner ``parent_id`` so all
        valid in-dimension parent relationships are present in
        ``subject_edges`` by the time this runs. Cross-dimensional
        polyhierarchy is an explicit non-goal of the migration (see
        plan §2), so confining edge traversal to this dimension's node
        set is correct.

        Args:
            exam_context_id: ID of the exam context
            dimension_id: ID of the dimension

        Returns:
            JSON response with hierarchical tree structure
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            nodes = self.user_db.get_hierarchy_nodes_by_dimension(
                exam_id=exam_context_id,
                dimension_id=dimension_id,
            )

            if not nodes:
                return serialize_response(True, data={
                    'exam_context_id': exam_context_id,
                    'dimension_id': dimension_id,
                    'root_nodes': []
                })

            node_by_id = {n['id']: n for n in nodes}
            node_ids = list(node_by_id.keys())

            # Pull all edges where BOTH endpoints are in this dimension's
            # node set. Cross-dim edges (if any ever exist) are skipped.
            placeholders = ','.join('?' * len(node_ids))
            edge_rows = self.user_db.fetchall(
                f"""
                SELECT parent_id, child_id, is_primary, display_order
                FROM subject_edges
                WHERE child_id IN ({placeholders})
                  AND parent_id IN ({placeholders})
                ORDER BY display_order, child_id
                """,
                tuple(node_ids) + tuple(node_ids),
            )

            # Index edges two ways: by parent (to enumerate children) and
            # by child (to detect roots = no incoming edges).
            children_by_parent: dict[int, list] = {}
            edges_by_child: dict[int, list] = {}
            for e in edge_rows:
                children_by_parent.setdefault(e['parent_id'], []).append(e)
                edges_by_child.setdefault(e['child_id'], []).append(e)

            def build_subtree(node_id: int, parent_edge=None) -> dict:
                """Build a tree-shaped dict for ``node_id``.

                ``parent_edge`` is the edge that led to this appearance
                (None for roots). When the edge is non-primary the
                appearance is an alias: flagged + childless. The primary
                appearance carries the subtree.
                """
                src = node_by_id[node_id]
                # Shallow copy so we can stamp per-appearance fields
                # without mutating the shared node dict.
                out = dict(src)
                is_alias = bool(parent_edge) and not parent_edge['is_primary']
                out['is_alias_appearance'] = is_alias
                if is_alias:
                    out['children'] = []
                else:
                    child_edges = children_by_parent.get(node_id, [])
                    out['children'] = [
                        build_subtree(ce['child_id'], ce)
                        for ce in child_edges
                    ]
                return out

            # Roots: nodes with no incoming edge in this dimension. Sort
            # by sort_order/name to match the legacy ordering.
            root_ids = [nid for nid in node_ids if nid not in edges_by_child]
            root_ids.sort(key=lambda nid: (
                node_by_id[nid].get('sort_order') or 0,
                node_by_id[nid].get('name') or '',
            ))

            root_nodes = [build_subtree(rid) for rid in root_ids]

            return serialize_response(True, data={
                'exam_context_id': exam_context_id,
                'dimension_id': dimension_id,
                'root_nodes': root_nodes
            })

        except Exception as e:
            self._log_error(f'Error getting dimension hierarchy: {e}', {
                'exam_context_id': exam_context_id,
                'dimension_id': dimension_id
            })
            return serialize_response(False, error=f'Failed to get dimension hierarchy: {e}')
