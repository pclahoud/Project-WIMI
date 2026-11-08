"""Shared helpers for the #848 Wave 2b scenarios: Quick note on the deep dive.

The deep dive opens the same dialog the entry form does (``quick_note.js``),
so the dialog probes come from ``_helpers.quick_note``; what lives here is the
seeding for this page (an exam, a subject, sessions and entries in the shape
``test_deep_dive_shows_tagged_notes.py`` uses), the page's own readiness
probe, and the picker's probes.

``QuickNote.isPicking()`` is the module's own answer to "is the entry step
showing"; the probes pair it with the panel actually being painted, for the
reason ``DIALOG_OPEN`` does.
"""
from __future__ import annotations

import json

from wimi_test.page import WimiPage

from _helpers.quick_note import wait_dialog_open
from _helpers.w114_form_ready import poll

PICKER = '[data-testid="quick-note-picker"]'

PICKING = (
    "(() => { if (!window.QuickNote || !QuickNote.isPicking()) return false;"
    f" const p = document.querySelector('{PICKER}');"
    " return !!p && p.checkVisibility({checkVisibilityCSS: true}); })()"
)
NOT_PICKING = (
    "(() => { if (window.QuickNote && QuickNote.isPicking()) return false;"
    f" const p = document.querySelector('{PICKER}');"
    " return !p || !p.checkVisibility({checkVisibilityCSS: true}); })()"
)


def seed_exam(db, name: str) -> dict:
    """One exam and two subjects in it: the page's subject and another."""
    db._ensure_phase2_schema()
    exam = db.create_exam_context(exam_name=f"{name} Exam", exam_description="#848 Wave 2b")
    subject = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name=f"{name} Pneumothorax", level_type="Topic",
        relative_weight=5, weight_source="user_defined")
    other = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name=f"{name} Asthma", level_type="Topic",
        relative_weight=5, weight_source="user_defined")
    db.conn.commit()
    return {"exam_id": exam.id, "subject_id": subject.id, "subject_name": subject.name,
            "other_id": other.id, "other_name": other.name}


def seed_session(db, exam_id: int, name: str, *, days_ago: int = 0, total: int = 5) -> int:
    session = db.execute(
        "INSERT INTO review_sessions (user_id, session_name, date_encountered, "
        "exam_context_id, total_questions, total_incorrect) "
        "VALUES (?, ?, date('now', ?), ?, ?, ?)",
        (db.user_id, name, f"-{days_ago} days", exam_id, total * 2, total),
    ).lastrowid
    db.conn.commit()
    return int(session)


def seed_entry(db, session_id: int, subject_id: int, *, order: int, question_id: str,
               user_answer: str = "", correct_answer: str = "", reflection: str = "",
               explanation: str = "", is_draft: bool = False) -> int:
    entry = db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, question_id, "
        "user_answer, correct_answer, reflection, explanation, is_draft) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, order, question_id, user_answer, correct_answer,
         f"<p>{reflection}</p>" if reflection else None,
         f"<p>{explanation}</p>" if explanation else None, 1 if is_draft else 0),
    ).lastrowid
    db.execute(
        "INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, "
        "mapping_type) VALUES (?, ?, 'primary')", (entry, subject_id))
    db.conn.commit()
    return int(entry)


def open_deep_dive(page: WimiPage, world: dict) -> None:
    page.goto("subject-deep-dive",
              query={"subject": world["subject_id"], "exam": world["exam_id"]})
    name = json.dumps(world["subject_name"])
    assert poll(page,
                "(() => { const h = document.querySelector('[data-testid=\"deep-dive-subject-title\"]');"
                f" return !!h && h.textContent.trim() === {name}"
                " && !!document.querySelector('#subjectNotesList > *'); })()",
                timeout_ms=20000), "the deep dive never finished loading"


def open_dialog(page: WimiPage) -> None:
    page.locator(testid="deep-dive-quick-note-button").click()
    wait_dialog_open(page)


def wait_picking(page: WimiPage, *, timeout_ms: int = 10000) -> None:
    assert poll(page, PICKING, timeout_ms=timeout_ms), "the entry step never showed"


def wait_not_picking(page: WimiPage, *, timeout_ms: int = 10000) -> None:
    assert poll(page, NOT_PICKING, timeout_ms=timeout_ms), "the entry step is still showing"


def card_ids(page: WimiPage) -> list[int]:
    return page.eval_js(
        "Array.from(document.querySelectorAll('[data-testid=\"quick-note-picker-entries\"] .qn-card'))"
        ".map(c => Number(c.dataset.entryId))") or []


def wait_cards(page: WimiPage, predicate, *, timeout_ms: int = 15000) -> list[int]:
    elapsed, last = 0, []
    while elapsed < timeout_ms:
        last = card_ids(page)
        if predicate(last):
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def text_of(page: WimiPage, testid: str) -> str | None:
    return page.eval_js(
        f"(() => {{ const e = document.querySelector('[data-testid=\"{testid}\"]');"
        " return e ? e.textContent.trim() : null; })()")


def row_meta(page: WimiPage, note_id: int) -> str | None:
    return text_of(page, f"deep-dive-note-meta-{note_id}")


def wait_row_meta(page: WimiPage, note_id: int, *, timeout_ms: int = 15000) -> str | None:
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        last = row_meta(page, note_id)
        if last:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def notes_on(db) -> list[dict]:
    return [dict(r) for r in db.fetchall(
        "SELECT id, question_entry_id, content_html, linked_subject_ids FROM entry_notes ORDER BY id")]
