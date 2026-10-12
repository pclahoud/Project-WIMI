/**
 * WIMI Escape — the one way a page script turns a value into markup (#548).
 *
 * Every first-party page used to carry its own `escapeHtml`, and the copies
 * disagreed. Twenty-one local helpers in eighteen files, under five names
 * (`escapeHtml`, `escapeAttr`, `_escapeHtml`, `escapeHtmlImport`,
 * `escapeRelationHtml`, ...). Several were the `textContent` -> `innerHTML`
 * round-trip, which escapes `&`, `<` and `>` but NOT `"` -- correct for text
 * content, an injection the moment the result lands inside a double-quoted
 * attribute. And because a top-level `function` is a global, pages quietly
 * borrowed each other's: `weight_editor.js` called `tree_editor.js`'s copy,
 * `import_export.js` called whichever page script happened to define one and
 * never used its own. #324, #525 and #546 were the same defect found three
 * times, one page at a time.
 *
 * So there is one definition, and it is safe in BOTH places a value can land:
 *
 *   `WimiEscape.html(value)` escapes `& < > " '`, so its result may go into
 *   element content or into a single- or double-quoted attribute value.
 *   `WimiEscape.attr` is the same function under a name that says where the
 *   result is going; use whichever reads true at the call site.
 *
 * It is a string replacement, not a DOM round-trip: it needs no document,
 * works on a number or a boolean, and cannot be broken by a value that a
 * parser would reinterpret. `null` and `undefined` become `''`; every other
 * value goes through `String()`, so `0` stays `"0"` (several old copies began
 * `if (!text) return ''`, which turned a count of zero into nothing).
 *
 * Where a row is simple, build it from text nodes instead (`textContent`) --
 * there is then nothing to escape. #533 did that for the deep dive. This is
 * for templates too large to rebuild. A stored rich-text column (reflection,
 * explanation) is not escaped here at all: it is reduced to its words by
 * `WimiTextPreview.htmlToPreviewText` (text_preview.js) and THEN escaped.
 *
 * Load before the page script that uses it, and link it on every page that
 * does -- scripts are linked per page, and `tests/test_web_escaping.py` checks
 * the link both ways, as `test_web_local_date.py` does for `LocalDate`.
 */
(function (global) {
    'use strict';

    const REPLACEMENTS = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    };

    /**
     * Escape a value for element content OR a quoted attribute value.
     *
     * @param {*} value anything; null/undefined become ''
     * @returns {string}
     */
    function html(value) {
        if (value === null || value === undefined) return '';
        return String(value).replace(/[&<>"']/g, ch => REPLACEMENTS[ch]);
    }

    global.WimiEscape = {
        html: html,
        attr: html
    };
})(window);
