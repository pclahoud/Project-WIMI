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

        // Check for empty content
        if (!html || html.trim() === '' || html === '<p><br></p>') {
            container.classList.remove('rich-content');
            container.innerHTML = `<span class="${emptyClass}">${emptyMessage}</span>`;
            return;
        }

        // Add rich-content class for styling
        container.classList.add('rich-content');

        // Set the HTML content
        container.innerHTML = html;

        // Render any math formulas
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
     * Check if content is considered empty
     * @param {string} html - The HTML content to check
     * @returns {boolean} True if content is empty or effectively empty
     */
    static isEmpty(html) {
        if (!html || html.trim() === '') return true;
        if (html === '<p><br></p>') return true;
        if (html === '<p></p>') return true;

        // Strip tags and check if any text content remains
        const temp = document.createElement('div');
        temp.innerHTML = html;
        const textContent = temp.textContent || temp.innerText || '';

        // Also check for meaningful elements (images, tables, math)
        const hasImages = html.includes('<img');
        const hasTables = html.includes('<table');
        const hasMath = html.includes('math-tex');

        return textContent.trim() === '' && !hasImages && !hasTables && !hasMath;
    }

    /**
     * Sanitize HTML content for safe rendering
     * This is a basic sanitizer - for production, consider using DOMPurify
     * @param {string} html - The HTML content to sanitize
     * @returns {string} Sanitized HTML
     */
    static sanitize(html) {
        if (!html) return '';

        // Remove script tags and event handlers
        const temp = document.createElement('div');
        temp.innerHTML = html;

        // Remove script elements
        const scripts = temp.querySelectorAll('script');
        scripts.forEach(script => script.remove());

        // Remove event handler attributes
        const allElements = temp.querySelectorAll('*');
        allElements.forEach(el => {
            const attrs = el.attributes;
            const toRemove = [];

            for (let i = 0; i < attrs.length; i++) {
                const name = attrs[i].name.toLowerCase();
                if (name.startsWith('on') || name === 'javascript') {
                    toRemove.push(attrs[i].name);
                }
            }

            toRemove.forEach(attr => el.removeAttribute(attr));
        });

        return temp.innerHTML;
    }
}

// Export for use in other modules
window.RichContentRenderer = RichContentRenderer;
