/**
 * Settings -> Calendar: the session templates list (#778 Wave 4, decision 10).
 *
 * Self-initialising and additive, the self-assessment panel's shape:
 * settings.html links this after settings.js, and nothing here carries a
 * data-field. Templates are rows in session_templates, not preferences, so
 * they cannot ride the page's flat save and must not appear in the DEFAULTS
 * sweep (tests/test_settings_defaults_cover_the_page.py); archiving saves
 * itself through archiveSessionTemplate.
 *
 * Built with createElement/textContent: a template's name is the student's
 * own text.
 */
(function () {
    'use strict';

    function $(id) { return document.getElementById(id); }

    function text(tag, content, className) {
        const n = document.createElement(tag);
        if (className) n.className = className;
        n.textContent = content;
        return n;
    }

    function describe(t) {
        const bits = [];
        if (t.exam_name) bits.push(t.exam_name); else bits.push('Any exam');
        if (t.default_start_time) bits.push('at ' + t.default_start_time);
        if (t.default_duration_minutes) bits.push(t.default_duration_minutes + ' min');
        if (t.default_questions) bits.push(t.default_questions + ' questions');
        return bits.join(' · ');
    }

    async function examNames() {
        try {
            const exams = await api.getAllExamContexts(false);
            const map = {};
            (exams || []).forEach(function (e) { map[e.id] = e.exam_name; });
            return map;
        } catch (err) {
            return {};
        }
    }

    async function archive(t, row) {
        try {
            await api.archiveSessionTemplate(t.id);
            row.remove();
            if (!$('calendar-templates-list').children.length) $('calendar-templates-empty').hidden = false;
        } catch (err) {
            const e = $('calendar-templates-error');
            e.textContent = err && err.message ? err.message : String(err);
            e.hidden = false;
        }
    }

    async function refresh() {
        const list = $('calendar-templates-list');
        if (!list) return;
        let templates;
        try {
            await api.ready();
            templates = await api.getSessionTemplates({});
        } catch (err) {
            console.error('session templates unavailable:', err);
            const e = $('calendar-templates-error');
            e.textContent = 'The session templates could not be loaded.';
            e.hidden = false;
            return;
        }
        $('calendar-templates-error').hidden = true;
        const names = await examNames();
        while (list.firstChild) list.removeChild(list.firstChild);
        $('calendar-templates-empty').hidden = templates.length > 0;
        templates.forEach(function (t) {
            const li = document.createElement('li');
            li.setAttribute('data-template-id', String(t.id));
            const label = document.createElement('div');
            label.appendChild(text('strong', t.name));
            label.appendChild(text('div', describe(Object.assign({}, t, { exam_name: names[t.exam_context_id] })), 'calendar-template-meta'));
            li.appendChild(label);
            const btn = text('button', 'Archive', 'btn btn-secondary btn-sm');
            btn.type = 'button';
            btn.setAttribute('aria-label', 'Archive template ' + t.name);
            btn.addEventListener('click', function () { archive(t, li); });
            li.appendChild(btn);
            list.appendChild(li);
        });
    }

    // Exposed for scenarios and for a page that wants to re-check.
    window.loadCalendarTemplatesSettings = refresh;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', refresh);
    } else {
        refresh();
    }
})();
