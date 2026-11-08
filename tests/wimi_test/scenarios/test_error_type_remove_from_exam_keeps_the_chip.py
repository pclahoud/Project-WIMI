"""Regression (#888): Remove from this exam leaves an entry's error type on it.

*Remove from this exam* is the everyday action in Manage Error Types (#888,
comment 12079, accepted by the owner): it deletes the exam's list row only.
The picker stops offering the type; entries that already carry it keep it,
and analytics still count it.

This opens an existing entry of exam B that carries *Knowledge Gap*, removes
the type from B through the modal with real clicks, and asserts the chip is
still on the entry, the ``entry_tags`` row is still in the database, and the
type has left B's picker. The old Delete removed the type everywhere, which
is what this action must never do.
"""
from __future__ import annotations

from datetime import date

import pytest

from _helpers.w114_form_ready import poll, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _seed(db) -> dict:
    exam = db.create_exam_context(exam_name="Exam B 888 remove")
    db.seed_default_tags(exam.exam_name)
    gap = db.fetchone("SELECT id FROM tags WHERE tag_name = 'Knowledge Gap'")["id"]
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=3, total_incorrect=2,
        session_name="remove session", date_encountered=date.today())
    subject = db.create_subject_node(exam.exam_name, "Cardiology", "System")
    entry = db.create_question_entry(session.id, "a", "b", reflection="<p>r</p>",
                                     explanation="<p>e</p>",
                                     primary_subject_ids=[subject.id],
                                     tag_ids=[gap])
    db.conn.commit()
    return {"session": session.id, "entry": entry.id, "gap": gap}


@pytest.mark.slow
@pytest.mark.regression
def test_remove_from_this_exam_leaves_the_chip_on_an_existing_entry(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    # ---- Arrange ---------------------------------------------------------
    db = wimi_session.user.db
    ids = _seed(db)
    chip = f"[data-testid='entry-form-tags-chip-{ids['gap']}']"
    in_picker = f"!!document.querySelector(\"#tag-hierarchy [data-tag-id='{ids['gap']}']\")"

    wimi_page.goto("entry-form", query={"session_id": ids["session"],
                                        "entry": ids["entry"]})
    wait_for_form_ready(wimi_page)
    assert poll(wimi_page, f"!!document.querySelector(\"{chip}\")"), (
        "premise: the entry opens carrying Knowledge Gap")
    assert poll(wimi_page, in_picker), "premise: B offers Knowledge Gap"

    # ---- Act: Remove from this exam, then confirm ------------------------
    wimi_page.eval_js("openManageTagsModal()")
    remove = f"manage-tag-remove-{ids['gap']}"
    assert poll(wimi_page, f"!!document.querySelector(\"[data-testid='{remove}']\")")
    wimi_page.locator(testid=remove).click()
    assert poll(wimi_page, "document.getElementById('delete-tag-modal')"
                           ".classList.contains('active')"), "no confirmation opened"
    detail = wimi_page.eval_js(
        "document.querySelector('[data-testid=\"delete-tag-modal-usage\"]').textContent")
    assert "1 entry on this exam carries it and keeps it" in detail, detail
    assert wimi_page.eval_js(
        "document.getElementById('delete-tag-confirm').textContent") == "Remove from this exam"
    wimi_page.locator(testid="delete-tag-modal-confirm").click()

    # ---- Assert ----------------------------------------------------------
    assert poll(wimi_page, f"!({in_picker})"), "the type is still in B's picker"
    assert wimi_page.eval_js(f"!!document.querySelector(\"{chip}\")") is True, (
        "Remove from this exam took the chip off the entry")
    assert db.fetchone("SELECT 1 FROM entry_tags WHERE question_entry_id = ?"
                       " AND tag_id = ?", (ids["entry"], ids["gap"])), (
        "Remove from this exam untagged the entry in the database")
    assert db.fetchone("SELECT 1 FROM tags WHERE id = ?", (ids["gap"],)), (
        "Remove from this exam deleted the type from the library")
    assert wimi_page.eval_js(
        f"!!document.querySelector(\"[data-testid='manage-tag-add-{ids['gap']}']\")"), (
        "the removed type should be offered back under Add from your other exams")
