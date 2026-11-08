/**
 * first_axis_dialog.js -- "Move your existing subjects into an axis?" (#605)
 *
 * When an exam that already has subjects gets its first axis, every one of
 * those subjects is left in no axis, and once an exam has an axis the tree
 * editor draws one axis at a time -- so the student's whole tree vanishes.
 * The owner's decision (2026-10-09) is to ask each time, defaulting to moving
 * them in; the batch of 2026-11-07 settled the rest (#605 comments 12206 and
 * 12211). This module is the question, shared by the two places an exam can
 * get its first axis: the exam wizard's edit mode (Wave 1) and the tree
 * editor's whole-exam import (Wave 2).
 *
 *   FirstAxisDialog.ask({subjects, subjectCount, axes, context})
 *     -> Promise resolving to
 *        {action: 'move', assignments: [{subject_id, axis}]}
 *        {action: 'aside'}
 *        null                        Go back: nothing is saved
 *
 * `subjects` is the preview read's `roots` (or null when that read failed:
 * the question is still asked, #486's rule, and every subject takes the
 * default). `axes` is `[{index, name}]` in final order; `axis` in an
 * assignment is that `index`. The default is the first axis.
 *
 * What the owner decided, and where it lives here:
 *  - several new axes: an axis select on each top-level row (decision 1),
 *    hidden when only one axis is new, because a choice of one is not a
 *    choice;
 *  - Escape and a backdrop click are Go back (decision 3). This module
 *    handles Escape itself: modal_dialog.js deliberately does not;
 *  - at most 6 rows, then "Show {r} more" with aria-expanded (decision 4).
 *    Hidden rows still submit their default, so collapsing never drops one;
 *  - rows sharing a descendant are linked and change together (decision 6),
 *    because splitting them would put the shared subject in one axis under a
 *    parent in another. The server refuses a split anyway;
 *  - Keep them aside applies to every subject (decision 9).
 *
 * Built from text nodes only: a subject name is text a student typed or a
 * profile import carried as written (#594, #548). The dialog semantics are
 * on the SURFACE, never the backdrop (#319), and modal_dialog.js draws the
 * aria-hidden boundary and the Tab trap.
 */
(function () {
    'use strict';

    const VISIBLE_ROWS = 6;
    let sequence = 0;

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function button(className, text, testid) {
        const b = el('button', className, text);
        b.type = 'button';
        if (testid) b.setAttribute('data-testid', testid);
        return b;
    }

    // The tree editor panel's own wording (tree_editor.js, "Subjects not in
    // any axis"), so a subject reads the same in the question and in the place
    // it lands after Keep them aside.
    function countWording(subtreeCount) {
        return subtreeCount > 1 ? `with ${subtreeCount - 1} underneath` : 'on its own';
    }

    function listOfNames(names) {
        if (names.length <= 1) return names.join('');
        return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
    }

    function introText(count) {
        const tail = ' Once an exam has axes, the tree editor shows one axis at a '
            + 'time, so subjects outside every axis are not drawn there.';
        if (count === null) {
            return 'This exam already has subjects, and none of them is in an '
                + 'axis yet.' + tail;
        }
        if (count === 1) {
            return 'This exam already has 1 subject, and it is not in an axis '
                + 'yet.' + tail;
        }
        return `This exam already has ${count} subjects, and none of them is in `
            + 'an axis yet.' + tail;
    }

    function ask(options) {
        const opts = options || {};
        const axes = (Array.isArray(opts.axes) ? opts.axes : [])
            .filter(a => a && a.name !== undefined && a.index !== undefined);
        if (!axes.length) return Promise.resolve(null);
        const subjects = Array.isArray(opts.subjects) ? opts.subjects : null;
        // Never derived from the rows: summing subtree sizes counts a shared
        // subject twice, so an unknown count says "subjects" instead.
        const count = Number.isInteger(opts.subjectCount) ? opts.subjectCount : null;
        const isImport = opts.context === 'import';
        return new Promise(resolve => open(subjects, count, axes, isImport, resolve));
    }

    function open(subjects, count, axes, isImport, resolve) {
        const id = ++sequence;
        const axisName = new Map(axes.map(a => [a.index, String(a.name)]));
        const several = axes.length > 1;

        const backdrop = document.createElement('div');
        backdrop.className = 'first-axis-backdrop';
        backdrop.id = `first-axis-modal-${id}`;
        backdrop.setAttribute('data-testid', 'first-axis-backdrop');

        const surface = el('div', 'first-axis-dialog');
        surface.setAttribute('data-modal-surface', '');
        surface.setAttribute('role', 'dialog');
        surface.setAttribute('aria-modal', 'true');
        surface.setAttribute('aria-labelledby', `first-axis-title-${id}`);
        surface.setAttribute('data-testid', 'first-axis-dialog');

        // The surface is a column: a body that scrolls, and the answers in a
        // footer that does not (#922). With the buttons inside the scroller,
        // focusing the primary button on open scrolled the title and the
        // question out of view -- measured at innerHeight 739 with eight
        // subjects: scrollTop 200, the title's top at -131 px. In a footer
        // the focused button is always on screen and never moves the body.
        const body = el('div', 'first-axis-body');
        surface.appendChild(body);

        const title = el('h2', 'first-axis-title',
            'Move your existing subjects into an axis?');
        title.id = `first-axis-title-${id}`;
        body.appendChild(title);
        body.appendChild(el('p', 'first-axis-text', introText(count)));
        body.appendChild(el('p', 'first-axis-text',
            'If you keep them aside, nothing about them changes. The tree editor '
            + 'lists them under Subjects not in any axis, where you can move each '
            + 'one in later.'));
        if (isImport) {
            body.appendChild(el('p', 'first-axis-text',
                'The import itself never changes these subjects. Moving them is a '
                + 'separate step that happens only if you choose it.'));
        }

        // ---- one row per top-level subject ---------------------------------
        const rows = [];
        const byGroup = new Map();
        (subjects || []).forEach(subject => {
            const clashes = new Set(subject.import_id_clash_axes || []);
            const allowed = axes.filter(a => !clashes.has(a.index));
            rows.push({
                subject,
                allowed,
                axis: allowed.length ? allowed[0].index : null,
                select: null,
            });
            const group = subject.group === undefined ? subject.subject_id : subject.group;
            if (!byGroup.has(group)) byGroup.set(group, []);
            byGroup.get(group).push(rows[rows.length - 1]);
        });

        const primary = button('btn btn-primary', '', 'first-axis-move');

        function refreshPrimary() {
            const chosen = new Set(rows.filter(r => r.axis !== null).map(r => r.axis));
            const only = rows.length ? (chosen.size === 1 ? [...chosen][0] : null)
                : axes[0].index;
            primary.textContent = only !== null
                ? `Move them into ${axisName.get(only)}`
                : 'Move them';
        }

        function buildRow(row) {
            const li = el('li', 'first-axis-row');
            li.setAttribute('data-testid', 'first-axis-row');
            li.setAttribute('data-subject-id', String(row.subject.subject_id));
            li.appendChild(el('span', 'first-axis-row-name', row.subject.name));
            li.appendChild(el('span', 'first-axis-row-meta',
                countWording(row.subject.subtree_count || 1)));

            const select = el('select', 'first-axis-row-select');
            select.setAttribute('data-testid', 'first-axis-select');
            select.setAttribute('aria-label', `Axis for ${row.subject.name}`);
            axes.forEach(a => {
                const option = el('option', null, String(a.name));
                option.value = String(a.index);
                option.disabled = !row.allowed.includes(a);
                select.appendChild(option);
            });
            if (row.axis !== null) select.value = String(row.axis);
            select.disabled = row.axis === null;
            select.hidden = !several;
            select.addEventListener('change', () => {
                const value = axes.find(a => String(a.index) === select.value);
                if (!value) return;
                const group = row.subject.group === undefined
                    ? row.subject.subject_id : row.subject.group;
                (byGroup.get(group) || [row]).forEach(member => {
                    if (member.axis === null) return;
                    member.axis = value.index;
                    if (member.select) member.select.value = select.value;
                });
                refreshPrimary();
            });
            row.select = select;
            li.appendChild(select);

            const group = row.subject.group === undefined
                ? row.subject.subject_id : row.subject.group;
            const others = (byGroup.get(group) || []).filter(m => m !== row)
                .map(m => m.subject.name);
            if (others.length) {
                li.appendChild(el('p', 'first-axis-row-note',
                    `Shares subjects with ${listOfNames(others)}, so they go into `
                    + 'the same axis.'));
            }
            if (isImport) {
                if (row.axis === null) {
                    li.appendChild(el('p', 'first-axis-row-note',
                        'The file already contains this subject, so it stays '
                        + 'outside the axes.'));
                }
                (row.subject.name_clash_axes || []).forEach(index => {
                    if (!axisName.has(index)) return;
                    li.appendChild(el('p', 'first-axis-row-note',
                        `The file also has a subject called ${row.subject.name} `
                        + `in ${axisName.get(index)}.`));
                });
            }
            return li;
        }

        if (rows.length) {
            const list = el('div', 'first-axis-list');
            const shown = el('ul', 'first-axis-rows');
            rows.slice(0, VISIBLE_ROWS).forEach(r => shown.appendChild(buildRow(r)));
            list.appendChild(shown);
            body.appendChild(list);

            const rest = rows.slice(VISIBLE_ROWS);
            if (rest.length) {
                const more = el('ul', 'first-axis-more-rows');
                more.id = `first-axis-more-rows-${id}`;
                more.hidden = true;
                rest.forEach(r => more.appendChild(buildRow(r)));
                list.appendChild(more);

                const label = `Show ${rest.length} more`;
                const toggle = button('btn btn-text-only first-axis-more', label,
                    'first-axis-more-toggle');
                toggle.setAttribute('aria-expanded', 'false');
                toggle.setAttribute('aria-controls', more.id);
                toggle.addEventListener('click', () => {
                    const expand = more.hidden;
                    more.hidden = !expand;
                    toggle.setAttribute('aria-expanded', expand ? 'true' : 'false');
                    toggle.textContent = expand ? 'Show fewer' : label;
                });
                body.appendChild(toggle);
            }
        }

        // ---- the three answers ---------------------------------------------
        const actions = el('div', 'first-axis-actions');
        const back = button('btn btn-secondary', 'Go back', 'first-axis-back');
        const aside = button('btn btn-secondary', 'Keep them aside', 'first-axis-aside');
        actions.append(back, aside, primary);
        surface.appendChild(actions);
        refreshPrimary();

        let settled = false;
        function finish(answer) {
            if (settled) return;
            settled = true;
            document.removeEventListener('keydown', onKeydown, true);
            backdrop.remove();
            resolve(answer);
        }

        function onKeydown(event) {
            if (event.key !== 'Escape') return;
            // Only the topmost dialog answers Escape; a dialog opened over
            // this one keeps it. modal_dialog.js owns "which is topmost", so
            // the two cannot disagree; without it, this dialog answers.
            const top = window.ModalDialog && window.ModalDialog.topmost
                ? window.ModalDialog.topmost() : null;
            if (top && top !== surface) return;
            event.preventDefault();
            event.stopPropagation();
            finish(null);
        }

        back.addEventListener('click', () => finish(null));
        aside.addEventListener('click', () => finish({ action: 'aside' }));
        primary.addEventListener('click', () => finish({
            action: 'move',
            assignments: rows
                .filter(r => r.axis !== null || isImport)
                .map(r => ({ subject_id: r.subject.subject_id, axis: r.axis })),
        }));
        backdrop.addEventListener('click', event => {
            if (event.target === backdrop) finish(null);
        });
        document.addEventListener('keydown', onKeydown, true);

        backdrop.appendChild(surface);
        document.body.appendChild(backdrop);
        // preventScroll as well as the footer: the button is outside the
        // scrolling body, so focusing it has nothing to scroll today, and
        // this keeps a later move of the button back inside the body from
        // silently bringing #922 back.
        primary.focus({ preventScroll: true });
    }

    window.FirstAxisDialog = { ask, countWording };
})();
