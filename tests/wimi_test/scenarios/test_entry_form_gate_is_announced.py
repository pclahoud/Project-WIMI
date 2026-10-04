"""Issue #127 — the `inert` gate must say something while it holds.

    "`inert` [...] removes the subtree from the accessibility tree, exactly
    as `aria-hidden` would. For the 0.1-0.6 s the gate is up a screen
    reader sees a document with nothing in it. Nothing is announced to say
    why, and nothing is announced when the form arrives."

#114's gate is correct and stays. What was missing is a voice: the only
affordance it added was a CSS dim and `cursor: progress`, both invisible to
assistive technology.

Measured, not inferred
----------------------
These tests assert through CDP's ``Accessibility`` domain, which returns the
tree Chromium hands assistive technology. On this page, with the bridge calls
held open by ``install_slow_bridge``, before the fix:

    while the gate is up     72 nodes, 71 ignored -- ONE exposed node, the
                             document root, and nothing else
    after release           461 nodes, 290 exposed: 52 buttons, 3 textboxes,
                            4 comboboxes, the headings

An attribute-level test would be close to worthless here. The way to get this
fix wrong is to put the status region *inside* the gated container, where it
has the right role, the right `aria-live`, the right text and a non-zero
bounding box, is removed from the accessibility tree with everything else, and
passes every DOM-level check ever written about it. Hence
``tests/test_page_gate_markup.py`` for the markup and the AX tree here.

What these tests do NOT verify
------------------------------
**No screen reader was run.** This box has none, and CDP cannot observe an
announcement. What is measured is that the gate's text is in the accessibility
tree while the form is not, and that the text changes at handover. That a
``role="status"`` text change is *spoken* rests on the ARIA specification and
on the deliberate choice that content present at registration is not announced
— reasoned, not verified. Do not report otherwise.
"""
from __future__ import annotations

import pytest

from _helpers.page_gate import (
    GATE_IS_TRANSPARENT,
    GATE_IS_VISIBLE,
    assert_gate_can_be_heard,
    ax_mentions,
    ax_snapshot,
    ax_summary,
    enable_accessibility,
    gate_state,
)
from _helpers.w114_form_ready import (
    assert_slow_bridge_took,
    install_slow_bridge,
    is_inert,
    poll,
    seed_empty_session,
    wait_for_form_ready,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FORM_RENDERED = "(() => !!document.getElementById('user-answer'))()"

# Two strings the shipped page owns. Quoted rather than read from the page so a
# fix that empties the message cannot make the test agree with it.
HOLDING = "Preparing the entry form"
READY = "Entry form ready"

# A control: something only the form itself has. If this is in the tree the
# gate is not up, whatever the attribute says.
FORM_ONLY = "Save as Draft"


@pytest.mark.slow
@pytest.mark.regression
def test_the_gate_is_in_the_accessibility_tree_while_the_form_is_not(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The substance of #127, in the only place it is observable."""
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_empty_session(wimi_session.user.db, name="W127")
    install_slow_bridge(wimi_page)
    wimi_page.goto("entry-form", query={"session_id": session_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, FORM_RENDERED), "the entry form markup never rendered"
    assert_slow_bridge_took(wimi_page)
    enable_accessibility(wimi_page)

    # ---- Act: inside the window -------------------------------------------
    during_inert = is_inert(wimi_page)
    during_gate = gate_state(wimi_page)
    during_ax = ax_snapshot(wimi_page)

    # ---- Assert: the gate is up, and audible ------------------------------
    assert during_inert is True, (
        "the form was not inert when the probe ran, so nothing below is "
        "measuring the window #127 is about. Raise BRIDGE_DELAY_MS rather "
        "than weakening the assertion")
    assert_gate_can_be_heard(during_gate, where="while the gate was up")
    assert HOLDING.lower() in during_gate["text"].lower(), (
        f"the gate carries no holding message while it holds "
        f"(text={during_gate['text']!r}); a screen reader lands on a document "
        f"that is empty and silent (#127)")

    assert ax_mentions(during_ax, HOLDING), (
        f"'{HOLDING}' is NOT in the accessibility tree while the gate is up, "
        f"so a screen reader is still handed an empty document. This is the "
        f"failure mode of putting the status element inside the `inert` "
        f"container: present in the DOM, absent from the tree. "
        f"Tree: {ax_summary(during_ax)}")
    assert not ax_mentions(during_ax, FORM_ONLY), (
        f"the form itself is already exposed to assistive technology during "
        f"the gate ({FORM_ONLY!r} is in the tree), so #114's gate is not "
        f"doing what this test assumes and the measurement is of some other "
        f"state. Tree: {ax_summary(during_ax)}")

    # ---- Act: after handover ----------------------------------------------
    wait_for_form_ready(wimi_page)
    after_gate = gate_state(wimi_page)
    after_ax = ax_snapshot(wimi_page)

    # ---- Assert: the handover is announced, and the form arrives ----------
    assert is_inert(wimi_page) is False, "the form stayed inert after init"
    assert after_gate["state"] == "ready", (
        f"PageGate.release() never ran: the gate still reads "
        f"state={after_gate['state']!r} after the form was handed over. "
        f"markEntryFormReady() is the one place that calls it (#127)")
    assert after_gate["announced"] == "true", (
        f"the handover was not announced (announced="
        f"{after_gate['announced']!r}). With the bridge held open the gate "
        f"was up for seconds, far past PageGate's "
        f"RELEASE_ANNOUNCE_AFTER_MS, so the quiet-fast-load branch should "
        f"not have been taken here")
    assert READY.lower() in after_gate["text"].lower(), (
        f"the gate's text did not change to the ready message "
        f"(text={after_gate['text']!r}). The text change IS the "
        f"announcement; without it a reader gets no event when the form "
        f"arrives (#127)")
    assert ax_mentions(after_ax, READY), (
        f"the ready message is not in the accessibility tree, so it cannot "
        f"be announced. Tree: {ax_summary(after_ax)}")
    assert ax_mentions(after_ax, FORM_ONLY), (
        f"the form is still not exposed to assistive technology after the "
        f"gate lifted -- `inert` removed but something else is hiding it. "
        f"Tree: {ax_summary(after_ax)}")
    assert after_ax["exposed"] > during_ax["exposed"] * 10, (
        f"the accessibility tree barely grew when the gate lifted "
        f"({during_ax['exposed']} -> {after_ax['exposed']} exposed nodes). "
        f"Measured on the fix: 1 -> 290")
    assert poll(wimi_page, GATE_IS_TRANSPARENT, timeout_ms=3000), (
        f"the gate is still painted after the form was handed over "
        f"(opacity={gate_state(wimi_page)['opacity']!r}); a 'Preparing…' pill "
        f"left on a ready page is worse than none")


@pytest.mark.slow
@pytest.mark.regression
def test_the_gate_is_also_visible_to_someone_who_can_see(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The sighted half, which the same element carries.

    #114's only affordance was a CSS dim on the gated page, which says that
    something is happening but not what or why. The gate's text doubles as the
    sighted "Preparing…" line, revealed with the same 250 ms delay the dim
    uses so a warm load never flashes it.

    This is also the only test that would notice `.page-gate` failing to
    paint at all -- an undefined token behind a `var(--x, fallback)`, a
    keyframe that never runs, a stylesheet that is not linked. None of those
    produce an error anywhere.
    """
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_empty_session(wimi_session.user.db, name="W127 seen")
    install_slow_bridge(wimi_page)
    wimi_page.goto("entry-form", query={"session_id": session_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, FORM_RENDERED), "the entry form markup never rendered"
    assert_slow_bridge_took(wimi_page)

    # ---- Assert: it appears while the gate drags --------------------------
    assert poll(wimi_page, GATE_IS_VISIBLE, timeout_ms=5000), (
        f"the gate never became visible during a load held open for seconds "
        f"(state={gate_state(wimi_page)!r}). A student watching a page that "
        f"refuses every keystroke is told nothing about why")
    assert is_inert(wimi_page) is True, (
        "the form was handed over before the pill was observed, so this is "
        "measuring the wrong state; raise BRIDGE_DELAY_MS")

    state = gate_state(wimi_page)
    assert state["pointerEvents"] == "none", (
        f"the gate is painted over the page with pointerEvents="
        f"{state['pointerEvents']!r}, so this fixed element can swallow a "
        f"click aimed at the page underneath once the form is live")

    # ---- Assert: and goes away when the form arrives ----------------------
    wait_for_form_ready(wimi_page)
    assert poll(wimi_page, GATE_IS_TRANSPARENT, timeout_ms=3000), (
        f"the pill stayed on screen after the form was handed over "
        f"(opacity={gate_state(wimi_page)['opacity']!r})")


@pytest.mark.slow
@pytest.mark.regression
def test_a_fast_load_is_announced_to_nobody(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The quiet path, which exists so the fix is not its own annoyance.

    The entry form is ready in ~110 ms warm and a student opens it many times
    in a session. Announcing "Entry form ready." on every one of those would
    be worse than the silence being fixed, so below
    ``RELEASE_ANNOUNCE_AFTER_MS`` the gate's text is *cleared* rather than
    replaced -- clearing a live region announces nothing, because
    ``aria-relevant`` does not include removals by default.

    This is the half of the decision an implementation would "simplify" away,
    so it gets its own test, and it is asserted through
    ``PageGate.shouldAnnounce`` rather than by waiting for a fast load. That
    is not a convenience: the branch is decided by how long the load took, so
    a test that waited for a quick one would skip itself on every machine
    slower than the threshold -- including this headless box, where the first
    draft of this test did exactly that. The predicate is the shipped code,
    called on the shipped page.
    """
    # ---- Arrange / Act ----------------------------------------------------
    session_id = seed_empty_session(wimi_session.user.db, name="W127 fast")
    wimi_page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(wimi_page)

    # ---- Assert: the decision, both sides of it ---------------------------
    threshold = wimi_page.eval_js("window.PageGate.RELEASE_ANNOUNCE_AFTER_MS")
    assert isinstance(threshold, (int, float)), (
        f"window.PageGate is not loaded on this page "
        f"(RELEASE_ANNOUNCE_AFTER_MS={threshold!r}); the <script> tag for "
        f"page_gate.js is missing from question_entry.html")
    assert threshold > 0, (
        f"RELEASE_ANNOUNCE_AFTER_MS is {threshold!r}, so every load announces "
        f"and the quiet branch is unreachable -- the entry form would speak "
        f"on every single open")

    quiet = wimi_page.eval_js(
        f"window.PageGate.shouldAnnounce({threshold} - 1)")
    loud = wimi_page.eval_js(f"window.PageGate.shouldAnnounce({threshold})")
    warm = wimi_page.eval_js("window.PageGate.shouldAnnounce(110)")
    assert quiet is False, (
        f"a gate held for less than {threshold} ms is announced "
        f"(shouldAnnounce -> {quiet!r}). Nobody heard the holding message "
        f"either, so this is a bare interruption on the most-used page in "
        f"the app")
    assert warm is False, (
        f"a warm ~110 ms load is announced (shouldAnnounce(110) -> {warm!r}) "
        f"-- that is the common case, many times per study session")
    assert loud is True, (
        f"a gate held at or past {threshold} ms is NOT announced "
        f"(shouldAnnounce -> {loud!r}), which is #127 unfixed for exactly "
        f"the slow loads it is about")

    # ---- Assert: the live page agrees with the decision -------------------
    state = gate_state(wimi_page)
    assert state["present"], "the gate element vanished from the page"
    assert state["state"] == "ready", (
        f"PageGate.release() did not run on a normal load "
        f"(state={state['state']!r})")
    assert state["announced"] in {"true", "false"}, (
        f"release() left no record of which branch it took "
        f"(announced={state['announced']!r})")

    if state["announced"] == "false":
        assert state["text"] == "", (
            f"the gate went quiet but left text behind ({state['text']!r}). "
            f"The holding message must be cleared, or a reader coming to the "
            f"page afterwards is told the form is still being prepared")
    else:
        # This box is slow enough that a real load can cross the threshold.
        # That is a legitimate outcome; announcing an empty string would not
        # be.
        assert READY.lower() in state["text"].lower(), (
            f"the gate announced and said {state['text']!r} rather than the "
            f"ready message")


@pytest.mark.slow
@pytest.mark.regression
def test_a_failed_init_still_announces_and_still_releases(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The unhappy path, where "permanently gated and silent" would hide.

    #114's rule is that every exit releases the form, including the early
    returns, and that a permanently inert form is far worse than the bug the
    gate fixes. #127 adds a second thing that must survive those exits: the
    gate must not be left claiming the form is still being prepared.

    A session id that does not resolve takes the "Session Not Found" return
    from inside the ``try``, reached through the ``finally`` -- the exit an
    ``if`` at the end of the happy path would miss.
    """
    # ---- Arrange / Act ----------------------------------------------------
    wimi_page.goto("entry-form", query={"session_id": 999999},
                   wait_for_bridge=False)
    assert poll(wimi_page, FORM_RENDERED), "the entry form markup never rendered"

    # The page redirects to the dashboard ~1.5 s later, so poll rather than
    # settle: the release happens at once, well before the redirect.
    released = poll(
        wimi_page,
        "(() => { const p = document.querySelector('.entry-page');"
        " return !!p && !p.hasAttribute('inert'); })()",
        timeout_ms=10000)

    # ---- Assert -----------------------------------------------------------
    assert released, (
        "the form stayed inert after init failed to find its session. The "
        "`finally` in initializeEntryPage() is not releasing it, which leaves "
        "a permanently dead page (#114)")

    state = gate_state(wimi_page)
    assert state["state"] == "ready", (
        f"the form was released but the gate was left holding "
        f"(state={state['state']!r}), so assistive technology is still being "
        f"told the form is being prepared while it is actually being "
        f"abandoned. PageGate.release() must be reached from the same exits "
        f"markEntryFormReady() is (#127)")
    assert HOLDING.lower() not in state["text"].lower(), (
        f"the gate still reads {state['text']!r} after the form was released")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# * `ax_mentions(during_ax, HOLDING)` fails against master, where the only
#   thing in the accessibility tree during the gate is the document root. It
#   also fails against the most likely bad fix -- the status element placed
#   inside `.entry-page` -- which is precisely what no DOM-level assertion
#   can distinguish from a correct one.
# * `not ax_mentions(during_ax, FORM_ONLY)` is the control. Without it the
#   first assertion would pass against a page that had simply stopped gating
#   itself, which would be #114 reopened and #127 "fixed".
# * `after_gate["announced"] == "true"` fails against a release that removes
#   `inert` and says nothing, which is the state the issue describes as
#   getting "no event when that stops being true".
# * `test_a_fast_load_...` fails against a fix that announces on every load.
#   That is not a hypothetical tidy-up: it is the simpler implementation, and
#   it would make the most-used page in the app speak on every open.
# * `test_a_failed_init_...` fails against a release path that is reached only
#   from the happy end of init -- the same shape of defect #114's own
#   `finally` exists to prevent, one layer out.
