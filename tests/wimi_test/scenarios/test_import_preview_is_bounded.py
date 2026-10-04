"""Regression: the import preview draws a bounded amount of DOM (#212, #250).

Issue #212 — *"the import preview walks every node's whole subtree to render a
count it usually throws away, and expands by depth alone"*.

It named two defects and asked for a measurement before choosing between two
fixes. The measurement said the choice was not close. In real QtWebEngine, on
`master` at `d0a9f4e`:

    shape                 nodes   HTML    build  innerHTML   layout  elements
    18 roots, 7 levels    5,094  237 KiB  10.5      4.7      118.7     2,880
    40 x 12 x 5           2,920  866 KiB  14.2     17.2      380.1    11,680
    60 x 20 x 4           6,060 1798 KiB  32.1     36.3      788.7    24,240

**Layout was 10-25x the string building** that both named defects live in, and
on the two broad shapes *100%* of the file was materialised. Depth is the wrong
axis: `maxDepth = 3` was already in force in all three rows. So the fix is a
node budget; hoisting the redundant counting is a tidy-up that rides along.

After, same shapes and same machine:

    18 roots, 7 levels    5,094  128 KiB   6.7      3.7       73.0     1,550
    40 x 12 x 5           2,920   89 KiB   2.9      1.8       39.7     1,203
    60 x 20 x 4           6,060   89 KiB   2.7      1.8       39.7     1,202

**Flat in file size**, which is the property worth guarding: the last two rows
differ by 3,140 subjects and render the same amount of DOM.

What these tests assert is that property, not those numbers. Timings belong in
the issue -- they are machine-specific and a test that pinned them would fail
on a slower box while the code was still correct. What is stable is *bounded
element count*, *conservation* (nothing is dropped from the accounting), and
that a small file is still drawn in full.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# One helper for every case: build a synthetic tree of the given breadths,
# render it, and report what came out. Breadths are per depth, so the shape can
# be varied independently of size -- which is the point, since #212's bug was
# invisible on a deep narrow tree and total on a broad one.
_RUNNER = """
window.__p212 = function (breadths, weight) {
    const id = {v: 0};
    const make = (d) => {
        const n = {name: 'Subject ' + (id.v++)};
        if (weight !== null) n.weight = weight;
        if (d < breadths.length) {
            n.children = [];
            for (let i = 0; i < breadths[d]; i++) n.children.push(make(d + 1));
        }
        return n;
    };
    const roots = [];
    for (let i = 0; i < breadths[0]; i++) roots.push(make(1));

    const total = window.countNodesInHierarchy(roots);
    const html = window.renderImportPreviewTree(roots, 0, 3);

    const host = document.createElement('div');
    host.style.cssText = 'position:absolute;left:-99999px;top:0;width:800px';
    document.body.appendChild(host);
    host.innerHTML = html;
    const drawn = host.querySelectorAll('.import-preview-node').length;
    const elements = host.querySelectorAll('*').length;
    const notShown = Array.from(host.querySelectorAll('.import-preview-more'))
        .map(el => el.textContent.trim());
    const weights = Array.from(host.querySelectorAll('.preview-weight'))
        .map(el => el.textContent.trim());
    host.remove();

    return {total, drawn, elements, notShown, weights,
            kib: Math.round(html.length / 1024)};
};
true
"""

BUDGET = 300


def _ready(page: WimiPage) -> None:
    for _ in range(60):
        if page.eval_js("!!(window.renderImportPreviewTree "
                        "&& window.countNodesInHierarchy)"):
            page.eval_js(_RUNNER)
            return
        page.wait_for_timeout(100)
    raise AssertionError("the preview renderer never loaded")


@pytest.fixture
def probe(wimi_session: WimiTestSession, wimi_page: WimiPage):
    db = wimi_session.user.db
    db.create_exam_context(exam_name="Issue 212 Preview",
                          exam_description="bounded import preview")
    exam_id = db.get_exam_context_by_name("Issue 212 Preview").id
    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    _ready(wimi_page)

    def run(breadths, weight=None):
        import json
        return wimi_page.eval_js(
            f"window.__p212({json.dumps(breadths)}, {json.dumps(weight)})")

    return run


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("breadths,nodes", [
    ([40, 12, 5], 2920),
    ([60, 20, 4], 6060),
])
def test_a_broad_file_draws_no_more_than_the_budget(probe, breadths, nodes):
    """The headline. Both of these drew 100% of themselves before the fix."""
    result = probe(breadths)

    assert result["total"] == nodes, "the fixture is not the shape it claims"
    assert result["drawn"] <= BUDGET, (
        f'{result["drawn"]} subjects drawn for a {nodes}-node file; the budget '
        f'is {BUDGET}'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_the_dom_does_not_grow_with_the_file(probe):
    """The property that actually matters, and the one a budget buys.

    These two files differ by 3,140 subjects. Before the fix they differed by
    12,560 DOM elements and 409 ms of layout; a budget makes the larger file
    cost no more than the smaller one.
    """
    smaller = probe([40, 12, 5])
    larger = probe([60, 20, 4])

    assert larger["total"] > smaller["total"] + 3000
    assert larger["elements"] <= smaller["elements"] * 1.1, (
        f'{smaller["total"]} nodes -> {smaller["elements"]} elements but '
        f'{larger["total"]} nodes -> {larger["elements"]}; the DOM is still '
        f'growing with the file'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_nothing_is_lost_from_the_accounting(probe):
    """Rendered + reported-as-not-shown must cover the whole file.

    A budget that silently dropped the remainder would look identical to one
    that reported it, and would be a worse lie than the slow render it
    replaced: the student is reading this to decide whether to import.
    """
    result = probe([40, 12, 5])

    summaries = [s for s in result["notShown"] if "not shown" in s]
    assert summaries, "a truncated preview reported nothing as omitted"

    reported = sum(int("".join(c for c in s if c.isdigit())) for s in summaries)
    assert result["drawn"] + reported == result["total"], (
        f'{result["drawn"]} drawn + {reported} reported omitted != '
        f'{result["total"]} in the file'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_a_small_file_is_still_drawn_in_full(probe):
    """The negative control. A budget that truncated everything would pass
    every test above and make the preview useless."""
    result = probe([3, 2])

    assert result["total"] == 9
    assert result["drawn"] == 9
    assert not [s for s in result["notShown"] if "not shown" in s], (
        "a nine-node file was reported as truncated"
    )


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("weight,expected", [
    (12, "12.0%"),
    ({"value": 7.5}, "7.5%"),
    ({"low": 10, "high": 20}, "10.0–20.0%"),
    ({"low": 15, "high": 15}, "15.0%"),
])
def test_every_documented_weight_form_renders(probe, weight, expected):
    """#250: only the bare number rendered.

    `{low, high}` is the form real blueprints use -- #64 exists because
    published outlines give bands -- and `{...} > 0` is NaN, so the comparison
    was false and no weight was drawn at all. Silently, for exactly the files
    this preview was built for.
    """
    result = probe([2, 2], weight=weight)

    assert result["weights"], f'no weight rendered for {weight!r}'
    assert result["weights"][0] == expected


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("weight", [None, 0, {}, {"low": None, "high": None}])
def test_a_weightless_subject_renders_no_weight(probe, weight):
    """Negative control for the above. An omitted weight is not 0%% on screen:
    #64 makes it 0 on *import*, but drawing "0.0%" beside every subject of an
    unweighted outline would be noise the file did not ask for."""
    result = probe([2, 2], weight=weight)

    assert result["weights"] == [], f'{weight!r} drew {result["weights"]}'
