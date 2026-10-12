"""The dashboard's first-run tour, through its real wiring (#430, #682).

Every dashboard anchor is drawn by `landing.js` or `analytics_preview.js`, so
the resolve guard (`test_tour_anchors_resolve.py`) proves each one CAN render.
This walks the tour a student actually gets on a profile with one active exam
holding an entry and one suspended exam, which is the state that shows every
step but the no-exams side of the `has-exams` fork, and checks what the
resolve guard cannot:

- the order, which since #701 is screen order and nothing else fixes;
- that each step's panel names the control it spotlights (#430 comment #9292).

The dashboard is not page-gated, so unlike the entry browser there is no gate
to check the tour starts after.
"""
from __future__ import annotations

from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

READY = ("(() => { try { return LandingState.isLoading === false"
         " && LandingState.hasExams !== null; } catch (e) { return false; } })()")
PANEL = """(() => {
  const p = document.querySelector('[data-testid="tour-panel"]');
  if (!p) return null;
  return {count: p.querySelector('[data-testid="tour-count"]').textContent,
          title: p.querySelector('[data-testid="tour-title"]').textContent};
})()"""
PANEL_OPEN = "!!document.querySelector('[data-testid=\"tour-panel\"]')"


def _titles_through_the_tour(page: WimiPage) -> list[str]:
    titles = []
    for _ in range(25):
        panel = page.eval_js(PANEL)
        if panel is None:
            return titles
        titles.append(panel["title"])
        page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    raise AssertionError(f"the tour did not end: {titles}")


def _seed(db) -> None:
    # The suspended exam first, so the active one is newest and its card is
    # drawn first: the card steps then point at the active card.
    parked = db.create_exam_context(exam_name="Tour dash parked", exam_description="")
    db.conn.execute("UPDATE exam_contexts SET is_active = 0 WHERE id = ?", (parked.id,))
    exam = db.create_exam_context(exam_name="Tour dash active", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=3,
        session_name="Tour dash", date_encountered=date.today())
    db.create_question_entry(
        review_session_id=session.id, user_answer="A", correct_answer="B",
        question_id="Q-DASH", reflection="<p>R</p>")
    db.conn.commit()


@pytest.mark.slow
@pytest.mark.regression
def test_the_dashboard_tour_runs_in_screen_order_naming_its_controls(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    _seed(wimi_session.user.db)

    wimi_page.goto("dashboard")
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert not wimi_page.eval_js(PANEL_OPEN), "the tour must be off until a scenario turns it on"
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    wimi_page.eval_js("window.__previousDocument = true")
    wimi_page.goto("dashboard")
    assert poll(wimi_page, "window.__previousDocument !== true", timeout_ms=10000)
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "the page did not start its tour"

    assert wimi_page.eval_js(PANEL)["count"] == "Tip 1"
    # In screen order (#682, measured): Quick Analytics' header left to right,
    # its stats row, then the first exam card (the active one) and its
    # buttons, and last the suspended card's Delete Permanently.
    titles = _titles_through_the_tour(wimi_page)
    assert len(titles) == 10, ascii(titles)
    (exam_list, report, this_week, top_mistake, streak, card, analytics,
     subjects, suspend, delete) = titles
    assert exam_list == "About: All Exams ▼", ascii(exam_list)
    assert report == "About: View Full Report →", ascii(report)
    # #733 recased these three Quick Analytics labels. A tour title comes
    # from the element's own text via `nameOf`, so each step title moved
    # with the label it points at -- which is the dependency worth seeing
    # here rather than only in the CSS diff.
    assert this_week.startswith("About: This Week 1 entries"), ascii(this_week)
    assert top_mistake.startswith("About: Top Mistake"), ascii(top_mistake)
    assert streak.startswith("About: Streak") and streak.endswith("1 day"), ascii(streak)
    # The card has no name of its own, so its title is its text, cut at 60.
    assert card.startswith("About: ") and "Tour dash active" in card, ascii(card)
    assert analytics == "About: View Analytics", analytics
    assert subjects == "About: Edit Subject Tree", subjects
    assert suspend == "About: Suspend Exam", suspend
    assert delete == "About: Permanently Delete Exam", delete
