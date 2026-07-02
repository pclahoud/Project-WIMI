/**
 * WIMI Tree Editor JavaScript
 * Phase 3 - Subject Hierarchy Management
 */

// =========================================================================
// State Management
// =========================================================================

const TreeState = {
    examContextId: null,
    examContext: null,
    hierarchyLevels: [],
    rootNodes: [],
    flatNodes: new Map(), // Map of nodeId -> node for quick lookup

    // Polyhierarchy: how many times each node id appears in the rendered
    // tree. count > 1 means the node has multiple parents and we render
    // the multi-parent chip on its primary appearance. Built once after
    // each loadHierarchy() in buildFlatNodeMap().
    appearanceCount: new Map(),

    // Cache of api.getParents(nodeId) results. Populated lazily when a
    // node is selected; cleared when the parents change (add/remove edge,
    // primary switch).
    parentsCache: new Map(),
    selectedNodeId: null,
    expandedNodes: new Set(),
    isLoading: true,
    editingNodeId: null,
    originalWeight: null,

    // Multi-dimensional support
    usesDimensions: false,       // Does this exam use multi-dimensional categorization?
    dimensions: [],              // Array of dimension objects
    currentDimensionId: null,    // Currently selected dimension ID
    currentDimension: null,      // Currently selected dimension object
    dimensionHierarchies: {},    // Cache: dimensionId -> { rootNodes, flatNodes }

    // Search/filter
    searchQuery: '',
    searchMatchIds: new Set(),
    searchVisibleIds: null,        // null = no filter active
    preSearchExpandedNodes: null   // saved expand state before search
};

// =========================================================================
// Toast Notification System (reused from landing)
// =========================================================================

const Toast = {
    container: null,
    
    init() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.className = 'toast-container';
            this.container.style.cssText = `
                position: fixed;
                bottom: 24px;
                right: 24px;
                z-index: 9999;
                display: flex;
                flex-direction: column;
                gap: 8px;
            `;
            document.body.appendChild(this.container);
        }
    },
    
    show(type, title, message, duration = 4000) {
        this.init();
        
        const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
        const colorVars = {
            success: 'var(--color-success, #10b981)',
            error: 'var(--color-error, #ef4444)',
            warning: 'var(--color-warning, #f59e0b)',
            info: 'var(--color-info, #06b6d4)'
        };

        const toast = document.createElement('div');
        toast.style.cssText = `
            background: var(--bg-primary, white);
            color: var(--text-primary, #111827);
            border-radius: 8px;
            padding: 12px 16px;
            box-shadow: var(--shadow-lg, 0 10px 15px -3px rgba(0,0,0,0.1));
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 280px;
            border-left: 4px solid ${colorVars[type]};
            transform: translateX(100%);
            opacity: 0;
            transition: all 0.2s ease;
        `;

        toast.innerHTML = `
            <span style="color: ${colorVars[type]}; font-size: 1.25rem;">${icons[type]}</span>
            <div style="flex: 1;">
                <div style="font-weight: 500; margin-bottom: 2px;">${title}</div>
                ${message ? `<div style="font-size: 0.875rem; color: var(--text-muted);">${message}</div>` : ''}
            </div>
            <button style="background: none; border: none; cursor: pointer; color: var(--text-muted); font-size: 1.25rem;">×</button>
        `;
        
        this.container.appendChild(toast);
        
        requestAnimationFrame(() => {
            toast.style.transform = 'translateX(0)';
            toast.style.opacity = '1';
        });
        
        toast.querySelector('button').onclick = () => this.dismiss(toast);
        if (duration > 0) setTimeout(() => this.dismiss(toast), duration);
    },
    
    dismiss(toast) {
        toast.style.transform = 'translateX(100%)';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 200);
    },
    
    success(title, message) { this.show('success', title, message); },
    error(title, message) { this.show('error', title, message); },
    warning(title, message) { this.show('warning', title, message); },
    info(title, message) { this.show('info', title, message); }
};

// =========================================================================
// Initialization
// =========================================================================

async function initializeTreeEditor() {
    console.log('🌳 Initializing tree editor...');

    // Get exam ID from URL
    const urlParams = new URLSearchParams(window.location.search);
    const examId = urlParams.get('exam_id');

    if (!examId) {
        showError('No exam ID provided. Please select an exam from the landing page.');
        return;
    }

    TreeState.examContextId = parseInt(examId);

    try {
        await api.ready();

        // Load exam context
        await loadExamContext();

        // Load hierarchy levels
        await loadHierarchyLevels();

        // Check if exam uses dimensions
        await checkDimensionSupport();

        if (TreeState.usesDimensions) {
            // Load dimensions and show selector
            await loadDimensions();
            renderDimensionSelector();

            // Select first dimension by default
            if (TreeState.dimensions.length > 0) {
                await selectDimension(TreeState.dimensions[0].id);
            }
        } else {
            // Simple exam - load hierarchy normally
            await loadHierarchy();
        }

        // Setup event listeners
        setupEventListeners();

        console.log('✅ Tree editor initialized');

    } catch (error) {
        console.error('Error initializing tree editor:', error);
        showError(`Failed to load exam: ${error.message}`);
    }
}

async function loadExamContext() {
    TreeState.examContext = await api.getExamContext(TreeState.examContextId);
    
    // Update header
    document.getElementById('exam-name').textContent = TreeState.examContext.exam_name;
    document.getElementById('exam-badge').textContent = TreeState.examContext.is_active ? 'Active' : 'Inactive';
    document.getElementById('exam-badge').className = `badge ${TreeState.examContext.is_active ? 'badge-success' : 'badge-gray'}`;
    
    document.title = `${TreeState.examContext.exam_name} - Subject Hierarchy - WIMI`;
}

async function loadHierarchyLevels() {
    TreeState.hierarchyLevels = await api.getHierarchyLevels(TreeState.examContextId);
    
    // Populate level dropdown in modal
    const levelSelect = document.getElementById('modal-node-level');
    levelSelect.innerHTML = TreeState.hierarchyLevels
        .map(level => `<option value="${level.level_name}">${level.level_name}</option>`)
        .join('');
}

async function loadHierarchy() {
    // For multi-dimensional exams, use dimension-specific loading
    if (TreeState.usesDimensions && TreeState.currentDimensionId) {
        await loadDimensionHierarchy(TreeState.currentDimensionId);
        renderTree();
        updateStats();
        if (TreeState.usesDimensions) {
            updateDimensionStats();
        }
        return;
    }

    showLoading(true);

    try {
        // Try to get hierarchy from backend
        // For now, we'll work with the existing get_subject_hierarchy method
        // which uses exam_context name string, not ID
        const hierarchy = await api.getSubjectHierarchy(TreeState.examContextId);

        TreeState.rootNodes = hierarchy?.root_nodes || [];
        buildFlatNodeMap();

        // Stage 5 — enrich the rendered nodes with ``q_typical`` so the
        // chip text and tooltip can show ``XX.X% • ~N q``. The
        // ``get_subject_hierarchy`` backend doesn't carry this field
        // (it returns ``SubjectNode`` rows), so we fetch the per-edge
        // counts in a separate call and overlay them. When
        // ``length_kind='unknown'`` the bridge returns null for every
        // q_typical, which is the no-op degradation path.
        await enrichNodesWithQuestionCounts();

        // Stage 7 — overlay per-parent feasibility status so renderNode
        // can draw a warning dot on rows whose children's weights don't
        // fit cleanly. Mirrored on the dimensional load path below.
        await enrichNodesWithFeasibility();

        renderTree();
        updateStats();

        // Show overview by default when no node is selected
        if (!TreeState.selectedNodeId) {
            showExamOverview();
        }

    } catch (error) {
        console.log('Hierarchy not yet available or error:', error);
        TreeState.rootNodes = [];
        renderTree();
        showExamOverview();
    } finally {
        showLoading(false);
    }
}

/**
 * Stage 5 — overlay per-edge ``q_typical`` onto the loaded tree.
 *
 * Calls ``api.getEffectiveQuestionCounts`` and stamps ``node.q_typical``
 * onto every node in ``TreeState.flatNodes``. The mapping is
 * child-id → max q_typical across this child's incoming edges (the
 * polyhierarchy case may yield multiple edges per child); using the
 * max keeps the chip honest under the most generous parent context.
 *
 * When the exam is ``length_kind='unknown'`` the response carries
 * ``q_typical: null`` on every row; we leave the node fields untouched
 * so the chip falls back to the percentage-only display.
 *
 * Failures are non-fatal — the tree still renders without the dual
 * unit display.
 */
/**
 * Stage 7 — overlay per-parent feasibility status onto the loaded tree.
 *
 * Calls ``api.getAllFeasibilityReports`` and stamps
 * ``node.feasibility_status`` onto every node in the tree that is a
 * parent (i.e. appears as a key in the response). The render path
 * (``renderNode``) uses this field to draw a warning dot on rows whose
 * status is non-``'ok'``.
 *
 * Failures are non-fatal — the tree still renders without the warning
 * dots, mirroring ``enrichNodesWithQuestionCounts`` behavior.
 *
 * Must run on BOTH the non-dimensional and dimensional load paths per
 * the feedback memory in ``feedback_dimension_code_paths.md``.
 */
async function enrichNodesWithFeasibility() {
    try {
        const response = await api.getAllFeasibilityReports(TreeState.examContextId);
        const parents = response?.parents || {};
        if (!parents || Object.keys(parents).length === 0) return;

        const stamp = (nodes) => {
            for (const node of nodes) {
                // The bridge serializes parent_id keys as strings (JSON
                // object keys must be strings); coerce on lookup.
                const key = String(node.id);
                if (Object.prototype.hasOwnProperty.call(parents, key)) {
                    const rep = parents[key];
                    node.feasibility_status = rep?.status || 'ok';
                }
                if (node.children && node.children.length > 0) {
                    stamp(node.children);
                }
            }
        };
        stamp(TreeState.rootNodes);
    } catch (error) {
        // Pre-Stage-7 bridges and exam contexts without the length
        // triple land here — skip silently. The chip still renders.
        console.debug('enrichNodesWithFeasibility skipped:', error?.message || error);
    }
}

async function enrichNodesWithQuestionCounts() {
    try {
        const counts = await api.getEffectiveQuestionCounts(TreeState.examContextId);
        if (!Array.isArray(counts) || counts.length === 0) return;

        const perChild = new Map();
        // Stage 6 — also stamp is_anchor + edge_id per child so the
        // weight chip can show an anchor pin and the sibling-preview
        // chart can render anchored vs auto-distributed bars.
        const anchorPerChild = new Map();
        const edgeIdPerChild = new Map();
        // Stage 8 — is_adaptive is uniform across all rows of one
        // exam context (it derives from length_kind on the context,
        // not per-edge). Capture it once for the chip formatter to
        // pick the float + "(planning estimate)" branch.
        let examIsAdaptive = false;
        for (const row of counts) {
            if (row.is_adaptive === true) {
                examIsAdaptive = true;
            }
            if (row.q_typical !== null && row.q_typical !== undefined) {
                const existing = perChild.get(row.child_id);
                if (existing === undefined || row.q_typical > existing) {
                    perChild.set(row.child_id, row.q_typical);
                }
            }
            // is_anchor / edge_id come straight from the per-edge row.
            // For polyhierarchy children with multiple edges, the last
            // row wins — Stage 6 only uses these for chip display, so
            // any-parent semantics are acceptable.
            if (row.is_anchor !== undefined) {
                // OR-fold: if ANY edge to this child is anchored, mark
                // the node as anchored on the chip. This is honest
                // because anchoring is per-edge and the chip summarizes
                // across the rendered context.
                anchorPerChild.set(
                    row.child_id,
                    !!(anchorPerChild.get(row.child_id) || row.is_anchor)
                );
            }
            if (row.edge_id !== undefined && !edgeIdPerChild.has(row.child_id)) {
                edgeIdPerChild.set(row.child_id, row.edge_id);
            }
        }

        // Stage 8 — surface on TreeState so renderNode (and the
        // tooltip helper) can pick the right q_typical formatter
        // without traversing the per-node flag.
        TreeState.examIsAdaptive = examIsAdaptive;

        // Apply to the rendered tree.
        const stamp = (nodes) => {
            for (const node of nodes) {
                if (perChild.has(node.id)) {
                    node.q_typical = perChild.get(node.id);
                }
                if (anchorPerChild.has(node.id)) {
                    node.is_anchor = anchorPerChild.get(node.id);
                }
                if (edgeIdPerChild.has(node.id)) {
                    node.primary_edge_id = edgeIdPerChild.get(node.id);
                }
                // Stage 8 — stamp is_adaptive per node (uniform across
                // the exam) so the chip render at renderNode can pick
                // the float + "(planning estimate)" formatter.
                node.is_adaptive = examIsAdaptive;
                if (node.children && node.children.length > 0) {
                    stamp(node.children);
                }
            }
        };
        stamp(TreeState.rootNodes);
    } catch (error) {
        // Length-triple migration may not be applied yet on legacy
        // databases, or the bridge slot may not be wired. Either way,
        // chip text falls back to percentage-only — no need to log
        // loudly.
        console.debug('enrichNodesWithQuestionCounts skipped:', error?.message || error);
    }
}

function buildFlatNodeMap() {
    TreeState.flatNodes.clear();
    TreeState.appearanceCount.clear();

    function addToMap(nodes, parent = null) {
        for (const node of nodes) {
            // Polyhierarchy: a node may appear under multiple parents in
            // the rendered tree. Increment its appearance count so the
            // primary appearance can show a "↗N" chip. Note that flatNodes
            // intentionally keeps only the LAST occurrence per id (we use
            // it for "find a node by id"); _parent is set to the parent
            // of whichever appearance was visited last and is best-effort.
            const cur = TreeState.appearanceCount.get(node.id) || 0;
            TreeState.appearanceCount.set(node.id, cur + 1);

            node._parent = parent;
            TreeState.flatNodes.set(node.id, node);
            if (node.children && node.children.length > 0) {
                addToMap(node.children, node);
            }
        }
    }

    addToMap(TreeState.rootNodes);
}

// =========================================================================
// Multi-Dimensional Support
// =========================================================================

/**
 * Check if the current exam uses multi-dimensional categorization
 */
async function checkDimensionSupport() {
    try {
        const result = await api.examUsesDimensions(TreeState.examContextId);
        TreeState.usesDimensions = result.uses_dimensions;
        console.log(`📊 Exam uses dimensions: ${TreeState.usesDimensions}`);
    } catch (error) {
        console.warn('Could not check dimension support:', error);
        TreeState.usesDimensions = false;
    }
}

/**
 * Load all dimensions for the current exam
 */
async function loadDimensions() {
    try {
        TreeState.dimensions = await api.getDimensions(TreeState.examContextId);
        console.log(`📊 Loaded ${TreeState.dimensions.length} dimensions`);
    } catch (error) {
        console.error('Failed to load dimensions:', error);
        TreeState.dimensions = [];
    }
}

/**
 * Render the dimension selector tabs
 */
function renderDimensionSelector() {
    const selector = document.getElementById('dimension-selector');
    const tabsContainer = document.getElementById('dimension-tabs');

    if (!selector || !tabsContainer) return;

    if (!TreeState.usesDimensions || TreeState.dimensions.length === 0) {
        selector.classList.add('hidden');
        return;
    }

    selector.classList.remove('hidden');

    tabsContainer.innerHTML = TreeState.dimensions.map(dim => `
        <button class="dimension-tab ${dim.id === TreeState.currentDimensionId ? 'active' : ''}"
                data-dimension-id="${dim.id}"
                data-testid="tree-dimension-tab-${dim.id}"
                onclick="selectDimension(${dim.id})"
                title="${escapeHtml(dim.description || dim.name)}">
            <span class="dimension-tab-name">${escapeHtml(dim.name)}</span>
            ${dim.is_required ? '<span class="dimension-tab-badge">Required</span>' : ''}
        </button>
    `).join('');
}

/**
 * Select a dimension and load its hierarchy
 * @param {number} dimensionId - Dimension ID to select
 */
async function selectDimension(dimensionId) {
    const dimension = TreeState.dimensions.find(d => d.id === dimensionId);
    if (!dimension) return;

    clearTreeSearch();

    TreeState.currentDimensionId = dimensionId;
    TreeState.currentDimension = dimension;

    // Update tab visual state
    document.querySelectorAll('.dimension-tab').forEach(tab => {
        tab.classList.toggle('active', parseInt(tab.dataset.dimensionId) === dimensionId);
    });

    // Update dimension info panel (name, description, badges - but NOT stats yet)
    updateDimensionInfo(dimension);

    // Load hierarchy for this dimension
    await loadDimensionHierarchy(dimensionId);

    // Render the tree
    renderTree();
    updateStats();

    // Update dimension stats AFTER hierarchy is loaded (fixes bug where stats showed previous dimension's data)
    updateDimensionStats();

    // Clear selection and show overview
    TreeState.selectedNodeId = null;
    showExamOverview();

    console.log(`📂 Selected dimension: ${dimension.name}`);
}

/**
 * Update the dimension info panel
 * @param {Object} dimension - The selected dimension
 */
function updateDimensionInfo(dimension) {
    const infoPanel = document.getElementById('dimension-info');
    const nameEl = document.getElementById('dimension-info-name');
    const badgeEl = document.getElementById('dimension-info-badge');
    const descEl = document.getElementById('dimension-info-description');
    const statsEl = document.getElementById('dimension-info-stats');

    if (!infoPanel) return;

    infoPanel.classList.remove('hidden');

    if (nameEl) nameEl.textContent = dimension.name;
    if (descEl) descEl.textContent = dimension.description || 'No description provided';

    if (badgeEl) {
        const badges = [];
        if (dimension.is_required) badges.push('Required');
        if (dimension.allow_multiple) badges.push('Multi-select');
        badgeEl.textContent = badges.join(' • ') || 'Optional';
        badgeEl.className = `dimension-info-badge ${dimension.is_required ? '' : 'optional'}`;
    }

    // Update empty state hint
    const emptyHint = document.getElementById('tree-empty-dimension-hint');
    const emptyDimName = document.getElementById('empty-dimension-name');
    if (emptyHint && emptyDimName) {
        emptyHint.classList.remove('hidden');
        emptyDimName.textContent = dimension.name;
    }

    // Stats will be updated after hierarchy loads
    updateDimensionStats();
}

/**
 * Update dimension stats in the info panel
 * Conditionally hides weight total when any nodes have weight ranges
 */
function updateDimensionStats() {
    const statsEl = document.getElementById('dimension-info-stats');
    if (!statsEl) return;

    const nodeCount = TreeState.flatNodes.size;

    // Check if any root nodes have weight ranges (exam_weight_low !== exam_weight_high)
    const hasWeightRanges = TreeState.rootNodes.some(node =>
        node.exam_weight_low !== null &&
        node.exam_weight_high !== null &&
        node.exam_weight_low !== node.exam_weight_high
    );

    if (hasWeightRanges) {
        // Don't show total weight when ranges exist - would be misleading
        statsEl.innerHTML = `
            <span class="dimension-stat"><strong>${nodeCount}</strong> subject${nodeCount !== 1 ? 's' : ''}</span>
            <span class="dimension-stat dimension-stat-range" title="Weight ranges are used - total varies">
                <span class="range-icon">↔</span> Weight ranges
            </span>
        `;
    } else {
        // Show total weight for fixed weights
        const totalWeight = TreeState.rootNodes.reduce((sum, node) => sum + (node.weight || node.exam_weight_low || 0), 0);
        statsEl.innerHTML = `
            <span class="dimension-stat"><strong>${nodeCount}</strong> subject${nodeCount !== 1 ? 's' : ''}</span>
            <span class="dimension-stat"><strong>${totalWeight.toFixed(1)}%</strong> total weight</span>
        `;
    }
}

/**
 * Load hierarchy for a specific dimension
 * @param {number} dimensionId - Dimension ID
 */
async function loadDimensionHierarchy(dimensionId) {
    showLoading(true);

    try {
        // Check cache first
        if (TreeState.dimensionHierarchies[dimensionId]) {
            const cached = TreeState.dimensionHierarchies[dimensionId];
            TreeState.rootNodes = cached.rootNodes;
            TreeState.flatNodes = new Map(cached.flatNodes);
            showLoading(false);
            return;
        }

        // Fetch from API
        const hierarchy = await api.getDimensionHierarchy(TreeState.examContextId, dimensionId);

        TreeState.rootNodes = hierarchy?.root_nodes || [];
        buildFlatNodeMap();

        // Stage 5 — overlay per-edge ``q_typical`` so chips render
        // ``XX.X% • ~N q`` in dimension view too. The non-dimension
        // path in loadHierarchy already does this; without it here,
        // dimensioned exams (the common case for IM Shelf, USMLE,
        // etc.) never see question counts on their chips.
        await enrichNodesWithQuestionCounts();

        // Stage 7 — overlay per-parent feasibility status so renderNode
        // can draw a warning dot on rows whose children's weights don't
        // fit cleanly. Mirrors the non-dimensional path in
        // ``loadHierarchy``; per ``feedback_dimension_code_paths.md``
        // both paths must enrich symmetrically so dimensioned exams
        // (the common case) see the same warning dots.
        await enrichNodesWithFeasibility();

        // Cache the result. q_typical AND feasibility_status are
        // stamped onto node objects before caching so a cache hit
        // also serves the enriched data.
        TreeState.dimensionHierarchies[dimensionId] = {
            rootNodes: TreeState.rootNodes,
            flatNodes: new Map(TreeState.flatNodes)
        };

    } catch (error) {
        console.error('Failed to load dimension hierarchy:', error);
        TreeState.rootNodes = [];
        TreeState.flatNodes = new Map();
    } finally {
        showLoading(false);
    }
}

/**
 * Invalidate the cache for a specific dimension
 * @param {number} dimensionId - Dimension ID to invalidate
 */
function invalidateDimensionCache(dimensionId) {
    delete TreeState.dimensionHierarchies[dimensionId];
}

// =========================================================================
// Tree Rendering
// =========================================================================

function renderTree() {
    const container = document.getElementById('tree-container');
    const emptyState = document.getElementById('tree-empty');

    if (TreeState.rootNodes.length === 0) {
        container.innerHTML = '';
        emptyState.classList.remove('hidden');
    } else {
        emptyState.classList.add('hidden');
        const html = renderNodes(TreeState.rootNodes, 1);
        if (TreeState.searchVisibleIds && html.trim() === '') {
            container.innerHTML = '<div class="tree-search-no-results">No subjects match your filter.</div>';
        } else {
            container.innerHTML = html;
        }
    }
}

function renderNodes(nodes, level) {
    let filtered = nodes;
    if (TreeState.searchVisibleIds) {
        filtered = nodes.filter(n => TreeState.searchVisibleIds.has(n.id));
    }
    return filtered.map(node => renderNode(node, level)).join('');
}

function renderNode(node, level) {
    const hasChildren = node.children && node.children.length > 0;
    const isExpanded = TreeState.expandedNodes.has(node.id);
    const isSelected = TreeState.selectedNodeId === node.id;
    
    // Handle hybrid weight system
    const hasRelativeWeight = node.relative_weight !== null && node.relative_weight !== undefined;
    const hasAbsoluteWeight = node.exam_weight_low !== null && node.exam_weight_low !== undefined;
    const weight = hasRelativeWeight ? node.relative_weight : (node.weight || node.exam_weight_low || 0);
    const isLocked = node.weight_locked || false;
    const weightSource = node.weight_source || 'user_defined';
    
    // Weight display with range if available
    let weightDisplay = `${weight.toFixed(1)}%`;
    if (hasAbsoluteWeight && node.exam_weight_high && node.exam_weight_low !== node.exam_weight_high) {
        weightDisplay = `${node.exam_weight_low}–${node.exam_weight_high}%`;
    } else if (hasRelativeWeight) {
        weightDisplay = `${weight.toFixed(1)}% (rel)`;
    }

    // Stage 5 — dual unit display.
    // When the exam declares a planning baseline (``length_kind !==
    // 'unknown'``), the polyhierarchy-aware
    // ``get_subjects_with_effective_weights`` attaches a ``q_typical``
    // field on each node's ``weight`` dict (the tree-editor loader
    // unpacks that onto ``node.q_typical``). Render the integer
    // question count next to the percentage so the user sees
    // ``XX.X% • ~N q``. When ``q_typical`` is null/undefined we fall
    // back to the percentage-only display (legacy behavior + the
    // ``length_kind='unknown'`` degradation contract per design §7.5).
    //
    // Stage 8 — adaptive (CAT) exams (NCLEX-RN etc.) render the q
    // value as a float with a "(planning estimate)" qualifier so the
    // user knows the CAT has no fixed precision. ``node.is_adaptive``
    // is stamped by ``enrichNodesWithQuestionCounts`` (uniform across
    // the exam context).
    const qTypical = node.q_typical;
    if (qTypical !== null && qTypical !== undefined) {
        const isAdaptive = !!node.is_adaptive;
        const qLabel = isAdaptive
            ? `~${Number(qTypical).toFixed(1)} q's (planning estimate)`
            : (Number.isInteger(qTypical)
                ? `~${qTypical} q's`
                : `~${qTypical.toFixed(1)} q's`);
        weightDisplay = `${weightDisplay} • ${qLabel}`;
    }
    
    const weightClass = weight >= 30 ? 'high' : weight >= 10 ? 'medium' : 'low';
    const icon = hasChildren ? '📁' : '📄';
    const levelName = TreeState.hierarchyLevels[level - 1]?.level_name || `Level ${level}`;
    
    // Lock and confidence indicators
    const lockIcon = isLocked ? '🔒' : '';
    const confidenceClass = weightSource === 'official' ? 'confidence-high' : 
                           weightSource === 'derived' ? 'confidence-medium' : 'confidence-low';
    
    // NOTE (polyhierarchy migration — partially landed): the polyhierarchy backend
    // now ships multi-parent leaves under each parent (with `is_alias_appearance=true`
    // on the non-primary appearances — see the alias-chip render below). That means
    // `tree-node-${node.id}` and `id="name-${node.id}"` are no longer unique in the
    // DOM for multi-parent nodes — each appearance gets the same data-id and HTML id.
    // For testid locators, the pattern needs to extend to
    // `tree-node-${node.id}-under-${parentId}` so tests can disambiguate the primary
    // appearance from the alias appearances. That requires threading the parent id
    // into renderNode/renderNodes, which isn't done here. Tracking as a follow-up;
    // current consumers (selectNode/toggleNode/etc.) all key off node.id only and
    // are insensitive to which appearance was clicked, so the duplication isn't
    // currently functionally broken — just an HTML-validity / locator-ambiguity
    // issue. See docs/testing/UI_AUDIT.md and POLYHIERARCHY_MIGRATION.md §7.1.
    return `
        <div class="tree-node ${isExpanded ? 'expanded' : ''} ${isSelected ? 'selected' : ''} ${isLocked ? 'locked' : ''}"
             data-id="${node.id}"
             data-level="${level}"
             data-testid="tree-node-${node.id}">
            <div class="tree-node-content"
                 data-testid="tree-node-content-${node.id}"
                 onclick="selectNode(${node.id})"
                 ondblclick="startInlineEdit(${node.id})">
                <button class="tree-toggle ${hasChildren ? '' : 'empty'}"
                        data-testid="tree-toggle-${node.id}"
                        onclick="event.stopPropagation(); toggleNode(${node.id})">
                    <span class="tree-toggle-icon">▶</span>
                </button>
                <span class="tree-node-icon">${icon}</span>
                <span class="tree-node-name" id="name-${node.id}" data-testid="tree-node-name-${node.id}">${TreeState.searchMatchIds.has(node.id) ? highlightSearchMatch(node.name, TreeState.searchQuery) : escapeHtml(node.name)}</span>
                ${node.is_alias_appearance ? `
                    <span class="tree-node-alias-chip"
                          data-testid="tree-node-alias-${node.id}"
                          title="This subject also appears under another parent. The primary location holds its descendants and weight settings.">
                        also here
                    </span>
                ` : (TreeState.appearanceCount.get(node.id) || 1) > 1 ? `
                    <span class="tree-node-multi-parent-chip"
                          data-testid="tree-node-multi-parent-${node.id}"
                          title="This subject lives in ${TreeState.appearanceCount.get(node.id)} places. Click to manage parents."
                          onclick="event.stopPropagation(); openParentsManagerFor(${node.id})">
                        <span class="tree-node-multi-parent-chip-arrow">↗</span>${TreeState.appearanceCount.get(node.id)}
                    </span>
                ` : ''}
                ${node.feasibility_status && node.feasibility_status !== 'ok' ? `
                    <span class="tree-row-warning-dot"
                          data-testid="tree-row-warning-dot-${node.id}"
                          data-feasibility-status="${node.feasibility_status}"
                          title="${node.feasibility_status === 'infeasible'
                              ? "Children's minimums don't fit in this parent's maximum. Click to inspect."
                              : node.feasibility_status === 'over'
                              ? "Children's weights exceed this parent's range. Click to inspect."
                              : "Children's weights leave room under this parent. Click to inspect."}"
                          onclick="event.stopPropagation(); selectNode(${node.id})">⚠</span>
                ` : ''}
                <span class="tree-node-level">${levelName}</span>
                <span class="tree-node-weight ${weightClass} ${confidenceClass} ${node.is_anchor ? 'anchored' : ''}" data-testid="tree-node-weight-${node.id}" title="${getWeightTooltip(node)}" ${node.primary_edge_id ? `data-edge-id="${node.primary_edge_id}"` : ''}>
                    ${lockIcon}${node.is_anchor ? '<span class="weight-anchor-pin filled" data-testid="tree-node-anchor-pin-' + node.id + '" title="Anchored — won\'t auto-adjust on rebalance">⚓</span>' : ''}${weightDisplay}
                </span>
                <div class="tree-node-actions">
                    <button class="tree-action-btn" data-testid="tree-node-add-child-${node.id}" onclick="event.stopPropagation(); addChild(${node.id})" title="Add Child">+</button>
                    <button class="tree-action-btn danger" data-testid="tree-node-delete-${node.id}" onclick="event.stopPropagation(); confirmDeleteNode(${node.id})" title="Delete">🗑️</button>
                </div>
            </div>
            ${hasChildren ? `
                <div class="tree-node-children" data-testid="tree-node-children-${node.id}">
                    ${renderNodes(node.children, level + 1)}
                </div>
            ` : ''}
        </div>
    `;
}

/**
 * Generate tooltip text for weight display
 */
function getWeightTooltip(node) {
    const parts = [];
    
    if (node.weight_source) {
        const sourceLabels = {
            'official': 'Official Exam Weight',
            'derived': 'Derived from Official',
            'user_estimate': 'User Estimate',
            'user_defined': 'User Defined'
        };
        parts.push(sourceLabels[node.weight_source] || node.weight_source);
    }
    
    if (node.exam_weight_low !== null && node.exam_weight_high !== null) {
        if (node.exam_weight_low !== node.exam_weight_high) {
            parts.push(`Range: ${node.exam_weight_low}%–${node.exam_weight_high}%`);
        } else {
            parts.push(`Fixed: ${node.exam_weight_low}%`);
        }
    }
    
    if (node.relative_weight !== null && node.relative_weight !== undefined) {
        parts.push(`Relative: ${node.relative_weight}%`);
    }
    
    if (node.weight_locked) {
        parts.push('🔒 Locked');
    }
    
    if (node.exam_source) {
        parts.push(`Source: ${node.exam_source}`);
    }

    // Stage 5 — dual unit display in the tooltip body.
    // Mirrors the chip text but spells the unit out. ``q_typical`` is
    // null/undefined when the exam is ``length_kind='unknown'``; in
    // that case we don't add the suffix at all so the tooltip stays
    // pure-percentage.
    //
    // Stage 8 — adaptive (CAT) exams use the float + "(planning
    // estimate)" formatter to mirror the chip text, so the tooltip
    // and the chip carry the same wording.
    if (node.q_typical !== null && node.q_typical !== undefined) {
        const isAdaptive = !!node.is_adaptive;
        const qLabel = isAdaptive
            ? `~${Number(node.q_typical).toFixed(1)} q's (planning estimate)`
            : (Number.isInteger(node.q_typical)
                ? `~${node.q_typical} q's`
                : `~${node.q_typical.toFixed(1)} q's`);
        parts.push(`Planning baseline: ${qLabel}`);
    }

    return parts.join(' | ');
}

function updateStats() {
    const nodeCount = TreeState.flatNodes.size;
    const totalWeight = TreeState.rootNodes.reduce((sum, node) => sum + (node.weight || node.exam_weight_low || 0), 0);
    
    document.getElementById('node-count').textContent = `${nodeCount} subject${nodeCount !== 1 ? 's' : ''}`;
    document.getElementById('total-weight').textContent = `Root Total: ${totalWeight.toFixed(1)}%`;
    
    // Update weight config badge
    updateWeightConfigBadge();
}

/**
 * Update the weight configuration badge in the toolbar
 */
async function updateWeightConfigBadge() {
    const badge = document.getElementById('weight-config-badge');
    if (!badge) return;
    
    try {
        const config = await api.getWeightConfig(TreeState.examContextId);
        
        const badgeIcon = badge.querySelector('.badge-icon');
        const badgeText = badge.querySelector('.badge-text');
        
        if (config.has_official_weights) {
            badge.classList.add('has-official');
            badgeIcon.textContent = '📋';
            
            let text = `Official (${config.official_weight_count})`;
            if (config.source_name) {
                text = config.source_name.length > 20 
                    ? config.source_name.substring(0, 20) + '...' 
                    : config.source_name;
            }
            badgeText.textContent = text;
            badge.title = `${config.official_weight_count} official weights from ${config.source_name || 'unknown source'}`;
        } else {
            badge.classList.remove('has-official');
            badgeIcon.textContent = '⚙️';
            badgeText.textContent = 'User Defined';
            badge.title = 'No official weights imported';
        }
    } catch (error) {
        console.warn('Could not update weight config badge:', error);
    }
}

// =========================================================================
// Node Selection & Details Panel
// =========================================================================

function selectNode(nodeId) {
    const node = TreeState.flatNodes.get(nodeId);
    const wasAlreadySelected = TreeState.selectedNodeId === nodeId;
    
    TreeState.selectedNodeId = nodeId;
    
    // Update tree visual selection
    document.querySelectorAll('.tree-node.selected').forEach(el => el.classList.remove('selected'));
    const nodeEl = document.querySelector(`.tree-node[data-id="${nodeId}"]`);
    if (nodeEl) nodeEl.classList.add('selected');
    
    // If the node has children, toggle expand/collapse
    // Option D: clicking a node both selects AND expands if it has children
    if (node && node.children && node.children.length > 0) {
        if (wasAlreadySelected) {
            // If already selected, toggle the expand state
            toggleNode(nodeId);
        } else {
            // If newly selected, expand it
            toggleNode(nodeId, true); // force expand
        }
    }
    
    // Update details panel
    showNodeDetails(nodeId);
}

function showExamOverview() {
    const placeholder = document.getElementById('details-placeholder');
    const content = document.getElementById('details-content');
    
    // Hide node details, show placeholder with overview
    content.classList.add('hidden');
    placeholder.classList.remove('hidden');
    
    // Calculate stats
    const totalNodes = TreeState.flatNodes.size;
    const rootNodes = TreeState.rootNodes;
    const totalRootWeight = rootNodes.reduce((sum, n) => sum + (n.weight || n.exam_weight_low || 0), 0);
    
    // Count nodes by level
    const levelCounts = {};
    TreeState.flatNodes.forEach((node) => {
        const level = getNodeLevel(node);
        const levelName = TreeState.hierarchyLevels[level - 1]?.level_name || `Level ${level}`;
        levelCounts[levelName] = (levelCounts[levelName] || 0) + 1;
    });
    
    // Generate pie chart SVG for root nodes
    const pieChart = generatePieChart(rootNodes);
    
    // Build overview HTML
    placeholder.innerHTML = `
        <div class="exam-overview">
            <h3 class="overview-title">📊 Exam Overview</h3>
            
            <div class="overview-stats">
                <div class="overview-stat">
                    <span class="overview-stat-value">${totalNodes}</span>
                    <span class="overview-stat-label">Total Subjects</span>
                </div>
                <div class="overview-stat">
                    <span class="overview-stat-value">${rootNodes.length}</span>
                    <span class="overview-stat-label">Root Topics</span>
                </div>
                <div class="overview-stat">
                    <span class="overview-stat-value">${totalRootWeight.toFixed(1)}%</span>
                    <span class="overview-stat-label">Total Weight</span>
                </div>
            </div>
            
            <div class="overview-section">
                <h4 class="overview-section-title">Subjects by Level</h4>
                <div class="level-counts">
                    ${Object.entries(levelCounts).map(([level, count]) => `
                        <div class="level-count-item">
                            <span class="level-count-name">${level}</span>
                            <span class="level-count-value">${count}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
            
            ${rootNodes.length > 0 ? `
                <div class="overview-section">
                    <h4 class="overview-section-title">Weight Distribution</h4>
                    <div class="pie-chart-container">
                        ${pieChart}
                    </div>
                    <div class="pie-legend">
                        ${rootNodes.map((node, i) => {
                            const weight = node.weight || node.exam_weight_low || 0;
                            const color = getPieColor(i);
                            return `
                                <div class="pie-legend-item" onclick="selectNode(${node.id})">
                                    <span class="pie-legend-color" style="background: ${color}"></span>
                                    <span class="pie-legend-name">${escapeHtml(node.name)}</span>
                                    <span class="pie-legend-value">${weight.toFixed(1)}%</span>
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
            ` : `
                <div class="overview-empty">
                    <p>No subjects yet. Click "+ Add Root Subject" to get started!</p>
                </div>
            `}
        </div>
    `;
}

function getPieColor(index) {
    const colors = [
        '#2563eb', '#7c3aed', '#059669', '#d97706', '#dc2626',
        '#0891b2', '#4f46e5', '#16a34a', '#ca8a04', '#e11d48',
        '#06b6d4', '#8b5cf6', '#22c55e', '#eab308', '#f43f5e'
    ];
    return colors[index % colors.length];
}

function generatePieChart(nodes) {
    if (nodes.length === 0) return '';
    
    const total = nodes.reduce((sum, n) => sum + (n.weight || n.exam_weight_low || 0), 0);
    if (total === 0) return '<p class="text-muted">No weights assigned</p>';
    
    const size = 200;
    const center = size / 2;
    const radius = 80;
    
    let paths = '';
    let currentAngle = -90; // Start from top
    
    nodes.forEach((node, i) => {
        const weight = node.weight || node.exam_weight_low || 0;
        const percentage = weight / total;
        const angle = percentage * 360;
        
        if (angle > 0) {
            const startAngle = currentAngle;
            const endAngle = currentAngle + angle;
            
            const startRad = (startAngle * Math.PI) / 180;
            const endRad = (endAngle * Math.PI) / 180;
            
            const x1 = center + radius * Math.cos(startRad);
            const y1 = center + radius * Math.sin(startRad);
            const x2 = center + radius * Math.cos(endRad);
            const y2 = center + radius * Math.sin(endRad);
            
            const largeArc = angle > 180 ? 1 : 0;
            
            const pathData = [
                `M ${center} ${center}`,
                `L ${x1} ${y1}`,
                `A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2}`,
                'Z'
            ].join(' ');
            
            paths += `<path d="${pathData}" fill="${getPieColor(i)}" 
                           class="pie-slice" data-node-id="${node.id}"
                           onclick="selectNode(${node.id})"
                           style="cursor: pointer;">
                        <title>${escapeHtml(node.name)}: ${weight.toFixed(1)}%</title>
                      </path>`;
            
            currentAngle = endAngle;
        }
    });
    
    return `
        <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" class="pie-chart">
            ${paths}
            <circle cx="${center}" cy="${center}" r="40" fill="var(--bg-primary, white)" />
            <text x="${center}" y="${center}" text-anchor="middle" dy="0.35em"
                  font-size="14" font-weight="600" fill="var(--text-primary, #374151)">
                ${total.toFixed(0)}%
            </text>
        </svg>
    `;
}

function showNodeDetails(nodeId) {
    const node = TreeState.flatNodes.get(nodeId);
    if (!node) return;

    const placeholder = document.getElementById('details-placeholder');
    const content = document.getElementById('details-content');

    placeholder.classList.add('hidden');
    content.classList.remove('hidden');

    // Basic info
    const level = getNodeLevel(node);
    const levelName = TreeState.hierarchyLevels[level - 1]?.level_name || `Level ${level}`;

    document.getElementById('detail-name').textContent = node.name;
    document.getElementById('detail-level').textContent = levelName;
    document.getElementById('edit-name').value = node.name;

    // Render the subtitle (level · parents · dimension on multi-dim).
    // Parent-count is filled in lazily when loadParentsForCurrentNode
    // resolves below — start with just level + dimension so the panel
    // doesn't flicker an empty subtitle on selection.
    renderDetailSubtitle(nodeId, /* parentCount */ null);

    // Parents section (polyhierarchy). Always loads — single-parent
    // nodes still surface here so users can promote-to-multi-parent
    // by adding a second.
    loadParentsForCurrentNode(nodeId);
    closeAddParentPicker();

    // Weight - basic values for fallback
    const weight = node.weight || node.exam_weight_low || 0;
    TreeState.originalWeight = weight;

    // Only set these if elements exist (they may be replaced by enhanced weight editor)
    const weightSlider = document.getElementById('weight-slider');
    const weightValue = document.getElementById('weight-value');
    if (weightSlider) weightSlider.value = weight;
    if (weightValue) weightValue.value = weight;

    renderSiblingsChart(node);
    renderChildrenList(node);

    // Load aliases preview
    loadAliasesPreview(nodeId);

    // Initialize enhanced weight editor if available
    if (typeof initWeightEditor === 'function') {
        initWeightEditor(node, TreeState.examContext);
    }
}

/**
 * Load and display aliases preview for a subject
 * @param {number} nodeId - Subject node ID
 */
async function loadAliasesPreview(nodeId) {
    const previewEl = document.getElementById('aliases-preview');
    if (!previewEl) return;

    try {
        const aliases = await api.getAliasesForSubject(nodeId);

        if (!aliases || aliases.length === 0) {
            previewEl.innerHTML = '<span class="text-muted text-sm">No aliases</span>';
            return;
        }

        // Show up to 3 aliases with a count if more exist
        const displayed = aliases.slice(0, 3);
        const remaining = aliases.length - 3;

        const aliasHtml = displayed.map(a =>
            `<span class="alias-chip alias-type-${a.alias_type}">${escapeHtml(a.alias_name)}</span>`
        ).join('');

        const moreHtml = remaining > 0
            ? `<span class="alias-more">+${remaining} more</span>`
            : '';

        previewEl.innerHTML = aliasHtml + moreHtml;

    } catch (error) {
        console.error('Error loading aliases:', error);
        previewEl.innerHTML = '<span class="text-muted text-sm">Failed to load</span>';
    }
}

// ============================================================================
// Polyhierarchy: parent management in the details panel
// ============================================================================
//
// The details panel's "Parents" section lets a user view all parent edges of
// the selected node, switch which one is primary (the canonical breadcrumb
// path), remove a non-primary edge, and add a new parent via a typeahead
// picker that disables cycle-creating choices upfront. Backed by the bridge
// slots api.{getParents, addParent, removeParent, setPrimaryParent} and
// api.searchSubjects (already in use elsewhere for the entry-form subject
// typeahead).
//
// State: TreeState.parentsCache (Map nodeId -> [{edge_id, parent_id,
// parent_name, is_primary, display_order}]). Lazy-populated on selection;
// invalidated after every mutation so the next render sees fresh data.

/**
 * Compute the set of subject_node ids that would create a cycle if added
 * as a parent of `nodeId`. A cycle would form if the prospective parent
 * is already a descendant of nodeId. Walked client-side from TreeState
 * (no bridge call) by finding the canonical primary appearance of
 * nodeId — alias appearances have empty children per the polyhierarchy-
 * aware get_subject_hierarchy backend — and collecting every descendant
 * id under it.
 */
function getDescendantIds(nodeId) {
    const out = new Set();
    function walk(node) {
        if (!node || !node.children) return;
        for (const child of node.children) {
            out.add(child.id);
            walk(child);
        }
    }
    // Find the canonical primary appearance. The flatNodes map only
    // stores one ref per id (whichever was visited last), so we walk
    // rootNodes to find an appearance whose children are populated.
    function findPrimary(nodes) {
        for (const n of nodes) {
            if (n.id === nodeId && (n.children?.length ?? 0) > 0) return n;
            const hit = findPrimary(n.children || []);
            if (hit) return hit;
        }
        // Fallback: any appearance, even if childless (single-parent
        // leaf with no descendants).
        for (const n of nodes) {
            if (n.id === nodeId) return n;
            const hit = findPrimary(n.children || []);
            if (hit) return hit;
        }
        return null;
    }
    const root = findPrimary(TreeState.rootNodes);
    walk(root);
    return out;
}

/**
 * Fetch (or load from cache) the parents of `nodeId` and render the
 * Parents section. Safe to call when nothing is selected — bails early.
 */
async function loadParentsForCurrentNode(nodeId) {
    const listEl = document.getElementById('parents-list');
    const countEl = document.getElementById('parents-count-badge');
    if (!listEl || !countEl) return;

    listEl.innerHTML = '<p class="text-muted text-sm">Loading…</p>';
    countEl.textContent = '—';

    try {
        let parents = TreeState.parentsCache.get(nodeId);
        if (!parents) {
            parents = await api.getParents(nodeId);
            TreeState.parentsCache.set(nodeId, parents);
        }
        renderParentsSection(nodeId, parents);
    } catch (error) {
        console.error('Failed to load parents:', error);
        listEl.innerHTML = '<p class="text-muted text-sm">Failed to load parents.</p>';
        countEl.textContent = '!';
    }
}

/**
 * Update the details-panel subtitle with level type, parent count, and
 * (on multi-dim exams) the active dimension's name. Called twice during
 * a selection: first synchronously from showNodeDetails with
 * ``parentCount=null`` so the level + dimension show immediately, then
 * again from renderParentsSection once api.getParents has resolved so
 * the parent count joins the row.
 *
 * Subtitle pieces are rendered as separate spans with classes so the
 * CSS dot-separator (``.details-subtitle > * + *::before``) can place a
 * ``·`` between them without us having to manage delimiters in JS.
 */
function renderDetailSubtitle(nodeId, parentCount) {
    const subtitle = document.getElementById('detail-subtitle');
    if (!subtitle) return;
    const node = TreeState.flatNodes.get(nodeId);
    if (!node) {
        subtitle.innerHTML = '';
        return;
    }
    const level = getNodeLevel(node);
    const levelName =
        TreeState.hierarchyLevels[level - 1]?.level_name || `Level ${level}`;

    const parts = [
        `<span class="details-subtitle-level"
               id="detail-level"
               data-testid="tree-detail-level">${escapeHtml(levelName)}</span>`,
    ];

    if (parentCount !== null && parentCount !== undefined) {
        const noun = parentCount === 1 ? 'parent' : 'parents';
        parts.push(
            `<span class="details-subtitle-parents"
                   data-testid="tree-detail-parent-count">${parentCount} ${noun}</span>`
        );
    }

    if (TreeState.usesDimensions && TreeState.currentDimensionId) {
        const dim = (TreeState.dimensions || []).find(
            d => d.id === TreeState.currentDimensionId
        );
        if (dim?.name) {
            parts.push(
                `<span class="details-subtitle-dimension"
                       data-testid="tree-detail-dimension">in ${escapeHtml(dim.name)}</span>`
            );
        }
    }

    subtitle.innerHTML = parts.join('');
}

/**
 * Build the parent-row list HTML and stamp it into #parents-list.
 * Each row shows the parent name, ancestor breadcrumb (if available),
 * a primary-indicator marker (★ for primary, ○ for non-primary that
 * promotes on click), and a remove button (disabled on the primary edge).
 */
function renderParentsSection(nodeId, parents) {
    const listEl = document.getElementById('parents-list');
    const countEl = document.getElementById('parents-count-badge');
    if (!listEl || !countEl) return;

    countEl.textContent = String(parents.length || 0);

    // Refresh the panel-header subtitle now that we know the real count
    // (showNodeDetails kicked off this load with parentCount=null).
    renderDetailSubtitle(nodeId, parents.length || 0);

    if (!parents || parents.length === 0) {
        listEl.innerHTML = `
            <p class="text-muted text-sm">
                Root subject — no parents.
                Adding a parent here makes this a child of another subject.
            </p>
        `;
        return;
    }

    listEl.innerHTML = parents.map(p => {
        const breadcrumbPath = buildAncestorPathFor(p.parent_id);
        const isPrimary = !!p.is_primary;
        return `
            <div class="parent-row ${isPrimary ? 'is-primary' : ''}"
                 data-edge-id="${p.edge_id}"
                 data-parent-id="${p.parent_id}"
                 data-testid="tree-parent-row-${p.parent_id}">
                <button class="parent-row-marker"
                        data-testid="tree-parent-marker-${p.parent_id}"
                        title="${isPrimary ? 'Primary parent — used for breadcrumbs and rollups' : 'Click to make this the primary parent'}"
                        ${isPrimary ? 'disabled' : ''}
                        onclick="switchPrimaryParentTo(${nodeId}, ${p.parent_id})">
                    ${isPrimary ? '★' : '○'}
                </button>
                <div class="parent-row-content">
                    <div class="parent-row-name">${escapeHtml(p.parent_name)}</div>
                    ${breadcrumbPath ? `<div class="parent-row-path">${escapeHtml(breadcrumbPath)}</div>` : ''}
                    <div class="parent-row-meta">
                        ${isPrimary ? 'primary · canonical breadcrumb' : 'alias · also-here appearance'}
                    </div>
                </div>
                <div class="parent-row-actions">
                    <button class="parent-row-action danger"
                            data-testid="tree-parent-remove-${p.parent_id}"
                            title="${isPrimary ? 'Cannot remove the primary parent — switch primary first.' : 'Remove this parent edge'}"
                            ${isPrimary ? 'disabled' : ''}
                            onclick="confirmRemoveParentEdge(${nodeId}, ${p.edge_id}, ${p.parent_id})">
                        ✕
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * Walk TreeState.flatNodes upward from `parentId` to build a "Grand-
 * parent › Parent" style breadcrumb path string. Best-effort: relies on
 * the legacy node._parent reference set by buildFlatNodeMap, which for
 * multi-parent ancestors picks one path arbitrarily (whichever was
 * visited last). Acceptable here — the breadcrumb is for orientation,
 * not a contractual rollup path.
 */
function buildAncestorPathFor(parentId) {
    const node = TreeState.flatNodes.get(parentId);
    if (!node) return '';
    const ancestors = [];
    let cur = node._parent;
    let depth = 0;
    while (cur && depth < 10) {  // bounded for safety
        ancestors.unshift(cur.name);
        cur = cur._parent;
        depth++;
    }
    return ancestors.join(' › ');
}

/**
 * Promote a non-primary edge to primary. Optimistically updates the
 * UI then refreshes from the server.
 */
async function switchPrimaryParentTo(childId, newParentId) {
    try {
        await api.setPrimaryParent(childId, newParentId);
        TreeState.parentsCache.delete(childId);
        await loadParentsForCurrentNode(childId);
        // The tree itself needs to re-render: the canonical primary
        // appearance just changed, which affects which appearance
        // carries the subtree. Reveal the new primary location so the
        // user sees what changed.
        await refreshHierarchyAndKeepSelection({ revealParentId: newParentId });
    } catch (error) {
        console.error('Failed to switch primary parent:', error);
        showError(`Could not switch primary parent: ${error.message}`);
    }
}

/**
 * Inline confirmation flow for removing a non-primary parent edge.
 * The clicked row is rewritten in place to show "Remove from this
 * parent? [Yes] [Cancel]" — no separate modal. The original HTML is
 * stashed in this module-scoped Map (not the DOM attribute) so quotes
 * and other markup survive the round-trip.
 */
const _parentRowOriginalHtml = new Map();

function confirmRemoveParentEdge(childId, edgeId, parentId) {
    const row = document.querySelector(`.parent-row[data-edge-id="${edgeId}"]`);
    if (!row) return;
    _parentRowOriginalHtml.set(edgeId, row.innerHTML);
    row.classList.add('confirming');
    row.innerHTML = `
        <span class="parent-row-confirm-text">Remove this parent edge? The subject stays — only this link goes away.</span>
        <div class="parent-row-actions">
            <button class="btn btn-secondary btn-sm"
                    data-testid="tree-parent-remove-cancel-${parentId}"
                    onclick="restoreParentRow(${edgeId})">
                Cancel
            </button>
            <button class="btn btn-danger btn-sm"
                    data-testid="tree-parent-remove-confirm-${parentId}"
                    onclick="performRemoveParentEdge(${childId}, ${edgeId})">
                Yes, remove
            </button>
        </div>
    `;
}

/** Restore a parent row's original HTML after a cancelled remove. */
function restoreParentRow(edgeId) {
    const row = document.querySelector(`.parent-row[data-edge-id="${edgeId}"]`);
    const original = _parentRowOriginalHtml.get(edgeId);
    if (!row || original === undefined) return;
    row.classList.remove('confirming');
    row.innerHTML = original;
    _parentRowOriginalHtml.delete(edgeId);
}

async function performRemoveParentEdge(childId, edgeId) {
    try {
        await api.removeParent(edgeId);
        TreeState.parentsCache.delete(childId);
        await loadParentsForCurrentNode(childId);
        await refreshHierarchyAndKeepSelection();
    } catch (error) {
        console.error('Failed to remove parent edge:', error);
        showError(`Could not remove parent: ${error.message}`);
    }
}

/**
 * Reload the hierarchy (so the tree reflects added/removed/reprimary'd
 * edges) and re-select the current node so the details panel doesn't
 * jump back to the placeholder.
 *
 * If ``revealParentId`` is supplied, the chain from a tree root down
 * to that parent is force-expanded after the reload, then the newly-
 * inserted child row under that parent is scrolled into view and
 * briefly flashed. Without this, an "add parent" or "switch primary"
 * action silently rewires the tree but leaves the visible side
 * collapsed — the user sees the side panel update but the tree
 * appears unchanged because the new appearance lives somewhere they
 * never expanded.
 */
async function refreshHierarchyAndKeepSelection({ revealParentId } = {}) {
    const keepId = TreeState.selectedNodeId;

    // For multi-dimensional exams, loadHierarchy routes to
    // loadDimensionHierarchy which short-circuits on TreeState
    // .dimensionHierarchies[dimId] when the cache is populated — so
    // without busting it here, every parent-edge mutation would refresh
    // the side panel but leave the tree painted from the pre-mutation
    // snapshot. Clear ALL cached dimensions: a primary-switch in one
    // dimension can shuffle subtree shape in another (the canonical
    // appearance moves), and polyhierarchy edges don't carry dimension
    // identity at the bridge layer, so a single clear is the safe
    // bound. Cost is one extra getDimensionHierarchy call per dimension
    // the user later visits; cheap relative to the cost of a stale tree.
    if (TreeState.usesDimensions) {
        TreeState.dimensionHierarchies = {};
    }

    await loadHierarchy();

    if (revealParentId) {
        const path = findPathToNodeId(TreeState.rootNodes, revealParentId);
        if (path) {
            for (const ancestor of path) {
                TreeState.expandedNodes.add(ancestor.id);
            }
        }
    }

    if (keepId) {
        TreeState.selectedNodeId = keepId;
        renderTree();
        showNodeDetails(keepId);
        if (revealParentId) {
            // Render then scroll/flash on the next frame so the DOM is
            // settled before we go looking for the new row.
            requestAnimationFrame(() =>
                flashChildUnderParent(keepId, revealParentId)
            );
        }
    }
}

/**
 * Walk the tree depth-first and return the list of nodes from root to
 * (and including) the node with id == targetId. Returns null if the id
 * isn't in the tree.
 */
function findPathToNodeId(nodes, targetId, path = []) {
    for (const n of nodes || []) {
        const next = [...path, n];
        if (n.id === targetId) return next;
        const hit = findPathToNodeId(n.children || [], targetId, next);
        if (hit) return hit;
    }
    return null;
}

/**
 * Find the tree-node DOM row for ``childId`` whose direct DOM parent's
 * ``data-id`` matches ``parentId`` — i.e. the appearance of the child
 * that lives under the just-added parent — scroll it into view, and
 * briefly flash it via the .tree-node-just-added CSS class.
 *
 * If the row can't be found (race or unexpected DOM shape) we silently
 * no-op rather than throw — the data update succeeded; visual feedback
 * is a polish, not a correctness contract.
 */
function flashChildUnderParent(childId, parentId) {
    const parentRow = document.querySelector(
        `.tree-node[data-id="${parentId}"]`
    );
    if (!parentRow) return;
    const childRow = parentRow.querySelector(
        `:scope > .tree-node-children > .tree-node[data-id="${childId}"]`
    );
    if (!childRow) return;
    childRow.classList.add('tree-node-just-added');
    childRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(
        () => childRow.classList.remove('tree-node-just-added'),
        2400
    );
}

/**
 * Open the typeahead picker UI inside the Parents section.
 */
function openAddParentPicker() {
    const btn = document.getElementById('btn-add-parent');
    const picker = document.getElementById('parents-picker');
    if (!btn || !picker) return;
    btn.classList.add('hidden');
    picker.classList.remove('hidden');
    const input = document.getElementById('parents-picker-input');
    if (input) {
        input.value = '';
        renderParentPickerResults([], 'Start typing to search…');
        // Defer focus so the show transition runs.
        setTimeout(() => input.focus(), 0);
    }
}

function closeAddParentPicker() {
    const btn = document.getElementById('btn-add-parent');
    const picker = document.getElementById('parents-picker');
    if (!btn || !picker) return;
    picker.classList.add('hidden');
    btn.classList.remove('hidden');
}

/**
 * Search subjects matching `query` and render them as picker results.
 * Each result is annotated with whether it's selectable and, if not,
 * why ("already a parent" / "would create a cycle" / "self").
 */
let _pickerSearchSeq = 0;
async function searchParentPicker(query, childId) {
    const seq = ++_pickerSearchSeq;
    if (!query || query.trim().length < 1) {
        renderParentPickerResults([], 'Start typing to search…');
        return;
    }
    try {
        const results = await api.searchSubjects(
            TreeState.examContextId, query.trim(), 30
        );
        if (seq !== _pickerSearchSeq) return;  // stale response

        const currentParents = TreeState.parentsCache.get(childId) || [];
        const currentParentIds = new Set(currentParents.map(p => p.parent_id));
        const descendants = getDescendantIds(childId);

        const annotated = (results || []).map(r => {
            let disabledReason = null;
            if (r.id === childId) {
                disabledReason = 'Self — cannot be its own parent.';
            } else if (currentParentIds.has(r.id)) {
                disabledReason = 'Already a parent of this subject.';
            } else if (descendants.has(r.id)) {
                disabledReason = 'Would create a cycle — this subject is a descendant.';
            }
            return { ...r, _disabledReason: disabledReason };
        });

        renderParentPickerResults(annotated, null, childId);
    } catch (error) {
        console.error('Parent search failed:', error);
        renderParentPickerResults([], 'Search failed. Try again.');
    }
}

function renderParentPickerResults(results, emptyMessage, childId) {
    const el = document.getElementById('parents-picker-results');
    if (!el) return;
    if (!results || results.length === 0) {
        el.innerHTML = `<p class="text-muted text-sm parents-picker-empty">${escapeHtml(emptyMessage || 'No matches.')}</p>`;
        return;
    }
    el.innerHTML = results.map(r => {
        const disabled = !!r._disabledReason;
        const onclick = disabled
            ? ''
            : `onclick="addParentEdgeFromPicker(${childId}, ${r.id})"`;
        return `
            <div class="parents-picker-result ${disabled ? 'disabled' : ''}"
                 data-result-id="${r.id}"
                 data-testid="tree-parents-picker-result-${r.id}"
                 ${onclick}>
                <span class="parents-picker-result-name">${escapeHtml(r.name)}</span>
                ${r.path ? `<span class="parents-picker-result-path">${escapeHtml(r.path)}</span>` : ''}
                ${disabled ? `<span class="parents-picker-result-reason" title="${escapeHtml(r._disabledReason)}">${escapeHtml(r._disabledReason)}</span>` : ''}
            </div>
        `;
    }).join('');
}

async function addParentEdgeFromPicker(childId, parentId) {
    try {
        await api.addParent(childId, parentId, false);
        TreeState.parentsCache.delete(childId);
        closeAddParentPicker();
        await loadParentsForCurrentNode(childId);
        // Reveal the new appearance — without this the tree silently
        // re-renders but the new row is hidden inside the collapsed
        // sub-branch under the parent the user just added.
        await refreshHierarchyAndKeepSelection({ revealParentId: parentId });
    } catch (error) {
        // Backend's cycle sentinel is { error: 'cycle' } — surface it
        // even though we filter upfront, in case state drifted.
        const msg = error?.message || String(error);
        console.error('Add parent failed:', error);
        showError(`Could not add parent: ${msg}`);
    }
}

/**
 * Entry point for the tree-row "↗N" chip. Selects the node so the
 * details panel populates, then scrolls the Parents section into view.
 */
function openParentsManagerFor(nodeId) {
    selectNode(nodeId);
    setTimeout(() => {
        const sec = document.getElementById('parents-section');
        if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 50);
}

function getNodeLevel(node) {
    let level = 1;
    let current = node;
    while (current._parent) {
        level++;
        current = current._parent;
    }
    return level;
}

function renderSiblingsChart(node) {
    const chart = document.getElementById('siblings-chart');
    const totalEl = document.getElementById('siblings-total');
    
    // Get siblings (same parent)
    let siblings;
    if (node._parent) {
        siblings = node._parent.children || [];
    } else {
        siblings = TreeState.rootNodes;
    }
    
    if (siblings.length <= 1) {
        chart.innerHTML = '<p class="text-muted text-sm">No siblings</p>';
        totalEl.innerHTML = '';
        return;
    }
    
    const total = siblings.reduce((sum, s) => sum + (s.weight || s.exam_weight_low || 0), 0);
    
    chart.innerHTML = siblings.map(s => {
        const weight = s.weight || s.exam_weight_low || 0;
        const isCurrent = s.id === node.id;
        
        return `
            <div class="sibling-bar ${isCurrent ? 'current' : ''}">
                <span class="sibling-name" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</span>
                <div class="sibling-bar-container">
                    <div class="sibling-bar-fill" style="width: ${weight}%"></div>
                </div>
                <span class="sibling-value">${weight.toFixed(1)}%</span>
            </div>
        `;
    }).join('');
    
    const isValid = Math.abs(total - 100) < 0.1;
    totalEl.innerHTML = `Total: <span>${total.toFixed(1)}%</span>`;
    totalEl.className = `siblings-total ${isValid ? '' : 'invalid'}`;
}

function renderChildrenList(node) {
    const list = document.getElementById('children-list');
    
    if (!node.children || node.children.length === 0) {
        list.innerHTML = '<p class="text-muted text-sm">No children</p>';
        return;
    }
    
    list.innerHTML = node.children.map(child => {
        const weight = child.weight || child.exam_weight_low || 0;
        return `
            <div class="child-item" onclick="selectNode(${child.id}); toggleNode(${node.id}, true);">
                <span class="child-icon">📄</span>
                <span class="child-name">${escapeHtml(child.name)}</span>
                <span class="child-weight">${weight.toFixed(1)}%</span>
            </div>
        `;
    }).join('');
}

// =========================================================================
// Node Operations
// =========================================================================

function toggleNode(nodeId, forceExpand = false) {
    if (forceExpand) {
        TreeState.expandedNodes.add(nodeId);
    } else if (TreeState.expandedNodes.has(nodeId)) {
        TreeState.expandedNodes.delete(nodeId);
    } else {
        TreeState.expandedNodes.add(nodeId);
    }
    
    const nodeEl = document.querySelector(`.tree-node[data-id="${nodeId}"]`);
    if (nodeEl) {
        nodeEl.classList.toggle('expanded', TreeState.expandedNodes.has(nodeId));
    }
}

function expandAll() {
    TreeState.flatNodes.forEach((node, id) => {
        if (node.children && node.children.length > 0) {
            TreeState.expandedNodes.add(id);
        }
    });
    renderTree();
}

function collapseAll() {
    TreeState.expandedNodes.clear();
    renderTree();
}

function startInlineEdit(nodeId) {
    const nameEl = document.getElementById(`name-${nodeId}`);
    if (!nameEl) return;
    
    const node = TreeState.flatNodes.get(nodeId);
    if (!node) return;
    
    TreeState.editingNodeId = nodeId;
    
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'tree-node-name-input';
    input.value = node.name;
    
    input.onblur = () => finishInlineEdit(nodeId, input.value);
    input.onkeydown = (e) => {
        if (e.key === 'Enter') finishInlineEdit(nodeId, input.value);
        if (e.key === 'Escape') cancelInlineEdit(nodeId);
    };
    
    nameEl.replaceWith(input);
    input.focus();
    input.select();
}

async function finishInlineEdit(nodeId, newName) {
    if (!newName.trim()) {
        cancelInlineEdit(nodeId);
        return;
    }
    
    const node = TreeState.flatNodes.get(nodeId);
    if (!node || node.name === newName.trim()) {
        cancelInlineEdit(nodeId);
        return;
    }
    
    try {
        await api.updateSubjectNode(nodeId, { name: newName.trim() });
        node.name = newName.trim();
        Toast.success('Updated', `Renamed to "${newName.trim()}"`);
    } catch (error) {
        Toast.error('Error', error.message);
    }
    
    TreeState.editingNodeId = null;
    renderTree();
    if (TreeState.selectedNodeId === nodeId) {
        showNodeDetails(nodeId);
    }
}

function cancelInlineEdit(nodeId) {
    TreeState.editingNodeId = null;
    renderTree();
}

// =========================================================================
// Add Node Modal
// =========================================================================

let addNodeParentId = null;

function showAddNodeModal(parentId = null) {
    addNodeParentId = parentId;

    const modal = document.getElementById('node-modal');
    const title = document.getElementById('node-modal-title');
    const levelGroup = document.getElementById('modal-level-group');
    const levelSelect = document.getElementById('modal-node-level');

    // Reset form
    document.getElementById('modal-node-name').value = '';
    document.getElementById('modal-node-weight').value = '';

    // Reset weight range fields
    const weightLowInput = document.getElementById('modal-weight-low');
    const weightHighInput = document.getElementById('modal-weight-high');
    const weightSourceSelect = document.getElementById('modal-weight-source');
    const weightRangeToggle = document.getElementById('modal-weight-range-toggle');

    if (weightLowInput) weightLowInput.value = '';
    if (weightHighInput) weightHighInput.value = '';
    if (weightSourceSelect) weightSourceSelect.value = 'user_defined';
    if (weightRangeToggle) weightRangeToggle.checked = false;

    // Toggle weight range visibility
    toggleWeightRangeFields(false);

    // Show dimension context for multi-dimensional exams
    const dimensionContext = document.getElementById('modal-dimension-context');
    const dimensionName = document.getElementById('modal-dimension-name');

    if (TreeState.usesDimensions && TreeState.currentDimension) {
        if (dimensionContext) {
            dimensionContext.classList.remove('hidden');
        }
        if (dimensionName) {
            dimensionName.textContent = TreeState.currentDimension.name;
        }
    } else {
        if (dimensionContext) {
            dimensionContext.classList.add('hidden');
        }
    }

    // Determine context (root vs child)
    let isChildNode = parentId !== null;
    let parentNode = null;

    if (parentId === null) {
        title.textContent = 'Add Root Subject';
        levelSelect.value = TreeState.hierarchyLevels[0]?.level_name || 'System';
        updateWeightModeForModal('absolute');
    } else {
        parentNode = TreeState.flatNodes.get(parentId);
        const parentLevel = getNodeLevel(parentNode);
        title.textContent = `Add Child to "${parentNode.name}"`;

        // Set level to one below parent
        if (TreeState.hierarchyLevels[parentLevel]) {
            levelSelect.value = TreeState.hierarchyLevels[parentLevel].level_name;
        }

        // If parent has official weight, child should use relative weight
        if (parentNode.weight_source === 'official' || parentNode.weight_source === 'derived') {
            updateWeightModeForModal('relative');
        } else {
            updateWeightModeForModal('absolute');
        }
    }

    modal.classList.add('active');
    document.getElementById('modal-node-name').focus();
}

/**
 * Update the modal weight section based on weight mode
 */
function updateWeightModeForModal(mode) {
    const weightSection = document.getElementById('modal-weight-section');
    if (!weightSection) return;
    
    const simpleWeightGroup = document.getElementById('modal-simple-weight-group');
    const rangeWeightGroup = document.getElementById('modal-range-weight-group');
    const weightModeLabel = document.getElementById('modal-weight-mode-label');
    
    if (mode === 'relative') {
        if (weightModeLabel) {
            weightModeLabel.textContent = 'Relative Weight';
            weightModeLabel.title = 'Percentage of parent weight';
        }
        // Show simple weight input for relative weights
        if (simpleWeightGroup) simpleWeightGroup.classList.remove('hidden');
        if (rangeWeightGroup) rangeWeightGroup.classList.add('hidden');
    } else {
        if (weightModeLabel) {
            weightModeLabel.textContent = 'Weight';
            weightModeLabel.title = 'Absolute exam weight';
        }
    }
}

/**
 * Toggle visibility of weight range input fields
 */
function toggleWeightRangeFields(showRange) {
    const simpleWeightGroup = document.getElementById('modal-simple-weight-group');
    const rangeWeightGroup = document.getElementById('modal-range-weight-group');
    
    if (showRange) {
        if (simpleWeightGroup) simpleWeightGroup.classList.add('hidden');
        if (rangeWeightGroup) rangeWeightGroup.classList.remove('hidden');
    } else {
        if (simpleWeightGroup) simpleWeightGroup.classList.remove('hidden');
        if (rangeWeightGroup) rangeWeightGroup.classList.add('hidden');
    }
}

/**
 * Update the help text based on selected weight source
 */
function updateWeightSourceHelp(source) {
    const hints = document.querySelectorAll('#weight-source-help .source-hint');
    hints.forEach(hint => {
        if (hint.classList.contains(source)) {
            hint.classList.remove('hidden');
            hint.classList.add('active');
        } else {
            hint.classList.add('hidden');
            hint.classList.remove('active');
        }
    });
}

// Expose these functions globally
window.toggleWeightRangeFields = toggleWeightRangeFields;
window.updateWeightSourceHelp = updateWeightSourceHelp;

function hideAddNodeModal() {
    document.getElementById('node-modal').classList.remove('active');
    addNodeParentId = null;
}

async function saveNewNode() {
    const name = document.getElementById('modal-node-name').value.trim();
    const levelType = document.getElementById('modal-node-level').value;
    
    // Get weight configuration
    const weightRangeToggle = document.getElementById('modal-weight-range-toggle');
    const useWeightRange = weightRangeToggle?.checked || false;
    const weightSourceSelect = document.getElementById('modal-weight-source');
    const weightSource = weightSourceSelect?.value || 'user_defined';
    
    let weightLow = null;
    let weightHigh = null;
    let relativeWeight = null;
    let simpleWeight = null;
    
    if (useWeightRange) {
        // Using weight range
        const lowInput = document.getElementById('modal-weight-low');
        const highInput = document.getElementById('modal-weight-high');
        weightLow = parseFloat(lowInput?.value) || null;
        weightHigh = parseFloat(highInput?.value) || null;
        
        // Validate range
        if (weightLow !== null && weightHigh !== null && weightHigh < weightLow) {
            Toast.warning('Invalid Range', 'High weight must be greater than or equal to low weight');
            return;
        }
    } else {
        // Using simple weight
        const simpleInput = document.getElementById('modal-node-weight');
        simpleWeight = parseFloat(simpleInput?.value) || 0;
        
        // Check if this is a relative weight context (parent has official weight)
        if (addNodeParentId) {
            const parentNode = TreeState.flatNodes.get(addNodeParentId);
            if (parentNode && (parentNode.weight_source === 'official' || parentNode.weight_source === 'derived')) {
                relativeWeight = simpleWeight;
                simpleWeight = null;
            }
        }
    }
    
    if (!name) {
        Toast.warning('Required', 'Please enter a subject name');
        return;
    }
    
    try {
        const nodeData = {
            exam_context_id: TreeState.examContextId,
            name: name,
            level_type: levelType,
            parent_id: addNodeParentId
        };

        // Add dimension_id for multi-dimensional exams
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            nodeData.dimension_id = TreeState.currentDimensionId;
        }

        // Add weight fields based on configuration
        if (useWeightRange) {
            if (weightLow !== null) nodeData.exam_weight_low = weightLow;
            if (weightHigh !== null) nodeData.exam_weight_high = weightHigh;
            nodeData.weight_source = weightSource;
            // Lock official weights
            if (weightSource === 'official') {
                nodeData.weight_locked = true;
            }
        } else if (relativeWeight !== null) {
            nodeData.relative_weight = relativeWeight;
            nodeData.weight_source = 'derived';
        } else if (simpleWeight !== null && simpleWeight > 0) {
            nodeData.exam_weight_low = simpleWeight;
            nodeData.exam_weight_high = simpleWeight;
            nodeData.weight_source = weightSource;
        }

        // Use the enhanced create method if weight fields are present
        let result;
        if (nodeData.exam_weight_low !== undefined || nodeData.relative_weight !== undefined) {
            result = await api.createSubjectNodeWithWeight(nodeData);
        } else {
            // Fall back to basic create for nodes without weight
            nodeData.weight = simpleWeight || 0;
            result = await api.createSubjectNode(nodeData);
        }

        Toast.success('Created', `Added "${name}"`);
        hideAddNodeModal();

        // Invalidate cache and reload hierarchy
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            invalidateDimensionCache(TreeState.currentDimensionId);
        }

        await loadHierarchy();

        // Expand parent if adding child
        if (addNodeParentId) {
            TreeState.expandedNodes.add(addNodeParentId);
        }

        reapplySearchIfActive();
        renderTree();

        // Select the new node
        if (result?.id) {
            selectNode(result.id);
        }

    } catch (error) {
        Toast.error('Error', error.message);
    }
}

function addChild(parentId) {
    showAddNodeModal(parentId);
}

// =========================================================================
// Delete Node
// =========================================================================

let deleteNodeTarget = null;

function confirmDeleteNode(nodeId) {
    const node = TreeState.flatNodes.get(nodeId);
    if (!node) return;
    
    deleteNodeTarget = node;
    
    document.getElementById('delete-node-name').textContent = node.name;
    
    const warning = document.getElementById('delete-children-warning');
    if (node.children && node.children.length > 0) {
        warning.textContent = `This will also delete ${node.children.length} child subject${node.children.length > 1 ? 's' : ''}!`;
        warning.classList.remove('hidden');
    } else {
        warning.classList.add('hidden');
    }
    
    document.getElementById('delete-node-modal').classList.add('active');
}

function hideDeleteModal() {
    document.getElementById('delete-node-modal').classList.remove('active');
    deleteNodeTarget = null;
}

async function executeDeleteNode() {
    if (!deleteNodeTarget) return;

    try {
        await api.deleteSubjectNode(deleteNodeTarget.id);

        Toast.success('Deleted', `Removed "${deleteNodeTarget.name}"`);

        // Clear selection if deleted node was selected, show overview
        if (TreeState.selectedNodeId === deleteNodeTarget.id) {
            TreeState.selectedNodeId = null;
            showExamOverview();
        }

        hideDeleteModal();

        // Invalidate cache and reload hierarchy
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            invalidateDimensionCache(TreeState.currentDimensionId);
        }

        await loadHierarchy();
        reapplySearchIfActive();

    } catch (error) {
        Toast.error('Error', error.message);
    }
}

// =========================================================================
// Weight Operations
// =========================================================================

function onWeightSliderChange(value) {
    document.getElementById('weight-value').value = value;
    previewWeightChange(parseFloat(value));
}

function onWeightInputChange(value) {
    const numValue = Math.max(0, Math.min(100, parseFloat(value) || 0));
    document.getElementById('weight-slider').value = numValue;
    document.getElementById('weight-value').value = numValue;
    previewWeightChange(numValue);
}

function previewWeightChange(newWeight) {
    // This would show a preview of how siblings will be affected
    // For now, just update the visual
}

async function applyWeight() {
    if (TreeState.selectedNodeId === null) return;
    
    const newWeight = parseFloat(document.getElementById('weight-value').value) || 0;
    
    if (newWeight === TreeState.originalWeight) {
        Toast.info('No Change', 'Weight value is unchanged');
        return;
    }
    
    try {
        await api.updateSubjectNodeWeight(
            TreeState.selectedNodeId,
            newWeight,
            'Manual adjustment',
            ''
        );
        
        Toast.success('Updated', `Weight set to ${newWeight.toFixed(1)}%`);
        TreeState.originalWeight = newWeight;
        
        // Reload to get updated sibling weights
        await loadHierarchy();
        showNodeDetails(TreeState.selectedNodeId);
        
    } catch (error) {
        Toast.error('Error', error.message);
    }
}

function resetWeight() {
    if (TreeState.originalWeight !== null) {
        document.getElementById('weight-slider').value = TreeState.originalWeight;
        document.getElementById('weight-value').value = TreeState.originalWeight;
    }
}

// =========================================================================
// Import/Export
// =========================================================================

async function exportHierarchy() {
    try {
        const data = await api.exportSubjectHierarchy(TreeState.examContextId);
        
        const exportData = {
            exam_name: TreeState.examContext.exam_name,
            exported_at: new Date().toISOString(),
            root_nodes: data?.root_nodes || TreeState.rootNodes
        };
        
        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `${TreeState.examContext.exam_name.replace(/[^a-z0-9]/gi, '_')}_hierarchy.json`;
        a.click();
        
        URL.revokeObjectURL(url);
        Toast.success('Exported', 'Hierarchy downloaded as JSON');
        
    } catch (error) {
        Toast.error('Export Failed', error.message);
    }
}

function triggerImport() {
    document.getElementById('import-file').click();
}

async function handleImportFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    try {
        const text = await file.text();
        const data = JSON.parse(text);
        
        if (!data.root_nodes || !Array.isArray(data.root_nodes)) {
            throw new Error('Invalid file format: missing root_nodes array');
        }
        
        // Confirm import
        const count = countNodes(data.root_nodes);
        if (!confirm(`Import ${count} subjects from "${file.name}"?\n\nThis will add to your existing hierarchy.`)) {
            return;
        }
        
        // Include dimension_id in import data when in dimension mode
        const importData = { ...data };
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            importData.dimension_id = TreeState.currentDimensionId;
        }

        await api.importSubjectHierarchy(TreeState.examContextId, JSON.stringify(importData));

        Toast.success('Imported', `Added ${count} subjects`);

        // Invalidate dimension cache before reload
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            invalidateDimensionCache(TreeState.currentDimensionId);
        }

        // Reload
        await loadHierarchy();
        
    } catch (error) {
        Toast.error('Import Failed', error.message);
    }
    
    // Reset file input
    event.target.value = '';
}

function countNodes(nodes) {
    return nodes.reduce((sum, node) => {
        return sum + 1 + (node.children ? countNodes(node.children) : 0);
    }, 0);
}

// =========================================================================
// Search / Filter
// =========================================================================

let _searchDebounceTimer = null;

function onSearchInput(query) {
    clearTimeout(_searchDebounceTimer);
    const clearBtn = document.getElementById('tree-search-clear');
    const countBadge = document.getElementById('tree-search-count');

    if (query.length === 0) {
        clearTreeSearch();
        return;
    }

    clearBtn.classList.remove('hidden');

    _searchDebounceTimer = setTimeout(() => {
        applyTreeSearch(query);
    }, 150);
}

function applyTreeSearch(query) {
    const lowerQuery = query.toLowerCase();
    const matchIds = new Set();
    const visibleIds = new Set();

    // Save expand state once when a search begins
    if (TreeState.preSearchExpandedNodes === null) {
        TreeState.preSearchExpandedNodes = new Set(TreeState.expandedNodes);
    }

    // Walk flatNodes to find matches. Match against both the node name and
    // any aliases shipped on the payload (hierarchy.py builds aliasesString
    // from get_aliases_for_exam so a single substring check covers all of
    // a subject's aliases).
    TreeState.flatNodes.forEach((node, id) => {
        const nameMatch = node.name.toLowerCase().includes(lowerQuery);
        const aliasMatch = !nameMatch && (node.aliasesString || '').toLowerCase().includes(lowerQuery);
        if (nameMatch || aliasMatch) {
            matchIds.add(id);
            visibleIds.add(id);
            // Walk up parent chain to keep ancestors visible
            let cur = node._parent;
            while (cur) {
                visibleIds.add(cur.id);
                cur = cur._parent;
            }
        }
    });

    TreeState.searchQuery = query;
    TreeState.searchMatchIds = matchIds;
    TreeState.searchVisibleIds = visibleIds;

    // Expand ancestors of matches so they are visible
    visibleIds.forEach(id => {
        if (!matchIds.has(id)) {
            TreeState.expandedNodes.add(id);
        }
    });
    // Also expand match nodes that have visible children
    matchIds.forEach(id => {
        const node = TreeState.flatNodes.get(id);
        if (node && node.children && node.children.some(c => visibleIds.has(c.id))) {
            TreeState.expandedNodes.add(id);
        }
    });

    renderTree();

    // Update count badge
    const countBadge = document.getElementById('tree-search-count');
    if (countBadge) {
        countBadge.textContent = matchIds.size === 1 ? '1 match' : `${matchIds.size} matches`;
        countBadge.classList.remove('hidden');
    }
}

function clearTreeSearch() {
    TreeState.searchQuery = '';
    TreeState.searchMatchIds = new Set();
    TreeState.searchVisibleIds = null;

    // Restore pre-search expand state
    if (TreeState.preSearchExpandedNodes !== null) {
        TreeState.expandedNodes = new Set(TreeState.preSearchExpandedNodes);
        TreeState.preSearchExpandedNodes = null;
    }

    const input = document.getElementById('tree-search-input');
    const clearBtn = document.getElementById('tree-search-clear');
    const countBadge = document.getElementById('tree-search-count');

    if (input) input.value = '';
    if (clearBtn) clearBtn.classList.add('hidden');
    if (countBadge) countBadge.classList.add('hidden');

    renderTree();
}

function highlightSearchMatch(text, query) {
    if (!query) return escapeHtml(text);
    const escaped = escapeHtml(text);
    const escapedQuery = escapeHtml(query);
    const idx = escaped.toLowerCase().indexOf(escapedQuery.toLowerCase());
    if (idx === -1) return escaped;
    const before = escaped.substring(0, idx);
    const match = escaped.substring(idx, idx + escapedQuery.length);
    const after = escaped.substring(idx + escapedQuery.length);
    return `${before}<mark class="tree-search-highlight">${match}</mark>${after}`;
}

function reapplySearchIfActive() {
    if (TreeState.searchVisibleIds !== null && TreeState.searchQuery) {
        applyTreeSearch(TreeState.searchQuery);
    }
}

// =========================================================================
// Event Listeners
// =========================================================================

function setupEventListeners() {
    // Toolbar buttons
    document.getElementById('btn-add-root').onclick = () => showAddNodeModal(null);
    document.getElementById('btn-add-first')?.addEventListener('click', () => showAddNodeModal(null));
    document.getElementById('btn-expand-all').onclick = expandAll;
    document.getElementById('btn-collapse-all').onclick = collapseAll;
    document.getElementById('btn-export').onclick = exportHierarchy;
    document.getElementById('btn-import').onclick = triggerImport;

    // Polyhierarchy: parent-management picker controls. Listeners wired
    // once at startup; the actions read TreeState.selectedNodeId at
    // call time so they stay correct as the user navigates the tree.
    const addParentBtn = document.getElementById('btn-add-parent');
    if (addParentBtn) {
        addParentBtn.addEventListener('click', () => {
            if (TreeState.selectedNodeId) openAddParentPicker();
        });
    }
    const pickerCancelBtn = document.getElementById('parents-picker-cancel');
    if (pickerCancelBtn) {
        pickerCancelBtn.addEventListener('click', closeAddParentPicker);
    }
    const pickerInput = document.getElementById('parents-picker-input');
    if (pickerInput) {
        let debounce = null;
        pickerInput.addEventListener('input', (e) => {
            clearTimeout(debounce);
            const query = e.target.value;
            const childId = TreeState.selectedNodeId;
            if (!childId) return;
            debounce = setTimeout(() => searchParentPicker(query, childId), 150);
        });
        pickerInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeAddParentPicker();
        });
    }

    // Search bar
    const searchInput = document.getElementById('tree-search-input');
    const searchClear = document.getElementById('tree-search-clear');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => onSearchInput(e.target.value));
    }
    if (searchClear) {
        searchClear.addEventListener('click', () => clearTreeSearch());
    }

    // Add node modal
    document.getElementById('node-modal-cancel').onclick = hideAddNodeModal;
    document.getElementById('node-modal-save').onclick = saveNewNode;
    document.getElementById('node-modal').onclick = (e) => {
        if (e.target.id === 'node-modal') hideAddNodeModal();
    };
    
    // Delete modal
    document.getElementById('delete-node-cancel').onclick = hideDeleteModal;
    document.getElementById('delete-node-confirm').onclick = executeDeleteNode;
    document.getElementById('delete-node-modal').onclick = (e) => {
        if (e.target.id === 'delete-node-modal') hideDeleteModal();
    };
    
    // Details panel
    document.getElementById('edit-name').onchange = async (e) => {
        if (TreeState.selectedNodeId) {
            try {
                await api.updateSubjectNode(TreeState.selectedNodeId, { name: e.target.value });
                const node = TreeState.flatNodes.get(TreeState.selectedNodeId);
                if (node) node.name = e.target.value;
                reapplySearchIfActive();
                renderTree();
                Toast.success('Updated', 'Name saved');
            } catch (error) {
                Toast.error('Error', error.message);
            }
        }
    };
    
    // Weight controls (with null checks since enhanced editor may replace them)
    const weightSlider = document.getElementById('weight-slider');
    const weightValueInput = document.getElementById('weight-value');
    const applyWeightBtn = document.getElementById('btn-apply-weight');
    const resetWeightBtn = document.getElementById('btn-reset-weight');
    
    if (weightSlider) weightSlider.oninput = (e) => onWeightSliderChange(e.target.value);
    if (weightValueInput) weightValueInput.onchange = (e) => onWeightInputChange(e.target.value);
    if (applyWeightBtn) applyWeightBtn.onclick = applyWeight;
    if (resetWeightBtn) resetWeightBtn.onclick = resetWeight;
    document.getElementById('btn-add-child').onclick = () => {
        if (TreeState.selectedNodeId) addChild(TreeState.selectedNodeId);
    };
    document.getElementById('btn-delete-node').onclick = () => {
        if (TreeState.selectedNodeId) confirmDeleteNode(TreeState.selectedNodeId);
    };

    // Manage Aliases button
    const manageAliasesBtn = document.getElementById('btn-manage-aliases');
    if (manageAliasesBtn) {
        manageAliasesBtn.onclick = () => {
            if (TreeState.selectedNodeId) {
                const node = TreeState.flatNodes.get(TreeState.selectedNodeId);
                if (node && typeof AliasManager !== 'undefined') {
                    AliasManager.open(node.id, TreeState.examContext.exam_name, node.name);
                }
            }
        };
    }

    // Listen for alias updates to refresh the preview
    window.addEventListener('aliases-updated', (e) => {
        if (e.detail.subjectId === TreeState.selectedNodeId) {
            loadAliasesPreview(TreeState.selectedNodeId);
        }
    });
    
    // Import file
    document.getElementById('import-file').onchange = handleImportFile;
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl+F / Cmd+F focuses the search bar
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
            e.preventDefault();
            const searchInput = document.getElementById('tree-search-input');
            if (searchInput) {
                searchInput.focus();
                searchInput.select();
            }
            return;
        }

        if (e.key === 'Escape') {
            // Clear active search first
            if (TreeState.searchVisibleIds !== null) {
                clearTreeSearch();
                return;
            }
            if (document.getElementById('node-modal').classList.contains('active')) {
                hideAddNodeModal();
            } else if (document.getElementById('delete-node-modal').classList.contains('active')) {
                hideDeleteModal();
            } else if (document.getElementById('import-preview-modal')?.classList.contains('active')) {
                hideImportPreviewModal();
            } else if (document.getElementById('import-error-modal')?.classList.contains('active')) {
                hideImportErrorModal();
            }
        }
    });
}

// =========================================================================
// Utility Functions
// =========================================================================

function showLoading(show) {
    const loading = document.getElementById('tree-loading');
    const container = document.getElementById('tree-container');
    const empty = document.getElementById('tree-empty');
    
    if (show) {
        loading.classList.remove('hidden');
        container.classList.add('hidden');
        empty.classList.add('hidden');
    } else {
        loading.classList.add('hidden');
        container.classList.remove('hidden');
    }
}

function showError(message) {
    const container = document.getElementById('tree-container');
    container.innerHTML = `
        <div class="alert alert-error" style="margin: 20px;">
            <strong>Error:</strong> ${escapeHtml(message)}
            <br><br>
            <a href="index.html" class="btn btn-secondary">← Back to Exams</a>
        </div>
    `;
    document.getElementById('tree-empty').classList.add('hidden');
    document.getElementById('tree-loading').classList.add('hidden');
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =========================================================================
// Expose Global Functions for onclick handlers
// =========================================================================

window.selectNode = selectNode;
window.toggleNode = toggleNode;
window.startInlineEdit = startInlineEdit;
window.addChild = addChild;
window.confirmDeleteNode = confirmDeleteNode;
window.expandAll = expandAll;
window.collapseAll = collapseAll;
window.escapeHtml = escapeHtml;
window.loadHierarchy = loadHierarchy;

// Polyhierarchy: tree-row chip + parents-section action handlers.
// Exposed because they're invoked from inline onclick attributes
// generated by renderNode and renderParentsSection.
window.openParentsManagerFor = openParentsManagerFor;
window.switchPrimaryParentTo = switchPrimaryParentTo;
window.confirmRemoveParentEdge = confirmRemoveParentEdge;
window.restoreParentRow = restoreParentRow;
window.performRemoveParentEdge = performRemoveParentEdge;
window.addParentEdgeFromPicker = addParentEdgeFromPicker;

// Multi-dimensional support exports
window.selectDimension = selectDimension;
window.TreeState = TreeState;

// =========================================================================
// Initialize on DOM Ready
// =========================================================================

document.addEventListener('DOMContentLoaded', initializeTreeEditor);

// Reload hierarchy data when page is restored from back-forward cache
window.addEventListener('pageshow', function(event) {
    if (event.persisted) {
        console.log('🔄 Page restored from cache, reloading hierarchy...');
        loadHierarchy();
    }
});
