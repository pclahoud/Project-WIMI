# Entry Browser Bug Fixes & Improvements - Planning Document

## Overview
This document outlines the bugs and feature requests for the entry browser system, organized into actionable tasks with dependencies for delegation to sub-agents.

---

## Task Categories

### Category A: Search Functionality
### Category B: Subject Dropdown UX
### Category C: Card Display Issues
### Category D: Content Rendering
### Category E: Navigation Features

---

## Tasks

### TASK-001: Fix Multidimensional Search for Subjects
**Category:** A - Search Functionality  
**Priority:** High  
**Dependencies:** None

**Description:**  
When users search for queries in tests that are multidimensional using a subject from one of the dimensions (e.g., "bacterial endocarditis"), no entries appear in results even though entries are associated with that subject.

**Acceptance Criteria:**
- [ ] Search returns all entries associated with a subject, regardless of which dimension the subject belongs to
- [ ] Multidimensional test entries are properly indexed for all associated subjects
- [ ] Search results include entries where the search term matches any dimension's subject

---

### TASK-002: Fix Subject Dropdown Search Function
**Category:** B - Subject Dropdown UX  
**Priority:** High  
**Dependencies:** None

**Description:**  
The search/filter function within the subject dropdown does not respond to user input.

**Acceptance Criteria:**
- [ ] Typing in the dropdown search field filters the displayed subjects in real-time
- [ ] Search is case-insensitive
- [ ] Partial matches are supported

---

### TASK-003: Implement Collapsible Subject Hierarchy in Dropdown
**Category:** B - Subject Dropdown UX  
**Priority:** High  
**Dependencies:** None

**Description:**  
Parent subjects display all children fully extended by default, resulting in an extremely long list that makes it difficult to navigate to desired subjects.

**Implementation Approach:**

Implement collapsible tree nodes with expand/collapse state persisted to sessionStorage so users don't lose their place when navigating away and back.

**Behavior:**
- Parent subjects are collapsed by default on first visit
- Clicking a parent toggles its expanded/collapsed state
- Chevron icon indicates state (▶ collapsed, ▼ expanded)
- Expand/collapse state is saved to sessionStorage per exam context
- State is restored when user returns to the dropdown

**Files to Modify:**
- `src/web/js/entry_browser.js` - Update `renderSubjectList()` method
- `src/web/css/entry_browser.css` - Add tree node styling

---

**Implementation Details:**

**Step 1: Add state management methods to `EntryBrowser` class**

```javascript
/**
 * Get the sessionStorage key for subject tree state
 */
getSubjectTreeStateKey() {
    return `subjectTreeState_${this.examContextId || 'global'}`;
}

/**
 * Load expanded subject IDs from sessionStorage
 * @returns {Set<number>} Set of expanded subject IDs
 */
loadSubjectTreeState() {
    try {
        const stored = sessionStorage.getItem(this.getSubjectTreeStateKey());
        if (stored) {
            return new Set(JSON.parse(stored));
        }
    } catch (error) {
        console.warn('Failed to load subject tree state:', error);
    }
    return new Set();
}

/**
 * Save expanded subject IDs to sessionStorage
 * @param {Set<number>} expandedIds - Set of expanded subject IDs
 */
saveSubjectTreeState(expandedIds) {
    try {
        sessionStorage.setItem(
            this.getSubjectTreeStateKey(),
            JSON.stringify([...expandedIds])
        );
    } catch (error) {
        console.warn('Failed to save subject tree state:', error);
    }
}

/**
 * Toggle a subject node's expanded state
 * @param {number} subjectId - The subject ID to toggle
 */
toggleSubjectExpanded(subjectId) {
    if (this.expandedSubjectIds.has(subjectId)) {
        this.expandedSubjectIds.delete(subjectId);
    } else {
        this.expandedSubjectIds.add(subjectId);
    }
    this.saveSubjectTreeState(this.expandedSubjectIds);
    this.renderSubjectList();
}
```

**Step 2: Initialize state in constructor**

```javascript
constructor() {
    // ... existing state ...
    
    // Subject tree expand/collapse state
    this.expandedSubjectIds = new Set();
}
```

**Step 3: Load state in `loadSubjects()`**

```javascript
async loadSubjects() {
    if (!this.examContextId) return;
    
    try {
        this.subjects = await api.getSubjectsForFilter(this.examContextId);
        
        // Load saved expand/collapse state
        this.expandedSubjectIds = this.loadSubjectTreeState();
        
        this.renderSubjectList();
    } catch (error) {
        console.error('Failed to load subjects:', error);
    }
}
```

**Step 4: Update `renderSubjectList()` method**

```javascript
renderSubjectList() {
    const container = this.elements.subjectList;
    container.innerHTML = '';
    
    const renderNodes = (nodes, level = 0) => {
        nodes.forEach(node => {
            const hasChildren = node.children && node.children.length > 0;
            const isExpanded = this.expandedSubjectIds.has(node.id);
            
            // Create tree item container
            const item = document.createElement('div');
            item.className = 'subject-tree-item';
            item.style.paddingLeft = `${8 + level * 20}px`;
            
            // Add expand/collapse toggle for parents
            if (hasChildren) {
                const toggle = document.createElement('span');
                toggle.className = `tree-toggle ${isExpanded ? 'expanded' : ''}`;
                toggle.innerHTML = isExpanded ? '▼' : '▶';
                toggle.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.toggleSubjectExpanded(node.id);
                });
                item.appendChild(toggle);
            } else {
                // Spacer for leaf nodes to align with parents
                const spacer = document.createElement('span');
                spacer.className = 'tree-toggle-spacer';
                item.appendChild(spacer);
            }
            
            // Checkbox
            const label = document.createElement('label');
            label.className = 'subject-checkbox-label';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = node.id;
            checkbox.checked = this.filters.subjectIds.includes(node.id);
            
            const name = document.createElement('span');
            name.className = 'subject-name';
            name.textContent = node.name;
            
            label.appendChild(checkbox);
            label.appendChild(name);
            item.appendChild(label);
            
            container.appendChild(item);
            
            // Render children if expanded
            if (hasChildren && isExpanded) {
                renderNodes(node.children, level + 1);
            }
        });
    };
    
    renderNodes(this.subjects);
}
```

**Step 5: Add CSS to `src/web/css/entry_browser.css`**

```css
/* Subject Tree Styling */
.subject-tree-item {
    display: flex;
    align-items: center;
    padding: 6px 8px;
    gap: 4px;
}

.subject-tree-item:hover {
    background: var(--bg-hover, #f3f4f6);
}

.tree-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    font-size: 10px;
    color: var(--text-secondary, #6b7280);
    cursor: pointer;
    user-select: none;
    flex-shrink: 0;
    border-radius: 3px;
    transition: background 0.15s ease;
}

.tree-toggle:hover {
    background: var(--bg-tertiary, #e5e7eb);
    color: var(--text-primary, #1a1a1a);
}

.tree-toggle.expanded {
    color: var(--primary, #6366f1);
}

.tree-toggle-spacer {
    display: inline-block;
    width: 16px;
    flex-shrink: 0;
}

.subject-checkbox-label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    flex: 1;
}

.subject-checkbox-label input[type="checkbox"] {
    margin: 0;
    cursor: pointer;
}

.subject-name {
    font-size: 14px;
    color: var(--text-primary, #1a1a1a);
}
```

---

**Acceptance Criteria:**
- [ ] Parent subjects are collapsed by default on first visit
- [ ] Users can expand/collapse parent subjects to show/hide children
- [ ] Visual indicators (chevrons ▶/▼) show expand/collapse state
- [ ] Expand/collapse state is saved to sessionStorage
- [ ] State is restored when user returns to the page or reopens the dropdown
- [ ] State is scoped per exam context (different exams can have different states)
- [ ] Clicking the toggle does not affect the checkbox selection
- [ ] Leaf nodes (no children) align properly with parent nodes

**Testing:**
- [ ] Open subject dropdown → verify all parents are collapsed by default
- [ ] Expand a parent → verify children are shown and chevron changes to ▼
- [ ] Collapse a parent → verify children are hidden and chevron changes to ▶
- [ ] Expand several parents, navigate away, return → verify state is preserved
- [ ] Switch to different exam context → verify state is independent
- [ ] Select a child checkbox while parent is expanded → verify selection works
- [ ] Click toggle vs click checkbox → verify they are independent actions

---

### TASK-004: Display All Associated Subjects on Entry Cards
**Category:** C - Card Display Issues  
**Priority:** Medium  
**Dependencies:** None

**Description:**  
Entry cards only display one associated subject instead of all associated subjects and dimensions for that entry.

**Acceptance Criteria:**
- [ ] All associated subjects are displayed on entry cards
- [ ] All associated dimensions are displayed on entry cards
- [ ] Display format handles multiple subjects gracefully (consider truncation with "show more" for many associations)

---

### TASK-005: Render HTML Content Properly in Entry Details
**Category:** D - Content Rendering  
**Priority:** High  
**Dependencies:** None

**Description:**  
The reflection, explanation, and question notes sections display raw HTML instead of rendered content. Users should see the same formatted output they see in the TinyMCE editing boxes.

**Root Cause:**  
In `src/web/js/entry_detail.js`, the `renderContentSections()` method uses `.textContent` instead of `.innerHTML`, causing HTML tags to display as literal text.

**Implementation Approach: Option C - Shared RichContentRenderer Utility**

This approach creates a reusable utility class that:
- Renders HTML content consistently across the app
- Re-renders KaTeX math formulas from `data-formula` attributes
- Uses shared CSS that mirrors TinyMCE's `content_style`
- Can be reused in entry cards, tooltips, print views, etc.

**Files to Create:**

1. `src/web/js/rich_content_renderer.js` - Utility class
2. `src/web/css/rich_content.css` - Shared styles matching TinyMCE

**Files to Modify:**

1. `src/web/js/entry_detail.js` - Use RichContentRenderer
2. `src/web/html/entry_detail.html` - Add script/CSS imports

---

**Implementation Details:**

**Step 1: Create `src/web/js/rich_content_renderer.js`**

```javascript
/**
 * RichContentRenderer - Utility for rendering TinyMCE HTML content
 * 
 * Renders HTML content with consistent styling and KaTeX math support.
 * Mirrors TinyMCE's content_style for visual consistency between
 * editing and viewing modes.
 */
class RichContentRenderer {
    /**
     * Render HTML content into a container element
     * @param {HTMLElement} container - The DOM element to render into
     * @param {string} html - The HTML content to render
     * @param {Object} options - Optional configuration
     * @param {string} options.emptyMessage - Message to show when content is empty
     * @param {string} options.emptyClass - CSS class for empty state
     */
    static render(container, html, options = {}) {
        const {
            emptyMessage = 'No content provided',
            emptyClass = 'no-content'
        } = options;

        // Handle empty content
        if (!html || html.trim() === '' || html === '<p><br></p>') {
            container.classList.remove('rich-content');
            container.innerHTML = `<span class="${emptyClass}">${emptyMessage}</span>`;
            return;
        }

        // Add rich-content class for styling
        container.classList.add('rich-content');
        
        // Set the HTML content
        container.innerHTML = html;

        // Re-render KaTeX formulas
        RichContentRenderer.renderMathFormulas(container);
    }

    /**
     * Re-render all KaTeX math formulas in a container
     * @param {HTMLElement} container - Container with math elements
     */
    static renderMathFormulas(container) {
        if (typeof katex === 'undefined') {
            console.warn('[RichContentRenderer] KaTeX not available, math formulas will not render');
            return;
        }

        const mathElements = container.querySelectorAll('.math-tex[data-formula]');
        
        mathElements.forEach(el => {
            const formula = el.getAttribute('data-formula');
            if (!formula) return;

            try {
                // Clear existing content and re-render
                katex.render(formula, el, {
                    throwOnError: false,
                    displayMode: false
                });
            } catch (error) {
                console.warn('[RichContentRenderer] KaTeX render error:', error);
                // Keep the existing content as fallback
            }
        });
    }

    /**
     * Render content and return the HTML string (for cases where you need the string)
     * @param {string} html - The HTML content
     * @returns {string} - Processed HTML with rendered math
     */
    static process(html) {
        if (!html || html.trim() === '') {
            return '';
        }

        // Create temporary container
        const temp = document.createElement('div');
        temp.innerHTML = html;

        // Render math formulas
        RichContentRenderer.renderMathFormulas(temp);

        return temp.innerHTML;
    }
}

// Export for use in other modules
window.RichContentRenderer = RichContentRenderer;
```

---

**Step 2: Create `src/web/css/rich_content.css`**

```css
/**
 * Rich Content Display Styles
 * 
 * These styles mirror TinyMCE's content_style from rich_editor.js
 * to ensure visual consistency between editing and viewing modes.
 * 
 * Keep in sync with: src/web/js/rich_editor.js content_style
 */

.rich-content {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    color: #1a1a1a;
}

.rich-content p {
    margin: 0 0 1em 0;
}

.rich-content p:last-child {
    margin-bottom: 0;
}

.rich-content h1,
.rich-content h2,
.rich-content h3,
.rich-content h4,
.rich-content h5,
.rich-content h6 {
    margin: 1em 0 0.5em 0;
    font-weight: 600;
}

.rich-content h1 { font-size: 2em; }
.rich-content h2 { font-size: 1.5em; }
.rich-content h3 { font-size: 1.25em; }
.rich-content h4 { font-size: 1.1em; }
.rich-content h5 { font-size: 1em; }
.rich-content h6 { font-size: 0.9em; }

.rich-content ul,
.rich-content ol {
    margin: 0 0 1em 0;
    padding-left: 2em;
}

.rich-content li {
    margin-bottom: 0.25em;
}

.rich-content blockquote {
    margin: 1em 0;
    padding: 0.5em 1em;
    border-left: 4px solid #6366f1;
    background: #f8fafc;
    color: #475569;
}

.rich-content pre {
    background: #1e293b;
    color: #e2e8f0;
    padding: 1em;
    border-radius: 6px;
    overflow-x: auto;
    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
    font-size: 0.9em;
    margin: 1em 0;
}

.rich-content code {
    background: #f1f5f9;
    padding: 0.2em 0.4em;
    border-radius: 3px;
    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
    font-size: 0.9em;
}

.rich-content pre code {
    background: transparent;
    padding: 0;
}

.rich-content table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
}

.rich-content table td,
.rich-content table th {
    border: 1px solid #e2e8f0;
    padding: 8px 12px;
    text-align: left;
}

.rich-content table th {
    background: #f8fafc;
    font-weight: 600;
}

.rich-content table tr:hover td {
    background: #f8fafc;
}

.rich-content a {
    color: #6366f1;
    text-decoration: none;
}

.rich-content a:hover {
    text-decoration: underline;
}

.rich-content img {
    max-width: 100%;
    height: auto;
    border-radius: 4px;
}

/* Math formula styling */
.rich-content .math-tex {
    display: inline-block;
    padding: 2px 4px;
    background: #f8fafc;
    border-radius: 3px;
}

/* Empty state styling */
.no-content {
    color: var(--text-secondary, #6b7280);
    font-style: italic;
}
```

---

**Step 3: Modify `src/web/js/entry_detail.js`**

Replace the `renderContentSections()` method:

```javascript
renderContentSections() {
    // Reflection
    RichContentRenderer.render(
        this.elements.reflectionContent,
        this.entry.reflection,
        { emptyMessage: 'No reflection provided' }
    );

    // Explanation
    RichContentRenderer.render(
        this.elements.explanationContent,
        this.entry.explanation,
        { emptyMessage: 'No explanation provided' }
    );
}

renderNotes() {
    if (this.entry.notes) {
        RichContentRenderer.render(
            this.elements.notesContent,
            this.entry.notes,
            { emptyMessage: 'No notes added' }
        );
        this.elements.notesContent.style.display = 'block';
        this.elements.noNotes.style.display = 'none';
    } else {
        this.elements.notesContent.style.display = 'none';
        this.elements.noNotes.style.display = 'block';
    }
}
```

---

**Step 4: Update `src/web/html/entry_detail.html`**

Add imports in the `<head>` section:

```html
<!-- Rich Content Renderer Styles -->
<link rel="stylesheet" href="../css/rich_content.css">

<!-- KaTeX for math rendering (if not already included) -->
<link rel="stylesheet" href="../lib/katex/katex.min.css">
<script src="../lib/katex/katex.min.js"></script>
```

Add script before `entry_detail.js`:

```html
<!-- Rich Content Renderer (must load before entry_detail.js) -->
<script src="../js/rich_content_renderer.js"></script>
<script src="../js/entry_detail.js"></script>
```

---

**Acceptance Criteria:**
- [ ] HTML content in reflection section renders as formatted text
- [ ] HTML content in explanation section renders as formatted text
- [ ] HTML content in question notes section renders as formatted text
- [ ] Rendered output matches TinyMCE editor preview exactly
- [ ] KaTeX math formulas re-render correctly on the detail page
- [ ] Tables display with proper borders and styling
- [ ] Code blocks display with syntax-appropriate styling
- [ ] `RichContentRenderer` utility is reusable for future components
- [ ] CSS is extracted to shared file for maintainability

**Testing:**
- [ ] Create entry with bold, italic, underline text → verify renders correctly
- [ ] Create entry with bullet list and numbered list → verify renders correctly
- [ ] Create entry with table → verify table displays with borders
- [ ] Create entry with math formula (e.g., `E = mc^2`) → verify KaTeX renders
- [ ] Create entry with code block → verify monospace font and background
- [ ] Create entry with blockquote → verify indented with left border
- [ ] Create entry with link → verify clickable and styled
- [ ] View empty entry → verify "No content provided" message appears

---

### TASK-006: Implement Keyboard Navigation Between Entries
**Category:** E - Navigation Features  
**Priority:** Medium  
**Dependencies:** TASK-007

**Description:**  
Users should be able to navigate between entries using arrow keys (left/right or up/down).

**Implementation Approach: Hybrid Navigation (Wrap with Notification)**

Navigation wraps around continuously, but displays a brief toast notification when the user loops back to inform them of their position. This provides continuous flow while keeping users oriented.

**Behavior:**
- Left/Up arrow → Previous entry (wraps from first to last)
- Right/Down arrow → Next entry (wraps from last to first)
- When wrapping occurs, show toast: "Returned to first entry" or "Continued from last entry"
- Keyboard navigation only active when not focused on text inputs

**Files to Modify:**
- `src/web/js/entry_detail.js` - Add keyboard event listeners

**Implementation:**

Add to `setupEventListeners()` in `entry_detail.js`:

```javascript
// Keyboard navigation between entries
document.addEventListener('keydown', (e) => {
    // Don't navigate if user is typing in an input field
    const activeEl = document.activeElement;
    const isTyping = activeEl.tagName === 'INPUT' || 
                     activeEl.tagName === 'TEXTAREA' || 
                     activeEl.isContentEditable;
    
    if (isTyping) return;
    
    // Don't navigate if lightbox is open (lightbox has its own arrow key handling)
    if (this.elements.lightboxModal.classList.contains('active')) return;
    
    switch (e.key) {
        case 'ArrowLeft':
        case 'ArrowUp':
            e.preventDefault();
            this.navigateToPreviousEntry();
            break;
        case 'ArrowRight':
        case 'ArrowDown':
            e.preventDefault();
            this.navigateToNextEntry();
            break;
    }
});
```

**Acceptance Criteria:**
- [ ] Left/Up arrow key navigates to previous entry
- [ ] Right/Down arrow key navigates to next entry
- [ ] Navigation wraps around at boundaries
- [ ] Toast notification appears when wrapping occurs
- [ ] Keyboard shortcuts don't interfere with text input fields
- [ ] Keyboard shortcuts don't interfere with lightbox navigation
- [ ] Navigation maintains current filter/search context

---

### TASK-007: Add Navigation Buttons and State Management to Entry Detail
**Category:** E - Navigation Features  
**Priority:** Medium  
**Dependencies:** None

**Description:**  
Add previous/next buttons to the entry detail page and implement the navigation state management required for both button and keyboard navigation. Uses hybrid approach: navigation wraps around with toast notifications.

**Implementation Approach: Hybrid Navigation (Wrap with Notification)**

**Behavior:**
- Previous button → Go to previous entry (wraps from first to last)
- Next button → Go to next entry (wraps from last to first)  
- Position indicator shows current position (e.g., "3 of 12")
- Toast notification when wrapping: "Returned to first entry" / "Continued from last entry"

**Architecture:**

The entry detail page needs to know:
1. The list of entry IDs in the current filtered context
2. The current entry's position in that list

This data is passed via URL parameters from `entry_browser.js`.

**Files to Create:**
- `src/web/js/toast.js` - Reusable toast notification utility
- `src/web/css/toast.css` - Toast styling

**Files to Modify:**
- `src/web/js/entry_browser.js` - Pass navigation context when opening entry
- `src/web/js/entry_detail.js` - Add navigation buttons and logic
- `src/web/html/entry_detail.html` - Add button HTML and imports
- `src/web/css/entry_detail.css` - Button styling

---

**Implementation Details:**

**Step 1: Create `src/web/js/toast.js`**

```javascript
/**
 * Toast - Lightweight toast notification utility
 * 
 * Usage:
 *   Toast.show('Message here');
 *   Toast.show('Custom duration', { duration: 5000 });
 *   Toast.show('Info message', { type: 'info' });
 */
class Toast {
    static container = null;
    static defaultDuration = 2500;

    /**
     * Initialize the toast container (called automatically on first use)
     */
    static init() {
        if (Toast.container) return;

        Toast.container = document.createElement('div');
        Toast.container.className = 'toast-container';
        document.body.appendChild(Toast.container);
    }

    /**
     * Show a toast notification
     * @param {string} message - The message to display
     * @param {Object} options - Optional configuration
     * @param {number} options.duration - How long to show the toast (ms)
     * @param {string} options.type - Toast type: 'info' | 'success' | 'warning' | 'error'
     */
    static show(message, options = {}) {
        Toast.init();

        const {
            duration = Toast.defaultDuration,
            type = 'info'
        } = options;

        // Create toast element
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;

        // Add to container
        Toast.container.appendChild(toast);

        // Trigger animation
        requestAnimationFrame(() => {
            toast.classList.add('toast-visible');
        });

        // Remove after duration
        setTimeout(() => {
            toast.classList.remove('toast-visible');
            toast.classList.add('toast-hiding');
            
            // Remove from DOM after animation
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        }, duration);
    }
}

// Export for use in other modules
window.Toast = Toast;
```

---

**Step 2: Create `src/web/css/toast.css`**

```css
/**
 * Toast Notification Styles
 */

.toast-container {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10000;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    pointer-events: none;
}

.toast {
    background: #1e293b;
    color: #f8fafc;
    padding: 12px 20px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    opacity: 0;
    transform: translateY(16px);
    transition: opacity 0.2s ease, transform 0.2s ease;
    pointer-events: auto;
}

.toast-visible {
    opacity: 1;
    transform: translateY(0);
}

.toast-hiding {
    opacity: 0;
    transform: translateY(-8px);
}

/* Toast types */
.toast-info {
    background: #1e293b;
}

.toast-success {
    background: #166534;
}

.toast-warning {
    background: #a16207;
}

.toast-error {
    background: #b91c1c;
}
```

---

**Step 3: Modify `src/web/js/entry_browser.js`**

Update `navigateToEntry()` to pass navigation context:

```javascript
navigateToEntry(entryId) {
    // Build list of current entry IDs in display order
    const entryIds = this.entries.map(e => e.id);
    const currentIndex = entryIds.indexOf(entryId);
    
    // Encode the entry list for URL (for small lists)
    // For large lists, consider storing in sessionStorage instead
    const navContext = {
        ids: entryIds,
        index: currentIndex,
        total: this.totalEntries,
        examContextId: this.examContextId
    };
    
    // Store in sessionStorage for larger datasets
    sessionStorage.setItem('entryNavContext', JSON.stringify(navContext));
    
    window.location.href = `entry_detail.html?id=${entryId}&exam=${this.examContextId || ''}`;
}
```

---

**Step 4: Modify `src/web/js/entry_detail.js`**

Add navigation state and methods:

```javascript
class EntryDetail {
    constructor() {
        // ... existing state ...
        
        // Navigation state
        this.navContext = null;  // { ids: [], index: 0, total: 0, examContextId: null }
    }

    async init() {
        // ... existing init code ...
        
        // Load navigation context
        this.loadNavContext();
        
        // Update navigation UI
        this.updateNavigationUI();
    }

    loadNavContext() {
        try {
            const stored = sessionStorage.getItem('entryNavContext');
            if (stored) {
                this.navContext = JSON.parse(stored);
                
                // Verify current entry is in the list and update index
                const currentIndex = this.navContext.ids.indexOf(this.entryId);
                if (currentIndex !== -1) {
                    this.navContext.index = currentIndex;
                } else {
                    // Entry not in list (maybe filters changed), clear context
                    this.navContext = null;
                    sessionStorage.removeItem('entryNavContext');
                }
            }
        } catch (error) {
            console.warn('Failed to load navigation context:', error);
            this.navContext = null;
        }
    }

    updateNavigationUI() {
        const prevBtn = this.elements.prevEntryBtn;
        const nextBtn = this.elements.nextEntryBtn;
        const positionIndicator = this.elements.positionIndicator;

        if (!this.navContext || this.navContext.ids.length <= 1) {
            // Hide navigation if no context or only one entry
            if (prevBtn) prevBtn.style.display = 'none';
            if (nextBtn) nextBtn.style.display = 'none';
            if (positionIndicator) positionIndicator.style.display = 'none';
            return;
        }

        // Show navigation
        if (prevBtn) prevBtn.style.display = 'inline-flex';
        if (nextBtn) nextBtn.style.display = 'inline-flex';
        
        // Update position indicator
        if (positionIndicator) {
            positionIndicator.style.display = 'inline';
            positionIndicator.textContent = `${this.navContext.index + 1} of ${this.navContext.ids.length}`;
        }
    }

    navigateToPreviousEntry() {
        if (!this.navContext || this.navContext.ids.length <= 1) return;

        let newIndex = this.navContext.index - 1;
        let wrapped = false;

        // Wrap around to last entry
        if (newIndex < 0) {
            newIndex = this.navContext.ids.length - 1;
            wrapped = true;
        }

        this.navigateToEntryAtIndex(newIndex, wrapped ? 'Continued from last entry' : null);
    }

    navigateToNextEntry() {
        if (!this.navContext || this.navContext.ids.length <= 1) return;

        let newIndex = this.navContext.index + 1;
        let wrapped = false;

        // Wrap around to first entry
        if (newIndex >= this.navContext.ids.length) {
            newIndex = 0;
            wrapped = true;
        }

        this.navigateToEntryAtIndex(newIndex, wrapped ? 'Returned to first entry' : null);
    }

    navigateToEntryAtIndex(index, toastMessage = null) {
        // Update context
        this.navContext.index = index;
        sessionStorage.setItem('entryNavContext', JSON.stringify(this.navContext));

        // Show toast if wrapping
        if (toastMessage && typeof Toast !== 'undefined') {
            Toast.show(toastMessage, { duration: 2000, type: 'info' });
            
            // Delay navigation slightly so toast is visible
            setTimeout(() => {
                const entryId = this.navContext.ids[index];
                window.location.href = `entry_detail.html?id=${entryId}&exam=${this.navContext.examContextId || ''}`;
            }, 400);
        } else {
            const entryId = this.navContext.ids[index];
            window.location.href = `entry_detail.html?id=${entryId}&exam=${this.navContext.examContextId || ''}`;
        }
    }
}
```

Add to `setupEventListeners()`:

```javascript
// Navigation buttons
if (this.elements.prevEntryBtn) {
    this.elements.prevEntryBtn.addEventListener('click', () => {
        this.navigateToPreviousEntry();
    });
}

if (this.elements.nextEntryBtn) {
    this.elements.nextEntryBtn.addEventListener('click', () => {
        this.navigateToNextEntry();
    });
}
```

Add to `cacheElements()`:

```javascript
// Navigation elements
prevEntryBtn: document.getElementById('prev-entry-btn'),
nextEntryBtn: document.getElementById('next-entry-btn'),
positionIndicator: document.getElementById('position-indicator'),
```

---

**Step 5: Update `src/web/html/entry_detail.html`**

Add navigation buttons to header area:

```html
<!-- Add to header section, near the edit button -->
<div class="entry-navigation">
    <button id="prev-entry-btn" class="nav-btn" title="Previous entry (←)">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10 12L6 8L10 4"/>
        </svg>
        <span>Previous</span>
    </button>
    
    <span id="position-indicator" class="position-indicator">1 of 10</span>
    
    <button id="next-entry-btn" class="nav-btn" title="Next entry (→)">
        <span>Next</span>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M6 4L10 8L6 12"/>
        </svg>
    </button>
</div>

<!-- Add imports in head -->
<link rel="stylesheet" href="../css/toast.css">
<script src="../js/toast.js"></script>
```

---

**Step 6: Add styles to `src/web/css/entry_detail.css`**

```css
/* Entry Navigation */
.entry-navigation {
    display: flex;
    align-items: center;
    gap: 12px;
}

.nav-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    background: var(--bg-secondary, #f3f4f6);
    border: 1px solid var(--border-color, #e5e7eb);
    border-radius: 6px;
    color: var(--text-primary, #1a1a1a);
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
}

.nav-btn:hover {
    background: var(--bg-tertiary, #e5e7eb);
    border-color: var(--border-hover, #d1d5db);
}

.nav-btn:active {
    transform: scale(0.98);
}

.nav-btn svg {
    flex-shrink: 0;
}

.position-indicator {
    font-size: 14px;
    color: var(--text-secondary, #6b7280);
    min-width: 60px;
    text-align: center;
}

/* Hide navigation when not available */
.entry-navigation:empty {
    display: none;
}
```

---

**Acceptance Criteria:**
- [ ] Previous button navigates to previous entry
- [ ] Next button navigates to next entry
- [ ] Navigation wraps around at boundaries
- [ ] Toast notification "Returned to first entry" shows when wrapping forward
- [ ] Toast notification "Continued from last entry" shows when wrapping backward
- [ ] Position indicator shows "X of Y" format
- [ ] Navigation context persists across page loads (via sessionStorage)
- [ ] Navigation hidden when only one entry in context
- [ ] Navigation maintains filter/search context from entry browser

**Testing:**
- [ ] From entry browser with 5 filtered entries, click entry #3 → verify "3 of 5" shown
- [ ] Click Next repeatedly → verify wraps from 5 to 1 with toast
- [ ] Click Previous repeatedly → verify wraps from 1 to 5 with toast
- [ ] Use arrow keys → verify same behavior as buttons
- [ ] Open entry directly via URL (no context) → verify navigation hidden
- [ ] Change filters in browser, open entry → verify new context applied

---

### TASK-008: Verify/Implement Arrow Key Navigation for Attachments
**Category:** E - Navigation Features  
**Priority:** Low  
**Dependencies:** None

**Description:**  
Confirm whether attachments can be navigated using arrow keys. If not implemented, add this functionality.

**Acceptance Criteria:**
- [ ] Audit current attachment navigation behavior
- [ ] If not present: Left/Right arrow keys cycle through attachments
- [ ] Visual indicator shows current attachment position (e.g., 2/5)
- [ ] Navigation works for all attachment types (images, PDFs, etc.)

---

## Dependency Graph

```
TASK-001 (Search Fix)              [No dependencies]
TASK-002 (Dropdown Search)         [No dependencies]
TASK-003 (Collapsible Hierarchy)   [No dependencies]
TASK-004 (Card Subject Display)    [No dependencies]
TASK-005 (HTML Rendering)          [No dependencies]
TASK-006 (Keyboard Nav)            ──depends on──> TASK-007 (Nav Buttons)
TASK-007 (Nav Buttons)             [No dependencies]
TASK-008 (Attachment Nav)          [No dependencies]
```

---

## Suggested Execution Order

**Phase 1 - Critical Fixes (Parallel)**
- TASK-001: Fix Multidimensional Search
- TASK-002: Fix Subject Dropdown Search
- TASK-005: Render HTML Content Properly

**Phase 2 - UX Improvements (Parallel)**
- TASK-003: Implement Collapsible Subject Hierarchy
- TASK-004: Display All Associated Subjects

**Phase 3 - Navigation Features (Sequential)**
- TASK-007: Add Navigation Buttons (first)
- TASK-006: Implement Keyboard Navigation (after TASK-007)
- TASK-008: Verify/Implement Attachment Navigation

---

## Notes for Sub-Agents

1. **Before starting any task:** Review the existing codebase structure for the entry browser component
2. **TASK-003 implementation decided:** Collapsible hierarchy with sessionStorage persistence. Full implementation details including code are provided in the task description. Key changes:
   - Modify: `src/web/js/entry_browser.js` (add state management methods, update `renderSubjectList()`)
   - Modify: `src/web/css/entry_browser.css` (tree node styling)
   - State is scoped per exam context using key `subjectTreeState_{examContextId}`
3. **TASK-005 implementation decided:** Use the RichContentRenderer utility approach (Option C). Full implementation details including code are provided in the task description. Key files:
   - Create: `src/web/js/rich_content_renderer.js`
   - Create: `src/web/css/rich_content.css`
   - Modify: `src/web/js/entry_detail.js` (replace `renderContentSections()` and `renderNotes()`)
   - Modify: `src/web/html/entry_detail.html` (add imports)
4. **TASK-006 and TASK-007 implementation decided:** Use hybrid navigation (wrap with toast notification). Full implementation details including code are provided in the task descriptions. Key files:
   - Create: `src/web/js/toast.js` (reusable toast utility)
   - Create: `src/web/css/toast.css`
   - Modify: `src/web/js/entry_browser.js` (pass navigation context via sessionStorage)
   - Modify: `src/web/js/entry_detail.js` (add navigation state, buttons, keyboard handling)
   - Modify: `src/web/html/entry_detail.html` (add navigation button HTML)
   - Modify: `src/web/css/entry_detail.css` (button styling)
5. **Testing:** Each task should include unit tests and integration tests for the implemented functionality
6. **Style consistency:** The `rich_content.css` styles must stay in sync with TinyMCE's `content_style` in `src/web/js/rich_editor.js`
7. **Toast utility:** The Toast component created for TASK-007 is reusable across the app for other notifications
8. **sessionStorage usage:** Both TASK-003 and TASK-007 use sessionStorage for state persistence. Keys are scoped to avoid collisions:
   - TASK-003: `subjectTreeState_{examContextId}`
   - TASK-007: `entryNavContext`

