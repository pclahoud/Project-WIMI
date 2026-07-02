"""WIMI Multi-Dimensional Analytics bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class DimensionAnalyticsBridgeMixin:
    """Bridge mixin for dimension analytics operations. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getDimensionPerformance(self, params_json: str) -> str:
        """
        Get aggregated performance by hierarchy nodes within one dimension.

        Args:
            params_json: JSON with:
                - exam_context_id: ID of the exam context
                - dimension_id: ID of the dimension
                - include_children: (optional, default True) Aggregate child counts to parents

        Returns:
            JSON response with dimension performance data. Each node includes:
            - direct_entries: entries mapped directly to this node
            - total_entries: entries mapped to this node OR any descendant (if include_children)
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            dimension_id = params.get('dimension_id')
            include_children = params.get('include_children', True)

            if not exam_context_id or not dimension_id:
                return serialize_response(False, error='exam_context_id and dimension_id required')

            result = self.user_db.get_dimension_performance(
                exam_context_id=exam_context_id,
                dimension_id=dimension_id,
                include_children=include_children
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting dimension performance: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'dimension_id': locals().get('dimension_id'),
                    'include_children': locals().get('include_children'),
                },
            )
            return serialize_response(False, error=f'Failed to get dimension performance: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getSubjectHierarchyWithMistakesByDimension(self, params_json: str) -> str:
        """
        Get hierarchical data for sunburst filtered by dimension.

        Args:
            params_json: JSON with exam_context_id, dimension_id

        Returns:
            JSON response with hierarchical data suitable for D3 sunburst
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            dimension_id = params.get('dimension_id')

            if not exam_context_id or not dimension_id:
                return serialize_response(False, error='exam_context_id and dimension_id required')

            result = self.user_db.get_subject_hierarchy_with_mistakes_by_dimension(
                exam_context_id=exam_context_id,
                dimension_id=dimension_id
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting hierarchy by dimension: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'dimension_id': locals().get('dimension_id'),
                },
            )
            return serialize_response(False, error=f'Failed to get hierarchy by dimension: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getCrossDimensionPerformance(self, params_json: str) -> str:
        """
        Get 2D matrix of performance at dimension intersections.

        Args:
            params_json: JSON with exam_context_id, dimension_a_id, dimension_b_id, min_entries,
                         and optional level_type_a, level_type_b, parent_node_a_id, parent_node_b_id
                         for hierarchy level filtering and drill-down

        Returns:
            JSON response with cross-dimension matrix data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            dimension_a_id = params.get('dimension_a_id')
            dimension_b_id = params.get('dimension_b_id')
            min_entries = params.get('min_entries', 1)
            # Hierarchy level filtering parameters
            level_type_a = params.get('level_type_a')
            level_type_b = params.get('level_type_b')
            parent_node_a_id = params.get('parent_node_a_id')
            parent_node_b_id = params.get('parent_node_b_id')
            include_children = params.get('include_children', True)

            if not exam_context_id or not dimension_a_id or not dimension_b_id:
                return serialize_response(False, error='exam_context_id, dimension_a_id, and dimension_b_id required')

            result = self.user_db.get_cross_dimension_performance(
                exam_context_id=exam_context_id,
                dimension_a_id=dimension_a_id,
                dimension_b_id=dimension_b_id,
                min_entries=min_entries,
                level_type_a=level_type_a,
                level_type_b=level_type_b,
                parent_node_a_id=parent_node_a_id,
                parent_node_b_id=parent_node_b_id,
                include_children=include_children
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting cross-dimension performance: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'dimension_a_id': locals().get('dimension_a_id'),
                    'dimension_b_id': locals().get('dimension_b_id'),
                    'min_entries': locals().get('min_entries'),
                    'level_type_a': locals().get('level_type_a'),
                    'level_type_b': locals().get('level_type_b'),
                    'parent_node_a_id': locals().get('parent_node_a_id'),
                    'parent_node_b_id': locals().get('parent_node_b_id'),
                    'include_children': locals().get('include_children'),
                },
            )
            return serialize_response(False, error=f'Failed to get cross-dimension performance: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getHierarchyLevelsForDimension(self, params_json: str) -> str:
        """
        Get available hierarchy levels for a dimension with counts.

        Used to populate level selector dropdowns for cross-dimension drill-down UI.

        Args:
            params_json: JSON with exam_context_id, dimension_id

        Returns:
            JSON response with dimension info and levels array:
            {
                'dimension_id': int,
                'dimension_name': str,
                'levels': [
                    {'level_type': 'System', 'count': 27, 'depth': 0},
                    {'level_type': 'Subsystem', 'count': 214, 'depth': 1},
                    ...
                ]
            }
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            dimension_id = params.get('dimension_id')

            if not exam_context_id or not dimension_id:
                return serialize_response(False, error='exam_context_id and dimension_id required')

            result = self.user_db.get_hierarchy_levels_for_dimension(
                exam_context_id=exam_context_id,
                dimension_id=dimension_id
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting hierarchy levels for dimension: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'dimension_id': locals().get('dimension_id'),
                },
            )
            return serialize_response(False, error=f'Failed to get hierarchy levels: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getDimensionNodes(self, params_json: str) -> str:
        """Get dimension nodes filtered by level_type and/or parent_node_id.

        Used by scope dropdown to list parent-level nodes for filtering.

        Args:
            params_json: JSON with exam_context_id (req), dimension_id (req),
                        level_type (opt), parent_node_id (opt)

        Returns:
            JSON response with list of node dicts [{id, name, parent_id, level_type}, ...]
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            dimension_id = params.get('dimension_id')

            if not exam_context_id or not dimension_id:
                return serialize_response(False, error='exam_context_id and dimension_id required')

            level_type = params.get('level_type')
            parent_node_id = params.get('parent_node_id')

            result = self.user_db.get_dimension_nodes(
                exam_context_id=exam_context_id,
                dimension_id=dimension_id,
                level_type=level_type,
                parent_node_id=parent_node_id
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting dimension nodes: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'dimension_id': locals().get('dimension_id'),
                    'level_type': locals().get('level_type'),
                    'parent_node_id': locals().get('parent_node_id'),
                },
            )
            return serialize_response(False, error=f'Failed to get dimension nodes: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getIntersectionEntries(self, params_json: str) -> str:
        """
        Get entries at specific dimension intersection for drill-down.

        Args:
            params_json: JSON with:
                - exam_context_id: ID of the exam context
                - hierarchy_a_id: Hierarchy node ID in dimension A
                - dimension_a_id: Dimension A ID
                - hierarchy_b_id: Hierarchy node ID in dimension B
                - dimension_b_id: Dimension B ID
                - limit: (optional, default 50) Maximum entries to return
                - include_children: (optional, default True) Include entries from descendant nodes

        Returns:
            JSON response with list of entries at this intersection.
            If include_children=True, includes entries tagged to any descendant
            of the specified hierarchy nodes.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            hierarchy_a_id = params.get('hierarchy_a_id')
            dimension_a_id = params.get('dimension_a_id')
            hierarchy_b_id = params.get('hierarchy_b_id')
            dimension_b_id = params.get('dimension_b_id')
            limit = params.get('limit', 50)
            include_children = params.get('include_children', True)

            if not all([exam_context_id, hierarchy_a_id, dimension_a_id, hierarchy_b_id, dimension_b_id]):
                return serialize_response(False, error='All parameters required')

            result = self.user_db.get_intersection_entries(
                exam_context_id=exam_context_id,
                hierarchy_a_id=hierarchy_a_id,
                dimension_a_id=dimension_a_id,
                hierarchy_b_id=hierarchy_b_id,
                dimension_b_id=dimension_b_id,
                limit=limit,
                include_children=include_children
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting intersection entries: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'hierarchy_a_id': locals().get('hierarchy_a_id'),
                    'dimension_a_id': locals().get('dimension_a_id'),
                    'hierarchy_b_id': locals().get('hierarchy_b_id'),
                    'dimension_b_id': locals().get('dimension_b_id'),
                    'limit': locals().get('limit'),
                    'include_children': locals().get('include_children'),
                },
            )
            return serialize_response(False, error=f'Failed to get intersection entries: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getTripleDimensionPerformance(self, params_json: str) -> str:
        """
        Get ranked 3-way dimension combinations.

        Args:
            params_json: JSON with exam_context_id, dim_a_id, dim_b_id, dim_c_id,
                         min_entries, limit

        Returns:
            JSON response with list of 3-way combinations
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            dim_a_id = params.get('dim_a_id')
            dim_b_id = params.get('dim_b_id')
            dim_c_id = params.get('dim_c_id')
            min_entries = params.get('min_entries', 1)
            limit = params.get('limit', 10)

            if not all([exam_context_id, dim_a_id, dim_b_id, dim_c_id]):
                return serialize_response(False, error='All dimension IDs required')

            result = self.user_db.get_triple_dimension_performance(
                exam_context_id=exam_context_id,
                dim_a_id=dim_a_id,
                dim_b_id=dim_b_id,
                dim_c_id=dim_c_id,
                min_entries=min_entries,
                limit=limit
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting triple dimension performance: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'dim_a_id': locals().get('dim_a_id'),
                    'dim_b_id': locals().get('dim_b_id'),
                    'dim_c_id': locals().get('dim_c_id'),
                    'min_entries': locals().get('min_entries'),
                    'limit': locals().get('limit'),
                },
            )
            return serialize_response(False, error=f'Failed to get triple dimension performance: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def detectInteractionEffects(self, params_json: str) -> str:
        """
        Detect interaction effects between two dimensions.

        Args:
            params_json: JSON with exam_context_id, dimension_a_id, dimension_b_id, threshold

        Returns:
            JSON response with list of detected interaction effects
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            dimension_a_id = params.get('dimension_a_id')
            dimension_b_id = params.get('dimension_b_id')
            threshold = params.get('threshold', 0.10)

            if not all([exam_context_id, dimension_a_id, dimension_b_id]):
                return serialize_response(False, error='All dimension IDs required')

            result = self.user_db.detect_interaction_effects(
                exam_context_id=exam_context_id,
                dimension_a_id=dimension_a_id,
                dimension_b_id=dimension_b_id,
                threshold=threshold
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error detecting interaction effects: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'dimension_a_id': locals().get('dimension_a_id'),
                    'dimension_b_id': locals().get('dimension_b_id'),
                    'threshold': locals().get('threshold'),
                },
            )
            return serialize_response(False, error=f'Failed to detect interaction effects: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getMistakeTypeByDimension(self, params_json: str) -> str:
        """
        Get mistake type breakdown per dimension value.

        Args:
            params_json: JSON with exam_context_id, dimension_id

        Returns:
            JSON response with mistake type distribution by dimension value
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            dimension_id = params.get('dimension_id')

            if not exam_context_id or not dimension_id:
                return serialize_response(False, error='exam_context_id and dimension_id required')

            result = self.user_db.get_mistake_type_by_dimension(
                exam_context_id=exam_context_id,
                dimension_id=dimension_id
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting mistake type by dimension: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'dimension_id': locals().get('dimension_id'),
                },
            )
            return serialize_response(False, error=f'Failed to get mistake type by dimension: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getWeightedStudyRecommendations(self, params_json: str) -> str:
        """
        Get priority-ranked study recommendations.

        Args:
            params_json: JSON with exam_context_id, limit

        Returns:
            JSON response with list of study recommendations
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            limit = params.get('limit', 10)

            if not exam_context_id:
                return serialize_response(False, error='exam_context_id required')

            result = self.user_db.get_weighted_study_recommendations(
                exam_context_id=exam_context_id,
                limit=limit
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting study recommendations: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'limit': locals().get('limit'),
                },
            )
            return serialize_response(False, error=f'Failed to get study recommendations: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getTemporalTrendsByDimension(self, params_json: str) -> str:
        """
        Get time series performance filtered by dimension.

        Args:
            params_json: JSON with exam_context_id, dimension_id, hierarchy_id, weeks

        Returns:
            JSON response with temporal trends data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            dimension_id = params.get('dimension_id')
            hierarchy_id = params.get('hierarchy_id')
            weeks = params.get('weeks', 12)

            if not exam_context_id or not dimension_id:
                return serialize_response(False, error='exam_context_id and dimension_id required')

            result = self.user_db.get_temporal_trends_by_dimension(
                exam_context_id=exam_context_id,
                dimension_id=dimension_id,
                hierarchy_id=hierarchy_id,
                weeks=weeks
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting temporal trends: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'dimension_id': locals().get('dimension_id'),
                    'hierarchy_id': locals().get('hierarchy_id'),
                    'weeks': locals().get('weeks'),
                },
            )
            return serialize_response(False, error=f'Failed to get temporal trends: {e}')
