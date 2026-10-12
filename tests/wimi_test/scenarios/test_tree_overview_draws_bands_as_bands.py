"""Regression: the Exam Overview draws a published band as a band (#346, #347).

What this replaces
------------------
The overview's "Weight Distribution" donut drew each root as
``weight / total`` of 360 degrees over the roots' **low bounds**. Two
separate lies in one graphic, and the text half of #347 could not reach
either:

* the arc's *size* came from the low bound alone, so a subject publishing
  7-11% was drawn from the origin at a length taken from 7;
* the arcs were then rescaled to fill the ring, so that 7 became **11.5%
  of the circle** beside a legend row reading 7.0%, under a centre reading
  "61%" and a stat reading "61-100%".

The owner replaced it with a range-bar list on 2026-10-04 (#346): one row
per root, its band on one shared linear axis.

Why these assertions and not the easy one
-----------------------------------------
**A test that read the labels would pass against the donut**, which already
printed "7-11%" in its legend after #352. So nothing here reads a label as
evidence. What is measured is where the ink is:

* ``right / left`` must equal ``high / low``. That ratio is **scale-free**:
  any linear axis through the origin gives it, and a mark starting at the
  track's origin cannot produce it at all. It is the single assertion that
  the mark spans the interval rather than starting at zero.
* two roots sharing a low bound and differing in their high bound
  (4-8% and 4-6%) must share a left edge and differ in width. Under the
  old reading those two rows were **identical**; this one assertion kills
  it outright.
* the axis must be a scale over the individual weights, not over their
  total. Read off the page's own ruler, and bounded below by the largest
  high bound (13) and above by the total of the lows (61) -- without that
  bound the proportionality checks would be circular, since they take the
  axis maximum from the same page they are checking.

A single value is not a degenerate band: it renders as a tick, not as a bar
of some invented width, and is checked separately.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import (
    STEP1_SYSTEMS, open_tree_editor, seed_step1_roots)

# Per row: the mark's left and right edge as a percentage of the track it is
# drawn in, plus the mark's own pixel width. Percentages of the track, not of
# the panel, so the assertions survive a layout change.
READ_ROWS = """
(() => {
  const out = {};
  for (const b of document.querySelectorAll('.weight-range-row')) {
    const id = (b.getAttribute('data-testid') || '').split('-').pop();
    const t = b.querySelector('.weight-range-track');
    const m = b.querySelector('.weight-range-mark');
    if (!t || !m) { out[id] = {missing: true}; continue; }
    const tr = t.getBoundingClientRect(), mr = m.getBoundingClientRect();
    out[id] = {
      left: (mr.left - tr.left) / tr.width * 100,
      right: (mr.right - tr.left) / tr.width * 100,
      widthPx: mr.width,
      trackPx: tr.width,
      isPoint: m.classList.contains('is-point'),
      value: b.querySelector('.weight-range-value').textContent.trim(),
    };
  }
  return {
    rows: out,
    ticks: [...document.querySelectorAll('.weight-range-tick')]
             .map(e => parseFloat(e.textContent)),
    donutParts: document.querySelectorAll(
        '.pie-chart, .pie-slice, .pie-legend-item, .pie-legend').length,
  };
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_a_band_is_drawn_as_an_interval_on_a_shared_axis(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange ------------------------------------------------------
    db = wimi_session.user.db
    seeded = seed_step1_roots(db, "W346 Bands")
    ids = dict(zip((s[0] for s in STEP1_SYSTEMS), seeded["roots"]))
    flat = db.create_subject_node(
        exam_context=seeded["exam"].exam_name, name="Flat Five",
        level_type="System", exam_weight_low=5.0, exam_weight_high=5.0,
        sort_order=90).id
    bare = db.create_subject_node(
        exam_context=seeded["exam"].exam_name, name="Not Weighted Yet",
        level_type="System", sort_order=91).id

    open_tree_editor(wimi_page, seeded["exam"].id)
    seen = wimi_page.eval_js(READ_ROWS)
    rows = seen["rows"]

    assert seen["donutParts"] == 0, (
        "the donut is still on the page; a ring states parts of a whole and "
        "these are bands (#346)")
    assert len(rows) == len(STEP1_SYSTEMS) + 2, (
        f"expected one row per root, got {len(rows)}: {rows!r}")

    # ---- The axis is over the weights, not over their total ------------
    axis_max = max(seen["ticks"])
    assert seen["ticks"][0] == 0, (
        f"the axis does not start at 0: {seen['ticks']!r}. A bar chart whose "
        "baseline is not zero misstates every length on it.")
    assert 13 <= axis_max <= 20, (
        f"the shared axis tops out at {axis_max}%. The largest published high "
        f"bound is 13% and the lows total 61%, so an axis at or above 61 is "
        f"the donut's rescale in another shape (#64: coverage is surfaced, "
        f"never corrected). Ticks: {seen['ticks']!r}")

    # ---- Every band spans [low, high] ---------------------------------
    for name, low, high in STEP1_SYSTEMS:
        r = rows[str(ids[name])]
        assert not r["isPoint"], f"{name} publishes a range, not a value: {r!r}"
        # Scale-free: any linear axis through the origin gives high/low.
        # A mark starting at the track's origin gives infinity, and a mark
        # whose length came from the low bound gives low/0 or 1.
        assert r["left"] == pytest.approx(low / axis_max * 100, abs=0.6), (
            f"{name} publishes {low}-{high}% and its bar starts at "
            f"{r['left']:.1f}% of the track, not at {low / axis_max * 100:.1f}%. "
            f"A bar starting at the origin is the low bound standing in for "
            f"the band -- the reading #347 is about.")
        assert r["right"] == pytest.approx(high / axis_max * 100, abs=0.6), (
            f"{name} publishes {low}-{high}% and its bar ends at "
            f"{r['right']:.1f}% of the track, not at "
            f"{high / axis_max * 100:.1f}%. The high bound is not drawn.")
        assert r["right"] / r["left"] == pytest.approx(high / low, rel=0.05), (
            f"{name}: the bar's ends are in the ratio "
            f"{r['right'] / r['left']:.3f}, and {high}/{low} is "
            f"{high / low:.3f}. This ratio does not depend on the axis at "
            f"all, so it fails for any rendering that is not the interval.")

    # ---- The discriminator two equal low bounds give ------------------
    #
    # Multisystem publishes 4-8% and Biostatistics 4-6%. Read as low bounds
    # they are the same number and drew the same arc; as bands they share a
    # left edge and differ in length. One assertion, no axis arithmetic.
    wide = rows[str(ids["Multisystem Processes & Disorders"])]
    narrow = rows[str(ids["Biostatistics & Epidemiology"])]
    assert wide["left"] == pytest.approx(narrow["left"], abs=0.6), (
        f"two roots with the same low bound (4%) start at different places: "
        f"{wide['left']:.1f}% and {narrow['left']:.1f}%")
    assert wide["widthPx"] > narrow["widthPx"] * 1.5, (
        f"4-8% is drawn {wide['widthPx']:.1f} px wide and 4-6% "
        f"{narrow['widthPx']:.1f} px. Twice the range, barely wider -- which "
        f"is what a length taken from the shared low bound looks like.")

    # ---- A single value is a tick, not a one-pixel range ---------------
    point = rows[str(flat)]
    assert point["isPoint"] and point["value"] == "5.0%", (
        f"a subject weighted at exactly 5% should render as a point: {point!r}")
    assert point["widthPx"] <= 6, (
        f"the single-value mark is {point['widthPx']:.1f} px wide. Anything "
        f"bar-shaped invents a range the subject does not have.")
    centre = (point["left"] + point["right"]) / 2
    assert centre == pytest.approx(5 / axis_max * 100, abs=1.0), (
        f"the 5% tick sits at {centre:.1f}% of the track, not at "
        f"{5 / axis_max * 100:.1f}%")

    # ---- An unweighted root reads 0% and stays inside the track --------
    zero = rows[str(bare)]
    assert zero["isPoint"] and zero["value"] == "0.0%", zero
    assert zero["left"] >= -0.5 and zero["right"] <= 100.5, (
        f"the 0% tick is drawn outside its own track: {zero!r}")
