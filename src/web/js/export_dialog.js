/**
 * WIMI Export Question IDs Dialog
 * Reusable modal for exporting question IDs with delimiter options.
 */

class ExportQuestionIdsDialog {
    static _cachedSaved = [];
    static _escHandler = null;

    /**
     * Show the export dialog with the given question IDs.
     * @param {string[]} questionIds - Array of question ID strings to display.
     * @param {Object} [options] - Optional configuration.
     * @param {number} [options.skippedCount=0] - Number of entries skipped (no question_id).
     * @param {string} [options.title='Export Question IDs'] - Dialog title.
     */
    static async show(questionIds, options = {}) {
        const {
            skippedCount = 0,
            title = 'Export Question IDs'
        } = options;

        // Preload saved delimiters from user database
        await ExportQuestionIdsDialog._refreshCache();

        // Remove any existing dialog
        ExportQuestionIdsDialog.close();

        // Build DOM
        const backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop active';
        backdrop.id = 'export-ids-modal';

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.maxWidth = '520px';

        // Title
        const titleEl = document.createElement('h3');
        titleEl.className = 'modal-title';
        titleEl.textContent = title;
        modal.appendChild(titleEl);

        // Delimiter options
        const delimGroup = document.createElement('div');
        delimGroup.className = 'export-delimiter-options';

        // Map symbolic keys to actual delimiter strings.
        const delimiterMap = {
            'newline': '\n',
            'comma': ', ',
        };

        const delimiterOptions = [
            { key: 'newline', label: 'Newline', id: 'delim-newline' },
            { key: 'comma', label: 'Comma', id: 'delim-comma' },
            { key: 'custom', label: 'Custom:', id: 'delim-custom' }
        ];

        let customInput = null;

        delimiterOptions.forEach((d, i) => {
            const label = document.createElement('label');
            label.className = 'export-delimiter-option';

            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = 'export-delimiter';
            radio.value = d.key;
            radio.id = d.id;
            if (i === 0) radio.checked = true;

            const text = document.createElement('span');
            text.textContent = d.label;

            label.appendChild(radio);
            label.appendChild(text);

            if (d.key === 'custom') {
                // Wrapper to hold input + saved button inline
                const customRow = document.createElement('div');
                customRow.className = 'export-custom-row';

                customInput = document.createElement('input');
                customInput.type = 'text';
                customInput.className = 'export-custom-delimiter';
                customInput.placeholder = '; or use {{qid}}';
                customInput.value = '; ';
                customInput.addEventListener('input', () => {
                    // Check for hotkey match
                    ExportQuestionIdsDialog._checkHotkey(customInput, updateOutput);
                    updateOutput();
                });

                const savedBtn = document.createElement('button');
                savedBtn.type = 'button';
                savedBtn.className = 'export-saved-btn';
                savedBtn.title = 'Saved delimiters';
                savedBtn.textContent = '\u2605'; // star
                savedBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    ExportQuestionIdsDialog._showSavedPopup(customInput, savedBtn, updateOutput);
                });

                customRow.appendChild(customInput);
                customRow.appendChild(savedBtn);
                label.appendChild(customRow);
            }

            radio.addEventListener('change', updateOutput);
            delimGroup.appendChild(label);
        });

        modal.appendChild(delimGroup);

        // Leading delimiter checkbox
        const leadingLabel = document.createElement('label');
        leadingLabel.className = 'export-delimiter-option';
        leadingLabel.style.marginBottom = '12px';
        const leadingCheckbox = document.createElement('input');
        leadingCheckbox.type = 'checkbox';
        leadingCheckbox.id = 'delim-leading';
        leadingCheckbox.addEventListener('change', updateOutput);
        const leadingText = document.createElement('span');
        leadingText.textContent = 'Add delimiter before first ID';
        leadingLabel.appendChild(leadingCheckbox);
        leadingLabel.appendChild(leadingText);
        modal.appendChild(leadingLabel);

        // Output textarea (editable so users can tweak before copying)
        const textarea = document.createElement('textarea');
        textarea.className = 'export-output';
        modal.appendChild(textarea);

        // Meta info
        const meta = document.createElement('div');
        meta.className = 'export-meta';
        meta.textContent = `${questionIds.length} question ID${questionIds.length !== 1 ? 's' : ''}`;
        modal.appendChild(meta);

        // Warning for skipped entries
        if (skippedCount > 0) {
            const warning = document.createElement('div');
            warning.className = 'export-warning';
            warning.textContent = `${skippedCount} entr${skippedCount !== 1 ? 'ies' : 'y'} skipped \u2014 no question ID`;
            modal.appendChild(warning);
        }

        // Actions
        const actions = document.createElement('div');
        actions.className = 'modal-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn btn-secondary';
        cancelBtn.textContent = 'Close';
        cancelBtn.addEventListener('click', () => ExportQuestionIdsDialog.close());

        const copyBtn = document.createElement('button');
        copyBtn.className = 'btn btn-primary export-copy-btn';
        copyBtn.textContent = 'Copy to Clipboard';
        copyBtn.addEventListener('click', () => {
            ExportQuestionIdsDialog._copyToClipboard(textarea, copyBtn);
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(copyBtn);
        modal.appendChild(actions);

        backdrop.appendChild(modal);
        document.body.appendChild(backdrop);
        document.body.style.overflow = 'hidden';

        // Close on backdrop click
        backdrop.addEventListener('click', (e) => {
            if (e.target === backdrop) {
                ExportQuestionIdsDialog.close();
            }
        });

        // Close on ESC
        ExportQuestionIdsDialog._escHandler = (e) => {
            if (e.key === 'Escape') {
                // Close saved popup first if open, otherwise close main dialog
                const savedPopup = document.getElementById('saved-delimiters-popup');
                if (savedPopup) {
                    savedPopup.remove();
                    return;
                }
                ExportQuestionIdsDialog.close();
            }
        };
        document.addEventListener('keydown', ExportQuestionIdsDialog._escHandler);

        // Build delimited output and update textarea.
        // Custom mode supports {{qid}} as a template placeholder.
        function updateOutput() {
            const selectedKey = modal.querySelector('input[name="export-delimiter"]:checked').value;

            if (selectedKey === 'custom') {
                const raw = customInput.value;
                if (raw.includes('{{qid}}')) {
                    textarea.value = questionIds
                        .map(id => raw.replace(/\{\{qid\}\}/g, id))
                        .join('\n');
                    return;
                }
                const delimiter = raw || ' ';
                const leading = leadingCheckbox.checked ? delimiter : '';
                textarea.value = leading + questionIds.join(delimiter);
            } else {
                const delimiter = delimiterMap[selectedKey];
                const leading = leadingCheckbox.checked ? delimiter : '';
                textarea.value = leading + questionIds.join(delimiter);
            }
        }
        updateOutput();
    }

    /**
     * Close and remove the export dialog from the DOM.
     */
    static close() {
        const existing = document.getElementById('export-ids-modal');
        if (existing) {
            existing.remove();
            document.body.style.overflow = '';
        }
        if (ExportQuestionIdsDialog._escHandler) {
            document.removeEventListener('keydown', ExportQuestionIdsDialog._escHandler);
            ExportQuestionIdsDialog._escHandler = null;
        }
    }

    // =========================================================================
    // Saved Delimiters (database-backed)
    // =========================================================================

    /**
     * Refresh the in-memory cache from the user database.
     */
    static async _refreshCache() {
        try {
            if (typeof api !== 'undefined' && api.getSavedDelimiters) {
                ExportQuestionIdsDialog._cachedSaved = await api.getSavedDelimiters() || [];
            }
        } catch (e) {
            console.warn('Failed to load saved delimiters:', e);
        }
    }

    /**
     * Return the cached saved delimiters (synchronous).
     */
    static _loadSaved() {
        return ExportQuestionIdsDialog._cachedSaved || [];
    }

    /**
     * Check if the custom input value ends with a saved hotkey.
     * If matched, replace the entire input value with the saved delimiter.
     */
    static _checkHotkey(customInput, updateOutput) {
        const val = customInput.value;
        const saved = ExportQuestionIdsDialog._loadSaved();

        for (const item of saved) {
            if (!item.hotkey) continue;
            if (val.endsWith(item.hotkey)) {
                customInput.value = item.value;
                // Move cursor to end
                customInput.setSelectionRange(item.value.length, item.value.length);
                updateOutput();
                return;
            }
        }
    }

    /**
     * Show the saved delimiters management popup anchored to the saved button.
     */
    static _showSavedPopup(customInput, anchorBtn, updateOutput) {
        // Remove existing popup
        const existing = document.getElementById('saved-delimiters-popup');
        if (existing) {
            existing.remove();
            return; // toggle off
        }

        const popup = document.createElement('div');
        popup.id = 'saved-delimiters-popup';
        popup.className = 'saved-delimiters-popup';

        // Stop clicks inside popup from propagating to backdrop
        popup.addEventListener('click', (e) => e.stopPropagation());

        const header = document.createElement('div');
        header.className = 'saved-delimiters-header';
        header.innerHTML = '<strong>Saved Delimiters</strong>';
        popup.appendChild(header);

        const list = document.createElement('div');
        list.className = 'saved-delimiters-list';
        popup.appendChild(list);

        function renderList() {
            const saved = ExportQuestionIdsDialog._loadSaved();
            list.innerHTML = '';

            if (saved.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'saved-delimiters-empty';
                empty.textContent = 'No saved delimiters yet.';
                list.appendChild(empty);
                return;
            }

            saved.forEach((item) => {
                const row = document.createElement('div');
                row.className = 'saved-delimiter-row';

                const info = document.createElement('div');
                info.className = 'saved-delimiter-info';

                const nameEl = document.createElement('span');
                nameEl.className = 'saved-delimiter-name';
                nameEl.textContent = item.name;
                nameEl.title = 'Click to use';

                const preview = document.createElement('span');
                preview.className = 'saved-delimiter-preview';
                const displayVal = item.value.length > 30
                    ? item.value.substring(0, 30) + '\u2026'
                    : item.value;
                preview.textContent = displayVal;

                info.appendChild(nameEl);
                if (item.hotkey) {
                    const hotkeyBadge = document.createElement('kbd');
                    hotkeyBadge.className = 'saved-delimiter-hotkey';
                    hotkeyBadge.textContent = item.hotkey;
                    hotkeyBadge.title = 'Type this in the custom box to auto-insert';
                    info.appendChild(hotkeyBadge);
                }
                info.appendChild(preview);

                // Use button
                const useBtn = document.createElement('button');
                useBtn.type = 'button';
                useBtn.className = 'saved-delimiter-use';
                useBtn.textContent = 'Use';
                useBtn.title = 'Insert into custom delimiter';
                useBtn.addEventListener('click', () => {
                    customInput.value = item.value;
                    // Select the custom radio
                    const customRadio = document.getElementById('delim-custom');
                    if (customRadio) customRadio.checked = true;
                    updateOutput();
                });

                // Delete button
                const delBtn = document.createElement('button');
                delBtn.type = 'button';
                delBtn.className = 'saved-delimiter-delete';
                delBtn.textContent = '\u00d7';
                delBtn.title = 'Delete';
                delBtn.addEventListener('click', async () => {
                    try {
                        await api.deleteSavedDelimiter(item.id);
                        await ExportQuestionIdsDialog._refreshCache();
                        renderList();
                    } catch (e) {
                        console.error('Failed to delete saved delimiter:', e);
                    }
                });

                row.appendChild(info);
                row.appendChild(useBtn);
                row.appendChild(delBtn);
                list.appendChild(row);
            });
        }

        renderList();

        // Add new form
        const addForm = document.createElement('div');
        addForm.className = 'saved-delimiters-add';

        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.placeholder = 'Name';
        nameInput.className = 'saved-add-name';

        const valueInput = document.createElement('input');
        valueInput.type = 'text';
        valueInput.placeholder = 'Value (e.g. ; or Q{{qid}})';
        valueInput.className = 'saved-add-value';

        const hotkeyInput = document.createElement('input');
        hotkeyInput.type = 'text';
        hotkeyInput.placeholder = 'Hotkey (e.g. /q)';
        hotkeyInput.className = 'saved-add-hotkey';

        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'btn btn-primary btn-sm saved-add-btn';
        addBtn.textContent = 'Save';
        addBtn.addEventListener('click', async () => {
            const name = nameInput.value.trim();
            const value = valueInput.value;
            const hotkey = hotkeyInput.value.trim();
            if (!name || !value) return;

            try {
                await api.createSavedDelimiter({ name, value, hotkey: hotkey || null });
                await ExportQuestionIdsDialog._refreshCache();

                nameInput.value = '';
                valueInput.value = '';
                hotkeyInput.value = '';
                renderList();
            } catch (e) {
                console.error('Failed to save delimiter:', e);
            }
        });

        addForm.appendChild(nameInput);
        addForm.appendChild(valueInput);
        addForm.appendChild(hotkeyInput);
        addForm.appendChild(addBtn);
        popup.appendChild(addForm);

        // Position relative to the anchor button
        anchorBtn.parentElement.style.position = 'relative';
        anchorBtn.parentElement.appendChild(popup);

        // Close popup on outside click (one-time)
        const closeOnOutside = (e) => {
            if (!popup.contains(e.target) && e.target !== anchorBtn) {
                popup.remove();
                document.removeEventListener('click', closeOnOutside, true);
            }
        };
        // Delay to avoid the current click closing it immediately
        setTimeout(() => {
            document.addEventListener('click', closeOnOutside, true);
        }, 0);
    }

    // =========================================================================
    // Clipboard
    // =========================================================================

    /**
     * Copy textarea content to clipboard.
     * Uses Qt bridge (primary) with web API and execCommand as fallbacks.
     */
    static async _copyToClipboard(textarea, button) {
        const text = textarea.value;
        let success = false;

        // Primary: use Qt bridge (works reliably in PyQt6 WebEngine)
        if (!success && typeof api !== 'undefined' && api.copyToClipboard) {
            try {
                await api.copyToClipboard(text);
                success = true;
            } catch (e) {
                // Bridge not available or failed
            }
        }

        // Fallback 1: modern Clipboard API (may be blocked on file:// protocol)
        if (!success && navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(text);
                success = true;
            } catch (e) {
                // Blocked
            }
        }

        // Fallback 2: execCommand
        if (!success) {
            try {
                textarea.select();
                textarea.setSelectionRange(0, textarea.value.length);
                success = document.execCommand('copy');
            } catch (e) {
                // Last resort: leave selected so user can Ctrl+C
                textarea.select();
                textarea.setSelectionRange(0, textarea.value.length);
            }
        }

        // Visual feedback
        const originalText = button.textContent;
        if (success) {
            button.textContent = 'Copied!';
            button.classList.add('copied');
        } else {
            button.textContent = 'Selected \u2014 press Ctrl+C';
        }

        setTimeout(() => {
            button.textContent = originalText;
            button.classList.remove('copied');
        }, 2000);
    }
}

// Make globally available
window.ExportQuestionIdsDialog = ExportQuestionIdsDialog;
