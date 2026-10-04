"""A modal is announced as a dialog, and focus goes into it and comes back (#319).

Why this cannot be an attribute check
-------------------------------------
``tests/test_modal_dialog_markup.py`` and ``tests/test_modal_dialog_js.py``
guard the attributes, and the attributes are **exactly what stays correct when
the node is not in the accessibility tree** -- #121's lesson, measured there on
the page gate. So the announcement half is read through CDP's
``Accessibility`` domain, which is the tree Chromium hands assistive
technology, and the focus half is driven with real CDP key events rather than
``el.focus()``.

Three things are measured here and nowhere else:

1. **The dialog exists in the tree with a name.** Before the modal opens there
   is no ``dialog`` node at all, which is the positive control that makes "a
   dialog appeared" a finding rather than a tautology.
2. **What ``aria-modal="true"`` does to the background in QtWebEngine.** This
   was measured rather than assumed -- the numbers are in the test body's
   assertion message, and the assertion is written against what Blink actually
   does, not against what the ARIA specification asks of it.
3. **Focus.** It lands inside the dialog on open, Tab wraps inside it, and it
   returns to the button that opened the dialog on close. ``modal_dialog.js``
   does all three with no per-modal wiring, which is what makes modal 46
   correct by default.

What this still cannot do
-------------------------
It is not a screen reader. It reads the exposed tree and the focus ring's
location; it cannot observe an announcement. That a ``role="dialog"`` with a
name is *spoken* on open rests on the specification, as it does for the page
gate's ``role="status"``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.page_gate import (
    ax_mentions,
    ax_snapshot,
    ax_summary,
    enable_accessibility,
)

_SURFACE = '[data-testid="tree-delete-modal-container"]'
_DELETE_BTN = "tree-node-delete-{node_id}"
_CANCEL = '[data-testid="tree-delete-modal-cancel"]'


def _wait_for(page: WimiPage, expression: str, *, what: str, tries: int = 60) -> None:
    for _ in range(tries):
        if page.eval_js(expression):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}: {expression}")


def _focus_state(page: WimiPage) -> dict:
    """Where focus is, and whether it is inside the dialog surface."""
    return json.loads(page.eval_js(
        "(() => {"
        "  const el = document.activeElement;"
        f"  const surface = document.querySelector('{_SURFACE}');"
        "  return JSON.stringify({"
        "    tag: el ? el.tagName : null,"
        "    testid: el ? (el.getAttribute('data-testid') || null) : null,"
        "    text: el ? (el.textContent || '').trim().slice(0, 40) : null,"
        "    inside: !!(el && surface && surface.contains(el))"
        "  });"
        "})()"
    ))


def _dialog_nodes(snapshot: dict) -> int:
    return snapshot["roles"].get("dialog", 0)


def _tab(page: WimiPage, *, shift: bool = False) -> None:
    """A real Tab, through the input pipeline, not ``el.focus()``.

    ``el.focus()`` would move ``document.activeElement`` without going near
    the keydown handler ``modal_dialog.js`` installs, so it would test
    nothing about the trap. (It would also not set any flag
    ``:focus-visible`` can read -- a separate trap recorded in CLAUDE.md, and
    the reason this file asserts on *where focus is* rather than on a ring.)
    """
    modifiers = 8 if shift else 0
    for kind in ("keyDown", "keyUp"):
        page.tab.Input.dispatchKeyEvent(
            type=kind, key="Tab", code="Tab", windowsVirtualKeyCode=9,
            nativeVirtualKeyCode=9, modifiers=modifiers,
        )
    page.wait_for_timeout(120)


@pytest.mark.slow
@pytest.mark.regression
def test_a_modal_is_a_named_dialog_in_the_accessibility_tree(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="W319 Dialog Semantics", exam_description="Issue #319")
    exam_id = db.get_exam_context_by_name(exam.exam_name).id
    node = db.create_subject_node(
        exam_context=exam.exam_name, name="W319 Cardiology",
        level_type="System")

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    enable_accessibility(wimi_page)
    _wait_for(
        wimi_page,
        '!!document.querySelector(\'[data-testid="%s"]\')'
        % _DELETE_BTN.format(node_id=node.id),
        what="the tree to render the subject's delete button",
    )

    # ---- Assert the control FIRST ------------------------------------
    # With no modal open there must be no dialog in the tree, or "a dialog
    # appeared" below would pass against a page that always had one.
    before = ax_snapshot(wimi_page)
    assert _dialog_nodes(before) == 0, (
        f"a dialog node is exposed before any modal opened, so this "
        f"scenario's main assertion would be vacuous. {ax_summary(before)}")
    assert before["exposed"] > 10, (
        f"the page exposes almost nothing before the modal opens, so the "
        f"background comparison below has no baseline. {ax_summary(before)}")
    # The probe for "is the background still reachable" has to be a string
    # that exists ONLY in the background. The exam name is in the document
    # title (the RootWebArea's accessible name, exposed whatever a dialog
    # does) and the subject's name is quoted inside the delete preview, so
    # both read as "still exposed" against a correct boundary. A toolbar
    # button is neither.
    assert ax_mentions(before, "Add Root Subject"), (
        f"the toolbar behind the modal is not in the accessibility tree "
        f"before the modal opens, so 'the background went away' cannot be "
        f"measured against it. {ax_summary(before)}")

    # ---- Act: open the modal the way a student does ------------------
    wimi_page.eval_js(
        '(() => document.querySelector(\'[data-testid="%s"]\').click())()'
        % _DELETE_BTN.format(node_id=node.id)
    )
    _wait_for(
        wimi_page,
        "(() => { const b = document.getElementById('delete-node-modal');"
        " return !!b && b.classList.contains('active'); })()",
        what="the delete modal to open",
    )
    wimi_page.wait_for_timeout(400)  # past the backdrop's opacity transition

    # ---- Assert: it is a dialog, and it has a name -------------------
    after = ax_snapshot(wimi_page)
    assert _dialog_nodes(after) >= 1, (
        f"the modal is open but no node in the accessibility tree has role "
        f"'dialog', so nothing tells a reader a dialog opened -- which is "
        f"#319 exactly. {ax_summary(after)}")
    assert ax_mentions(after, "Delete Subject?"), (
        f"the open dialog has no accessible name a reader could hear; "
        f"aria-labelledby should resolve to the h2 'Delete Subject?'. "
        f"{ax_summary(after)}")

    # ---- Assert: the background really is out of the tree ------------
    #
    # `aria-modal="true"` is supposed to do this on its own. IT DOES NOT, on
    # QtWebEngine 6.9.2 / Chromium 130, and that was measured four ways
    # before `modal_dialog.js` was given the job (the numbers are in its
    # header). The obvious hypothesis -- that Blink only computes the active
    # aria-modal dialog on DOM insertion -- is wrong: a freshly inserted
    # aria-modal dialog left the page exposed too. So the helper hides the
    # background itself, and this is the assertion that keeps it honest.
    #
    assert after["exposed"] < before["exposed"], (
        f"opening the dialog did not reduce what the accessibility tree "
        f"exposes ({before['exposed']} -> {after['exposed']}), so the page "
        f"behind the modal is still fully reachable: arrowing past the end "
        f"of the dialog walks into the page it is covering, with no boundary "
        f"(#319). Measured at 119 -> 25 when this was written.\n"
        f"before: {ax_summary(before)}\nafter: {ax_summary(after)}")
    assert not ax_mentions(after, "Add Root Subject"), (
        f"the toolbar behind the modal is still an exposed accessible name "
        f"while the dialog is open, so the boundary was not drawn. "
        f"{ax_summary(after)}")
    hidden_count = wimi_page.eval_js(
        "(() => window.ModalDialog.hiddenCount())()")
    assert hidden_count > 0, (
        "the accessibility tree shrank but modal_dialog.js is holding zero "
        "aria-hidden attributes, so something else caused it -- the engine "
        "has started honouring aria-modal, or the page simply rendered less. "
        "Either way this assertion is no longer measuring what it says.")


@pytest.mark.slow
@pytest.mark.regression
def test_focus_enters_the_dialog_is_trapped_and_comes_back(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The half ``aria-modal`` promises and only script can keep.

    ``aria-modal="true"`` takes the background out of the accessibility tree.
    If focus could then leave the dialog, a keyboard user would land on
    something their reader cannot see -- so shipping the attribute without
    containment would be new damage rather than a partial fix. This is why
    focus was kept in #319's scope rather than deferred.
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="W319 Dialog Focus", exam_description="Issue #319")
    exam_id = db.get_exam_context_by_name(exam.exam_name).id
    node = db.create_subject_node(
        exam_context=exam.exam_name, name="W319 Nephrology",
        level_type="System")
    opener = _DELETE_BTN.format(node_id=node.id)

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    _wait_for(
        wimi_page, '!!document.querySelector(\'[data-testid="%s"]\')' % opener,
        what="the tree to render the subject's delete button")
    assert wimi_page.eval_js("typeof window.ModalDialog") == "object", (
        "modal_dialog.js is not loaded on the tree editor, so none of the "
        "focus behaviour below exists. Check the <script> tag.")

    # ---- Act: open it with a real click, so the button holds focus ---
    # A hit-tested click rather than `el.click()`, because the invoker this
    # test asserts focus returns to is whatever the click leaves focused --
    # and `el.click()` dispatches no pointer events, so it focuses nothing.
    wimi_page.locator(testid=opener).click()
    _wait_for(
        wimi_page,
        "(() => { const b = document.getElementById('delete-node-modal');"
        " return !!b && b.classList.contains('active'); })()",
        what="the delete modal to open")
    wimi_page.wait_for_timeout(400)

    # ---- Assert: focus went in ---------------------------------------
    landed = _focus_state(wimi_page)
    assert landed["inside"], (
        f"focus is still outside the dialog after it opened ({landed}). With "
        f"aria-modal=\"true\" on the surface, everything focus can reach out "
        f"here is absent from the accessibility tree, so a keyboard user is "
        f"somewhere their reader cannot describe (#319).")

    # ---- Assert: Tab stays inside ------------------------------------
    # Walk forward more times than there are stops. Without a trap this
    # leaves the dialog and never comes back; with one it cycles.
    stops = wimi_page.eval_js(
        "(() => window.ModalDialog.focusables("
        f"document.querySelector('{_SURFACE}')).length)()")
    assert stops >= 2, (
        f"the dialog reports {stops} focus stops, so a wrap cannot be "
        f"observed at all -- this modal has a Cancel and a Delete button and "
        f"should report at least two")

    for step in range(stops + 2):
        _tab(wimi_page)
        state = _focus_state(wimi_page)
        assert state["inside"], (
            f"Tab #{step + 1} of {stops + 2} moved focus out of the open "
            f"dialog to {state}. The trap in modal_dialog.js resolves the "
            f"topmost open [data-modal-surface] on every keypress; if this "
            f"fails, focus is escaping into content aria-modal has removed "
            f"from the accessibility tree (#319).")

    # ---- Act: close it, and assert focus comes home ------------------
    wimi_page.eval_js(f"(() => document.querySelector('{_CANCEL}').click())()")
    _wait_for(
        wimi_page,
        "(() => { const b = document.getElementById('delete-node-modal');"
        " return !!b && !b.classList.contains('active'); })()",
        what="the delete modal to close")
    wimi_page.wait_for_timeout(400)

    back = _focus_state(wimi_page)
    assert back["testid"] == opener, (
        f"after the dialog closed, focus is at {back} rather than back on "
        f"the control that opened it ({opener!r}). Focus dropped to <body> is "
        f"the usual symptom: a keyboard user is returned to the top of the "
        f"document and has to walk the whole tree again (#319).")
