"""Regression: the JavaScript link builder agrees with the Python one, and
its links land on the card's counts in the real entry browser (#898 Wave 1).

``tests/database/test_entry_browser_lands_on_the_card.py`` proves that
``dt_entry_browser_params`` (Python) lands on every bucket's count, with the
entry browser's URL handling mirrored in Python. This closes the two gaps a
Python test cannot reach:

1. ``WimiDifficultyTimeLinks.paramsFor`` -- the copy Wave 2's card will call
   -- returns the same parameters as the Python helper for every bucket, on
   a real payload with a picker selection and on the deep-dive scope;
2. opening each of those links in the real page, through
   ``parseUrlParams`` and ``filterParams``, shows the card's count.

The positive control is the bucket counts themselves: the fixture makes
every bucket non-empty, so agreement cannot be agreement on zero.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from database.domains.analytics_advanced import (
    DT_LINK_BUCKETS, dt_entry_browser_params)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

SETTLED = ("typeof entryBrowser !== 'undefined' && entryBrowser.isPageReady"
           " && !window.__w898_old_document && entryBrowser.totalEntries >= 0"
           " && document.getElementById('loadingState').style.display === 'none'")


def _seed(db) -> dict:
    exam = db.create_exam_context(exam_name="W898L Exam", exam_description="#898")
    root = db.create_subject_node(exam.exam_name, "W898L Root", "System")
    other = db.create_subject_node(exam.exam_name, "W898L Other", "System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=40, total_incorrect=40,
        session_name="W898L", date_encountered=date.today())
    a = db.create_tag(exam.exam_name, "W898L A").id
    b = db.create_tag(exam.exam_name, "W898L B").id
    rows = []
    for i, (d, t) in enumerate([(5, 20), (4, 30), (4, 75), (5, 90), (2, 20),
                                (1, 40), (2, 80), (1, 120), (3, 50), (3, 60),
                                (None, 70), (4, None), (2, 0), (5, 100)]):
        rows.append((d, t, [[a], [b], [a, b], []][i % 4],
                     root if i % 3 else other))
    for d, t, tags, subject in rows:
        db.create_question_entry(
            session.id, "A", "B", perceived_difficulty=d,
            time_spent_seconds=t, reflection="r", explanation="e",
            primary_subject_ids=[subject.id], tag_ids=tags)
    db.conn.commit()
    return {"exam": exam.id, "root": root.id, "a": a, "b": b}


def _count(payload: dict, bucket: str) -> int:
    if bucket == "total":
        return sum(1 for e in payload["entries"] if e["matches"])
    return payload["buckets"][bucket]["match"]["count"]


@pytest.mark.slow
@pytest.mark.regression
def test_js_links_match_python_and_land_on_the_cards_counts(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    ids = _seed(db)
    wimi_page.goto("entry-browser", query={"exam": ids["exam"]})
    assert poll(wimi_page, SETTLED, timeout_ms=20000)

    payloads = {
        "dashboard, any": db.get_difficulty_time_quadrants(
            ids["exam"], tag_ids=[ids["a"], ids["b"]], match="any"),
        "deep dive, all": db.get_difficulty_time_quadrants(
            ids["exam"], subject_id=ids["root"],
            tag_ids=[ids["a"], ids["b"]], match="all"),
        "dashboard, untagged": db.get_difficulty_time_quadrants(
            ids["exam"], untagged=True),
    }
    buckets = [b for b in DT_LINK_BUCKETS if b != "unsplit"]
    for name, payload in payloads.items():
        assert payload["median"]["available"], f"{name}: fixture has no split"
        lean = {k: payload[k] for k in ("scope", "median", "selection")}
        js = json.loads(wimi_page.eval_js(
            f"JSON.stringify({json.dumps(buckets)}.map(b =>"
            f" WimiDifficultyTimeLinks.paramsFor({json.dumps(lean)}, b)))"))
        python = [dt_entry_browser_params(payload, b) for b in buckets]
        assert js == python, f"{name}: the two link builders disagree"

    payload = payloads["dashboard, any"]
    seen_nonzero = 0
    for bucket in buckets:
        wimi_page.eval_js("window.__w898_old_document = true")
        wimi_page.goto("entry-browser",
                       query=dt_entry_browser_params(payload, bucket))
        assert poll(wimi_page, SETTLED, timeout_ms=20000), bucket
        shown = wimi_page.eval_js("entryBrowser.totalEntries")
        expected = _count(payload, bucket)
        assert shown == expected, (
            f"{bucket}: the card shows {expected}, its link opens on {shown}")
        seen_nonzero += expected > 0
    assert seen_nonzero == len(buckets), "a bucket was empty; parity on 0"
