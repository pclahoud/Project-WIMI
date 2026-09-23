/**
 * WIMI Settings Page
 * Manages user preferences with live preview, save/cancel workflow.
 */

class SettingsPage {
    constructor() {
        this.originalPreferences = null;
        this.currentPreferences = null;
        this.isDirty = false;
        this.isSaving = false;

        // Default preference values (must match UserPreferences dataclass defaults)
        this.DEFAULTS = {
            theme_name: 'default',
            primary_color_hex: '#2196F3',
            secondary_color_hex: '#FFC107',
            font_family: 'system',
            font_size_scale: 1.0,
            ui_density: 'comfortable',
            show_animations: true,
            default_session_duration_minutes: 60,
            default_break_interval_minutes: 25,
            default_long_break_minutes: 15,
            manual_break_control: true,
            long_break_interval_rounds: 4,
            timer_display_size: 'normal',
            hotkey_timer_pause_resume: 'Alt+P',
            hotkey_timer_new_round: 'Alt+N',
            hotkey_timer_end_round: 'Alt+E',
            analytics_detail_level: 'detailed',
            dashboard_auto_refresh_seconds: 300,
            show_performance_trends: true,
            show_mistake_patterns: true,
            show_subject_breakdown: true,
            show_time_analytics: true,
            // #133 -- off means one number plus the Weight Sources card,
            // which is the full information either way.
            efficiency_show_confidence_band: false,
            calendar_default_view: 'week',
            calendar_time_slot_minutes: 30,
            show_weekend_in_calendar: true,
            entry_review_items_per_page: 25,
            entry_review_default_sort_field: 'answered_incorrectly_date',
            entry_review_default_sort_direction: 'desc',
            anki_integration_enabled: false,
            ankiconnect_port: 8765,
            auto_backup_enabled: true,
            backup_frequency_hours: 24,
            backup_retention_days: 30,
            realtime_update_delay_ms: 1500,
            mcp_server_enabled: false,
            mcp_server_port: 8000
        };

        // Visual fields that trigger live preview
        this.VISUAL_FIELDS = [
            'theme_name', 'primary_color_hex', 'secondary_color_hex',
            'font_family', 'font_size_base_px', 'ui_density', 'show_animations'
        ];

        // Base px for font scale conversion
        this.FONT_BASE_PX = 16;

        // ID for the animation-kill style tag
        this._animationStyleTagId = 'wimi-no-animations';

        // Per-exam analytics chart definitions
        this.CHART_DEFINITIONS = [
            { key: 'subject_sunburst', label: 'Subject Sunburst', dimensionOnly: false },
            { key: 'tag_chart', label: 'Mistake Type Chart', dimensionOnly: false },
            { key: 'activity_chart', label: 'Activity Chart', dimensionOnly: false },
            { key: 'activity_heatmap', label: 'Activity Heatmap', dimensionOnly: false },
            { key: 'streak_stats', label: 'Streak Statistics', dimensionOnly: false },
            { key: 'weekly_goal', label: 'Weekly Goal', dimensionOnly: false },
            { key: 'difficulty_distribution', label: 'Difficulty Distribution', dimensionOnly: false },
            { key: 'patterns_insights', label: 'Patterns & Insights', dimensionOnly: false },
            { key: 'cross_dimension_heatmap', label: 'Cross-Dimension Heatmap', dimensionOnly: true },
            { key: 'study_recommendations', label: 'Study Recommendations', dimensionOnly: true },
            { key: 'interaction_effects', label: 'Interaction Effects', dimensionOnly: true },
            { key: 'weight_analysis', label: 'Weight Analysis', dimensionOnly: false }
        ];
        this._examAnalyticsConfig = null;
        this._selectedExamId = null;
        this._examHasDimensions = false;

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.init());
        } else {
            this.init();
        }
    }

    async init() {
        await api.ready();
        this.setupNavigation();
        this.setupInputHandlers();
        this.setupActionButtons();
        this.setupKeyboardShortcuts();
        this.setupHotkeyCapture();
        this.setupUnsavedChangesGuard();
        await this.loadSettings();
        await this.initExamAnalytics();
        await this.initProfileSection();
        await this.initQuestionBanks();
        await this.initAddons();
        await this.initFolderSync();
        await this.refreshMcpStatus();

        // Handle URL hash navigation (e.g., from gear icon on dashboard)
        this.handleHashNavigation();
    }

    // =========================================================================
    // Navigation
    // =========================================================================

    setupNavigation() {
        // Use event delegation on the sidebar for both static and dynamic nav items
        const sidebar = document.querySelector('.settings-sidebar');
        if (sidebar) {
            sidebar.addEventListener('click', (e) => {
                const navItem = e.target.closest('.settings-nav-item');
                if (!navItem) return;

                const panelName = navItem.getAttribute('data-panel');

                // Remove active from all nav items (including dynamic ones)
                sidebar.querySelectorAll('.settings-nav-item').forEach(item => item.classList.remove('active'));

                // Remove active from all panels
                document.querySelectorAll('.settings-panel').forEach(panel => panel.classList.remove('active'));

                // Activate clicked nav item and matching panel
                navItem.classList.add('active');
                const targetPanel = document.querySelector(`.settings-panel[data-panel="${panelName}"]`);
                if (targetPanel) {
                    targetPanel.classList.add('active');
                }
            });
        }
    }

    // =========================================================================
    // Input Handlers
    // =========================================================================

    setupInputHandlers() {
        const fields = document.querySelectorAll('[data-field]');
        // Track which fields we have already bound to avoid double-binding
        // color inputs (two elements share the same data-field).
        const boundFields = new Set();

        fields.forEach(el => {
            const field = el.getAttribute('data-field');

            // Skip disabled (coming-soon) controls
            if (el.disabled) return;

            // ------ Color inputs come in pairs (color picker + text) ------
            if (field === 'primary_color_hex' || field === 'secondary_color_hex') {
                // Only bind once per field
                if (boundFields.has(field)) return;
                boundFields.add(field);

                const group = el.closest('.color-input-group');
                if (!group) return;

                const colorInput = group.querySelector('input[type="color"]');
                const textInput = group.querySelector('input[type="text"]');

                if (colorInput) {
                    colorInput.addEventListener('input', () => {
                        if (textInput) textInput.value = colorInput.value;
                        this._onFieldChange(field, colorInput.value);
                    });
                }

                if (textInput) {
                    textInput.addEventListener('input', () => {
                        const hex = textInput.value.trim();
                        if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
                            if (colorInput) colorInput.value = hex;
                            this._onFieldChange(field, hex);
                        }
                    });
                }
                return;
            }

            // ------ Range inputs ------
            if (el.type === 'range') {
                el.addEventListener('input', () => {
                    const value = parseFloat(el.value);
                    // Update the range-value display
                    const rangeGroup = el.closest('.range-input-group');
                    if (rangeGroup) {
                        const display = rangeGroup.querySelector('.range-value');
                        if (display) display.textContent = value;
                    }
                    this._onFieldChange(field, value);
                });
                return;
            }

            // ------ Checkboxes ------
            if (el.type === 'checkbox') {
                el.addEventListener('change', () => {
                    this._onFieldChange(field, el.checked);
                });
                return;
            }

            // ------ Number inputs ------
            if (el.type === 'number') {
                el.addEventListener('change', () => {
                    this._onFieldChange(field, parseFloat(el.value));
                });
                return;
            }

            // ------ Select / text / everything else ------
            el.addEventListener('change', () => {
                this._onFieldChange(field, el.value);
            });
        });
    }

    /**
     * Centralized handler for any field change.
     */
    _onFieldChange(field, value) {
        if (!this.currentPreferences) return;

        // Convert font size px → internal scale value
        if (field === 'font_size_base_px') {
            this.currentPreferences.font_size_scale = parseInt(value) / this.FONT_BASE_PX;
        } else {
            this.currentPreferences[field] = value;
        }

        // When theme changes, sync color pickers to the new theme's palette
        if (field === 'theme_name') {
            this._applyThemeToColorPickers(value);
        }

        this.markDirty();

        if (this.VISUAL_FIELDS.includes(field)) {
            this.applyLivePreview();
        }
    }

    /**
     * Sync color picker inputs and currentPreferences to a theme's palette.
     * @param {string} themeName - Key in WIMI_THEMES
     */
    _applyThemeToColorPickers(themeName) {
        const theme = window.WIMI_THEMES && window.WIMI_THEMES[themeName];
        if (!theme) return;

        // Update primary color
        this.currentPreferences.primary_color_hex = theme.primaryColorHex;
        const primaryPicker = document.getElementById('primary_color_hex_picker');
        const primaryText = document.getElementById('primary_color_hex');
        if (primaryPicker) primaryPicker.value = theme.primaryColorHex;
        if (primaryText) primaryText.value = theme.primaryColorHex;

        // Update secondary color
        this.currentPreferences.secondary_color_hex = theme.secondaryColorHex;
        const secondaryPicker = document.getElementById('secondary_color_hex_picker');
        const secondaryText = document.getElementById('secondary_color_hex');
        if (secondaryPicker) secondaryPicker.value = theme.secondaryColorHex;
        if (secondaryText) secondaryText.value = theme.secondaryColorHex;
    }

    // =========================================================================
    // Action Buttons
    // =========================================================================

    setupActionButtons() {
        const saveBtn = document.getElementById('saveBtn');
        const cancelBtn = document.getElementById('cancelBtn');
        const resetBtn = document.getElementById('resetDefaultsBtn');

        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveSettings());
        }
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => this.cancelChanges());
        }
        if (resetBtn) {
            resetBtn.addEventListener('click', () => this.resetToDefaults());
        }
    }

    // =========================================================================
    // Keyboard Shortcuts
    // =========================================================================

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Skip when a hotkey capture field is focused
            if (document.activeElement && document.activeElement.classList.contains('hotkey-capture')) {
                return;
            }
            // Ctrl+S / Cmd+S -> save
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                this.saveSettings();
                return;
            }
            // Escape -> cancel
            if (e.key === 'Escape') {
                this.cancelChanges();
            }
        });
    }

    // =========================================================================
    // Unsaved Changes Guard
    // =========================================================================

    setupUnsavedChangesGuard() {
        // Warn on browser/app-level navigation when dirty
        window.addEventListener('beforeunload', (e) => {
            if (this.isDirty) {
                e.preventDefault();
                e.returnValue = '';
            }
        });

        // Intercept the back link so we can (a) honor in-app history and
        // (b) prompt to save if dirty. If the user reached settings from
        // another WIMI page (e.g. Analytics Dashboard via the gear icon),
        // history.back() returns them to that page; otherwise we fall back
        // to the dashboard.
        const backLink = document.getElementById('backLink');
        if (backLink) {
            const goBack = () => {
                const ref = document.referrer || '';
                const cameFromWimi = ref.includes('/web/html/') && !ref.endsWith('/settings.html');
                if (cameFromWimi && window.history.length > 1) {
                    window.history.back();
                } else {
                    window.location.href = backLink.href;
                }
            };

            backLink.addEventListener('click', (e) => {
                e.preventDefault();
                if (!this.isDirty) {
                    goBack();
                    return;
                }
                if (confirm('You have unsaved changes. Save before leaving?')) {
                    this.saveSettings().then(goBack);
                } else {
                    this.revertLivePreview();
                    goBack();
                }
            });
        }
    }

    // =========================================================================
    // Load / Populate
    // =========================================================================

    async loadSettings() {
        try {
            const prefs = await api.getUserPreferences();
            this.originalPreferences = JSON.parse(JSON.stringify(prefs));
            this.currentPreferences = JSON.parse(JSON.stringify(prefs));
            this.populateForm(prefs);
            this.clearDirty();
        } catch (e) {
            console.error('Failed to load settings:', e);
            this.showToast('Failed to load settings', 'error');
        }
    }

    /**
     * Populate the form controls from a preferences object.
     */
    populateForm(prefs) {
        const fields = document.querySelectorAll('[data-field]');
        // Track color fields we already populated (two elements per field)
        const populatedColorFields = new Set();

        fields.forEach(el => {
            const field = el.getAttribute('data-field');

            // ------ Font size select (virtual field → stored as font_size_scale) ------
            // Must be checked before the `field in prefs` guard since
            // font_size_base_px is a virtual field not present in prefs.
            if (field === 'font_size_base_px') {
                const scale = prefs.font_size_scale != null ? prefs.font_size_scale : 1.0;
                const px = Math.round(scale * 16);
                el.value = String(px);
                return;
            }

            if (!(field in prefs)) return;

            const value = prefs[field];

            // ------ Color inputs (pair) ------
            if (field === 'primary_color_hex' || field === 'secondary_color_hex') {
                if (populatedColorFields.has(field)) return;
                populatedColorFields.add(field);

                const group = el.closest('.color-input-group');
                if (!group) return;

                const colorInput = group.querySelector('input[type="color"]');
                const textInput = group.querySelector('input[type="text"]');
                if (colorInput) colorInput.value = value;
                if (textInput) textInput.value = value;
                return;
            }

            // ------ Range inputs ------
            if (el.type === 'range') {
                el.value = value;
                const rangeGroup = el.closest('.range-input-group');
                if (rangeGroup) {
                    const display = rangeGroup.querySelector('.range-value');
                    if (display) display.textContent = value;
                }
                return;
            }

            // ------ Checkboxes ------
            if (el.type === 'checkbox') {
                el.checked = !!value;
                return;
            }

            // ------ Select / text / number ------
            el.value = value;

            // A <select> handed a value no option carries lands on
            // selectedIndex -1, which paints an empty control with just the
            // chevron (issue #9). Degrade to the default the markup declares
            // instead. Only `option[selected]` counts: selects whose options
            // are built at runtime (the question bank picker) declare no
            // default on purpose, so a dangling id still shows blank there.
            if (el.tagName === 'SELECT' && el.selectedIndex === -1) {
                const declared = el.querySelector('option[selected]');
                if (declared) el.value = declared.value;
            }
        });
    }

    // =========================================================================
    // Dirty State
    // =========================================================================

    markDirty() {
        this.isDirty = true;
        const warning = document.getElementById('previewWarning');
        if (warning) {
            warning.style.display = 'flex';
            warning.classList.add('visible');
        }
        const saveBtn = document.getElementById('saveBtn');
        if (saveBtn) {
            saveBtn.disabled = false;
        }
    }

    clearDirty() {
        this.isDirty = false;
        const warning = document.getElementById('previewWarning');
        if (warning) {
            warning.classList.remove('visible');
            warning.style.display = 'none';
        }
    }

    // =========================================================================
    // Live Preview
    // =========================================================================

    applyLivePreview() {
        if (!this.currentPreferences) return;
        const prefs = this.currentPreferences;
        const root = document.documentElement.style;

        // --- Theme Base Variables ---
        const themeName = prefs.theme_name || 'default';
        if (typeof _wimiApplyThemeVariables === 'function') {
            _wimiApplyThemeVariables(themeName);
            if (window.eventBus) eventBus.emit('theme:changed', { theme: themeName });
        }

        // --- Primary Color ---
        if (prefs.primary_color_hex) {
            root.setProperty('--color-primary', prefs.primary_color_hex);
            root.setProperty('--color-primary-hover', this._adjustColor(prefs.primary_color_hex, -25));
            root.setProperty('--color-primary-light', this._adjustColor(prefs.primary_color_hex, 20));
            root.setProperty('--color-primary-bg', this._adjustColor(prefs.primary_color_hex, 180));
        }

        // --- Secondary Color ---
        if (prefs.secondary_color_hex) {
            root.setProperty('--color-secondary', prefs.secondary_color_hex);
            root.setProperty('--color-secondary-hover', this._adjustColor(prefs.secondary_color_hex, -25));
        }

        // --- Font Family ---
        // Applied by the same helper themes.js runs on every page load, so
        // the preview and the saved state cannot diverge.
        if (typeof _wimiApplyFontFamily === 'function') {
            _wimiApplyFontFamily(prefs.font_family);
        }

        // --- Font Size ---
        if (prefs.font_size_scale != null) {
            root.fontSize = (prefs.font_size_scale * this.FONT_BASE_PX) + 'px';
        }

        // --- UI Density ---
        if (prefs.ui_density) {
            switch (prefs.ui_density) {
                case 'compact':
                    root.setProperty('--space-sm', '0.25rem');
                    root.setProperty('--space-md', '0.75rem');
                    root.setProperty('--space-lg', '1rem');
                    root.setProperty('--space-xl', '1.5rem');
                    break;
                case 'spacious':
                    root.setProperty('--space-sm', '0.75rem');
                    root.setProperty('--space-md', '1.25rem');
                    root.setProperty('--space-lg', '2rem');
                    root.setProperty('--space-xl', '2.5rem');
                    break;
                case 'comfortable':
                default:
                    // Remove overrides, revert to CSS defaults
                    root.removeProperty('--space-sm');
                    root.removeProperty('--space-md');
                    root.removeProperty('--space-lg');
                    root.removeProperty('--space-xl');
                    break;
            }
        }

        // --- Animations ---
        this._applyAnimationPreference(prefs.show_animations);
    }

    /**
     * Enable or disable all CSS transitions via an injected style tag.
     */
    _applyAnimationPreference(showAnimations) {
        let tag = document.getElementById(this._animationStyleTagId);
        if (!showAnimations) {
            if (!tag) {
                tag = document.createElement('style');
                tag.id = this._animationStyleTagId;
                tag.textContent = '*, *::before, *::after { transition-duration: 0s !important; animation-duration: 0s !important; }';
                document.head.appendChild(tag);
            }
        } else {
            if (tag) {
                tag.remove();
            }
        }
    }

    /**
     * Revert all live preview CSS overrides back to stylesheet defaults.
     */
    revertLivePreview() {
        const root = document.documentElement.style;

        // Clear all theme variable overrides
        if (typeof _wimiGetAllThemeVarNames === 'function') {
            const allVars = _wimiGetAllThemeVarNames();
            for (const varName of allVars) {
                root.removeProperty(varName);
            }
        }

        // Color overrides
        root.removeProperty('--color-primary');
        root.removeProperty('--color-primary-hover');
        root.removeProperty('--color-primary-light');
        root.removeProperty('--color-primary-bg');
        root.removeProperty('--color-secondary');
        root.removeProperty('--color-secondary-hover');

        // Font family and size
        root.removeProperty('--font-family');
        root.fontSize = '';

        // Density spacing
        root.removeProperty('--space-sm');
        root.removeProperty('--space-md');
        root.removeProperty('--space-lg');
        root.removeProperty('--space-xl');

        // Animations style tag
        const tag = document.getElementById(this._animationStyleTagId);
        if (tag) {
            tag.remove();
        }
    }

    /**
     * Simple lighten / darken helper.
     * Positive amount lightens, negative amount darkens.
     * @param {string} hex - Hex color string e.g. "#2563eb"
     * @param {number} amount - Amount to adjust each RGB channel (-255 to 255)
     * @returns {string} Adjusted hex color
     */
    _adjustColor(hex, amount) {
        let r = parseInt(hex.slice(1, 3), 16);
        let g = parseInt(hex.slice(3, 5), 16);
        let b = parseInt(hex.slice(5, 7), 16);
        r = Math.max(0, Math.min(255, r + amount));
        g = Math.max(0, Math.min(255, g + amount));
        b = Math.max(0, Math.min(255, b + amount));
        return '#' + [r, g, b].map(c => c.toString(16).padStart(2, '0')).join('');
    }

    // =========================================================================
    // Save / Cancel / Reset
    // =========================================================================

    async saveSettings() {
        if (this.isSaving) return;
        this.isSaving = true;

        try {
            // Compute diff: only send changed fields
            const changes = {};
            for (const [key, value] of Object.entries(this.currentPreferences)) {
                if (JSON.stringify(value) !== JSON.stringify(this.originalPreferences[key])) {
                    changes[key] = value;
                }
            }

            if (Object.keys(changes).length === 0) {
                this.showToast('No changes to save', 'info');
                this.isSaving = false;
                return;
            }

            const updated = await api.updateUserPreferences(changes);
            this.originalPreferences = JSON.parse(JSON.stringify(updated));
            this.currentPreferences = JSON.parse(JSON.stringify(updated));
            this.clearDirty();
            if (window.eventBus) eventBus.emit('settings:changed', updated);

            // Handle MCP server start/stop based on preference change
            if ('mcp_server_enabled' in changes) {
                await this._applyMcpServerState(updated.mcp_server_enabled, updated.mcp_server_port);
            } else if ('mcp_server_port' in changes && updated.mcp_server_enabled) {
                // Port changed while enabled — restart
                await api.stopMcpServer();
                await this._applyMcpServerState(true, updated.mcp_server_port);
            }

            this.showToast('Settings saved successfully', 'success');
        } catch (e) {
            console.error('Failed to save settings:', e);
            this.showToast('Failed to save settings: ' + e.message, 'error');
        } finally {
            this.isSaving = false;
        }
    }

    cancelChanges() {
        if (!this.isDirty) return;
        this.currentPreferences = JSON.parse(JSON.stringify(this.originalPreferences));
        this.populateForm(this.originalPreferences);
        this.revertLivePreview();
        this.applyLivePreview();
        this.clearDirty();
    }

    async resetToDefaults() {
        if (!confirm('Reset all settings to their default values?')) return;
        try {
            const updated = await api.updateUserPreferences(this.DEFAULTS);
            this.originalPreferences = JSON.parse(JSON.stringify(updated));
            this.currentPreferences = JSON.parse(JSON.stringify(updated));
            this.populateForm(updated);
            this.revertLivePreview();
            this.clearDirty();
            this.showToast('Settings reset to defaults', 'success');
        } catch (e) {
            console.error('Failed to reset settings:', e);
            this.showToast('Failed to reset settings', 'error');
        }
    }

    // =========================================================================
    // Per-Exam Analytics
    // =========================================================================

    async initExamAnalytics() {
        const selector = document.getElementById('analytics_exam_selector');
        if (!selector) return;

        // Populate exam dropdown
        try {
            const exams = await api.getAllExamContexts(true);
            exams.forEach(exam => {
                const option = document.createElement('option');
                option.value = exam.id;
                option.textContent = exam.exam_name;
                selector.appendChild(option);
            });
        } catch (e) {
            console.error('Failed to load exams for analytics config:', e);
        }

        // On exam change, load its analytics config
        selector.addEventListener('change', async () => {
            const examId = selector.value ? parseInt(selector.value) : null;
            this._selectedExamId = examId;

            const configDiv = document.getElementById('examAnalyticsConfig');
            if (!examId) {
                configDiv.style.display = 'none';
                return;
            }

            await this.loadExamAnalyticsConfig(examId);
            configDiv.style.display = 'block';
        });

        // Save button
        const saveBtn = document.getElementById('saveExamAnalyticsBtn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveExamAnalyticsConfig());
        }
    }

    async loadExamAnalyticsConfig(examId) {
        try {
            // Load config
            const config = await api.getExamAnalyticsConfig(examId);
            this._examAnalyticsConfig = config;

            // Check if exam uses dimensions
            let hasDimensions = false;
            try {
                const dimResult = await api.examUsesDimensions(examId);
                hasDimensions = dimResult && dimResult.uses_dimensions;
            } catch (e) {
                hasDimensions = false;
            }
            this._examHasDimensions = hasDimensions;

            // Show/hide dimension selector
            const dimGroup = document.getElementById('defaultDimensionGroup');
            if (hasDimensions) {
                dimGroup.style.display = 'block';
                await this.populateDimensionSelector(examId, config.default_dimension_id);
            } else {
                dimGroup.style.display = 'none';
            }

            // Render chart toggles
            this.renderChartToggles(config.chart_visibility, hasDimensions);

        } catch (e) {
            console.error('Failed to load exam analytics config:', e);
            this.showToast('Failed to load exam analytics config', 'error');
        }
    }

    async populateDimensionSelector(examId, currentDimensionId) {
        const select = document.getElementById('default_dimension_id');
        if (!select) return;

        // Clear existing options except first
        select.innerHTML = '<option value="">All Dimensions</option>';

        try {
            const dimensions = await api.getDimensions(examId);
            dimensions.forEach(dim => {
                const option = document.createElement('option');
                option.value = dim.id;
                option.textContent = dim.name;
                select.appendChild(option);
            });

            if (currentDimensionId) {
                select.value = String(currentDimensionId);
            }
        } catch (e) {
            console.error('Failed to load dimensions:', e);
        }
    }

    renderChartToggles(chartVisibility, hasDimensions) {
        const container = document.getElementById('chartToggleList');
        if (!container) return;
        container.innerHTML = '';

        this.CHART_DEFINITIONS.forEach(def => {
            // Hide dimension-only charts if exam has no dimensions
            if (def.dimensionOnly && !hasDimensions) return;

            const isVisible = chartVisibility[def.key] !== false;

            const item = document.createElement('div');
            item.className = 'chart-toggle-item';
            item.innerHTML = `
                <label>
                    <input type="checkbox" data-chart-key="${def.key}" data-testid="settings-analytics-chart-${def.key}" ${isVisible ? 'checked' : ''}>
                    <span>${def.label}</span>
                </label>
            `;
            container.appendChild(item);
        });
    }

    async saveExamAnalyticsConfig() {
        if (!this._selectedExamId) return;

        // Collect dimension filter
        const dimSelect = document.getElementById('default_dimension_id');
        const defaultDimensionId = dimSelect && dimSelect.value ? parseInt(dimSelect.value) : null;

        // Collect chart visibility
        const chartVisibility = {};
        document.querySelectorAll('#chartToggleList input[data-chart-key]').forEach(cb => {
            chartVisibility[cb.dataset.chartKey] = cb.checked;
        });

        try {
            await api.updateExamAnalyticsConfig({
                examContextId: this._selectedExamId,
                defaultDimensionId: defaultDimensionId,
                chartVisibility: chartVisibility
            });
            this.showToast('Exam analytics config saved', 'success');
        } catch (e) {
            console.error('Failed to save exam analytics config:', e);
            this.showToast('Failed to save exam analytics config', 'error');
        }
    }

    handleHashNavigation() {
        const hash = window.location.hash.replace('#', '');
        if (!hash) return;

        const navItem = document.querySelector(`.settings-nav-item[data-panel="${hash}"]`);
        if (navItem) {
            navItem.click();
        }
    }

    // =========================================================================
    // Hotkey Capture
    // =========================================================================

    /**
     * Reserved key combos that should not be assignable as timer hotkeys.
     */
    static RESERVED_COMBOS = new Set([
        'Ctrl+S', 'Ctrl+C', 'Ctrl+V', 'Ctrl+Z', 'Ctrl+X', 'Ctrl+A', 'Ctrl+P', 'Ctrl+F',
        'Meta+S', 'Meta+C', 'Meta+V', 'Meta+Z', 'Meta+X', 'Meta+A', 'Meta+P', 'Meta+F',
        'Tab', 'Escape', 'F5', 'F12'
    ]);

    /**
     * All hotkey field IDs for cross-field duplicate detection.
     */
    static HOTKEY_FIELDS = [
        'hotkey_timer_pause_resume',
        'hotkey_timer_new_round',
        'hotkey_timer_end_round'
    ];

    setupHotkeyCapture() {
        const inputs = document.querySelectorAll('.hotkey-capture');
        inputs.forEach(input => {
            const field = input.getAttribute('data-field');

            input.addEventListener('focus', () => {
                input.classList.add('recording');
                input.dataset.originalValue = input.value;
                input.value = 'Press a key combo...';
            });

            input.addEventListener('blur', () => {
                input.classList.remove('recording');
                // If still showing placeholder, restore original value
                if (input.value === 'Press a key combo...') {
                    input.value = input.dataset.originalValue || '';
                }
                this._hideConflictWarning();
            });

            input.addEventListener('keydown', (e) => {
                e.preventDefault();
                e.stopPropagation();

                // Escape clears the binding
                if (e.key === 'Escape') {
                    input.value = '';
                    input.classList.remove('recording');
                    input.blur();
                    this._onFieldChange(field, '');
                    this._hideConflictWarning();
                    return;
                }

                // Ignore bare modifier keys
                if (['Control', 'Shift', 'Alt', 'Meta'].includes(e.key)) {
                    return;
                }

                const combo = this._buildComboString(e);

                // Check reserved
                if (SettingsPage.RESERVED_COMBOS.has(combo)) {
                    this._showConflictWarning(`"${combo}" is reserved by the application.`);
                    return;
                }

                // Check duplicates among the 3 hotkey fields
                const duplicate = SettingsPage.HOTKEY_FIELDS.find(f => {
                    if (f === field) return false;
                    const otherInput = document.getElementById(f);
                    return otherInput && otherInput.value === combo;
                });
                if (duplicate) {
                    const label = duplicate.replace('hotkey_timer_', '').replace(/_/g, ' ');
                    this._showConflictWarning(`"${combo}" is already assigned to ${label}.`);
                    return;
                }

                // Accept the combo
                input.value = combo;
                input.classList.remove('recording');
                input.blur();
                this._onFieldChange(field, combo);
                this._hideConflictWarning();
            });
        });

        // Clear buttons
        document.querySelectorAll('.hotkey-clear-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const field = btn.getAttribute('data-hotkey-field');
                const input = document.getElementById(field);
                if (input) {
                    input.value = '';
                    this._onFieldChange(field, '');
                }
                this._hideConflictWarning();
            });
        });
    }

    /**
     * Build a normalized combo string from a KeyboardEvent.
     * e.g. "Ctrl+Shift+K", "Alt+P", "F5"
     */
    _buildComboString(e) {
        const parts = [];
        if (e.ctrlKey) parts.push('Ctrl');
        if (e.altKey) parts.push('Alt');
        if (e.shiftKey) parts.push('Shift');
        if (e.metaKey) parts.push('Meta');

        let key = e.key;
        // Normalize key name
        if (key === ' ') key = 'Space';
        else if (key.length === 1) key = key.toUpperCase();

        parts.push(key);
        return parts.join('+');
    }

    _showConflictWarning(message) {
        const el = document.getElementById('hotkeyConflictWarning');
        if (el) {
            el.textContent = message;
            el.style.display = 'block';
        }
    }

    _hideConflictWarning() {
        const el = document.getElementById('hotkeyConflictWarning');
        if (el) {
            el.style.display = 'none';
        }
    }

    // =========================================================================
    // Profile (export / import — same flows as the profile picker)
    // =========================================================================

    /**
     * True when the profile transfer API (Task-4 bridge surface) is
     * available. Mirrors the feature detection in profile_select.js.
     */
    _profileTransferApiAvailable() {
        return typeof api.openProfileExportDialog === 'function' &&
               typeof api.exportProfile === 'function' &&
               typeof api.openProfileImportDialog === 'function' &&
               typeof api.readProfileArchive === 'function';
    }

    /** Normalize a file-dialog response ({file_path} | string | null). */
    _profileDialogPath(result) {
        if (!result) return null;
        if (typeof result === 'string') return result;
        return result.file_path || result.dest_path || result.path || null;
    }

    /** Two-letter initials from a display name (fallback: username). */
    _profileInitials(displayName, username) {
        const source = (displayName || username || '?').trim();
        const words = source.split(/\s+/).filter(Boolean);
        if (words.length >= 2) {
            return (words[0][0] + words[1][0]).toUpperCase();
        }
        return source.slice(0, 2).toUpperCase();
    }

    async initProfileSection() {
        const navItem = document.getElementById('profileNavItem');
        const panel = document.getElementById('profilePanel');
        if (!navItem || !panel) return;

        // Feature-detect the profile API — hide the whole section when the
        // bridge surface is absent so this page keeps working standalone.
        if (typeof api.getCurrentProfile !== 'function') {
            navItem.style.display = 'none';
            return;
        }

        this._currentProfile = null;
        try {
            const data = await api.getCurrentProfile();
            this._currentProfile = (data && data.profile) || null;
        } catch (e) {
            console.warn('Failed to load current profile:', e);
        }

        // Render the current-profile card.
        const avatarEl = document.getElementById('profileSettingsAvatar');
        const nameEl = document.getElementById('profileSettingsName');
        const usernameEl = document.getElementById('profileSettingsUsername');
        if (this._currentProfile) {
            const p = this._currentProfile;
            if (avatarEl) avatarEl.textContent = this._profileInitials(p.display_name, p.username);
            if (nameEl) nameEl.textContent = p.display_name || p.username;
            if (usernameEl) usernameEl.textContent = '@' + p.username;
        } else {
            if (avatarEl) avatarEl.textContent = '?';
            if (nameEl) nameEl.textContent = 'No profile open';
            if (usernameEl) usernameEl.textContent = '';
        }

        // Transfer controls (export/import) need the Task-4 bridge surface.
        const transferSection = document.getElementById('profileTransferSection');
        if (!this._profileTransferApiAvailable()) {
            if (transferSection) transferSection.style.display = 'none';
            return;
        }

        const exportBtn = document.getElementById('profileExportBtn');
        const importBtn = document.getElementById('profileImportBtn');
        if (exportBtn) {
            exportBtn.disabled = !this._currentProfile;
            exportBtn.addEventListener('click', () => this.handleProfileExport());
        }
        if (importBtn) {
            importBtn.addEventListener('click', () => this.handleProfileImport());
        }
    }

    async handleProfileExport() {
        const profile = this._currentProfile;
        if (!profile || !this._profileTransferApiAvailable()) return;

        const includeMedia = !!document.getElementById('profileExportIncludeMedia')?.checked;
        const exportBtn = document.getElementById('profileExportBtn');
        const originalText = exportBtn ? exportBtn.textContent : '';

        try {
            const dialogResult = await api.openProfileExportDialog({
                default_filename: profile.username + '.wimi'
            });
            const destPath = this._profileDialogPath(dialogResult);
            if (!destPath) return; // user cancelled the save dialog

            if (exportBtn) {
                exportBtn.disabled = true;
                exportBtn.textContent = 'Exporting…';
            }

            await api.exportProfile({
                user_id: profile.id,
                include_media: includeMedia,
                dest_path: destPath
            });
            this.showToast('Profile exported to ' + destPath, 'success');
        } catch (e) {
            console.error('Failed to export profile:', e);
            this.showToast(e.message || 'Failed to export profile', 'error');
        } finally {
            if (exportBtn) {
                exportBtn.disabled = false;
                exportBtn.textContent = originalText;
            }
        }
    }

    async handleProfileImport() {
        if (!this._profileTransferApiAvailable()) return;

        try {
            const dialogResult = await api.openProfileImportDialog();
            const archivePath = this._profileDialogPath(dialogResult);
            if (!archivePath) return; // user cancelled

            // Hand off to the profile picker page, which owns the single
            // import-preview implementation (profile_select.js checks this
            // sessionStorage key on load and auto-opens the preview modal).
            try {
                sessionStorage.setItem('wimi.pendingProfileImport', archivePath);
            } catch (storageError) {
                console.error('Failed to stage import path:', storageError);
                this.showToast('Could not start the import', 'error');
                return;
            }
            window.location.href = 'profile_select.html';
        } catch (e) {
            console.error('Failed to open import dialog:', e);
            this.showToast(e.message || 'Failed to open the file dialog', 'error');
        }
    }

    // =========================================================================
    // Question Banks
    // =========================================================================

    /**
     * Load the question-bank rows for the browser pane.
     *
     * Two reads, because they answer different questions: getPaneSources()
     * returns only sources that already have a web address, in the order the
     * pane shows them (most recently opened first), while getQuestionSources()
     * returns everything — the difference is exactly the set of rows that need
     * an invitation to add an address.
     */
    async initQuestionBanks() {
        const container = document.getElementById('questionBankList');
        if (!container) return;

        // Feature-detect the pane API so this page keeps working standalone.
        if (typeof api.getPaneSources !== 'function') {
            const navItem = document.querySelector('.settings-nav-item[data-panel="question_banks"]');
            if (navItem) navItem.style.display = 'none';
            return;
        }

        try {
            const [paneSources, allSources] = await Promise.all([
                api.getPaneSources(),
                api.getQuestionSources()
            ]);
            this._questionBanks = this._mergeQuestionBanks(paneSources, allSources);
        } catch (e) {
            console.error('Failed to load question banks:', e);
            this._questionBanks = null;
            container.innerHTML =
                '<div class="qbank-empty">Could not load your question banks. Reopen settings to try again.</div>';
            return;
        }

        this.renderQuestionBanks();
    }

    /**
     * Sources with an address in pane order, then the rest by name.
     *
     * @param {Array<object>} paneSources - From getPaneSources().
     * @param {Array<object>} allSources - From getQuestionSources().
     * @returns {Array<object>} Rows of {id, name, url, desktopSite}.
     */
    _mergeQuestionBanks(paneSources, allSources) {
        const withUrl = (paneSources || []).map(s => ({
            id: s.id,
            name: s.source_name || '',
            url: s.url || '',
            desktopSite: !!s.desktop_site
        }));

        const seen = new Set(withUrl.map(s => s.id));
        const withoutUrl = (allSources || [])
            .filter(s => !seen.has(s.id))
            .map(s => ({
                id: s.id,
                name: s.source_name || '',
                url: '',
                desktopSite: false
            }))
            .sort((a, b) => a.name.localeCompare(b.name));

        return withUrl.concat(withoutUrl);
    }

    /**
     * Fill the "which bank" picker.
     *
     * Options come from the same list the shortcut rows render, so a
     * bank can only be nominated once it has an address — nominating one
     * the pane cannot open would be a setting that silently does
     * nothing.
     *
     * The picker used to be hidden unless the open mode was 'source'.
     * It is always visible now: the same choice also decides which bank
     * a new tab lands on, so it applies whatever the open mode is.
     *
     * The select carries data-field, so the existing save machinery
     * persists it; this only supplies the options.
     *
     * populateForm runs before this select has any options, so on the
     * first render its value is empty even when a bank is saved. Fall
     * back to the saved preference then; a later re-render (a row gained
     * or lost an address) keeps whatever the select currently shows.
     */
    renderPaneOpenMode() {
        const pick = document.getElementById('pane_default_source_id');
        if (!pick) return;

        const withUrl = (this._questionBanks || []).filter(b => b.url);
        const saved = this.currentPreferences
            ? this.currentPreferences.pane_default_source_id
            : null;
        const chosen = pick.value || (saved != null ? String(saved) : '');
        pick.innerHTML = withUrl.length
            ? withUrl.map(b =>
                '<option value="' + b.id + '">' + this._escapeHtml(b.name) + '</option>'
              ).join('')
            : '<option value="">Add a web address to a question bank first</option>';
        if (chosen && withUrl.some(b => String(b.id) === String(chosen))) {
            pick.value = chosen;
        }
    }

    renderQuestionBanks() {
        this.renderPaneOpenMode();
        const container = document.getElementById('questionBankList');
        if (!container) return;
        container.innerHTML = '';

        const banks = this._questionBanks || [];
        if (banks.length === 0) {
            container.innerHTML =
                '<div class="qbank-empty">No question banks yet. Add one when you start a study session.</div>';
            return;
        }

        banks.forEach(bank => {
            const hasUrl = !!bank.url;
            const row = document.createElement('div');
            row.className = 'qbank-row';
            row.dataset.sourceId = String(bank.id);
            row.setAttribute('data-testid', 'settings-qbank-row-' + bank.id);

            const urlId = 'qbank-url-' + bank.id;
            const toggleId = 'qbank-desktop-' + bank.id;

            row.innerHTML =
                '<label class="qbank-row-name" for="' + urlId + '">' + this._escapeHtml(bank.name) + '</label>' +
                '<input type="url" class="qbank-row-url" id="' + urlId + '"' +
                    ' data-testid="settings-qbank-url-' + bank.id + '"' +
                    ' value="' + this._escapeHtml(bank.url) + '"' +
                    ' placeholder="Add a web address"' +
                    ' spellcheck="false" autocomplete="off">' +
                (hasUrl
                    ? '<label class="qbank-row-desktop" for="' + toggleId + '">' +
                          '<input type="checkbox" id="' + toggleId + '"' +
                              ' data-testid="settings-qbank-desktop-' + bank.id + '"' +
                              (bank.desktopSite ? ' checked' : '') + '>' +
                          '<span>Desktop site</span>' +
                      '</label>'
                    : '<span class="qbank-row-nodesktop" aria-hidden="true">&mdash;</span>');

            container.appendChild(row);

            const urlInput = row.querySelector('.qbank-row-url');
            if (urlInput) {
                urlInput.addEventListener('change', () => this.handleQuestionBankUrl(bank, urlInput));
            }

            const toggle = row.querySelector('input[type="checkbox"]');
            if (toggle) {
                toggle.addEventListener('change', () => this.handleQuestionBankDesktopSite(bank, toggle));
            }
        });
    }

    /**
     * Save an address the student typed, and re-render when the row changes
     * state — gaining an address is what earns the Desktop site checkbox.
     */
    async handleQuestionBankUrl(bank, input) {
        const url = this._normalizeUrl(input.value);
        if (url === bank.url) {
            input.value = url;
            return;
        }

        try {
            await api.updateQuestionSource(bank.id, { url: url });
        } catch (e) {
            console.error('Failed to save question bank address:', e);
            input.value = bank.url;
            this.showToast('Could not save the address. Try again.', 'error');
            return;
        }

        const hadUrl = !!bank.url;
        bank.url = url;
        if (!url) bank.desktopSite = false;

        this.showToast(url ? 'Address saved' : 'Address removed', 'success');

        if (hadUrl !== !!url) {
            this.renderQuestionBanks();
        } else {
            input.value = url;
        }
    }

    async handleQuestionBankDesktopSite(bank, toggle) {
        const enabled = toggle.checked;
        try {
            await api.setPaneDesktopSite(bank.id, enabled);
            bank.desktopSite = enabled;
            this.showToast(
                'Desktop site ' + (enabled ? 'on' : 'off') + ' for ' + bank.name,
                'success'
            );
        } catch (e) {
            console.error('Failed to save desktop site setting:', e);
            toggle.checked = !enabled;
            this.showToast('Could not change the desktop site setting. Try again.', 'error');
        }
    }

    /**
     * Trim an address and give it a scheme, so a bare "uworld.com" still
     * opens. The normalized value is written back into the field rather
     * than saved invisibly.
     */
    _normalizeUrl(value) {
        const trimmed = String(value || '').trim();
        if (!trimmed) return '';
        if (/^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed)) return trimmed;
        return 'https://' + trimmed;
    }

    // =========================================================================
    // Addons
    // =========================================================================

    async initAddons() {
        try {
            this._installedPlugins = await api.getInstalledPlugins();
        } catch (e) {
            console.error('Failed to load installed plugins:', e);
            this._installedPlugins = [];
        }
        this.renderAddonList();
        this.renderPluginSubNav();
        await this.renderPluginSettingsPanels();

        // Install button
        const installBtn = document.getElementById('installPluginBtn');
        if (installBtn) {
            installBtn.addEventListener('click', () => this.handleInstallPlugin());
        }

        // Signal that plugin settings panels (and their slots) are now in the DOM.
        // Plugin frontend.js that builds custom settings UI should listen for this
        // event, since the slot elements don't exist until initAddons() completes.
        window.dispatchEvent(new CustomEvent('wimi:plugin-settings-ready'));
    }

    async handleInstallPlugin() {
        try {
            const result = await api.installPlugin();
            if (result == null) return; // user cancelled (data omitted → undefined)
            const msg = result.replaced
                ? result.name + ' v' + result.version + ' replaced successfully'
                : result.name + ' v' + result.version + ' installed successfully';
            this.showToast(msg, 'success');
            await this.initAddons();
        } catch (e) {
            console.error('Failed to install plugin:', e);
            this.showToast(e.message || 'Failed to install plugin', 'error');
        }
    }

    async handleUninstallPlugin(pluginId, pluginName) {
        if (!confirm('Uninstall "' + pluginName + '"? This will remove the plugin and all its data.')) {
            return;
        }
        try {
            await api.uninstallPlugin(pluginId);
            this.showToast(pluginName + ' uninstalled', 'success');
            await this.initAddons();
        } catch (e) {
            console.error('Failed to uninstall plugin:', e);
            this.showToast(e.message || 'Failed to uninstall plugin', 'error');
        }
    }

    renderAddonList() {
        const container = document.getElementById('addonList');
        if (!container) return;
        container.innerHTML = '';

        if (!this._installedPlugins || this._installedPlugins.length === 0) {
            container.innerHTML = '<div class="addon-empty">No addons installed. Use "Install from .zip" above or place plugin folders in <code>app_data/plugins/</code>.</div>';
            return;
        }

        this._installedPlugins.forEach(plugin => {
            const card = document.createElement('div');
            card.className = 'addon-card';
            card.dataset.pluginId = plugin.id;
            card.setAttribute('data-testid', 'settings-addon-card-' + plugin.id);

            const toggleId = 'addon-toggle-' + plugin.id;
            const safePluginId = this._escapeHtml(plugin.id);

            card.innerHTML =
                '<div class="addon-card-header">' +
                    '<div class="addon-card-info">' +
                        '<span class="addon-card-name">' + this._escapeHtml(plugin.name) + '</span>' +
                        '<span class="addon-card-version">v' + this._escapeHtml(plugin.version) + '</span>' +
                        (plugin.author ? '<span class="addon-card-author">by ' + this._escapeHtml(plugin.author) + '</span>' : '') +
                    '</div>' +
                    '<label class="addon-toggle-label" for="' + toggleId + '">' +
                        '<input type="checkbox" id="' + toggleId + '" data-testid="settings-addon-toggle-' + safePluginId + '" ' + (plugin.enabled ? 'checked' : '') + '>' +
                        '<span>Enabled</span>' +
                    '</label>' +
                '</div>' +
                (plugin.description ? '<p class="addon-card-description">' + this._escapeHtml(plugin.description) + '</p>' : '') +
                (plugin.permissions && plugin.permissions.length > 0 ?
                    '<div class="addon-permissions">' +
                        plugin.permissions.map(function(p) {
                            return '<span class="addon-permission-badge">' + p + '</span>';
                        }).join('') +
                    '</div>' : '') +
                '<div class="addon-card-actions">' +
                    '<button class="btn-addon-uninstall" data-testid="settings-addon-uninstall-' + safePluginId + '" data-plugin-id="' + plugin.id + '">Uninstall</button>' +
                '</div>';

            container.appendChild(card);

            // Toggle handler
            const toggle = card.querySelector('#' + toggleId);
            if (toggle) {
                toggle.addEventListener('change', async () => {
                    try {
                        await api.setPluginEnabled(plugin.id, toggle.checked);
                        plugin.enabled = toggle.checked;
                        this.showToast(
                            plugin.name + ' ' + (toggle.checked ? 'enabled' : 'disabled'),
                            'success'
                        );
                    } catch (e) {
                        console.error('Failed to toggle plugin:', e);
                        toggle.checked = !toggle.checked;
                        this.showToast('Failed to update plugin state', 'error');
                    }
                });
            }

            // Uninstall handler
            const uninstallBtn = card.querySelector('.btn-addon-uninstall');
            if (uninstallBtn) {
                uninstallBtn.addEventListener('click', () => {
                    this.handleUninstallPlugin(plugin.id, plugin.name);
                });
            }
        });
    }

    renderPluginSubNav() {
        const container = document.getElementById('pluginSubNav');
        if (!container) return;
        container.innerHTML = '';

        if (!this._installedPlugins) return;

        this._installedPlugins.forEach(plugin => {
            var hasManifestSettings = plugin.settings && plugin.settings.length > 0;
            var hasCustomSlot = plugin.slots && plugin.slots['plugin-settings-' + plugin.id];
            if (!hasManifestSettings && !hasCustomSlot) return;

            const btn = document.createElement('button');
            btn.className = 'settings-nav-item plugin-sub-nav';
            btn.setAttribute('data-panel', 'plugin-settings-' + plugin.id);
            btn.setAttribute('data-testid', 'settings-plugin-nav-' + plugin.id);
            btn.innerHTML =
                '<span class="nav-icon">&#128268;</span>' +
                '<span class="nav-label">' + this._escapeHtml(plugin.name) + '</span>';
            container.appendChild(btn);
        });
    }

    async renderPluginSettingsPanels() {
        const container = document.getElementById('pluginSettingsPanels');
        if (!container) return;
        container.innerHTML = '';

        if (!this._installedPlugins) return;

        for (var i = 0; i < this._installedPlugins.length; i++) {
            var plugin = this._installedPlugins[i];
            var hasManifestSettings = plugin.settings && plugin.settings.length > 0;
            var hasCustomSlot = plugin.slots && plugin.slots['plugin-settings-' + plugin.id];
            if (!hasManifestSettings && !hasCustomSlot) continue;

            const panel = document.createElement('div');
            panel.className = 'settings-panel';
            panel.setAttribute('data-panel', 'plugin-settings-' + plugin.id);
            panel.setAttribute('data-testid', 'settings-plugin-panel-' + plugin.id);

            let html = '<h2 class="panel-title">' + this._escapeHtml(plugin.name) + ' Settings</h2>';

            if (hasManifestSettings) {
                plugin.settings.forEach(setting => {
                    html += '<div class="form-group">';
                    html += '<label for="plugin-setting-' + plugin.id + '-' + setting.key + '">' + this._escapeHtml(setting.label) + '</label>';
                    if (setting.description) {
                        html += '<p class="field-description">' + this._escapeHtml(setting.description) + '</p>';
                    }
                    html += this._renderPluginSettingField(plugin.id, setting, setting.default);
                    html += '</div>';
                });
            }

            // Per-plugin custom settings slot
            html += '<div data-plugin-slot="plugin-settings-' + plugin.id + '"></div>';

            if (hasManifestSettings) {
                html += '<button class="btn-save plugin-settings-save" data-testid="settings-plugin-save-' + this._escapeHtml(plugin.id) + '" data-plugin-id="' + plugin.id + '">Save ' + this._escapeHtml(plugin.name) + ' Settings</button>';
            }

            panel.innerHTML = html;
            container.appendChild(panel);

            if (hasManifestSettings) {
                // Load saved settings and populate form before continuing
                await this._loadPluginSettingsIntoForm(plugin.id, plugin.settings);

                // Save button handler
                const saveBtn = panel.querySelector('.plugin-settings-save');
                if (saveBtn) {
                    saveBtn.addEventListener('click', () => this._savePluginSettings(plugin.id, plugin.settings));
                }
            }
        }

        // Retroactive injection: PluginLoader may have already run before
        // these panels were created. Re-inject any plugin-settings-* slots.
        if (window.PluginLoader) {
            var loaded = PluginLoader.getLoadedPlugins();
            for (var pluginId in loaded) {
                var manifest = loaded[pluginId];
                if (!manifest.slots) continue;
                var slotName = 'plugin-settings-' + pluginId;
                if (!manifest.slots[slotName]) continue;
                var slotEl = document.querySelector('[data-plugin-slot="' + slotName + '"]');
                if (slotEl && !slotEl.querySelector('[data-plugin-id="' + pluginId + '"]')) {
                    var wrapper = document.createElement('div');
                    wrapper.dataset.pluginId = pluginId;
                    wrapper.innerHTML = manifest.slots[slotName];
                    slotEl.appendChild(wrapper);
                }
            }
        }
    }

    _renderPluginSettingField(pluginId, setting, value) {
        const id = 'plugin-setting-' + pluginId + '-' + setting.key;

        switch (setting.type) {
            case 'text':
                return '<input type="text" id="' + id + '" data-plugin-setting="' + setting.key + '" value="' + this._escapeHtml(String(value || '')) + '">';

            case 'number': {
                var attrs = '';
                if (setting.min != null) attrs += ' min="' + setting.min + '"';
                if (setting.max != null) attrs += ' max="' + setting.max + '"';
                return '<input type="number" id="' + id + '" data-plugin-setting="' + setting.key + '" value="' + (value != null ? value : '') + '"' + attrs + '>';
            }

            case 'toggle':
                return '<label class="checkbox-label"><input type="checkbox" id="' + id + '" data-plugin-setting="' + setting.key + '" ' + (value ? 'checked' : '') + '><span>' + this._escapeHtml(setting.label) + '</span></label>';

            case 'select': {
                var html = '<select id="' + id + '" data-plugin-setting="' + setting.key + '">';
                (setting.options || []).forEach(function(opt) {
                    var optValue = typeof opt === 'object' ? opt.value : opt;
                    var optLabel = typeof opt === 'object' ? opt.label : opt;
                    var selected = optValue === value ? ' selected' : '';
                    html += '<option value="' + optValue + '"' + selected + '>' + optLabel + '</option>';
                });
                html += '</select>';
                return html;
            }

            default:
                return '<input type="text" id="' + id + '" data-plugin-setting="' + setting.key + '" value="' + this._escapeHtml(String(value || '')) + '">';
        }
    }

    async _loadPluginSettingsIntoForm(pluginId, settingDefs) {
        try {
            const saved = await api.getPluginSettings(pluginId);
            settingDefs.forEach(setting => {
                const el = document.getElementById('plugin-setting-' + pluginId + '-' + setting.key);
                if (!el) return;
                const value = saved[setting.key] != null ? saved[setting.key] : setting.default;
                if (el.type === 'checkbox') {
                    el.checked = !!value;
                } else {
                    el.value = value != null ? value : '';
                }
            });
        } catch (e) {
            console.error('Failed to load plugin settings for ' + pluginId + ':', e);
        }
    }

    async _savePluginSettings(pluginId, settingDefs) {
        const settings = {};
        settingDefs.forEach(setting => {
            const el = document.getElementById('plugin-setting-' + pluginId + '-' + setting.key);
            if (!el) return;
            if (el.type === 'checkbox') {
                settings[setting.key] = el.checked;
            } else if (setting.type === 'number') {
                settings[setting.key] = el.value !== '' ? parseFloat(el.value) : null;
            } else {
                settings[setting.key] = el.value;
            }
        });

        try {
            await api.updatePluginSettings(pluginId, settings);
            this.showToast('Plugin settings saved', 'success');
        } catch (e) {
            console.error('Failed to save plugin settings:', e);
            this.showToast('Failed to save plugin settings', 'error');
        }
    }

    _escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // =========================================================================
    // Toast Notifications
    // =========================================================================

    /**
     * Show a brief toast message.
     * @param {string} message - Text to display
     * @param {'success'|'error'|'info'} type - Visual style
     */
    showToast(message, type = 'info') {
        // Reuse existing toast element or create one
        let toast = document.querySelector('.settings-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.className = 'settings-toast';
            document.body.appendChild(toast);
        }

        // Clear any pending hide timer
        if (this._toastTimer) {
            clearTimeout(this._toastTimer);
            this._toastTimer = null;
        }

        // Remove previous type classes and visible state so we can re-trigger
        toast.classList.remove('visible', 'success', 'error', 'info');
        toast.textContent = message;
        toast.classList.add(type);

        // Force reflow before adding visible class so the transition re-fires
        void toast.offsetWidth;
        toast.classList.add('visible');

        // Auto-hide after 3 seconds
        this._toastTimer = setTimeout(() => {
            toast.classList.remove('visible');
            this._toastTimer = null;
        }, 3000);
    }

    // =========================================================================
    // MCP Server
    // =========================================================================

    async refreshMcpStatus() {
        try {
            const status = await api.getMcpServerStatus();
            this._updateMcpStatusUI(status);
        } catch (e) {
            // This used to say "hide panel silently". It hid nothing: the
            // panel stayed up showing whatever the markup shipped, which was
            // `Stopped` -- so a bridge that could not answer the question
            // rendered as a confident answer to it (#90).
            //
            // The panel deliberately still does not hide. This catch is not
            // specific to an older bridge: `_callBridge` throws here for any
            // failure, including a transient one, and removing a settings
            // panel on a failed read would take away the only way to try
            // again. What it must not do is leave a state claim standing, so
            // say the true thing -- the status could not be read -- which is
            // a different fact from "the server is stopped" and now looks
            // like one. Logged rather than swallowed: a real error in the
            // slot left no trace at all before.
            console.warn('Could not read MCP server status:', e);
            this._setMcpStatusUnavailable();
        }
    }

    /** Render the "we could not find out" state, distinct from "stopped". */
    _setMcpStatusUnavailable() {
        const dot = document.getElementById('mcpStatusDot');
        const text = document.getElementById('mcpStatusText');
        const urlWrap = document.getElementById('mcpConnectionUrl');
        const instructions = document.getElementById('mcpConnectInstructions');

        if (!dot || !text) return;

        dot.className = 'mcp-status-dot unknown';
        text.textContent = 'Status unavailable';
        // No URL and no connect instructions: both describe a running server,
        // and we do not know that there is one.
        if (urlWrap) urlWrap.style.display = 'none';
        if (instructions) instructions.style.display = 'none';
    }

    async _applyMcpServerState(enabled, port) {
        try {
            if (enabled) {
                const result = await api.startMcpServer(port || 8000);
                this._updateMcpStatusUI(result);
                if (!result.running) {
                    this.showToast('MCP server failed: ' + (result.error || 'Unknown error'), 'error');
                }
            } else {
                const result = await api.stopMcpServer();
                this._updateMcpStatusUI(result);
            }
        } catch (e) {
            this.showToast('MCP server error: ' + e.message, 'error');
        }
    }

    _updateMcpStatusUI(status) {
        const dot = document.getElementById('mcpStatusDot');
        const text = document.getElementById('mcpStatusText');
        const urlWrap = document.getElementById('mcpConnectionUrl');
        const urlValue = document.getElementById('mcpUrlValue');
        const instructions = document.getElementById('mcpConnectInstructions');

        if (!dot || !text) return;

        dot.className = 'mcp-status-dot';
        if (status.running) {
            dot.classList.add('running');
            text.textContent = 'Running on port ' + status.port;
            if (urlWrap && urlValue) {
                urlValue.textContent = status.url;
                urlWrap.style.display = '';
            }
            if (instructions) {
                this._populateMcpInstructions(status.url, status.port);
                instructions.style.display = '';
            }
        } else if (status.error) {
            dot.classList.add('error');
            text.textContent = 'Error: ' + status.error;
            if (urlWrap) urlWrap.style.display = 'none';
            if (instructions) instructions.style.display = 'none';
        } else {
            dot.classList.add('stopped');
            text.textContent = 'Stopped';
            if (urlWrap) urlWrap.style.display = 'none';
            if (instructions) instructions.style.display = 'none';
        }
    }

    _populateMcpInstructions(url, port) {
        const jsonEl = document.getElementById('mcpConfigJson');
        const cliEl = document.getElementById('mcpConfigCli');

        if (jsonEl) {
            const config = {
                mcpServers: {
                    'wimi-db': {
                        type: 'sse',
                        url: url
                    }
                }
            };
            jsonEl.textContent = JSON.stringify(config, null, 2);
        }

        if (cliEl) {
            cliEl.textContent =
                'claude mcp remove wimi-db\n' +
                'claude mcp add --scope project --transport sse wimi-db ' + url;
        }

        // Wire up copy buttons (idempotent — re-binding is fine)
        const jsonBtn = document.getElementById('mcpCopyJsonBtn');
        const cliBtn = document.getElementById('mcpCopyCliBtn');

        if (jsonBtn) {
            jsonBtn.onclick = () => this._copyToClipboard(jsonEl.textContent, jsonBtn);
        }
        if (cliBtn) {
            cliBtn.onclick = () => this._copyToClipboard(cliEl.textContent, cliBtn);
        }
    }

    _copyToClipboard(text, btn) {
        navigator.clipboard.writeText(text).then(() => {
            const original = btn.textContent;
            btn.textContent = 'Copied!';
            btn.classList.add('copied');
            setTimeout(() => {
                btn.textContent = original;
                btn.classList.remove('copied');
            }, 2000);
        }).catch(() => {
            // Fallback for environments where clipboard API isn't available
            this.showToast('Could not copy to clipboard', 'error');
        });
    }
    // =========================================================================
    // Folder Sync (#123)
    //
    // The "Enable Cloud Sync" checkbox reflects and toggles THE LINK. No
    // boolean is stored for it (settled 2026-09-21): `user_preferences.
    // cloud_sync_enabled` is user-level and so travels inside a .wimi, which
    // would have a profile arrive on a second machine claiming to sync with
    // no folder linked there. The control therefore carries no data-field and
    // never goes through saveSettings() -- this section owns it end to end.
    //
    // Nothing here ever draws a tick meaning "in sync". You cannot force a
    // sync or know when one finished, so "nothing new" and "the other device
    // has not uploaded yet" are the same observation from the filesystem.
    // Every line rendered below is something we saw, with when we saw it.
    // =========================================================================

    async initFolderSync() {
        const checkbox = document.getElementById('cloud_sync_enabled');
        if (!checkbox) return;

        this.folderSyncProviders = [];
        try {
            this.folderSyncProviders = await api.getFolderSyncProviders();
        } catch (e) {
            // Providers are static data; failing to read them is not a reason
            // to hide the feature, only to offer the generic folder.
            console.warn('folder sync: could not read providers', e);
        }

        const select = document.getElementById('folder-sync-provider');
        if (select) {
            select.innerHTML = this.folderSyncProviders
                .map(p => `<option value="${this._escapeHtml(p.id)}">${this._escapeHtml(p.name)}</option>`)
                .join('');
            select.addEventListener('change', () => this.relinkFolderSync());
        }

        checkbox.addEventListener('change', () => this.toggleFolderSync(checkbox.checked));
        this.bindClick('folder-sync-change-folder', () => this.chooseFolderSyncFolder());
        this.bindClick('folder-sync-refresh', () => this.refreshFolderSyncStatus());
        this.bindClick('folder-sync-push', () => this.pushFolderSync());
        this.bindClick('folder-sync-fetch', () => this.fetchFolderSync());
        this.bindClick('folder-sync-keep-both', () => this.resolveFolderSyncFork('keep_both'));
        this.bindClick('folder-sync-keep-local', () => this.resolveFolderSyncFork('keep_local'));
        this.bindClick('folder-sync-keep-remote', () => this.resolveFolderSyncFork('keep_remote'));
        this.bindClick('folder-sync-take-newer', () => this.takeNewerFolderSyncCopy());
        this.bindClick('folder-sync-send-first', () => this.pushFolderSync());

        await this.renderFolderSyncLink();
        this.showFolderSyncFlash();
    }

    /** A message left by a resolution that reloaded the page (see resolveFolderSyncFork). */
    showFolderSyncFlash() {
        let flash = null;
        try {
            flash = sessionStorage.getItem('wimi.folderSync.flash');
            sessionStorage.removeItem('wimi.folderSync.flash');
        } catch (e) { return; }
        if (flash) this.showToast(flash, 'success');
    }

    bindClick(id, handler) {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', handler);
    }

    /** Read the link and paint the control from it. Cheap; never touches the folder. */
    async renderFolderSyncLink() {
        const checkbox = document.getElementById('cloud_sync_enabled');
        const details = document.getElementById('folder-sync-details');
        if (!checkbox || !details) return;

        let link = {linked: false};
        try {
            link = await api.getFolderSyncLink();
        } catch (e) {
            // No master database yet, or the feature is unavailable. Treat it
            // as "not present" rather than surfacing an error the student
            // cannot act on.
            checkbox.disabled = true;
            details.hidden = true;
            return;
        }

        this.folderSyncLink = link;
        checkbox.checked = !!link.linked;
        details.hidden = !link.linked;
        if (!link.linked) return;

        const folderEl = document.getElementById('folder-sync-folder');
        if (folderEl) folderEl.textContent = link.folder;

        const select = document.getElementById('folder-sync-provider');
        if (select && link.provider_id) select.value = link.provider_id;

        const pin = document.getElementById('folder-sync-pin-hint');
        if (pin) {
            const p = pin.querySelector('.field-description');
            if (link.pin_hint) {
                // The single most useful sentence this panel says. An
                // immutable-file design is the worst case for a streaming
                // client's cache policy: our files are written once and never
                // modified, which is exactly the condition Box evicts on.
                p.innerHTML = 'Pin this folder in ' + this._escapeHtml(link.provider_name || 'your cloud client')
                    + ' so its files stay on this computer - the setting is called <strong>'
                    + this._escapeHtml(link.pin_hint) + '</strong>.';
                pin.hidden = false;
            } else {
                pin.hidden = true;
            }
        }

        this.renderFolderSyncObservations(link);
        this.renderFolderSyncPending(link.pending || null, null);
    }

    /**
     * A choice made on this computer and not yet sent (#148).
     *
     * Two things must be clear, and they are different: what has ALREADY
     * happened here (keep_remote replaced this copy; keep_both installed a
     * second profile -- neither waits for anything), and what is WAITING
     * for the send (the other computer being told). A panel that blurred
     * them would let a student think an overwrite could still be called off.
     *
     * @param {object|null} pending the link's pending choice.
     * @param {string|null} state 'ready', 'folder_moved', or null when no
     *     folder look has come back yet.
     */
    renderFolderSyncPending(pending, state, unseen) {
        const box = document.getElementById('folder-sync-pending');
        const text = document.getElementById('folder-sync-pending-text');
        const push = document.getElementById('folder-sync-push');
        if (!box || !text) return;
        if (!pending) {
            box.hidden = true;
            text.innerHTML = '';
            if (push) push.textContent = "Send this device's copy";
            return;
        }
        const when = pending.resolved_at ? ' on ' + this.formatSyncTime(pending.resolved_at) : '';
        const already = {
            keep_local: "This computer's copy was kept - nothing on this computer changed.",
            keep_remote: "This computer now holds the other computer's copy. That has "
                + 'already happened and is not undone by leaving it unsent; the '
                + 'previous copy is in the backup.',
            keep_both: 'The other copy is already on this computer as a separate '
                + 'profile. This profile is the one that stays synced.',
        }[pending.choice] || '';
        const lines = [
            `<p class="field-description"><strong>You chose which copy to keep${when}, `
            + 'but have not sent it yet.</strong> ' + already + '</p>',
        ];
        if (state === 'folder_moved') {
            const who = (unseen || []).map(u => this._escapeHtml(u.device_name || 'another computer')
                + ' (generation ' + u.generation + ')').join(', ');
            lines.push('<p class="field-description folder-sync-problem">The folder has '
                + 'changed since you chose' + (who ? ': ' + who + ' sent a copy' : '')
                + '. Nothing will be sent until you look at the copies again and choose.</p>');
        } else {
            const others = (pending.set_aside_devices || [])
                .map(d => this._escapeHtml(d || 'the other computer')).join(', ');
            lines.push('<p class="field-description">Until you send, '
                + (others || 'the other computer') + ' still sees two copies. '
                + 'Sending tells it which one you kept.</p>');
        }
        text.innerHTML = lines.join('');
        box.hidden = false;
        if (push) push.textContent = state === 'folder_moved' ? "Send this device's copy" : 'Send your choice';
    }

    /**
     * What we saw, and when. Never a claim about what is true now.
     */
    renderFolderSyncObservations(state) {
        const mount = document.getElementById('folder-sync-observations');
        if (!mount) return;

        const lines = [];
        const seen = state.last_seen_generation;
        if (seen !== undefined && seen !== null && seen > 0) {
            lines.push(`Newest copy seen in the folder: <strong>generation ${seen}</strong>`
                + (state.head_device ? ` from ${this._escapeHtml(state.head_device)}` : '')
                + (state.last_seen_at ? `, when we looked at ${this.formatSyncTime(state.last_seen_at)}` : ''));
            // #147: we read the small manifest, not the archive. Checking the
            // archive means downloading it, which on a streaming client is the
            // whole file - so say plainly that we have not, rather than let
            // "seen" be read as "verified".
            if (state.head_verified === false) {
                lines.push('That copy is still in the cloud, so its contents have not '
                    + 'been checked yet - WIMI would have had to download it to do that. '
                    + 'It is checked when you bring it over.');
            }
        } else {
            lines.push('No copy seen in this folder yet. If the other computer has '
                + 'just sent one, its cloud client may still be uploading.');
        }

        const pushed = state.last_pushed_generation;
        if (pushed !== undefined && pushed !== null && pushed > 0) {
            lines.push(`This computer last sent <strong>generation ${pushed}</strong>`
                + (state.last_pushed_at ? ` at ${this.formatSyncTime(state.last_pushed_at)}` : '')
                + '. Whether the cloud client has finished uploading it is not '
                + 'something WIMI can see.');
        }

        if (state.rejected && state.rejected.length) {
            lines.push(state.rejected
                .map(r => `Ignored generation ${r.generation}: ${this._escapeHtml(r.reason)}`)
                .join('<br>'));
        }

        // Where this computer's copy stands (#148). "superseded" is the one
        // the owner required be said out loud: another computer chose its
        // own copy over this one's.
        const rel = state.relation_detail || {};
        if (state.base_relation === 'superseded') {
            lines.push('<strong>This computer\u2019s copy was not the one kept.</strong> '
                + this._escapeHtml(rel.device_name || 'Another computer')
                + (rel.created_at ? ' chose its own copy on ' + this.formatSyncTime(rel.created_at) : ' chose its own copy')
                + '. Nothing has been removed from this computer - choose below what you want.');
        } else if (state.base_relation === 'behind') {
            lines.push('The folder has a newer copy from '
                + this._escapeHtml(rel.device_name || 'another computer')
                + (rel.generation ? ` (generation ${rel.generation})` : '')
                + ' that builds on this computer\u2019s - see below.');
        }

        const openForks = (state.forks || []).filter(f => !f.resolved_here && !f.set_aside);
        if (openForks.length) {
            lines.push('<strong>Two computers changed this profile independently.</strong> '
                + 'Compare them below and choose which to keep.');
        }

        if (state.conflict_copies && state.conflict_copies.length) {
            lines.push(`Your cloud client left ${state.conflict_copies.length} conflict `
                + 'copy/copies in this folder. They may hold work that never arrived '
                + 'under its own name.');
        }

        mount.innerHTML = lines.map(l => `<p class="field-description">${l}</p>`).join('');
    }

    formatSyncTime(iso) {
        try {
            return new Date(iso).toLocaleString();
        } catch (e) {
            return iso;
        }
    }

    /** Ticking the box links; unticking unlinks. That is all the state there is. */
    async toggleFolderSync(wanted) {
        if (!wanted) {
            try {
                await api.unlinkFolderSync();
                this.showToast('Cloud sync turned off. Nothing in the folder was changed.', 'success');
            } catch (e) {
                this.showToast('Could not turn off cloud sync: ' + e.message, 'error');
            }
            await this.renderFolderSyncLink();
            return;
        }
        const linked = await this.chooseFolderSyncFolder();
        if (!linked) {
            // Cancelled or refused: the box must not stay ticked claiming a
            // link that does not exist.
            await this.renderFolderSyncLink();
        }
    }

    async chooseFolderSyncFolder() {
        let picked;
        try {
            picked = await api.pickFolderSyncFolder();
        } catch (e) {
            this.showToast('Could not open the folder picker: ' + e.message, 'error');
            return false;
        }
        if (!picked || !picked.folder) return false;

        const select = document.getElementById('folder-sync-provider');
        const providerId = (select && select.value) || 'generic';

        // Say what is already there BEFORE linking. #129 recorded that no
        // "this profile is already linked here" check existed anywhere and
        // that linking was "a manual act of faith"; the folder segment is the
        // profile uuid now, so it need not be.
        try {
            const found = await api.discoverFolderSync(picked.folder, providerId);
            const mine = found.filter(f => (f.local_profiles || []).length);
            if (found.length && !mine.length) {
                this.showToast(
                    `That folder already holds ${found.length} other WIMI profile(s). `
                    + 'Yours will sit alongside them, not merge with them.', 'info');
            }
        } catch (e) {
            // Discovery is advisory. A folder we cannot enumerate may still be
            // linkable, and the link's own preflight is what decides.
            console.warn('folder sync: discovery failed', e);
        }

        try {
            await api.linkFolderSync(picked.folder, providerId);
            this.showToast('Cloud sync folder set.', 'success');
        } catch (e) {
            this.showToast('Could not use that folder: ' + e.message, 'error');
            await this.renderFolderSyncLink();
            return false;
        }
        await this.renderFolderSyncLink();
        await this.refreshFolderSyncStatus();
        return true;
    }

    async relinkFolderSync() {
        // Changing the client for an already-linked folder re-links in place;
        // the folder and the profile's segment are unchanged.
        if (!this.folderSyncLink || !this.folderSyncLink.linked) return;
        const select = document.getElementById('folder-sync-provider');
        try {
            await api.linkFolderSync(this.folderSyncLink.folder, select.value);
        } catch (e) {
            this.showToast('Could not change the cloud client: ' + e.message, 'error');
        }
        await this.renderFolderSyncLink();
    }

    async withFolderSyncBusy(buttonId, label, work) {
        const btn = document.getElementById(buttonId);
        const original = btn ? btn.textContent : null;
        if (btn) { btn.disabled = true; btn.textContent = label; }
        try {
            return await work();
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = original; }
        }
    }

    async refreshFolderSyncStatus() {
        try {
            const status = await this.withFolderSyncBusy(
                'folder-sync-refresh', 'Checking...', () => api.getFolderSyncStatus());
            if (!status.linked) { await this.renderFolderSyncLink(); return; }
            this.renderFolderSyncObservations(status);
            this.renderFolderSyncProblems(status.problems || []);
            this.renderFolderSyncPending(status.pending || null, status.pending_state || null,
                status.pending ? status.pending.unseen : null);
            this.renderFolderSyncCatchup(status);
            // status already told us whether there are forks; only build the
            // full report (which downloads both sides) when there is one --
            // and not when it was already chosen here and only awaits a send.
            // Asking the same question twice is how a student ends up
            // answering it differently the second time.
            const open = (status.forks || []).filter(f => !f.resolved_here);
            if (open.length) {
                await this.refreshFolderSyncFork();
            } else {
                const panel = document.getElementById('folder-sync-fork');
                if (panel) panel.hidden = true;
            }
        } catch (e) {
            this.showToast('Could not read the folder: ' + e.message, 'error');
        }
    }

    renderFolderSyncProblems(problems) {
        const mount = document.getElementById('folder-sync-problems');
        if (!mount) return;
        if (!problems.length) { mount.hidden = true; mount.innerHTML = ''; return; }
        mount.hidden = false;
        mount.innerHTML = problems
            .map(p => `<p class="field-description folder-sync-problem">${this._escapeHtml(p)}</p>`)
            .join('');
    }

    async pushFolderSync() {
        try {
            const result = await this.withFolderSyncBusy(
                'folder-sync-push', 'Sending...', () => api.pushFolderSync());
            // Deliberately not "synced". The file is written; whether the
            // cloud client has uploaded it is not observable from here, and
            // Box destroys a failed upload on logout without saying so.
            const carried = this.folderSyncLink && this.folderSyncLink.pending;
            this.showToast(
                (carried ? 'Your choice was sent. ' : '')
                + `Generation ${result.generation} written to the folder. Your cloud `
                + 'client uploads it on its own schedule.', 'success');
            await this.renderFolderSyncLink();
            await this.refreshFolderSyncStatus();
        } catch (e) {
            this.showToast('Could not send this copy: ' + e.message, 'error');
        }
    }

    /**
     * "Look for a newer copy": look at the folder and say what is there.
     *
     * Taking the copy is the catch-up block's job (#151), which appears when
     * there is one -- so this looks, rather than downloading an archive
     * nobody has asked to install yet.
     */
    async fetchFolderSync() {
        let status;
        try {
            status = await this.withFolderSyncBusy(
                'folder-sync-fetch', 'Looking...', () => api.getFolderSyncStatus());
        } catch (e) {
            this.showToast('Could not read the folder: ' + e.message, 'error');
            return;
        }
        if (!status.linked) { await this.renderFolderSyncLink(); return; }
        await this.refreshFolderSyncStatus();
        const open = (status.forks || []).filter(f => !f.resolved_here);
        if (open.length) {
            this.showToast('Two copies need choosing between - see below.', 'info');
        } else if (status.base_relation === 'behind') {
            this.showToast('A newer copy is in the folder - see below.', 'info');
        } else if (status.base_relation === 'current') {
            // "Shows", not "has": a copy the other computer has not finished
            // uploading is invisible from here.
            this.showToast(`This computer has the newest copy the folder shows `
                + `(generation ${status.head_generation}).`, 'success');
        }
    }

    /**
     * Another computer built on this one's copy (#151).
     *
     * Shown only when that is the whole story: no unresolved fork (the fork
     * panel owns that) and no unsent choice (the pending block does).
     * The owner's rule: say exactly what was checked about work on this
     * computer, and offer both ways forward when there is any.
     */
    renderFolderSyncCatchup(status) {
        const box = document.getElementById('folder-sync-catchup');
        const text = document.getElementById('folder-sync-catchup-text');
        const take = document.getElementById('folder-sync-take-newer');
        const sendFirst = document.getElementById('folder-sync-send-first');
        if (!box || !text || !take || !sendFirst) return;

        const open = (status.forks || []).filter(f => !f.resolved_here);
        const newer = status.relation_detail;
        if (status.base_relation !== 'behind' || open.length || status.pending || !newer) {
            box.hidden = true;
            this.folderSyncNewer = null;
            return;
        }
        this.folderSyncNewer = newer;

        const lines = [
            '<p class="field-description"><strong>'
            + this._escapeHtml(newer.device_name || 'Another computer') + '</strong> sent generation '
            + newer.generation
            + (newer.created_at ? ' on ' + this.formatSyncTime(newer.created_at) : '')
            + ', built on this computer\u2019s copy'
            + (newer.entries !== null && newer.entries !== undefined ? ` (${newer.entries} entries)` : '')
            + '.</p>',
        ];
        const changes = status.local_changes || {};
        const differs = changes.differs || [];
        let anyway = false;
        if (changes.checked && differs.length) {
            anyway = true;
            const list = differs.map(d => `${this._escapeHtml(d.label)}: ${this._escapeHtml(String(d.here))} `
                + `here, ${this._escapeHtml(String(d.then))} when it last synced`).join('; ');
            lines.push('<p class="field-description"><strong>This computer has changed since it last '
                + 'synced</strong> - ' + list + '. Using the newer copy replaces those changes; '
                + 'they are kept in the backup WIMI takes first. <strong>Send mine first</strong> '
                + 'keeps both, and you then choose between the two copies.</p>');
        } else if (changes.checked) {
            lines.push('<p class="field-description">No changes found on this computer since it last '
                + 'synced. WIMI compares counts and dates, so an edit to an existing entry would '
                + 'not show here - WIMI takes a backup of this computer\u2019s copy first either way.</p>');
        } else {
            anyway = true;
            lines.push('<p class="field-description">WIMI cannot tell whether this computer has changes '
                + 'the newer copy lacks' + (changes.reason ? ' (' + this._escapeHtml(changes.reason) + ')' : '')
                + '. Using the newer copy replaces this computer\u2019s; it is kept in the backup '
                + 'WIMI takes first.</p>');
        }
        text.innerHTML = lines.join('');
        take.textContent = anyway ? 'Use the newer copy anyway' : 'Use the newer copy';
        sendFirst.hidden = !anyway;
        box.hidden = false;
    }

    /** Catch up: keep_remote onto the newer copy. Needs no send; reopens the profile. */
    async takeNewerFolderSyncCopy() {
        const newer = this.folderSyncNewer;
        if (!newer || !newer.blob_name) {
            this.showToast('Look at the folder again first - WIMI no longer knows which copy is newer.', 'error');
            return;
        }
        try {
            const result = await this.withFolderSyncBusy(
                'folder-sync-take-newer', 'Working...',
                () => api.resolveFolderSyncFork('keep_remote', newer.blob_name));
            const lines = ['This computer now has the newer copy.'];
            const backup = result.safety_export && result.safety_export.path;
            if (backup) lines.push('Its previous copy is backed up at ' + backup);
            if (result.replaced_local) {
                // The profile was closed, replaced and reopened under this page.
                try {
                    sessionStorage.setItem('wimi.folderSync.flash', lines.join(' '));
                } catch (e) { /* the status block will say it anyway */ }
                window.location.reload();
                return;
            }
            this.showToast(lines.join(' '), 'success');
            await this.renderFolderSyncLink();
            await this.refreshFolderSyncStatus();
        } catch (e) {
            this.showToast('Could not take the newer copy: ' + e.message, 'error');
        }
    }

    // ---------------------------------------------------------------------
    // Fork resolution (#124)
    //
    // "The report is the feature." A dialog that says "there is a conflict,
    // choose one" without numbers is a coin flip with extra steps, so the
    // four figures per side are the point and the buttons are incidental.
    //
    // Two states that must never be rendered alike:
    //   report === null        -> no fork. Panel stays hidden.
    //   report.compared false  -> there IS a fork but a side could not be
    //                             read, so the empty "only on this side"
    //                             lists mean NOBODY LOOKED. Saying "no
    //                             differences" there is a comforting lie.
    // ---------------------------------------------------------------------

    async refreshFolderSyncFork() {
        const panel = document.getElementById('folder-sync-fork');
        if (!panel) return;
        let report = null;
        try {
            report = await api.getFolderSyncForkReport();
        } catch (e) {
            // Looking for a fork failed. That is not the same as there being
            // none, so say so rather than hiding the panel.
            this.renderFolderSyncProblems(['Could not check for conflicting copies: ' + e.message]);
            panel.hidden = true;
            return;
        }
        this.folderSyncFork = report;
        if (!report) { panel.hidden = true; return; }

        panel.hidden = false;
        this.renderForkFraming(report);
        const mount = document.getElementById('folder-sync-fork-sides');
        mount.innerHTML = report.sides.map(s => this.renderForkSide(s, report)).join('');

        const note = document.getElementById('folder-sync-fork-note');
        if (report.notes && report.notes.length) {
            note.hidden = false;
            note.innerHTML = report.notes.map(n => this._escapeHtml(n)).join('<br>');
        } else {
            note.hidden = true;
        }
    }

    /**
     * The same three choices at three moments (#124, #148), framed for each.
     * The question is always "which copy do I want"; what differs is why
     * the student is being asked.
     */
    renderForkFraming(report) {
        const title = document.getElementById('folder-sync-fork-title');
        const intro = document.getElementById('folder-sync-fork-intro');
        if (!title || !intro) return;
        if (report.set_aside) {
            title.textContent = 'Another computer kept a different copy';
            intro.innerHTML = 'Another of your computers chose to keep its own copy of '
                + 'this profile instead of this one. <strong>Nothing has been removed from '
                + 'this computer.</strong> Take the kept copy, or keep this one - WIMI saves '
                + 'a backup of this computer\u2019s copy before doing anything.';
        } else if (report.first_connect) {
            title.textContent = 'Two copies that have never synced';
            intro.innerHTML = 'This folder already holds a copy of this profile that was '
                + 'never synced with this computer\u2019s. <strong>Nothing is lost</strong> - '
                + 'WIMI saves a backup of this computer\u2019s copy first. '
                + '<strong>WIMI will not merge them</strong>; you choose which to keep.';
        } else {
            title.textContent = 'Two copies have gone their own way';
            intro.innerHTML = 'Two of your computers both changed this profile without '
                + 'seeing each other\u2019s work. <strong>Nothing is lost</strong> - both '
                + 'copies are safe in the folder, and WIMI saves a backup of this '
                + 'computer\u2019s copy before doing anything at all. '
                + '<strong>WIMI will not merge them</strong>; you choose which to keep.';
        }
    }

    renderForkSide(side, report) {
        const rows = [];
        rows.push(`<strong>${this._escapeHtml(side.device_name || 'Unknown computer')}</strong>`
            + (side.is_local ? ' <em>(this computer\u2019s copy)</em>' : ''));
        if (side.entries !== null && side.entries !== undefined) {
            rows.push(`${side.entries} entries`);
        }
        // The date range is what separates "a month of work" from "a stale
        // copy" -- two copies can have identical counts.
        if (side.encountered_first && side.encountered_last) {
            rows.push('questions sat ' + this._escapeHtml(side.encountered_first)
                + ' to ' + this._escapeHtml(side.encountered_last));
        }
        if (side.logged_last) {
            rows.push('last added to ' + this._escapeHtml(String(side.logged_last).slice(0, 16)));
        }
        if (side.created_at) {
            rows.push('sent to the folder ' + this.formatSyncTime(side.created_at));
        }

        let unique;
        if (!report.compared) {
            unique = '<em>Could not compare subjects - see the note below.</em>';
        } else if (side.subjects_only_here_count === 0) {
            unique = 'No subjects that the other copy lacks.';
        } else {
            const named = side.subjects_only_here_named.map(s => this._escapeHtml(s)).join(', ');
            const extra = side.subjects_only_here_count - side.subjects_only_here_named.length;
            unique = `<strong>Only here:</strong> ${named}`
                + (extra > 0 ? ` and ${extra} more` : '');
        }

        return '<div class="folder-sync-fork-side" data-blob="'
            + this._escapeHtml(side.blob_name || '') + '">'
            + '<p class="field-description">' + rows.join(' &middot; ') + '</p>'
            + '<p class="field-description">' + unique + '</p>'
            + '</div>';
    }

    /**
     * Which side is not this computer's, by device id rather than name.
     *
     * Names are hostnames and two machines can share one; the device id
     * cannot. Picking by name here would be the same class of bug that let
     * two devices write one file.
     */
    otherForkSide() {
        const report = this.folderSyncFork;
        if (!report || !report.sides || report.sides.length !== 2) return null;
        // The service knows which side this computer's copy is -- by what
        // it descends from, which a device id cannot say once a copy has
        // been installed from another computer (#148).
        const local = report.sides.filter(s => s.is_local);
        if (local.length === 1) return report.sides.find(s => !s.is_local);
        // No side is known to be this computer's copy. Refuse rather than
        // guess -- in particular not by device id: a computer that published
        // a side and then took the other one holds the OTHER one's rows, so
        // "the side I published" is a coin flip between the copy the student
        // chose and the one they rejected.
        return null;
    }

    async resolveFolderSyncFork(choice) {
        const other = this.otherForkSide();
        if (!other || !other.blob_name) {
            this.showToast('WIMI cannot tell which of these copies this computer holds, '
                + 'so it will not choose between them from here.', 'error');
            return;
        }
        const buttonId = {
            keep_both: 'folder-sync-keep-both',
            keep_local: 'folder-sync-keep-local',
            keep_remote: 'folder-sync-keep-remote',
        }[choice];

        try {
            const result = await this.withFolderSyncBusy(
                buttonId, 'Working...',
                () => api.resolveFolderSyncFork(choice, other.blob_name));

            // Always lead with the backup. It is the reassurance that makes
            // the choice safe to make, and the student should not have to
            // hunt for whether one was taken.
            const backup = result.safety_export && result.safety_export.path;
            const lines = (result.notes || []).slice();
            if (backup) lines.push('A backup of this computer’s copy is at ' + backup);
            this.showToast(lines.join(' '), 'success');

            if (result.replaced_local) {
                // The profile was closed, replaced and reopened underneath
                // this page. Everything on it describes a database that no
                // longer exists, so start again from the new one -- carrying
                // the message across, since it names the backup.
                try {
                    sessionStorage.setItem('wimi.folderSync.flash', lines.join(' '));
                } catch (e) { /* storage unavailable: the pending block still says it */ }
                window.location.reload();
                return;
            }
            await this.renderFolderSyncLink();
            await this.refreshFolderSyncStatus();
        } catch (e) {
            this.showToast('Could not resolve: ' + e.message, 'error');
        }
    }

}

// =========================================================================
// Instantiate
// =========================================================================

const settingsPage = new SettingsPage();
