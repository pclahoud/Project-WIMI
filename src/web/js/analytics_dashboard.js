/**
 * WIMI Analytics Dashboard
 * Phase 6 Stage 2 - Overview Section
 */

// Size preset definitions for resizable charts
/**
 * "+10" / "−8": the week-on-week change as a signed number (#470).
 *
 * U+2212 MINUS SIGN rather than a hyphen, so the two signs are the same
 * width and the number reads as a quantity, not a dash.
 */
function formatWeekChange(change) {
    return (change > 0 ? '+' : '\u2212') + Math.abs(change);
}

const CHART_SIZE_PRESETS = {
    subject_sunburst: {
        S: { width: 340, height: 340 },
        M: { width: 460, height: 460 },
        L: { width: 600, height: 600 }
    },
    tag_chart: {
        S: { width: 300, height: 300 },
        M: { width: 400, height: 400 },
        L: { width: 520, height: 520 }
    },
    activity_chart: {
        S: { width: 800, height: 300 },
        M: { width: 1000, height: 400 },
        L: { width: 1200, height: 500 }
    },
    activity_heatmap: {
        S: { cellSize: 12, cellGap: 3 },
        M: { cellSize: 16, cellGap: 4 },
        L: { cellSize: 22, cellGap: 5 }
    },
    cross_dimension_heatmap: {
        S: { cellSize: 50, cellPadding: 4 },
        M: { cellSize: 68, cellPadding: 5 },
        L: { cellSize: 88, cellPadding: 6 }
    }
};

// Where each chart lives on the page. One map, read by both the per-exam
// Chart Visibility ticks and the student-wide settings below.
const CHART_SELECTORS = {
    'subject_sunburst': '#subjectBreakdownCard',
    'tag_chart': '#tagBreakdownCard',
    'activity_chart': '.activity-section',
    'activity_heatmap': '.heatmap-section',
    'streak_stats': '#streakStats',
    'weekly_goal': '.goal-section',
    'difficulty_distribution': '.difficulty-section',
    'patterns_insights': '.insights-section',
    'cross_dimension_heatmap': '#crossDimensionSection',
    'study_recommendations': '#recommendationsSection',
    'interaction_effects': '#interactionEffectsContainer',
    'weight_analysis': '.weight-analysis-section',
    'source_comparison': '.source-section'
};

// Settings -> Dashboard & Analytics (#504). These were stored and read by
// nothing. Each switch hides a fixed group of charts for every exam; the
// per-exam ticks can hide a chart as well, and neither can show what the
// other hides. settings.html names the same groups to the student, so the
// two must change together.
const PREFERENCE_CHART_GROUPS = {
    show_performance_trends: ['activity_chart', 'streak_stats'],
    show_mistake_patterns: ['tag_chart', 'patterns_insights', 'difficulty_distribution'],
    show_subject_breakdown: ['subject_sunburst', 'cross_dimension_heatmap', 'weight_analysis'],
    show_time_analytics: ['activity_heatmap', 'weekly_goal']
};

// What each analytics_detail_level leaves out (#504). The overview figures
// are not a chart and always show. Summary keeps the sunburst and the
// mistake-type chart; Detailed drops the three dimension-only deep views;
// Advanced is the whole page.
const DETAIL_LEVEL_HIDES = {
    summary: Object.keys(CHART_SELECTORS).filter(k => k !== 'subject_sunburst' && k !== 'tag_chart'),
    detailed: ['cross_dimension_heatmap', 'study_recommendations', 'interaction_effects'],
    advanced: []
};

/** Chart keys the student's own settings hide, whatever the exam says. */
function chartsHiddenByPreferences(prefs) {
    const hidden = new Set();
    if (!prefs) return hidden;
    for (const [field, keys] of Object.entries(PREFERENCE_CHART_GROUPS)) {
        if (prefs[field] === false) keys.forEach(k => hidden.add(k));
    }
    (DETAIL_LEVEL_HIDES[prefs.analytics_detail_level] || []).forEach(k => hidden.add(k));
    return hidden;
}

class AnalyticsDashboard {
    constructor() {
        // True once init() has drawn every card and applied visibility: the
        // moment the tour starts, and what a scenario waits on.
        this.isReady = false;
        this.currentExamFilter = null;
        this.currentPeriod = '7d';
        this.charts = {
            subject: null,
            tag: null,
            activity: null
        };
        this.sunburstChart = null;
        this.heatmapChart = null;
        this.streakDisplay = null;
        this.goalWidget = null;
        this.weightAnalysis = null;
        this.selectedSubjectId = null;

        // Chart size presets (persisted per-exam)
        this.chartSizes = {};

        // Multi-dimensional analytics components
        this.dimensionAnalytics = null;
        this.dimensionHeatmap = null;
        this.dimensionInsights = null;
        this.currentDimensionFilter = null;

        // Cross-dimension drill-down state
        this.drilldownState = {
            levelTypeA: null,
            levelTypeB: null,
            parentNodeA: null,  // { id, name }
            parentNodeB: null,  // { id, name }
            drillPathA: [],     // Array of { id, name } for breadcrumb
            drillPathB: [],
            levelsA: [],        // Cached hierarchy levels for dimension A
            levelsB: []         // Cached hierarchy levels for dimension B
        };

        this.init();
    }

    async init() {
        console.log('Initializing Analytics Dashboard...');

        // Wait for API to be ready
        await api.ready();

        // Get exam ID from URL parameter if present
        const urlParams = new URLSearchParams(window.location.search);
        const examParam = urlParams.get('exam');
        if (examParam) {
            this.currentExamFilter = parseInt(examParam);
        }

        // Load exam contexts for filter
        await this.loadExamFilter();

        // Load per-exam analytics config (sets dimension filter + chart visibility)
        await this.loadAnalyticsConfig();

        // The student-wide Dashboard & Analytics settings (#504)
        await this.loadUserPreferences();

        // Initialize dimension analytics
        await this.initializeDimensionAnalytics();

        // Set up event listeners
        this.setupEventListeners();

        // Load all analytics data
        await this.loadAllData();

        // Apply chart visibility after data is loaded
        this.applyChartVisibility();
        this.applyPreferenceVisibility();

        // Apply saved chart sizes
        this.applyChartSizes();

        this.startAutoRefresh();

        this.isReady = true;

        // The first-run tour (#430), once every card is drawn and the
        // student's own visibility choices have hidden what they hide: a step
        // on a hidden card waits rather than spotlighting nothing. No re-start
        // on an exam change, which reloads values into the same markup, nor on
        // autoRefresh, which never replaces an anchor. The page is not gated.
        // Behind a typeof check and a try, so a broken tour cannot break it.
        try {
            if (typeof WimiTour !== 'undefined') WimiTour.start('analytics');
        } catch (e) {
            console.error('Tour failed to start:', e);
        }
    }

    async loadUserPreferences() {
        try {
            this.userPreferences = (await api.getUserPreferences()) || {};
        } catch (e) {
            console.warn('Could not load user preferences, showing every chart:', e);
            this.userPreferences = {};
        }
    }

    /**
     * Hide what the student's settings hide (#504). A class with
     * !important rather than style.display, because the per-exam pass and
     * several loaders write style.display themselves and must not be able to
     * show a chart these settings switched off; nor can this pass show one
     * they hid.
     */
    applyPreferenceVisibility() {
        const hidden = chartsHiddenByPreferences(this.userPreferences);
        for (const [key, selector] of Object.entries(CHART_SELECTORS)) {
            const el = document.querySelector(selector);
            if (el) el.classList.toggle('pref-hidden', hidden.has(key));
        }
    }

    /**
     * Reload the figures every dashboard_auto_refresh_seconds (#504), so an
     * entry logged in another window shows without leaving the page. Skipped
     * while the window is hidden, and never overlapping itself.
     */
    startAutoRefresh() {
        const seconds = Number(this.userPreferences && this.userPreferences.dashboard_auto_refresh_seconds);
        this.autoRefreshMs = (seconds >= 30 ? seconds : 300) * 1000;
        if (this._autoRefreshTimer) clearInterval(this._autoRefreshTimer);
        this._autoRefreshTimer = setInterval(() => this.autoRefresh(), this.autoRefreshMs);
    }

    async autoRefresh() {
        if (document.hidden || this._refreshing) return;
        this._refreshing = true;
        try {
            await this.loadAllData();
            this.applyChartVisibility();
            this.applyPreferenceVisibility();
        } finally {
            this._refreshing = false;
        }
    }

    /**
     * Initialize dimension analytics if exam uses dimensions
     */
    async initializeDimensionAnalytics() {
        if (!this.currentExamFilter) return;

        try {
            this.dimensionAnalytics = new DimensionAnalytics(
                this.currentExamFilter,
                (dimensionId) => this.onDimensionChange(dimensionId)
            );

            const hasDimensions = await this.dimensionAnalytics.loadDimensions();

            if (hasDimensions) {
                // Show multi-dimensional sections
                this.showMultiDimensionalSections(true);

                // Initialize dimension heatmap
                const dimHeatmapSize = CHART_SIZE_PRESETS.cross_dimension_heatmap[this.chartSizes.cross_dimension_heatmap || 'M'];
                this.dimensionHeatmap = new DimensionHeatmap('dimensionHeatmap', {
                    cellSize: dimHeatmapSize.cellSize,
                    cellPadding: dimHeatmapSize.cellPadding,
                    onCellClick: (data) => this.handleHeatmapCellClick(data),
                    onCellHover: (data, isHovering) => this.handleHeatmapCellHover(data, isHovering)
                });

                // Initialize dimension insights
                this.dimensionInsights = new DimensionInsights('dimensionInsights', {
                    onCombinationClick: (rec) => this.handleRecommendationClick(rec)
                });

                // Populate dimension pickers for heatmap
                this.populateHeatmapDimensionPickers();
            } else {
                this.showMultiDimensionalSections(false);
            }
        } catch (error) {
            console.error('Error initializing dimension analytics:', error);
            this.showMultiDimensionalSections(false);
        }
    }

    /**
     * Load per-exam analytics config (dimension filter + chart visibility)
     */
    async loadAnalyticsConfig() {
        this.analyticsConfig = null;
        if (!this.currentExamFilter) return;

        try {
            this.analyticsConfig = await api.getExamAnalyticsConfig(this.currentExamFilter);
            if (this.analyticsConfig) {
                this.currentDimensionFilter = this.analyticsConfig.default_dimension_id || null;
                this.chartSizes = this.analyticsConfig.chart_sizes || {};
            }
        } catch (e) {
            console.warn('Could not load analytics config:', e);
        }
    }

    /**
     * Apply chart visibility from analytics config
     */
    applyChartVisibility() {
        if (!this.analyticsConfig || !this.analyticsConfig.chart_visibility) return;

        const vis = this.analyticsConfig.chart_visibility;

        // These three need two dimensions. The dimension gate
        // (showMultiDimensionalSections) is a capability test and this config
        // is a preference: a preference cannot switch on a section the exam
        // cannot support, so "visible" here must never undo the gate's hide.
        // This runs AFTER the gate in init() and on an exam switch, and its
        // `display = ''` used to clear both the gate's hide and the markup's
        // own display:none on a single-dimension exam (#473).
        const dimensionOnly = new Set([
            'cross_dimension_heatmap', 'study_recommendations', 'interaction_effects'
        ]);

        // One shared CHART_SELECTORS serves this per-exam pass, the student's
        // master switches in applyPreferenceVisibility and the detail-level
        // tiers (#504). Two maps would drift, and a chart missing from one of
        // them is invisible to exactly one of the three.
        //
        // The two passes COMPOSE rather than race, and the mechanism is what
        // makes that true: this one writes style.display, the preference pass
        // toggles a `pref-hidden` class carrying !important. So neither can
        // reveal what the other hid, and a chart shows only if neither hid it.
        // Keep them on different mechanisms.
        for (const [key, selector] of Object.entries(CHART_SELECTORS)) {
            const el = document.querySelector(selector);
            if (!el) continue;
            if (dimensionOnly.has(key) && this.multiDimensionalSectionsShown !== true) {
                el.style.display = 'none';
            } else if (vis[key] === false) {
                el.style.display = 'none';
            } else {
                // Restore visibility (clear any previous override)
                el.style.display = '';
            }
        }
    }

    /**
     * Apply saved chart sizes and update button states
     */
    applyChartSizes() {
        // Update button active states and apply sizes
        document.querySelectorAll('.size-preset-group').forEach(group => {
            const chartKey = group.dataset.chart;
            const savedSize = this.chartSizes[chartKey] || 'M';
            // Update active button
            group.querySelectorAll('.size-preset-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.size === savedSize);
            });
            // Apply the size
            if (savedSize !== 'M') {
                this.applyChartSize(chartKey, savedSize);
            }
        });
    }

    /**
     * Apply a size preset to a specific chart
     */
    applyChartSize(chartKey, size) {
        const preset = CHART_SIZE_PRESETS[chartKey]?.[size];
        if (!preset) return;

        // Update in-memory size immediately so re-render calls read the correct value
        this.chartSizes[chartKey] = size;

        switch (chartKey) {
            case 'subject_sunburst': {
                const container = document.getElementById('subjectSunburstContainer');
                if (container) {
                    container.style.minHeight = preset.height + 'px';
                }
                if (this.sunburstChart) {
                    this.sunburstChart.resize(preset.width, preset.height);
                }
                break;
            }
            case 'tag_chart': {
                const canvas = document.getElementById('tagChart');
                if (canvas) {
                    canvas.width = preset.width;
                    canvas.height = preset.height;
                    const container = canvas.closest('.chart-container');
                    if (container) {
                        container.style.width = preset.width + 'px';
                        container.style.height = preset.height + 'px';
                    }
                    // Re-render if we have data
                    this.loadTagChart();
                }
                break;
            }
            case 'activity_chart': {
                const canvas = document.getElementById('activityChart');
                if (canvas) {
                    canvas.width = preset.width;
                    canvas.height = preset.height;
                    this.loadActivityChart();
                }
                break;
            }
            case 'activity_heatmap': {
                // Recreate heatmap with new cell size
                this.heatmapChart = new ActivityHeatmap('activityHeatmap', {
                    weeks: 16,
                    cellSize: preset.cellSize,
                    cellGap: preset.cellGap,
                    onCellClick: (day) => this.handleHeatmapCellClick(day),
                    onCellHover: (day, isHovering) => this.handleHeatmapCellHover(day, isHovering)
                });
                this.loadActivityHeatmap();
                break;
            }
            case 'cross_dimension_heatmap': {
                if (this.dimensionHeatmap) {
                    this.dimensionHeatmap.options.cellSize = preset.cellSize;
                    this.dimensionHeatmap.options.cellPadding = preset.cellPadding;
                    this.loadCrossDimensionHeatmap();
                }
                break;
            }
        }
    }

    /**
     * Save chart size to backend
     */
    async saveChartSize(chartKey, size) {
        this.chartSizes[chartKey] = size;
        if (!this.currentExamFilter) return;
        try {
            await api.updateExamAnalyticsConfig({
                examContextId: this.currentExamFilter,
                chartSizes: this.chartSizes
            });
        } catch (e) {
            console.warn('Could not save chart size:', e);
        }
    }

    /**
     * Show or hide multi-dimensional sections
     */
    showMultiDimensionalSections(show) {
        // Read by applyChartVisibility, which runs after this (#473).
        this.multiDimensionalSectionsShown = show;
        const sections = [
            'crossDimensionSection',
            'recommendationsSection',
            'interactionEffectsContainer'
        ];

        sections.forEach(id => {
            const section = document.getElementById(id);
            if (section) {
                section.style.display = show ? 'block' : 'none';
            }
        });
    }

    /**
     * Handle dimension filter change
     */
    onDimensionChange(dimensionId) {
        this.currentDimensionFilter = dimensionId;
        this.loadSubjectChart();
        this.loadTagChart();
    }

    /**
     * Populate dimension pickers for heatmap
     */
    populateHeatmapDimensionPickers() {
        if (!this.dimensionAnalytics) return;

        const dimensions = this.dimensionAnalytics.getDimensions();
        const dimASelect = document.getElementById('heatmapDimA');
        const dimBSelect = document.getElementById('heatmapDimB');

        if (!dimASelect || !dimBSelect || dimensions.length < 2) return;

        [dimASelect, dimBSelect].forEach(select => {
            select.innerHTML = '';
            dimensions.forEach(dim => {
                const option = document.createElement('option');
                option.value = dim.id;
                option.textContent = dim.name;
                select.appendChild(option);
            });
        });

        // Set default selections (first two dimensions)
        dimASelect.value = dimensions[0].id;
        dimBSelect.value = dimensions[1].id;

        // Add change listeners for dimension selectors
        // The heatmap waits on heatmapLevelsReady (#799): a dimension change
        // nulls the level, and a query with no level draws every subject.
        dimASelect.addEventListener('change', () => {
            this.resetDrilldown('A');
            this.heatmapLevelsReady = this.loadLevelOptionsForDimension('A', parseInt(dimASelect.value));
            this.loadCrossDimensionHeatmap();
        });
        dimBSelect.addEventListener('change', () => {
            this.resetDrilldown('B');
            this.heatmapLevelsReady = this.loadLevelOptionsForDimension('B', parseInt(dimBSelect.value));
            this.loadCrossDimensionHeatmap();
        });

        // Level selector listeners
        const levelASelect = document.getElementById('heatmapLevelA');
        const levelBSelect = document.getElementById('heatmapLevelB');

        if (levelASelect) {
            levelASelect.addEventListener('change', () => {
                this.drilldownState.levelTypeA = levelASelect.value || null;
                this.drilldownState.parentNodeA = null;
                this.drilldownState.drillPathA = [];
                this.updateScopeDropdown('A');
                this.loadCrossDimensionHeatmap();
                this.updateBreadcrumb();
            });
        }
        if (levelBSelect) {
            levelBSelect.addEventListener('change', () => {
                this.drilldownState.levelTypeB = levelBSelect.value || null;
                this.drilldownState.parentNodeB = null;
                this.drilldownState.drillPathB = [];
                this.updateScopeDropdown('B');
                this.loadCrossDimensionHeatmap();
                this.updateBreadcrumb();
            });
        }

        // Reset drilldown button
        const resetBtn = document.getElementById('resetDrilldownBtn');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                this.resetDrilldown();
                this.loadCrossDimensionHeatmap();
            });
        }

        // Export CSV button
        const exportBtn = document.getElementById('exportHeatmapCSV');
        if (exportBtn) {
            exportBtn.addEventListener('click', () => {
                if (this.dimensionHeatmap) {
                    this.dimensionHeatmap.downloadCSV();
                }
            });
        }

        // Load initial level options. Every heatmap load awaits this first
        // (#799): the page's first load used to run before the levels
        // arrived, query with no level -- every subject at every depth -- and
        // nothing redrew it once they did. On a full published blueprint that
        // was hundreds of thousands of SVG shapes under top-level pickers.
        this.heatmapLevelsReady = Promise.all([
            this.loadLevelOptionsForDimension('A', parseInt(dimASelect.value)),
            this.loadLevelOptionsForDimension('B', parseInt(dimBSelect.value)),
        ]);
    }

    /**
     * Load hierarchy level options for a dimension
     */
    async loadLevelOptionsForDimension(which, dimensionId) {
        const selectId = which === 'A' ? 'heatmapLevelA' : 'heatmapLevelB';
        const select = document.getElementById(selectId);
        if (!select) return;

        try {
            const data = await api.getHierarchyLevelsForDimension({
                examContextId: this.currentExamFilter,
                dimensionId: dimensionId
            });

            select.innerHTML = '';

            if (data && data.levels && data.levels.length > 0) {
                // Cache levels for scope dropdown logic
                if (which === 'A') {
                    this.drilldownState.levelsA = data.levels;
                } else {
                    this.drilldownState.levelsB = data.levels;
                }

                data.levels.forEach(level => {
                    const option = document.createElement('option');
                    option.value = level.level_type;
                    option.textContent = `${level.level_type} (${level.count})`;
                    select.appendChild(option);
                });
                select.disabled = false;

                // Restore selected level or default to highest (first) level
                const currentLevel = which === 'A' ? this.drilldownState.levelTypeA : this.drilldownState.levelTypeB;
                if (currentLevel) {
                    select.value = currentLevel;
                } else {
                    select.value = data.levels[0].level_type;
                    if (which === 'A') {
                        this.drilldownState.levelTypeA = data.levels[0].level_type;
                    } else {
                        this.drilldownState.levelTypeB = data.levels[0].level_type;
                    }
                }
            } else {
                // No hierarchy levels - disable selector
                if (which === 'A') {
                    this.drilldownState.levelsA = [];
                } else {
                    this.drilldownState.levelsB = [];
                }
                select.disabled = true;
            }

            // Update scope dropdown based on current level selection
            this.updateScopeDropdown(which);
        } catch (error) {
            console.error(`Error loading level options for dimension ${which}:`, error);
            select.innerHTML = '<option value="">All Levels</option>';
            select.disabled = true;
            if (which === 'A') {
                this.drilldownState.levelsA = [];
            } else {
                this.drilldownState.levelsB = [];
            }
            this.updateScopeDropdown(which);
        }
    }

    /**
     * Update scope dropdown for a dimension based on current level selection.
     * Generates cascading dropdowns — one per ancestor level.
     */
    async updateScopeDropdown(which) {
        const container = document.getElementById(`scopeContainer${which}`);
        if (!container) return;
        container.innerHTML = '';

        const currentLevel = this.drilldownState[`levelType${which}`];
        const levels = this.drilldownState[`levels${which}`];

        if (!currentLevel || levels.length === 0) {
            container.style.display = 'none';
            return;
        }

        const selectedIdx = levels.findIndex(l => l.level_type === currentLevel);
        if (selectedIdx <= 0) {
            container.style.display = 'none';
            return;
        }

        container.style.display = 'flex';

        // Build one dropdown for each ancestor level (depth 0 .. selectedIdx-1)
        for (let depth = 0; depth < selectedIdx; depth++) {
            // Add separator before non-first dropdowns
            if (depth > 0) {
                const sep = document.createElement('span');
                sep.className = 'scope-separator';
                sep.textContent = '\u203A';
                container.appendChild(sep);
            }

            const levelInfo = levels[depth];

            const label = document.createElement('label');
            label.className = 'scope-picker-label';

            const labelText = document.createTextNode(`${levelInfo.level_type}: `);
            label.appendChild(labelText);

            const select = document.createElement('select');
            select.className = 'scope-picker';
            select.dataset.depth = depth;
            select.dataset.which = which;
            select.setAttribute('data-testid', `analytics-heatmap-scope-${which.toLowerCase()}-depth-${depth}`);
            select.setAttribute('aria-label', `Dimension ${which} scope at depth ${depth}`);
            label.appendChild(select);
            container.appendChild(label);

            // Populate this dropdown
            await this.populateScopeAtDepth(which, depth);

            // Add change handler
            select.addEventListener('change', () => this.handleScopeChange(which, depth));
        }
    }

    /**
     * Populate a scope dropdown at a specific depth.
     * Uses the parent scope's selection to filter nodes.
     */
    async populateScopeAtDepth(which, depth) {
        const container = document.getElementById(`scopeContainer${which}`);
        const selects = container.querySelectorAll('select.scope-picker');
        const select = selects[depth];
        if (!select) return;

        const dimSelect = document.getElementById(which === 'A' ? 'heatmapDimA' : 'heatmapDimB');
        const dimensionId = parseInt(dimSelect.value);
        const levels = this.drilldownState[`levels${which}`];

        // Determine parent filter: if depth > 0, use parent scope's selected value
        let parentNodeId = null;
        if (depth > 0) {
            const parentSelect = selects[depth - 1];
            if (parentSelect.value) {
                parentNodeId = JSON.parse(parentSelect.value).id;
            }
        }

        const levelType = levels[depth].level_type;

        try {
            const nodes = await api.getDimensionNodes({
                examContextId: this.currentExamFilter,
                dimensionId, levelType, parentNodeId
            });

            select.innerHTML = '<option value="">(All)</option>';
            if (nodes && nodes.length > 0) {
                nodes.forEach(node => {
                    const option = document.createElement('option');
                    option.value = JSON.stringify({ id: node.id, name: node.name });
                    option.textContent = node.name;
                    select.appendChild(option);
                });
            }
            select.disabled = false;
        } catch (error) {
            console.error(`Error loading scope depth ${depth} for ${which}:`, error);
            select.innerHTML = '<option value="">(All)</option>';
            select.disabled = true;
        }
    }

    /**
     * Handle change in a cascading scope dropdown.
     * Repopulates deeper dropdowns and updates parentNode state.
     */
    async handleScopeChange(which, depth) {
        const container = document.getElementById(`scopeContainer${which}`);
        const selects = container.querySelectorAll('select.scope-picker');

        // Repopulate all deeper dropdowns (they depend on this selection)
        for (let d = depth + 1; d < selects.length; d++) {
            await this.populateScopeAtDepth(which, d);
        }

        // Determine parentNode from deepest non-"All" selection
        let parentNode = null;
        for (let d = selects.length - 1; d >= 0; d--) {
            if (selects[d].value) {
                parentNode = JSON.parse(selects[d].value);
                break;
            }
        }

        this.drilldownState[`parentNode${which}`] = parentNode;
        this.drilldownState[`drillPath${which}`] = [];
        this.loadCrossDimensionHeatmap();
        this.updateBreadcrumb();
    }

    /**
     * Reset drill-down state
     */
    resetDrilldown(which = null) {
        if (!which || which === 'A') {
            this.drilldownState.parentNodeA = null;
            this.drilldownState.drillPathA = [];
            const levelASelect = document.getElementById('heatmapLevelA');
            if (levelASelect && levelASelect.options.length > 0) {
                levelASelect.selectedIndex = 0;
                this.drilldownState.levelTypeA = levelASelect.value || null;
            } else {
                this.drilldownState.levelTypeA = null;
            }
            const scopeContainerA = document.getElementById('scopeContainerA');
            if (scopeContainerA) { scopeContainerA.innerHTML = ''; scopeContainerA.style.display = 'none'; }
        }
        if (!which || which === 'B') {
            this.drilldownState.parentNodeB = null;
            this.drilldownState.drillPathB = [];
            const levelBSelect = document.getElementById('heatmapLevelB');
            if (levelBSelect && levelBSelect.options.length > 0) {
                levelBSelect.selectedIndex = 0;
                this.drilldownState.levelTypeB = levelBSelect.value || null;
            } else {
                this.drilldownState.levelTypeB = null;
            }
            const scopeContainerB = document.getElementById('scopeContainerB');
            if (scopeContainerB) { scopeContainerB.innerHTML = ''; scopeContainerB.style.display = 'none'; }
        }
        this.updateBreadcrumb();
    }

    /**
     * Update breadcrumb navigation display
     */
    updateBreadcrumb() {
        const breadcrumb = document.getElementById('heatmapBreadcrumb');
        const pathA = document.getElementById('breadcrumbPathA');
        const pathB = document.getElementById('breadcrumbPathB');

        if (!breadcrumb || !pathA || !pathB) return;

        const hasPathA = this.drilldownState.drillPathA.length > 0;
        const hasPathB = this.drilldownState.drillPathB.length > 0;

        if (!hasPathA && !hasPathB) {
            breadcrumb.style.display = 'none';
            return;
        }

        breadcrumb.style.display = 'flex';

        // Build each path from text nodes: a step's name is a subject the
        // student typed or imported, so it is never parsed as markup (#548).
        const buildPath = (container, path, dim) => {
            const key = dim.toLowerCase();
            if (path.length === 0) {
                container.innerHTML = `<span class="breadcrumb-empty" data-testid="analytics-heatmap-breadcrumb-${key}-empty">All</span>`;
                return;
            }
            const parts = [];
            path.forEach((node, idx) => {
                if (idx > 0) parts.push(document.createTextNode(' > '));
                const link = document.createElement('a');
                link.className = 'breadcrumb-link';
                link.dataset.dimension = dim;
                link.dataset.index = String(idx);
                link.setAttribute('data-testid', `analytics-heatmap-breadcrumb-${key}-step-${idx}`);
                link.textContent = node.name;
                parts.push(link);
            });
            container.replaceChildren(...parts);
        };
        buildPath(pathA, this.drilldownState.drillPathA, 'A');
        buildPath(pathB, this.drilldownState.drillPathB, 'B');

        // Add click handlers for breadcrumb links
        breadcrumb.querySelectorAll('.breadcrumb-link').forEach(link => {
            link.addEventListener('click', (e) => {
                const dim = e.target.dataset.dimension;
                const idx = parseInt(e.target.dataset.index);
                this.navigateToBreadcrumb(dim, idx);
            });
        });
    }

    /**
     * Navigate to a specific breadcrumb level
     */
    async navigateToBreadcrumb(dimension, index) {
        const path = dimension === 'A' ? this.drilldownState.drillPathA : this.drilldownState.drillPathB;

        if (index < path.length - 1) {
            // Go back to this level
            const newPath = path.slice(0, index + 1);
            const parentNode = newPath[newPath.length - 1];

            if (dimension === 'A') {
                this.drilldownState.drillPathA = newPath;
                this.drilldownState.parentNodeA = parentNode;
            } else {
                this.drilldownState.drillPathB = newPath;
                this.drilldownState.parentNodeB = parentNode;
            }

            this.loadCrossDimensionHeatmap();
            this.updateBreadcrumb();
            await this.updateScopeDropdown(dimension);
            await this.syncScopeToPath(dimension);
        }
    }

    /**
     * Handle drill-down into a row or column header.
     * Saves previous state and rolls back with a toast if the drilldown yields no data.
     */
    async handleHeatmapDrilldown(nodeId, nodeName, dimension) {
        const levelSelect = document.getElementById(dimension === 'A' ? 'heatmapLevelA' : 'heatmapLevelB');

        // Save previous state for rollback
        const prevLevelType = dimension === 'A' ? this.drilldownState.levelTypeA : this.drilldownState.levelTypeB;
        const prevParentNode = dimension === 'A' ? this.drilldownState.parentNodeA : this.drilldownState.parentNodeB;
        const prevPath = [...(dimension === 'A' ? this.drilldownState.drillPathA : this.drilldownState.drillPathB)];
        const prevSelectedIndex = levelSelect ? levelSelect.selectedIndex : 0;

        // Apply drilldown
        const path = dimension === 'A' ? this.drilldownState.drillPathA : this.drilldownState.drillPathB;
        path.push({ id: nodeId, name: nodeName });

        if (dimension === 'A') {
            this.drilldownState.drillPathA = path;
            this.drilldownState.parentNodeA = { id: nodeId, name: nodeName };
        } else {
            this.drilldownState.drillPathB = path;
            this.drilldownState.parentNodeB = { id: nodeId, name: nodeName };
        }

        // Move to next level in the selector if available
        if (levelSelect && levelSelect.selectedIndex < levelSelect.options.length - 1) {
            levelSelect.selectedIndex++;
            if (dimension === 'A') {
                this.drilldownState.levelTypeA = levelSelect.value || null;
            } else {
                this.drilldownState.levelTypeB = levelSelect.value || null;
            }
        }

        // Load heatmap and check if data was returned. null means a newer
        // load superseded this one (#799), which is not "no data".
        const hasData = await this.loadCrossDimensionHeatmap();

        if (hasData === false) {
            // Rollback drilldown state
            if (dimension === 'A') {
                this.drilldownState.drillPathA = prevPath;
                this.drilldownState.parentNodeA = prevParentNode;
                this.drilldownState.levelTypeA = prevLevelType;
            } else {
                this.drilldownState.drillPathB = prevPath;
                this.drilldownState.parentNodeB = prevParentNode;
                this.drilldownState.levelTypeB = prevLevelType;
            }
            if (levelSelect) levelSelect.selectedIndex = prevSelectedIndex;

            // Reload previous state
            await this.loadCrossDimensionHeatmap();
            this.updateBreadcrumb();
            await this.updateScopeDropdown(dimension);
            await this.syncScopeToPath(dimension);

            Toast.info(`"${nodeName}" has no child subjects to drill into.`, 3000);
            return;
        }

        this.updateBreadcrumb();

        // Sync scope dropdown to reflect the full drill-down path
        await this.updateScopeDropdown(dimension);
        await this.syncScopeToPath(dimension);
    }

    /**
     * Sync scope dropdowns to match the current drill path.
     * Walks each entry in drillPath, selects the matching node,
     * and repopulates child scopes so filtering cascades correctly.
     */
    async syncScopeToPath(dimension) {
        const drillPath = this.drilldownState[`drillPath${dimension}`];
        if (!drillPath || drillPath.length === 0) return;

        const scopeContainer = document.getElementById(`scopeContainer${dimension}`);
        if (!scopeContainer) return;

        const selects = scopeContainer.querySelectorAll('select.scope-picker');
        if (selects.length === 0) return;

        // Walk through each depth, selecting the matching drillPath node
        for (let depth = 0; depth < selects.length && depth < drillPath.length; depth++) {
            const node = drillPath[depth];
            const select = selects[depth];

            // Find and select the matching option
            const match = Array.from(select.options).find(opt => {
                if (!opt.value) return false;
                try { return JSON.parse(opt.value).id === node.id; }
                catch { return false; }
            });

            if (match) {
                select.value = match.value;
                // Repopulate deeper scopes based on this selection
                if (depth + 1 < selects.length) {
                    await this.populateScopeAtDepth(dimension, depth + 1);
                }
            }
        }
    }

    /**
     * Load exam contexts for the filter dropdown
     */
    async loadExamFilter() {
        try {
            // `false` = include suspended exams, the same argument landing.js
            // passes (#310). This call used to take the default, `true`, and
            // the consequence was silent by construction: a suspended exam is
            // reachable here in one click -- renderExamCard puts an "Analytics"
            // button on EVERY card, since its isSuspended branch swaps only the
            // utility row -- and assigning an id that is not among the options
            // to a <select> raises nothing. It leaves selectedIndex = -1 and
            // value = '', i.e. an empty box, while `currentExamFilter` kept the
            // id so every chart below went on loading that exam's data. The
            // page was showing an exam it could not name.
            //
            // Note the asymmetry worth keeping: an `exam=` id that is not an
            // exam AT ALL was never silent -- six bridge calls fail and log
            // "Exam context N not found". The silence needed the exam to
            // exist and merely be excluded from the list, which is why this
            // sat unexplained.
            const exams = await api.getAllExamContexts(false);

            if (exams && exams.length > 0) {
                const select = document.getElementById('examFilter');
                select.innerHTML = ''; // Clear any existing options

                exams.forEach(exam => {
                    const option = document.createElement('option');
                    option.value = exam.id;
                    // Say so, rather than listing a suspended exam
                    // indistinguishably from an active one: the dashboard card
                    // this filter can now be reached from carries the same
                    // "Suspended" badge, and the whole point of the fix is that
                    // the filter tells the truth about what is on screen.
                    option.textContent = exam.is_active
                        ? exam.exam_name
                        : `${exam.exam_name} (suspended)`;
                    select.appendChild(option);
                });

                // Set the selected exam if provided via URL, otherwise default to first exam
                if (this.currentExamFilter) {
                    select.value = this.currentExamFilter;
                } else {
                    // Default to first exam
                    this.currentExamFilter = exams[0].id;
                    select.value = this.currentExamFilter;
                }
            } else {
                // No exams available - show empty state
                const select = document.getElementById('examFilter');
                select.innerHTML = '<option value="" disabled selected>No exams available</option>';
            }
        } catch (error) {
            console.error('Error loading exam filter:', error);
        }
    }

    /**
     * Set up event listeners
     */
    setupEventListeners() {
        // Exam filter change
        document.getElementById('examFilter').addEventListener('change', async (e) => {
            this.currentExamFilter = e.target.value ? parseInt(e.target.value) : null;
            this.currentDimensionFilter = null;

            // Reload analytics config for new exam
            await this.loadAnalyticsConfig();

            // Reinitialize dimension analytics for new exam
            await this.initializeDimensionAnalytics();

            await this.loadAllData();
            this.applyChartVisibility();
            this.applyPreferenceVisibility();
            this.applyChartSizes();
        });

        // Size preset buttons
        document.querySelectorAll('.size-preset-group').forEach(group => {
            group.addEventListener('click', (e) => {
                const btn = e.target.closest('.size-preset-btn');
                if (!btn) return;
                const chartKey = group.dataset.chart;
                const size = btn.dataset.size;
                // Update active state
                group.querySelectorAll('.size-preset-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                // Apply and save
                this.applyChartSize(chartKey, size);
                this.saveChartSize(chartKey, size);
            });
        });

        // Period selector buttons
        document.querySelectorAll('.period-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // Update active state
                document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');

                // Update period and reload
                this.currentPeriod = e.target.dataset.period;
                this.loadActivityChart();
            });
        });
    }

    /**
     * Load all analytics data
     */
    async loadAllData() {
        console.log('Loading analytics data...');

        const promises = [
            this.loadOverviewStats(),
            this.loadSubjectChart(),
            this.loadTagChart(),
            this.loadActivityChart(),
            this.loadActivityHeatmap(),
            this.loadGoalWidget(),
            this.loadDifficultyDistribution(),
            this.loadInsights(),
            this.loadWeightAnalysis(),
            this.loadSourceComparison()
        ];

        // Add multi-dimensional analytics if available
        if (this.dimensionAnalytics && this.dimensionAnalytics.examUsesDimensions()) {
            // Study Recommendations is loaded by the heatmap, with the
            // heatmap's scope, every time it draws (#824).
            promises.push(
                this.loadCrossDimensionHeatmap(),
                this.loadInteractionEffects()
            );
        }

        await Promise.all(promises);
    }

    /**
     * Load overview statistics
     */
    async loadOverviewStats() {
        try {
            const data = await api.getAnalyticsOverview(this.currentExamFilter);

            console.log('Analytics overview response:', data);

            if (data) {

                // Total entries
                document.getElementById('totalEntries').textContent = data.total_entries || 0;

                // This week with change
                const weekValue = document.querySelector('#thisWeek .value');
                const weekChange = document.getElementById('weekChange');

                weekValue.textContent = data.this_week || 0;

                // A neutral, signed number: no colour and no arrow (#470,
                // owner's decision 2026-10-07). "This Week" counts LOGGED
                // ENTRIES -- the activity the Weekly Goal and the streak
                // reward -- while Patterns & Insights reads more mistakes as a
                // concern, so a coloured direction contradicted one or the
                // other whichever way it pointed. The minus sign is shown: it
                // used to be dropped, leaving "8" beside a down arrow.
                if (data.week_change !== 0) {
                    weekChange.textContent = formatWeekChange(data.week_change) + ' vs last week';
                    weekChange.className = 'change';
                } else {
                    weekChange.textContent = '';
                }

                // Sessions
                document.getElementById('sessions').textContent = data.total_sessions || 0;
                document.getElementById('sessionsCompleted').textContent =
                    `${data.completed_sessions || 0} completed`;

                // Average difficulty
                const diffValue = document.querySelector('#avgDifficulty .value');
                diffValue.textContent = data.avg_difficulty?.toFixed(1) || '0.0';
            }
        } catch (error) {
            console.error('Error loading overview stats:', error);
        }
    }

    /**
     * Load and render subject sunburst chart
     */
    async loadSubjectChart() {
        try {
            // Only load sunburst if an exam is selected
            if (this.currentExamFilter) {
                let hierarchyData;

                // Check if dimension filter is active
                if (this.currentDimensionFilter && this.dimensionAnalytics?.examUsesDimensions()) {
                    // Load dimension-filtered hierarchy. This payload
                    // carries no `distinct_entries`, so the centre keeps
                    // showing the sum of what it draws: a slice of one
                    // dimension is not the population the "Total Entries"
                    // card counts, and pinning the two together (issue #6)
                    // would state an equality that isn't true here.
                    hierarchyData = await api.getSubjectHierarchyWithMistakesByDimension({
                        examContextId: this.currentExamFilter,
                        dimensionId: this.currentDimensionFilter
                    });
                } else {
                    // Load standard hierarchy
                    hierarchyData = await api.getSubjectHierarchyWithMistakes({
                        examContextId: this.currentExamFilter
                    });
                }

                console.log('Subject hierarchy response:', hierarchyData);

                if (hierarchyData && hierarchyData.children && hierarchyData.children.length > 0) {
                    // Initialize or update sunburst chart
                    if (!this.sunburstChart) {
                        const sunburstSize = CHART_SIZE_PRESETS.subject_sunburst[this.chartSizes.subject_sunburst || 'M'];
                        this.sunburstChart = new SunburstChart('subjectSunburst', {
                            width: sunburstSize.width,
                            height: sunburstSize.height,
                            innerRadiusRatio: 0.35,
                            centerLabelId: 'totalEntriesCenter',
                            centerTextId: 'centerSubjectName',
                            breadcrumbId: 'sunburstBreadcrumb',
                            onSegmentClick: (data) => this.handleSunburstClick(data),
                            onSegmentHover: (data, isHovering) => this.handleSunburstHover(data, isHovering)
                        });
                    }

                    this.sunburstChart.render(hierarchyData);

                    // Extract top-level subjects from hierarchy for legend
                    // Only show root-level children (not nested subjects)
                    const topLevelSubjects = hierarchyData.children
                        .map(child => ({
                            subject_id: child.id,
                            subject_name: child.name,
                            mistake_count: child.value  // Total including all descendants
                        }))
                        .sort((a, b) => b.mistake_count - a.mistake_count)
                        .slice(0, 5);

                    if (topLevelSubjects.length > 0) {
                        this.subjectData = topLevelSubjects;
                        this.renderLegend('subjectLegend', topLevelSubjects, 'subject_name', 'mistake_count');
                        
                        // Set default deep dive link to top subject
                        this.updateDeepDiveLink(topLevelSubjects[0].subject_id);
                    } else {
                        this.renderLegend('subjectLegend', [], 'subject_name', 'mistake_count');
                        // Set deep dive link without specific subject
                        this.updateDeepDiveLink(null);
                    }
                } else {
                    // No data - render empty sunburst
                    if (this.sunburstChart) {
                        this.sunburstChart.render({ name: 'Root', children: [] });
                    } else {
                        this._renderEmptySunburst();
                    }
                    this.renderLegend('subjectLegend', [], 'subject_name', 'mistake_count');
                    document.getElementById('totalEntriesCenter').textContent = '0';
                    this.updateDeepDiveLink(null);
                }
            } else {
                // No exam selected - fall back to flat subject analytics
                const data = await api.getSubjectAnalytics({
                    examContextId: null,
                    limit: 5
                });

                console.log('Subject analytics response (no exam filter):', data);

                if (data && data.length > 0) {
                    // get_subject_analytics ranks these rows by total_mistake_count
                    // (direct + all descendants) whenever include_children is on, which
                    // is the default here. So every figure on this card — slice angles,
                    // legend counts and the centre number — must use that same rolled-up
                    // count. Reading mistake_count showed the direct-only count under a
                    // ranking by totals: a top 5 made up of parents with no directly
                    // tagged entries summed to 0 and sent the card to its empty state on
                    // a database full of entries. Fallback covers payload shapes that
                    // predate total_mistake_count.
                    const rankedSubjects = data.map(item => ({
                        ...item,
                        rollup_count: item.total_mistake_count || item.mistake_count || 0
                    }));

                    this.subjectData = rankedSubjects;
                    this._renderSimpleDonut(rankedSubjects);
                    this.renderLegend('subjectLegend', rankedSubjects, 'subject_name', 'rollup_count');

                    // The centre is the total of what this donut draws, not the
                    // database's entry count: if a parent and one of its descendants
                    // both make the top 5, the descendant's entries are inside both
                    // slices and the sum exceeds the number of entries. The sunburst
                    // branch above has the same property via its own centre label.
                    const total = rankedSubjects.reduce((sum, item) => sum + item.rollup_count, 0);
                    document.getElementById('totalEntriesCenter').textContent = total;

                    // Set default deep dive link to top subject
                    // (data[0] is the maximum only because the backend sorted it)
                    this.updateDeepDiveLink(data[0].subject_id);
                } else {
                    this._renderEmptySunburst();
                    this.renderLegend('subjectLegend', [], 'subject_name', 'mistake_count');
                    document.getElementById('totalEntriesCenter').textContent = '0';
                    this.updateDeepDiveLink(null);
                }
            }
        } catch (error) {
            console.error('Error loading subject chart:', error);
            this._renderEmptySunburst();
        }
    }

    /**
     * Handle sunburst segment click
     */
    handleSunburstClick(data) {
        if (data && data.id) {
            this.selectedSubjectId = data.id;
            this.updateDeepDiveLink(data.id);
        }
    }

    /**
     * Update the Subject Deep Dive link
     * @param {number|null} subjectId - Subject ID or null for general deep dive
     */
    updateDeepDiveLink(subjectId) {
        const deepDiveLink = document.getElementById('subjectDeepDiveLink');
        if (deepDiveLink) {
            let url = 'subject_deep_dive.html';
            const params = [];
            
            if (subjectId) {
                params.push(`subject=${subjectId}`);
            }
            if (this.currentExamFilter) {
                params.push(`exam=${this.currentExamFilter}`);
            }
            
            if (params.length > 0) {
                url += '?' + params.join('&');
            }
            
            deepDiveLink.href = url;
        }
    }

    /**
     * Handle sunburst segment hover
     */
    handleSunburstHover(data, isHovering) {
        // Could highlight corresponding legend item
        console.log('Sunburst hover:', data?.name, isHovering);
    }

    /**
     * Render empty sunburst state
     */
    _renderEmptySunburst() {
        const container = document.getElementById('subjectSunburst');
        if (!container) return;

        const emptySize = CHART_SIZE_PRESETS.subject_sunburst[this.chartSizes.subject_sunburst || 'M'];
        const ew = emptySize.width;
        const eh = emptySize.height;
        const half = ew / 2;
        container.innerHTML = `
            <svg width="${ew}" height="${eh}" viewBox="-${half} -${half} ${ew} ${eh}">
                <circle cx="0" cy="0" r="${half - 20}" fill="var(--bg-tertiary)" />
                <circle cx="0" cy="0" r="${half * 0.35}" fill="var(--bg-primary)" />
                <text text-anchor="middle" dy="0.35em" fill="var(--text-muted)" font-size="14">No data yet</text>
            </svg>
        `;
    }

    /**
     * Render simple donut for non-hierarchical view
     */
    _renderSimpleDonut(data) {
        const container = document.getElementById('subjectSunburst');
        if (!container) return;

        const width = 340;
        const height = 340;
        const radius = Math.min(width, height) / 2 - 20;
        const innerRadius = radius * 0.6;

        const colors = [
            '#ef4444', '#f59e0b', '#10b981', '#0ea5e9', '#8b5cf6', '#ec4899'
        ];

        // Rows arrive carrying rollup_count — total_mistake_count, i.e. direct plus
        // every descendant — which is the figure the backend ranked them by, so it is
        // what the slices have to be drawn from. mistake_count (direct only) is the
        // fallback for payload shapes without the rolled-up field.
        const countOf = (item) => item.rollup_count ?? item.mistake_count ?? 0;

        const total = data.reduce((sum, item) => sum + countOf(item), 0);
        if (total === 0) {
            this._renderEmptySunburst();
            return;
        }

        // Build SVG path data for each slice
        let pathsHtml = '';
        let startAngle = -Math.PI / 2;

        data.forEach((item, index) => {
            const sliceAngle = (countOf(item) / total) * 2 * Math.PI;
            const endAngle = startAngle + sliceAngle;

            const x1 = Math.cos(startAngle) * radius;
            const y1 = Math.sin(startAngle) * radius;
            const x2 = Math.cos(endAngle) * radius;
            const y2 = Math.sin(endAngle) * radius;
            const x3 = Math.cos(endAngle) * innerRadius;
            const y3 = Math.sin(endAngle) * innerRadius;
            const x4 = Math.cos(startAngle) * innerRadius;
            const y4 = Math.sin(startAngle) * innerRadius;

            const largeArc = sliceAngle > Math.PI ? 1 : 0;

            const pathData = [
                `M ${x1} ${y1}`,
                `A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2}`,
                `L ${x3} ${y3}`,
                `A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${x4} ${y4}`,
                'Z'
            ].join(' ');

            pathsHtml += `<path d="${pathData}" fill="${colors[index % colors.length]}" style="cursor: pointer;" onclick="window.dashboard.navigateToSubjectDeepDive(${item.subject_id})"><title>${WimiEscape.html(item.subject_name)}: ${countOf(item)}</title></path>`;

            startAngle = endAngle;
        });

        container.innerHTML = `
            <svg width="${width}" height="${height}" viewBox="${-width/2} ${-height/2} ${width} ${height}">
                ${pathsHtml}
            </svg>
        `;
    }

    /**
     * Load and render tag donut chart
     */
    async loadTagChart() {
        try {
            // Apply saved size to canvas
            const tagSize = CHART_SIZE_PRESETS.tag_chart[this.chartSizes.tag_chart || 'M'];
            const tagCanvas = document.getElementById('tagChart');
            if (tagCanvas) {
                tagCanvas.width = tagSize.width;
                tagCanvas.height = tagSize.height;
                const tagContainer = tagCanvas.closest('.chart-container');
                if (tagContainer) {
                    tagContainer.style.width = tagSize.width + 'px';
                    tagContainer.style.height = tagSize.height + 'px';
                }
            }

            const data = await api.getTagAnalytics({
                examContextId: this.currentExamFilter,
                dimensionId: this.currentDimensionFilter
            });

            console.log('Tag analytics response:', data);

            if (data && data.top_tags && data.top_tags.length > 0) {
                const topTags = data.top_tags.slice(0, 5);
                this.renderDonutChart('tagChart', topTags, 'name', 'count');
                this.renderLegend('tagLegend', topTags, 'name', 'count', 'color');

                // Update center label
                document.getElementById('totalTaggedCenter').textContent = data.total_tagged || 0;
            } else {
                // Show empty state
                this.renderDonutChart('tagChart', [], 'name', 'count');
                this.renderLegend('tagLegend', [], 'name', 'count');
                document.getElementById('totalTaggedCenter').textContent = '0';
            }
        } catch (error) {
            console.error('Error loading tag chart:', error);
        }
    }

    /**
     * Render a donut chart using Canvas
     */
    renderDonutChart(canvasId, data, labelKey, valueKey) {
        const canvas = document.getElementById(canvasId);
        const ctx = canvas.getContext('2d');

        console.log(`Rendering donut chart ${canvasId}:`, {
            dataLength: data?.length,
            labelKey,
            valueKey,
            firstItem: data?.[0]
        });

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Check if we have data
        if (!data || data.length === 0) {
            console.log(`No data for ${canvasId}, rendering empty state`);
            this.renderEmptyChart(canvas);
            return;
        }

        // Calculate total
        const total = data.reduce((sum, item) => sum + item[valueKey], 0);
        if (total === 0) {
            this.renderEmptyChart(canvas);
            return;
        }

        // Chart settings
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const radius = Math.min(centerX, centerY) - 20;
        const innerRadius = radius * 0.6;

        // Color palette
        const colors = [
            '#ef4444', // Red
            '#f59e0b', // Orange
            '#10b981', // Green
            '#0ea5e9', // Blue
            '#8b5cf6', // Purple
            '#ec4899'  // Pink
        ];

        let startAngle = -Math.PI / 2;

        data.forEach((item, index) => {
            const sliceAngle = (item[valueKey] / total) * 2 * Math.PI;
            const endAngle = startAngle + sliceAngle;

            // Draw slice
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius, startAngle, endAngle);
            ctx.arc(centerX, centerY, innerRadius, endAngle, startAngle, true);
            ctx.closePath();

            ctx.fillStyle = item.color || colors[index % colors.length];
            ctx.fill();

            startAngle = endAngle;
        });
    }

    /**
     * Render empty state for chart
     */
    renderEmptyChart(canvas) {
        const ctx = canvas.getContext('2d');
        const _cs = getComputedStyle(document.documentElement);

        // Draw a light gray circle
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const radius = Math.min(centerX, centerY) - 20;
        const innerRadius = radius * 0.6;

        ctx.beginPath();
        ctx.arc(centerX, centerY, radius, 0, 2 * Math.PI);
        ctx.arc(centerX, centerY, innerRadius, 2 * Math.PI, 0, true);
        ctx.closePath();
        ctx.fillStyle = _cs.getPropertyValue('--bg-tertiary').trim();
        ctx.fill();

        // Draw "No data" text
        ctx.fillStyle = _cs.getPropertyValue('--text-muted').trim();
        ctx.font = '14px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('No data yet', centerX, centerY);
    }

    /**
     * Render chart legend
     */
    renderLegend(containerId, data, labelKey, valueKey, colorKey = null) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';

        // Show empty state if no data
        if (!data || data.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted); font-size: 13px; text-align: center; margin: 16px 0;">No entries logged yet</p>';
            return;
        }

        const colors = [
            '#ef4444', '#f59e0b', '#10b981', '#0ea5e9', '#8b5cf6', '#ec4899'
        ];

        data.forEach((item, index) => {
            const legendItem = document.createElement('div');
            legendItem.className = 'legend-item';

            const color = colorKey && item[colorKey] ? item[colorKey] : colors[index % colors.length];

            // Add data-testid for individually addressable legend items
            const labelValue = item[labelKey];
            if (labelValue !== undefined && labelValue !== null) {
                if (containerId === 'tagLegend') {
                    legendItem.setAttribute('data-testid', `analytics-tag-legend-${labelValue}`);
                } else if (containerId === 'subjectLegend') {
                    const subjectKey = item.subject_id != null ? item.subject_id : labelValue;
                    legendItem.setAttribute('data-testid', `analytics-subject-legend-${subjectKey}`);
                }
            }

            // Make subject legend items clickable
            if (containerId === 'subjectLegend' && item.subject_id) {
                legendItem.style.cursor = 'pointer';
                legendItem.addEventListener('click', () => {
                    this.navigateToSubjectDeepDive(item.subject_id);
                });
            }

            // Built from nodes, not markup: the label is a subject or tag name
            // and the colour a stored tag column, both of which an import can
            // deliver unchecked (#548). Assigned through the style property, a
            // value that is not a colour paints nothing instead of escaping
            // the attribute.
            const label = document.createElement('div');
            label.className = 'legend-label';
            const swatch = document.createElement('div');
            swatch.className = 'legend-color';
            swatch.style.backgroundColor = color;
            const name = document.createElement('span');
            name.textContent = item[labelKey] ?? '';
            label.append(swatch, name);
            const countEl = document.createElement('span');
            countEl.className = 'legend-count';
            countEl.textContent = item[valueKey] ?? '';
            legendItem.append(label, countEl);

            // Surface tag definitions as hover tooltips (only tag data carries a description)
            if (typeof item.description === 'string' && item.description.trim() !== '') {
                legendItem.title = item.description;
            }

            container.appendChild(legendItem);
        });
    }

    /**
     * Navigate to subject deep dive page
     */
    navigateToSubjectDeepDive(subjectId) {
        const url = `subject_deep_dive.html?subject=${subjectId}${this.currentExamFilter ? `&exam=${this.currentExamFilter}` : ''}`;
        window.location.href = url;
    }

    /**
     * Load and render activity over time chart
     */
    async loadActivityChart() {
        try {
            // Apply saved size to canvas
            const actSize = CHART_SIZE_PRESETS.activity_chart[this.chartSizes.activity_chart || 'M'];
            const actCanvas = document.getElementById('activityChart');
            if (actCanvas) {
                actCanvas.width = actSize.width;
                actCanvas.height = actSize.height;
            }

            const data = await api.getActivityOverTime({
                examContextId: this.currentExamFilter,
                period: this.currentPeriod,
                granularity: 'day'
            });

            if (data) {
                this.renderLineChart('activityChart', data);
            }
        } catch (error) {
            console.error('Error loading activity chart:', error);
        }
    }

    /**
     * Render line chart using Canvas
     */
    renderLineChart(canvasId, data) {
        const canvas = document.getElementById(canvasId);
        const ctx = canvas.getContext('2d');
        const _cs = getComputedStyle(document.documentElement);

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        if (!data || data.length === 0) {
            // Draw empty state
            ctx.fillStyle = _cs.getPropertyValue('--text-muted').trim();
            ctx.font = '14px sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('No activity data yet. Start logging mistakes to see trends!', canvas.width / 2, canvas.height / 2);
            return;
        }

        // Chart settings
        const padding = 40;
        const chartWidth = canvas.width - (padding * 2);
        const chartHeight = canvas.height - (padding * 2);

        // Find max value
        const maxValue = Math.max(...data.map(d => d.count), 1);

        // Calculate points
        const points = data.map((item, index) => {
            const x = padding + (index / (data.length - 1 || 1)) * chartWidth;
            const y = padding + chartHeight - (item.count / maxValue) * chartHeight;
            return { x, y, count: item.count, label: item.label };
        });

        // Draw grid lines and Y-axis labels
        ctx.strokeStyle = _cs.getPropertyValue('--border-medium').trim();
        ctx.lineWidth = 1;
        ctx.fillStyle = _cs.getPropertyValue('--text-muted').trim();
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (let i = 0; i <= 5; i++) {
            const y = padding + (i / 5) * chartHeight;
            ctx.beginPath();
            ctx.moveTo(padding, y);
            ctx.lineTo(padding + chartWidth, y);
            ctx.stroke();
            const value = Math.round(maxValue * (1 - i / 5));
            ctx.fillText(value.toString(), padding - 8, y);
        }

        // Draw area fill under the line
        const infoColor = _cs.getPropertyValue('--color-info').trim();
        if (points.length > 1) {
            ctx.beginPath();
            ctx.moveTo(points[0].x, padding + chartHeight);
            points.forEach(point => ctx.lineTo(point.x, point.y));
            ctx.lineTo(points[points.length - 1].x, padding + chartHeight);
            ctx.closePath();
            const gradient = ctx.createLinearGradient(0, padding, 0, padding + chartHeight);
            gradient.addColorStop(0, infoColor + '30');
            gradient.addColorStop(1, infoColor + '05');
            ctx.fillStyle = gradient;
            ctx.fill();
        }

        // Draw line
        ctx.strokeStyle = infoColor;
        ctx.lineWidth = 3;
        ctx.lineJoin = 'round';
        ctx.beginPath();

        points.forEach((point, index) => {
            if (index === 0) {
                ctx.moveTo(point.x, point.y);
            } else {
                ctx.lineTo(point.x, point.y);
            }
        });

        ctx.stroke();

        // Draw points
        points.forEach(point => {
            ctx.beginPath();
            ctx.arc(point.x, point.y, 5, 0, 2 * Math.PI);
            ctx.fillStyle = _cs.getPropertyValue('--color-info').trim();
            ctx.fill();
            ctx.strokeStyle = _cs.getPropertyValue('--bg-primary').trim();
            ctx.lineWidth = 2;
            ctx.stroke();
        });

        // Draw X-axis labels
        ctx.fillStyle = _cs.getPropertyValue('--text-secondary').trim();
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'alphabetic';

        points.forEach((point, index) => {
            if (index % Math.ceil(data.length / 7) === 0 || index === data.length - 1) {
                ctx.fillText(point.label, point.x, canvas.height - 10);
            }
        });
    }

    /**
     * Load and render activity heatmap and streak display
     */
    async loadActivityHeatmap() {
        try {
            // Load heatmap data
            const heatmapData = await api.getActivityHeatmap({
                examContextId: this.currentExamFilter,
                weeks: 16
            });

            console.log('Heatmap data response:', heatmapData);

            // Initialize or update heatmap chart
            if (!this.heatmapChart) {
                const heatmapSize = CHART_SIZE_PRESETS.activity_heatmap[this.chartSizes.activity_heatmap || 'M'];
                this.heatmapChart = new ActivityHeatmap('activityHeatmap', {
                    weeks: 16,
                    cellSize: heatmapSize.cellSize,
                    cellGap: heatmapSize.cellGap,
                    onCellClick: (day) => this.handleHeatmapCellClick(day),
                    onCellHover: (day, isHovering) => this.handleHeatmapCellHover(day, isHovering)
                });
            }

            if (heatmapData) {
                this.heatmapChart.render(heatmapData);
            }

            // Initialize or update streak display
            if (!this.streakDisplay) {
                this.streakDisplay = new StreakDisplay('streakStats', {
                    showCurrentStreak: true,
                    showLongestStreak: true,
                    showActiveDays: true
                });
            }

            // Render streak display with data from heatmap response
            if (heatmapData) {
                this.streakDisplay.render({
                    current_streak: heatmapData.current_streak || 0,
                    longest_streak: heatmapData.longest_streak || 0,
                    total_active_days: heatmapData.total_active_days || 0,
                    // `end_date` is the payload's own last day, and the only
                    // honest key to look for here (#286). `days` is generated
                    // by `get_activity_heatmap` from `datetime.now().date()`
                    // -- the LOCAL date -- and stops there, so the UTC date
                    // this used to compute is a key the array cannot contain
                    // for part of every day: east or west of Greenwich the
                    // `some` found nothing and told a student who had logged
                    // entries today that they had not. Comparing against the
                    // payload keeps one clock in the comparison instead of
                    // two, so it cannot drift even if the response is stale.
                    is_active_today: heatmapData.days?.some(
                        d => d.date === heatmapData.end_date && d.count > 0
                    ) || false,
                    // The backend's own flag (#478), from the same
                    // `_calculate_streak_info` that produced the streak
                    // above -- never a definition of "at risk" made up here.
                    streak_at_risk: heatmapData.streak_at_risk === true
                }, heatmapData.total_days || 112);
            }

        } catch (error) {
            console.error('Error loading activity heatmap:', error);
        }
    }

    /**
     * Handle heatmap cell hover (activity heatmap)
     */
    handleHeatmapCellHover(day, isHovering) {
        // Could show additional details
    }

    /**
     * Load and render goal widget
     */
    async loadGoalWidget() {
        try {
            // Initialize goal widget if not already
            if (!this.goalWidget) {
                this.goalWidget = new GoalWidget('goalWidget', {
                    showHistory: true,
                    historyWeeks: 8,
                    onGoalChange: (result) => this.handleGoalChange(result)
                });
                
                // Make available globally for modal callbacks
                window.goalWidget = this.goalWidget;
            }

            // Load goal data
            await this.goalWidget.load(this.currentExamFilter);

        } catch (error) {
            console.error('Error loading goal widget:', error);
        }
    }

    /**
     * Handle goal change (callback from goal widget)
     */
    handleGoalChange(result) {
        console.log('Goal changed:', result);
        // Could refresh other analytics if needed
    }

    /**
     * Load and render difficulty distribution
     */
    async loadDifficultyDistribution() {
        try {
            const data = await api.getDifficultyDistribution(this.currentExamFilter);

            if (data) {
                this.renderDifficultyBars(data);
            }
        } catch (error) {
            console.error('Error loading difficulty distribution:', error);
        }
    }

    /**
     * Render difficulty distribution bars
     */
    renderDifficultyBars(data) {
        const container = document.getElementById('difficultyBars');
        container.innerHTML = '';

        const distribution = data.distribution;
        const total = data.total_rated;

        const levels = [
            { level: 1, class: 'easy', dots: '●' },
            { level: 2, class: 'moderate', dots: '●●' },
            { level: 3, class: 'medium', dots: '●●●' },
            { level: 4, class: 'hard', dots: '●●●●' },
            { level: 5, class: 'very-hard', dots: '●●●●●' }
        ];

        levels.forEach(({ level, class: className, dots }) => {
            const item = distribution[level];
            const percentage = item.percentage || 0;

            const row = document.createElement('div');
            row.className = 'difficulty-bar-row';
            row.setAttribute('data-testid', `analytics-difficulty-bar-${level}`);
            row.innerHTML = `
                <div class="difficulty-label">
                    <span class="difficulty-dots">${dots}</span>
                    <span>${item.label}</span>
                </div>
                <div class="difficulty-bar-container">
                    <div class="difficulty-bar-fill ${className}" style="width: ${percentage}%">
                        ${item.count > 0 ? `${item.count} (${percentage}%)` : ''}
                    </div>
                </div>
                <div class="difficulty-count">${item.count || 0} (${percentage}%)</div>
            `;

            container.appendChild(row);
        });
    }

    /**
     * Load and render insights
     */
    async loadInsights() {
        try {
            const data = await api.getPatternsAndInsights({
                examContextId: this.currentExamFilter,
                limit: 5
            });

            if (data) {
                this.renderInsights(data);
            }
        } catch (error) {
            console.error('Error loading insights:', error);
        }
    }

    /**
     * Render insights cards
     */
    renderInsights(insights) {
        const container = document.getElementById('insightsContainer');
        container.innerHTML = '';

        if (!insights || insights.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted);">No insights available yet. Keep logging mistakes to see patterns!</p>';
            return;
        }

        const icons = {
            warning: '⚠️',
            info: 'ℹ️',
            success: '✓'
        };

        insights.forEach(insight => {
            const card = document.createElement('div');
            card.className = `insight-card ${insight.severity}`;

            // The backend writes subject and tag names into the title, the
            // description and the suggested action, so every one is set as
            // text, never parsed (#546).
            const el = (tag, cls, text) => {
                const node = document.createElement(tag);
                node.className = cls;
                node.textContent = text ?? '';
                return node;
            };
            const content = document.createElement('div');
            content.className = 'insight-content';
            content.append(
                el('h3', 'insight-title', insight.title),
                el('p', 'insight-description', insight.description),
                el('div', 'insight-action', insight.actionable));
            card.append(el('div', 'insight-icon', icons[insight.severity] || 'ℹ️'), content);

            container.appendChild(card);
        });
    }

    /**
     * Question Banks Compared (#604).
     *
     * `source_chart.js` and `source_table.js` were written for this section
     * and loaded by no page for their whole existence (never, per
     * `git log -S`). Everything behind them was already live:
     * `get_source_comparison` -> `getSourceComparison` -> `api`.
     *
     * One fetch, two renderers. They are pure -- a container id and a
     * `render(data)` -- so neither knows about the bridge and both take the
     * same payload. A failure hides the section rather than leaving two empty
     * boxes and a gap, which is #60's mistake in another file.
     */
    async loadSourceComparison() {
        const section = document.querySelector('.source-section');
        try {
            const data = await api.getSourceComparison({
                examContextId: this.currentExamFilter || null
            });

            // No question bank has entries yet: say nothing rather than
            // drawing two empty frames. The section is absent, not empty.
            if (!data || !data.sources || data.sources.length === 0) {
                if (section) section.style.display = 'none';
                return;
            }
            if (section) section.style.display = '';

            if (!this.sourceChart) {
                this.sourceChart = new SourceComparisonChart('sourceComparisonChart');
            }
            if (!this.sourceTable) {
                this.sourceTable = new SourceTable('sourceComparisonTable');
            }
            this.sourceChart.render(data);
            this.sourceTable.render(data);
        } catch (e) {
            console.error('Failed to load source comparison:', e);
            if (section) section.style.display = 'none';
        }
    }

    /**
     * Fill the weight card's dimension and level pickers and return what
     * they select (#820): ``{}`` for an exam without dimensions, ``null``
     * when no dimension is chosen yet, else ``{dimensionId, levelType}``.
     *
     * The dimension starts at Settings' default dimension filter, the
     * setting the sunburst and the error-type chart already follow. The
     * level list is the cross-dimension pickers' own, so the two cards
     * offer the same levels in the same order (and share #818's).
     */
    async weightAnalysisScope() {
        const row = document.getElementById('weightScope');
        const dimSel = document.getElementById('weightDim');
        const levelSel = document.getElementById('weightLevel');
        const dims = this.dimensionAnalytics?.examUsesDimensions()
            ? (this.dimensionAnalytics.getDimensions() || []) : [];
        if (!row || !dimSel || !levelSel || !dims.length) {
            if (row) row.hidden = true;
            return {};
        }
        row.hidden = false;

        if (!this.weightScopeBound) {
            dimSel.addEventListener('change', () => {
                this.weightLevel = null;
                this.loadWeightAnalysis();
            });
            levelSel.addEventListener('change', () => {
                this.weightLevel = levelSel.value;
                this.loadWeightAnalysis();
            });
            this.weightScopeBound = true;
        }

        if (dimSel.dataset.exam !== String(this.currentExamFilter)) {
            const prompt = new Option('Choose a dimension', '');
            prompt.disabled = true;
            dimSel.replaceChildren(prompt, ...dims.map(d => new Option(d.name, String(d.id))));
            const preset = this.currentDimensionFilter;
            dimSel.value = dims.some(d => d.id === preset) ? String(preset) : '';
            dimSel.dataset.exam = String(this.currentExamFilter);
            this.weightLevel = null;
        }

        const dimensionId = dimSel.value ? parseInt(dimSel.value, 10) : null;
        if (!dimensionId) {
            levelSel.replaceChildren();
            levelSel.disabled = true;
            return null;
        }

        let levels = [];
        try {
            const data = await api.getHierarchyLevelsForDimension({
                examContextId: this.currentExamFilter,
                dimensionId,
            });
            levels = (data && data.levels) || [];
        } catch (e) {
            console.warn('Could not load levels for the weight analysis:', e);
        }
        levelSel.replaceChildren(...levels.map(l =>
            new Option(`${l.level_type} (${l.count})`, l.level_type)));
        levelSel.disabled = !levels.length;
        if (!levels.some(l => l.level_type === this.weightLevel)) {
            this.weightLevel = levels.length ? levels[0].level_type : null;
        }
        if (this.weightLevel) levelSel.value = this.weightLevel;
        return {dimensionId, levelType: this.weightLevel};
    }

    /**
     * Load and render subject vs exam weight analysis
     */
    async loadWeightAnalysis() {
        try {
            // Weight analysis requires an exam context to be selected
            if (!this.currentExamFilter) {
                const scopeRow = document.getElementById('weightScope');
                if (scopeRow) scopeRow.hidden = true;
                // Show message that exam selection is required
                const container = document.getElementById('weightAnalysis');
                if (container) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <p>Please select an exam to view weight analysis.</p>
                            <p class="empty-hint">This analysis compares your mistakes with exam subject weights.</p>
                        </div>
                    `;
                }
                // Stage 9: also hide the breakdown card when no exam.
                const breakdownCard = document.getElementById('weightSourceBreakdownCard');
                if (breakdownCard) breakdownCard.style.display = 'none';
                return;
            }

            // Initialize weight analysis component if not already
            if (!this.weightAnalysis) {
                this.weightAnalysis = new WeightAnalysis('weightAnalysis', api);
            }

            // One dimension at one level (#820). null means the exam has
            // dimensions and none is chosen: the owner's decision is to ask
            // rather than mix them, since each covers the whole exam.
            const scope = await this.weightAnalysisScope();
            if (scope === null) {
                // A load still in flight must not draw over the prompt.
                this.weightAnalysis.loadSeq = (this.weightAnalysis.loadSeq || 0) + 1;
                this.weightAnalysis.renderPrompt(
                    'Choose a dimension to compare its subjects with their exam weights.',
                    'Each dimension covers the whole exam on its own, so they are compared one at a time.');
            } else {
                await this.weightAnalysis.load(this.currentExamFilter, scope);
            }

            // Stage 9: render the confidence breakdown card. We do
            // this in parallel with the main analysis so the card
            // shows the same data the user sees in the quadrant view.
            await this.loadWeightSourceBreakdown();

        } catch (error) {
            console.error('Error loading weight analysis:', error);
            const container = document.getElementById('weightAnalysis');
            if (container) {
                container.innerHTML = `
                    <div class="error-state">
                        <p>Error loading weight analysis</p>
                        <p class="error-detail">${WimiEscape.html(error.message)}</p>
                    </div>
                `;
            }
        }
    }

    /**
     * Stage 9 — render the per-``weight_source`` confidence breakdown card.
     *
     * Pulls from ``api.getWeightSourceBreakdown`` (cheaper than the
     * full ``getSubjectExamWeightAnalysis`` if the user only needs the
     * counts). Uses the same marker glyphs as
     * ``WeightAnalysis.renderSourceMarker`` so the card and the inline
     * markers are visually consistent.
     */
    async loadWeightSourceBreakdown() {
        const card = document.getElementById('weightSourceBreakdownCard');
        if (!card || !this.currentExamFilter) return;

        try {
            const data = await api.getWeightSourceBreakdown(this.currentExamFilter);
            if (!data) {
                card.style.display = 'none';
                return;
            }

            const total = data.total || 0;
            if (total === 0) {
                card.innerHTML = `
                    <div class="breakdown-title">Weight Sources</div>
                    <div class="breakdown-empty">No weighted subjects yet.</div>
                `;
                card.style.display = '';
                return;
            }

            // Glyphs mirror WeightAnalysis.renderSourceMarker exactly
            // so visual identity is preserved across the dashboard.
            const rows = [
                { key: 'official',      glyph: '●', label: 'official' },
                { key: 'user_explicit', glyph: '⚓', label: 'user-anchored' },
                { key: 'user_defined',  glyph: '○', label: 'user-defined' },
                { key: 'derived',       glyph: '⊘', label: 'derived' },
                { key: 'user_estimate', glyph: '·', label: 'estimated' },
            ];

            const listHtml = rows.map(r => {
                const count = data[r.key] || 0;
                return `
                    <li class="breakdown-row" data-testid="weight-source-breakdown-row-${r.key}">
                        <span class="weight-source-marker" data-source="${r.key}">${r.glyph}</span>
                        <span class="breakdown-count">${count}</span>
                        <span class="breakdown-label">${r.label}</span>
                    </li>
                `;
            }).join('');

            // The tour's step is about the counts, so only the branch that
            // draws them carries its anchor (#682).
            card.innerHTML = `
                <div class="section-title-row">
                    <div class="breakdown-title" data-tour-anchor="analytics-weight-sources">Weight Sources</div>
                    <span class="card-info-icon" tabindex="0" data-testid="analytics-info-weight-sources"
                          aria-label="${WEIGHT_SOURCES_TIP}">i<span class="card-info-tooltip"
                          data-testid="analytics-info-weight-sources-tooltip">${WEIGHT_SOURCES_TIP}</span></span>
                </div>
                <ul class="breakdown-list">${listHtml}</ul>
            `;
            card.style.display = '';
        } catch (error) {
            console.error('Error loading weight source breakdown:', error);
            // Hide rather than show a noisy error — the breakdown is
            // a secondary card and failure shouldn't dominate the page.
            card.style.display = 'none';
        }
    }

    // =========================================================================
    // MULTI-DIMENSIONAL ANALYTICS METHODS
    // =========================================================================

    /**
     * Load and render cross-dimension heatmap
     */
    async loadCrossDimensionHeatmap() {
        if (!this.dimensionAnalytics?.examUsesDimensions() || !this.dimensionHeatmap) {
            return false;
        }

        // Only the newest request may draw (#799). An older one -- above all
        // an unlevelled one, the slowest query on the page -- would otherwise
        // land after it and overwrite the right grid with the wrong one.
        // A superseded call returns null, never false: the drilldown handler
        // reads false as "no data here" and rolls its own state back.
        const ticket = (this.heatmapRequest = (this.heatmapRequest || 0) + 1);
        if (this.heatmapLevelsReady) {
            try { await this.heatmapLevelsReady; } catch (e) { /* drawn below as All Levels */ }
        }
        if (ticket !== this.heatmapRequest) return null;

        try {
            const dimASelect = document.getElementById('heatmapDimA');
            const dimBSelect = document.getElementById('heatmapDimB');

            if (!dimASelect || !dimBSelect) return false;

            const dimensionAId = parseInt(dimASelect.value);
            const dimensionBId = parseInt(dimBSelect.value);

            if (dimensionAId === dimensionBId) {
                // Show warning that same dimension was selected
                const container = document.getElementById('dimensionHeatmap');
                if (container) {
                    container.innerHTML = `
                        <div class="heatmap-warning">
                            <p>Please select two different dimensions to view the heatmap</p>
                        </div>
                    `;
                }
                return false;
            }

            // Get drill-down parameters from state
            const levelTypeA = this.drilldownState.levelTypeA;
            const levelTypeB = this.drilldownState.levelTypeB;
            const parentNodeAId = this.drilldownState.parentNodeA?.id || null;
            const parentNodeBId = this.drilldownState.parentNodeB?.id || null;

            const scope = {
                dimensionAId: dimensionAId,
                dimensionBId: dimensionBId,
                levelTypeA: levelTypeA,
                levelTypeB: levelTypeB,
                parentNodeAId: parentNodeAId,
                parentNodeBId: parentNodeBId
            };
            const data = await api.getCrossDimensionPerformance({
                examContextId: this.currentExamFilter,
                minEntries: 1,
                ...scope
            });
            if (ticket !== this.heatmapRequest) return null;
            // Recommendations rank exactly these cells (#824). Not awaited:
            // the heatmap's own result must not wait on a second query.
            this.loadStudyRecommendations(scope);

            if (!data || !data.matrix || data.matrix.length === 0) {
                // Render the empty state but signal no data
                this.dimensionHeatmap.render(data, {
                    onRowHeaderClick: (nodeId, nodeName) => this.handleHeatmapDrilldown(nodeId, nodeName, 'A'),
                    onColHeaderClick: (nodeId, nodeName) => this.handleHeatmapDrilldown(nodeId, nodeName, 'B')
                });
                return false;
            }

            // Pass drill-down handler to heatmap for row/column header clicks
            this.dimensionHeatmap.render(data, {
                onRowHeaderClick: (nodeId, nodeName) => this.handleHeatmapDrilldown(nodeId, nodeName, 'A'),
                onColHeaderClick: (nodeId, nodeName) => this.handleHeatmapDrilldown(nodeId, nodeName, 'B')
            });
            this.dimensionHeatmap.renderLegend('heatmapLegend');
            return true;

        } catch (error) {
            if (ticket !== this.heatmapRequest) return null;
            console.error('Error loading cross-dimension heatmap:', error);
            const container = document.getElementById('dimensionHeatmap');
            if (container) {
                container.innerHTML = `
                    <div class="heatmap-error">
                        <p>Error loading heatmap</p>
                    </div>
                `;
            }
            return false;
        }
    }

    /**
     * Load and render study recommendations
     */
    async loadStudyRecommendations(scope = {}) {
        if (!this.dimensionAnalytics?.examUsesDimensions() || !this.dimensionInsights) {
            return;
        }
        // Only the newest request may draw, as with the heatmap (#799).
        const seq = (this.recommendationsRequest = (this.recommendationsRequest || 0) + 1);

        try {
            const data = await api.getWeightedStudyRecommendations({
                examContextId: this.currentExamFilter,
                limit: 5,
                ...scope
            });
            if (seq !== this.recommendationsRequest) return;

            this.dimensionInsights.renderStudyRecommendations(data);

        } catch (error) {
            if (seq !== this.recommendationsRequest) return;
            console.error('Error loading study recommendations:', error);
            // Say so in the card (#469). This was console-only, so a failure
            // left the heading STUDY RECOMMENDATIONS with nothing under it --
            // no message and nothing to act on (#174). Styled as this card's
            // own empty state (`.insights-empty`), which analytics.css already
            // lays out; the detail goes in as text, never as markup.
            const container = document.getElementById(
                `${this.dimensionInsights.containerId}-recommendations`);
            if (container) {
                const box = document.createElement('div');
                box.className = 'insights-empty';
                box.setAttribute('data-testid', 'study-recommendations-error');
                const head = document.createElement('p');
                head.textContent = 'Error loading study recommendations';
                const detail = document.createElement('p');
                detail.className = 'insights-empty-hint';
                detail.textContent = error && error.message ? error.message : String(error);
                box.append(head, detail);
                container.replaceChildren(box);
            }
        }
    }

    /**
     * Load and render interaction effects
     */
    async loadInteractionEffects() {
        // Cleared first so an exam switch to one with fewer than two
        // dimensions does not keep the tour's anchor from the last (#682).
        document.querySelector('#interactionEffectsContainer .subsection-title')
            ?.removeAttribute('data-tour-anchor');
        if (!this.dimensionAnalytics?.examUsesDimensions() || !this.dimensionInsights) {
            return;
        }

        try {
            const dimensions = this.dimensionAnalytics.getDimensions();
            if (dimensions.length < 2) return;

            const data = await api.detectInteractionEffects({
                examContextId: this.currentExamFilter,
                dimensionAId: dimensions[0].id,
                dimensionBId: dimensions[1].id,
                threshold: 0.10
            });

            this.dimensionInsights.renderInteractionEffects(data);

            // The tour's step says these compare the exam's first two
            // dimensions, which is true only once two exist and were sent
            // (#682). The heading is static markup, so it is marked here.
            document.querySelector('#interactionEffectsContainer .subsection-title')
                ?.setAttribute('data-tour-anchor', 'analytics-interaction-effects');

        } catch (error) {
            console.error('Error loading interaction effects:', error);
        }
    }

    /**
     * Handle heatmap cell click — navigate to entry browser for the intersection.
     * Cross-dimension heatmap passes {dimA, dimB, cell}; activity heatmap passes {date, count}.
     */
    handleHeatmapCellClick(data) {
        if (!data) return;

        // Cross-dimension heatmap cell: navigate to entry browser with AND-mode subjects
        if (data.dimA && data.dimB) {
            const params = new URLSearchParams();
            if (this.currentExamFilter) {
                params.set('exam', this.currentExamFilter);
            }
            params.set('subjects', `${data.dimA.id},${data.dimB.id}`);
            params.set('subject_mode', 'and');
            params.set('include_children', 'true');
            window.location.href = `entry_browser.html?${params.toString()}`;
            return;
        }

        // Activity heatmap cell (day object) — no action currently
        console.log('Heatmap cell clicked:', data);
    }

    /**
     * Handle heatmap cell hover
     */
    handleHeatmapCellHover(data, isHovering) {
        // Optional hover handling
    }

    /**
     * Handle study recommendation click
     */
    /**
     * Open the entries behind a recommended pair (#829, owner's decision).
     * Since #824 a recommendation is one of the heatmap's cells, so this goes
     * through the cell's own handler and the two land on the same list.
     */
    handleRecommendationClick(recommendation) {
        if (!recommendation) return;
        this.handleHeatmapCellClick({
            dimA: {id: recommendation.dim_a_hierarchy_id},
            dimB: {id: recommendation.dim_b_hierarchy_id},
        });
    }
}

/** The Weight Sources card's tip, the owner's approved text (#825). No
 *  markup characters, so it is safe in an attribute and in text alike. */
const WEIGHT_SOURCES_TIP = "Where your subjects' weights came from. It describes your data and changes no number on this page.";

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new AnalyticsDashboard();
});
