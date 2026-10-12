"""Regression: the deep dive names the student's own day (#534).

``renderRecentEntries`` built each row's date with ``new Date(entry.date_encountered)``
and ``getDaysAgo`` parsed ``last_mistake_date`` the same way. A bare
``YYYY-MM-DD`` is specified to parse as **UTC** midnight, so west of Greenwich
both named the previous day -- #471's defect on the heatmap, in a second file.

The Recent Entries half is deterministic: under ``Pacific/Pago_Pago`` (UTC-11,
DST-free) the old parse names the day before **at every hour**, so a fixed
date fails the old code whenever this runs. ``Pacific/Kiritimati`` (UTC+14) is
the east-side control, where the old parse happened to be right and the fix
must not break it. The "Last Mistake" half is asserted too, but note its limit:
under the old code it read "Yesterday" for a mistake logged yesterday only
until 13:00 local and "2 days ago" after, so that assertion catches the defect
for part of the day, not all of it. The sweep in ``tests/test_web_local_date.py``
is what holds the form out at every hour.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FIXED_DAY = date(2026, 6, 15)          # a Monday; reads "Jun 15"
FIXED_LABEL = 'Jun 15'


def _seed(db, days) -> tuple[int, int]:
    exam = db.create_exam_context(exam_name='Local Day Exam', exam_description='#534')
    subject = db.create_subject_node(exam.exam_name, 'Cardiovascular', 'System')
    for day in days:
        session = db.create_review_session(
            exam_context_id=exam.id, total_questions=1, total_incorrect=1,
            session_name=str(day), date_encountered=day)
        db.create_question_entry(session.id, 'a', 'b', reflection='<p>x</p>',
                                 primary_subject_ids=[subject.id])
    db.conn.commit()
    return subject.id, exam.id


def _open(page: WimiPage, zone: str, subject_id: int, exam_id: int) -> dict:
    # The override survives navigation, so it goes on BEFORE the page reads
    # the clock (CLAUDE.md, #286).
    page.tab._tab.Emulation.setTimezoneOverride(timezoneId=zone)
    page.goto('subject-deep-dive', query={'subject': subject_id, 'exam': exam_id})
    assert poll(page, "!!document.querySelector('.recent-entry-date')"
                      " && document.getElementById('lastMistake').textContent !== '-'",
                timeout_ms=20000), 'the deep dive never drew its dates'
    offset = page.eval_js('new Date().getTimezoneOffset()')
    return {
        'offset': offset,
        'dates': page.eval_js(
            "JSON.stringify(Array.from(document.querySelectorAll('.recent-entry-date'))"
            ".map(e => e.textContent))"),
        'last': page.eval_js("document.getElementById('lastMistake').textContent"),
    }


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize('zone, expected_offset', [
    pytest.param('Pacific/Pago_Pago', 660, id='west-UTC-11'),
    pytest.param('Pacific/Kiritimati', -840, id='east-UTC+14'),
])
def test_a_recent_entry_shows_the_day_it_was_logged(
    wimi_session: WimiTestSession, wimi_page: WimiPage, zone: str,
    expected_offset: int,
) -> None:
    subject_id, exam_id = _seed(wimi_session.user.db, [FIXED_DAY])

    state = _open(wimi_page, zone, subject_id, exam_id)

    assert state['offset'] == expected_offset, (
        f'the timezone override did not take ({state["offset"]}), so this '
        f'would measure the host zone instead')
    assert state['dates'] == f'["{FIXED_LABEL}"]', (
        f'under {zone} the row reads {state["dates"]} for an entry logged on '
        f'{FIXED_DAY} -- a date-only string parsed as UTC (#534)')


@pytest.mark.slow
@pytest.mark.regression
def test_last_mistake_counts_local_days(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    zone = 'Pacific/Pago_Pago'
    yesterday = datetime.now(ZoneInfo(zone)).date() - timedelta(days=1)
    subject_id, exam_id = _seed(wimi_session.user.db, [yesterday])

    state = _open(wimi_page, zone, subject_id, exam_id)

    assert state['last'] == 'Yesterday', (
        f'a mistake logged on {yesterday} (yesterday in {zone}) reads '
        f'{state["last"]!r}')
