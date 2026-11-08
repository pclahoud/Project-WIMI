"""Regression: the difficulty and time card on the subject deep dive counts
the page's own mistakes, moves with the parent context, and lands the entry
browser on the number it shows (#898 Wave 4).

Seeded on a polyhierarchy so the parent context means something:
Hypertension sits under Cardiovascular (primary edge) and Pregnancy, with
Emergency beneath it. Thirteen timed mistakes on the exam, so the exam-wide
median is the 7th, 50 s ("under 50 s" / "50 s or more").

On Hypertension, every parent (10 mistakes):

* hard and fast 2 -- (5, 20 s) no context, (5, 30 s) via Cardiovascular;
* hard and slow 4 -- (4, 100 s) none, (4, 90 s) and (5, 110 s) via Pregnancy,
  (4, 200 s) on Emergency, a primary descendant;
* easy and fast 2, easy and slow 1, rated 3 one.

Shown as part of Cardiovascular the three Pregnancy-context mistakes drop
out: 7, with hard and slow 2.

The **negative control** is a hard and fast mistake (5, 25 s) whose main
subject is another one and which carries Hypertension only as a SECONDARY
subject. The entry browser's ordinary subject filter (the finding rule, #13)
would include it; the deep dive totals mistakes, so it is primary only. It
must be absent from the card (hard and fast reads 2, not 3) and from the
browser the quadrant opens (checked by entry id, not only by count).

The tip is pinned word for word from the plan's "Tip text": no deep-dive tip
registry exists, so this file is it.

No positions are asserted: offscreen and native viewports differ (CLAUDE.md).

Fails on master ``26b3a18``, where the deep dive has no card: the first poll
for ``[data-testid="deep-dive-difficulty-time"]`` times out ("the card never
drew on the deep dive"), and the no-exam test finds no sentence.

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

TIP = ("The same four groups, for mistakes whose main subject is this one or a "
       "subject beneath it. Fast and slow use your median for the whole exam, so "
       "they mean the same here as on the dashboard.")

CARD = '[data-testid="deep-dive-difficulty-time"]'
SELECTOR = '[data-testid="multi-parent-selector-control"]'
BROWSER_SETTLED = (
    "typeof entryBrowser !== 'undefined' && entryBrowser.isPageReady"
    " && entryBrowser.totalEntries >= 0"
    " && document.getElementById('loadingState').style.display === 'none'")

READ = """(() => {
    const card = document.querySelector('%s');
    const t = id => {
        const n = card.querySelector('[data-testid="deep-dive-difficulty-time-' + id + '"]');
        return n ? n.textContent.replace(/\\s+/g, ' ').trim() : null;
    };
    const href = b => {
        const n = card.querySelector('[data-testid="deep-dive-difficulty-time-quadrant-' + b + '"]');
        return n ? n.getAttribute('href') : null;
    };
    return JSON.stringify({
        state: card.dataset.state,
        total: card.dataset.total,
        page_total: document.getElementById('totalMistakes').textContent.trim(),
        counts: Object.fromEntries(['hard_fast', 'hard_slow', 'easy_fast', 'easy_slow']
            .map(b => [b, t('count-' + b)])),
        grid: t('grid'),
        accounting: t('accounting'),
        hrefs: {hard_fast: href('hard_fast'), hard_slow: href('hard_slow')},
    });
})()""" % CARD

TIP_OPEN = """(() => {
    const icon = document.querySelector('[data-testid="deep-dive-info-difficulty-time"]');
    if (!icon) return JSON.stringify({missing: true});
    icon.scrollIntoView({block: 'center'});
    icon.focus();
    const tip = icon.querySelector('.card-info-tooltip');
    const r = tip.getBoundingClientRect();
    return JSON.stringify({
        focused: document.activeElement === icon,
        shown: getComputedStyle(tip).display !== 'none' && r.width > 0 && r.height > 0,
        positioned: getComputedStyle(tip).position === 'absolute',
        inside: r.left >= 0 && r.right <= window.innerWidth,
        label: icon.getAttribute('aria-label'),
        text: tip.textContent,
    });
})()"""


def _seed(db) -> dict:
    exam = db.create_exam_context(exam_name="W898D", exam_description="#898 W4")
    cardio = db.create_subject_node(exam.exam_name, "W898D Cardiovascular", "System")
    preg = db.create_subject_node(exam.exam_name, "W898D Pregnancy", "System")
    other = db.create_subject_node(exam.exam_name, "W898D Renal", "System")
    hyp = db.create_subject_node(exam.exam_name, "W898D Hypertension", "Topic",
                                 parent_id=cardio.id)
    db.add_edge(preg.id, hyp.id, is_primary=False)
    emerg = db.create_subject_node(exam.exam_name, "W898D Emergency", "Subtopic",
                                   parent_id=hyp.id)
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=40, total_incorrect=40,
        session_name="W898D", date_encountered=date.today())

    def entry(d, t, primary, ctx=None, secondary=None):
        e = db.create_question_entry(
            session.id, "A", "B", perceived_difficulty=d, time_spent_seconds=t,
            reflection="r", explanation="e", primary_subject_ids=[primary],
            secondary_subject_ids=secondary)
        if ctx is not None:
            db.execute(
                "UPDATE entry_subject_mappings SET primary_parent_id = ? "
                "WHERE question_entry_id = ? AND subject_node_id = ?",
                (ctx, e.id, primary))
        return e.id

    ids = {
        "hf_none": entry(5, 20, hyp.id),
        "hf_cardio": entry(5, 30, hyp.id, ctx=cardio.id),
    }
    entry(4, 100, hyp.id)
    entry(1, 15, hyp.id)
    entry(3, 50, hyp.id)
    entry(2, 120, hyp.id, ctx=cardio.id)
    entry(4, 90, hyp.id, ctx=preg.id)
    entry(5, 110, hyp.id, ctx=preg.id)
    entry(1, 10, hyp.id, ctx=preg.id)
    entry(4, 200, emerg.id)
    # The negative control: hard and fast, Hypertension only as secondary.
    ids["secondary_only"] = entry(5, 25, other.id, secondary=[hyp.id])
    entry(2, 60, other.id)
    entry(None, 40, other.id)
    db.conn.commit()
    return {"exam": exam.id, "hyp": hyp.id, "cardio": cardio.id, **ids}


def _read(page: WimiPage, expect_total: int) -> dict:
    drawn = (f"(() => {{ const c = document.querySelector('{CARD}');"
             f" const p = document.getElementById('totalMistakes');"
             f" return !!c && c.dataset.state === 'split'"
             f" && c.dataset.total === '{expect_total}'"
             f" && !!p && p.textContent.trim() === '{expect_total}'; }})()")
    if not poll(page, drawn, timeout_ms=30000):
        if not page.eval_js(f"!!document.querySelector('{CARD}')"):
            raise AssertionError("the card never drew on the deep dive")
        raise AssertionError(
            f"card and Total Mistakes never both read {expect_total}: {page.eval_js(READ)}")
    return json.loads(page.eval_js(READ))


def _land(page: WimiPage, bucket: str) -> tuple:
    page.locator(
        css=f'{CARD} [data-testid="deep-dive-difficulty-time-quadrant-{bucket}"]').click()
    assert poll(page, "location.pathname.endsWith('entry_browser.html')", timeout_ms=20000)
    assert poll(page, BROWSER_SETTLED, timeout_ms=20000)
    return (page.eval_js("entryBrowser.totalEntries"),
            json.loads(page.eval_js("JSON.stringify(entryBrowser.entries.map(e => e.id))")))


@pytest.mark.slow
@pytest.mark.regression
def test_the_card_counts_the_pages_mistakes_and_moves_with_the_context(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    ids = _seed(wimi_session.user.db)
    query = {"subject": ids["hyp"], "exam": ids["exam"]}
    wimi_page.goto("subject-deep-dive", query=query)

    # Every parent: the card's total is the Statistics total.
    got = _read(wimi_page, 10)
    assert got["total"] == got["page_total"] == "10", got
    assert got["counts"] == {"hard_fast": "2", "hard_slow": "4",
                             "easy_fast": "2", "easy_slow": "1"}, got
    assert "under 50 s" in got["grid"] and "50 s or more" in got["grid"], got["grid"]
    assert got["accounting"].startswith("9 of 10 mistakes placed."), got["accounting"]
    assert f"counted_subject={ids['hyp']}" in got["hrefs"]["hard_fast"], got["hrefs"]
    assert "counted_parent" not in got["hrefs"]["hard_fast"], got["hrefs"]

    # The tip, word for word, opened by keyboard focus.
    tip = json.loads(wimi_page.eval_js(TIP_OPEN))
    assert not tip.get("missing"), "the deep dive's card has no tip"
    assert tip["text"] == TIP and tip["label"] == TIP, tip
    assert tip["focused"] and tip["shown"] and tip["positioned"] and tip["inside"], (
        f"the tip did not open as a positioned tooltip on focus: {tip}")

    # Switching the parent context moves both totals together.
    assert poll(wimi_page, f"!!document.querySelector('{SELECTOR}')", timeout_ms=20000)
    wimi_page.eval_js(
        f"(() => {{ const s = document.querySelector('{SELECTOR}');"
        f" s.value = '{ids['cardio']}';"
        f" s.dispatchEvent(new Event('change', {{bubbles: true}})); }})()")
    cardio = _read(wimi_page, 7)
    assert cardio["total"] == cardio["page_total"] == "7", cardio
    assert cardio["counts"] == {"hard_fast": "2", "hard_slow": "2",
                                "easy_fast": "1", "easy_slow": "1"}, cardio
    href = cardio["hrefs"]["hard_slow"]
    assert (f"counted_subject={ids['hyp']}" in href
            and f"counted_parent={ids['cardio']}" in href), href

    # A quadrant under that context lands the browser on the shown number.
    total, _ = _land(wimi_page, "hard_slow")
    assert total == 2, f"hard and slow under Cardiovascular shows 2, the browser found {total}"

    # Back to every parent: hard and fast lands on exactly its 2, and the
    # secondary-only mistake is in neither the card nor the landing.
    wimi_page.goto("subject-deep-dive", query=query)
    again = _read(wimi_page, 10)
    assert again["counts"]["hard_fast"] == "2", again
    total, landed = _land(wimi_page, "hard_fast")
    assert total == 2 and sorted(landed) == sorted([ids["hf_none"], ids["hf_cardio"]]), (
        f"hard and fast landed on {total} entries {landed}; expected exactly "
        f"{[ids['hf_none'], ids['hf_cardio']]}")
    assert ids["secondary_only"] not in landed


@pytest.mark.slow
@pytest.mark.regression
def test_with_no_exam_the_card_is_not_drawn_and_a_sentence_says_why(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    ids = _seed(wimi_session.user.db)
    wimi_page.goto("subject-deep-dive", query={"subject": ids["hyp"]})
    note = '[data-testid="deep-dive-difficulty-time-no-exam"]'
    assert poll(wimi_page, f"!!document.querySelector('{note}')", timeout_ms=30000), (
        "no sentence explained the missing card")
    text = wimi_page.eval_js(f"document.querySelector('{note}').textContent")
    assert "opened without an exam" in text, text
    assert wimi_page.eval_js(f"!!document.querySelector('{CARD}')") is False
