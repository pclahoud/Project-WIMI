/**
 * RichContentRenderer
 * A shared utility for rendering rich HTML content with math formula support
 *
 * Used in entry_detail.js and other views that display rich text content
 * created by the TinyMCE-based RichEditor.
 */

class RichContentRenderer {
    /**
     * Render HTML content into a container element
     * @param {HTMLElement} container - The DOM element to render into
     * @param {string} html - The HTML content to render
     * @param {Object} options - Configuration options
     * @param {string} options.emptyMessage - Message to show when content is empty (default: 'No content provided')
     * @param {string} options.emptyClass - CSS class for empty state (default: 'no-content')
     */
    static render(container, html, options = {}) {
        const { emptyMessage = 'No content provided', emptyClass = 'no-content' } = options;

        if (RichContentRenderer.isEmpty(html)) {
            container.classList.remove('rich-content');
            const empty = document.createElement('span');
            empty.className = emptyClass;
            empty.textContent = emptyMessage;
            container.replaceChildren(empty);
            return;
        }

        container.classList.add('rich-content');
        // Never `innerHTML = html` (#589). The stored string arrives from the
        // editor, but also from profile, .wimi and session imports, and an
        // <img onerror> in it ran here. WimiRichHtml keeps the formatting the
        // editor makes and builds it fresh; see rich_html.js.
        container.replaceChildren(WimiRichHtml.sanitize(html));

        RichContentRenderer.renderMathFormulas(container);
    }

    /**
     * Render KaTeX math formulas within a container
     * Looks for elements with class 'math-tex' and data-formula attribute
     * @param {HTMLElement} container - The container to search for math elements
     */
    static renderMathFormulas(container) {
        // Check if KaTeX is available
        if (typeof katex === 'undefined') {
            console.warn('[RichContentRenderer] KaTeX not available, math formulas will not be rendered');
            return;
        }

        // Find all math elements
        const mathElements = container.querySelectorAll('.math-tex[data-formula]');

        mathElements.forEach(el => {
            const formula = el.getAttribute('data-formula');
            if (!formula) return;

            try {
                // `trust` is left unset, so KaTeX's default (false) keeps
                // \href, \url and \includegraphics inert. data-formula is
                // stored text that WimiRichHtml passes through as-is, so
                // that default is what makes it safe: do not set trust:true.
                katex.render(formula, el, {
                    throwOnError: false,
                    displayMode: false
                });
            } catch (error) {
                console.warn('[RichContentRenderer] KaTeX render error:', error);
                // Leave the element as-is if rendering fails
            }
        });
    }

    /**
     * Check if content is considered empty.
     * @param {string} html - The HTML content to check
     * @returns {boolean} True if content is empty or effectively empty
     */
    static isEmpty(html) {
        // An inert parse (#589). This used to put the string into a detached
        // <div>, which still loads an <img> -- so a stored note's handler ran
        // here before render() was even called.
        return WimiRichHtml.isEmpty(html);
    }
}

// Export for use in other modules
window.RichContentRenderer = RichContentRenderer;
