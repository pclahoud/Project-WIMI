"""The relation runtime: verify, load once, ask in chunks, classify failures (#60).

Everything except the last section runs against a fake model through
``RelationRuntime``'s ``model_factory`` seam, so it needs no torch and runs in
the main venv. The fake honours the one contract the real model is held to:
``run(text, labels, threshold, checkpoint)`` calls ``checkpoint()`` before each
unit of work, which is where cancellation and the deadline are enforced.

The last section drives the real GLiNER2 and skips unless the runtime is
importable and ``WIMI_RELATIONS_TEST_APP_DATA`` names an app-data directory
holding a verified model (``models/gliner2/``).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app.relation_extraction import model_spec
from app.relation_extraction import runtime as rt
from app.relation_extraction.errors import (
    RelationExtractionError,
    RelationExtractionErrorKind as Kind,
)
from app.relation_extraction.runtime import (
    EXTRACTION_THRESHOLD,
    ExtractionCancelled,
    RelationLabel,
    RelationRuntime,
    label_index,
    labels_from_types,
    passage_bounds,
    proposals_from_raw,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNTIME_SOURCE = REPO_ROOT / 'src' / 'app' / 'relation_extraction' / 'runtime.py'

TEXT = ('Hypertension is a risk factor for stroke. Chronic hypertension causes '
        'hypertensive nephrosclerosis. ACE inhibitors treat hypertension.')
LABELS = (
    RelationLabel(1, 'causes'),
    RelationLabel(2, 'risk factor for'),
    RelationLabel(3, 'treats'),
)

#: The verbatim message torch 2.14.1+cpu raised on Windows for an allocation
#: it could not meet (measured for 2 GB under a job-object limit and for
#: 200 GB with none). Copied, not paraphrased, because the classifier matches
#: on it.
WINDOWS_ALLOCATOR_MESSAGE = (
    '[enforce fail at alloc_cpu.cpp:117] data. DefaultCPUAllocator: not enough '
    'memory: you tried to allocate 2097152000 bytes.'
)
#: The same failure on Linux, torch 2.14.1+cpu, measured on the Linux machine.
#: Line number, assertion text and phrase all differ from Windows; the
#: classifier must accept both.
LINUX_ALLOCATOR_MESSAGE = (
    "[enforce fail at alloc_cpu.cpp:127] err == 0. DefaultCPUAllocator: can't "
    "allocate memory: you tried to allocate 80000000000000 bytes. Error code 12 "
    "(Cannot allocate memory)"
)


def mention(text: str, start: int, confidence: float = 0.99) -> dict:
    return {'text': text, 'start': start, 'end': start + len(text),
            'confidence': confidence}


def span(text: str, phrase: str, nth: int = 0) -> int:
    at = -1
    for _ in range(nth + 1):
        at = text.index(phrase, at + 1)
    return at


def probe_output() -> dict:
    """GLiNER2-shaped output for :data:`TEXT`, offsets computed, not typed."""
    return {'relation_extraction': {
        'risk factor for': [{
            'head': mention('Hypertension', span(TEXT, 'Hypertension'), 1.0),
            'tail': mention('stroke', span(TEXT, 'stroke'), 1.0)}],
        'causes': [{
            'head': mention('Chronic hypertension', span(TEXT, 'Chronic hypertension'), 0.98),
            'tail': mention('hypertensive nephrosclerosis',
                            span(TEXT, 'hypertensive nephrosclerosis'), 0.97)}],
        'treats': [{
            'head': mention('ACE inhibitors', span(TEXT, 'ACE inhibitors'), 0.95),
            'tail': mention('hypertension', span(TEXT, 'hypertension.'), 0.60)}],
    }}


class FakeModel:
    """Stands in for ``_GlinerModel``: records calls, calls the checkpoint."""

    def __init__(self, output=None, *, chunks: int = 1, on_chunk=None, raises=None):
        self.output = output if output is not None else probe_output()
        self.chunks = chunks
        self.on_chunk = on_chunk
        self.raises = raises
        self.calls = []

    def run(self, text, labels, threshold, checkpoint):
        self.calls.append({'text': text, 'labels': list(labels), 'threshold': threshold,
                           'thread': threading.get_ident()})
        for index in range(self.chunks):
            checkpoint()
            if self.on_chunk is not None:
                self.on_chunk(index)
        if self.raises is not None:
            raise self.raises
        return self.output


class Factory:
    def __init__(self, model=None, raises=None):
        self.model = model or FakeModel()
        self.raises = raises
        self.directories = []

    def __call__(self, directory):
        self.directories.append(directory)
        if self.raises is not None:
            raise self.raises
        return self.model


class Verify:
    def __init__(self, raises=None):
        self.raises = raises
        self.calls = 0

    def __call__(self, app_data_dir, *, cancel=None):
        self.calls += 1
        if self.raises is not None:
            raise self.raises


def make(tmp_path, *, model=None, factory=None, verify=None, **kwargs):
    factory = factory or Factory(model)
    verify = verify or Verify()
    runtime = RelationRuntime(tmp_path, model_factory=factory, verify=verify, **kwargs)
    return runtime, factory, verify


# --------------------------------------------------------------------------
# Nothing happens until it is asked for
# --------------------------------------------------------------------------

def test_constructing_a_runtime_verifies_and_loads_nothing(tmp_path):
    """The bridge builds one on the Qt main thread; that must cost nothing."""
    runtime, factory, verify = make(tmp_path)
    assert not runtime.loaded
    assert verify.calls == 0 and factory.directories == []


def test_importing_the_runtime_and_jobs_does_not_import_torch():
    """Module scope stays torch-free even though the quarantine permits it.

    The model is built on the worker; if importing these modules pulled torch
    in, the first ``import`` from the bridge would freeze the window for
    seconds on the Qt main thread.
    """
    code = ('import sys; sys.path.insert(0, "src"); '
            'import app.relation_extraction.runtime, app.relation_extraction.jobs; '
            'heavy = [m for m in ("torch", "transformers", "gliner2") if m in sys.modules]; '
            'print(",".join(heavy))')
    out = subprocess.run([sys.executable, '-c', code], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ''


def test_a_blank_text_returns_nothing_without_loading(tmp_path):
    runtime, factory, verify = make(tmp_path)
    result = runtime.extract('   \n ', LABELS)
    assert result.proposals == () and result.load_ms is None
    assert verify.calls == 0 and factory.directories == []


# --------------------------------------------------------------------------
# Verify, then load once
# --------------------------------------------------------------------------

def test_the_model_is_built_from_the_installed_directory(tmp_path):
    runtime, factory, _ = make(tmp_path)
    runtime.extract(TEXT, LABELS)
    assert factory.directories == [model_spec.model_dir(tmp_path, create=False)]


def test_verify_runs_before_the_model_is_built_and_only_once(tmp_path):
    order = []
    verify = Verify()
    factory = Factory()
    runtime = RelationRuntime(
        tmp_path,
        verify=lambda d, cancel=None: (order.append('verify'), verify(d, cancel=cancel)),
        model_factory=lambda d: (order.append('build'), factory(d))[1],
    )
    first = runtime.extract(TEXT, LABELS)
    second = runtime.extract(TEXT, LABELS)
    assert order == ['verify', 'build']
    assert first.load_ms is not None and second.load_ms is None


@pytest.mark.parametrize('kind', [Kind.MODEL_MISSING, Kind.MODEL_CORRUPT])
def test_a_missing_or_corrupt_model_is_never_built_and_not_retryable(tmp_path, kind):
    """Both need a download, which "try again" cannot provide."""
    runtime, factory, _ = make(
        tmp_path, verify=Verify(RelationExtractionError(kind, 'no')))
    with pytest.raises(RelationExtractionError) as exc:
        runtime.extract(TEXT, LABELS)
    assert exc.value.kind == kind and not exc.value.retryable
    assert factory.directories == []


def test_a_load_failure_after_a_clean_verify_is_retryable_and_retried(tmp_path):
    factory = Factory(raises=OSError('disk hiccup'))
    runtime, _, verify = make(tmp_path, factory=factory)
    with pytest.raises(RelationExtractionError) as exc:
        runtime.extract(TEXT, LABELS)
    assert exc.value.kind == Kind.MODEL_LOAD_FAILED and exc.value.retryable
    assert 'OSError: disk hiccup' in exc.value.detail

    factory.raises = None
    assert runtime.extract(TEXT, LABELS).proposals
    assert len(factory.directories) == 2 and verify.calls == 2


def test_running_out_of_memory_while_loading_is_its_own_kind(tmp_path):
    runtime, _, _ = make(tmp_path, factory=Factory(raises=RuntimeError(WINDOWS_ALLOCATOR_MESSAGE)))
    with pytest.raises(RelationExtractionError) as exc:
        runtime.load()
    assert exc.value.kind == Kind.OUT_OF_MEMORY and not exc.value.retryable


def test_unload_drops_the_model_so_the_next_pass_loads_again(tmp_path):
    runtime, factory, _ = make(tmp_path)
    runtime.load()
    runtime.unload()
    assert not runtime.loaded
    runtime.extract(TEXT, LABELS)
    assert len(factory.directories) == 2


def test_the_real_loader_refuses_anything_that_is_not_a_directory(tmp_path):
    """Checked before gliner2 is imported, so this runs without torch.

    A string that is not a directory is what a repo id looks like, and a repo
    id is a Hub load: main's tokenizer paired with our pinned weights.
    """
    with pytest.raises(RelationExtractionError) as exc:
        rt._GlinerModel(tmp_path / 'fastino' / 'gliner2-base-v1')
    assert exc.value.kind == Kind.MODEL_MISSING


def test_the_real_loader_passes_the_directory_and_local_files_only():
    """Static, because the property is in a call this suite cannot run.

    The only ``from_pretrained`` call in the module must take
    ``str(directory)`` and ``local_files_only=True``, so a future gliner2 that
    routed a directory through the Hub would fail loudly instead of
    downloading.
    """
    tree = ast.parse(RUNTIME_SOURCE.read_text(encoding='utf-8'))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == 'from_pretrained']
    assert len(calls) == 1
    call = calls[0]
    assert ast.unparse(call.args[0]) == 'str(directory)'
    keywords = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
    assert keywords.get('local_files_only') == 'True'


# --------------------------------------------------------------------------
# Labels are the exam's relation types
# --------------------------------------------------------------------------

def test_labels_come_from_the_types_and_retired_ones_are_dropped():
    types = [
        {'id': 1, 'label': 'causes', 'status': 'active', 'is_retired': False},
        {'id': 2, 'label': 'old', 'status': 'retired', 'is_retired': True},
        {'id': 3, 'label': 'treats', 'status': 'active', 'is_retired': False},
        {'id': 4, 'label': 'also old', 'status': 'retired'},
    ]
    assert labels_from_types(types) == (RelationLabel(1, 'causes'), RelationLabel(3, 'treats'))


def test_the_model_is_asked_exactly_the_type_labels_at_the_named_threshold(tmp_path):
    model = FakeModel()
    runtime, _, _ = make(tmp_path, model=model)
    runtime.extract(TEXT, LABELS)
    assert model.calls[0]['labels'] == ['causes', 'risk factor for', 'treats']
    # Owner's decision, 2026-10-05: "80% and user configurable".
    assert model.calls[0]['threshold'] == EXTRACTION_THRESHOLD == 0.8


def test_a_per_call_threshold_reaches_the_model_and_the_filter(tmp_path):
    """The student's setting decides both what the model returns and what is kept."""
    model = FakeModel()
    runtime, _, _ = make(tmp_path, model=model)
    loose = runtime.extract(TEXT, LABELS, threshold=0.5).proposals
    strict = runtime.extract(TEXT, LABELS).proposals
    assert [c['threshold'] for c in model.calls] == [0.5, 0.8]
    assert {p.relation_type_id for p in loose} == {1, 2, 3}
    # treats scores 0.60 (its weaker end), so the default drops it.
    assert {p.relation_type_id for p in strict} == {1, 2}


@pytest.mark.parametrize('bad', [
    0, 0.0, -1, 0.05, 0.0999, 0.951, 1, 1.0001, 'x', None, True, float('nan'),
])
def test_a_threshold_outside_the_decided_range_is_refused(bad):
    """#380: 0.10-0.95. ``True`` is refused too, though Python calls it 1."""
    with pytest.raises(ValueError, match='threshold'):
        rt.validate_threshold(bad)


@pytest.mark.parametrize('good', [0.10, 0.1, 0.5, 0.8, 0.95, '0.75', 0.83])
def test_a_threshold_inside_the_range_is_accepted_as_a_float(good):
    """Between-step values are valid; the 0.05 step is the control's, not a rule."""
    assert rt.validate_threshold(good) == float(good)


def test_the_decided_range_and_default():
    assert (rt.THRESHOLD_MIN, rt.THRESHOLD_MAX, rt.THRESHOLD_STEP) == (0.10, 0.95, 0.05)
    assert rt.THRESHOLD_MIN <= EXTRACTION_THRESHOLD <= rt.THRESHOLD_MAX


def test_the_preference_validates_the_same_range():
    """``preferences.py`` restates the range because it may not import this package."""
    import re

    source = (REPO_ROOT / 'src' / 'database' / 'domains' / 'preferences.py').read_text(
        encoding='utf-8')
    match = re.search(r"'relation_confidence_threshold':\s*\(([\d.]+),\s*([\d.]+)\)", source)
    assert match, 'preferences.py no longer validates relation_confidence_threshold'
    assert (float(match.group(1)), float(match.group(2))) == (rt.THRESHOLD_MIN, rt.THRESHOLD_MAX)


def test_the_settings_slider_offers_exactly_the_valid_range():
    """A control that offers a value the extraction refuses is a broken control."""
    import re

    html = (REPO_ROOT / 'src' / 'web' / 'html' / 'settings.html').read_text(encoding='utf-8')
    tag = re.search(r'<input[^>]*id="relation_confidence_threshold"[^>]*>', html, re.S)
    assert tag, 'the Related Topics slider is missing'
    attrs = dict(re.findall(r'(\w[\w-]*)="([^"]*)"', tag.group(0)))
    assert attrs['type'] == 'range'
    assert attrs['data-field'] == 'relation_confidence_threshold'
    assert float(attrs['min']) == rt.THRESHOLD_MIN
    assert float(attrs['max']) == rt.THRESHOLD_MAX
    assert float(attrs['step']) == rt.THRESHOLD_STEP
    assert float(attrs['value']) == EXTRACTION_THRESHOLD
    js = (REPO_ROOT / 'src' / 'web' / 'js' / 'settings.js').read_text(encoding='utf-8')
    default = re.search(r'relation_confidence_threshold:\s*([\d.]+)', js)
    assert default and float(default.group(1)) == EXTRACTION_THRESHOLD


def test_an_impossible_threshold_is_refused_before_anything_loads(tmp_path):
    runtime, factory, verify = make(tmp_path)
    with pytest.raises(ValueError):
        runtime.extract(TEXT, LABELS, threshold=2)
    with pytest.raises(ValueError):
        RelationRuntime(tmp_path, threshold=0)
    assert verify.calls == 0 and factory.directories == []


@pytest.mark.parametrize('labels, why', [
    ((), 'no relation types'),
    ((RelationLabel(1, 'causes'), RelationLabel(2, 'Causes')), 'share the label'),
    ((RelationLabel(1, '  '),), 'blank label'),
])
def test_labels_the_model_could_not_answer_about_are_refused(labels, why):
    with pytest.raises(ValueError, match=why):
        label_index(labels)


# --------------------------------------------------------------------------
# What comes back
# --------------------------------------------------------------------------

def test_answers_map_back_to_type_ids_best_first(tmp_path):
    runtime, _, _ = make(tmp_path)
    proposals = runtime.extract(TEXT, LABELS, threshold=0.5).proposals
    assert [(p.relation_type_id, p.head.text, p.tail.text, p.score) for p in proposals] == [
        (2, 'Hypertension', 'stroke', 1.0),
        (1, 'Chronic hypertension', 'hypertensive nephrosclerosis', 0.97),
        (3, 'ACE inhibitors', 'hypertension', 0.6),
    ]


def test_each_proposal_carries_the_passage_it_came_from(tmp_path):
    runtime, _, _ = make(tmp_path)
    by_type = {p.relation_type_id: p
               for p in runtime.extract(TEXT, LABELS, threshold=0.5).proposals}
    assert by_type[2].passage == 'Hypertension is a risk factor for stroke.'
    assert by_type[3].passage == 'ACE inhibitors treat hypertension.'
    for p in by_type.values():
        assert TEXT[p.passage_start:p.passage_end] == p.passage


def test_a_relation_across_two_sentences_gets_both():
    """The model points where it looked, which can be the previous sentence."""
    raw = {'relation_extraction': {'treats': [{
        'head': mention('ACE inhibitors', span(TEXT, 'ACE inhibitors')),
        'tail': mention('hypertension', span(TEXT, 'hypertension causes')),
    }]}}
    [proposal] = proposals_from_raw(TEXT, raw, label_index(LABELS), 0.5)
    assert proposal.passage == ('Chronic hypertension causes hypertensive '
                                'nephrosclerosis. ACE inhibitors treat hypertension.')


def test_the_score_is_the_weaker_end_and_the_threshold_applies_to_it():
    raw = {'relation_extraction': {'causes': [{
        'head': mention('Chronic hypertension', 42, 0.99),
        'tail': mention('hypertensive nephrosclerosis', 70, 0.40),
    }]}}
    assert proposals_from_raw(TEXT, raw, label_index(LABELS), 0.5) == ()
    [kept] = proposals_from_raw(TEXT, raw, label_index(LABELS), 0.3)
    assert kept.score == 0.4


def test_the_same_relation_twice_is_proposed_once_with_its_best_passage():
    text = 'Smoking causes cancer. Truly, smoking causes CANCER.'
    raw = {'relation_extraction': {'causes': [
        {'head': mention('Smoking', 0, 0.7), 'tail': mention('cancer', 15, 0.7)},
        {'head': mention('smoking', 30, 0.9), 'tail': mention('CANCER', 45, 0.9)},
    ]}}
    [proposal] = proposals_from_raw(text, raw, label_index(LABELS), 0.5)
    assert proposal.score == 0.9 and proposal.passage == 'Truly, smoking causes CANCER.'


def test_an_unrequested_label_or_a_malformed_mention_is_dropped_not_guessed():
    raw = {'relation_extraction': {
        'invented': [{'head': mention('a', 0), 'tail': mention('b', 2)}],
        'causes': [
            {'head': {'text': 'x'}, 'tail': mention('b', 2)},
            {'head': mention('a', 0), 'tail': None},
            {'head': {'text': '', 'start': 0, 'end': 0, 'confidence': 1.0},
             'tail': mention('b', 2)},
        ],
    }}
    assert proposals_from_raw('a b', raw, label_index(LABELS), 0.5) == ()


@pytest.mark.parametrize('text, start, end, expected', [
    ('One. Two three. Four.', 5, 8, 'Two three.'),
    ('One. Two three. Four.', 0, 20, 'One. Two three. Four.'),
    ('Line one\nline two here\nthree', 13, 17, 'line two here'),
    ('  padded sentence  ', 2, 8, 'padded sentence'),
    ('No terminal punctuation at all', 3, 5, 'No terminal punctuation at all'),
    ('Is it? Yes! Fine.', 7, 10, 'Yes!'),
])
def test_passage_bounds(text, start, end, expected):
    s, e = passage_bounds(text, start, end)
    assert text[s:e] == expected


# --------------------------------------------------------------------------
# The text the model is given
#
# ``question_entries.explanation`` holds HTML -- ``question_entry.js`` saves
# ``explanationEditor.getContent().html``. The model is asked for character
# spans, so markup reaching it means a mention of ``<p>Chronic hypertension``,
# which matches no subject, and a passage containing tags, which then becomes
# the relation's ``reason``: the one field #14 makes mandatory and shows to the
# student as their own words.
# --------------------------------------------------------------------------

@pytest.mark.parametrize('html, expected', [
    ('<p>Chronic hypertension causes nephrosclerosis.</p>',
     'Chronic hypertension causes nephrosclerosis.'),
    # Paragraph boundaries survive as newlines: _SENTENCE_BREAK splits on
    # them, so losing them would merge two paragraphs into one passage
    # whenever the first does not end in a full stop.
    ('<p>First claim</p><p>Second claim</p>', 'First claim\n\nSecond claim'),
    ('<div>First<br>Second</div>', 'First\nSecond'),
    # Entities have to be resolved or the model reads them as words.
    ('<p>a &lt; b and 5 &amp; 6</p>', 'a < b and 5 & 6'),
    ('<p>Keep&nbsp;this</p>', 'Keep this'),
    # A regex strip would eat ``< b</p>`` here. This is why it is parsed.
    ('<p>a < b</p>', 'a < b'),
    ('<p>Prose</p><script>var x = 1;</script>', 'Prose'),
    ('Plain text, no markup at all.', 'Plain text, no markup at all.'),
    ('<p><br></p>', ''),
    ('', ''),
    (None, ''),
])
def test_plain_text(html, expected):
    assert rt.plain_text(html) == expected


def test_a_passage_cut_from_converted_text_carries_no_markup():
    """The two halves together, which is where the damage would have shown.

    A passage is what becomes the relation's reason, so this is the assertion
    that says the student's own words are what gets stored.
    """
    text = rt.plain_text(
        '<p>Chronic hypertension causes hypertensive nephrosclerosis.</p>'
        '<p>Hypertension is a risk factor for stroke.</p>')
    at = text.index('nephrosclerosis')

    start, end = passage_bounds(text, at, at + len('nephrosclerosis'))
    assert text[start:end] == (
        'Chronic hypertension causes hypertensive nephrosclerosis.')


def test_unparseable_markup_still_yields_the_words():
    """A status read must not raise because an editor wrote something odd."""
    assert 'hypertension' in rt.plain_text('<p>hypertension<<<</p>')


# --------------------------------------------------------------------------
# Stopping a pass
# --------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_a_pass_past_its_deadline_stops_at_the_next_chunk(tmp_path):
    clock = Clock()
    model = FakeModel(chunks=10, on_chunk=lambda i: setattr(clock, 'now', clock.now + 4.0))
    runtime, _, _ = make(tmp_path, model=model, timeout_s=10.0, clock=clock)
    with pytest.raises(RelationExtractionError) as exc:
        runtime.extract(TEXT, LABELS)
    assert exc.value.kind == Kind.EXTRACTION_TIMEOUT and exc.value.retryable
    assert exc.value.detail == {'chars': len(TEXT), 'timeout_s': 10.0}
    # 3 chunks of 4 s pass 10 s; the 4th checkpoint is where it stops.
    assert clock.now == 1012.0


def test_a_per_call_timeout_overrides_the_runtime_default(tmp_path):
    clock = Clock()
    model = FakeModel(chunks=3, on_chunk=lambda i: setattr(clock, 'now', clock.now + 4.0))
    runtime, _, _ = make(tmp_path, model=model, timeout_s=1.0, clock=clock)
    assert runtime.extract(TEXT, LABELS, timeout_s=60).proposals


def test_a_cancel_mid_pass_stops_at_the_next_chunk(tmp_path):
    cancel = threading.Event()
    seen = []
    model = FakeModel(chunks=5, on_chunk=lambda i: (seen.append(i), i == 1 and cancel.set()))
    runtime, _, _ = make(tmp_path, model=model)
    with pytest.raises(ExtractionCancelled):
        runtime.extract(TEXT, LABELS, cancel=cancel)
    assert seen == [0, 1]


def test_a_cancel_during_verification_is_a_cancel_not_a_download_error(tmp_path):
    runtime, factory, _ = make(tmp_path, verify=Verify(
        RelationExtractionError(Kind.DOWNLOAD_CANCELLED, 'cancelled while verifying')))
    with pytest.raises(ExtractionCancelled):
        runtime.extract(TEXT, LABELS, cancel=threading.Event())
    assert factory.directories == []


# --------------------------------------------------------------------------
# Failures during a pass
# --------------------------------------------------------------------------

@pytest.mark.parametrize('raised, kind', [
    (RuntimeError(WINDOWS_ALLOCATOR_MESSAGE), Kind.OUT_OF_MEMORY),
    (MemoryError(), Kind.OUT_OF_MEMORY),
    (RuntimeError('shape mismatch in span head'), Kind.EXTRACTION_FAILED),
    (ValueError('bad token'), Kind.EXTRACTION_FAILED),
])
def test_failures_during_a_pass_are_classified(tmp_path, raised, kind):
    runtime, _, _ = make(tmp_path, model=FakeModel(raises=raised))
    with pytest.raises(RelationExtractionError) as exc:
        runtime.extract(TEXT, LABELS)
    assert exc.value.kind == kind


def test_out_of_memory_is_not_offered_as_retryable():
    """The same text on the same machine fails the same way."""
    assert not RelationExtractionError(Kind.OUT_OF_MEMORY, 'x').retryable


def test_an_interrupt_is_not_swallowed_into_an_extraction_error(tmp_path):
    runtime, _, _ = make(tmp_path, model=FakeModel(raises=KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        runtime.extract(TEXT, LABELS)


@pytest.mark.parametrize('exc, expected', [
    (RuntimeError(WINDOWS_ALLOCATOR_MESSAGE), True),
    (RuntimeError(LINUX_ALLOCATOR_MESSAGE), True),
    (MemoryError(), True),
    (type('OutOfMemoryError', (RuntimeError,), {})('CUDA out of memory'), True),
    (RuntimeError('expected all tensors to be on the same device'), False),
    (RuntimeError('not enough values to unpack'), False),
    (OSError('not enough memory'), False),
])
def test_what_counts_as_out_of_memory(exc, expected):
    assert rt._is_out_of_memory(exc) is expected


def test_an_error_serialises_to_the_stt_shape():
    error = RelationExtractionError(Kind.EXTRACTION_TIMEOUT, 'slow', detail={'timeout_s': 60})
    assert error.to_dict() == {'kind': 'extraction_timeout', 'detail': {'timeout_s': 60},
                               'retryable': True}


# --------------------------------------------------------------------------
# The real model
# --------------------------------------------------------------------------

#: Runs in a child process, because this one cannot load torch: conftest has
#: already imported PyQt6, whose older ``msvcp140.dll`` is then the one the
#: process holds, and torch's ``c10.dll`` fails with WinError 1114 against it
#: (#367). The child does what WIMI's startup does -- ``preload_newest()``
#: before anything else -- which is also what makes this test realistic.
_REAL_MODEL_SCRIPT = r"""
import itertools, json, sys
sys.path.insert(0, 'src')
from app.msvc_runtime import preload_newest
preload_newest()
from console_encoding import configure_stdio
configure_stdio()
from app.relation_extraction.errors import RelationExtractionError
from app.relation_extraction.runtime import RelationLabel, RelationRuntime
app_data, text = sys.argv[1], sys.argv[2]
out = {}
runtime = RelationRuntime(app_data)
result = runtime.extract(text, (RelationLabel(2, 'risk factor for'),
                                RelationLabel(1, 'causes'), RelationLabel(4, 'treats')))
out['proposals'] = [p.to_dict() for p in result.proposals]
out['load_ms'] = result.load_ms
# A clock that advances one second per reading, against a 2.5 s ceiling:
# reading 0 sets the deadline, reading 1 is the check before the pass, and
# readings 2, 3, ... are the encoder hook, one per chunk. Stopping at reading
# 3 is only possible if the hook runs inside the pass.
ticks = itertools.count()
runtime._clock = lambda: float(next(ticks))
try:
    runtime.extract(text * 40, (RelationLabel(1, 'causes'),), timeout_s=2.5)
    out['timeout'] = None
except RelationExtractionError as exc:
    out['timeout'] = exc.kind.value
out['clock_reads'] = next(ticks)
print('RESULT ' + json.dumps(out))
"""


@pytest.fixture(scope='module')
def real_model_run():
    path = os.environ.get('WIMI_RELATIONS_TEST_APP_DATA')
    if not path:
        pytest.skip('set WIMI_RELATIONS_TEST_APP_DATA to an app-data dir holding models/gliner2')
    if importlib.util.find_spec('gliner2') is None:
        pytest.skip('the relations runtime is not installed in this venv')
    if not model_spec.is_installed(path):
        pytest.skip(f'no installed model under {path}')
    done = subprocess.run([sys.executable, '-c', _REAL_MODEL_SCRIPT, path, TEXT],
                          cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=600)
    lines = [line for line in done.stdout.splitlines() if line.startswith('RESULT ')]
    assert done.returncode == 0 and lines, done.stderr[-3000:]
    return json.loads(lines[-1][len('RESULT '):])


@pytest.mark.slow
def test_the_real_model_proposes_the_probe_relation(real_model_run):
    found = {(p['relation_type_id'], p['head']['text'], p['tail']['text'])
             for p in real_model_run['proposals']}
    assert (2, 'Hypertension', 'stroke') in found
    assert all(p['score'] >= EXTRACTION_THRESHOLD for p in real_model_run['proposals'])
    assert real_model_run['load_ms'] is not None


@pytest.mark.slow
def test_the_real_model_stops_at_the_encoder_hook(real_model_run):
    """The hook inside the pass is what makes cancel and the deadline real."""
    assert real_model_run['timeout'] == 'extraction_timeout'
    assert real_model_run['clock_reads'] == 4
