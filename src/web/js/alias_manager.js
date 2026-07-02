/**
 * WIMI Alias Manager Module
 * Provides a modal component for managing subject aliases (eponyms, acronyms, etc.)
 *
 * Usage:
 *   AliasManager.open(subjectNodeId, examContext, subjectName);
 *   // Modal handles create/edit/delete operations
 *   // Emits 'aliases-updated' event on changes
 */

// =========================================================================
// Alias Manager
// =========================================================================

const AliasManager = {
    // State
    modal: null,
    currentSubjectId: null,
    currentExamContext: null,
    currentSubjectName: null,
    aliases: [],
    isLoading: false,

    // Alias type options
    ALIAS_TYPES: [
        { value: 'eponym', label: 'Eponym', description: 'Named after a person (e.g., "Parkinson\'s")' },
        { value: 'acronym', label: 'Acronym/Abbreviation', description: 'Short form (e.g., "MI", "CHF")' },
        { value: 'alternate_name', label: 'Alternate Name', description: 'Official alternate term' },
        { value: 'colloquial', label: 'Common/Slang', description: 'Informal term (e.g., "heart attack")' }
    ],

    /**
     * Initialize the modal (creates DOM if needed)
     */
    init() {
        if (this.modal) return;

        // Create modal HTML
        const modalHtml = `
            <div class="modal-backdrop" id="alias-manager-modal">
                <div class="modal modal-lg alias-manager">
                    <div class="modal-header">
                        <h3 class="modal-title">
                            <span class="modal-icon">🏷️</span>
                            Manage Aliases
                        </h3>
                        <button class="modal-close" id="alias-modal-close">×</button>
                    </div>

                    <div class="alias-manager-subject">
                        <span class="alias-subject-label">Subject:</span>
                        <span class="alias-subject-name" id="alias-subject-name">Loading...</span>
                    </div>

                    <!-- Add Alias Form -->
                    <div class="alias-add-form">
                        <div class="alias-add-row">
                            <input type="text"
                                   id="alias-new-name"
                                   class="alias-input"
                                   placeholder="Enter alias (e.g., MI, Heart Attack)"
                                   autocomplete="off">
                            <select id="alias-new-type" class="alias-type-select">
                                ${this.ALIAS_TYPES.map(t =>
                                    `<option value="${t.value}">${t.label}</option>`
                                ).join('')}
                            </select>
                            <button class="btn btn-primary btn-sm" id="alias-add-btn">
                                Add
                            </button>
                        </div>
                        <div class="alias-conflict-warning hidden" id="alias-conflict-warning">
                            <span class="warning-icon">⚠️</span>
                            <span class="warning-text" id="alias-conflict-text">
                                This alias already exists for another subject.
                            </span>
                        </div>
                    </div>

                    <!-- Aliases List -->
                    <div class="alias-list-container">
                        <div class="alias-list" id="alias-list">
                            <!-- Aliases rendered here -->
                        </div>
                        <div class="alias-empty hidden" id="alias-empty">
                            <span class="alias-empty-icon">📝</span>
                            <p>No aliases yet. Add some to improve searchability!</p>
                            <p class="alias-empty-hint">
                                Aliases help users find this subject by alternative names like
                                eponyms, acronyms, or common terms.
                            </p>
                        </div>
                        <div class="alias-loading hidden" id="alias-loading">
                            <div class="spinner spinner-sm"></div>
                            <span>Loading aliases...</span>
                        </div>
                    </div>

                    <div class="modal-footer">
                        <button class="btn btn-secondary" id="alias-modal-done">Done</button>
                    </div>
                </div>
            </div>
        `;

        // Append to body
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        this.modal = document.getElementById('alias-manager-modal');

        // Bind events
        this._bindEvents();
    },

    /**
     * Bind event handlers
     */
    _bindEvents() {
        // Close button
        document.getElementById('alias-modal-close').addEventListener('click', () => this.close());
        document.getElementById('alias-modal-done').addEventListener('click', () => this.close());

        // Backdrop click
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });

        // Add alias button
        document.getElementById('alias-add-btn').addEventListener('click', () => this.addAlias());

        // Enter key in input
        document.getElementById('alias-new-name').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.addAlias();
            }
        });

        // Check for conflicts on input
        document.getElementById('alias-new-name').addEventListener('input',
            this._debounce(() => this.checkConflicts(), 300)
        );

        // Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.classList.contains('active')) {
                this.close();
            }
        });
    },

    /**
     * Open the alias manager for a subject
     * @param {number} subjectNodeId - Subject node ID
     * @param {string} examContext - Exam context name
     * @param {string} subjectName - Subject display name
     */
    async open(subjectNodeId, examContext, subjectName) {
        this.init();

        this.currentSubjectId = subjectNodeId;
        this.currentExamContext = examContext;
        this.currentSubjectName = subjectName;

        // Update UI
        document.getElementById('alias-subject-name').textContent = subjectName;
        document.getElementById('alias-new-name').value = '';
        document.getElementById('alias-new-type').value = 'alternate_name';
        this._hideConflictWarning();

        // Show modal
        this.modal.classList.add('active');
        document.body.style.overflow = 'hidden';

        // Load aliases
        await this.loadAliases();

        // Focus input (multiple attempts for QWebEngine compatibility)
        const aliasInput = document.getElementById('alias-new-name');
        setTimeout(() => {
            aliasInput.focus();
            aliasInput.click();
        }, 150);
        setTimeout(() => {
            if (document.activeElement !== aliasInput) {
                aliasInput.focus();
            }
        }, 400);
    },

    /**
     * Close the modal
     */
    close() {
        if (this.modal) {
            this.modal.classList.remove('active');
            document.body.style.overflow = '';
        }
    },

    /**
     * Load aliases for the current subject
     */
    async loadAliases() {
        this._setLoading(true);

        try {
            this.aliases = await api.getAliasesForSubject(this.currentSubjectId);
            this._renderAliases();
        } catch (error) {
            console.error('Error loading aliases:', error);
            this._showError('Failed to load aliases');
        } finally {
            this._setLoading(false);
        }
    },

    /**
     * Add a new alias
     */
    async addAlias() {
        const nameInput = document.getElementById('alias-new-name');
        const typeSelect = document.getElementById('alias-new-type');

        const aliasName = nameInput.value.trim();
        const aliasType = typeSelect.value;

        if (!aliasName) {
            nameInput.focus();
            return;
        }

        // Check for conflicts first
        const conflicts = await this._checkConflictsAsync(aliasName);
        if (conflicts && conflicts.length > 0) {
            // Show warning but allow adding (user can proceed)
            this._showConflictWarning(conflicts);
        }

        try {
            await api.createSubjectAlias({
                subject_node_id: this.currentSubjectId,
                exam_context: this.currentExamContext,
                alias_name: aliasName,
                alias_type: aliasType
            });

            // Clear input
            nameInput.value = '';
            this._hideConflictWarning();

            // Reload and notify
            await this.loadAliases();
            this._emitUpdate();

        } catch (error) {
            console.error('Error creating alias:', error);
            if (error.message && error.message.includes('already exists')) {
                this._showError('This alias already exists for this subject');
            } else {
                this._showError('Failed to create alias');
            }
        }
    },

    /**
     * Delete an alias
     * @param {number} aliasId - Alias ID to delete
     */
    async deleteAlias(aliasId) {
        try {
            await api.deleteSubjectAlias(aliasId);
            await this.loadAliases();
            this._emitUpdate();
        } catch (error) {
            console.error('Error deleting alias:', error);
            this._showError('Failed to delete alias');
        }
    },

    /**
     * Toggle primary status of an alias
     * @param {number} aliasId - Alias ID
     * @param {boolean} isPrimary - New primary status
     */
    async togglePrimary(aliasId, isPrimary) {
        try {
            await api.updateSubjectAlias({
                alias_id: aliasId,
                is_primary: isPrimary
            });
            await this.loadAliases();
            this._emitUpdate();
        } catch (error) {
            console.error('Error updating alias:', error);
            this._showError('Failed to update alias');
        }
    },

    /**
     * Check for conflicting aliases (debounced)
     */
    async checkConflicts() {
        const nameInput = document.getElementById('alias-new-name');
        const aliasName = nameInput.value.trim();

        if (!aliasName || aliasName.length < 2) {
            this._hideConflictWarning();
            return;
        }

        const conflicts = await this._checkConflictsAsync(aliasName);
        if (conflicts && conflicts.length > 0) {
            this._showConflictWarning(conflicts);
        } else {
            this._hideConflictWarning();
        }
    },

    /**
     * Check conflicts via API
     */
    async _checkConflictsAsync(aliasName) {
        try {
            const result = await api.checkAliasConflicts(
                this.currentExamContext,
                aliasName,
                this.currentSubjectId
            );
            return result.conflicts || [];
        } catch (error) {
            console.error('Error checking conflicts:', error);
            return [];
        }
    },

    /**
     * Render the aliases list
     */
    _renderAliases() {
        const listEl = document.getElementById('alias-list');
        const emptyEl = document.getElementById('alias-empty');

        if (!this.aliases || this.aliases.length === 0) {
            listEl.innerHTML = '';
            emptyEl.classList.remove('hidden');
            return;
        }

        emptyEl.classList.add('hidden');

        const html = this.aliases.map(alias => `
            <div class="alias-item" data-id="${alias.id}">
                <div class="alias-item-content">
                    <span class="alias-name">${this._escapeHtml(alias.alias_name)}</span>
                    <span class="alias-type-badge alias-type-${alias.alias_type}">
                        ${this._getTypeLabel(alias.alias_type)}
                    </span>
                    ${alias.is_primary ? '<span class="alias-primary-badge">Primary</span>' : ''}
                </div>
                <div class="alias-item-actions">
                    <button class="btn-icon btn-icon-sm alias-primary-toggle"
                            title="${alias.is_primary ? 'Remove primary' : 'Set as primary'}"
                            onclick="AliasManager.togglePrimary(${alias.id}, ${!alias.is_primary})">
                        ${alias.is_primary ? '★' : '☆'}
                    </button>
                    <button class="btn-icon btn-icon-sm btn-icon-danger alias-delete"
                            title="Delete alias"
                            onclick="AliasManager.deleteAlias(${alias.id})">
                        🗑️
                    </button>
                </div>
            </div>
        `).join('');

        listEl.innerHTML = html;
    },

    /**
     * Show conflict warning
     */
    _showConflictWarning(conflicts) {
        const warningEl = document.getElementById('alias-conflict-warning');
        const textEl = document.getElementById('alias-conflict-text');

        const subjects = conflicts.map(c => c.subject_name).join(', ');
        textEl.textContent = `This alias is used by: ${subjects}. You can still add it.`;

        warningEl.classList.remove('hidden');
    },

    /**
     * Hide conflict warning
     */
    _hideConflictWarning() {
        document.getElementById('alias-conflict-warning').classList.add('hidden');
    },

    /**
     * Show error message (toast)
     */
    _showError(message) {
        if (typeof Toast !== 'undefined') {
            Toast.error('Error', message);
        } else {
            alert(message);
        }
    },

    /**
     * Set loading state
     */
    _setLoading(loading) {
        this.isLoading = loading;
        const loadingEl = document.getElementById('alias-loading');
        const listEl = document.getElementById('alias-list');

        if (loading) {
            loadingEl.classList.remove('hidden');
            listEl.classList.add('hidden');
        } else {
            loadingEl.classList.add('hidden');
            listEl.classList.remove('hidden');
        }
    },

    /**
     * Emit update event for parent components
     */
    _emitUpdate() {
        window.dispatchEvent(new CustomEvent('aliases-updated', {
            detail: {
                subjectId: this.currentSubjectId,
                examContext: this.currentExamContext
            }
        }));
    },

    /**
     * Get type label
     */
    _getTypeLabel(type) {
        const typeObj = this.ALIAS_TYPES.find(t => t.value === type);
        return typeObj ? typeObj.label : type;
    },

    /**
     * Escape HTML
     */
    _escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    /**
     * Debounce helper
     */
    _debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
};

// Make globally available
window.AliasManager = AliasManager;
