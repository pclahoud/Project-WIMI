"""#848 Wave 2b: Back from the entry step returns to the note as it was.

The picker is a step inside the one dialog (decision 5), so it replaces the
dialog's body rather than opening over it. That is only safe if going there
and back costs the student nothing: the editor is hidden with its panel, not
destroyed, and Back -- an icon button whose accessible name is *Back to the
note* -- restores it with the text intact and focus on the button that opened
the step.

The control is the editor's content read back before the step: the text
after Back is the same text, in the same editor instance, not a page that
happened to show it.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.deep_dive_quick_note import (
    open_deep_dive, open_dialog, seed_entry, seed_exam, seed_session, wait_cards,
    wait_not_picking, wait_picking,
)
from _helpers.quick_note import chord, editor_html, focus_state, set_editor

TEXT = "DDD half a sentence the student has not saved yet"


@pytest.mark.slow
@pytest.mark.regression
def test_back_from_the_picker_restores_the_note_with_its_content(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    world = seed_exam(db, "DDD")
    session = seed_session(db, world["exam_id"], "DDD block", days_ago=1)
    seed_entry(db, session, world["subject_id"], order=1, question_id="4001",
               user_answer="A", correct_answer="B")

    open_deep_dive(wimi_page, world)
    open_dialog(wimi_page)
    set_editor(wimi_page, f"<p>{TEXT}</p>")
    assert TEXT in editor_html(wimi_page), "control: the text is in the editor before the step"
    wimi_page.eval_js("(() => { window.__ddd_editor = QuickNote.editor(); return true; })()")

    wimi_page.locator(testid="quick-note-where-entry").click()
    wimi_page.locator(testid="quick-note-choose-entry").click()
    wait_picking(wimi_page)
    assert wait_cards(wimi_page, lambda ids: len(ids) == 1), "the step drew its candidate"
    hidden = wimi_page.eval_js(
        "!document.getElementById('quick-note-editor').checkVisibility()"
        " && QuickNote.editor() === window.__ddd_editor")
    assert hidden is True, "in the step the editor is hidden, and still the same editor"
    name = wimi_page.eval_js(
        "document.querySelector('[data-testid=\"quick-note-picker-back\"]').getAttribute('aria-label')")
    assert name == "Back to the note", name
    labelled = wimi_page.eval_js(
        "document.querySelector('[data-testid=\"quick-note-dialog\"]').getAttribute('aria-labelledby')")
    assert labelled == "quick-note-picker-title", "the step is named by its own heading"

    wimi_page.locator(testid="quick-note-picker-back").click()
    wait_not_picking(wimi_page)

    assert wimi_page.eval_js("QuickNote.editor() === window.__ddd_editor") is True, (
        "Back must return to the same editor, not a new one")
    assert TEXT in editor_html(wimi_page), "the note's text must survive the step"
    assert wimi_page.eval_js(
        "document.getElementById('quick-note-editor').checkVisibility()") is True
    assert wimi_page.eval_js(
        "document.querySelector('[data-testid=\"quick-note-where-entry\"]')"
        ".getAttribute('aria-pressed')") == "true", "still On an entry"
    assert focus_state(wimi_page)["testid"] == "quick-note-choose-entry", (
        f"focus should land on the button that opened the step: {focus_state(wimi_page)}")
    assert wimi_page.eval_js(
        "document.querySelector('[data-testid=\"quick-note-dialog\"]')"
        ".getAttribute('aria-labelledby')") == "quick-note-title"

    # ---- Escape in the step is Back too, never Close -------------------
    # Closing from the step would throw away a note the student cannot see.
    wimi_page.locator(testid="quick-note-choose-entry").click()
    wait_picking(wimi_page)
    chord(wimi_page, "Escape", ctrl=False, shift=False)
    wait_not_picking(wimi_page)
    assert wimi_page.eval_js("QuickNote.isOpen()") is True, (
        "Escape in the entry step must return to the note, not close the dialog")
    assert TEXT in editor_html(wimi_page), "and the note's text is still there"

    # ---- A click on the backdrop in the step is Back too ---------------
    # The same reason as Escape: a stray click outside the dialog must not
    # throw away a note the student cannot see (operator's edit on PR #865).
    # A real hit-tested press at the viewport's corner, which is backdrop.
    wimi_page.locator(testid="quick-note-choose-entry").click()
    wait_picking(wimi_page)
    hit = wimi_page.eval_js(
        "(() => { const el = document.elementFromPoint(4, 4);"
        " return el ? el.id : null; })()")
    assert hit == "quick-note-modal", f"the corner is not the backdrop: {hit!r}"
    for kind in ("mousePressed", "mouseReleased"):
        wimi_page.tab.Input.dispatchMouseEvent(
            type=kind, x=4, y=4, button="left", clickCount=1)
    wait_not_picking(wimi_page)
    assert wimi_page.eval_js("QuickNote.isOpen()") is True, (
        "a backdrop click in the entry step must return to the note, not close the dialog")
    assert TEXT in editor_html(wimi_page), "and the note's text is still there"
