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
            cloud_sync_enabled: false,
            realtime_update_delay_ms: 1500,
            mcp_server_enabled: false,
            mcp_server_port: 8000
        };

        // Visual fields that trigger live preview
        this.VISUAL_FIELDS = [
            'theme_name', 'primary_color_hex', 'secondary_color_hex',
            'font_size_base_px', 'ui_density', 'show_animations'
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
        await this.initAddons();
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

        // Font size
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
            // MCP API not available (older bridge) — hide panel silently
        }
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
}

// =========================================================================
// Instantiate
// =========================================================================

const settingsPage = new SettingsPage();
