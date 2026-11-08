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

import json

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


# Two viewports, as test_tour_entry_form.py pins its pair (#755). CLAMPED is
# this project's reference viewport (CLAUDE.md, tour_steps.js) and Windows
# machine B's real window; WIDE is a width at which the filter row does not
# wrap. The tour sorts its stops by getBoundingClientRect (#682), so the row's
# wrapping decides the order and an inherited viewport decides the test.
CLAMPED = (1130, 689)
WIDE = (1400, 900)

# The eight steps whose titles are fixed strings. The other two are written
# from data -- the header's entry count and the first card's date -- so they
# are matched by shape below.
STABLE_TITLES = [
    "About: Export IDs",
    "About: Search entries",
    "About: Date (Newest) ▾",
    "About: Drafts only",
    "About: Search syntax help",
]


def _set_viewport(page: WimiPage, width: int, height: int) -> None:
    """Pin the CSS viewport, and prove it took (as test_tour_entry_form)."""
    page.tab._tab.Emulation.setDeviceMetricsOverride(
        width=width, height=height, deviceScaleFactor=0, mobile=False)
    got = json.loads(page.eval_js(
        "JSON.stringify({w: window.innerWidth, h: window.innerHeight})"))
    assert (got["w"], got["h"]) == (width, height), (
        f"the viewport override did not apply: asked for {width}x{height}, got {got}")


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
    _set_viewport(wimi_page, *CLAMPED)
    wimi_page.eval_js("window.__previousDocument = true")
    wimi_page.goto("entry-browser", query={"exam": exam_id})
    assert poll(wimi_page, "window.__previousDocument !== true", timeout_ms=10000)
    assert wimi_page.eval_js("[innerWidth, innerHeight]") == list(CLAMPED), (
        "the viewport override did not survive the navigation")
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "the page did not start its tour"
    assert wimi_page.eval_js("window.__tourGateAtStart") is False, (
        "the tour started over a page that was still gated (true), or the "
        "recorder never saw .app-container")

    # AT THE REFERENCE VIEWPORT, EVERY STEP IS STILL DRAWN -- but not in the
    # left-to-right order below. At 1130 the filter row wraps, so the search
    # help sits on an earlier visual row than the sort control and #682's
    # screen-order sort follows it. Whether the row SHOULD wrap at this width
    # is an owner question (#926), so this half pins coverage and not order:
    # a step going missing at the reference viewport is a defect either way.
    assert wimi_page.eval_js(PANEL)["count"] == "Tip 1"
    clamped = _titles_through_the_tour(wimi_page)
    assert len(clamped) == 10, clamped
    assert set(STABLE_TITLES) <= set(clamped), (STABLE_TITLES, clamped)
    for prefix in ("About: Subject", "About: Tags", "About: Date All Time"):
        assert any(t.startswith(prefix) for t in clamped), (prefix, clamped)
    assert any(t.startswith("About: ") and "entries" in t for t in clamped), clamped
    assert any(t.startswith("About: ") and t[-4:].isdigit() for t in clamped), clamped

    # Now a width where the row does not wrap, so the documented left-to-right
    # order holds and can be asserted as an order (#682). Same ten steps.
    # The walk above marked every step seen (m031's `tour_seen_steps`), and the
    # tour only auto-starts for steps it has not shown, so the seen list is
    # cleared before the second pass or nothing re-starts.
    wimi_page.eval_js("window.api.resetTour()", await_promise=True)
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    _set_viewport(wimi_page, *WIDE)
    wimi_page.eval_js("window.__previousDocument = true")
    wimi_page.goto("entry-browser", query={"exam": exam_id})
    assert poll(wimi_page, "window.__previousDocument !== true", timeout_ms=10000)
    assert wimi_page.eval_js("[innerWidth, innerHeight]") == list(WIDE), (
        "the viewport override did not survive the navigation")
    assert poll(wimi_page, READY, timeout_ms=30000)
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "the page did not re-start its tour"

    # In screen order (#682): the header's count and Export IDs, the filter row
    # left to right, the search help at the row's end, then the first card's date.
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

    # The two walks must agree about WHICH steps exist, whatever the order.
    assert sorted(clamped) == sorted(titles), (clamped, titles)

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
