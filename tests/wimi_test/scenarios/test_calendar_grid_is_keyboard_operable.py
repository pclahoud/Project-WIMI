"""The calendar grid is operable from the keyboard (#778 Wave 4).

A `table role=grid` with a roving tabindex: exactly one cell is in the tab
order, the arrow keys move the focused day by one, Home and End go to the
week's ends, and Enter opens the day panel and moves focus to its heading.
Assertions read `document.activeElement`, not the focus ring: a CDP
synthetic key sets no focus-visible flag CSS could show (CLAUDE.md, Testing).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.a11y import real_key

_READY = (
    "(() => { const g = document.querySelector('[data-page-gated]');"
    " return !!g && !g.hasAttribute('inert') && !!window.CalendarState"
    " && window.CalendarState.isLoading === false; })()"
)
_ACTIVE_DATE = "(() => { const a = document.activeElement; return a && a.getAttribute ? a.getAttribute('data-date') : null; })()"


def _wait_active(page: WimiPage, expected: str, *, tries: int = 50) -> None:
    got = None
    for _ in range(tries):
        got = page.eval_js(_ACTIVE_DATE)
        if got == expected:
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"focus is on {got!r}, expected the cell for {expected}")


def _wait(page: WimiPage, expr: str, *, what: str, tries: int = 300) -> None:
    for _ in range(tries):
        if page.eval_js(expr):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.fixture
def calendar(wimi_session: WimiTestSession, wimi_page: WimiPage) -> WimiPage:
    exam = wimi_session.user.db.create_exam_context(exam_name="Keys Exam")
    wimi_session.user.db.create_planned_session(date.today(), exam_context_id=exam.id, title="Today's plan")
    wimi_page.goto("calendar")
    _wait(wimi_page, _READY, what="the calendar gate to release")
    return wimi_page


@pytest.mark.slow
@pytest.mark.regression
def test_one_cell_is_in_the_tab_order_and_arrows_move_the_focused_day(calendar: WimiPage) -> None:
    tabbable = calendar.eval_js(
        "[...document.querySelectorAll('#cal-grid td[role=gridcell]')].filter(td => td.tabIndex === 0).length")
    assert tabbable == 1, f"{tabbable} cells carry tabindex=0; a roving tabindex has exactly one"

    calendar.eval_js("document.querySelector('#cal-grid td[role=gridcell][tabindex=\"0\"]').focus()")
    start = calendar.eval_js(_ACTIVE_DATE)
    assert start, "focus did not land on a grid cell"
    start_day = date.fromisoformat(start)

    real_key(calendar, "ArrowRight")
    _wait_active(calendar, (start_day + timedelta(days=1)).isoformat())
    real_key(calendar, "ArrowLeft")
    real_key(calendar, "ArrowLeft")
    # On a Monday this crosses the week's edge, which reloads the range and
    # redraws the grid; focus must land on the new cell, not on <body>.
    _wait_active(calendar, (start_day - timedelta(days=1)).isoformat())

    # Still exactly one cell in the tab order after moving.
    tabbable_after = calendar.eval_js(
        "[...document.querySelectorAll('#cal-grid td[role=gridcell]')].filter(td => td.tabIndex === 0).length")
    assert tabbable_after == 1


@pytest.mark.slow
@pytest.mark.regression
def test_home_and_end_reach_the_weeks_ends_and_enter_opens_the_day(calendar: WimiPage) -> None:
    calendar.eval_js("document.querySelector('#cal-grid td[role=gridcell][tabindex=\"0\"]').focus()")
    start_day = date.fromisoformat(calendar.eval_js(_ACTIVE_DATE))
    monday = start_day - timedelta(days=start_day.weekday())

    real_key(calendar, "Home")
    assert calendar.eval_js(_ACTIVE_DATE) == monday.isoformat(), "Home goes to Monday (weeks start Monday, decision 8)"
    real_key(calendar, "End")
    end_date = date.fromisoformat(calendar.eval_js(_ACTIVE_DATE))
    assert end_date.weekday() in (5, 6) and end_date > monday, "End goes to the week's last visible day"

    # Back to today, then Enter opens the panel and focus lands on its heading.
    calendar.eval_js("document.querySelector('#cal-grid td[data-date=\"' + LocalDate.today() + '\"]').focus()")
    real_key(calendar, "Enter")
    _wait(calendar, "!document.getElementById('cal-day-panel').hidden", what="the day panel to open", tries=50)
    assert calendar.eval_js("document.activeElement && document.activeElement.id") == "cal-day-heading"
    heading = calendar.eval_js("document.getElementById('cal-day-heading').textContent")
    assert heading, "the day heading was not written"
    assert "Today's plan" in calendar.eval_js("document.getElementById('cal-day-list').textContent")
