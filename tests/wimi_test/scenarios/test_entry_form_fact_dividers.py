"""Every row of the entry form's facts block keeps its divider (#430, #620 #26).

The dividers are drawn by `.fact-row + .fact-row`, an adjacent-sibling rule.
The tour wraps the two subject rows in `.fact-row-group` so it can point at
the pair, and a wrapper breaks that adjacency: without entry.css's restated
rule, Primary Subject(s) and Tags each lose the line above them while every
token and every other row is unchanged.

Measured when the wrapper landed: the block's screenshot identical to the
pre-wrapper page, 0 of 331,428 pixels; with the restated rule removed, 17,012
pixels differ, from the Primary row's divider down. A divider is a painted
line, so this reads the computed border where it is drawn, on the row or on
the group the row opens.
"""
from __future__ import annotations

import pytest

from _helpers.w114_form_ready import seed_session_with_draft, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

DIVIDERS = """(() => {
  const rows = [...document.querySelectorAll('.entry-facts .fact-row')];
  const line = el => {
    const cs = getComputedStyle(el);
    return cs.borderTopStyle !== 'none' && parseFloat(cs.borderTopWidth) >= 1;
  };
  return rows.map((row, i) => {
    const group = row.parentElement.classList.contains('fact-row-group')
        && row === row.parentElement.firstElementChild ? row.parentElement : null;
    const label = row.querySelector('.fact-label');
    return {label: label ? label.textContent.replace(/\\s+/g, ' ').trim() : '?',
            first: i === 0, drawn: line(row) || (!!group && line(group))};
  });
})()"""


@pytest.mark.slow
@pytest.mark.regression
def test_every_fact_row_after_the_first_has_a_divider_above_it(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    session_id, _ = seed_session_with_draft(wimi_session.user.db, name="Fact dividers")
    wimi_page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(wimi_page)

    rows = wimi_page.eval_js(DIVIDERS)
    labels = [r["label"] for r in rows]
    # The found-them control: the two wrapped rows and the one after them.
    assert any(l.startswith("Primary Subject(s)") for l in labels), labels
    assert "Tags" in labels, labels
    assert wimi_page.eval_js(
        "document.querySelectorAll('.entry-facts .fact-row-group > .fact-row').length") == 2

    missing = [r["label"] for r in rows if not r["first"] and not r["drawn"]]
    assert not missing, f"no divider drawn above: {missing}"
    assert not rows[0]["drawn"], "the first row should have no line above it"
