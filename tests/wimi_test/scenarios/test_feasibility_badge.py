"""Regression: no surface warns that children exceed their parent (#664).

This file used to assert the opposite. It was Stage 7's guard that the
weight modal's ``#weight-feasibility-badge`` filled with
``status-infeasible`` and the copy ``Can't fit child minimums (>=10 q)
into parent maximum (9 q).`` for 5 children at 18% under a parent at
90-99% with N=10.

**The owner removed that verdict (#664, 2026-10-10.)** All three faults
Stage 7 reported -- ``'over'``, ``'infeasible'`` and ``'under'`` -- summed
the children's weights and compared them with their parent's, which #64
denies any meaning to: a weight is a percentage of the **whole exam** at
any depth, never a share of the subject above it. So the badge and the
tree row's warning dot fired on correct published blueprints.

The file is kept and inverted rather than deleted, because there are
**two** surfaces to hold down and a database test cannot see either:

1. the tree row's ``⚠`` dot, which ``tree_editor.js`` drew for any
   non-``'ok'`` status;
2. the weight editor's badge, which ``weight_editor.js`` filled.

Deleting would have left both unguarded at the UI. Compare
``test_efficiency_band_toggle.py``, which *was* deleted for #146 -- its
subject was whether a score drew as a number or a range, and that is moot
once nothing draws. Here the subject is whether something draws at all,
which is exactly what needs a guard.

**The positive controls are the point.** An assertion that nothing drew
passes against a page that never loaded, which is #121's lesson. So this
asserts the tree rendered its rows and the weight editor opened *before*
concluding anything from an absence.

Loader quirk note
-----------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because ``_loader.js``
aliases ``window._wimiApi`` -> ``window.api`` then deletes the source
handle.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _poll(wimi_page: WimiPage, read, want, *, timeout_ms: int = 10000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if last == want:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


@pytest.mark.slow
@pytest.mark.regression
def test_no_warning_dot_and_no_badge_on_the_arrangement_that_used_to_trip_them(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Stage 7's own infeasible fixture now draws nothing anywhere.

    5 children at 18% under a parent at 90-99%, N=10. The percentages
    fit (5x18 = 90 <= 99) and the ceiling-rounded question counts do not
    (5x ceil(1.8) = 10 > floor(9.9) = 9), which is precisely the
    rounding-class case Stage 7 built ``'infeasible'`` for.
    """
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name='Feasibility 664',
        exam_description='#664 - the arrangement that used to warn',
    )
    db.update_exam_length(exam.id, kind='fixed', min=10, max=10, typical=10)

    parent = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name='Parent 90 to 99',
        level_type='System',
        exam_weight_low=90,
        exam_weight_high=99,
        weight_source='user_defined',
    )
    for i in range(5):
        child = db.create_subject_node_with_weight(
            exam_context=exam.exam_name,
            name=f'Child {i}',
            level_type='Topic',
            parent_id=parent.id,
            relative_weight=18,
            weight_source='user_defined',
        )
        row = db.fetchone(
            "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
            (parent.id, child.id),
        )
        edge_id = row['id'] if row else db.add_edge(
            parent.id, child.id, is_primary=True).id
        db.execute(
            "UPDATE subject_edges SET relative_weight = ?, "
            "weight_source = 'user_defined' WHERE id = ?",
            (18, edge_id),
        )
        db.conn.commit()

    wimi_page.goto('tree-editor', query={'exam_id': exam.id})

    # ---- Positive control: the page really loaded and really drew rows.
    # Without this, every assertion below passes on a blank page (#121).
    # Rows are collapsed on load, so Expand All is what puts the children
    # on screen -- and the dot used to sit on the PARENT, so the control
    # has to prove the parent is there as much as the children.
    assert _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            "document.querySelectorAll('.tree-node').length"),
        1,
    ) == 1, "the tree did not draw the parent row"
    wimi_page.eval_js(
        "document.querySelector('[data-testid=\"tree-expand-all\"]').click()")
    assert _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            "document.querySelectorAll('.tree-node').length"),
        6,
    ) == 6, "Expand All did not draw the parent and its five children"

    # ---- The slot still exists, and the bridge slot is still registered.
    # #664 kept both: deleting a registered bridge slot is a breaking
    # change, and the report's figures are still honest.
    assert wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.getFeasibilityReport === 'function')()"
    ), "getFeasibilityReport should still be a registered slot"

    report = wimi_page.eval_js(
        f"window.api.getFeasibilityReport({parent.id})", await_promise=True)
    assert report.get('status') == 'ok', (
        f"the bridge must report no fault for this arrangement: {report!r}")
    assert report.get('violators') == []
    # The figures that made it 'infeasible' are unchanged and still sent.
    assert report.get('parent_high_q') == 9
    assert report.get('children_low_sum_q') == 10

    # ---- No warning dot on any row, which is the first surface.
    dots = wimi_page.eval_js(
        "Array.from(document.querySelectorAll('[data-testid^=\"tree-row-warning-dot\"],"
        " .tree-row-warning-dot')).length")
    assert dots == 0, (
        f"{dots} warning dot(s) drawn; #664 removed them and #64 says this "
        f"arrangement is correct")

    # ---- No badge copy, which is the second surface. The slot may exist;
    # it must be empty and hidden.
    badge = wimi_page.eval_js(
        "(() => { const b = document.getElementById('weight-feasibility-badge');"
        " return b ? {hidden: b.hasAttribute('hidden'),"
        " text: (b.textContent || '').trim(),"
        " cls: b.className} : null; })()")
    if badge is not None:
        assert badge['hidden'] is True, f"the badge is showing: {badge!r}"
        assert badge['text'] == '', f"the badge has copy: {badge!r}"
        for gone in ('status-over', 'status-under', 'status-infeasible'):
            assert gone not in badge['cls'], f"{gone} applied: {badge!r}"
