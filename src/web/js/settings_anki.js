/**
 * Settings -> Anki Integration panel (#784 Wave 3).
 *
 * Self-initialising and additive, on settings_assessment.js's pattern:
 * settings.html links this after settings.js, and the panel's controls carry
 * NO data-field. Every control saves itself the moment it changes, so the
 * page's Save button never covers Anki, and the Anki keys are kept OUT of
 * SettingsPage.DEFAULTS so Reset what Save covers leaves them alone. The switch and the port go through updateUserPreferences, which
 * routes them to this computer's device_settings; the refresh and display
 * preferences go to user_preferences and travel with the profile.
 *
 * Everything is built from DOM nodes and textContent; no string from the
 * database or from Anki is ever parsed as HTML.
 *
 * Talking to Anki (Test connection, Fetch this exam's cards) goes through the
 * bridge's job slots, so a closed Anki costs a status line, never a frozen
 * window.
 */
(function () {
    'use strict';

    const PORT_MIN = 1000;
    const PORT_MAX = 65535;
    const MINUTES_MIN = 1;
    const MINUTES_MAX = 1440;

    let exams = [];
    // The port this computer has saved, which is the one every job dials.
    // The box may hold an unsaved or refused value (#802 review 3).
    let savedPort = 8765;

    function $(id) { return document.getElementById(id); }

    function el(tag, attrs, text) {
        const node = document.createElement(tag);
        Object.entries(attrs || {}).forEach(function (pair) {
            if (pair[0] === 'className') node.className = pair[1];
            else node.setAttribute(pair[0], pair[1]);
        });
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function say(id, message, isError) {
        const node = $(id);
        if (!node) return;
        node.textContent = message || '';
        node.classList.toggle('is-error', !!isError);
    }

    function showPanelError(message) {
        say('anki-settings-error', message, true);
        $('anki-settings-error').hidden = false;
    }

    function clearPanelError() {
        say('anki-settings-error', '');
        $('anki-settings-error').hidden = true;
    }

    function failure(err) {
        return err && err.message ? err.message : String(err);
    }

    /** What a failed job means to the student, by its kind. */
    function ankiProblem(err, port) {
        if (err && err.kind === 'unavailable') {
            return 'Nothing answered on port ' + port + '. Check that Anki is open and the '
                + 'AnkiConnect add-on is installed.';
        }
        if (err && err.kind === 'action_failed') {
            return 'Anki refused: ' + failure(err);
        }
        return 'Could not reach Anki: ' + failure(err);
    }

    // ------------------------------------------------------------ preferences

    async function save(fields, statusId) {
        try {
            await api.updateUserPreferences(fields);
            say(statusId, 'Saved.');
            return true;
        } catch (err) {
            say(statusId, 'Could not save: ' + failure(err), true);
            return false;
        }
    }

    function validInt(value, low, high) {
        const n = Number(value);
        return Number.isInteger(n) && n >= low && n <= high ? n : null;
    }

    function bindPreferences(prefs) {
        const enabled = $('anki-enabled');
        const port = $('anki-port');
        const auto = $('anki-auto-refresh');
        const minutes = $('anki-refresh-minutes');
        const mode = $('anki-display-mode');

        savedPort = prefs.ankiconnect_port || 8765;
        let savedMinutes = prefs.anki_cache_refresh_interval_minutes || 60;
        let savedMode = prefs.anki_display_mode === 'note' ? 'note' : 'card';
        enabled.checked = !!prefs.anki_integration_enabled;
        port.value = savedPort;
        auto.checked = prefs.anki_auto_refresh !== false;
        minutes.value = savedMinutes;
        minutes.disabled = !auto.checked;
        mode.value = savedMode;

        // A refused save puts the control back, so the page never shows a
        // state the database did not take (#802 review 5).
        enabled.addEventListener('change', async function () {
            if (!await save({anki_integration_enabled: enabled.checked}, 'anki-connection-status')) {
                enabled.checked = !enabled.checked;
            }
        });
        port.addEventListener('change', async function () {
            const n = validInt(port.value, PORT_MIN, PORT_MAX);
            if (n === null) {
                say('anki-connection-status',
                    'Choose a port from ' + PORT_MIN + ' to ' + PORT_MAX + '.', true);
                return;                       // nothing sent to the bridge
            }
            if (await save({ankiconnect_port: n}, 'anki-connection-status')) savedPort = n;
            else port.value = savedPort;
        });
        auto.addEventListener('change', async function () {
            minutes.disabled = !auto.checked;
            if (!await save({anki_auto_refresh: auto.checked}, 'anki-prefs-status')) {
                auto.checked = !auto.checked;
                minutes.disabled = !auto.checked;
            }
        });
        minutes.addEventListener('change', async function () {
            const n = validInt(minutes.value, MINUTES_MIN, MINUTES_MAX);
            if (n === null) {
                say('anki-prefs-status',
                    'Choose from ' + MINUTES_MIN + ' to ' + MINUTES_MAX + ' minutes.', true);
                return;
            }
            if (await save({anki_cache_refresh_interval_minutes: n}, 'anki-prefs-status')) {
                savedMinutes = n;
            } else {
                minutes.value = savedMinutes;
            }
        });
        mode.addEventListener('change', async function () {
            if (await save({anki_display_mode: mode.value}, 'anki-prefs-status')) savedMode = mode.value;
            else mode.value = savedMode;
        });
    }

    async function testConnection() {
        const n = validInt($('anki-port').value, PORT_MIN, PORT_MAX);
        if (n === null) {
            say('anki-connection-status', 'Choose a port from ' + PORT_MIN + ' to ' + PORT_MAX + '.', true);
            return;
        }
        const button = $('anki-test-connection');
        button.disabled = true;
        say('anki-connection-status', 'Asking Anki on port ' + n + '…');
        try {
            const result = await api.pingAnki(n);
            say('anki-connection-status',
                'Connected. AnkiConnect answered on port ' + n + ' (API version ' + result.version + ').');
        } catch (err) {
            say('anki-connection-status', ankiProblem(err, n), true);
        } finally {
            button.disabled = false;
        }
    }

    // -------------------------------------------------------------- templates

    function currentExam() {
        const id = Number($('anki-template-exam').value);
        return exams.find(function (e) { return e.id === id; }) || null;
    }

    async function renderTemplates() {
        const list = $('anki-template-list');
        list.replaceChildren();
        const exam = currentExam();
        const sync = $('anki-sync-exam');
        if (!exam) {
            list.appendChild(el('p', {className: 'field-description'},
                'Create an exam first; templates belong to an exam\'s question banks.'));
            sync.disabled = true;
            return;
        }
        let sources, templates;
        try {
            sources = await api.getQuestionSources(exam.exam_name);
            templates = await api.getAnkiTemplates(exam.id);
        } catch (err) {
            list.appendChild(el('p', {className: 'anki-settings-message is-error'},
                'The templates could not be loaded: ' + failure(err)));
            return;
        }
        if (!sources.length) {
            list.appendChild(el('p', {className: 'field-description'},
                'This exam has no question banks yet. Add one in Settings, Question Banks.'));
        }
        sources.forEach(function (source) {
            list.appendChild(bankBlock(exam, source,
                templates.filter(function (t) { return t.question_source_id === source.id; })));
        });
        sync.disabled = !templates.length;
    }

    function bankBlock(exam, source, templates) {
        const block = el('div', {className: 'anki-bank', 'data-source-id': String(source.id)});
        block.appendChild(el('h4', {className: 'anki-bank-name'}, source.source_name));
        const status = el('p', {className: 'anki-settings-message', role: 'status'});

        templates.forEach(function (t) {
            const row = el('div', {className: 'anki-inline-row anki-template-row'});
            const label = 'Search template for ' + source.source_name;
            const input = el('input', {type: 'text', className: 'anki-template-input',
                                       'aria-label': label, 'data-template-id': String(t.id)});
            input.value = t.template;
            const saveBtn = el('button', {type: 'button', className: 'btn btn-secondary btn-sm'},
                               'Save');
            const removeBtn = el('button', {type: 'button', className: 'btn btn-secondary btn-sm'},
                                 'Remove');
            saveBtn.addEventListener('click', async function () {
                try {
                    await api.updateAnkiTemplate(t.id, input.value);
                    status.textContent = 'Saved.';
                    status.classList.remove('is-error');
                } catch (err) {
                    status.textContent = failure(err);
                    status.classList.add('is-error');
                }
            });
            removeBtn.addEventListener('click', async function () {
                try {
                    await api.removeAnkiTemplate(t.id);
                    await renderTemplates();
                } catch (err) {
                    status.textContent = failure(err);
                    status.classList.add('is-error');
                }
            });
            row.append(input, saveBtn, removeBtn);
            block.appendChild(row);
        });

        const addRow = el('div', {className: 'anki-inline-row anki-template-row'});
        const addInput = el('input', {type: 'text', className: 'anki-template-input',
                                      'aria-label': 'New search template for ' + source.source_name,
                                      placeholder: 'tag:MyDeck::{{qid}}'});
        const addBtn = el('button', {type: 'button', className: 'btn btn-primary btn-sm'},
                          'Add template');
        async function add() {
            try {
                await api.addAnkiTemplate(exam.id, source.id, addInput.value);
                await renderTemplates();
            } catch (err) {
                status.textContent = failure(err);
                status.classList.add('is-error');
                addInput.focus();
            }
        }
        addBtn.addEventListener('click', add);
        addInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); add(); }
        });
        addRow.append(addInput, addBtn);
        block.append(addRow, status);
        return block;
    }

    async function syncExam() {
        const exam = currentExam();
        if (!exam) return;
        const button = $('anki-sync-exam');
        button.disabled = true;
        say('anki-sync-status', 'Fetching cards for ' + exam.exam_name + '…');
        try {
            const r = await api.syncAnkiExam(exam.id);
            let message = 'Fetched cards for ' + r.synced + ' of ' + r.questions + ' questions.';
            if (r.skipped.length) {
                message += ' ' + r.skipped.length + ' could not be searched: '
                    + r.skipped.map(function (s) { return s.question_id + ' (' + s.reason + ')'; })
                        .join('; ') + '.';
            }
            if (r.stopped) {
                message += ' Anki stopped answering part-way; the rest were left as they were.';
            }
            say('anki-sync-status', message, !!r.stopped);
            await renderFields();
        } catch (err) {
            say('anki-sync-status', ankiProblem(err, savedPort)
                + ' Nothing that was fetched before has changed.', true);
        } finally {
            button.disabled = false;
        }
    }

    // ------------------------------------------------------------------ fields

    async function renderFields() {
        const list = $('anki-field-list');
        list.replaceChildren();
        let settings;
        try {
            settings = await api.getAnkiFieldSettings();
        } catch (err) {
            list.appendChild(el('p', {className: 'anki-settings-message is-error'},
                'The card fields could not be loaded: ' + failure(err)));
            return;
        }
        if (!settings.note_types.length) {
            list.appendChild(el('p', {className: 'field-description'},
                'No cards have been fetched yet.'));
            return;
        }
        settings.note_types.forEach(function (type) {
            const set = el('fieldset', {className: 'anki-note-type'});
            set.appendChild(el('legend', {}, type.model_name));
            type.fields.forEach(function (field) {
                const label = el('label', {className: 'checkbox-label'});
                const box = el('input', {type: 'checkbox'});
                box.checked = !!field.visible;
                box.addEventListener('change', async function () {
                    try {
                        await api.setAnkiFieldVisibility(type.model_name, field.name, box.checked);
                        clearPanelError();     // #802 review 6: not sticky
                    } catch (err) {
                        box.checked = !box.checked;
                        showPanelError('Could not save: ' + failure(err));
                    }
                });
                label.append(box, el('span', {}, field.name));
                set.appendChild(label);
            });
            list.appendChild(set);
        });
    }

    // -------------------------------------------------------------------- init

    async function init() {
        if (!$('anki-settings')) return;
        try {
            await api.ready();
            const prefs = await api.getUserPreferences();
            bindPreferences(prefs);
            exams = await api.getAllExamContexts(true);
        } catch (err) {
            console.error('Anki settings unavailable:', err);
            showPanelError('The Anki settings could not be loaded.');
            return;
        }
        const select = $('anki-template-exam');
        exams.forEach(function (exam) {
            select.appendChild(el('option', {value: String(exam.id)}, exam.exam_name));
        });
        select.addEventListener('change', renderTemplates);
        $('anki-test-connection').addEventListener('click', testConnection);
        $('anki-sync-exam').addEventListener('click', syncExam);
        await renderTemplates();
        await renderFields();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
