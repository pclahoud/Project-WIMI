"""Regression: the entry browser's search icon covers the first character.

Forgejo issue #309 -- "[bug] Entry browser: the search icon sits on top of
the first character of the search text":

    Visible in the screenshot: the placeholder reads **"earch entries..."**
    -- the magnifier glyph covers the leading "S". [...] ``.search-icon`` is
    absolutely positioned at ``left: 0.75rem``, and ``.search-input`` has
    ``padding-left: 2.25rem``. At this font and this emoji's rendered width
    the glyph is wider than the gap the padding leaves, so it overlaps.
    **Typed text is overlapped the same way**, not just the placeholder.

    Emoji advance width varies by platform font, so this may look fine on
    macOS and Linux and wrong on Windows [...] A non-emoji icon, or sizing
    the padding from the icon's measured width, is more robust than nudging
    the constant.

Why a measurement of this machine's emoji is not enough
-------------------------------------------------------
The issue was measured on Windows, and it says plainly that the same CSS may
look fine here. So the obvious test -- measure the gap, assert it is positive
-- can pass on this box against the unfixed page, which makes it a test of
the local font rather than of the layout. A constant tuned until that test
goes green would be exactly the fix the issue warns against.

What is asserted instead is the property that makes a platform irrelevant:

1. the icon does not reach past where the input's text starts, at the real
   rendered width; and
2. **the input's text origin moves when the icon gets wider.**

(2) is the decisive one. It says the space is *reserved* from the icon's
actual box rather than guessed by a constant, so any emoji font on any
platform is accommodated by construction -- and it fails on the pre-fix
layout regardless of what this machine's magnifier measures, because an
absolutely positioned icon is out of flow and a fixed ``padding-left``
cannot respond to it. (3) then re-checks (1) at the widened size.

Widening by font-size rather than by swapping in a wider glyph keeps the
probe honest about what it is simulating: a font whose advance for the same
character is larger, which is the variable the issue names.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Stand-in for a platform whose emoji font has a much larger advance. The
# pre-fix geometry left 24 CSS px between the icon's left edge and the input's
# text origin (left: 0.75rem, padding-left: 2.25rem), so this is comfortably
# past it on any font.
WIDENED_PX = 40

GEOMETRY = """
(() => {
  const icon = document.querySelector('.search-icon');
  const input = document.querySelector('.search-input');
  if (!icon || !input) return JSON.stringify({found: false});
  const widen = __WIDEN__;
  if (widen) icon.style.fontSize = widen + 'px';
  const cs = getComputedStyle(input);
  const ir = icon.getBoundingClientRect();
  const nr = input.getBoundingClientRect();
  // Where the first character is painted: the input's content box, i.e. past
  // its border and padding. Nothing here sets text-indent or direction: rtl.
  const textLeft = nr.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft);
  return JSON.stringify({
    found: true,
    iconLeft: ir.left, iconRight: ir.right, iconWidth: ir.width,
    inputLeft: nr.left, inputWidth: nr.width,
    textLeft: textLeft,
    paddingLeft: parseFloat(cs.paddingLeft),
    glyph: icon.textContent.trim(),
    // Positive means the icon is painted over the start of the text.
    overlapPx: ir.right - textLeft
  });
})()
"""

# The search box is inside the container #122 gates, so measure once the gate
# has handed over -- a box measured mid-load is not the one a student sees.
RELEASED = (
    "(() => { const el = document.querySelector('[data-page-gated]');"
    " return !!el && !el.hasAttribute('inert'); })()"
)


def _geometry(wimi_page: WimiPage, widen: int = 0) -> dict:
    return json.loads(wimi_page.eval_js(GEOMETRY.replace('__WIDEN__', str(widen or 0))))


def _open_browser(wimi_page: WimiPage) -> None:
    wimi_page.goto('entry-browser')
    elapsed = 0
    while elapsed < 15000 and wimi_page.eval_js(RELEASED) is not True:
        wimi_page.wait_for_timeout(100)
        elapsed += 100


@pytest.mark.slow
@pytest.mark.regression
def test_the_icon_does_not_reach_the_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """At the real rendered width, on this platform's font."""
    _open_browser(wimi_page)
    geo = _geometry(wimi_page)

    assert geo['found'], 'The search icon or input is not on the entry browser'
    assert geo['iconWidth'] > 0 and geo['inputWidth'] > 0, (
        f'The search box is not laid out, so nothing measured here is what a '
        f'student sees: {geo!r}'
    )
    assert geo['overlapPx'] <= 0, (
        f'The {geo["glyph"]!r} icon ends {geo["overlapPx"]:.1f} px past where '
        f'the input paints its first character, so the placeholder reads '
        f'"earch entries..." (#309). Icon {geo["iconLeft"]:.1f}-'
        f'{geo["iconRight"]:.1f} px, text starts at {geo["textLeft"]:.1f} px.'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_the_text_origin_follows_the_icon_width(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The space is reserved from the icon's box, not guessed by a constant.

    This is the whole platform-independence claim, and it is the assertion
    that fails on the pre-fix layout on *every* platform -- including the ones
    where the shipped emoji happens to fit.
    """
    _open_browser(wimi_page)
    before = _geometry(wimi_page)
    assert before['found'] and before['iconWidth'] > 0, before

    after = _geometry(wimi_page, widen=WIDENED_PX)
    assert after['iconWidth'] > before['iconWidth'], (
        f'Setting font-size: {WIDENED_PX}px did not widen the icon '
        f'({before["iconWidth"]:.1f} -> {after["iconWidth"]:.1f} px), so this '
        'test is not simulating a wider emoji font and proves nothing.'
    )
    grew = after['textLeft'] - before['textLeft']
    assert grew > 0, (
        f'The icon grew {after["iconWidth"] - before["iconWidth"]:.1f} px and '
        f'the input\'s text origin did not move ({before["textLeft"]:.1f} -> '
        f'{after["textLeft"]:.1f} px). The gap is a fixed padding-left rather '
        'than space the icon reserves, so whether the glyph fits depends on '
        'the platform\'s emoji advance width -- which is exactly what #309 '
        'says must not decide it.'
    )
    assert after['overlapPx'] <= 0, (
        f'With a {WIDENED_PX}px icon the glyph still ends '
        f'{after["overlapPx"]:.1f} px past the text origin: {after!r}'
    )
