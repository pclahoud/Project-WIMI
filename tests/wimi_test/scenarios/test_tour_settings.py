"""Settings' first-run tour, through its real wiring (#430).

`test_tour_anchors_resolve.py` proves each step's anchor renders in some
state; `test_tour_view_change.py` proves the runner rebuilds on a view change
with fixture steps. This walks the REAL steps through the page's own three
call sites -- the release at the end of init(), a sidebar click (five panels
carry steps besides Appearance), and an exam chosen for Per-Exam Analytics --
and checks what the resolve guard cannot:

- the tour starts AFTER the page gate releases (`.app-container` is inert
  until then), recorded at the moment the panel is inserted;
- each step's panel names the control it spotlights (the title standard,
  #430 comment #9292).
"""
from __future__ import annotations

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

READY = ("(() => { try { return settingsPage.isPageReady === true; }"
         " catch (e) { return false; } })()")
PANEL = """(() => {
  const p = document.querySelector('[data-testid="tour-panel"]');
  if (!p) return null;
  return {count: p.querySelector('[data-testid="tour-count"]').textContent,
          title: p.querySelector('[data-testid="tour-title"]').textContent};
})()"""
PANEL_OPEN = "!!document.querySelector('[data-testid=\"tour-panel\"]')"
GATE_AT_START = """
(() => {
  new MutationObserver((records, observer) => {
    for (const r of records) for (const n of r.addedNodes) {
      if (n.nodeType === 1 && n.getAttribute('data-testid') === 'tour-panel') {
        const page = document.querySelector('.app-container');
        window.__tourGateAtStart = page ? page.hasAttribute('inert') : 'no page';
        observer.disconnect();
        return;
      }
    }
  }).observe(document, {childList: true, subtree: true});
})();
"""


def _titles_through_the_tour(page: WimiPage) -> list[str]:
    """Every panel title from here to the tour's end, pressing Next."""
    titles = []
    for _ in range(20):
        panel = page.eval_js(PANEL)
        if panel is None:
            return titles
        titles.append(panel["title"])
        page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    raise AssertionError(f"the tour did not end: {titles}")


def _click_panel(page: WimiPage, panel: str) -> None:
    page.eval_js(f"document.querySelector('.settings-nav-item[data-panel=\"{panel}\"]').click()")


@pytest.mark.slow
@pytest.mark.regression
def test_each_view_shows_its_steps_after_the_gate_naming_their_controls(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db.create_exam_context(exam_name="Tour settings", exam_description="")
    # A bank with an address, so its row draws the Desktop site switch.
    db.create_question_source(source_name="Tour bank", url="https://example.org")
    db.conn.commit()

    wimi_page.goto("settings")
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert not wimi_page.eval_js(PANEL_OPEN), "the tour must be off until a scenario turns it on"
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    wimi_page.tab.Page.enable()
    wimi_page.tab.Page.addScriptToEvaluateOnNewDocument(source=GATE_AT_START)
    wimi_page.eval_js("window.__previousDocument = true")
    wimi_page.goto("settings")
    assert poll(wimi_page, "window.__previousDocument !== true", timeout_ms=10000)
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "the page did not start its tour"

    assert wimi_page.eval_js("window.__tourGateAtStart") is False, (
        "the tour started over a page that was still gated (true), or the "
        "recorder never saw .app-container")

    # The release: Appearance is the default panel.
    assert wimi_page.eval_js(PANEL)["count"] == "Tip 1"
    # Screen order (#682): Reset and Save share the toolbar row, Reset on the
    # left, although Save's top is 1 px higher.
    assert _titles_through_the_tour(wimi_page) == [
        "About: Reset what Save covers", "About: Save", "About: Primary color swatch"]

    # A sidebar click.
    _click_panel(wimi_page, "question_banks")
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "a panel switch did not re-start the tour"
    # The panel's title, then the bank row's switch beneath it (#682).
    assert _titles_through_the_tour(wimi_page) == [
        "About: Question Banks", "About: Desktop site"]
    for panel, titles in (
        ("data_backup", ["About: Enable Cloud Sync"]),
        ("mcp_server", ["About: Enable MCP Server"]),
        ("profile", ["About: Export profile…"]),
        ("addons", ["About: Install from .zip"]),
    ):
        _click_panel(wimi_page, panel)
        assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), panel
        assert _titles_through_the_tour(wimi_page) == titles, panel

    # Per-Exam Analytics renders its Save only once an exam is chosen, so the
    # panel switch alone shows nothing new and the selection is what shows it.
    _click_panel(wimi_page, "dashboard_analytics")
    wimi_page.wait_for_timeout(500)
    assert not wimi_page.eval_js(PANEL_OPEN), wimi_page.eval_js(PANEL)
    wimi_page.eval_js("(() => { const s = document.getElementById('analytics_exam_selector');"
                      " s.selectedIndex = 1; s.dispatchEvent(new Event('change')); })()")
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "choosing an exam did not re-start the tour"
    assert _titles_through_the_tour(wimi_page) == ["About: Save Exam Analytics"]

    for _ in range(50):
        seen = wimi_page.eval_js("window.api.getTourState().then(s => s.seen)",
                                 await_promise=True)
        if len(seen) == 10:
            break
        wimi_page.wait_for_timeout(100)
    assert sorted(seen) == sorted(f"settings:{a}" for a in (
        "settings-save", "settings-reset-defaults", "settings-appearance-primary-color-picker",
        "settings-question-banks", "settings-profile-export",
        "settings-analytics-save-exam-config", "settings-qbank-desktop",
        "settings-sync-enable", "settings-mcp-server-enabled",
        "settings-addons-install")), seen
