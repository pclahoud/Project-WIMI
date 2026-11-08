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

        // #898 Wave 4 -- the difficulty and time card. One instance for the
        // page's life (its heading, tip and tabs are drawn once); each
        // parent-context change only reloads it with the new scope.
        this.difficultyTimeCard = null;

        // #848 Wave 2b — the Quick note dialog. The exam's subjects are read
        // once, the first time the dialog opens, and kept: they name the
        // dialog's chips and fill the subject chooser.
        this.quickNoteSubjects = null;
        this.quickNoteOpening = false;
        this.noticeTimer = null;

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

        this.initQuickNote();

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
            this.renderDifficultyTime();
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
    /**
     * #898 Wave 4 -- the difficulty and time card, for this subject.
     *
     * Scoped exactly as the Statistics figure beside it: the exam, this
     * subject, and the parent context chosen in Subject Info. The backend
     * counts through `_deep_dive_counted_entries_sql`, which copies
     * `get_subject_deep_dive`'s own population (primary only, this
     * subject's subtree, the parent context's lenient rule), and a parity
     * test holds the two together -- so the card's total is the Total
     * Mistakes number, and a context change moves both. Its links carry
     * `counted_subject` / `counted_parent`, so a quadrant lands the entry
     * browser on the same count rather than on the finding rule's wider set.
     *
     * Called from loadSubjectData, which the parent selector re-runs, so a
     * context change reloads the card with the new scope. The median stays
     * exam-wide (the plan's default), which the tip says.
     *
     * With no exam the card cannot place anything -- fast and slow are
     * measured against a median over one exam -- so it is not drawn, and a
     * sentence says why rather than leaving a blank.
     */
    renderDifficultyTime() {
        const mount = document.getElementById('difficultyTimeSection');
        if (!mount || typeof DifficultyTimeCard === 'undefined') return;

        if (!this.examContextId) {
            this.difficultyTimeCard = null;
            mount.replaceChildren();
            const note = document.createElement('p');
            note.className = 'dt-no-exam';
            note.setAttribute('data-testid', 'deep-dive-difficulty-time-no-exam');
            note.textContent =
                'Difficulty and time spent is not shown: this page was opened without an ' +
                'exam, and fast and slow are measured against your median time on one exam. ' +
                'Open this subject from the analytics dashboard with an exam chosen to see it.';
            mount.appendChild(note);
            return;
        }

        if (!this.difficultyTimeCard) {
            this.difficultyTimeCard = new DifficultyTimeCard({
                mount,
                scope: {},
                testid: 'deep-dive-difficulty-time',
                tipTestid: 'deep-dive-info-difficulty-time',
                tip: SubjectDeepDive.DIFFICULTY_TIME_TIP,
                subtitle: 'Your mistakes whose main subject is this one or a subject ' +
                    'beneath it, sorted by how hard you rated each question and how ' +
                    'long you spent on it.',
                emptyScope: 'this subject',
            });
        }
        this.difficultyTimeCard.load({
            examContextId: this.examContextId,
            subjectId: this.subjectId,
            primaryParentId: this.activeParentId,
        });
    }

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
     * A row for a note with an origin copies `renderRecentEntries`, not
     * invented: same `entryNavContext` clearing, same URL shape, same
     * Enter/Space handling. #464 established that a row announced as a
     * button has to go somewhere. A note on no entry (#848) has no entry to
     * open, so its row opens the Quick note dialog on it instead (Wave 2b).
     * That makes two behaviours on one list, which is honest only because
     * every row's meta line names its own: "Entry #N · Opens the entry", or
     * "Note on its own · Opens in Quick note".
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
            // Every row is a button again (#848 Wave 2b). #464 settled that a
            // row announced as a button has to go somewhere, and now each one
            // does: a note with an origin opens that entry, and a note on no
            // entry -- which arrives with NO `entry_id` key, absent rather
            // than null, the convention this payload's `dimension_id` uses --
            // opens the Quick note dialog on itself for editing. Wave 0 drew
            // that second kind as text because it had nowhere to go yet.
            item.setAttribute('role', 'button');
            item.setAttribute('tabindex', '0');
            const onEntry = ('entry_id' in note);

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

            const cell = (className, text) => {
                const node = document.createElement(text === undefined ? 'div' : 'span');
                node.className = className;
                if (text !== undefined) node.textContent = text;
                return node;
            };
            const dateCell = document.createElement('div');
            dateCell.className = 'subject-note-date';
            dateCell.textContent = dateStr;
            const main = cell('subject-note-main');
            const bodyCell = document.createElement('div');
            bodyCell.className = 'subject-note-body';
            bodyCell.textContent = body;

            // The meta line names what the row opens (the mockup's "Opens
            // ..." label). Two behaviours on one list are honest only because
            // each row says which it has.
            const meta = cell('subject-note-meta');
            // Not under the row's own `deep-dive-subject-note-` prefix, which
            // scenarios use to count the rows.
            meta.setAttribute('data-testid', `deep-dive-note-meta-${note.note_id}`);
            let activate;
            if (onEntry) {
                meta.appendChild(cell('subject-note-tag', `Entry #${note.entry_id}`));
                // The origin's own attachment is one of the count; the rest
                // are the other entries the note is on.
                const others = Math.max(0, (Number(note.attachment_count) || 0) - 1);
                if (others > 0) {
                    meta.appendChild(cell('subject-note-others',
                        `and ${others} other${others === 1 ? '' : 's'}`));
                }
                meta.appendChild(cell('subject-note-opens', 'Opens the entry'));
                activate = () => {
                    try { sessionStorage.removeItem('entryNavContext'); } catch (e) { /* storage unavailable */ }
                    const exam = this.examContextId ? `&exam=${this.examContextId}` : '';
                    window.location.href = `entry_detail.html?id=${note.entry_id}${exam}`;
                };
            } else {
                meta.appendChild(cell('subject-note-tag subject-note-tag-free', 'Note on its own'));
                meta.appendChild(cell('subject-note-opens', 'Opens in Quick note'));
                activate = () => { this.openQuickNote({ editNoteId: note.note_id }); };
            }
            main.append(bodyCell, meta);
            item.append(dateCell, main);

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

    // =====================================================================
    // Quick note (#848 Wave 2b): the entry form's dialog, on this page
    // =====================================================================

    /**
     * The header button and Ctrl+Shift+N. The shortcut that opens the dialog
     * here is the document keydown. The `wimi:editor-shortcut` listener is the
     * entry form's second route (the chord rich_editor.js re-emits from inside
     * a TinyMCE iframe, whose keydowns never reach this document), but the
     * only rich editor on this page is the Quick note dialog's own, so on the
     * deep dive that route only arrives while the dialog is open: the press is
     * swallowed and `openQuickNote()` refuses it, as it refuses while any
     * dialog is open.
     */
    initQuickNote() {
        const btn = document.getElementById('btn-quick-note');
        if (btn) btn.addEventListener('click', () => this.openQuickNote());
        const isChord = (key, mods) => !!mods.ctrlKey && !!mods.shiftKey
            && !mods.altKey && !mods.metaKey
            && typeof key === 'string' && key.toUpperCase() === 'N';
        document.addEventListener('keydown', (e) => {
            if (!isChord(e.key, e)) return;
            e.preventDefault();
            this.openQuickNote();
        });
        document.addEventListener('wimi:editor-shortcut', (e) => {
            const d = e.detail || {};
            if (!isChord(d.key, d)) return;
            e.preventDefault();
            this.openQuickNote();
        });
    }

    /** The exam's subjects, read once. Never throws: a failed read is an empty list. */
    async loadQuickNoteSubjects() {
        if (this.quickNoteSubjects) return this.quickNoteSubjects;
        let list = [];
        if (this.examContextId) {
            try {
                const read = await api.getAllSubjectsForExam(this.examContextId);
                list = Array.isArray(read) ? read : [];
            } catch (err) {
                console.error('Quick note: could not read the exam subjects', err);
            }
        }
        // This page's own subject names its chip even if the read missed it.
        if (this.subjectId && !list.some(s => s && s.id === this.subjectId)) {
            const name = this.subjectData && this.subjectData.subject_name;
            if (name) list = [{ id: this.subjectId, name, path: name }, ...list];
        }
        this.quickNoteSubjects = list;
        return list;
    }

    /**
     * Open the dialog: on a new note pre-tagged with this subject, or -- from
     * a "Note on its own" row -- on that note for editing, which is the state
     * Your notes' Edit sets (quick_note.js `edit`). The note is read fresh by
     * id rather than from this page's payload, which carries no tags.
     */
    async openQuickNote({ editNoteId = null } = {}) {
        if (typeof QuickNote === 'undefined' || QuickNote.isOpen()) return false;
        if (window.ModalDialog && window.ModalDialog.openSurfaces().length > 0) return false;
        if (this.quickNoteOpening) return false;
        this.quickNoteOpening = true;
        try {
            const subjects = await this.loadQuickNoteSubjects();
            let edit = null;
            if (editNoteId !== null) {
                try {
                    edit = await api.getNote(editNoteId);
                } catch (err) {
                    this.notify('Could not open the note',
                        err && err.message ? err.message : String(err), 'error');
                    return false;
                }
            }
            const subjectName = (this.subjectData && this.subjectData.subject_name) || '';
            QuickNote.open({
                subjects,
                subjectIds: this.subjectId ? [this.subjectId] : [],
                entryChoice: (this.examContextId && this.subjectId)
                    ? { examContextId: this.examContextId, subjectId: this.subjectId, subjectName }
                    : null,
                edit,
                chooseSubjects: (currentIds) => this.chooseNoteSubjects(subjects, currentIds),
                // The page re-reads its payload, so a note saved or edited
                // with this subject's tag is listed below straight away.
                onSaved: () => { this.loadSubjectData({ skipParentEdges: true }); },
                onDeleted: () => { this.loadSubjectData({ skipParentEdges: true }); },
                notify: (title, text, kind) => this.notify(title, text, kind),
            });
            return true;
        } finally {
            this.quickNoteOpening = false;
        }
    }

    /** The dialog's notify, in this page's voice: one live line under the header. */
    notify(title, text, kind) {
        const box = document.getElementById('deepDiveNotice');
        if (!box) return;
        if (this.noticeTimer) clearTimeout(this.noticeTimer);
        box.textContent = [title, text].filter(Boolean).join('. ').replace(/\.\./g, '.');
        box.classList.add('deep-dive-notice-shown');
        box.classList.toggle('deep-dive-notice-error', kind === 'error');
        this.noticeTimer = setTimeout(() => {
            box.textContent = '';
            box.classList.remove('deep-dive-notice-shown', 'deep-dive-notice-error');
        }, 8000);
    }

    /**
     * The subject chooser the dialog's Subjects… button opens on this page.
     *
     * The entry form's chooser (`openNoteSubjectChooser`) lives in
     * question_entry.js and is built around that entry's own subjects and
     * the form's search widget, so it is not a shared module; this is the
     * smallest chooser over the exam's subject list: a search, a list of
     * checkboxes with each subject's path, Save and Cancel. Resolves to the
     * ticked ids on Save and to `null` on Cancel, Escape or a backdrop
     * click, which is the contract `QuickNote.open`'s `chooseSubjects` asks.
     */
    chooseNoteSubjects(subjects, currentIds) {
        const all = Array.isArray(subjects) ? subjects.filter(s => s && Number.isInteger(s.id)) : [];
        const chosen = new Set(Array.isArray(currentIds) ? currentIds : []);
        const opener = document.activeElement;
        const SHOW = 50;

        return new Promise((resolve) => {
            const old = document.getElementById('deep-dive-subject-chooser');
            if (old) old.remove();

            const backdrop = document.createElement('div');
            backdrop.className = 'modal-backdrop qn-chooser-backdrop active';
            backdrop.id = 'deep-dive-subject-chooser';
            const surface = document.createElement('div');
            surface.className = 'modal qn-chooser';
            surface.setAttribute('data-modal-surface', '');
            surface.setAttribute('role', 'dialog');
            surface.setAttribute('aria-modal', 'true');
            surface.setAttribute('aria-labelledby', 'deep-dive-subject-chooser-title');
            surface.setAttribute('data-testid', 'deep-dive-subject-chooser');

            const title = document.createElement('h2');
            title.className = 'modal-title qn-title';
            title.id = 'deep-dive-subject-chooser-title';
            title.textContent = 'Quick note — Assign Subjects';
            const hint = document.createElement('p');
            hint.className = 'qn-hint';
            hint.textContent = 'Tick the subjects this note is about. Search to find any subject in this exam.';
            const searchLabel = document.createElement('label');
            searchLabel.className = 'qn-visually-hidden';
            searchLabel.htmlFor = 'deep-dive-subject-chooser-search';
            searchLabel.textContent = 'Search subjects';
            const search = document.createElement('input');
            search.type = 'search';
            search.id = 'deep-dive-subject-chooser-search';
            search.className = 'qn-pick-search';
            search.placeholder = 'Search subjects…';
            search.setAttribute('data-testid', 'deep-dive-subject-chooser-search');
            const list = document.createElement('div');
            list.className = 'qn-chooser-list';
            list.setAttribute('role', 'group');
            list.setAttribute('aria-labelledby', title.id);
            list.setAttribute('data-testid', 'deep-dive-subject-chooser-list');
            const more = document.createElement('p');
            more.className = 'qn-hint';
            more.setAttribute('role', 'status');
            const actions = document.createElement('div');
            actions.className = 'qn-chooser-actions';
            const cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'btn btn-secondary';
            cancel.textContent = 'Cancel';
            cancel.setAttribute('data-testid', 'deep-dive-subject-chooser-cancel');
            const save = document.createElement('button');
            save.type = 'button';
            save.className = 'btn btn-primary';
            save.textContent = 'Save';
            save.setAttribute('data-testid', 'deep-dive-subject-chooser-save');
            actions.append(cancel, save);
            surface.append(title, hint, searchLabel, search, list, more, actions);
            backdrop.appendChild(surface);

            const option = (s) => {
                const label = document.createElement('label');
                label.className = 'qn-chooser-option';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.value = String(s.id);
                cb.checked = chosen.has(s.id);
                cb.setAttribute('data-testid', `deep-dive-subject-chooser-option-${s.id}`);
                cb.addEventListener('change', () => {
                    if (cb.checked) chosen.add(s.id); else chosen.delete(s.id);
                });
                const name = document.createElement('span');
                name.textContent = s.name || `Subject #${s.id}`;
                label.append(cb, name);
                if (s.path && s.path !== s.name) {
                    const path = document.createElement('span');
                    path.className = 'qn-chooser-path';
                    path.textContent = s.path;
                    label.appendChild(path);
                }
                return label;
            };
            const render = () => {
                const q = search.value.trim().toLowerCase();
                // The ticked subjects always stay in view, so one can be
                // unticked whatever the search says.
                const ticked = all.filter(s => chosen.has(s.id));
                const rest = all.filter(s => !chosen.has(s.id) && (!q
                    || String(s.name || '').toLowerCase().includes(q)
                    || String(s.path || '').toLowerCase().includes(q)));
                list.replaceChildren(...ticked.map(option), ...rest.slice(0, SHOW).map(option));
                more.textContent = rest.length > SHOW
                    ? `Showing ${SHOW} of ${rest.length} subjects. Type to narrow them.`
                    : (all.length === 0 ? 'This exam has no subjects to tag.' : '');
            };
            search.addEventListener('input', render);

            const finish = (result) => {
                document.removeEventListener('keydown', onKey);
                backdrop.remove();
                // Back to the Subjects… button inside the Quick note dialog,
                // before modal_dialog.js restores focus to an invoker behind it.
                if (opener && document.contains(opener) && typeof opener.focus === 'function') {
                    try { opener.focus(); } catch (err) { /* nothing to restore to */ }
                }
                resolve(result);
            };
            const onKey = (e) => {
                if (e.key !== 'Escape' || e.defaultPrevented) return;
                if (window.ModalDialog && window.ModalDialog.topmost() !== surface) return;
                e.preventDefault();
                finish(null);
            };
            cancel.addEventListener('click', () => finish(null));
            save.addEventListener('click', () => {
                // In the list's order, so the chips read as the list did. A
                // tag the list does not hold (a subject archived since the
                // note was tagged) is kept rather than dropped unseen.
                const listed = all.filter(s => chosen.has(s.id)).map(s => s.id);
                const unlisted = [...chosen].filter(id => !listed.includes(id));
                finish([...listed, ...unlisted]);
            });
            backdrop.addEventListener('click', (e) => { if (e.target === backdrop) finish(null); });
            document.addEventListener('keydown', onKey);

            render();
            document.body.appendChild(backdrop);
            search.focus();
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

/**
 * The deep dive's tip for the difficulty and time card, word for word from
 * docs/planning/DIFFICULTY_TIME_CARD_PLAN.md ("Tip text"), chosen under the
 * owner's delegation on #898 (comment 12219).
 * test_difficulty_time_card_on_the_deep_dive.py pins it.
 */
SubjectDeepDive.DIFFICULTY_TIME_TIP =
    'The same four groups, for mistakes whose main subject is this one or a ' +
    'subject beneath it. Fast and slow use your median for the whole exam, so ' +
    'they mean the same here as on the dashboard.';

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.subjectDeepDive = new SubjectDeepDive();
});
