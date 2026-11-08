/**
 * WIMI difficulty and time card: links into the entry browser, and the
 * words for a time spent (#898).
 *
 * `paramsFor(payload, bucket)` is the JavaScript copy of
 * `dt_entry_browser_params` in `src/database/domains/analytics_advanced.py`,
 * line for line. Given a `getDifficultyTimeQuadrants` payload and one of
 * `BUCKETS`, it returns the entry browser's URL parameters that land on
 * exactly the number the card shows for that bucket.
 * `tests/database/test_entry_browser_lands_on_the_card.py` proves the
 * Python copy lands for every bucket and picker state;
 * `test_entry_browser_filters_by_difficulty_and_time.py` checks this copy
 * returns the same parameters on a real payload. Change both or neither.
 *
 * Wave 2's card takes `urlFor` from here. The entry browser loads this file
 * for `formatSeconds` / `timeRangeLabel`, so its chips and the card's labels
 * say a time the same way.
 *
 * No dependencies; load before the page script that uses it.
 */
(function (global) {
    'use strict';

    var HARD = [4, 5];
    var EASY = [1, 2];
    var MIDDLE = 3;
    var QUADRANTS = ['hard_fast', 'hard_slow', 'easy_fast', 'easy_slow'];
    var BUCKETS = ['total'].concat(QUADRANTS, ['unsplit', 'middle', 'not_placed']);

    /** 94 -> "94", 94.5 -> "94.5": String() already writes both as Python does. */
    function linkNumber(value) {
        return String(Number(value));
    }

    function paramsFor(payload, bucket) {
        if (BUCKETS.indexOf(bucket) === -1) {
            throw new Error('unknown bucket ' + bucket);
        }
        var scope = payload.scope || {};
        var params = { exam: String(scope.exam_context_id) };
        if (scope.subject_id !== null && scope.subject_id !== undefined) {
            params.counted_subject = String(scope.subject_id);
            if (scope.primary_parent_id !== null && scope.primary_parent_id !== undefined) {
                params.counted_parent = String(scope.primary_parent_id);
            }
        }

        if (QUADRANTS.indexOf(bucket) !== -1) {
            var median = payload.median || {};
            if (!median.available) {
                throw new Error(bucket + ' has no split to link to');
            }
            var levels = bucket.indexOf('hard_') === 0 ? HARD : EASY;
            params.difficulty = levels.join(',');
            var m = linkNumber(median.value_seconds);
            if (/_fast$/.test(bucket)) {
                params.time_max = m;
            } else {
                params.time_min = m;
            }
        } else if (bucket === 'unsplit') {
            params.difficulty = EASY.concat(HARD).sort(function (a, b) { return a - b; }).join(',');
            params.time_min = '0';
        } else if (bucket === 'middle') {
            params.difficulty = String(MIDDLE);
            params.time_min = '0';
        } else if (bucket === 'not_placed') {
            params.missing = 'difficulty,time';
        }

        var selection = payload.selection || {};
        var picked = selection.tag_ids || [];
        if (selection.untagged) {
            params.untagged = '1';
        } else if (picked.length) {
            params.tags = picked.join(',');
            if (selection.match === 'all' && picked.length > 1) {
                params.tag_mode = 'all';
            }
        }
        return params;
    }

    /** The entry browser URL, relative to a page in src/web/html/. */
    function urlFor(payload, bucket) {
        return 'entry_browser.html?' + new URLSearchParams(paramsFor(payload, bucket)).toString();
    }

    /**
     * A whole number of seconds as words: "45 s", "1 min 34 s", "2 min",
     * "1 h 5 min". Callers round first: the card's label is ceil(median),
     * and so is the browser's chip for a link carrying the median.
     */
    function formatSeconds(seconds) {
        var total = Math.max(0, Math.round(Number(seconds) || 0));
        var h = Math.floor(total / 3600);
        var min = Math.floor((total % 3600) / 60);
        var s = total % 60;
        var parts = [];
        if (h) parts.push(h + ' h');
        if (min) parts.push(min + ' min');
        if (s || !parts.length) parts.push(s + ' s');
        return parts.join(' ');
    }

    /**
     * Plain words for a time filter: min inclusive, max exclusive, either
     * may be null. Whole seconds round UP, as the card's label does: with
     * the median at 94.5 every whole time under it is under 95 s, and every
     * time at or above it is 95 s or more.
     */
    function timeRangeLabel(min, max) {
        var hasMin = min !== null && min !== undefined;
        var hasMax = max !== null && max !== undefined;
        var lo = hasMin ? formatSeconds(Math.ceil(min)) : '';
        var hi = hasMax ? formatSeconds(Math.ceil(max)) : '';
        if (hasMin && hasMax) return lo + ' to under ' + hi;
        if (hasMax) return 'under ' + hi;
        if (hasMin && Number(min) <= 0) return 'recorded';
        if (hasMin) return lo + ' or more';
        return '';
    }

    global.WimiDifficultyTimeLinks = {
        BUCKETS: BUCKETS,
        paramsFor: paramsFor,
        urlFor: urlFor,
        formatSeconds: formatSeconds,
        timeRangeLabel: timeRangeLabel
    };
})(window);
