"""#848 Wave 2a: a note card's **Subjects** button still tags the card.

Wave 2a turned the note cards' subject-choosing modal into
``openNoteSubjectChooser()``, a promise the Quick note dialog awaits through
its ``chooseSubjects`` option, so the two cannot drift. ``editNoteSubjects``
now awaits that promise and only then writes ``noteEntry.linkedSubjectIds``,
redraws the card's chips and marks the entry dirty. No scenario pressed a
CARD's Subjects button (PR #864 round 2): the Quick note scenarios press the
dialog's own button, so a regression in the card's half of the plumbing --
Save resolving ``null``, or the ``.then`` never running -- would close the
chooser with no chip drawn, save the card untagged, and leave every quoted
test green. A note no subject names is one ``+ Add existing`` never offers.

So this presses a card's Subjects button, ticks the entry's subject and
presses the chooser's Save, all hit-tested, and reads the chip, the card's
``linkedSubjectIds`` and ``isDirty`` afterwards. The Cancel branch opens the
chooser again -- pre-ticked from the card's current ids, which is the other
direction of the plumbing -- unticks the subject and cancels: nothing may
change and the form stays clean.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import CARDS_READY, open_form, seed_entry
from _helpers.w114_form_ready import poll

CHOOSER_OPEN = (
    "!!document.querySelector('#note-subject-modal.active input[type=\"checkbox\"]')"
)
CHOOSER_GONE = "!document.getElementById('note-subject-modal')"


def _checkbox(subject_id: int) -> str:
    return f'#note-subject-modal input[type="checkbox"][value="{subject_id}"]'


def _card(page: WimiPage, note_id: int) -> dict:
    return json.loads(page.eval_js(
        f"(() => {{ const ne = EntryState.noteEditors.find(e => e.id === {note_id});"
        " if (!ne) return JSON.stringify(null);"
        " const chips = Array.from(document.querySelectorAll("
        "   `[data-testid^=\"entry-form-note-card-${ne.tempId}-subject-chip-\"]`))"
        "   .map(c => c.textContent.trim());"
        " const general = !!document.querySelector("
        "   `.note-card[data-temp-id=\"${ne.tempId}\"] .note-general-badge`);"
        " return JSON.stringify({tempId: ne.tempId, ids: ne.linkedSubjectIds || [],"
        "   chips: chips, general: general, dirty: EntryState.isDirty}); })()"))


def _mark_clean(page: WimiPage) -> None:
    # The first load leaves isDirty true (addNoteCard marks dirty and the
    # loader never marks clean) -- test_quick_note_leaves_the_entry_clean.py
    # says why. Start clean so the button's effect on the flag is readable.
    page.eval_js("(() => { markClean(); return true; })()")
    assert poll(page, "EntryState.isDirty === false", timeout_ms=3000)


@pytest.mark.slow
@pytest.mark.regression
def test_the_cards_subjects_button_tags_the_card_and_cancel_changes_nothing(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange: one saved, untagged note on the entry ----------------
    db = wimi_session.user.db
    world = seed_entry(db, name="QNC")
    note = db.add_entry_note(world["entry_id"], content_html="<p>QNC tag me from the card</p>")
    db.conn.commit()
    open_form(wimi_page, world["session_id"], world["entry_id"])
    assert poll(wimi_page, CARDS_READY, timeout_ms=20000), "the note card never mounted"
    _mark_clean(wimi_page)
    before = _card(wimi_page, note.id)
    assert before and before["ids"] == [] and before["chips"] == [] and before["general"], (
        f"arrange is void: the card is not an untagged card showing General: {before!r}")
    temp_id = before["tempId"]
    sid = world["subject_id"]

    # ---- Act: Subjects -> tick -> Save, every press hit-tested ---------
    wimi_page.locator(testid=f"entry-form-note-card-{temp_id}-subject-button").click()
    assert poll(wimi_page, CHOOSER_OPEN, timeout_ms=5000), (
        "the card's Subjects button did not open the chooser")
    assert wimi_page.eval_js(f"document.querySelector('{_checkbox(sid)}').checked") is False, (
        "the chooser opened with the subject already ticked on an untagged card")
    wimi_page.locator(css=_checkbox(sid)).click()
    assert poll(wimi_page, f"document.querySelector('{_checkbox(sid)}').checked", timeout_ms=3000)
    wimi_page.locator(testid="note-subject-modal-save").click()
    chip = f"entry-form-note-card-{temp_id}-subject-chip-{sid}"
    assert poll(wimi_page, f"!!document.querySelector('[data-testid=\"{chip}\"]')",
                timeout_ms=5000), (
        "the chosen subject never appeared as a chip on the card: the chooser's "
        "answer did not reach editNoteSubjects")
    assert poll(wimi_page, CHOOSER_GONE, timeout_ms=3000), "Save left the chooser in the DOM"

    # ---- Assert: the chip, the state and the dirty flag ----------------
    after = _card(wimi_page, note.id)
    assert after["chips"] == [world["subject_name"]], f"{after!r}"
    assert after["ids"] == [sid], f"the card's linkedSubjectIds did not take the choice: {after!r}"
    assert not after["general"], "the General badge survived beside a subject chip"
    assert after["dirty"] is True, (
        "tagging the card did not mark the entry dirty, so the autosave would never write the tag")

    # ---- Act: open again, untick, Cancel -------------------------------
    _mark_clean(wimi_page)
    wimi_page.locator(testid=f"entry-form-note-card-{temp_id}-subject-button").click()
    assert poll(wimi_page, CHOOSER_OPEN, timeout_ms=5000)
    assert wimi_page.eval_js(f"document.querySelector('{_checkbox(sid)}').checked") is True, (
        "the chooser did not open pre-ticked from the card's current ids")
    wimi_page.locator(css=_checkbox(sid)).click()
    assert poll(wimi_page, f"!document.querySelector('{_checkbox(sid)}').checked", timeout_ms=3000)
    wimi_page.locator(testid="note-subject-modal-cancel").click()
    assert poll(wimi_page, CHOOSER_GONE, timeout_ms=3000), "Cancel left the chooser in the DOM"
    wimi_page.wait_for_timeout(300)   # a late .then would have run by now

    # ---- Assert: nothing changed ---------------------------------------
    cancelled = _card(wimi_page, note.id)
    assert cancelled["ids"] == [sid], f"Cancel changed the card's tags: {cancelled!r}"
    assert cancelled["chips"] == [world["subject_name"]], f"Cancel redrew the chips: {cancelled!r}"
    assert cancelled["dirty"] is False, "Cancel marked the entry dirty"
