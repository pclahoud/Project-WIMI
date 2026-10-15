/**
 * Calendar page controller (#778 Wave 2).
 *
 * One month or week grid of real sessions (by the day they were studied) and
 * planned ones (by the day they are for), coloured by exam. Every day shown
 * or chosen is a LOCAL calendar day built with LocalDate (#286); nothing here
 * parses 'YYYY-MM-DD' with new Date() or formats with toISOString().
 *
 * Built with DOM nodes, not innerHTML: exam names, titles and notes are
 * student text (tests/test_web_escaping.py). Render is a pure function of
 * window.CalendarState; a range change loads once through getCalendarRange.
 *
 * Decisions encoded (owner 2026-10-12, #778): weeks start Monday and the
 * default view comes from calendar_default_view (8); an exam's chosen colour
 * paints its chips, falling back to four theme series slots (9); templates
 * fill the plan dialog (10); entry points live elsewhere (12); exam dates are
 * drawn as markers (13). Starting a plan hands session setup
 * `?exam_id=&planned_id=`, which prefills and links the new session back.
 *
 * Ships `inert` and releases the gate on every exit of init(), with a 15 s
 * fail-open (docs/guides/PAGE_GATE.md).
 */

/* On window on purpose: a top-level const is unreachable from a scenario's
 * eval_js (CLAUDE.md, Testing). */
window.CalendarState = {
    view: 'week',             // 'month' | 'week'
    showWeekends: true,
    anchor: null,             // YYYY-MM-DD, local; the day the view is built around
    rangeStart: null,
    rangeEnd: null,
    exams: [],                // [{id, exam_name, color_hex, series}]
    examFilter: null,         // exam id or null
    planned: [],              // from getCalendarRange
    sessions: [],
    examDates: [],
    byDay: new Map(),         // 'YYYY-MM-DD' -> {planned: [], sessions: [], examDates: []}
    templates: [],
    banks: [],                // question sources for the plan dialog
    selectedDay: null,
    focusedDay: null,
    isLoading: true,
    refocusAfterReload: false,
    error: null,
    editing: null,            // plan being edited in the dialog, or null
    removing: null,           // plan the Remove dialog is about, or null
};

(function () {
    'use strict';

    var state = window.CalendarState;
    var GATE_FAIL_OPEN_MS = 15000;
    var MAX_CHIPS_PER_DAY = 3;
    var SERIES_SLOTS = 4;
    var gateReleased = false;
    var el = {};

    function $(id) { return document.getElementById(id); }

    // ------------------------------------------------------------- gate

    function markCalendarReady(message) {
        if (gateReleased) return;
        gateReleased = true;
        state.isLoading = false;
        var page = document.querySelector('.calendar-page');
        if (page) page.removeAttribute('inert');
        try {
            if (typeof PageGate !== 'undefined') PageGate.release(message || 'Calendar ready.');
        } catch (err) {
            console.warn('PageGate.release failed; the page is released anyway:', err);
        }
    }

    // ------------------------------------------------------------- dates

    function addDays(iso, n) {
        var d = LocalDate.parse(iso);
        d.setDate(d.getDate() + n);
        return LocalDate.toISODate(d);
    }

    function mondayOf(iso) {
        var d = LocalDate.parse(iso);
        var back = (d.getDay() + 6) % 7;          // Monday = 0
        d.setDate(d.getDate() - back);
        return LocalDate.toISODate(d);
    }

    function monthStart(iso) {
        var d = LocalDate.parse(iso);
        return LocalDate.toISODate(new Date(d.getFullYear(), d.getMonth(), 1));
    }

    function monthEnd(iso) {
        var d = LocalDate.parse(iso);
        return LocalDate.toISODate(new Date(d.getFullYear(), d.getMonth() + 1, 0));
    }

    function shiftMonth(iso, n) {
        var d = LocalDate.parse(iso);
        return LocalDate.toISODate(new Date(d.getFullYear(), d.getMonth() + n, Math.min(d.getDate(), 28)));
    }

    var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
        'August', 'September', 'October', 'November', 'December'];
    var WEEKDAYS_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

    function longDate(iso) {
        var d = LocalDate.parse(iso);
        return WEEKDAYS_LONG[(d.getDay() + 6) % 7] + ', ' + d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear();
    }

    function shortDate(iso) {
        var d = LocalDate.parse(iso);
        return d.getDate() + ' ' + MONTHS[d.getMonth()].slice(0, 3);
    }

    /** The grid's first and last visible day, and the days to request. */
    function computeRange() {
        if (state.view === 'month') {
            var first = monthStart(state.anchor);
            var last = monthEnd(state.anchor);
            var gridStart = mondayOf(first);
            var gridEnd = addDays(mondayOf(last), 6);
            return { gridStart: gridStart, gridEnd: gridEnd, first: first, last: last };
        }
        var ws = mondayOf(state.anchor);
        return { gridStart: ws, gridEnd: addDays(ws, 6), first: ws, last: addDays(ws, 6) };
    }

    // ------------------------------------------------------------- colour

    function hexLuminance(hex) {
        if (typeof _wimiLuminance === 'function') return _wimiLuminance(hex);
        var parts = [hex.slice(1, 3), hex.slice(3, 5), hex.slice(5, 7)].map(function (h) {
            var s = parseInt(h, 16) / 255;
            return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
    }

    // The two mix ratios are the ones themes.js uses for --color-primary-bg
    // (#322): toward white on a light theme, toward black on a dark one.
    // Named constants and a helper that returns only them, because
    // tests/test_web_derived_colour.py resolves every ratio handed to the
    // mixer statically and refuses an expression it cannot tell from a
    // channel offset.
    function chipBgRatio() {
        // Declared inside the helper on purpose: the guard resolves a
        // helper's return values against constants in its OWN body.
        var CHIP_BG_LIGHT = 0.85;
        var CHIP_BG_DARK = -0.68;
        return pageIsDark() ? CHIP_BG_DARK : CHIP_BG_LIGHT;
    }

    function mixChannels(hex, r) {
        var channels = [hex.slice(1, 3), hex.slice(3, 5), hex.slice(5, 7)].map(function (h) {
            var c = parseInt(h, 16);
            return Math.round(r >= 0 ? c + (255 - c) * r : c * (1 + r));
        });
        return '#' + channels.map(function (c) { return c.toString(16).padStart(2, '0'); }).join('');
    }

    function mixTowardTheme(hex) {
        if (typeof _wimiMixColor === 'function') return _wimiMixColor(hex, chipBgRatio());
        return mixChannels(hex, chipBgRatio());
    }

    /** Is the current theme dark? Read off the painted page background. */
    function pageIsDark() {
        var bg = getComputedStyle(document.body).backgroundColor || '';
        var m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(bg);
        if (!m) return false;
        var hex = '#' + [m[1], m[2], m[3]].map(function (v) { return Number(v).toString(16).padStart(2, '0'); }).join('');
        return hexLuminance(hex) < 0.18;
    }

    /**
     * The chip's three colours from the exam's chosen colour: the border is
     * the colour itself, the fill is the colour mixed toward the page's own
     * background by luminance direction (#322's rule: light themes mix toward
     * white, dark ones toward black), and the text is black or white by the
     * fill's luminance. Written as custom properties so calendar.css paints
     * them; the student's hex never reaches a stylesheet literal.
     */
    function chipColours(hex) {
        var bg = mixTowardTheme(hex);
        var text = hexLuminance(bg) > 0.4 ? '#111111' : '#ffffff';
        return { bg: bg, border: hex, text: text };
    }

    function applyChipColour(node, exam) {
        if (exam && exam.color_hex && /^#[0-9a-f]{6}$/i.test(exam.color_hex)) {
            var c = chipColours(exam.color_hex.toLowerCase());
            node.style.setProperty('--cal-chip-bg', c.bg);
            node.style.setProperty('--cal-chip-border', c.border);
            node.style.setProperty('--cal-chip-text', c.text);
            node.setAttribute('data-coloured', 'exam');
        } else if (exam) {
            node.setAttribute('data-series', String(exam.series));
        } else {
            node.setAttribute('data-series', '0');
        }
    }

    // ------------------------------------------------------------- data

    function examById(id) {
        for (var i = 0; i < state.exams.length; i++) if (state.exams[i].id === id) return state.exams[i];
        return null;
    }

    function examName(id) {
        var ex = examById(id);
        return ex ? ex.exam_name : 'No exam';
    }

    function indexByDay() {
        var map = new Map();
        function bucket(day) {
            if (!map.has(day)) map.set(day, { planned: [], sessions: [], examDates: [] });
            return map.get(day);
        }
        state.planned.forEach(function (p) { bucket(p.planned_date).planned.push(p); });
        state.sessions.forEach(function (s) {
            var day = String(s.date_encountered).slice(0, 10);
            // A session that came from a plan is drawn once, from the plan.
            if (s.planned_session_id === null || s.planned_session_id === undefined) bucket(day).sessions.push(s);
        });
        state.examDates.forEach(function (e) { bucket(String(e.exam_date).slice(0, 10)).examDates.push(e); });
        state.byDay = map;
    }

    async function loadExams() {
        var exams = await api.getAllExamContexts(true);
        state.exams = (exams || []).map(function (ex, i) {
            return { id: ex.id, exam_name: ex.exam_name, color_hex: ex.color_hex || null,
                     exam_date: ex.exam_date || null, series: (i % SERIES_SLOTS) + 1 };
        });
    }

    async function loadRange() {
        var r = computeRange();
        state.rangeStart = r.gridStart;
        state.rangeEnd = r.gridEnd;
        var params = state.examFilter ? { exam_context_id: state.examFilter } : {};
        var data = await api.getCalendarRange(r.gridStart, r.gridEnd, params);
        state.planned = data.planned || [];
        state.sessions = data.sessions || [];
        state.examDates = data.exam_dates || [];
        indexByDay();
    }

    async function loadTemplates() {
        try {
            state.templates = await api.getSessionTemplates({});
        } catch (err) {
            console.warn('Templates could not be loaded:', err);
            state.templates = [];
        }
    }

    async function loadBanks(examId) {
        if (!examId) { state.banks = []; return; }
        try {
            var ex = examById(examId);
            var all = await api.getQuestionSources(ex ? ex.exam_name : '');
            state.banks = all || [];
        } catch (err) {
            console.warn('Question banks could not be loaded:', err);
            state.banks = [];
        }
    }

    // ------------------------------------------------------------- render

    function text(tag, content, className) {
        var n = document.createElement(tag);
        if (className) n.className = className;
        if (content !== undefined && content !== null) n.textContent = content;
        return n;
    }

    function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

    function renderRange() {
        var r = computeRange();
        var a = LocalDate.parse(state.anchor);
        if (state.view === 'month') {
            el.range.textContent = MONTHS[a.getMonth()] + ' ' + a.getFullYear();
        } else {
            el.range.textContent = 'Week of ' + shortDate(r.first) + ' to ' + shortDate(r.last) + ' ' + LocalDate.parse(r.last).getFullYear();
        }
        var monthRadio = $('cal-view-month'), weekRadio = $('cal-view-week');
        if (monthRadio) monthRadio.checked = state.view === 'month';
        if (weekRadio) weekRadio.checked = state.view === 'week';
    }

    function chipFor(item, kind) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'cal-event';
        btn.setAttribute('data-kind', kind);
        var exam = examById(item.exam_context_id);
        applyChipColour(btn, exam);
        var label = exam ? exam.exam_name : 'No exam';
        if (kind === 'planned') {
            btn.appendChild(text('span', 'Planned', 'cal-event-tag'));
            if (item.series_id !== null && item.series_id !== undefined) {
                btn.appendChild(text('span', 'weekly', 'cal-event-tag cal-event-series'));
            }
            if (item.status === 'started') btn.appendChild(text('span', 'started', 'cal-event-tag'));
            if (item.status === 'skipped') btn.appendChild(text('span', 'skipped', 'cal-event-tag'));
            btn.appendChild(text('span', label + (item.title ? ': ' + item.title : ''), 'cal-event-label'));
            if (item.planned_start_time) btn.appendChild(text('span', item.planned_start_time, 'cal-event-time'));
            btn.setAttribute('data-planned-id', item.id === null ? '' : String(item.id));
            if (item.series_id !== null && item.series_id !== undefined) btn.setAttribute('data-series-id', String(item.series_id));
        } else {
            btn.appendChild(text('span', label + (item.session_name ? ': ' + item.session_name : ''), 'cal-event-label'));
            btn.appendChild(text('span', item.total_incorrect + ' of ' + item.total_questions + ' missed', 'cal-event-time'));
            btn.setAttribute('data-session-id', String(item.id));
        }
        btn.setAttribute('data-date', kind === 'planned' ? item.planned_date : String(item.date_encountered).slice(0, 10));
        btn.addEventListener('click', function (evt) {
            evt.stopPropagation();
            selectDay(btn.getAttribute('data-date'), true);
        });
        return btn;
    }

    function renderGrid() {
        var r = computeRange();
        clear(el.gridBody);
        var today = LocalDate.today();
        var day = r.gridStart;
        var focusTarget = state.focusedDay && state.focusedDay >= r.gridStart && state.focusedDay <= r.gridEnd
            ? state.focusedDay : (today >= r.gridStart && today <= r.gridEnd ? today : r.first);
        state.focusedDay = focusTarget;
        var columns = state.showWeekends ? 7 : 5;
        document.querySelectorAll('.cal-grid th.cal-weekend').forEach(function (th) { th.hidden = !state.showWeekends; });
        while (day <= r.gridEnd) {
            var tr = document.createElement('tr');
            tr.setAttribute('role', 'row');
            for (var i = 0; i < 7; i++) {
                var td = document.createElement('td');
                td.setAttribute('role', 'gridcell');
                td.setAttribute('data-date', day);
                td.tabIndex = day === focusTarget ? 0 : -1;
                td.setAttribute('aria-selected', state.selectedDay === day ? 'true' : 'false');
                if (day === today) td.classList.add('cal-today');
                if (state.view === 'month' && (day < r.first || day > r.last)) td.classList.add('cal-outside');
                if (i >= 5) { td.classList.add('cal-weekend'); if (!state.showWeekends) td.hidden = true; }
                var d = LocalDate.parse(day);
                var num = text('span', String(d.getDate()), 'cal-day-number');
                td.appendChild(num);
                var bucket = state.byDay.get(day);
                if (bucket) {
                    bucket.examDates.forEach(function (e) {
                        var marker = text('span', 'Exam: ' + e.exam_name, 'cal-exam-date');
                        applyChipColour(marker, examById(e.exam_context_id));
                        td.appendChild(marker);
                    });
                    var list = document.createElement('ul');
                    list.className = 'cal-events';
                    var items = bucket.planned.map(function (p) { return { kind: 'planned', item: p }; })
                        .concat(bucket.sessions.map(function (s) { return { kind: 'past', item: s }; }));
                    items.slice(0, MAX_CHIPS_PER_DAY).forEach(function (x) {
                        var li = document.createElement('li');
                        li.appendChild(chipFor(x.item, x.kind));
                        list.appendChild(li);
                    });
                    if (items.length) td.appendChild(list);
                    if (items.length > MAX_CHIPS_PER_DAY) {
                        var more = document.createElement('button');
                        more.type = 'button';
                        more.className = 'cal-more';
                        more.textContent = '+' + (items.length - MAX_CHIPS_PER_DAY) + ' more';
                        more.setAttribute('data-date', day);
                        more.addEventListener('click', function (evt) {
                            evt.stopPropagation();
                            selectDay(more.getAttribute('data-date'), true);
                        });
                        td.appendChild(more);
                    }
                }
                td.setAttribute('aria-label', longDate(day) + (bucket ? ', ' + (bucket.planned.length + bucket.sessions.length) + ' items' : ''));
                td.addEventListener('click', onCellClick);
                td.addEventListener('keydown', onCellKeydown);
                tr.appendChild(td);
                day = addDays(day, 1);
            }
            el.gridBody.appendChild(tr);
        }
        el.grid.setAttribute('aria-colcount', String(columns));
    }

    function renderLegend() {
        clear(el.legendList);
        if (!state.exams.length) { el.legendEmpty.classList.remove('hidden'); return; }
        el.legendEmpty.classList.add('hidden');
        state.exams.forEach(function (ex) {
            var li = document.createElement('li');
            var swatch = text('span', '', 'cal-swatch');
            swatch.setAttribute('aria-hidden', 'true');
            applyChipColour(swatch, ex);
            li.appendChild(swatch);
            li.appendChild(text('span', ex.exam_name));
            el.legendList.appendChild(li);
        });
    }

    function renderExamFilter() {
        var current = state.examFilter;
        clear(el.examFilter);
        el.examFilter.appendChild(text('option', 'All exams')).value = '';
        state.exams.forEach(function (ex) {
            var o = text('option', ex.exam_name);
            o.value = String(ex.id);
            el.examFilter.appendChild(o);
        });
        el.examFilter.value = current ? String(current) : '';
    }

    function actionButton(label, className, handler) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn btn-sm ' + (className || 'btn-secondary');
        b.textContent = label;
        b.addEventListener('click', handler);
        return b;
    }

    function renderDayPanel() {
        if (!state.selectedDay) { el.dayPanel.hidden = true; return; }
        el.dayPanel.hidden = false;
        el.dayHeading.textContent = longDate(state.selectedDay);
        clear(el.dayList);
        var bucket = state.byDay.get(state.selectedDay) || { planned: [], sessions: [], examDates: [] };
        bucket.examDates.forEach(function (e) {
            var li = document.createElement('li');
            li.className = 'cal-day-item cal-day-exam-date';
            li.appendChild(text('strong', 'Exam day: ' + e.exam_name));
            el.dayList.appendChild(li);
        });
        bucket.planned.forEach(function (p) {
            var li = document.createElement('li');
            li.className = 'cal-day-item';
            li.setAttribute('data-planned-id', p.id === null ? '' : String(p.id));
            var head = text('div', '', 'cal-day-item-head');
            var chip = chipFor(p, 'planned');
            chip.disabled = true;
            head.appendChild(chip);
            li.appendChild(head);
            var meta = [];
            if (p.planned_start_time) meta.push('at ' + p.planned_start_time);
            if (p.planned_duration_minutes) meta.push(p.planned_duration_minutes + ' min');
            if (p.planned_questions) meta.push(p.planned_questions + ' questions');
            if (p.status !== 'planned') meta.push(p.status);
            if (meta.length) li.appendChild(text('p', meta.join(' · '), 'cal-day-meta'));
            if (p.notes) li.appendChild(text('p', p.notes, 'cal-day-notes'));
            var actions = text('div', '', 'cal-day-actions');
            if (p.status === 'planned') {
                actions.appendChild(actionButton('Start', 'btn-primary', function () { startPlan(p); }));
                actions.appendChild(actionButton('Edit', null, function () { openPlanDialog(p); }));
                actions.appendChild(actionButton('Skip', null, function () { markPlan(p, 'skipped'); }));
            } else if (p.status === 'started' && p.review_session_id) {
                var open = document.createElement('a');
                open.className = 'btn btn-sm btn-secondary';
                open.href = 'question_entry.html?session_id=' + encodeURIComponent(p.review_session_id);
                open.textContent = 'Open session';
                actions.appendChild(open);
            } else if (p.status === 'skipped' || p.status === 'cancelled') {
                actions.appendChild(actionButton('Plan again', null, function () { markPlan(p, 'planned'); }));
            }
            if (p.id !== null) actions.appendChild(actionButton('Remove', 'btn-danger-text', function () { openRemoveDialog(p); }));
            li.appendChild(actions);
            el.dayList.appendChild(li);
        });
        bucket.sessions.forEach(function (s) {
            var li = document.createElement('li');
            li.className = 'cal-day-item';
            var head = text('div', '', 'cal-day-item-head');
            var chip = chipFor(s, 'past');
            chip.disabled = true;
            head.appendChild(chip);
            li.appendChild(head);
            var actions = text('div', '', 'cal-day-actions');
            var open = document.createElement('a');
            open.className = 'btn btn-sm btn-secondary';
            open.href = 'question_entry.html?session_id=' + encodeURIComponent(s.id);
            open.textContent = 'Open session';
            actions.appendChild(open);
            li.appendChild(actions);
            el.dayList.appendChild(li);
        });
        var empty = !bucket.planned.length && !bucket.sessions.length && !bucket.examDates.length;
        el.dayEmpty.classList.toggle('hidden', !empty);
    }

    function render() {
        renderRange();
        renderGrid();
        renderLegend();
        renderDayPanel();
    }

    function showStatus(message) {
        el.status.textContent = message;
        el.status.classList.remove('hidden');
    }

    function showError(message) {
        state.error = message;
        el.errorText.textContent = message;
        el.error.classList.remove('hidden');
    }

    // ------------------------------------------------------------- interaction

    function selectDay(day, focusPanel) {
        state.selectedDay = day;
        state.focusedDay = day;
        renderGrid();
        renderDayPanel();
        if (focusPanel) el.dayHeading.focus();
    }

    function onCellClick(evt) {
        var td = evt.currentTarget;
        selectDay(td.getAttribute('data-date'), true);
    }

    function focusDay(day) {
        var r = computeRange();
        if (day < r.gridStart || day > r.gridEnd) {
            // Crossing the grid's edge reloads the range. renderGrid()
            // destroys the cell that held focus, so by the time reload()
            // looks, document.activeElement is <body> and its TD check would
            // leave the keyboard user nowhere (measured: ArrowLeft from a
            // Monday in week view). Remember the intent instead.
            state.anchor = day;
            state.focusedDay = day;
            state.refocusAfterReload = true;
            reload();
            return;
        }
        state.focusedDay = day;
        renderGrid();
        var cell = el.gridBody.querySelector('td[data-date="' + day + '"]');
        if (cell) cell.focus();
    }

    function onCellKeydown(evt) {
        var day = evt.currentTarget.getAttribute('data-date');
        var step = state.showWeekends ? 1 : null;
        switch (evt.key) {
            case 'ArrowRight': evt.preventDefault(); focusDay(nextVisible(day, 1)); break;
            case 'ArrowLeft': evt.preventDefault(); focusDay(nextVisible(day, -1)); break;
            case 'ArrowDown': evt.preventDefault(); focusDay(addDays(day, 7)); break;
            case 'ArrowUp': evt.preventDefault(); focusDay(addDays(day, -7)); break;
            case 'Home': evt.preventDefault(); focusDay(mondayOf(day)); break;
            case 'End': evt.preventDefault(); focusDay(addDays(mondayOf(day), state.showWeekends ? 6 : 4)); break;
            case 'PageDown': evt.preventDefault(); focusDay(state.view === 'month' ? shiftMonth(day, 1) : addDays(day, 7)); break;
            case 'PageUp': evt.preventDefault(); focusDay(state.view === 'month' ? shiftMonth(day, -1) : addDays(day, -7)); break;
            case 'Enter': case ' ': evt.preventDefault(); selectDay(day, true); break;
            default: void step;
        }
    }

    function nextVisible(day, dir) {
        var candidate = addDays(day, dir);
        if (!state.showWeekends) {
            var wd = (LocalDate.parse(candidate).getDay() + 6) % 7;
            if (wd >= 5) candidate = addDays(candidate, dir > 0 ? (7 - wd) : -(wd - 4));
        }
        return candidate;
    }

    async function reload() {
        try {
            await loadRange();
            render();
            var cell = el.gridBody.querySelector('td[data-date="' + state.focusedDay + '"]');
            var hadCellFocus = document.activeElement && document.activeElement.tagName === 'TD';
            if (cell && (hadCellFocus || state.refocusAfterReload)) cell.focus();
            state.refocusAfterReload = false;
        } catch (err) {
            showError('The calendar could not load this range: ' + (err && err.message ? err.message : err));
        }
    }

    function goPrev() {
        state.anchor = state.view === 'month' ? shiftMonth(state.anchor, -1) : addDays(state.anchor, -7);
        state.focusedDay = null;
        reload().then(function () { el.range.focus(); });
    }

    function goNext() {
        state.anchor = state.view === 'month' ? shiftMonth(state.anchor, 1) : addDays(state.anchor, 7);
        state.focusedDay = null;
        reload().then(function () { el.range.focus(); });
    }

    function goToday() {
        state.anchor = LocalDate.today();
        state.focusedDay = state.anchor;
        reload();
    }

    function onViewChange(evt) {
        state.view = evt.target.value === 'month' ? 'month' : 'week';
        reload();
    }

    function onFilterChange() {
        var v = el.examFilter.value;
        state.examFilter = v ? Number(v) : null;
        reload();
    }

    // ------------------------------------------------------------- plan dialog

    var planEls = {};

    function bindPlanDialog() {
        planEls.backdrop = $('cal-plan-modal');
        planEls.form = $('cal-plan-form');
        planEls.template = $('cal-plan-template');
        planEls.exam = $('cal-plan-exam');
        planEls.bank = $('cal-plan-bank');
        planEls.date = $('cal-plan-date');
        planEls.time = $('cal-plan-time');
        planEls.duration = $('cal-plan-duration');
        planEls.questions = $('cal-plan-questions');
        planEls.title = $('cal-plan-title-input');
        planEls.notes = $('cal-plan-notes');
        planEls.repeat = $('cal-plan-repeat');
        planEls.repeatFields = $('cal-repeat-fields');
        planEls.repeatEnd = $('cal-repeat-end');
        planEls.untilLabel = $('cal-repeat-until-label');
        planEls.until = $('cal-repeat-until');
        planEls.countLabel = $('cal-repeat-count-label');
        planEls.count = $('cal-repeat-count');
        planEls.error = $('cal-plan-error');
        planEls.cancel = $('cal-plan-cancel');
        planEls.titleHeading = $('cal-plan-title');

        planEls.cancel.addEventListener('click', closePlanDialog);
        planEls.form.addEventListener('submit', onPlanSubmit);
        planEls.repeat.addEventListener('change', function () {
            planEls.repeatFields.classList.toggle('hidden', !planEls.repeat.checked);
        });
        planEls.repeatEnd.addEventListener('change', function () {
            planEls.untilLabel.classList.toggle('hidden', planEls.repeatEnd.value !== 'until');
            planEls.countLabel.classList.toggle('hidden', planEls.repeatEnd.value !== 'count');
        });
        planEls.exam.addEventListener('change', function () {
            fillBanks(planEls.exam.value ? Number(planEls.exam.value) : null, null);
        });
        var saveTplBox = $('cal-plan-save-template');
        if (saveTplBox) {
            saveTplBox.addEventListener('change', function () {
                $('cal-plan-template-name-label').classList.toggle('hidden', !saveTplBox.checked);
                if (saveTplBox.checked) $('cal-plan-template-name').focus();
            });
        }
        planEls.template.addEventListener('change', function () {
            var t = state.templates.filter(function (x) { return String(x.id) === planEls.template.value; })[0];
            if (!t) return;
            planEls.exam.value = t.exam_context_id ? String(t.exam_context_id) : '';
            fillBanks(t.exam_context_id || null, t.question_source_id || null);
            if (t.default_start_time) planEls.time.value = t.default_start_time;
            if (t.default_duration_minutes) planEls.duration.value = String(t.default_duration_minutes);
            if (t.default_questions) planEls.questions.value = String(t.default_questions);
            if (!planEls.title.value) planEls.title.value = t.name;
        });
        planEls.backdrop.addEventListener('keydown', function (evt) {
            if (evt.key === 'Escape') { evt.preventDefault(); closePlanDialog(); }
        });
    }

    function fillSelect(select, firstLabel, rows, value, labelOf) {
        clear(select);
        var first = text('option', firstLabel);
        first.value = '';
        select.appendChild(first);
        rows.forEach(function (r) {
            var o = text('option', labelOf(r));
            o.value = String(r.id);
            select.appendChild(o);
        });
        select.value = value ? String(value) : '';
        if (select.value !== (value ? String(value) : '')) select.value = '';
    }

    async function fillBanks(examId, bankId) {
        await loadBanks(examId);
        fillSelect(planEls.bank, 'Any', state.banks, bankId, function (b) { return b.source_name; });
        planEls.bank.disabled = !examId;
    }

    function openPlanDialog(plan) {
        state.editing = plan || null;
        planEls.titleHeading.textContent = plan ? 'Edit plan' : 'Plan a session';
        planEls.error.classList.add('hidden');
        fillSelect(planEls.template, 'None', state.templates, null, function (t) { return t.name; });
        planEls.template.closest('.form-group').classList.toggle('hidden', !state.templates.length || !!plan);
        var saveGroup = $('cal-plan-save-template-group');
        if (saveGroup) {
            saveGroup.classList.toggle('hidden', !!plan);
            $('cal-plan-save-template').checked = false;
            $('cal-plan-template-name').value = '';
            $('cal-plan-template-name-label').classList.add('hidden');
        }
        fillSelect(planEls.exam, 'No exam', state.exams, plan ? plan.exam_context_id : state.examFilter, function (e) { return e.exam_name; });
        planEls.date.value = plan ? plan.planned_date : (state.selectedDay || LocalDate.today());
        planEls.time.value = plan && plan.planned_start_time ? plan.planned_start_time : '';
        planEls.duration.value = plan && plan.planned_duration_minutes ? String(plan.planned_duration_minutes) : '';
        if (plan && plan.planned_duration_minutes && planEls.duration.value !== String(plan.planned_duration_minutes)) planEls.duration.value = '';
        planEls.questions.value = plan && plan.planned_questions ? String(plan.planned_questions) : '';
        planEls.title.value = plan && plan.title ? plan.title : '';
        planEls.notes.value = plan && plan.notes ? plan.notes : '';
        planEls.repeat.checked = false;
        planEls.repeatFields.classList.add('hidden');
        planEls.repeat.closest('.form-group').classList.toggle('hidden', !!plan);
        planEls.repeatFields.querySelectorAll('input[type="checkbox"]').forEach(function (c) { c.checked = false; });
        planEls.repeatEnd.value = 'never';
        planEls.untilLabel.classList.add('hidden');
        planEls.countLabel.classList.add('hidden');
        planEls.until.value = '';
        planEls.count.value = '';
        fillBanks(plan ? plan.exam_context_id : state.examFilter, plan ? plan.question_source_id : null);
        planEls.backdrop.hidden = false;
        planEls.backdrop.classList.add('active');
        planEls.date.focus();
    }

    function closePlanDialog() {
        planEls.backdrop.classList.remove('active');
        planEls.backdrop.hidden = true;
        state.editing = null;
        el.planButton.focus();
    }

    function buildRrule() {
        if (!planEls.repeat.checked) return null;
        var days = Array.prototype.map.call(planEls.repeatFields.querySelectorAll('input[type="checkbox"]:checked'), function (c) { return c.value; });
        var rule = 'FREQ=WEEKLY';
        if (days.length) rule += ';BYDAY=' + days.join(',');
        if (planEls.repeatEnd.value === 'until' && planEls.until.value) rule += ';UNTIL=' + planEls.until.value.replace(/-/g, '');
        if (planEls.repeatEnd.value === 'count' && planEls.count.value) rule += ';COUNT=' + parseInt(planEls.count.value, 10);
        return rule;
    }

    async function onPlanSubmit(evt) {
        evt.preventDefault();
        planEls.error.classList.add('hidden');
        if (!planEls.date.value) {
            planEls.error.textContent = 'Choose a date.';
            planEls.error.classList.remove('hidden');
            return;
        }
        var payload = {
            planned_date: planEls.date.value,
            exam_context_id: planEls.exam.value ? Number(planEls.exam.value) : null,
            question_source_id: planEls.bank.value ? Number(planEls.bank.value) : null,
            planned_start_time: planEls.time.value || null,
            planned_duration_minutes: planEls.duration.value ? Number(planEls.duration.value) : null,
            planned_questions: planEls.questions.value ? Number(planEls.questions.value) : null,
            title: planEls.title.value.trim() || null,
            notes: planEls.notes.value.trim() || null,
        };
        try {
            if (state.editing) {
                await api.updatePlannedSession(state.editing.id, payload);
            } else {
                payload.recurrence_rule = buildRrule();
                if (planEls.template.value) payload.template_id = Number(planEls.template.value);
                var saveTpl = $('cal-plan-save-template');
                if (saveTpl && saveTpl.checked) {
                    var tplName = $('cal-plan-template-name').value.trim();
                    if (!tplName) {
                        planEls.error.textContent = 'Give the template a name, or untick "save as a template".';
                        planEls.error.classList.remove('hidden');
                        return;
                    }
                    await api.createSessionTemplate({
                        name: tplName,
                        exam_context_id: payload.exam_context_id,
                        question_source_id: payload.question_source_id,
                        default_start_time: payload.planned_start_time,
                        default_duration_minutes: payload.planned_duration_minutes,
                        default_questions: payload.planned_questions,
                    });
                    await loadTemplates();
                }
                await api.createPlannedSession(payload);
            }
            state.selectedDay = payload.planned_date;
            closePlanDialog();
            await reload();
            el.dayHeading.focus();
        } catch (err) {
            planEls.error.textContent = err && err.message ? err.message : String(err);
            planEls.error.classList.remove('hidden');
        }
    }

    // ------------------------------------------------------------- actions

    async function materialisedId(plan) {
        if (plan.id !== null && plan.id !== undefined) return plan.id;
        var child = await api.materialiseOccurrence(plan.series_id, plan.planned_date);
        return child.id;
    }

    async function startPlan(plan) {
        try {
            var id = await materialisedId(plan);
            var url = 'session_setup.html?planned_id=' + encodeURIComponent(id);
            if (plan.exam_context_id) url += '&exam_id=' + encodeURIComponent(plan.exam_context_id);
            window.location.href = url;
        } catch (err) {
            showError('The plan could not be started: ' + (err && err.message ? err.message : err));
        }
    }

    async function markPlan(plan, status) {
        try {
            var id = await materialisedId(plan);
            await api.setPlannedSessionStatus(id, status);
            await reload();
            el.dayHeading.focus();
        } catch (err) {
            showError('The plan could not be updated: ' + (err && err.message ? err.message : err));
        }
    }

    var removeEls = {};

    function bindRemoveDialog() {
        removeEls.backdrop = $('cal-remove-modal');
        removeEls.text = $('cal-remove-text');
        removeEls.cancel = $('cal-remove-cancel');
        removeEls.confirm = $('cal-remove-confirm');
        removeEls.cancel.addEventListener('click', closeRemoveDialog);
        removeEls.confirm.addEventListener('click', confirmRemove);
        removeEls.backdrop.addEventListener('keydown', function (evt) {
            if (evt.key === 'Escape') { evt.preventDefault(); closeRemoveDialog(); }
        });
    }

    function openRemoveDialog(plan) {
        state.removing = plan;
        var series = plan.series_id !== null && plan.series_id !== undefined;
        removeEls.text.textContent = series
            ? 'This removes only this occurrence from your calendar. The weekly series continues.'
            : (plan.is_series
                ? 'This removes the whole weekly series and every occurrence of it.'
                : 'The plan is removed from your calendar. A session you already started stays in your history.');
        removeEls.backdrop.hidden = false;
        removeEls.backdrop.classList.add('active');
        removeEls.confirm.focus();
    }

    function closeRemoveDialog() {
        removeEls.backdrop.classList.remove('active');
        removeEls.backdrop.hidden = true;
        state.removing = null;
        el.dayHeading.focus();
    }

    async function confirmRemove() {
        var plan = state.removing;
        if (!plan) return;
        try {
            if (plan.series_id !== null && plan.series_id !== undefined) {
                // An occurrence: cancelling it is the per-date removal; the series stays.
                var id = await materialisedId(plan);
                await api.setPlannedSessionStatus(id, 'cancelled');
            } else {
                await api.deletePlannedSession(plan.id);
            }
            closeRemoveDialog();
            await reload();
        } catch (err) {
            closeRemoveDialog();
            showError('The plan could not be removed: ' + (err && err.message ? err.message : err));
        }
    }

    async function exportIcs() {
        try {
            var picked = await api.openCalendarExportDialog({ default_filename: 'wimi-calendar.ics' });
            if (!picked || !picked.file_path) return;   // cancelled
            var params = { dest_path: picked.file_path };
            if (state.examFilter) params.exam_context_id = state.examFilter;
            var out = await api.exportCalendarIcs(params);
            showStatus('Exported ' + out.event_count + (out.event_count === 1 ? ' event' : ' events') + ' to ' + out.file_path);
        } catch (err) {
            showError('The export failed: ' + (err && err.message ? err.message : err));
        }
    }

    // ------------------------------------------------------------- init

    function bindElements() {
        el.range = $('cal-range');
        el.grid = $('cal-grid');
        el.gridBody = $('cal-grid-body');
        el.dayPanel = $('cal-day-panel');
        el.dayHeading = $('cal-day-heading');
        el.dayList = $('cal-day-list');
        el.dayEmpty = $('cal-day-empty');
        el.legendList = $('cal-legend-list');
        el.legendEmpty = $('cal-legend-empty');
        el.examFilter = $('cal-exam-filter');
        el.planButton = $('cal-plan');
        el.exportButton = $('cal-export');
        el.status = $('cal-status');
        el.error = $('cal-error');
        el.errorText = $('cal-error-text');
    }

    async function init() {
        bindElements();
        bindPlanDialog();
        bindRemoveDialog();
        var failOpen = setTimeout(function () {
            if (!gateReleased) {
                showError('The calendar did not load. You can go back to the dashboard and try again.');
                markCalendarReady('Calendar could not load.');
            }
        }, GATE_FAIL_OPEN_MS);
        try {
            state.anchor = LocalDate.today();
            try {
                var prefs = await api.getUserPreferences();
                state.view = prefs && prefs.calendar_default_view === 'month' ? 'month' : 'week';
                state.showWeekends = !(prefs && prefs.show_weekend_in_calendar === false);
            } catch (err) {
                console.warn('Preferences could not be read; using the week view:', err);
            }
            await loadExams();
            renderExamFilter();
            await loadTemplates();
            await loadRange();

            $('cal-prev').addEventListener('click', goPrev);
            $('cal-next').addEventListener('click', goNext);
            $('cal-today').addEventListener('click', goToday);
            $('cal-view-month').addEventListener('change', onViewChange);
            $('cal-view-week').addEventListener('change', onViewChange);
            el.examFilter.addEventListener('change', onFilterChange);
            el.planButton.addEventListener('click', function () { openPlanDialog(null); });
            el.exportButton.addEventListener('click', exportIcs);

            render();
            clearTimeout(failOpen);
            markCalendarReady('Calendar ready.');
            // The first-run tour (#430), after the grid is drawn because every
            // anchor on this page is in the markup or drawn by render(). Behind
            // a typeof check and a try, so a broken tour cannot break the page.
            try {
                if (typeof WimiTour !== 'undefined') WimiTour.start('calendar');
            } catch (err) {
                console.error('Tour failed to start:', err);
            }
        } catch (err) {
            clearTimeout(failOpen);
            showError('The calendar could not load: ' + (err && err.message ? err.message : err));
            markCalendarReady('Calendar could not load.');
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
