/**
 * Exam Setup Wizard
 * Multi-step wizard for creating exam contexts
 * 
 * Phase 7.2: Updated to support multi-dimensional exam type selection
 */

class ExamWizard {
    constructor() {
        // Step configuration based on exam type.
        // Step 'length' (Stage 4 of HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md
        // §3.2/§7.4) sits between hierarchy and weights — it captures the
        // exam-length triple that downstream stages consume for question-count
        // grounding and Hamilton allocation. Persisted via api.updateExamLength
        // after the exam context itself is created (handled in createNewExam).
        this.stepConfigs = {
            simple: {
                steps: ['type', 'template', 'info', 'hierarchy', 'length', 'weights', 'review'],
                stepIds: ['step-1', 'step-1-template', 'step-2', 'step-3', 'step-exam-length', 'step-4', 'step-5'],
                labels: ['Exam Type', 'Template', 'Exam Info', 'Hierarchy', 'Length', 'Weights', 'Review'],
                totalSteps: 7
            },
            multi_dimensional: {
                steps: ['type', 'template', 'info', 'dimensions', 'hierarchy', 'length', 'weights', 'review'],
                stepIds: ['step-1', 'step-1-template', 'step-2', 'step-3-dimensions', 'step-3', 'step-exam-length', 'step-4', 'step-5'],
                labels: ['Exam Type', 'Template', 'Exam Info', 'Dimensions', 'Hierarchy', 'Length', 'Weights', 'Review'],
                totalSteps: 8
            }
        };

        this.currentStep = 1;
        this.isEditMode = false;
        this.editExamId = null;

        // Template system properties
        this.templates = [];           // All loaded templates
        this.filteredTemplates = [];   // Templates filtered by exam type and search
        this.selectedTemplateId = null; // Currently selected template ID (null = scratch)
        this.templateCategoryFilter = 'all';
        this.templateSearchQuery = '';
        this.originalTemplateData = null; // Store original template data for reset functionality
        this.templateModified = false;    // Track if user has modified template data

        this.data = {
            examType: 'simple',  // 'simple' or 'multi_dimensional'
            examName: '',
            examDescription: '',
            examDate: '',
            notes: '',
            hierarchyLevels: ['System', 'Subsystem', 'Topic', 'Subtopic', 'Child'],
            dimensions: [],  // For multi-dimensional exams
            weightSettings: {
                autonomousBalancing: true,
                precision: 1,
                balancingAlgorithm: 'proportional'
            },
            // Stage 4: exam-length triple (HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md §3.2)
            // 'unknown' is the safe default — wizard skip-friendly and matches
            // the migration's column default.
            examLength: {
                kind: 'unknown',
                min: null,
                max: null,
                typical: null,
                note: ''
            },
            templateId: null,  // Track which template was used (for reference only)
            templateModified: false  // Track if template data has been modified
        };

        this.init();
    }
    
    get currentConfig() {
        return this.stepConfigs[this.data.examType];
    }
    
    get totalSteps() {
        return this.currentConfig.totalSteps;
    }
    
    async init() {
        // Check for edit mode
        const urlParams = new URLSearchParams(window.location.search);
        const editId = urlParams.get('edit');

        if (editId) {
            this.isEditMode = true;
            this.editExamId = parseInt(editId);
            this.updateUIForEditMode();
        }

        // Load templates (non-blocking - continues even if fails)
        this.loadTemplates().catch(err => {
            console.warn('Failed to load templates:', err);
        });

        // Setup event listeners
        this.setupEventListeners();

        // Initialize UI
        this.renderHierarchyLevels();
        this.updateAlgorithmPreview();
        this.updateProgressBar();

        // If editing, load existing data
        if (this.isEditMode) {
            await this.loadExistingExam();
        }

        console.log(`Exam Wizard initialized (${this.isEditMode ? 'Edit' : 'Create'} mode)`);
    }
    
    updateUIForEditMode() {
        // Update page title
        document.title = 'Edit Exam - WIMI';
        
        // Update wizard header
        const headerTitle = document.querySelector('.wizard-header h1');
        if (headerTitle) {
            headerTitle.textContent = 'Edit Exam';
        }
        const headerSubtitle = document.querySelector('.wizard-header p');
        if (headerSubtitle) {
            headerSubtitle.textContent = 'Update your exam configuration and settings.';
        }
        
        // Update Create button text
        const btnCreate = document.getElementById('btn-create');
        if (btnCreate) {
            const btnText = btnCreate.querySelector('.btn-text');
            if (btnText) {
                btnText.textContent = 'Save Changes';
            }
        }
    }
    
    async loadExistingExam() {
        try {
            // Wait for API
            await api.ready();
            
            // Fetch exam data
            const exam = await api.getExamContext(this.editExamId);
            
            if (!exam) {
                throw new Error('Exam not found');
            }
            
            // Populate data object
            this.data.examName = exam.exam_name || '';
            this.data.examDescription = exam.exam_description || '';
            this.data.examDate = exam.exam_date || '';
            this.data.notes = exam.notes || '';
            
            // Determine exam type based on dimensions
            try {
                const { uses_dimensions } = await api.examUsesDimensions(this.editExamId);
                this.data.examType = uses_dimensions ? 'multi_dimensional' : 'simple';
                
                // Load existing dimensions if multi-dimensional
                if (uses_dimensions) {
                    const dimensions = await api.getDimensions(this.editExamId);
                    this.data.dimensions = dimensions.map(dim => ({
                        id: dim.id,
                        dbId: dim.id,  // Track the database ID for updates
                        name: dim.name,
                        description: dim.description || '',
                        isRequired: dim.is_required,
                        allowMultiple: dim.allow_multiple,
                        displayOrder: dim.display_order
                    }));
                    console.log('📊 Loaded dimensions:', this.data.dimensions);
                }
            } catch (dimError) {
                console.warn('Could not check dimensions (may be legacy exam):', dimError);
                this.data.examType = 'simple';
            }
            
            // Populate hierarchy levels if available
            if (exam.hierarchy_levels && Array.isArray(exam.hierarchy_levels)) {
                this.data.hierarchyLevels = exam.hierarchy_levels;
            }
            
            // Populate weight settings
            this.data.weightSettings = {
                autonomousBalancing: exam.autonomous_balancing !== false,
                precision: exam.precision ?? 1,
                balancingAlgorithm: exam.balancing_algorithm || 'proportional'
            };

            // Stage 4 — load the exam-length triple so the length step
            // pre-fills with the existing values when the user edits.
            try {
                const length = await api.getExamLength(this.editExamId);
                this.data.examLength = {
                    kind: (length && length.kind) || 'unknown',
                    min: length ? length.min : null,
                    max: length ? length.max : null,
                    typical: length ? length.typical : null,
                    note: (length && length.note) || ''
                };
            } catch (lengthError) {
                console.warn('Could not load exam length:', lengthError);
            }

            // Update form fields
            this.populateFormFields();

            // In edit mode, skip type selection and template selection (can't change exam type)
            // Step 1 = type, Step 2 = template, Step 3 = info
            this.currentStep = 3;
            this.updateUI();

            console.log('Loaded existing exam data:', this.data);
            
        } catch (error) {
            console.error('Error loading exam:', error);
            alert(`Failed to load exam: ${error.message}`);
            this.goHome();
        }
    }
    
    populateFormFields() {
        // Step 2: Basic Info
        document.getElementById('exam-name').value = this.data.examName;
        document.getElementById('exam-description').value = this.data.examDescription;
        document.getElementById('exam-date').value = this.data.examDate;
        document.getElementById('exam-notes').value = this.data.notes;
        
        // Step 3: Hierarchy (re-render)
        this.renderHierarchyLevels();
        
        // Weight Settings
        const autonomousToggle = document.getElementById('autonomous-balancing');
        autonomousToggle.checked = this.data.weightSettings.autonomousBalancing;
        autonomousToggle.closest('.toggle')?.classList.toggle('is-checked', this.data.weightSettings.autonomousBalancing);
        
        // Update precision select
        const precisionSelect = document.getElementById('weight-precision-select');
        if (precisionSelect) {
            precisionSelect.dataset.value = this.data.weightSettings.precision;
            const precisionLabels = {
                0: 'Whole numbers (0)',
                1: 'One decimal (0.0)',
                2: 'Two decimals (0.00)'
            };
            const valueDisplay = precisionSelect.querySelector('.custom-select-value');
            if (valueDisplay) {
                valueDisplay.textContent = precisionLabels[this.data.weightSettings.precision];
            }
            // Update selected option
            precisionSelect.querySelectorAll('.custom-select-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.value === String(this.data.weightSettings.precision));
            });
        }
        
        // Update algorithm select
        const algorithmSelect = document.getElementById('balancing-algorithm-select');
        if (algorithmSelect) {
            algorithmSelect.dataset.value = this.data.weightSettings.balancingAlgorithm;
            const algorithmLabels = {
                'proportional': 'Proportional Distribution',
                'even': 'Even Distribution'
            };
            const valueDisplay = algorithmSelect.querySelector('.custom-select-value');
            if (valueDisplay) {
                valueDisplay.textContent = algorithmLabels[this.data.weightSettings.balancingAlgorithm];
            }
            // Update selected option
            algorithmSelect.querySelectorAll('.custom-select-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.value === this.data.weightSettings.balancingAlgorithm);
            });
        }
        
        this.updateAlgorithmPreview();
    }
    
    setupEventListeners() {
        // Navigation buttons
        document.getElementById('btn-next').addEventListener('click', () => this.nextStep());
        document.getElementById('btn-back').addEventListener('click', () => this.prevStep());
        document.getElementById('btn-create').addEventListener('click', () => this.createExam());
        
        // Cancel/Exit button
        document.getElementById('btn-cancel').addEventListener('click', () => this.confirmCancel());
        
        // Exam type selection (Step 1)
        this.setupExamTypeSelection();
        
        // Learn More modals
        this.setupLearnMoreModals();
        
        // Form validation on input with template modification tracking
        document.getElementById('exam-name').addEventListener('input', (e) => {
            this.data.examName = e.target.value.trim();
            this.validateCurrentStep();
            this.markTemplateModified();
        });

        document.getElementById('exam-description').addEventListener('input', (e) => {
            this.markTemplateModified();
        });

        document.getElementById('exam-date').addEventListener('change', (e) => {
            this.markTemplateModified();
        });

        document.getElementById('exam-notes').addEventListener('input', (e) => {
            this.markTemplateModified();
        });
        
        // Settings changes - Toggle switch with explicit visual update
        const autonomousToggle = document.getElementById('autonomous-balancing');
        autonomousToggle.addEventListener('change', (e) => {
            this.data.weightSettings.autonomousBalancing = e.target.checked;
            // Force visual update by toggling a class on the parent
            e.target.closest('.toggle').classList.toggle('is-checked', e.target.checked);
            this.markTemplateModified();
        });
        // Initialize toggle visual state
        if (autonomousToggle.checked) {
            autonomousToggle.closest('.toggle').classList.add('is-checked');
        }
        
        // Custom select dropdowns
        this.initCustomSelects();
        
        // Dimension management (for multi-dimensional exams)
        this.setupDimensionListeners();
        
        // Modal buttons
        document.getElementById('btn-continue').addEventListener('click', () => {
            this.goHome();
        });

        document.getElementById('btn-dismiss-error').addEventListener('click', () => {
            document.getElementById('error-modal').classList.add('hidden');
        });

        // Template reset button
        const resetBtn = document.getElementById('btn-reset-template');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => this.resetToTemplateDefaults());
        }

        // Stage 4: Exam-length step radio + numeric inputs.
        this.setupExamLengthListeners();
    }

    /**
     * Stage 4 — wire the exam-length step.
     * Radio change toggles the visible field group; numeric inputs
     * stream into ``this.data.examLength`` so saveStepData has the
     * canonical state when the user clicks Next.
     *
     * Stage 8 — the CAT radio also refreshes the planning-baseline
     * copy so the user sees the right typical/min/max values per
     * design §7.4.
     */
    setupExamLengthListeners() {
        const radios = document.querySelectorAll('input[name="exam-length-kind"]');
        radios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                if (!e.target.checked) return;
                this.data.examLength.kind = e.target.value;
                this.updateExamLengthFieldVisibility();
                this.updatePlanningBaselineCopy();
                this.markTemplateModified();
            });
        });

        const wireNumeric = (id, key) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.addEventListener('input', (e) => {
                const raw = e.target.value;
                this.data.examLength[key] = raw === '' ? null : parseInt(raw, 10);
                this.updatePlanningBaselineCopy();
                this.markTemplateModified();
            });
        };
        wireNumeric('exam-length-fixed-typical', 'typical');
        wireNumeric('exam-length-range-min', 'min');
        wireNumeric('exam-length-range-typical', 'typical');
        wireNumeric('exam-length-range-max', 'max');

        const noteEl = document.getElementById('exam-length-note');
        if (noteEl) {
            noteEl.addEventListener('input', (e) => {
                this.data.examLength.note = e.target.value;
                this.markTemplateModified();
            });
        }
    }

    /**
     * Show/hide the fixed vs range field groups based on the current kind.
     */
    updateExamLengthFieldVisibility() {
        const fixed = document.getElementById('exam-length-fields-fixed');
        const range = document.getElementById('exam-length-fields-range');
        const kind = this.data.examLength.kind;
        if (fixed) fixed.classList.toggle('hidden', kind !== 'fixed');
        if (range) range.classList.toggle('hidden', kind !== 'range');
    }

    /**
     * Stage 8 — refresh the CAT (Variable length) planning-baseline
     * help copy per design §7.4:
     *
     *   "Planning baseline: ~{typical} items (actual exam: {min}–{max}).
     *    Use this to budget your study allocation; the real exam ends
     *    when the algorithm reaches a confident decision."
     *
     * Visible only when the CAT radio is active (parent container
     * ``.exam-length-fields-range`` handles visibility via the
     * ``hidden`` class). Falls back to a generic message when the
     * typical/min/max inputs haven't been filled in yet, so the copy
     * isn't broken before the user finishes typing.
     */
    updatePlanningBaselineCopy() {
        const textEl = document.getElementById('exam-length-cat-planning-copy-text');
        if (!textEl) return;
        if (this.data.examLength.kind !== 'range') {
            // Not adaptive — nothing to render (the parent container
            // is hidden anyway, but we reset the text so a later
            // toggle starts from the static fallback).
            return;
        }
        const { typical, min, max } = this.data.examLength || {};
        if (
            typical === null || typical === undefined
            || min === null || min === undefined
            || max === null || max === undefined
        ) {
            textEl.textContent = (
                'Use the typical value to budget your study allocation; '
                + 'the real exam ends when the algorithm reaches a '
                + 'confident decision.'
            );
            return;
        }
        textEl.textContent = (
            `~${typical} items (actual exam: ${min}–${max}). `
            + 'Use this to budget your study allocation; the real exam '
            + 'ends when the algorithm reaches a confident decision.'
        );
    }

    /**
     * Push the current ``this.data.examLength`` state into the form
     * controls. Called when entering the length step (so a pre-fill
     * from a known exam name takes effect on render).
     */
    populateExamLengthFields() {
        const kind = this.data.examLength.kind || 'unknown';
        const radio = document.getElementById(`exam-length-kind-${kind}`);
        if (radio) radio.checked = true;

        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.value = (val === null || val === undefined) ? '' : String(val);
        };
        if (kind === 'fixed') {
            setVal('exam-length-fixed-typical', this.data.examLength.typical);
        } else if (kind === 'range') {
            setVal('exam-length-range-min', this.data.examLength.min);
            setVal('exam-length-range-typical', this.data.examLength.typical);
            setVal('exam-length-range-max', this.data.examLength.max);
        }
        setVal('exam-length-note', this.data.examLength.note || '');

        const errEl = document.getElementById('exam-length-error');
        if (errEl) errEl.classList.add('hidden');

        this.updateExamLengthFieldVisibility();
        // Stage 8 — refresh the CAT planning baseline copy so a
        // pre-filled NCLEX context (e.g. typical=100, min=85,
        // max=150) renders the design §7.4 message immediately.
        this.updatePlanningBaselineCopy();
    }

    /**
     * Pre-fill the length step from the bridge's known-exam-length
     * lookup. Called when the user enters the length step so a typed
     * exam name (e.g. "USMLE Step 1") auto-populates 280/280/280.
     * Only writes when the user hasn't already set a kind.
     */
    async prefillExamLengthFromName() {
        if (this.data.examLength.kind && this.data.examLength.kind !== 'unknown') {
            return;  // user already chose; don't clobber
        }
        if (!this.data.examName || !this.data.examName.trim()) {
            return;
        }
        try {
            const result = await api.getKnownExamLength(this.data.examName);
            if (result && result.found) {
                this.data.examLength = {
                    kind: result.kind,
                    min: result.min ?? null,
                    max: result.max ?? null,
                    typical: result.typical ?? null,
                    note: result.note || ''
                };
                this.populateExamLengthFields();
            }
        } catch (err) {
            console.warn('prefillExamLengthFromName failed:', err);
        }
    }
    
    setupExamTypeSelection() {
        const cards = document.querySelectorAll('.exam-type-card');
        
        cards.forEach(card => {
            card.addEventListener('click', (e) => {
                // Don't trigger if clicking on learn more button
                if (e.target.closest('.btn-learn-more')) return;
                
                const type = card.dataset.type;
                this.selectExamType(type);
            });
        });
    }
    
    selectExamType(type) {
        // Update data
        this.data.examType = type;
        
        // Update radio buttons
        document.getElementById('type-simple').checked = (type === 'simple');
        document.getElementById('type-multi').checked = (type === 'multi_dimensional');
        
        // Update card visual state
        document.querySelectorAll('.exam-type-card').forEach(card => {
            card.classList.toggle('selected', card.dataset.type === type);
        });
        
        // Update progress bar to reflect new step count
        this.updateProgressBar();
        
        console.log(`📋 Exam type selected: ${type}`);
    }
    
    setupLearnMoreModals() {
        // Learn More buttons
        document.querySelectorAll('.btn-learn-more').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation(); // Prevent card selection
                const type = btn.dataset.type;
                const modalId = type === 'simple' ? 'modal-learn-simple' : 'modal-learn-multi';
                document.getElementById(modalId).classList.remove('hidden');
            });
        });
        
        // Close modal buttons
        document.querySelectorAll('.modal-close[data-dismiss="modal"]').forEach(btn => {
            btn.addEventListener('click', () => {
                btn.closest('.modal-backdrop').classList.add('hidden');
            });
        });
        
        // Close on backdrop click
        document.querySelectorAll('.learn-more-modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.classList.add('hidden');
                }
            });
        });
    }
    
    setupDimensionListeners() {
        // Add dimension button
        const btnAdd = document.getElementById('btn-add-dimension');
        if (btnAdd) {
            btnAdd.addEventListener('click', () => this.addDimension());
        }
    }

    // =========================================================================
    // Template System (Phase 7.2 Stage 2.4)
    // =========================================================================

    /**
     * Load templates from JSON file
     */
    async loadTemplates() {
        try {
            const response = await fetch('../../data/exam_templates.json');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            this.templates = data.templates || [];

            console.log(`Loaded ${this.templates.length} exam templates`);

            // Setup template UI event listeners after templates are loaded
            this.setupTemplateListeners();

            // If we're already on the template step, render it
            if (this.getCurrentStepType() === 'template') {
                this.displayTemplates(this.data.examType);
            }

            return this.templates;
        } catch (error) {
            console.error('Error loading templates:', error);
            this.templates = [];
            return [];
        }
    }

    /**
     * Setup event listeners for template selection UI
     */
    setupTemplateListeners() {
        // Start from scratch option
        const scratchOption = document.getElementById('template-scratch');
        if (scratchOption) {
            scratchOption.addEventListener('click', () => {
                this.selectTemplate(null);
            });
        }

        // Search input
        const searchInput = document.getElementById('template-search-input');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.templateSearchQuery = e.target.value.trim().toLowerCase();
                this.filterAndDisplayTemplates();
            });
        }

        // Category filter buttons
        const categoryFilters = document.getElementById('template-category-filters');
        if (categoryFilters) {
            categoryFilters.addEventListener('click', (e) => {
                const btn = e.target.closest('.category-filter-btn');
                if (btn) {
                    // Update active state
                    categoryFilters.querySelectorAll('.category-filter-btn').forEach(b => {
                        b.classList.remove('active');
                    });
                    btn.classList.add('active');

                    // Update filter and re-render
                    this.templateCategoryFilter = btn.dataset.category;
                    this.filterAndDisplayTemplates();
                }
            });
        }
    }

    /**
     * Display templates filtered by exam type
     * @param {string} examType - 'simple' or 'multi_dimensional'
     */
    displayTemplates(examType) {
        // Reset selection to scratch when displaying templates
        this.selectedTemplateId = null;
        this.data.templateId = null;

        // Reset filters
        this.templateSearchQuery = '';
        this.templateCategoryFilter = 'all';

        // Clear search input
        const searchInput = document.getElementById('template-search-input');
        if (searchInput) {
            searchInput.value = '';
        }

        // Reset category filter buttons
        const categoryFilters = document.getElementById('template-category-filters');
        if (categoryFilters) {
            categoryFilters.querySelectorAll('.category-filter-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.category === 'all');
            });
        }

        // Update scratch option selection state
        this.updateScratchOptionState(true);

        // Filter and display
        this.filterAndDisplayTemplates();
    }

    /**
     * Filter templates based on current exam type, category, and search query
     */
    filterAndDisplayTemplates() {
        const examType = this.data.examType;

        // Filter templates
        this.filteredTemplates = this.templates.filter(template => {
            // Must match exam type
            if (template.examType !== examType) {
                return false;
            }

            // Must match category filter
            if (this.templateCategoryFilter !== 'all' &&
                template.category !== this.templateCategoryFilter) {
                return false;
            }

            // Must match search query (search in name, description, and tags)
            if (this.templateSearchQuery) {
                const searchableText = [
                    template.name,
                    template.description,
                    ...(template.tags || []),
                    ...(template.targetUsers || [])
                ].join(' ').toLowerCase();

                if (!searchableText.includes(this.templateSearchQuery)) {
                    return false;
                }
            }

            return true;
        });

        // Sort by popularity (descending)
        this.filteredTemplates.sort((a, b) => (b.popularity || 0) - (a.popularity || 0));

        // Render template cards
        this.renderTemplateCards();
    }

    /**
     * Render template cards in the grid
     */
    renderTemplateCards() {
        const container = document.getElementById('template-cards-grid');
        const noResults = document.getElementById('template-no-results');

        if (!container) return;

        // Show/hide no results message
        if (this.filteredTemplates.length === 0) {
            container.innerHTML = '';
            if (noResults) noResults.classList.remove('hidden');
            return;
        }

        if (noResults) noResults.classList.add('hidden');

        // Generate template cards HTML
        container.innerHTML = this.filteredTemplates.map(template => {
            const isSelected = this.selectedTemplateId === template.id;
            const categoryLabel = this.getCategoryLabel(template.category);
            const categoryClass = `category-${template.category}`;
            const targetUsersHtml = template.targetUsers
                ? `<div class="template-target-users">${template.targetUsers.join(' | ')}</div>`
                : '';

            // Generate dimension preview for multi-dimensional templates
            let dimensionPreviewHtml = '';
            if (template.examType === 'multi_dimensional' && template.dimensions) {
                dimensionPreviewHtml = `
                    <div class="template-dimensions-preview">
                        ${template.dimensions.slice(0, 3).map(d =>
                            `<span class="template-dimension-badge">${this.escapeHtml(d.name)}</span>`
                        ).join('')}
                        ${template.dimensions.length > 3 ? `<span class="template-dimension-more">+${template.dimensions.length - 3} more</span>` : ''}
                    </div>
                `;
            }

            return `
                <div class="template-card ${isSelected ? 'selected' : ''}"
                     data-template-id="${template.id}"
                     data-testid="wizard-step1-template-card-${this.escapeHtml(template.id)}">
                    <div class="template-card-header">
                        <span class="template-category-badge ${categoryClass}">${categoryLabel}</span>
                        ${template.popularity >= 4 ? '<span class="template-popular-badge">Popular</span>' : ''}
                    </div>
                    <div class="template-card-body">
                        <h3 class="template-name">${this.escapeHtml(template.name)}</h3>
                        <p class="template-description">${this.escapeHtml(template.description)}</p>
                        ${dimensionPreviewHtml}
                        ${targetUsersHtml}
                    </div>
                    <div class="template-card-footer">
                        <div class="template-radio">
                            <input type="radio" name="template-selection"
                                   value="${template.id}" ${isSelected ? 'checked' : ''}>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Attach click listeners to template cards
        container.querySelectorAll('.template-card').forEach(card => {
            card.addEventListener('click', () => {
                const templateId = card.dataset.templateId;
                this.selectTemplate(templateId);
            });
        });
    }

    /**
     * Select a template (or null for "start from scratch")
     * @param {string|null} templateId - Template ID or null for scratch
     */
    selectTemplate(templateId) {
        this.selectedTemplateId = templateId;
        this.data.templateId = templateId;

        // Update scratch option visual state
        this.updateScratchOptionState(templateId === null);

        // Update template cards visual state
        document.querySelectorAll('.template-card').forEach(card => {
            const isSelected = card.dataset.templateId === templateId;
            card.classList.toggle('selected', isSelected);

            // Update radio button
            const radio = card.querySelector('input[type="radio"]');
            if (radio) {
                radio.checked = isSelected;
            }
        });

        // Update scratch option radio
        const scratchRadio = document.querySelector('#template-scratch input[type="radio"]');
        if (scratchRadio) {
            scratchRadio.checked = (templateId === null);
        }

        // Apply template data or clear for scratch
        if (templateId) {
            const template = this.templates.find(t => t.id === templateId);
            if (template) {
                this.applyTemplate(template);
                console.log(`Template selected and applied: ${template.name}`);
            } else {
                console.warn(`Template not found: ${templateId}`);
            }
        } else {
            this.clearTemplateData();
            console.log('Starting from scratch (no template)');
        }
    }

    /**
     * Apply template data to populate wizard fields
     * @param {Object} template - The template object to apply
     */
    applyTemplate(template) {
        // Store original template data for reset functionality (deep copy)
        this.originalTemplateData = JSON.parse(JSON.stringify(template));
        this.templateModified = false;
        this.data.templateModified = false;

        // Set exam type based on template
        if (template.examType) {
            this.data.examType = template.examType;
            // Update UI for exam type selection
            document.getElementById('type-simple').checked = (template.examType === 'simple');
            document.getElementById('type-multi').checked = (template.examType === 'multi_dimensional');
            document.querySelectorAll('.exam-type-card').forEach(card => {
                card.classList.toggle('selected', card.dataset.type === template.examType);
            });
        }

        // Populate suggested exam name and description
        if (template.suggestedName) {
            this.data.examName = template.suggestedName;
        }
        if (template.suggestedDescription) {
            this.data.examDescription = template.suggestedDescription;
        }

        // Populate dimensions for multi-dimensional templates
        if (template.examType === 'multi_dimensional' && template.dimensions && template.dimensions.length > 0) {
            this.data.dimensions = template.dimensions.map((dim, index) => ({
                id: Date.now() + index,  // Temporary ID for UI purposes
                name: dim.name || '',
                description: dim.description || '',
                isRequired: dim.isRequired !== undefined ? dim.isRequired : true,
                allowMultiple: dim.allowMultiple !== undefined ? dim.allowMultiple : false,
                displayOrder: dim.displayOrder || (index + 1),
                fromTemplate: true  // Mark as template-provided for visual indication
            }));
            console.log(`Populated ${this.data.dimensions.length} dimensions from template`);
        }

        // Populate hierarchy levels from template, or use defaults if not provided
        if (template.hierarchyLevels && Array.isArray(template.hierarchyLevels) && template.hierarchyLevels.length > 0) {
            this.data.hierarchyLevels = [...template.hierarchyLevels];
            console.log(`Hierarchy levels set from template: ${this.data.hierarchyLevels.join(' > ')}`);
        } else {
            // Use defaults if template doesn't have hierarchy levels
            this.data.hierarchyLevels = ['System', 'Subsystem', 'Topic', 'Subtopic', 'Child'];
            console.log('Using default hierarchy levels (template had none)');
        }

        // Populate weight settings from template, or use defaults if not provided
        if (template.weightSettings) {
            this.data.weightSettings = {
                autonomousBalancing: template.weightSettings.autonomousBalancing !== undefined
                    ? template.weightSettings.autonomousBalancing : true,
                precision: template.weightSettings.precision !== undefined
                    ? template.weightSettings.precision : 1,
                balancingAlgorithm: template.weightSettings.balancingAlgorithm || 'proportional'
            };
            console.log(`Weight settings set from template:`, this.data.weightSettings);
        } else {
            // Use defaults if template doesn't have weight settings
            this.data.weightSettings = {
                autonomousBalancing: true,
                precision: 1,
                balancingAlgorithm: 'proportional'
            };
            console.log('Using default weight settings (template had none)');
        }

        // Update progress bar to reflect exam type (step count may change)
        this.updateProgressBar();

        // Update modification indicator (shows "Using template defaults")
        this.updateTemplateModificationIndicator();
    }

    /**
     * Mark that the user has modified template data
     * Called when any field that was pre-populated by template is changed
     */
    markTemplateModified() {
        // Only mark as modified if we have a template selected
        if (this.selectedTemplateId && !this.templateModified) {
            this.templateModified = true;
            this.data.templateModified = true;
            console.log('Template data has been modified by user');

            // Update UI to show modification indicator
            this.updateTemplateModificationIndicator();
        }
    }

    /**
     * Update the UI to show whether template data has been modified
     */
    updateTemplateModificationIndicator() {
        const statusBar = document.getElementById('template-status-bar');
        const indicator = document.getElementById('template-modification-indicator');
        const resetBtn = document.getElementById('btn-reset-template');

        // Show/hide the entire status bar based on template selection
        if (statusBar) {
            if (this.selectedTemplateId) {
                statusBar.style.display = 'flex';
            } else {
                statusBar.style.display = 'none';
            }
        }

        if (indicator) {
            if (this.templateModified && this.selectedTemplateId) {
                indicator.classList.remove('hidden');
                indicator.textContent = 'Modified from template';
                indicator.classList.add('modified');
                indicator.classList.remove('default');
            } else if (this.selectedTemplateId) {
                indicator.classList.remove('hidden');
                indicator.textContent = 'Using template defaults';
                indicator.classList.add('default');
                indicator.classList.remove('modified');
            } else {
                indicator.classList.add('hidden');
            }
        }

        // Show/hide reset button
        if (resetBtn) {
            if (this.templateModified && this.selectedTemplateId) {
                resetBtn.classList.remove('hidden');
            } else {
                resetBtn.classList.add('hidden');
            }
        }
    }

    /**
     * Reset all data to the original template defaults
     */
    resetToTemplateDefaults() {
        if (!this.originalTemplateData || !this.selectedTemplateId) {
            console.warn('No template data to reset to');
            return;
        }

        const confirmed = confirm(
            'Reset to template defaults?\n\n' +
            'This will undo all changes you\'ve made to the pre-filled data.'
        );

        if (!confirmed) {
            return;
        }

        // Re-apply the original template
        this.applyTemplate(this.originalTemplateData);

        // Update current form fields if we're on a relevant step
        const currentStepType = this.getCurrentStepType();

        if (currentStepType === 'info') {
            this.populateInfoFormFields();
        } else if (currentStepType === 'dimensions') {
            this.renderDimensions();
        } else if (currentStepType === 'hierarchy') {
            this.renderHierarchyLevels();
        } else if (currentStepType === 'weights') {
            this.populateWeightSettingsUI();
        }

        console.log('Reset to template defaults:', this.originalTemplateData.name);
    }

    /**
     * Clear template-populated data (for "start from scratch" option)
     */
    clearTemplateData() {
        // Clear exam info (but keep exam type - user already selected it in step 1)
        this.data.examName = '';
        this.data.examDescription = '';

        // Clear dimensions
        this.data.dimensions = [];

        // Reset hierarchy levels to default
        this.data.hierarchyLevels = ['System', 'Subsystem', 'Topic', 'Subtopic', 'Child'];

        // Reset weight settings to default
        this.data.weightSettings = {
            autonomousBalancing: true,
            precision: 1,
            balancingAlgorithm: 'proportional'
        };

        // Clear template tracking state
        this.originalTemplateData = null;
        this.templateModified = false;
        this.data.templateModified = false;

        // Update modification indicator (hide it since no template)
        this.updateTemplateModificationIndicator();

        console.log('Cleared template data - starting from scratch');
    }

    /**
     * Update the visual state of the "start from scratch" option
     * @param {boolean} isSelected - Whether scratch is selected
     */
    updateScratchOptionState(isSelected) {
        const scratchOption = document.getElementById('template-scratch');
        if (scratchOption) {
            scratchOption.classList.toggle('selected', isSelected);
        }
    }

    /**
     * Get display label for a category
     * @param {string} category - Category identifier
     * @returns {string} Display label
     */
    getCategoryLabel(category) {
        const labels = {
            'medical': 'Medical',
            'graduate': 'Graduate',
            'undergraduate': 'Undergraduate',
            'professional': 'Professional',
            'other': 'Other'
        };
        return labels[category] || category;
    }

    /**
     * Get the currently selected template object
     * @returns {Object|null} Template object or null if starting from scratch
     */
    getSelectedTemplate() {
        if (!this.selectedTemplateId) return null;
        return this.templates.find(t => t.id === this.selectedTemplateId) || null;
    }
    
    // =========================================================================
    // Dimension Management (Phase 7.2 Stage 2.2)
    // =========================================================================
    
    addDimension() {
        const newDimension = {
            id: Date.now(), // Temporary ID for UI purposes
            name: '',
            description: '',
            isRequired: true,
            allowMultiple: false,
            displayOrder: this.data.dimensions.length + 1,
            fromTemplate: false  // New dimension, not from template
        };

        this.data.dimensions.push(newDimension);
        this.renderDimensions();

        // Mark as modified since user added a new dimension
        this.markTemplateModified();

        // Focus the new dimension's name input
        setTimeout(() => {
            const inputs = document.querySelectorAll('.dimension-name');
            const lastInput = inputs[inputs.length - 1];
            if (lastInput) lastInput.focus();
        }, 50);
    }
    
    updateDimension(index, field, value) {
        if (this.data.dimensions[index]) {
            this.data.dimensions[index][field] = value;
        }
    }
    
    deleteDimension(index) {
        if (this.data.dimensions.length > 1 || confirm('Delete this dimension?')) {
            this.data.dimensions.splice(index, 1);
            // Update display orders
            this.data.dimensions.forEach((dim, i) => {
                dim.displayOrder = i + 1;
            });
            this.renderDimensions();
        }
    }
    
    renderDimensions() {
        const container = document.getElementById('dimensions-list');
        if (!container) return;

        // Initialize with one dimension if empty
        if (this.data.dimensions.length === 0) {
            this.data.dimensions.push({
                id: Date.now(),
                name: '',
                description: '',
                isRequired: true,
                allowMultiple: false,
                displayOrder: 1
            });
        }

        container.innerHTML = this.data.dimensions.map((dim, index) => {
            // Show template badge if dimension came from template
            const templateBadge = dim.fromTemplate
                ? '<span class="template-source-badge" title="Pre-filled from template">From template</span>'
                : '';

            // NOTE: testids use the array index for now. TODO (per UI_AUDIT.md):
            // switch to a stable identifier (e.g. dim.dbId or a UUID) once
            // dimensions get UUIDs at create-time so tests don't break on
            // reorder/delete-and-re-add.
            return `
                <div class="dimension-card ${dim.fromTemplate ? 'from-template' : ''}"
                     data-dimension-index="${index}"
                     data-testid="wizard-step3-dimension-${index}"
                     draggable="true">
                    <div class="dimension-header">
                        <span class="drag-handle" title="Drag to reorder">⋮⋮</span>
                        <span class="dimension-number">Dimension ${index + 1}</span>
                        ${templateBadge}
                        <button type="button" class="btn-delete-dimension"
                                data-testid="wizard-step3-dimension-${index}-delete-button"
                                title="Delete dimension"
                                ${this.data.dimensions.length <= 1 ? 'disabled' : ''}>
                            ✕
                        </button>
                    </div>
                    <div class="dimension-body">
                        <div class="form-group">
                            <label>Name <span class="required">*</span></label>
                            <input type="text" class="dimension-name"
                                   data-testid="wizard-step3-dimension-${index}-name-input"
                                   placeholder="e.g., Site of Care"
                                   value="${this.escapeHtml(dim.name)}"
                                   required>
                        </div>
                        <div class="form-group">
                            <label>Description <span class="optional">(optional)</span></label>
                            <input type="text" class="dimension-description"
                                   data-testid="wizard-step3-dimension-${index}-description-input"
                                   placeholder="e.g., Where the patient encounter occurs"
                                   value="${this.escapeHtml(dim.description || '')}">
                        </div>
                        <div class="form-row dimension-options">
                            <label class="checkbox-label">
                                <input type="checkbox" class="dimension-required"
                                       data-testid="wizard-step3-dimension-${index}-required-checkbox"
                                       ${dim.isRequired ? 'checked' : ''}>
                                Required
                            </label>
                            <label class="checkbox-label">
                                <input type="checkbox" class="dimension-allow-multiple"
                                       data-testid="wizard-step3-dimension-${index}-allow-multiple-checkbox"
                                       ${dim.allowMultiple ? 'checked' : ''}>
                                Allow multiple selections
                            </label>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Re-attach event listeners
        this.attachDimensionListeners();
    }
    
    attachDimensionListeners() {
        const container = document.getElementById('dimensions-list');
        if (!container) return;

        // Name inputs
        container.querySelectorAll('.dimension-name').forEach((input, index) => {
            input.addEventListener('input', (e) => {
                this.updateDimension(index, 'name', e.target.value.trim());
                this.markTemplateModified();
            });
        });

        // Description inputs
        container.querySelectorAll('.dimension-description').forEach((input, index) => {
            input.addEventListener('input', (e) => {
                this.updateDimension(index, 'description', e.target.value.trim());
                this.markTemplateModified();
            });
        });

        // Required checkboxes
        container.querySelectorAll('.dimension-required').forEach((checkbox, index) => {
            checkbox.addEventListener('change', (e) => {
                this.updateDimension(index, 'isRequired', e.target.checked);
                this.markTemplateModified();
            });
        });

        // Allow multiple checkboxes
        container.querySelectorAll('.dimension-allow-multiple').forEach((checkbox, index) => {
            checkbox.addEventListener('change', (e) => {
                this.updateDimension(index, 'allowMultiple', e.target.checked);
                this.markTemplateModified();
            });
        });

        // Delete buttons
        container.querySelectorAll('.btn-delete-dimension').forEach((btn, index) => {
            btn.addEventListener('click', () => {
                this.deleteDimension(index);
                this.markTemplateModified();
            });
        });

        // Setup drag and drop for reordering
        this.setupDimensionDragDrop();
    }
    
    setupDimensionDragDrop() {
        const container = document.getElementById('dimensions-list');
        if (!container) return;
        
        const cards = container.querySelectorAll('.dimension-card');
        let draggedItem = null;
        
        cards.forEach(card => {
            card.addEventListener('dragstart', (e) => {
                draggedItem = card;
                card.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
            });
            
            card.addEventListener('dragend', () => {
                card.classList.remove('dragging');
                draggedItem = null;

                // Update dimension order based on DOM order
                const newOrder = [...container.querySelectorAll('.dimension-card')].map(
                    (c, i) => parseInt(c.dataset.dimensionIndex)
                );

                // Check if order actually changed
                const orderChanged = newOrder.some((oldIdx, newIdx) => oldIdx !== newIdx);

                // Reorder dimensions array
                const reordered = newOrder.map(oldIndex => this.data.dimensions[oldIndex]);
                reordered.forEach((dim, i) => dim.displayOrder = i + 1);
                this.data.dimensions = reordered;

                // Mark as modified if order changed
                if (orderChanged) {
                    this.markTemplateModified();
                }

                // Re-render with new order
                this.renderDimensions();
            });
            
            card.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                
                if (draggedItem && draggedItem !== card) {
                    const rect = card.getBoundingClientRect();
                    const midpoint = rect.top + rect.height / 2;
                    
                    if (e.clientY < midpoint) {
                        container.insertBefore(draggedItem, card);
                    } else {
                        container.insertBefore(draggedItem, card.nextSibling);
                    }
                }
            });
        });
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // =========================================================================
    // Navigation
    // =========================================================================
    
    nextStep() {
        // Save current step data
        this.saveStepData();

        // Validate current step
        if (!this.validateCurrentStep()) {
            return;
        }

        if (this.currentStep < this.totalSteps) {
            this.currentStep++;
            this.updateUI();

            // Update summary if on last step
            if (this.currentStep === this.totalSteps) {
                this.updateSummary();
            }

            // Populate info form fields when entering info step (e.g., from template)
            if (this.getCurrentStepType() === 'info') {
                this.populateInfoFormFields();
            }

            // Render dimensions if entering dimensions step
            if (this.getCurrentStepType() === 'dimensions') {
                this.renderDimensions();
            }

            // Render templates if entering template step
            if (this.getCurrentStepType() === 'template') {
                this.displayTemplates(this.data.examType);
            }

            // Render hierarchy levels if entering hierarchy step
            if (this.getCurrentStepType() === 'hierarchy') {
                this.renderHierarchyLevels();
            }

            // Update weight settings UI if entering weights step
            if (this.getCurrentStepType() === 'weights') {
                this.populateWeightSettingsUI();
            }

            // Stage 4 — render the length step + try to pre-fill from
            // the known-exam-length lookup. Pre-fill is async but the
            // initial render fires synchronously.
            if (this.getCurrentStepType() === 'length') {
                this.populateExamLengthFields();
                this.prefillExamLengthFromName();
            }
        }
    }

    /**
     * Populate the info step form fields from this.data
     * Used when navigating to info step after template selection
     */
    populateInfoFormFields() {
        const nameInput = document.getElementById('exam-name');
        const descInput = document.getElementById('exam-description');
        const dateInput = document.getElementById('exam-date');
        const notesInput = document.getElementById('exam-notes');

        // Always set the values, even if empty (to properly clear from previous state)
        if (nameInput) {
            nameInput.value = this.data.examName || '';
        }
        if (descInput) {
            descInput.value = this.data.examDescription || '';
        }
        if (dateInput) {
            dateInput.value = this.data.examDate || '';
        }
        if (notesInput) {
            notesInput.value = this.data.notes || '';
        }
    }

    /**
     * Populate weight settings UI from this.data
     * Used when navigating to weights step after template selection
     */
    populateWeightSettingsUI() {
        // Update autonomous balancing toggle
        const autonomousToggle = document.getElementById('autonomous-balancing');
        if (autonomousToggle) {
            autonomousToggle.checked = this.data.weightSettings.autonomousBalancing;
            autonomousToggle.closest('.toggle')?.classList.toggle('is-checked', this.data.weightSettings.autonomousBalancing);
        }

        // Update precision select
        const precisionSelect = document.getElementById('weight-precision-select');
        if (precisionSelect) {
            const precision = this.data.weightSettings.precision;
            precisionSelect.dataset.value = precision;
            const precisionLabels = {
                0: 'Whole numbers (0)',
                1: 'One decimal (0.0)',
                2: 'Two decimals (0.00)'
            };
            const valueDisplay = precisionSelect.querySelector('.custom-select-value');
            if (valueDisplay) {
                valueDisplay.textContent = precisionLabels[precision];
            }
            precisionSelect.querySelectorAll('.custom-select-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.value === String(precision));
            });
        }

        // Update algorithm select
        const algorithmSelect = document.getElementById('balancing-algorithm-select');
        if (algorithmSelect) {
            const algorithm = this.data.weightSettings.balancingAlgorithm;
            algorithmSelect.dataset.value = algorithm;
            const algorithmLabels = {
                'proportional': 'Proportional Distribution',
                'even': 'Even Distribution'
            };
            const valueDisplay = algorithmSelect.querySelector('.custom-select-value');
            if (valueDisplay) {
                valueDisplay.textContent = algorithmLabels[algorithm];
            }
            algorithmSelect.querySelectorAll('.custom-select-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.value === algorithm);
            });
        }

        // Update algorithm preview
        this.updateAlgorithmPreview();
    }
    
    prevStep() {
        if (this.currentStep > 1) {
            this.currentStep--;
            this.updateUI();
        }
    }
    
    getCurrentStepType() {
        const stepIndex = this.currentStep - 1;
        return this.currentConfig.steps[stepIndex];
    }
    
    getCurrentStepId() {
        const stepIndex = this.currentStep - 1;
        return this.currentConfig.stepIds[stepIndex];
    }
    
    saveStepData() {
        const stepType = this.getCurrentStepType();
        
        switch (stepType) {
            case 'info':
                this.data.examName = document.getElementById('exam-name').value.trim();
                this.data.examDescription = document.getElementById('exam-description').value.trim();
                this.data.examDate = document.getElementById('exam-date').value;
                this.data.notes = document.getElementById('exam-notes').value.trim();
                break;
                
            case 'dimensions':
                // Dimensions are saved in real-time via event listeners
                break;
                
            case 'weights':
                // Get values from custom selects
                const precisionSelect = document.getElementById('weight-precision-select');
                const algorithmSelect = document.getElementById('balancing-algorithm-select');

                this.data.weightSettings = {
                    autonomousBalancing: document.getElementById('autonomous-balancing').checked,
                    precision: parseInt(precisionSelect ? precisionSelect.dataset.value : 1),
                    balancingAlgorithm: algorithmSelect ? algorithmSelect.dataset.value : 'proportional'
                };
                break;

            case 'length':
                // The radio + input listeners stream to this.data.examLength
                // already; force a final read here so a pre-fill that bypassed
                // the input event still wins.
                const checkedRadio = document.querySelector('input[name="exam-length-kind"]:checked');
                if (checkedRadio) {
                    this.data.examLength.kind = checkedRadio.value;
                }
                if (this.data.examLength.kind === 'fixed') {
                    const v = document.getElementById('exam-length-fixed-typical');
                    const parsed = v && v.value !== '' ? parseInt(v.value, 10) : null;
                    this.data.examLength.min = parsed;
                    this.data.examLength.max = parsed;
                    this.data.examLength.typical = parsed;
                } else if (this.data.examLength.kind === 'range') {
                    const minEl = document.getElementById('exam-length-range-min');
                    const typEl = document.getElementById('exam-length-range-typical');
                    const maxEl = document.getElementById('exam-length-range-max');
                    this.data.examLength.min = minEl && minEl.value !== '' ? parseInt(minEl.value, 10) : null;
                    this.data.examLength.typical = typEl && typEl.value !== '' ? parseInt(typEl.value, 10) : null;
                    this.data.examLength.max = maxEl && maxEl.value !== '' ? parseInt(maxEl.value, 10) : null;
                } else {
                    // unknown
                    this.data.examLength.min = null;
                    this.data.examLength.max = null;
                    this.data.examLength.typical = null;
                }
                const noteEl = document.getElementById('exam-length-note');
                if (noteEl) {
                    this.data.examLength.note = noteEl.value;
                }
                break;
        }
    }
    
    validateCurrentStep() {
        const stepType = this.getCurrentStepType();
        
        switch (stepType) {
            case 'type':
                // Type is always valid (has default selection)
                return true;
                
            case 'info':
                const examName = document.getElementById('exam-name').value.trim();
                const errorEl = document.getElementById('exam-name-error');
                
                if (!examName) {
                    errorEl.textContent = 'Exam name is required';
                    errorEl.classList.remove('hidden');
                    return false;
                }
                
                if (examName.length < 2) {
                    errorEl.textContent = 'Exam name must be at least 2 characters';
                    errorEl.classList.remove('hidden');
                    return false;
                }
                
                errorEl.classList.add('hidden');
                return true;
                
            case 'length':
                // Stage 4: validate the exam-length triple before advancing.
                // Mirrors the user_db invariants in update_exam_length so the
                // user sees the error inline rather than via a bridge round-trip.
                const errEl = document.getElementById('exam-length-error');
                const showError = (msg) => {
                    if (errEl) {
                        errEl.textContent = msg;
                        errEl.classList.remove('hidden');
                    } else {
                        alert(msg);
                    }
                };
                if (errEl) errEl.classList.add('hidden');

                const len = this.data.examLength;
                if (len.kind === 'unknown') {
                    return true;
                }
                if (len.kind === 'fixed') {
                    if (!Number.isFinite(len.typical) || len.typical < 1) {
                        showError('Enter a positive integer for the number of items.');
                        return false;
                    }
                    return true;
                }
                if (len.kind === 'range') {
                    if (!Number.isFinite(len.min) || !Number.isFinite(len.max) || !Number.isFinite(len.typical)) {
                        showError('Fill in min, typical, and max for variable-length exams.');
                        return false;
                    }
                    if (len.min < 1 || len.max < 1 || len.typical < 1) {
                        showError('Length values must be positive integers.');
                        return false;
                    }
                    if (!(len.min <= len.typical && len.typical <= len.max)) {
                        showError('Range invariant: min ≤ typical ≤ max.');
                        return false;
                    }
                    return true;
                }
                showError('Pick a length kind to continue.');
                return false;

            case 'dimensions':
                // Validate dimensions for multi-dimensional exams
                if (this.data.dimensions.length === 0) {
                    alert('Please add at least one dimension.');
                    return false;
                }
                
                // Check all dimensions have names
                for (let i = 0; i < this.data.dimensions.length; i++) {
                    if (!this.data.dimensions[i].name.trim()) {
                        alert(`Please enter a name for Dimension ${i + 1}.`);
                        return false;
                    }
                }
                
                // Check for duplicate names
                const names = this.data.dimensions.map(d => d.name.toLowerCase().trim());
                const uniqueNames = new Set(names);
                if (uniqueNames.size !== names.length) {
                    alert('Dimension names must be unique.');
                    return false;
                }
                
                return true;
                
            default:
                return true;
        }
    }
    
    updateUI() {
        // Hide all wizard steps
        document.querySelectorAll('.wizard-step').forEach(step => {
            step.classList.remove('active');
        });
        
        // Show current step
        const currentStepId = this.getCurrentStepId();
        const currentStepEl = document.getElementById(currentStepId);
        if (currentStepEl) {
            currentStepEl.classList.add('active');
        }
        
        // Update progress
        this.updateProgressBar();
        
        // Update navigation buttons
        this.updateNavigation();
    }
    
    updateProgressBar() {
        const config = this.currentConfig;
        
        // Update progress bar fill
        const progress = (this.currentStep / config.totalSteps) * 100;
        document.getElementById('progress-fill').style.width = `${progress}%`;
        
        // Re-render progress steps based on exam type
        const stepsContainer = document.getElementById('progress-steps');
        stepsContainer.innerHTML = config.labels.map((label, index) => {
            const stepNum = index + 1;
            let className = 'progress-step';
            
            if (stepNum === this.currentStep) {
                className += ' active';
            } else if (stepNum < this.currentStep) {
                className += ' completed';
            }
            
            return `
                <div class="${className}" data-step="${stepNum}" data-testid="wizard-progress-step-${stepNum}">
                    <div class="step-circle">${stepNum}</div>
                    <div class="step-label">${label}</div>
                </div>
            `;
        }).join('');
    }
    
    updateNavigation() {
        const btnBack = document.getElementById('btn-back');
        const btnNext = document.getElementById('btn-next');
        const btnCreate = document.getElementById('btn-create');

        // Back button - disabled on first step
        btnBack.disabled = this.currentStep === 1;

        // In edit mode, disable back on step 3 (info step - can't go back to type/template selection)
        if (this.isEditMode && this.currentStep === 3) {
            btnBack.disabled = true;
        }
        
        // Next/Create buttons
        if (this.currentStep === this.totalSteps) {
            btnNext.classList.add('hidden');
            btnCreate.classList.remove('hidden');
        } else {
            btnNext.classList.remove('hidden');
            btnCreate.classList.add('hidden');
        }
    }
    
    renderHierarchyLevels() {
        const container = document.getElementById('hierarchy-levels');
        container.innerHTML = '';
        
        this.data.hierarchyLevels.forEach((level, index) => {
            const isRequired = index < 3;
            
            const levelEl = document.createElement('div');
            levelEl.className = `hierarchy-level ${isRequired ? 'required' : ''}`;
            levelEl.innerHTML = `
                <div class="level-order">${index + 1}</div>
                <div class="level-info">
                    <span class="level-name">${level}</span>
                    <span class="badge ${isRequired ? 'badge-required' : 'badge-optional'} level-badge">
                        ${isRequired ? 'Required' : 'Optional'}
                    </span>
                </div>
            `;
            
            container.appendChild(levelEl);
        });
    }
    
    updateAlgorithmPreview() {
        const container = document.getElementById('algorithm-preview');
        if (!container) return;
        
        // Get algorithm from custom select or use default
        const algorithmSelect = document.getElementById('balancing-algorithm-select');
        const algorithm = algorithmSelect ? algorithmSelect.dataset.value : this.data.weightSettings.balancingAlgorithm;
        
        let example;
        if (algorithm === 'proportional') {
            example = `
                <div class="preview-title">Example: Proportional Distribution</div>
                <div class="preview-example">
                    <p><strong>Before:</strong> Node A = 40%, Node B = 30%, Node C = 30%</p>
                    <p><strong>Action:</strong> Increase Node A to 60% (+20%)</p>
                    <p><strong>After:</strong></p>
                    <ul>
                        <li>Node A = <span class="preview-highlight">60%</span> (your change)</li>
                        <li>Node B = 25% (reduced by 5%, proportional to its 30/60 share)</li>
                        <li>Node C = 15% (reduced by 15%, proportional to its 30/60 share)</li>
                    </ul>
                    <p><em>Sibling ratios are preserved relative to each other.</em></p>
                </div>
            `;
        } else {
            example = `
                <div class="preview-title">Example: Even Distribution</div>
                <div class="preview-example">
                    <p><strong>Before:</strong> Node A = 40%, Node B = 30%, Node C = 30%</p>
                    <p><strong>Action:</strong> Increase Node A to 60% (+20%)</p>
                    <p><strong>After:</strong></p>
                    <ul>
                        <li>Node A = <span class="preview-highlight">60%</span> (your change)</li>
                        <li>Node B = 20% (reduced by 10%, equal share of -20%)</li>
                        <li>Node C = 20% (reduced by 10%, equal share of -20%)</li>
                    </ul>
                    <p><em>Change is split equally among all siblings.</em></p>
                </div>
            `;
        }
        
        container.innerHTML = example;
    }
    
    updateSummary() {
        // Exam information
        document.getElementById('summary-name').textContent = this.data.examName || '-';
        document.getElementById('summary-type').textContent =
            this.data.examType === 'multi_dimensional' ? 'Multi-Dimensional' : 'Simple';
        document.getElementById('summary-description').textContent =
            this.data.examDescription || 'No description provided';
        document.getElementById('summary-date').textContent =
            this.data.examDate ? this.formatDate(this.data.examDate) : 'Not scheduled';

        // Template used (if applicable)
        const templateSection = document.getElementById('summary-template-section');
        const templateValue = document.getElementById('summary-template');
        if (templateSection && templateValue) {
            const template = this.getSelectedTemplate();
            if (template) {
                templateSection.style.display = 'block';
                templateValue.textContent = template.name;
            } else {
                templateSection.style.display = 'none';
            }
        }

        // Dimensions (multi-dimensional only)
        const dimensionsSection = document.getElementById('summary-dimensions-section');
        const dimensionsContainer = document.getElementById('summary-dimensions');
        
        if (this.data.examType === 'multi_dimensional' && this.data.dimensions.length > 0) {
            dimensionsSection.style.display = 'block';
            dimensionsContainer.innerHTML = this.data.dimensions.map(dim => `
                <div class="summary-dimension-item">
                    <span class="dimension-name-badge">${this.escapeHtml(dim.name)}</span>
                    ${dim.isRequired ? '<span class="badge badge-required">Required</span>' : ''}
                    ${dim.allowMultiple ? '<span class="badge badge-optional">Multi-select</span>' : ''}
                </div>
            `).join('');
        } else {
            dimensionsSection.style.display = 'none';
        }
        
        // Hierarchy
        const hierarchyContainer = document.getElementById('summary-hierarchy');
        hierarchyContainer.innerHTML = this.data.hierarchyLevels.map((level, index) => `
            <span class="hierarchy-item">${level}</span>
            ${index < this.data.hierarchyLevels.length - 1 ? '<span class="hierarchy-arrow">→</span>' : ''}
        `).join('');
        
        // Weight settings
        document.getElementById('summary-balancing').textContent = 
            this.data.weightSettings.autonomousBalancing ? 'Enabled' : 'Disabled';
        
        const precisionLabels = {
            0: 'Whole numbers',
            1: 'One decimal place',
            2: 'Two decimal places'
        };
        document.getElementById('summary-precision').textContent = 
            precisionLabels[this.data.weightSettings.precision];
        
        const algorithmLabels = {
            'proportional': 'Proportional',
            'even': 'Even Distribution'
        };
        document.getElementById('summary-algorithm').textContent = 
            algorithmLabels[this.data.weightSettings.balancingAlgorithm];
    }
    
    formatDate(dateString) {
        if (!dateString) return '';
        const [y, m, d] = dateString.slice(0, 10).split('-').map(Number);
        if (!y || !m || !d) return dateString;
        const date = new Date(y, m - 1, d);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
    }
    
    confirmCancel() {
        // Check if any data has been entered
        const hasData = this.data.examName || 
                        this.data.examDescription || 
                        this.data.examDate || 
                        this.data.notes ||
                        this.data.dimensions.some(d => d.name);
        
        if (hasData) {
            // Show confirmation dialog
            const confirmed = confirm(
                'Are you sure you want to cancel?\n\n' +
                'Any information you\'ve entered will be lost.'
            );
            
            if (confirmed) {
                this.goHome();
            }
        } else {
            // No data entered, just go home
            this.goHome();
        }
    }
    
    goHome() {
        window.location.href = '../index.html';
    }
    
    initCustomSelects() {
        // Initialize all custom select dropdowns
        document.querySelectorAll('.custom-select').forEach(select => {
            const trigger = select.querySelector('.custom-select-trigger');
            const options = select.querySelectorAll('.custom-select-option');
            const valueDisplay = select.querySelector('.custom-select-value');
            
            // Toggle dropdown on trigger click
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                
                // Close other open selects
                document.querySelectorAll('.custom-select.open').forEach(other => {
                    if (other !== select) {
                        other.classList.remove('open');
                    }
                });
                
                select.classList.toggle('open');
            });
            
            // Handle option selection
            options.forEach(option => {
                option.addEventListener('click', (e) => {
                    e.stopPropagation();
                    
                    const value = option.dataset.value;
                    const text = option.textContent;
                    
                    // Update visual state
                    options.forEach(opt => opt.classList.remove('selected'));
                    option.classList.add('selected');
                    valueDisplay.textContent = text;
                    select.dataset.value = value;
                    
                    // Close dropdown
                    select.classList.remove('open');
                    
                    // Handle specific selects
                    if (select.id === 'weight-precision-select') {
                        this.data.weightSettings.precision = parseInt(value);
                        this.markTemplateModified();
                    } else if (select.id === 'balancing-algorithm-select') {
                        this.data.weightSettings.balancingAlgorithm = value;
                        this.updateAlgorithmPreview();
                        this.markTemplateModified();
                    }
                });
            });
        });
        
        // Close dropdowns when clicking outside
        document.addEventListener('click', () => {
            document.querySelectorAll('.custom-select.open').forEach(select => {
                select.classList.remove('open');
            });
        });
    }
    
    async createExam() {
        // Show loading state
        const btnCreate = document.getElementById('btn-create');
        const btnText = btnCreate.querySelector('.btn-text');
        const btnLoading = btnCreate.querySelector('.btn-loading');
        
        btnCreate.disabled = true;
        btnText.classList.add('hidden');
        btnLoading.classList.remove('hidden');
        
        try {
            let result;
            
            if (this.isEditMode) {
                // Update existing exam
                result = await this.updateExam();
            } else {
                // Create new exam
                result = await this.createNewExam();
            }
            
            console.log(`✅ Exam ${this.isEditMode ? 'updated' : 'created'}:`, result);
            
            // Show success modal with appropriate message
            const successMessage = this.isEditMode
                ? `"${this.data.examName}" has been updated successfully.`
                : `"${this.data.examName}" has been created and is ready to use.`;
            document.getElementById('success-message').textContent = successMessage;
            document.getElementById('success-modal').classList.remove('hidden');
            
        } catch (error) {
            console.error(`❌ Error ${this.isEditMode ? 'updating' : 'creating'} exam:`, error);
            
            // Show error modal
            document.getElementById('error-message').textContent = 
                error.message || 'An unexpected error occurred. Please try again.';
            document.getElementById('error-modal').classList.remove('hidden');
            
        } finally {
            // Reset button state
            btnCreate.disabled = false;
            btnText.classList.remove('hidden');
            btnLoading.classList.add('hidden');
        }
    }
    
    async createNewExam() {
        // Prepare weight rules
        const weightRules = {
            autonomous_weight_balancing: this.data.weightSettings.autonomousBalancing,
            allow_absolute_weight_editing: !this.data.weightSettings.autonomousBalancing,
            precision_decimal_places: this.data.weightSettings.precision,
            require_exact_100: true,
            balancing_algorithm: this.data.weightSettings.balancingAlgorithm
        };
        
        // Create exam context via API
        const examResult = await api.createExamContext({
            examName: this.data.examName,
            examDescription: this.data.examDescription,
            examDate: this.data.examDate,
            weightRules: weightRules,
            hierarchyLevels: this.data.hierarchyLevels,
            notes: this.data.notes
        });

        // Stage 4 — persist the length triple. We always call this
        // (including for kind='unknown') so the row's length_kind is
        // explicitly set to the user's pick rather than left at the
        // migration default. Failures don't abort exam creation; they
        // surface as a console warning and the user can retry from the
        // edit screen.
        try {
            await api.updateExamLength({
                examContextId: examResult.id,
                kind: this.data.examLength.kind,
                min: this.data.examLength.min,
                max: this.data.examLength.max,
                typical: this.data.examLength.typical,
                note: this.data.examLength.note
            });
        } catch (lengthError) {
            console.warn('Failed to persist exam length:', lengthError);
        }

        // If multi-dimensional, create dimensions
        if (this.data.examType === 'multi_dimensional' && this.data.dimensions.length > 0) {
            console.log('📊 Creating dimensions for multi-dimensional exam...');
            
            const createdDimensions = [];
            
            for (const dim of this.data.dimensions) {
                try {
                    const createdDim = await api.createDimension({
                        examContextId: examResult.id,
                        name: dim.name,
                        displayOrder: dim.displayOrder,
                        isRequired: dim.isRequired,
                        allowMultiple: dim.allowMultiple,
                        description: dim.description || ''
                    });
                    
                    createdDimensions.push(createdDim);
                    console.log(`  ✓ Created dimension: ${dim.name} (ID: ${createdDim.id})`);
                } catch (dimError) {
                    console.error(`⚠️ Failed to create dimension "${dim.name}":`, dimError);
                    // Continue with other dimensions, but log the error
                }
            }
            
            console.log(`📊 Created ${createdDimensions.length}/${this.data.dimensions.length} dimensions`);
            
            // Attach created dimensions to result for reference
            examResult.dimensions = createdDimensions;
        }
        
        return examResult;
    }
    
    async updateExam() {
        // Prepare settings object for update
        const settings = {
            exam_description: this.data.examDescription,
            exam_date: this.data.examDate,
            notes: this.data.notes,
            autonomous_balancing: this.data.weightSettings.autonomousBalancing,
            precision: this.data.weightSettings.precision,
            balancing_algorithm: this.data.weightSettings.balancingAlgorithm
        };
        
        // Update exam context via API
        const examResult = await api.updateExamContextSettings(this.editExamId, settings);

        // Stage 4 — persist the length triple in edit mode too.
        try {
            await api.updateExamLength({
                examContextId: this.editExamId,
                kind: this.data.examLength.kind,
                min: this.data.examLength.min,
                max: this.data.examLength.max,
                typical: this.data.examLength.typical,
                note: this.data.examLength.note
            });
        } catch (lengthError) {
            console.warn('Failed to persist exam length:', lengthError);
        }

        // Handle dimension updates for multi-dimensional exams
        if (this.data.examType === 'multi_dimensional') {
            await this.syncDimensions();
        }

        return examResult;
    }
    
    /**
     * Synchronize dimensions between UI state and database.
     * Handles creating new dimensions, updating existing ones, and deleting removed ones.
     */
    async syncDimensions() {
        console.log('🔄 Syncing dimensions...');
        
        // Get existing dimensions from database
        const existingDimensions = await api.getDimensions(this.editExamId);
        const existingIds = new Set(existingDimensions.map(d => d.id));
        
        // Track IDs of dimensions still in UI
        const uiDimensionIds = new Set();
        
        for (const dim of this.data.dimensions) {
            if (dim.dbId && existingIds.has(dim.dbId)) {
                // Update existing dimension
                uiDimensionIds.add(dim.dbId);
                try {
                    await api.updateDimension(dim.dbId, {
                        name: dim.name,
                        description: dim.description || '',
                        display_order: dim.displayOrder,
                        is_required: dim.isRequired,
                        allow_multiple: dim.allowMultiple
                    });
                    console.log(`  ✓ Updated dimension: ${dim.name}`);
                } catch (error) {
                    console.error(`  ⚠️ Failed to update dimension "${dim.name}":`, error);
                }
            } else {
                // Create new dimension
                try {
                    const createdDim = await api.createDimension({
                        examContextId: this.editExamId,
                        name: dim.name,
                        displayOrder: dim.displayOrder,
                        isRequired: dim.isRequired,
                        allowMultiple: dim.allowMultiple,
                        description: dim.description || ''
                    });
                    dim.dbId = createdDim.id;  // Update local reference
                    uiDimensionIds.add(createdDim.id);
                    console.log(`  ✓ Created dimension: ${dim.name} (ID: ${createdDim.id})`);
                } catch (error) {
                    console.error(`  ⚠️ Failed to create dimension "${dim.name}":`, error);
                }
            }
        }
        
        // Delete dimensions that were removed from UI
        for (const existing of existingDimensions) {
            if (!uiDimensionIds.has(existing.id)) {
                try {
                    await api.deleteDimension(existing.id);
                    console.log(`  ✓ Deleted dimension: ${existing.name}`);
                } catch (error) {
                    console.error(`  ⚠️ Failed to delete dimension "${existing.name}":`, error);
                }
            }
        }
        
        // Reorder dimensions based on current displayOrder
        const orderedIds = this.data.dimensions
            .filter(d => d.dbId)
            .sort((a, b) => a.displayOrder - b.displayOrder)
            .map(d => d.dbId);
        
        if (orderedIds.length > 1) {
            try {
                await api.reorderDimensions(this.editExamId, orderedIds);
                console.log(`  ✓ Reordered ${orderedIds.length} dimensions`);
            } catch (error) {
                console.error('  ⚠️ Failed to reorder dimensions:', error);
            }
        }
        
        console.log('🔄 Dimension sync complete');
    }
}


// Initialize wizard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.examWizard = new ExamWizard();
});
