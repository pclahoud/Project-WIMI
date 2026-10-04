"""Issue #121 — the tree editor must not claim an exam is empty while it loads.

#121 is the #114 defect on this page, plus one thing #114 did not have:

    before any JS runs, the page paints the empty state -- "No Subjects Yet"
    plus a large primary CTA "Add Your First Subject" -- on an exam that may
    have a full hierarchy. [...] the page actively asserts something false
    and offers a primary action that does nothing, then replaces both without
    comment when the real tree arrives.

So there are two halves to verify and they need **different instruments**:

* **The refusal** (`inert` on `.tree-page`) is only measurable with real,
  hit-tested input. ``inert`` does not block ``el.click()``, ``el.value =``
  or ``innerHTML =``, so a probe built from those reports a fix that is not
  one — #114's trap, restated in #285.
* **The false assertion** is *not* measurable through the accessibility tree,
  and this is worth being explicit about. While the gate is up the gated
  subtree is out of the tree **whatever those two blocks are doing**, so
  `ax_mentions(..., 'No Subjects Yet')` is false against the unfixed page too.
  It is a sighted-user defect, so it is measured where it lives: the computed
  display of ``#tree-empty`` and ``#tree-loading``.

Both load paths
---------------
``loadHierarchy()`` (plain exam) and ``loadDimensionHierarchy()`` (a
dimensioned exam — the common case, not the edge case) are reached from inside
the same ``try``, so the release lives in its ``finally``. A gate released from
the end of one branch is a **permanently gated page** on the other, which is
far worse than #121, so the release is parametrised over both shapes.

What this does NOT verify
-------------------------
**No screen reader was run.** CDP cannot observe an announcement. What is
measured is that the gate's text is in the accessibility tree while the page
is not, and that it changes at handover; that a ``role="status"`` change is
*spoken* rests on the ARIA specification.
"""
from __future__ import annotations

import json

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

GATED = ".tree-page"
PAGE_RENDERED = "(() => !!document.querySelector('.tree-page'))()"
PAGE_READY = (
    "(() => { try { return typeof TreeState !== 'undefined'"
    " && TreeState.isPageReady === true; } catch (e) { return false; } })()"
)
RELEASED = (
    "(() => { const p = document.querySelector('.tree-page');"
    " return !!p && !p.hasAttribute('inert'); })()"
)

# Two strings the shipped page owns, quoted rather than read off it so a fix
# that empties the message cannot make the test agree with itself.
HOLDING = "Preparing the subject hierarchy"
READY = "Subject hierarchy ready"

# The false assertion, verbatim from the markup. If this is on screen during
# the load, #121 is unfixed.
FALSE_CLAIM = "No Subjects Yet"
DEAD_CTA = "Add Your First Subject"

PANEL_STATE = """
(() => {
  const vis = (id) => {
    const el = document.getElementById(id);
    if (!el) return 'absent';
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return (cs.display === 'none' || cs.visibility === 'hidden'
            || r.width === 0 || r.height === 0) ? 'hidden' : 'shown';
  };
  return JSON.stringify({
    empty: vis('tree-empty'),
    loading: vis('tree-loading'),
    container: vis('tree-container'),
    bodyText: document.body.innerText
  });
})()
"""


def _panel_state(page: WimiPage) -> dict:
    return json.loads(page.eval_js(PANEL_STATE))


def _seed_plain_exam(db, name: str) -> int:
    """An exam with subjects and no dimensions — the loadHierarchy() path."""
    exam = db.create_exam_context(exam_name=name, exam_description="")
    cardio = db.create_subject_node(exam.exam_name, "W121 Cardiovascular", "System")
    db.create_subject_node(
        exam.exam_name, "W121 Hypertension", "Topic", parent_id=cardio.id)
    db.conn.commit()
    return exam.id


def _seed_dimensioned_exam(db, name: str) -> int:
    """An exam with a dimension and subjects — the loadDimensionHierarchy() path.

    The branch #121's fix has to release from and the one a backend test cannot
    reach at all (CLAUDE.md, *Dimension code path symmetry*).
    """
    exam = db.create_exam_context(exam_name=name, exam_description="")
    # create_dimension returns the row id, not an object.
    dim = db.create_dimension(
        exam_id=exam.id, name="W121 System", display_order=1, is_required=True)
    root = db.create_subject_node(
        exam.exam_name, "W121 Renal", "System", dimension_id=dim)
    db.create_subject_node(
        exam.exam_name, "W121 Glomerular", "Topic",
        parent_id=root.id, dimension_id=dim)
    db.conn.commit()
    assert db.exam_uses_dimensions(exam.id), (
        "the seed must produce a dimensioned exam or this parametrisation "
        "silently tests the plain path twice")
    return exam.id


@pytest.mark.slow
@pytest.mark.regression
def test_the_page_does_not_claim_the_exam_is_empty_while_it_loads(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#121's substance: the false assertion, and the dead CTA beside it."""
    # ---- Arrange ----------------------------------------------------------
    exam_id = _seed_plain_exam(wimi_session.user.db, "W121 Empty Claim")
    install_slow_bridge(wimi_page)
    wimi_page.goto("tree-editor", query={"exam_id": exam_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the tree editor markup never rendered"
    assert_slow_bridge_took(wimi_page)
    enable_accessibility(wimi_page)

    # ---- Act: inside the window -------------------------------------------
    assert_inside_the_window(wimi_page, GATED, "before reading the panels")
    during = _panel_state(wimi_page)
    during_ax = ax_snapshot(wimi_page)
    during_gate = gate_state(wimi_page)

    # ---- Assert: nothing false is on screen -------------------------------
    assert during["empty"] == "hidden", (
        f"#tree-empty is {during['empty']!r} while the hierarchy is still "
        f"loading, so the page is claiming {FALSE_CLAIM!r} about an exam that "
        f"has subjects -- and offering {DEAD_CTA!r}, which is bound in "
        f"setupEventListeners() and does nothing yet. That is #121: not a "
        f"dead click but a wrong answer (panels={during!r})")
    assert FALSE_CLAIM not in during["bodyText"], (
        f"the page's rendered text contains {FALSE_CLAIM!r} during the load. "
        f"The computed-display check above is the precise one; this reads what "
        f"a student would, and catches the same claim arriving some other way")
    assert DEAD_CTA not in during["bodyText"]
    assert during["loading"] == "shown", (
        f"#tree-loading is {during['loading']!r} during the load, so the page "
        f"says nothing at all about why it is blank. #121's remedy is that one "
        f"of the two blocks is true at parse, and it is this one "
        f"(panels={during!r})")

    # ---- Assert: and the gate is audible while it holds -------------------
    assert_gate_can_be_heard(during_gate, where="while the gate was up")
    assert HOLDING.lower() in during_gate["text"].lower(), (
        f"the gate carries no holding message (text={during_gate['text']!r}); "
        f"a screen reader lands on a document that is empty and silent (#127)")
    assert ax_mentions(during_ax, HOLDING), (
        f"{HOLDING!r} is NOT in the accessibility tree while the gate is up, "
        f"so a screen reader is still handed an empty document. This is the "
        f"failure mode of nesting the status element inside .tree-page -- "
        f"present in the DOM, absent from the tree, every DOM check passing. "
        f"Tree: {ax_summary(during_ax)}")

    # ---- Act: after handover ----------------------------------------------
    assert poll(wimi_page, PAGE_READY, timeout_ms=60000), (
        "TreeState.isPageReady never went true; markTreeEditorReady() did not "
        "run from the init chain's `finally`")
    after = _panel_state(wimi_page)
    after_gate = gate_state(wimi_page)

    # ---- Assert: the real tree arrives, and the handover is announced ------
    assert is_inert(wimi_page, GATED) is False, "the page stayed inert after init"
    assert after["empty"] == "hidden", (
        f"#tree-empty is showing after the load finished, on an exam seeded "
        f"with two subjects (panels={after!r})")
    assert "W121 Cardiovascular" in after["bodyText"], (
        f"the seeded tree never drew after the gate lifted, so the fix may "
        f"have left the container hidden rather than merely ungated "
        f"(panels={after!r})")
    assert after_gate["state"] == "ready", (
        f"PageGate.release() never ran: the gate still reads "
        f"state={after_gate['state']!r} (#127)")
    assert after_gate["announced"] == "true", (
        f"the handover was not announced (announced={after_gate['announced']!r}). "
        f"With the bridge held open the gate was up for seconds, far past "
        f"PageGate.RELEASE_ANNOUNCE_AFTER_MS")
    assert READY.lower() in after_gate["text"].lower(), (
        f"the gate's text did not change to the ready message "
        f"(text={after_gate['text']!r}). The text change IS the announcement")


@pytest.mark.slow
@pytest.mark.regression
def test_a_real_click_and_a_real_keystroke_are_refused_while_it_loads(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The refusal half, through hit-tested input only.

    ``#tree-search-input`` is the control worth proving, because it is the one
    that silently keeps what it is given: its handler is bound in
    ``setupEventListeners()``, so a query typed earlier would sit in the box
    while the tree below stayed unfiltered -- #122's shape on this page.
    """
    # ---- Arrange ----------------------------------------------------------
    exam_id = _seed_plain_exam(wimi_session.user.db, "W121 Refusal")
    install_slow_bridge(wimi_page)
    wimi_page.goto("tree-editor", query={"exam_id": exam_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the tree editor markup never rendered"
    assert_slow_bridge_took(wimi_page)

    # ---- Act: a real click, then real typing -------------------------------
    assert_inside_the_window(wimi_page, GATED, "before aiming the click")
    real_click(wimi_page, centre_of(wimi_page, "#tree-search-input"))
    real_type(wimi_page, "W121-REFUSED")
    assert_inside_the_window(wimi_page, GATED, "after typing")

    typed = wimi_page.eval_js(
        "(() => { const el = document.getElementById('tree-search-input');"
        " return el ? el.value : null; })()")
    focused = wimi_page.eval_js(
        "(() => (document.activeElement && document.activeElement.id) || "
        "(document.activeElement && document.activeElement.tagName) || null)()")

    # ---- Assert: nothing landed -------------------------------------------
    assert typed == "", (
        f"the search box accepted {typed!r} while the page was still inert, so "
        f"the gate is not refusing hit-tested input (activeElement="
        f"{focused!r}). A box holding a query the page cannot run is the "
        f"wrong-answer half of #121/#122, not a dead control")
    assert focused != "tree-search-input", (
        f"the inert search box took focus (activeElement={focused!r}); `inert` "
        f"is meant to make it unfocusable, so either the attribute is absent "
        f"or something re-enabled it")

    # ---- Assert: and the page becomes usable afterwards -------------------
    # The positive control. Without it this test passes against a page whose
    # search box is permanently broken, which is a worse bug than the one
    # being fixed (#114's own rule).
    assert poll(wimi_page, PAGE_READY, timeout_ms=60000), (
        "TreeState.isPageReady never went true")
    real_click(wimi_page, centre_of(wimi_page, "#tree-search-input"))
    real_type(wimi_page, "W121-ACCEPTED")
    accepted = wimi_page.eval_js(
        "document.getElementById('tree-search-input').value")
    assert accepted == "W121-ACCEPTED", (
        f"after the gate lifted the search box still refuses input "
        f"(value={accepted!r}). The gate is permanent, which is far worse "
        f"than #121")


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("shape", ["plain", "dimensioned"])
def test_both_load_paths_release_the_gate(
    wimi_session: WimiTestSession, wimi_page: WimiPage, shape: str,
) -> None:
    """A gate released from one branch is a dead page on the other.

    ``initializeTreeEditor()`` forks on ``TreeState.usesDimensions``:
    ``loadHierarchy()`` for a plain exam, ``loadDimensions()`` ->
    ``selectDimension()`` -> ``loadDimensionHierarchy()`` for a dimensioned
    one. The dimensioned branch is the common case (USMLE, IM Shelf) and is
    exactly where mirroring gets forgotten, and no backend test can see either
    of them.
    """
    # ---- Arrange / Act ----------------------------------------------------
    db = wimi_session.user.db
    if shape == "plain":
        exam_id = _seed_plain_exam(db, "W121 Paths Plain")
        expect = "W121 Cardiovascular"
    else:
        exam_id = _seed_dimensioned_exam(db, "W121 Paths Dimensioned")
        expect = "W121 Renal"

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})

    # ---- Assert -----------------------------------------------------------
    assert poll(wimi_page, RELEASED, timeout_ms=60000), (
        f"the {shape} load path never removed `inert` from .tree-page, so "
        f"every click on this page is refused forever. markTreeEditorReady() "
        f"must be reached from the init chain's `finally`, which covers both "
        f"branches, not from the end of one of them (#114, #121)")
    assert wimi_page.eval_js(PAGE_READY) is True, (
        f"`inert` was removed on the {shape} path but TreeState.isPageReady "
        f"is false, so the attribute and the flag have drifted apart -- one "
        f"gate is meant to own both")

    drawn = poll(
        wimi_page,
        "(() => document.body.innerText.indexOf(%s) !== -1)()" % json.dumps(expect),
        timeout_ms=30000)
    assert drawn, (
        f"the {shape} exam's tree never drew ({expect!r} absent). The release "
        f"happened, so this is the panel being left hidden rather than the "
        f"gate: showLoading(false) is what reveals #tree-container, which now "
        f"ships hidden (#121)")

    state = _panel_state(wimi_page)
    assert state["empty"] == "hidden", (
        f"#tree-empty is showing on the {shape} path for an exam with "
        f"subjects (panels={state!r})")
    assert state["loading"] == "hidden", (
        f"#tree-loading is still spinning on the {shape} path after the tree "
        f"drew (panels={state!r})")


@pytest.mark.slow
@pytest.mark.regression
def test_a_missing_exam_id_still_releases_the_page(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The exit an `if` at the end of the happy path would miss.

    No ``exam_id`` takes the early return in ``initializeTreeEditor()``, which
    is *before* the ``try`` and so cannot be reached by its ``finally``. The
    page draws an error with a "Back to Exams" link; leaving it gated would
    refuse the one control it had just offered.
    """
    # ---- Arrange / Act ----------------------------------------------------
    wimi_page.goto("tree-editor")
    assert poll(wimi_page, PAGE_RENDERED), "the tree editor markup never rendered"

    # ---- Assert -----------------------------------------------------------
    assert poll(wimi_page, RELEASED, timeout_ms=15000), (
        "the page stayed inert after init bailed out for want of an exam id. "
        "The early return is before the `try`, so it needs its own "
        "markTreeEditorReady() call -- otherwise the error message it just "
        "drew sits behind a gate that never lifts (#114)")

    state = _panel_state(wimi_page)
    assert state["container"] == "shown", (
        f"the error message was written into a hidden #tree-container, so "
        f"nobody can read it (panels={state!r}). showError() has to reveal "
        f"the container now that it ships hidden (#121)")
    assert "No exam ID provided" in state["bodyText"], (
        f"the error itself is missing from the page (panels={state!r})")

    gate = gate_state(wimi_page)
    assert gate["state"] == "ready", (
        f"the page was released but the gate was left holding "
        f"(state={gate['state']!r}), so assistive technology is still being "
        f"told the hierarchy is being prepared while it is being abandoned "
        f"(#127)")
    assert HOLDING.lower() not in gate["text"].lower(), (
        f"the gate still reads {gate['text']!r} after the page was released")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# * `during["empty"] == "hidden"` fails against master, where #tree-empty has
#   no `hidden` class and is therefore the parse-time default. It is the ONLY
#   assertion here that catches that, because the accessibility tree is empty
#   during the gate whichever block is painted -- so the AX assertions below
#   it would pass against the unfixed page.
# * `during["loading"] == "shown"` is the other half, and stops "hide both
#   blocks" passing: a page that says nothing while it loads is honest but
#   mute, and #121 asked for one of the two to be true at parse.
# * `typed == ""` fails against master, where #tree-search-input is live and
#   keeps a query nothing will apply. It is driven with
#   `Input.dispatchMouseEvent` / `Input.insertText` because `el.value = 'x'`
#   works on an inert subtree and would pass against an ungated page (#285).
# * The `W121-ACCEPTED` control fails against the simplest wrong fix -- never
#   releasing -- which otherwise satisfies every refusal assertion above.
# * `test_both_load_paths_release_the_gate[dimensioned]` fails against a
#   release placed at the end of the plain branch, which is the shape the
#   dimension-symmetry gotcha predicts and which no backend test can reach.
# * `test_a_missing_exam_id_...` fails against a release reached only from the
#   `finally`, since that early return is outside the `try` -- and its
#   `container == "shown"` assertion fails against the #tree-container hidden
#   default without the matching showError() change.
