"""Regression: a failed part of an exam edit is reported, and nothing is saved (#874).

Edit mode used to save in three independent calls: the settings, then
``updateExamLength``, then a dimension sync of one call per axis. Only the
first could fail the save. The length and every axis caught their own errors
and logged them to the console, and ``createExam()`` then showed *"<name> has
been updated successfully."* So a student who renamed an exam and gave it an
impossible length saw a success modal, kept the rename and lost the length,
with nothing said (#240's *reads-like-success*).

Now ``updateExam()`` makes one ``saveExamEdit`` call, and the bridge writes
every part in one transaction. The first test forces a real failure in the
length part. It asserts the error modal names that part and says nothing was
saved, that no success modal appears, and that the rename typed in the same
edit is not in the database. The second test is the control: the same edit
with a valid length saves both. Without it, a wizard that refused every save
would pass the first test.

Step 1 is committed with ``saveStepData()``, which is what Next calls. The
length is set on ``examWizard.data`` directly, because the length step's own
inputs validate as the student types and would not let an impossible range
through. This test is about what the save does with a part that fails, not
about that step's validation.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

OLD, NEW = "Shelf Surgery", "NBME Surgery Shelf"

# Ready means loadExistingExam() has finished, not only started. It fills
# examName first and only moves to Exam Info (step 3) after awaiting the
# exam's axes, so a check on examName alone could read the step as 'type'
# (seen once in a combined run: assert 'type' == 'info').
_READY = ("typeof examWizard !== 'undefined' && !!examWizard"
          " && examWizard.isEditMode && examWizard.data.examName.length > 0"
          " && examWizard.currentStep === 3")
_SETTLED = ("(() => { const s = document.getElementById('success-modal');"
            " const e = document.getElementById('error-modal');"
            " return !s.classList.contains('hidden')"
            " || !e.classList.contains('hidden'); })()")


def _poll(page: WimiPage, expr: str, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = page.eval_js(expr)
        except Exception:
            last = None
        if last:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def _modal(page: WimiPage, which: str):
    return page.eval_js(
        f"(() => {{ const m = document.getElementById('{which}-modal');"
        f" return m && !m.classList.contains('hidden')"
        f" ? document.getElementById('{which}-message').textContent : null; }})()")


def _edit_and_save(wimi_session: WimiTestSession, page: WimiPage, length: dict):
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name=OLD, exam_description="#874")
    db.update_exam_length(exam.id, "unknown", None, None, None)
    db.conn.commit()
    page.goto("exam-wizard", query={"edit": exam.id})
    assert _poll(page, _READY), "the wizard never initialised in edit mode"
    assert page.eval_js("examWizard.getCurrentStepType()") == "info"

    page.eval_js(f"""(() => {{
        const n = document.getElementById('exam-name');
        n.value = {json.dumps(NEW)}; n.dispatchEvent(new Event('input'));
        examWizard.saveStepData();
        examWizard.data.examLength = {json.dumps(length)};
        examWizard.createExam();
    }})()""")
    assert _poll(page, _SETTLED), "the save never finished"
    return db, exam


@pytest.mark.slow
@pytest.mark.regression
def test_a_part_that_fails_is_reported_and_nothing_is_saved(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db, exam = _edit_and_save(wimi_session, wimi_page, {
        "kind": "range", "min": 300, "max": 100, "typical": 200, "note": ""})

    assert _modal(wimi_page, "success") is None, (
        f"#874: a failed length was reported as a success: "
        f"{_modal(wimi_page, 'success')!r}")
    error = _modal(wimi_page, "error") or ""
    assert error.startswith("Nothing was saved."), (
        f"#874: the error must say nothing was saved: {error!r}")
    assert "The exam's length could not be saved" in error, (
        f"#874: the error must name the part that failed: {error!r}")
    row = db.fetchone("SELECT exam_name, length_kind FROM exam_contexts WHERE id = ?",
                      (exam.id,))
    assert row["exam_name"] == OLD, (
        f"#874: the rename in the same edit was saved anyway ({row['exam_name']!r}),"
        f" so the edit was half-saved behind an error")


@pytest.mark.slow
@pytest.mark.regression
def test_the_same_edit_with_a_valid_length_saves_both(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The control. A wizard that refused every save would pass the test above."""
    db, exam = _edit_and_save(wimi_session, wimi_page, {
        "kind": "fixed", "min": 110, "max": 110, "typical": 110, "note": ""})

    message = _modal(wimi_page, "success")
    assert message == f'"{NEW}" has been updated successfully.', (
        f"the valid edit was not reported as saved: {message!r}, "
        f"error {_modal(wimi_page, 'error')!r}")
    row = db.fetchone("SELECT exam_name, length_kind, length_typical FROM exam_contexts"
                      " WHERE id = ?", (exam.id,))
    assert (row["exam_name"], row["length_kind"], row["length_typical"]) == (
        NEW, "fixed", 110)
