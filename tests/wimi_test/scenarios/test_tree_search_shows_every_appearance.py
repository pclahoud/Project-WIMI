"""Regression: the tree search draws every appearance of a shared subject (#850).

``applyTreeSearch`` found matches in ``TreeState.flatNodes`` and kept their
ancestors visible by climbing ``node._parent``. ``flatNodes`` keeps one record
per id -- the appearance visited LAST -- so a subject with several parents
kept exactly one ancestor chain, and ``renderNodes`` filtered the others out
at the root. A student searching for a subject they had just given a second
parent saw it drawn once, under the non-primary parent with *also here*, and
concluded it had moved. Measured on master ``82dab8d``: both edges intact,
both appearances drawn with the search cleared, one drawn with it applied.
Which one survived was decided by the roots' sort order.

``deep venous thrombosis`` is one of the ``exam_outline`` fixture's
cross-listed topics: three parents under three different roots, the first
primary. The search must draw it under all three, and only the primary row
may go without the *also here* chip.

Both load paths are driven -- ``loadHierarchy`` on the plain exam the seeder
builds, and ``loadDimensionHierarchy`` after moving its trees into an axis,
which is the path the student was on (CLAUDE.md, *Dimension code path
symmetry*).

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import open_tree_editor, wait_for

SUBJECT = "deep venous thrombosis"

#: Every rendered row for the subject, with the id of the row it sits under.
ROWS = """
((id) => [...document.querySelectorAll(`.tree-node[data-id="${id}"]`)].map(r => ({
    parent: Number(r.parentElement.closest('.tree-node')?.dataset.id ?? 0),
    also_here: !!r.querySelector(':scope > .tree-node-content .tree-node-alias-chip'),
})))(%d)
"""


def _seed(db, *, dimensioned: bool) -> tuple[int, int, list[dict]]:
    """Seed the outline; return (exam id, subject id, its parent edges)."""
    exam_id, exam_name = db.conn.execute(
        "SELECT id, exam_name FROM exam_contexts ORDER BY id DESC LIMIT 1").fetchone()
    subject = db.conn.execute(
        "SELECT id FROM subject_nodes WHERE exam_context = ? AND name = ?"
        " AND status = 'active'", (exam_name, SUBJECT)).fetchone()[0]
    edges = [dict(r) for r in db.conn.execute(
        "SELECT parent_id, is_primary FROM subject_edges WHERE child_id = ?",
        (subject,)).fetchall()]
    if dimensioned:
        dim = db.create_dimension(exam_id=exam_id, name="System",
                                  display_order=1, is_required=True)
        roots = [r[0] for r in db.conn.execute(
            "SELECT n.id FROM subject_nodes n WHERE n.exam_context = ?"
            " AND n.status = 'active' AND NOT EXISTS (SELECT 1 FROM"
            " subject_edges e WHERE e.child_id = n.id)", (exam_name,))]
        db.move_subjects_into_axis(roots, dim)
    assert db.exam_uses_dimensions(exam_id) == dimensioned, "seed drifted"
    return exam_id, subject, edges


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("dimensioned", [False, True],
                         ids=["loadHierarchy", "loadDimensionHierarchy"])
def test_a_search_draws_a_shared_subject_under_every_parent(
    wimi_session: WimiTestSession, wimi_page: WimiPage, dimensioned: bool,
) -> None:
    wimi_session.user.seed("exam_outline")
    db = wimi_session.user.db
    exam_id, subject, edges = _seed(db, dimensioned=dimensioned)
    parents = {e["parent_id"] for e in edges}
    primary = {e["parent_id"] for e in edges if e["is_primary"]}
    # The premise, checked rather than assumed: three parents, one primary.
    assert len(parents) == 3 and len(primary) == 1, edges

    open_tree_editor(wimi_page, exam_id)
    assert wimi_page.eval_js("TreeState.usesDimensions") == dimensioned

    wimi_page.eval_js(
        "(() => { const i = document.getElementById('tree-search-input');"
        f" i.value = {json.dumps(SUBJECT)}; i.dispatchEvent(new Event('input')); }})()")
    wait_for(wimi_page, "TreeState.searchQuery === " + json.dumps(SUBJECT),
             what="the debounced search to apply")
    wimi_page.wait_for_timeout(200)

    rows = wimi_page.eval_js(ROWS % subject)
    assert {r["parent"] for r in rows} == parents, (
        f"the search must draw {SUBJECT!r} under all of {sorted(parents)}; "
        f"it drew {rows}")
    assert len(rows) == len(parents), f"one row per parent, got {rows}"
    plain = [r["parent"] for r in rows if not r["also_here"]]
    assert plain == sorted(primary), (
        f"only the primary appearance goes without 'also here': {rows}")
    badge = wimi_page.eval_js("document.getElementById('tree-search-count').textContent")
    assert badge == "1 match", f"the badge counts subjects, not rows: {badge!r}"
