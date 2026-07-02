/**
 * WIMI Source Comparison Chart Component
 * D3.js multi-line chart for source performance over time
 * Phase 6 Stage 10
 */

class SourceComparisonChart {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        
        if (!this.container) {
            console.error(`Source comparison chart container #${containerId} not found`);
            return;
        }

        this.options = {
            height: options.height || 280,
            margin: { top: 20, right: 120, bottom: 40, left: 50 },
            colors: ['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
            ...options
        };

        this.data = null;
        this.svg = null;
    }

    render(data) {
        if (!this.container || !data) return;

        const _cs = getComputedStyle(document.documentElement);

        this.data = data;
        this.container.innerHTML = '';

        if (!data.timeline || data.timeline.length === 0) {
            this.container.innerHTML = '<div class="chart-empty"><p>No source data available</p></div>';
            return;
        }

        const containerWidth = this.container.clientWidth || 600;
        const width = containerWidth - this.options.margin.left - this.options.margin.right;
        const height = this.options.height - this.options.margin.top - this.options.margin.bottom;

        const sourceNames = data.sources.map(s => s.source_name);
        
        const lineData = sourceNames.map((sourceName, i) => ({
            name: sourceName,
            color: this.options.colors[i % this.options.colors.length],
            values: data.timeline.map(t => ({
                label: t.label,
                count: t.sources[sourceName] || 0
            }))
        }));

        const xScale = d3.scalePoint()
            .domain(data.timeline.map(t => t.label))
            .range([0, width])
            .padding(0.5);

        const maxCount = d3.max(lineData, d => d3.max(d.values, v => v.count)) || 10;
        const yScale = d3.scaleLinear()
            .domain([0, maxCount * 1.1])
            .range([height, 0]);

        this.svg = d3.select(this.container)
            .append('svg')
            .attr('width', width + this.options.margin.left + this.options.margin.right)
            .attr('height', height + this.options.margin.top + this.options.margin.bottom)
            .append('g')
            .attr('transform', `translate(${this.options.margin.left},${this.options.margin.top})`);

        // Grid lines
        this.svg.append('g')
            .attr('class', 'grid')
            .call(d3.axisLeft(yScale).ticks(5).tickSize(-width).tickFormat(''))
            .style('stroke', _cs.getPropertyValue('--border-color').trim())
            .style('stroke-dasharray', '2,2');

        // Axes
        this.svg.append('g')
            .attr('transform', `translate(0,${height})`)
            .call(d3.axisBottom(xScale))
            .selectAll('text')
            .style('font-size', '11px')
            .style('fill', _cs.getPropertyValue('--text-muted').trim());

        this.svg.append('g')
            .call(d3.axisLeft(yScale).ticks(5))
            .selectAll('text')
            .style('font-size', '11px')
            .style('fill', _cs.getPropertyValue('--text-muted').trim());

        // Line generator
        const line = d3.line()
            .x(d => xScale(d.label))
            .y(d => yScale(d.count))
            .curve(d3.curveMonotoneX);

        // Draw lines and points
        lineData.forEach(source => {
            this.svg.append('path')
                .datum(source.values)
                .attr('fill', 'none')
                .attr('stroke', source.color)
                .attr('stroke-width', 2.5)
                .attr('d', line);

            this.svg.selectAll(`.point-${source.name.replace(/\W/g, '')}`)
                .data(source.values)
                .enter()
                .append('circle')
                .attr('cx', d => xScale(d.label))
                .attr('cy', d => yScale(d.count))
                .attr('r', 4)
                .attr('fill', source.color)
                .attr('stroke', _cs.getPropertyValue('--bg-primary').trim())
                .attr('stroke-width', 2);
        });

        // Legend
        const legend = this.svg.append('g')
            .attr('transform', `translate(${width + 15}, 0)`);

        lineData.forEach((source, i) => {
            const item = legend.append('g').attr('transform', `translate(0, ${i * 22})`);
            item.append('line').attr('x1', 0).attr('y1', 8).attr('x2', 20).attr('y2', 8)
                .attr('stroke', source.color).attr('stroke-width', 2.5);
            item.append('circle').attr('cx', 10).attr('cy', 8).attr('r', 3).attr('fill', source.color);
            item.append('text').attr('x', 26).attr('y', 12)
                .style('font-size', '11px').style('fill', _cs.getPropertyValue('--text-secondary').trim())
                .text(source.name.length > 10 ? source.name.slice(0, 10) + '…' : source.name);
        });
    }

    update(data) {
        this.render(data);
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = SourceComparisonChart;
}
