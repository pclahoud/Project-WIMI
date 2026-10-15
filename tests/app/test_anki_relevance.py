"""The lexical relevance scorer's golden cases (#784 Wave 5, decision 14).

Pure: no database, no Anki. Each case is one rule from the module docstring,
and several are the ones a later "improvement" would undo -- fuzzy matching,
matching inside words, or treating a choice letter as an answer.
"""
from __future__ import annotations

import pytest

from app.anki.relevance import (
    ANSWER_WEIGHT,
    SUBJECT_WEIGHT,
    CardText,
    EntryFacts,
    LexicalScorer,
    Term,
    answer_is_words,
    proposals_for,
    terms_from,
)

AORTA = {'id': 1, 'name': 'Aortic dissection', 'aliases': ['Tearing aorta']}
MI = {'id': 2, 'name': 'Myocardial infarction', 'aliases': ['MI']}
POTASSIUM = {'id': 3, 'name': 'Hyperkalemia', 'aliases': []}


def _cards(*texts):
    return [{'card_id': 100 + i, 'fields': [{'text': t}]} for i, t in enumerate(texts)]


def _ids(proposals):
    return [p['card_id'] for p in proposals]


def test_a_subject_name_or_alias_proposes_the_card_with_its_words():
    out = proposals_for({'subjects': [AORTA], 'answer': 'B'},
                        _cards('Pain of a TEARING  aorta', 'Unrelated card'), {}, set())
    assert _ids(out) == [100]
    assert [r['text'] for r in out[0]['reasons']] == ['Tearing aorta']
    assert out[0]['subject_ids'] == [1]


def test_matching_is_exact_never_fuzzy():
    """#60: fuzzy matching proposed hyperkalemia for hypercalcemia."""
    out = proposals_for({'subjects': [POTASSIUM], 'answer': None},
                        _cards('Hypercalcemia from malignancy', 'Hypokalemia'), {}, set())
    assert out == []


def test_a_term_matches_whole_words_only():
    out = proposals_for({'subjects': [MI], 'answer': None},
                        _cards('Michael has amiloride', 'An acute MI, inferior'), {}, set())
    assert _ids(out) == [101]


def test_no_subjects_and_no_usable_answer_means_no_proposals():
    assert proposals_for({'subjects': [], 'answer': 'C'}, _cards('C', 'C'), {}, set()) == []


def test_one_card_is_not_a_choice():
    assert proposals_for({'subjects': [AORTA], 'answer': None},
                         _cards('Aortic dissection'), {}, set()) == []


@pytest.mark.parametrize('answer, words', [
    ('B', False), ('(c)', False), ('d)', False), ('12', False), ('E.', False),
    ('Aortic dissection', True), ('Beta blocker', True), ('ACE', True),
])
def test_a_choice_letter_is_not_an_answer(answer, words):
    assert answer_is_words(answer) is words


def test_an_answer_phrase_counts_for_less_than_a_subject():
    out = proposals_for({'subjects': [MI], 'answer': 'Beta blocker'},
                        _cards('Beta blocker after an MI', 'Give a beta  blocker', 'Nothing'),
                        {}, set())
    assert _ids(out) == [100, 101]
    assert out[0]['score'] == SUBJECT_WEIGHT + ANSWER_WEIGHT
    assert out[1]['score'] == ANSWER_WEIGHT
    assert out[1]['subject_ids'] == [], 'an answer-only match has no subject to reject for'


def test_a_card_already_answered_about_is_not_proposed_again():
    cards = _cards('Aortic dissection', 'Aortic dissection again')
    out = proposals_for({'subjects': [AORTA], 'answer': None}, cards,
                        {100: 'not_for_entry', 101: 'confirmed'}, set())
    assert out == []


def test_a_subject_rejected_for_a_card_stops_counting_for_that_card_only():
    terms = {'subjects': [AORTA, MI], 'answer': None}
    cards = _cards('Aortic dissection and an MI', 'Aortic dissection')
    out = proposals_for(terms, cards, {}, {(1, 100)})
    by_card = {p['card_id']: p for p in out}
    assert [r['text'] for r in by_card[100]['reasons']] == ['MI']
    assert by_card[100]['subject_ids'] == [2]
    assert [r['text'] for r in by_card[101]['reasons']] == ['Aortic dissection']


def test_order_is_score_then_anki_order():
    out = proposals_for({'subjects': [AORTA, MI], 'answer': None},
                        _cards('MI', 'Aortic dissection and MI', 'Aortic dissection'), {}, set())
    assert _ids(out) == [101, 100, 102]


def test_every_field_is_read_whatever_is_displayed():
    cards = [{'card_id': 1, 'fields': [{'text': 'Front'}, {'text': 'Tearing aorta'}]},
             {'card_id': 2, 'fields': [{'text': 'Other'}]}]
    assert _ids(proposals_for({'subjects': [AORTA], 'answer': None}, cards, {}, set())) == [1]


def test_terms_are_deduplicated_ignoring_case():
    terms = terms_from({'subjects': [{'id': 1, 'name': 'MI', 'aliases': ['mi', 'MI ']}],
                        'answer': None})
    assert [t.text for t in terms] == ['MI']


def test_the_scorer_is_an_interface():
    """A second scorer plugs in without touching the bridge."""
    class Always:
        def propose(self, facts, cards):
            from app.anki.relevance import Proposal
            return [Proposal(c.card_id, 9.0, (Term('x', 'answer'),)) for c in cards]

    out = proposals_for({'subjects': [], 'answer': None}, _cards('a', 'b'), {}, set(),
                        scorer=Always())
    assert _ids(out) == [100, 101]
    assert isinstance(LexicalScorer().propose(EntryFacts(terms=()), [CardText(1, 'x')]), list)
