/**
 * WIMI - First-run tour runner (#430)
 *
 * Shows a page's tour steps from `window.WIMI_TOUR_STEPS` (generated into
 * tour_steps.js from the manual's `<!-- tour -->` blocks), one at a time, with
 * a spotlight on the element each step describes.
 *
 * THREE DECISIONS SHAPE IT, all recorded on #430:
 *
 *   - A step is shown once it can be (owner, 2026-10-09). A visit shows only
 *     the steps whose target is rendered right now and records them as seen;
 *     the rest wait for a later visit. Measured on the dashboard, a true first
 *     run can point at 1 of its 5 steps, so a tour that needed every target
 *     would never run and one that showed absent steps would point at nothing.
 *   - An anchor is an identifier, resolved as `[data-tour-anchor]` (first
 *     rendered match, for an element repeated per card, #618) and then
 *     `[data-testid]` (#625). Anything else is unconverted prose and resolves
 *     to nothing. `tests/wimi_test/scenarios/test_tour_anchors_resolve.py` fails
 *     on that, so a page cannot ship a step it can never show.
 *   - A fork (#620) picks `fork_anchor` when the page's named predicate is true.
 *     The page computes the predicate once, where it already decides the same
 *     thing, and registers it here. It is never re-derived from the DOM.
 *
 * Two more from #682 (owner, 2026-10-10): steps run in screen order, not the
 * manual's (inScreenOrder), and steps sharing an anchor are one step shown as
 * slides (stopsFor).
 *
 * NOT `modal_dialog.js`, deliberately (#430). That helper writes `aria-hidden`
 * on everything outside the dialog, which would hide the very element a step
 * describes. A tour is the inverse of a modal: the page behind it stays
 * perceivable, visually and in the accessibility tree. So the panel is a
 * non-modal dialog that names its target in its own text.
 *
 * Skip is offered from the first step, and Escape does the same. Skip marks
 * every step of this page as seen, including ones not yet shown, because a
 * student who skipped did not ask to be interrupted again on a later visit.
 * Replay in Settings undoes it.
 */
(function () {
    'use strict';

    const IDENTIFIER = /^[a-z0-9-]+$/;
    /**
     * Steps the manual carries that the page must not show yet, keyed as
     * stepKey() keys them. A held step is never queued and never marked seen,
     * not even by Skip, so a student who skipped still sees it once it is
     * released. inspect() still lists it, so the resolve guard keeps proving
     * its anchor renders.
     *
     * **Empty, and that is the expected state.** It is the mechanism, not a
     * list anything has to stay on.
     *
     * tree-editor:tree-row-weight was held here from #677 to #664's fix: its
     * text says WIMI never compares a child's weight with its parent's, and
     * the feasibility badge one row away did. The badge is gone (#664, owner
     * 2026-10-10), the sentence is true, and the step is released. Nothing
     * else has needed holding.
     */
    const HELD = new Set([]);
    const predicates = {};
    let active = null;
    // Keys shown whose seen-write is still in flight, so a re-start cannot
    // re-queue them. Emptied as each write lands, so Replay still works on a
    // page that stays open.
    const shown = new Set();
    let startCalls = 0;
    /**
     * Each stop's tip number on this page, given when it is first shown and
     * kept through redraws. The counter is a running number, "Tip 6", with no
     * total (#682, owner 2026-10-10): a total counts only the targets
     * rendered when the queue was built, so a step that renders later started
     * a new "Tip 1 of 1" straight after "Tip 5 of 5", and a rebuild mid-tour
     * sent "Tip 2 of 5" back to "Tip 1 of 5" (both measured on 11f4932). The
     * queue's length is still written to the counter as data-tour-total, so
     * showing a total again is a one-line change if long pages want it.
     */
    const tipNumbers = new Map();

    function registerPredicate(name, fn) {
        predicates[name] = fn;
    }

    function stepKey(page, step) {
        return `${page}:${step.anchor}`;
    }

    function isRendered(el) {
        if (!el || !el.isConnected) return false;
        if (el.closest('[hidden], .hidden')) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    /** The first rendered element carrying this anchor identifier, or null. */
    function resolveAnchor(id) {
        if (typeof id !== 'string' || !IDENTIFIER.test(id)) return null;
        for (const attr of ['data-tour-anchor', 'data-testid']) {
            for (const el of document.querySelectorAll(`[${attr}="${id}"]`)) {
                if (isRendered(el)) return el;
            }
        }
        return null;
    }

    /**
     * Which anchor this step points at now: the fork's, when its predicate holds.
     *
     * A predicate's source can be tri-state, and this collapses "unknown" to
     * false ON PURPOSE: the step then points at its unforked anchor. That is
     * safe on the dashboard only because its unknown state (exams not loaded,
     * or a failed load) paints NEITHER side, so nothing resolves and the step
     * waits. A page whose unknown state does paint its unforked anchor must
     * not inherit this, or it would show the no-X text while the truth is
     * unknown (#289, #174). That page needs null to mean "show neither" here,
     * and a predicate registered without the `=== true` collapse.
     */
    function anchorFor(step) {
        if (step.fork) {
            const predicate = predicates[step.fork];
            let holds = false;
            try {
                holds = typeof predicate === 'function' && predicate() === true;
            } catch (e) {
                holds = false;
            }
            if (holds) return step.fork_anchor;
        }
        return step.anchor;
    }

    function stepsFor(page) {
        return ((window.WIMI_TOUR_STEPS || {})[page]) || [];
    }

    /** The steps a student may be shown: this page's, less any held. */
    function showableSteps(page) {
        return stepsFor(page).filter(step => !HELD.has(stepKey(page, step)));
    }

    /**
     * The showable steps as tour stops: steps that share an anchor are ONE
     * stop shown as slides, in the manual's order (#682, owner 2026-10-10:
     * the question bank pane is a second QWebEngineView the tour cannot
     * reach, so it is explained by several slides on the entry form's
     * button). The gate allows that only within one chapter and with no fork.
     *
     * A stop keeps the `page:anchor` key its first step always had, so every
     * key already stored keeps meaning the step it meant. A key per slide was
     * rejected: a position suffix (`#2`) moves when a slide is inserted, and a
     * returning student would then skip the new slide and see an old one
     * again. Two consequences, both accepted with the stable key:
     *   - the slides are recorded seen together, on the last one (showStep),
     *     so leaving part way shows the sequence again, while Skip on slide 1
     *     records them all and Replay is the way back;
     *   - a slide added later to an explainer a student has seen is not shown
     *     to them.
     */
    function stopsFor(page) {
        const stops = new Map();
        for (const step of showableSteps(page)) {
            const key = stepKey(page, step);
            if (stops.has(key)) stops.get(key).slides.push(step);
            else stops.set(key, { key, step, slides: [step], order: stops.size });
        }
        return [...stops.values()];
    }

    /**
     * Stops in the order they sit on screen now: top to bottom, then left to
     * right (#682, owner 2026-10-10). The manual's order was chapter order,
     * which on analytics put the exam filter at the top of the page fourth.
     *
     * Rows are bands, not exact tops (sameRow). Measured on master 11f4932,
     * exact tops put Settings' Save (top 130, right edge) before Reset
     * defaults (top 131, left edge) in one toolbar, and the entry browser's
     * 18 px Drafts checkbox sits 21 px below the top of the 40 px search box
     * it is centred beside.
     * Ties go to the manual's order, written into the comparator rather than
     * left to the engine's sort stability: an element and its container can
     * share a top-left corner.
     *
     * Two consequences, by design: two steps from one chapter may be
     * separated, and a layout change reorders a page's tour with no test
     * failing. Positions are read from the screen when the queue is built.
     */
    /**
     * One row when the smaller box's vertical centre lies within the larger
     * box, and the larger is at most three times as tall. The height bound is
     * what keeps a container out of its contents' rows: the entry form's
     * whole-form step spans every field's centre.
     */
    function sameRow(a, b) {
        const [small, big] = a.height <= b.height ? [a, b] : [b, a];
        const centre = small.top + small.height / 2;
        return big.height <= 3 * small.height && centre >= big.top && centre <= big.bottom;
    }

    function inScreenOrder(entries) {
        const byTop = [...entries].sort((a, b) =>
            a.box.top - b.box.top || a.box.left - b.box.left || a.order - b.order);
        const rows = [];
        for (const entry of byTop) {
            const row = rows[rows.length - 1];
            if (row && sameRow(row[0].box, entry.box)) {
                row.push(entry);
            } else {
                rows.push([entry]);
            }
        }
        return rows.flatMap(row => row.sort((a, b) =>
            a.box.left - b.box.left || a.order - b.order));
    }

    /**
     * For the resolve guard: every step on this page and what it resolves to
     * in the page's current state. Read-only; shows nothing.
     */
    function inspect(page) {
        return stepsFor(page).map(step => {
            const anchor = anchorFor(step);
            return {
                key: stepKey(page, step),
                held: HELD.has(stepKey(page, step)),
                anchor: step.anchor,
                fork: step.fork || null,
                fork_anchor: step.fork_anchor || null,
                used: anchor,
                identifier: IDENTIFIER.test(step.anchor)
                    && (!step.fork || IDENTIFIER.test(step.fork_anchor || '')),
                resolved: !!resolveAnchor(anchor),
            };
        });
    }

    /**
     * The element's own name, so the panel can say what it points at.
     *
     * A form field has no text of its own, so its name is its `<label>` (or
     * `aria-labelledby`), which is also what assistive tech reads. Without
     * that an input titled its panel "About this". A label's trailing
     * required-field asterisk is dropped: it marks the field, it is not
     * part of its name.
     */
    function nameOf(el) {
        const clean = t => (t || '').replace(/\s+/g, ' ').trim();
        const labelledBy = (el.getAttribute('aria-labelledby') || '').split(/\s+/)
            .map(id => id && document.getElementById(id)).filter(Boolean)
            .map(n => n.textContent).join(' ');
        const fieldLabel = el.labels && el.labels.length ? el.labels[0].textContent : '';
        const label = clean(el.getAttribute('aria-label')) || clean(labelledBy)
            || clean(fieldLabel).replace(/\s*\*+$/, '') || clean(el.getAttribute('title'));
        return shorten(label || clean(renderedText(el)));
    }

    /**
     * A name past 60 characters, cut so that no figure is left half-printed
     * (#672). The tree editor's total names its axis before its band, so a long
     * axis name pushed "…total 97–142% of the exam." past the old fixed cut at
     * 57 and the title read "total 97…": a number the student is invited to
     * complete and was never shown.
     *
     * 1. Cut at the last space at or before character 57 (nameOf has already
     *    collapsed whitespace to single spaces). A figure is then whole or
     *    absent: "…Physician Task / Competency total…".
     * 2. No space there, so the first 57 characters are one token: cut at 57,
     *    backing up to the start of a figure the cut would land inside. A
     *    figure is a band as one unit (FIGURE), so "97–142%" is never cut to
     *    "97–". It does not span spaces: "97 – 142" is two figures.
     * 3. Nothing left before that figure: no name at all, so the panel says
     *    "About this" rather than print part of a number.
     *
     * The cap holds in every branch, which bounds the panel's height as well
     * as its width; `overflow-wrap: anywhere` on .wimi-tour-title (tour.css)
     * makes a 57-character token wrap inside the panel.
     */
    const TITLE_MAX = 60;
    const FIGURE = /[0-9][0-9.,\u2013-]*%?/g;
    function shorten(name) {
        if (name.length <= TITLE_MAX) return name;
        const limit = TITLE_MAX - 3;
        let cut = name.lastIndexOf(' ', limit);
        if (cut <= 0) {
            cut = limit;
            for (const m of name.matchAll(FIGURE)) {
                if (m.index < cut && cut < m.index + m[0].length) cut = m.index;
            }
            if (cut === 0) return '';
        }
        return name.slice(0, cut).trimEnd() + '…';
    }

    /**
     * The element's text AS WRITTEN, from its rendered descendants only.
     *
     * Not innerText: innerText is the text as painted, so CSS text-transform
     * reaches it, and an uppercased heading titled its panel "About: WEEKLY
     * GOAL". A tour title is a name, not a rendering. Not plain textContent
     * either, which would read hidden children (a `display: none` node has no
     * client rects, and that is the test used here).
     *
     * This matters beyond one heading: `text-transform: uppercase` is on ~48
     * rules across the stylesheets, including the tree editor's details-panel
     * eyebrows, whose copy and typography are a PARKED decision (#346). If a
     * title reads in capitals, fix it here, never by changing the CSS: the tour
     * must not become the reason that parked copy changes.
     *
     * Text under `aria-hidden="true"` is left out, as the accessible name
     * leaves it out: it is decoration, not part of the name. The dictation
     * button's dot (dictation.js) titled its panel "About: ● Speak".
     */
    function renderedText(el) {
        const parts = [];
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
            const parent = n.parentElement;
            if (parent && parent.getClientRects().length > 0 && !ariaHidden(parent, el)) {
                parts.push(n.textContent);
            }
        }
        return parts.join(' ');
    }

    function ariaHidden(node, root) {
        for (let n = node; n; n = n === root ? null : n.parentElement) {
            if (n.getAttribute('aria-hidden') === 'true') return true;
        }
        return false;
    }

    function make(tag, attrs, text) {
        const el = document.createElement(tag);
        Object.entries(attrs || {}).forEach(([k, v]) => el.setAttribute(k, v));
        if (text) el.textContent = text;
        return el;
    }

    function place() {
        if (!active) return;
        const { ring, panel, target } = active;
        const r = target.getBoundingClientRect();
        const pad = 6;
        Object.assign(ring.style, {
            top: `${r.top - pad}px`, left: `${r.left - pad}px`,
            width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px`,
        });
        const gap = 12;
        const below = r.bottom + gap;
        const panelHeight = panel.offsetHeight;
        const top = below + panelHeight <= window.innerHeight
            ? below : Math.max(gap, r.top - gap - panelHeight);
        const left = Math.min(Math.max(gap, r.left),
            Math.max(gap, window.innerWidth - panel.offsetWidth - gap));
        Object.assign(panel.style, { top: `${top}px`, left: `${left}px` });
    }

    /** Close the open step. `restoreFocus` false when a view change rebuilds
     *  the tour: focus belongs to whatever the student just pressed. */
    function teardown(restoreFocus = true) {
        if (!active) return;
        window.removeEventListener('resize', place);
        window.removeEventListener('scroll', place, true);
        document.removeEventListener('keydown', active.onKey, true);
        active.ring.remove();
        active.panel.remove();
        const back = active.returnFocus;
        active = null;
        if (restoreFocus && back && back.isConnected && typeof back.focus === 'function') {
            back.focus();
        }
    }

    async function markSeen(keys) {
        try {
            await api.markTourStepsSeen(keys);
        } catch (e) {
            console.error('Could not record tour steps:', e);
        }
    }

    function showStep(page, queue, index, focus = true, slide = 0) {
        const slides = queue[index].slides;
        const step = slides[slide];
        const target = queue[index].target;
        target.scrollIntoView({ block: 'nearest', inline: 'nearest' });

        const ring = active ? active.ring : make('div', {
            class: 'wimi-tour-ring', 'aria-hidden': 'true', 'data-testid': 'tour-ring',
        });
        const panel = active ? active.panel : make('div', {
            class: 'wimi-tour-panel', role: 'dialog', 'aria-modal': 'false',
            'aria-labelledby': 'wimi-tour-title', 'aria-describedby': 'wimi-tour-text',
            'data-testid': 'tour-panel', tabindex: '-1',
            // A tip may describe a control inside an open modal (the tree
            // editor's import preview). modal_dialog.js then leaves its focus
            // alone and does not hide it from assistive tech.
            'data-modal-companion': '', 'data-modal-keep-announced': '',
        });
        panel.replaceChildren();

        const what = nameOf(target);
        const key = queue[index].key;
        if (!tipNumbers.has(key)) tipNumbers.set(key, tipNumbers.size + 1);
        panel.appendChild(make('p', { class: 'wimi-tour-count', 'data-testid': 'tour-count',
            'data-tour-total': String(queue.length) }, `Tip ${tipNumbers.get(key)}`));
        panel.appendChild(make('h2', { class: 'wimi-tour-title', id: 'wimi-tour-title',
            'data-testid': 'tour-title' }, what ? `About: ${what}` : 'About this'));
        // The tip counter counts stops; a stop with slides says where in them
        // the student is, so "Tip 3" does not stand still for five Nexts. Its
        // slides all render with their one target, so this total is known.
        if (slides.length > 1) {
            panel.appendChild(make('p', { class: 'wimi-tour-count', 'data-testid': 'tour-slide' },
                `${slide + 1} of ${slides.length}`));
        }
        panel.appendChild(make('p', { class: 'wimi-tour-text', id: 'wimi-tour-text',
            'data-testid': 'tour-text' }, step.text));
        if (step.link) {
            panel.appendChild(make('a', { class: 'wimi-tour-more', href: step.link,
                'data-testid': 'tour-more' }, `Read more in "${step.chapter_title}"`));
        }
        const actions = make('div', { class: 'wimi-tour-actions' });
        const skip = make('button', { type: 'button', class: 'btn btn-ghost btn-sm',
            'data-testid': 'tour-skip' }, 'Skip tips');
        const lastSlide = slide === slides.length - 1;
        const last = index === queue.length - 1 && lastSlide;
        const next = make('button', { type: 'button', class: 'btn btn-primary btn-sm',
            'data-testid': 'tour-next' }, last ? 'Done' : 'Next');
        actions.append(skip, next);
        panel.appendChild(actions);

        skip.addEventListener('click', () => skipAll(page));
        next.addEventListener('click', () => {
            if (!lastSlide && isRendered(target)) {
                showStep(page, queue, index, true, slide + 1);
                return;
            }
            // Skip a queued step whose target stopped rendering since the
            // queue was built: a view change that made no start() call must
            // not walk the ring onto a hidden control.
            let to = index + 1;
            while (to < queue.length && !isRendered(queue[to].target)) to += 1;
            if (last || to >= queue.length) teardown();
            else showStep(page, queue, to);
        });

        if (!active) {
            const onKey = (event) => {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    skipAll(page);
                } else if (event.key === 'Tab') {
                    tabWithinPanel(event);
                }
            };
            active = { ring, panel, target, onKey, returnFocus: focusHomeFor(target) };
            document.body.append(ring, panel);
            window.addEventListener('resize', place);
            window.addEventListener('scroll', place, true);
            document.addEventListener('keydown', onKey, true);
        }
        active.target = target;
        active.slide = slide;
        place();
        if (focus) panel.focus();
        active.key = key;
        // A stop is recorded seen on its LAST slide (#682, owner 2026-10-10),
        // so a student who leaves part way through a sequence is shown it
        // again rather than never seeing the rest. A one-slide stop's last
        // slide is its first, so for every other step nothing changes. Skip
        // still records the whole page.
        if (lastSlide) {
            shown.add(key);
            markSeen([key]).finally(() => shown.delete(key));
        }
    }

    /**
     * Tab between the panel's own controls, as the browser would, so that an
     * open modal cannot take them away. modal_dialog.js sends any Tab from
     * outside its dialog into the dialog, and a tip shown over one (the tree
     * editor's import preview) sits outside it: measured, a keyboard user
     * could not reach Read more, Skip or Next. That file yields to a Tab the
     * page has already handled, so this handles it. Leaving the panel, past
     * its first or last control, is not handled here, so this is not a trap:
     * with a modal open, modal_dialog.js then takes focus into the dialog.
     */
    function tabWithinPanel(event) {
        if (!active || !active.panel.contains(document.activeElement)) return;
        const items = [...active.panel.querySelectorAll('a[href], button:not([disabled])')];
        const at = items.indexOf(document.activeElement);
        const to = at === -1 ? (event.shiftKey ? -1 : 0) : at + (event.shiftKey ? -1 : 1);
        if (to < 0 || to >= items.length) return;
        event.preventDefault();
        items[to].focus();
    }

    /**
     * Where focus goes when the tip closes: where it was, unless the target is
     * inside an open modal dialog and focus was not, in which case the
     * dialog's first control. Focus left outside an aria-modal dialog is
     * focus in content a reader has been told is not there.
     */
    function focusHomeFor(target) {
        const here = document.activeElement;
        const dialog = target.closest('[aria-modal="true"]');
        if (!dialog || dialog.contains(here)) return here;
        return dialog.querySelector('a[href], button:not([disabled]), input:not([disabled]), '
            + 'select:not([disabled]), textarea:not([disabled])') || here;
    }

    async function skipAll(page) {
        const keys = stopsFor(page).map(stop => stop.key);
        teardown();
        await markSeen(keys);
    }

    /**
     * Show this page's unseen steps whose targets are rendered now.
     * Resolves to the number of steps shown. Never throws: a broken tour must
     * not break the page it sits on.
     *
     * A page calls this on load and again whenever its view changes (a
     * Settings panel, a wizard step). A call while a tour is open REBUILDS it
     * from what renders now: the open step's target may be hidden by the
     * change, and a hidden element stays in the document (`display: none`), so
     * "is it still connected" cannot tell. Overlapping calls: the latest wins.
     *
     * THE OPEN STEP SURVIVES A REBUILD WHILE ITS ANCHOR STILL RENDERS. A step
     * is recorded as seen the moment it is shown, so a rebuild that skipped
     * every seen step would retire the one on screen. That used to be argued
     * harmless ("it was recorded as seen when shown, so nothing is lost"),
     * which holds only when the rebuild comes from a view change that hid it.
     * A page that calls this again with no view change (the wizard re-starts
     * once its template cards load) closed the tip it had just opened, a few
     * milliseconds after showing it, and never showed it again (#430).
     *
     * It is kept by KEY and its anchor resolved afresh, not by the element it
     * pointed at: the tree editor redraws every row with innerHTML, so the
     * element is gone while the same chip renders again in its place. Kept,
     * it is re-drawn without taking focus, unless the panel had it: a tip
     * that did not change must not pull the keyboard out of the tree row the
     * student just pressed.
     */
    async function start(page) {
        const call = ++startCalls;
        try {
            if (typeof api === 'undefined' || !api.getTourState) return 0;
            const state = await api.getTourState();
            if (call !== startCalls) return 0;
            // Read BEFORE teardown(), which nulls `active`: after it this is
            // always null and the open step is dropped again, silently.
            const keep = active && active.key ? active.key : null;
            const keepSlide = active ? active.slide || 0 : 0;
            const panelHadFocus = !!(active && active.panel.contains(document.activeElement));
            teardown(false);
            if (!state || !state.auto_start) return 0;
            // The open step is in `shown` while its seen-write is in flight and
            // in `state.seen` once it lands, so without `keep` it is filtered on
            // EVERY rebuild, not in a window: this is not a race.
            const seen = new Set([...(state.seen || []), ...shown]);
            if (keep) seen.delete(keep);
            let kept = null;
            const rest = [];
            for (const stop of stopsFor(page)) {
                if (seen.has(stop.key)) continue;
                const target = resolveAnchor(anchorFor(stop.step));
                if (!target) continue;
                const entry = { ...stop, target, box: target.getBoundingClientRect() };
                if (stop.key === keep) kept = entry;
                else rest.push(entry);
            }
            // The kept step goes FIRST, because showStep() draws index 0: in
            // screen order, an unseen step above it that has just started
            // rendering would take the ring off the tip being read. On its
            // slide, too: a redraw must not send a student back to slide 1.
            const queue = (kept ? [kept] : []).concat(inScreenOrder(rest));
            if (!queue.length) return 0;
            const redrawn = !!kept;
            const slide = redrawn ? Math.min(keepSlide, kept.slides.length - 1) : 0;
            showStep(page, queue, 0, !redrawn || panelHadFocus, slide);
            return queue.length;
        } catch (e) {
            console.error('Tour failed:', e);
            teardown();
            return 0;
        }
    }

    /** A registered predicate's current value, for the resolve guard. */
    function predicateValue(name) {
        const fn = predicates[name];
        try {
            return typeof fn === 'function' ? fn() === true : null;
        } catch (e) {
            return null;
        }
    }

    window.WimiTour = {
        registerPredicate, start, inspect, resolveAnchor, stepKey, predicateValue,
        isOpen: () => !!active,
    };
})();
