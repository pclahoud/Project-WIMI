/**
 * Rich Editor Component for WIMI
 * A reusable TinyMCE-based rich text editor with math, tables, and formatting support
 *
 * Dependencies (loaded via HTML):
 * - lib/tinymce/tinymce.min.js (core)
 * - lib/katex/katex.min.js, katex.min.css (math)
 *
 * Features:
 * - Rich text formatting (bold, italic, underline, strikethrough)
 * - Text color and background color (NEW - was missing in Quill)
 * - Headers (H1, H2, H3, H4, H5, H6)
 * - Lists (ordered and unordered)
 * - Blockquotes and code blocks
 * - Links
 * - Math equations via KaTeX
 * - Tables with full editing (built-in, no custom DOM manipulation needed)
 *
 * Keyboard Shortcuts:
 * - Ctrl+B: Bold
 * - Ctrl+I: Italic
 * - Ctrl+U: Underline
 * - Ctrl+K: Insert link
 * - Ctrl+Z: Undo
 * - Ctrl+Y: Redo
 */

class RichEditor {
    /**
     * Create a RichEditor instance
     * @param {HTMLElement|string} container - DOM element or selector for the editor container
     * @param {Object} options - Configuration options
     * @param {string} options.placeholder - Placeholder text when editor is empty
     * @param {Object|string} options.initialContent - Initial content (HTML string or legacy object)
     * @param {Function} options.onChange - Callback when content changes
     * @param {boolean} options.readOnly - Start in read-only mode (default: false)
     */
    constructor(container, options = {}) {
        // Resolve container element
        if (typeof container === 'string') {
            this.container = document.querySelector(container);
        } else {
            this.container = container;
        }

        if (!this.container) {
            throw new Error('RichEditor: Container element not found');
        }

        // Store options
        this.placeholder = options.placeholder || 'Enter text here...';
        this.initialContent = options.initialContent || null;
        this.onChange = options.onChange || null;
        this.readOnly = options.readOnly || false;

        // Editor state
        this.editor = null;
        this.isInitialized = false;
        this.editorId = 'tinymce-editor-' + this._generateId();
        this._pendingContent = null;  // Queue for content set before editor is ready

        // Initialize
        this._init();
    }

    /**
     * Initialize the editor
     */
    _init() {
        // Check for TinyMCE
        if (typeof tinymce === 'undefined') {
            console.error('RichEditor: TinyMCE library not loaded');
            this._showError('TinyMCE editor library not loaded. Please check script includes.');
            return;
        }

        // Create editor container structure
        this._createEditorStructure();

        // Initialize TinyMCE
        this._initTinyMCE();
    }

    /**
     * Create the editor DOM structure
     */
    _createEditorStructure() {
        // Add editor class to container
        this.container.classList.add('rich-editor-wrapper');

        // Create textarea for TinyMCE
        this.editorElement = document.createElement('textarea');
        this.editorElement.id = this.editorId;
        this.editorElement.className = 'rich-editor-textarea';

        // Clear and append
        this.container.innerHTML = '';
        this.container.appendChild(this.editorElement);
    }

    /**
     * Initialize TinyMCE editor
     */
    _initTinyMCE() {
        const self = this;

        tinymce.init({
            selector: '#' + this.editorId,
            base_url: '../lib/tinymce',
            license_key: 'gpl',

            // Plugins
            plugins: 'lists advlist table link code autolink searchreplace charmap',

            // Toolbar configuration
            toolbar: [
                'undo redo | blocks | bold italic underline strikethrough | forecolor backcolor',
                'bullist numlist | blockquote | link table | math | removeformat code'
            ].join(' | '),

            // Menu bar - disabled for cleaner UI
            menubar: false,

            // Status bar - disabled
            statusbar: false,

            // Content styling
            content_css: '../lib/katex/katex.min.css',
            content_style: `
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                    font-size: 15px;
                    line-height: 1.6;
                    color: #1a1a1a;
                    padding: 16px;
                    margin: 0;
                }
                p { margin: 0 0 1em 0; }
                h1, h2, h3, h4, h5, h6 { margin: 1em 0 0.5em 0; font-weight: 600; }
                h1 { font-size: 2em; }
                h2 { font-size: 1.5em; }
                h3 { font-size: 1.25em; }
                h4 { font-size: 1.1em; }
                h5 { font-size: 1em; }
                h6 { font-size: 0.9em; }
                ul, ol { margin: 0 0 1em 0; padding-left: 2em; }
                blockquote {
                    margin: 1em 0;
                    padding: 0.5em 1em;
                    border-left: 4px solid #6366f1;
                    background: #f8fafc;
                    color: #475569;
                }
                pre {
                    background: #1e293b;
                    color: #e2e8f0;
                    padding: 1em;
                    border-radius: 6px;
                    overflow-x: auto;
                    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
                    font-size: 0.9em;
                }
                code {
                    background: #f1f5f9;
                    padding: 0.2em 0.4em;
                    border-radius: 3px;
                    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
                    font-size: 0.9em;
                }
                table {
                    border-collapse: collapse;
                    width: 100%;
                    margin: 1em 0;
                }
                table td, table th {
                    border: 1px solid #e2e8f0;
                    padding: 8px 12px;
                    text-align: left;
                }
                table th {
                    background: #f8fafc;
                    font-weight: 600;
                }
                table tr:hover td {
                    background: #f8fafc;
                }
                a { color: #6366f1; text-decoration: none; }
                a:hover { text-decoration: underline; }
                .math-tex {
                    display: inline-block;
                    padding: 2px 4px;
                    background: #f8fafc;
                    border-radius: 3px;
                    cursor: pointer;
                }
                .math-tex:hover {
                    background: #e2e8f0;
                }
                img {
                    max-width: 100%;
                    height: auto;
                }
            `,

            // Block formats (heading dropdown)
            block_formats: 'Paragraph=p; Heading 1=h1; Heading 2=h2; Heading 3=h3; Heading 4=h4; Heading 5=h5; Heading 6=h6',

            // Table options
            table_responsive_width: true,
            table_default_attributes: {
                border: '1'
            },
            table_default_styles: {
                'border-collapse': 'collapse',
                'width': '100%'
            },

            // Ensure tables and all elements are valid (not stripped on load/save)
            valid_elements: '*[*]',  // Allow all elements and attributes
            extended_valid_elements: 'table[*],tbody[*],thead[*],tr[*],td[*],th[*],span[*],div[*]',
            valid_children: '+body[style|table],+table[tbody|thead|tr],+tr[td|th]',

            // Prevent HTML cleanup that might strip tables
            verify_html: false,
            cleanup: false,
            remove_trailing_brs: false,

            // Paste handling
            paste_data_images: true,
            paste_webkit_styles: 'none',
            paste_remove_styles_if_webkit: true,

            // Auto-resize
            min_height: 200,
            max_height: 500,
            autoresize_bottom_margin: 20,

            // Placeholder
            placeholder: this.placeholder,

            // Read-only mode
            readonly: this.readOnly,

            // Skin - use oxide for light mode
            skin: 'oxide',

            // Setup callback for custom buttons and events
            setup: (editor) => {
                self.editor = editor;

                // Register custom math button
                editor.ui.registry.addButton('math', {
                    icon: 'formula',
                    tooltip: 'Insert Math Equation (LaTeX)',
                    onAction: () => self._showMathDialog()
                });

                // Add formula icon if not present
                editor.ui.registry.addIcon('formula', '<svg width="24" height="24" viewBox="0 0 24 24"><path d="M7 2v2h1v14H7v2h6v-2h-1V4h1V2H7zm10 0v2h-1v14h1v2h-6v-2h1V4h-1V2h6z"/></svg>');

                // Handle content change
                editor.on('change', () => {
                    if (self.onChange) {
                        self.onChange();
                    }
                });

                editor.on('keyup', () => {
                    if (self.onChange) {
                        self.onChange();
                    }
                });

                // When editor is ready
                editor.on('init', () => {
                    console.log('[RichEditor] TinyMCE init event fired, editor is ready');
                    self.isInitialized = true;

                    // Set initial content if provided
                    if (self.initialContent) {
                        console.log('[RichEditor] Setting initial content');
                        self._setContentInternal(self.initialContent);
                    }

                    // Set any pending content that was queued before init
                    if (self._pendingContent !== null) {
                        console.log('[RichEditor] Setting pending content that was queued before init');
                        self._setContentInternal(self._pendingContent);
                        self._pendingContent = null;
                    }

                    // Apply theme colors to iframe content
                    self._updateContentTheme();

                    // Watch for theme changes on :root style attribute
                    self._themeObserver = new MutationObserver(() => {
                        self._updateContentTheme();
                    });
                    self._themeObserver.observe(document.documentElement, {
                        attributes: true,
                        attributeFilter: ['style']
                    });

                    // Handle math equation clicks for editing
                    editor.on('click', (e) => {
                        const mathEl = e.target.closest('.math-tex');
                        if (mathEl) {
                            const formula = mathEl.getAttribute('data-formula');
                            if (formula) {
                                self._showMathDialog(formula, mathEl);
                            }
                        }
                    });
                });
            }
        });
    }

    /**
     * Show math equation dialog
     * @param {string} existingFormula - Optional existing formula to edit
     * @param {HTMLElement} existingElement - Optional existing math element to replace
     */
    _showMathDialog(existingFormula = '', existingElement = null) {
        // Check if KaTeX is available
        if (typeof katex === 'undefined') {
            alert('Math rendering (KaTeX) is not available. Please check if the library is loaded.');
            return;
        }

        // Create modal dialog
        const modal = document.createElement('div');
        modal.className = 'rich-editor-math-modal';
        modal.innerHTML = `
            <div class="rich-editor-math-backdrop"></div>
            <div class="rich-editor-math-dialog">
                <div class="rich-editor-math-header">
                    <h4>${existingFormula ? 'Edit' : 'Insert'} Math Equation</h4>
                    <button type="button" class="rich-editor-math-close" aria-label="Close">&times;</button>
                </div>
                <div class="rich-editor-math-body">
                    <label for="latex-input">LaTeX Expression:</label>
                    <input type="text"
                           id="latex-input"
                           class="rich-editor-math-input"
                           placeholder="e.g., E = mc^2 or \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}"
                           value="${existingFormula.replace(/"/g, '&quot;')}"
                           autocomplete="off">
                    <div class="rich-editor-math-preview-label">Preview:</div>
                    <div class="rich-editor-math-preview"></div>
                    <div class="rich-editor-math-examples">
                        <span class="rich-editor-math-examples-label">Examples:</span>
                        <button type="button" data-latex="E = mc^2">E = mc^2</button>
                        <button type="button" data-latex="\\frac{a}{b}">Fraction</button>
                        <button type="button" data-latex="\\sqrt{x}">Square Root</button>
                        <button type="button" data-latex="x^{n}">Power</button>
                        <button type="button" data-latex="\\sum_{i=1}^{n}">Sum</button>
                        <button type="button" data-latex="\\int_{a}^{b}">Integral</button>
                    </div>
                </div>
                <div class="rich-editor-math-footer">
                    ${existingFormula ? '<button type="button" class="btn btn-danger btn-sm rich-editor-math-delete">Delete</button>' : ''}
                    <button type="button" class="btn btn-secondary btn-sm rich-editor-math-cancel">Cancel</button>
                    <button type="button" class="btn btn-primary btn-sm rich-editor-math-insert">${existingFormula ? 'Update' : 'Insert'}</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Get elements
        const input = modal.querySelector('.rich-editor-math-input');
        const preview = modal.querySelector('.rich-editor-math-preview');
        const insertBtn = modal.querySelector('.rich-editor-math-insert');
        const cancelBtn = modal.querySelector('.rich-editor-math-cancel');
        const deleteBtn = modal.querySelector('.rich-editor-math-delete');
        const closeBtn = modal.querySelector('.rich-editor-math-close');
        const backdrop = modal.querySelector('.rich-editor-math-backdrop');
        const exampleBtns = modal.querySelectorAll('.rich-editor-math-examples button');

        // Update preview
        const updatePreview = () => {
            const latex = input.value.trim();
            if (!latex) {
                preview.innerHTML = '<span class="placeholder">Enter LaTeX above to see preview</span>';
                return;
            }

            try {
                katex.render(latex, preview, {
                    throwOnError: false,
                    displayMode: true
                });
            } catch (e) {
                preview.innerHTML = `<span class="error">Invalid LaTeX: ${e.message}</span>`;
            }
        };

        // Initial preview
        if (existingFormula) {
            updatePreview();
        }

        // Close modal
        const closeModal = () => {
            modal.remove();
            this.editor.focus();
        };

        // Create math HTML element
        const createMathHtml = (latex) => {
            const container = document.createElement('span');
            container.className = 'math-tex';
            container.setAttribute('data-formula', latex);
            container.setAttribute('contenteditable', 'false');

            try {
                katex.render(latex, container, {
                    throwOnError: false,
                    displayMode: false
                });
            } catch (e) {
                container.textContent = latex;
            }

            return container.outerHTML;
        };

        // Insert/update formula
        const insertFormula = () => {
            const latex = input.value.trim();
            if (!latex) {
                input.focus();
                return;
            }

            const mathHtml = createMathHtml(latex);

            if (existingElement) {
                // Update existing element
                existingElement.outerHTML = mathHtml;
            } else {
                // Insert at cursor
                this.editor.insertContent(mathHtml + '&nbsp;');
            }

            closeModal();
        };

        // Delete formula
        const deleteFormula = () => {
            if (existingElement) {
                existingElement.remove();
            }
            closeModal();
        };

        // Event listeners
        input.addEventListener('input', updatePreview);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                insertFormula();
            }
            if (e.key === 'Escape') {
                closeModal();
            }
        });

        exampleBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                input.value = btn.dataset.latex;
                updatePreview();
                input.focus();
            });
        });

        insertBtn.addEventListener('click', insertFormula);
        cancelBtn.addEventListener('click', closeModal);
        if (deleteBtn) {
            deleteBtn.addEventListener('click', deleteFormula);
        }
        closeBtn.addEventListener('click', closeModal);
        backdrop.addEventListener('click', closeModal);

        // Focus input
        setTimeout(() => input.focus(), 100);
    }

    /**
     * Read current CSS variable values from the parent document
     * @returns {Object} Theme color values
     */
    _getThemeColors() {
        const cs = getComputedStyle(document.documentElement);
        const get = (name, fallback) => cs.getPropertyValue(name).trim() || fallback;
        return {
            textPrimary:   get('--text-primary', '#1a1a1a'),
            textSecondary: get('--text-secondary', '#475569'),
            textMuted:     get('--text-muted', '#64748b'),
            bgPrimary:     get('--bg-primary', '#ffffff'),
            bgSecondary:   get('--bg-secondary', '#f8fafc'),
            bgTertiary:    get('--bg-tertiary', '#f1f5f9'),
            borderColor:   get('--border-color', '#e2e8f0'),
            colorPrimary:  get('--color-primary', '#6366f1'),
        };
    }

    /**
     * Inject/update theme-aware styles into the TinyMCE iframe.
     * Called after init and whenever the parent theme changes.
     */
    _updateContentTheme() {
        if (!this.editor || !this.isInitialized) return;

        const doc = this.editor.getDoc();
        if (!doc) return;

        const c = this._getThemeColors();

        // Scale editor font size with global font size preference
        const scale = (window.wimiPreferences && window.wimiPreferences.font_size_scale)
            ? window.wimiPreferences.font_size_scale
            : 1.0;
        const baseFontSize = Math.round(15 * scale);

        const css = `
            body { color: ${c.textPrimary}; background: ${c.bgPrimary}; font-size: ${baseFontSize}px; }
            blockquote { background: ${c.bgSecondary}; color: ${c.textSecondary}; border-left-color: ${c.colorPrimary}; }
            code { background: ${c.bgTertiary}; }
            table td, table th { border-color: ${c.borderColor}; }
            table th { background: ${c.bgSecondary}; }
            table tr:hover td { background: ${c.bgSecondary}; }
            a { color: ${c.colorPrimary}; }
            .math-tex { background: ${c.bgSecondary}; }
            .math-tex:hover { background: ${c.bgTertiary}; }
        `;

        let styleEl = doc.getElementById('wimi-theme-override');
        if (!styleEl) {
            styleEl = doc.createElement('style');
            styleEl.id = 'wimi-theme-override';
            doc.head.appendChild(styleEl);
        }
        styleEl.textContent = css;
    }

    /**
     * Generate a unique ID
     */
    _generateId() {
        return Math.random().toString(36).substring(2, 9);
    }

    /**
     * Show an error message in the container
     */
    _showError(message) {
        this.container.innerHTML = `
            <div class="rich-editor-error">
                <span class="rich-editor-error-icon">!</span>
                <span class="rich-editor-error-message">${message}</span>
            </div>
        `;
    }

    // ========== Public Methods ==========

    /**
     * Get the editor content
     * @returns {Object} Content object with delta (null for TinyMCE) and html properties
     */
    getContent() {
        if (!this.editor || !this.isInitialized) {
            console.log('[RichEditor] getContent called but editor not ready, returning empty');
            return { delta: null, html: '' };
        }

        const html = this.editor.getContent();
        console.log('[RichEditor] getContent returning HTML length:', html.length);
        if (html.includes('<table')) {
            console.log('[RichEditor] getContent: content contains a table');
        }

        return {
            delta: null,  // TinyMCE doesn't use Delta format
            html: html
        };
    }

    /**
     * Set the editor content
     * @param {Object|string} content - HTML string, or object with html property, or legacy Quill Delta
     */
    setContent(content) {
        console.log('[RichEditor] setContent called, isInitialized:', this.isInitialized);

        // If editor isn't ready yet, queue the content for later
        if (!this.isInitialized) {
            console.log('[RichEditor] Editor not ready, queuing content for later');
            this._pendingContent = content;
            return;
        }

        this._setContentInternal(content);
    }

    /**
     * Internal method to actually set content (called when editor is ready)
     * @param {Object|string} content - HTML string, or object with html property, or legacy Quill Delta
     */
    _setContentInternal(content) {
        if (!this.editor) {
            console.warn('[RichEditor] _setContentInternal called but editor is null');
            return;
        }

        console.log('[RichEditor] _setContentInternal called with:', typeof content);

        let htmlContent = '';

        if (typeof content === 'string') {
            // HTML string - use directly
            htmlContent = content;
            console.log('[RichEditor] Content is HTML string, length:', content.length);
        } else if (content && content.html) {
            // Object with html property
            htmlContent = content.html;
            console.log('[RichEditor] Content has html property, length:', content.html.length);
        } else if (content && content.ops) {
            // Legacy Quill Delta format - attempt to extract text or use HTML fallback
            console.warn('[RichEditor] Quill Delta format detected. Using HTML fallback if available.');
            // If there's an html property in the parent, use that
            if (content.html) {
                htmlContent = content.html;
            } else {
                // Try to convert simple deltas (text only)
                htmlContent = this._convertDeltaToHtml(content);
            }
        } else if (content && content.delta && content.delta.ops) {
            // Object with delta property containing ops
            console.warn('[RichEditor] Legacy delta object detected. Using HTML if available.');
            if (content.html) {
                htmlContent = content.html;
            } else {
                htmlContent = this._convertDeltaToHtml(content.delta);
            }
        } else if (content === null || content === undefined) {
            // Clear content
            htmlContent = '';
        } else {
            console.warn('[RichEditor] _setContentInternal received unexpected content type:', content);
            return;
        }

        // Log if content contains a table for debugging
        if (htmlContent.includes('<table')) {
            console.log('[RichEditor] Content contains a table');
        }

        // Set the content
        console.log('[RichEditor] Calling editor.setContent with HTML length:', htmlContent.length);
        this.editor.setContent(htmlContent);

        // Verify the content was set and retry if tables were lost
        setTimeout(() => {
            const actualContent = this.editor.getContent();
            console.log('[RichEditor] Content verification - set length:', htmlContent.length, 'actual length:', actualContent.length);

            if (htmlContent.includes('<table') && !actualContent.includes('<table')) {
                console.error('[RichEditor] WARNING: Table was in input but not in output! Retrying...');
                // Try setting content again with a small delay
                setTimeout(() => {
                    console.log('[RichEditor] Retry: Setting content again');
                    this.editor.setContent(htmlContent);

                    // Final verification
                    setTimeout(() => {
                        const retryContent = this.editor.getContent();
                        if (retryContent.includes('<table')) {
                            console.log('[RichEditor] Retry successful: table is now present');
                        } else {
                            console.error('[RichEditor] Retry failed: table still missing after retry');
                            console.error('[RichEditor] Input HTML:', htmlContent.substring(0, 500));
                            console.error('[RichEditor] Output HTML:', retryContent.substring(0, 500));
                        }
                    }, 100);
                }, 100);
            }
        }, 100);
    }

    /**
     * Convert a simple Quill Delta to HTML (basic fallback)
     * @param {Object} delta - Quill Delta object with ops array
     * @returns {string} HTML string
     */
    _convertDeltaToHtml(delta) {
        if (!delta || !delta.ops) {
            return '';
        }

        let html = '';
        let currentParagraph = '';

        for (const op of delta.ops) {
            if (typeof op.insert === 'string') {
                // Text insert
                let text = op.insert;

                // Handle newlines
                if (text.includes('\n')) {
                    const parts = text.split('\n');
                    for (let i = 0; i < parts.length; i++) {
                        currentParagraph += this._escapeHtml(parts[i]);
                        if (i < parts.length - 1) {
                            // End of paragraph
                            if (currentParagraph.trim()) {
                                html += '<p>' + currentParagraph + '</p>';
                            } else {
                                html += '<p><br></p>';
                            }
                            currentParagraph = '';
                        }
                    }
                } else {
                    // Apply formatting if present
                    let formatted = this._escapeHtml(text);
                    if (op.attributes) {
                        if (op.attributes.bold) formatted = '<strong>' + formatted + '</strong>';
                        if (op.attributes.italic) formatted = '<em>' + formatted + '</em>';
                        if (op.attributes.underline) formatted = '<u>' + formatted + '</u>';
                        if (op.attributes.strike) formatted = '<s>' + formatted + '</s>';
                        if (op.attributes.link) formatted = '<a href="' + this._escapeHtml(op.attributes.link) + '">' + formatted + '</a>';
                    }
                    currentParagraph += formatted;
                }
            } else if (typeof op.insert === 'object') {
                // Embedded content (image, formula, etc.)
                if (op.insert.formula) {
                    // Math formula
                    const formula = op.insert.formula;
                    let mathHtml = '<span class="math-tex" data-formula="' + this._escapeHtml(formula) + '">';
                    if (typeof katex !== 'undefined') {
                        try {
                            const container = document.createElement('span');
                            katex.render(formula, container, { throwOnError: false });
                            mathHtml += container.innerHTML;
                        } catch (e) {
                            mathHtml += this._escapeHtml(formula);
                        }
                    } else {
                        mathHtml += this._escapeHtml(formula);
                    }
                    mathHtml += '</span>';
                    currentParagraph += mathHtml;
                } else if (op.insert.image) {
                    // Image
                    currentParagraph += '<img src="' + this._escapeHtml(op.insert.image) + '" alt="">';
                }
            }
        }

        // Flush remaining paragraph
        if (currentParagraph.trim()) {
            html += '<p>' + currentParagraph + '</p>';
        }

        return html || '<p><br></p>';
    }

    /**
     * Escape HTML special characters
     * @param {string} text - Text to escape
     * @returns {string} Escaped text
     */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Check if the editor is empty
     * @returns {boolean} True if editor has no meaningful content
     */
    isEmpty() {
        if (!this.editor || !this.isInitialized) return true;

        const content = this.editor.getContent({ format: 'text' }).trim();
        if (content.length === 0) {
            // Also check for embedded content (images, math, etc.)
            const html = this.editor.getContent();
            const hasImages = html.includes('<img');
            const hasMath = html.includes('math-tex');
            const hasTables = html.includes('<table');
            return !hasImages && !hasMath && !hasTables;
        }

        return false;
    }

    /**
     * Focus the editor
     */
    focus() {
        if (this.editor) {
            this.editor.focus();
        }
    }

    /**
     * Disable the editor (read-only mode)
     */
    disable() {
        if (this.editor) {
            this.editor.mode.set('readonly');
            this.container.classList.add('rich-editor-disabled');
        }
    }

    /**
     * Enable the editor
     */
    enable() {
        if (this.editor) {
            this.editor.mode.set('design');
            this.container.classList.remove('rich-editor-disabled');
        }
    }

    /**
     * Get the underlying TinyMCE instance
     * @returns {Object} The TinyMCE editor instance
     */
    getEditor() {
        return this.editor;
    }

    /**
     * Alias for getEditor (backward compatibility with Quill-based version)
     * @returns {Object} The editor instance
     * @deprecated Use getEditor() instead
     */
    getQuill() {
        console.warn('[RichEditor] getQuill() is deprecated. Use getEditor() instead.');
        return this.editor;
    }

    /**
     * Clear all content
     */
    clear() {
        if (this.editor && this.isInitialized) {
            this.editor.setContent('');
        } else {
            // Queue empty content if not initialized yet
            this._pendingContent = '';
        }
    }

    /**
     * Destroy the editor and clean up
     */
    destroy() {
        if (this._themeObserver) {
            this._themeObserver.disconnect();
            this._themeObserver = null;
        }
        if (this.editor) {
            this.editor.destroy();
            this.editor = null;
        }
        this.container.innerHTML = '';
        this.container.classList.remove('rich-editor-wrapper');
        this.isInitialized = false;
    }
}

// Export for use in other modules
window.RichEditor = RichEditor;
