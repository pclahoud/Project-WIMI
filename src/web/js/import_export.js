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
    isProcessing: false
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
        
        // Store pending import data
        ImportExportState.pendingImport = {
            filename: file.name,
            data: data,
            nodeCount: countNodesInHierarchy(data.root_nodes || []),
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
    
    // Check for root_nodes OR subjects array (support both formats)
    const rootNodes = data.root_nodes || data.subjects;
    
    if (!rootNodes) {
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
            path: 'root_nodes',
            severity: 'error'
        });
        return { errors, warnings, hasValidNodes: false };
    }
    
    // Normalize data structure if "subjects" was used
    if (data.subjects && !data.root_nodes) {
        data.root_nodes = data.subjects;
        warnings.push({
            type: 'format',
            message: 'File uses "subjects" key instead of "root_nodes" - auto-converted',
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
        
        // Check weight (optional but validate if present)
        if (node.weight !== undefined) {
            if (typeof node.weight === 'object' && node.weight !== null) {
                // Weight range format: {low, high}
                const low = node.weight.low;
                const high = node.weight.high;
                if (typeof low !== 'number' || typeof high !== 'number') {
                    warnings.push({
                        type: 'field',
                        message: `Weight range has non-numeric values, will default to 0`,
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
    
    data.root_nodes.forEach((node, i) => {
        validateNode(node, `root_nodes[${i}]`);
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
    
    checkWeightTotals(data.root_nodes, 'root_nodes');
    
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
    previewContainer.innerHTML = renderImportPreviewTree(pending.data.root_nodes || [], 0, 3);
    
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
    
    const mode = ImportExportState.importMode;
    
    try {
        ImportExportState.isProcessing = true;
        
        // Update button state
        const confirmBtn = document.getElementById('import-confirm-btn');
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Importing...';
        }
        
        // If replace mode, we need to delete existing nodes first
        if (mode === 'replace' && TreeState.rootNodes.length > 0) {
            // Delete all existing root nodes (cascade deletes children)
            for (const node of TreeState.rootNodes) {
                await api.deleteSubjectNode(node.id);
            }
        }
        
        // Include dimension_id in import data when in dimension mode
        const importData = { ...pending.data };
        if (TreeState.usesDimensions && TreeState.currentDimensionId) {
            importData.dimension_id = TreeState.currentDimensionId;
        }

        // Import the new hierarchy
        await api.importSubjectHierarchy(
            TreeState.examContextId,
            JSON.stringify(importData)
        );

        // Success
        const actionText = mode === 'replace' ? 'Replaced with' : 'Added';
        Toast.success('Import Complete', `${actionText} ${pending.nodeCount} subjects`);

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
                
                <!-- Import Mode -->
                <div class="import-mode-section">
                    <h4 class="section-title">Import Mode</h4>
                    <div class="import-mode-options">
                        <label class="import-mode-option">
                            <input type="radio" name="import-mode" value="merge" checked onchange="updateImportModeInfo()">
                            <div class="mode-content">
                                <span class="mode-title">➕ Merge</span>
                                <span class="mode-desc">Add to existing subjects</span>
                            </div>
                        </label>
                        <label class="import-mode-option">
                            <input type="radio" name="import-mode" value="replace" onchange="updateImportModeInfo()">
                            <div class="mode-content">
                                <span class="mode-title">🔄 Replace</span>
                                <span class="mode-desc">Remove existing, import new</span>
                            </div>
                        </label>
                    </div>
                    
                    <div class="import-mode-info" id="import-merge-info">
                        <span class="info-icon">ℹ️</span>
                        <span>Will add to your existing <strong id="import-existing-count">0</strong> subjects</span>
                    </div>
                    
                    <div class="import-mode-info warning hidden" id="import-replace-info">
                        <span class="info-icon">⚠️</span>
                        <span>This will <strong>delete all existing subjects</strong> and replace them with the imported ones</span>
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
window.toggleImportWarnings = toggleImportWarnings;
window.updateImportModeInfo = updateImportModeInfo;
window.hideImportErrorModal = hideImportErrorModal;
window.showImportHelpModal = showImportHelpModal;
window.hideImportHelpModal = hideImportHelpModal;
window.ImportExportState = ImportExportState;
