"""Regression: a dark theme keeps a dark primary tint, and the label on it is readable.

Forgejo issues #322 (the tint direction), #325 (the label), #111 (the surface
step). The values are barred statically by ``tests/test_theme_text_contrast.py``,
which costs milliseconds and stops a seventh theme shipping a failing one.
Three things that file **cannot** establish, which is why this scenario exists:

* **That the derived tint is what paints.** The static guard *models*
  ``_wimiApplyColourPreferences`` -- it ports ``_wimiMixColor`` and parses the
  two magnitudes out of ``themes.js``. A model can be a faithful model of the
  wrong thing. Here the real applier runs in the real engine and the result is
  read off ``getComputedStyle``, so "the dictionary's ``--color-primary-bg``
  never paints" is observed rather than argued.
* **That the cascade delivers the token to the element.** #325 repointed 129
  ``color:`` declarations. A token can be correct and still not reach a node --
  ``styles.css``'s ``input[type="text"]`` outranking ``.search-input`` is the
  worked example (#309), and a class cannot be seen by any sweep over values.
* **The composited background.** A chip's label sits on a tint over a card over
  a page, and only a render knows what that stack resolves to.

**Transitions are switched off, and that is load-bearing rather than tidy.**
Reading ``getComputedStyle`` shortly after a theme is applied returns
*mid-transition* colours -- measured at ``#9dabbb`` and ``#c2c4c5``, values in
no palette -- because §12c's harness fix made CSS transitions actually
advance. An earlier run of this measurement reported 37 failures on a page that
settles to 9. The page is given the same ``transition-duration: 0s`` tag the
``show_animations: false`` preference injects, rather than a longer sleep,
because a sleep is a guess about a machine.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.db.seeders import seed_multi_dimensional
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

AA_BODY_TEXT = 4.5

# Midnight and High Contrast. Named rather than derived from luminance so the
# test states which themes it is about; the static guard owns the general rule.
DARK_THEMES = ('midnight', 'high_contrast')
LIGHT_THEMES = ('default', 'warm_study', 'forest', 'nord')
THEMES = LIGHT_THEMES[:1] + DARK_THEMES + LIGHT_THEMES[1:]

NO_TRANSITIONS = """
(() => {
  let s = document.getElementById('scenario-no-anim');
  if (!s) {
    s = document.createElement('style');
    s.id = 'scenario-no-anim';
    s.textContent = '*, *::before, *::after { transition-duration: 0s'
      + ' !important; animation-duration: 0s !important; }';
    document.head.appendChild(s);
  }
  return JSON.stringify({ok: true});
})()
"""

# Apply the theme and then the colour preferences, exactly as the page-load
# IIFE does -- with primary_color_hex set to the theme's own, which is what
# settings.js's _applyThemeToColorPickers stores when a theme is chosen.
# Then build a real primary chip and read the cascade off it.
MEASURE = """
(() => {
  const name = '%(theme)s';
  const theme = window.WIMI_THEMES[name];
  _wimiApplyThemeVariables(name);
  _wimiApplyColourPreferences({
    theme_name: name,
    primary_color_hex: theme.primaryColorHex,
    secondary_color_hex: theme.secondaryColorHex,
  });

  const host = document.createElement('div');
  document.body.appendChild(host);
  host.innerHTML = '<span class="subject-chip primary">'
    + '<span class="subject-name">Heart Failure</span></span>';
  const chip = host.querySelector('.subject-chip.primary');
  const label = host.querySelector('.subject-name');

  const probe = document.createElement('span');
  document.body.appendChild(probe);
  const token = (value) => {
    probe.style.cssText = '';
    probe.style.setProperty('background-color', value);
    return getComputedStyle(probe).backgroundColor;
  };

  const out = {
    chipBackground: getComputedStyle(chip).backgroundColor,
    labelColour: getComputedStyle(label).color,
    labelOpacity: getComputedStyle(label).opacity,
    bgPrimary: token('var(--bg-primary)'),
    bgSecondary: token('var(--bg-secondary)'),
    bgTertiary: token('var(--bg-tertiary)'),
    primaryBgToken: token('var(--color-primary-bg)'),
    // The control: what the pre-#322 arithmetic would have produced here.
    preFixTint: _wimiMixColor(theme.primaryColorHex, 0.85),
  };
  host.remove();
  probe.remove();
  return JSON.stringify(out);
})()
"""


def _rgb(value: str) -> tuple[float, float, float]:
    """``rgb()`` / ``rgba()`` / ``color(srgb ...)`` / ``#rrggbb`` -> 8-bit sRGB.

    Both notations are needed in one test. ``getComputedStyle`` hands back a
    functional form, while ``_wimiMixColor`` -- called directly for the
    pre-#322 control -- returns the hex it builds. Qt 6.9's Chromium also
    reports a resolved ``color-mix()`` as ``color(srgb 0.086 ...)``, floats in
    0..1, which is why that branch exists at all.
    """
    value = value.strip()
    if value.startswith('#'):
        body = value[1:]
        if len(body) == 3:
            body = ''.join(c * 2 for c in body)
        return tuple(float(int(body[i:i + 2], 16)) for i in (0, 2, 4))  # type: ignore[return-value]
    nums = [float(n) for n in
            value[value.index('(') + 1:value.rindex(')')]
            .replace('/', ' ').replace(',', ' ').split()]
    if value.startswith('color('):
        nums = [n * 255 for n in nums[:3]]
    return tuple(nums[:3])  # type: ignore[return-value]


def _luminance(value: str) -> float:
    def channel(c: float) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a: str, b: str) -> float:
    x, y = _luminance(a), _luminance(b)
    if x < y:
        x, y = y, x
    return (x + 0.05) / (y + 0.05)


def _lightness(value: str) -> float:
    y = _luminance(value)
    return 116 * (y ** (1 / 3)) - 16 if y > 0.008856 else 903.3 * y


def _measure_all(page: WimiPage) -> dict[str, dict]:
    page.eval_js(NO_TRANSITIONS)
    return {theme: json.loads(page.eval_js(MEASURE % {'theme': theme}))
            for theme in THEMES}




@pytest.mark.slow
@pytest.mark.regression
def test_a_dark_theme_keeps_a_dark_primary_tint(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#322: the derived tint overwrote the curated one with a pale blue.

    ``prefs.primary_color_hex`` has a column default and a dataclass default,
    so the derivation always fires; before #322 it always mixed toward white,
    and Midnight's badges and input focus rings got a light slab on a
    near-black page.

    The ``preFixTint`` control is the point of this test rather than decoration:
    it is the pre-#322 arithmetic evaluated by the shipped mixer on the same
    input, so the assertion compares what paints against what used to, in the
    same engine. Without it, "the tint is dark" would also pass on a build
    where the derivation had simply stopped running.
    """
    seed_multi_dimensional(wimi_session.user.db)
    wimi_page.goto('entry-browser')
    wimi_page.wait_for_timeout(2500)
    state = _measure_all(wimi_page)

    for theme in DARK_THEMES:
        got = state[theme]
        page = _luminance(got['bgPrimary'])
        tint = _luminance(got['chipBackground'])
        assert tint < 0.18, (
            f"{theme}: the primary tint paints {got['chipBackground']} "
            f"(luminance {tint:.3f}) on a page whose --bg-primary is "
            f"{got['bgPrimary']} ({page:.3f}). A dark theme's "
            "--color-primary-bg has to be a dark tint (#322)."
        )
        assert _luminance(got['preFixTint']) > 0.5, (
            f"{theme}: the pre-#322 arithmetic (_wimiMixColor toward white at "
            f"0.85) now yields {got['preFixTint']}, which is not light. This "
            "control is what makes the assertion above evidence rather than a "
            "tautology -- if it stops producing a pale tint the defect is no "
            "longer reachable and this test no longer discriminates."
        )
        assert tint > page, (
            f"{theme}: the tint {got['chipBackground']} is no lighter than the "
            f"page {got['bgPrimary']}. A badge has to be visible against the "
            "surface behind it -- mixing 85% toward black would make it a hole."
        )

    for theme in LIGHT_THEMES:
        got = state[theme]
        assert _luminance(got['chipBackground']) > 0.5, (
            f"{theme}: the primary tint paints {got['chipBackground']}, which "
            "is not light. #322 changed the DIRECTION on dark themes only; the "
            "four light themes must be untouched."
        )


@pytest.mark.slow
@pytest.mark.regression
def test_the_label_on_a_primary_tint_clears_aa_in_every_theme(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#325: ``--color-primary`` was the fill and the label, at 3.25:1 in Nord.

    Measured on a real ``.subject-chip.primary`` built in the live document, so
    the chain from the repointed declaration through the cascade to a composited
    background is exercised rather than assumed.

    ``.subject-chip.primary .dimension-label`` is deliberately NOT asserted
    here. Its token clears AA (5.90-6.92:1) and its ``opacity: 0.7`` then
    halves it back to 3.23-4.25, which is **#331** -- a de-emphasis decision
    parked behind #313/#314, not a token defect. Asserting it would make this
    file red for a reason it is not about; the exclusion is named so it is a
    carve-out rather than an oversight.
    """
    seed_multi_dimensional(wimi_session.user.db)
    wimi_page.goto('entry-browser')
    wimi_page.wait_for_timeout(2500)
    state = _measure_all(wimi_page)

    for theme in THEMES:
        got = state[theme]
        assert got['labelOpacity'] == '1', (
            f"{theme}: the chip's subject name renders at opacity "
            f"{got['labelOpacity']}, so this ratio is not the composited one. "
            "An opacity on a text node is a contrast multiplier (#331)."
        )
        ratio = _ratio(got['labelColour'], got['chipBackground'])
        assert ratio >= AA_BODY_TEXT, (
            f"{theme}: a primary chip's label renders {got['labelColour']} on "
            f"{got['chipBackground']} -- {ratio:.2f}:1, below "
            f"{AA_BODY_TEXT}:1 (#325). Note the background is the DERIVED "
            f"tint; the dictionary's --color-primary-bg is "
            f"{got['primaryBgToken']} and never paints."
        )

    # The tint that paints is the derived one in every theme, which is the
    # finding #325's own table missed -- it barred against the dictionary.
    differ = [t for t in THEMES
              if state[t]['chipBackground'] != state[t]['primaryBgToken']]
    assert not differ, (
        f"the chip background and var(--color-primary-bg) disagree in {differ}, "
        "which should be impossible -- the chip paints that very token. If this "
        "fires, the probe and the element are resolving different cascades."
    )


@pytest.mark.slow
@pytest.mark.regression
def test_a_one_step_hover_is_visible_in_every_theme(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#111: Midnight and High Contrast resolved both surface steps to one colour.

    Read off a live probe rather than the dictionary, because ``--bg-tertiary``
    is defined *from* ``--color-gray-100`` in ``styles.css`` and #111 moved
    both -- a test reading only the dictionary entry would pass a build where
    the two had been allowed to disagree again.

    The floor is Default's own step, the smallest the application ships.
    """
    seed_multi_dimensional(wimi_session.user.db)
    wimi_page.goto('entry-browser')
    wimi_page.wait_for_timeout(2500)
    state = _measure_all(wimi_page)

    floor = min(
        abs(_lightness(got['bgTertiary']) - _lightness(got['bgSecondary']))
        for got in state.values()
    )
    assert floor > 1.0, (
        f"the smallest --bg-secondary -> --bg-tertiary step across the themes "
        f"renders at {floor:.2f} L*. Every one-step hover in src/web/css is "
        "invisible in whichever theme that is (#111)."
    )
    for theme in THEMES:
        got = state[theme]
        assert got['bgSecondary'] != got['bgTertiary'], (
            f"{theme}: --bg-secondary and --bg-tertiary both render "
            f"{got['bgSecondary']}, so a hover from one to the other shows "
            "nothing at all (#111)."
        )
