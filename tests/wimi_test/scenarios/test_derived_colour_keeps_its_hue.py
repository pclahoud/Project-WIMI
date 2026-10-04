"""Regression: a colour derived from the student's primary keeps its hue.

Forgejo issue #307 -- "[bug] A custom primary colour produces an off-palette
cyan, because ``_adjustColor`` adds a flat +180 per channel". The argument for
a proportional mix, the measured hue collapse of all six theme primaries, and
the guards that keep one mixer rather than two are in
``tests/test_web_derived_colour.py``; this file pins the arithmetic and the two
paths that use it.

Why a table of exact outputs rather than a screenshot: the conversion is a
pure function of one hex string, so every claim about it is checkable without
rendering anything -- and the thing that was wrong is not visible at all for
an unsaturated colour, which is how three tokens shipped like this. The table
is evaluated by the **shipped** function in the **real engine**, so it covers
Chromium's rounding rather than a reimplementation's.

Two inputs are here because clipping is worst at the bounds: ``#fefefe``
(lighten has one level of headroom) and ``#010101`` (darken has one). The old
code turned ``#010101`` into ``#b5b5b5`` for the background token -- not
wrong-hued, because grey has no hue, which is exactly why a mid-tone test
alone would have passed.

Tests 2 and 3 are the two appliers, and both are needed: #307 existed twice,
and ``themes.js``'s copy -- the one that runs on **every page load** -- is the
one the issue did not name. A fix verified only on Settings leaves every other
surface producing the cyan.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import colorsys
import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# The issue's measured case. Forest's primary; the pre-fix +180 made it a
# bright cyan, 18.6 degrees of hue away and fully saturated.
PRIMARY = '#059669'
PRE_FIX_BG = '#b9ffff'

# input -> [hover, light, bg], as the shipped mixer must return them. The six
# theme primaries, both near-bounds, both bounds, pure red (one channel at
# each extreme) and one colour with no channel near a bound.
TABLE = {
    '#059669': ['#05875f', '#199e75', '#daefe9'],
    '#2563eb': ['#2159d4', '#366fed', '#dee8fc'],
    '#60a5fa': ['#5695e1', '#6dacfa', '#e7f2fe'],
    '#b45309': ['#a24b08', '#ba611d', '#f4e5da'],
    '#5e81ac': ['#55749b', '#6b8bb3', '#e7ecf3'],
    '#3391ff': ['#2e83e6', '#439aff', '#e0efff'],
    '#ff0000': ['#e60000', '#ff1414', '#ffd9d9'],
    '#fefefe': ['#e5e5e5', '#fefefe', '#ffffff'],
    '#010101': ['#010101', '#151515', '#d9d9d9'],
    '#ffffff': ['#e6e6e6', '#ffffff', '#ffffff'],
    '#000000': ['#000000', '#141414', '#d9d9d9'],
    '#7f3fbf': ['#7239ac', '#894ec4', '#ece2f5'],
}

# The ratios the applier uses, in the order TABLE's lists are written.
RATIOS = [-0.10, 0.08, 0.85]

# 8-bit rounding is the only hue movement a proportional mix can cause. The
# worst case over this table is 1.9 degrees (a low-saturation blue at t=0.85,
# where the channel spread has shrunk to ~20 levels so one level is ~1 degree).
# The pre-fix code moved 18.6-41.2 degrees, or destroyed the hue outright.
HUE_TOLERANCE_DEG = 2.0

MIX = """
(() => {
  if (typeof _wimiMixColor !== 'function') return JSON.stringify({missing: true});
  const table = __TABLE__, ratios = __RATIOS__;
  const out = {};
  for (const hex of Object.keys(table)) out[hex] = ratios.map(t => _wimiMixColor(hex, t));
  return JSON.stringify({missing: false, out: out});
})()
"""

TOKENS = """
(() => { const cs = getComputedStyle(document.documentElement);
  const get = (n) => cs.getPropertyValue(n).trim().toLowerCase();
  return JSON.stringify({
    marker: window.__w307 === 1,
    primary: get('--color-primary'),
    hover: get('--color-primary-hover'),
    light: get('--color-primary-light'),
    bg: get('--color-primary-bg')
  }); })()
"""

PREFS_LOADED = "document.getElementById('primary_color_hex').value !== ''"


def _hue_sat(hex_colour: str) -> tuple[float, float]:
    raw = hex_colour.lstrip('#')
    r, g, b = (int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, _, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s * 100


def _hue_drift(before: str, after: str) -> float:
    (h0, _), (h1, _) = _hue_sat(before), _hue_sat(after)
    delta = abs(h1 - h0)
    return min(delta, 360 - delta)


def _assert_keeps_hue(source: str, derived: str, label: str) -> None:
    """Hue is only meaningful on a colour that has one, so grey is skipped."""
    if min(_hue_sat(source)[1], _hue_sat(derived)[1]) < 1:
        return
    drift = _hue_drift(source, derived)
    assert drift <= HUE_TOLERANCE_DEG, (
        f'{label}: {source} derived {derived}, {drift:.1f} degrees of hue away. '
        'A derived colour may change lightness, not hue -- #307 shipped a flat '
        f'per-channel offset, which clipped and turned {PRIMARY} into '
        f'{PRE_FIX_BG}, a cyan.'
    )


def _poll(wimi_page: WimiPage, js: str, *, fresh: bool = False,
          timeout_ms: int = 10000) -> dict:
    elapsed, last = 0, {}
    while elapsed < timeout_ms:
        try:
            last = json.loads(wimi_page.eval_js(js))
        except Exception:  # context torn down mid-navigation
            last = {}
        if last.get('bg') and not (fresh and last.get('marker')):
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


@pytest.mark.slow
@pytest.mark.regression
def test_the_shipped_mixer_matches_the_table(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The arithmetic, in the engine that runs it."""
    wimi_page.goto('dashboard')
    probe = json.loads(wimi_page.eval_js(
        MIX.replace('__TABLE__', json.dumps(TABLE)).replace('__RATIOS__', json.dumps(RATIOS))
    ))
    assert probe['missing'] is False, (
        '_wimiMixColor is not defined on a loaded page. It replaces the '
        'additive _wimiAdjustColor (#307) and lives in themes.js, which every '
        'page links.'
    )
    assert probe['out'] == {k: v for k, v in TABLE.items()}, (
        f'The mixer does not match the table.\n  expected {TABLE}\n  got      '
        f'{probe["out"]}'
    )
    for source, derived in probe['out'].items():
        for hex_out, ratio in zip(derived, RATIOS):
            _assert_keeps_hue(source, hex_out, f'ratio {ratio:+.2f}')

    # Control: the pre-fix arithmetic, evaluated here, does NOT satisfy the
    # assertion above -- so the table and the tolerance discriminate.
    old = wimi_page.eval_js(
        "(() => { const c = [5, 150, 105].map(v => Math.max(0, Math.min(255, v + 180)));"
        " return '#' + c.map(v => v.toString(16).padStart(2, '0')).join(''); })()"
    )
    assert old == PRE_FIX_BG, f'The control did not reproduce the filed value: {old!r}'
    assert _hue_drift(PRIMARY, old) > HUE_TOLERANCE_DEG, (
        f'The pre-fix value {old} is within the hue tolerance of {PRIMARY}, so '
        'this test cannot tell the fix from the bug.'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_a_stored_primary_derives_in_hue_on_every_page(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """themes.js's page-load applier -- the copy the issue did not name.

    Asserted away from Settings on purpose: the surfaces #307 lists
    (``browser.css``, the exam badges, the deep dive) are rendered by this
    path and never by the live preview.
    """
    db = wimi_session.user.db
    db.update_preferences(primary_color_hex=PRIMARY)
    wimi_page.goto('dashboard')
    wimi_page.eval_js('window.__w307 = 1')
    wimi_page.goto('entry-browser')
    got = _poll(wimi_page, TOKENS, fresh=True)

    assert got.get('primary') == PRIMARY, (
        f'The stored primary did not reach the page: {got!r}'
    )
    assert got['bg'] != PRE_FIX_BG, (
        f'--color-primary-bg is {got["bg"]} on the entry browser, the value '
        f'#307 measured: a flat +180 clipped green and blue to 255 while red '
        'landed at 185, so a green became a cyan.'
    )
    for name in ('hover', 'light', 'bg'):
        _assert_keeps_hue(PRIMARY, got[name], f'--color-primary-{name}')


@pytest.mark.slow
@pytest.mark.regression
def test_choosing_a_primary_previews_in_hue(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """settings.js's live preview -- the copy the issue did name."""
    wimi_page.goto('settings')
    elapsed = 0
    while elapsed < 10000 and wimi_page.eval_js(PREFS_LOADED) is not True:
        wimi_page.wait_for_timeout(100)
        elapsed += 100

    wimi_page.eval_js(
        "(() => { const el = document.getElementById('primary_color_hex_picker');"
        f" el.value = {PRIMARY!r};"
        " el.dispatchEvent(new Event('input', {bubbles: true})); })()"
    )
    elapsed, got = 0, {}
    while elapsed < 5000:
        got = _poll(wimi_page, TOKENS)
        if got.get('primary') == PRIMARY:
            break
        wimi_page.wait_for_timeout(100)
        elapsed += 100

    assert got.get('primary') == PRIMARY, (
        f'Picking {PRIMARY} did not preview at all: {got!r}'
    )
    assert got['bg'] != PRE_FIX_BG, (
        f'The live preview derived {got["bg"]} from {PRIMARY} -- #307 verbatim.'
    )
    for name in ('hover', 'light', 'bg'):
        _assert_keeps_hue(PRIMARY, got[name], f'preview --color-primary-{name}')
