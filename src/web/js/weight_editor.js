/**
 * WIMI Weight Editor Module - Enhanced with Hybrid Weight System
 * Supports official weight ranges, relative weights, and effective weight calculation
 * 
 * Features:
 * - Official weight range display (e.g., 20%-25%)
 * - Relative weight editing for child subjects
 * - Effective weight calculation with confidence indicators
 * - Lock status display and enforcement
 * - Real-time sibling rebalancing preview
 * - Weight history display
 */

// =========================================================================
// Weight Editor State
// =========================================================================

const WeightEditorState = {
    nodeId: null,
    node: null,
    // Stage 3 (Hierarchical Weight Allocation): id of the edge whose
    // weight the panel is currently editing. Populated in init() by
    // looking up the node's primary edge via api.getEdgesForChild.
    // Stage 6 routes writes through this id via api.setExplicitWeight.
    currentEdgeId: null,
    originalWeight: null,
    currentWeight: null,
    siblings: [],
    examConfig: null,
    weightConfig: null,
    precision: 1,
    algorithm: 'proportional',
    isPreviewMode: false,
    history: [],
    historyExpanded: false,
    // Hybrid weight fields
    isHybridMode: false,
    weightType: 'absolute', // 'absolute', 'relative', or 'effective'
    isLocked: false,
    weightSource: 'user_defined',
    confidence: 'low',
    effectiveWeight: null,
    effectiveLow: null,
    effectiveHigh: null,
    // Weight range fields
    hasWeightRange: false,
    originalWeightLow: null,
    originalWeightHigh: null,
    currentWeightLow: null,
    currentWeightHigh: null,
    // ----------------------------------------------------------------
    // Stage 6 (Hierarchical Weight Allocation) — dual-unit input,
    // parent-context disclosure, and per-edge anchor UX.
    // ----------------------------------------------------------------
    /** Currently selected unit in the segmented control: '%' or 'Q'. */
    currentUnit: '%',
    /**
     * Cached parent ``q_typical`` for the current edge's parent. Used
     * by ``convertWeightUnit`` so the segment toggle and the magic
     * suffix parser can convert the user-typed value bidirectionally.
     * ``null`` when ``length_kind='unknown'`` or the lookup failed —
     * Q-mode is unavailable in that case.
     */
    parentQTypical: null,
    /** Display name of the parent edge under which we're editing. */
    parentName: '',
    /** Exam length kind: 'fixed' | 'range' | 'unknown'. */
    examLengthKind: 'unknown',
    /**
     * Stage 8 — True iff the current exam context is adaptive (CAT,
     * ``length_kind === 'range'``). When set, Q-mode formatting uses
     * floats and appends the ``(planning estimate)`` qualifier so the
     * user sees that NCLEX-style exams have no fixed precision.
     * Populated in initWeightEditor() from the same getExamLength
     * lookup that fills ``examLengthKind`` (Stage 6 wired the fetch).
     */
    examIsAdaptive: false,
    /**
     * All parent edges of the current child (from getEdgesForChild).
     * When the array length > 1 we render the "switch parent" link so
     * the user can edit the same node's weight under another parent.
     */
    childParentEdges: []
};

// =========================================================================
// Stage 6 (Hierarchical Weight Allocation) — Pure helpers
// =========================================================================

/**
 * Parse a raw input string under the dual-unit input contract (design §3.6).
 *
 * Magic-suffix mode (preferred):
 *   ``"10%"`` → ``{value: 10, unit: '%'}``
 *   ``"28q"`` → ``{value: 28, unit: 'Q'}``  (case-insensitive)
 *
 * Bare-number mode falls back to the segmented control state:
 *   ``"45"`` with ``currentUnit='%'`` → ``{value: 45, unit: '%'}``
 *   ``"45"`` with ``currentUnit='Q'`` → ``{value: 45, unit: 'Q'}``
 *
 * Magnitude inference is rejected per design §3.6 — there's no "is 45
 * a percent or a Q?" guess based on size; the only cues are the
 * explicit suffix or the segment state.
 *
 * @param {string} rawInput - The raw text from the input field.
 * @param {string} currentUnit - '%' or 'Q'; the segmented-control state.
 * @returns {{value:number, unit:('%'|'Q')}|null} Parsed pair, or null
 *     when input is empty/non-numeric.
 */
function parseWeightInput(rawInput, currentUnit) {
    const trimmed = String(rawInput == null ? '' : rawInput).trim();
    if (!trimmed) return null;
    if (trimmed.endsWith('%')) {
        const n = parseFloat(trimmed.slice(0, -1));
        return Number.isFinite(n) ? { value: n, unit: '%' } : null;
    }
    const lower = trimmed.toLowerCase();
    // Accept both "5 q" and the display form "5 q's" — the chip text uses
    // the latter, and users sometimes type back what they see.
    const qSuffix = lower.endsWith("q's") ? 3 : (lower.endsWith('q') ? 1 : 0);
    if (qSuffix) {
        const n = parseFloat(trimmed.slice(0, -qSuffix));
        return Number.isFinite(n) ? { value: n, unit: 'Q' } : null;
    }
    const n = parseFloat(trimmed);
    if (!Number.isFinite(n)) return null;
    const unit = currentUnit === 'Q' ? 'Q' : '%';
    return { value: n, unit };
}

/**
 * Convert a weight value between '%' and 'Q' units (design §3.6).
 *
 * ``Q→%``: ``value / parent_q_typical * 100``
 * ``%→Q``: ``value / 100 * parent_q_typical``
 *
 * @param {number} value
 * @param {string} from - '%' or 'Q'
 * @param {string} to - '%' or 'Q'
 * @param {number|null} parentQTypical - Parent's typical question budget;
 *     when null/0 the conversion is undefined and we return null.
 * @returns {number|null} Converted value, or null when impossible.
 */
function convertWeightUnit(value, from, to, parentQTypical) {
    if (from === to) return value;
    if (!parentQTypical || parentQTypical <= 0) return null;
    if (from === 'Q' && to === '%') return (value / parentQTypical) * 100;
    if (from === '%' && to === 'Q') return (value / 100) * parentQTypical;
    return null;
}

// =========================================================================
// Initialization
// =========================================================================

/**
 * Initialize the weight editor for a selected node
 * @param {Object} node - The selected node
 * @param {Object} examConfig - The exam context configuration
 */
async function initWeightEditor(node, examConfig) {
    if (!node) return;

    WeightEditorState.nodeId = node.id;
    WeightEditorState.node = node;
    WeightEditorState.examConfig = examConfig;
    WeightEditorState.precision = examConfig?.precision ?? 1;
    WeightEditorState.algorithm = examConfig?.balancing_algorithm || 'proportional';
    WeightEditorState.isPreviewMode = false;

    // Check for weight range (exam_weight_low !== exam_weight_high)
    const hasRange = node.exam_weight_low !== null &&
                     node.exam_weight_high !== null &&
                     node.exam_weight_low !== node.exam_weight_high;
    WeightEditorState.hasWeightRange = hasRange;

    // Initialize weight range fields
    if (hasRange) {
        WeightEditorState.originalWeightLow = node.exam_weight_low;
        WeightEditorState.originalWeightHigh = node.exam_weight_high;
        WeightEditorState.currentWeightLow = node.exam_weight_low;
        WeightEditorState.currentWeightHigh = node.exam_weight_high;
    } else {
        WeightEditorState.originalWeightLow = null;
        WeightEditorState.originalWeightHigh = null;
        WeightEditorState.currentWeightLow = null;
        WeightEditorState.currentWeightHigh = null;
    }

    // Determine weight type based on node properties
    if (node.relative_weight !== null && node.relative_weight !== undefined) {
        WeightEditorState.weightType = 'relative';
        WeightEditorState.originalWeight = node.relative_weight;
        WeightEditorState.currentWeight = node.relative_weight;
    } else if (node.exam_weight_low !== null && node.exam_weight_low !== undefined) {
        WeightEditorState.weightType = 'absolute';
        WeightEditorState.originalWeight = node.weight || node.exam_weight_low || 0;
        WeightEditorState.currentWeight = WeightEditorState.originalWeight;
    } else {
        WeightEditorState.weightType = 'absolute';
        WeightEditorState.originalWeight = 0;
        WeightEditorState.currentWeight = 0;
    }

    // Set hybrid weight properties
    WeightEditorState.isLocked = node.weight_locked || false;
    WeightEditorState.weightSource = node.weight_source || 'user_defined';
    WeightEditorState.confidence = getConfidenceLevel(node.weight_source);
    WeightEditorState.isHybridMode = node.weight_source === 'official' ||
                                      node.weight_source === 'derived' ||
                                      node.relative_weight !== null;

    // Get siblings
    WeightEditorState.siblings = getSiblings(node);

    // Stage 3 (Hierarchical Weight Allocation): resolve the primary
    // edge for this node so Stage 6's writes can target a specific
    // (parent, child) edge instead of being node-keyed. Defensive
    // try/catch — Stage 5's read-side API may be partially landed in
    // some branches, and we never want the weight panel to fail to
    // open just because the edge lookup is unavailable.
    WeightEditorState.currentEdgeId = null;
    WeightEditorState.childParentEdges = [];
    WeightEditorState.parentName = '';
    try {
        const edges = await api.getEdgesForChild(node.id);
        if (Array.isArray(edges) && edges.length > 0) {
            WeightEditorState.childParentEdges = edges;
            const primaryEdge = edges.find(e => e.is_primary);
            if (primaryEdge) {
                WeightEditorState.currentEdgeId = primaryEdge.edge_id;
                // Stage 6 — populate the parent-context header. The
                // primary edge's parent_name is the canonical "under"
                // anchor for the disclosure copy.
                WeightEditorState.parentName = primaryEdge.parent_name || '';
            } else {
                console.warn(
                    `WeightEditor: node ${node.id} has ${edges.length} ` +
                    `parent edge(s) but none are marked is_primary. ` +
                    `currentEdgeId left null. Post-m005 every child should ` +
                    `have at most one primary edge — investigate.`
                );
            }
        }
    } catch (error) {
        console.warn('WeightEditor: could not resolve primary edge for node', node.id, error);
    }

    // Stage 6 — fetch the exam length triple so we know whether the Q
    // segment in the dual-unit toggle should be visible. Defensive try/
    // catch matches the rest of init(): the weight panel must never
    // fail to open just because length lookup is unavailable.
    WeightEditorState.examLengthKind = 'unknown';
    WeightEditorState.examIsAdaptive = false;
    WeightEditorState.parentQTypical = null;
    try {
        if (TreeState && TreeState.examContextId) {
            const lengthInfo = await api.getExamLength(TreeState.examContextId);
            if (lengthInfo && lengthInfo.kind) {
                WeightEditorState.examLengthKind = lengthInfo.kind;
                // Stage 8 — CAT signal. ``length_kind='range'`` ⇒
                // adaptive. The chip and sibling preview tooltips
                // switch to ``~26.4 q (planning estimate)``.
                WeightEditorState.examIsAdaptive = lengthInfo.kind === 'range';
            }
        }
    } catch (error) {
        // Pre-Stage-4 databases (no length triple migration) and bridges
        // without the slot land here — leave examLengthKind='unknown' so
        // the segment hides gracefully.
        console.debug('WeightEditor: could not load exam length:', error?.message || error);
    }

    // Stage 6 — when length_kind is known AND we have a parent edge,
    // fetch the parent's question allocation so Q ↔ % conversion works
    // and we can show the integer Q in the input. Skipped when no
    // parent (root node) or length unknown.
    if (
        WeightEditorState.examLengthKind !== 'unknown'
        && WeightEditorState.currentEdgeId
        && node._parent
        && node._parent.id !== undefined
    ) {
        try {
            const allocation = await api.getQuestionAllocation(node._parent.id);
            if (allocation && allocation.total_q != null) {
                WeightEditorState.parentQTypical = allocation.total_q;
            }
        } catch (error) {
            console.debug('WeightEditor: getQuestionAllocation failed:', error?.message || error);
        }
    }

    // Load weight config for the exam
    try {
        WeightEditorState.weightConfig = await api.getWeightConfig(TreeState.examContextId);
    } catch (error) {
        console.warn('Could not load weight config:', error);
        WeightEditorState.weightConfig = null;
    }

    // Load weight history
    await loadWeightHistory(node.id);

    // Render the enhanced editor
    renderWeightEditor(node);

    // Stage 7 — populate the empty feasibility-badge slot Stage 6
    // reserved. Fire-and-forget so it doesn't block the modal opening
    // if the slot is slow or the bridge isn't wired yet. Reads the
    // parent_id from the rendered node context — root nodes (no
    // _parent) have no parent feasibility to report and the helper
    // short-circuits.
    _renderFeasibilityBadge(node).catch(error => {
        console.debug(
            'WeightEditor: feasibility-badge render skipped:',
            error?.message || error
        );
    });
}

/**
 * Stage 7 — populate ``#weight-feasibility-badge`` with status copy.
 *
 * The badge slot is created by ``renderWeightEditor`` (Stage 6) as a
 * hidden ``<div>``. This helper:
 *
 *   1. Resolves the parent_id from the node's _parent context.
 *   2. Calls ``api.getFeasibilityReport(parent_id)``.
 *   3. Hides the badge on ``status='ok'`` or any error (defensive).
 *   4. Renders status-specific copy + a CSS class for color when the
 *      status is ``'under'``/``'over'``/``'infeasible'``.
 *
 * Per design §3.5 (Save-then-warn): the badge is purely informational
 * and never blocks save. Per Stage 7 spec: status is rendered with the
 * ``status-under`` / ``status-over`` / ``status-infeasible`` CSS class
 * (all yellow per the plan — red is reserved for save failures).
 *
 * @param {Object} node - The node currently in the weight editor.
 */
async function _renderFeasibilityBadge(node) {
    const badge = document.getElementById('weight-feasibility-badge');
    if (!badge) return;

    // Default-hidden until we know better. The ``hidden`` attribute
    // pairs with the ``[hidden] { display: none; }`` rule in weight.css
    // so this is the canonical "off" state.
    badge.setAttribute('hidden', '');
    badge.classList.remove('status-ok', 'status-under', 'status-over', 'status-infeasible');
    badge.textContent = '';
    badge.removeAttribute('title');

    if (!node || !node._parent || node._parent.id === undefined) {
        // Root nodes have no parent context to validate. Leave hidden.
        return;
    }

    let report;
    try {
        report = await api.getFeasibilityReport(node._parent.id);
    } catch (error) {
        // Pre-Stage-7 bridges land here (slot not wired). Leave
        // hidden so the UI degrades gracefully.
        console.debug(
            'WeightEditor: getFeasibilityReport unavailable:',
            error?.message || error
        );
        return;
    }

    if (!report || !report.status || report.status === 'ok') {
        return;
    }

    // Compose status-specific copy per Stage 7 spec.
    const status = report.status;
    let copy = '';
    const childPct = (report.children_low_sum_pct ?? 0).toFixed(1);
    const childHighPct = (report.children_high_sum_pct ?? 0).toFixed(1);

    if (status === 'under') {
        // Children sum (high) is < parent low. Use children_high_sum_pct
        // for the "sum" display because that's the optimistic side; the
        // remaining gap is the distance to parent's floor.
        const remaining = Math.max(
            0,
            (report.parent_low_q ?? 0) - (report.children_high_sum_q ?? 0)
        );
        copy = `Children sum to ${childHighPct}% — ${remaining} q's remaining.`;
    } else if (status === 'over') {
        // Children sum (low) exceeds parent high.
        const over = Math.max(
            0,
            (report.children_low_sum_q ?? 0) - (report.parent_high_q ?? 0)
        );
        copy = `Children sum to ${childPct}% — ${over} q's over.`;
    } else if (status === 'infeasible') {
        const childLowQ = report.children_low_sum_q ?? 0;
        const parentHighQ = report.parent_high_q ?? 0;
        copy = `Can't fit child minimums (≥${childLowQ} q's) into parent maximum (${parentHighQ} q's).`;
    } else {
        // Unknown future status — render the raw status name so we
        // notice the gap rather than silently hiding.
        copy = `Feasibility: ${status}`;
    }

    badge.textContent = copy;
    badge.setAttribute('title', copy);
    badge.classList.add(`status-${status}`);
    badge.removeAttribute('hidden');
}

/**
 * Get confidence level from weight source
 * @param {string} source - Weight source type
 * @returns {string} Confidence level: 'high', 'medium', or 'low'
 */
function getConfidenceLevel(source) {
    switch (source) {
        case 'official': return 'high';
        case 'derived': return 'medium';
        case 'user_estimate':
        case 'user_defined':
        default: return 'low';
    }
}

/**
 * Get siblings of a node (nodes with the same parent)
 * For multi-dimensional exams, root nodes are filtered by dimension
 * @param {Object} node - The current node
 * @returns {Array} Array of sibling nodes including the current node
 */
function getSiblings(node) {
    let siblings;
    if (node._parent) {
        // Child nodes - siblings are children of the same parent
        siblings = node._parent.children || [];
    } else {
        // Root nodes
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            // For multi-dimensional exams, filter root nodes by dimension
            siblings = TreeState.rootNodes.filter(
                n => n.dimension_id === TreeState.currentDimensionId
            );
        } else {
            siblings = TreeState.rootNodes;
        }
    }

    return siblings.map(s => ({
        id: s.id,
        name: s.name,
        weight: s.relative_weight ?? s.exam_weight_low ?? s.weight ?? 0,
        isCurrent: s.id === node.id,
        isLocked: s.weight_locked || false,
        weightSource: s.weight_source || 'user_defined',
        // Stage 5 — surface q_typical so the sibling preview chart
        // tooltip can show ``XX.X% • ~N q``. Stamped onto the node by
        // ``enrichNodesWithQuestionCounts`` in tree_editor.js; absent
        // when the exam is ``length_kind='unknown'`` or the
        // length-triple migration hasn't run.
        qTypical: s.q_typical ?? null,
        // Stage 6 — surface per-edge ``is_anchor`` so the sibling
        // preview chart can render anchored siblings as filled bars
        // and auto-distributed siblings as striped bars (per design
        // §7.2). When the polyhierarchy enrichment hasn't stamped
        // is_anchor onto the rendered node we fall back to false.
        isAnchor: !!s.is_anchor
    }));
}

/**
 * Load weight history for a node
 * @param {number} nodeId - Node ID
 */
async function loadWeightHistory(nodeId) {
    try {
        WeightEditorState.history = await api.getWeightHistory(nodeId, 10);
    } catch (error) {
        console.warn('Could not load weight history:', error);
        WeightEditorState.history = [];
    }
}

// =========================================================================
// Rendering
// =========================================================================

/**
 * Render the complete weight editor UI with hybrid weight support
 * @param {Object} node - The selected node
 */
function renderWeightEditor(node) {
    const container = document.getElementById('weight-editor-container');
    if (!container) {
        renderBasicWeightEditor(node);
        return;
    }
    
    const precision = WeightEditorState.precision;
    const step = Math.pow(10, -precision);
    const weight = WeightEditorState.currentWeight;
    const originalWeight = WeightEditorState.originalWeight;
    const delta = weight - originalWeight;
    const isLocked = WeightEditorState.isLocked;
    const weightType = WeightEditorState.weightType;
    const confidence = WeightEditorState.confidence;
    const weightSource = WeightEditorState.weightSource;
    
    // Calculate effective weight if this is a relative weight
    let effectiveDisplay = '';
    if (weightType === 'relative' && node._parent) {
        const parentMidpoint = (node._parent.exam_weight_low + (node._parent.exam_weight_high || node._parent.exam_weight_low)) / 2;
        const effective = parentMidpoint * (weight / 100);
        effectiveDisplay = `
            <div class="effective-weight-display">
                <span class="effective-label">Effective Weight:</span>
                <span class="effective-value">${effective.toFixed(2)}%</span>
                <span class="effective-calc">(${parentMidpoint.toFixed(1)}% × ${weight.toFixed(precision)}%)</span>
            </div>
        `;
    }
    
    // Weight range display - now editable for ranges
    let rangeDisplay = '';
    const hasRange = WeightEditorState.hasWeightRange;
    if (hasRange) {
        rangeDisplay = `
            <div class="weight-range-indicator">
                <span class="range-icon">↔</span>
                <span class="range-label">Weight Range Mode</span>
                ${node.exam_source ? `<span class="range-source" title="Source: ${escapeHtml(node.exam_source)}">📋</span>` : ''}
            </div>
        `;
    }
    
    // Stage 6 — Parent-context disclosure header. The user must always
    // know which (parent → child) edge they're editing because
    // polyhierarchy lets the same node carry different weight under
    // different parents (per design §3.7). Only rendered when we have
    // an edge and a parent; root nodes / orphans show nothing.
    let parentContextHeader = '';
    if (WeightEditorState.currentEdgeId && WeightEditorState.parentName) {
        parentContextHeader = `
            <div class="weight-modal-context-header" data-testid="weight-modal-context-header">
                <span class="weight-modal-context-label">Weight for</span>
                <strong id="weight-modal-child-name" data-testid="weight-modal-child-name">${escapeHtml(node.name)}</strong>
                <span class="weight-modal-context-label">under</span>
                <strong id="weight-modal-parent-name" data-testid="weight-modal-parent-name">${escapeHtml(WeightEditorState.parentName)}</strong>
            </div>
        `;
    }

    // Stage 6 — Switch-parent affordance for multi-parent leaves. Only
    // rendered when the child has more than one parent edge. Each
    // alternate parent is a clickable link that swaps the modal context
    // (per design §3.7 "switch parent" UX).
    let switchParentBlock = '';
    const otherEdges = (WeightEditorState.childParentEdges || []).filter(
        e => e.edge_id !== WeightEditorState.currentEdgeId
    );
    if (otherEdges.length > 0) {
        const otherParentLinks = otherEdges.map(e => `
            <a href="#"
               class="weight-switch-parent-link"
               data-edge-id="${e.edge_id}"
               data-parent-id="${e.parent_id}"
               data-testid="weight-switch-parent-link-${e.edge_id}"
               onclick="event.preventDefault(); switchWeightEditorParent(${e.edge_id}, ${e.parent_id});">
                ${escapeHtml(e.parent_name || ('Parent ' + e.parent_id))}
            </a>
        `).join(', ');
        switchParentBlock = `
            <div class="weight-switch-parent" id="weight-switch-parent" data-testid="weight-switch-parent">
                <span>Also appears under:</span>
                <span id="weight-other-parents-list" data-testid="weight-other-parents-list">${otherParentLinks}</span>
            </div>
        `;
    }

    // Stage 6 — Dual-unit segmented control (% | Q). Only available
    // when the exam declares a length_typical (length_kind != 'unknown')
    // AND we are editing a per-edge relative weight (not a system-level
    // range). Hidden otherwise per design §3.6.
    const showUnitToggle = (
        WeightEditorState.examLengthKind !== 'unknown'
        && WeightEditorState.currentEdgeId
        && weightType === 'relative'
        && !hasRange
    );
    const currentUnit = WeightEditorState.currentUnit || '%';
    const unitToggleMarkup = `
        <div class="weight-unit-toggle"
             id="weight-unit-toggle"
             data-testid="weight-unit-toggle"
             ${showUnitToggle ? '' : 'hidden'}>
            <button type="button"
                    data-unit="%"
                    class="weight-unit-btn ${currentUnit === '%' ? 'active' : ''}"
                    data-testid="weight-unit-percent"
                    onclick="setWeightEditorUnit('%')">%</button>
            <button type="button"
                    data-unit="Q"
                    class="weight-unit-btn ${currentUnit === 'Q' ? 'active' : ''}"
                    data-testid="weight-unit-questions"
                    onclick="setWeightEditorUnit('Q')">Q</button>
        </div>
    `;

    // Stage 6 — Anchor checkbox. Defaults checked when the user types a
    // value (the canonical setExplicitWeight always anchors). Visible
    // only for relative weights that have a per-edge id.
    const showAnchorToggle = (
        WeightEditorState.currentEdgeId
        && weightType === 'relative'
        && !hasRange
        && !isLocked
    );
    const anchorChecked = (
        WeightEditorState.childParentEdges
            .find(e => e.edge_id === WeightEditorState.currentEdgeId)
            ?.is_anchor !== false
    );
    const anchorToggleMarkup = showAnchorToggle ? `
        <label class="weight-anchor-toggle" data-testid="weight-anchor-toggle">
            <input type="checkbox"
                   id="weight-anchor-checkbox"
                   data-testid="weight-anchor-checkbox"
                   ${anchorChecked ? 'checked' : ''}>
            <span>Anchor this value (don't auto-adjust on rebalance)</span>
        </label>
    ` : '';

    // Stage 6 — Empty feasibility-badge slot. Stage 7 will fill the
    // copy + status; for now we just reserve the DOM hook.
    const feasibilityBadgeMarkup = `
        <div class="weight-feasibility-badge"
             id="weight-feasibility-badge"
             data-testid="weight-feasibility-badge"
             hidden></div>
    `;

    container.innerHTML = `
        <div class="weight-editor-enhanced ${isLocked ? 'locked' : ''}" data-testid="tree-weight-editor-enhanced">
            ${parentContextHeader}
            ${switchParentBlock}

            <!-- Weight Status Header -->
            <div class="weight-status-header">
                <div class="weight-badges">
                    <span class="weight-type-badge ${weightType}">${getWeightTypeLabel(weightType)}</span>
                    <span class="weight-confidence-badge ${confidence}" title="Confidence: ${confidence}">
                        ${getConfidenceIcon(confidence)} ${capitalizeFirst(confidence)}
                    </span>
                    ${isLocked ? '<span class="weight-lock-badge">🔒 Locked</span>' : ''}
                </div>
                <span class="weight-source-label">${getSourceLabel(weightSource)}</span>
            </div>

            ${feasibilityBadgeMarkup}
            ${rangeDisplay}

            <!-- Current Weight Display -->
            <div class="weight-current-display">
                <div class="weight-current-header">
                    <label>${weightType === 'relative' ? 'Relative Weight' : (hasRange ? 'Weight Range' : 'Current Weight')}</label>
                    <span class="weight-precision-badge">${precision} decimal${precision !== 1 ? 's' : ''}</span>
                </div>

                ${hasRange ? `
                    <!-- Weight Range Display (side-by-side Low/High) -->
                    <div class="weight-range-main-display">
                        <span class="weight-range-values ${WeightEditorState.isPreviewMode ? 'changed' : ''}" id="weight-display" data-testid="tree-weight-display-enhanced">
                            ${WeightEditorState.currentWeightLow.toFixed(precision)}% – ${WeightEditorState.currentWeightHigh.toFixed(precision)}%
                        </span>
                    </div>

                    ${!isLocked ? `
                        <div class="weight-range-inputs">
                            <div class="weight-range-input-group">
                                <label for="weight-low-input">Low</label>
                                <div class="weight-input-wrapper">
                                    <input type="number"
                                           class="weight-input-field weight-low-field"
                                           id="weight-low-input"
                                           data-testid="tree-weight-low"
                                           min="0"
                                           max="100"
                                           step="${step}"
                                           value="${WeightEditorState.currentWeightLow.toFixed(precision)}">
                                    <span class="weight-input-suffix">%</span>
                                </div>
                            </div>
                            <span class="weight-range-separator">–</span>
                            <div class="weight-range-input-group">
                                <label for="weight-high-input">High</label>
                                <div class="weight-input-wrapper">
                                    <input type="number"
                                           class="weight-input-field weight-high-field"
                                           id="weight-high-input"
                                           data-testid="tree-weight-high"
                                           min="0"
                                           max="100"
                                           step="${step}"
                                           value="${WeightEditorState.currentWeightHigh.toFixed(precision)}">
                                    <span class="weight-input-suffix">%</span>
                                </div>
                            </div>
                        </div>
                        <p class="weight-range-help">Adjust the low and high bounds of this weight range</p>
                    ` : `
                        <div class="weight-locked-message">
                            <span class="icon">🔒</span>
                            <span>This weight range is locked and cannot be edited.</span>
                            <span class="locked-reason">Source: ${getSourceLabel(weightSource)}</span>
                        </div>
                    `}
                ` : `
                    <!-- Single Weight Display (original behavior) -->
                    <div class="weight-main-display">
                        <span class="weight-value-large ${delta !== 0 ? 'changed' : ''}" id="weight-display" data-testid="tree-weight-display-enhanced">
                            ${weight.toFixed(precision)}%
                        </span>
                        <span class="weight-delta ${delta > 0 ? 'positive' : delta < 0 ? 'negative' : 'neutral'}" id="weight-delta" data-testid="tree-weight-delta-enhanced">
                            ${delta > 0 ? '+' : ''}${delta.toFixed(precision)}%
                        </span>
                    </div>

                    ${effectiveDisplay}

                    ${!isLocked ? `
                        <div class="weight-slider-container">
                            <input type="range"
                                   class="weight-slider-enhanced ${WeightEditorState.isPreviewMode ? 'preview-mode' : ''}"
                                   id="weight-slider-enhanced"
                                   data-testid="tree-weight-slider-enhanced"
                                   min="0"
                                   max="100"
                                   step="${step}"
                                   value="${weight}">
                            <div class="weight-slider-markers">
                                <span class="weight-slider-marker">0%</span>
                                <span class="weight-slider-marker">25%</span>
                                <span class="weight-slider-marker">50%</span>
                                <span class="weight-slider-marker">75%</span>
                                <span class="weight-slider-marker">100%</span>
                            </div>
                        </div>

                        <div class="weight-direct-input">
                            <label>Or enter directly:</label>
                            <input type="text"
                                   class="weight-input-field"
                                   id="weight-input-enhanced"
                                   data-testid="tree-weight-input-enhanced"
                                   inputmode="decimal"
                                   value="${weight.toFixed(precision)}">
                            ${unitToggleMarkup}
                        </div>
                        ${anchorToggleMarkup}
                    ` : `
                        <div class="weight-locked-message">
                            <span class="icon">🔒</span>
                            <span>This weight is locked and cannot be edited.</span>
                            <span class="locked-reason">Source: ${getSourceLabel(weightSource)}</span>
                        </div>
                    `}
                `}
            </div>
            
            ${WeightEditorState.weightConfig ? `
                <!-- Weight Mode Info -->
                <div class="weight-mode-info">
                    <span class="icon">⚙️</span>
                    <span>Mode:</span>
                    <span class="weight-mode-name">${getWeightModeLabel(WeightEditorState.weightConfig.weight_mode)}</span>
                    ${WeightEditorState.weightConfig.source_name ? 
                        `<span class="weight-mode-source" title="${WeightEditorState.weightConfig.source_name}">📋 ${WeightEditorState.weightConfig.source_name}</span>` : ''}
                </div>
            ` : ''}
            
            <!-- Algorithm Info (only show if not locked) -->
            ${!isLocked ? `
                <div class="weight-algorithm-info">
                    <span class="icon">⚖️</span>
                    <span>Balancing:</span>
                    <span class="weight-algorithm-name">${capitalizeFirst(WeightEditorState.algorithm)}</span>
                    <span class="weight-algorithm-desc">${getAlgorithmDescription(WeightEditorState.algorithm)}</span>
                </div>
            ` : ''}
            
            <!-- Siblings Preview -->
            <div class="weight-siblings-section">
                <div class="weight-siblings-header">
                    <label>Sibling Weight Distribution</label>
                    ${WeightEditorState.isPreviewMode ? '<span class="weight-preview-badge">Preview Mode</span>' : ''}
                </div>

                <div class="siblings-chart-enhanced" id="siblings-chart-enhanced" data-testid="tree-siblings-chart-enhanced">
                    ${renderSiblingsChart()}
                </div>

                <div class="siblings-total-enhanced" id="siblings-total-enhanced" data-testid="tree-siblings-total-enhanced">
                    ${renderTotalValidation()}
                </div>
            </div>

            <!-- Weight History -->
            <div class="weight-history-section">
                <div class="weight-history-header">
                    <label>Recent Changes</label>
                    <button class="weight-history-toggle" data-testid="tree-weight-history-toggle" onclick="toggleWeightHistory()">
                        ${WeightEditorState.historyExpanded ? 'Hide' : 'Show'}
                    </button>
                </div>
                <div class="weight-history-list ${WeightEditorState.historyExpanded ? '' : 'collapsed'}" id="weight-history-list" data-testid="tree-weight-history">
                    ${renderWeightHistory()}
                </div>
            </div>

            <!-- Actions -->
            ${!isLocked ? `
                <div class="weight-actions-enhanced">
                    <button class="btn btn-secondary" id="btn-reset-weight-enhanced" data-testid="tree-reset-weight-enhanced" onclick="resetWeightEditor()">
                        Reset
                    </button>
                    <button class="btn btn-secondary btn-rebalance-siblings" id="btn-rebalance-siblings-enhanced" data-testid="weight-panel-rebalance-siblings" onclick="rebalanceSiblings()" title="Redistribute remaining weight across non-anchored, non-locked siblings" ${canRebalanceSiblings() ? '' : 'disabled'}>
                        Rebalance siblings
                    </button>
                    <button class="btn btn-apply" id="btn-apply-weight-enhanced" data-testid="tree-apply-weight-enhanced" onclick="applyWeightChange()" ${delta === 0 ? 'disabled' : ''}>
                        Apply Changes
                    </button>
                </div>
            ` : ''}
        </div>
    `;

    // Setup event listeners
    if (!isLocked) {
        setupWeightEditorListeners();
    }
}

/**
 * Determine whether the Rebalance Siblings button should be active.
 *
 * Stage 2 of WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md. The button is
 * meaningless when there is no adjustable sibling — i.e. every sibling
 * (other than the currently selected node) is either locked or
 * anchored.
 *
 * Notes on data sources:
 *   - ``WeightEditorState.siblings`` includes the current node itself.
 *     We exclude it via ``isCurrent``.
 *   - The ``is_anchor`` per-edge flag is not yet surfaced through
 *     ``getSiblings`` (that wiring lands in Stage 3). For now we
 *     conservatively use ``isLocked`` as the only exclusion reason; if
 *     a parent is fully locked the button will still disable correctly,
 *     and Stage 3 will tighten the gate to also honor anchored edges.
 *
 * @returns {boolean} ``true`` when at least one sibling is adjustable.
 */
function canRebalanceSiblings() {
    const sibs = WeightEditorState.siblings || [];
    return sibs.some(s => !s.isCurrent && !s.isLocked);
}

/**
 * Trigger an explicit sibling rebalance via the bridge.
 *
 * Stage 2 of WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md. Replaces the
 * implicit-rebalance side effect of ``updateRelativeWeight``: the user
 * must now opt in by clicking this button.
 *
 * The handler:
 *   1. Resolves the parent context (from the currently selected node).
 *   2. Calls ``api.rebalanceSiblings``.
 *   3. Surfaces a confirmation toast when any sibling shifted by more
 *      than 5 percentage points (so the user notices large changes
 *      without being alarmed by routine ±0.1% nudges).
 *   4. Reloads the hierarchy + reopens the current node to refresh
 *      both the tree chrome and the sibling preview chart.
 */
async function rebalanceSiblings() {
    const node = WeightEditorState.node;
    if (!node) return;

    // Resolve the parent context. The current node's _parent.id is the
    // canonical parent under which we rebalance siblings.
    const parentId = node._parent ? node._parent.id : null;
    if (parentId === null || parentId === undefined) {
        // Root nodes have no parent under which to rebalance.
        if (typeof Toast !== 'undefined') {
            Toast.info('No Parent', 'Root nodes have no parent to rebalance under.');
        }
        return;
    }

    const btn = document.getElementById('btn-rebalance-siblings-enhanced');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Rebalancing...';
    }

    try {
        const result = await api.rebalanceSiblings({
            parentId,
            reason: 'User clicked Rebalance siblings'
        });

        const affected = (result && result.affected_edges) || [];
        const skipped = (result && result.skipped) || [];

        if (affected.length === 0) {
            if (typeof Toast !== 'undefined') {
                Toast.info('Nothing to rebalance', 'All siblings are anchored or locked.');
            }
        } else {
            // Surface a warning when any sibling shifted by >5pp so the
            // user is aware of large reallocations (per Stage 2 plan).
            const maxShift = affected.reduce((m, e) => {
                const delta = Math.abs((e.new_weight || 0) - (e.old_weight || 0));
                return delta > m ? delta : m;
            }, 0);
            if (typeof Toast !== 'undefined') {
                if (maxShift > 5) {
                    Toast.warning(
                        'Large adjustment',
                        `Rebalanced ${affected.length} siblings (largest shift: ${maxShift.toFixed(1)}%)`
                    );
                } else {
                    Toast.success(
                        'Rebalanced',
                        `${affected.length} siblings adjusted${skipped.length ? `, ${skipped.length} skipped` : ''}`
                    );
                }
            }
        }

        // Bust the dimension cache so the subsequent loadHierarchy()
        // re-fetches instead of replaying stale chip data. Without this,
        // dimensioned exams (the common case) render the pre-rebalance
        // values until the user presses F5. Mirrors the cache-invalidation
        // pattern in the Apply Weight handler.
        if (
            typeof invalidateDimensionCache === 'function'
            && typeof TreeState !== 'undefined'
            && TreeState.usesDimensions
            && TreeState.currentDimensionId
        ) {
            invalidateDimensionCache(TreeState.currentDimensionId);
        }

        // Refresh the tree + reopen the current node.
        if (typeof loadHierarchy === 'function') {
            await loadHierarchy();
        }
        if (typeof TreeState !== 'undefined' && TreeState.selectedNodeId && typeof showNodeDetails === 'function') {
            showNodeDetails(TreeState.selectedNodeId);
        }
    } catch (error) {
        if (typeof Toast !== 'undefined') {
            Toast.error('Error', error.message || String(error));
        }
    } finally {
        const refreshedBtn = document.getElementById('btn-rebalance-siblings-enhanced');
        if (refreshedBtn) {
            refreshedBtn.disabled = !canRebalanceSiblings();
            refreshedBtn.textContent = 'Rebalance siblings';
        }
    }
}

/**
 * Render basic weight editor (fallback for existing details panel)
 * @param {Object} node - The selected node
 */
function renderBasicWeightEditor(node) {
    const weight = WeightEditorState.currentWeight;
    const precision = WeightEditorState.precision;
    const step = Math.pow(10, -precision);
    const isLocked = WeightEditorState.isLocked;
    
    // Update existing slider and input
    const slider = document.getElementById('weight-slider');
    const input = document.getElementById('weight-value');
    
    if (slider) {
        slider.min = 0;
        slider.max = 100;
        slider.step = step;
        slider.value = weight;
        slider.disabled = isLocked;
    }
    
    if (input) {
        input.step = step;
        input.value = weight.toFixed(precision);
        input.disabled = isLocked;
    }
    
    // Add lock indicator if needed
    const weightSection = document.querySelector('.detail-weight-section');
    if (weightSection) {
        const existingIndicator = weightSection.querySelector('.weight-lock-indicator');
        if (existingIndicator) existingIndicator.remove();
        
        if (isLocked) {
            const indicator = document.createElement('div');
            indicator.className = 'weight-lock-indicator';
            indicator.innerHTML = `<span>🔒</span> Locked (${getSourceLabel(WeightEditorState.weightSource)})`;
            weightSection.prepend(indicator);
        }
    }
    
    // Render enhanced siblings chart
    renderEnhancedSiblingsChart();
}

/**
 * Render the siblings comparison chart with lock indicators
 * @returns {string} HTML string
 */
function renderSiblingsChart() {
    const siblings = WeightEditorState.siblings;
    
    if (siblings.length <= 1) {
        return '<p class="text-muted text-sm">No siblings to compare</p>';
    }
    
    const previewWeights = calculatePreviewWeights();
    
    return siblings.map(s => {
        const currentWeight = s.weight;
        const previewWeight = previewWeights.get(s.id) ?? currentWeight;
        const diff = previewWeight - currentWeight;
        const showPreview = WeightEditorState.isPreviewMode && Math.abs(diff) > 0.01;

        let changeClass = 'unchanged';
        if (diff > 0.01) changeClass = 'increase';
        else if (diff < -0.01) changeClass = 'decrease';

        // Stage 5 — dual unit in the row tooltip when q_typical is
        // known. The user sees the sibling's name and (optionally)
        // its planning-baseline question count alongside the bar.
        // Stage 8 — adaptive (CAT) exams render the q value as a
        // float with a "(planning estimate)" qualifier so the user
        // knows the CAT has no fixed precision.
        let rowTitle = s.name;
        if (s.qTypical !== null && s.qTypical !== undefined) {
            const qLabel = WeightEditorState.examIsAdaptive
                ? `~${Number(s.qTypical).toFixed(1)} q's (planning estimate)`
                : (Number.isInteger(s.qTypical)
                    ? `~${s.qTypical} q's`
                    : `~${s.qTypical.toFixed(1)} q's`);
            rowTitle = `${s.name} — ${currentWeight.toFixed(WeightEditorState.precision)}% • ${qLabel}`;
        }

        // Stage 6 — per-design §7.2, anchored siblings render as a
        // solid filled bar; auto-distributed (non-anchored) render as
        // a striped bar so the user can see at a glance which values
        // are user-locked vs system-computed.
        const barFillClass = s.isAnchor ? 'sibling-bar-anchored' : 'sibling-bar-auto';
        const anchorPin = s.isAnchor
            ? `<span class="weight-anchor-pin filled"
                     data-testid="sibling-anchor-pin-${s.id}"
                     title="Anchored — won't auto-adjust on rebalance">⚓</span>`
            : '';

        return `
            <div class="sibling-row ${s.isCurrent ? 'current' : ''} ${showPreview && !s.isCurrent ? 'will-change' : ''} ${s.isLocked ? 'locked' : ''} ${s.isAnchor ? 'anchored' : 'auto'}">
                <span class="sibling-row-name" title="${escapeHtml(rowTitle)}">
                    ${s.isLocked ? '🔒 ' : ''}${anchorPin}${escapeHtml(s.name)}
                </span>
                <div class="sibling-bar-wrapper" title="${escapeHtml(rowTitle)}">
                    <div class="sibling-bar-current ${barFillClass}" style="width: ${currentWeight}%"></div>
                    ${showPreview ? `<div class="sibling-bar-preview" style="width: ${previewWeight}%"></div>` : ''}
                </div>
                <span class="sibling-current-value">${currentWeight.toFixed(WeightEditorState.precision)}%</span>
                <span class="sibling-preview-value ${changeClass}">
                    ${showPreview ? (diff > 0 ? '+' : '') + diff.toFixed(WeightEditorState.precision) + '%' :
                      (s.isLocked ? '🔒' : '—')}
                </span>
            </div>
        `;
    }).join('');
}

/**
 * Render enhanced siblings chart (update in place)
 */
function renderEnhancedSiblingsChart() {
    const chartContainer = document.getElementById('siblings-chart-enhanced');
    if (chartContainer) {
        chartContainer.innerHTML = renderSiblingsChart();
    }
    
    // Also update the basic siblings chart if it exists
    const basicChart = document.getElementById('siblings-chart');
    if (basicChart) {
        basicChart.innerHTML = renderBasicSiblingsChart();
    }
    
    // Update total validation
    const totalContainer = document.getElementById('siblings-total-enhanced');
    if (totalContainer) {
        totalContainer.innerHTML = renderTotalValidation();
    }
}

/**
 * Render basic siblings chart for the existing panel
 * @returns {string} HTML string
 */
function renderBasicSiblingsChart() {
    const siblings = WeightEditorState.siblings;
    
    if (siblings.length <= 1) {
        return '<p class="text-muted text-sm">No siblings</p>';
    }
    
    const previewWeights = calculatePreviewWeights();
    
    return siblings.map(s => {
        const currentWeight = s.weight;
        const previewWeight = previewWeights.get(s.id) ?? currentWeight;
        const showPreview = WeightEditorState.isPreviewMode && s.id !== WeightEditorState.nodeId;
        
        return `
            <div class="sibling-bar ${s.isCurrent ? 'current' : ''} ${showPreview ? 'preview' : ''} ${s.isLocked ? 'locked' : ''}">
                <span class="sibling-name" title="${escapeHtml(s.name)}">
                    ${s.isLocked ? '🔒 ' : ''}${escapeHtml(s.name)}
                </span>
                <div class="sibling-bar-container">
                    <div class="sibling-bar-fill" style="width: ${showPreview ? previewWeight : currentWeight}%"></div>
                </div>
                <span class="sibling-value">${(showPreview ? previewWeight : currentWeight).toFixed(WeightEditorState.precision)}%</span>
            </div>
        `;
    }).join('');
}

/**
 * Render the total validation display
 * @returns {string} HTML string
 */
function renderTotalValidation() {
    const siblings = WeightEditorState.siblings;
    const currentTotal = siblings.reduce((sum, s) => sum + s.weight, 0);
    const previewWeights = calculatePreviewWeights();
    let previewTotal = 0;
    previewWeights.forEach(w => previewTotal += w);
    
    const precision = WeightEditorState.precision;
    const tolerance = Math.pow(10, -precision) * 5;
    
    const isCurrentValid = Math.abs(currentTotal - 100) < tolerance;
    const isPreviewValid = Math.abs(previewTotal - 100) < tolerance;
    
    let previewClass = 'valid';
    let validationMessage = '';
    let validationClass = 'success';
    
    if (!isPreviewValid) {
        if (previewTotal > 100) {
            previewClass = 'invalid';
            validationClass = 'error';
            validationMessage = `⚠️ Total exceeds 100% by ${(previewTotal - 100).toFixed(precision)}%`;
        } else {
            previewClass = 'warning';
            validationClass = 'warning';
            validationMessage = `⚠️ Total is ${(100 - previewTotal).toFixed(precision)}% below 100%`;
        }
    } else if (WeightEditorState.isPreviewMode) {
        validationMessage = '✓ Weights will sum to 100%';
    }
    
    // Count locked siblings
    const lockedCount = siblings.filter(s => s.isLocked && !s.isCurrent).length;
    
    return `
        <div class="siblings-total-label">Total Weight</div>
        <div class="siblings-total-values">
            <span class="total-current">${currentTotal.toFixed(precision)}%</span>
            ${WeightEditorState.isPreviewMode ? `
                <span class="total-arrow">→</span>
                <span class="total-preview ${previewClass}">${previewTotal.toFixed(precision)}%</span>
            ` : ''}
        </div>
        ${lockedCount > 0 ? `
            <div class="locked-siblings-note">
                <span class="icon">🔒</span>
                ${lockedCount} sibling${lockedCount > 1 ? 's' : ''} locked (won't be adjusted)
            </div>
        ` : ''}
        ${validationMessage ? `
            <div class="validation-message ${validationClass}">
                ${validationMessage}
            </div>
        ` : ''}
    `;
}

/**
 * Render weight history list
 * @returns {string} HTML string
 */
function renderWeightHistory() {
    const history = WeightEditorState.history;
    
    if (!history || history.length === 0) {
        return '<div class="weight-history-empty">No weight changes recorded yet</div>';
    }
    
    const precision = WeightEditorState.precision;
    
    return history.map(entry => {
        const date = new Date(entry.edited_date).toLocaleDateString();
        const oldValue = entry.previous_weight?.toFixed(precision) ?? '—';
        const newValue = entry.weight_value.toFixed(precision);
        const isAuto = entry.is_auto_adjustment;
        
        return `
            <div class="weight-history-item">
                <span class="history-date">${date}</span>
                <div class="history-change">
                    <span class="history-old-value">${oldValue}%</span>
                    <span class="history-arrow">→</span>
                    <span class="history-new-value">${newValue}%</span>
                </div>
                <span class="history-badge ${isAuto ? 'auto' : 'user'}">${isAuto ? 'Auto' : 'Manual'}</span>
                ${entry.edited_reason ? `<span class="history-reason" title="${escapeHtml(entry.edited_reason)}">${escapeHtml(entry.edited_reason)}</span>` : ''}
            </div>
        `;
    }).join('');
}

// =========================================================================
// Weight Calculation
// =========================================================================

/**
 * Calculate preview weights for all siblings based on the current adjustment
 * Respects locked weights during rebalancing
 * @returns {Map} Map of nodeId -> preview weight
 */
function calculatePreviewWeights() {
    const siblings = WeightEditorState.siblings;
    const nodeId = WeightEditorState.nodeId;
    const newWeight = WeightEditorState.currentWeight;
    const originalWeight = WeightEditorState.originalWeight;
    const algorithm = WeightEditorState.algorithm;
    
    const previewWeights = new Map();
    
    // Start with current weights
    siblings.forEach(s => {
        previewWeights.set(s.id, s.isCurrent ? newWeight : s.weight);
    });
    
    // If no change, return current weights
    const delta = newWeight - originalWeight;
    if (Math.abs(delta) < 0.001) {
        return previewWeights;
    }
    
    // Get unlocked siblings (not the current node, and not locked)
    const unlockedSiblings = siblings.filter(s => !s.isCurrent && !s.isLocked);
    
    if (unlockedSiblings.length === 0) {
        // No unlocked siblings to adjust
        return previewWeights;
    }
    
    // Calculate distribution based on algorithm
    const totalUnlockedWeight = unlockedSiblings.reduce((sum, s) => sum + s.weight, 0);
    const adjustmentNeeded = -delta;
    
    if (algorithm === 'proportional') {
        unlockedSiblings.forEach(s => {
            if (totalUnlockedWeight > 0) {
                const proportion = s.weight / totalUnlockedWeight;
                const adjustment = adjustmentNeeded * proportion;
                const newSiblingWeight = Math.max(0, s.weight + adjustment);
                previewWeights.set(s.id, newSiblingWeight);
            } else {
                const evenAdjustment = adjustmentNeeded / unlockedSiblings.length;
                previewWeights.set(s.id, Math.max(0, s.weight + evenAdjustment));
            }
        });
    } else if (algorithm === 'even') {
        const evenAdjustment = adjustmentNeeded / unlockedSiblings.length;
        unlockedSiblings.forEach(s => {
            const newSiblingWeight = Math.max(0, s.weight + evenAdjustment);
            previewWeights.set(s.id, newSiblingWeight);
        });
    }
    
    // Round to precision
    const precision = WeightEditorState.precision;
    previewWeights.forEach((value, key) => {
        previewWeights.set(key, Number(value.toFixed(precision)));
    });
    
    return previewWeights;
}

// =========================================================================
// Event Handlers
// =========================================================================

/**
 * Setup event listeners for the weight editor
 */
function setupWeightEditorListeners() {
    // Check if we're in range mode
    if (WeightEditorState.hasWeightRange) {
        setupRangeWeightListeners();
        return;
    }

    // Standard single weight listeners
    const slider = document.getElementById('weight-slider-enhanced');
    const input = document.getElementById('weight-input-enhanced');

    if (slider) {
        slider.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            onWeightChange(value);
        });
    }

    if (input) {
        // Stage 6 — the input is now a text field that supports magic
        // suffixes (10%, 28q). On every change we parse, convert to %
        // (the canonical internal unit), and update the live preview.
        input.addEventListener('input', (e) => {
            const parsed = parseWeightInput(e.target.value, WeightEditorState.currentUnit);
            if (!parsed) return;
            // If a magic suffix flipped the unit, reflect that in the
            // segmented control so visual state agrees with input.
            if (parsed.unit !== WeightEditorState.currentUnit) {
                _setUnitButtonsActive(parsed.unit);
                WeightEditorState.currentUnit = parsed.unit;
            }
            // Convert to % (the canonical internal unit) for preview.
            let asPercent = parsed.value;
            if (parsed.unit === 'Q') {
                const conv = convertWeightUnit(
                    parsed.value, 'Q', '%', WeightEditorState.parentQTypical
                );
                if (conv == null) return;
                asPercent = conv;
            }
            if (asPercent < 0 || asPercent > 100) return;
            onWeightChange(asPercent);
        });

        input.addEventListener('blur', (e) => {
            const parsed = parseWeightInput(e.target.value, WeightEditorState.currentUnit);
            const resetToCurrent = () => {
                e.target.value = _formatInputForCurrentUnit(WeightEditorState.currentWeight);
            };
            if (!parsed) {
                resetToCurrent();
                return;
            }
            if (parsed.unit !== WeightEditorState.currentUnit) {
                _setUnitButtonsActive(parsed.unit);
                WeightEditorState.currentUnit = parsed.unit;
            }
            let asPercent = parsed.value;
            if (parsed.unit === 'Q') {
                const conv = convertWeightUnit(
                    parsed.value, 'Q', '%', WeightEditorState.parentQTypical
                );
                if (conv == null) {
                    if (typeof Toast !== 'undefined') {
                        Toast.error('Cannot convert', 'No parent question budget — switch to % mode.');
                    }
                    resetToCurrent();
                    return;
                }
                asPercent = conv;
            }
            // Stage 6 fix: do NOT silently clamp — that hides input
            // errors (typing a Q value larger than the parent has) and
            // causes the surprising "20 → 100" reformat the user sees.
            // Show a clear error and revert the field instead.
            if (asPercent < 0 || asPercent > 100) {
                if (typeof Toast !== 'undefined') {
                    const maxQ = WeightEditorState.parentQTypical || 0;
                    const ctx = (parsed.unit === 'Q' && maxQ > 0)
                        ? ` (parent has ~${maxQ} q's, max ${maxQ})`
                        : '';
                    Toast.error(
                        'Out of range',
                        `Value resolves to ${asPercent.toFixed(1)}%; must be 0–100%${ctx}.`
                    );
                }
                resetToCurrent();
                return;
            }
            e.target.value = _formatInputForCurrentUnit(asPercent);
            onWeightChange(asPercent);
        });
    }
}

/**
 * Stage 6 — format a percentage value for display in the input field
 * according to the segmented control's current unit. Single source of
 * truth so the input handler, blur handler, and updateWeightDisplay all
 * agree on what number to show.
 *
 * @param {number} percentValue - The canonical % value (always 0-100).
 * @returns {string} The string to put into input.value.
 */
function _formatInputForCurrentUnit(percentValue) {
    const p = (percentValue == null || isNaN(percentValue)) ? 0 : percentValue;
    if (
        WeightEditorState.currentUnit === 'Q'
        && WeightEditorState.parentQTypical
        && WeightEditorState.parentQTypical > 0
    ) {
        const qVal = (p / 100) * WeightEditorState.parentQTypical;
        return qVal.toFixed(0);
    }
    return p.toFixed(WeightEditorState.precision);
}

/**
 * Stage 6 — set the active state on the unit toggle buttons.
 * @param {string} unit - '%' or 'Q'
 */
function _setUnitButtonsActive(unit) {
    const buttons = document.querySelectorAll('#weight-unit-toggle .weight-unit-btn');
    buttons.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.unit === unit);
    });
}

/**
 * Stage 6 — toggle the active unit in the segmented control.
 *
 * Reformats the displayed value via convertWeightUnit so the user sees
 * the equivalent number under the new unit (no value change, just a
 * display reformat).
 *
 * @param {string} newUnit - '%' or 'Q'
 */
function setWeightEditorUnit(newUnit) {
    if (newUnit !== '%' && newUnit !== 'Q') return;
    if (newUnit === WeightEditorState.currentUnit) return;
    if (newUnit === 'Q' && !WeightEditorState.parentQTypical) {
        // Q mode is unavailable — defensive guard, the segment should
        // already be hidden in this case.
        return;
    }

    const oldUnit = WeightEditorState.currentUnit;
    const input = document.getElementById('weight-input-enhanced');
    if (input && input.value) {
        const parsed = parseWeightInput(input.value, oldUnit);
        if (parsed) {
            const converted = convertWeightUnit(
                parsed.value,
                parsed.unit,
                newUnit,
                WeightEditorState.parentQTypical
            );
            if (converted != null) {
                if (newUnit === 'Q') {
                    input.value = converted.toFixed(0);
                } else {
                    input.value = converted.toFixed(WeightEditorState.precision);
                }
            }
        }
    }

    WeightEditorState.currentUnit = newUnit;
    _setUnitButtonsActive(newUnit);
}

/**
 * Stage 6 — switch the weight editor's parent context (multi-parent UX).
 *
 * When a child appears under multiple parents, the user can click an
 * alternate parent in the switch-parent block to edit the weight under
 * that parent edge. We update the currentEdgeId, look up the
 * fresh parent context, and re-render the editor in place.
 *
 * @param {number} edgeId - The new edge to edit.
 * @param {number} parentId - The new parent id (used for q_typical lookup).
 */
async function switchWeightEditorParent(edgeId, parentId) {
    if (!WeightEditorState.node) return;

    WeightEditorState.currentEdgeId = edgeId;
    const edge = (WeightEditorState.childParentEdges || []).find(e => e.edge_id === edgeId);
    if (edge) {
        WeightEditorState.parentName = edge.parent_name || '';
        // Use the edge's own relative_weight as the new "current".
        if (edge.relative_weight != null) {
            WeightEditorState.originalWeight = edge.relative_weight;
            WeightEditorState.currentWeight = edge.relative_weight;
        }
    }

    // Re-fetch parent q_typical for the new parent context so % ↔ Q
    // conversion is correct under the switched edge.
    WeightEditorState.parentQTypical = null;
    if (WeightEditorState.examLengthKind !== 'unknown' && parentId) {
        try {
            const allocation = await api.getQuestionAllocation(parentId);
            if (allocation && allocation.total_q != null) {
                WeightEditorState.parentQTypical = allocation.total_q;
            }
        } catch (error) {
            console.debug('switchWeightEditorParent: getQuestionAllocation failed:',
                error?.message || error);
        }
    }

    renderWeightEditor(WeightEditorState.node);
}

/**
 * Setup event listeners for weight range inputs (Low/High)
 */
function setupRangeWeightListeners() {
    const lowInput = document.getElementById('weight-low-input');
    const highInput = document.getElementById('weight-high-input');
    const precision = WeightEditorState.precision;

    if (lowInput) {
        lowInput.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            if (!isNaN(value) && value >= 0 && value <= 100) {
                onWeightRangeChange('low', value);
            }
        });

        lowInput.addEventListener('blur', (e) => {
            let value = parseFloat(e.target.value) || 0;
            value = Math.max(0, Math.min(100, value));
            // Ensure low <= high
            if (value > WeightEditorState.currentWeightHigh) {
                value = WeightEditorState.currentWeightHigh;
            }
            e.target.value = value.toFixed(precision);
            onWeightRangeChange('low', value);
        });
    }

    if (highInput) {
        highInput.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            if (!isNaN(value) && value >= 0 && value <= 100) {
                onWeightRangeChange('high', value);
            }
        });

        highInput.addEventListener('blur', (e) => {
            let value = parseFloat(e.target.value) || 0;
            value = Math.max(0, Math.min(100, value));
            // Ensure high >= low
            if (value < WeightEditorState.currentWeightLow) {
                value = WeightEditorState.currentWeightLow;
            }
            e.target.value = value.toFixed(precision);
            onWeightRangeChange('high', value);
        });
    }
}

/**
 * Handle weight range value change (Low or High)
 * @param {string} field - 'low' or 'high'
 * @param {number} newValue - New weight value
 */
function onWeightRangeChange(field, newValue) {
    const precision = WeightEditorState.precision;
    newValue = Number(newValue.toFixed(precision));

    if (field === 'low') {
        WeightEditorState.currentWeightLow = newValue;
        // Also update the main currentWeight to low value for compatibility
        WeightEditorState.currentWeight = newValue;
    } else {
        WeightEditorState.currentWeightHigh = newValue;
    }

    // Check if values have changed from original
    const lowChanged = WeightEditorState.currentWeightLow !== WeightEditorState.originalWeightLow;
    const highChanged = WeightEditorState.currentWeightHigh !== WeightEditorState.originalWeightHigh;
    WeightEditorState.isPreviewMode = lowChanged || highChanged;

    updateWeightRangeDisplay();
    renderEnhancedSiblingsChart();
}

/**
 * Handle weight value change
 * @param {number} newValue - New weight value
 */
function onWeightChange(newValue) {
    const precision = WeightEditorState.precision;
    WeightEditorState.currentWeight = Number(newValue.toFixed(precision));
    WeightEditorState.isPreviewMode = WeightEditorState.currentWeight !== WeightEditorState.originalWeight;
    
    updateWeightDisplay();
    renderEnhancedSiblingsChart();
    updateBasicWeightElements();
}

/**
 * Update the weight display elements
 */
function updateWeightDisplay() {
    const weight = WeightEditorState.currentWeight;
    const original = WeightEditorState.originalWeight;
    const delta = weight - original;
    const precision = WeightEditorState.precision;
    
    const display = document.getElementById('weight-display');
    if (display) {
        display.textContent = `${weight.toFixed(precision)}%`;
        display.classList.toggle('changed', delta !== 0);
    }
    
    const deltaEl = document.getElementById('weight-delta');
    if (deltaEl) {
        deltaEl.textContent = `${delta > 0 ? '+' : ''}${delta.toFixed(precision)}%`;
        deltaEl.className = `weight-delta ${delta > 0 ? 'positive' : delta < 0 ? 'negative' : 'neutral'}`;
    }
    
    const slider = document.getElementById('weight-slider-enhanced');
    if (slider) {
        slider.value = weight;
        slider.classList.toggle('preview-mode', WeightEditorState.isPreviewMode);
    }
    
    const input = document.getElementById('weight-input-enhanced');
    if (input && document.activeElement !== input) {
        // Stage 6 fix: respect the current segmented-control unit when
        // re-rendering the input. Previously this always wrote the %
        // value, which overrode the blur handler's Q-mode formatting
        // and produced the surprising "20 → 100" jump in Q mode.
        input.value = _formatInputForCurrentUnit(weight);
    }

    const applyBtn = document.getElementById('btn-apply-weight-enhanced');
    if (applyBtn) {
        applyBtn.disabled = delta === 0;
    }
    
    const previewBadge = document.querySelector('.weight-preview-badge');
    if (previewBadge) {
        previewBadge.style.display = WeightEditorState.isPreviewMode ? '' : 'none';
    }
}

/**
 * Update basic weight elements in the original panel
 */
function updateBasicWeightElements() {
    const weight = WeightEditorState.currentWeight;
    const precision = WeightEditorState.precision;

    const basicSlider = document.getElementById('weight-slider');
    if (basicSlider && document.activeElement !== basicSlider) {
        basicSlider.value = weight;
    }

    const basicInput = document.getElementById('weight-value');
    if (basicInput && document.activeElement !== basicInput) {
        basicInput.value = weight.toFixed(precision);
    }

    const basicTotal = document.getElementById('siblings-total');
    if (basicTotal) {
        const previewWeights = calculatePreviewWeights();
        let total = 0;
        previewWeights.forEach(w => total += w);
        const isValid = Math.abs(total - 100) < 0.1;
        basicTotal.innerHTML = `Total: <span>${total.toFixed(precision)}%</span>`;
        basicTotal.className = `siblings-total ${isValid ? '' : 'invalid'}`;
    }
}

/**
 * Update the weight range display elements
 */
function updateWeightRangeDisplay() {
    const precision = WeightEditorState.precision;
    const lowChanged = WeightEditorState.currentWeightLow !== WeightEditorState.originalWeightLow;
    const highChanged = WeightEditorState.currentWeightHigh !== WeightEditorState.originalWeightHigh;
    const hasChanges = lowChanged || highChanged;

    // Update main display
    const display = document.getElementById('weight-display');
    if (display) {
        display.textContent = `${WeightEditorState.currentWeightLow.toFixed(precision)}% – ${WeightEditorState.currentWeightHigh.toFixed(precision)}%`;
        display.classList.toggle('changed', hasChanges);
    }

    // Update input fields (only if not focused)
    const lowInput = document.getElementById('weight-low-input');
    if (lowInput && document.activeElement !== lowInput) {
        lowInput.value = WeightEditorState.currentWeightLow.toFixed(precision);
    }

    const highInput = document.getElementById('weight-high-input');
    if (highInput && document.activeElement !== highInput) {
        highInput.value = WeightEditorState.currentWeightHigh.toFixed(precision);
    }

    // Update apply button state
    const applyBtn = document.getElementById('btn-apply-weight-enhanced');
    if (applyBtn) {
        applyBtn.disabled = !hasChanges;
    }

    // Update preview badge
    const previewBadge = document.querySelector('.weight-preview-badge');
    if (previewBadge) {
        previewBadge.style.display = hasChanges ? '' : 'none';
    }
}

/**
 * Reset the weight editor to original value
 */
function resetWeightEditor() {
    WeightEditorState.currentWeight = WeightEditorState.originalWeight;
    WeightEditorState.isPreviewMode = false;

    // Reset range values if applicable
    if (WeightEditorState.hasWeightRange) {
        WeightEditorState.currentWeightLow = WeightEditorState.originalWeightLow;
        WeightEditorState.currentWeightHigh = WeightEditorState.originalWeightHigh;
        updateWeightRangeDisplay();
    } else {
        updateWeightDisplay();
    }

    renderEnhancedSiblingsChart();
    updateBasicWeightElements();

    Toast.info('Reset', 'Weight reset to original value');
}

/**
 * Apply the weight change - uses hybrid weight API for relative weights
 */
async function applyWeightChange() {
    if (!WeightEditorState.nodeId) return;

    // Handle weight range changes
    if (WeightEditorState.hasWeightRange) {
        await applyWeightRangeChange();
        return;
    }

    const newWeight = WeightEditorState.currentWeight;
    const originalWeight = WeightEditorState.originalWeight;

    if (newWeight === originalWeight) {
        Toast.info('No Change', 'Weight value is unchanged');
        return;
    }

    try {
        const applyBtn = document.getElementById('btn-apply-weight-enhanced');
        if (applyBtn) {
            applyBtn.disabled = true;
            applyBtn.textContent = 'Applying...';
        }

        let result;

        // Use hybrid weight API for relative weights
        if (WeightEditorState.weightType === 'relative') {
            // Stage 6 — canonical user-typed-value path. Single atomic
            // bridge call that writes value AND anchors AND records the
            // 'user_explicit' source. Replaces the pre-Stage-6 two-call
            // hot patch (updateRelativeWeight + setEdgeAnchor).
            //
            // Falls back to the legacy node-keyed writer when there is
            // no edge_id (root nodes / orphans) since setExplicitWeight
            // is per-edge. The fallback path preserves the previous
            // behavior for those rare cases.
            if (WeightEditorState.currentEdgeId) {
                // Resolve the value to apply. Priority order:
                //   1. Re-parse the live input field so magic suffixes
                //      (10% / 28q) typed right before Apply are honored
                //      without a prior blur.
                //   2. Fall back to ``WeightEditorState.currentWeight``
                //      (always in %; maintained by the input handler).
                //
                // The input handler's onWeightChange path silently bails
                // when a Q value converts to >100%, so without an
                // explicit guard here we'd either crash at the bridge
                // ("Relative weight must be between 0 and 100") or
                // silently apply the stale state value.
                let percentForApi = newWeight;
                const inputEl = document.getElementById('weight-input-enhanced');
                if (inputEl && inputEl.value) {
                    const parsed = parseWeightInput(
                        inputEl.value, WeightEditorState.currentUnit
                    );
                    if (parsed) {
                        let asPercent = parsed.value;
                        if (parsed.unit === 'Q') {
                            const conv = convertWeightUnit(
                                parsed.value, 'Q', '%',
                                WeightEditorState.parentQTypical
                            );
                            if (conv == null) {
                                Toast.error(
                                    'Cannot convert',
                                    'No parent question budget — switch to % mode.'
                                );
                                return;
                            }
                            asPercent = conv;
                        }
                        if (asPercent < 0 || asPercent > 100) {
                            const maxQ = (WeightEditorState.parentQTypical || 0);
                            const ctx = (parsed.unit === 'Q' && maxQ > 0)
                                ? ` (parent has ~${maxQ} q's, max ${maxQ})`
                                : '';
                            Toast.error(
                                'Out of range',
                                `Value resolves to ${asPercent.toFixed(1)}%; must be 0–100%${ctx}.`
                            );
                            return;
                        }
                        percentForApi = asPercent;
                    }
                }
                if (percentForApi == null || percentForApi < 0 || percentForApi > 100) {
                    Toast.error(
                        'Invalid',
                        `Weight must be between 0% and 100%.`
                    );
                    return;
                }
                result = await api.setExplicitWeight({
                    edgeId: WeightEditorState.currentEdgeId,
                    value: percentForApi,
                    unit: '%',
                    reason: 'Manual adjustment'
                });

                // Read the anchor checkbox; un-check means the user
                // wants this written but NOT anchored (rebalance-fair
                // value rather than a hard anchor).
                const anchorCheckbox = document.getElementById('weight-anchor-checkbox');
                const shouldAnchor = anchorCheckbox ? !!anchorCheckbox.checked : true;
                if (!shouldAnchor) {
                    try {
                        await api.setEdgeAnchor({
                            edgeId: WeightEditorState.currentEdgeId,
                            isAnchor: false,
                            reason: 'User unchecked anchor on Apply'
                        });
                    } catch (anchorErr) {
                        console.warn('Failed to clear anchor after Apply:', anchorErr);
                    }
                }

                const appliedRw = result?.applied_relative_weight ?? newWeight;
                const appliedQ = result?.applied_question_count;
                const successMsg = (appliedQ != null)
                    ? `Set to ${appliedRw.toFixed(WeightEditorState.precision)}% (~${appliedQ} q's)`
                    : `Set to ${appliedRw.toFixed(WeightEditorState.precision)}%`;
                Toast.success('Updated', successMsg);
            } else {
                // Defensive fallback: no edge resolved (root or orphan).
                // The legacy node-keyed writer is the only path here.
                result = await api.updateRelativeWeight({
                    nodeId: WeightEditorState.nodeId,
                    relativeWeight: newWeight,
                    reason: 'Manual adjustment'
                });
                Toast.success('Updated', `Relative weight set to ${newWeight.toFixed(WeightEditorState.precision)}%`);
            }
        } else {
            // Update absolute weight via generic node update (sets both low and high)
            result = await api.updateSubjectNode(WeightEditorState.nodeId, {
                exam_weight_low: newWeight,
                exam_weight_high: newWeight
            });

            Toast.success('Updated', `Weight set to ${newWeight.toFixed(WeightEditorState.precision)}%`);
        }

        WeightEditorState.originalWeight = newWeight;
        WeightEditorState.isPreviewMode = false;

        // Invalidate cache for multi-dimensional exams
        if (typeof invalidateDimensionCache === 'function' && TreeState.usesDimensions && TreeState.currentDimensionId) {
            invalidateDimensionCache(TreeState.currentDimensionId);
        }

        // Reload the hierarchy
        await loadHierarchy();

        if (TreeState.selectedNodeId) {
            showNodeDetails(TreeState.selectedNodeId);
        }

        await loadWeightHistory(WeightEditorState.nodeId);

    } catch (error) {
        Toast.error('Error', error.message);
    } finally {
        const applyBtn = document.getElementById('btn-apply-weight-enhanced');
        if (applyBtn) {
            applyBtn.disabled = false;
            applyBtn.textContent = 'Apply Changes';
        }
    }
}

/**
 * Apply weight range changes (both low and high values)
 */
async function applyWeightRangeChange() {
    const newLow = WeightEditorState.currentWeightLow;
    const newHigh = WeightEditorState.currentWeightHigh;
    const originalLow = WeightEditorState.originalWeightLow;
    const originalHigh = WeightEditorState.originalWeightHigh;
    const precision = WeightEditorState.precision;

    // Check if no changes
    if (newLow === originalLow && newHigh === originalHigh) {
        Toast.info('No Change', 'Weight range is unchanged');
        return;
    }

    // Validate range
    if (newLow > newHigh) {
        Toast.warning('Invalid Range', 'Low value cannot be greater than high value');
        return;
    }

    try {
        const applyBtn = document.getElementById('btn-apply-weight-enhanced');
        if (applyBtn) {
            applyBtn.disabled = true;
            applyBtn.textContent = 'Applying...';
        }

        // Update the node with new weight range
        const result = await api.updateSubjectNode(WeightEditorState.nodeId, {
            exam_weight_low: newLow,
            exam_weight_high: newHigh
        });

        Toast.success('Updated', `Weight range set to ${newLow.toFixed(precision)}% – ${newHigh.toFixed(precision)}%`);

        // Update original values
        WeightEditorState.originalWeightLow = newLow;
        WeightEditorState.originalWeightHigh = newHigh;
        WeightEditorState.originalWeight = newLow;
        WeightEditorState.isPreviewMode = false;

        // Invalidate cache for multi-dimensional exams
        if (typeof invalidateDimensionCache === 'function' && TreeState.usesDimensions && TreeState.currentDimensionId) {
            invalidateDimensionCache(TreeState.currentDimensionId);
        }

        // Reload the hierarchy
        await loadHierarchy();

        if (TreeState.selectedNodeId) {
            showNodeDetails(TreeState.selectedNodeId);
        }

        await loadWeightHistory(WeightEditorState.nodeId);

    } catch (error) {
        Toast.error('Error', error.message);
    } finally {
        const applyBtn = document.getElementById('btn-apply-weight-enhanced');
        if (applyBtn) {
            applyBtn.disabled = false;
            applyBtn.textContent = 'Apply Changes';
        }
    }
}

/**
 * Toggle weight history visibility
 */
function toggleWeightHistory() {
    WeightEditorState.historyExpanded = !WeightEditorState.historyExpanded;
    
    const historyList = document.getElementById('weight-history-list');
    const toggleBtn = document.querySelector('.weight-history-toggle');
    
    if (historyList) {
        historyList.classList.toggle('collapsed', !WeightEditorState.historyExpanded);
    }
    
    if (toggleBtn) {
        toggleBtn.textContent = WeightEditorState.historyExpanded ? 'Hide' : 'Show';
    }
}

// =========================================================================
// Utility Functions
// =========================================================================

function getWeightTypeLabel(type) {
    switch (type) {
        case 'absolute': return 'Absolute';
        case 'relative': return 'Relative';
        case 'effective': return 'Effective';
        default: return type;
    }
}

function getSourceLabel(source) {
    switch (source) {
        case 'official': return 'Official Exam Weight';
        case 'derived': return 'Derived from Official';
        case 'user_estimate': return 'User Estimate';
        case 'user_defined': return 'User Defined';
        default: return source;
    }
}

function getConfidenceIcon(confidence) {
    switch (confidence) {
        case 'high': return '🟢';
        case 'medium': return '🟡';
        case 'low': return '🟠';
        default: return '⚪';
    }
}

function getWeightModeLabel(mode) {
    switch (mode) {
        case 'official_ranges': return 'Official Ranges';
        case 'official_fixed': return 'Official Fixed';
        case 'user_defined': return 'User Defined';
        default: return mode;
    }
}

function getAlgorithmDescription(algorithm) {
    switch (algorithm) {
        case 'proportional':
            return 'Changes distributed by current weight ratio';
        case 'even':
            return 'Changes distributed equally';
        default:
            return '';
    }
}

function capitalizeFirst(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
}

function escapeHtmlWeight(text) {
    if (typeof escapeHtml === 'function') {
        return escapeHtml(text);
    }
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =========================================================================
// Global Exports
// =========================================================================

window.initWeightEditor = initWeightEditor;
window.resetWeightEditor = resetWeightEditor;
window.applyWeightChange = applyWeightChange;
window.rebalanceSiblings = rebalanceSiblings;
window.toggleWeightHistory = toggleWeightHistory;
window.WeightEditorState = WeightEditorState;
// Stage 6 (Hierarchical Weight Allocation) — expose helpers for
// inline onclick handlers + scenario-driven probing in wimi_test.
window.parseWeightInput = parseWeightInput;
window.convertWeightUnit = convertWeightUnit;
window.setWeightEditorUnit = setWeightEditorUnit;
window.switchWeightEditorParent = switchWeightEditorParent;
// Stage 7 — expose the feasibility-badge helper so wimi_test
// scenarios can probe it directly and the tree-row warning dot can
// re-trigger badge population after navigation.
window._renderFeasibilityBadge = _renderFeasibilityBadge;
