/**
 * WIMI — Related Topics panel (issue #14).
 *
 * Student-authored semantic relations between subjects, rendered as a
 * one-hop list on the subject deep dive. The decisions this file
 * implements, because each of them is a thing a later edit would
 * plausibly "fix" in the wrong direction:
 *
 * - **Decision 1: no graph.** A list. D3 is already loaded on this page
 *   and it will be tempting; every surviving system in the research
 *   hides its graph. Resist it.
 * - **Decision 2: the reason is mandatory.** Save stays disabled until
 *   a subject is chosen *and* the sentence is non-blank. There is no
 *   "add now, explain later".
 * - **Decision 4: directional, rendered from both ends.** One stored
 *   row shows as "Leads to" on the from-subject and "Caused by" on the
 *   to-subject.
 * - **Decision 5: the context selector ORDERS this panel, it never
 *   filters it.** The backend returns the same set for every context;
 *   this file simply renders the order it is given. Do not add a
 *   client-side filter on `context_parent_ids`.
 * - **Decision 6: relations may cross dimensions**, and the other end's
 *   dimension is labelled when it differs.
 * - **Decision 11: degrade to absent.** With zero relations nothing but
 *   a single quiet "Link a related topic" action is rendered — no card,
 *   no heading, no empty state. Zero is the normal state for months.
 */

const RELATION_STRENGTHS = [
    { value: 3, label: 'Certain' },
    { value: 2, label: 'Likely' },
    { value: 1, label: 'Possible' },
    { value: -1, label: 'Checked — not related' }
];

class SubjectRelationsPanel {
    /**
     * @param {Object} options
     * @param {HTMLElement} options.mount - the (unstyled, untagged)
     *     placeholder the panel renders into. It stays empty apart from
     *     the add action when there are no relations.
     * @param {number} options.subjectId
     * @param {number|null} options.examContextId - carried into the
     *     links so navigating to a related subject keeps the exam.
     */
    constructor({ mount, subjectId, examContextId }) {
        this.mount = mount;
        this.subjectId = subjectId;
        this.examContextId = examContextId || null;
        this.subjectName = '';
        this.activeParentId = null;
        this.payload = null;
        this.modal = null;
        this._searchTimer = null;
    }

    // ---------------------------------------------------------------- data

    /**
     * Load and render for the given parent context.
     *
     * `primaryParentId` reaches the backend, which reorders the list.
     * It never shortens it — see decision 5. A failure is swallowed to
     * a console warning and an absent panel: nothing else on the deep
     * dive may break because relations are empty, sparse or wrong
     * (decision 10).
     */
    async load(primaryParentId, subjectName) {
        this.activeParentId = primaryParentId === undefined
            ? this.activeParentId
            : primaryParentId;
        if (subjectName) {
            this.subjectName = subjectName;
        }
        if (!this.mount || !window.api || !api.getSubjectRelations) {
            return;
        }
        try {
            this.payload = await api.getSubjectRelations({
                subjectId: this.subjectId,
                primaryParentId: this.activeParentId
            });
        } catch (err) {
            console.warn('Could not load subject relations:', err);
            this.payload = null;
        }
        this.render();
    }

    // ---------------------------------------------------------------- render

    render() {
        if (!this.mount) return;
        const relations = (this.payload && this.payload.relations) || [];
        this.mount.innerHTML = '';

        if (relations.length === 0) {
            // Decision 11. No card, no heading, no empty state — one
            // unobtrusive action and otherwise nothing. Asserting the
            // *absence* of the panel is a regression test in
            // tests/wimi_test/scenarios/.
            this.mount.appendChild(this._buildAddButton(true));
            return;
        }

        const section = document.createElement('section');
        section.className = 'relations-section';
        section.setAttribute('data-testid', 'deep-dive-relations-panel');

        const card = document.createElement('div');
        card.className = 'relations-card';

        const header = document.createElement('div');
        header.className = 'relations-header';
        const title = document.createElement('h2');
        title.className = 'card-title';
        title.textContent = 'Related Topics';
        header.appendChild(title);
        header.appendChild(this._buildAddButton(false));
        card.appendChild(header);

        if (this.payload.fanin_over_cap) {
            const note = document.createElement('p');
            note.className = 'relations-fanin-note';
            note.setAttribute('data-testid', 'deep-dive-relations-fanin-note');
            note.textContent =
                `${this.payload.incoming_count} topics now point at this one. ` +
                `Past about ${this.payload.fanin_soft_cap} the list gets hard ` +
                `to hold in your head — worth checking whether some of them ` +
                `are really the same idea.`;
            card.appendChild(note);
        }

        const list = document.createElement('div');
        list.className = 'relations-list';
        list.setAttribute('data-testid', 'deep-dive-relations-list');
        relations.forEach(relation => list.appendChild(this._buildRow(relation)));
        card.appendChild(list);

        section.appendChild(card);
        this.mount.appendChild(section);
    }

    _buildAddButton(bare) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'relations-add' + (bare ? ' relations-add--bare' : '');
        button.setAttribute('data-testid', 'deep-dive-relations-add');
        button.textContent = bare
            ? '+ Link a related topic'
            : '+ Link another topic';
        button.addEventListener('click', () => this.openModal());
        return button;
    }

    _buildRow(relation) {
        const item = document.createElement('article');
        item.className = 'relation-item';
        item.setAttribute('data-testid', `deep-dive-relation-${relation.relation_id}`);
        item.setAttribute('data-direction', relation.direction);
        item.setAttribute('data-refuted', String(!!relation.is_refuted));
        // Exposed so a regression scenario can assert decision 5's
        // ordering by tier rather than by guessing at row positions.
        item.setAttribute('data-context-rank', String(relation.context_rank));

        const head = document.createElement('div');
        head.className = 'relation-head';

        const direction = document.createElement('span');
        direction.className = 'relation-direction';
        direction.setAttribute(
            'data-testid', `deep-dive-relation-direction-${relation.relation_id}`);
        direction.textContent = this._directionLabel(relation);
        head.appendChild(direction);

        const link = document.createElement('a');
        link.className = 'relation-subject';
        link.setAttribute(
            'data-testid', `deep-dive-relation-subject-${relation.relation_id}`);
        link.textContent = relation.other_subject_name;
        link.href = `subject_deep_dive.html?subject=${relation.other_subject_id}`
            + (this.examContextId ? `&exam=${this.examContextId}` : '');
        head.appendChild(link);

        if (relation.crosses_dimension && relation.other_dimension_name) {
            const dim = document.createElement('span');
            dim.className = 'relation-dimension';
            dim.setAttribute(
                'data-testid',
                `deep-dive-relation-dimension-${relation.relation_id}`);
            dim.textContent = relation.other_dimension_name;
            dim.title =
                `${relation.other_subject_name} sits in the `
                + `${relation.other_dimension_name} dimension.`;
            head.appendChild(dim);
        }

        const strength = document.createElement('span');
        strength.className = 'relation-strength';
        strength.setAttribute(
            'data-testid', `deep-dive-relation-strength-${relation.relation_id}`);
        strength.textContent = relation.strength_label;
        head.appendChild(strength);

        head.appendChild(this._buildRemoveButton(relation));
        item.appendChild(head);

        const reason = document.createElement('p');
        reason.className = 'relation-reason';
        reason.setAttribute(
            'data-testid', `deep-dive-relation-reason-${relation.relation_id}`);
        reason.textContent = relation.reason;
        item.appendChild(reason);

        if (relation.other_subject_path) {
            const path = document.createElement('span');
            path.className = 'relation-path';
            path.textContent = relation.other_subject_path;
            item.appendChild(path);
        }

        return item;
    }

    /**
     * Decision 4's two faces of one row.
     *
     * A refuted relation is neither: it is a note that the student
     * checked the pair and found nothing, so it says so instead of
     * asserting a direction it does not have.
     */
    _directionLabel(relation) {
        if (relation.is_refuted) {
            return 'Checked against';
        }
        return relation.direction === 'outgoing' ? 'Leads to' : 'Caused by';
    }

    /**
     * Two-step remove. The first click arms the button, the second
     * commits — deliberately inline rather than a `confirm()` dialog,
     * which blocks the Qt web view and cannot be driven from a test.
     */
    _buildRemoveButton(relation) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'relation-remove';
        button.setAttribute(
            'data-testid', `deep-dive-relation-remove-${relation.relation_id}`);
        button.textContent = 'Remove';
        button.title = 'Remove this relation';
        button.addEventListener('click', async () => {
            if (button.getAttribute('data-armed') !== 'true') {
                button.setAttribute('data-armed', 'true');
                button.textContent = 'Remove?';
                return;
            }
            try {
                await api.deleteSubjectRelation(relation.relation_id);
            } catch (err) {
                console.error('Could not remove relation:', err);
            }
            await this.load();
        });
        return button;
    }

    // ---------------------------------------------------------------- modal

    openModal() {
        this.closeModal();
        const modal = document.createElement('div');
        modal.className = 'relation-modal';
        modal.setAttribute('data-testid', 'relation-modal');
        modal.innerHTML = this._modalMarkup();
        document.body.appendChild(modal);
        this.modal = modal;
        this._chosen = null;

        const $ = sel => modal.querySelector(`[data-testid="${sel}"]`);
        modal.querySelector('.modal-backdrop')
            .addEventListener('click', () => this.closeModal());
        $('relation-modal-close').addEventListener('click', () => this.closeModal());
        $('relation-cancel').addEventListener('click', () => this.closeModal());
        $('relation-direction').addEventListener('change', () => {
            this._refreshDirectionCopy();
            // The candidate list is direction-aware, so a change
            // invalidates both the choice and the results behind it.
            this._chosen = null;
            $('relation-chosen').hidden = true;
            $('relation-fanin-warning').hidden = true;
            this._refreshSaveState();
            this._runSearch($('relation-search').value);
        });
        $('relation-reason').addEventListener('input', () => this._refreshSaveState());
        $('relation-search').addEventListener('input', e => {
            this._chosen = null;
            $('relation-chosen').hidden = true;
            $('relation-fanin-warning').hidden = true;
            this._refreshSaveState();
            this._queueSearch(e.target.value);
        });
        $('relation-save').addEventListener('click', () => this._save());

        this._refreshDirectionCopy();
        this._refreshSaveState();
        $('relation-search').focus();
    }

    closeModal() {
        if (this.modal && this.modal.parentNode) {
            this.modal.parentNode.removeChild(this.modal);
        }
        this.modal = null;
        if (this._searchTimer) {
            clearTimeout(this._searchTimer);
            this._searchTimer = null;
        }
    }

    _modalMarkup() {
        const name = escapeRelationHtml(this.subjectName || 'this topic');
        const options = RELATION_STRENGTHS.map(s =>
            `<option value="${s.value}"${s.value === 2 ? ' selected' : ''}>`
            + `${escapeRelationHtml(s.label)}</option>`
        ).join('');
        return `
            <div class="modal-backdrop"></div>
            <div class="modal-content" role="dialog" aria-modal="true"
                 aria-label="Link a related topic">
                <div class="modal-header">
                    <h3>Link a related topic</h3>
                    <button type="button" class="modal-close"
                            data-testid="relation-modal-close"
                            aria-label="Close">&times;</button>
                </div>
                <div class="modal-body">
                    <p class="relation-modal-lede">
                        Relations are yours to write. Say how
                        <strong>${name}</strong> connects to another topic in
                        your own words — writing it is the part that sticks.
                    </p>

                    <div class="relation-field">
                        <label for="relationDirection">Direction</label>
                        <select id="relationDirection" data-testid="relation-direction">
                            <option value="outgoing">${name} leads to&hellip;</option>
                            <option value="incoming">${name} is caused by&hellip;</option>
                        </select>
                    </div>

                    <div class="relation-field">
                        <label for="relationSearch">The other topic</label>
                        <input type="text" id="relationSearch"
                               data-testid="relation-search"
                               autocomplete="off"
                               placeholder="Search this exam's subjects&hellip;">
                        <div class="relation-results"
                             data-testid="relation-results" hidden></div>
                        <div class="relation-chosen"
                             data-testid="relation-chosen" hidden></div>
                        <p class="relation-warning"
                           data-testid="relation-fanin-warning" hidden></p>
                        <p class="relation-hint">
                            Any subject in this exam, including one in another
                            dimension.
                        </p>
                    </div>

                    <div class="relation-field">
                        <label for="relationReason">
                            Why are they related?
                            <span class="relation-required">required</span>
                        </label>
                        <textarea id="relationReason" data-testid="relation-reason"
                                  placeholder="e.g. Chronic hypertension scleroses the afferent arteriole, which is how it ends up as a renal lesion."></textarea>
                        <p class="relation-hint" data-testid="relation-reason-hint">
                            One sentence is plenty. A relation without a reason
                            is just a bookmark, so this field is required.
                        </p>
                    </div>

                    <div class="relation-field">
                        <label for="relationStrength">How sure are you?</label>
                        <select id="relationStrength" data-testid="relation-strength">
                            ${options}
                        </select>
                        <p class="relation-hint">
                            "Checked — not related" is worth recording: it is a
                            conclusion you reached, and it stops you re-checking
                            the same pair.
                        </p>
                    </div>

                    <p class="relation-error" data-testid="relation-error" hidden></p>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn-secondary"
                            data-testid="relation-cancel">Cancel</button>
                    <button type="button" class="btn-primary"
                            data-testid="relation-save" disabled>Save relation</button>
                </div>
            </div>
        `;
    }

    _refreshDirectionCopy() {
        if (!this.modal) return;
        const direction = this.modal.querySelector(
            '[data-testid="relation-direction"]').value;
        const hint = this.modal.querySelector(
            '[data-testid="relation-reason-hint"]');
        hint.textContent = direction === 'outgoing'
            ? 'One sentence on how this topic leads to the other. A relation '
              + 'without a reason is just a bookmark, so this field is required.'
            : 'One sentence on how the other topic leads to this one. A relation '
              + 'without a reason is just a bookmark, so this field is required.';
    }

    /**
     * Decision 2, at the control that enforces it: no subject or no
     * sentence means no save. Both halves, every time the user types.
     */
    _refreshSaveState() {
        if (!this.modal) return;
        const reason = this.modal.querySelector(
            '[data-testid="relation-reason"]').value.trim();
        const save = this.modal.querySelector('[data-testid="relation-save"]');
        save.disabled = !(this._chosen && reason.length > 0);
    }

    _queueSearch(query) {
        if (this._searchTimer) clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this._runSearch(query), 200);
    }

    async _runSearch(query) {
        if (!this.modal) return;
        const box = this.modal.querySelector('[data-testid="relation-results"]');
        const term = (query || '').trim();
        if (term.length < 2) {
            box.hidden = true;
            box.innerHTML = '';
            return;
        }
        let results = [];
        try {
            results = await api.searchRelatableSubjects({
                subjectId: this.subjectId,
                query: term,
                limit: 8,
                // Direction-aware so a subject already related the other
                // way is still offered — closing a cycle from the second
                // subject's page is legitimate content (decision 7).
                direction: this.modal.querySelector(
                    '[data-testid="relation-direction"]').value
            });
        } catch (err) {
            console.warn('Relation subject search failed:', err);
        }
        if (!this.modal) return;
        box.innerHTML = '';
        if (!results || results.length === 0) {
            box.hidden = true;
            return;
        }
        results.forEach(result => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'relation-result';
            button.setAttribute('data-testid', `relation-result-${result.id}`);
            button.innerHTML =
                `${escapeRelationHtml(result.name)}`
                + (result.crosses_dimension && result.dimension_name
                    ? ` <span class="relation-dimension">`
                      + `${escapeRelationHtml(result.dimension_name)}</span>`
                    : '')
                + `<span class="relation-result-path">`
                + `${escapeRelationHtml(result.path || '')}</span>`;
            button.addEventListener('click', () => this._choose(result));
            box.appendChild(button);
        });
        box.hidden = false;
    }

    _choose(result) {
        if (!this.modal) return;
        this._chosen = result;
        const box = this.modal.querySelector('[data-testid="relation-results"]');
        box.hidden = true;
        box.innerHTML = '';
        this.modal.querySelector('[data-testid="relation-search"]').value =
            result.name;

        const chosen = this.modal.querySelector('[data-testid="relation-chosen"]');
        chosen.textContent = result.path || result.name;
        chosen.hidden = false;

        // The soft fan-in cap, said before the relation is written
        // rather than after. Advisory only — the save button is
        // untouched by it.
        const warning = this.modal.querySelector(
            '[data-testid="relation-fanin-warning"]');
        if (result.fanin_over_cap) {
            warning.textContent =
                `${result.name} already has ${result.incoming_count} topics `
                + `pointing at it. That is about where a list stops being `
                + `readable — still fine to add, just worth a look first.`;
            warning.hidden = false;
        } else {
            warning.hidden = true;
        }
        this._refreshSaveState();
    }

    async _save() {
        if (!this.modal || !this._chosen) return;
        const modal = this.modal;
        const reason = modal.querySelector(
            '[data-testid="relation-reason"]').value.trim();
        const direction = modal.querySelector(
            '[data-testid="relation-direction"]').value;
        const strength = parseInt(
            modal.querySelector('[data-testid="relation-strength"]').value, 10);
        const error = modal.querySelector('[data-testid="relation-error"]');
        const save = modal.querySelector('[data-testid="relation-save"]');

        // Belt and braces for decision 2: the button is disabled without
        // a sentence, but a paste-then-delete race must not slip past.
        if (!reason) {
            error.textContent =
                'Write a line on how the two topics are related — that '
                + 'sentence is the whole point of recording this.';
            error.hidden = false;
            return;
        }

        save.disabled = true;
        error.hidden = true;
        try {
            await api.createSubjectRelation({
                fromSubjectId: direction === 'outgoing'
                    ? this.subjectId : this._chosen.id,
                toSubjectId: direction === 'outgoing'
                    ? this._chosen.id : this.subjectId,
                reason,
                strength
            });
        } catch (err) {
            // The database layer writes these messages for the student;
            // show them rather than a generic failure.
            error.textContent = (err && err.message) || String(err);
            error.hidden = false;
            save.disabled = false;
            return;
        }
        this.closeModal();
        await this.load();
    }
}

/** Minimal escape — subject names and dimension names are user input. */
function escapeRelationHtml(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

window.SubjectRelationsPanel = SubjectRelationsPanel;
