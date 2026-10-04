"""Every page's heading levels descend without gaps, and start at h1 (#317).

Why a sweep rather than three fixes
-----------------------------------
#317 named three sites -- the dashboard and the tree editor skipping ``h1`` ->
``h3``, and ``entry_detail.html`` having no ``h1`` at all -- and noted that
``tests/test_page_gate_markup.py`` is the model for a guard that would make
this a class of bug the repo cannot reacquire. It also noted the honest limit
of the audit that found them: it visited 12 pages at one window size, in one
theme, with no screen reader. A sweep settles the rest.

Heading level **is** the document outline. It is one of the two things a
non-visual reader navigates by (the other is landmarks), and a level-3 heading
directly under a level-1 is indistinguishable from a level-2 section the reader
missed. Nothing in the rendered page says which it was, which is why this is
invisible to every test anybody would otherwise write.

The rule, and what is deliberately NOT in it
--------------------------------------------
Two things are asserted, per page:

1. no heading is more than one level below the heading before it, in document
   order;
2. the page's first heading is an ``h1``.

What is **not** asserted is anything about size. A heading's level is the
outline; its size is CSS. Every class this guard's own fixes re-tagged
(``.tree-empty-title``, ``.details-placeholder-title``, ``.overview-title``,
``.overview-section-title``, ``.analytics-preview-title``) already carried an
explicit ``font-size`` in its stylesheet, so each change was visually inert --
and if a future one is not, the fix is a CSS rule, never a heading level.

Nor is "exactly one ``h1``" asserted. It is a defensible rule and two pages
would need discussion rather than a one-character change, so it is left to
whoever takes the pending list below.

Why no hidden-subtree exclusion
-------------------------------
The obvious refinement is to skip headings inside containers the markup says
are not rendered -- ``hidden``, ``class="hidden"`` (``display: none
!important`` in styles.css), an inline ``display: none``, a closed
``.modal-backdrop``. It was measured and **rejected**, because it is how this
guard would go green without being right:

======================  ===========  ======================================
rule                    pages failing
======================  ===========  ======================================
every heading (used)    6            tree_editor, entry_detail, entry_browser,
                                     profile_select, question_entry, exam_wizard
skip hidden subtrees    3            and ``entry_detail.html`` reports **zero
                                     headings**, so its missing ``h1`` -- one
                                     of the three defects #317 was filed for --
                                     stops being visible at all
======================  ===========  ======================================

That is the same failure mode ``test_page_gate_markup.py`` wrote
``test_the_parser_can_see_the_page_at_all`` to prevent: a check that passes by
not looking. A hidden container is also only hidden *now*; every one of these
is revealed by script at some point, and the outline it lands in is the one
written here.

What this guard cannot see
--------------------------
**Headings built by JavaScript.** This is a markup check, and the single worst
instance in the tree was invisible to it: ``analytics_preview.js`` renders
``<h3 class="analytics-preview-title">`` into ``#analytics-preview-container``,
which sits in ``index.html`` *above* the ``h2`` of "Your Exams" -- so the
dashboard's rendered outline was ``h1 -> h3`` while its markup was clean. The
tree editor's was the same shape: ``showOverview()`` replaces
``.details-placeholder``'s content with an ``h3`` "Exam Overview", so the skip
the Windows audit screenshotted is in ``tree_editor.js``, not in the page.

``tests/wimi_test/scenarios/test_heading_levels_descend.py`` covers those two
pages against the **rendered** DOM for exactly that reason. Neither check
subsumes the other: this one reaches every page cheaply, that one reaches the
headings that only exist at runtime.

The pending list
----------------
#317's scope is three sites. The sweep found five more pages, which are
recorded in ``PENDING_SKIPS`` / ``PENDING_NO_H1`` with the issue that tracks
them (#318) rather than fixed here -- a PR about three sites should not quietly
re-tag a dozen headings across pages nobody asked it to look at. A page that is
**not** listed is checked from the day it is written, which is the whole point
of discovering pages rather than listing them.

**A pending entry cannot outlive the defect it names.**
``test_every_pending_page_still_fails`` asserts that each listed page really
does still break the rule it is listed under, so fixing one fails this file
until its line is deleted. That test is not decoration: ``pytest.xfail()`` is
imperative and is reached only from inside the failing branch, so without it a
fixed page would simply pass and leave a stale entry behind -- quietly
exempting that page from the guard again the next time somebody edits it. This
file claimed the exemptions were self-correcting before that test existed, and
they were not.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

WEB_HTML = Path(__file__).resolve().parents[1] / "src" / "web" / "html"

LEVELS = {f"h{n}": n for n in range(1, 7)}

# Pages whose heading order is known-wrong and deliberately NOT fixed by #317.
# Keyed by filename -> (which check, what is wrong). Both checks consult this,
# so a page may appear under either or both.
#
# Tracked in #318. Delete a line when its page is fixed --
# test_every_pending_page_still_fails below makes a stale entry fail this file
# and say so, which is what stops an exemption outliving its defect.
PENDING_SKIPS = {
    "entry_browser.html":
        "h1 -> h3 at the empty-state title (#emptyTitle), which is the only "
        "other heading on the page",
}
# Three of #318's five were MODAL titles, and #318 deliberately left the level
# open ("whether a modal's heading belongs to the page's outline or starts its
# own is a real question... worth settling once for all ~40 modals instead of
# per page"). The owner settled it inside #319's pattern on 2026-10-03: a
# dialog title is an **h2**, one level under the page's h1 wherever the modal
# sits in document order -- which is also the only level that cannot create a
# skip. So `profile_select.html`, `question_entry.html` and
# `wizards/exam_wizard.html` left this list with that decision, and
# `tests/test_modal_dialog_markup.py::test_a_dialog_title_is_an_h2` is what
# keeps them right. The two that remain are not modal titles.

PENDING_NO_H1 = {
    "error-viewer.html":
        "the page has no heading of any level -- .viewer-title and "
        ".stats-title are <div>s. A developer utility, but the fix is the "
        "same two elements",
}


class _HeadingReader(HTMLParser):
    """Collect ``(level, line)`` for every h1-h6 inside ``<body>``.

    Deliberately not a tree: this check needs document order and nothing else,
    so it carries no ancestry and cannot be wrong about nesting. ``<template>``
    content is skipped -- a template is inert markup for cloning, not part of
    the document's outline until something clones it, and the clone's position
    is a runtime fact this file cannot see either way.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[tuple[int, int]] = []
        self._in_body = False
        self._template_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "body":
            self._in_body = True
            return
        if tag == "template":
            self._template_depth += 1
            return
        if tag in LEVELS and self._in_body and not self._template_depth:
            self.headings.append((LEVELS[tag], self.getpos()[0]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "template" and self._template_depth:
            self._template_depth -= 1


def _headings(path: Path) -> list[tuple[int, int]]:
    reader = _HeadingReader()
    reader.feed(path.read_text(encoding="utf-8"))
    return reader.headings


def _html_pages() -> list[Path]:
    pages = sorted(WEB_HTML.rglob("*.html"))
    assert pages, f"no HTML pages found under {WEB_HTML}"
    return pages


def _page_id(path: Path) -> str:
    return str(path.relative_to(WEB_HTML).as_posix())


def _outline(headings: list[tuple[int, int]]) -> str:
    return ", ".join(f"h{level}@{line}" for level, line in headings)


def _maybe_xfail(path: Path, pending: dict[str, str]) -> None:
    reason = pending.get(_page_id(path))
    if reason is not None:
        pytest.xfail(f"{_page_id(path)}: {reason} (#318)")


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _html_pages(), ids=_page_id)
def test_no_page_skips_a_heading_level(path: Path) -> None:
    headings = _headings(path)
    if len(headings) < 2:
        pytest.skip(f"{_page_id(path)} has fewer than two headings")

    skips = [
        (prev, level, line)
        for (prev, _), (level, line) in zip(headings, headings[1:])
        if level > prev + 1
    ]
    if skips:
        _maybe_xfail(path, PENDING_SKIPS)
    assert not skips, (
        f"{_page_id(path)} skips a heading level: "
        + "; ".join(
            f"line {line}: h{prev} -> h{level} (nothing is h{prev + 1})"
            for prev, level, line in skips
        )
        + f".\nOutline in document order: {_outline(headings)}.\n"
        f"Heading level is the document outline, so a reader navigating by "
        f"heading cannot tell a skipped level from a section they missed "
        f"(#317). Use the level the outline implies -- never one chosen for "
        f"its size, which belongs in CSS."
    )


@pytest.mark.parametrize("path", _html_pages(), ids=_page_id)
def test_every_page_starts_at_h1(path: Path) -> None:
    headings = _headings(path)
    if not headings or headings[0][0] != 1:
        _maybe_xfail(path, PENDING_NO_H1)

    assert headings, (
        f"{_page_id(path)} has no heading at all, so it has no document "
        f"outline and nothing for a reader to navigate by (#317)."
    )
    level, line = headings[0]
    assert level == 1, (
        f"{_page_id(path)}'s first heading is an h{level} at line {line}, not "
        f"an h1, so the page has no top of its outline. Outline in document "
        f"order: {_outline(headings)} (#317)."
    )


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------


def test_the_three_sites_317_names_are_actually_covered() -> None:
    """The parametrised checks skip a page with too few headings.

    Both checks above bail out on a page with fewer than two headings, and
    "fewer than two headings" is also what a *failed parse* looks like. Without
    this, a reader that silently stopped collecting would leave the whole file
    green. These are the three pages #317 was filed for, so if any of them
    stops being read, this fails rather than the file passing by skipping.
    """
    for page, least in (
        ("index.html", 3),
        ("tree_editor.html", 6),
        ("entry_detail.html", 6),
    ):
        headings = _headings(WEB_HTML / page)
        assert len(headings) >= least, (
            f"expected at least {least} headings in {page}, read "
            f"{len(headings)} -- the reader is not seeing this page, so every "
            f"check in this file skips it"
        )
        assert headings[0][0] == 1, (
            f"{page}'s first heading is an h{headings[0][0]}; #317 fixed all "
            f"three of these pages to start at h1"
        )


def test_the_reader_would_catch_each_mistake() -> None:
    """Negative control: the two rules, each asserted to be detectable.

    A guard whose parser quietly found nothing would look exactly like a clean
    tree. Each case below is the real defect shape from #317.
    """

    def read(source: str) -> list[tuple[int, int]]:
        reader = _HeadingReader()
        reader.feed(source)
        return reader.headings

    # 1. The skip: the dashboard's and the tree editor's shape.
    levels = [lvl for lvl, _ in read(
        "<html><body><h1>Exam</h1><h3>No subject selected</h3></body></html>"
    )]
    assert levels == [1, 3], f"the reader did not see both headings: {levels}"

    # 2. No h1: entry_detail.html's shape.
    levels = [lvl for lvl, _ in read(
        "<html><body><h2>Failed to Load</h2><h3>Reflection</h3></body></html>"
    )]
    assert levels and levels[0] != 1, (
        "the reader cannot see that the first heading is not an h1")

    # 3. A correct page must trip nothing, or the rules fail on everything.
    headings = read(
        "<html><body><h1>A</h1><h2>B</h2><h3>C</h3><h2>D</h2></body></html>"
    )
    assert [lvl for lvl, _ in headings] == [1, 2, 3, 2]
    assert not [
        1 for (prev, _), (lvl, _) in zip(headings, headings[1:]) if lvl > prev + 1
    ], "the skip rule fires on a correctly ordered page"

    # 4. Headings in <head> and in a <template> are not part of the outline,
    #    and nothing outside <body> may be counted.
    assert read("<html><head><h1>no</h1></head><body><h2>x</h2></body></html>") \
        == [(2, 1)], "a heading outside <body> was counted"
    assert read("<html><body><template><h4>clone me</h4></template>"
                "<h1>real</h1></body></html>") == [(1, 1)], \
        "a heading inside <template> was counted as part of the outline"


def test_every_pending_page_still_fails() -> None:
    """An exemption may not outlive the defect it names.

    ``pytest.xfail()`` is imperative and the two parametrised checks reach it
    only from inside their failing branch, so a page that gets FIXED while
    still listed does not report anything -- it simply passes, and the stale
    line goes on exempting it from the guard the next time somebody edits that
    page. This is the test that makes the pending list self-correcting, and
    without it the mechanism does not work in the direction that matters.
    """
    for name, reason in PENDING_SKIPS.items():
        headings = _headings(WEB_HTML / name)
        skips = [
            (prev, level, line)
            for (prev, _), (level, line) in zip(headings, headings[1:])
            if level > prev + 1
        ]
        assert skips, (
            f"{name} no longer skips a heading level, but it is still listed in "
            f"PENDING_SKIPS as {reason!r}. Delete that line so the page is "
            f"guarded again (#318). Outline: {_outline(headings)}"
        )

    for name, reason in PENDING_NO_H1.items():
        headings = _headings(WEB_HTML / name)
        assert not headings or headings[0][0] != 1, (
            f"{name} now has an h1 as its first heading, but it is still listed "
            f"in PENDING_NO_H1 as {reason!r}. Delete that line (#318). "
            f"Outline: {_outline(headings)}"
        )


def test_the_pending_list_names_only_real_pages() -> None:
    """A pending entry for a page that no longer exists hides a live failure.

    If a listed page is renamed, its xfail silently stops applying -- and the
    rename would then look like a fix. Both lists are checked against the tree.
    """
    on_disk = {_page_id(p) for p in _html_pages()}
    for name in (*PENDING_SKIPS, *PENDING_NO_H1):
        assert name in on_disk, (
            f"{name} is on a pending list in this file but is not in "
            f"{WEB_HTML}. Either it was renamed -- update the key -- or it is "
            f"gone and the line should be deleted (#318)"
        )
