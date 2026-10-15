"""The self-assessment page (#766 Wave 2): gated until its items arrive, one
item at a time, and an answer is in the database the moment Next is pressed.

Three scenarios through the real app. The fuller set -- the whole flow to
completion, skip-and-banner, attention checks -- is Wave 4; these are the
smoke the page must pass to land at all.

Clicks are hit-tested through the harness (`locator().click()`), never
`el.click()`, which bypasses hit-testing and passes against an `inert` page
(#114's trap). State is read from `window.AssessmentState`, which the page
exposes on window on purpose: a top-level `const` would be invisible to
`eval_js` (CLAUDE.md, Testing).
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

GATE_RELEASE_MS = 15000

_RELEASED = """(() => {
    const p = document.querySelector('.assessment-page');
    const s = window.AssessmentState;
    return !!p && !p.hasAttribute('inert') && !!s && s.isLoading === false;
})()"""


def _wait_released(page: WimiPage) -> None:
    for _ in range(GATE_RELEASE_MS // 100):
        if page.eval_js(_RELEASED):
            return
        page.wait_for_timeout(100)
    raise AssertionError("the assessment page never released its gate")


def _wait_index(page: WimiPage, expected: int) -> None:
    for _ in range(50):
        if page.eval_js("window.AssessmentState.index") == expected:
            return
        page.wait_for_timeout(100)
    raise AssertionError(
        f"index did not reach {expected}: {page.eval_js('window.AssessmentState.index')}")


@pytest.fixture
def assessment(wimi_session: WimiTestSession, wimi_page: WimiPage) -> WimiPage:
    wimi_page.goto("assessment")
    _wait_released(wimi_page)
    return wimi_page


@pytest.mark.slow
@pytest.mark.regression
def test_the_page_releases_its_gate_with_the_whole_flow_loaded(assessment: WimiPage):
    state = assessment.eval_js(
        "({ n: window.AssessmentState.items.length,"
        "   idx: window.AssessmentState.index,"
        "   sections: window.AssessmentState.sections.map(s => s.name),"
        "   err: window.AssessmentState.error,"
        "   first: window.AssessmentState.items[0].prompt })"
    )
    assert state["err"] is None
    assert state["sections"] == ["nfc", "lgo", "importance"]
    assert state["n"] == 57 and state["idx"] == 0

    # The legend IS the current item's prompt -- asserted against the payload
    # rather than a literal, so Wave 5 populating the stubs does not break it.
    assert assessment.locator(css="#assessment-prompt").text() == state["first"]
    assert state["first"].strip()
    assert assessment.locator(css="#assessment-progress-label").text() == "Question 1 of 57"

    # Nothing to press until an answer is chosen; nothing to go back to.
    assert assessment.eval_js("document.getElementById('assessment-next').disabled") is True
    assert assessment.eval_js("document.getElementById('assessment-prev').disabled") is True
    # Nine options: NFC is the paper's nine-point scale (decision 9).
    assert assessment.eval_js(
        "document.querySelectorAll('#assessment-options input[type=radio]').length") == 9


@pytest.mark.slow
@pytest.mark.regression
def test_an_answer_reaches_the_database_when_next_is_pressed(
        assessment: WimiPage, wimi_session: WimiTestSession):
    assessment.locator(css="#assessment-options label:nth-child(4)").click()
    assert assessment.eval_js("document.getElementById('assessment-next').disabled") is False

    assessment.locator(css="#assessment-next").click()
    _wait_index(assessment, 1)
    assert assessment.locator(css="#assessment-progress-label").text() == "Question 2 of 57"

    # The row, not the page, is the evidence (#114's lesson: a page can look
    # right and have kept nothing).
    db = wimi_session.user.db
    rec = db.get_in_flight_assessment()
    assert rec is not None and rec.is_complete is False
    rows = db.get_assessment_responses(rec.id)
    assert [(r.item_code, r.raw_response) for r in rows] == [("nfc_01", 4)]
    assert rows[0].response_time_ms >= 0


@pytest.mark.slow
@pytest.mark.regression
def test_reloading_resumes_at_the_first_unanswered_item(assessment: WimiPage):
    assessment.locator(css="#assessment-options label:nth-child(2)").click()
    assessment.locator(css="#assessment-next").click()
    _wait_index(assessment, 1)

    # A second goto to the same page returns before the new document commits:
    # mark the old one and wait for the mark to vanish (scenario README).
    assessment.eval_js("window.__assessmentOldDocument = true")
    assessment.goto("assessment")
    for _ in range(100):
        if assessment.eval_js("window.__assessmentOldDocument === undefined"):
            break
        assessment.wait_for_timeout(100)
    _wait_released(assessment)

    assert assessment.eval_js("window.AssessmentState.index") == 1
    assert assessment.eval_js("window.AssessmentState.responses['nfc_01']") == 2
    assert assessment.locator(css="#assessment-progress-label").text() == "Question 2 of 57"
    # Previous is live now, so the restored answer can be seen.
    assert assessment.eval_js("document.getElementById('assessment-prev').disabled") is False
