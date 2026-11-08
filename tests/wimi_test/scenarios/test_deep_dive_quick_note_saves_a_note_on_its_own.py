"""#848 Wave 2b: the deep dive's Quick note saves a note on its own, tagged here.

From a subject's deep dive the student presses **Quick note**; the dialog
opens already tagged with this page's subject (the mockup's footer:
"tagged Pneumothorax"), offers *On its own* / *On an entry*, and with *On its
own* Save writes a free note: NULL origin, no junction row, the subject in
``linked_subject_ids``. The page then re-reads its payload and lists the note
under *Notes Tagged with This Subject* with the meta line *Note on its own*.

The positive control is the notes list's empty state before the save: the
row afterwards is the save being found, not a page that always had one.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.deep_dive_quick_note import (
    open_deep_dive, open_dialog, seed_exam, text_of, wait_row_meta,
)
from _helpers.quick_note import (
    free_notes, junction_count, set_editor, wait_dialog_closed, wait_editor_ready,
)
from _helpers.w114_form_ready import poll

TEXT = "DDA needle before film: decompress on clinical grounds"


@pytest.mark.slow
@pytest.mark.regression
def test_the_deep_dive_quick_note_saves_a_note_on_its_own_tagged_with_the_subject(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    world = seed_exam(db, "DDA")
    open_deep_dive(wimi_page, world)
    assert free_notes(db) == [], "arrange is void: a free note already exists"
    empty = text_of(wimi_page, "deep-dive-empty-state-subject-notes")
    assert empty and "tagged" in empty.lower(), (
        f"control: the notes list should start empty, read {empty!r}")

    # ---- Act: open from the header button -----------------------------
    open_dialog(wimi_page)
    wait_editor_ready(wimi_page)
    chip = f"quick-note-chip-{world['subject_id']}"
    assert text_of(wimi_page, chip) == world["subject_name"], (
        "a new note opened from the deep dive must start tagged with the page's subject")
    where = json.loads(wimi_page.eval_js(
        "(() => { const r = document.querySelector('[data-testid=\"quick-note-where\"]');"
        " const g = r && r.querySelector('[role=\"group\"]');"
        " const own = document.querySelector('[data-testid=\"quick-note-where-own\"]');"
        " const ent = document.querySelector('[data-testid=\"quick-note-where-entry\"]');"
        " const name = g && document.getElementById(g.getAttribute('aria-labelledby'));"
        " return JSON.stringify({shown: !!r && r.checkVisibility(),"
        "  label: name ? name.textContent.trim() : null,"
        "  own: own && own.getAttribute('aria-pressed'),"
        "  entry: ent && ent.getAttribute('aria-pressed')}); })()"))
    assert where == {"shown": True, "label": "Where does this note live?",
                     "own": "true", "entry": "false"}, where
    assert text_of(wimi_page, "quick-note-footer-text") == "Not on any entry"

    set_editor(wimi_page, f"<p>{TEXT}</p>")
    wimi_page.locator(testid="quick-note-save-button").click()
    wait_dialog_closed(wimi_page)

    # ---- Assert: one free row, tagged with this subject ----------------
    rows = []
    for _ in range(50):
        rows = free_notes(db)
        if rows:
            break
        wimi_page.wait_for_timeout(100)
    assert len(rows) == 1, f"expected one note on no entry, found {rows!r}"
    row = rows[0]
    assert TEXT in (row["content_html"] or "")
    assert row["question_entry_id"] is None, "a note on its own has a NULL origin"
    assert junction_count(db, row["id"]) == 0, "a note on its own has no attachment row"
    assert json.loads(row["linked_subject_ids"]) == [world["subject_id"]]

    # ---- Assert: the page lists it, labelled for what it opens ---------
    meta = wait_row_meta(wimi_page, row["id"])
    assert meta and "Note on its own" in meta and "Opens in Quick note" in meta, (
        f"the new note's row should say it is a note on its own: {meta!r}")
    assert TEXT in (text_of(wimi_page, f"deep-dive-subject-note-{row['id']}") or "")
    assert poll(wimi_page,
                "(document.querySelector('[data-testid=\"deep-dive-notice\"]').textContent"
                " || '').includes('Saved as a note on its own')", timeout_ms=5000), (
        "the page should say the note was saved")
