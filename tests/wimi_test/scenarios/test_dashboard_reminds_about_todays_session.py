"""The dashboard reminds the student about a session planned for today or
missed, once per launch, and says nothing when there is nothing to say
(#778 Wave 3, owner decision 7).

Three scenarios. The positive case seeds a plan for today and one missed
plan and asserts the notice is revealed with both named, its Start link
carrying the plan's id, and that Dismiss hides it and keeps it hidden on
the next dashboard load in the same launch (bridge state, not a column).
The control seeds only a future plan and asserts the notice stays hidden,
which is what makes the positive case evidence: reveal-after-read means a
failed read also shows nothing.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

NOTICE = "document.getElementById('session-reminder-notice')"


def _wait_dashboard(page: WimiPage) -> None:
    for _ in range(300):
        if page.eval_js("typeof window.api === 'object' && !!document.getElementById('exams-grid')"):
            return
        page.wait_for_timeout(100)
    raise AssertionError("the dashboard never loaded")


def _wait_notice(page: WimiPage, *, visible: bool) -> None:
    for _ in range(60):
        hidden = page.eval_js(NOTICE + ".hidden")
        if hidden is (not visible):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"the reminder notice did not become {'visible' if visible else 'hidden'}")


@pytest.mark.slow
@pytest.mark.regression
def test_a_plan_for_today_and_a_missed_plan_are_announced_then_dismissed(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Reminder Exam")
    today = date.today()
    plan = db.create_planned_session(today, exam_context_id=exam.id, title="Morning cardio", planned_start_time="09:00")
    db.create_planned_session(today - timedelta(days=3), exam_context_id=exam.id, title="Missed renal")

    wimi_page.goto("dashboard")
    _wait_dashboard(wimi_page)
    _wait_notice(wimi_page, visible=True)

    text = wimi_page.eval_js("document.getElementById('session-reminder-text').textContent")
    assert "Morning cardio" in text and "today" in text and "09:00" in text, text
    assert "Missed renal" in text and (today - timedelta(days=3)).isoformat() in text, text
    href = wimi_page.eval_js("document.getElementById('session-reminder-start').getAttribute('href')")
    assert href == f"session_setup.html?planned_id={plan['id']}&exam_id={exam.id}", href

    wimi_page.eval_js("document.getElementById('session-reminder-dismiss').click()")
    _wait_notice(wimi_page, visible=False)

    # Same launch, next dashboard load: still dismissed, and nothing was stored.
    marker = "window.__reminder_mark = true"
    wimi_page.eval_js(marker)
    wimi_page.goto("dashboard")
    for _ in range(100):
        if not wimi_page.eval_js("!!window.__reminder_mark"):
            break
        wimi_page.wait_for_timeout(50)
    _wait_dashboard(wimi_page)
    wimi_page.wait_for_timeout(500)
    assert wimi_page.eval_js(NOTICE + ".hidden") is True
    assert db.fetchone("SELECT status FROM planned_sessions WHERE id = ?", (plan["id"],))["status"] == "planned"


@pytest.mark.slow
@pytest.mark.regression
def test_a_future_plan_alone_shows_nothing(wimi_session: WimiTestSession, wimi_page: WimiPage) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Quiet Exam")
    db.create_planned_session(date.today() + timedelta(days=5), exam_context_id=exam.id, title="Later")

    wimi_page.goto("dashboard")
    _wait_dashboard(wimi_page)
    # Give the module time to have answered; a revealed notice would be wrong.
    wimi_page.wait_for_timeout(800)
    assert wimi_page.eval_js(NOTICE + ".hidden") is True
    assert wimi_page.eval_js("document.getElementById('session-reminder-text').textContent") == ""
