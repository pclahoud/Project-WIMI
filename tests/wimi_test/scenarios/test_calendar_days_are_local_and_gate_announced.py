"""The calendar names each day for the student's own day, and its gate can
be heard (#778 Wave 4; #286 and #127 applied to a new page).

Local days: `Emulation.setTimezoneOverride` is applied before the navigation
that reads the clock, with a zone chosen so the local and UTC days always
differ; the test fails hard if the instrument cannot tell the two apart. A
chip's `data-date` must match the cell it sits in, and the highlighted today
must be the page's own LocalDate.today(), under both a far-west and a far-east
zone.

Gate: the voice is a `role="status"` sibling of the inert container, present
and audible while the bridge is slowed, and the container is released
afterwards. No screen reader was run; what is measured is the accessibility
tree.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from _helpers.page_gate import (
    assert_gate_can_be_heard,
    ax_mentions,
    ax_snapshot,
    enable_accessibility,
    gate_state,
    is_gated,
    wait_for_release,
)
from _helpers.w114_form_ready import install_slow_bridge, poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_READY = (
    "(() => { const g = document.querySelector('[data-page-gated]');"
    " return !!g && !g.hasAttribute('inert') && !!window.CalendarState"
    " && window.CalendarState.isLoading === false; })()"
)

READ = """
(() => {
  const chips = [...document.querySelectorAll('#cal-grid .cal-event[data-date]')];
  const wrong = chips
    .map(c => ({chip: c.getAttribute('data-date'), cell: c.closest('td') && c.closest('td').getAttribute('data-date')}))
    .filter(x => x.chip !== x.cell);
  const todayCells = [...document.querySelectorAll('#cal-grid td.cal-today')].map(td => td.getAttribute('data-date'));
  return JSON.stringify({
    zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    chips: chips.length,
    wrong,
    todayCells,
    localToday: LocalDate.today(),
    naiveShifts: new Date('2026-03-01').getDate() !== 1,
  });
})()
"""


def _zone_for_now() -> tuple[str, bool]:
    """A DST-free zone whose local day differs from UTC's right now."""
    hour = datetime.now(timezone.utc).hour
    return ("Pacific/Pago_Pago", True) if hour < 11 else ("Pacific/Kiritimati", False)


@pytest.mark.slow
@pytest.mark.regression
def test_every_chip_sits_in_its_own_day_under_a_divergent_zone(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    import json
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Zone Exam")
    # Seven logged sessions and seven plans, one per day around today, so
    # whichever day the page calls "today" the week on screen is populated.
    for offset in range(-3, 4):
        d = date.today() + timedelta(days=offset)
        db.create_review_session(exam_context_id=exam.id, total_questions=5, total_incorrect=1,
                                 session_name=f"S{offset}", date_encountered=d)
        db.create_planned_session(d, exam_context_id=exam.id, title=f"P{offset}")
    db.conn.commit()

    zone, west = _zone_for_now()
    wimi_page.goto("dashboard")
    wimi_page.tab._tab.Emulation.setTimezoneOverride(timezoneId=zone)
    wimi_page.goto("calendar")
    assert poll(wimi_page, _READY), "the calendar never released its gate"

    got = json.loads(wimi_page.eval_js(READ))
    assert got["zone"] == zone, f"the timezone override did not take: {got!r}"
    assert got["naiveShifts"] is west, (
        f"under {zone} a naive new Date('YYYY-MM-DD') {'does not' if west else 'does'} "
        f"name another day, so this zone cannot tell a fixed page from a broken one: {got!r}")
    assert got["chips"] >= 7, f"too few chips drawn to mean anything: {got!r}"
    assert got["wrong"] == [], f"chips drawn under a day other than their own: {got['wrong']}"
    assert got["todayCells"] == [got["localToday"]], (
        f"the highlighted today is {got['todayCells']} while the page's own local day is {got['localToday']}")


@pytest.mark.slow
@pytest.mark.regression
def test_the_gate_is_audible_while_the_page_loads_and_releases_after(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    wimi_session.user.db.create_exam_context(exam_name="Gate Exam")
    install_slow_bridge(wimi_page, delay_ms=1500)
    wimi_page.goto("calendar", wait_for_bridge=False)
    assert poll(wimi_page, "!!document.getElementById('cal-grid')"), "the calendar markup never rendered"

    assert is_gated(wimi_page), "the page accepted input before it had anything to keep"
    state = gate_state(wimi_page)
    assert_gate_can_be_heard(state, where="calendar.html")
    assert "calendar" in state["text"].lower()

    enable_accessibility(wimi_page)
    snap = ax_snapshot(wimi_page)
    assert ax_mentions(snap, "Loading your calendar"), "the gate's text is not in the accessibility tree while gated"
    assert not ax_mentions(snap, "Plan a session"), (
        "the inert page's controls are exposed while gated; inert should have removed them")

    wait_for_release(wimi_page)
    assert not is_gated(wimi_page)
    after = ax_snapshot(wimi_page)
    assert ax_mentions(after, "Plan a session"), "the released page is still absent from the accessibility tree"
