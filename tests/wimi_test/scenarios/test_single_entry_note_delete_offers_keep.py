"""#848 decision 4 (owner, comment 11583): Detach on every single-entry note,
labelled *Keep as a note on its own*.

Before this, Delete on a saved note that only this entry held ran a bare
``confirm()`` and hard-deleted; the modal with a choice appeared only for a
note on several entries. Now a saved single-entry note opens the same modal
with the message *"This note is on this entry only."*, the two explanations
from the design, and three buttons: **Keep as a note on its own** (primary),
**Delete** (danger) and **Cancel**. Keep calls ``detachNoteFromEntry``, which
since Wave 0 removes the attachment AND frees the origin, so the row survives
with a NULL origin and no junction row -- reachable under *Your notes*. The
mutant that makes Keep call the hard delete fails the "row still present"
assertion.

The existing testids are kept and relabelled by textContent, so the
multi-entry scenarios keep passing against the same buttons.
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
    " keep: document.getElementById('note-delete-modal-detach').textContent.trim(),"
    " del: document.getElementById('note-delete-modal-delete-everywhere').textContent.trim(),"
    " cancel: document.getElementById('note-delete-modal-cancel').textContent.trim()})"
)
CARDS = (
    "JSON.stringify(EntryState.noteEditors.map(ne => ({tempId: ne.tempId, id: ne.id,"
    " count: ne.attachmentCount})))"
)


def _cards(page: WimiPage) -> list[dict]:
    return json.loads(page.eval_js(CARDS))


@pytest.mark.slow
@pytest.mark.regression
def test_delete_on_a_single_entry_note_offers_keep_as_a_note_on_its_own(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange: one entry, two saved notes only it holds -------------
    db = wimi_session.user.db
    world = seed_entry(db, name="QND")
    kept = db.add_entry_note(world["entry_id"], content_html="<p>QND keep me</p>",
                             linked_subject_ids=[world["subject_id"]])
    gone = db.add_entry_note(world["entry_id"], content_html="<p>QND delete me</p>")
    db.conn.commit()
    open_form(wimi_page, world["session_id"], world["entry_id"])
    assert poll(wimi_page, CARDS_READY, timeout_ms=20000), "the note cards never mounted"
    cards = {c["id"]: c for c in _cards(wimi_page)}
    assert set(cards) == {kept.id, gone.id} and all(c["count"] == 1 for c in cards.values()), (
        f"arrange is void: {cards!r}")
    assert wimi_page.eval_js(MODAL_OPEN) is False

    # ---- Act 1: Delete on the first card, read the three-way choice ----
    wimi_page.locator(testid=f"entry-form-note-card-{cards[kept.id]['tempId']}-delete-button").click()
    assert poll(wimi_page, MODAL_OPEN, timeout_ms=5000), (
        "Delete on a saved single-entry note did not open the modal (the old "
        "confirm() path?)")
    text = json.loads(wimi_page.eval_js(MODAL_TEXT))
    assert text["message"] == "This note is on this entry only.", text
    assert "Keep as a note on its own: takes it off this entry and keeps it, with its subjects, under Your notes in Quick note." in text["detail"], text
    assert "Delete: removes it for good. There is no undo." in text["detail"], text
    assert (text["keep"], text["del"], text["cancel"]) == (
        "Keep as a note on its own", "Delete", "Cancel"), text

    # ---- Act 2: Keep -----------------------------------------------------
    wimi_page.locator(testid="note-delete-modal-detach").click()
    assert poll(wimi_page, f"EntryState.noteEditors.length === 1", timeout_ms=5000), (
        "Keep did not remove the card from the entry")
    row = None
    for _ in range(50):
        row = note_row(db, kept.id)
        if row and row["question_entry_id"] is None:
            break
        wimi_page.wait_for_timeout(100)

    # ---- Assert: freed, not deleted ------------------------------------
    assert row is not None, "Keep as a note on its own DELETED the row"
    assert row["question_entry_id"] is None, f"the origin was not cleared: {row!r}"
    assert junction_count(db, kept.id) == 0, "the attachment row survived Keep"
    assert json.loads(row["linked_subject_ids"]) == [world["subject_id"]], (
        "Keep lost the note's subjects")
    assert wimi_page.eval_js(MODAL_OPEN) is False

    # ---- Act 3: Delete on the other card removes its row ---------------
    remaining = _cards(wimi_page)
    assert [c["id"] for c in remaining] == [gone.id]
    wimi_page.locator(testid=f"entry-form-note-card-{remaining[0]['tempId']}-delete-button").click()
    assert poll(wimi_page, MODAL_OPEN, timeout_ms=5000)
    assert json.loads(wimi_page.eval_js(MODAL_TEXT))["del"] == "Delete"
    wimi_page.locator(testid="note-delete-modal-delete-everywhere").click()
    assert poll(wimi_page, "EntryState.noteEditors.length === 0", timeout_ms=5000)
    for _ in range(50):
        if note_row(db, gone.id) is None:
            break
        wimi_page.wait_for_timeout(100)
    assert note_row(db, gone.id) is None, "Delete left the row in place"
    assert note_row(db, kept.id) is not None, "Delete on the second note took the kept one too"
