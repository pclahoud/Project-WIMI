"""#848 Wave 2a: the Quick note button saves a note that belongs to no entry.

What a student can do now that they could not before: press **Quick note** in
the entry form's header, write, tag a subject, press **Save note** -- and the
note is written as its own row with a NULL origin and no junction row (owner's
decision 1, m036), outside the entry's autosave. Tag it with a subject and the
next entry about that subject offers it under **+ Add existing**: this entry
is tagged with the same subject, so its own count rises straight away.

The positive control is the count itself: it reads nothing before the save,
so the "(1)" afterwards is the save being found, not a page that always said
so. The NULL-origin assertion is the one the mutant that calls
``api.addEntryNote(currentEntryId, ...)`` instead of ``api.addNote`` fails.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import (
    free_notes, junction_count, open_form, seed_entry, set_editor,
    wait_dialog_closed, wait_dialog_open, wait_editor_ready, focus_state,
)
from _helpers.w114_form_ready import poll

TEXT = "QNS tension pneumothorax is a clinical diagnosis"

COUNT_PROBE = (
    "(() => { const b = document.getElementById('btn-attach-existing-notes');"
    " const c = document.getElementById('btn-attach-existing-notes-count');"
    " return JSON.stringify({disabled: !!(b && b.disabled),"
    "  count: c && !c.hidden ? c.textContent.trim() : ''}); })()"
)


def _count(page: WimiPage) -> dict:
    return json.loads(page.eval_js(COUNT_PROBE))


@pytest.mark.slow
@pytest.mark.regression
def test_the_quick_note_button_saves_a_tagged_note_on_no_entry(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    world = seed_entry(db, name="QNS")
    open_form(wimi_page, world["session_id"], world["entry_id"])
    assert free_notes(db) == [], "arrange is void: a free note already exists"
    # The control: nothing to attach yet, so the count below has to come
    # from this scenario's own save.
    for _ in range(50):
        before = _count(wimi_page)
        if before["disabled"]:
            break
        wimi_page.wait_for_timeout(100)
    assert before["disabled"] and before["count"] == "", (
        f"+ Add existing already offers something before the save: {before}")

    # ---- Act: open, write, tag, save ----------------------------------
    wimi_page.locator(testid="entry-form-quick-note-button").click()
    wait_dialog_open(wimi_page)
    heading = wimi_page.eval_js(
        "(() => { const h = document.getElementById('quick-note-title');"
        " return h ? h.textContent.trim() : null; })()")
    assert heading == "Quick note", f"the dialog's h2 reads {heading!r}"
    role = wimi_page.eval_js(
        "document.querySelector('[data-testid=\"quick-note-dialog\"]').getAttribute('role')")
    assert role == "dialog"
    for _ in range(40):
        if focus_state(wimi_page)["inDialog"]:
            break
        wimi_page.wait_for_timeout(50)
    assert focus_state(wimi_page)["inDialog"], (
        f"focus did not move into the dialog: {focus_state(wimi_page)}")
    wait_editor_ready(wimi_page)
    assert wimi_page.eval_js(
        "document.querySelector('[data-testid=\"quick-note-chip-general\"]') !== null"), (
        "a fresh note should show the General chip before any subject is chosen")

    set_editor(wimi_page, f"<p>{TEXT}</p>")

    # Tag the entry's own subject through the shared chooser.
    wimi_page.locator(testid="quick-note-subjects-button").click()
    assert poll(wimi_page,
                "!!document.querySelector('#note-subject-modal.active input[type=\"checkbox\"]')",
                timeout_ms=5000), "the subject chooser never opened over the dialog"
    wimi_page.eval_js(
        "(() => { const cb = document.querySelector('#note-subject-modal input[type=\"checkbox\"][value=\"%d\"]');"
        " if (cb && !cb.checked) cb.click(); return !!cb; })()" % world["subject_id"])
    wimi_page.locator(testid="note-subject-modal-save").click()
    chip = f'quick-note-chip-{world["subject_id"]}'
    assert poll(wimi_page, f"!!document.querySelector('[data-testid=\"{chip}\"]')",
                timeout_ms=5000), "the chosen subject never appeared as a chip"
    assert wimi_page.eval_js(
        f"document.querySelector('[data-testid=\"{chip}\"]').textContent.trim()"
    ) == world["subject_name"]

    wimi_page.locator(testid="quick-note-save-button").click()
    wait_dialog_closed(wimi_page)

    # ---- Assert: one row, NULL origin, no junction, the tag ------------
    rows = []
    for _ in range(50):
        rows = free_notes(db)
        if rows:
            break
        wimi_page.wait_for_timeout(100)
    assert len(rows) == 1, f"expected one note on no entry, found {rows!r}"
    row = rows[0]
    assert TEXT in (row["content_html"] or "")
    assert row["question_entry_id"] is None, (
        f"the Quick note was written onto entry {row['question_entry_id']}; "
        f"it must have a NULL origin (decision 1)")
    assert junction_count(db, row["id"]) == 0, "a free note has no attachment row"
    assert json.loads(row["linked_subject_ids"]) == [world["subject_id"]]
    all_rows = db.fetchall("SELECT question_entry_id FROM entry_notes")
    assert all(r["question_entry_id"] is None for r in all_rows), (
        "a second note reached the entry itself")

    # ---- Assert: + Add existing offers it straight away ----------------
    for _ in range(60):
        after = _count(wimi_page)
        if after["count"]:
            break
        wimi_page.wait_for_timeout(100)
    assert not after["disabled"] and after["count"] == "(1)", (
        f"+ Add existing did not pick up the new tagged note: {after}")
