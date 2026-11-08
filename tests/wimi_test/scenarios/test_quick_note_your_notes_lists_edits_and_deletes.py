"""#848 Wave 2a: *Your notes* lists the notes on their own, newest first,
with Edit and Delete (owner's decision 3, comment 11576).

Decision 3 made a free note's subject tag optional and paid for it with this
list: an untagged note on no entry is reachable from nowhere else. So the list
has to show every free note, in the order ``listFreeNotes`` returns them
(``updated_at`` descending), carry the count on its tab and in its footer,
edit one in place, and delete one only after naming what the delete costs.

Seeded rather than typed: two free notes as rows, the older aged by a day so
"newest first" is an observable order rather than an insertion accident. The
older note is also attached to the open entry, so it is BOTH a card on the
form and a row in this list -- which is the case the review found (PR #864
round 1): ``syncEntryNotes()`` rewrites every card from the card's own
content on the entry's next save, so a Your notes edit the card did not take
would be undone by the autosave, and a Your notes delete that left the card
behind would make every later save fail on a row that no longer exists. The
edit and the delete here both target that note, and the card is read after
each.

Three things the first version of this scenario could not see, each pinned
now because a DOM-attribute probe passes against a painted page:

* the inactive tab panel is hidden with the ``hidden`` attribute, and
  ``.qn-panel { display: flex }`` outranked the user agent's ``[hidden]``
  rule, so both panels painted stacked -- ``checkVisibility()`` is read on
  both panels after every view change;
* the inline delete confirmation lands focus on CANCEL, never on its Delete,
  because a <button> activates on keydown and Enter auto-repeats;
* focus survives Cancel (back to the row's Delete), a confirmed delete (the
  row now in the deleted one's place) and Edit (into the editor), where
  before all three dropped it to <body>.

The positive control is the empty list before the seed is read: the tab
count is hidden until the slot answers.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import (
    CARDS_READY, editor_html, free_notes, note_row, open_form, seed_entry,
    seed_free_note, set_editor, wait_dialog_open,
)
from _helpers.w114_form_ready import poll

NEW_TEXT = "QNL newest: read the whole timeline before the options"
OLD_TEXT = "QNL older: peaked T waves are hyperkalemia"
EDITED = "QNL edited: peaked T waves and a wide QRS are hyperkalemia"

ROWS = (
    "JSON.stringify(Array.from(document.querySelectorAll('[data-testid^=\"quick-note-row-\"]'))"
    ".filter(r => /^quick-note-row-\\d+$/.test(r.dataset.testid))"
    ".map(r => ({id: Number(r.dataset.noteId),"
    " text: r.querySelector('.qn-row-text').textContent,"
    " where: r.querySelector('.qn-row-where').textContent})))"
)
TAB_COUNT = (
    "(() => { const c = document.querySelector('[data-testid=\"quick-note-list-count\"]');"
    " return c && !c.hidden ? c.textContent.trim() : null; })()"
)
#: The count pill's attribute and its painting agree: hidden means not drawn.
COUNT_ATTRIBUTE_MATCHES_PAINT = (
    "(() => { const c = document.querySelector('[data-testid=\"quick-note-list-count\"]');"
    " return !!c && c.hidden === !c.checkVisibility({checkVisibilityCSS: true}); })()"
)
FOOTER = "document.querySelector('[data-testid=\"quick-note-footer-text\"]').textContent.trim()"
ROW_COUNT = "document.querySelectorAll('.qn-row').length"
ACTIVE = (
    "(() => { const a = document.activeElement;"
    " return a ? (a.getAttribute('data-testid') || a.id || a.tagName) : null; })()"
)
FOCUS_IN_EDITOR = (
    "(() => { const a = document.activeElement;"
    " return !!(a && a.closest && a.closest('#quick-note-editor')); })()"
)


def _rows(page: WimiPage) -> list[dict]:
    return json.loads(page.eval_js(ROWS))


def _panel_visible(page: WimiPage, which: str) -> bool:
    return bool(page.eval_js(
        f"document.getElementById('quick-note-panel-{which}')"
        ".checkVisibility({checkVisibilityCSS: true})"))


def _assert_one_panel_painted(page: WimiPage, shown: str) -> None:
    other = "list" if shown == "new" else "new"
    assert _panel_visible(page, shown), f"the {shown} panel is not painted while selected"
    assert not _panel_visible(page, other), (
        f"the {other} panel is painted while the {shown} panel is selected: the `hidden` "
        f"attribute is being outranked by an author display rule")


def _card(page: WimiPage, note_id: int) -> dict | None:
    raw = page.eval_js(
        f"(() => {{ const ne = EntryState.noteEditors.find(e => e.id === {note_id});"
        " if (!ne) return null; const c = ne.editor ? ne.editor.getContent() : null;"
        " return JSON.stringify({html: c ? c.html : null, ids: ne.linkedSubjectIds}); })()")
    return json.loads(raw) if raw else None


@pytest.mark.slow
@pytest.mark.regression
def test_your_notes_lists_newest_first_edits_and_deletes(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    world = seed_entry(db, name="QNL")
    older = seed_free_note(db, f"<p>{OLD_TEXT}</p>", subject_ids=[world["subject_id"]],
                           days_ago=1)
    db.attach_existing_note_to_entry(older, world["entry_id"])
    db.conn.commit()
    newer = seed_free_note(db, f"<p><b>{NEW_TEXT}</b></p>")
    # #877: one minute in the past, so the edit below is strictly the most
    # recent write. CURRENT_TIMESTAMP has one-second resolution, and an
    # edit landing in the same second as this note's creation tied on
    # updated_at, with id DESC then listing this note first: 6 of 12 runs
    # failed alone on the MacBook. Still newer than the day-old note.
    db.conn.execute(
        "UPDATE entry_notes SET updated_at = datetime('now', '-1 minute'),"
        " created_at = datetime('now', '-1 minute') WHERE id = ?", (newer,))
    db.conn.commit()
    assert [r["id"] for r in free_notes(db)] == [older, newer]

    open_form(wimi_page, world["session_id"], world["entry_id"])
    assert poll(wimi_page, CARDS_READY, timeout_ms=20000), "the attached note's card never mounted"
    card_before = _card(wimi_page, older)
    assert card_before and OLD_TEXT in card_before["html"], (
        f"the control is void: the attached note is not a card on the form: {card_before!r}")
    # The first load leaves isDirty true (addNoteCard marks dirty and the
    # loader never marks clean) -- test_quick_note_leaves_the_entry_clean.py
    # says why. Start clean so the dialog's effect on the flag is readable.
    wimi_page.eval_js("(() => { markClean(); return true; })()")
    assert poll(wimi_page, "EntryState.isDirty === false", timeout_ms=3000)
    cards_before = wimi_page.eval_js("EntryState.noteEditors.length")

    wimi_page.locator(testid="entry-form-quick-note-button").click()
    wait_dialog_open(wimi_page)
    _assert_one_panel_painted(wimi_page, "new")
    assert wimi_page.eval_js(COUNT_ATTRIBUTE_MATCHES_PAINT), (
        "the tab's count pill is painted while hidden (or hidden while shown)")

    # ---- Act: the list ------------------------------------------------
    wimi_page.locator(testid="quick-note-tab-list").click()
    assert poll(wimi_page, f"{ROW_COUNT} > 0", timeout_ms=10000), (
        "the Your notes list never rendered a row")
    _assert_one_panel_painted(wimi_page, "list")
    rows = _rows(wimi_page)

    # ---- Assert: both notes, newest first, labelled --------------------
    assert [r["id"] for r in rows] == [newer, older], (
        f"rows are not newest first by updated_at: {rows!r}")
    assert NEW_TEXT in rows[0]["text"] and "<b>" not in rows[0]["text"], (
        f"the preview is not the note's plain text: {rows[0]!r}")
    assert rows[0]["where"] == "Not on any entry"
    assert rows[1]["where"] == "On 1 entry", f"{rows[1]!r}"
    assert wimi_page.eval_js(TAB_COUNT) == "2", "the tab does not carry the count"
    assert wimi_page.eval_js(COUNT_ATTRIBUTE_MATCHES_PAINT)
    assert wimi_page.eval_js(FOOTER) == "2 notes on their own"

    # ---- Act: edit the attached one, which is also a card --------------
    wimi_page.locator(testid=f"quick-note-row-{older}-edit").click()
    assert poll(wimi_page, "QuickNote.editor() !== null", timeout_ms=5000)
    _assert_one_panel_painted(wimi_page, "new")
    assert OLD_TEXT in editor_html(wimi_page), "Edit did not load the note into the editor"
    assert poll(wimi_page, FOCUS_IN_EDITOR, timeout_ms=5000), (
        f"Edit left focus at {wimi_page.eval_js(ACTIVE)!r} instead of in the editor: the list "
        f"panel that held the pressed button is hidden, so focus had dropped to <body>")
    assert wimi_page.eval_js(
        "document.querySelector('[data-testid=\"quick-note-save-button\"]').textContent.trim()"
    ) == "Save changes"
    set_editor(wimi_page, f"<p>{EDITED}</p>")
    wimi_page.locator(testid="quick-note-save-button").click()
    assert poll(wimi_page, f"{ROW_COUNT} === 2", timeout_ms=10000), (
        "Save changes did not return to the list")
    _assert_one_panel_painted(wimi_page, "list")
    stored = note_row(db, older)
    assert EDITED in (stored["content_html"] or ""), f"the edit never reached the row: {stored!r}"
    assert stored["question_entry_id"] is None, "editing re-homed the note onto an entry"
    rows = _rows(wimi_page)
    assert [r["id"] for r in rows] == [older, newer], (
        f"the edited note did not move to the top: {rows!r}")
    assert EDITED in rows[0]["text"]

    # ---- Assert: the card on the form took the edit --------------------
    assert poll(wimi_page, f"(() => {{ const ne = EntryState.noteEditors.find(e => e.id === {older});"
                           " return !!ne && ne.editor.getContent().html.includes("
                           f"{json.dumps(EDITED)}); }})()", timeout_ms=5000), (
        f"the card still holds the old text, which the entry's next save would write back over "
        f"the edit: {_card(wimi_page, older)!r}")
    card_after = _card(wimi_page, older)
    assert card_after["ids"] == [world["subject_id"]], (
        f"the card's tags no longer match the note's: {card_after!r}")
    assert wimi_page.eval_js("EntryState.isDirty") is False, (
        "redrawing the card from the dialog's save marked the entry dirty")

    # ---- Act: delete it, after it names the cost -----------------------
    wimi_page.locator(testid=f"quick-note-row-{older}-delete").click()
    confirm = f'[data-testid="quick-note-row-{older}-confirm"]'
    assert poll(wimi_page, f"!!document.querySelector('{confirm}')", timeout_ms=5000), (
        "Delete removed the note without asking")
    assert wimi_page.eval_js(ACTIVE) == f"quick-note-row-{older}-cancel-delete", (
        f"the confirmation landed focus on {wimi_page.eval_js(ACTIVE)!r}; on its Delete an Enter "
        f"key-repeat would delete before the question was read")
    cost = wimi_page.eval_js(f"document.querySelector('{confirm}').textContent")
    assert "on 1 entry" in cost and "removes it from all of them" in cost, (
        f"the confirmation does not name the cost: {cost!r}")
    assert note_row(db, older) is not None, "the row was deleted before the student confirmed"
    # The question names the group and describes Cancel, where focus lands,
    # so a screen reader hears the cost (PR #864 round 3). Read through the
    # ARIA references rather than the DOM order, which focus skips.
    named = json.loads(wimi_page.eval_js(
        f"(() => {{ const g = document.querySelector('{confirm}');"
        " const label = document.getElementById(g.getAttribute('aria-labelledby') || '');"
        " const desc = document.getElementById(document.activeElement.getAttribute('aria-describedby') || '');"
        " return JSON.stringify({name: label ? label.textContent : null,"
        " described: desc ? desc.textContent : null}); })()"))
    assert named["name"] and "There is no undo" in named["name"], (
        f"the confirmation group has no accessible name: {named!r}")
    assert named["described"] == named["name"], (
        f"Cancel is not described by the question it cancels: {named!r}")

    # Cancel hands focus back to the Delete that opened the box.
    wimi_page.locator(testid=f"quick-note-row-{older}-cancel-delete").click()
    assert poll(wimi_page, f"!document.querySelector('{confirm}')", timeout_ms=5000)
    assert wimi_page.eval_js(ACTIVE) == f"quick-note-row-{older}-delete", (
        f"Cancel left focus at {wimi_page.eval_js(ACTIVE)!r}")
    assert note_row(db, older) is not None, "Cancel deleted the note"

    wimi_page.locator(testid=f"quick-note-row-{older}-delete").click()
    assert poll(wimi_page, f"!!document.querySelector('{confirm}')", timeout_ms=5000)
    wimi_page.locator(testid=f"quick-note-row-{older}-confirm-delete").click()
    assert poll(wimi_page, f"{ROW_COUNT} === 1", timeout_ms=10000)

    # ---- Assert: gone from the database, the list, the counts, the form -
    assert note_row(db, older) is None, "Delete left the row in place"
    assert note_row(db, newer) is not None, "Delete took the wrong note"
    assert wimi_page.eval_js(TAB_COUNT) == "1"
    assert wimi_page.eval_js(FOOTER) == "1 note on their own"
    assert wimi_page.eval_js(ACTIVE) == f"quick-note-row-{newer}-edit", (
        f"after the delete focus is at {wimi_page.eval_js(ACTIVE)!r}, not on the row that took "
        f"the deleted one's place")
    assert poll(wimi_page, f"!EntryState.noteEditors.some(e => e.id === {older})", timeout_ms=5000), (
        "the deleted note is still a card on the form, so every later save would call "
        "updateEntryNote on a row that no longer exists")
    assert wimi_page.eval_js("EntryState.noteEditors.length") == cards_before - 1
    assert wimi_page.eval_js(
        f"document.querySelectorAll('.note-card').length") == cards_before - 1, (
        "the card's element outlived its state entry")
    assert wimi_page.eval_js("EntryState.isDirty") is False, (
        "dropping the deleted note's card marked the entry dirty")
