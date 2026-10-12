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
 * carrying `data-modal-keep-announced`, the opt-out for an element shown
 * beside a dialog on purpose. The first-run tour's tip is the first (#430):
 * it can describe a control inside the tree editor's import preview.
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
 * subtree holding focus is never hidden, so the boundary is completed on the
 * sweep where focus finishes moving into the dialog rather than cached as
 * drawn before it has (#422); and a throw unhides everything.
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
    /**
     * Did the last walk SKIP a subtree because it held focus (#422)?
     *
     * The difference between "a boundary was drawn" and "an attempt was made",
     * which is the whole of #422. See `boundaryIsCurrent`.
     */
    var hiddenSkippedFocus = false;
    /** `document.activeElement` when that walk ran -- what has to move. */
    var hiddenFocusWas = null;
    var lastFocused = null;
    var scheduled = false;
    var settle = null;
    /** Frames still to sweep after the last change (see FOLLOW_FRAMES). */
    var followFrames = 0;
    /** Open surfaces whose focus move is waiting for a control to render. */
    var pending = [];
    /** How many sweeps each pending surface has waited (see DEFER_SWEEPS). */
    var deferrals = new WeakMap();

    /**
     * Sweep this many frames after every change, not just the next one (#374).
     *
     * A modal opens by a class change, and that mutation schedules a sweep for
     * the next frame -- but in that frame the surface is often NOT YET visible:
     * a `visibility` transition reads `hidden` at its first frame, and the
     * surface reads visible one frame later through a style change, which
     * emits no mutation. So nothing looked again until SETTLE_MS, and focus
     * sat on the control BEHIND the dialog for that long. Measured on
     * Windows machine B, tree editor delete modal: `.active` at t, surface
     * visible at t+6..20 ms, buttons visible ~20 ms later, focus moved at
     * t+330..360 ms -- by the settle pass. A real Enter key-repeat in that
     * window activated the opener behind the open dialog 2-3 times per run.
     *
     * A handful of frames covers the frame-late reveal without polling
     * forever; SETTLE_MS below stays as the fallback, so a surface that takes
     * longer still behaves exactly as it did before this.
     */
    var FOLLOW_FRAMES = 6;

    /**
     * How many sweeps focusInto() waits for a control to become visible before
     * falling back to focusing the surface itself (#374).
     *
     * A surface's buttons can render a frame after the surface does. Falling
     * back to the container in that frame made the landing target depend on
     * frame timing -- the Cancel button on most runs, the dialog box on the
     * rest. The fallback is still reached, and still needed: a dialog that
     * genuinely has nothing focusable must still receive focus.
     */
    var DEFER_SWEEPS = 10;

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

    /**
     * Move focus into an open surface. Returns false when it chose to wait
     * for a control that exists but has not rendered yet, so the caller
     * retries on a later sweep; true when focus is settled either way.
     */
    function focusInto(surface) {
        try {
            // The page's own choice wins. image_browser.js focuses its search
            // box synchronously as it renders, which happens before this
            // observer's microtask, so that choice is already in place here.
            if (surface.contains(document.activeElement)) return true;
            // So does a companion's: an element shown beside the dialog on
            // purpose, which may hold focus while it is open (the first-run
            // tour's tip about a control inside the dialog, #430). Taking
            // focus from it made who held it a race between this sweep and
            // the tip's own bridge round trip, measured going both ways.
            var active = document.activeElement;
            if (active && active.closest && active.closest('[data-modal-companion]')) return true;

            var target = surface.querySelector('[autofocus]')
                || focusables(surface)[0];
            if (!target) {
                // Controls that exist but are not visible YET are worth a
                // few frames' wait; a surface with none at all is not (#374).
                var waited = deferrals.get(surface) || 0;
                if (waited < DEFER_SWEEPS && surface.querySelector(FOCUSABLE)) {
                    deferrals.set(surface, waited + 1);
                    return false;
                }
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
        deferrals.delete(surface);
        return true;
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
        hiddenSkippedFocus = false;
        hiddenFocusWas = null;
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
    /**
     * Hide `el` from the accessibility tree, keeping any live region inside it.
     *
     * A sibling that CONTAINS a live region used to be skipped whole, which
     * kept the region audible and also left everything around it exposed. On
     * a page whose main container holds one -- Settings carries the
     * folder-sync status lines (#401) and an alert inside `.app-container` --
     * that skipped the entire page: with the #412 dialog open, the helper
     * hid two <script> elements and the exposed node count ROSE, 190 -> 214
     * (Windows machine B). So such an element is now descended into instead:
     * its children are hidden one by one, and only the live regions and the
     * elements on the way to them stay in the tree.
     */
    function hideOutside(el) {
        if (el.hasAttribute('aria-hidden')) return;
        if (el.matches(KEEP_ANNOUNCED)) return;
        // Never hide a subtree holding focus: that is an ARIA violation, and
        // the Tab trap means it should be impossible -- so if it happens,
        // leave it alone rather than produce an invalid tree.
        //
        // It is NOT impossible while focus is on its way in: `focusInto`
        // waits a few sweeps for a control that exists but has not rendered
        // (#374), and for those sweeps the subtree holding focus is the page
        // container the invoker sits in -- i.e. almost the whole page. So the
        // skip is recorded, because a walk that skipped is not a boundary and
        // must not be cached as one (#422).
        if (el.contains(document.activeElement)) {
            hiddenSkippedFocus = true;
            return;
        }
        if (el.querySelector(KEEP_ANNOUNCED)) {
            var kids = el.children;
            for (var k = 0; k < kids.length; k++) hideOutside(kids[k]);
            return;
        }
        el.setAttribute('aria-hidden', 'true');
        hidden.push(el);
    }

    /**
     * Is the boundary currently held still the right answer for `surface`?
     *
     * THE CACHE HAS TO RECORD A DRAWN BOUNDARY, NOT AN ATTEMPTED ONE (#422).
     * Keyed on the surface alone it recorded the attempt, and the two guards
     * either side of it combined into a permanent no-op: `sweep` calls
     * `hideBackground` on every pass, `focusInto` may spend several of those
     * passes waiting for a control to render (#374), and for each of them
     * `hideOutside` refuses the page container because the invoker inside it
     * still holds focus. So the first walk hid nothing of the page, the
     * surface never changed again, and every later sweep returned early --
     * the dialog went its whole life with no boundary, with `role`, the name,
     * `aria-modal` and eventual focus all still correct, and only
     * `hiddenCount()` or the exposed node count able to see it.
     *
     * A walk that skipped nothing is still the right answer, which is what
     * keeps the cache worth having: re-walking the page's subtrees looking for
     * live regions on every sweep would cost that each time anything animates.
     * A walk that SKIPPED is the right answer only while focus has not moved,
     * because moving focus is precisely what unblocks the skip -- one identity
     * comparison, and it settles after exactly one extra walk rather than
     * re-walking per sweep.
     */
    function boundaryIsCurrent(surface) {
        if (surface !== hiddenFor) return false;
        if (!hiddenSkippedFocus) return true;
        return document.activeElement === hiddenFocusWas;
    }

    function hideBackground(surface) {
        if (boundaryIsCurrent(surface)) return;
        showBackground();
        if (!surface) return;
        hiddenFor = surface;
        hiddenFocusWas = document.activeElement;
        try {
            var node = surface;
            while (node && node.parentNode && node !== document.body) {
                var siblings = node.parentNode.children;
                for (var i = 0; i < siblings.length; i++) {
                    if (siblings[i] !== node) hideOutside(siblings[i]);
                }
                node = node.parentNode;
            }
        } catch (err) {
            console.warn('modal_dialog: could not hide the background', err);
            showBackground();
        }
    }

    function sweep() {
        var now = openSurfaces();
        var waiting = [];
        var i;

        for (i = 0; i < now.length; i++) {
            var isNew = open.indexOf(now[i]) === -1;
            if (isNew && !invokers.has(now[i])) {
                var from = document.activeElement;
                // Focus already INSIDE the new dialog means the page moved it
                // there itself before this sweep (the relation modal focuses
                // its search box as it renders), so activeElement no longer
                // names the opener. `lastFocused` does: it records the last
                // focus outside any surface. Without this the invoker was
                // never recorded and closing dropped focus to <body> (#374).
                if (!from || from === document.body || now[i].contains(from)) {
                    from = lastFocused;
                }
                if (from && !now[i].contains(from)) invokers.set(now[i], from);
            }
            // A surface that opened in an earlier sweep but was waiting for
            // its controls to render is retried until focusInto settles it.
            if ((isNew || pending.indexOf(now[i]) !== -1) && !focusInto(now[i])) {
                waiting.push(now[i]);
            }
        }
        pending = waiting;
        for (i = 0; i < open.length; i++) {
            if (now.indexOf(open[i]) === -1) restoreFocus(open[i]);
        }
        open = now;

        // The boundary is always the topmost open dialog's, derived rather
        // than reference counted -- so a modal opening over a modal needs no
        // bookkeeping, and a wrong count cannot leave the page permanently
        // hidden. `hideBackground` is a no-op when that dialog has not changed
        // AND the last walk actually drew the boundary; it deliberately runs
        // again on the sweep where focus finishes arriving (#422), because
        // until then the subtree the invoker sits in cannot be hidden.
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
     * would never be returned.
     *
     * Since #374 the end of that transition is ALSO caught directly: one
     * document-level listener for transition and animation events on a
     * surface or anything containing one (see `start`), so focus returns when
     * the dialog actually disappears instead of up to SETTLE_MS later. The
     * timer stays as the guard for a property that never animates, and as the
     * fallback for everything FOLLOW_FRAMES does not cover.
     */
    var SETTLE_MS = 400;

    function onFrame() {
        scheduled = false;
        sweep();
        // Keep looking for a few frames after a change, and for as long as a
        // surface is waiting for its controls -- both bounded (FOLLOW_FRAMES,
        // DEFER_SWEEPS), so this always stops.
        if (followFrames > 0 || pending.length) {
            if (followFrames > 0) followFrames--;
            queueFrame();
        }
    }

    function queueFrame() {
        if (scheduled) return;
        scheduled = true;
        if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(onFrame);
        } else {
            setTimeout(onFrame, 16);
        }
    }

    function schedule() {
        if (settle) clearTimeout(settle);
        settle = setTimeout(sweep, SETTLE_MS);
        followFrames = FOLLOW_FRAMES;
        queueFrame();
    }

    /**
     * A transition or animation on a surface, or on anything holding one,
     * may have just changed whether it is visible -- with no mutation to say
     * so. Anything else is ignored, so hover effects elsewhere on the page
     * cost nothing.
     */
    function onVisualChange(event) {
        try {
            var t = event.target;
            if (t && t.matches && (t.matches(SURFACE) || t.querySelector(SURFACE))) {
                schedule();
            }
        } catch (err) { /* the settle pass still covers it */ }
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
            // Capture phase: transition/animation events do bubble, but a
            // page handler calling stopPropagation must not blind this file.
            ['transitionrun', 'transitionend', 'transitioncancel',
             'animationstart', 'animationend'].forEach(function (type) {
                document.addEventListener(type, onVisualChange, true);
            });

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
