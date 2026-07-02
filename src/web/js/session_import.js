/**
 * WIMI Session Import Wizard
 * Multi-step wizard for importing question data from external JSON sources.
 */

// =========================================================================
// Built-in Mapping Profiles (Templates)
// =========================================================================

const BUILTIN_PROFILES = [
    {
        id: 'builtin_amboss',
        profile_name: 'AMBOSS (Default)',
        source_type: 'amboss',
        field_mappings: JSON.stringify({
            mappings: [
                { source: 'question_number', target: 'question_id' },
                { source: 'incorrect_answer', target: 'user_answer' },
                { source: 'correct_answer', target: 'correct_answer' },
                { source: 'correct_answer_explanation', target: 'explanation' },
                { source: 'incorrect_answer_explanation', target: 'reflection' }
            ]
        }),
        builtin: true
    },
    {
        id: 'builtin_uworld',
        profile_name: 'UWorld (Default)',
        source_type: 'uworld',
        field_mappings: JSON.stringify({
            mappings: [
                { source: 'question_number', target: 'question_id' },
                { source: 'incorrect_answer', target: 'user_answer' },
                { source: 'correct_answer', target: 'correct_answer' },
                { source: 'correct_answer_explanation', target: 'explanation' },
                { source: 'incorrect_answer_explanation', target: 'reflection' }
            ]
        }),
        builtin: true
    }
];

// WIMI target field options
const TARGET_FIELDS = [
    { value: '(skip)', label: '-- Skip --' },
    { value: 'question_id', label: 'Question ID' },
    { value: 'user_answer', label: 'User Answer' },
    { value: 'correct_answer', label: 'Correct Answer' },
    { value: 'explanation', label: 'Explanation' },
    { value: 'reflection', label: 'Reflection' },
    { value: 'notes', label: 'Notes' },
    { value: 'perceived_difficulty', label: 'Perceived Difficulty' },
    { value: 'time_spent_seconds', label: 'Time Spent (seconds)' }
];

// Auto-detection mapping for obvious field names
const AUTO_DETECT_MAP = {
    'question_number': 'question_id',
    'question_id': 'question_id',
    'question_text': '(skip)',
    'incorrect_answer': 'user_answer',
    'user_answer': 'user_answer',
    'correct_answer': 'correct_answer',
    'correct_answer_explanation': 'explanation',
    'explanation': 'explanation',
    'incorrect_answer_explanation': 'reflection',
    'reflection': 'reflection',
    'notes': 'notes',
    'perceived_difficulty': 'perceived_difficulty',
    'difficulty': 'perceived_difficulty',
    'time_spent_seconds': 'time_spent_seconds',
    'time_spent': 'time_spent_seconds',
    'answer_choices_text': '(skip)',
    'anki_card_ids': '(skip)'
};

// Fields to skip in mapping UI (handled separately by the import engine)
const SKIP_FIELDS = ['images'];

// =========================================================================
// Import Wizard State
// =========================================================================

const ImportState = {
    currentStep: 1,
    totalSteps: 5,
    fileData: null,       // Analysis result from readImportJsonFile
    filePath: null,
    mappings: [],         // Array of {source, target, merge_order}
    savedProfiles: [],    // From DB
    sessionConfig: {
        questionSourceId: null,
        dateEncountered: '',
        sessionName: '',
        importImages: true,
        imagesDirectory: '',
        sessionDurationMinutes: null
    },
    importResult: null
};

// =========================================================================
// Wizard Lifecycle
// =========================================================================

function openImportWizard() {
    resetImportState();
    const modal = document.getElementById('import-wizard-modal');
    modal.classList.add('active');
    updateWizardStep(1);
    loadMappingProfiles();
}

function closeImportWizard() {
    const modal = document.getElementById('import-wizard-modal');
    modal.classList.remove('active');
    resetImportState();
}

function resetImportState() {
    ImportState.currentStep = 1;
    ImportState.fileData = null;
    ImportState.filePath = null;
    ImportState.mappings = [];
    ImportState.sessionConfig = {
        questionSourceId: null,
        dateEncountered: '',
        sessionName: '',
        importImages: true,
        imagesDirectory: '',
        sessionDurationMinutes: null
    };
    ImportState.importResult = null;

    // Reset UI
    const dropzone = document.getElementById('import-file-dropzone');
    const fileInfo = document.getElementById('import-file-info');
    if (dropzone) dropzone.classList.remove('hidden');
    if (fileInfo) fileInfo.classList.add('hidden');
}

// =========================================================================
// Step Navigation
// =========================================================================

function updateWizardStep(step) {
    ImportState.currentStep = step;

    // Update progress bar
    const fill = document.getElementById('import-progress-fill');
    fill.style.width = `${(step / ImportState.totalSteps) * 100}%`;

    // Update step indicators
    document.querySelectorAll('.import-step-indicator').forEach(el => {
        const s = parseInt(el.dataset.step);
        el.classList.remove('active', 'completed');
        if (s === step) el.classList.add('active');
        else if (s < step) el.classList.add('completed');
    });

    // Show/hide step content
    document.querySelectorAll('.import-wizard-step').forEach(el => {
        el.classList.remove('active');
    });
    const activeStep = document.getElementById(`import-step-${step}`);
    if (activeStep) activeStep.classList.add('active');

    // Update navigation buttons
    updateNavButtons(step);

    // Run step-specific logic
    if (step === 2) renderMappingTable();
    if (step === 3) prepareConfigStep();
    if (step === 4) renderPreview();
    if (step === 5) executeImport();
}

function updateNavButtons(step) {
    const btnBack = document.getElementById('import-btn-back');
    const btnNext = document.getElementById('import-btn-next');
    const btnCancel = document.getElementById('import-btn-cancel');

    // Back button
    if (step > 1 && step < 5) {
        btnBack.classList.remove('hidden');
    } else {
        btnBack.classList.add('hidden');
    }

    // Next/Import button
    if (step === 5) {
        btnNext.classList.add('hidden');
        btnCancel.textContent = 'Close';
    } else if (step === 4) {
        btnNext.textContent = 'Import';
        btnNext.classList.remove('hidden');
        btnNext.disabled = false;
    } else {
        btnNext.textContent = 'Next';
        btnNext.classList.remove('hidden');
        // Enable/disable based on step validation
        btnNext.disabled = !isStepValid(step);
    }

    // Cancel button visibility
    if (step === 5 && ImportState.importResult) {
        btnCancel.textContent = 'Close';
    } else {
        btnCancel.textContent = 'Cancel';
    }
}

function isStepValid(step) {
    switch (step) {
        case 1: return ImportState.fileData !== null;
        case 2: return ImportState.mappings.some(m => m.target !== '(skip)');
        case 3: return true;
        case 4: return true;
        default: return false;
    }
}

function goNext() {
    if (ImportState.currentStep < ImportState.totalSteps) {
        updateWizardStep(ImportState.currentStep + 1);
    }
}

function goBack() {
    if (ImportState.currentStep > 1) {
        updateWizardStep(ImportState.currentStep - 1);
    }
}

// =========================================================================
// Step 1: File Selection
// =========================================================================

async function selectImportFile() {
    try {
        const result = await api.openImportFileDialog();
        if (!result) return; // User cancelled

        const filePath = result.file_path;
        ImportState.filePath = filePath;

        // Read and analyze the file
        const analysis = await api.readImportJsonFile(filePath);
        ImportState.fileData = analysis;

        // Update UI
        renderFileInfo(analysis);

        // Pre-fill session config from metadata
        if (analysis.session_metadata) {
            if (analysis.session_metadata.session_name) {
                ImportState.sessionConfig.sessionName = analysis.session_metadata.session_name;
            }
            if (analysis.session_metadata.date_scraped) {
                // Extract date portion from ISO datetime
                const dateStr = analysis.session_metadata.date_scraped.split('T')[0];
                ImportState.sessionConfig.dateEncountered = dateStr;
            }
        }

        if (analysis.has_images) {
            ImportState.sessionConfig.imagesDirectory = analysis.images_directory;
            ImportState.sessionConfig.importImages = true;
        } else {
            ImportState.sessionConfig.importImages = false;
        }

        // Auto-detect field mappings
        autoDetectMappings(analysis.question_fields);

        // Enable next button
        updateNavButtons(1);
    } catch (err) {
        console.error('Error selecting import file:', err);
        if (typeof Toast !== 'undefined') {
            Toast.show('Error reading file: ' + err.message, 'error');
        }
    }
}

function renderFileInfo(analysis) {
    const dropzone = document.getElementById('import-file-dropzone');
    const fileInfo = document.getElementById('import-file-info');

    dropzone.classList.add('hidden');
    fileInfo.classList.remove('hidden');

    const fileName = ImportState.filePath.split(/[/\\]/).pop();

    fileInfo.innerHTML = `
        <div class="import-file-info-header">
            <div class="import-file-name">📄 ${escapeHtml(fileName)}</div>
            <button type="button" class="btn btn-secondary btn-sm" id="btn-change-file">Change File</button>
        </div>
        <div class="import-file-stats">
            <div class="import-stat-item">
                <div class="import-stat-value">${analysis.question_count}</div>
                <div class="import-stat-label">Questions</div>
            </div>
            <div class="import-stat-item">
                <div class="import-stat-value">${analysis.question_fields.length}</div>
                <div class="import-stat-label">Fields</div>
            </div>
            <div class="import-stat-item">
                <div class="import-stat-value">${analysis.image_count || 0}</div>
                <div class="import-stat-label">Images</div>
            </div>
        </div>
        ${analysis.session_metadata?.session_name ? `<div style="margin-top: var(--space-sm); font-size: var(--font-size-sm); color: var(--text-secondary);">Session: ${escapeHtml(analysis.session_metadata.session_name)}</div>` : ''}
    `;

    // Re-bind change file button
    document.getElementById('btn-change-file').addEventListener('click', () => {
        dropzone.classList.remove('hidden');
        fileInfo.classList.add('hidden');
        ImportState.fileData = null;
        ImportState.filePath = null;
        updateNavButtons(1);
        selectImportFile();
    });
}

function autoDetectMappings(questionFields) {
    ImportState.mappings = [];
    for (const field of questionFields) {
        if (SKIP_FIELDS.includes(field)) continue;
        const autoTarget = AUTO_DETECT_MAP[field] || '(skip)';
        ImportState.mappings.push({
            source: field,
            target: autoTarget,
            merge_order: 0
        });
    }

    // Assign merge_order for duplicate targets
    assignMergeOrders();
}

function assignMergeOrders() {
    const targetCounts = {};
    for (const m of ImportState.mappings) {
        if (m.target === '(skip)') continue;
        if (!targetCounts[m.target]) targetCounts[m.target] = [];
        targetCounts[m.target].push(m);
    }
    for (const target in targetCounts) {
        const group = targetCounts[target];
        if (group.length > 1) {
            group.forEach((m, i) => { m.merge_order = i + 1; });
        } else {
            group[0].merge_order = 0;
        }
    }
}

// =========================================================================
// Step 2: Field Mapping
// =========================================================================

function renderMappingTable() {
    const tbody = document.getElementById('import-mapping-tbody');
    tbody.innerHTML = '';

    for (let i = 0; i < ImportState.mappings.length; i++) {
        const mapping = ImportState.mappings[i];
        const row = document.createElement('tr');

        // Source field column
        const tdSource = document.createElement('td');
        tdSource.innerHTML = `<span class="import-source-field">${escapeHtml(mapping.source)}</span>`;

        // Show sample value
        if (ImportState.fileData?.sample_question) {
            const sampleVal = ImportState.fileData.sample_question[mapping.source];
            if (sampleVal !== undefined && sampleVal !== null && typeof sampleVal !== 'object') {
                const truncated = String(sampleVal).length > 80
                    ? String(sampleVal).substring(0, 80) + '...'
                    : String(sampleVal);
                tdSource.innerHTML += `<div class="import-sample-value">${escapeHtml(truncated)}</div>`;
            }
        }

        // Target select column
        const tdTarget = document.createElement('td');
        const select = document.createElement('select');
        select.className = 'import-target-select';
        select.dataset.index = i;

        for (const tf of TARGET_FIELDS) {
            const opt = document.createElement('option');
            opt.value = tf.value;
            opt.textContent = tf.label;
            if (tf.value === mapping.target) opt.selected = true;
            select.appendChild(opt);
        }

        select.addEventListener('change', (e) => {
            const idx = parseInt(e.target.dataset.index);
            ImportState.mappings[idx].target = e.target.value;
            assignMergeOrders();
            renderMappingTable();
            updateNavButtons(2);
        });

        tdTarget.appendChild(select);

        // Check if this target has merge conflicts
        const sameTargetCount = ImportState.mappings.filter(
            m => m.target === mapping.target && m.target !== '(skip)'
        ).length;

        if (sameTargetCount > 1) {
            const badge = document.createElement('div');
            badge.className = 'import-merge-badge';
            badge.textContent = `Merge #${mapping.merge_order}`;
            tdTarget.appendChild(badge);
        }

        // Merge order column
        const tdOrder = document.createElement('td');
        if (sameTargetCount > 1) {
            const orderInput = document.createElement('input');
            orderInput.type = 'number';
            orderInput.className = 'import-merge-order-input';
            orderInput.min = 1;
            orderInput.value = mapping.merge_order;
            orderInput.dataset.index = i;
            orderInput.addEventListener('change', (e) => {
                const idx = parseInt(e.target.dataset.index);
                ImportState.mappings[idx].merge_order = parseInt(e.target.value) || 1;
            });
            tdOrder.appendChild(orderInput);
        }

        row.appendChild(tdSource);
        row.appendChild(tdTarget);
        row.appendChild(tdOrder);
        tbody.appendChild(row);
    }

    // Render sample preview section
    renderSamplePreview();
}

function renderSamplePreview() {
    const container = document.getElementById('import-sample-content');
    if (!ImportState.fileData?.sample_question) {
        container.innerHTML = '<em>No sample data available</em>';
        return;
    }

    const question = ImportState.fileData.sample_question;
    const mapped = applyMappingsToQuestion(question);

    let html = '';
    for (const [field, value] of Object.entries(mapped)) {
        if (!value) continue;
        const label = TARGET_FIELDS.find(f => f.value === field)?.label || field;
        const truncated = String(value).length > 200
            ? String(value).substring(0, 200) + '...'
            : String(value);
        html += `
            <div class="import-entry-field">
                <div class="import-entry-field-label">${escapeHtml(label)}</div>
                <div class="import-entry-field-value">${escapeHtml(truncated)}</div>
            </div>
        `;
    }

    container.innerHTML = html || '<em>No fields mapped yet</em>';
}

function applyMappingsToQuestion(question) {
    const targetGroups = {};
    for (const mapping of ImportState.mappings) {
        if (mapping.target === '(skip)') continue;
        if (!targetGroups[mapping.target]) targetGroups[mapping.target] = [];
        targetGroups[mapping.target].push({
            source: mapping.source,
            merge_order: mapping.merge_order
        });
    }

    const result = {};
    for (const [target, sources] of Object.entries(targetGroups)) {
        sources.sort((a, b) => a.merge_order - b.merge_order);
        const values = sources
            .map(s => question[s.source])
            .filter(v => v !== undefined && v !== null)
            .map(v => String(v));
        if (values.length > 0) {
            result[target] = values.length > 1 ? values.join(' | ') : values[0];
        }
    }
    return result;
}

// =========================================================================
// Step 3: Session Configuration
// =========================================================================

async function prepareConfigStep() {
    // Load sources dropdown
    loadImportSources();

    // Pre-fill from metadata
    const dateInput = document.getElementById('import-session-date');
    const nameInput = document.getElementById('import-session-name');
    const imagesCheckbox = document.getElementById('import-images-checkbox');
    const imagesInfo = document.getElementById('import-images-info');

    if (ImportState.sessionConfig.dateEncountered) {
        dateInput.value = ImportState.sessionConfig.dateEncountered;
    } else {
        dateInput.value = new Date().toISOString().split('T')[0];
    }

    nameInput.value = ImportState.sessionConfig.sessionName || '';
    imagesCheckbox.checked = ImportState.sessionConfig.importImages;

    if (ImportState.fileData?.has_images) {
        imagesCheckbox.disabled = false;
        imagesInfo.textContent = `${ImportState.fileData.image_count} images found in images/ folder`;
    } else {
        imagesCheckbox.disabled = true;
        imagesCheckbox.checked = false;
        imagesInfo.textContent = 'No images/ folder found alongside the JSON file';
    }

    // Initialize duration controls
    const durationPreset = document.getElementById('import-duration-preset');
    const durationCustom = document.getElementById('import-duration-custom');
    if (durationPreset && durationCustom && !durationPreset.dataset.initialized) {
        durationPreset.dataset.initialized = 'true';

        // Toggle custom input visibility
        durationPreset.addEventListener('change', () => {
            durationCustom.style.display = durationPreset.value === 'custom' ? 'inline-block' : 'none';
            if (durationPreset.value !== 'custom') {
                durationCustom.value = '';
            }
        });

        // Pre-fill from user preferences
        try {
            const prefs = await api.getUserPreferences();
            const defaultMinutes = prefs.default_session_duration_minutes;
            if (defaultMinutes) {
                const presetValues = Array.from(durationPreset.options).map(o => o.value);
                if (presetValues.includes(String(defaultMinutes))) {
                    durationPreset.value = String(defaultMinutes);
                } else {
                    durationPreset.value = 'custom';
                    durationCustom.style.display = 'inline-block';
                    durationCustom.value = defaultMinutes;
                }
            }
        } catch (e) {
            console.warn('Could not load user preferences for import duration:', e);
        }
    }
}

function getImportDurationMinutes() {
    const presetSelect = document.getElementById('import-duration-preset');
    if (!presetSelect) return null;

    if (presetSelect.value === '0') return null;
    if (presetSelect.value === 'custom') {
        const customInput = document.getElementById('import-duration-custom');
        const val = customInput ? parseInt(customInput.value) : null;
        return (val && val > 0) ? val : null;
    }
    return parseInt(presetSelect.value) || null;
}

async function loadImportSources() {
    const container = document.getElementById('import-source-select-container');
    try {
        const examName = SessionState.examContext?.exam_name;
        const sources = await api.getQuestionSources(examName);

        let html = '<select id="import-source-id" class="import-target-select" style="width: 100%;">';
        html += '<option value="">-- Select Source --</option>';
        for (const src of sources) {
            html += `<option value="${src.id}">${escapeHtml(src.source_name)}</option>`;
        }
        html += '</select>';
        container.innerHTML = html;

        // Pre-select if session_name hints at source
        const sourceSelect = document.getElementById('import-source-id');
        if (ImportState.sessionConfig.questionSourceId) {
            sourceSelect.value = ImportState.sessionConfig.questionSourceId;
        }
        sourceSelect.addEventListener('change', (e) => {
            ImportState.sessionConfig.questionSourceId = e.target.value ? parseInt(e.target.value) : null;
        });
    } catch (err) {
        container.innerHTML = '<em>Error loading sources</em>';
    }
}

// =========================================================================
// Step 4: Preview
// =========================================================================

function renderPreview() {
    // Collect config from step 3 inputs
    const dateInput = document.getElementById('import-session-date');
    const nameInput = document.getElementById('import-session-name');
    const imagesCheckbox = document.getElementById('import-images-checkbox');
    const sourceSelect = document.getElementById('import-source-id');

    ImportState.sessionConfig.dateEncountered = dateInput?.value || '';
    ImportState.sessionConfig.sessionName = nameInput?.value || '';
    ImportState.sessionConfig.importImages = imagesCheckbox?.checked || false;
    ImportState.sessionConfig.sessionDurationMinutes = getImportDurationMinutes();
    if (sourceSelect) {
        ImportState.sessionConfig.questionSourceId = sourceSelect.value ? parseInt(sourceSelect.value) : null;
    }

    // Summary stats
    const summary = document.getElementById('import-preview-summary');
    const activeMappings = ImportState.mappings.filter(m => m.target !== '(skip)');
    summary.innerHTML = `
        <div class="import-preview-stat">
            <div class="import-preview-stat-value">${ImportState.fileData.question_count}</div>
            <div class="import-preview-stat-label">Questions</div>
        </div>
        <div class="import-preview-stat">
            <div class="import-preview-stat-value">${activeMappings.length}</div>
            <div class="import-preview-stat-label">Fields Mapped</div>
        </div>
        <div class="import-preview-stat">
            <div class="import-preview-stat-value">${ImportState.sessionConfig.importImages ? (ImportState.fileData.image_count || 0) : 0}</div>
            <div class="import-preview-stat-label">Images</div>
        </div>
        <div class="import-preview-stat">
            <div class="import-preview-stat-value">${ImportState.sessionConfig.sessionDurationMinutes ? ImportState.sessionConfig.sessionDurationMinutes + ' min' : 'None'}</div>
            <div class="import-preview-stat-label">Duration</div>
        </div>
    `;

    // Mapping preview table
    const mappingPreview = document.getElementById('import-mapping-preview');
    let tableHtml = '<table><thead><tr><th>Source</th><th>Target</th></tr></thead><tbody>';
    for (const m of activeMappings) {
        const targetLabel = TARGET_FIELDS.find(f => f.value === m.target)?.label || m.target;
        tableHtml += `<tr><td>${escapeHtml(m.source)}</td><td>${escapeHtml(targetLabel)}${m.merge_order > 0 ? ` (merge #${m.merge_order})` : ''}</td></tr>`;
    }
    tableHtml += '</tbody></table>';
    mappingPreview.innerHTML = tableHtml;

    // Entry preview
    if (ImportState.fileData?.sample_question) {
        const question = ImportState.fileData.sample_question;
        const mapped = applyMappingsToQuestion(question);
        const previewContent = document.getElementById('import-entry-preview-content');
        let html = '';
        for (const [field, value] of Object.entries(mapped)) {
            if (!value) continue;
            const label = TARGET_FIELDS.find(f => f.value === field)?.label || field;
            const truncated = String(value).length > 300
                ? String(value).substring(0, 300) + '...'
                : String(value);
            html += `
                <div class="import-entry-field">
                    <div class="import-entry-field-label">${escapeHtml(label)}</div>
                    <div class="import-entry-field-value">${escapeHtml(truncated)}</div>
                </div>
            `;
        }
        previewContent.innerHTML = html || '<em>No fields mapped</em>';
    }
}

// =========================================================================
// Step 5: Execute Import
// =========================================================================

async function executeImport() {
    const progressContainer = document.getElementById('import-progress-container');
    const resultsContainer = document.getElementById('import-results');
    const progressLabel = document.getElementById('import-progress-label');
    const barFill = document.getElementById('import-bar-fill');

    progressContainer.classList.remove('hidden');
    resultsContainer.classList.add('hidden');
    barFill.style.width = '10%';
    progressLabel.textContent = 'Preparing import...';

    // Build field_mappings array for the bridge
    const fieldMappings = ImportState.mappings
        .filter(m => m.target !== '(skip)')
        .map(m => ({
            source: m.source,
            target: m.target,
            merge_order: m.merge_order
        }));

    const importConfig = {
        file_path: ImportState.filePath,
        exam_context_id: SessionState.examContextId,
        question_source_id: ImportState.sessionConfig.questionSourceId,
        session_name: ImportState.sessionConfig.sessionName || null,
        date_encountered: ImportState.sessionConfig.dateEncountered || null,
        field_mappings: fieldMappings,
        import_images: ImportState.sessionConfig.importImages,
        images_directory: ImportState.sessionConfig.imagesDirectory || '',
        session_duration_minutes: ImportState.sessionConfig.sessionDurationMinutes
    };

    barFill.style.width = '30%';
    progressLabel.textContent = 'Importing questions...';

    try {
        const result = await api.executeSessionImport(importConfig);
        ImportState.importResult = result;

        barFill.style.width = '100%';
        progressLabel.textContent = 'Complete!';

        // Show results after a brief delay
        setTimeout(() => {
            progressContainer.classList.add('hidden');
            resultsContainer.classList.remove('hidden');
            renderResults(result);
            updateNavButtons(5);
        }, 500);
    } catch (err) {
        progressContainer.classList.add('hidden');
        resultsContainer.classList.remove('hidden');
        resultsContainer.innerHTML = `
            <div class="import-results-icon">❌</div>
            <div class="import-results-title">Import Failed</div>
            <div class="import-results-errors">
                <strong>Error:</strong> ${escapeHtml(err.message)}
            </div>
        `;
        updateNavButtons(5);
    }
}

function renderResults(result) {
    const container = document.getElementById('import-results');

    let html = `
        <div class="import-results-icon">✅</div>
        <div class="import-results-title">Import Complete</div>
        <div class="import-results-stats">
            <div class="import-result-stat">
                <div class="import-result-stat-value">${result.entries_created}</div>
                <div class="import-result-stat-label">Entries Created</div>
            </div>
            <div class="import-result-stat">
                <div class="import-result-stat-value">${result.images_imported}</div>
                <div class="import-result-stat-label">Images Imported</div>
            </div>
            <div class="import-result-stat">
                <div class="import-result-stat-value">${result.total_questions - result.entries_created}</div>
                <div class="import-result-stat-label">Errors</div>
            </div>
        </div>
    `;

    if (result.errors && result.errors.length > 0) {
        html += `<div class="import-results-errors"><strong>Errors:</strong><ul>`;
        for (const err of result.errors) {
            html += `<li>${escapeHtml(err)}</li>`;
        }
        html += '</ul></div>';
    }

    if (result.warnings && result.warnings.length > 0) {
        html += `<div class="import-results-warnings"><strong>Warnings:</strong><ul>`;
        for (const w of result.warnings) {
            html += `<li>${escapeHtml(w)}</li>`;
        }
        html += '</ul></div>';
    }

    html += `
        <button type="button" class="btn btn-primary btn-lg" id="btn-go-to-session">
            Go to Session
        </button>
    `;

    container.innerHTML = html;

    document.getElementById('btn-go-to-session').addEventListener('click', () => {
        window.location.href = `question_entry.html?session_id=${result.session_id}`;
    });
}

// =========================================================================
// Mapping Profiles
// =========================================================================

async function loadMappingProfiles() {
    try {
        const profiles = await api.getImportMappingProfiles();
        ImportState.savedProfiles = profiles || [];
    } catch (err) {
        ImportState.savedProfiles = [];
    }
    renderProfileDropdown();
}

function renderProfileDropdown() {
    const select = document.getElementById('import-profile-select');
    if (!select) return;

    select.innerHTML = '<option value="">-- Load Profile --</option>';

    // Add built-in profiles
    for (const bp of BUILTIN_PROFILES) {
        const opt = document.createElement('option');
        opt.value = bp.id;
        opt.textContent = bp.profile_name;
        select.appendChild(opt);
    }

    // Add user-saved profiles
    if (ImportState.savedProfiles.length > 0) {
        const optGroup = document.createElement('optgroup');
        optGroup.label = 'Saved Profiles';
        for (const p of ImportState.savedProfiles) {
            const opt = document.createElement('option');
            opt.value = `saved_${p.id}`;
            opt.textContent = p.profile_name;
            optGroup.appendChild(opt);
        }
        select.appendChild(optGroup);
    }
}

function loadProfile(profileId) {
    let mappingsJson;

    if (profileId.startsWith('builtin_')) {
        const bp = BUILTIN_PROFILES.find(p => p.id === profileId);
        if (!bp) return;
        mappingsJson = bp.field_mappings;
    } else if (profileId.startsWith('saved_')) {
        const dbId = parseInt(profileId.replace('saved_', ''));
        const sp = ImportState.savedProfiles.find(p => p.id === dbId);
        if (!sp) return;
        mappingsJson = sp.field_mappings;
    } else {
        return;
    }

    try {
        const parsed = JSON.parse(mappingsJson);
        const profileMappings = parsed.mappings || [];

        // Apply profile mappings to current fields
        for (const m of ImportState.mappings) {
            const profileMatch = profileMappings.find(pm => pm.source === m.source);
            if (profileMatch) {
                m.target = profileMatch.target;
                m.merge_order = profileMatch.merge_order || 0;
            } else {
                m.target = '(skip)';
                m.merge_order = 0;
            }
        }

        assignMergeOrders();
        renderMappingTable();
        updateNavButtons(2);
    } catch (err) {
        console.error('Error loading profile:', err);
    }
}

async function saveCurrentProfile() {
    const modal = document.getElementById('save-profile-modal');
    modal.classList.add('active');
}

async function doSaveProfile() {
    const nameInput = document.getElementById('save-profile-name');
    const typeSelect = document.getElementById('save-profile-source-type');
    const name = nameInput.value.trim();

    if (!name) {
        nameInput.focus();
        return;
    }

    const activeMappings = ImportState.mappings
        .filter(m => m.target !== '(skip)')
        .map(m => ({
            source: m.source,
            target: m.target,
            merge_order: m.merge_order
        }));

    try {
        await api.createImportMappingProfile({
            profile_name: name,
            source_type: typeSelect.value,
            field_mappings: { mappings: activeMappings }
        });

        const modal = document.getElementById('save-profile-modal');
        modal.classList.remove('active');
        nameInput.value = '';

        await loadMappingProfiles();
        if (typeof Toast !== 'undefined') {
            Toast.show('Profile saved!', 'success');
        }
    } catch (err) {
        console.error('Error saving profile:', err);
        if (typeof Toast !== 'undefined') {
            Toast.show('Error saving profile: ' + err.message, 'error');
        }
    }
}

// =========================================================================
// Utility
// =========================================================================

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

// =========================================================================
// Event Binding
// =========================================================================

function initImportWizard() {
    // Import Session button
    const btnImport = document.getElementById('btn-import-session');
    if (btnImport) {
        btnImport.addEventListener('click', openImportWizard);
    }

    // File selection
    const dropzone = document.getElementById('import-file-dropzone');
    if (dropzone) {
        dropzone.addEventListener('click', selectImportFile);
        // Keyboard activation (role="button" + tabindex="0" for accessibility)
        dropzone.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                selectImportFile();
            }
        });
    }

    // Navigation
    const btnNext = document.getElementById('import-btn-next');
    const btnBack = document.getElementById('import-btn-back');
    const btnCancel = document.getElementById('import-btn-cancel');

    if (btnNext) btnNext.addEventListener('click', goNext);
    if (btnBack) btnBack.addEventListener('click', goBack);
    if (btnCancel) {
        btnCancel.addEventListener('click', () => {
            if (ImportState.importResult) {
                // Refresh the page to show the new session
                window.location.reload();
            } else {
                closeImportWizard();
            }
        });
    }

    // Profile dropdown
    const profileSelect = document.getElementById('import-profile-select');
    if (profileSelect) {
        profileSelect.addEventListener('change', (e) => {
            if (e.target.value) loadProfile(e.target.value);
        });
    }

    // Save profile button
    const btnSaveProfile = document.getElementById('btn-save-mapping-profile');
    if (btnSaveProfile) {
        btnSaveProfile.addEventListener('click', saveCurrentProfile);
    }

    // Save profile modal
    const btnSaveProfileSave = document.getElementById('save-profile-save');
    const btnSaveProfileCancel = document.getElementById('save-profile-cancel');
    if (btnSaveProfileSave) btnSaveProfileSave.addEventListener('click', doSaveProfile);
    if (btnSaveProfileCancel) {
        btnSaveProfileCancel.addEventListener('click', () => {
            document.getElementById('save-profile-modal').classList.remove('active');
        });
    }

    // Close modal on backdrop click
    const importModal = document.getElementById('import-wizard-modal');
    if (importModal) {
        importModal.addEventListener('click', (e) => {
            if (e.target === importModal && !ImportState.importResult) {
                closeImportWizard();
            }
        });
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', initImportWizard);
