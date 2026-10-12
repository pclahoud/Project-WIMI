"""Session setup's first-run tour, through its real wiring (#430, #682).

`test_tour_anchors_resolve.py` proves each step's anchor renders. This proves
the page actually starts its tour, and what the resolve guard cannot:

- it starts AFTER the page gate releases. Before that the form is `inert`, so
  a tour drawn over it could be neither reached nor read (#430's body);
- the steps run in screen order (#682): the form top to bottom, then the first
  card's Logged count and its buttons left to right;
- the card's first button step points at Continue on an unfinished session and
  at Review on a finished one. Their texts differ (first unfinished entry
  against entry 1), and the anchor sat on the wrong button until #644, which a
  guard that only checks "does it resolve" passed (#430, comment #9236);
- the Edit modal's step (lowering Questions Incorrect deletes entries) exists
  only once the session has a logged entry, and the tour reaches it when Edit
  opens (#682).
"""
from __future__ import annotations

from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from tests.test_tour_wiring import all_steps

READY = ("(() => { try { return SessionState.isPageReady === true; }"
         " catch (e) { return false; } })()")
PANEL_OPEN = "!!document.querySelector('[data-testid=\"tour-panel\"]')"
PANEL = """(() => {
  const p = document.querySelector('[data-testid="tour-panel"]');
  if (!p) return null;
  return {count: p.querySelector('[data-testid="tour-count"]').textContent,
          title: p.querySelector('[data-testid="tour-title"]').textContent,
          text: p.querySelector('[data-testid="tour-text"]').textContent};
})()"""
# Records the gate at the moment the panel is inserted. Read afterwards, the
# gate is released whichever order the page did things in, so only this can
# fail for a tour started before the release. (Not w114's is_inert, which reads
# `.entry-page` and so is false on this page whatever its gate is doing.)
GATE_AT_START = """
(() => {
  new MutationObserver((records, observer) => {
    for (const r of records) for (const n of r.addedNodes) {
      if (n.nodeType === 1 && n.getAttribute('data-testid') === 'tour-panel') {
        const page = document.querySelector('.session-page');
        window.__tourGateAtStart = page ? page.hasAttribute('inert') : 'no page';
        observer.disconnect();
        return;
      }
    }
  }).observe(document, {childList: true, subtree: true});
})();
"""
EDIT = "document.querySelector('.prev-session-actions [onclick^=\"editSession\"]').click()"
EDIT_OPEN = "document.getElementById('edit-session-modal').classList.contains('active')"
FORM = ["About: + Add New", "About: Date Encountered", "About: Questions Incorrect",
        "About: Session Duration (optional)"]


def _text(anchor: str) -> str:
    [step] = [s for s in all_steps()["session-setup"] if s["anchor"] == anchor]
    return step["text"]


def _open_with_the_tour_on(page: WimiPage, exam_id: int) -> None:
    """The flag is off under --test-mode, and the page starts its tour on
    load, so turn it on and then load the page the student would."""
    page.goto("session-setup", query={"exam_id": exam_id})
    assert poll(page, READY, timeout_ms=30000)
    assert not page.eval_js(PANEL_OPEN), "the tour must be off until a scenario turns it on"
    page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    page.tab.Page.enable()
    page.tab.Page.addScriptToEvaluateOnNewDocument(source=GATE_AT_START)
    # A second goto to the same page returns before the new document commits.
    page.eval_js("window.__previousDocument = true")
    page.goto("session-setup", query={"exam_id": exam_id})
    assert poll(page, "window.__previousDocument !== true", timeout_ms=10000)
    assert poll(page, READY, timeout_ms=30000)
    assert poll(page, PANEL_OPEN, timeout_ms=10000), "the page did not start its tour"


def _walk(page: WimiPage) -> list[dict]:
    """Every tip in order, pressing Next until the tour ends."""
    panels = []
    for _ in range(20):
        panel = page.eval_js(PANEL)
        if panel is None:
            return panels
        panels.append(panel)
        page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    raise AssertionError(f"the tour did not end: {[p['title'] for p in panels]}")


@pytest.mark.slow
@pytest.mark.regression
def test_a_first_visit_starts_after_the_gate_with_the_four_form_steps(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Tour setup", exam_description="")
    db.conn.commit()
    _open_with_the_tour_on(wimi_page, exam.id)

    assert wimi_page.eval_js("window.__tourGateAtStart") is False, (
        "the tour started over a page that was still gated (true), or the "
        "recorder never saw .session-page")
    # The duration step says the field starts at the Settings default, 60
    # minutes on a fresh profile, not at No Limit. Read it off the page.
    assert wimi_page.eval_js("document.getElementById('session-duration-preset').value") == "60"
    panels = _walk(wimi_page)
    # No sessions yet, so the card steps have nothing to point at and wait.
    assert panels[0]["count"] == "Tip 1", panels[0]
    assert panels[0]["text"] == _text("session-add-source"), panels[0]
    # The inputs have no text of their own: their name is their <label>.
    assert [p["title"] for p in panels] == FORM, panels
    assert panels[3]["text"] == _text("session-duration"), panels[3]


@pytest.mark.slow
@pytest.mark.regression
def test_an_unfinished_session_points_at_continue_and_has_no_edit_step(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Tour setup", exam_description="")
    db.create_review_session(exam_context_id=exam.id, total_questions=20,
                             total_incorrect=3, session_name="Tour unfinished",
                             date_encountered=date.today())
    db.conn.commit()
    _open_with_the_tour_on(wimi_page, exam.id)

    panels = _walk(wimi_page)
    # The panel names its target from the element itself (tour.js nameOf), so
    # this reads which button the ring is on, not which anchor was asked for.
    assert [p["title"] for p in panels] == FORM + [
        "About: Logged 0/3", "About: Continue", "About: Export IDs", "About: Delete"], panels
    assert panels[5]["count"] == "Tip 6", panels[5]
    assert panels[5]["text"] == _text("session-card-continue"), panels[5]

    # Nothing is logged, so lowering the count can delete nothing and the
    # field carries no step. The finished session below is the other half.
    wimi_page.eval_js(EDIT)
    assert poll(wimi_page, EDIT_OPEN, timeout_ms=5000)
    assert wimi_page.eval_js("WimiTour.resolveAnchor('session-edit-incorrect')") is None


@pytest.mark.slow
@pytest.mark.regression
def test_a_finished_session_points_at_review_and_edit_reaches_its_step(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Tour setup logged", exam_description="")
    subject = db.create_subject_node(exam_context="Tour setup logged", name="Cardio",
                                     level_type="System")
    session = db.create_review_session(exam_context_id=exam.id, total_questions=20,
                                       total_incorrect=1, session_name="Tour finished",
                                       date_encountered=date.today())
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer="A", correct_answer="B",
        reflection="<p>R</p>", explanation="<p>E</p>", primary_subject_ids=[subject.id])
    db.conn.commit()
    assert not entry.is_draft
    _open_with_the_tour_on(wimi_page, exam.id)

    panels = _walk(wimi_page)
    assert [p["title"] for p in panels] == FORM + [
        "About: Logged 1/1", "About: Review", "About: Export IDs", "About: Delete"], panels
    assert panels[5]["text"] == _text("session-card-review"), panels[5]

    # Edit is the student's click that shows the field; the tour re-starts.
    wimi_page.eval_js(EDIT)
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "opening Edit did not re-start the tour"
    panel = wimi_page.eval_js(PANEL)
    assert panel["title"] == "About: Questions Incorrect", panel
    assert panel["text"] == _text("session-edit-incorrect"), panel
    assert panel["count"] == "Tip 9", panel
    # Closed with the tip still open, the tip goes rather than ring a hidden field.
    wimi_page.eval_js("document.getElementById('edit-session-cancel').click()")
    assert poll(wimi_page, "!document.querySelector('[data-testid=\"tour-panel\"]')",
                timeout_ms=10000), "the tip outlived the modal it describes"
