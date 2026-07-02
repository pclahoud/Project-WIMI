/**
 * WIMI Entry Browser
 * Phase 5: Entry Review & Browsing
 * 
 * Handles browsing, filtering, and pagination of question entries.
 */

class EntryBrowser {
    constructor() {
        // State
        this.examContextId = null;
        this.examName = '';
        this.entries = [];
        this.totalEntries = 0;
        this.currentPage = 1;
        this.perPage = 20;
        
        // Filter state
        this.filters = {
            searchQuery: '',
            fieldFilters: {},
            subjectIds: [],
            includeChildSubjects: false,
            subjectMode: 'or',
            tagIds: [],
            dateFrom: null,
            dateTo: null,
            sessionId: null,
            sortBy: 'date_desc',
            isDraft: null
        };

        // Search prefix definitions for autocomplete
        this.SEARCH_PREFIXES = [
            { name: 'user_answer:', description: "User's answer" },
            { name: 'correct_answer:', description: 'Correct answer' },
            { name: 'subject:', description: 'Subject name' },
            { name: 'reflection:', description: 'Reflection text' },
            { name: 'explanation:', description: 'Explanation text' },
            { name: 'notes:', description: 'Notes content' },
            { name: 'question_id:', description: 'Question ID' }
        ];
        this.autocompleteHighlightIndex = -1;
        
        // Dropdown data
        this.subjects = [];
        this.tags = [];
        this.sessions = [];
        
        // Debounce timer for search
        this.searchDebounceTimer = null;

        // Subject tree expansion state
        this.expandedSubjectIds = new Set();

        // Selection mode state
        this.selectionMode = false;
        this.selectedEntryIds = new Set();

        // Initialize on DOM ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.init());
        } else {
            this.init();
        }
    }
    
    async init() {
        console.log('📋 Entry Browser initializing...');
        
        // Parse URL parameters
        this.parseUrlParams();
        
        // Wait for API
        await api.ready();

        // Apply user preferences for defaults
        try {
            const prefs = await api.getUserPreferences();
            if (prefs) {
                if (prefs.entry_review_items_per_page) {
                    this.perPage = prefs.entry_review_items_per_page;
                }
                if (prefs.entry_review_default_sort_field) {
                    this.filters.sortBy = prefs.entry_review_default_sort_field;
                }
            }
        } catch (e) {
            console.warn('Could not load user preferences, using defaults:', e);
        }

        // Cache DOM elements
        this.cacheElements();
        
        // Set up event listeners
        this.setupEventListeners();
        
        // Load initial data
        await this.loadInitialData();
        
        console.log('✅ Entry Browser ready');
    }
    
    parseUrlParams() {
        const params = new URLSearchParams(window.location.search);
        this.examContextId = parseInt(params.get('exam')) || null;

        // Pre-fill filters from URL if provided
        // Support multiple subjects (comma-separated) with optional AND mode
        if (params.get('subjects')) {
            this.filters.subjectIds = params.get('subjects').split(',').map(id => parseInt(id)).filter(Boolean);
            this.filters.subjectMode = params.get('subject_mode') || 'or';
        } else if (params.get('subject')) {
            this.filters.subjectIds = [parseInt(params.get('subject'))];
        }
        if (params.get('include_children') === 'true') {
            this.filters.includeChildSubjects = true;
        }
        if (params.get('tag')) {
            this.filters.tagIds = [parseInt(params.get('tag'))];
        }
        if (params.get('session')) {
            this.filters.sessionId = parseInt(params.get('session'));
        }
    }
    
    cacheElements() {
        // Header
        this.elements = {
            backLink: document.getElementById('backLink'),
            examBadge: document.getElementById('examBadge'),
            totalEntries: document.getElementById('totalEntries'),
            draftCount: document.getElementById('draftCount'),
            
            // Search
            searchInput: document.getElementById('searchInput'),
            clearSearch: document.getElementById('clearSearch'),
            
            // Filter buttons
            subjectFilterBtn: document.getElementById('subjectFilterBtn'),
            tagFilterBtn: document.getElementById('tagFilterBtn'),
            dateFilterBtn: document.getElementById('dateFilterBtn'),
            sessionFilterBtn: document.getElementById('sessionFilterBtn'),
            
            // Filter values
            subjectFilterValue: document.getElementById('subjectFilterValue'),
            tagFilterValue: document.getElementById('tagFilterValue'),
            dateFilterValue: document.getElementById('dateFilterValue'),
            sessionFilterValue: document.getElementById('sessionFilterValue'),
            
            // Dropdowns
            subjectDropdown: document.getElementById('subjectDropdown'),
            tagDropdown: document.getElementById('tagDropdown'),
            dateDropdown: document.getElementById('dateDropdown'),
            sessionDropdown: document.getElementById('sessionDropdown'),
            
            // Dropdown content
            subjectList: document.getElementById('subjectList'),
            tagList: document.getElementById('tagList'),
            sessionList: document.getElementById('sessionList'),

            // Dropdown search inputs
            subjectSearch: document.getElementById('subjectSearch'),
            sessionSearch: document.getElementById('sessionSearch'),
            
            // Sort & Draft
            sortSelectContainer: document.getElementById('sortSelectContainer'),
            showDraftsOnly: document.getElementById('showDraftsOnly'),
            
            // Active filters
            activeFilters: document.getElementById('activeFilters'),
            filterChips: document.getElementById('filterChips'),
            clearAllFilters: document.getElementById('clearAllFilters'),
            
            // Main content
            loadingState: document.getElementById('loadingState'),
            emptyState: document.getElementById('emptyState'),
            entryGrid: document.getElementById('entryGrid'),
            
            // Pagination
            paginationArea: document.getElementById('paginationArea'),
            showingStart: document.getElementById('showingStart'),
            showingEnd: document.getElementById('showingEnd'),
            totalCount: document.getElementById('totalCount'),
            loadMoreBtn: document.getElementById('loadMoreBtn'),
            
            // Template
            entryCardTemplate: document.getElementById('entryCardTemplate'),

            // Selection mode
            enterSelectionBtn: document.getElementById('enterSelectionBtn'),
            selectionToolbar: document.getElementById('selectionToolbar'),
            selectAllCheckbox: document.getElementById('selectAllCheckbox'),
            selectionCount: document.getElementById('selectionCount'),
            exportSelectedBtn: document.getElementById('exportSelectedBtn'),
            exportAllVisibleBtn: document.getElementById('exportAllVisibleBtn'),
            cancelSelectionBtn: document.getElementById('cancelSelectionBtn')
        };
    }
    
    setupEventListeners() {
        // Search
        this.elements.searchInput.addEventListener('input', (e) => {
            this.handleSearchInput(e.target.value);
            this.updateAutocomplete(e.target.value);
        });
        this.elements.clearSearch.addEventListener('click', () => {
            this.elements.searchInput.value = '';
            this.handleSearchInput('');
            this.hideAutocomplete();
        });
        this.setupSearchAutocomplete();
        
        // Filter dropdowns
        this.setupDropdown('subject');
        this.setupDropdown('tag');
        this.setupDropdown('date');
        this.setupDropdown('session');

        // Subject dropdown search
        if (this.elements.subjectSearch) {
            this.elements.subjectSearch.addEventListener('input', (e) => {
                this.filterSubjectList(e.target.value);
            });
        }

        // Session dropdown search
        if (this.elements.sessionSearch) {
            this.elements.sessionSearch.addEventListener('input', (e) => {
                this.filterSessionList(e.target.value);
            });
        }

        // Sort - Initialize CustomSelect
        this.sortSelect = new CustomSelect(this.elements.sortSelectContainer, {
            id: 'sortSelect',
            placeholder: 'Sort by...',
            options: [
                { value: 'date_desc', label: 'Date (Newest)' },
                { value: 'date_asc', label: 'Date (Oldest)' },
                { value: 'difficulty_desc', label: 'Difficulty (High→Low)' },
                { value: 'difficulty_asc', label: 'Difficulty (Low→High)' }
            ],
            value: this.filters.sortBy,
            onChange: (value) => {
                this.filters.sortBy = value;
                this.resetAndLoad();
            }
        });
        
        // Draft toggle
        this.elements.showDraftsOnly.addEventListener('change', (e) => {
            this.filters.isDraft = e.target.checked ? true : null;
            this.resetAndLoad();
        });
        
        // Clear all filters
        this.elements.clearAllFilters.addEventListener('click', () => {
            this.clearAllFilters();
        });
        
        // Load more
        this.elements.loadMoreBtn.addEventListener('click', () => {
            this.loadMore();
        });
        
        // Close dropdowns on outside click
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.filter-group')) {
                this.closeAllDropdowns();
            }
        });

        // Selection mode controls
        this.elements.enterSelectionBtn?.addEventListener('click', () => {
            this.enterSelectionMode();
        });
        this.elements.cancelSelectionBtn?.addEventListener('click', () => {
            this.exitSelectionMode();
        });
        this.elements.selectAllCheckbox?.addEventListener('change', (e) => {
            if (e.target.checked) {
                this.selectAllVisible();
            } else {
                this.deselectAll();
            }
        });
        this.elements.exportSelectedBtn?.addEventListener('click', () => {
            this.exportSelectedIds();
        });
        this.elements.exportAllVisibleBtn?.addEventListener('click', () => {
            this.exportAllVisibleIds();
        });
        
        // Subject filter controls
        document.getElementById('includeChildSubjects')?.addEventListener('change', (e) => {
            this.filters.includeChildSubjects = e.target.checked;
        });
        document.getElementById('clearSubjects')?.addEventListener('click', () => {
            this.clearSubjectSelection();
        });
        document.getElementById('applySubjects')?.addEventListener('click', () => {
            this.applySubjectFilter();
        });
        
        // Tag filter controls
        document.getElementById('clearTags')?.addEventListener('click', () => {
            this.clearTagSelection();
        });
        document.getElementById('applyTags')?.addEventListener('click', () => {
            this.applyTagFilter();
        });
        
        // Date filter controls
        document.querySelectorAll('.date-preset').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.handleDatePreset(e.target.dataset.range);
            });
        });
        document.getElementById('applyDate')?.addEventListener('click', () => {
            this.applyDateFilter();
        });
        
        // Session filter controls
        document.getElementById('clearSessions')?.addEventListener('click', () => {
            this.clearSessionSelection();
        });
        document.getElementById('applySessions')?.addEventListener('click', () => {
            this.applySessionFilter();
        });
    }
    
    setupDropdown(name) {
        const btn = this.elements[`${name}FilterBtn`];
        const dropdown = this.elements[`${name}Dropdown`];
        const filterGroup = btn.closest('.filter-group');
        
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = filterGroup.classList.contains('open');
            this.closeAllDropdowns();
            if (!isOpen) {
                filterGroup.classList.add('open');
            }
        });
    }
    
    closeAllDropdowns() {
        document.querySelectorAll('.filter-group.open').forEach(group => {
            group.classList.remove('open');
        });
    }
    
    async loadInitialData() {
        try {
            this.showLoading();
            
            // Load exam context info if we have an exam ID
            if (this.examContextId) {
                const examContext = await api.getExamContext(this.examContextId);
                this.examName = examContext.exam_name;
                this.elements.examBadge.textContent = this.examName;
                this.elements.examBadge.style.display = 'inline-block';
            } else {
                this.elements.examBadge.style.display = 'none';
            }
            
            // Load filter data
            await Promise.all([
                this.loadSubjects(),
                this.loadTags(),
                this.loadSessions(),
                this.loadStatistics()
            ]);
            
            // Load entries
            await this.loadEntries();
            
        } catch (error) {
            console.error('Failed to load initial data:', error);
            this.showError('Failed to load entries. Please try again.');
        }
    }
    
    async loadSubjects() {
        if (!this.examContextId) return;

        try {
            this.subjects = await api.getSubjectsForFilter(this.examContextId);
            // Load tree expansion state from sessionStorage
            this.expandedSubjectIds = this.loadSubjectTreeState();
            this.renderSubjectList();
        } catch (error) {
            console.error('Failed to load subjects:', error);
        }
    }

    // Subject tree state management methods

    /**
     * Get the sessionStorage key for subject tree state based on exam context
     */
    getSubjectTreeStateKey() {
        return `subjectTreeState_${this.examContextId || 'global'}`;
    }

    /**
     * Load subject tree expansion state from sessionStorage
     */
    loadSubjectTreeState() {
        try {
            const stored = sessionStorage.getItem(this.getSubjectTreeStateKey());
            if (stored) {
                return new Set(JSON.parse(stored));
            }
        } catch (error) {
            console.warn('Failed to load subject tree state:', error);
        }
        return new Set();
    }

    /**
     * Save subject tree expansion state to sessionStorage
     */
    saveSubjectTreeState(expandedIds) {
        try {
            sessionStorage.setItem(this.getSubjectTreeStateKey(), JSON.stringify([...expandedIds]));
        } catch (error) {
            console.warn('Failed to save subject tree state:', error);
        }
    }

    /**
     * Toggle expansion state for a subject node
     */
    toggleSubjectExpanded(subjectId) {
        if (this.expandedSubjectIds.has(subjectId)) {
            this.expandedSubjectIds.delete(subjectId);
        } else {
            this.expandedSubjectIds.add(subjectId);
        }

        // Update pre-search state too, so manual toggles during search persist
        if (this._preSearchExpandedIds) {
            if (this._preSearchExpandedIds.has(subjectId)) {
                this._preSearchExpandedIds.delete(subjectId);
            } else {
                this._preSearchExpandedIds.add(subjectId);
            }
        }

        this.saveSubjectTreeState(this.expandedSubjectIds);
        this.renderSubjectList();

        // Re-apply active search filter after re-render
        const searchTerm = this.elements.subjectSearch?.value;
        if (searchTerm) {
            this.filterSubjectList(searchTerm);
        }
    }
    
    async loadTags() {
        if (!this.examContextId) return;
        
        try {
            this.tags = await api.getTagsForFilter(this.examContextId);
            this.renderTagList();
        } catch (error) {
            console.error('Failed to load tags:', error);
        }
    }
    
    async loadSessions() {
        if (!this.examContextId) return;
        
        try {
            this.sessions = await api.getSessionsForFilter(this.examContextId);
            this.renderSessionList();
        } catch (error) {
            console.error('Failed to load sessions:', error);
        }
    }
    
    async loadStatistics() {
        try {
            const stats = await api.getEntryStatistics(this.examContextId || -1);
            this.elements.totalEntries.textContent = stats.total || 0;
            this.elements.draftCount.textContent = stats.drafts || 0;
        } catch (error) {
            console.error('Failed to load statistics:', error);
        }
    }
    
    async loadEntries(append = false) {
        try {
            if (!append) {
                this.showLoading();
            }
            
            const params = {
                page: this.currentPage,
                per_page: this.perPage,
                sort_by: this.filters.sortBy
            };
            
            // Add filters
            if (this.examContextId) {
                params.exam_context_id = this.examContextId;
            }
            if (this.filters.searchQuery) {
                params.search_query = this.filters.searchQuery;
            }
            if (this.filters.fieldFilters && Object.keys(this.filters.fieldFilters).length > 0) {
                params.field_filters = this.filters.fieldFilters;
            }
            if (this.filters.subjectIds.length > 0) {
                params.subject_ids = this.filters.subjectIds;
                params.include_child_subjects = this.filters.includeChildSubjects;
                if (this.filters.subjectMode === 'and') {
                    params.subject_mode = 'and';
                }
            }
            if (this.filters.tagIds.length > 0) {
                params.tag_ids = this.filters.tagIds;
            }
            if (this.filters.dateFrom) {
                params.date_from = this.filters.dateFrom;
            }
            if (this.filters.dateTo) {
                params.date_to = this.filters.dateTo;
            }
            if (this.filters.sessionId) {
                params.session_id = this.filters.sessionId;
            }
            if (this.filters.isDraft !== null) {
                params.is_draft = this.filters.isDraft;
            }
            
            const result = await api.getEntriesPaginated(params);
            
            if (append) {
                this.entries = [...this.entries, ...result.entries];
            } else {
                this.entries = result.entries;
            }
            this.totalEntries = result.total;
            
            this.renderEntries(append);
            this.updatePagination();
            this.updateActiveFilters();
            
        } catch (error) {
            console.error('Failed to load entries:', error);
            this.showError('Failed to load entries. Please try again.');
        }
    }
    
    renderEntries(append = false) {
        this.hideLoading();
        
        if (this.entries.length === 0) {
            this.showEmpty();
            return;
        }
        
        this.elements.emptyState.style.display = 'none';
        this.elements.entryGrid.style.display = 'grid';
        
        if (!append) {
            this.elements.entryGrid.innerHTML = '';
        }
        
        const startIdx = append ? this.entries.length - this.perPage : 0;
        const entriesToRender = append ? this.entries.slice(startIdx) : this.entries;
        
        entriesToRender.forEach(entry => {
            const card = this.createEntryCard(entry);
            this.elements.entryGrid.appendChild(card);
        });
    }
    
    createEntryCard(entry) {
        const template = this.elements.entryCardTemplate.content.cloneNode(true);
        const card = template.querySelector('.entry-card');

        card.dataset.entryId = entry.id;
        // Per-entry testid (entry card is the foundation of navigation tests)
        card.setAttribute('data-testid', `browser-row-${entry.id}`);

        // Selection mode: show checkbox, toggle selection on click
        if (this.selectionMode) {
            card.classList.add('selection-mode');
            const checkboxContainer = card.querySelector('.card-select-checkbox');
            const checkbox = card.querySelector('.entry-checkbox');
            if (checkboxContainer) checkboxContainer.style.display = '';
            if (checkbox) {
                checkbox.setAttribute('data-testid', `browser-row-${entry.id}-checkbox`);
                checkbox.checked = this.selectedEntryIds.has(entry.id);
                checkbox.addEventListener('click', (e) => e.stopPropagation());
                checkbox.addEventListener('change', () => {
                    this.toggleEntrySelection(entry.id);
                });
            }
            if (this.selectedEntryIds.has(entry.id)) {
                card.classList.add('selected');
            }
        }

        card.addEventListener('click', () => {
            if (this.selectionMode) {
                this.toggleEntrySelection(entry.id);
                return;
            }
            this.navigateToEntry(entry.id);
        });
        
        // Difficulty badge
        const difficultyBadge = card.querySelector('.difficulty-badge');
        if (entry.perceived_difficulty) {
            difficultyBadge.dataset.difficulty = entry.perceived_difficulty;
            const difficultyLabels = { 1: 'Easy', 2: 'Medium', 3: 'Hard' };
            difficultyBadge.textContent = difficultyLabels[entry.perceived_difficulty] || '';
        } else {
            difficultyBadge.style.display = 'none';
        }
        
        // Date
        const dateEl = card.querySelector('.entry-date');
        if (entry.session_date) {
            dateEl.textContent = this.formatDate(entry.session_date);
        } else {
            dateEl.textContent = this.formatDate(entry.created_at);
        }
        
        // Subjects container - display all associated subjects
        const subjectsContainer = card.querySelector('.subjects-container');
        this.renderSubjectsOnCard(subjectsContainer, entry);
        subjectsContainer.setAttribute('data-testid', `browser-row-${entry.id}-subjects`);
        
        // Answers
        card.querySelector('.your-answer').textContent = entry.user_answer || '—';
        card.querySelector('.correct-answer').textContent = entry.correct_answer || '—';
        
        // Reflection preview
        const reflectionPreview = card.querySelector('.reflection-preview');
        if (entry.reflection) {
            reflectionPreview.textContent = entry.reflection;
        } else {
            reflectionPreview.textContent = 'No reflection added';
            reflectionPreview.style.fontStyle = 'italic';
        }
        
        // Tags
        const tagsRow = card.querySelector('.tags-row');
        if (entry.tags && entry.tags.length > 0) {
            entry.tags.slice(0, 3).forEach(tag => {
                const chip = document.createElement('span');
                chip.className = 'tag-chip';
                chip.textContent = tag.name;
                chip.style.backgroundColor = this.lightenColor(tag.color, 0.8);
                chip.style.color = tag.color;
                chip.setAttribute('data-testid', `browser-row-${entry.id}-tag-${tag.id}`);
                tagsRow.appendChild(chip);
            });
            if (entry.tags.length > 3) {
                const more = document.createElement('span');
                more.className = 'tag-chip';
                more.textContent = `+${entry.tags.length - 3}`;
                more.style.backgroundColor = 'var(--bg-tertiary)';
                more.style.color = 'var(--text-muted)';
                more.setAttribute('data-testid', `browser-row-${entry.id}-tag-more`);
                tagsRow.appendChild(more);
            }
        }
        
        // Media count
        const mediaCount = card.querySelector('.media-count');
        if (entry.media && entry.media.length > 0) {
            mediaCount.style.display = 'inline';
            mediaCount.querySelector('.count').textContent = entry.media.length;
        }
        
        // Draft badge
        const draftBadge = card.querySelector('.draft-badge');
        if (entry.is_draft) {
            draftBadge.style.display = 'inline';
        }
        
        return card;
    }

    /**
     * Render all subjects (primary and secondary) on an entry card.
     * Shows up to MAX_VISIBLE subjects with a "+N more" chip for overflow.
     */
    renderSubjectsOnCard(container, entry) {
        const MAX_VISIBLE = 3;
        const allSubjects = [];

        // Collect primary subjects
        if (entry.primary_subjects && entry.primary_subjects.length > 0) {
            entry.primary_subjects.forEach(s => {
                allSubjects.push({ ...s, isPrimary: true });
            });
        }

        // Collect secondary subjects
        if (entry.secondary_subjects && entry.secondary_subjects.length > 0) {
            entry.secondary_subjects.forEach(s => {
                allSubjects.push({ ...s, isPrimary: false });
            });
        }

        // Handle empty state
        if (allSubjects.length === 0) {
            const emptyText = document.createElement('span');
            emptyText.className = 'no-subjects-text';
            emptyText.textContent = 'No subject assigned';
            container.appendChild(emptyText);
            return;
        }

        // Group subjects by dimension for better display
        const byDimension = new Map();
        const noDimension = [];

        allSubjects.forEach(subject => {
            if (subject.dimension_name) {
                if (!byDimension.has(subject.dimension_name)) {
                    byDimension.set(subject.dimension_name, []);
                }
                byDimension.get(subject.dimension_name).push(subject);
            } else {
                noDimension.push(subject);
            }
        });

        // Build display list: dimension groups first, then ungrouped
        const displayItems = [];

        // Add dimension-grouped subjects
        byDimension.forEach((subjects, dimensionName) => {
            subjects.forEach(subject => {
                displayItems.push({
                    subject,
                    dimensionName,
                    label: subject.name,
                    tooltip: subject.path
                });
            });
        });

        // Add ungrouped subjects
        noDimension.forEach(subject => {
            displayItems.push({
                subject,
                dimensionName: null,
                label: subject.name,
                tooltip: subject.path
            });
        });

        // Render visible items
        const visibleItems = displayItems.slice(0, MAX_VISIBLE);
        const hiddenCount = displayItems.length - MAX_VISIBLE;

        visibleItems.forEach(item => {
            const chip = document.createElement('span');
            chip.className = 'subject-chip';
            if (item.subject.isPrimary) {
                chip.classList.add('primary');
            }
            if (item.dimensionName) {
                chip.classList.add('has-dimension');
            }

            // Add dimension label if present
            if (item.dimensionName) {
                const dimLabel = document.createElement('span');
                dimLabel.className = 'dimension-label';
                dimLabel.textContent = item.dimensionName + ':';
                chip.appendChild(dimLabel);
            }

            const nameSpan = document.createElement('span');
            nameSpan.className = 'subject-name';
            nameSpan.textContent = item.label;
            chip.appendChild(nameSpan);

            // Add tooltip for full path
            if (item.tooltip && item.tooltip !== item.label) {
                chip.title = item.tooltip;
            }

            // Per-card subject testid
            if (entry && entry.id != null && item.subject && item.subject.id != null) {
                chip.setAttribute('data-testid', `browser-row-${entry.id}-subject-${item.subject.id}`);
            }

            container.appendChild(chip);
        });

        // Add "+N more" chip if there are hidden items
        if (hiddenCount > 0) {
            const moreChip = document.createElement('span');
            moreChip.className = 'subject-chip more-chip';
            moreChip.textContent = `+${hiddenCount} more`;

            // Build tooltip showing all hidden subjects
            const hiddenItems = displayItems.slice(MAX_VISIBLE);
            const hiddenNames = hiddenItems.map(item => {
                if (item.dimensionName) {
                    return `${item.dimensionName}: ${item.label}`;
                }
                return item.label;
            });
            moreChip.title = hiddenNames.join('\n');

            if (entry && entry.id != null) {
                moreChip.setAttribute('data-testid', `browser-row-${entry.id}-subject-more`);
            }

            container.appendChild(moreChip);
        }
    }

    navigateToEntry(entryId) {
        // Find the index of this entry in the current list
        const currentIndex = this.entries.findIndex(e => e.id === entryId);

        // Store navigation context in sessionStorage for prev/next navigation
        const navContext = {
            ids: this.entries.map(e => e.id),
            index: currentIndex >= 0 ? currentIndex : 0,
            total: this.totalEntries,
            examContextId: this.examContextId,
            // Store current filter state for potential "back to filtered results"
            filters: { ...this.filters }
        };
        sessionStorage.setItem('entryNavContext', JSON.stringify(navContext));

        window.location.href = `entry_detail.html?id=${entryId}`;
    }

    // Filter rendering methods
    renderSubjectList() {
        const container = this.elements.subjectList;
        container.innerHTML = '';

        const renderNodes = (nodes, level = 0) => {
            nodes.forEach(node => {
                const hasChildren = node.children && node.children.length > 0;
                const isExpanded = this.expandedSubjectIds.has(node.id);

                // Create wrapper for the tree item
                const itemWrapper = document.createElement('div');
                itemWrapper.className = 'subject-tree-node';
                itemWrapper.dataset.subjectId = node.id;
                itemWrapper.setAttribute('data-testid', `browser-subject-item-${node.id}`);

                // Create the main item row
                const item = document.createElement('label');
                item.className = 'subject-tree-item';
                item.style.paddingLeft = `${8 + level * 20}px`;

                // Add toggle button or spacer
                if (hasChildren) {
                    const toggle = document.createElement('span');
                    toggle.className = 'tree-toggle';
                    toggle.textContent = isExpanded ? '\u25BC' : '\u25B6'; // Down or right chevron
                    toggle.title = isExpanded ? 'Collapse' : 'Expand';
                    toggle.setAttribute('data-testid', `browser-subject-toggle-${node.id}`);
                    toggle.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        this.toggleSubjectExpanded(node.id);
                    });
                    item.appendChild(toggle);
                } else {
                    const spacer = document.createElement('span');
                    spacer.className = 'tree-toggle-spacer';
                    item.appendChild(spacer);
                }

                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.value = node.id;
                checkbox.checked = this.filters.subjectIds.includes(node.id);
                checkbox.setAttribute('data-testid', `browser-subject-checkbox-${node.id}`);

                const name = document.createElement('span');
                name.className = 'subject-name';
                name.textContent = node.name;

                // Add child count indicator for parent nodes
                if (hasChildren) {
                    const childCount = document.createElement('span');
                    childCount.className = 'subject-child-count';
                    childCount.textContent = `(${node.children.length})`;
                    name.appendChild(childCount);
                }

                item.appendChild(checkbox);
                item.appendChild(name);
                itemWrapper.appendChild(item);
                container.appendChild(itemWrapper);

                // Render children if expanded
                if (hasChildren && isExpanded) {
                    const childrenContainer = document.createElement('div');
                    childrenContainer.className = 'subject-tree-children';
                    container.appendChild(childrenContainer);

                    // Temporarily set container to childrenContainer for recursive rendering
                    const originalContainer = container;
                    this.elements.subjectList = childrenContainer;
                    renderNodes(node.children, level + 1);
                    this.elements.subjectList = originalContainer;
                }
            });
        };

        renderNodes(this.subjects);
    }

    /**
     * Filter subject list based on search term
     * Shows matching subjects and their ancestors (for hierarchy context)
     * Auto-expands ancestor nodes so matching children inside collapsed parents are visible
     * Case-insensitive partial matching
     */
    filterSubjectList(searchTerm) {
        const lowerSearch = searchTerm.toLowerCase().trim();

        if (!lowerSearch) {
            // Search cleared: restore original expansion state and re-render
            if (this._preSearchExpandedIds) {
                this.expandedSubjectIds = new Set(this._preSearchExpandedIds);
                this._preSearchExpandedIds = null;
                this.renderSubjectList();
            } else {
                // No saved state - just show all items
                const container = this.elements.subjectList;
                container.querySelectorAll('.subject-tree-node').forEach(node => {
                    node.style.display = '';
                });
                container.querySelectorAll('.subject-tree-children').forEach(child => {
                    child.style.display = '';
                });
            }
            return;
        }

        // Build a set of node IDs that should be visible
        // (either matching or ancestors of matching nodes)
        const visibleIds = new Set();
        const ancestorIdsToExpand = new Set();

        // Recursive function to find matches and mark ancestors
        const findMatchesAndAncestors = (nodes, ancestorPath = []) => {
            nodes.forEach(node => {
                const currentPath = [...ancestorPath, node.id];
                const nameMatches = node.name.toLowerCase().includes(lowerSearch)
                    || (node.aliasesString || '').toLowerCase().includes(lowerSearch);

                if (nameMatches) {
                    // Add this node and all its ancestors to visible set
                    currentPath.forEach(id => visibleIds.add(id));
                    // Mark ancestors for expansion (not the match itself)
                    ancestorPath.forEach(id => ancestorIdsToExpand.add(id));
                }

                if (node.children && node.children.length > 0) {
                    findMatchesAndAncestors(node.children, currentPath);
                }
            });
        };

        findMatchesAndAncestors(this.subjects);

        // Save pre-search expansion state (only once per search session)
        if (!this._preSearchExpandedIds) {
            this._preSearchExpandedIds = new Set(this.expandedSubjectIds);
        }

        // Auto-expand ancestor nodes of matches so their children are rendered
        let needsRerender = false;
        ancestorIdsToExpand.forEach(id => {
            if (!this.expandedSubjectIds.has(id)) {
                this.expandedSubjectIds.add(id);
                needsRerender = true;
            }
        });

        if (needsRerender) {
            this.renderSubjectList();
        }

        // Apply visibility to DOM items
        const container = this.elements.subjectList;
        container.querySelectorAll('.subject-tree-node').forEach(node => {
            const nodeId = parseInt(node.dataset.subjectId);
            node.style.display = visibleIds.has(nodeId) ? '' : 'none';
        });

        // Show child containers only if they have visible children
        container.querySelectorAll('.subject-tree-children').forEach(child => {
            const hasVisibleContent = Array.from(child.querySelectorAll('.subject-tree-node')).some(n => {
                const id = parseInt(n.dataset.subjectId);
                return visibleIds.has(id);
            });
            child.style.display = hasVisibleContent ? '' : 'none';
        });
    }

    /**
     * Filter session list based on search term
     * Case-insensitive partial matching on session name
     */
    filterSessionList(searchTerm) {
        const container = this.elements.sessionList;
        const items = container.querySelectorAll('.session-item');
        const lowerSearch = searchTerm.toLowerCase().trim();

        items.forEach(item => {
            if (!lowerSearch) {
                item.style.display = '';
                return;
            }

            const sessionName = item.querySelector('.session-name');
            const name = sessionName ? sessionName.textContent.toLowerCase() : '';
            item.style.display = name.includes(lowerSearch) ? '' : 'none';
        });
    }

    renderTagList() {
        const container = this.elements.tagList;
        container.innerHTML = '';

        this.tags.forEach(group => {
            if (!group.is_group) return;

            const groupDiv = document.createElement('div');
            groupDiv.className = 'tag-group';
            if (group.id != null) {
                groupDiv.setAttribute('data-testid', `browser-tag-group-${group.id}`);
            }

            const header = document.createElement('div');
            header.className = 'tag-group-header';

            const colorDot = document.createElement('span');
            colorDot.className = 'tag-group-color';
            colorDot.style.backgroundColor = group.color;

            const name = document.createElement('span');
            name.textContent = group.name;

            header.appendChild(colorDot);
            header.appendChild(name);
            groupDiv.appendChild(header);

            if (group.children) {
                group.children.forEach(tag => {
                    const item = document.createElement('label');
                    item.className = 'tag-item';
                    item.setAttribute('data-testid', `browser-tag-item-${tag.id}`);

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.value = tag.id;
                    checkbox.checked = this.filters.tagIds.includes(tag.id);
                    checkbox.setAttribute('data-testid', `browser-tag-checkbox-${tag.id}`);

                    const dot = document.createElement('span');
                    dot.className = 'tag-color-dot';
                    dot.style.backgroundColor = tag.color;

                    const tagName = document.createElement('span');
                    tagName.className = 'tag-name';
                    tagName.textContent = tag.name;

                    item.appendChild(checkbox);
                    item.appendChild(dot);
                    item.appendChild(tagName);
                    groupDiv.appendChild(item);
                });
            }

            container.appendChild(groupDiv);
        });
    }
    
    renderSessionList() {
        const container = this.elements.sessionList;
        container.innerHTML = '';

        this.sessions.forEach(session => {
            const item = document.createElement('label');
            item.className = 'session-item';
            item.setAttribute('data-testid', `browser-session-item-${session.id}`);

            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = 'session';
            radio.value = session.id;
            radio.checked = this.filters.sessionId === session.id;
            radio.setAttribute('data-testid', `browser-session-radio-${session.id}`);
            
            const info = document.createElement('div');
            info.className = 'session-info';
            
            const name = document.createElement('div');
            name.className = 'session-name';
            name.textContent = session.name || `Session ${session.id}`;
            
            const meta = document.createElement('div');
            meta.className = 'session-meta';
            meta.textContent = `${this.formatDate(session.date)} • ${session.entries_completed}/${session.total_incorrect} entries`;
            
            info.appendChild(name);
            info.appendChild(meta);
            
            item.appendChild(radio);
            item.appendChild(info);
            container.appendChild(item);
        });
    }
    
    // Filter application methods
    handleSearchInput(value) {
        clearTimeout(this.searchDebounceTimer);
        this.searchDebounceTimer = setTimeout(() => {
            const parsed = this.parseSearchQuery(value);
            this.filters.searchQuery = parsed.plainText;
            this.filters.fieldFilters = parsed.fieldFilters;
            this.resetAndLoad();
        }, 300);
    }

    /**
     * Parse search input into plain text and field-specific filters.
     * Syntax: field:"multi word" or field:single_word
     * Supported fields: user_answer, correct_answer, subject, reflection, explanation, notes, question_id
     */
    parseSearchQuery(rawInput) {
        const fieldFilters = {};
        const regex = /\b(user_answer|correct_answer|subject|reflection|explanation|notes|question_id):(?:"([^"]*)"|([\S]+))/g;
        let match;
        let remaining = rawInput;

        while ((match = regex.exec(rawInput)) !== null) {
            const field = match[1];
            const value = match[2] !== undefined ? match[2] : match[3];
            if (value) {
                fieldFilters[field] = value;
            }
            remaining = remaining.replace(match[0], '');
        }

        const plainText = remaining.replace(/\s+/g, ' ').trim();
        return { plainText, fieldFilters };
    }
    
    handleDatePreset(range) {
        document.querySelectorAll('.date-preset').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.range === range);
        });
        
        const customRange = document.getElementById('customDateRange');
        
        if (range === 'custom') {
            customRange.style.display = 'block';
            return;
        }
        
        customRange.style.display = 'none';
        
        const today = new Date();
        let dateFrom = null;
        let dateTo = null;
        
        switch (range) {
            case 'today':
                dateFrom = this.formatDateISO(today);
                dateTo = this.formatDateISO(today);
                break;
            case '7days':
                const sevenDaysAgo = new Date();
                sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
                dateFrom = this.formatDateISO(sevenDaysAgo);
                dateTo = this.formatDateISO(new Date());
                break;
            case '30days':
                const thirtyDaysAgo = new Date();
                thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
                dateFrom = this.formatDateISO(thirtyDaysAgo);
                dateTo = this.formatDateISO(new Date());
                break;
            case 'month':
                dateFrom = this.formatDateISO(new Date(today.getFullYear(), today.getMonth(), 1));
                dateTo = this.formatDateISO(new Date());
                break;
            case 'all':
            default:
                break;
        }
        
        this.filters.dateFrom = dateFrom;
        this.filters.dateTo = dateTo;
    }
    
    applySubjectFilter() {
        const checkboxes = this.elements.subjectList.querySelectorAll('input[type="checkbox"]:checked');
        this.filters.subjectIds = Array.from(checkboxes).map(cb => parseInt(cb.value));
        
        const count = this.filters.subjectIds.length;
        this.elements.subjectFilterValue.textContent = count === 0 ? 'All' : `${count} selected`;
        
        this.closeAllDropdowns();
        this.resetAndLoad();
    }
    
    clearSubjectSelection() {
        this.elements.subjectList.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.checked = false;
        });
    }
    
    applyTagFilter() {
        const checkboxes = this.elements.tagList.querySelectorAll('input[type="checkbox"]:checked');
        this.filters.tagIds = Array.from(checkboxes).map(cb => parseInt(cb.value));
        
        const count = this.filters.tagIds.length;
        this.elements.tagFilterValue.textContent = count === 0 ? 'All' : `${count} selected`;
        
        this.closeAllDropdowns();
        this.resetAndLoad();
    }
    
    clearTagSelection() {
        this.elements.tagList.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.checked = false;
        });
    }
    
    applyDateFilter() {
        const customFrom = document.getElementById('dateFrom').value;
        const customTo = document.getElementById('dateTo').value;
        
        if (customFrom) this.filters.dateFrom = customFrom;
        if (customTo) this.filters.dateTo = customTo;
        
        if (this.filters.dateFrom || this.filters.dateTo) {
            this.elements.dateFilterValue.textContent = 'Custom';
        } else {
            this.elements.dateFilterValue.textContent = 'All Time';
        }
        
        this.closeAllDropdowns();
        this.resetAndLoad();
    }
    
    applySessionFilter() {
        const selected = this.elements.sessionList.querySelector('input[type="radio"]:checked');
        this.filters.sessionId = selected ? parseInt(selected.value) : null;
        
        if (this.filters.sessionId) {
            const session = this.sessions.find(s => s.id === this.filters.sessionId);
            this.elements.sessionFilterValue.textContent = session?.name || 'Selected';
        } else {
            this.elements.sessionFilterValue.textContent = 'All';
        }
        
        this.closeAllDropdowns();
        this.resetAndLoad();
    }
    
    clearSessionSelection() {
        this.elements.sessionList.querySelectorAll('input[type="radio"]').forEach(rb => {
            rb.checked = false;
        });
    }
    
    clearAllFilters() {
        this.filters = {
            searchQuery: '',
            fieldFilters: {},
            subjectIds: [],
            includeChildSubjects: false,
            tagIds: [],
            dateFrom: null,
            dateTo: null,
            sessionId: null,
            sortBy: 'date_desc',
            isDraft: null
        };
        
        // Reset UI
        this.elements.searchInput.value = '';
        if (this.sortSelect) {
            this.sortSelect.setValue('date_desc');
        }
        this.elements.showDraftsOnly.checked = false;
        
        this.elements.subjectFilterValue.textContent = 'All';
        this.elements.tagFilterValue.textContent = 'All';
        this.elements.dateFilterValue.textContent = 'All Time';
        this.elements.sessionFilterValue.textContent = 'All';
        
        this.clearSubjectSelection();
        this.clearTagSelection();
        this.clearSessionSelection();
        
        document.querySelectorAll('.date-preset').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.range === 'all');
        });
        
        this.resetAndLoad();
    }
    
    updateActiveFilters() {
        const chips = [];

        if (this.filters.searchQuery) {
            chips.push({ label: `Search: "${this.filters.searchQuery}"`, type: 'search' });
        }
        if (this.filters.fieldFilters) {
            for (const [field, value] of Object.entries(this.filters.fieldFilters)) {
                chips.push({ label: `${field}: "${value}"`, type: `field_${field}` });
            }
        }
        if (this.filters.subjectIds.length > 0) {
            const subjectLabel = this.filters.subjectMode === 'and'
                ? `${this.filters.subjectIds.length} subjects (all match)`
                : `${this.filters.subjectIds.length} subject(s)`;
            chips.push({ label: subjectLabel, type: 'subject' });
        }
        if (this.filters.tagIds.length > 0) {
            chips.push({ label: `${this.filters.tagIds.length} tag(s)`, type: 'tag' });
        }
        if (this.filters.dateFrom || this.filters.dateTo) {
            chips.push({ label: 'Date range', type: 'date' });
        }
        if (this.filters.sessionId) {
            chips.push({ label: 'Session', type: 'session' });
        }
        if (this.filters.isDraft) {
            chips.push({ label: 'Drafts only', type: 'draft' });
        }
        
        this.elements.activeFilters.style.display = chips.length > 0 ? 'flex' : 'none';

        this.elements.filterChips.innerHTML = chips.map(chip => `
            <span class="filter-chip" data-testid="browser-filter-chip-${chip.type}">
                ${chip.label}
                <span class="remove-chip" data-type="${chip.type}" data-testid="browser-filter-chip-${chip.type}-remove">×</span>
            </span>
        `).join('');
        
        // Add remove handlers
        this.elements.filterChips.querySelectorAll('.remove-chip').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.removeFilter(btn.dataset.type);
            });
        });
    }
    
    removeFilter(type) {
        if (type.startsWith('field_')) {
            const fieldName = type.substring(6);
            delete this.filters.fieldFilters[fieldName];
            this.rebuildSearchInput();
            this.resetAndLoad();
            return;
        }
        switch (type) {
            case 'search':
                this.filters.searchQuery = '';
                this.filters.fieldFilters = {};
                this.elements.searchInput.value = '';
                break;
            case 'subject':
                this.filters.subjectIds = [];
                this.elements.subjectFilterValue.textContent = 'All';
                this.clearSubjectSelection();
                break;
            case 'tag':
                this.filters.tagIds = [];
                this.elements.tagFilterValue.textContent = 'All';
                this.clearTagSelection();
                break;
            case 'date':
                this.filters.dateFrom = null;
                this.filters.dateTo = null;
                this.elements.dateFilterValue.textContent = 'All Time';
                break;
            case 'session':
                this.filters.sessionId = null;
                this.elements.sessionFilterValue.textContent = 'All';
                this.clearSessionSelection();
                break;
            case 'draft':
                this.filters.isDraft = null;
                this.elements.showDraftsOnly.checked = false;
                break;
        }
        this.resetAndLoad();
    }

    /**
     * Rebuild the search input text from current plainText + fieldFilters.
     */
    rebuildSearchInput() {
        let parts = [];
        if (this.filters.searchQuery) {
            parts.push(this.filters.searchQuery);
        }
        for (const [field, value] of Object.entries(this.filters.fieldFilters)) {
            if (value.includes(' ')) {
                parts.push(`${field}:"${value}"`);
            } else {
                parts.push(`${field}:${value}`);
            }
        }
        this.elements.searchInput.value = parts.join(' ');
    }
    
    // Pagination
    updatePagination() {
        const hasMore = this.entries.length < this.totalEntries;
        
        this.elements.paginationArea.style.display = this.entries.length > 0 ? 'flex' : 'none';
        this.elements.loadMoreBtn.style.display = hasMore ? 'inline-block' : 'none';
        
        this.elements.showingStart.textContent = this.entries.length > 0 ? 1 : 0;
        this.elements.showingEnd.textContent = this.entries.length;
        this.elements.totalCount.textContent = this.totalEntries;
    }
    
    loadMore() {
        this.currentPage++;
        this.loadEntries(true);
    }
    
    resetAndLoad() {
        this.currentPage = 1;
        this.entries = [];
        this.loadEntries();
    }
    
    // UI state methods
    showLoading() {
        this.elements.loadingState.style.display = 'flex';
        this.elements.emptyState.style.display = 'none';
        this.elements.entryGrid.style.display = 'none';
    }
    
    hideLoading() {
        this.elements.loadingState.style.display = 'none';
    }
    
    showEmpty() {
        this.elements.emptyState.style.display = 'flex';
        this.elements.entryGrid.style.display = 'none';
        this.elements.paginationArea.style.display = 'none';
        
        // Update empty state message based on filters
        const hasFilters = this.filters.searchQuery || 
                          this.filters.subjectIds.length > 0 ||
                          this.filters.tagIds.length > 0 ||
                          this.filters.dateFrom ||
                          this.filters.sessionId ||
                          this.filters.isDraft;
        
        document.getElementById('emptyTitle').textContent = hasFilters 
            ? 'No entries match your filters'
            : 'No entries yet';
        document.getElementById('emptyMessage').textContent = hasFilters
            ? 'Try adjusting your filters or search query.'
            : 'Start by creating your first question entry.';
    }
    
    showError(message) {
        this.hideLoading();
        this.elements.emptyState.style.display = 'flex';
        document.getElementById('emptyTitle').textContent = 'Error';
        document.getElementById('emptyMessage').textContent = message;
    }
    
    // Utility methods
    formatDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', { 
            month: 'short', 
            day: 'numeric', 
            year: 'numeric' 
        });
    }
    
    formatDateISO(date) {
        return date.toISOString().split('T')[0];
    }
    
    lightenColor(hex, amount) {
        if (!hex) return '#f3f4f6';
        // Convert hex to RGB, lighten, convert back
        let color = hex.replace('#', '');
        if (color.length === 3) {
            color = color.split('').map(c => c + c).join('');
        }
        const num = parseInt(color, 16);
        const r = Math.min(255, Math.floor((num >> 16) + (255 - (num >> 16)) * amount));
        const g = Math.min(255, Math.floor(((num >> 8) & 0x00FF) + (255 - ((num >> 8) & 0x00FF)) * amount));
        const b = Math.min(255, Math.floor((num & 0x0000FF) + (255 - (num & 0x0000FF)) * amount));
        return `rgb(${r}, ${g}, ${b})`;
    }

    // =========================================================================
    // Selection Mode (Export IDs)
    // =========================================================================

    enterSelectionMode() {
        this.selectionMode = true;
        this.selectedEntryIds.clear();

        // Show selection toolbar, hide the enter button
        if (this.elements.selectionToolbar) this.elements.selectionToolbar.style.display = 'flex';
        if (this.elements.enterSelectionBtn) this.elements.enterSelectionBtn.style.display = 'none';

        // Re-render cards to show checkboxes
        this.renderEntries(false);
        this.updateSelectionUI();
    }

    exitSelectionMode() {
        this.selectionMode = false;
        this.selectedEntryIds.clear();

        // Hide selection toolbar, show the enter button
        if (this.elements.selectionToolbar) this.elements.selectionToolbar.style.display = 'none';
        if (this.elements.enterSelectionBtn) this.elements.enterSelectionBtn.style.display = '';
        if (this.elements.selectAllCheckbox) this.elements.selectAllCheckbox.checked = false;

        // Re-render cards to remove checkboxes
        this.renderEntries(false);
    }

    toggleEntrySelection(entryId) {
        if (this.selectedEntryIds.has(entryId)) {
            this.selectedEntryIds.delete(entryId);
        } else {
            this.selectedEntryIds.add(entryId);
        }

        // Update the card's visual state
        const card = this.elements.entryGrid.querySelector(`[data-entry-id="${entryId}"]`);
        if (card) {
            const checkbox = card.querySelector('.entry-checkbox');
            const isSelected = this.selectedEntryIds.has(entryId);
            card.classList.toggle('selected', isSelected);
            if (checkbox) checkbox.checked = isSelected;
        }

        this.updateSelectionUI();
    }

    selectAllVisible() {
        this.entries.forEach(entry => {
            this.selectedEntryIds.add(entry.id);
        });

        // Update all card visuals
        this.elements.entryGrid.querySelectorAll('.entry-card').forEach(card => {
            card.classList.add('selected');
            const checkbox = card.querySelector('.entry-checkbox');
            if (checkbox) checkbox.checked = true;
        });

        this.updateSelectionUI();
    }

    deselectAll() {
        this.selectedEntryIds.clear();

        this.elements.entryGrid.querySelectorAll('.entry-card').forEach(card => {
            card.classList.remove('selected');
            const checkbox = card.querySelector('.entry-checkbox');
            if (checkbox) checkbox.checked = false;
        });

        this.updateSelectionUI();
    }

    updateSelectionUI() {
        const count = this.selectedEntryIds.size;
        if (this.elements.selectionCount) {
            this.elements.selectionCount.textContent = `${count} selected`;
        }
        if (this.elements.exportSelectedBtn) {
            this.elements.exportSelectedBtn.disabled = count === 0;
        }
        if (this.elements.selectAllCheckbox) {
            this.elements.selectAllCheckbox.checked = count > 0 && count === this.entries.length;
        }
    }

    /**
     * Collect question IDs from selected entries and open the export dialog.
     */
    async exportSelectedIds() {
        const questionIds = [];
        let skippedCount = 0;

        this.entries.forEach(entry => {
            if (this.selectedEntryIds.has(entry.id)) {
                if (entry.question_id) {
                    questionIds.push(String(entry.question_id));
                } else {
                    skippedCount++;
                }
            }
        });

        if (questionIds.length === 0) {
            // Use a simple alert since toast.js may not be loaded on this page
            alert('None of the selected entries have a question ID.');
            return;
        }

        await ExportQuestionIdsDialog.show(questionIds, { skippedCount });
    }

    /**
     * Collect question IDs from all currently loaded/visible entries and open the export dialog.
     */
    async exportAllVisibleIds() {
        const questionIds = [];
        let skippedCount = 0;

        this.entries.forEach(entry => {
            if (entry.question_id) {
                questionIds.push(String(entry.question_id));
            } else {
                skippedCount++;
            }
        });

        if (questionIds.length === 0) {
            alert('None of the visible entries have a question ID.');
            return;
        }

        await ExportQuestionIdsDialog.show(questionIds, { skippedCount });
    }

    // ========================================
    // Search Autocomplete
    // ========================================

    setupSearchAutocomplete() {
        const input = this.elements.searchInput;
        const dropdown = document.getElementById('searchAutocomplete');
        if (!dropdown) return;

        input.addEventListener('keydown', (e) => {
            if (!dropdown.classList.contains('visible')) return;
            const items = dropdown.querySelectorAll('.autocomplete-item');
            if (items.length === 0) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.moveAutocompleteHighlight(1, items);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.moveAutocompleteHighlight(-1, items);
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                if (this.autocompleteHighlightIndex >= 0) {
                    e.preventDefault();
                    this.selectAutocompleteItem(this.autocompleteHighlightIndex);
                }
            } else if (e.key === 'Escape') {
                this.hideAutocomplete();
            }
        });

        input.addEventListener('blur', () => {
            // Delay to allow click on item
            setTimeout(() => this.hideAutocomplete(), 150);
        });

        input.addEventListener('focus', () => {
            this.updateAutocomplete(input.value);
        });
    }

    updateAutocomplete(inputValue) {
        const dropdown = document.getElementById('searchAutocomplete');
        if (!dropdown) return;

        const input = this.elements.searchInput;
        const cursorPos = input.selectionStart || inputValue.length;

        // Get the word at cursor position
        const textBeforeCursor = inputValue.substring(0, cursorPos);
        const wordMatch = textBeforeCursor.match(/(\S+)$/);
        const currentWord = wordMatch ? wordMatch[1] : '';

        // Only show autocomplete for partial prefix matches (not already complete prefix:)
        if (!currentWord || currentWord.includes(':')) {
            this.hideAutocomplete();
            return;
        }

        const matches = this.SEARCH_PREFIXES.filter(p =>
            p.name.startsWith(currentWord.toLowerCase())
        );

        if (matches.length === 0) {
            this.hideAutocomplete();
            return;
        }

        this.autocompleteHighlightIndex = -1;
        dropdown.innerHTML = matches.map((p, i) => `
            <div class="autocomplete-item" data-index="${i}" data-prefix="${p.name}" data-testid="browser-autocomplete-item-${p.name.replace(':', '')}">
                <span class="prefix-name">${p.name}</span>
                <span class="prefix-desc">${p.description}</span>
            </div>
        `).join('');

        dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
                this.selectAutocompleteItem(parseInt(item.dataset.index));
            });
        });

        dropdown.classList.add('visible');
    }

    selectAutocompleteItem(index) {
        const dropdown = document.getElementById('searchAutocomplete');
        if (!dropdown) return;
        const items = dropdown.querySelectorAll('.autocomplete-item');
        if (index < 0 || index >= items.length) return;

        const prefix = items[index].dataset.prefix;
        const input = this.elements.searchInput;
        const value = input.value;
        const cursorPos = input.selectionStart || value.length;

        // Find the partial word before cursor
        const textBeforeCursor = value.substring(0, cursorPos);
        const wordMatch = textBeforeCursor.match(/(\S+)$/);
        const wordStart = wordMatch ? cursorPos - wordMatch[1].length : cursorPos;

        // Replace partial word with full prefix
        const newValue = value.substring(0, wordStart) + prefix + value.substring(cursorPos);
        input.value = newValue;

        // Position cursor after the colon
        const newCursorPos = wordStart + prefix.length;
        input.setSelectionRange(newCursorPos, newCursorPos);
        input.focus();

        this.hideAutocomplete();
    }

    moveAutocompleteHighlight(direction, items) {
        if (!items || items.length === 0) return;

        // Remove previous highlight
        items.forEach(item => item.classList.remove('highlighted'));

        // Calculate new index with wrapping
        this.autocompleteHighlightIndex += direction;
        if (this.autocompleteHighlightIndex >= items.length) {
            this.autocompleteHighlightIndex = 0;
        } else if (this.autocompleteHighlightIndex < 0) {
            this.autocompleteHighlightIndex = items.length - 1;
        }

        items[this.autocompleteHighlightIndex].classList.add('highlighted');
    }

    hideAutocomplete() {
        const dropdown = document.getElementById('searchAutocomplete');
        if (dropdown) {
            dropdown.classList.remove('visible');
            dropdown.innerHTML = '';
        }
        this.autocompleteHighlightIndex = -1;
    }
}

// Initialize browser
const entryBrowser = new EntryBrowser();