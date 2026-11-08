"""Regression: the dashboard's difficulty and time card shows the right
counts, accounts for every mistake, and its quadrants land the entry browser
on the number they show (#898 Wave 2).

Seeded by hand so every figure is known. Fourteen mistakes, twelve of them
timed, so the median is the mean of 50 and 60 = 55 s ("under 55 s" / "55 s or
more"):

* hard and fast 2, hard and slow 3, easy and fast 3, easy and slow 1 -- 9
  placed;
* rated 3 and timed: 2, the middle line;
* not placed: 3 (no rating, no time, and a stored time of 0).

The **negative control** adds one rated-3 mistake at 55 s, which leaves the
median where it is: only the middle line may move, and the four quadrants
and the not-placed line must not. A card that counted the middle band into a
quadrant, or into "not placed", fails here.

The **too-few case** is a second exam with three timed mistakes, under the
minimum of 10: no quadrants, one unsplit block, and a sentence saying why.

No positions are asserted: offscreen and native viewports differ (CLAUDE.md).

Fails on master ``4a09d5a``, where the card does not exist: the first poll
for ``[data-testid="analytics-difficulty-time"]`` times out.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

CARD = '[data-testid="analytics-difficulty-time"]'
DRAWN = ("typeof dashboard !== 'undefined' && dashboard.isReady === true"
         " && !window.__w898_old_document"
         f" && !!document.querySelector('{CARD}')"
         f" && !!document.querySelector('{CARD}').dataset.state")
BROWSER_SETTLED = (
    "typeof entryBrowser !== 'undefined' && entryBrowser.isPageReady"
    " && entryBrowser.totalEntries >= 0"
    " && document.getElementById('loadingState').style.display === 'none'")

READ = """(() => {
    const card = document.querySelector('%s');
    const t = id => {
        const n = card.querySelector('[data-testid="analytics-difficulty-time-' + id + '"]');
        return n ? n.textContent.replace(/\\s+/g, ' ').trim() : null;
    };
    return JSON.stringify({
        state: card.dataset.state,
        counts: Object.fromEntries(['hard_fast', 'hard_slow', 'easy_fast', 'easy_slow', 'unsplit']
            .map(b => [b, t('count-' + b)])),
        middle: t('line-middle'),
        not_placed: t('line-not_placed'),
        accounting: t('accounting'),
        too_few: t('too-few'),
        grid: t('grid'),
        hard_slow: t('quadrant-hard_slow'),
        hard_slow_types: Array.from(card.querySelectorAll(
            '[data-testid="analytics-difficulty-time-quadrant-hard_slow"] .dt-type'))
            .map(li => li.children[0].textContent + '=' + li.children[1].textContent),
    });
})()""" % CARD


def _seed(db, name: str, rows) -> dict:
    exam = db.create_exam_context(exam_name=name, exam_description="#898 W2")
    subject = db.create_subject_node(exam.exam_name, f"{name} Subject", "System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=40, total_incorrect=40,
        session_name=name, date_encountered=date.today())
    tags = {t: db.create_tag(exam.exam_name, f"{name} {t}").id for t in "AB"}
    for d, t, carried in rows:
        db.create_question_entry(
            session.id, "A", "B", perceived_difficulty=d,
            time_spent_seconds=t, reflection="r", explanation="e",
            primary_subject_ids=[subject.id],
            tag_ids=[tags[c] for c in carried])
    db.conn.commit()
    return {"exam": exam.id, "session": session.id, "subject": subject.id}


SPLIT_ROWS = [
    (5, 20, "A"), (4, 30, ""),                     # hard and fast
    (4, 100, "A"), (5, 120, "AB"), (4, 90, "B"),   # hard and slow
    (1, 10, "B"), (2, 25, ""), (2, 15, "A"),       # easy and fast
    (1, 200, "A"),                                 # easy and slow
    (3, 50, "A"), (3, 60, ""),                     # middle
    (None, 70, "A"), (4, None, ""), (2, 0, "B"),   # not placed
]


def _read(page: WimiPage, exam: int) -> dict:
    page.eval_js("window.__w898_old_document = true")
    page.goto("analytics", query={"exam": exam})
    assert poll(page, DRAWN, timeout_ms=30000), "the difficulty and time card never drew"
    return json.loads(page.eval_js(READ))


@pytest.mark.slow
@pytest.mark.regression
def test_counts_footer_and_a_quadrant_click_landing(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    ids = _seed(db, "W898C", SPLIT_ROWS)

    got = _read(wimi_page, ids["exam"])
    assert got["state"] == "split", got
    assert got["counts"] == {"hard_fast": "2", "hard_slow": "3", "easy_fast": "3",
                             "easy_slow": "1", "unsplit": None}, got
    assert "under 55 s" in got["grid"] and "55 s or more" in got["grid"], got["grid"]
    assert got["middle"].startswith(
        "Rated 3: 2 mistakes sit in the middle, neither hard nor easy"), got["middle"]
    assert got["not_placed"].startswith(
        "Not placed: 3 mistakes have no difficulty rating or no time spent."), got["not_placed"]
    assert got["accounting"].startswith("9 of 14 mistakes placed."), got["accounting"]
    assert "2 placed mistakes have no error type." in got["accounting"], got["accounting"]
    # Hard and slow carries A twice and B twice: both listed, tie broken by name.
    assert "33% of placed mistakes" in got["hard_slow"], got["hard_slow"]
    assert got["hard_slow_types"] == ["W898C A=2", "W898C B=2"], got["hard_slow_types"]
    assert got["too_few"] is None

    # A real click on a quadrant lands the entry browser on the shown number.
    wimi_page.locator(css=f'{CARD} [data-testid="analytics-difficulty-time-quadrant-hard_slow"]').click()
    assert poll(wimi_page, "location.pathname.endsWith('entry_browser.html')", timeout_ms=20000)
    assert poll(wimi_page, BROWSER_SETTLED, timeout_ms=20000)
    assert wimi_page.eval_js("entryBrowser.totalEntries") == 3

    # Negative control: one more rated-3 mistake at the median moves the
    # middle line and nothing else.
    db.create_question_entry(
        ids["session"], "A", "B", perceived_difficulty=3, time_spent_seconds=55,
        reflection="r", explanation="e", primary_subject_ids=[ids["subject"]])
    db.conn.commit()
    after = _read(wimi_page, ids["exam"])
    assert after["counts"] == got["counts"], after
    assert after["not_placed"] == got["not_placed"], after
    assert after["middle"].startswith("Rated 3: 3 mistakes sit in the middle"), after["middle"]
    assert after["accounting"].startswith("9 of 15 mistakes placed."), after["accounting"]


@pytest.mark.slow
@pytest.mark.regression
def test_too_few_timed_mistakes_show_one_unsplit_block_and_say_why(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    ids = _seed(wimi_session.user.db, "W898F",
                [(5, 20, "A"), (1, 30, ""), (3, 40, "B"), (None, None, "")])
    got = _read(wimi_page, ids["exam"])
    assert got["state"] == "unsplit", got
    assert got["grid"] is None, "quadrants drawn without a median to split at"
    assert got["counts"]["unsplit"] == "2", got
    assert "at least 10 mistakes with a time spent" in got["too_few"], got["too_few"]
    assert "This exam has 3 so far" in got["too_few"], got["too_few"]
    assert got["middle"].startswith("Rated 3: 1 mistake sits in the middle"), got["middle"]
    assert got["not_placed"].startswith("Not placed: 1 mistake has no"), got["not_placed"]
