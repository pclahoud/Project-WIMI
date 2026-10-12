"""Regression: the import preview does not judge sibling weight totals (#488, #64).

`validateImportData` carried a `checkWeightTotals` that warned whenever a set of
siblings did not sum to 100%, recursing into every level. That contradicts the
rule the rest of WIMI is built on: **a weight is a percentage of the whole exam
at every level, and WIMI never rescales it** (#64). So siblings have no reason
to total 100%, the planner deliberately contains no such comparison, and the
check fired on correct files.

Measured in the real engine before the fix, from #488:

    bands_real         Sibling weights sum to 33.5% (expected 100%)
    value_children     Sibling weights sum to 10.0% (expected 100%)
    bare_33            Sibling weights sum to 33.5% (expected 100%)
    bands_84_153       Sibling weights sum to 118.5% (expected 100%)
    value_exactly_100  (silent)
    value_33           (silent)
    bare_exactly_100   (silent)
    unweighted         (silent)

`bands_real` is three real published Step 2 CK rows copied verbatim. The 118.5%
is the figure `docs/manual/20_weights.md` and CLAUDE.md both use as the worked
example of a *legitimate* published total.

**Two of those silences were the second defect, and they are why this file is
shaped the way it is.** `typeof w === 'object'` is true for `{value: N}` — one
of the three weight forms the import guide documents, and the one chapter 03
points a chat assistant at — and the branch then read only `w.low` and `w.high`,
both undefined, both defaulted to 0. So those subjects contributed nothing and
the check could not see them. #488's own first probe used `{value: N}` for its
"totals exactly 100" control and **passed vacuously**; that is how the second
defect was found.

So every case here that must be silent is written with **bare numbers or
bands**, the spellings the old code could actually see. A `{value: N}` case
would pass against the unfixed tree and prove nothing.

The positive control is `transposed_band`. A low above its high still warns
(`type: 'range'`, a warning and never a rejection per #64), which is what
distinguishes "the sibling sum is gone" from "weight validation is gone" or
"`validateImportData` threw and returned nothing". Without it this whole file
would pass against a function that had stopped running.
"""

from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# `validateImportData` is a top-level `function` declaration in a classic
# script, so it IS a property of `window` -- unlike `const EntryState` and
# friends, which are script-scope bindings and read `undefined` off `window`
# with no error. That difference has cost two scenarios a debugging cycle, so
# it is worth stating rather than relying on.
_PROBE = """
window.__p488 = function (file) {
    const r = window.validateImportData(file);
    return {
        warningTypes: (r.warnings || []).map(w => w.type),
        warnings: (r.warnings || []).map(w => w.message),
        errorCount: (r.errors || []).length,
        validNodeCount: r.validNodeCount,
    };
};
true
"""

# Each case is a file shape plus what it means. Bare numbers and bands only --
# see the module docstring for why a `{value: N}` case would be vacuous here.
_SILENT_CASES = {
    # Three real published Step 2 CK rows, copied verbatim. Was 33.5%.
    "bands_real": [
        {"name": "A", "weight": {"low": 8, "high": 12}},
        {"name": "B", "weight": {"low": 15, "high": 20}},
        {"name": "C", "weight": {"low": 4, "high": 8}},
    ],
    # A legitimate published total of 84-153%. Was 118.5%.
    "bands_84_153": [
        {"name": "A", "weight": {"low": 40, "high": 70}},
        {"name": "B", "weight": {"low": 24, "high": 45}},
        {"name": "C", "weight": {"low": 20, "high": 38}},
    ],
    # Bare numbers: the spelling the old check could see, so this is the case
    # that makes this test non-vacuous. Was 33.5%.
    "bare_33": [
        {"name": "A", "weight": 20},
        {"name": "B", "weight": 13.5},
    ],
    # A child may exceed its parent and a parent's share is not divided among
    # its children (#64). The old check recursed, so this warned twice.
    "parent_child": [
        {"name": "Parent", "weight": {"low": 8, "high": 12}, "children": [
            {"name": "Child A", "weight": 3},
            {"name": "Child B", "weight": 2},
        ]},
    ],
    # The control for the old check's own `total > 0` guard.
    "unweighted": [{"name": "A"}, {"name": "B"}],
}


def _ready(page: WimiPage) -> None:
    for _ in range(60):
        if page.eval_js("typeof window.validateImportData === 'function'"):
            page.eval_js(_PROBE)
            return
        page.wait_for_timeout(100)
    raise AssertionError("validateImportData never loaded on the tree editor")


@pytest.fixture
def validate(wimi_session: WimiTestSession, wimi_page: WimiPage):
    db = wimi_session.user.db
    db.create_exam_context(exam_name="Issue 488 Weights",
                           exam_description="sibling weight totals")
    exam_id = db.get_exam_context_by_name("Issue 488 Weights").id
    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    _ready(wimi_page)

    def run(nodes):
        file = {"root_nodes": nodes}
        return wimi_page.eval_js(f"window.__p488({json.dumps(file)})")

    return run


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("case", sorted(_SILENT_CASES))
def test_a_correct_file_draws_no_weight_warning(validate, case):
    """The headline. Every one of these warned before the fix except the last."""
    result = validate(_SILENT_CASES[case])

    assert "weight" not in result["warningTypes"], (
        f"{case}: a sibling-total warning is back -- {result['warnings']}"
    )
    assert not [m for m in result["warnings"] if "expected 100%" in m], (
        f"{case}: {result['warnings']}"
    )


@pytest.mark.slow
@pytest.mark.regression
def test_a_transposed_band_still_warns(validate):
    """The positive control, without which this file is a tautology.

    A low above its high is a real transcription mistake and still earns a
    warning -- a warning and never a rejection, because losing a 2,000-subject
    file over one transposed pair helps nobody (#64). If this ever goes quiet,
    the tests above are passing because weight validation stopped running, not
    because the sibling sum is gone.
    """
    result = validate([{"name": "A", "weight": {"low": 20, "high": 10}}])

    assert "range" in result["warningTypes"], (
        f"weight validation itself has stopped: {result}"
    )
    assert any("is above high" in m for m in result["warnings"]), result["warnings"]
    assert "weight" not in result["warningTypes"], result["warnings"]


@pytest.mark.slow
@pytest.mark.regression
def test_a_malformed_file_is_still_rejected(validate):
    """The second control: errors still flow, so the function really ran."""
    result = validate([{"weight": 10}, {"name": ""}])

    assert result["errorCount"] > 0, (
        f"a file of nameless subjects passed validation: {result}"
    )
