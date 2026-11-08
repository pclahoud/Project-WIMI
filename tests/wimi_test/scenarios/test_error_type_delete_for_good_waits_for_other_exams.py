"""Regression (#888 decision 4b): Delete for good only once no other exam lists it.

Deleting a type for good takes it off every entry that carries it, in every
exam. The owner's decision 4b: *offered only once no other exam lists the
type*. That does NOT keep the delete out of other exams: Remove from this
exam leaves that exam's entries tagged, so once B has removed the type a
delete for good on A still untags B's entries. The confirmation's count
across every exam is the only warning, which is what this test pins.

Exams A and B both offer *Memory Failure*, and an entry of B carries it. On
A's Manage Error Types the row must have no trash button and must say it is
also on another exam. Once B stops offering the type, the trash button
appears on A, and its confirmation counts B's entry: the count spans every
exam, which is what the student is agreeing to.
"""
from __future__ import annotations

from datetime import date

import pytest

from _helpers.w114_form_ready import poll, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

A, B = "Exam A 888 delete", "Exam B 888 delete"


def _seed(db) -> dict:
    sessions = {}
    exams = {}
    for name in (A, B):
        exams[name] = db.create_exam_context(exam_name=name)
        db.seed_default_tags(name)
        sessions[name] = db.create_review_session(
            exam_context_id=exams[name].id, total_questions=3, total_incorrect=2,
            session_name=f"{name} session", date_encountered=date.today()).id
    memory = db.fetchone("SELECT id FROM tags WHERE tag_name = 'Memory Failure'")["id"]
    subject = db.create_subject_node(B, "Renal", "System")
    entry = db.create_question_entry(sessions[B], "a", "b",
                                     primary_subject_ids=[subject.id],
                                     tag_ids=[memory])
    db.conn.commit()
    return {"session": sessions[A], "memory": memory, "entry": entry.id}


def _exists(page: WimiPage, testid: str) -> str:
    return f"!!document.querySelector(\"[data-testid='{testid}']\")"


@pytest.mark.slow
@pytest.mark.regression
def test_delete_for_good_appears_only_when_no_other_exam_lists_the_type(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    # ---- Arrange ---------------------------------------------------------
    db = wimi_session.user.db
    ids = _seed(db)
    delete = f"manage-tag-delete-{ids['memory']}"
    shared = f"manage-tag-shared-{ids['memory']}"
    remove = f"manage-tag-remove-{ids['memory']}"

    wimi_page.goto("entry-form", query={"session_id": ids["session"]})
    wait_for_form_ready(wimi_page)

    # ---- Assert: while B lists it, A offers no Delete for good -----------
    wimi_page.eval_js("openManageTagsModal()")
    assert poll(wimi_page, _exists(wimi_page, remove)), "the modal never drew the row"
    assert wimi_page.eval_js(_exists(wimi_page, delete)) is False, (
        "4b: Delete for good was offered while another exam lists the type")
    assert wimi_page.eval_js(
        f"document.querySelector(\"[data-testid='{shared}']\").textContent"
    ) == "Also on 1 other exam"

    # ---- Act: B stops offering it ----------------------------------------
    db.remove_tag_from_exam(B, ids["memory"])
    db.conn.commit()
    wimi_page.eval_js("closeManageTagsModal()")
    wimi_page.eval_js("openManageTagsModal()")

    # ---- Assert: now it is offered, and counts every exam's entries ------
    assert poll(wimi_page, _exists(wimi_page, delete)), (
        "4b: Delete for good never appeared once no other exam listed the type")
    assert wimi_page.eval_js(_exists(wimi_page, shared)) is False
    # `renderManageTagsModal` calls `container.replaceChildren()`, so a
    # re-render DESTROYS this button and builds a new one. Polling for the row
    # only proves some render finished, and a synthetic click landing across a
    # later re-render is dropped. Wait until the same node has survived
    # unreplaced; the stamp is lost with the node, so this measures identity
    # rather than existence (#925). Measured natively at 1130x689: polling for
    # the row alone gave 5 of 12, this gives 10 of 10.
    assert poll(wimi_page, f"""(() => {{
        const n = document.querySelector("[data-testid='{delete}']");
        if (!n) return false;
        if (!n.__settledAt) {{ n.__settledAt = performance.now(); return false; }}
        return performance.now() - n.__settledAt > 400;
    }})()"""), "the Manage Error Types list never stopped re-rendering"
    wimi_page.locator(testid=delete).click()
    assert poll(wimi_page, "document.getElementById('delete-tag-modal')"
                           ".classList.contains('active')"), "no confirmation opened"
    detail = wimi_page.eval_js(
        "document.querySelector('[data-testid=\"delete-tag-modal-usage\"]').textContent")
    assert detail.startswith("This removes it from 1 entry in every exam"), detail
    wimi_page.locator(testid="delete-tag-modal-confirm").click()

    assert poll(wimi_page, f"!({_exists(wimi_page, remove)})"), (
        "the deleted type is still in the modal")
    assert db.fetchone("SELECT 1 FROM tags WHERE id = ?", (ids["memory"],)) is None
    assert db.fetchone("SELECT 1 FROM entry_tags WHERE question_entry_id = ?",
                       (ids["entry"],)) is None, (
        "Delete for good must take the type off B's entry too")
