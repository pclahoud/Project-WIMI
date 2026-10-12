"""A dialog whose control renders late still gets a background boundary (#422).

The defect, in three functions
------------------------------
``modal_dialog.js`` draws the dialog boundary itself, because ``aria-modal``
does nothing on this engine (measured; see the helper's header). ``sweep()``
calls ``hideBackground(topmost)`` on every pass; ``hideBackground`` caches its
result against the surface it was computed for; and ``hideOutside`` refuses to
hide any subtree holding ``document.activeElement``.

For a dialog whose focusable controls exist but have not rendered yet --
``focusInto`` waits a few sweeps for exactly that case (#374) -- those three
combine into a permanent no-op:

1. **First sweep.** ``focusInto`` defers, so focus is still on the invoker,
   which lives inside the page container. The walk runs anyway, and skips that
   container because it holds focus. **Nothing of the page is hidden.**
2. **Every later sweep.** The surface has not changed, so the cache returns
   before walking. The boundary is never drawn for that dialog's lifetime.

Why this needs an injected dialog
---------------------------------
Neither modal measured in #421 defers -- Settings' warning dialog has its
buttons in markup and the entry form's Manage Error Types modal settled on the
first sweep -- so no page in this tree is known to reproduce it. The probe is
therefore a surface built in the page, which is the technique
``test_modal_focus_follows_any_dialog.py`` already uses and the one the
helper's own ``aria-modal`` measurement used. It needs no call-site wiring:
the helper discovers ``[data-modal-surface]`` from the DOM, so an injected
surface goes through exactly the code a real one does.

Why both arms, and why the control cannot be skipped
----------------------------------------------------
The arms differ in **one** thing: whether the dialog's only control is visible
on the frame it opens. ``control-ready`` must pass on the unfixed tree, which
is what makes ``late-control``'s failure a finding about deferral rather than
about the probe, the focus setup or the accessibility instrument. Each arm also
asserts that it *is* the arm it claims to be -- ``control-ready`` that focus
had already entered the dialog, ``late-control`` that it had not and that the
helper had nonetheless already swept -- so an arm that stops differing fails
loudly instead of quietly agreeing with the other (#121's lesson).

The outcome is read from the accessibility tree, never from ``aria-*``: the
attributes are exactly what stays correct when a node is not in the tree.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.modal_focus import changes, read_timeline, start_timeline, wait_for
from _helpers.page_gate import (
    ax_mentions,
    ax_snapshot,
    ax_summary,
    enable_accessibility,
    wait_for_release,
)

#: A toolbar button that exists only in the page behind the dialog. The exam
#: name would not do: it is also the document title, so the RootWebArea
#: announces it whatever a dialog does (recorded in MODAL_DIALOG.md).
_BACKGROUND_NAME = "Add Root Subject"
_OPENER = "tree-add-root"
_SURFACE = '[data-testid="w422-surface"]'
_CONTROL = "w422-confirm"

#: The frame, counted from the open, on which the deferred control is revealed
#: and the helper's state is sampled. Comfortably inside ``DEFER_SWEEPS`` (10),
#: so the arm measures a deferral that resolves rather than one that times out
#: into ``focusInto``'s surface fallback.
_REVEAL_FRAME = 4


def _inject(page: WimiPage, *, defer: bool) -> None:
    """A closed overlay holding a dialog whose single control may be unrendered.

    Appended to ``<body>``, so the page container is a sibling on the walk's
    path. That is the arrangement most of this tree's markup modals have, and
    the one in which the focus guard can skip the whole page.

    ``visibility: hidden`` rather than ``display: none`` is deliberate for the
    deferring control: ``focusInto`` defers only when a focusable exists and is
    not *visible*, and both properties satisfy that, but a revealed
    ``visibility`` needs no reflow of the dialog's own box.
    """
    page.eval_js(
        "(() => {"
        "  const box = document.createElement('div');"
        "  box.id = 'w422-overlay';"
        "  box.setAttribute('style', 'position:fixed;inset:0;display:none');"
        "  box.innerHTML = '<div data-modal-surface role=\"dialog\" '"
        "    + 'aria-modal=\"true\" aria-labelledby=\"w422-title\" '"
        "    + 'data-testid=\"w422-surface\" style=\"background:#fff\">'"
        "    + '<h2 id=\"w422-title\">W422 Late Control</h2>'"
        "    + '<button type=\"button\" data-testid=\"%s\"%s>Confirm</button>'"
        "    + '</div>';"
        "  document.body.appendChild(box);"
        "})()"
        % (_CONTROL, ' style="visibility:hidden"' if defer else '')
    )


def _open(page: WimiPage, *, defer: bool) -> None:
    """Open it, and sample the helper's state on frame ``_REVEAL_FRAME``.

    ``display`` is one of the attributes the helper's MutationObserver watches,
    so the assignment below *is* the open: the sweep it schedules is the first
    one that sees the surface.

    The sample is taken from inside the page's own frame clock rather than by
    polling from here, so it is a structural observation -- "this is where the
    helper had got to after N sweeps" -- and not a wall-clock race (the reason
    ``_helpers/modal_focus.py`` counts frames at all). The deferring arm reveals
    the control in the same callback, immediately after sampling.
    """
    page.eval_js(
        "(() => {"
        "  const box = document.getElementById('w422-overlay');"
        "  const btn = box.querySelector('button');"
        "  const surface = box.querySelector('[data-modal-surface]');"
        "  const gated = document.querySelector('[data-page-gated]');"
        "  const defer = %s;"
        "  box.style.display = 'block';"
        "  let n = 0;"
        "  const tick = () => {"
        "    if (++n < %d) { requestAnimationFrame(tick); return; }"
        "    const a = document.activeElement;"
        "    window.__w422 = {"
        "      frames: n,"
        "      active: a ? (a.getAttribute('data-testid') || a.tagName) : null,"
        "      swept: !!window.ModalDialog.invokerOf(surface),"
        "      hiddenCount: window.ModalDialog.hiddenCount(),"
        "      containerHidden: gated ? gated.hasAttribute('aria-hidden') : null"
        "    };"
        "    if (defer) btn.style.visibility = 'visible';"
        "  };"
        "  requestAnimationFrame(tick);"
        "})()" % ('true' if defer else 'false', _REVEAL_FRAME)
    )


def _sample(page: WimiPage) -> dict | None:
    return json.loads(page.eval_js("JSON.stringify(window.__w422 || null)"))


def _focus_inside(page: WimiPage) -> bool:
    return bool(page.eval_js(
        "(() => { const s = document.querySelector(%s);"
        " const a = document.activeElement;"
        " return !!(s && a && s.contains(a)); })()" % json.dumps(_SURFACE)))


def _snapshot_once_the_boundary_lands(page: WimiPage, before: dict,
                                      *, tries: int = 30) -> dict:
    """The snapshot after Chromium has caught up with the DOM, or the last one.

    ``modal_dialog.js`` writes its attributes synchronously but the tree is
    handed the change on a later update, so a single snapshot at a fixed delay
    failed most runs on both Windows machines (#350, #371). Polling is a
    ceiling and not a weakening: a helper that hides nothing still exposes
    *more* than the baseline after ~3 s, and the assertions below fail exactly
    as they would without it.
    """
    after = ax_snapshot(page)
    for _ in range(tries):
        if after["exposed"] < before["exposed"]:
            return after
        page.wait_for_timeout(100)
        after = ax_snapshot(page)
    return after


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("defer", [False, True],
                         ids=["control-ready", "late-control"])
def test_the_boundary_is_drawn_whether_or_not_the_control_renders_late(
    wimi_session: WimiTestSession, wimi_page: WimiPage, defer: bool,
) -> None:
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W422 Boundary",
                                  exam_description="Issue #422")
    exam_id = db.get_exam_context_by_name(exam.exam_name).id
    db.create_subject_node(exam_context=exam.exam_name, name="W422 Cardiology",
                           level_type="System")

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    # The page gate, not the markup, is the readiness signal here. `inert`
    # leaves the toolbar in the DOM and takes the whole subtree OUT of the
    # accessibility tree, so waiting on the button alone can take the baseline
    # snapshot while the page exposes five nodes and the gate's own holding
    # message -- measured: `Add Root Subject` absent, and the control assertion
    # below correctly refusing to continue (#121, #127).
    wait_for_release(wimi_page)
    wait_for(wimi_page,
             '!!document.querySelector(\'[data-testid="%s"]\')' % _OPENER,
             what="the tree editor's toolbar to render")
    assert wimi_page.eval_js("typeof window.ModalDialog") == "object", (
        "modal_dialog.js is not loaded on the tree editor, so there is no "
        "boundary to measure at all. Check the <script> tag.")
    enable_accessibility(wimi_page)

    # ---- Assert the controls FIRST -----------------------------------
    before = ax_snapshot(wimi_page)
    assert before["roles"].get("dialog", 0) == 0, (
        f"a dialog is already exposed before anything opened, so this "
        f"scenario would be measuring the wrong one. {ax_summary(before)}")
    assert ax_mentions(before, _BACKGROUND_NAME), (
        f"{_BACKGROUND_NAME!r} is not an exposed accessible name before the "
        f"dialog opens, so 'the background went away' cannot be measured "
        f"against it and the main assertion would be vacuous. "
        f"{ax_summary(before)}")

    # Focus a control in the page behind the dialog, which is what an invoker
    # is. `hideOutside` refuses to hide a subtree holding focus, so this is
    # what makes the page container unhideable until focus moves into the
    # dialog -- the precondition for #422 and for nothing else here.
    wimi_page.eval_js(
        '(() => document.querySelector(\'[data-testid="%s"]\').focus())()'
        % _OPENER)
    assert wimi_page.eval_js(
        "(() => { const a = document.activeElement;"
        " return a ? a.getAttribute('data-testid') : null; })()") == _OPENER, (
        f"focus did not land on {_OPENER!r}, so the page container does not "
        f"hold document.activeElement, the walk has nothing to skip, and this "
        f"arm would pass against the unfixed helper.")

    # ---- Act ---------------------------------------------------------
    _inject(wimi_page, defer=defer)
    start_timeline(wimi_page, _SURFACE, '[data-testid="%s"]' % _OPENER)
    _open(wimi_page, defer=defer)

    # Wait for the SAMPLE before waiting for focus. The control arm settles
    # focus on the first sweep, so a poll that stops at "focus is inside" can
    # return before frame `_REVEAL_FRAME` has run at all and read the sample as
    # absent -- measured, and it reads exactly like the frame callback never
    # firing.
    wait_for(wimi_page, "typeof window.__w422 !== 'undefined'",
             what="the helper's state to be sampled on frame %d" % _REVEAL_FRAME)
    for _ in range(80):
        if _focus_inside(wimi_page):
            break
        wimi_page.wait_for_timeout(50)
    frames = read_timeline(wimi_page)
    sample = _sample(wimi_page)
    assert sample is not None, (
        f"the frame sampled at frame {_REVEAL_FRAME} never ran, so neither "
        f"arm's precondition can be checked: {changes(frames)}")

    # ---- Assert this arm is the arm it says it is --------------------
    if defer:
        assert sample["swept"], (
            f"by frame {_REVEAL_FRAME} the helper had not yet recorded an "
            f"invoker for the surface, so it had not swept and focus sitting "
            f"outside the dialog says nothing about deferral. The probe is "
            f"not reproducing #422's precondition. Sample: {sample}")
        assert sample["active"] == _OPENER, (
            f"the control was still unrendered at frame {_REVEAL_FRAME} and "
            f"focus was already at {sample['active']!r} rather than on the "
            f"invoker, so focusInto() did not defer and this arm is NOT "
            f"measuring #422. Fix the probe; do not relax the assertion. "
            f"Timeline: {changes(frames)}")
        assert sample["containerHidden"] is False, (
            f"while focus was still outside the dialog the walk had already "
            f"hidden the page container, which it is documented never to do "
            f"for a subtree holding document.activeElement. Either that rule "
            f"changed -- in which case say so in modal_dialog.js and in "
            f"docs/guides/MODAL_DIALOG.md -- or this arm no longer reproduces "
            f"the no-op walk #422 is about. Sample: {sample}")
    else:
        assert sample["active"] == _CONTROL, (
            f"the control arm deferred too: focus was at "
            f"{sample['active']!r} at frame {_REVEAL_FRAME} rather than on "
            f"the dialog's button, so it is not a control -- both arms would "
            f"fail together and the deferring arm's failure would say nothing "
            f"about deferral. Timeline: {changes(frames)}")

    assert _focus_inside(wimi_page), (
        f"focus never reached the dialog, so what follows would be measuring "
        f"a stuck page rather than the boundary. Timeline: {changes(frames)}")

    # ---- Assert the boundary, through the accessibility tree ---------
    after = _snapshot_once_the_boundary_lands(wimi_page, before)
    assert after["roles"].get("dialog", 0) >= 1, (
        f"the injected surface is not exposed as a dialog, so the probe is "
        f"malformed rather than the helper broken. {ax_summary(after)}")
    assert not ax_mentions(after, _BACKGROUND_NAME), (
        f"{_BACKGROUND_NAME!r} is still an exposed accessible name with the "
        f"dialog open, so the page behind it was never taken out of the "
        f"accessibility tree: arrowing past the end of the dialog walks into "
        f"the page it covers, with no boundary (#422). hideBackground() caches "
        f"its result against the surface, and the first sweep's walk hid "
        f"nothing of the page because the container held focus while "
        f"focusInto() waited for a control to render -- so the cache recorded "
        f"an attempt where it had to record a drawn boundary.\n"
        f"frame {_REVEAL_FRAME} sample: {sample}\n"
        f"before: {ax_summary(before)}\nafter: {ax_summary(after)}")
    assert after["exposed"] < before["exposed"], (
        f"opening the dialog did not reduce what the accessibility tree "
        f"exposes ({before['exposed']} -> {after['exposed']}), so the "
        f"boundary was not drawn (#422). before: {ax_summary(before)}\n"
        f"after: {ax_summary(after)}")
    held = wimi_page.eval_js("(() => window.ModalDialog.hiddenCount())()")
    assert held > 0, (
        "the accessibility tree shrank but modal_dialog.js is holding zero "
        "aria-hidden attributes, so something else caused it -- the engine "
        "has started honouring aria-modal, or the page simply rendered less. "
        "Either way this is no longer measuring what it says (#319).")
