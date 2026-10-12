"""The analytics section holding both breakdown charts must not be named after one of them (#474).

`analytics_dashboard.html` put the **By Subject** sunburst and the **By
Mistake Type** donut under one `<h2>` that read "Mistake Type Breakdown". A
student reading top-down was told the sunburst's arcs -- the largest and
most-read chart on the page -- were a breakdown of error types, which is what
the *other* chart in the section is.

The heading has to cover both cards. This reads the markup rather than the
running page because the heading is static and nothing renders it; the cards
are found by their ids so the test follows the section, not a line number.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "src" / "web" / "html" / "analytics_dashboard.html"
CARDS = ("subjectBreakdownCard", "tagBreakdownCard")


class _Sections(HTMLParser):
    """Collects each <section>'s first <h2> text and the ids inside it."""

    def __init__(self) -> None:
        super().__init__()
        self.sections: list[dict] = []
        self._depth = 0
        self._in_h2 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section":
            if self._depth == 0:
                self.sections.append({"h2": None, "ids": set(), "_h2": ""})
            self._depth += 1
        if not self._depth:
            return
        current = self.sections[-1]
        if "id" in attrs:
            current["ids"].add(attrs["id"])
        if tag == "h2" and current["h2"] is None:
            self._in_h2 = True

    def handle_endtag(self, tag):
        if tag == "h2" and self._in_h2:
            self._in_h2 = False
            self.sections[-1]["h2"] = self.sections[-1]["_h2"].strip()
        if tag == "section" and self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._in_h2:
            self.sections[-1]["_h2"] += data


def _breakdown_heading() -> str:
    parser = _Sections()
    parser.feed(PAGE.read_text(encoding="utf-8"))
    holding = [s for s in parser.sections if all(c in s["ids"] for c in CARDS)]
    assert len(holding) == 1, (
        f"expected one <section> holding both {CARDS}, found {len(holding)}; "
        f"the guard below would be reading the wrong heading")
    heading = holding[0]["h2"]
    assert heading, "the section holding both breakdown charts has no <h2>"
    return heading


def test_the_breakdown_heading_names_neither_chart_alone() -> None:
    heading = _breakdown_heading()
    for one_card in (r"mistake\s+types?", r"subjects?", r"tags?"):
        assert not re.search(one_card, heading, re.IGNORECASE), (
            f"the section heading {heading!r} names one of its two charts "
            f"(By Subject, By Mistake Type) as if it were the whole section -- "
            f"#474")


def test_no_deep_dive_link_points_nowhere():
    """#474, owner's decision 2026-10-07: the dead link is removed.

    "Mistake Types Deep Dive ->" was ``href="#"`` -- no such page exists, so
    pressing it jumped to the top of the dashboard. If an error-type deep dive
    is ever built, its link comes back with it. The Subject Deep Dive link
    also ships ``href="#"`` but is given its real address by
    ``updateSubjectDeepDiveLink``, so the check is on the links nothing
    rewrites.
    """
    html = PAGE.read_text(encoding='utf-8')
    assert 'analytics-mistaketype-deepdive-link' not in html
    assert 'Mistake Types Deep Dive' not in html
    assert 'id="subjectDeepDiveLink"' in html, 'the sibling link must stay'
