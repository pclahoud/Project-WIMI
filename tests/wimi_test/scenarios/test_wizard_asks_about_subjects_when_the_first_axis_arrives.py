"""Regression: giving an exam its first axis asks about the subjects it has (#605, #444).

Before this, a Simple exam could not reach the Define Dimensions step at all
without a script (#444: edit mode opens on Exam Info with Back disabled), and
once a script got it there the save created the axis and said nothing while
the exam's whole tree vanished from the tree editor (#605's hazard, measured
on 3b2c208 and again in Wave 0). The owner's decisions: ask each time,
defaulting to moving them in; an axis per top-level subject when several
arrive; Escape and the backdrop are Go back; at most six rows, then expand;
after Keep them aside the success screen opens the tree editor.

Every step here is a real click, starting from #444's new **Add dimensions to
this exam** control: a scenario that called ``selectExamType`` would prove
nothing about the route a student has. On master ``fde66e1`` this file fails
at its first click, because the control does not exist.
"""
from __future__ import annotations

import json
import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.a11y import real_key
from _helpers.first_axis import (
    DIALOG, add_axes_and_save, axes_of, css, dialog_open, dims_of, name_axes,
    next_until_save, open_edit, poll, seed_plain, success_shown, visible)

EIGHT = ["Cardio", "Renal", "Pulm", "GI", "Neuro", "Heme", "Derm", "Endo"]
ROW = '[data-testid="first-axis-row"]'
TOGGLE = '[data-testid="first-axis-more-toggle"]'


def _rows(page: WimiPage):
    return page.eval_js(
        f"[...document.querySelectorAll('{ROW}')].map(r => ["
        " r.querySelector('.first-axis-row-name').textContent,"
        " r.getClientRects().length > 0])")


OPEN_GEOMETRY = """(() => {
  const r = sel => document.querySelector(sel).getBoundingClientRect();
  const s = r('[data-testid="first-axis-dialog"]');
  const t = r('[data-testid="first-axis-dialog"] .first-axis-title');
  const p = r('[data-testid="first-axis-move"]');
  return JSON.stringify({vh: innerHeight, surface_top: s.top, surface_bottom: s.bottom,
                         title_top: t.top, primary_top: p.top, primary_bottom: p.bottom});
})()"""


def _assert_question_and_answer_on_screen(page: WimiPage) -> dict:
    """#922: on open, the question is visible and so is the focused answer.

    The primary button takes focus on open. When the buttons scrolled with
    the content, that focus scrolled the dialog down and the title out of
    view: at innerHeight 739 the title opened at -131 px, at 858 at -18 px.
    """
    g = json.loads(page.eval_js(OPEN_GEOMETRY))
    assert g["title_top"] >= g["surface_top"] - 0.5 and g["title_top"] >= 0, (
        f"#922: the dialog opened with its title scrolled out of view: {g}")
    bottom = min(g["surface_bottom"], g["vh"])
    assert g["primary_top"] >= 0 and g["primary_bottom"] <= bottom + 0.5, (
        f"the focused primary button is not on screen when the dialog opens: {g}")
    return g


def _save_calls(page: WimiPage, since: float) -> int:
    return sum(1 for c in page.get_bridge_calls(since_ts=since)
               if c.get("method") == "saveExamEdit")


@pytest.fixture
def eight(wimi_session: WimiTestSession, wimi_page: WimiPage):
    """A Simple exam with eight top-level subjects; Cardio has AFib beneath it."""
    db = wimi_session.user.db
    exam, ids = seed_plain(db, "First Axis Eight", EIGHT, child_of_first="AFib")
    open_edit(wimi_page, exam.id)
    return wimi_page, db, exam, ids


@pytest.mark.slow
@pytest.mark.regression
def test_six_rows_then_expand_and_each_row_keeps_its_axis(eight):
    page, db, exam, ids = eight
    add_axes_and_save(page, ["System", "Task"])
    assert poll(page, lambda: dialog_open(page), True) is True, (
        "saving the exam's first axes asked nothing about its eight subjects")

    # Listed in the panel's order (sort order, then name): alphabetical here,
    # so Pulm and Renal are the two behind the expand button.
    rows = _rows(page)
    assert [name for name, _ in rows] == sorted(EIGHT)
    assert [shown for _, shown in rows] == [True] * 6 + [False] * 2, rows
    assert page.eval_js(f"document.querySelector('{TOGGLE}').textContent") == "Show 2 more"
    assert page.eval_js(f"document.querySelector('{TOGGLE}').getAttribute('aria-expanded')") == "false"
    assert visible(page, '[data-testid="first-axis-select"]'), (
        "two new axes, so each row must offer a choice")
    assert page.eval_js("document.activeElement.dataset.testid") == "first-axis-move", (
        "focus must start on the primary button")
    _assert_question_and_answer_on_screen(page)

    css(page, TOGGLE).click()
    assert poll(page, lambda: [s for _, s in _rows(page)], [True] * 8) == [True] * 8
    assert page.eval_js(f"document.querySelector('{TOGGLE}').getAttribute('aria-expanded')") == "true"
    assert page.eval_js(f"document.querySelector('{TOGGLE}').textContent") == "Show fewer"
    css(page, TOGGLE).click()  # collapse again: hidden rows must still submit
    assert poll(page, lambda: _rows(page)[7][1], False) is False

    # A per-row choice, by keyboard on the native select: Cardio into Task.
    # Type-ahead ("t" for Task), not ArrowDown: on macOS Blink answers an
    # arrow key on a closed select by opening its popup
    # (LayoutTheme::PopsMenuByArrowKey) and the value never moves, while
    # type-ahead changes the value in place on all three platforms.
    page.eval_js(f"document.querySelector('{ROW} select').focus()")
    real_key(page, "t")
    assert poll(page, lambda: page.eval_js(f"document.querySelector('{ROW} select').value"),
                "1") == "1", "typing 't' did not move Cardio's select to Task"
    assert page.eval_js("document.querySelector('[data-testid=\"first-axis-move\"]').textContent") == "Move them"

    css(page, '[data-testid="first-axis-move"]').click()
    assert poll(page, lambda: success_shown(page), True) is True
    system, task = [d["id"] for d in sorted(db.get_exam_dimensions(exam.id),
                                            key=lambda d: d["display_order"])]
    dims = dims_of(db, exam.exam_name)
    assert (dims["Cardio"], dims["AFib"]) == (task, task), "the per-row choice was lost"
    assert {dims[n] for n in EIGHT[1:]} == {system}, (
        "every other row, the two collapsed ones included, takes the first axis")
    assert page.eval_js("document.getElementById('success-existing-subjects').textContent") \
        == "9 subjects moved into your axes."
    assert not visible(page, '[data-testid="wizard-success-open-tree-editor-button"]'), (
        "after a move there is nothing to go and fix in the tree editor")


@pytest.mark.slow
@pytest.mark.regression
def test_at_a_short_viewport_the_question_and_every_answer_are_reachable(
        wimi_session: WimiTestSession, wimi_page: WimiPage):
    """#922 at the project's reference viewport height, 689 px.

    The harness cannot size the window, so the page's viewport is emulated
    with CDP ``Emulation.setDeviceMetricsOverride``; ``vh`` and
    ``innerHeight`` follow it, which is asserted first so the test cannot
    pass against an override that did not take. Expanded, the eight rows are
    far taller than the dialog, so this also checks the far end: the last
    row scrolls into reach and the buttons never move.
    """
    wimi_page.tab._tab.Emulation.setDeviceMetricsOverride(
        width=1130, height=689, deviceScaleFactor=0, mobile=False)
    try:
        db = wimi_session.user.db
        exam, _ids = seed_plain(db, "First Axis Short", EIGHT, child_of_first="AFib")
        open_edit(wimi_page, exam.id)
        assert wimi_page.eval_js("innerHeight") == 689, "the viewport override did not take"
        add_axes_and_save(wimi_page, ["System", "Task"])
        assert poll(wimi_page, lambda: dialog_open(wimi_page), True) is True
        assert wimi_page.eval_js("document.activeElement.dataset.testid") == "first-axis-move"
        opened = _assert_question_and_answer_on_screen(wimi_page)

        css(wimi_page, TOGGLE).click()
        assert poll(wimi_page, lambda: [s for _, s in _rows(wimi_page)], [True] * 8) == [True] * 8
        wimi_page.eval_js(
            f"[...document.querySelectorAll('{ROW}')].pop().scrollIntoView({{block: 'nearest'}})")
        last = json.loads(wimi_page.eval_js(f"""(() => {{
            const rows = [...document.querySelectorAll('{ROW}')];
            const r = rows[rows.length - 1].getBoundingClientRect();
            const p = document.querySelector('[data-testid="first-axis-move"]').getBoundingClientRect();
            return JSON.stringify({{last_top: r.top, last_bottom: r.bottom, primary_top: p.top}});
        }})()"""))
        assert last["last_top"] >= opened["surface_top"] and last["last_bottom"] <= last["primary_top"], (
            f"the last row cannot be scrolled into view above the answers: {last}, {opened}")
        assert abs(last["primary_top"] - opened["primary_top"]) < 0.5, (
            "scrolling the rows moved the answers; they belong to a footer that does not scroll")
    finally:
        wimi_page.tab._tab.Emulation.clearDeviceMetricsOverride()


@pytest.mark.slow
@pytest.mark.regression
def test_the_expand_button_works_from_the_keyboard(eight):
    page, _db, _exam, _ids = eight
    add_axes_and_save(page, ["System", "Task"])
    poll(page, lambda: dialog_open(page), True)
    page.eval_js(f"document.querySelector('{TOGGLE}').focus()")
    real_key(page, "Enter")
    assert poll(page, lambda: page.eval_js(
        f"document.querySelector('{TOGGLE}').getAttribute('aria-expanded')"), "true") == "true"
    real_key(page, " ")
    assert poll(page, lambda: page.eval_js(
        f"document.querySelector('{TOGGLE}').getAttribute('aria-expanded')"), "false") == "false"


@pytest.mark.slow
@pytest.mark.regression
def test_keep_them_aside_then_the_tree_editor_lists_them(eight):
    page, db, exam, _ids = eight
    add_axes_and_save(page, ["System"])
    poll(page, lambda: dialog_open(page), True)
    assert not visible(page, '[data-testid="first-axis-select"]'), (
        "one new axis is not a choice, so the selects stay hidden")
    assert page.eval_js("document.querySelector('[data-testid=\"first-axis-move\"]').textContent") \
        == "Move them into System"

    css(page, '[data-testid="first-axis-aside"]').click()
    assert poll(page, lambda: success_shown(page), True) is True
    assert axes_of(db, exam.id) == ["System"]
    assert set(dims_of(db, exam.exam_name).values()) == {None}
    assert page.eval_js("document.getElementById('success-existing-subjects').textContent") == (
        "Your existing subjects are listed under Subjects not in any axis in the tree editor.")

    css(page, '[data-testid="wizard-success-open-tree-editor-button"]').click()
    assert poll(page, lambda: page.eval_js("location.pathname.endsWith('tree_editor.html')"),
                True) is True, "Open the tree editor did not open it"
    listed = poll(page, lambda: page.eval_js(
        "document.querySelectorAll('[data-testid^=\"tree-unassigned-row-\"]').length"), 8,
        timeout_ms=20000)
    assert listed == 8, f"the panel lists {listed} of the eight subjects kept aside"


@pytest.mark.slow
@pytest.mark.regression
def test_escape_and_the_backdrop_are_go_back(eight):
    page, db, exam, _ids = eight
    add_axes_and_save(page, ["System"])
    poll(page, lambda: dialog_open(page), True)

    mark = page.mark_bridge_calls()
    real_key(page, "Escape")
    assert poll(page, lambda: dialog_open(page), False) is False, "Escape did not close it"

    css(page, "#btn-create").click()
    assert poll(page, lambda: dialog_open(page), True) is True, "Save did not ask again"
    page.tab.Input.dispatchMouseEvent(type="mouseMoved", x=4, y=4, button="none")
    page.tab.Input.dispatchMouseEvent(type="mousePressed", x=4, y=4, button="left", clickCount=1)
    page.tab.Input.dispatchMouseEvent(type="mouseReleased", x=4, y=4, button="left", clickCount=1)
    assert poll(page, lambda: dialog_open(page), False) is False, "the backdrop did not close it"

    page.wait_for_timeout(300)
    assert _save_calls(page, mark) == 0, "Go back still saved"
    assert not success_shown(page)
    assert axes_of(db, exam.id) == [], "Go back created the axis anyway"
    assert page.eval_js("examWizard.getCurrentStepType()") == "review"


@pytest.mark.slow
@pytest.mark.regression
def test_no_question_on_an_exam_that_already_had_an_axis(wimi_session, wimi_page):
    db = wimi_session.user.db
    exam, _ids = seed_plain(db, "Had An Axis", ["Cardio"])
    db.create_dimension(exam_id=exam.id, name="System", display_order=1)
    db.conn.commit()
    open_edit(wimi_page, exam.id)
    assert not visible(wimi_page, '[data-testid="wizard-add-dimensions-offer"]'), (
        "#444's control must be absent on an exam that has axes (#900)")

    css(wimi_page, "#btn-next").click()
    name_axes(wimi_page, ["Task"], start=1)
    next_until_save(wimi_page)
    css(wimi_page, "#btn-create").click()
    assert poll(wimi_page, lambda: success_shown(wimi_page), True) is True
    assert not dialog_open(wimi_page)
    assert axes_of(db, exam.id) == ["System", "Task"]


@pytest.mark.slow
@pytest.mark.regression
def test_no_question_on_an_exam_with_no_subjects(wimi_session, wimi_page):
    db = wimi_session.user.db
    exam, _ids = seed_plain(db, "No Subjects Yet", [])
    open_edit(wimi_page, exam.id)
    add_axes_and_save(wimi_page, ["System"])
    assert poll(wimi_page, lambda: success_shown(wimi_page), True) is True
    assert not wimi_page.eval_js(f"!!document.querySelector('{DIALOG}')")
    assert axes_of(db, exam.id) == ["System"]
