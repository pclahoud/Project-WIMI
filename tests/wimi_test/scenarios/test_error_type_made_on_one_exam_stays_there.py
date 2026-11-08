"""Regression (#888 decision 4a): a type made on one exam is offered there only.

Error types are one library per profile, and each exam lists the ones it
offers (``exam_error_types``). The owner's decision 4a: *a new custom type is
added only to the exam where it was made; other exams add it on purpose*.

So a type created through exam A's inline Create Tag flow must not be in exam
B's picker, and must be in B's Manage Error Types under **Add from your other
exams**. Pressing **Add** there puts it in B's picker. Before #888 the copy
was filed under A's name and B could never reach it at all; a "fix" that
listed every new type on every exam would fail the first assertion.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

NEW = "Buzzword Trap"
IN_PICKER = ("!!Array.from(document.querySelectorAll('#tag-hierarchy .tag-item'))"
             f".find(b => b.dataset.name === {json.dumps(NEW)})")


def _seed(db) -> dict:
    out = {}
    for name in ("Exam A 888", "Exam B 888"):
        exam = db.create_exam_context(exam_name=name)
        db.seed_default_tags(name)
        session = db.create_review_session(
            exam_context_id=exam.id, total_questions=3, total_incorrect=2,
            session_name=f"{name} session", date_encountered=date.today())
        out[name] = session.id
    db.conn.commit()
    return out


def _open_form(page: WimiPage, session_id: int) -> None:
    page.eval_js("window.__left_888 = 1")
    page.goto("entry-form", query={"session_id": session_id})
    # A second goto to the same page returns before the new document commits.
    assert poll(page, "typeof window.__left_888 === 'undefined'"), "never navigated"
    wait_for_form_ready(page)
    assert poll(page, "!!document.querySelector('#tag-hierarchy .tag-item')"), (
        "the error-type palette never drew")


@pytest.mark.slow
@pytest.mark.regression
def test_a_type_made_on_one_exam_is_not_offered_on_another_until_added(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    # ---- Arrange ---------------------------------------------------------
    db = wimi_session.user.db
    sessions = _seed(db)

    # ---- Act: create the type through A's inline Create Tag flow ---------
    _open_form(wimi_page, sessions["Exam A 888"])
    wimi_page.eval_js(
        "(() => { const el = document.getElementById('tag-search'); el.focus();"
        f" el.value = {json.dumps(NEW)};"
        " el.dispatchEvent(new Event('input', {bubbles: true})); })()")
    assert poll(wimi_page, "!!document.querySelector('#tag-dropdown .dropdown-create-btn')")
    wimi_page.locator(css="#tag-dropdown .dropdown-create-btn").click()
    assert poll(wimi_page, IN_PICKER), "the new type never reached A's picker"
    row = db.fetchone("SELECT id, exam_context FROM tags WHERE tag_name = ?", (NEW,))
    assert row and row["exam_context"] is None, "decision 3: a library row"
    tag_id = row["id"]
    # Leave without the unsaved-changes dialog, which wedges the tab.
    wimi_page.eval_js("EntryState.isDirty = false")

    # ---- Assert: B's picker does not offer it ----------------------------
    _open_form(wimi_page, sessions["Exam B 888"])
    assert wimi_page.eval_js(IN_PICKER) is False, (
        "4a: a type made on exam A appeared in exam B's picker")

    # ---- Act: B adds it from "Add from your other exams" -----------------
    wimi_page.eval_js("openManageTagsModal()")
    add = f"[data-testid='manage-tag-add-{tag_id}']"
    assert poll(wimi_page, f"!!document.querySelector(\"{add}\")"), (
        "B's Manage Error Types did not offer A's type under Add from your other exams")
    assert wimi_page.eval_js(
        "!document.getElementById('manage-tags-add').hidden") is True
    wimi_page.locator(testid=f"manage-tag-add-{tag_id}").click()

    # ---- Assert: now B offers it, and the Add row is gone ----------------
    assert poll(wimi_page, IN_PICKER), "Add did not put the type in B's picker"
    assert poll(wimi_page, f"!document.querySelector(\"{add}\")"), (
        "the type is still listed under Add from your other exams")
    assert poll(wimi_page,
                f"!!document.querySelector(\"[data-testid='manage-tag-shared-{tag_id}']\")"), (
        "the row should now say the type is also on another exam")
    assert db.fetchone("SELECT COUNT(*) AS n FROM tags WHERE tag_name = ?",
                       (NEW,))["n"] == 1, "decision 1: no copy was made"
