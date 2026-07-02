/**
 * WIMI Analytics Dashboard
 * Phase 6 Stage 2 - Overview Section
 */

// Size preset definitions for resizable charts
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

class AnalyticsDashboard {
    constructor() {
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

        // Initialize dimension analytics
        await this.initializeDimensionAnalytics();

        // Set up event listeners
        this.setupEventListeners();

        // Load all analytics data
        await this.loadAllData();

        // Apply chart visibility after data is loaded
        this.applyChartVisibility();

        // Apply saved chart sizes
        this.applyChartSizes();
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
        const mapping = {
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
            'weight_analysis': '.weight-analysis-section'
        };

        for (const [key, selector] of Object.entries(mapping)) {
            const el = document.querySelector(selector);
            if (!el) continue;
            if (vis[key] === false) {
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
        dimASelect.addEventListener('change', () => {
            this.resetDrilldown('A');
            this.loadLevelOptionsForDimension('A', parseInt(dimASelect.value));
            this.loadCrossDimensionHeatmap();
        });
        dimBSelect.addEventListener('change', () => {
            this.resetDrilldown('B');
            this.loadLevelOptionsForDimension('B', parseInt(dimBSelect.value));
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

        // Swap button
        const swapBtn = document.getElementById('swapDimensionsBtn');
        if (swapBtn) {
            swapBtn.addEventListener('click', () => {
                const tempVal = dimASelect.value;
                dimASelect.value = dimBSelect.value;
                dimBSelect.value = tempVal;
                // Swap drilldown state (levels, parents, paths, cached levels)
                const tempLevelA = this.drilldownState.levelTypeA;
                const tempParentA = this.drilldownState.parentNodeA;
                const tempPathA = this.drilldownState.drillPathA;
                const tempLevelsA = this.drilldownState.levelsA;
                this.drilldownState.levelTypeA = this.drilldownState.levelTypeB;
                this.drilldownState.parentNodeA = this.drilldownState.parentNodeB;
                this.drilldownState.drillPathA = this.drilldownState.drillPathB;
                this.drilldownState.levelsA = this.drilldownState.levelsB;
                this.drilldownState.levelTypeB = tempLevelA;
                this.drilldownState.parentNodeB = tempParentA;
                this.drilldownState.drillPathB = tempPathA;
                this.drilldownState.levelsB = tempLevelsA;
                // Reload level options for swapped dimensions
                this.loadLevelOptionsForDimension('A', parseInt(dimASelect.value));
                this.loadLevelOptionsForDimension('B', parseInt(dimBSelect.value));
                this.loadCrossDimensionHeatmap();
                this.updateBreadcrumb();
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

        // Load initial level options
        this.loadLevelOptionsForDimension('A', parseInt(dimASelect.value));
        this.loadLevelOptionsForDimension('B', parseInt(dimBSelect.value));
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

        // Build path A
        if (hasPathA) {
            pathA.innerHTML = this.drilldownState.drillPathA
                .map((node, idx) => `<a class="breadcrumb-link" data-dimension="A" data-index="${idx}" data-testid="analytics-heatmap-breadcrumb-a-step-${idx}">${node.name}</a>`)
                .join(' > ');
        } else {
            pathA.innerHTML = '<span class="breadcrumb-empty" data-testid="analytics-heatmap-breadcrumb-a-empty">All</span>';
        }

        // Build path B
        if (hasPathB) {
            pathB.innerHTML = this.drilldownState.drillPathB
                .map((node, idx) => `<a class="breadcrumb-link" data-dimension="B" data-index="${idx}" data-testid="analytics-heatmap-breadcrumb-b-step-${idx}">${node.name}</a>`)
                .join(' > ');
        } else {
            pathB.innerHTML = '<span class="breadcrumb-empty" data-testid="analytics-heatmap-breadcrumb-b-empty">All</span>';
        }

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

        // Load heatmap and check if data was returned
        const hasData = await this.loadCrossDimensionHeatmap();

        if (!hasData) {
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
            const exams = await api.getAllExamContexts();

            if (exams && exams.length > 0) {
                const select = document.getElementById('examFilter');
                select.innerHTML = ''; // Clear any existing options

                exams.forEach(exam => {
                    const option = document.createElement('option');
                    option.value = exam.id;
                    option.textContent = exam.exam_name;
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
            this.loadWeightAnalysis()
        ];

        // Add multi-dimensional analytics if available
        if (this.dimensionAnalytics && this.dimensionAnalytics.examUsesDimensions()) {
            promises.push(
                this.loadCrossDimensionHeatmap(),
                this.loadStudyRecommendations(),
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

                if (data.week_change !== 0) {
                    const changeText = Math.abs(data.week_change);
                    weekChange.textContent = `${data.week_change > 0 ? '+' : ''}${changeText}`;
                    weekChange.className = 'change ' + (data.week_change > 0 ? 'positive' : 'negative');
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
                    // Load dimension-filtered hierarchy
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
                    this.subjectData = data;
                    this._renderSimpleDonut(data);
                    this.renderLegend('subjectLegend', data, 'subject_name', 'mistake_count');

                    const total = data.reduce((sum, item) => sum + item.mistake_count, 0);
                    document.getElementById('totalEntriesCenter').textContent = total;
                    
                    // Set default deep dive link to top subject
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

        const total = data.reduce((sum, item) => sum + item.mistake_count, 0);
        if (total === 0) {
            this._renderEmptySunburst();
            return;
        }

        // Build SVG path data for each slice
        let pathsHtml = '';
        let startAngle = -Math.PI / 2;

        data.forEach((item, index) => {
            const sliceAngle = (item.mistake_count / total) * 2 * Math.PI;
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

            pathsHtml += `<path d="${pathData}" fill="${colors[index % colors.length]}" style="cursor: pointer;" onclick="window.dashboard.navigateToSubjectDeepDive(${item.subject_id})"><title>${item.subject_name}: ${item.mistake_count}</title></path>`;

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

            legendItem.innerHTML = `
                <div class="legend-label">
                    <div class="legend-color" style="background-color: ${color}"></div>
                    <span>${item[labelKey]}</span>
                </div>
                <span class="legend-count">${item[valueKey]}</span>
            `;

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
                    is_active_today: heatmapData.days?.some(d => {
                        const today = new Date().toISOString().split('T')[0];
                        return d.date === today && d.count > 0;
                    }) || false,
                    streak_at_risk: false  // Will be calculated if needed
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

            card.innerHTML = `
                <div class="insight-icon">${icons[insight.severity] || 'ℹ️'}</div>
                <div class="insight-content">
                    <h3 class="insight-title">${insight.title}</h3>
                    <p class="insight-description">${insight.description}</p>
                    <div class="insight-action">${insight.actionable}</div>
                </div>
            `;

            container.appendChild(card);
        });
    }

    /**
     * Load and render subject vs exam weight analysis
     */
    async loadWeightAnalysis() {
        try {
            // Weight analysis requires an exam context to be selected
            if (!this.currentExamFilter) {
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

            // Load the weight analysis data
            await this.weightAnalysis.load(this.currentExamFilter);

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
                        <p class="error-detail">${error.message}</p>
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

            card.innerHTML = `
                <div class="breakdown-title">Weight Sources</div>
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

            const data = await api.getCrossDimensionPerformance({
                examContextId: this.currentExamFilter,
                dimensionAId: dimensionAId,
                dimensionBId: dimensionBId,
                minEntries: 1,
                levelTypeA: levelTypeA,
                levelTypeB: levelTypeB,
                parentNodeAId: parentNodeAId,
                parentNodeBId: parentNodeBId
            });

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
    async loadStudyRecommendations() {
        if (!this.dimensionAnalytics?.examUsesDimensions() || !this.dimensionInsights) {
            return;
        }

        try {
            const data = await api.getWeightedStudyRecommendations({
                examContextId: this.currentExamFilter,
                limit: 5
            });

            this.dimensionInsights.renderStudyRecommendations(data);

        } catch (error) {
            console.error('Error loading study recommendations:', error);
        }
    }

    /**
     * Load and render interaction effects
     */
    async loadInteractionEffects() {
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
    handleRecommendationClick(recommendation) {
        console.log('Recommendation clicked:', recommendation);
        // Could navigate to filtered entries view
    }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new AnalyticsDashboard();
});
