/**
 * The second channel for #301's caveat.
 *
 * `_build_subject_path` filters archived ancestors (#301, matching the
 * #262-fixed `get_paths_to_root`), so a subject whose parent has been
 * archived renders a SHORTER path than it used to. The owner's decision
 * (2026-10-03) was neither of the two options the issue offered: filter
 * **and** explain. Option 1's stated cost was that a shortened path "can
 * look wrong without explaining why"; this is the explanation.
 *
 * One rule for the path, a second channel for the caveat — the archived
 * name stays out of the primary reading line, which is what #15's soft
 * delete was getting away from.
 *
 * Three things are load-bearing:
 *
 * 1. **It appears only where a path was actually shortened.** `create()`
 *    returns `null` for an empty or missing list, and every backend payload
 *    carrying this sends `null`/omits the key rather than `[]` for exactly
 *    that reason. An affordance that always appears means nothing.
 *
 * 2. **It is not a bare `title=`.** `title` never appears on keyboard
 *    focus, is unreliable for assistive tech and cannot be styled. This
 *    copies the shape WIMI already uses three times — `.sunburst-info-icon`
 *    (#6), `.efficiency-info-icon` (#133), `.search-help-icon` — a
 *    `tabindex="0"` host with an `aria-label` carrying the same sentence as
 *    the visible tooltip, which opens on `:hover` AND `:focus`. #319's
 *    shared pattern is for modal **dialogs** (role, aria-modal, focus
 *    trapping) and is not this; adopting it here would be the wrong
 *    mechanism, not a shared one.
 *
 * 3. **It names where to undo.** #37 landed, so the Archived subjects panel
 *    in the tree editor really can bring the parent back. #252's lesson:
 *    a warning with no way forward is half a warning, and one that denies
 *    an existing way forward is worse.
 *
 * It degrades to silence: a page that forgets the `<script>` tag calls
 * nothing (every caller guards on `typeof`), so the path still renders
 * filtered and correct, just unexplained.
 */
(function () {
    'use strict';

    /**
     * The sentence, as plain text.
     *
     * Also used on its own by surfaces that already have a tooltip of their
     * own to append to (the entry browser's subject chips carry the path in
     * a `title`), where adding a second, tabbable affordance inside a
     * filter control would be worse than extending the one that is there.
     *
     * @param {string[]} names archived ancestor names, newest-walk-first
     * @returns {string} '' when there is nothing to say
     */
    function sentence(names) {
        const list = (names || []).filter(function (n) {
            return typeof n === 'string' && n.trim() !== '';
        });
        if (list.length === 0) return '';

        const quoted = list.map(function (n) { return '"' + n + '"'; });
        let joined;
        if (quoted.length === 1) {
            joined = quoted[0];
        } else if (quoted.length === 2) {
            joined = quoted[0] + ' and ' + quoted[1];
        } else {
            joined = quoted.slice(0, -1).join(', ')
                + ' and ' + quoted[quoted.length - 1];
        }

        const subject = list.length === 1 ? 'is archived' : 'are archived';
        return 'This path is shortened: ' + joined + ' ' + subject
            + ', so it is not shown. Restore it from the Archived subjects '
            + 'panel in the tree editor.';
    }

    /**
     * The hover/focus note element, or `null` when nothing was removed.
     *
     * @param {string[]} names archived ancestor names
     * @returns {HTMLElement|null}
     */
    function create(names) {
        const text = sentence(names);
        if (!text) return null;

        const host = document.createElement('span');
        host.className = 'archived-ancestors-note';
        host.setAttribute('tabindex', '0');
        // The visible glyph and the accessible name are deliberately
        // separate nodes: the glyph is 'i', which says nothing, so the host
        // carries the sentence as its own name. Same split as #6's icon.
        host.setAttribute('aria-label', text);
        host.setAttribute('data-testid', 'archived-ancestors-note');
        host.textContent = 'i';

        const tip = document.createElement('span');
        tip.className = 'archived-ancestors-tooltip';
        tip.setAttribute('data-testid', 'archived-ancestors-tooltip');
        tip.textContent = text;
        host.appendChild(tip);

        return host;
    }

    /**
     * Put the note immediately AFTER `target`, as its sibling.
     *
     * **This is the placement rule, and it is not cosmetic.** The note must
     * never be a child of the node whose `textContent` *is* the path string,
     * because that string is read as a value: `#fullPath` on the deep dive
     * and `.relation-path` in the Related Topics panel are both read by
     * scenarios, and a nested note silently appends this whole sentence --
     * including the `display: none` tooltip, which `textContent` returns and
     * `innerText` does not -- to the value they read. `test_multi_parent_
     * selector_refilter.py` asserts a *name is absent* from `#fullPath`, so
     * nesting could turn an archived subject's name into a false failure
     * there.
     *
     * Same shape as #127's page-gate voice, where nesting the `role="status"`
     * element inside the container it describes was "the one mistake with no
     * symptom". Use `appendTo` only for a *container* that holds the path as
     * several child nodes (the entry detail breadcrumb), where there is no
     * single value node to sit beside.
     *
     * Returns the note or `null`, so a caller can tell whether anything was
     * added.
     */
    function insertAfter(target, names) {
        const note = create(names);
        if (note && target && target.parentNode) {
            target.parentNode.insertBefore(note, target.nextSibling);
        }
        return note;
    }

    /**
     * Append the note to `target` if `names` is non-empty. For containers
     * only — see `insertAfter` for why.
     */
    function appendTo(target, names) {
        const note = create(names);
        if (note && target) target.appendChild(note);
        return note;
    }

    window.ArchivedAncestorNote = {
        sentence: sentence,
        create: create,
        insertAfter: insertAfter,
        appendTo: appendTo,
    };
})();
