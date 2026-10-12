"""Regression: the overview's bars take their colour from a token (#346).

What was wrong
--------------
``getPieColor()`` held fifteen literal hexes and the donut's slices and
legend swatches used them directly. Measured in #346's audit: the swatches
rendered the identical ``rgb(37,99,235) / rgb(124,58,237) / rgb(5,150,105)
/ rgb(217,119,6) / rgb(220,38,38)`` under ``default`` (``--bg-primary:
#ffffff``), ``midnight`` (``#0f172a``) **and** ``high_contrast``
(``#000000``). Eleven roots also ran the series blue -> violet -> indigo
and red -> rose, which are hard to tell apart at a 12 px swatch.

Replacing the ring with one axis made the palette question moot rather than
deferred (#346, owner, 2026-10-04): there is no series, so there is one
fill, and it is the same ``--color-primary`` the rest of the app paints a
fill with.

What is asserted, and what deliberately is not
----------------------------------------------
Asserted: the mark's colour **is** the resolved ``--color-primary``, by
comparing against a probe element painted with that token rather than by
matching a string -- so any literal, in any notation, fails. And none of
the fifteen retired hexes is painted anywhere in the overview, under any
theme, which is the guard against a categorical series coming back.

Not asserted: a contrast threshold between the mark and its track. The
figures are printed below, and on the light themes they sit under 3:1 --
but that is a property of the bright ``--color-primary`` itself, which
#325 settled stays bright for fills and borders ("do not fix it in
passing: the fills are a palette design question"). A threshold here would
settle that question sideways. What *is* checked is that the component is
themed at all: the track moves between a light theme and a dark one.

Measured rendered, after the transition settles -- a ``getComputedStyle``
taken straight after a theme switch returns mid-transition values, which
has produced two wrong colour tables in this repo already.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import open_tree_editor, seed_step1_roots

# The series `getPieColor()` held. Normalised to the rgb() spelling
# `getComputedStyle` returns, so a reintroduction is caught however it is
# written in the source.
RETIRED_PALETTE = {
    "rgb(37, 99, 235)", "rgb(124, 58, 237)", "rgb(5, 150, 105)",
    "rgb(217, 119, 6)", "rgb(220, 38, 38)", "rgb(8, 145, 178)",
    "rgb(79, 70, 229)", "rgb(22, 163, 74)", "rgb(202, 138, 4)",
    "rgb(225, 29, 72)", "rgb(6, 182, 212)", "rgb(139, 92, 246)",
    "rgb(34, 197, 94)", "rgb(234, 179, 8)", "rgb(244, 63, 94)",
}

APPLY_THEME = """
(() => {
  _wimiApplyThemeVariables(%(t)r);
  _wimiApplyColourPreferences(Object.assign(
      {}, window.wimiPreferences, {theme_name: %(t)r}));
  return 1;
})()
"""

READ_COLOURS = """
(() => {
  // A probe painted with the token itself: comparing against this makes the
  // assertion "the mark uses --color-primary", not "the mark is #2196F3".
  const probe = document.createElement('div');
  probe.style.background = 'var(--color-primary)';
  probe.style.position = 'absolute';
  probe.style.left = '-9999px';
  document.body.appendChild(probe);
  const token = getComputedStyle(probe).backgroundColor;
  probe.remove();
  const marks = [...document.querySelectorAll('.weight-range-mark')]
      .map(e => getComputedStyle(e).backgroundColor);
  // Every painted colour in the overview, for the retired-palette sweep.
  const painted = new Set();
  for (const el of document.querySelectorAll('.exam-overview, .exam-overview *')) {
    const cs = getComputedStyle(el);
    painted.add(cs.backgroundColor);
    painted.add(cs.color);
    painted.add(cs.borderTopColor);
    painted.add(cs.fill);
  }
  const track = document.querySelector('.weight-range-track');
  return {
    token, marks: [...new Set(marks)], painted: [...painted],
    track: track ? getComputedStyle(track).backgroundColor : null,
    panel: getComputedStyle(document.getElementById('details-panel'))
             .backgroundColor,
  };
})()
"""


def _luminance(css_rgb: str) -> float:
    nums = [float(n) for n in css_rgb.replace("rgba", "rgb")
            .split("(")[1].split(")")[0].split(",")[:3]]
    chan = []
    for n in nums:
        s = n / 255
        chan.append(s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.slow
@pytest.mark.regression
def test_the_bars_are_painted_from_a_token_and_the_old_series_is_gone(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    seeded = seed_step1_roots(wimi_session.user.db, "W346 Colour")
    open_tree_editor(wimi_page, seeded["exam"].id)

    themes = ("default", "midnight", "high_contrast", "forest", "ocean",
              "sunset")
    read: dict[str, dict] = {}
    for theme in themes:
        wimi_page.eval_js(APPLY_THEME % {"t": theme})
        # `.weight-range-row { transition: background-color }` and the page's
        # own theme transitions have to land before anything is read.
        wimi_page.wait_for_timeout(900)
        read[theme] = wimi_page.eval_js(READ_COLOURS)

    backgrounds = {v["panel"] for v in read.values()}
    assert len(backgrounds) >= 3, (
        f"the sweep applied {len(themes)} themes and produced "
        f"{len(backgrounds)} distinct panel backgrounds ({backgrounds!r}). "
        f"A sweep that silently applies one theme six times passes every "
        f"colour assertion for the wrong reason.")

    for theme, v in read.items():
        assert v["marks"], f"{theme}: no bar was drawn at all"
        assert v["marks"] == [v["token"]], (
            f"{theme}: the bars paint {v['marks']!r} and --color-primary "
            f"resolves to {v['token']!r}. A fill that is not the token is a "
            f"literal, which is what made the donut's swatches identical "
            f"under a white, a navy and a black background.")
        bad = RETIRED_PALETTE.intersection(v["painted"])
        assert not bad, (
            f"{theme}: {sorted(bad)} is painted in the Exam Overview. Those "
            f"are getPieColor()'s retired hexes; a categorical series has "
            f"come back (#346).")

    # The surrounding chrome is themed even though the fill is the student's
    # own accent colour: without this the whole component could be literals
    # and the token assertion above would still pass on a one-theme run.
    light, dark = read["default"]["track"], read["midnight"]["track"]
    assert light != dark, (
        f"the bar track renders {light} on `default` and {dark} on "
        f"`midnight` -- identical, i.e. not themed.")

    print("\nmark vs track contrast, rendered, settled:")
    for theme, v in read.items():
        print(f"  {theme:<14} mark {v['token']:<20} track {v['track']:<20} "
              f"{_contrast(v['token'], v['track']):.2f}:1")
