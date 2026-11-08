"""#848 Wave 2a: editing a note under *Your notes* can change its subject tags.

Decision 3 made a free note's tag optional and paid for it with the Your notes
list; the tag is still what makes the note reachable anywhere else -- the
``+ Add existing`` picker and the deep dive both read ``linked_subject_ids``.
So Edit on a Your notes row has to be able to add one. ``save()`` writes the
text through ``updateEntryNote`` and, only when the tags changed, the tags
through ``updateNoteLinkedSubjects``. The one scenario that edited a Your
notes row changed only the text (PR #864 round 2), so the tag write ran with
identical ids and was indistinguishable from not running: inverting the gate,
deleting the call or sending the ids in the wrong shape all passed. A student
would read *Note updated* and the row would still hold NULL tags.

Two edits of one untagged free note, in order:

1. **Subjects… -> tick -> Save changes**, text untouched: the row's
   ``linked_subject_ids`` is the subject, the list row's chips name it, and
   ``+ Add existing`` on the open entry (tagged with that subject) counts it.
2. **Text only -> Save changes**, tags left as they are: the text is written
   and the tags survive -- the gate's other side, on a note that now HAS tags.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import (
    editor_html, note_row, open_form, seed_entry, seed_free_note, set_editor,
    wait_dialog_open,
)
from _helpers.w114_form_ready import poll

TEXT = "QNT a wide QRS with peaked T waves is hyperkalemia"
EDITED = "QNT a wide QRS with peaked T waves is hyperkalemia until proven otherwise"

ROW_COUNT = "document.querySelectorAll('.qn-row').length"
CHOOSER_OPEN = (
    "!!document.querySelector('#note-subject-modal.active input[type=\"checkbox\"]')"
)
ADD_EXISTING_COUNT = (
    "(() => { const c = document.getElementById('btn-attach-existing-notes-count');"
    " return c && !c.hidden ? c.textContent.trim() : ''; })()"
)


def _row_chips(page: WimiPage, note_id: int) -> list[str]:
    return json.loads(page.eval_js(
        f"JSON.stringify(Array.from(document.querySelectorAll("
        f"'[data-testid=\"quick-note-row-{note_id}\"] .qn-row-chips .qn-chip'))"
        ".map(c => c.textContent.trim()))"))


def _row_tags(db, note_id: int) -> list[int] | None:
    raw = note_row(db, note_id)["linked_subject_ids"]
    return json.loads(raw) if raw else None


def _open_edit(page: WimiPage, note_id: int) -> None:
    page.locator(testid=f"quick-note-row-{note_id}-edit").click()
    assert poll(page, "QuickNote.editor() !== null", timeout_ms=5000)
    assert poll(page, "(() => { const ed = QuickNote.editor(); return !!ed && ed.isInitialized === true; })()",
                timeout_ms=20000), "the edit view's editor never mounted"


def _save_changes(page: WimiPage) -> None:
    assert page.eval_js(
        "document.querySelector('[data-testid=\"quick-note-save-button\"]').textContent.trim()"
    ) == "Save changes"
    page.locator(testid="quick-note-save-button").click()
    assert poll(page, f"{ROW_COUNT} === 1 && QuickNote.editor() === null", timeout_ms=10000), (
        "Save changes did not return to the list")


@pytest.mark.slow
@pytest.mark.regression
def test_an_edit_under_your_notes_writes_the_new_tags_and_a_text_edit_keeps_them(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange: one untagged free note, the form open on a tagged entry
    db = wimi_session.user.db
    world = seed_entry(db, name="QNT")
    sid = world["subject_id"]
    note_id = seed_free_note(db, f"<p>{TEXT}</p>")
    assert _row_tags(db, note_id) is None, "arrange is void: the note is already tagged"
    open_form(wimi_page, world["session_id"], world["entry_id"])
    assert wimi_page.eval_js(ADD_EXISTING_COUNT) == "", (
        "+ Add existing already counts something before the tag exists")

    wimi_page.locator(testid="entry-form-quick-note-button").click()
    wait_dialog_open(wimi_page)
    wimi_page.locator(testid="quick-note-tab-list").click()
    assert poll(wimi_page, f"{ROW_COUNT} === 1", timeout_ms=10000), "the Your notes list never rendered"
    assert _row_chips(wimi_page, note_id) == ["General"], (
        f"the control is void: the untagged row does not read General: {_row_chips(wimi_page, note_id)!r}")

    # ---- Act 1: Edit -> Subjects... -> tick -> Save changes ------------
    _open_edit(wimi_page, note_id)
    assert wimi_page.eval_js(
        "document.querySelector('[data-testid=\"quick-note-chip-general\"]') !== null"), (
        "the edit view did not start from the note's own (empty) tags")
    wimi_page.locator(testid="quick-note-subjects-button").click()
    assert poll(wimi_page, CHOOSER_OPEN, timeout_ms=5000), "the subject chooser never opened over the dialog"
    box = f'#note-subject-modal input[type="checkbox"][value="{sid}"]'
    wimi_page.locator(css=box).click()
    assert poll(wimi_page, f"document.querySelector('{box}').checked", timeout_ms=3000)
    wimi_page.locator(testid="note-subject-modal-save").click()
    chip = f"quick-note-chip-{sid}"
    assert poll(wimi_page, f"!!document.querySelector('[data-testid=\"{chip}\"]')", timeout_ms=5000), (
        "the chosen subject never appeared as a chip in the edit view")
    assert TEXT in editor_html(wimi_page), "the text was lost while choosing a subject"
    _save_changes(wimi_page)

    # ---- Assert 1: the row, the list and the picker all carry the tag --
    tags = None
    for _ in range(50):
        tags = _row_tags(db, note_id)
        if tags:
            break
        wimi_page.wait_for_timeout(100)
    assert tags == [sid], (
        f"Save changes reported success and the row's linked_subject_ids is {tags!r}: "
        f"updateNoteLinkedSubjects never ran, so the note is offered nowhere")
    stored = note_row(db, note_id)
    assert TEXT in (stored["content_html"] or "") and EDITED not in (stored["content_html"] or ""), (
        f"the first edit changed the text, which it did not touch: {stored!r}")
    assert stored["question_entry_id"] is None, "editing re-homed the note onto an entry"
    assert _row_chips(wimi_page, note_id) == [world["subject_name"]], (
        f"the list row does not show the new tag: {_row_chips(wimi_page, note_id)!r}")
    assert poll(wimi_page, f"({ADD_EXISTING_COUNT}) === '(1)'", timeout_ms=10000), (
        f"+ Add existing on an entry tagged {world['subject_name']} does not offer the note "
        f"after it was tagged: {wimi_page.eval_js(ADD_EXISTING_COUNT)!r}")

    # ---- Act 2: Edit again, change only the text -----------------------
    _open_edit(wimi_page, note_id)
    assert wimi_page.eval_js(f"!!document.querySelector('[data-testid=\"{chip}\"]')"), (
        "the second edit did not start from the note's saved tag")
    set_editor(wimi_page, f"<p>{EDITED}</p>")
    _save_changes(wimi_page)

    # ---- Assert 2: the text moved and the tag stayed -------------------
    stored = None
    for _ in range(50):
        stored = note_row(db, note_id)
        if EDITED in (stored["content_html"] or ""):
            break
        wimi_page.wait_for_timeout(100)
    assert EDITED in (stored["content_html"] or ""), f"the text edit never reached the row: {stored!r}"
    assert _row_tags(db, note_id) == [sid], (
        f"a text-only edit changed the tags: {_row_tags(db, note_id)!r}")
    assert _row_chips(wimi_page, note_id) == [world["subject_name"]]
