"""Regression: the entry's Anki relevance proposals (#784 Wave 5, decision 14).

Five cards match the question. Two name what the entry is about -- one by the
subject's own name, one by an alias the student recorded -- and are proposed
with those words as the reason, on the card's own row (#815); the other three
are not. The student's answers:

- **Show first** moves that card to the top of this entry's list, marks it,
  and survives a reload. It changes nothing in Anki: the fake records no
  request at all after the proposals are drawn.
- **Never for <subject>** stops that card being proposed for that subject.
- The three answers are painted identically (decision 14: equal weight, no
  default), measured on the computed style rather than the class list.
- **Owner, #815: answers only when the proposals narrow the list** (at most
  half the cards). When nearly every card matches, the page says so in one
  sentence and draws no answers -- the second test, whose control is the
  first: the same seeding with two more matching cards is the only change.

**The card ids are real-size on purpose (#813).** An Anki card id is a
millisecond timestamp, far above 2**32. This scenario used 101-103 and passed
while the verdict slots declared a 32-bit ``int``, which QWebChannel wrapped,
so every real card was refused. Ids above 2**32 make the presses cross the
channel the way a real deck's do; with the slots back on ``int`` this fails.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.anki_entry import TPL, enable_anki, open_entry, status, wait_for_cards
from _helpers.anki_settings import poll, poll_true
from tests._fake_ankiconnect import FakeAnkiConnect
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PROPOSALS = "document.querySelectorAll('#anki-cards .anki-proposal').length"
ORDER = ("JSON.stringify(Array.from(document.querySelectorAll('#anki-cards article.anki-card'))"
         ".map(a => Number(a.dataset.cardId)))")
# Real-size Anki card ids (ms timestamps), all above 2**32 -- see the
# docstring. Made up: a round 2023 timestamp, not ids from anyone's collection.
C1, C2, C3, C4, C5 = (1700000000001, 1700000000002, 1700000000003,
                      1700000000004, 1700000000005)
assert min(C1, C2, C3, C4, C5) > 2 ** 32

STYLE = ("JSON.stringify(Array.from(document.querySelectorAll("
         f"'.anki-proposal[data-card-id=\"{C3}\"] .anki-proposal-action')).map(b => {{"
         " const s = getComputedStyle(b); return [s.fontWeight, s.fontSize, s.color,"
         " s.backgroundColor, s.borderTopColor, s.paddingTop]; }))")


def _seed(db) -> int:
    exam = db.create_exam_context(exam_name='Step X')
    bank = db.create_question_source(source_name='Bank', exam_context='Step X')
    db.anki_add_template(exam.id, bank.id, TPL)
    subject = db.create_subject_node('Step X', 'Aortic dissection', 'System')
    db.create_subject_alias(subject.id, 'Step X', 'Tearing aorta')
    session = db.create_review_session(exam_context_id=exam.id, total_questions=5,
                                       total_incorrect=1, question_source_id=bank.id)
    entry = db.create_question_entry(session.id, 'A', 'B', question_id='7',
                                     primary_subject_ids=[subject.id])
    return entry.id


def _stock(anki, *, all_match: bool = False) -> None:
    """Five cards, two matching. ``all_match`` makes C4 and C5 match too, so
    four of five are proposed and the proposals no longer narrow the list."""
    anki.searches['tag:Bank::7'] = [C1, C2, C3, C4, C5]
    anki.add_card(C1, note_id=10, deckName='Deck A',
                  fields={'Front': {'value': 'Aortic dissection: tearing pain', 'order': 0}})
    anki.add_card(C2, note_id=11, deckName='Deck A',
                  fields={'Front': {'value': 'Renal physiology', 'order': 0}})
    anki.add_card(C3, note_id=12, deckName='Deck B',
                  fields={'Front': {'value': 'A tearing aorta on imaging', 'order': 0}})
    extra = 'Aortic dissection in Marfan syndrome' if all_match else 'Nephron anatomy'
    anki.add_card(C4, note_id=13, deckName='Deck A',
                  fields={'Front': {'value': extra, 'order': 0}})
    extra = 'Aortic dissection: Stanford types' if all_match else 'Acid-base balance'
    anki.add_card(C5, note_id=14, deckName='Deck A',
                  fields={'Front': {'value': extra, 'order': 0}})


@pytest.mark.slow
@pytest.mark.regression
def test_proposals_show_first_and_never(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    entry_id = _seed(db)
    with FakeAnkiConnect() as anki:
        _stock(anki)
        enable_anki(wimi_page, anki.port)
        open_entry(wimi_page, entry_id)
        wait_for_cards(wimi_page, 5)
        assert poll(wimi_page, PROPOSALS, 2) == 2, status(wimi_page)
        anki.requests.clear()

        reasons = wimi_page.eval_js(
            "Array.from(document.querySelectorAll('#anki-cards .anki-proposal'))"
            ".map(p => p.innerText).join(' | ')")
        assert 'Aortic dissection (subject)' in reasons
        assert 'Tearing aorta (another name for Aortic dissection)' in reasons
        assert 'Renal physiology' not in reasons

        styles = json.loads(wimi_page.eval_js(STYLE))
        assert len(styles) == 3 and styles[0] == styles[1] == styles[2], styles

        # ---- Show first: C3 moves to the top and is marked
        wimi_page.locator(css=f'.anki-proposal[data-card-id="{C3}"] '
                              'button[data-action="confirm"]').click()
        assert poll_true(wimi_page, "document.getElementById('anki-status').textContent"
                                    " === 'Shown first for this entry.'"), status(wimi_page)
        assert json.loads(wimi_page.eval_js(ORDER)) == [C3, C1, C2, C4, C5]
        assert 'Shown first for this entry' in wimi_page.eval_js(
            f"document.querySelector('article.anki-card[data-card-id=\"{C3}\"]').innerText")
        assert wimi_page.eval_js(PROPOSALS) == 1
        assert wimi_page.eval_js("document.activeElement.dataset.action") == 'confirm', \
            'focus should move to the next proposal, not drop to the page'

        # ---- Never for the subject: C1 is no longer proposed
        wimi_page.locator(css=f'.anki-proposal[data-card-id="{C1}"] '
                              'button[data-action="never"]').click()
        assert poll_true(wimi_page, "document.getElementById('anki-status').textContent"
                                    ".startsWith('WIMI will not propose this card for')")
        assert wimi_page.eval_js(PROPOSALS) == 0
        assert wimi_page.eval_js(
            "document.querySelectorAll('#anki-cards article.anki-card').length") == 5, \
            'a rejection never hides a card'
        assert anki.actions() == [], f'an answer reached Anki: {anki.actions()}'

    # ---- A fresh document keeps both answers
    open_entry(wimi_page, entry_id)
    wait_for_cards(wimi_page, 5)
    assert json.loads(wimi_page.eval_js(ORDER)) == [C3, C1, C2, C4, C5]
    assert wimi_page.eval_js(PROPOSALS) == 0


@pytest.mark.slow
@pytest.mark.regression
def test_proposals_that_do_not_narrow_the_list_draw_no_answers(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Owner, #815: four of five cards mention the subject, so there is nothing
    to choose between. One sentence says so; no row carries the answers."""
    entry_id = _seed(wimi_session.user.db)
    with FakeAnkiConnect() as anki:
        _stock(anki, all_match=True)
        enable_anki(wimi_page, anki.port)
        open_entry(wimi_page, entry_id)
        wait_for_cards(wimi_page, 5)
        assert poll_true(wimi_page, "document.querySelector('.anki-proposals-weak') !== null"),             status(wimi_page)
    note = wimi_page.eval_js("document.querySelector('.anki-proposals-weak').textContent")
    assert note.startswith('4 of 5 cards mention'), note
    assert 'can’t tell which one this mistake is about' in note, note
    assert wimi_page.eval_js(PROPOSALS) == 0, 'answers drawn although nothing was narrowed'
    assert wimi_page.eval_js("document.querySelectorAll('.anki-proposal-action').length") == 0
