"""Regression: on a dimensioned exam, "empty" means one axis is empty (#605).

The dimensioned load path reads one axis's subjects and nothing else, so a
subject in no axis is invisible to it. Every subject an exam had before its
first axis was added is in that state. Measured on ``3b2c208``: a plain exam
with three subjects, given one axis through Edit, opened to **"No Subjects
Yet"**, **"Add Your First Subject"** and an Exam Overview reading **"0
subjects across 0 roots."** All three were claims about the whole exam, and
all three were false.

The fix only names the axis. Where those subjects are, and what to do with
them, is #605's decision. That decision is to ask when the axis is added, so
an empty state must not settle it. This file asserts the naming and nothing
more.

**The positive control matters as much as the finding.** "It no longer says
0 subjects" is also true of a page that says nothing at all, and on a
genuinely empty plain exam that silence would be a regression in the common
case. So the second test pins the plain empty state word for word.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import open_tree_editor

# Null-safe throughout, so the pre-fix failure is a wrong string and not a JS
# error. `innerText` leaves out `display:none` subtrees, which is how a claim
# the page is actually showing differs from markup it holds hidden (#121).
READ = """
(() => {
  const one = sel => {
    const e = document.querySelector(sel);
    return e ? e.textContent.trim().replace(/\\s+/g, ' ') : null;
  };
  const empty = document.getElementById('tree-empty');
  return {
    emptyShown: !!empty && !empty.classList.contains('hidden'),
    title: one('#tree-empty .tree-empty-title'),
    button: one('#btn-add-first'),
    summary: one('.overview-summary'),
    overviewEmpty: one('.overview-empty'),
    toolbar: one('#node-count'),
    bodyText: (document.body.innerText || '').replace(/\\s+/g, ' '),
  };
})()
"""

AXIS = "W605 Discipline"


@pytest.mark.slow
@pytest.mark.regression
def test_a_first_axis_does_not_make_the_exam_read_as_empty(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange: #605's shape, a plain exam that then gets one axis -------
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W605 First Axis",
                                  exam_description="")
    root = db.create_subject_node(exam.exam_name, "W605 Cardiology", "System")
    db.create_subject_node(exam.exam_name, "W605 Arrhythmia", "Topic",
                           parent_id=root.id)
    db.create_subject_node(exam.exam_name, "W605 Nephrology", "System")
    db.create_dimension(exam_id=exam.id, name=AXIS, display_order=1,
                        is_required=True)
    db.conn.commit()
    # The premise, checked rather than assumed: three subjects that exist,
    # are active and sit in no axis, on an exam the flag now calls dimensioned.
    in_no_axis = db.conn.execute(
        "SELECT COUNT(*) FROM subject_nodes WHERE exam_context = ? "
        "AND status = 'active' AND dimension_id IS NULL",
        (exam.exam_name,)).fetchone()[0]
    assert in_no_axis == 3, in_no_axis
    assert db.exam_uses_dimensions(exam.id)

    # ---- Act ---------------------------------------------------------------
    open_tree_editor(wimi_page, exam.id)
    seen = wimi_page.eval_js(READ)

    # ---- Assert ------------------------------------------------------------
    for claim in ("No Subjects Yet", "Add Your First Subject",
                  "0 subjects across"):
        assert claim not in seen["bodyText"], (
            f"the page shows {claim!r} for an exam holding three subjects. "
            f"The dimensioned view counted one axis and stated the result "
            f"about the whole exam (#605): {seen['bodyText'][:400]!r}")

    # The empty state still appears, because the axis really is empty. It now
    # says which axis it means.
    assert seen["emptyShown"] is True, seen
    assert seen["title"] == f"No Subjects in {AXIS} Yet", seen["title"]
    assert seen["button"] == f"Add the First Subject to {AXIS}", seen["button"]
    assert seen["summary"] == f"0 subjects in {AXIS} across 0 roots.", (
        seen["summary"])
    assert seen["overviewEmpty"] == (
        f'No subjects in {AXIS} yet. Click "+ Add Root Subject" to get '
        f'started!'), seen["overviewEmpty"]
    assert seen["toolbar"] == f"0 subjects in {AXIS}", seen["toolbar"]


@pytest.mark.slow
@pytest.mark.regression
def test_a_genuinely_empty_plain_exam_still_says_so(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Positive control: the plain path's empty state is unchanged.

    It is also what ``docs/manual/02_the_first_hour.md`` tells a student they
    will see after the wizard.
    """
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W605 Empty", exam_description="")
    db.conn.commit()
    assert not db.exam_uses_dimensions(exam.id)

    open_tree_editor(wimi_page, exam.id)
    seen = wimi_page.eval_js(READ)

    assert seen["emptyShown"] is True, (
        f"a plain exam with no subjects shows no empty state: {seen!r}")
    assert seen["title"] == "No Subjects Yet", seen["title"]
    assert seen["button"] == "Add Your First Subject", seen["button"]
    assert seen["summary"] == "0 subjects across 0 roots.", seen["summary"]
    assert seen["overviewEmpty"] == (
        'No subjects yet. Click "+ Add Root Subject" to get started!'), (
        seen["overviewEmpty"])
    assert seen["toolbar"] == "0 subjects", seen["toolbar"]
