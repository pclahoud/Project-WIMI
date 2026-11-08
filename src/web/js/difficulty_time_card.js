/**
 * WIMI difficulty and time card (#898).
 *
 * One shared component, drawn on the analytics dashboard and on the subject
 * deep dive (Wave 4). Spec: docs/planning/DIFFICULTY_TIME_CARD_PLAN.md.
 *
 *     const card = new DifficultyTimeCard({
 *         mount,                      // the element the card is drawn into
 *         scope: { examContextId, subjectId, primaryParentId },
 *         onOpenEntries,              // optional (url, bucket, payload) => void
 *         tip, testid, tipTestid,     // optional; the dashboard's are defaults
 *         subtitle, emptyScope,       // optional; the dashboard's are defaults
 *     });
 *     await card.load();              // or card.load(newScope)
 *
 * The data is `api.getDifficultyTimeQuadrants`, and every link into the
 * entry browser is `WimiDifficultyTimeLinks.urlFor`, the JavaScript twin of
 * `dt_entry_browser_params` -- so a quadrant opens the browser on exactly
 * the number it shows. A card never builds its own query string.
 *
 * Every mistake in scope is accounted for: the four quadrants (or, under
 * the minimum number of timed mistakes, one unsplit block), the rated-3
 * middle line and the not-placed line add up to the total the last sentence
 * names.
 *
 * Built with createElement / textContent throughout: error-type names are
 * student-written and nothing here goes through innerHTML.
 *
 * Wave 2 drew the Quadrants tab; Wave 3 adds the error-type picker, the
 * per-type rows and the Every entry tab (a D3 scatter). The picker's
 * selection travels in every request and in every link, so a quadrant opens
 * the browser on exactly the "N of M" it shows ("a quadrant click keeps the
 * selection", #898's defaults).
 *
 * The scatter is drawn for the mouse and the eye: a dot is not focusable,
 * and the Quadrants tab is the keyboard route to the same entries, which
 * the scatter says in words beside it.
 *
 * Needs api (api/_loader.js) and difficulty_time_links.js; the scatter needs
 * D3 (lib/d3.v7.min.js); uses difficulty.js for the words of a rating when
 * it is loaded.
 */
(function (global) {
    'use strict';

    var DASHBOARD_TIP = 'Each mistake is placed by how hard you rated the question and how long you spent on it. Hard means rated 4 or 5, easy means 1 or 2. Fast means under your median time for this exam, which moves as you log more. Mistakes rated 3 sit in the middle, in no quadrant, and mistakes with no rating or no time are counted as not placed, so none is dropped. A mistake with two error types counts under both.';

    var SUBTITLE = 'Your mistakes on this exam, sorted by how hard you rated each question and how long you spent on it.';

    var ROWS = [
        { key: 'hard', label: 'Hard', sub: 'rated 4–5', levels: [4, 5] },
        { key: 'easy', label: 'Easy', sub: 'rated 1–2', levels: [1, 2] }
    ];
    var COLUMNS = [
        { key: 'fast', label: 'Faster than your median' },
        { key: 'slow', label: 'Slower than your median' }
    ];
    var NAMES = {
        hard_fast: 'Hard and fast', hard_slow: 'Hard and slow',
        easy_fast: 'Easy and fast', easy_slow: 'Easy and slow'
    };

    var QUADRANT_KEYS = ['hard_fast', 'hard_slow', 'easy_fast', 'easy_slow'];
    /** Picks with a colour each; one more and every match shares one. */
    var SERIES_COUNT = 4;
    /** A picker change waits this long for the next before asking again. */
    var DEBOUNCE_MS = 250;

    var nextId = 0;

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function plural(n, one, many) {
        return n === 1 ? one : many;
    }

    function mistakes(n) {
        return n + ' ' + plural(n, 'mistake', 'mistakes');
    }

    function entries(n) {
        return n + ' ' + plural(n, 'entry', 'entries');
    }

    /** The colour a picked type draws in, by its place in the pick order. */
    function seriesColour(index, pickedCount) {
        if (pickedCount > SERIES_COUNT) return 'var(--dt-series-many)';
        return 'var(--dt-series-' + (index + 1) + ')';
    }

    function swatch(colour, className) {
        var dot = el('span', className || 'dt-swatch');
        dot.setAttribute('aria-hidden', 'true');
        dot.style.background = colour;
        return dot;
    }

    function links() {
        return global.WimiDifficultyTimeLinks;
    }

    /** "Hard or Very Hard", from the entry form's own words when loaded. */
    function levelWords(levels) {
        var d = global.WimiDifficulty;
        if (!d) return '';
        return levels.map(function (v) { return d.labelFor(v); }).filter(Boolean).join(' or ');
    }

    function DifficultyTimeCard(options) {
        options = options || {};
        if (!options.mount) throw new Error('DifficultyTimeCard needs a mount');
        this.mount = options.mount;
        this.scope = options.scope || {};
        this.onOpenEntries = typeof options.onOpenEntries === 'function' ? options.onOpenEntries : null;
        this.tip = options.tip || DASHBOARD_TIP;
        this.testid = options.testid || 'analytics-difficulty-time';
        // The deep dive names its own tip and words: its card counts one
        // subject's mistakes, not the exam's (Wave 4).
        this.tipTestid = options.tipTestid || 'analytics-info-difficulty-time';
        this.subtitle = options.subtitle || SUBTITLE;
        // What "no mistakes yet" is about: "this exam" or "this subject".
        this.emptyScope = options.emptyScope || 'this exam';
        this.uid = 'dt-card-' + (++nextId);
        this.payload = null;
        this.onOpenEntry = typeof options.onOpenEntry === 'function' ? options.onOpenEntry : null;
        this.requestSeq = 0;
        this.activeTab = 'quadrants';
        // The picker's state. tagIds keeps pick order: it decides colours.
        this.selection = { tagIds: [], untagged: false, match: 'any' };
        this.debounceTimer = null;
        this.pickerOpen = false;
        this.buildFrame();
    }

    DifficultyTimeCard.DASHBOARD_TIP = DASHBOARD_TIP;

    /**
     * The heading, tip, subtitle and toolbar are drawn at once and never
     * redrawn, so the tip exists before any data arrives (a page's tip
     * sweep counts it) and a reload does not move focus out of the tabs.
     */
    DifficultyTimeCard.prototype.buildFrame = function () {
        var mount = this.mount;
        while (mount.firstChild) mount.removeChild(mount.firstChild);

        var head = el('div', 'section-title-row');
        var title = el('h2', 'section-title', 'Difficulty and Time Spent');
        title.id = this.uid + '-title';
        head.appendChild(title);
        var icon = el('span', 'card-info-icon', 'i');
        icon.tabIndex = 0;
        icon.setAttribute('data-testid', this.tipTestid);
        icon.setAttribute('aria-label', this.tip);
        var tooltip = el('span', 'card-info-tooltip', this.tip);
        tooltip.setAttribute('data-testid', this.tipTestid + '-tooltip');
        icon.appendChild(tooltip);
        head.appendChild(icon);
        mount.appendChild(head);

        var card = el('div', 'dt-card');
        card.setAttribute('data-testid', this.testid);
        card.setAttribute('aria-labelledby', title.id);
        card.appendChild(el('p', 'dt-subtitle', this.subtitle));

        var toolbar = el('div', 'dt-toolbar');
        var tabs = el('div', 'dt-tabs');
        tabs.setAttribute('role', 'tablist');
        tabs.setAttribute('aria-label', 'View');
        this.tabs = {};
        this.panels = {};
        var self = this;
        [['quadrants', 'Quadrants'], ['every', 'Every entry']].forEach(function (pair) {
            var tab = el('button', 'dt-tab', pair[1]);
            tab.type = 'button';
            tab.id = self.uid + '-tab-' + pair[0];
            tab.setAttribute('role', 'tab');
            tab.setAttribute('aria-controls', self.uid + '-panel-' + pair[0]);
            tab.setAttribute('data-testid', self.testid + '-tab-' + pair[0]);
            tab.addEventListener('click', function () { self.selectTab(pair[0]); });
            tab.addEventListener('keydown', function (e) { self.onTabKey(e); });
            tabs.appendChild(tab);
            self.tabs[pair[0]] = tab;
        });
        // A tab list of one tab is a button that does nothing, so the list
        // hides while fewer than two tabs are offered (Wave 2 hid the scatter
        // tab until it existed; it exists now).
        tabs.hidden = Object.keys(this.tabs).filter(function (k) {
            return !self.tabs[k].hidden;
        }).length < 2;
        this.tabList = tabs;
        toolbar.appendChild(tabs);
        var slot = el('div', 'dt-toolbar-slot');
        this.buildPicker(slot);
        toolbar.appendChild(slot);
        card.appendChild(toolbar);

        ['quadrants', 'every'].forEach(function (key) {
            var panel = el('div', 'dt-panel');
            panel.id = self.uid + '-panel-' + key;
            panel.setAttribute('role', 'tabpanel');
            panel.setAttribute('aria-labelledby', self.uid + '-tab-' + key);
            panel.setAttribute('data-testid', self.testid + '-panel-' + key);
            card.appendChild(panel);
            self.panels[key] = panel;
        });
        mount.appendChild(card);
        this.card = card;
        this.selectTab('quadrants', false);
    };

    DifficultyTimeCard.prototype.selectTab = function (key, focus) {
        if (!this.tabs[key] || this.tabs[key].hidden) return;
        this.activeTab = key;
        for (var k in this.tabs) {
            var on = k === key;
            this.tabs[k].setAttribute('aria-selected', on ? 'true' : 'false');
            this.tabs[k].tabIndex = on ? 0 : -1;
            this.panels[k].hidden = !on;
        }
        if (focus) this.tabs[key].focus();
        // The scatter is sized to its panel, which has no width while
        // hidden; draw it again at its real width once it is shown.
        if (key === 'every' && this.payload && this.payload.total) {
            var width = this.panels.every.clientWidth;
            if (width && width !== this.scatterWidth) this.drawScatter(this.payload);
        }
    };

    DifficultyTimeCard.prototype.onTabKey = function (e) {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' && e.key !== 'Home' && e.key !== 'End') return;
        var keys = Object.keys(this.tabs).filter(function (k) { return !this.tabs[k].hidden; }, this);
        var i = keys.indexOf(this.activeTab);
        if (e.key === 'ArrowRight') i = (i + 1) % keys.length;
        else if (e.key === 'ArrowLeft') i = (i - 1 + keys.length) % keys.length;
        else if (e.key === 'Home') i = 0;
        else i = keys.length - 1;
        e.preventDefault();
        this.selectTab(keys[i], true);
    };

    /**
     * Fetch and draw. Only the newest request draws, so a quick exam switch
     * cannot leave the card showing the exam that was left.
     */
    DifficultyTimeCard.prototype.load = async function (scope) {
        if (scope) this.scope = scope;
        if (scope && scope.examContextId !== this.loadedExamId) {
            // Error-type ids are per profile, but the list is per exam:
            // a selection made on one exam means nothing on the next.
            this.selection = { tagIds: [], untagged: false, match: 'any' };
            this.closePicker(false);
        }
        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
            this.debounceTimer = null;
        }
        var seq = ++this.requestSeq;
        var panel = this.panels.quadrants;
        if (!this.scope.examContextId) {
            this.payload = null;
            this.loadedExamId = null;
            this.replace(panel, el('p', 'dt-empty', 'Choose an exam to see this card.'));
            this.replace(this.panels.every, el('p', 'dt-empty', 'Choose an exam to see this card.'));
            this.updatePickerButton();
            return null;
        }
        this.loadedExamId = this.scope.examContextId;
        var sel = this.selection;
        try {
            var payload = await global.api.getDifficultyTimeQuadrants({
                examContextId: this.scope.examContextId,
                subjectId: this.scope.subjectId || null,
                primaryParentId: this.scope.primaryParentId || null,
                tagIds: sel.untagged ? [] : sel.tagIds.slice(),
                untagged: sel.untagged,
                match: sel.tagIds.length > 1 ? sel.match : 'any'
            });
            if (seq !== this.requestSeq) return null;
            this.render(payload);
            return payload;
        } catch (error) {
            if (seq !== this.requestSeq) return null;
            this.payload = null;
            var message = (error && error.message) ? error.message : String(error);
            this.replace(panel, el('p', 'dt-error', 'This card could not load: ' + message));
            this.replace(this.panels.every, el('p', 'dt-error', 'This card could not load: ' + message));
            if (global.console) console.error('Difficulty and time card:', error);
            return null;
        }
    };

    DifficultyTimeCard.prototype.replace = function (panel) {
        while (panel.firstChild) panel.removeChild(panel.firstChild);
        for (var i = 1; i < arguments.length; i++) {
            if (arguments[i]) panel.appendChild(arguments[i]);
        }
    };


    /**
     * The selection a payload was computed for, in the card's own terms:
     * `all` (nothing picked), `one`, `any` / `every` (two or more picked,
     * by the Match switch) or `untagged` (No error type). Read from the
     * payload, never from the picker, so a count is never labelled with a
     * selection it was not counted for.
     */
    function selectionOf(payload) {
        var s = payload.selection || {};
        var ids = s.tag_ids || [];
        var mode;
        if (s.untagged) mode = 'untagged';
        else if (!ids.length) mode = 'all';
        else if (ids.length === 1) mode = 'one';
        else mode = s.match === 'all' ? 'every' : 'any';
        var byId = {};
        (payload.types || []).forEach(function (t) { byId[t.tag_id] = t; });
        return {
            mode: mode,
            ids: ids,
            names: ids.map(function (id) {
                return byId[id] ? byId[id].name : 'Error type ' + id;
            }),
            colour: function (id) { return seriesColour(ids.indexOf(id), ids.length); }
        };
    }

    /** "3 Careless Mistake entries", "5 mistakes carrying any of these" ... */
    function selectionPhrase(sel, n) {
        if (sel.mode === 'one') return n + ' ' + sel.names[0] + ' ' + plural(n, 'entry', 'entries');
        if (sel.mode === 'untagged') return mistakes(n) + ' with no error type';
        if (sel.mode === 'any') return mistakes(n) + ' carrying any of these';
        return mistakes(n) + ' carrying all of these';
    }

    function placedBuckets(payload) {
        return payload.median.available ? QUADRANT_KEYS : ['unsplit'];
    }

    function bucketSummary(payload, bucket) {
        return bucket === 'unsplit' ? payload.unsplit : payload.buckets[bucket];
    }

    function matchCount(summary) {
        return summary && summary.match ? summary.match.count : 0;
    }

    DifficultyTimeCard.prototype.render = function (payload) {
        this.payload = payload;
        this.renderQuadrants(payload);
        this.drawScatter(payload);
        this.updatePickerButton();
        if (this.pickerOpen) this.renderPickerList();
    };

    DifficultyTimeCard.prototype.renderQuadrants = function (payload) {
        var panel = this.panels.quadrants;
        this.card.dataset.state = '';
        // Every mistake in scope, whatever is picked: the number a page puts
        // beside the card (the deep dive's Total Mistakes) to show they agree.
        this.card.dataset.total = payload ? String(payload.total || 0) : '';
        if (!payload || !payload.total) {
            this.card.dataset.state = 'empty';
            this.card.dataset.selection = '';
            this.replace(panel, el('p', 'dt-empty', 'No mistakes on ' + this.emptyScope +
                ' yet. Each one you log is placed here by its difficulty and its time spent.'));
            return;
        }
        this.card.dataset.selection = selectionOf(payload).mode;
        var median = payload.median || {};
        var parts = [];
        if (!median.available) {
            this.card.dataset.state = 'unsplit';
            parts.push(this.tooFewNote(median));
            parts.push(this.unsplitBlock(payload));
        } else {
            this.card.dataset.state = median.all_equal ? 'all-equal' : 'split';
            if (median.all_equal) parts.push(this.allEqualNote(median));
            parts.push(this.grid(payload));
        }
        parts.push(this.footer(payload));
        this.replace.apply(this, [panel].concat(parts));
    };
    DifficultyTimeCard.prototype.tooFewNote = function (median) {
        var have = median.timed_count || 0;
        var need = median.min_timed || 10;
        var note = el('p', 'dt-note',
            'Fast and slow are measured against your median time, which needs at least ' +
            need + ' mistakes with a time spent. This exam has ' + have +
            ' so far, so the mistakes below are not split into quadrants yet.');
        note.setAttribute('data-testid', this.testid + '-too-few');
        return note;
    };

    DifficultyTimeCard.prototype.allEqualNote = function (median) {
        var t = links().formatSeconds(median.label_seconds);
        var note = el('p', 'dt-note',
            'Every timed mistake took the same time, ' + t +
            ', so none is faster than your median and both fast cards are empty.');
        note.setAttribute('data-testid', this.testid + '-all-equal');
        return note;
    };

    /** A link or a plain block: a card with nothing in it opens nothing. */
    DifficultyTimeCard.prototype.linkBlock = function (payload, bucket, count, className) {
        var self = this;
        if (!count) {
            var block = el('div', className);
            block.setAttribute('data-bucket', bucket);
            return block;
        }
        var a = el('a', className);
        a.href = links().urlFor(payload, bucket);
        a.setAttribute('data-bucket', bucket);
        a.addEventListener('click', function (e) {
            if (!self.onOpenEntries) return;
            e.preventDefault();
            self.onOpenEntries(a.getAttribute('href'), bucket, payload);
        });
        return a;
    };


    DifficultyTimeCard.prototype.typeList = function (summary) {
        var list = el('ul', 'dt-types');
        (summary.top_types || []).forEach(function (t) {
            var li = el('li', 'dt-type');
            li.appendChild(el('span', 'dt-type-name', t.name));
            li.appendChild(el('span', 'dt-type-count', t.count));
            list.appendChild(li);
        });
        if (summary.more_types > 0) {
            list.appendChild(el('li', 'dt-type-more', 'and ' + summary.more_types + ' more'));
        }
        if (!(summary.top_types || []).length) {
            list.appendChild(el('li', 'dt-type-none',
                summary.count === 1 ? 'It has no error type.' : 'None has an error type.'));
        }
        return list;
    };

    /**
     * Match any with two or more picked: one colour-keyed row per picked
     * type, in pick order. The rows overlap (a mistake carrying two picked
     * types is in both), which the footer says; the large number above
     * them counts each mistake once.
     */
    DifficultyTimeCard.prototype.pickedRows = function (payload, sel, summary, bucket) {
        var list = el('ul', 'dt-types dt-types--picked');
        list.setAttribute('data-testid', this.testid + '-rows-' + bucket);
        var perType = {};
        (summary.match.per_type || []).forEach(function (p) { perType[p.tag_id] = p.count; });
        sel.ids.forEach(function (id, i) {
            var li = el('li', 'dt-type');
            var name = el('span', 'dt-type-name');
            name.appendChild(swatch(sel.colour(id)));
            name.appendChild(document.createTextNode(sel.names[i]));
            li.appendChild(name);
            li.appendChild(el('span', 'dt-type-count', perType[id] || 0));
            list.appendChild(li);
        });
        return list;
    };

    /**
     * The inside of one quadrant (or the unsplit block). On All: the count,
     * its share of the placed mistakes and the top three types, as Wave 2
     * drew them. With a selection: "N of M", N being the mistakes in this
     * quadrant that match and M all of its mistakes, and the share of the
     * matching placed mistakes that fall here. A quadrant with no matching
     * mistake opens nothing, as a quadrant with no mistake does on All.
     */
    DifficultyTimeCard.prototype.quadrantBlock = function (payload, bucket, name, className, allShare) {
        var summary = bucketSummary(payload, bucket);
        var sel = selectionOf(payload);
        var total = summary.count;
        var shown = sel.mode === 'all' ? total : matchCount(summary);
        var block = this.linkBlock(payload, bucket, shown, className);
        block.setAttribute('data-testid', this.testid + '-quadrant-' + bucket);
        block.appendChild(el('span', 'dt-quadrant-name', name));
        var countEl = el('span', 'dt-quadrant-count', shown);
        countEl.setAttribute('data-testid', this.testid + '-count-' + bucket);
        block.appendChild(countEl);

        var share;
        if (sel.mode === 'all') {
            share = allShare;
            block.appendChild(el('span', 'dt-quadrant-share', share));
            if (total > 0) block.appendChild(this.typeList(summary));
        } else {
            var of = 'of ' + total;
            if (sel.mode === 'any') of += ' carry any of these';
            if (sel.mode === 'every') of += ' carry all of these';
            var ofEl = el('span', 'dt-quadrant-of', of);
            ofEl.setAttribute('data-testid', this.testid + '-of-' + bucket);
            countEl.appendChild(document.createTextNode(' '));
            countEl.appendChild(ofEl);
            var placedMatch = 0;
            placedBuckets(payload).forEach(function (b) {
                placedMatch += matchCount(bucketSummary(payload, b));
            });
            var whose = {
                one: 'of this type’s placed mistakes',
                untagged: 'of the placed mistakes with no error type',
                any: 'of the placed mistakes carrying any of these',
                every: 'of the placed mistakes carrying all of these'
            }[sel.mode];
            share = placedMatch > 0
                ? Math.round(100 * shown / placedMatch) + '% ' + whose
                : 'No placed mistake matches';
            block.appendChild(el('span', 'dt-quadrant-share', share));
            if (sel.mode === 'any') block.appendChild(this.pickedRows(payload, sel, summary, bucket));
        }
        if (shown > 0) {
            block.appendChild(el('span', 'dt-show', 'Show these entries'));
            var said = sel.mode === 'all' ? mistakes(total) : shown + ' of ' + mistakes(total) + ' match';
            block.setAttribute('aria-label', name + ': ' + said + ', ' + share + '. Show these entries');
        }
        return block;
    };

    DifficultyTimeCard.prototype.quadrant = function (payload, bucket, rowKey) {
        var count = payload.buckets[bucket].count;
        var share = payload.placed > 0
            ? Math.round(100 * count / payload.placed) + '% of placed mistakes'
            : 'No placed mistakes yet';
        return this.quadrantBlock(payload, bucket, NAMES[bucket],
            'dt-quadrant dt-quadrant--' + rowKey, share);
    };

    DifficultyTimeCard.prototype.grid = function (payload) {
        var grid = el('div', 'dt-grid');
        grid.setAttribute('data-testid', this.testid + '-grid');
        var label = links().formatSeconds(payload.median.label_seconds);
        grid.appendChild(el('div'));
        COLUMNS.forEach(function (col) {
            var head = el('div', 'dt-col-head', col.label);
            head.appendChild(el('span', 'dt-sub',
                col.key === 'fast' ? 'under ' + label : label + ' or more'));
            grid.appendChild(head);
        });
        var self = this;
        ROWS.forEach(function (row) {
            var head = el('div', 'dt-row-head', row.label);
            head.appendChild(el('span', 'dt-sub', row.sub));
            var words = levelWords(row.levels);
            if (words) head.title = words;
            grid.appendChild(head);
            COLUMNS.forEach(function (col) {
                grid.appendChild(self.quadrant(payload, row.key + '_' + col.key, row.key));
            });
        });
        return grid;
    };

    DifficultyTimeCard.prototype.unsplitBlock = function (payload) {
        return this.quadrantBlock(payload, 'unsplit', 'Rated hard or easy, with a time',
            'dt-quadrant dt-unsplit', 'rated 1, 2, 4 or 5');
    };

    DifficultyTimeCard.prototype.footerLine = function (payload, bucket, label, sentence, count) {
        var line = el('div', 'dt-footer-line');
        line.setAttribute('data-testid', this.testid + '-line-' + bucket);
        var text = el('span');
        text.appendChild(el('strong', null, label));
        text.appendChild(document.createTextNode(' ' + sentence));
        line.appendChild(text);
        if (count > 0) {
            var a = this.linkBlock(payload, bucket, count, 'dt-footer-show');
            a.textContent = 'Show';
            a.setAttribute('aria-label', 'Show the ' + label.replace(/:$/, '').toLowerCase() +
                ' entries');
            a.setAttribute('data-testid', this.testid + '-show-' + bucket);
            line.appendChild(a);
        }
        return line;
    };

    DifficultyTimeCard.prototype.footer = function (payload) {
        var sel = selectionOf(payload);
        return sel.mode === 'all' ? this.footerAll(payload) : this.footerSelected(payload, sel);
    };

    DifficultyTimeCard.prototype.footerAll = function (payload) {
        var footer = el('div', 'dt-footer');
        var middle = payload.buckets.middle.count;
        var notPlaced = payload.buckets.not_placed.count;
        footer.appendChild(this.footerLine(payload, 'middle', 'Rated 3:',
            middle === 0
                ? 'no mistakes sit in the middle.'
                : mistakes(middle) + ' ' + plural(middle, 'sits', 'sit') +
                  ' in the middle, neither hard nor easy, so ' +
                  plural(middle, 'it is', 'they are') + ' in no quadrant.',
            middle));
        footer.appendChild(this.footerLine(payload, 'not_placed', 'Not placed:',
            notPlaced === 0
                ? 'none. Every mistake has a difficulty rating and a time spent.'
                : mistakes(notPlaced) + ' ' + plural(notPlaced, 'has', 'have') +
                  ' no difficulty rating or no time spent.',
            notPlaced));

        var placed = payload.placed;
        var untaggedPlaced = 0;
        placedBuckets(payload).forEach(function (b) {
            untaggedPlaced += bucketSummary(payload, b).untagged;
        });
        var first = payload.median.available
            ? placed + ' of ' + mistakes(payload.total) + ' placed.'
            : placed + ' of ' + mistakes(payload.total) +
              ' are rated hard or easy and timed, waiting for the split.';
        var sentences = [first,
            'A mistake with two error types is counted under both, so a card’s error-type counts can add up to more than its total.'];
        if (untaggedPlaced > 0) {
            sentences.push(untaggedPlaced === 1
                ? '1 placed mistake has no error type.'
                : untaggedPlaced + ' placed mistakes have no error type.');
        }
        var accounting = el('p', 'dt-accounting', sentences.join(' '));
        accounting.setAttribute('data-testid', this.testid + '-accounting');
        footer.appendChild(accounting);
        return footer;
    };

    /**
     * The footer under a selection counts only what matches, so every
     * number on the tab answers the same question. The Show links carry the
     * selection and land on these counts.
     */
    DifficultyTimeCard.prototype.footerSelected = function (payload, sel) {
        var footer = el('div', 'dt-footer');
        var middle = matchCount(payload.buckets.middle);
        var notPlaced = matchCount(payload.buckets.not_placed);
        footer.appendChild(this.footerLine(payload, 'middle', 'Rated 3:',
            selectionPhrase(sel, middle) + ' ' + plural(middle, 'sits', 'sit') +
            ' in the middle band, in no quadrant.', middle));
        footer.appendChild(this.footerLine(payload, 'not_placed', 'Not placed:',
            selectionPhrase(sel, notPlaced) + ' ' + plural(notPlaced, 'has', 'have') +
            ' no difficulty rating or no time spent.', notPlaced));

        var placedMatch = 0;
        placedBuckets(payload).forEach(function (b) {
            placedMatch += matchCount(bucketSummary(payload, b));
        });
        var allMatch = placedMatch + middle + notPlaced;
        var sentences = [payload.median.available
            ? placedMatch + ' of ' + selectionPhrase(sel, allMatch) + ' placed.'
            : placedMatch + ' of ' + selectionPhrase(sel, allMatch) +
              ' are rated hard or easy and timed, waiting for the split.'];
        if (sel.mode === 'one') {
            sentences.push('Each card shows how many of its mistakes carry this error type.');
        } else if (sel.mode === 'untagged') {
            sentences.push('Each card shows how many of its mistakes have no error type yet; open one to go back and tag them.');
        } else if (sel.mode === 'any') {
            sentences.push('The coloured rows overlap: a mistake tagged both ' + sel.names[0] +
                ' and ' + sel.names[1] + ' counts in each row, and once in the large number.' +
                ' With Match set to all, each card shows one number: mistakes carrying every picked type.');
        } else {
            sentences.push('Each card shows how many of its mistakes carry every picked type.');
        }
        var accounting = el('p', 'dt-accounting', sentences.join(' '));
        accounting.setAttribute('data-testid', this.testid + '-accounting');
        footer.appendChild(accounting);
        return footer;
    };

    // =====================================================================
    // The error-type picker
    // =====================================================================

    /**
     * A disclosure: a button that opens a non-modal popover of checkboxes
     * under it. Not one of the modal surfaces modal_dialog.js manages -- it
     * hides nothing and traps nothing, so the card stays readable beside
     * it -- but it keeps that pattern's promises that matter here: Escape
     * and Done close it, and focus goes back to the button that opened it.
     * A click or focus outside closes it without moving focus.
     */
    DifficultyTimeCard.prototype.buildPicker = function (slot) {
        var self = this;
        var wrap = el('div', 'dt-picker');
        var label = el('span', 'dt-picker-label', 'Error type');
        label.setAttribute('aria-hidden', 'true');
        wrap.appendChild(label);

        var anchor = el('div', 'dt-picker-anchor');
        var button = el('button', 'dt-picker-button');
        button.type = 'button';
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-controls', this.uid + '-picker');
        button.setAttribute('data-testid', this.testid + '-picker-button');
        var buttonText = el('span', 'dt-picker-button-text', 'All error types');
        button.appendChild(buttonText);
        var caret = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        caret.setAttribute('class', 'dt-picker-caret');
        caret.setAttribute('viewBox', '0 0 12 12');
        caret.setAttribute('aria-hidden', 'true');
        var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', 'M2 4l4 4 4-4');
        caret.appendChild(path);
        button.appendChild(caret);
        button.addEventListener('click', function () {
            if (self.pickerOpen) self.closePicker(true);
            else self.openPicker();
        });
        anchor.appendChild(button);

        var pop = el('div', 'dt-picker-popover');
        pop.id = this.uid + '-picker';
        pop.hidden = true;
        pop.setAttribute('role', 'group');
        pop.setAttribute('aria-labelledby', this.uid + '-picker-title');
        pop.setAttribute('data-testid', this.testid + '-picker');
        var head = el('div', 'dt-picker-head');
        var title = el('span', 'dt-picker-title', 'Error types to highlight');
        title.id = this.uid + '-picker-title';
        head.appendChild(title);
        var clear = el('button', 'dt-picker-clear', 'Clear');
        clear.type = 'button';
        clear.setAttribute('data-testid', this.testid + '-picker-clear');
        clear.addEventListener('click', function () {
            self.selection.tagIds = [];
            self.selection.untagged = false;
            self.selection.match = 'any';
            self.selectionChanged();
        });
        head.appendChild(clear);
        pop.appendChild(head);
        var body = el('div', 'dt-picker-body');
        pop.appendChild(body);
        var note = el('p', 'dt-picker-note');
        note.setAttribute('data-testid', this.testid + '-picker-note');
        pop.appendChild(note);
        var foot = el('div', 'dt-picker-foot');
        var done = el('button', 'dt-picker-done', 'Done');
        done.type = 'button';
        done.setAttribute('data-testid', this.testid + '-picker-done');
        done.addEventListener('click', function () { self.closePicker(true); });
        foot.appendChild(done);
        pop.appendChild(foot);
        pop.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                self.closePicker(true);
            }
        });
        anchor.appendChild(pop);
        wrap.appendChild(anchor);
        wrap.addEventListener('focusout', function (e) {
            if (self.pickerOpen && e.relatedTarget && !wrap.contains(e.relatedTarget)) {
                self.closePicker(false);
            }
        });

        // Match any / all: offered only while two or more types are picked.
        var match = el('div', 'dt-match');
        match.setAttribute('role', 'group');
        match.setAttribute('aria-label', 'Match');
        match.hidden = true;
        match.appendChild(el('span', 'dt-match-label', 'Match'));
        this.matchButtons = {};
        ['any', 'all'].forEach(function (mode) {
            var b = el('button', 'dt-match-button', mode);
            b.type = 'button';
            b.setAttribute('aria-pressed', mode === 'any' ? 'true' : 'false');
            b.setAttribute('aria-label', mode === 'any'
                ? 'Match any picked error type' : 'Match all picked error types');
            b.setAttribute('data-testid', self.testid + '-match-' + mode);
            b.addEventListener('click', function () {
                if (self.selection.match === mode) return;
                self.selection.match = mode;
                self.selectionChanged();
            });
            match.appendChild(b);
            self.matchButtons[mode] = b;
        });
        wrap.appendChild(match);

        this.picker = { wrap: wrap, button: button, buttonText: buttonText, pop: pop,
                        body: body, note: note, match: match };
        this.outsideHandler = function (e) {
            if (self.pickerOpen && !wrap.contains(e.target)) self.closePicker(false);
        };
        slot.appendChild(wrap);
    };

    DifficultyTimeCard.prototype.openPicker = function () {
        if (this.pickerOpen) return;
        this.pickerOpen = true;
        this.renderPickerList();
        this.picker.pop.hidden = false;
        this.picker.button.setAttribute('aria-expanded', 'true');
        document.addEventListener('mousedown', this.outsideHandler, true);
        var first = this.picker.body.querySelector('input');
        (first || this.picker.pop.querySelector('.dt-picker-done')).focus();
    };

    DifficultyTimeCard.prototype.closePicker = function (returnFocus) {
        if (!this.picker || !this.pickerOpen) return;
        this.pickerOpen = false;
        this.picker.pop.hidden = true;
        this.picker.button.setAttribute('aria-expanded', 'false');
        document.removeEventListener('mousedown', this.outsideHandler, true);
        if (returnFocus) this.picker.button.focus();
    };

    /** Any picker change: redraw the controls now, ask again shortly. */
    DifficultyTimeCard.prototype.selectionChanged = function () {
        this.updatePickerButton();
        if (this.pickerOpen) this.renderPickerList();
        var self = this;
        if (this.debounceTimer) clearTimeout(this.debounceTimer);
        this.debounceTimer = setTimeout(function () {
            self.debounceTimer = null;
            self.load();
        }, DEBOUNCE_MS);
    };

    DifficultyTimeCard.prototype.toggleType = function (tagId, on) {
        var sel = this.selection;
        var at = sel.tagIds.indexOf(tagId);
        if (on && at === -1) sel.tagIds.push(tagId);
        if (!on && at !== -1) sel.tagIds.splice(at, 1);
        // No error type is exclusive with the types.
        if (on) sel.untagged = false;
        if (sel.tagIds.length < 2) sel.match = 'any';
        this.selectionChanged();
    };

    DifficultyTimeCard.prototype.toggleUntagged = function (on) {
        this.selection.untagged = !!on;
        if (on) {
            this.selection.tagIds = [];
            this.selection.match = 'any';
        }
        this.selectionChanged();
    };

    DifficultyTimeCard.prototype.updatePickerButton = function () {
        if (!this.picker) return;
        var sel = this.selection;
        var names = {};
        ((this.payload && this.payload.types) || []).forEach(function (t) { names[t.tag_id] = t.name; });
        var text;
        if (sel.untagged) text = 'No error type';
        else if (!sel.tagIds.length) text = 'All error types';
        else if (sel.tagIds.length === 1) text = names[sel.tagIds[0]] || '1 error type';
        else text = sel.tagIds.length + ' error types';
        this.picker.buttonText.textContent = text;
        this.picker.button.setAttribute('aria-label', 'Error types to highlight: ' + text +
            '. Open to change');
        var active = sel.untagged || sel.tagIds.length > 0;
        this.picker.button.classList.toggle('dt-picker-button--active', active);
        this.picker.button.style.borderColor = sel.tagIds.length
            ? seriesColour(0, sel.tagIds.length) : '';

        var showMatch = !sel.untagged && sel.tagIds.length > 1;
        this.picker.match.hidden = !showMatch;
        for (var mode in this.matchButtons) {
            this.matchButtons[mode].setAttribute('aria-pressed',
                sel.match === mode ? 'true' : 'false');
        }
    };

    DifficultyTimeCard.prototype.pickerOption = function (key, name, count, opts) {
        var self = this;
        var label = el('label', 'dt-picker-option' + (opts.className ? ' ' + opts.className : ''));
        label.setAttribute('data-testid', this.testid + '-picker-option-' + key);
        var box = el('input');
        box.type = 'checkbox';
        box.checked = !!opts.checked;
        box.setAttribute('data-key', key);
        box.addEventListener('change', function () { opts.onChange(box.checked); });
        label.appendChild(box);
        var dot = swatch(opts.colour || 'transparent', 'dt-swatch dt-picker-swatch');
        if (!opts.colour) dot.classList.add('dt-swatch--none');
        label.appendChild(dot);
        var text = el('span', 'dt-picker-text');
        text.appendChild(el('span', 'dt-picker-name', name));
        if (opts.sub) text.appendChild(el('span', 'dt-picker-sub', opts.sub));
        label.appendChild(text);
        label.appendChild(el('span', 'dt-picker-count', count));
        return label;
    };

    /**
     * The list, from the last payload's `types` and `untagged_count`
     * (counts over every mistake in scope, whatever is picked) and the
     * picker's own selection (ticks and colours, which change before the
     * next payload arrives). Rebuilt on every change; focus is put back
     * on the checkbox that had it.
     */
    DifficultyTimeCard.prototype.renderPickerList = function () {
        var self = this;
        var body = this.picker.body;
        var focusedKey = document.activeElement && body.contains(document.activeElement)
            ? document.activeElement.getAttribute('data-key') : null;
        var scrollTop = body.scrollTop;
        while (body.firstChild) body.removeChild(body.firstChild);
        var payload = this.payload || {};
        var sel = this.selection;
        var types = (payload.types || []).slice();

        body.appendChild(this.pickerOption('untagged', 'No error type',
            payload.untagged_count || 0, {
                checked: sel.untagged,
                colour: sel.untagged ? 'var(--dt-series-1)' : null,
                sub: 'Finds mistakes not tagged yet, so you can go back and tag them.',
                className: 'dt-picker-option--untagged',
                onChange: function (on) { self.toggleUntagged(on); }
            }));
        body.appendChild(el('div', 'dt-picker-separator'));

        if (!types.length) {
            body.appendChild(el('p', 'dt-picker-empty',
                'None of these mistakes has an error type yet.'));
        }
        var groups = [];
        var byGroup = {};
        types.forEach(function (t) {
            var key = t.group_id === null || t.group_id === undefined ? 'none' : String(t.group_id);
            if (!byGroup[key]) {
                byGroup[key] = { id: t.group_id, name: t.group_name || 'Other', types: [] };
                groups.push(byGroup[key]);
            }
            byGroup[key].types.push(t);
        });
        groups.sort(function (a, b) {
            if (a.id === null || a.id === undefined) return 1;
            if (b.id === null || b.id === undefined) return -1;
            return a.id - b.id;
        });
        groups.forEach(function (g) {
            var section = el('div', 'dt-picker-group');
            section.setAttribute('role', 'group');
            var heading = el('div', 'dt-picker-group-name', g.name);
            heading.id = self.uid + '-picker-group-' + (g.id === null || g.id === undefined ? 'none' : g.id);
            section.setAttribute('aria-labelledby', heading.id);
            section.appendChild(heading);
            g.types.sort(function (a, b) {
                return a.name < b.name ? -1 : a.name > b.name ? 1 : a.tag_id - b.tag_id;
            });
            g.types.forEach(function (t) {
                var at = sel.tagIds.indexOf(t.tag_id);
                var option = self.pickerOption(String(t.tag_id), t.name, t.count, {
                    checked: at !== -1,
                    colour: at !== -1 ? seriesColour(at, sel.tagIds.length) : null,
                    sub: t.listed_on_exam ? null : 'No longer on this exam',
                    className: t.listed_on_exam ? '' : 'dt-picker-option--removed',
                    onChange: function (on) { self.toggleType(t.tag_id, on); }
                });
                if (t.description) option.title = t.description;
                section.appendChild(option);
            });
            body.appendChild(section);
        });

        var n = sel.tagIds.length;
        var note;
        if (sel.untagged) note = 'Showing mistakes with no error type.';
        else if (!n) note = 'Nothing picked: every mistake is shown. The first ' + SERIES_COUNT + ' types you pick get a colour each.';
        else if (n <= SERIES_COUNT) note = n + ' picked. The first ' + SERIES_COUNT + ' get a colour each.';
        else note = n + ' picked. With more than ' + SERIES_COUNT + ', every match is drawn in one colour.';
        this.picker.note.textContent = note;

        if (focusedKey) {
            var again = body.querySelector('input[data-key="' + focusedKey + '"]');
            if (again) again.focus({ preventScroll: true });
        }
        body.scrollTop = scrollTop;
    };

    // =====================================================================
    // The Every entry tab: a D3 scatter
    // =====================================================================

    var SVG_HEIGHT = 392;
    var MARGIN = { left: 56, right: 20, top: 10, bottom: 42 };
    var JITTER = 0.3;      // of one rating step, either way
    var R_MATCH = 6;
    var R_NONMATCH = 3;
    var R_ALL = 4.5;
    var R_RING = 9.5;

    /**
     * A number in [-1, 1) from an entry id, the same on every draw, so a
     * dot does not jump when the picker changes (a random jitter would).
     */
    function jitterFor(id) {
        var h = Math.imul((Number(id) | 0) ^ 0x9e3779b9, 0x85ebca6b);
        h ^= h >>> 13;
        h = Math.imul(h, 0xc2b2ae35);
        h ^= h >>> 16;
        return ((h >>> 0) / 4294967296) * 2 - 1;
    }

    /** Ticks at whole minutes, at most about eight of them. */
    function minuteTicks(xMax) {
        var minutes = xMax / 60;
        var steps = [1, 2, 5, 10, 15, 30, 60, 120, 240];
        var step = steps[steps.length - 1];
        for (var i = 0; i < steps.length; i++) {
            if (minutes / steps[i] <= 8) { step = steps[i]; break; }
        }
        var ticks = [];
        for (var m = 0; m <= minutes + 1e-9; m += step) ticks.push(m * 60);
        return ticks;
    }

    DifficultyTimeCard.prototype.legend = function (payload, sel) {
        var legend = el('div', 'dt-legend');
        legend.setAttribute('aria-hidden', 'true');
        function key(markClass, colour, text) {
            var item = el('span', 'dt-legend-item');
            var mark = el('span', markClass);
            if (colour) mark.style.background = colour;
            item.appendChild(mark);
            item.appendChild(document.createTextNode(text));
            legend.appendChild(item);
        }
        key('dt-legend-band dt-legend-band--hard', null, 'Hard, rated 4–5');
        key('dt-legend-band dt-legend-band--middle', null, 'Rated 3');
        key('dt-legend-band dt-legend-band--easy', null, 'Easy, rated 1–2');
        if (sel.mode === 'all') {
            key('dt-legend-dot', 'var(--text-primary)', 'A mistake');
        } else {
            if (sel.mode === 'untagged') {
                key('dt-legend-dot', 'var(--dt-series-1)', 'No error type');
            } else if (sel.ids.length > SERIES_COUNT) {
                key('dt-legend-dot', 'var(--dt-series-many)',
                    sel.mode === 'every' ? 'Carries all of these' : 'Carries any of these');
            } else if (sel.mode === 'every') {
                key('dt-legend-dot', sel.colour(sel.ids[0]), 'Carries all of these');
            } else {
                sel.ids.forEach(function (id, i) { key('dt-legend-dot', sel.colour(id), sel.names[i]); });
            }
            if (sel.mode === 'any') key('dt-legend-dot dt-legend-dot--ring', null, 'Carries 2 or more of these');
            key('dt-legend-dot dt-legend-dot--small', 'var(--dt-dot-nonmatch)', 'Other mistakes');
        }
        if (payload.median.available) {
            key('dt-legend-median', null,
                'Your median, ' + links().formatSeconds(payload.median.label_seconds));
        }
        return legend;
    };

    DifficultyTimeCard.prototype.drawScatter = function (payload) {
        var panel = this.panels.every;
        var self = this;
        this.scatterWidth = panel.clientWidth || 0;
        if (!payload || !payload.total) {
            this.replace(panel, el('p', 'dt-empty', 'No mistakes on ' + this.emptyScope +
                ' yet. Each one you log is drawn here as a dot.'));
            return;
        }
        var d3 = global.d3;
        if (!d3) {
            this.replace(panel, el('p', 'dt-error', 'This chart needs D3, which this page did not load.'));
            return;
        }
        var sel = selectionOf(payload);
        var drawn = (payload.entries || []).filter(function (e) { return e.bucket !== 'not_placed'; });
        var typeNames = {};
        (payload.types || []).forEach(function (t) { typeNames[t.tag_id] = t.name; });
        var parts = [this.legend(payload, sel)];

        var footer = el('div', 'dt-scatter-footer');
        footer.setAttribute('data-testid', this.testid + '-scatter-footer');
        footer.appendChild(el('p', null,
            'One dot per mistake, on bands coloured by difficulty rating. Picking an error type colours the dots that carry it and draws the others smaller. Hover a dot to see its entry and its error types; click it to open it. Dots line up in columns at whole minutes because time is often entered that way, and dots with the same rating are spread a little up and down so fewer hide behind another.'));

        var matched = drawn.filter(function (e) { return e.matches; }).length;
        var ringed = sel.mode === 'any'
            ? drawn.filter(function (e) { return e.matches && e.picked_hits.length >= 2; }).length : 0;
        var sentences = [];
        var D = drawn.length;
        if (sel.mode === 'one') {
            sentences.push(matched + ' of the ' + D + ' dots ' + plural(matched, 'is', 'are') +
                ' tagged ' + sel.names[0] + '.');
        } else if (sel.mode === 'untagged') {
            sentences.push(matched + ' of the ' + D + ' dots ' + plural(matched, 'has', 'have') +
                ' no error type yet.');
        } else if (sel.mode === 'any') {
            sentences.push(matched + ' of the ' + D + ' dots carry at least one of the ' +
                sel.ids.length + ' picked error types; ' + ringed + ' ' +
                plural(ringed, 'carries', 'carry') + ' two or more and ' +
                plural(ringed, 'is', 'are') + ' ringed, coloured by the first type ' +
                plural(ringed, 'it carries', 'they carry') + '.');
        } else if (sel.mode === 'every') {
            sentences.push(matched + ' of the ' + D + ' dots carry all ' + sel.ids.length +
                ' picked error types.');
        }
        if (sel.mode !== 'all' && sel.mode !== 'untagged') {
            sentences.push(sel.ids.length > SERIES_COUNT
                ? 'With more than ' + SERIES_COUNT + ' types picked, every match is drawn in one colour.'
                : 'Up to ' + SERIES_COUNT + ' types get a colour each; pick a fifth and every match turns one colour.');
        }
        var notDrawn = payload.total - D;
        sentences.push(D + ' of ' + mistakes(payload.total) + ' shown.');
        if (notDrawn > 0) {
            sentences.push(notDrawn + ' ' + plural(notDrawn, 'has', 'have') +
                ' no difficulty rating or no time spent and ' +
                plural(notDrawn, 'is', 'are') + ' not drawn.');
        }
        var clipped = (payload.axis && payload.axis.clipped_count) || 0;
        var xMax = payload.axis && payload.axis.x_max_seconds;
        if (clipped > 0) {
            sentences.push(clipped + ' ' + plural(clipped, 'takes', 'take') + ' longer than ' +
                links().formatSeconds(xMax) + ' and ' + plural(clipped, 'is', 'are') +
                ' drawn at the right edge.');
        }
        var counts = el('p', null, sentences.join(' '));
        counts.setAttribute('data-testid', this.testid + '-scatter-counts');
        footer.appendChild(counts);
        var keyboard = el('p', 'dt-keyboard-note',
            'The dots cannot be reached with the keyboard. The Quadrants tab opens the same mistakes in the entry browser, a quadrant at a time.');
        keyboard.setAttribute('data-testid', this.testid + '-keyboard-note');
        footer.appendChild(keyboard);

        if (!D || !xMax) {
            parts.push(el('p', 'dt-empty',
                'No mistake has both a difficulty rating and a time spent yet, so there is nothing to plot.'));
            parts.push(footer);
            this.replace.apply(this, [panel].concat(parts));
            return;
        }

        var W = Math.max(560, this.scatterWidth || 836);
        var H = SVG_HEIGHT;
        var plotW = W - MARGIN.left - MARGIN.right;
        var plotH = H - MARGIN.top - MARGIN.bottom;
        var step = plotH / 5;
        var x = d3.scaleLinear().domain([0, xMax]).range([MARGIN.left, MARGIN.left + plotW]);
        var yOf = function (rating) { return MARGIN.top + (5 - rating) * step + step / 2; };

        var summary = 'Scatter plot of ' + mistakes(D) +
            ': time spent across, difficulty rating up.' +
            (payload.median.available
                ? ' A dashed line marks your median, ' +
                  links().formatSeconds(payload.median.label_seconds) + '.'
                : '') +
            (sentences.length && sel.mode !== 'all' ? ' ' + sentences[0] : '') +
            ' The Quadrants tab reaches these mistakes by keyboard.';

        var wrap = el('div', 'dt-scatter-wrap');
        var svg = d3.create('svg')
            .attr('class', 'dt-scatter')
            .attr('viewBox', '0 0 ' + W + ' ' + H)
            .attr('width', '100%')
            .attr('role', 'img')
            .attr('aria-label', summary)
            .attr('data-testid', this.testid + '-scatter');

        var bands = svg.append('g').attr('class', 'dt-bands');
        bands.append('rect').attr('class', 'dt-band dt-band--hard')
            .attr('x', MARGIN.left).attr('y', MARGIN.top).attr('width', plotW).attr('height', 2 * step);
        bands.append('rect').attr('class', 'dt-band dt-band--middle')
            .attr('x', MARGIN.left).attr('y', MARGIN.top + 2 * step).attr('width', plotW).attr('height', step);
        bands.append('rect').attr('class', 'dt-band dt-band--easy')
            .attr('x', MARGIN.left).attr('y', MARGIN.top + 3 * step).attr('width', plotW).attr('height', 2 * step);

        var ticks = minuteTicks(xMax);
        var grid = svg.append('g').attr('class', 'dt-gridlines');
        ticks.forEach(function (t) {
            if (t <= 0) return;
            grid.append('line').attr('class', 'dt-gridline')
                .attr('x1', x(t)).attr('x2', x(t))
                .attr('y1', MARGIN.top).attr('y2', MARGIN.top + plotH);
        });
        svg.append('line').attr('class', 'dt-axis-line')
            .attr('x1', MARGIN.left).attr('x2', MARGIN.left + plotW)
            .attr('y1', MARGIN.top + plotH).attr('y2', MARGIN.top + plotH);
        svg.append('line').attr('class', 'dt-axis-line')
            .attr('x1', MARGIN.left).attr('x2', MARGIN.left)
            .attr('y1', MARGIN.top).attr('y2', MARGIN.top + plotH);

        var yLabels = svg.append('g').attr('class', 'dt-tick-labels').attr('text-anchor', 'end');
        [1, 2, 3, 4, 5].forEach(function (r) {
            yLabels.append('text').attr('x', MARGIN.left - 8).attr('y', yOf(r) + 4).text(String(r));
        });
        var xLabels = svg.append('g').attr('class', 'dt-tick-labels').attr('text-anchor', 'middle');
        ticks.forEach(function (t) {
            xLabels.append('text').attr('x', x(t)).attr('y', MARGIN.top + plotH + 18)
                .text(t === 0 ? '0' : links().formatSeconds(t));
        });
        svg.append('text').attr('class', 'dt-axis-title').attr('text-anchor', 'middle')
            .attr('x', MARGIN.left + plotW / 2).attr('y', H - 4).text('Time spent');
        svg.append('text').attr('class', 'dt-axis-title').attr('text-anchor', 'middle')
            .attr('transform', 'rotate(-90 14 ' + (MARGIN.top + plotH / 2) + ')')
            .attr('x', 14).attr('y', MARGIN.top + plotH / 2).text('Difficulty');

        if (payload.median.available) {
            var corners = svg.append('g').attr('class', 'dt-corner-labels');
            corners.append('text').attr('x', MARGIN.left + 8).attr('y', MARGIN.top + 16).text('Hard and fast');
            corners.append('text').attr('x', MARGIN.left + plotW - 8).attr('y', MARGIN.top + 16)
                .attr('text-anchor', 'end').text('Hard and slow');
            corners.append('text').attr('x', MARGIN.left + 8).attr('y', MARGIN.top + plotH - 8).text('Easy and fast');
            corners.append('text').attr('x', MARGIN.left + plotW - 8).attr('y', MARGIN.top + plotH - 8)
                .attr('text-anchor', 'end').text('Easy and slow');
            var mx = x(Math.min(payload.median.label_seconds, xMax));
            svg.append('line').attr('class', 'dt-median')
                .attr('data-testid', this.testid + '-median')
                .attr('x1', mx).attr('x2', mx).attr('y1', MARGIN.top).attr('y2', MARGIN.top + plotH);
        }

        // Each dot's kind and colour. Non-matches first, so matches and
        // rings are drawn over them.
        var rank = { nonmatch: 0, all: 1, match: 2 };
        var dots = drawn.map(function (e) {
            var kind = sel.mode === 'all' ? 'all' : (e.matches ? 'match' : 'nonmatch');
            var colour = 'var(--text-primary)';
            if (kind === 'nonmatch') colour = 'var(--dt-dot-nonmatch)';
            if (kind === 'match') {
                colour = sel.mode === 'untagged'
                    ? (sel.ids.length > SERIES_COUNT ? 'var(--dt-series-many)' : 'var(--dt-series-1)')
                    : sel.colour(e.picked_hits[0]);
            }
            return {
                e: e, kind: kind, colour: colour,
                ringed: sel.mode === 'any' && kind === 'match' && e.picked_hits.length >= 2,
                cx: x(Math.min(e.t, xMax)),
                cy: yOf(e.d + JITTER * jitterFor(e.id)),
                clipped: e.t > xMax
            };
        });
        dots.sort(function (a, b) {
            return (rank[a.kind] - rank[b.kind]) || (a.ringed - b.ringed) || (a.e.id - b.e.id);
        });

        var hover = el('div', 'dt-hover');
        hover.hidden = true;
        hover.setAttribute('aria-hidden', 'true');
        hover.setAttribute('data-testid', this.testid + '-scatter-hover');

        var layer = svg.append('g').attr('class', 'dt-dots');
        dots.forEach(function (dot) {
            var r = dot.kind === 'match' ? R_MATCH : dot.kind === 'nonmatch' ? R_NONMATCH : R_ALL;
            var circle = layer.append('circle')
                .attr('class', 'dt-dot dt-dot--' + dot.kind + (dot.clipped ? ' dt-dot--clipped' : ''))
                .attr('cx', dot.cx).attr('cy', dot.cy).attr('r', r)
                .attr('data-entry-id', dot.e.id)
                .style('fill', dot.colour);
            if (dot.ringed) {
                layer.append('circle').attr('class', 'dt-dot-ring')
                    .attr('data-entry-id', dot.e.id)
                    .attr('cx', dot.cx).attr('cy', dot.cy).attr('r', R_RING);
            }
            circle.on('mouseenter', function () { self.showHover(hover, wrap, this, dot.e, typeNames); })
                .on('mouseleave', function () { hover.hidden = true; })
                .on('click', function () { self.openEntry(dot.e); });
        });

        wrap.appendChild(svg.node());
        wrap.appendChild(hover);
        parts.push(wrap);
        parts.push(footer);
        this.replace.apply(this, [panel].concat(parts));
    };

    /** The hover box: every line a text node, error-type names included. */
    DifficultyTimeCard.prototype.showHover = function (hover, wrap, circle, e, typeNames) {
        while (hover.firstChild) hover.removeChild(hover.firstChild);
        var title = e.session_name || ('Entry ' + e.id);
        if (e.question_id) title += ', question ' + e.question_id;
        hover.appendChild(el('div', 'dt-hover-title', title));
        var subjects = (e.subjects || []).map(function (s) { return s.name; });
        hover.appendChild(el('div', null, subjects.length ? subjects.join(', ') : 'No subject'));
        var d = global.WimiDifficulty;
        var word = d ? d.labelFor(e.d) : '';
        var rating = (word ? word + ', rated ' : 'Rated ') + e.d;
        hover.appendChild(el('div', null, rating + ' · ' + links().formatSeconds(e.t) +
            (e.is_draft ? ' · draft' : '')));
        var types = (e.tag_ids || []).map(function (id) { return typeNames[id] || ('Error type ' + id); });
        hover.appendChild(el('div', 'dt-hover-types', types.length ? types.join(', ') : 'No error type'));
        hover.appendChild(el('div', 'dt-hover-action', 'Click to open the entry'));
        hover.hidden = false;
        var box = wrap.getBoundingClientRect();
        var c = circle.getBoundingClientRect();
        var left = c.right - box.left + 10;
        var top = c.top - box.top - 10;
        var width = hover.offsetWidth;
        var height = hover.offsetHeight;
        if (left + width > box.width) left = Math.max(0, c.left - box.left - width - 10);
        if (top + height > box.height) top = Math.max(0, box.height - height);
        hover.style.left = left + 'px';
        hover.style.top = Math.max(0, top) + 'px';
    };

    /**
     * Open one entry, at the URL the entry browser and the deep dive use.
     * entry_detail reads a prev/next list the entry browser leaves in
     * sessionStorage; one left from an earlier browse would draw a stale
     * "N of M" bar around an entry opened from here.
     */
    DifficultyTimeCard.prototype.openEntry = function (e) {
        if (this.onOpenEntry) {
            this.onOpenEntry(e.id, e);
            return;
        }
        try { sessionStorage.removeItem('entryNavContext'); } catch (err) { /* storage unavailable */ }
        var exam = this.scope.examContextId ? '&exam=' + this.scope.examContextId : '';
        global.location.href = 'entry_detail.html?id=' + e.id + exam;
    };

    global.DifficultyTimeCard = DifficultyTimeCard;
})(window);
