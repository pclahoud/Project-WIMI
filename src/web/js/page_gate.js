/**
 * PageGate -- the voice of a page that ships `inert` while it initialises.
 *
 * Settled in #127, which is the accessibility half of #114.
 *
 * The problem this solves
 * -----------------------
 * #114 gates a page by shipping its container with the `inert` attribute and
 * removing it once the page can keep what it is given. That is correct for
 * pointer and keyboard input and must stay. But `inert` does one more thing:
 * it removes the whole subtree from the **accessibility tree**, exactly as
 * `aria-hidden` would. Measured on the entry form through CDP's
 * `Accessibility.getFullAXTree`, with the page's bridge calls held open:
 *
 *     while the gate is up   72 nodes, 71 ignored -- ONE non-ignored node,
 *                            the document root, and nothing else
 *     after release         461 nodes, 290 non-ignored: 52 buttons,
 *                            3 textboxes, 4 comboboxes, the headings...
 *
 * So for the 0.1-0.6 s the gate holds (and up to the 15 s fail-open backstop
 * on a bad day) a screen reader reads an empty document, is told nothing
 * about why, and gets no event when that stops being true. The CSS dim and
 * `cursor: progress` that #114 added are invisible to assistive tech.
 *
 * The shape of the fix
 * --------------------
 * One element, declared in the markup, OUTSIDE the gated container:
 *
 *     <div class="page-gate" data-page-gate role="status" aria-live="polite"
 *         >Preparing the entry form&hellip;</div>
 *     <div class="entry-page" inert data-page-gated> ... </div>
 *
 * and one call, from the page's own release function, after it has removed
 * `inert`:
 *
 *     PageGate.release('Entry form ready.');
 *
 * Five things about that are load-bearing, and four pages are going to copy
 * it (#119 settings, #120 session setup, #121 tree editor, #122 entry
 * browser), so they are spelled out rather than left to be inferred:
 *
 * 1. **Outside the gated container, not inside it.** A status message placed
 *    inside the thing being gated is as invisible to a screen reader as the
 *    form is -- it is in the subtree `inert` removes. This is the one mistake
 *    that produces no symptom at all in a DOM test, so
 *    `tests/test_page_gate_markup.py` is a markup guard against it.
 *
 * 2. **The holding message ships in the markup**, for the same reason the
 *    `inert` attribute does: there must be no window in which the page is
 *    gated and silent. Nothing here puts it there, and nothing needs to.
 *
 * 3. **A live region does not announce what was already in it** when it was
 *    registered, and that is the behaviour we want, not a limitation to work
 *    around. The holding text is simply what a screen reader finds if it
 *    reads the document during the gate. `release()` then *changes* the text,
 *    and a change is what gets announced.
 *
 * 4. **A fast load says nothing.** The entry form is ready in ~110 ms warm
 *    and a student opens it many times in a session; announcing "Entry form
 *    ready." on every one of those would be worse than the silence being
 *    fixed. Below `RELEASE_ANNOUNCE_AFTER_MS` the message is cleared instead
 *    of replaced -- clearing a live region does not announce, because
 *    `aria-relevant` does not include removals by default -- and nobody heard
 *    the holding message either, because the reader was still working through
 *    the document. The threshold is deliberately the same 250 ms the CSS
 *    waits before dimming the page, so there is one number and one story:
 *    under it nothing is shown and nothing is said; over it the dim appears
 *    and the handover is announced.
 *
 * 5. **The release of `inert` is NOT this module's job.** It stays as a bare
 *    `removeAttribute` in the page's own gate function, ahead of the call to
 *    `release()` and outside its try. A permanently gated page is a far worse
 *    bug than the one #127 describes (#114's own rule), so nothing added for
 *    assistive tech -- a missing `<script>` tag included -- may be able to
 *    cause one. `release()` returning false means "nothing was announced",
 *    never "the page is still gated".
 *
 * Deliberately NOT done: moving focus on release. Nothing inside the gated
 * container is focusable while the gate is up, so there is no lost focus to
 * restore, and grabbing focus from a user who was working in the browser
 * chrome is its own defect. The announcement is the event; where the reader
 * goes next is the reader's business.
 */
(function () {
    'use strict';

    const GATE_SELECTOR = '[data-page-gate]';

    /**
     * Below this, release() clears the message instead of replacing it, so
     * nothing is announced. Same value as `.page-gate`'s animation delay in
     * styles.css -- see point 4 above. Exported so a test can assert against
     * the real number rather than a copy of it.
     */
    const RELEASE_ANNOUNCE_AFTER_MS = 250;

    function gateElement() {
        return document.querySelector(GATE_SELECTOR);
    }

    /**
     * How long the gate has been up, in milliseconds.
     *
     * The gate ships in the markup, so it has been up since the document
     * started -- which is what `performance.now()` measures, with no
     * bookkeeping to get out of step with the attribute. Parse time and
     * script loading are part of the gate and are correctly included.
     */
    function heldForMs() {
        try {
            return performance.now();
        } catch (err) {
            // No usable clock: assume the gate dragged and announce. Saying
            // something unnecessary is the better failure here.
            return RELEASE_ANNOUNCE_AFTER_MS;
        }
    }

    /**
     * Is a gate that was up for `ms` worth announcing the end of?
     *
     * Pure, and exposed on `window` for that reason: the branch it decides
     * cannot be reached deterministically through a real page load, because
     * how long a load takes is the thing being measured. A scenario that
     * waited for a fast load to assert the quiet branch would skip itself on
     * any machine slower than the threshold -- which is every headless box
     * this suite runs on. Same reasoning as #237's pure export builders.
     *
     * Written as `!(ms < threshold)` rather than `ms >= threshold` so that a
     * NaN -- an unusable clock reading -- announces instead of going quiet.
     * Every comparison with NaN is false, so the two forms differ exactly
     * there, and the one that speaks is the better failure: an unnecessary
     * announcement is a small annoyance, a missed one is #127 again. Do not
     * "simplify" it to `>=`.
     *
     * @param {number} ms how long the gate was up
     * @returns {boolean} whether to announce rather than go quiet
     */
    function shouldAnnounce(ms) {
        return !(ms < RELEASE_ANNOUNCE_AFTER_MS);
    }

    /**
     * Hand the page over, as far as assistive tech is concerned.
     *
     * Call AFTER removing `inert`. Returns true if `readyMessage` was put
     * into the live region (and therefore announced), false if the gate was
     * too brief to be worth announcing or there is no gate element on the
     * page. Never throws for a reason a caller should care about.
     *
     * @param {string} readyMessage What to announce, e.g. 'Entry form ready.'
     * @returns {boolean} whether anything was announced
     */
    function release(readyMessage) {
        const gate = gateElement();
        if (!gate) return false;

        // Replacing the live region's own textContent is the announcement.
        // An empty message cannot be one, however long the gate was up, so
        // the recorded answer is "did anything get said" rather than "did we
        // intend to say something" -- an announced=true with no text would be
        // a lie a test could not see past.
        const text = shouldAnnounce(heldForMs()) ? String(readyMessage || '') : '';
        gate.textContent = text;
        gate.setAttribute('data-gate-state', 'ready');
        gate.setAttribute('data-gate-announced', text ? 'true' : 'false');
        return Boolean(text);
    }

    window.PageGate = {
        RELEASE_ANNOUNCE_AFTER_MS: RELEASE_ANNOUNCE_AFTER_MS,
        shouldAnnounce: shouldAnnounce,
        release: release,
    };
})();
