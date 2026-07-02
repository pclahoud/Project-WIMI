"""WIMI Weight management bridge operations."""
import json
from typing import Optional

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response
from database.exceptions import (
    WeightValidationError, WeightBalancingError, SubjectNodeError
)


class WeightBridgeMixin:
    """Bridge mixin for weight management operations. Composed into DatabaseBridge."""

    @pyqtSlot(int, float, str, str, result=str)
    @instrumented_slot
    def updateSubjectNodeWeight(
        self,
        node_id: int,
        new_weight: float,
        reason: str = '',
        user_notes: str = ''
    ) -> str:
        """
        Update a subject node's weight with automatic sibling balancing.

        Args:
            node_id: ID of the subject node
            new_weight: New weight value (0-100)
            reason: Optional reason for the change
            user_notes: Optional user notes

        Returns:
            JSON response with update result
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            result = self.user_db.update_subject_node_weight(
                node_id=node_id,
                new_weight=new_weight,
                reason=reason if reason else None,
                user_notes=user_notes if user_notes else None
            )

            # Emit signal
            self.weightUpdated.emit(str(node_id))

            return serialize_response(True, data={
                'updated_node_id': result.updated_node.id if result.updated_node else node_id,
                'total_updates': result.total_updates,
                'affected_sibling_ids': [s.id for s in result.affected_siblings],
                'weight_history_ids': result.weight_history_ids,
                'had_side_effects': result.had_side_effects
            })

        except WeightValidationError as e:
            return serialize_response(False, error=str(e))
        except WeightBalancingError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error updating weight: {e}', {'node_id': node_id})
            return serialize_response(False, error=f'Failed to update weight: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def getWeightHistory(self, node_id: int, limit: int = 50) -> str:
        """
        Get weight change history for a subject node.

        Args:
            node_id: ID of the subject node
            limit: Maximum number of history entries to return

        Returns:
            JSON response with weight history
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            history = self.user_db.get_weight_history(node_id, limit=limit)

            data = [{
                'id': entry.id,
                'subject_node_id': entry.subject_node_id,
                'weight_value': entry.weight_value,
                'edited_date': entry.edited_date,
                'edited_by': entry.edited_by,
                'edited_reason': entry.edited_reason,
                'previous_weight': entry.previous_weight,
                'change_type': entry.change_type,
                'weight_delta': entry.weight_delta,
                'is_user_edit': entry.is_user_edit,
                'is_auto_adjustment': entry.is_auto_adjustment,
                'user_notes': entry.user_notes
            } for entry in history]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(f'Error getting weight history: {e}', {'node_id': node_id})
            return serialize_response(False, error=f'Failed to get weight history: {e}')

    @pyqtSlot(int, float, str, result=str)
    @instrumented_slot
    def updateRelativeWeight(
        self,
        node_id: int,
        relative_weight: float,
        reason: str = ""
    ) -> str:
        """
        Update relative weight on the node's primary edge.

        **Behavior changed Stage 2 (WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md):
        siblings are no longer auto-touched.** Use ``rebalanceSiblings``
        for explicit redistribution. The slot signature is intentionally
        unchanged so existing JS callers do not break; the response
        payload always reports ``rebalanced: False`` and
        ``affected_siblings: []`` so consumers can detect the new
        contract.

        Args:
            node_id: ID of subject node to update
            relative_weight: New relative weight (0-100)
            reason: Optional reason for change (for audit trail)

        Returns:
            JSON string: {
                'success': bool,
                'data': {
                    'old_weight': float,
                    'new_weight': float,
                    'updated_node': {...},
                    'rebalanced': False,            # always False
                    'affected_siblings': []         # always empty
                }
            } or error
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            result = self.user_db.update_subject_relative_weight(
                node_id=node_id,
                relative_weight=relative_weight,
                reason=reason if reason else None
            )

            # Convert SubjectNode to dict
            result['updated_node'] = self._subject_node_to_dict(result['updated_node'])
            # Stage 2 contract: explicitly mark the no-rebalance shape.
            result['rebalanced'] = False
            result['affected_siblings'] = []

            # Emit signal for UI updates
            self.weightUpdated.emit(str(node_id))

            return serialize_response(True, data=result)

        except SubjectNodeError as e:
            # Specific error for locked weights or other subject issues
            self._log_error(f'updateRelativeWeight failed (locked): {e}', {
                'node_id': node_id,
                'relative_weight': relative_weight
            })
            return json.dumps({
                'success': False,
                'error': str(e),
                'error_type': 'SubjectNodeError'
            })

        except WeightValidationError as e:
            # Specific error for invalid weights
            self._log_error(f'updateRelativeWeight validation failed: {e}', {
                'node_id': node_id,
                'relative_weight': relative_weight
            })
            return json.dumps({
                'success': False,
                'error': str(e),
                'error_type': 'WeightValidationError'
            })

        except Exception as e:
            self._log_error(f'updateRelativeWeight failed: {e}', {'node_id': node_id})
            return serialize_response(False, error=f'Failed to update relative weight: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def rebalanceSiblings(
        self,
        parent_id: int,
        reason: str = ""
    ) -> str:
        """Explicitly rebalance the sibling edges under ``parent_id``.

        Stage 2 of the Hierarchical Weight Allocation Implementation
        Plan. Now that ``updateRelativeWeight`` no longer auto-touches
        siblings, the UI must invoke this slot to opt in to
        redistribution.

        Anchored edges (``subject_edges.is_anchor=TRUE``) and edges
        whose child has the legacy ``subject_nodes.weight_locked`` flag
        are excluded from the adjustable set; the remainder is split
        proportionally across the rest.

        Args:
            parent_id: Parent node id whose outgoing edges to rebalance.
            reason: Optional audit-trail reason. Empty string is
                normalized to ``'User-triggered rebalance'``.

        Returns:
            JSON string: ``{
                'success': True,
                'data': {
                    'ok': True,
                    'parent_id': int,
                    'affected_edges': [
                        {'edge_id': int, 'child_id': int,
                         'old_weight': float, 'new_weight': float}, ...
                    ],
                    'skipped': [
                        {'edge_id': int, 'child_id': int,
                         'reason': 'anchored' | 'weight_locked'}, ...
                    ]
                }
            }``
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            result = self.user_db.rebalance_sibling_edge_weights(
                parent_id=parent_id,
                reason=reason if reason else 'User-triggered rebalance',
            )
            # Emit a per-parent signal so subscribers can refresh.
            try:
                self.weightUpdated.emit(str(parent_id))
            except Exception:
                # Signal may not exist in test contexts; not a hard requirement.
                pass
            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'rebalanceSiblings failed: {e}',
                {'parent_id': parent_id},
            )
            return serialize_response(
                False, error=f'Failed to rebalance siblings: {e}'
            )

    @pyqtSlot(int, bool, result=str)
    @instrumented_slot
    def getSubjectsWithEffectiveWeights(
        self,
        exam_context_id: int,
        include_children: bool = True
    ) -> str:
        """
        Get subjects with calculated effective weights.

        Args:
            exam_context_id: ID of exam context
            include_children: Whether to include child subjects recursively

        Returns:
            JSON string: {
                'success': bool,
                'data': [
                    {
                        'id': int,
                        'name': str,
                        'level_type': str,
                        'weight': {
                            'absolute_low': float or null,
                            'absolute_high': float or null,
                            'relative': float or null,
                            'effective': float,
                            'effective_low': float,
                            'effective_high': float,
                            'source': str,
                            'confidence': str,
                            'locked': bool
                        },
                        'children': [...]
                    },
                    ...
                ]
            } or error
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            subjects = self.user_db.get_subjects_with_effective_weights(
                exam_context_id=exam_context_id,
                include_children=include_children
            )

            return serialize_response(True, data=subjects)

        except Exception as e:
            self._log_error(f'getSubjectsWithEffectiveWeights failed: {e}', {
                'exam_context_id': exam_context_id
            })
            return serialize_response(False, error=f'Failed to get effective weights: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getWeightConfig(self, exam_context_id: int) -> str:
        """
        Get weight configuration for exam.

        Args:
            exam_context_id: ID of exam context

        Returns:
            JSON string: {
                'success': bool,
                'data': {
                    'weight_mode': str,
                    'has_official_weights': bool,
                    'official_weight_count': int,
                    'user_defined_count': int,
                    'total_weight_sum': float,
                    'weights_sum_to_100': bool,
                    'source_name': str or null,
                    'source_url': str or null
                }
            } or error
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.get_weight_config_for_exam(
                exam_context_id=exam_context_id
            )

            return serialize_response(True, data=config)

        except Exception as e:
            self._log_error(f'getWeightConfig failed: {e}', {
                'exam_context_id': exam_context_id
            })
            return serialize_response(False, error=f'Failed to get weight config: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createSubjectNodeWithWeight(self, node_data_json: str) -> str:
        """
        Create a new subject node with full weight configuration.

        Args:
            node_data_json: JSON string with node data including:
                - exam_context_id (required): ID to look up exam_name
                - name (required): Subject name
                - level_type (required): Hierarchy level type
                - parent_id (optional): Parent node ID
                - exam_weight_low (optional): Low end of weight range
                - exam_weight_high (optional): High end of weight range
                - relative_weight (optional): Relative weight (0-100)
                - weight_source (optional): 'official', 'derived', 'user_estimate', 'user_defined'
                - weight_locked (optional): Whether weight is locked
                - exam_source (optional): Source name for official weights
                - sort_order (optional): Display sort order

        Returns:
            JSON string: {
                'success': bool,
                'data': {subject node properties}
            } or error
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

            # Create the subject node with weight
            node = self.user_db.create_subject_node_with_weight(
                exam_context=config.exam_name,
                name=data['name'],
                level_type=data.get('level_type', 'System'),
                parent_id=data.get('parent_id'),
                exam_weight_low=data.get('exam_weight_low'),
                exam_weight_high=data.get('exam_weight_high'),
                relative_weight=data.get('relative_weight'),
                weight_source=data.get('weight_source', 'user_defined'),
                weight_locked=data.get('weight_locked', False),
                exam_source=data.get('exam_source'),
                sort_order=data.get('sort_order', 1),
                dimension_id=data.get('dimension_id')
            )

            return serialize_response(True, data=self._subject_node_to_dict(node))

        except WeightValidationError as e:
            self._log_error(
                f'createSubjectNodeWithWeight validation failed: {e}',
                {
                    'node_data_json_len': len(node_data_json) if node_data_json else 0,
                    'node_data_json_preview': (node_data_json or '')[:200],
                },
            )
            return json.dumps({
                'success': False,
                'error': str(e),
                'error_type': 'WeightValidationError'
            })
        except Exception as e:
            self._log_error(
                f'createSubjectNodeWithWeight failed: {e}',
                {
                    'node_data_json_len': len(node_data_json) if node_data_json else 0,
                    'node_data_json_preview': (node_data_json or '')[:200],
                },
            )
            return serialize_response(False, error=f'Failed to create subject node: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getSubjectExamWeightAnalysis(self, params_json: str) -> str:
        """
        Get subject vs exam weight analysis with quadrant categorization.

        Args:
            params_json: JSON with required exam_context_id

        Returns:
            JSON response with weight analysis data
        """
        if self.error_logger:
            self.error_logger.info(f"[getSubjectExamWeightAnalysis] Called with params_json: {params_json}")

        if not self.user_db:
            if self.error_logger:
                self.error_logger.error("[getSubjectExamWeightAnalysis] No user database connected")
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json) if params_json else {}
            exam_context_id = params.get('examContextId') or params.get('exam_context_id')

            if not exam_context_id:
                if self.error_logger:
                    self.error_logger.error("[getSubjectExamWeightAnalysis] Missing required exam_context_id")
                return serialize_response(False, error='exam_context_id is required for weight analysis')

            if self.error_logger:
                self.error_logger.info(f"[getSubjectExamWeightAnalysis] Analyzing exam_context_id: {exam_context_id}")

            data = self.user_db.get_subject_exam_weight_analysis(
                exam_context_id=exam_context_id
            )

            if self.error_logger:
                self.error_logger.info(f"[getSubjectExamWeightAnalysis] Analysis complete: {len(data.get('subjects', []))} subjects, efficiency: {data.get('efficiency_score', 0):.1f}")

            return serialize_response(True, data=data)

        except ValueError as e:
            if self.error_logger:
                self.error_logger.warning(f"[getSubjectExamWeightAnalysis] Validation error: {e}")
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error getting subject exam weight analysis: {e}',
                {
                    'params_json_len': len(params_json) if params_json else 0,
                    'params_json_preview': (params_json or '')[:200],
                },
            )
            return serialize_response(False, error=f'Failed to get weight analysis: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getStudyEfficiencyTrends(self, params_json: str) -> str:
        """
        Get study efficiency trends over time.

        Args:
            params_json: JSON with exam_context_id and optional weeks

        Returns:
            JSON response with efficiency trends
        """
        if self.error_logger:
            self.error_logger.info(f"[getStudyEfficiencyTrends] Called with params_json: {params_json}")

        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json) if params_json else {}
            exam_context_id = params.get('examContextId') or params.get('exam_context_id')
            weeks = params.get('weeks', 8)

            if not exam_context_id:
                return serialize_response(False, error='exam_context_id is required')

            data = self.user_db.get_study_efficiency_trends(
                exam_context_id=exam_context_id,
                weeks=weeks
            )

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting efficiency trends: {e}',
                {
                    'params_json_len': len(params_json) if params_json else 0,
                    'params_json_preview': (params_json or '')[:200],
                },
            )
            return serialize_response(False, error=f'Failed to get efficiency trends: {e}')

    # ================================================================
    # Stage 3 (Hierarchical Weight Allocation): per-edge anchor / writer / parents
    #
    # These slots wire the per-edge anchor concept through the bridge
    # so the UI can set/clear anchors and write weights against a
    # specific edge. The DB methods live on ``EdgesMixin`` (anchor /
    # source) and ``HierarchyMixin`` (relative-weight write — added by
    # Stage 2). See
    # ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md`` §3 for
    # the full scope and rationale.
    # ================================================================

    @pyqtSlot(int, bool, str, result=str)
    @instrumented_slot
    def setEdgeAnchor(
        self,
        edge_id: int,
        is_anchor: bool,
        reason: str = '',
    ) -> str:
        """Toggle ``subject_edges.is_anchor`` for a single edge.

        Stage 3 of the Hierarchical Weight Allocation Implementation
        Plan. Anchoring an edge marks it as "exempt from sibling
        rebalance" under that specific parent — anchoring
        (Cardio → Hypertension) does NOT anchor
        (Pregnancy → Hypertension). Delegates to
        :meth:`EdgesMixin.set_edge_anchor`; the history row is written
        by the DB method.

        Args:
            edge_id: ``subject_edges.id`` to mutate.
            is_anchor: New value for the flag.
            reason: Optional audit-trail reason.

        Returns:
            JSON string: ``{
                'success': True,
                'data': {
                    'ok': True,
                    'edge': {<SubjectEdge dict>},
                    'weight_history_id': int | None
                }
            }`` or ``{'success': False, 'error': ...}``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            edge, history_id = self.user_db.set_edge_anchor(
                edge_id, bool(is_anchor), reason or ''
            )
            try:
                # Notify subscribers — anchoring affects the edge's
                # rebalance behavior, even though it does not change
                # the value.
                self.weightUpdated.emit(str(edge.child_id))
            except Exception:
                pass
            return serialize_response(True, data={
                'ok': True,
                'edge': edge.to_dict(),
                'weight_history_id': history_id,
            })

        except SubjectNodeError as e:
            return json.dumps({
                'success': False,
                'error': str(e),
                'error_type': 'SubjectNodeError',
            })
        except Exception as e:
            self._log_error(
                f'setEdgeAnchor failed: {e}', {'edge_id': edge_id}
            )
            return serialize_response(
                False, error=f'Failed to set edge anchor: {e}'
            )

    @pyqtSlot(int, float, str, result=str)
    @instrumented_slot
    def updateEdgeRelativeWeight(
        self,
        edge_id: int,
        relative_weight: float,
        reason: str = '',
    ) -> str:
        """Update ``relative_weight`` on a specific edge.

        Stage 3 of the Hierarchical Weight Allocation Implementation
        Plan. Per-edge counterpart to ``updateRelativeWeight`` (which
        is node-keyed and routes through the node's primary edge).
        Calls :meth:`HierarchyMixin.update_edge_relative_weight`
        (Stage 2) under the hood, which means **siblings are not
        auto-rebalanced** — callers that want redistribution must
        invoke ``rebalanceSiblings`` explicitly. The response payload
        intentionally omits ``affected_siblings`` so consumers cannot
        accidentally rely on a non-existent side effect.

        Args:
            edge_id: ``subject_edges.id`` to mutate.
            relative_weight: New weight value (0-100).
            reason: Optional audit-trail reason.

        Returns:
            JSON string: ``{
                'success': True,
                'data': {
                    'ok': True,
                    'edge_id': int,
                    'old_weight': float,
                    'new_weight': float,
                    'anchor_set': bool
                }
            }`` or ``{'success': False, 'error': ...}``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            result = self.user_db.update_edge_relative_weight(
                edge_id,
                relative_weight,
                reason=reason if reason else None,
            )
            # Fetch the edge's child_id so subscribers can refresh the
            # affected node — the writer return shape doesn't include
            # it directly.
            try:
                edge_row = self.user_db.fetchone(
                    "SELECT child_id FROM subject_edges WHERE id = ?",
                    (edge_id,),
                )
                if edge_row:
                    self.weightUpdated.emit(str(edge_row['child_id']))
            except Exception:
                pass
            return serialize_response(True, data=result)

        except WeightValidationError as e:
            self._log_error(
                f'updateEdgeRelativeWeight validation failed: {e}', {
                    'edge_id': edge_id,
                    'relative_weight': relative_weight,
                }
            )
            return json.dumps({
                'success': False,
                'error': str(e),
                'error_type': 'WeightValidationError',
            })
        except SubjectNodeError as e:
            return json.dumps({
                'success': False,
                'error': str(e),
                'error_type': 'SubjectNodeError',
            })
        except Exception as e:
            self._log_error(
                f'updateEdgeRelativeWeight failed: {e}',
                {'edge_id': edge_id},
            )
            return serialize_response(
                False, error=f'Failed to update edge weight: {e}'
            )

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getEdgesForChild(self, child_id: int) -> str:
        """Return every parent edge for ``child_id`` (primary first).

        Stage 3 of the Hierarchical Weight Allocation Implementation
        Plan. Fuels Stage 6's "switch parent" UX: when the same node
        has multiple parent edges, the weight editor enumerates them
        so the user can pick which parent-context to edit. Ordering
        (``is_primary DESC, parent_id ASC``) ensures the canonical
        primary edge always leads the list.

        Args:
            child_id: ``subject_nodes.id`` of the child.

        Returns:
            JSON string: ``{
                'success': True,
                'data': [
                    {'edge_id', 'parent_id', 'parent_name', 'child_id',
                     'dimension_id', 'relative_weight', 'is_anchor',
                     'weight_source', 'sort_order', 'is_primary'},
                    ...
                ]
            }`` or ``{'success': False, 'error': ...}``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            edges = self.user_db.get_edges_for_child(child_id)
            return serialize_response(True, data=edges)
        except Exception as e:
            self._log_error(
                f'getEdgesForChild failed: {e}', {'child_id': child_id}
            )
            return serialize_response(
                False, error=f'Failed to get edges for child: {e}'
            )

    # =====================================================================
    # Stage 5 — Allocation bridge & read-side API
    # (docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 5")
    #
    # Appended at the end of the mixin to avoid merge conflicts with the
    # parallel Stage 3 (edge-anchor bridge) work above. Together they
    # form the read+write surface for the Hamilton allocator (Stage 1)
    # and exam length triple (Stage 4).
    # =====================================================================

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getQuestionAllocation(self, parent_id: int) -> str:
        """Per-parent question allocation under the Hamilton allocator.

        Stage 5: surfaces the Stage 1 allocator + Stage 4 exam length
        triple to the UI so the weight panel can render ``9.2% • ~26 q``
        and the sibling preview chart can show per-edge integer counts.

        Stage 8: extends the response payload with an ``is_adaptive``
        flag (``True`` iff the parent's exam context has
        ``length_kind='range'``) and, in adaptive mode, returns the
        per-child ``allocated_q`` as a **float** (raw exact share) so
        the UI can render ``~26.4 q (planning estimate)`` instead of
        lying about a precision the CAT exam doesn't have. The slot
        signature is unchanged; only the payload shape gains the
        ``is_adaptive`` key and the ``allocated_q`` value type widens
        from ``int`` to ``int|float``.

        Args:
            parent_id: ``subject_nodes.id`` of the parent whose outgoing
                edges should be allocated.

        Returns:
            JSON string::

                {
                    'success': True,
                    'data': {
                        'ok': True,
                        'parent_id': int,
                        'total_q': int | None,        # None when
                                                      # length_kind='unknown'
                        'length_kind': str,           # 'fixed' | 'range'
                                                      # | 'unknown'
                        'is_adaptive': bool,          # Stage 8: True iff
                                                      # length_kind='range'
                        'children': [
                            {
                                'edge_id': int,
                                'child_id': int,
                                'child_name': str,
                                'allocated_q': int | float | None,
                                                      # float when
                                                      # is_adaptive=True
                                'low_q': int | None,
                                'high_q': int | None,
                                'weight_source': str,
                                'is_anchor': bool,
                                'relative_weight': float | None,
                            }, ...
                        ]
                    }
                }

            ``length_kind='unknown'`` ⇒ every ``allocated_q``/``low_q``/
            ``high_q`` is null; the UI suppresses the question-count
            suffix and shows percentages only. ``is_adaptive=False``
            in that case (CAT semantics require a planning baseline).
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            # Locate the parent's exam context — we need it to know
            # length_typical/kind. The parent's row carries
            # ``exam_context`` (the exam_name string); we cross-walk
            # to ``exam_contexts.id`` via that name.
            parent_row = self.user_db.fetchone(
                """
                SELECT sn.exam_context AS exam_name,
                       ec.id AS exam_context_id,
                       ec.length_kind AS length_kind,
                       ec.length_typical AS length_typical,
                       ec.length_min AS length_min,
                       ec.length_max AS length_max,
                       sn.exam_weight_low AS exam_weight_low,
                       sn.exam_weight_high AS exam_weight_high
                FROM subject_nodes sn
                LEFT JOIN exam_contexts ec ON ec.exam_name = sn.exam_context
                WHERE sn.id = ?
                """,
                (parent_id,),
            )
            if not parent_row:
                return serialize_response(
                    False, error=f'Parent node {parent_id} not found'
                )

            length_kind = parent_row['length_kind'] or 'unknown'
            length_typical = parent_row['length_typical']
            # Stage 8 — adaptive (CAT) exams skip integer rounding in
            # the allocator so the UI can render ``~26.4 q (planning
            # estimate)``. Fall back to the canonical helper rather
            # than re-deriving the rule so the contract stays in one
            # place. The exam_context_id is available on parent_row
            # via the LEFT JOIN above.
            is_adaptive = False
            exam_context_id = parent_row['exam_context_id']
            if exam_context_id is not None:
                try:
                    is_adaptive = self.user_db.is_adaptive_exam(exam_context_id)
                except Exception:
                    # Defensive — a lookup failure shouldn't break
                    # allocation; we just lose the CAT formatting.
                    is_adaptive = False

            # Compute the parent's question budget by walking up the
            # edge chain from the System root. For Topic-level parents
            # this scales length_typical through every ancestor's
            # relative_weight. The whole-tree endpoint applies the
            # same per-path scaling — they agree.
            if length_kind == 'unknown' or length_typical is None:
                total_q: Optional[int] = None
            else:
                total_q = self._compute_parent_q_budget(
                    parent_id, int(length_typical)
                )

            children: list = []
            if total_q is not None and total_q > 0:
                # Stage 8 — pass ``is_adaptive`` so the allocator
                # returns float shares (no integer rounding) for CAT
                # exams. Non-adaptive callers see the same int output
                # as before.
                allocations = self.user_db.allocate_questions_hamilton(
                    parent_id, total_q, is_adaptive=is_adaptive
                )
            else:
                allocations = {}

            # Pull the sibling rows once for the response shape.
            sibling_edges = self.user_db.get_sibling_edges(parent_id)
            for edge in sibling_edges:
                edge_id = edge['edge_id']
                rw = edge['relative_weight']

                if total_q is None or rw is None:
                    low_q: Optional[int] = None
                    high_q: Optional[int] = None
                else:
                    plow = parent_row['exam_weight_low']
                    phigh = parent_row['exam_weight_high']
                    if plow is not None and phigh is not None:
                        # Parent has a range — propagate it to the
                        # edge's q_low/q_high.
                        low_q = int(round(
                            plow * length_typical / 100.0 * rw / 100.0
                        ))
                        high_q = int(round(
                            phigh * length_typical / 100.0 * rw / 100.0
                        ))
                    else:
                        # No range — the Hamilton allocation is the
                        # only signal we have, so q_low == q_high ==
                        # allocated_q.
                        low_q = allocations.get(edge_id)
                        high_q = allocations.get(edge_id)

                children.append({
                    'edge_id': edge_id,
                    'child_id': edge['child_id'],
                    'child_name': edge['child_name'],
                    'allocated_q': allocations.get(edge_id),
                    'low_q': low_q,
                    'high_q': high_q,
                    'weight_source': edge['weight_source'],
                    'is_anchor': bool(edge['is_anchor']),
                    'relative_weight': rw,
                })

            return serialize_response(True, data={
                'ok': True,
                'parent_id': parent_id,
                'total_q': total_q,
                'length_kind': length_kind,
                'is_adaptive': is_adaptive,
                'children': children,
            })

        except Exception as e:
            self._log_error(
                f'getQuestionAllocation failed: {e}',
                {'parent_id': parent_id},
            )
            return serialize_response(
                False, error=f'Failed to compute question allocation: {e}'
            )

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getEffectiveQuestionCounts(self, exam_context_id: int) -> str:
        """Whole-tree effective question counts for an exam context.

        Stage 5: the analytics-dashboard endpoint. Returns the flat list
        produced by :meth:`HierarchyMixin.get_effective_question_counts`
        — one row per ``subject_edges`` row, with the per-edge
        ``q_typical / q_low / q_high`` computed by walking the DAG
        downward from each System root.

        Stage 8: each returned row carries an ``is_adaptive: bool``
        field (``True`` iff the exam context has ``length_kind='range'``,
        i.e. is a CAT). In adaptive mode ``q_typical`` is a **float**
        (raw allocator share, no integer rounding) so the UI can
        render ``~26.4 q (planning estimate)``. Backward-compat: the
        legacy `Array<row>` shape is preserved (this slot returns the
        list directly via ``serialize_response``), with the new field
        layered onto each row.

        Args:
            exam_context_id: Target exam context.

        Returns:
            JSON string ``{'success': True, 'data': [row, ...]}`` where
            each row carries the keys documented on
            :meth:`HierarchyMixin.get_effective_question_counts`,
            including the Stage 8 ``is_adaptive`` flag.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            rows = self.user_db.get_effective_question_counts(
                exam_context_id=exam_context_id
            )
            return serialize_response(True, data=rows)

        except ValueError as e:
            # Unknown exam_context_id surfaces here as a clean message.
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'getEffectiveQuestionCounts failed: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(
                False, error=f'Failed to compute effective question counts: {e}'
            )

    # =====================================================================
    # Stage 6 — Canonical user-typed-value endpoint.
    # (docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 6")
    #
    # Replaces the pre-Stage-6 hot patch in weight_editor.js that called
    # ``updateRelativeWeight`` followed by ``setEdgeAnchor`` for every
    # explicit user edit. ``setExplicitWeight`` collapses both writes
    # into a single atomic operation that:
    #   1. Converts ``Q`` to ``relative_weight`` when needed.
    #   2. Writes the value with ``set_anchor=True`` and
    #      ``source='user_explicit'`` (per design §3.4).
    #   3. Mirrors onto ``subject_nodes.relative_weight`` so legacy
    #      read paths (chip render, analytics) reflect the new value.
    # =====================================================================

    @pyqtSlot(int, float, str, str, result=str)
    @instrumented_slot
    def setExplicitWeight(
        self,
        edge_id: int,
        value: float,
        unit: str,
        reason: str = '',
    ) -> str:
        """Canonical user-typed-value endpoint (Stage 6).

        Atomic write replacing the pre-Stage-6 hot patch in
        ``weight_editor.js`` (which called ``updateRelativeWeight``
        followed by ``setEdgeAnchor`` for every Apply). Behavior:

        * When ``unit='%'`` the value is interpreted directly as the
          edge's ``relative_weight``.
        * When ``unit='Q'`` the value is the integer question count and
          is converted via
          ``relative_weight = (value / parent_q_typical) * 100``.
          When ``parent_q_typical`` is ``None`` (the parent's
          ``length_kind='unknown'``) ``Q`` mode is unsupported and the
          slot returns ``ok=False`` with a clear error.
        * The write is always anchored
          (``subject_edges.is_anchor=TRUE``) and tagged
          ``weight_source='user_explicit'`` because, by definition, the
          user typed this value (per design §3.4).
        * The value is mirrored onto ``subject_nodes.relative_weight``
          so the legacy read paths (chip render, analytics drill-down)
          see the new number without waiting for Stage 10's column drop.

        Args:
            edge_id: ``subject_edges.id`` to update.
            value: User-typed number, interpreted per ``unit``.
            unit: ``'%'`` or ``'Q'``.
            reason: Audit-trail reason. Empty string normalizes to a
                default ``'User-typed explicit value'``.

        Returns:
            JSON string ``{
                'success': True,
                'data': {
                    'ok': True,
                    'edge_id': int,
                    'applied_relative_weight': float,
                    'applied_question_count': int | None,
                    'unit': str,
                }
            }`` or ``{'success': False, 'error': ...}``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        # Normalize and validate the unit upfront so callers get a clean
        # error before we touch the DB.
        normalized_unit = (unit or '').strip()
        if normalized_unit not in ('%', 'Q'):
            return serialize_response(
                False,
                error=f"unit must be '%' or 'Q' (got {unit!r})",
            )

        try:
            # Resolve the edge so we know which parent to ask for
            # ``q_typical``. Done in one query so we have parent_id +
            # child_id in hand for downstream writes.
            edge_row = self.user_db.fetchone(
                "SELECT id, parent_id, child_id FROM subject_edges "
                "WHERE id = ?",
                (edge_id,),
            )
            if edge_row is None:
                return serialize_response(
                    False, error=f'Subject edge {edge_id} not found'
                )

            parent_id = edge_row['parent_id']
            child_id = edge_row['child_id']

            # Look up the parent's question budget. Reuses the helper
            # introduced for Stage 5's ``getQuestionAllocation`` so we
            # have one source of truth for "how big is this parent?".
            parent_q_typical = None
            try:
                parent_row = self.user_db.fetchone(
                    """
                    SELECT ec.length_kind AS length_kind,
                           ec.length_typical AS length_typical
                    FROM subject_nodes sn
                    LEFT JOIN exam_contexts ec
                        ON ec.exam_name = sn.exam_context
                    WHERE sn.id = ?
                    """,
                    (parent_id,),
                )
                if (
                    parent_row
                    and parent_row['length_kind'] not in (None, 'unknown')
                    and parent_row['length_typical'] is not None
                ):
                    parent_q_typical = self._compute_parent_q_budget(
                        parent_id, int(parent_row['length_typical'])
                    )
            except Exception:
                # Defensive — if length lookup fails, we still let
                # ``unit='%'`` through; ``unit='Q'`` will surface a
                # clean error below.
                parent_q_typical = None

            # Convert Q → % when needed.
            if normalized_unit == 'Q':
                if not parent_q_typical or parent_q_typical <= 0:
                    return serialize_response(
                        False,
                        error=(
                            "Cannot interpret value as questions: the "
                            "exam has no length_typical (length_kind="
                            "'unknown') or the parent has no question "
                            "budget. Use '%' instead."
                        ),
                    )
                computed_rw = (float(value) / float(parent_q_typical)) * 100.0
            else:
                computed_rw = float(value)

            # Write the edge value + anchor + source in one atomic call.
            writer_result = self.user_db.update_edge_relative_weight(
                edge_id,
                computed_rw,
                set_anchor=True,
                source='user_explicit',
                reason=reason or 'User-typed explicit value',
            )

            # Mirror onto subject_nodes.relative_weight for legacy
            # read paths (chip render, analytics). Without this mirror
            # the chip won't update post-write because the polyhierarchy
            # cut-over to subject_edges is incomplete (Stage 10 will
            # finish the drop). Mirrors the pattern in
            # ``HierarchyMixin.update_subject_relative_weight`` and
            # ``_write_rebalanced_edge_weight``.
            #
            # NOTE: ``subject_nodes.weight_source`` has a legacy CHECK
            # constraint that only accepts the original four enum
            # values; ``'user_explicit'`` is per-edge only. We mirror
            # to ``'user_defined'`` (the closest legacy semantic — the
            # user defined this value) so the constraint is satisfied
            # without losing the "user touched it" signal.
            try:
                with self.user_db.transaction():
                    self.user_db.execute(
                        """
                        UPDATE subject_nodes
                        SET relative_weight = ?,
                            weight_source = CASE
                                WHEN weight_source = 'official' THEN 'official'
                                ELSE 'user_defined'
                            END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (computed_rw, child_id),
                    )
            except Exception as mirror_err:
                # Mirror failure shouldn't poison the success of the
                # canonical edge write. Log and continue.
                self._log_error(
                    f'setExplicitWeight: mirror to subject_nodes failed: {mirror_err}',
                    {'edge_id': edge_id, 'child_id': child_id},
                )

            # Compute the applied_question_count for the response.
            if parent_q_typical and parent_q_typical > 0:
                applied_q = int(round(computed_rw * parent_q_typical / 100.0))
            else:
                applied_q = None

            try:
                self.weightUpdated.emit(str(child_id))
            except Exception:
                pass

            return serialize_response(True, data={
                'ok': True,
                'edge_id': edge_id,
                'applied_relative_weight': computed_rw,
                'applied_question_count': applied_q,
                'unit': normalized_unit,
                'old_weight': writer_result.get('old_weight'),
            })

        except WeightValidationError as e:
            self._log_error(
                f'setExplicitWeight validation failed: {e}',
                {'edge_id': edge_id, 'value': value, 'unit': unit},
            )
            return json.dumps({
                'success': False,
                'error': str(e),
                'error_type': 'WeightValidationError',
            })
        except SubjectNodeError as e:
            return json.dumps({
                'success': False,
                'error': str(e),
                'error_type': 'SubjectNodeError',
            })
        except Exception as e:
            self._log_error(
                f'setExplicitWeight failed: {e}',
                {'edge_id': edge_id, 'value': value, 'unit': unit},
            )
            return serialize_response(
                False, error=f'Failed to set explicit weight: {e}'
            )

    def _compute_parent_q_budget(
        self, parent_id: int, length_typical: int
    ) -> int:
        """Derive the parent's integer question budget for Q ↔ % conversion.

        Helper for :meth:`getQuestionAllocation` and
        :meth:`setExplicitWeight`. Delegates to the canonical walker
        :meth:`HierarchyMixin.get_effective_question_counts` (Stage 5)
        which already handles every edge case correctly:

        * Roots: midpoint of ``subject_nodes.exam_weight_low/high`` ×
          ``length_typical``.
        * Non-roots: per-parent Hamilton allocation (Stage 1), which
          consults both ``subject_edges.relative_weight`` and the
          legacy ``subject_nodes.relative_weight`` fallback when the
          edge is uncategorized (rw=NULL on the edge but a weight set
          on the node from pre-polyhierarchy data).

        Pre-fix: this helper re-implemented the walk and returned
        ``length_typical`` whenever any ancestor edge had ``rw=NULL``,
        which makes deeply-nested descendants of partially-uncategorized
        chains (e.g. Histology under Anatomy under GI in IM Shelf when
        the GI→Anatomy edge has NULL weight despite Anatomy carrying
        16.667 on ``subject_nodes``) report a budget of the whole exam
        instead of their actual ~6 q share. That made the Q-mode
        segmented control produce nonsensical numbers (~93 q for a
        topic that really has ~2 q).

        Args:
            parent_id: The ``subject_nodes.id`` whose question budget
                we want.
            length_typical: Defensive fallback when the node isn't
                attached to any exam context (orphaned data) — should
                effectively never fire in normal use.

        Returns:
            Integer question budget. ``length_typical`` only as a
            last-resort fallback for orphaned / corrupted data.
        """
        # Find the exam_context_id that owns this node. The legacy
        # schema stores ``subject_nodes.exam_context`` as the exam's
        # name string (not its ID); join through ``exam_contexts.exam_name``
        # to recover the integer ID that ``get_effective_question_counts``
        # accepts.
        exam_row = self.user_db.fetchone(
            """
            SELECT ec.id AS exam_context_id
            FROM subject_nodes sn
            JOIN exam_contexts ec ON ec.exam_name = sn.exam_context
            WHERE sn.id = ?
            """,
            (parent_id,),
        )
        if not exam_row:
            return length_typical

        try:
            counts = self.user_db.get_effective_question_counts(
                exam_row['exam_context_id']
            )
        except Exception:
            # The Stage 5 walker can raise for missing exam contexts;
            # fall back to the whole-exam budget so the UI still works.
            return length_typical

        # Pick the row that represents *this* node. ``get_effective_
        # question_counts`` emits one row per edge plus one synthetic
        # root row per System-level node (the bugfix 8890d8a added
        # the root rows). In both shapes, ``child_id`` is the node id
        # we care about.
        #
        # Polyhierarchy edge case: a node with multiple parent edges
        # appears multiple times. Pick the largest q_typical so the Q
        # segmented control sizes against the most generous parent
        # context — matches the chip-stamping behavior of
        # enrichNodesWithQuestionCounts (see tree_editor.js).
        best_q: Optional[int] = None
        for row in counts:
            if row['child_id'] != parent_id:
                continue
            q = row['q_typical']
            if q is None:
                continue
            if best_q is None or q > best_q:
                best_q = q

        if best_q is None:
            return length_typical
        return int(best_q)

    # =====================================================================
    # Stage 7 — Interval-rounding feasibility report (read-only).
    # (docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 7";
    #  docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md §3.5)
    #
    # Surfaces the per-parent feasibility report so the weight editor
    # can render the soft-warning badge in the modal and the tree
    # editor can show warning dots on parent rows whose children's
    # weights don't fit cleanly. Save-then-warn: these slots only
    # READ, never write, and the UI never blocks save.
    # =====================================================================

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getFeasibilityReport(self, parent_id: int) -> str:
        """Per-parent feasibility report for the weight modal badge.

        Stage 7: looks up the parent's exam context, resolves
        ``length_typical`` (the planning baseline used for q
        conversion), then delegates to
        :meth:`HierarchyMixin.validate_hierarchy_feasibility`.

        When ``length_kind='unknown'`` no integer feasibility check is
        possible, so the slot returns a short-circuit ``status='ok'``
        payload (with empty violators) so the UI hides the badge.

        Args:
            parent_id: ``subject_nodes.id`` of the parent whose
                outgoing edges should be validated.

        Returns:
            JSON string ``{
                'success': True,
                'data': {
                    'ok': True,
                    'parent_id': int,
                    'length_kind': 'fixed' | 'range' | 'unknown',
                    'status': 'ok' | 'under' | 'over' | 'infeasible',
                    'parent_low_q':  int | None,
                    'parent_high_q': int | None,
                    'children_low_sum_q':  int,
                    'children_high_sum_q': int,
                    'children_low_sum_pct':  float,
                    'children_high_sum_pct': float,
                    'violators': [
                        {'edge_id', 'child_id', 'child_name', 'reason'},
                        ...
                    ]
                }
            }`` or ``{'success': False, 'error': ...}``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            # Resolve the parent's exam context to recover
            # length_kind / length_typical. Parents that don't belong
            # to any exam context surface a clean error.
            parent_row = self.user_db.fetchone(
                """
                SELECT sn.exam_context AS exam_name,
                       ec.id AS exam_context_id,
                       ec.length_kind AS length_kind,
                       ec.length_typical AS length_typical
                FROM subject_nodes sn
                LEFT JOIN exam_contexts ec ON ec.exam_name = sn.exam_context
                WHERE sn.id = ?
                """,
                (parent_id,),
            )
            if not parent_row:
                return serialize_response(
                    False, error=f'Parent node {parent_id} not found'
                )

            length_kind = parent_row['length_kind'] or 'unknown'
            length_typical = parent_row['length_typical']

            if length_kind == 'unknown' or length_typical is None:
                # No integer feasibility check possible without a
                # length budget. Surface a clean 'ok' so the UI hides
                # the badge.
                return serialize_response(True, data={
                    'ok': True,
                    'parent_id': parent_id,
                    'length_kind': length_kind,
                    'status': 'ok',
                    'parent_low_q': None,
                    'parent_high_q': None,
                    'children_low_sum_q': 0,
                    'children_high_sum_q': 0,
                    'children_low_sum_pct': 0.0,
                    'children_high_sum_pct': 0.0,
                    'violators': [],
                })

            report = self.user_db.validate_hierarchy_feasibility(
                parent_id, int(length_typical)
            )
            payload = {
                'ok': True,
                'parent_id': parent_id,
                'length_kind': length_kind,
            }
            payload.update(report)
            return serialize_response(True, data=payload)

        except Exception as e:
            self._log_error(
                f'getFeasibilityReport failed: {e}',
                {'parent_id': parent_id},
            )
            return serialize_response(
                False, error=f'Failed to compute feasibility report: {e}'
            )

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getAllFeasibilityReports(self, exam_context_id: int) -> str:
        """Whole-tree feasibility reports keyed by parent_id.

        Stage 7: fuels the warning-dot rendering on the tree editor.
        Delegates to
        :meth:`HierarchyMixin.validate_hierarchy_feasibility_recursive`.
        Every parent in the exam (i.e. every node with at least one
        outgoing edge) gets a report; the UI iterates and stamps a
        warning dot wherever ``status != 'ok'``.

        Args:
            exam_context_id: Target exam context.

        Returns:
            JSON string ``{
                'success': True,
                'data': {
                    'parents': {
                        <parent_id_str>: {<feasibility-report-dict>},
                        ...
                    }
                }
            }`` — note the parent_id key is serialized as a string
            because JSON object keys must be strings; the JS consumer
            coerces back to int when needed.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            reports = self.user_db.validate_hierarchy_feasibility_recursive(
                exam_context_id
            )
            # JSON object keys must be strings — stringify the parent_id
            # keys so serialize_response doesn't choke on int keys.
            stringified = {str(pid): rep for pid, rep in reports.items()}
            return serialize_response(True, data={
                'parents': stringified,
            })

        except ValueError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'getAllFeasibilityReports failed: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(
                False, error=f'Failed to compute feasibility reports: {e}'
            )
