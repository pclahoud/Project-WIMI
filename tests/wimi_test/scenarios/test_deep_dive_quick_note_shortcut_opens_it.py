"""#848 Wave 2b: Ctrl+Shift+N opens Quick note on the deep dive too.

The entry form binds the chord (Wave 2a, comment 11663's build default); the
deep dive binds it with a document keydown, so the shortcut a student has
learnt works on both pages that carry the button.

What this does NOT show is the TinyMCE-iframe route (the chord
rich_editor.js re-emits as ``wimi:editor-shortcut``) opening anything here.
The only rich editor on the deep dive is the Quick note dialog's own, so
that route only ever arrives while the dialog is open, when the page
refuses it; ``test_quick_note_shortcut_opens_from_the_editor.py`` is where
the re-emission is shown opening the dialog, on the entry form.

The page's own refusal -- ``openQuickNote()`` returns while any dialog is
open -- is measured with a DIFFERENT dialog open (the relation modal), with
the Quick note closed. A second press inside the Quick note proves nothing
about it: ``QuickNote.open()`` refuses a second open by itself, so that half
stays green with the page's guard deleted. With the relation modal open and
the guard deleted, the chord opens the Quick note over it.

The key goes through CDP ``Input.dispatchKeyEvent``, a real key press. The
control is the closed state before the press, and Escape closing it again,
which shows the press was the thing that opened it.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.deep_dive_quick_note import open_deep_dive, seed_exam, text_of
from _helpers.quick_note import (
    DIALOG_OPEN, chord, wait_dialog_closed, wait_dialog_open, wait_editor_ready,
)
from _helpers.w114_form_ready import poll

RELATION_MODAL = '[data-testid="relation-modal"]'
SURFACES = "window.ModalDialog.openSurfaces().length"


@pytest.mark.slow
@pytest.mark.regression
def test_ctrl_shift_n_opens_the_quick_note_dialog_on_the_deep_dive(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    world = seed_exam(db, "DDG")
    open_deep_dive(wimi_page, world)

    assert wimi_page.eval_js(DIALOG_OPEN) is False, "control: the dialog starts closed"
    title = wimi_page.eval_js(
        "document.querySelector('[data-testid=\"deep-dive-quick-note-button\"]').title")
    assert "Ctrl+Shift+N" in title, f"the button names its shortcut: {title!r}"

    wimi_page.eval_js("(() => { document.body.focus(); return true; })()")
    chord(wimi_page, "N")
    wait_dialog_open(wimi_page)
    wait_editor_ready(wimi_page)
    assert text_of(wimi_page, f"quick-note-chip-{world['subject_id']}") == world["subject_name"], (
        "opened by the shortcut, the note is pre-tagged the same way")

    # A second press with focus inside the dialog's own editor stacks
    # nothing. This is QuickNote.open()'s own refusal at work as much as the
    # page's, so it is not the page guard's test; that is the last arm below.
    wimi_page.eval_js("(() => { QuickNote.editor().focus(); return true; })()")
    chord(wimi_page, "N")
    count = wimi_page.eval_js(
        "document.querySelectorAll('[data-testid=\"quick-note-dialog\"]').length")
    surfaces = wimi_page.eval_js("window.ModalDialog.openSurfaces().length")
    assert count == 1 and surfaces == 1, (
        f"a second press must not open anything more: {count} dialogs, {surfaces} open")

    chord(wimi_page, "Escape", ctrl=False, shift=False)
    wait_dialog_closed(wimi_page)
    assert "subject_deep_dive" in wimi_page.eval_js("window.location.pathname")

    # ---- Again, after a close: the binding is the page's, not one-shot --
    # And the dialog reopens fresh: a note written and abandoned before is
    # not carried into the next one, which starts tagged with this subject.
    wimi_page.eval_js("(() => { document.body.focus(); return true; })()")
    chord(wimi_page, "N")
    wait_dialog_open(wimi_page)
    wait_editor_ready(wimi_page)
    assert wimi_page.eval_js("QuickNote.editor().isEmpty()") is True, (
        "a reopened dialog starts with an empty editor")
    pressed = wimi_page.eval_js(
        "document.querySelector('[data-testid=\"quick-note-where-own\"]').getAttribute('aria-pressed')")
    assert pressed == "true", "a reopened dialog starts On its own"
    chord(wimi_page, "Escape", ctrl=False, shift=False)
    wait_dialog_closed(wimi_page)

    # ---- With another dialog open, the page refuses the chord ----------
    # The relation modal is a ModalDialog surface that is not the Quick
    # note, so only openQuickNote()'s openSurfaces() check stands between
    # the chord and a second dialog stacked over it.
    assert wimi_page.eval_js(SURFACES) == 0, "control: no dialog is open before the relation modal"
    wimi_page.locator(testid="deep-dive-relations-add").click()
    assert poll(wimi_page,
                f"!!document.querySelector('{RELATION_MODAL}') && {SURFACES} === 1"
                " && document.activeElement === document.querySelector('[data-testid=\"relation-search\"]')",
                timeout_ms=10000), "the relation modal never opened with focus in its search box"
    chord(wimi_page, "N", settle_ms=1000)
    assert wimi_page.eval_js("QuickNote.isOpen()") is False and wimi_page.eval_js(DIALOG_OPEN) is False, (
        "Ctrl+Shift+N opened the Quick note over another open dialog")
    assert wimi_page.eval_js(SURFACES) == 1, (
        f"the chord changed the open dialogs: {wimi_page.eval_js(SURFACES)} open")
    wimi_page.locator(testid="relation-cancel").click()
    assert poll(wimi_page, f"!document.querySelector('{RELATION_MODAL}') && {SURFACES} === 0",
                timeout_ms=5000), "the relation modal did not close"
