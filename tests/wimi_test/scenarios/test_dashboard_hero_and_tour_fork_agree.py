"""Regression: the dashboard's hero and the tour's `has-exams` fork read one value.

#620 decided that the dashboard step *"the Create Your First Exam button, or the
exam cards once you have one"* is a fork, and #430 that it must read
`applyHeroState`'s own predicate rather than derive the painted state again
(#313's two outcomes drifted exactly that way). `applyHeroState` now records
what it was handed as `LandingState.hasExams`, and the fork reads that.

This asserts the agreement in both states, plus the two anchors the fork's sides
resolve to. `LandingState` is a top-level `const`, so it is read by its bare
name: `window.LandingState` is `undefined` with no error (CLAUDE.md's
`EntryState` hazard).
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

READ = """
(() => {
  const rendered = sel => {
    const el = document.querySelector(sel);
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  return {
    hasExams: LandingState.hasExams,
    heroCompact: !!document.querySelector('.landing-header--compact'),
    createButton: rendered('[data-testid="dashboard-create-first-exam"]'),
    examCard: rendered('[data-tour-anchor="exam-card"]'),
  };
})()
"""


def _settled(page: WimiPage) -> dict:
    page.goto("dashboard")
    for _ in range(100):
        state = page.eval_js(
            "(() => { try { return LandingState.isLoading === false"
            " && LandingState.hasExams !== null; } catch (e) { return false; } })()")
        if state:
            break
        page.wait_for_timeout(100)
    return page.eval_js(READ)


@pytest.mark.slow
@pytest.mark.regression
def test_with_no_exams_the_fork_and_the_hero_both_say_no(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    seen = _settled(wimi_page)
    assert seen["hasExams"] is False, seen
    assert seen["heroCompact"] is False, seen
    assert seen["createButton"] is True and seen["examCard"] is False, (
        f"the fork's unforked side must be the thing on screen: {seen!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_with_an_exam_the_fork_and_the_hero_both_say_yes(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db.create_exam_context(exam_name="Fork exam", exam_description="")
    db.conn.commit()

    seen = _settled(wimi_page)
    assert seen["hasExams"] is True, seen
    assert seen["heroCompact"] is True, seen
    assert seen["examCard"] is True and seen["createButton"] is False, (
        f"the fork's forked side must be the thing on screen: {seen!r}")
