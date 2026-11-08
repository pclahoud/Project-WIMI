"""#848 Wave 2b: the deep dive's subject chooser removes the pre-tag and adds another.

The Quick note dialog's **Subjects…** button opens ``chooseNoteSubjects`` on
this page -- its own chooser over the exam's subjects, separate from the
entry form's. It is the only way a student removes the page's subject from a
new note, so its contract is what is measured here: Save resolves to the
ticked ids, and Cancel and Escape resolve to nothing, leaving the chips as
they were even after a box was unticked.

Also measured, because the chooser is a modal surface of its own over the
Quick note dialog: Chromium hands it to assistive tech as a ``dialog`` named
by its title, it is ``ModalDialog``'s topmost surface, focus lands inside
it, the Quick note dialog's controls behind it leave the accessibility tree
while it is open, and focus returns to **Subjects…** when it closes. (The
Quick note's surface node itself stays exposed, measured: it holds a
``role="status"`` line, and ``modal_dialog.js`` descends into a subtree with
a live region rather than hiding it whole, so the instrument is a control
inside it, not the dialog node.)

The controls: the chips before the chooser opens (the page's subject and
not the other), and Cancel and Escape each after a box was changed, so the
final retag is the Save button's doing and not a chooser that applies every
change as it is made.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers import a11y
from _helpers.deep_dive_quick_note import open_deep_dive, open_dialog, seed_exam
from _helpers.quick_note import (
    DIALOG_OPEN, chord, free_notes, set_editor, wait_dialog_closed, wait_editor_ready,
)
from _helpers.w114_form_ready import poll

TEXT = "DDS a pleural effusion blunts the costophrenic angle"
CHOOSER = '[data-testid="deep-dive-subject-chooser"]'
CHOOSER_OPEN = (
    f"(() => {{ const s = document.querySelector('{CHOOSER}');"
    " return !!s && s.checkVisibility({checkVisibilityCSS: true}); })()"
)
CHOOSER_GONE = f"!document.querySelector('{CHOOSER}')"
FOCUS_ON_SUBJECTS = (
    "document.activeElement === "
    "document.querySelector('[data-testid=\"quick-note-subjects-button\"]')"
)


def _chips(page: WimiPage) -> list[str]:
    return json.loads(page.eval_js(
        "JSON.stringify(Array.from(document.querySelectorAll("
        "'[data-testid^=\"quick-note-chip-\"]')).map(c => c.getAttribute('data-testid')))"))


def _open_chooser(page: WimiPage) -> None:
    page.locator(testid="quick-note-subjects-button").click()
    assert poll(page, CHOOSER_OPEN, timeout_ms=5000), "the subject chooser never opened"


def _box(page: WimiPage, subject_id: int) -> bool | None:
    return page.eval_js(
        f"(() => {{ const b = document.querySelector("
        f"'[data-testid=\"deep-dive-subject-chooser-option-{subject_id}\"]');"
        " return b ? b.checked : null; })()")


def _toggle(page: WimiPage, subject_id: int, *, to: bool) -> None:
    page.locator(testid=f"deep-dive-subject-chooser-option-{subject_id}").click()
    assert poll(page, f"(() => {{ const b = document.querySelector("
                      f"'[data-testid=\"deep-dive-subject-chooser-option-{subject_id}\"]');"
                      f" return !!b && b.checked === {json.dumps(to)}; }})()",
                timeout_ms=3000), f"the box for subject {subject_id} never became {to}"


@pytest.mark.slow
@pytest.mark.regression
def test_the_deep_dive_chooser_saves_the_ticked_subjects_and_cancel_keeps_the_chips(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    world = seed_exam(db, "DDS")
    here, other = world["subject_id"], world["other_id"]
    before = [f"quick-note-chip-{here}"]
    open_deep_dive(wimi_page, world)
    open_dialog(wimi_page)
    wait_editor_ready(wimi_page)
    set_editor(wimi_page, f"<p>{TEXT}</p>")
    assert _chips(wimi_page) == before, f"control: the note starts tagged here only: {_chips(wimi_page)!r}"

    # ---- The chooser is a dialog of its own, over the Quick note -------
    a11y.enable(wimi_page)
    _open_chooser(wimi_page)
    assert _box(wimi_page, here) is True and _box(wimi_page, other) is False, (
        "the chooser should open on the note's current tags")
    node = a11y.ax_node(wimi_page, CHOOSER)
    assert node["found"] and node["role"] == "dialog", f"the chooser is not exposed as a dialog: {node!r}"
    assert node["name"] == "Quick note — Assign Subjects", f"the chooser's accessible name: {node!r}"
    assert wimi_page.eval_js(
        f"window.ModalDialog.topmost() === document.querySelector('{CHOOSER}')"), (
        "the chooser is not ModalDialog's topmost surface")
    assert poll(wimi_page, f"document.querySelector('{CHOOSER}').contains(document.activeElement)",
                timeout_ms=3000), "focus did not move into the chooser"
    for testid in ("quick-note-subjects-button", "quick-note-save-button"):
        behind: dict = {}
        for _ in range(30):
            behind = a11y.ax_node(wimi_page, f'[data-testid="{testid}"]')
            if behind["found"] and behind["ignored"]:
                break
            wimi_page.wait_for_timeout(100)
        assert behind["found"] and behind["ignored"], (
            f"{testid} behind the chooser is still in the accessibility tree: {behind!r}")

    # ---- Control 1: untick, then Cancel -> the chips are unchanged -----
    _toggle(wimi_page, here, to=False)
    wimi_page.locator(testid="deep-dive-subject-chooser-cancel").click()
    assert poll(wimi_page, CHOOSER_GONE, timeout_ms=3000), "Cancel did not close the chooser"
    assert _chips(wimi_page) == before, f"Cancel changed the chips: {_chips(wimi_page)!r}"
    assert poll(wimi_page, FOCUS_ON_SUBJECTS, timeout_ms=3000), (
        "focus did not return to Subjects… after Cancel")
    assert wimi_page.eval_js(DIALOG_OPEN), "Cancel closed the Quick note dialog too"

    # ---- Control 2: tick the other, then Escape -> unchanged -----------
    _open_chooser(wimi_page)
    _toggle(wimi_page, other, to=True)
    chord(wimi_page, "Escape", ctrl=False, shift=False)
    assert poll(wimi_page, CHOOSER_GONE, timeout_ms=3000), "Escape did not close the chooser"
    assert _chips(wimi_page) == before, f"Escape changed the chips: {_chips(wimi_page)!r}"
    assert wimi_page.eval_js(DIALOG_OPEN), "Escape closed the Quick note dialog as well as the chooser"
    assert poll(wimi_page, FOCUS_ON_SUBJECTS, timeout_ms=3000), (
        "focus did not return to Subjects… after Escape")

    # ---- Act: untick the page's subject, tick the other, Save ----------
    _open_chooser(wimi_page)
    assert _box(wimi_page, here) is True and _box(wimi_page, other) is False, (
        "a cancelled chooser's changes were carried into the next one")
    _toggle(wimi_page, here, to=False)
    _toggle(wimi_page, other, to=True)
    wimi_page.locator(testid="deep-dive-subject-chooser-save").click()
    assert poll(wimi_page, CHOOSER_GONE, timeout_ms=3000), "Save did not close the chooser"
    assert _chips(wimi_page) == [f"quick-note-chip-{other}"], (
        f"Save should leave only the other subject's chip: {_chips(wimi_page)!r}")
    assert poll(wimi_page, FOCUS_ON_SUBJECTS, timeout_ms=3000), (
        "focus did not return to Subjects… after Save")

    wimi_page.locator(testid="quick-note-save-button").click()
    wait_dialog_closed(wimi_page)

    # ---- Assert: the row carries the chosen tags, not the page's -------
    rows: list[dict] = []
    for _ in range(50):
        rows = free_notes(db)
        if rows:
            break
        wimi_page.wait_for_timeout(100)
    assert len(rows) == 1, f"expected one note on no entry, found {rows!r}"
    assert TEXT in (rows[0]["content_html"] or "")
    assert json.loads(rows[0]["linked_subject_ids"]) == [other], (
        f"the note should carry only the subject ticked in the chooser: {rows[0]!r}")
