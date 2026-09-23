"""Regression: a coloured toast stays readable in all six themes (#110).

Forgejo issue #110 — "Success, warning and error toasts are near-unreadable
in Midnight and High Contrast":

    ``.toast`` painted ``background: var(--color-gray-800, #1e293b);
    color: var(--color-white, #ffffff)``, and **both of those tokens invert
    between themes** — Midnight maps ``--color-gray-800`` to ``#f1f5f9`` and
    ``--color-white`` to ``#0f172a``. The three coloured variants overrode
    only the *background*, with ``var(--color-success-dark, #166534)`` and
    friends — and those three ``-dark`` names were defined **nowhere**, so
    the fallback was unconditional and pinned to a light-theme value while
    the inherited text colour kept flipping. Measured 2.15–2.52:1 in
    Midnight and 2.53–2.96:1 in High Contrast against a 4.5:1 bar.

What the fix changes: the three names are now real tokens, defined at
``:root`` in ``styles.css`` at the literals they used to fall back to, and
overridden in the **two** theme dictionaries that invert ``--color-white``.
The three ``KNOWN_DEAD_FALLBACK`` entries went with them.

Why these assertions catch the regression, and why there are two halves.
An undefined ``var()`` still computes to *something*, and here the something
was a colour that looks perfectly reasonable in four of the six themes — so
"is it readable" alone would have passed on this bug for four themes and
"is it the expected hex" would have passed for those same four after a
revert. The two halves discriminate in opposite directions:

* **every theme** must clear 4.5:1 on all three coloured variants, and
* the four themes that do **not** invert ``--color-white`` must still
  resolve to the pre-fix literal (nothing moved for them — that is (b)'s
  whole claim), while the two that **do** must resolve to something else
  (which is the half a revert breaks, because reverting restores exactly
  that literal everywhere).

``.toast-info`` is carried through as a control: it was fine before the fix
and must stay fine, so a harness that reports it failing is measuring the
wrong element rather than finding a bug.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.contrast import AA_BODY_TEXT, contrast_ratio, is_transparent
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

THEMES = ['default', 'midnight', 'warm_study', 'forest', 'nord', 'high_contrast']
COLOURED = ['success', 'warning', 'error']

# The four themes that leave --color-white light, so the :root slab already
# pairs with it and (b) adds them no dictionary entry.
UNCHANGED_THEMES = ['default', 'warm_study', 'forest', 'nord']

# What the dead fallback produced, and therefore what the unchanged themes
# must still produce. Hardcoded on purpose: this is the *pre-fix* value, and
# a test that re-read it from the stylesheet could not tell a revert apart.
LEGACY_SLAB = {'success': 'rgb(22, 101, 52)',
               'warning': 'rgb(146, 64, 14)',
               'error': 'rgb(153, 27, 27)'}

# Build the four variants in the live document and read the real elements.
# A probe span would resolve the token but not the cascade that puts .toast's
# inherited colour on the message, which is the half of the pair that moves.
MEASURE = """
(() => {
  document.getElementById('w110-probe')?.remove();
  const host = document.createElement('div');
  host.id = 'w110-probe';
  host.innerHTML = ['info'].concat(__COLOURED__).map(v =>
    '<div class="toast toast-visible toast-' + v + '" data-v="' + v + '">' +
    '<span class="toast-icon">i</span>' +
    '<span class="toast-message">Entry saved</span></div>').join('');
  document.body.appendChild(host);
  const out = {};
  for (const toast of host.querySelectorAll('.toast')) {
    out[toast.dataset.v] = {
      bg: getComputedStyle(toast).backgroundColor,
      fg: getComputedStyle(toast.querySelector('.toast-message')).color,
    };
  }
  host.remove();
  return JSON.stringify(out);
})()
"""

THEME = ("(() => {{ _wimiApplyThemeVariables('{0}'); "
         "return JSON.stringify({{ok: true}}); }})()")

READY = ("(() => (typeof _wimiApplyThemeVariables === 'function' && document.body)"
         " ? JSON.stringify({ready: true}) : null)()")


def _measure(wimi_page: WimiPage, theme: str) -> dict:
    wimi_page.eval_js(THEME.format(theme))
    return json.loads(wimi_page.eval_js(
        MEASURE.replace('__COLOURED__', json.dumps(COLOURED))))


def _open_dashboard(wimi_page: WimiPage) -> None:
    """The analytics dashboard is one of the two pages that link toast.css."""
    wimi_page.goto('analytics')
    for _ in range(100):
        if wimi_page.eval_js(READY) is not None:
            return
        wimi_page.wait_for_timeout(200)
    raise AssertionError('themes.js never loaded on the analytics dashboard')


@pytest.mark.slow
@pytest.mark.regression
def test_coloured_toasts_clear_wcag_aa_in_every_theme(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """All 18 coloured cells, plus info as the untouched control."""
    _open_dashboard(wimi_page)

    for theme in THEMES:
        measured = _measure(wimi_page, theme)
        for variant in COLOURED + ['info']:
            bg, fg = measured[variant]['bg'], measured[variant]['fg']
            assert not is_transparent(bg), (
                f'.toast-{variant} has no background under {theme} ({bg!r}). A '
                'var() naming an undefined token with no fallback is discarded '
                'at computed-value time, so this is what a deleted --color-'
                f'{variant}-dark definition in styles.css looks like.')
            ratio = contrast_ratio(fg, bg)
            assert ratio >= AA_BODY_TEXT, (
                f'.toast-{variant} renders {fg} on {bg} under {theme} — '
                f'{ratio:.2f}:1, below the {AA_BODY_TEXT}:1 body-text bar. The '
                'slab and the text have to be decided together: .toast takes '
                'its colour from var(--color-white), which inverts in Midnight '
                'and High Contrast, so a background that does not invert with '
                'it is dark-on-dark there (#110).')


@pytest.mark.slow
@pytest.mark.regression
def test_only_the_two_inverting_themes_moved(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """(b)'s claim: four themes keep the exact slab they had, two do not.

    Without this, a revert to ``var(--color-success-dark, #166534)`` would
    still satisfy the ratio test in the four themes that were never broken,
    and the suite would report four sixths of a working fix.
    """
    _open_dashboard(wimi_page)

    for theme in THEMES:
        measured = _measure(wimi_page, theme)
        for variant in COLOURED:
            bg = measured[variant]['bg']
            if theme in UNCHANGED_THEMES:
                assert bg == LEGACY_SLAB[variant], (
                    f'.toast-{variant} renders {bg} under {theme}, but this '
                    f'theme does not invert --color-white, so the slab should '
                    f'still be {LEGACY_SLAB[variant]} — unchanged from before '
                    '#110. A different colour here means the :root value '
                    f'moved, or that this theme grew a --color-{variant}-dark '
                    'entry it does not need.')
            else:
                assert bg != LEGACY_SLAB[variant], (
                    f'.toast-{variant} renders {LEGACY_SLAB[variant]} under '
                    f'{theme}, the pre-#110 literal. This theme inverts '
                    '--color-white, so the slab must follow it. A value '
                    f'pinned here means --color-{variant}-dark is not reaching '
                    'the theme dictionary: either it was dropped from '
                    'themes.js, or the declaration went back to carrying a '
                    'hardcoded fallback.')
