"""The app-wide scrollbar is themed, visible, and not silently switched off.

styles.css draws every scrollbar with `::-webkit-scrollbar` rules coloured from
theme tokens. Two ways that quietly stops working, each guarded here:

* **A thumb that disappears into the page.** A scrollbar is a control, and
  WCAG 1.4.11 asks 3:1 of it against what is behind it. The first pick,
  --border-dark, measured 2.34-2.98:1 in the four light themes. The resting
  thumb's token is read out of styles.css and barred on all three surface
  steps in every theme, using test_theme_text_contrast's own theme model, so a
  seventh theme is checked the day it lands.
* **A standard property that turns the custom bars off.** Since Chromium 121
  an element with `scrollbar-color` or `scrollbar-width` set ignores its
  `::-webkit-scrollbar` rules. Set on `*`, `html` or `body` in styles.css, it
  would switch off the hover state everywhere and pass every other test.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

# The theme model (the six dictionaries, :root, and the resolver) lives in
# test_theme_text_contrast.py. Loaded by path rather than re-implemented, so
# the two files cannot disagree about what a theme paints.
_spec = importlib.util.spec_from_file_location(
    "_theme_model", Path(__file__).with_name("test_theme_text_contrast.py"))
theme_model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(theme_model)

STYLES_CSS = Path(__file__).resolve().parent.parent / "src" / "web" / "css" / "styles.css"
UI_CONTROL_BAR = 3.0


def _css() -> str:
    return re.sub(r"/\*.*?\*/", "", STYLES_CSS.read_text(encoding="utf-8"), flags=re.S)


def _thumb_token(css: str) -> str:
    m = re.search(r"(?m)^::-webkit-scrollbar-thumb\s*\{([^}]*)\}", css)
    assert m, "styles.css has no global ::-webkit-scrollbar-thumb rule"
    tok = re.search(r"background-color:\s*var\((--[\w-]+)\)", m.group(1))
    assert tok, f"the thumb is not coloured from a token: {m.group(1)!r}"
    return tok.group(1)


def _failures(token: str) -> list[str]:
    out = []
    for theme, theme_vars in sorted(theme_model.THEMES.items()):
        fg = theme_model._resolve(token, theme_vars, theme_model.ROOT)
        for slab in theme_model.SURFACE_SLABS:
            bg = theme_model._resolve(slab, theme_vars, theme_model.ROOT)
            ratio = theme_model._ratio(fg, bg)
            if ratio < UI_CONTROL_BAR:
                out.append(f"{theme}: {token} {fg} on {slab} {bg} = {ratio:.2f}:1")
    return out


def test_the_resting_thumb_clears_3_to_1_in_every_theme() -> None:
    token = _thumb_token(_css())
    assert _failures(token) == []


def test_the_contrast_guard_catches_the_first_pick() -> None:
    """Negative control: --border-dark, the value this replaced, must fail."""
    assert _failures("--border-dark"), "the bar cannot fail, so it measures nothing"


@pytest.mark.parametrize("prop", ["scrollbar-color", "scrollbar-width"])
def test_no_global_rule_switches_the_custom_scrollbar_off(prop: str) -> None:
    css = _css()
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        sels = {s.strip() for s in selector.split(",")}
        if sels & {"*", "html", "body", ":root"} and prop in body:
            pytest.fail(f"{selector.strip()} sets {prop}, which makes Chromium "
                        "ignore every ::-webkit-scrollbar rule on the page")
