"""Which of an entry's Anki cards are about what the student missed (#784 Wave 5).

When one question matches several cards (the worked example on #10716 is
nine), WIMI proposes the ones whose text names what this entry is about, and
the student confirms or sets each proposal aside (owner decision 14).

``RelevanceScorer`` is the interface: pure, over the entry's facts and its
cards' text, returning proposals with their reasons. ``LexicalScorer`` is the
only implementation, and it uses no model. A later scorer -- GLiNER2, only
after a measured gap, and never a language model in the cloud (#10716) --
would be a second implementation rather than a rewrite.

The lexical rules, each a decision:

- **Exact, never fuzzy.** A term matches as whole words, ignoring case and
  runs of spaces; there is no edit distance and no "did you mean". #60
  measured 0.86 exact against 0.45 fuzzy, and fuzzy proposed hyperkalemia for
  hypercalcemia.
- **The terms are the student's own.** The entry's primary and secondary
  subjects' names and their recorded aliases, plus the correct answer when it
  is words rather than a choice letter. No subjects and no usable answer
  means no proposals.
- **A reason is the matched words**, shown on the proposal, so the student
  can see why a card was picked before agreeing.
- **Only a choice is proposed.** With fewer than two cards there is nothing to
  choose between, so nothing is proposed.
- **The student's answers are honoured**: a card with a verdict on this entry
  is not proposed again, and a subject the student said never to use for a
  card no longer counts as a reason for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Set, Tuple

#: A subject's name or alias names the topic outright; an answer phrase is
#: weaker evidence, because answers are often generic words.
SUBJECT_WEIGHT = 1.0
ANSWER_WEIGHT = 0.5

#: An answer that is a choice letter (``B``, ``(c)``, ``d)``) or a number is
#: not words, and matching it would propose every card containing that letter.
_CHOICE = re.compile(r"^\(?[A-Za-z0-9]{1,2}[).]?$")


@dataclass(frozen=True)
class Term:
    """One phrase to look for. ``subject_id`` is ``None`` for the answer."""

    text: str
    kind: str                      # 'subject' | 'alias' | 'answer'
    subject_id: Optional[int] = None
    subject_name: Optional[str] = None


@dataclass(frozen=True)
class CardText:
    card_id: int
    text: str


@dataclass(frozen=True)
class Proposal:
    card_id: int
    score: float
    reasons: Tuple[Term, ...]

    @property
    def subject_ids(self) -> Tuple[int, ...]:
        """The subjects a *never* rejection can be scoped to (may be empty)."""
        seen: List[int] = []
        for term in self.reasons:
            if term.subject_id is not None and term.subject_id not in seen:
                seen.append(term.subject_id)
        return tuple(seen)

    def to_dict(self) -> dict:
        return {
            'card_id': self.card_id,
            'score': self.score,
            'subject_ids': list(self.subject_ids),
            'reasons': [{'text': t.text, 'kind': t.kind, 'subject_id': t.subject_id,
                         'subject_name': t.subject_name} for t in self.reasons],
        }


@dataclass(frozen=True)
class EntryFacts:
    terms: Tuple[Term, ...]
    #: Cards the student has already answered about on this entry.
    decided_cards: frozenset = field(default_factory=frozenset)
    #: ``(subject_id, card_id)`` pairs the student said never to propose.
    rejected_pairs: frozenset = field(default_factory=frozenset)


class RelevanceScorer(Protocol):
    def propose(self, facts: EntryFacts, cards: Sequence[CardText]) -> List[Proposal]:
        ...


def normalise(text: str) -> str:
    return ' '.join((text or '').casefold().split())


def answer_is_words(answer: Optional[str]) -> bool:
    text = (answer or '').strip()
    return len(text) >= 3 and any(ch.isalpha() for ch in text) and not _CHOICE.match(text)


def terms_from(relevance_terms: Mapping) -> Tuple[Term, ...]:
    """Build the term list from ``AnkiMixin.anki_relevance_terms``."""
    out: List[Term] = []
    seen: Set[Tuple[str, Optional[int]]] = set()

    def add(term: Term) -> None:
        key = (normalise(term.text), term.subject_id)
        if key[0] and key not in seen:
            seen.add(key)
            out.append(term)

    for subject in relevance_terms.get('subjects') or []:
        add(Term(subject['name'], 'subject', subject['id'], subject['name']))
        for alias in subject.get('aliases') or []:
            add(Term(alias, 'alias', subject['id'], subject['name']))
    answer = relevance_terms.get('answer')
    if answer_is_words(answer):
        add(Term(answer.strip(), 'answer'))
    return tuple(out)


def _pattern(term: str) -> re.Pattern:
    words = [re.escape(w) for w in normalise(term).split(' ')]
    return re.compile(r'(?<!\w)' + r'\s+'.join(words) + r'(?!\w)')


class LexicalScorer:
    """Exact whole-word matching of the student's own terms. No model."""

    def propose(self, facts: EntryFacts, cards: Sequence[CardText]) -> List[Proposal]:
        if len(cards) < 2 or not facts.terms:
            return []
        patterns = [(term, _pattern(term.text)) for term in facts.terms]
        proposals: List[Proposal] = []
        for card in cards:
            if card.card_id in facts.decided_cards:
                continue
            text = normalise(card.text)
            reasons = tuple(
                term for term, pattern in patterns
                if (term.subject_id is None
                    or (term.subject_id, card.card_id) not in facts.rejected_pairs)
                and pattern.search(text))
            if not reasons:
                continue
            score = sum(ANSWER_WEIGHT if t.kind == 'answer' else SUBJECT_WEIGHT for t in reasons)
            proposals.append(Proposal(card.card_id, score, reasons))
        order = {card.card_id: i for i, card in enumerate(cards)}
        proposals.sort(key=lambda p: (-p.score, order[p.card_id]))
        return proposals


def card_texts(cards: Iterable[Mapping]) -> List[CardText]:
    """The text the scorer reads for each cached card: every field, whichever
    the student chose to display -- visibility decides what is shown, not
    what a card is about."""
    out = []
    for card in cards:
        text = '\n'.join(f.get('text') or '' for f in card.get('fields') or [])
        out.append(CardText(card['card_id'], text))
    return out


def proposals_for(relevance_terms: Mapping, cards: Sequence[Mapping],
                  verdicts: Mapping[int, str], rejected_pairs: Iterable[Tuple[int, int]],
                  scorer: Optional[RelevanceScorer] = None) -> List[Dict]:
    """The bridge's one call: facts in, proposal dicts out."""
    facts = EntryFacts(terms=terms_from(relevance_terms),
                       decided_cards=frozenset(verdicts),
                       rejected_pairs=frozenset(rejected_pairs))
    scorer = scorer or LexicalScorer()
    return [p.to_dict() for p in scorer.propose(facts, card_texts(cards))]
