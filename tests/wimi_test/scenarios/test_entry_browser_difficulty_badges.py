"""Regression: entry browser cards render no difficulty badge for 4 and 5.

Forgejo issue #10 -- "[bug] Entry browser: difficulty 4 renders no badge":

    Entry cards with ``perceived_difficulty = 4`` render with an empty
    space where the difficulty badge belongs. Difficulty 2 shows
    ``Medium`` and 3 shows ``Hard`` on neighbouring cards in the same
    grid. [...] The column accepts 1-5 and the entry form offers all five
    as buttons, so all five need labels. [...] Not read back from the
    DOM, so I have not confirmed whether 1 and 5 are also blank.

This scenario seeds all five difficulties at once and reports every
blank, so the answer is in the failure message rather than in a
follow-up investigation.

Why it failed: ``createEntryCard`` in ``entry_browser.js`` looked the
label up in ``{ 1: 'Easy', 2: 'Medium', 3: 'Hard' }`` and fell back to
``''``. The map covers three of the five values the column accepts, so 4
and 5 produced an empty badge -- an element with padding and a radius
but no text and, because ``browser.css`` only styled
``[data-difficulty]`` 1 to 3, no pill either.

What the fix changes: the browser's map is completed from the mapping the
entry *detail* page already carries (``renderDifficultyBadge``,
``entry_detail.js``), which is the one that covers all five; ``browser.css``
gains the two missing swatches using the same error palette detail gives
``very-hard``.

Since #46 neither surface carries a map of its own: both read
``window.WimiDifficulty`` (``js/difficulty.js``) and paint from
``css/difficulty.css``. The words below therefore changed -- 4 and 5 no
longer collide, and the scale reads one step lower -- but nothing in this
file names a word, so it pins the two surfaces together whatever the
vocabulary is. ``test_difficulty_labels_match_entry_form.py`` is what
pins that vocabulary to the entry form's buttons.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

DIFFICULTIES = [1, 2, 3, 4, 5]
CARD_COUNT = "document.querySelectorAll('#entryGrid [data-entry-id]').length"

# One row per card: the difficulty it carries, the badge's text, whether the
# badge is displayed at all, and whether it has a painted background.
BADGES = """
(() => JSON.stringify(
  Array.from(document.querySelectorAll('#entryGrid [data-entry-id]')).map(card => {
    const b = card.querySelector('.difficulty-badge');
    if (!b) return { difficulty: null, text: null, shown: false, painted: false };
    const cs = getComputedStyle(b);
    const bg = cs.backgroundColor;
    return {
      difficulty: b.dataset.difficulty ? Number(b.dataset.difficulty) : null,
      text: b.textContent.trim(),
      shown: cs.display !== 'none',
      painted: bg !== 'transparent' && bg !== 'rgba(0, 0, 0, 0)'
    };
  })
))()
"""


def _poll(wimi_page: WimiPage, js: str, want, *, timeout_ms: int = 10000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last == want:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed(db) -> None:
    """One entry per difficulty the column accepts."""
    exam = db.create_exam_context(exam_name='Difficulty Exam', exam_description='')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10,
        total_incorrect=len(DIFFICULTIES), session_name='Difficulty session',
        date_encountered=date.today(),
    )
    for difficulty in DIFFICULTIES:
        db.create_question_entry(
            review_session_id=session.id, user_answer='a', correct_answer='b',
            perceived_difficulty=difficulty,
            reflection=f'<p>Seeded at difficulty {difficulty}</p>',
        )


@pytest.mark.slow
@pytest.mark.regression
def test_every_valid_difficulty_renders_a_badge(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto('entry-browser')
    cards = _poll(wimi_page, CARD_COUNT, len(DIFFICULTIES))
    assert cards == len(DIFFICULTIES), f'Expected {len(DIFFICULTIES)} cards, got {cards!r}'
    badges = json.loads(wimi_page.eval_js(BADGES))
    by_difficulty = {b['difficulty']: b for b in badges}

    # ---- Assert: all five, checked together --------------------------
    assert sorted(by_difficulty) == DIFFICULTIES, (
        f'Cards did not carry one of each difficulty: {badges!r}'
    )
    blank = sorted(d for d, b in by_difficulty.items() if not b['text'])
    assert not blank, (
        f'Difficulties {blank} render an empty difficulty badge: {badges!r}. '
        'The label lookup in createEntryCard covers a narrower range than the '
        'column accepts and falls back to an empty string.'
    )
    for difficulty, badge in sorted(by_difficulty.items()):
        assert badge['shown'], f'Difficulty {difficulty} badge is hidden: {badge!r}'
        # An unstyled badge is text floating where a pill belongs -- the
        # reporter's "empty space" symptom in its other form.
        assert badge['painted'], (
            f'Difficulty {difficulty} badge has no background: {badge!r}. '
            'browser.css styles [data-difficulty] 1-3 only.'
        )


@pytest.mark.slow
@pytest.mark.regression
def test_browser_labels_match_the_entry_detail_page(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The card and the detail page must not disagree about one entry.

    Two mappings existed; the detail page's is the complete one, so the
    card was completed from it rather than from a third invention. This
    pins them together so they cannot drift apart again -- and since #46
    there is only one mapping for them to drift from.
    """
    _seed(wimi_session.user.db)
    wimi_page.goto('entry-browser')
    assert _poll(wimi_page, CARD_COUNT, len(DIFFICULTIES)) == len(DIFFICULTIES)

    cards = json.loads(wimi_page.eval_js(
        "(() => JSON.stringify(Array.from("
        "document.querySelectorAll('#entryGrid [data-entry-id]')).map(c => ({"
        " id: c.dataset.entryId,"
        " text: c.querySelector('.difficulty-badge').textContent.trim() }))))()"
    ))

    # Page.navigate returns before the new document commits, so mark the old
    # one and wait for a fresh document carrying a rendered badge.
    ready = (
        "(() => { const b = document.getElementById('difficulty-badge');"
        " return typeof window.__wimiPrevDoc === 'undefined'"
        " && !!b && b.textContent.trim() !== ''; })()"
    )
    for card in cards:
        wimi_page.eval_js("window.__wimiPrevDoc = true")
        wimi_page.goto('entry-detail', query={'id': card['id']})
        assert _poll(wimi_page, ready, True) is True, (
            f"Entry {card['id']}: the detail page never rendered a difficulty badge"
        )
        shown = wimi_page.eval_js(
            "document.getElementById('difficulty-badge').textContent.trim()"
        )
        assert shown == card['text'], (
            f"Entry {card['id']}: the browser card says {card['text']!r} but the "
            f'detail page says {shown!r}. The two difficulty mappings disagree.'
        )
