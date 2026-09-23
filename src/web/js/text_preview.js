/**
 * WIMI Text Preview — the one reduction of stored rich-text HTML to preview text.
 *
 * Reflections, explanations and the legacy `notes` column are written by
 * TinyMCE, so they are HTML strings in the database. Any surface that
 * clamps one of those fields into a one- or two-line preview wants the
 * same reduction: no markup, the words in reading order, and nothing that
 * can execute.
 *
 * The parse is inert, and that is the whole reason this is a DOMParser
 * call and not a regex or an `innerHTML` round-trip. `parseFromString`
 * builds a document with no browsing context: scripts do not run, `<img>`
 * does not fetch, event-handler attributes never fire, and nothing is
 * inserted into the live page. Only `textContent` crosses back out. A
 * caller that drops the result into a template still escapes it — the
 * inertness here is about the parse, not a licence to stop escaping.
 *
 * Forgejo #41: this existed twice, byte for byte. Issue #3 added it to
 * `entry_browser.js` for the card reflection preview; issue #34 needed the
 * same behaviour for the session-setup entry picker while that first fix
 * was still in an open PR, so it was copied rather than shared. The risk
 * was quiet divergence — teach one copy about `<table>` cells or an
 * `&nbsp;` quirk and the other page keeps the old behaviour with nobody
 * the wiser. One definition now; consumers read it from here.
 *
 * No dependencies; load before the page script that uses it, and add the
 * `<script>` tag to every page that consumes it (scripts are linked per
 * page, so a missing tag leaves the symbol silently undefined).
 */
(function (global) {
    'use strict';

    /**
     * Elements after which a space is inserted so block boundaries do not
     * fuse words together: "<p>a</p><ul><li>b</li></ul>" must read "a b",
     * not "ab". `br` is here for the same reason even though it is inline.
     */
    const BLOCK_BOUNDARY_SELECTOR =
        'p, div, li, br, h1, h2, h3, h4, h5, h6, tr, blockquote, pre';

    /**
     * Reduce stored rich-text HTML to a single line of plain text.
     *
     * Returns '' for null/undefined/empty input. Plain-text (pre-TinyMCE)
     * values pass through with their whitespace collapsed. Runs of
     * whitespace — including the boundary spaces inserted above — collapse
     * to one, and the result is trimmed.
     */
    function htmlToPreviewText(html) {
        if (!html) return '';
        const doc = new DOMParser().parseFromString(html, 'text/html');
        doc.body
            .querySelectorAll(BLOCK_BOUNDARY_SELECTOR)
            .forEach(el => el.insertAdjacentText('afterend', ' '));
        return doc.body.textContent.replace(/\s+/g, ' ').trim();
    }

    global.WimiTextPreview = {
        BLOCK_BOUNDARY_SELECTOR: BLOCK_BOUNDARY_SELECTOR,
        htmlToPreviewText: htmlToPreviewText
    };
})(window);
