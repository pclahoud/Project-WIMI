"""WIMI Analytics bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class AnalyticsBridgeMixin:
    """Bridge mixin for analytics operations. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getAnalyticsOverview(self, params_json: str) -> str:
        """
        Get high-level analytics overview.

        Args:
            params_json: JSON with optional exam_context_id

        Returns:
            JSON response with overview statistics
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')

            overview = self.user_db.get_analytics_overview(exam_context_id)
            return serialize_response(True, data=overview)

        except Exception as e:
            self._log_error(
                f'Error getting analytics overview: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(False, error=f'Failed to get analytics overview: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getSubjectAnalytics(self, params_json: str) -> str:
        """
        Get subject analytics with mistake distribution.

        Args:
            params_json: JSON with optional exam_context_id, limit, include_children

        Returns:
            JSON response with subject analytics
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            limit = params.get('limit', 10)
            include_children = params.get('include_children', True)

            analytics = self.user_db.get_subject_analytics(
                exam_context_id=exam_context_id,
                limit=limit,
                include_children=include_children
            )
            return serialize_response(True, data=analytics)

        except Exception as e:
            self._log_error(
                f'Error getting subject analytics: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'limit': limit,
                    'include_children': include_children,
                },
            )
            return serialize_response(False, error=f'Failed to get subject analytics: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getTagAnalytics(self, params_json: str) -> str:
        """
        Get tag analytics with grouping.

        Args:
            params_json: JSON with optional exam_context_id, group_by_parent

        Returns:
            JSON response with tag analytics
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            group_by_parent = params.get('group_by_parent', True)
            dimension_id = params.get('dimension_id')

            analytics = self.user_db.get_tag_analytics(
                exam_context_id=exam_context_id,
                group_by_parent=group_by_parent,
                dimension_id=dimension_id
            )
            return serialize_response(True, data=analytics)

        except Exception as e:
            self._log_error(
                f'Error getting tag analytics: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'group_by_parent': group_by_parent,
                    'dimension_id': dimension_id,
                },
            )
            return serialize_response(False, error=f'Failed to get tag analytics: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getExamAnalyticsConfig(self, exam_context_id: int) -> str:
        """
        Get analytics configuration for an exam context.

        Args:
            exam_context_id: Exam context ID

        Returns:
            JSON response with analytics config
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.get_exam_analytics_config(exam_context_id)
            return serialize_response(True, data=config)

        except Exception as e:
            self._log_error(
                f'Error getting exam analytics config: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(False, error=f'Failed to get exam analytics config: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def updateExamAnalyticsConfig(self, config_json: str) -> str:
        """
        Update analytics configuration for an exam context.

        Args:
            config_json: JSON with exam_context_id and config fields

        Returns:
            JSON response with updated config
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(config_json)
            exam_context_id = data.pop('exam_context_id')

            config = self.user_db.update_exam_analytics_config(exam_context_id, data)
            return serialize_response(True, data=config)

        except Exception as e:
            self._log_error(
                f'Error updating exam analytics config: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'data_keys': sorted(list(data.keys())) if isinstance(locals().get('data'), dict) else None,
                },
            )
            return serialize_response(False, error=f'Failed to update exam analytics config: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getDifficultyDistribution(self, params_json: str) -> str:
        """
        Get difficulty distribution.

        Args:
            params_json: JSON with optional exam_context_id

        Returns:
            JSON response with difficulty distribution
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')

            distribution = self.user_db.get_difficulty_distribution(exam_context_id)
            return serialize_response(True, data=distribution)

        except Exception as e:
            self._log_error(
                f'Error getting difficulty distribution: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(False, error=f'Failed to get difficulty distribution: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getActivityOverTime(self, params_json: str) -> str:
        """
        Get activity over time for trend charts.

        Args:
            params_json: JSON with optional exam_context_id, period, granularity

        Returns:
            JSON response with activity data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            period = params.get('period', '30d')
            granularity = params.get('granularity', 'day')

            activity = self.user_db.get_activity_over_time(
                exam_context_id=exam_context_id,
                period=period,
                granularity=granularity
            )
            return serialize_response(True, data=activity)

        except Exception as e:
            self._log_error(
                f'Error getting activity over time: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'period': period,
                    'granularity': granularity,
                },
            )
            return serialize_response(False, error=f'Failed to get activity over time: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getStudyStreak(self, params_json: str) -> str:
        """
        Get study streak information.

        Args:
            params_json: JSON with optional exam_context_id

        Returns:
            JSON response with streak data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')

            streak = self.user_db.get_study_streak(exam_context_id)
            return serialize_response(True, data=streak)

        except Exception as e:
            self._log_error(
                f'Error getting study streak: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(False, error=f'Failed to get study streak: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getPatternsAndInsights(self, params_json: str) -> str:
        """
        Get pattern detection and insights.

        Args:
            params_json: JSON with optional exam_context_id, limit

        Returns:
            JSON response with insights
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')
            limit = params.get('limit', 5)

            insights = self.user_db.get_patterns_and_insights(
                exam_context_id=exam_context_id,
                limit=limit
            )
            return serialize_response(True, data=insights)

        except Exception as e:
            self._log_error(
                f'Error getting patterns and insights: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'limit': limit,
                },
            )
            return serialize_response(False, error=f'Failed to get patterns and insights: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getSubjectDeepDive(self, params_json: str) -> str:
        """
        Get comprehensive analytics for a specific subject.

        Args:
            params_json: JSON with subject_id (required), optional exam_context_id

        Returns:
            JSON response with subject deep dive data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            subject_id = params.get('subject_id')
            exam_context_id = params.get('exam_context_id')
            primary_parent_id = params.get('primary_parent_id')

            if not subject_id:
                return serialize_response(False, error='subject_id is required')

            subject_data = self.user_db.get_subject_deep_dive(
                subject_id=subject_id,
                exam_context_id=exam_context_id,
                primary_parent_id=primary_parent_id
            )

            if not subject_data:
                return serialize_response(False, error='Subject not found')

            return serialize_response(True, data=subject_data)

        except Exception as e:
            self._log_error(
                f'Error getting subject deep dive: {e}',
                {
                    'subject_id': locals().get('subject_id'),
                    'exam_context_id': locals().get('exam_context_id'),
                    'primary_parent_id': locals().get('primary_parent_id'),
                },
            )
            return serialize_response(False, error=f'Failed to get subject deep dive: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getSubjectHierarchyWithMistakes(self, params_json: str) -> str:
        """
        Get full subject hierarchy with mistake counts for sunburst visualization.

        Args:
            params_json: JSON with exam_context_id (required)

        Returns:
            JSON response with hierarchical subject data including mistake counts
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)
            exam_context_id = params.get('exam_context_id')

            if not exam_context_id:
                return serialize_response(False, error='exam_context_id is required')

            # Get exam context to get the exam_name
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            # Get hierarchy using exam_name
            root_nodes = self.user_db.get_subject_hierarchy(config.exam_name)

            # Get mistake counts for all subjects
            mistake_counts = self._get_subject_mistake_counts(exam_context_id)

            def node_to_dict_with_mistakes(node, depth=0):
                node_id = node.id
                direct_count = mistake_counts.get(node_id, 0)

                # Process children first
                children_data = []
                if node.children:
                    for child in node.children:
                        children_data.append(node_to_dict_with_mistakes(child, depth + 1))

                # Calculate total (direct + all descendants)
                children_total = sum(c.get('value', 0) for c in children_data)
                total_count = direct_count + children_total

                result = {
                    'id': node_id,
                    'name': node.name,
                    'level_type': node.level_type,
                    'depth': depth,
                    'direct_mistakes': direct_count,
                    'value': total_count,  # Total mistakes including children
                }

                if children_data:
                    result['children'] = children_data

                return result

            hierarchy_data = {
                'name': config.exam_name,
                'children': [node_to_dict_with_mistakes(n) for n in root_nodes]
            }

            # Calculate total
            total_mistakes = sum(c.get('value', 0) for c in hierarchy_data.get('children', []))
            hierarchy_data['value'] = total_mistakes

            return serialize_response(True, data=hierarchy_data)

        except Exception as e:
            self._log_error(
                f'Error getting subject hierarchy with mistakes: {e}',
                {'exam_context_id': locals().get('exam_context_id')},
            )
            return serialize_response(False, error=f'Failed to get hierarchy: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getActivityHeatmap(self, params_json: str) -> str:
        """
        Get activity data for GitHub-style heatmap visualization.

        Args:
            params_json: JSON with optional exam_context_id and weeks

        Returns:
            JSON response with heatmap data including days array and streak info
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json) if params_json else {}
            exam_context_id = params.get('examContextId') or params.get('exam_context_id')
            weeks = params.get('weeks', 16)

            heatmap_data = self.user_db.get_activity_heatmap(
                exam_context_id=exam_context_id,
                weeks=weeks
            )

            return serialize_response(True, data=heatmap_data)

        except Exception as e:
            self._log_error(
                f'Error getting activity heatmap: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'weeks': locals().get('weeks'),
                },
            )
            return serialize_response(False, error=f'Failed to get heatmap data: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getStreakInfo(self, params_json: str) -> str:
        """
        Get detailed streak information.

        Args:
            params_json: JSON with optional exam_context_id

        Returns:
            JSON response with streak data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json) if params_json else {}
            exam_context_id = params.get('examContextId') or params.get('exam_context_id')

            streak_data = self.user_db.get_streak_info(
                exam_context_id=exam_context_id
            )

            return serialize_response(True, data=streak_data)

        except Exception as e:
            self._log_error(
                f'Error getting streak info: {e}',
                {'exam_context_id': locals().get('exam_context_id')},
            )
            return serialize_response(False, error=f'Failed to get streak info: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getSourceComparison(self, params_json: str) -> str:
        """
        Get source comparison data with performance trends.

        Args:
            params_json: JSON with optional exam_context_id and months

        Returns:
            JSON response with source comparison data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json) if params_json else {}
            exam_context_id = params.get('examContextId') or params.get('exam_context_id')
            months = params.get('months', 6)

            data = self.user_db.get_source_comparison(
                exam_context_id=exam_context_id,
                months=months
            )

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting source comparison: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'months': locals().get('months'),
                },
            )
            return serialize_response(False, error=f'Failed to get source comparison: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getPerformanceOverTime(self, params_json: str) -> str:
        """
        Get performance metrics over time.

        Args:
            params_json: JSON with optional exam_context_id, period, and weeks

        Returns:
            JSON response with performance data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json) if params_json else {}
            exam_context_id = params.get('examContextId') or params.get('exam_context_id')
            period = params.get('period', 'weekly')
            weeks = params.get('weeks', 12)

            data = self.user_db.get_performance_over_time(
                exam_context_id=exam_context_id,
                period=period,
                weeks=weeks
            )

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting performance over time: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'period': locals().get('period'),
                    'weeks': locals().get('weeks'),
                },
            )
            return serialize_response(False, error=f'Failed to get performance over time: {e}')

    # =====================================================================
    # Stage 9 — weight_source-aware analytics
    # (docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 9")
    #
    # Surfaces the new ``get_weight_source_breakdown`` helper so the
    # analytics dashboard's "Confidence breakdown" card can render the
    # per-source subject counts without round-tripping through the
    # heavier ``getSubjectExamWeightAnalysis`` slot (which now also
    # bundles the same data on its response, but the dedicated slot
    # avoids re-running the full weight analysis when only the
    # breakdown is needed).
    # =====================================================================

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getWeightSourceBreakdown(self, exam_context_id: int) -> str:
        """Per-``weight_source`` subject counts for the breakdown card.

        Stage 9. Returns the same dict shape as
        :meth:`AdvancedAnalyticsMixin.get_weight_source_breakdown`::

            {
                'official': int,
                'user_explicit': int,
                'user_defined': int,
                'derived': int,
                'user_estimate': int,
                'total': int,
            }

        ``total`` is the sum of the other five buckets.

        Args:
            exam_context_id: Target exam context. Required and must
                exist (the underlying DB method raises ``ValueError``
                otherwise, which this slot reports as a clean error).

        Returns:
            JSON string ``{'success': True, 'data': {...}}`` or
            ``{'success': False, 'error': ...}``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = self.user_db.get_weight_source_breakdown(
                exam_context_id=exam_context_id
            )
            return serialize_response(True, data=data)

        except ValueError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'getWeightSourceBreakdown failed: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(
                False, error=f'Failed to get weight source breakdown: {e}'
            )
