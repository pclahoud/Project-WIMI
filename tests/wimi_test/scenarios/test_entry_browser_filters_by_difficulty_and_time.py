"""Regression: the entry browser opens on a difficulty and time link, and a
removed error type survives Apply (#898 Wave 1).

The difficulty and time card links into the entry browser with ``difficulty``
and ``time_max`` (and friends) in the URL. The first test opens such a link
and asserts the count and the chips, which must say in words what they
filter: the difficulty in ``WimiDifficulty``'s words (#46), the time as the
card's label says it, rounded up (a median of 94.5 s reads "under 1 min
35 s", which is exactly true of every whole-second time under it). The
positive control is the same link without ``time_max``, which must show more.

The second is the bug the plan found: a type removed from the exam's list
(#888) still sits on entries, so a link can carry it, but the error-type
panel drew only the exam's list and ``applyTagFilter`` rebuilt the filter
from the ticked boxes. With no box for the removed type, pressing Apply
silently dropped it and the page went on to show every entry under a
"filtered" header. **This fails on master ``fde66e1``**: there the total
after Apply is every entry (8), not the 2 that carry the type.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import centre_of, poll, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

SETTLED = ("typeof entryBrowser !== 'undefined' && entryBrowser.isPageReady"
           " && !window.__w898_old_document && entryBrowser.totalEntries >= 0"
           " && document.getElementById('loadingState').style.display === 'none'")


def _seed(db) -> dict:
    exam = db.create_exam_context(exam_name="W898 Exam", exam_description="#898")
    subject = db.create_subject_node(exam.exam_name, "W898 Topic", "System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=8, total_incorrect=8,
        session_name="W898 session", date_encountered=date.today())
    group = db.create_tag_group(exam.exam_name, "W898 Kinds")
    kept = db.create_hierarchical_tag(exam.exam_name, "W898 Kept", group.id).id
    removed = db.create_hierarchical_tag(
        exam.exam_name, "W898 Removed", group.id).id
    for d, t, tags in [(5, 30, [kept]), (4, 60, [removed]), (4, 94, []),
                       (4, 95, [kept]), (5, 200, [removed]), (2, 30, []),
                       (3, 40, []), (None, None, [])]:
        db.create_question_entry(
            session.id, "A", "B", perceived_difficulty=d,
            time_spent_seconds=t, reflection="r", explanation="e",
            primary_subject_ids=[subject.id], tag_ids=tags)
    db.remove_tag_from_exam(exam.exam_name, removed)
    db.conn.commit()
    return {"exam": exam.id, "removed": removed}


def _open(page: WimiPage, query: dict) -> int:
    """Open the browser on ``query`` and return its total once it settles.

    A second ``goto`` to the same page returns before the new document
    commits, so the old document is marked and the wait outlasts it.
    """
    try:
        page.eval_js("window.__w898_old_document = true")
    except Exception:
        pass
    page.goto("entry-browser", query=query)
    assert poll(page, SETTLED, timeout_ms=20000), f"never settled on {query}"
    return page.eval_js("entryBrowser.totalEntries")


def _chip(page: WimiPage, kind: str):
    return page.eval_js(
        "(() => { const c = document.querySelector("
        f"'[data-testid=\"browser-filter-chip-{kind}\"]');"
        " return c ? c.firstChild.textContent.trim() : null; })()")


@pytest.mark.slow
@pytest.mark.regression
def test_a_difficulty_and_time_link_lands_and_says_so(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    ids = _seed(wimi_session.user.db)
    control = _open(wimi_page, {"exam": ids["exam"], "difficulty": "4,5"})
    assert control == 5, f"control: rated Hard or Very Hard is 5, read {control}"

    total = _open(wimi_page, {"exam": ids["exam"], "difficulty": "4,5",
                              "time_max": "94.5"})
    assert total == 3, (
        f"rated 4-5 and under 94.5 s is the 30, 60 and 94 s entries; the "
        f"browser shows {total}")
    assert total < control
    assert _chip(wimi_page, "difficulty") == "Difficulty: Hard, Very Hard"
    assert _chip(wimi_page, "time") == "Time: under 1 min 35 s"
    # The panels show what the link put in force, not their defaults.
    assert wimi_page.eval_js(
        "document.getElementById('difficultyFilterValue').textContent") == (
        "2 selected")
    assert wimi_page.eval_js("document.getElementById('timeMax').value") == "94.5"


@pytest.mark.slow
@pytest.mark.regression
def test_a_removed_type_survives_apply(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    ids = _seed(wimi_session.user.db)
    # ``tag`` is the URL key master already reads, so this test fails there
    # for #898's reason (Apply drops the type) rather than for a missing key.
    before = _open(wimi_page, {"exam": ids["exam"], "tag": ids["removed"]})
    assert before == 2, f"the link itself should land on 2 entries, read {before}"

    real_click(wimi_page, centre_of(wimi_page, "#tagFilterBtn"))
    assert poll(wimi_page, "document.getElementById('tagFilterBtn')"
                ".closest('.filter-group').classList.contains('open')",
                timeout_ms=5000), "the error-type panel did not open"
    wimi_page.eval_js("entryBrowser.totalEntries = -1")
    real_click(wimi_page, centre_of(wimi_page, "#applyTags"))
    assert poll(wimi_page, SETTLED, timeout_ms=15000), "Apply never reloaded"

    after = wimi_page.eval_js("entryBrowser.totalEntries")
    picked = json.loads(wimi_page.eval_js(
        "JSON.stringify(entryBrowser.filters.tagIds)"))
    assert after == 2 and picked == [ids["removed"]], (
        f"#898: Apply with a removed type in force left tagIds={picked} and "
        f"{after} entries; it should keep the type and its 2 entries")
    assert _chip(wimi_page, "tag") == "Error type: W898 Removed"

    box = (f"document.querySelector('[data-testid=\"browser-tag-group-not-listed\"]"
           f" [data-testid=\"browser-tag-checkbox-{ids['removed']}\"]')")
    assert wimi_page.eval_js(f"!!{box} && {box}.checked"), (
        "the removed type should be drawn, ticked, under 'No longer on this exam'")
