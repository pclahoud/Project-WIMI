"""Every page the tour runs on has steps the runner can resolve (#430).

**The exemption, stated so it is not read as laxness.** `tour_steps.js` holds
steps for eight pages, and #430 wires them one page at a time: *"a page whose
tour is not written yet simply has none."* So a page with no tour wired is
legitimately unchecked here. What makes that safe is that "wired" is
**derived, not maintained**: a page is wired when first-party JS calls
`WimiTour.start('<page>')`, which is the very call that makes the runner draw
on it. The guard and the runner therefore cannot disagree about which pages
have a tour, and the second page is covered the day it is wired, with no list
to remember to extend (`test_page_gate_markup.py`'s self-counting shape).

For a wired page, every step's anchor, and its fork anchor, must be an
identifier: a `data-tour-anchor` or `data-testid` value. A prose anchor means
the page was wired before its chapter blocks were converted, and the runner
would skip that step silently. This is where that fails instead.

Whether each identifier actually renders is the scenario half,
`tests/wimi_test/scenarios/test_tour_anchors_resolve.py`, because every
dashboard anchor is drawn by JavaScript and a markup search would find none.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "src" / "web" / "js"
STEPS = JS / "tour_steps.js"
IDENTIFIER = re.compile(r"^[a-z0-9-]+$")
START_CALL = re.compile(r"""WimiTour\.start\(\s*['"]([a-z-]+)['"]\s*\)""")
ANY_START = re.compile(r"WimiTour\.start\(")


def wired_pages() -> dict[str, list[str]]:
    """{page: [files that start a tour on it]}, read from the call sites."""
    pages: dict[str, list[str]] = {}
    for path in sorted(JS.rglob("*.js")):
        if path.name in ("tour.js", "tour_steps.js") or "/lib/" in path.as_posix():
            continue
        for page in START_CALL.findall(path.read_text(encoding="utf-8")):
            pages.setdefault(page, []).append(path.relative_to(ROOT).as_posix())
    return pages


def all_steps() -> dict[str, list[dict]]:
    text = STEPS.read_text(encoding="utf-8")
    payload = text.split("window.WIMI_TOUR_STEPS = ", 1)[1].rstrip().rstrip(";")
    return json.loads(payload)


def test_every_start_call_names_its_page_literally():
    """What makes the scan above exhaustive rather than best-effort.

    `wired_pages` reads `WimiTour.start('<page>')` from source, so a call
    through a variable (`WimiTour.start(pageName)`) would draw a tour that no
    guard checks. That fails open, the one direction that costs a student a
    step. So the form the scan cannot read is forbidden outright.
    """
    unreadable = []
    for path in sorted(JS.rglob("*.js")):
        if path.name in ("tour.js", "tour_steps.js") or "/lib/" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        if len(ANY_START.findall(text)) != len(START_CALL.findall(text)):
            unreadable.append(path.relative_to(ROOT).as_posix())
    assert not unreadable, (
        f"{unreadable} call WimiTour.start with something other than a page "
        f"name in quotes, which the wiring guards cannot see. Name the page "
        f"literally")


def test_the_dashboard_is_wired():
    """The found-it control. Without it, a regex that matched nothing would
    pass every assertion below by checking zero pages."""
    assert "dashboard" in wired_pages(), wired_pages()


def test_every_wired_page_has_steps():
    steps = all_steps()
    for page, files in wired_pages().items():
        assert steps.get(page), (
            f"{files} start a tour on {page!r}, which has no steps in "
            f"tour_steps.js. A wired page with nothing to show is a dead call")


def test_every_wired_step_points_at_an_identifier():
    steps = all_steps()
    problems = []
    for page in wired_pages():
        for step in steps.get(page, []):
            for key in ("anchor", "fork_anchor"):
                value = step.get(key)
                if value is not None and not IDENTIFIER.match(value):
                    problems.append(f"{page}: {key} {value!r}")
    assert not problems, (
        "These steps are on a page the runner draws on, but their anchors are "
        "still prose, so the runner would skip them silently. Convert their "
        "chapter blocks (anchor: <data-tour-anchor or data-testid value>):\n  "
        + "\n  ".join(problems))
