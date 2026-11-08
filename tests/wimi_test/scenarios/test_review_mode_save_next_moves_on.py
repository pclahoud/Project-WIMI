"""Reviewing a completed session: Save & Next moves on, no dialog (#879).

Every Save & Next in a session that was already complete opened the Session
Complete dialog instead of moving to the next entry, because "every slot is
finished" is true on every slot. The student, stepping through with Save &
Next as the owner did, met the dialog on each press, and Done was the only
way out, which read as the dialog sending them home.

The owner chose option A: the dialog appears once, when a session becomes
complete during the visit, and never on a session that was complete as the
form opened. Here a completed session is opened the way its card's Review
button opens it, ``mode=view``, and stepped through with real hit-tested
presses. The page must stay on the entry form throughout.

The control is ``test_with_every_slot_finished_the_last_slot_completes_the_
session`` in ``test_last_slot_does_not_complete_a_session_with_drafts.py``:
a session that becomes complete on the visit still gets the dialog.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.w114_form_ready import poll, wait_for_form_ready

FULL = dict(user_answer="a", correct_answer="b", reflection="<p>R</p>",
            explanation="<p>E</p>")
SAVE_NEXT_READY = (
    "(() => { const b = document.getElementById('btn-save-next');"
    " return !!b && !b.disabled; })()"
)
MODAL_OPEN = (
    "(() => { const m = document.getElementById('complete-modal');"
    " return !!m && m.classList.contains('active'); })()"
)


@pytest.mark.slow
@pytest.mark.regression
def test_save_and_next_steps_through_a_reviewed_session_without_the_dialog(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="R879 Exam", exam_description="")
    subj = db.create_subject_node(exam_context=exam.exam_name, name="R879 Cardiology",
                                  level_type="System")
    session = db.create_review_session(
        exam_context_id=exam.id, session_name="R879 session",
        date_encountered=date.today(), total_questions=10, total_incorrect=3)
    for _ in range(3):
        db.create_question_entry(review_session_id=session.id,
                                 primary_subject_ids=[subj.id], **FULL)
    db.conn.commit()
    status = lambda: db.fetchone("SELECT session_status FROM review_sessions WHERE id = ?",
                                 (session.id,))["session_status"]
    assert status() == "completed", "arrange: the session is complete before the visit"

    wimi_page.goto("entry-form", query={"session_id": session.id, "mode": "view"})
    wait_for_form_ready(wimi_page)
    assert wimi_page.eval_js("EntryState.currentEntryIndex") == 0, "Review starts at entry 1"

    for expected_next in (1, 2):
        assert poll(wimi_page, SAVE_NEXT_READY, timeout_ms=10000), "Save & Next never enabled"
        wimi_page.locator(testid="entry-form-save-next-button").click()
        assert poll(wimi_page, f"EntryState.currentEntryIndex === {expected_next}",
                    timeout_ms=10000), (
            f"Save & Next did not move to entry {expected_next + 1}; on entry "
            f"{wimi_page.eval_js('EntryState.currentEntryIndex') + 1}")
        assert wimi_page.eval_js(MODAL_OPEN) is False, (
            "#879: the Session Complete dialog opened while reviewing a completed session")

    # The last slot saves and stays: no dialog, still on the form, still complete.
    assert poll(wimi_page, SAVE_NEXT_READY, timeout_ms=10000)
    wimi_page.locator(testid="entry-form-save-next-button").click()
    wimi_page.wait_for_timeout(1500)
    assert wimi_page.eval_js(MODAL_OPEN) is False, "the dialog opened on the last slot"
    assert wimi_page.eval_js("EntryState.currentEntryIndex") == 2
    assert "question_entry" in wimi_page.eval_js("window.location.pathname"), (
        "the page left the entry form")
    assert status() == "completed"
