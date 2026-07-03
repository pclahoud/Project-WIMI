/**
 * WIMI Question Entry JavaScript
 * Phase 4 Stage 3 - Question Entry Form Logic
 */

// =========================================================================
// State Management
// =========================================================================

const EntryState = {
    sessionId: null,
    session: null,
    examContext: null,
    currentEntryIndex: 0,
    entries: [],
    currentEntry: null,
    isDirty: false,
    isLoading: true,
    isNavigating: false, // Mutex to prevent auto-save during navigation
    autoSaveTimer: null,
    autoSaveInterval: 30000, // 30 seconds
    lastSaveTime: null,

    // Rich text editors
    explanationEditor: null,
    reflectionEditor: null,
    // Multi-note editors: Array of { id, tempId, editor: RichEditor, linkedSubjectIds: [] }
    noteEditors: [],
    noteIdCounter: 0,

    // Form data
    formData: {
        questionId: '',
        userAnswer: '',
        correctAnswer: '',
        perceivedDifficulty: null,
        timeSpent: null,
        timeUnit: 'minutes',
        primarySubjects: [],
        secondarySubjects: [],
        tags: [],
        reflection: '',
        explanation: '',
        notes: '',
        // Rich text JSON data (for round-trip editing)
        reflection_json: null,
        explanation_json: null,
        notes_json: null,
        media: [],
        notesList: [],
        // Per-primary-subject parent-context choice — see
        // POLYHIERARCHY_MIGRATION.md §7.3 (Tag context pill).
        // Map of { subjectId: parentNodeId } for subjects whose user-
        // chosen tag-context differs from the canonical primary edge.
        // Persisted via api.setPrimaryParentForEntry after each save.
        primaryParentChoices: {}
    },

    // Cache: subjectId -> array of parent-edge dicts (from
    // api.getEdgesForChild). Drives the Tag context pill render
    // without re-hitting the bridge on every chip rerender.
    subjectParentEdges: {},
    // Track which subjects had their parent edges synced to DB this
    // session so we don't write the same value repeatedly.
    primaryParentSynced: {},

    // Available data for selection
    tagHierarchy: [],
    subjects: [],

    // UI state
    imageSuggestionsDismissed: false,

    // Timer state
    timerIntervalId: null,
    timerExpired: false,
    timerPaused: false,
    activeRound: null,
    breakActive: false,
    breakEndTime: null,
    userPreferences: null
};

// =========================================================================
// Toast Notification System
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
        
        const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
        
        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || 'ℹ'}</span>
            <div class="toast-content">
                <p class="toast-title">${title}</p>
                ${message ? `<p class="toast-message">${message}</p>` : ''}
            </div>
            <button class="toast-close" aria-label="Close">×</button>
        `;
        
        this.container.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('show'));
        
        toast.querySelector('.toast-close').addEventListener('click', () => this.dismiss(toast));
        if (duration > 0) setTimeout(() => this.dismiss(toast), duration);
        
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
    }
};

// =========================================================================
// Utility Functions
// =========================================================================

function getUrlParam(param) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(param);
}

function formatDate(dateStr) {
    if (!dateStr) return 'Unknown';
    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
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

function debounce(func, wait) {
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

// =========================================================================
// Section Collapse/Expand
// =========================================================================

// Order of sections for navigation
const SECTION_ORDER = [
    'section-question-info',
    'section-subjects',
    'section-tags',
    'section-reflection',
    'section-explanation',
    'section-notes'
];

function toggleSection(sectionId, focusFirstInput = false) {
    const section = document.getElementById(sectionId);
    if (!section) return;

    const wasExpanded = section.classList.contains('expanded');
    const header = section.querySelector('.entry-section-header');

    // If clicking already-expanded section, just collapse it
    if (wasExpanded) {
        section.classList.remove('expanded');
        if (header) header.setAttribute('aria-expanded', 'false');
        return;
    }

    // Collapse OTHER sections only (not target)
    document.querySelectorAll('.entry-section').forEach(s => {
        if (s.id !== sectionId) {
            s.classList.remove('expanded');
            const h = s.querySelector('.entry-section-header');
            if (h) h.setAttribute('aria-expanded', 'false');
        }
    });

    // Expand target section
    section.classList.add('expanded');
    if (header) header.setAttribute('aria-expanded', 'true');

    if (focusFirstInput) {
        setTimeout(() => {
            const firstInput = section.querySelector('input:not([type="hidden"]), textarea, select, .ql-editor');
            if (firstInput) firstInput.focus();
        }, 150);
    }
}

function expandSection(sectionId, focusFirstInput = false) {
    const section = document.getElementById(sectionId);
    if (section && !section.classList.contains('expanded')) {
        toggleSection(sectionId, focusFirstInput);
    }
}

function handleSectionKeydown(event, sectionId) {
    // Handle Enter or Space to toggle section
    if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggleSection(sectionId, true);
    }
}

function getNextSection(currentSectionId) {
    const currentIndex = SECTION_ORDER.indexOf(currentSectionId);
    if (currentIndex < SECTION_ORDER.length - 1) {
        return SECTION_ORDER[currentIndex + 1];
    }
    return null;
}

function getPrevSection(currentSectionId) {
    const currentIndex = SECTION_ORDER.indexOf(currentSectionId);
    if (currentIndex > 0) {
        return SECTION_ORDER[currentIndex - 1];
    }
    return null;
}

// Handle Tab key to navigate between sections
function initSectionTabNavigation() {
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Tab') return;
        
        const activeElement = document.activeElement;
        if (!activeElement) return;
        
        // Check if we're in a form field within a section
        const currentSection = activeElement.closest('.entry-section');
        if (!currentSection) return;
        
        const sectionId = currentSection.id;
        const isLastInSection = activeElement.dataset.lastInSection === 'true';
        
        // If tabbing forward from the last field in a section
        if (!e.shiftKey && isLastInSection) {
            const nextSectionId = getNextSection(sectionId);
            if (nextSectionId) {
                e.preventDefault();
                const nextSection = document.getElementById(nextSectionId);
                const nextHeader = nextSection?.querySelector('.entry-section-header');
                if (nextHeader) {
                    // Expand the next section and focus its header
                    toggleSection(nextSectionId, false);
                    nextHeader.focus();
                }
            }
        }
        
        // If shift-tabbing from the first field in a section
        if (e.shiftKey) {
            const firstInput = currentSection.querySelector('input:not([type="hidden"]), textarea, select');
            if (activeElement === firstInput) {
                const prevSectionId = getPrevSection(sectionId);
                if (prevSectionId) {
                    e.preventDefault();
                    const prevSection = document.getElementById(prevSectionId);
                    const prevHeader = prevSection?.querySelector('.entry-section-header');
                    if (prevHeader) {
                        // Focus the previous section's header
                        prevHeader.focus();
                    }
                }
            }
        }
    });
    
    // When a section header receives focus via Tab, expand it.
    //
    // Use ``:focus-visible`` to gate this on keyboard-induced focus only.
    // The browser's focus-visible heuristic is already exactly the
    // signal we need: it matches when focus came from a key (Tab,
    // Shift+Tab, arrow keys) but not from a mouse/touch click. Mouse
    // clicks still set ``:focus`` on the element (because the header
    // is ``tabindex="0"``), but ``:focus-visible`` returns false, so
    // the focus handler bails and lets the inline ``onclick`` be the
    // sole toggle path. This replaces a fragile flag-based guard that
    // raced with the click-vs-focus event order.
    document.querySelectorAll('.entry-section-header').forEach(header => {
        header.addEventListener('focus', () => {
            const section = header.closest('.entry-section');
            if (!section) return;

            // Mouse-induced focus is ``:focus`` but NOT
            // ``:focus-visible``. Bail so the click handler alone
            // drives the toggle.
            if (!header.matches(':focus-visible')) {
                return;
            }

            // Only expand if collapsed (for Tab navigation).
            if (!section.classList.contains('expanded')) {
                toggleSection(section.id, false);
            }
        });
    });
}

// =========================================================================
// Difficulty Rating
// =========================================================================

function initDifficultyRating() {
    const container = document.getElementById('difficulty-rating');
    const hiddenInput = document.getElementById('perceived-difficulty');
    
    if (!container) return;
    
    container.querySelectorAll('.difficulty-dot').forEach(dot => {
        dot.addEventListener('click', () => {
            const value = parseInt(dot.dataset.value);
            
            // Toggle selection
            if (hiddenInput.value === String(value)) {
                hiddenInput.value = '';
                dot.classList.remove('selected');
            } else {
                container.querySelectorAll('.difficulty-dot').forEach(d => d.classList.remove('selected'));
                dot.classList.add('selected');
                hiddenInput.value = value;
            }
            
            EntryState.formData.perceivedDifficulty = hiddenInput.value ? parseInt(hiddenInput.value) : null;
            markDirty();
        });
    });
}

function setDifficultyRating(value) {
    const container = document.getElementById('difficulty-rating');
    const hiddenInput = document.getElementById('perceived-difficulty');
    
    if (!container) return;
    
    container.querySelectorAll('.difficulty-dot').forEach(dot => {
        if (parseInt(dot.dataset.value) === value) {
            dot.classList.add('selected');
        } else {
            dot.classList.remove('selected');
        }
    });
    
    hiddenInput.value = value || '';
}

// =========================================================================
// Subject Search & Selection (Phase 4 Stage 4 - Fuse.js Integration)
// =========================================================================

// Store keyboard controllers for cleanup
const keyboardControllers = {
    primarySubject: null,
    secondarySubject: null,
    tags: null
};

/**
 * Load all subjects for the exam and initialize fuzzy search index
 * Uses enhanced method with aliases for better searchability
 */
async function loadAllSubjectsForFuzzySearch() {
    if (!EntryState.session) return;

    try {
        console.log('📚 Loading all subjects for fuzzy search...');

        // Try to load with aliases first for enhanced search
        let subjects;
        try {
            subjects = await api.getAllSubjectsWithAliasesForExam(EntryState.session.exam_context_id);
            console.log('✅ Loaded subjects with alias support');
        } catch (aliasError) {
            // Fall back to basic method without aliases
            console.warn('⚠️ Alias-enhanced load failed, using basic method');
            subjects = await api.getAllSubjectsForExam(EntryState.session.exam_context_id);
        }

        EntryState.subjects = subjects || [];

        // Initialize fuzzy search index (will detect if aliases are present)
        if (typeof fuzzySearch !== 'undefined') {
            fuzzySearch.initSubjectIndex(subjects);
        } else {
            console.warn('⚠️ FuzzySearch not available, falling back to API search');
        }
    } catch (error) {
        console.error('Error loading subjects for fuzzy search:', error);
        // Fall back to API search if loading fails
    }
}

function initSubjectSearch() {
    // Initialize primary subject search with keyboard nav
    initSubjectSearchField('primary-subject-search', 'primary-subject-dropdown', 'primary-subjects-chips', 'primary');
    keyboardControllers.primarySubject = attachDropdownKeyboard('primary-subject-search', 'primary-subject-dropdown', {
        itemSelector: '.subject-option'
    });
    
    // Initialize secondary subject search with keyboard nav
    initSubjectSearchField('secondary-subject-search', 'secondary-subject-dropdown', 'secondary-subjects-chips', 'secondary');
    keyboardControllers.secondarySubject = attachDropdownKeyboard('secondary-subject-search', 'secondary-subject-dropdown', {
        itemSelector: '.subject-option'
    });
}

function initSubjectSearchField(inputId, dropdownId, chipsId, type) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    const chipsContainer = document.getElementById(chipsId);
    
    if (!input || !dropdown) return;
    
    // Store current query for highlighting
    let currentQuery = '';
    
    const searchSubjects = (query) => {
        currentQuery = query;
        
        if (!query || query.length < 2) {
            dropdown.classList.remove('visible');
            return;
        }
        
        // Use fuzzy search if available, otherwise fall back to API
        if (typeof fuzzySearch !== 'undefined' && fuzzySearch.isReady()) {
            const results = fuzzySearch.searchSubjects(query, 10);
            renderSubjectDropdown(dropdown, results, type, query);
        } else {
            // Fallback to API search (debounced)
            searchSubjectsViaAPI(query, dropdown, type);
        }
    };
    
    // Debounced API fallback
    const searchSubjectsViaAPI = debounce(async (query, dropdown, type) => {
        try {
            const results = await api.searchSubjects(EntryState.session.exam_context_id, query, 10);
            renderSubjectDropdown(dropdown, results, type, query);
        } catch (error) {
            console.error('Error searching subjects:', error);
        }
    }, 300);
    
    input.addEventListener('input', (e) => {
        searchSubjects(e.target.value);
    });
    
    input.addEventListener('focus', () => {
        if (input.value.length >= 2) {
            searchSubjects(input.value);
        }
    });
    
    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.remove('visible');
        }
    });
}

/**
 * Render subject dropdown with fuzzy search results
 * Includes match highlighting, best match indicator, and alias match display
 */
function renderSubjectDropdown(dropdown, results, type, query = '') {
    // Check if user has dismissed keyboard hint
    const hintDismissed = localStorage.getItem('wimi_keyboard_hint_dismissed') === 'true';

    if (!results || results.length === 0) {
        dropdown.innerHTML = `
            <div class="dropdown-empty">
                <span class="dropdown-empty-icon">🔍</span>
                <span>No subjects found</span>
            </div>
        `;
    } else {
        const highlightFn = typeof fuzzySearch !== 'undefined'
            ? (text) => fuzzySearch.highlightMatches(text, query)
            : (text) => escapeHtml(text);

        dropdown.innerHTML = `
            <div class="dropdown-results" role="listbox">
                ${results.map((subject, index) => {
                    const isBestMatch = subject.isBestMatch || (index === 0 && subject.score < 0.3);

                    // Check if match came from an alias
                    const matchedAlias = subject.matchedAlias || null;
                    const aliasHtml = matchedAlias
                        ? `<span class="alias-match"><span class="alias-label">matched:</span> ${escapeHtml(matchedAlias)}</span>`
                        : '';

                    return `
                        <div class="subject-option ${isBestMatch ? 'best-match' : ''}"
                             role="option"
                             id="subject-option-${type}-${index}"
                             data-id="${subject.id}"
                             data-name="${escapeHtml(subject.name)}"
                             data-path="${escapeHtml(subject.path)}"
                             data-index="${index}"
                             data-testid="entry-form-subject-option-${type}-${subject.id}"
                             aria-selected="false"
                             onclick="selectSubject(${subject.id}, '${escapeHtml(subject.name).replace(/'/g, "&apos;")}', '${escapeHtml(subject.path).replace(/'/g, "&apos;")}', '${type}')">
                            ${isBestMatch ? '<span class="best-match-icon" title="Best match">🎯</span>' : ''}
                            <div class="subject-option-content">
                                <div class="subject-option-name">${highlightFn(subject.name)}</div>
                                <div class="subject-option-path"><span class="subject-option-path-text">${escapeHtml(subject.path)}</span>${aliasHtml}</div>
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
            ${!hintDismissed ? `
                <div class="dropdown-hint" id="keyboard-hint-${type}">
                    <span>💡 ↑↓ navigate • Enter select • Esc close</span>
                    <button type="button" class="dropdown-hint-dismiss" onclick="dismissKeyboardHint(event)" title="Dismiss">×</button>
                </div>
            ` : ''}
        `;
    }
    dropdown.classList.add('visible');
}

/**
 * Dismiss the keyboard hint permanently
 */
function dismissKeyboardHint(event) {
    event.stopPropagation();
    localStorage.setItem('wimi_keyboard_hint_dismissed', 'true');
    
    // Remove all keyboard hints from the page
    document.querySelectorAll('.dropdown-hint').forEach(hint => {
        hint.remove();
    });
}

function selectSubject(id, name, path, type) {
    const subjects = type === 'primary' ? EntryState.formData.primarySubjects : EntryState.formData.secondarySubjects;
    const otherSubjects = type === 'primary' ? EntryState.formData.secondarySubjects : EntryState.formData.primarySubjects;
    const otherLabel = type === 'primary' ? 'secondary' : 'primary';
    const chipsId = type === 'primary' ? 'primary-subjects-chips' : 'secondary-subjects-chips';
    const inputId = type === 'primary' ? 'primary-subject-search' : 'secondary-subject-search';
    const dropdownId = type === 'primary' ? 'primary-subject-dropdown' : 'secondary-subject-dropdown';

    // Check if already selected
    if (subjects.some(s => s.id === id)) {
        Toast.info('Already Selected', 'This subject is already added.');
        return;
    }

    // The DB unique index on entry_subject_mappings(question_entry_id,
    // subject_node_id) is mapping_type-agnostic, so the same subject
    // cannot be both primary and secondary on the same entry. Reject
    // here with a clear message instead of letting save fail with an
    // opaque IntegrityError.
    if (otherSubjects.some(s => s.id === id)) {
        Toast.warning(
            'Already a ' + otherLabel + ' subject',
            'Remove "' + name + '" from ' + otherLabel + ' subjects first.'
        );
        return;
    }

    // Add to state
    subjects.push({ id, name, path });

    // Render chip
    renderSubjectChips(chipsId, subjects, type);

    // Clear input, hide dropdown, and refocus search input
    const searchInput = document.getElementById(inputId);
    searchInput.value = '';
    document.getElementById(dropdownId).classList.remove('visible');
    searchInput.focus();

    markDirty();
    validateForm();

    // Update MediaUpload and note subjects with current entry subjects
    syncMediaUploadSubjects();
    syncNoteSubjects();

    // For primary subjects, check for associated images
    if (type === 'primary') {
        checkSubjectImages(id, name);
        scheduleRefreshAttachCandidates();
    }
}

/**
 * Add a subject chip programmatically (used by auto-fill)
 */
function addSubjectChip(type, subject) {
    const subjects = type === 'primary' ? EntryState.formData.primarySubjects : EntryState.formData.secondarySubjects;
    const otherSubjects = type === 'primary' ? EntryState.formData.secondarySubjects : EntryState.formData.primarySubjects;
    const chipsId = type === 'primary' ? 'primary-subjects-chips' : 'secondary-subjects-chips';

    // Check if already selected (same list OR other list — the entry's
    // subject mappings are unique by (entry, subject), see selectSubject).
    if (subjects.some(s => s.id === subject.id) || otherSubjects.some(s => s.id === subject.id)) {
        return;
    }

    // Add to state
    subjects.push({
        id: subject.id,
        name: subject.name,
        path: subject.path || subject.name
    });

    // Render chip
    renderSubjectChips(chipsId, subjects, type);

    // Update MediaUpload and note subjects with current entry subjects
    syncMediaUploadSubjects();
    syncNoteSubjects();

    if (type === 'primary') {
        scheduleRefreshAttachCandidates();
    }
}

/**
 * Check for images associated with a subject and offer auto-population
 */
async function checkSubjectImages(subjectId, subjectName) {
    if (!EntryState.session?.exam_context_id) return;

    // Don't prompt if entry already has images
    if (EntryState.formData.media.length > 0) return;

    // Check if user has dismissed image suggestions this session
    if (EntryState.imageSuggestionsDismissed) return;

    try {
        // Look up the subject's dimension_id for filtering
        const subject = EntryState.subjects?.find(s => s.id === subjectId);
        const dimensionId = subject?.dimension_id || 0;

        const images = await api.getMediaBySubject(subjectId, 5, dimensionId);

        if (images && images.length > 0) {
            showImageAutoPopulationPrompt(images, subjectName);
        }
    } catch (error) {
        console.error('Error checking subject images:', error);
    }
}

/**
 * Show prompt to auto-populate images from subject
 */
function showImageAutoPopulationPrompt(images, subjectName) {
    // Remove any existing prompt
    hideImageAutoPopulationPrompt();

    const prompt = document.createElement('div');
    prompt.id = 'image-autopopulate-prompt';
    prompt.className = 'autofill-prompt';
    prompt.dataset.testid = 'entry-form-image-autopopulate-prompt';
    prompt.innerHTML = `
        <div class="autofill-prompt-content">
            <div class="autofill-prompt-icon">🖼️</div>
            <div class="autofill-prompt-text">
                <strong>Related images found</strong>
                <span>${images.length} image${images.length !== 1 ? 's' : ''} previously used with "${subjectName}"</span>
            </div>
            <div class="autofill-prompt-actions">
                <button type="button" class="btn btn-sm btn-primary" id="btn-image-autopopulate-accept" data-testid="entry-form-image-autopopulate-accept-button">
                    Add Images
                </button>
                <button type="button" class="btn btn-sm btn-ghost" id="btn-image-autopopulate-dismiss" data-testid="entry-form-image-autopopulate-dismiss-button">
                    Dismiss
                </button>
                <button type="button" class="btn btn-sm btn-ghost" id="btn-image-autopopulate-stop" title="Don't show image suggestions for this session" data-testid="entry-form-image-autopopulate-stop-button">
                    Don't Ask Again
                </button>
            </div>
        </div>
    `;

    // Insert in the media upload section
    const mediaSection = document.getElementById('section-media-content') ||
                        document.getElementById('media-upload-container')?.closest('.entry-section-content');
    if (mediaSection) {
        mediaSection.insertBefore(prompt, mediaSection.firstChild);
    }

    // Event listeners
    document.getElementById('btn-image-autopopulate-accept')?.addEventListener('click', () => {
        applyImageAutoPopulation(images);
        hideImageAutoPopulationPrompt();
    });

    document.getElementById('btn-image-autopopulate-dismiss')?.addEventListener('click', () => {
        hideImageAutoPopulationPrompt();
    });

    document.getElementById('btn-image-autopopulate-stop')?.addEventListener('click', () => {
        EntryState.imageSuggestionsDismissed = true;
        hideImageAutoPopulationPrompt();
        Toast.info('Image Suggestions Disabled', 'Image suggestions won\'t appear for the rest of this session');
    });
}

/**
 * Hide image auto-population prompt
 */
function hideImageAutoPopulationPrompt() {
    const existing = document.getElementById('image-autopopulate-prompt');
    if (existing) {
        existing.remove();
    }
}

/**
 * Apply auto-populated images
 */
function applyImageAutoPopulation(images) {
    if (!EntryState.mediaUpload) return;

    let addedCount = 0;
    images.forEach(image => {
        if (!EntryState.formData.media.some(m => m.id === image.id)) {
            EntryState.formData.media.push(image);
            addedCount++;
        }
    });

    if (addedCount > 0) {
        // Reload media display
        if (EntryState.mediaUpload.mediaItems) {
            EntryState.mediaUpload.mediaItems = [...EntryState.formData.media];
            EntryState.mediaUpload.renderThumbnails();
        }
        markDirty();
        Toast.success('Images Added', `Added ${addedCount} related image${addedCount !== 1 ? 's' : ''}`);
    }
}

function removeSubject(id, type) {
    // Check if any images have this subject linked
    const linkedImages = getImagesLinkedToSubject(id);
    if (linkedImages.length > 0) {
        // Show confirmation warning
        const imageNames = linkedImages.map(img => img.user_filename || 'Unnamed image').join(', ');
        const confirmRemove = confirm(
            `Warning: ${linkedImages.length} image(s) are linked to this subject:\n${imageNames}\n\n` +
            `Removing this subject will NOT automatically unlink the images, but they may become orphaned ` +
            `if this was their only subject.\n\nContinue removing this subject?`
        );
        if (!confirmRemove) {
            return;
        }
    }

    const subjects = type === 'primary' ? EntryState.formData.primarySubjects : EntryState.formData.secondarySubjects;
    const chipsId = type === 'primary' ? 'primary-subjects-chips' : 'secondary-subjects-chips';

    const index = subjects.findIndex(s => s.id === id);
    if (index > -1) {
        subjects.splice(index, 1);
    }

    // Tag context pill housekeeping (§7.3): when a primary subject
    // chip is removed, drop any per-subject parent-context choice so
    // we don't leak stale state into the next save.
    if (type === 'primary') {
        delete EntryState.formData.primaryParentChoices[id];
        delete EntryState.primaryParentSynced[id];
    }

    renderSubjectChips(chipsId, subjects, type);
    markDirty();
    validateForm();

    // Refocus the subject search input
    const inputId = type === 'primary' ? 'primary-subject-search' : 'secondary-subject-search';
    document.getElementById(inputId)?.focus();

    // Update MediaUpload and note subjects with current entry subjects
    syncMediaUploadSubjects();
    syncNoteSubjects();

    if (type === 'primary') {
        scheduleRefreshAttachCandidates();
    }
}

/**
 * Get images that have a specific subject in their linked_subject_ids
 */
function getImagesLinkedToSubject(subjectId) {
    const media = EntryState.formData.media || [];
    return media.filter(img => {
        const linkedIds = img.linked_subject_ids || [];
        return linkedIds.includes(subjectId);
    });
}

// =========================================================================
// Attach-Existing — header buttons + picker modal
// =========================================================================
// Replaces the old "Reuse from other entries" section-rendered surface
// with two small per-section header buttons (one next to the Notes
// label, one next to the Media label). Each button is disabled when
// no candidates exist for the entry's primary subjects, and enabled
// (with a parenthesised count) when there are. Click → opens a picker
// modal that lets the user multi-select and confirm.
//
// Candidates are polled (debounced 250ms) on the same 5 events that
// the legacy renderer subscribed to: primary subject add (typeahead
// + programmatic), primary subject remove, populate-from-entry, and
// reset-for-new-entry. Plus once after each picker-confirm to refresh
// the now-smaller candidate set.

const ATTACH_FETCH_LIMIT = 50;
const ATTACH_PREVIEW_CHARS = 200;
const ATTACH_KINDS = ['notes', 'media'];

const _attachCandidates = { notes: [], media: [] };
let _attachCandidatesTimer = null;

let _attachExistingKind = null;
const _attachExistingSelected = new Set();
let _attachExistingHandlersWired = false;

function _attachStripHtml(html) {
    if (!html) return '';
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const text = (tmp.textContent || tmp.innerText || '').trim();
    return text.replace(/\s+/g, ' ');
}

function _attachTruncate(str, max) {
    if (!str) return '';
    if (str.length <= max) return str;
    return str.slice(0, max - 1).trimEnd() + '…';
}

function _attachResolveDimensionId() {
    const subjects = EntryState.formData.primarySubjects || [];
    for (const s of subjects) {
        const full = EntryState.subjects?.find(x => x.id === s.id);
        if (full?.dimension_id) return full.dimension_id;
    }
    return 0;
}

function _attachDisableBoth(reason) {
    for (const kind of ATTACH_KINDS) {
        const btn = document.getElementById(`btn-attach-existing-${kind}`);
        const countSpan = document.getElementById(`btn-attach-existing-${kind}-count`);
        if (!btn) continue;
        btn.disabled = true;
        btn.title = reason;
        if (countSpan) { countSpan.hidden = true; countSpan.textContent = ''; }
        _attachCandidates[kind] = [];
    }
}

function updateAttachButtonState(kind) {
    const btn = document.getElementById(`btn-attach-existing-${kind}`);
    const countSpan = document.getElementById(`btn-attach-existing-${kind}-count`);
    if (!btn) return;
    const n = (_attachCandidates[kind] || []).length;
    const noun = kind === 'notes' ? 'note' : 'image';
    if (n === 0) {
        btn.disabled = true;
        btn.title = `No matching ${noun}s found for this entry's subjects yet`;
        if (countSpan) { countSpan.hidden = true; countSpan.textContent = ''; }
    } else {
        btn.disabled = false;
        btn.title = `${n} matching ${noun}${n === 1 ? '' : 's'} available to attach`;
        if (countSpan) { countSpan.hidden = false; countSpan.textContent = `(${n})`; }
    }
}

async function refreshAttachCandidates() {
    const subjects = EntryState.formData.primarySubjects || [];
    const primarySubjectIds = subjects.map(s => s.id).filter(Boolean);

    if (primarySubjectIds.length === 0) {
        _attachDisableBoth('No primary subjects yet — tag one to see matches');
        return;
    }
    if (!window.api) {
        _attachDisableBoth('API not ready');
        return;
    }

    try {
        await api.ready();
        const dimensionId = _attachResolveDimensionId();
        const excludeEntryId = EntryState.currentEntry?.id || 0;

        const [notes, media] = await Promise.all([
            api.getNotesBySubjects(primarySubjectIds, excludeEntryId, ATTACH_FETCH_LIMIT),
            api.getMediaBySubjects(primarySubjectIds, excludeEntryId, ATTACH_FETCH_LIMIT, dimensionId)
        ]);

        const noteList = Array.isArray(notes) ? notes : [];
        const mediaList = Array.isArray(media) ? media : [];

        // Filter out items already attached to this entry. Use noteEditors
        // for in-flight id tracking (collectFormData hasn't necessarily run).
        const attachedNoteIds = new Set((EntryState.formData.notesList || [])
            .map(n => n.id).filter(Boolean));
        for (const ne of EntryState.noteEditors || []) {
            if (ne.id) attachedNoteIds.add(ne.id);
        }
        const attachedMediaIds = new Set((EntryState.formData.media || [])
            .map(m => m.id).filter(Boolean));

        _attachCandidates.notes = noteList.filter(n => !attachedNoteIds.has(n.id));
        _attachCandidates.media = mediaList.filter(m => !attachedMediaIds.has(m.id));

        updateAttachButtonState('notes');
        updateAttachButtonState('media');
    } catch (err) {
        console.error('[attach-existing] candidate refresh failed:', err);
        _attachDisableBoth("Couldn't load candidates");
    }
}

function scheduleRefreshAttachCandidates() {
    clearTimeout(_attachCandidatesTimer);
    _attachCandidatesTimer = setTimeout(() => {
        refreshAttachCandidates().catch(err => {
            console.error('[attach-existing] refresh failed:', err);
        });
    }, 250);
}

async function refreshAfterAttach(kind, entryId) {
    if (!entryId) return;
    if (kind === 'notes') {
        try {
            const fresh = await api.getEntryNotes(entryId);
            const freshNotes = Array.isArray(fresh) ? fresh : [];

            const existingById = new Map(
                EntryState.noteEditors.filter(ne => ne.id).map(ne => [ne.id, ne])
            );
            for (const note of freshNotes) {
                if (existingById.has(note.id)) {
                    existingById.get(note.id).attachmentCount =
                        typeof note.attachment_count === 'number' ? note.attachment_count : 1;
                } else {
                    addNoteCard(note);
                }
            }
            EntryState.formData.notesList = freshNotes;
        } catch (err) {
            console.error('[attach-existing] failed to refresh notes:', err);
        }
    } else if (kind === 'media') {
        try {
            if (EntryState.mediaUpload?.loadMedia) {
                await EntryState.mediaUpload.loadMedia(entryId);
                EntryState.formData.media = [...(EntryState.mediaUpload.mediaItems || [])];
            } else {
                const fresh = await api.getQuestionMedia(entryId);
                EntryState.formData.media = Array.isArray(fresh) ? fresh : [];
            }
        } catch (err) {
            console.error('[attach-existing] failed to refresh media:', err);
        }
    }
    syncMediaUploadSubjects();
    syncNoteSubjects();
}

function _attachBuildNoteRow(note) {
    const id = note.id;
    const row = document.createElement('label');
    row.className = 'attach-existing-row';
    row.dataset.kind = 'notes';
    row.dataset.itemId = String(id);
    row.dataset.testid = `attach-existing-item-notes-${id}`;
    row.setAttribute('role', 'listitem');

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'attach-existing-checkbox';
    cb.value = String(id);
    cb.dataset.testid = `attach-existing-checkbox-notes-${id}`;
    cb.addEventListener('change', () => {
        if (cb.checked) _attachExistingSelected.add(id);
        else _attachExistingSelected.delete(id);
        updateAttachExistingConfirmButton();
    });
    row.appendChild(cb);

    const body = document.createElement('div');
    body.className = 'attach-existing-body';

    const preview = document.createElement('div');
    preview.className = 'attach-existing-preview';
    const text = note.content_html ? _attachStripHtml(note.content_html) : '';
    preview.textContent = _attachTruncate(text, ATTACH_PREVIEW_CHARS) || '(empty note)';
    body.appendChild(preview);

    const meta = document.createElement('div');
    meta.className = 'attach-existing-meta';
    const entryId = note.question_entry_id || note.entry_id;
    meta.textContent = entryId ? `from entry #${entryId}` : 'from another entry';
    body.appendChild(meta);

    row.appendChild(body);
    return row;
}

function _attachBuildMediaRow(media) {
    const id = media.id;
    const row = document.createElement('label');
    row.className = 'attach-existing-row attach-existing-row-media';
    row.dataset.kind = 'media';
    row.dataset.itemId = String(id);
    row.dataset.testid = `attach-existing-item-media-${id}`;
    row.setAttribute('role', 'listitem');

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'attach-existing-checkbox';
    cb.value = String(id);
    cb.dataset.testid = `attach-existing-checkbox-media-${id}`;
    cb.addEventListener('change', () => {
        if (cb.checked) _attachExistingSelected.add(id);
        else _attachExistingSelected.delete(id);
        updateAttachExistingConfirmButton();
    });
    row.appendChild(cb);

    const thumbUrl = media.thumbnail_url || media.full_url || '';
    if (thumbUrl) {
        const img = document.createElement('img');
        img.className = 'attach-existing-thumb';
        img.src = thumbUrl;
        img.alt = media.user_filename || media.original_filename || 'image';
        img.loading = 'lazy';
        row.appendChild(img);
    } else {
        const placeholder = document.createElement('div');
        placeholder.className = 'attach-existing-thumb-placeholder';
        placeholder.setAttribute('aria-hidden', 'true');
        placeholder.textContent = '🖼';
        row.appendChild(placeholder);
    }

    const body = document.createElement('div');
    body.className = 'attach-existing-body';

    const label = document.createElement('div');
    label.className = 'attach-existing-preview';
    const name = media.user_filename || media.original_filename || `media #${id}`;
    label.textContent = name;
    label.title = name;
    body.appendChild(label);

    const meta = document.createElement('div');
    meta.className = 'attach-existing-meta';
    const entryId = media.question_entry_id || media.entry_id;
    meta.textContent = entryId ? `from entry #${entryId}` : 'from another entry';
    body.appendChild(meta);

    row.appendChild(body);
    return row;
}

function renderAttachExistingList(kind, items) {
    const listEl = document.getElementById('attach-existing-list');
    const emptyEl = document.getElementById('attach-existing-empty');
    if (!listEl || !emptyEl) return;
    listEl.innerHTML = '';
    if (!items || items.length === 0) {
        emptyEl.hidden = false;
        return;
    }
    emptyEl.hidden = true;
    for (const item of items) {
        const row = kind === 'notes'
            ? _attachBuildNoteRow(item)
            : _attachBuildMediaRow(item);
        listEl.appendChild(row);
    }
}

function updateAttachExistingConfirmButton() {
    const btn = document.getElementById('btn-attach-existing-confirm');
    if (!btn) return;
    const n = _attachExistingSelected.size;
    btn.disabled = n === 0;
    btn.textContent = n > 0 ? `Attach selected (${n})` : 'Attach selected';
}

function openAttachExistingPicker(kind) {
    if (!ATTACH_KINDS.includes(kind)) return;
    _attachExistingKind = kind;
    _attachExistingSelected.clear();

    const items = _attachCandidates[kind] || [];
    const titleEl = document.getElementById('attach-existing-modal-title');
    const subEl = document.getElementById('attach-existing-modal-sub');
    if (titleEl) {
        titleEl.textContent = kind === 'notes' ? 'Attach existing notes' : 'Attach existing images';
    }
    if (subEl) {
        const noun = kind === 'notes' ? 'note' : 'image';
        subEl.textContent = items.length === 0
            ? `No matching ${noun}s available — items already attached to this entry are excluded.`
            : `${items.length} ${noun}${items.length === 1 ? '' : 's'} matching this entry's subjects.`;
    }

    renderAttachExistingList(kind, items);
    updateAttachExistingConfirmButton();
    _wireAttachExistingHandlers();
    Modal.open('attach-existing-modal');

    // Focus management: first checkbox if any, otherwise the cancel button.
    requestAnimationFrame(() => {
        const firstBox = document.querySelector('#attach-existing-list .attach-existing-checkbox');
        if (firstBox) {
            firstBox.focus();
        } else {
            document.getElementById('btn-attach-existing-cancel')?.focus();
        }
    });
}

function cancelAttachExistingPicker() {
    Modal.close('attach-existing-modal');
    _attachExistingKind = null;
    _attachExistingSelected.clear();
    const listEl = document.getElementById('attach-existing-list');
    if (listEl) listEl.innerHTML = '';
    updateAttachExistingConfirmButton();
}

async function confirmAttachExistingSelected() {
    const kind = _attachExistingKind;
    if (!kind) return;
    const ids = [..._attachExistingSelected];
    if (!ids.length) return;

    // Autosave-then-attach: materialise an entry id if needed.
    if (!EntryState.currentEntry?.id) {
        try {
            await saveEntryAsDraft(true);
        } catch (err) {
            console.error('[attach-existing] autosave before attach failed:', err);
            Toast.error('Save Failed', 'Could not save the draft before attaching.');
            return;
        }
        if (!EntryState.currentEntry?.id) {
            Toast.error('Save Failed', 'Entry id was not assigned after save.');
            return;
        }
    }
    const entryId = EntryState.currentEntry.id;

    const failures = [];
    for (const id of ids) {
        try {
            if (kind === 'notes') {
                await api.attachExistingNoteToEntry(id, entryId);
            } else {
                await api.attachExistingMediaToEntry(id, entryId);
            }
        } catch (err) {
            console.error('[attach-existing] attach failed for id', id, err);
            failures.push({ id, error: err.message || String(err) });
        }
    }

    Modal.close('attach-existing-modal');
    _attachExistingKind = null;
    _attachExistingSelected.clear();

    const successCount = ids.length - failures.length;
    if (successCount > 0) {
        const noun = kind === 'notes' ? 'note' : 'image';
        Toast.success(
            'Attached',
            `${successCount} ${noun}${successCount === 1 ? '' : 's'} attached to this entry.`
        );
    }
    if (failures.length) {
        Toast.error(
            'Attach Failed',
            `${failures.length} item${failures.length === 1 ? '' : 's'} could not be attached.`
        );
    }

    await refreshAfterAttach(kind, entryId);
    // Re-poll to refresh both header button states (now fewer candidates).
    scheduleRefreshAttachCandidates();
}

function _wireAttachExistingHandlers() {
    if (_attachExistingHandlersWired) return;
    const confirmBtn = document.getElementById('btn-attach-existing-confirm');
    const cancelBtn = document.getElementById('btn-attach-existing-cancel');
    const backdrop = document.getElementById('attach-existing-modal');
    if (!confirmBtn || !cancelBtn || !backdrop) return;

    confirmBtn.addEventListener('click', () => {
        confirmAttachExistingSelected().catch(err => {
            console.error('[attach-existing] confirm failed:', err);
        });
    });
    cancelBtn.addEventListener('click', cancelAttachExistingPicker);

    // Backdrop click → cancel (but not clicks inside the modal itself).
    backdrop.addEventListener('click', (ev) => {
        if (ev.target === backdrop) cancelAttachExistingPicker();
    });

    // Escape → cancel when modal is open.
    document.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Escape') return;
        if (!backdrop.classList.contains('active')) return;
        cancelAttachExistingPicker();
    });

    _attachExistingHandlersWired = true;
}

/**
 * Sync current entry subjects to MediaUpload component
 * Called when subjects are added or removed
 */
function syncMediaUploadSubjects() {
    if (!EntryState.mediaUpload) return;

    // Combine primary and secondary subjects
    const allSubjects = [
        ...EntryState.formData.primarySubjects,
        ...EntryState.formData.secondarySubjects
    ];

    EntryState.mediaUpload.setEntrySubjects(allSubjects);
}

function renderSubjectChips(containerId, subjects, type) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = subjects.map(subject => {
        const chipMarkup = `
            <div class="chip ${type}" data-testid="entry-form-subject-${type}-chip-${subject.id}">
                <span>${escapeHtml(subject.name)}</span>
                <button type="button" class="chip-remove" onclick="removeSubject(${subject.id}, '${type}')" title="Remove">×</button>
            </div>
        `;
        // Tag context pill: only on primary subjects with ≥2 parents.
        // The pill markup is rendered as a placeholder slot; the actual
        // pill is mounted by renderTagContextPill once the parent-edges
        // fetch resolves. POLYHIERARCHY_MIGRATION §7.3.
        if (type !== 'primary') {
            return `<div class="chip-with-context">${chipMarkup}</div>`;
        }
        return `
            <div class="chip-with-context" data-subject-id="${subject.id}">
                ${chipMarkup}
                <div class="tag-context-pill-slot" data-subject-id="${subject.id}"></div>
            </div>
        `;
    }).join('');

    // For primary subjects, hydrate the tag-context pill from cache
    // (or fire off the fetch and re-render). Secondary subjects skip
    // this entirely — per §7.3 the pill is a primary-tag concept.
    if (type === 'primary') {
        subjects.forEach(subject => {
            mountTagContextPill(subject.id);
        });
    }
}

// =========================================================================
// Tag Context Pill — POLYHIERARCHY_MIGRATION §7.3
// Renders below each primary subject chip when the leaf has ≥2 parent
// edges. Lets the user disambiguate which parent context the entry
// rolls up through. Persisted via api.setPrimaryParentForEntry on save.
// =========================================================================

/**
 * Fetch and cache the parent edges for a subject. Returns the cached
 * array immediately if available; otherwise fires off the request and
 * triggers a re-mount when it resolves. Returns null on the first call
 * for a given subject (caller should expect a delayed render).
 */
async function ensureSubjectParentEdges(subjectId) {
    if (EntryState.subjectParentEdges[subjectId]) {
        return EntryState.subjectParentEdges[subjectId];
    }
    try {
        const edges = await api.getEdgesForChild(subjectId);
        EntryState.subjectParentEdges[subjectId] = Array.isArray(edges) ? edges : [];
        return EntryState.subjectParentEdges[subjectId];
    } catch (err) {
        console.warn('[tag-context-pill] getEdgesForChild failed for', subjectId, err);
        EntryState.subjectParentEdges[subjectId] = [];
        return EntryState.subjectParentEdges[subjectId];
    }
}

/**
 * Render the pill markup into the placeholder slot for a subject.
 * Triggers an async parent-edges fetch if not yet cached.
 */
function mountTagContextPill(subjectId) {
    const slot = document.querySelector(
        `.tag-context-pill-slot[data-subject-id="${subjectId}"]`
    );
    if (!slot) return;

    const cached = EntryState.subjectParentEdges[subjectId];
    if (cached === undefined) {
        // Fire the fetch; re-mount when it resolves.
        ensureSubjectParentEdges(subjectId).then(() => mountTagContextPill(subjectId));
        return;
    }

    // Single-parent (or orphan) subject — pill is not applicable.
    if (!cached || cached.length < 2) {
        slot.innerHTML = '';
        return;
    }

    // Determine the active parent — user's explicit choice if set,
    // otherwise the canonical primary edge (first row, per
    // getEdgesForChild ordering "is_primary DESC, parent_id ASC").
    const explicitChoice = EntryState.formData.primaryParentChoices[subjectId];
    const activeParentId = explicitChoice ?? cached[0].parent_id;
    const activeEdge = cached.find(e => e.parent_id === activeParentId) || cached[0];
    const isExplicit = explicitChoice !== undefined && explicitChoice !== null;

    slot.innerHTML = `
        <button type="button"
                class="tag-context-pill"
                data-subject-id="${subjectId}"
                data-explicit="${isExplicit}"
                data-testid="entry-form-tag-context-pill-${subjectId}"
                title="Click to change tag context — POLYHIERARCHY_MIGRATION §7.3"
                onclick="openTagContextMenu(${subjectId}, event)">
            <span class="tag-context-pill-label">Tag context:</span>
            <span class="tag-context-pill-value">${escapeHtml(activeEdge.parent_name)}</span>
            <span class="tag-context-pill-caret">▾</span>
        </button>
    `;
}

/**
 * Toggle the parent-picker menu for a subject's pill. Closes any other
 * open menu first so only one is visible at a time.
 */
function openTagContextMenu(subjectId, event) {
    if (event) {
        event.stopPropagation();
    }
    // Toggle: if this subject's menu is already open, close and bail.
    const existingMenu = document.querySelector(
        `.tag-context-menu[data-subject-id="${subjectId}"]`
    );
    closeAllTagContextMenus();
    if (existingMenu) return;

    const slot = document.querySelector(
        `.tag-context-pill-slot[data-subject-id="${subjectId}"]`
    );
    if (!slot) return;

    const edges = EntryState.subjectParentEdges[subjectId] || [];
    if (edges.length < 2) return;

    const explicitChoice = EntryState.formData.primaryParentChoices[subjectId];
    const activeParentId = explicitChoice ?? edges[0].parent_id;

    const items = edges.map(edge => {
        const checked = edge.parent_id === activeParentId;
        const primaryBadge = edge.is_primary
            ? '<span class="tag-context-menu-item-check" aria-hidden="true">✓</span>'
            : '<span class="tag-context-menu-item-check" aria-hidden="true">✓</span>';
        return `
            <button type="button"
                    class="tag-context-menu-item"
                    role="menuitemradio"
                    aria-checked="${checked}"
                    data-testid="entry-form-tag-context-option-${subjectId}-${edge.parent_id}"
                    onclick="selectTagContext(${subjectId}, ${edge.parent_id}, event)">
                <span>${escapeHtml(edge.parent_name)}${edge.is_primary ? ' <span style="opacity:0.6;font-weight:400;">(default)</span>' : ''}</span>
                ${primaryBadge}
            </button>
        `;
    }).join('');

    const menu = document.createElement('div');
    menu.className = 'tag-context-menu';
    menu.setAttribute('role', 'menu');
    menu.dataset.subjectId = String(subjectId);
    menu.dataset.testid = `entry-form-tag-context-menu-${subjectId}`;
    menu.innerHTML = items;
    slot.appendChild(menu);

    const pill = slot.querySelector('.tag-context-pill');
    if (pill) pill.classList.add('open');

    // Outside click closes the menu. One-shot listener.
    setTimeout(() => {
        document.addEventListener('click', closeAllTagContextMenus, { once: true });
    }, 0);
}

function closeAllTagContextMenus() {
    document.querySelectorAll('.tag-context-menu').forEach(m => m.remove());
    document.querySelectorAll('.tag-context-pill.open').forEach(p => {
        p.classList.remove('open');
    });
}

/**
 * Apply a parent-context choice for a subject.
 *
 * Policy: every multi-parent subject on an entry gets a non-NULL
 * primary_parent_id. The pill's default is the canonical primary
 * (first edge from get_edges_for_child); picking it explicitly is
 * still a real write, not a "no choice" sentinel. This makes
 * disambiguation the norm and lets the deep-dive selector behave as
 * a genuine filter rather than a no-op.
 */
function selectTagContext(subjectId, parentId, event) {
    if (event) event.stopPropagation();
    EntryState.formData.primaryParentChoices[subjectId] = parentId;
    delete EntryState.primaryParentSynced[subjectId];

    closeAllTagContextMenus();
    mountTagContextPill(subjectId);
    markDirty();
}

/**
 * Push the per-subject parent-context choices to the DB. Called by the
 * existing save path once an entry_id is known. Idempotent — only fires
 * writes when the cached "last synced" value differs from the current
 * choice, so re-saves with no pill changes do not hammer the bridge.
 *
 * Multi-parent subjects always get a non-NULL write (canonical primary
 * if the user didn't touch the pill). Single-parent subjects are
 * skipped — NULL is unambiguous there.
 */
async function syncTagContextChoices(entryId) {
    if (!entryId) return;
    const subjects = EntryState.formData.primarySubjects;
    for (const subject of subjects) {
        // Single-parent subjects don't render a pill and don't need
        // disambiguation; leave their primary_parent_id at NULL.
        const edges = await ensureSubjectParentEdges(subject.id);
        if (!edges || edges.length < 2) continue;

        const explicit = EntryState.formData.primaryParentChoices[subject.id];
        const desired = explicit !== undefined
            ? explicit
            : edges[0].parent_id;  // canonical primary default
        const lastSynced = EntryState.primaryParentSynced[subject.id];
        if (lastSynced === desired) continue;
        try {
            await api.setPrimaryParentForEntry(entryId, subject.id, desired);
            EntryState.primaryParentSynced[subject.id] = desired;
        } catch (err) {
            console.error(
                '[tag-context-pill] setPrimaryParentForEntry failed',
                { entryId, subjectId: subject.id, desired },
                err,
            );
        }
    }
}

// =========================================================================
// Quick Add Subject (Inline Hierarchy Management)
// =========================================================================

/**
 * Initialize quick add subject controls
 */
function initQuickAddSubject() {
    const showBtn = document.getElementById('btn-quick-add-subject');
    const modal = document.getElementById('quick-add-subject-modal');
    const closeBtn = document.getElementById('quick-add-close');
    const cancelBtn = document.getElementById('quick-add-cancel');
    const saveBtn = document.getElementById('quick-add-save');
    const nameInput = document.getElementById('quick-add-name');

    if (!showBtn || !modal) return;

    // Initialize parent search field
    initQuickAddParentSearch();

    showBtn.addEventListener('click', () => {
        resetQuickAddParentSearch();
        modal.style.display = 'block';
        nameInput?.focus();
    });

    closeBtn?.addEventListener('click', closeQuickAddModal);
    cancelBtn?.addEventListener('click', closeQuickAddModal);

    saveBtn?.addEventListener('click', handleQuickAddSave);

    // Enter key in name input triggers save
    nameInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handleQuickAddSave();
        }
    });

    // Show/hide alias type selector when aliases are entered
    const aliasInput = document.getElementById('quick-add-aliases');
    const aliasTypeGroup = document.getElementById('quick-add-alias-type-group');
    if (aliasInput && aliasTypeGroup) {
        aliasInput.addEventListener('input', () => {
            aliasTypeGroup.style.display = aliasInput.value.trim() ? 'block' : 'none';
        });
    }
}

/**
 * Initialize the parent subject search field with fuzzy search
 */
function initQuickAddParentSearch() {
    const input = document.getElementById('quick-add-parent-search');
    const dropdown = document.getElementById('quick-add-parent-dropdown');
    const hiddenInput = document.getElementById('quick-add-parent');

    if (!input || !dropdown) return;

    const searchParents = (query) => {
        if (!EntryState.subjects || EntryState.subjects.length === 0) {
            renderParentDropdown(dropdown, [], query);
            return;
        }

        let results;
        if (!query || query.length < 1) {
            // Show all subjects sorted by path when no query
            results = [...EntryState.subjects].sort((a, b) => {
                const pathA = a.path || a.name;
                const pathB = b.path || b.name;
                return pathA.localeCompare(pathB);
            });
        } else if (typeof fuzzySearch !== 'undefined' && fuzzySearch.isReady()) {
            // Use fuzzy search
            results = fuzzySearch.searchSubjects(query, 15);
        } else {
            // Simple filter fallback
            const lowerQuery = query.toLowerCase();
            results = EntryState.subjects.filter(s =>
                s.name.toLowerCase().includes(lowerQuery) ||
                (s.path && s.path.toLowerCase().includes(lowerQuery))
            );
        }

        renderParentDropdown(dropdown, results, query);
    };

    input.addEventListener('input', (e) => {
        searchParents(e.target.value);
    });

    input.addEventListener('focus', () => {
        searchParents(input.value);
    });

    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.remove('visible');
        }
    });

    // Attach keyboard navigation
    keyboardControllers.quickAddParent = attachDropdownKeyboard('quick-add-parent-search', 'quick-add-parent-dropdown', {
        itemSelector: '.subject-option'
    });
}

/**
 * Render parent subject dropdown
 */
function renderParentDropdown(dropdown, results, query = '') {
    const highlightFn = typeof fuzzySearch !== 'undefined'
        ? (text) => fuzzySearch.highlightMatches(text, query)
        : (text) => escapeHtml(text);

    // Always include "Root (Top Level)" option at the top
    let optionsHtml = `
        <div class="subject-option root-option"
             role="option"
             data-id=""
             data-name="Root (Top Level)"
             data-path=""
             onclick="selectQuickAddParent('', 'Root (Top Level)')">
            <span class="root-icon">📍</span>
            <div class="subject-option-content">
                <div class="subject-option-name">Root (Top Level)</div>
                <div class="subject-option-path">No parent - top-level subject</div>
            </div>
        </div>
    `;

    if (results && results.length > 0) {
        optionsHtml += results.map((subject, index) => `
            <div class="subject-option"
                 role="option"
                 data-id="${subject.id}"
                 data-name="${escapeHtml(subject.name)}"
                 data-path="${escapeHtml(subject.path || '')}"
                 onclick="selectQuickAddParent(${subject.id}, '${escapeHtml(subject.name).replace(/'/g, "&apos;")}')">
                <div class="subject-option-content">
                    <div class="subject-option-name">${highlightFn(subject.name)}</div>
                    <div class="subject-option-path">${escapeHtml(subject.path || '')}</div>
                </div>
            </div>
        `).join('');
    }

    dropdown.innerHTML = `<div class="dropdown-results" role="listbox">${optionsHtml}</div>`;
    dropdown.classList.add('visible');
}

/**
 * Select a parent from the dropdown
 */
function selectQuickAddParent(id, name) {
    const input = document.getElementById('quick-add-parent-search');
    const hiddenInput = document.getElementById('quick-add-parent');
    const dropdown = document.getElementById('quick-add-parent-dropdown');

    if (input) input.value = name;
    if (hiddenInput) hiddenInput.value = id;
    if (dropdown) dropdown.classList.remove('visible');
}

/**
 * Reset parent search to default state
 */
function resetQuickAddParentSearch() {
    const input = document.getElementById('quick-add-parent-search');
    const hiddenInput = document.getElementById('quick-add-parent');
    const dropdown = document.getElementById('quick-add-parent-dropdown');

    if (input) input.value = '';
    if (hiddenInput) hiddenInput.value = '';
    if (dropdown) dropdown.classList.remove('visible');
}

/**
 * Close the quick add modal
 */
function closeQuickAddModal() {
    const modal = document.getElementById('quick-add-subject-modal');
    if (modal) {
        modal.style.display = 'none';
        document.getElementById('quick-add-name').value = '';
        const aliasField = document.getElementById('quick-add-aliases');
        if (aliasField) aliasField.value = '';
        const aliasTypeGroup = document.getElementById('quick-add-alias-type-group');
        if (aliasTypeGroup) aliasTypeGroup.style.display = 'none';
        const aliasTypeSelect = document.getElementById('quick-add-alias-type');
        if (aliasTypeSelect) aliasTypeSelect.value = 'alternate_name';
        resetQuickAddParentSearch();
    }
}

/**
 * Handle quick add save button
 */
async function handleQuickAddSave() {
    const nameInput = document.getElementById('quick-add-name');
    const parentSelect = document.getElementById('quick-add-parent');
    const saveBtn = document.getElementById('quick-add-save');

    const name = nameInput?.value.trim();
    const parentId = parentSelect?.value ? parseInt(parentSelect.value) : null;

    if (!name) {
        Toast.error('Required', 'Please enter a subject name');
        nameInput?.focus();
        return;
    }

    if (!EntryState.session?.exam_context_id) {
        Toast.error('Error', 'No exam context available');
        return;
    }

    // Disable button while saving
    if (saveBtn) saveBtn.disabled = true;

    try {
        const nodeData = {
            exam_context_id: EntryState.session.exam_context_id,
            name: name,
            parent_id: parentId
        };

        const newSubject = await api.createSubjectNode(nodeData);

        if (newSubject && newSubject.id) {
            // Create aliases if provided
            const aliasInput = document.getElementById('quick-add-aliases');
            const aliasTypeSelect = document.getElementById('quick-add-alias-type');
            const aliasText = aliasInput?.value.trim();
            if (aliasText) {
                const aliasNames = aliasText.split(',').map(a => a.trim()).filter(a => a);
                const aliasType = aliasTypeSelect?.value || 'alternate_name';
                for (const aliasName of aliasNames) {
                    try {
                        await api.createSubjectAlias({
                            subject_node_id: newSubject.id,
                            exam_context: EntryState.examContext?.exam_name || EntryState.session.exam_name,
                            alias_name: aliasName,
                            alias_type: aliasType
                        });
                    } catch (aliasErr) {
                        console.warn('Failed to create alias:', aliasName, aliasErr);
                    }
                }
            }

            // Build full path for the new subject
            let subjectPath = newSubject.name;
            if (parentId) {
                const parent = EntryState.subjects.find(s => s.id === parentId);
                if (parent && parent.path) {
                    subjectPath = parent.path + ' > ' + newSubject.name;
                }
            }
            newSubject.path = subjectPath;

            // Attach aliases string for fuzzy search (if any were created)
            if (aliasText) {
                newSubject.aliasesString = aliasText;
            }

            // Add to subjects list and refresh fuzzy search index
            EntryState.subjects.push(newSubject);
            if (typeof fuzzySearch !== 'undefined' && fuzzySearch.refreshSubjects) {
                fuzzySearch.refreshSubjects(EntryState.subjects);
            }

            // Select the new subject as primary
            selectSubject(newSubject.id, newSubject.name, newSubject.path || newSubject.name, 'primary');

            closeQuickAddModal();
            Toast.success('Subject Created', `"${name}" added and selected`);
        } else {
            Toast.error('Error', 'Failed to create subject');
        }
    } catch (error) {
        console.error('Error creating subject:', error);
        Toast.error('Error', error.message || 'Failed to create subject');
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

// =========================================================================
// Tag Picker (Phase 4 Stage 4 - Fuzzy Search Enhancement)
// =========================================================================

async function loadTagHierarchy() {
    if (!EntryState.session) return;
    
    try {
        const examContext = EntryState.examContext?.exam_name || EntryState.session.exam_name;
        console.log('🏷️ Loading tag hierarchy for:', examContext);
        let hierarchy = await api.getTagHierarchy(examContext);
        console.log('📋 Tag hierarchy received:', hierarchy);
        
        // If no tags exist, try to seed defaults first
        if (!hierarchy || hierarchy.length === 0) {
            console.log('🌱 No tags found, attempting to seed defaults...');
            try {
                await api.seedDefaultTags(examContext);
                hierarchy = await api.getTagHierarchy(examContext);
                console.log('📋 Tag hierarchy after seeding:', hierarchy);
            } catch (seedErr) {
                console.warn('⚠️ Seeding failed:', seedErr);
            }
        }
        
        EntryState.tagHierarchy = hierarchy || [];
        
        // Initialize tag fuzzy search index
        if (typeof fuzzySearch !== 'undefined') {
            console.log('🔄 Initializing fuzzy search tag index...');
            fuzzySearch.initTagIndex(EntryState.tagHierarchy);
            console.log('✅ Tag index ready, tags:', fuzzySearch.tags?.length || 0);
        }
        
        renderTagHierarchy();
        // Re-render chips so tooltips pick up descriptions when the form was
        // hydrated (edit mode) before the hierarchy finished loading
        renderTagChips();
    } catch (error) {
        console.error('Error loading tag hierarchy:', error);
        EntryState.tagHierarchy = [];
        renderTagHierarchy();
    }
}

/**
 * Initialize tag search with fuzzy matching and keyboard navigation
 */
function initTagSearch() {
    const input = document.getElementById('tag-search');
    const dropdown = document.getElementById('tag-dropdown');
    
    if (!input || !dropdown) return;
    
    const searchTags = (query) => {
        if (!query || query.length < 2) {
            dropdown.classList.remove('visible');
            return;
        }
        
        console.log('🔍 Searching tags for:', query);
        
        // Use fuzzy search if available and tag index is ready
        if (typeof fuzzySearch !== 'undefined' && fuzzySearch.tagIndex) {
            console.log('✅ Using Fuse.js tag search');
            const results = fuzzySearch.searchTags(query, 10);
            console.log('📋 Fuzzy results:', results);
            renderTagDropdown(dropdown, results, query);
        } else {
            // Fallback to simple filter on flattened tags
            console.log('⚠️ Falling back to simple filter');
            const allTags = [];
            EntryState.tagHierarchy.forEach(group => {
                (group.children || []).forEach(tag => {
                    allTags.push({
                        id: tag.id,
                        name: tag.name,
                        groupName: group.name,
                        color: tag.color || group.color,
                        description: tag.description || ''
                    });
                });
            });
            console.log('📋 All flattened tags:', allTags);
            const filtered = allTags.filter(t => 
                t.name.toLowerCase().includes(query.toLowerCase()) ||
                t.groupName.toLowerCase().includes(query.toLowerCase())
            ).slice(0, 10);
            console.log('📋 Filtered results:', filtered);
            renderTagDropdown(dropdown, filtered, query);
        }
    };
    
    input.addEventListener('input', (e) => {
        searchTags(e.target.value);
    });
    
    input.addEventListener('focus', () => {
        if (input.value.length >= 2) {
            searchTags(input.value);
        }
    });
    
    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.remove('visible');
        }
    });
    
    // Attach keyboard navigation
    keyboardControllers.tags = attachDropdownKeyboard('tag-search', 'tag-dropdown', {
        itemSelector: '.tag-option'
    });
}

/**
 * Render tag dropdown with fuzzy search results
 * Includes inline tag creation option when no exact match
 */
function renderTagDropdown(dropdown, results, query = '') {
    const hintDismissed = localStorage.getItem('wimi_keyboard_hint_dismissed') === 'true';
    
    // Check if we have an exact match
    const trimmedQuery = query.trim();
    const hasExactMatch = results.some(t => 
        t.name.toLowerCase() === trimmedQuery.toLowerCase()
    );
    
    // Get tag groups for the create option
    const tagGroups = EntryState.tagHierarchy || [];
    
    if (!results || results.length === 0) {
        // No results - show create option only
        dropdown.innerHTML = `
            <div class="dropdown-empty">
                <span class="dropdown-empty-icon">🏷️</span>
                <span>No tags found for "${escapeHtml(query)}"</span>
            </div>
            ${trimmedQuery.length >= 2 ? renderCreateTagOption(trimmedQuery, tagGroups) : ''}
            ${!hintDismissed ? `
                <div class="dropdown-hint">
                    <span>💡 ↑↓ navigate • Enter select • Esc close</span>
                    <button type="button" class="dropdown-hint-dismiss" onclick="dismissKeyboardHint(event)" title="Dismiss">×</button>
                </div>
            ` : ''}
        `;
    } else {
        const highlightFn = typeof fuzzySearch !== 'undefined' 
            ? (text) => fuzzySearch.highlightMatches(text, query)
            : (text) => escapeHtml(text);
        
        dropdown.innerHTML = `
            <div class="dropdown-results" role="listbox">
                ${results.map((tag, index) => {
                    const isBestMatch = tag.isBestMatch || (index === 0 && tag.score < 0.3);
                    const isSelected = isTagSelected(tag.id);
                    return `
                        <div class="tag-option ${isBestMatch ? 'best-match' : ''} ${isSelected ? 'already-selected' : ''}"
                             role="option"
                             id="tag-option-${index}"
                             ${tag.description ? `title="${escapeHtml(tag.description)}"` : ''}
                             data-id="${tag.id}"
                             data-name="${escapeHtml(tag.name)}"
                             data-color="${tag.color || '#6B7280'}"
                             data-index="${index}"
                             data-testid="entry-form-tags-option-${tag.id}"
                             aria-selected="${isSelected}"
                             onclick="selectTagFromDropdown(${tag.id}, '${escapeHtml(tag.name).replace(/'/g, "&apos;")}', '${tag.color || '#6B7280'}')">
                            ${isBestMatch ? '<span class="best-match-icon" title="Best match">🎯</span>' : ''}
                            <span class="tag-option-color" style="background: ${tag.color || '#6B7280'}"></span>
                            <div class="tag-option-content">
                                <div class="tag-option-name">${highlightFn(tag.name)}</div>
                                ${tag.groupName ? `<div class="tag-option-group">${escapeHtml(tag.groupName)}</div>` : ''}
                            </div>
                            ${isSelected ? '<span class="tag-option-check">✓</span>' : ''}
                        </div>
                    `;
                }).join('')}
            </div>
            ${!hasExactMatch && trimmedQuery.length >= 2 ? renderCreateTagOption(trimmedQuery, tagGroups) : ''}
            ${!hintDismissed ? `
                <div class="dropdown-hint">
                    <span>💡 ↑↓ navigate • Enter select • Esc close</span>
                    <button type="button" class="dropdown-hint-dismiss" onclick="dismissKeyboardHint(event)" title="Dismiss">×</button>
                </div>
            ` : ''}
        `;
    }
    dropdown.classList.add('visible');
}

/**
 * Render the "Create new tag" option with group selection
 */
function renderCreateTagOption(tagName, tagGroups) {
    if (!tagGroups || tagGroups.length === 0) {
        return '';
    }
    
    // Auto-suggest the first group as default
    const defaultGroupId = tagGroups[0]?.id || '';
    
    return `
        <div class="dropdown-create-section">
            <div class="dropdown-create-header">
                <span class="dropdown-create-icon">➕</span>
                <span>Create "<strong>${escapeHtml(tagName)}</strong>"</span>
            </div>
            <div class="dropdown-create-groups">
                ${tagGroups.map((group, index) => `
                    <label class="create-group-option ${index === 0 ? 'selected' : ''}" data-group-id="${group.id}">
                        <input type="radio" name="create-tag-group" value="${group.id}" 
                               ${index === 0 ? 'checked' : ''}
                               onchange="updateSelectedCreateGroup(${group.id})">
                        <span class="create-group-color" style="background: ${group.color || '#6B7280'}"></span>
                        <span class="create-group-name">${escapeHtml(group.name)}</span>
                    </label>
                `).join('')}
            </div>
            <input type="text" class="form-input dropdown-create-definition"
                   id="create-tag-definition"
                   placeholder="Definition (optional) — shown as a tooltip"
                   autocomplete="off"
                   data-testid="entry-form-create-tag-definition-input">
            <button type="button" class="btn btn-sm btn-primary dropdown-create-btn"
                    onclick="createTagInline('${escapeHtml(tagName).replace(/'/g, "&apos;")}')">
                Create Tag
            </button>
        </div>
    `;
}

/**
 * Update the visual selection state of create group options
 */
function updateSelectedCreateGroup(groupId) {
    document.querySelectorAll('.create-group-option').forEach(opt => {
        opt.classList.toggle('selected', parseInt(opt.dataset.groupId) === groupId);
    });
}

/**
 * Create a new tag inline and add it to the selection
 */
async function createTagInline(tagName) {
    const selectedRadio = document.querySelector('input[name="create-tag-group"]:checked');
    if (!selectedRadio) {
        Toast.warning('Select a Group', 'Please select a group for the new tag.');
        return;
    }
    
    const groupId = parseInt(selectedRadio.value);
    const group = EntryState.tagHierarchy.find(g => g.id === groupId);
    
    if (!group) {
        Toast.error('Invalid Group', 'Could not find the selected group.');
        return;
    }
    
    const createBtn = document.querySelector('.dropdown-create-btn');
    if (createBtn) {
        createBtn.disabled = true;
        createBtn.innerHTML = '<span class="spinner spinner-sm"></span> Creating...';
    }
    
    try {
        const examContext = EntryState.examContext?.exam_name || '';
        const definitionInput = document.querySelector('[data-testid="entry-form-create-tag-definition-input"]');
        const definition = definitionInput ? definitionInput.value.trim() : '';
        const newTag = await api.createTagInGroup(examContext, tagName, groupId, definition);
        const newDescription = newTag.description || definition || '';

        // Add the new tag to our local hierarchy
        if (group.children) {
            group.children.push({
                id: newTag.id,
                name: tagName,
                color: group.color,
                is_group: false,
                description: newDescription || null,
                usage_count: 0
            });
        }

        // Refresh the fuzzy search index
        if (typeof fuzzySearch !== 'undefined') {
            fuzzySearch.initTagIndex(EntryState.tagHierarchy);
        }

        // Add the tag to the current selection
        EntryState.formData.tags.push({
            id: newTag.id,
            name: tagName,
            color: group.color || '#6B7280',
            description: newDescription
        });
        
        // Update UI
        renderTagHierarchy();
        renderTagChips();
        markDirty();
        
        // Close dropdown and clear input
        const dropdown = document.getElementById('tag-dropdown');
        const input = document.getElementById('tag-search');
        if (dropdown) dropdown.classList.remove('visible');
        if (input) input.value = '';
        
        Toast.success('Tag Created', `"${tagName}" added to ${group.name}`);
        
    } catch (error) {
        console.error('Error creating tag:', error);
        Toast.error('Creation Failed', error.message || 'Could not create the tag.');
    } finally {
        if (createBtn) {
            createBtn.disabled = false;
            createBtn.textContent = 'Create Tag';
        }
    }
}

/**
 * Select a tag from the dropdown
 */
function selectTagFromDropdown(id, name, color) {
    const dropdown = document.getElementById('tag-dropdown');
    const input = document.getElementById('tag-search');
    
    // Check if already selected - if so, remove it
    if (isTagSelected(id)) {
        removeTag(id);
    } else {
        // Add the tag
        EntryState.formData.tags.push({ id, name, color, description: getTagDescriptionById(id) });
        renderTagHierarchy();
        renderTagChips();
        markDirty();
    }
    
    // Clear input and hide dropdown
    if (input) input.value = '';
    if (dropdown) dropdown.classList.remove('visible');
}

/**
 * Find a tag or group node in the loaded hierarchy by id
 * @returns {{node: object, isGroup: boolean, group: object|null}|null}
 */
function findTagNodeById(tagId) {
    for (const group of (EntryState.tagHierarchy || [])) {
        if (group.id === tagId) {
            return { node: group, isGroup: true, group: null };
        }
        for (const child of (group.children || [])) {
            if (child.id === tagId) {
                return { node: child, isGroup: false, group };
            }
        }
    }
    return null;
}

/**
 * Look up a tag's description (definition) from the loaded hierarchy
 */
function getTagDescriptionById(tagId) {
    const found = findTagNodeById(tagId);
    return (found && found.node.description) || '';
}

function renderTagHierarchy() {
    const container = document.getElementById('tag-hierarchy');
    if (!container) return;

    if (!EntryState.tagHierarchy || EntryState.tagHierarchy.length === 0) {
        container.innerHTML = '<p class="form-help">No tags available. Tags will be created when you first use them.</p>';
        return;
    }

    container.innerHTML = EntryState.tagHierarchy.map(group => `
        <div class="tag-group">
            <div class="tag-group-header" ${group.description ? `title="${escapeHtml(group.description)}"` : ''}>
                <span class="tag-group-color" style="background: ${group.color || '#6B7280'}"></span>
                <span>${escapeHtml(group.name)}</span>
            </div>
            <div class="tag-group-items">
                ${(group.children || []).map(tag => `
                    <button type="button" class="tag-item ${isTagSelected(tag.id) ? 'selected' : ''}"
                            ${tag.description ? `title="${escapeHtml(tag.description)}"` : ''}
                            data-tag-id="${tag.id}" onclick="toggleTag(${tag.id}, '${escapeHtml(tag.name).replace(/'/g, "&apos;")}', '${tag.color || group.color}')">
                        ${escapeHtml(tag.name)}
                    </button>
                `).join('')}
            </div>
        </div>
    `).join('');
}

function isTagSelected(tagId) {
    return EntryState.formData.tags.some(t => t.id === tagId);
}

function toggleTag(id, name, color) {
    const index = EntryState.formData.tags.findIndex(t => t.id === id);
    
    if (index > -1) {
        // Remove tag
        EntryState.formData.tags.splice(index, 1);
    } else {
        // Add tag
        EntryState.formData.tags.push({ id, name, color, description: getTagDescriptionById(id) });
    }
    
    renderTagHierarchy();
    renderTagChips();
    markDirty();
}

function renderTagChips() {
    const container = document.getElementById('tags-chips');
    if (!container) return;
    
    container.innerHTML = EntryState.formData.tags.map(tag => {
        const description = tag.description || getTagDescriptionById(tag.id);
        return `
        <div class="chip tag" style="border-left: 3px solid ${tag.color || '#6B7280'}" ${description ? `title="${escapeHtml(description)}"` : ''} data-testid="entry-form-tags-chip-${tag.id}">
            <span>${escapeHtml(tag.name)}</span>
            <button type="button" class="chip-remove" onclick="removeTag(${tag.id})" title="Remove">×</button>
        </div>
    `;
    }).join('');
}

function removeTag(id) {
    const index = EntryState.formData.tags.findIndex(t => t.id === id);
    if (index > -1) {
        EntryState.formData.tags.splice(index, 1);
    }

    renderTagHierarchy();
    renderTagChips();
    markDirty();
}

// =========================================================================
// Error Type Management (Manage modal: definitions + delete)
// =========================================================================

// Original definition text per tag id, captured at render time for dirty checks
let manageTagOriginals = {};

// Tag pending deletion via the confirmation modal: { id, name, isGroup, usageCount }
let pendingDeleteTag = null;

/**
 * Open the "Manage error types" modal with fresh live usage counts
 */
async function openManageTagsModal() {
    await loadTagHierarchy();
    renderManageTagsModal();
    Modal.open('manage-tags-modal');
}

function closeManageTagsModal() {
    Modal.close('manage-tags-modal');
}

/**
 * Render the manage modal body from EntryState.tagHierarchy
 */
function renderManageTagsModal() {
    const container = document.getElementById('manage-tags-list');
    if (!container) return;

    manageTagOriginals = {};

    const hierarchy = EntryState.tagHierarchy || [];
    if (hierarchy.length === 0) {
        container.innerHTML = '<p class="form-help">No error types yet. Defaults are re-seeded the next time the picker loads.</p>';
        return;
    }

    const usageLabel = (count) => `${count} ${count === 1 ? 'entry' : 'entries'}`;

    container.innerHTML = hierarchy.map(group => {
        const children = group.children || [];
        const groupCount = group.usage_count || 0;
        const groupEmpty = children.length === 0;

        return `
        <div class="manage-tag-group">
            <div class="manage-tag-group-header" ${group.description ? `title="${escapeHtml(group.description)}"` : ''}>
                <span class="tag-group-color" style="background: ${group.color || '#6B7280'}"></span>
                <span class="manage-tag-group-name">${escapeHtml(group.name)}</span>
                <span class="manage-tag-usage" data-testid="manage-tag-usage-${group.id}">${usageLabel(groupCount)}</span>
                <button type="button" class="manage-tag-delete" data-testid="manage-tag-delete-${group.id}"
                        ${groupEmpty ? 'title="Delete this empty group"' : 'disabled title="Delete or move its types first"'}
                        onclick="confirmDeleteTag(${group.id})">🗑️</button>
            </div>
            <div class="manage-tag-rows">
                ${children.map(tag => {
                    const count = tag.usage_count || 0;
                    manageTagOriginals[tag.id] = tag.description || '';
                    return `
                <div class="manage-tag-row" data-tag-id="${tag.id}">
                    <div class="manage-tag-row-main">
                        <span class="tag-option-color" style="background: ${tag.color || group.color || '#6B7280'}"></span>
                        <span class="manage-tag-name">${escapeHtml(tag.name)}</span>
                        <span class="manage-tag-usage" data-testid="manage-tag-usage-${tag.id}">${usageLabel(count)}</span>
                        <button type="button" class="manage-tag-delete" data-testid="manage-tag-delete-${tag.id}"
                                title="Delete this error type"
                                onclick="confirmDeleteTag(${tag.id})">🗑️</button>
                    </div>
                    <div class="manage-tag-def">
                        <textarea class="manage-tag-def-input" rows="2"
                                  placeholder="Definition (optional) — shown as a tooltip in the picker"
                                  data-testid="manage-tag-def-${tag.id}"
                                  oninput="onTagDefinitionInput(${tag.id})">${escapeHtml(tag.description || '')}</textarea>
                        <button type="button" class="btn btn-sm btn-primary manage-tag-save"
                                data-testid="manage-tag-save-${tag.id}" hidden
                                onclick="saveTagDefinition(${tag.id})">Save</button>
                    </div>
                </div>`;
                }).join('')}
            </div>
        </div>`;
    }).join('');
}

/**
 * Show/hide the Save button when a definition textarea diverges from its saved value
 */
function onTagDefinitionInput(tagId) {
    const textarea = document.querySelector(`[data-testid="manage-tag-def-${tagId}"]`);
    const saveBtn = document.querySelector(`[data-testid="manage-tag-save-${tagId}"]`);
    if (!textarea || !saveBtn) return;
    const original = manageTagOriginals[tagId] || '';
    saveBtn.hidden = textarea.value.trim() === original.trim();
}

/**
 * Persist a tag definition and refresh every surface that shows it
 */
async function saveTagDefinition(tagId) {
    const textarea = document.querySelector(`[data-testid="manage-tag-def-${tagId}"]`);
    if (!textarea) return;
    const saveBtn = document.querySelector(`[data-testid="manage-tag-save-${tagId}"]`);
    const value = textarea.value.trim();

    if (saveBtn) saveBtn.disabled = true;

    try {
        const result = await api.updateTagDescription(tagId, value);
        const newDescription = (result && result.description) || '';

        // Update the in-memory hierarchy node
        const found = findTagNodeById(tagId);
        if (found) {
            found.node.description = newDescription || null;
        }

        // Sync any selected chip carrying this tag
        let chipsChanged = false;
        EntryState.formData.tags.forEach(t => {
            if (t.id === tagId) {
                t.description = newDescription;
                chipsChanged = true;
            }
        });

        // Reindex fuzzy search (flattened records carry description) and re-render
        if (typeof fuzzySearch !== 'undefined') {
            fuzzySearch.initTagIndex(EntryState.tagHierarchy);
        }
        renderTagHierarchy();
        if (chipsChanged) renderTagChips();

        // Reset dirty state in the modal row
        manageTagOriginals[tagId] = newDescription;
        textarea.value = newDescription;
        if (saveBtn) saveBtn.hidden = true;

        const tagName = found ? found.node.name : 'error type';
        Toast.success('Definition Saved', `Updated "${tagName}"`);
    } catch (error) {
        console.error('Error saving tag definition:', error);
        Toast.error('Save Failed', error.message || 'Could not save the definition.');
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

/**
 * Open the delete confirmation modal, filling in the live usage line
 */
function confirmDeleteTag(tagId) {
    const found = findTagNodeById(tagId);
    if (!found) return;

    const count = found.node.usage_count || 0;
    pendingDeleteTag = {
        id: tagId,
        name: found.node.name,
        isGroup: found.isGroup,
        usageCount: count
    };

    const nameEl = document.getElementById('delete-tag-modal-name');
    if (nameEl) {
        nameEl.textContent = found.isGroup
            ? `Delete the group "${found.node.name}"?`
            : `Delete "${found.node.name}"?`;
    }

    const usageEl = document.getElementById('delete-tag-modal-usage');
    if (usageEl) {
        usageEl.textContent = count > 0
            ? `Used by ${count} ${count === 1 ? 'entry' : 'entries'}. Deleting removes this tag from those entries and from analytics. This cannot be undone.`
            : 'Not used by any entries. This cannot be undone.';
    }

    Modal.open('delete-tag-modal');
}

/**
 * Close the delete confirmation, keeping the manage modal's scroll lock intact
 */
function closeDeleteTagModal() {
    Modal.close('delete-tag-modal');
    const manageModal = document.getElementById('manage-tags-modal');
    if (manageModal && manageModal.classList.contains('active')) {
        document.body.style.overflow = 'hidden';
    }
}

function cancelDeleteTag() {
    pendingDeleteTag = null;
    closeDeleteTagModal();
}

/**
 * Hard-delete the pending tag/group, then refresh chips, picker, and modal
 */
async function executeDeleteTag() {
    if (!pendingDeleteTag) return;
    const { id, name, isGroup } = pendingDeleteTag;

    const confirmBtn = document.getElementById('delete-tag-confirm');
    if (confirmBtn) confirmBtn.disabled = true;

    try {
        const result = await api.deleteTag(id);
        const affected = (result && result.affected_entries) || 0;

        if (isGroup) {
            Toast.success('Group Deleted', `Removed "${name}"`);
        } else {
            Toast.success('Error Type Deleted', `Removed "${name}" (untagged ${affected} ${affected === 1 ? 'entry' : 'entries'})`);
        }

        // Prune from the current selection if present
        const index = EntryState.formData.tags.findIndex(t => t.id === id);
        if (index > -1) {
            EntryState.formData.tags.splice(index, 1);
            renderTagChips();
            markDirty();
        }

        pendingDeleteTag = null;
        closeDeleteTagModal();

        // Refresh hierarchy (re-renders browse-all + reindexes Fuse) and the modal in place
        await loadTagHierarchy();
        renderManageTagsModal();
    } catch (error) {
        // e.g. stale UI: group became non-empty — bridge returns a user-facing message
        console.error('Error deleting tag:', error);
        Toast.error('Delete Failed', error.message || 'Could not delete this error type.');
        pendingDeleteTag = null;
        closeDeleteTagModal();
        await loadTagHierarchy();
        renderManageTagsModal();
    } finally {
        if (confirmBtn) confirmBtn.disabled = false;
    }
}

// =========================================================================
// Form Data Collection & Validation
// =========================================================================

function collectFormData() {
    EntryState.formData.questionId = document.getElementById('question-id')?.value || '';
    EntryState.formData.userAnswer = document.getElementById('user-answer')?.value || '';
    EntryState.formData.correctAnswer = document.getElementById('correct-answer')?.value || '';
    EntryState.formData.perceivedDifficulty = document.getElementById('perceived-difficulty')?.value
        ? parseInt(document.getElementById('perceived-difficulty').value) : null;

    const timeSpent = document.getElementById('time-spent')?.value;
    const timeUnit = document.getElementById('time-unit')?.value || 'minutes';
    EntryState.formData.timeUnit = timeUnit;

    if (timeSpent) {
        const seconds = timeUnit === 'minutes' ? parseInt(timeSpent) * 60 : parseInt(timeSpent);
        EntryState.formData.timeSpent = seconds;
    } else {
        EntryState.formData.timeSpent = null;
    }

    // Collect rich text content from editors
    if (EntryState.reflectionEditor) {
        const reflectionContent = EntryState.reflectionEditor.getContent();
        EntryState.formData.reflection = reflectionContent?.html || '';
        EntryState.formData.reflection_json = reflectionContent?.delta ? JSON.stringify(reflectionContent.delta) : null;
        console.log('[COLLECT] Reflection - html length:', EntryState.formData.reflection?.length, 'json:', EntryState.formData.reflection_json ? 'present' : 'null');
    }

    if (EntryState.explanationEditor) {
        const explanationContent = EntryState.explanationEditor.getContent();
        EntryState.formData.explanation = explanationContent?.html || '';
        EntryState.formData.explanation_json = explanationContent?.delta ? JSON.stringify(explanationContent.delta) : null;
        console.log('[COLLECT] Explanation - html length:', EntryState.formData.explanation?.length, 'json:', EntryState.formData.explanation_json ? 'present' : 'null');
        if (EntryState.formData.explanation_json) {
            console.log('[COLLECT] Explanation JSON preview:', EntryState.formData.explanation_json.substring(0, 200));
        }
    }

    // Collect from multi-note editors
    EntryState.formData.notesList = EntryState.noteEditors.map(ne => {
        const content = ne.editor ? ne.editor.getContent() : null;
        return {
            id: ne.id || null,
            tempId: ne.tempId,
            content_html: content?.html || '',
            content_json: content?.delta ? JSON.stringify(content.delta) : null,
            linked_subject_ids: ne.linkedSubjectIds || [],
            attachment_count: typeof ne.attachmentCount === 'number' ? ne.attachmentCount : 1
        };
    });
    // Keep legacy notes field empty for new entries (migrated notes live in notesList)
    EntryState.formData.notes = '';
    EntryState.formData.notes_json = null;

    return EntryState.formData;
}

function validateForm() {
    const data = collectFormData();

    const hasUserAnswer = data.userAnswer.trim().length > 0;
    const hasCorrectAnswer = data.correctAnswer.trim().length > 0;
    const hasPrimarySubject = data.primarySubjects.length > 0;

    // Check rich text editors for content (they use isEmpty() method)
    const hasReflection = EntryState.reflectionEditor
        ? !EntryState.reflectionEditor.isEmpty()
        : data.reflection.trim().length > 0;
    const hasExplanation = EntryState.explanationEditor
        ? !EntryState.explanationEditor.isEmpty()
        : data.explanation.trim().length > 0;

    // Check if any images have unassigned subjects
    const hasUnassignedImages = EntryState.mediaUpload?.hasUnassignedMedia() || false;
    const allImagesHaveSubjects = !hasUnassignedImages;

    const isComplete = hasUserAnswer && hasCorrectAnswer && hasPrimarySubject && hasReflection && hasExplanation && allImagesHaveSubjects;
    
    // Determine if this is the last entry
    const totalEntries = EntryState.session?.total_incorrect || 0;
    const currentIndex = EntryState.currentEntryIndex;
    const isLastEntry = totalEntries > 0 && currentIndex >= totalEntries - 1;
    
    // Update save button state
    const saveBtn = document.getElementById('btn-save-next');
    if (saveBtn) {
        saveBtn.disabled = !isComplete;
        if (!isComplete) {
            // Provide specific message for unassigned images
            if (hasUnassignedImages) {
                saveBtn.textContent = 'Assign subjects to images';
            } else {
                saveBtn.textContent = 'Complete required fields';
            }
            saveBtn.classList.remove('btn-complete');
        } else if (isLastEntry) {
            saveBtn.textContent = 'Complete Review ✓';
            saveBtn.classList.add('btn-complete');
        } else {
            saveBtn.textContent = 'Save & Next →';
            saveBtn.classList.remove('btn-complete');
        }
    }
    
    // Update draft indicator
    const draftIndicator = document.getElementById('draft-indicator');
    if (draftIndicator) {
        draftIndicator.classList.toggle('hidden', isComplete);
    }
    
    // Update section indicators
    updateSectionIndicators();
    
    return isComplete;
}

function updateSectionIndicators() {
    const data = EntryState.formData;
    
    // Section A: Question Info
    const sectionA = document.getElementById('section-question-info');
    if (sectionA) {
        const hasContent = data.userAnswer || data.correctAnswer;
        const hasError = !data.userAnswer || !data.correctAnswer;
        sectionA.classList.toggle('has-content', hasContent && !hasError);
        sectionA.classList.toggle('has-error', hasError && (data.userAnswer || data.correctAnswer));
    }
    
    // Section B: Subjects
    const sectionB = document.getElementById('section-subjects');
    if (sectionB) {
        sectionB.classList.toggle('has-content', data.primarySubjects.length > 0);
        sectionB.classList.toggle('has-error', data.primarySubjects.length === 0);
    }
    
    // Section D: Reflection (uses rich text editor)
    const sectionD = document.getElementById('section-reflection');
    if (sectionD) {
        const hasReflection = EntryState.reflectionEditor
            ? !EntryState.reflectionEditor.isEmpty()
            : data.reflection.trim().length > 0;
        sectionD.classList.toggle('has-content', hasReflection);
        sectionD.classList.toggle('has-error', !hasReflection);
    }

    // Section E: Explanation (uses rich text editor)
    const sectionE = document.getElementById('section-explanation');
    if (sectionE) {
        const hasExplanation = EntryState.explanationEditor
            ? !EntryState.explanationEditor.isEmpty()
            : data.explanation.trim().length > 0;
        sectionE.classList.toggle('has-content', hasExplanation);
        sectionE.classList.toggle('has-error', !hasExplanation);
    }
}

// =========================================================================
// Dirty State & Auto-Save
// =========================================================================

function markDirty() {
    EntryState.isDirty = true;
    updateAutoSaveIndicator('unsaved');
}

function markClean() {
    EntryState.isDirty = false;
    EntryState.lastSaveTime = new Date();
    updateAutoSaveIndicator('saved');
}

function updateAutoSaveIndicator(state) {
    const indicator = document.getElementById('auto-save-indicator');
    if (!indicator) return;
    
    indicator.classList.remove('saving', 'saved');
    
    switch (state) {
        case 'saving':
            indicator.classList.add('saving');
            indicator.querySelector('.auto-save-text').textContent = 'Saving...';
            break;
        case 'saved':
            indicator.classList.add('saved');
            const time = new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
            indicator.querySelector('.auto-save-text').textContent = `Saved at ${time}`;
            break;
        default:
            indicator.querySelector('.auto-save-text').textContent = 'Unsaved changes';
    }
}

function startAutoSave() {
    if (EntryState.autoSaveTimer) {
        clearInterval(EntryState.autoSaveTimer);
    }
    
    EntryState.autoSaveTimer = setInterval(async () => {
        if (EntryState.isDirty && !EntryState.isLoading && !EntryState.isNavigating) {
            await saveEntryAsDraft(true);
        }
    }, EntryState.autoSaveInterval);
}

function stopAutoSave() {
    if (EntryState.autoSaveTimer) {
        clearInterval(EntryState.autoSaveTimer);
        EntryState.autoSaveTimer = null;
    }
}

// =========================================================================
// Save Operations
// =========================================================================

async function saveEntryAsDraft(silent = false) {
    const data = collectFormData();
    
    if (!silent) {
        updateAutoSaveIndicator('saving');
    }
    
    try {
        const entryData = {
            review_session_id: EntryState.sessionId,
            question_id: data.questionId || null,
            user_answer: data.userAnswer || '',
            correct_answer: data.correctAnswer || '',
            perceived_difficulty: data.perceivedDifficulty,
            time_spent_seconds: data.timeSpent,
            reflection: data.reflection || null,
            explanation: data.explanation || null,
            notes: data.notes || null,
            // Rich text JSON for round-trip editing
            reflection_json: data.reflection_json || null,
            explanation_json: data.explanation_json || null,
            notes_json: data.notes_json || null,
            primary_subject_ids: data.primarySubjects.map(s => s.id),
            secondary_subject_ids: data.secondarySubjects.map(s => s.id),
            tag_ids: data.tags.map(t => t.id)
        };
        
        let result;
        if (EntryState.currentEntry && EntryState.currentEntry.id) {
            // Update existing entry
            result = await api.updateQuestionEntry(EntryState.currentEntry.id, entryData);
            if (window.eventBus) eventBus.emit('entry:saved', { id: EntryState.currentEntry.id, action: 'update' });
        } else {
            // Create new entry
            result = await api.createQuestionEntry(entryData);
            EntryState.currentEntry = result;
            if (window.eventBus) eventBus.emit('entry:saved', { id: result.id, action: 'create' });

            // Update media upload with new entry ID
            if (EntryState.mediaUpload && result.id) {
                EntryState.mediaUpload.setEntryId(result.id);
            }
        }

        // Sync entry notes to database
        const entryId = EntryState.currentEntry?.id || result?.id;
        if (entryId) {
            await syncEntryNotes(entryId);
            // Push per-subject parent-context choices for any
            // multi-parent primary subjects (Tag context pill, §7.3).
            // Runs after primary_subject_ids land via the create/update
            // call above so the entry_subject_mappings rows exist.
            await syncTagContextChoices(entryId);
        }

        markClean();
        
        if (!silent) {
            Toast.success('Draft Saved', 'Your entry has been saved as a draft.');
        }
        
        // Reload entries to update navigation
        await loadSessionEntries();
        renderEntryNavigation(false);
        
        return result;
    } catch (error) {
        console.error('Error saving draft:', error);
        if (!silent) {
            Toast.error('Save Failed', error.message || 'Could not save the draft.');
        }
        throw error;
    }
}

async function saveEntryAndNext() {
    const data = collectFormData();

    // Validate required fields
    if (!validateForm()) {
        // Check if specifically images need subjects
        if (EntryState.mediaUpload?.hasUnassignedMedia()) {
            const unassigned = EntryState.mediaUpload.getUnassignedMedia();
            Toast.warning('Images Need Subjects', `${unassigned.length} image(s) need subject assignments. Click "Edit Subjects" on the image thumbnail.`);
        } else {
            Toast.warning('Incomplete Entry', 'Please fill in all required fields.');
        }
        return;
    }
    
    const saveBtn = document.getElementById('btn-save-next');
    const totalEntries = EntryState.session?.total_incorrect || 0;
    const currentIndex = EntryState.currentEntryIndex;
    const isLastEntry = currentIndex >= totalEntries - 1;
    
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<span class="spinner spinner-sm"></span> Saving...';
    }
    
    try {
        await saveEntryAsDraft(true);
        
        // Reload session to get updated completion status
        await loadSessionEntries();
        
        // Count completed entries (non-draft entries)
        const completedCount = EntryState.entries.filter(e => !e.is_draft).length;
        const allEntriesComplete = completedCount >= totalEntries;
        
        // Check if this is the last entry AND all entries are complete
        if (isLastEntry || allEntriesComplete) {
            // Update session status to completed
            try {
                await api.updateReviewSession(EntryState.sessionId, {
                    session_status: 'completed',
                    entries_completed: completedCount
                });
            } catch (updateError) {
                console.warn('Could not update session status:', updateError);
            }
            
            Toast.success('Session Complete!', 'All entries have been saved.');
            showSessionComplete();
        } else {
            Toast.success('Entry Saved', 'Moving to next entry...');
            // Move to next entry
            await navigateToNextEntry();
        }
        
    } catch (error) {
        console.error('Error saving entry:', error);
        Toast.error('Save Failed', error.message || 'Could not save the entry.');
    } finally {
        if (saveBtn) {
            saveBtn.disabled = false;
            validateForm(); // This will set the correct button text
        }
    }
}

// =========================================================================
// Entry Navigation
// =========================================================================

async function loadSessionEntries() {
    try {
        const entries = await api.getSessionEntries(EntryState.sessionId);
        EntryState.entries = entries || [];
    } catch (error) {
        console.error('Error loading session entries:', error);
        EntryState.entries = [];
    }
}

function renderEntryNavigation(shouldScroll = true) {
    const dotsContainer = document.getElementById('entry-dots');
    const prevBtn = document.getElementById('btn-prev-entry');
    const nextBtn = document.getElementById('btn-next-entry');
    const counter = document.getElementById('entry-counter');
    const saveNextBtn = document.getElementById('btn-save-next');
    
    if (!dotsContainer) return;
    
    const totalEntries = EntryState.session?.total_incorrect || 0;
    const currentIndex = EntryState.currentEntryIndex;
    const isLastEntry = totalEntries > 0 && currentIndex >= totalEntries - 1;
    
    // Update counter
    if (counter) {
        counter.textContent = `Entry ${currentIndex + 1} of ${totalEntries}`;
    }
    
    // Update navigation buttons
    if (prevBtn) {
        prevBtn.disabled = currentIndex <= 0;
    }
    if (nextBtn) {
        nextBtn.disabled = isLastEntry;
    }
    
    // Update Save & Next button text for last entry (only if button is enabled)
    // Note: validateForm() handles the disabled state and text when form is invalid
    if (saveNextBtn && !saveNextBtn.disabled) {
        if (isLastEntry) {
            saveNextBtn.textContent = 'Complete Review ✓';
            saveNextBtn.classList.add('btn-complete');
        } else {
            saveNextBtn.textContent = 'Save & Next →';
            saveNextBtn.classList.remove('btn-complete');
        }
    }
    
    // Render all dots (scrollable container handles overflow)
    let dots = [];

    for (let i = 0; i < totalEntries; i++) {
        const entry = EntryState.entries.find(e => e.entry_order === i + 1);
        let dotClass = 'entry-dot';

        if (i === currentIndex) {
            dotClass += ' current';
        } else if (entry) {
            dotClass += entry.is_draft ? ' draft' : ' complete';
        }

        dots.push(`<div class="${dotClass}" data-index="${i}" data-testid="entry-form-nav-dot-${i}" onclick="navigateToEntry(${i})" title="Entry ${i + 1}"></div>`);
    }

    dotsContainer.innerHTML = dots.join('');

    // Scroll current dot into view if container is scrollable
    if (shouldScroll) {
        const currentDot = dotsContainer.querySelector('.entry-dot.current');
        if (currentDot) {
            currentDot.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        }
    }
}

async function navigateToEntry(index) {
    EntryState.isNavigating = true;
    try {
        if (EntryState.isDirty) {
            const shouldSave = await showUnsavedChangesModal();
            if (shouldSave === 'cancel') return;
            if (shouldSave === 'save') {
                await saveEntryAsDraft();
            }
        }

        EntryState.currentEntryIndex = index;

        // Check if entry exists at this index (entry_order is 1-indexed)
        const targetOrder = index + 1;
        const existingEntry = EntryState.entries.find(e => e.entry_order === targetOrder);

        if (existingEntry) {
            await loadExistingEntry(existingEntry.id);
        } else {
            resetFormForNewEntry();
        }

        renderEntryNavigation();
        markClean();
    } finally {
        EntryState.isNavigating = false;
    }
}

async function navigateToNextEntry() {
    const nextIndex = EntryState.currentEntryIndex + 1;
    const totalEntries = EntryState.session?.total_incorrect || 0;
    
    if (nextIndex < totalEntries) {
        await navigateToEntry(nextIndex);
    }
    // Note: Session completion is now handled in saveEntryAndNext()
    // This function is only called for navigation, not completion
}

async function navigateToPrevEntry() {
    const prevIndex = EntryState.currentEntryIndex - 1;
    if (prevIndex >= 0) {
        await navigateToEntry(prevIndex);
    }
}

// =========================================================================
// Form Population
// =========================================================================

async function loadExistingEntry(entryId) {
    try {
        const entry = await api.getQuestionEntry(entryId);
        console.log('[LOAD] Entry loaded from API:', {
            id: entry.id,
            has_reflection: !!entry.reflection,
            has_reflection_json: !!entry.reflection_json,
            has_explanation: !!entry.explanation,
            has_explanation_json: !!entry.explanation_json,
            has_notes: !!entry.notes,
            has_notes_json: !!entry.notes_json
        });
        if (entry.explanation_json) {
            console.log('[LOAD] explanation_json preview:', entry.explanation_json.substring(0, 200));
        }
        EntryState.currentEntry = entry;

        populateFormWithEntry(entry);

        // Reload media for this entry (MediaUpload component persists across navigations)
        if (EntryState.mediaUpload) {
            await EntryState.mediaUpload.loadMedia(entry.id);
        }
    } catch (error) {
        console.error('Error loading entry:', error);
        Toast.error('Load Failed', 'Could not load the entry.');
    }
}

function populateFormWithEntry(entry) {
    if (!entry) {
        console.error('populateFormWithEntry called with null/undefined entry');
        return;
    }
    
    // Basic fields
    document.getElementById('question-id').value = entry.question_id || '';
    document.getElementById('user-answer').value = entry.user_answer || '';
    document.getElementById('correct-answer').value = entry.correct_answer || '';
    
    // Difficulty
    setDifficultyRating(entry.perceived_difficulty);
    
    // Time spent
    if (entry.time_spent_seconds) {
        const minutes = Math.floor(entry.time_spent_seconds / 60);
        if (minutes > 0 && entry.time_spent_seconds % 60 === 0) {
            document.getElementById('time-spent').value = minutes;
            document.getElementById('time-unit').value = 'minutes';
        } else {
            document.getElementById('time-spent').value = entry.time_spent_seconds;
            document.getElementById('time-unit').value = 'seconds';
        }
    } else {
        document.getElementById('time-spent').value = '';
    }
    
    // Subjects
    EntryState.formData.primarySubjects = (entry.primary_subjects || []).map(s => ({
        id: s.id,
        name: s.name,
        path: s.path || s.name
    }));
    EntryState.formData.secondarySubjects = (entry.secondary_subjects || []).map(s => ({
        id: s.id,
        name: s.name,
        path: s.path || s.name
    }));

    // Round-trip the per-subject parent-context choice — see
    // POLYHIERARCHY_MIGRATION §7.3. Serializer exposes primary_parent_id
    // per subject; populate the formData map AND prime primaryParentSynced
    // so the next save doesn't re-write the same value.
    EntryState.formData.primaryParentChoices = {};
    EntryState.primaryParentSynced = {};
    (entry.primary_subjects || []).forEach(s => {
        if (s.primary_parent_id !== undefined && s.primary_parent_id !== null) {
            EntryState.formData.primaryParentChoices[s.id] = s.primary_parent_id;
            EntryState.primaryParentSynced[s.id] = s.primary_parent_id;
        } else {
            EntryState.primaryParentSynced[s.id] = null;
        }
    });

    renderSubjectChips('primary-subjects-chips', EntryState.formData.primarySubjects, 'primary');
    renderSubjectChips('secondary-subjects-chips', EntryState.formData.secondarySubjects, 'secondary');
    
    // Tags
    EntryState.formData.tags = (entry.tags || []).map(t => ({
        id: t.id,
        name: t.tag_name || t.name,
        color: t.color_hex || t.color || '#6B7280',
        // Join definition from the loaded tag hierarchy for chip tooltips
        description: t.description || getTagDescriptionById(t.id)
    }));
    renderTagHierarchy();
    renderTagChips();
    
    // Reflection - load into rich text editor
    if (EntryState.reflectionEditor) {
        console.log('[POPULATE] Loading reflection - json available:', !!entry.reflection_json, 'html available:', !!entry.reflection);
        if (entry.reflection_json) {
            try {
                const parsed = JSON.parse(entry.reflection_json);
                console.log('[POPULATE] Parsed reflection_json:', parsed);
                EntryState.reflectionEditor.setContent(parsed);
            } catch (e) {
                console.warn('Failed to parse reflection_json, falling back to HTML:', e);
                EntryState.reflectionEditor.setContent(entry.reflection || '');
            }
        } else if (entry.reflection) {
            console.log('[POPULATE] Using reflection HTML fallback');
            EntryState.reflectionEditor.setContent(entry.reflection);
        } else {
            console.log('[POPULATE] No reflection content, clearing editor');
            EntryState.reflectionEditor.clear();
        }
    }

    // Explanation - load into rich text editor
    if (EntryState.explanationEditor) {
        console.log('[POPULATE] Loading explanation - json available:', !!entry.explanation_json, 'html available:', !!entry.explanation);
        if (entry.explanation_json) {
            try {
                const parsed = JSON.parse(entry.explanation_json);
                console.log('[POPULATE] Parsed explanation_json:', parsed);
                EntryState.explanationEditor.setContent(parsed);
            } catch (e) {
                console.warn('Failed to parse explanation_json, falling back to HTML:', e);
                EntryState.explanationEditor.setContent(entry.explanation || '');
            }
        } else if (entry.explanation) {
            console.log('[POPULATE] Using explanation HTML fallback');
            EntryState.explanationEditor.setContent(entry.explanation);
        } else {
            console.log('[POPULATE] No explanation content, clearing editor');
            EntryState.explanationEditor.clear();
        }
    }

    // Notes - load from notes_list (multi-note system)
    clearAllNoteCards();
    if (entry.notes_list && entry.notes_list.length > 0) {
        for (const note of entry.notes_list) {
            addNoteCard(note);
        }
    } else if (entry.notes && entry.notes.trim()) {
        // Legacy fallback: single notes field → create one general note card
        addNoteCard({ content_html: entry.notes, content_json: entry.notes_json });
    }

    // Media - don't render here. MediaUpload component isn't initialized yet during
    // initial page load (initMediaUpload runs after loadExistingEntry).
    // initMediaUpload() will call loadMedia() which fetches proper thumbnail/full URLs.
    EntryState.formData.media = entry.media || [];
    syncMediaUploadSubjects();
    syncNoteSubjects();

    // Update form state
    collectFormData();
    validateForm();

    scheduleRefreshAttachCandidates();
}

function resetFormForNewEntry() {
    EntryState.currentEntry = null;
    EntryState.formData = {
        questionId: '',
        userAnswer: '',
        correctAnswer: '',
        perceivedDifficulty: null,
        timeSpent: null,
        timeUnit: 'minutes',
        primarySubjects: [],
        secondarySubjects: [],
        tags: [],
        reflection: '',
        explanation: '',
        notes: '',
        reflection_json: null,
        explanation_json: null,
        notes_json: null,
        media: [],
        notesList: [],
        primaryParentChoices: {}
    };
    // Drop the per-subject sync ledger too; a fresh entry has no
    // previously-synced choices to deduplicate against.
    EntryState.primaryParentSynced = {};

    // Clear form fields
    document.getElementById('question-id').value = '';
    document.getElementById('user-answer').value = '';
    document.getElementById('correct-answer').value = '';
    document.getElementById('time-spent').value = '';
    document.getElementById('time-unit').value = 'minutes';

    // Clear rich text editors
    if (EntryState.reflectionEditor) {
        EntryState.reflectionEditor.clear();
    }
    if (EntryState.explanationEditor) {
        EntryState.explanationEditor.clear();
    }
    // Clear multi-note cards
    clearAllNoteCards();

    setDifficultyRating(null);

    renderSubjectChips('primary-subjects-chips', [], 'primary');
    renderSubjectChips('secondary-subjects-chips', [], 'secondary');
    renderTagHierarchy();
    renderTagChips();

    // Clear media upload
    if (EntryState.mediaUpload) {
        EntryState.mediaUpload.clear();
    }

    validateForm();

    // Expand first section
    expandSection('section-question-info');

    scheduleRefreshAttachCandidates();
}

// =========================================================================
// Character Count
// =========================================================================

function updateCharCount(inputId, countId) {
    const input = document.getElementById(inputId);
    const counter = document.getElementById(countId);
    
    if (input && counter) {
        counter.textContent = `${input.value.length} characters`;
    }
}

function initCharacterCounts() {
    // Character counts are no longer needed for rich text editors
    // The editors have their own content change handlers
    // This function is kept for backward compatibility but does nothing now
}

// =========================================================================
// Unsaved Changes Modal
// =========================================================================

function showUnsavedChangesModal() {
    return new Promise((resolve) => {
        Modal.open('unsaved-modal');
        
        const discardBtn = document.getElementById('unsaved-discard');
        const saveBtn = document.getElementById('unsaved-save');
        const cancelBtn = document.getElementById('unsaved-cancel');
        
        const cleanup = () => {
            discardBtn.removeEventListener('click', onDiscard);
            saveBtn.removeEventListener('click', onSave);
            cancelBtn.removeEventListener('click', onCancel);
        };
        
        const onDiscard = () => { cleanup(); Modal.close('unsaved-modal'); resolve('discard'); };
        const onSave = () => { cleanup(); Modal.close('unsaved-modal'); resolve('save'); };
        const onCancel = () => { cleanup(); Modal.close('unsaved-modal'); resolve('cancel'); };
        
        discardBtn.addEventListener('click', onDiscard);
        saveBtn.addEventListener('click', onSave);
        cancelBtn.addEventListener('click', onCancel);
    });
}

// =========================================================================
// Session Complete Modal
// =========================================================================

function showSessionComplete() {
    const countEl = document.getElementById('complete-count');
    if (countEl) {
        countEl.textContent = EntryState.session?.total_incorrect || 0;
    }
    
    Modal.open('complete-modal');
    
    document.getElementById('complete-done').onclick = async () => {
        Modal.close('complete-modal');
        await autoSuspendTimerForNavigation();
        window.location.href = 'index.html';
    };
    
    document.getElementById('complete-review').onclick = async () => {
        Modal.close('complete-modal');
        // Stop the running study timer. Without this, choosing
        // "Review Entries" leaves the timer ticking while the user
        // browses past entries — the bug reported in bugs.md
        // ("Question Review Timer does not stop when user selects the
        // complete review button"). Mirrors the call in the
        // ``complete-done`` handler above.
        await autoSuspendTimerForNavigation();
        // Mark the session as completed in the DB. The save-the-last-
        // entry code path around line 1855 already does this when the
        // modal is reached via the normal flow, but we also flip the
        // status here so other entry points to the modal (and any
        // session that arrived here without going through saveEntry's
        // last-entry branch) leave the session in a coherent state.
        try {
            await api.updateReviewSession(EntryState.sessionId, {
                session_status: 'completed',
            });
        } catch (updateError) {
            console.warn('Could not update session status:', updateError);
        }
        // Stay on page so the user can review their entries.
    };
}

// =========================================================================
// Back Button Handling
// =========================================================================

async function handleBackButton() {
    if (EntryState.isDirty) {
        const shouldSave = await showUnsavedChangesModal();
        if (shouldSave === 'cancel') return;
        if (shouldSave === 'save') {
            await saveEntryAsDraft();
        }
    }

    // Auto-pause timer before navigating away
    await autoSuspendTimerForNavigation();

    // If we came from edit mode (entry detail page), go back to entry detail
    if (EntryState.isEditMode && EntryState.editEntryId) {
        const examId = EntryState.session?.exam_context_id || '';
        window.location.href = `entry_detail.html?id=${EntryState.editEntryId}&exam=${examId}`;
    } else {
        // Otherwise, go back to session setup
        window.location.href = `session_setup.html?exam_id=${EntryState.session?.exam_context_id}`;
    }
}

// =========================================================================
// Form Input Handlers
// =========================================================================

function initFormInputHandlers() {
    // Text inputs that trigger dirty state
    // Note: reflection, explanation, and notes are now rich text editors with their own onChange handlers
    const inputs = [
        'question-id', 'user-answer', 'correct-answer',
        'time-spent'
    ];

    inputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', () => {
                markDirty();
                validateForm();
            });
        }
    });

    // Question ID auto-fill lookup on blur
    const questionIdInput = document.getElementById('question-id');
    if (questionIdInput) {
        questionIdInput.addEventListener('blur', handleQuestionIdBlur);
    }

    // Time unit change
    const timeUnit = document.getElementById('time-unit');
    if (timeUnit) {
        timeUnit.addEventListener('change', () => {
            markDirty();
        });
    }
}

// =========================================================================
// Question ID Auto-Fill
// =========================================================================

let autoFillLookupTimeout = null;

/**
 * Handle blur event on question ID field to trigger auto-fill lookup
 */
async function handleQuestionIdBlur(event) {
    const questionId = event.target.value.trim();

    // Don't lookup if empty, no session, or already has data
    if (!questionId || !EntryState.session?.exam_context_id) {
        return;
    }

    // Don't lookup if the current entry already has subjects (editing existing)
    if (EntryState.currentEntry?.id && EntryState.formData.primarySubjects.length > 0) {
        return;
    }

    // Clear previous timeout
    if (autoFillLookupTimeout) {
        clearTimeout(autoFillLookupTimeout);
    }

    // Debounce the lookup
    autoFillLookupTimeout = setTimeout(async () => {
        await lookupQuestionIdForAutofill(questionId);
    }, 300);
}

/**
 * Look up entries with the same question ID and offer auto-fill
 */
async function lookupQuestionIdForAutofill(questionId) {
    try {
        const excludeId = EntryState.currentEntry?.id || -1;
        const entries = await api.getEntriesByQuestionId(
            questionId,
            EntryState.session.exam_context_id,
            excludeId
        );

        if (!entries || entries.length === 0) {
            return;
        }

        // Use the most recent entry as the source
        const sourceEntry = entries[0];

        // Check if source has useful data to auto-fill
        const hasSubjects = (sourceEntry.primary_subjects?.length > 0) ||
                           (sourceEntry.secondary_subjects?.length > 0);
        const hasTags = sourceEntry.tags?.length > 0;

        if (!hasSubjects && !hasTags) {
            return;
        }

        // Show auto-fill prompt
        showAutofillPrompt(sourceEntry, entries.length);

    } catch (error) {
        console.error('Auto-fill lookup failed:', error);
    }
}

/**
 * Show auto-fill prompt to the user
 */
function showAutofillPrompt(sourceEntry, matchCount) {
    // Remove any existing prompt
    hideAutofillPrompt();

    const prompt = document.createElement('div');
    prompt.id = 'autofill-prompt';
    prompt.className = 'autofill-prompt';
    prompt.innerHTML = `
        <div class="autofill-prompt-content">
            <div class="autofill-prompt-icon">💡</div>
            <div class="autofill-prompt-text">
                <strong>Auto-fill available</strong>
                <span>Found ${matchCount} previous ${matchCount === 1 ? 'entry' : 'entries'} with this Question ID</span>
            </div>
            <div class="autofill-prompt-actions">
                <button type="button" class="btn btn-sm btn-primary" id="btn-autofill-accept">
                    Apply All Data
                </button>
                <button type="button" class="btn btn-sm btn-ghost" id="btn-autofill-dismiss">
                    Dismiss
                </button>
            </div>
        </div>
    `;

    // Insert after question-id field
    const questionIdGroup = document.getElementById('question-id')?.closest('.form-group');
    if (questionIdGroup) {
        questionIdGroup.appendChild(prompt);
    }

    // Event listeners
    document.getElementById('btn-autofill-accept')?.addEventListener('click', () => {
        applyAutofillData(sourceEntry);
        hideAutofillPrompt();
    });

    document.getElementById('btn-autofill-dismiss')?.addEventListener('click', () => {
        hideAutofillPrompt();
    });
}

/**
 * Hide auto-fill prompt
 */
function hideAutofillPrompt() {
    const existing = document.getElementById('autofill-prompt');
    if (existing) {
        existing.remove();
    }
}

/**
 * Apply auto-fill data from source entry to current form
 */
function applyAutofillData(sourceEntry) {
    let appliedItems = [];

    // Apply correct answer (only if current field is empty)
    const correctAnswerField = document.getElementById('correct-answer');
    if (sourceEntry.correct_answer && correctAnswerField && !correctAnswerField.value.trim()) {
        correctAnswerField.value = sourceEntry.correct_answer;
        EntryState.formData.correctAnswer = sourceEntry.correct_answer;
        appliedItems.push('correct answer');
    }

    // Apply explanation (only if current editor is empty)
    if (sourceEntry.explanation && EntryState.explanationEditor && EntryState.explanationEditor.isEmpty()) {
        if (sourceEntry.explanation_json) {
            try {
                EntryState.explanationEditor.setContent(JSON.parse(sourceEntry.explanation_json));
            } catch (e) {
                EntryState.explanationEditor.setContent(sourceEntry.explanation);
            }
        } else {
            EntryState.explanationEditor.setContent(sourceEntry.explanation);
        }
        appliedItems.push('explanation');
    }

    // Apply notes (only if current editor is empty)
    if (sourceEntry.notes && EntryState.notesEditor && EntryState.notesEditor.isEmpty()) {
        if (sourceEntry.notes_json) {
            try {
                EntryState.notesEditor.setContent(JSON.parse(sourceEntry.notes_json));
            } catch (e) {
                EntryState.notesEditor.setContent(sourceEntry.notes);
            }
        } else {
            EntryState.notesEditor.setContent(sourceEntry.notes);
        }
        appliedItems.push('notes');
    }

    // Apply primary subjects
    if (sourceEntry.primary_subjects?.length > 0) {
        let addedCount = 0;
        sourceEntry.primary_subjects.forEach(subject => {
            if (!EntryState.formData.primarySubjects.some(s => s.id === subject.id)) {
                addSubjectChip('primary', subject);
                addedCount++;
            }
        });
        if (addedCount > 0) {
            appliedItems.push(`${addedCount} primary subject(s)`);
        }
    }

    // Apply secondary subjects
    if (sourceEntry.secondary_subjects?.length > 0) {
        let addedCount = 0;
        sourceEntry.secondary_subjects.forEach(subject => {
            if (!EntryState.formData.secondarySubjects.some(s => s.id === subject.id)) {
                addSubjectChip('secondary', subject);
                addedCount++;
            }
        });
        if (addedCount > 0) {
            appliedItems.push(`${addedCount} secondary subject(s)`);
        }
    }

    // Apply tags
    if (sourceEntry.tags?.length > 0) {
        let addedCount = 0;
        sourceEntry.tags.forEach(tag => {
            if (!EntryState.formData.tags.some(t => t.id === tag.id)) {
                // Add tag to state and re-render
                EntryState.formData.tags.push({
                    id: tag.id,
                    name: tag.name || tag.tag_name,
                    color: tag.color || tag.color_hex || '#6b7280',
                    description: tag.description || getTagDescriptionById(tag.id)
                });
                addedCount++;
            }
        });
        if (addedCount > 0) {
            renderTagChips();
            appliedItems.push(`${addedCount} tag(s)`);
        }
    }

    if (appliedItems.length > 0) {
        markDirty();
        validateForm();
        Toast.success('Auto-fill Applied', `Added ${appliedItems.join(', ')}`);
    } else {
        Toast.info('No New Data', 'All fields already have values or no data to apply');
    }
}

// =========================================================================
// Rich Text Editors
// =========================================================================

function initRichTextEditors() {
    // Check if RichEditor class is available
    if (typeof window.RichEditor === 'undefined') {
        console.warn('RichEditor component not loaded, falling back to textareas');
        return;
    }

    console.log('Initializing rich text editors...');

    // Initialize explanation editor
    const explanationContainer = document.getElementById('explanation-editor');
    if (explanationContainer) {
        EntryState.explanationEditor = new RichEditor('#explanation-editor', {
            placeholder: 'Explain the reasoning behind the correct answer. What concept or rule makes this the right choice?',
            onChange: () => {
                markDirty();
                validateForm();
            }
        });
        console.log('Explanation editor initialized');
    }

    // Initialize reflection editor
    const reflectionContainer = document.getElementById('reflection-editor');
    if (reflectionContainer) {
        EntryState.reflectionEditor = new RichEditor('#reflection-editor', {
            placeholder: 'Reflect on your thought process. What led you to choose the wrong answer? What did you miss or misunderstand?',
            onChange: () => {
                markDirty();
                validateForm();
            }
        });
        console.log('Reflection editor initialized');
    }

    // Initialize "Add Note" button
    const addNoteBtn = document.getElementById('btn-add-note');
    if (addNoteBtn) {
        addNoteBtn.addEventListener('click', () => addNoteCard());
    }

    console.log('Rich text editors initialized');
}

// =========================================================================
// Multi-Note Card Management (Phase 9)
// =========================================================================

function addNoteCard(noteData = null) {
    const container = document.getElementById('notes-list-container');
    if (!container) return;

    const tempId = 'note-' + (++EntryState.noteIdCounter);
    const noteId = noteData?.id || null;
    const linkedSubjectIds = noteData?.linked_subject_ids || [];

    // Create card DOM
    const card = document.createElement('div');
    card.className = 'note-card';
    card.dataset.tempId = tempId;
    card.dataset.testid = `entry-form-note-card-${tempId}`;

    const header = document.createElement('div');
    header.className = 'note-card-header';

    const subjectChips = document.createElement('div');
    subjectChips.className = 'note-card-subjects';
    subjectChips.dataset.tempId = tempId;
    header.appendChild(subjectChips);

    const actions = document.createElement('div');
    actions.className = 'note-card-actions';

    const subjectBtn = document.createElement('button');
    subjectBtn.type = 'button';
    subjectBtn.className = 'btn btn-text btn-xs';
    subjectBtn.textContent = 'Subjects';
    subjectBtn.title = 'Assign subjects to this note';
    subjectBtn.dataset.testid = `entry-form-note-card-${tempId}-subject-button`;
    subjectBtn.addEventListener('click', () => editNoteSubjects(tempId));
    actions.appendChild(subjectBtn);

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'btn btn-text btn-xs';
    clearBtn.textContent = 'Clear';
    clearBtn.title = 'Clear note content';
    clearBtn.dataset.testid = `entry-form-note-card-${tempId}-clear-button`;
    clearBtn.addEventListener('click', () => clearNote(tempId));
    actions.appendChild(clearBtn);

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'btn btn-text btn-xs btn-danger-text';
    deleteBtn.textContent = 'Delete';
    deleteBtn.title = 'Delete this note';
    deleteBtn.dataset.testid = `entry-form-note-card-${tempId}-delete-button`;
    deleteBtn.addEventListener('click', () => deleteNote(tempId));
    actions.appendChild(deleteBtn);

    header.appendChild(actions);
    card.appendChild(header);

    const editorDiv = document.createElement('div');
    editorDiv.className = 'rich-editor-container';
    editorDiv.id = `editor-${tempId}`;
    editorDiv.dataset.testid = `entry-form-note-card-${tempId}-editor`;
    card.appendChild(editorDiv);

    container.appendChild(card);

    // Create RichEditor instance
    const editor = new RichEditor(`#editor-${tempId}`, {
        placeholder: 'Write your note here...',
        onChange: () => {
            markDirty();
        }
    });

    // Load content if provided
    if (noteData) {
        if (noteData.content_json) {
            try {
                const parsed = typeof noteData.content_json === 'string'
                    ? JSON.parse(noteData.content_json) : noteData.content_json;
                editor.setContent(parsed);
            } catch (e) {
                editor.setContent(noteData.content_html || '');
            }
        } else if (noteData.content_html) {
            editor.setContent(noteData.content_html);
        }
    }

    // Track in state. attachmentCount comes from the serializer
    // (entry_note_attachments junction); used by deleteNote() to decide
    // between the simple hard-delete path and the detach-vs-delete modal.
    EntryState.noteEditors.push({
        id: noteId,
        tempId: tempId,
        editor: editor,
        linkedSubjectIds: [...linkedSubjectIds],
        attachmentCount: typeof noteData?.attachment_count === 'number' ? noteData.attachment_count : 1
    });

    renderNoteSubjectChips(tempId, linkedSubjectIds);
    markDirty();
}

function renderNoteSubjectChips(tempId, linkedSubjectIds) {
    const container = document.querySelector(`.note-card-subjects[data-temp-id="${tempId}"]`);
    if (!container) return;

    container.innerHTML = '';
    if (!linkedSubjectIds || linkedSubjectIds.length === 0) {
        const badge = document.createElement('span');
        badge.className = 'note-general-badge';
        badge.textContent = 'General';
        container.appendChild(badge);
        return;
    }

    // Look up names from entry subjects first, then full hierarchy
    const entrySubjects = [
        ...EntryState.formData.primarySubjects,
        ...EntryState.formData.secondarySubjects
    ];

    for (const subId of linkedSubjectIds) {
        let subject = entrySubjects.find(s => s.id === subId);
        if (!subject) {
            subject = EntryState.subjects.find(s => s.id === subId);
        }
        const chip = document.createElement('span');
        chip.className = 'note-subject-chip';
        chip.textContent = subject ? subject.name : `Subject #${subId}`;
        chip.dataset.testid = `entry-form-note-card-${tempId}-subject-chip-${subId}`;
        container.appendChild(chip);
    }
}

function editNoteSubjects(tempId) {
    const noteEntry = EntryState.noteEditors.find(ne => ne.tempId === tempId);
    if (!noteEntry) return;

    const entrySubjects = [
        ...EntryState.formData.primarySubjects,
        ...EntryState.formData.secondarySubjects
    ];
    const entrySubjectIds = entrySubjects.map(s => s.id);

    // Separate linked IDs into entry subjects vs search-added subjects
    const currentLinkedIds = noteEntry.linkedSubjectIds || [];
    const additionalLinkedIds = currentLinkedIds.filter(id => !entrySubjectIds.includes(id));

    // Build additional subject objects from full hierarchy
    const additionalSubjects = [];
    for (const id of additionalLinkedIds) {
        const found = EntryState.subjects.find(s => s.id === id);
        additionalSubjects.push(found || { id, name: `Unknown Subject (ID: ${id})` });
    }

    // Remove any existing modal
    const existingModal = document.getElementById('note-subject-modal');
    if (existingModal) existingModal.remove();

    // Build modal
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'note-subject-modal';
    backdrop.classList.add('active');

    const modal = document.createElement('div');
    modal.className = 'modal note-subject-modal-content';

    // Title
    const title = document.createElement('h3');
    title.className = 'modal-title';
    const noteIndex = EntryState.noteEditors.indexOf(noteEntry) + 1;
    title.textContent = `Note ${noteIndex} — Assign Subjects`;
    modal.appendChild(title);

    // Hint
    const hint = document.createElement('p');
    hint.className = 'note-subject-modal-hint';
    hint.textContent = 'Select which subjects this note relates to:';
    modal.appendChild(hint);

    // Entry subjects as checkboxes
    if (entrySubjects.length > 0) {
        const checkboxSection = document.createElement('div');
        checkboxSection.className = 'note-subject-checkbox-list';

        for (const subject of entrySubjects) {
            const label = document.createElement('label');
            label.className = 'note-subject-option';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = subject.id;
            cb.checked = currentLinkedIds.includes(subject.id);
            label.appendChild(cb);
            label.appendChild(document.createTextNode(' ' + subject.name));
            checkboxSection.appendChild(label);
        }

        modal.appendChild(checkboxSection);
    } else {
        const empty = document.createElement('p');
        empty.className = 'note-subject-modal-hint';
        empty.style.fontStyle = 'italic';
        empty.textContent = 'No subjects on entry yet. Use search below to add subjects.';
        modal.appendChild(empty);
    }

    // Divider + search widget
    const divider = document.createElement('div');
    divider.style.cssText = 'border-top: 1px solid var(--border-color, #e5e7eb); margin: 16px 0 12px 0;';
    modal.appendChild(divider);

    const searchLabel = document.createElement('div');
    searchLabel.className = 'note-subject-modal-hint';
    searchLabel.textContent = 'Search for additional subjects:';
    modal.appendChild(searchLabel);

    const widgetContainer = document.createElement('div');
    widgetContainer.className = 'note-subject-search-widget';
    modal.appendChild(widgetContainer);

    // Actions
    const actions = document.createElement('div');
    actions.className = 'modal-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn btn-secondary';
    cancelBtn.textContent = 'Cancel';

    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'btn btn-primary';
    saveBtn.textContent = 'Save';

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    modal.appendChild(actions);

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    // Initialize search widget
    const widget = new SubjectSearchSelect(widgetContainer, {
        fuzzySearch: window.fuzzySearch,
        excludeIds: entrySubjectIds,
        placeholder: 'Search for additional subjects...'
    });

    if (additionalSubjects.length > 0) {
        widget.setSelectedSubjects(additionalSubjects);
    }

    // Close on backdrop click
    backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) closeNoteSubjectModal();
    });

    cancelBtn.addEventListener('click', closeNoteSubjectModal);

    saveBtn.addEventListener('click', () => {
        // Collect checked entry subjects
        const checked = modal.querySelectorAll('.note-subject-checkbox-list input[type="checkbox"]:checked');
        const checkedIds = Array.from(checked).map(cb => parseInt(cb.value));

        // Collect search-added subjects
        const searchIds = widget.getSelectedIds();

        // Merge (dedup)
        noteEntry.linkedSubjectIds = [...new Set([...checkedIds, ...searchIds])];

        renderNoteSubjectChips(tempId, noteEntry.linkedSubjectIds);
        markDirty();
        closeNoteSubjectModal();
    });

    function closeNoteSubjectModal() {
        widget.destroy();
        backdrop.classList.remove('active');
        backdrop.remove();
    }
}

function deleteNote(tempId) {
    const idx = EntryState.noteEditors.findIndex(ne => ne.tempId === tempId);
    if (idx === -1) return;

    const noteEntry = EntryState.noteEditors[idx];

    // Resolve attachment_count tracked on the noteEditor (mirrored from
    // the serializer at load time and refreshed after picker attach).
    // Default to 1 if missing / not yet persisted.
    const attachmentCount = (noteEntry.id && typeof noteEntry.attachmentCount === 'number')
        ? noteEntry.attachmentCount
        : 1;

    // Single-attachment (or unpersisted) → simple confirm + hard-delete path.
    if (attachmentCount <= 1) {
        if (!confirm('Delete this note?')) return;
        _deleteNoteHardDelete(tempId);
        return;
    }

    // Many-to-many: open modal with detach-vs-delete-everywhere choice.
    _showNoteDeleteModal(tempId, noteEntry.id, attachmentCount);
}

function _deleteNoteHardDelete(tempId) {
    const idx = EntryState.noteEditors.findIndex(ne => ne.tempId === tempId);
    if (idx === -1) return;
    const noteEntry = EntryState.noteEditors[idx];

    if (noteEntry.id) {
        api.deleteEntryNote(noteEntry.id).catch(e => console.error('Error deleting note:', e));
    }
    _removeNoteCardFromUi(tempId);
}

function _detachNoteFromCurrentEntry(tempId, noteId) {
    const entryId = EntryState.currentEntry?.id;
    if (!entryId || !noteId) return;
    api.detachNoteFromEntry(noteId, entryId).catch(e => console.error('Error detaching note:', e));
    _removeNoteCardFromUi(tempId);
}

function _removeNoteCardFromUi(tempId) {
    const idx = EntryState.noteEditors.findIndex(ne => ne.tempId === tempId);
    if (idx === -1) return;
    const noteEntry = EntryState.noteEditors[idx];

    if (noteEntry.editor) noteEntry.editor.destroy();
    EntryState.noteEditors.splice(idx, 1);

    const card = document.querySelector(`.note-card[data-temp-id="${tempId}"]`);
    if (card) card.remove();

    // Mirror in formData.notesList so subsequent candidate-refreshes
    // correctly re-surface the note as attach-able.
    EntryState.formData.notesList = (EntryState.formData.notesList || [])
        .filter(n => n.tempId !== tempId);

    markDirty();
    // Re-poll candidates so the "+ Add existing" notes button reflects
    // that this note is now available to re-attach.
    scheduleRefreshAttachCandidates();
}

function _showNoteDeleteModal(tempId, noteId, attachmentCount) {
    const message = document.getElementById('note-delete-modal-message');
    const detail = document.getElementById('note-delete-modal-detail');
    const detachBtn = document.getElementById('note-delete-modal-detach');
    const deleteBtn = document.getElementById('note-delete-modal-delete-everywhere');
    const cancelBtn = document.getElementById('note-delete-modal-cancel');

    if (!message || !detail || !detachBtn || !deleteBtn || !cancelBtn) {
        // Safety fallback if modal markup is missing.
        if (confirm(`This note is attached to ${attachmentCount} entries. Delete from EVERY entry? Cancel to detach from just this one.`)) {
            _deleteNoteHardDelete(tempId);
        } else {
            _detachNoteFromCurrentEntry(tempId, noteId);
        }
        return;
    }

    message.textContent = `This note is attached to ${attachmentCount} entries. Choose how to remove it from this entry.`;
    detail.innerHTML = `
        <strong>Detach</strong>: keeps the note (still appears on the other ${attachmentCount - 1} entr${attachmentCount - 1 === 1 ? 'y' : 'ies'}).<br>
        <strong>Delete everywhere</strong>: removes the note from all ${attachmentCount} entries.
    `;

    Modal.open('note-delete-modal');

    const cleanup = () => {
        detachBtn.removeEventListener('click', onDetach);
        deleteBtn.removeEventListener('click', onDelete);
        cancelBtn.removeEventListener('click', onCancel);
    };
    const onDetach = () => {
        cleanup();
        Modal.close('note-delete-modal');
        _detachNoteFromCurrentEntry(tempId, noteId);
        Toast.info('Detached', 'Note detached from this entry. It is still available on other entries.');
    };
    const onDelete = () => {
        cleanup();
        Modal.close('note-delete-modal');
        _deleteNoteHardDelete(tempId);
        Toast.success('Deleted', `Note removed from all ${attachmentCount} entries.`);
    };
    const onCancel = () => {
        cleanup();
        Modal.close('note-delete-modal');
    };

    detachBtn.addEventListener('click', onDetach);
    deleteBtn.addEventListener('click', onDelete);
    cancelBtn.addEventListener('click', onCancel);
}

function clearNote(tempId) {
    if (!confirm('Clear this note\'s content?')) return;

    const noteEntry = EntryState.noteEditors.find(ne => ne.tempId === tempId);
    if (!noteEntry) return;

    if (noteEntry.editor) noteEntry.editor.clear();

    if (noteEntry.id) {
        api.clearEntryNote(noteEntry.id).catch(e => console.error('Error clearing note:', e));
    }
    markDirty();
}

function clearAllNoteCards() {
    for (const ne of EntryState.noteEditors) {
        if (ne.editor) ne.editor.destroy();
    }
    EntryState.noteEditors = [];
    EntryState.noteIdCounter = 0;
    const container = document.getElementById('notes-list-container');
    if (container) container.innerHTML = '';
}

async function syncEntryNotes(entryId) {
    const data = collectFormData();
    if (!data.notesList) return;

    for (const note of data.notesList) {
        const payload = {
            content_html: note.content_html,
            content_json: note.content_json,
            linked_subject_ids: note.linked_subject_ids
        };

        if (note.id) {
            // Update existing note
            await api.updateEntryNote(note.id, payload);
        } else {
            // Create new note
            const result = await api.addEntryNote(entryId, payload);
            // Update the editor's tracked id
            const ne = EntryState.noteEditors.find(e => e.tempId === note.tempId);
            if (ne && result?.id) ne.id = result.id;
        }
    }
}

function syncNoteSubjects() {
    // Re-render subject chips on all note cards when entry subjects change.
    // Preserve search-added subjects (IDs that were never in the entry subject list).
    const entrySubjectIds = new Set([
        ...EntryState.formData.primarySubjects.map(s => s.id),
        ...EntryState.formData.secondarySubjects.map(s => s.id)
    ]);

    for (const ne of EntryState.noteEditors) {
        // Keep IDs that are either: (a) still in entry subjects, or (b) not from entry (search-added)
        ne.linkedSubjectIds = ne.linkedSubjectIds.filter(id => {
            // If this ID is in the current entry subjects, keep it
            if (entrySubjectIds.has(id)) return true;
            // If this ID exists in the full hierarchy but NOT in entry subjects,
            // it's a search-added subject — preserve it
            if (EntryState.subjects.some(s => s.id === id)) return true;
            // Unknown ID — drop it
            return false;
        });
        renderNoteSubjectChips(ne.tempId, ne.linkedSubjectIds);
    }
}

// =========================================================================
// Media Upload (Placeholder for Stage 5)
// =========================================================================

function initMediaUpload() {
    const container = document.getElementById('media-upload-container');
    
    if (!container) {
        console.warn('Media upload container not found');
        return;
    }
    
    // Check if MediaUpload class is available
    if (typeof window.MediaUpload === 'undefined') {
        console.warn('MediaUpload component not loaded');
        container.innerHTML = '<p class="text-muted">Media upload not available</p>';
        return;
    }
    
    // Initialize MediaUpload component
    EntryState.mediaUpload = new window.MediaUpload(container, {
        entryId: EntryState.currentEntry?.id || null,
        examContextId: EntryState.session?.exam_context_id || null,
        onUpload: (mediaItem) => {
            console.log('Media uploaded:', mediaItem);
            EntryState.formData.media.push(mediaItem);
            markDirty();
            validateForm();
            Toast.success('Image Added', mediaItem.user_filename || 'Image added');
        },
        onDelete: (mediaItem) => {
            console.log('Media deleted:', mediaItem);
            EntryState.formData.media = EntryState.formData.media.filter(m => m.id !== mediaItem.id);
            markDirty();
            validateForm();
            Toast.info('Image Deleted', mediaItem.user_filename || 'Image removed');
        },
        onError: (errorMessage) => {
            Toast.error('Media Error', errorMessage);
        },
        onSubjectAssigned: () => {
            markDirty();
            validateForm();
        }
    });

    // If editing an existing entry, load its media with proper URLs
    if (EntryState.currentEntry?.id) {
        EntryState.mediaUpload.loadMedia(EntryState.currentEntry.id).then(() => {
            EntryState.formData.media = [...EntryState.mediaUpload.mediaItems];
        });
    }

    // Sync current entry subjects to MediaUpload and notes (for existing entries or if subjects already added)
    syncMediaUploadSubjects();
    syncNoteSubjects();

    console.log('📷 Media upload component initialized');
}

// =========================================================================
// Initialization
// =========================================================================

async function initializeEntryPage() {
    console.log('🚀 Initializing question entry page...');
    
    // Get session ID from URL (support both 'session_id' and 'session' params)
    const sessionId = getUrlParam('session_id') || getUrlParam('session');
    const editEntryId = getUrlParam('entry');
    const isEditMode = getUrlParam('edit') === 'true' || !!editEntryId;
    
    console.log('🔧 DEBUG: URL params - sessionId:', sessionId, 'editEntryId:', editEntryId, 'isEditMode:', isEditMode);
    
    if (!sessionId) {
        console.error('❌ DEBUG: No session ID found in URL!');
        console.error('❌ DEBUG: Current URL:', window.location.href);
        console.error('❌ DEBUG: Search params:', window.location.search);
        Toast.error('Missing Session', 'No session selected. Redirecting...');
        setTimeout(() => {
            window.location.href = 'index.html';
        }, 1500);
        return;
    }
    
    EntryState.sessionId = parseInt(sessionId);
    EntryState.editEntryId = editEntryId ? parseInt(editEntryId) : null;
    EntryState.isEditMode = isEditMode;
    
    try {
        await api.ready();
        
        // Load session data
        EntryState.session = await api.getReviewSession(EntryState.sessionId);
        
        if (!EntryState.session) {
            Toast.error('Session Not Found', 'The session could not be loaded.');
            setTimeout(() => {
                window.location.href = 'index.html';
            }, 1500);
            return;
        }
        
        // Load exam context
        EntryState.examContext = await api.getExamContext(EntryState.session.exam_context_id);
        
        // Update header
        document.getElementById('session-name').textContent = EntryState.session.session_name || 'Review Session';
        document.getElementById('exam-badge').textContent = EntryState.examContext?.exam_name || 'Exam';

        // Initialize rich text editors BEFORE loading entries (they need to be ready to receive content)
        initRichTextEditors();

        // Load existing entries
        await loadSessionEntries();

        // Determine which entry to show
        const mode = getUrlParam('mode');
        
        console.log('🔧 DEBUG: Determining entry to show - mode:', mode, 'editEntryId:', EntryState.editEntryId, 'entries:', EntryState.entries.length);
        
        if (EntryState.editEntryId) {
            // Edit specific entry - came from entry detail page
            console.log('🔧 DEBUG: Loading specific entry for edit:', EntryState.editEntryId);
            const targetEntry = EntryState.entries.find(e => e.id === EntryState.editEntryId);
            if (targetEntry) {
                await loadExistingEntry(targetEntry.id);
                EntryState.currentEntryIndex = targetEntry.entry_order - 1;
            } else {
                // Entry not in list, try loading directly
                await loadExistingEntry(EntryState.editEntryId);
                EntryState.currentEntryIndex = 0;
            }
        } else if (mode === 'view' && EntryState.entries.length > 0) {
            // View mode - show first entry
            await loadExistingEntry(EntryState.entries[0].id);
            EntryState.currentEntryIndex = 0;
        } else {
            // Edit mode - find first incomplete or create new
            const incompleteEntry = EntryState.entries.find(e => e.is_draft);
            if (incompleteEntry) {
                await loadExistingEntry(incompleteEntry.id);
                EntryState.currentEntryIndex = incompleteEntry.entry_order - 1;
            } else if (EntryState.entries.length < EntryState.session.total_incorrect) {
                // Need to create new entry
                EntryState.currentEntryIndex = EntryState.entries.length;
                resetFormForNewEntry();
            } else if (EntryState.entries.length > 0) {
                // All entries complete, show first
                await loadExistingEntry(EntryState.entries[0].id);
                EntryState.currentEntryIndex = 0;
            } else {
                // No entries, start fresh
                resetFormForNewEntry();
            }
        }
        
        // Render navigation
        renderEntryNavigation();
        
        // Load tag hierarchy
        await loadTagHierarchy();
        
        // Load all subjects for fuzzy search (Stage 4)
        await loadAllSubjectsForFuzzySearch();
        
        // Initialize tag fuzzy search index (Stage 4)
        if (typeof fuzzySearch !== 'undefined' && EntryState.tagHierarchy) {
            fuzzySearch.initTagIndex(EntryState.tagHierarchy);
        }
        
        // Initialize components
        initDifficultyRating();
        initSubjectSearch();
        initQuickAddSubject();
        initTagSearch();
        initCharacterCounts();
        initFormInputHandlers();
        initMediaUpload();
        initAddEntries();
        initSectionTabNavigation();
        await initSessionTimer();
        setupTimerHotkeys();

        // Set up event handlers
        document.getElementById('btn-back').addEventListener('click', handleBackButton);
        document.getElementById('btn-save-draft').addEventListener('click', () => saveEntryAsDraft(false));
        document.getElementById('btn-save-next').addEventListener('click', saveEntryAndNext);
        document.getElementById('btn-prev-entry').addEventListener('click', navigateToPrevEntry);
        document.getElementById('btn-next-entry').addEventListener('click', navigateToNextEntry);
        
        // Start auto-save
        startAutoSave();
        
        // Initial validation
        validateForm();
        
        EntryState.isLoading = false;
        console.log('✅ Question entry page initialized');
        
    } catch (error) {
        console.error('Error initializing entry page:', error);
        Toast.error('Initialization Failed', error.message);
    }
}

// =========================================================================
// Add Entries Feature
// =========================================================================

function toggleAddEntriesPopover() {
    const popover = document.getElementById('add-entries-popover');
    if (!popover) return;

    if (popover.style.display === 'none') {
        // Position near the button
        const btn = document.getElementById('btn-add-entries');
        if (btn) {
            const rect = btn.getBoundingClientRect();
            popover.style.top = (rect.bottom + 4) + 'px';
            popover.style.right = (window.innerWidth - rect.right) + 'px';
        }
        document.getElementById('add-entries-count').value = 1;
        popover.style.display = 'block';
        document.getElementById('add-entries-count').focus();
    } else {
        popover.style.display = 'none';
    }
}

async function confirmAddEntries() {
    const countInput = document.getElementById('add-entries-count');
    const count = parseInt(countInput?.value);

    if (!count || count < 1 || count > 50) {
        Toast.warning('Invalid Count', 'Please enter a number between 1 and 50.');
        return;
    }

    try {
        const session = EntryState.session;
        if (!session) return;

        const newTotal = session.total_incorrect + count;
        const updates = { total_incorrect: newTotal };

        // If session was completed, revert to in_progress
        if (session.session_status === 'completed') {
            updates.session_status = 'in_progress';
            updates.completed_at = null;
        }

        const updated = await api.updateReviewSession(EntryState.sessionId, updates);
        EntryState.session = updated;

        // Close popover
        document.getElementById('add-entries-popover').style.display = 'none';

        // Regenerate navigation
        renderEntryNavigation();

        Toast.success('Entries Added', `Added ${count} entry slot${count > 1 ? 's' : ''}. Total: ${newTotal}`);
    } catch (error) {
        console.error('Error adding entries:', error);
        Toast.error('Error', 'Failed to add entries: ' + error.message);
    }
}

function initAddEntries() {
    document.getElementById('btn-add-entries')?.addEventListener('click', toggleAddEntriesPopover);
    document.getElementById('add-entries-confirm')?.addEventListener('click', confirmAddEntries);
    document.getElementById('add-entries-cancel')?.addEventListener('click', () => {
        document.getElementById('add-entries-popover').style.display = 'none';
    });

    // Close popover on outside click
    document.addEventListener('mousedown', (e) => {
        const popover = document.getElementById('add-entries-popover');
        const btn = document.getElementById('btn-add-entries');
        if (popover && popover.style.display !== 'none' &&
            !popover.contains(e.target) && !btn?.contains(e.target)) {
            popover.style.display = 'none';
        }
    });

    // Enter key submits
    document.getElementById('add-entries-count')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            confirmAddEntries();
        }
    });
}

// =========================================================================
// Session Countdown Timer
// =========================================================================

async function initSessionTimer() {
    const session = EntryState.session;
    if (!session || !session.session_duration_minutes) return;

    const timerEl = document.getElementById('session-timer');
    const pauseBtn = document.getElementById('btn-timer-pause');
    const newRoundBtn = document.getElementById('btn-new-round');
    if (!timerEl) return;

    timerEl.style.display = 'flex';

    // Load user preferences for timer display size & break intervals
    try {
        const prefs = await api.getUserPreferences();
        EntryState.userPreferences = prefs;
        if (prefs && prefs.timer_display_size === 'large') {
            timerEl.classList.add('timer-large');
        }
    } catch (err) {
        console.warn('Failed to load user preferences for timer:', err);
    }

    // Load active round from session response
    const round = session.active_round || null;
    EntryState.activeRound = round;

    if (round) {
        // Active round exists — show pause button, hide new-round button
        pauseBtn.style.display = '';
        newRoundBtn.style.display = 'none';

        EntryState.timerPaused = !!round.timer_paused_at;

        // Auto-resume if timer was auto-paused on previous navigation away
        const autoPauseKey = `wimi_timer_auto_paused_${EntryState.sessionId}`;
        if (sessionStorage.getItem(autoPauseKey) && EntryState.timerPaused) {
            sessionStorage.removeItem(autoPauseKey);
            try {
                const result = await api.unpauseRoundTimer(round.id);
                if (result) {
                    round.total_break_seconds = result.total_break_seconds;
                    round.timer_paused_at = result.timer_paused_at;
                }
                EntryState.timerPaused = false;
            } catch (err) {
                console.warn('Failed to auto-resume timer on return:', err);
            }
        }

        if (EntryState.timerPaused) {
            timerEl.classList.add('timer-paused');
            document.getElementById('timer-pause-icon').innerHTML = '&#x25B6;';
            pauseBtn.title = 'Resume timer';
        }
        EntryState.timerExpired = false;
    } else {
        // No active round (all ended or none) — show new-round button
        pauseBtn.style.display = 'none';
        newRoundBtn.style.display = '';
        EntryState.timerExpired = true;
        timerEl.classList.add('timer-expired');
        document.getElementById('timer-display').textContent = '00:00';
    }

    updateRoundIndicator();

    pauseBtn.addEventListener('click', toggleTimerPause);
    newRoundBtn.addEventListener('click', showNewRoundDialog);

    updateTimerDisplay();
    EntryState.timerIntervalId = setInterval(updateTimerDisplay, 1000);
}

/**
 * Normalize a SQLite datetime string to a valid ISO 8601 UTC string.
 * SQLite datetime('now') returns "2026-03-12 14:30:00" (space, no T, no Z).
 * JS Date requires "2026-03-12T14:30:00Z" for reliable cross-engine parsing.
 */
function toISOUTC(str) {
    if (!str) return str;
    return str.replace(' ', 'T').replace(/T(\d{2}:\d{2}:\d{2})$/, 'T$1Z');
}

function calculateRemainingSeconds() {
    const round = EntryState.activeRound;
    if (!round) return null;

    const startedAt = new Date(toISOUTC(round.started_at)).getTime();
    const totalDurationSec = round.duration_minutes * 60;
    const breakSeconds = round.total_break_seconds || 0;

    let referenceTime;
    if (EntryState.timerPaused && round.timer_paused_at) {
        referenceTime = new Date(toISOUTC(round.timer_paused_at)).getTime();
    } else {
        referenceTime = Date.now();
    }

    const elapsedSec = (referenceTime - startedAt) / 1000;
    const effectiveElapsed = elapsedSec - breakSeconds;
    return totalDurationSec - effectiveElapsed;
}

function updateTimerDisplay() {
    const displayEl = document.getElementById('timer-display');
    const timerEl = document.getElementById('session-timer');
    if (!displayEl || !timerEl) return;

    // Break countdown mode
    if (EntryState.breakActive && EntryState.breakEndTime) {
        const breakRemaining = (EntryState.breakEndTime - Date.now()) / 1000;
        timerEl.classList.remove('timer-warning', 'timer-critical', 'timer-expired');
        timerEl.classList.add('timer-break');

        if (breakRemaining <= 0) {
            // Break is over
            EntryState.breakActive = false;
            EntryState.breakEndTime = null;
            timerEl.classList.remove('timer-break');
            Toast.info('Break Over', 'Break time is up! Ready for the next round?');
            showNewRoundDialog();
            return;
        }

        const bSec = Math.ceil(breakRemaining);
        const bMin = Math.floor(bSec / 60);
        const bS = bSec % 60;
        displayEl.textContent = `${String(bMin).padStart(2, '0')}:${String(bS).padStart(2, '0')}`;
        return;
    }

    const remaining = calculateRemainingSeconds();
    if (remaining === null) return;

    timerEl.classList.remove('timer-warning', 'timer-critical', 'timer-expired', 'timer-break');

    if (remaining <= 0) {
        displayEl.textContent = '00:00';
        timerEl.classList.add('timer-expired');

        if (!EntryState.timerExpired) {
            EntryState.timerExpired = true;
            // End the round on the backend
            const endedRoundNumber = EntryState.activeRound ? EntryState.activeRound.round_number : 1;
            if (EntryState.activeRound) {
                var _endedRoundId = EntryState.activeRound.id;
                api.endTimerRound(_endedRoundId).then(function() {
                    if (window.eventBus) eventBus.emit('timer:ended', { roundId: _endedRoundId });
                }).catch(function(err) {
                    console.error('Failed to end timer round:', err);
                });
                EntryState.activeRound = null;
            }
            // Swap buttons: hide pause, show new-round
            const pauseBtn = document.getElementById('btn-timer-pause');
            const newRoundBtn = document.getElementById('btn-new-round');
            if (pauseBtn) pauseBtn.style.display = 'none';
            if (newRoundBtn) newRoundBtn.style.display = '';

            showRoundCompleteOverlay(endedRoundNumber);
        }
        return;
    }

    const totalSec = Math.ceil(remaining);
    const hours = Math.floor(totalSec / 3600);
    const minutes = Math.floor((totalSec % 3600) / 60);
    const seconds = totalSec % 60;

    if (hours > 0) {
        displayEl.textContent = `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    } else {
        displayEl.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

    if (remaining < 60) {
        timerEl.classList.add('timer-critical');
    } else if (remaining < 300) {
        timerEl.classList.add('timer-warning');
    }
}

async function toggleTimerPause() {
    const round = EntryState.activeRound;
    if (!round) return;

    const timerEl = document.getElementById('session-timer');
    const iconEl = document.getElementById('timer-pause-icon');
    const pauseBtn = document.getElementById('btn-timer-pause');
    if (!timerEl) return;

    try {
        let result;
        if (EntryState.timerPaused) {
            result = await api.unpauseRoundTimer(round.id);
            EntryState.timerPaused = false;
            timerEl.classList.remove('timer-paused');
            iconEl.innerHTML = '&#x23F8;';
            pauseBtn.title = 'Pause timer';
            if (window.eventBus) eventBus.emit('timer:resumed', { roundId: round.id });
        } else {
            result = await api.pauseRoundTimer(round.id);
            EntryState.timerPaused = true;
            timerEl.classList.add('timer-paused');
            iconEl.innerHTML = '&#x25B6;';
            pauseBtn.title = 'Resume timer';
            if (window.eventBus) eventBus.emit('timer:paused', { roundId: round.id });
        }

        if (result) {
            EntryState.activeRound.total_break_seconds = result.total_break_seconds;
            EntryState.activeRound.timer_paused_at = result.timer_paused_at;
        }

        updateTimerDisplay();
    } catch (err) {
        console.error('Failed to toggle timer pause:', err);
    }
}

function updateRoundIndicator() {
    const el = document.getElementById('round-indicator');
    if (!el) return;
    const round = EntryState.activeRound;
    // Also check completed rounds to determine highest round_number
    // For simplicity, derive from activeRound or hide if round 1
    if (round && round.round_number > 1) {
        el.textContent = `R${round.round_number}`;
        el.style.display = '';
    } else {
        el.style.display = 'none';
    }
}

function showNewRoundDialog() {
    const overlay = document.getElementById('new-round-dialog-overlay');
    const input = document.getElementById('new-round-duration');
    if (!overlay || !input) return;

    // Pre-fill with session default duration
    const defaultMin = (EntryState.session && EntryState.session.session_duration_minutes) || 30;
    input.value = defaultMin;
    overlay.style.display = 'flex';
    input.focus();
    input.select();
}

async function startNewRound() {
    const input = document.getElementById('new-round-duration');
    const overlay = document.getElementById('new-round-dialog-overlay');
    const duration = parseInt(input.value, 10);
    if (!duration || duration < 1) {
        Toast.error('Invalid Duration', 'Please enter a positive number of minutes.');
        return;
    }

    overlay.style.display = 'none';

    try {
        const round = await api.createTimerRound(EntryState.sessionId, duration);
        if (!round) {
            Toast.error('Error', 'Failed to create new timer round.');
            return;
        }
        if (window.eventBus) eventBus.emit('timer:started', { roundId: round.id, sessionId: EntryState.sessionId });
        EntryState.activeRound = round;
        EntryState.timerExpired = false;
        EntryState.timerPaused = false;

        const timerEl = document.getElementById('session-timer');
        const pauseBtn = document.getElementById('btn-timer-pause');
        const newRoundBtn = document.getElementById('btn-new-round');
        const iconEl = document.getElementById('timer-pause-icon');

        if (timerEl) timerEl.classList.remove('timer-expired', 'timer-paused', 'timer-warning', 'timer-critical');
        if (pauseBtn) { pauseBtn.style.display = ''; }
        if (newRoundBtn) { newRoundBtn.style.display = 'none'; }
        if (iconEl) { iconEl.innerHTML = '&#x23F8;'; }

        updateRoundIndicator();
        updateTimerDisplay();

        Toast.success('New Round', `Round ${round.round_number} started (${duration} min).`);
    } catch (err) {
        console.error('Failed to start new round:', err);
        Toast.error('Error', 'Failed to start new timer round.');
    }
}

function cancelNewRound() {
    const overlay = document.getElementById('new-round-dialog-overlay');
    if (overlay) overlay.style.display = 'none';
}

function showRoundCompleteOverlay(roundNumber) {
    const overlay = document.getElementById('round-complete-overlay');
    if (!overlay) return;

    const prefs = EntryState.userPreferences || {};
    const longBreakInterval = prefs.long_break_interval_rounds || 4;
    const isLongBreak = roundNumber > 0 && (roundNumber % longBreakInterval === 0);

    const messageEl = document.getElementById('round-complete-message');
    const breakInput = document.getElementById('break-duration-input');

    if (isLongBreak) {
        messageEl.textContent = `You've completed ${roundNumber} rounds — time for a long break!`;
        breakInput.value = prefs.default_long_break_minutes || 15;
    } else {
        messageEl.textContent = 'Great work! Take a short break.';
        breakInput.value = prefs.default_break_interval_minutes || 5;
    }

    overlay.style.display = 'flex';
    breakInput.focus();
    breakInput.select();
}

function startBreakFromModal() {
    const breakInput = document.getElementById('break-duration-input');
    const overlay = document.getElementById('round-complete-overlay');
    const duration = parseInt(breakInput.value, 10);
    if (!duration || duration < 1) {
        Toast.error('Invalid Duration', 'Please enter a positive number of minutes.');
        return;
    }

    overlay.style.display = 'none';

    EntryState.breakActive = true;
    EntryState.breakEndTime = Date.now() + duration * 60000;

    const timerEl = document.getElementById('session-timer');
    if (timerEl) {
        timerEl.classList.remove('timer-expired', 'timer-warning', 'timer-critical', 'timer-paused');
        timerEl.classList.add('timer-break');
    }

    // Hide pause and new-round buttons during break
    const pauseBtn = document.getElementById('btn-timer-pause');
    const newRoundBtn = document.getElementById('btn-new-round');
    if (pauseBtn) pauseBtn.style.display = 'none';
    if (newRoundBtn) newRoundBtn.style.display = 'none';

    Toast.info('Break Started', `${duration} minute break started.`);
}

function skipBreakNewRound() {
    const overlay = document.getElementById('round-complete-overlay');
    if (overlay) overlay.style.display = 'none';
    showNewRoundDialog();
}

function endTimerFromModal() {
    const overlay = document.getElementById('round-complete-overlay');
    if (overlay) overlay.style.display = 'none';
    // Timer stays expired, user can click refresh to reopen overlay later
}

async function endCurrentRoundEarly() {
    const round = EntryState.activeRound;
    if (!round) return;

    try {
        await api.endTimerRound(round.id);
        if (window.eventBus) eventBus.emit('timer:ended', { roundId: round.id });
    } catch (err) {
        console.error('Failed to end timer round early:', err);
    }

    const endedRoundNumber = round.round_number || 1;
    EntryState.activeRound = null;
    EntryState.timerExpired = true;
    EntryState.timerPaused = false;

    const timerEl = document.getElementById('session-timer');
    if (timerEl) {
        timerEl.classList.remove('timer-warning', 'timer-critical', 'timer-paused');
        timerEl.classList.add('timer-expired');
    }
    const displayEl = document.getElementById('timer-display');
    if (displayEl) displayEl.textContent = '00:00';

    const pauseBtn = document.getElementById('btn-timer-pause');
    const newRoundBtn = document.getElementById('btn-new-round');
    if (pauseBtn) pauseBtn.style.display = 'none';
    if (newRoundBtn) newRoundBtn.style.display = '';

    showRoundCompleteOverlay(endedRoundNumber);
}

function _buildComboString(e) {
    const parts = [];
    if (e.ctrlKey) parts.push('Ctrl');
    if (e.altKey) parts.push('Alt');
    if (e.shiftKey) parts.push('Shift');
    if (e.metaKey) parts.push('Meta');

    let key = e.key;
    if (key === ' ') key = 'Space';
    else if (key.length === 1) key = key.toUpperCase();

    parts.push(key);
    return parts.join('+');
}

function setupTimerHotkeys() {
    // Remove previous handler if re-initializing
    if (EntryState._timerHotkeyHandler) {
        document.removeEventListener('keydown', EntryState._timerHotkeyHandler);
        EntryState._timerHotkeyHandler = null;
    }

    const prefs = EntryState.userPreferences || {};
    const bindings = {};

    if (prefs.hotkey_timer_pause_resume) {
        bindings[prefs.hotkey_timer_pause_resume] = toggleTimerPause;
    }
    if (prefs.hotkey_timer_new_round) {
        bindings[prefs.hotkey_timer_new_round] = showNewRoundDialog;
    }
    if (prefs.hotkey_timer_end_round) {
        bindings[prefs.hotkey_timer_end_round] = endCurrentRoundEarly;
    }

    if (Object.keys(bindings).length === 0) return;

    const handler = (e) => {
        // Skip when focused in form fields or contentEditable
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (document.activeElement?.isContentEditable) return;

        // Skip when any modal overlay is visible
        const overlays = document.querySelectorAll('[id$="-overlay"], .modal-overlay');
        for (const ov of overlays) {
            if (ov.style.display && ov.style.display !== 'none') return;
        }

        const combo = _buildComboString(e);
        const action = bindings[combo];
        if (action) {
            e.preventDefault();
            e.stopPropagation();
            action();
        }
    };

    document.addEventListener('keydown', handler);
    EntryState._timerHotkeyHandler = handler;
}

async function autoSuspendTimerForNavigation() {
    if (EntryState.activeRound && !EntryState.timerPaused && !EntryState.timerExpired) {
        const key = `wimi_timer_auto_paused_${EntryState.sessionId}`;
        sessionStorage.setItem(key, 'true');
        try {
            const result = await api.pauseRoundTimer(EntryState.activeRound.id);
            if (result) {
                EntryState.activeRound.total_break_seconds = result.total_break_seconds;
                EntryState.activeRound.timer_paused_at = result.timer_paused_at;
            }
            EntryState.timerPaused = true;
        } catch (err) {
            console.warn('Failed to auto-pause timer on navigation:', err);
        }
    }
}

function stopSessionTimer() {
    if (EntryState.timerIntervalId) {
        clearInterval(EntryState.timerIntervalId);
        EntryState.timerIntervalId = null;
    }
}

// =========================================================================
// Expose Global Functions
// =========================================================================

window.toggleSection = toggleSection;
window.handleSectionKeydown = handleSectionKeydown;
window.selectSubject = selectSubject;
window.removeSubject = removeSubject;
window.toggleTag = toggleTag;
window.removeTag = removeTag;
window.selectTagFromDropdown = selectTagFromDropdown;
window.createTagInline = createTagInline;
window.updateSelectedCreateGroup = updateSelectedCreateGroup;
window.navigateToEntry = navigateToEntry;
window.dismissKeyboardHint = dismissKeyboardHint;
window.startNewRound = startNewRound;
window.cancelNewRound = cancelNewRound;

// =========================================================================
// Page Initialization
// =========================================================================

document.addEventListener('DOMContentLoaded', initializeEntryPage);

// Cleanup on page unload
window.addEventListener('beforeunload', (e) => {
    stopAutoSave();
    stopSessionTimer();

    // Best-effort auto-pause for edge cases (OS back, app close) where
    // user-initiated navigation hooks don't fire
    if (EntryState.activeRound && !EntryState.timerPaused && !EntryState.timerExpired) {
        sessionStorage.setItem(`wimi_timer_auto_paused_${EntryState.sessionId}`, 'true');
        api.pauseRoundTimer(EntryState.activeRound.id).catch(() => {});
    }

    if (EntryState.isDirty) {
        e.preventDefault();
        e.returnValue = '';
    }
});
