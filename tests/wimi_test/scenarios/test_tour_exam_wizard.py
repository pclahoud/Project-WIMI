"""The exam wizard's first-run tour, walked through the wizard's own Next (#430).

Every wizard step is a `.wizard-step` in one document, so each tour step
renders on exactly one wizard step and the tour is re-started on every step
change (exam_wizard.js `updateUI()`). A student goes through the wizard once,
so a step that waited for "a later visit" would never be seen: this walks
the Simple path from Choose Exam Type to Review & Create and asserts that
each tour step shows on its own wizard step and names the control it
spotlights (the title standard, #430 comment #9292). A wizard step with
several tips shows them in screen order (#682), walked with the tour's Next.
"""
from __future__ import annotations

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

READY = ("(() => { try { return typeof examWizard !== 'undefined'"
         " && !!examWizard.currentConfig && typeof WimiTour !== 'undefined'; }"
         " catch (e) { return false; } })()")
STEP = "examWizard.getCurrentStepId()"
PANEL = """(() => {
  const p = document.querySelector('[data-testid="tour-panel"]');
  if (!p) return null;
  return {count: p.querySelector('[data-testid="tour-count"]').textContent,
          title: p.querySelector('[data-testid="tour-title"]').textContent};
})()"""
PANEL_OPEN = "!!document.querySelector('[data-testid=\"tour-panel\"]')"


def _next_wizard_step(page: WimiPage) -> None:
    page.eval_js("document.querySelector('[data-testid=\"wizard-next-button\"]').click()")


def _close_tip(page: WimiPage) -> None:
    page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    assert poll(page, f"!({PANEL_OPEN})", timeout_ms=5000)


def _tip_on(page: WimiPage, wizard_step: str, number: int) -> dict:
    assert poll(page, f"{STEP} === {wizard_step!r}", timeout_ms=10000), page.eval_js(STEP)
    assert poll(page, PANEL_OPEN, timeout_ms=10000), (
        f"no tour step showed on {wizard_step}: the wizard did not re-start the tour")
    panel = page.eval_js(PANEL)
    # A running number across the wizard's steps, never a restart (#682).
    assert panel["count"] == f"Tip {number}", panel
    return panel


def _tips_on(page: WimiPage, wizard_step: str, first: int) -> list[str]:
    """Every tip one wizard step shows, in order, pressing the tour's Next
    until it closes. Tip numbers run on from `first`."""
    titles = [_tip_on(page, wizard_step, first)["title"]]
    for _ in range(10):
        page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
        page.wait_for_timeout(200)
        panel = page.eval_js(PANEL)
        if panel is None:
            return titles
        assert panel["count"] == f"Tip {first + len(titles)}", panel
        titles.append(panel["title"])
    raise AssertionError(f"the tour on {wizard_step} never closed: {titles}")


@pytest.mark.slow
@pytest.mark.regression
def test_each_wizard_step_shows_its_tour_step_naming_its_control(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    wimi_page.goto("exam-wizard")
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert not wimi_page.eval_js(PANEL_OPEN), "the tour must be off until a scenario turns it on"
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    wimi_page.eval_js("window.__previousDocument = true")
    wimi_page.goto("exam-wizard")
    assert poll(wimi_page, "window.__previousDocument !== true", timeout_ms=10000)
    assert poll(wimi_page, READY, timeout_ms=30000)

    # Choose Exam Type, on load.
    panel = _tip_on(wimi_page, "step-1", 1)
    assert "Multi-Dimensional Exam" in panel["title"], panel
    _close_tip(wimi_page)

    # Choose a Template: the category row, then the first card, which is
    # drawn after the step change (#682: screen order).
    _next_wizard_step(wimi_page)
    titles = _tips_on(wimi_page, "step-1-template", 2)
    print("template step:", titles)
    first_card = wimi_page.eval_js(
        "[...document.querySelectorAll('[data-tour-anchor=\"template-card\"]')]"
        ".find(c => c.getBoundingClientRect().width > 0)"
        ".querySelector('.template-name').textContent")
    assert len(titles) == 2, titles
    assert titles[0] == "About: All", titles
    assert first_card and first_card in titles[1], (titles, first_card)
    wimi_page.eval_js("document.getElementById('template-scratch').click()")

    # Exam Information: fields, so each name is its <label> (#655).
    _next_wizard_step(wimi_page)
    titles = _tips_on(wimi_page, "step-2", 4)
    print("info step:", titles)
    assert titles == ["About: Exam Name", "About: Description (optional)"], titles
    wimi_page.eval_js("document.getElementById('exam-name').value = 'Tour wizard'")

    # Subject Hierarchy has no tour step: nothing shows, and Next goes on.
    _next_wizard_step(wimi_page)
    assert poll(wimi_page, f"{STEP} === 'step-3'", timeout_ms=10000)
    wimi_page.wait_for_timeout(500)
    assert not wimi_page.eval_js(PANEL_OPEN), wimi_page.eval_js(PANEL)

    _next_wizard_step(wimi_page)
    titles = _tips_on(wimi_page, "step-exam-length", 6)
    print("length step:", titles)
    assert titles == ["About: Exam Length", "About: Variable length (CAT)"], titles

    _next_wizard_step(wimi_page)  # Weights: no tour step
    assert poll(wimi_page, f"{STEP} === 'step-4'", timeout_ms=10000)
    _next_wizard_step(wimi_page)
    panel = _tip_on(wimi_page, "step-5", 8)
    assert panel["title"] == "About: Review & Create", panel

    seen = wimi_page.eval_js("window.api.getTourState().then(s => s.seen)", await_promise=True)
    assert len(seen) == 8 and all(k.startswith("exam-wizard:") for k in seen), seen
