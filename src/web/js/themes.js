/**
 * WIMI Theme System
 * Theme definitions, CSS variable application, and settings loader.
 * Extracted from api.js — standalone, depends only on window.api.
 */

/**
 * Mix a hex colour toward white or black, keeping its hue.
 *
 * `ratio` is a FRACTION of the distance to the endpoint, not a channel
 * offset: positive mixes toward white, negative toward black, and 0 is the
 * colour itself. This is deliberately a different scale from the `amount`
 * the predecessor took -- see the three ratios below.
 *
 * Why proportional rather than additive (#307). The previous version added
 * one constant to each of R, G and B and clamped at 0/255. A channel with
 * headroom moved the whole amount while a channel without it stopped at the
 * bound, so the channels moved by different amounts -- and the ratios
 * between them are what hue is. Measured: `#059669` with the `+180` used for
 * `--color-primary-bg` became `#b9ffff`, a cyan 18.6 degrees away, and two
 * of the six shipped theme primaries came out `#ffffff` with no hue left at
 * all.
 *
 * A proportional mix scales every channel's distance from the endpoint by
 * the same factor, so `max - min` and `mid - min` scale together and the hue
 * is preserved exactly -- within 8-bit rounding, measured at <= 1.9 degrees
 * over the theme primaries and both bounds. Note the two directions are NOT
 * the same formula, which is the other reason an "amount" was the wrong
 * parameter: lightening interpolates toward 255, darkening toward 0.
 *
 * No clamp is needed, and none may be added: for `ratio` in [-1, 1] the
 * result is bounded by construction. A clamp here would mean the arithmetic
 * had become additive again. `tests/test_web_derived_colour.py` enforces
 * that, and the exact outputs are pinned by
 * `tests/wimi_test/scenarios/test_derived_colour_keeps_its_hue.py`.
 */
function _wimiMixColor(hex, ratio) {
    var channels = [
        parseInt(hex.slice(1, 3), 16),
        parseInt(hex.slice(3, 5), 16),
        parseInt(hex.slice(5, 7), 16)
    ].map(function(c) {
        return Math.round(ratio >= 0 ? c + (255 - c) * ratio : c * (1 + ratio));
    });
    return '#' + channels.map(function(c) { return c.toString(16).padStart(2, '0'); }).join('');
}

/**
 * Write `--color-primary` / `--color-secondary` and everything derived from
 * them, from the student's stored colours.
 *
 * One applier, called by BOTH colour paths -- the page-load IIFE at the foot
 * of this file and `SettingsPage.applyLivePreview` -- the same shape
 * `_wimiApplyFontFamily` and `_wimiApplyThemeVariables` already have. #307
 * was this arithmetic copied into two files, and the copy the issue did not
 * name was the one that runs on every page load, so the surfaces it listed
 * were being coloured by the copy nobody was looking at.
 *
 * The three ratios, and where each number comes from:
 *
 * - `BG` 0.85 is the issue's own figure, and the three light themes that
 *   curate a `--color-primary-bg` agree with it: the single mix ratio best
 *   reproducing each from its primary measures 0.834 (sepia), 0.834 (forest)
 *   and 0.811 (nord). There is no previous appearance to preserve here --
 *   `+180` clipped for every theme primary, so the current look *is* the bug.
 * - `LIGHT` 0.08 and `HOVER` -0.10 are `20/255` and `25/255`, i.e. exactly
 *   the fraction of the range the old constants moved a channel that had the
 *   headroom for them. So an ordinary mid-tone keeps the weight it has today
 *   and only the clipping at the extremes changes. The curated hover tokens
 *   are darker than this (-0.144 to -0.194); matching them would change how
 *   a custom colour looks, which is a palette question for #302 / #303 and
 *   not this fix.
 * - `BG_DARK` -0.68 is #322, and the direction is chosen rather than fixed.
 *   See `_wimiPrimaryBgRatio` below.
 */
function _wimiApplyColourPreferences(prefs) {
    var root = document.documentElement.style;
    var HOVER = -0.10;
    var LIGHT = 0.08;

    if (prefs.primary_color_hex) {
        root.setProperty('--color-primary', prefs.primary_color_hex);
        root.setProperty('--color-primary-hover', _wimiMixColor(prefs.primary_color_hex, HOVER));
        root.setProperty('--color-primary-light', _wimiMixColor(prefs.primary_color_hex, LIGHT));
        root.setProperty('--color-primary-bg', _wimiMixColor(
            prefs.primary_color_hex, _wimiPrimaryBgRatio(prefs.theme_name)));
    }

    if (prefs.secondary_color_hex) {
        root.setProperty('--color-secondary', prefs.secondary_color_hex);
        root.setProperty('--color-secondary-hover', _wimiMixColor(prefs.secondary_color_hex, HOVER));
    }
}

/**
 * Relative luminance of a hex colour, WCAG 2.x with sRGB linearisation.
 *
 * Here only to answer "is this theme dark?" for the mix direction. It is NOT
 * a contrast calculator and must not grow into one: the contrast arithmetic
 * for this palette is in `tests/test_theme_text_contrast.py`, which bars the
 * shipped values rather than computing them at runtime.
 */
function _wimiLuminance(hex) {
    var parts = [hex.slice(1, 3), hex.slice(3, 5), hex.slice(5, 7)].map(function(h) {
        var s = parseInt(h, 16) / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
}

/**
 * The mix ratio for `--color-primary-bg`, signed by the theme's own
 * background (#322).
 *
 * THE DEFECT. `--color-primary-bg` means "a background tinted with the
 * primary", and until this fix it was always a mix toward WHITE. That is
 * right for the four light themes and exactly inverted for the two dark
 * ones: Midnight and High Contrast curate a *dark* tint, and because
 * `prefs.primary_color_hex` has both a column default (`m001_baseline.py`)
 * and a dataclass default (`models.py`) the branch above always fires and
 * always overwrote them with a pale one. Every surface using the token --
 * the selected wizard card, the exam and session badges, the active Settings
 * nav item, and the focus ring on every text input
 * (`box-shadow: 0 0 0 3px var(--color-primary-bg)`) -- got a light slab on a
 * dark page. #307 made that strictly better (before it, clipping produced
 * `#ffffff`) without addressing it.
 *
 * WHY A SIGN AND NOT A SECOND FORMULA. #322 offered three shapes; the owner
 * chose the direction-by-luminance one. `_wimiMixColor` already takes a
 * signed ratio, so nothing about the arithmetic changes -- which matters,
 * because #307's whole finding was that this mix is hue-preserving only
 * because of its shape.
 *
 * WHY THE TWO MAGNITUDES DIFFER, and they must. `BG` 0.85 is justified by
 * the three light themes that curate a tint agreeing with it (fitted 0.834,
 * 0.834, 0.811). The same question asked of the two dark themes answers
 * -0.634 and -0.704, and -0.68 is the joint least-squares fit (-0.667)
 * rounded to the magnitude that minimises the WORST reproduction error of
 * the two curated values -- 2.5 and 1.9 L*, against 2.0/2.8 at -0.67 and
 * 3.8/0.9 at -0.70. A single magnitude of 0.85 flipped in sign is NOT the
 * answer and was measured: Midnight's tint would become `#0f1926` against a
 * `--bg-primary` of `#0f172a`, i.e. indistinguishable from the page, so
 * every badge and focus ring would vanish. Mixing 85% toward white leaves a
 * pale tint; mixing 85% toward black leaves a hole.
 *
 * Note #322's own table gives High Contrast's fit as -0.367. That does not
 * reproduce: `#3391ff` mixed 0.367 toward black is `#205ca1`, nothing like
 * the curated `#0a2a4d`. The per-channel fits are -0.804 / -0.710 / -0.698
 * and the least-squares fit is -0.704. Midnight's -0.626 does reproduce
 * (-0.634 here, the difference being method). Anybody averaging the issue's
 * two numbers would have landed near -0.5 and produced a tint a third too
 * light.
 *
 * THE SOURCE IS THE DICTIONARY, NOT `getComputedStyle`. Both callers pass
 * the same `prefs`, and `_wimiApplyThemeVariables` resolves the same name
 * from the same table, so reading it here needs no ordering constraint and
 * no layout flush. The cost is that a `--bg-primary` set by anything other
 * than a theme (a plugin stylesheet) is not seen; the benefit is that this
 * function is pure and the static guard can model it, which is what makes
 * #325's four-slab bar possible at all.
 *
 * @param {string} themeName - `prefs.theme_name`; an unknown name falls back
 *   to the default theme, exactly as `_wimiApplyThemeVariables` does.
 */
function _wimiPrimaryBgRatio(themeName) {
    var BG = 0.85;
    var BG_DARK = -0.68;
    var DARK_BG_LUMINANCE = 0.18;

    var theme = window.WIMI_THEMES[themeName] || window.WIMI_THEMES.default;
    // The default theme's dictionary is empty and styles.css resolves
    // --bg-primary to --color-white #ffffff, so a missing entry is light.
    var bg = theme.variables['--bg-primary'];
    var isDark = !!bg && _wimiLuminance(bg) < DARK_BG_LUMINANCE;
    // The threshold is deliberately NOT in this return expression:
    // tests/test_web_derived_colour.py range-checks every ratio this helper
    // can hand the mixer by reading the identifiers it returns, and a
    // luminance threshold is a constant in this function, not a ratio.
    return isDark ? BG_DARK : BG;
}

// =========================================================================
// Font Families
// =========================================================================

/**
 * Stacks the `font_family` preference can name, keyed by the values the
 * Appearance select offers.
 *
 * Every stack is built from faces the host already has and ends in a
 * generic family, so nothing here depends on a font file shipping with
 * the app — a bundled typeface is a packaging decision this does not
 * take. `system` is null: it means "leave --font-family alone", i.e.
 * whatever styles.css declares, which is what every profile had before
 * the preference did anything.
 */
window.WIMI_FONT_STACKS = {
    system: null,
    sans:   "'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif",
    serif:  "Georgia, 'Times New Roman', 'Noto Serif', Times, serif",
    mono:   "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace"
};

/**
 * Apply the `font_family` preference to the --font-family custom property.
 *
 * Scope is deliberate. --font-family is the UI typeface: styles.css hands
 * it to `body`, and the chrome inherits from there. It is NOT --font-mono
 * (code, hotkeys, the pane's URL bar), NOT `.rich-content` (saved answers,
 * reflections and notes, whose stack is matched to TinyMCE's content_style
 * so view and edit modes agree) and NOT KaTeX (its own KaTeX_* faces).
 * A student's written work must not reflow because they changed a UI font.
 *
 * @param {string} name - Key in WIMI_FONT_STACKS. Anything else (including
 *   the legacy 'system_default') falls back to the stylesheet default.
 */
function _wimiApplyFontFamily(name) {
    var stacks = window.WIMI_FONT_STACKS;
    var stack = Object.prototype.hasOwnProperty.call(stacks, name)
        ? stacks[name] : null;
    if (stack) {
        document.documentElement.style.setProperty('--font-family', stack);
    } else {
        document.documentElement.style.removeProperty('--font-family');
    }
}

// =========================================================================
// Theme Definitions
// =========================================================================

window.WIMI_THEMES = {
    default: {
        label: 'Default (Light)',
        primaryColorHex: '#2563eb',
        secondaryColorHex: '#64748b',
        variables: {}
    },

    midnight: {
        label: 'Midnight (Dark)',
        primaryColorHex: '#60a5fa',
        secondaryColorHex: '#94a3b8',
        variables: {
            '--color-gray-50':  '#1e293b',
            // #111: this was '#1e293b' too, collapsed onto gray-50, and
            // styles.css defines --bg-tertiary FROM this token -- so the two
            // surface steps were one colour and every one-step hover in
            // src/web/css was invisible in this theme. 1.86 L* above
            // --bg-secondary, which is Default's own step (1.83). gray-100 has
            // exactly one consumer (--bg-tertiary), so moving it with that
            // token keeps the stated relation true and changes nothing else.
            '--color-gray-100': '#222d3f',
            '--color-gray-200': '#334155',
            '--color-gray-300': '#475569',
            '--color-gray-400': '#64748b',
            '--color-gray-500': '#94a3b8',
            '--color-gray-600': '#cbd5e1',
            '--color-gray-700': '#e2e8f0',
            '--color-gray-800': '#f1f5f9',
            '--color-gray-900': '#f8fafc',
            '--color-white':    '#0f172a',
            '--text-primary':   '#f8fafc',
            '--text-secondary': '#cbd5e1',
            // #302: this theme's --color-gray-500, one step along its own
            // ramp from the gray-400 #64748b it used to carry (3.75:1 on
            // --bg-primary #0f172a). 6.96:1 now. Note the DIRECTION: this
            // theme's --bg-primary is near-black, so reaching contrast here
            // means moving LIGHTER. "Darken to fix contrast" is a
            // light-theme habit and is the wrong move in two of the six.
            //
            // #326 widened the bar to the nested surfaces and this is the ONE
            // theme of the six that needed no further move: 6.96 / 5.71 / 5.41
            // on --bg-primary / -secondary / -tertiary, the last measured
            // against #111's new #222d3f. #326 predicted it "may not" pass
            // after #111; measured, it does. Unchanged is a measurement here,
            // not an omission.
            '--text-muted':     '#94a3b8',
            '--text-inverse':   '#0f172a',
            '--bg-primary':   '#0f172a',
            '--bg-secondary': '#1e293b',
            // #111: a genuine second surface step, mirroring --color-gray-100
            // above. Checked against the text that lands on it: --text-muted
            // 5.41:1, --text-secondary 9.34, --text-primary 13.25, and every
            // status label 5.01-8.30, so nothing is pushed below AA by
            // lightening it.
            '--bg-tertiary':  '#222d3f',
            '--border-color':  '#334155',
            '--border-light':  '#334155',
            '--border-medium': '#475569',
            '--border-dark':   '#64748b',
            '--shadow-sm': '0 1px 2px 0 rgb(0 0 0 / 0.3)',
            '--shadow-md': '0 4px 6px -1px rgb(0 0 0 / 0.4), 0 2px 4px -2px rgb(0 0 0 / 0.3)',
            '--shadow-lg': '0 10px 15px -3px rgb(0 0 0 / 0.4), 0 4px 6px -4px rgb(0 0 0 / 0.3)',
            '--shadow-xl': '0 20px 25px -5px rgb(0 0 0 / 0.4), 0 8px 10px -6px rgb(0 0 0 / 0.3)',
            '--color-primary':       '#60a5fa',
            '--color-primary-hover': '#3b82f6',
            '--color-primary-light': '#93c5fd',
            '--color-primary-bg':    '#1e3a5f',
            // Primary colour as text (#325). The base is unchanged at 4.52:1
            // on the dictionary tint and 4.91 on the derived one -- this
            // theme's tint is dark, so the readable label is the bright
            // value, as with the status -text tokens above. Listed anyway:
            // omitting it would fall through to :root's darkened BLUE OF A
            // DIFFERENT PRIMARY, which is a hue break rather than a thin
            // ratio.
            //
            // The hover label moves, and LIGHTER. This theme's designed hover
            // is darker (#3b82f6), which measures 3.13:1 on its own tint --
            // one of the two worst cells in #325. Going further dark cannot
            // clear the bar, so the label hovers toward light instead. The
            // value is this theme's own --color-primary-light literal, 11.26
            // L* from the label, which is at least the 11.11 L* step the
            // theme designs between its primary and its hover; the minimum
            // contrast move alone landed 0.01 L* away and would have made
            // every colour-only hover invisible here.
            '--color-primary-text':       '#60a5fa',
            '--color-primary-hover-text': '#93c5fd',
            '--color-secondary':       '#94a3b8',
            '--color-secondary-hover': '#cbd5e1',
            '--color-success':    '#34d399',
            '--color-success-bg': '#064e3b',
            '--color-warning':    '#fbbf24',
            '--color-warning-bg': '#451a03',
            '--color-error':      '#f87171',
            '--color-error-bg':   '#450a0a',
            '--color-info':       '#22d3ee',
            '--color-info-bg':    '#083344',
            // Toast slabs (#110). This theme inverts --color-white to #0f172a,
            // so a toast's text is dark and its slab has to be LIGHT -- these
            // are the brightest of the three, not darker ones. The name is a
            // light-theme name; see the --color-success-dark comment in
            // styles.css before changing or copying these.
            '--color-success-dark': '#34d399',
            '--color-warning-dark': '#fbbf24',
            '--color-error-dark':   '#f87171',
            // Status colours as text (#303). Same inversion story as the
            // -dark trio above, and the same reason: this theme's status
            // tints are near-black (--color-warning-bg #451a03), so a
            // readable LABEL on them is the bright value, not a darkened
            // one. These are therefore identical to the four base colours,
            // and they are listed explicitly rather than omitted -- leaving
            // them out would fall through to the :root darkened values and
            // paint #a16707 on #451a03 at 1.93:1, turning a theme that
            // passes today into the worst of the six.
            '--color-success-text': '#34d399',
            '--color-warning-text': '#fbbf24',
            '--color-error-text':   '#f87171',
            '--color-info-text':    '#22d3ee'
        }
    },

    warm_study: {
        label: 'Warm Study (Sepia)',
        primaryColorHex: '#b45309',
        secondaryColorHex: '#92400e',
        variables: {
            '--color-gray-50':  '#faf6f1',
            '--color-gray-100': '#f5ebe0',
            '--color-gray-200': '#e8dcc8',
            '--color-gray-300': '#d5c4a1',
            '--color-gray-400': '#a89070',
            '--color-gray-500': '#7c6f5e',
            '--color-gray-600': '#5c4f3d',
            '--color-gray-700': '#3d3425',
            '--color-gray-800': '#2a2318',
            '--color-gray-900': '#1a1610',
            '--color-white':    '#fefcf8',
            '--text-primary':   '#1a1610',
            '--text-secondary': '#5c4f3d',
            // #302 took this to the theme's own --color-gray-500 #7c6f5e, up
            // from gray-400 #a89070 (2.98:1 on --bg-primary #fefcf8), for
            // 4.77:1. #326 widened the bar: gray-500 is 4.55:1 on
            // --bg-secondary and 4.16:1 on --bg-tertiary #f5ebe0, this
            // theme's warmest and darkest surface. #766959 is the minimum
            // hue-preserving darkening clearing all three (5.21 / 4.96 /
            // 4.53) and is #326's own priced value. Off the ramp now -- do
            // not tidy it back to var(--color-gray-500).
            '--text-muted':     '#766959',
            '--text-inverse':   '#fefcf8',
            '--bg-primary':   '#fefcf8',
            '--bg-secondary': '#faf6f1',
            '--bg-tertiary':  '#f5ebe0',
            '--border-color':  '#e8dcc8',
            '--border-light':  '#e8dcc8',
            '--border-medium': '#d5c4a1',
            '--border-dark':   '#a89070',
            '--shadow-sm': '0 1px 2px 0 rgb(120 80 20 / 0.08)',
            '--shadow-md': '0 4px 6px -1px rgb(120 80 20 / 0.1), 0 2px 4px -2px rgb(120 80 20 / 0.08)',
            '--shadow-lg': '0 10px 15px -3px rgb(120 80 20 / 0.1), 0 4px 6px -4px rgb(120 80 20 / 0.08)',
            '--shadow-xl': '0 20px 25px -5px rgb(120 80 20 / 0.1), 0 8px 10px -6px rgb(120 80 20 / 0.08)',
            '--color-primary':       '#b45309',
            '--color-primary-hover': '#92400e',
            '--color-primary-light': '#d97706',
            '--color-primary-bg':    '#fef3c7',
            // Primary colour as text (#325). #325's table says this theme
            // passes at 4.51:1 and it does not: that figure is against the
            // dictionary tint #fef3c7, and the tint that paints is the
            // derived #f4e5da, where #b45309 measures 4.08:1. #a94e08 is the
            // minimum darkening clearing all four slabs (5.42 / 5.16 / 4.99 /
            // 4.51). The hover label follows it down by the theme's own 9.36
            // L* step.
            '--color-primary-text':       '#a94e08',
            '--color-primary-hover-text': '#853d06',
            '--color-secondary':       '#92400e',
            '--color-secondary-hover': '#78350f',
            // Status colours as text (#303). This theme overrides NONE of
            // --color-success / -warning / -error / -info, so it is easy to
            // read these as redundant. They are not: this theme's
            // --bg-secondary #faf6f1 is a shade darker than the generic
            // #f8fafc, and the :root values land at 4.37-4.42:1 on it. Each
            // is one or two notches darker than :root and nothing else.
            // --color-error-text falls through because #df1313 already
            // clears every slab here.
            '--color-success-text': '#0b815a',
            '--color-warning-text': '#9e6506',
            '--color-info-text':    '#047c91'
        }
    },

    forest: {
        label: 'Forest (Earthy Green)',
        primaryColorHex: '#059669',
        secondaryColorHex: '#6b7280',
        variables: {
            '--color-gray-50':  '#f5f9f7',
            '--color-gray-100': '#ecf3ef',
            '--color-gray-200': '#d5e2db',
            '--color-gray-300': '#b0c7bb',
            '--color-gray-400': '#82a394',
            '--color-gray-500': '#5e7e6f',
            '--color-gray-600': '#435a4e',
            '--color-gray-700': '#2f4038',
            '--color-gray-800': '#1d2b24',
            '--color-gray-900': '#0f1a14',
            '--color-white':    '#fbfdfb',
            '--text-primary':   '#0f1a14',
            '--text-secondary': '#435a4e',
            // #302: THE ONE THEME WHERE THE RAMP WAS NOT ENOUGH even for the
            // narrow bar. The other four moved --text-muted to their own
            // --color-gray-500; this theme's gray-500 #5e7e6f measures 4.38:1
            // on --bg-primary #fbfdfb -- short of 4.5:1, so it would have
            // shipped a value that looks like the fix and is not one. #302
            // landed #5c7c6d at 4.51:1.
            //
            // #326: that 4.51 was against --bg-primary alone, and this theme
            // has the worst nested slabs of the six -- 4.34:1 on
            // --bg-secondary and 4.09:1 on --bg-tertiary #ecf3ef. #567466 is
            // the minimum hue-preserving darkening clearing all three (5.03 /
            // 4.84 / 4.56) and is #326's own priced value. Do not tidy it
            // back to var(--color-gray-500), and not to the gray-600 #435a4e
            // (7.31:1) either, which overshoots the minimum the owner
            // approved and lands where --text-secondary already is.
            '--text-muted':     '#567466',
            '--text-inverse':   '#fbfdfb',
            '--bg-primary':   '#fbfdfb',
            '--bg-secondary': '#f5f9f7',
            '--bg-tertiary':  '#ecf3ef',
            '--border-color':  '#d5e2db',
            '--border-light':  '#d5e2db',
            '--border-medium': '#b0c7bb',
            '--border-dark':   '#82a394',
            '--shadow-sm': '0 1px 2px 0 rgb(15 60 30 / 0.06)',
            '--shadow-md': '0 4px 6px -1px rgb(15 60 30 / 0.08), 0 2px 4px -2px rgb(15 60 30 / 0.06)',
            '--shadow-lg': '0 10px 15px -3px rgb(15 60 30 / 0.08), 0 4px 6px -4px rgb(15 60 30 / 0.06)',
            '--shadow-xl': '0 20px 25px -5px rgb(15 60 30 / 0.08), 0 8px 10px -6px rgb(15 60 30 / 0.06)',
            '--color-primary':       '#059669',
            '--color-primary-hover': '#047857',
            '--color-primary-light': '#10b981',
            '--color-primary-bg':    '#d1fae5',
            // Primary colour as text (#325). 3.69:1 on --bg-primary and
            // 3.14:1 on the derived tint #daefe8 -- with Nord, the worst of
            // the six. #047955 is the minimum darkening clearing all four
            // (5.31 / 5.11 / 4.78 / 4.52).
            //
            // NOTE IT IS NOT THE #047d58 two lines down, and the near-
            // duplicate is deliberate rather than sloppy. This theme sets
            // --color-primary and --color-success to the SAME hex #059669 and
            // both tints to #d1fae5, so the two labels look like they should
            // share a value. They cannot: --color-success-bg is curated and
            // paints as written, while --color-primary-bg is overwritten by
            // the derived #daefe8, which is darker. #047d58 clears #d1fae5 at
            // 4.54 and the derived tint at only ~4.3. Unifying them would
            // mean tightening a #303 value that has no defect behind it.
            '--color-primary-text':       '#047955',
            '--color-primary-hover-text': '#035c41',
            '--color-secondary':       '#6b7280',
            '--color-secondary-hover': '#4b5563',
            '--color-success':    '#059669',
            '--color-success-bg': '#d1fae5',
            // Status colours as text (#303). This theme overrides ONLY
            // --color-success of the four, so only its text counterpart is
            // listed; warning, error and info fall through to :root, which
            // is correct because this theme leaves their tints light.
            // #047d58 is the minimum darkening of #059669 (3.69:1 on
            // --bg-primary, 3.32:1 on #d1fae5) that clears both at 5.04 /
            // 4.54:1. NOTE --color-primary is #059669 TOO in this theme, and
            // that is a different defect with its own issue -- repointing a
            // label here does not fix a primary-coloured one.
            //
            // The warning and info entries are here for the --bg-secondary
            // reason given in the Warm Study dictionary, not because this
            // theme overrides those bases (it does not). Error falls
            // through: #df1313 clears every slab here.
            '--color-success-text': '#047d58',
            '--color-warning-text': '#9f6607',
            '--color-info-text':    '#047d92'
        }
    },

    nord: {
        label: 'Nord (Arctic)',
        primaryColorHex: '#5e81ac',
        secondaryColorHex: '#81a1c1',
        variables: {
            '--color-gray-50':  '#eceff4',
            '--color-gray-100': '#e5e9f0',
            '--color-gray-200': '#d8dee9',
            '--color-gray-300': '#b8c4d4',
            '--color-gray-400': '#7b8fa4',
            '--color-gray-500': '#616e7c',
            '--color-gray-600': '#4c566a',
            '--color-gray-700': '#3b4252',
            '--color-gray-800': '#2e3440',
            '--color-gray-900': '#242933',
            '--color-white':    '#f8fafc',
            '--text-primary':   '#2e3440',
            '--text-secondary': '#4c566a',
            // #302 took this to the theme's own --color-gray-500 #616e7c, up
            // from gray-400 #7b8fa4 (3.18:1 on --bg-primary #f8fafc), for
            // 4.98:1. #326 widened the bar: gray-500 clears --bg-secondary by
            // 0.02 (4.52:1) and fails --bg-tertiary #e5e9f0 at 4.28:1. That
            // 0.02 is why a --bg-tertiary-only fix would have been wrong --
            // three themes were passing the middle slab by coincidence.
            // #5e6a78 clears all three (5.27 / 4.78 / 4.53) and is #326's own
            // priced value. Off the ramp now; do not tidy it back.
            '--text-muted':     '#5e6a78',
            '--text-inverse':   '#eceff4',
            '--bg-primary':   '#f8fafc',
            '--bg-secondary': '#eceff4',
            '--bg-tertiary':  '#e5e9f0',
            '--border-color':  '#d8dee9',
            '--border-light':  '#d8dee9',
            '--border-medium': '#b8c4d4',
            '--border-dark':   '#7b8fa4',
            '--shadow-sm': '0 1px 2px 0 rgb(46 52 64 / 0.06)',
            '--shadow-md': '0 4px 6px -1px rgb(46 52 64 / 0.08), 0 2px 4px -2px rgb(46 52 64 / 0.06)',
            '--shadow-lg': '0 10px 15px -3px rgb(46 52 64 / 0.08), 0 4px 6px -4px rgb(46 52 64 / 0.06)',
            '--shadow-xl': '0 20px 25px -5px rgb(46 52 64 / 0.08), 0 8px 10px -6px rgb(46 52 64 / 0.06)',
            '--color-primary':       '#5e81ac',
            '--color-primary-hover': '#4c6e96',
            '--color-primary-light': '#81a1c1',
            '--color-primary-bg':    '#dfe8f1',
            // Primary colour as text (#325). The headline case: #5e81ac on
            // #dfe8f1 is 3.25:1, and this theme carried 55 of the 118 failing
            // elements -- 31 from the base and 24 from the hover value, which
            // is why BOTH tokens exist. #4d6a8d is the minimum darkening
            // clearing all four slabs (5.34 / 4.84 / 4.51 / 4.70). The hover
            // label follows by the theme's own 7.53 L* step; derived on its
            // own it landed 0.00 L* from the label.
            '--color-primary-text':       '#4d6a8d',
            '--color-primary-hover-text': '#405774',
            '--color-secondary':       '#81a1c1',
            '--color-secondary-hover': '#6d8faf',
            '--color-success':    '#a3be8c',
            '--color-success-bg': '#edf3e8',
            '--color-warning':    '#ebcb8b',
            '--color-warning-bg': '#faf4e6',
            '--color-error':      '#bf616a',
            '--color-error-bg':   '#f5e0e2',
            '--color-info':       '#88c0d0',
            '--color-info-bg':    '#e3f1f5',
            // Status colours as text (#303). Nord is the worst of the six
            // here, because its palette is pastel: #ebcb8b on #faf4e6
            // measured 1.42:1, the lowest ratio found anywhere in the audit.
            // Each value is the minimum hue-preserving darkening of the base
            // above it that clears 4.5:1 on BOTH --bg-primary #f8fafc and
            // its own tint. The bases keep their pastel for fills.
            '--color-success-text': '#597442',
            '--color-warning-text': '#8d6618',
            '--color-error-text':   '#ab454f',
            '--color-info-text':    '#357486'
        }
    },

    high_contrast: {
        label: 'High Contrast',
        primaryColorHex: '#3391ff',
        secondaryColorHex: '#b0b0b0',
        variables: {
            '--color-gray-50':  '#1a1a1a',
            // #111, as in Midnight: this was '#1a1a1a', collapsed onto
            // gray-50, so the two surface steps were one colour. 2.00 L* above
            // --bg-secondary. Deliberately NOT a bolder step even though this
            // theme's other steps are bold (--bg-primary to --bg-secondary is
            // 9.26 L*): lightening a dark surface lowers the contrast of
            // everything on it, and --text-muted here is the token with the
            // least headroom in the palette. The owner's rule is the minimum
            // perceptual step, and this is it -- the next hex up, #1f1f1f, is
            // 2.4 L* and costs --text-muted another 0.05.
            '--color-gray-100': '#1e1e1e',
            '--color-gray-200': '#333333',
            '--color-gray-300': '#4d4d4d',
            '--color-gray-400': '#808080',
            '--color-gray-500': '#b0b0b0',
            '--color-gray-600': '#d0d0d0',
            '--color-gray-700': '#e8e8e8',
            '--color-gray-800': '#f2f2f2',
            '--color-gray-900': '#ffffff',
            '--color-white':    '#000000',
            '--text-primary':   '#ffffff',
            '--text-secondary': '#d0d0d0',
            // #302 DELIBERATELY DID NOT TOUCH THIS, and #326 does. #808080 on
            // --bg-primary #000000 is 5.32:1 and already cleared AA -- the
            // only theme of the six that did -- so moving it then would have
            // been a change with no defect behind it. On the nested surfaces
            // it does not clear: 4.41:1 on the old --bg-secondary/-tertiary
            // #1a1a1a.
            //
            // This value is NOT #326's priced #828282, and the difference is
            // #111 landing in the same change. #828282 was computed against
            // #1a1a1a; against #111's new --bg-tertiary #1e1e1e it measures
            // 4.34:1, still short. #858585 clears all three (5.69 / 4.72 /
            // 4.52). #326 said its High Contrast row would move if #111 did;
            // it did, and this is by how much.
            //
            // Note the DIRECTION once more: this is a LIGHTENING. Two of the
            // six themes fix contrast by moving away from black.
            '--text-muted':     '#858585',
            '--text-inverse':   '#000000',
            '--bg-primary':   '#000000',
            '--bg-secondary': '#1a1a1a',
            // #111: a genuine second surface step, mirroring --color-gray-100
            // above. This is the change that forced --text-muted to move here
            // (#326): #828282, the value #326 priced against the old #1a1a1a,
            // measures 4.34:1 on this surface. See --text-muted below.
            '--bg-tertiary':  '#1e1e1e',
            '--border-color':  '#4d4d4d',
            '--border-light':  '#333333',
            '--border-medium': '#4d4d4d',
            '--border-dark':   '#808080',
            '--shadow-sm': '0 1px 2px 0 rgb(0 0 0 / 0.5)',
            '--shadow-md': '0 4px 6px -1px rgb(0 0 0 / 0.6), 0 2px 4px -2px rgb(0 0 0 / 0.5)',
            '--shadow-lg': '0 10px 15px -3px rgb(0 0 0 / 0.6), 0 4px 6px -4px rgb(0 0 0 / 0.5)',
            '--shadow-xl': '0 20px 25px -5px rgb(0 0 0 / 0.6), 0 8px 10px -6px rgb(0 0 0 / 0.5)',
            '--color-primary':       '#3391ff',
            '--color-primary-hover': '#66b0ff',
            '--color-primary-light': '#66b0ff',
            '--color-primary-bg':    '#0a2a4d',
            // Primary colour as text (#325), and the clearest case in the
            // palette for "contrast is a ratio, never a direction": BOTH
            // values here move LIGHTER. #3391ff is 4.57:1 on the curated tint
            // and 4.32:1 on the derived #102e52, so the fix is away from
            // black. #3a95ff clears all four (6.92 / 5.74 / 4.77 / 4.51).
            // A sweep that darkened would have made this theme worse while
            // reporting a fix.
            '--color-primary-text':       '#3a95ff',
            '--color-primary-hover-text': '#71b3ff',
            '--color-secondary':       '#b0b0b0',
            '--color-secondary-hover': '#d0d0d0',
            '--color-success':    '#00ff88',
            '--color-success-bg': '#003d1f',
            '--color-warning':    '#ffcc00',
            '--color-warning-bg': '#4d3d00',
            '--color-error':      '#ff4444',
            '--color-error-bg':   '#4d0000',
            '--color-info':       '#00e5ff',
            '--color-info-bg':    '#003d44',
            // Toast slabs (#110). Same inversion as Midnight: --color-white is
            // #000000 here, so the slab has to be LIGHT. See the
            // --color-success-dark comment in styles.css.
            '--color-success-dark': '#00ff88',
            '--color-warning-dark': '#ffcc00',
            '--color-error-dark':   '#ff4444',
            // Status colours as text (#303). As in Midnight: the tints here
            // are near-black, so the readable label is the bright value and
            // these equal the four bases. Measured 4.68-15.66:1 unchanged.
            // Omitting them would inherit :root's darkened values onto a
            // near-black tint -- #df1313 on #4d0000 is 1.75:1.
            '--color-success-text': '#00ff88',
            '--color-warning-text': '#ffcc00',
            '--color-error-text':   '#ff4444',
            '--color-info-text':    '#00e5ff'
        }
    }
};

/**
 * Collect all CSS variable names used across every theme.
 * Cached after first call.
 */
function _wimiGetAllThemeVarNames() {
    if (window._wimiAllThemeVarNames) return window._wimiAllThemeVarNames;
    var names = new Set();
    for (var key in window.WIMI_THEMES) {
        var theme = window.WIMI_THEMES[key];
        for (var varName in theme.variables) {
            names.add(varName);
        }
    }
    window._wimiAllThemeVarNames = Array.from(names);
    return window._wimiAllThemeVarNames;
}

/**
 * Apply a theme's CSS variable overrides to :root.
 * @param {string} themeName - Key in WIMI_THEMES
 */
function _wimiApplyThemeVariables(themeName) {
    var root = document.documentElement.style;
    var allVars = _wimiGetAllThemeVarNames();
    var theme = window.WIMI_THEMES[themeName] || window.WIMI_THEMES.default;

    for (var i = 0; i < allVars.length; i++) {
        root.removeProperty(allVars[i]);
    }

    for (var varName in theme.variables) {
        root.setProperty(varName, theme.variables[varName]);
    }
}

/**
 * Apply persisted visual settings on every page load.
 */
(async function() {
    try {
        await api.ready();
        var prefs = await api.getUserPreferences();
        window.wimiPreferences = prefs;

        var root = document.documentElement.style;
        var themeName = prefs.theme_name || 'default';
        var theme = window.WIMI_THEMES[themeName] || window.WIMI_THEMES.default;

        _wimiApplyThemeVariables(themeName);

        // Always apply saved color preferences — ensures consistency
        // regardless of whether they match the current theme's defaults
        _wimiApplyColourPreferences(prefs);

        _wimiApplyFontFamily(prefs.font_family);

        if (prefs.font_size_scale != null && prefs.font_size_scale !== 1.0) {
            root.fontSize = (prefs.font_size_scale * 16) + 'px';
        }

        // Apply UI density — including comfortable (reset to CSS defaults)
        if (prefs.ui_density === 'compact') {
            root.setProperty('--space-sm', '0.25rem');
            root.setProperty('--space-md', '0.75rem');
            root.setProperty('--space-lg', '1rem');
            root.setProperty('--space-xl', '1.5rem');
        } else if (prefs.ui_density === 'spacious') {
            root.setProperty('--space-sm', '0.75rem');
            root.setProperty('--space-md', '1.25rem');
            root.setProperty('--space-lg', '2rem');
            root.setProperty('--space-xl', '2.5rem');
        } else {
            root.removeProperty('--space-sm');
            root.removeProperty('--space-md');
            root.removeProperty('--space-lg');
            root.removeProperty('--space-xl');
        }

        if (prefs.show_animations === false) {
            var style = document.createElement('style');
            style.id = 'wimi-no-animations';
            style.textContent = '*, *::before, *::after { transition-duration: 0s !important; animation-duration: 0s !important; }';
            document.head.appendChild(style);
        }
    } catch (e) {
        console.warn('Settings load failed:', e);
    }
})();
