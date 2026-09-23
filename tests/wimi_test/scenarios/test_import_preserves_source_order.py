"""Regression: an imported subject tree renders in the file's order.

Issue #62 — "Import gives every subject sort_order = 1, so the source
document's ordering is lost".

    ``import_node`` sets ``sort_order=node_data.get('sort_order', 1)``.
    ``sort_order`` is not a documented field in ``rules.txt``, so no
    hand-authored import file supplies it, so **every imported node
    lands with sort_order = 1**. The read path orders by
    ``se.display_order, sn.sort_order, sn.name`` — with every node tied
    on the first two, the tree renders **alphabetically by name**.

The trap this scenario exists for: the *edge's* ``display_order`` is
the first ORDER BY term for children, so a fix that moves only
``subject_nodes.sort_order`` looks correct in the table and changes
nothing on screen. ``tests/app/test_bridge_hierarchy_import.py`` pins
both columns; only a rendered assertion proves the tree the user
actually sees came out in source order.

Seeded names are deliberately anti-alphabetical, so "source order" and
"sorted by name" cannot both be satisfied by the same output.
"""

from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Alphabetical order is Alpha, Mid, Omega, Zulu — nothing like this.
_ROOTS = ["Zulu Root", "Alpha Root"]
_CHILDREN = ["Zulu Child", "Mid Child", "Alpha Child"]

_IMPORT_FILE = {
    "root_nodes": [
        {
            "name": _ROOTS[0],
            "level_type": "System",
            "children": [
                {"name": name, "level_type": "Topic"} for name in _CHILDREN
            ],
        },
        {"name": _ROOTS[1], "level_type": "System"},
    ]
}


def _wait_for(page: WimiPage, expression: str, *, what: str, tries: int = 50) -> None:
    for _ in range(tries):
        if page.eval_js(expression):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}: {expression}")


@pytest.mark.slow
@pytest.mark.regression
def test_imported_tree_renders_in_file_order(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Issue 62 Import Order",
        exam_description="Regression — source order must survive import",
    )
    exam_id = db.get_exam_context_by_name(exam.exam_name).id

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    _wait_for(
        wimi_page,
        "!!(window.api && window.api.importSubjectHierarchy)",
        what="the tree editor's API layer to come up",
    )

    # ---- Act: import through the real bridge slot ---------------------
    imported = wimi_page.eval_js(
        f"window.api.importSubjectHierarchy({exam_id}, "
        f"{json.dumps(json.dumps(_IMPORT_FILE))})",
        await_promise=True,
    )
    assert imported["imported_count"] == len(_ROOTS) + len(_CHILDREN), imported

    # Re-render from the database, then open every node so the children
    # are on screen and not merely in the document.
    wimi_page.eval_js("window.loadHierarchy()", await_promise=True)
    _wait_for(
        wimi_page,
        "document.querySelectorAll('.tree-node-name').length >= "
        f"{len(_ROOTS) + len(_CHILDREN)}",
        what="the imported nodes to render",
    )
    wimi_page.eval_js("window.expandAll()")
    wimi_page.wait_for_timeout(200)

    # ---- Assert: rendered order is the file's order -------------------
    rendered = wimi_page.eval_js(
        """(() => {
            const names = [];
            document.querySelectorAll('.tree-node-name').forEach(el => {
                names.push({
                    name: el.textContent.trim(),
                    visible: el.offsetParent !== null,
                    nested: !!el.closest('.tree-node-children')
                });
            });
            return names;
        })()"""
    )

    roots = [n["name"] for n in rendered if not n["nested"]]
    children = [n["name"] for n in rendered if n["nested"]]

    assert roots == _ROOTS, (
        f"root subjects rendered as {roots}, expected the file's order "
        f"{_ROOTS}. Sorted-by-name output means sort_order tied at the "
        "default and sn.name broke the tie."
    )
    assert children == _CHILDREN, (
        f"child subjects rendered as {children}, expected the file's order "
        f"{_CHILDREN}. Children order by se.display_order FIRST — if the "
        "bridge test passes and this one does not, the fix moved "
        "subject_nodes.sort_order and left the edge behind."
    )
    assert all(n["visible"] for n in rendered), (
        f"some imported subjects are in the DOM but not on screen: {rendered}"
    )


# ---------------------------------------------------------------------
# Bug context
# ---------------------------------------------------------------------
# Before the fix every imported node was created with sort_order = 1,
# and create_subject_node writes the edge as display_order = sort_order,
# so every sibling edge tied at 1 too. Both assertions above came back
# alphabetical: ["Alpha Root", "Zulu Root"] and ["Alpha Child",
# "Mid Child", "Zulu Child"]. The fix enumerates siblings during the
# import recursion and passes the position as sort_order, which
# create_subject_node then mirrors onto subject_edges.display_order —
# so the two assertions here fail independently if only one of the two
# columns is fixed.
