"""Analytics' first-run tour, through its real wiring (#430, #682).

Every analytics card is drawn on load, so one start after `init()` shows every
step whose card the seeded exam can draw. The seed (`analytics_tour_seed`) has
two dimensions, weights and lopsided mistakes, which is what draws the
cross-dimension key, Interaction Effects and the weight card's three panels;
so all sixteen steps show in one walk. What this pins beyond the resolve guard
is the title standard (#430 comment #9292), each panel naming the control it
spotlights, read from the element itself, and the screen order (#701).

Titles worth knowing about:
- The Weekly Goal heading and the stat labels are uppercased by CSS. The title
  reads the text as written ("Weekly Goal"), not as painted ("WEEKLY GOAL"):
  a tour title is a name, not a rendering (tour.js `renderedText`).
- The ring's centre and the two stat cards carry live data, so their titles
  are matched by shape, not as fixed strings. Kept live on purpose: a
  tour-only title override could state something the element does not.
- The cross-dimension key has no single label, so its title is the key's own
  three phrases run together.
"""
from __future__ import annotations

import re

import pytest

from _helpers.analytics_tour_seed import seed_analytics_tour_exam
from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

READY = ("(() => { try { return window.dashboard.isReady === true; }"
         " catch (e) { return false; } })()")
PANEL = """(() => {
  const p = document.querySelector('[data-testid="tour-panel"]');
  if (!p) return null;
  return {count: p.querySelector('[data-testid="tour-count"]').textContent,
          title: p.querySelector('[data-testid="tour-title"]').textContent};
})()"""
PANEL_OPEN = "!!document.querySelector('[data-testid=\"tour-panel\"]')"


def _titles_through_the_tour(page: WimiPage) -> list[str]:
    titles = []
    for _ in range(30):
        panel = page.eval_js(PANEL)
        if panel is None:
            return titles
        titles.append(panel["title"])
        page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    raise AssertionError(f"the tour did not end: {titles}")


@pytest.mark.slow
@pytest.mark.regression
def test_every_step_shows_on_load_in_screen_order_naming_its_control(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    query = seed_analytics_tour_exam(wimi_session.user.db, "Tour analytics")
    wimi_page.goto("analytics", query=query)
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert not wimi_page.eval_js(PANEL_OPEN), "the tour must be off until a scenario turns it on"
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    wimi_page.eval_js("window.__previousDocument = true")
    wimi_page.goto("analytics", query=query)
    assert poll(wimi_page, "window.__previousDocument !== true", timeout_ms=10000)
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "the page did not start its tour"

    assert wimi_page.eval_js(PANEL)["count"] == "Tip 1"
    # The steps that teach what Reduce Focus and "consider reducing time"
    # mean are only worth pinning in a state that draws them, so check the
    # seed produced the group before trusting the walk.
    card = wimi_page.eval_js("document.getElementById('weightAnalysis').innerText")
    assert "Reduce Focus" in card and "Dermatology" in card, card
    assert "consider reducing time" in card, card

    # Screen order (#701), measured once and pinned: the filter row, the four
    # stat cards left to right, the two breakdown charts, then the cards down
    # the page.
    titles = _titles_through_the_tour(wimi_page)
    assert len(titles) == 16, titles
    (exam_filter, cog, total, this_week, avg, by_subject, centre, by_type,
     cross_key, streak, goal, interactions, trend, quadrant, recs,
     sources) = titles
    assert exam_filter == "About: Exam filter", titles
    assert cog == "About: Configure Analytics", titles
    assert total.startswith("About: Total Entries"), titles
    assert this_week.startswith("About: This Week"), titles
    assert avg.startswith("About: Avg Difficulty"), titles
    assert by_subject == "About: By Subject", titles
    assert re.fullmatch(r"About: \d+ Total", centre), titles
    assert by_type == "About: By Mistake Type", titles
    assert cross_key == "About: Fewer mistakes More mistakes Insufficient data", titles
    assert streak == "About: Current Streak", titles
    assert goal == "About: Weekly Goal", titles
    assert interactions == "About: Interaction Effects", titles
    assert trend == "About: Trend", titles
    assert quadrant == "About: Quadrant Analysis", titles
    assert recs == "About: Top Recommendations", titles
    assert sources == "About: Weight Sources", titles
