/**
 * Subject vs Exam Weight Analysis Component
 *
 * Displays quadrant analysis and recommendations for aligning study time
 * with exam priorities. The efficiency score is DISABLED -- see below.
 */

/**
 * #146 -- the efficiency score is withdrawn from the product.
 *
 * It cannot report a bad result. On a realistic 15-row blueprint every
 * distribution a student could plausibly produce scores 88-99 and rates
 * **Excellent**; `Fair` and `Needs Improvement` are unreachable, and
 * perfect alignment scores 99.1 rather than 100 because real blueprints
 * do not total 100% and #64 forbids rescaling them. So the number was
 * telling every student they were doing well, including the ones who
 * were not.
 *
 * The owner's decision (2026-10-05) is **not** one of #146's five
 * proposed fixes: *"We have yet to discuss this. The feature should be
 * disabled for the time being."* So this is a hide, not a removal, and
 * one flag is the whole of it.
 *
 * What deliberately stays, so re-enabling is one word rather than a
 * reconstruction: `_calculate_efficiency_score`, `_get_efficiency_rating`
 * and `_build_efficiency_band` in `analytics_advanced.py`; the
 * `efficiency_score` / `efficiency_rating` / `efficiency_band` keys in the
 * payload; `user_preferences.efficiency_show_confidence_band` and m022;
 * and `renderEfficiencyValue`, `renderEfficiencyBandNote` and
 * `renderEfficiencyInfoIcon` below. Those three render nothing today and
 * are **not dead code to be swept** -- they are the other half of the
 * flag.
 *
 * The Settings control that chooses one-number-or-band is hidden in the
 * same change (`settings.html`), because with no score on the page it
 * would be a control over nothing -- the #289/#174 class of defect.
 *
 * Flip to `true` to restore it. `tests/test_efficiency_score_is_disabled.py`
 * will go red, which is the point: restoring it is a decision, not a drift.
 */
const EFFICIENCY_SCORE_ENABLED = false;

/** Subjects drawn per quadrant before "Show all" (owner, #817). */
const QUADRANT_LIMIT = 5;

/** Gridline steps for the shared scale, smallest first (#827 follow-up). */
const BAND_AXIS_STEPS = [1, 2, 5, 10, 20, 25, 50];

/**
 * One scale for every row on the card, so a bar in Priority and a bar in
 * Low Priority can be compared by eye. Its end is the largest figure on the
 * card -- a share or a band's top -- rounded up to a step, never 100%: the
 * rows are shares of one exam that do not sum to 100 (#6, #64), and a
 * 0-100 axis would squeeze every band into its first tenth. The tree
 * editor's range bars take their end the same way (#346).
 */
function bandAxisFor(subjects) {
    const top = subjects.reduce((m, s) => Math.max(m,
        Number(s.mistake_percentage) || 0,
        Number(s.exam_weight_high ?? s.exam_weight) || 0), 0);
    if (!(top > 0)) return null;
    let step = BAND_AXIS_STEPS[BAND_AXIS_STEPS.length - 1];
    for (const candidate of BAND_AXIS_STEPS) {
        if (top / candidate <= 4) { step = candidate; break; }
    }
    const max = Math.ceil(top / step) * step;
    const ticks = [];
    for (let v = 0; v <= max + 1e-9; v += step) ticks.push(Math.round(v * 1000) / 1000);
    return {max, step, ticks};
}

/** The four quadrants, in reading order. ``key`` is the payload's. */
const QUADRANTS = [
    {key: 'priority', cls: 'priority', icon: '🔴', title: 'Priority (Focus Here)'},
    {key: 'well_maintained', cls: 'well-maintained', icon: '🟢', title: 'Well-Maintained'},
    {key: 'reduce_focus', cls: 'reduce-focus', icon: '🟡', title: 'Reduce Focus'},
    {key: 'low_priority', cls: 'low-priority', icon: '⚪', title: 'Low Priority'},
];

class WeightAnalysis {
    constructor(containerId, api) {
        this.container = document.getElementById(containerId);
        this.api = api;
        this.data = null;
        // #133 -- student preference: draw the efficiency score as a
        // band instead of a single number. Default off, and off is not a
        // degraded mode: the "Weight Sources" card carries the same
        // provenance information either way.
        this.showConfidenceBand = false;

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
     * @param {object} scope - Optional {dimensionId, levelType} (#820):
     *     list one dimension's subjects at one level. Empty lists every
     *     weighted subject, which is what an exam without dimensions gets.
     */
    async load(examContextId, scope = {}) {
        // Only the newest load may draw: two quick picker changes must not
        // let the slower, older answer land last.
        const seq = (this.loadSeq = (this.loadSeq || 0) + 1);
        const scopeKey = `${scope.dimensionId ?? ''}|${scope.levelType ?? ''}`;
        if (scopeKey !== this.scopeKey) this.expandedQuadrants = new Set();
        this.scopeKey = scopeKey;
        this.scope = scope;
        console.log('[WeightAnalysis] Starting load with examContextId:', examContextId);
        
        if (!examContextId) {
            console.error('[WeightAnalysis] examContextId is required');
            this.renderError('Exam context is required for weight analysis');
            return;
        }
        
        try {
            console.log('[WeightAnalysis] Calling API.getSubjectExamWeightAnalysis...');
            
            const data = await this.api.getSubjectExamWeightAnalysis({
                examContextId,
                dimensionId: scope.dimensionId ?? null,
                levelType: scope.levelType || null,
            });
            if (seq !== this.loadSeq) return;
            
            console.log('[WeightAnalysis] Data received:', data);

            // #133. A failure here must not cost the student the whole
            // analysis, so the band simply stays off.
            try {
                const prefs = await this.api.getUserPreferences();
                this.showConfidenceBand = !!(
                    prefs && prefs.efficiency_show_confidence_band
                );
            } catch (prefError) {
                console.warn(
                    '[WeightAnalysis] Could not read the efficiency band ' +
                    'preference; showing a single number.', prefError
                );
                this.showConfidenceBand = false;
            }

            if (!data || typeof data !== 'object') {
                console.error('[WeightAnalysis] Invalid data received:', data);
                this.renderError('Invalid data received from server');
                return;
            }

            if (seq !== this.loadSeq) return;
            this.data = data;
            
            console.log('[WeightAnalysis] Calling render...');
            this.render();
            console.log('[WeightAnalysis] Render complete');

        } catch (error) {
            if (seq !== this.loadSeq) return;
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
                ${this.renderEfficiencyHeader()}

                <!-- Main Content Grid -->
                <div class="weight-content-grid">
                    <div class="quadrant-panel">
                        <h3 class="subsection-title" data-tour-anchor="analytics-weight-quadrant">Quadrant Analysis</h3>
                        <div id="quadrantAnalysis"></div>
                    </div>
                    <div class="recommendations-panel">
                        <h3 class="subsection-title" data-tour-anchor="analytics-weight-recommendations">Top Recommendations</h3>
                        <div id="recommendations"></div>
                    </div>
                </div>
            </div>
        `;

        this.renderQuadrantAnalysis();
        this.renderRecommendations();
    }

    /**
     * Render quadrant analysis with categorized subjects.
     *
     * Each quadrant shows its QUADRANT_LIMIT subjects with the largest gap
     * between mistake share and exam weight, and a toggle for the rest
     * (owner, #817). Before that every subject of every quadrant was drawn:
     * dozens of screens on a full published blueprint, where almost every
     * subject has no entries and still lands in a quadrant.
     */
    renderQuadrantAnalysis() {
        const container = document.getElementById('quadrantAnalysis');
        if (!container) return;

        const quadrants = this.data.quadrant_analysis;
        if (!this.expandedQuadrants) this.expandedQuadrants = new Set();
        // From every subject, not the rows on screen, so "Show all" does
        // not rescale the bars already drawn.
        const axis = bandAxisFor(this.data.subjects || []);
        const axisStyle = axis
            ? ` style="--axis-step: ${((axis.step / axis.max) * 100).toFixed(3)}%"` : '';

        let html = `<div class="quadrant-list"${axisStyle}>`;
        QUADRANTS.forEach(q => {
            const subjects = (quadrants[q.key] || []).slice()
                .sort((a, b) => Math.abs(b.difference || 0) - Math.abs(a.difference || 0));
            if (!subjects.length) return;
            const open = this.expandedQuadrants.has(q.key);
            const shown = open ? subjects : subjects.slice(0, QUADRANT_LIMIT);
            html += `
                <div class="quadrant-section ${q.cls}">
                    <div class="quadrant-header">
                        <span class="quadrant-icon">${q.icon}</span>
                        <span class="quadrant-title">${q.title}</span>
                        <span class="quadrant-count">${subjects.length}</span>
                    </div>
                    <ul class="quadrant-subjects">
            `;
            shown.forEach(subject => { html += this.renderBandRow(subject, axis); });
            html += '</ul>';
            if (subjects.length > QUADRANT_LIMIT) {
                html += `<button type="button" class="btn btn-secondary btn-sm quadrant-more"
                                 data-quadrant="${q.key}" aria-expanded="${open}">${
                            open ? `Show top ${QUADRANT_LIMIT}` : `Show all ${subjects.length}`}</button>`;
            }
            html += '</div>';
        });
        if (axis) html += this.renderBandScale(axis);
        html += '</div>';
        container.innerHTML = html;

        if (!container.dataset.quadrantToggle) {
            container.dataset.quadrantToggle = 'wired';
            container.addEventListener('click', (event) => {
                const button = event.target.closest('button.quadrant-more');
                if (!button) return;
                const key = button.dataset.quadrant;
                if (this.expandedQuadrants.has(key)) this.expandedQuadrants.delete(key);
                else this.expandedQuadrants.add(key);
                this.renderQuadrantAnalysis();
                const again = container.querySelector(`button.quadrant-more[data-quadrant="${key}"]`);
                if (again) again.focus();
            });
        }
    }

    /**
     * One subject: its name and count, then a bar on the card's shared scale
     * with the exam's band shaded and the student's share as a dot, then the
     * two figures in words (#827 follow-up, owner's choice of three layouts).
     *
     * The words sit in two fixed places under the bar, not under the marks:
     * a share inside or beside its band would put the two labels on top of
     * each other. Each carries the swatch of its mark, which is the link
     * between the words and the bar. The weight-source glyph sits by the
     * name: beside the figures, official's filled circle read as a second
     * share dot. The bar is decoration for a sighted
     * reader; everything it says is also in the text.
     */
    renderBandRow(subject, axis) {
        const count = subject.mistake_count ?? 0;
        const low = Number(subject.exam_weight_low ?? subject.exam_weight) || 0;
        const high = Number(subject.exam_weight_high ?? subject.exam_weight) || 0;
        const share = Number(subject.mistake_percentage) || 0;
        let bar = '';
        if (axis) {
            const pct = v => Math.min(100, (v / axis.max) * 100).toFixed(3);
            const point = low === high;
            bar = `
                        <div class="band-track" aria-hidden="true">
                            <span class="band-mark${point ? ' is-point' : ''}"
                                  style="--band-left: ${pct(low)}%; --band-width: ${(pct(high) - pct(low)).toFixed(3)}%"></span>
                            <span class="share-mark" style="--share: ${pct(share)}%"></span>
                        </div>`;
        }
        return `
                    <li class="band-row">
                        <div class="band-row-head">
                            <span class="band-row-name"><span class="subject-name">${WimiEscape.html(subject.subject_name)}</span>${this.renderSourceMarker(subject)}</span>
                            <span class="band-row-count">${count} ${count === 1 ? 'mistake' : 'mistakes'}</span>
                        </div>${bar}
                        <div class="subject-stats">
                            <span class="band-stat-exam"><span class="band-swatch" aria-hidden="true"></span>${this.formatWeightDisplay(subject)} of the exam</span>
                            <span class="band-stat-share"><span class="share-swatch" aria-hidden="true"></span>${subject.mistake_percentage}% of your mistakes</span>
                        </div>
                    </li>
                `;
    }

    /** The shared scale, once, under the last group (#827 follow-up). */
    renderBandScale(axis) {
        const ticks = axis.ticks.map((t, i) => {
            const cls = i === 0 ? ' is-first' : (i === axis.ticks.length - 1 ? ' is-last' : '');
            return `<span class="band-tick${cls}" style="left: ${((t / axis.max) * 100).toFixed(3)}%">${t}%</span>`;
        }).join('');
        return `
                <div class="band-scale" aria-hidden="true">${ticks}</div>`;
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
                        <div class="rec-subject">${WimiEscape.html(rec.subject)}</div>
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
     * The score header, or nothing at all (#146).
     *
     * One early return rather than four scattered guards, so the
     * disabled state is a single readable fact and the markup it would
     * draw stays beside it for when the discussion happens.
     *
     * **Nothing is left behind when it returns ''.** No empty
     * `.efficiency-header`, no placeholder, no greyed-out number -- the
     * `.weight-analysis-layout` grid would space an empty child, which is
     * the same mistake #60's proposal panel made with a `gap` over two
     * empty boxes. A disabled feature occupies no pixels.
     *
     * @returns {string} HTML for the score header, or '' while disabled.
     */
    renderEfficiencyHeader() {
        if (!EFFICIENCY_SCORE_ENABLED) {
            return '';
        }
        return `
                <!-- Efficiency Score Header -->
                <div class="efficiency-header">
                    <div class="efficiency-score-display">
                        <span class="efficiency-label">EFFICIENCY SCORE${this.renderEfficiencyInfoIcon()}</span>
                        <span class="efficiency-value ${this.getScoreClass(this.data.efficiency_score)}"
                              data-testid="efficiency-score-value">
                            ${this.renderEfficiencyValue()}
                        </span>
                        <span class="efficiency-rating">${this.data.efficiency_rating}</span>
                        ${this.renderEfficiencyBandNote()}
                    </div>
                </div>
        `;
    }

    /**
     * The score, as one number or as a band (#133).
     *
     * Reached only when ``EFFICIENCY_SCORE_ENABLED`` (#146). Kept rather
     * than deleted: it is the other half of the flag.
     *
     * Provenance is not part of the score's arithmetic in either
     * direction -- Stage 9's confidence multiplier scaled a *penalty*,
     * so a weight WIMI could not vouch for produced a higher score, and
     * it was deleted. What remains is a presentation choice the student
     * owns: one number, or the range the unverified weight mass allows.
     * Both describe the same score.
     *
     * @returns {string} e.g. ``76/100`` or ``69-83/100``.
     */
    renderEfficiencyValue() {
        const score = Math.round(this.data.efficiency_score);
        const band = this.data.efficiency_band;
        if (!this.showConfidenceBand || !band || !(band.half_width > 0)) {
            return `${score}/100`;
        }
        // En dash, not a hyphen: the low bound can be a bare number and
        // "69-83" reads as a subtraction at 2.6rem.
        return `${Math.round(band.low)}\u2013${Math.round(band.high)}/100`;
    }

    /**
     * One line saying where the band's width came from (#133).
     *
     * Only rendered with the band, because without it the sentence has
     * nothing to explain. The number it quotes is the share of the
     * exam's weight whose source is anything other than the published
     * blueprint.
     *
     * @returns {string} HTML, or '' when the band is not shown.
     */
    renderEfficiencyBandNote() {
        const band = this.data.efficiency_band;
        if (!this.showConfidenceBand || !band || !(band.half_width > 0)) {
            return '';
        }
        const pct = Math.round(band.unverified_weight_pct);
        return (
            `<span class="efficiency-band-note" ` +
            `data-testid="efficiency-band-note">` +
            `Weights covering about ${pct}% of this exam were typed or ` +
            `derived rather than taken from a blueprint, so the score is ` +
            `shown as a range.</span>`
        );
    }

    /**
     * The card's info affordance, mirroring the sunburst's (#6, #133).
     *
     * Same shape as ``analytics_dashboard.html``'s non-additive-arcs
     * tooltip: markup text rather than a CSS ``::after`` so it is
     * readable, and ``tabindex`` so it is reachable without a pointer.
     * The short form lives here; the full explanation is at the setting.
     *
     * @returns {string} HTML for the icon and its tooltip.
     */
    renderEfficiencyInfoIcon() {
        const text = this.showConfidenceBand
            ? 'The range widens with how much of this exam\'s weight was '
              + 'typed or derived rather than taken from the official '
              + 'blueprint. The score is the same either way.'
            : 'Some subject weights come from the official blueprint and '
              + 'others were typed or derived. The score treats them '
              + 'alike. Settings \u2192 Dashboard & Analytics can show it '
              + 'as a range instead.';
        return (
            `<span class="efficiency-info-icon" tabindex="0" ` +
            `data-testid="efficiency-confidence-info" ` +
            `aria-label="${text}">i<span class="efficiency-info-tooltip" ` +
            `data-testid="efficiency-confidence-tooltip">${text}</span></span>`
        );
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
        if (this.scope && this.scope.levelType) {
            this.renderPrompt(
                'No subject at this level has an exam weight.',
                'Choose another level, or add weights in the tree editor.');
            return;
        }
        this.container.innerHTML = `
            <div class="empty-state">
                <p>No weight analysis data available.</p>
                <p class="empty-hint">This analysis requires subjects with exam weights and logged mistakes.</p>
            </div>
        `;
    }

    /**
     * Say what to do instead of drawing (#820). Text only, never markup.
     */
    renderPrompt(message, hint) {
        this.data = null;
        const box = document.createElement('div');
        box.className = 'empty-state';
        const p = document.createElement('p');
        p.textContent = message;
        box.appendChild(p);
        if (hint) {
            const h = document.createElement('p');
            h.className = 'empty-hint';
            h.textContent = hint;
            box.appendChild(h);
        }
        this.container.replaceChildren(box);
    }

    /**
     * Render error state
     * @param {string} message - Error message
     */
    renderError(message) {
        this.container.innerHTML = `
            <div class="error-state">
                <p>Error loading weight analysis</p>
                <p class="error-detail">${WimiEscape.html(message)}</p>
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
