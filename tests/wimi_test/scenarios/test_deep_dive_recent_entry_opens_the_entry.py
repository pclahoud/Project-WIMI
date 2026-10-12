"""Regression: a deep dive's Recent Entries row opens that entry (#464).

Each row is `role="button"` with `tabindex="0"` and both a click and an
Enter/Space handler -- and the handler was `console.log('View entry:', id)`
under `// TODO: Navigate to entry detail view`. So five things announced as
buttons did nothing when pressed, and Space was swallowed by
`preventDefault` as well: #174's rule reached through a role instead of copy.

The destination is the one the TODO names and the one every other route to
a single entry already uses: `entry_detail.html?id=<entry>&exam=<exam>`
(`entry_browser.js`, `question_entry.js`). The payload already carries
`entry_id`.

Driven with real input only: a hit-tested CDP mouse click, and real Enter and
Space key events through `Input.dispatchKeyEvent` on the focused row. An
`el.click()` would pass against a row with no handler wiring a keyboard user
can reach. Each test asserts the navigation by what the NEXT page shows --
the seeded entry's own answer text on `entry_detail.html` -- not by the URL
alone.

The entry page reads a prev/next list from `sessionStorage.entryNavContext`,
written by the entry browser. A list left there from an earlier browse would
otherwise give an entry opened from here a stale "N of M" bar, so the row
clears it; the click test plants such a list first and asserts no bar.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.a11y import real_key
from _helpers.w114_form_ready import (
    centre_of, poll, real_click,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

ANSWERS = ("W464 first answer", "W464 second answer")


@pytest.fixture
def seeded(wimi_session: WimiTestSession) -> dict:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W464 Exam", exam_description="#464")
    node = db.create_subject_node(
        exam_context=exam.exam_name, name="Nephrology", level_type="System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=2, total_incorrect=2,
        session_name="W464", date_encountered=date.today())
    ids = []
    for answer in ANSWERS:
        entry = db.create_question_entry(
            review_session_id=session.id, user_answer=answer,
            correct_answer="B", reflection=f"reflection for {answer}",
            primary_subject_ids=[node.id])
        ids.append(entry.id)
    db.conn.commit()
    return {"exam": exam.id, "subject": node.id, "entries": ids}


def _open_deep_dive(page: WimiPage, seeded: dict) -> None:
    page.goto("subject-deep-dive",
              query={"subject": seeded["subject"], "exam": seeded["exam"]})
    selector = f'[data-testid="deep-dive-recent-entry-{seeded["entries"][0]}"]'
    assert poll(page, "!!document.querySelector(%s)" % json.dumps(selector),
                timeout_ms=15000), "the Recent Entries rows never rendered"


def _assert_opened(page: WimiPage, seeded: dict, entry_id: int, how: str) -> None:
    landed = poll(page, "location.pathname.endsWith('/entry_detail.html')",
                  timeout_ms=10000)
    assert landed, (
        f"{how} on a Recent Entries row left the page at "
        f"{page.eval_js('location.href')!r}; the row is announced as a button "
        f"and its handler navigates nowhere -- #464")
    params = json.loads(page.eval_js(
        "JSON.stringify(Object.fromEntries(new URLSearchParams(location.search)))"))
    assert params.get("id") == str(entry_id), f"opened the wrong entry: {params}"
    assert params.get("exam") == str(seeded["exam"]), f"exam not carried: {params}"
    answer = ANSWERS[seeded["entries"].index(entry_id)]
    shown = poll(page, "(document.getElementById('user-answer')||{}).textContent"
                       " && document.getElementById('user-answer').textContent"
                       ".includes(%s)" % json.dumps(answer), timeout_ms=10000)
    assert shown, f"entry_detail.html never showed {answer!r} for entry {entry_id}"


def _focus_row(page: WimiPage, entry_id: int) -> None:
    ok = page.eval_js(
        "(() => { const el = document.querySelector("
        "'[data-testid=\"deep-dive-recent-entry-%d\"]'); if (!el) return false;"
        " el.focus(); return document.activeElement === el; })()" % entry_id)
    assert ok is True, "the row could not take focus, so no key can reach it"


@pytest.mark.slow
@pytest.mark.regression
def test_clicking_a_row_opens_that_entry(wimi_page: WimiPage, seeded: dict) -> None:
    _open_deep_dive(wimi_page, seeded)
    # A list an earlier entry-browser visit could have left behind.
    wimi_page.eval_js(
        "sessionStorage.setItem('entryNavContext', JSON.stringify("
        "{ids: [990, 991, 992], index: 1, total: 3}))")
    target = seeded["entries"][1]
    real_click(wimi_page, centre_of(
        wimi_page, f'[data-testid="deep-dive-recent-entry-{target}"]'))
    _assert_opened(wimi_page, seeded, target, "A click")
    page_settled = poll(wimi_page, "!!(window.entryDetail && window.entryDetail.entry)",
                        timeout_ms=10000)
    assert page_settled, "entry_detail never finished loading the entry"
    nav = wimi_page.eval_js(
        "getComputedStyle(document.querySelector('.entry-navigation')).display")
    assert nav == "none", (
        f"the entry page drew a prev/next bar ({nav!r}) from a list the deep "
        f"dive never built")


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("key", ["Enter", " "], ids=["enter", "space"])
def test_a_key_on_a_focused_row_opens_that_entry(
    wimi_page: WimiPage, seeded: dict, key: str,
) -> None:
    _open_deep_dive(wimi_page, seeded)
    target = seeded["entries"][0]
    _focus_row(wimi_page, target)
    real_key(wimi_page, key)
    _assert_opened(wimi_page, seeded, target, f"{key!r}")
