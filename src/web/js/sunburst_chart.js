/**
 * WIMI Sunburst Chart Component
 * D3.js-based hierarchical visualization for subject mistake distribution
 * Phase 6 - Analytics Dashboard Enhancement
 */

class SunburstChart {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        
        // Default options
        this.options = {
            width: options.width || 340,
            height: options.height || 340,
            innerRadiusRatio: options.innerRadiusRatio || 0.35,
            colors: options.colors || [
                '#ef4444', // Red
                '#f59e0b', // Orange  
                '#10b981', // Green
                '#0ea5e9', // Blue
                '#8b5cf6', // Purple
                '#ec4899', // Pink
                '#14b8a6', // Teal
                '#f97316', // Orange bright
                '#6366f1', // Indigo
                '#84cc16'  // Lime
            ],
            onSegmentClick: options.onSegmentClick || null,
            onSegmentHover: options.onSegmentHover || null,
            centerLabelId: options.centerLabelId || 'totalEntriesCenter',
            centerTextId: options.centerTextId || 'centerSubjectName',
            breadcrumbId: options.breadcrumbId || 'sunburstBreadcrumb'
        };
        
        this.svg = null;
        this.root = null;
        this.currentRoot = null;
        this.arc = null;
        this.colorScale = null;
        this.totalMistakes = 0;
        
        this._init();
    }
    
    _init() {
        // Clear existing content
        this.container.innerHTML = '';
        
        const { width, height } = this.options;
        const radius = Math.min(width, height) / 2;
        
        // Create SVG
        this.svg = d3.select(`#${this.containerId}`)
            .append('svg')
            .attr('width', width)
            .attr('height', height)
            .attr('viewBox', [-width / 2, -height / 2, width, height])
            .style('font', '12px sans-serif');
        
        // Create arc generator
        this.arc = d3.arc()
            .startAngle(d => d.x0)
            .endAngle(d => d.x1)
            .padAngle(d => Math.min((d.x1 - d.x0) / 2, 0.005))
            .padRadius(radius * this.options.innerRadiusRatio)
            .innerRadius(d => {
                const innerRadius = radius * this.options.innerRadiusRatio;
                return d.depth === 0 ? 0 : innerRadius + d.y0 * (radius - innerRadius);
            })
            .outerRadius(d => {
                const innerRadius = radius * this.options.innerRadiusRatio;
                return innerRadius + d.y1 * (radius - innerRadius) - 1;
            });
        
        // Create color scale
        this.colorScale = d3.scaleOrdinal(this.options.colors);
    }
    
    /**
     * Render the sunburst chart with hierarchical data
     * @param {Object} data - Hierarchical data with name, value, and children properties
     */
    render(data) {
        if (!data || !data.children || data.children.length === 0) {
            this._renderEmptyState();
            return;
        }
        
        // Clear previous content
        this.svg.selectAll('*').remove();
        
        // Compute total mistakes
        this.totalMistakes = data.value || 0;
        
        // Create hierarchy
        this.root = d3.hierarchy(data)
            .sum(d => {
                // For leaf nodes, use the direct_mistakes value
                // For parent nodes, the value is calculated by d3.hierarchy.sum()
                if (!d.children || d.children.length === 0) {
                    return d.direct_mistakes || d.value || 0;
                }
                return d.direct_mistakes || 0;
            })
            .sort((a, b) => b.value - a.value);
        
        // Create partition layout
        const partition = d3.partition()
            .size([2 * Math.PI, 1]);
        
        partition(this.root);
        
        this.currentRoot = this.root;
        
        // Filter to show only first few depth levels initially
        const maxDepth = 3;
        
        // Create path elements
        const path = this.svg.append('g')
            .selectAll('path')
            .data(this.root.descendants().filter(d => d.depth <= maxDepth && d.depth > 0))
            .join('path')
            .attr('data-testid', d => `analytics-sunburst-arc-${d.data.id}`)
            .attr('fill', d => this._getColor(d))
            .attr('fill-opacity', d => this._getOpacity(d))
            .attr('d', this.arc)
            .style('cursor', 'pointer')
            .on('click', (event, d) => this._handleClick(event, d))
            .on('mouseenter', (event, d) => this._handleMouseEnter(event, d))
            .on('mouseleave', (event, d) => this._handleMouseLeave(event, d));

        // Add text labels for larger segments
        this._addLabels(maxDepth);
        
        // Update center label
        this._updateCenterLabel(this.root);
        
        // Update breadcrumb
        this._updateBreadcrumb(this.root);
    }
    
    _getColor(d) {
        // Get root-level ancestor for consistent coloring
        let ancestor = d;
        while (ancestor.depth > 1) ancestor = ancestor.parent;
        
        // Use the ancestor's data index for color
        if (ancestor.parent && ancestor.parent.children) {
            const index = ancestor.parent.children.indexOf(ancestor);
            return this.colorScale(index);
        }
        return this.colorScale(0);
    }
    
    _getOpacity(d) {
        // Darker for nodes closer to root, lighter for deeper nodes
        const baseOpacity = 0.9;
        const depthFactor = 0.15;
        return Math.max(0.4, baseOpacity - (d.depth - 1) * depthFactor);
    }
    
    _addLabels(maxDepth) {
        const { width, height } = this.options;
        const radius = Math.min(width, height) / 2;

        // Add text labels only to segments large enough
        const label = this.svg.append('g')
            .attr('pointer-events', 'none')
            .attr('text-anchor', 'middle')
            .selectAll('text')
            .data(this.root.descendants().filter(d => {
                // Show label if segment is large enough
                const angle = d.x1 - d.x0;
                return d.depth > 0 && d.depth <= maxDepth && angle > 0.15;
            }))
            .join('text')
            .attr('data-testid', d => `analytics-sunburst-label-${d.data.id}`)
            .attr('transform', d => {
                const x = (d.x0 + d.x1) / 2;
                const y = (d.y0 + d.y1) / 2;
                const innerRadius = radius * this.options.innerRadiusRatio;
                const r = innerRadius + y * (radius - innerRadius);
                const angle = x - Math.PI / 2;
                return `
                    rotate(${angle * 180 / Math.PI})
                    translate(${r}, 0)
                    rotate(${angle > Math.PI / 2 && angle < 3 * Math.PI / 2 ? 180 : 0})
                `;
            })
            .attr('dy', '0.35em')
            .attr('fill', '#fff')
            .attr('font-size', d => d.depth === 1 ? '11px' : '10px')
            .attr('font-weight', d => d.depth === 1 ? '600' : '400')
            .text(d => this._truncateLabel(d.data.name, d.x1 - d.x0));
    }
    
    _truncateLabel(text, arcAngle) {
        // Estimate max characters based on arc angle
        const maxChars = Math.floor(arcAngle * 15);
        if (text.length <= maxChars) return text;
        return text.substring(0, maxChars - 1) + '…';
    }
    
    _handleClick(event, d) {
        event.stopPropagation();
        
        // If clicking on a node with children, zoom into it
        if (d.children && d.children.length > 0) {
            this._zoomTo(d);
        }
        
        // Call external click handler if provided
        if (this.options.onSegmentClick && d.data.id) {
            this.options.onSegmentClick(d.data);
        }
    }
    
    _zoomTo(node) {
        this.currentRoot = node;
        
        const { width, height } = this.options;
        const radius = Math.min(width, height) / 2;
        
        // Create new partition centered on the clicked node
        const newRoot = d3.hierarchy(node.data)
            .sum(d => {
                if (!d.children || d.children.length === 0) {
                    return d.direct_mistakes || d.value || 0;
                }
                return d.direct_mistakes || 0;
            })
            .sort((a, b) => b.value - a.value);
        
        const partition = d3.partition()
            .size([2 * Math.PI, 1]);
        
        partition(newRoot);
        
        // Clear and re-render
        this.svg.selectAll('*').remove();
        
        const maxDepth = 3;
        
        // Create path elements
        const path = this.svg.append('g')
            .selectAll('path')
            .data(newRoot.descendants().filter(d => d.depth <= maxDepth && d.depth > 0))
            .join('path')
            .attr('data-testid', d => `analytics-sunburst-arc-${d.data.id}`)
            .attr('fill', d => {
                // Use consistent colors based on original hierarchy
                let ancestor = d;
                while (ancestor.depth > 1) ancestor = ancestor.parent;
                if (ancestor.parent && ancestor.parent.children) {
                    const index = ancestor.parent.children.indexOf(ancestor);
                    return this.colorScale(index);
                }
                return this.colorScale(0);
            })
            .attr('fill-opacity', d => this._getOpacity(d))
            .attr('d', this.arc)
            .style('cursor', 'pointer')
            .on('click', (event, d) => this._handleClick(event, d))
            .on('mouseenter', (event, d) => this._handleMouseEnter(event, d))
            .on('mouseleave', (event, d) => this._handleMouseLeave(event, d));
        
        path.append('title')
            .text(d => `${this._getAncestorPath(d)}\n${d.value} mistake${d.value !== 1 ? 's' : ''}`);
        
        this._addLabelsForNode(newRoot, maxDepth);
        this._updateCenterLabel(newRoot);
        this._updateBreadcrumb(node);
    }
    
    _addLabelsForNode(root, maxDepth) {
        const { width, height } = this.options;
        const radius = Math.min(width, height) / 2;
        
        this.svg.append('g')
            .attr('pointer-events', 'none')
            .attr('text-anchor', 'middle')
            .selectAll('text')
            .data(root.descendants().filter(d => {
                const angle = d.x1 - d.x0;
                return d.depth > 0 && d.depth <= maxDepth && angle > 0.15;
            }))
            .join('text')
            .attr('data-testid', d => `analytics-sunburst-label-${d.data.id}`)
            .attr('transform', d => {
                const x = (d.x0 + d.x1) / 2;
                const y = (d.y0 + d.y1) / 2;
                const innerRadius = radius * this.options.innerRadiusRatio;
                const r = innerRadius + y * (radius - innerRadius);
                const angle = x - Math.PI / 2;
                return `
                    rotate(${angle * 180 / Math.PI})
                    translate(${r}, 0)
                    rotate(${angle > Math.PI / 2 && angle < 3 * Math.PI / 2 ? 180 : 0})
                `;
            })
            .attr('dy', '0.35em')
            .attr('fill', '#fff')
            .attr('font-size', d => d.depth === 1 ? '11px' : '10px')
            .attr('font-weight', d => d.depth === 1 ? '600' : '400')
            .text(d => this._truncateLabel(d.data.name, d.x1 - d.x0));
    }
    
    _handleMouseEnter(event, d) {
        // Highlight the segment
        d3.select(event.currentTarget)
            .attr('fill-opacity', 1)
            .attr('stroke', '#fff')
            .attr('stroke-width', 2);
        
        // Update center label to show hovered segment
        this._updateCenterLabel(d);
        
        if (this.options.onSegmentHover) {
            this.options.onSegmentHover(d.data, true);
        }
    }
    
    _handleMouseLeave(event, d) {
        // Reset highlight
        d3.select(event.currentTarget)
            .attr('fill-opacity', this._getOpacity(d))
            .attr('stroke', 'none');
        
        // Reset center label to current root
        this._updateCenterLabel(this.currentRoot);
        
        if (this.options.onSegmentHover) {
            this.options.onSegmentHover(d.data, false);
        }
    }
    
    _updateCenterLabel(node) {
        const centerNumber = document.getElementById(this.options.centerLabelId);
        const centerText = document.getElementById(this.options.centerTextId);
        
        if (centerNumber) {
            centerNumber.textContent = node.value || 0;
        }
        
        if (centerText) {
            const name = node.data ? node.data.name : 'Total';
            centerText.textContent = name === this.root?.data?.name ? 'Total' : name;
        }
    }
    
    _updateBreadcrumb(node) {
        const breadcrumb = document.getElementById(this.options.breadcrumbId);
        if (!breadcrumb) return;
        
        // Build path from root to current node
        const path = [];
        let current = node;
        while (current) {
            path.unshift(current);
            current = current.parent;
        }
        
        // Clear existing breadcrumb
        breadcrumb.innerHTML = '';
        
        // If at root, show nothing
        if (path.length <= 1) {
            return;
        }
        
        // Create breadcrumb elements
        path.forEach((n, i) => {
            if (i > 0) {
                const separator = document.createElement('span');
                separator.className = 'breadcrumb-separator';
                separator.textContent = ' › ';
                breadcrumb.appendChild(separator);
            }
            
            const item = document.createElement('span');
            item.className = 'breadcrumb-item';
            item.textContent = n.data.name;
            
            // Make previous levels clickable to zoom back
            if (i < path.length - 1) {
                item.classList.add('clickable');
                item.addEventListener('click', () => {
                    if (i === 0) {
                        // Go back to root
                        this.render(this.root.data);
                    } else {
                        this._zoomTo(path[i]);
                    }
                });
            }
            
            breadcrumb.appendChild(item);
        });
    }
    
    _getAncestorPath(d) {
        const path = [];
        let current = d;
        while (current) {
            path.unshift(current.data.name);
            current = current.parent;
        }
        return path.join(' › ');
    }
    
    _renderEmptyState() {
        const _cs = getComputedStyle(document.documentElement);
        const { width, height } = this.options;
        const radius = Math.min(width, height) / 2;
        const innerRadius = radius * this.options.innerRadiusRatio;

        // Clear existing content
        this.svg.selectAll('*').remove();

        // Draw empty ring
        const emptyArc = d3.arc()
            .innerRadius(innerRadius)
            .outerRadius(radius - 10)
            .startAngle(0)
            .endAngle(2 * Math.PI);

        this.svg.append('path')
            .attr('d', emptyArc)
            .attr('fill', _cs.getPropertyValue('--bg-tertiary').trim());

        // Add "No data" text
        this.svg.append('text')
            .attr('text-anchor', 'middle')
            .attr('dy', '0.35em')
            .attr('fill', _cs.getPropertyValue('--text-muted').trim())
            .attr('font-size', '14px')
            .text('No data yet');
        
        // Update center label
        const centerNumber = document.getElementById(this.options.centerLabelId);
        const centerText = document.getElementById(this.options.centerTextId);
        
        if (centerNumber) centerNumber.textContent = '0';
        if (centerText) centerText.textContent = 'Total';
        
        // Clear breadcrumb
        const breadcrumb = document.getElementById(this.options.breadcrumbId);
        if (breadcrumb) breadcrumb.innerHTML = '';
    }
    
    /**
     * Reset view to root level
     */
    resetView() {
        if (this.root) {
            this.render(this.root.data);
        }
    }
    
    /**
     * Resize the chart
     * @param {number} width - New width
     * @param {number} height - New height
     */
    resize(width, height) {
        this.options.width = width;
        this.options.height = height;
        this._init();
        if (this.root) {
            this.render(this.root.data);
        }
    }
}

// Export for use in other modules
window.SunburstChart = SunburstChart;
