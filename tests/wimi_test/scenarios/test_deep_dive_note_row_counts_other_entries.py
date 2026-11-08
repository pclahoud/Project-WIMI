"""#848 Wave 2b: a shared note's row says how many other entries hold it.

The mockup's row for a note on two entries reads *Entry #412 · and 1 other*.
Without it a note shared through *+ Add existing* reads as belonging to the
one entry its row opens, which is the 1:1 belief the junction made false.
The figure is the payload's ``attachment_count`` less the origin's own row.

The control is a second note on one entry only, whose row must carry no
"other" at all: a constant or a flag would fail one of the two.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.deep_dive_quick_note import (
    open_deep_dive, seed_entry, seed_exam, seed_session, wait_row_meta,
)


@pytest.mark.slow
@pytest.mark.regression
def test_a_note_on_two_entries_reads_entry_n_and_1_other(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    world = seed_exam(db, "DDF")
    session = seed_session(db, world["exam_id"], "DDF block", days_ago=1)
    first = seed_entry(db, session, world["subject_id"], order=1, question_id="6001",
                       user_answer="A", correct_answer="B")
    second = seed_entry(db, session, world["subject_id"], order=2, question_id="6002",
                        user_answer="C", correct_answer="D")
    shared = db.add_entry_note(first, content_html="<p>DDF shared note</p>",
                               linked_subject_ids=[world["subject_id"]]).id
    assert db.attach_existing_note_to_entry(shared, second), "arrange: attach to a second entry"
    single = db.add_entry_note(first, content_html="<p>DDF single note</p>",
                               linked_subject_ids=[world["subject_id"]]).id
    db.conn.commit()

    open_deep_dive(wimi_page, world)

    shared_meta = wait_row_meta(wimi_page, shared) or ""
    assert f"Entry #{first}" in shared_meta, shared_meta
    assert "and 1 other" in shared_meta, (
        f"a note on two entries should say so beside its entry: {shared_meta!r}")
    assert "Opens the entry" in shared_meta, shared_meta

    single_meta = wait_row_meta(wimi_page, single) or ""
    assert f"Entry #{first}" in single_meta and "Opens the entry" in single_meta, single_meta
    assert "other" not in single_meta, (
        f"control: a note on one entry has no others to count: {single_meta!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_a_note_on_its_own_still_reads_as_one_when_an_entry_holds_it(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """A free note attached through + Add existing is on an entry and still
    has no origin, so its row opens in Quick note and names no entry: the
    count line belongs to rows that open an entry. The attachment is real
    (asserted from the junction), so the absence is the rule, not a missing
    row."""
    db = wimi_session.user.db
    world = seed_exam(db, "DDF2")
    session = seed_session(db, world["exam_id"], "DDF2 block", days_ago=1)
    entry = seed_entry(db, session, world["subject_id"], order=1, question_id="6101",
                       user_answer="A", correct_answer="B")
    free = db.add_free_note(content_html="<p>DDF2 free but attached</p>",
                            linked_subject_ids=[world["subject_id"]]).id
    assert db.attach_existing_note_to_entry(free, entry), "arrange: attach the free note"
    db.conn.commit()
    assert db.fetchone("SELECT COUNT(*) AS n FROM entry_note_attachments WHERE note_id = ?",
                       (free,))["n"] == 1

    open_deep_dive(wimi_page, world)
    meta = wait_row_meta(wimi_page, free) or ""
    assert "Note on its own" in meta and "Opens in Quick note" in meta, meta
    assert "Entry #" not in meta and "other" not in meta, (
        f"a note with no origin names no entry on its row: {meta!r}")
