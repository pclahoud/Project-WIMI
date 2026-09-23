"""Regression: the difficulty scale reads differently on every surface.

Forgejo issue #46 -- "[bug] Difficulty labels disagree across three
surfaces":

    ``perceived_difficulty`` is a 1-5 scale, and three surfaces put
    different words on the same number. [...] a student who records a
    question as **"Medium"** (button 3, tooltip "Medium") opens it later
    and reads **"Hard"** on both the card and the detail page. [...]
    There is a second, smaller oddity in the display mapping: **4 and 5
    both render "Very Hard"**, so the top two steps of a five-point scale
    are indistinguishable once an entry is saved.

The owner decided Option B on 2026-09-14: the entry form's vocabulary
(1 Very Easy, 2 Easy, 3 Medium, 4 Hard, 5 Very Hard) is the correct one,
and the two display surfaces adopt it.

Why it failed: ``entry_detail.js`` and ``entry_browser.js`` each carried
their own literal ``{1: 'Easy', 2: 'Medium', 3: 'Hard', 4: 'Very Hard',
5: 'Very Hard'}``, shifted one step from the ``title`` attributes on
``.difficulty-dot`` in ``question_entry.html``.

What the fix changes: one shared definition (``src/web/js/difficulty.js``)
that both display surfaces read, carrying the entry form's words; and the
scale's two CSS encodings (the ``::before`` dots and the badge swatches)
move with it into ``src/web/css/difficulty.css`` so five steps look like
five steps.

This scenario reads the entry form's tooltips *from the form* rather than
hard-coding them, so it pins the display surfaces to whatever the form
offers. That is what stops a fourth vocabulary appearing.

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
DOT_COUNT = "document.querySelectorAll('#difficulty-rating .difficulty-dot').length"

# The entry form's own vocabulary: value -> tooltip, straight off the buttons.
FORM_TOOLTIPS = """
(() => JSON.stringify(Object.fromEntries(
  Array.from(document.querySelectorAll('#difficulty-rating .difficulty-dot'))
    .map(b => [b.dataset.value, (b.getAttribute('title') || '').trim()])
)))()
"""

# One row per card: entry id, the difficulty it carries, the badge's word,
# the CSS dot indicator and the colour the swatch paints it.
CARDS = """
(() => JSON.stringify(
  Array.from(document.querySelectorAll('#entryGrid [data-entry-id]')).map(card => {
    const b = card.querySelector('.difficulty-badge');
    const cs = getComputedStyle(b);
    return {
      id: card.dataset.entryId,
      difficulty: b.dataset.difficulty ? Number(b.dataset.difficulty) : null,
      text: b.textContent.trim(),
      color: cs.color,
      background: cs.backgroundColor
    };
  })
))()
"""

DETAIL_BADGE = """
(() => {
  const b = document.getElementById('difficulty-badge');
  if (!b) return null;
  return JSON.stringify({
    text: b.textContent.trim(),
    dots: getComputedStyle(b, '::before').content,
    color: getComputedStyle(b).color
  });
})()
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


def _seed(db) -> int:
    """One entry per difficulty the column accepts. Returns the session id."""
    exam = db.create_exam_context(exam_name='Vocabulary Exam', exam_description='')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10,
        total_incorrect=len(DIFFICULTIES), session_name='Vocabulary session',
        date_encountered=date.today(),
    )
    for difficulty in DIFFICULTIES:
        db.create_question_entry(
            review_session_id=session.id, user_answer='a', correct_answer='b',
            perceived_difficulty=difficulty,
            reflection=f'<p>Seeded at difficulty {difficulty}</p>',
        )
    return session.id


def _read_form_vocabulary(wimi_page: WimiPage, session_id: int) -> dict[int, str]:
    wimi_page.goto('entry-form', query={'session_id': session_id})
    assert _poll(wimi_page, DOT_COUNT, len(DIFFICULTIES)) == len(DIFFICULTIES), (
        'The entry form never rendered its five difficulty buttons'
    )
    raw = json.loads(wimi_page.eval_js(FORM_TOOLTIPS))
    vocabulary = {int(value): label for value, label in raw.items()}
    assert sorted(vocabulary) == DIFFICULTIES, f'Unexpected buttons: {raw!r}'
    assert all(vocabulary.values()), f'A difficulty button has no tooltip: {raw!r}'
    return vocabulary


def _read_cards(wimi_page: WimiPage) -> list[dict]:
    wimi_page.goto('entry-browser')
    assert _poll(wimi_page, CARD_COUNT, len(DIFFICULTIES)) == len(DIFFICULTIES), (
        'The entry browser never rendered one card per difficulty'
    )
    return json.loads(wimi_page.eval_js(CARDS))


# The detail page commits its document after Page.navigate returns, so mark
# the old one and wait for a fresh document carrying a rendered badge.
_DETAIL_READY = (
    "(() => { const b = document.getElementById('difficulty-badge');"
    " return typeof window.__wimiPrevDoc === 'undefined'"
    " && !!b && b.textContent.trim() !== ''; })()"
)


def _read_detail(wimi_page: WimiPage, entry_id: str) -> dict:
    wimi_page.eval_js('window.__wimiPrevDoc = true')
    wimi_page.goto('entry-detail', query={'id': entry_id})
    assert _poll(wimi_page, _DETAIL_READY, True) is True, (
        f'Entry {entry_id}: the detail page never rendered a difficulty badge'
    )
    return json.loads(wimi_page.eval_js(DETAIL_BADGE))


@pytest.mark.slow
@pytest.mark.regression
def test_display_labels_match_the_entry_form_tooltips(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The word offered at recording time is the word read back.

    Read value by value, against the form's own tooltips rather than a
    literal list, so the three surfaces cannot drift apart again.
    """
    # ---- Arrange -----------------------------------------------------
    session_id = _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    vocabulary = _read_form_vocabulary(wimi_page, session_id)
    cards = _read_cards(wimi_page)
    by_difficulty = {c['difficulty']: c for c in cards}

    # ---- Assert ------------------------------------------------------
    assert sorted(by_difficulty) == DIFFICULTIES, (
        f'Cards did not carry one of each difficulty: {cards!r}'
    )
    browser_disagrees = {
        d: (by_difficulty[d]['text'], vocabulary[d])
        for d in DIFFICULTIES if by_difficulty[d]['text'] != vocabulary[d]
    }
    assert not browser_disagrees, (
        'The entry browser renders a different word than the button the student '
        f'clicked. value: (card, form tooltip) = {browser_disagrees!r}'
    )

    for difficulty in DIFFICULTIES:
        detail = _read_detail(wimi_page, by_difficulty[difficulty]['id'])
        assert detail['text'] == vocabulary[difficulty], (
            f'Difficulty {difficulty}: the entry form offers '
            f'{vocabulary[difficulty]!r} but the detail page reads back '
            f"{detail['text']!r}."
        )


@pytest.mark.slow
@pytest.mark.regression
def test_the_five_steps_are_visibly_distinct(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Five labels need five swatches, or 3/4/5 still look alike.

    Before the fix 4 and 5 shared the word "Very Hard" and, on both
    surfaces, the error palette that 3 also used -- so the top three steps
    of a five-point scale were indistinguishable by colour.
    """
    session_id = _seed(wimi_session.user.db)
    vocabulary = _read_form_vocabulary(wimi_page, session_id)
    assert len(set(vocabulary.values())) == len(DIFFICULTIES), (
        f'The entry form itself does not offer five distinct words: {vocabulary!r}'
    )

    cards = {c['difficulty']: c for c in _read_cards(wimi_page)}
    swatches = {d: cards[d]['color'] for d in DIFFICULTIES}
    assert len(set(swatches.values())) == len(DIFFICULTIES), (
        f'Entry browser swatches do not distinguish five steps: {swatches!r}. '
        'browser.css gave [data-difficulty] 3, 4 and 5 the same error palette.'
    )

    dots = {}
    for difficulty in DIFFICULTIES:
        detail = _read_detail(wimi_page, cards[difficulty]['id'])
        dots[difficulty] = detail['dots']
    assert len(set(dots.values())) == len(DIFFICULTIES), (
        f'The detail page dot indicators do not show five steps: {dots!r}. '
        'detail.css encodes the scale a second time as ::before content.'
    )
