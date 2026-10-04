"""Regression: the dashboard and the tree editor skipped h1 -> h3 (#317).

From the issue:

    The dashboard and the tree editor skip a heading level, ``h1`` ->
    ``h3``. A screen-reader user navigating by heading hears a level-3
    heading directly under a level-1 and cannot tell whether a level-2
    section was missed or never existed.

``tests/test_heading_order.py`` is the cheap sweep over every page's markup
and is where this class of bug is guarded in general. **It cannot see either
of the two headings this scenario is about**, and that is the whole reason
this file exists:

* ``analytics_preview.js`` renders ``<h3 class="analytics-preview-title">``
  into ``#analytics-preview-container``, which sits in ``index.html`` *above*
  the ``h2`` of "Your Exams". The dashboard's markup is clean; its rendered
  outline was ``h1 -> h3``.
* ``tree_editor.js``'s ``showOverview()`` **replaces** the content of
  ``.details-placeholder`` with an ``h3`` "Exam Overview" whenever the exam
  has subjects and nothing is selected -- which is the state the page opens
  in. So the skip the Windows audit screenshotted is in the JavaScript, not
  in ``tree_editor.html``, and the two ``h3``s that *are* in that page's
  markup are a different pair.

Both were fixed by re-tagging, never by restyling: every class involved
(``.analytics-preview-title``, ``.overview-title``, ``.overview-section-title``,
``.tree-empty-title``, ``.details-placeholder-title``) already carried an
explicit ``font-size`` in its stylesheet, so the level changed and the pixels
did not.

The third test here is ``entry_detail.html``'s, and it is in this file rather
than in the markup sweep for the mirror-image reason: the sweep proves the
``h1`` #317 added **exists** and is an ``h1``, and cannot prove anything
**fills** it. An ``h1`` stuck forever on its holding value would satisfy every
markup check and tell a reader nothing, so that one is checked against the
rendered page too.

What is asserted is the **rendered, visible** outline, because that is what a
reader navigates. A heading inside a closed modal is not in the outline (the
backdrops are ``visibility: hidden`` until ``.active``), and filtering on
``checkVisibility`` is what keeps this scenario about the page rather than
about every dialog the page could open.

Each test guards against passing vacuously by first asserting that the heading
it is about actually rendered -- "Quick Analytics", "Exam Overview", a
populated ``h1`` -- because all three live behind a load that can fail
silently, and an empty outline trivially skips no level.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Document order is what querySelectorAll returns, which is what a reader
# navigating by heading walks. `checkOpacity` is what excludes the closed
# modal backdrops (opacity 0 / visibility hidden until `.active`).
_OUTLINE_JS = """
(() => {
  const out = [];
  document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(el => {
    const visible = typeof el.checkVisibility === 'function'
      ? el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
      : el.offsetParent !== null;
    if (visible) {
      out.push([Number(el.tagName.slice(1)),
                (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60)]);
    }
  });
  return JSON.stringify(out);
})()
"""


def _outline(page: WimiPage) -> list[tuple[int, str]]:
    return [(int(lvl), text) for lvl, text in json.loads(page.eval_js(_OUTLINE_JS))]


def _wait_for_text(page: WimiPage, needle: str, attempts: int = 80):
    """Poll until a visible heading contains ``needle``; return the outline."""
    outline: list[tuple[int, str]] = []
    for _ in range(attempts):
        outline = _outline(page)
        if any(needle.lower() in text.lower() for _, text in outline):
            return outline
        page.wait_for_timeout(100)
    return outline


def _describe(outline) -> str:
    return "; ".join(f"h{lvl} {text!r}" for lvl, text in outline)


def _assert_descends(outline, page_name: str) -> None:
    assert outline, f"{page_name} rendered no visible heading at all"
    first_level, first_text = outline[0]
    assert first_level == 1, (
        f"{page_name}'s first visible heading is an h{first_level} "
        f"({first_text!r}), not an h1. Rendered outline: {_describe(outline)}"
    )
    skips = [
        (prev_lvl, prev_text, lvl, text)
        for (prev_lvl, prev_text), (lvl, text) in zip(outline, outline[1:])
        if lvl > prev_lvl + 1
    ]
    assert not skips, (
        f"{page_name} skips a heading level in its RENDERED outline: "
        + "; ".join(
            f"h{p} {pt!r} -> h{l} {t!r} (nothing is h{p + 1})"
            for p, pt, l, t in skips
        )
        + f".\nRendered outline: {_describe(outline)}.\n"
        f"Heading level is the document outline (#317). These headings are "
        f"built by JavaScript, so tests/test_heading_order.py cannot see them."
    )


# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.regression
def test_the_dashboard_outline_descends_without_gaps(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """``analytics_preview.js``'s title sits above "Your Exams"'s h2."""
    # ---- Arrange -----------------------------------------------------
    # One entry is enough to take the preview's populated render path --
    # the path the Windows audit saw. Its empty and error renders carry
    # the same heading, so the fix covers all three.
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="W317 Heading Order", exam_description="Issue #317",
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name="w317", date_encountered=date.today(),
    )
    db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer, is_draft) VALUES (?, 1, 'a', 'b', 0)",
        (session.id,),
    )
    db.conn.commit()

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("dashboard")
    outline = _wait_for_text(wimi_page, "Quick Analytics")

    # ---- Assert ------------------------------------------------------
    assert any("quick analytics" in t.lower() for _, t in outline), (
        "the analytics preview never rendered, so this scenario would pass "
        f"without exercising the heading it guards. Outline: {_describe(outline)}"
    )
    _assert_descends(outline, "index.html (the dashboard)")


@pytest.mark.slow
@pytest.mark.regression
def test_the_tree_editor_outline_descends_without_gaps(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """``showOverview()`` is the state the page opens in, not an edge case."""
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="W317 Tree Headings", exam_description="Issue #317",
    )
    root = db.create_subject_node(
        exam_context=exam.exam_name, name="W317 Root", level_type="System",
    )
    db.create_subject_node(
        exam_context=exam.exam_name, name="W317 Child", level_type="Topic",
        parent_id=root.id,
    )

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    outline = _wait_for_text(wimi_page, "Exam Overview")

    # ---- Assert ------------------------------------------------------
    assert any("exam overview" in t.lower() for _, t in outline), (
        "showOverview() never ran, so the h3 this scenario guards was never "
        f"rendered and the assertion below would be vacuous. Outline: "
        f"{_describe(outline)}"
    )
    _assert_descends(outline, "tree_editor.html")


@pytest.mark.slow
@pytest.mark.regression
def test_the_entry_detail_h1_names_the_entry(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The h1 #317 added is populated, not merely present.

    ``tests/test_heading_order.py`` proves the element exists and is an h1.
    What it cannot see is whether anything fills it -- an h1 permanently
    reading its holding value would satisfy every markup check and tell the
    reader nothing. The text follows #314's decision (session + question).
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="W317 Detail Heading", exam_description="Issue #317",
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=12, total_incorrect=3,
        session_name="W317 Day 11",
    )
    # Three entries so the one under test has entry_order 3 -- a heading that
    # hardcoded "Question 1", or read the row id, would pass on one entry.
    entry_id = None
    for _ in range(3):
        entry_id = db.create_question_entry(
            review_session_id=session.id, user_answer="a", correct_answer="b",
            reflection="<p>w317</p>",
        ).id
    order = db.fetchone(
        "SELECT entry_order FROM question_entries WHERE id = ?", (entry_id,)
    )["entry_order"]
    assert order == 3, f"expected the third entry to be order 3, got {order}"

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("entry-detail", query={"id": entry_id})
    outline = _wait_for_text(wimi_page, "Question")

    # ---- Assert ------------------------------------------------------
    heading = outline[0] if outline else None
    assert heading is not None, "entry_detail.html rendered no visible heading"
    level, text = heading
    assert level == 1, (
        f"entry_detail.html's first visible heading is an h{level} ({text!r}); "
        f"#317 added an h1. Outline: {_describe(outline)}"
    )
    assert text == f"W317 Day 11 — Question {order}", (
        f"the h1 reads {text!r}. #314 specifies the entry named by session + "
        f"question, and `entry_order` is the question number within the "
        f"session -- not the row id and not the free-text question_id"
    )
    _assert_descends(outline, "entry_detail.html")
