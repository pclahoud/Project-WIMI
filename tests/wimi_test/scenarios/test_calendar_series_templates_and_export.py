"""A weekly series drawn from one row, a template made from the Plan dialog
and listed in Settings, and the iCal work slot writing a parseable file
(#778 Wave 4, decisions 2, 10 and 11).

The export is driven through the work slot with a path the test owns; the
native save dialog is never clicked (nothing in the harness can dismiss
one). The file is read and parsed from the test process.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from app.ical_export import parse_ics
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


def _next_weekday(start: date, weekday: int) -> date:
    d = start
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


@pytest.mark.slow
@pytest.mark.regression
def test_a_series_made_in_the_dialog_draws_every_occurrence_from_one_row(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Series Exam")
    first = _next_weekday(date.today(), 1)          # next Tuesday, inside the current or next week

    wimi_page.goto("calendar")
    _wait(wimi_page, _READY, what="the calendar gate to release")
    wimi_page.eval_js("document.getElementById('cal-view-month').click()")
    wimi_page.wait_for_timeout(300)
    wimi_page.locator(css="#cal-plan").click()
    _wait(wimi_page, "!document.getElementById('cal-plan-modal').hidden", what="the Plan dialog", tries=50)
    wimi_page.eval_js(f"""
        (() => {{
            document.getElementById('cal-plan-exam').value = '{exam.id}';
            document.getElementById('cal-plan-exam').dispatchEvent(new Event('change', {{bubbles: true}}));
            document.getElementById('cal-plan-date').value = '{first.isoformat()}';
            document.getElementById('cal-plan-title-input').value = 'Weekly review';
            const rep = document.getElementById('cal-plan-repeat');
            rep.checked = true; rep.dispatchEvent(new Event('change', {{bubbles: true}}));
            document.querySelector('#cal-repeat-fields input[value="TU"]').checked = true;
            document.getElementById('cal-repeat-end').value = 'count';
            document.getElementById('cal-repeat-end').dispatchEvent(new Event('change', {{bubbles: true}}));
            document.getElementById('cal-repeat-count').value = '3';
            document.getElementById('cal-plan-save').click();
        }})()
    """)
    _wait(wimi_page, "document.getElementById('cal-plan-modal').hidden", what="the dialog to close", tries=100)

    rows = db.fetchall("SELECT recurrence_rule, planned_date FROM planned_sessions")
    assert len(rows) == 1 and rows[0]["recurrence_rule"] == "FREQ=WEEKLY;BYDAY=TU;COUNT=3", rows
    rng = db.get_calendar_range(first, first + timedelta(days=30))
    assert [p["planned_date"] for p in rng["planned"]] == [
        first.isoformat(), (first + timedelta(days=7)).isoformat(), (first + timedelta(days=14)).isoformat()]
    # Drawn: at least the occurrences inside the month on screen carry the series title.
    chips = wimi_page.eval_js(
        "[...document.querySelectorAll('#cal-grid [data-kind=\"planned\"]')].map(c => c.closest('td').getAttribute('data-date'))")
    assert first.isoformat() in chips, chips


@pytest.mark.slow
@pytest.mark.regression
def test_a_template_saved_from_the_dialog_appears_in_settings_and_archives(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Template Exam")
    day = date.today() + timedelta(days=2)

    wimi_page.goto("calendar")
    _wait(wimi_page, _READY, what="the calendar gate to release")
    wimi_page.locator(css="#cal-plan").click()
    _wait(wimi_page, "!document.getElementById('cal-plan-modal').hidden", what="the Plan dialog", tries=50)
    wimi_page.eval_js(f"""
        (() => {{
            document.getElementById('cal-plan-exam').value = '{exam.id}';
            document.getElementById('cal-plan-exam').dispatchEvent(new Event('change', {{bubbles: true}}));
            document.getElementById('cal-plan-date').value = '{day.isoformat()}';
            document.getElementById('cal-plan-duration').value = '45';
            document.getElementById('cal-plan-questions').value = '20';
            const box = document.getElementById('cal-plan-save-template');
            box.checked = true; box.dispatchEvent(new Event('change', {{bubbles: true}}));
            document.getElementById('cal-plan-template-name').value = 'Morning block';
            document.getElementById('cal-plan-save').click();
        }})()
    """)
    _wait(wimi_page, "document.getElementById('cal-plan-modal').hidden", what="the dialog to close", tries=100)

    templates = db.get_session_templates()
    assert [(t["name"], t["default_duration_minutes"], t["default_questions"], t["exam_context_id"]) for t in templates] == [
        ("Morning block", 45, 20, exam.id)]
    assert db.fetchone("SELECT template_id FROM planned_sessions")["template_id"] is None, (
        "saving a template alongside a plan does not retro-link the plan; the template is for the next one")

    # The picker now offers it on the next open.
    wimi_page.locator(css="#cal-plan").click()
    _wait(wimi_page, "!document.getElementById('cal-plan-modal').hidden", what="the Plan dialog again", tries=50)
    options = wimi_page.eval_js("[...document.getElementById('cal-plan-template').options].map(o => o.textContent)")
    assert "Morning block" in options, options
    wimi_page.eval_js("document.getElementById('cal-plan-cancel').click()")

    # Settings lists it, and Archive removes it from the list and from the picker's set.
    wimi_page.goto("settings")
    _wait(wimi_page, "document.querySelectorAll('#calendar-templates-list li').length === 1",
          what="the Settings templates list", tries=200)
    assert "Morning block" in wimi_page.eval_js("document.getElementById('calendar-templates-list').textContent")
    wimi_page.eval_js("document.querySelector('#calendar-templates-list li button').click()")
    _wait(wimi_page, "document.querySelectorAll('#calendar-templates-list li').length === 0", what="the row to go", tries=100)
    assert db.get_session_templates() == []
    assert len(db.get_session_templates(include_archived=True)) == 1


@pytest.mark.slow
@pytest.mark.regression
def test_the_export_work_slot_writes_a_parseable_ics(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Export Exam")
    db.create_planned_session(date.today() + timedelta(days=1), exam_context_id=exam.id,
                              title="Timed plan", planned_start_time="09:00", planned_duration_minutes=60)
    db.create_review_session(exam_context_id=exam.id, date_encountered=date.today(),
                             total_questions=10, total_incorrect=2, session_name="Past block")

    wimi_page.goto("calendar")
    _wait(wimi_page, _READY, what="the calendar gate to release")
    assert wimi_page.eval_js("typeof api.openCalendarExportDialog === 'function'")
    assert wimi_page.eval_js("!!document.getElementById('cal-export')")

    dest = tmp_path / "export.ics"
    result = wimi_page.eval_js(
        f"(async () => await api.exportCalendarIcs({json.dumps({'dest_path': str(dest)})}))()",
        await_promise=True)
    assert result["event_count"] == 2 and result["file_path"] == str(dest)
    events = parse_ics(dest.read_bytes())
    summaries = sorted(e["SUMMARY"][0] for e in events)
    assert summaries == ["WIMI session: Export Exam – Past block", "WIMI session: Export Exam – Timed plan"]
    timed = next(e for e in events if "Timed plan" in e["SUMMARY"][0])
    assert timed["DTSTART"][0].endswith("Z") and timed["DURATION"] == ["PT60M"]
    assert not any("ORGANIZER" in e or "ATTENDEE" in e for e in events)
