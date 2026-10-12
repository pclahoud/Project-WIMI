"""Regression: the search filter chip renders the student's text as TEXT (#324).

``updateActiveFilters`` built each chip with ``innerHTML`` and interpolated
``chip.label`` -- the student's own search text, ``Search: "<query>"`` --
unescaped, so markup typed into the search box became markup in the page and
an ``onerror`` handler ran. A ``field:"value"`` search reaches the same chip
through ``fieldFilters`` and is checked too.

The query is TYPED (focus, then ``Input.insertText``), the way a student
enters it, so the input's own debounce and ``parseSearchQuery`` are on the
path. The assertion has two halves: the payload did not execute, and the chip
shows the text the student typed, character for character -- escaping that
mangled the text would pass the first half and fail the second.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import centre_of, poll, real_click, real_type
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PAYLOAD = '<img src=x onerror="window.__chip_xss=1">'

CHIPS = """
(() => JSON.stringify({
  fired: window.__chip_xss === 1,
  imgs: document.querySelectorAll('#filterChips img, .filter-chip img').length,
  chips: Array.from(document.querySelectorAll('.filter-chip')).map(c =>
      c.childNodes[0] ? c.childNodes[0].textContent.trim() : ''),
}))()
"""


def _seed(db) -> None:
    exam = db.create_exam_context(exam_name='Chip Exam', exam_description='#324')
    subject = db.create_subject_node(exam.exam_name, 'Cardiovascular', 'System')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='Chip session', date_encountered=date.today())
    db.create_question_entry(session.id, 'a', 'b', primary_subject_ids=[subject.id])
    db.conn.commit()


def _search(page: WimiPage, text: str) -> dict:
    page.goto('entry-browser')
    assert poll(page, "document.querySelectorAll('.entry-card').length === 1",
                timeout_ms=20000), 'the browser never drew its entry'
    real_click(page, centre_of(page, '#searchInput'))
    real_type(page, text)
    assert poll(page, "document.querySelectorAll('.filter-chip').length > 0",
                timeout_ms=10000), 'no filter chip appeared for the search'
    page.wait_for_timeout(300)   # an onerror on a broken <img> fires async
    return json.loads(page.eval_js(CHIPS))


@pytest.mark.slow
@pytest.mark.regression
def test_a_search_term_is_shown_not_executed(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _seed(wimi_session.user.db)

    state = _search(wimi_page, PAYLOAD)

    assert not state['fired'], 'the search text executed as markup (#324)'
    assert state['imgs'] == 0, state
    assert f'Search: "{PAYLOAD}"' in state['chips'], (
        f'the chip does not show what was typed: {state["chips"]}')


@pytest.mark.slow
@pytest.mark.regression
def test_a_field_search_value_is_shown_not_executed(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _seed(wimi_session.user.db)

    state = _search(wimi_page, f'notes:"{PAYLOAD.replace(chr(34), chr(39))}"')

    assert not state['fired'], 'a field-search value executed as markup (#324)'
    assert state['imgs'] == 0, state
