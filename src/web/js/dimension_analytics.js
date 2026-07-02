/**
 * WIMI Dimension Analytics Component
 * Phase 7.4 - Dimension selector and filtering for multi-dimensional exams
 */

class DimensionAnalytics {
    /**
     * Create a dimension analytics controller
     * @param {number} examContextId - Exam context ID
     * @param {function} onDimensionChange - Callback when dimension changes
     */
    constructor(examContextId, onDimensionChange) {
        this.examContextId = examContextId;
        this.onDimensionChange = onDimensionChange;
        this.dimensions = [];
        this.currentDimensionId = null;
        this.usesDimensions = false;
    }

    /**
     * Load dimensions for the exam
     * @returns {Promise<boolean>} Whether the exam uses dimensions
     */
    async loadDimensions() {
        try {
            // Check if exam uses dimensions
            const result = await api.examUsesDimensions(this.examContextId);
            this.usesDimensions = result.uses_dimensions || false;

            if (!this.usesDimensions) {
                this.dimensions = [];
                return false;
            }

            // Load dimensions
            this.dimensions = await api.getDimensions(this.examContextId);
            return this.dimensions.length > 0;

        } catch (error) {
            console.error('Error loading dimensions:', error);
            this.dimensions = [];
            this.usesDimensions = false;
            return false;
        }
    }

    /**
     * Render the dimension selector dropdown
     * @param {string} containerId - ID of the container element
     */
    renderSelector(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        // Clear existing content
        container.innerHTML = '';

        if (!this.usesDimensions || this.dimensions.length === 0) {
            container.style.display = 'none';
            return;
        }

        container.style.display = 'block';

        // Create the select element
        const select = document.createElement('select');
        select.id = 'dimensionFilter';
        select.className = 'dimension-filter';

        // Add "All Dimensions" option
        const allOption = document.createElement('option');
        allOption.value = '';
        allOption.textContent = 'All Dimensions';
        select.appendChild(allOption);

        // Add dimension options
        this.dimensions.forEach(dim => {
            const option = document.createElement('option');
            option.value = dim.id;
            option.textContent = dim.name;
            select.appendChild(option);
        });

        // Add change listener
        select.addEventListener('change', (e) => {
            this.currentDimensionId = e.target.value ? parseInt(e.target.value) : null;
            if (this.onDimensionChange) {
                this.onDimensionChange(this.currentDimensionId);
            }
        });

        container.appendChild(select);
    }

    /**
     * Get the currently selected dimension ID
     * @returns {number|null} Current dimension ID or null for "All"
     */
    getCurrentDimensionId() {
        return this.currentDimensionId;
    }

    /**
     * Set the current dimension programmatically
     * @param {number|null} dimensionId - Dimension ID to select
     */
    setCurrentDimension(dimensionId) {
        this.currentDimensionId = dimensionId;
        const select = document.getElementById('dimensionFilter');
        if (select) {
            select.value = dimensionId ? dimensionId.toString() : '';
        }
    }

    /**
     * Check if exam uses dimensions
     * @returns {boolean}
     */
    examUsesDimensions() {
        return this.usesDimensions;
    }

    /**
     * Get all dimensions
     * @returns {Array} List of dimensions
     */
    getDimensions() {
        return this.dimensions;
    }

    /**
     * Get dimension by ID
     * @param {number} dimensionId - Dimension ID
     * @returns {object|null} Dimension object or null
     */
    getDimensionById(dimensionId) {
        return this.dimensions.find(d => d.id === dimensionId) || null;
    }

    /**
     * Render dimension tabs instead of dropdown (alternative UI)
     * @param {string} containerId - ID of the container element
     */
    renderTabs(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        container.innerHTML = '';

        if (!this.usesDimensions || this.dimensions.length === 0) {
            container.style.display = 'none';
            return;
        }

        container.style.display = 'flex';
        container.className = 'dimension-tabs';

        // Add "All" tab
        const allTab = document.createElement('button');
        allTab.className = 'dimension-tab active';
        allTab.textContent = 'All';
        allTab.dataset.dimensionId = '';
        allTab.addEventListener('click', () => this._handleTabClick(allTab, null));
        container.appendChild(allTab);

        // Add dimension tabs
        this.dimensions.forEach(dim => {
            const tab = document.createElement('button');
            tab.className = 'dimension-tab';
            tab.textContent = dim.name;
            tab.dataset.dimensionId = dim.id;
            tab.addEventListener('click', () => this._handleTabClick(tab, dim.id));
            container.appendChild(tab);
        });
    }

    /**
     * Handle tab click
     * @private
     */
    _handleTabClick(tab, dimensionId) {
        // Update active state
        document.querySelectorAll('.dimension-tab').forEach(t => {
            t.classList.remove('active');
        });
        tab.classList.add('active');

        // Update current dimension
        this.currentDimensionId = dimensionId;

        // Trigger callback
        if (this.onDimensionChange) {
            this.onDimensionChange(dimensionId);
        }
    }

    /**
     * Get performance data for all dimensions
     * @returns {Promise<Array>} Performance data for each dimension
     */
    async getAllDimensionPerformance() {
        if (!this.usesDimensions) return [];

        const results = [];
        for (const dim of this.dimensions) {
            try {
                const perf = await api.getDimensionPerformance({
                    examContextId: this.examContextId,
                    dimensionId: dim.id
                });
                results.push({
                    dimension: dim,
                    performance: perf
                });
            } catch (error) {
                console.error(`Error loading performance for dimension ${dim.id}:`, error);
            }
        }
        return results;
    }

    /**
     * Render a summary card showing dimension overview
     * @param {string} containerId - ID of the container element
     */
    async renderSummaryCard(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!this.usesDimensions || this.dimensions.length === 0) {
            container.innerHTML = `
                <div class="dimension-info-card">
                    <p class="dimension-info-text">
                        This exam uses single-dimension categorization.
                        <a href="#" class="learn-more-link">Learn about multi-dimensional analytics</a>
                    </p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="dimension-summary-loading">
                <div class="loading-spinner"></div>
                <span>Loading dimension summary...</span>
            </div>
        `;

        try {
            const performanceData = await this.getAllDimensionPerformance();

            let cardsHtml = performanceData.map(({ dimension, performance }) => {
                const topNodes = performance.nodes.slice(0, 3);
                const topNodesHtml = topNodes.map(n =>
                    `<span class="dim-top-node">${n.name} (${n.total_entries})</span>`
                ).join('');

                return `
                    <div class="dimension-summary-item">
                        <div class="dim-summary-header">
                            <span class="dim-name">${dimension.name}</span>
                            <span class="dim-total">${performance.total} entries</span>
                        </div>
                        <div class="dim-top-nodes">${topNodesHtml}</div>
                    </div>
                `;
            }).join('');

            container.innerHTML = `
                <div class="dimension-summary-card">
                    <h4 class="dimension-summary-title">Dimensions Overview</h4>
                    <div class="dimension-summary-grid">
                        ${cardsHtml}
                    </div>
                </div>
            `;

        } catch (error) {
            console.error('Error rendering dimension summary:', error);
            container.innerHTML = `
                <div class="dimension-error">
                    <p>Error loading dimension data</p>
                </div>
            `;
        }
    }
}

// Export for use in other modules
window.DimensionAnalytics = DimensionAnalytics;
