"""Regression: an exam with dimensions cannot be saved as Simple, and says so (#900).

A Simple save sends ``dimensions: null``, which ``save_exam_edit`` reads as
"leave the axes alone". So an exam with axes saved as Simple kept every axis
while the wizard reported "updated successfully" and its Review step had said
"Type: Simple" -- #240's success over nothing. The owner chose option C:
refuse, and explain.

No click reaches the type step in edit mode (the wizard opens on Exam Info
with Back disabled, and #444's control is offered only to an exam with no
axes), so the scenario has to use script for the one step a student cannot
take, and says so where it does. That is two layers, asserted separately:

* ``selectExamType('simple')`` is a no-op on such an exam, so the wizard never
  draws a state it would refuse;
* if Simple is reached anyway (``data.examType`` written directly -- the state
  master reached through ``selectExamType``), Save shows the refusal in the
  error modal, ``saveExamEdit`` is never called and the axes are untouched.

The positive control is an ordinary rename of the same exam, which must still
save, so the refusal cannot pass by refusing everything.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.first_axis import (
    axes_of, css, next_until_save, open_edit, poll, success_shown, visible)

EXAM = "Has Axes Exam"
REFUSAL = ("Nothing was saved. This exam has dimensions, and an exam with "
           "dimensions can't be switched back to Simple.")


@pytest.fixture
def with_axes(wimi_session: WimiTestSession, wimi_page: WimiPage):
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name=EXAM, exam_description="#900")
    axes = [db.create_dimension(exam_id=exam.id, name=n, display_order=i)
            for i, n in enumerate(("System", "Task"), start=1)]
    subject = db.create_subject_node(EXAM, "Cardio", "System", dimension_id=axes[0]).id
    db.conn.commit()
    open_edit(wimi_page, exam.id)
    return wimi_page, db, exam, subject


def _error_shown(page: WimiPage) -> bool:
    return bool(page.eval_js(
        "!document.getElementById('error-modal').classList.contains('hidden')"))


@pytest.mark.slow
@pytest.mark.regression
def test_saving_an_exam_with_axes_as_simple_is_refused(with_axes):
    page, db, exam, subject = with_axes
    assert not visible(page, '[data-testid="wizard-add-dimensions-offer"]'), (
        "#444's Add dimensions control must be absent on an exam with axes")

    # Script, because no click can reach the type step in edit mode.
    page.eval_js("examWizard.selectExamType('simple'); true")
    assert page.eval_js("examWizard.data.examType") == "multi_dimensional", (
        "selectExamType('simple') must do nothing on an exam with axes")

    # Reach Simple the way master could, then save through the real button.
    page.eval_js("examWizard.data.examType = 'simple'; examWizard.updateProgressBar(); true")
    next_until_save(page)
    mark = page.mark_bridge_calls()
    css(page, "#btn-create").click()

    assert poll(page, lambda: _error_shown(page), True) is True, (
        "saving an exam with axes as Simple showed no error")
    assert page.eval_js("document.getElementById('error-message').textContent") == REFUSAL
    assert not success_shown(page), "the wizard still reported a success"
    page.wait_for_timeout(300)
    calls = [c for c in page.get_bridge_calls(since_ts=mark)
             if c.get("method") == "saveExamEdit"]
    assert calls == [], "the refused save still reached saveExamEdit"
    assert axes_of(db, exam.id) == ["System", "Task"]
    row = db.fetchone("SELECT status FROM subject_nodes WHERE id = ?", (subject,))
    assert row["status"] == "active"


@pytest.mark.slow
@pytest.mark.regression
def test_a_plain_rename_of_the_same_exam_still_saves(with_axes):
    """The positive control: the refusal is about Simple, not about saving."""
    page, db, exam, _subject = with_axes
    css(page, '[data-testid="wizard-exam-name-input"]').fill("Has Axes Renamed")
    next_until_save(page)
    css(page, "#btn-create").click()
    assert poll(page, lambda: success_shown(page), True) is True, (
        "an ordinary rename of an exam with axes no longer saves")
    assert not _error_shown(page)
    row = db.fetchone("SELECT exam_name FROM exam_contexts WHERE id = ?", (exam.id,))
    assert row["exam_name"] == "Has Axes Renamed"
    assert axes_of(db, exam.id) == ["System", "Task"]
