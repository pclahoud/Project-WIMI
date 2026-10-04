/**
 * LocalDate -- the student's own calendar day, as `YYYY-MM-DD`.
 *
 * Settled in #286.
 *
 * The defect this replaces
 * -----------------------
 * Five sites spelled "today" as
 *
 *     new Date().toISOString().split('T')[0]
 *
 * and `toISOString()` is **UTC**. So the expression names a different day
 * from the student's for part of every day: west of Greenwich it runs ahead
 * (an evening load in UTC-4 yields *tomorrow*), east of it behind (a morning
 * load in UTC+14 yields *yesterday*). Measured live through the harness with
 * CDP's `Emulation.setTimezoneOverride`, which Qt's CDP does implement:
 * under `Pacific/Kiritimati` (UTC+14) at 13:00 UTC the page's own local date
 * was `2026-10-04` and `#session-date` held `2026-10-03`.
 *
 * Why local is the right answer, rather than a matter of taste
 * -----------------------------------------------------------
 * It is not "a nicer default" -- it is the only value consistent with what
 * reads `review_sessions.date_encountered` back:
 *
 * * `sessions.py`'s own fallback is `date.today()` -- Python's **local**
 *   date -- so the backend and the frontend were answering the same question
 *   two different ways.
 * * `get_activity_heatmap` builds its day range from `datetime.now().date()`
 *   and emits days up to **local** today, so a UTC "tomorrow" is a key that
 *   is not in the heatmap at all.
 * * `_calculate_streak_info` compares `max(active_dates)` against
 *   `datetime.now().date()`, so that same row neither starts nor extends a
 *   streak.
 *
 * An evening session was therefore stored under a day nothing counts. That is
 * why this is a storage bug and not a display one: no later fix can tell a
 * genuine tomorrow-dated session from a defaulted one.
 *
 * Why composition rather than arithmetic on the UTC string
 * --------------------------------------------------------
 * #286 offers `new Date(now.getTime() - now.getTimezoneOffset() * 60000)
 * .toISOString().split('T')[0]` as one option. It gives the right ten
 * characters, but it gets there by building a Date that is deliberately
 * wrong -- every other field on it is off by the offset -- so anything that
 * later reads more than the date out of it is silently misled. Composing
 * from `getFullYear()` / `getMonth()` / `getDate()` states what is wanted
 * instead of encoding it, which is also the pattern `session_setup.js`'s
 * `formatDate()` and `entry_browser.js`'s `formatDate()` already use in the
 * other direction.
 *
 * Nothing here formats a *timestamp*. `new Date().toISOString()` with no
 * `split` is still correct for `exported_at` and friends: an instant is
 * properly written in UTC, and `tests/test_web_local_date.py` only bans the
 * date-extracting form.
 *
 * Loading it
 * ----------
 * A plain classic script, like `page_gate.js`, linked by each page whose
 * scripts use it. That is the per-page link gotcha, so it is enforced rather
 * than remembered: `tests/test_web_local_date.py` fails if a page's scripts
 * name `LocalDate` and the page does not link this file.
 */
(function () {
    'use strict';

    function pad(n) {
        return String(n).padStart(2, '0');
    }

    /**
     * One `Date` rendered as its own local calendar day.
     *
     * Takes the date apart with the local component getters, so the answer
     * is the day a student looking at a wall calendar would name -- never
     * the UTC day the same instant falls in.
     *
     * @param {Date} date any Date
     * @returns {string} `YYYY-MM-DD` in the local zone
     */
    function toISODate(date) {
        return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-'
            + pad(date.getDate());
    }

    /**
     * Today, where the student is.
     *
     * @returns {string} `YYYY-MM-DD` in the local zone
     */
    function today() {
        return toISODate(new Date());
    }

    window.LocalDate = {
        today: today,
        toISODate: toISODate,
    };
})();
