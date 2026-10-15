"""Re-measurement: a profile whose last completed administration is 200 days
old is told it is due, "Snooze 30 days" hides the notice and moves next_due_at
by 30 days in the database, and the notice stays hidden across a reload
(#766 Wave 4, plan Stage 6 scenario 2).

The completed administration is seeded through the mixin and then aged with
two UPDATEs, so the scenario does not depend on waiting 200 days or on the
cadence default.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

NOTICE_VISIBLE = "(() => { const b = document.getElementById('assessment-notice'); return !!b && !b.hidden; })()"


def _wait(page: WimiPage, expr: str, *, ms: int = 10000) -> None:
    for _ in range(ms // 100):
        if page.eval_js(expr):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for: {expr[:90]}")


def _seed_overdue_completion(db) -> int:
    """One complete administration 200 days ago, next due 20 days ago."""
    rec = db.start_assessment("v1")
    rec = db.finish_assessment(rec.id)
    with db.transaction():
        db.execute(
            "UPDATE user_assessments SET started_at = datetime('now', '-200 days'), "
            "completed_at = datetime('now', '-200 days') WHERE id = ?", (rec.id,))
        db.execute(
            "UPDATE user_assessment_preferences SET next_due_at = datetime('now', '-20 days') "
            "WHERE user_id = ?", (db.user_id,))
    status = db.get_reassessment_status()
    assert status["has_completed_administration"] is True and status["due"] is True, status
    return rec.id


@pytest.mark.slow
@pytest.mark.regression
def test_an_overdue_profile_is_told_it_is_due_and_can_snooze_30_days(
        wimi_session: WimiTestSession, wimi_page: WimiPage):
    db = wimi_session.user.db
    _seed_overdue_completion(db)
    before = db.get_assessment_preferences()

    wimi_page.goto("dashboard")
    _wait(wimi_page, NOTICE_VISIBLE)
    text = wimi_page.locator(css="#assessment-notice-text").text().lower()
    assert "retake" in text and "due" in text
    assert wimi_page.locator(css="#assessment-notice-take").text() == "Retake now"
    assert wimi_page.eval_js("document.getElementById('assessment-notice-snooze-long').hidden") is False

    wimi_page.locator(css='[data-testid="dashboard-assessment-snooze-long"]').click()
    _wait(wimi_page, "document.getElementById('assessment-notice').hidden === true")

    after = db.get_assessment_preferences()
    assert after.snooze_count == before.snooze_count + 1
    # Snooze advances from the existing next_due_at (20 days ago), so the new
    # value is about 10 days ahead -- not 30 from now (Stage 1 semantics).
    assert after.next_due_at is not None
    status = db.get_reassessment_status()
    assert status["due"] is False
    assert 8 <= status["days_until_due"] <= 10, status

    # Reload: still hidden, no flicker to detect because it ships hidden.
    wimi_page.eval_js("window.__wimiOldDocument = true")
    wimi_page.goto("dashboard")
    _wait(wimi_page, "window.__wimiOldDocument === undefined")
    wimi_page.wait_for_timeout(600)
    assert wimi_page.eval_js(NOTICE_VISIBLE) is False


@pytest.mark.slow
@pytest.mark.regression
def test_settings_shows_the_overdue_state_and_saves_a_cadence(
        wimi_session: WimiTestSession, wimi_page: WimiPage):
    db = wimi_session.user.db
    _seed_overdue_completion(db)

    wimi_page.goto("settings")
    _wait(wimi_page, "(() => { const g = document.querySelector('[data-page-gated]'); return !!g && !g.hasAttribute('inert'); })()")
    wimi_page.locator(css='[data-testid="settings-nav-self-assessment"]').click()
    _wait(wimi_page, "document.getElementById('assessment-settings-started').hidden === false")
    assert "overdue" in wimi_page.locator(css="#assessment-next-due").text()
    assert wimi_page.locator(css="#assessment-snooze-count").text() == "0"

    # Out of range never reaches the bridge.
    wimi_page.locator(css="#assessment_cadence_days").fill("29")
    wimi_page.locator(css="#assessment-cadence-save").click()
    _wait(wimi_page, "document.getElementById('assessment-cadence-message').hidden === false")
    assert "30" in wimi_page.locator(css="#assessment-cadence-message").text()
    assert db.get_assessment_preferences().cadence_days == 180

    wimi_page.locator(css="#assessment_cadence_days").fill("90")
    wimi_page.locator(css="#assessment-cadence-save").click()
    _wait(wimi_page, "document.getElementById('assessment-cadence-message').textContent.startsWith('Saved')")
    assert db.get_assessment_preferences().cadence_days == 90
