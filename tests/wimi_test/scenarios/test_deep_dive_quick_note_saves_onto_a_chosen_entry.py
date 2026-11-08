"""#848 Wave 2b: On an entry -- pick the session, then the entry, then Save.

Owner's decision 5 (#848 comment 11594): on the deep dive the dialog offers
*On its own* or *On an entry*; the entry is chosen by session and then from
previews showing both answers, the reflection and the explanation; and Save
writes an ORDINARY entry note through the existing create path, so the row
has that entry as its origin and a junction row, exactly as a note card's.

Before an entry is chosen Save is disabled and the footer says why (#174).
The mutant that makes this branch call ``api.addNote`` writes a NULL origin
and fails the origin assertion below.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.deep_dive_quick_note import (
    notes_on, open_deep_dive, open_dialog, seed_entry, seed_exam, seed_session,
    text_of, wait_cards, wait_not_picking, wait_picking, wait_row_meta,
)
from _helpers.quick_note import junction_count, set_editor, wait_dialog_closed

TEXT = "DDB the trachea was the tell, not the saturation"
SAVE = "document.querySelector('[data-testid=\"quick-note-save-button\"]')"


@pytest.mark.slow
@pytest.mark.regression
def test_on_an_entry_saves_an_entry_note_onto_the_entry_chosen_by_session(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    world = seed_exam(db, "DDB")
    older = seed_session(db, world["exam_id"], "DDB pulm review", days_ago=6)
    newer = seed_session(db, world["exam_id"], "DDB cardiopulmonary week 3", days_ago=1, total=20)
    seed_entry(db, older, world["subject_id"], order=1, question_id="1999",
               user_answer="Observe", correct_answer="Aspirate")
    entry = seed_entry(db, newer, world["subject_id"], order=7, question_id="2041",
                       user_answer="Chest X-ray", correct_answer="Needle decompression",
                       reflection="I treated it as a radiology question",
                       explanation="Tension is treated on clinical grounds")
    open_deep_dive(wimi_page, world)
    assert notes_on(db) == [], "arrange is void: a note already exists"

    open_dialog(wimi_page)
    set_editor(wimi_page, f"<p>{TEXT}</p>")
    wimi_page.locator(testid="quick-note-where-entry").click()

    # ---- No entry yet: Save cannot save and says why -------------------
    assert wimi_page.eval_js(f"{SAVE}.disabled") is True, "Save must wait for an entry"
    reason = text_of(wimi_page, "quick-note-footer-text")
    assert reason and "Choose an entry first" in reason, reason
    assert wimi_page.eval_js(f"{SAVE}.getAttribute('aria-describedby')") == "quick-note-footer-text"
    assert text_of(wimi_page, "quick-note-choose-entry") == "Choose an entry"

    # ---- Choose: the session, then the entry from its preview ----------
    wimi_page.locator(testid="quick-note-choose-entry").click()
    wait_picking(wimi_page)
    assert len(wait_cards(wimi_page, lambda ids: len(ids) == 2)) == 2, "both candidates first"
    wimi_page.locator(testid=f"quick-note-picker-session-{newer}").click()
    assert wait_cards(wimi_page, lambda ids: ids == [entry]) == [entry], (
        "choosing the session should leave that session's entry only")
    card = f"quick-note-entry-card-{entry}"
    preview = {k: text_of(wimi_page, f"{card}-{k}") for k in
               ("id", "user-answer", "correct-answer", "reflection", "explanation")}
    assert preview == {
        "id": "Q 2041", "user-answer": "Chest X-ray", "correct-answer": "Needle decompression",
        "reflection": "I treated it as a radiology question",
        "explanation": "Tension is treated on clinical grounds"}, preview
    wimi_page.locator(testid=f"{card}-use").click()
    wait_not_picking(wimi_page)

    summary = text_of(wimi_page, "quick-note-entry-summary") or ""
    assert "Q 2041" in summary and "DDB cardiopulmonary week 3" in summary, summary
    assert "Entry 7 of 20" in summary and "You answered Chest X-ray" in summary, summary
    assert text_of(wimi_page, "quick-note-choose-entry") == "Change"
    assert text_of(wimi_page, "quick-note-footer-text") == (
        f"Saves onto entry #{entry}, tagged {world['subject_name']}")
    assert wimi_page.eval_js(f"{SAVE}.disabled") is False

    wimi_page.locator(testid="quick-note-save-button").click()
    wait_dialog_closed(wimi_page)

    # ---- An ordinary entry note on that entry --------------------------
    rows = []
    for _ in range(50):
        rows = notes_on(db)
        if rows:
            break
        wimi_page.wait_for_timeout(100)
    assert len(rows) == 1, f"expected one note, found {rows!r}"
    row = rows[0]
    assert row["question_entry_id"] == entry, (
        f"the note's origin is {row['question_entry_id']!r}; it was saved onto entry {entry}")
    assert junction_count(db, row["id"]) == 1, "an entry note carries its origin's attachment row"
    assert json.loads(row["linked_subject_ids"]) == [world["subject_id"]]
    assert TEXT in (row["content_html"] or "")

    meta = wait_row_meta(wimi_page, row["id"])
    assert meta and f"Entry #{entry}" in meta and "Opens the entry" in meta, meta
