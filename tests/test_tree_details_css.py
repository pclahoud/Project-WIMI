"""Static guards on the tree editor's details-panel stylesheet.

#344: a block left over from the panel's pre-sticky-header layout sat AFTER
the rules that replaced it, at equal specificity, so it won on source order.
`.details-content { padding }` inset the sticky header 25 px from the panel
edge and a second `.details-title { margin: 0 }` flushed the title onto its
subtitle. Nothing errored; the rules that were meant to apply simply did not.

The shape to stop is "the same selector declared twice in one file", which is
how a stale rule overrides a live one without anybody seeing it, plus the one
wrapper that must carry no inset of its own.
"""

import re
from collections import Counter
from pathlib import Path

TREE_CSS = Path(__file__).resolve().parents[1] / "src" / "web" / "css" / "tree.css"

# Selectors of the details panel that must be declared exactly once at the top
# level of tree.css. A second declaration is the #344 shape.
DETAILS_SELECTORS = (
    ".details-panel",
    ".details-panel-header",
    ".details-panel-eyebrow",
    ".details-title",
    ".details-subtitle",
    ".details-panel-body",
    ".details-placeholder",
    ".details-placeholder-text",
    ".details-placeholder-title",
)


def _top_level_rules(css: str):
    """(selector, body) for every rule outside an at-rule block."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules, depth, start, selector = [], 0, 0, None
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                selector = css[start:i].strip()
                body_start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                if not selector.startswith("@"):
                    rules.append((selector, css[body_start:i]))
                start = i + 1
    return rules


def _problems(css: str):
    rules = _top_level_rules(css)
    counts = Counter(sel for sel, _ in rules)
    problems = [
        f"{sel} is declared {counts[sel]} times; the later one silently wins"
        for sel in DETAILS_SELECTORS
        if counts[sel] > 1
    ]
    for sel, body in rules:
        if sel == ".details-content" and re.search(r"\bpadding", body):
            problems.append(
                ".details-content carries padding, which insets the sticky "
                "header from the panel edge"
            )
        if sel in (".details-header", ".details-level"):
            problems.append(f"{sel} matches nothing in the page (#344)")
    return problems


def test_the_details_panel_rules_are_declared_once():
    assert _problems(TREE_CSS.read_text(encoding="utf-8")) == []


def test_the_guard_catches_the_original_block():
    """Negative control: #344's block, appended to the live rules, must fail."""
    original_block = """
    .details-content { padding: var(--space-lg); }
    .details-header { display: flex; }
    .details-title { font-size: var(--font-size-xl); margin: 0; }
    .details-level { font-size: var(--font-size-sm); }
    """
    problems = _problems(TREE_CSS.read_text(encoding="utf-8") + original_block)
    assert len(problems) == 4, problems


def test_rules_inside_media_queries_are_not_counted_as_duplicates():
    """The breakpoint legitimately restates `.details-panel`; that is not #344."""
    css = ".details-panel { a: b; } @media (max-width: 900px) { .details-panel { c: d; } }"
    assert _problems(css) == []
