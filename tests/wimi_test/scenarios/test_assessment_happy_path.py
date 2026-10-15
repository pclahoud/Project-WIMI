"""A student completes the whole self-assessment and the database holds one
complete administration with every score and all 57 answers (#766 Wave 4,
plan Stage 6 scenario 1).

Drives the flow from the page's own state rather than a hard-coded item
order, so a fixture change moves this test with it. The plan says "53 + 2";
the fixture is 34 + 13 + 8 = 55 items plus 2 attention checks, 57, and the
bridge tests pin that number -- this one reads it off the page.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_RELEASED = """(() => {
    const p = document.querySelector('.assessment-page');
    const s = window.AssessmentState;
    return !!p && !p.hasAttribute('inert') && !!s && s.isLoading === false;
})()"""

# The instructed answers, from attention_checks.json.
ATTENTION = {"atc_01": 3, "atc_02": 4}
SCORE_KEYS = (
    "nfc_total", "lgo_learning", "lgo_prove", "lgo_avoid",
    "importance_exam", "importance_clinical", "importance_mastery",
    "importance_reflection",
)


def _wait(page: WimiPage, expr: str, *, ms: int = 15000) -> None:
    for _ in range(ms // 100):
        if page.eval_js(expr):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for: {expr[:90]}")


@pytest.mark.slow
@pytest.mark.regression
def test_completing_every_item_scores_the_administration(
        wimi_session: WimiTestSession, wimi_page: WimiPage):
    wimi_page.goto("assessment")
    _wait(wimi_page, _RELEASED)

    items = wimi_page.eval_js(
        "window.AssessmentState.items.map(i => ({code: i.item_code, kind: i.kind, "
        "min: window.AssessmentState.sections[i.sectionIdx].scale.min, "
        "max: window.AssessmentState.sections[i.sectionIdx].scale.max}))")
    assert len(items) == 57
    assert sum(1 for i in items if i["kind"] == "attention") == 2

    for n, item in enumerate(items):
        _wait(wimi_page, f"window.AssessmentState.index === {n}")
        radios = wimi_page.eval_js(
            "document.querySelectorAll('#assessment-options input[type=radio]').length")
        assert radios == item["max"] - item["min"] + 1, (item, radios)

        value = ATTENTION[item["code"]] if item["kind"] == "attention" \
            else (item["min"] + item["max"]) // 2
        nth = value - item["min"] + 1
        wimi_page.locator(css=f"#assessment-options label:nth-child({nth})").click()
        wimi_page.locator(css="#assessment-next").click()

    _wait(wimi_page, "window.AssessmentState.completed === true")
    _wait(wimi_page, "document.getElementById('assessment-done').hidden === false "
                     "|| !document.getElementById('assessment-done').classList.contains('hidden')")
    assert wimi_page.locator(css="#assessment-progress-label").text() == "Complete"

    # Eight numeric scores on the completion screen, none "not scored".
    shown = wimi_page.eval_js(
        "Array.from(document.querySelectorAll('#assessment-scores dd')).map(d => d.textContent)")
    assert len(shown) == 8
    assert all(s != "not scored" for s in shown), shown
    for s in shown:
        float(s)

    # The database is the evidence (#114's lesson).
    db = wimi_session.user.db
    rec = db.get_latest_scores()
    assert rec is not None and rec.is_complete is True
    assert rec.attention_check_pass is True
    for key in SCORE_KEYS:
        assert getattr(rec, key) is not None, key
    assert len(db.get_assessment_history()) == 1
    assert len(db.get_assessment_responses(rec.id)) == 57
    assert db.get_in_flight_assessment() is None

    # And the dashboard no longer offers it.
    wimi_page.locator(css="#assessment-done a.btn-primary").click()
    _wait(wimi_page, "location.pathname.endsWith('index.html')")
    wimi_page.wait_for_timeout(600)
    assert wimi_page.eval_js(
        "(() => { const b = document.getElementById('assessment-notice'); return !!b && !b.hidden; })()") is False
