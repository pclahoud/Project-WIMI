"""Subject terms to a whisper.cpp ``--prompt`` string, inside a measured budget (#59, T10).

Whisper's ``initial_prompt`` biases decoding toward the words in it. That is a
Whisper *decoding* feature rather than an engine feature (#59 comment #1583), so
everything here holds for any backend that ever runs.

THE ONE RULE THAT LOOKS BACKWARDS AND IS NOT
--------------------------------------------

**Terms are emitted least relevant FIRST and most relevant LAST.**

whisper.cpp's usable prompt is ``n_text_ctx / 2 - 1`` = **223 tokens** for the
448-context models. Task T1 verified that three ways -- the binary's own log
line, whisper.cpp's source, and OpenAI's reference ``decoding.py`` using the
identical tail-slice formula -- and verified that when a prompt is longer than
that, whisper.cpp **keeps the tail and discards the front, silently**: exit 0,
nothing on stderr, and with ``-np`` not even the tokenizer's own warning.

So the end of the string is the part that survives, and the end is where the
subjects on the open entry belong.

The first draft of the plan said to truncate "nearest-first", which would have
placed the most relevant terms at the front -- exactly the part that is thrown
away, with nothing reporting it. A student would have got priming that was
switched on and made of whichever terms happened to sort last. That was a
correctness bug, not a refinement (plan section 0.1, finding 2; section 3.6).

If reverse order ever looks like a mistake to you, read
``tests/app/test_stt_priming.py::test_over_budget_keeps_the_best_term_and_drops_the_worst``
before changing it. It exists for this.

THE SAME RULE, ONE STEP ALONG: AN ALIAS IS NOT A TIER
-----------------------------------------------------

**An alias inherits the rank of the subject it names** (owner's decision,
section 3.6 as revised). Ranking aliases as their own tier below siblings is
the tail-keeping bug wearing a different hat: a flat alias tier is discarded
*before* the siblings above it, so a student explaining atrial fibrillation
keeps some sibling topic's canonical name and loses **"afib"** -- the name they
are most likely to actually say, for the subject they are actually explaining.
Correct-looking, silent, and worst exactly where the feature should be
strongest.

So the tiers take *subjects*, and a subject may carry its aliases. There is no
``aliases=`` parameter, and ``select_priming_terms`` has none to flatten.

WHAT THIS MODULE IS AND IS NOT
------------------------------

Pure functions over strings. No database, no Qt, no subprocess, no I/O at all.
Whoever calls it fetches the subject data; keeping it pure is what makes it
testable and what keeps it clear of the worker-thread rules in section 3.4.

``build_priming_prompt([]) == ''``, and **an empty string means pass no
``--prompt`` argument at all** -- not ``--prompt ""``. An empty prompt still
costs a tokenizer round trip and still conditions the decoder on nothing, and
a frame with no glossary behind it ("... in their own words. Terms:") is a
dangling sentence, which section 3.6 records as the shape that pushes Whisper
toward hallucination and looping on short inputs. The caller writes::

    prompt = build_priming_prompt(terms)
    if prompt:
        cmd += ['--prompt', prompt]

RELATION TO ``scripts/stt_measure.py``
--------------------------------------

The T3 accuracy harness contains ``build_prompt``/``estimate_tokens``, which
were used for the real transcription measurements. This module agrees with it
on everything load-bearing: the 223-token budget, the tail-keeping order,
truncating from the front here rather than in the engine, and the
characters-per-token ratio and the measurement behind it. It is deliberately
**not imported** -- that file is a measurement script and adds no dependency to
the product -- and it differs in three stated places, each marked ``[differs
from stt_measure]`` below.

Plan: ``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` sections 0.1 and 3.6.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from enum import IntEnum

__all__ = [
    'PROMPT_TOKEN_BUDGET',
    'DEFAULT_PROMPT_FRAME',
    'TermSource',
    'TERM_SOURCES_MOST_RELEVANT_FIRST',
    'ORDINARY_ENGLISH_WORDS',
    'estimate_prompt_tokens',
    'normalise_term',
    'is_ordinary_english',
    'select_priming_terms',
    'build_priming_prompt',
]


#: whisper.cpp's usable prompt budget, ``n_text_ctx / 2 - 1`` for the
#: 448-context models. Measured by task T1, not guessed, and enforced here
#: because overflow in the engine is silent.
PROMPT_TOKEN_BUDGET = 223

#: The natural-language frame the glossary hangs off. A bare comma-separated
#: word list with no frame is known to push Whisper toward hallucination and
#: looping on short inputs (section 3.6), so there is always a frame.
#:
#: [differs from stt_measure] The harness frame says "a medical exam question",
#: because its corpus is medical. This one does not: a WIMI exam context can be
#: an SAT tree as easily as a USMLE one (CLAUDE.md's hierarchy-level example is
#: Section / Domain / Skill), and the prompt is text the decoder conditions on,
#: so telling it "medical" while the student explains a geometry question is a
#: false context cue. A caller that knows the exam's subject matter can pass a
#: more specific ``frame``.
#:
#: **The frame is load-bearing, and this was measured, not assumed** (#59
#: comment #2271, 2026-09-23, against the owner's own 11 s recording). Whisper's
#: ``--prompt`` conditions the decoder as if the string were *preceding
#: transcript text*, so fluent prose primes and a bare token list does not. On
#: the out-of-vocabulary proper noun "WIMI", against `tiny.en`, `base.en` and
#: `small.en` alike:
#:
#: * no prompt                     -> "Winnie", 0/3
#: * ``'WIMI'`` alone              -> "Wimmy", 0/3
#: * ``'WIMI, spelled W-I-M-I.'``  -> "Wimmy", 0/3
#: * this frame + ``'Terms: ..., WIMI.'`` -> **"WIMI", 3/3**
#:
#: So deleting the frame to "just send the terms" costs 3/3 -> 0/3, silently,
#: and looks like tidying up boilerplate. It is the sentence that makes the
#: glossary read as language. Model size did not matter in that test and the
#: prompt did: `small.en` (466 MB) unprimed failed where `tiny.en` (75 MB)
#: primed succeeded.
DEFAULT_PROMPT_FRAME = (
    'A student is explaining an exam question out loud, in their own words. Terms:'
)

#: Characters per Whisper BPE token, measured rather than guessed -- see
#: ``scripts/stt_measure.py``'s ``_CHARS_PER_TOKEN`` for the instrument. In
#: short: whisper.cpp's tokenizer prints the true token count when a prompt
#: overflows its 1024-token tokenize buffer, and four probe strings built from
#: this project's own priming glossary came out at 3.69 characters per token
#: (within 0.3% of each other), while a single budget-sized prompt came out
#: denser at 3.46. The ratio moves with the mix of long Latin names and short
#: framing words, so it is a range and not a constant.
#:
#: 3.3 sits below the whole measured range on purpose. **Under-filling is the
#: intended direction of error.** Dividing by a smaller number produces a
#: LARGER token estimate, so the budget is reached sooner and a couple of
#: glossary terms are dropped that would in fact have fitted -- and they are
#: dropped off the FRONT, which is where the least relevant terms live.
#: Estimating the other way would hand the truncation back to the engine, which
#: also cuts from the front but silently, and with no idea which terms mattered.
_CHARS_PER_TOKEN = 3.3

#: A single term longer than this is dropped rather than truncated. An exam
#: subject name is a phrase; a paragraph in that field is bad data. Without the
#: cap one pathological "term" attached to the open entry would be the most
#: relevant candidate, fail to fit on its own, and take the entire prompt down
#: with it -- the truncation loop would empty out and return ''.
_MAX_TERM_CHARS = 80

#: Characters that are separators in the rendered glossary, or noise at the
#: edge of a subject name. An internal one is replaced with a space so a
#: subject called "Diabetes, type 2" cannot render as two glossary entries.
_SEPARATOR_CHARS = ',;'
_EDGE_PUNCTUATION = ' \t\r\n.,;:!?-_/\\|*"\'()[]{}'


class TermSource(IntEnum):
    """Where a candidate term came from. **Lower is more relevant.**

    The subjects tagged on the open entry, then their ancestors, then the
    siblings under the same parents, then the exam context's most-used subjects
    as the fallback when nothing is tagged yet.

    **An alias is not a tier. An alias inherits the rank of the subject it
    names** (owner's decision, plan section 3.6 as revised). A flat alias tier
    below siblings is the tail-keeping bug in a second costume: the glossary is
    emitted least relevant first, so a tier-3 alias set is discarded *before*
    tier-2 siblings. A student explaining atrial fibrillation would keep some
    sibling topic's canonical name and lose "afib" -- the alternate name they
    are most likely to actually say, for the subject they are actually
    explaining. Correct-looking, silent, and worst exactly where the feature is
    supposed to be strongest.

    So an alias of an entry subject ranks ``ENTRY_SUBJECT``, an alias of an
    ancestor ranks ``ANCESTOR``, an alias of a sibling ranks ``SIBLING``, and an
    alias of a fallback subject ranks ``FREQUENT``. This is what finally makes
    section 3.6's "an alias is the single highest-value source here" true in the
    code: an alias now sits wherever its subject sits.
    """

    ENTRY_SUBJECT = 0
    ANCESTOR = 1
    SIBLING = 2
    FREQUENT = 3


#: The tier order in one place, most relevant first, as ``select_priming_terms``
#: keyword names. The emitted prompt is this list reversed.
#:
#: There is deliberately no ``aliases`` entry: an alias rides with its owner in
#: whichever of these tiers the owner is in. See ``TermSource``.
TERM_SOURCES_MOST_RELEVANT_FIRST = (
    ('entry_subjects', TermSource.ENTRY_SUBJECT),
    ('ancestors', TermSource.ANCESTOR),
    ('siblings', TermSource.SIBLING),
    ('frequent_subjects', TermSource.FREQUENT),
)


# ==========================================================================
# Ordinary English
#
# A glossary of "Cardiovascular, Pathology" buys nothing and spends budget:
# Whisper transcribes those words correctly without being told. What needs
# priming is the vocabulary that a general English model gets wrong -- drug
# names, eponyms, acronyms, long Latin compounds.
#
# This is a STOPLIST, not a dictionary. Membership means "drop"; absence means
# "keep", which is the safe default, because dropping a term the student
# actually needed is a worse outcome than spending four tokens on one they did
# not. It is also deliberately domain-NEUTRAL apart from one small block:
# WIMI's exam contexts are not all medical, and a medical stoplist applied to
# an SAT tree would be both useless and wrong.
# ==========================================================================

ORDINARY_ENGLISH_WORDS = frozenset({
    # -- function words --------------------------------------------------
    'a', 'an', 'and', 'as', 'at', 'by', 'for', 'from', 'in', 'into', 'is',
    'of', 'on', 'or', 'the', 'to', 'with', 'without', 'within', 'per', 'via',
    'between', 'among', 'across', 'about', 'under', 'over', 'their', 'its',
    # -- blueprint scaffolding: words an outline uses to organise itself --
    'system', 'systems', 'section', 'sections', 'chapter', 'chapters', 'unit',
    'units', 'module', 'modules', 'part', 'parts', 'topic', 'topics', 'area',
    'areas', 'domain', 'domains', 'skill', 'skills', 'subject', 'subjects',
    'category', 'categories', 'group', 'groups', 'level', 'levels', 'block',
    'blocks', 'item', 'items', 'list', 'lists', 'set', 'sets', 'type', 'types',
    'general', 'principles', 'principle', 'fundamental', 'fundamentals',
    'basic', 'basics', 'introduction', 'intro', 'overview', 'review',
    'concept', 'concepts', 'misc', 'miscellaneous', 'other', 'others',
    'related', 'advanced', 'core', 'foundation', 'foundations', 'applied',
    'practice', 'theory', 'method', 'methods', 'approach', 'approaches',
    'problem', 'problems', 'question', 'questions', 'answer', 'answers',
    'exam', 'test', 'tests', 'testing', 'study', 'studies', 'course',
    # -- everyday words that turn up inside subject names ----------------
    'health', 'disease', 'diseases', 'disorder', 'disorders', 'condition',
    'conditions', 'process', 'processes', 'function', 'functions', 'structure',
    'structures', 'development', 'growth', 'aging', 'normal', 'abnormal',
    'human', 'body', 'blood', 'heart', 'lung', 'lungs', 'brain', 'skin',
    'bone', 'bones', 'muscle', 'muscles', 'nerve', 'nerves', 'kidney',
    'kidneys', 'liver', 'stomach', 'eye', 'eyes', 'ear', 'ears', 'failure',
    'infection', 'infections', 'injury', 'injuries', 'pain', 'cancer',
    'treatment', 'treatments', 'therapy', 'therapies', 'drug', 'drugs',
    'diagnosis', 'symptom', 'symptoms', 'sign', 'signs', 'risk', 'care',
    'social', 'behavioral', 'behavioural', 'behavior', 'behaviour', 'mental',
    'special', 'senses', 'tissue', 'tissues', 'cell', 'cells', 'life',
    'water', 'energy', 'light', 'heat', 'force', 'motion', 'time', 'space',
    'number', 'numbers', 'data', 'change', 'changes', 'first', 'second',
    'third', 'new', 'old', 'early', 'late', 'high', 'low', 'small', 'large',
    # -- common academic subject names ------------------------------------
    # These are the "Cardiovascular, Pathology" case from the task. Every one
    # is a word a general English model transcribes correctly every time, and
    # every one turns up as a node name in a real subject tree.
    'anatomy', 'physiology', 'pathology', 'pharmacology', 'microbiology',
    'immunology', 'biochemistry', 'genetics', 'histology', 'embryology',
    'epidemiology', 'biostatistics', 'statistics', 'nutrition', 'psychiatry',
    'psychology', 'sociology', 'neurology', 'cardiology', 'oncology',
    'radiology', 'surgery', 'medicine', 'science', 'sciences', 'nursing',
    'biology', 'chemistry', 'physics', 'mathematics', 'math', 'maths',
    'algebra', 'geometry', 'trigonometry', 'calculus', 'arithmetic',
    'history', 'geography', 'economics', 'philosophy', 'literature',
    'reading', 'writing', 'grammar', 'vocabulary', 'language', 'languages',
    'english', 'composition', 'rhetoric', 'logic', 'law', 'ethics',
    'accounting', 'finance', 'business', 'management', 'marketing',
    'engineering', 'computing', 'programming', 'software', 'hardware',
    'cardiovascular', 'respiratory', 'renal', 'urinary', 'endocrine',
    'gastrointestinal', 'musculoskeletal', 'reproductive', 'nervous',
    'immune', 'lymphatic', 'digestive', 'subcutaneous',
})

_WORD_SPLIT = re.compile(r'[\s/&+]+')
_DIGITS_ONLY = re.compile(r'^\d+(?:[.,]\d+)*$')


def is_ordinary_english(term: str) -> bool:
    """True when ``term`` is made entirely of words Whisper already knows.

    A term is ordinary when **every** word in it is ordinary, so one unusual
    word rescues the whole phrase: "Cardiovascular System" goes, "hypertensive
    nephrosclerosis" stays, and "ACE inhibitor" stays because of the acronym
    even though "ace" is an ordinary English word on its own.

    Three rules decide a single word, in this order:

    1. An **acronym** -- two or more letters, all upper case -- is never
       ordinary. This is what protects ACE, COPD, DVT and MI, and it is the
       reason the stoplist can contain everyday words like "ace" at all.
       (A shouty all-capitals import therefore keeps everything, which wastes
       a little budget and loses nothing.)
    2. A word that is **only digits** is scaffolding: "Unit 3", "1.2". Note
       there is no Roman-numeral rule, deliberately -- "MI" is a heart attack.
    3. Otherwise, ordinary iff its lower-cased form is in
       ``ORDINARY_ENGLISH_WORDS``.

    An empty or punctuation-only term is ordinary, which is how it gets
    dropped.
    """
    words = [w.strip(_EDGE_PUNCTUATION) for w in _WORD_SPLIT.split(term or '')]
    words = [w for w in words if w]
    if not words:
        return True
    for word in words:
        if len(word) >= 2 and word.isupper() and any(c.isalpha() for c in word):
            return False  # acronym
        if _DIGITS_ONLY.match(word):
            continue  # section numbering, not vocabulary
        if word.lower() not in ORDINARY_ENGLISH_WORDS:
            return False
    return True


# ==========================================================================
# Normalisation
# ==========================================================================


def normalise_term(term: str) -> str:
    """Clean one candidate term, or return ``''`` if nothing usable is left.

    Case is **not** changed. Case normalisation here is for the de-duplication
    key only (see ``_dedupe_keep_last``); rewriting the display form would turn
    "COPD" into "Copd" and prime a spelling that never occurs. Acronyms and
    proper names are exactly the vocabulary this feature exists to serve.

    What is changed: NFKC folding, control characters and newlines removed,
    whitespace collapsed, commas and semicolons replaced by a space so a
    subject named "Diabetes, type 2" cannot masquerade as two glossary
    entries, and edge punctuation stripped. A term longer than
    ``_MAX_TERM_CHARS`` is rejected outright -- see that constant.
    """
    if not term:
        return ''
    text = unicodedata.normalize('NFKC', term)
    text = ''.join(
        ' ' if (ch in _SEPARATOR_CHARS or unicodedata.category(ch)[0] == 'C') else ch
        for ch in text
    )
    text = ' '.join(text.split()).strip(_EDGE_PUNCTUATION).strip()
    if not text or len(text) > _MAX_TERM_CHARS:
        return ''
    return text


def _dedupe_keep_last(terms: Sequence[str]) -> list[str]:
    """De-duplicate case-insensitively, keeping the LAST occurrence.

    The list is in emit order -- least relevant first -- so the last occurrence
    is the best-ranked one, and keeping it is what makes a term that is both an
    exam-wide frequent subject and a subject on the open entry land in the tail
    where it survives truncation.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for term in reversed(terms):
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(term)
    kept.reverse()
    return kept


def _prepare(terms: Iterable[str], *, drop_ordinary: bool) -> list[str]:
    """Normalise, drop the unusable and the ordinary, de-duplicate.

    Idempotent, so it is safe for ``build_priming_prompt`` to run it over the
    output of ``select_priming_terms``, which has already run it.
    """
    cleaned: list[str] = []
    for term in terms:
        text = normalise_term(term)
        if not text:
            continue
        if drop_ordinary and is_ordinary_english(text):
            continue
        cleaned.append(text)
    return _dedupe_keep_last(cleaned)


# ==========================================================================
# Token estimation
# ==========================================================================


def estimate_prompt_tokens(text: str) -> int:
    """Estimated Whisper BPE token count for ``text``, biased to over-count.

    There is no Whisper tokeniser in this process and this module adds no
    dependency to ``requirements-prod.txt`` to get one, so the count is
    estimated. The estimate is the larger of two things:

    * ``len(text) / 3.3``, the measured character ratio -- see
      ``_CHARS_PER_TOKEN`` for where 3.3 comes from and why it is below the
      measured range rather than in the middle of it.
    * a **structural floor**. Whisper inherits GPT-2's byte-level BPE, whose
      pre-tokenizer splits on whitespace before any merge, so a merge can never
      span two words: every whitespace-delimited word costs at least one token,
      and a punctuation character is almost always cut off into one of its own.
      An all-capitals run of two or more letters is counted as two, because
      whole upper-case words are largely absent from the vocabulary and get
      split. Where that last rule over-counts -- a short acronym that does
      happen to be one token -- it over-counts, which is the safe direction.

    The floor is what makes this safe for the acronym-dense end of the exam
    vocabulary. "ACE, DVT, CHF, MI, TIA" is 22 characters -- 7 tokens by the
    ratio, and nearer 15 in reality, because each acronym is split and each
    comma is its own token. The character ratio was calibrated on a glossary of
    long Latin names, where it holds well; the floor covers the other end.

    Whitespace-only text is 0 tokens, which is what makes the empty-prompt
    contract hold.
    """
    if not text or not text.strip():
        return 0
    by_chars = math.ceil(len(text) / _CHARS_PER_TOKEN)
    floor = 0
    for word in text.split():
        floor += 1
        core = word.strip(_EDGE_PUNCTUATION)
        if len(core) >= 2 and core.isupper() and any(c.isalpha() for c in core):
            floor += 1
        floor += sum(1 for ch in word if not ch.isalnum())
    return max(by_chars, floor)


# ==========================================================================
# Selection
# ==========================================================================

#: Keys an alias mapping may use for its text, in the order they are tried.
#: ``alias_name`` is ``SubjectAlias.to_dict()``'s, which is what
#: ``get_all_subjects_with_aliases_for_exam`` puts in each row's ``aliases``.
_ALIAS_TEXT_KEYS = ('alias_name', 'name', 'alias', 'text')


def _alias_text(alias: object) -> str:
    """One alias, however the caller's row happens to spell it."""
    if isinstance(alias, str):
        return alias
    if isinstance(alias, Mapping):
        for key in _ALIAS_TEXT_KEYS:
            value = alias.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ''


def _candidate_terms(candidate: object) -> list[str]:
    """A tier entry expanded to ``[subject_name, *its aliases]``.

    The subject's own name comes first and its aliases follow, so the group
    reads least-relevant-first like everything else here: if a truncation ever
    falls inside the group, the alias -- the name the student actually says --
    is the half that survives.

    A candidate the parser cannot make sense of yields nothing. That is the
    safe failure: a malformed row costs its own priming, not the prompt.

    **A candidate with no name yields nothing at all, aliases included.** A
    subject with no name has no rank to lend, so its aliases have none either,
    and letting them through would smuggle an ownerless alias in at whatever
    tier the row happened to sit in -- the flat alias tier through a side door.
    """
    if isinstance(candidate, str):
        return [candidate]
    if isinstance(candidate, Mapping):
        name = candidate.get('name') or candidate.get('subject_name') or ''
        aliases = candidate.get('aliases') or ()
    elif isinstance(candidate, Sequence):
        if len(candidate) != 2:
            return []
        name, aliases = candidate[0], candidate[1] or ()
    else:
        return []
    if not isinstance(name, str) or not name.strip():
        return []
    if isinstance(aliases, (str, Mapping)):
        aliases = (aliases,)
    terms = [name]
    terms.extend(text for text in map(_alias_text, aliases) if text)
    return terms


def select_priming_terms(
    *,
    entry_subjects: Iterable[object] = (),
    ancestors: Iterable[object] = (),
    siblings: Iterable[object] = (),
    frequent_subjects: Iterable[object] = (),
    drop_ordinary: bool = True,
) -> list[str]:
    """Rank the candidates and return them **in emit order**.

    Emit order is least relevant first, most relevant last, ready to hand
    straight to :func:`build_priming_prompt`. The caller does not reverse
    anything; if the returned list looks upside down, that is the point, and
    the module docstring says why.

    Tiers, most relevant first: ``entry_subjects`` (the subjects tagged on the
    open entry), ``ancestors``, ``siblings`` (the subjects under the same
    parents -- a student explaining hypertensive nephrosclerosis is likely to
    say "hypertension" too), and ``frequent_subjects`` (the exam context's
    most-used subjects, the fallback for an entry with nothing tagged yet).
    Section 3.6 lists where each comes from in the database.

    **Each tier takes subjects, and a subject may carry its aliases**, because
    an alias ranks with the subject it names rather than in a tier of its own
    (see ``TermSource`` for why that is a correctness matter and not a
    preference). A tier entry is either:

    * a plain ``str`` -- a subject with no aliases; or
    * a ``(name, aliases)`` pair; or
    * a mapping with ``name`` and ``aliases``, which is exactly the shape
      ``AliasesMixin.get_all_subjects_with_aliases_for_exam`` already returns,
      so the caller passes those rows straight through. Each alias in it may be
      a ``str`` or a mapping carrying ``alias_name`` / ``name`` / ``alias``,
      which covers ``SubjectAlias.to_dict()``.

    **There is no ``aliases=`` parameter and adding one back is the bug.** A
    bag of aliases with no owner cannot be ranked, and the old flat tier put it
    mid-order where it silently outranked nothing and was outranked by
    everything. A caller that genuinely has ownerless aliases puts them in
    ``frequent_subjects``, which ranks them with the fallback tier -- the
    documented floor, not a silent middle.

    Within a tier the caller's own order is preserved and is the only
    tie-break, so the caller decides what "first" means there -- pass a list,
    not a set, or the prompt stops being deterministic. A subject's aliases sit
    immediately **after** it, i.e. slightly more relevant, so if the cut ever
    lands inside that group the spoken name is the half kept. Across tiers, a
    term that appears twice keeps its **best** rank.

    ``drop_ordinary=False`` turns off the ordinary-English filter, for a caller
    that has already curated its terms.
    """
    by_tier = {
        'entry_subjects': entry_subjects,
        'ancestors': ancestors,
        'siblings': siblings,
        'frequent_subjects': frequent_subjects,
    }
    # Built least-relevant-first by walking the tier order backwards, so the
    # list is already in emit order and _dedupe_keep_last's "keep the last
    # occurrence" resolves a cross-tier duplicate to its best rank.
    ordered: list[str] = []
    for name, _source in reversed(TERM_SOURCES_MOST_RELEVANT_FIRST):
        for candidate in by_tier[name]:
            ordered.extend(_candidate_terms(candidate))
    return _prepare(ordered, drop_ordinary=drop_ordinary)


# ==========================================================================
# The prompt
# ==========================================================================


def _render(frame: str, terms: Sequence[str]) -> str:
    glossary = ', '.join(terms) + '.'
    return (frame + ' ' + glossary) if frame else glossary


def build_priming_prompt(
    terms: Sequence[str],
    budget: int = PROMPT_TOKEN_BUDGET,
    *,
    frame: str = DEFAULT_PROMPT_FRAME,
    drop_ordinary: bool = True,
) -> str:
    """Render ``terms`` as a whisper.cpp ``--prompt`` string within ``budget``.

    ``terms`` is in **emit order: least relevant first, most relevant last** --
    what :func:`select_priming_terms` returns. The result is a frame followed
    by a comma-separated glossary, cut from the front until it fits, so the
    terms that survive are the ones at the end of the list.

    **An empty return means pass no ``--prompt`` argument at all.** Not
    ``--prompt ''``. It happens when there are no terms, when every term is
    dropped as unusable or as ordinary English, when ``budget`` is not
    positive, or when not even the frame plus one term fits.

    [differs from stt_measure] The harness returns its bare frame when the
    glossary empties out, because it is measuring "priming on" as a condition
    and wants the condition to exist. The product must not: a frame with no
    glossary is a dangling sentence with nothing to bias toward, and section
    3.6 records that shape as the one that pushes Whisper toward hallucination
    and looping on short inputs. Here it collapses to '' and the flag is
    omitted.

    The function re-runs normalisation, the ordinary-English filter and
    de-duplication over whatever it is given, so it is safe to call on a raw
    list. That pipeline is idempotent, so a list from
    :func:`select_priming_terms` passes through unchanged.

    Deterministic: same ``terms``, same ``budget``, same ``frame``, same
    string, always. There is no set iteration, no dictionary ordering and no
    randomness anywhere in the path.
    """
    if budget <= 0:
        return ''
    frame = ' '.join((frame or '').split()).strip()
    kept = _prepare(terms, drop_ordinary=drop_ordinary)
    if not kept:
        return ''

    # The exact loop below rebuilds the string once per dropped term. That is
    # fine for the tens of terms this normally sees, but a caller could hand
    # over a whole imported outline, so first drop the front that no budget
    # could ever pay for. _CHARS_PER_TOKEN is the most generous characters-per
    # -token ratio this module will ever assume, so this can only ever remove
    # terms the loop was going to remove anyway.
    max_chars = int(budget * _CHARS_PER_TOKEN) + len(frame) + 2
    running = 0
    first_reachable = len(kept)
    for index in range(len(kept) - 1, -1, -1):
        running += len(kept[index]) + 2  # the term and its ", " separator
        if running > max_chars:
            break
        first_reachable = index
    kept = kept[first_reachable:]

    while kept:
        candidate = _render(frame, kept)
        if estimate_prompt_tokens(candidate) <= budget:
            return candidate
        # From the FRONT. The front is the least relevant end, and the engine
        # would cut here too -- silently. See the module docstring.
        kept.pop(0)
    return ''
