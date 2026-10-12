"""Shared arrange/act for the tree editor's details-panel scenarios.

#341, #342, #343, #345, #347 and #348 were all measured against
``scripts/build_demo_profile.py``'s profile: eleven Systems roots carrying the
real 2025 Step 1 published ranges, ``relative_weight`` NULL. ``seed_step1_roots``
reproduces the part of that profile those issues depend on, and nothing else.

Geometry defects are conditional on the viewport -- #341 needs an overview
taller than the panel, #342 only exists below the 900 px breakpoint -- so the
scenarios drive the viewport through CDP rather than trusting whatever size the
harness window opened at. ``set_viewport`` checks that the override took and
fails hard otherwise, because a geometry assertion at the wrong size passes or
fails for reasons that have nothing to do with the fix.
"""

from __future__ import annotations

from typing import Any

from wimi_test.page import WimiPage

# (name, low, high): the 2025 USMLE Step 1 Systems ranges the demo profile
# uses. Sum of lows 61, sum of highs 100 -- #347's numbers.
STEP1_SYSTEMS = (
    ("Blood & Lymphoreticular/Immune Systems", 7, 11),
    ("Behavioral Health & Nervous System", 9, 13),
    ("Cardiovascular System", 9, 13),
    ("Respiratory & Renal/Urinary Systems", 6, 10),
    ("Gastrointestinal System", 6, 10),
    ("Reproductive & Endocrine Systems", 5, 9),
    ("Multisystem Processes & Disorders", 4, 8),
    ("Musculoskeletal, Skin & Subcutaneous Tissue", 4, 8),
    ("Human Development", 6, 9),
    ("Biostatistics & Epidemiology", 4, 6),
    ("Social Sciences", 1, 3),
)


def seed_step1_roots(db, exam_name: str) -> dict[str, Any]:
    """Create the exam, its eleven banded roots and one child to select.

    Returns ``{"exam": exam, "roots": [ids], "child": id}``.
    """
    exam = db.create_exam_context(exam_name=exam_name, exam_description="")
    roots = [
        db.create_subject_node(
            exam_context=exam.exam_name, name=name, level_type="System",
            exam_weight_low=float(low), exam_weight_high=float(high),
            sort_order=i + 1,
        ).id
        for i, (name, low, high) in enumerate(STEP1_SYSTEMS)
    ]
    child = db.create_subject_node(
        exam_context=exam.exam_name, name="Anemias", level_type="Topic",
        parent_id=roots[0],
    ).id
    return {"exam": exam, "roots": roots, "child": child}


def set_viewport(page: WimiPage, width: int, height: int) -> None:
    """Emulate a ``width`` x ``height`` CSS-pixel viewport, and prove it took."""
    page.tab._tab.Emulation.setDeviceMetricsOverride(
        width=width, height=height, deviceScaleFactor=1, mobile=False)
    got = None
    for _ in range(20):
        got = page.eval_js("[innerWidth, innerHeight]")
        if got == [width, height]:
            return
        page.wait_for_timeout(100)
    raise AssertionError(
        f"Emulation.setDeviceMetricsOverride did not take: asked for "
        f"{width}x{height}, the page reports {got}. Every geometry assertion "
        "after this would be measured at the wrong size.")


def clear_viewport(page: WimiPage) -> None:
    page.tab._tab.Emulation.clearDeviceMetricsOverride()


def open_tree_editor(page: WimiPage, exam_id: int) -> None:
    """Navigate and wait until the gate has released and the overview drew."""
    page.goto("tree-editor", query={"exam_id": exam_id})
    wait_for(page, "document.querySelectorAll('[data-page-gated][inert]')"
                   ".length === 0 && !!document.querySelector('.exam-overview')",
             what="the tree editor to release its gate and draw the overview")


def select_subject(page: WimiPage, node_id: int) -> None:
    page.eval_js(f"selectNode({node_id})")
    wait_for(page, "(() => { const c = document.getElementById("
                   "'details-content'); return !!c && !c.classList.contains("
                   "'hidden') && !!document.querySelector("
                   "'.weight-actions-enhanced'); })()",
             what="the subject's details and weight editor to render")
    # Let `.btn { transition: all }` and friends settle before measuring.
    page.wait_for_timeout(400)


def wait_for(page: WimiPage, expr: str, *, what: str,
             timeout_ms: int = 10000) -> Any:
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        last = page.eval_js(expr)
        if last:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    raise AssertionError(f"Timed out waiting for {what}; last value {last!r}")
