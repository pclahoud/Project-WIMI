"""One noun per thing in the Related Topics copy (#402).

Three real things in that panel, and they used to share a word:

====================================  ==============================
the artifact the student installed     **"this version of WIMI"**
the other, larger artifact (#337)      **"the full version"**
the 845 MB model file fetched after    **"the download"**, "download the model"
====================================  ==============================

"Download" is reserved for the model because it is the only one of the three
the student can act on from this panel — which is also what makes the button
beside the sentence, **Download the model**, the right antecedent instead of a
misleading one.

The defect was circular rather than merely loose. ``model_not_downloaded`` is
the first state most students ever see, and it read:

    WIMI needs to **download** the model once (845 MB). It is not included in
    the **download**, so that WIMI stays small for people who do not use this.

The second "download" means the WIMI package. Its nearest antecedent is the
model download four words earlier, so the sentence says *the model is not
included in the model download*. ``not_in_this_build`` then used the same word
for the artifact twice with no model in sight, and ``runtime_broken`` for a
third referent.

Why a source sweep is the right instrument
------------------------------------------
Three of the five states are unreachable on any one machine — this box reports
``dev_runtime_missing`` (no torch in ``.venv``), a relations checkout reports
``ready`` or ``model_not_downloaded``, and ``not_in_this_build`` needs the
default artifact. So a rendered test could only ever see one sentence, and
would be a property of the machine rather than of the copy (#186's lesson).
The ambiguity is in the text and is established by reading it, which is how
#402 was confirmed in the first place.

**The sweep must not ban the word.** "The download" naming the model fetch is
the *sanctioned* use, and the ``partial`` clause — "so the download carries on
from where it stopped" — depends on it. A guard that banned the noun outright
would read as stricter and would delete the one correct use, so
:func:`test_the_sanctioned_use_of_the_noun_is_not_flagged` is here to fail if
anybody tightens it that way.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_relation_proposals_markup import js_string_literals

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_JS = REPO_ROOT / 'src' / 'web' / 'js' / 'settings.js'
PROPOSALS_JS = REPO_ROOT / 'src' / 'web' / 'js' / 'relation_proposals.js'

#: Phrases that can only name an artifact. "the download" is absent on
#: purpose: it is the sanctioned name for the model fetch.
ARTIFACT_SENSE = (
    'download of wimi',
    'larger download',
    'smaller download',
    'this download',
    'that download',
    'included in the download',
    'fault in the download',
    'part of any download',
)

#: What the artifact is called instead, in the two states that name one.
SANCTIONED = ('this version of WIMI', 'the full version')


def _student_facing(source: str) -> list[str]:
    """Single-quoted literals, comments skipped.

    Both files reason about "the larger download" in their *comments*, which
    is the repo's internal vocabulary and reaches nobody. What is left is
    `textContent`, `title` and toast copy.

    **One reader, shared with `test_relation_proposals_markup.py`.** The
    regex version it used to carry desynchronised on a trailing comment
    containing an apostrophe and then returned the code between the literals
    instead of the literals — measured here first, when this sweep reported no
    occurrences of "download" in a file that has one. Two sweeps with two
    readers is how one of them ends up passing over text it cannot see, so
    there is one.
    """
    return js_string_literals(source)


def _status_block() -> str:
    source = SETTINGS_JS.read_text(encoding='utf-8')
    start = source.index('renderRelationsStatus(status, failure) {')
    end = source.index('_relationsMissingList(missing)', start)
    return source[start:end]


def _offenders(strings: list[str]) -> list[tuple[str, str]]:
    found = []
    for text in strings:
        lowered = text.lower()
        for phrase in ARTIFACT_SENSE:
            if phrase in lowered:
                found.append((phrase, text))
    return found


@pytest.fixture(scope='module')
def status_sentences() -> list[str]:
    return _student_facing(_status_block())


# ==================== the rule ====================

def test_no_state_sentence_calls_the_artifact_a_download(status_sentences):
    """All five states, not the two the issue quoted.

    The owner's decision says so in terms: leaving one state on the old
    vocabulary leaves the ambiguity reachable, and ``runtime_broken`` was the
    third one saying "the download" and meaning the artifact.
    """
    assert status_sentences, 'no copy parsed out of renderRelationsStatus'
    offenders = _offenders(status_sentences)
    assert not offenders, (
        f'these sentences call an artifact a "download", in a panel that uses '
        f'the same word for the 845 MB model fetch: {offenders}. The artifact '
        f'is "this version of WIMI" and the other one is "the full version" '
        f'(#402).')


def test_the_artifact_is_named_the_way_the_decision_names_it(status_sentences):
    """The other half: having stopped saying "download", it must say something.

    Two states talk about an artifact — ``not_in_this_build`` and
    ``runtime_broken`` — so both sanctioned names have to appear, or the
    sentences have gone vague instead of precise.
    """
    # Case-insensitive: both names open a sentence, so both are capitalised
    # where they appear.
    joined = ' '.join(status_sentences).lower()
    missing = [name for name in SANCTIONED if name.lower() not in joined]
    assert not missing, (
        f'{missing} never appears in the status copy. The states that name an '
        f'artifact must name it the agreed way rather than dropping the '
        f'reference (#402)')


def test_the_entry_forms_copy_keeps_the_same_rule():
    """`relation_proposals.js` sends students to this panel.

    Its `model_missing` / `model_corrupt` sentence is the one place the entry
    form says the word at all, and it means the model — so it stays, and the
    artifact sense must not arrive here later either.
    """
    strings = _student_facing(PROPOSALS_JS.read_text(encoding='utf-8'))
    offenders = _offenders(strings)
    assert not offenders, (
        f'the entry form now calls an artifact a "download": {offenders}')
    assert any('download the model again' in s for s in strings), (
        'the sentence that sends a student to Settings no longer names the '
        'model, so "download" has nothing to attach to there')


# ==================== the controls ====================

def test_the_sweep_would_catch_each_sentence_it_replaced():
    """Without this the sweep passes against a file it cannot read.

    The three literals are the ones that shipped before #402, each in the
    state it belonged to.
    """
    before = [
        'not included in the download, so that WIMI stays small ',
        'This download of WIMI does not include ',
        '. That is a fault in the download rather than ',
    ]
    for sentence in before:
        assert _offenders([sentence]), (
            f'the sweep does not flag {sentence!r}, which is one of the three '
            f'sentences #402 was filed about -- so it proves nothing about '
            f'the three that replaced them')


def test_the_sanctioned_use_of_the_noun_is_not_flagged():
    """The rule is one noun per thing, not one fewer noun.

    "The download" *is* what the model fetch is called, and the resume clause
    in ``model_not_downloaded`` uses it. A guard tightened to ban the word
    would look stricter and would be wrong — so this fails if anybody does
    that.
    """
    allowed = [
        ' Part of it is already here, so the download carries on from where '
        'it stopped.',
        'Could not start the download: ',
        'The download did not finish',
        'WIMI needs to download the model once (',
    ]
    for sentence in allowed:
        assert not _offenders([sentence]), (
            f'{sentence!r} is the model fetch, which is exactly what the word '
            f'"download" is reserved FOR. The sweep has been tightened into '
            f'banning the noun (#402)')


def test_the_block_this_reads_is_the_one_that_paints(status_sentences):
    """A sweep anchored on a moved landmark reports an empty table (#322).

    If `renderRelationsStatus` is renamed or the slice lands on the wrong
    bounds, every assertion above passes over nothing. Anchor on the five
    state names the switch branches on.
    """
    block = _status_block()
    for state in ('ready', 'model_not_downloaded', 'not_in_this_build',
                  'dev_runtime_missing', 'runtime_broken'):
        assert f"case '{state}':" in block, (
            f'{state} is not in the slice this test reads, so the sweep is '
            f'looking at the wrong part of settings.js')
    assert len(status_sentences) > 10, (
        f'only {len(status_sentences)} literals parsed; the status block has '
        f'five states and a failure branch, so the reader is broken')
