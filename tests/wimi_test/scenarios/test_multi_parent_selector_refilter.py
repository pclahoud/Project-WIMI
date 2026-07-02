"""Regression: subject deep-dive multi-parent selector triggers a
parent-context-aware refetch.

Stage 9 follow-up of
``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md`` /
``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``.

The deep-dive page renders a "Show as part of: {parent}" selector when
the subject has 2+ parent edges. Changing the selector must:

1. Call ``api.getSubjectDeepDive`` again with the new
   ``primaryParentId``.
2. Re-render every dependent section without errors (totals are still
   numeric after the refetch).

The pytest-only coverage in
``tests/database/test_primary_parent_context.py`` proves the *math*
(the lenient filter on the DB layer). This scenario proves the
*wiring* — that the selector → ``loadSubjectData({skipParentEdges:
true})`` → bridge → DB → re-render chain is intact.

Loader quirk note
-----------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because
``_loader.js`` aliases ``window._wimiApi`` → ``window.api`` then
deletes the source handle. CDP-click quirk: triggering the ``change``
event on a hidden-ish ``<select>`` is more reliable via direct
``.dispatchEvent`` than via ``locator.click()`` per
``feedback_cdp_click_quirks.md``.
"""
from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_multi_parent_selector_refilter_triggers_refetch(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Changing the selector causes a parent-context-aware refetch.

    Arrange
    -------
    Polyhierarchy: Hypertension under both Cardiovascular and
    Pregnancy. Tag two entries on Hypertension so the deep-dive page
    has data to render.

    Act
    ---
    1. Navigate to the subject deep-dive for Hypertension.
    2. Install a JS-side spy on ``api.getSubjectDeepDive`` that
       records every call's params.
    3. Change the selector to Cardiovascular via ``.value`` +
       ``dispatchEvent('change')``.

    Assert
    ------
    * The selector dropdown rendered (the page sees 2 parents).
    * After the change, the spy captured a call with
      ``primary_parent_id`` matching the Cardiovascular node id.
    * The page still renders ``totalMistakes`` as a numeric value
      (post-refetch render did not error).
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name="Stage 9 Followup Deep-Dive Refilter",
        exam_description="Regression — multi-parent selector wires through",
    )

    cardio = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="S9FU Cardiovascular",
        level_type="System",
        exam_weight_low=20,
        exam_weight_high=20,
        weight_source="user_defined",
    )
    preg = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="S9FU Pregnancy",
        level_type="System",
        exam_weight_low=15,
        exam_weight_high=15,
        weight_source="user_defined",
    )
    hyp = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="S9FU Hypertension",
        level_type="Topic",
        parent_id=cardio.id,  # legacy column populated by helper
        weight_source="user_defined",
    )

    # The create_subject_node_with_weight helper adds a primary
    # cardio → hyp edge. Add the second parent edge (preg → hyp)
    # so Hypertension is a 2-parent leaf and the selector renders.
    db.add_edge(preg.id, hyp.id, is_primary=False)

    # Provision a session + tag entries on Hypertension so the deep
    # dive has visible totals to assert against.
    session_row = db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = ?",
        (exam.exam_name,),
    )
    assert session_row is not None
    ec_id = session_row["id"]

    cursor = db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) "
        "VALUES (?, ?, DATE('now'), ?, ?, ?)",
        (db.user_id, "S9FU session", ec_id, 2, 2),
    )
    review_session_id = cursor.lastrowid

    for entry_order in (1, 2):
        c = db.execute(
            "INSERT INTO question_entries "
            "(review_session_id, entry_order, user_answer, correct_answer) "
            "VALUES (?, ?, ?, ?)",
            (review_session_id, entry_order, "A", "B"),
        )
        db.execute(
            "INSERT INTO entry_subject_mappings "
            "(question_entry_id, subject_node_id, mapping_type, primary_parent_id) "
            "VALUES (?, ?, 'primary', NULL)",
            (c.lastrowid, hyp.id),
        )
    db.conn.commit()

    # ---- Act ---------------------------------------------------------
    wimi_page.goto(
        "subject-deep-dive",
        query={"subject": hyp.id, "exam": ec_id},
    )

    # Sanity: the API wrapper is loaded with the Stage 9 follow-up
    # parameter name.
    api_ready = wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.getSubjectDeepDive === 'function')()"
    )
    assert api_ready, (
        "window.api.getSubjectDeepDive is not exposed. "
        "Check that src/web/js/api/analytics.js loaded via _loader.js."
    )

    # The page's init() races with our probe; give it a beat to finish
    # the initial load (parent edges + deep dive in parallel) and
    # render the selector. The settle wait is bounded — we re-probe
    # for the selector below as the real readiness signal.
    wimi_page.wait_for_timeout(500)

    selector_present = wimi_page.eval_js(
        "!!document.querySelector('[data-testid=\"multi-parent-selector-control\"]')"
    )
    assert selector_present, (
        "Multi-parent selector did not render. Hypertension has 2 "
        "parent edges (cardio, preg) so the selector should be visible. "
        "Check renderMultiParentSelector and loadParentEdges."
    )

    # Install a JS-side spy on the API wrapper. The spy records every
    # call's params (post-bridge serialization is opaque from the JS
    # side; recording the JS-API call args is the cleanest seam).
    spy_install = wimi_page.eval_js(
        """
        (() => {
            window._capturedDeepDiveCalls = [];
            const original = window.api.getSubjectDeepDive;
            window.api.getSubjectDeepDive = async function(params) {
                window._capturedDeepDiveCalls.push(
                    JSON.parse(JSON.stringify(params || {}))
                );
                return original.call(this, params);
            };
            return true;
        })()
        """
    )
    assert spy_install is True

    # Change the selector to the Cardiovascular parent. Use direct
    # ``.value`` + ``dispatchEvent`` because CDP-click on a hidden-ish
    # select doesn't always trigger ``change`` (the established
    # workaround from feedback_cdp_click_quirks.md).
    change_result = wimi_page.eval_js(
        f"""
        (() => {{
            const sel = document.querySelector(
                '[data-testid="multi-parent-selector-control"]'
            );
            if (!sel) return {{ok: false, error: 'selector not found'}};
            sel.value = '{cardio.id}';
            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
            return {{ok: true}};
        }})()
        """
    )
    assert change_result.get("ok"), (
        f"Could not dispatch change on the selector: {change_result!r}"
    )

    # The refetch is async; give it time to land and re-render.
    wimi_page.wait_for_timeout(500)

    # ---- Assert ------------------------------------------------------
    captured = wimi_page.eval_js("window._capturedDeepDiveCalls")
    assert isinstance(captured, list) and len(captured) >= 1, (
        f"Selector change did not trigger api.getSubjectDeepDive. "
        f"Captured calls: {captured!r}. Check loadSubjectData wiring "
        f"on the change handler."
    )

    # The most recent captured call must carry primaryParentId pointing
    # at the chosen Cardiovascular node.
    last_call: Any = captured[-1]
    assert isinstance(last_call, dict), (
        f"Captured call payload was not an object: {last_call!r}"
    )
    assert last_call.get("primaryParentId") == cardio.id, (
        f"Refetch did not include the chosen parent id. "
        f"Expected primaryParentId={cardio.id}, got call={last_call!r}. "
        f"Check the change handler passes this.activeParentId through."
    )

    # The page must still render — totals are visible as a numeric value
    # post-refetch (the render path didn't throw).
    total_text = wimi_page.eval_js(
        "(() => { const el = document.getElementById('totalMistakes'); "
        "return el ? el.textContent.trim() : null; })()"
    )
    assert total_text is not None and total_text.lstrip("-").isdigit(), (
        f"totalMistakes is missing or non-numeric after refetch: "
        f"{total_text!r}. The page did not re-render cleanly."
    )

    # Stage 9 polish — breadcrumb reflects the chosen parent context.
    # When primary_parent_id=cardio.id, the path should route through
    # cardio (not preg). The backend stitches "S9FU Cardiovascular >
    # ... > Stage 3 Hypertension"; we just assert cardio's name appears
    # and preg's name does not.
    path_text = wimi_page.eval_js(
        "(() => { const el = document.getElementById('fullPath'); "
        "return el ? el.textContent.trim() : null; })()"
    )
    assert path_text and "S9FU Cardiovascular" in path_text, (
        f"Breadcrumb did not switch to the cardio path after the "
        f"selector change. Got {path_text!r}. Check that the bridge "
        f"returns path_via_parent and renderInfoAndTrend prefers it."
    )
    assert "S9FU Pregnancy" not in path_text, (
        f"Breadcrumb still mentions Pregnancy after filtering to "
        f"Cardiovascular. Got {path_text!r}. path_via_parent should "
        f"only contain the chosen parent's chain."
    )

    # Stage 9 polish — explanatory banner names the chosen parent.
    banner_text = wimi_page.eval_js(
        "(() => { const el = document.querySelector("
        "'[data-testid=\"multi-parent-selector-banner\"]'); "
        "return el ? el.textContent.trim() : null; })()"
    )
    assert banner_text is not None, (
        "Banner element [data-testid=multi-parent-selector-banner] "
        "did not render. Check _buildSelectorBanner."
    )
    assert "S9FU Cardiovascular" in banner_text, (
        f"Banner does not name the active parent. Got {banner_text!r}."
    )
    assert "Viewing entries that route through" in banner_text, (
        f"Banner copy missing the 'route through' phrase: {banner_text!r}."
    )
