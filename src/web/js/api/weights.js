/**
 * WIMI API — Weight Management Operations
 */
(function(api) {
    'use strict';

    api.updateSubjectNodeWeight = async function(nodeId, newWeight, reason, userNotes) {
        return api._callBridge('updateSubjectNodeWeight', nodeId, newWeight, reason || '', userNotes || '');
    };

    api.getWeightHistory = async function(nodeId, limit) {
        return api._callBridge('getWeightHistory', nodeId, limit || 50);
    };

    /**
     * Update a node's relative weight on its primary parent edge.
     *
     * **Stage 2 behavior change (WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md):
     * siblings are no longer auto-touched.** Callers wanting redistribution
     * must invoke ``api.rebalanceSiblings`` separately. The response now
     * always reports ``rebalanced: false`` and ``affected_siblings: []``.
     *
     * @param {{nodeId:number, relativeWeight:number, reason?:string}} params
     * @returns {Promise<object>} The unwrapped data payload from the bridge.
     */
    api.updateRelativeWeight = async function(params) {
        params = params || {};
        if (!params.nodeId) throw new Error('nodeId is required');
        if (params.relativeWeight === undefined || params.relativeWeight === null) {
            throw new Error('relativeWeight is required');
        }
        return api._callBridge('updateRelativeWeight', params.nodeId, params.relativeWeight, params.reason || '');
    };

    /**
     * Explicitly rebalance the sibling edges under a given parent.
     *
     * Stage 2 opt-in entry point: ``updateRelativeWeight`` no longer
     * auto-mutates siblings, so callers that want proportional
     * redistribution must trigger it explicitly. Anchored edges
     * (``is_anchor=TRUE``) and legacy ``weight_locked`` nodes are
     * excluded from the adjustable set.
     *
     * @param {{parentId:number, reason?:string}} params
     * @returns {Promise<{ok:boolean, parent_id:number,
     *     affected_edges:Array<{edge_id:number, child_id:number,
     *         old_weight:number, new_weight:number}>,
     *     skipped:Array<{edge_id:number, child_id:number, reason:string}>}>}
     */
    api.rebalanceSiblings = async function(params) {
        params = params || {};
        if (params.parentId === undefined || params.parentId === null) {
            throw new Error('parentId is required');
        }
        return api._callBridge('rebalanceSiblings', params.parentId, params.reason || '');
    };

    api.getSubjectsWithEffectiveWeights = async function(params) {
        params = params || {};
        if (!params.examContextId) throw new Error('examContextId is required');
        return api._callBridge('getSubjectsWithEffectiveWeights',
            params.examContextId,
            params.includeChildren !== false
        );
    };

    api.getWeightConfig = async function(examContextId) {
        if (!examContextId) throw new Error('examContextId is required');
        return api._callBridge('getWeightConfig', examContextId);
    };

    api.createSubjectNodeWithWeight = async function(nodeData) {
        return api._callBridge('createSubjectNodeWithWeight', JSON.stringify(nodeData));
    };

    api.getSubjectExamWeightAnalysis = async function(params) {
        params = params || {};
        if (!params.examContextId) throw new Error('examContextId is required for weight analysis');
        return api._callBridge('getSubjectExamWeightAnalysis', JSON.stringify({
            examContextId: params.examContextId
        }));
    };

    api.getStudyEfficiencyTrends = async function(params) {
        params = params || {};
        if (!params.examContextId) throw new Error('examContextId is required');
        return api._callBridge('getStudyEfficiencyTrends', JSON.stringify({
            examContextId: params.examContextId,
            weeks: params.weeks || 8
        }));
    };

    api.readDocumentation = async function(filename) {
        if (!filename) throw new Error('filename is required');
        return api._callBridge('readDocumentation', filename);
    };

    // ====================================================================
    // Stage 3 (Hierarchical Weight Allocation): per-edge anchor / writer / parents
    //
    // These wrappers expose the new edge-aware bridge slots so the UI can
    // set/clear anchors and write weights against a specific edge. See
    // ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md`` §3.
    // ====================================================================

    /**
     * Toggle the anchor flag on a single edge.
     *
     * Anchored edges (``subject_edges.is_anchor=TRUE``) are exempt from
     * sibling rebalance under the same parent. Anchor scope is *per edge*
     * — anchoring (Cardio → Hypertension) does NOT anchor any other
     * edge into Hypertension.
     *
     * @param {{edgeId:number, isAnchor:boolean, reason?:string}} params
     * @returns {Promise<{ok:boolean, edge:object, weight_history_id:number|null}>}
     */
    api.setEdgeAnchor = async function(params) {
        params = params || {};
        if (params.edgeId === undefined || params.edgeId === null) {
            throw new Error('edgeId is required');
        }
        if (params.isAnchor === undefined || params.isAnchor === null) {
            throw new Error('isAnchor is required');
        }
        return api._callBridge(
            'setEdgeAnchor',
            params.edgeId,
            !!params.isAnchor,
            params.reason || ''
        );
    };

    /**
     * Update the relative weight of a specific edge.
     *
     * Per-edge counterpart to ``updateRelativeWeight`` (node-keyed,
     * routes through the primary edge). **Siblings are not
     * auto-rebalanced** — callers wanting redistribution must invoke
     * ``api.rebalanceSiblings`` separately. The response payload
     * intentionally omits ``affected_siblings`` so consumers cannot
     * accidentally rely on a non-existent side effect.
     *
     * @param {{edgeId:number, relativeWeight:number, reason?:string}} params
     * @returns {Promise<{ok:boolean, edge_id:number, old_weight:number,
     *     new_weight:number, anchor_set:boolean}>}
     */
    api.updateEdgeRelativeWeight = async function(params) {
        params = params || {};
        if (params.edgeId === undefined || params.edgeId === null) {
            throw new Error('edgeId is required');
        }
        if (params.relativeWeight === undefined || params.relativeWeight === null) {
            throw new Error('relativeWeight is required');
        }
        return api._callBridge(
            'updateEdgeRelativeWeight',
            params.edgeId,
            params.relativeWeight,
            params.reason || ''
        );
    };

    /**
     * Get every parent edge for a child (primary first).
     *
     * Fuels Stage 6's "switch parent" UX. Result is ordered
     * ``is_primary DESC, parent_id ASC`` so the canonical primary
     * edge always leads the list. Each entry carries the per-edge
     * weight metadata (``relative_weight``, ``is_anchor``,
     * ``weight_source``) plus the parent's display name.
     *
     * @param {number} childId
     * @returns {Promise<Array<{edge_id:number, parent_id:number,
     *     parent_name:string, child_id:number, dimension_id:number|null,
     *     relative_weight:number|null, is_anchor:boolean,
     *     weight_source:string, sort_order:number, is_primary:boolean}>>}
     */
    api.getEdgesForChild = async function(childId) {
        if (childId === undefined || childId === null) {
            throw new Error('childId is required');
        }
        return api._callBridge('getEdgesForChild', childId);
    };

    // ====================================================================
    // Stage 5 — Allocation read-side API
    // (docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 5")
    //
    // Wrappers around the per-parent and whole-tree question-count
    // endpoints. Both wrappers are appended at the end to dodge merge
    // conflicts with the parallel Stage 3 work above.
    // ====================================================================

    /**
     * Per-parent question allocation under the Hamilton allocator.
     *
     * Returns the per-edge integer question counts when the exam has a
     * ``length_typical`` (i.e. ``length_kind`` is ``'fixed'`` or
     * ``'range'``). When ``length_kind === 'unknown'`` the response
     * carries ``total_q: null`` and every ``allocated_q``/``low_q``/
     * ``high_q`` is ``null`` — the UI should degrade to percentage-only
     * rendering and hide any "~N q" suffix.
     *
     * Stage 8 (CAT / adaptive exams)
     * -------------------------------
     * The response now carries an ``is_adaptive: boolean`` field at
     * the top level. ``is_adaptive=true`` means the exam's
     * ``length_kind === 'range'`` (NCLEX-RN and similar adaptive
     * exams). In that case the per-child ``allocated_q`` is a
     * **float** (raw allocator share, not integer-rounded) so the
     * UI can render ``~26.4 q (planning estimate)`` instead of
     * fabricating precision the CAT exam doesn't have. For
     * ``is_adaptive=false`` the value remains an integer Hamilton
     * allocation as before.
     *
     * @param {number} parentId - subject_nodes.id of the parent whose
     *     outgoing edges should be allocated.
     * @returns {Promise<{
     *     ok: boolean, parent_id: number,
     *     total_q: number|null,
     *     length_kind: 'fixed'|'range'|'unknown',
     *     is_adaptive: boolean,
     *     children: Array<{
     *         edge_id: number, child_id: number, child_name: string,
     *         allocated_q: number|null, low_q: number|null,
     *         high_q: number|null, weight_source: string,
     *         is_anchor: boolean, relative_weight: number|null
     *     }>
     * }>}
     */
    api.getQuestionAllocation = async function(parentId) {
        if (parentId === undefined || parentId === null) {
            throw new Error('parentId is required');
        }
        return api._callBridge('getQuestionAllocation', parentId);
    };

    /**
     * Whole-tree effective question counts for an exam context.
     *
     * Returns a flat list of one row per ``subject_edges`` row in the
     * exam context, each carrying ``q_typical``/``q_low``/``q_high``
     * computed by walking the DAG downward from each System root.
     *
     * Length-kind degradation: when the exam is
     * ``length_kind === 'unknown'`` (no planning baseline), every row's
     * ``q_typical``/``q_low``/``q_high`` is ``null`` — analytics UIs
     * should suppress the "~N q" suffix and render percentages only.
     *
     * Stage 8 (CAT / adaptive exams)
     * -------------------------------
     * Every row now carries an ``is_adaptive: boolean`` field
     * (``true`` iff the exam's ``length_kind === 'range'``). In
     * adaptive mode each row's ``q_typical`` is a **float** (raw
     * allocator share, not integer-rounded) so the UI can render
     * ``~26.4 q (planning estimate)`` instead of fabricating
     * precision the CAT exam doesn't have. For ``is_adaptive=false``
     * the value remains an integer Hamilton allocation as before.
     *
     * @param {number} examContextId
     * @returns {Promise<Array<{
     *     edge_id: number, child_id: number, child_name: string,
     *     parent_id: number, parent_name: string, parent_path: string,
     *     relative_weight: number|null, weight_source: string,
     *     is_anchor: boolean, is_adaptive: boolean,
     *     q_typical: number|null, q_low: number|null, q_high: number|null
     * }>>}
     */
    api.getEffectiveQuestionCounts = async function(examContextId) {
        if (examContextId === undefined || examContextId === null) {
            throw new Error('examContextId is required');
        }
        return api._callBridge('getEffectiveQuestionCounts', examContextId);
    };

    // ====================================================================
    // Stage 6 — Canonical user-typed-value endpoint.
    // (docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 6")
    //
    // Replaces the pre-Stage-6 hot patch in weight_editor.js
    // (updateRelativeWeight + setEdgeAnchor two-call pattern) with one
    // atomic bridge call that writes the value, anchors the edge, and
    // tags weight_source='user_explicit' all at once.
    // ====================================================================

    /**
     * Atomic user-typed-value write with anchor + 'user_explicit' source.
     *
     * Unit semantics:
     *   - ``'%'`` — value IS the relative_weight (0-100).
     *   - ``'Q'`` — value is the question count; the bridge converts to
     *     percent via ``(value / parent_q_typical) * 100``. When the
     *     exam is ``length_kind='unknown'`` the bridge returns
     *     ``ok=false`` because there's no question budget to convert
     *     against — callers should validate ``length_kind`` upstream
     *     and gate the segmented control accordingly.
     *
     * Always anchors the edge (``is_anchor=TRUE``) and tags
     * ``weight_source='user_explicit'`` because the user typed this
     * value explicitly. Use ``api.setEdgeAnchor`` if the user wants to
     * un-anchor afterwards.
     *
     * @param {{edgeId:number, value:number, unit:('%'|'Q'),
     *     reason?:string}} params
     * @returns {Promise<{ok:boolean, edge_id:number,
     *     applied_relative_weight:number,
     *     applied_question_count:number|null,
     *     unit:string, old_weight:number|null}>}
     */
    api.setExplicitWeight = async function(params) {
        params = params || {};
        if (params.edgeId === undefined || params.edgeId === null) {
            throw new Error('edgeId is required');
        }
        if (params.value === undefined || params.value === null) {
            throw new Error('value is required');
        }
        if (params.unit !== '%' && params.unit !== 'Q') {
            throw new Error("unit must be '%' or 'Q'");
        }
        return api._callBridge(
            'setExplicitWeight',
            params.edgeId,
            params.value,
            params.unit,
            params.reason || ''
        );
    };

    // ====================================================================
    // Stage 7 — Interval-rounding feasibility report (read-only).
    // (docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 7";
    //  docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md §3.5)
    //
    // Surfaces the per-parent feasibility report so the weight editor
    // can render the soft-warning badge in the modal slot Stage 6
    // reserved, and the tree editor can show warning dots on rows
    // whose parent is non-`ok`.
    // ====================================================================

    /**
     * Per-parent feasibility report.
     *
     * Status semantics:
     *   - ``'ok'``         — children's [low, high] ranges fit cleanly
     *                        inside parent's range
     *   - ``'under'``      — Σ child highs < parent low (room for more)
     *   - ``'over'``       — Σ child lows > parent high (over-claimed)
     *   - ``'infeasible'`` — ``Σ⌈child_lo·N/100⌉ > ⌊parent_hi·N/100⌋``
     *                        (rounding-class violation; mathematically
     *                        impossible even with integer rounding
     *                        latitude)
     *
     * Length-kind degradation: when the exam is ``length_kind ===
     * 'unknown'`` (no planning baseline) the integer feasibility check
     * cannot run; the bridge returns ``status='ok'`` with empty
     * violators so the UI hides the badge.
     *
     * @param {number} parentId - subject_nodes.id of the parent whose
     *     outgoing edges should be validated.
     * @returns {Promise<{
     *     ok: boolean, parent_id: number,
     *     length_kind: 'fixed'|'range'|'unknown',
     *     status: 'ok'|'under'|'over'|'infeasible',
     *     parent_low_q: number|null, parent_high_q: number|null,
     *     children_low_sum_q: number, children_high_sum_q: number,
     *     children_low_sum_pct: number, children_high_sum_pct: number,
     *     violators: Array<{edge_id:number, child_id:number,
     *         child_name:string, reason:string}>
     * }>}
     */
    api.getFeasibilityReport = async function(parentId) {
        if (parentId === undefined || parentId === null) {
            throw new Error('parentId is required');
        }
        return api._callBridge('getFeasibilityReport', parentId);
    };

    /**
     * Whole-tree feasibility reports keyed by parent_id.
     *
     * Fuels warning-dot rendering on the tree editor. The bridge
     * returns one report per parent (every node with at least one
     * outgoing edge); iterate ``response.parents`` and stamp a
     * warning dot wherever ``status !== 'ok'``.
     *
     * The ``parents`` object's keys are stringified parent IDs
     * (JSON object keys must be strings); coerce back to int when
     * comparing against ``node.id``.
     *
     * @param {number} examContextId
     * @returns {Promise<{
     *     parents: Object<string, {
     *         status: 'ok'|'under'|'over'|'infeasible',
     *         parent_low_q: number|null, parent_high_q: number|null,
     *         children_low_sum_q: number, children_high_sum_q: number,
     *         children_low_sum_pct: number, children_high_sum_pct: number,
     *         violators: Array<object>
     *     }>
     * }>}
     */
    api.getAllFeasibilityReports = async function(examContextId) {
        if (examContextId === undefined || examContextId === null) {
            throw new Error('examContextId is required');
        }
        return api._callBridge('getAllFeasibilityReports', examContextId);
    };

})(window._wimiApi);
