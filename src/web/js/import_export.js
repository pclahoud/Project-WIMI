/**
 * WIMI Import/Export Module
 * Phase 3 Stage 4 - Enhanced Import/Export Functionality
 * 
 * Features:
 * - Export with metadata and formatting options
 * - Import preview modal with validation
 * - Detailed validation error display
 * - Replace vs Merge import options
 * - Progress indication for large imports
 */

// =========================================================================
// Import/Export State
// =========================================================================

const ImportExportState = {
    pendingImport: null,
    importMode: 'merge', // 'merge' or 'replace'
    validationErrors: [],
    validationWarnings: [],
    isProcessing: false,
    // Issue #67: the backend's plan for this file — what the import will
    // add, update, rename, remove and keep. Fetched when the preview
    // modal opens and produced by the same planner the import itself
    // runs, so the modal cannot promise something the import won't do.
    // `mergePlanToken` guards against a second file being chosen while
    // the first plan is still in flight.
    mergePlan: null,
    mergePlanToken: 0
};

// =========================================================================
// Export Functionality
// =========================================================================

/**
 * Fetch the exam's aliases once, keyed by subject row id.
 *
 * One call for the whole exam rather than one per dimension: a whole-exam
 * export would otherwise repeat it per axis for a map that is already
 * exam-wide.
 */
async function fetchExportAliasMap(examContextId) {
    const aliasMap = new Map();
    try {
        const subjects = await api.getAllSubjectsWithAliasesForExam(examContextId);
        if (subjects) {
            for (const subj of subjects) {
                if (subj.aliases && subj.aliases.length > 0) {
                    aliasMap.set(subj.id, subj.aliases);
                }
            }
        }
    } catch (e) {
        console.warn('Could not fetch aliases for export:', e);
    }
    return aliasMap;
}

/**
 * The stable, portable id of a dimension, or undefined (#237).
 *
 * `exam_dimensions.import_id` (m025), never `exam_dimensions.id`. The row id
 * means something different in every profile, so writing it as an identifier
 * would claim to identify dimensions that were never imported — the #67 rule
 * for subjects, one level up, where getting it wrong costs an entire subject
 * tree rather than one subject.
 *
 * Absent when the dimension has none, exactly as a hand-built subject tree
 * exports id-free. A dimension adopts an id the first time a file supplies
 * one (#66 2.3), and until then there is nothing portable to write.
 */
function portableDimensionId(dimension) {
    return (dimension && dimension.import_id) || undefined;
}

/**
 * Build the file a per-dimension (or no-dimension) export writes. Pure.
 *
 * Separated from the download so the result can be asserted on at all: this
 * whole module had no test covering what it writes, which is how the
 * dimension-level version of #67's "NOT the row id" rule came to be violated
 * (#237).
 *
 * **This form deliberately carries no dimension id.** The import it feeds is
 * *targeted* — the tree view supplies the dimension — so the file does not
 * need to identify one. And it must not: a file declaring a `dimensions` list
 * is authoritative about exam structure (#241), so a one-axis file says "this
 * exam has one dimension" and archives the rest. Measured on a three-axis
 * exam: importing a one-axis file archived the other two axes and their
 * trees. The whole-exam form below is the one that carries ids, because it
 * declares every axis and is therefore a no-op on re-import.
 */
function buildSingleTreeExport(params) {
    const {
        hierarchyData, examContext, examContextId, hierarchyLevels,
        dimension = null, includeMetadata = true, includeWeights = true,
        aliasMap = new Map(),
    } = params;

    const rootNodes = cleanNodesForExport(
        hierarchyData?.root_nodes || [], includeWeights, aliasMap);

    return {
        ...(includeMetadata && {
            _metadata: {
                export_version: '1.2',
                exported_at: new Date().toISOString(),
                exported_from: 'WIMI Desktop',
                exam_name: examContext?.exam_name || 'Unknown',
                exam_id: examContextId,
                total_nodes: countNodesInHierarchy(hierarchyData?.root_nodes || []),
                hierarchy_levels: hierarchyLevels?.map(l => l.level_name) || [],
                // `dimension_name` is a human label and says so. The raw
                // `exam_dimensions.id` that used to sit beside it is gone
                // (#237): nothing read it, and a number that looks like an
                // identifier invites being used as one in the next profile,
                // where it names a different dimension or none.
                ...(dimension && {
                    dimension_name: dimension.name || 'Unknown',
                    ...(portableDimensionId(dimension) && {
                        dimension_import_id: portableDimensionId(dimension),
                    }),
                }),
            },
        }),
        root_nodes: rootNodes,
    };
}

/**
 * Build a whole-exam file: every axis, each with its own tree (#237, #66 2.3).
 *
 * **Every axis, or none.** Omitting one would archive it on re-import, so a
 * whole-exam export is only correct when it is complete — which is also what
 * makes the per-axis `id` safe to write here.
 */
function buildWholeExamExport(params) {
    const {
        axes, examContext, examContextId, hierarchyLevels,
        includeMetadata = true, includeWeights = true, aliasMap = new Map(),
    } = params;

    const dimensions = axes.map(({ dimension, hierarchyData }) => {
        const axis = { name: dimension.name };
        const id = portableDimensionId(dimension);
        if (id) axis.id = id;
        if (dimension.display_order !== undefined && dimension.display_order !== null) {
            axis.display_order = dimension.display_order;
        }
        // Written out even though the importer leaves an omitted flag alone:
        // a whole-exam file is a description of the exam, and a round trip
        // that quietly dropped these would make the file a worse description
        // of the exam than the thing it came from.
        axis.is_required = !!dimension.is_required;
        axis.allow_multiple = !!dimension.allow_multiple;
        if (dimension.description) axis.description = dimension.description;
        axis.root_nodes = cleanNodesForExport(
            hierarchyData?.root_nodes || [], includeWeights, aliasMap);
        return axis;
    });

    const totalNodes = axes.reduce(
        (sum, { hierarchyData }) =>
            sum + countNodesInHierarchy(hierarchyData?.root_nodes || []), 0);

    return {
        ...(includeMetadata && {
            _metadata: {
                export_version: '1.2',
                exported_at: new Date().toISOString(),
                exported_from: 'WIMI Desktop',
                exam_name: examContext?.exam_name || 'Unknown',
                exam_id: examContextId,
                total_nodes: totalNodes,
                dimension_count: dimensions.length,
                hierarchy_levels: hierarchyLevels?.map(l => l.level_name) || [],
            },
        }),
        dimensions,
    };
}

/**
 * Turn a built export object into a download.
 */
function downloadExportFile(data, filename, prettyPrint = true) {
    const jsonString = prettyPrint
        ? JSON.stringify(data, null, 2)
        : JSON.stringify(data);
    const blob = new Blob([jsonString], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function exportFilenameBase(examContext) {
    return (examContext?.exam_name || 'hierarchy')
        .replace(/[^a-z0-9]/gi, '_')
        .toLowerCase();
}

/**
 * Export hierarchy with enhanced options
 * @param {Object} options - Export options
 */
async function exportHierarchyEnhanced(options = {}) {
    const {
        includeMetadata = true,
        prettyPrint = true,
        includeWeights = true
    } = options;
    
    try {
        // Show loading state on export button
        const exportBtn = document.getElementById('btn-export');
        const originalText = exportBtn?.innerHTML;
        if (exportBtn) {
            exportBtn.innerHTML = '<span>⏳</span> Exporting...';
            exportBtn.disabled = true;
        }
        
        // Get hierarchy data - dimension-aware for multi-dimensional exams
        const isDimensionMode = TreeState.usesDimensions && TreeState.currentDimensionId;
        let hierarchyData;
        if (isDimensionMode) {
            hierarchyData = await api.getDimensionHierarchy(TreeState.examContextId, TreeState.currentDimensionId);
        } else {
            hierarchyData = await api.getSubjectHierarchy(TreeState.examContextId);
        }

        const aliasMap = await fetchExportAliasMap(TreeState.examContextId);

        const exportData = buildSingleTreeExport({
            hierarchyData,
            examContext: TreeState.examContext,
            examContextId: TreeState.examContextId,
            hierarchyLevels: TreeState.hierarchyLevels,
            dimension: isDimensionMode ? TreeState.currentDimension : null,
            includeMetadata,
            includeWeights,
            aliasMap,
        });

        // Generate filename - include dimension name for multi-dimensional exams
        const examName = exportFilenameBase(TreeState.examContext);
        // The day the student made the export, not the UTC one (#286). This
        // site is cosmetic on its own -- but a file saved at 21:00 and named
        // with tomorrow is the sort of inconsistency somebody later "fixes"
        // in the wrong direction, so it moves with the other four.
        const date = LocalDate.today();
        let filename;
        if (isDimensionMode) {
            const dimName = (TreeState.currentDimension?.name || 'dimension')
                .replace(/[^a-z0-9]/gi, '_')
                .toLowerCase();
            filename = `${examName}_${dimName}_subjects_${date}.json`;
        } else {
            filename = `${examName}_subjects_${date}.json`;
        }

        downloadExportFile(exportData, filename, prettyPrint);

        Toast.success('Exported', `Downloaded ${filename}`);
        
    } catch (error) {
        console.error('Export error:', error);
        Toast.error('Export Failed', error.message);
    } finally {
        // Restore button
        const exportBtn = document.getElementById('btn-export');
        if (exportBtn) {
            exportBtn.innerHTML = '<span>📤</span> Export';
            exportBtn.disabled = false;
        }
    }
}

/**
 * Export every dimension of the exam as one whole-exam file (#237, #66).
 *
 * A separate action from `exportHierarchyEnhanced` rather than a mode of it.
 * The two produce files that mean different things — one is a tree to merge
 * into the dimension you are looking at, the other is a description of the
 * whole exam that will create, rename and archive dimensions — and silently
 * changing what the existing button writes would be the more surprising of
 * the two options.
 */
async function exportWholeExamHierarchy(options = {}) {
    const {
        includeMetadata = true,
        prettyPrint = true,
        includeWeights = true
    } = options;

    const exportBtn = document.getElementById('btn-export-whole-exam');
    try {
        if (exportBtn) {
            exportBtn.innerHTML = '<span>⏳</span> Exporting...';
            exportBtn.disabled = true;
        }

        const dimensions = await api.getDimensions(TreeState.examContextId);
        if (!dimensions || dimensions.length === 0) {
            Toast.error('Nothing to export',
                'This exam has no dimensions. Use Export for its subject tree.');
            return;
        }

        const aliasMap = await fetchExportAliasMap(TreeState.examContextId);

        // Sequential on purpose: the bridge is a single channel and the
        // trees can be large, so firing every dimension at once buys nothing
        // and makes a failure harder to attribute.
        const axes = [];
        for (const dimension of dimensions) {
            axes.push({
                dimension,
                hierarchyData: await api.getDimensionHierarchy(
                    TreeState.examContextId, dimension.id),
            });
        }

        const exportData = buildWholeExamExport({
            axes,
            examContext: TreeState.examContext,
            examContextId: TreeState.examContextId,
            hierarchyLevels: TreeState.hierarchyLevels,
            includeMetadata,
            includeWeights,
            aliasMap,
        });

        const date = LocalDate.today();  // #286, as above
        const filename =
            `${exportFilenameBase(TreeState.examContext)}_whole_exam_${date}.json`;

        downloadExportFile(exportData, filename, prettyPrint);

        Toast.success('Exported',
            `Downloaded ${filename} (${axes.length} dimensions)`);

    } catch (error) {
        console.error('Whole-exam export error:', error);
        Toast.error('Export Failed', error.message);
    } finally {
        if (exportBtn) {
            exportBtn.innerHTML = '<span>\u{1F4E6}</span> Export all';
            exportBtn.disabled = false;
        }
    }
}

/**
 * Clean nodes for export (remove internal properties)
 * @param {Array} nodes - Nodes to clean
 * @param {boolean} includeWeights - Whether to include weight fields
 * @param {Map} aliasMap - Map of node ID to alias objects
 * @returns {Array} Cleaned nodes
 */
function cleanNodesForExport(nodes, includeWeights = true, aliasMap = new Map()) {
    return nodes.map(node => {
        const cleanNode = {
            name: node.name,
            level_type: node.level_type
        };

        // Issue #67: the file's stable id, when this subject has one.
        // NOT `node.id` — that is the database row id, which means
        // nothing in another profile and would claim to identify
        // subjects that were never imported. Only an id the file gave
        // us goes back out, so a round trip keeps renames matchable and
        // an export of a hand-built tree stays id-free.
        if (node.import_id) {
            cleanNode.id = node.import_id;
        }

        if (includeWeights) {
            const low = node.exam_weight_low ?? node.weight ?? 0;
            const high = node.exam_weight_high ?? low;
            if (high !== low) {
                cleanNode.weight = { low, high };
            } else {
                cleanNode.weight = low;
            }
        }

        if (node.sort_order !== undefined) {
            cleanNode.sort_order = node.sort_order;
        }

        // Include aliases if present
        const nodeAliases = aliasMap.get(node.id);
        if (nodeAliases && nodeAliases.length > 0) {
            cleanNode.aliases = nodeAliases.map(a => {
                const alias = { name: a.alias_name, type: a.alias_type };
                if (a.is_primary) alias.is_primary = true;
                if (a.notes) alias.notes = a.notes;
                return alias;
            });
        }

        if (node.children && node.children.length > 0) {
            cleanNode.children = cleanNodesForExport(node.children, includeWeights, aliasMap);
        }

        return cleanNode;
    });
}

/**
 * Count total nodes in hierarchy
 * @param {Array} nodes - Root nodes
 * @returns {number} Total count
 */
function countNodesInHierarchy(nodes) {
    return nodes.reduce((sum, node) => {
        return sum + 1 + (node.children ? countNodesInHierarchy(node.children) : 0);
    }, 0);
}

// =========================================================================
// Import Functionality
// =========================================================================

/**
 * Trigger file picker for import
 */
function triggerImportEnhanced() {
    const fileInput = document.getElementById('import-file');
    if (fileInput) {
        fileInput.click();
    }
}

/**
 * Handle file selection for import
 * @param {Event} event - File input change event
 */
async function handleImportFileEnhanced(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    try {
        // Read and parse file
        const text = await file.text();
        let data;
        
        try {
            data = JSON.parse(text);
        } catch (parseError) {
            Toast.error('Invalid JSON', 'The file does not contain valid JSON');
            event.target.value = '';
            return;
        }
        
        // Validate structure
        const validation = validateImportData(data);
        ImportExportState.validationErrors = validation.errors;
        ImportExportState.validationWarnings = validation.warnings;
        
        if (validation.errors.length > 0 && !validation.hasValidNodes) {
            // Show error modal
            showImportErrorModal(validation);
            event.target.value = '';
            return;
        }
        
        // Store pending import data. `rootNodes` is kept alongside the
        // untouched file so the preview and the count don't have to
        // guess which key it used (issue #61).
        //
        // A whole-exam file (#241) has no top-level `root_nodes`, so reading
        // one would put **0 subjects to import** on the modal for a file
        // carrying three trees — the same "reads like success" failure #240
        // fixed at the bridge. The count is therefore pooled over the axes.
        // Drawing those trees is a separate matter: `renderImportPreviewTree`
        // recurses on depth alone and `countNodesInHierarchy` walks every
        // subtree again per internal node, so it does not scale to several
        // trees as written (#212). Wave 4 owns the rendering; this only makes
        // sure the number is not a lie in the meantime.
        const rootNodes = validation.isWholeExam
            ? (data.dimensions || []).flatMap(
                  axis => (axis && api.getImportRootNodes(axis).nodes) || [])
            : (api.getImportRootNodes(data).nodes || []);
        ImportExportState.pendingImport = {
            filename: file.name,
            data: data,
            rootNodes: rootNodes,
            nodeCount: countNodesInHierarchy(rootNodes),
            isWholeExam: validation.isWholeExam,
            axisCount: validation.isWholeExam ? (data.dimensions || []).length : 0,
            metadata: data._metadata || null
        };
        
        // Show preview modal
        showImportPreviewModal();
        
    } catch (error) {
        console.error('Import error:', error);
        Toast.error('Import Failed', error.message);
    }
    
    // Reset file input
    event.target.value = '';
}

/**
 * Validate import data structure
 * @param {Object} data - Parsed JSON data
 * @returns {Object} Validation result with errors and warnings
 */
function validateImportData(data) {
    const errors = [];
    const warnings = [];
    let validNodeCount = 0;
    
    // Issue #61: root_nodes (what export writes) and subjects (what the
    // import spec documents) are both accepted. api.getImportRootNodes
    // is the single shared reader — the tree editor's own handler uses
    // it too, and importSubjectHierarchy accepts either key, so nothing
    // here rewrites the caller's file.
    // A whole-exam file (#66 Wave 3, #241) carries a top-level `dimensions`
    // list, each entry an axis with its own tree, and `root_nodes` is not
    // read. Each axis is validated as a tree in its own right, so every
    // per-node and per-weight check below applies unchanged — and, as in the
    // planner, the trees never see each other.
    //
    // Keyed on the list type rather than the key's presence: `dimensions: 3`
    // is a malformed file, not a whole-exam file, and belongs to the ordinary
    // path so the ordinary messages describe it.
    const isWholeExam = !!data && Array.isArray(data.dimensions);

    // `trees` is what the rest of this function walks: one entry for an
    // ordinary file, one per axis for a whole-exam file. Collapsing the two
    // shapes here rather than branching per check is what keeps the axes from
    // acquiring their own, weaker validation.
    const trees = [];

    if (isWholeExam) {
        data.dimensions.forEach((axis, i) => {
            const label = (axis && typeof axis.name === 'string' && axis.name.trim())
                ? axis.name.trim()
                : `#${i + 1}`;
            if (!axis || typeof axis !== 'object' || Array.isArray(axis)) {
                errors.push({
                    type: 'structure',
                    message: `Dimension ${i + 1} is not an object`,
                    path: `dimensions[${i}]`,
                    severity: 'error'
                });
                return;
            }
            if (!axis.name || typeof axis.name !== 'string' || !axis.name.trim()) {
                errors.push({
                    type: 'field',
                    message: `Dimension ${i + 1} has no "name"`,
                    path: `dimensions[${i}]`,
                    severity: 'error'
                });
                return;
            }
            const { nodes, key } = api.getImportRootNodes(axis);
            if (key === null) {
                // A misspelled `root_nodes` inside an axis. A warning, not an
                // error: an axis listing no subjects removes nothing, exactly
                // as an empty file removes nothing, and refusing the whole
                // blueprint over one typo costs the student every other axis.
                warnings.push({
                    type: 'empty',
                    message: `Dimension "${label}" lists no subjects, so nothing `
                           + `in it will be added, changed or removed`,
                    path: `dimensions[${i}]`,
                    severity: 'warning'
                });
                return;
            }
            trees.push({ nodes, key: `dimensions[${i}].${key}`, spelling: key });
        });

        if (data.dimensions.length === 0) {
            warnings.push({
                type: 'empty',
                message: 'The file lists no dimensions, so importing it will '
                       + 'change nothing',
                path: 'dimensions',
                severity: 'warning'
            });
        }
    } else {
        // Issue #61: root_nodes (what export writes) and subjects (what the
        // import spec documents) are both accepted. api.getImportRootNodes
        // is the single shared reader — the tree editor's own handler uses
        // it too, and importSubjectHierarchy accepts either key, so nothing
        // here rewrites the caller's file.
        const { nodes: rootNodes, key: usedKey } = api.getImportRootNodes(data);

        if (usedKey === null) {
            errors.push({
                type: 'structure',
                message: 'Missing "root_nodes" or "subjects" array',
                path: 'root',
                severity: 'error'
            });
            return { errors, warnings, hasValidNodes: false };
        }

        if (!Array.isArray(rootNodes)) {
            errors.push({
                type: 'structure',
                message: '"root_nodes" (or "subjects") must be an array',
                path: usedKey,
                severity: 'error'
            });
            return { errors, warnings, hasValidNodes: false };
        }

        if (usedKey === 'subjects') {
            warnings.push({
                type: 'format',
                message: 'File uses the "subjects" key; "root_nodes" is what export writes',
                path: 'root',
                severity: 'info'
            });
        }

        if (rootNodes.length === 0) {
            warnings.push({
                type: 'empty',
                message: 'The file contains no subjects to import',
                path: 'root_nodes',
                severity: 'warning'
            });
        }

        trees.push({ nodes: rootNodes, key: usedKey, spelling: usedKey });
    }

    // Validate each node recursively
    function validateNode(node, path, depth = 1) {
        // Check name
        if (!node.name || typeof node.name !== 'string') {
            errors.push({
                type: 'field',
                message: `Missing or invalid "name" field`,
                path: path,
                severity: 'error'
            });
        } else if (node.name.trim().length === 0) {
            errors.push({
                type: 'field',
                message: `Empty name`,
                path: path,
                severity: 'error'
            });
        } else {
            validNodeCount++;
        }
        
        // Check weight (optional but validate if present).
        //
        // Issue #69: this used to read `low` and `high` directly, so the
        // two single-value forms the guide documents — `{value: 50}` and
        // `{low: 50}` with `high` defaulting to it — both warned "weight
        // range has non-numeric values, will default to 0" about a file
        // that was written exactly as recommended, and then imported
        // perfectly. Resolve the object the way `_import_weight_bounds`
        // does in subject_import.py so the warning and the import agree.
        if (node.weight !== undefined) {
            if (typeof node.weight === 'object' && node.weight !== null) {
                let low;
                let high;
                if ('value' in node.weight) {
                    low = node.weight.value;
                    high = node.weight.value;
                } else {
                    low = node.weight.low !== undefined ? node.weight.low : 0;
                    high = node.weight.high !== undefined ? node.weight.high : low;
                }
                if (typeof low !== 'number' || typeof high !== 'number') {
                    warnings.push({
                        type: 'field',
                        message: `Weight has non-numeric values, will default to 0`,
                        path: path,
                        severity: 'warning'
                    });
                } else if (low > high) {
                    // A warning, never a rejection (issue #64): a real
                    // blueprint transcribed by hand can transpose a pair,
                    // and losing the other 2,210 subjects over it helps
                    // nobody. The importer says the same thing.
                    warnings.push({
                        type: 'range',
                        message: `Weight low ${low}% is above high ${high}%; imported as written`,
                        path: path,
                        severity: 'warning'
                    });
                } else if (low < 0 || low > 100 || high < 0 || high > 100) {
                    warnings.push({
                        type: 'range',
                        message: `Weight range ${low}%-${high}% is outside valid range (0-100)`,
                        path: path,
                        severity: 'warning'
                    });
                }
            } else if (typeof node.weight !== 'number') {
                warnings.push({
                    type: 'field',
                    message: `Weight is not a number, will default to 0`,
                    path: path,
                    severity: 'warning'
                });
            } else if (node.weight < 0 || node.weight > 100) {
                warnings.push({
                    type: 'range',
                    message: `Weight ${node.weight}% is outside valid range (0-100)`,
                    path: path,
                    severity: 'warning'
                });
            }
        }
        
        // Check level_type (optional)
        if (node.level_type !== undefined && typeof node.level_type !== 'string') {
            warnings.push({
                type: 'field',
                message: `Invalid level_type, will use default`,
                path: path,
                severity: 'warning'
            });
        }
        
        // Warn about deep nesting
        if (depth > 10) {
            warnings.push({
                type: 'depth',
                message: `Node at depth ${depth} - deep nesting may affect performance`,
                path: path,
                severity: 'warning'
            });
        }
        
        // Validate aliases (optional)
        if (node.aliases) {
            if (!Array.isArray(node.aliases)) {
                warnings.push({
                    type: 'field',
                    message: `"aliases" must be an array, will be skipped`,
                    path: path + '.aliases',
                    severity: 'warning'
                });
            } else {
                node.aliases.forEach((alias, j) => {
                    if (!alias.name || typeof alias.name !== 'string') {
                        warnings.push({
                            type: 'field',
                            message: `Alias missing "name", will be skipped`,
                            path: `${path}.aliases[${j}]`,
                            severity: 'warning'
                        });
                    }
                });
            }
        }

        // Validate children
        if (node.children) {
            if (!Array.isArray(node.children)) {
                errors.push({
                    type: 'structure',
                    message: `"children" must be an array`,
                    path: path + '.children',
                    severity: 'error'
                });
            } else {
                node.children.forEach((child, i) => {
                    validateNode(child, `${path}.children[${i}]`, depth + 1);
                });
            }
        }
    }
    
    trees.forEach((tree) => {
        tree.nodes.forEach((node, i) => {
            validateNode(node, `${tree.key}[${i}]`);
        });
    });

    // Check sibling weight totals
    function checkWeightTotals(nodes, path) {
        if (!nodes || nodes.length === 0) return;

        const total = nodes.reduce((sum, n) => {
            const w = n.weight;
            if (typeof w === 'object' && w !== null) return sum + ((w.low || 0) + (w.high || 0)) / 2;
            return sum + (w || 0);
        }, 0);
        if (total > 0 && Math.abs(total - 100) > 0.5) {
            warnings.push({
                type: 'weight',
                message: `Sibling weights sum to ${total.toFixed(1)}% (expected 100%)`,
                path: path,
                severity: 'warning'
            });
        }
        
        nodes.forEach((node, i) => {
            if (node.children && node.children.length > 0) {
                checkWeightTotals(node.children, `${path}[${i}].children`);
            }
        });
    }
    
    // Per tree, never pooled. Sibling totals are a statement about one set of
    // siblings, and the roots of two different axes are not siblings — each
    // axis's roots describe 100% of the exam on their own, so pooling them
    // would report every whole-exam file as wildly over 100%.
    trees.forEach((tree) => {
        checkWeightTotals(tree.nodes, tree.key);
    });

    return {
        errors,
        warnings,
        hasValidNodes: validNodeCount > 0,
        validNodeCount,
        isWholeExam
    };
}

/**
 * Show import preview modal
 */
function showImportPreviewModal() {
    const modal = document.getElementById('import-preview-modal');
    if (!modal) {
        createImportPreviewModal();
    }
    
    const pending = ImportExportState.pendingImport;
    if (!pending) return;
    
    // Update modal content
    document.getElementById('import-filename').textContent = pending.filename;
    document.getElementById('import-node-count').textContent = pending.nodeCount;
    
    // What this file's scope actually is (#66 Wave 4).
    //
    // This notice keyed on `TreeState.currentDimension` and never on the file,
    // so a whole-exam file -- one that creates, renames and archives
    // dimensions across the exam -- was announced as "Importing into
    // dimension: System". False in the most expensive direction: the student
    // would believe the blast radius is one axis when it is all of them.
    //
    // The whole-exam branch is first and does NOT depend on a current
    // dimension, because such a file is equally valid on an exam that has none
    // yet -- that is how a student sets one up from a document.
    const dimensionNoticeEl = document.getElementById('import-dimension-notice');
    if (dimensionNoticeEl) {
        if (pending.isWholeExam) {
            const notOnlyCurrent = TreeState.currentDimension
                ? ` It does not import only into
                   <strong>${escapeHtml(TreeState.currentDimension.name)}</strong>.`
                : '';
            const howMany = pending.axisCount
                ? ` (${pending.axisCount} in the file)`
                : '';
            dimensionNoticeEl.innerHTML = `
                <span class="info-icon">📦</span>
                <span>This file describes <strong>every dimension</strong> of
                this exam${howMany}, and can create, rename and archive
                them.${notOnlyCurrent} Read the summary below before
                confirming.</span>
            `;
            dimensionNoticeEl.classList.remove('hidden');
        } else if (TreeState.usesDimensions && TreeState.currentDimensionId
                   && TreeState.currentDimension) {
            dimensionNoticeEl.innerHTML = `
                <span class="info-icon">📂</span>
                <span>Importing into dimension: <strong>${escapeHtml(TreeState.currentDimension.name)}</strong></span>
            `;
            dimensionNoticeEl.classList.remove('hidden');
        } else {
            dimensionNoticeEl.classList.add('hidden');
        }
    }

    // Show metadata if available
    const metadataEl = document.getElementById('import-metadata');
    if (pending.metadata) {
        metadataEl.innerHTML = `
            <div class="import-metadata-item">
                <span class="label">Source:</span>
                <span class="value">${escapeHtml(pending.metadata.exported_from || 'Unknown')}</span>
            </div>
            <div class="import-metadata-item">
                <span class="label">Exported:</span>
                <span class="value">${formatDate(pending.metadata.exported_at)}</span>
            </div>
            ${pending.metadata.exam_name ? `
                <div class="import-metadata-item">
                    <span class="label">Original Exam:</span>
                    <span class="value">${escapeHtml(pending.metadata.exam_name)}</span>
                </div>
            ` : ''}
        `;
        metadataEl.classList.remove('hidden');
    } else {
        metadataEl.classList.add('hidden');
    }
    
    // Show preview tree
    const previewContainer = document.getElementById('import-preview-tree');
    previewContainer.innerHTML = renderImportPreviewTree(pending.rootNodes || [], 0, 3);
    
    // Show warnings if any
    const warningsEl = document.getElementById('import-warnings');
    if (ImportExportState.validationWarnings.length > 0) {
        warningsEl.innerHTML = `
            <div class="import-warning-header">
                <span class="warning-icon">⚠️</span>
                <span>${ImportExportState.validationWarnings.length} warning${ImportExportState.validationWarnings.length > 1 ? 's' : ''}</span>
                <button class="toggle-details" onclick="toggleImportWarnings()">Show Details</button>
            </div>
            <div class="import-warning-list hidden" id="import-warning-list">
                ${ImportExportState.validationWarnings.map(w => `
                    <div class="import-warning-item">
                        <span class="warning-path">${escapeHtml(w.path)}</span>
                        <span class="warning-message">${escapeHtml(w.message)}</span>
                    </div>
                `).join('')}
            </div>
        `;
        warningsEl.classList.remove('hidden');
    } else {
        warningsEl.classList.add('hidden');
    }
    
    // Set import mode
    const modeRadios = document.querySelectorAll('input[name="import-mode"]');
    modeRadios.forEach(radio => {
        radio.checked = radio.value === ImportExportState.importMode;
    });
    
    // Update existing count for merge info
    const existingCount = TreeState.flatNodes.size;
    document.getElementById('import-existing-count').textContent = existingCount;
    
    // Show/hide merge warning based on mode and existing nodes
    updateImportModeInfo();

    // Show modal
    document.getElementById('import-preview-modal').classList.add('active');

    // Issue #67: ask the backend what this file would actually do. Fired
    // after the modal is up so the file preview is never held hostage to
    // a round trip over a 2,000-subject outline; the section renders a
    // "working it out" line until the plan lands.
    loadImportMergePlan();
}

/**
 * Build the JSON the import slots will be given.
 *
 * The preview and the import must be handed the *same* bytes or the plan
 * shown is not the plan that runs — so both go through here rather than
 * each assembling their own payload.
 *
 * @returns {string|null} JSON string, or null with no pending import.
 */
function buildImportPayload() {
    const pending = ImportExportState.pendingImport;
    if (!pending) return null;
    const importData = { ...pending.data };
    if (TreeState.usesDimensions && TreeState.currentDimensionId) {
        importData.dimension_id = TreeState.currentDimensionId;
    }
    return JSON.stringify(importData);
}

/**
 * Fetch and render the merge plan for the pending import (issue #67).
 */
async function loadImportMergePlan() {
    const container = document.getElementById('import-merge-plan');
    if (!container) return;

    const payload = buildImportPayload();
    if (payload === null) return;

    const token = ++ImportExportState.mergePlanToken;
    ImportExportState.mergePlan = null;
    container.innerHTML =
        '<div class="import-plan-pending">Working out what this file changes…</div>';

    try {
        const plan = await api.previewSubjectHierarchyImport(
            TreeState.examContextId, payload
        );
        if (token !== ImportExportState.mergePlanToken) return;
        ImportExportState.mergePlan = plan;
        container.innerHTML = renderImportMergePlan(plan);
    } catch (error) {
        if (token !== ImportExportState.mergePlanToken) return;
        console.error('Import preview failed:', error);
        // A plan that could not be computed must not read as "nothing
        // will change" — the student is about to approve a destructive
        // operation on the strength of this box.
        container.innerHTML = `
            <div class="import-plan-error">
                <span class="info-icon">⚠️</span>
                <span>Could not work out what this import will change
                (${escapeHtml(error.message || String(error))}).
                Importing anyway is not recommended.</span>
            </div>
        `;
    }
}

/**
 * Render the merge plan (issue #67).
 *
 * Four numbers and the two things that need sentences: subjects kept
 * because entries point at them, and the warning that a file with no ids
 * cannot express a rename.
 *
 * @param {Object} plan Payload from `previewSubjectHierarchyImport`.
 * @returns {string} HTML string.
 */
/**
 * The axis-level half of the import plan (#252, #66 Wave 4).
 *
 * The planner already decided all of this; before this existed the modal
 * displayed only the subject-level counts, so a file that archived two
 * dimensions and every subject tree inside them reported **"0 removed"** --
 * `counts.removed` is the subject figure for the axes the file *declares*, and
 * subjects removed by a dimension archive go through `archive_dimension`'s
 * cascade instead. The one number a student reads to answer "will this delete
 * anything" said zero when the answer was "two whole axes".
 *
 * So an archived axis is the loudest thing in this panel. Under #210 the
 * cascade takes the whole tree.
 *
 * It **is** undoable since #37 landed: the tree editor's "Archived subjects"
 * panel restores the whole archive as one event, dimension and trees
 * together. This text said "cannot be undone yet" until then, and saying so
 * after the fact would be worse than the original omission -- it would talk a
 * student out of an import that is in fact reversible.
 */
function renderWholeExamPlanNotes(plan) {
    const c = plan.counts || {};
    let notes = '';

    // Loudest first: what is about to be archived.
    if ((plan.dimensions_removed || []).length) {
        const rows = plan.dimensions_removed.map(d => `
            <li>
                <strong>${escapeHtml(d.name)}</strong>
                <span class="import-plan-count">${d.subject_count}
                    ${d.subject_count === 1 ? 'subject' : 'subjects'}</span>
            </li>
        `).join('');
        const n = plan.dimensions_removed.length;
        const subjects = plan.dimensions_removed.reduce(
            (sum, d) => sum + (d.subject_count || 0), 0);
        notes += `
            <div class="import-plan-note warning">
                <span class="info-icon">\u26A0\uFE0F</span>
                <div>
                    <p><strong>${n} ${n === 1 ? 'dimension' : 'dimensions'} and
                    ${subjects === 1 ? 'its' : 'their'} ${subjects}
                    ${subjects === 1 ? 'subject' : 'subjects'} will be
                    archived</strong>, because this file does not list
                    ${n === 1 ? 'it' : 'them'} and nothing is tagged inside
                    ${n === 1 ? 'it' : 'them'}. You can undo this afterwards
                    from <strong>Archived subjects</strong> at the foot of the
                    tree editor.</p>
                    <ul class="import-plan-kept-list">${rows}</ul>
                    <p>To keep ${n === 1 ? 'it' : 'them'}, add
                    ${n === 1 ? 'it' : 'them'} to the file's
                    <code>dimensions</code> list and import again.</p>
                </div>
            </div>
        `;
    }

    if ((plan.dimensions_kept_in_use || []).length) {
        const rows = plan.dimensions_kept_in_use.map(d => `
            <li>
                <strong>${escapeHtml(d.name)}</strong>
                <span class="import-plan-count">${d.entry_count}
                    ${d.entry_count === 1 ? 'entry' : 'entries'}</span>
            </li>
        `).join('');
        const n = plan.dimensions_kept_in_use.length;
        notes += `
            <div class="import-plan-note kept">
                <span class="info-icon">\u{1F4CC}</span>
                <div>
                    <p><strong>${n} ${n === 1 ? 'dimension is' : 'dimensions are'}
                    kept because your entries are tagged inside
                    ${n === 1 ? 'it' : 'them'}</strong>, even though this file
                    does not list ${n === 1 ? 'it' : 'them'}. Your history
                    wins.</p>
                    <ul class="import-plan-kept-list">${rows}</ul>
                </div>
            </div>
        `;
    }

    if ((plan.dimensions_added || []).length) {
        const names = plan.dimensions_added
            .map(d => escapeHtml(d.name)).join(', ');
        const n = plan.dimensions_added.length;
        notes += `
            <div class="import-plan-note">
                <span class="info-icon">\u2795</span>
                <span>${n} new ${n === 1 ? 'dimension' : 'dimensions'} will be
                created: <strong>${names}</strong>.</span>
            </div>
        `;
    }

    // A renamed axis is worth saying out loud: without a stable `id` in the
    // file it would have been an archive plus a create, taking the tree with
    // it, so seeing "renamed" is the student's evidence that the ids worked.
    const renamed = (plan.dimensions_updated || [])
        .filter(d => d.changes && d.changes.name);
    if (renamed.length) {
        const rows = renamed.map(d => `
            <li><strong>${escapeHtml(String(d.changes.name[0]))}</strong>
                \u2192 <strong>${escapeHtml(String(d.changes.name[1]))}</strong></li>
        `).join('');
        notes += `
            <div class="import-plan-note">
                <span class="info-icon">\u{1F4DD}</span>
                <div>
                    <p><strong>${renamed.length}
                    ${renamed.length === 1 ? 'dimension is' : 'dimensions are'}
                    renamed</strong>, and ${renamed.length === 1 ? 'its' : 'their'}
                    subjects stay where they are.</p>
                    <ul class="import-plan-kept-list">${rows}</ul>
                </div>
            </div>
        `;
    }

    if (plan.declares_no_dimensions) {
        notes += `
            <div class="import-plan-note warning">
                <span class="info-icon">\u26A0\uFE0F</span>
                <span>This file lists no dimensions, so importing it does
                nothing. It is <strong>not</strong> read as "remove every
                dimension" &mdash; a file that lost its
                <code>dimensions</code> key, or downloaded half-way, looks
                exactly like this.</span>
            </div>
        `;
    }

    const quiet = (plan.axes || []).filter(a => a.declares_no_subjects);
    if (quiet.length) {
        const names = quiet.map(a => escapeHtml(a.name)).join(', ');
        notes += `
            <div class="import-plan-note warning">
                <span class="info-icon">\u26A0\uFE0F</span>
                <span>${quiet.length === 1 ? 'Dimension' : 'Dimensions'}
                <strong>${names}</strong>
                ${quiet.length === 1 ? 'lists' : 'list'} no subjects, so nothing
                in ${quiet.length === 1 ? 'it' : 'them'} is added, changed or
                removed. A misspelled <code>root_nodes</code> key looks exactly
                like this.</span>
            </div>
        `;
    }

    if (plan.dimensionless_subject_count) {
        const n = plan.dimensionless_subject_count;
        notes += `
            <div class="import-plan-note">
                <span class="info-icon">\u2139\uFE0F</span>
                <span>${n} ${n === 1 ? 'subject is' : 'subjects are'} not in any
                dimension. A whole-exam file describes the dimensions, so
                ${n === 1 ? 'it is' : 'they are'} left exactly as
                ${n === 1 ? 'it is' : 'they are'} &mdash; neither updated nor
                removed.</span>
            </div>
        `;
    }

    return notes;
}

/**
 * One row per axis: what happens to it, and its own coverage band.
 *
 * **Coverage is per axis and never summed** (#64, and #241). The axes are
 * overlapping partitions of one item pool -- the three real Step 2 CK tables
 * total 84-153%, 78-113% and 97-142% -- so one combined figure would describe
 * nothing. That is why this is a table of bands and not a total.
 */
function renderWholeExamAxisTable(plan) {
    const axes = plan.axes || [];
    if (!axes.length) return '';

    const ACTION = {add: 'new', update: 'updated', unchanged: 'unchanged'};
    const rows = axes.map(axis => {
        const ac = axis.counts || {};
        const cov = axis.coverage || {};
        const band = cov.weighted_roots
            ? `${(cov.low || 0)}\u2013${(cov.high || 0)}%`
            : '\u2014';
        const spans100 = cov.weighted_roots && !cov.spans_100;
        return `
            <tr>
                <td class="import-axis-name">${escapeHtml(axis.name)}</td>
                <td>${ACTION[axis.action] || escapeHtml(String(axis.action))}</td>
                <td>${ac.added || 0}</td>
                <td>${ac.updated || 0}</td>
                <td>${ac.removed || 0}</td>
                <td class="${spans100 ? 'import-axis-coverage-warn' : ''}"
                    title="${spans100
                        ? 'This axis\u2019s weights do not span 100%. WIMI imports them as written and never rescales.'
                        : ''}">${band}</td>
            </tr>
        `;
    }).join('');

    return `
        <table class="import-axis-table">
            <thead>
                <tr>
                    <th>Dimension</th><th></th>
                    <th>added</th><th>updated</th><th>removed</th>
                    <th title="The summed low\u2013high of this dimension\u2019s top-level weights. Never added across dimensions: they describe the same questions.">coverage</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

function renderImportMergePlan(plan) {
    const c = plan.counts || {};
    // `label` may be a plain string, or `[singular, plural]` where the count
    // makes "1 dimensions added" read badly.
    const stat = (n, label, cls) => {
        const count = n || 0;
        const text = Array.isArray(label)
            ? (count === 1 ? label[0] : label[1])
            : label;
        return `
        <div class="import-plan-stat ${n ? cls : 'is-zero'}">
            <span class="import-plan-number">${count}</span>
            <span class="import-plan-label">${text}</span>
        </div>
    `;
    };

    const detail = [];
    if (c.renamed) detail.push(`${c.renamed} renamed`);
    if (c.moved) detail.push(`${c.moved} moved`);

    let notes = '';

    if (plan.whole_exam) {
        notes += renderWholeExamPlanNotes(plan);
    }

    if (plan.empty_file) {
        notes += `
            <div class="import-plan-note warning">
                <span class="info-icon">⚠️</span>
                <span>This file lists no subjects, so importing it does
                nothing. It is <strong>not</strong> read as "remove every
                subject" — a file that lost its <code>root_nodes</code> key,
                or downloaded half-way, looks exactly like this.</span>
            </div>
        `;
    }

    if (plan.file_exam_matches === false && plan.file_exam_name) {
        notes += `
            <div class="import-plan-note">
                <span class="info-icon">ℹ️</span>
                <span>This file was written for
                <strong>${escapeHtml(String(plan.file_exam_name))}</strong>;
                you are importing it into
                <strong>${escapeHtml(String(plan.exam_name))}</strong>.</span>
            </div>
        `;
    }

    if (plan.rename_blind) {
        notes += `
            <div class="import-plan-note warning">
                <span class="info-icon">⚠️</span>
                <span>This file gives no <code>id</code> for its subjects, so a
                subject you renamed in the file cannot be recognised as the same
                subject: it will be <strong>removed and added back</strong>,
                and anything attached to the old one stays with the old one.
                Add an <code>id</code> to each subject to keep renames
                connected.</span>
            </div>
        `;
    }

    if (c.kept_in_use) {
        // On a whole-exam plan the kept subjects live per axis, so reading
        // `plan.kept_in_use` rendered the explanation with an EMPTY list --
        // the student was told subjects were kept and shown none of them
        // (#252). Pooled here rather than at the payload, because the
        // single-tree shape is the one every other caller expects.
        const keptItems = plan.whole_exam
            ? (plan.axes || []).flatMap(a => a.kept_in_use || [])
            : (plan.kept_in_use || []);
        const keptTotal = plan.whole_exam
            ? (plan.axes || []).reduce(
                (sum, a) => sum + (a.kept_in_use_total || 0), 0)
            : plan.kept_in_use_total;
        const links = keptItems.map(item => `
            <li>
                <a class="import-plan-link"
                   href="entry_browser.html?exam=${encodeURIComponent(plan.exam_context_id)}&subject=${encodeURIComponent(item.id)}">
                    ${escapeHtml(item.name)}</a>
                <span class="import-plan-count">${item.entry_count}
                    ${item.entry_count === 1 ? 'entry' : 'entries'}</span>
            </li>
        `).join('');
        const more = keptTotal > keptItems.length
            ? `<li class="import-plan-more">and ${
                keptTotal - keptItems.length} more</li>`
            : '';
        notes += `
            <div class="import-plan-note kept">
                <span class="info-icon">📌</span>
                <div>
                    <p><strong>${c.kept_in_use}
                    ${c.kept_in_use === 1 ? 'subject is' : 'subjects are'} kept
                    because your entries are tagged to
                    ${c.kept_in_use === 1 ? 'it' : 'them'}</strong>, even though
                    this file no longer lists
                    ${c.kept_in_use === 1 ? 'it' : 'them'}. Your history wins.
                    ${plan.entries_affected}
                    ${plan.entries_affected === 1 ? 'entry' : 'entries'}
                    ${plan.entries_affected === 1 ? 'is' : 'are'} affected — open
                    ${c.kept_in_use === 1 ? 'it' : 'them'} to re-tag, then the
                    subject can be deleted normally.</p>
                    <ul class="import-plan-kept-list">${links}${more}</ul>
                </div>
            </div>
        `;
    }

    if (c.kept_as_ancestor) {
        notes += `
            <div class="import-plan-note">
                <span class="info-icon">📌</span>
                <span>${c.kept_as_ancestor} parent
                ${c.kept_as_ancestor === 1 ? 'subject is' : 'subjects are'} also
                kept, because a subject in use sits beneath
                ${c.kept_as_ancestor === 1 ? 'it' : 'them'}.</span>
            </div>
        `;
    }

    if (plan.entry_contexts_cleared) {
        notes += `
            <div class="import-plan-note">
                <span class="info-icon">ℹ️</span>
                <span>${plan.entry_contexts_cleared}
                ${plan.entry_contexts_cleared === 1 ? 'entry' : 'entries'} chose a
                parent subject that is being removed; that choice is cleared and
                the ${plan.entry_contexts_cleared === 1 ? 'entry rolls' : 'entries roll'}
                up through every parent again.</span>
            </div>
        `;
    }

    if ((plan.errors || []).length) {
        notes += `
            <div class="import-plan-note warning">
                <span class="info-icon">⚠️</span>
                <div>
                    <p><strong>This file cannot be imported as it stands:</strong></p>
                    <ul>${plan.errors.map(
                        e => `<li>${escapeHtml(e)}</li>`).join('')}</ul>
                </div>
            </div>
        `;
    }

    // A whole-exam file leads with its dimensions, because that is the level
    // at which it can cost the student a whole tree (#252). The subject
    // figures follow, and are labelled as subjects so the two rows of numbers
    // cannot be read as one.
    const axisBlock = plan.whole_exam
        ? `
            <div class="import-plan-stats">
                ${stat(c.dimensions_added, ['dimension added', 'dimensions added'], 'is-added')}
                ${stat(c.dimensions_updated, ['dimension updated', 'dimensions updated'], 'is-updated')}
                ${stat(c.dimensions_removed, ['dimension archived', 'dimensions archived'], 'is-removed')}
                ${stat(c.dimensions_kept_in_use, ['dimension kept', 'dimensions kept'], 'is-unchanged')}
            </div>
            ${renderWholeExamAxisTable(plan)}
        `
        : '';

    return `
        ${axisBlock}
        <div class="import-plan-stats">
            ${stat(c.added, plan.whole_exam ? ['subject added', 'subjects added'] : 'added', 'is-added')}
            ${stat(c.updated, plan.whole_exam ? ['subject updated', 'subjects updated'] : 'updated', 'is-updated')}
            ${stat(c.removed, plan.whole_exam ? ['subject removed', 'subjects removed'] : 'removed', 'is-removed')}
            ${stat(c.unchanged, plan.whole_exam ? ['subject unchanged', 'subjects unchanged'] : 'unchanged', 'is-unchanged')}
        </div>
        ${detail.length
            ? `<p class="import-plan-detail">Of the updated subjects,
               ${detail.join(' and ')}.</p>`
            : ''}
        ${notes}
    `;
}

/**
 * Render import preview tree (limited depth for performance)
 * @param {Array} nodes - Nodes to render
 * @param {number} depth - Current depth
 * @param {number} maxDepth - Maximum depth to render
 * @returns {string} HTML string
 */
//: How many subjects the preview will draw before it stops and says how many
//: it did not. Measured (#212): layout is 10-25x the cost of building the HTML
//: string and 8-22x the cost of parsing it, so what has to be bounded is the
//: number of DOM elements, not the depth. A 40x12x5 file materialised 100% of
//: itself -- 11,680 elements in a 93,440-pixel-tall container, 380 ms of
//: layout. 300 nodes keeps the modal's own list to roughly a screen and a half
//: at every file size.
const _PREVIEW_NODE_BUDGET = 300;

/**
 * Subtree sizes for every node, in one bottom-up pass.
 *
 * Replaces calling `countNodesInHierarchy` per node, which walked each
 * subtree again for every ancestor -- 1.8-3.8x the file in redundant visits,
 * measured, and for most nodes the result was then discarded because it is
 * only read when a branch is truncated (#212).
 *
 * Keyed by node object identity, which is safe here because the plan's nodes
 * are the file's own parsed objects and are not copied between the parse and
 * the render.
 */
function importPreviewSubtreeSizes(nodes) {
    const sizes = new Map();
    const visit = (node) => {
        let size = 0;
        for (const child of node.children || []) {
            size += 1 + visit(child);
        }
        sizes.set(node, size);
        return size;
    };
    for (const node of nodes || []) visit(node);
    return sizes;
}

/**
 * How a subject's weight reads in the preview (#250).
 *
 * The format documents three forms and this drew exactly one of them. A
 * `{low, high}` object -- the form real blueprints use, and the reason #64
 * exists -- coerced to NaN in `weight > 0`, so the comparison was false and
 * **no weight was rendered at all**, silently, for precisely the files this
 * preview was built for.
 *
 * A band reads as a band. Flattening it to a midpoint would state a number
 * the file does not contain, which is the thing #64 forbids one layer down.
 */
function importPreviewWeightLabel(weight) {
    const num = (v) => (typeof v === 'number' && isFinite(v) ? v : null);
    if (typeof weight === 'number') {
        return num(weight) ? `${weight.toFixed(1)}%` : '';
    }
    if (weight && typeof weight === 'object') {
        if ('value' in weight) {
            const v = num(weight.value);
            return v ? `${v.toFixed(1)}%` : '';
        }
        const low = num(weight.low);
        const high = num(weight.high);
        if (low === null && high === null) return '';
        if (low !== null && high !== null && low !== high) {
            return `${low.toFixed(1)}\u2013${high.toFixed(1)}%`;
        }
        const single = low !== null ? low : high;
        return single ? `${single.toFixed(1)}%` : '';
    }
    return '';
}

/**
 * Render the import preview's subject list, bounded in the number of nodes
 * it draws (#212).
 *
 * `budget` and `sizes` are threaded through the recursion and default on the
 * top-level call, so the existing two-argument callers are unchanged.
 *
 * **Bounded by node count, not only by depth.** Depth alone is not a limit
 * when the breadth is what is large: a file 40 wide at the top rendered all
 * 2,920 of its nodes with `maxDepth = 3` already in force. The depth limit is
 * kept as well, because it is what keeps a deep narrow tree readable.
 */
function renderImportPreviewTree(nodes, depth = 0, maxDepth = 3,
                                 budget = null, sizes = null) {
    if (!nodes || nodes.length === 0) return '';

    if (budget === null) budget = { left: _PREVIEW_NODE_BUDGET };
    if (sizes === null) sizes = importPreviewSubtreeSizes(nodes);

    const indent = depth * 20;
    const parts = [];

    for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i];
        if (budget.left <= 0) {
            // Everything still unrendered at this level and below it. Read
            // from the sizes map rather than walked again, and indexed rather
            // than searched -- this is a performance fix, so an O(n) lookup
            // here would be in poor taste even at one call per truncation.
            let remaining = 0;
            for (let j = i; j < nodes.length; j++) {
                remaining += 1 + (sizes.get(nodes[j]) || 0);
            }
            parts.push(`
                <div class="import-preview-more" style="margin-left: ${indent}px;">
                    ... and ${remaining} more subject${remaining === 1 ? '' : 's'} not shown
                </div>
            `);
            break;
        }
        budget.left -= 1;

        const hasChildren = node.children && node.children.length > 0;
        const childCount = hasChildren ? (sizes.get(node) || 0) : 0;
        const weightLabel = importPreviewWeightLabel(node.weight);

        let childrenHtml = '';
        if (hasChildren) {
            if (depth < maxDepth) {
                childrenHtml = renderImportPreviewTree(
                    node.children, depth + 1, maxDepth, budget, sizes);
            } else {
                childrenHtml = `
                    <div class="import-preview-more" style="margin-left: ${indent + 20}px;">
                        ... and ${childCount} more nested node${childCount > 1 ? 's' : ''}
                    </div>
                `;
            }
        }

        parts.push(`
            <div class="import-preview-node" style="margin-left: ${indent}px;">
                <span class="preview-icon">${hasChildren ? '\u{1F4C1}' : '\u{1F4C4}'}</span>
                <span class="preview-name">${escapeHtml(node.name)}</span>
                ${weightLabel ? `<span class="preview-weight">${weightLabel}</span>` : ''}
                ${hasChildren && depth >= maxDepth ? `<span class="preview-children-count">(${childCount})</span>` : ''}
            </div>
            ${childrenHtml}
        `);
    }

    return parts.join('');
}


/**
 * Toggle import warnings visibility
 */
function toggleImportWarnings() {
    const list = document.getElementById('import-warning-list');
    const btn = document.querySelector('#import-warnings .toggle-details');
    
    if (list.classList.contains('hidden')) {
        list.classList.remove('hidden');
        btn.textContent = 'Hide Details';
    } else {
        list.classList.add('hidden');
        btn.textContent = 'Show Details';
    }
}

/**
 * Update import mode info display
 */
function updateImportModeInfo() {
    const mode = document.querySelector('input[name="import-mode"]:checked')?.value || 'merge';
    ImportExportState.importMode = mode;
    
    const mergeInfo = document.getElementById('import-merge-info');
    const replaceInfo = document.getElementById('import-replace-info');
    
    if (mode === 'merge') {
        mergeInfo?.classList.remove('hidden');
        replaceInfo?.classList.add('hidden');
    } else {
        mergeInfo?.classList.add('hidden');
        replaceInfo?.classList.remove('hidden');
    }
}

/**
 * Hide import preview modal
 */
function hideImportPreviewModal() {
    document.getElementById('import-preview-modal')?.classList.remove('active');
    ImportExportState.pendingImport = null;
}

/**
 * Execute the import
 */
async function executeImport() {
    const pending = ImportExportState.pendingImport;
    if (!pending) return;
    
    try {
        ImportExportState.isProcessing = true;

        // Update button state
        const confirmBtn = document.getElementById('import-confirm-btn');
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Importing...';
        }

        // Issue #67: the same bytes the preview was planned from.
        const payload = buildImportPayload();

        const result = await api.importSubjectHierarchy(
            TreeState.examContextId, payload
        );

        // Success — report what happened, not how many lines the file
        // had. "Added 2,211 subjects" after a re-import that changed
        // four of them is the message that hid this bug for so long.
        const counts = (result && result.counts) || {};
        const parts = [];
        if (counts.added) parts.push(`${counts.added} added`);
        if (counts.updated) parts.push(`${counts.updated} updated`);
        if (counts.removed) parts.push(`${counts.removed} removed`);
        if (counts.kept_in_use) parts.push(`${counts.kept_in_use} kept in use`);
        Toast.success(
            'Import Complete',
            parts.length ? parts.join(', ') : 'No changes — your tree already matches this file'
        );
        (result?.warnings || []).forEach(
            warning => Toast.error('Import warning', warning)
        );

        // Invalidate dimension cache before reload
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            invalidateDimensionCache(TreeState.currentDimensionId);
        }

        // Reload hierarchy
        await loadHierarchy();
        
        // Close modal
        hideImportPreviewModal();
        
    } catch (error) {
        console.error('Import error:', error);
        Toast.error('Import Failed', error.message);
    } finally {
        ImportExportState.isProcessing = false;
        
        // Restore button
        const confirmBtn = document.getElementById('import-confirm-btn');
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Import';
        }
    }
}

/**
 * Show import error modal
 * @param {Object} validation - Validation result
 */
function showImportErrorModal(validation) {
    // Create modal if needed
    if (!document.getElementById('import-error-modal')) {
        createImportErrorModal();
    }
    
    const errorList = document.getElementById('import-error-list');
    errorList.innerHTML = validation.errors.map(e => `
        <div class="import-error-item">
            <span class="error-icon">❌</span>
            <div class="error-details">
                <span class="error-path">${escapeHtml(e.path)}</span>
                <span class="error-message">${escapeHtml(e.message)}</span>
            </div>
        </div>
    `).join('');
    
    document.getElementById('import-error-modal').classList.add('active');
}

/**
 * Hide import error modal
 */
function hideImportErrorModal() {
    document.getElementById('import-error-modal')?.classList.remove('active');
}

// =========================================================================
// Modal Creation
// =========================================================================

/**
 * Create import preview modal HTML
 */
function createImportPreviewModal() {
    const modal = document.createElement('div');
    modal.id = 'import-preview-modal';
    modal.className = 'modal-backdrop';
    modal.innerHTML = `
        <div class="modal modal-lg" data-modal-surface role="dialog" aria-modal="true"
             aria-labelledby="import-preview-modal-title">
            <div class="modal-header">
                <h2 class="modal-title" id="import-preview-modal-title">📥 Import Preview</h2>
                <button class="modal-close" onclick="hideImportPreviewModal()" aria-label="Close">×</button>
            </div>
            
            <div class="modal-body">
                <!-- File Info -->
                <div class="import-file-info">
                    <div class="file-info-row">
                        <span class="file-icon">📄</span>
                        <span class="file-name" id="import-filename">file.json</span>
                    </div>
                    <div class="import-stats">
                        <span class="stat">
                            <strong id="import-node-count">0</strong> subjects to import
                        </span>
                    </div>
                </div>
                
                <!-- Dimension context notice -->
                <div class="import-mode-info hidden" id="import-dimension-notice">
                    <!-- Filled dynamically -->
                </div>

                <!-- Metadata -->
                <div class="import-metadata hidden" id="import-metadata">
                    <!-- Filled dynamically -->
                </div>
                
                <!-- Warnings -->
                <div class="import-warnings hidden" id="import-warnings">
                    <!-- Filled dynamically -->
                </div>
                
                <!-- Preview Tree -->
                <div class="import-preview-section">
                    <h4 class="section-title">Preview</h4>
                    <div class="import-preview-tree" id="import-preview-tree">
                        <!-- Filled dynamically -->
                    </div>
                </div>
                
                <!-- What this import will do (issue #67).
                     There used to be a Merge / Replace choice here.
                     "Merge" meant *append*, which is the bug: it
                     duplicated whatever had been renamed. Import is now
                     a merge against your existing tree in every case, so
                     the only thing "Replace" still did that this does
                     not was delete subjects your entries are tagged to —
                     which #67 decision 3 forbids an import from doing.
                     A control whose one remaining effect is forbidden is
                     not a choice, so the section states the outcome
                     instead of offering a mode. -->
                <div class="import-mode-section">
                    <h4 class="section-title">What this import will do</h4>
                    <div class="import-merge-plan" id="import-merge-plan">
                        <!-- Filled by loadImportMergePlan() -->
                    </div>
                    <div class="import-mode-info" id="import-merge-info">
                        <span class="info-icon">ℹ️</span>
                        <span>Merged into your existing
                        <strong id="import-existing-count">0</strong> subjects.
                        Subjects your entries are tagged to are never
                        removed by an import.</span>
                    </div>
                </div>
            </div>
            
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="hideImportPreviewModal()">Cancel</button>
                <button class="btn btn-primary" id="import-confirm-btn" onclick="executeImport()">
                    Import
                </button>
            </div>
        </div>
    `;
    
    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) hideImportPreviewModal();
    });
    
    document.body.appendChild(modal);
}

/**
 * Create import error modal HTML
 */
function createImportErrorModal() {
    const modal = document.createElement('div');
    modal.id = 'import-error-modal';
    modal.className = 'modal-backdrop';
    modal.innerHTML = `
        <div class="modal" data-modal-surface role="dialog" aria-modal="true"
             aria-labelledby="import-error-modal-title">
            <div class="modal-icon error">❌</div>
            <h2 class="modal-title" id="import-error-modal-title">Import Failed</h2>
            <p class="modal-message">The file could not be imported due to the following errors:</p>
            
            <div class="import-error-list" id="import-error-list">
                <!-- Filled dynamically -->
            </div>
            
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="hideImportErrorModal()">Close</button>
            </div>
        </div>
    `;
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) hideImportErrorModal();
    });
    
    document.body.appendChild(modal);
}

// =========================================================================
// Utility Functions
// =========================================================================

/**
 * Format date string for display
 * @param {string} dateStr - ISO date string
 * @returns {string} Formatted date
 */
function formatDate(dateStr) {
    if (!dateStr) return 'Unknown';
    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
    } catch {
        return dateStr;
    }
}

/**
 * Escape HTML (use global if available)
 */
function escapeHtmlImport(text) {
    if (typeof escapeHtml === 'function') {
        return escapeHtml(text);
    }
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =========================================================================
// Override existing functions
// =========================================================================

// Store original functions
const _originalExportHierarchy = window.exportHierarchy;
const _originalTriggerImport = window.triggerImport;
const _originalHandleImportFile = window.handleImportFile;

// Override with enhanced versions
window.exportHierarchy = exportHierarchyEnhanced;
window.triggerImport = triggerImportEnhanced;
window.handleImportFile = handleImportFileEnhanced;

// =========================================================================
// Global Exports
// =========================================================================

// =========================================================================
// Import Help Modal
// =========================================================================

// Cache for markdown content
let cachedHelpContent = null;

/**
 * Simple markdown to HTML parser
 * Handles: headers, code blocks, inline code, tables, lists, bold, italic, links, hr
 */
function parseMarkdown(markdown) {
    let html = markdown;
    
    // Escape HTML entities (but preserve code blocks first)
    const codeBlocks = [];
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        const index = codeBlocks.length;
        codeBlocks.push({ lang, code: code.trim() });
        return `__CODE_BLOCK_${index}__`;
    });
    
    // Escape remaining HTML
    html = html
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    
    // Restore code blocks with syntax highlighting placeholder
    html = html.replace(/__CODE_BLOCK_(\d+)__/g, (match, index) => {
        const block = codeBlocks[parseInt(index)];
        const langClass = block.lang ? ` class="language-${block.lang}"` : '';
        return `<pre${langClass}><code>${escapeHtml(block.code)}</code></pre>`;
    });
    
    // Headers (must be at start of line)
    html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    
    // Horizontal rules
    html = html.replace(/^---+$/gm, '<hr>');
    
    // Tables
    html = html.replace(/^\|(.+)\|\s*\n\|[-|: ]+\|\s*\n((?:\|.+\|\s*\n?)+)/gm, (match, header, body) => {
        const headers = header.split('|').map(h => h.trim()).filter(h => h);
        const rows = body.trim().split('\n').map(row => 
            row.split('|').map(cell => cell.trim()).filter(cell => cell)
        );
        
        let table = '<table><thead><tr>';
        headers.forEach(h => table += `<th>${h}</th>`);
        table += '</tr></thead><tbody>';
        rows.forEach(row => {
            table += '<tr>';
            row.forEach(cell => table += `<td>${cell}</td>`);
            table += '</tr>';
        });
        table += '</tbody></table>';
        return table;
    });
    
    // Bold and Italic
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    
    // Inline code (after code blocks to avoid conflicts)
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    
    // Unordered lists
    html = html.replace(/^(\s*)[-*] (.+)$/gm, (match, indent, content) => {
        const level = Math.floor(indent.length / 2);
        return `<li data-level="${level}">${content}</li>`;
    });
    
    // Wrap consecutive list items
    html = html.replace(/(<li[^>]*>.*<\/li>\n?)+/g, (match) => {
        return '<ul>' + match + '</ul>';
    });
    
    // Ordered lists
    html = html.replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => {
        if (!match.includes('<ul>')) {
            return '<ol>' + match + '</ol>';
        }
        return match;
    });
    
    // Paragraphs - wrap lines that aren't already wrapped
    const lines = html.split('\n');
    const processedLines = [];
    let inParagraph = false;
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        const isBlockElement = /^<(h[1-6]|ul|ol|li|table|thead|tbody|tr|th|td|pre|hr|blockquote)/.test(line) ||
                              /<\/(h[1-6]|ul|ol|table|pre|blockquote)>$/.test(line);
        
        if (line === '') {
            if (inParagraph) {
                processedLines.push('</p>');
                inParagraph = false;
            }
            processedLines.push('');
        } else if (isBlockElement) {
            if (inParagraph) {
                processedLines.push('</p>');
                inParagraph = false;
            }
            processedLines.push(line);
        } else {
            if (!inParagraph) {
                processedLines.push('<p>');
                inParagraph = true;
            }
            processedLines.push(line);
        }
    }
    
    if (inParagraph) {
        processedLines.push('</p>');
    }
    
    return processedLines.join('\n');
}

/**
 * Show the import help modal with markdown documentation.
 * The guide is embedded in the page (#import-help-source, a text/markdown
 * script block in tree_editor.html) and rendered locally — no bridge fetch.
 */
function showImportHelpModal() {
    const modal = document.getElementById('import-help-modal');
    const content = document.getElementById('import-help-content');

    if (!modal || !content) return;

    modal.classList.add('active');

    // If we have cached content, use it
    if (cachedHelpContent) {
        content.innerHTML = cachedHelpContent;
        return;
    }

    const source = document.getElementById('import-help-source');
    if (source && source.textContent.trim()) {
        const htmlContent = parseMarkdown(source.textContent.trim());
        cachedHelpContent = htmlContent;
        content.innerHTML = htmlContent;
    } else {
        console.error('Import help source block missing from page');

        // Show fallback content
        content.innerHTML = `
            <div class="error-message">
                <h3>⚠️ Unable to Load Documentation</h3>
                <p>The import format documentation could not be loaded.</p>
                <p>Please refer to the documentation file at:</p>
                <code>docs/examples/subject_tree_import_format.md</code>
                
                <h3 style="margin-top: 24px;">Quick Reference</h3>
                <p>Import files should be JSON with this structure:</p>
                <pre><code>{
  "root_nodes": [
    {
      "name": "Subject Name",
      "level_type": "System",
      "weight": { "low": 20, "high": 25 },
      "children": [ ... ]
    }
  ]
}</code></pre>
                
                <h4>Weight Formats</h4>
                <ul>
                    <li><strong>Range:</strong> <code>{"low": 20, "high": 25}</code></li>
                    <li><strong>Single value:</strong> <code>{"value": 50}</code></li>
                    <li><strong>Simple:</strong> <code>"weight": 50</code></li>
                </ul>
            </div>
        `;
    }
}

/**
 * Hide the import help modal
 */
function hideImportHelpModal() {
    const modal = document.getElementById('import-help-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

/**
 * Initialize help button event listener
 */
function initImportHelpButton() {
    const helpBtn = document.getElementById('btn-import-help');
    if (helpBtn) {
        helpBtn.addEventListener('click', showImportHelpModal);
    }
    
    // Close modal on backdrop click
    const modal = document.getElementById('import-help-modal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                hideImportHelpModal();
            }
        });
    }
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initImportHelpButton);
} else {
    initImportHelpButton();
}

window.exportHierarchyEnhanced = exportHierarchyEnhanced;
window.exportWholeExamHierarchy = exportWholeExamHierarchy;
// The pure builders, exposed so a scenario can assert on what the export
// WRITES without going through a browser download (#237). Before this, the
// only thing guarding "never write the row id" was a comment.
window.buildSingleTreeExport = buildSingleTreeExport;
window.buildWholeExamExport = buildWholeExamExport;
// #212 / #250: pure, and the only way to assert on what the preview draws.
window.renderImportPreviewTree = renderImportPreviewTree;
window.renderWholeExamPlanNotes = renderWholeExamPlanNotes;
window.renderWholeExamAxisTable = renderWholeExamAxisTable;
window.importPreviewWeightLabel = importPreviewWeightLabel;
window.importPreviewSubtreeSizes = importPreviewSubtreeSizes;
window.countNodesInHierarchy = countNodesInHierarchy;
window.triggerImportEnhanced = triggerImportEnhanced;
window.handleImportFileEnhanced = handleImportFileEnhanced;
window.showImportPreviewModal = showImportPreviewModal;
window.hideImportPreviewModal = hideImportPreviewModal;
window.executeImport = executeImport;
window.buildImportPayload = buildImportPayload;
window.loadImportMergePlan = loadImportMergePlan;
window.renderImportMergePlan = renderImportMergePlan;
window.toggleImportWarnings = toggleImportWarnings;
window.updateImportModeInfo = updateImportModeInfo;
window.hideImportErrorModal = hideImportErrorModal;
window.showImportHelpModal = showImportHelpModal;
window.hideImportHelpModal = hideImportHelpModal;
window.ImportExportState = ImportExportState;
