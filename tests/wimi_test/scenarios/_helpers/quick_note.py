"""Shared helpers for the #848 Wave 2a Quick note scenarios.

The Quick note scenario files (and the note card's own Subjects scenario)
drive the same page; the seeding, the readiness probes and the CDP key
dispatch live here so each file stays about one behaviour.

Two facts the probes lean on, both from CLAUDE.md:

* ``EntryState`` and ``QuickNote.editor()`` are reached by bare name from
  ``eval_js`` (script-scope consts resolve; ``window.EntryState`` is
  ``undefined``), and ``window.QuickNote`` is a real window property because
  ``quick_note.js`` assigns it.
* A RichEditor answers ``isEmpty()`` / ``getContent()`` from queued content
  until TinyMCE's ``init`` fires, so anything that writes into the dialog's
  editor waits for ``isInitialized`` first (#47/#114).
"""
from __future__ import annotations

import json
from datetime import date

from wimi_test.page import WimiPage

from _helpers.w114_form_ready import poll, wait_for_form_ready

DIALOG = '[data-testid="quick-note-dialog"]'

#: The dialog is open: the module says so AND its surface is painted.
DIALOG_OPEN = (
    "(() => { if (!window.QuickNote || !QuickNote.isOpen()) return false;"
    f" const s = document.querySelector('{DIALOG}');"
    " return !!s && s.checkVisibility({checkVisibilityCSS: true}); })()"
)
DIALOG_CLOSED = (
    "(() => { if (window.QuickNote && QuickNote.isOpen()) return false;"
    f" const s = document.querySelector('{DIALOG}');"
    " return !s || !s.checkVisibility({checkVisibilityCSS: true}); })()"
)
#: The dialog's own TinyMCE has mounted and holds any content handed to it.
EDITOR_READY = (
    "(() => { const ed = window.QuickNote && QuickNote.editor();"
    " return !!ed && ed.isInitialized === true; })()"
)
#: Every note card's editor on the form has mounted.
CARDS_READY = (
    "(() => { const eds = (typeof EntryState !== 'undefined' && EntryState.noteEditors) || [];"
    " return eds.length > 0 && eds.every(ne => ne.editor && ne.editor.isInitialized); })()"
)


def seed_entry(db, *, name: str = "QN") -> dict:
    """One exam with one subject, one session, one entry tagged with it."""
    exam = db.create_exam_context(exam_name=f"{name} Exam", exam_description="")
    subject = db.create_subject_node(
        exam_context=exam.exam_name, name=f"{name} Cardiology", level_type="System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=5, total_incorrect=2,
        session_name=f"{name} session", date_encountered=date.today())
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer="a", correct_answer="b",
        reflection="<p>R</p>", explanation="<p>E</p>",
        primary_subject_ids=[subject.id])
    db.conn.commit()
    return {
        "exam_id": exam.id, "subject_id": subject.id,
        "subject_name": subject.name, "session_id": session.id,
        "entry_id": entry.id,
    }


def seed_free_note(db, html: str, *, subject_ids: list[int] | None = None,
                   days_ago: int = 0) -> int:
    """A note on no entry, as one row (the shape tests/database/test_free_notes.py
    uses), optionally aged so a newest-first order is observable."""
    linked = json.dumps(subject_ids) if subject_ids else None
    db.conn.execute(
        "INSERT INTO entry_notes (question_entry_id, content_html, sort_order, linked_subject_ids) "
        "VALUES (NULL, ?, 0, ?)", (html, linked))
    note_id = db.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if days_ago:
        db.conn.execute(
            "UPDATE entry_notes SET updated_at = datetime('now', ?), "
            "created_at = datetime('now', ?) WHERE id = ?",
            (f"-{days_ago} days", f"-{days_ago} days", note_id))
    db.conn.commit()
    return int(note_id)


def open_form(page: WimiPage, session_id: int, entry_id: int | None = None) -> None:
    query = {"session_id": session_id}
    if entry_id is not None:
        query["entry"] = entry_id
    page.goto("entry-form", query=query)
    wait_for_form_ready(page)


def wait_dialog_open(page: WimiPage, *, timeout_ms: int = 10000) -> None:
    assert poll(page, DIALOG_OPEN, timeout_ms=timeout_ms), (
        "the Quick note dialog never opened (QuickNote.isOpen() false or the "
        "surface never became visible)")


def wait_dialog_closed(page: WimiPage, *, timeout_ms: int = 10000) -> None:
    assert poll(page, DIALOG_CLOSED, timeout_ms=timeout_ms), (
        "the Quick note dialog is still open")


def wait_editor_ready(page: WimiPage, *, timeout_ms: int = 20000) -> None:
    assert poll(page, EDITOR_READY, timeout_ms=timeout_ms), (
        "the Quick note dialog's editor never mounted")


def set_editor(page: WimiPage, html: str) -> None:
    """Write into the dialog's editor through its own API, as the note-card
    scenarios do: WimiLocator.fill is a value assignment and cannot type into
    TinyMCE."""
    wait_editor_ready(page)
    page.eval_js("(() => { QuickNote.editor().setContent(%s); return true; })()"
                 % json.dumps(html))


def editor_html(page: WimiPage) -> str:
    wait_editor_ready(page)
    return page.eval_js("QuickNote.editor().getContent().html") or ""


def focus_state(page: WimiPage) -> dict:
    return json.loads(page.eval_js(
        "(() => { const a = document.activeElement;"
        f" const s = document.querySelector('{DIALOG}');"
        " return JSON.stringify({tag: a ? a.tagName : null,"
        "  id: a ? (a.id || null) : null,"
        "  testid: a ? (a.getAttribute('data-testid') || null) : null,"
        "  inDialog: !!(s && a && s.contains(a)),"
        "  inReflection: !!(a && a.closest && a.closest('#reflection-editor'))}); })()"))


def chord(page: WimiPage, key: str = "N", *, ctrl: bool = True,
          shift: bool = True, settle_ms: int = 300) -> None:
    """A real key press through CDP, with modifiers (Alt 1, Ctrl 2, Meta 4,
    Shift 8). Delivered to whatever frame holds focus, which is the case the
    shortcut has to survive."""
    modifiers = (2 if ctrl else 0) | (8 if shift else 0)
    code = {"N": ("KeyN", 78), "Escape": ("Escape", 27)}[key]
    for kind in ("keyDown", "keyUp"):
        page.tab.Input.dispatchKeyEvent(
            type=kind, key=key, code=code[0], windowsVirtualKeyCode=code[1],
            nativeVirtualKeyCode=code[1], modifiers=modifiers)
    page.wait_for_timeout(settle_ms)


def free_notes(db) -> list[dict]:
    return [dict(r) for r in db.fetchall(
        "SELECT id, question_entry_id, content_html, linked_subject_ids "
        "FROM entry_notes WHERE question_entry_id IS NULL ORDER BY id")]


def note_row(db, note_id: int) -> dict | None:
    row = db.fetchone(
        "SELECT id, question_entry_id, content_html, linked_subject_ids "
        "FROM entry_notes WHERE id = ?", (note_id,))
    return dict(row) if row else None


def junction_count(db, note_id: int) -> int:
    return int(db.fetchone(
        "SELECT COUNT(*) AS n FROM entry_note_attachments WHERE note_id = ?",
        (note_id,))["n"])
