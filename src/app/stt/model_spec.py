"""The pinned whisper.cpp weights: what file, what digest, where it installs.

**One pin table.** The downloader (``download.py``), the runtime that invokes
whisper-cli (``runtime.py``, T6), the bridge and the settings page all read
this module and nothing else. A revision pinned in two places is a revision
that will eventually disagree with itself (plan §3.3), and a *wrong* pin is
worse than no pin because everything downstream trusts it -- so the values
below are written by ``scripts/pin_whisper_model.py`` from the host, never by
hand.

Why the weights are not in the installer
----------------------------------------

Owner's decision D2 (plan §0, §3.8): the binary ships, the weights download on
first run, sha256-verified, into ``app_data/``. Bundling was weighed and
rejected; §3.8 keeps the argument so it is not re-proposed.

Where the model installs -- there is no frozen-mode branch
-----------------------------------------------------------

``<app_data_dir>/models/whisper/ggml-<size>.bin``, in development **and** in a
frozen build, with no ``sys.frozen`` test anywhere in this module. That
asymmetry with the rest of the codebase is the design, not an oversight:

* the **binary** is bundled by PyInstaller, so where it lives differs between
  a checkout and ``_internal/`` and ``runtime.py`` must branch on frozen mode
  to find it;
* the **model** is downloaded at runtime into writable application data, which
  is the same place in both modes. A frozen branch here could only point at a
  directory inside the bundle, which is read-only on macOS and replaced
  wholesale on every update.

On macOS ``app_data/`` sits *beside* ``WIMI.app``, not inside it
(``src/app/main.py:33-43``), so a downloaded model survives replacing the
bundle. On a ``--test-mode`` run ``app_data_dir`` is ``app_data_test/``, so a
test build downloads its own copy; that is correct and deliberate, not
something to work around.

What T6 consumes
----------------

::

    from app.stt.model_spec import (
        DEFAULT_MODEL_SIZE, MODELS, MODEL_SIZES, ModelSpec, UnknownModelSize,
        get_spec, model_dir, model_path, part_path, is_installed,
        verify_file, sha256_file, download_url,
    )

    spec = get_spec(size_from_device_settings)   # None/'' -> DEFAULT_MODEL_SIZE
    path = model_path(app_data_dir, spec.size)   # creates the directory
    if not is_installed(app_data_dir, spec.size):
        ...offer the download (T11/T13/T14)
    verify_file(path, spec)                      # raises SttError; cache per process

``is_installed`` is the **cheap** check -- the file exists and its byte size
matches the pin -- and is what a UI asks before offering a download.
``verify_file`` is the **honest** one: it hashes. Both live here rather than in
``download.py`` so that "does this file match the pin" has one answer, and so
that T6 needs no import from the downloader at all.

§3.7 keeps **no database column recording that a model is installed**: the file
plus its digest is the record. That is only trustworthy because
``download.py`` writes to ``<name>.bin.part`` and ``os.replace()``s into
position, so a half-finished download never looks installed (R15).
"""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple, Union

from .errors import SttError, SttErrorKind

PathLike = Union[str, os.PathLike]


# --------------------------------------------------------------------------
# Where the weights come from
# --------------------------------------------------------------------------

#: The ggml conversions, published by the whisper.cpp author.
MODEL_REPO = 'ggerganov/whisper.cpp'

#: The repo commit the table below was read from. Pinned to a commit rather
#: than ``main`` so a re-upload cannot change what a student downloads without
#: this file changing first. Rewritten by ``scripts/pin_whisper_model.py``.
MODEL_REVISION = '5359861c739e955e79d9a303bcbc70fb988958b1'

#: Confirmed at the source (the repo's own card metadata reports ``mit``), not
#: taken from the plan's prose: whisper.cpp is MIT, OpenAI's Whisper weights
#: are MIT, and these conversions are redistributed under MIT. §3.8 asks for
#: the model's licence to be recorded here and in the student guide (T20).
MODEL_LICENCE = 'MIT'
MODEL_LICENCE_URL = f'https://huggingface.co/{MODEL_REPO}/blob/main/README.md'

_DOWNLOAD_URL_TEMPLATE = 'https://huggingface.co/{repo}/resolve/{revision}/{filename}'

#: ``app_data/models/whisper``. Two module-level name constants and a helper
#: that joins them onto ``app_data_dir``, following ``browser_pane.py:50``.
MODELS_DIR_NAME = 'models'
WHISPER_DIR_NAME = 'whisper'

#: Suffix appended to the destination while a download is in flight. Never a
#: prefix and never a sibling temp name: ``ggml-base.en.bin.part`` sorts beside
#: the file it will become and cannot be mistaken for a model by a glob on
#: ``*.bin``.
PART_SUFFIX = '.part'


# --------------------------------------------------------------------------
# The default size
# --------------------------------------------------------------------------

# Chosen by the owner on 2026-09-23 from T3's measurement (#59 comments
# #2275, #2276). The placeholder that stood here is gone; so is its TODO.
#
# The measurement: 16 utterances of the owner's own voice, ~5 minutes, read
# from a corpus built out of their own subject tree (3,118 entries, 6 exam
# contexts), scored on **term recall** rather than WER -- one proving
# utterance scored 6.0% WER while destroying three of six drug names, so WER
# hides the exact failure this feature cannot tolerate.
#
#   small.en-q5_1  84.1% recall   ~99% precision   0 invented   0.47x RTF   181 MiB
#   small.en       85.0%          98.9%            0            0.44x       465 MiB
#   base.en        74.8%          100%             0            0.15x       141 MiB
#   medium.en-q5_0 87.9%          100%             0            1.44x       514 MiB
#
# Why this one. Against `small.en` the difference is 0.9 pp, well inside the
# corpus's +/-4.1 pp interval -- statistically indistinguishable -- for 61%
# less download at the same speed. Against `base.en` it is **+9.3 pp for 40
# MiB**, which is why `base.en` is no longer the size §3.8's first-run copy
# should quote. `medium.en-q5_0` is the most accurate thing measured and is
# disqualified on speed: at 1.44x a three-minute explanation takes four and a
# half minutes to transcribe, which is longer than the student spent speaking.
#
# Two results worth keeping, because both contradict what a reasonable person
# would guess:
#
# * **Quantisation beat model size at a fixed download budget.** Every earlier
#   comparison was fp16-only, which made "bigger model" mean "much bigger
#   download". It does not: a quantised larger model fits the same budget.
# * **`large-v3-turbo-q5_0` was the worst of the four AND the slowest** (82.2%,
#   1.80x), despite being the family behind the owner's own reference
#   transcripts. It is multilingual, and the `.en` models are English-only
#   fine-tunes that beat it on English; and its speed comes from cutting
#   decoder layers while keeping a full-size encoder, which on CPU is the part
#   that dominates. Do not reach for it here on the strength of its reputation
#   elsewhere.
#
# The pinned digest below is the **same file that produced 84.1%** -- verified
# by hashing the measured copy against the pin rather than assuming it.
#
# Ten configurations have now failed the plan's proposed >=95% recall bar and
# the best of them fails on speed, so that bar was wrong rather than the
# models: 95% on drug generics and eponyms is not available from local CPU
# whisper at any size that fits this product. What does move it is #166 --
# correcting the transcript against the student's own subject tree, measured
# at 85.0% -> 88.8% on this model, better than tripling the model.
DEFAULT_MODEL_SIZE = 'small.en-q5_1'


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSpec:
    """One downloadable model: the four pinned facts plus what follows.

    ``size`` is the whisper.cpp model name (``base.en``, ``base-q5_1``), which
    is also what ``device_settings.stt_model_size`` stores and what
    ``whisper-cli -m`` is ultimately pointed at.
    """

    size: str
    filename: str
    sha256: str
    size_bytes: int

    # -- derived from ``size``, never pinned separately -------------------

    @property
    def english_only(self) -> bool:
        """``.en`` models drop the multilingual head. Smaller and, for
        English dictation, usually better."""
        return '.en' in self.size

    @property
    def quantisation(self) -> Optional[str]:
        """``'q5_1'``, ``'q8_0'`` or ``None`` for the full-precision model."""
        _, _, tail = self.size.partition('-')
        return tail or None

    @property
    def baseline_size(self) -> str:
        """The unquantised model this one is a quantisation of.

        The comparison baseline for accuracy work: ``base-q5_1``'s baseline is
        ``base``, never ``base.en``.
        """
        return self.size.partition('-')[0]

    @property
    def licence(self) -> str:
        return MODEL_LICENCE

    @property
    def url(self) -> str:
        return download_url(self)

    def megabytes(self) -> float:
        """Decimal MB, because that is what a download dialog should say."""
        return self.size_bytes / 1_000_000


def _pins() -> Tuple[Tuple[str, str, str, int], ...]:
    """The pinned rows: ``(size, filename, sha256, size_bytes)``.

    Everything between the two markers is **generated**. Add a row by hand
    with a 64-zero digest and run ``python scripts/pin_whisper_model.py``; do
    not type a digest read off a web page or a report. Task T1 transcribed its
    own sha256 values truncated to 63 characters, which is exactly the class of
    mistake this arrangement removes.
    """
    return (
        # --- BEGIN PINS (rewritten by scripts/pin_whisper_model.py) ---
        ('tiny.en', 'ggml-tiny.en.bin', '921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f', 77704715),
        ('tiny', 'ggml-tiny.bin', 'be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21', 77691713),
        ('base.en', 'ggml-base.en.bin', 'a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002', 147964211),
        ('base', 'ggml-base.bin', '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe', 147951465),
        ('base-q5_1', 'ggml-base-q5_1.bin', '422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898', 59707625),
        ('base-q8_0', 'ggml-base-q8_0.bin', 'c577b9a86e7e048a0b7eada054f4dd79a56bbfa911fbdacf900ac5b567cbb7d9', 81768585),
        ('small.en', 'ggml-small.en.bin', 'c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d', 487614201),
        ('small', 'ggml-small.bin', '1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b', 487601967),
        ('small.en-q5_1', 'ggml-small.en-q5_1.bin', 'bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30', 190098681),
        # --- END PINS ---
    )


MODELS: Dict[str, ModelSpec] = {
    size: ModelSpec(size=size, filename=filename, sha256=sha256, size_bytes=size_bytes)
    for size, filename, sha256, size_bytes in _pins()
}

#: Offered order: smallest first, so a settings dropdown reads as a cost
#: gradient. This is the order the table is written in, not a sort, because
#: ``tiny.en``/``tiny`` and the quantised variants interleave by byte size in a
#: way that would scramble the families.
MODEL_SIZES: Tuple[str, ...] = tuple(MODELS)


class UnknownModelSize(ValueError):
    """A size that is not in the pin table.

    Raised rather than silently falling back to the default: a stale
    ``device_settings.stt_model_size`` pointing at a size that has since left
    the table is worth a message, and a quiet substitution would transcribe
    with a model the student did not choose.
    """


def get_spec(size: Optional[str] = None) -> ModelSpec:
    """The spec for ``size``. ``None`` or ``''`` means ``DEFAULT_MODEL_SIZE``."""
    name = (size or '').strip() or DEFAULT_MODEL_SIZE
    try:
        return MODELS[name]
    except KeyError:
        raise UnknownModelSize(
            f'unknown whisper model size {name!r}; '
            f'pinned sizes are {", ".join(MODEL_SIZES)}'
        ) from None


def download_url(spec_or_size: Union[ModelSpec, str, None] = None) -> str:
    """The pinned URL for a model. Takes a spec or a size, for convenience."""
    spec = spec_or_size if isinstance(spec_or_size, ModelSpec) else get_spec(spec_or_size)
    return _DOWNLOAD_URL_TEMPLATE.format(
        repo=MODEL_REPO, revision=MODEL_REVISION, filename=spec.filename
    )


# --------------------------------------------------------------------------
# Where it lands
# --------------------------------------------------------------------------


def model_dir(app_data_dir: PathLike, *, create: bool = True) -> Path:
    """``<app_data_dir>/models/whisper``, created by default.

    Eager ``mkdir(parents=True, exist_ok=True)`` follows
    ``browser_pane.py:338-339``. Pass ``create=False`` where the answer is
    wanted without a side effect -- a settings page reporting a path, or a
    test asserting the layout.
    """
    path = Path(app_data_dir) / MODELS_DIR_NAME / WHISPER_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def model_path(app_data_dir: PathLike, size: Optional[str] = None, *, create: bool = True) -> Path:
    """Where ``size`` installs. The same path in dev and frozen, by design."""
    spec = get_spec(size)
    return model_dir(app_data_dir, create=create) / spec.filename


def part_path(destination: PathLike) -> Path:
    """The in-flight name for a destination: ``ggml-base.en.bin.part``."""
    path = Path(destination)
    return path.with_name(path.name + PART_SUFFIX)


def is_installed(app_data_dir: PathLike, size: Optional[str] = None) -> bool:
    """Cheap: the file is there and its byte size matches the pin.

    Deliberately does **not** hash -- this is what a page asks before deciding
    whether to offer a download, and hashing 140 MB to render a button is the
    #147 mistake (a status check that does real work) in another costume. Call
    ``verify_file`` before invoking the binary.
    """
    spec = get_spec(size)
    path = model_dir(app_data_dir, create=False) / spec.filename
    try:
        return path.stat().st_size == spec.size_bytes
    except OSError:
        return False


def installed_sizes(app_data_dir: PathLike) -> Tuple[str, ...]:
    """Which pinned sizes are present on this machine, in offered order."""
    return tuple(size for size in MODEL_SIZES if is_installed(app_data_dir, size))


#: 1 MiB. Large enough that hashing is I/O bound, small enough that a cancel
#: between chunks is felt immediately.
CHUNK_BYTES = 1 << 20


def sha256_file(
    path: PathLike,
    *,
    chunk_bytes: int = CHUNK_BYTES,
    cancel: Optional[threading.Event] = None,
    progress: Optional[Callable[[int, Optional[int]], None]] = None,
) -> str:
    """Hex digest of a file, read in chunks so a 487 MB model does not sit in RAM.

    ``cancel`` is honoured between chunks: hashing a large model is seconds of
    work, and a cancel that only applies to the network half would look like
    the button had stopped responding.
    """
    digest = hashlib.sha256()
    read = 0
    total: Optional[int] = None
    try:
        total = os.path.getsize(path)
    except OSError:
        total = None
    with open(path, 'rb') as handle:
        while True:
            if cancel is not None and cancel.is_set():
                raise SttError(SttErrorKind.DOWNLOAD_CANCELLED, 'cancelled while verifying')
            block = handle.read(chunk_bytes)
            if not block:
                break
            digest.update(block)
            read += len(block)
            if progress is not None:
                progress(read, total)
    return digest.hexdigest()


def verify_file(
    path: PathLike,
    spec: Optional[ModelSpec] = None,
    *,
    cancel: Optional[threading.Event] = None,
) -> None:
    """Raise unless the file on disk *is* the pinned model.

    Byte size first, because it is a ``stat`` and catches the common failure
    (a truncated or range-confused download) without reading 140 MB; then the
    digest, which is the one that actually decides.

    Raises ``SttError(MODEL_MISSING)`` when there is no file and
    ``SttError(MODEL_CORRUPT)`` when there is the wrong one. The download path
    raises ``DOWNLOAD_FAILED`` for its own verification instead -- see
    ``download.py`` for why the two differ.
    """
    spec = spec or get_spec()
    file_path = Path(path)
    try:
        actual_size = file_path.stat().st_size
    except OSError as exc:
        raise SttError(SttErrorKind.MODEL_MISSING, f'{file_path}: {exc}') from exc

    if actual_size != spec.size_bytes:
        raise SttError(
            SttErrorKind.MODEL_CORRUPT,
            f'{file_path.name} is {actual_size} bytes, pinned at {spec.size_bytes}',
        )

    actual_sha = sha256_file(file_path, cancel=cancel)
    if actual_sha != spec.sha256:
        raise SttError(
            SttErrorKind.MODEL_CORRUPT,
            f'{file_path.name} sha256 {actual_sha} does not match pin {spec.sha256}',
        )
