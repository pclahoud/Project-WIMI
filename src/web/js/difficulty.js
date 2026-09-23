/**
 * WIMI Perceived Difficulty — the one definition of the 1–5 vocabulary.
 *
 * `question_entries.perceived_difficulty` accepts 1–5, and the entry form
 * offers all five as buttons whose `title` attributes are the words the
 * student reads at the moment of recording (`question_entry.html`,
 * `#difficulty-rating .difficulty-dot`). Those words are the vocabulary:
 * whatever a display surface shows for a stored number has to be the word
 * that was on the button that was clicked.
 *
 * Forgejo #46: the two display surfaces each carried their own literal map,
 * both shifted one step off the form's (1 → "Easy" instead of "Very Easy"),
 * and both collapsing 4 and 5 onto "Very Hard". A student who recorded
 * "Medium" opened the entry later and read "Hard". The owner's decision
 * (Option B, 2026-09-14) was that the form's vocabulary is the correct one
 * and the displays adopt it, so this module now holds it once.
 *
 * Any surface that renders a stored difficulty reads it from here. The
 * matching colours and dot indicators live in `css/difficulty.css`, keyed
 * off the `data-difficulty` attribute `applyToBadge` writes — keep the two
 * files in step, and if you add a step to the scale, add it in both.
 *
 * No dependencies; load before the page script that uses it.
 */
(function (global) {
    'use strict';

    /**
     * Ordered low → high. `className` is kept for styling hooks that
     * predate the data attribute (and for plugins); `css/difficulty.css`
     * itself keys off the numeric value so both surfaces share one
     * selector set.
     */
    var LEVELS = [
        { value: 1, label: 'Very Easy', className: 'very-easy' },
        { value: 2, label: 'Easy',      className: 'easy' },
        { value: 3, label: 'Medium',    className: 'medium' },
        { value: 4, label: 'Hard',      className: 'hard' },
        { value: 5, label: 'Very Hard', className: 'very-hard' }
    ];

    var BY_VALUE = {};
    LEVELS.forEach(function (level) { BY_VALUE[level.value] = level; });

    /**
     * Look a stored difficulty up. Accepts the number or its string form,
     * because `dataset` reads give strings. Returns null for anything
     * outside the scale so callers can decide between hiding the badge and
     * showing a placeholder.
     */
    function describe(value) {
        var key = Number(value);
        return BY_VALUE[key] || null;
    }

    /** The word for a stored difficulty, or '' when it is not on the scale. */
    function labelFor(value) {
        var level = describe(value);
        return level ? level.label : '';
    }

    /**
     * Render `value` into a `.difficulty-badge` element: the word as its
     * text, the numeric value as `data-difficulty` (what difficulty.css
     * paints off), and the level's class for legacy hooks. Returns the
     * level, or null when the value is off-scale — in which case the badge
     * is left blank and unkeyed rather than guessing.
     */
    function applyToBadge(badge, value, baseClass) {
        if (!badge) { return null; }
        var level = describe(value);
        var base = baseClass || 'difficulty-badge';
        if (!level) {
            badge.textContent = '';
            delete badge.dataset.difficulty;
            badge.className = base;
            return null;
        }
        badge.textContent = level.label;
        badge.dataset.difficulty = String(level.value);
        badge.className = base + ' ' + level.className;
        return level;
    }

    global.WimiDifficulty = {
        LEVELS: LEVELS,
        describe: describe,
        labelFor: labelFor,
        applyToBadge: applyToBadge
    };
})(window);
