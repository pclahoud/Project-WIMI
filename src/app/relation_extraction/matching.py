"""Turning a model's spans into the student's subjects (#60, #380 decision 2).

> **Exact, exam-wide, aliases included. Nothing is dropped without being
> counted.**

The model returns character spans of the student's own prose. This module
decides which subject each span *is*, and it is the half #4904 measured as
worth more than anything else in the pipeline: **exact subject matching scored
0.86 against fuzzy's 0.45** on the owner's blind adjudication of 99 proposals.

No torch, no Qt, no database. It takes a vocabulary the caller fetched and
returns decisions the caller writes; the bridge runs it in a job's ``finish``
phase, on the Qt main thread, which is where that read belongs.

What "exact" means here, and what it deliberately does not
----------------------------------------------------------
Normalisation is **case folding plus whitespace collapse, and nothing else**:

* ``casefold()`` rather than ``lower()``, because the former is what Unicode
  defines for caseless comparison. A subject written *Hypertension* has to
  match *hypertension* in prose or "exact" would mean "exactly capitalised",
  which is not a rule anybody intends.
* Internal runs of whitespace collapse to one space, so a line break inside
  *hypertensive  nephrosclerosis* does not make it a different term.
* A mention's **edges** are stripped of whitespace and of ``.,;:!?`` and
  quotes, because a span can arrive carrying the sentence's full stop.

There is **no stemming, no plural handling, no punctuation removal inside a
term, and no edit distance**. *strokes* does not match *stroke*. That is not an
oversight: the moment a near-miss is accepted this becomes the fuzzy matcher
that produced *hyperkalemia → hypercalcemia*, and the 0.45 figure is what that
costs. Internal punctuation is kept because a subject really can be named
*Ear, nose and throat*.

**An alias is not a relaxation of this rule.** #380 decision 2 includes
``subject_aliases``, and an alias match is still exact matching -- against a
second name the student recorded themselves. Fuzzy matching guesses at a name
nobody wrote; an alias is a name somebody did write. Different mechanism,
different failure mode.

Why everything is counted
-------------------------
``MatchReport`` accounts for **every** proposal it was given:
``matched + unmatched + ambiguous + self_referential + suppressed`` equals the
input length, and a test asserts it. A matcher that silently dropped a
proposal would be indistinguishable from a model that never made it, which is
the state in which nobody can tell a filter bug from a model limitation. It is
the same rule as #212's *rendered plus reported-as-omitted equals the file*.

Ambiguity is reported, never guessed
------------------------------------
Two subjects in one exam can carry the same alias; ``check_alias_conflicts``
detects that case rather than forbidding it. So a normalised term can name
more than one subject, and an "exact" matcher that picked one of them would be
guessing in the one place this module exists not to guess. Such a proposal is
reported as ``ambiguous`` with the candidates, and is not written.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .runtime import Proposal

#: Stripped from a mention's edges before lookup. A span can include the
#: sentence's punctuation; it cannot include punctuation that belongs to the
#: subject's own name, because that is in the middle.
_EDGE_PUNCTUATION = ' \t\r\n.,;:!?\'"`()[]*_'

_WHITESPACE = re.compile(r'\s+')


def normalise(text: str) -> str:
    """The one normalisation. See the module docstring for what it refuses."""
    collapsed = _WHITESPACE.sub(' ', text or '')
    return collapsed.strip(_EDGE_PUNCTUATION).casefold()


@dataclass(frozen=True)
class Vocabulary:
    """Normalised term to subject ids, built once per extraction.

    Built from rows the caller fetched -- ``{'id', 'name', 'aliases'}`` -- so
    this module needs no database and can be tested with a literal.

    A term mapping to several subjects is kept as several, not resolved: see
    the module docstring on ambiguity.
    """

    terms: Mapping[str, Tuple[int, ...]]
    #: Subject id to the name to show the student. Kept so a report can name a
    #: subject without a second query.
    names: Mapping[int, str]

    @classmethod
    def from_subjects(cls, subjects: Iterable[Mapping[str, Any]]) -> 'Vocabulary':
        terms: Dict[str, List[int]] = {}
        names: Dict[int, str] = {}

        def add(term: str, subject_id: int) -> None:
            key = normalise(term)
            if not key:
                return
            bucket = terms.setdefault(key, [])
            if subject_id not in bucket:
                bucket.append(subject_id)

        for row in subjects:
            subject_id = int(row['id'])
            names[subject_id] = str(row['name'])
            add(str(row['name']), subject_id)
            for alias in row.get('aliases') or ():
                # Accepts a bare string or a row with an ``alias_name``, since
                # the two alias readers in the codebase return each shape.
                text = alias if isinstance(alias, str) else alias.get('alias_name')
                if text:
                    add(str(text), subject_id)

        return cls(terms={k: tuple(v) for k, v in terms.items()}, names=names)

    def lookup(self, text: str) -> Tuple[int, ...]:
        """Every subject the span names. Empty for a miss, >1 for ambiguity."""
        return self.terms.get(normalise(text), ())

    def name_of(self, subject_id: int) -> Optional[str]:
        return self.names.get(subject_id)

    def __len__(self) -> int:
        return len(self.terms)


def canonical_pair(
    from_subject_id: int,
    to_subject_id: int,
    relation_type_id: Optional[int],
    symmetric_type_ids: frozenset,
) -> Tuple[int, int]:
    """Order a pair the way m026 and m027 store it.

    A symmetric type is one relation, stored as ``(min id, max id)``; an
    asymmetric one keeps its direction. **This must agree with
    ``RelationsMixin._canonical_rejection_pair``**, which asks the database
    for ``is_symmetric`` instead of being handed the set --
    ``test_relation_matching.py`` pins the two against each other, because two
    canonicalisations that disagree would mean a rejection suppressing the
    spelling the student did not reject and leaving the one they did.
    """
    if relation_type_id is not None and relation_type_id in symmetric_type_ids:
        if from_subject_id > to_subject_id:
            return to_subject_id, from_subject_id
    return from_subject_id, to_subject_id


@dataclass(frozen=True)
class MatchedProposal:
    """A proposal both of whose ends are a subject, and that is not suppressed.

    Carries the ``Proposal`` it came from rather than copying its fields, so
    the passage, the offsets and the score stay available to the write path
    without this module deciding what they are for.
    """

    proposal: Proposal
    from_subject_id: int
    to_subject_id: int
    from_subject_name: Optional[str] = None
    to_subject_name: Optional[str] = None

    @property
    def relation_type_id(self) -> int:
        return self.proposal.relation_type_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            'from_subject_id': self.from_subject_id,
            'to_subject_id': self.to_subject_id,
            'from_subject_name': self.from_subject_name,
            'to_subject_name': self.to_subject_name,
            **self.proposal.to_dict(),
        }


@dataclass(frozen=True)
class UnmatchedProposal:
    """A proposal one or both of whose ends named no subject.

    Reported rather than dropped, because "the model found a relation between
    two things, one of which is not in your tree" is a different fact from
    "the model found nothing" -- and it is the fact that says whether the
    vocabulary or the model is the limit.
    """

    proposal: Proposal
    head_text: str
    tail_text: str
    head_matched: bool
    tail_matched: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            'head_text': self.head_text,
            'tail_text': self.tail_text,
            'head_matched': self.head_matched,
            'tail_matched': self.tail_matched,
            'label': self.proposal.label,
            'passage': self.proposal.passage,
        }


@dataclass(frozen=True)
class AmbiguousProposal:
    """A span naming more than one subject. Never resolved by guessing."""

    proposal: Proposal
    head_candidates: Tuple[int, ...]
    tail_candidates: Tuple[int, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'head_text': self.proposal.head.text,
            'tail_text': self.proposal.tail.text,
            'head_candidates': list(self.head_candidates),
            'tail_candidates': list(self.tail_candidates),
            'label': self.proposal.label,
            'passage': self.proposal.passage,
        }


@dataclass(frozen=True)
class MatchReport:
    """Every proposal, classified. The counts add up; a test says so."""

    matched: Tuple[MatchedProposal, ...] = ()
    unmatched: Tuple[UnmatchedProposal, ...] = ()
    ambiguous: Tuple[AmbiguousProposal, ...] = ()
    #: Both ends resolved to the same subject. ``create_subject_relation``
    #: refuses a self-loop with a sentence, so these are dropped before the
    #: write rather than surfacing as a refusal the student did not cause.
    #: Reachable from ordinary prose: one sentence naming a subject twice.
    self_referential: Tuple[Proposal, ...] = ()
    #: Matched, then suppressed by a rejection or by an existing relation.
    suppressed: Tuple[MatchedProposal, ...] = ()
    #: Counts by cause, for a log line and for the accounting test.
    counts: Dict[str, int] = field(default_factory=dict)

    @property
    def considered(self) -> int:
        return (len(self.matched) + len(self.unmatched) + len(self.ambiguous)
                + len(self.self_referential) + len(self.suppressed))

    def describe(self) -> str:
        return (f'{len(self.matched)} matched, {len(self.unmatched)} unmatched, '
                f'{len(self.ambiguous)} ambiguous, '
                f'{len(self.self_referential)} self-referential, '
                f'{len(self.suppressed)} suppressed')


def match_proposals(
    proposals: Sequence[Proposal],
    vocabulary: Vocabulary,
    *,
    suppressed_pairs: Optional[Iterable[Tuple[int, int, Optional[int]]]] = None,
    symmetric_type_ids: Iterable[int] = (),
) -> MatchReport:
    """Classify every proposal against the student's own vocabulary.

    Parameters
    ----------
    proposals:
        What the model returned, already above the student's threshold --
        this function does **not** filter on score. The threshold is the
        runtime's (#380: default 0.80, 0.10-0.95), applied where the model is
        asked, so that a score a student never wanted is never even carried.
    suppressed_pairs:
        ``(from, to, relation_type_id)`` triples in **canonical** order, as
        ``RelationsMixin.rejected_pairs_for_entry`` returns them. The caller
        unions in the pairs that already carry a relation of that type: m026's
        ``UNIQUE(from, to, relation_type_id)`` would refuse the insert anyway,
        and a refusal the student did not cause is worse than a proposal
        quietly not made again.
    symmetric_type_ids:
        Types for which ``A~B`` and ``B~A`` are one relation, so the pair is
        canonicalised before the suppression lookup. Omitting them would leave
        *B confused with A* live after the student rejected
        *A confused with B*, and they would be asked again from the other end.

    The order of the checks is deliberate: **ambiguity before self-reference**,
    because a span naming two subjects is not a self-loop even when one of its
    candidates is the other end; and **suppression last**, because a
    suppressed proposal has to be a matched one first in order to be reported
    as suppressed at all.
    """
    suppressed_set = set(suppressed_pairs or ())
    symmetric = frozenset(int(t) for t in symmetric_type_ids)

    matched: List[MatchedProposal] = []
    unmatched: List[UnmatchedProposal] = []
    ambiguous: List[AmbiguousProposal] = []
    self_referential: List[Proposal] = []
    held_back: List[MatchedProposal] = []

    for proposal in proposals:
        heads = vocabulary.lookup(proposal.head.text)
        tails = vocabulary.lookup(proposal.tail.text)

        if not heads or not tails:
            unmatched.append(UnmatchedProposal(
                proposal=proposal,
                head_text=proposal.head.text,
                tail_text=proposal.tail.text,
                head_matched=bool(heads),
                tail_matched=bool(tails),
            ))
            continue

        if len(heads) > 1 or len(tails) > 1:
            ambiguous.append(AmbiguousProposal(
                proposal=proposal,
                head_candidates=heads,
                tail_candidates=tails,
            ))
            continue

        head_id, tail_id = heads[0], tails[0]
        if head_id == tail_id:
            self_referential.append(proposal)
            continue

        candidate = MatchedProposal(
            proposal=proposal,
            from_subject_id=head_id,
            to_subject_id=tail_id,
            from_subject_name=vocabulary.name_of(head_id),
            to_subject_name=vocabulary.name_of(tail_id),
        )
        key = canonical_pair(
            head_id, tail_id, proposal.relation_type_id, symmetric)
        if (key[0], key[1], proposal.relation_type_id) in suppressed_set:
            held_back.append(candidate)
        else:
            matched.append(candidate)

    return MatchReport(
        matched=tuple(matched),
        unmatched=tuple(unmatched),
        ambiguous=tuple(ambiguous),
        self_referential=tuple(self_referential),
        suppressed=tuple(held_back),
        counts={
            'considered': len(proposals),
            'matched': len(matched),
            'unmatched': len(unmatched),
            'ambiguous': len(ambiguous),
            'self_referential': len(self_referential),
            'suppressed': len(held_back),
            'vocabulary_terms': len(vocabulary),
        },
    )
