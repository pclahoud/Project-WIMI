/**
 * WIMI Rich HTML — show a student's own formatting, and nothing that runs (#589).
 *
 * Reflections, explanations and notes are stored as TinyMCE HTML, and the
 * entry page shows them WITH their formatting: bold, lists, tables, links,
 * pasted images, maths. Rendering that string with `innerHTML` also renders
 * whatever else it contains, and the editor is not the only way in -- a
 * profile import, a `.wimi` restore or a session import carries any HTML at
 * all. Measured on #548's sweep: an `<img onerror>` in each of the three
 * fields ran on the entry page, the note's twice.
 *
 * Owner's decision on #589: keep the formatting, filter the markup, no new
 * dependency. So this is an ALLOWLIST, and it never inserts a parsed node:
 *
 * 1. The stored string is parsed with `DOMParser`, which builds a document
 *    with no browsing context -- scripts do not run, images do not load,
 *    handlers never fire (the property text_preview.js relies on too).
 * 2. A FRESH tree is built in the live document from that parse, element by
 *    element, copying only allowed attributes with allowed values. Anything
 *    not on the list is not copied; it cannot be "missed by a strip", because
 *    nothing is stripped.
 *
 * What is kept, and why each is on the list:
 *   tags        what the editor's toolbar produces (formatting, lists,
 *               blockquote, code, headings, tables, links) plus `img` for
 *               pasted images (`paste_data_images: true`) and `span`/`div`.
 *               An unknown element is UNWRAPPED (its text survives); a
 *               dangerous one (script, style, iframe, svg, ...) is dropped
 *               with its content.
 *   attributes  layout and table attributes, `class`, `title`, and
 *               `data-formula` (the maths markup renderMathFormulas reads).
 *   href        http, https and mailto only; a link opens in a new window
 *               with `rel="noopener noreferrer"`.
 *   img src     `data:image/{png,jpeg,gif,webp}` only. A stored image is a
 *               pasted one; nothing else should fetch.
 *   style       an allowlist of CSS PROPERTIES (#591), copied from the
 *               element's parsed `style`, never from the attribute text.
 *
 * Why there is no escape handling in the style rule: the attribute string
 * is not read. The CSS parser has already tokenised it on the inert element,
 * so `\75 rl(` is just `url(` by the time we see it, a shorthand arrives as
 * its longhands, and an unknown or invalid declaration is simply absent. What
 * survives is decided by the property NAME, and no allowed property takes a
 * URL or moves an element out of the text: `background-color`, not
 * `background`; `list-style-type`, not `list-style`. Anything not named --
 * `position`, `z-index`, `opacity`, `transform`, custom properties, whatever
 * CSS adds next -- is absent because it was never named. Do not put a regex
 * back here: a text-matching denylist is what #591 measured being evaded.
 *
 * The set is what the configured editor (rich_editor.js) can produce:
 * forecolor/backcolor, the table plugin's defaults and properties dialog,
 * advlist's list styles, plus plain typography a pasted or `code`-edited
 * document carries. An ambiguous formatting property is kept; dropping one
 * would silently flatten a student's table with no error anywhere.
 *
 * Load it on any page that renders stored rich text, before that page's
 * script; tests/test_web_escaping.py checks the link both ways.
 */
(function (global) {
    'use strict';

    const KEEP_TAGS = new Set([
        'p', 'br', 'div', 'span', 'b', 'strong', 'i', 'em', 'u', 's', 'strike',
        'del', 'ins', 'sub', 'sup', 'small', 'mark', 'ul', 'ol', 'li',
        'blockquote', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr',
        'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption',
        'colgroup', 'col', 'a', 'img'
    ]);

    /** Dropped WITH their content: what is inside them is not text. */
    const DROP_TAGS = new Set([
        'script', 'style', 'iframe', 'frame', 'frameset', 'object', 'embed',
        'applet', 'link', 'meta', 'base', 'template', 'noscript', 'svg', 'math',
        'form', 'input', 'button', 'textarea', 'select', 'option', 'audio',
        'video', 'source', 'track', 'canvas', 'portal', 'head', 'title'
    ]);

    const KEEP_ATTRS = new Set([
        'class', 'title', 'dir', 'lang', 'colspan', 'rowspan', 'scope',
        'headers', 'width', 'height', 'align', 'valign', 'border',
        'cellpadding', 'cellspacing', 'start', 'reversed', 'type', 'alt',
        'data-formula'
    ]);

    const SAFE_HREF = /^(https?:|mailto:)/i;
    const SAFE_IMG = /^data:image\/(png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$/i;

    /** CSS longhands a stored `style` may keep (#591); see the header. */
    const KEEP_STYLE = new Set([
        'color', 'background-color',
        'font-family', 'font-size', 'font-style', 'font-weight', 'font-variant-caps',
        'line-height', 'letter-spacing', 'word-spacing',
        'text-align', 'text-indent', 'text-transform', 'vertical-align',
        'text-decoration-line', 'text-decoration-style', 'text-decoration-color',
        'text-decoration-thickness',
        'white-space', 'white-space-collapse', 'text-wrap-mode', 'direction',
        'width', 'height', 'min-width', 'max-width', 'min-height', 'max-height',
        'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
        'margin-top', 'margin-right', 'margin-bottom', 'margin-left',
        'border-collapse', 'border-spacing',
        '-webkit-border-horizontal-spacing', '-webkit-border-vertical-spacing',
        'border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width',
        'border-top-style', 'border-right-style', 'border-bottom-style', 'border-left-style',
        'border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color',
        'border-top-left-radius', 'border-top-right-radius',
        'border-bottom-right-radius', 'border-bottom-left-radius',
        'list-style-type', 'float', 'clear', 'table-layout', 'caption-side'
    ]);

    /** A margin may only push text apart: a negative one lifts it over its neighbours. */
    const NONNEGATIVE = /^(auto|0|[0-9.]+[a-z%]*)$/i;

    function copyStyle(from, to) {
        const style = from.style;
        if (!style) return;
        for (let i = 0; i < style.length; i++) {
            const name = style[i];
            if (!KEEP_STYLE.has(name)) continue;
            const value = style.getPropertyValue(name);
            if (name.startsWith('margin-') && !NONNEGATIVE.test(value.trim())) continue;
            to.style.setProperty(name, value);
        }
    }

    function parse(html) {
        return new DOMParser().parseFromString(String(html || ''), 'text/html');
    }

    function copyAttributes(from, to, tag) {
        for (const attr of Array.from(from.attributes)) {
            const name = attr.name.toLowerCase();
            const value = attr.value;
            if (name === 'href' && tag === 'a') {
                if (SAFE_HREF.test(value.trim())) {
                    to.setAttribute('href', value.trim());
                    to.setAttribute('target', '_blank');
                    to.setAttribute('rel', 'noopener noreferrer');
                }
                continue;
            }
            if (name === 'src' && tag === 'img') {
                if (SAFE_IMG.test(value.trim())) to.setAttribute('src', value.trim());
                continue;
            }
            if (name === 'style') continue;        // copied by property, below
            if (!KEEP_ATTRS.has(name)) continue;
            to.setAttribute(name, value);
        }
        copyStyle(from, to);
    }

    function build(node, out) {
        for (const child of Array.from(node.childNodes)) {
            if (child.nodeType === 3) {            // text
                out.appendChild(document.createTextNode(child.nodeValue));
                continue;
            }
            if (child.nodeType !== 1) continue;    // comments, PIs, ...
            const tag = child.tagName.toLowerCase();
            if (DROP_TAGS.has(tag)) continue;
            if (!KEEP_TAGS.has(tag)) {             // unknown: keep its text
                build(child, out);
                continue;
            }
            if (tag === 'img' && !SAFE_IMG.test((child.getAttribute('src') || '').trim())) {
                continue;                          // an image that would fetch, or nothing
            }
            const clean = document.createElement(tag);
            copyAttributes(child, clean, tag);
            build(child, clean);
            out.appendChild(clean);
        }
        return out;
    }

    /**
     * The stored HTML as a safe DocumentFragment of the live document.
     * @param {string} html
     * @returns {DocumentFragment}
     */
    function sanitize(html) {
        return build(parse(html).body, document.createDocumentFragment());
    }

    /**
     * Whether stored HTML has nothing worth showing. Uses the inert parse:
     * the old check put the string into a detached <div>, which still loads
     * an <img> -- the second time #548 saw a note's handler fire.
     * @param {string} html
     * @returns {boolean}
     */
    function isEmpty(html) {
        if (!html || !String(html).trim()) return true;
        const body = parse(html).body;
        if (body.textContent.trim()) return false;
        return !body.querySelector('img, table, .math-tex, hr');
    }

    global.WimiRichHtml = { sanitize: sanitize, isEmpty: isEmpty };
})(window);
