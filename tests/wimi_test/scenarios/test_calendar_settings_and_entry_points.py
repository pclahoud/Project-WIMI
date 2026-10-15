"""Settings -> Calendar takes effect on the calendar page, and both entry
points resolve to it (#778 Wave 4, decisions 8 and 12).

Saving Month as the default view in Settings makes the calendar open in
month view; unticking weekends hides the Saturday and Sunday columns. The
dashboard's exam-section link and the session-setup header link both carry
the student to the calendar route.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_READY = (
    "(() => { const g = document.querySelector('[data-page-gated]');"
    " return !!g && !g.hasAttribute('inert') && !!window.CalendarState"
    " && window.CalendarState.isLoading === false; })()"
)


def _wait(page: WimiPage, expr: str, *, what: str, tries: int = 300) -> None:
    for _ in range(tries):
        if page.eval_js(expr):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.mark.slow
@pytest.mark.regression
def test_the_settings_panel_drives_the_default_view_and_the_weekend_columns(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db.create_exam_context(exam_name="Prefs Exam")
    # Seed the preference the way the page's Save does, then read the calendar.
    db.update_settings(calendar_default_view="month", show_weekend_in_calendar=False)

    wimi_page.goto("calendar")
    _wait(wimi_page, _READY, what="the calendar gate to release")
    assert wimi_page.eval_js("window.CalendarState.view") == "month"
    assert wimi_page.eval_js("document.getElementById('cal-view-month').checked") is True
    weekend_headers = wimi_page.eval_js(
        "[...document.querySelectorAll('#cal-grid th.cal-weekend')].map(th => th.hidden)")
    assert weekend_headers and all(weekend_headers), weekend_headers
    visible_cols = wimi_page.eval_js(
        "[...document.querySelectorAll('#cal-grid thead th')].filter(th => !th.hidden).length")
    assert visible_cols == 5

    # The Settings panel itself is live and shows the stored values.
    wimi_page.goto("settings")
    _wait(wimi_page, "!!document.getElementById('calendar_default_view') && document.getElementById('calendar_default_view').value === 'month'",
          what="the Settings calendar panel to populate")
    assert wimi_page.eval_js("document.getElementById('calendar_default_view').disabled") is False
    assert wimi_page.eval_js("document.getElementById('show_weekend_in_calendar').checked") is False
    assert wimi_page.eval_js("!!document.querySelector('[data-panel=\"calendar\"] .coming-soon-badge')") is False


@pytest.mark.slow
@pytest.mark.regression
def test_both_entry_points_reach_the_calendar(wimi_session: WimiTestSession, wimi_page: WimiPage) -> None:
    exam = wimi_session.user.db.create_exam_context(exam_name="Links Exam")

    wimi_page.goto("dashboard")
    _wait(wimi_page, "!!document.querySelector('[data-testid=\"dashboard-calendar-link\"]')", what="the dashboard link")
    wimi_page.eval_js("document.querySelector('[data-testid=\"dashboard-calendar-link\"]').click()")
    _wait(wimi_page, "window.location.href.includes('calendar.html')", what="navigation to the calendar")
    _wait(wimi_page, _READY, what="the calendar gate to release")

    # Session setup needs an exam id, so navigate with the query string directly.
    wimi_page.eval_js(f"window.location.href = 'session_setup.html?exam_id={exam.id}'")
    _wait(wimi_page, "!!document.querySelector('[data-testid=\"session-calendar-link\"]')", what="the session-setup link")
    href = wimi_page.eval_js("document.querySelector('[data-testid=\"session-calendar-link\"]').getAttribute('href')")
    assert href == "calendar.html"
