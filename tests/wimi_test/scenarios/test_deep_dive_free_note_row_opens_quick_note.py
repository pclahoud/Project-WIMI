"""#848 Wave 2b: a note on its own, listed on the deep dive, opens for editing.

Wave 0 drew a free note's row as text, because it had nowhere to go (#464:
a row announced as a button has to go somewhere). Its destination is now the
Quick note dialog, on that note, with its content in the editor -- the same
state *Your notes*' Edit sets -- and Save writes the change and closes.

The entry note's row beside it is the control twice over: it still opens its
entry, which proves the two rows are told apart by their data rather than
both doing one thing; and each row's meta line names what it opens. The
mutant that makes the free row navigate again fails at the dialog.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.deep_dive_quick_note import (
    open_deep_dive, seed_entry, seed_exam, seed_session, text_of, wait_row_meta,
)
from _helpers.quick_note import (
    editor_html, note_row, seed_free_note, set_editor, wait_dialog_closed, wait_dialog_open,
)
from _helpers.w114_form_ready import poll

FREE = "DDE open pneumothorax: a three-sided dressing"
EDITED = "DDE open pneumothorax: three-sided dressing, then a tube away from the wound"
ON_ENTRY = "DDE needle before film"


@pytest.mark.slow
@pytest.mark.regression
def test_a_free_notes_row_opens_it_in_quick_note_and_an_entry_notes_row_opens_the_entry(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    world = seed_exam(db, "DDE")
    session = seed_session(db, world["exam_id"], "DDE block", days_ago=1)
    entry = seed_entry(db, session, world["subject_id"], order=1, question_id="5001",
                       user_answer="A", correct_answer="B")
    entry_note = db.add_entry_note(entry, content_html=f"<p>{ON_ENTRY}</p>",
                                   linked_subject_ids=[world["subject_id"]]).id
    free = seed_free_note(db, f"<p>{FREE}</p>", subject_ids=[world["subject_id"]])

    open_deep_dive(wimi_page, world)
    assert "Note on its own" in (wait_row_meta(wimi_page, free) or "")
    assert "Opens in Quick note" in (text_of(wimi_page, f"deep-dive-note-meta-{free}") or "")
    assert "Opens the entry" in (wait_row_meta(wimi_page, entry_note) or "")
    roles = json.loads(wimi_page.eval_js(
        "JSON.stringify([%d, %d].map(id => { const r = document.querySelector("
        "`[data-testid=\"deep-dive-subject-note-${id}\"]`);"
        " return [r.getAttribute('role'), r.getAttribute('tabindex')]; }))" % (free, entry_note)))
    assert roles == [["button", "0"], ["button", "0"]], f"both rows are buttons: {roles!r}"

    # ---- The free row opens the dialog on that note --------------------
    wimi_page.locator(testid=f"deep-dive-subject-note-{free}").click()
    wait_dialog_open(wimi_page)
    assert "subject_deep_dive" in wimi_page.eval_js("window.location.pathname"), (
        "pressing a free note's row must not navigate")
    assert FREE in editor_html(wimi_page), "the dialog must open with the note's content"
    assert text_of(wimi_page, "quick-note-footer-text") == "Editing a note on its own"
    assert wimi_page.eval_js(
        "!document.querySelector('[data-testid=\"quick-note-where\"]').checkVisibility()"), (
        "editing a note on its own offers no where-it-lives choice")
    assert text_of(wimi_page, f"quick-note-chip-{world['subject_id']}") == world["subject_name"]

    set_editor(wimi_page, f"<p>{EDITED}</p>")
    wimi_page.locator(testid="quick-note-save-button").click()
    wait_dialog_closed(wimi_page)
    row = None
    for _ in range(50):
        row = note_row(db, free)
        if row and EDITED in (row["content_html"] or ""):
            break
        wimi_page.wait_for_timeout(100)
    assert row and EDITED in (row["content_html"] or ""), f"the edit was not saved: {row!r}"
    assert row["question_entry_id"] is None, "editing keeps it a note on its own"
    assert poll(wimi_page,
                "(document.querySelector('[data-testid=\"deep-dive-subject-note-%d\"]')"
                " || {textContent: ''}).textContent.includes(%s)" % (free, json.dumps(EDITED)),
                timeout_ms=10000), "the list should show the edited text"

    # ---- Control: the entry note's row still opens its entry -----------
    wimi_page.locator(testid=f"deep-dive-subject-note-{entry_note}").click()
    assert poll(wimi_page, "window.location.pathname.includes('entry_detail')",
                timeout_ms=15000), "the entry note's row must still open the entry"
    assert f"id={entry}" in wimi_page.eval_js("window.location.search")
