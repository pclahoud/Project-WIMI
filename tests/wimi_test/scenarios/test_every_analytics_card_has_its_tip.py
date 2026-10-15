"""Regression: every analytics card carries its tip, and the tip opens (#825).

Owner, 2026-10-14: *"would it be possible to add hover tip buttons to each
diagram"*; the text below was shown and approved (*"this is good"*), with the
four count cards at the top left out (*"no need"*). Study Recommendations'
first sentence follows #824's fix, as recorded on #825, and the weight card's
states the over-representation rule, as the owner asked on #827.

This pins the approved words, so changing one is a visible edit here. Each
tip is opened the way a keyboard user opens it -- focus -- and must show its
own text, inside the window, while its aria-label says the same thing.

Seeded with the analytics tour's exam, which draws every card on the page.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.analytics_tour_seed import seed_analytics_tour_exam
from _helpers.anki_settings import poll_true
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

TIPS = {
    'analytics-sunburst-total-info': "The centre counts your entries. Each segment is a branch of your subject tree, sized by every mistake in it. A subject filed under two parents counts under both, so the segments add up to more than the centre. Click a segment to zoom in.",
    'analytics-info-mistake-type': "Your five most-used error types. The centre counts entries with at least one error type. An entry can have several, so the segments add up to more. Error types are optional, so this shows how you tagged, not every mistake.",
    'analytics-info-cross-dimension': "Each cell counts the entries tagged with both subjects. Colours are relative to the busiest cell on screen, so the reddest cell is the worst one here, not a fixed number. Grey means no entries. Click a cell to see those entries, or a heading to go one level down.",
    'analytics-info-recommendations': "Ranks the cells of the diagram above that have at least 2 entries. A pair ranks higher the more of your mistakes it holds, the more the exam weights it, and the harder you rated those questions. A subject with no weight is ranked as if it were 5%.",
    'analytics-info-activity': "Entries per day over the period you pick. Each entry is dated by its session's Date Encountered, so this shows when you practised, not when you typed.",
    'analytics-info-study-activity': "One square per day for 16 weeks, darker for more entries. The darkest square is your busiest day in this view, not a fixed number. The streaks count all time; Active Days counts only the 16 weeks shown.",
    'analytics-info-goal': "The only card that counts finished entries only. It shows how many drafts are still to finish.",
    'analytics-info-difficulty': "How you rated the questions you got wrong. Entries you didn't rate are left out. Many mistakes on easy questions usually points to something other than missing knowledge.",
    'analytics-info-insights': "Up to five things WIMI noticed, warnings first. Each one names a subject or number you can check on another card.",
    'analytics-info-interaction': "Pairs from your first two dimensions whose mistakes differ from what each dimension's own totals predict. Expected is arithmetic, not a target. The severity word is only the size of the gap, so a pair with one entry can read High.",
    'analytics-info-banks': "Entries per question bank, dated by the day you typed them, over about the last six months. Trend compares counts, not rates, so doing fewer questions from a bank reads as Better.",
    'analytics-info-weight': "Compares your share of mistakes in each subject with the exam's weight for it. A subject's mistakes include everything beneath it. A subject is over-represented when your share is above 1.3 times the middle of its weight band, outside the band, and it has at least the minimum number of mistakes set in Settings (3 to start with). Over-represented subjects worth 10% or more are Priority; lighter ones rank below them, even ones you miss often. It counts mistakes, not your accuracy, so it reads true when you practise mixed blocks: blocks filtered to one subject inflate that subject, and a subject you have not practised shows no mistakes.",
    'analytics-info-weight-sources': "Where your subjects' weights came from. It describes your data and changes no number on this page.",
}

_OPEN = """(() => {
    const icon = document.querySelector('[data-testid="%s"]');
    if (!icon) return JSON.stringify({missing: true});
    icon.scrollIntoView({block: 'center'});
    icon.focus();
    const tip = icon.querySelector('.card-info-tooltip');
    const r = tip.getBoundingClientRect();
    return JSON.stringify({
        focused: document.activeElement === icon,
        shown: getComputedStyle(tip).display !== 'none' && r.width > 0 && r.height > 0,
        inside: r.left >= 0 && r.right <= window.innerWidth,
        label: icon.getAttribute('aria-label'),
        text: tip.textContent,
    });
})()"""


@pytest.mark.slow
@pytest.mark.regression
def test_every_card_has_its_approved_tip_and_it_opens_on_focus(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    query = seed_analytics_tour_exam(wimi_session.user.db, 'Tips')
    wimi_page.goto('analytics', query=query)
    assert poll_true(
        wimi_page, "!!document.querySelector('[data-tour-anchor=\"analytics-weight-sources\"]')",
        timeout_ms=30000), 'the Weight Sources card never drew, so not every card was reached'

    drawn = set(json.loads(wimi_page.eval_js(
        "JSON.stringify(Array.from(document.querySelectorAll('.card-info-icon'))"
        ".map(e => e.dataset.testid))")))
    assert drawn == set(TIPS), (
        f'tips without approved text: {sorted(drawn - set(TIPS))}; '
        f'cards without a tip: {sorted(set(TIPS) - drawn)}')

    faults = {}
    for testid, text in TIPS.items():
        got = json.loads(wimi_page.eval_js(_OPEN % testid))
        wrong = [k for k in ('focused', 'shown', 'inside') if not got.get(k)]
        if got.get('label') != text or got.get('text') != text:
            wrong.append(f"text {got.get('text')!r}")
        if wrong:
            faults[testid] = wrong
    assert not faults, faults
