"""The GLiNER2 model: built once from its verified directory, then asked (#60).

This is the body of the worker phase in :mod:`jobs`. It imports neither Qt nor
``sqlite3`` nor anything under ``database``, and
``tests/app/test_relation_extraction_jobs.py`` asserts that statically, for the
reason ``app/stt/jobs.py`` gives: the worker must not touch a database
connection, and a rule nobody checks is a rule somebody breaks.

The model comes from a DIRECTORY, never from a repo id
------------------------------------------------------
:func:`_build_gliner` hands ``from_pretrained`` the installed directory
(:func:`model_spec.model_dir`) and nothing else, and refuses to run if that
path is not a directory. This is the most important line in the module.
``gliner2/models/base.py`` loads the tokenizer with
``AutoTokenizer.from_pretrained(repo_or_dir)`` and **no revision**, so a load
resolved through the Hub pairs ``main``'s tokenizer with our pinned weights.
Today those are the same commit, which is exactly why a Hub load would look
fine until the day the publisher changes the tokenizer.

Measured on Windows (gliner2 2.0.0, transformers 5.18.0, huggingface_hub
1.33.0, torch 2.14.1+cpu): with a fresh **empty** ``HF_HOME``,
``HF_HUB_OFFLINE=1`` and ``socket.connect`` patched to raise, a load from the
directory took 4.59 s, made **zero** connection attempts, left ``HF_HOME``
empty, and gave a ``DebertaV2Tokenizer`` of 128,011 entries (128,000 plus
GLiNER2's 11 added tokens). The control, the repo id under the same
conditions, raised ``LocalEntryNotFoundError``. ``local_files_only=True`` is
passed as well, so if a future gliner2 ever routes a directory through the Hub
the load fails loudly instead of downloading.

``from_pretrained`` prints a banner containing an emoji. On a console whose
encoding is cp1252 that print raises ``UnicodeEncodeError`` and the load
fails; it did exactly that in the measurement above until
``console_encoding.configure_stdio()`` ran. WIMI's entry point calls it, and a
windowed build has no stream to print to, so the app is safe; a script that
drives this module must call it too.

Verify, then load once, then keep it
------------------------------------
:meth:`RelationRuntime.load` runs :func:`model_spec.verify_dir` before building
anything (0.85 s for 845 MB on this machine, warm cache), so a missing file is
``MODEL_MISSING`` and a wrong digest is ``MODEL_CORRUPT`` -- both need a
download, so neither is retryable. A failure *after* a clean verify is
``MODEL_LOAD_FAILED``, which is. The model is then held for the life of the
runtime: loading costs seconds (4.4-4.6 s here, 5.2 s on the Mac, plus
several seconds importing torch and gliner2), and paying that per extraction
would make the feature unusable.

Loading needs more memory than it keeps. Measured with the real 834 MB
checkpoint in a fresh process, resident memory and Windows commit side by
side, because they are different quantities and only the first is comparable
across platforms:

=================================  ========  ========  ========
                                   settled   peak      delta
=================================  ========  ========  ========
Windows, resident (working set)    1,256 MB  2,052 MB    796 MB
Linux, resident (``VmHWM``)        1,388 MB  2,202 MB    814 MB
Windows, commit                    1,691 MB  3,285 MB  1,594 MB
=================================  ========  ========  ========

- **Resident, both platforms: one extra copy of the weights, ~800 MB.**
  gliner2 builds the whole model first, with random weights
  (``from_config``), so the encoder exists at full size before a single
  weight is read. The state dict then arrives and replaces it. 184 M fp32
  parameters is ~790 MB, so the deltas land on one copy almost exactly.
- **Windows commit adds a second ~800 MB that is never resident.** While
  ``safetensors.torch.load_file`` reads the checkpoint, peak commit rises by
  twice the file but the peak working set by only one copy. So it is memory
  charged and never touched, most likely a copy-on-write mapping of the whole
  file. That still counts against the commit limit (RAM plus page file), so it
  can still fail a load on a machine short of page file. It is not memory the
  load actually occupies. A synthetic 300 MB file on Linux showed ~2x
  *resident*, which briefly led this module to call the doubling
  cross-platform. That proxy held the mapping and a read-through copy resident
  together, which the real loader does not, so it measured the wrong path.
- **macOS is not measured** and has no known reason to differ from Linux:
  expect a peak of about 2.2 GB resident.

**Re-measuring? Do not reach for ``ru_maxrss`` in a subprocess.** The first
Linux attempt did and read **+0 MB**, because a forked child inherits its
parent's high-water mark, and that parent had already imported torch at
587 MB, burying the rise underneath. ``VmHWM`` in a process that is not a fork
of a heavier one is what caught it. Measure the real checkpoint through the
real loader, too: a proxy file is how a ~2x got attributed to Linux.

``low_cpu_mem_usage`` is not available to fix the first half. gliner2
rejects unknown load options (``split_load_kwargs``), and the encoder is built
``from_config``, where that option does not apply. Avoiding the random-init
copy would mean building gliner2's model on the meta device and loading with
``assign=True``, inside gliner2's own ``from_pretrained``. That is reported
here rather than done.

Memory, and why every pass is chunked
-------------------------------------
The single most important measurement in this module is this one. Running out
of memory during inference does **not** reliably raise. With the process held
to its post-load commit plus 300 MB, and again plus 1000 MB, by a Windows job
object, a growing extraction **killed the process with an access violation**
(exit 139) inside DeBERTa's attention, 3 runs of 3, with no Python exception
to catch. A single oversized allocation, by contrast, raises cleanly (see
:func:`_is_out_of_memory`). So the ``except`` clause is the second defence.
The first is never asking for that much memory.

The memory one plain ``extract_relations`` pass needs grows faster than
linearly with the text, because DeBERTa's attention is quadratic in tokens.
Extra commit at the peak of one pass, same machine:

=========  ================  =====================================
chars      plain pass        chunked (384 words, batch 1) pass
=========  ================  =====================================
135        +51 MB            +52 MB
1,350      +108 MB           +76 MB
5,400      +466 MB           +246 MB
10,800     +1,110 MB         +249 MB
16,200     +1,903 MB, 12.1 s +252 MB, 7.7 s
=========  ================  =====================================

So every pass uses ``extract_relations_long`` with GLiNER2's own chunking,
whose cost per pass stays roughly flat at about 250 MB whatever the length. On
the short text it gave the same five relations as the plain pass, with scores
within 0.04. Chunking also gives :meth:`RelationRuntime.extract` somewhere to
stop. Each chunk is one encoder forward, and a pre-forward hook checks
cancellation and the deadline there (:class:`_GlinerModel`).

What a pass can and cannot be stopped by
----------------------------------------
:data:`EXTRACTION_TIMEOUT_S` is enforced **between chunks**. A pass past its
deadline raises ``EXTRACTION_TIMEOUT`` at the next encoder forward, so a slow
or wedged pass releases the single worker within one chunk of the ceiling. It
cannot stop a single native call that never returns. Doing that needs the model
in a child process, which this module deliberately does not have: the cost
would be a second 1.7 GB process and ``multiprocessing`` support in the frozen
build, against a failure mode not observed. The model load itself is one
``from_pretrained`` call and is not interruptible either; the deadline applies
to extraction. What a wedged call leaves behind -- a worker thread that never
returns -- cannot be reclaimed, but :mod:`jobs` reports it instead of
spinning forever (its watchdog).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import model_spec
from .errors import RelationExtractionError, RelationExtractionErrorKind as Kind

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Product parameters
# --------------------------------------------------------------------------

#: Minimum confidence for a relation to be proposed, **by default**. A
#: product parameter, not a tuning knob for tests. The owner decided it on
#: #380 (2026-10-05): **0.80 by default, configurable by the student, from
#: 0.10 to 0.95 in steps of 0.05**. So this is the default, and the student's
#: own setting (``user_preferences.relation_confidence_threshold``, m028)
#: arrives per call, as ``RelationRuntime.extract(threshold=...)`` or
#: ``RelationJobs.start(threshold=...)``. The worker never reads a preference.
#:
#: Why 0.80: #4904, the owner's own adjudication of extracted relations on
#: real explanations, measured **0.80 precision at confidence >= 0.8 against
#: 0.69 with no cut at all**. It replaces 0.5, which was GLiNER2's own
#: default and what the #60 probe ran with.
#:
#: What it does on the two hand-written probe sentences, so the number is not
#: read as a guarantee: it drops a loose ``presents with`` at 0.784, and it
#: keeps a false ``confused with: Hypertension -> stroke`` at 0.865 that a
#: clause reordering produced (#378). A 0.9 cut drops that one too and keeps
#: all four true relations on that sentence. Two sentences are not a corpus,
#: and #378 showed that the false-positive rate moves with phrasing.
EXTRACTION_THRESHOLD = 0.8

#: The range a student may set, both ends inclusive (#380). Restated in
#: ``database/domains/preferences.py``, which may not import this package;
#: ``tests/app/test_relation_extraction_runtime.py`` asserts that the two
#: agree, and that the Settings slider offers exactly this range.
#:
#: **The floor is deliberately low. Do not raise it back to 0.50 in a tidy-up.**
#: A proposal is stored unconfirmed and stays invisible until the student
#: endorses it (#5494), so a permissive cutoff costs the student's attention,
#: not their data. #4904 measured 0.69 precision with no cut at all, which is
#: a panel worth skimming rather than noise. The floor exists only so that the
#: dial cannot reach a value where essentially every candidate pair is
#: proposed. The ceiling stops below 1.0 because a cut at certainty would
#: propose almost nothing and read as a broken feature.
THRESHOLD_MIN = 0.10
THRESHOLD_MAX = 0.95
#: What the Settings control steps by. Not enforced here: a value between
#: steps is a valid cutoff, and refusing it would make a hand-edited or
#: future preference fail for no reason a student could act on.
THRESHOLD_STEP = 0.05


def validate_threshold(value: Any) -> float:
    """A confidence cutoff as a float in ``[THRESHOLD_MIN, THRESHOLD_MAX]``, or ``ValueError``.

    Validated where it is passed in, before anything loads or is queued, so an
    out-of-range setting is refused with a sentence rather than producing a
    flooded or empty panel. ``bool`` is refused too: ``True`` is a number to
    Python, and a checkbox wired to this by mistake should fail loudly.
    """
    if isinstance(value, bool):
        raise ValueError(f'confidence threshold must be a number, not {value!r}')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'confidence threshold must be a number, not {value!r}') from None
    if not THRESHOLD_MIN <= number <= THRESHOLD_MAX:  # also refuses NaN
        raise ValueError(
            f'confidence threshold must be between {THRESHOLD_MIN:g} and '
            f'{THRESHOLD_MAX:g}, not {number:g}')
    return number

#: Wall-clock ceiling for one extraction pass, enforced between chunks. A pass
#: took 0.35-0.42 s for a 135-character explanation and 7.7 s for 16,200
#: characters on this machine (about 0.5 s per 1,000 characters). 60 s
#: therefore leaves room for a text several times that long on a machine
#: several times slower. It is not set near the typical time, because what it
#: exists to stop is the atypical pass. Callers may pass their own.
EXTRACTION_TIMEOUT_S = 60.0

#: GLiNER2's own chunking defaults for ``extract_relations_long``, stated here
#: so a gliner2 upgrade cannot change our memory profile silently. Words, not
#: tokens or characters.
CHUNK_WORDS = 384
CHUNK_OVERLAP_WORDS = 64
#: One chunk per encoder forward: the smallest memory per step, and the
#: finest granularity for the cancel/deadline check.
BATCH_SIZE = 1


# --------------------------------------------------------------------------
# What goes in and what comes out
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationLabel:
    """One exam relation type, as the model is asked about it.

    ``label`` is the type's own ``label`` from ``relation_types`` -- the model
    is asked the student's vocabulary, so there is no second one -- and
    ``type_id`` is how an answer maps back.
    """

    type_id: int
    label: str


def labels_from_types(types: Iterable[Mapping[str, Any]]) -> Tuple[RelationLabel, ...]:
    """``RelationLabel`` s from ``get_relation_types()`` rows, retired ones dropped.

    ``get_relation_types`` already excludes retired types unless asked, but
    this filters again on ``is_retired``/``status`` so a caller that read the
    whole list (``include_retired=True``, as a Settings page does) still cannot
    have a retired type proposed. A retired type is one the student has said
    they no longer want; proposing it would be arguing with them.
    """
    out = []
    for row in types:
        if row.get('is_retired') or row.get('status') == 'retired':
            continue
        out.append(RelationLabel(type_id=int(row['id']), label=str(row['label'])))
    return tuple(out)


@dataclass(frozen=True)
class Mention:
    """One end of a proposed relation, as the model located it.

    ``start``/``end`` are character offsets into the text that was sent, taken
    from the token positions the model scored. They are **not** a text search
    for the first occurrence; when a word appears twice, these point at the one
    the model used.
    """

    text: str
    start: int
    end: int
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {'text': self.text, 'start': self.start, 'end': self.end,
                'confidence': self.confidence}


@dataclass(frozen=True)
class Proposal:
    """A relation the model proposes, with the passage it came from.

    This layer does not decide what a proposal becomes. Matching ``head`` and
    ``tail`` to subjects, dropping rejected pairs, and what an accepted one
    writes into ``subject_relations.reason`` all belong to the write path; it
    gets ``passage`` so it can decide.

    ``score`` is the **lower** of the two mention confidences: a relation is
    only as certain as its less certain end.

    ``passage`` is the sentence or sentences covering both mentions, cut from
    the original text by :func:`passage_bounds`, and ``passage_start`` /
    ``passage_end`` are its offsets in that text.
    """

    relation_type_id: int
    label: str
    head: Mention
    tail: Mention
    score: float
    passage: str
    passage_start: int
    passage_end: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'relation_type_id': self.relation_type_id,
            'label': self.label,
            'head': self.head.to_dict(),
            'tail': self.tail.to_dict(),
            'score': self.score,
            'passage': self.passage,
            'passage_start': self.passage_start,
            'passage_end': self.passage_end,
        }


@dataclass(frozen=True)
class ExtractionResult:
    proposals: Tuple[Proposal, ...]
    #: Wall time of the pass alone, excluding any model load.
    ms: int
    #: Wall time of the model load this pass triggered, or ``None`` when the
    #: model was already resident. Reported so a first use that took 15 s can
    #: be told apart from a slow extraction.
    load_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {'proposals': [p.to_dict() for p in self.proposals],
                'ms': self.ms, 'load_ms': self.load_ms}


class ExtractionCancelled(Exception):
    """The caller's cancel event was set. Not a :class:`RelationExtractionError`
    because it is not a failure to report; :mod:`jobs` turns it into a state."""


# --------------------------------------------------------------------------
# The text the model is given
# --------------------------------------------------------------------------

#: Elements whose boundary is a line break in the plain text. Sentence
#: boundaries are what ``passage_bounds`` splits on, so losing these would
#: merge two paragraphs into one "passage" whenever the first does not end in
#: a full stop -- which student prose frequently does not.
_BLOCK_TAGS = frozenset({
    'address', 'article', 'aside', 'blockquote', 'br', 'dd', 'div', 'dl', 'dt',
    'figcaption', 'figure', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'header', 'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table',
    'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'ul',
})

#: Elements whose text is not the student's prose.
_DROPPED_TAGS = frozenset({'script', 'style', 'head', 'title'})

_BLANK_RUN = re.compile(r'\n{3,}')
_SPACE_RUN = re.compile(r'[ \t ]+')


class _TextExtractor(HTMLParser):
    """Collects the text of an HTML fragment, keeping block boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _DROPPED_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROPPED_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self._parts.append('\n')

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append('\n')

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        return ''.join(self._parts)


def plain_text(value: Optional[str]) -> str:
    """The student's prose, with the editor's markup removed.

    **``question_entries.explanation`` holds HTML**, not plain text:
    ``question_entry.js`` saves ``explanationEditor.getContent().html``. So
    every caller that hands an explanation to the model must come through
    here, and the reason is not tidiness -- the model is asked for character
    spans, and a span taken from ``<p>Chronic hypertension causes...</p>``
    can include the markup. A mention of ``<p>Chronic hypertension`` matches
    no subject, and :func:`passage_bounds` would cut a passage containing
    tags, which then becomes the relation's ``reason``: the one field #14
    makes mandatory, shown to the student as their own words.

    Parsed rather than regex-stripped, because ``<p>a < b</p>`` defeats
    ``re.sub(r'<[^>]+>', '', ...)`` and HTML entities (``&amp;``,
    ``&nbsp;``) have to be resolved or the model sees them as words.

    Block elements become newlines so sentence boundaries survive, runs of
    blank lines collapse to one, and a non-breaking space becomes an ordinary
    one -- ``_SENTENCE_BREAK`` keys on ``\\s``, which ``\\u00a0`` does not
    satisfy in a ``str`` pattern by default.

    Plain text in, plain text out: a value with no markup is returned with
    only its whitespace normalised, so this is safe to apply unconditionally.
    """
    if not value:
        return ''
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
        text = parser.text()
    except Exception:  # noqa: BLE001 - malformed markup must not lose the text
        # HTMLParser is lenient, but a caller must still get the student's
        # words rather than an exception from inside a status read.
        logger.warning('relations: could not parse the explanation as HTML; '
                       'using it as plain text')
        text = value
    text = text.replace(' ', ' ')
    text = _SPACE_RUN.sub(' ', text)
    text = '\n'.join(line.strip() for line in text.split('\n'))
    return _BLANK_RUN.sub('\n\n', text).strip()


# --------------------------------------------------------------------------
# Passages
# --------------------------------------------------------------------------

#: A sentence ends at ``.``, ``!`` or ``?`` followed by whitespace, or at a
#: line break. Deliberately simple: a student explanation is prose, and a
#: passage that is a sentence too long ("e.g. this") is a cosmetic flaw where
#: a wrong one would not be.
_SENTENCE_BREAK = re.compile(r'(?<=[.!?])\s+|\n+')


def passage_bounds(text: str, start: int, end: int) -> Tuple[int, int]:
    """``(start, end)`` of the sentence(s) covering ``text[start:end]``.

    Leading and trailing whitespace is excluded, so ``text[s:e]`` is the
    passage exactly as the student wrote it.
    """
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    s = 0
    for match in _SENTENCE_BREAK.finditer(text, 0, start):
        s = match.end()
    m = _SENTENCE_BREAK.search(text, end)
    e = m.start() if m else len(text)
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


# --------------------------------------------------------------------------
# Out of memory
# --------------------------------------------------------------------------


def _is_out_of_memory(exc: BaseException) -> bool:
    """Whether ``exc`` is torch or Python running out of memory.

    A CPU allocation torch cannot meet raises a plain ``RuntimeError`` -- not
    ``MemoryError``, and not ``torch.OutOfMemoryError``, which is CUDA's. The
    message differs by platform, measured with torch 2.14.1+cpu:

    Windows (2 GB under a job-object limit, and 200 GB with none)::

        [enforce fail at alloc_cpu.cpp:117] data. DefaultCPUAllocator: not
        enough memory: you tried to allocate N bytes.

    Linux::

        [enforce fail at alloc_cpu.cpp:127] err == 0. DefaultCPUAllocator:
        can't allocate memory: you tried to allocate 80000000000000 bytes.
        Error code 12 (Cannot allocate memory)

    The line number, the assertion text and the phrase **all** differ, so
    matching on any of the obvious ones would be wrong on one platform. The
    allocator's name plus "allocate" is in both. macOS is not measured; it
    takes the same POSIX ``posix_memalign`` branch as Linux (the one that
    produces ``err == 0`` and ``Error code 12``), so it is expected to read
    like Linux.

    See the module docstring for the case this cannot catch: memory running
    out *gradually* inside a pass killed the process outright.
    """
    if isinstance(exc, MemoryError):
        return True
    if type(exc).__name__ == 'OutOfMemoryError':
        return True
    if isinstance(exc, RuntimeError):
        message = str(exc)
        return 'DefaultCPUAllocator' in message and 'allocate' in message
    return False


# --------------------------------------------------------------------------
# The model seam
# --------------------------------------------------------------------------

#: ``run(text, labels, threshold, checkpoint) -> raw`` where ``raw`` is
#: GLiNER2's formatted relation output and ``checkpoint()`` must be called
#: between units of work. Tests supply their own; the real one is
#: :class:`_GlinerModel`.
ModelFactory = Callable[[Path], Any]


class _GlinerModel:
    """GLiNER2, built from a directory, with a stop point before each chunk."""

    def __init__(self, directory: Path) -> None:
        if not Path(directory).is_dir():
            # verify_dir has already run, so this is a programming error, but
            # it is the one that would let a repo id through; refuse it here.
            raise RelationExtractionError(
                Kind.MODEL_MISSING, 'the model directory does not exist',
                detail=str(directory))
        from gliner2 import GLiNER2  # the runtime: function-local on purpose

        self._model = GLiNER2.from_pretrained(str(directory), local_files_only=True)
        self._model.eval()
        self._checkpoint: Optional[Callable[[], None]] = None
        encoder = getattr(self._model, 'encoder', None)
        if encoder is None or not hasattr(encoder, 'register_forward_pre_hook'):
            raise RuntimeError(
                'this gliner2 has no encoder module to hook; the deadline and '
                'cancel checks would be silently absent')
        encoder.register_forward_pre_hook(self._before_forward)

    def _before_forward(self, _module, _args) -> None:
        checkpoint = self._checkpoint
        if checkpoint is not None:
            checkpoint()

    def run(self, text: str, labels: Sequence[str], threshold: float,
            checkpoint: Callable[[], None]) -> Dict[str, Any]:
        self._checkpoint = checkpoint
        try:
            return self._model.extract_relations_long(
                text, list(labels), threshold=threshold,
                chunk_size=CHUNK_WORDS, chunk_overlap=CHUNK_OVERLAP_WORDS,
                batch_size=BATCH_SIZE,
                include_confidence=True, include_spans=True,
            )
        finally:
            self._checkpoint = None


def _build_gliner(directory: Path) -> _GlinerModel:
    return _GlinerModel(directory)


# --------------------------------------------------------------------------
# The runtime
# --------------------------------------------------------------------------


class _Stop(Exception):
    """Raised from a checkpoint; carries why. Private to this module."""

    def __init__(self, timed_out: bool) -> None:
        super().__init__('timed out' if timed_out else 'cancelled')
        self.timed_out = timed_out


class RelationRuntime:
    """One loaded model and the means to ask it about a text.

    Construction does nothing expensive: no import of torch, no hashing, no
    load. The first :meth:`extract` (or an explicit :meth:`load`) pays for
    those, on whatever thread calls it -- which in WIMI is the job worker,
    never the Qt main thread.

    Thread-safe in the sense the job layer needs: a lock serialises loading
    and extraction, so two callers cannot build two models or run two passes
    over one.
    """

    def __init__(
        self,
        app_data_dir: Any,
        *,
        threshold: float = EXTRACTION_THRESHOLD,
        timeout_s: float = EXTRACTION_TIMEOUT_S,
        model_factory: Optional[ModelFactory] = None,
        verify: Optional[Callable[..., None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app_data_dir = Path(app_data_dir)
        self.threshold = validate_threshold(threshold)
        self.timeout_s = float(timeout_s)
        self._factory = model_factory or _build_gliner
        self._verify = verify or model_spec.verify_dir
        self._clock = clock
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, *, cancel: Optional[threading.Event] = None) -> Optional[int]:
        """Verify and build the model if it is not resident.

        Returns the milliseconds the load took, or ``None`` if there was
        nothing to do. Raises :class:`RelationExtractionError` (``MODEL_MISSING``,
        ``MODEL_CORRUPT``, ``MODEL_LOAD_FAILED`` or ``OUT_OF_MEMORY``) or
        :class:`ExtractionCancelled`.
        """
        with self._lock:
            return self._load_locked(cancel)

    def _load_locked(self, cancel: Optional[threading.Event]) -> Optional[int]:
        if self._model is not None:
            return None
        started = time.perf_counter()
        try:
            self._verify(self.app_data_dir, cancel=cancel)
        except RelationExtractionError as exc:
            if exc.kind == Kind.DOWNLOAD_CANCELLED:
                # verify_dir speaks the downloader's vocabulary for a cancel;
                # here nothing was being downloaded.
                raise ExtractionCancelled() from exc
            raise
        if cancel is not None and cancel.is_set():
            raise ExtractionCancelled()
        directory = model_spec.model_dir(self.app_data_dir, create=False)
        try:
            model = self._factory(directory)
        except RelationExtractionError:
            raise
        except BaseException as exc:  # noqa: BLE001 - classified, not swallowed
            if _is_out_of_memory(exc):
                raise RelationExtractionError(
                    Kind.OUT_OF_MEMORY, 'ran out of memory loading the model',
                    detail=f'{type(exc).__name__}: {exc}') from exc
            if not isinstance(exc, Exception):
                raise  # KeyboardInterrupt, SystemExit
            raise RelationExtractionError(
                Kind.MODEL_LOAD_FAILED, 'the model could not be loaded',
                detail=f'{type(exc).__name__}: {exc}') from exc
        self._model = model
        load_ms = int((time.perf_counter() - started) * 1000)
        logger.info('relation model loaded in %d ms from %s', load_ms, directory)
        return load_ms

    def unload(self) -> None:
        """Drop the model, so its ~1.7 GB can be returned."""
        with self._lock:
            self._model = None

    def extract(
        self,
        text: str,
        labels: Sequence[RelationLabel],
        *,
        cancel: Optional[threading.Event] = None,
        timeout_s: Optional[float] = None,
        threshold: Optional[float] = None,
        on_pass_start: Optional[Callable[[], None]] = None,
    ) -> ExtractionResult:
        """Propose relations in ``text`` using ``labels`` as the vocabulary.

        ``threshold`` (default :attr:`threshold`, which defaults to
        :data:`EXTRACTION_THRESHOLD`) is the student's confidence setting for
        this pass; it is validated before anything loads.

        Loads the model first if it is not resident. ``timeout_s`` (default
        :attr:`timeout_s`) bounds the pass, not the load. ``on_pass_start`` is
        called once the model is resident and the pass is about to begin, so a
        watchdog (:mod:`jobs`) can time the pass apart from the load.

        A blank text returns no proposals without loading anything. An empty
        ``labels`` is a :class:`ValueError`: there is nothing to ask, and the
        caller should not have queued it.
        """
        by_label = label_index(labels)
        cutoff = self.threshold if threshold is None else validate_threshold(threshold)
        if not text or not text.strip():
            return ExtractionResult(proposals=(), ms=0, load_ms=None)
        with self._lock:
            load_ms = self._load_locked(cancel)
            limit = self.timeout_s if timeout_s is None else float(timeout_s)
            deadline = self._clock() + limit

            def checkpoint() -> None:
                if cancel is not None and cancel.is_set():
                    raise _Stop(timed_out=False)
                if self._clock() > deadline:
                    raise _Stop(timed_out=True)

            if on_pass_start is not None:
                on_pass_start()
            started = time.perf_counter()
            try:
                checkpoint()
                raw = self._model.run(text, list(by_label), cutoff, checkpoint)
            except _Stop as stop:
                if not stop.timed_out:
                    raise ExtractionCancelled() from None
                raise RelationExtractionError(
                    Kind.EXTRACTION_TIMEOUT,
                    f'extraction did not finish within {limit:g} s',
                    detail={'chars': len(text), 'timeout_s': limit}) from None
            except RelationExtractionError:
                raise
            except BaseException as exc:  # noqa: BLE001 - classified, not swallowed
                if _is_out_of_memory(exc):
                    raise RelationExtractionError(
                        Kind.OUT_OF_MEMORY, 'ran out of memory extracting relations',
                        detail=f'{type(exc).__name__}: {exc}') from exc
                if not isinstance(exc, Exception):
                    raise
                raise RelationExtractionError(
                    Kind.EXTRACTION_FAILED, 'relation extraction failed',
                    detail=f'{type(exc).__name__}: {exc}') from exc
            ms = int((time.perf_counter() - started) * 1000)
        proposals = proposals_from_raw(text, raw, by_label, cutoff)
        return ExtractionResult(proposals=proposals, ms=ms, load_ms=load_ms)


def label_index(labels: Sequence[RelationLabel]) -> Dict[str, RelationLabel]:
    """``label -> RelationLabel``, refusing what the model could not answer about.

    GLiNER2 keys its answer by the label string it was given, so two types
    whose labels differ only in case would be two questions with
    indistinguishable intent, and an exact duplicate would be one key for two
    types. ``relation_types`` already forbids both among an exam's active
    types (a unique index ``COLLATE NOCASE``); this is that rule restated at
    the boundary, not a second one.
    """
    if not labels:
        raise ValueError('no relation types to ask about')
    index: Dict[str, RelationLabel] = {}
    seen: Dict[str, int] = {}
    for item in labels:
        text = item.label.strip()
        if not text:
            raise ValueError(f'relation type {item.type_id} has a blank label')
        folded = text.casefold()
        if folded in seen:
            raise ValueError(
                f'relation types {seen[folded]} and {item.type_id} share the '
                f'label {text!r}')
        seen[folded] = item.type_id
        index[text] = RelationLabel(type_id=item.type_id, label=text)
    return index


def proposals_from_raw(
    text: str,
    raw: Mapping[str, Any],
    by_label: Mapping[str, RelationLabel],
    threshold: float,
) -> Tuple[Proposal, ...]:
    """GLiNER2's formatted output -> :class:`Proposal` s, best first.

    One proposal per ``(type, head, tail)`` with heads and tails compared
    case-insensitively: chunk overlap, or a student who says the same thing
    twice, would otherwise propose the same relation twice. The
    highest-scoring occurrence is kept, with its own passage.

    A label the model returns that was not asked about is dropped and logged,
    never guessed at.
    """
    best: Dict[Tuple[int, str, str], Proposal] = {}
    for label, found in (raw.get('relation_extraction') or {}).items():
        target = by_label.get(label)
        if target is None:
            logger.warning('model returned an unrequested label %r; dropped', label)
            continue
        for item in found or ():
            head, tail = _mention(item.get('head')), _mention(item.get('tail'))
            if head is None or tail is None:
                continue
            score = min(head.confidence, tail.confidence)
            if score < threshold:
                continue
            s, e = passage_bounds(text, min(head.start, tail.start), max(head.end, tail.end))
            proposal = Proposal(
                relation_type_id=target.type_id, label=target.label,
                head=head, tail=tail, score=score,
                passage=text[s:e], passage_start=s, passage_end=e,
            )
            key = (target.type_id, head.text.casefold(), tail.text.casefold())
            if key not in best or best[key].score < score:
                best[key] = proposal
    return tuple(sorted(best.values(),
                        key=lambda p: (-p.score, p.passage_start, p.relation_type_id)))


def _mention(value: Any) -> Optional[Mention]:
    """A ``Mention`` from GLiNER2's ``{text, confidence, start, end}``, or ``None``."""
    if not isinstance(value, Mapping):
        return None
    try:
        text = str(value['text']).strip()
        start, end = int(value['start']), int(value['end'])
        confidence = round(float(value['confidence']), 4)
    except (KeyError, TypeError, ValueError):
        return None
    if not text or end <= start:
        return None
    return Mention(text=text, start=start, end=end, confidence=confidence)
