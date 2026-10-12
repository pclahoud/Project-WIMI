/**
 * WIMI relation proposals — the suggestions beside the explanation (#60).
 *
 * The student writes why the correct answer is correct, presses "Find related
 * topics", and a local model proposes relations between subjects their own
 * sentences already name. Each one waits for them to confirm it. Nothing
 * leaves the machine.
 *
 * Mirrors `dictation.js`, which solved the same shape of problem for #59: a
 * worker job beside a writing field, a taxonomy of named failures, and a
 * result that can arrive after the form has moved on.
 *
 * Four decisions this file implements rather than invents
 * ------------------------------------------------------
 *
 * **A press, never automatically** (owner, #380). The first pass of a session
 * loads 845 MB of weights — about 16 seconds and a 2–3 GB peak — so that cost
 * belongs to something the student did. There is no autosave hook here and
 * adding one would need #380 reopened.
 *
 * **Silence when it cannot run** (#5179, #5183). If the status is anything but
 * `ready`, this renders *nothing at all* — no disabled button, no notice, no
 * placeholder. Settings carries the one line that explains why. So an
 * unavailable machine looks exactly like a build without the feature, which
 * is the point: a student who never touches this must never notice it exists.
 *
 * **The passage is the reason, prefilled and editable** (#5494). Each card
 * shows the sentence the proposal came from *in an editable field*, not as
 * static text behind a Confirm button. #14's decision 2 makes the reason
 * mandatory and #60's body says "do not assert a pre-filled label the student
 * clicks past" — so the sentence and the type are both in front of them,
 * changeable, at the moment they confirm. That is the anti-rubber-stamp
 * property, and it is why Confirm is not a one-press accept of something
 * hidden.
 *
 * **Rejecting asks WHICH KIND, and has no default** (m027). #60's own
 * adjudication found **25 of 45 rejections meant "you misread my sentence"**,
 * not "these two are unrelated" — and the two have different scopes. A
 * misread suppresses the pair for this entry only; "not related" suppresses
 * it everywhere. So there are two buttons with two sentences, and no way to
 * reject without choosing.
 *
 * **The scope is the visible text; the reason is the tooltip** (#398, owner's
 * decision 2026-10-06). The two used to be the other way round: the labels
 * named the *claim* ("WIMI misread this" / "Not related") and the `title`
 * carried the reach. A `title` never appears on a touch device, is not shown
 * on keyboard focus, is inconsistently exposed to screen readers and arrives
 * about a second late for a decisive mouse — so a student who hovered neither
 * button chose between two equally weighted presses without being told that
 * one of them suppresses the pair across their whole exam. With the scope
 * invisible, the split the 25-of-45 finding bought was only half delivered.
 * The cost, accepted rather than overlooked: the labels no longer say *why* a
 * student would pick one. The reason moved to the `title`, where it is still
 * available and no longer load-bearing.
 *
 * A named failure RESOLVES; it does not reject
 * --------------------------------------------
 * `api._callBridge` throws on `success=false` and **drops `data`**, so a
 * failure returned that way would arrive with no `kind` — and the branches
 * here are on the kind. Every call therefore checks `result.error` before
 * anything else, exactly as `dictation.js` does.
 *
 * **`wedged` overrides `retryable`.** The taxonomy calls `extraction_timeout`
 * retryable and is right to; a wedged worker is different, because every
 * later attempt fails identically until WIMI restarts. The bridge sets
 * `retryable: false` in that case and carries `wedged: true`; this file reads
 * both rather than re-deriving either (#174).
 *
 * Staleness
 * ---------
 * A pass takes 0.4–8 seconds, and in that window the student may save, move
 * to the next entry, or reset the form. `getContext()` is read at **call
 * time** and the entry id and token are compared when the result lands: a
 * result for a different entry is discarded and said to be, never rendered
 * against whatever is on screen now. That is #59's §3.5, where the same race
 * could corrupt a required field on another entry.
 *
 * What this deliberately does NOT do
 * ----------------------------------
 * **It does not reload proposals on page load.** They are written to the
 * database as unconfirmed rows, but #4695's decision is inline confirmation
 * "not a later review queue", so the list belongs to the press that produced
 * it. An ignored proposal stays invisible until the student runs extraction
 * again (which replaces it) or writes that relation by hand (which adopts
 * it) — both #382.
 */
(function () {
    'use strict';

    /** Poll interval while a pass is running. */
    var POLL_MS = 400;

    /** How long to wait for a single poll before giving up on the job. */
    var MAX_POLLS = 400;  // 160 s, well past the runtime's own 60 s ceiling

    function el(tag, className, attrs) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (attrs) {
            Object.keys(attrs).forEach(function (key) {
                node.setAttribute(key, attrs[key]);
            });
        }
        return node;
    }

    function api() {
        return window.api;
    }

    /**
     * Copy for a failure, by kind.
     *
     * No kind gets a sentence that directs a press the payload says is
     * impossible — `retryable` decides whether the button is drawn at all,
     * and these sentences never contradict it (#174).
     */
    function describeFailure(error, wedged) {
        var kind = (error && error.kind) || 'extraction_failed';
        if (wedged) {
            return 'Something in the model stopped responding. Restart WIMI '
                + 'and it will work again — nothing you wrote is affected.';
        }
        switch (kind) {
            case 'out_of_memory':
                return 'This computer ran out of memory reading your '
                    + 'explanation. Closing some other programs and trying '
                    + 'again usually fixes it.';
            case 'extraction_timeout':
                return 'Reading your explanation took too long and was '
                    + 'stopped.';
            case 'model_missing':
            case 'model_corrupt':
                // "download" means the model and nothing else (#402): the
                // same word names the WIMI you installed, the larger WIMI and
                // this 845 MB fetch, so only the fetch keeps it. Naming the
                // model rather than writing "them" also matches the button
                // this sentence sends the student to, "Download the model".
                return 'The model files are missing or damaged. Settings → '
                    + 'Related Topics can download the model again.';
            case 'model_load_failed':
                return 'The model would not load.';
            case 'unknown_job':
                return 'WIMI lost track of that search.';
            default:
                return 'WIMI could not read your explanation this time.';
        }
    }

    /** Why nothing was started. Each is an ordinary state, not an error. */
    function describeNotStarted(reason) {
        switch (reason) {
            case 'no_explanation':
                return 'Write the explanation first — that is what WIMI '
                    + 'reads.';
            // Client-side only: the bridge never returns this, because a press
            // cannot reach it without an entry to attach a proposal to. It is
            // here rather than inline so the pre-press sentences stay in one
            // place with the ones a refused press produces (#483).
            case 'not_saved':
                return 'Save this entry first — a suggestion has to attach '
                    + 'to it. The autosave does that on its own shortly, or '
                    + 'Save as Draft does it now.';
            case 'no_relation_types':
                return 'This exam has no relation types to look for. '
                    + 'Settings can add some.';
            case 'no_subjects':
                return 'This exam has no subjects yet, so there is nothing '
                    + 'for a relation to join.';
            case 'nothing_found':
                return 'WIMI did not find a relation between your subjects '
                    + 'in what you wrote.';
            default:
                return 'There was nothing to look for this time.';
        }
    }

    function attachRelationProposals(options) {
        var mountEl = options.mountEl;
        var getContext = options.getContext || function () { return {}; };
        var notify = options.notify || function () {};

        if (!mountEl) return null;

        var ready = false;          // the feature can run on this machine
        var token = 0;              // paired with the entry id for staleness
        var running = false;
        var jobId = null;
        var proposals = [];         // what the last pass returned
        var extra = null;           // unmatched/ambiguous counts, or null
        var pendingElsewhere = [];  // pairs waiting on another entry (#390)
        var failure = null;         // {error, wedged} or null
        var notStarted = null;      // a reason string, or null
        var relationTypes = [];     // the exam's active types, for the selects

        var root = el('div', 'relprop');
        // TWO children, and the split is load-bearing. The button's enabled
        // state follows the explanation as the student types, so it is
        // re-drawn often; the cards hold a textarea the student may be part
        // way through editing. Rebuilding the list on every keystroke would
        // throw that edit away -- silently, which is the worst version.
        // `update()` therefore touches only the bar.
        var barEl = el('div', 'relprop-bar-wrap');
        var listEl = el('div', 'relprop-list');

        // The bar is built ONCE and updated in place (#397). It used to be
        // rebuilt on every render, so pressing "Find related topics" removed
        // the very button the student was standing on and focus fell to
        // <body> -- top of a long form, mid-press. Keeping the element is the
        // same principle as the bar/list split above, one level down.
        var bar = el('div', 'relprop-bar');
        var findButton = el('button', 'relprop-find', {
            type: 'button',
            'data-testid': 'entry-form-relations-find'
        });
        findButton.addEventListener('click', start);
        var cancelButton = el('button', 'relprop-cancel', {
            type: 'button',
            'data-testid': 'entry-form-relations-cancel'
        });
        cancelButton.textContent = 'Stop';
        cancelButton.addEventListener('click', stop);
        bar.appendChild(findButton);
        bar.appendChild(cancelButton);

        // The one live region, present from attach so it is in the tree
        // BEFORE anything is written to it -- a region created together with
        // its text is often not announced at all (#397). Visually hidden by
        // clipping, never display:none / visibility:hidden, both of which
        // take it out of the accessibility tree (#127). It holds text only
        // after a press on a `ready` machine: render() empties it whenever
        // `ready` is false, so silence (#5179) stays silence.
        var statusEl = el('p', 'relprop-status', {
            role: 'status',
            'aria-live': 'polite',
            'aria-atomic': 'true',
            'data-testid': 'entry-form-relations-status'
        });

        // Why the Find button cannot be pressed, as VISIBLE text (#398).
        //
        // It used to be the button's `title`, where a keyboard or touch user
        // could never read it: a `title` opens on hover, and a `disabled`
        // button **cannot take focus at all** -- measured on this
        // QtWebEngine, `el.focus()` leaves `document.activeElement`
        // elsewhere, so no Tab can reach it either. A touch screen has no
        // hover, and `title` exposure to screen readers is inconsistent
        // where the element already has a name. So the student most likely
        // to need the sentence is the one who cannot get it.
        //
        // What #398 reasoned from was something else, and it is FALSE here:
        // it said Chromium dispatches no mouse events to a disabled control,
        // so the tooltip could never open for anyone. Measured with a
        // disabled <button> and a disabled <input> on this engine -- both
        // receive pointerover, mouseover, mouseenter and mousemove, and both
        // match :hover. A mouse user probably did see the tooltip. The three
        // reasons above are what this change rests on; see
        // test_relations_find_says_why_it_cannot_run.py.
        //
        // It lives in `barEl` rather than in the list because `update()` is
        // bound to renderBar alone (the cards hold an edit in progress), and
        // this line has to follow the explanation keystroke by keystroke, the
        // same way the button's own enabled state does. The sentence is
        // `describeNotStarted`'s, so the pre-press explanation and the one the
        // bridge gives after a refused press cannot drift apart.
        var hintEl = el('p', 'relprop-hint', {
            id: 'relprop-find-hint',
            'data-testid': 'entry-form-relations-hint'
        });
        // The text is NOT set here. It was, and that was the defect (#483):
        // the button is greyed when the entry is unsaved OR the explanation is
        // empty, and a fixed sentence named only the second. The usual case is
        // the first -- entry_id is null until the first autosave -- so a
        // student who had just typed an explanation was told to write one.
        // renderBar sets it from whichever blocker is real, on every edit.

        root.appendChild(barEl);
        root.appendChild(listEl);
        root.appendChild(statusEl);
        mountEl.appendChild(root);

        // ------------------------------------------------------------ render

        function render() {
            // A render may remove the element that has focus -- the retry
            // button with its failure box, Stop when the pass ends. Note it
            // here and hand focus to the Find button afterwards rather than
            // letting it fall to <body>. Only when focus was already inside
            // this module: a result landing while the student types in
            // another field must never pull them out of it.
            var focused = document.activeElement;
            var hadFocus = !!focused && focused !== root
                && root.contains(focused);
            if (!ready) statusEl.textContent = '';
            renderBar();
            renderList();
            if (hadFocus && !focusable(focused)) focusFind();
        }

        function focusable(node) {
            return root.contains(node) && !node.disabled && !node.hidden;
        }

        function focusFind() {
            if (findButton.parentNode && !findButton.disabled) {
                findButton.focus();
            }
        }

        /**
         * Say something through the live region (#397).
         *
         * Polite, and one channel: every outcome of a press is spoken here
         * exactly once. The entry form's toasts are not a live region, so
         * nothing reaches assistive tech twice today.
         */
        function announce(text) {
            if (!ready) return;
            statusEl.textContent = text || '';
        }

        /**
         * Announce what the list now shows, read back from the list itself.
         *
         * Reading the rendered notes rather than re-deriving their copy keeps
         * the announcement and the screen from drifting apart when a note's
         * wording changes.
         */
        function announceOutcome() {
            var parts = [];
            if (proposals.length) {
                parts.push(proposals.length === 1
                    ? 'WIMI suggests one relation from what you wrote.'
                    : 'WIMI suggests ' + proposals.length
                      + ' relations from what you wrote.');
            }
            Array.prototype.forEach.call(
                listEl.querySelectorAll('.relprop-note, .relprop-failure-text'),
                function (node) { parts.push(node.textContent); });
            announce(parts.join(' '));
        }

        function renderBar() {
            // Silence. Not a disabled button, not a notice -- see the module
            // docstring. The mount stays empty and the page looks like a
            // build without the feature.
            if (!ready && bar.parentNode) barEl.removeChild(bar);
            if (!ready) showHint(false);
            if (!ready) return;
            if (bar.parentNode !== barEl) barEl.appendChild(bar);

            var context = getContext() || {};
            var canRun = !!context.entry_id && !!context.has_explanation;

            findButton.textContent = running
                ? 'Reading your explanation…'
                : 'Find related topics';
            // While a pass runs the button is aria-disabled, NOT disabled.
            // Measured on this QtWebEngine: a focused button that becomes
            // `disabled` drops focus to <body>, so keeping the element alone
            // does not fix #397. start() already ignores a press while
            // running, which is all `disabled` was doing here.
            findButton.disabled = !running && !canRun;
            if (running) {
                findButton.setAttribute('aria-disabled', 'true');
            } else {
                findButton.removeAttribute('aria-disabled');
            }
            // The one case where a disabled control is better than silence:
            // the feature IS available, and the student is a keystroke away
            // from being able to use it. Saying nothing here would read as
            // the button having vanished.
            //
            // The reason is a sentence beside the button, never a `title`
            // (#398) -- see hintEl above for what a disabled control costs a
            // keyboard or touch user. `notStarted` is checked so the same
            // sentence is not drawn twice: a press refused by the bridge puts
            // it in the list already.
            // Name the blocker that is actually in force. Both halves of
            // canRun can be false at once; the explanation is the one the
            // student can act on in place, so it wins.
            var blocker = !context.has_explanation ? 'no_explanation'
                : !context.entry_id ? 'not_saved'
                : null;
            if (blocker) hintEl.textContent = describeNotStarted(blocker);

            // Still de-duplicated against a refusal already in the list, and
            // now only when it would be the SAME sentence -- the old check
            // suppressed the unsaved hint too, which is a different sentence
            // and was never in the list.
            showHint(!canRun && !running && !(blocker && blocker === notStarted));

            cancelButton.hidden = !running;
        }

        /**
         * Draw or remove the reason the Find button is unavailable.
         *
         * Removed from the tree rather than emptied: an empty element would
         * need `:empty` to collapse, which QtWebEngine 6.10 stops
         * re-invalidating (#134/#136/#141), and it would stay in the
         * accessibility tree announcing nothing. `aria-describedby` ties the
         * sentence to the control for a reader that reaches a disabled button
         * in browse mode; the visible text is what everyone else gets.
         */
        function showHint(show) {
            if (show && hintEl.parentNode !== barEl) {
                barEl.appendChild(hintEl);
            } else if (!show && hintEl.parentNode) {
                hintEl.parentNode.removeChild(hintEl);
            }
            if (show) {
                findButton.setAttribute('aria-describedby', hintEl.id);
            } else {
                findButton.removeAttribute('aria-describedby');
            }
        }

        function renderList() {
            listEl.innerHTML = '';
            if (!ready) return;

            if (failure) {
                listEl.appendChild(buildFailure());
                return;
            }
            if (notStarted) {
                var note = el('p', 'relprop-note',
                    {'data-testid': 'entry-form-relations-note'});
                note.textContent = describeNotStarted(notStarted);
                listEl.appendChild(note);
                return;
            }
            if (running) return;

            proposals.forEach(function (proposal) {
                listEl.appendChild(buildCard(proposal));
            });

            pendingElsewhere.forEach(function (pending) {
                listEl.appendChild(buildPendingNote(pending));
            });

            if (extra) listEl.appendChild(buildExtraNote());
        }

        function buildFailure() {
            var box = el('div', 'relprop-failure',
                {'data-testid': 'entry-form-relations-failure'});
            var text = el('p', 'relprop-failure-text');
            text.textContent = describeFailure(failure.error, failure.wedged);
            box.appendChild(text);
            // Drawn from the payload's own answer, never re-derived from the
            // kind. A wedge forces it false (#174).
            if (failure.error && failure.error.retryable && !failure.wedged) {
                var again = el('button', 'relprop-retry', {
                    type: 'button',
                    'data-testid': 'entry-form-relations-retry'
                });
                again.textContent = 'Try again';
                again.addEventListener('click', start);
                box.appendChild(again);
            }
            return box;
        }

        /**
         * The count of relations whose ends are not subjects in this tree.
         *
         * Without it, "no suggestions" would be the same sentence whether the
         * model found nothing or found three connections to things the
         * student has never added as subjects -- and those are very different
         * facts. It is deliberately not actionable: offering to create a
         * subject from here is out of #60's scope.
         */
        function buildExtraNote() {
            var note = el('p', 'relprop-note',
                {'data-testid': 'entry-form-relations-extra'});
            var parts = [];
            if (extra.unmatched) {
                parts.push(extra.unmatched + (extra.unmatched === 1
                    ? ' connection to something that is not a subject in this '
                      + 'exam' : ' connections to things that are not subjects '
                      + 'in this exam'));
            }
            if (extra.ambiguous) {
                // Says what was found, which the first version did not: it
                // read "WIMI also found 2 where a name matches two
                // subjects", leaving "2 what?" unanswered. Its singular and
                // plural arms were also byte-identical, so the ternary was
                // dead (#396).
                parts.push(extra.ambiguous + (extra.ambiguous === 1
                    ? ' name that matches two subjects'
                    : ' names that each match two subjects'));
            }
            // "those" follows the ITEM count, not the number of clauses. The
            // first version keyed on parts.length, so three unmatched
            // connections in one clause read "so it did not suggest that"
            // (#396).
            var items = (extra.unmatched || 0) + (extra.ambiguous || 0);
            note.textContent = 'WIMI also found ' + parts.join(' and ')
                + ', so it did not suggest ' + (items > 1 ? 'those' : 'that')
                + '.';
            return note;
        }

        /**
         * A pair this pass found but cannot offer, because it is already
         * waiting, unanswered, on another entry (#390, owner's decision:
         * say so on the card).
         *
         * Without it the pair simply never appears here, and nothing says
         * why -- the row holding it is invisible by design (#5494) and m026's
         * UNIQUE keeps a second one from being written. The bridge sends only
         * that case: a rejection, a confirmed relation and an archived
         * subject's hidden one are filtered out before this list exists.
         *
         * **No Confirm and no Reject.** There is nothing on THIS entry to
         * answer; the proposal belongs to the entry it names.
         */
        function buildPendingNote(pending) {
            var note = el('p', 'relprop-note', {
                'data-testid': 'entry-form-relations-pending',
                'data-entry-id': String(pending.entry_id)
            });
            var where = [];
            if (pending.session_name) where.push(pending.session_name);
            if (pending.entry_order) where.push('Question ' + pending.entry_order);
            note.textContent = pending.from_subject_name + ' ' + pending.label
                + ' ' + pending.to_subject_name + ' is already suggested on '
                + (where.length ? where.join(' — ') : 'another entry')
                + ', waiting for you there.';
            return note;
        }

        function buildCard(proposal) {
            var card = el('div', 'relprop-card', {
                'data-testid': 'entry-form-relation-proposal',
                'data-relation-id': String(proposal.relation_id)
            });

            var pair = el('p', 'relprop-pair');
            pair.textContent = proposal.from_subject_name + ' '
                + proposal.label + ' ' + proposal.to_subject_name;
            card.appendChild(pair);

            var quote = el('blockquote', 'relprop-passage');
            quote.textContent = proposal.passage;
            card.appendChild(quote);

            // The type, visible and changeable. #4904 measured 11 of 31
            // rejections as "right pair, wrong type" -- fixed by choosing the
            // right one rather than by rejecting a true pair.
            //
            // **No select when the list could not be read**, and this is not
            // cosmetic: an empty select yields '' -> null, which differs from
            // the proposal's own type, so confirming would have UNTYPED the
            // relation. Keeping the proposed type is the only honest answer
            // when the student was never shown a choice.
            var select = null;
            if (relationTypes.length) {
                var typeRow = el('label', 'relprop-field');
                typeRow.textContent = 'Relation';
                select = el('select', 'relprop-type',
                    {'data-testid': 'entry-form-relation-type'});
                relationTypes.forEach(function (type) {
                    var option = el('option');
                    option.value = String(type.id);
                    option.textContent = type.label;
                    if (type.id === proposal.relation_type_id) {
                        option.selected = true;
                    }
                    select.appendChild(option);
                });
                typeRow.appendChild(select);
                card.appendChild(typeRow);
            }

            // The reason, PREFILLED AND EDITABLE rather than hidden behind
            // the button (#5494). A blank one is refused by the database
            // layer, which is decision 2 holding on this path too.
            var reasonRow = el('label', 'relprop-field');
            reasonRow.textContent = 'In your words';
            var reason = el('textarea', 'relprop-reason', {
                rows: '2',
                'data-testid': 'entry-form-relation-reason'
            });
            reason.value = proposal.passage;
            reasonRow.appendChild(reason);
            card.appendChild(reasonRow);

            var actions = el('div', 'relprop-actions');

            // The house primary button supplies the colours AND their hover
            // (#400); `relprop-confirm` only sizes it to match the two
            // rejections beside it. Class first, so the markup test that
            // checks every relprop-* class is styled still parses it.
            var confirm = el('button', 'relprop-confirm btn btn-primary', {
                type: 'button',
                'data-testid': 'entry-form-relation-confirm'
            });
            confirm.textContent = 'Add this relation';
            confirm.addEventListener('click', function () {
                accept(proposal, card, select ? select.value : null,
                       reason.value);
            });
            actions.appendChild(confirm);

            // TWO rejections, because the kind decides the scope and there is
            // no safe default (m027). "Misread" is the common case: 25 of 45.
            //
            // EACH LABEL STATES ITS SCOPE (#398). What a student needs before
            // pressing is what the press *does* -- this entry, or everywhere --
            // and that has to be on screen, because the `title` below reaches
            // neither a touch screen nor a keyboard nor several readers. The
            // two stay the same size, colour and weight: making one quieter
            // would push students toward the global suppression when they meant
            // the local one, which is the same defect wearing different clothes
            // (see relation_proposals.css above `.relprop-reject`).
            var misread = el('button', 'relprop-reject', {
                type: 'button',
                'data-testid': 'entry-form-relation-misread'
            });
            misread.textContent = 'Not in this entry';
            // The REASON, which is what a tooltip is for: context a student
            // may want and does not need in order to choose correctly.
            //
            // An em dash, not `--`. This file's `--` is the repo's ASCII
            // convention for COMMENTS; `title` renders verbatim, and the same
            // file already uses real punctuation in copy the student sees
            // (the wedge sentence, both reject toasts). #396.
            misread.title = 'The two topics may well be related — this '
                + 'sentence just does not say so. WIMI will not suggest it '
                + 'from this entry again.';
            misread.addEventListener('click', function () {
                reject(proposal, card, 'misread');
            });
            actions.appendChild(misread);

            var unrelated = el('button', 'relprop-reject', {
                type: 'button',
                'data-testid': 'entry-form-relation-not-related'
            });
            unrelated.textContent = 'Never related';
            unrelated.title = 'These two topics are not related at all. WIMI '
                + 'will not suggest this pair again anywhere.';
            unrelated.addEventListener('click', function () {
                reject(proposal, card, 'not_related');
            });
            actions.appendChild(unrelated);

            card.appendChild(actions);
            return card;
        }

        // ------------------------------------------------------------ status

        /**
         * Read availability and park the button.
         *
         * Fire and forget from the host's point of view: eight `stat` calls,
         * never a hash, so the form never waits on it. A failure leaves
         * `ready` false, which means silence -- the honest resting state for
         * a page that cannot find out.
         */
        function refresh() {
            if (!api() || typeof api().getRelationExtractionStatus !== 'function') {
                ready = false;
                render();
                return Promise.resolve();
            }
            return api().getRelationExtractionStatus().then(function (status) {
                ready = !!(status && status.ready);
                render();
            }).catch(function () {
                ready = false;
                render();
            });
        }

        function loadTypes(examContextId) {
            if (!api() || typeof api().getRelationTypes !== 'function') {
                return Promise.resolve();
            }
            return api().getRelationTypes({examId: examContextId})
                .then(function (types) { relationTypes = types || []; })
                .catch(function () { relationTypes = []; });
        }

        // ----------------------------------------------------------- the run

        function start() {
            if (running) return;
            var context = getContext() || {};
            if (!context.entry_id || !context.has_explanation) return;

            token += 1;
            var mine = {entry_id: context.entry_id, token: token};
            failure = null;
            notStarted = null;
            proposals = [];
            pendingElsewhere = [];
            extra = null;
            running = true;
            render();
            // Said once at the press: the first pass of a session loads the
            // model and can take many seconds, and the button's new label is
            // not reliably re-read while focus sits on it.
            announce('Reading your explanation…');

            api().proposeRelationsForEntry({
                entryId: mine.entry_id, token: mine.token
            }).then(function (started) {
                // The machine cannot run it after all -- the page was out of
                // step with Settings. Go quiet rather than raise anything.
                if (!started.available) {
                    ready = false;
                    running = false;
                    render();
                    return;
                }
                if (!started.started) {
                    running = false;
                    notStarted = started.reason || 'nothing_to_do';
                    render();
                    announceOutcome();
                    return;
                }
                jobId = started.job_id;
                return poll(mine, 0);
            }).catch(function (error) {
                // A rejection is the bridge unable to do its job at all --
                // no profile open, a malformed request. Not a taxonomy
                // failure, so it carries no kind.
                running = false;
                failure = {error: {kind: 'extraction_failed',
                                   detail: error && error.message,
                                   retryable: true}, wedged: false};
                render();
                announceOutcome();
            });
        }

        function poll(mine, attempt) {
            if (!running || !jobId) return Promise.resolve();
            if (attempt > MAX_POLLS) {
                running = false;
                failure = {error: {kind: 'extraction_timeout', retryable: true},
                           wedged: false};
                render();
                announceOutcome();
                return Promise.resolve();
            }
            return api().pollRelationProposals(jobId).then(function (report) {
                if (report.state === 'running') {
                    return new Promise(function (resolve) {
                        setTimeout(resolve, POLL_MS);
                    }).then(function () { return poll(mine, attempt + 1); });
                }

                running = false;
                jobId = null;

                // Staleness, checked before anything is rendered. A result
                // for an entry the student has left must not be shown against
                // the one in front of them (#59 §3.5).
                var context = getContext() || {};
                var stale = report.entry_id !== mine.entry_id
                    || report.token !== mine.token
                    || context.entry_id !== mine.entry_id;
                if (stale) {
                    var discarded = 'Those suggestions were for a different '
                        + 'entry, so WIMI did not show them.';
                    notify('info', 'Suggestions discarded', discarded);
                    render();
                    announce(discarded);
                    return;
                }

                if (report.state === 'cancelled') {
                    render();
                    announce('Stopped. WIMI did not suggest anything.');
                    return;
                }
                if (report.state === 'failed') {
                    failure = {error: report.error || {}, wedged: !!report.wedged};
                    render();
                    announceOutcome();
                    return;
                }

                proposals = report.proposals || [];
                pendingElsewhere = report.pending_elsewhere || [];
                var unmatched = (report.unmatched || []).length;
                var ambiguous = (report.ambiguous || []).length;
                extra = (unmatched || ambiguous)
                    ? {unmatched: unmatched, ambiguous: ambiguous} : null;
                // A pair waiting elsewhere WAS found, so "did not find a
                // relation" would be false while the note says otherwise.
                if (!proposals.length && !extra && !pendingElsewhere.length) {
                    notStarted = 'nothing_found';
                }
                render();
                announceOutcome();

                if (proposals.length) {
                    notify('info', 'Suggestions ready',
                        proposals.length === 1
                            ? 'WIMI suggests one relation from what you wrote.'
                            : 'WIMI suggests ' + proposals.length
                              + ' relations from what you wrote.');
                }
            }).catch(function (error) {
                running = false;
                jobId = null;
                failure = {error: {kind: 'unknown_job',
                                   detail: error && error.message,
                                   retryable: true}, wedged: false};
                render();
                announceOutcome();
            });
        }

        function stop() {
            if (!jobId) return;
            api().cancelRelationExtraction(jobId).catch(function () {});
            // Nothing is torn down here: the job reaches `cancelled` on the
            // next poll and the loop above ends on it.
        }

        // ------------------------------------------------------- the answers

        function accept(proposal, card, typeValue, reasonValue) {
            // `typeValue === null` means no select was offered, so the type
            // is not being changed -- not that it is being cleared.
            var offered = typeValue !== null;
            var typeId = offered && typeValue
                ? parseInt(typeValue, 10) : proposal.relation_type_id;
            var changed = offered && typeId !== proposal.relation_type_id;
            var focusOwed = holdsFocus(card);
            setBusy(card, true);
            api().acceptRelationProposal({
                relationId: proposal.relation_id,
                reason: reasonValue,
                relationTypeId: typeId,
                changeType: changed
            }).then(function () {
                drop(proposal.relation_id, focusOwed);
                notify('success', 'Relation added',
                    'It is on the subject’s Related Topics list now.');
                announce('Relation added. It is on the subject’s Related '
                    + 'Topics list now.');
            }).catch(function (error) {
                setBusy(card, false, focusOwed);
                // The database layer writes these for the student -- a blank
                // reason, a retired type, a pair that already carries that
                // type. Show the sentence rather than a generic failure.
                var why = (error && error.message) || String(error);
                notify('warning', 'Not added', why);
                announce('Not added. ' + why);
            });
        }

        function reject(proposal, card, kind) {
            var focusOwed = holdsFocus(card);
            setBusy(card, true);
            api().rejectRelationProposal({
                relationId: proposal.relation_id,
                kind: kind,
                sourceEntryId: (getContext() || {}).entry_id
            }).then(function () {
                drop(proposal.relation_id, focusOwed);
                var said = kind === 'misread'
                    ? 'WIMI will not suggest that from this entry again.'
                    : 'WIMI will not suggest that pair again.';
                notify('info', kind === 'misread'
                    ? 'Noted' : 'Noted — not related', said);
                announce('Noted. ' + said);
            }).catch(function (error) {
                setBusy(card, false, focusOwed);
                var why = (error && error.message) || String(error);
                notify('warning', 'Could not record that', why);
                announce('Could not record that. ' + why);
            });
        }

        /** Whether focus is on something inside `node` (#397). */
        function holdsFocus(node) {
            var active = document.activeElement;
            return !!active && node.contains(active);
        }

        function setBusy(card, busy, focusOwed) {
            Array.prototype.forEach.call(
                card.querySelectorAll('button, select, textarea'),
                function (control) { control.disabled = busy; });
            // Disabling the pressed button drops its focus; if the answer
            // failed and the card is back, so is the student (#397).
            if (!busy && focusOwed && !holdsFocus(card)) {
                var first = card.querySelector('button');
                if (first) first.focus();
            }
        }

        /**
         * Remove an answered card. `focusOwed` says the student answered it
         * from the keyboard or with focus inside it: the card -- and the
         * button they pressed -- is gone, so focus goes to the Find button,
         * which sits directly above the remaining cards, rather than falling
         * to <body> (#397).
         */
        function drop(relationId, focusOwed) {
            proposals = proposals.filter(function (p) {
                return p.relation_id !== relationId;
            });
            if (!proposals.length && !extra && !pendingElsewhere.length) {
                notStarted = null;
            }
            render();
            if (focusOwed && !holdsFocus(root)) focusFind();
        }

        render();

        return {
            refresh: refresh,
            loadTypes: loadTypes,
            /**
             * Re-park the button after the form's state changed.
             *
             * The bar ONLY. The host calls this on every edit, and the cards
             * hold a textarea the student may be mid-way through -- rebuilding
             * the list here would discard that silently.
             */
            update: renderBar,
            /** Forget the current list, e.g. when the form resets. */
            clear: function () {
                proposals = [];
                pendingElsewhere = [];
                extra = null;
                failure = null;
                notStarted = null;
                running = false;
                jobId = null;
                // Emptying a live region announces nothing, which is right:
                // the form was reset, and the last result belonged to the
                // entry that just left.
                statusEl.textContent = '';
                render();
            }
        };
    }

    window.attachRelationProposals = attachRelationProposals;
})();
