"""Regression: an untouched "+ Add Note" card must not become a note row.

Forgejo issue #134, second half (comment #1741). #134 was two defects. The
rendering half — ``#notes-list-container:empty`` never re-invalidating on
QtWebEngine 6.10, so the new card was 0 px tall and the student clicked
again and again — landed in ``bcf7aa0`` and is guarded by
``test_empty_containers_become_visible.py``. This file covers the other
half, which is engine-independent and reproduces on the shipped stack:

    ``syncEntryNotes()`` had no emptiness check, so **every** card in
    ``collectFormData().notesList`` was written as its own ``entry_notes``
    row. Measured on Windows: three blank cards, three blank rows, plus an
    empty row created by ordinary autosave. Measured here before the fix:
    one click on "+ Add Note", one Save Draft, one blank row
    (``content_html = ''``) that nothing tells the student about and no UI
    action removes.

The fix skips a card that is blank **and** has no id. The asymmetry is the
whole point, and the first two tests below pin both sides of it:

* **no id + blank** — never typed into, so there is nothing to keep.
* **id + blank** — an existing note the student emptied. That is what Clear
  means, and it is a different intent from never having typed anything, so
  it must still be persisted as blank.

Blankness is asked of the card's own ``RichEditor.isEmpty()`` rather than of
the collected HTML, because it is embed-aware: a note holding only an image
or only a table has empty *text* and must not be discarded. That direction
is pinned too — failing there loses real work silently, which is worse than
the bug being fixed. (Measured: an untouched TinyMCE card reports
``getContent().html === ''`` exactly, not ``<p></p>`` and not ``<br>``. The
predicate does not lean on that — a card emptied by hand holds
``<p><br></p>`` or ``&nbsp;`` — hence ``isEmpty()``'s text-plus-embeds test.)

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

TYPED = "NCR typed note body"
IMG_ONLY = ('<p><img src="data:image/gif;base64,'
            'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"></p>')
TABLE_ONLY = ('<table border="1"><tbody><tr><td></td><td></td></tr>'
              '</tbody></table>')

READY = """
(() => {
  if (typeof EntryState === 'undefined') return null;
  if (EntryState.isLoading) return null;
  if (!document.getElementById('btn-add-note')) return null;
  return JSON.stringify({entryId: EntryState.currentEntry ? EntryState.currentEntry.id : null});
})()
"""

# Every note card's TinyMCE has mounted. Until then isEmpty() answers from
# queued content — correct, but not what this file is measuring.
EDITORS_READY = """
(() => {
  const eds = (typeof EntryState !== 'undefined' && EntryState.noteEditors) || [];
  if (!eds.length) return null;
  if (!eds.every(ne => ne.editor && ne.editor.isInitialized)) return null;
  return JSON.stringify({count: eds.length});
})()
"""

# markClean() runs after syncEntryNotes(), so a clean form means every note
# write this save was going to make has already been made.
SAVED = """
(() => {
  if (typeof EntryState === 'undefined') return null;
  if (EntryState.isDirty) return null;
  if (!EntryState.currentEntry || !EntryState.currentEntry.id) return null;
  return JSON.stringify({entryId: EntryState.currentEntry.id});
})()
"""


def _poll(page: WimiPage, js: str, *, timeout_ms: int = 30000):
    elapsed = 0
    while elapsed < timeout_ms:
        try:
            result = page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            result = None
        if result is not None:
            return json.loads(result)
        page.wait_for_timeout(200)
        elapsed += 200
    return None


def _seed(db, *, with_note: str | None = None) -> tuple[int, int | None]:
    """A session with one entry slot; optionally an entry carrying one note."""
    exam = db.create_exam_context(exam_name="Blank Note Exam", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=5, total_incorrect=1,
        session_name="Blank note session", date_encountered=date.today())
    entry_id = None
    if with_note is not None:
        entry = db.create_question_entry(
            review_session_id=session.id, user_answer="a", correct_answer="b")
        db.add_entry_note(entry_id=entry.id, content_html=with_note)
        entry_id = entry.id
    db.conn.commit()
    return session.id, entry_id


def _open_form(page: WimiPage, session_id: int, entry_id: int | None = None) -> None:
    query = {"session_id": session_id}
    if entry_id is not None:
        query["entry"] = entry_id
    page.goto("entry-form", query=query)
    assert _poll(page, READY) is not None, "the entry form never finished loading"


def _add_note_card(page: WimiPage) -> None:
    page.locator(testid="entry-form-notes-add-button").click()
    assert _poll(page, EDITORS_READY), "the new note card's editor never mounted"


def _save_draft(page: WimiPage) -> int:
    page.locator(testid="entry-form-save-draft-button").click()
    saved = _poll(page, SAVED)
    assert saved, "Save Draft never completed (the form stayed dirty)"
    return saved["entryId"]


def _notes_of(db, entry_id: int) -> list[dict]:
    return [dict(r) for r in db.fetchall(
        "SELECT id, content_html FROM entry_notes WHERE question_entry_id = ? "
        "ORDER BY id", (entry_id,))]


@pytest.mark.slow
@pytest.mark.regression
def test_an_untouched_note_card_writes_no_row(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """One abandoned click on '+ Add Note' must leave nothing behind."""
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    session_id, _ = _seed(db)
    _open_form(wimi_page, session_id)

    # ---- Act: click once, never type, save -----------------------------
    _add_note_card(wimi_page)
    entry_id = _save_draft(wimi_page)

    # ---- Assert: no row, and the card is still usable ------------------
    rows = _notes_of(db, entry_id)
    assert rows == [], (
        f"An untouched note card was persisted: {rows!r}. This is #134 — one "
        f"stray click leaves one empty note behind permanently, and nothing "
        f"in the UI tells the student or removes it.")
    assert wimi_page.eval_js(
        "document.querySelectorAll('#notes-list-container .note-card').length"
    ) == 1, (
        "Not writing the card must not mean removing it — the student can "
        "still type into it, and the next save must then keep it.")


@pytest.mark.slow
@pytest.mark.regression
def test_an_existing_note_emptied_is_persisted_as_blank(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The other half of the asymmetry: clearing is not the same as never typing."""
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    session_id, entry_id = _seed(db, with_note="<p>Something worth clearing</p>")
    _open_form(wimi_page, session_id, entry_id)
    assert _poll(wimi_page, EDITORS_READY), "the stored note's editor never mounted"
    before = _notes_of(db, entry_id)
    assert len(before) == 1 and before[0]["content_html"]

    # ---- Act: empty the editor, then save ------------------------------
    # Through the editor's own API rather than keystrokes: the Clear button
    # asks confirm(), which the harness has no dialog handler for, and the
    # predicate under test reads the live TinyMCE either way. markDirty() is
    # what a real keystroke would also have done.
    wimi_page.eval_js(
        "(() => { EntryState.noteEditors[0].editor.setContent(''); "
        "markDirty(); return true; })()")
    _save_draft(wimi_page)

    # ---- Assert: the row survives, blank -------------------------------
    after = _notes_of(db, entry_id)
    assert len(after) == 1 and after[0]["id"] == before[0]["id"], (
        f"Emptying a saved note deleted its row: {before!r} -> {after!r}. A "
        f"card with an id must still be written, blank.")
    assert not (after[0]["content_html"] or "").strip(), (
        f"The emptied note kept its old content: {after!r}. The blank never "
        f"reached the database, so reopening the entry resurrects the text.")


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize(
    "html, label",
    [(f"<p>{TYPED}</p>", "typed text"),
     (IMG_ONLY, "an image and no text"),
     (TABLE_ONLY, "an empty table and no text")],
    ids=["typed_text", "image_only", "table_only"])
def test_a_note_with_content_is_still_saved(
    wimi_session: WimiTestSession, wimi_page: WimiPage, html: str, label: str,
) -> None:
    """The strict direction: a card carrying anything real must survive.

    An image-only or table-only card has empty *text*, so a predicate
    written against ``textContent`` would silently discard a screenshot the
    student had just pasted in.
    """
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    session_id, _ = _seed(db)
    _open_form(wimi_page, session_id)
    _add_note_card(wimi_page)

    # ---- Act -----------------------------------------------------------
    wimi_page.eval_js(
        "(() => { EntryState.noteEditors[0].editor.setContent(%s); "
        "markDirty(); return true; })()" % json.dumps(html))
    entry_id = _save_draft(wimi_page)

    # ---- Assert ---------------------------------------------------------
    rows = _notes_of(db, entry_id)
    assert len(rows) == 1, (
        f"A new note card holding {label} was not saved: {rows!r}. The "
        f"emptiness check must not reach past genuinely blank cards.")
