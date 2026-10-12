"""The entry form's first-run tour, through its real wiring (#430).

The last wired page. Most of its steps render once the form is released,
including the question bank button's five slides. Three need the seed below:
the timer's Pause exists only in a timed session, and a note card's Delete and
a thumbnail's Delete only on an entry carrying a note and an image, so the
session is timed and opens on such a draft. The tag-context pill exists only
for a primary subject with two or more parents, so the form re-starts its tour
when a pill mounts.
This walks both and checks what the resolve guard cannot:

- the tour starts AFTER the form's gate releases, which is after the rich text
  editors report ready (#114), recorded at the moment the panel is inserted;
- each step's panel names the control it spotlights;
- the order follows the window's height, at two pinned viewports (#752).

The tour sorts by screen position when it starts (#682 decision 2), and Save &
Next sits in a sticky footer, so its top is the window's height less the
footer's while the reflection editor stays where the page put it. Below the
crossing, Save & Next comes first. That is the feature, so both sides are
asserted, with the viewport pinned through `Emulation.setDeviceMetricsOverride`
rather than inherited from whatever window the machine gives. The app asks
for 1400x900 (`main_window.py`); a display that cannot grant it clamps the
window, and on Windows machine B (2256x1504 at 200%) that left 1130x689, Save
& Next first and this test failing, while every machine that granted the
request passed. A test pinned to one viewport could no longer fail for that
reason, so it asserts both, and that they differ.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import FORM_READY, poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PANEL = """(() => {
  const p = document.querySelector('[data-testid="tour-panel"]');
  if (!p) return null;
  return {count: p.querySelector('[data-testid="tour-count"]').textContent,
          title: p.querySelector('[data-testid="tour-title"]').textContent,
          text: p.querySelector('[data-testid="tour-text"]').textContent};
})()"""
PANEL_OPEN = "!!document.querySelector('[data-testid=\"tour-panel\"]')"
GATE_AT_START = """
(() => {
  new MutationObserver((records, observer) => {
    for (const r of records) for (const n of r.addedNodes) {
      if (n.nodeType === 1 && n.getAttribute('data-testid') === 'tour-panel') {
        const page = document.querySelector('.entry-page');
        window.__tourGateAtStart = page ? page.hasAttribute('inert') : 'no page';
        observer.disconnect();
        return;
      }
    }
  }).observe(document, {childList: true, subtree: true});
})();
"""


def _panels_through_the_tour(page: WimiPage) -> list[dict]:
    panels = []
    for _ in range(30):
        panel = page.eval_js(PANEL)
        if panel is None:
            return panels
        panels.append(panel)
        page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    raise AssertionError(f"the tour did not end: {[p['title'] for p in panels]}")


def _titles_through_the_tour(page: WimiPage) -> list[str]:
    return [panel["title"] for panel in _panels_through_the_tour(page)]


# Two viewports either side of the crossing. They illustrate real
# configurations rather than being constants anything derives: CLAMPED is this
# project's reference viewport (CLAUDE.md, tour_steps.js) and Windows machine
# B's window, where the app's 1400x900 request was refused; GRANTED is a
# height above the crossing that a granted request gives. Measured on master
# d6ba47e: the editor's top is ~646 px at any height and Save & Next's is the
# height less 77, so they cross near 723 px. Above roughly 1153 px Save & Next
# would also pass the dictation button; that third order is not claimed here.
CLAMPED = (1130, 689)
GRANTED = (1400, 828)
BOXES = """(() => { const box = a => { const r = WimiTour.resolveAnchor(a).getBoundingClientRect();
  return {top: r.top, height: r.height}; };
  return {editor: box('entry-form-reflection-editor'), save: box('entry-form-save-next-button')}; })()"""


def _set_viewport(page: WimiPage, width: int, height: int) -> None:
    """Pin the CSS viewport, and prove it took (as test_dashboard_hero_and_session_order)."""
    page.tab._tab.Emulation.setDeviceMetricsOverride(
        width=width, height=height, deviceScaleFactor=0, mobile=False)
    got = json.loads(page.eval_js(
        "JSON.stringify({w: window.innerWidth, h: window.innerHeight})"))
    assert (got["w"], got["h"]) == (width, height), (
        f"the viewport override did not apply: asked for {width}x{height}, got {got}")


SCROLL_TO_TOP = ("(() => { window.scrollTo(0, 0); for (const el of document.querySelectorAll('*'))"
                 " if (el.scrollTop) el.scrollTop = 0; })()")


def _editor_then_save(page: WimiPage) -> bool:
    """Whether the reflection editor is above Save & Next, and that nothing else decides it.

    The editor is far more than three times the button's height, so the tour's
    row banding (`sameRow`) never ties them. The order is then their tops
    alone, which is why it flips cleanly at a height rather than being flaky
    near one.
    """
    b = page.eval_js(BOXES)
    assert b["editor"]["height"] > 3 * b["save"]["height"], b
    assert b["editor"]["top"] != b["save"]["top"], b
    return b["editor"]["top"] < b["save"]["top"]


# The question bank explainer: five slides on one button, in chapter 52's
# section order (#682 decision 3). The order is the manual's, because slides on
# one anchor share a screen position; these openings pin it.
BANK = "About: Show your question bank beside this form"
BANK_SLIDE_OPENINGS = [
    "This button puts a browser",
    "The named buttons in the pane's toolbar",
    "A pop-up a site opens",
    "The pane keeps its own logins",
    "WIMI never reads the page",
]


@pytest.mark.slow
@pytest.mark.regression
def test_the_released_form_then_a_tag_context_pill_each_show_their_steps(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Tour entry", exam_description="")

    def subject(title, level, parent=None):
        return db.create_subject_node_with_weight(
            exam_context="Tour entry", name=title, level_type=level, parent_id=parent)

    cardiology = subject("Cardiology", "System")
    nephrology = subject("Nephrology", "System")
    shared = subject("Hypertension", "Topic", cardiology.id)
    db.add_edge(nephrology.id, shared.id, is_primary=False)
    # Timed, so the timer's Pause button is drawn; a draft carrying a note and
    # an image, so a note card's Delete and a thumbnail's Delete are too.
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=3,
        session_name="Tour entry", date_encountered=date.today(),
        session_duration_minutes=30)
    draft = db.create_question_entry(
        review_session_id=session.id, user_answer="A", correct_answer="B",
        reflection="<p>R</p>")
    assert draft.is_draft
    db.add_entry_note(draft.id, content_html="<p>A note</p>")
    db.add_entry_media(draft.id, "no-such-file-uuid", original_filename="tour.png",
                       mime_type="image/png", file_size_bytes=10,
                       linked_subject_ids=[cardiology.id])
    db.conn.commit()

    wimi_page.goto("entry-form", query={"session_id": session.id})
    assert poll(wimi_page, FORM_READY, timeout_ms=60000)
    assert not wimi_page.eval_js(PANEL_OPEN), "the tour must be off until a scenario turns it on"
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    wimi_page.tab.Page.enable()
    wimi_page.tab.Page.addScriptToEvaluateOnNewDocument(source=GATE_AT_START)
    wimi_page.eval_js("window.__previousDocument = true")
    # Pinned before the navigation the tour starts on, and checked after it
    # rather than set again: a tour started at the harness's own height would
    # pass the tall list anyway, so only the check shows the pin held.
    _set_viewport(wimi_page, *CLAMPED)
    wimi_page.goto("entry-form", query={"session_id": session.id})
    assert poll(wimi_page, "window.__previousDocument !== true", timeout_ms=10000)
    assert wimi_page.eval_js("[innerWidth, innerHeight]") == list(CLAMPED), (
        "the viewport override did not survive the navigation")
    assert poll(wimi_page, FORM_READY, timeout_ms=60000)
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "the form did not start its tour"
    assert wimi_page.eval_js("window.__tourGateAtStart") is False, (
        "the tour started over a form that was still gated (true), or the "
        "recorder never saw .entry-page")

    assert wimi_page.eval_js(PANEL)["count"] == "Tip 1"
    # Screen order (#682): the header left to right -- the timer's Pause, Add
    # Entries, the question bank button -- then the save status, the form as a
    # whole and its rows top to bottom. The footer is sticky, so Save & Next
    # sits at the bottom of the window and comes before whatever is below it:
    # at the reference viewport, that includes the reflection editor.
    assert not _editor_then_save(wimi_page), "at 1130x689 Save & Next must be above the editor"
    panels = _panels_through_the_tour(wimi_page)
    titles = [p["title"] for p in panels]
    # The dictation button names what pressing it will do, so its label is a
    # state (#748): "Download and speak" where the engine is bundled and the
    # model is not yet downloaded -- every built app's first run -- and
    # "Speak" in a checkout with no vendor/whisper, or once the model is
    # here. The tip must name whichever label the student is looking at.
    speak = wimi_page.eval_js(
        "document.querySelector('[data-testid=\"dictation-reflection-button\"]"
        " .dictation-btn-label').textContent")
    assert speak in ("Speak", "Download and speak"), speak
    assert titles[:2] == ["About: Pause timer", "About: Add more entry slots"], titles
    assert titles[2:7] == [BANK] * 5, titles
    for panel, opening in zip(panels[2:7], BANK_SLIDE_OPENINGS):
        assert panel["text"].startswith(opening), (opening, panel["text"])
    clamped = [
        "About: Save status",
        "About: Entry form",
        "About: Question ID / Reference",
        "About: Subjects",
        "About: Tags",
        # Save & Next, named by its label, which says what is still missing.
        "About: Complete required fields",
        "About: Why did you get this wrong?",
        # The dictation button's dot is aria-hidden, so it is not in the name.
        f"About: {speak}",
        "About: Notes",
        "About: Delete this note",
        "About: Media Attachments",
        # + Add existing, named by its aria-label: its title is a state
        # tooltip, rewritten as candidates load.
        "About: Add existing images",
        "About: Delete",
    ]
    assert titles[7:] == clamped, titles

    # The same form when the window was granted: Save & Next's footer is below
    # the reflection editor, so its tip comes after it. That one move is the
    # whole difference, and the difference is the feature (#752).
    wimi_page.eval_js("window.api.resetTour()", await_promise=True)
    _set_viewport(wimi_page, *GRANTED)
    # The first walk scrolled each target into view; a student starts at the top.
    wimi_page.eval_js(SCROLL_TO_TOP)
    assert _editor_then_save(wimi_page), "at 1400x828 the editor must be above Save & Next"
    wimi_page.eval_js("WimiTour.start('entry-form')", await_promise=True)
    granted_titles = _titles_through_the_tour(wimi_page)
    save, editor = "About: Complete required fields", "About: Why did you get this wrong?"
    expected_granted = [t for t in clamped if t != save]
    expected_granted.insert(expected_granted.index(editor) + 1, save)
    assert granted_titles[7:] == expected_granted, granted_titles
    assert granted_titles[:7] == titles[:7], granted_titles

    # The rule, stated over both walks so it cannot quietly become one band
    # walked twice: if a layout change ever put both viewports on one side of
    # the crossing, the two lists above would be edited to match and nothing
    # would fail. This does.
    walks = {"1130x689": titles, "1400x828": granted_titles}
    assert walks["1130x689"] != walks["1400x828"], walks
    save_first = [name for name, t in walks.items() if t.index(save) < t.index(editor)]
    assert save_first == ["1130x689"], walks

    # The student tags a primary subject that has two parents: the pill mounts
    # and the tour re-starts for its one step.
    wimi_page.eval_js(f"addSubjectChip('primary', {{id: {shared.id}, name: 'Hypertension',"
                      f" level_type: 'Topic'}})")
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "mounting the pill did not re-start the tour"
    assert _titles_through_the_tour(wimi_page) == ["About: Tag context: Cardiology"]
