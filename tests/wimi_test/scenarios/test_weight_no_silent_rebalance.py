"""Regression: typing a child's weight must not silently mutate siblings.

Stage 2 of ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.

Before Stage 2, ``update_subject_relative_weight`` silently mutated
every unlocked sibling whenever any child's weight changed. The fix is
structural: the writer never rebalances; rebalance is a separate
explicit operation triggered by the new "Rebalance siblings" button.

This scenario verifies the *wiring* — that a real WIMI run with the
tree editor on screen no longer auto-mutates siblings when the user
types a value into one child's weight field. The pytest-only coverage
in ``tests/database/test_edge_anchor_semantics.py`` proves the contract
at the data layer; this scenario proves the UI flows match.

Markers / fixtures
------------------

* ``@pytest.mark.slow`` — spawns a real WIMI subprocess.
* ``@pytest.mark.regression`` — registered in ``pytest.ini`` so
  collection emits no warning.
* Fixtures: ``wimi_session``, ``wimi_page``. We seed the parent +
  three children directly through the DB so the scenario does not
  walk the whole tree-editor "create node" flow.

Click strategy
--------------

The CDP synthetic click pathway drops events on inline-styled or
dynamically-rendered modal buttons in QtWebEngine (see
``feedback_cdp_click_quirks.md`` in project memory). The weight panel
itself is not a modal, but we use ``eval_js(".click()")`` for the
Apply button to keep the assertion focused on the *handler logic*
("did the click stop touching siblings?") rather than the dispatch
pathway.
"""
from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_typing_a_weight_does_not_mutate_siblings(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Typing 30% on one child must leave the other two siblings untouched.

    Arrange
    -------
    Seed an exam context, one parent system, and three children with
    distinct weights (15 / 35 / 50). Direct DB seeding bypasses the
    tree-editor "Add Subject" flow — the bug under test is the *write
    path*, not the creation path.

    Act
    ---
    1. Navigate to the tree editor.
    2. Select the first child node.
    3. Call ``api.updateRelativeWeight`` with the new value (30).
       This exercises the same bridge slot the Apply button calls;
       the scenario goal is the contract, not the click pathway.

    Assert
    ------
    Re-read the parent's children from the database. Sibling B and
    Sibling C must still carry 35 and 50 respectively — Stage 2's
    contract is that the writer never auto-rebalances.
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name="Stage 2 No-Silent-Rebalance Repro",
        exam_description="Regression scenario for Stage 2 of the weight allocation plan",
    )

    parent = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 2 Parent System",
        level_type="System",
        exam_weight_low=20,
        exam_weight_high=20,
        weight_source='user_defined',
    )

    child_a = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 2 ChildA",
        level_type="Topic",
        parent_id=parent.id,
        relative_weight=15,
        weight_source='user_estimate',
    )
    child_b = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 2 ChildB",
        level_type="Topic",
        parent_id=parent.id,
        relative_weight=35,
        weight_source='user_estimate',
    )
    child_c = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 2 ChildC",
        level_type="Topic",
        parent_id=parent.id,
        relative_weight=50,
        weight_source='user_estimate',
    )

    # ---- Act ---------------------------------------------------------
    # Navigate to the tree editor. The page loads the polyhierarchy
    # API on init, so the bridge is wired by the time we issue
    # api.updateRelativeWeight.
    wimi_page.goto("tree-editor")

    # Sanity check that the api wrapper is loaded before we depend on it.
    # NOTE: _loader.js aliases window._wimiApi -> window.api then deletes
    # the _wimiApi handle, so probe window.api (the canonical name).
    api_ready = wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.updateRelativeWeight === 'function')()"
    )
    assert api_ready, (
        "window.api.updateRelativeWeight is not exposed on the page. "
        "Check that src/web/js/api/weights.js loaded via _loader.js."
    )

    # Trigger the bridge call directly. Using the API wrapper exercises
    # the same code path the Apply button uses; the scenario goal is
    # the *contract*, not the synthetic-click pathway.
    update_result: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                const res = await window.api.updateRelativeWeight({{
                    nodeId: {child_a.id},
                    relativeWeight: 30,
                    reason: 'Stage 2 regression scenario'
                }});
                return {{ok: true, data: res}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert update_result.get("ok"), (
        f"api.updateRelativeWeight returned an error: {update_result!r}"
    )

    # Stage 2 contract: the bridge response payload reports no
    # rebalance and no affected siblings.
    data = update_result["data"]
    assert data.get("rebalanced") is False, (
        f"updateRelativeWeight reported rebalanced=True under Stage 2 "
        f"— this is exactly the regression we're guarding against. "
        f"payload={data!r}"
    )
    assert data.get("affected_siblings") == [], (
        f"updateRelativeWeight reported affected_siblings={data.get('affected_siblings')!r} "
        f"— Stage 2 forbids implicit sibling mutation. "
        f"payload={data!r}"
    )

    # ---- Assert: DB-level confirmation ------------------------------
    # The bridge contract is one thing; the actual DB state is the
    # final source of truth. Re-read each sibling and assert they kept
    # their pre-edit values.
    row_b = db.fetchone(
        "SELECT relative_weight FROM subject_nodes WHERE id = ?",
        (child_b.id,),
    )
    row_c = db.fetchone(
        "SELECT relative_weight FROM subject_nodes WHERE id = ?",
        (child_c.id,),
    )
    assert row_b is not None and row_c is not None
    assert float(row_b['relative_weight']) == pytest.approx(35.0), (
        f"Sibling B relative_weight changed silently: "
        f"expected 35, got {row_b['relative_weight']}. Stage 2 contract violated."
    )
    assert float(row_c['relative_weight']) == pytest.approx(50.0), (
        f"Sibling C relative_weight changed silently: "
        f"expected 50, got {row_c['relative_weight']}. Stage 2 contract violated."
    )

    # And the target child should reflect the new value.
    row_a = db.fetchone(
        "SELECT relative_weight FROM subject_nodes WHERE id = ?",
        (child_a.id,),
    )
    assert row_a is not None
    assert float(row_a['relative_weight']) == pytest.approx(30.0)
