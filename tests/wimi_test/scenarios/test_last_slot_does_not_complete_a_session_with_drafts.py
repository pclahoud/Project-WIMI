"""Save & Next on the last slot completes a session only when nothing is a draft (#714).

The session's last slot used to mark the whole session ``completed`` whatever
the earlier slots held, so a session with a draft in slot 1 read **Complete**
on its card with Logged 2/3, and Review opened entry 1 rather than the draft.
Under #12 a draft is a mistake still to finish.

Now Save & Next on the last slot, with a draft earlier, leaves the session in
progress, says how many entries are still to finish, and opens the first of
them. The control is the same press with every slot finished: the session is
completed and the completion dialog opens, so the first test's "not
completed" cannot pass against a press that did nothing.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import open_form
from _helpers.w114_form_ready import poll

FULL = dict(user_answer="a", correct_answer="b", reflection="<p>R</p>",
            explanation="<p>E</p>")
SAVE_NEXT_READY = (
    "(() => { const b = document.getElementById('btn-save-next');"
    " return !!b && !b.disabled; })()"
)
COMPLETE_MODAL_OPEN = (
    "(() => { const m = document.getElementById('complete-modal');"
    " return !!m && m.classList.contains('active'); })()"
)


def _seed(db, name: str, *, first_is_draft: bool, last_is_draft: bool = False) -> dict:
    exam = db.create_exam_context(exam_name=f"{name} Exam", exam_description="")
    subj = db.create_subject_node(exam_context=exam.exam_name, name=f"{name} Cardiology",
                                  level_type="System")
    session = db.create_review_session(
        exam_context_id=exam.id, session_name=f"{name} session",
        date_encountered=date.today(), total_questions=10, total_incorrect=3)
    first = dict(FULL, explanation="") if first_is_draft else FULL
    last = dict(FULL, explanation="") if last_is_draft else FULL
    ids = []
    for fields in (first, FULL, last):
        ids.append(db.create_question_entry(review_session_id=session.id,
                                            primary_subject_ids=[subj.id], **fields).id)
    db.conn.commit()
    return {"session_id": session.id, "entry_ids": ids}


def _status(db, session_id):
    return db.fetchone("SELECT session_status FROM review_sessions WHERE id = ?",
                       (session_id,))["session_status"]


@pytest.mark.slow
@pytest.mark.regression
def test_a_draft_earlier_keeps_the_session_open_and_opens_the_draft(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    world = _seed(db, "L714D", first_is_draft=True)
    open_form(wimi_page, world["session_id"], world["entry_ids"][2])
    assert wimi_page.eval_js("EntryState.currentEntryIndex") == 2, "arrange: on the last slot"
    assert poll(wimi_page, SAVE_NEXT_READY, timeout_ms=10000), "Save & Next never enabled"

    wimi_page.locator(testid="entry-form-save-next-button").click()

    assert poll(wimi_page, "EntryState.currentEntryIndex === 0", timeout_ms=10000), (
        "Save & Next on the last slot should open the first unfinished entry, slot 1; "
        f"on slot {wimi_page.eval_js('EntryState.currentEntryIndex') + 1}")
    assert wimi_page.eval_js(COMPLETE_MODAL_OPEN) is False, (
        "the completion dialog opened over a session with a draft")
    assert _status(db, world["session_id"]) != "completed", (
        "the session was marked completed with a draft in slot 1")
    toast = wimi_page.eval_js(
        "Array.from(document.querySelectorAll('.toast')).map(t => t.textContent).join(' ')")
    assert "1 entry is not finished yet" in toast, toast


@pytest.mark.slow
@pytest.mark.regression
def test_with_every_slot_finished_the_last_slot_completes_the_session(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # The session BECOMES complete on this visit, as a student finishing it
    # would see it: the last entry opens as a draft and its explanation is
    # written on the form. A session that was already complete when the form
    # opened does not show the dialog again (#879).
    db = wimi_session.user.db
    world = _seed(db, "L714C", first_is_draft=False, last_is_draft=True)
    open_form(wimi_page, world["session_id"], world["entry_ids"][2])
    assert _status(db, world["session_id"]) != "completed", "arrange: not yet complete"
    wimi_page.eval_js(
        "(() => { EntryState.explanationEditor.setContent('<p>E</p>');"
        " markDirty(); validateForm(); return true; })()")
    assert poll(wimi_page, SAVE_NEXT_READY, timeout_ms=10000), "Save & Next never enabled"

    wimi_page.locator(testid="entry-form-save-next-button").click()

    assert poll(wimi_page, COMPLETE_MODAL_OPEN, timeout_ms=10000), (
        "the completion dialog did not open on a fully finished session")
    for _ in range(50):
        if _status(db, world["session_id"]) == "completed":
            break
        wimi_page.wait_for_timeout(100)
    assert _status(db, world["session_id"]) == "completed"

    # #879: Review Entries keeps the student on the form. A real press, then
    # the address is watched for two seconds: the owner reported being sent
    # to the dashboard, and only Done may go there.
    wimi_page.locator(testid="entry-form-complete-review-button").click()
    assert poll(wimi_page, f"!({COMPLETE_MODAL_OPEN})", timeout_ms=5000), (
        "Review Entries did not close the dialog")
    for _ in range(20):
        assert "question_entry" in wimi_page.eval_js("window.location.pathname"), (
            "Review Entries left the entry form")
        wimi_page.wait_for_timeout(100)

    # And another Save & Next on the now-complete session moves nothing into
    # a second dialog: it was shown once on this visit.
    assert poll(wimi_page, SAVE_NEXT_READY, timeout_ms=10000)
    wimi_page.locator(testid="entry-form-save-next-button").click()
    wimi_page.wait_for_timeout(1500)
    assert wimi_page.eval_js(COMPLETE_MODAL_OPEN) is False, (
        "the dialog opened a second time on the same visit")
