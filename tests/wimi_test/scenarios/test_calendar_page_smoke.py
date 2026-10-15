"""The calendar page (#778 Wave 2) opens, releases its gate, draws today's
sessions and plans, and its Plan dialog draws an accessibility boundary.

Two scenarios. The smoke proves the page is a page: the gate releases, the
range heading is written, today's cell exists and carries the seeded past
session and the seeded plan as chips. The boundary test is the measurement
``tests/test_modal_boundary_coverage.py`` demands before a page may join
``KNOWN_AT_RISK``: with the Plan dialog opened by a REAL hit-tested click,
the accessibility tree exposes fewer nodes than before and
``modal_dialog.js`` is holding ``aria-hidden`` attributes (#420, #422). A
class toggle would not be faithful; the click is the invoker a student uses.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.page_gate import ax_snapshot, ax_summary, enable_accessibility

GATE_RELEASE_MS = 60000
_RELEASED = (
    "(() => { const g = document.querySelector('[data-page-gated]');"
    " return !!g && !g.hasAttribute('inert') && !!window.CalendarState"
    " && window.CalendarState.isLoading === false; })()"
)


def _wait_released(page: WimiPage) -> None:
    for _ in range(GATE_RELEASE_MS // 100):
        if page.eval_js(_RELEASED):
            return
        page.wait_for_timeout(100)
    raise AssertionError("the calendar page never released its gate")


@pytest.fixture
def calendar(wimi_session: WimiTestSession, wimi_page: WimiPage) -> WimiPage:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Cal Exam")
    db.update_exam_context_settings(exam.id, color_hex="#aa3366")
    today = date.today()
    db.create_review_session(exam_context_id=exam.id, date_encountered=today,
                             total_questions=10, total_incorrect=2, session_name="Past block")
    db.create_planned_session(today, exam_context_id=exam.id, title="Planned one", planned_questions=20)
    wimi_page.goto("calendar")
    _wait_released(wimi_page)
    return wimi_page


@pytest.mark.slow
@pytest.mark.regression
def test_the_page_opens_and_draws_today(calendar: WimiPage) -> None:
    heading = calendar.eval_js("document.getElementById('cal-range').textContent.trim()")
    assert heading, "the range heading was never written"
    today = calendar.eval_js("LocalDate.today()")
    cell_info = calendar.eval_js(
        "(() => { const td = document.querySelector('[data-date=\"' + LocalDate.today() + '\"]');"
        " if (!td) return null;"
        " return { kinds: [...td.querySelectorAll('[data-kind]')].map(e => e.getAttribute('data-kind')),"
        "          text: td.textContent }; })()")
    assert cell_info is not None, f"no grid cell for today {today}"
    assert "past" in cell_info["kinds"] and "planned" in cell_info["kinds"], cell_info
    assert "Cal Exam" in cell_info["text"], cell_info
    assert calendar.eval_js("window.CalendarState.error") in (None, ""), calendar.eval_js("window.CalendarState.error")
    legend = calendar.eval_js("document.getElementById('cal-legend-list').textContent")
    assert "Cal Exam" in legend
    # Both dialogs ship `hidden`, and the stylesheet must let the attribute
    # win: the first measurement found `display: flex` on the class beating
    # the user agent's `[hidden]` rule, both dialogs painted, and the page
    # behind them hidden from assistive tech.
    displays = calendar.eval_js(
        "['cal-plan-modal', 'cal-remove-modal'].map(id => getComputedStyle(document.getElementById(id)).display)")
    assert displays == ["none", "none"], displays


@pytest.mark.slow
@pytest.mark.regression
def test_the_plan_dialog_draws_an_accessibility_boundary(calendar: WimiPage) -> None:
    """The measurement KNOWN_AT_RISK requires (#420): a real click opens the
    dialog, and the tree exposes less than before."""
    enable_accessibility(calendar)
    before = ax_snapshot(calendar)
    assert "dialog" not in before["roles"], f"a dialog is exposed before anything opened: {ax_summary(before)}"

    calendar.locator(css="#cal-plan").click()
    for _ in range(50):
        if calendar.eval_js("!document.getElementById('cal-plan-modal').hidden"):
            break
        calendar.wait_for_timeout(100)
    else:
        raise AssertionError("the Plan dialog never opened after a real click on #cal-plan")

    after = ax_snapshot(calendar)
    for _ in range(30):
        if after["exposed"] < before["exposed"] and "dialog" in after["roles"]:
            break
        calendar.wait_for_timeout(100)
        after = ax_snapshot(calendar)

    assert "dialog" in after["roles"], f"the dialog is not exposed: {ax_summary(after)}"
    assert after["exposed"] < before["exposed"], (
        f"opening the Plan dialog did not reduce what the accessibility tree exposes "
        f"({before['exposed']} -> {after['exposed']}), so no boundary was drawn (#422).\n"
        f"before: {ax_summary(before)}\nafter: {ax_summary(after)}")
    held = calendar.eval_js("(() => window.ModalDialog ? window.ModalDialog.hiddenCount() : -1)()")
    assert held > 0, (
        "the tree shrank but modal_dialog.js holds no aria-hidden attributes, so something else "
        f"caused it (held={held}); this is not measuring the boundary (#319)")
