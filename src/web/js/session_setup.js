/**
 * WIMI Session Setup JavaScript
 * Phase 4 - Review Session Setup Page
 */

// =========================================================================
// Helpers
// =========================================================================

/**
 * Normalize a SQLite datetime string to a valid ISO 8601 UTC string.
 * SQLite datetime('now') returns "2026-03-12 14:30:00" (space, no T, no Z).
 * JS Date requires "2026-03-12T14:30:00Z" for reliable cross-engine parsing.
 */
function toISOUTC(str) {
    if (!str) return str;
    return str.replace(' ', 'T').replace(/T(\d{2}:\d{2}:\d{2})$/, 'T$1Z');
}

// =========================================================================
// State Management
// =========================================================================

const SessionState = {
    examContextId: null,
    examContext: null,
    sources: [],
    previousSessions: [],
    isLoading: true,
    selectedSourceId: null,
    editingSourceId: null,
    sourceSelect: null,  // CustomSelect instance for new session form
    editSourceSelect: null  // CustomSelect instance for edit session modal
};

// =========================================================================
// Toast Notification System (reused from landing.js)
// =========================================================================

const Toast = {
    container: null,
    
    init() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.className = 'toast-container';
            document.body.appendChild(this.container);
        }
    },
    
    show(type, title, message, duration = 4000) {
        this.init();
        
        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };
        
        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.setAttribute('data-testid', `session-toast-${type}`);
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || 'ℹ'}</span>
            <div class="toast-content">
                <p class="toast-title">${title}</p>
                ${message ? `<p class="toast-message">${message}</p>` : ''}
            </div>
            <button class="toast-close" aria-label="Close">×</button>
        `;
        
        this.container.appendChild(toast);
        
        requestAnimationFrame(() => {
            toast.classList.add('show');
        });
        
        toast.querySelector('.toast-close').addEventListener('click', () => {
            this.dismiss(toast);
        });
        
        if (duration > 0) {
            setTimeout(() => this.dismiss(toast), duration);
        }
        
        return toast;
    },
    
    dismiss(toast) {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    },
    
    success(title, message) { return this.show('success', title, message); },
    error(title, message) { return this.show('error', title, message); },
    warning(title, message) { return this.show('warning', title, message); },
    info(title, message) { return this.show('info', title, message); }
};

// =========================================================================
// Modal Management
// =========================================================================

const Modal = {
    open(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
        }
    },
    
    close(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('active');
            document.body.style.overflow = '';
        }
    },
    
    initCloseHandlers(modalId, onClose) {
        const modal = document.getElementById(modalId);
        if (!modal) return;
        
        // Close on backdrop click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.close(modalId);
                if (onClose) onClose();
            }
        });
        
        // ESC key handler
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.classList.contains('active')) {
                this.close(modalId);
                if (onClose) onClose();
            }
        });
    }
};

// =========================================================================
// Utilities
// =========================================================================

function getUrlParam(param) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(param);
}

function formatDate(dateStr) {
    if (!dateStr) return 'Unknown';
    try {
        const [y, m, d] = dateStr.slice(0, 10).split('-').map(Number);
        if (!y || !m || !d) return dateStr;
        const date = new Date(y, m - 1, d);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    } catch {
        return dateStr;
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getTodayDateString() {
    const today = new Date();
    return today.toISOString().split('T')[0];
}

function getSourceTypeLabel(type) {
    const labels = {
        'commercial_prep': 'Commercial Prep',
        'official_prep': 'Official Prep',
        'textbook': 'Textbook',
        'online_platform': 'Online Platform',
        'practice_tests': 'Practice Tests',
        'previous_exams': 'Previous Exams',
        'tutoring_materials': 'Tutoring Materials',
        'flashcard_system': 'Flashcard System',
        'video_course': 'Video Course',
        'study_group': 'Study Group',
        'other': 'Other'
    };
    return labels[type] || type;
}

// =========================================================================
// Previous Sessions Rendering
// =========================================================================

function renderPreviousSessionCard(session) {
    const completionPercent = session.total_incorrect > 0 
        ? Math.round((session.entries_completed / session.total_incorrect) * 100) 
        : 100;
    
    const isComplete = completionPercent >= 100 || session.session_status === 'completed';
    
    // Determine status class and text based on both status field and completion percentage
    let statusClass, statusText;
    if (session.session_status === 'completed' || isComplete) {
        statusClass = 'badge-completed';
        statusText = 'Complete';
    } else if (session.session_status === 'abandoned') {
        statusClass = 'badge-abandoned';
        statusText = 'Abandoned';
    } else {
        statusClass = 'badge-in-progress';
        statusText = 'In Progress';
    }
    
    // Show Continue for incomplete in-progress sessions, Review for complete or abandoned
    const actionButton = session.session_status !== 'abandoned' && !isComplete
        ? `<button class="btn btn-primary btn-sm" onclick="continueSession(${session.id})">Continue</button>`
        : `<button class="btn btn-secondary btn-sm" onclick="viewSession(${session.id})">Review</button>`;
    
    return `
        <div class="prev-session-card" data-session-id="${session.id}" data-testid="session-card-${session.id}">
            <div class="prev-session-header">
                <div>
                    <h4 class="prev-session-name">${escapeHtml(session.session_name || 'Untitled Session')}</h4>
                    <div class="prev-session-date">${formatDate(session.date_encountered)}</div>
                </div>
                <span class="badge ${statusClass}">${statusText}</span>
            </div>
            
            <div class="prev-session-stats">
                <div class="prev-session-stat">
                    <span class="prev-session-stat-label">Total</span>
                    <span class="prev-session-stat-value">${session.total_questions}</span>
                </div>
                <div class="prev-session-stat">
                    <span class="prev-session-stat-label">Incorrect</span>
                    <span class="prev-session-stat-value">${session.total_incorrect}</span>
                </div>
                <div class="prev-session-stat">
                    <span class="prev-session-stat-label">Logged</span>
                    <span class="prev-session-stat-value">${session.entries_completed}/${session.total_incorrect}</span>
                </div>
            </div>
            
            <div class="prev-session-progress">
                <div class="progress-bar">
                    <div class="progress-fill ${isComplete ? 'complete' : ''}" style="width: ${completionPercent}%"></div>
                </div>
                <div class="progress-text">${completionPercent}% complete</div>
            </div>
            
            <div class="prev-session-actions">
                ${actionButton}
                <button class="btn btn-secondary btn-sm" onclick="editSession(${session.id})">Edit</button>
                <button class="btn btn-secondary btn-sm" onclick="exportSessionIds(${session.id})">
                    Export IDs
                </button>
                <button class="btn btn-danger-outline btn-sm" onclick="confirmDeleteSession(${session.id}, '${escapeHtml(session.session_name || 'Untitled Session').replace(/'/g, "\\'")}')">
                    Delete
                </button>
            </div>
        </div>
    `;
}

async function loadPreviousSessions() {
    const container = document.getElementById('previous-sessions-container');
    const loadingEl = document.getElementById('sessions-loading');
    const emptyEl = document.getElementById('sessions-empty');
    
    try {
        const sessions = await api.getReviewSessions(SessionState.examContextId, true);
        SessionState.previousSessions = sessions || [];
        
        if (loadingEl) loadingEl.classList.add('hidden');
        
        if (SessionState.previousSessions.length === 0) {
            container.innerHTML = '';
            emptyEl?.classList.remove('hidden');
        } else {
            emptyEl?.classList.add('hidden');
            container.innerHTML = SessionState.previousSessions
                .map(renderPreviousSessionCard)
                .join('');
        }
    } catch (error) {
        console.error('Error loading previous sessions:', error);
        if (loadingEl) loadingEl.classList.add('hidden');
        container.innerHTML = `<div class="sessions-empty"><p>Failed to load sessions</p></div>`;
    }
}

// =========================================================================
// Question Sources Management
// =========================================================================

async function loadQuestionSources() {
    try {
        const sources = await api.getQuestionSources(SessionState.examContext?.exam_name);
        SessionState.sources = sources || [];
        
        // Build options array for custom select
        const options = SessionState.sources.map(source => ({
            value: String(source.id),
            label: source.source_name
        }));
        
        // Initialize or update custom select
        if (!SessionState.sourceSelect) {
            const container = document.getElementById('source-select-container');
            SessionState.sourceSelect = new CustomSelect(container, {
                id: 'session-source',
                placeholder: 'Select a source...',
                options: options,
                value: SessionState.selectedSourceId ? String(SessionState.selectedSourceId) : '',
                onChange: (value) => {
                    SessionState.selectedSourceId = value ? parseInt(value) : null;
                    validateForm();
                }
            });
        } else {
            // Update existing select with new options
            SessionState.sourceSelect.setOptions(options);
            
            // Restore selection if valid
            if (SessionState.selectedSourceId) {
                SessionState.sourceSelect.setValue(String(SessionState.selectedSourceId));
            }
        }
        
        validateForm();
    } catch (error) {
        console.error('Error loading question sources:', error);
        Toast.error('Failed to load sources', error.message);
    }
}

function renderSourceItem(source) {
    return `
        <div class="source-item" data-source-id="${source.id}" data-testid="source-item-${source.id}">
            <div class="source-info">
                <div class="source-name">${escapeHtml(source.source_name)}</div>
                <div class="source-type">${getSourceTypeLabel(source.source_type)}</div>
            </div>
            <div class="source-actions">
                <button class="btn btn-secondary btn-icon-sm" onclick="editSource(${source.id})" title="Edit">
                    ✏️
                </button>
            </div>
        </div>
    `;
}

async function loadSourcesForModal() {
    const container = document.getElementById('sources-list');
    
    try {
        // Sources should already be loaded
        if (SessionState.sources.length === 0) {
            container.innerHTML = `
                <div class="sources-empty">
                    <div class="sources-empty-icon">📚</div>
                    <p>No question sources yet.<br>Add one to get started!</p>
                </div>
            `;
        } else {
            container.innerHTML = SessionState.sources.map(renderSourceItem).join('');
        }
    } catch (error) {
        console.error('Error loading sources for modal:', error);
        container.innerHTML = `<div class="sources-empty"><p>Failed to load sources</p></div>`;
    }
}

// =========================================================================
// Add Source Modal
// =========================================================================

function openAddSourceModal() {
    // Clear form
    document.getElementById('new-source-name').value = '';
    document.getElementById('new-source-type').value = 'commercial_prep';
    document.getElementById('new-source-description').value = '';
    
    Modal.open('add-source-modal');
    document.getElementById('new-source-name').focus();
}

async function saveNewSource() {
    const name = document.getElementById('new-source-name').value.trim();
    const type = document.getElementById('new-source-type').value;
    const description = document.getElementById('new-source-description').value.trim();
    
    if (!name) {
        Toast.error('Name Required', 'Please enter a source name.');
        return;
    }
    
    const saveBtn = document.getElementById('add-source-save');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner spinner-sm"></span> Saving...';
    
    try {
        const source = await api.createQuestionSource({
            source_name: name,
            source_type: type,
            description: description || null,
            exam_context: SessionState.examContext?.exam_name
        });
        
        Modal.close('add-source-modal');
        Toast.success('Source Added', `"${name}" has been added.`);
        
        // Reload sources and select the new one
        await loadQuestionSources();
        if (SessionState.sourceSelect) {
            SessionState.sourceSelect.setValue(String(source.id), true);
        }
        SessionState.selectedSourceId = source.id;
        validateForm();
        
        // If manage modal is open, refresh it
        if (document.getElementById('manage-sources-modal').classList.contains('active')) {
            loadSourcesForModal();
        }
        
    } catch (error) {
        console.error('Error adding source:', error);
        Toast.error('Failed to Add', error.message);
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Add Source';
    }
}

// =========================================================================
// Edit Source Modal
// =========================================================================

function editSource(sourceId) {
    const source = SessionState.sources.find(s => s.id === sourceId);
    if (!source) return;
    
    SessionState.editingSourceId = sourceId;
    
    document.getElementById('edit-source-id').value = sourceId;
    document.getElementById('edit-source-name').value = source.source_name;
    document.getElementById('edit-source-type').value = source.source_type || 'other';
    document.getElementById('edit-source-description').value = source.description || '';
    
    Modal.close('manage-sources-modal');
    Modal.open('edit-source-modal');
}

async function saveEditedSource() {
    const sourceId = parseInt(document.getElementById('edit-source-id').value);
    const name = document.getElementById('edit-source-name').value.trim();
    const type = document.getElementById('edit-source-type').value;
    const description = document.getElementById('edit-source-description').value.trim();
    
    if (!name) {
        Toast.error('Name Required', 'Please enter a source name.');
        return;
    }
    
    const saveBtn = document.getElementById('edit-source-save');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner spinner-sm"></span> Saving...';
    
    try {
        await api.updateQuestionSource(sourceId, {
            source_name: name,
            source_type: type,
            description: description || null
        });
        
        Modal.close('edit-source-modal');
        Toast.success('Source Updated', `"${name}" has been updated.`);
        
        // Reload sources
        await loadQuestionSources();
        
        // Re-open manage modal
        Modal.open('manage-sources-modal');
        loadSourcesForModal();
        
    } catch (error) {
        console.error('Error updating source:', error);
        Toast.error('Failed to Update', error.message);
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save Changes';
    }
}

// =========================================================================
// Delete Source
// =========================================================================

function confirmDeleteSource() {
    const sourceId = parseInt(document.getElementById('edit-source-id').value);
    const source = SessionState.sources.find(s => s.id === sourceId);
    if (!source) return;
    
    document.getElementById('delete-source-name').textContent = source.source_name;
    
    Modal.close('edit-source-modal');
    Modal.open('delete-source-modal');
}

async function deleteSource() {
    const sourceId = parseInt(document.getElementById('edit-source-id').value);
    
    const confirmBtn = document.getElementById('delete-source-confirm');
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = '<span class="spinner spinner-sm"></span> Deleting...';
    
    try {
        await api.deleteQuestionSource(sourceId);
        
        Modal.close('delete-source-modal');
        Toast.success('Source Deleted', 'The source has been removed.');
        
        // Clear selection if deleted source was selected
        if (SessionState.selectedSourceId === sourceId) {
            SessionState.selectedSourceId = null;
            if (SessionState.sourceSelect) {
                SessionState.sourceSelect.setValue('');
            }
        }
        
        // Reload sources
        await loadQuestionSources();
        
        // Re-open manage modal
        Modal.open('manage-sources-modal');
        loadSourcesForModal();
        
    } catch (error) {
        console.error('Error deleting source:', error);
        Toast.error('Failed to Delete', error.message);
    } finally {
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Delete';
    }
}

// =========================================================================
// Form Validation
// =========================================================================

function validateForm() {
    const source = SessionState.sourceSelect ? SessionState.sourceSelect.getValue() : '';
    const date = document.getElementById('session-date').value;
    const totalQuestions = document.getElementById('session-total-questions').value;
    const totalIncorrect = document.getElementById('session-total-incorrect').value;
    
    const isValid = source && date && totalQuestions && totalIncorrect;
    const startBtn = document.getElementById('btn-start-session');
    
    // Additional validation
    let errorMessage = '';
    
    if (totalQuestions && totalIncorrect) {
        const total = parseInt(totalQuestions);
        const incorrect = parseInt(totalIncorrect);
        
        if (incorrect > total) {
            errorMessage = 'Questions incorrect cannot exceed total questions.';
        }
        if (total < 1) {
            errorMessage = 'Total questions must be at least 1.';
        }
        if (incorrect < 0) {
            errorMessage = 'Questions incorrect cannot be negative.';
        }
    }
    
    const errorContainer = document.getElementById('form-error');
    const errorMessageEl = document.getElementById('form-error-message');
    
    if (errorMessage) {
        errorMessageEl.textContent = errorMessage;
        errorContainer.classList.remove('hidden');
        startBtn.disabled = true;
    } else {
        errorContainer.classList.add('hidden');
        startBtn.disabled = !isValid;
    }
    
    return isValid && !errorMessage;
}

// =========================================================================
// Session Duration
// =========================================================================

async function initializeSessionDuration() {
    const presetSelect = document.getElementById('session-duration-preset');
    const customInput = document.getElementById('session-duration-custom');
    if (!presetSelect || !customInput) return;

    // Toggle custom input visibility
    presetSelect.addEventListener('change', () => {
        customInput.style.display = presetSelect.value === 'custom' ? 'inline-block' : 'none';
        if (presetSelect.value !== 'custom') {
            customInput.value = '';
        }
    });

    // Pre-fill from user preferences
    try {
        const prefs = await api.getUserPreferences();
        const defaultMinutes = prefs.default_session_duration_minutes;
        if (defaultMinutes) {
            const presetValues = Array.from(presetSelect.options).map(o => o.value);
            if (presetValues.includes(String(defaultMinutes))) {
                presetSelect.value = String(defaultMinutes);
            } else {
                presetSelect.value = 'custom';
                customInput.style.display = 'inline-block';
                customInput.value = defaultMinutes;
            }
        }
    } catch (e) {
        console.warn('Could not load user preferences for session duration:', e);
    }
}

function getSessionDurationMinutes() {
    const presetSelect = document.getElementById('session-duration-preset');
    if (!presetSelect) return null;

    if (presetSelect.value === '0') return null;
    if (presetSelect.value === 'custom') {
        const customInput = document.getElementById('session-duration-custom');
        const val = customInput ? parseInt(customInput.value) : null;
        return (val && val > 0) ? val : null;
    }
    return parseInt(presetSelect.value) || null;
}

// =========================================================================
// Session Actions
// =========================================================================

async function startSession() {
    if (!validateForm()) return;
    
    const source = SessionState.sourceSelect ? SessionState.sourceSelect.getValue() : '';
    const date = document.getElementById('session-date').value;
    const totalQuestions = parseInt(document.getElementById('session-total-questions').value);
    const totalIncorrect = parseInt(document.getElementById('session-total-incorrect').value);
    const sessionName = document.getElementById('session-name').value.trim();
    
    // Generate session name if not provided
    const selectedSource = SessionState.sources.find(s => s.id == source);
    const generatedName = sessionName || `${selectedSource?.source_name || 'Practice'} - ${formatDate(date)}`;
    
    const startBtn = document.getElementById('btn-start-session');
    startBtn.disabled = true;
    startBtn.innerHTML = '<span class="spinner spinner-sm"></span> Creating...';
    
    try {
        const session = await api.createReviewSession({
            exam_context_id: SessionState.examContextId,
            question_source_id: parseInt(source),
            session_name: generatedName,
            date_encountered: date,
            total_questions: totalQuestions,
            total_incorrect: totalIncorrect,
            session_duration_minutes: getSessionDurationMinutes()
        });
        if (window.eventBus) eventBus.emit('session:created', { id: session.id });

        Toast.success('Session Created', 'Redirecting to question entry...');
        
        // Navigate to question entry page
        setTimeout(() => {
            window.location.href = `question_entry.html?session_id=${session.id}`;
        }, 500);
        
    } catch (error) {
        console.error('Error creating session:', error);
        Toast.error('Failed to Create', error.message);
        startBtn.disabled = false;
        startBtn.textContent = 'Start Session';
    }
}

function continueSession(sessionId) {
    window.location.href = `question_entry.html?session_id=${sessionId}`;
}

function viewSession(sessionId) {
    // For now, also go to question entry (will add view mode later)
    window.location.href = `question_entry.html?session_id=${sessionId}&mode=view`;
}

// =========================================================================
// Delete Session
// =========================================================================

let deleteSessionId = null;

function confirmDeleteSession(sessionId, sessionName) {
    deleteSessionId = sessionId;
    document.getElementById('delete-session-name').textContent = sessionName;
    Modal.open('delete-session-modal');
}

async function deleteSession() {
    if (!deleteSessionId) return;
    
    const confirmBtn = document.getElementById('delete-session-confirm');
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = '<span class="spinner spinner-sm"></span> Deleting...';
    
    try {
        await api.deleteReviewSession(deleteSessionId);
        if (window.eventBus) eventBus.emit('session:deleted', { id: deleteSessionId });

        Modal.close('delete-session-modal');
        Toast.success('Session Deleted', 'The review session has been removed.');
        
        // Reload sessions list
        await loadPreviousSessions();
        
    } catch (error) {
        console.error('Error deleting session:', error);
        Toast.error('Failed to Delete', error.message);
    } finally {
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Delete Session';
        deleteSessionId = null;
    }
}

// =========================================================================
// Edit Session Modal
// =========================================================================

function editSession(sessionId) {
    const session = SessionState.previousSessions.find(s => s.id === sessionId);
    if (!session) return;

    document.getElementById('edit-session-id').value = sessionId;
    document.getElementById('edit-session-name').value = session.session_name || '';
    document.getElementById('edit-session-date').value = session.date_encountered || '';
    document.getElementById('edit-session-total-questions').value = session.total_questions || '';
    document.getElementById('edit-session-total-incorrect').value = session.total_incorrect;

    // Clear any previous error
    document.getElementById('edit-session-error').style.display = 'none';

    // Show hint about entries completed
    const hint = document.getElementById('edit-session-min-hint');
    hint.textContent = session.entries_completed > 0
        ? `${session.entries_completed} entries already logged`
        : '';

    // Build source dropdown from already-loaded sources
    const options = SessionState.sources.map(source => ({
        value: String(source.id),
        label: source.source_name
    }));

    // Clear previous instance if exists
    if (SessionState.editSourceSelect) {
        SessionState.editSourceSelect = null;
    }

    const container = document.getElementById('edit-source-select-container');
    container.innerHTML = '';
    SessionState.editSourceSelect = new CustomSelect(container, {
        id: 'edit-session-source',
        placeholder: 'Select a source...',
        options: options,
        value: session.question_source_id ? String(session.question_source_id) : ''
    });

    // Listen for changes to show/hide entry picker in real-time
    const totalQEl = document.getElementById('edit-session-total-questions');
    const totalIEl = document.getElementById('edit-session-total-incorrect');
    const onEditFieldChange = () => checkEntryPickerNeeded(sessionId);
    totalQEl.removeEventListener('input', totalQEl._editHandler);
    totalIEl.removeEventListener('input', totalIEl._editHandler);
    totalQEl._editHandler = onEditFieldChange;
    totalIEl._editHandler = onEditFieldChange;
    totalQEl.addEventListener('input', onEditFieldChange);
    totalIEl.addEventListener('input', onEditFieldChange);

    // Load and render timer round history
    loadRoundHistory(sessionId);

    Modal.open('edit-session-modal');
}

async function loadRoundHistory(sessionId) {
    const section = document.getElementById('round-history-section');
    const list = document.getElementById('round-history-list');
    if (!section || !list) return;

    try {
        const rounds = await api.getTimerRounds(sessionId);
        if (!rounds || rounds.length === 0) {
            section.style.display = 'none';
            return;
        }
        section.style.display = 'block';
        renderRoundHistory(rounds);
    } catch (err) {
        console.error('Failed to load round history:', err);
        section.style.display = 'none';
    }
}

/**
 * Format total seconds as mm:ss string.
 * @param {number} totalSeconds
 * @returns {string} e.g. "12:45"
 */
function formatMmSs(totalSeconds) {
    if (totalSeconds == null || isNaN(totalSeconds)) return '';
    const sec = Math.round(totalSeconds);
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * Parse a mm:ss (or plain number of minutes) string into total seconds.
 * Accepts: "12:45", "12", "0:30"
 * @param {string} str
 * @returns {number|null} total seconds, or null if invalid
 */
function parseMmSs(str) {
    if (!str || !str.trim()) return null;
    const trimmed = str.trim();

    // mm:ss format
    const match = trimmed.match(/^(\d+):([0-5]?\d)$/);
    if (match) {
        return parseInt(match[1], 10) * 60 + parseInt(match[2], 10);
    }

    // Plain number — treat as minutes
    const num = parseInt(trimmed, 10);
    if (!isNaN(num) && num >= 0 && String(num) === trimmed) {
        return num * 60;
    }

    return null;
}

function renderRoundHistory(rounds) {
    const list = document.getElementById('round-history-list');
    if (!list) return;
    list.innerHTML = '';

    rounds.forEach(round => {
        const breakSec = round.total_break_seconds || 0;
        const breakStr = breakSec > 0 ? `${Math.round(breakSec / 60)}m break` : '';
        const startStr = round.started_at ? new Date(toISOUTC(round.started_at)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
        const endStr = round.ended_at ? new Date(toISOUTC(round.ended_at)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'active';

        const durationMmSs = formatMmSs(round.duration_minutes * 60);
        const studiedMmSs = round.actual_studied_seconds != null ? formatMmSs(round.actual_studied_seconds) : '';

        const item = document.createElement('div');
        item.className = 'round-history-item';
        item.dataset.roundId = round.id;
        item.setAttribute('data-testid', `session-round-${round.id}`);
        item.innerHTML = `
            <span class="round-label">R${round.round_number}</span>
            <div class="round-field">
                <label class="round-field-label">Duration</label>
                <input type="text" class="round-duration-input round-mmss-input" value="${durationMmSs}" data-round-id="${round.id}" data-testid="session-round-${round.id}-duration" placeholder="mm:ss" title="Planned duration (mm:ss)" />
            </div>
            <div class="round-field">
                <label class="round-field-label">Studied</label>
                <input type="text" class="round-actual-studied-input round-mmss-input" value="${studiedMmSs}" data-round-id="${round.id}" data-testid="session-round-${round.id}-studied" placeholder="mm:ss" title="Actual time studied (mm:ss)" />
            </div>
            <span class="round-meta">${startStr}–${endStr}${breakStr ? ' | ' + breakStr : ''}</span>
            <span class="round-actions">
                <button onclick="saveRoundEdits(${round.id})" data-testid="session-round-${round.id}-save" title="Save">Save</button>
                <button onclick="deleteRound(${round.id})" data-testid="session-round-${round.id}-delete" title="Delete">Del</button>
            </span>
        `;
        list.appendChild(item);
    });
}

async function saveRoundEdits(roundId) {
    const durInput = document.querySelector(`.round-duration-input[data-round-id="${roundId}"]`);
    const studiedInput = document.querySelector(`.round-actual-studied-input[data-round-id="${roundId}"]`);
    if (!durInput) return;

    const durSeconds = parseMmSs(durInput.value);
    if (durSeconds == null || durSeconds < 60) {
        alert('Duration must be at least 1:00 (mm:ss).');
        return;
    }
    // Convert to minutes, rounding up so partial minutes are preserved
    const durMinutes = Math.ceil(durSeconds / 60);

    const updates = { duration_minutes: durMinutes };

    if (studiedInput && studiedInput.value.trim() !== '') {
        const studiedSeconds = parseMmSs(studiedInput.value);
        if (studiedSeconds == null || studiedSeconds < 0) {
            alert('Studied time must be a valid mm:ss value.');
            return;
        }
        updates.actual_studied_seconds = studiedSeconds;
    }

    try {
        await api.updateTimerRound(roundId, updates);
        const sessionId = parseInt(document.getElementById('edit-session-id').value, 10);
        if (sessionId) loadRoundHistory(sessionId);
    } catch (err) {
        console.error('Failed to update round:', err);
        alert('Failed to update round.');
    }
}

async function deleteRound(roundId) {
    if (!confirm('Delete this timer round?')) return;
    try {
        await api.deleteTimerRound(roundId);
        // Remove the row from the list
        const item = document.querySelector(`.round-history-item[data-round-id="${roundId}"]`);
        if (item) item.remove();
        // Hide section if no rounds remain
        const list = document.getElementById('round-history-list');
        if (list && list.children.length === 0) {
            document.getElementById('round-history-section').style.display = 'none';
        }
    } catch (err) {
        console.error('Failed to delete round:', err);
        alert('Failed to delete round.');
    }
}

function checkEntryPickerNeeded(sessionId) {
    const session = SessionState.previousSessions.find(s => s.id === sessionId);
    if (!session || session.entries_completed === 0) return;

    const totalQ = parseInt(document.getElementById('edit-session-total-questions').value);
    const totalI = parseInt(document.getElementById('edit-session-total-incorrect').value);
    if (isNaN(totalQ) || isNaN(totalI) || totalQ < 1 || totalI < 1) {
        document.getElementById('inline-entry-picker').style.display = 'none';
        return;
    }

    const effectiveIncorrect = Math.min(totalI, totalQ);

    if (effectiveIncorrect < session.entries_completed) {
        const entriesToRemove = session.entries_completed - effectiveIncorrect;
        if (entryPickerState.sessionId !== sessionId || entryPickerState.entriesToRemove !== entriesToRemove) {
            showEntryPicker(sessionId, entriesToRemove);
        }
    } else {
        document.getElementById('inline-entry-picker').style.display = 'none';
    }
}

async function saveEditedSession() {
    const sessionId = parseInt(document.getElementById('edit-session-id').value);
    if (!sessionId) return;

    const newName = document.getElementById('edit-session-name').value.trim();
    const newDate = document.getElementById('edit-session-date').value;
    const newTotalQuestions = parseInt(document.getElementById('edit-session-total-questions').value);
    const newTotalIncorrect = parseInt(document.getElementById('edit-session-total-incorrect').value);
    const newSourceId = SessionState.editSourceSelect
        ? parseInt(SessionState.editSourceSelect.getValue())
        : null;

    if (isNaN(newTotalIncorrect) || newTotalIncorrect < 1) return;
    if (isNaN(newTotalQuestions) || newTotalQuestions < 1) return;

    const errorEl = document.getElementById('edit-session-error');
    const errorText = document.getElementById('edit-session-error-text');

    // Auto-cap: total_incorrect cannot exceed total_questions
    let effectiveIncorrect = Math.min(newTotalIncorrect, newTotalQuestions);
    if (effectiveIncorrect !== newTotalIncorrect) {
        document.getElementById('edit-session-total-incorrect').value = effectiveIncorrect;
    }

    // Find current session to check entries_completed
    const session = SessionState.previousSessions.find(s => s.id === sessionId);
    if (!session) return;

    // Block save if entries still need removal (picker is visible)
    if (effectiveIncorrect < session.entries_completed) {
        errorText.textContent = 'Please select and confirm entries to remove before saving.';
        errorEl.style.display = 'flex';
        return;
    }

    // Normal save
    errorEl.style.display = 'none';

    try {
        const updates = {};
        if (newName) updates.session_name = newName;
        if (newDate) updates.date_encountered = newDate;
        updates.total_questions = newTotalQuestions;
        updates.total_incorrect = effectiveIncorrect;
        if (newSourceId && !isNaN(newSourceId)) updates.question_source_id = newSourceId;

        // Status transitions
        if (effectiveIncorrect <= session.entries_completed && session.session_status !== 'completed') {
            updates.session_status = 'completed';
        } else if (effectiveIncorrect > session.entries_completed && session.session_status === 'completed') {
            updates.session_status = 'in_progress';
            updates.completed_at = null;
        }

        await api.updateReviewSession(sessionId, updates);
        closeEditSessionModal();
        await loadPreviousSessions();
        Toast.success('Session Updated', 'Session details have been saved.');
    } catch (error) {
        console.error('Error updating session:', error);
        Toast.error('Error', 'Failed to update session: ' + error.message);
    }
}

function closeEditSessionModal() {
    if (SessionState.editSourceSelect) {
        SessionState.editSourceSelect = null;
    }
    const container = document.getElementById('edit-source-select-container');
    if (container) container.innerHTML = '';
    const picker = document.getElementById('inline-entry-picker');
    if (picker) picker.style.display = 'none';
    Modal.close('edit-session-modal');
}

// =========================================================================
// Entry Picker (for reducing incorrect count below entries completed)
// =========================================================================

let entryPickerState = {
    sessionId: null,
    entriesToRemove: 0,
    entries: []
};

async function showEntryPicker(sessionId, entriesToRemove) {
    entryPickerState.sessionId = sessionId;
    entryPickerState.entriesToRemove = entriesToRemove;

    const container = document.getElementById('inline-entry-picker');
    const messageEl = document.getElementById('inline-picker-message');
    const listEl = document.getElementById('inline-picker-list');
    const confirmBtn = document.getElementById('inline-picker-confirm');

    messageEl.textContent = `You need to remove ${entriesToRemove} entr${entriesToRemove === 1 ? 'y' : 'ies'}. Select which to delete:`;
    listEl.innerHTML = '<div class="sources-loading">Loading entries...</div>';
    confirmBtn.disabled = true;
    container.style.display = 'block';
    updateEntryPickerCount();

    try {
        const entries = await api.getSessionEntries(sessionId);
        entryPickerState.entries = entries;

        if (!entries || entries.length === 0) {
            listEl.innerHTML = '<div class="sources-empty"><p>No entries found.</p></div>';
            return;
        }

        listEl.innerHTML = entries.map(entry => {
            const questionId = entry.question_id || 'No ID';
            const subjects = (entry.subjects || []).map(s => s.subject_name || s.name || '').filter(Boolean).join(', ');
            const notes = entry.notes_preview || entry.notes || '';
            return `
                <label class="entry-picker-item" data-entry-id="${entry.id}">
                    <input type="checkbox" value="${entry.id}" data-testid="session-entry-${entry.id}" onchange="updateEntryPickerCount()">
                    <div class="entry-picker-details">
                        <div class="entry-picker-question-id">${escapeHtml(questionId)}</div>
                        ${subjects ? `<div class="entry-picker-subjects">${escapeHtml(subjects)}</div>` : ''}
                        ${notes ? `<div class="entry-picker-notes">${escapeHtml(notes.substring(0, 80))}</div>` : ''}
                    </div>
                </label>
            `;
        }).join('');

        updateEntryPickerCount();
    } catch (error) {
        console.error('Error loading entries:', error);
        listEl.innerHTML = '<div class="sources-empty"><p>Failed to load entries.</p></div>';
    }
}

function updateEntryPickerCount() {
    const checked = document.querySelectorAll('#inline-picker-list input[type="checkbox"]:checked');
    const needed = entryPickerState.entriesToRemove;
    const counterEl = document.getElementById('inline-picker-counter');
    counterEl.textContent = `${checked.length} of ${needed} selected`;

    const confirmBtn = document.getElementById('inline-picker-confirm');
    confirmBtn.disabled = checked.length !== needed;

    // Highlight selected items
    document.querySelectorAll('#inline-picker-list .entry-picker-item').forEach(item => {
        const cb = item.querySelector('input[type="checkbox"]');
        item.classList.toggle('selected', cb && cb.checked);
    });
}

async function confirmEntryDeletion() {
    const checked = document.querySelectorAll('#inline-picker-list input[type="checkbox"]:checked');
    const confirmBtn = document.getElementById('inline-picker-confirm');
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Removing...';

    try {
        for (const cb of checked) {
            await api.deleteQuestionEntry(parseInt(cb.value));
        }

        // Hide inline picker
        document.getElementById('inline-entry-picker').style.display = 'none';

        // Reload sessions to get updated entries_completed
        await loadPreviousSessions();

        // Re-trigger save with the updated session data
        await saveEditedSession();
    } catch (error) {
        console.error('Error deleting entries:', error);
        Toast.error('Error', 'Failed to remove entries: ' + error.message);
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Confirm Removal';
    }
}

// =========================================================================
// Initialization
// =========================================================================

async function initializeSessionSetup() {
    console.log('🚀 Initializing session setup page...');
    
    // Get exam context ID from URL
    const examId = getUrlParam('exam_id');
    if (!examId) {
        Toast.error('Missing Exam', 'No exam selected. Redirecting...');
        setTimeout(() => {
            window.location.href = 'index.html';
        }, 1500);
        return;
    }
    
    SessionState.examContextId = parseInt(examId);
    
    try {
        await api.ready();
        
        // Load exam context
        SessionState.examContext = await api.getExamContext(SessionState.examContextId);
        
        // Update header
        document.getElementById('exam-name').textContent = SessionState.examContext.exam_name;
        document.getElementById('session-exam').value = SessionState.examContext.exam_name;
        
        // Set default date to today
        document.getElementById('session-date').value = getTodayDateString();
        
        // Load data
        await Promise.all([
            loadQuestionSources(),
            loadPreviousSessions()
        ]);

        // Pre-fill session duration from user preferences
        await initializeSessionDuration();

        // Initialize modal handlers
        initializeModalHandlers();

        // Initialize form validation
        initializeFormValidation();
        
        console.log('✅ Session setup page initialized');
        
    } catch (error) {
        console.error('Error initializing session setup:', error);
        Toast.error('Initialization Failed', error.message);
    }
}

function initializeModalHandlers() {
    // Add Source Modal
    Modal.initCloseHandlers('add-source-modal');
    document.getElementById('btn-add-source')?.addEventListener('click', openAddSourceModal);
    document.getElementById('add-source-cancel')?.addEventListener('click', () => Modal.close('add-source-modal'));
    document.getElementById('add-source-save')?.addEventListener('click', saveNewSource);
    
    // Enter key to save
    document.getElementById('new-source-name')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') saveNewSource();
    });
    
    // Manage Sources Modal
    Modal.initCloseHandlers('manage-sources-modal');
    document.getElementById('btn-manage-sources')?.addEventListener('click', () => {
        loadSourcesForModal();
        Modal.open('manage-sources-modal');
    });
    document.getElementById('manage-sources-close')?.addEventListener('click', () => Modal.close('manage-sources-modal'));
    document.getElementById('manage-sources-add')?.addEventListener('click', () => {
        Modal.close('manage-sources-modal');
        openAddSourceModal();
    });
    
    // Edit Source Modal
    Modal.initCloseHandlers('edit-source-modal', () => {
        // Re-open manage modal when edit is closed
        Modal.open('manage-sources-modal');
    });
    document.getElementById('edit-source-cancel')?.addEventListener('click', () => {
        Modal.close('edit-source-modal');
        Modal.open('manage-sources-modal');
    });
    document.getElementById('edit-source-save')?.addEventListener('click', saveEditedSource);
    document.getElementById('edit-source-delete')?.addEventListener('click', confirmDeleteSource);
    
    // Delete Source Modal
    Modal.initCloseHandlers('delete-source-modal', () => {
        Modal.open('edit-source-modal');
    });
    document.getElementById('delete-source-cancel')?.addEventListener('click', () => {
        Modal.close('delete-source-modal');
        Modal.open('edit-source-modal');
    });
    document.getElementById('delete-source-confirm')?.addEventListener('click', deleteSource);
    
    // Delete Session Modal
    Modal.initCloseHandlers('delete-session-modal');
    document.getElementById('delete-session-cancel')?.addEventListener('click', () => {
        Modal.close('delete-session-modal');
        deleteSessionId = null;
    });
    document.getElementById('delete-session-confirm')?.addEventListener('click', deleteSession);

    // Edit Session Modal
    Modal.initCloseHandlers('edit-session-modal', closeEditSessionModal);
    document.getElementById('edit-session-save')?.addEventListener('click', saveEditedSession);
    document.getElementById('edit-session-cancel')?.addEventListener('click', closeEditSessionModal);

    // Inline Entry Picker (inside edit session modal)
    document.getElementById('inline-picker-confirm')?.addEventListener('click', confirmEntryDeletion);
}

function initializeFormValidation() {
    // Date and other inputs
    document.getElementById('session-date')?.addEventListener('change', validateForm);
    document.getElementById('session-total-questions')?.addEventListener('input', validateForm);
    document.getElementById('session-total-incorrect')?.addEventListener('input', validateForm);
    
    // Start session button
    document.getElementById('btn-start-session')?.addEventListener('click', startSession);
}

// =========================================================================
// Export Session Question IDs
// =========================================================================

async function exportSessionIds(sessionId) {
    try {
        const entries = await api.getSessionEntries(sessionId);
        const questionIds = [];
        let skippedCount = 0;

        (entries || []).forEach(entry => {
            if (entry.question_id) {
                questionIds.push(String(entry.question_id));
            } else {
                skippedCount++;
            }
        });

        if (questionIds.length === 0) {
            Toast.warning('No Question IDs', 'None of the entries in this session have a question ID.');
            return;
        }

        await ExportQuestionIdsDialog.show(questionIds, { skippedCount });
    } catch (error) {
        console.error('Error exporting session IDs:', error);
        Toast.error('Export Failed', error.message);
    }
}

// =========================================================================
// Expose Global Functions
// =========================================================================

window.continueSession = continueSession;
window.viewSession = viewSession;
window.confirmDeleteSession = confirmDeleteSession;
window.editSession = editSession;
window.editSource = editSource;
window.exportSessionIds = exportSessionIds;

// =========================================================================
// Run Initialization
// =========================================================================

document.addEventListener('DOMContentLoaded', initializeSessionSetup);
