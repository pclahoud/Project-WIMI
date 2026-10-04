"""What the priming prompt has to guarantee before a microphone exists (#59, T10).

Most of these are ordinary unit tests. One is not, and it is the reason this
file exists:

``test_over_budget_keeps_the_best_term_and_drops_the_worst`` guards the
**reverse emit order**. whisper.cpp keeps the TAIL of an over-long prompt and
discards the FRONT, silently, so the most relevant terms have to be emitted
last. That reads backwards, and the first draft of the plan got it backwards --
it said "truncate nearest-first", which would have put the best terms exactly
where the engine throws them away, with exit 0 and nothing on stderr to say so.
Somebody will eventually read ``priming.py``, find the reversal counter-
intuitive, and "fix" it. That test is what stops them, so its failure message
explains the tail-keeping behaviour rather than just printing two lists.

The other one worth knowing about is
``test_estimate_leaves_headroom_against_the_measured_density``: there is no
Whisper tokeniser in this process, so the budget is estimated from a measured
characters-per-token ratio, and that test checks the estimate errs on the
**under-filling** side -- which is the whole point of estimating conservatively.

Plan: ``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` sections 0.1 and 3.6.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.stt.priming import (
    DEFAULT_PROMPT_FRAME,
    ORDINARY_ENGLISH_WORDS,
    PROMPT_TOKEN_BUDGET,
    TERM_SOURCES_MOST_RELEVANT_FIRST,
    TermSource,
    build_priming_prompt,
    estimate_prompt_tokens,
    is_ordinary_english,
    normalise_term,
    select_priming_terms,
)

FIXTURE = (Path(__file__).resolve().parents[1]
           / 'fixtures' / 'stt_vocabulary_terms.json')

#: The two characters-per-token densities task T3 measured on this project's
#: own priming glossary, using whisper.cpp's overflow message as the
#: instrument: 3.69 on four long probe strings, 3.46 on a single budget-sized
#: prompt. ``priming.py`` divides by 3.3, below both, on purpose.
MEASURED_DENSEST = 3.46
MEASURED_SPARSEST = 3.69


def glossary(prompt):
    """The glossary terms of a rendered prompt, in emit order."""
    if not prompt:
        return []
    return [term.strip()
            for term in prompt.split('Terms: ', 1)[1].rstrip('.').split(',')]


@pytest.fixture(scope='module')
def real_terms():
    """The 118 exam-blueprint terms task T3 built for the accuracy corpus.

    Real vocabulary, not invented: every string in there occurs verbatim in
    ``tests/fixtures/usmle_step1_outline.txt``. Using it here means the budget
    arithmetic is checked against the thing it will actually be asked to carry,
    long drug names and all.
    """
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    return list(data['priming']['base_terms'])


# ==========================================================================
# The ordering rule. Read the module docstring before touching this one.
# ==========================================================================


@pytest.mark.unit
def test_over_budget_keeps_the_best_term_and_drops_the_worst(real_terms):
    """Too many terms: the best-ranked survives and a worst-ranked one is cut.

    This is the regression guard for plan section 0.1, finding 2.
    """
    best = 'hypertensive nephrosclerosis'
    worst = real_terms[0]
    assert worst != best

    terms = select_priming_terms(
        entry_subjects=[best],
        frequent_subjects=real_terms,
    )
    prompt = build_priming_prompt(terms)

    assert estimate_prompt_tokens(prompt) <= PROMPT_TOKEN_BUDGET
    assert len(terms) > prompt.count(',') + 1, (
        'this test is only meaningful when more terms were offered than fit; '
        'the fixture no longer overflows the budget, so widen it'
    )

    explanation = (
        "\n"
        "ORDER IS REVERSED ON PURPOSE. Do not 'fix' it.\n"
        "\n"
        "whisper.cpp's prompt budget is n_text_ctx/2 - 1 = %d tokens. When a\n"
        "prompt is longer than that it keeps the TAIL and discards the FRONT,\n"
        "and it does so SILENTLY: exit 0, nothing on stderr, and with -np not\n"
        "even the tokenizer's own warning. Task T1 verified that three ways.\n"
        "\n"
        "So the most relevant terms must be emitted LAST, where they survive,\n"
        "and priming.py cuts from the front itself so the cut is inspectable.\n"
        "An implementation that emits best-first looks more natural, passes a\n"
        "casual read, and throws the student's own tagged subjects away.\n"
        "\n"
        "Expected in the prompt:  %r  (tier %s, the subject on the open entry)\n"
        "Expected cut from it:    %r  (tier %s, an exam-wide frequent subject)\n"
        "\n"
        "Prompt was:\n%s\n"
    ) % (PROMPT_TOKEN_BUDGET, best, TermSource.ENTRY_SUBJECT.name,
         worst, TermSource.FREQUENT.name, prompt)

    assert best in prompt, 'the HIGHEST-ranked term was dropped.' + explanation
    assert worst not in prompt, 'a LOWEST-ranked term survived.' + explanation


@pytest.mark.unit
def test_the_most_relevant_term_is_last_in_the_glossary(real_terms):
    """Not merely present: it has to be at the end, where truncation cannot reach."""
    best = 'hypertensive nephrosclerosis'
    prompt = build_priming_prompt(
        select_priming_terms(entry_subjects=[best], frequent_subjects=real_terms)
    )
    assert prompt.rstrip('.').endswith(best), (
        'the best term must be the LAST thing in the prompt, because the tail '
        'is the part whisper.cpp keeps. Got: ...%r' % prompt[-80:]
    )


@pytest.mark.unit
def test_tiers_are_emitted_worst_first():
    """Every tier, in one assertion, in the order section 3.6 lists them."""
    terms = select_priming_terms(
        entry_subjects=['metoprolol'],
        ancestors=['nephrosclerosis'],
        siblings=['glomerulosclerosis'],
        frequent_subjects=['pheochromocytoma'],
        drop_ordinary=False,
    )
    assert terms == [
        'pheochromocytoma',    # FREQUENT  -- least relevant, cut first
        'glomerulosclerosis',  # SIBLING
        'nephrosclerosis',     # ANCESTOR
        'metoprolol',          # ENTRY_SUBJECT -- most relevant, survives
    ]


@pytest.mark.unit
def test_an_alias_of_an_entry_subject_outlives_a_sibling(real_terms):
    """An alias ranks with its subject, so it survives a cut that eats siblings.

    This is the tail-keeping rule one step along, and it is a guard against the
    same shape of mistake: a flat alias tier below siblings looks tidy, reads
    fine, and throws away the word the student is most likely to say.
    """
    alias = 'afib'
    subject = 'atrial fibrillation'
    terms = select_priming_terms(
        entry_subjects=[(subject, [alias])],
        siblings=real_terms,
    )
    prompt = build_priming_prompt(terms)
    survivors = glossary(prompt)
    dropped = [term for term in terms if term not in survivors]

    assert estimate_prompt_tokens(prompt) <= PROMPT_TOKEN_BUDGET
    assert dropped, (
        'this test is only meaningful when the budget actually cuts something; '
        'the sibling fixture no longer overflows, so widen it'
    )

    explanation = (
        "\n"
        "AN ALIAS IS NOT A TIER. It ranks with the subject it names.\n"
        "\n"
        "The glossary is emitted least relevant first and whisper.cpp keeps the\n"
        "TAIL, silently. So a flat alias tier ranked below siblings is thrown\n"
        "away BEFORE the siblings above it -- and the alias is the alternate\n"
        "name the student actually says out loud, for the subject they are\n"
        "actually explaining. Losing %r while keeping some sibling topic's\n"
        "canonical name is the exact inversion of what priming is for.\n"
        "\n"
        "Section 3.6 calls an alias the single highest-value source here. That\n"
        "is only true in the code if it inherits its owner's rank, which is\n"
        "what select_priming_terms does: tiers take SUBJECTS, and a subject\n"
        "carries its aliases. There is no aliases= parameter to flatten.\n"
        "\n"
        "Expected to survive: %r (alias of the entry subject %r)\n"
        "%d of %d candidates were cut, all of them siblings.\n"
    ) % (alias, alias, subject, len(dropped), len(terms))

    assert alias in survivors, 'the alias was cut.' + explanation
    assert subject in survivors, 'the entry subject was cut.' + explanation
    assert all(term in real_terms for term in dropped), (
        'something other than a sibling was cut.' + explanation)


@pytest.mark.unit
def test_an_alias_sits_with_its_owner_in_every_tier():
    """Owner first, its aliases immediately after, at the owner's tier."""
    terms = select_priming_terms(
        entry_subjects=[('atrial fibrillation', ['afib'])],
        ancestors=[('myocardial infarction', ['MI'])],
        siblings=[('deep vein thrombosis', ['DVT'])],
        frequent_subjects=[('chronic obstructive pulmonary disease', ['COPD'])],
        drop_ordinary=False,
    )
    assert terms == [
        'chronic obstructive pulmonary disease', 'COPD',   # FREQUENT
        'deep vein thrombosis', 'DVT',                     # SIBLING
        'myocardial infarction', 'MI',                     # ANCESTOR
        'atrial fibrillation', 'afib',                     # ENTRY_SUBJECT
    ]


@pytest.mark.unit
def test_an_alias_is_slightly_more_relevant_than_its_own_subject():
    """If the cut lands inside the group, the spoken name is the half kept."""
    terms = select_priming_terms(
        entry_subjects=[('atrial fibrillation', ['afib'])], drop_ordinary=False)
    assert terms.index('afib') > terms.index('atrial fibrillation')


@pytest.mark.unit
def test_a_subject_row_from_the_database_is_accepted_unchanged():
    """The exact shape get_all_subjects_with_aliases_for_exam returns.

    Its rows carry 'name' and 'aliases', and each alias is a
    SubjectAlias.to_dict() with 'alias_name'. The caller should be able to hand
    those straight over -- reshaping them in the bridge is where the
    association gets accidentally flattened.
    """
    row = {
        'id': 7,
        'name': 'Atrial Fibrillation',
        'path': 'Cardiovascular System > Atrial Fibrillation',
        'level_type': 'Topic',
        'weight': 0,
        'aliases': [
            {'id': 1, 'subject_node_id': 7, 'alias_name': 'afib',
             'alias_type': 'colloquial', 'is_primary': False},
            {'id': 2, 'subject_node_id': 7, 'alias_name': 'AF',
             'alias_type': 'acronym', 'is_primary': False},
        ],
        'aliasesString': 'afib | AF',
    }
    assert select_priming_terms(entry_subjects=[row], drop_ordinary=False) == \
        ['Atrial Fibrillation', 'afib', 'AF']


@pytest.mark.unit
@pytest.mark.parametrize('candidate, expected', [
    ('warfarin', ['warfarin']),                              # bare name
    (('warfarin', []), ['warfarin']),                        # pair, no aliases
    (('warfarin', None), ['warfarin']),                      # pair, null aliases
    (('warfarin', ['coumadin']), ['warfarin', 'coumadin']),  # pair
    (('warfarin', 'coumadin'), ['warfarin', 'coumadin']),    # one bare alias
    ({'name': 'warfarin'}, ['warfarin']),                    # mapping, no key
    ({'name': 'warfarin', 'aliases': ['coumadin']},
     ['warfarin', 'coumadin']),
    ({'name': 'warfarin', 'aliases': [{'alias_name': 'coumadin'}]},
     ['warfarin', 'coumadin']),
])
def test_every_accepted_candidate_shape(candidate, expected):
    assert select_priming_terms(entry_subjects=[candidate],
                                drop_ordinary=False) == expected


@pytest.mark.unit
def test_a_malformed_candidate_costs_only_itself():
    """A bad row loses its own priming, never the prompt.

    ``{'aliases': [...]}`` with no name is the interesting one: it is an
    ownerless alias, and letting it through would readmit the flat alias tier
    through a side door, at whatever tier the row happened to be passed in.
    """
    terms = select_priming_terms(
        entry_subjects=['metoprolol', 12345, ('a', 'b', 'c'), None,
                        {'aliases': ['orphan']}, ('   ', ['orphan'])],
        drop_ordinary=False,
    )
    assert terms == ['metoprolol']


@pytest.mark.unit
def test_there_is_no_flat_aliases_parameter():
    """Re-adding one is the bug. It must be impossible, not merely discouraged.

    A bag of aliases with no owner cannot be ranked. The old flat tier put it
    mid-order, below siblings, where truncation reached it first. A caller that
    genuinely has ownerless aliases puts them in frequent_subjects -- the
    documented floor, which is honest about what it can promise.
    """
    with pytest.raises(TypeError):
        select_priming_terms(aliases=['afib'])
    assert 'aliases' not in dict(TERM_SOURCES_MOST_RELEVANT_FIRST)
    assert not hasattr(TermSource, 'ALIAS')


@pytest.mark.unit
def test_tier_order_constant_matches_the_enum():
    """One definition of the tier order, not two that can drift apart."""
    assert [source for _name, source in TERM_SOURCES_MOST_RELEVANT_FIRST] == \
        sorted(TermSource)


@pytest.mark.unit
def test_caller_order_within_a_tier_is_preserved():
    """The caller's order is the only tie-break inside a tier, so it must hold."""
    terms = select_priming_terms(
        entry_subjects=['metoprolol', 'warfarin', 'furosemide'],
        drop_ordinary=False,
    )
    assert terms == ['metoprolol', 'warfarin', 'furosemide']


# ==========================================================================
# Budgeting
# ==========================================================================


@pytest.mark.unit
def test_a_full_blueprint_is_cut_to_the_budget(real_terms):
    prompt = build_priming_prompt(select_priming_terms(frequent_subjects=real_terms))
    assert prompt
    assert estimate_prompt_tokens(prompt) <= PROMPT_TOKEN_BUDGET


@pytest.mark.unit
def test_a_smaller_budget_keeps_fewer_terms(real_terms):
    terms = select_priming_terms(frequent_subjects=real_terms)
    wide = build_priming_prompt(terms, PROMPT_TOKEN_BUDGET)
    narrow = build_priming_prompt(terms, 60)
    assert estimate_prompt_tokens(narrow) <= 60
    assert 0 < narrow.count(',') < wide.count(',')
    # And the narrow prompt is a suffix of the wide one's glossary: the cut
    # only ever comes off the front.
    assert wide.endswith(narrow.split('Terms: ', 1)[1])


@pytest.mark.unit
def test_a_budget_too_small_for_anything_yields_no_prompt():
    """Not a frame with an empty glossary -- nothing at all. See the docstring."""
    assert build_priming_prompt(['pheochromocytoma'], 1) == ''
    assert build_priming_prompt(['pheochromocytoma'], 0) == ''
    assert build_priming_prompt(['pheochromocytoma'], -5) == ''


@pytest.mark.unit
def test_one_absurd_term_cannot_take_the_whole_prompt_down():
    """A pathological entry subject is dropped; the rest of the glossary lives.

    Without the per-term length cap this is the nastiest failure available: the
    absurd term is the MOST relevant one, so it sits in the tail, never fits,
    and the truncation loop empties the list out and returns ''. Priming would
    silently switch itself off because one subject name was too long.
    """
    junk = 'x' * 4000
    prompt = build_priming_prompt(
        select_priming_terms(entry_subjects=[junk, 'metoprolol'],
                             frequent_subjects=['warfarin'])
    )
    assert junk not in prompt
    assert 'metoprolol' in prompt and 'warfarin' in prompt


@pytest.mark.unit
def test_a_huge_candidate_list_gives_the_same_answer_as_its_tail(real_terms):
    """The pre-trim is an optimisation and must not change the result."""
    padding = ['filler%04d' % n for n in range(2000)]
    big = build_priming_prompt(padding + real_terms)
    small = build_priming_prompt(real_terms)
    assert big == small
    assert 'filler' not in big


# ==========================================================================
# Token estimation -- the direction of error is the point
# ==========================================================================


@pytest.mark.unit
def test_estimate_leaves_headroom_against_the_measured_density(real_terms):
    """The estimate must OVER-count tokens, so the prompt UNDER-fills the budget.

    There is no Whisper tokeniser in this process (and this module adds no
    dependency to get one), so the check is against the two densities T3
    measured on this very glossary using whisper.cpp's overflow message: 3.46
    and 3.69 characters per token. ``priming.py`` divides by 3.3.

    Over-counting costs two or three glossary terms off the front, which is
    where the least relevant ones are. Under-counting hands the truncation back
    to the engine, which takes it from the front too -- but silently, and
    possibly through the terms that mattered. That asymmetry is why this test
    asserts a one-sided margin and not an accuracy band.
    """
    prompt = build_priming_prompt(select_priming_terms(frequent_subjects=real_terms))
    estimate = estimate_prompt_tokens(prompt)

    true_at_densest = len(prompt) / MEASURED_DENSEST
    true_at_sparsest = len(prompt) / MEASURED_SPARSEST

    assert true_at_densest <= PROMPT_TOKEN_BUDGET, (
        'the prompt would overflow whisper.cpp at the densest measured ratio '
        '(%.2f chars/token): %d chars implies %.0f tokens against a budget of '
        '%d. The engine would then truncate it from the front, silently.'
        % (MEASURED_DENSEST, len(prompt), true_at_densest, PROMPT_TOKEN_BUDGET)
    )
    assert estimate >= true_at_densest, (
        'the estimate under-counts even at the densest measured ratio, which '
        'is the wrong direction of error: estimate %d vs %.0f real.'
        % (estimate, true_at_densest)
    )
    # The margin, stated so a future reader knows what "conservative" bought.
    # 5-12% of the budget is 11-27 tokens of deliberate headroom.
    assert 1.03 <= estimate / true_at_densest <= 1.35
    assert 1.03 <= estimate / true_at_sparsest <= 1.45


@pytest.mark.unit
def test_the_structural_floor_catches_acronym_dense_text():
    """Where the character ratio under-counts, the floor has to take over.

    The ratio was calibrated on long Latin names. An acronym list is the
    opposite shape -- every acronym is split and every comma is its own token
    -- and it is exactly the vocabulary this feature exists to serve.
    """
    acronyms = 'ACE, DVT, CHF, MI, TIA, COPD, CVA, DKA, GERD, HTN.'
    by_ratio = len(acronyms) / 3.3
    assert estimate_prompt_tokens(acronyms) > by_ratio * 1.5


@pytest.mark.unit
def test_empty_text_is_zero_tokens():
    """What makes the empty-prompt contract hold at the arithmetic level."""
    assert estimate_prompt_tokens('') == 0
    assert estimate_prompt_tokens('   \n ') == 0


# ==========================================================================
# The empty contract
# ==========================================================================


@pytest.mark.unit
def test_no_terms_means_no_prompt_argument():
    """'' is the signal to omit --prompt entirely, not to pass an empty one."""
    assert build_priming_prompt([]) == ''
    assert build_priming_prompt(()) == ''
    assert select_priming_terms() == []
    assert build_priming_prompt(select_priming_terms()) == ''


@pytest.mark.unit
def test_terms_that_all_wash_out_mean_no_prompt():
    """Never a frame with an empty glossary behind it -- section 3.6."""
    assert build_priming_prompt(['', '   ', '...']) == ''
    assert build_priming_prompt(['Pathology', 'Cardiovascular System']) == ''


@pytest.mark.unit
def test_a_surviving_term_always_brings_the_frame():
    """The converse: a non-empty prompt is never a bare word list."""
    prompt = build_priming_prompt(['pheochromocytoma'])
    assert prompt.startswith(DEFAULT_PROMPT_FRAME)
    assert prompt.endswith('pheochromocytoma.')


# ==========================================================================
# Determinism
# ==========================================================================


@pytest.mark.unit
def test_same_inputs_give_the_same_prompt_every_time(real_terms):
    first = build_priming_prompt(select_priming_terms(
        entry_subjects=['metoprolol'], frequent_subjects=real_terms))
    for _ in range(20):
        assert build_priming_prompt(select_priming_terms(
            entry_subjects=['metoprolol'], frequent_subjects=real_terms)) == first


@pytest.mark.unit
def test_building_from_an_already_selected_list_changes_nothing(real_terms):
    """The pipeline is idempotent, so build_priming_prompt is safe on raw input."""
    selected = select_priming_terms(frequent_subjects=real_terms)
    assert select_priming_terms(frequent_subjects=selected) == selected
    assert build_priming_prompt(selected) == build_priming_prompt(real_terms)


# ==========================================================================
# De-duplication and case
# ==========================================================================


@pytest.mark.unit
def test_duplicates_are_dropped_case_insensitively():
    """One entry survives, and it is the LAST spelling offered.

    Last means best-ranked, because the list arrives in emit order. The
    surviving spelling is therefore the one the most relevant tier used.
    """
    prompt = build_priming_prompt(['Metoprolol', 'metoprolol', 'METOPROLOL'])
    assert glossary(prompt) == ['METOPROLOL']


@pytest.mark.unit
def test_a_duplicate_keeps_its_best_rank():
    """A term in two tiers belongs in the tail, at the better tier's position."""
    terms = select_priming_terms(
        entry_subjects=['warfarin'],
        frequent_subjects=['warfarin', 'pheochromocytoma'],
    )
    assert terms == ['pheochromocytoma', 'warfarin']


@pytest.mark.unit
def test_display_case_is_never_rewritten():
    """Case normalisation is for the dedup key only.

    Lower-casing 'COPD' to 'copd' would prime a spelling that never occurs, and
    acronyms are precisely the vocabulary this feature exists to serve.
    """
    prompt = build_priming_prompt(['COPD', 'IgA nephropathy', 'ACE inhibitor'])
    assert 'COPD' in prompt
    assert 'IgA nephropathy' in prompt
    assert 'ACE inhibitor' in prompt


@pytest.mark.unit
@pytest.mark.parametrize('raw, expected', [
    ('  metoprolol  ', 'metoprolol'),
    ('acute\ttubular   necrosis', 'acute tubular necrosis'),
    ('Diabetes, type 2', 'Diabetes type 2'),       # an internal comma would
    ('Sepsis; bacteremia', 'Sepsis bacteremia'),   # split one term into two
    ('warfarin\n', 'warfarin'),
    ('Cardiology:', 'Cardiology'),
    ('', ''),
    ('   ', ''),
    ('...', ''),
    ('x' * 200, ''),
])
def test_normalise_term(raw, expected):
    assert normalise_term(raw) == expected


@pytest.mark.unit
def test_an_internal_comma_cannot_forge_a_second_glossary_entry():
    prompt = build_priming_prompt(['Diabetes, type 2'])
    assert glossary(prompt) == ['Diabetes type 2']


# ==========================================================================
# Ordinary English
# ==========================================================================


@pytest.mark.unit
@pytest.mark.parametrize('term, ordinary', [
    # Dropped: the glossary the task names as buying nothing.
    ('Cardiovascular', True),
    ('Pathology', True),
    ('Cardiovascular System', True),
    ('General Principles', True),
    ('Other Topics', True),
    ('Unit 3', True),
    ('Algebra', True),
    ('Reading and Writing', True),
    # Kept: what actually needs priming.
    ('metoprolol', False),
    ('hypertensive nephrosclerosis', False),
    ('pheochromocytoma', False),
    ('ACE inhibitor', False),      # 'ace' is ordinary; the casing rescues it
    ('MI', False),                 # NOT a Roman numeral. There is no such rule.
    # Kept because the stoplist is a stoplist and not a dictionary: absence
    # means keep. 'Lymphoreticular' is not in it, so the whole phrase stays,
    # which costs a few tokens at the least relevant end and risks nothing.
    ('Blood & Lymphoreticular System', False),
    ('COPD', False),
    ('IgA nephropathy', False),
    ('HbA1c', False),
    ('Multisystem Processes & Disorders', False),
])
def test_is_ordinary_english(term, ordinary):
    assert is_ordinary_english(term) is ordinary


@pytest.mark.unit
def test_ordinary_terms_are_dropped_from_the_glossary():
    terms = select_priming_terms(
        entry_subjects=['hypertensive nephrosclerosis'],
        ancestors=['Cardiovascular System', 'Pathology'],
    )
    assert terms == ['hypertensive nephrosclerosis']


@pytest.mark.unit
def test_the_ordinary_filter_can_be_switched_off():
    """A caller that has curated its own terms should not be second-guessed."""
    assert select_priming_terms(ancestors=['Pathology'], drop_ordinary=False) \
        == ['Pathology']
    assert 'Pathology' in build_priming_prompt(['Pathology'], drop_ordinary=False)


@pytest.mark.unit
def test_the_stoplist_is_lower_case():
    """Lookups are done on the lower-cased word, so a capital here is dead weight."""
    assert all(word == word.lower() for word in ORDINARY_ENGLISH_WORDS)


@pytest.mark.unit
def test_dropping_ordinary_terms_buys_real_budget(real_terms):
    """The filter is not cosmetic: the budget it frees goes to real vocabulary.

    Where it earns its keep is the *ancestors* tier, not the fallback one. An
    ancestor of a tagged subject is usually a blueprint heading -- exactly the
    "Cardiovascular, Pathology" case -- and it ranks high, so without the
    filter it sits safely in the tail and pushes real drug names off the front.
    (A frequent-subjects list is the opposite: its ordinary entries are at the
    least relevant end and truncation would have taken them anyway, so
    measuring there measures nothing.)
    """
    ancestors = ['Cardiovascular System', 'Pathology', 'General Principles',
                 'Other Topics', 'Human Development']
    kwargs = dict(entry_subjects=['hypertensive nephrosclerosis'],
                  ancestors=ancestors, frequent_subjects=real_terms)

    filtered = glossary(build_priming_prompt(select_priming_terms(**kwargs)))
    unfiltered = glossary(build_priming_prompt(
        select_priming_terms(drop_ordinary=False, **kwargs), drop_ordinary=False))

    assert not set(ancestors) & set(filtered)
    assert set(ancestors) <= set(unfiltered)
    bought = [term for term in filtered if term not in unfiltered]
    assert bought, (
        'the ordinary-English filter freed no budget for real vocabulary; it '
        'is meant to trade blueprint headings for drug names'
    )


# ==========================================================================
# Shape of the string
# ==========================================================================


@pytest.mark.unit
def test_the_prompt_is_a_frame_then_a_comma_separated_glossary():
    prompt = build_priming_prompt(['warfarin', 'metoprolol'])
    assert prompt == DEFAULT_PROMPT_FRAME + ' warfarin, metoprolol.'


@pytest.mark.unit
def test_a_caller_may_supply_its_own_frame():
    prompt = build_priming_prompt(['warfarin'], frame='A medical student. Terms:')
    assert prompt == 'A medical student. Terms: warfarin.'


@pytest.mark.unit
def test_the_default_frame_names_no_subject_matter():
    """A WIMI exam context can be an SAT tree; the prompt must not claim otherwise.

    The T3 harness frame says 'a medical exam question' because its corpus is
    medical. The product's default deliberately does not -- the decoder
    conditions on this text.
    """
    lowered = DEFAULT_PROMPT_FRAME.lower()
    for word in ('medical', 'medicine', 'clinical', 'usmle', 'sat'):
        assert word not in lowered


@pytest.mark.unit
def test_the_prompt_is_a_single_line(real_terms):
    """It is handed to a subprocess as one argv element. Newlines have no business."""
    prompt = build_priming_prompt(select_priming_terms(
        entry_subjects=['acute\ntubular necrosis'], frequent_subjects=real_terms))
    assert '\n' not in prompt and '\r' not in prompt
