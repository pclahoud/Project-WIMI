"""Regression: anchoring an edge isolates rebalance to that parent only.

Stage 3 of ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.

The Hypertension example: a single leaf node ("Hypertension") lives
under both Cardiovascular and Pregnancy. Anchoring the
(Cardiovascular → Hypertension) edge marks it as exempt from sibling
rebalance under Cardiovascular, but it must NOT also anchor the
(Pregnancy → Hypertension) edge — anchor scope is per-edge, not per-
child. Likewise, writing to a sibling edge under Cardiovascular must
not touch the Pregnancy edge in any way.

This scenario verifies the *wiring* — that a real WIMI run with the
tree editor on screen exposes the new bridge slots
(``setEdgeAnchor``, ``updateEdgeRelativeWeight``) on the page and
that calling them from JS lands the right rows in
``subject_edges``. The pytest-only coverage in
``tests/database/test_edge_anchor_semantics.py`` proves the contract
at the data layer; this scenario proves the bridge surface does too.

API alias note
--------------

``src/web/js/api/_loader.js`` aliases ``window._wimiApi`` →
``window.api`` then deletes the ``_wimiApi`` handle. Stage 2's
scenario hit this — probe ``window.api`` (the canonical name).
"""
from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_anchor_per_edge_isolation(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Anchor under one parent + write a sibling under that parent must not touch the other parent's edge.

    Arrange
    -------
    Build the canonical Hypertension polyhierarchy:

        Cardiovascular ---┐                  Pregnancy ---┐
                          ├─ Hypertension                 ├─ Hypertension
        Arrhythmia    ----┘ (primary edge)                └─ Gestational DM
                                                            (separate edge)

    Each parent holds Hypertension plus a sibling so rebalance has
    a meaningful adjustable target.

    Act
    ---
    1. Navigate to the tree editor (forces the API loader to run).
    2. From JS, call ``api.setEdgeAnchor`` to anchor the
       Cardiovascular → Hypertension edge.
    3. From JS, call ``api.updateEdgeRelativeWeight`` to write to the
       Cardiovascular → Arrhythmia sibling edge.

    Assert
    ------
    At the DB level:

    - Cardiovascular → Hypertension: ``is_anchor=TRUE``, weight unchanged
      (Stage 2 contract: writes never auto-rebalance).
    - Pregnancy → Hypertension: ``is_anchor=FALSE`` (no cross-talk),
      weight unchanged (separate edge).
    - Cardiovascular → Arrhythmia: weight reflects the new value.
    - Pregnancy → Gestational DM: weight unchanged.
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name="Stage 3 Anchor Per Edge Repro",
        exam_description="Regression scenario for Stage 3 of the weight allocation plan",
    )

    cardio = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 3 Cardiovascular",
        level_type="System",
        exam_weight_low=20,
        exam_weight_high=20,
        weight_source='user_defined',
    )
    preg = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 3 Pregnancy",
        level_type="System",
        exam_weight_low=15,
        exam_weight_high=15,
        weight_source='user_defined',
    )
    hyp = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 3 Hypertension",
        level_type="Topic",
        parent_id=cardio.id,
        weight_source='user_defined',
    )
    arr = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 3 Arrhythmia",
        level_type="Topic",
        parent_id=cardio.id,
        weight_source='user_defined',
    )
    gdm = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 3 Gestational DM",
        level_type="Topic",
        parent_id=preg.id,
        weight_source='user_defined',
    )

    # The create_subject_node_with_weight path will already insert a
    # primary edge (cardio → hyp, cardio → arr, preg → gdm) under the
    # polyhierarchy migration. Add the second parent edge for hyp
    # explicitly so it lives under both Cardio and Pregnancy.
    edge_preg_hyp = db.add_edge(preg.id, hyp.id, is_primary=False)

    # Resolve the existing cardio→hyp primary edge for later assertions.
    primary_edges = db.get_edges_for_child(hyp.id)
    edge_cardio_hyp_id = next(
        e['edge_id'] for e in primary_edges
        if e['parent_id'] == cardio.id
    )
    # And the cardio→arr edge so we can write to it.
    arr_edges = db.get_edges_for_child(arr.id)
    edge_cardio_arr_id = next(
        e['edge_id'] for e in arr_edges
        if e['parent_id'] == cardio.id
    )

    # Seed baseline weights so post-write deltas are visible.
    db.execute(
        "UPDATE subject_edges SET relative_weight = ? WHERE id = ?",
        (60.0, edge_cardio_hyp_id),
    )
    db.execute(
        "UPDATE subject_edges SET relative_weight = ? WHERE id = ?",
        (40.0, edge_cardio_arr_id),
    )
    db.execute(
        "UPDATE subject_edges SET relative_weight = ? WHERE id = ?",
        (70.0, edge_preg_hyp.id),
    )
    # Find the preg→gdm edge.
    gdm_edges = db.get_edges_for_child(gdm.id)
    edge_preg_gdm_id = next(
        e['edge_id'] for e in gdm_edges if e['parent_id'] == preg.id
    )
    db.execute(
        "UPDATE subject_edges SET relative_weight = ? WHERE id = ?",
        (30.0, edge_preg_gdm_id),
    )
    db.conn.commit()

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("tree-editor")

    # Sanity check that the api wrappers are loaded. NOTE: probe
    # window.api (NOT window._wimiApi — _loader.js aliases and
    # deletes the _wimiApi handle).
    api_ready = wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.setEdgeAnchor === 'function' "
        "&& typeof window.api.updateEdgeRelativeWeight === 'function')()"
    )
    assert api_ready, (
        "window.api.setEdgeAnchor / updateEdgeRelativeWeight are not "
        "exposed on the page. Check that src/web/js/api/weights.js "
        "loaded via _loader.js and Stage 3's slots are wired."
    )

    # 1. Anchor the Cardiovascular → Hypertension edge.
    anchor_result: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                const res = await window.api.setEdgeAnchor({{
                    edgeId: {edge_cardio_hyp_id},
                    isAnchor: true,
                    reason: 'Stage 3 regression scenario'
                }});
                return {{ok: true, data: res}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert anchor_result.get("ok"), (
        f"api.setEdgeAnchor returned an error: {anchor_result!r}"
    )
    assert anchor_result["data"].get("ok") is True
    assert anchor_result["data"]["edge"]["is_anchor"] is True

    # 2. Write to the Cardiovascular → Arrhythmia sibling edge.
    write_result: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                const res = await window.api.updateEdgeRelativeWeight({{
                    edgeId: {edge_cardio_arr_id},
                    relativeWeight: 25,
                    reason: 'Stage 3 regression scenario'
                }});
                return {{ok: true, data: res}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert write_result.get("ok"), (
        f"api.updateEdgeRelativeWeight returned an error: {write_result!r}"
    )
    # Stage 2 contract: this writer must not promise sibling rebalance.
    assert "affected_siblings" not in write_result["data"], (
        f"updateEdgeRelativeWeight payload included affected_siblings — "
        f"Stage 2/3 contract forbids this. payload={write_result['data']!r}"
    )

    # ---- Assert: DB-level confirmation ------------------------------
    # Cardio → Hypertension: anchored, weight unchanged (no rebalance).
    row_cardio_hyp = db.fetchone(
        "SELECT relative_weight, is_anchor FROM subject_edges WHERE id = ?",
        (edge_cardio_hyp_id,),
    )
    assert row_cardio_hyp is not None
    assert bool(row_cardio_hyp['is_anchor']) is True
    assert float(row_cardio_hyp['relative_weight']) == pytest.approx(60.0), (
        f"Anchored Cardio→Hyp edge changed silently. "
        f"expected 60, got {row_cardio_hyp['relative_weight']}. "
        f"Stage 2/3 contract violated."
    )

    # Pregnancy → Hypertension: NOT anchored (cross-parent isolation),
    # weight unchanged (separate edge from the one we wrote).
    row_preg_hyp = db.fetchone(
        "SELECT relative_weight, is_anchor FROM subject_edges WHERE id = ?",
        (edge_preg_hyp.id,),
    )
    assert row_preg_hyp is not None
    assert bool(row_preg_hyp['is_anchor']) is False, (
        "Anchoring (Cardio → Hypertension) leaked to (Pregnancy → Hypertension). "
        "is_anchor must be per-edge per Stage 3 §3.3."
    )
    assert float(row_preg_hyp['relative_weight']) == pytest.approx(70.0), (
        f"(Pregnancy → Hypertension) weight changed unexpectedly: "
        f"expected 70, got {row_preg_hyp['relative_weight']}."
    )

    # Cardio → Arrhythmia: reflects the new value.
    row_cardio_arr = db.fetchone(
        "SELECT relative_weight FROM subject_edges WHERE id = ?",
        (edge_cardio_arr_id,),
    )
    assert row_cardio_arr is not None
    assert float(row_cardio_arr['relative_weight']) == pytest.approx(25.0)

    # Preg → Gestational DM: untouched.
    row_preg_gdm = db.fetchone(
        "SELECT relative_weight FROM subject_edges WHERE id = ?",
        (edge_preg_gdm_id,),
    )
    assert row_preg_gdm is not None
    assert float(row_preg_gdm['relative_weight']) == pytest.approx(30.0), (
        f"(Pregnancy → Gestational DM) sibling under the OTHER parent "
        f"changed unexpectedly: expected 30, got {row_preg_gdm['relative_weight']}."
    )
