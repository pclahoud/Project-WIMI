"""Regression: the tree editor reports a weight band as a band (#347, #346).

Every root of the Step 1 demo stores its published range
(``exam_weight_low``/``exam_weight_high``) with ``relative_weight`` NULL, and
every figure in the editor read ``node.weight || node.exam_weight_low``. So
eleven roots publishing 61-100% were totalled "Root Total: 61.0%" in the
toolbar and "Total Weight 61.0%" in the Exam Overview, and each legend row
showed its low bound ("7.0%") beside a tree chip reading "7-11%". A student
reads 61% as "39% of the exam is missing from my outline" when the blueprint
is fully covered.

The text and number half shipped in #352 and stopped at the donut on
purpose, which left the overview stating **both** readings at once: a
"61-100%" stat tile directly above a ring whose centre said "61%". #346's
range-bar list removed the ring, and the last assertion here is the one that
closes that: no figure in the overview is the low-bound artefact any more.

The three-box stat row went with it (the owner's decision: a tile can only
hold a scalar, and "61-100%" wrapped over two lines inside a 103 px box).
Its sentence is checked here rather than in the geometry scenario because it
is a *figure*, which is what this file is about.
"""

from __future__ import annotations

import re

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import (
    STEP1_SYSTEMS, open_tree_editor, seed_step1_roots, select_subject)

# Null-safe on purpose: run against the donut this reports "the sentence is
# missing" and "the overview still says 61%", which is the finding. A `.`
# straight onto a missing element would throw instead, and a scenario whose
# pre-fix failure is a JS error proves only that the selector changed.
READ = """
(() => {
  const text = sel => [...document.querySelectorAll(sel)]
      .map(e => e.textContent.trim().replace(/\\s+/g, ' '));
  const one = sel => {
    const e = document.querySelector(sel);
    return e ? e.textContent.trim().replace(/\\s+/g, ' ') : null;
  };
  const ov = document.querySelector('.exam-overview');
  return {
    toolbar: one('#total-weight'),
    summary: one('.overview-summary'),
    total: one('.weight-range-total'),
    values: text('.weight-range-value'),
    overviewText: ov ? (ov.innerText || '').replace(/\\s+/g, ' ') : '',
  };
})()
"""

# "61%" or "61.0%" standing alone -- the low-bound artefact. `61-100%` does
# not match, because what follows the 61 there is an en dash.
LOW_BOUND_ARTEFACT = re.compile(r"(?<!\d)61(\.0)?\s*%")


@pytest.mark.slow
@pytest.mark.regression
def test_root_totals_rows_and_children_show_the_published_band(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    seeded = seed_step1_roots(db, "W347 Bands")
    banded_child = db.create_subject_node(
        exam_context=seeded["exam"].exam_name, name="Hemostasis",
        level_type="Topic", parent_id=seeded["roots"][0],
        exam_weight_low=2.0, exam_weight_high=4.0).id
    assert banded_child

    open_tree_editor(wimi_page, seeded["exam"].id)
    seen = wimi_page.eval_js(READ)

    # Read the artefact first: on `master` the overview's donut printed "61%"
    # in its centre one section below a stat tile reading "61-100%", and that
    # live contradiction is the thing #346 was asked to close.
    artefact = LOW_BOUND_ARTEFACT.search(seen["overviewText"])
    assert artefact is None, (
        f"The Exam Overview still prints a bare {artefact.group(0)!r}: "
        f"{seen['overviewText'][:300]!r}. 61 is the sum of the low bounds "
        f"and no part of the page should state it as a quantity of its own "
        f"(#347).")

    assert seen["toolbar"] == "Root Total: 61–100%", (
        f"The toolbar reads {seen['toolbar']!r}. The eleven roots publish "
        "lows summing to 61 and highs to 100; showing 61 alone is the low "
        "bound standing in for the band (#347).")
    assert seen["total"] == (
        "Published ranges total 61–100% of the exam."), (
        f"The overview's closing sentence reads {seen['total']!r}. It "
        "replaced a 'Total Weight' tile that could only hold a scalar.")
    assert seen["summary"] == "13 subjects across 11 roots.", seen["summary"]
    assert seen["values"][:3] == ["7–11%", "9–13%", "9–13%"], seen["values"]
    assert len(seen["values"]) == len(STEP1_SYSTEMS), seen["values"]

    select_subject(wimi_page, seeded["roots"][0])
    children = wimi_page.eval_js(
        "[...document.querySelectorAll('#children-list .child-item')].map(e =>"
        " [e.querySelector('.child-name').textContent.trim(),"
        "  e.querySelector('.child-weight').textContent.trim()])")
    assert ["Hemostasis", "2–4%"] in children, (
        f"The children list reads {children!r}; a banded child must show "
        "its band, not its low bound.")
    assert ["Anemias", "0.0%"] in children, (
        f"An unweighted child must still read as a single value: {children!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_the_closing_sentence_names_the_axis_it_is_totalling(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Coverage is per dimension and is never pooled (#64, #241).

    The three real Step 2 CK tables total 84-153%, 78-113% and 97-142%,
    because the axes are overlapping partitions of one item pool. A sentence
    reading "published ranges total 61-100% of the exam" with no axis named
    invites exactly the addition those figures forbid, so on a dimensioned
    exam the sentence says which axis it is talking about.
    """
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W346 Axis", exam_description="")
    dim = db.create_dimension(exam_id=exam.id, name="Systems",
                              display_order=1, is_required=True)
    for name, low, high in STEP1_SYSTEMS:
        db.create_subject_node(
            exam_context=exam.exam_name, name=name, level_type="System",
            dimension_id=dim, exam_weight_low=float(low),
            exam_weight_high=float(high))
    db.conn.commit()
    assert db.exam_uses_dimensions(exam.id), (
        "the seed must produce a dimensioned exam, or this asserts the "
        "plain path's sentence under a dimensioned name")

    open_tree_editor(wimi_page, exam.id)
    sentence = wimi_page.eval_js(
        "(() => { const e = document.querySelector('.weight-range-total');"
        " return e ? e.textContent.trim() : null; })()")
    assert sentence == (
        "Published ranges for Systems total 61–100% of the exam."), (
        f"the overview's closing sentence reads {sentence!r}")
