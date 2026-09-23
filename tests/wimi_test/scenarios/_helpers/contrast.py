"""WCAG 2.x contrast ratio from whatever ``getComputedStyle`` hands back.

Extracted from #110's scenario so the next contrast filing does not
re-derive the formula. Two things here are not obvious and both produced a
wrong answer first time:

* Qt 6.9's Chromium reports a resolved ``color-mix()`` as
  ``color(srgb 0.086 0.396 0.204)`` — floats in 0..1 — while every other
  declaration on the same page yields an ``rgb()`` triple. A parser that
  only handles ``rgb()`` cannot measure a ``color-mix`` rule at all.
* The ratio must use real sRGB linearisation. The common shortcut
  (``(max+0.05)/(min+0.05)`` on raw channel averages) puts several of #110's
  cells on the wrong side of the 4.5:1 bar.
"""
from __future__ import annotations

AA_BODY_TEXT = 4.5


def parse_css_color(value: str) -> tuple[int, int, int]:
    """``rgb()`` / ``rgba()`` / ``color(srgb …)`` -> 8-bit sRGB."""
    inner = value[value.index('(') + 1:value.rindex(')')].strip()
    if value.startswith('color('):
        space, *rest = inner.replace('/', ' ').split()
        if space != 'srgb':
            raise ValueError(f'unhandled colour space in {value!r}')
        return tuple(  # type: ignore[return-value]
            max(0, min(255, round(float(c) * 255))) for c in rest[:3])
    parts = [p.strip() for p in inner.replace('/', ' ').split(',')]
    if len(parts) == 1:
        parts = inner.split()
    return tuple(round(float(p)) for p in parts[:3])  # type: ignore[return-value]


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.x relative luminance, with sRGB linearisation."""
    def channel(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    """``(L1 + 0.05) / (L2 + 0.05)``, lighter over darker."""
    a = relative_luminance(parse_css_color(foreground))
    b = relative_luminance(parse_css_color(background))
    if a < b:
        a, b = b, a
    return (a + 0.05) / (b + 0.05)


def is_transparent(value: str) -> bool:
    """True for the initial ``background-color``.

    A ``var()`` naming an undefined token *with no fallback* is invalid at
    computed-value time and the declaration is discarded, so the slab goes
    transparent rather than erroring. That is the shape a deleted ``:root``
    definition takes, and it has to be caught by name — a ratio computed
    against ``rgba(0, 0, 0, 0)`` reads as a very good 21:1.
    """
    return value.replace(' ', '') in ('rgba(0,0,0,0)', 'transparent')
