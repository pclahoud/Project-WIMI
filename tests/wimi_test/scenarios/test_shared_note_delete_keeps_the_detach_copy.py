"""Delete on a note shared by two entries keeps the multi-entry choice (#848 Wave 2a).

Wave 2a relabels one modal for two cases by ``attachmentCount <= 1``. The
single-entry case is pinned by ``test_single_entry_note_delete_offers_keep.py``;
this is the other branch, which nothing read until PR #864's round-3 review:
the message names the count, the buttons read *Detach from this entry* and
*Delete everywhere*, and Detach takes the note off this entry while it stays
on the other one. Pressed on the origin, Detach also clears the origin
(Wave 0), so the row survives with a NULL origin and one junction row.

The control is the arrange's own assertion that the card reports two
attachments: a page that never mounted the cards, or counted 1, fails there.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import CARDS_READY, junction_count, note_row, open_form, seed_entry
from _helpers.w114_form_ready import poll

MODAL_OPEN = (
    "(() => { const m = document.getElementById('note-delete-modal');"
    " return !!m && m.classList.contains('active'); })()"
)
MODAL_TEXT = (
    "JSON.stringify({message: document.getElementById('note-delete-modal-message').textContent.trim(),"
    " detail: document.getElementById('note-delete-modal-detail').textContent,"
    " detach: document.getElementById('note-delete-modal-detach').textContent.trim(),"
    " del: document.getElementById('note-delete-modal-delete-everywhere').textContent.trim()})"
)
CARDS = (
    "JSON.stringify(EntryState.noteEditors.map(ne => ({tempId: ne.tempId, id: ne.id,"
    " count: ne.attachmentCount})))"
)


@pytest.mark.slow
@pytest.mark.regression
def test_delete_on_a_shared_note_offers_detach_and_detach_keeps_it_on_the_other_entry(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    world = seed_entry(db, name="QNS")
    other = db.create_question_entry(
        review_session_id=world["session_id"], user_answer="c", correct_answer="d",
        primary_subject_ids=[world["subject_id"]])
    shared = db.add_entry_note(world["entry_id"], content_html="<p>QNS shared</p>",
                               linked_subject_ids=[world["subject_id"]])
    db.attach_existing_note_to_entry(shared.id, other.id)
    db.conn.commit()

    open_form(wimi_page, world["session_id"], world["entry_id"])
    assert poll(wimi_page, CARDS_READY, timeout_ms=20000), "the note cards never mounted"
    cards = json.loads(wimi_page.eval_js(CARDS))
    assert [(c["id"], c["count"]) for c in cards] == [(shared.id, 2)], (
        f"arrange is void, the card must report two attachments: {cards!r}")

    wimi_page.locator(testid=f"entry-form-note-card-{cards[0]['tempId']}-delete-button").click()
    assert poll(wimi_page, MODAL_OPEN, timeout_ms=5000), "Delete did not open the modal"
    text = json.loads(wimi_page.eval_js(MODAL_TEXT))
    assert text["message"] == (
        "This note is attached to 2 entries. Choose how to remove it from this entry."), text
    assert "still appears on the other 1 entry" in text["detail"], text
    assert "removes the note from all 2 entries" in text["detail"], text
    assert (text["detach"], text["del"]) == ("Detach from this entry", "Delete everywhere"), (
        f"the multi-entry case took the single-entry labels: {text!r}")

    wimi_page.locator(testid="note-delete-modal-detach").click()
    assert poll(wimi_page, "EntryState.noteEditors.length === 0", timeout_ms=5000), (
        "Detach did not remove the card from this entry")
    row = None
    for _ in range(50):
        row = note_row(db, shared.id)
        if row and row["question_entry_id"] is None and junction_count(db, shared.id) == 1:
            break
        wimi_page.wait_for_timeout(100)
    assert row is not None, "Detach DELETED a note another entry still holds"
    assert junction_count(db, shared.id) == 1, "the other entry's attachment went too"
    assert db.fetchone(
        "SELECT question_entry_id FROM entry_note_attachments WHERE note_id = ?",
        (shared.id,))["question_entry_id"] == other.id
    assert row["question_entry_id"] is None, (
        f"Detach on the origin must clear it (Wave 0): {row!r}")
