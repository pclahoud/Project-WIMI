/**
 * Time vs Difficulty Analysis Component
 *
 * Displays average time by difficulty level with bar chart
 * and correlation analysis with insights
 */

class TimeDifficultyAnalysis {
    constructor(containerId, api) {
        this.container = document.getElementById(containerId);
        this.api = api;
        this.data = null;

        if (!this.container) {
            console.error(`Container #${containerId} not found`);
            return;
        }
    }

    /**
     * Load and render time vs difficulty analysis
     * @param {number|null} examContextId - Optional exam context filter
     */
    async load(examContextId = null) {
        console.log('[TimeDifficultyAnalysis] Starting load with examContextId:', examContextId);
        
        try {
            console.log('[TimeDifficultyAnalysis] Calling API.getTimeVsDifficultyAnalysis...');
            
            // API returns data directly, not wrapped in {success, data}
            const data = await this.api.getTimeVsDifficultyAnalysis({ examContextId });
            
            console.log('[TimeDifficultyAnalysis] Data received:', data);

            if (!data || typeof data !== 'object') {
                console.error('[TimeDifficultyAnalysis] Invalid data received:', data);
                this.renderError('Invalid data received from server');
                return;
            }

            this.data = data;
            
            console.log('[TimeDifficultyAnalysis] Calling render...');
            this.render();
            console.log('[TimeDifficultyAnalysis] Render complete');

        } catch (error) {
            console.error('[TimeDifficultyAnalysis] Exception caught:', error);
            console.error('[TimeDifficultyAnalysis] Error stack:', error.stack);
            this.renderError(`Failed to load analysis: ${error.message}`);
        }
    }

    /**
     * Render the complete time vs difficulty section
     */
    render() {
        if (!this.data || !this.data.avg_time_by_difficulty) {
            this.renderEmpty();
            return;
        }

        this.container.innerHTML = `
            <div class="time-difficulty-layout">
                <div class="time-bars-container">
                    <h3 class="subsection-title">Average Time by Difficulty</h3>
                    <div id="timeBars"></div>
                </div>
                <div class="correlation-container">
                    <h3 class="subsection-title">Correlation Analysis</h3>
                    <div id="correlationAnalysis"></div>
                </div>
            </div>
        `;

        this.renderTimeBars();
        this.renderCorrelationAnalysis();
    }

    /**
     * Render horizontal bar chart showing average time by difficulty
     */
    renderTimeBars() {
        const barsContainer = document.getElementById('timeBars');
        if (!barsContainer) return;

        const avgTimeByDifficulty = this.data.avg_time_by_difficulty;

        if (Object.keys(avgTimeByDifficulty).length === 0) {
            barsContainer.innerHTML = '<p class="empty-message">No time data available</p>';
            return;
        }

        // Find max time for scaling
        const maxTime = Math.max(...Object.values(avgTimeByDifficulty).map(d => d.avg_seconds));

        // Difficulty indicators
        const difficultyIcons = {
            1: '●',
            2: '●●',
            3: '●●●',
            4: '●●●●',
            5: '●●●●●'
        };

        // Generate bars HTML
        let html = '<div class="time-bars-list">';

        for (let difficulty = 1; difficulty <= 5; difficulty++) {
            const diffData = avgTimeByDifficulty[difficulty];

            if (!diffData) {
                // No data for this difficulty level
                html += `
                    <div class="time-bar-row">
                        <div class="time-bar-label">
                            <span class="difficulty-icon">${difficultyIcons[difficulty]}</span>
                            <span class="difficulty-name">Level ${difficulty}</span>
                        </div>
                        <div class="time-bar-value no-data">No data</div>
                    </div>
                `;
                continue;
            }

            const avgSeconds = diffData.avg_seconds;
            const count = diffData.count;
            const label = diffData.label;
            const barWidth = (avgSeconds / maxTime) * 100;

            // Format time display
            const timeDisplay = this.formatTime(avgSeconds);

            // Check for warning (e.g., Hard taking less time than Medium)
            let warningClass = '';
            if (difficulty === 4 && avgTimeByDifficulty[3]) {
                // Hard vs Medium
                if (avgSeconds < avgTimeByDifficulty[3].avg_seconds * 0.9) {
                    warningClass = 'warning-bar';
                }
            }

            html += `
                <div class="time-bar-row ${warningClass}">
                    <div class="time-bar-label">
                        <span class="difficulty-icon">${difficultyIcons[difficulty]}</span>
                        <span class="difficulty-name">${label}</span>
                    </div>
                    <div class="time-bar-graph">
                        <div class="time-bar-fill" style="width: ${barWidth}%"></div>
                    </div>
                    <div class="time-bar-value">
                        ${timeDisplay}
                        ${warningClass ? '<span class="warning-icon">⚠️</span>' : ''}
                    </div>
                </div>
            `;
        }

        html += '</div>';

        // Add footer with summary
        const totalWithTime = this.data.entries_with_time || 0;
        const totalEntries = this.data.total_entries || 0;
        const percentageWithTime = totalEntries > 0 ? Math.round((totalWithTime / totalEntries) * 100) : 0;

        html += `
            <div class="time-bars-footer">
                <small>${totalWithTime} of ${totalEntries} entries (${percentageWithTime}%) have time data</small>
            </div>
        `;

        barsContainer.innerHTML = html;
    }

    /**
     * Render correlation analysis section with insights
     */
    renderCorrelationAnalysis() {
        const analysisContainer = document.getElementById('correlationAnalysis');
        if (!analysisContainer) return;

        const correlation = this.data.correlation || 0;
        const strength = this.data.correlation_strength || 'Unknown';
        const insights = this.data.insights || [];

        // Determine correlation description
        let corrDescription = '';
        let corrClass = '';

        if (correlation >= 0.6) {
            corrDescription = 'Positive correlation - you spend more time on harder questions';
            corrClass = 'correlation-good';
        } else if (correlation >= 0.3) {
            corrDescription = 'Moderate correlation - some alignment with difficulty';
            corrClass = 'correlation-moderate';
        } else if (correlation >= -0.3) {
            corrDescription = 'Weak correlation - time not aligned with difficulty';
            corrClass = 'correlation-weak';
        } else {
            corrDescription = 'Negative correlation - spending less time on harder questions';
            corrClass = 'correlation-bad';
        }

        let html = `
            <div class="correlation-score ${corrClass}">
                <div class="correlation-value">${correlation.toFixed(2)}</div>
                <div class="correlation-strength">${strength} Correlation</div>
            </div>
            <div class="correlation-description">
                ${corrDescription}
            </div>
        `;

        // Render insights
        if (insights.length > 0) {
            html += '<div class="correlation-insights">';

            insights.forEach(insight => {
                const iconMap = {
                    'success': '✓',
                    'warning': '⚠️',
                    'info': '💡'
                };

                const icon = iconMap[insight.type] || '•';
                const typeClass = `insight-${insight.type}`;

                html += `
                    <div class="insight-item ${typeClass}">
                        <div class="insight-icon">${icon}</div>
                        <div class="insight-content">
                            <div class="insight-message">${insight.message}</div>
                            <div class="insight-detail">${insight.detail}</div>
                        </div>
                    </div>
                `;
            });

            html += '</div>';
        }

        analysisContainer.innerHTML = html;
    }

    /**
     * Format seconds into human-readable time
     * @param {number} seconds - Time in seconds
     * @returns {string} Formatted time string
     */
    formatTime(seconds) {
        if (seconds < 60) {
            return `${Math.round(seconds)}s`;
        } else if (seconds < 3600) {
            const minutes = Math.floor(seconds / 60);
            const secs = Math.round(seconds % 60);
            return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
        } else {
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.round((seconds % 3600) / 60);
            return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
        }
    }

    /**
     * Render empty state
     */
    renderEmpty() {
        this.container.innerHTML = `
            <div class="empty-state">
                <p>No time vs difficulty data available yet.</p>
                <p class="empty-hint">Start tracking time spent on questions to see pacing insights.</p>
            </div>
        `;
    }

    /**
     * Render error state
     * @param {string} message - Error message
     */
    renderError(message) {
        this.container.innerHTML = `
            <div class="error-state">
                <p>Error loading time vs difficulty analysis</p>
                <p class="error-detail">${message}</p>
            </div>
        `;
    }

    /**
     * Clear the component
     */
    clear() {
        if (this.container) {
            this.container.innerHTML = '';
        }
        this.data = null;
    }
}
