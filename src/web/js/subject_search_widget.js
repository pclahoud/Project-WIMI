/**
 * SubjectSearchSelect Widget
 * Reusable subject search + select component for embedding in modals.
 *
 * Uses the global FuzzySearch instance to search the full exam subject hierarchy.
 * Displays selected subjects as removable chips.
 *
 * Usage:
 *   const widget = new SubjectSearchSelect(containerEl, {
 *       fuzzySearch: window.fuzzySearch,
 *       excludeIds: [1, 2, 3],
 *       onSubjectAdded: (subject) => { ... },
 *       onSubjectRemoved: (subjectId) => { ... },
 *       placeholder: 'Search for additional subjects...'
 *   });
 *   widget.setSelectedSubjects([{ id: 4, name: 'Cardiology' }]);
 *   widget.getSelectedSubjects();  // returns array of { id, name, path, ... }
 *   widget.destroy();
 */

class SubjectSearchSelect {
    /**
     * @param {HTMLElement} container - DOM element to render into
     * @param {Object} options
     * @param {FuzzySearch} options.fuzzySearch - FuzzySearch instance
     * @param {number[]} [options.excludeIds=[]] - Subject IDs to exclude from results
     * @param {Function} [options.onSubjectAdded] - Callback when a subject is added
     * @param {Function} [options.onSubjectRemoved] - Callback when a subject is removed
     * @param {string} [options.placeholder] - Search input placeholder text
     */
    constructor(container, options = {}) {
        this.container = container;
        this.fuzzySearch = options.fuzzySearch || window.fuzzySearch;
        this.excludeIds = new Set(options.excludeIds || []);
        this.onSubjectAdded = options.onSubjectAdded || null;
        this.onSubjectRemoved = options.onSubjectRemoved || null;
        this.placeholder = options.placeholder || 'Search for additional subjects...';

        // Internal state
        this.selectedSubjects = new Map(); // id -> subject object
        this.searchResults = [];
        this.highlightedIndex = -1;
        this.isOpen = false;
        this._debounceTimer = null;

        // Build DOM
        this._render();
        this._bindEvents();
    }

    // =========================================================================
    // Public API
    // =========================================================================

    /**
     * Set initial selected subjects (e.g., when reopening a modal)
     * @param {Array} subjects - Array of subject objects with at least { id, name }
     */
    setSelectedSubjects(subjects) {
        this.selectedSubjects.clear();
        for (const s of (subjects || [])) {
            this.selectedSubjects.set(s.id, s);
        }
        this._renderChips();
    }

    /**
     * Get currently selected subjects
     * @returns {Array} Array of subject objects
     */
    getSelectedSubjects() {
        return Array.from(this.selectedSubjects.values());
    }

    /**
     * Get selected subject IDs
     * @returns {number[]}
     */
    getSelectedIds() {
        return Array.from(this.selectedSubjects.keys());
    }

    /**
     * Update the exclusion list (e.g., when entry subjects change)
     * @param {number[]} ids - Subject IDs to exclude from search results
     */
    setExcludeIds(ids) {
        this.excludeIds = new Set(ids || []);
    }

    /**
     * Clear all selections and reset the widget
     */
    clear() {
        this.selectedSubjects.clear();
        this.searchInput.value = '';
        this._closeDropdown();
        this._renderChips();
    }

    /**
     * Clean up event listeners and DOM
     */
    destroy() {
        if (this._debounceTimer) clearTimeout(this._debounceTimer);
        if (this._outsideClickHandler) {
            document.removeEventListener('mousedown', this._outsideClickHandler);
        }
        this.container.innerHTML = '';
    }

    // =========================================================================
    // DOM Construction
    // =========================================================================

    _render() {
        this.container.innerHTML = '';
        this.container.classList.add('ssw-container');

        // Search input wrapper
        const searchWrapper = document.createElement('div');
        searchWrapper.className = 'ssw-search-wrapper';

        this.searchInput = document.createElement('input');
        this.searchInput.type = 'text';
        this.searchInput.className = 'ssw-search-input';
        this.searchInput.placeholder = this.placeholder;
        this.searchInput.autocomplete = 'off';
        this.searchInput.dataset.testid = 'tree-subject-search-input';

        const searchIcon = document.createElement('span');
        searchIcon.className = 'ssw-search-icon';
        searchIcon.textContent = '\u{1F50D}';

        searchWrapper.appendChild(searchIcon);
        searchWrapper.appendChild(this.searchInput);

        // Dropdown for search results
        this.dropdown = document.createElement('div');
        this.dropdown.className = 'ssw-dropdown';
        this.dropdown.style.display = 'none';
        this.dropdown.dataset.testid = 'tree-subject-search-dropdown';

        // Chips container for selected subjects
        this.chipsContainer = document.createElement('div');
        this.chipsContainer.className = 'ssw-chips';
        this.chipsContainer.dataset.testid = 'tree-subject-chips';

        this.container.appendChild(searchWrapper);
        this.container.appendChild(this.dropdown);
        this.container.appendChild(this.chipsContainer);
    }

    // =========================================================================
    // Event Binding
    // =========================================================================

    _bindEvents() {
        // Search input - debounced
        this.searchInput.addEventListener('input', () => {
            if (this._debounceTimer) clearTimeout(this._debounceTimer);
            this._debounceTimer = setTimeout(() => this._onSearch(), 150);
        });

        // Keyboard navigation
        this.searchInput.addEventListener('keydown', (e) => this._onKeydown(e));

        // Close dropdown when clicking outside
        this._outsideClickHandler = (e) => {
            if (!this.container.contains(e.target)) {
                this._closeDropdown();
            }
        };
        document.addEventListener('mousedown', this._outsideClickHandler);

        // Focus opens dropdown if there's a query
        this.searchInput.addEventListener('focus', () => {
            if (this.searchInput.value.length >= 2) {
                this._onSearch();
            }
        });
    }

    // =========================================================================
    // Search Logic
    // =========================================================================

    _onSearch() {
        const query = this.searchInput.value.trim();

        if (query.length < 2) {
            this._closeDropdown();
            return;
        }

        if (!this.fuzzySearch) {
            this._closeDropdown();
            return;
        }

        // Get raw results
        const rawResults = this.fuzzySearch.searchSubjects(query, 20);

        // Filter out excluded IDs and already-selected IDs
        this.searchResults = rawResults.filter(r =>
            !this.excludeIds.has(r.id) && !this.selectedSubjects.has(r.id)
        ).slice(0, 10);

        this.highlightedIndex = -1;
        this._renderDropdown(query);
    }

    // =========================================================================
    // Dropdown Rendering
    // =========================================================================

    _renderDropdown(query) {
        if (this.searchResults.length === 0) {
            this.dropdown.innerHTML = `
                <div class="ssw-dropdown-empty">No matching subjects found</div>
            `;
            this.dropdown.style.display = 'block';
            this.isOpen = true;
            return;
        }

        let html = '';
        for (let i = 0; i < this.searchResults.length; i++) {
            const result = this.searchResults[i];
            const highlightedName = this.fuzzySearch.highlightMatches(result.name, query);

            // Build path display (exclude the subject name itself from the path)
            let pathDisplay = '';
            if (result.path) {
                const pathParts = result.path.split(' > ');
                // Remove last part if it matches the subject name
                if (pathParts.length > 1 && pathParts[pathParts.length - 1] === result.name) {
                    pathParts.pop();
                }
                if (pathParts.length > 0) {
                    pathDisplay = pathParts.join(' > ');
                }
            }

            // Alias display
            let aliasDisplay = '';
            if (result.matchedAlias) {
                aliasDisplay = `<span class="ssw-result-alias">aka "${this.fuzzySearch.highlightMatches(result.matchedAlias, query)}"</span>`;
            }

            html += `
                <div class="ssw-dropdown-item ${i === this.highlightedIndex ? 'highlighted' : ''}"
                     data-index="${i}"
                     data-testid="tree-subject-result-${i}">
                    <div class="ssw-result-name">${highlightedName}</div>
                    ${pathDisplay ? `<div class="ssw-result-path">${this._escapeHtml(pathDisplay)}</div>` : ''}
                    ${aliasDisplay}
                </div>
            `;
        }

        this.dropdown.innerHTML = html;
        this.dropdown.style.display = 'block';
        this.isOpen = true;

        // Bind click handlers on items
        this.dropdown.querySelectorAll('.ssw-dropdown-item').forEach(item => {
            item.addEventListener('mousedown', (e) => {
                e.preventDefault(); // Prevent blur
                const index = parseInt(item.dataset.index);
                this._selectResult(index);
            });
            item.addEventListener('mouseenter', () => {
                this.highlightedIndex = parseInt(item.dataset.index);
                this._updateHighlight();
            });
        });
    }

    _closeDropdown() {
        this.dropdown.style.display = 'none';
        this.dropdown.innerHTML = '';
        this.isOpen = false;
        this.highlightedIndex = -1;
        this.searchResults = [];
    }

    _updateHighlight() {
        const items = this.dropdown.querySelectorAll('.ssw-dropdown-item');
        items.forEach((item, i) => {
            item.classList.toggle('highlighted', i === this.highlightedIndex);
        });

        // Scroll highlighted item into view
        if (this.highlightedIndex >= 0 && items[this.highlightedIndex]) {
            items[this.highlightedIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    // =========================================================================
    // Keyboard Navigation
    // =========================================================================

    _onKeydown(e) {
        if (!this.isOpen) return;

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.highlightedIndex = Math.min(
                    this.highlightedIndex + 1,
                    this.searchResults.length - 1
                );
                this._updateHighlight();
                break;

            case 'ArrowUp':
                e.preventDefault();
                this.highlightedIndex = Math.max(this.highlightedIndex - 1, -1);
                this._updateHighlight();
                break;

            case 'Enter':
                e.preventDefault();
                if (this.highlightedIndex >= 0) {
                    this._selectResult(this.highlightedIndex);
                }
                break;

            case 'Escape':
                this._closeDropdown();
                break;
        }
    }

    // =========================================================================
    // Selection Logic
    // =========================================================================

    _selectResult(index) {
        if (index < 0 || index >= this.searchResults.length) return;

        const subject = this.searchResults[index];
        this.selectedSubjects.set(subject.id, subject);

        // Clear search
        this.searchInput.value = '';
        this._closeDropdown();

        // Update chips
        this._renderChips();

        // Callback
        if (this.onSubjectAdded) {
            this.onSubjectAdded(subject);
        }

        // Refocus search input for quick successive adds
        this.searchInput.focus();
    }

    _removeSubject(subjectId) {
        const subject = this.selectedSubjects.get(subjectId);
        this.selectedSubjects.delete(subjectId);
        this._renderChips();

        if (this.onSubjectRemoved) {
            this.onSubjectRemoved(subjectId);
        }
    }

    // =========================================================================
    // Chips Rendering
    // =========================================================================

    _renderChips() {
        if (this.selectedSubjects.size === 0) {
            this.chipsContainer.innerHTML = '';
            this.chipsContainer.style.display = 'none';
            return;
        }

        this.chipsContainer.style.display = 'flex';
        let html = '';

        for (const [id, subject] of this.selectedSubjects) {
            const name = subject.name || `Unknown Subject (ID: ${id})`;
            html += `
                <span class="ssw-chip" data-id="${id}" data-testid="tree-subject-chip-${id}">
                    <span class="ssw-chip-text">${this._escapeHtml(name)}</span>
                    <button type="button" class="ssw-chip-remove" data-id="${id}" data-testid="tree-subject-remove-${id}" title="Remove">&times;</button>
                </span>
            `;
        }

        this.chipsContainer.innerHTML = html;

        // Bind remove handlers
        this.chipsContainer.querySelectorAll('.ssw-chip-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                this._removeSubject(parseInt(btn.dataset.id));
            });
        });
    }

    // =========================================================================
    // Utilities
    // =========================================================================

    _escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Make available globally
window.SubjectSearchSelect = SubjectSearchSelect;
