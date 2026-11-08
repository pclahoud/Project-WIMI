"""#848 Wave 2b: after an edit under Your notes, the New note tab is pre-tagged again.

Decision 5: a new note from the deep dive starts tagged with the page's
subject. ``startNew()`` restores that, but the New note TAB calls
``showCompose()``, which draws the chips from whatever the dialog holds --
and an edit's Cancel and its Save changes both used to leave that empty.
So Edit -> Cancel -> New note tab opened an untagged compose, and *On its
own* saved a note this subject's *Notes Tagged* list would never show.

Both ways out of an edit are driven here, Cancel and Save changes, each
followed by the New note tab, and the note is then saved so the row's
``linked_subject_ids`` is read rather than only the chip.

The controls: the dialog opens pre-tagged (so the chip's return is a
restore, not a page that always had it), and the edit view shows the edited
note's OWN tag and not the page's (so the edit really replaced the tags the
restore has to undo).
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.deep_dive_quick_note import open_deep_dive, open_dialog, seed_exam, text_of
from _helpers.quick_note import (
    free_notes, seed_free_note, set_editor, wait_dialog_closed, wait_editor_ready,
)
from _helpers.w114_form_ready import poll

SEEDED = "DDT seeded note, tagged with the other subject"
TEXT = "DDT a tension pneumothorax shifts the trachea away"

ROW_COUNT = "document.querySelectorAll('.qn-row').length"
IN_LIST = f"{ROW_COUNT} === 1 && QuickNote.editor() === null"


def _chip(page: WimiPage, subject_id: int) -> bool:
    return bool(page.eval_js(
        f"!!document.querySelector('[data-testid=\"quick-note-chip-{subject_id}\"]')"))


def _open_edit(page: WimiPage, note_id: int, world: dict) -> None:
    page.locator(testid="quick-note-tab-list").click()
    assert poll(page, f"{ROW_COUNT} === 1", timeout_ms=10000), "the Your notes list never rendered"
    page.locator(testid=f"quick-note-row-{note_id}-edit").click()
    wait_editor_ready(page)
    assert _chip(page, world["other_id"]) and not _chip(page, world["subject_id"]), (
        "control: the edit view should show the edited note's own tag, not the page's")


def _new_note_tab_is_pre_tagged(page: WimiPage, world: dict, after: str) -> None:
    page.locator(testid="quick-note-tab-new").click()
    wait_editor_ready(page)
    assert _chip(page, world["subject_id"]), (
        f"after {after} the New note tab opened with no {world['subject_name']!r} chip: "
        f"a note saved On its own from here would be missing from this subject's list")
    assert not _chip(page, world["other_id"]), (
        f"after {after} the New note tab carried the edited note's tag over")


@pytest.mark.slow
@pytest.mark.regression
def test_the_new_note_tab_after_an_edit_starts_tagged_with_the_page_subject(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    world = seed_exam(db, "DDT")
    note_id = seed_free_note(db, f"<p>{SEEDED}</p>", subject_ids=[world["other_id"]])
    open_deep_dive(wimi_page, world)
    open_dialog(wimi_page)
    wait_editor_ready(wimi_page)
    assert _chip(wimi_page, world["subject_id"]), "control: the dialog opens pre-tagged"

    # ---- Act 1: Edit -> Cancel -> New note tab -------------------------
    _open_edit(wimi_page, note_id, world)
    assert text_of(wimi_page, "quick-note-secondary-button") == "Cancel"
    wimi_page.locator(testid="quick-note-secondary-button").click()
    assert poll(wimi_page, IN_LIST, timeout_ms=10000), "Cancel did not return to the list"
    _new_note_tab_is_pre_tagged(wimi_page, world, "an edit's Cancel")

    # ---- Act 2: Edit -> Save changes -> New note tab -------------------
    _open_edit(wimi_page, note_id, world)
    assert text_of(wimi_page, "quick-note-save-button") == "Save changes"
    wimi_page.locator(testid="quick-note-save-button").click()
    assert poll(wimi_page, IN_LIST, timeout_ms=10000), "Save changes did not return to the list"
    _new_note_tab_is_pre_tagged(wimi_page, world, "an edit's Save changes")

    # ---- Act 3: save it On its own -------------------------------------
    set_editor(wimi_page, f"<p>{TEXT}</p>")
    wimi_page.locator(testid="quick-note-save-button").click()
    wait_dialog_closed(wimi_page)

    # ---- Assert: the new note is tagged here, the edited one untouched -
    rows: list[dict] = []
    for _ in range(50):
        rows = [r for r in free_notes(db) if TEXT in (r["content_html"] or "")]
        if rows:
            break
        wimi_page.wait_for_timeout(100)
    assert len(rows) == 1, f"expected one new note on no entry, found {free_notes(db)!r}"
    assert json.loads(rows[0]["linked_subject_ids"]) == [world["subject_id"]], rows[0]
    seeded = [r for r in free_notes(db) if r["id"] == note_id]
    assert seeded and json.loads(seeded[0]["linked_subject_ids"]) == [world["other_id"]], (
        f"the edits changed the seeded note's tags: {seeded!r}")
