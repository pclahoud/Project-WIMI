"""Regression: Stage 7 interval-rounding feasibility badge.

Stage 7 of ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.

Verifies that the weight modal's feasibility-badge slot (reserved by
Stage 6) is populated with the right status class + copy when the
children's [low, high] ranges don't fit cleanly inside the parent's
range.

What's covered
--------------

1. ``api.getFeasibilityReport`` is exposed on the page.
2. With 5 children at 18% under a parent at 90-99% and N=10, the
   bridge returns ``status='infeasible'`` (rounding-class violation —
   ⌈18·10/100⌉×5 = 10 > ⌊99·10/100⌋ = 9).
3. After ``initWeightEditor`` runs, ``#weight-feasibility-badge``
   carries the ``status-infeasible`` CSS class and the canonical copy
   ``Can't fit child minimums (≥10 q) into parent maximum (9 q).``.

Loader quirk note
-----------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because
``_loader.js`` aliases ``window._wimiApi`` → ``window.api`` then deletes
the source handle. See ``test_weight_no_silent_rebalance.py`` and
``test_dual_unit_input.py`` for the established pattern.
"""
from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_feasibility_badge_renders_infeasible_status(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """5 children at 18% under a 90-99% parent (N=10) → infeasible badge.

    Arrange
    -------
    Seed an exam with ``length_kind='fixed'``, ``length_typical=10``.
    One System parent with range 90-99% and five children each at 18%.

    Math: ``Σ⌈18·10/100⌉ = Σ⌈1.8⌉ = 10`` vs
    ``⌊99·10/100⌋ = ⌊9.9⌋ = 9`` → infeasible.

    Act
    ---
    1. Navigate to the tree editor.
    2. Verify the page exposes ``window.api.getFeasibilityReport``.
    3. Call ``api.getFeasibilityReport`` for the parent — expect
       ``status='infeasible'``.
    4. Open the weight editor for one child via
       ``window.initWeightEditor`` (driven through the rendered tree
       state — same hook the chip-click handler uses).
    5. Wait for the badge to render and assert the CSS class + copy.

    Assert
    ------
    * ``#weight-feasibility-badge`` is visible (no ``hidden`` attribute).
    * It carries the ``status-infeasible`` class.
    * Its text matches the canonical copy from the Stage 7 spec.
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name='Stage 7 Feasibility Badge',
        exam_description='Stage 7 regression — feasibility badge wiring',
    )
    db.update_exam_length(
        exam.id, kind='fixed', min=10, max=10, typical=10,
    )

    # Parent with range 90-99%.
    parent = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name='Stage 7 InfParent',
        level_type='System',
        exam_weight_low=90,
        exam_weight_high=99,
        weight_source='user_defined',
    )

    # 5 children each at 18% (no absolute range — helper uses rw for
    # both low and high).
    child_ids = []
    edge_ids = []
    for i in range(5):
        child = db.create_subject_node_with_weight(
            exam_context=exam.exam_name,
            name=f'Stage 7 Child{i}',
            level_type='Topic',
            parent_id=parent.id,
            relative_weight=18,
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
            (18, edge_id),
        )
        db.conn.commit()
        edge_ids.append(edge_id)

    # ---- Act ---------------------------------------------------------
    # Pass the exam_id query param so the tree editor's TreeState gets
    # populated for our seeded exam — otherwise initWeightEditor can't
    # find the node in flatNodes.
    wimi_page.goto('tree-editor', query={'exam_id': exam.id})

    api_ready = wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.getFeasibilityReport === 'function')()"
    )
    assert api_ready, (
        'window.api.getFeasibilityReport is not exposed on the page. '
        'Check that src/web/js/api/weights.js loaded via _loader.js.'
    )

    # Probe the bridge directly to confirm the math.
    bridge_result: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                const res = await window.api.getFeasibilityReport({parent.id});
                return {{ok: true, data: res}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert bridge_result.get('ok'), (
        f'api.getFeasibilityReport raised: {bridge_result!r}'
    )
    payload = bridge_result['data']
    assert payload.get('status') == 'infeasible', (
        f"Expected status='infeasible'; got {payload!r}"
    )
    assert payload.get('parent_high_q') == 9
    assert payload.get('children_low_sum_q') == 10

    # Wait for the tree to render so TreeState.flatNodes is populated.
    # Poll for the seeded child node via a small JS readiness probe.
    target_child_id = child_ids[0]
    ready = wimi_page.eval_js(
        f"""
        (async () => {{
            for (let i = 0; i < 40; i++) {{
                if (window.TreeState
                    && window.TreeState.flatNodes
                    && window.TreeState.flatNodes.get({target_child_id})) {{
                    return true;
                }}
                await new Promise(r => setTimeout(r, 100));
            }}
            return false;
        }})()
        """,
        await_promise=True,
    )
    assert ready, (
        f'TreeState.flatNodes never received child {target_child_id} '
        f'within 4s. Check that the tree-editor loaded the seeded exam.'
    )

    # Open the weight editor for the first child. Synthesize the
    # rendered-node object the editor consumes — we don't drive a real
    # click because the chip onclick handler reads from the
    # TreeState.flatNodes map, which is already populated by the
    # render pass.
    open_result: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                const node = window.TreeState
                    ? window.TreeState.flatNodes.get({target_child_id})
                    : null;
                if (!node) {{
                    return {{
                        ok: false,
                        error: 'node not in TreeState.flatNodes',
                    }};
                }}
                // Stage 6's initWeightEditor reads from TreeState.examContextId
                // and queries the bridge — give it the same shape it would
                // get from the tree-row click path.
                await window.initWeightEditor(node, {{ precision: 1 }});
                // Allow the fire-and-forget feasibility-badge render to land.
                await new Promise(r => setTimeout(r, 500));
                return {{ok: true}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert open_result.get('ok'), (
        f'initWeightEditor failed: {open_result!r}'
    )

    # ---- Assert: badge DOM state ------------------------------------
    badge_state: Any = wimi_page.eval_js(
        """
        (() => {
            const b = document.getElementById('weight-feasibility-badge');
            if (!b) return {found: false};
            return {
                found: true,
                hidden: b.hasAttribute('hidden'),
                classList: Array.from(b.classList),
                text: b.textContent || '',
            };
        })()
        """
    )
    assert badge_state.get('found'), (
        'weight-feasibility-badge element not in DOM. Check '
        'renderWeightEditor in src/web/js/weight_editor.js.'
    )
    assert not badge_state.get('hidden'), (
        f'Badge should be visible (no hidden attr); got {badge_state!r}'
    )
    classes = badge_state.get('classList') or []
    assert 'status-infeasible' in classes, (
        f"Expected 'status-infeasible' in badge classList; got {classes!r}"
    )

    text = (badge_state.get('text') or '').strip()
    assert 'Can' in text and "fit child minimums" in text, (
        f"Badge text should match the Stage 7 spec copy; got {text!r}"
    )
    assert '10' in text, (
        f"Badge text should mention 10 q (children minimum); got {text!r}"
    )
    assert '9' in text, (
        f"Badge text should mention 9 q (parent maximum); got {text!r}"
    )
