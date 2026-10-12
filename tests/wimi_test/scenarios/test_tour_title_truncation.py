"""A tour title past 60 characters never prints half a figure (#672).

`nameOf` used to cut every long name at character 57, so the tree editor's
total, which names its axis before its band, read "…total 97…": a number the
student is invited to complete and was never shown. The rule (tour.js,
`shorten`) cuts at the last space at or before 57; failing that, at 57 but
never inside a figure, a band counting as one; failing that, no name.

Three cases, each asserting the title as rendered and its box:
- the real sentence, drawn by the real `weightRangeTotalSentence` on an axis
  with a published name (Physician Task / Competency), where the space rule
  alone leaves the band out;
- one unbroken token with a band inside the first 57 characters' cut, which
  backs up to the band's start, and whose 52 letters must wrap inside the
  panel (`overflow-wrap: anywhere`) rather than run out of it;
- a name that is all figure, which gets "About this".

The second and third are fixtures on the dashboard: no real anchor has a
57-character token today, so these are the only exercise those branches get.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

TITLE = """(() => {
  const p = document.querySelector('[data-testid="tour-panel"]');
  if (!p) return null;
  const t = p.querySelector('[data-testid="tour-title"]');
  const a = t.getBoundingClientRect(), b = p.getBoundingClientRect();
  return {title: t.textContent, inside: a.left >= b.left && a.right <= b.right,
          clipped: t.scrollWidth > t.clientWidth};
})()"""
PANEL_OPEN = "!!document.querySelector('[data-testid=\"tour-panel\"]')"
LONG_TOKEN = "A" * 52 + "97–142%" + "B" * 10
ALL_FIGURE = "1234567890" * 7


def _fixture_step(anchor: str) -> dict:
    return {"page": "dashboard", "anchor": anchor, "text": "Fixture step for #672.",
            "chapter": "the_first_hour", "chapter_title": "Your first hour",
            "section": "S", "link": "help_the_first_hour.html"}


@pytest.mark.slow
@pytest.mark.regression
def test_the_real_total_on_a_long_axis_name_leaves_the_band_out_whole(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Tour titles", exam_description="")
    axis = db.create_dimension(exam_id=exam.id, name="Physician Task / Competency",
                               display_order=1, is_required=True)
    db.create_subject_node_with_weight(
        exam_context="Tour titles", name="Diagnosis", level_type="Task",
        exam_weight_low=97, exam_weight_high=142, dimension_id=axis)
    db.conn.commit()

    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=30000), "the tree editor did not start its tour"
    # The sentence the old rule cut to "…total 97…": the real function's own.
    sentence = "Published ranges for Physician Task / Competency total 97–142% of the exam."
    assert wimi_page.eval_js(
        "document.querySelector('.weight-range-total').textContent") == sentence

    for _ in range(10):
        panel = wimi_page.eval_js(TITLE)
        assert panel is not None, "the tour ended before the total's tip"
        if "Published ranges" in panel["title"]:
            break
        wimi_page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    assert panel["title"] == "About: Published ranges for Physician Task / Competency total…", panel
    assert panel["inside"] and not panel["clipped"], panel


@pytest.mark.slow
@pytest.mark.regression
def test_a_name_with_no_space_to_cut_at_backs_up_to_the_figure_and_wraps(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    wimi_page.goto("dashboard")
    assert poll(wimi_page, "typeof WimiTour !== 'undefined' && LandingState.isLoading === false",
                timeout_ms=30000)
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    wimi_page.eval_js(
        "(() => { for (const [id, text] of [['fixture-all-figure', %s], ['fixture-long-token', %s]]) {"
        " const el = document.createElement('div'); el.setAttribute('data-tour-anchor', id);"
        " el.textContent = text; el.style.cssText = 'width: 10rem; overflow: hidden;';"
        " document.body.prepend(el); } })()" % (json.dumps(ALL_FIGURE), json.dumps(LONG_TOKEN)))
    # Prepended last, so on top: the tour runs in screen order (#682).
    steps = [_fixture_step("fixture-long-token"), _fixture_step("fixture-all-figure")]
    wimi_page.eval_js(f"window.WIMI_TOUR_STEPS = {{dashboard: {json.dumps(steps)}}}")
    assert wimi_page.eval_js("WimiTour.start('dashboard')", await_promise=True) == 2

    panel = wimi_page.eval_js(TITLE)
    assert panel["title"] == "About: " + "A" * 52 + "…", panel
    assert panel["inside"] and not panel["clipped"], (
        f"a 52-letter token ran out of the panel instead of wrapping: {panel}")

    wimi_page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    assert wimi_page.eval_js(TITLE)["title"] == "About this"
