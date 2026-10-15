"""The dashboard offers the self-assessment on a fresh profile, "Later" snoozes
it for a week in the database, and the Settings panel shows the first-run
state (#766 Wave 3, decision 6).

Three scenarios through the real app. The re-measurement banner (after a
completion, when due) and the cadence round trip are Wave 4's.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

NOTICE_VISIBLE = "(() => { const b = document.getElementById('assessment-notice'); return !!b && !b.hidden; })()"


def _wait(page: WimiPage, expr: str, *, ms: int = 10000) -> None:
    for _ in range(ms // 100):
        if page.eval_js(expr):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for: {expr[:80]}")


def _reload(page: WimiPage, route: str) -> None:
    """A second goto to the same page returns before the new document commits:
    mark the old one and wait for the mark to vanish (scenario README)."""
    page.eval_js("window.__wimiOldDocument = true")
    page.goto(route)
    _wait(page, "window.__wimiOldDocument === undefined")


@pytest.mark.slow
@pytest.mark.regression
def test_a_fresh_profile_is_offered_the_assessment(wimi_session: WimiTestSession, wimi_page: WimiPage):
    wimi_page.goto("dashboard")
    _wait(wimi_page, NOTICE_VISIBLE)
    text = wimi_page.locator(css="#assessment-notice-text").text()
    assert "self-assessment" in text.lower()
    assert wimi_page.locator(css="#assessment-notice-take").text() == "Take it now"
    assert wimi_page.locator(css="#assessment-notice-take").attribute("href") == "assessment.html"
    # The 30-day option is for re-measurement only; a first-run offer has two actions.
    assert wimi_page.eval_js("document.getElementById('assessment-notice-snooze-long').hidden") is True
    # Nothing written yet: offering is not recording.
    assert wimi_session.user.db.get_assessment_preferences().snooze_count == 0


@pytest.mark.slow
@pytest.mark.regression
def test_later_hides_the_offer_and_snoozes_it_in_the_database(wimi_session: WimiTestSession, wimi_page: WimiPage):
    wimi_page.goto("dashboard")
    _wait(wimi_page, NOTICE_VISIBLE)
    wimi_page.locator(css="#assessment-notice-later").click()
    _wait(wimi_page, "document.getElementById('assessment-notice').hidden === true")

    prefs = wimi_session.user.db.get_assessment_preferences()
    assert prefs.snooze_count == 1
    assert prefs.next_due_at is not None
    status = wimi_session.user.db.get_reassessment_status()
    assert status["has_completed_administration"] is False
    assert status["days_until_due"] is not None and status["days_until_due"] >= 6

    # The snooze holds across a reload: the offer stays hidden, with no flicker
    # to detect because the markup ships hidden and only a positive read reveals it.
    _reload(wimi_page, "dashboard")
    wimi_page.wait_for_timeout(600)
    assert wimi_page.eval_js(NOTICE_VISIBLE) is False


@pytest.mark.slow
@pytest.mark.regression
def test_settings_shows_the_first_run_state_without_a_data_field(wimi_session: WimiTestSession, wimi_page: WimiPage):
    wimi_page.goto("settings")
    _wait(wimi_page, "(() => { const g = document.querySelector('[data-page-gated]'); return !!g && !g.hasAttribute('inert'); })()")
    wimi_page.locator(css='[data-testid="settings-nav-self-assessment"]').click()
    _wait(wimi_page, "document.querySelector('[data-panel=\"self_assessment\"]').classList.contains('active')")
    _wait(wimi_page, "document.getElementById('assessment-settings-empty').hidden === false")
    assert wimi_page.eval_js("document.getElementById('assessment-settings-started').hidden") is True
    assert wimi_page.locator(css="#assessment-settings-take").text() == "Take it now"
    # The cadence control is deliberately outside the page's flat save.
    assert wimi_page.eval_js(
        "document.querySelectorAll('#assessment-settings [data-field]').length") == 0
