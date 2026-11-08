"""#848 Wave 2a: Ctrl+Shift+N opens Quick note from inside a rich text editor.

The build default recorded on #848 comment 11663: the moment a student wants a
note is mid-explanation, with the caret in an editor, so the chord has to work
*there*. Two facts decide the mechanism and both are measured here:

* ``setupTimerHotkeys()`` skips INPUT, TEXTAREA and contentEditable on
  purpose and is left as it is; the chord has its own listener.
* A keydown inside a TinyMCE iframe never reaches the parent document, so a
  document listener alone misses the press exactly where it matters.
  ``rich_editor.js`` re-emits Ctrl/Meta+Shift chords as a
  ``wimi:editor-shortcut`` event on the document; the page listens to both.

The key is pressed through CDP ``Input.dispatchKeyEvent``, which is delivered
to the frame that holds focus -- so the first case really does arrive inside
the iframe. The negative control is a plain ``N`` with no modifiers, which
must open nothing; the positive control is the same chord with focus on the
page body. A second chord while the dialog is open opens nothing more, and
Escape closes it with focus returned to where it was.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import (
    chord, focus_state, open_form, seed_entry, wait_dialog_closed,
    wait_dialog_open, wait_editor_ready,
)
from _helpers.w114_form_ready import poll

OPEN_SURFACES = "window.ModalDialog.openSurfaces().length"


def _focus_reflection(page: WimiPage) -> None:
    page.eval_js("(() => { EntryState.reflectionEditor.focus(); return true; })()")
    assert poll(page, "document.activeElement && document.activeElement.tagName === 'IFRAME'"
                      " && !!document.activeElement.closest('#reflection-editor')",
                timeout_ms=5000), (
        f"focus did not land in the reflection editor's iframe: {focus_state(page)}")


@pytest.mark.slow
@pytest.mark.regression
def test_ctrl_shift_n_opens_from_the_editor_and_from_the_body(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    world = seed_entry(db, name="QNK")
    open_form(wimi_page, world["session_id"], world["entry_id"])
    assert poll(wimi_page, "EntryState.reflectionEditor && EntryState.reflectionEditor.isInitialized",
                timeout_ms=20000), "the reflection editor never mounted"
    assert wimi_page.eval_js("QuickNote.isOpen()") is False

    # ---- Negative control: a plain N inside the editor opens nothing ---
    _focus_reflection(wimi_page)
    chord(wimi_page, "N", ctrl=False, shift=False)
    assert wimi_page.eval_js("QuickNote.isOpen()") is False, (
        "a bare N opened the dialog; the chord is not being checked")

    # ---- Act 1: the chord from inside the reflection iframe ------------
    _focus_reflection(wimi_page)
    chord(wimi_page, "N")
    wait_dialog_open(wimi_page)
    wait_editor_ready(wimi_page)
    for _ in range(40):
        if focus_state(wimi_page)["inDialog"]:
            break
        wimi_page.wait_for_timeout(50)
    assert focus_state(wimi_page)["inDialog"], f"focus is not in the dialog: {focus_state(wimi_page)}"
    assert wimi_page.eval_js(OPEN_SURFACES) == 1

    # A second press while it is open opens nothing more.
    chord(wimi_page, "N")
    assert wimi_page.eval_js(OPEN_SURFACES) == 1, "the chord opened a second dialog over the first"
    assert wimi_page.eval_js("QuickNote.isOpen()") is True

    # Escape closes it and focus goes back to the reflection editor.
    chord(wimi_page, "Escape", ctrl=False, shift=False)
    wait_dialog_closed(wimi_page)
    for _ in range(40):
        if focus_state(wimi_page)["inReflection"]:
            break
        wimi_page.wait_for_timeout(50)
    back = focus_state(wimi_page)
    assert back["inReflection"] and back["tag"] == "IFRAME", (
        f"after Escape focus is at {back}, not back in the reflection editor")

    # ---- Act 2: the chord with focus on the page body ------------------
    wimi_page.eval_js(
        "(() => { if (document.activeElement && document.activeElement.blur) document.activeElement.blur();"
        " return true; })()")
    assert poll(wimi_page, "document.activeElement === document.body", timeout_ms=3000), (
        f"could not park focus on <body>: {focus_state(wimi_page)}")
    chord(wimi_page, "N")
    wait_dialog_open(wimi_page)
    assert wimi_page.eval_js(OPEN_SURFACES) == 1

    chord(wimi_page, "Escape", ctrl=False, shift=False)
    wait_dialog_closed(wimi_page)

    # ---- Act 3: from a plain field, where the timer handler would skip --
    # A focused <input> is the case setupTimerHotkeys() refuses on purpose;
    # the chord must still open, and Escape must put focus back on the field.
    # (With focus parked on <body> there is nothing to return to: the helper
    # returns focus to the last focused element, which is the right call.)
    wimi_page.eval_js("(() => { document.getElementById('question-id').focus(); return true; })()")
    assert poll(wimi_page, "document.activeElement && document.activeElement.id === 'question-id'",
                timeout_ms=3000)
    chord(wimi_page, "N")
    wait_dialog_open(wimi_page)
    chord(wimi_page, "Escape", ctrl=False, shift=False)
    wait_dialog_closed(wimi_page)
    for _ in range(40):
        if focus_state(wimi_page)["id"] == "question-id":
            break
        wimi_page.wait_for_timeout(50)
    assert focus_state(wimi_page)["id"] == "question-id", (
        f"after Escape focus is at {focus_state(wimi_page)}, not back on the field it left")
