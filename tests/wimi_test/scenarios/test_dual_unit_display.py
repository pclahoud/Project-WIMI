"""Regression: tree-editor chips render the Stage 5 dual unit display.

Stage 5 of ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.

When the exam declares a ``length_typical`` (i.e.
``length_kind in ('fixed','range')``), the tree-editor weight chips
should render ``XX.X% • ~N q`` next to each subject. When the exam is
``length_kind='unknown'`` (no planning baseline), chips must degrade
to a pure ``XX.X%`` display per the design doc §7.5 contract.

The pytest-only coverage in
``tests/database/test_question_allocation_bridge.py`` and
``tests/app/test_bridge_edges.py`` proves the *math* and *bridge
shape*; this scenario proves the *wiring* — that the tree editor
actually fetches the per-edge counts and renders the dual display.

Markers / fixtures
------------------

* ``@pytest.mark.slow`` — spawns a real WIMI subprocess.
* ``@pytest.mark.regression`` — registered in ``pytest.ini`` so
  collection emits no warning.
* Fixtures: ``wimi_session``, ``wimi_page``. The exam context and the
  subject hierarchy are seeded directly through the DB so the
  scenario does not walk the wizard's create-exam flow.

Loader quirk note
-----------------

The JS API is loaded under ``window._wimiApi`` and then aliased to
``window.api`` by ``_loader.js`` (the ``_wimiApi`` handle is deleted
after the alias). Probes therefore use ``window.api``, NOT
``window._wimiApi`` — see ``test_weight_no_silent_rebalance.py`` for
the precedent established under Stage 2.
"""
from __future__ import annotations

import re
from typing import Any, List

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


CHIP_DUAL_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*%\s*•\s*~\d+(?:\.\d+)?\s*q")
CHIP_PCT_ONLY_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*%(?!\s*•)")


@pytest.mark.slow
@pytest.mark.regression
def test_tree_chip_dual_unit_display(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Tree-editor chips show ``XX.X% • ~N q`` when length_typical is set,
    and fall back to ``XX.X%`` when length_kind='unknown'.

    Arrange
    -------
    Seed an exam with ``length_kind='fixed'`` and ``length_typical=280``
    (USMLE Step 1). Add one System at 100% range with three children
    weighted 30/30/40. We use direct DB writes so the scenario tests
    the *render path*, not the create path.

    Act
    ---
    1. Navigate to the tree editor.
    2. Wait for the hierarchy to load.
    3. Read the chip text for the three child rows via the
       ``data-testid`` attribute the renderer assigns each row.

    Assert
    ------
    * Each chip's text matches ``\\d+\\.\\d+% • ~\\d+ q``.
    * After flipping the exam to ``length_kind='unknown'`` and
      reloading, the same chips match ``\\d+\\.\\d+%`` (no ``• ~N q``
      suffix).
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name="Stage 5 Dual Unit Display",
        exam_description="Regression for Stage 5 dual chip display",
    )
    db.update_exam_length(
        exam.id, kind="fixed", min=280, max=280, typical=280,
    )

    # Parent System at 100% so the three children inherit the full
    # exam budget (280 questions split 30/30/40 → 84/84/112).
    parent = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="Stage 5 Sys",
        level_type="System",
        exam_weight_low=100,
        exam_weight_high=100,
        weight_source="user_defined",
    )

    children_data = [
        ("Stage 5 ChildA", 30.0),
        ("Stage 5 ChildB", 30.0),
        ("Stage 5 ChildC", 40.0),
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
        # Stamp the per-edge weight metadata so the read path returns
        # what Stage 5 reports as q_typical (legacy node-level
        # writes don't always propagate to the edge in the same call).
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

    # ---- Act ---------------------------------------------------------
    # The tree editor's ``initializeTreeEditor`` reads ``?exam_id=<id>``
    # from URL params. The wimi_test route resolver doesn't pass query
    # strings, so we navigate to the bare route and then force the
    # ``TreeState.examContextId`` manually before calling loadHierarchy.
    wimi_page.goto("tree-editor")

    api_ready = wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.getEffectiveQuestionCounts === 'function')()"
    )
    assert api_ready, (
        "window.api.getEffectiveQuestionCounts is not exposed. "
        "Check that src/web/js/api/weights.js loaded via _loader.js."
    )

    # Force the exam context and load the hierarchy. We do this via
    # eval_js rather than relying on the URL because the route
    # resolver intentionally doesn't pass query strings (see
    # ``wimi_test/routes.py``) — the established pattern for
    # tree-editor scenarios is to drive the state via the API.
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

    # Confirm the parent's chip is rendered. ``loadHierarchy``
    # awaited above so the synchronous DOM should be settled.
    parent_chip_present = wimi_page.eval_js(
        f"!!document.querySelector('[data-testid=\"tree-node-weight-{parent.id}\"]')"
    )
    assert parent_chip_present, (
        f"Parent weight chip [data-testid=tree-node-weight-{parent.id}] "
        f"not found after loadHierarchy — the tree did not render."
    )

    # Read the chip text for all three children. The parent renders
    # its children directly into ``tree-node-children-{parent.id}``,
    # so the child weight chips are in the DOM even when the parent
    # row is visually "collapsed" (CSS hides the children-container,
    # but doesn't remove them).
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

    # Stage 5 contract: chip text matches `XX.X% • ~N q` when
    # length_kind != 'unknown'.
    for i, txt in enumerate(chip_texts):
        assert CHIP_DUAL_PATTERN.search(txt), (
            f"Child {i} chip text {txt!r} does not match the Stage 5 "
            f"dual-display pattern `\\d+\\.\\d+% • ~\\d+ q`. "
            f"The dual-display did not render."
        )

    # ---- Act 2: flip exam to length_kind='unknown' and reload -------
    wimi_page.eval_js(
        f"""
        (async () => {{
            await window.api.updateExamLength({{
                examContextId: {exam.id},
                kind: 'unknown',
                min: null, max: null, typical: null,
                note: null,
            }});
        }})()
        """,
        await_promise=True,
    )

    # Reload the tree so it picks up the new length_kind.
    chip_texts_unknown = wimi_page.eval_js(
        f"""
        (async () => {{
            const ids = {child_ids};
            try {{ await window.loadHierarchy(); }} catch (e) {{}}
            return ids.map(id => {{
                const el = document.querySelector(
                    `[data-testid="tree-node-weight-${{id}}"]`
                );
                return el ? el.textContent.trim() : null;
            }});
        }})()
        """,
        await_promise=True,
    )

    assert chip_texts_unknown is not None
    assert all(t is not None for t in chip_texts_unknown), (
        f"One or more child chips were not rendered after length flip: "
        f"{chip_texts_unknown!r}"
    )

    # Stage 5 degradation contract: length_kind='unknown' means no
    # ``• ~N q`` suffix — the chip should be percentage-only.
    for i, txt in enumerate(chip_texts_unknown):
        assert "•" not in txt and "~" not in txt and " q" not in txt, (
            f"Child {i} chip text {txt!r} still carries the dual-unit "
            f"suffix after the exam was flipped to length_kind='unknown'. "
            f"The degradation contract is violated."
        )
        # Sanity: there is still a percentage in the chip.
        assert "%" in txt, (
            f"Child {i} chip text {txt!r} has no percentage at all — "
            f"the chip rendering broke entirely."
        )
