"""The tree editor shows subjects stranded outside every axis, and moves
them in (#605, owner 2026-10-10).

The defect this ends: adding the first axis to an exam that already has
subjects leaves every one of them at ``dimension_id NULL``. The
dimensioned tree filters on ``dimension_id`` and the plain tree is never
drawn again once an exam has an axis, so **the student's whole tree
vanishes** with no warning and nothing to click. `exam_uses_dimensions`
is derived, so one active dimension flips the exam the instant it is
saved and there is no migration to hang a prompt on.

The owner's design: a collapsed panel on the Archived-subjects pattern,
**and it can move them in** — a place the student resolves this from,
not a holding pen, and explicitly not a banner.

Three things a database test cannot see, which is why this file exists:

1. the tree really does draw **nothing** for that exam, so the panel is
   the only thing on screen that knows those subjects exist;
2. the panel appears, names them, and says how many travel with each;
3. pressing **Move in** actually puts them in the tree — which exercises
   the dimension cache invalidation, and that is frontend-only. CLAUDE.md
   is explicit that backend pytest cannot catch a stale dimensional
   cache, and that "after write X, UI shows new state" needs a scenario.

**The positive control is the first assertion, not an afterthought.** A
test that checks "the panel lists one subject" would pass on a page where
the tree also still drew them, which is not the state being fixed.

Loader quirk note
-----------------

Probes use ``window.api`` (NOT ``window._wimiApi``): ``_loader.js``
aliases it and deletes the source handle. ``TreeState`` is a top-level
``const``, reachable as a bare name and ``undefined`` on ``window``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

ROOT = "Cardiovascular System"
CHILD = "Arrhythmias"
GRANDCHILD = "Atrial fibrillation"
AXIS = "Discipline"


def _poll(wimi_page: WimiPage, read, predicate, *, timeout_ms: int = 20000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if predicate(last):
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed_stranded(db):
    """A three-subject tree, then an axis added after the fact.

    This is the student's path exactly: subjects first, axis later. The
    axis is created last so the subjects keep `dimension_id NULL`, which
    is what `create_dimension` leaves them at -- nothing backfills.
    """
    db._ensure_phase2_schema()
    exam = db.create_exam_context(
        exam_name="Pre-Axis Exam 605",
        exam_description="#605 - subjects that predate the first axis")

    ids = {}
    for order, name in enumerate((ROOT, CHILD, GRANDCHILD)):
        ids[name] = db.execute(
            "INSERT INTO subject_nodes (exam_context, name, level_type, "
            "dimension_id, sort_order, status) "
            "VALUES (?, ?, 'System', NULL, ?, 'active')",
            (exam.exam_name, name, order),
        ).lastrowid
    db.conn.commit()
    db.add_edge(ids[ROOT], ids[CHILD], is_primary=True)
    db.add_edge(ids[CHILD], ids[GRANDCHILD], is_primary=True)

    axis_id = db.create_dimension(
        exam_id=exam.id, name=AXIS, display_order=1)
    return exam.id, ids, axis_id


@pytest.mark.slow
@pytest.mark.regression
def test_the_panel_finds_the_tree_the_first_axis_hid(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    exam_id, ids, axis_id = _seed_stranded(wimi_session.user.db)

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})

    # ---- Positive control: the defect is live. The tree draws NOTHING,
    # which is the whole reason the panel has to exist. Without this, the
    # assertions below would pass on a page that showed the subjects too.
    panel_count = _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            "(() => { const el = document.querySelector("
            "'[data-testid=\"tree-unassigned-count\"]');"
            " return el ? el.textContent.trim() : null; })()"),
        lambda t: t not in (None, "", "0"),
    )
    assert panel_count == "1", (
        f"the panel should count the one stranded root, got {panel_count!r}")

    rows_in_tree = wimi_page.eval_js(
        "document.querySelectorAll('.tree-node').length")
    assert rows_in_tree == 0, (
        f"the tree drew {rows_in_tree} rows; if it can already show these "
        f"subjects then #605's defect is not reproduced and nothing below "
        f"proves anything")

    # ---- The panel is visible, and collapsed until asked.
    state = wimi_page.eval_js(
        "(() => { const p = document.querySelector("
        "'[data-testid=\"tree-unassigned-panel\"]');"
        " const b = document.querySelector("
        "'[data-testid=\"tree-unassigned-body\"]');"
        " return {shown: p && p.getClientRects().length > 0,"
        "         bodyHidden: b ? b.hasAttribute('hidden') : null}; })()")
    assert state["shown"], "the panel is hidden although subjects are stranded"
    assert state["bodyHidden"] is True, (
        "the panel must start collapsed, and `hidden` rather than merely "
        "invisible so a collapsed body is out of the accessibility tree")

    wimi_page.eval_js(
        "document.querySelector('[data-testid=\"tree-unassigned-toggle\"]').click()")

    row = _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            f"(() => {{ const el = document.querySelector("
            f"'[data-testid=\"tree-unassigned-row-{ids[ROOT]}\"]');"
            f" return el ? el.textContent.replace(/\\s+/g, ' ').trim() : null; }})()"),
        lambda t: isinstance(t, str) and t != "",
    )
    assert row and ROOT in row, f"the stranded root is not named: {row!r}"
    assert "with 2 underneath" in row, (
        f"the row must say what travels with it -- the name alone does not "
        f"tell a student two more subjects move: {row!r}")

    # Roots only: the descendants are not offered as separate rows, because
    # moving the root moves them.
    assert wimi_page.eval_js(
        "document.querySelectorAll("
        "'[data-testid^=\"tree-unassigned-row-\"]').length") == 1, (
        "descendants must not be listed separately; moving the root moves "
        "them, and a row each would offer the same operation three times")


@pytest.mark.slow
@pytest.mark.regression
def test_moving_them_in_puts_the_tree_back_on_screen(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """The half a database test cannot reach: the dimension cache.

    CLAUDE.md is explicit that a stale dimensional cache is frontend-only
    and that "after write X, UI shows new state" needs a scenario.
    """
    exam_id, ids, axis_id = _seed_stranded(wimi_session.user.db)

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            "(() => { const el = document.querySelector("
            "'[data-testid=\"tree-unassigned-count\"]');"
            " return el ? el.textContent.trim() : null; })()"),
        lambda t: t == "1",
    )
    wimi_page.eval_js(
        "document.querySelector('[data-testid=\"tree-unassigned-toggle\"]').click()")
    _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            f"!!document.querySelector("
            f"'[data-testid=\"tree-unassigned-move-{ids[ROOT]}\"]')"),
        lambda ok: ok is True,
    )

    wimi_page.eval_js(
        f"document.querySelector("
        f"'[data-testid=\"tree-unassigned-move-{ids[ROOT]}\"]').click()")

    # The tree now draws the root. Polled on the ROW COUNT rather than on
    # the panel emptying, because the point of the fix is that the subjects
    # become visible, not that a panel cleared.
    drawn = _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            "document.querySelectorAll('.tree-node').length"),
        lambda n: isinstance(n, int) and n > 0,
    )
    assert drawn and drawn >= 1, (
        "the tree still draws nothing after the move: the dimensional cache "
        "is serving the state from before the write")

    names = wimi_page.eval_js(
        "Array.from(document.querySelectorAll('.tree-node-name'))"
        ".map(el => el.textContent.trim())")
    assert ROOT in names, f"the moved root is not in the tree: {names!r}"

    # And the panel has emptied itself and hidden again.
    hidden = _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            "(() => { const p = document.querySelector("
            "'[data-testid=\"tree-unassigned-panel\"]');"
            " return p ? p.classList.contains('hidden') : null; })()"),
        lambda h: h is True,
    )
    assert hidden is True, (
        "nothing is stranded any more, so the panel must hide rather than "
        "sit there empty")

    # The whole subtree moved, not just the row that was pressed.
    db = wimi_session.user.db
    for name in (ROOT, CHILD, GRANDCHILD):
        row = db.fetchone(
            "SELECT dimension_id FROM subject_nodes WHERE id = ?",
            (ids[name],))
        assert row["dimension_id"] == axis_id, (
            f"{name} was left outside the axis; cross-dimensional edges are "
            f"a Non-Goal, so the subtree has to travel with its root")
