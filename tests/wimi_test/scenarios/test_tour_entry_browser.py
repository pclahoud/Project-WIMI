"""The entry browser's first-run tour, through its real wiring (#430).

Ten steps render on load; two (the Subject panel's Apply button and its
Include child subjects box) exist on screen only while that panel is open, so
the page re-starts its tour when a filter panel opens (#649's rebuild), and one
(Export All Visible) only in selection mode, which re-starts it too (#682).
This walks all three views and checks what the resolve guard cannot:

- the tour starts AFTER the page gate releases (`.app-container` is inert
  until then), recorded at the moment the panel is inserted;
- each step's panel names the control it spotlights (#430 comment #9292).
"""
from __future__ import annotations

import pytest

from _helpers.w114_form_ready import poll, seed_session_with_draft
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

READY = ("(() => { try { return entryBrowser.isPageReady === true; }"
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
    titles = []
    for _ in range(20):
        panel = page.eval_js(PANEL)
        if panel is None:
            return titles
        titles.append(panel["title"])
        page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    raise AssertionError(f"the tour did not end: {titles}")


@pytest.mark.slow
@pytest.mark.regression
def test_load_then_a_filter_panel_each_show_their_steps_naming_their_controls(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    session_id, _ = seed_session_with_draft(db, name="Tour browse")
    exam_id = db.conn.execute("SELECT exam_context_id FROM review_sessions WHERE id = ?",
                              (session_id,)).fetchone()[0]

    wimi_page.goto("entry-browser", query={"exam": exam_id})
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert not wimi_page.eval_js(PANEL_OPEN), "the tour must be off until a scenario turns it on"
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    wimi_page.tab.Page.enable()
    wimi_page.tab.Page.addScriptToEvaluateOnNewDocument(source=GATE_AT_START)
    wimi_page.eval_js("window.__previousDocument = true")
    wimi_page.goto("entry-browser", query={"exam": exam_id})
    assert poll(wimi_page, "window.__previousDocument !== true", timeout_ms=10000)
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "the page did not start its tour"
    assert wimi_page.eval_js("window.__tourGateAtStart") is False, (
        "the tour started over a page that was still gated (true), or the "
        "recorder never saw .app-container")

    # On load, in screen order (#682): the header's count and Export IDs, the
    # filter row left to right, the search help at the row's end, then the
    # first card's date.
    assert wimi_page.eval_js(PANEL)["count"] == "Tip 1"
    titles = _titles_through_the_tour(wimi_page)
    assert len(titles) == 10, titles
    (count, export_ids, search, subject, tags, date, sort, drafts, search_help,
     card_date) = titles
    assert count.startswith("About: ") and "entries" in count, count
    assert export_ids == "About: Export IDs", export_ids
    assert search == "About: Search entries", search
    assert subject.startswith("About: Subject"), subject
    assert tags.startswith("About: Tags"), tags
    assert date.startswith("About: Date All Time"), date
    assert sort == "About: Date (Newest) ▾", sort
    assert drafts == "About: Drafts only", drafts
    assert search_help == "About: Search syntax help", search_help
    # The card's date, written by formatDate: "Oct 10, 2026".
    assert card_date.startswith("About: ") and card_date[-4:].isdigit(), card_date

    # Opening the Subject panel draws the two steps that live inside it.
    wimi_page.eval_js("document.getElementById('subjectFilterBtn').click()")
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "opening a panel did not re-start the tour"
    # One row in the panel, left to right (#682).
    assert _titles_through_the_tour(wimi_page) == [
        "About: Include child subjects", "About: Apply"]

    # Export IDs shows the selection toolbar and draws its one step.
    wimi_page.eval_js("document.getElementById('enterSelectionBtn').click()")
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), (
        "entering selection mode did not re-start the tour")
    assert _titles_through_the_tour(wimi_page) == ["About: Export All Visible"]
