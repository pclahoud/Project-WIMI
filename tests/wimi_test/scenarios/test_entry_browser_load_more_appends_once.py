"""Regression: Load More appends exactly the page it fetched (#467).

``renderEntries`` sliced the accumulated array from ``length - perPage``,
which assumes the page just appended was full. The last page usually is not:
with 14 entries at 10 per page, one press left **20 cards for 14 entries** --
entries drawn twice -- under a footer reading *Showing 1-14 of 14 entries*.

Measured through a real, hit-tested click on the button, and counted two ways
(cards, and distinct ``data-entry-id``) so a duplicate cannot hide inside a
matching total. The full-last-page case is the control: the old arithmetic
was right there, so it must stay right.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import centre_of, poll, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PER_PAGE = 10

GRID = """
(() => {
  const cards = Array.from(document.querySelectorAll('.entry-card'));
  const ids = cards.map(c => c.dataset.entryId);
  const btn = document.getElementById('loadMoreBtn');
  return JSON.stringify({
    cards: cards.length,
    distinct: new Set(ids).size,
    load_more_visible: !!btn && btn.offsetParent !== null,
    footer: (document.querySelector('[data-testid="browser-pagination-info"]')
             || document.getElementById('paginationInfo') || {}).textContent || '',
  });
})()
"""


def _seed(db, entries: int) -> None:
    exam = db.create_exam_context(exam_name='Paging Exam', exam_description='#467')
    subject = db.create_subject_node(exam.exam_name, 'Cardiovascular', 'System')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=entries,
        total_incorrect=entries, session_name='Paging session',
        date_encountered=date.today())
    for _ in range(entries):
        db.create_question_entry(session.id, 'a', 'b',
                                 primary_subject_ids=[subject.id])
    db.update_preferences(entry_review_items_per_page=PER_PAGE)
    db.conn.commit()


def _grid(page: WimiPage) -> dict:
    return json.loads(page.eval_js(GRID))


def _press_load_more(page: WimiPage, entries: int) -> dict:
    page.goto('entry-browser')
    assert poll(page, "document.querySelectorAll('.entry-card').length === %d"
                % PER_PAGE, timeout_ms=20000), (
        f'the first page never drew {PER_PAGE} cards: {_grid(page)}')
    first = _grid(page)
    assert first['load_more_visible'], f'no Load More button to press: {first}'

    real_click(page, centre_of(page, '#loadMoreBtn'))
    assert poll(page, "document.querySelectorAll('.entry-card').length >= %d"
                % entries, timeout_ms=20000), f'Load More drew nothing: {_grid(page)}'
    page.wait_for_timeout(300)   # let any late extra cards land before counting
    return _grid(page)


@pytest.mark.slow
@pytest.mark.regression
def test_a_short_last_page_adds_only_its_own_cards(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _seed(wimi_session.user.db, entries=14)

    after = _press_load_more(wimi_page, 14)

    assert after['distinct'] == 14, after
    assert after['cards'] == 14, (
        f"{after['cards']} cards for 14 entries after one Load More: the "
        f"short last page was appended as if it were full (#467). {after}")


@pytest.mark.slow
@pytest.mark.regression
def test_a_full_last_page_is_unchanged(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    """Control: the case the old arithmetic already got right."""
    _seed(wimi_session.user.db, entries=20)

    after = _press_load_more(wimi_page, 20)

    assert after['cards'] == after['distinct'] == 20, after
