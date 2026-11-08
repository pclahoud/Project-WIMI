"""#848 Wave 2a: saving a Quick note touches nothing on the entry.

A free note is not part of the entry, so its save must not call
``markDirty()``, must not write into ``EntryState.formData`` and must not add
a card. The cost of getting this wrong is not cosmetic: a dirty flag here
raises the ``beforeunload`` guard for nothing, and the entry form's whole
leave path (#267/#270) reads that flag as "there is unsaved work".

Seeded with one real note on the entry, so "the entry's own notes are
unchanged" has something to be unchanged: the card count, the row's origin
and the junction table are read before and after.

The positive control is the save itself -- the free note's row is asserted
present -- so a clean flag against a dialog that never saved proves nothing.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import (
    CARDS_READY, free_notes, junction_count, note_row, open_form, seed_entry,
    set_editor, wait_dialog_closed, wait_dialog_open,
)
from _helpers.w114_form_ready import poll

TEXT = "QNC a note that is not about this entry"
ENTRY_STATE = (
    "JSON.stringify({dirty: EntryState.isDirty, cards: EntryState.noteEditors.length,"
    " listed: (EntryState.formData.notesList || []).length})"
)


@pytest.mark.slow
@pytest.mark.regression
def test_saving_a_free_note_leaves_the_form_clean(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    import json

    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    world = seed_entry(db, name="QNC")
    own = db.add_entry_note(world["entry_id"], content_html="<p>QNC the entry's own note</p>")
    db.conn.commit()
    open_form(wimi_page, world["session_id"], world["entry_id"])
    assert poll(wimi_page, CARDS_READY, timeout_ms=20000), "the entry's note card never mounted"
    # Start from a clean form on purpose. Measured here: the initial load of
    # an entry that carries a note leaves `isDirty` TRUE, because
    # addNoteCard() calls markDirty() and the first-load path never marks
    # clean afterwards (navigateToEntry's path does). That is the loader's
    # business, not this dialog's; what this scenario measures is that the
    # Quick note save does not flip a clean flag, so the flag is reset
    # deliberately and said so, rather than the assertion weakened.
    wimi_page.eval_js("(() => { markClean(); return true; })()")
    assert poll(wimi_page, "EntryState.isDirty === false", timeout_ms=3000), (
        f"could not start from a clean form: {wimi_page.eval_js(ENTRY_STATE)}")
    before = json.loads(wimi_page.eval_js(ENTRY_STATE))
    assert before["cards"] == 1
    own_before = note_row(db, own.id)
    assert own_before["question_entry_id"] == world["entry_id"]
    # m009's junction records the originating attachment too, so this is 1.
    own_junction_before = junction_count(db, own.id)
    assert own_junction_before == 1

    # ---- Act: write and save a free note -------------------------------
    wimi_page.locator(testid="entry-form-quick-note-button").click()
    wait_dialog_open(wimi_page)
    set_editor(wimi_page, f"<p>{TEXT}</p>")
    wimi_page.locator(testid="quick-note-save-button").click()
    wait_dialog_closed(wimi_page)
    saved = []
    for _ in range(50):
        saved = free_notes(db)
        if saved:
            break
        wimi_page.wait_for_timeout(100)
    assert len(saved) == 1 and TEXT in saved[0]["content_html"], (
        f"the control is void: the free note was not saved: {saved!r}")
    wimi_page.wait_for_timeout(600)   # past the attach-candidate refresh debounce

    # ---- Assert: the entry is exactly as it was ------------------------
    after = json.loads(wimi_page.eval_js(ENTRY_STATE))
    assert after["dirty"] is False, (
        f"saving a Quick note marked the entry form dirty: {after}. The "
        f"beforeunload guard would now stop the student leaving for nothing.")
    assert after["cards"] == before["cards"] == 1, (
        f"saving a Quick note added or removed a note card: {before} -> {after}")
    assert after["listed"] == before["listed"], (
        f"saving a Quick note changed EntryState.formData.notesList: {before} -> {after}")
    assert note_row(db, own.id) == own_before, "the entry's own note changed"
    assert junction_count(db, own.id) == own_junction_before, "the entry's own attachment changed"
    assert junction_count(db, saved[0]["id"]) == 0, "the free note gained an attachment"
    assert [r["question_entry_id"] for r in db.fetchall(
        "SELECT question_entry_id FROM entry_notes WHERE question_entry_id IS NOT NULL")
    ] == [world["entry_id"]], "a second note reached the entry"
