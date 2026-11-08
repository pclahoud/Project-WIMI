"""#848 Wave 2a: a blank Quick note is not saved, and the dialog says why.

The rule ``test_blank_note_card_writes_no_row.py`` pins for the entry's note
cards (#134: an untouched card is never written) applies to the dialog too,
with one difference -- a card is saved by the entry's autosave and skipped
silently, where the dialog's Save is an explicit press, so refusing it has to
say something. The status line inside the dialog carries the sentence, the
dialog stays open, and nothing reaches ``entry_notes``.

The positive control is the editor itself: the scenario waits until the
dialog's TinyMCE has mounted, because before ``init`` a RichEditor answers
``isEmpty()`` from queued content (#47), and "nothing was written" against a
dialog that never finished opening would prove nothing.

The ``role="status"`` line has to be IN THE TREE BEFORE it is written (PR
#864 round 2). It shipped ``hidden`` until written, and once round 1 made
``.quick-note-modal [hidden]`` real that was ``display: none``: the node was
out of the accessibility tree while empty and entered it with its text in
place, which is an addition to its parent rather than a change to a live
region, so the refusal painted and was never spoken (#127's rule). The
scenario therefore reads the element's ``hidden`` attribute, computed
``display`` and ``visibility`` while it is still EMPTY, and again once the
message is in it.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import (
    free_notes, open_form, seed_entry, wait_dialog_open, wait_editor_ready,
)
from _helpers.w114_form_ready import poll

STATUS = (
    "(() => { const s = document.querySelector('[data-testid=\"quick-note-status\"]');"
    " return s ? s.textContent.trim() : ''; })()"
)
#: Why the status line would NOT be in the accessibility tree, or 'in tree'.
STATUS_IN_TREE = (
    "(() => { const s = document.querySelector('[data-testid=\"quick-note-status\"]');"
    " if (!s) return 'missing'; if (s.hidden) return 'hidden attribute';"
    " const cs = getComputedStyle(s);"
    " if (cs.display === 'none') return 'display none';"
    " if (cs.visibility === 'hidden') return 'visibility hidden';"
    " return 'in tree'; })()"
)


@pytest.mark.slow
@pytest.mark.regression
def test_a_blank_save_writes_no_row_and_says_why(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    world = seed_entry(db, name="QNB")
    open_form(wimi_page, world["session_id"], world["entry_id"])
    total_before = db.fetchone("SELECT COUNT(*) AS n FROM entry_notes")["n"]

    wimi_page.locator(testid="entry-form-quick-note-button").click()
    wait_dialog_open(wimi_page)
    wait_editor_ready(wimi_page)
    assert wimi_page.eval_js("QuickNote.editor().isEmpty()") is True, (
        "the control is void: the dialog's editor is not empty before Save")
    assert wimi_page.eval_js(STATUS) == "", (
        "the status line already shows text before Save was pressed, so the "
        "assertion below would be vacuous")
    assert wimi_page.eval_js(STATUS_IN_TREE) == "in tree", (
        f"the empty status line is {wimi_page.eval_js(STATUS_IN_TREE)}: a live region "
        f"that is out of the accessibility tree until it is written announces nothing")

    # ---- Act -----------------------------------------------------------
    wimi_page.locator(testid="quick-note-save-button").click()
    assert poll(wimi_page, f"({STATUS}) !== ''", timeout_ms=5000), (
        "pressing Save on a blank note produced no message")

    # ---- Assert: it said why, stayed open, wrote nothing ---------------
    message = wimi_page.eval_js(STATUS)
    assert "blank" in message.lower() and "not saved" in message.lower(), (
        f"the refusal does not say that a blank note is not saved: {message!r}")
    assert wimi_page.eval_js(STATUS_IN_TREE) == "in tree", (
        f"the written status line is {wimi_page.eval_js(STATUS_IN_TREE)}")
    assert wimi_page.eval_js("QuickNote.isOpen()") is True, (
        "a refused blank save closed the dialog, which would read as a save")
    wimi_page.wait_for_timeout(500)   # a write in flight would have landed by now
    assert free_notes(db) == [], (
        f"a blank Quick note was written: {free_notes(db)!r}")
    total_after = db.fetchone("SELECT COUNT(*) AS n FROM entry_notes")["n"]
    assert total_after == total_before, (
        f"entry_notes grew from {total_before} to {total_after} on a blank save")

    # The role=status region is what a reader hears; it must be the dialog's
    # own, inside the surface, so the boundary modal_dialog.js draws does not
    # hide it.
    assert wimi_page.eval_js(
        "(() => { const s = document.querySelector('[data-testid=\"quick-note-status\"]');"
        " const d = document.querySelector('[data-testid=\"quick-note-dialog\"]');"
        " return !!s && s.getAttribute('role') === 'status' && d.contains(s); })()"
    ) is True
