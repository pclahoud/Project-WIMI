"""Regression: Question Banks Compared is on the analytics page (#604).

`source_chart.js` and `source_table.js` were written for this section and
**loaded by no page for their whole existence** -- `git log -S` against
`src/web/html/*.html` returns zero commits for either. Everything behind them
was already live (`get_source_comparison` -> `getSourceComparison` -> `api`),
so wiring them up is a container, a caller, and this file. The owner's
decision on #604 was to put them on the analytics page.

Three things are asserted, and the third is why the first two are not enough:

* **the section draws** -- an SVG from the D3 chart and a row per source in
  the table, from a real `api.getSourceComparison` round trip;
* **a stored source name is text, not markup.** These files were swept as
  dead code: `source_table.js` was escaped in #603 on a file nothing loaded,
  and this is the first test that can fail if that escaping is removed;
* **an exam with no question banks hides the section entirely.** Without that,
  "the section exists" would pass against a page that always draws two empty
  frames -- #60's two-empty-boxes-and-a-gap, which `loadSourceComparison`
  exists to avoid.

One latent crash was fixed on the way in and is covered by the first test
rather than its own: `source_chart.js` built a D3 selector out of the source
name (`.point-${name.replace(/\W/g,'')}`). Nothing ever applied that class so
the join did no work, but a name starting with a digit or reducing to nothing
makes an **invalid CSS selector**, and `selectAll` throws a SyntaxError that
takes the chart with it. The seeded names below include both shapes, so the
chart drawing at all is the assertion.
"""

from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

EXAM = "Source Section Exam"

HANDLER = 'onerror="(window.__x=window.__x||[]).push(1)"'
#: A payload name, and two names that broke the old D3 selector: one starting
#: with a digit, one reducing to the empty string once `\W` is stripped.
PAYLOAD_SOURCE = f'UWorld <img src=x {HANDLER}>'
DIGIT_SOURCE = "2024 Qbank"
SYMBOL_SOURCE = "???"

_READ = """
(() => {
  const section = document.querySelector('.source-section');
  const table = document.getElementById('sourceComparisonTable');
  const chart = document.getElementById('sourceComparisonChart');
  const shown = section
      ? getComputedStyle(section).display !== 'none' : null;
  return JSON.stringify({
    section_present: !!section,
    section_shown: shown,
    fired: (window.__x || []).length,
    imgs: table ? table.querySelectorAll('img').length : null,
    rows: table ? table.querySelectorAll('tbody tr').length : null,
    names: table
        ? [...table.querySelectorAll('.source-label')].map(e => e.textContent)
        : null,
    svgs: chart ? chart.querySelectorAll('svg').length : null,
    circles: chart ? chart.querySelectorAll('circle').length : null,
  });
})()
"""


def _seed_entries(db, exam, source_id, n):
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=n, total_incorrect=n,
        question_source_id=source_id, session_name=f"s{source_id}")
    for i in range(n):
        db.create_question_entry(session.id, f"q{i}", f"a{i}")


@pytest.fixture
def analytics(wimi_session: WimiTestSession, wimi_page: WimiPage):
    """An exam with three question banks, two of them awkwardly named."""
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name=EXAM, exam_description="#604")
    for name, n in ((PAYLOAD_SOURCE, 3), (DIGIT_SOURCE, 2), (SYMBOL_SOURCE, 1)):
        src = db.create_question_source(source_name=name, exam_context=EXAM)
        _seed_entries(db, exam, src.id, n)
    db.conn.commit()

    wimi_page.goto("analytics")
    assert poll(
        wimi_page,
        "document.querySelectorAll("
        "'#sourceComparisonTable tbody tr').length > 0",
        timeout_ms=30000,
    ), "the source table never rendered a row"
    return wimi_page


@pytest.mark.slow
@pytest.mark.regression
def test_the_section_draws_from_a_real_round_trip(analytics):
    """The headline: both renderers run on data fetched through the bridge."""
    state = json.loads(analytics.eval_js(_READ))

    assert state["section_present"], "the section is not in the page"
    assert state["section_shown"] is True, state
    assert state["rows"] == 3, f"expected a row per question bank: {state}"
    assert state["svgs"] == 1, (
        f"the D3 chart drew no svg -- if 0, check whether a source name made "
        f"an invalid selector: {state}")
    assert state["circles"] > 0, f"the chart drew no data points: {state}"


@pytest.mark.slow
@pytest.mark.regression
def test_a_stored_source_name_is_text(analytics):
    """First test that can fail if #603's escaping is removed.

    Both files were reviewed and escaped as *dead code*; nothing could
    exercise them until this section existed.
    """
    state = json.loads(analytics.eval_js(_READ))

    assert state["fired"] == 0, f"a stored source name ran as markup: {state}"
    assert state["imgs"] == 0, f"a stored source name was parsed: {state}"
    assert PAYLOAD_SOURCE in state["names"], (
        f"the name is not shown exactly; an escape that mangles it fails too: "
        f"{state['names']}")


@pytest.mark.slow
@pytest.mark.regression
def test_no_question_banks_hides_the_section(analytics):
    """The control, and the reason the other two mean something.

    Without it, "the section is present and shown" would pass against a page
    that always draws two empty frames with a gap between them.

    **This drives the branch rather than seeding an exam with no banks**, and
    the first attempt did the latter and failed for a reason that had nothing
    to do with the code: `wimi_session` is session-scoped, so the banks seeded
    by the fixture above still existed, and `loadSourceComparison` passes
    `this.currentExamFilter || null` -- a null filter returns every source in
    the profile. The test reported `section_shown: True` with `rows: 0`, which
    reads exactly like the hide branch being broken.

    So the payload is replaced at the one seam that decides this, and the
    plumbing it bypasses is what the first test covers.
    """
    page = analytics

    # Precondition: it is visible, or the assertion below asserts nothing.
    assert json.loads(page.eval_js(_READ))["section_shown"] is True

    page.eval_js("""
        window.api.getSourceComparison = () =>
            Promise.resolve({sources: [], timeline: []});
        window.dashboard.loadSourceComparison();
        true
    """)
    assert poll(
        page,
        "(() => {const s = document.querySelector('.source-section');"
        " return !!s && getComputedStyle(s).display === 'none';})()",
        timeout_ms=15000,
    ), "a profile with no question banks drew the section anyway"

    state = json.loads(page.eval_js(_READ))
    assert state["section_present"], (
        "the section stays in the markup; this is about it being hidden, not "
        "removed")
    assert state["section_shown"] is False, state
