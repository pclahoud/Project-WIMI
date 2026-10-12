"""Regression: a selected subject has a way back to the Exam Overview (#343).

Selecting a subject was a one-way door. Re-clicking the selected row toggles
its expansion, Escape did nothing, and no control on the page matched
overview / deselect / clear; the only routes back were switching dimension,
deleting the subject, or F5. On a single-dimension exam two of those three do
not exist. Separately, ``showExamOverview()`` wrote the overview into
``#details-placeholder`` with ``innerHTML``, destroying the "No subject
selected" markup within a few hundred milliseconds of load.

The way back is pressed with a real, hit-tested click (``locator.click``), not
``el.click()`` or a call to the handler: the defect was that nothing pressable
existed, and only real input can tell a pressable control from a handler.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import (
    open_tree_editor, seed_step1_roots, select_subject, wait_for)

STATE = """
(() => {
  const shown = id => { const e = document.getElementById(id);
                        return !!e && !e.classList.contains('hidden'); };
  const a = document.activeElement;
  return {
    overview: shown('details-overview'),
    details: shown('details-content'),
    selectedRows: document.querySelectorAll('.tree-node.selected').length,
    placeholderTitle: !!document.querySelector('.details-placeholder-title'),
    focus: a ? (a.className || a.tagName) : null,
  };
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_back_to_overview_returns_from_a_selected_subject(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    seeded = seed_step1_roots(wimi_session.user.db, "W343 Way back")
    open_tree_editor(wimi_page, seeded["exam"].id)
    select_subject(wimi_page, seeded["child"])

    before = wimi_page.eval_js(STATE)
    assert before["details"] and not before["overview"], (
        f"Precondition: a subject is selected and its details shown: {before!r}")

    wimi_page.locator(testid="tree-show-overview").click()
    after = wait_for(
        wimi_page,
        f"(() => {{ const s = {STATE.strip()}; return s.overview ? s : null; }})()",
        what="the Exam Overview to come back after pressing 'Back to overview'")

    assert not after["details"], f"The subject's details are still shown: {after!r}"
    assert after["selectedRows"] == 0, (
        f"{after['selectedRows']} tree row(s) still marked selected after "
        "returning to the overview.")
    assert "overview-title" in (after["focus"] or ""), (
        f"Focus is on {after['focus']!r}. The button pressed lives in the "
        "header that just hid, so focus must be moved to the overview's "
        "heading or it falls to <body>.")
    assert after["placeholderTitle"], (
        "'.details-placeholder-title' is gone: the overview was written over "
        "the placeholder's markup again (#343).")
