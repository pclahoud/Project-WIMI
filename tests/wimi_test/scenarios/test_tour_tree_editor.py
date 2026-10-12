"""The tree editor's first-run tour, through its real wiring (#430, #664, #682).

Twenty-five steps: eight on a weighted tree's first screen, the shared-parents
chip once a branch is open, the Archived subjects panel, Export all on an exam
with dimensions, three inside the import preview, four inside the page's own
modals and the opened Archived panel, and seven in the details panel once a
subject is selected.

The page differs from the ones wired before it in four ways, each checked
here because the resolve guard cannot see them:

- **Its rows are redrawn by innerHTML** on every expand, collapse and
  selection. So the page re-starts its tour from `renderTree()`, and the runner
  keeps an open tip by its key, re-resolved, rather than by the node it pointed
  at, which is gone. Kept, the tip is redrawn without taking focus from the row
  control the student pressed.
- **Two targets arrive after the gate releases**: the Archived subjects panel,
  whose load init does not await, and the shared-parents chip, which sits on a
  child row and renders only once that row is expanded.
- **Tips are drawn over modals**: the import preview's scope notice, its plan
  heading and its "... more" line, and in the page's own Add Child and delete
  modals. Which of a tip and a modal held focus was a race (measured: tip,
  modal, and tip-then-modal in three runs), so modal_dialog.js now leaves
  focus with a companion. The tip moves Tab between its own controls, which
  the modal's trap would otherwise take; Tab past its last control enters the
  dialog; closing it puts focus in the dialog, never outside it.
- **A closed modal still has a box.** These modals fade out by `visibility`,
  which the runner's rendered check does not read, so an anchor in a closed
  modal would resolve and ring nothing visible. Every modal anchor is set when
  its modal opens and removed when it closes, and closing a modal closes its
  tip; that is asserted for all three. The scope notice's anchor exists only on
  a whole-exam file, the one kind its text is about; the "... more" line's only
  when the preview left something out.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

READY = ("(() => { try { return TreeState.isPageReady === true; }"
         " catch (e) { return false; } })()")
PANEL = """(() => {
  const p = document.querySelector('[data-testid="tour-panel"]');
  if (!p) return null;
  return {count: p.querySelector('[data-testid="tour-count"]').textContent,
          title: p.querySelector('[data-testid="tour-title"]').textContent,
          text: p.querySelector('[data-testid="tour-text"]').textContent};
})()"""
PANEL_OPEN = "!!document.querySelector('[data-testid=\"tour-panel\"]')"
# The ring has a 0.15 s transition (tour.css) and the panel has none, so this
# is polled, never read once (#672).
RING_ON = """((id) => {
  const ring = document.querySelector('[data-testid="tour-ring"]');
  const el = WimiTour.resolveAnchor(id);
  if (!ring || !el) return false;
  const a = ring.getBoundingClientRect(), b = el.getBoundingClientRect();
  return b.width > 0 && a.left <= b.left && a.top <= b.top
      && a.right >= b.right && a.bottom >= b.bottom;
})"""
GATE_AT_START = """
(() => {
  new MutationObserver((records, observer) => {
    for (const r of records) for (const n of r.addedNodes) {
      if (n.nodeType === 1 && n.getAttribute('data-testid') === 'tour-panel') {
        const page = document.querySelector('.tree-page');
        window.__tourGateAtStart = page ? page.hasAttribute('inert') : 'no page';
        observer.disconnect();
        return;
      }
    }
  }).observe(document, {childList: true, subtree: true});
})();
"""
PREVIEW = """(async (text, name, outside) => {
  const f = new File([text], name, {type: 'application/json'});
  await window.handleImportFileEnhanced({target: {files: [f], value: name}});
  if (outside) document.getElementById('btn-import').focus();
})"""
WEIGHT_TEXT = "A weight is a share of the whole exam at any depth"
FOCUS = """(() => {
  const a = document.activeElement;
  if (!a) return null;
  if (a.closest('[data-testid="tour-panel"]')) return 'tip:' + (a.dataset.testid || '');
  if (a.closest('#import-preview-modal')) return 'dialog';
  return a.tagName + '#' + a.id;
})()"""


def _next(page: WimiPage) -> None:
    page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")


def _rest_of_the_tour(page: WimiPage) -> list[dict]:
    panels = []
    for _ in range(30):
        panel = page.eval_js(PANEL)
        if panel is None:
            return panels
        panels.append(panel)
        _next(page)
    raise AssertionError(f"the tour did not end: {panels}")


def _open_with_the_tour_on(page: WimiPage, exam_id: int) -> None:
    page.goto("tree-editor", query={"exam_id": exam_id})
    assert poll(page, READY, timeout_ms=30000)
    assert not page.eval_js(PANEL_OPEN), "the tour must be off until a scenario turns it on"
    page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    page.tab.Page.enable()
    page.tab.Page.addScriptToEvaluateOnNewDocument(source=GATE_AT_START)
    page.eval_js("window.__previousDocument = true")
    page.goto("tree-editor", query={"exam_id": exam_id})
    assert poll(page, "window.__previousDocument !== true", timeout_ms=10000)
    assert poll(page, READY, timeout_ms=30000)
    assert poll(page, PANEL_OPEN, timeout_ms=10000), "the page did not start its tour"
    assert page.eval_js("window.__tourGateAtStart") is False, (
        "the tour started over a page that was still gated (true), or the "
        "recorder never saw .tree-page")


def _tab(page: WimiPage) -> None:
    page.tab.Input.dispatchKeyEvent(type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9)
    page.tab.Input.dispatchKeyEvent(type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)


def _preview(page: WimiPage, payload: dict, name: str, focus_outside: bool = False) -> None:
    page.eval_js(f"{PREVIEW}({json.dumps(json.dumps(payload))}, {name!r}, "
                 f"{'true' if focus_outside else 'false'})", await_promise=True)


def _titles_until(page: WimiPage, last: str) -> list[str]:
    """Titles from the open tip through the one titled `last`, which is left
    open."""
    titles = []
    for _ in range(30):
        panel = page.eval_js(PANEL)
        assert panel is not None, f"the tour ended before {last!r}: {titles}"
        titles.append(panel["title"])
        if panel["title"] == last:
            return titles
        _next(page)
    raise AssertionError(f"never reached {last!r}: {titles}")


@pytest.mark.slow
@pytest.mark.regression
def test_a_weighted_tree_shows_its_steps_keeps_a_tip_through_a_redraw_and_holds_the_weight_step(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Tour tree", exam_description="")

    def subject(name, level, low, high, parent=None):
        return db.create_subject_node_with_weight(
            exam_context="Tour tree", name=name, level_type=level, parent_id=parent,
            exam_weight_low=low, exam_weight_high=high)

    cardiology = subject("Cardiology", "System", 10, 20)
    nephrology = subject("Nephrology", "System", 15, 25)
    shared = subject("Hypertension", "Topic", 5, 8, cardiology.id)
    db.add_edge(nephrology.id, shared.id, is_primary=False)
    doomed = subject("Renal artery stenosis", "Topic", 1, 2, nephrology.id)
    db.conn.commit()
    db.delete_subject_subtree(doomed.id)
    db.conn.commit()

    _open_with_the_tour_on(wimi_page, exam.id)
    # Nothing is held any more. tree-row-weight was, from #677 until #664's
    # fix removed the feasibility badge its text contradicted; the sentence
    # is true now and the step shows. Asserted as an empty list rather than
    # dropped, so a step held in future is a visible change here.
    held = [r for r in wimi_page.eval_js("WimiTour.inspect('tree-editor')") if r["held"]]
    assert held == [], f"no tree-editor step should be held (#664): {held}"
    # And the released step's anchor still resolves, which is what the hold
    # was keeping proven while its text waited.
    weight = [r for r in wimi_page.eval_js("WimiTour.inspect('tree-editor')")
              if r["anchor"] == "tree-row-weight"]
    assert [(r["anchor"], r["resolved"]) for r in weight] == [("tree-row-weight", True)], weight

    # Screen order (#682): the header's buttons left to right, the toolbar's
    # filter, then the first row: its name, then its chips.
    assert wimi_page.eval_js(PANEL)["count"] == "Tip 1"
    assert _titles_until(wimi_page, "About: System") == [
        "About: Import Hierarchy",
        "About: Import format help",
        "About: Export the dimension you are editing, as a subject tree",
        "About: Filter subjects",
        "About: Cardiology",
        "About: System",  # the level chip
    ]

    # Expand All redraws every row. The open tip stays, its ring moves to the
    # chip drawn in the old one's place, and focus stays on the button.
    wimi_page.eval_js("document.querySelector('[data-testid=\"tree-expand-all\"]').focus()")
    wimi_page.eval_js("document.querySelector('[data-testid=\"tree-expand-all\"]').click()")
    assert poll(wimi_page, "!!WimiTour.resolveAnchor('tree-row-shared-parents')", timeout_ms=5000)
    assert poll(wimi_page, f"{RING_ON}('tree-row-level')", timeout_ms=5000), (
        f"the redraw moved the tour off the tip being read: {wimi_page.eval_js(PANEL)}")
    assert wimi_page.eval_js(PANEL)["title"] == "About: System"
    assert wimi_page.eval_js(
        "document.activeElement && document.activeElement.dataset.testid") == "tree-expand-all", (
        "redrawing the open tip took focus from the control the student pressed")

    panels = _rest_of_the_tour(wimi_page)
    titles = [p["title"] for p in panels]
    # The kept tip first, then screen order (#682): the weight chip beside it
    # on the same row, the shared chip on the row below, then the Archived
    # panel and the total further down.
    assert titles == [
        "About: System",
        "About: Range: 10%–20%",
        "About: This subject lives in 2 places. Click to manage parents.",
        "About: Archived subjects",
        "About: Published ranges total 25–45% of the exam.",
    ], titles
    # The weight step's TEXT is shown now, not just its title. It was held
    # while the feasibility badge contradicted it (#664); the badge is gone,
    # so "WIMI never compares the two" is true and the step may teach it.
    #
    # Read from the panels this walk collected, NOT from a live DOM query.
    # The version here before #664 was
    #   assert not [...querySelectorAll('[data-testid="tour-text"]')]
    #              .some(t => t.textContent.startsWith(WEIGHT_TEXT))
    # and it could not fail: _rest_of_the_tour returns once the panel is
    # gone, so that query always found zero nodes and `not false` always
    # passed. The hold was really guarded by the titles list above.
    assert any(p["text"].startswith(WEIGHT_TEXT) for p in panels), (
        f"the released weight step should show its text; got "
        f"{[p['text'][:40] for p in panels]}")

    # A whole-exam file's preview gets the scope tip, above the plan's;
    # closing the preview closes the tip.
    _preview(wimi_page, {"dimensions": [{"name": "System", "root_nodes": []}]}, "whole.json")
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "opening the preview did not re-start the tour"
    assert wimi_page.eval_js(PANEL)["title"].startswith(
        "About: \U0001F4E6 This file describes every dimension"), wimi_page.eval_js(PANEL)
    wimi_page.eval_js("hideImportPreviewModal()")
    assert poll(wimi_page, "!" + PANEL_OPEN, timeout_ms=5000), (
        f"the tip outlived the preview it is about: {wimi_page.eval_js(PANEL)}")


@pytest.mark.slow
@pytest.mark.regression
def test_a_dimensioned_exam_tips_over_the_import_preview_and_tab_reaches_the_tip(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Tour tree axes", exam_description="")
    axis = db.create_dimension(exam_id=exam.id, name="System", display_order=1, is_required=True)
    db.create_subject_node(exam_context="Tour tree axes", name="Cardio", level_type="System",
                           dimension_id=axis)
    db.conn.commit()

    # The dimensioned load path, the common one, starts the tour too. Its root
    # carries no weight, so "No weights are set" is drawn and gets no tip.
    _open_with_the_tour_on(wimi_page, exam.id)
    # Export all shows on this exam alone. The weight chip on THIS exam titles
    # itself "User Defined" rather than a range, because the root carries no
    # weight band and the chip falls back to its source -- which is #678's
    # shape (a description in a `title`, a terse name in the text) and not
    # this test's business. Asserted as measured so the next reader knows it
    # is the observed value, not a chosen one.
    assert [p["title"] for p in _rest_of_the_tour(wimi_page)] == [
        "About: Import Hierarchy", "About: Import format help",
        "About: Export the dimension you are editing, as a subject tree",
        "About: Export every dimension of this exam as one whole-exam file",
        "About: Filter subjects",
        "About: Cardio", "About: System", "About: User Defined"]
    assert wimi_page.eval_js("!!document.querySelector('.weight-range-total')")

    # A one-tree file's preview draws the notice ("Importing into dimension")
    # and gets no scope tip: that tip is about a file that can archive an
    # axis, and this one cannot. It does get the plan's tip, which is true of
    # every file, and a five-level file gets the tip on what is left undrawn.
    deep = {"root_nodes": [{"name": "Cardio", "children": [{"name": "B", "children": [
        {"name": "C", "children": [{"name": "D", "children": [{"name": "E"}]}]}]}]}]}
    _preview(wimi_page, deep, "one.json")
    assert poll(wimi_page, "document.getElementById('import-dimension-notice').innerText"
                           ".includes('Importing into dimension')", timeout_ms=5000)
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "opening the preview did not re-start the tour"
    assert [p["title"] for p in _rest_of_the_tour(wimi_page)] == [
        "About: ... and 1 more nested node", "About: What this import will do"]
    wimi_page.eval_js("hideImportPreviewModal()")
    for anchor in ("tree-import-preview-more", "tree-import-plan"):
        assert not wimi_page.eval_js(f"!!WimiTour.resolveAnchor({anchor!r})"), (
            f"{anchor} still resolves in the closed preview")

    # Focus is put outside the dialog before the tip arrives, the order the
    # race also produced: closing the tip must still land inside the dialog.
    whole = {"dimensions": [{"name": "System", "root_nodes": [{"name": "Cardio"}]}]}
    _preview(wimi_page, whole, "whole.json", focus_outside=True)
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "opening the preview did not re-start the tour"
    panel = wimi_page.eval_js(PANEL)
    assert panel["title"].startswith("About: \U0001F4E6 This file describes every dimension"), panel
    assert poll(wimi_page, f"{RING_ON}('tree-import-scope-notice')", timeout_ms=5000)

    # The tip holds focus. The dialog's own focus move ran before it here, and
    # the race also ran it after; re-running it on the open tip (the dialog
    # re-opened, which is how modal_dialog.js sees an open) is that order, made
    # certain. The tip must keep focus through it.
    assert poll(wimi_page, FOCUS + " === 'tip:tour-panel'", timeout_ms=3000), wimi_page.eval_js(FOCUS)
    wimi_page.eval_js("document.getElementById('import-preview-modal').classList.remove('active')")
    wimi_page.wait_for_timeout(1000)  # past the fade, so it reads as closed
    wimi_page.eval_js("document.getElementById('import-preview-modal').classList.add('active')")
    wimi_page.wait_for_timeout(1000)
    assert wimi_page.eval_js(FOCUS) == "tip:tour-panel", (
        f"the dialog took focus from the tip: {wimi_page.eval_js(FOCUS)}")

    # Tab reaches the tip's own controls although a modal is open, and past
    # the last one it enters the dialog rather than stopping.
    for expected in ("tip:tour-more", "tip:tour-skip", "tip:tour-next", "dialog"):
        _tab(wimi_page)
        assert wimi_page.eval_js(FOCUS) == expected, (
            f"Tab went to {wimi_page.eval_js(FOCUS)!r}, not {expected!r}")

    # Done puts focus in the dialog, not back outside it.
    wimi_page.eval_js("document.querySelector('[data-testid=\"tour-next\"]').click()")
    assert poll(wimi_page, "!" + PANEL_OPEN, timeout_ms=5000)
    assert wimi_page.eval_js(FOCUS) == "dialog", wimi_page.eval_js(FOCUS)


@pytest.mark.slow
@pytest.mark.regression
def test_the_page_modals_and_the_archived_panel_tip_while_open_and_close_with_them(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Tour tree modals", exam_description="")
    cardiology = db.create_subject_node_with_weight(
        exam_context="Tour tree modals", name="Cardiology", level_type="System",
        exam_weight_low=10, exam_weight_high=20)
    db.create_subject_node_with_weight(
        exam_context="Tour tree modals", name="Heart failure", level_type="Topic",
        parent_id=cardiology.id)
    doomed = db.create_subject_node_with_weight(
        exam_context="Tour tree modals", name="Renal", level_type="System")
    db.conn.commit()
    db.delete_subject_subtree(doomed.id)
    db.conn.commit()

    _open_with_the_tour_on(wimi_page, exam.id)
    # The page's own steps first, so what follows is only the modals'. None
    # of them is shown on load: each anchor exists only while its view is open.
    on_load = [p["title"] for p in _rest_of_the_tour(wimi_page)]
    assert "About: Level Type" not in on_load and "About: Delete" not in on_load, on_load
    assert "About: Restore" not in on_load, on_load

    # A row's + opens Add Child, whose Level Type is suggested from the parent.
    wimi_page.eval_js(f"document.querySelector('[data-testid=\"tree-node-add-child-{cardiology.id}\"]').click()")
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "opening Add Child did not re-start the tour"
    assert wimi_page.eval_js(PANEL)["title"] == "About: Level Type"
    assert poll(wimi_page, f"{RING_ON}('tree-add-child-level')", timeout_ms=5000)
    wimi_page.eval_js("hideAddNodeModal()")
    assert poll(wimi_page, "!" + PANEL_OPEN, timeout_ms=5000), (
        f"the tip outlived the Add Child modal: {wimi_page.eval_js(PANEL)}")
    assert not wimi_page.eval_js("!!WimiTour.resolveAnchor('tree-add-child-level')"), (
        "the level step's anchor still resolves in the closed Add Child modal")
    # Add Root Subject suggests nothing from a parent, so its select has no tip.
    wimi_page.eval_js("document.getElementById('btn-add-root').click()")
    wimi_page.wait_for_timeout(800)
    assert not wimi_page.eval_js("!!WimiTour.resolveAnchor('tree-add-child-level')")
    wimi_page.eval_js("hideAddNodeModal()")

    # A row's bin opens the delete modal. The Keep checkbox appears once the
    # preview has loaded, and re-starts the tour; whether that lands before or
    # after the first start draws the Delete tip is a race, so the two are
    # compared as a set.
    wimi_page.eval_js(f"document.querySelector('[data-testid=\"tree-node-delete-{cardiology.id}\"]').click()")
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "opening the delete modal did not re-start the tour"
    assert poll(wimi_page, "!document.getElementById('delete-promote-row').classList.contains('hidden')",
                timeout_ms=5000)
    wimi_page.wait_for_timeout(500)
    first = wimi_page.eval_js(PANEL)["title"]
    _next(wimi_page)
    second = wimi_page.eval_js(PANEL)
    assert second is not None, "the delete modal showed one tip, not two"
    assert sorted([first, second["title"]]) == sorted([
        "About: Delete", "About: Keep \"Heart failure\" — move it to the top level"]), (
        first, second)
    # Both anchors sit on controls that keep a box in the closed modal, so
    # only removing them stops a later tour pointing into it. Read directly:
    # which tip is open at the close is the race above.
    wimi_page.eval_js("hideDeleteModal()")
    assert poll(wimi_page, "!" + PANEL_OPEN, timeout_ms=5000), (
        f"the tip outlived the delete modal: {wimi_page.eval_js(PANEL)}")
    for anchor in ("tree-delete-confirm", "tree-delete-promote"):
        assert not wimi_page.eval_js(f"!!WimiTour.resolveAnchor({anchor!r})"), (
            f"{anchor} still resolves in the closed delete modal")

    # Opening the Archived panel shows its Restore buttons, and the first
    # carries the tip.
    wimi_page.eval_js("document.getElementById('archived-panel-toggle').click()")
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), "opening the Archived panel did not re-start the tour"
    assert [p["title"] for p in _rest_of_the_tour(wimi_page)] == ["About: Restore"]


# Screen order down the panel (#682): Basic Information's Name, the circle on
# the parent that is not primary, the weight panel's two badges, then the Q
# toggle, the anchor box and Rebalance siblings. The last title is the
# button's own `title`, cut at the runner's 60 characters.
PANEL_TITLES = [
    "About: Name",
    "About: Click to make this the primary parent",
    "About: Relative",
    "About: Confidence: low",
    "About: Q",
    "About: Anchor this value (don't auto-adjust on rebalance)",
    "About: Redistribute remaining weight across non-anchored,…",
]
PANEL_ANCHORS = ("tree-edit-name", "tree-parent-make-primary", "tree-weight-type",
                 "tree-weight-confidence", "tree-weight-unit-q", "tree-weight-anchor",
                 "tree-weight-rebalance")
SETTLED_ON = """((name) => {
  const w = document.getElementById('weight-modal-child-name');
  return !!w && w.textContent.trim() === name;
})"""


@pytest.mark.slow
@pytest.mark.regression
def test_the_details_panel_tips_its_controls_for_the_subject_on_screen(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The details panel's seven steps (#682, unblocked by #346).

    The panel is the one part of this page that is redrawn per subject, and
    its weight editor keeps the PREVIOUS subject's markup on screen until the
    next one has loaded (#346's measuring hazard). So every wait here is on
    content naming the subject under test, and the editor's anchors are
    dropped the moment a new subject is chosen: a tip on the Q toggle must
    never be drawn for a subject that has none.
    """
    db = wimi_session.user.db
    name = "Tour tree details"
    exam = db.create_exam_context(exam_name=name, exam_description="")
    db.update_exam_length(exam.id, kind="fixed", min=100, max=100, typical=100)
    # Dimensioned on purpose: the plain load path drops relative_weight, so
    # Relative mode cannot appear there (#454).
    axis = db.create_dimension(exam_id=exam.id, name="System", display_order=1,
                               is_required=True)
    cardiology = db.create_subject_node_with_weight(
        exam_context=name, name="Cardiology", level_type="System",
        exam_weight_low=10, exam_weight_high=20, dimension_id=axis)
    nephrology = db.create_subject_node_with_weight(
        exam_context=name, name="Nephrology", level_type="System",
        exam_weight_low=15, exam_weight_high=25, dimension_id=axis)
    hypertension = None
    for title, share in (("Hypertension", 50.0), ("Heart failure", 25.0)):
        child = db.create_subject_node_with_weight(
            exam_context=name, name=title, level_type="Topic",
            parent_id=cardiology.id, relative_weight=share, weight_source="user_defined",
            dimension_id=axis)
        db.conn.execute("UPDATE subject_edges SET relative_weight = ? "
                        "WHERE parent_id = ? AND child_id = ?",
                        (share, cardiology.id, child.id))
        if title == "Hypertension":
            hypertension = child
            db.add_edge(nephrology.id, child.id, is_primary=False)
    db.conn.commit()

    _open_with_the_tour_on(wimi_page, exam.id)
    # Nothing of the panel's is shown before a subject is chosen: the
    # overview is on screen and none of its controls exist yet.
    on_load = _rest_of_the_tour(wimi_page)
    for anchor in PANEL_ANCHORS:
        assert not wimi_page.eval_js(f"!!WimiTour.resolveAnchor({anchor!r})"), (
            f"{anchor} resolves with no subject selected")

    wimi_page.eval_js(f"selectNode({hypertension.id})")
    assert poll(wimi_page, f"{SETTLED_ON}('Hypertension')", timeout_ms=15000), (
        "the weight panel never settled on Hypertension")
    assert poll(wimi_page, PANEL_OPEN, timeout_ms=10000), (
        "selecting a subject did not re-start the tour")
    # The parent rows and the weight editor arrive on separate schedules and
    # each re-starts the tour; let both land before reading the queue.
    assert poll(wimi_page, "!!WimiTour.resolveAnchor('tree-parent-make-primary')"
                           " && !!WimiTour.resolveAnchor('tree-weight-unit-q')",
                timeout_ms=10000)
    wimi_page.wait_for_timeout(500)
    titles = [p["title"] for p in _rest_of_the_tour(wimi_page)]
    assert titles == PANEL_TITLES, titles

    # A root carries an Absolute weight: no Q toggle and no anchor box. The
    # editor still shows Hypertension's markup until the root loads, and the
    # anchors on it are dropped synchronously, in the same turn as the click.
    after_click = wimi_page.eval_js(
        f"(() => {{ selectNode({cardiology.id});"
        " const w = document.getElementById('weight-modal-child-name');"
        " return {on_screen: w ? w.textContent.trim() : null,"
        " stale: ['tree-weight-unit-q', 'tree-weight-anchor', 'tree-weight-type']"
        ".filter(a => !!WimiTour.resolveAnchor(a))}; })()")
    # The control: the old markup really was still drawn at that moment, so
    # the empty list is the anchors being dropped and not the markup gone.
    assert after_click["on_screen"] == "Hypertension", after_click
    assert after_click["stale"] == [], (
        f"the previous subject's controls still carry tips: {after_click}")
    assert poll(wimi_page, "!!WimiTour.resolveAnchor('tree-weight-type')"
                           " && document.querySelector('.weight-type-badge')"
                           ".textContent.trim() === 'Absolute'", timeout_ms=15000)
    for anchor in ("tree-weight-unit-q", "tree-weight-anchor", "tree-parent-make-primary"):
        assert not wimi_page.eval_js(f"!!WimiTour.resolveAnchor({anchor!r})"), (
            f"{anchor} resolves on a top-level subject with an absolute weight")

    # Back to overview hides the panel's controls, and an open tip with them.
    wimi_page.eval_js("document.getElementById('btn-show-overview').click()")
    for anchor in PANEL_ANCHORS:
        assert poll(wimi_page, f"!WimiTour.resolveAnchor({anchor!r})", timeout_ms=5000), (
            f"{anchor} still resolves on the overview")
