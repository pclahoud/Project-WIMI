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

    // "The page is still markup." Cleared by markTreeEditorReady(), which is
    // the one place that also removes `inert` from .tree-page (#114, #121).
    // Latched so the function is idempotent; it is called from the init
    // chain's `finally` and from the no-exam-id early return.
    isPageReady: false,
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

        // Built from text nodes, not a template (#548). The messages carry
        // subject names -- "Renamed to ...", and the importer's own warnings,
        // which quote a FILE's subject names back -- so an innerHTML template
        // here ran whatever markup a name held.
        const icon = document.createElement('span');
        icon.style.cssText = `color: ${colorVars[type]}; font-size: 1.25rem;`;
        icon.textContent = icons[type];

        const body = document.createElement('div');
        body.style.flex = '1';
        const titleEl = document.createElement('div');
        titleEl.style.cssText = 'font-weight: 500; margin-bottom: 2px;';
        titleEl.textContent = title;
        body.appendChild(titleEl);
        if (message) {
            const messageEl = document.createElement('div');
            messageEl.style.cssText = 'font-size: 0.875rem; color: var(--text-muted);';
            messageEl.textContent = message;
            body.appendChild(messageEl);
        }

        const close = document.createElement('button');
        close.style.cssText = 'background: none; border: none; cursor: pointer; color: var(--text-muted); font-size: 1.25rem;';
        close.textContent = '×';

        toast.append(icon, body, close);

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

/**
 * Hand the tree editor to the student: clear `inert` and drop isLoading.
 *
 * Until this runs, .tree-page ships `inert`, so a click has nowhere to land
 * and the search box cannot be typed into -- which is the point. The toolbar
 * (Collapse All, Expand All, Import, Export), #btn-add-root and
 * #tree-search-input are all bound in setupEventListeners(), five awaits into
 * initializeTreeEditor(), and every click before that is swallowed with no
 * toast, no console error and no other sign (#114's shape, filed as #121).
 *
 * Called from the `finally` of initializeTreeEditor() and from its
 * no-exam-id early return, which is before the `try`. That placement is
 * load-bearing twice over:
 *
 * - **Both load paths are inside the try.** A dimensioned exam goes
 *   loadDimensions() -> selectDimension() -> loadDimensionHierarchy(); a
 *   plain one goes loadHierarchy(). Releasing from the end of one branch
 *   would leave the other permanently gated, and the dimensioned path is the
 *   common case, not the edge case (CLAUDE.md, *Dimension code path
 *   symmetry*).
 * - **Every failure exit releases too.** A permanently gated page is far
 *   worse than the bug the gate fixes (#114's own rule), so the release sits
 *   in a `finally` rather than after the last statement of the happy path.
 *
 * It also owns the announcement (#127): `inert` takes .tree-page out of the
 * accessibility tree, so the gate is silence as well as refusal, and
 * #tree-loading cannot say so because it is inside the gated subtree.
 */
function markTreeEditorReady() {
    if (TreeState.isPageReady) return;
    TreeState.isPageReady = true;
    TreeState.isLoading = false;

    const page = document.querySelector('.tree-page');
    if (page) page.removeAttribute('inert');

    // AFTER removeAttribute, inside a try, behind a typeof check, and its
    // return value deliberately ignored. Nothing added for assistive tech --
    // a forgotten <script> tag included -- may be able to leave the page
    // gated (#127, point 5 of page_gate.js's contract).
    try {
        if (typeof PageGate !== 'undefined') PageGate.release('Subject hierarchy ready.');
    } catch (err) {
        console.warn('PageGate.release failed; the page is released anyway:', err);
    }
}

/**
 * The first-run tour (#430). Called once the page gate has released, and
 * again when a view brings a step's target on screen: the Archived subjects
 * panel (shown only once its asynchronous load finds a deletion) and the
 * import preview (import_export.js). tour.js rebuilds an open tour from what
 * renders now. A no-op before the release, when .tree-page is inert. Behind a
 * typeof check and a try, so a broken tour cannot break the page.
 */
function startTreeTour() {
    if (!TreeState.isPageReady) return;
    try {
        if (typeof WimiTour !== 'undefined') WimiTour.start('tree-editor');
    } catch (err) {
        console.error('Tour failed to start:', err);
    }
}

async function initializeTreeEditor() {
    console.log('🌳 Initializing tree editor...');

    // Get exam ID from URL
    const urlParams = new URLSearchParams(window.location.search);
    const examId = urlParams.get('exam_id');

    if (!examId) {
        showError('No exam ID provided. Please select an exam from the landing page.');
        // This return is before the `try`, so the `finally` below cannot
        // reach it. A page left `inert` here would refuse the "Back to Exams"
        // link showError() just drew (#114).
        markTreeEditorReady();
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
            } else {
                // An exam flagged as dimensioned with no active dimension
                // reaches NEITHER load path, so nothing here would ever clear
                // the loading state the page now ships visible (#121). It
                // used to land on #tree-empty by default, which was wrong for
                // a different reason. renderTree() on an empty tree is the
                // honest answer: there is nothing to draw.
                showLoading(false);
                renderTree();
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
    } finally {
        // One release, reached from the happy path, from a thrown exam load,
        // and from both the dimensioned and the plain hierarchy branch above.
        // See markTreeEditorReady() for why it is here and not at the end of
        // the try.
        markTreeEditorReady();
        startTreeTour();
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
    renderLevelOptions();
}

/**
 * Fill the Add Subject modal's "Level Type" dropdown (issue #82).
 *
 * ``extraLevelName`` is appended when a node already in the tree carries
 * a level name the exam's configured list does not have — an imported
 * outline that brought its own vocabulary (the in-app SAT example uses
 * Section / Domain / Skill), or a level renamed through
 * ``update_hierarchy_level`` without back-filling
 * ``subject_nodes.level_type``. Per the decision on #82, that name is
 * offered rather than silently replaced with one of the app's own.
 *
 * The appended option exists for this modal instance ONLY, because a
 * node in the tree already carries it. It is never written to
 * ``hierarchy_level_definitions`` — the dropdown is rebuilt on every
 * open, so it disappears again the moment it is no longer relevant.
 *
 * Options are built with the DOM API rather than an innerHTML template
 * because ``extraLevelName`` is user data straight out of the database.
 */
function renderLevelOptions(extraLevelName) {
    const levelSelect = document.getElementById('modal-node-level');
    if (!levelSelect) return;

    const names = TreeState.hierarchyLevels.map(level => level.level_name);
    if (extraLevelName && !names.includes(extraLevelName)) {
        names.push(extraLevelName);
    }

    levelSelect.innerHTML = '';
    names.forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        levelSelect.appendChild(option);
    });
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
        // The Archived panel (#37) is refreshed from BOTH load paths on
        // purpose. This one is the common case, not the edge case, and the
        // dimension/plain split is exactly where enrichment gets forgotten
        // (see the "Dimension code path symmetry" note in CLAUDE.md).
        // Deliberately not awaited: the panel is supplementary, and blocking
        // the tree render on it would make a slow journal read look like a
        // slow tree.
        refreshArchivedPanel();
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
        // Mirrored from the dimension branch above -- see the note there.
        refreshArchivedPanel();
        refreshUnassignedPanel();   // #605
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
 * parent (i.e. appears as a key in the response).
 *
 * **NOTHING DRAWS A WARNING FROM THIS, AND NOTHING MAY (#664, owner
 * 2026-10-10).** The row used to carry a ⚠ whenever the status was not
 * ``'ok'``, titled "Children's weights exceed this parent's range"
 * (``'over'``), "Children's minimums don't fit in this parent's maximum"
 * (``'infeasible'``) or "Children's weights leave room under this parent"
 * (``'under'``). All three compared the children's summed weights with
 * their parent's, and #64 says that comparison has no meaning: a weight is
 * a share of the **whole exam** at any depth, never of the subject above
 * it. So the dot fired on correct published blueprints — Step 2 CK lists
 * Nutrition at 15–20% and Multisystem at 4–8% as siblings, so filing the
 * first under the second warned about two numbers copied off the document
 * — while ``docs/manual/20_weights.md`` told students "there is no such
 * check anywhere in the app, and nothing warns you". The manual was right
 * and this was the check.
 *
 * ``validate_hierarchy_feasibility`` now always reports ``'ok'``, so the
 * stamp is uniformly ``'ok'`` and this function has nothing to change on
 * screen. It is kept because the report's *figures* are still real and a
 * future caller may want them; see the decision point in ``hierarchy.py``
 * for what it would take to make a per-parent verdict meaningful again.
 *
 * Failures are non-fatal — the tree still renders, mirroring
 * ``enrichNodesWithQuestionCounts`` behavior.
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

    // #237: "Export all" writes a whole-exam file, which only means anything
    // for an exam that has dimensions. Revealed here rather than at wiring
    // time because `usesDimensions` is not known until they are loaded.
    const exportAllBtn = document.getElementById('btn-export-whole-exam');

    if (!TreeState.usesDimensions || TreeState.dimensions.length === 0) {
        selector.classList.add('hidden');
        exportAllBtn?.classList.add('hidden');
        return;
    }

    selector.classList.remove('hidden');
    exportAllBtn?.classList.remove('hidden');

    tabsContainer.innerHTML = TreeState.dimensions.map(dim => `
        <button class="dimension-tab ${dim.id === TreeState.currentDimensionId ? 'active' : ''}"
                data-dimension-id="${dim.id}"
                data-testid="tree-dimension-tab-${dim.id}"
                onclick="selectDimension(${dim.id})"
                title="${WimiEscape.html(dim.description || dim.name)}">
            <span class="dimension-tab-name">${WimiEscape.html(dim.name)}</span>
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
        // `allow_multiple` states what is EXPECTED, not what is enforced
        // (#209). Nothing blocks a second subject; the entry form reports an
        // over-tagged dimension as a warning. Showing "Multi-select" when the
        // flag is on and nothing when it is off implied the opposite -- that
        // off meant single-select -- while the live path has always permitted
        // any number of subjects per dimension.
        const badges = [];
        if (dimension.is_required) badges.push('Required');
        badges.push(dimension.allow_multiple ? 'Multi-select' : 'One expected');
        badgeEl.textContent = badges.join(' • ') || 'Optional';
        badgeEl.title = dimension.allow_multiple
            ? 'More than one subject from this dimension is expected on an entry.'
            : 'One subject from this dimension is expected. WIMI warns if an entry '
              + 'carries more, it does not block saving.';
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
            <span class="dimension-stat" data-testid="tree-overview-total-weight"><strong>${totalWeight.toFixed(1)}%</strong> total weight</span>
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
        // #605's panel is refreshed HERE rather than in `loadHierarchy`'s
        // dimension branch, and the difference is the whole reason the
        // panel appeared empty the first time it was wired.
        //
        // ON A DIMENSIONED EXAM, `loadHierarchy` IS NOT THE INITIAL LOAD
        // PATH. Init goes `loadDimensions() -> selectDimension() ->
        // loadDimensionHierarchy()` and never touches `loadHierarchy`,
        // which this file's own header comment says at the top. So a
        // refresh hung off `loadHierarchy` runs on every later reload and
        // not on the one that matters. `loadDimensionHierarchy` is the
        // function both dimensioned entry points share.
        //
        // In the `finally` so the cache-hit early return above is covered
        // too; not awaited, because a supplementary panel must not make a
        // slow read look like a slow tree.
        //
        // The Archived panel (#37) has this same gap and is NOT fixed here
        // -- filed separately rather than folded into an unrelated issue.
        refreshUnassignedPanel();
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

    // #304: this replaces the whole tree markup, destroying any focused row
    // control. Selecting a row with children expands it, which lands here,
    // so without putting focus back a keyboard user is returned to the top
    // of the document by their own Enter press -- a route you cannot use
    // twice is not a route. Captured before the write, restored after.
    const focusedRowId = focusedTreeRowId();

    if (TreeState.rootNodes.length === 0) {
        container.innerHTML = '';
        // On a dimensioned exam this is "this axis is empty", never "this
        // exam is empty" (#605, see currentAxisName). Text, not markup.
        const axis = currentAxisName();
        emptyState.querySelector('.tree-empty-title').textContent = axis
            ? `No Subjects in ${axis} Yet` : 'No Subjects Yet';
        document.getElementById('btn-add-first').textContent = axis
            ? `Add the First Subject to ${axis}` : 'Add Your First Subject';
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

    if (focusedRowId !== null) focusTreeRow(focusedRowId);

    // Every row was just replaced, so an open tour tip points at a removed
    // node, and an expanded row may have brought a step's target on screen
    // (the shared-parents chip sits on a child). Rebuilding re-resolves both.
    startTreeTour();
}

/**
 * The node id of the row control that currently has keyboard focus, or null.
 *
 * Reads `document.activeElement` rather than tracking focus in `TreeState`,
 * because the question being asked is "is the keyboard in the tree right
 * now" and the DOM is the only thing that knows.
 */
function focusedTreeRowId() {
    const active = document.activeElement;
    if (!active || !active.classList
        || !active.classList.contains('tree-node-name')) {
        return null;
    }
    const match = /^name-(\d+)$/.exec(active.id || '');
    return match ? Number(match[1]) : null;
}

/** Put keyboard focus on a subject row's control. No-op if it is gone. */
function focusTreeRow(nodeId) {
    const el = document.getElementById(`name-${nodeId}`);
    if (el && typeof el.focus === 'function') el.focus();
}

/**
 * Keyboard equivalents for the row's mouse gestures (#304).
 *
 * Enter / Space mirror the single click (select), F2 mirrors the double
 * click (inline rename) -- F2 because that is what every tree view the
 * student already uses binds rename to, and because Enter is taken by
 * select. `preventDefault` on Space is not optional: without it the page
 * scrolls instead.
 */
function handleTreeRowKeydown(event, nodeId) {
    if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
        event.preventDefault();
        event.stopPropagation();
        selectNode(nodeId);
    } else if (event.key === 'F2') {
        event.preventDefault();
        event.stopPropagation();
        startInlineEdit(nodeId);
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
    // ``level`` here is the render depth of THIS appearance, so a
    // multi-parent subject used to get a different chip under each parent.
    // The chip now echoes the node's own level_type (#49).
    const levelName = getNodeLevelName(node, level);

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
    //
    // #304/#306 in the markup below:
    //   - `.tree-node-name` carries role="button" + tabindex="0" + a keydown
    //     handler, because the row was mouse-only. It is the name span rather
    //     than `.tree-node-content` because role="button" on the container
    //     makes the row's accessible name the concatenation of everything in
    //     it -- measured as "> [folder] Cardio System 0.0% + [bin]".
    //   - the two action buttons carry aria-labels. A title attribute does
    //     NOT override visible content, so they announced as "+" and
    //     "wastebasket"; the subject's name is in the label because a tree of
    //     31 rows otherwise offers 31 identically-named Delete buttons.
    //
    // NOTE: everything from here to the closing backtick is ONE template
    // literal, so an HTML comment inside it may not contain a backtick -- a
    // backtick ends the literal. That is not hypothetical: writing this
    // paragraph as an inline `<!-- ... `title` ... -->` produced
    // "SyntaxError: Unexpected identifier 'title'" and left the tree editor
    // permanently gated with an empty tree and no other symptom.
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
                <span class="tree-node-name" id="name-${node.id}" data-testid="tree-node-name-${node.id}"
                      data-tour-anchor="tree-row-name"
                      role="button" tabindex="0"
                      aria-keyshortcuts="Enter F2"
                      ${isSelected ? 'aria-current="true"' : ''}
                      onkeydown="handleTreeRowKeydown(event, ${node.id})">${TreeState.searchMatchIds.has(node.id) ? highlightSearchMatch(node.name, TreeState.searchQuery) : WimiEscape.html(node.name)}</span>
                ${node.is_alias_appearance ? `
                    <span class="tree-node-alias-chip"
                          data-testid="tree-node-alias-${node.id}"
                          title="This subject also appears under another parent. The primary location holds its descendants and weight settings.">
                        also here
                    </span>
                ` : (TreeState.appearanceCount.get(node.id) || 1) > 1 ? `
                    <span class="tree-node-multi-parent-chip"
                          data-testid="tree-node-multi-parent-${node.id}" data-tour-anchor="tree-row-shared-parents"
                          title="This subject lives in ${TreeState.appearanceCount.get(node.id)} places. Click to manage parents."
                          onclick="event.stopPropagation(); openParentsManagerFor(${node.id})">
                        <span class="tree-node-multi-parent-chip-arrow">↗</span>${TreeState.appearanceCount.get(node.id)}
                    </span>
                ` : ''}
                <span class="tree-node-level" data-tour-anchor="tree-row-level">${WimiEscape.html(levelName)}</span>
                <span class="tree-node-weight ${weightClass} ${confidenceClass} ${node.is_anchor ? 'anchored' : ''}" data-testid="tree-node-weight-${node.id}" data-tour-anchor="tree-row-weight" title="${WimiEscape.attr(getWeightTooltip(node))}" ${node.primary_edge_id ? `data-edge-id="${node.primary_edge_id}"` : ''}>
                    ${lockIcon}${node.is_anchor ? '<span class="weight-anchor-pin filled" data-testid="tree-node-anchor-pin-' + node.id + '" title="Anchored — won\'t auto-adjust on rebalance">⚓</span>' : ''}${weightDisplay}
                </span>
                <div class="tree-node-actions">
                    <button class="tree-action-btn" data-testid="tree-node-add-child-${node.id}" onclick="event.stopPropagation(); addChild(${node.id})" title="Add Child" aria-label="Add a child subject under ${WimiEscape.attr(node.name)}">+</button>
                    <button class="tree-action-btn danger" data-testid="tree-node-delete-${node.id}" onclick="event.stopPropagation(); confirmDeleteNode(${node.id})" title="Delete" aria-label="Delete subject ${WimiEscape.attr(node.name)}">🗑️</button>
                </div>
            </div>
            ${hasChildren ? `
                <div class="tree-node-children" data-testid="tree-node-children-${node.id}">
                    ${isExpanded ? renderNodes(node.children, level + 1) : ''}
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

// =========================================================================
// Weight bands (#347)
// =========================================================================
//
// A subject's published weight is often a band -- `exam_weight_low` to
// `exam_weight_high`, with `relative_weight` NULL -- and every figure on this
// page used to read `node.weight || node.exam_weight_low`, i.e. the band's low
// bound. Eleven Step 1 roots publishing 61-100% were totalled as "61.0%",
// which reads as "39% of the exam is missing from your outline" when the
// blueprint is fully covered. A band reads as a band, never as one number
// from inside it (#250's rule for the import preview), and a total of bands
// is the band of the lows to the highs, never rescaled (#64).
//
// The last figure reading a band as a scalar was the weight-distribution
// donut's centre, which drew `weight || exam_weight_low` normalised to 360
// degrees and printed "61%" directly under a "61-100%" stat. A ring states
// parts of a whole and cannot show a band at all, so the owner replaced it
// with the range-bar list below rather than re-palette it (#346, 2026-10-04).

/** `{low, high}` for a node; equal when the weight is a single value. */
function nodeWeightBand(node) {
    const low = node.exam_weight_low;
    const high = node.exam_weight_high;
    if (low !== null && low !== undefined && high !== null && high !== undefined
            && Number(low) !== Number(high)) {
        return { low: Number(low), high: Number(high) };
    }
    const value = Number(node.weight || node.exam_weight_low || 0);
    return { low: value, high: value };
}

/** The band of a set of nodes: lows summed, highs summed. */
function sumWeightBands(nodes) {
    return nodes.reduce((acc, n) => {
        const band = nodeWeightBand(n);
        return { low: acc.low + band.low, high: acc.high + band.high };
    }, { low: 0, high: 0 });
}

/**
 * "7.0%" for a single value, "7–11%" for a band. The two precisions match the
 * tree rows' chips, which already render a band as `7–11%`.
 */
function formatWeightBand(band) {
    if (band.low === band.high) return `${band.low.toFixed(1)}%`;
    const end = x => (Number.isInteger(x) ? String(x) : x.toFixed(1));
    return `${end(band.low)}–${end(band.high)}%`;
}

/**
 * The name of the axis the tree is showing, or null on a plain exam.
 *
 * Every count and every "nothing here" on a dimensioned exam is a count of
 * ONE axis: the dimensioned view loads that axis's subjects and nothing else.
 * A subject in no axis -- every subject an exam had before its first axis
 * was added (#605) -- is invisible to it. So on that path a figure must say
 * which axis it counted. "0 subjects across 0 roots" under "Exam Overview",
 * and "No Subjects Yet", stated something about the whole exam that the page
 * had never looked at, and on an exam holding three subjects it was false.
 *
 * Naming the axis is the whole of this fix, on purpose. Saying WHERE the
 * other subjects are, or offering to move them, is #605's decision (ask at
 * the moment the axis is added), not something an empty state may settle.
 */
function currentAxisName() {
    return (TreeState.usesDimensions && TreeState.currentDimension
        && TreeState.currentDimension.name) || null;
}

function updateStats() {
    const nodeCount = TreeState.flatNodes.size;
    const axis = currentAxisName();
    const totalWeight = sumWeightBands(TreeState.rootNodes);

    // Both spans ship empty and `hidden` (#289), because "0 subjects /
    // Total: 0%" in the markup is indistinguishable from a measured zero.
    // This is the one place that has counted, so it is the one place that may
    // show a number.
    //
    // Write, THEN reveal. The order is not observable today -- the browser
    // cannot paint between two statements of one synchronous function, so
    // revealing first would show nothing either -- but it is the order that
    // stays correct if either half ever gains an await, and it reads as what
    // it means: there is something true to show now.
    const nodeCountEl = document.getElementById('node-count');
    const totalWeightEl = document.getElementById('total-weight');
    nodeCountEl.textContent = `${nodeCount} subject${nodeCount !== 1 ? 's' : ''}`
        + (axis ? ` in ${axis}` : '');
    totalWeightEl.textContent = `Root Total: ${formatWeightBand(totalWeight)}`;
    nodeCountEl.classList.remove('hidden');
    totalWeightEl.classList.remove('hidden');

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

        // Reveal only now. The badge ships `hidden` because it names the
        // exam's weight source and, unlike the rest of this page's deferred
        // chrome, it sits in the toolbar with nothing above it hiding it --
        // so whatever it shipped was on screen for the whole of this round
        // trip. It used to ship "User Defined", which is a real answer, and
        // therefore told every student with imported official weights the
        // opposite of the truth until the await resolved (#89). Left hidden
        // on failure below: "we could not find out" is not "user defined".
        badge.classList.remove('hidden');
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

/**
 * Say what the details panel now shows (#345).
 *
 * The panel is swapped wholesale on every selection and focus stays where the
 * student is working, so without this the swap is silent to a screen reader.
 * `#details-announcer` is a polite `role="status"`; writing the same text
 * twice announces nothing, which is right -- nothing changed.
 */
function announceDetails(text) {
    const el = document.getElementById('details-announcer');
    if (el) el.textContent = text;
}

/**
 * Deselect and go back to the Exam Overview (#343).
 *
 * Selecting a subject used to be a one-way door: re-clicking the selected row
 * toggles its expansion, and nothing else on the page led back. The button
 * that calls this lives in the subject header, which is hidden as soon as the
 * overview shows, so focus is moved to the overview's heading -- left where it
 * was, it would fall to <body>.
 */
function returnToExamOverview() {
    TreeState.selectedNodeId = null;
    document.querySelectorAll('.tree-node.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.tree-node-name[aria-current]').forEach(el => el.removeAttribute('aria-current'));
    showExamOverview();
    const title = document.querySelector('#details-overview .overview-title');
    if (title) title.focus();
    // The subject's controls are hidden now and the overview's total is
    // back, so an open tip has to be rebuilt from what is on screen (#682).
    startTreeTour();
}

function showExamOverview() {
    const placeholder = document.getElementById('details-placeholder');
    const overview = document.getElementById('details-overview');
    const content = document.getElementById('details-content');

    // The overview has its own element (#341). It used to be written into
    // #details-placeholder, whose flex centring is right for a graphic and two
    // lines and wrong for anything taller than the panel: centred overflow
    // spills out of BOTH ends of the scroll box, and the top end cannot be
    // scrolled to, so the heading and all three figures were unreachable.
    // Writing it there also destroyed the placeholder's own markup (#343).
    content.classList.add('hidden');
    placeholder.classList.add('hidden');
    overview.classList.remove('hidden');
    announceDetails('Showing the exam overview');
    
    // Calculate stats
    const totalNodes = TreeState.flatNodes.size;
    const rootNodes = TreeState.rootNodes;
    const totalRootWeight = sumWeightBands(rootNodes);
    // Already escaped: this goes into the overview's innerHTML (#605).
    const axis = currentAxisName();
    const axisIn = axis ? ` in ${WimiEscape.html(axis)}` : '';

    // Count nodes by level
    // Group by the node's stored level_type, not by tree depth (#49).
    // flatNodes holds one entry per distinct subject id, so a shared child
    // is counted once no matter how many parents it appears under.
    const levelCounts = {};
    TreeState.flatNodes.forEach((node) => {
        const levelName = getNodeLevelName(node);
        levelCounts[levelName] = (levelCounts[levelName] || 0) + 1;
    });

    // Order the buckets by the exam's configured level order so the section
    // reads top-down. level_type values that aren't a configured level name
    // (imported outlines use their own vocabulary) sort after, alphabetically.
    const levelOrder = new Map(
        TreeState.hierarchyLevels.map((l, i) => [l.level_name, i])
    );
    const orderedLevelCounts = Object.entries(levelCounts).sort((a, b) => {
        const ai = levelOrder.has(a[0]) ? levelOrder.get(a[0]) : Infinity;
        const bi = levelOrder.has(b[0]) ? levelOrder.get(b[0]) : Infinity;
        return ai !== bi ? ai - bi : a[0].localeCompare(b[0]);
    });
    
    // Build overview HTML.
    //
    // `.overview-title` is an h2 and `.overview-section-title`s are h3 (#317).
    // This is the details panel's state when nothing is selected, so the
    // title is the panel's own top-level heading and sits directly under the page's
    // h1 (`#exam-name`) -- the same slot `.details-title` occupies, which is
    // already an h2. An h3 here made the tree editor's RENDERED outline skip
    // h1 -> h3 in the state the page opens in (subjects exist, nothing
    // selected), which is what the #317 audit screenshotted. The markup's own
    // two h3s are a different pair and neither is visible in that state, so
    // only tests/wimi_test/scenarios/test_heading_levels_descend.py sees this
    // one. Sizes live on both classes in tree.css, which is what leaves the
    // level free to be the one the outline implies.
    overview.innerHTML = `
        <div class="exam-overview">
            <h2 class="overview-title" tabindex="-1">📊 Exam Overview</h2>

            <p class="overview-summary">${totalNodes} subject${totalNodes !== 1 ? 's' : ''}${axisIn} across ${rootNodes.length} root${rootNodes.length !== 1 ? 's' : ''}.</p>

            <div class="overview-section">
                <h3 class="overview-section-title">Subjects by Level</h3>
                <div class="level-counts">
                    ${orderedLevelCounts.map(([level, count]) => `
                        <div class="level-count-item">
                            <span class="level-count-name">${WimiEscape.html(level)}</span>
                            <span class="level-count-value">${count}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
            
            ${rootNodes.length > 0 ? `
                <div class="overview-section">
                    <h3 class="overview-section-title">Weight by Root Subject</h3>
                    ${renderWeightRangeChart(rootNodes, totalRootWeight)}
                </div>
            ` : `
                <div class="overview-empty">
                    <p>No subjects${axisIn} yet. Click "+ Add Root Subject" to get started!</p>
                </div>
            `}
        </div>
    `;
}

// =========================================================================
// The range-bar list (#346, owner's decision 2026-10-04)
// =========================================================================
//
// WHAT THIS REPLACED, AND WHY NOT A PALETTE. The overview drew a donut over
// the roots' LOW bounds, each slice `weight / total` of 360 degrees. Two
// things were wrong with it and only one of them was a colour:
//
//   * A ring asserts parts of a whole. These are bands -- Step 1 publishes
//     7-11%, not 7% -- and no arc can be two numbers. #64's rule is that
//     coverage is surfaced, never corrected; normalising to a full ring
//     corrects it by construction. Measured on the demo profile: Blood &
//     Lymphoreticular drew 7/61 = 11.5% of the ring beside a legend row
//     reading 7.0%, under a centre reading "61%" and a stat reading
//     "61-100%". Three different quantities, one panel.
//   * `getPieColor()` held 15 literal hexes, so the swatches rendered the
//     identical rgb under `default` (#ffffff), `midnight` (#0f172a) and
//     `high_contrast` (#000000).
//
// A shared linear axis can show a band, so the colour question stops being a
// question: one series, one token. The axis is derived from the LARGEST
// weight, never from the total -- an axis scaled to the total is the donut's
// rescale wearing a different shape.
//
// The rows are real <button>s because the legend's 11 `onclick` <div>s were
// half of #304's remaining scope: 11 clickable rows, 0 tabbable, exposed to
// assistive tech as plain text.

/** Tick ladder for the shared axis; scaled, not open-ended, on purpose. */
const WEIGHT_AXIS_STEPS = [0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500];

/**
 * The axis every band is drawn against: a round ceiling at or above the
 * largest published high bound, with at most four intervals.
 *
 * Returns `null` when nothing carries a weight, which is a real state on a
 * tree a student has only just started -- the caller then draws names and
 * figures with no scale rather than eleven marks stacked on the origin.
 */
function weightAxisFor(bands) {
    const maxHigh = bands.reduce((m, b) => Math.max(m, b.high), 0);
    if (!(maxHigh > 0)) return null;
    let step = WEIGHT_AXIS_STEPS[WEIGHT_AXIS_STEPS.length - 1];
    for (const candidate of WEIGHT_AXIS_STEPS) {
        if (maxHigh / candidate <= 4) { step = candidate; break; }
    }
    const max = Math.ceil(maxHigh / step) * step;
    const ticks = [];
    for (let v = 0; v <= max + 1e-9; v += step) {
        ticks.push(Math.round(v * 1000) / 1000);
    }
    return { max, step, ticks };
}

/** One row: the subject, its band on the shared axis, the band in text. */
function renderWeightRangeRow(node, axis) {
    const band = nodeWeightBand(node);
    const text = formatWeightBand(band);
    // Two escapers, deliberately. `escapeHtml` leaves `"` alone, which is
    // right for text content and ends the aria-label early on a subject
    // called `Cardio "fast" track` -- announced as `Cardio ` while the
    // visible half stayed perfectly correct.
    const name = WimiEscape.html(node.name);
    const nameAttr = WimiEscape.attr(node.name);
    // `left` is the low bound and `width` the band's own length. A bar
    // starting at 0 with a length taken from the low bound is exactly the
    // reading this replaced, so the offset is the load-bearing half.
    const left = axis ? (band.low / axis.max) * 100 : 0;
    const width = axis ? ((band.high - band.low) / axis.max) * 100 : 0;
    const isPoint = band.low === band.high;
    const track = axis ? `
                <span class="weight-range-track" aria-hidden="true">
                    <span class="weight-range-mark${isPoint ? ' is-point' : ''}"
                          style="--band-left: ${left.toFixed(3)}%; --band-width: ${width.toFixed(3)}%"></span>
                </span>` : '';
    return `
            <li class="weight-range-item">
                <button type="button" class="weight-range-row"
                        onclick="selectNode(${node.id})"
                        data-testid="overview-weight-row-${node.id}"
                        aria-label="${nameAttr}, ${text} of the exam">
                    <span class="weight-range-name">${name}</span>${track}
                    <span class="weight-range-value">${text}</span>
                </button>
            </li>`;
}

/** The axis ruler, drawn once under the rows they all share. */
function renderWeightRangeAxis(axis) {
    const ticks = axis.ticks.map((v, i) => {
        const pos = (v / axis.max) * 100;
        const edge = i === 0 ? ' is-first'
            : (i === axis.ticks.length - 1 ? ' is-last' : '');
        return `<span class="weight-range-tick${edge}" `
            + `style="left: ${pos.toFixed(3)}%">${v}%</span>`;
    }).join('');
    return `
            <div class="weight-range-axis" aria-hidden="true">
                <span class="weight-range-scale">${ticks}</span>
            </div>`;
}

/**
 * The sentence the three-box stat row became.
 *
 * A tile can only hold a scalar, and these quantities are bands: the "Total
 * Weight" tile rendered "61-100%" wrapped across two lines inside a 103 px
 * box. The sentence says the same thing in one breath and can name the axis
 * it is talking about, which matters because coverage is per dimension and
 * is never pooled (#241).
 */
function weightRangeTotalSentence(bands, total) {
    if (!(total.high > 0)) {
        return 'No weights are set on these root subjects yet.';
    }
    const axis = currentAxisName();
    const scope = axis ? ` for ${WimiEscape.html(axis)}` : '';
    const noun = bands.some(b => b.low !== b.high)
        ? 'Published ranges' : 'Root weights';
    return `${noun}${scope} total ${formatWeightBand(total)} of the exam.`;
}

function renderWeightRangeChart(rootNodes, total) {
    const bands = rootNodes.map(nodeWeightBand);
    const axis = weightAxisFor(bands);
    // `--axis-step` draws the same gridlines inside every track, so the rows
    // read against one scale rather than eleven. Defined here because it is
    // a property of this exam's numbers, not of the stylesheet.
    const style = axis
        ? ` style="--axis-step: ${((axis.step / axis.max) * 100).toFixed(3)}%"`
        : '';
    // The tour anchor only when there is a total: its tip explains a total
    // past 100%, which is false of "No weights are set", and a tip shown
    // there is recorded as seen and never reaches the tree it is about.
    return `
        <div class="weight-range-chart"${style}>
            <ul class="weight-range-list${axis ? '' : ' is-unweighted'}" role="list">
                ${rootNodes.map(node => renderWeightRangeRow(node, axis)).join('')}
            </ul>
            ${axis ? renderWeightRangeAxis(axis) : ''}
            <p class="weight-range-total"${total.high > 0 ? ' data-tour-anchor="tree-weight-range-total"' : ''}>${weightRangeTotalSentence(bands, total)}</p>
        </div>`;
}

function showNodeDetails(nodeId) {
    const node = TreeState.flatNodes.get(nodeId);
    if (!node) return;

    const placeholder = document.getElementById('details-placeholder');
    const overview = document.getElementById('details-overview');
    const content = document.getElementById('details-content');

    placeholder.classList.add('hidden');
    overview.classList.add('hidden');
    content.classList.remove('hidden');
    announceDetails(`Showing details for ${node.name}`);

    // Basic info. The level shown must be the node's own level_type (#49)
    // — anything else contradicts the Level Type dropdown that wrote it.
    const levelName = getNodeLevelName(node);

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

    // The panel's own controls are on screen from here (#682). The weight
    // editor and the parent rows arrive later and re-start it themselves;
    // initWeightEditor has already dropped the previous subject's anchors.
    startTreeTour();
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

        // `alias_type` is NOT interpolated (#597). It reached a class
        // attribute raw here, which is the same break-out measured in the
        // alias manager, and `alias_type`'s CHECK constraint only holds on a
        // database WIMI wrote -- an installed profile brings its own schema.
        // The per-type class is styled for exactly the four known values
        // (aliases.css:209-224), so an unrecognised one is dropped rather than
        // escaped: it was styling nothing either way.
        const knownAliasTypes = new Set(
            (window.AliasManager && AliasManager.ALIAS_TYPES || [])
                .map(t => t.value));

        const aliasHtml = displayed.map(a => {
            const typeClass = knownAliasTypes.has(a.alias_type)
                ? ` alias-type-${a.alias_type}` : '';
            return `<span class="alias-chip${typeClass}">`
                + `${WimiEscape.html(a.alias_name)}</span>`;
        }).join('');

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
    const levelName = getNodeLevelName(node);

    const parts = [
        `<span class="details-subtitle-level"
               id="detail-level"
               data-testid="tree-detail-level">${WimiEscape.html(levelName)}</span>`,
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
                       data-testid="tree-detail-dimension">in ${WimiEscape.html(dim.name)}</span>`
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
 *
 * THE META LINE SAYS WHAT THE PARENT DOES, NOT WHAT WE CALL IT (#346, owner
 * 2026-10-10). It read `primary · canonical breadcrumb` and
 * `alias · also-here appearance`, which are our words for the data model:
 * "canonical" and "appearance" are schema vocabulary, and "alias" collides
 * with `subject_aliases`, a different feature with its own section three
 * headings further down this same panel.
 *
 * The replacements are chapter 11's own two facts, in its own words. That
 * chapter's "What the primary parent is for" says the primary parent decides
 * **the breadcrumb** and **which appearance carries the children**, and it
 * calls a non-primary appearance "also here" — the same phrase the tree row's
 * chip uses. So the panel, the tree and the manual now agree on one wording
 * instead of three.
 *
 * TWO THINGS DELIBERATELY NOT SAID HERE, both verified rather than assumed:
 *
 * - **Rollups.** The marker button's own `title` claims the primary parent is
 *   "used for breadcrumbs and rollups". No analytics query reads
 *   `subject_edges.is_primary` — grep `analytics.py`, `advanced_analytics.py`,
 *   `dimensions.py` and `graph.py` and it appears in none of them. What
 *   scopes a rollup is `entry_subject_mappings.primary_parent_id`, which is
 *   per entry; the primary edge is only its default, via `getEdgesForChild`
 *   ordering `is_primary DESC`. True transitively, so not worth a line here,
 *   and chapter 12 is where it belongs.
 * - **Weight settings.** The tree row's `also here` chip says the primary
 *   location "holds its descendants and weight settings". The second half is
 *   legacy: `update_subject_relative_weight` keys on the primary edge, but the
 *   panel writes through `setExplicitWeight(edge_id, …)`, which is per edge —
 *   that is why the weight header names the pairing at all. Chapter 11 says so
 *   outright ("A weight in WIMI belongs to the pairing of a subject with one
 *   of its parents"). The chip is a tree row rather than this panel, so it is
 *   **#443**, filed 2026-10-06 and confirmed since, not fixed here. (I
 *   re-found it independently and filed a duplicate, #734, now closed --
 *   search the tracker before filing.)
 *
 * Keep a replacement under roughly 33 characters: at 12px in the 225px parents
 * column, 33 fits on one line and 38 wraps. Measured per candidate.
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
                        ${isPrimary ? '' : 'data-tour-anchor="tree-parent-make-primary"'}
                        title="${isPrimary ? 'Primary parent — used for breadcrumbs and rollups' : 'Click to make this the primary parent'}"
                        ${isPrimary ? 'disabled' : ''}
                        onclick="switchPrimaryParentTo(${nodeId}, ${p.parent_id})">
                    ${isPrimary ? '★' : '○'}
                </button>
                <div class="parent-row-content">
                    <div class="parent-row-name">${WimiEscape.html(p.parent_name)}</div>
                    ${breadcrumbPath ? `<div class="parent-row-path">${WimiEscape.html(breadcrumbPath)}</div>` : ''}
                    <div class="parent-row-meta">
                        ${isPrimary ? 'Sets the breadcrumb and children' : 'Also here, children not repeated'}
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

    // A circle is on screen only from here, and only for a subject with a
    // parent that is not primary, which is the one row the tour's
    // make-primary step is about (#682).
    startTreeTour();
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
        el.innerHTML = `<p class="text-muted text-sm parents-picker-empty">${WimiEscape.html(emptyMessage || 'No matches.')}</p>`;
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
                <span class="parents-picker-result-name">${WimiEscape.html(r.name)}</span>
                ${r.path ? `<span class="parents-picker-result-path">${WimiEscape.html(r.path)}</span>` : ''}
                ${disabled ? `<span class="parents-picker-result-reason" title="${WimiEscape.html(r._disabledReason)}">${WimiEscape.html(r._disabledReason)}</span>` : ''}
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

/**
 * The display label for a node's hierarchy level (issue #49).
 *
 * Reads the node's own stored ``level_type`` — the value the "Level Type"
 * dropdown writes on create, the one the import format carries, and the one
 * the analytics drilldown groups by. It deliberately does NOT derive the
 * label from tree depth.
 *
 * Depth is not merely the wrong source here, it is an unsound one: in a
 * polyhierarchy a node has no single depth. A subject with two parents at
 * different levels sits at two depths at once, and ``buildFlatNodeMap`` says
 * itself that ``_parent`` "is set to the parent of whichever appearance was
 * visited last and is best-effort". So a depth-derived label is ambiguous
 * (which appearance won the flat-map race?) and inconsistent (the same
 * subject wore two different level names in one tree — "Subsystem" under one
 * parent, "Topic" under another). ``level_type`` is stored per node and has
 * neither problem.
 *
 * ``fallbackDepth`` is only consulted for rows carrying no ``level_type`` at
 * all. The column is NOT NULL in the schema, so this is belt-and-braces for
 * payloads that predate a field or omit it.
 */
function getNodeLevelName(node, fallbackDepth) {
    const stored = node && node.level_type;
    if (typeof stored === 'string' && stored.trim()) {
        return stored.trim();
    }
    const depth = fallbackDepth || (node ? getNodeLevel(node) : 1);
    return TreeState.hierarchyLevels[depth - 1]?.level_name || `Level ${depth}`;
}

/**
 * Where ``levelName`` sits in the exam's configured levels, or -1.
 *
 * The inverse of ``getNodeLevelName``: that turns a node into the level
 * name it stores, this turns a level name into its position in
 * ``TreeState.hierarchyLevels`` so the next one along can be found.
 * -1 means the name is not configured for this exam — see
 * ``suggestChildLevelName`` for what that means.
 */
function getLevelIndex(levelName) {
    if (typeof levelName !== 'string' || !levelName.trim()) return -1;
    const wanted = levelName.trim();
    return TreeState.hierarchyLevels.findIndex(
        level => level.level_name === wanted
    );
}

/**
 * The level to pre-select for a new child of ``parentNode`` (issue #82).
 *
 * Reads the parent's **stored** ``level_type`` and takes the next
 * configured level along. It must not use ``getNodeLevel`` — that is
 * tree depth, and depth is both wrong and unsound here:
 *
 * - A parent stored as 'System' can sit at depth 2 (nothing forces the
 *   two to agree), and pre-#82 the modal suggested
 *   ``hierarchyLevels[2]`` = 'Topic', skipping 'Subsystem'. Most users
 *   accept the pre-filled default, so the wrong name was what landed in
 *   ``subject_nodes.level_type``. This is a WRITE path, which is why it
 *   was split out of #49's four display sites.
 * - In a polyhierarchy a node has no single depth. ``buildFlatNodeMap``
 *   sets ``_parent`` to "whichever appearance was visited last" and says
 *   so, making a depth-derived suggestion depend on flat-map traversal
 *   order. ``level_type`` is per node and has no such ambiguity.
 *
 * Two cases repeat the parent's own level rather than inventing one:
 * the bottom of the list (no next level exists), and a level name the
 * exam's configured list does not contain (there is no derivable "one
 * below Domain"). The caller passes the result to
 * ``renderLevelOptions`` so an unconfigured name is still selectable.
 * The same fall-throughs live in ``createSubjectNode``
 * (``src/app/bridge_domains/hierarchy.py``) for callers that omit the
 * field entirely; keep the two in step.
 */
function suggestChildLevelName(parentNode) {
    const parentLevelName = getNodeLevelName(parentNode);
    const index = getLevelIndex(parentLevelName);
    if (index === -1) return parentLevelName;
    return TreeState.hierarchyLevels[index + 1]?.level_name || parentLevelName;
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
    
    const total = sumWeightBands(siblings);

    chart.innerHTML = siblings.map(s => {
        const band = nodeWeightBand(s);
        const isCurrent = s.id === node.id;
        
        return `
            <div class="sibling-bar ${isCurrent ? 'current' : ''}">
                <span class="sibling-name" title="${WimiEscape.html(s.name)}">${WimiEscape.html(s.name)}</span>
                <div class="sibling-bar-container">
                    <div class="sibling-bar-fill" style="width: ${band.low}%"></div>
                </div>
                <span class="sibling-value">${formatWeightBand(band)}</span>
            </div>
        `;
    }).join('');
    
    // Valid when the band can reach 100%, the same test #64's coverage uses.
    const isValid = total.low <= 100.05 && total.high >= 99.95;
    totalEl.innerHTML = `Total: <span>${formatWeightBand(total)}</span>`;
    totalEl.className = `siblings-total ${isValid ? '' : 'invalid'}`;
}

function renderChildrenList(node) {
    const list = document.getElementById('children-list');
    
    if (!node.children || node.children.length === 0) {
        list.innerHTML = '<p class="text-muted text-sm">No children</p>';
        return;
    }
    
    list.innerHTML = node.children.map(child => {
        const weight = formatWeightBand(nodeWeightBand(child));
        return `
            <div class="child-item" onclick="selectNode(${child.id}); toggleNode(${node.id}, true);">
                <span class="child-icon">📄</span>
                <span class="child-name">${WimiEscape.html(child.name)}</span>
                <span class="child-weight">${weight}</span>
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
    
    // Re-render rather than flipping the CSS class, because a collapsed
    // subtree is no longer IN the DOM to reveal (#177). This used to cost
    // 0.1 ms against a tree where every node was always rendered and
    // `expanded` was decoration; it now costs one render of whatever is
    // actually open, which on a freshly loaded outline is a few dozen rows
    // rather than 2,752.
    //
    // Deliberately not a targeted DOM patch. `TreeState.flatNodes` keeps
    // only the LAST occurrence of a node id (see buildFlatNodeMap), so on a
    // polyhierarchy node `flatNodes.get(id).children` may belong to a
    // different appearance than the one that was clicked -- filling a
    // container from it would render the primary's descendants under an
    // alias, or nothing under the primary. Rendering from the root cannot
    // get that wrong.
    renderTree();
}

function expandAll() {
    // Walk the tree, not TreeState.flatNodes. flatNodes keeps only the
    // LAST appearance of each id (see buildFlatNodeMap), so a subject that
    // appears twice -- once as an alias leaf, once as the primary with
    // descendants -- may be stored under the childless appearance and then
    // never expanded. Measured on the seeded USMLE outline: 325 parents by
    // appearance, 315 by flatNodes, so 10 subtrees stayed shut.
    //
    // This was always wrong and was always invisible, because collapsing
    // used to be cosmetic -- every node sat in the DOM whatever
    // expandedNodes said, so an unexpanded parent still had its children
    // there to reveal. Now that rendering follows expansion (#177), those
    // 10 subtrees would simply not appear.
    const expandParents = (nodes) => {
        for (const node of nodes) {
            if (node.children && node.children.length > 0) {
                TreeState.expandedNodes.add(node.id);
                expandParents(node.children);
            }
        }
    };
    expandParents(TreeState.rootNodes);
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
    // #304: whether to hand focus back to the row afterwards. Only when the
    // rename input still HAS focus -- this function is also reached from the
    // input's own `onblur`, i.e. because the student clicked somewhere else,
    // and focusing the row then would yank them back out of wherever they
    // just went. Read before the await, because the await is where focus
    // moves.
    const cameFromTheKeyboard = inlineEditHasFocus();

    if (!newName.trim()) {
        cancelInlineEdit(nodeId, cameFromTheKeyboard);
        return;
    }
    
    const node = TreeState.flatNodes.get(nodeId);
    if (!node || node.name === newName.trim()) {
        cancelInlineEdit(nodeId, cameFromTheKeyboard);
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
    if (cameFromTheKeyboard) focusTreeRow(nodeId);
    if (TreeState.selectedNodeId === nodeId) {
        showNodeDetails(nodeId);
    }
}

/** Does the inline rename input currently hold keyboard focus? */
function inlineEditHasFocus() {
    const active = document.activeElement;
    return !!(active && active.classList
              && active.classList.contains('tree-node-name-input'));
}

function cancelInlineEdit(nodeId, restoreFocus) {
    // Default to the DOM's answer so the one-argument callers (the Escape
    // key handler, and anything outside this module) still behave.
    const giveFocusBack = restoreFocus === undefined
        ? inlineEditHasFocus()
        : restoreFocus;
    TreeState.editingNodeId = null;
    renderTree();
    if (giveFocusBack) focusTreeRow(nodeId);
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

    // The tour's level step (#682) says the value is suggested from the
    // parent's level, so only the child branch carries its anchor.
    levelSelect.removeAttribute('data-tour-anchor');

    if (parentId === null) {
        title.textContent = 'Add Root Subject';
        // Rebuild from the configured levels, dropping any name a
        // previous open appended for an unconfigured parent (#82).
        renderLevelOptions();
        levelSelect.value = TreeState.hierarchyLevels[0]?.level_name || 'System';
        updateWeightModeForModal('absolute');
    } else {
        parentNode = TreeState.flatNodes.get(parentId);
        title.textContent = `Add Child to "${parentNode.name}"`;

        // Set level to one below the parent's STORED level_type — never
        // its tree depth (#82). ``suggestChildLevelName`` may return a
        // name outside the configured list, which is why the dropdown is
        // rebuilt with it before the value is assigned: a value that is
        // not one of the options silently does not stick.
        const suggestedLevel = suggestChildLevelName(parentNode);
        renderLevelOptions(suggestedLevel);
        levelSelect.value = suggestedLevel;
        levelSelect.setAttribute('data-tour-anchor', 'tree-add-child-level');

        // If parent has official weight, child should use relative weight
        if (parentNode.weight_source === 'official' || parentNode.weight_source === 'derived') {
            updateWeightModeForModal('relative');
        } else {
            updateWeightModeForModal('absolute');
        }
    }

    modal.classList.add('active');
    document.getElementById('modal-node-name').focus();
    startTreeTour();
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
    // The closed modal still has a box (it fades by `visibility`, which the
    // tour cannot see), so dropping the anchor is what closes its tip.
    document.getElementById('modal-node-level').removeAttribute('data-tour-anchor');
    startTreeTour();
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
// Both outcomes of the pending delete, from api.getSubjectDeletePreview.
// Cached so toggling the promote checkbox re-renders without a round trip.
let deleteNodePreview = null;

/**
 * Open the delete confirmation modal for a subject.
 *
 * Issue #15: the old warning counted `node.children`, i.e. the *rendered*
 * children, which come from `subject_edges`, while the backend walked the
 * legacy `subject_nodes.parent_id` column — so the modal promised to
 * delete a set the delete did not touch. The counts now come from the
 * backend's own plan for this delete, so the modal and the mutation
 * cannot disagree.
 */
async function confirmDeleteNode(nodeId) {
    const node = TreeState.flatNodes.get(nodeId);
    if (!node) return;

    deleteNodeTarget = node;
    deleteNodePreview = null;

    document.getElementById('delete-node-name').textContent = node.name;

    const promoteRow = document.getElementById('delete-promote-row');
    const promoteToggle = document.getElementById('delete-promote-children');
    promoteToggle.checked = false;
    promoteRow.classList.add('hidden');

    const previewEl = document.getElementById('delete-preview');
    previewEl.textContent = 'Checking what this will affect…';

    document.getElementById('delete-node-modal').classList.add('active');
    // The tour's Delete step (#682) exists only while this modal is open: a
    // closed modal keeps its box, so an anchor in the markup would resolve.
    document.getElementById('delete-node-confirm')
        .setAttribute('data-tour-anchor', 'tree-delete-confirm');
    promoteToggle.removeAttribute('data-tour-anchor');
    startTreeTour();

    try {
        const preview = await api.getSubjectDeletePreview(nodeId);
        // The user may have cancelled or moved on while we were waiting.
        if (!deleteNodeTarget || deleteNodeTarget.id !== nodeId) return;
        deleteNodePreview = preview;

        const exclusive = preview.exclusive_direct_children || [];
        const label = document.getElementById('delete-promote-label');
        label.textContent = exclusive.length === 1
            ? `Keep "${exclusive[0].name}" — move it to the top level`
            : `Keep the ${exclusive.length} direct children — move them to the top level`;
        promoteRow.classList.toggle('hidden', exclusive.length === 0);
        // The checkbox is on screen only from here, and only when there are
        // children of this subject alone to keep (#682).
        if (exclusive.length) {
            promoteToggle.setAttribute('data-tour-anchor', 'tree-delete-promote');
            startTreeTour();
        }

        renderDeletePreview();
    } catch (error) {
        previewEl.textContent =
            `Could not work out what this delete affects: ${error.message}`;
    }
}

/** Render the cached preview for whichever mode the checkbox is on. */
function renderDeletePreview() {
    const previewEl = document.getElementById('delete-preview');
    if (!deleteNodePreview) return;

    const promote = document.getElementById('delete-promote-children').checked;
    const plan = promote
        ? deleteNodePreview.modes.promote
        : deleteNodePreview.modes.delete;

    // The target itself is always the first entry in `archived`; the rest
    // are the subjects that have no other parent to fall back on.
    const alsoArchived = (plan.archived || []).slice(1);
    const detached = plan.detached || [];
    const promoted = plan.promoted || [];
    const promotedIds = new Set(promoted.map(p => p.id));
    // A promoted child is already described by its own bullet.
    const reparented = detached.filter(d => !promotedIds.has(d.child_id));

    const lines = [];
    if (alsoArchived.length) {
        lines.push(
            `<li class="delete-preview-danger">${alsoArchived.length} other ` +
            `subject${alsoArchived.length === 1 ? '' : 's'} will be deleted too ` +
            `(nothing else holds ${alsoArchived.length === 1 ? 'it' : 'them'}): ` +
            `${formatDeletePreviewNames(alsoArchived.map(n => n.name))}</li>`
        );
    }
    if (promoted.length) {
        lines.push(
            `<li>${promoted.length} subject${promoted.length === 1 ? '' : 's'} ` +
            `will move to the top level: ` +
            `${formatDeletePreviewNames(promoted.map(n => n.name))}</li>`
        );
    }
    if (reparented.length) {
        lines.push(
            `<li>${reparented.length} shared subject` +
            `${reparented.length === 1 ? '' : 's'} will be kept and stay under ` +
            `${reparented.length === 1 ? 'its' : 'their'} other parent: ` +
            `${formatDeletePreviewNames(reparented.map(n => n.child_name))}</li>`
        );
    }
    if (plan.entries_unscoped) {
        lines.push(
            `<li>${plan.entries_unscoped} entr` +
            `${plan.entries_unscoped === 1 ? 'y' : 'ies'} pinned to this subject ` +
            `will go back to counting under every parent of their topic.</li>`
        );
    }

    if (!lines.length) {
        previewEl.innerHTML =
            `<span data-testid="tree-delete-preview-summary">Only ` +
            `"${WimiEscape.html(deleteNodePreview.node_name)}" will be deleted. ` +
            `Nothing else is affected.</span>`;
        return;
    }

    previewEl.innerHTML =
        `<span data-testid="tree-delete-preview-summary">Deleting ` +
        `"${WimiEscape.html(deleteNodePreview.node_name)}" will also:</span>` +
        `<ul>${lines.join('')}</ul>` +
        `<span class="delete-preview-note">Deleted subjects are archived, ` +
        `not erased.</span>`;
}

/** "A, B and 3 more" — keeps a wide subtree from overflowing the modal. */
function formatDeletePreviewNames(names, limit = 3) {
    const shown = names.slice(0, limit).map(WimiEscape.html);
    const rest = names.length - shown.length;
    if (rest > 0) shown.push(`${rest} more`);
    if (shown.length === 1) return shown[0];
    return `${shown.slice(0, -1).join(', ')} and ${shown[shown.length - 1]}`;
}

function hideDeleteModal() {
    document.getElementById('delete-node-modal').classList.remove('active');
    deleteNodeTarget = null;
    deleteNodePreview = null;
    document.getElementById('delete-node-confirm').removeAttribute('data-tour-anchor');
    document.getElementById('delete-promote-children').removeAttribute('data-tour-anchor');
    startTreeTour();
}

async function executeDeleteNode() {
    if (!deleteNodeTarget) return;

    const promoteChildren =
        document.getElementById('delete-promote-children').checked;

    try {
        await api.deleteSubjectNode(deleteNodeTarget.id, promoteChildren);

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
// Archived subjects panel (#37)
// =========================================================================
//
// A flat list, not a "show archived" toggle inside the tree: an archived
// subject frequently has no valid position any more -- that is the whole of
// #15 -- so drawing it in place would be a lie.
//
// Collapsed by default, and the whole section is hidden when nothing is
// archived, so a healthy tree pays no attention for it.
//
// Restore is offered per *event*, not per row: one deletion archived a
// subtree, stripped edges, cleared entry contexts and hid relations, and
// restore undoes that operation. A dimension archive is one event too, even
// though it produced several subject batches underneath -- the backend
// refuses to restore those individually, so they are never listed.

const ARCHIVED_PANEL_STATE = { batches: [], busy: null };

async function refreshArchivedPanel() {
    const panel = document.getElementById('archived-panel');
    const list = document.getElementById('archived-list');
    const count = document.getElementById('archived-panel-count');
    if (!panel || !list || !count) return;

    let batches = [];
    try {
        const payload = await api.getArchivedBatches(TreeState.examContextId);
        batches = (payload && payload.batches) || [];
    } catch (error) {
        // A panel that cannot load is not worth a toast on every page load --
        // the tree itself is fine and this is supplementary. Say it in the
        // panel, where somebody looking for it will see it.
        ARCHIVED_PANEL_STATE.batches = [];
        panel.classList.remove('hidden');
        count.textContent = '!';
        list.innerHTML =
            '<li class="archived-empty">Could not load archived deletions: ' +
            WimiEscape.html(error.message || String(error)) + '</li>';
        return;
    }

    ARCHIVED_PANEL_STATE.batches = batches;
    count.textContent = String(batches.length);

    if (!batches.length) {
        // Hidden rather than shown-empty: nothing archived is the normal
        // state and does not need a row of its own.
        panel.classList.add('hidden');
        panel.classList.remove('open');
        setArchivedPanelExpanded(false);
        list.innerHTML = '';
        return;
    }

    panel.classList.remove('hidden');
    list.innerHTML = batches.map(renderArchivedItem).join('');
    // Read the batch from data attributes rather than an inline onclick (#548).
    // An inline handler put the id in a JS string, and HTML escaping does not
    // protect that: the parser decodes `&#39;` back to `'` before the script
    // runs. Ids are uuid4 when WIMI writes them, but a .wimi import installs a
    // whole database. Assigned, not added, so a re-render never stacks it.
    list.onclick = (event) => {
        const button = event.target.closest('.archived-restore-btn');
        const item = button && button.closest('.archived-item');
        if (!item) return;
        restoreArchivedBatch(item.dataset.batchId, item.dataset.batchKind);
    };
    // Its tour step can show only now: this load is not awaited by init, so
    // it may land after the gate's release started the tour.
    startTreeTour();
}

function renderArchivedItem(batch) {
    const isDimension = batch.kind === 'dimension';
    const name = isDimension
        ? (batch.dimension_name || 'a dimension')
        : (batch.root_node_name || 'a subject');

    // "was under Cardiovascular System" -- the listing carries `parents` for
    // exactly this, so no second round trip is needed.
    let where;
    if (isDimension) {
        const trees = batch.tree_count || 0;
        where = `dimension, ${trees} ${trees === 1 ? 'tree' : 'trees'}`;
    } else if (batch.parents && batch.parents.length) {
        where = 'was under ' + batch.parents
            .map(parent => WimiEscape.html(parent.name))
            .join(', ');
    } else {
        where = 'was a top-level subject';
    }

    const subjects = batch.node_count || 0;
    const subjectLabel = `${subjects} ${subjects === 1 ? 'subject' : 'subjects'}`;
    const when = formatArchivedWhen(batch.deleted_at);

    return `
        <li class="archived-item${isDimension ? ' archived-item-dimension' : ''}"
            data-batch-id="${WimiEscape.attr(batch.batch_id)}"
            data-batch-kind="${WimiEscape.attr(batch.kind)}"
            data-testid="tree-archived-item">
            <span class="archived-item-main">
                <span class="archived-item-name">${WimiEscape.html(name)}</span>
                <span class="archived-item-meta">${where} &middot; ${subjectLabel}${when}</span>
            </span>
            <button class="archived-restore-btn"
                    data-testid="tree-archived-restore">Restore</button>
        </li>`;
}

function formatArchivedWhen(deletedAt) {
    if (!deletedAt) return '';
    // SQLite writes `YYYY-MM-DD HH:MM:SS` in UTC with no zone marker, which
    // `new Date()` reads as local time -- enough to land "just now" a few
    // hours out. Parse as UTC explicitly.
    const parsed = new Date(String(deletedAt).replace(' ', 'T') + 'Z');
    if (isNaN(parsed.getTime())) return '';

    const days = Math.floor((Date.now() - parsed.getTime()) / 86400000);
    if (days < 1) return ', deleted today';
    if (days === 1) return ', deleted yesterday';
    if (days < 30) return `, deleted ${days} days ago`;
    return `, deleted ${parsed.toLocaleDateString()}`;
}

async function restoreArchivedBatch(batchId, kind) {
    if (ARCHIVED_PANEL_STATE.busy) return;
    ARCHIVED_PANEL_STATE.busy = batchId;

    const button = document.querySelector(
        `.archived-item[data-batch-id="${CSS.escape(batchId)}"] .archived-restore-btn`);
    if (button) {
        button.disabled = true;
        button.textContent = 'Restoring...';
    }

    try {
        const result = await api.restoreBatch(batchId, kind);

        // The summary names what was skipped and why -- the owner's decision
        // that a partial restore must not read as a complete one. Showing
        // only "Restored" would be the same defect #240 fixed at the bridge.
        Toast.success('Restored', result.summary || 'Restored.');

        // #260's note: a subject whose parent is still archived comes back at
        // the top level. Not an error, but the student would otherwise go
        // looking for it in the wrong place.
        (result.notes || []).forEach(note => {
            Toast.info('Where it went', note.message);
        });

        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            invalidateDimensionCache(TreeState.currentDimensionId);
        }
        // A dimension restore changes which dimensions exist, so the selector
        // has to be rebuilt rather than just the tree redrawn.
        if (kind === 'dimension' && typeof loadDimensions === 'function') {
            await loadDimensions();
        }
        await loadHierarchy();
        reapplySearchIfActive();
    } catch (error) {
        // Every refusal from the planner is a sentence the student can act on
        // ("another dimension is already called X", "restore that parent's
        // deletion first"), so it is shown verbatim.
        Toast.error('Could not restore', error.message || String(error));
    } finally {
        ARCHIVED_PANEL_STATE.busy = null;
        await refreshArchivedPanel();
    }
}

// =========================================================================
// Subjects not in any axis (#605, owner 2026-10-10)
// =========================================================================
//
// Adding the first axis to an exam that already has subjects leaves every
// one of them at `dimension_id NULL`. The dimensioned tree filters on
// dimension_id and the plain tree is never drawn once an exam has an axis,
// so the student's whole tree vanishes with no warning and nothing to
// click. `exam_uses_dimensions` is DERIVED -- one active dimension flips
// the exam immediately -- so there is no migration and no moment to hook.
//
// The owner chose a panel on the Archived-subjects pattern that CAN MOVE
// THEM IN: a place the student resolves this from, not a holding pen, and
// explicitly not a banner. Mirrors that panel deliberately, including the
// `hidden` on the body so a collapsed panel is out of the accessibility
// tree rather than merely invisible.
//
// It is refreshed from BOTH load paths. The plain path's call returns an
// empty list (a dimensionless exam has no axis to be outside of) and the
// panel hides itself -- but it is wired anyway, because the
// dimension/plain split is exactly where this gets forgotten.

const UNASSIGNED_PANEL_STATE = { subjects: [], busy: null };

async function refreshUnassignedPanel() {
    const panel = document.getElementById('unassigned-panel');
    const list = document.getElementById('unassigned-list');
    const count = document.getElementById('unassigned-panel-count');
    if (!panel || !list || !count) return;

    let subjects = [];
    try {
        const payload = await api.getSubjectsOutsideAnyAxis(TreeState.examContextId);
        subjects = (payload && payload.subjects) || [];
    } catch (error) {
        // Same judgement as the Archived panel: a supplementary panel that
        // cannot load is not worth a toast on every tree render. Say it
        // where somebody looking for it will see it.
        UNASSIGNED_PANEL_STATE.subjects = [];
        panel.classList.remove('hidden');
        count.textContent = '!';
        list.innerHTML =
            '<li class="unassigned-empty">Could not check for subjects outside your axes: ' +
            WimiEscape.html(error.message || String(error)) + '</li>';
        return;
    }

    UNASSIGNED_PANEL_STATE.subjects = subjects;
    count.textContent = String(subjects.length);

    if (!subjects.length) {
        panel.classList.add('hidden');
        panel.classList.remove('open');
        setUnassignedPanelExpanded(false);
        list.innerHTML = '';
        return;
    }

    panel.classList.remove('hidden');
    renderUnassignedList(subjects);
}

function renderUnassignedList(subjects) {
    const list = document.getElementById('unassigned-list');
    if (!list) return;
    list.innerHTML = '';

    const axes = (TreeState.dimensions || []).filter(d => d.status !== 'archived');

    subjects.forEach(subject => {
        const row = document.createElement('li');
        row.className = 'unassigned-row';
        row.setAttribute('data-testid', `tree-unassigned-row-${subject.subject_id}`);

        // Built from text nodes, never innerHTML: a subject name is text a
        // student typed or imported, and an imported profile can carry
        // anything (#594, #548).
        const name = document.createElement('span');
        name.className = 'unassigned-row-name';
        name.textContent = subject.name;
        row.appendChild(name);

        const meta = document.createElement('span');
        meta.className = 'unassigned-row-meta';
        // The count is what tells a student what travels with the row --
        // "Cardiovascular System" alone does not say 340 subjects move.
        meta.textContent = subject.subtree_count === 1
            ? 'on its own'
            : `with ${subject.subtree_count - 1} underneath`;
        row.appendChild(meta);

        const actions = document.createElement('span');
        actions.className = 'unassigned-row-actions';

        if (!axes.length) {
            // Reachable: every axis archived while subjects sit outside.
            // #174 -- do not offer a press when there is nothing to press.
            const none = document.createElement('span');
            none.className = 'unassigned-row-note';
            none.textContent = 'No active axis to move it into';
            actions.appendChild(none);
        } else {
            const select = document.createElement('select');
            select.className = 'unassigned-row-select';
            select.setAttribute('data-testid',
                `tree-unassigned-select-${subject.subject_id}`);
            select.setAttribute('aria-label', `Move ${subject.name} into an axis`);
            axes.forEach(axis => {
                const option = document.createElement('option');
                option.value = String(axis.id);
                option.textContent = axis.name;
                select.appendChild(option);
            });
            actions.appendChild(select);

            const button = document.createElement('button');
            button.className = 'btn btn-secondary btn-sm unassigned-row-move';
            button.type = 'button';
            button.setAttribute('data-testid',
                `tree-unassigned-move-${subject.subject_id}`);
            button.textContent = 'Move in';
            button.addEventListener('click', () => {
                moveUnassignedSubjectInto(subject.subject_id, Number(select.value));
            });
            actions.appendChild(button);
        }

        row.appendChild(actions);
        list.appendChild(row);
    });
}

async function moveUnassignedSubjectInto(subjectId, dimensionId) {
    if (UNASSIGNED_PANEL_STATE.busy) return;
    UNASSIGNED_PANEL_STATE.busy = subjectId;
    try {
        const result = await api.moveSubjectsIntoAxis([subjectId], dimensionId);
        const moved = (result && result.moved) || 0;
        const axisName = (result && result.dimension_name) || 'that axis';
        // `Toast.success(title, message)`, which is what this page uses --
        // there is no `showToast` here. An earlier draft called one, and the
        // ReferenceError fired AFTER the move had already committed and
        // before the reload below, so the subjects moved and the tree never
        // redrew. A write that succeeds and a page that does not update is
        // the worst shape this handler can take, so the reload belongs after
        // nothing that can throw.
        Toast.success(
            'Moved',
            moved === 1
                ? `1 subject moved into ${axisName}.`
                : `${moved} subjects moved into ${axisName}.`);

        // The dimensional cache holds pre-move weights and membership for
        // the axis that just gained a tree. Invalidate BEFORE reloading or
        // the tree draws the state from before the write (CLAUDE.md,
        // "Dimension code path symmetry").
        invalidateDimensionCache(dimensionId);
        invalidateDimensionCache(TreeState.currentDimensionId);
        await loadHierarchy();
    } catch (error) {
        // The domain method returns its refusals as sentences, and the
        // bridge passes them through as `success=false` (#240), so this is
        // the student-readable reason rather than a stack frame.
        Toast.error('Could not move them',
                    error.message || 'Could not move those subjects.');
    } finally {
        UNASSIGNED_PANEL_STATE.busy = null;
    }
}

function setUnassignedPanelExpanded(expanded) {
    const panel = document.getElementById('unassigned-panel');
    const toggle = document.getElementById('unassigned-panel-toggle');
    const body = document.getElementById('unassigned-panel-body');
    if (!panel || !toggle || !body) return;

    panel.classList.toggle('open', expanded);
    toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    // `hidden` as well as the class, for the same reason the Archived panel
    // does it: collapsed must mean out of the accessibility tree.
    body.hidden = !expanded;
}

function toggleUnassignedPanel() {
    const panel = document.getElementById('unassigned-panel');
    if (!panel) return;
    setUnassignedPanelExpanded(!panel.classList.contains('open'));
}

function setArchivedPanelExpanded(expanded) {
    const panel = document.getElementById('archived-panel');
    const toggle = document.getElementById('archived-panel-toggle');
    const body = document.getElementById('archived-panel-body');
    if (!panel || !toggle || !body) return;

    panel.classList.toggle('open', expanded);
    toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    // `hidden` as well as the class: the panel must be out of the a11y tree
    // when collapsed, not merely invisible (#127's lesson, other direction).
    body.hidden = !expanded;
}

function toggleArchivedPanel() {
    const panel = document.getElementById('archived-panel');
    if (!panel) return;
    setArchivedPanelExpanded(!panel.classList.contains('open'));
    // The Restore buttons are on screen only while the panel is open (#682).
    startTreeTour();
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
        
        // Issue #61: accept both documented spellings of the top-level
        // array. api.getImportRootNodes is the single shared reader;
        // importSubjectHierarchy accepts both keys too, so the file is
        // handed to the bridge exactly as it was written.
        const { nodes: rootNodes } = api.getImportRootNodes(data);
        if (!Array.isArray(rootNodes)) {
            throw new Error(
                'Invalid file format: missing "root_nodes" (or "subjects") array'
            );
        }

        // Confirm import.
        //
        // This handler is the fallback: import_export.js overrides
        // `handleImportFile` with the preview-modal version at load
        // time, and that is what the file input reaches. It is still
        // wrong for this one to claim the import only adds — issue #67
        // made import a merge, so a subject this file no longer lists is
        // removed unless entries are tagged to it. If this path is ever
        // the live one again, it must not promise otherwise.
        const count = countNodes(rootNodes);
        if (!confirm(
            `Import ${count} subjects from "${file.name}"?\n\n` +
            `Your hierarchy is merged with this file: subjects it lists are ` +
            `added or updated, and subjects it no longer lists are removed ` +
            `unless your entries are tagged to them.`
        )) {
            return;
        }
        
        // Include dimension_id in import data when in dimension mode
        const importData = { ...data };
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            importData.dimension_id = TreeState.currentDimensionId;
        }

        const result = await api.importSubjectHierarchy(
            TreeState.examContextId, JSON.stringify(importData)
        );

        const counts = (result && result.counts) || {};
        const parts = [];
        if (counts.added) parts.push(`${counts.added} added`);
        if (counts.updated) parts.push(`${counts.updated} updated`);
        if (counts.removed) parts.push(`${counts.removed} removed`);
        if (counts.kept_in_use) parts.push(`${counts.kept_in_use} kept in use`);
        Toast.success(
            'Imported',
            parts.length ? parts.join(', ') : 'No changes — already matches this file'
        );

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
    // Find the match in the RAW name and escape each piece afterwards. Matching
    // in the escaped string let a query land inside an entity -- "p" in
    // "Salt &amp; Pepper" split "&amp;" and the row read "Salt &amp; Pepper"
    // (#548).
    const raw = String(text ?? '');
    if (!query) return WimiEscape.html(raw);
    const idx = raw.toLowerCase().indexOf(String(query).toLowerCase());
    if (idx === -1) return WimiEscape.html(raw);
    const end = idx + String(query).length;
    return `${WimiEscape.html(raw.substring(0, idx))}`
        + `<mark class="tree-search-highlight">${WimiEscape.html(raw.substring(idx, end))}</mark>`
        + `${WimiEscape.html(raw.substring(end))}`;
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
    // #237. `import_export.js` replaces `window.exportHierarchy` with its own
    // enhanced version at load; the whole-exam export has no legacy
    // counterpart, so it is read off `window` at click time rather than
    // captured here, for the same reason.
    const exportAllBtn = document.getElementById('btn-export-whole-exam');
    if (exportAllBtn) {
        exportAllBtn.onclick = () => window.exportWholeExamHierarchy?.();
    }
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
    // Both outcomes arrive in one preview call, so the choice re-renders
    // locally rather than making the user wait mid-decision.
    document.getElementById('delete-promote-children').onchange = renderDeletePreview;
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
    document.getElementById('btn-show-overview').onclick = returnToExamOverview;
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

    // Archived subjects panel (#37). Collapsed by default; the list itself is
    // loaded by `loadHierarchy` so it tracks the exam and dimension on screen.
    const unassignedToggle = document.getElementById('unassigned-panel-toggle');
    if (unassignedToggle) {
        unassignedToggle.addEventListener('click', toggleUnassignedPanel);
    }

    const archivedToggle = document.getElementById('archived-panel-toggle');
    if (archivedToggle) {
        archivedToggle.addEventListener('click', toggleArchivedPanel);
    }
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
    // #tree-container ships `hidden` since #121 (so the first load looks like
    // every later one), and showLoading(true) hides it as well. An error
    // written into a hidden container is an error nobody reads, and the
    // no-exam-id path reaches here before any showLoading(false).
    container.classList.remove('hidden');
    container.innerHTML = `
        <div class="alert alert-error" style="margin: 20px;">
            <strong>Error:</strong> ${WimiEscape.html(message)}
            <br><br>
            <a href="index.html" class="btn btn-secondary">← Back to Exams</a>
        </div>
    `;
    document.getElementById('tree-empty').classList.add('hidden');
    document.getElementById('tree-loading').classList.add('hidden');
}



// =========================================================================
// Expose Global Functions for onclick handlers
// =========================================================================

window.selectNode = selectNode;
window.handleTreeRowKeydown = handleTreeRowKeydown;
window.toggleNode = toggleNode;
window.startInlineEdit = startInlineEdit;
window.addChild = addChild;
window.confirmDeleteNode = confirmDeleteNode;
window.expandAll = expandAll;
window.collapseAll = collapseAll;
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
// Archived panel (#37) -- invoked from an inline onclick in renderArchivedItem.
window.restoreArchivedBatch = restoreArchivedBatch;
window.refreshArchivedPanel = refreshArchivedPanel;
window.toggleArchivedPanel = toggleArchivedPanel;

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
