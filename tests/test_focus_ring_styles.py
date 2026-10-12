"""The app's keyboard focus indicator exists, follows the theme, and clears 3:1 (#349, #325).

**This is a SOURCE check, not a rendered one, and that is deliberate.** A
focus ring is drawn by a `:focus-visible` rule, and `:focus-visible` only
matches when the browser decides focus came from the keyboard. Focus moved
by CDP -- `el.focus()`, or a synthetic `Input.dispatchKeyEvent` Tab -- does
not set the flag that pseudo-class reads (CLAUDE.md, "Four traps found on
2026-10-03"). So a scenario driven the usual way would see no ring with
this fix and no ring without it, and would pass against a completely
unstyled page. This file reads the stylesheets and does the contrast
arithmetic instead.

The RENDERED check was made by hand on Windows machine A: a headed WIMI,
real Windows Tab keystrokes (SendKeys, foreground-checked), computed styles
read 700 ms after keyup so `.btn { transition: all }` has settled, in all
six themes. The figures are on #349. Repeating it needs a desktop session;
an offscreen run cannot.

Guarded here:

* **A global ring exists**, as a top-level `:focus-visible` rule in
  styles.css drawing a 2px solid `--focus-ring-color` outline. Without it
  every button falls back to Blink's `auto 1px #e59700` (2.40:1), the #349
  defect.
* **Its colour clears 3:1 on every surface step in every theme**, using
  test_theme_text_contrast's own theme model, with the embedder's amber as
  the negative control.
* **Its colour does not come from the student's stored primary.** The first
  version drew the ring in `--color-primary`, which passed this file's
  per-theme arithmetic and then measured **2.99:1** in the real-Tab check:
  `_wimiApplyColourPreferences` overwrites `--color-primary` with the
  profile's stored colour, and a new profile stores `#2196F3`. That value is
  the second negative control.
* **The weight fields carry no per-field focus colour** (#325, owner's
  decision 2026-10-04): the low field's `--color-warning` (2.15:1) and the
  high field's `--color-success` (2.54:1) are gone and must not come back.
* **No `:focus-visible` rule removes the outline without replacing it**,
  except where another rule draws the ring for it through `:has()`. The
  profile card was this shape: `outline: none` plus a `--color-primary-bg`
  halo of about 1.1:1.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

CSS_DIR = Path(__file__).resolve().parent.parent / "src" / "web" / "css"
STYLES = CSS_DIR / "styles.css"
WEIGHT = CSS_DIR / "weight.css"
UI_CONTROL_BAR = 3.0
BLINK_DEFAULT_RING = "#e59700"

_spec = importlib.util.spec_from_file_location(
    "_theme_model", Path(__file__).with_name("test_theme_text_contrast.py"))
theme_model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(theme_model)


def _rules(css: str) -> list[tuple[str, str]]:
    """(selector, body) for every innermost rule, comments stripped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def _ring_failures(colour_token: str | None, literal: str | None = None) -> list[str]:
    out = []
    for theme, theme_vars in sorted(theme_model.THEMES.items()):
        fg = literal or theme_model._resolve(colour_token, theme_vars, theme_model.ROOT)
        for slab in theme_model.SURFACE_SLABS:
            bg = theme_model._resolve(slab, theme_vars, theme_model.ROOT)
            ratio = theme_model._ratio(fg, bg)
            if ratio < UI_CONTROL_BAR:
                out.append(f"{theme}: {fg} on {slab} {bg} = {ratio:.2f}:1")
    return out


def test_a_global_focus_visible_ring_exists() -> None:
    bodies = [body for sel, body in _rules(STYLES.read_text(encoding="utf-8"))
              if sel == ":focus-visible"]
    assert bodies, ("styles.css has no top-level :focus-visible rule, so every "
                    "button falls back to the embedder's amber ring (#349)")
    body = " ".join(bodies)
    assert re.search(r"outline:\s*2px\s+solid\s+var\(--focus-ring-color\)", body), body
    assert re.search(r"outline-offset:\s*[1-9]", body), (
        "the floating ring needs a positive offset to clear the control's own edge")


def test_the_ring_colour_clears_3_to_1_in_every_theme() -> None:
    assert _ring_failures("--focus-ring-color") == []


def test_the_ring_colour_does_not_follow_the_stored_primary() -> None:
    """--color-primary is overwritten from preferences on every page load."""
    root = {sel: body for sel, body in _rules(STYLES.read_text(encoding="utf-8"))}[":root"]
    m = re.search(r"--focus-ring-color:\s*([^;]+);", root)
    assert m, "--focus-ring-color is not defined at :root"
    assert not re.search(r"var\(--color-primary\)", m.group(1)), (
        f"--focus-ring-color is {m.group(1)!r}; --color-primary is the student's "
        "stored colour, and the default #2196F3 draws the ring at 2.99:1")


def test_the_contrast_guard_catches_the_default_stored_primary() -> None:
    """Negative control: #2196F3, what a new profile stores, must fail."""
    assert _ring_failures(None, literal="#2196F3")


def test_the_contrast_guard_catches_the_embedder_default() -> None:
    """Negative control: Blink's amber ring, the #349 defect, must fail."""
    assert _ring_failures(None, literal=BLINK_DEFAULT_RING)


def test_the_weight_fields_carry_no_per_field_focus_colour() -> None:
    offending = [
        f"{sel} {{{body.strip()}}}"
        for sel, body in _rules(WEIGHT.read_text(encoding="utf-8"))
        if ":focus" in sel and re.search(r"--color-(warning|success)", body)
    ]
    assert not offending, (
        "a weight field's focus colour is back. #325 (owner, 2026-10-04) "
        f"removed the low/high coding: {offending}")


def test_the_weight_guard_catches_the_original_rule() -> None:
    """Negative control: the pre-#325 low-field rule must be caught."""
    old = (".weight-range-input-group .weight-input-field.weight-low-field:focus "
           "{ border-color: var(--color-warning); }")
    assert any(":focus" in s and "--color-warning" in b for s, b in _rules(old))


def _unreplaced_outline_removals(css_by_file: dict[str, str]) -> list[str]:
    all_rules = [(name, sel, body) for name, css in css_by_file.items()
                 for sel, body in _rules(css)]
    has_selectors = " ".join(sel for _, sel, _ in all_rules if ":has(" in sel)
    out = []
    for name, sel, body in all_rules:
        if ":focus-visible" not in sel or not re.search(r"outline:\s*(none|0)\b", body):
            continue
        ring = r"var\(--(focus-ring-color|color-primary)\)"
        draws = re.search(r"border(-color)?:[^;]*" + ring, body) or \
            re.search(r"box-shadow:[^;]*" + ring, body)
        target = sel.replace(":focus-visible", "").strip()
        if not draws and target not in has_selectors:
            out.append(f"{name}: {sel}")
    return out


def test_no_focus_visible_rule_removes_the_outline_without_a_replacement() -> None:
    css = {p.name: p.read_text(encoding="utf-8") for p in CSS_DIR.glob("*.css")}
    assert _unreplaced_outline_removals(css) == []


def test_the_removal_guard_catches_the_old_profile_card() -> None:
    """Negative control: the pre-#349 profile card rule must be caught."""
    old = (".profile-card-main:focus-visible { outline: none; "
           "box-shadow: 0 0 0 3px var(--color-primary-bg); }")
    assert _unreplaced_outline_removals({"profiles.css": old})


def _focus_outlines_on_the_stored_primary(css_by_file: dict[str, str]) -> list[str]:
    """Focus rules whose outline still names --color-primary (#356).

    --color-primary is the student's stored colour, so a ring drawn in it
    is 2.99:1 for a new profile. Every focus outline goes through
    --focus-ring-color. A `:has(...:focus...)` selector counts: that is how
    the tree row draws its ring. Non-focus outlines (the tree's drag-over
    dashes) are not this rule's business.
    """
    return [f"{name}: {sel}" for name, css in css_by_file.items()
            for sel, body in _rules(css)
            if ":focus" in sel and re.search(r"outline:[^;]*var\(--color-primary\)", body)]


def test_no_focus_outline_uses_the_stored_primary() -> None:
    css = {p.name: p.read_text(encoding="utf-8") for p in CSS_DIR.glob("*.css")}
    assert _focus_outlines_on_the_stored_primary(css) == []


def test_the_stored_primary_guard_catches_the_old_tree_row() -> None:
    """Negative control: tree.css's row ring as it was before #356."""
    old = (".tree-node-content:has(> .tree-node-name:focus-visible) "
           "{ outline: 2px solid var(--color-primary); outline-offset: -2px; }")
    assert _focus_outlines_on_the_stored_primary({"tree.css": old})
