/**
 * Entry detail -> Anki cards (#784 Waves 4-5, redesigned in #815).
 *
 * The section ships `hidden` in entry_detail.html and is revealed only when
 * this computer has Anki switched on. It starts on `entry-detail:ready`, which
 * entry_detail.js fires after the page is drawn, so nothing here can hold the
 * page back; the section has its own status line instead.
 *
 * #815 measured the first version on a large shared deck: a dozen cards drawn
 * fully expanded, every field including `ankihub_id`, every image as a hash
 * file name with two buttons -- dozens of screens and hundreds of buttons for
 * one question. So:
 *
 * - **One row per card, collapsed.** The title is the card's own front text,
 *   never its deck (every card in a deck has the same one). Expanding shows
 *   the front and back in full, other fields by name, and the full figures.
 * - **Tooling fields never show** (`ankihub_id`, `Note ID`): a name ending in
 *   "id" is an identifier, not something to read. Settings' per-field
 *   visibility still hides anything else the student chose to hide.
 * - **Images are thumbnails**, fetched only when the field holding them is
 *   open, a few at a time. Viewing one opens the entry's lightbox, which is
 *   where Save to Attachments lives now, and the arrows (buttons and keys)
 *   step through every image on that card in field order, fetching each as
 *   it is reached (owner, #815).
 * - **Proposals sit on the card they are about**, and their three answers are
 *   drawn only when the proposals narrow the list: at most half the cards.
 *   Otherwise one sentence says why there is nothing to choose (owner, #815).
 *   The three answers keep one class and no default (decision 14, #60).
 *
 * Built from DOM nodes and textContent only: card fields come from Anki and
 * may come from shared decks, and Python has already reduced them to text and
 * image file names. One delegated click listener is attached once, so a
 * re-render can never double a handler (the plugin's suspend fired twice after
 * one refresh). Stability, recall and the next review date are labelled
 * "estimated": they are WIMI's FSRS-4.5 arithmetic on Anki's review log, not
 * Anki's own figures (owner decision 11), and Anki's `factor` is shown as Ease.
 */
(function () {
    'use strict';

    const DAY_MS = 86400000;
    /** Thumbnails drawn per field before "Show N more". */
    const THUMB_BATCH = 6;
    /** A field whose name ends in "id" is an identifier, not card content. */
    const TOOLING_FIELD = /(^|[\s_-])id$/i;

    let entryId = null;
    let payload = null;
    let busy = false;

    // State that survives a re-render: which rows and fields are open, how
    // many thumbnails each field shows, and the images already fetched.
    const expanded = new Set();
    const openFields = new Set();
    const thumbsShown = new Map();
    const imageCache = new Map();
    let feedback = null;    // {key, text}: the last answer, shown on its card
    let viewing = 0;        // bumps per image request, so a slow one cannot land late

    function $(id) { return document.getElementById(id); }

    function el(tag, attrs, text) {
        const node = document.createElement(tag);
        Object.entries(attrs || {}).forEach(function (pair) {
            if (pair[0] === 'className') node.className = pair[1];
            else node.setAttribute(pair[0], pair[1]);
        });
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function say(message, isError) {
        const node = $('anki-status');
        node.textContent = message || '';
        node.classList.toggle('is-error', !!isError);
    }

    function failure(err) {
        return err && err.message ? err.message : String(err);
    }

    function problem(err) {
        if (err && err.kind === 'unavailable') {
            return 'Anki is not answering on this computer. Open Anki to refresh.';
        }
        if (err && err.kind === 'action_failed') return 'Anki refused: ' + failure(err);
        return 'Could not reach Anki: ' + failure(err);
    }

    function when(iso) {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        return d.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
    }

    function days(n) {
        return n === 1 ? '1 day' : n + ' days';
    }

    function plural(n, one, many) {
        return n + ' ' + (n === 1 ? one : many);
    }

    // ----------------------------------------------------------------- fields

    /** The fields worth drawing: shown in Settings, not an identifier, and
     *  carrying text or an image. */
    function usable(fields) {
        return (fields || []).filter(function (f) {
            return f.visible && !TOOLING_FIELD.test((f.name || '').trim())
                && (f.text || (f.images || []).length);
        });
    }

    /** The card's own words, for its row title. */
    function frontText(fields) {
        const first = usable(fields).find(function (f) { return f.text; });
        return first ? first.text.replace(/\s+/g, ' ').trim() : '';
    }

    // ------------------------------------------------------------- thumbnails

    function thumbList(key, field) {
        const images = field.images || [];
        if (!images.length) return null;
        const id = key + '|' + field.name;
        const shown = Math.min(images.length, thumbsShown.get(id) || THUMB_BATCH);
        const box = el('div', {className: 'anki-thumbs'});
        images.slice(0, shown).forEach(function (name) {
            const attached = !!(window.entryDetail && window.entryDetail.hasAttachmentNamed(name));
            const button = el('button', {type: 'button', className: 'anki-thumb',
                'data-action': 'view-image', 'data-filename': name, 'data-field': field.name,
                'data-focus-key': 'view:' + name,
                'aria-label': 'View image ' + name + (attached ? ' (in Attachments)' : '')});
            const img = el('img', {alt: '', 'data-filename': name});
            if (typeof imageCache.get(name) === 'string') img.src = imageCache.get(name);
            button.appendChild(img);
            box.appendChild(button);
        });
        if (shown < images.length) {
            box.appendChild(el('button', {type: 'button', className: 'btn btn-secondary btn-sm',
                'data-action': 'more-images', 'data-field-key': id,
                'data-focus-key': 'more:' + id},
                'Show ' + Math.min(THUMB_BATCH, images.length - shown) + ' more of '
                + (images.length - shown)));
        }
        return box;
    }

    /** Fetch the images of every thumbnail that is on screen and has none
     *  yet. Hidden rows fetch nothing, which is the point of collapsing them. */
    async function loadVisibleThumbs() {
        const pending = Array.from($('anki-cards').querySelectorAll('.anki-thumb img'))
            .filter(function (img) { return !img.getAttribute('src') && img.offsetParent; });
        for (const img of pending) {
            const name = img.dataset.filename;
            if (!imageCache.has(name)) {
                try {
                    imageCache.set(name, (await api.viewAnkiImage(entryId, name)).data_url);
                } catch (err) {
                    imageCache.set(name, null);
                }
            }
            const url = imageCache.get(name);
            const current = $('anki-cards').querySelectorAll(
                '.anki-thumb img[data-filename="' + CSS.escape(name) + '"]');
            current.forEach(function (node) {
                if (url) node.src = url;
                else node.parentNode.classList.add('is-missing');
            });
        }
    }

    function fieldBlock(key, field, imagesOnly) {
        const box = el('div', {className: 'anki-field'});
        if (!imagesOnly) {
            box.appendChild(el('p', {className: 'anki-field-name'}, field.name));
            if (field.text) box.appendChild(el('p', {className: 'anki-field-text'}, field.text));
        }
        const thumbs = thumbList(key, field);
        if (thumbs) box.appendChild(thumbs);
        return box;
    }

    /** Front and back in full; every other field by name, opened on demand
     *  (owner, #815: "Text + Extra, rest by name"). The front's words are
     *  already the open row's title, so only its images are drawn again. */
    function cardFields(key, fields) {
        const box = el('div', {className: 'anki-fields'});
        const list = usable(fields);
        const title = list.find(function (f) { return f.text; });
        list.slice(0, 2).forEach(function (f) {
            if (f !== title) box.appendChild(fieldBlock(key, f));
            else if ((f.images || []).length) box.appendChild(fieldBlock(key, f, true));
        });
        const rest = list.slice(2);
        if (!rest.length) return box;
        const names = el('div', {className: 'anki-more-fields'});
        names.appendChild(el('span', {className: 'anki-more-fields-label'}, 'More fields'));
        rest.forEach(function (f) {
            const id = key + '|' + f.name;
            const open = openFields.has(id);
            names.appendChild(el('button', {type: 'button', className: 'anki-field-toggle',
                'data-action': 'field', 'data-field-key': id, 'data-focus-key': 'field:' + id,
                'aria-expanded': open ? 'true' : 'false'}, f.name));
        });
        box.appendChild(names);
        rest.filter(function (f) { return openFields.has(key + '|' + f.name); })
            .forEach(function (f) { box.appendChild(fieldBlock(key, f)); });
        return box;
    }

    // ------------------------------------------------------------------ stats

    function addStat(list, label, value) {
        if (value === null || value === undefined || value === '') return;
        list.append(el('dt', {}, label), el('dd', {}, String(value)));
    }

    function intervalText(interval) {
        if (interval > 0) return days(interval);
        if (interval < 0) return 'Learning';
        return 'New';
    }

    function cardStats(card) {
        const list = el('dl', {className: 'anki-stats'});
        const e = card.estimate || {};
        addStat(list, 'Interval', intervalText(card.interval));
        addStat(list, 'Reviews', e.review_count);
        addStat(list, 'Lapses', card.lapses);
        if (e.ease_percent !== null && e.ease_percent !== undefined) {
            addStat(list, 'Ease', Math.round(e.ease_percent) + '%');
        }
        if (e.latest_review_ms && e.latest_ivl > 0) {
            const next = new Date(e.latest_review_ms + e.latest_ivl * DAY_MS);
            addStat(list, 'Next review (estimated)',
                    next.toLocaleDateString(undefined, {dateStyle: 'medium'}));
        }
        if (e.stability_days !== null && e.stability_days !== undefined) {
            addStat(list, 'Stability (estimated)', days(Math.round(e.stability_days * 10) / 10));
        }
        if (e.retrievability !== null && e.retrievability !== undefined) {
            addStat(list, 'Recall now (estimated)', Math.round(e.retrievability * 100) + '%');
        }
        return list;
    }

    /** The row's one line of figures, so a card can be judged without
     *  opening it. Separate spans, spaced by the stylesheet. */
    function cardMeta(card) {
        const line = el('p', {className: 'anki-card-meta'});
        const e = card.estimate || {};
        const parts = [card.deck_name, intervalText(card.interval) === 'New' ? 'New'
                       : 'Interval ' + intervalText(card.interval)];
        if (e.review_count) parts.push(plural(e.review_count, 'review', 'reviews'));
        if (card.lapses) parts.push(plural(card.lapses, 'lapse', 'lapses'));
        if (e.retrievability !== null && e.retrievability !== undefined) {
            parts.push('Recall about ' + Math.round(e.retrievability * 100) + '% (estimated)');
        }
        parts.filter(Boolean).forEach(function (t) { line.appendChild(el('span', {}, t)); });
        return line;
    }

    function noteMeta(cards) {
        const line = el('p', {className: 'anki-card-meta'});
        const reviews = cards.reduce(function (n, c) {
            return n + ((c.estimate && c.estimate.review_count) || 0); }, 0);
        const lapses = cards.reduce(function (n, c) { return n + (c.lapses || 0); }, 0);
        [cards[0].deck_name, plural(cards.length, 'card', 'cards'),
         plural(reviews, 'review', 'reviews'), plural(lapses, 'lapse', 'lapses')]
            .filter(Boolean).forEach(function (t) { line.appendChild(el('span', {}, t)); });
        return line;
    }

    // -------------------------------------------------------------- proposals

    function reasonText(r) {
        if (r.kind === 'subject') return r.text + ' (subject)';
        if (r.kind === 'alias') return r.text + ' (another name for ' + r.subject_name + ')';
        return r.text + ' (the correct answer)';
    }

    /** Owner, #815: answers only when the proposals narrow the list. */
    function narrows(p) {
        const n = (p.proposals || []).length;
        return n > 0 && n * 2 <= p.cards.length;
    }

    function matchedWords(proposals) {
        const words = [];
        proposals.forEach(function (p) {
            p.reasons.forEach(function (r) { if (words.indexOf(r.text) < 0) words.push(r.text); });
        });
        return words.length <= 2 ? words.join(' and ')
            : words.slice(0, -1).join(', ') + ' and ' + words[words.length - 1];
    }

    function proposalsIntro(p) {
        const n = p.proposals.length;
        if (narrows(p)) {
            return el('p', {className: 'anki-proposals-note'},
                (n === 1 ? 'One card mentions ' : n + ' cards mention ') + matchedWords(p.proposals)
                + ', so WIMI marked ' + (n === 1 ? 'it' : 'them') + ' below. Showing a card first '
                + 'changes only this page; nothing is changed in Anki.');
        }
        return el('p', {className: 'anki-proposals-note anki-proposals-weak'},
            (n === p.cards.length ? 'Every card' : n + ' of ' + p.cards.length + ' cards')
            + ' mention' + (n === 1 ? 's ' : ' ') + matchedWords(p.proposals)
            + ', so WIMI can’t tell which one this mistake is about. Open a card and '
            + 'choose Show first to keep it at the top.');
    }

    /** Decision 14, on #60's proposal pattern: a visible reason, and three
     *  answers of equal weight with no default -- one class owns all three,
     *  so none can drift into looking like the expected press. */
    function proposalStrip(proposal) {
        const id = proposal.card_id;
        const box = el('div', {className: 'anki-proposal', 'data-card-id': String(id)});
        box.appendChild(el('p', {className: 'anki-proposal-reason'},
            'Mentions ' + proposal.reasons.map(reasonText).join(', ') + '.'));
        const names = [];
        proposal.reasons.forEach(function (r) {
            if (r.subject_name && names.indexOf(r.subject_name) < 0) names.push(r.subject_name);
        });
        const actions = el('div', {className: 'anki-card-actions'});
        actions.appendChild(el('button', {type: 'button', 'data-action': 'confirm',
            className: 'btn btn-secondary btn-sm anki-proposal-action',
            'data-card-ids': String(id), 'data-focus-key': 'proposal:' + id}, 'Show first'));
        actions.appendChild(el('button', {type: 'button', 'data-action': 'set-aside',
            className: 'btn btn-secondary btn-sm anki-proposal-action',
            'data-card-ids': String(id)}, 'Not for this entry'));
        if (names.length) {
            actions.appendChild(el('button', {type: 'button', 'data-action': 'never',
                className: 'btn btn-secondary btn-sm anki-proposal-action',
                'data-card-ids': String(id), 'data-subjects': names.join(' or '),
                'aria-label': 'Never propose this card for ' + names.join(' or ')},
                'Never for ' + names.join(' or ')));
        }
        box.appendChild(actions);
        if (!names.length) {
            box.appendChild(el('p', {className: 'anki-proposals-note'},
                'Only the correct answer matched, so this card can be set aside for this '
                + 'entry only.'));
        }
        return box;
    }

    // ------------------------------------------------------------------- rows

    function suspendButton(ids, allSuspended, noun) {
        const action = allSuspended ? 'unsuspend' : 'suspend';
        const label = (allSuspended ? 'Unsuspend ' : 'Suspend ') + noun + ' in Anki';
        return el('button', {type: 'button', className: 'btn btn-secondary btn-sm',
                             'data-action': action, 'data-card-ids': ids.join(','),
                             'data-focus-key': 'suspension:' + ids.join(','),
                             'aria-label': label},
                  allSuspended ? 'Unsuspend in Anki' : 'Suspend in Anki');
    }

    function firstButton(ids, confirmed) {
        if (confirmed) {
            return el('button', {type: 'button', className: 'btn btn-secondary btn-sm',
                                 'data-action': 'unconfirm', 'data-card-ids': ids.join(','),
                                 'data-focus-key': 'unconfirm:' + ids.join(',')},
                      'Stop showing first');
        }
        return el('button', {type: 'button', className: 'btn btn-secondary btn-sm',
                             'data-action': 'confirm', 'data-card-ids': String(ids[0]),
                             'data-focus-key': 'first:' + ids[0]}, 'Show first');
    }

    /** One collapsed row. ``parts`` carries what differs between card and
     *  note mode; the row's shape is the same in both. */
    function row(parts) {
        const open = expanded.has(parts.key);
        const bodyId = 'anki-body-' + parts.key.replace(/[^a-z0-9]/gi, '-');
        const block = el('article', Object.assign({className: 'anki-card'}, parts.attrs));
        block.classList.toggle('is-first', !!parts.confirmed);

        const head = el('div', {className: 'anki-card-head'});
        const toggle = el('button', {type: 'button', className: 'anki-toggle',
            'data-action': 'toggle', 'data-key': parts.key, 'data-focus-key': 'toggle:' + parts.key,
            'aria-expanded': open ? 'true' : 'false', 'aria-controls': bodyId});
        toggle.appendChild(el('span', {className: 'anki-card-title'}, parts.title));
        head.appendChild(toggle);
        const badges = el('span', {className: 'anki-badges'});
        if (parts.confirmed) badges.appendChild(el('span', {className: 'anki-badge anki-badge-first'},
                                                   'Shown first for this entry'));
        if (parts.suspended) badges.appendChild(el('span', {className: 'anki-badge anki-badge-suspended'},
                                                   'Suspended'));
        if (badges.childNodes.length) head.appendChild(badges);
        block.appendChild(head);
        block.appendChild(parts.meta);
        if (parts.proposal) block.appendChild(proposalStrip(parts.proposal));
        if (feedback && feedback.key === parts.key) {
            block.appendChild(el('p', {className: 'anki-card-feedback'}, feedback.text));
        }

        const body = el('div', {className: 'anki-card-body', id: bodyId});
        body.hidden = !open;
        body.appendChild(cardFields(parts.key, parts.fields));
        body.appendChild(parts.stats);
        const actions = el('div', {className: 'anki-card-actions'});
        parts.actions.filter(Boolean).forEach(function (a) { actions.appendChild(a); });
        body.appendChild(actions);
        block.appendChild(body);
        return block;
    }

    function cardRow(card, proposal) {
        const key = 'card:' + card.card_id;
        return row({
            key: key, attrs: {'data-card-id': String(card.card_id)},
            title: frontText(card.fields) || 'Card ' + card.card_id,
            meta: cardMeta(card), fields: card.fields, stats: cardStats(card),
            confirmed: card.confirmed, suspended: card.suspended, proposal: proposal,
            // A proposed card already offers Show first on its strip.
            actions: [proposal ? null : firstButton([card.card_id], card.confirmed),
                      suspendButton([card.card_id], card.suspended, 'this card')],
        });
    }

    function noteRow(cards, proposal) {
        const first = cards[0];
        const withFields = cards.find(function (c) { return (c.fields || []).length; }) || first;
        const ids = cards.map(function (c) { return c.card_id; });
        const allSuspended = cards.every(function (c) { return c.suspended; });
        const confirmedIds = cards.filter(function (c) { return c.confirmed; })
            .map(function (c) { return c.card_id; });
        const pending = allSuspended ? ids : cards.filter(function (c) { return !c.suspended; })
            .map(function (c) { return c.card_id; });
        const stats = el('dl', {className: 'anki-stats'});
        addStat(stats, 'Cards', cards.length);
        return row({
            key: 'note:' + first.note_id, attrs: {'data-note-id': String(first.note_id)},
            title: frontText(withFields.fields) || 'Note ' + first.note_id,
            meta: noteMeta(cards), fields: withFields.fields, stats: stats,
            confirmed: confirmedIds.length > 0, suspended: allSuspended, proposal: proposal,
            actions: [proposal && !confirmedIds.length ? null
                      : firstButton(confirmedIds.length ? confirmedIds : ids, confirmedIds.length > 0),
                      suspendButton(pending, allSuspended,
                                    cards.length === 1 ? 'this card' : 'this note’s cards')],
        });
    }

    function byNote(cards) {
        const groups = new Map();
        cards.forEach(function (c) {
            if (!groups.has(c.note_id)) groups.set(c.note_id, []);
            groups.get(c.note_id).push(c);
        });
        return Array.from(groups.values());
    }

    function render(p) {
        payload = p;
        const list = $('anki-cards');
        const refresh = $('anki-refresh');
        const synced = $('anki-synced');
        list.replaceChildren();
        synced.textContent = '';

        if (!p.matchable) {
            refresh.hidden = true;
            say(p.reason);
            return;
        }
        if (!p.has_templates) {
            refresh.hidden = true;
            say('This question bank has no Anki search template yet. Add one in Settings, Anki.');
            return;
        }
        refresh.hidden = false;
        synced.textContent = p.synced && p.last_synced_at
            ? plural(p.cards.length, 'card', 'cards') + ' for this question, fetched from Anki '
              + when(p.last_synced_at)
            : 'Not fetched from Anki yet.';
        if (!p.synced) return;
        if (!p.cards.length) {
            list.appendChild(el('p', {className: 'anki-empty'},
                                'Anki found no cards for this question.'));
            return;
        }
        const proposals = new Map();
        if (narrows(p)) p.proposals.forEach(function (x) { proposals.set(x.card_id, x); });
        if ((p.proposals || []).length) list.appendChild(proposalsIntro(p));
        if (p.display_mode === 'note') {
            byNote(p.cards).forEach(function (group) {
                const hit = group.map(function (c) { return proposals.get(c.card_id); })
                    .find(Boolean);
                list.appendChild(noteRow(group, hit));
            });
        } else {
            p.cards.forEach(function (card) {
                list.appendChild(cardRow(card, proposals.get(card.card_id)));
            });
            list.appendChild(el('p', {className: 'anki-estimate-note'},
                'Figures marked estimated are worked out by WIMI from Anki’s review log '
                + '(FSRS-4.5); they are not Anki’s own numbers.'));
        }
        loadVisibleThumbs();
    }

    // ---------------------------------------------------------------- actions

    function setBusy(on) {
        busy = on;
        $('anki-refresh').disabled = on;
        $('anki-cards').setAttribute('aria-busy', on ? 'true' : 'false');
    }

    function refocus(key) {
        if (!key) return;
        const target = Array.from($('anki-cards').querySelectorAll('button[data-focus-key]'))
            .find(function (b) { return b.dataset.focusKey === key; });
        if (target && !target.disabled) target.focus();
    }

    /** After answering a proposal its buttons are gone; keep the keyboard
     *  in the list rather than dropping focus to the page. */
    function focusNextProposal() {
        const next = $('anki-cards').querySelector('.anki-proposal button[data-action="confirm"]');
        (next || $('anki-refresh')).focus();
    }

    function rowKey(button) {
        const card = button.closest('.anki-card');
        if (!card) return null;
        return card.dataset.cardId ? 'card:' + card.dataset.cardId : 'note:' + card.dataset.noteId;
    }

    /** Say it in the live region, and on the card it happened to. */
    function answered(button, text) {
        feedback = {key: rowKey(button), text: text};
        say(text);
    }

    async function refresh(automatic) {
        if (busy) return;
        setBusy(true);
        say(automatic ? 'Checking Anki for newer cards…' : 'Asking Anki…');
        try {
            render(await api.refreshAnkiEntry(entryId));
            say('Up to date with Anki.');
        } catch (err) {
            const kept = payload && payload.synced && payload.last_synced_at
                ? ' Showing what was fetched ' + when(payload.last_synced_at) + '.' : '';
            say(problem(err) + kept, true);
        } finally {
            setBusy(false);
        }
    }

    /** Opening and closing never waits on anything, so it is not "busy". */
    function toggleView(button) {
        const action = button.dataset.action;
        if (action === 'toggle') {
            const key = button.dataset.key;
            if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
        } else if (action === 'field') {
            const id = button.dataset.fieldKey;
            if (openFields.has(id)) openFields.delete(id); else openFields.add(id);
        } else {
            const id = button.dataset.fieldKey;
            thumbsShown.set(id, (thumbsShown.get(id) || THUMB_BATCH) + THUMB_BATCH);
        }
        const key = button.dataset.focusKey;
        render(payload);
        refocus(key);
    }

    /** Every image on one row's card, in field order: what the lightbox's
     *  arrows step through. Hidden and identifier fields are not included. */
    function cardImages(key) {
        if (!payload) return [];
        let card;
        if (key.indexOf('card:') === 0) {
            const id = Number(key.slice(5));
            card = payload.cards.find(function (c) { return c.card_id === id; });
        } else {
            const id = Number(key.slice(5));
            const group = payload.cards.filter(function (c) { return c.note_id === id; });
            card = group.find(function (c) { return (c.fields || []).length; }) || group[0];
        }
        const images = [];
        usable(card ? card.fields : []).forEach(function (f) {
            (f.images || []).forEach(function (name) { images.push({field: f.name, name: name}); });
        });
        return images;
    }

    async function imageUrl(name) {
        let url = imageCache.get(name);
        if (typeof url !== 'string') {
            url = (await api.viewAnkiImage(entryId, name)).data_url;
            imageCache.set(name, url);
        }
        return url;
    }

    function saveAction(name) {
        return {
            attached: !!window.entryDetail.hasAttachmentNamed(name),
            run: async function () {
                say('Saving the image…');
                try {
                    const saved = await api.saveAnkiImageToEntry(entryId, name);
                    await window.entryDetail.reloadAttachments();
                    render(payload);
                    say('Saved ' + saved.original_filename + ' to Attachments.');
                } catch (err) {
                    say(problem(err), true);
                    throw err;
                }
            },
        };
    }

    /** Show image ``index`` of a card in the lightbox. The caption names the
     *  field and the position, because the file name is usually a hash. */
    async function openImage(key, images, index) {
        const ticket = ++viewing;
        const item = images[index];
        say('Fetching the image from Anki…');
        let url;
        try {
            url = await imageUrl(item.name);
        } catch (err) {
            if (ticket === viewing) say(problem(err), true);
            return;
        }
        if (ticket !== viewing) return;
        say('');
        const caption = images.length > 1
            ? item.field + ', image ' + (index + 1) + ' of ' + images.length : item.field;
        const step = images.length > 1 ? function (delta) {
            openImage(key, images, (index + delta + images.length) % images.length);
        } : null;
        window.entryDetail.showImageInLightbox(url, caption, saveAction(item.name), step);
    }

    async function viewImage(button) {
        const key = rowKey(button);
        const images = cardImages(key);
        let index = images.findIndex(function (i) {
            return i.name === button.dataset.filename && i.field === button.dataset.field;
        });
        if (index < 0) {
            images.splice(0, images.length, {field: button.dataset.field || '',
                                             name: button.dataset.filename});
            index = 0;
        }
        await openImage(key, images, index);
    }

    async function onCardClick(event) {
        const button = event.target.closest('button[data-action]');
        if (!button) return;
        const action = button.dataset.action;
        if (action === 'toggle' || action === 'field' || action === 'more-images') {
            toggleView(button);
            return;
        }
        if (busy) return;
        const key = button.dataset.focusKey;
        setBusy(true);
        feedback = null;
        // A verdict or rejection touches WIMI's database only, so its failure
        // must not be worded as Anki being unreachable (#813).
        const local = ['confirm', 'set-aside', 'never', 'unconfirm'].includes(action);
        try {
            if (action === 'suspend' || action === 'unsuspend') {
                const ids = button.dataset.cardIds.split(',').map(Number);
                say(action === 'suspend' ? 'Suspending in Anki…' : 'Unsuspending in Anki…');
                const fresh = await api.setAnkiCardsSuspended(entryId, ids, action === 'suspend');
                answered(button, action === 'suspend' ? 'Suspended in Anki.' : 'Unsuspended in Anki.');
                render(fresh);
                refocus(key);
            } else if (action === 'confirm' || action === 'set-aside') {
                const id = Number(button.dataset.cardIds);
                const fresh = await api.setAnkiCardVerdict(entryId, id,
                    action === 'confirm' ? 'confirmed' : 'not_for_entry');
                answered(button, action === 'confirm' ? 'Shown first for this entry.'
                                                      : 'Set aside for this entry.');
                render(fresh);
                focusNextProposal();
            } else if (action === 'never') {
                const id = Number(button.dataset.cardIds);
                const fresh = await api.rejectAnkiCardForSubjects(entryId, id);
                answered(button, 'WIMI will not propose this card for '
                                 + button.dataset.subjects + ' again.');
                render(fresh);
                focusNextProposal();
            } else if (action === 'unconfirm') {
                const ids = button.dataset.cardIds.split(',').map(Number);
                let fresh = payload;
                for (const id of ids) fresh = await api.setAnkiCardVerdict(entryId, id, 'clear');
                answered(button, 'No longer shown first.');
                render(fresh);
            } else if (action === 'view-image') {
                await viewImage(button);
            }
        } catch (err) {
            say(local ? 'WIMI could not save that answer: ' + failure(err) : problem(err), true);
        } finally {
            setBusy(false);
        }
    }

    // -------------------------------------------------------------------- init

    async function start(id) {
        entryId = id;
        let first;
        try {
            first = await api.getAnkiEntryStats(entryId);
        } catch (err) {
            console.error('Anki panel unavailable:', err);
            return;  // the section stays hidden; the page is unaffected
        }
        if (!first || !first.enabled) return;
        $('anki-section').hidden = false;
        render(first);
        if (first.matchable && first.has_templates && first.stale) refresh(true);
    }

    function wire() {
        if (!$('anki-section')) return;
        $('anki-refresh').addEventListener('click', function () { refresh(false); });
        $('anki-cards').addEventListener('click', onCardClick);
        document.addEventListener('entry-detail:ready', function (event) {
            start(event.detail.entryId);
        }, {once: true});
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wire);
    } else {
        wire();
    }
})();
