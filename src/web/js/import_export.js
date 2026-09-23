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

        // Fetch aliases for all subjects in this exam (keyed by node ID)
        const aliasMap = new Map();
        try {
            const subjects = await api.getAllSubjectsWithAliasesForExam(TreeState.examContextId);
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

        // Build export object
        const exportData = {
            // Metadata section
            ...(includeMetadata && {
                _metadata: {
                    export_version: '1.1',
                    exported_at: new Date().toISOString(),
                    exported_from: 'WIMI Desktop',
                    exam_name: TreeState.examContext?.exam_name || 'Unknown',
                    exam_id: TreeState.examContextId,
                    total_nodes: countNodesInHierarchy(hierarchyData?.root_nodes || []),
                    hierarchy_levels: TreeState.hierarchyLevels?.map(l => l.level_name) || [],
                    ...(isDimensionMode && {
                        dimension_id: TreeState.currentDimensionId,
                        dimension_name: TreeState.currentDimension?.name || 'Unknown'
                    })
                }
            }),

            // Root nodes
            root_nodes: cleanNodesForExport(hierarchyData?.root_nodes || [], includeWeights, aliasMap)
        };

        // Create blob and download
        const jsonString = prettyPrint
            ? JSON.stringify(exportData, null, 2)
            : JSON.stringify(exportData);

        const blob = new Blob([jsonString], { type: 'application/json' });
        const url = URL.createObjectURL(blob);

        // Generate filename - include dimension name for multi-dimensional exams
        const examName = (TreeState.examContext?.exam_name || 'hierarchy')
            .replace(/[^a-z0-9]/gi, '_')
            .toLowerCase();
        const date = new Date().toISOString().split('T')[0];
        let filename;
        if (isDimensionMode) {
            const dimName = (TreeState.currentDimension?.name || 'dimension')
                .replace(/[^a-z0-9]/gi, '_')
                .toLowerCase();
            filename = `${examName}_${dimName}_subjects_${date}.json`;
        } else {
            filename = `${examName}_subjects_${date}.json`;
        }
        
        // Trigger download
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        
        URL.revokeObjectURL(url);
        
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
        const rootNodes = api.getImportRootNodes(data).nodes || [];
        ImportExportState.pendingImport = {
            filename: file.name,
            data: data,
            rootNodes: rootNodes,
            nodeCount: countNodesInHierarchy(rootNodes),
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
    
    rootNodes.forEach((node, i) => {
        validateNode(node, `${usedKey}[${i}]`);
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
    
    checkWeightTotals(rootNodes, usedKey);
    
    return {
        errors,
        warnings,
        hasValidNodes: validNodeCount > 0,
        validNodeCount
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
    
    // Show dimension context notice when in dimension mode
    const dimensionNoticeEl = document.getElementById('import-dimension-notice');
    if (dimensionNoticeEl) {
        if (TreeState.usesDimensions && TreeState.currentDimensionId && TreeState.currentDimension) {
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
function renderImportMergePlan(plan) {
    const c = plan.counts || {};
    const stat = (n, label, cls) => `
        <div class="import-plan-stat ${n ? cls : 'is-zero'}">
            <span class="import-plan-number">${n || 0}</span>
            <span class="import-plan-label">${label}</span>
        </div>
    `;

    const detail = [];
    if (c.renamed) detail.push(`${c.renamed} renamed`);
    if (c.moved) detail.push(`${c.moved} moved`);

    let notes = '';

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
        const links = (plan.kept_in_use || []).map(item => `
            <li>
                <a class="import-plan-link"
                   href="entry_browser.html?exam=${encodeURIComponent(plan.exam_context_id)}&subject=${encodeURIComponent(item.id)}">
                    ${escapeHtml(item.name)}</a>
                <span class="import-plan-count">${item.entry_count}
                    ${item.entry_count === 1 ? 'entry' : 'entries'}</span>
            </li>
        `).join('');
        const more = plan.kept_in_use_total > (plan.kept_in_use || []).length
            ? `<li class="import-plan-more">and ${
                plan.kept_in_use_total - plan.kept_in_use.length} more</li>`
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

    return `
        <div class="import-plan-stats">
            ${stat(c.added, 'added', 'is-added')}
            ${stat(c.updated, 'updated', 'is-updated')}
            ${stat(c.removed, 'removed', 'is-removed')}
            ${stat(c.unchanged, 'unchanged', 'is-unchanged')}
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
function renderImportPreviewTree(nodes, depth = 0, maxDepth = 3) {
    if (!nodes || nodes.length === 0) return '';
    
    const indent = depth * 20;
    
    return nodes.map((node, i) => {
        const hasChildren = node.children && node.children.length > 0;
        const weight = node.weight || 0;
        const childCount = hasChildren ? countNodesInHierarchy(node.children) : 0;
        
        let childrenHtml = '';
        if (hasChildren) {
            if (depth < maxDepth) {
                childrenHtml = renderImportPreviewTree(node.children, depth + 1, maxDepth);
            } else {
                childrenHtml = `
                    <div class="import-preview-more" style="margin-left: ${indent + 20}px;">
                        ... and ${childCount} more nested node${childCount > 1 ? 's' : ''}
                    </div>
                `;
            }
        }
        
        return `
            <div class="import-preview-node" style="margin-left: ${indent}px;">
                <span class="preview-icon">${hasChildren ? '📁' : '📄'}</span>
                <span class="preview-name">${escapeHtml(node.name)}</span>
                ${weight > 0 ? `<span class="preview-weight">${weight.toFixed(1)}%</span>` : ''}
                ${hasChildren && depth >= maxDepth ? `<span class="preview-children-count">(${childCount})</span>` : ''}
            </div>
            ${childrenHtml}
        `;
    }).join('');
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
        <div class="modal modal-lg">
            <div class="modal-header">
                <h3 class="modal-title">📥 Import Preview</h3>
                <button class="modal-close" onclick="hideImportPreviewModal()">×</button>
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
        <div class="modal">
            <div class="modal-icon error">❌</div>
            <h3 class="modal-title">Import Failed</h3>
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
