/**
 * WIMI Custom Select Component
 * Reusable custom dropdown select that replaces native <select> elements
 * Provides consistent styling across all pages
 */

class CustomSelect {
    /**
     * Create a custom select component
     * @param {HTMLElement} container - Container element for the custom select
     * @param {Object} options - Configuration options
     * @param {string} options.id - Unique ID for the select
     * @param {string} options.placeholder - Placeholder text when no option is selected
     * @param {Array} options.options - Array of {value, label} objects
     * @param {string} options.value - Initial selected value
     * @param {Function} options.onChange - Callback when selection changes
     */
    constructor(container, options = {}) {
        this.container = container;
        this.id = options.id || `custom-select-${Date.now()}`;
        this.placeholder = options.placeholder || 'Select an option...';
        this.options = options.options || [];
        this.value = options.value || '';
        this.onChange = options.onChange || null;
        this.isOpen = false;
        
        this.render();
        this.attachEventListeners();
    }
    
    render() {
        const selectedOption = this.options.find(opt => opt.value === this.value);
        const displayText = selectedOption ? selectedOption.label : this.placeholder;
        
        this.container.innerHTML = `
            <div class="custom-select" id="${this.id}" data-value="${this.value}">
                <div class="custom-select-trigger" tabindex="0" role="combobox" aria-haspopup="listbox" aria-expanded="false">
                    <span class="custom-select-value ${!selectedOption ? 'placeholder' : ''}">${displayText}</span>
                    <span class="custom-select-arrow">▾</span>
                </div>
                <div class="custom-select-options" role="listbox">
                    ${this.options.map((opt, index) => `
                        <div class="custom-select-option ${opt.value === this.value ? 'selected' : ''}" 
                             data-value="${opt.value}"
                             data-index="${index}"
                             role="option"
                             aria-selected="${opt.value === this.value}">
                            ${opt.label}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
        
        this.element = this.container.querySelector('.custom-select');
        this.trigger = this.container.querySelector('.custom-select-trigger');
        this.valueDisplay = this.container.querySelector('.custom-select-value');
        this.optionsContainer = this.container.querySelector('.custom-select-options');
    }
    
    attachEventListeners() {
        // Toggle dropdown on trigger click
        this.trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggle();
        });
        
        // Keyboard navigation
        this.trigger.addEventListener('keydown', (e) => {
            switch (e.key) {
                case 'Enter':
                case ' ':
                    e.preventDefault();
                    this.toggle();
                    break;
                case 'ArrowDown':
                    e.preventDefault();
                    if (!this.isOpen) {
                        this.open();
                    } else {
                        this.focusNextOption();
                    }
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    if (this.isOpen) {
                        this.focusPrevOption();
                    }
                    break;
                case 'Escape':
                    this.close();
                    break;
            }
        });
        
        // Handle option clicks
        this.optionsContainer.addEventListener('click', (e) => {
            const option = e.target.closest('.custom-select-option');
            if (option) {
                e.stopPropagation();
                this.selectOption(option.dataset.value);
            }
        });
        
        // Handle keyboard on options
        this.optionsContainer.addEventListener('keydown', (e) => {
            const option = e.target.closest('.custom-select-option');
            if (!option) return;
            
            switch (e.key) {
                case 'Enter':
                case ' ':
                    e.preventDefault();
                    this.selectOption(option.dataset.value);
                    break;
                case 'ArrowDown':
                    e.preventDefault();
                    this.focusNextOption();
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    this.focusPrevOption();
                    break;
                case 'Escape':
                    this.close();
                    this.trigger.focus();
                    break;
            }
        });
        
        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!this.element.contains(e.target)) {
                this.close();
            }
        });
    }
    
    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }
    
    open() {
        // Close other open selects
        document.querySelectorAll('.custom-select.open').forEach(select => {
            if (select !== this.element) {
                select.classList.remove('open');
            }
        });
        
        this.element.classList.add('open');
        this.trigger.setAttribute('aria-expanded', 'true');
        this.isOpen = true;
        
        // Focus the selected option or first option
        const selected = this.optionsContainer.querySelector('.custom-select-option.selected');
        if (selected) {
            selected.focus();
        } else {
            const first = this.optionsContainer.querySelector('.custom-select-option');
            if (first) first.focus();
        }
    }
    
    close() {
        this.element.classList.remove('open');
        this.trigger.setAttribute('aria-expanded', 'false');
        this.isOpen = false;
    }
    
    focusNextOption() {
        const options = Array.from(this.optionsContainer.querySelectorAll('.custom-select-option'));
        const current = document.activeElement;
        const currentIndex = options.indexOf(current);
        const nextIndex = currentIndex < options.length - 1 ? currentIndex + 1 : 0;
        options[nextIndex]?.focus();
    }
    
    focusPrevOption() {
        const options = Array.from(this.optionsContainer.querySelectorAll('.custom-select-option'));
        const current = document.activeElement;
        const currentIndex = options.indexOf(current);
        const prevIndex = currentIndex > 0 ? currentIndex - 1 : options.length - 1;
        options[prevIndex]?.focus();
    }
    
    selectOption(value) {
        const option = this.options.find(opt => String(opt.value) === String(value));
        if (!option) return;
        
        this.value = value;
        this.element.dataset.value = value;
        
        // Update visual state
        this.valueDisplay.textContent = option.label;
        this.valueDisplay.classList.remove('placeholder');
        
        // Update selected state on options
        this.optionsContainer.querySelectorAll('.custom-select-option').forEach(opt => {
            const isSelected = opt.dataset.value === String(value);
            opt.classList.toggle('selected', isSelected);
            opt.setAttribute('aria-selected', isSelected);
        });
        
        // Close dropdown
        this.close();
        this.trigger.focus();
        
        // Trigger callback
        if (this.onChange) {
            this.onChange(value, option);
        }
    }
    
    /**
     * Get current value
     * @returns {string} Current selected value
     */
    getValue() {
        return this.value;
    }
    
    /**
     * Set value programmatically
     * @param {string} value - Value to set
     * @param {boolean} triggerChange - Whether to trigger onChange callback
     */
    setValue(value, triggerChange = false) {
        const option = this.options.find(opt => String(opt.value) === String(value));
        
        this.value = value;
        this.element.dataset.value = value;
        
        if (option) {
            this.valueDisplay.textContent = option.label;
            this.valueDisplay.classList.remove('placeholder');
        } else {
            this.valueDisplay.textContent = this.placeholder;
            this.valueDisplay.classList.add('placeholder');
        }
        
        // Update selected state on options
        this.optionsContainer.querySelectorAll('.custom-select-option').forEach(opt => {
            const isSelected = opt.dataset.value === String(value);
            opt.classList.toggle('selected', isSelected);
            opt.setAttribute('aria-selected', isSelected);
        });
        
        if (triggerChange && this.onChange) {
            this.onChange(value, option);
        }
    }
    
    /**
     * Update options list
     * @param {Array} options - New options array
     * @param {boolean} keepValue - Whether to keep current value if still valid
     */
    setOptions(options, keepValue = true) {
        this.options = options;
        
        // Check if current value is still valid
        const currentValid = keepValue && this.options.some(opt => String(opt.value) === String(this.value));
        if (!currentValid) {
            this.value = '';
        }
        
        // Re-render options
        const selectedOption = this.options.find(opt => String(opt.value) === String(this.value));
        const displayText = selectedOption ? selectedOption.label : this.placeholder;
        
        this.valueDisplay.textContent = displayText;
        this.valueDisplay.classList.toggle('placeholder', !selectedOption);
        this.element.dataset.value = this.value;
        
        this.optionsContainer.innerHTML = this.options.map((opt, index) => `
            <div class="custom-select-option ${String(opt.value) === String(this.value) ? 'selected' : ''}" 
                 data-value="${opt.value}"
                 data-index="${index}"
                 role="option"
                 tabindex="-1"
                 aria-selected="${String(opt.value) === String(this.value)}">
                ${opt.label}
            </div>
        `).join('');
    }
    
    /**
     * Enable/disable the select
     * @param {boolean} disabled - Whether to disable
     */
    setDisabled(disabled) {
        if (disabled) {
            this.element.classList.add('disabled');
            this.trigger.setAttribute('tabindex', '-1');
        } else {
            this.element.classList.remove('disabled');
            this.trigger.setAttribute('tabindex', '0');
        }
    }
}

/**
 * Initialize all custom selects marked with data-custom-select attribute
 * Converts native <select> elements to custom selects
 */
function initCustomSelects() {
    document.querySelectorAll('select[data-custom-select]').forEach(select => {
        const container = document.createElement('div');
        container.className = 'custom-select-container';
        
        // Extract options from native select
        const options = Array.from(select.options).map(opt => ({
            value: opt.value,
            label: opt.textContent
        }));
        
        // Get configuration from data attributes
        const config = {
            id: select.id ? `custom-${select.id}` : undefined,
            placeholder: select.options[0]?.value === '' ? select.options[0].textContent : 'Select...',
            options: options.filter(opt => opt.value !== ''), // Remove empty placeholder from options
            value: select.value,
            onChange: (value) => {
                // Update the hidden native select for form submission
                select.value = value;
                select.dispatchEvent(new Event('change', { bubbles: true }));
            }
        };
        
        // Replace the native select
        select.style.display = 'none';
        select.parentNode.insertBefore(container, select.nextSibling);
        
        // Create custom select
        const customSelect = new CustomSelect(container, config);
        
        // Store reference on the native select
        select._customSelect = customSelect;
    });
}

// Make available globally
window.CustomSelect = CustomSelect;
window.initCustomSelects = initCustomSelects;
