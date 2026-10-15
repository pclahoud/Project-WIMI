/**
 * Dashboard self-assessment notice (#766 Wave 3, plan Stage 5 as amended by
 * decision 6: offer at first run, skippable, banner until completed).
 *
 * Self-initialising and additive: index.html links this after landing.js and
 * nothing in landing.js knows it exists. The markup ships `hidden` and is
 * revealed only once the status is known, so there is no flicker and a
 * failed read shows nothing -- the sync notice's pattern (#151).
 *
 * When it shows:
 *   - no administration has ever been completed, and no snooze is in force
 *     (the first-run offer; `due` is always false before a first completion,
 *     so this clause is its own), or
 *   - a completed administration exists and `due` is true (re-measurement).
 * When it does not: a snooze is in force, or the read failed.
 *
 * "Later" is a 7-day snooze. The banner therefore comes back, which is what
 * "persists until completed" means in practice without nagging on every
 * launch. Re-measurement adds a 30-day option.
 */
(function () {
    'use strict';

    const SNOOZE_LATER_DAYS = 7;
    const SNOOZE_LONG_DAYS = 30;

    function $(id) { return document.getElementById(id); }

    function describe(status, inFlight) {
        if (!status.has_completed_administration) {
            if (inFlight) {
                return {
                    text: 'You started the self-assessment but did not finish it. '
                        + 'Picking it up again takes about ten minutes.',
                    primary: 'Resume',
                    showLong: false,
                };
            }
            return {
                text: 'A short self-assessment helps WIMI understand how you approach '
                    + 'thinking and learning. It takes about ten minutes and nothing '
                    + 'else changes because of it yet.',
                primary: 'Take it now',
                showLong: false,
            };
        }
        const overdue = typeof status.days_until_due === 'number' && status.days_until_due < 0
            ? ' (due ' + Math.abs(status.days_until_due) + (Math.abs(status.days_until_due) === 1 ? ' day' : ' days') + ' ago)'
            : '';
        return {
            text: 'Time to retake your self-assessment' + overdue + '.',
            primary: inFlight ? 'Resume' : 'Retake now',
            showLong: true,
        };
    }

    function shouldShow(status) {
        if (!status) return false;
        if (status.has_completed_administration) return status.due === true;
        // Never completed: offer unless a snooze pushed next_due_at ahead.
        return status.days_until_due === null || status.days_until_due === undefined
            || status.days_until_due <= 0;
    }

    async function snooze(days, box) {
        try {
            await api.snoozeReassessment(days);
        } catch (err) {
            console.error('snoozeReassessment failed:', err);
        }
        box.hidden = true;
    }

    async function load() {
        const box = $('assessment-notice');
        if (!box) return;
        let status, inFlight;
        try {
            await api.ready();
            status = await api.getReassessmentStatus();
            inFlight = await api.getInFlightAssessment();
        } catch (err) {
            console.error('assessment status unavailable:', err);
            return;                          // stays hidden: nothing false is painted
        }
        if (!shouldShow(status)) return;

        const d = describe(status, inFlight);
        $('assessment-notice-text').textContent = d.text;
        const primary = $('assessment-notice-take');
        primary.textContent = d.primary;
        const later = $('assessment-notice-later');
        later.textContent = 'Later';
        later.addEventListener('click', function () { snooze(SNOOZE_LATER_DAYS, box); }, { once: true });
        const long = $('assessment-notice-snooze-long');
        if (d.showLong) {
            long.hidden = false;
            long.textContent = 'Snooze ' + SNOOZE_LONG_DAYS + ' days';
            long.addEventListener('click', function () { snooze(SNOOZE_LONG_DAYS, box); }, { once: true });
        } else {
            long.hidden = true;
        }
        box.hidden = false;
    }

    // Exposed for scenarios and for a page that wants to re-check.
    window.loadAssessmentNotice = load;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', load);
    } else {
        load();
    }
})();
