"""Regression: removing a dimension in the wizard asks first, and says what goes (#486).

The wizard's **✕** on a dimension card removed the axis from its local list, and
`saveDimensions` then archived it through `api.deleteDimension` →
`archive_dimension` → `delete_subject_subtree` per root: #210's whole cascade,
every subject tree in that axis, in one transaction.

**The student was told nothing.** The handler's only `confirm()` was
unreachable — `if (this.data.dimensions.length > 1 || confirm(...))`
short-circuits on the `||` whenever there is more than one axis, and the button
is rendered `disabled` when there is one or none, so the branch that asks could
not run. No subject count either: `getDimensionDeletePreview` is a registered
slot whose own docstring says *"Call this before `deleteDimension` and show the
student the numbers"*, and it had no JS wrapper and no caller.

Compare the two paths that get this right. Deleting a **subject** draws a
preview computed by the same code that performs the delete and closes with
*"Deleted subjects are archived, not erased."* A whole-exam **import** that
drops an axis makes it the loudest thing in the panel, with the subject count
and where to undo it. The wizard was the one route to the same outcome with no
information at all, reached while editing a dimension's name.

What this file asserts, and the three things that make it non-vacuous:

* an axis that exists in the database is **not removed until confirmed**, and
  "Keep it" leaves it in place;
* the message names the axis, its subject count and where to undo it;
* **an axis added in this wizard session is removed with no dialog**, because
  it is in no database and there is nothing to archive. Without that case the
  fix could have been "always ask", which is the inverse lie and would have
  passed an assertion about the dialog appearing.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

EXAM = "Axis Confirm Exam"

_READY = (
    "typeof examWizard !== 'undefined' && !!examWizard "
    "&& Array.isArray(examWizard.data && examWizard.data.dimensions)"
)


def _poll(page: WimiPage, read, want, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if last == want:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


@pytest.fixture
def wizard(wimi_session: WimiTestSession, wimi_page: WimiPage):
    """A three-axis exam with subjects and an entry, opened in the wizard's edit mode."""
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name=EXAM, exam_description="#486")

    # create_dimension returns the id itself, not a row object.
    axes = [db.create_dimension(exam_id=exam.id, name=name, display_order=i)
            for i, name in enumerate(("System", "Task", "Discipline"), start=1)]

    # Two subjects in the axis under test, one carrying an entry, so the
    # preview has non-zero counts to report.
    root = db.create_subject_node(EXAM, "Cardiovascular", "System",
                                  dimension_id=axes[0])
    db.create_subject_node(EXAM, "Hypertension", "Topic",
                           parent_id=root.id, dimension_id=axes[0])
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name="s")
    db.create_question_entry(session.id, "a", "b", primary_subject_ids=[root.id])
    db.conn.commit()

    wimi_page.goto("exam-wizard", query={"edit": exam.id})
    assert _poll(wimi_page, lambda: wimi_page.eval_js(_READY), True) is True, (
        "the wizard never initialised in edit mode")
    # The dimensions step has to be loaded before its cards exist.
    _poll(wimi_page,
          lambda: wimi_page.eval_js("examWizard.data.dimensions.length"), 3)
    return wimi_page, db, exam


def _names(page: WimiPage):
    return page.eval_js("examWizard.data.dimensions.map(d => d.name)")


def _dialog_open(page: WimiPage) -> bool:
    return page.eval_js(
        "!document.getElementById('remove-dimension-modal')"
        ".classList.contains('hidden')")


@pytest.mark.slow
@pytest.mark.regression
def test_an_existing_axis_is_not_removed_until_it_is_confirmed(wizard):
    """The headline. On master the axis was gone the moment ✕ was pressed."""
    page, _db, _exam = wizard
    before = _names(page)
    assert "System" in before, before

    page.eval_js("examWizard.deleteDimension(0); true")
    assert _poll(page, lambda: _dialog_open(page), True) is True, (
        "pressing the remove button asked nothing")

    # Still there while the question is open.
    assert _names(page) == before, (
        "the axis was removed before the student answered")

    page.eval_js(
        "document.getElementById('btn-cancel-remove-dimension').click(); true")
    assert _poll(page, lambda: _dialog_open(page), False) is False
    assert _names(page) == before, '"Keep it" removed the axis anyway'


@pytest.mark.slow
@pytest.mark.regression
def test_confirming_removes_it_and_the_message_said_what_would_go(wizard):
    page, _db, _exam = wizard

    page.eval_js("examWizard.deleteDimension(0); true")
    _poll(page, lambda: _dialog_open(page), True)
    message = page.eval_js(
        "document.getElementById('remove-dimension-message').textContent")

    assert "System" in message, message
    assert "2 subjects" in message, f"the subject count is missing: {message!r}"
    assert "1 entry" in message, f"the entry count is missing: {message!r}"
    assert "Archived subjects" in message, (
        f"nothing told the student it is reversible: {message!r}")
    assert "until you save" in message, (
        f"the message must say when it takes effect: {message!r}")

    page.eval_js(
        "document.getElementById('btn-confirm-remove-dimension').click(); true")
    assert _poll(page, lambda: _dialog_open(page), False) is False
    assert "System" not in _names(page), "confirming did not remove it"


@pytest.mark.slow
@pytest.mark.regression
def test_an_axis_added_in_this_session_is_removed_without_asking(wizard):
    """The control, and the reason this file is not just "always ask".

    A dimension with no `dbId` exists only in the wizard's local list. There is
    nothing in any database to archive, so a confirmation naming subjects and
    offering an undo would be describing an event that cannot happen.
    """
    page, _db, _exam = wizard

    page.eval_js("""
        examWizard.data.dimensions.push(
            {name: 'Setting', description: '', displayOrder: 4,
             isRequired: false, allowMultiple: false});
        examWizard.renderDimensions();
        true
    """)
    assert "Setting" in _names(page)

    page.eval_js("examWizard.deleteDimension(3); true")
    assert _poll(page, lambda: "Setting" not in _names(page), True) is True, (
        "a never-saved axis was not removed")
    assert _dialog_open(page) is False, (
        "an axis that is in no database must not raise an archive warning")
