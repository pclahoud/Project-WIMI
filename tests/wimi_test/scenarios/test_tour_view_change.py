"""The tour on a page whose view changes under it (#430).

Settings is the first page that shows different controls without loading a new
document: a panel switch hides the old panel with `display: none` and shows the
new one. So a step's target can stop rendering while it is still in the
document, which "is it still connected" cannot see (measured: the colour swatch
is connected and 0x0 on the Profile panel). The page re-starts its tour on a
view change: settings.js calls `WimiTour.start('settings')` on every sidebar
click. These drive the runner with fixture steps on Settings, so they test the
runner whatever the chapters say.

Pinned:
- a re-start while a step is open rebuilds the tour from what renders now;
- Next skips a queued step whose target stopped rendering;
- two overlapping starts show the tour once, from its first step;
- Replay brings steps back on a page that stays open.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

READY = ("(() => { try { return settingsPage.isPageReady === true"
         " && typeof WimiTour !== 'undefined'; } catch (e) { return false; } })()")


def _step(anchor: str, text: str) -> dict:
    return {"page": "settings", "anchor": anchor, "text": text,
            "chapter": "settings", "chapter_title": "Settings", "section": "S",
            "link": "help_settings.html"}


FIXTURE_STEPS = [
    _step("settings-save", "Fixture: the Save button, always rendered."),
    _step("settings-appearance-primary-color-picker", "Fixture: the swatch, Appearance only."),
    _step("settings-profile-export", "Fixture: Export profile, Profile only."),
]

PANEL = """(() => {
  const panels = document.querySelectorAll('[data-testid="tour-panel"]');
  const p = panels[0];
  if (!p) return null;
  return {n: panels.length,
          count: p.querySelector('[data-testid="tour-count"]').textContent,
          title: p.querySelector('[data-testid="tour-title"]').textContent};
})()"""

# The ring sits on the element the panel names: their boxes overlap.
RING_ON = """((id) => {
  const ring = document.querySelector('[data-testid="tour-ring"]');
  const el = document.querySelector(`[data-testid="${id}"]`);
  if (!ring || !el) return false;
  const a = ring.getBoundingClientRect(), b = el.getBoundingClientRect();
  return b.width > 0 && a.left <= b.left && a.top <= b.top
      && a.right >= b.right && a.bottom >= b.bottom;
})"""


def _open(page: WimiPage) -> None:
    page.goto("settings")
    assert poll(page, READY, timeout_ms=30000)
    page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    page.eval_js(f"window.WIMI_TOUR_STEPS = {{settings: {json.dumps(FIXTURE_STEPS)}}}")


def _switch(page: WimiPage, panel: str) -> None:
    """The student's sidebar click, which the page answers with a re-start."""
    page.eval_js(f"document.querySelector('.settings-nav-item[data-panel=\"{panel}\"]').click()")


def _switch_without_restart(page: WimiPage, panel: str) -> None:
    """The same view change by class toggle alone, so no start() call follows:
    the case a page's view changes under the tour without telling it."""
    page.eval_js("document.querySelectorAll('.settings-panel').forEach(p =>"
                 f" p.classList.toggle('active', p.dataset.panel === {panel!r}))")


def _start(page: WimiPage) -> int:
    return page.eval_js("WimiTour.start('settings')", await_promise=True)


def _next(page: WimiPage) -> None:
    page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")


def _seen(page: WimiPage) -> list:
    return page.eval_js("window.api.getTourState().then(s => s.seen)", await_promise=True)


@pytest.mark.slow
@pytest.mark.regression
def test_a_view_change_mid_step_rebuilds_the_tour_on_what_renders_now(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    _open(wimi_page)
    assert _start(wimi_page) == 2  # Save and the swatch; Export is on a hidden panel
    _next(wimi_page)
    assert wimi_page.eval_js(PANEL)["title"] == "About: Primary color swatch"

    _switch(wimi_page, "profile")  # the page's own handler re-starts the tour
    # Positive control: the swatch is still IN the document, so a
    # connectedness check would not have fired.
    assert wimi_page.eval_js("(() => { const el = document.querySelector("
                             "'[data-testid=\"settings-appearance-primary-color-picker\"]');"
                             " return el.isConnected && el.getBoundingClientRect().width === 0; })()")
    assert poll(wimi_page, f"({PANEL}) && ({PANEL}).title === 'About: Export profile…'",
                timeout_ms=10000), wimi_page.eval_js(PANEL)

    panel = wimi_page.eval_js(PANEL)
    assert panel["n"] == 1, panel
    # Save and the swatch were Tips 1 and 2: the count runs on (#682).
    assert panel["title"] == "About: Export profile…" and panel["count"] == "Tip 3", panel
    # Polled, never read once: the ring carries a 0.15 s transition and the
    # panel none (#672). A rebuild draws a fresh ring today, which does not
    # transition, so a single read passed; a ring reused across a rebuild
    # would make it a race.
    assert poll(wimi_page, f"{RING_ON}('settings-profile-export')", timeout_ms=3000), (
        "the ring is not on the control the panel names")


@pytest.mark.slow
@pytest.mark.regression
def test_next_skips_a_step_whose_target_stopped_rendering(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """A view change the page makes no start() call for. Save stays rendered;
    the swatch queued behind it does not."""
    _open(wimi_page)
    assert _start(wimi_page) == 2
    _switch_without_restart(wimi_page, "profile")
    _next(wimi_page)
    assert wimi_page.eval_js(PANEL) is None, (
        f"Next walked onto a hidden control: {wimi_page.eval_js(PANEL)}")
    for _ in range(50):
        if _seen(wimi_page):
            break
        wimi_page.wait_for_timeout(100)
    # The swatch was never shown, so it still waits for a view it renders in.
    assert _seen(wimi_page) == ["settings:settings-save"]


@pytest.mark.slow
@pytest.mark.regression
def test_two_overlapping_starts_show_the_tour_once_from_its_first_step(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    _open(wimi_page)
    shown = wimi_page.eval_js(
        "Promise.all([WimiTour.start('settings'), WimiTour.start('settings')])",
        await_promise=True)
    assert sorted(shown) == [0, 2], shown
    panel = wimi_page.eval_js(PANEL)
    assert panel["n"] == 1 and panel["count"] == "Tip 1", panel
    assert panel["title"] == "About: Save", panel


@pytest.mark.slow
@pytest.mark.regression
def test_a_restart_with_no_view_change_keeps_the_open_step(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """A page may start again with nothing changed: the wizard re-starts once
    its template cards load. The open step is recorded as seen the moment it
    is shown, so a rebuild that skipped every seen step retired the tip on
    screen: on the wizard's first step, a few milliseconds after showing it,
    and for good."""
    _open(wimi_page)
    assert _start(wimi_page) == 2
    assert wimi_page.eval_js(PANEL)["title"] == "About: Save"
    assert _start(wimi_page) == 2, "the rebuild dropped the step it had open"
    panel = wimi_page.eval_js(PANEL)
    assert panel["n"] == 1 and panel["count"] == "Tip 1", panel
    assert panel["title"] == "About: Save", panel
    assert poll(wimi_page, f"{RING_ON}('settings-save')", timeout_ms=3000), (
        "the ring left the open step's target")


@pytest.mark.slow
@pytest.mark.regression
def test_the_kept_step_stays_in_front_of_an_earlier_step_that_began_rendering(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The ring must not jump off the tip being read. The open step here is
    Export (third in order); the swatch (second, unseen) starts rendering
    without a start() call, then the page starts again. In step order the
    rebuild would draw the swatch, because showStep() draws index 0."""
    _open(wimi_page)
    _switch(wimi_page, "profile")
    assert poll(wimi_page, "(() => { const p = document.querySelector("
                "'[data-testid=\"tour-title\"]'); return !!p && p.textContent === 'About: Save'; })()",
                timeout_ms=10000)
    _next(wimi_page)
    # The ring animates (0.15 s in tour.css), so its box is polled, never read once.
    assert poll(wimi_page, f"{RING_ON}('settings-profile-export')", timeout_ms=3000)
    # Appearance becomes visible too, by class toggle alone: no restart.
    wimi_page.eval_js("document.querySelector('.settings-panel[data-panel=\"appearance\"]')"
                      ".classList.add('active')")
    assert wimi_page.eval_js(
        "document.querySelector('[data-testid=\"settings-appearance-primary-color-picker\"]')"
        ".getClientRects().length > 0"), "the earlier step's target is not rendering"
    assert _start(wimi_page) == 2, "both the kept step and the swatch should be queued"
    assert wimi_page.eval_js(PANEL)["title"].startswith("About: Export profile"), (
        f"the rebuild drew another step over the tip being read: {wimi_page.eval_js(PANEL)}")
    assert poll(wimi_page, f"{RING_ON}('settings-profile-export')", timeout_ms=3000)
    # The kept tip keeps its number through the rebuild (#682).
    assert wimi_page.eval_js(PANEL)["count"] == "Tip 2"


@pytest.mark.slow
@pytest.mark.regression
def test_replay_brings_the_steps_back_on_a_page_that_stays_open(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    _open(wimi_page)
    assert _start(wimi_page) == 2
    _next(wimi_page)
    _next(wimi_page)
    assert wimi_page.eval_js(PANEL) is None
    for _ in range(50):
        if len(_seen(wimi_page)) == 2:
            break
        wimi_page.wait_for_timeout(100)
    assert len(_seen(wimi_page)) == 2
    wimi_page.eval_js("window.api.resetTour()", await_promise=True)
    assert _start(wimi_page) == 2, "steps shown earlier in this document did not come back"
