"""The difficulty and time card's colours clear their bars on every theme (#898 Wave 2).

``docs/planning/DIFFICULTY_TIME_CARD_PLAN.md`` *Colours* names the tokens and
the rules, and the owner delegated the values (#898 comment 12219). This is
the static sweep the plan asks for, built the way
``tests/test_theme_text_contrast.py`` is built and on its readers, so a
seventh theme is checked the day it is added:

* **Marks at 3:1** (WCAG 1.4.11). Each series colour, ``--dt-series-many``,
  ``--dt-dot-nonmatch`` and ``--text-primary`` (the All-mode dot, the ring
  and the median line) against both bands, the middle band
  (``--bg-tertiary``) and the page (``--bg-primary``). The plan names "both
  bands and ``--bg-primary``"; the middle band is added because the scatter
  draws dots on it too, and it costs nothing.
* **Text at 4.5:1 on the card tints.** A quadrant card is painted on a band
  and carries the theme's primary and secondary text and its primary-coloured
  link text.
* **The four series colours are pairwise distinct** -- not merely different
  hex strings, but far enough apart to tell two dots apart. Measured as
  Euclidean distance in sRGB, a coarse instrument chosen because it is easy
  to read; the bar is :data:`MIN_SERIES_DISTANCE`.

**Every token must be listed by every theme but Default.** A theme reaches
only the names its dictionary lists (``check_css_tokens.py``'s *Repoint, do
not define* note); a dark theme that forgot one would paint the light value
on a dark band. Default's dictionary is empty by design and falls through to
``:root``, which ``test_theme_text_contrast.py`` already asserts.
"""
from __future__ import annotations

import itertools
import math

import pytest

from tests.test_theme_text_contrast import (
    ROOT, THEMES, _ratio, _resolve, _rgb)

pytestmark = pytest.mark.unit

MARK_CONTRAST = 3.0
TEXT_CONTRAST = 4.5
#: About a fifth of the sRGB cube's diagonal (441). The shipped light series
#: are 150+ apart and the dark ones 100+.
MIN_SERIES_DISTANCE = 90.0

SERIES = ["--dt-series-1", "--dt-series-2", "--dt-series-3", "--dt-series-4"]
MARKS = SERIES + ["--dt-series-many", "--dt-dot-nonmatch", "--text-primary"]
MARK_SLABS = ["--dt-band-hard", "--dt-band-easy", "--bg-tertiary",
              "--bg-primary"]
TINTS = ["--dt-band-hard", "--dt-band-easy"]
TINT_TEXT = ["--text-primary", "--text-secondary", "--color-primary-text"]
DT_TOKENS = ["--dt-band-hard", "--dt-band-hard-border", "--dt-band-easy",
             "--dt-band-easy-border", *SERIES, "--dt-series-many",
             "--dt-dot-nonmatch"]

THEME_NAMES = sorted(THEMES)


def _value(token: str, theme: str) -> str:
    return _resolve(token, THEMES[theme], ROOT)


def test_the_sweep_found_every_theme() -> None:
    """Guard the guard: a reader that found nothing would pass everything."""
    assert len(THEME_NAMES) >= 6, (
        f"found {len(THEME_NAMES)} themes; the six that ship are default, "
        f"midnight, warm_study, forest, nord and high_contrast")
    assert {"default", "midnight", "high_contrast"} <= set(THEME_NAMES)
    for token in DT_TOKENS:
        assert token in ROOT, f"{token} is not defined in styles.css :root"


@pytest.mark.parametrize("theme", [t for t in THEME_NAMES if t != "default"])
def test_every_theme_lists_every_token(theme: str) -> None:
    missing = [t for t in DT_TOKENS if t not in THEMES[theme]]
    assert not missing, (
        f"{theme} does not list {missing}, so it would paint the light "
        f":root value whatever its own palette is")


@pytest.mark.parametrize("theme", THEME_NAMES)
def test_marks_reach_3_to_1_on_every_band_and_the_page(theme: str) -> None:
    faults = []
    for mark in MARKS:
        for slab in MARK_SLABS:
            ratio = _ratio(_value(mark, theme), _value(slab, theme))
            if ratio < MARK_CONTRAST:
                faults.append(f"{mark} on {slab}: {ratio:.2f}:1")
    assert not faults, f"{theme}: " + "; ".join(faults)


@pytest.mark.parametrize("theme", THEME_NAMES)
def test_text_reaches_4_5_to_1_on_the_card_tints(theme: str) -> None:
    faults = []
    for text in TINT_TEXT:
        for tint in TINTS:
            ratio = _ratio(_value(text, theme), _value(tint, theme))
            if ratio < TEXT_CONTRAST:
                faults.append(f"{text} on {tint}: {ratio:.2f}:1")
    assert not faults, f"{theme}: " + "; ".join(faults)


@pytest.mark.parametrize("theme", THEME_NAMES)
def test_the_four_series_colours_are_distinct(theme: str) -> None:
    values = {s: _rgb(_value(s, theme)) for s in SERIES}
    faults = []
    for a, b in itertools.combinations(SERIES, 2):
        distance = math.dist(values[a], values[b])
        if distance < MIN_SERIES_DISTANCE:
            faults.append(f"{a} and {b}: {distance:.0f}")
    assert not faults, f"{theme}: too close to tell apart: " + "; ".join(faults)


def test_the_bars_can_fail() -> None:
    """The control: each instrument rejects a value it should reject."""
    assert _ratio("#9ca3af", "#ffedd5") < MARK_CONTRAST   # a faint grey dot
    assert _ratio("#60a5fa", "#dbeafe") < TEXT_CONTRAST   # light text on a tint
    assert math.dist(_rgb("#6d28d9"), _rgb("#7c3aed")) < MIN_SERIES_DISTANCE
