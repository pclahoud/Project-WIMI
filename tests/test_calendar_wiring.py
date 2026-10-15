"""#778 Wave 2, the wiring half: the Settings panel is live and shaped by
owner decision 8, the two entry points exist (decision 12), the route and the
tour page list know the calendar, the wizard carries the colour field
(decision 9), session setup honours ?planned_id=, and chapter 80 no longer
says the Calendar panel is connected to nothing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SETTINGS = (REPO / "src/web/html/settings.html").read_text(encoding="utf-8")
INDEX = (REPO / "src/web/html/index.html").read_text(encoding="utf-8")
SESSION_HTML = (REPO / "src/web/html/session_setup.html").read_text(encoding="utf-8")
SESSION_JS = (REPO / "src/web/js/session_setup.js").read_text(encoding="utf-8")
WIZARD_HTML = (REPO / "src/web/html/wizards/exam_wizard.html").read_text(encoding="utf-8")
WIZARD_JS = (REPO / "src/web/js/exam_wizard.js").read_text(encoding="utf-8")
CHAPTER_80 = (REPO / "docs/manual/80_settings.md").read_text(encoding="utf-8")


def _panel(name: str) -> str:
    m = re.search(rf'<div class="settings-panel" data-panel="{name}".*?\n                </div>\n', SETTINGS, re.S)
    assert m, name
    return m.group(0)


@pytest.mark.unit
def test_the_calendar_panel_is_live_and_has_only_the_two_controls():
    panel = _panel("calendar")
    assert "coming-soon" not in panel and "disabled" not in panel and 'title="Coming soon"' not in panel
    fields = re.findall(r'data-field="([^"]+)"', panel)
    assert fields == ["calendar_default_view", "show_weekend_in_calendar"], fields
    assert 'value="day"' not in panel and "calendar_time_slot_minutes" not in panel


@pytest.mark.unit
def test_the_markup_default_agrees_with_the_stored_default():
    """The stored default is 'week' (UserPreferences and settings.js DEFAULTS);
    the old markup selected 'month' and populateForm hid the disagreement."""
    panel = _panel("calendar")
    assert '<option value="week" selected>' in panel
    assert 'value="month" selected' not in panel


# test_the_anki_panel_is_still_coming_soon lived here until #784 Wave 3 (PR
# #802) connected the Anki panel. Its intent -- calendar work leaves Anki to
# #784 -- is spent; tests/test_settings_anki_markup.py pins what that panel
# is now.


@pytest.mark.unit
def test_the_two_entry_points_exist_and_the_hero_is_untouched():
    assert 'data-testid="dashboard-calendar-link"' in INDEX and 'href="calendar.html"' in INDEX
    header = INDEX[INDEX.index('<header class="landing-header'):INDEX.index('</header>')]
    assert "calendar.html" not in header, "the entry point is the exam section header, not the hero (#313)"
    assert 'data-testid="session-calendar-link"' in SESSION_HTML


@pytest.mark.unit
def test_the_route_and_the_tour_page_list_know_the_calendar():
    import sys
    sys.path.insert(0, str(REPO))
    try:
        from wimi_test.routes import ROUTES
    finally:
        sys.path.pop(0)
    assert ROUTES["calendar"] == "calendar.html"
    gate = (REPO / "scripts/check_manual_sync.py").read_text(encoding="utf-8")
    assert '"calendar",' in gate[gate.index("TOUR_PAGES = ("):gate.index(")", gate.index("TOUR_PAGES = ("))]


@pytest.mark.unit
def test_session_setup_prefills_from_a_plan_and_starts_through_the_plan():
    assert "getUrlParam('planned_id')" in SESSION_JS
    assert "api.getPlannedSession(" in SESSION_JS
    start = SESSION_JS[SESSION_JS.index("async function startSession()"):]
    start = start[:start.index("\n}\n")]
    assert "api.startPlannedSession(" in start and "api.createReviewSession(" in start, (
        "both paths must exist: a plan starts through startPlannedSession, anything else creates as before")


@pytest.mark.unit
def test_the_wizard_carries_the_exam_colour_field():
    assert 'id="exam-color"' in WIZARD_HTML and 'id="exam-color-enabled"' in WIZARD_HTML
    assert "examColor" in WIZARD_JS
    assert "color_hex: this.data.examColor || null" in WIZARD_JS
    assert "updateExamContextSettings(examResult.id, { color_hex: this.data.examColor })" in WIZARD_JS


@pytest.mark.unit
def test_chapter_80_no_longer_says_the_calendar_panel_is_connected_to_nothing():
    assert "## Calendar and Anki Integration" not in CHAPTER_80, "the shared heading was the Coming Soon framing"
    assert "Nothing in them is connected to anything" not in CHAPTER_80
    section = CHAPTER_80[CHAPTER_80.index("## Calendar\n"):CHAPTER_80.index("## Anki Integration")]
    assert "It is connected now" in section, "the retraction has to say the panel works now"
    assert "Coming Soon" not in section.split("Until 2026-10-12")[0], "the present tense must not call it Coming Soon"
    assert "Two whole panels" not in CHAPTER_80
