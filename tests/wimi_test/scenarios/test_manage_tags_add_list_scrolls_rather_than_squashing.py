"""Regression: "Add from your other exams" scrolls instead of squashing (#927).

``.manage-tags-add-list`` is the second list in the Manage Error Types modal,
and it has #925's shape exactly: a column flex container with
``max-height: 14rem`` and ``overflow-y: auto`` whose children,
``.manage-tag-add-group``, carry ``overflow: hidden`` for their rounded
corners and were left at the default ``flex-shrink: 1``. So each group shrank
to fit and clipped its own rows, and the list reported
``scrollHeight == clientHeight`` and drew no scrollbar.

#927's candidate table said this list's children were flat type rows that
would overlap visibly rather than clip. Rendered, they are groups, and the
clipping is silent. Measured on master ``6128a1d`` plus #925's branch (whose
line styles the OTHER list) with the five default
groups offered to an exam that lists none of them: 929 px of groups in 224 px,
all five clipped, ``scrollHeight`` 224.

Of #927's nine candidates this is the only one affected; the other eight have
children with ``overflow: visible``, whose ``min-height: auto`` stops them
shrinking below their content.

Fails without ``flex-shrink: 0`` on ``.manage-tag-add-group``; passes with it.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

MEASURE = """(() => {
    const list = document.getElementById('manage-tags-add-list');
    const groups = Array.from(list.children);
    let natural = 0;
    groups.forEach(g => { natural += g.scrollHeight; });
    return JSON.stringify({
        groups: groups.length,
        clipped: groups.filter(g => g.scrollHeight > g.clientHeight + 2).length,
        natural: natural,
        clientHeight: list.clientHeight,
        scrollHeight: list.scrollHeight,
    });
})()"""


@pytest.mark.slow
@pytest.mark.regression
def test_the_add_list_scrolls_and_no_group_clips_its_own_rows(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    # The defaults live in the library through another exam ...
    db.create_exam_context(exam_name="Squash 927 other")
    db.seed_default_tags("Squash 927 other")
    # ... and this exam lists none of them. Marking it seeded stops the entry
    # form's seed from giving it the defaults, so all five groups are offered
    # under "Add from your other exams".
    exam = db.create_exam_context(exam_name="Squash 927")
    db.conn.execute(
        "INSERT INTO exam_error_types_seeded (exam_context_id) VALUES (?)", (exam.id,))
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=3, total_incorrect=2,
        session_name="Squash 927 session", date_encountered=date.today())
    db.conn.commit()

    wimi_page.goto("entry-form", query={"session_id": session.id})
    wait_for_form_ready(wimi_page)
    wimi_page.eval_js("openManageTagsModal()")
    assert poll(wimi_page, "!!document.getElementById('manage-tags-add-list')"
                           " && document.getElementById('manage-tags-add-list').children.length > 0")
    assert poll(wimi_page, "(() => { const l = document.getElementById('manage-tags-add-list');"
                           " return l.scrollHeight > 0; })()")
    wimi_page.wait_for_timeout(300)
    seen = json.loads(wimi_page.eval_js(MEASURE))

    # The fixture must offer more than the list's max-height, or this passes
    # vacuously.
    assert seen["natural"] > seen["clientHeight"], seen

    assert seen["clipped"] == 0, (
        f"{seen['clipped']} of {seen['groups']} groups clip their own rows; "
        f"a group must keep its natural height and let the list scroll: {seen}")
    assert seen["scrollHeight"] > seen["clientHeight"] + 2, (
        "the list reports no overflow, so it offers no scrollbar while holding "
        f"{seen['natural']} px of groups in {seen['clientHeight']} px: {seen}")
