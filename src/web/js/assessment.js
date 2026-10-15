/**
 * Psychometric self-assessment page controller (#766 Wave 2, plan Stage 3).
 *
 * One item at a time, three sections in fixture order, attention checks
 * rendered exactly like the items around them. Every answer is sent to the
 * bridge the moment Next is pressed, so leaving the page loses nothing and
 * startAssessment() resumes at the first unanswered item (decision 6).
 *
 * Passive only (decision 3): on completion the page shows the student their
 * own scores and offers the dashboard. Nothing else in WIMI reads them yet.
 *
 * Built with DOM nodes, not innerHTML -- the prompts are data from a fixture
 * that Wave 5 will populate from published papers (test_web_escaping.py).
 *
 * The page ships `inert` and this script releases it (docs/guides/PAGE_GATE.md).
 * Every exit of init() releases the gate, including failure: a permanently
 * inert page is a worse bug than any error it could be hiding.
 */

/* Exposed on window on purpose: a top-level `const` is a script-scope
 * binding that a scenario's eval_js cannot reach (CLAUDE.md, Testing). */
window.AssessmentState = {
    assessmentId: null,
    instrumentVersion: 'v1',
    sections: [],          // from startAssessment, in order
    items: [],             // flattened, each with sectionIdx
    index: 0,              // position in items (0-based)
    responses: {},         // item_code -> raw_response, for back-navigation
    itemShownAt: null,
    completed: false,
    isLoading: true,
    error: null,
};

(function () {
    'use strict';

    const state = window.AssessmentState;
    const GATE_FAIL_OPEN_MS = 15000;
    let gateReleased = false;

    // ----------------------------------------------------------- elements

    function $(id) { return document.getElementById(id); }

    const el = {};
    function bindElements() {
        el.page = document.querySelector('.assessment-page');
        el.sectionLabel = $('assessment-section-label');
        el.progress = $('assessment-progress');
        el.progressFill = $('assessment-progress-fill');
        el.progressLabel = $('assessment-progress-label');
        el.itemCard = $('assessment-item');
        el.prompt = $('assessment-prompt');
        el.options = $('assessment-options');
        el.prev = $('assessment-prev');
        el.next = $('assessment-next');
        el.done = $('assessment-done');
        el.scores = $('assessment-scores');
        el.doneNote = $('assessment-done-note');
        el.error = $('assessment-error');
        el.errorText = $('assessment-error-text');
    }

    // ---------------------------------------------------------------- gate

    function markAssessmentReady(message) {
        if (gateReleased) return;
        gateReleased = true;
        state.isLoading = false;
        if (el.page) el.page.removeAttribute('inert');
        // After removeAttribute, inside a try, behind a typeof check (#127):
        // nothing added for assistive tech may leave the page gated.
        try {
            if (typeof PageGate !== 'undefined') {
                PageGate.release(message || 'Assessment ready.');
            }
        } catch (err) {
            console.warn('PageGate.release failed; the page is released anyway:', err);
        }
    }

    // ------------------------------------------------------------- helpers

    function show(node) { node.classList.remove('hidden'); }
    function hide(node) { node.classList.add('hidden'); }

    function text(tag, content, className) {
        const n = document.createElement(tag);
        if (className) n.className = className;
        n.textContent = content;
        return n;
    }

    function flatten(sections) {
        const out = [];
        sections.forEach(function (sec, sectionIdx) {
            sec.items.forEach(function (it) {
                out.push(Object.assign({}, it, { sectionIdx: sectionIdx }));
            });
        });
        return out;
    }

    function firstUnanswered(items, answered) {
        for (let i = 0; i < items.length; i++) {
            if (!answered.has(items[i].item_code)) return i;
        }
        return items.length - 1;
    }

    function scaleFor(item) {
        return state.sections[item.sectionIdx].scale;
    }

    // -------------------------------------------------------------- render

    function render() {
        const item = state.items[state.index];
        const section = state.sections[item.sectionIdx];
        const total = state.items.length;
        const n = state.index + 1;

        el.sectionLabel.textContent =
            'Section ' + (item.sectionIdx + 1) + ' of ' + state.sections.length +
            ' · ' + section.title;

        const pct = Math.round((state.index / total) * 100);
        el.progressFill.style.width = pct + '%';
        el.progress.setAttribute('aria-valuenow', String(state.index));
        el.progress.setAttribute('aria-valuemax', String(total));
        el.progressLabel.textContent = 'Question ' + n + ' of ' + total;

        el.prompt.textContent = item.prompt;

        // Options: one labelled radio per scale point, built as nodes.
        while (el.options.firstChild) el.options.removeChild(el.options.firstChild);
        const scale = scaleFor(item);
        const chosen = state.responses[item.item_code];
        for (let v = scale.min; v <= scale.max; v++) {
            const anchor = scale.anchors[v - scale.min] || String(v);
            const label = document.createElement('label');
            label.className = 'assessment-option' + (chosen === v ? ' is-selected' : '');
            const input = document.createElement('input');
            input.type = 'radio';
            input.name = 'assessment-answer';
            input.value = String(v);
            input.checked = chosen === v;
            input.addEventListener('change', onSelect);
            label.appendChild(input);
            label.appendChild(text('span', anchor));
            el.options.appendChild(label);
        }

        el.prev.disabled = state.index === 0;
        el.next.disabled = chosen === undefined;
        el.next.textContent = (state.index === total - 1) ? 'Finish' : 'Next';

        state.itemShownAt = Date.now();
    }

    function onSelect(evt) {
        const item = state.items[state.index];
        state.responses[item.item_code] = parseInt(evt.target.value, 10);
        Array.prototype.forEach.call(el.options.children, function (label) {
            label.classList.toggle('is-selected', label.firstChild.checked);
        });
        el.next.disabled = false;
    }

    // -------------------------------------------------------------- flow

    async function onNext() {
        const item = state.items[state.index];
        const raw = state.responses[item.item_code];
        if (raw === undefined) return;
        const elapsed = state.itemShownAt ? Date.now() - state.itemShownAt : 0;
        el.next.disabled = true;
        try {
            await api.submitAssessmentResponse({
                assessmentId: state.assessmentId,
                itemCode: item.item_code,
                rawResponse: raw,
                responseTimeMs: elapsed,
            });
        } catch (err) {
            showError('Your answer could not be saved: ' + (err && err.message ? err.message : err));
            el.next.disabled = false;
            return;
        }
        if (state.index === state.items.length - 1) {
            await finish();
            return;
        }
        state.index += 1;
        render();
        focusFirstOption();
    }

    function onPrev() {
        if (state.index === 0) return;
        // Going back does not un-submit; re-answering re-submits (UPSERT).
        state.index -= 1;
        render();
        focusFirstOption();
    }

    async function finish() {
        let record;
        try {
            record = await api.finishAssessment(state.assessmentId);
        } catch (err) {
            showError('The assessment could not be completed: ' + (err && err.message ? err.message : err));
            el.next.disabled = false;
            return;
        }
        state.completed = true;
        renderDone(record);
    }

    const SCORE_ROWS = [
        ['nfc_total', 'Need for Cognition'],
        ['lgo_learning', 'Learning orientation'],
        ['lgo_prove', 'Prove orientation'],
        ['lgo_avoid', 'Avoid orientation'],
        ['importance_exam', 'Importance: exam'],
        ['importance_clinical', 'Importance: clinical'],
        ['importance_mastery', 'Importance: mastery'],
        ['importance_reflection', 'Importance: reflection'],
    ];

    function renderDone(record) {
        hide(el.itemCard);
        while (el.scores.firstChild) el.scores.removeChild(el.scores.firstChild);
        SCORE_ROWS.forEach(function (row) {
            const value = record ? record[row[0]] : null;
            el.scores.appendChild(text('dt', row[1]));
            if (value === null || value === undefined) {
                el.scores.appendChild(text('dd', 'not scored', 'is-empty'));
            } else {
                el.scores.appendChild(text('dd', Number(value).toFixed(2)));
            }
        });
        if (record && record.attention_check_pass === false) {
            el.doneNote.textContent =
                'One or more attention checks were not answered as instructed, ' +
                'so these scores should be read with that in mind.';
            show(el.doneNote);
        } else {
            hide(el.doneNote);
        }
        el.progressFill.style.width = '100%';
        el.progress.setAttribute('aria-valuenow', el.progress.getAttribute('aria-valuemax'));
        el.progressLabel.textContent = 'Complete';
        el.sectionLabel.textContent = 'All sections answered';
        show(el.done);
        const heading = el.done.querySelector('h2');
        if (heading) heading.focus();
    }

    function showError(message) {
        state.error = message;
        el.errorText.textContent = message;
        show(el.error);
    }

    function focusFirstOption() {
        const first = el.options.querySelector('input[type="radio"]');
        if (first) first.focus();
    }

    // ---------------------------------------------------------- keyboard

    function onKeydown(evt) {
        if (state.completed) return;
        if (evt.target && evt.target.tagName === 'BUTTON') return;
        // Digits pick an option when the scale has that many points.
        if (/^[1-9]$/.test(evt.key)) {
            const item = state.items[state.index];
            const scale = scaleFor(item);
            const v = parseInt(evt.key, 10);
            if (v >= scale.min && v <= scale.max) {
                const input = el.options.querySelector('input[value="' + v + '"]');
                if (input) { input.checked = true; input.dispatchEvent(new Event('change', { bubbles: true })); input.focus(); }
                evt.preventDefault();
            }
            return;
        }
        if (evt.key === 'Enter' && !el.next.disabled) {
            evt.preventDefault();
            onNext();
        }
    }

    // ------------------------------------------------------------- init

    async function init() {
        bindElements();
        // Fail open: if the bridge never answers, the page is still a page.
        const failOpen = setTimeout(function () {
            if (!gateReleased) {
                showError('The assessment did not load. You can go back to the dashboard and try again.');
                markAssessmentReady('Assessment could not load.');
            }
        }, GATE_FAIL_OPEN_MS);

        try {
            const data = await api.startAssessment(state.instrumentVersion);
            state.assessmentId = data.assessment_id;
            state.instrumentVersion = data.instrument_version;
            state.sections = data.sections;
            state.items = flatten(data.sections);

            const answered = new Set(data.answered_item_codes || []);
            if (answered.size) {
                // Resuming: restore what was chosen so Previous shows it.
                const rows = await api.getAssessmentResponses(state.assessmentId);
                rows.forEach(function (r) { state.responses[r.item_code] = r.raw_response; });
            }
            state.index = firstUnanswered(state.items, answered);

            el.prev.addEventListener('click', onPrev);
            el.next.addEventListener('click', onNext);
            document.addEventListener('keydown', onKeydown);

            render();
            clearTimeout(failOpen);
            markAssessmentReady(answered.size
                ? 'Assessment ready, resuming where you left off.'
                : 'Assessment ready.');
        } catch (err) {
            clearTimeout(failOpen);
            showError('The assessment could not be started: ' + (err && err.message ? err.message : err));
            markAssessmentReady('Assessment could not load.');
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
