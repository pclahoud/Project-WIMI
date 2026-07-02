/**
 * WIMI Dropdown Keyboard Navigation Module
 * Phase 4 Stage 4 - Keyboard navigation for search dropdowns
 * 
 * Provides arrow key navigation, Enter to select, Escape to close,
 * and proper ARIA attributes for accessibility.
 */

// =========================================================================
// DropdownKeyboard Class
// =========================================================================

class DropdownKeyboard {
    /**
     * Create a keyboard navigation controller for a dropdown
     * @param {Object} options - Configuration options
     * @param {HTMLElement} options.input - The search input element
     * @param {HTMLElement} options.dropdown - The dropdown container element
     * @param {Function} options.onSelect - Callback when an item is selected (receives element)
     * @param {Function} [options.onClose] - Callback when dropdown is closed
     * @param {string} [options.itemSelector] - CSS selector for dropdown items
     */
    constructor(options) {
        this.input = options.input;
        this.dropdown = options.dropdown;
        this.onSelect = options.onSelect;
        this.onClose = options.onClose || (() => {});
        this.itemSelector = options.itemSelector || '.subject-option, .tag-option';
        
        this.selectedIndex = -1;
        this.isOpen = false;
        
        this._bindEvents();
        this._setupARIA();
    }
    
    /**
     * Set up ARIA attributes for accessibility
     */
    _setupARIA() {
        // Generate unique ID for the dropdown if not present
        if (!this.dropdown.id) {
            this.dropdown.id = `dropdown-${Math.random().toString(36).substr(2, 9)}`;
        }
        
        // Set up input ARIA attributes
        this.input.setAttribute('role', 'combobox');
        this.input.setAttribute('aria-autocomplete', 'list');
        this.input.setAttribute('aria-haspopup', 'listbox');
        this.input.setAttribute('aria-expanded', 'false');
        this.input.setAttribute('aria-controls', this.dropdown.id);
        
        // Set up dropdown ARIA attributes
        this.dropdown.setAttribute('role', 'listbox');
    }
    
    /**
     * Bind keyboard and other events
     */
    _bindEvents() {
        // Keyboard events on input
        this.input.addEventListener('keydown', (e) => this._handleKeydown(e));
        
        // Track dropdown visibility
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.attributeName === 'class') {
                    this.isOpen = this.dropdown.classList.contains('visible');
                    this.input.setAttribute('aria-expanded', this.isOpen ? 'true' : 'false');
                    
                    if (this.isOpen) {
                        this._updateItemARIA();
                        this.selectedIndex = -1; // Reset selection when dropdown opens
                    }
                }
            });
        });
        
        observer.observe(this.dropdown, { attributes: true });
        
        // Mouse hover should update selection
        this.dropdown.addEventListener('mouseover', (e) => {
            const item = e.target.closest(this.itemSelector);
            if (item) {
                const items = this._getItems();
                const index = Array.from(items).indexOf(item);
                if (index !== -1) {
                    this._setSelectedIndex(index, false); // Don't scroll on hover
                }
            }
        });
    }
    
    /**
     * Handle keydown events
     * @param {KeyboardEvent} e - The keyboard event
     */
    _handleKeydown(e) {
        const items = this._getItems();
        
        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                if (!this.isOpen) {
                    // If dropdown is closed, trigger search
                    if (this.input.value.length >= 2) {
                        this.input.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                } else {
                    // Navigate down
                    this._selectNext(items);
                }
                break;
                
            case 'ArrowUp':
                e.preventDefault();
                if (this.isOpen) {
                    this._selectPrev(items);
                }
                break;
                
            case 'Enter':
                if (this.isOpen && this.selectedIndex >= 0) {
                    e.preventDefault();
                    this._confirmSelection(items);
                }
                break;
                
            case 'Escape':
                if (this.isOpen) {
                    e.preventDefault();
                    this._closeDropdown();
                }
                break;
                
            case 'Tab':
                if (this.isOpen && this.selectedIndex >= 0) {
                    // Confirm selection and allow tab to proceed
                    this._confirmSelection(items);
                }
                break;
        }
    }
    
    /**
     * Get all selectable items in the dropdown
     * @returns {NodeList} List of item elements
     */
    _getItems() {
        return this.dropdown.querySelectorAll(this.itemSelector);
    }
    
    /**
     * Select the next item in the list
     * @param {NodeList} items - List of items
     */
    _selectNext(items) {
        if (items.length === 0) return;
        
        let newIndex = this.selectedIndex + 1;
        if (newIndex >= items.length) {
            newIndex = 0; // Wrap to beginning
        }
        
        this._setSelectedIndex(newIndex);
    }
    
    /**
     * Select the previous item in the list
     * @param {NodeList} items - List of items
     */
    _selectPrev(items) {
        if (items.length === 0) return;
        
        let newIndex = this.selectedIndex - 1;
        if (newIndex < 0) {
            newIndex = items.length - 1; // Wrap to end
        }
        
        this._setSelectedIndex(newIndex);
    }
    
    /**
     * Set the selected index and update visual state
     * @param {number} index - New selected index
     * @param {boolean} [scroll=true] - Whether to scroll item into view
     */
    _setSelectedIndex(index, scroll = true) {
        const items = this._getItems();
        
        // Remove selection from all items
        items.forEach((item, i) => {
            item.classList.remove('selected');
            item.setAttribute('aria-selected', 'false');
        });
        
        this.selectedIndex = index;
        
        // Add selection to new item
        if (index >= 0 && index < items.length) {
            const selectedItem = items[index];
            selectedItem.classList.add('selected');
            selectedItem.setAttribute('aria-selected', 'true');
            
            // Update aria-activedescendant on input
            if (selectedItem.id) {
                this.input.setAttribute('aria-activedescendant', selectedItem.id);
            }
            
            // Scroll into view if needed
            if (scroll) {
                this._scrollIntoView(selectedItem);
            }
        } else {
            this.input.removeAttribute('aria-activedescendant');
        }
    }
    
    /**
     * Scroll an item into view within the dropdown
     * @param {HTMLElement} item - The item to scroll into view
     */
    _scrollIntoView(item) {
        const dropdownRect = this.dropdown.getBoundingClientRect();
        const itemRect = item.getBoundingClientRect();
        
        if (itemRect.bottom > dropdownRect.bottom) {
            // Item is below visible area
            item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        } else if (itemRect.top < dropdownRect.top) {
            // Item is above visible area
            item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    }
    
    /**
     * Confirm the current selection
     * @param {NodeList} items - List of items
     */
    _confirmSelection(items) {
        if (this.selectedIndex >= 0 && this.selectedIndex < items.length) {
            const selectedItem = items[this.selectedIndex];
            
            // Call the onSelect callback
            if (this.onSelect) {
                this.onSelect(selectedItem);
            }
            
            // Simulate a click on the item (triggers existing onclick handlers)
            selectedItem.click();
        }
    }
    
    /**
     * Close the dropdown
     */
    _closeDropdown() {
        this.dropdown.classList.remove('visible');
        this.selectedIndex = -1;
        this.isOpen = false;
        this.input.setAttribute('aria-expanded', 'false');
        
        if (this.onClose) {
            this.onClose();
        }
    }
    
    /**
     * Update ARIA attributes on dropdown items
     */
    _updateItemARIA() {
        const items = this._getItems();
        items.forEach((item, index) => {
            // Generate ID if not present
            if (!item.id) {
                item.id = `${this.dropdown.id}-option-${index}`;
            }
            
            item.setAttribute('role', 'option');
            item.setAttribute('aria-selected', 'false');
        });
    }
    
    /**
     * Get the currently selected item
     * @returns {HTMLElement|null} The selected item or null
     */
    getSelectedItem() {
        const items = this._getItems();
        if (this.selectedIndex >= 0 && this.selectedIndex < items.length) {
            return items[this.selectedIndex];
        }
        return null;
    }
    
    /**
     * Manually set the selected index
     * @param {number} index - The index to select
     */
    setSelectedIndex(index) {
        this._setSelectedIndex(index);
    }
    
    /**
     * Reset the selection
     */
    resetSelection() {
        this._setSelectedIndex(-1);
    }
    
    /**
     * Destroy the keyboard controller and clean up
     */
    destroy() {
        // Remove ARIA attributes
        this.input.removeAttribute('role');
        this.input.removeAttribute('aria-autocomplete');
        this.input.removeAttribute('aria-haspopup');
        this.input.removeAttribute('aria-expanded');
        this.input.removeAttribute('aria-controls');
        this.input.removeAttribute('aria-activedescendant');
        
        this.dropdown.removeAttribute('role');
    }
}

// =========================================================================
// Global Instance & Helper
// =========================================================================

/**
 * Attach keyboard navigation to a search dropdown
 * @param {string} inputId - ID of the input element
 * @param {string} dropdownId - ID of the dropdown element
 * @param {Object} [options] - Additional options
 * @returns {DropdownKeyboard} The keyboard controller instance
 */
function attachDropdownKeyboard(inputId, dropdownId, options = {}) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    
    if (!input || !dropdown) {
        console.warn(`Could not attach keyboard nav: input=${inputId}, dropdown=${dropdownId}`);
        return null;
    }
    
    return new DropdownKeyboard({
        input,
        dropdown,
        onSelect: options.onSelect || null,
        onClose: options.onClose || null,
        itemSelector: options.itemSelector || '.subject-option, .tag-option'
    });
}

// Make available globally
window.DropdownKeyboard = DropdownKeyboard;
window.attachDropdownKeyboard = attachDropdownKeyboard;
