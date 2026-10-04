"""Issue #289 - five counters shipped a literal `0`, so two list pages stated
a count before anything had counted.

    "Measured on `fix/121-122-load-window-gates` while the bridge was held
    open, the tree editor's rendered body text during the load reads
    `0 subjects - Total: 0%` on an exam seeded with two subjects, and the entry
    browser's header reads `0 entries - 0 drafts` with two entries in the
    database."

`0` is the most plausible wrong answer there is. #2 was this exact reading
arriving as a *genuine* counting bug -- the header saying `0 entries` with 11
cards rendered -- so a reader cannot tell the shipped literal from the defect,
and neither can a screenshot in a bug report. It is also #83's test hazard: a
scenario waiting for `textContent.trim() != ''` is satisfied the instant the
document commits and then reads `0`.

The instrument is `innerText`, not the accessibility tree
---------------------------------------------------------
Both pages are gated (#121, #122), and while a container is `inert` its whole
subtree is out of the accessibility tree *whichever* markup is inside it -- so
an AX assertion that the page does not say "0 subjects" passes against the
unfixed page too. #121 measured that and it is the trap in the opposite
direction. `innerText` is the right instrument because it excludes
`display: none` subtrees, which is exactly the distinction the `hidden` class
makes.

The second test is about the fix, not the bug
---------------------------------------------
Emptying a node is free; *hiding* one is not. The tree editor's two toolbar
counters ship `hidden` and are revealed by `updateStats()`, so a release that
never runs leaves a permanently blank toolbar -- a worse bug than the one
being fixed, and the exact shape of #291's lesson about the two load paths.
It is therefore parametrised over both.
"""
from __future__ import annotations

import json

import pytest

from _helpers.page_gate import wait_for_release
from _helpers.w114_form_ready import install_slow_bridge, poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

#: Readable text, excluding `display: none` subtrees.
BODY_TEXT = "document.body.innerText"

TOOLBAR = """
(() => {
  const read = id => {
    const el = document.getElementById(id);
    if (!el) return null;
    const cs = getComputedStyle(el);
    return {
      text: el.textContent.trim(),
      shown: !(cs.display === 'none' || cs.visibility === 'hidden')
    };
  };
  return JSON.stringify({
    node_count: read('node-count'),
    total_weight: read('total-weight'),
    body: document.body.innerText
  });
})()
"""


def _seed_plain_exam(db) -> int:
    exam = db.create_exam_context(exam_name="W289 Plain", exam_description="")
    root = db.create_subject_node(exam.exam_name, "W289 Cardio", "System")
    db.create_subject_node(exam.exam_name, "W289 HTN", "Topic", parent_id=root.id)
    db.conn.commit()
    return exam.id


def _seed_dimensioned_exam(db) -> int:
    exam = db.create_exam_context(exam_name="W289 Dim", exam_description="")
    dim = db.create_dimension(exam_id=exam.id, name="W289 System",
                              display_order=1, is_required=True)
    root = db.create_subject_node(exam.exam_name, "W289 Renal", "System",
                                  dimension_id=dim)
    db.create_subject_node(exam.exam_name, "W289 Glomerular", "Topic",
                           parent_id=root.id, dimension_id=dim)
    db.conn.commit()
    assert db.exam_uses_dimensions(exam.id), (
        "the seed must produce a dimensioned exam or this parametrisation "
        "silently tests the plain path twice")
    return exam.id


@pytest.mark.parametrize("page_name,route,seed,forbidden", [
    ("tree editor", "tree-editor", _seed_plain_exam,
     ["0 subjects", "Total: 0%", "Root Total: 0"]),
    ("entry browser", "entry-browser", None,
     ["0 entries", "0 drafts"]),
])
def test_a_list_page_states_no_count_while_it_is_still_counting(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
    page_name: str, route: str, seed, forbidden: list[str],
) -> None:
    # ---- Arrange ----------------------------------------------------------
    db = wimi_session.user.db
    query = {"exam_id": seed(db)} if seed else None
    install_slow_bridge(wimi_page)
    wimi_page.goto(route, query=query, wait_for_bridge=False)

    # ---- Act --------------------------------------------------------------
    # Poll for the document, not for the text: a poll that waits for the
    # expected text cannot report the wrong one.
    assert poll(wimi_page, "(() => !!document.body)()"), "no document"
    text = wimi_page.eval_js(BODY_TEXT) or ""

    # ---- Assert -----------------------------------------------------------
    said = [f for f in forbidden if f in text]
    assert not said, (
        f"the {page_name} states {said} while its bridge calls are still in "
        f"flight. #289: a shipped `0` is indistinguishable from a measured "
        f"one -- #2 was exactly this reading as a real counting bug. Full "
        f"text: {text[:400]!r}"
    )


@pytest.mark.parametrize("shape", ["plain", "dimensioned"])
def test_the_tree_toolbar_counters_do_appear_once_they_have_counted(
    wimi_session: WimiTestSession, wimi_page: WimiPage, shape: str,
) -> None:
    """The cost of hiding them, paid for on both load paths.

    `updateStats()` is what reveals these two, and it is reached through
    `loadHierarchy()` for a plain exam and `loadDimensionHierarchy()` for a
    dimensioned one. If only one branch ran it, the common case (USMLE, IM
    Shelf) would be a toolbar that never says anything at all.
    """
    # ---- Arrange ----------------------------------------------------------
    db = wimi_session.user.db
    exam_id = (_seed_dimensioned_exam(db) if shape == "dimensioned"
               else _seed_plain_exam(db))

    # ---- Act --------------------------------------------------------------
    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    wait_for_release(wimi_page)
    assert poll(wimi_page,
                "(() => { const e = document.getElementById('node-count');"
                " return !!e && !e.classList.contains('hidden'); })()"), (
        f"the {shape} load path never revealed #node-count, so its toolbar "
        f"is permanently blank. Full text: "
        f"{json.loads(wimi_page.eval_js(TOOLBAR))['body'][:300]!r}")

    # ---- Assert -----------------------------------------------------------
    state = json.loads(wimi_page.eval_js(TOOLBAR))
    for name in ("node_count", "total_weight"):
        shown = state[name]
        assert shown and shown["shown"] is True, (
            f"#{name.replace('_', '-')} is not displayed after the {shape} "
            f"load: {state!r}")
        assert shown["text"], (
            f"#{name.replace('_', '-')} is displayed and empty after the "
            f"{shape} load: {state!r}")
    assert state["node_count"]["text"] == "2 subjects", (
        f"the toolbar counted {state['node_count']['text']!r} on an exam "
        f"seeded with 2 subjects: {state!r}")
