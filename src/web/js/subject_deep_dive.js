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

        // Issue #14 — the Related Topics panel. Owns its own mount and
        // its own fetch; the deep dive only tells it which parent
        // context is selected, because that context ORDERS the panel
        // (decision 5) exactly as it narrows everything else here.
        this.relationsPanel = null;

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
        const labelEl = document.getElementById('examLabel');
        try {
            if (this.examContextId) {
                const exam = await api.getExamContext(this.examContextId);
                if (exam) {
                    labelEl.textContent = exam.exam_name;
                    // #314 item 2 (owner 2026-10-10): this was a <span>
                    // bordered and filled like a button that did nothing on
                    // click -- an affordance that lies. It is a real link
                    // now, and the destination is the exam's SUBJECT TREE.
                    //
                    // Why there and not analytics: "Back to Analytics" in
                    // this same header already goes to analytics for this
                    // exam, so pointing the exam name at it would give the
                    // header two controls with one destination. The tree is
                    // the exam itself rather than a view of its data, and it
                    // is continuous with the "Full path" line directly below
                    // -- a student reading where this subject sits can go and
                    // see it sitting there. The query key is `exam_id`, which
                    // is what tree_editor.html reads; analytics and the entry
                    // browser use `exam`, and mixing them up yields "No exam
                    // ID provided".
                    labelEl.href =
                        `tree_editor.html?exam_id=${encodeURIComponent(this.examContextId)}`;
                }
            } else {
                labelEl.textContent = 'No exam selected';
                // Nothing to link to. Removing the attribute (rather than
                // leaving "#") takes it out of the tab order and stops it
                // presenting as a link at all, which is #174's rule: do not
                // offer a press when there is nothing to press.
                labelEl.removeAttribute('href');
            }
            
            // Update the back link with exam context
            this.updateBackLink();
        } catch (error) {
            console.error('Error loading exam label:', error);
            labelEl.textContent = 'Unknown exam';
            labelEl.removeAttribute('href');
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
            this.renderSubjectNotes();
            this.renderRecommendations();
            this.renderRelations();

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
                Viewing entries that route through <strong>${WimiEscape.html(activeName)}</strong>.${elsewhere}
            </p>
        `;
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
        // the top as the default. Built from nodes, not an HTML string
        // (#548): a parent's name is text a student typed or imported.
        const control = document.createElement('select');
        control.id = 'multiParentSelectorControl';
        control.setAttribute('data-testid', 'multi-parent-selector-control');
        const allOption = document.createElement('option');
        allOption.value = '';
        allOption.setAttribute('data-testid', 'multi-parent-selector-option-all');
        allOption.textContent = 'All parents';
        control.appendChild(allOption);
        edges.forEach(edge => {
            const pid = edge.parent_id;
            const option = document.createElement('option');
            option.value = String(pid);
            option.setAttribute('data-testid', `multi-parent-selector-option-${pid}`);
            option.textContent = edge.parent_name || `Parent ${pid}`;
            if (this.activeParentId === pid) option.selected = true;
            control.appendChild(option);
        });

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

        container.innerHTML = '';
        const label = document.createElement('label');
        label.htmlFor = 'multiParentSelectorControl';
        label.textContent = 'Show as part of:';
        container.append(label, ' ', control);
        if (alsoNames) {
            const also = document.createElement('span');
            also.className = 'also-list';
            also.textContent = `(also: ${alsoNames})`;
            container.append(' ', also);
        }
        // The banner escapes the one name it carries (_buildSelectorBanner).
        container.insertAdjacentHTML('beforeend', banner);
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
     * Render header with subject name, and the axis it is on.
     *
     * THE TITLE ALONE DOES NOT IDENTIFY THE SUBJECT (#314, owner
     * 2026-10-10). On a multi-dimensional exam the heading read "18 to 65"
     * and "Full path: 18 to 65" repeated it, because a dimension root has
     * nothing above it to disambiguate with. Nothing on the page said it was
     * a **Patient Age** group rather than a topic or a Site of Care value.
     *
     * The app already had this habit and had not applied it here: subject
     * relations deliberately label the *other* subject's dimension when the
     * two differ, and the tree editor's details subtitle carries an
     * `in <Axis>` fragment. This is the same fragment on the page's own
     * title.
     *
     * `dimension_name` is ABSENT from the payload when the subject is in no
     * axis, so the check is presence rather than truthiness of a null, and
     * the element stays hidden on every single-dimension and dimensionless
     * exam. Hidden via a class rather than left empty: `:empty` is banned by
     * a CI gate (#134/#136/#141) and an empty qualifier still occupies the
     * line.
     */
    renderHeader() {
        document.getElementById('subjectTitle').textContent = this.subjectData.subject_name;

        const dimEl = document.getElementById('subjectDimension');
        if (!dimEl) return;
        const axis = this.subjectData.dimension_name;
        if (axis) {
            dimEl.textContent = `in ${axis}`;
            dimEl.classList.remove('hidden');
        } else {
            dimEl.textContent = '';
            dimEl.classList.add('hidden');
        }
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
        const pathEl = document.getElementById('fullPath');
        pathEl.textContent = displayPath;
        // #301: the path above is filtered, so an archived ancestor is no
        // longer named in it. Say why, where something was actually
        // removed. `path_omitted_ancestors` is keyed to whichever of the
        // two paths the backend knows this line will show, so there is no
        // branch here. Guarded on `typeof` so a missing script tag costs
        // the explanation, never the path.
        //
        // A SIBLING of `#fullPath`, never a child: that element's
        // `textContent` is the value scenarios read, and
        // `test_multi_parent_selector_refilter.py` asserts a subject name is
        // *absent* from it.
        const staleNote = pathEl.parentNode
            && pathEl.parentNode.querySelector(
                '[data-testid="archived-ancestors-note"]');
        if (staleNote) staleNote.remove();
        if (typeof ArchivedAncestorNote !== 'undefined') {
            ArchivedAncestorNote.insertAfter(
                pathEl, this.subjectData.path_omitted_ancestors);
        }

        // Exam weight - show range if available
        document.getElementById('examWeight').textContent = this.formatWeightDisplay(this.subjectData);

        // Trend
        document.getElementById('thisWeek').textContent = this.subjectData.this_week || 0;
        document.getElementById('lastWeek').textContent = this.subjectData.last_week || 0;

        const lastWeek = this.subjectData.last_week || 0;
        const change = (this.subjectData.this_week || 0) - lastWeek;
        const trendEl = document.getElementById('trendChange');

        // NOTHING HAPPENED AND NO CHANGE ARE DIFFERENT STATES (#314 item 3,
        // owner 2026-10-10). A 0-vs-0 comparison used to fall into the same
        // branch as a genuine 4-vs-4, so a subject whose last mistake was 122
        // days ago reported "No change from last week" in a highlighted box.
        // Technically true, and it reads as a status report on current
        // activity: "no change" implies something is being tracked and is
        // steady, where the truth is that nothing has been tracked for four
        // months. That is #289's and #174's class -- the page stating
        // something that does not mean what it appears to.
        //
        // This is a THIRD BRANCH rather than a reworded string, deliberately.
        // The two states have to stay distinguishable to anything that reads
        // this later -- a copy change would merge them again the moment
        // somebody wants to style, announce or count them separately.
        //
        // No new visual treatment: the neutral `trend-change` class is kept
        // for both. Quietening this box is exactly the de-emphasis that #326
        // still owns, and item 2 was decided the way it was to stay out of
        // that; the words were the lie, so the words are the fix.
        const bothWeeksEmpty = (this.subjectData.this_week || 0) === 0 && lastWeek === 0;

        if (bothWeeksEmpty) {
            trendEl.textContent = 'No activity this week or last';
            trendEl.className = 'trend-change';
        } else if (change === 0) {
            trendEl.textContent = 'No change from last week';
            trendEl.className = 'trend-change';
        } else if (change < 0) {
            trendEl.textContent = `Change: ${change} (${this.formatTrendDetail('↓', change, lastWeek, 'Improving!')})`;
            trendEl.className = 'trend-change improving';
        } else {
            trendEl.textContent = `Change: +${change} (${this.formatTrendDetail('↑', change, lastWeek, 'Need more review')})`;
            trendEl.className = 'trend-change declining';
        }
    }

    /**
     * Parenthetical after "Change: ±N": arrow, week-over-week
     * percentage, label. The percentage is relative to LAST WEEK, so
     * it is undefined when last week had no entries; issue #11 was a
     * fallback to 0 there, which read "↑ 0%" beside a "+9". Growth
     * from zero now drops the figure and keeps the arrow and label.
     * (A drop to zero is not the mirror case: change < 0 implies
     * last_week > 0, and 100% is the right figure there.)
     */
    formatTrendDetail(arrow, change, lastWeek, label) {
        const parts = [arrow];
        if (lastWeek > 0) {
            parts.push(`${Math.abs(Math.round(change / lastWeek * 100))}% -`);
        }
        parts.push(label);
        return parts.join(' ');
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
            // Text nodes, not innerHTML (#548): a subject name is text a
            // student typed or imported.
            const nameEl = document.createElement('span');
            nameEl.className = 'child-subject-name';
            nameEl.textContent = child.subject_name;
            const countEl = document.createElement('span');
            countEl.className = 'child-subject-count';
            countEl.textContent = child.mistake_count;
            item.append(nameEl, countEl);
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
            // Nodes, not innerHTML (#548): an error type's name is text a
            // student typed or imported, and its colour went into a style
            // attribute where a quote ended the attribute.
            const nameWrap = document.createElement('span');
            nameWrap.className = 'mistake-type-name';
            const badge = document.createElement('span');
            badge.className = 'mistake-type-badge';
            badge.setAttribute('data-testid', `deep-dive-mistake-type-badge-${type.tag_name}`);
            badge.style.setProperty('background-color', `${type.color || 'var(--border-color)'}22`);
            badge.style.setProperty('color', type.color || 'var(--text-muted)');
            badge.textContent = type.tag_name;
            nameWrap.appendChild(badge);
            const countEl = document.createElement('span');
            countEl.className = 'mistake-type-count';
            countEl.textContent = `${type.count} (${type.percentage}%)`;
            item.append(nameWrap, countEl);
            // Surface the tag definition as a hover tooltip when one is set
            if (typeof type.description === 'string' && type.description.trim() !== '') {
                item.title = type.description;
            }
            container.appendChild(item);
        });
    }

    /**
     * Render recent entries
     */
    /**
     * Notes TAGGED with this subject (#465, owner 2026-10-10).
     *
     * The strict set: a note whose own `linked_subject_ids` names this
     * subject. Not every note on an entry tagged here, and not inherited
     * from descendants. That is **deliberately the opposite rule** from the
     * entries list above it, which uses this page's permissive
     * "show everything" semantic — a note is filed by hand at one subject,
     * where an entry's rollup is derived. Both lists are on one page on
     * purpose, and the headings are what keeps them apart.
     *
     * Until this landed, `get_subject_deep_dive` returned no notes key at
     * all, and the only thing on the page resembling one was the Recent
     * Entries row's third line — classed `recent-entry-note`, rendering a
     * reflection, falling back to the literal string "No notes".
     *
     * The row behaviour is copied from `renderRecentEntries`, not invented:
     * same `entryNavContext` clearing, same URL shape, same Enter/Space
     * handling. #464 established that a row announced as a button has to go
     * somewhere; two lists on one page behaving differently would be worse
     * than either behaviour alone.
     */
    renderSubjectNotes() {
        const container = document.getElementById('subjectNotesList');
        if (!container) return;
        container.innerHTML = '';

        const notes = this.subjectData.notes || [];

        if (notes.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.setAttribute('data-testid', 'deep-dive-empty-state-subject-notes');
            // Says which set is empty. "No notes" alone would read as "this
            // subject has nothing written about it", when what is true is
            // that nothing has been TAGGED to it -- the entry reflections
            // above may be full.
            empty.textContent = 'No notes are tagged with this subject yet';
            container.appendChild(empty);
            return;
        }

        notes.forEach(note => {
            const item = document.createElement('div');
            item.className = 'subject-note-item';
            item.setAttribute('data-testid', `deep-dive-subject-note-${note.note_id}`);
            item.setAttribute('role', 'button');
            item.setAttribute('tabindex', '0');

            // Stored rich text, reduced to its words through the same inert
            // path the entry browser's card and the row above use (#525,
            // #591). Never innerHTML: a note's content is student-supplied
            // and a profile import can carry anything.
            const toText = html => (window.WimiTextPreview
                ? window.WimiTextPreview.htmlToPreviewText(html) : '');
            const body = toText(note.content_html) || '(empty note)';

            const when = note.updated_at
                ? LocalDate.parse(String(note.updated_at).slice(0, 10))
                : null;
            const dateStr = when
                ? when.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
                : '';

            [
                ['subject-note-date', dateStr],
                ['subject-note-body', body],
            ].forEach(([className, text]) => {
                const cell = document.createElement('div');
                cell.className = className;
                cell.textContent = text;
                item.appendChild(cell);
            });

            const activate = () => {
                try { sessionStorage.removeItem('entryNavContext'); } catch (e) { /* storage unavailable */ }
                const exam = this.examContextId ? `&exam=${this.examContextId}` : '';
                window.location.href = `entry_detail.html?id=${note.entry_id}${exam}`;
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

            // A date-only string is a LOCAL day (#534). `new Date('YYYY-MM-DD')`
            // parses it as UTC midnight, which names the previous day west
            // of Greenwich -- #471's defect on the heatmap, here again.
            const date = LocalDate.parse(entry.date_encountered);
            const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

            // Built from text nodes, never innerHTML (#525). The subject name
            // is plain text a student types or imports, and a profile or
            // subject import can carry anything, so `<img onerror=...>` in
            // one ran when this page opened. The reflection is stored
            // rich-text HTML: it reads as its words, through the same inert
            // reduction the entry browser's card uses (text_preview.js).
            const toText = html => (window.WimiTextPreview
                ? window.WimiTextPreview.htmlToPreviewText(html) : '');
            const note = toText(entry.reflection) || toText(entry.explanation)
                || 'No notes';
            [
                ['recent-entry-date', dateStr],
                ['recent-entry-subject', entry.subject_name || ''],
                ['recent-entry-note', note],
            ].forEach(([className, text]) => {
                const cell = document.createElement('div');
                cell.className = className;
                cell.textContent = text;
                item.appendChild(cell);
            });

            // Open the entry, at the same URL the entry browser and the entry
            // form use. The row is announced as a button, so pressing it has
            // to go somewhere (#464).
            const activate = () => {
                // entry_detail reads a prev/next list the entry browser leaves
                // in sessionStorage; one left from an earlier browse would
                // draw a stale "N of M" bar around an entry opened from here.
                try { sessionStorage.removeItem('entryNavContext'); } catch (e) { /* storage unavailable */ }
                const exam = this.examContextId ? `&exam=${this.examContextId}` : '';
                window.location.href = `entry_detail.html?id=${entry.entry_id}${exam}`;
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
     * Render the Related Topics panel (issue #14).
     *
     * Its predecessor, "Related Topics (Siblings)", listed the other
     * children of this subject's parent — two topics can share a parent
     * and have nothing to do with each other, and for a multi-parent
     * subject it was wrong in a way the student could not detect. The
     * replacement is a *semantic* relation the student wrote
     * ("hypertension leads to hypertensive nephrosclerosis"), and
     * nothing structural was carried over.
     *
     * The panel fetches its own data so a slow or failed relations read
     * never delays the rest of this page — nothing else here may break
     * when relations are empty, sparse or wrong (decision 10). The
     * active parent context is passed through because it **orders** the
     * list (decision 5); there is no filter on this path and none
     * should be added.
     */
    renderRelations() {
        const mount = document.getElementById('relationsMount');
        if (!mount || typeof SubjectRelationsPanel === 'undefined') {
            return;
        }
        if (!this.relationsPanel) {
            this.relationsPanel = new SubjectRelationsPanel({
                mount,
                subjectId: this.subjectId,
                examContextId: this.examContextId,
            });
        }
        // Not awaited: the panel renders itself when its fetch lands.
        this.relationsPanel.load(
            this.activeParentId, this.subjectData.subject_name
        );
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
            // Text nodes (#548): the child-focus line quotes a subject name.
            const icon = document.createElement('div');
            icon.className = 'recommendation-icon';
            icon.textContent = rec.icon;
            const text = document.createElement('div');
            text.className = 'recommendation-text';
            text.textContent = rec.text;
            item.append(icon, text);
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
        // Whole calendar days between two LOCAL days (#534). This parsed the
        // date-only `last_mistake_date` as UTC midnight and measured to the
        // current instant, so west of Greenwich a mistake logged today read
        // "1 day ago" for the evening. Local midnight to local midnight, and
        // rounded, because a DST day is 23 or 25 hours long.
        const date = LocalDate.parse(dateStr);
        const today = LocalDate.parse(LocalDate.today());
        return Math.round((today - date) / (1000 * 60 * 60 * 24));
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
