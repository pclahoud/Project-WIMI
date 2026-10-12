"""Regression: the Exam Overview starts at the top of the details panel (#341).

The overview was written into ``#details-placeholder``, a flex column with
``justify-content: center`` built for a graphic and two lines. Once the
overview is taller than the panel, centring pushes its overflow out of BOTH
ends of the scroll box, and the top end cannot be scrolled to: the heading and
all three figures sat above ``scrollTop: 0`` (205.9 px on Linux, 298.4 px on
Windows machine A at 1400x900). ``align-items: center`` also took the overview
off ``stretch``, so it laid out at max-content and overflowed sideways.

Asserted as *visible*, not as present: the heading was in the DOM, in the
accessibility tree and correctly levelled the whole time, so every existence
check passed against the broken page. The precondition -- overview taller
than the panel -- is asserted too, because at a size where it fits the
centring is harmless and this test could not fail.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import (
    clear_viewport, open_tree_editor, seed_step1_roots, set_viewport)

MEASURE = """
(() => {
  const p = document.getElementById('details-panel');
  const h = document.querySelector('.overview-title');
  const ov = document.querySelector('.exam-overview');
  const vis = () => {
    const pr = p.getBoundingClientRect(), b = h.getBoundingClientRect();
    return b.top >= pr.top - 0.5 && b.bottom <= pr.top + p.clientHeight + 0.5;
  };
  p.scrollTop = 0;
  const atTop = vis();
  const contentTop = ov.getBoundingClientRect().top - p.getBoundingClientRect().top;
  return {
    overviewH: ov.getBoundingClientRect().height, panelH: p.clientHeight,
    headingVisibleAtTop: atTop, contentTop,
    hOverflow: p.scrollWidth - p.clientWidth,
  };
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_the_overview_heading_is_visible_with_the_panel_scrolled_to_the_top(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    seeded = seed_step1_roots(wimi_session.user.db, "W341 Overview")
    set_viewport(wimi_page, 1400, 820)
    try:
        open_tree_editor(wimi_page, seeded["exam"].id)
        m = wimi_page.eval_js(MEASURE)
    finally:
        clear_viewport(wimi_page)

    assert m["overviewH"] > m["panelH"], (
        f"Precondition: the overview ({m['overviewH']:.1f} px) must be taller "
        f"than the panel ({m['panelH']} px), or centring clips nothing and "
        "this test cannot fail.")
    assert m["contentTop"] >= 0, (
        f"The overview starts {-m['contentTop']:.1f} px ABOVE the panel's "
        "top edge, where no scroll position reaches it (#341).")
    assert m["headingVisibleAtTop"], (
        "'Exam Overview' is not visible with the panel scrolled to the top. "
        f"Measured {m!r}.")
    assert m["hOverflow"] <= 0, (
        f"The panel scrolls sideways by {m['hOverflow']} px: the overview is "
        "laying out wider than the panel (#341's horizontal half).")
