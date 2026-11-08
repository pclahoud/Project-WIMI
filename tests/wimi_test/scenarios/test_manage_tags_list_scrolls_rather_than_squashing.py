"""Regression: the Manage Error Types list scrolls instead of squashing (#925).

``.manage-tags-list`` is a column flex container with ``max-height: 26rem``
and ``overflow-y: auto``, so its groups are meant to keep their natural height
and let the LIST scroll. They did not: a ``.manage-tag-group`` is a flex item
and ``flex-shrink`` defaults to 1, so each group shrank to fit and then
clipped its own rows against the ``overflow: hidden`` it carries for its
rounded corners.

Measured on master ``e63edf3`` at 1130x689 with the five default groups:
2790 px of content compressed into 416 px, all five groups clipped, and the
list reporting ``scrollHeight == clientHeight`` so it never offered a
scrollbar. A student could neither see nor reach most of their error types,
and a group's header painted over the row beneath it -- which is what made
that row's *Delete for good* unclickable.

Fails on ``e63edf3``; passes with ``flex-shrink: 0`` on the group.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

MEASURE = """(() => {
    const list = document.getElementById('manage-tags-list');
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
def test_the_list_scrolls_and_no_group_clips_its_own_rows(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Squash 925")
    db.seed_default_tags("Squash 925")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=3, total_incorrect=2,
        session_name="Squash 925 session", date_encountered=date.today())
    db.conn.commit()

    wimi_page.goto("entry-form", query={"session_id": session.id})
    wait_for_form_ready(wimi_page)
    wimi_page.eval_js("openManageTagsModal()")
    assert poll(wimi_page, "!!document.getElementById('manage-tags-list')"
                           " && document.getElementById('manage-tags-list').children.length > 0")
    # The groups render from a bridge read; let the list settle before measuring.
    assert poll(wimi_page, "(() => { const l = document.getElementById('manage-tags-list');"
                           " return l.scrollHeight > 0; })()")
    wimi_page.wait_for_timeout(300)
    seen = json.loads(wimi_page.eval_js(MEASURE))

    # The fixture seeds more content than the list's max-height, which is what
    # makes this measurable at all. Without it the test would pass vacuously.
    assert seen["natural"] > seen["clientHeight"], seen

    assert seen["clipped"] == 0, (
        f"{seen['clipped']} of {seen['groups']} groups clip their own rows; "
        f"a group must keep its natural height and let the list scroll: {seen}")
    assert seen["scrollHeight"] > seen["clientHeight"] + 2, (
        "the list reports no overflow, so it offers no scrollbar while holding "
        f"{seen['natural']} px of groups in {seen['clientHeight']} px: {seen}")
