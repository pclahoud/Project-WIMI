"""No text styled in CSS renders below 12px (#308).

The owner's decision, 2026-10-06: the floor is ``--font-size-xs`` (0.75rem,
12px), the smallest token the theme already has, for every piece of text whose
size is set in CSS. Two carve-outs, both deliberate:

* **Icons and carets are exempt** -- a dropdown arrow or an "i" in a circle is
  a glyph, not a word anybody reads. They are listed in ``GLYPHS`` by file and
  selector, and each carries a ``#308`` comment at its declaration.
* **Charts are separate.** D3 labels (sunburst, heatmap, axes) get their own
  pass, where each chart decides which labels to drop when space is short. The
  chart modules are listed in ``CHART_MODULES`` and skipped as whole files.

And one thing that is neither: ``PENDING`` holds text left small because
raising it needs a decision nobody has made. It is empty: the one candidate,
the tree editor's ``.parent-row-meta``, was raised on the owner's decision
(2026-10-06) to take the floor and accept that "PRIMARY · CANONICAL
BREADCRUMB" wrapped to two lines, rather than wait for #346.

**That trade is no longer being paid, and the reason is worth keeping.**
#346 settled the copy pass on 2026-10-10 and the ``text-transform:
uppercase`` came off that rule, which took the same column from two lines to
one — 36px to 18px, measured in the same 225px column at the same 12px. So
the wrap this paragraph accepted was never really the floor's cost; it was
the capitals', and raising the size only made it visible. Neither decision
was wrong: #308 could not have known, because the two rules are in different
issues and only the rendered panel shows them interacting.

What this can and cannot see. It reads **literal** sizes (``rem``, ``px``,
``pt``) in stylesheets, page markup and JavaScript, which is where every one of
#308's declarations was, bar one. A relative size (``em``, ``%``) depends on its
parent and cannot be judged from the source -- ``.notes-count`` was ``0.8em``
inside an 11px heading, 8.8px on screen, and this sweep could not have found
it. So this is a guard against the literal coming back, not a proof that
nothing renders small; the rendered audit is the measurement.

Shape copied from the other self-counting sweeps: the scan has to report how
much it read (``test_the_sweep_read_the_stylesheets``), every exemption has to
still be needed (``test_every_glyph_exemption_is_still_small``, the
``pytest.xfail`` lesson -- an exemption nobody re-checks outlives its reason),
and the matcher has to catch the value it replaced (the negative control).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "web"
CSS_DIR = WEB / "css"
STYLES_CSS = CSS_DIR / "styles.css"

FLOOR_PX = 12.0
ROOT_PX = 16.0

#: (file, selector) -> what the glyph is. Kept small and named, so a new
#: exemption is a visible decision in review rather than a quiet literal.
GLYPHS = {
    ("analytics.css", ".sunburst-info-icon"): 'the italic "i" in an 18px info circle',
    ("weight_analysis.css", ".efficiency-info-icon"): 'the italic "i" in an info circle',
    ("browser.css", ".dropdown-arrow"): "the filter dropdown's caret",
    ("browser.css", ".tree-toggle"): "the subject tree's expand caret",
    ("entry.css", ".tag-context-pill-caret"): "the tag-context pill's caret",
    ("entry.css", ".dictation-icon"): "the dictation button's record dot",
    ("difficulty.css", ".difficulty-badge--dots::before"): "the five difficulty dots",
}

#: Text still under the floor because raising it needs a decision that has
#: not been made. Not an exemption: each entry names what it waits for, and
#: ``test_every_pending_entry_is_still_small`` fails the day it is raised so
#: the entry gets deleted rather than outliving its reason.
PENDING: dict = {}

#: Charts are a separate pass (owner, 2026-10-06). D3 sets these labels with
#: ``.attr('font-size', ...)`` / ``.style('font-size', ...)``.
CHART_MODULES = {
    "sunburst_chart.js",
    "heatmap_chart.js",
    "source_chart.js",
    "dimension_heatmap.js",
}

_SIZE = r"([0-9]*\.?[0-9]+)\s*(rem|px|pt)\b"
_DECL = re.compile(r"font-size\s*:\s*" + _SIZE)
_JS_DECL = re.compile(r"font-size['\"]?\s*[:,]\s*['\"]?" + _SIZE)


def _px(value: str, unit: str) -> float:
    n = float(value)
    return n * ROOT_PX if unit == "rem" else n * 4 / 3 if unit == "pt" else n


def _strip_comments(css: str) -> str:
    # Keep line numbers stable: replace each comment with its own newlines.
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), css, flags=re.S)


def css_small_declarations(css: str) -> list[tuple[str, int, str, float]]:
    """(selector, line, literal, px) for every sub-floor font-size in ``css``."""
    css = _strip_comments(css)
    out = []
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector = " ".join(rule.group(1).split())
        for decl in _DECL.finditer(rule.group(2)):
            px = _px(decl.group(1), decl.group(2))
            if px < FLOOR_PX:
                line = css.count("\n", 0, rule.start(2) + decl.start()) + 1
                out.append((selector, line, decl.group(0), px))
    return out


def text_small_declarations(text: str, pattern=_DECL) -> list[tuple[int, str, float]]:
    """(line, literal, px) for every sub-floor font-size in markup or script."""
    out = []
    for decl in pattern.finditer(text):
        px = _px(decl.group(1), decl.group(2))
        if px < FLOOR_PX:
            out.append((text.count("\n", 0, decl.start()) + 1, decl.group(0), px))
    return out


def _css_files() -> list[Path]:
    return sorted(CSS_DIR.glob("*.css"))


def _html_files() -> list[Path]:
    return sorted((WEB / "html").rglob("*.html"))


def _js_files() -> list[Path]:
    return sorted((WEB / "js").rglob("*.js"))


def _offenders() -> list[str]:
    found = []
    for f in _css_files():
        for selector, line, literal, px in css_small_declarations(f.read_text(encoding="utf-8")):
            if (f.name, selector) in GLYPHS or (f.name, selector) in PENDING:
                continue
            found.append(f"{f.relative_to(ROOT)}:{line} {selector} {{{literal}}} = {px:g}px")
    for f in _html_files():
        for line, literal, px in text_small_declarations(f.read_text(encoding="utf-8")):
            found.append(f"{f.relative_to(ROOT)}:{line} {literal} = {px:g}px")
    for f in _js_files():
        if f.name in CHART_MODULES:
            continue
        for line, literal, px in text_small_declarations(f.read_text(encoding="utf-8"), _JS_DECL):
            found.append(f"{f.relative_to(ROOT)}:{line} {literal} = {px:g}px")
    return found


def test_the_floor_is_the_smallest_token() -> None:
    css = STYLES_CSS.read_text(encoding="utf-8")
    m = re.search(r"--font-size-xs\s*:\s*" + _SIZE, css)
    assert m, "styles.css no longer defines --font-size-xs"
    assert _px(m.group(1), m.group(2)) == FLOOR_PX, (
        f"--font-size-xs is {m.group(0)!r}; #308's floor is defined as that token at 12px")


def test_no_text_is_styled_below_12px() -> None:
    offenders = _offenders()
    assert offenders == [], (
        "text styled below the 12px floor (#308). Use var(--font-size-xs); if "
        "this is an icon or caret, add it to GLYPHS with what it is:\n  "
        + "\n  ".join(offenders))


def test_the_sweep_read_the_stylesheets() -> None:
    """Self-count: an empty glob or a broken rule regex must not read as clean."""
    decls = sum(len(_DECL.findall(_strip_comments(f.read_text(encoding="utf-8"))))
                for f in _css_files())
    token_uses = sum(f.read_text(encoding="utf-8").count("font-size: var(--font-size-xs)")
                     for f in _css_files())
    assert len(_css_files()) >= 30, f"only {len(_css_files())} stylesheets found under {CSS_DIR}"
    assert len(_js_files()) >= 30, f"only {len(_js_files())} scripts found"
    # 2026-10-06: ~180 literal sizes and >200 uses of the floor token.
    assert decls >= 100, f"the sweep parsed only {decls} literal font-sizes"
    assert token_uses >= 200, f"only {token_uses} declarations use the floor token"


def _small_rules() -> set[tuple[str, str]]:
    return {(f.name, sel) for f in _css_files()
            for sel, *_ in css_small_declarations(f.read_text(encoding="utf-8"))}


def test_every_glyph_exemption_is_still_small() -> None:
    """An exemption whose rule moved, was renamed or was raised is stale."""
    stale = sorted(set(GLYPHS) - _small_rules())
    assert stale == [], f"GLYPHS entries no longer below the floor; remove them: {stale}"


def test_every_pending_entry_is_still_small() -> None:
    """Raised at last? Then delete its PENDING line, or it exempts nothing forever."""
    done = sorted(set(PENDING) - _small_rules())
    assert done == [], f"PENDING entries now meet the floor; remove them: {done}"


def test_every_chart_module_exists() -> None:
    names = {f.name for f in _js_files()}
    assert CHART_MODULES <= names, f"chart modules renamed or gone: {CHART_MODULES - names}"


def test_the_matcher_catches_what_it_replaced() -> None:
    """Negative control: the values #308 removed must fail; the floor must not."""
    css = """
    .tag-chip { color: red; font-size: 0.6875rem; }
    @media (max-width: 768px) {
        .exam-stat-label,
        .x { font-size: 0.625rem }
    }
    .ok { font-size: var(--font-size-xs); }
    .ok2 { font-size: 0.75rem; }
    .rel { font-size: 0.8em; }
    /* .commented { font-size: 10px; } */
    """
    got = [(sel, px) for sel, _line, _lit, px in css_small_declarations(css)]
    assert got == [(".tag-chip", 11.0), (".exam-stat-label, .x", 10.0)]
    assert text_small_declarations('<span style="font-size: 10px;">') == [
        (1, "font-size: 10px", 10.0)]
    assert [px for *_, px in text_small_declarations(
        ".attr('font-size', '10px') .style('font-size','11px') x.style.fontSize = '9px'",
        _JS_DECL)] == [10.0, 11.0]
