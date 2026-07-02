"""Regression: Stage 8 CAT (variable-length adaptive) exam display.

Stage 8 of ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.

When the exam declares ``length_kind='range'`` (CAT — NCLEX-RN and
similar), the tree-editor weight chips for child rows should render
``~XX.X q (planning estimate)`` instead of the integer ``~XX q``
that fixed-length exams use. This proves the wiring from the backend
``is_adaptive`` flag through ``getEffectiveQuestionCounts`` →
``enrichNodesWithQuestionCounts`` → the chip render.

The pytest-only coverage in ``tests/database/test_cat_allocation.py``
proves the *math* (the allocator returns floats and
``get_effective_question_counts`` marks rows ``is_adaptive=True``).
This scenario proves the *wiring* — a real WIMI run renders the
adaptive copy on the chip.

Loader quirk note
-----------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because
``_loader.js`` aliases ``window._wimiApi`` → ``window.api`` then
deletes the source handle. See ``test_weight_no_silent_rebalance.py``
for the established pattern. CDP-click quirk: clicks on dynamic
elements are driven via ``eval_js(".click()")`` rather than
``locator.click()`` per the feedback memory.
"""
from __future__ import annotations

import re
from typing import List

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


# Stage 8 chip text: float + " (planning estimate)" qualifier.
# Tolerates surrounding whitespace and the dual-unit `XX.X% • ~Y.Y q's ...`
# format. The "q's" plural matches the chip text rendered by
# tree_editor.js / weight_analysis.js / subject_deep_dive.js — the
# parser in weight_editor.js accepts both "q" and "q's" on input so
# user-typed values still round-trip.
CHIP_ADAPTIVE_PATTERN = re.compile(
    r"~\d+\.\d+\s*q's\s*\(planning estimate\)"
)


@pytest.mark.slow
@pytest.mark.regression
def test_cat_exam_chip_shows_planning_estimate(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """NCLEX-like exam (length_kind='range', typical=100) renders
    child chips as ``~N.N q (planning estimate)``.

    Arrange
    -------
    Seed an exam with ``length_kind='range'``, ``length_typical=100``,
    ``length_min=85``, ``length_max=150`` (NCLEX-RN profile). One
    System parent at 100% with three Topic children weighted
    40/30/30. The 40/30/30 split with typical=100 produces clean
    floats (40.0, 30.0, 30.0) — the formatting still goes through
    the adaptive branch because ``is_adaptive=True``.

    Act
    ---
    1. Navigate to the tree editor.
    2. Force ``TreeState.examContextId`` and call ``loadHierarchy``
       (the route resolver doesn't pass query params; see
       ``test_dual_unit_display.py`` for the established pattern).
    3. Read the chip text for the three children via ``eval_js``.

    Assert
    ------
    * Each chip's text matches ``~\\d+\\.\\d+ q \\(planning estimate\\)``.
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name="Stage 8 NCLEX CAT Display",
        exam_description="Stage 8 regression — CAT chip display",
    )
    db.update_exam_length(
        exam.id, kind="range", min=85, max=150, typical=100,
    )

    # Sanity: the helper agrees the exam is adaptive.
    assert db.is_adaptive_exam(exam.id) is True, (
        "Stage 8 contract: length_kind='range' must report is_adaptive=True"
    )

    parent = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 8 Sys",
        level_type="System",
        exam_weight_low=100,
        exam_weight_high=100,
        weight_source="user_defined",
    )

    children_data = [
        ("Stage 8 ChildA", 40.0),
        ("Stage 8 ChildB", 30.0),
        ("Stage 8 ChildC", 30.0),
    ]
    child_ids: List[int] = []
    for name, rw in children_data:
        child = db.create_subject_node_with_weight(
            exam_context=exam.exam_name,
            name=name,
            level_type="Topic",
            parent_id=parent.id,
            relative_weight=rw,
            weight_source="user_defined",
        )
        child_ids.append(child.id)
        # Stamp per-edge weight metadata so the read path returns what
        # Stage 5 reports as q_typical (legacy node-level writes don't
        # always propagate to the edge in the same call). See the
        # established pattern in test_dual_unit_display.py.
        edge_row = db.fetchone(
            "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
            (parent.id, child.id),
        )
        if edge_row is None:
            edge = db.add_edge(parent.id, child.id, is_primary=True)
            edge_id = edge.id
        else:
            edge_id = edge_row["id"]
        db.execute(
            "UPDATE subject_edges SET relative_weight = ?, "
            "weight_source = 'user_defined' WHERE id = ?",
            (rw, edge_id),
        )
        db.conn.commit()

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("tree-editor")

    api_ready = wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.getEffectiveQuestionCounts === 'function')()"
    )
    assert api_ready, (
        "window.api.getEffectiveQuestionCounts is not exposed. "
        "Check that src/web/js/api/weights.js loaded via _loader.js."
    )

    # Sanity probe: confirm the bridge response carries the new
    # ``is_adaptive`` flag (Stage 8). This is a thin wiring check
    # that fails fast if the bridge or JS API didn't round-trip the
    # flag.
    bridge_probe = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                await window.api.ready();
                const rows = await window.api.getEffectiveQuestionCounts({exam.id});
                if (!Array.isArray(rows) || rows.length === 0) {{
                    return {{ok: false, error: 'empty rows'}};
                }}
                const adaptive = rows.every(r => r.is_adaptive === true);
                const floats = rows.filter(r =>
                    r.q_typical !== null && r.q_typical !== undefined
                    && !Number.isInteger(r.q_typical * 10)
                        ? true : (
                            r.q_typical !== null && r.q_typical !== undefined
                            && typeof r.q_typical === 'number'
                        )
                ).length;
                return {{
                    ok: true,
                    adaptive_on_every_row: adaptive,
                    row_count: rows.length,
                    sample_q: rows[0].q_typical,
                }};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert bridge_probe.get("ok"), (
        f"Bridge probe failed: {bridge_probe!r}"
    )
    assert bridge_probe.get("adaptive_on_every_row") is True, (
        f"Bridge did not stamp is_adaptive=True on every row: {bridge_probe!r}"
    )

    # Force the exam context and load the hierarchy. We do this via
    # eval_js rather than relying on the URL because the route
    # resolver intentionally doesn't pass query strings.
    load_result = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                await window.api.ready();
                window.TreeState.examContextId = {exam.id};
                await window.loadHierarchy();
                return {{ok: true}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert load_result.get("ok"), (
        f"loadHierarchy failed: {load_result!r}"
    )

    parent_chip_present = wimi_page.eval_js(
        f"!!document.querySelector('[data-testid=\"tree-node-weight-{parent.id}\"]')"
    )
    assert parent_chip_present, (
        f"Parent weight chip [data-testid=tree-node-weight-{parent.id}] "
        f"not found after loadHierarchy — the tree did not render."
    )

    chip_texts = wimi_page.eval_js(
        f"""
        (() => {{
            const ids = {child_ids};
            return ids.map(id => {{
                const el = document.querySelector(
                    `[data-testid="tree-node-weight-${{id}}"]`
                );
                return el ? el.textContent.trim() : null;
            }});
        }})()
        """
    )

    assert chip_texts is not None, "Could not read chip text from the tree"
    assert all(t is not None for t in chip_texts), (
        f"One or more child chips were not rendered: {chip_texts!r}"
    )

    # ---- Assert ------------------------------------------------------
    # Stage 8 contract: adaptive (CAT) chips include a float q value
    # AND the "(planning estimate)" qualifier so the user knows the
    # CAT exam has no fixed precision.
    for i, txt in enumerate(chip_texts):
        assert CHIP_ADAPTIVE_PATTERN.search(txt), (
            f"Child {i} chip text {txt!r} does not match the Stage 8 "
            f"adaptive-display pattern `~\\d+\\.\\d+ q \\(planning "
            f"estimate\\)`. The CAT formatting did not render — check "
            f"that ``enrichNodesWithQuestionCounts`` stamps "
            f"``node.is_adaptive`` and ``renderNode`` picks the "
            f"adaptive qLabel branch."
        )
