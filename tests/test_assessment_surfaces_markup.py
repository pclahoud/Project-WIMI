"""Static shape of #766 Wave 3's two surfaces: the dashboard offer and the
Settings panel. The behaviour is in the scenario; this holds the markup
properties a scenario would pass through unnoticed.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INDEX = (REPO / "src/web/html/index.html").read_text(encoding="utf-8")
SETTINGS = (REPO / "src/web/html/settings.html").read_text(encoding="utf-8")


def _tag(html: str, pattern: str) -> str:
    m = re.search(pattern, html, re.S)
    assert m, pattern
    return m.group(0)


@pytest.mark.unit
def test_the_dashboard_offer_ships_hidden():
    """A notice that is visible before its status is known paints a false
    state for a frame on every launch; the sync notice taught this (#151)."""
    section = _tag(INDEX, r'<section class="assessment-notice"[^>]*>')
    assert " hidden" in section


@pytest.mark.unit
def test_the_dashboard_offer_has_its_three_actions_and_the_long_snooze_is_hidden():
    block = _tag(INDEX, r'<section class="assessment-notice".*?</section>')
    assert 'id="assessment-notice-take"' in block and 'href="assessment.html"' in block
    assert 'id="assessment-notice-later"' in block
    long = _tag(block, r'<button[^>]*id="assessment-notice-snooze-long"[^>]*>')
    assert " hidden" in long, "the 30-day snooze is for re-measurement only"


@pytest.mark.unit
def test_the_offer_module_is_linked_after_landing_js():
    scripts = re.findall(r'<script src="([^"]+)">', INDEX)
    assert "../js/landing.js" in scripts and "../js/assessment_notice.js" in scripts
    assert scripts.index("../js/assessment_notice.js") > scripts.index("../js/landing.js")


@pytest.mark.unit
def test_the_settings_panel_has_a_nav_item_and_is_the_only_panel_with_its_name():
    assert SETTINGS.count('data-panel="self_assessment"') == 2, "one nav item, one panel"
    assert 'data-testid="settings-nav-self-assessment"' in SETTINGS


@pytest.mark.unit
def test_no_control_in_the_settings_panel_carries_data_field():
    """The cadence lives in user_assessment_preferences, not user_preferences.
    A data-field here would be posted by the page's flat save, which the
    bridge refuses, and would be demanded by the DEFAULTS sweep."""
    panel = _tag(SETTINGS, r'<div class="settings-panel" data-panel="self_assessment".*?\n                </div>\n\n')
    assert "data-field" not in panel
    assert 'id="assessment_cadence_days"' in panel
    assert 'min="30"' in panel and 'max="730"' in panel


@pytest.mark.unit
def test_the_settings_module_is_linked_after_settings_js():
    scripts = re.findall(r'<script src="([^"]+)">', SETTINGS)
    assert scripts.index("../js/settings_assessment.js") > scripts.index("../js/settings.js")


# ---------------------------------------------------------------------------
# Wave 5b: the credit for the questionnaire items in Settings -> About.
# ---------------------------------------------------------------------------

def _about_credit() -> str:
    return _tag(SETTINGS, r'<table class="about-notices-table" data-testid="about-notices-assessment".*?</table>')


@pytest.mark.unit
def test_the_about_panel_credits_both_published_scales():
    """#195(a): notices live in the About panel and nowhere else, so this
    table is the only credit the items have."""
    credit = _about_credit()
    assert "Cacioppo" in credit and "Petty" in credit and "1982" in credit
    assert "VandeWalle" in credit and "1997" in credit
    assert "Personal Importance" in credit and "CC BY 4.0" in credit


@pytest.mark.unit
def test_the_lgo_credit_says_adapted_and_unvalidated():
    """Decision 8 made LGO an adaptation, not the validated instrument, and
    the credit has to say both halves (#766 comment #10553)."""
    credit = _about_credit()
    assert "Adapted" in credit
    assert "has not been independently validated" in credit


@pytest.mark.unit
def test_the_credit_makes_no_claim_about_permission():
    """Owner, 2026-10-12: do not add "No permission has been sought". The
    credit names the source and the copyright holder and stops there; a
    sentence in either direction -- sought or not, granted or not -- is a
    claim the owner declined to make on this page."""
    credit = _about_credit().lower()
    assert "permission" not in credit
    assert "fair use" not in credit and "fair-use" not in credit
