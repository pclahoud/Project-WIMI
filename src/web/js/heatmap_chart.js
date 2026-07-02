/**
 * WIMI Activity Heatmap Chart
 * GitHub-style activity heatmap visualization using D3.js
 * Phase 6 Stage 7
 */

class ActivityHeatmap {
    /**
     * Create an activity heatmap
     * @param {string} containerId - ID of container element
     * @param {object} options - Configuration options
     */
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        
        if (!this.container) {
            console.error(`Heatmap container #${containerId} not found`);
            return;
        }

        this.options = {
            weeks: options.weeks || 16,
            cellSize: options.cellSize || 12,
            cellGap: options.cellGap || 3,
            cellRadius: options.cellRadius || 2,
            colors: options.colors || [
                '#ebedf0',  // level 0 - no activity
                '#9be9a8',  // level 1 - light
                '#40c463',  // level 2 - medium
                '#30a14e',  // level 3 - high
                '#216e39'   // level 4 - very high
            ],
            dayLabels: options.dayLabels || ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
            monthLabels: options.monthLabels || ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
            showDayLabels: options.showDayLabels !== false,
            showMonthLabels: options.showMonthLabels !== false,
            showLegend: options.showLegend !== false,
            onCellClick: options.onCellClick || null,
            onCellHover: options.onCellHover || null,
            ...options
        };

        this.data = null;
        this.svg = null;
    }

    /**
     * Render the heatmap with data
     * @param {object} data - Heatmap data from API
     */
    render(data) {
        if (!this.container) return;
        
        this.data = data;
        this.container.innerHTML = '';

        if (!data || !data.days || data.days.length === 0) {
            this._renderEmptyState();
            return;
        }

        const { cellSize, cellGap, dayLabels, showDayLabels, showMonthLabels, showLegend } = this.options;
        
        // Calculate dimensions
        const dayLabelWidth = showDayLabels ? 30 : 0;
        const monthLabelHeight = showMonthLabels ? 20 : 0;
        const legendHeight = showLegend ? 30 : 0;
        
        // Calculate number of weeks from data
        const numWeeks = Math.ceil(data.days.length / 7);
        
        const width = dayLabelWidth + numWeeks * (cellSize + cellGap) + 10;
        const height = monthLabelHeight + 7 * (cellSize + cellGap) + legendHeight + 10;

        // Create SVG
        this.svg = d3.select(this.container)
            .append('svg')
            .attr('width', width)
            .attr('height', height)
            .attr('class', 'activity-heatmap');

        // Create main group
        const g = this.svg.append('g')
            .attr('transform', `translate(${dayLabelWidth}, ${monthLabelHeight})`);

        // Render day labels (Sun, Mon, etc.)
        if (showDayLabels) {
            this._renderDayLabels(monthLabelHeight);
        }

        // Render month labels
        if (showMonthLabels) {
            this._renderMonthLabels(data.days, dayLabelWidth);
        }

        // Render cells
        this._renderCells(g, data.days);

        // Render legend
        if (showLegend) {
            this._renderLegend(dayLabelWidth, monthLabelHeight + 7 * (cellSize + cellGap) + 15);
        }
    }

    /**
     * Render day labels (Sun, Mon, etc.)
     */
    _renderDayLabels(offsetY) {
        const _cs = getComputedStyle(document.documentElement);
        const { cellSize, cellGap, dayLabels } = this.options;

        // Only show Mon, Wed, Fri to save space
        const showIndices = [1, 3, 5];

        const labelGroup = this.svg.append('g')
            .attr('class', 'day-labels');

        showIndices.forEach(i => {
            labelGroup.append('text')
                .attr('data-testid', `analytics-heatmap-day-${i}`)
                .attr('x', 0)
                .attr('y', offsetY + i * (cellSize + cellGap) + cellSize / 2 + 3)
                .attr('font-size', '10px')
                .attr('fill', _cs.getPropertyValue('--text-secondary').trim())
                .attr('text-anchor', 'start')
                .text(dayLabels[i]);
        });
    }

    /**
     * Render month labels
     */
    _renderMonthLabels(days, offsetX) {
        const _cs = getComputedStyle(document.documentElement);
        const { cellSize, cellGap, monthLabels } = this.options;

        const labelGroup = this.svg.append('g')
            .attr('class', 'month-labels');

        let currentMonth = null;
        let monthPositions = [];

        days.forEach((day, i) => {
            const date = new Date(day.date);
            const month = date.getMonth();
            const weekIndex = Math.floor(i / 7);

            if (month !== currentMonth) {
                monthPositions.push({
                    month: month,
                    x: offsetX + weekIndex * (cellSize + cellGap)
                });
                currentMonth = month;
            }
        });

        // Only show labels that have enough space
        monthPositions.forEach((pos, i) => {
            const nextPos = monthPositions[i + 1];
            const hasSpace = !nextPos || (nextPos.x - pos.x) > 30;

            if (hasSpace) {
                labelGroup.append('text')
                    .attr('data-testid', `analytics-heatmap-month-${monthLabels[pos.month]}`)
                    .attr('x', pos.x)
                    .attr('y', 12)
                    .attr('font-size', '10px')
                    .attr('fill', _cs.getPropertyValue('--text-secondary').trim())
                    .text(monthLabels[pos.month]);
            }
        });
    }

    /**
     * Render heatmap cells
     */
    _renderCells(g, days) {
        const _cs = getComputedStyle(document.documentElement);
        const { cellSize, cellGap, cellRadius, colors, onCellClick, onCellHover } = this.options;

        const cells = g.selectAll('.heatmap-cell')
            .data(days)
            .enter()
            .append('rect')
            .attr('class', 'heatmap-cell')
            .attr('data-testid', d => `analytics-heatmap-cell-${d.date}`)
            .attr('x', (d, i) => Math.floor(i / 7) * (cellSize + cellGap))
            .attr('y', (d, i) => (i % 7) * (cellSize + cellGap))
            .attr('width', cellSize)
            .attr('height', cellSize)
            .attr('rx', cellRadius)
            .attr('ry', cellRadius)
            .attr('fill', d => colors[Math.min(d.level, colors.length - 1)])
            .style('cursor', 'pointer');

        // Add tooltips
        cells.append('title')
            .text(d => {
                const date = new Date(d.date);
                const dateStr = date.toLocaleDateString('en-US', { 
                    weekday: 'short', 
                    month: 'short', 
                    day: 'numeric',
                    year: 'numeric'
                });
                return `${d.count} ${d.count === 1 ? 'entry' : 'entries'} on ${dateStr}`;
            });

        // Add hover effects
        cells.on('mouseenter', function(event, d) {
            d3.select(this)
                .attr('stroke', _cs.getPropertyValue('--text-primary').trim())
                .attr('stroke-width', 1);
            
            if (onCellHover) {
                onCellHover(d, true, event);
            }
        })
        .on('mouseleave', function(event, d) {
            d3.select(this)
                .attr('stroke', 'none');
            
            if (onCellHover) {
                onCellHover(d, false, event);
            }
        });

        // Add click handler
        if (onCellClick) {
            cells.on('click', (event, d) => onCellClick(d, event));
        }
    }

    /**
     * Render legend
     */
    _renderLegend(offsetX, offsetY) {
        const _cs = getComputedStyle(document.documentElement);
        const { colors, cellSize } = this.options;
        const legendCellSize = 10;
        const legendGap = 3;

        const legend = this.svg.append('g')
            .attr('class', 'heatmap-legend')
            .attr('transform', `translate(${offsetX}, ${offsetY})`);

        // "Less" label
        legend.append('text')
            .attr('x', 0)
            .attr('y', legendCellSize - 2)
            .attr('font-size', '10px')
            .attr('fill', _cs.getPropertyValue('--text-secondary').trim())
            .text('Less');

        // Color cells
        colors.forEach((color, i) => {
            legend.append('rect')
                .attr('x', 30 + i * (legendCellSize + legendGap))
                .attr('y', 0)
                .attr('width', legendCellSize)
                .attr('height', legendCellSize)
                .attr('rx', 2)
                .attr('fill', color);
        });

        // "More" label
        legend.append('text')
            .attr('x', 35 + colors.length * (legendCellSize + legendGap))
            .attr('y', legendCellSize - 2)
            .attr('font-size', '10px')
            .attr('fill', _cs.getPropertyValue('--text-secondary').trim())
            .text('More');
    }

    /**
     * Render empty state
     */
    _renderEmptyState() {
        this.container.innerHTML = `
            <div class="heatmap-empty">
                <p>No activity data available</p>
                <p class="heatmap-empty-hint">Start logging mistakes to see your activity!</p>
            </div>
        `;
    }

    /**
     * Update heatmap with new data
     * @param {object} data - New heatmap data
     */
    update(data) {
        this.render(data);
    }

    /**
     * Resize heatmap
     */
    resize() {
        if (this.data) {
            this.render(this.data);
        }
    }

    /**
     * Get color for a given level
     * @param {number} level - Activity level (0-4)
     * @returns {string} Color hex code
     */
    getColorForLevel(level) {
        return this.options.colors[Math.min(level, this.options.colors.length - 1)];
    }
}

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ActivityHeatmap;
}
