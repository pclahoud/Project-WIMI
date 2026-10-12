"""#504: every Dashboard & Analytics control on the Settings page has a reader.

Nine controls were stored and read by nothing. The decisions on #504 made six
of them live on the analytics dashboard, joined the sort direction to the
field the entry browser reads, and removed the Performance panel's one
control. These are the source-level halves that a scenario cannot hold:

* the four ``show_*`` switches on the page are exactly the groups the
  dashboard knows, and every chart those groups or the detail levels name
  is one the dashboard can find -- so a switch cannot quietly hide nothing;
* the Performance panel and its control are gone, and stay gone.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SETTINGS = (REPO / "src/web/html/settings.html").read_text(encoding="utf-8")
DASHBOARD = (REPO / "src/web/js/analytics_dashboard.js").read_text(encoding="utf-8")


def _object_keys(const_name: str) -> list[str]:
    body = re.search(rf"const {const_name} = \{{(.*?)\n\}};", DASHBOARD, re.S)
    assert body, f"{const_name} not found in analytics_dashboard.js"
    return re.findall(r"^\s*'?([a-z_]+)'?\s*:", body.group(1), re.M)


def _quoted_in(const_name: str) -> set[str]:
    body = re.search(rf"const {const_name} = \{{(.*?)\n\}};", DASHBOARD, re.S)
    return set(re.findall(r"'([a-z_]+)'", body.group(1)))


def test_the_readers_find_what_they_should():
    """Controls: an empty read would make every comparison below pass.

    A FLOOR, not equality, and the change is deliberate. This test's job is to
    prove the regex found something -- an empty or broken read is what makes
    every comparison below vacuous. `>= 12` catches that exactly as `== 12`
    did, and does not additionally assert an INVENTORY, which is a different
    claim owned by a different test.

    Equality broke the moment a chart was legitimately added: #604 put
    `source_comparison` on the analytics page as the thirteenth entry, and
    this line failed with `13 == 12` -- a red master caused by a correct
    change, which is the shape a reader control should never have.

    The exact agreement between the two chart lists is
    `tests/test_chart_lists_agree.py`, which DERIVES it by comparing
    `CHART_SELECTORS` against `CHART_DEFINITIONS` rather than quoting a
    number. That is where a new chart must be accounted for.
    """
    assert len(_object_keys("CHART_SELECTORS")) >= 12
    assert len(_object_keys("PREFERENCE_CHART_GROUPS")) == 4


def _dashboard_panel() -> str:
    start = SETTINGS.index('class="settings-panel" data-panel="dashboard_analytics"')
    end = SETTINGS.index('class="settings-panel" data-panel=', start + 1)
    return SETTINGS[start:end]


def test_the_page_switches_are_the_dashboard_groups():
    on_page = set(re.findall(r'data-field="(show_[a-z_]+)"', _dashboard_panel()))
    assert on_page == set(_object_keys("PREFERENCE_CHART_GROUPS"))


def test_every_chart_a_setting_names_is_one_the_dashboard_can_find():
    charts = set(_object_keys("CHART_SELECTORS"))
    named = _quoted_in("PREFERENCE_CHART_GROUPS") | _quoted_in("DETAIL_LEVEL_HIDES")
    assert named - charts == set(), f"names no chart on the page: {named - charts}"


def test_every_detail_level_the_page_offers_is_defined():
    select = re.search(r'<select id="analytics_detail_level".*?</select>', SETTINGS, re.S).group(0)
    offered = set(re.findall(r'value="([a-z]+)"', select))
    assert offered == set(_object_keys("DETAIL_LEVEL_HIDES")) == {"summary", "detailed", "advanced"}


def test_the_performance_panel_is_gone():
    assert 'data-panel="performance"' not in SETTINGS
    assert 'data-field="realtime_update_delay_ms"' not in SETTINGS
