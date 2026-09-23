"""Regression: tree editor level labels must read ``level_type``, not depth.

Forgejo issue #49 — "[bug] Tree editor 'Subjects by Level' labels nodes by
tree depth, ignoring their stored level_type" (split out of #7).

From the report::

    DB ``subject_nodes.level_type``: Root A -> 'System', Child B -> 'Topic',
    Grand C -> 'Topic'
    "Subjects by Level" renders: System 1  Subsystem 1  Topic 1

``showExamOverview`` computed ``getNodeLevel(node)`` (a walk up ``_parent``)
and indexed ``TreeState.hierarchyLevels[level - 1].level_name``; the node's
own ``level_type`` — the value the "Level Type" dropdown writes on create —
was never read. The same depth -> name substitution sat in ``renderNode``
(the ``.tree-node-level`` chip on every row) and in the details subtitle.

Why depth is wrong *in principle*, not merely wrong here
--------------------------------------------------------

A node in a polyhierarchy has no single depth. ``buildFlatNodeMap`` says so
itself: "``_parent`` is set to the parent of whichever appearance was visited
last and is best-effort". A subject with two parents at different levels is
at two depths at once, so a depth-derived label is both *ambiguous* (which
appearance won?) and *inconsistent* (the same subject wears two different
level names in one tree). ``level_type`` is stored per node and has neither
problem.

The seed below is built to expose exactly that: ``level_type`` deliberately
disagrees with depth, and the shared subject sits at depth 2 under one parent
and depth 3 under another.

    L49 Foundations   (root,   level_type='System')
      +- L49 Cardiovascular  (depth 2, level_type='System')  <- depth says "Subsystem"
           +- L49 Hypertension (depth 3, level_type='Topic')
    L49 Renal         (root,   level_type='System')
      +- L49 Hypertension    (same node, second edge -> depth 2)

Expected "Subjects by Level": ``System 3, Topic 1`` (four distinct subjects,
no "Subsystem" bucket at all). Pre-fix it reported a "Subsystem" bucket and
split the level counts by depth.

Markers / fixtures: ``@pytest.mark.slow`` + ``@pytest.mark.regression``;
``wimi_session`` + ``wimi_page``, seeding through ``wimi_session.user.db``.
"""

from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession



def _wait_for(
    wimi_page: WimiPage,
    js_expression: str,
    *,
    timeout_ms: int = 5000,
    poll_step_ms: int = 100,
) -> Any:
    """Poll ``js_expression`` until it returns something truthy.

    Returns the last value seen rather than raising, so the caller's own
    assertion still reports what it actually found. This replaces a fixed
    ``wait_for_timeout`` that was "enough on an idle box" and a race under
    load -- the #84 shape.
    """
    elapsed = 0
    last: Any = None
    while elapsed < timeout_ms:
        last = wimi_page.eval_js(js_expression)
        if last:
            return last
        wimi_page.wait_for_timeout(poll_step_ms)
        elapsed += poll_step_ms
    return last


def _wait_for_level_counts(page: WimiPage) -> dict[str, int]:
    """Poll the Exam Overview panel until "Subjects by Level" has rendered."""
    # TODO(Phase 3 / T3.6): replace with
    #     page.wait_for_bridge_call("getSubjectHierarchy")
    script = """
        (() => {
            // ``.level-counts`` is the container the issue's own probe
            // read; no testid exists on it and adding one is out of scope
            // for this fix (UI_AUDIT locator order applies to
            // wimi_page.locator, not to an eval_js aggregation like this).
            const items = document.querySelectorAll(
                '.level-counts .level-count-item'
            );
            const out = {};
            items.forEach(el => {
                const name = el.querySelector('.level-count-name');
                const value = el.querySelector('.level-count-value');
                if (name && value) out[name.textContent.trim()] =
                    Number(value.textContent.trim());
            });
            return out;
        })()
    """
    counts: dict[str, int] = {}
    for _ in range(40):
        counts = dict(page.eval_js(script) or {})
        if counts:
            return counts
        page.wait_for_timeout(250)
    return counts


@pytest.mark.slow
@pytest.mark.regression
def test_level_labels_read_level_type_not_depth(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Every level label in the tree editor must echo the node's ``level_type``."""
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Issue 49 Level Type Repro",
        exam_description="Regression scenario for Forgejo issue #49",
    )

    def node(name: str, level_type: str, parent_id: int | None = None) -> int:
        return db.create_subject_node(
            exam_context=exam.exam_name,
            name=name,
            level_type=level_type,
            parent_id=parent_id,
        ).id

    foundations = node("L49 Foundations", "System")
    # level_type deliberately disagrees with depth: a "System" at depth 2,
    # where the default hierarchy_level_definitions say "Subsystem".
    cardio = node("L49 Cardiovascular", "System", foundations)
    renal = node("L49 Renal", "System")
    # Shared subject: depth 3 under Cardiovascular, depth 2 under Renal.
    hypertension = node("L49 Hypertension", "Topic", cardio)
    db.add_edge(renal, hypertension)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    level_counts = _wait_for_level_counts(wimi_page)

    chip_labels: Any = wimi_page.eval_js(
        f"""
        (() => Array.from(document.querySelectorAll(
            '.tree-node[data-id="{hypertension}"] > .tree-node-content'
            + ' .tree-node-level'
        )).map(el => el.textContent.trim()))()
        """
    )

    wimi_page.eval_js(f"selectNode({cardio})")
    # Poll for the detail pane to fill rather than sleeping (#84).
    _wait_for(
        wimi_page,
        "(() => { const el = document.querySelector("
        "'[data-testid=\"tree-detail-level\"]');"
        " return !!el && el.textContent.trim().length > 0; })()",
    )
    detail_level = wimi_page.locator(testid="tree-detail-level").text().strip()

    # ---- Assert ------------------------------------------------------
    # 1. "Subjects by Level" must match SELECT level_type, COUNT(*).
    expected = {
        row["level_type"]: row["n"]
        for row in db.fetchall(
            "SELECT level_type, COUNT(*) AS n FROM subject_nodes "
            "WHERE exam_context = ? GROUP BY level_type",
            (exam.exam_name,),
        )
    }
    assert expected == {"System": 3, "Topic": 1}, f"Seed drifted: {expected!r}"
    assert level_counts == expected, (
        f'"Subjects by Level" reads {level_counts!r}; the stored level_type '
        f"values are {expected!r}. A 'Subsystem' bucket (or a split of the "
        "two System nodes) means the panel is still grouping by tree depth "
        "(issue #49)."
    )

    # 2. The shared subject renders twice — at depth 2 and depth 3. Both
    #    chips must say "Topic". Pre-fix they read "Subsystem" and "Topic",
    #    i.e. one subject wearing two level names in one tree.
    assert len(chip_labels) == 2, (
        f"Expected 2 rendered appearances of L49 Hypertension, got "
        f"{chip_labels!r}. Without the second parent edge this scenario "
        "cannot distinguish depth from level_type."
    )
    assert set(chip_labels) == {"Topic"}, (
        f"Row chips for the shared subject read {chip_labels!r}; its stored "
        "level_type is 'Topic' under every parent. Two different labels for "
        "one subject is the polyhierarchy face of issue #49."
    )

    # 3. The details subtitle must agree with the Level Type dropdown that
    #    wrote the value — "System", not the depth-2 name "Subsystem".
    assert detail_level == "System", (
        f"Details subtitle reads {detail_level!r} for L49 Cardiovascular, "
        "whose stored level_type is 'System'. The detail pane must not "
        "contradict the value its own Level Type dropdown writes."
    )
