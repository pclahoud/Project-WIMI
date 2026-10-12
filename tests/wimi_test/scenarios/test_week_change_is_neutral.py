"""Regression: the week-on-week change is a neutral signed number (#470).

Owner's decision, 2026-10-07. "This Week" counts logged entries -- the
activity the Weekly Goal and the streak reward -- while Patterns & Insights
reads more mistakes as a concern. The analytics dashboard's badge painted
"+10" green with an up arrow and Insights called the same change a concern;
"-8" lost its minus and showed "8" beside a red down arrow. The dashboard's
Quick Analytics card had the same polarity, which the issue did not name.

Now both show a plain signed number with no colour and no arrow. Asserted
**rendered**: the badge's computed colour equals its unstyled baseline (the
colour it inherits), and its ``::before`` carries no content -- so a colour
or arrow coming back through any selector fails here, not only through the
old class names.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

MINUS = '−'

DASHBOARD_BADGE = """
(() => {
  const el = document.getElementById('weekChange');
  if (!el || !el.textContent.trim()) return null;
  const parent = el.parentElement;
  return JSON.stringify({
    text: el.textContent.trim(),
    color: getComputedStyle(el).color,
    parent_color: getComputedStyle(parent).color,
    value_color: getComputedStyle(parent.querySelector('.value') || parent).color,
    before: getComputedStyle(el, '::before').content,
    classes: el.className,
  });
})()
"""

PREVIEW_BADGE = """
(() => {
  const el = document.querySelector('.preview-stat-trend');
  if (!el) return null;
  return JSON.stringify({
    text: el.textContent.trim(),
    color: getComputedStyle(el).color,
    parent_color: getComputedStyle(el.parentElement).color,
    before: getComputedStyle(el, '::before').content,
    classes: el.className,
  });
})()
"""


def _seed(db, this_week: int, last_week: int) -> int:
    exam = db.create_exam_context(exam_name='Week Exam', exam_description='#470')
    subject = db.create_subject_node(exam.exam_name, 'Cardiovascular', 'System')
    for count, when in ((this_week, date.today()),
                        (last_week, date.today() - timedelta(days=10))):
        if not count:
            continue
        session = db.create_review_session(
            exam_context_id=exam.id, total_questions=count,
            total_incorrect=count, session_name=f'{when}', date_encountered=when)
        for _ in range(count):
            db.create_question_entry(session.id, 'a', 'b',
                                     primary_subject_ids=[subject.id])
    db.conn.commit()
    return exam.id


def _dashboard_badge(page: WimiPage) -> dict:
    page.goto('analytics')
    assert poll(page, '(%s) !== null' % DASHBOARD_BADGE.strip(), timeout_ms=20000), (
        'the This Week change badge never rendered')
    page.wait_for_timeout(300)   # let any colour transition settle
    return json.loads(page.eval_js(DASHBOARD_BADGE))


def _preview_badge(page: WimiPage) -> dict:
    page.goto('dashboard')
    assert poll(page, '(%s) !== null' % PREVIEW_BADGE.strip(), timeout_ms=20000), (
        'the Quick Analytics This Week trend never rendered')
    page.wait_for_timeout(300)
    return json.loads(page.eval_js(PREVIEW_BADGE))


def _assert_neutral(badge: dict, where: str) -> None:
    assert badge['before'] in ('none', 'normal', ''), (
        f'{where}: the change still draws an arrow ({badge["before"]!r})')
    assert badge['color'] == badge['parent_color'], (
        f'{where}: the change is coloured {badge["color"]} against its '
        f'container\'s {badge["parent_color"]} -- it must side with neither '
        f'"more is good" nor "fewer is good" (#470)')
    assert 'positive' not in badge['classes'] and 'negative' not in badge['classes']


@pytest.mark.slow
@pytest.mark.regression
def test_more_than_last_week_is_neutral(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _seed(wimi_session.user.db, this_week=10, last_week=0)

    dash = _dashboard_badge(wimi_page)
    assert dash['text'] == '+10 vs last week', dash
    _assert_neutral(dash, 'analytics dashboard')

    preview = _preview_badge(wimi_page)
    assert preview['text'] == '+10 vs last', preview
    _assert_neutral(preview, 'Quick Analytics')


@pytest.mark.slow
@pytest.mark.regression
def test_fewer_than_last_week_is_neutral_and_keeps_its_minus(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _seed(wimi_session.user.db, this_week=2, last_week=10)

    dash = _dashboard_badge(wimi_page)
    assert dash['text'] == f'{MINUS}8 vs last week', (
        f'the decrease must carry its sign: {dash}')
    _assert_neutral(dash, 'analytics dashboard')

    preview = _preview_badge(wimi_page)
    assert preview['text'] == f'{MINUS}8 vs last', preview
    _assert_neutral(preview, 'Quick Analytics')
