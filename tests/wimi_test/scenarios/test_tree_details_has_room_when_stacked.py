"""Regression: below the 900 px breakpoint the details panel has a usable body (#342).

Below 900 px the tree and the details panel stack. The page is a fixed 100vh
frame, and the header, dimension bar and wrapped toolbar above the panes took
most of it, so the two panes split what was left: at an 860x700 window the
details panel got 91 px of client height under a 106.5 px sticky header -- a
body of -15.5 px, measured on Windows machine A. Scrolling could not help,
because the header is sticky. ``max-height: 50vh`` was in the media query and
never the binding constraint.

844x618 is that window's inner size. The long-name case is asserted
separately because a 134-character name grows the sticky header (#342
measured 131.5 px of header and 0.5 px of body on Linux).
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import (
    clear_viewport, open_tree_editor, seed_step1_roots, select_subject,
    set_viewport)

LONG_NAME = (
    "Disorders of the hematopoietic and lymphoreticular systems presenting "
    "with anemia, cytopenias and abnormal hemostasis in any age group"
)

# Enough body under the header to hold a field and its label, at the least.
MIN_BODY_PX = 200

MEASURE = """
(() => {
  const p = document.getElementById('details-panel');
  const h = document.querySelector('.details-panel-header');
  return {
    breakpoint: matchMedia('(max-width: 900px)').matches,
    panel: p.clientHeight,
    header: h.getBoundingClientRect().height,
    body: p.clientHeight - h.getBoundingClientRect().height,
  };
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_the_stacked_details_panel_shows_its_body(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    seeded = seed_step1_roots(db, "W342 Stacked")
    assert len(LONG_NAME) == 134
    long_child = db.create_subject_node(
        exam_context=seeded["exam"].exam_name, name=LONG_NAME,
        level_type="Topic", parent_id=seeded["roots"][1]).id

    set_viewport(wimi_page, 844, 618)
    try:
        open_tree_editor(wimi_page, seeded["exam"].id)
        select_subject(wimi_page, seeded["child"])
        normal = wimi_page.eval_js(MEASURE)
        select_subject(wimi_page, long_child)
        long = wimi_page.eval_js(MEASURE)
    finally:
        clear_viewport(wimi_page)

    assert normal["breakpoint"], "Precondition: the stacked layout is active."
    assert long["header"] > normal["header"], (
        f"Precondition: the long name grows the header ({normal!r}, {long!r}).")
    for label, m in (("a short name", normal), ("a 134-character name", long)):
        assert m["body"] >= MIN_BODY_PX, (
            f"With {label} the details panel is {m['panel']} px tall and its "
            f"sticky header {m['header']:.1f} px, leaving {m['body']:.1f} px "
            f"of body; at least {MIN_BODY_PX} expected (#342).")
