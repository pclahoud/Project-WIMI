"""Every theme's text tokens clear WCAG AA against the slab that PAINTS (#302, #303, #325, #326, #111).

A static sweep over the theme dictionaries in ``src/web/js/themes.js`` and the
``:root`` block in ``src/web/css/styles.css``. No browser, no ``QApplication`` --
it reads the shipped values and does the WCAG arithmetic, so it costs
milliseconds and runs in the default (non-``slow``) selection.

**The dictionary's ``--color-primary-bg`` never paints, and that is why this
file models the colour-preference applier as well as the theme applier
(#322/#325).** ``_wimiApplyColourPreferences`` runs *after*
``_wimiApplyThemeVariables`` on both colour paths, and
``prefs.primary_color_hex`` has a column default and a dataclass default, so
the branch always fires and the derived tint always overwrites the curated one.
A bar built from the dictionary alone said Default's primary label was at
4.75:1 when the slab it lands on gives **4.20:1** -- which is #325's table
being right about the mechanism and wrong about the numbers, because it read
the dictionary. So ``_wimi_mix_color`` and the two BG magnitudes are ported
here and parsed back out of ``themes.js``, and a magnitude changed in the
source without changing it here fails ``test_the_sweep_found_every_theme``
rather than silently re-barring against a slab that no longer exists.

Why a *static* test when #302 insists the ratios be measured rendered. The two
answer different questions and this project has been bitten by conflating them
before (#121's AX-tree-versus-painted-state note is the same shape):

* **Rendered** is the only thing that can tell you which *backgrounds* a token
  is actually painted on -- alpha-blended slabs, inherited colours, a card
  nested in a card. That is how #302's own scale figures were produced and how
  this fix was verified.
* **Static** is the only thing that can stop a *seventh theme* shipping a
  failing value, because a rendered audit only sees the themes and pages it was
  pointed at, and it is ``slow``/``regression`` so it does not run in the fast
  loop. This file is the cheap recurrence gate.

The sweep is **self-counting**: it discovers the themes from ``themes.js``
rather than carrying a list, so a seventh theme is checked the day it is added
and cannot be forgotten. ``KNOWN_FAILING`` does not exist on purpose -- there
is no allowlist, in the spirit of ``scripts/check_css_empty_selector.py``.

One thing that is deliberately *not* asserted: a direction. The owner's rule
for #302 is "darken the minimum needed to reach 4.5:1 against that theme's own
``--bg-primary``, preserving hue", and in Midnight and High Contrast
``--bg-primary`` is near-black, so reaching contrast there means moving
*lighter*. A test that asserted "darken" would be wrong in a third of the
palette and would have to carry the exception list this file exists to avoid.
Two of the shipped values prove it is not hypothetical: High Contrast's
``--color-primary-text`` and Midnight's ``--color-primary-hover-text`` are both
*lighter* than the bases they are derived from.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
THEMES_JS = REPO_ROOT / "src" / "web" / "js" / "themes.js"
STYLES_CSS = REPO_ROOT / "src" / "web" / "css" / "styles.css"

AA_BODY_TEXT = 4.5

# The tokens whose job is *text*, each against the slab it is painted on.
# --text-muted carries 270 `color:` declarations across src/web/css (#302);
# the four status tokens are #303's "a fill and a label are different jobs";
# the two primary ones are #325's, with 129 between them.
NEUTRAL_TEXT = ["--text-muted", "--text-secondary", "--text-primary"]
STATUS_SEMANTICS = ["success", "warning", "error", "info"]
PRIMARY_TEXT = ["--color-primary-text", "--color-primary-hover-text"]

# The three surface steps. #302's approved bar was --bg-primary alone;
# #326 widened it for the neutral text tokens, because a card nested in a card
# is not --bg-primary and 114 rendered elements sit on these two. The status
# tokens keep #303's narrower bar -- see that test's docstring.
SURFACE_SLABS = ["--bg-primary", "--bg-secondary", "--bg-tertiary"]

# High Contrast's --text-muted measured 5.32:1 on --bg-primary and #302
# deliberately left it alone for that reason. #326 widened the bar and it does
# NOT clear the nested slabs, so it moves here; "already passes" was a
# measurement against one background, not an exemption.


# ---------------------------------------------------------------------------
# Reading the shipped values
# ---------------------------------------------------------------------------

def _root_declarations() -> dict[str, str]:
    """``--token: value`` pairs from the first ``:root`` block of styles.css."""
    text = STYLES_CSS.read_text(encoding="utf-8")
    start = text.index(":root")
    block = text[start:text.index("}", start)]
    # Strip comments first -- styles.css's :root carries long prose blocks
    # that mention token names, and #110's comment quotes three hex literals.
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


def _theme_dictionaries() -> dict[str, dict[str, str]]:
    """``{theme: {token: value}}`` from ``window.WIMI_THEMES`` in themes.js.

    Parsed rather than executed: the file is a browser script with no module
    boundary, and running it would need a JS engine for a table of literals.
    """
    text = THEMES_JS.read_text(encoding="utf-8")
    text = re.sub(r"//[^\n]*", "", text)          # line comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)  # block comments
    # Anchor on the ASSIGNMENT, not the bare name. This was `index(
    # "window.WIMI_THEMES")` and #322 broke it the moment a function above the
    # table *read* `window.WIMI_THEMES[themeName]`: the brace walk started
    # inside that function and returned an empty table. The parse guard caught
    # it, which is the only reason it is a footnote rather than a green run
    # that checked nothing.
    match = re.search(r"window\.WIMI_THEMES\s*=", text)
    assert match is not None, (
        f"no `window.WIMI_THEMES =` assignment found in {THEMES_JS.name}; the "
        "theme table parser has nothing to anchor on.")
    start = match.start()
    # Walk braces to find the end of the object literal.
    depth, i = 0, text.index("{", start)
    end = i
    for end in range(i, len(text)):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0:
                break
    body = text[i:end + 1]

    themes: dict[str, dict[str, str]] = {}
    for m in re.finditer(r"(\w+)\s*:\s*\{\s*\n\s*label\s*:", body):
        name = m.group(1)
        seg = body[m.start():]
        vdepth, vi = 0, seg.index("variables")
        vstart = seg.index("{", vi)
        vend = vstart
        for vend in range(vstart, len(seg)):
            if seg[vend] == "{":
                vdepth += 1
            elif seg[vend] == "}":
                vdepth -= 1
                if vdepth == 0:
                    break
        themes[name] = {
            km.group(1): km.group(2)
            for km in re.finditer(r"'(--[\w-]+)'\s*:\s*'([^']+)'",
                                  seg[vstart:vend + 1])
        }
    return themes


def _stored_primaries() -> dict[str, str]:
    """``{theme: primaryColorHex}`` -- what ``settings.js`` persists per theme.

    ``_applyThemeToColorPickers`` writes this literal into
    ``prefs.primary_color_hex`` the moment the student picks a theme, and
    ``_wimiApplyColourPreferences`` then derives the live ``--color-primary-bg``
    from it. So this, not the dictionary's ``--color-primary-bg``, is what a
    primary-coloured label is painted on.
    """
    text = THEMES_JS.read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in re.finditer(
        r"(\w+)\s*:\s*\{\s*\n\s*label\s*:[^\n]*\n\s*primaryColorHex\s*:\s*"
        r"'(#[0-9a-fA-F]{6})'", text)}


def _bg_magnitudes() -> tuple[float, float]:
    """``(BG, BG_DARK)`` read out of ``_wimiApplyColourPreferences``.

    Parsed rather than duplicated: the whole value of modelling the derived
    slab is lost if the model and the source can drift. A rename or a retuned
    constant trips the parse guard instead.
    """
    text = THEMES_JS.read_text(encoding="utf-8")
    light = re.search(r"\bvar\s+BG\s*=\s*([0-9.]+)\s*;", text)
    dark = re.search(r"\bvar\s+BG_DARK\s*=\s*(-?[0-9.]+)\s*;", text)
    return (float(light.group(1)) if light else float("nan"),
            float(dark.group(1)) if dark else float("nan"))


def _resolve(token: str, theme_vars: dict[str, str],
             root: dict[str, str], _seen: frozenset[str] = frozenset()) -> str:
    """Resolve a token to a literal, following ``var()`` indirections.

    ``_wimiApplyThemeVariables`` writes the theme dictionary as inline custom
    properties on the root element, so a dictionary entry wins over ``:root``;
    anything the dictionary omits falls through to ``:root``. That fall-through
    is why #110's ``-dark`` tokens needed entries in only two of six
    dictionaries, and it is the mechanism this resolver has to mirror.
    """
    if token in _seen:
        raise AssertionError(f"{token} resolves in a cycle")
    value = theme_vars.get(token, root.get(token))
    if value is None:
        raise KeyError(token)
    m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,[^)]*)?\)", value.strip())
    if m:
        return _resolve(m.group(1), theme_vars, root, _seen | {token})
    return value.strip()


# ---------------------------------------------------------------------------
# WCAG arithmetic (kept local: this file must not import a scenario helper,
# which lives under tests/wimi_test/scenarios/_helpers and is only importable
# with that directory on sys.path)
# ---------------------------------------------------------------------------

def _rgb(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    assert len(v) == 6, f"not a hex colour: {value!r}"
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _luminance(rgb: tuple[int, int, int]) -> float:
    def ch(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(fg: str, bg: str) -> float:
    a, b = _luminance(_rgb(fg)), _luminance(_rgb(bg))
    if a < b:
        a, b = b, a
    return (a + 0.05) / (b + 0.05)


def _lightness(value: str) -> float:
    """CIE L* -- the perceptually uniform lightness axis.

    Used only for the two *visibility* assertions (#111's hover step and
    #325's hover-text step). Contrast ratio is the wrong instrument there:
    ``#1e293b`` and ``#222d3f`` are 1.07:1 apart, which says nothing about
    whether a pointer-over is noticeable, while their 1.86 L* difference is
    the same perceptual step Default already ships between its own
    ``--bg-secondary`` and ``--bg-tertiary``.
    """
    y = _luminance(_rgb(value))
    return 116 * (y ** (1 / 3)) - 16 if y > 0.008856 else 903.3 * y


def _mix(value: str, ratio: float) -> str:
    """``_wimiMixColor`` from themes.js, ported (#307).

    Positive mixes toward white, negative toward black, and the two are not
    the same formula -- which is exactly why #307 replaced a channel offset
    with a proportional mix, and why a port has to keep both branches.
    """
    channels = _rgb(value)
    out = [round(c + (255 - c) * ratio) if ratio >= 0 else round(c * (1 + ratio))
           for c in channels]
    return "#" + "".join(f"{c:02x}" for c in out)


# ---------------------------------------------------------------------------
# Fixtures / parametrisation
# ---------------------------------------------------------------------------

ROOT = _root_declarations()
THEMES = _theme_dictionaries()
STORED_PRIMARY = _stored_primaries()
BG_LIGHT_RATIO, BG_DARK_RATIO = _bg_magnitudes()

# `_wimiApplyColourPreferences` picks the mix direction from this threshold.
# Keep it in step with themes.js; the parse guard below asserts the six
# shipped themes land either side of it rather than all on one.
DARK_THEME_BG_LUMINANCE = 0.18


def _theme_is_dark(theme: str) -> bool:
    return _luminance(_rgb(_resolve("--bg-primary", THEMES[theme], ROOT))) < \
        DARK_THEME_BG_LUMINANCE


def _derived_primary_bg(theme: str) -> str:
    """The ``--color-primary-bg`` that actually paints, per #322.

    ``_wimiApplyColourPreferences`` always overwrites the dictionary value,
    because ``prefs.primary_color_hex`` is never unset. The sign comes from
    the theme's own ``--bg-primary`` luminance: a dark theme's tint has to be
    a dark tint, which is the whole of #322.
    """
    ratio = BG_DARK_RATIO if _theme_is_dark(theme) else BG_LIGHT_RATIO
    return _mix(STORED_PRIMARY[theme], ratio)


def _primary_label_slabs(theme: str) -> dict[str, str]:
    """Every background a primary-coloured LABEL is painted on.

    Four, not the two #325's table names. ``--bg-secondary`` is in because
    #303's re-render found eight status labels failing there; the *derived*
    tint is in because it is the one that paints, and it is the binding
    constraint in four of the six themes. The dictionary tint stays in the
    bar as well: it costs nothing, and it is the curated value the derived
    magnitude is fitted to, so a drift between them shows up here first.
    """
    theme_vars = THEMES[theme]
    return {
        "--bg-primary": _resolve("--bg-primary", theme_vars, ROOT),
        "--bg-secondary": _resolve("--bg-secondary", theme_vars, ROOT),
        "--color-primary-bg (dictionary)": _resolve(
            "--color-primary-bg", theme_vars, ROOT),
        "--color-primary-bg (derived)": _derived_primary_bg(theme),
    }


def test_the_sweep_found_every_theme() -> None:
    """Guard the guard: a parse that silently found nothing would pass everything.

    The parsers above are regexes over a browser script and a stylesheet. If
    either stops matching -- a reformat, a trailing-comma style change, a theme
    defined by spreading another -- every parametrised case below would receive
    an empty dictionary and the sweep would report green while checking nothing.
    """
    assert len(THEMES) >= 6, (
        f"parsed {len(THEMES)} themes from {THEMES_JS.name}, expected at least "
        "the six that ship (default, midnight, warm_study, forest, nord, "
        "high_contrast). The object-literal parser has stopped matching.")
    assert "default" in THEMES and "high_contrast" in THEMES
    assert len(ROOT) > 50, (
        f"parsed {len(ROOT)} declarations from styles.css's :root, expected the "
        "full token table. The :root parser has stopped matching.")
    # default overrides nothing, so every value it resolves comes from :root --
    # which makes it the proof that the fall-through path works.
    assert THEMES["default"] == {}, (
        "the default theme is expected to carry an empty `variables` dictionary "
        "and inherit every value from :root. If that changed, the fall-through "
        "assertions below are no longer exercising it.")

    # Everything #322/#325 added depends on these three parsers, and each one
    # fails SILENTLY in the direction of passing: no stored primary means no
    # derived slab, and a NaN magnitude makes every ratio NaN, which compares
    # False against >= and would therefore fail loudly -- but an empty dict
    # would just drop the slab out of the bar.
    assert set(STORED_PRIMARY) >= set(THEMES), (
        f"parsed primaryColorHex for {sorted(STORED_PRIMARY)} but themes are "
        f"{sorted(THEMES)}. The derived --color-primary-bg cannot be modelled "
        "for a theme whose stored primary was not found, so that theme's "
        "label would be barred against three slabs instead of four.")
    assert BG_LIGHT_RATIO == BG_LIGHT_RATIO and BG_DARK_RATIO == BG_DARK_RATIO, (
        f"could not read BG / BG_DARK out of {THEMES_JS.name} "
        f"(got {BG_LIGHT_RATIO}, {BG_DARK_RATIO}). They are the magnitudes "
        "_wimiApplyColourPreferences mixes with; this file models that applier "
        "and must not carry its own copy of the constants.")
    assert BG_LIGHT_RATIO > 0 and BG_DARK_RATIO < 0, (
        f"BG {BG_LIGHT_RATIO} and BG_DARK {BG_DARK_RATIO} must have opposite "
        "signs -- #322's whole finding is that one direction cannot serve both "
        "kinds of theme (_wimiMixColor: positive mixes toward white).")
    dark = {t for t in THEMES if _theme_is_dark(t)}
    assert dark and dark != set(THEMES), (
        f"{len(dark)} of {len(THEMES)} themes classify as dark "
        f"({sorted(dark)}). If every theme lands on one side of "
        "DARK_THEME_BG_LUMINANCE the direction choice is untested, and #322 "
        "is precisely a direction bug.")


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("token", NEUTRAL_TEXT)
@pytest.mark.parametrize("slab", SURFACE_SLABS)
def test_neutral_text_token_clears_aa_on_every_surface_step(
    theme: str, token: str, slab: str,
) -> None:
    """#302 on ``--bg-primary``, widened to the nested slabs by #326.

    #302: five of six themes shipped a ``--text-muted`` below 4.5:1 against
    their own ``--bg-primary`` -- Default 2.56:1, Forest 2.70:1, Warm Study
    2.98:1, Nord 3.18:1, Midnight 3.75:1, only High Contrast passing at
    5.32:1. That one token carries 270 ``color:`` declarations in
    ``src/web/css``, which is why one value per theme was most of the app's
    contrast debt.

    #326 is the measured residual of that fix: a card nested in a card is not
    ``--bg-primary``, and on ``--bg-secondary``/``--bg-tertiary``
    ``--text-muted`` was still below AA in **five** of the six -- 114 rendered
    elements, 46% of everything surviving #302 and #303. The bar is widened
    here rather than in a second file because #302's own rule ("the minimum
    needed to reach 4.5:1") is unchanged; only which backgrounds count.

    Note that Default, Warm Study and Nord cleared ``--bg-secondary`` by
    0.02-0.05 before this, so a fix barring only ``--bg-tertiary`` would have
    left three themes passing by coincidence.
    """
    theme_vars = THEMES[theme]
    fg = _resolve(token, theme_vars, ROOT)
    bg = _resolve(slab, theme_vars, ROOT)
    ratio = _ratio(fg, bg)
    assert ratio >= AA_BODY_TEXT, (
        f"{token} is {fg} on {slab} {bg} in the {theme} theme -- "
        f"{ratio:.2f}:1, below the {AA_BODY_TEXT}:1 WCAG AA body-text bar "
        "(#302, #326). Darken -- or, in a theme whose surfaces are dark, "
        "LIGHTEN -- the minimum needed to reach the bar while preserving hue. "
        "A label is a label whichever slab it is on.")


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("semantic", STATUS_SEMANTICS)
def test_status_text_token_clears_aa_on_every_slab_it_is_painted_on(
    theme: str, semantic: str,
) -> None:
    """#303: a status colour cannot be both the fill and the label.

    ``--color-warning`` ``#f59e0b`` was painted as text on
    ``--color-warning-bg`` ``#fffbeb`` at **2.07:1** (the "In Progress" session
    badge) and on white at 2.15:1. The fix is a separate ``--color-X-text``
    token; the bright value stays for fills and borders.

    **Three backgrounds, not the two #303 names.** The issue's table lists the
    tinted badge slab and plain ``--bg-primary``; a rendered audit of the first
    attempt at this fix found eight labels still failing on ``--bg-secondary``,
    because several themes tint it a shade darker than the generic ``#f8fafc``.
    A value tuned to a subset of the slabs it lands on is the defect in
    miniature, so all three are asserted.

    ``--bg-tertiary`` is **still** deliberately absent, and the asymmetry with
    the neutral tokens above is now empirical rather than pending. #326 widened
    their bar because a rendered audit counted 114 elements carrying
    ``--text-muted`` on the nested slabs. No status label has ever been
    observed on ``--bg-tertiary``, and the bar in this file is "every slab a
    rendered audit found the label on", not "every slab that exists" -- a
    static sweep says 13 of these 24 cells *would* fail there, which is a
    statement about a background none of them land on.

    What remains of #326 for this palette is the two ``color-mix`` rules in
    ``tree.css`` that invent their own slab (its comment #4593), and that is a
    choice between widening this bar and making those two rules stop inventing
    one. It is left open on purpose.
    """
    theme_vars = THEMES[theme]
    fg = _resolve(f"--color-{semantic}-text", theme_vars, ROOT)
    for bg_token in ("--bg-primary", "--bg-secondary", f"--color-{semantic}-bg"):
        bg = _resolve(bg_token, theme_vars, ROOT)
        ratio = _ratio(fg, bg)
        assert ratio >= AA_BODY_TEXT, (
            f"--color-{semantic}-text is {fg} on {bg_token} {bg} in the {theme} "
            f"theme -- {ratio:.2f}:1, below the {AA_BODY_TEXT}:1 bar (#303). "
            "This token's only job is text; if the value here is the same as "
            f"--color-{semantic} then the theme is still using one value for "
            "both the fill and the label.")


@pytest.mark.parametrize("semantic", STATUS_SEMANTICS)
def test_a_status_text_token_exists_for_every_semantic(semantic: str) -> None:
    """The four ``-text`` tokens are defined at ``:root``, not only in a theme.

    A token defined only inside theme dictionaries would be undefined in
    ``default`` -- and a ``var()`` naming an undefined token with no fallback is
    invalid at computed-value time, so Chromium discards the declaration
    **silently** and the label falls back to its inherited colour. That is the
    failure mode ``scripts/check_css_tokens.py`` exists for, reached from the
    other direction.
    """
    assert f"--color-{semantic}-text" in ROOT, (
        f"--color-{semantic}-text is not declared in styles.css's :root block. "
        "Themes may override it, but :root has to define it or the default "
        "theme has no value at all.")


def test_a_status_text_token_is_not_just_the_base_colour_in_a_light_theme() -> None:
    """The fix has to have *moved* something, in the themes that were broken.

    Without this, repointing every ``color:`` declaration at
    ``--color-X-text`` and then defining ``--color-X-text: var(--color-X)``
    would satisfy every ratio assertion above in Midnight and High Contrast
    (whose bright values are already readable on their dark slabs) and leave
    the four light themes exactly as broken as they were. This is #110's
    "only the two inverting themes moved" test, pointed the other way: there
    the four light themes had to stay put, here they are the ones that must
    change.
    """
    moved = []
    for theme in sorted(THEMES):
        theme_vars = THEMES[theme]
        bg = _resolve("--bg-primary", theme_vars, ROOT)
        if _luminance(_rgb(bg)) < 0.18:
            continue  # a dark-slab theme; its bright base is already readable
        for semantic in STATUS_SEMANTICS:
            base = _resolve(f"--color-{semantic}", theme_vars, ROOT)
            text = _resolve(f"--color-{semantic}-text", theme_vars, ROOT)
            if base.lower() != text.lower():
                moved.append(f"{theme}/{semantic}")
    assert len(moved) >= 16, (
        "expected every status semantic in all four light themes to resolve a "
        f"--color-X-text distinct from its base colour; only {len(moved)} did "
        f"({moved}). A light theme where the two are equal is still painting "
        "one value as both the fill and the label, which is #303.")


# ---------------------------------------------------------------------------
# #325 -- the primary palette, same defect one semantic over
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("token", PRIMARY_TEXT)
def test_primary_text_token_clears_aa_on_every_slab_it_is_painted_on(
    theme: str, token: str,
) -> None:
    """#325: ``--color-primary`` was doing #303's two jobs, on more elements.

    129 ``color:`` declarations across 26 stylesheets painted
    ``--color-primary`` (125) or ``--color-primary-hover`` (4, one of them
    behind a fallback) as text, usually on the primary tint --
    ``.badge-primary`` is the canonical shape. Measured 3.25:1 in Nord,
    3.32:1 in Forest, 3.13:1 for Midnight's hover value, and 118 rendered
    elements across four pages.

    **Four slabs, and the fourth is the one that paints.** See
    ``_primary_label_slabs``: barring against the dictionary tint alone put
    Default at 4.75:1 and Warm Study at 4.51:1, both "passing"; against the
    derived tint they are **4.20:1 and 4.08:1**. #325's table reports the
    first pair, because it read the dictionary. Three of the six themes
    cleared the narrow bar by 0.01-0.25, which is the issue's own argument for
    a token rather than four nudges -- the coincidences are not load-bearing
    any more, because the label is now barred independently of the fill.
    """
    theme_vars = THEMES[theme]
    assert token in ROOT or token in theme_vars, (
        f"{token} resolves nowhere for the {theme} theme. It is #325's fix: a "
        "darker (or, on a dark theme, lighter) text counterpart for "
        "--color-primary, defined at :root and overridden in every dictionary "
        "that overrides --color-primary.")
    fg = _resolve(token, theme_vars, ROOT)
    for name, bg in _primary_label_slabs(theme).items():
        ratio = _ratio(fg, bg)
        assert ratio >= AA_BODY_TEXT, (
            f"{token} is {fg} on {name} {bg} in the {theme} theme -- "
            f"{ratio:.2f}:1, below the {AA_BODY_TEXT}:1 bar (#325). This "
            "token's only job is text; the bright --color-primary stays for "
            "fills and borders, which is the owner's rule and is why the fill "
            "half of #325 is deliberately still failing.")


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_every_theme_that_themes_its_primary_also_themes_its_primary_label(
    theme: str,
) -> None:
    """A fall-through here is a HUE break, not just a contrast one.

    #303's ``-text`` tokens could be omitted by a theme whose base matched
    ``:root``'s, and four of six legitimately were. That cannot happen for the
    primary palette: **every theme sets its own ``--color-primary``**, so a
    dictionary that lists the fill and omits the label paints Default's blue
    on Warm Study's sepia. Measured as a worked example: with no entry, Warm
    Study's ``--color-primary-text`` resolves to ``:root``'s blue.

    That is a louder failure than a thin ratio, and it is invisible to
    ``check_css_tokens.py`` -- the token *is* defined, just not here.
    """
    theme_vars = THEMES[theme]
    if "--color-primary" not in theme_vars:
        pytest.skip(f"{theme} does not override --color-primary")
    for token in PRIMARY_TEXT:
        assert token in theme_vars, (
            f"the {theme} dictionary sets --color-primary "
            f"{theme_vars['--color-primary']} but not {token}, so that label "
            "falls through to :root -- a value derived from a different "
            "theme's primary, in a different hue. Every dictionary that "
            "overrides the fill must override the label, even when the value "
            "is the unchanged base (four of the six are).")


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_the_primary_hover_label_stays_a_visible_step_from_the_label(
    theme: str,
) -> None:
    """The minimum contrast move collapses the hover step in three themes.

    Derived independently, ``--color-primary-hover-text`` lands within
    **0.00-0.30 L*** of ``--color-primary-text`` in Midnight, Forest and Nord:
    each theme's hover value sits on the far side of the bar from its base, so
    "the minimum move that clears AA" converges on nearly the same colour. A
    link would then stop responding visibly to the pointer -- #111's defect,
    reached through text instead of through a surface.

    So the hover token carries a second requirement: at least the perceptual
    step the theme itself designed between ``--color-primary`` and
    ``--color-primary-hover``. Direction is free, and has to be: Midnight's
    designed hover is *darker*, which cannot clear the bar on its dark tint,
    so its label hovers lighter instead. The shipped values clear AA at
    5.90-9.59:1, so this requirement costs nothing.
    """
    theme_vars = THEMES[theme]
    text = _resolve("--color-primary-text", theme_vars, ROOT)
    hover = _resolve("--color-primary-hover-text", theme_vars, ROOT)
    designed = abs(_lightness(_resolve("--color-primary", theme_vars, ROOT))
                   - _lightness(_resolve("--color-primary-hover", theme_vars, ROOT)))
    got = abs(_lightness(text) - _lightness(hover))
    assert got >= designed, (
        f"in the {theme} theme --color-primary-text {text} and "
        f"--color-primary-hover-text {hover} are {got:.2f} L* apart, less than "
        f"the {designed:.2f} L* this theme designs between --color-primary and "
        "--color-primary-hover. A hover that does not change colour is "
        "invisible wherever colour is the only hover signal -- "
        "`.header-left .back-link:hover` in subject_deep_dive.css is such a "
        "site. Move it further in whichever direction keeps it above the bar.")


# ---------------------------------------------------------------------------
# #111 -- the surface ramp
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("theme", sorted(THEMES))
def test_a_one_step_hover_is_visible_in_every_theme(theme: str) -> None:
    """#111: Midnight and High Contrast mapped both surface steps to one value.

    ``--bg-secondary`` and ``--bg-tertiary`` were both ``#1e293b`` in Midnight
    and both ``#1a1a1a`` in High Contrast, so the house pattern -- paint
    ``--bg-secondary``, hover to ``--bg-tertiary`` -- gave **no feedback at
    all** in a third of the palette. Six rules do that
    (``settings.css .btn-cancel``, ``tree.css .child-item``,
    ``wizard.css .category-filter-btn``, ``entry.css .note-subject-option``,
    ``media.css .media-dropzone`` and ``.media-subject-checkbox``).

    The floor is **Default's own step**, which is the smallest the application
    already ships and therefore the house minimum rather than an invented
    threshold. Measured in L* because a contrast ratio is the wrong instrument
    for a surface step -- see ``_lightness``.

    The ramp is restored rather than the pair being special-cased:
    ``--color-gray-100`` was collapsed onto ``--color-gray-50`` in those two
    dictionaries, which is where the two surfaces came from
    (``styles.css``: ``--bg-tertiary: var(--color-gray-100)``). That token has
    exactly one consumer, so moving it with ``--bg-tertiary`` keeps the stated
    relation true and changes nothing else.
    """
    theme_vars = THEMES[theme]
    secondary = _resolve("--bg-secondary", theme_vars, ROOT)
    tertiary = _resolve("--bg-tertiary", theme_vars, ROOT)
    floor = min(
        abs(_lightness(_resolve("--bg-secondary", THEMES[t], ROOT))
            - _lightness(_resolve("--bg-tertiary", THEMES[t], ROOT)))
        for t in THEMES
        if _resolve("--bg-secondary", THEMES[t], ROOT)
        != _resolve("--bg-tertiary", THEMES[t], ROOT)
    )
    step = abs(_lightness(secondary) - _lightness(tertiary))
    assert step >= floor, (
        f"in the {theme} theme --bg-secondary {secondary} and --bg-tertiary "
        f"{tertiary} are {step:.2f} L* apart, below the {floor:.2f} L* floor "
        "taken from the smallest step any shipped theme uses (#111). Every "
        "one-step hover in src/web/css is invisible in this theme. Give the "
        "theme a genuine second surface -- and move its --color-gray-100 with "
        "it, since that is the token --bg-tertiary is defined from.")


def test_the_surface_floor_is_not_zero() -> None:
    """Guard the guard: the #111 floor is computed from the themes it checks.

    ``test_a_one_step_hover_is_visible_in_every_theme`` derives its floor from
    the shipped dictionaries so a seventh theme is held to the same step with
    no constant to update. The failure mode of that convenience is a floor of
    zero -- if every theme collapsed the two values, the ``!=`` filter would
    select nothing, ``min()`` would raise, and if it were written with a
    default instead it would pass everything. Pin it as a real step.
    """
    steps = [
        abs(_lightness(_resolve("--bg-secondary", THEMES[t], ROOT))
            - _lightness(_resolve("--bg-tertiary", THEMES[t], ROOT)))
        for t in THEMES
    ]
    assert min(steps) > 1.0, (
        f"the smallest --bg-secondary -> --bg-tertiary step across the themes "
        f"is {min(steps):.2f} L*, which is at or below the threshold where a "
        "large-area surface change stops being noticeable. The floor this "
        "file bars against is derived from these values, so a collapsed theme "
        "lowers the bar for every other theme as well as failing on its own.")


# ---------------------------------------------------------------------------
# #330 -- the token has to be a TEXT token, not merely a readable one
# ---------------------------------------------------------------------------

#: Every file whose `color:` declarations this sweep reads. The html and js
#: trees are included because #317 established that a markup-only sweep
#: misses what JavaScript renders, and the same applies in reverse.
_STYLE_TREES = ("css/*.css", "html/*.html", "html/**/*.html",
                "js/*.js", "js/**/*.js")

#: `color:` and nothing that merely ends in `-color`. #302 miscounted
#: --text-muted by 3 for exactly this reason, in a file about the difference
#: between a text colour and a border colour.
_COLOUR_DECLARATION = re.compile(r"(?<![-\w])color\s*:\s*([^;{}]+)", re.I)


def _colour_declarations() -> list[tuple[str, str]]:
    """``(file, value)`` for every first-party ``color:`` declaration."""
    web = REPO_ROOT / "src" / "web"
    out = []
    for pattern in _STYLE_TREES:
        for path in sorted(web.glob(pattern)):
            if "lib" in path.relative_to(web).parts:
                continue      # vendored
            text = re.sub(r"/\*.*?\*/", " ", path.read_text(encoding="utf-8"),
                          flags=re.S)
            for match in _COLOUR_DECLARATION.finditer(text):
                out.append((str(path.relative_to(REPO_ROOT)), match.group(1).strip()))
    return out


def test_no_border_token_is_painted_as_text() -> None:
    """#330: a border colour is for borders, and as text it is 1.17-2.48:1.

    Four declarations did this -- ``browser.css``'s ``.stat-divider`` and
    three in ``analytics.css``, two of which are ``-empty-hint`` *sentences*
    rather than decorative glyphs. Measured across both light slabs and all
    six themes, **24 of 24 cells below AA**, with ``#d8dee9`` on ``#eceff4``
    at **1.17:1** the worst ratio anywhere in the application.

    This is #97's rule, which its own scenario already states -- *"the
    subtitle separator became var(--text-muted) and NOT --border-color: it is
    text"* -- applied to the files that fix did not reach. Three separators in
    the tree already complied; these were the outliers, which is why the rule
    is enforced rather than restated.

    No allowlist, in the spirit of ``check_css_empty_selector.py``: there were
    zero legitimate uses when this landed, and a border grey readable as text
    would not be a border grey. ``check_css_tokens.py`` cannot see this -- the
    token is defined and themed, it is just the wrong one.
    """
    offenders = [
        (where, value) for where, value in _colour_declarations()
        if re.search(r"var\(\s*--border[\w-]*", value)
    ]
    assert not offenders, (
        "a `color:` declaration names a border token:\n  "
        + "\n  ".join(f"{w}: color: {v}" for w, v in offenders)
        + "\nA border colour as text measures 1.17-2.48:1 in every theme "
          "(#330). Use --text-muted, which clears AA on every surface in all "
          "six themes and is what every other separator and hint in this tree "
          "already uses."
    )


def test_the_declaration_sweep_reads_the_stylesheets() -> None:
    """Guard the guard: a glob that matched nothing would pass everything.

    ``test_no_border_token_is_painted_as_text`` asserts an *absence*, so an
    empty input is indistinguishable from a clean tree. #302's own count was
    wrong by 3 because a ``color:`` pattern also matched ``border-top-color``;
    this pins both that the sweep sees the tree and that it excludes the
    ``*-color:`` properties the bug is about.
    """
    declarations = _colour_declarations()
    # Measured at 1289 on the branch that added this. The floor is well below
    # that rather than at it: the point is to catch a glob that stopped
    # matching, not to make every new rule edit this number -- which is how
    # #302's 273 came to be quoted in three places and wrong in all of them.
    assert len(declarations) > 900, (
        f"the sweep found {len(declarations)} `color:` declarations under "
        "src/web, expected around 1289. The globs or the property pattern "
        "have stopped matching, and an absence assertion over an empty list "
        "passes.")
    assert any("--text-muted" in value for _w, value in declarations), (
        "no declaration naming --text-muted was found, which cannot be true "
        "of this tree -- that token alone carries 270 of them.")
    assert not any(re.match(r"^\s*var\(\s*--border", v) for w, v in declarations
                   if w.endswith("styles.css") and "border-color" in v), (
        "the sweep is matching `border-color:` as `color:`. That inflation is "
        "exactly #302's miscount and would make this test fire on every "
        "border declaration in the tree.")


#: The tokens whose job is a FILL or a BORDER, which therefore may not appear
#: in a `color:` declaration. #325 split the primary family for exactly this
#: reason, and #330 established the same rule for the border greys.
FILL_ONLY_TOKENS = ("--color-primary", "--color-primary-hover",
                    "--color-primary-light")


def test_no_fill_token_is_painted_as_text() -> None:
    """#325's split is enforced, not merely asserted of the token values.

    The ratio tests above check that ``--color-primary-text`` is readable.
    They cannot check that anything *uses* it: a new rule painting
    ``color: var(--color-primary)`` on the primary tint reintroduces the whole
    defect with every token still correct.

    **That is not hypothetical and this test was written because of it.** #301
    landed ``.archived-ancestors-note:hover`` in ``styles.css`` while #325 was
    on a branch -- `background: var(--color-primary-bg); color:
    var(--color-primary)`, the canonical shape, 4.20:1 in Default and 2.24:1
    in Midnight. Merging master in produced a clean three-way merge and a
    reintroduced bug, which is the one thing a value-level guard cannot see.

    Note what is *not* forbidden: the same tokens as ``background``,
    ``border-color``, ``border-left-color``, ``outline`` and ``fill``. That is
    the owner's rule for #325 -- the bright value stays for fills and borders
    -- and the rule this test encodes is only that a **label** takes the
    ``-text`` variant. ``.archived-ancestors-note:hover`` keeps
    ``border-color: var(--color-primary)`` on the very line below the one this
    test caught.

    No allowlist: after #325 there are zero legitimate uses, and a fill colour
    that is readable as a label would not have needed the split.
    """
    offenders = [
        (where, value) for where, value in _colour_declarations()
        if any(re.search(r"var\(\s*" + re.escape(token) + r"\s*[,)]", value)
               for token in FILL_ONLY_TOKENS)
    ]
    assert not offenders, (
        "a `color:` declaration names a fill token:\n  "
        + "\n  ".join(f"{w}: color: {v}" for w, v in offenders)
        + "\nUse --color-primary-text (or --color-primary-hover-text for a "
          "hover state). The bright value is for `background`, `border-color` "
          "and `fill`; as a label it measures 2.24-4.20:1 against the tint it "
          "usually sits on, which is #325."
    )
