"""Spans become subjects: exact, exam-wide, aliases in, nothing lost (#60, #380).

#4904 measured this as the most valuable half of the pipeline — **exact
subject matching 0.86 against fuzzy 0.45** on the owner's blind adjudication —
so the tests that matter here are the ones that would catch a relaxation of
"exact" creeping in, not the happy path.

Three of them are the guards rather than the examples:

* ``test_a_near_miss_is_not_a_match`` is the whole of #4904. Fuzzy matching
  produced *hyperkalemia → hypercalcemia*, and any stemming, plural handling
  or edit distance added later makes that test fail — which is the point.
* ``test_the_counts_account_for_every_proposal`` makes a silent drop
  impossible to add. A matcher that lost a proposal would be
  indistinguishable from a model that never made it, and #212's rule is that
  rendered plus reported-as-omitted equals the input.
* ``test_canonicalisation_agrees_with_the_database`` pins this module's pair
  ordering against ``RelationsMixin._canonical_rejection_pair``. Two
  canonicalisations that disagreed would suppress the spelling the student did
  not reject and leave live the one they did.

No database and no model: ``Proposal`` is built directly, which is what makes
the matching rule testable at all.
"""
from __future__ import annotations

import pytest

from app.relation_extraction.matching import (
    MatchReport,
    Vocabulary,
    canonical_pair,
    match_proposals,
    normalise,
)
from app.relation_extraction.runtime import Mention, Proposal

pytestmark = pytest.mark.unit


# ==================== helpers ====================

def _proposal(head: str, tail: str, *, type_id: int = 1, label: str = 'causes',
              score: float = 0.95, passage: str = 'a sentence.') -> Proposal:
    return Proposal(
        relation_type_id=type_id,
        label=label,
        head=Mention(text=head, start=0, end=len(head), confidence=score),
        tail=Mention(text=tail, start=20, end=20 + len(tail), confidence=score),
        score=score,
        passage=passage,
        passage_start=0,
        passage_end=len(passage),
    )


@pytest.fixture
def vocabulary():
    return Vocabulary.from_subjects([
        {'id': 10, 'name': 'Hypertension', 'aliases': ['HTN', 'high blood pressure']},
        {'id': 11, 'name': 'Stroke', 'aliases': []},
        {'id': 12, 'name': 'Hypertensive nephrosclerosis', 'aliases': []},
        {'id': 13, 'name': 'Ear, nose and throat', 'aliases': []},
    ])


# ==================== normalisation ====================

@pytest.mark.parametrize('text, expected', [
    ('Hypertension', 'hypertension'),
    ('  hypertension  ', 'hypertension'),
    ('hypertension.', 'hypertension'),
    ('"hypertension"', 'hypertension'),
    ('Hypertensive\n nephrosclerosis', 'hypertensive nephrosclerosis'),
    ('Ear, nose and throat', 'ear, nose and throat'),
])
def test_normalisation_folds_case_and_whitespace_and_edge_punctuation(text, expected):
    """Internal punctuation stays: a subject really can be named *Ear, nose...*"""
    assert normalise(text) == expected


def test_a_match_is_case_insensitive(vocabulary):
    """Otherwise "exact" would mean "exactly capitalised", which nobody intends.

    The model returns spans of the student's prose, where a subject named
    *Hypertension* appears mid-sentence as *hypertension*.
    """
    assert vocabulary.lookup('hypertension') == (10,)
    assert vocabulary.lookup('HYPERTENSION') == (10,)


def test_an_alias_matches(vocabulary):
    """#380 decision 2. *HTN* is the ordinary case in this corpus.

    Still exact matching — against a second name the student recorded
    themselves — which is why it does not reopen #4904's exact-only finding.
    """
    assert vocabulary.lookup('HTN') == (10,)
    assert vocabulary.lookup('high blood pressure') == (10,)


def test_a_near_miss_is_not_a_match(vocabulary):
    """The load-bearing one. Fuzzy matching gave *hyperkalemia → hypercalcemia*.

    Any stemming, plural handling or edit distance added later fails here, and
    that is what this test is for. #4904: exact 0.86, fuzzy 0.45.
    """
    for near in ('strokes', 'hypertensive', 'hyper tension', 'Hypertensio',
                 'hypertension nephrosclerosis'):
        assert vocabulary.lookup(near) == (), f'{near!r} must not match'


def test_an_alias_shared_by_two_subjects_is_ambiguous_not_arbitrary():
    """`subject_aliases` is UNIQUE per subject, not per exam, so this is legal.

    An "exact" matcher that picked one of two candidates would be guessing in
    the one place this module exists not to guess.
    """
    vocab = Vocabulary.from_subjects([
        {'id': 1, 'name': 'Myocardial infarction', 'aliases': ['MI']},
        {'id': 2, 'name': 'Mitral insufficiency', 'aliases': ['MI']},
    ])
    assert set(vocab.lookup('MI')) == {1, 2}

    report = match_proposals([_proposal('MI', 'Mitral insufficiency')], vocab)
    assert not report.matched
    assert len(report.ambiguous) == 1
    assert set(report.ambiguous[0].head_candidates) == {1, 2}


def test_alias_rows_are_accepted_in_either_shape():
    """The two alias readers in this codebase return different shapes.

    ``get_aliases_for_subject`` gives objects with ``alias_name``;
    ``get_extraction_vocabulary`` gives plain strings. A matcher that handled
    one would silently index no aliases at all when handed the other.
    """
    vocab = Vocabulary.from_subjects([
        {'id': 1, 'name': 'Hypertension', 'aliases': [{'alias_name': 'HTN'}]},
    ])
    assert vocab.lookup('HTN') == (1,)


# ==================== matching ====================

def test_both_ends_resolved_is_a_match(vocabulary):
    report = match_proposals(
        [_proposal('hypertension', 'hypertensive nephrosclerosis')], vocabulary)

    assert len(report.matched) == 1
    hit = report.matched[0]
    assert (hit.from_subject_id, hit.to_subject_id) == (10, 12)
    assert hit.from_subject_name == 'Hypertension'
    assert hit.relation_type_id == 1
    assert hit.to_dict()['passage'] == 'a sentence.'


def test_one_unresolved_end_is_reported_with_which_end(vocabulary):
    """"One end is not in your tree" says whether the vocabulary is the limit.

    Dropping it would make that indistinguishable from the model finding
    nothing.
    """
    report = match_proposals(
        [_proposal('hypertension', 'renal papillary necrosis')], vocabulary)

    assert not report.matched
    assert len(report.unmatched) == 1
    miss = report.unmatched[0]
    assert miss.head_matched is True
    assert miss.tail_matched is False
    assert miss.tail_text == 'renal papillary necrosis'


def test_both_ends_the_same_subject_is_dropped_before_the_write(vocabulary):
    """Reachable from ordinary prose: one sentence naming a subject twice.

    ``create_subject_relation`` refuses a self-loop with a sentence, and a
    refusal the student did not cause is worse than a proposal not made.
    """
    report = match_proposals([_proposal('hypertension', 'HTN')], vocabulary)

    assert not report.matched
    assert len(report.self_referential) == 1


def test_a_rejected_pair_is_suppressed_and_said_to_be(vocabulary):
    """#60's acceptance criterion: a rejected proposal is not re-proposed."""
    report = match_proposals(
        [_proposal('hypertension', 'stroke', type_id=3)],
        vocabulary,
        suppressed_pairs={(10, 11, 3)},
    )

    assert not report.matched
    assert len(report.suppressed) == 1
    assert report.suppressed[0].from_subject_id == 10


def test_suppression_of_a_symmetric_type_works_from_either_end(vocabulary):
    """Otherwise the student is asked the same question from the other side.

    A symmetric type is one relation stored as (min, max), so a rejection of
    *A confused with B* has to suppress the *B confused with A* spelling too.
    """
    report = match_proposals(
        [_proposal('stroke', 'hypertension', type_id=6)],  # 11 -> 10
        vocabulary,
        suppressed_pairs={(10, 11, 6)},                    # stored canonically
        symmetric_type_ids={6},
    )
    assert not report.matched and len(report.suppressed) == 1

    # The control: without the symmetric set the same rejection misses.
    leaked = match_proposals(
        [_proposal('stroke', 'hypertension', type_id=6)],
        vocabulary,
        suppressed_pairs={(10, 11, 6)},
    )
    assert len(leaked.matched) == 1, (
        'this is the bug the symmetric set prevents; if this ever passes as '
        'suppressed, the canonicalisation moved and the test above is vacuous')


def test_an_asymmetric_type_keeps_its_direction(vocabulary):
    """*A causes B* being rejected says nothing about *B causes A* (decision 7)."""
    report = match_proposals(
        [_proposal('stroke', 'hypertension', type_id=1)],
        vocabulary,
        suppressed_pairs={(10, 11, 1)},
    )
    assert len(report.matched) == 1


def test_an_untyped_triple_in_the_suppressed_set_is_handled(vocabulary):
    """Defensive cover, and the docstring says so rather than implying a path.

    Extraction cannot *produce* an untyped proposal — ``proposals_from_raw``
    resolves every label through ``label_index`` — but
    ``rejected_pairs_for_entry`` legitimately returns untyped triples, because
    a manually authored relation may be untyped and so may its rejection.
    SQLite keeps NULLs distinct in a UNIQUE index, so the type is part of the
    key and a ``None`` in the set must neither match a typed proposal nor
    raise.
    """
    untyped = _proposal('hypertension', 'stroke', type_id=None)

    assert len(match_proposals(
        [untyped], vocabulary, suppressed_pairs={(10, 11, None)}).suppressed) == 1
    assert len(match_proposals(
        [_proposal('hypertension', 'stroke', type_id=3)],
        vocabulary, suppressed_pairs={(10, 11, None)}).matched) == 1, (
        'an untyped rejection must not suppress a typed proposal')


# ==================== the accounting ====================

def test_the_counts_account_for_every_proposal(vocabulary):
    """``matched + unmatched + ambiguous + self_referential + suppressed``.

    A silent drop would be indistinguishable from a model that found nothing,
    which is the state where nobody can tell a filter bug from a model limit.
    """
    proposals = [
        _proposal('hypertension', 'hypertensive nephrosclerosis'),   # matched
        _proposal('hypertension', 'renal papillary necrosis'),       # unmatched
        _proposal('hypertension', 'HTN'),                            # self
        _proposal('hypertension', 'stroke', type_id=3),              # suppressed
    ]
    report = match_proposals(proposals, vocabulary,
                             suppressed_pairs={(10, 11, 3)})

    assert report.considered == len(proposals)
    assert report.counts['considered'] == len(proposals)
    assert sum(report.counts[k] for k in (
        'matched', 'unmatched', 'ambiguous', 'self_referential', 'suppressed'
    )) == len(proposals)
    assert report.describe()


def test_nothing_in_gives_an_empty_report_rather_than_an_error():
    """An explanation naming no subject at all is the ordinary case."""
    report = match_proposals([], Vocabulary.from_subjects([]))
    assert report.considered == 0
    assert isinstance(report, MatchReport)


def test_a_blank_name_is_not_indexed():
    """An empty term would match every span that normalises to nothing."""
    vocab = Vocabulary.from_subjects([
        {'id': 1, 'name': '   ', 'aliases': ['']},
        {'id': 2, 'name': 'Stroke', 'aliases': []},
    ])
    assert vocab.lookup('') == ()
    assert vocab.lookup('...') == ()
    assert len(vocab) == 1


# ==================== agreement with the database ====================

@pytest.mark.parametrize('symmetric, from_id, to_id, expected', [
    (True, 20, 10, (10, 20)),
    (True, 10, 20, (10, 20)),
    (False, 20, 10, (20, 10)),
    (False, 10, 20, (10, 20)),
])
def test_canonicalisation_agrees_with_the_database(symmetric, from_id, to_id, expected):
    """Pinned against ``RelationsMixin._canonical_rejection_pair``'s rule.

    That method asks the database for ``is_symmetric``; this one is handed the
    set. Two canonicalisations that disagreed would suppress the spelling the
    student did not reject and leave live the one they did — a bug with no
    symptom until the same proposal came back from the other end.

    Checked against the real method's source rather than a restatement of it,
    so a change there fails here.
    """
    import inspect

    from database.domains.relations import RelationsMixin

    source = inspect.getsource(RelationsMixin._canonical_rejection_pair)
    assert "is_symmetric'] and from_subject_id > to_subject_id" in source, (
        'the database canonicalises symmetric pairs as (min, max) by '
        'swapping when from > to; if that line moved, this test and '
        'matching.canonical_pair both need re-deriving')

    assert canonical_pair(
        from_id, to_id, 7, frozenset({7} if symmetric else ())) == expected


def test_an_untyped_pair_is_never_reordered():
    """``_canonical_rejection_pair`` returns early on ``None``, and so must this.

    An untyped relation has no symmetry to appeal to, so its direction is the
    student's.
    """
    assert canonical_pair(20, 10, None, frozenset({20})) == (20, 10)
