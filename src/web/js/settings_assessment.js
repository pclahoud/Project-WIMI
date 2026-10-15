/**
 * Settings -> Self-assessment panel (#766 Wave 3, plan Stage 5).
 *
 * Self-initialising and additive: settings.html links this after settings.js
 * and the panel's controls carry NO data-field. That is deliberate. The
 * cadence lives in user_assessment_preferences, not user_preferences, so it
 * cannot ride the page's flat save (update_settings would refuse an unknown
 * key) and must not appear in the DEFAULTS sweep
 * (tests/test_settings_defaults_cover_the_page.py). It saves through its own
 * slot, setReassessmentCadence, and says so on the page.
 *
 * Passive only (decision 3): the panel reports and lets the student set the
 * cadence or start an administration. It adapts nothing.
 */
(function () {
    'use strict';

    const MIN_DAYS = 30;
    const MAX_DAYS = 730;

    function $(id) { return document.getElementById(id); }
    function show(n) { if (n) n.hidden = false; }
    function hide(n) { if (n) n.hidden = true; }

    function fmtDate(iso) {
        if (!iso) return 'never';
        const d = new Date(iso);
        return isNaN(d.getTime()) ? String(iso) : d.toLocaleDateString();
    }

    function daysWord(n) {
        const a = Math.abs(n);
        return a + (a === 1 ? ' day' : ' days');
    }

    async function refresh() {
        const panel = $('assessment-settings');
        if (!panel) return;
        let status, latest, inFlight;
        try {
            await api.ready();
            status = await api.getReassessmentStatus();
            latest = await api.getLatestAssessmentScores();
            inFlight = await api.getInFlightAssessment();
            const cadence = await api.getReassessmentCadence();
            $('assessment_cadence_days').value = cadence.cadence_days;
        } catch (err) {
            console.error('self-assessment settings unavailable:', err);
            $('assessment-settings-error').textContent =
                'The self-assessment settings could not be loaded.';
            show($('assessment-settings-error'));
            return;
        }
        hide($('assessment-settings-error'));

        const started = $('assessment-settings-started');
        const empty = $('assessment-settings-empty');
        if (!status.has_completed_administration) {
            // First-run empty state: one clear action, no cadence to tune yet.
            $('assessment-settings-take').textContent = inFlight ? 'Resume it' : 'Take it now';
            show(empty); hide(started);
            return;
        }
        hide(empty); show(started);

        $('assessment-last-completed').textContent = fmtDate(latest && latest.completed_at);
        const due = $('assessment-next-due');
        if (status.next_due_at) {
            const n = status.days_until_due;
            due.textContent = fmtDate(status.next_due_at)
                + (typeof n === 'number'
                    ? (n < 0 ? ' (' + daysWord(n) + ' ago, overdue)' : n === 0 ? ' (today)' : ' (in ' + daysWord(n) + ')')
                    : '');
        } else {
            due.textContent = 'not scheduled';
        }
        $('assessment-snooze-count').textContent = String(status.snooze_count || 0);
        $('assessment-settings-retake').textContent = inFlight ? 'Resume the assessment' : 'Take a new assessment now';
    }

    function validateCadence(value) {
        const n = Number(value);
        if (!Number.isInteger(n)) return 'Enter a whole number of days.';
        if (n < MIN_DAYS || n > MAX_DAYS) return 'Choose between ' + MIN_DAYS + ' and ' + MAX_DAYS + ' days.';
        return null;
    }

    async function saveCadence() {
        const input = $('assessment_cadence_days');
        const msg = $('assessment-cadence-message');
        const problem = validateCadence(input.value);
        if (problem) {
            msg.textContent = problem;
            msg.classList.add('is-error');
            show(msg);
            input.focus();
            return;                          // nothing sent to the bridge
        }
        try {
            const prefs = await api.setReassessmentCadence(Number(input.value));
            input.value = prefs.cadence_days;
            msg.textContent = 'Saved. You will be asked again every ' + prefs.cadence_days + ' days.';
            msg.classList.remove('is-error');
            show(msg);
            await refresh();
        } catch (err) {
            msg.textContent = 'Could not save: ' + (err && err.message ? err.message : err);
            msg.classList.add('is-error');
            show(msg);
        }
    }

    function init() {
        const save = $('assessment-cadence-save');
        if (save) save.addEventListener('click', saveCadence);
        const input = $('assessment_cadence_days');
        if (input) {
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); saveCadence(); }
            });
        }
        refresh();
    }

    window.refreshAssessmentSettings = refresh;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
