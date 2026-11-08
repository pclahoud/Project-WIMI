"""Regression: editing an exam saves a new name and a cleared date (#718).

In edit mode the wizard's Exam Name field was editable and validated, and
then ``updateExam()`` left it out of the settings it sent. No layer below
could rename an exam either. A cleared Exam Date was sent as ``''``, which the
bridge turned into ``None``, which the database reads as "not supplied". So
both edits were dropped, and the success modal then said
``"<new name>" has been updated successfully.``, naming the change that had
not happened (#240's *reads-like-success*).

The rename also moves the subject tree. Subjects name their exam by TEXT in
``subject_nodes.exam_context``, so an exam renamed in ``exam_contexts`` alone
would reopen on an empty tree. That is why the scenario checks the tree, not
just the name.

The second test is the refusal. A name another exam holds must come back as
the error modal carrying a sentence, with nothing saved. A success modal over
an unsaved rename was the original bug.

The fields are set through their own ``input``/``change`` listeners, and
step 1 is committed with ``saveStepData()``, which is what Next calls. The
save then runs through ``createExam()``, which Save Changes calls in edit
mode. That is the same path as the wizard's last step, without clicking
through the steps in between.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

OLD, NEW = "Shelf Medicine", "NBME Medicine Shelf"

_READY = ("typeof examWizard !== 'undefined' && !!examWizard"
          " && examWizard.isEditMode && examWizard.data.examName.length > 0")


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


def _open_in_edit_mode(wimi_session: WimiTestSession, page: WimiPage):
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name=OLD, exam_description="#718")
    db.execute("UPDATE exam_contexts SET exam_date = '2026-12-15' WHERE id = ?",
               (exam.id,))
    db.create_subject_node(OLD, "Cardiology", "System")
    db.conn.commit()
    page.goto("exam-wizard", query={"edit": exam.id})
    assert _poll(page, _READY), "the wizard never initialised in edit mode"
    assert page.eval_js("examWizard.data.examDate") == "2026-12-15", (
        "premise: the edit form must load the stored date before it is cleared")
    return db, exam


def _type_name_and_clear_date(page: WimiPage, name: str) -> None:
    """Edit step 1's fields, then commit the step the way Next does.

    ``saveStepData()`` is where the date reaches ``examWizard.data``. Its
    ``change`` listener only marks the template modified, so a scenario that
    skipped the commit would be testing a path no student takes.
    """
    assert page.eval_js("examWizard.getCurrentStepType()") == "info", (
        "premise: edit mode opens on the Exam Information step")
    page.eval_js(f"""(() => {{
        const n = document.getElementById('exam-name');
        n.value = {json.dumps(name)}; n.dispatchEvent(new Event('input'));
        const d = document.getElementById('exam-date');
        d.value = ''; d.dispatchEvent(new Event('change'));
        examWizard.saveStepData();
    }})()""")


def _modal(page: WimiPage, which: str):
    return page.eval_js(
        f"(() => {{ const m = document.getElementById('{which}-modal');"
        f" return m && !m.classList.contains('hidden')"
        f" ? document.getElementById('{which}-message').textContent : null; }})()")


@pytest.mark.slow
@pytest.mark.regression
def test_editing_an_exam_saves_its_new_name_and_its_cleared_date(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db, exam = _open_in_edit_mode(wimi_session, wimi_page)

    _type_name_and_clear_date(wimi_page, NEW)
    wimi_page.eval_js("examWizard.createExam(); true")
    message = _poll(wimi_page, "(() => { const m = document.getElementById('success-modal');"
                               " return m && !m.classList.contains('hidden')"
                               " ? document.getElementById('success-message').textContent"
                               " : (document.getElementById('error-modal').classList"
                               ".contains('hidden') ? null : 'ERROR: ' +"
                               " document.getElementById('error-message').textContent); })()")
    assert message == f'"{NEW}" has been updated successfully.', (
        f"#718: the save did not report the rename it made: {message!r}")

    row = db.fetchone("SELECT exam_name, exam_date FROM exam_contexts WHERE id = ?",
                      (exam.id,))
    assert row["exam_name"] == NEW, (
        f"#718: the new name was dropped, and the exam is still {row['exam_name']!r}")
    assert row["exam_date"] is None, (
        f"#718: the cleared date came back as {row['exam_date']!r}")
    subjects = [r["name"] for r in db.fetchall(
        "SELECT name FROM subject_nodes WHERE exam_context = ?", (NEW,))]
    assert subjects == ["Cardiology"], (
        f"#718: the subject tree did not follow the rename (under {NEW!r}: "
        f"{subjects}). Subjects name their exam by text, so the renamed exam "
        f"would open empty.")


@pytest.mark.slow
@pytest.mark.regression
def test_a_name_another_exam_holds_is_an_error_and_saves_nothing(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db.create_exam_context(exam_name=NEW, exam_description="already here")
    db.conn.commit()
    db, exam = _open_in_edit_mode(wimi_session, wimi_page)

    _type_name_and_clear_date(wimi_page, NEW)
    wimi_page.eval_js("examWizard.createExam(); true")
    assert _poll(wimi_page, "(() => { const s = document.getElementById('success-modal');"
                            " const e = document.getElementById('error-modal');"
                            " return !s.classList.contains('hidden')"
                            " || !e.classList.contains('hidden'); })()"), (
        "the save never finished")

    assert _modal(wimi_page, "success") is None, (
        f"#718/#240: a refused rename was reported as a success: "
        f"{_modal(wimi_page, 'success')!r}")
    error = _modal(wimi_page, "error") or ""
    assert f'Another exam is already called "{NEW}"' in error, (
        f"the error modal must say why: {error!r}")
    row = db.fetchone("SELECT exam_name, exam_date FROM exam_contexts WHERE id = ?",
                      (exam.id,))
    assert (row["exam_name"], row["exam_date"]) == (OLD, "2026-12-15"), (
        f"a refused save changed the exam anyway: {dict(row)}")
