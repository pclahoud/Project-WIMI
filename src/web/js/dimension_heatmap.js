/**
 * WIMI Dimension Heatmap Component
 * Phase 7.5 - D3.js-based 2D heatmap for cross-dimension analysis
 */

class DimensionHeatmap {
    /**
     * Create a dimension heatmap
     * @param {string} containerId - ID of the container element
     * @param {object} options - Configuration options
     */
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);

        this.options = {
            cellSize: options.cellSize || 50,
            cellPadding: options.cellPadding || 4,
            marginTop: options.marginTop || 100,
            marginRight: options.marginRight || 20,
            marginBottom: options.marginBottom || 20,
            marginLeft: options.marginLeft || 140,
            minColor: options.minColor || '#10b981',  // Green (good)
            midColor: options.midColor || '#f59e0b',   // Yellow
            maxColor: options.maxColor || '#ef4444',   // Red (bad)
            insufficientColor: options.insufficientColor || '#e5e7eb',
            onCellClick: options.onCellClick || null,
            onCellHover: options.onCellHover || null
        };

        this.data = null;
        this.svg = null;
        this.colorScale = null;
    }

    /**
     * Render the heatmap with matrix data
     * @param {object} matrixData - Cross-dimension performance data
     * @param {object} drilldownOptions - Optional drill-down callbacks
     * @param {function} drilldownOptions.onRowHeaderClick - Callback when row header is clicked (nodeId, nodeName)
     * @param {function} drilldownOptions.onColHeaderClick - Callback when column header is clicked (nodeId, nodeName)
     */
    render(matrixData, drilldownOptions = {}) {
        if (!matrixData || !matrixData.matrix || matrixData.matrix.length === 0) {
            this._renderEmptyState();
            return;
        }

        const _cs = getComputedStyle(document.documentElement);

        this.data = matrixData;
        this.drilldownOptions = drilldownOptions;

        // Clear existing content
        this.container.innerHTML = '';

        // Scale factor relative to medium cell size (68px)
        const sf = this.options.cellSize / 68;
        const headerFont = Math.round(11 * sf);
        const cellFont = Math.round(12 * sf);
        const titleFont = Math.round(13 * sf);
        const colTruncLen = Math.round(15 * sf);
        const rowTruncLen = Math.round(18 * sf);
        this.options.marginLeft = Math.round(140 * sf);

        // Get unique values for each dimension
        const dimAValues = matrixData.dimension_a.values;
        const dimBValues = matrixData.dimension_b.values;

        // Measure longest column label to auto-adjust top margin
        const truncatedLabels = dimBValues.map(v => this._truncateLabel(v.name, colTruncLen));
        const measureCanvas = document.createElement('canvas');
        const ctx = measureCanvas.getContext('2d');
        ctx.font = `${headerFont}px sans-serif`;
        let maxTextWidth = 0;
        truncatedLabels.forEach(label => {
            maxTextWidth = Math.max(maxTextWidth, ctx.measureText(label).width);
        });

        // Vertical extent of longest label when rotated -45deg
        const labelHeight = Math.ceil(maxTextWidth * Math.sin(Math.PI / 4));
        // marginTop = dim B title space (30px scaled) + label vertical extent + gap (2px)
        this.options.marginTop = Math.max(Math.round(60 * sf), Math.round(30 * sf) + labelHeight + 2);

        // With text-anchor: start + rotate(-45), anchor is the bottom of the rotated text.
        // Place it just above the cell area so the first character connects to the column.
        const labelY = this.options.marginTop - 2;

        // Calculate dimensions
        const width = this.options.marginLeft + (dimBValues.length * (this.options.cellSize + this.options.cellPadding)) + this.options.marginRight;
        const height = this.options.marginTop + (dimAValues.length * (this.options.cellSize + this.options.cellPadding)) + this.options.marginBottom;

        // Create SVG
        this.svg = d3.select(`#${this.containerId}`)
            .append('svg')
            .attr('width', width)
            .attr('height', height)
            .attr('viewBox', [0, 0, width, height])
            .style('font', `${cellFont}px sans-serif`);

        // Create color scale
        const maxCount = d3.max(matrixData.matrix, d => d.count) || 1;
        this.colorScale = d3.scaleSequential()
            .domain([0, maxCount])
            .interpolator(d3.interpolateRgb(this.options.minColor, this.options.maxColor));

        // Create scales for positioning
        const xScale = d3.scaleBand()
            .domain(dimBValues.map(v => v.id))
            .range([this.options.marginLeft, width - this.options.marginRight])
            .padding(0.1);

        const yScale = d3.scaleBand()
            .domain(dimAValues.map(v => v.id))
            .range([this.options.marginTop, height - this.options.marginBottom])
            .padding(0.1);

        // Create lookup for matrix data
        const matrixLookup = {};
        matrixData.matrix.forEach(cell => {
            const key = `${cell.dim_a_hierarchy_id}-${cell.dim_b_hierarchy_id}`;
            matrixLookup[key] = cell;
        });

        // Draw column headers (dimension B values) - clickable for drill-down
        const colHeaders = this.svg.append('g')
            .attr('class', 'col-headers')
            .selectAll('text')
            .data(dimBValues)
            .join('text')
            .attr('class', drilldownOptions.onColHeaderClick ? 'col-label clickable' : 'col-label')
            .attr('data-testid', d => `analytics-cross-dim-col-header-${d.id}`)
            .attr('x', d => xScale(d.id) + xScale.bandwidth() / 2)
            .attr('y', labelY)
            .attr('text-anchor', 'start')
            .attr('transform', d => `rotate(-45, ${xScale(d.id) + xScale.bandwidth() / 2}, ${labelY})`)
            .attr('fill', _cs.getPropertyValue('--text-secondary').trim())
            .attr('font-size', `${headerFont}px`)
            .style('cursor', drilldownOptions.onColHeaderClick ? 'pointer' : 'default')
            .text(d => this._truncateLabel(d.name, colTruncLen));

        // Add click handler for column headers
        if (drilldownOptions.onColHeaderClick) {
            colHeaders.on('click', (event, d) => {
                drilldownOptions.onColHeaderClick(d.id, d.name);
            });
        }

        // Draw row headers (dimension A values) - clickable for drill-down
        const rowHeaders = this.svg.append('g')
            .attr('class', 'row-headers')
            .selectAll('text')
            .data(dimAValues)
            .join('text')
            .attr('class', drilldownOptions.onRowHeaderClick ? 'row-label clickable' : 'row-label')
            .attr('data-testid', d => `analytics-cross-dim-row-header-${d.id}`)
            .attr('x', this.options.marginLeft - 10)
            .attr('y', d => yScale(d.id) + yScale.bandwidth() / 2)
            .attr('text-anchor', 'end')
            .attr('dominant-baseline', 'middle')
            .attr('fill', _cs.getPropertyValue('--text-secondary').trim())
            .attr('font-size', `${headerFont}px`)
            .style('cursor', drilldownOptions.onRowHeaderClick ? 'pointer' : 'default')
            .text(d => this._truncateLabel(d.name, rowTruncLen));

        // Add click handler for row headers
        if (drilldownOptions.onRowHeaderClick) {
            rowHeaders.on('click', (event, d) => {
                drilldownOptions.onRowHeaderClick(d.id, d.name);
            });
        }

        // Draw cells
        const cellsGroup = this.svg.append('g');

        dimAValues.forEach(dimA => {
            dimBValues.forEach(dimB => {
                const key = `${dimA.id}-${dimB.id}`;
                const cell = matrixLookup[key];

                const x = xScale(dimB.id);
                const y = yScale(dimA.id);
                const cellWidth = xScale.bandwidth();
                const cellHeight = yScale.bandwidth();

                const hasData = cell && cell.count >= matrixData.min_entries;

                // Draw cell background
                const rect = cellsGroup.append('rect')
                    .attr('data-testid', `analytics-cross-dim-cell-${dimA.id}-${dimB.id}`)
                    .attr('x', x)
                    .attr('y', y)
                    .attr('width', cellWidth)
                    .attr('height', cellHeight)
                    .attr('rx', 4)
                    .attr('fill', hasData ? this.colorScale(cell.count) : this.options.insufficientColor)
                    .attr('class', hasData ? 'heatmap-cell' : 'heatmap-cell insufficient')
                    .style('cursor', hasData ? 'pointer' : 'default')
                    .on('mouseenter', (event) => this._handleMouseEnter(event, dimA, dimB, cell))
                    .on('mouseleave', (event) => this._handleMouseLeave(event));

                if (hasData && this.options.onCellClick) {
                    rect.on('click', () => this._handleCellClick(dimA, dimB, cell));
                }

                // Draw count label
                if (hasData) {
                    cellsGroup.append('text')
                        .attr('data-testid', `analytics-cross-dim-count-${dimA.id}-${dimB.id}`)
                        .attr('x', x + cellWidth / 2)
                        .attr('y', y + cellHeight / 2)
                        .attr('text-anchor', 'middle')
                        .attr('dominant-baseline', 'middle')
                        .attr('fill', cell.count > maxCount * 0.5 ? 'white' : _cs.getPropertyValue('--text-primary').trim())
                        .attr('font-size', `${cellFont}px`)
                        .attr('font-weight', '600')
                        .attr('pointer-events', 'none')
                        .text(cell.count);
                }
            });
        });

        // Add dimension labels
        this.svg.append('text')
            .attr('x', this.options.marginLeft + (width - this.options.marginLeft - this.options.marginRight) / 2)
            .attr('y', Math.round(15 * sf))
            .attr('text-anchor', 'middle')
            .attr('fill', _cs.getPropertyValue('--text-primary').trim())
            .attr('font-size', `${titleFont}px`)
            .attr('font-weight', '600')
            .text(matrixData.dimension_b.name);

        this.svg.append('text')
            .attr('x', Math.round(15 * sf))
            .attr('y', this.options.marginTop + (height - this.options.marginTop - this.options.marginBottom) / 2)
            .attr('text-anchor', 'middle')
            .attr('dominant-baseline', 'middle')
            .attr('transform', `rotate(-90, ${Math.round(15 * sf)}, ${this.options.marginTop + (height - this.options.marginTop - this.options.marginBottom) / 2})`)
            .attr('fill', _cs.getPropertyValue('--text-primary').trim())
            .attr('font-size', `${titleFont}px`)
            .attr('font-weight', '600')
            .text(matrixData.dimension_a.name);
    }

    /**
     * Truncate label text
     * @private
     */
    _truncateLabel(text, maxLength) {
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength - 1) + '...';
    }

    /**
     * Handle mouse enter on cell
     * @private
     */
    _handleMouseEnter(event, dimA, dimB, cell) {
        const _cs = getComputedStyle(document.documentElement);
        const rect = d3.select(event.currentTarget);
        rect.attr('stroke', _cs.getPropertyValue('--text-primary').trim())
            .attr('stroke-width', 2);

        // Show tooltip
        this._showTooltip(event, dimA, dimB, cell);

        if (this.options.onCellHover) {
            this.options.onCellHover({ dimA, dimB, cell }, true);
        }
    }

    /**
     * Handle mouse leave on cell
     * @private
     */
    _handleMouseLeave(event) {
        const rect = d3.select(event.currentTarget);
        rect.attr('stroke', 'none');

        // Hide tooltip
        this._hideTooltip();

        if (this.options.onCellHover) {
            this.options.onCellHover(null, false);
        }
    }

    /**
     * Handle cell click
     * @private
     */
    _handleCellClick(dimA, dimB, cell) {
        if (this.options.onCellClick) {
            this.options.onCellClick({
                dimA: dimA,
                dimB: dimB,
                cell: cell
            });
        }
    }

    /**
     * Show tooltip
     * @private
     */
    _showTooltip(event, dimA, dimB, cell) {
        // Remove existing tooltip
        this._hideTooltip();

        if (!cell) return;

        const tooltip = document.createElement('div');
        tooltip.id = 'heatmap-tooltip';
        tooltip.className = 'heatmap-tooltip';
        tooltip.innerHTML = `
            <div class="tooltip-header">${dimA.name} × ${dimB.name}</div>
            <div class="tooltip-body">
                <div class="tooltip-stat">
                    <span class="tooltip-label">Entries:</span>
                    <span class="tooltip-value">${cell.count}</span>
                </div>
                <div class="tooltip-stat">
                    <span class="tooltip-label">Avg Difficulty:</span>
                    <span class="tooltip-value">${cell.avg_difficulty?.toFixed(1) || '-'}</span>
                </div>
            </div>
            <div class="tooltip-footer">Click to view entries</div>
        `;

        document.body.appendChild(tooltip);

        // Position tooltip
        const rect = event.currentTarget.getBoundingClientRect();
        tooltip.style.left = `${rect.left + rect.width / 2 - tooltip.offsetWidth / 2}px`;
        tooltip.style.top = `${rect.top - tooltip.offsetHeight - 8}px`;
    }

    /**
     * Hide tooltip
     * @private
     */
    _hideTooltip() {
        const tooltip = document.getElementById('heatmap-tooltip');
        if (tooltip) {
            tooltip.remove();
        }
    }

    /**
     * Render empty state
     * @private
     */
    _renderEmptyState() {
        this.container.innerHTML = `
            <div class="heatmap-empty">
                <p>No cross-dimension data available</p>
                <p class="heatmap-empty-hint">Add more entries with dimension tags to see the heatmap</p>
            </div>
        `;
    }

    /**
     * Export data as CSV
     * @returns {string} CSV string
     */
    exportAsCSV() {
        if (!this.data || !this.data.matrix) {
            return '';
        }

        const headers = [
            this.data.dimension_a.name,
            this.data.dimension_b.name,
            'Count',
            'Avg Difficulty'
        ];

        const rows = this.data.matrix.map(cell => [
            cell.dim_a_value,
            cell.dim_b_value,
            cell.count,
            cell.avg_difficulty || ''
        ]);

        const csv = [
            headers.join(','),
            ...rows.map(r => r.join(','))
        ].join('\n');

        return csv;
    }

    /**
     * Download the heatmap data as CSV
     */
    downloadCSV() {
        const csv = this.exportAsCSV();
        if (!csv) return;

        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.setAttribute('href', url);
        link.setAttribute('download', 'cross_dimension_analysis.csv');
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    /**
     * Create the color legend
     * @param {string} containerId - ID of the legend container
     */
    renderLegend(containerId) {
        const container = document.getElementById(containerId);
        if (!container || !this.data) return;

        const maxCount = d3.max(this.data.matrix, d => d.count) || 1;

        container.innerHTML = `
            <div class="heatmap-legend">
                <span class="legend-label">Fewer mistakes</span>
                <div class="legend-gradient" style="background: linear-gradient(to right, ${this.options.minColor}, ${this.options.midColor}, ${this.options.maxColor})"></div>
                <span class="legend-label">More mistakes</span>
                <span class="legend-insufficient">
                    <span class="legend-color-box" style="background: ${this.options.insufficientColor}"></span>
                    Insufficient data
                </span>
            </div>
        `;
    }
}

// Export for use in other modules
window.DimensionHeatmap = DimensionHeatmap;
