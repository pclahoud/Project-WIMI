"""Issue #122 — the entry browser must refuse a query it cannot run.

#122 is the #114 defect on this page, and what makes it worse than a dead
control is spelled out in the issue:

    A query typed in that window fires `input` events into nothing, so
    `filters.searchQuery` stays empty. The result is worse than a dead
    control: the box *displays* the student's query while the grid below shows
    **every** entry, unfiltered, and nothing further fires until they type
    another character. A filtered-looking view that is not filtered is a wrong
    answer, not a missing one.

So the fix is the first of the issue's two options — "the search box should not
accept a query it cannot run" — and the thing to measure is that a real
keystroke lands nowhere while the page is gated, **and** that it lands
properly once the page is ready. Only the pair is meaningful: a page whose
search box never works at all satisfies the first half, and is a far worse bug
than #122 (#114's own rule).

Instrument
----------
``inert`` blocks hit-tested pointer events and focus. It does **not** block
``el.value = 'x'``, ``el.click()`` or ``innerHTML =``, so a probe built from
those passes against a completely ungated page — #114's trap, restated in
#285. Everything here goes through ``Input.dispatchMouseEvent`` and
``Input.insertText``.

What this does NOT verify
-------------------------
**No screen reader was run.** CDP cannot observe an announcement. What is
measured is that the gate's text is in the accessibility tree while the page
is not, and that it changes at handover; that a ``role="status"`` change is
*spoken* rests on the ARIA specification.
"""
from __future__ import annotations

from datetime import date

import pytest

from _helpers.page_gate import (
    assert_gate_can_be_heard,
    assert_inside_the_window,
    ax_mentions,
    ax_snapshot,
    ax_summary,
    enable_accessibility,
    gate_state,
    is_inert,
)
from _helpers.w114_form_ready import (
    assert_slow_bridge_took,
    centre_of,
    install_slow_bridge,
    poll,
    real_click,
    real_type,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

GATED = ".app-container"
PAGE_RENDERED = "(() => !!document.getElementById('searchInput'))()"

# Waiting on the markup alone is NOT enough on this page, and the reference
# scenario's arrange sequence does not generalise here. `_loader.js` builds
# `window.api` through a chain of synchronous `document.write` calls, and
# entry_browser.html loads it at the *bottom of <body>* rather than in <head>
# like question_entry.html -- so #searchInput exists some milliseconds before
# `window.api` is assigned, and the slow-bridge hook (which intercepts that
# assignment) has not fired yet. Measured: `assert_slow_bridge_took` failed
# intermittently on exactly that window, which reads like a broken hook rather
# than a race. Poll for the hook instead.
BRIDGE_WRAPPED = "(() => (window.__w114slow || 0) > 0)()"
PAGE_READY = (
    "(() => { try { return entryBrowser.isPageReady === true; }"
    " catch (e) { return false; } })()"
)
CARD_COUNT = "document.querySelectorAll('#entryGrid [data-entry-id]').length"
SEARCH_VALUE = (
    "(() => { const el = document.getElementById('searchInput');"
    " return el ? el.value : null; })()"
)
APPLIED_QUERY = (
    "(() => { try { return entryBrowser.filters.searchQuery; }"
    " catch (e) { return '<unreachable>'; } })()"
)

# Two strings the shipped page owns, quoted rather than read off it so a fix
# that empties the message cannot make the test agree with itself.
HOLDING = "Preparing the entry browser"
READY = "Entry browser ready"

# Something only the browser itself has. If this is in the accessibility tree
# the gate is not up, whatever the attribute says.
PAGE_ONLY = "Export IDs"

# The query the student types too early, and the one they type once the page
# is theirs. Distinct so neither can be mistaken for the other.
TOO_EARLY = "W122-REFUSED"
ALPHA = "W122UNIQUEALPHA"
BETA = "W122OTHERBETA"


def _seed(db) -> int:
    """One exam, one session, two entries with distinguishable answers.

    Two rather than one, because the positive control at the end has to show a
    search *narrowing* the list. One entry would pass for a filter that was
    never applied.
    """
    exam = db.create_exam_context(exam_name="W122 Browser Gate", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=2,
        session_name="W122 session", date_encountered=date.today(),
    )
    for answer in (ALPHA, BETA):
        db.create_question_entry(
            review_session_id=session.id, user_answer=answer,
            correct_answer="B", reflection=f"<p>{answer} reflection</p>",
            explanation=f"<p>{answer} explanation</p>",
        )
    db.conn.commit()
    return exam.id


@pytest.mark.slow
@pytest.mark.regression
def test_a_query_typed_during_load_is_refused_rather_than_ignored(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#122's substance, plus the control that stops the cure being worse."""
    # ---- Arrange ----------------------------------------------------------
    exam_id = _seed(wimi_session.user.db)
    # 1200 ms rather than the entry form's 600: this page's init is only four
    # sequential bridge steps (getUserPreferences, getExamContext, a
    # Promise.all of four, loadEntries), so 600 would leave a ~2.4 s window
    # for a probe that needs to click, type and read inside it.
    install_slow_bridge(wimi_page, delay_ms=1200)
    wimi_page.goto("entry-browser", query={"exam": exam_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the entry browser markup never rendered"
    assert poll(wimi_page, BRIDGE_WRAPPED), (
        "window.api was never assigned, so the slow-bridge hook never ran -- "
        "see BRIDGE_WRAPPED for why waiting on the markup is not enough here")
    assert_slow_bridge_took(wimi_page)

    # ---- Act: a real click on the search box, then real typing ------------
    assert_inside_the_window(wimi_page, GATED, "before aiming the click")
    real_click(wimi_page, centre_of(wimi_page, "#searchInput"))
    real_type(wimi_page, TOO_EARLY)
    assert_inside_the_window(wimi_page, GATED, "after typing the early query")

    typed = wimi_page.eval_js(SEARCH_VALUE)
    focused = wimi_page.eval_js(
        "(() => (document.activeElement && document.activeElement.id) || "
        "(document.activeElement && document.activeElement.tagName) || null)()")

    # ---- Assert: the query never reached the box -------------------------
    assert typed == "", (
        f"#searchInput accepted {typed!r} while .app-container was still "
        f"inert (activeElement={focused!r}). That is #122 exactly: the box "
        f"shows a query, the handler that would apply it is not bound yet, "
        f"and the grid below goes on showing every entry. The box must refuse "
        f"what it cannot run")
    assert focused != "searchInput", (
        f"the inert search box took focus (activeElement={focused!r}); "
        f"`inert` is meant to make it unfocusable, so either the attribute is "
        f"absent from .app-container or something re-enabled it")

    # ---- Act: hand over, then type the same way --------------------------
    assert poll(wimi_page, PAGE_READY, timeout_ms=60000), (
        "entryBrowser.isPageReady never went true; markPageReady() did not "
        "run from init()'s `finally`")

    # Read AT ONCE, not polled. This is the assertion that pins *where* in
    # init() the release sits: `loadEntries` calls `renderEntries` synchronously
    # after its await, so in the shipped order -- release in the `finally`,
    # after loadInitialData() -- the cards and the hidden loading state are
    # already true the instant the gate lifts. Moving the release up to just
    # after setupEventListeners() (the plausible wrong fix, since that is where
    # the search handler is bound) leaves this false for a further bridge
    # round trip. Without this line that mutation passes the whole file:
    # measured.
    at_release = wimi_page.eval_js(
        "JSON.stringify({cards: %s, loading: getComputedStyle("
        "document.getElementById('loadingState')).display})" % CARD_COUNT)
    assert '"cards":2' in at_release and '"loading":"none"' in at_release, (
        f"the gate lifted before the page had anything to show "
        f"({at_release}). The release belongs in init()'s `finally`, after "
        f"loadInitialData(): a search box that is live while the first page "
        f"of entries is still in flight lets a query race "
        f"loadInitialData()'s own loadEntries(), and whichever resolves last "
        f"wins -- #122's wrong answer reached after the release instead of "
        f"before it. The filter dropdowns are also empty until then")

    real_click(wimi_page, centre_of(wimi_page, "#searchInput"))
    real_type(wimi_page, ALPHA)

    # ---- Assert: now it is both kept AND applied -------------------------
    # The positive control. Without it every assertion above is satisfied by
    # a page that never releases, which is far worse than #122.
    assert wimi_page.eval_js(SEARCH_VALUE) == ALPHA, (
        f"after the gate lifted the search box still refuses hit-tested "
        f"input (value={wimi_page.eval_js(SEARCH_VALUE)!r}). The gate is "
        f"permanent, which is a worse bug than the one being fixed (#114)")
    assert poll(wimi_page, f"{CARD_COUNT} === 1", timeout_ms=30000), (
        f"the query was kept but never applied: {ALPHA!r} is in the box and "
        f"{wimi_page.eval_js(CARD_COUNT)!r} cards are drawn, so the grid is "
        f"still unfiltered. This is #122's wrong answer reached after the "
        f"release instead of before it -- applied query="
        f"{wimi_page.eval_js(APPLIED_QUERY)!r}")
    assert wimi_page.eval_js(APPLIED_QUERY) == ALPHA, (
        f"the grid narrowed but entryBrowser.filters.searchQuery is "
        f"{wimi_page.eval_js(APPLIED_QUERY)!r}, so the page's state and what "
        f"it is showing disagree")


@pytest.mark.slow
@pytest.mark.regression
def test_the_gate_is_in_the_accessibility_tree_while_the_browser_is_not(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#127 on this page: `inert` is silence as well as refusal.

    ``#loadingState`` cannot do this job and was measured not to be able to —
    it sits inside ``<main>``, i.e. inside ``.app-container``, so ``inert``
    removes it from the accessibility tree along with everything else. It has
    the right text, a real box and ``display: flex``, and is never read.
    """
    # ---- Arrange ----------------------------------------------------------
    exam_id = _seed(wimi_session.user.db)
    install_slow_bridge(wimi_page, delay_ms=1200)
    wimi_page.goto("entry-browser", query={"exam": exam_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the entry browser markup never rendered"
    assert poll(wimi_page, BRIDGE_WRAPPED), (
        "window.api was never assigned, so the slow-bridge hook never ran -- "
        "see BRIDGE_WRAPPED for why waiting on the markup is not enough here")
    assert_slow_bridge_took(wimi_page)
    enable_accessibility(wimi_page)

    # ---- Act: inside the window -------------------------------------------
    assert_inside_the_window(wimi_page, GATED, "before reading the AX tree")
    during_gate = gate_state(wimi_page)
    during_ax = ax_snapshot(wimi_page)

    # ---- Assert: audible, and the page itself is not -----------------------
    assert_gate_can_be_heard(during_gate, where="while the gate was up")
    assert HOLDING.lower() in during_gate["text"].lower(), (
        f"the gate carries no holding message (text={during_gate['text']!r}); "
        f"a screen reader lands on a document that is empty and silent (#127)")
    assert ax_mentions(during_ax, HOLDING), (
        f"{HOLDING!r} is NOT in the accessibility tree while the gate is up, "
        f"so a screen reader is still handed an empty document. This is the "
        f"failure mode of nesting the status element inside .app-container -- "
        f"or of reusing #loadingState, which is inside it. Present in the DOM, "
        f"absent from the tree, every DOM check passing. "
        f"Tree: {ax_summary(during_ax)}")
    assert not ax_mentions(during_ax, PAGE_ONLY), (
        f"the browser itself is already exposed to assistive technology during "
        f"the gate ({PAGE_ONLY!r} is in the tree), so the page is not gated "
        f"and this measurement is of some other state. "
        f"Tree: {ax_summary(during_ax)}")

    # ---- Act: after handover ----------------------------------------------
    assert poll(wimi_page, PAGE_READY, timeout_ms=60000), (
        "entryBrowser.isPageReady never went true")
    after_gate = gate_state(wimi_page)
    after_ax = ax_snapshot(wimi_page)

    # ---- Assert: the handover is announced, and the page arrives ----------
    assert is_inert(wimi_page, GATED) is False, "the page stayed inert after init"
    assert after_gate["state"] == "ready", (
        f"PageGate.release() never ran: the gate still reads "
        f"state={after_gate['state']!r} after the page was handed over (#127)")
    assert after_gate["announced"] == "true", (
        f"the handover was not announced (announced={after_gate['announced']!r}). "
        f"With the bridge held open the gate was up for seconds, far past "
        f"PageGate.RELEASE_ANNOUNCE_AFTER_MS")
    assert READY.lower() in after_gate["text"].lower(), (
        f"the gate's text did not change to the ready message "
        f"(text={after_gate['text']!r}). The text change IS the announcement")
    assert ax_mentions(after_ax, READY), (
        f"the ready message is not in the accessibility tree, so it cannot be "
        f"announced. Tree: {ax_summary(after_ax)}")
    assert ax_mentions(after_ax, PAGE_ONLY), (
        f"the browser is still not exposed to assistive technology after the "
        f"gate lifted -- `inert` removed but something else is hiding it. "
        f"Tree: {ax_summary(after_ax)}")
    assert after_ax["exposed"] > during_ax["exposed"] * 10, (
        f"the accessibility tree barely grew when the gate lifted "
        f"({during_ax['exposed']} -> {after_ax['exposed']} exposed nodes); "
        f"measured on the entry form's fix, 1 -> 290")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# * `typed == ""` fails against master, where #searchInput is live from parse
#   and keeps a query nothing will apply. It is driven with
#   `Input.dispatchMouseEvent` / `Input.insertText` because `el.value = 'x'`
#   works on an inert subtree and would pass against an ungated page (#285).
# * The `CARD_COUNT === 1` control fails against the simplest wrong fix --
#   `disabled` on the input, or never releasing the gate -- both of which
#   satisfy every refusal assertion above while leaving the search unusable.
#   It is also the assertion that reads #122's actual symptom: query present,
#   list unfiltered.
# * `ax_mentions(during_ax, HOLDING)` fails against master, where the only
#   thing in the tree during the gate is the document root, AND against the
#   obvious bad fix of reusing #loadingState as the status region -- which no
#   DOM-level assertion can distinguish from a correct one (#127).
# * `not ax_mentions(during_ax, PAGE_ONLY)` is the control for that one.
#   Without it the assertion above would pass against a page that had simply
#   stopped gating itself.
# * `after_gate["announced"] == "true"` fails against a release that removes
#   `inert` and says nothing, which is #127 unfixed on a page that now has a
#   gate.
