"""Issue #478 - the Current Streak card could never say "At risk!".

``loadActivityHeatmap`` handed ``StreakDisplay`` a hardcoded
``streak_at_risk: false``, so the card's one actionable line -- *"At risk!
Log an entry today"* -- was unreachable on the analytics dashboard, while
the Patterns & Insights card on the same page and the landing page's Quick
Analytics both warned from the real value.

The value already existed: ``_calculate_streak_info`` computes it (active
yesterday, nothing yet today, streak > 0) and ``get_activity_heatmap``
called it and dropped the key. The fix forwards it; nothing here defines
"at risk" anew. The oracle below is that same backend method, read from
the seeded database, so the card is asserted to *agree with the backend*
rather than with a definition written into the test.

Both directions are asserted: a test that only checked the warning appears
would pass against a card hardcoded the other way.

The same issue noted ``1 days``; the second test pins the singular.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

CARD = """
(() => {
  const card = document.querySelector('#streakStats .streak-card.current');
  if (!card) return null;
  const longest = document.querySelector('#streakStats .streak-card.longest');
  return {
    cls: card.className,
    text: card.textContent.replace(/\\s+/g, ' ').trim(),
    value: card.querySelector('.streak-value').textContent.replace(/\\s+/g, ' ').trim(),
    longest: longest ? longest.querySelector('.streak-value').textContent
      .replace(/\\s+/g, ' ').trim() : null,
    warning: !!card.querySelector('.streak-warning'),
  };
})()
"""


def _seed(db, days_ago: list[int]) -> int:
    """One entry on each of the given days before today (0 = today)."""
    exam = db.create_exam_context(exam_name='W478 Exam', exam_description='')
    subject = db.create_subject_node(
        exam_context=exam.exam_name, name='W478 Topic', level_type='Topic',
        exam_weight_low=10, exam_weight_high=10,
    )
    for n in days_ago:
        session = db.create_review_session(
            exam_context_id=exam.id, total_questions=5, total_incorrect=1,
            session_name=f'W478 day -{n}',
            date_encountered=date.today() - timedelta(days=n),
        )
        db.create_question_entry(
            review_session_id=session.id, user_answer='A', correct_answer='B',
            perceived_difficulty=3, reflection='r', explanation='e',
            primary_subject_ids=[subject.id],
        )
    db.conn.commit()
    return exam.id


def _read_card(page: WimiPage, exam_id: int) -> dict:
    page.goto('analytics', query={'exam': exam_id})
    assert poll(page, "!!document.querySelector('#streakStats .streak-card.current')"), (
        'the Current Streak card never rendered'
    )
    return page.eval_js(CARD)


@pytest.mark.parametrize('days_ago, expect_risk', [
    pytest.param([1, 2], True, id='active-yesterday-not-today'),
    pytest.param([0, 1], False, id='active-today'),
])
def test_the_card_carries_the_backends_at_risk_flag(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
    days_ago: list[int], expect_risk: bool,
) -> None:
    # ---- Arrange ----------------------------------------------------------
    db = wimi_session.user.db
    exam_id = _seed(db, days_ago)
    backend = db.get_streak_info(exam_id)
    # The precondition, from the backend's own definition: without it this
    # test would be asserting a seed, not the page.
    assert backend['streak_at_risk'] is expect_risk, backend
    assert backend['current_streak'] == 2, backend

    # ---- Act --------------------------------------------------------------
    card = _read_card(wimi_page, exam_id)

    # ---- Assert -----------------------------------------------------------
    assert card['value'].startswith('2'), (
        f'the card did not load the seeded streak: {card!r}'
    )
    assert card['warning'] is expect_risk, (
        f'_calculate_streak_info says streak_at_risk={expect_risk} and the '
        f'Current Streak card {"omits" if expect_risk else "shows"} the '
        f'warning: {card["text"]!r}. #478: the dashboard hardcoded the flag '
        f'instead of reading the one get_activity_heatmap already computes.'
    )
    assert ('at-risk' in card['cls'].split()) is expect_risk, card
    if expect_risk:
        assert 'At risk! Log an entry today' in card['text'], card


def test_a_one_day_streak_reads_day_not_days(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    exam_id = _seed(wimi_session.user.db, [0])

    card = _read_card(wimi_page, exam_id)

    assert card['value'] == '1 day', (
        f'a one-day streak reads {card["value"]!r} (#478: "1 days")'
    )
    assert card['longest'] == '1 day', (
        f'a one-day longest streak reads {card["longest"]!r}'
    )
