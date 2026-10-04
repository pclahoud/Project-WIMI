"""Make the tree editor's descendants visible before asserting on them (#177).

Until #177, `renderNode` recursed into every node's children regardless of
`isExpanded`, and `isExpanded` only added a CSS class. `tree.css` hides
`.tree-node-children` unless the parent carries `.expanded`, so the whole
tree sat in the DOM while the user saw only the roots.

That let a scenario query `[data-testid="tree-node-weight-<id>"]` for a
node three levels down and get a hit **for something the user could not
see** — the same class of hazard as the `:empty` zero-pixel render (#134)
and the harness once driving a page with no view (TEST_INFRASTRUCTURE.md
§12c): a green assertion about invisible state.

Now that rendering follows expansion, a collapsed descendant is genuinely
absent. Scenarios that want to assert on one must open it first, which is
what a student does, and the assertion becomes a statement about what is
actually on screen.

Use `expand_whole_tree` when the scenario does not care which parent it
came from, and `expand_and_wait_for` when it is waiting for specific rows.
"""
from __future__ import annotations

from wimi_test.page import WimiPage


def expand_whole_tree(page: WimiPage) -> int:
    """Expand every parent and return the number of rendered rows.

    `expandAll()` walks the node tree (not `TreeState.flatNodes`, which
    keeps only each id's last appearance — see #177), so a subject that
    appears under several parents is expanded under all of them.
    """
    page.eval_js("expandAll()")
    return int(page.eval_js("document.querySelectorAll('.tree-node').length"))


def expand_and_wait_for(
    page: WimiPage,
    expression: str,
    *,
    what: str,
    tries: int = 50,
    poll_ms: int = 100,
) -> None:
    """Expand the tree, then poll `expression` until it is truthy.

    Expanding first is not a substitute for the wait: the tree may still
    be loading when the scenario arrives, in which case `expandAll()` has
    nothing to expand yet. So expand on every poll rather than once up
    front — it is idempotent, and it removes the ordering assumption.
    """
    for _ in range(tries):
        page.eval_js("if (window.expandAll) expandAll();")
        if page.eval_js(expression):
            return
        page.wait_for_timeout(poll_ms)
    raise AssertionError(f"timed out waiting for {what}: {expression}")
