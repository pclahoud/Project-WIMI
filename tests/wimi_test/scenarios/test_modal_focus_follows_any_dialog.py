"""Focus follows a dialog in and out within a few frames, whatever the dialog (#374).

``modal_dialog.js`` is the helper behind every modal surface in the app, so
#374's fix is checked on more than the one modal that exposed it
(``test_modal_is_announced_as_a_dialog.py``, the tree editor's delete modal,
opened by a class change and faded in by a ``visibility`` transition):

1. **The relation modal on the subject deep dive** -- a different page, built
   in code rather than markup, and removed from the DOM when it closes.
2. **A dialog with nothing focusable** must still receive focus, on the
   surface itself. #374 made the helper wait a few sweeps for controls that
   exist but have not rendered; a fix that removed the fallback instead would
   leave a text-only dialog unfocusable, so its reachability is pinned here.
3. **A dialog whose only control never renders** must not wait forever -- it
   falls back to the surface once the bounded wait runs out.

Latency is counted in animation frames (see ``_helpers/modal_focus.py``).
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.modal_focus import (
    FRAME_BUDGET,
    changes,
    frames_until,
    read_timeline,
    start_timeline,
    wait_for,
)

_REL_SURFACE = '[data-modal-surface][aria-labelledby="relation-modal-title"]'
_REL_OPENER = '[data-testid="deep-dive-relations-add"]'

#: The helper waits DEFER_SWEEPS sweeps for unrendered controls; a surface
#: whose control never renders lands on the fallback within that plus the
#: usual budget.
_DEFER_SWEEPS = 10


def _active(page: WimiPage, sel: str) -> bool:
    return bool(page.eval_js(
        "(() => { const s = document.querySelector(%r); const a = document.activeElement;"
        " return !!(s && a && s.contains(a)); })()" % sel))


@pytest.mark.slow
@pytest.mark.regression
def test_focus_follows_the_relation_modal_in_and_out(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="F374 Relations", exam_description="#374")
    a = db.create_subject_node(exam_context=exam.exam_name, name="F374 Alpha",
                               level_type="Topic")
    db.create_subject_node(exam_context=exam.exam_name, name="F374 Beta",
                           level_type="Topic")
    db.conn.commit()
    wimi_page.goto("subject-deep-dive", query={"subject": a.id, "exam": exam.id})
    wait_for(wimi_page, "!!document.querySelector(%r)" % _REL_OPENER,
             what="the Link a related topic action")

    # ---- open ----------------------------------------------------------
    start_timeline(wimi_page, _REL_SURFACE, _REL_OPENER)
    wimi_page.locator(testid="deep-dive-relations-add").click()
    for _ in range(60):
        if _active(wimi_page, _REL_SURFACE):
            break
        wimi_page.wait_for_timeout(50)
    wimi_page.wait_for_timeout(100)
    frames = read_timeline(wimi_page)
    shown_at, lag = frames_until(frames, "vis", True, "inside")
    assert shown_at is not None, f"the relation modal never became visible: {changes(frames)}"
    assert lag is not None and lag <= FRAME_BUDGET, (
        f"focus took {lag} frames to enter the relation modal after it became "
        f"visible (budget {FRAME_BUDGET}) (#374). Timeline: {changes(frames)}")

    # ---- close ---------------------------------------------------------
    start_timeline(wimi_page, _REL_SURFACE, _REL_OPENER)
    wimi_page.eval_js(
        "(() => document.querySelector('[data-testid=\"relation-cancel\"]').click())()")
    for _ in range(60):
        if wimi_page.eval_js(
                "(() => { const a = document.activeElement;"
                " return !!(a && a.matches(%r)); })()" % _REL_OPENER):
            break
        wimi_page.wait_for_timeout(50)
    wimi_page.wait_for_timeout(100)
    frames = read_timeline(wimi_page)
    gone_at, lag = frames_until(frames, "vis", False, "onOpener")
    assert gone_at is not None, f"the relation modal never closed: {changes(frames)}"
    assert lag is not None and lag <= FRAME_BUDGET, (
        f"focus took {lag} frames to return to 'Link a related topic' after the "
        f"modal closed (budget {FRAME_BUDGET}) (#374). Timeline: {changes(frames)}")


def _inject_surface(page: WimiPage, inner_html: str) -> None:
    """A hidden overlay + surface, shown by a style change, the way several
    modals here open. Appended to <body> so no page container gates it."""
    page.eval_js(
        "(() => { const b = document.createElement('div');"
        " b.id = 'probe-374'; b.style.display = 'none';"
        " b.innerHTML = '<div data-modal-surface role=\"dialog\" aria-modal=\"true\""
        " aria-label=\"Probe\" data-testid=\"probe-374-surface\">' + %r + '</div>';"
        " document.body.appendChild(b); })()" % inner_html)


def _open_injected_and_measure(page: WimiPage) -> tuple[list[dict], int | None]:
    sel = '[data-testid="probe-374-surface"]'
    start_timeline(page, sel, 'body')
    page.eval_js("document.getElementById('probe-374').style.display = 'block'")
    for _ in range(60):
        if _active(page, sel):
            break
        page.wait_for_timeout(50)
    page.wait_for_timeout(100)
    frames = read_timeline(page)
    return frames, frames_until(frames, "vis", True, "inside")[1]


def _focused_testid(page: WimiPage) -> str | None:
    return page.eval_js(
        "(() => { const a = document.activeElement;"
        " return a ? a.getAttribute('data-testid') : null; })()")


@pytest.mark.slow
@pytest.mark.regression
def test_a_dialog_with_nothing_focusable_still_receives_focus(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    wimi_page.goto("dashboard")
    wait_for(wimi_page, "typeof window.ModalDialog === 'object'",
             what="modal_dialog.js on the dashboard")
    _inject_surface(wimi_page, "<p>Only text. Nothing here takes focus.</p>")
    frames, lag = _open_injected_and_measure(wimi_page)
    assert _focused_testid(wimi_page) == "probe-374-surface", (
        f"a dialog with nothing focusable did not receive focus on its own "
        f"surface; focus is on {_focused_testid(wimi_page)!r}. #374 defers the "
        f"container fallback only while controls exist but have not rendered -- "
        f"it must not remove it. Timeline: {changes(frames)}")
    assert lag is not None and lag <= FRAME_BUDGET, (
        f"an empty dialog took {lag} frames to receive focus (budget "
        f"{FRAME_BUDGET}); with nothing to wait for there should be no wait. "
        f"Timeline: {changes(frames)}")


@pytest.mark.slow
@pytest.mark.regression
def test_a_control_that_never_renders_does_not_hold_focus_back_forever(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    wimi_page.goto("dashboard")
    wait_for(wimi_page, "typeof window.ModalDialog === 'object'",
             what="modal_dialog.js on the dashboard")
    _inject_surface(wimi_page,
                    "<p>A control that stays hidden.</p>"
                    "<button style=\"display:none\">Never shown</button>")
    frames, lag = _open_injected_and_measure(wimi_page)
    assert _focused_testid(wimi_page) == "probe-374-surface", (
        f"the bounded wait for an unrendered control never fell back to the "
        f"surface; focus is on {_focused_testid(wimi_page)!r}. Timeline: "
        f"{changes(frames)}")
    assert lag is not None and lag <= _DEFER_SWEEPS + FRAME_BUDGET, (
        f"falling back took {lag} frames, more than the helper's bounded wait "
        f"({_DEFER_SWEEPS} sweeps) plus {FRAME_BUDGET}. Timeline: {changes(frames)}")
