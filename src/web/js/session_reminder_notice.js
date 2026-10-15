/**
 * Dashboard reminder for planned sessions (#778 Wave 3, owner decision 7).
 *
 * The v1 reminder is this notice and nothing else: WIMI runs only while the
 * student runs it, so a desktop toast could not fire while it is closed, and
 * nothing here pretends otherwise. It shows the plans due TODAY and the plans
 * OVERDUE (dated before today and still planned; a missed plan stays planned
 * until the student acts, decision 3), once per profile per launch: Dismiss
 * is recorded on the bridge, not in a column (`dismissSessionReminders`).
 *
 * Self-initialising and additive, the assessment offer's shape: index.html
 * links this after landing.js, the markup ships `hidden`, and it is revealed
 * only once `getSessionReminders` has answered, so a failed read paints
 * nothing (#151). Built with textContent; the plan titles are the student's
 * own text.
 *
 * Days arrive as YYYY-MM-DD strings from the bridge and are shown as such;
 * no Date is built from them, so this module needs no LocalDate link.
 */
(function () {
    'use strict';

    function $(id) { return document.getElementById(id); }

    function label(plan) {
        return plan.title || plan.exam_name || 'a planned session';
    }

    function describe(rem) {
        const due = rem.due_today || [];
        const overdue = rem.overdue || [];
        const parts = [];
        if (due.length === 1) {
            parts.push('You planned ' + label(due[0]) + ' for today'
                + (due[0].planned_start_time ? ' at ' + due[0].planned_start_time : '') + '.');
        } else if (due.length > 1) {
            parts.push('You planned ' + due.length + ' sessions for today.');
        }
        if (overdue.length === 1) {
            parts.push('A session you planned for ' + overdue[0].planned_date + ' (' + label(overdue[0]) + ') has not happened yet.');
        } else if (overdue.length > 1) {
            parts.push(overdue.length + ' planned sessions are overdue; the oldest was for ' + overdue[0].planned_date + '.');
        }
        return parts.join(' ');
    }

    function startHref(plan) {
        // A series occurrence has no row yet; the calendar materialises it on
        // Start, so send the student there instead of to session setup.
        if (plan.id === null || plan.id === undefined) return 'calendar.html';
        const q = 'planned_id=' + encodeURIComponent(plan.id)
            + (plan.exam_context_id ? '&exam_id=' + encodeURIComponent(plan.exam_context_id) : '');
        return 'session_setup.html?' + q;
    }

    async function dismiss(box) {
        try {
            await api.dismissSessionReminders();
        } catch (err) {
            console.error('dismissSessionReminders failed:', err);
        }
        box.hidden = true;
    }

    async function load() {
        const box = $('session-reminder-notice');
        if (!box) return;
        let rem;
        try {
            await api.ready();
            rem = await api.getSessionReminders();
        } catch (err) {
            console.error('session reminders unavailable:', err);
            return;                          // stays hidden: nothing false is painted
        }
        if (!rem || rem.dismissed) return;
        const due = rem.due_today || [];
        const overdue = rem.overdue || [];
        if (!due.length && !overdue.length) return;

        $('session-reminder-text').textContent = describe(rem);
        const start = $('session-reminder-start');
        const first = due[0] || overdue[0];
        start.href = startHref(first);
        start.textContent = first.id === null || first.id === undefined ? 'Open calendar' : 'Start session';
        $('session-reminder-calendar').hidden = start.href.indexOf('calendar.html') !== -1;
        $('session-reminder-dismiss').addEventListener('click', function () { dismiss(box); }, { once: true });
        box.hidden = false;
    }

    // Exposed for scenarios and for a page that wants to re-check.
    window.loadSessionReminderNotice = load;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', load);
    } else {
        load();
    }
})();
