"""Issue #530 - the This Week card counts the last seven days, against the seven before.

One entry today, one exactly seven days ago, one exactly fourteen days ago.
The manual's windows (today-6..today against today-13..today-7) put one in
each of the first two and the third in neither, so This Week reads 1 and
the change badge is empty (no change). Before the fix This Week covered
eight days and read 2, with a "+1" badge.

Both renderings of the figure are read: the analytics dashboard's This Week
card with its badge, and Quick Analytics' THIS WEEK stat on the home
dashboard, which computes ``this_week - last_week`` itself from the same
overview payload.

Dates are written by Python's local ``date.today()``, the clock the backend
compares against (#286), so the boundary days are the backend's own.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]


def _seed(db) -> int:
    exam = db.create_exam_context(exam_name='W530 Exam', exam_description='')
    today = date.today()
    for back in (0, 7, 14):
        s = db.create_review_session(
            exam_context_id=exam.id, total_questions=1, total_incorrect=1,
            session_name=f'W530 {back}', date_encountered=today - timedelta(days=back),
        )
        db.create_question_entry(
            review_session_id=s.id, user_answer='A', correct_answer='B',
        )
    db.conn.commit()
    return exam.id


PREVIEW = """
(() => {
  const stat = [...document.querySelectorAll('.preview-stat')]
    .find(s => s.querySelector('.preview-stat-label')?.textContent.trim() === 'This Week');
  return stat ? {
    value: stat.querySelector('.preview-stat-value').textContent.trim(),
    trend: stat.querySelector('.preview-stat-trend')?.textContent.trim() ?? null,
  } : null;
})()
"""


def test_this_week_is_seven_days_on_both_surfaces(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    exam_id = _seed(wimi_session.user.db)

    wimi_page.goto('analytics', query={'exam': exam_id})
    # Total Entries is the positive control that the overview loaded at all.
    assert poll(
        wimi_page, "document.getElementById('totalEntries')?.textContent.trim() === '3'",
    ), 'the overview never loaded the three seeded entries'
    card = wimi_page.eval_js(
        "({value: document.querySelector('#thisWeek .value').textContent.trim(),"
        " badge: document.getElementById('weekChange').textContent.trim()})"
    )
    assert card == {'value': '1', 'badge': ''}, (
        f'This Week card reads {card}; with entries today, 7 and 14 days ago the '
        f'last seven days hold one and the seven before hold one. #530: the '
        f'window was eight days, so the entry from 7 days ago counted as this week.'
    )

    wimi_page.goto('dashboard')
    assert poll(
        wimi_page,
        "[...document.querySelectorAll('.preview-stat-label')]"
        ".some(e => e.textContent.trim() === 'This Week')",
    ), 'Quick Analytics never drew its THIS WEEK stat'
    preview = wimi_page.eval_js(PREVIEW)
    assert preview == {'value': '1', 'trend': None}, (
        f'Quick Analytics THIS WEEK reads {preview}; expected 1 with no trend'
    )
