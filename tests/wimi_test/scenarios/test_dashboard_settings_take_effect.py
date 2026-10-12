"""Regression: the Dashboard & Analytics settings do what they say (#504).

Six controls in Settings -> Dashboard & Analytics were stored and read by
nothing. By decision on #504:

* the four ``show_*`` boxes are **master switches**, each hiding a fixed group
  of charts for every exam, and the per-exam Chart Visibility ticks can hide
  a chart as well -- neither can show what the other hides;
* ``analytics_detail_level`` is Summary / Detailed / Advanced over the same
  charts;
* ``dashboard_auto_refresh_seconds`` reloads the dashboard's figures while it
  is open.

Every hiding assertion carries a positive control -- a chart that must still
show -- because an absence on a page that never rendered proves nothing.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Readiness from what master and the fix share -- the overview figure --
# so a test fails at its own assertion and not at the wait.
# The figure ships as a "-" placeholder, so wait for a number.
READY = ("(() => !!(window.dashboard && document.getElementById('totalEntries')"
         " && /^[0-9]+$/.test(document.getElementById('totalEntries').textContent.trim())))()")

SHOWN = """JSON.stringify(Object.fromEntries(Object.entries({
  subject_sunburst: '#subjectBreakdownCard', tag_chart: '#tagBreakdownCard',
  activity_chart: '.activity-section', activity_heatmap: '.heatmap-section',
  weekly_goal: '.goal-section', difficulty_distribution: '.difficulty-section',
  patterns_insights: '.insights-section', weight_analysis: '.weight-analysis-section'
}).map(([k, sel]) => {
  const el = document.querySelector(sel);
  return [k, !!el && getComputedStyle(el).display !== 'none'];
})))"""

# Recorded, not replaced: the page's own setInterval still runs.
RECORD_INTERVALS = """
(() => {
  const real = window.setInterval.bind(window);
  window.__intervals = [];
  window.setInterval = (fn, ms, ...rest) => {
    window.__intervals.push({ ms, fn });
    return real(fn, ms, ...rest);
  };
})();
"""


def _poll(page: WimiPage, js: str, want, *, timeout_ms: int = 20000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last == want:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed(db, entries: int = 2):
    exam = db.create_exam_context(exam_name="Dashboard Settings")
    session = db.create_review_session(exam_context_id=exam.id,
                                       total_questions=10, total_incorrect=entries)
    for i in range(entries):
        db.create_question_entry(review_session_id=session.id,
                                 user_answer="a", correct_answer="b",
                                 question_id=f"q{i}")
    return exam, session


def _open(page: WimiPage, exam_id: int) -> None:
    page.eval_js("window.__wimiPrevDoc = true")
    page.goto("analytics", query={"exam": exam_id})
    assert _poll(page, "typeof window.__wimiPrevDoc === 'undefined'", True) is True
    assert _poll(page, READY, True) is True, "the analytics dashboard never finished loading"


def _shown_once(page: WimiPage, settled) -> dict:
    """The visibility map, once ``settled(map)`` holds or 10 s have passed."""
    shown = {}
    for _ in range(100):
        shown = json.loads(page.eval_js(SHOWN))
        if settled(shown):
            break
        page.wait_for_timeout(100)
    return shown


@pytest.mark.slow
@pytest.mark.regression
def test_a_master_switch_hides_its_group_for_every_exam(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam, _ = _seed(db)
    db.update_settings(show_subject_breakdown=False, analytics_detail_level="advanced")

    _open(wimi_page, exam.id)
    shown = _shown_once(wimi_page, lambda m: not m["subject_sunburst"])

    assert shown["tag_chart"] and shown["activity_chart"], (
        f"positive control: charts outside the group must still show: {shown}")
    assert not shown["subject_sunburst"], f"Show Subject Breakdown off, sunburst drawn: {shown}"
    assert not shown["weight_analysis"], f"Show Subject Breakdown off, weight analysis drawn: {shown}"


@pytest.mark.slow
@pytest.mark.regression
def test_summary_detail_keeps_only_the_sunburst_and_mistake_types(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam, _ = _seed(db)
    db.update_settings(analytics_detail_level="summary")

    _open(wimi_page, exam.id)
    shown = _shown_once(wimi_page, lambda m: not m["activity_chart"])

    assert shown["subject_sunburst"] and shown["tag_chart"], f"summary keeps these two: {shown}"
    hidden = [k for k, v in shown.items() if v and k not in ("subject_sunburst", "tag_chart")]
    assert not hidden, f"Summary still drew: {hidden}"


@pytest.mark.slow
@pytest.mark.regression
def test_the_dashboard_refreshes_itself_at_the_chosen_interval(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam, session = _seed(db, entries=2)
    db.update_settings(dashboard_auto_refresh_seconds=45)

    wimi_page.tab.Page.enable()
    script = wimi_page.tab.Page.addScriptToEvaluateOnNewDocument(source=RECORD_INTERVALS)
    try:
        _open(wimi_page, exam.id)
        assert wimi_page.eval_js("document.getElementById('totalEntries').textContent.trim()") == "2"
        has_45 = "window.__intervals.some(i => i.ms === 45000)"
        delays = wimi_page.eval_js("window.__intervals.map(i => i.ms)")
        assert _poll(wimi_page, has_45, True, timeout_ms=5000) is True, (
            f"no 45-second refresh was scheduled: {delays}")

        db.create_question_entry(review_session_id=session.id, user_answer="a",
                                 correct_answer="b", question_id="late")
        # Fire the dashboard's own scheduled callback rather than waiting 45 s.
        wimi_page.eval_js("window.__intervals.find(i => i.ms === 45000).fn()")

        assert _poll(wimi_page,
                     "document.getElementById('totalEntries').textContent.trim()",
                     "3") == "3", "the refresh did not reload the figures"
    finally:
        wimi_page.tab.Page.removeScriptToEvaluateOnNewDocument(identifier=script["identifier"])
