"""The deep dive draws notes tagged with the subject, beside the entries (#465).

The owner's design, 2026-10-10: **both lists, and the old one renamed.**
Not a replacement, not an entry count.

Two things this has to hold down that the payload tests cannot:

1. **Both lists are drawn, and their headings tell them apart.** Having
   two similar-looking lists on one page is the acknowledged cost of this
   option, and the naming is the whole mitigation. If the headings stop
   distinguishing them the page is worse than either single-list design,
   and nothing but a rendered test can see that.

2. **The old list's name no longer suggests it holds notes.** Its third
   line is classed ``recent-entry-note`` and falls back to the literal
   string "No notes" while rendering a *reflection*. That class name and
   that string are the entire reason ``README.md``, a briefing and very
   nearly a published chapter all asserted this page already showed
   notes. Renaming the heading is what stops the belief regenerating,
   so the heading is asserted rather than assumed.

The strict-vs-permissive rule is pinned in
``tests/database/test_deep_dive_notes_are_the_tagged_set.py``, where it
can be tested without a browser. Here it is checked once end to end, so
a payload that is right cannot be undone by a renderer that merges the
two lists.

Loader quirk note
-----------------

Probes use ``window.api`` (NOT ``window._wimiApi``): ``_loader.js``
aliases it and deletes the source handle.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

TAGGED_NOTE = "peaked T waves on the ECG"
UNTAGGED_NOTE = "scribble with no subject tag"
REFLECTION = "I confused the potassium thresholds"


def _poll(wimi_page: WimiPage, read, predicate, *, timeout_ms: int = 20000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if predicate(last):
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed(db):
    """One subject, one entry on it, two notes: one tagged, one not."""
    db._ensure_phase2_schema()
    exam = db.create_exam_context(
        exam_name="Notes Exam 465",
        exam_description="#465 - notes tagged with this subject",
    )
    subject = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="Hyperkalemia", level_type="Topic",
        relative_weight=5, weight_source="user_defined")
    ec = db.fetchone("SELECT id FROM exam_contexts WHERE exam_name = ?",
                     (exam.exam_name,))["id"]
    session = db.execute(
        "INSERT INTO review_sessions (user_id, session_name, "
        "date_encountered, exam_context_id, total_questions, total_incorrect) "
        "VALUES (?, 'S', date('now'), ?, 1, 1)", (db.user_id, ec),
    ).lastrowid
    entry = db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer, reflection) VALUES (?, 1, 'A', 'B', ?)",
        (session, f"<p>{REFLECTION}</p>"),
    ).lastrowid
    db.execute(
        "INSERT INTO entry_subject_mappings (question_entry_id, "
        "subject_node_id, mapping_type) VALUES (?, ?, 'primary')",
        (entry, subject.id))
    for text, tags in ((TAGGED_NOTE, [subject.id]), (UNTAGGED_NOTE, None)):
        db.execute(
            "INSERT INTO entry_notes (question_entry_id, content_html, "
            "sort_order, linked_subject_ids) VALUES (?, ?, 0, ?)",
            (entry, f"<p>{text}</p>", json.dumps(tags) if tags else None))
    db.conn.commit()
    return exam.id, subject.id


@pytest.mark.slow
@pytest.mark.regression
def test_the_notes_list_and_the_entries_list_are_both_drawn_and_distinct(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    exam_id, subject_id = _seed(wimi_session.user.db)

    wimi_page.goto("subject-deep-dive",
                   query={"subject": subject_id, "exam": exam_id})

    # ---- Positive control: the notes list rendered a row. Every absence
    # asserted below is meaningless against a page that never loaded (#121).
    notes = _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            "Array.from(document.querySelectorAll("
            "'[data-testid^=\"deep-dive-subject-note-\"]'))"
            ".map(el => el.textContent.trim())"),
        lambda rows: isinstance(rows, list) and len(rows) > 0,
    )
    assert notes, "the notes list drew no rows at all"

    joined = " ".join(notes)
    assert TAGGED_NOTE in joined, (
        f"the note tagged with this subject is not on the page: {notes!r}")
    assert UNTAGGED_NOTE not in joined, (
        "an untagged note on a tagged entry is the PERMISSIVE set and must "
        f"not appear: {notes!r}")

    # ---- The other list is still there, with its own content.
    entries = wimi_page.eval_js(
        "Array.from(document.querySelectorAll("
        "'[data-testid^=\"deep-dive-recent-entry-\"]'))"
        ".map(el => el.textContent.trim())")
    assert entries, (
        "the entries list must survive: the owner chose BOTH lists, not a "
        "replacement")
    assert REFLECTION in " ".join(entries), (
        f"the entries list should still show the reflection: {entries!r}")

    # ---- And the headings tell them apart, which is the whole mitigation
    # for having two similar lists. Asserted on the rendered text because
    # the point is what a student reads.
    headings = wimi_page.eval_js(
        "Array.from(document.querySelectorAll('.section-title'))"
        ".map(el => el.textContent.trim())")
    notes_heading = [h for h in headings if "Notes" in h]
    entries_heading = [h for h in headings if "Recent Entries" in h]

    assert notes_heading, f"no heading names the notes list: {headings!r}"
    assert entries_heading, f"no heading names the entries list: {headings!r}"
    assert "Reflection" in entries_heading[0], (
        "the entries heading must say what those rows CONTAIN -- 'Recent "
        "Entries' alone is what made everyone read them as notes: "
        f"{entries_heading[0]!r}")
    assert notes_heading[0] != entries_heading[0], (
        f"the two headings are identical: {headings!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_a_subject_with_no_tagged_notes_says_which_set_is_empty(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """"No notes" alone would read as "nothing is written about this".

    What is true is that nothing has been *tagged*; the reflections above
    may be full. The empty state has to say which.
    """
    db = wimi_session.user.db
    db._ensure_phase2_schema()
    exam = db.create_exam_context(
        exam_name="Empty Notes Exam 465", exam_description="#465 empty state")
    subject = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="Untouched Topic",
        level_type="Topic", relative_weight=5, weight_source="user_defined")

    wimi_page.goto("subject-deep-dive",
                   query={"subject": subject.id, "exam": exam.id})

    empty = _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            "(() => { const el = document.querySelector("
            "'[data-testid=\"deep-dive-empty-state-subject-notes\"]');"
            " return el ? el.textContent.trim() : null; })()"),
        lambda t: isinstance(t, str) and t != "",
    )
    assert empty, "the notes list drew no empty state"
    assert "tagged" in empty.lower(), (
        f"the empty state must say which set is empty: {empty!r}")
