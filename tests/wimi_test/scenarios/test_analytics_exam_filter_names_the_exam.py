"""Regression: the analytics exam filter rendered as an empty box (#310).

#310 was filed as one unexplained observation on one machine, with three
candidate causes and none ruled out:

    1. a race with load -- options populated after the value was set, or the
       screenshot taken between the two;
    2. a styling issue making the selected option invisible rather than absent;
    3. the URL's `exam=2` not matching any option's `value`, so
       `select.value = '2'` silently selects nothing.

**Candidate 3, measured.** `loadExamFilter` called `api.getAllExamContexts()`
with no argument, which defaults to `active_only=true`, so a **suspended** exam
named by the URL was never among the options. Assigning an unmatched value to a
`<select>` is not an error: it leaves `selectedIndex = -1` and `value = ''`,
which paints an empty box with the control present and still accessibly named
"Exam filter" -- exactly what the screenshot showed.

Measured on Linux before the fix, one active exam and one suspended one:

    ?exam=1 (active)     length=1  value='1'  selectedIndex=0
    ?exam=2 (suspended)  length=1  value=''   selectedIndex=-1   <-- #310

It is reachable in **one click**, not only by typing a URL. `renderExamCard` in
`landing.js` puts a "Analytics" button on *every* exam card -- the
`isSuspended` branch swaps only the utility row (Reactivate / Delete
Permanently), so the Browse / Analytics / Subjects row is rendered for a
suspended exam too, and `viewAnalytics` navigates to
`analytics_dashboard.html?exam=<id>`.

**The surface one page earlier already disagreed with this one.** Of the four
callers of `getAllExamContexts`, `landing.js:411` passes `false` -- commented
"Include inactive" -- while `settings.js` and `analytics_preview.js` pass `true`
explicitly. The analytics dashboard was the only one leaving it implicit, and
the only one reachable with an inactive id in its URL. So the fix brings it into
line with the page that links to it: the filter must be able to name the exam
whose data the page is showing, and it *was* showing it -- `currentExamFilter`
stayed 2, so every chart loaded exam 2's data under a blank filter.

Candidates 1 and 2 are **not** the mechanism here. The blank box is
`selectedIndex = -1`, which no amount of waiting or restyling changes. Neither
is thereby disproved as a separate possibility; this test pins the one that was
measured.

**The asymmetry that kept this unexplained**, also measured: an `exam=` id that
is not an exam *at all* was never silent. Navigating to `?exam=1000` on a
profile with one exam produces nine console entries, six of them naming the id
(`Exam context 1000 not found`, from `getExamAnalyticsConfig`,
`getSubjectHierarchyWithMistakes`, `getSubjectExamWeightAnalysis`,
`getWeightSourceBreakdown` and two WeightAnalysis frames). So the silence
required the exam to **exist** and merely be excluded from the options: every
bridge call then succeeds, every chart renders real data, and only the `<select>`
cannot represent it. A third test asserting "an unknown id is not silent" was
written here and **deleted as vacuous** -- it passed before the fix, because the
page was already shouting.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_SELECT_JS = """
(() => {
  const s = document.getElementById('examFilter');
  if (!s) return JSON.stringify({found: false});
  return JSON.stringify({
    found: true,
    length: s.options.length,
    value: s.value,
    selectedIndex: s.selectedIndex,
    options: Array.from(s.options).map(o => o.value),
    selectedText: s.selectedIndex >= 0 ? s.options[s.selectedIndex].text : null,
  });
})()
"""


def _read_filter(page: WimiPage, attempts: int = 60) -> dict:
    """Poll until the filter has been populated at all.

    The dashboard's `init()` awaits `loadExamFilter()` before anything else, so
    a populated select is the earliest settled state there is -- which is also
    what rules candidate 1 (a race) out rather than merely outwaiting it.
    """
    last: dict = {}
    for _ in range(attempts):
        last = json.loads(page.eval_js(_SELECT_JS))
        if last.get("found") and last.get("length"):
            return last
        page.wait_for_timeout(100)
    return last


@pytest.fixture
def two_exams(wimi_session: WimiTestSession) -> dict:
    """One active exam and one suspended one."""
    db = wimi_session.user.db
    active = db.create_exam_context(
        exam_name="W310 Active", exam_description="Issue #310",
    )
    suspended = db.create_exam_context(
        exam_name="W310 Suspended", exam_description="Issue #310",
    )
    db.update_exam_context_settings(
        exam_context_id=suspended.id, is_active=False,
    )
    db.conn.commit()
    return {"active": active.id, "suspended": suspended.id}


@pytest.mark.slow
@pytest.mark.regression
def test_a_suspended_exam_is_named_by_the_filter(
    wimi_page: WimiPage, two_exams: dict,
) -> None:
    """#310's mechanism: the one the dashboard's Analytics button reaches."""
    # ---- Act ---------------------------------------------------------
    wimi_page.goto("analytics", query={"exam": two_exams["suspended"]})
    state = _read_filter(wimi_page)

    # ---- Assert ------------------------------------------------------
    assert state.get("found"), f"#examFilter is not on the page: {state!r}"
    assert str(two_exams["suspended"]) in state["options"], (
        f"the suspended exam is absent from the filter's options "
        f"({state['options']}), so `select.value` cannot match it and the box "
        f"renders empty -- #310. The page is still showing this exam's data."
    )
    assert state["selectedIndex"] >= 0, (
        f"the filter has no selection (selectedIndex={state['selectedIndex']}, "
        f"value={state['value']!r}). That is the empty box #310 screenshotted: "
        f"assigning an unmatched value to a <select> selects nothing and "
        f"raises nothing."
    )
    assert state["value"] == str(two_exams["suspended"]), (
        f"the filter selected {state['value']!r} while the URL named "
        f"{two_exams['suspended']} -- the page would be naming one exam and "
        f"charting another, which is worse than the blank box"
    )
    # The option says it is suspended. Without this the fix would trade one
    # untruth for a quieter one: the filter would list a suspended exam
    # indistinguishably from an active one, on a page reached from a card that
    # carries a "Suspended" badge for the same exam.
    assert state["selectedText"] == "W310 Suspended (suspended)", (
        f"the filter is showing {state['selectedText']!r}; it should name the "
        f"exam AND say that it is suspended")


@pytest.mark.slow
@pytest.mark.regression
def test_an_active_exam_still_selects_itself(
    wimi_page: WimiPage, two_exams: dict,
) -> None:
    """Positive control: the path that always worked must keep working.

    Without this, "put every exam in the list" could regress the ordinary case
    and the test above would still pass.
    """
    wimi_page.goto("analytics", query={"exam": two_exams["active"]})
    state = _read_filter(wimi_page)

    assert state.get("found"), f"#examFilter is not on the page: {state!r}"
    assert state["value"] == str(two_exams["active"]), (
        f"an ACTIVE exam named by the URL is no longer selected: {state!r}")
    assert state["selectedText"] == "W310 Active"
