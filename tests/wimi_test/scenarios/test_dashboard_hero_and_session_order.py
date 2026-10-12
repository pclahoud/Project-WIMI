"""Regression: the dashboard hero sizes itself, and the session page leads with
its main action (#313).

The owner's decision, 2026-10-05:

* **dashboard hero** — shrink or collapse it once the profile has exams. A
  first-run profile wants it; the 500th launch does not.
* **session setup** — Start New Session goes above the previous-session strip.
* **exam wizard header** — left alone, a wizard being seen once.

Why this needs a scenario at all
--------------------------------
Both halves are claims of the form *"after the page loads, the layout is X"*,
which no pytest against the database layer can see. The hero's size is decided
by `applyHeroState()` from the exam list that `loadExams()` fetches over the
bridge, so the condition only exists in a running app.

The two traps this is written around
------------------------------------
**1. An above-the-fold assertion is vacuous without a control.** "The exam
cards are visible at 1130x689" passes on a page whose header collapsed for an
unrelated reason, on a short page, or on a page that failed to render the
cards at all. So `test_the_compact_hero_is_what_lifts_the_cards` measures the
same element **twice at one viewport** — once compact, once with the hero
forced open — and requires the second to push it *below* the fold. If the
forced-open arm does not, the measurement cannot tell the two apart and says
nothing about the change.

**2. The no-exams state is the one that breaks silently.** The hero is
compact in the markup and expands only when `loadExams()` finds nothing, so a
first-run profile is the arm that exercises the JS. Nobody opens it by
accident, and it is the state the owner's reasoning is *about* — so it gets a
test of its own rather than being assumed from the other arm passing.

Viewport honesty
----------------
Every figure in #313 came from one window: 1130x689 CSS px. Below-the-fold is
a function of window height, so this drives the viewport through CDP's
`Emulation.setDeviceMetricsOverride` rather than inheriting whatever the
harness happens to open, and **asserts the override took effect** before
measuring anything. An unapplied override would silently measure the default
window, which is the same class of mistake as reading a colour off the theme
dictionary instead of the painted pixel (#325).

`const` note: `landing.js` declares `LandingState` at script top level, so
`window.LandingState` is `undefined` and the bare name is what resolves from
`eval_js`. The probes below use class names and geometry instead, which avoids
the question entirely.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

#: #313's own measurement window, so the numbers here are comparable to the
#: ones in the issue.
VIEWPORT_W = 1130
VIEWPORT_H = 689


def _set_viewport(page: WimiPage, width: int, height: int) -> None:
    """Pin the CSS viewport, and prove it took.

    `Emulation.setTimezoneOverride` is already known to work in QtWebEngine
    (#286); this is its neighbour in the same domain and is checked rather
    than assumed, because an override that silently did nothing would leave
    every measurement below describing the harness's default window while
    reading as though it described #313's.
    """
    page.tab._tab.Emulation.setDeviceMetricsOverride(
        width=width, height=height, deviceScaleFactor=0, mobile=False)
    got = json.loads(page.eval_js(
        "JSON.stringify({w: window.innerWidth, h: window.innerHeight})"))
    assert got['w'] == width and got['h'] == height, (
        f'Emulation.setDeviceMetricsOverride did not apply: asked for '
        f'{width}x{height}, page reports {got["w"]}x{got["h"]}. Every '
        f'measurement in this file would otherwise be of the wrong window.')


_HERO_STATE = """
(() => {
  const hero = document.querySelector('[data-testid="dashboard-hero"]');
  if (!hero) return JSON.stringify({found: false});
  const subtitle = hero.querySelector('.landing-subtitle');
  return JSON.stringify({
    found: true,
    compact: hero.classList.contains('landing-header--compact'),
    hero_height: Math.round(hero.getBoundingClientRect().height),
    // The tagline is the thing the compact form drops. Read computed
    // display rather than the class, so this describes the pixels.
    subtitle_display: subtitle
      ? getComputedStyle(subtitle).display : 'absent',
    // Positive control for "the page actually finished": the exam grid is
    // written by loadExams(), the same function that sets the hero state.
    grid_filled: !!(document.querySelector('#exams-grid') || {}).textContent
      && document.querySelector('#exams-grid').textContent.trim().length > 0,
  });
})()
"""


def _seed_exam(db):
    exam = db.create_exam_context(
        exam_name='Hero Exam',
        exam_description="#313 — a profile that has exams",
    )
    db.conn.commit()
    return exam


def _wait_for_grid(page: WimiPage, *, tries: int = 50) -> dict:
    """Poll until loadExams() has written the grid, then read the hero."""
    for _ in range(tries):
        state = json.loads(page.eval_js(_HERO_STATE))
        if state.get('found') and state.get('grid_filled'):
            return state
        page.wait_for_timeout(100)
    return json.loads(page.eval_js(_HERO_STATE))


@pytest.mark.slow
@pytest.mark.regression
def test_a_profile_with_exams_gets_the_compact_hero(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _seed_exam(wimi_session.user.db)

    wimi_page.goto('dashboard')
    state = _wait_for_grid(wimi_page)

    assert state['found'], 'the hero is missing its data-testid'
    assert state['grid_filled'], (
        'the exam grid never rendered, so loadExams() did not complete and '
        'the hero state below was never decided by it')
    assert state['compact'], (
        'a profile WITH exams is showing the full hero. #313: the dashboard '
        'is the page a student opens most often and the hero filled about '
        'the top half of it')
    assert state['subtitle_display'] == 'none', (
        f'the tagline is still laid out ({state["subtitle_display"]}), so '
        f'the compact header still reserves its height')


@pytest.mark.slow
@pytest.mark.regression
def test_a_profile_with_no_exams_keeps_the_full_hero(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    """The arm that exercises the JS, and the one nobody opens by accident.

    The markup ships compact, so this state exists only because
    `applyHeroState(false)` ran. A version of this change that never called
    it would pass the other test and fail here — which is the whole reason
    both arms are written.
    """
    # Deliberately no exam seeded.
    wimi_page.goto('dashboard')

    for _ in range(50):
        state = json.loads(wimi_page.eval_js(_HERO_STATE))
        # The empty state is what loadExams() writes into the grid here.
        if state.get('found') and state.get('grid_filled'):
            break
        wimi_page.wait_for_timeout(100)

    assert state['found'], 'the hero is missing its data-testid'
    assert state['grid_filled'], (
        'the empty state never rendered, so loadExams() did not complete')
    assert not state['compact'], (
        'a first-run profile got the compact hero. The owner\'s reasoning is '
        'that a first run wants the hero; applyHeroState(false) is what '
        'delivers that and appears not to have run')
    assert state['subtitle_display'] != 'none', (
        'the tagline is hidden on a first-run profile, so the welcome the '
        'full hero exists to give is not being given')


@pytest.mark.slow
@pytest.mark.regression
def test_the_compact_hero_is_what_lifts_the_cards(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    """The measurement, with the control that makes it mean something.

    Same element, same viewport, twice: compact, then with the hero forced
    open. If the forced-open arm does not push the cards below the fold, this
    viewport cannot distinguish the two layouts and the compact arm's pass is
    not evidence of anything.
    """
    _seed_exam(wimi_session.user.db)

    wimi_page.goto('dashboard')
    _set_viewport(wimi_page, VIEWPORT_W, VIEWPORT_H)
    _wait_for_grid(wimi_page)

    probe = """
    (() => {
      const grid = document.querySelector('#exams-grid');
      const hero = document.querySelector('[data-testid="dashboard-hero"]');
      const r = grid.getBoundingClientRect();
      return JSON.stringify({
        hero_h: Math.round(hero.getBoundingClientRect().height),
        grid_top: Math.round(r.top),
        viewport_h: window.innerHeight,
        above_fold: r.top < window.innerHeight,
      });
    })()
    """

    compact = json.loads(wimi_page.eval_js(probe))
    assert compact['viewport_h'] == VIEWPORT_H, 'viewport drifted mid-test'
    assert compact['above_fold'], (
        f"with the compact hero the exam grid still starts at "
        f"{compact['grid_top']}px in a {VIEWPORT_H}px window")

    # --- the control: force the hero open and measure again --------------
    wimi_page.eval_js(
        "document.querySelector('[data-testid=\\\"dashboard-hero\\\"]')"
        ".classList.remove('landing-header--compact')")
    wimi_page.wait_for_timeout(300)  # let layout settle
    full = json.loads(wimi_page.eval_js(probe))

    assert full['hero_h'] > compact['hero_h'], (
        f"forcing the hero open did not make it taller "
        f"({full['hero_h']}px vs {compact['hero_h']}px), so the compact "
        f"class is not what controls the hero's height and this test is "
        f"measuring something else")
    assert not full['above_fold'], (
        f"the control failed: with the FULL hero the exam grid starts at "
        f"{full['grid_top']}px, still inside a {VIEWPORT_H}px window. This "
        f"viewport cannot tell the two layouts apart, so the compact arm "
        f"above proves nothing. Either the hero shrank for an unrelated "
        f"reason or this window is too tall to be #313's case.")


@pytest.mark.slow
@pytest.mark.regression
def test_session_setup_leads_with_start_new_session(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    """DOM order **and** tab order, because only one of them is the fix.

    Reordering visually with CSS `order` would satisfy a screenshot and
    still make a keyboard user traverse every card in the strip to reach the
    page's main action. Source order moves both, so both are asserted.
    """
    db = wimi_session.user.db
    exam = _seed_exam(db)
    # Two sessions, so the strip has real content to sit below.
    for i in range(2):
        db.create_review_session(
            exam_context_id=exam.id, total_questions=10, total_incorrect=3,
            session_name=f'Prior {i}', date_encountered=date.today())
    db.conn.commit()

    wimi_page.goto('session-setup', query={'exam_id': exam.id})
    wimi_page.wait_for_timeout(2500)

    order = json.loads(wimi_page.eval_js("""
    (() => {
      const main = document.querySelector('.session-content');
      const kids = Array.from(main.children);
      const newIdx = kids.findIndex(
        el => el.classList.contains('new-session-section'));
      const prevIdx = kids.findIndex(
        el => el.classList.contains('previous-sessions-section'));
      // Tab order follows document order for elements with no tabindex, so
      // compare the two sections' first focusable descendants by position
      // in a flat document-order list of everything focusable.
      const focusables = Array.from(document.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), ' +
        'select:not([disabled]), textarea:not([disabled]), [tabindex]'));
      const firstIn = (sel) => {
        const sec = document.querySelector(sel);
        if (!sec) return -1;
        return focusables.findIndex(f => sec.contains(f));
      };
      return JSON.stringify({
        new_idx: newIdx,
        prev_idx: prevIdx,
        new_tab: firstIn('.new-session-section'),
        prev_tab: firstIn('.previous-sessions-section'),
        // Control: the strip really is populated, so "it comes second" is
        // about ordering and not about an empty section collapsing.
        strip_cards: document.querySelectorAll(
          '#previous-sessions-container .prev-session-card').length,
      });
    })()
    """))

    assert order['new_idx'] >= 0 and order['prev_idx'] >= 0, (
        f'one of the two sections is missing from .session-content: {order!r}')
    assert order['new_idx'] < order['prev_idx'], (
        'Previous Sessions still comes before Start New Session in the DOM')

    assert order['new_tab'] >= 0 and order['prev_tab'] >= 0, (
        f'no focusable element found in one of the sections: {order!r}')
    assert order['new_tab'] < order['prev_tab'], (
        f"Start New Session is above the strip visually but a keyboard user "
        f"still reaches the strip first (tab positions {order['new_tab']} vs "
        f"{order['prev_tab']}) -- that is a CSS reorder, not this fix")

    assert order['strip_cards'] >= 2, (
        f"only {order['strip_cards']} session card(s) rendered, so the strip "
        f"may have collapsed rather than moved -- the ordering assertions "
        f"above would pass for the wrong reason")
