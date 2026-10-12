"""The first-run tour's runner on the dashboard (#430).

These mostly drive `WimiTour` with fixture steps whose anchors are identifiers,
so they test the runner itself, whatever the chapters' steps say; one runs the
real steps end to end. `test_tour_anchors_resolve.py` is the other half: it
holds every REAL step to the same rules.

What is pinned, each an owner decision or a #430 requirement:
- off under --test-mode until a scenario turns it on;
- a step shows only once its target is rendered, and is recorded as seen;
- a fork reads the page's predicate (the hero's), never the DOM;
- Skip (and Escape) marks the page's steps seen, and Replay brings them back;
- the page behind stays perceivable: no aria-hidden above the target, and a
  non-modal dialog that names its target.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll, seed_empty_session
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FIXTURE_STEPS = [
    {"page": "dashboard", "anchor": "dashboard-create-first-exam",
     "fork": "has-exams", "fork_anchor": "exam-card",
     "text": "Fixture step one, which forks on whether the profile has exams.",
     "chapter": "the_first_hour", "chapter_title": "Your first hour",
     "section": "S", "link": "help_the_first_hour.html"},
    {"page": "dashboard", "anchor": "exam-card-subjects",
     "text": "Fixture step two, which needs an exam card to exist first.",
     "chapter": "the_first_hour", "chapter_title": "Your first hour",
     "section": "S", "link": "help_the_first_hour.html"},
    {"page": "dashboard", "anchor": "no-such-anchor-anywhere",
     "text": "Fixture step three, whose target never renders on this page.",
     "chapter": "the_first_hour", "chapter_title": "Your first hour",
     "section": "S", "link": "help_the_first_hour.html"},
]

PANEL = """
(() => {
  const p = document.querySelector('[data-testid="tour-panel"]');
  const ring = document.querySelector('[data-testid="tour-ring"]');
  if (!p) return null;
  return {
    count: p.querySelector('[data-testid="tour-count"]').textContent,
    title: p.querySelector('[data-testid="tour-title"]').textContent,
    text: p.querySelector('[data-testid="tour-text"]').textContent,
    role: p.getAttribute('role'),
    modal: p.getAttribute('aria-modal'),
    focused: document.activeElement === p,
    ringed: !!ring,
  };
})()
"""


def _open_dashboard(page: WimiPage) -> None:
    page.goto("dashboard")
    assert poll(page, "(() => { try { return LandingState.isLoading === false"
                      " && LandingState.hasExams !== null"
                      " && typeof WimiTour !== 'undefined'; }"
                      " catch (e) { return false; } })()", timeout_ms=30000)


def _start_with_fixture(page: WimiPage) -> int:
    page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    page.eval_js(f"window.WIMI_TOUR_STEPS = {{dashboard: {json.dumps(FIXTURE_STEPS)}}}")
    return page.eval_js("WimiTour.start('dashboard')", await_promise=True)


def _seen(page: WimiPage) -> list:
    return page.eval_js("window.api.getTourState().then(s => s.seen)",
                        await_promise=True)


@pytest.mark.slow
@pytest.mark.regression
def test_it_is_off_under_test_mode_until_a_scenario_turns_it_on(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    _open_dashboard(wimi_page)
    # Positive control: the runner loaded and a target is on screen, so an
    # absent panel means "off", not "broken".
    assert wimi_page.eval_js("!!WimiTour.resolveAnchor('dashboard-create-first-exam')")
    assert wimi_page.eval_js(PANEL) is None
    state = wimi_page.eval_js("window.api.getTourState()", await_promise=True)
    assert state["auto_start"] is False and state["seen"] == []


@pytest.mark.slow
@pytest.mark.regression
def test_a_first_run_shows_only_the_step_it_can_point_at(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    _open_dashboard(wimi_page)
    shown = _start_with_fixture(wimi_page)
    assert shown == 1, f"expected only the Create step on a first run, got {shown}"
    panel = wimi_page.eval_js(PANEL)
    assert panel["count"] == "Tip 1", panel
    assert panel["text"].startswith("Fixture step one"), panel
    assert "Create" in panel["title"], (
        f"the panel must name what it points at: {panel['title']!r}")
    assert panel["role"] == "dialog" and panel["modal"] == "false", panel
    assert panel["focused"] and panel["ringed"], panel
    # The page behind stays perceivable: nothing above the target is hidden.
    assert wimi_page.eval_js(
        "!document.querySelector('[data-testid=\"dashboard-create-first-exam\"]')"
        ".closest('[aria-hidden=\"true\"]')")
    assert _seen(wimi_page) == ["dashboard:dashboard-create-first-exam"]

    wimi_page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    assert wimi_page.eval_js(PANEL) is None


@pytest.mark.slow
@pytest.mark.regression
def test_the_real_dashboard_steps_show_their_first_run_step(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """End to end with the chapters' own steps, not the fixture: a true first
    run shows the one step it can point at, with that step's chapter text."""
    _open_dashboard(wimi_page)
    real = wimi_page.eval_js("window.WIMI_TOUR_STEPS.dashboard")
    create = [s for s in real if s["anchor"] == "dashboard-create-first-exam"]
    assert len(create) == 1, [s["anchor"] for s in real]
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    assert wimi_page.eval_js("WimiTour.start('dashboard')", await_promise=True) == 1
    panel = wimi_page.eval_js(PANEL)
    assert panel["count"] == "Tip 1" and panel["text"] == create[0]["text"], panel
    assert _seen(wimi_page) == ["dashboard:dashboard-create-first-exam"]


@pytest.mark.slow
@pytest.mark.regression
def test_the_fork_follows_the_hero_and_unseen_steps_wait_for_their_target(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db.create_exam_context(exam_name="Tour exam", exam_description="")
    db.conn.commit()
    _open_dashboard(wimi_page)

    shown = _start_with_fixture(wimi_page)
    assert shown == 2, f"fork + subjects should show, the absent one wait: {shown}"
    assert wimi_page.eval_js("WimiTour.inspect('dashboard')[0].used") == "exam-card", (
        "with exams, the fork must point at the exam card, as the hero says")

    wimi_page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    assert wimi_page.eval_js(PANEL)["count"] == "Tip 2"
    wimi_page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    assert wimi_page.eval_js(PANEL) is None
    assert _seen(wimi_page) == ["dashboard:dashboard-create-first-exam",
                                "dashboard:exam-card-subjects"]

    # A second visit has nothing new to show; the absent step still waits.
    assert wimi_page.eval_js("WimiTour.start('dashboard')", await_promise=True) == 0


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("how", ["skip-button", "escape"])
def test_skip_marks_the_whole_page_seen_and_replay_brings_it_back(
    wimi_session: WimiTestSession, wimi_page: WimiPage, how: str,
) -> None:
    _open_dashboard(wimi_page)
    assert _start_with_fixture(wimi_page) == 1
    if how == "skip-button":
        wimi_page.eval_js("document.querySelector('[data-testid=\"tour-skip\"]').click()")
    else:
        wimi_page.eval_js("document.dispatchEvent(new KeyboardEvent('keydown',"
                          " {key: 'Escape', bubbles: true}))")
    assert poll(wimi_page, "document.querySelector('[data-testid=\"tour-panel\"]') === null")
    for _ in range(50):  # the mark is written after the panel closes
        if len(_seen(wimi_page)) == 3:
            break
        wimi_page.wait_for_timeout(100)
    assert len(_seen(wimi_page)) == 3, (
        "Skip must mark every step of the page, shown or not, so a student "
        "who skipped is not interrupted again on the next visit")

    # Replay, through the real Settings control.
    wimi_page.goto("settings")
    assert poll(wimi_page, "!!document.getElementById('tour-replay-btn')"
                           " && !document.querySelector('[data-page-gated][inert]')",
                timeout_ms=30000)
    wimi_page.eval_js("document.getElementById('tour-replay-btn').click()")
    assert poll(wimi_page, "(document.getElementById('tour-replay-status') || {})"
                           ".textContent?.startsWith('Done.') === true")
    assert _seen(wimi_page) == []


@pytest.mark.slow
@pytest.mark.regression
def test_a_broken_step_list_cannot_break_the_dashboard(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The runner never throws: a malformed step list shows nothing and the
    page is still usable. Positive control: the exam card still renders."""
    seed_empty_session(wimi_session.user.db, name="Tour broken")
    _open_dashboard(wimi_page)
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    wimi_page.eval_js("window.WIMI_TOUR_STEPS = {dashboard: [null, 42, {anchor: 7}]}")
    assert wimi_page.eval_js("WimiTour.start('dashboard')", await_promise=True) == 0
    assert wimi_page.eval_js(PANEL) is None
    assert wimi_page.eval_js("!!WimiTour.resolveAnchor('exam-card')")
