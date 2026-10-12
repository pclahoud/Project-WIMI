"""Issue #531 - the rendered streak surfaces agree when today has a session but no entry.

Owner's decision, 2026-10-07: a study day is a day with at least one entry.

Fixture: entries yesterday and the day before, and a review session dated
today with nothing logged. Every streak surface must read **2 days, at
risk**:

* the analytics dashboard's Current Streak card (heatmap payload,
  ``_calculate_streak_info``),
* its Patterns & Insights list (``get_study_streak``), which must carry the
  "2-day streak at risk!" card -- before #531 it counted today's empty
  session, saw a safe 3-day streak and said nothing,
* Quick Analytics' STREAK stat on the home dashboard (``getStreakInfo``).

Dates are written by Python's local ``date.today()``, the same clock the
backend reads, so the fixture's "today" is the backend's today (#286).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]


def _seed(db) -> int:
    exam = db.create_exam_context(exam_name='W531 Exam', exam_description='')
    today = date.today()
    for back, n in ((2, 1), (1, 2), (0, 0)):
        s = db.create_review_session(
            exam_context_id=exam.id, total_questions=max(n, 1), total_incorrect=n,
            session_name=f'W531 {back}', date_encountered=today - timedelta(days=back),
        )
        for _ in range(n):
            db.create_question_entry(
                review_session_id=s.id, user_answer='A', correct_answer='B',
            )
    db.conn.commit()
    return exam.id


DASHBOARD = """
(() => ({
  streak: document.querySelector('#streakStats .streak-card.current .streak-value')?.textContent.trim() ?? null,
  titles: [...document.querySelectorAll('#insightsContainer .insight-title')].map(e => e.textContent.trim()),
  actions: [...document.querySelectorAll('#insightsContainer .insight-action')].map(e => e.textContent.trim()),
}))()
"""

PREVIEW = """
(() => {
  const stat = [...document.querySelectorAll('.preview-stat')]
    .find(s => s.querySelector('.preview-stat-label')?.textContent.trim() === 'Streak');
  return stat ? {
    value: stat.querySelector('.preview-stat-value').textContent.replace(/\\D+/g, ''),
    warning: stat.querySelector('.preview-stat-warning')?.textContent.trim() ?? null,
  } : null;
})()
"""


def test_every_rendered_streak_says_two_days_at_risk(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    exam_id = _seed(wimi_session.user.db)

    wimi_page.goto('analytics', query={'exam': exam_id})
    assert poll(
        wimi_page,
        "!!document.querySelector('#streakStats .streak-card.current') && "
        "document.querySelectorAll('#insightsContainer .insight-card').length > 0",
    ), 'the streak card or the insights list never rendered'
    dash = wimi_page.eval_js(DASHBOARD)

    assert dash['streak'] is not None and dash['streak'].split()[0] == '2', dash
    assert '2-day streak at risk!' in dash['titles'], (
        f'Patterns & Insights shows {dash["titles"]}; with entries yesterday and '
        f'the day before and an empty session today the streak is 2 days and at '
        f'risk. #531: get_study_streak counted the empty session as a study day.'
    )
    risk_action = dash['actions'][dash['titles'].index('2-day streak at risk!')]
    assert 'session' not in risk_action.lower(), risk_action

    wimi_page.goto('dashboard')
    assert poll(
        wimi_page,
        "[...document.querySelectorAll('.preview-stat-label')]"
        ".some(e => e.textContent.trim() === 'Streak')",
    ), 'Quick Analytics never drew its STREAK stat'
    # Quick Analytics follows the exam its own selector holds; read which.
    preview = wimi_page.eval_js(PREVIEW)
    assert preview == {'value': '2', 'warning': 'At risk!'}, (
        f'Quick Analytics STREAK reads {preview}; expected 2 days, at risk'
    )
