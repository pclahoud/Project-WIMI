"""Regression: each weight-analysis quadrant shows its top five (#817).

``renderQuadrantAnalysis`` drew every subject of every quadrant. On the
owner's own profile (a full published blueprint, almost every subject without
entries) the card was dozens of screens tall. The owner's decision: each quadrant shows the five
subjects with the largest gap between mistake share and exam weight, with a
*Show all N* toggle for that quadrant alone.

Eight subjects, no entries, weights 1-2% up to 8-9%: every one is 0% of
mistakes against a sub-10% weight outside its range, so all eight land in
*Low Priority*, and the gap is the weight's midpoint -- so the top five are the
five heaviest, in that order. The toggle is pressed for real and pressed back.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.anki_settings import poll_true
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

NAMES = "JSON.stringify(Array.from(document.querySelectorAll(" \
        "'#quadrantAnalysis .quadrant-section.low-priority .subject-name')).map(e => e.textContent))"
TOGGLE = '#quadrantAnalysis .quadrant-section.low-priority button.quadrant-more'

_LOAD = """
(async () => {
    await window.api.ready();
    const dash = window.analyticsDashboard || window.dashboard;
    dash.currentExamFilter = %d;
    await dash.loadWeightAnalysis();
    return 'ok';
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_a_quadrant_shows_its_top_five_and_toggles_the_rest(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db._ensure_phase2_schema()
    exam = db.create_exam_context(exam_name='Q817', exam_description='')
    for n in range(1, 9):
        db.create_subject_node_with_weight(
            exam_context=exam.exam_name, name=f'Weight {n}', level_type='System',
            exam_weight_low=n, exam_weight_high=n + 1, weight_source='user_defined')

    wimi_page.goto('analytics')
    assert wimi_page.eval_js(_LOAD % exam.id, await_promise=True) == 'ok'
    assert poll_true(wimi_page, f"{NAMES} !== '[]'"), 'the quadrant list never drew'

    # Top five by gap: the heaviest weights first.
    assert json.loads(wimi_page.eval_js(NAMES)) == [
        'Weight 8', 'Weight 7', 'Weight 6', 'Weight 5', 'Weight 4']
    count = wimi_page.eval_js(
        "document.querySelector('#quadrantAnalysis .quadrant-section.low-priority"
        " .quadrant-count').textContent")
    assert count == '8', 'the capped list must still say how many there are'
    assert wimi_page.eval_js(f"document.querySelector('{TOGGLE}').textContent.trim()") \
        == 'Show all 8'

    wimi_page.locator(css=TOGGLE).click()
    assert poll_true(wimi_page, f"JSON.parse({NAMES}).length === 8")
    assert wimi_page.eval_js(f"document.querySelector('{TOGGLE}').textContent.trim()") \
        == 'Show top 5'
    assert wimi_page.eval_js(f"document.querySelector('{TOGGLE}').getAttribute('aria-expanded')") \
        == 'true'
    assert wimi_page.eval_js("document.activeElement.classList.contains('quadrant-more')"), \
        'focus must stay on the toggle after it redraws the list'

    wimi_page.locator(css=TOGGLE).click()
    assert poll_true(wimi_page, f"JSON.parse({NAMES}).length === 5")
