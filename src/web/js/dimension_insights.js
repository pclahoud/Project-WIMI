/**
 * WIMI Dimension Insights Component
 * Phase 7.6 - Interaction effects, study recommendations, and triple dimension analysis
 */

class DimensionInsights {
    /**
     * Create a dimension insights controller
     * @param {string} containerId - ID of the container element
     * @param {object} options - Configuration options
     */
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);

        this.options = {
            maxInteractionEffects: options.maxInteractionEffects || 5,
            maxRecommendations: options.maxRecommendations || 5,
            maxTripleCombinations: options.maxTripleCombinations || 10,
            onCombinationClick: options.onCombinationClick || null
        };

        this.data = {
            interactions: [],
            recommendations: [],
            tripleDimensions: []
        };
    }

    /**
     * Render interaction effects cards
     * @param {Array} data - Interaction effects data
     */
    renderInteractionEffects(data) {
        this.data.interactions = data || [];

        const container = document.getElementById(`${this.containerId}-interactions`);
        if (!container) return;

        if (!data || data.length === 0) {
            container.innerHTML = `
                <div class="insights-empty">
                    <p>No significant interaction effects detected</p>
                    <p class="insights-empty-hint">Interaction effects appear when certain dimension combinations show unexpected patterns</p>
                </div>
            `;
            return;
        }

        const limitedData = data.slice(0, this.options.maxInteractionEffects);

        const cardsHtml = limitedData.map(effect => {
            const isOver = effect.direction === 'over';
            const severityClass = `severity-${effect.severity}`;
            const directionIcon = isOver ? '↑' : '↓';
            const directionText = isOver ? 'More mistakes than expected' : 'Fewer mistakes than expected';
            const percentDiff = Math.abs(effect.interaction * 100).toFixed(0);

            return `
                <div class="interaction-card ${severityClass}">
                    <div class="interaction-header">
                        <span class="interaction-direction ${effect.direction}">${directionIcon}</span>
                        <span class="interaction-combination">${effect.dim_a_value} × ${effect.dim_b_value}</span>
                        <span class="interaction-severity">${effect.severity}</span>
                    </div>
                    <div class="interaction-body">
                        <div class="interaction-comparison">
                            <div class="interaction-expected">
                                <span class="label">Expected</span>
                                <span class="value">${effect.expected}</span>
                            </div>
                            <span class="comparison-arrow">→</span>
                            <div class="interaction-actual">
                                <span class="label">Actual</span>
                                <span class="value">${effect.actual}</span>
                            </div>
                        </div>
                        <div class="interaction-description">
                            ${directionText} (${percentDiff}% difference)
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = `
            <div class="interaction-effects-grid">
                ${cardsHtml}
            </div>
        `;
    }

    /**
     * Render study recommendations
     * @param {Array} data - Study recommendations data
     */
    renderStudyRecommendations(data) {
        this.data.recommendations = data || [];

        const container = document.getElementById(`${this.containerId}-recommendations`);
        if (!container) return;

        if (!data || data.length === 0) {
            container.innerHTML = `
                <div class="insights-empty">
                    <p>No study recommendations available</p>
                    <p class="insights-empty-hint">Recommendations will appear as you log more entries</p>
                </div>
            `;
            return;
        }

        const limitedData = data.slice(0, this.options.maxRecommendations);

        const itemsHtml = limitedData.map((rec, index) => {
            const priorityStars = this._renderPriorityStars(rec.priority_score, data[0].priority_score);
            const difficultyLabel = this._getDifficultyLabel(rec.avg_difficulty);

            return `
                <div class="recommendation-item" data-index="${index}">
                    <div class="recommendation-rank">${index + 1}</div>
                    <div class="recommendation-content">
                        <div class="recommendation-header">
                            <span class="recommendation-combination">${rec.combination}</span>
                            <span class="recommendation-priority">${priorityStars}</span>
                        </div>
                        <div class="recommendation-stats">
                            <span class="stat-item">
                                <span class="stat-label">Mistakes:</span>
                                <span class="stat-value">${rec.count}</span>
                            </span>
                            <span class="stat-item">
                                <span class="stat-label">Difficulty:</span>
                                <span class="stat-value difficulty-${difficultyLabel.toLowerCase()}">${difficultyLabel}</span>
                            </span>
                            <span class="stat-item">
                                <span class="stat-label">Weight:</span>
                                <span class="stat-value">${rec.weight}%</span>
                            </span>
                        </div>
                        <p class="recommendation-text">${rec.recommendation}</p>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = `
            <div class="recommendations-list">
                ${itemsHtml}
            </div>
        `;

        // Add click handlers
        container.querySelectorAll('.recommendation-item').forEach((item, index) => {
            item.addEventListener('click', () => {
                if (this.options.onCombinationClick) {
                    this.options.onCombinationClick(limitedData[index]);
                }
            });
        });
    }

    /**
     * Render triple dimension ranking
     * @param {Array} data - Triple dimension performance data
     */
    renderTripleDimensionRanking(data) {
        this.data.tripleDimensions = data || [];

        const container = document.getElementById(`${this.containerId}-triple`);
        if (!container) return;

        if (!data || data.length === 0) {
            container.innerHTML = `
                <div class="insights-empty">
                    <p>No 3-way combinations available</p>
                    <p class="insights-empty-hint">This requires entries tagged across at least 3 dimensions</p>
                </div>
            `;
            return;
        }

        const limitedData = data.slice(0, this.options.maxTripleCombinations);
        const maxCount = data[0]?.count || 1;

        const rowsHtml = limitedData.map((combo, index) => {
            const barWidth = (combo.count / maxCount * 100).toFixed(1);

            return `
                <div class="triple-row">
                    <div class="triple-rank">${index + 1}</div>
                    <div class="triple-combination">
                        <span class="dim-a">${combo.dim_a_value}</span>
                        <span class="separator">×</span>
                        <span class="dim-b">${combo.dim_b_value}</span>
                        <span class="separator">×</span>
                        <span class="dim-c">${combo.dim_c_value}</span>
                    </div>
                    <div class="triple-bar-container">
                        <div class="triple-bar" style="width: ${barWidth}%"></div>
                    </div>
                    <div class="triple-count">${combo.count}</div>
                    <div class="triple-difficulty">${combo.avg_difficulty?.toFixed(1) || '-'}</div>
                </div>
            `;
        }).join('');

        container.innerHTML = `
            <div class="triple-dimension-table">
                <div class="triple-header">
                    <div class="triple-rank">#</div>
                    <div class="triple-combination">Combination</div>
                    <div class="triple-bar-container">Distribution</div>
                    <div class="triple-count">Count</div>
                    <div class="triple-difficulty">Avg Diff</div>
                </div>
                ${rowsHtml}
            </div>
        `;
    }

    /**
     * Render priority stars based on score
     * @private
     */
    _renderPriorityStars(score, maxScore) {
        const normalizedScore = maxScore > 0 ? score / maxScore : 0;
        const stars = Math.ceil(normalizedScore * 5);
        const filledStars = '★'.repeat(stars);
        const emptyStars = '☆'.repeat(5 - stars);
        return `<span class="priority-stars">${filledStars}${emptyStars}</span>`;
    }

    /**
     * Get difficulty label
     * @private
     */
    _getDifficultyLabel(difficulty) {
        if (!difficulty) return 'Unknown';
        if (difficulty >= 4.5) return 'Very Hard';
        if (difficulty >= 3.5) return 'Hard';
        if (difficulty >= 2.5) return 'Medium';
        if (difficulty >= 1.5) return 'Easy';
        return 'Very Easy';
    }

    /**
     * Render a compact summary of all insights
     * @param {object} allData - Object with interactions, recommendations, tripleDimensions
     */
    renderCompactSummary(allData) {
        const container = document.getElementById(this.containerId);
        if (!container) return;

        const { interactions, recommendations, tripleDimensions } = allData;

        // Count significant findings
        const highInteractions = (interactions || []).filter(i => i.severity === 'high').length;
        const topRecommendation = recommendations?.[0];
        const topTriple = tripleDimensions?.[0];

        let summaryHtml = '<div class="insights-summary">';

        // Interaction effects summary
        if (highInteractions > 0) {
            summaryHtml += `
                <div class="summary-item warning">
                    <span class="summary-icon">⚠️</span>
                    <span class="summary-text">
                        <strong>${highInteractions}</strong> high-impact interaction effect${highInteractions > 1 ? 's' : ''} detected
                    </span>
                </div>
            `;
        }

        // Top recommendation
        if (topRecommendation) {
            summaryHtml += `
                <div class="summary-item info">
                    <span class="summary-icon">📚</span>
                    <span class="summary-text">
                        Focus area: <strong>${topRecommendation.combination}</strong> (${topRecommendation.count} mistakes)
                    </span>
                </div>
            `;
        }

        // Top triple combination
        if (topTriple) {
            summaryHtml += `
                <div class="summary-item">
                    <span class="summary-icon">🎯</span>
                    <span class="summary-text">
                        Most common pattern: <strong>${topTriple.combination}</strong>
                    </span>
                </div>
            `;
        }

        // No insights
        if (!highInteractions && !topRecommendation && !topTriple) {
            summaryHtml += `
                <div class="summary-item neutral">
                    <span class="summary-icon">📊</span>
                    <span class="summary-text">
                        Add more entries to see cross-dimensional insights
                    </span>
                </div>
            `;
        }

        summaryHtml += '</div>';
        container.innerHTML = summaryHtml;
    }

    /**
     * Render a trends chart for a specific dimension
     * @param {string} containerId - Container ID
     * @param {object} trendsData - Temporal trends data
     */
    renderTrendsChart(containerId, trendsData) {
        const container = document.getElementById(containerId);
        if (!container || !trendsData || !trendsData.data || trendsData.data.length === 0) {
            if (container) {
                container.innerHTML = `
                    <div class="trends-empty">
                        <p>No trend data available</p>
                    </div>
                `;
            }
            return;
        }

        // Create simple line chart using SVG
        const width = 400;
        const height = 150;
        const padding = 40;
        const data = trendsData.data;

        const maxCount = Math.max(...data.map(d => d.count), 1);
        const xStep = (width - padding * 2) / Math.max(data.length - 1, 1);

        let pathD = '';
        const points = data.map((d, i) => {
            const x = padding + i * xStep;
            const y = height - padding - (d.count / maxCount * (height - padding * 2));
            return { x, y, count: d.count, week: d.week };
        });

        points.forEach((p, i) => {
            if (i === 0) {
                pathD += `M ${p.x} ${p.y}`;
            } else {
                pathD += ` L ${p.x} ${p.y}`;
            }
        });

        const trendIcon = trendsData.trend === 'increasing' ? '↗' :
                          trendsData.trend === 'decreasing' ? '↘' : '→';
        const trendClass = trendsData.trend === 'increasing' ? 'trend-up' :
                           trendsData.trend === 'decreasing' ? 'trend-down' : 'trend-stable';

        container.innerHTML = `
            <div class="trends-chart">
                <div class="trends-header">
                    <span class="trends-title">${trendsData.dimension_name} Trend</span>
                    <span class="trends-indicator ${trendClass}">${trendIcon} ${trendsData.trend}</span>
                </div>
                <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
                    <path d="${pathD}" fill="none" stroke="var(--color-info, #0ea5e9)" stroke-width="2" />
                    ${points.map(p => `
                        <circle cx="${p.x}" cy="${p.y}" r="4" fill="var(--color-info, #0ea5e9)" />
                    `).join('')}
                </svg>
                <div class="trends-total">Total: ${trendsData.total} entries</div>
            </div>
        `;
    }
}

// Export for use in other modules
window.DimensionInsights = DimensionInsights;
