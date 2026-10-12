"""Regression: the weight editor's action row fits inside the details panel (#348).

``.weight-actions-enhanced`` was ``display: flex`` with no wrap, holding
Reset, Rebalance siblings and Apply Changes at ``flex: 1``. ``flex: 1`` cannot
shrink an item below its min-content width (``min-width: auto``), and the
three min-contents plus two gaps exceed the panel's column, so the row
overflowed: on Windows machine A (Segoe UI) Apply Changes ended at x=1409.9
against a visible panel edge of 1366, and the panel scrolled sideways by
43 px to reach the one button that commits a weight edit.

Button widths are text widths, and Inter is in the font stack but not
shipped, so the overflow is platform-dependent (#348's caveat). The assertion
is that no action ends past the panel's visible right edge -- true whatever
the font -- rather than any particular width.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import (
    clear_viewport, open_tree_editor, seed_step1_roots, select_subject,
    set_viewport)

MEASURE = """
(() => {
  const p = document.getElementById('details-panel');
  const edge = p.getBoundingClientRect().left + p.clientLeft + p.clientWidth;
  const row = document.querySelector('.weight-actions-enhanced');
  return {
    edge,
    hOverflow: p.scrollWidth - p.clientWidth,
    buttons: [...row.querySelectorAll('button')].map(b => ({
      text: b.textContent.trim(),
      right: b.getBoundingClientRect().right,
    })),
  };
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_every_weight_action_is_inside_the_panel(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    seeded = seed_step1_roots(wimi_session.user.db, "W348 Actions")
    set_viewport(wimi_page, 1400, 820)
    try:
        open_tree_editor(wimi_page, seeded["exam"].id)
        select_subject(wimi_page, seeded["child"])
        m = wimi_page.eval_js(MEASURE)
    finally:
        clear_viewport(wimi_page)

    assert [b["text"] for b in m["buttons"]] == [
        "Reset", "Rebalance siblings", "Apply Changes"], (
        f"The action row changed shape; re-check what this test measures: {m!r}")
    outside = [b for b in m["buttons"] if b["right"] > m["edge"] + 0.5]
    assert not outside, (
        f"{[b['text'] for b in outside]} end past the panel's visible right "
        f"edge ({m['edge']:.1f}): {outside!r}. The row is not wrapping (#348).")
    assert m["hOverflow"] <= 0, (
        f"The details panel scrolls sideways by {m['hOverflow']} px.")
