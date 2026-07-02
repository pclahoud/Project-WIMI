/**
 * WIMI Subject Deep Dive
 * Phase 6 Stage 3 - Subject Analysis
 */

class SubjectDeepDive {
    constructor() {
        this.subjectId = null;
        this.examContextId = null;
        this.subjectData = null;

        // Stage 9 (WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md): multi-parent
        // context selector state. ``parentEdges`` is the result of
        // ``api.getEdgesForChild(subjectId)``; ``activeParentId`` is the
        // currently selected parent (null = "All parents"). When the
        // subject has 0 or 1 parents the selector stays hidden.
        this.parentEdges = [];
        this.activeParentId = null;

        this.init();
    }

    /**
     * Format weight for display, showing range if low != high.
     *
     * Stage 5 — when the subject carries a ``q_typical`` field (the
     * exam has a planning baseline / ``length_kind !== 'unknown'``),
     * append the integer question count so the user sees
     * ``11-15% • ~26 q`` per design §7.5 dual-display copy.
     *
     * @param {object} data - Object with exam_weight_low,
     *     exam_weight_high (or just exam_weight) and optional
     *     ``q_typical`` from ``api.getEffectiveQuestionCounts``.
     * @returns {string} Formatted weight string.
     */
    formatWeightDisplay(data) {
        const low = data.exam_weight_low ?? data.exam_weight;
        const high = data.exam_weight_high ?? data.exam_weight;

        let pct;
        // If low and high are the same (or high is missing), show single value
        if (low === high || !high || low === 0) {
            pct = low > 0 ? `${low.toFixed(1)}%` : 'Not set';
        } else {
            pct = `${low}-${high}%`;
        }

        const q = data.q_typical;
        if (q !== null && q !== undefined && pct !== 'Not set') {
            const qLabel = Number.isInteger(q) ? `~${q} q's` : `~${q.toFixed(1)} q's`;
            return `${pct} • ${qLabel}`;
        }
        return pct;
    }

    async init() {
        console.log('Initializing Subject Deep Dive...');

        // Wait for API to be ready
        await api.ready();

        // Get subject ID and exam context from URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        this.subjectId = parseInt(urlParams.get('subject'));
        const examParam = urlParams.get('exam');
        if (examParam) {
            this.examContextId = parseInt(examParam);
        }

        if (!this.subjectId) {
            console.error('No subject ID provided');
            this.showError('No subject specified');
            return;
        }

        // Load exam name for display (read-only)
        await this.loadExamLabel();

        // Load all subject data
        await this.loadSubjectData();
    }

    /**
     * Load exam name for display in header (read-only, no switching)
     */
    async loadExamLabel() {
        try {
            if (this.examContextId) {
                const exam = await api.getExamContext(this.examContextId);
                if (exam) {
                    document.getElementById('examLabel').textContent = exam.exam_name;
                }
            } else {
                document.getElementById('examLabel').textContent = 'No exam selected';
            }
            
            // Update the back link with exam context
            this.updateBackLink();
        } catch (error) {
            console.error('Error loading exam label:', error);
            document.getElementById('examLabel').textContent = 'Unknown exam';
        }
    }

    /**
     * Update the "Back to Analytics" link to preserve exam context
     */
    updateBackLink() {
        const backLink = document.getElementById('backToAnalytics');
        if (backLink && this.examContextId) {
            backLink.href = `analytics_dashboard.html?exam=${this.examContextId}`;
        } else {
            backLink.href = 'analytics_dashboard.html';
        }
    }

    /**
     * Load all subject data.
     *
     * On initial load (``skipParentEdges`` falsy), parent edges are
     * fetched in parallel with the deep-dive payload so the multi-
     * parent context selector can render alongside the rest of the
     * page. On a context-change refresh, the parent edge list does not
     * change — pass ``skipParentEdges=true`` so only the deep-dive
     * payload is re-fetched.
     *
     * The deep-dive call always carries the current
     * ``this.activeParentId`` (Stage 9 follow-up); when null, the
     * backend returns the unfiltered union view.
     */
    async loadSubjectData({ skipParentEdges = false } = {}) {
        console.log(
            `Loading data for subject ${this.subjectId} ` +
            `(parentContext=${this.activeParentId})...`
        );

        try {
            const deepDivePromise = api.getSubjectDeepDive({
                subjectId: this.subjectId,
                examContextId: this.examContextId,
                primaryParentId: this.activeParentId,
            });

            let deepDiveData, parentEdges;
            if (skipParentEdges) {
                deepDiveData = await deepDivePromise;
                parentEdges = this.parentEdges;
            } else {
                // Stage 9 — fetch parent edges in parallel with the deep
                // dive payload. A failure on parent edges is not fatal;
                // we simply hide the selector and continue.
                const results = await Promise.all([
                    deepDivePromise,
                    this.loadParentEdges(),
                ]);
                deepDiveData = results[0];
                parentEdges = results[1] || [];
            }

            this.subjectData = deepDiveData;
            this.parentEdges = parentEdges;

            console.log('Subject data loaded:', this.subjectData);
            if (!skipParentEdges) {
                console.log('Parent edges loaded:', this.parentEdges);
            }

            if (!this.subjectData) {
                this.showError('Subject not found');
                return;
            }

            // Render all sections
            this.renderHeader();
            this.renderInfoAndTrend();
            this.renderMultiParentSelector();
            this.renderStats();
            this.renderTimeline();
            this.renderChildSubjects();
            this.renderMistakeTypes();
            this.renderRecentEntries();
            this.renderRelatedTopics();
            this.renderRecommendations();

        } catch (error) {
            console.error('Error loading subject data:', error);
            this.showError('Failed to load subject data');
        }
    }

    /**
     * Stage 9 — fetch every parent edge for the current subject so the
     * multi-parent context selector can be rendered. Returns an empty
     * array (rather than throwing) when the API isn't available so the
     * page still renders for older bridge surfaces.
     */
    async loadParentEdges() {
        if (!api.getEdgesForChild || !this.subjectId) {
            return [];
        }
        try {
            const edges = await api.getEdgesForChild(this.subjectId);
            return Array.isArray(edges) ? edges : [];
        } catch (err) {
            console.warn('Could not load parent edges:', err);
            return [];
        }
    }

    /**
     * Build the markup for the selector's explanatory banner.
     *
     * Two states matching the deep-dive's "Show everything always"
     * view semantic:
     *
     *   * "All parents" — every entry tagged on this subject is
     *     visible. Banner is just orientation copy ("this subject
     *     lives under N parents, pick one to scope").
     *   * Active parent P — the view is narrowed to entries that
     *     route through P. ``entries_scoped_elsewhere`` is the count
     *     of entries on the subject that route through a different
     *     parent and are therefore hidden from this view; the banner
     *     surfaces it so the user understands what's missing.
     */
    _buildSelectorBanner(edges) {
        const scopedAway = this.subjectData?.entries_scoped_elsewhere || 0;
        if (this.activeParentId === null) {
            return `
                <p class="multi-parent-banner"
                   data-testid="multi-parent-selector-banner">
                    This subject lives under ${edges.length} parents. Showing every entry tagged on it — pick a parent above to narrow the view to one context.
                </p>
            `;
        }
        const activeEdge = edges.find(e => e.parent_id === this.activeParentId);
        const activeName = activeEdge?.parent_name || `Parent ${this.activeParentId}`;
        const elsewhere = scopedAway > 0
            ? ` <strong>${scopedAway}</strong> ${scopedAway === 1 ? 'entry on this subject is' : 'entries on this subject are'} tagged with a different parent context and ${scopedAway === 1 ? 'is' : 'are'} not shown in this view.`
            : '';
        return `
            <p class="multi-parent-banner multi-parent-banner--active"
               data-testid="multi-parent-selector-banner">
                Viewing entries that route through <strong>${this._escape(activeName)}</strong>.${elsewhere}
            </p>
        `;
    }

    /**
     * Minimal HTML escape so a malicious parent_name in the DB can't
     * inject markup through the banner. Subject and parent names come
     * from user input.
     */
    _escape(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /**
     * Stage 9 (with follow-up) — render the "Show as part of"
     * parent-context selector.
     *
     * Visible only when the subject has 2+ parent edges. The dropdown
     * carries every parent name plus an "All parents" option (the
     * default union view). Selecting a parent updates
     * ``this.activeParentId`` and triggers a refetch of
     * ``getSubjectDeepDive`` with ``primaryParentId`` so every section
     * narrows to the chosen parent's rollup (lenient semantic — see
     * ``analytics_advanced.get_subject_deep_dive`` docstring).
     */
    renderMultiParentSelector() {
        const container = document.getElementById('multiParentSelector');
        if (!container) return;

        const edges = this.parentEdges || [];
        if (edges.length < 2) {
            // Hidden when 0 or 1 parents — no need to choose.
            container.style.display = 'none';
            container.innerHTML = '';
            return;
        }

        // Build the dropdown. We list parents in the order returned by
        // get_edges_for_child (primary first), with "All parents" at
        // the top as the default.
        const options = [
            '<option value="" data-testid="multi-parent-selector-option-all">All parents</option>',
        ].concat(edges.map(edge => {
            const pid = edge.parent_id;
            const name = edge.parent_name || `Parent ${pid}`;
            const selected = this.activeParentId === pid ? ' selected' : '';
            return `<option value="${pid}" data-testid="multi-parent-selector-option-${pid}"${selected}>${name}</option>`;
        })).join('');

        // Names of the non-selected parents for the "also: ..." hint.
        const alsoNames = edges
            .filter(e => e.parent_id !== this.activeParentId)
            .map(e => e.parent_name || `Parent ${e.parent_id}`)
            .join(', ');

        // Stage 9 polish — explanatory banner. The selector by itself
        // doesn't communicate what filtering by parent *means*; on
        // leaf subjects (the common case) it's a structural no-op
        // because §5.4 already scopes explicit-context entries away
        // from the leaf's own deep-dive. The banner makes the user's
        // current view + what they're not seeing explicit.
        const banner = this._buildSelectorBanner(edges);

        container.innerHTML = `
            <label for="multiParentSelectorControl">Show as part of:</label>
            <select
                id="multiParentSelectorControl"
                data-testid="multi-parent-selector-control"
            >${options}</select>
            ${alsoNames ? `<span class="also-list">(also: ${alsoNames})</span>` : ''}
            ${banner}
        `;
        container.style.display = '';

        const select = container.querySelector('#multiParentSelectorControl');
        if (select) {
            select.addEventListener('change', (e) => {
                const value = e.target.value;
                this.activeParentId = value === '' ? null : parseInt(value, 10);
                console.log('Active parent context changed:', this.activeParentId);
                // Refetch the deep-dive with the new context and
                // re-render every section. ``skipParentEdges=true``
                // because the parent edge list itself does not change
                // when the selection changes.
                this.loadSubjectData({ skipParentEdges: true });
            });
        }
    }

    /**
     * Render header with subject name
     */
    renderHeader() {
        document.getElementById('subjectTitle').textContent = this.subjectData.subject_name;
    }

    /**
     * Render info and trend sections.
     *
     * Stage 9 polish — when an explicit parent context is active and
     * the backend returned a ``path_via_parent``, render that instead
     * of the canonical primary path so the breadcrumb actually
     * reflects the chosen view. Falls back to ``full_path`` when no
     * context is selected (the "All parents" case).
     */
    renderInfoAndTrend() {
        const displayPath = this.subjectData.path_via_parent
            || this.subjectData.full_path
            || '-';
        document.getElementById('fullPath').textContent = displayPath;

        // Exam weight - show range if available
        document.getElementById('examWeight').textContent = this.formatWeightDisplay(this.subjectData);

        // Trend
        document.getElementById('thisWeek').textContent = this.subjectData.this_week || 0;
        document.getElementById('lastWeek').textContent = this.subjectData.last_week || 0;

        const change = (this.subjectData.this_week || 0) - (this.subjectData.last_week || 0);
        const trendEl = document.getElementById('trendChange');

        if (change === 0) {
            trendEl.textContent = 'No change from last week';
            trendEl.className = 'trend-change';
        } else if (change < 0) {
            const percentage = this.subjectData.last_week > 0
                ? Math.abs(Math.round(change / this.subjectData.last_week * 100))
                : 0;
            trendEl.textContent = `Change: ${change} (↓ ${percentage}% - Improving!)`;
            trendEl.className = 'trend-change improving';
        } else {
            const percentage = this.subjectData.last_week > 0
                ? Math.round(change / this.subjectData.last_week * 100)
                : 0;
            trendEl.textContent = `Change: +${change} (↑ ${percentage}% - Need more review)`;
            trendEl.className = 'trend-change declining';
        }
    }

    /**
     * Render statistics cards
     */
    renderStats() {
        document.getElementById('totalMistakes').textContent = this.subjectData.total_mistakes || 0;
        document.getElementById('percentageOfAll').textContent =
            this.subjectData.percentage ? `${this.subjectData.percentage.toFixed(1)}%` : '0%';
        document.getElementById('avgDifficulty').textContent =
            this.subjectData.avg_difficulty ? this.subjectData.avg_difficulty.toFixed(1) : '-';

        // Last mistake date
        const lastDate = this.subjectData.last_mistake_date;
        if (lastDate) {
            const daysAgo = this.getDaysAgo(lastDate);
            document.getElementById('lastMistake').textContent =
                daysAgo === 0 ? 'Today' : daysAgo === 1 ? 'Yesterday' : `${daysAgo} days ago`;
        } else {
            document.getElementById('lastMistake').textContent = 'Never';
        }
    }

    /**
     * Render timeline chart with D3.js
     */
    renderTimeline() {
        const data = this.subjectData.timeline || [];

        if (!data || data.length === 0) {
            this.renderEmptyTimeline();
            return;
        }

        const canvas = document.getElementById('timelineChart');
        const ctx = canvas.getContext('2d');
        const _cs = getComputedStyle(document.documentElement);

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Chart settings
        const padding = 40;
        const chartWidth = canvas.width - (padding * 2);
        const chartHeight = canvas.height - (padding * 2);

        // Find max value
        const maxValue = Math.max(...data.map(d => d.count), 1);

        // Calculate bar width
        const barWidth = chartWidth / data.length - 10;

        // Draw bars
        data.forEach((item, index) => {
            const barHeight = (item.count / maxValue) * chartHeight;
            const x = padding + (index * (chartWidth / data.length));
            const y = padding + chartHeight - barHeight;

            // Draw bar
            ctx.fillStyle = _cs.getPropertyValue('--color-info').trim();
            ctx.fillRect(x, y, barWidth, barHeight);

            // Draw label
            ctx.fillStyle = _cs.getPropertyValue('--text-muted').trim();
            ctx.font = '12px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(item.label, x + barWidth / 2, canvas.height - 10);

            // Draw count on top of bar
            ctx.fillStyle = _cs.getPropertyValue('--text-primary').trim();
            ctx.font = '12px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(item.count, x + barWidth / 2, y - 5);
        });
    }

    /**
     * Render empty timeline state
     */
    renderEmptyTimeline() {
        const canvas = document.getElementById('timelineChart');
        const ctx = canvas.getContext('2d');

        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const _cs = getComputedStyle(document.documentElement);
        ctx.fillStyle = _cs.getPropertyValue('--text-muted').trim();
        ctx.font = '14px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('No timeline data available', canvas.width / 2, canvas.height / 2);
    }

    /**
     * Render child subjects list
     *
     * Future-aware (polyhierarchy migration):
     *   When the DAG migration lands, a child may render under multiple parents.
     *   The per-row testid pattern will extend to `deep-dive-child-row-{childId}-under-{parentId}`
     *   to disambiguate. Today the parent context is implicit (this.subjectId), so the
     *   plain `deep-dive-child-row-{childId}` form is used.
     */
    renderChildSubjects() {
        const container = document.getElementById('childSubjectsList');
        container.setAttribute('data-testid', 'deep-dive-list-children');
        container.innerHTML = '';

        const children = this.subjectData.child_subjects || [];

        if (children.length === 0) {
            container.innerHTML = '<div class="empty-state" data-testid="deep-dive-empty-state-children">No child subjects</div>';
            return;
        }

        children.forEach(child => {
            const item = document.createElement('div');
            item.className = 'child-subject-item';
            item.setAttribute('data-testid', `deep-dive-child-row-${child.subject_id}`);
            item.setAttribute('role', 'button');
            item.setAttribute('tabindex', '0');
            item.innerHTML = `
                <span class="child-subject-name">${child.subject_name}</span>
                <span class="child-subject-count">${child.mistake_count}</span>
            `;
            const navigate = () => {
                // Navigate to this child subject's deep dive
                const url = `subject_deep_dive.html?subject=${child.subject_id}${this.examContextId ? `&exam=${this.examContextId}` : ''}`;
                window.location.href = url;
            };
            item.addEventListener('click', navigate);
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    navigate();
                }
            });
            container.appendChild(item);
        });
    }

    /**
     * Render common mistake types
     */
    renderMistakeTypes() {
        const container = document.getElementById('mistakeTypesList');
        container.setAttribute('data-testid', 'deep-dive-list-mistake-types');
        container.innerHTML = '';

        const types = this.subjectData.mistake_types || [];

        if (types.length === 0) {
            container.innerHTML = '<div class="empty-state" data-testid="deep-dive-empty-state-mistake-types">No mistake types tagged</div>';
            return;
        }

        types.forEach(type => {
            const item = document.createElement('div');
            item.className = 'mistake-type-item';
            item.innerHTML = `
                <span class="mistake-type-name">
                    <span class="mistake-type-badge" data-testid="deep-dive-mistake-type-badge-${type.tag_name}" style="background-color: ${type.color || 'var(--border-color)'}22; color: ${type.color || 'var(--text-muted)'}">
                        ${type.tag_name}
                    </span>
                </span>
                <span class="mistake-type-count">${type.count} (${type.percentage}%)</span>
            `;
            container.appendChild(item);
        });
    }

    /**
     * Render recent entries
     */
    renderRecentEntries() {
        const container = document.getElementById('recentEntriesList');
        container.setAttribute('data-testid', 'deep-dive-list-recent-entries');
        container.innerHTML = '';

        const entries = this.subjectData.recent_entries || [];

        if (entries.length === 0) {
            container.innerHTML = '<div class="empty-state" data-testid="deep-dive-empty-state-recent-entries">No recent entries</div>';
            return;
        }

        entries.forEach(entry => {
            const item = document.createElement('div');
            item.className = 'recent-entry-item';
            item.setAttribute('data-testid', `deep-dive-recent-entry-${entry.entry_id}`);
            item.setAttribute('role', 'button');
            item.setAttribute('tabindex', '0');

            const date = new Date(entry.date_encountered);
            const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

            item.innerHTML = `
                <div class="recent-entry-date">${dateStr}</div>
                <div class="recent-entry-subject">${entry.subject_name}</div>
                <div class="recent-entry-note">${entry.reflection || entry.explanation || 'No notes'}</div>
            `;

            // Click to view entry details (future implementation)
            const activate = () => {
                console.log('View entry:', entry.entry_id);
                // TODO: Navigate to entry detail view
            };
            item.addEventListener('click', activate);
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    activate();
                }
            });

            container.appendChild(item);
        });
    }

    /**
     * Render related topics (sibling subjects)
     */
    renderRelatedTopics() {
        const container = document.getElementById('relatedTopicsList');
        container.setAttribute('data-testid', 'deep-dive-list-related-topics');
        container.innerHTML = '';

        const siblings = this.subjectData.sibling_subjects || [];

        if (siblings.length === 0) {
            container.innerHTML = '<div class="empty-state" data-testid="deep-dive-empty-state-related-topics">No related topics</div>';
            return;
        }

        siblings.forEach(sibling => {
            const item = document.createElement('div');
            item.className = 'related-topic-item';
            item.setAttribute('data-testid', `deep-dive-related-topic-${sibling.subject_id}`);
            item.setAttribute('role', 'button');
            item.setAttribute('tabindex', '0');
            item.innerHTML = `
                <span class="related-topic-name">${sibling.subject_name}</span>
                <span class="related-topic-count">${sibling.mistake_count} mistakes</span>
            `;
            const navigate = () => {
                // Navigate to this sibling's deep dive
                const url = `subject_deep_dive.html?subject=${sibling.subject_id}${this.examContextId ? `&exam=${this.examContextId}` : ''}`;
                window.location.href = url;
            };
            item.addEventListener('click', navigate);
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    navigate();
                }
            });
            container.appendChild(item);
        });
    }

    /**
     * Render recommendations
     */
    renderRecommendations() {
        const container = document.getElementById('recommendationsList');
        container.setAttribute('data-testid', 'deep-dive-list-recommendations');
        container.innerHTML = '';

        const recommendations = this.generateRecommendations();

        if (recommendations.length === 0) {
            container.innerHTML = '<div class="empty-state" data-testid="deep-dive-empty-state-recommendations">No recommendations available</div>';
            return;
        }

        recommendations.forEach(rec => {
            const item = document.createElement('div');
            item.className = 'recommendation-item';
            if (rec.type) {
                item.setAttribute('data-testid', `deep-dive-recommendation-${rec.type}`);
            }
            item.innerHTML = `
                <div class="recommendation-icon">${rec.icon}</div>
                <div class="recommendation-text">${rec.text}</div>
            `;
            container.appendChild(item);
        });
    }

    /**
     * Generate smart recommendations based on data
     */
    generateRecommendations() {
        const recommendations = [];

        // High mistake count
        if (this.subjectData.total_mistakes > 10) {
            recommendations.push({
                type: 'high-mistake-count',
                icon: '💡',
                text: `This subject has ${this.subjectData.total_mistakes} mistakes - consider dedicating extra study time here.`
            });
        }

        // Weight mismatch - use midpoint for comparison but display range
        const weight = this.subjectData.exam_weight || 0;
        const weightHigh = this.subjectData.exam_weight_high || weight;
        if (weight > 0 && this.subjectData.percentage > weightHigh * 1.5) {
            const weightDisplay = this.formatWeightDisplay(this.subjectData);
            recommendations.push({
                type: 'weight-mismatch',
                icon: '⚠️',
                text: `This subject is ${weightDisplay} of the exam but ${this.subjectData.percentage.toFixed(1)}% of your mistakes. Focus here!`
            });
        }

        // Child subject focus
        const children = this.subjectData.child_subjects || [];
        if (children.length > 0) {
            const topChild = children[0];
            recommendations.push({
                type: 'child-focus',
                icon: '🎯',
                text: `Focus on "${topChild.subject_name}" - it has the most mistakes (${topChild.mistake_count}).`
            });
        }

        // Improving trend
        const change = (this.subjectData.this_week || 0) - (this.subjectData.last_week || 0);
        if (change < -3) {
            recommendations.push({
                type: 'trend-improving',
                icon: '✓',
                text: 'Great progress! Keep up the current study approach.'
            });
        } else if (change > 3) {
            recommendations.push({
                type: 'trend-declining',
                icon: '📚',
                text: 'Mistakes increasing - review fundamentals and past entries.'
            });
        }

        return recommendations;
    }

    /**
     * Calculate days ago from date string
     */
    getDaysAgo(dateStr) {
        const date = new Date(dateStr);
        const today = new Date();
        const diffTime = today - date;
        const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
        return diffDays;
    }

    /**
     * Show error message
     */
    showError(message) {
        document.querySelector('.page-container').innerHTML = `
            <div style="padding: 40px; text-align: center;">
                <h2 style="color: var(--color-error); margin-bottom: 16px;">Error</h2>
                <p style="color: var(--text-muted);">${message}</p>
                <a href="analytics_dashboard.html" style="display: inline-block; margin-top: 20px; color: var(--color-info); text-decoration: none;">
                    ← Back to Analytics
                </a>
            </div>
        `;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.subjectDeepDive = new SubjectDeepDive();
});
