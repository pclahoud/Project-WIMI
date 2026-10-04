"""Regression: the tree editor renders expanded subtrees only (#177).

`renderNode` used to recurse into `node.children` regardless of
`isExpanded`, and `isExpanded` only added a CSS class. So every node was
always in the DOM and collapsing was cosmetic: measured on the seeded
USMLE outline, `collapseAll()` left the same 2,752 rows, the same
4,341,662 characters of HTML and the same ~210 ms rebuild. Every one of
the 14 `renderTree()` call sites paid for the whole tree, which is why
pressing **Escape** on an inline edit -- a no-op -- froze the page for a
fifth of a second, and why users reported the subject tree as laggy to
move around in.

After the fix, the same outline renders 18 rows and 29,551 characters at
load, and `renderTree()` costs 2.7 ms.

`toggleNode` now re-renders instead of flipping a class. That is
deliberate and not a targeted DOM patch: `TreeState.flatNodes` keeps only
the LAST appearance of each id (`buildFlatNodeMap` says so), so filling a
container from `flatNodes.get(id).children` would render the primary's
descendants under an alias appearance, or nothing under the primary.

The third test is the one worth keeping. Rendering-follows-expansion
exposed a pre-existing bug in `expandAll`, which walked `flatNodes` for
the same reason and therefore skipped any subject whose last appearance
was childless -- 10 parents of 325 on the seeded outline. That was
invisible while collapse was cosmetic (the rows were in the DOM anyway)
and would have become 141 missing rows.

Markers / fixtures follow the directory convention: `@pytest.mark.slow`
+ `@pytest.mark.regression`, `wimi_session` + `wimi_page`, seeded through
`wimi_session.user.db`.
"""

from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _count_rows(page: WimiPage) -> int:
    return int(page.eval_js("document.querySelectorAll('.tree-node').length"))


def _wait_for_tree(page: WimiPage) -> int:
    """Poll until the tree has painted; return the row count it settled on."""
    rows = 0
    for _ in range(80):
        rows = _count_rows(page)
        if rows:
            return rows
        page.wait_for_timeout(100)
    return rows


@pytest.fixture
def poly_tree(wimi_session: WimiTestSession, wimi_page: WimiPage) -> dict[str, Any]:
    """A shared subject whose LAST appearance is the childless one.

        W177 Alpha   (root)
          +- W177 Shared      <- primary, HAS a child
               +- W177 Deep Leaf
        W177 Zeta    (root)
          +- W177 Shared      <- second edge, alias appearance, no children

    `buildFlatNodeMap` walks roots in order and keeps the last occurrence,
    so `flatNodes` ends up holding the childless Zeta appearance. That is
    the condition `expandAll` used to trip over, and the fixture asserts
    it rather than assuming it -- if the backend ever ships descendants on
    alias appearances, this scenario should say so instead of passing for
    the wrong reason.
    """
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="W177 Render Repro",
        exam_description="Regression scenario for Forgejo issue #177",
    )

    def node(name: str, level_type: str, parent_id: int | None = None) -> int:
        return db.create_subject_node(
            exam_context=exam.exam_name,
            name=name,
            level_type=level_type,
            parent_id=parent_id,
        ).id

    alpha = node("W177 Alpha", "System")
    shared = node("W177 Shared", "Topic", alpha)
    deep = node("W177 Deep Leaf", "Subtopic", shared)
    zeta = node("W177 Zeta", "System")
    db.add_edge(zeta, shared)

    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    _wait_for_tree(wimi_page)

    return {"alpha": alpha, "shared": shared, "deep": deep, "zeta": zeta}


@pytest.mark.slow
@pytest.mark.regression
def test_a_collapsed_subtree_is_absent_from_the_dom_not_merely_hidden(
    wimi_page: WimiPage, poly_tree: dict[str, Any]
) -> None:
    """The whole point: collapsed means not rendered, not display:none."""
    assert _count_rows(wimi_page) == 2, (
        "a freshly loaded tree should render its two roots and nothing "
        "else; every descendant in the DOM is the #177 defect"
    )
    assert wimi_page.eval_js(
        f"!document.querySelector('.tree-node[data-id=\"{poly_tree['deep']}\"]')"
    ), "a grandchild under a collapsed root must not be in the DOM"


@pytest.mark.slow
@pytest.mark.regression
def test_expanding_renders_children_and_collapsing_removes_them(
    wimi_page: WimiPage, poly_tree: dict[str, Any]
) -> None:
    """`toggleNode` has to render now -- there is nothing there to reveal."""
    wimi_page.eval_js(f"toggleNode({poly_tree['alpha']})")
    assert wimi_page.eval_js(
        f"!!document.querySelector('.tree-node[data-id=\"{poly_tree['shared']}\"]')"
    ), "expanding a root must put its child in the DOM"
    assert wimi_page.eval_js(
        f"!document.querySelector('.tree-node[data-id=\"{poly_tree['deep']}\"]')"
    ), "expanding one level must not drag the whole subtree in with it"

    wimi_page.eval_js(f"toggleNode({poly_tree['alpha']})")
    assert _count_rows(wimi_page) == 2, "collapsing must take the rows back out"


@pytest.mark.slow
@pytest.mark.regression
def test_expand_all_reaches_a_subject_whose_last_appearance_is_childless(
    wimi_page: WimiPage, poly_tree: dict[str, Any]
) -> None:
    """`expandAll` must walk the tree, not `flatNodes` (#177).

    Guard the precondition first: if `flatNodes` happens to hold the
    appearance WITH children, the old implementation would have passed
    too and this test proves nothing.
    """
    assert wimi_page.eval_js(
        f"((TreeState.flatNodes.get({poly_tree['shared']}) || {{}}).children || []).length"
    ) == 0, (
        "precondition: flatNodes should hold the childless alias "
        "appearance of the shared subject"
    )

    wimi_page.eval_js("expandAll()")

    assert wimi_page.eval_js(
        f"!!document.querySelector('.tree-node[data-id=\"{poly_tree['deep']}\"]')"
    ), (
        "expandAll walked flatNodes, found the childless appearance of the "
        "shared subject, never expanded it, and left its descendants "
        "unrendered"
    )

    appearances = wimi_page.eval_js(
        "(() => { let n = 0;"
        " const walk = ns => { for (const x of ns) { n++;"
        " if (x.children) walk(x.children); } };"
        " walk(TreeState.rootNodes); return n; })()"
    )
    assert _count_rows(wimi_page) == appearances, (
        "expandAll must render one row per appearance; a shared subject "
        "appears under each of its parents"
    )
