/**
 * modal_dialog.js -- the focus half of the modal pattern (#319).
 *
 * THE CONTRACT
 * ============
 * A modal has two parts and they are not interchangeable:
 *
 *   <div class="modal-backdrop" id="x">            <!-- the OVERLAY: scrim +
 *                                                       click-to-dismiss -->
 *     <div class="modal" data-modal-surface        <!-- the SURFACE: the box -->
 *          role="dialog" aria-modal="true"
 *          aria-labelledby="x-title">
 *       <h2 class="modal-title" id="x-title">...</h2>
 *
 * The markup carries `role`, `aria-modal` and the accessible name. This file
 * carries what markup cannot express: focus moves into the dialog when it
 * opens, stays inside it with Tab, and returns to whatever opened it on close.
 *
 * WHY THE ATTRIBUTES ARE *NOT* SET FROM HERE
 * ------------------------------------------
 * The same reason `page_gate.js` does not install its own holding message and
 * `inert` ships in the markup (#114/#127): there must be no window in which a
 * dialog is on screen without its semantics. A script-applied role is also
 * invisible to `tests/test_modal_dialog_markup.py`, which is the thing that
 * makes the next modal correct by default. So this file never writes `role`,
 * `aria-modal`, `aria-labelledby` or `aria-label`.
 *
 * WHY aria-modal AND NOT `inert` ON THE PAGE
 * ------------------------------------------
 * #319 offered `inert` on the page container as "the modern answer". It cannot
 * work here, measured rather than argued: **eight of this tree's modals live
 * INSIDE the page container they would have to gate** -- `exam_wizard.html`'s
 * four sit in `div.wizard-page`, and `media_upload.js` injects four more into
 * `#media-upload-container` inside `.entry-page`. Gating the container would
 * make those modals inert too. And on the five gated pages `inert` is already
 * spoken for: `[data-page-gated][inert]` in styles.css carries the page gate's
 * 0.55 dim, so a modal would dim the page it just opened over.
 *
 * `aria-modal="true"` is therefore the declared mechanism, and it carries the
 * MEANING of the dialog boundary. It does not, on its own, produce it here.
 *
 * aria-modal IS NOT HONOURED BY THIS ENGINE -- MEASURED
 * ----------------------------------------------------
 * QtWebEngine 6.9.2 / Chromium 130, through CDP's `Accessibility` domain on
 * the tree editor. Exposed (non-ignored) accessibility nodes, with the
 * delete-subject dialog open:
 *
 *     baseline, no dialog                        119 exposed of 221
 *     dialog revealed by a class change          143 exposed of 245
 *     a FRESH aria-modal dialog, DOM-inserted    126 exposed of 228
 *     the surface removed and re-inserted open   143 exposed of 245
 *     aria-hidden applied to the path siblings    25 exposed of 117
 *
 * In the first four the page behind the dialog is still fully exposed -- the
 * exam name is still an announced accessible name. The third row is the one
 * that matters: "Blink only computes the active aria-modal dialog on DOM
 * insertion" was the obvious hypothesis and it is **wrong**, so there is no
 * ordering trick that makes the attribute work. Only the last row produces
 * the boundary, and the 25 exposed nodes it leaves are the dialog's own.
 *
 * So `hideBackground()` below walks from the surface to `<body>` and sets
 * `aria-hidden="true"` on every sibling along that path, removing exactly
 * what it added when the dialog closes. It keeps the attribute as well,
 * because `aria-modal` is what a conforming engine (and a future Qt) reads,
 * and because it is what the markup guard checks for.
 *
 * Two things it deliberately does not hide: **live regions**
 * (`[aria-live]`, `role=status/alert/log`) outside the dialog, because an
 * alert must still reach the student -- `.page-gate` is one -- and anything
 * carrying `data-modal-keep-announced`, which is the opt-out for a case
 * nobody has met yet.
 *
 * WHY Escape IS NOT HANDLED
 * -------------------------
 * Closing is each modal's own business -- some confirm, some save, some are
 * mid-flight in a wizard step -- and there is no close() this file could call
 * that is right for 45 surfaces. Synthesising one would be a behaviour change
 * wearing an accessibility fix's clothes. Escape-to-close belongs with
 * whatever owns each modal's lifecycle.
 *
 * HOW IT FAILS
 * ------------
 * Open: it never moves focus that is already inside the dialog, so a modal
 * that focuses its own search box (image_browser.js) keeps its choice.
 * Tab: the trap resolves the open dialog freshly on every keypress and only
 * calls preventDefault() when it has actually moved focus -- so in the worst
 * case Tab behaves exactly as it does today. A dialog with nothing focusable
 * in it is left alone.
 * Background: every `aria-hidden` written is remembered and only those are
 * removed, so an `aria-hidden` the page set itself survives untouched; a
 * subtree holding focus is never hidden; and a throw unhides everything.
 *
 * Nothing here can wedge a page, which is the same rule the page gate is
 * built on: a permanently gated page is worse than the bug it fixes.
 */
(function () {
    'use strict';

    var SURFACE = '[data-modal-surface]';

    // Deliberately not `:focus-visible`-aware and deliberately not a library.
    // `[tabindex="-1"]` is excluded: it is programmatically focusable but not
    // a Tab stop, and the trap is about Tab stops.
    var FOCUSABLE = [
        'a[href]',
        'area[href]',
        'button:not([disabled])',
        'input:not([disabled]):not([type="hidden"])',
        'select:not([disabled])',
        'textarea:not([disabled])',
        'summary',
        'iframe',
        '[contenteditable="true"]',
        '[tabindex]:not([tabindex="-1"])'
    ].join(',');

    // A live region outside the dialog is still worth hearing: a toast
    // saying the save failed, or the page gate's own `role="status"`.
    var KEEP_ANNOUNCED = [
        '[aria-live]',
        '[role="status"]',
        '[role="alert"]',
        '[role="log"]',
        '[data-modal-keep-announced]'
    ].join(',');

    /** The element that had focus before the current dialog opened. */
    var invokers = new WeakMap();
    /** The set of surfaces this file currently believes are open. */
    var open = [];
    /** Elements THIS file set `aria-hidden` on, so it removes only its own. */
    var hidden = [];
    /** The surface `hidden` was computed for; null when nothing is hidden. */
    var hiddenFor = null;
    var lastFocused = null;
    var scheduled = false;
    var settle = null;

    /**
     * Is this element rendered? `display` and `visibility` only.
     *
     * NOT opacity, and that is measured rather than tidied. Every
     * `.modal-backdrop` in this tree fades in with
     * `transition: opacity, visibility`, so for the first frames after
     * `.active` lands the computed opacity is still 0. An opacity-aware test
     * therefore reports the dialog CLOSED exactly when it has just opened,
     * the observer's one scheduled sweep finds nothing, and -- because a CSS
     * transition emits no mutations -- nothing ever looks again. Measured:
     * focus stayed on the button that opened the dialog, and the only reason
     * the background was ever hidden was an unrelated later mutation (the
     * delete preview's text arriving) happening to trigger a second sweep.
     *
     * `visibility` flips to `visible` at the START of a show transition and
     * back to `hidden` at the END of a hide one, so this reads "open"
     * immediately and stays "open" for the length of the close animation --
     * which is what `SETTLE_MS` below exists for.
     */
    function visible(el) {
        try {
            if (typeof el.checkVisibility === 'function') {
                return el.checkVisibility({ checkVisibilityCSS: true });
            }
        } catch (err) { /* fall through to the geometric test */ }
        return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    }

    /**
     * Is this surface open AND reachable?
     *
     * The `inert` test is what keeps this out of the page gate's way: a modal
     * inside a container that is still gated (#114) is on screen for nobody,
     * and taking focus into it would be taking focus into a subtree the
     * browser refuses to focus anyway.
     */
    function isOpen(surface) {
        try {
            if (surface.closest('[inert]')) return false;
            return visible(surface);
        } catch (err) {
            return false;
        }
    }

    function openSurfaces() {
        var out = [];
        try {
            var all = document.querySelectorAll(SURFACE);
            for (var i = 0; i < all.length; i++) {
                if (isOpen(all[i])) out.push(all[i]);
            }
        } catch (err) { /* no dialogs is a safe answer */ }
        return out;
    }

    /**
     * The dialog Tab should be confined to.
     *
     * Last in document order among the open ones. Stacking context would be
     * the formally right answer, but every modal-over-modal pair in this tree
     * (the media rename/delete modals over the image viewer, the import error
     * over the import preview) is also later in the document, and reading
     * z-index off `getComputedStyle` for every open surface on every keypress
     * buys nothing measurable here.
     */
    function topmost() {
        var all = openSurfaces();
        return all.length ? all[all.length - 1] : null;
    }

    function focusables(root) {
        var out = [];
        try {
            var all = root.querySelectorAll(FOCUSABLE);
            for (var i = 0; i < all.length; i++) {
                if (visible(all[i])) out.push(all[i]);
            }
        } catch (err) { /* an empty list means "leave Tab alone" */ }
        return out;
    }

    function focusInto(surface) {
        try {
            // The page's own choice wins. image_browser.js focuses its search
            // box synchronously as it renders, which happens before this
            // observer's microtask, so that choice is already in place here.
            if (surface.contains(document.activeElement)) return;

            var target = surface.querySelector('[autofocus]')
                || focusables(surface)[0];
            if (!target) {
                // Nothing to focus: make the dialog itself the landing place
                // so a reader is at least inside the thing that just opened.
                target = surface;
                if (!surface.hasAttribute('tabindex')) {
                    surface.setAttribute('tabindex', '-1');
                }
            }
            target.focus();
        } catch (err) {
            console.warn('modal_dialog: could not focus into the dialog', err);
        }
    }

    function restoreFocus(surface) {
        try {
            var invoker = invokers.get(surface);
            invokers.delete(surface);
            if (!invoker || !document.contains(invoker)) return;

            // Only restore when focus is loose -- still inside the dialog
            // that just closed, or dropped to <body> because the element
            // holding it was removed. If something has deliberately moved
            // focus elsewhere (the next dialog in a chain, a control the page
            // focused itself), leave it there.
            var active = document.activeElement;
            var loose = !active
                || active === document.body
                || surface.contains(active)
                || !document.contains(active);
            if (!loose) return;

            if (visible(invoker)) invoker.focus();
        } catch (err) {
            console.warn('modal_dialog: could not restore focus', err);
        }
    }

    /** Undo exactly the `aria-hidden` attributes this file wrote. */
    function showBackground() {
        hiddenFor = null;
        for (var i = 0; i < hidden.length; i++) {
            try {
                hidden[i].removeAttribute('aria-hidden');
            } catch (err) { /* the element may be gone; that is fine */ }
        }
        hidden = [];
    }

    /**
     * Take everything outside `surface` out of the accessibility tree.
     *
     * See the header: `aria-modal` alone does nothing here, measured. Walking
     * to `<body>` rather than hiding `<body>`'s other children is what makes
     * this work for the eight modals that live INSIDE a page container.
     */
    function hideBackground(surface) {
        // Recomputing on every sweep would re-walk the page's subtrees
        // looking for live regions each time anything animates. The boundary
        // only changes when the topmost dialog does.
        if (surface === hiddenFor) return;
        showBackground();
        if (!surface) return;
        hiddenFor = surface;
        try {
            var node = surface;
            while (node && node.parentNode && node !== document.body) {
                var siblings = node.parentNode.children;
                for (var i = 0; i < siblings.length; i++) {
                    var sib = siblings[i];
                    if (sib === node) continue;
                    if (sib.hasAttribute('aria-hidden')) continue;
                    if (sib.matches(KEEP_ANNOUNCED)) continue;
                    if (sib.querySelector(KEEP_ANNOUNCED)) continue;
                    // Never hide a subtree holding focus: that is an ARIA
                    // violation, and the Tab trap means it should be
                    // impossible -- so if it happens, leave it alone rather
                    // than produce an invalid tree.
                    if (sib.contains(document.activeElement)) continue;
                    sib.setAttribute('aria-hidden', 'true');
                    hidden.push(sib);
                }
                node = node.parentNode;
            }
        } catch (err) {
            console.warn('modal_dialog: could not hide the background', err);
            showBackground();
        }
    }

    function sweep() {
        scheduled = false;
        var now = openSurfaces();
        var i;

        for (i = 0; i < now.length; i++) {
            if (open.indexOf(now[i]) === -1) {
                if (!invokers.has(now[i])) {
                    var from = document.activeElement;
                    if (!from || from === document.body) from = lastFocused;
                    if (from && !now[i].contains(from)) invokers.set(now[i], from);
                }
                focusInto(now[i]);
            }
        }
        for (i = 0; i < open.length; i++) {
            if (now.indexOf(open[i]) === -1) restoreFocus(open[i]);
        }
        open = now;

        // The boundary is always the topmost open dialog's, derived rather
        // than reference counted -- so a modal opening over a modal needs no
        // bookkeeping, and a wrong count cannot leave the page permanently
        // hidden. `hideBackground` is a no-op when that dialog has not
        // changed.
        hideBackground(now.length ? now[now.length - 1] : null);
    }

    /**
     * Longer than any modal transition in this tree.
     *
     * A modal closes by removing a class, and `visibility` only becomes
     * `hidden` when that transition ENDS -- by which time there are no more
     * mutations to schedule a sweep from. Without a settle pass the helper
     * would believe a closed dialog was still open: the background would stay
     * `aria-hidden`, Tab would stay trapped in an invisible box, and focus
     * would never be returned. `transitionend` would be more precise and
     * needs a listener per overlay plus a guard for the case where the
     * property never animates; this is one timer.
     */
    var SETTLE_MS = 400;

    function schedule() {
        if (settle) clearTimeout(settle);
        settle = setTimeout(sweep, SETTLE_MS);
        if (scheduled) return;
        scheduled = true;
        if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(sweep);
        } else {
            setTimeout(sweep, 0);
        }
    }

    function onKeydown(event) {
        // Bubble phase and `defaultPrevented`, so any handler the page itself
        // binds to Tab keeps winning. This runs last or not at all.
        if (event.key !== 'Tab' || event.defaultPrevented) return;
        var dialog = topmost();
        if (!dialog) return;

        var items = focusables(dialog);
        if (!items.length) return;

        var first = items[0];
        var last = items[items.length - 1];
        var active = document.activeElement;

        try {
            if (!dialog.contains(active)) {
                // Focus is outside an open modal dialog. With
                // aria-modal="true" that content is not in the accessibility
                // tree, so a reader would follow focus into silence.
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
                return;
            }
            if (!event.shiftKey && active === last) {
                event.preventDefault();
                first.focus();
            } else if (event.shiftKey && active === first) {
                event.preventDefault();
                last.focus();
            }
        } catch (err) {
            console.warn('modal_dialog: Tab was left to the browser', err);
        }
    }

    function start() {
        try {
            document.addEventListener('focusin', function (event) {
                var el = event.target;
                if (el && el.closest && !el.closest(SURFACE)) lastFocused = el;
            }, false);
            document.addEventListener('keydown', onKeydown, false);

            // `class` is how almost every modal here opens (`.active`,
            // `.hidden`); `style` covers the ones toggled with
            // `style.display`; `childList` covers the ones created on demand
            // (goal_widget, subject_relations, export_dialog, rich_editor,
            // image_browser, import_export).
            new MutationObserver(schedule).observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['class', 'style', 'hidden', 'inert'],
                childList: true,
                subtree: true
            });
            sweep();
        } catch (err) {
            console.warn('modal_dialog: not watching for dialogs', err);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }

    // Exposed for the regression scenarios, which need to ask what this file
    // thinks is open without re-deriving the predicate (and getting it wrong).
    window.ModalDialog = {
        openSurfaces: openSurfaces,
        topmost: topmost,
        focusables: focusables,
        invokerOf: function (surface) { return invokers.get(surface) || null; },
        // How many elements this file is currently holding aria-hidden. The
        // scenario reads it to tell "the boundary was drawn" apart from "the
        // engine happened to expose less of the page".
        hiddenCount: function () { return hidden.length; }
    };
})();
