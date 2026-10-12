"""A tour title leaves out text hidden from assistive tech (#682).

A control with no label is titled by its rendered text. The dictation button
holds an `aria-hidden` dot before its label, so its tip read "About: ● Speak"
(found by the entry form's tour pass, PR #724). The accessible name leaves
`aria-hidden` content out, and so does the title now.

Fixtures on the dashboard, because each case needs a shape no single real
control has:
- a dot directly under the control, and a star two levels down, both hidden;
- a control whose own ANCESTOR is `aria-hidden`. Only hiding inside the
  control counts: the walk stops at the control, so its name survives.
The real dictation button's title is asserted by test_tour_entry_form.py.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

TITLE = ("(() => { const t = document.querySelector('[data-testid=\"tour-title\"]');"
         " return t && t.textContent; })()")
NEXT = "document.querySelector('[data-testid=\"tour-next\"]').click()"
FIXTURES = """
<div data-tour-anchor="fx-icon-label" style="position: fixed; top: 100px; left: 100px;">
  <span aria-hidden="true">●</span>
  <span><span aria-hidden="true"><b>★</b></span>Speak</span>
</div>
<div aria-hidden="true" style="position: fixed; top: 200px; left: 100px;">
  <div data-tour-anchor="fx-in-hidden-region">Inside a hidden region</div>
</div>
"""


def _step(anchor: str) -> dict:
    return {"page": "dashboard", "anchor": anchor, "text": "Fixture step.",
            "chapter": "the_first_hour", "chapter_title": "Your first hour",
            "section": "S", "link": "help_the_first_hour.html"}


@pytest.mark.slow
@pytest.mark.regression
def test_a_title_from_rendered_text_leaves_out_aria_hidden_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    wimi_page.goto("dashboard")
    assert poll(wimi_page, "typeof WimiTour !== 'undefined' && LandingState.isLoading === false",
                timeout_ms=30000)
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    wimi_page.eval_js("document.body.insertAdjacentHTML('beforeend', %s)" % json.dumps(FIXTURES))
    steps = [_step("fx-icon-label"), _step("fx-in-hidden-region")]
    wimi_page.eval_js(f"window.WIMI_TOUR_STEPS = {{dashboard: {json.dumps(steps)}}}")
    assert wimi_page.eval_js("WimiTour.start('dashboard')", await_promise=True) == 2

    assert wimi_page.eval_js(TITLE) == "About: Speak"
    wimi_page.eval_js(NEXT)
    assert wimi_page.eval_js(TITLE) == "About: Inside a hidden region"
