"""Regression: dimension-only analytics sections on an exam without dimensions (#473).

**Cross-Dimension Analysis**, **Study Recommendations** and **Interaction
Effects** need two dimensions to mean anything. They ship `display:none` in the
markup and `initializeDimensionAnalytics()` hides them again through
`showMultiDimensionalSections(false)` when the exam has none. Then `init()` --
and the exam selector's change handler -- call `applyChartVisibility()` LAST,
whose "visible" branch is `el.style.display = ''`. Every one of the three
`chart_visibility` keys defaults to `True`, so that line cleared both the
runtime hide and the markup's own, and a student on a simple exam was shown
three headings over empty pickers, an empty div and an Export CSV button: the
#174 class, an affordance with nothing behind it.

The dimension gate is a capability test and the visibility config is a
preference; a preference cannot switch on a feature the exam cannot support.
So the fix makes `applyChartVisibility` keep the three dimension-only sections
hidden whenever the gate said no. Nothing is de-emphasised or restyled -- only
whether the section is displayed.

Both directions are asserted, because a fix that "hides them always" would
pass the first test alone:

* a single-dimension exam -> all three hidden, on load and after switching to
  it from a multi-dimensional exam through the exam filter;
* the `multi_dimensional` fixture -> all three displayed (positive control);
* the multi-dimensional exam with one preference off -> that one hidden and the
  other two still shown, so the preference still governs where the capability
  exists.

**Waiting for the right moment.** The defect is the LAST thing `init()` does,
so a probe that reads the sections before `applyChartVisibility()` has run
passes on the unfixed tree. `applyChartSizes()` is called immediately after it
on both paths, so a hook installed before the page's scripts counts its calls
and the test waits for the count to move. The hook only observes; the code
under test is the code that ships.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.db.seeders import seed_multi_dimensional
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

SECTIONS = {
    "cross_dimension_heatmap": "crossDimensionSection",
    "study_recommendations": "recommendationsSection",
    "interaction_effects": "interactionEffectsContainer",
}

# Counts completed visibility passes: applyChartSizes() runs straight after
# applyChartVisibility() in init() and in the exam filter's change handler.
SETTLED_HOOK = """
document.addEventListener('DOMContentLoaded', () => {
  window.__w473settled = 0;
  try {
    const proto = AnalyticsDashboard.prototype;
    const real = proto.applyChartSizes;
    proto.applyChartSizes = function (...args) {
      const out = real.apply(this, args);
      window.__w473settled += 1;
      return out;
    };
  } catch (err) { window.__w473hookError = String(err); }
}, {capture: true});
"""

READ_SECTIONS = """
(() => JSON.stringify(Object.fromEntries(%s.map(id => {
  const el = document.getElementById(id);
  if (!el) return [id, null];
  const r = el.getBoundingClientRect();
  return [id, {display: getComputedStyle(el).display, height: r.height}];
}))))()
""" % json.dumps(list(SECTIONS.values()))


def _settled_count(page: WimiPage) -> int:
    value = page.eval_js("typeof window.__w473settled === 'number'"
                         " ? window.__w473settled : -1")
    return int(value)


def _wait_settled(page: WimiPage, past: int, what: str) -> None:
    for _ in range(300):
        if _settled_count(page) > past:
            return
        page.wait_for_timeout(50)
    err = page.eval_js("window.__w473hookError || null")
    raise AssertionError(
        f"{what}: the dashboard never reached the end of its visibility pass "
        f"(applyChartSizes count stayed {_settled_count(page)}, hook error "
        f"{err!r}); any reading taken now could precede the defect")


def _open(page: WimiPage, exam_id: int) -> dict:
    page.tab.Page.enable()
    page.tab.Page.addScriptToEvaluateOnNewDocument(source=SETTLED_HOOK)
    page.goto("analytics", query={"exam": exam_id})
    _wait_settled(page, 0, f"opening exam {exam_id}")
    return json.loads(page.eval_js(READ_SECTIONS))


def _shown(state: dict, section_id: str) -> bool:
    s = state[section_id]
    assert s is not None, f"#{section_id} is missing from the page"
    return s["display"] != "none" and s["height"] > 0


@pytest.fixture
def exams(wimi_session: WimiTestSession) -> dict:
    """A plain exam with one entry, and the two-dimension fixture."""
    db = wimi_session.user.db
    simple = db.create_exam_context(
        exam_name="W473 Simple Exam", exam_description="Issue #473",
        hierarchy_levels=["System", "Topic"],
    )
    node = db.create_subject_node(
        exam_context=simple.exam_name, name="Cardiology", level_type="System",
    )
    session = db.create_review_session(
        exam_context_id=simple.id, total_questions=1, total_incorrect=1,
        session_name="W473", date_encountered=date.today(),
    )
    db.create_question_entry(
        review_session_id=session.id, user_answer="a", correct_answer="b",
        primary_subject_ids=[node.id],
    )
    multi = seed_multi_dimensional(db)
    db.conn.commit()
    return {"simple": simple.id, "multi": multi.exam_context_id, "db": db}


@pytest.mark.slow
@pytest.mark.regression
def test_a_simple_exam_does_not_show_the_dimension_sections(
    wimi_page: WimiPage, exams: dict,
) -> None:
    state = _open(wimi_page, exams["simple"])
    shown = [sid for sid in SECTIONS.values() if _shown(state, sid)]
    assert shown == [], (
        f"on an exam with no dimensions these sections are displayed: {shown} "
        f"({state}). applyChartVisibility() ran after the dimension gate and "
        f"its `display = ''` undid the hide -- #473")


@pytest.mark.slow
@pytest.mark.regression
def test_switching_to_a_simple_exam_hides_them_again(
    wimi_page: WimiPage, exams: dict,
) -> None:
    """The exam filter's change handler runs the same gate-then-visibility order."""
    state = _open(wimi_page, exams["multi"])
    assert all(_shown(state, sid) for sid in SECTIONS.values()), (
        f"precondition: the multi-dimensional exam should show all three "
        f"before the switch: {state}")

    before = _settled_count(wimi_page)
    wimi_page.eval_js(
        "(() => { const s = document.getElementById('examFilter');"
        " s.value = %s; s.dispatchEvent(new Event('change')); })()"
        % json.dumps(str(exams["simple"])))
    _wait_settled(wimi_page, before, "switching to the simple exam")

    state = json.loads(wimi_page.eval_js(READ_SECTIONS))
    shown = [sid for sid in SECTIONS.values() if _shown(state, sid)]
    assert shown == [], (
        f"after switching to an exam with no dimensions these are still "
        f"displayed: {shown} ({state}) -- #473 via the exam filter")


@pytest.mark.slow
@pytest.mark.regression
def test_a_multi_dimensional_exam_still_shows_them(
    wimi_page: WimiPage, exams: dict,
) -> None:
    """Positive control: a fix that hides them always must fail here."""
    state = _open(wimi_page, exams["multi"])
    hidden = [sid for sid in SECTIONS.values() if not _shown(state, sid)]
    assert hidden == [], (
        f"on the two-dimension fixture these sections are hidden: {hidden} "
        f"({state}); the dimension gate should have let them through")


@pytest.mark.slow
@pytest.mark.regression
def test_the_preference_still_hides_one_on_a_multi_dimensional_exam(
    wimi_page: WimiPage, exams: dict,
) -> None:
    """The capability gate must not override a student's 'off'."""
    exams["db"].update_exam_analytics_config(
        exams["multi"],
        {"chart_visibility": {"interaction_effects": False}},
    )
    exams["db"].conn.commit()
    state = _open(wimi_page, exams["multi"])
    assert not _shown(state, "interactionEffectsContainer"), (
        f"Interaction Effects is switched off for this exam and still shown: "
        f"{state}")
    assert _shown(state, "crossDimensionSection") and _shown(
        state, "recommendationsSection"), (
        f"switching one section off hid the others too: {state}")
