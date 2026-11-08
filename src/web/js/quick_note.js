/**
 * quick_note.js -- the Quick note dialog (#848 Wave 2a).
 *
 * A student mid-session has something worth writing down and no entry to put
 * it on. This dialog saves a note on its own (a row in `entry_notes` with a
 * NULL origin, decision 1) the moment Save is pressed, and lists the notes on
 * their own for editing under *Your notes* (decision 3). The entry form opens
 * it from a header button and from Ctrl+Shift+N; Wave 2b opens the same
 * dialog on the subject deep dive, which is why it is a module and not a
 * block of question_entry.js.
 *
 * What it owns and what it is given
 * ---------------------------------
 * It builds its own markup on first open, mounted at `<body>` level like the
 * entry form's other modals, and talks to the bridge through `window.api`
 * only. It knows nothing about the page it sits on: no EntryState, no Modal,
 * no Toast. The page passes what the dialog needs in `open(options)`:
 *
 *   subjects        [{id, name}] used to name subject chips
 *   chooseSubjects  async (currentIds) => ids | null -- opens the page's own
 *                   subject-choosing modal and resolves to the chosen ids
 *   onSaved         (note) => void -- after a note is written or edited; the
 *                   note carries id, content_html and linked_subject_ids so a
 *                   page holding that note as a card can redraw it (a free
 *                   note attached through + Add existing is both a card and a
 *                   Your notes row, and the entry's next save rewrites every
 *                   card from the card's own content)
 *   onDeleted       (noteId) => void -- after a Your notes delete, so a page
 *                   holding that note as a card drops the card before its next
 *                   save references a row that no longer exists
 *   notify          (title, text, kind) => void -- a toast, in the page's voice
 *   view            'new' (default) or 'list'
 *   mount           the element to append the dialog to (default body)
 *
 * Three more that only the subject deep dive passes (#848 Wave 2b); the entry
 * form passes none of them, so its dialog is exactly Wave 2a's:
 *
 *   subjectIds      [ids] a new note starts tagged with (the deep dive's own
 *                   subject); the student may remove it
 *   entryChoice     {examContextId, subjectId, subjectName} -- adds "Where
 *                   does this note live?" to the New note view: On its own
 *                   (a free note, the path above) or On an entry, chosen in a
 *                   second step inside this dialog by session and then from
 *                   previews (owner's decision 5, #848 comment 11594). The
 *                   entry branch writes an ORDINARY entry note through
 *                   `api.addEntryNote`; only the free branch is new.
 *   edit            a note on its own to open for editing, the state Your
 *                   notes' Edit sets; Save and Cancel then close the dialog
 *                   rather than returning to a list the student never saw
 *
 * The entry picker
 * ----------------
 * A step, not a second dialog (decision 5: "a second step inside the one
 * dialog with a Back control"; #319's boundary walk handles one surface at a
 * time). It hides the header, tabs, New note panel and footer and shows its
 * own panel; the editor is NOT destroyed, only hidden with its panel, so Back
 * returns to the note exactly as it was. The candidates are what the entry
 * browser's subject filter returns (#13: entries tagged with the subject
 * directly, plus entries on its descendants routing through it), read through
 * the same slot, `getEntriesPaginated`, with `include_child_subjects`; the
 * checkbox drops the subject filter and keeps the exam. Drafts are offered and
 * marked (#12: a draft is a mistake that happened). Every string a card shows
 * is student-typed, so it reaches the page as textContent only.
 *
 * The dialog semantics
 * --------------------
 * The surface carries `data-modal-surface`, `role="dialog"`,
 * `aria-modal="true"` and `aria-labelledby` pointing at its visible h2, so
 * `modal_dialog.js` (#318/#319) draws the aria-hidden boundary, moves focus
 * in and restores it on close -- it watches childList, so a surface created
 * on demand is seen. Escape closes it when it is the topmost dialog, and the
 * subject chooser opened over it is left alone.
 *
 * The editor
 * ----------
 * The same RichEditor class the note cards use, created when the compose
 * view shows and destroyed on close. A RichEditor flushes queued content over
 * the editor when TinyMCE's `init` fires (#47/#114), so content for an edit is
 * handed to it before init and nothing else writes to it until then.
 *
 * Public surface, kept small on purpose:
 *   QuickNote.open(options), QuickNote.close(), QuickNote.isOpen(),
 *   QuickNote.editor() (the live RichEditor, for scenarios),
 *   QuickNote.isPicking() (the entry step is showing; Wave 2b, for scenarios).
 */
(function () {
    'use strict';

    // Your notes is drawn a page at a time, never cut off. Decision 3 made the
    // subject tag optional because an untagged free note is always reachable
    // from this list, so a fixed cap that drew 50 and called it the total
    // would make the 51st-newest note reachable from nowhere. The dialog asks
    // for one more than it shows: a longer answer means there are more, and
    // the footer, the tab count and a Show more button say so instead of
    // stating the page size as the total.
    const LIST_PAGE = 50;

    // The picker reads the candidate set a page at a time until it has all
    // of it, because the session column's counts are counts of the WHOLE set
    // and a count taken over a truncated read would be a number the dialog
    // cannot vouch for. The page ceiling is a guard against a runaway loop,
    // not a display cap; reaching it is said in the status line.
    const PICK_PAGE = 200;
    const PICK_MAX_PAGES = 25;
    // Cards drawn at once. Past this the status line says how many matched
    // and asks for a session or a search, rather than laying out thousands of
    // previews (#212's lesson: layout, not the data, is the cost).
    const PICK_CARD_LIMIT = 100;

    const INTRO_ENTRY_FORM = 'A note of your own, not part of this entry. It is saved on its own the moment you press Save.';
    const INTRO_OWN = 'A note of your own, on no entry. It is saved on its own the moment you press Save.';
    const INTRO_ON_ENTRY = 'A note on one of your entries, saved onto it the moment you press Save.';

    function freshPick() {
        return {
            token: 0, loaded: false, loading: false, error: null,
            widened: false, sessionId: null, query: '',
            entries: [], total: 0, truncated: false,
            sessionsById: null, sourcesById: null
        };
    }

    const state = {
        built: false,
        backdrop: null,
        surface: null,
        els: {},
        options: {},
        isOpen: false,
        view: 'new',
        editor: null,
        editing: null,       // {id, linked_subject_ids} while a free note is edited
        subjectIds: [],
        notes: [],
        limit: LIST_PAGE,    // how many Your notes rows are asked for
        hasMore: false,      // the slot had more than `limit`
        invoker: null,
        busy: false,
        // Wave 2b (the deep dive): see the header comment.
        defaultSubjectIds: [],
        entryChoice: null,
        where: 'own',        // 'own' | 'entry', only with entryChoice
        chosenEntry: null,   // the entry an On-an-entry note will go on
        editReturn: 'list',  // where Save/Cancel lead after an edit
        picking: false,
        pick: freshPick()
    };

    // ------------------------------------------------------------------ DOM

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function button(className, text, testid) {
        const b = el('button', className, text);
        b.type = 'button';
        if (testid) b.dataset.testid = testid;
        return b;
    }

    function build(mount) {
        if (state.built) return;

        // Written as a literal so tests/test_modal_dialog_js.py's overlay
        // detector sees that this module builds a modal.
        const backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop quick-note-backdrop';
        backdrop.id = 'quick-note-modal';

        const surface = el('div', 'modal quick-note-modal');
        surface.dataset.testid = 'quick-note-dialog';
        // The dialog semantics go on the SURFACE, never on the backdrop --
        // docs/guides/MODAL_DIALOG.md.
        surface.setAttribute('data-modal-surface', '');
        surface.setAttribute('role', 'dialog');
        surface.setAttribute('aria-modal', 'true');
        surface.setAttribute('aria-labelledby', 'quick-note-title');

        // Header: title and Close.
        const header = el('div', 'qn-header');
        const title = el('h2', 'modal-title qn-title', 'Quick note');
        title.id = 'quick-note-title';
        const closeBtn = button('qn-close', '×', 'quick-note-close');
        closeBtn.setAttribute('aria-label', 'Close');
        closeBtn.addEventListener('click', close);
        header.append(title, closeBtn);

        // Tabs.
        const tabs = el('div', 'qn-tabs');
        tabs.setAttribute('role', 'tablist');
        tabs.setAttribute('aria-label', 'Quick note views');
        const tabNew = button('qn-tab', 'New note', 'quick-note-tab-new');
        tabNew.id = 'quick-note-tab-new';
        tabNew.setAttribute('role', 'tab');
        tabNew.setAttribute('aria-controls', 'quick-note-panel-new');
        const tabList = button('qn-tab', 'Your notes', 'quick-note-tab-list');
        tabList.id = 'quick-note-tab-list';
        tabList.setAttribute('role', 'tab');
        tabList.setAttribute('aria-controls', 'quick-note-panel-list');
        const count = el('span', 'qn-count', '');
        count.dataset.testid = 'quick-note-list-count';
        count.hidden = true;
        tabList.appendChild(count);
        tabNew.addEventListener('click', () => showCompose());
        tabList.addEventListener('click', () => { showList(); });
        tabs.addEventListener('keydown', onTabKeydown);
        tabs.append(tabNew, tabList);

        // Compose panel.
        const panelNew = el('div', 'qn-panel');
        panelNew.id = 'quick-note-panel-new';
        panelNew.setAttribute('role', 'tabpanel');
        panelNew.setAttribute('aria-labelledby', tabNew.id);
        const intro = el('p', 'qn-hint qn-intro', INTRO_ENTRY_FORM);
        const where = buildWhere();
        const editorHost = el('div', 'rich-editor-container qn-editor-host');
        editorHost.id = 'quick-note-editor';
        editorHost.dataset.testid = 'quick-note-editor';
        const subjectsRow = el('div', 'qn-subjects-row');
        const subjectsLabel = el('span', 'qn-label', 'Subjects');
        const chips = el('span', 'qn-chips');
        chips.dataset.testid = 'quick-note-subject-chips';
        const subjectsBtn = button('btn btn-text qn-subjects-btn', 'Subjects…', 'quick-note-subjects-button');
        subjectsBtn.addEventListener('click', onChooseSubjects);
        subjectsRow.append(subjectsLabel, chips, subjectsBtn);
        const tagHint = el('p', 'qn-hint qn-tag-hint');
        tagHint.append(
            document.createTextNode('Tag a subject and later entries about it offer this note under '),
            el('b', null, '+ Add existing'),
            document.createTextNode('. Leave it General and it stays under '),
            el('b', null, 'Your notes'),
            document.createTextNode('.'));
        // The status line is NEVER hidden, not even while empty. A live
        // region announces changes to a node already in the accessibility
        // tree; a node that enters the tree with its text in place is an
        // addition to its parent, which is not live, so a `hidden` status
        // written and revealed in one tick is painted and never spoken
        // (#127's rule, measured there through CDP: display: none takes the
        // node out of the tree). It sits in the tree as an empty <p> with no
        // margin and only its text changes.
        const status = el('p', 'qn-status');
        status.setAttribute('role', 'status');
        status.dataset.testid = 'quick-note-status';
        panelNew.append(intro, where.row, where.box, editorHost, subjectsRow, tagHint, status);

        // List panel.
        const panelList = el('div', 'qn-panel');
        panelList.id = 'quick-note-panel-list';
        panelList.setAttribute('role', 'tabpanel');
        panelList.setAttribute('aria-labelledby', tabList.id);
        panelList.hidden = true;
        // The landing place after a delete empties the list: focus has to go
        // somewhere inside the dialog, and the panel now holds the "No notes"
        // sentence.
        panelList.tabIndex = -1;
        const listIntro = el('p', 'qn-hint',
            'Notes that belong to you rather than to an entry, newest first. Press one to edit it.');
        const list = el('div', 'qn-list');
        list.dataset.testid = 'quick-note-list';
        const empty = el('p', 'qn-empty', 'No notes on their own yet.');
        empty.dataset.testid = 'quick-note-empty';
        empty.hidden = true;
        const more = button('btn btn-secondary btn-sm qn-more', 'Show more', 'quick-note-show-more');
        more.hidden = true;
        more.addEventListener('click', showMore);
        panelList.append(listIntro, list, empty, more);

        // Footer: one left text and two buttons, relabelled per view.
        const footer = el('div', 'qn-footer');
        const footerText = el('span', 'qn-footer-text', '');
        footerText.id = 'quick-note-footer-text';
        footerText.dataset.testid = 'quick-note-footer-text';
        const footerActions = el('div', 'qn-footer-actions');
        const secondary = button('btn btn-secondary', 'Cancel', 'quick-note-secondary-button');
        const primary = button('btn btn-primary', 'Save note', 'quick-note-save-button');
        secondary.addEventListener('click', onSecondary);
        primary.addEventListener('click', onPrimary);
        footerActions.append(secondary, primary);
        footer.append(footerText, footerActions);

        const pick = buildPicker();

        surface.append(header, tabs, panelNew, panelList, pick.panel, footer);
        backdrop.appendChild(surface);
        // In the entry step a stray click outside is Back, like Escape:
        // closing from there would discard a note the student cannot see.
        backdrop.addEventListener('click', (e) => {
            if (e.target !== backdrop) return;
            if (state.picking) { exitPicker(); return; }
            close();
        });
        (mount || document.body).appendChild(backdrop);

        state.backdrop = backdrop;
        state.surface = surface;
        state.els = {
            tabNew, tabList, count, panelNew, panelList, editorHost, chips,
            subjectsBtn, status, list, empty, more, footerText, secondary, primary, closeBtn,
            header, tabs, footer, intro, tagHint, where, pick
        };
        state.built = true;
    }

    /**
     * "Where does this note live?" and the chosen entry's summary (#848
     * Wave 2b). Built on every page and shown only when the page passes
     * `entryChoice`, so the entry form's dialog never draws it.
     *
     * The control is a pair of toggle buttons in a named group, not a radio
     * pair: the mockup draws a segmented control, and aria-pressed on two
     * buttons is what such a control announces as.
     */
    function buildWhere() {
        const row = el('div', 'qn-where-row');
        row.dataset.testid = 'quick-note-where';
        row.hidden = true;
        const label = el('span', 'qn-label', 'Where does this note live?');
        label.id = 'quick-note-where-label';
        const seg = el('div', 'qn-seg');
        seg.setAttribute('role', 'group');
        seg.setAttribute('aria-labelledby', label.id);
        const own = button('qn-seg-btn', 'On its own', 'quick-note-where-own');
        const onEntry = button('qn-seg-btn', 'On an entry', 'quick-note-where-entry');
        own.addEventListener('click', () => setWhere('own'));
        onEntry.addEventListener('click', () => setWhere('entry'));
        seg.append(own, onEntry);
        row.append(label, seg);

        const box = el('div', 'qn-entry-box');
        box.dataset.testid = 'quick-note-entry-box';
        box.hidden = true;
        const summary = el('div', 'qn-entry-summary');
        summary.id = 'quick-note-entry-summary';
        summary.dataset.testid = 'quick-note-entry-summary';
        const choose = button('btn btn-secondary btn-sm qn-entry-choose', 'Choose an entry',
            'quick-note-choose-entry');
        choose.setAttribute('aria-describedby', summary.id);
        choose.addEventListener('click', () => enterPicker());
        box.append(summary, choose);
        return { row, own, onEntry, box, summary, choose };
    }

    function backIcon() {
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('width', '18');
        svg.setAttribute('height', '18');
        svg.setAttribute('viewBox', '0 0 20 20');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('aria-hidden', 'true');
        svg.setAttribute('focusable', 'false');
        const path = document.createElementNS(ns, 'path');
        path.setAttribute('d', 'M12.5 5L7.5 10L12.5 15');
        path.setAttribute('stroke', 'currentColor');
        path.setAttribute('stroke-width', '2');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(path);
        return svg;
    }

    /** The choose-an-entry step: its own head, a sessions column, a search and the cards. */
    function buildPicker() {
        const panel = el('div', 'qn-pick');
        panel.dataset.testid = 'quick-note-picker';
        panel.hidden = true;

        const head = el('div', 'qn-pick-head');
        const back = button('qn-pick-back', null, 'quick-note-picker-back');
        back.setAttribute('aria-label', 'Back to the note');
        back.appendChild(backIcon());
        back.addEventListener('click', () => exitPicker());
        const titles = el('div', 'qn-pick-titles');
        const title = el('h2', 'modal-title qn-title', 'Choose an entry');
        title.id = 'quick-note-picker-title';
        const lede = el('p', 'qn-hint qn-pick-lede');
        lede.dataset.testid = 'quick-note-picker-lede';
        titles.append(title, lede);
        const widenLabel = el('label', 'qn-pick-widen');
        const widen = document.createElement('input');
        widen.type = 'checkbox';
        widen.dataset.testid = 'quick-note-picker-widen';
        widen.addEventListener('change', () => {
            state.pick.widened = widen.checked;
            state.pick.sessionId = null;
            renderPickerLede();
            loadPicker();
        });
        widenLabel.append(widen, document.createTextNode('Show every entry in this exam'));
        const close2 = button('qn-close', '×', 'quick-note-picker-close');
        close2.setAttribute('aria-label', 'Close');
        close2.addEventListener('click', close);
        head.append(back, titles, widenLabel, close2);

        const body = el('div', 'qn-pick-body');
        const aside = el('div', 'qn-pick-aside');
        const sessionsLabel = el('span', 'qn-label qn-pick-aside-label', 'Sessions');
        sessionsLabel.id = 'quick-note-picker-sessions-label';
        const sessions = el('div', 'qn-pick-sessions');
        sessions.setAttribute('role', 'group');
        sessions.setAttribute('aria-labelledby', sessionsLabel.id);
        sessions.dataset.testid = 'quick-note-picker-sessions';
        aside.append(sessionsLabel, sessions);

        const main = el('div', 'qn-pick-main');
        const searchLabel = el('label', 'qn-visually-hidden', 'Search entries');
        searchLabel.htmlFor = 'quick-note-picker-search';
        const search = document.createElement('input');
        search.type = 'search';
        search.id = 'quick-note-picker-search';
        search.className = 'qn-pick-search';
        search.placeholder = 'Search question id, answers or text…';
        search.dataset.testid = 'quick-note-picker-search';
        search.addEventListener('input', () => {
            state.pick.query = search.value;
            renderPickerEntries();
        });
        // Never hidden, for the reason build() gives for the compose status.
        const pickStatus = el('p', 'qn-hint qn-pick-status');
        pickStatus.setAttribute('role', 'status');
        pickStatus.dataset.testid = 'quick-note-picker-status';
        const cards = el('div', 'qn-pick-cards');
        cards.dataset.testid = 'quick-note-picker-entries';
        main.append(searchLabel, search, pickStatus, cards);
        body.append(aside, main);

        panel.append(head, body);
        return { panel, back, title, lede, widen, sessions, search, status: pickStatus, cards };
    }

    // ---------------------------------------------------------------- helpers

    function bridge() {
        return window.api;
    }

    function notify(title, text, kind) {
        const fn = state.options.notify;
        if (typeof fn === 'function') {
            try { fn(title, text, kind || 'success'); } catch (err) { console.warn('QuickNote notify failed', err); }
        }
    }

    /** Write or clear the status line's text. Only the text: see build(). */
    function setStatus(text) {
        const s = state.els.status;
        if (!s) return;
        s.textContent = text || '';
    }

    function setBusy(busy) {
        state.busy = busy;
        refreshPrimary();
    }

    /** Is the New note view on "On an entry" with no entry chosen yet? */
    function needsEntry() {
        return !!state.entryChoice && !state.editing && state.view === 'new'
            && state.where === 'entry' && !state.chosenEntry;
    }

    /**
     * Save is disabled while it cannot do what it says, and the footer line
     * beside it states why (#174: a control that cannot work says so). The
     * disabled button is described by that line, so a reader that reaches it
     * hears the reason with it.
     */
    function refreshPrimary() {
        const { primary, footerText } = state.els;
        if (!primary) return;
        const blocked = needsEntry();
        primary.disabled = state.busy || blocked;
        if (blocked) primary.setAttribute('aria-describedby', footerText.id);
        else primary.removeAttribute('aria-describedby');
    }

    function subjectName(id) {
        const list = Array.isArray(state.options.subjects) ? state.options.subjects : [];
        const hit = list.find((s) => s && s.id === id);
        return hit ? hit.name : null;
    }

    /** Chips for a list of subject ids: names where they resolve, a count for the rest. */
    function renderChips(target, ids, testidPrefix) {
        target.replaceChildren();
        const known = (ids || []).filter((id) => subjectName(id) !== null);
        const unknown = (ids || []).length - known.length;
        if (!ids || ids.length === 0) {
            const chip = el('span', 'qn-chip qn-chip-general', 'General');
            if (testidPrefix) chip.dataset.testid = `${testidPrefix}-general`;
            target.appendChild(chip);
            return;
        }
        for (const id of known) {
            const chip = el('span', 'qn-chip', subjectName(id));
            if (testidPrefix) chip.dataset.testid = `${testidPrefix}-${id}`;
            target.appendChild(chip);
        }
        if (unknown > 0) {
            target.appendChild(el('span', 'qn-chip', `${unknown} subject${unknown === 1 ? '' : 's'}`));
        }
    }

    function sameIds(a, b) {
        const x = [...new Set(a || [])].sort((p, q) => p - q);
        const y = [...new Set(b || [])].sort((p, q) => p - q);
        return x.length === y.length && x.every((v, i) => v === y[i]);
    }

    /**
     * A stored stamp as the student's own calendar day, in the entry
     * browser's spelling (`Nov 5, 2026`). SQLite's CURRENT_TIMESTAMP is UTC
     * and arrives without a zone designator, so one is added before the
     * instant is turned into a local day through LocalDate.
     */
    function formatDay(stamp) {
        if (!stamp) return '';
        const text = String(stamp);
        const zoned = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(text);
        const instant = new Date(zoned ? text : text + 'Z');
        if (isNaN(instant.getTime())) return text.slice(0, 10);
        const day = LocalDate.parse(LocalDate.toISODate(instant));
        return day.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    function previewText(html) {
        try {
            if (window.WimiTextPreview) return window.WimiTextPreview.htmlToPreviewText(html);
        } catch (err) { /* fall through */ }
        return '';
    }

    /** A session's date-only day (local, #534), in the deep dive's spelling: `Nov 3`. */
    function formatSessionDay(dateStr) {
        if (!dateStr) return '';
        try {
            const day = LocalDate.parse(String(dateStr).slice(0, 10));
            if (isNaN(day.getTime())) return '';
            return day.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        } catch (err) {
            return '';
        }
    }

    function plural(n, one, many) {
        return `${n} ${n === 1 ? one : many}`;
    }

    function cleanIds(ids) {
        return Array.isArray(ids) ? ids.map(Number).filter(Number.isInteger) : [];
    }

    /** The tags a note will carry, as the footer says them. */
    function tagPhrase(ids) {
        if (!ids || ids.length === 0) return 'with no subject';
        const names = ids.map(subjectName).filter((n) => n !== null);
        const unknown = ids.length - names.length;
        if (unknown > 0) names.push(plural(unknown, 'other subject', 'other subjects'));
        return 'tagged ' + names.join(', ');
    }

    // ----------------------------------------------------------------- views

    function selectTab(which) {
        const { tabNew, tabList, panelNew, panelList } = state.els;
        const composing = which === 'new';
        tabNew.setAttribute('aria-selected', composing ? 'true' : 'false');
        tabList.setAttribute('aria-selected', composing ? 'false' : 'true');
        tabNew.tabIndex = composing ? 0 : -1;
        tabList.tabIndex = composing ? -1 : 0;
        tabNew.classList.toggle('qn-tab-active', composing);
        tabList.classList.toggle('qn-tab-active', !composing);
        panelNew.hidden = !composing;
        panelList.hidden = composing;
        state.view = which;
    }

    function onTabKeydown(e) {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        if (state.view === 'new') { showList(); state.els.tabList.focus(); }
        else { showCompose(); state.els.tabNew.focus(); }
    }

    function ensureEditor(initialHtml) {
        if (state.editor) return state.editor;
        const host = state.els.editorHost;
        host.replaceChildren();
        const editor = new RichEditor(host, {
            placeholder: 'Write your note here...',
            height: 260,
            onReady: () => {
                // Land the caret in the editor once it exists, unless the
                // student has already moved on to something else in the
                // dialog or the dialog has closed meanwhile. Focus that is
                // NOT inside the dialog counts as loose: Edit on a Your notes
                // row hides the list panel that held the pressed button, so
                // focus has dropped to <body> and nothing else restores it
                // (modal_dialog.js places focus only on a surface it has not
                // seen before).
                if (!state.isOpen || state.view !== 'new' || state.editor !== editor) return;
                const active = document.activeElement;
                const loose = !active || active === document.body || !state.surface.contains(active);
                if (loose || active === state.els.tabNew || active === state.els.closeBtn) {
                    editor.focus();
                }
            }
        });
        if (initialHtml) editor.setContent(initialHtml);
        state.editor = editor;
        return editor;
    }

    function destroyEditor() {
        if (state.editor) {
            try { state.editor.destroy(); } catch (err) { console.warn('QuickNote: editor destroy failed', err); }
            state.editor = null;
        }
        if (state.els.editorHost) state.els.editorHost.replaceChildren();
    }

    function updateComposeFooter() {
        const { footerText, secondary, primary } = state.els;
        if (state.editing) {
            footerText.textContent = 'Editing a note on its own';
            secondary.textContent = 'Cancel';
            primary.textContent = 'Save changes';
        } else if (state.entryChoice && state.where === 'entry') {
            footerText.textContent = state.chosenEntry
                ? `Saves onto entry #${state.chosenEntry.id}, ${tagPhrase(state.subjectIds)}`
                : 'Choose an entry first: Save puts the note on the entry you choose.';
            secondary.textContent = 'Cancel';
            primary.textContent = 'Save note';
        } else {
            footerText.textContent = 'Not on any entry';
            secondary.textContent = 'Cancel';
            primary.textContent = 'Save note';
        }
        refreshPrimary();
    }

    /**
     * The parts of the New note view that depend on where the note goes:
     * the intro, the where control, the chosen entry's box and the tag hint
     * (which talks about Your notes, where an entry note never appears).
     * With no `entryChoice` this leaves everything as Wave 2a drew it.
     */
    function renderWhere() {
        const { intro, tagHint, where } = state.els;
        const offered = !!state.entryChoice && !state.editing;
        const onEntry = offered && state.where === 'entry';
        where.row.hidden = !offered;
        where.own.setAttribute('aria-pressed', onEntry ? 'false' : 'true');
        where.onEntry.setAttribute('aria-pressed', onEntry ? 'true' : 'false');
        where.own.classList.toggle('qn-seg-on', !onEntry);
        where.onEntry.classList.toggle('qn-seg-on', onEntry);
        intro.textContent = !state.entryChoice ? INTRO_ENTRY_FORM
            : (onEntry ? INTRO_ON_ENTRY : INTRO_OWN);
        tagHint.hidden = onEntry;
        renderEntryBox(onEntry);
    }

    /** The chosen entry in one or two lines, with Change; or Choose an entry. */
    function renderEntryBox(show) {
        const { box, summary, choose } = state.els.where;
        box.hidden = !show;
        summary.replaceChildren();
        const e = state.chosenEntry;
        if (!e) {
            summary.appendChild(el('div', 'qn-entry-summary-empty', 'No entry chosen yet.'));
            choose.textContent = 'Choose an entry';
            return;
        }
        const headParts = [entryHeadline(e), e.session_name].filter(Boolean);
        const head = el('div', 'qn-entry-summary-head', headParts.join(' · '));
        head.dataset.testid = 'quick-note-entry-summary-head';
        const meta = el('div', 'qn-entry-summary-meta');
        meta.dataset.testid = 'quick-note-entry-summary-meta';
        const position = entryPosition(e);
        if (position) meta.appendChild(document.createTextNode(position));
        if (hasText(e.user_answer) || hasText(e.correct_answer)) {
            if (position) meta.appendChild(document.createTextNode(' · '));
            meta.append(
                document.createTextNode('You answered '),
                el('b', null, answerText(e.user_answer)),
                document.createTextNode(', correct was '),
                el('b', null, answerText(e.correct_answer)));
        }
        summary.append(head, meta);
        choose.textContent = 'Change';
    }

    function setWhere(which) {
        if (!state.entryChoice) return;
        state.where = which === 'entry' ? 'entry' : 'own';
        setStatus('');
        renderWhere();
        updateComposeFooter();
    }

    function showCompose() {
        selectTab('new');
        setStatus('');
        ensureEditor(null);
        renderChips(state.els.chips, state.subjectIds, 'quick-note-chip');
        renderWhere();
        updateComposeFooter();
    }

    /** A fresh compose: no editing state, the page's subjects, an empty editor. */
    function startNew() {
        state.editing = null;
        state.subjectIds = state.defaultSubjectIds.slice();
        state.where = 'own';
        state.chosenEntry = null;
        destroyEditor();
        showCompose();
    }

    function startEdit(note) {
        state.editing = { id: note.id, linked_subject_ids: (note.linked_subject_ids || []).slice() };
        state.subjectIds = (note.linked_subject_ids || []).slice();
        destroyEditor();
        selectTab('new');
        setStatus('');
        ensureEditor(note.content_html || '');
        renderChips(state.els.chips, state.subjectIds, 'quick-note-chip');
        renderWhere();
        updateComposeFooter();
    }

    async function showList() {
        selectTab('list');
        const { footerText, secondary, primary } = state.els;
        secondary.textContent = 'Close';
        primary.textContent = 'New note';
        footerText.textContent = '';
        refreshPrimary();
        await loadNotes();
        renderList();
    }

    // ----------------------------------------------------------- the picker

    function hasText(value) {
        return value !== null && value !== undefined && String(value).trim() !== '';
    }

    function answerText(value) {
        return hasText(value) ? String(value).trim() : 'not recorded';
    }

    function sessionFor(entry) {
        const byId = state.pick.sessionsById;
        return (byId && byId.get(entry.review_session_id)) || null;
    }

    /** `Q 2041 · UWorld`, or `Entry #5` when the entry has no question id. */
    function entryHeadline(e) {
        const parts = [hasText(e.question_id) ? `Q ${String(e.question_id).trim()}` : `Entry #${e.id}`];
        if (hasText(e.source_name)) parts.push(e.source_name);
        return parts.join(' · ');
    }

    /** `Nov 3 · Entry 7 of 20`. "of M" only when the session's count covers N. */
    function entryPosition(e) {
        const parts = [];
        const day = formatSessionDay(e.session_date);
        if (day) parts.push(day);
        const n = Number(e.entry_order);
        const m = Number(e.session_total);
        if (Number.isInteger(n) && n > 0) {
            parts.push(Number.isInteger(m) && m >= n ? `Entry ${n} of ${m}` : `Entry ${n}`);
        }
        return parts.join(' · ');
    }

    /**
     * The fields a card and the summary need, flattened once from the
     * entry and its session, so the chosen entry survives the picker's data
     * being dropped on close.
     */
    function describeEntry(entry) {
        const session = sessionFor(entry);
        const sources = state.pick.sourcesById;
        const sourceId = session ? session.question_source_id : null;
        return {
            id: entry.id,
            review_session_id: entry.review_session_id,
            question_id: entry.question_id,
            entry_order: entry.entry_order,
            user_answer: entry.user_answer,
            correct_answer: entry.correct_answer,
            reflection: entry.reflection,
            explanation: entry.explanation,
            is_draft: !!entry.is_draft,
            primary_subjects: Array.isArray(entry.primary_subjects) ? entry.primary_subjects : [],
            session_name: entry.session_name || (session && session.session_name) || '',
            session_date: entry.session_date || (session && session.date_encountered) || null,
            session_total: session ? session.total_incorrect : null,
            source_name: (sources && sourceId !== null && sourceId !== undefined)
                ? (sources.get(sourceId) || '') : ''
        };
    }

    function setPickStatus(text) {
        const s = state.els.pick && state.els.pick.status;
        if (s) s.textContent = text || '';
    }

    function renderPickerLede() {
        const { lede, widen } = state.els.pick;
        const choice = state.entryChoice || {};
        widen.checked = !!state.pick.widened;
        lede.replaceChildren();
        if (state.pick.widened) {
            lede.textContent = 'Every entry in this exam. Pick a session, then the entry.';
        } else {
            lede.append(
                document.createTextNode('Entries tagged '),
                el('b', null, choice.subjectName || 'this subject'),
                document.createTextNode('. Pick a session, then the entry.'));
        }
    }

    function enterPicker() {
        if (!state.entryChoice || state.picking || state.editing) return;
        state.picking = true;
        const { header, tabs, panelNew, footer, pick } = state.els;
        header.hidden = true;
        tabs.hidden = true;
        panelNew.hidden = true;   // the editor stays alive inside it
        footer.hidden = true;
        pick.panel.hidden = false;
        state.surface.classList.add('qn-picking');
        // The step is named by its own heading while it is shown.
        state.surface.setAttribute('aria-labelledby', pick.title.id);
        state.pick.sessionId = state.chosenEntry ? state.chosenEntry.review_session_id : null;
        renderPickerLede();
        if (state.pick.loaded) renderPicker();
        else loadPicker();
        pick.back.focus();
    }

    /** Back to the note, the editor and its content exactly as they were. */
    function exitPicker(options) {
        if (!state.picking) return;
        state.picking = false;
        const { header, tabs, panelNew, footer, pick } = state.els;
        pick.panel.hidden = true;
        header.hidden = false;
        tabs.hidden = false;
        panelNew.hidden = false;
        footer.hidden = false;
        state.surface.classList.remove('qn-picking');
        state.surface.setAttribute('aria-labelledby', 'quick-note-title');
        if (options && options.quiet) return;
        renderWhere();
        updateComposeFooter();
        state.els.where.choose.focus();
    }

    async function loadPicker() {
        const choice = state.entryChoice;
        if (!choice) return;
        const pick = state.pick;
        const token = ++pick.token;
        pick.loading = true;
        pick.error = null;
        pick.entries = [];
        state.els.pick.sessions.replaceChildren();
        state.els.pick.cards.replaceChildren();
        setPickStatus('Loading entries…');
        try {
            if (!pick.sessionsById) {
                const results = await Promise.all([
                    bridge().getReviewSessions(choice.examContextId, true).catch(() => []),
                    bridge().getQuestionSources('').catch(() => [])
                ]);
                if (token !== pick.token) return;
                const sessions = Array.isArray(results[0]) ? results[0] : [];
                const sources = Array.isArray(results[1]) ? results[1] : [];
                pick.sessionsById = new Map(sessions.map((s) => [s.id, s]));
                pick.sourcesById = new Map(sources.map((s) => [s.id, s.source_name]));
            }
            const read = await fetchCandidates(choice, pick.widened, token);
            if (token !== pick.token) return;
            pick.entries = read.entries.map(describeEntry);
            pick.total = read.total;
            pick.truncated = read.entries.length < read.total;
            pick.loaded = true;
        } catch (err) {
            if (token !== pick.token) return;
            console.error('QuickNote: loading the entries failed', err);
            pick.entries = [];
            pick.error = err && err.message ? err.message : String(err);
        }
        pick.loading = false;
        renderPicker();
    }

    /**
     * Every candidate, a page at a time. The subject branch is the entry
     * browser's own subject filter (#13): `subject_ids` plus
     * `include_child_subjects`, which `get_entries_paginated` scopes through
     * `_subject_filter_scope_sql` -- tagged directly in any parent context,
     * or on a descendant routing through the subject, primary or secondary
     * tag alike. Widened, the subject filter goes and the exam stays.
     */
    async function fetchCandidates(choice, widened, token) {
        const out = [];
        let total = 0;
        for (let page = 1; page <= PICK_MAX_PAGES; page++) {
            const params = {
                exam_context_id: choice.examContextId,
                sort_by: 'date_desc',
                page: page,
                per_page: PICK_PAGE
            };
            if (!widened) {
                params.subject_ids = [choice.subjectId];
                params.include_child_subjects = true;
            }
            const res = await bridge().getEntriesPaginated(params);
            if (token !== state.pick.token) break;
            const rows = res && Array.isArray(res.entries) ? res.entries : [];
            total = res && typeof res.total === 'number' ? res.total : out.length + rows.length;
            out.push(...rows);
            if (rows.length < PICK_PAGE || out.length >= total) break;
        }
        return { entries: out, total: Math.max(total, out.length) };
    }

    /** Sessions newest first, each with the count of candidates it holds. */
    function pickSessions() {
        const groups = new Map();
        for (const e of state.pick.entries) {
            let g = groups.get(e.review_session_id);
            if (!g) {
                g = { id: e.review_session_id, name: e.session_name, date: e.session_date, count: 0 };
                groups.set(e.review_session_id, g);
            }
            g.count += 1;
        }
        return [...groups.values()].sort((a, b) => {
            const da = String(a.date || '');
            const db = String(b.date || '');
            if (da !== db) return da < db ? 1 : -1;
            return (b.id || 0) - (a.id || 0);
        });
    }

    function renderPicker() {
        renderPickerSessions();
        renderPickerEntries();
    }

    function sessionButton(id, name, meta, testid) {
        const b = button('qn-sess', null, testid);
        b.dataset.sessionId = id === null ? '' : String(id);
        b.append(el('span', 'qn-sess-name', name), el('span', 'qn-sess-meta', meta));
        b.addEventListener('click', () => selectSession(id));
        return b;
    }

    function renderPickerSessions() {
        const list = state.els.pick.sessions;
        list.replaceChildren();
        if (state.pick.loading || state.pick.error) return;
        const n = state.pick.entries.length;
        list.appendChild(sessionButton(null, 'All sessions', plural(n, 'entry', 'entries'),
            'quick-note-picker-session-all'));
        for (const g of pickSessions()) {
            const day = formatSessionDay(g.date);
            const meta = [day, plural(g.count, 'entry', 'entries')].filter(Boolean).join(' · ');
            list.appendChild(sessionButton(g.id, g.name || `Session #${g.id}`, meta,
                `quick-note-picker-session-${g.id}`));
        }
        markSelectedSession();
    }

    function markSelectedSession() {
        const wanted = state.pick.sessionId === null ? '' : String(state.pick.sessionId);
        for (const b of state.els.pick.sessions.querySelectorAll('.qn-sess')) {
            const on = b.dataset.sessionId === wanted;
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
            b.classList.toggle('qn-sess-on', on);
        }
    }

    function selectSession(id) {
        // A session the current set does not hold (the chosen entry's, after
        // the subject filter came back on) reads as All sessions.
        const held = id === null || state.pick.entries.some((e) => e.review_session_id === id);
        state.pick.sessionId = held ? id : null;
        markSelectedSession();
        renderPickerEntries();
    }

    function matchesQuery(e, q) {
        if (!q) return true;
        const hay = [
            e.question_id, e.user_answer, e.correct_answer, e.session_name, e.source_name,
            previewText(e.reflection), previewText(e.explanation)
        ].filter(hasText).join('\n').toLowerCase();
        return hay.includes(q);
    }

    function renderPickerEntries() {
        const pick = state.pick;
        const cards = state.els.pick.cards;
        cards.replaceChildren();
        if (pick.loading) { setPickStatus('Loading entries…'); return; }
        if (pick.error) { setPickStatus('Could not load the entries: ' + pick.error); return; }
        if (pick.entries.length === 0) {
            setPickStatus(pick.widened
                ? 'There are no entries in this exam yet.'
                : 'No entries are tagged with this subject yet. Tick Show every entry in this exam to choose from all of them.');
            return;
        }
        // The session filter re-checks itself against the set it is applied
        // to, so a widen or narrow cannot leave a stale session selected.
        if (pick.sessionId !== null && !pick.entries.some((e) => e.review_session_id === pick.sessionId)) {
            pick.sessionId = null;
            markSelectedSession();
        }
        const q = String(pick.query || '').trim().toLowerCase();
        // Newest session first, as the column reads; inside a session, in the
        // order the entries were logged.
        const rank = new Map(pickSessions().map((g, i) => [g.id, i]));
        const shown = pick.entries
            .filter((e) => pick.sessionId === null || e.review_session_id === pick.sessionId)
            .filter((e) => matchesQuery(e, q))
            .sort((a, b) => {
                const ra = rank.get(a.review_session_id) || 0;
                const rb = rank.get(b.review_session_id) || 0;
                if (ra !== rb) return ra - rb;
                return (Number(a.entry_order) || 0) - (Number(b.entry_order) || 0);
            });
        if (shown.length === 0) {
            setPickStatus(q ? `No entry here matches "${pick.query.trim()}".` : 'No entries in this session.');
            return;
        }
        const drawn = shown.slice(0, PICK_CARD_LIMIT);
        for (const e of drawn) cards.appendChild(buildEntryCard(e));
        let text = shown.length > drawn.length
            ? `Showing the first ${drawn.length} of ${shown.length} entries. Pick a session or search to narrow them.`
            : plural(shown.length, 'entry', 'entries');
        if (pick.truncated) {
            text += ` Only the newest ${pick.entries.length} of ${pick.total} could be read.`;
        }
        setPickStatus(text);
    }

    function cardSection(label, html, testid) {
        const sec = el('div', 'qn-card-sec');
        const text = previewText(html);
        const body = el('span', text ? 'qn-card-sec-text' : 'qn-card-sec-text qn-card-sec-empty',
            text || 'Not written yet.');
        body.dataset.testid = testid;
        sec.append(el('span', 'qn-card-sec-label', label), body);
        return sec;
    }

    function buildEntryCard(e) {
        const chosen = !!state.chosenEntry && state.chosenEntry.id === e.id;
        const card = el('div', chosen ? 'qn-card qn-card-on' : 'qn-card');
        const tid = `quick-note-entry-card-${e.id}`;
        card.dataset.testid = tid;
        card.dataset.entryId = String(e.id);

        const head = el('div', 'qn-card-head');
        const ident = el('div', 'qn-card-ident');
        const headline = el('span', 'qn-card-id', entryHeadline(e));
        headline.id = `${tid}-id`;
        headline.dataset.testid = `${tid}-id`;
        ident.append(headline, el('span', 'qn-card-meta', entryPosition(e)));
        if (e.is_draft) {
            const draft = el('span', 'qn-tag qn-tag-draft', 'Draft');
            draft.dataset.testid = `${tid}-draft`;
            ident.appendChild(draft);
        }
        const side = el('div', 'qn-card-side');
        const chips = el('span', 'qn-chips');
        for (const s of e.primary_subjects) {
            if (s && hasText(s.name)) chips.appendChild(el('span', 'qn-chip', s.name));
        }
        const use = button(chosen ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm',
            'Use this entry', `${tid}-use`);
        // Every card's button reads the same, so each is described by the
        // card's own headline.
        use.setAttribute('aria-describedby', headline.id);
        use.addEventListener('click', () => chooseEntry(e));
        side.append(chips, use);
        head.append(ident, side);

        const answers = el('div', 'qn-card-answers');
        const wrong = el('div', 'qn-card-ans qn-card-ans-wrong');
        wrong.append(el('span', 'qn-card-ans-label', 'You answered'),
            el('span', 'qn-card-ans-text', answerText(e.user_answer)));
        wrong.lastChild.dataset.testid = `${tid}-user-answer`;
        const right = el('div', 'qn-card-ans qn-card-ans-right');
        right.append(el('span', 'qn-card-ans-label', 'Correct answer'),
            el('span', 'qn-card-ans-text', answerText(e.correct_answer)));
        right.lastChild.dataset.testid = `${tid}-correct-answer`;
        answers.append(wrong, right);

        card.append(head, answers,
            cardSection('Why did you get this wrong?', e.reflection, `${tid}-reflection`),
            cardSection('Why is the correct answer correct?', e.explanation, `${tid}-explanation`));
        return card;
    }

    function chooseEntry(entry) {
        state.chosenEntry = entry;
        state.where = 'entry';
        exitPicker();
    }

    async function loadNotes() {
        try {
            // One past the page: a full answer means the list goes on.
            const notes = await bridge().listFreeNotes(state.limit + 1);
            const all = Array.isArray(notes) ? notes : [];
            state.hasMore = all.length > state.limit;
            state.notes = all.slice(0, state.limit);
        } catch (err) {
            console.error('QuickNote: listFreeNotes failed', err);
            state.notes = [];
            state.hasMore = false;
        }
        const n = state.notes.length;
        // A count the dialog cannot vouch for says so: "50+" is honest where
        // "50" would state the page size as the total.
        state.els.count.textContent = state.hasMore ? `${n}+` : String(n);
        state.els.count.hidden = false;
    }

    function renderList() {
        const { list, empty, more, footerText } = state.els;
        list.replaceChildren();
        const n = state.notes.length;
        empty.hidden = n > 0;
        footerText.textContent = state.hasMore
            ? `Showing the newest ${n} notes on their own`
            : `${n} note${n === 1 ? '' : 's'} on their own`;
        more.hidden = !state.hasMore;
        for (const note of state.notes) list.appendChild(buildRow(note));
    }

    /** The next page of Your notes, drawn under the rows already shown. */
    async function showMore() {
        if (!state.hasMore) return;
        const { more } = state.els;
        more.disabled = true;
        const shown = state.notes.length;
        state.limit += LIST_PAGE;
        try {
            await loadNotes();
            renderList();
        } finally {
            more.disabled = false;
        }
        // Keep the student's place: the first newly drawn row, or the button
        // again when the list is now complete and Show more has gone.
        const rows = state.els.list.children;
        const landing = rows[shown] && rows[shown].querySelector('.qn-row-actions button');
        if (landing) landing.focus();
        else if (!more.hidden) more.focus();
        else state.els.panelList.focus();
    }

    function buildRow(note) {
        const row = el('div', 'qn-row');
        row.dataset.noteId = String(note.id);
        row.dataset.testid = `quick-note-row-${note.id}`;

        const dateEl = el('span', 'qn-row-date', formatDay(note.updated_at || note.created_at));

        const body = el('div', 'qn-row-body');
        const text = el('div', 'qn-row-text', previewText(note.content_html) || '(empty note)');
        text.dataset.testid = `quick-note-row-${note.id}-text`;
        const meta = el('div', 'qn-row-meta');
        const chips = el('span', 'qn-row-chips');
        renderChips(chips, note.linked_subject_ids || [], null);
        const count = typeof note.attachment_count === 'number' ? note.attachment_count : 0;
        const where = el('span', 'qn-row-where',
            count === 0 ? 'Not on any entry' : `On ${count} entr${count === 1 ? 'y' : 'ies'}`);
        where.dataset.testid = `quick-note-row-${note.id}-where`;
        meta.append(chips, el('span', 'qn-dot', '·'), where);
        body.append(text, meta);
        body.addEventListener('click', () => startEdit(note));

        const actions = el('div', 'qn-row-actions');
        const editBtn = button('btn btn-text', 'Edit', `quick-note-row-${note.id}-edit`);
        editBtn.addEventListener('click', () => startEdit(note));
        const deleteBtn = button('btn btn-text btn-danger-text', 'Delete', `quick-note-row-${note.id}-delete`);
        deleteBtn.addEventListener('click', () => askDelete(row, note, count, deleteBtn));
        actions.append(editBtn, deleteBtn);

        row.append(dateEl, body, actions);
        return row;
    }

    /**
     * The question before a delete, inline in the row, naming the cost.
     *
     * Focus matters here in three places, each measured on this engine. The
     * box lands focus on CANCEL, never on its Delete: a <button> activates on
     * keydown and Enter auto-repeats, so with focus on Delete the repeat
     * that follows the press that opened the box would delete the note
     * before "There is no undo" was ever read (modal_dialog.js records the
     * same key-repeat reaching 2-3 activations per run). Cancel removes the
     * element holding focus, so it hands focus back to the row's Delete
     * button that opened it. A confirmed delete redraws every row, so it
     * lands on the row now in the deleted one's place, or on the panel when
     * none is left -- otherwise document.activeElement is <body> and a
     * keyboard student has lost their place in the list.
     */
    function askDelete(row, note, count, trigger) {
        const existing = row.querySelector('.qn-row-confirm');
        if (existing) return;
        const confirmBox = el('div', 'qn-row-confirm');
        confirmBox.setAttribute('role', 'group');
        confirmBox.dataset.testid = `quick-note-row-${note.id}-confirm`;
        const msg = el('span', 'qn-row-confirm-text',
            count > 0
                ? `This note is on ${count} entr${count === 1 ? 'y' : 'ies'}; deleting removes it from all of them. There is no undo.`
                : 'Delete this note? There is no undo.');
        // The question names the group and describes both buttons, so a
        // screen reader landing on Cancel hears what it is cancelling and
        // what Delete costs (PR #864 round 3). Focus skips static text.
        const msgId = `quick-note-row-${note.id}-confirm-text`;
        msg.id = msgId;
        confirmBox.setAttribute('aria-labelledby', msgId);
        const yes = button('btn btn-sm btn-danger', 'Delete', `quick-note-row-${note.id}-confirm-delete`);
        const no = button('btn btn-sm btn-secondary', 'Cancel', `quick-note-row-${note.id}-cancel-delete`);
        yes.setAttribute('aria-describedby', msgId);
        no.setAttribute('aria-describedby', msgId);
        no.addEventListener('click', () => {
            confirmBox.remove();
            if (trigger && document.contains(trigger)) trigger.focus();
        });
        yes.addEventListener('click', async () => {
            yes.disabled = true;
            try {
                await bridge().deleteEntryNote(note.id);
            } catch (err) {
                console.error('QuickNote: deleteEntryNote failed', err);
                msg.textContent = 'Could not delete the note: ' + (err && err.message ? err.message : String(err));
                yes.disabled = false;
                return;
            }
            notify('Deleted', 'Note deleted.', 'success');
            if (typeof state.options.onDeleted === 'function') {
                try { state.options.onDeleted(note.id); } catch (err) { console.warn('QuickNote onDeleted failed', err); }
            }
            const index = Array.prototype.indexOf.call(state.els.list.children, row);
            await loadNotes();
            renderList();
            focusRowAt(index);
        });
        confirmBox.append(msg, yes, no);
        row.appendChild(confirmBox);
        no.focus();
    }

    /** Focus the Edit button of the row at `index` (clamped), or the panel when the list is empty. */
    function focusRowAt(index) {
        const rows = state.els.list.children;
        if (rows.length === 0) { state.els.panelList.focus(); return; }
        const at = Math.min(Math.max(index, 0), rows.length - 1);
        const target = rows[at].querySelector('.qn-row-actions button');
        if (target) target.focus();
        else state.els.panelList.focus();
    }

    // --------------------------------------------------------------- actions

    async function onChooseSubjects() {
        const choose = state.options.chooseSubjects;
        if (typeof choose !== 'function') return;
        let ids;
        try {
            ids = await choose(state.subjectIds.slice());
        } catch (err) {
            console.error('QuickNote: chooseSubjects failed', err);
            return;
        }
        if (ids === null || ids === undefined) return;
        state.subjectIds = cleanIds(ids);
        renderChips(state.els.chips, state.subjectIds, 'quick-note-chip');
        // The On-an-entry footer names the tags the note will carry.
        if (state.isOpen && state.view === 'new') updateComposeFooter();
    }

    function onSecondary() {
        if (state.view === 'list') { close(); return; }
        if (state.editing && state.editReturn === 'close') { close(); return; }
        if (state.editing) {
            // Back to the list without saving. The next New note starts
            // from the page's subjects again, whichever way it is reached:
            // the New note tab calls showCompose(), which draws the chips
            // from whatever state.subjectIds holds (#848 decision 5).
            state.editing = null;
            state.subjectIds = state.defaultSubjectIds.slice();
            destroyEditor();
            showList();
            return;
        }
        close();
    }

    function onPrimary() {
        if (state.view === 'list') { startNew(); return; }
        save();
    }

    async function save() {
        if (state.busy) return;
        const editor = state.editor;
        if (!editor || editor.isEmpty()) {
            setStatus('Write something first. A blank note is not saved.');
            return;
        }
        if (needsEntry()) {
            // Save is disabled here; this is the belt to its braces.
            setStatus('Choose an entry first. Save puts the note on the entry you choose.');
            return;
        }
        const onEntry = (state.entryChoice && !state.editing && state.where === 'entry')
            ? state.chosenEntry : null;
        const content = editor.getContent() || {};
        const html = content.html || '';
        const ids = state.subjectIds.slice();
        setBusy(true);
        setStatus('');
        try {
            if (state.editing) {
                const id = state.editing.id;
                await bridge().updateEntryNote(id, { content_html: html, content_json: null });
                if (!sameIds(state.editing.linked_subject_ids, ids)) {
                    await bridge().updateNoteLinkedSubjects(id, ids);
                }
                const saved = { id: id, content_html: html, linked_subject_ids: ids };
                notify('Note updated', 'Your changes are saved.', 'success');
                if (typeof state.options.onSaved === 'function') state.options.onSaved(saved);
                if (state.editReturn === 'close') {
                    close();
                    return;
                }
                state.editing = null;
                // As Cancel does: the next New note is pre-tagged again.
                state.subjectIds = state.defaultSubjectIds.slice();
                destroyEditor();
                await showList();
            } else if (onEntry) {
                // An ORDINARY entry note, through the path the note cards use
                // (decision 5): origin set to the entry, its junction row
                // written by add_entry_note, tagged as the dialog says.
                const note = await bridge().addEntryNote(onEntry.id, {
                    content_html: html,
                    content_json: null,
                    linked_subject_ids: ids
                });
                notify('Saved onto the entry',
                    `The note is on entry #${onEntry.id}${onEntry.session_name ? ', in ' + onEntry.session_name : ''}.`,
                    'success');
                if (typeof state.options.onSaved === 'function') state.options.onSaved(note || null);
                close();
            } else {
                const note = await bridge().addNote({
                    content_html: html,
                    content_json: null,
                    linked_subject_ids: ids
                });
                notify('Saved as a note on its own', 'Find it under Your notes in Quick note.', 'success');
                if (typeof state.options.onSaved === 'function') state.options.onSaved(note || null);
                close();
            }
        } catch (err) {
            console.error('QuickNote: save failed', err);
            setStatus('Could not save the note: ' + (err && err.message ? err.message : String(err)));
        } finally {
            setBusy(false);
        }
    }

    function onDocumentKeydown(e) {
        if (!state.isOpen || e.key !== 'Escape' || e.defaultPrevented) return;
        // Only when this dialog is the topmost one: the subject chooser opens
        // over it and owns its own closing.
        if (window.ModalDialog && window.ModalDialog.topmost() !== state.surface) return;
        e.preventDefault();
        // In the picker step Escape is Back: closing from there would throw
        // away a note the student has not saved and cannot see.
        if (state.picking) { exitPicker(); return; }
        close();
    }

    /** Escape pressed inside the dialog's own editor, re-emitted by rich_editor.js. */
    function onEditorShortcut(e) {
        const d = e.detail || {};
        if (!state.isOpen || d.key !== 'Escape') return;
        if (!state.editor || !state.els.editorHost.contains(document.activeElement)) return;
        if (window.ModalDialog && window.ModalDialog.topmost() !== state.surface) return;
        e.preventDefault();
        close();
    }

    // ----------------------------------------------------------------- public

    function open(options) {
        if (state.isOpen) return;
        state.options = options || {};
        build(state.options.mount);
        state.invoker = document.activeElement;
        state.editing = null;
        state.defaultSubjectIds = cleanIds(state.options.subjectIds);
        state.subjectIds = state.defaultSubjectIds.slice();
        state.entryChoice = validEntryChoice(state.options.entryChoice);
        state.where = 'own';
        state.chosenEntry = null;
        state.editReturn = 'list';
        state.picking = false;
        state.pick = freshPick();
        state.notes = [];
        state.limit = LIST_PAGE;
        state.hasMore = false;
        state.els.count.hidden = true;
        state.els.pick.search.value = '';
        state.isOpen = true;
        state.backdrop.classList.add('active');
        document.body.style.overflow = 'hidden';
        document.addEventListener('keydown', onDocumentKeydown);
        document.addEventListener('wimi:editor-shortcut', onEditorShortcut);
        // The count on the Your notes tab is live from the first paint.
        loadNotes().catch(() => {});
        const edit = state.options.edit;
        if (edit && edit.id !== undefined && edit.id !== null) {
            // Opened on one note, from a list on the page: the same state
            // Your notes' Edit sets, but Save and Cancel close the dialog.
            state.editReturn = 'close';
            startEdit(edit);
        } else if (state.options.view === 'list') showList();
        else showCompose();
    }

    /** `entryChoice` is honoured only when it names an exam and a subject. */
    function validEntryChoice(choice) {
        if (!choice || typeof choice !== 'object') return null;
        const examContextId = Number(choice.examContextId);
        const subjectId = Number(choice.subjectId);
        if (!Number.isInteger(examContextId) || !Number.isInteger(subjectId)) return null;
        return {
            examContextId: examContextId,
            subjectId: subjectId,
            subjectName: hasText(choice.subjectName) ? String(choice.subjectName) : ''
        };
    }

    function close() {
        if (!state.isOpen) return;
        state.isOpen = false;
        document.removeEventListener('keydown', onDocumentKeydown);
        document.removeEventListener('wimi:editor-shortcut', onEditorShortcut);
        // A picker load still in flight must not draw into the next open.
        state.pick.token += 1;
        exitPicker({ quiet: true });
        destroyEditor();
        state.editing = null;
        state.subjectIds = [];
        state.chosenEntry = null;
        state.entryChoice = null;
        state.where = 'own';
        setStatus('');
        state.els.list.replaceChildren();
        state.backdrop.classList.remove('active');
        document.body.style.overflow = '';
        // Focus goes back to whatever opened the dialog when it is loose --
        // still inside the dialog, or dropped to <body> with the editor.
        const invoker = state.invoker;
        state.invoker = null;
        const active = document.activeElement;
        const loose = !active || active === document.body || state.surface.contains(active);
        if (loose && invoker && document.contains(invoker) && typeof invoker.focus === 'function') {
            try { invoker.focus(); } catch (err) { /* nothing to restore to */ }
        }
    }

    window.QuickNote = {
        open: open,
        close: close,
        isOpen: function () { return state.isOpen; },
        editor: function () { return state.editor; },
        // For scenarios (#848 Wave 2b): is the entry step showing.
        isPicking: function () { return state.isOpen && state.picking; }
    };
})();
