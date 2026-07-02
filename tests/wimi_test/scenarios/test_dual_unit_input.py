"""Regression: Stage 6 dual-unit input + per-edge anchor UX (weight editor).

Stage 6 of ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.

The user-facing centerpiece. Verifies:

1. The segmented control (``%`` | ``Q``) renders when the exam declares
   a length_typical (length_kind != 'unknown').
2. The magic-suffix parser (``28q`` → unit='Q') works through the
   ``window.parseWeightInput`` helper.
3. ``api.setExplicitWeight`` writes the value, anchors the edge, and
   tags ``weight_source='user_explicit'`` in one atomic call (replacing
   the pre-Stage-6 two-call hot patch).
4. The DB-level state confirms ``relative_weight`` matches the converted
   value, ``is_anchor=TRUE``, ``weight_source='user_explicit'``.

The pytest-only coverage in
``tests/database/test_explicit_weight_anchors.py`` proves the *math* and
*bridge shape*; this scenario proves the *wiring* — that a real WIMI run
exposes ``window.api.setExplicitWeight`` and the helpers correctly.

Loader quirk note
-----------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because
``_loader.js`` aliases ``window._wimiApi`` → ``window.api`` then deletes
the source handle. See ``test_weight_no_silent_rebalance.py`` for the
established pattern.
"""
from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_dual_unit_input_writes_explicit_anchored_weight(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Type 28q under a 280-question exam → 10.0% anchored, source=user_explicit.

    Arrange
    -------
    Seed an exam with ``length_kind='fixed'``, ``length_typical=280``.
    One System parent at 100% with three Topic children at 25/25/50.
    Direct DB seeding bypasses the wizard so the scenario tests the
    write path, not the create path.

    Act
    ---
    1. Navigate to the tree editor.
    2. Verify the page exposes ``window.api.setExplicitWeight``.
    3. Verify the helpers ``parseWeightInput`` and ``convertWeightUnit``
       are accessible (the segmented-control + magic-suffix wiring).
    4. Probe the parser with ``"28q"`` and confirm it returns ``{value:
       28, unit: 'Q'}``.
    5. Call ``api.setExplicitWeight`` with the parsed pair.

    Assert
    ------
    * The bridge response shape carries ``applied_relative_weight=10.0``
      and ``applied_question_count=28`` and ``ok=true``.
    * DB-level state: ``subject_edges.relative_weight=10.0``,
      ``is_anchor=TRUE``, ``weight_source='user_explicit'``.
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name='Stage 6 Dual Unit Input',
        exam_description='Stage 6 regression — dual-unit input + anchor',
    )
    db.update_exam_length(
        exam.id, kind='fixed', min=280, max=280, typical=280,
    )

    # Parent System at 100% so the children inherit the full exam budget.
    parent = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name='Stage 6 Sys',
        level_type='System',
        exam_weight_low=100,
        exam_weight_high=100,
        weight_source='user_defined',
    )

    children_data = [
        ('Stage 6 ChildA', 25.0),
        ('Stage 6 ChildB', 25.0),
        ('Stage 6 ChildC', 50.0),
    ]
    child_ids = []
    edge_ids = []
    for name, rw in children_data:
        child = db.create_subject_node_with_weight(
            exam_context=exam.exam_name,
            name=name,
            level_type='Topic',
            parent_id=parent.id,
            relative_weight=rw,
            weight_source='user_defined',
        )
        child_ids.append(child.id)
        edge_row = db.fetchone(
            "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
            (parent.id, child.id),
        )
        if edge_row is None:
            edge = db.add_edge(parent.id, child.id, is_primary=True)
            edge_id = edge.id
        else:
            edge_id = edge_row['id']
        db.execute(
            "UPDATE subject_edges SET relative_weight = ?, "
            "weight_source = 'user_defined' WHERE id = ?",
            (rw, edge_id),
        )
        db.conn.commit()
        edge_ids.append(edge_id)

    target_child_id = child_ids[0]
    target_edge_id = edge_ids[0]

    # ---- Act ---------------------------------------------------------
    wimi_page.goto('tree-editor')

    # The Stage 6 contract requires the new bridge slot + helpers.
    api_ready = wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.setExplicitWeight === 'function')()"
    )
    assert api_ready, (
        'window.api.setExplicitWeight is not exposed on the page. '
        'Check that src/web/js/api/weights.js loaded via _loader.js.'
    )

    helpers_ready = wimi_page.eval_js(
        "(() => typeof window.parseWeightInput === 'function' "
        "&& typeof window.convertWeightUnit === 'function')()"
    )
    assert helpers_ready, (
        'Stage 6 helpers (parseWeightInput, convertWeightUnit) are not '
        'exposed globally. Check that src/web/js/weight_editor.js '
        'attaches them to window.'
    )

    # Probe the magic-suffix parser. "28q" must yield value=28, unit='Q'.
    parser_result = wimi_page.eval_js(
        "JSON.stringify(window.parseWeightInput('28q', '%'))"
    )
    import json
    parsed = json.loads(parser_result) if parser_result else None
    assert parsed is not None, 'parseWeightInput returned null for "28q"'
    assert parsed.get('value') == 28
    assert parsed.get('unit') == 'Q', (
        f"Magic-suffix 'q' should set unit='Q'; got {parsed!r}"
    )

    # Now exercise the canonical setExplicitWeight slot with the parsed
    # value. This is the same call the Apply handler makes after parsing.
    set_result: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                const res = await window.api.setExplicitWeight({{
                    edgeId: {target_edge_id},
                    value: 28,
                    unit: 'Q',
                    reason: 'Stage 6 regression scenario'
                }});
                return {{ok: true, data: res}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert set_result.get('ok'), (
        f'api.setExplicitWeight raised: {set_result!r}'
    )

    data = set_result['data']
    assert data.get('ok') is True, (
        f'setExplicitWeight returned ok=false: {data!r}'
    )
    assert data.get('applied_relative_weight') == pytest.approx(10.0), (
        f"Expected applied_relative_weight=10.0 (28q of 280); got {data!r}"
    )
    assert data.get('applied_question_count') == 28, (
        f"Expected applied_question_count=28; got {data!r}"
    )
    assert data.get('unit') == 'Q'

    # ---- Assert: DB-level confirmation ------------------------------
    edge_row = db.fetchone(
        "SELECT relative_weight, is_anchor, weight_source "
        "FROM subject_edges WHERE id = ?",
        (target_edge_id,),
    )
    assert edge_row is not None
    assert float(edge_row['relative_weight']) == pytest.approx(10.0), (
        f'Edge relative_weight mismatch: {edge_row!r}'
    )
    assert bool(edge_row['is_anchor']) is True, (
        f"Stage 6 contract: setExplicitWeight always anchors. Got: {edge_row!r}"
    )
    assert edge_row['weight_source'] == 'user_explicit', (
        f"Stage 6 contract: weight_source must be 'user_explicit'. "
        f"Got: {edge_row!r}"
    )

    # And the legacy mirror on subject_nodes.relative_weight must
    # carry the converted value too (the bug-fix for chip-not-updating).
    node_row = db.fetchone(
        "SELECT relative_weight FROM subject_nodes WHERE id = ?",
        (target_child_id,),
    )
    assert node_row is not None
    assert float(node_row['relative_weight']) == pytest.approx(10.0), (
        f'Mirror to subject_nodes.relative_weight failed: {node_row!r}. '
        f'Without this mirror, the chip will not update post-write.'
    )
