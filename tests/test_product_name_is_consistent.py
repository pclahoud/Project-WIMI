"""The product is called "Why I Missed It", in every place that says so (#312).

Owner's decision, 2026-10-03. WIMI expanded **two different ways** before this:
``index.html``'s hero said *Why*, while the window title, the About panel, the
Qt shell and the CLI said *What*. Two of those are the first thing a student
sees and one of them is the s5(d) legal notices document.

**The acronym no longer expands letter for letter, and that is the decision.**
*What* matches W-I-M-I; *Why* matches the product, which is about reflection
rather than about the question you got wrong. The owner chose meaning over
spelling. Anyone who finds this later and reads it as a typo should read #312
before "fixing" it -- which is most of why this test exists rather than a
comment.

Why a test and not a one-time sweep
-----------------------------------
There were **eight** sites, and the audit that found the inconsistency only
looked at the two web pages. The other four were in the Qt shell and the CLI,
including ``main_window.py``'s ``setWindowTitle`` -- i.e. the *actual* window
title, as opposed to the HTML ``<title>`` the audit did find. A sweep that
misses half its sites recreates the bug it just fixed, so the sweep is the test.

What is deliberately NOT swept
------------------------------
``docs/handoff/``, ``docs/phases/`` and the other dated documents are a
**record of what was written at the time**. Rewriting them would falsify a
history nobody can check afterwards, and they are not shipped. Only live code
and the two documents a reader is pointed at are covered.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CANONICAL = "Why I Missed It"
REJECTED = "What I Missed It"

# Live code and the primary docs. Not docs/handoff, docs/phases or any dated
# planning document -- see the module docstring.
SWEPT_FILES = [
    Path("src/app/cli.py"),
    Path("src/app/main.py"),
    Path("src/app/main_window.py"),
    Path("src/web/html/index.html"),
    Path("src/web/html/settings.html"),
    Path("README.md"),
    Path("CLAUDE.md"),
]

# Where the name must actually appear, so the sweep cannot pass by the name
# having been deleted everywhere.
MUST_NAME_THE_PRODUCT = [
    Path("src/web/html/index.html"),     # window <title> and the hero
    Path("src/web/html/settings.html"),  # the About panel = s5(d) notices
    Path("src/app/main_window.py"),      # setWindowTitle
    Path("README.md"),
]


def _read(rel: Path) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", SWEPT_FILES, ids=lambda p: str(p))
def test_no_live_file_uses_the_rejected_expansion(rel: Path):
    text = _read(rel)
    if REJECTED not in text:
        return
    lines = [
        f"  {rel}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if REJECTED in line
    ]
    pytest.fail(
        f'{rel} still expands WIMI as "{REJECTED}". The owner settled this in '
        f'#312: the name is "{CANONICAL}". The acronym deliberately no longer '
        f"matches letter for letter.\n" + "\n".join(lines)
    )


@pytest.mark.parametrize("rel", MUST_NAME_THE_PRODUCT, ids=lambda p: str(p))
def test_the_places_that_name_the_product_still_do(rel: Path):
    """Negative control for the sweep above.

    Deleting the name everywhere would satisfy "no file uses the rejected
    expansion" perfectly. These four must still carry it.
    """
    assert CANONICAL in _read(rel), (
        f"{rel} no longer names the product at all. The sweep in this file "
        f"passes trivially if the name is deleted rather than corrected")


def test_the_about_panel_and_the_window_title_agree():
    """The two that disagreed, pinned against each other.

    The whole defect was these two drifting apart, so asserting each
    separately is not enough -- that is what let it happen.
    """
    index = _read(Path("src/web/html/index.html"))
    settings = _read(Path("src/web/html/settings.html"))

    title = re.search(r"<title>(.*?)</title>", index, re.S)
    assert title, "index.html has no <title>"
    assert CANONICAL in title.group(1), (
        f"the window title reads {title.group(1)!r}, which does not name the "
        f"product as {CANONICAL!r}")

    # The About panel's own line, not just the file.
    about = re.search(r"<strong>([^<]*Missed It)</strong>", settings)
    assert about, "the About panel no longer names the product in its <strong>"
    assert about.group(1).strip() == CANONICAL, (
        f"the About panel says {about.group(1)!r} and the window title says "
        f"{CANONICAL!r}; #312 exists because these two disagreed")


def test_the_qt_shell_and_the_web_page_agree():
    """`setWindowTitle` and the HTML <title> are different code paths.

    The audit that found #312 checked the HTML and missed the Qt call, so the
    *real* window title was wrong while the one it looked at was being fixed.
    """
    shell = _read(Path("src/app/main_window.py"))
    assert f"WIMI - {CANONICAL}" in shell, (
        "main_window.py's setWindowTitle does not name the product correctly - "
        "this is the actual OS window title, not the HTML <title>")
