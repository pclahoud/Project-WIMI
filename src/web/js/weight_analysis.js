/**
 * Subject vs Exam Weight Analysis Component
 *
 * Displays efficiency score, quadrant analysis, and recommendations
 * for aligning study time with exam priorities
 */

class WeightAnalysis {
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
     * Format weight for display, showing range if low != high.
     *
     * Stage 5 — when the subject carries a ``q_typical`` field (the
     * exam has a planning baseline / ``length_kind !== 'unknown'``),
     * append the integer question count to the percentage so the user
     * sees ``11-15% • ~26 q``. Per design §7.5 dual-display copy.
     *
     * @param {object} subject - Subject object with exam_weight_low,
     *     exam_weight_high (or just exam_weight) and optional
     *     ``q_typical`` from ``api.getEffectiveQuestionCounts``.
     * @returns {string} Formatted weight string.
     */
    formatWeightDisplay(subject) {
        const low = subject.exam_weight_low ?? subject.exam_weight;
        const high = subject.exam_weight_high ?? subject.exam_weight;

        // If low and high are the same (or high is missing), show single value
        let pct;
        if (low === high || !high) {
            pct = `${low}%`;
        } else {
            pct = `${low}-${high}%`;
        }

        const q = subject.q_typical;
        if (q !== null && q !== undefined) {
            const qLabel = Number.isInteger(q) ? `~${q} q's` : `~${q.toFixed(1)} q's`;
            return `${pct} • ${qLabel}`;
        }
        return pct;
    }

    /**
     * Render an inline weight-source marker for a subject row.
     *
     * Stage 9 (WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 9").
     * The marker is a small theme-aware glyph that communicates the
     * underlying ``weight_source`` at a glance. Glyphs mirror the
     * spec in the implementation plan:
     *
     *   official       — ● (filled circle)
     *   user_explicit  — ⚓ (anchor pin)
     *   user_defined   — ○ (open circle)
     *   derived        — ⊘ (dashed/circled)
     *   user_estimate  — · (small dot)
     *
     * @param {object} subject - Subject row with optional ``weight_source``
     *     and ``subject_id`` (used to scope the data-testid).
     * @returns {string} Inline HTML snippet for the marker; empty string
     *     when no source is available so the caller can drop the marker
     *     into existing layouts without producing an orphan span.
     */
    renderSourceMarker(subject) {
        if (!subject) return '';
        const source = subject.weight_source;
        if (!source) return '';

        const glyphs = {
            'official':      '●',  // ● filled circle
            'user_explicit': '⚓',  // ⚓ anchor
            'user_defined':  '○',  // ○ open circle
            'derived':       '⊘',  // ⊘ circled slash
            'user_estimate': '·',  // · middle dot
        };
        const labels = {
            'official':      'Official outline',
            'user_explicit': 'User anchored',
            'user_defined':  'User defined',
            'derived':       'System derived',
            'user_estimate': 'User estimate',
        };
        const glyph = glyphs[source] || '○';
        const label = labels[source] || source;
        const testid = `weight-source-marker-${subject.subject_id ?? 'x'}`;
        return (
            `<span class="weight-source-marker" data-source="${source}" ` +
            `data-testid="${testid}" title="Weight source: ${label}" ` +
            `aria-label="Weight source: ${label}">${glyph}</span>`
        );
    }

    /**
     * Load and render weight analysis
     * @param {number} examContextId - Exam context ID (required)
     */
    async load(examContextId) {
        console.log('[WeightAnalysis] Starting load with examContextId:', examContextId);
        
        if (!examContextId) {
            console.error('[WeightAnalysis] examContextId is required');
            this.renderError('Exam context is required for weight analysis');
            return;
        }
        
        try {
            console.log('[WeightAnalysis] Calling API.getSubjectExamWeightAnalysis...');
            
            const data = await this.api.getSubjectExamWeightAnalysis({ examContextId });
            
            console.log('[WeightAnalysis] Data received:', data);

            if (!data || typeof data !== 'object') {
                console.error('[WeightAnalysis] Invalid data received:', data);
                this.renderError('Invalid data received from server');
                return;
            }

            this.data = data;
            
            console.log('[WeightAnalysis] Calling render...');
            this.render();
            console.log('[WeightAnalysis] Render complete');

        } catch (error) {
            console.error('[WeightAnalysis] Exception caught:', error);
            console.error('[WeightAnalysis] Error stack:', error.stack);
            this.renderError(`Failed to load analysis: ${error.message}`);
        }
    }

    /**
     * Render the complete weight analysis section
     */
    render() {
        if (!this.data || !this.data.subjects || this.data.subjects.length === 0) {
            this.renderEmpty();
            return;
        }

        this.container.innerHTML = `
            <div class="weight-analysis-layout">
                <!-- Efficiency Score Header -->
                <div class="efficiency-header">
                    <div class="efficiency-score-display">
                        <span class="efficiency-label">EFFICIENCY SCORE</span>
                        <span class="efficiency-value ${this.getScoreClass(this.data.efficiency_score)}">
                            ${Math.round(this.data.efficiency_score)}/100
                        </span>
                        <span class="efficiency-rating">${this.data.efficiency_rating}</span>
                    </div>
                </div>

                <!-- Main Content Grid -->
                <div class="weight-content-grid">
                    <div class="quadrant-panel">
                        <h3 class="subsection-title">Quadrant Analysis</h3>
                        <div id="quadrantAnalysis"></div>
                    </div>
                    <div class="recommendations-panel">
                        <h3 class="subsection-title">Top Recommendations</h3>
                        <div id="recommendations"></div>
                    </div>
                </div>
            </div>
        `;

        this.renderQuadrantAnalysis();
        this.renderRecommendations();
    }

    /**
     * Render quadrant analysis with categorized subjects
     */
    renderQuadrantAnalysis() {
        const container = document.getElementById('quadrantAnalysis');
        if (!container) return;

        const quadrants = this.data.quadrant_analysis;

        let html = '<div class="quadrant-list">';

        // Priority (Red) - Focus Here
        if (quadrants.priority && quadrants.priority.length > 0) {
            html += `
                <div class="quadrant-section priority">
                    <div class="quadrant-header">
                        <span class="quadrant-icon">🔴</span>
                        <span class="quadrant-title">PRIORITY (Focus Here)</span>
                    </div>
                    <ul class="quadrant-subjects">
            `;
            
            quadrants.priority.forEach(subject => {
                html += `
                    <li>
                        <span class="subject-name">${subject.subject_name}</span>
                        <span class="subject-stats">(${subject.mistake_percentage}% vs ${this.formatWeightDisplay(subject)})${this.renderSourceMarker(subject)}</span>
                    </li>
                `;
            });
            
            html += `
                    </ul>
                </div>
            `;
        }

        // Well-Maintained (Green) - Keep Up
        if (quadrants.well_maintained && quadrants.well_maintained.length > 0) {
            html += `
                <div class="quadrant-section well-maintained">
                    <div class="quadrant-header">
                        <span class="quadrant-icon">🟢</span>
                        <span class="quadrant-title">WELL-MAINTAINED</span>
                    </div>
                    <ul class="quadrant-subjects">
            `;
            
            quadrants.well_maintained.forEach(subject => {
                html += `
                    <li>
                        <span class="subject-name">${subject.subject_name}</span>
                        <span class="subject-stats">(${subject.mistake_percentage}% vs ${this.formatWeightDisplay(subject)})${this.renderSourceMarker(subject)}</span>
                    </li>
                `;
            });
            
            html += `
                    </ul>
                </div>
            `;
        }

        // Reduce Focus (Yellow) - Over-studying
        if (quadrants.reduce_focus && quadrants.reduce_focus.length > 0) {
            html += `
                <div class="quadrant-section reduce-focus">
                    <div class="quadrant-header">
                        <span class="quadrant-icon">🟡</span>
                        <span class="quadrant-title">REDUCE FOCUS</span>
                    </div>
                    <ul class="quadrant-subjects">
            `;
            
            quadrants.reduce_focus.forEach(subject => {
                html += `
                    <li>
                        <span class="subject-name">${subject.subject_name}</span>
                        <span class="subject-stats">(${subject.mistake_percentage}% vs ${this.formatWeightDisplay(subject)})${this.renderSourceMarker(subject)}</span>
                    </li>
                `;
            });
            
            html += `
                    </ul>
                </div>
            `;
        }

        // Low Priority (Gray) - Acceptable
        if (quadrants.low_priority && quadrants.low_priority.length > 0) {
            html += `
                <div class="quadrant-section low-priority">
                    <div class="quadrant-header">
                        <span class="quadrant-icon">⚪</span>
                        <span class="quadrant-title">LOW PRIORITY</span>
                    </div>
                    <ul class="quadrant-subjects">
            `;
            
            quadrants.low_priority.forEach(subject => {
                html += `
                    <li>
                        <span class="subject-name">${subject.subject_name}</span>
                        <span class="subject-stats">(${subject.mistake_percentage}% vs ${this.formatWeightDisplay(subject)})${this.renderSourceMarker(subject)}</span>
                    </li>
                `;
            });
            
            html += `
                    </ul>
                </div>
            `;
        }

        html += '</div>';
        container.innerHTML = html;
    }

    /**
     * Render recommendations based on quadrant analysis
     */
    renderRecommendations() {
        const container = document.getElementById('recommendations');
        if (!container) return;

        const recommendations = this.generateRecommendations();

        if (recommendations.length === 0) {
            container.innerHTML = '<p class="empty-message">No specific recommendations at this time.</p>';
            return;
        }

        let html = '<ol class="recommendations-list">';

        recommendations.forEach(rec => {
            html += `
                <li class="recommendation-item ${rec.type}">
                    <span class="rec-icon">${rec.icon}</span>
                    <div class="rec-content">
                        <div class="rec-subject">${rec.subject}</div>
                        <div class="rec-message">${rec.message}</div>
                    </div>
                </li>
            `;
        });

        html += '</ol>';
        container.innerHTML = html;
    }

    /**
     * Generate prioritized recommendations from quadrant data
     */
    generateRecommendations() {
        const recommendations = [];
        const quadrants = this.data.quadrant_analysis;

        // Priority subjects (increase focus)
        if (quadrants.priority) {
            quadrants.priority.slice(0, 3).forEach(subject => {
                recommendations.push({
                    type: 'increase',
                    icon: '↑',
                    subject: subject.subject_name,
                    message: `High exam weight (${this.formatWeightDisplay(subject)}), many mistakes (${subject.mistake_percentage}%) - increase focus`
                });
            });
        }

        // Reduce focus subjects
        if (quadrants.reduce_focus) {
            quadrants.reduce_focus.slice(0, 2).forEach(subject => {
                recommendations.push({
                    type: 'decrease',
                    icon: '↓',
                    subject: subject.subject_name,
                    message: `Low exam weight (${this.formatWeightDisplay(subject)}) - consider reducing time`
                });
            });
        }

        // Well-maintained (encourage)
        if (quadrants.well_maintained && quadrants.well_maintained.length > 0) {
            const best = quadrants.well_maintained[0];
            recommendations.push({
                type: 'maintain',
                icon: '✓',
                subject: best.subject_name,
                message: `Well-balanced - maintain current study level`
            });
        }

        // Limit to top 5 recommendations
        return recommendations.slice(0, 5);
    }

    /**
     * Get CSS class for efficiency score
     */
    getScoreClass(score) {
        if (score >= 85) return 'score-excellent';
        if (score >= 70) return 'score-good';
        if (score >= 50) return 'score-fair';
        return 'score-poor';
    }

    /**
     * Render empty state
     */
    renderEmpty() {
        this.container.innerHTML = `
            <div class="empty-state">
                <p>No weight analysis data available.</p>
                <p class="empty-hint">This analysis requires subjects with exam weights and logged mistakes.</p>
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
                <p>Error loading weight analysis</p>
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
