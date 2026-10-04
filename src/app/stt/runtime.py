"""Where the whisper.cpp binary and the model live, and how to run them (#59).

This module is the whole of the transcription engine: it resolves two files
that arrive by **two different routes**, answers "is this feature usable right
now?", and runs one subprocess. It imports no Qt and touches no database, so
the worker in ``jobs.py`` may call ``transcribe()`` directly -- that is the
contract in §3.4 of the plan, and it is enforced statically by
``tests/app/test_stt_jobs.py``.

The binary and the model resolve from different places, and that is the point
---------------------------------------------------------------------------

The **binary is bundled**. It is fetched at build time into
``vendor/whisper/<platform>/`` (``scripts/fetch_whisper.py``, T4) and carried
into the frozen build at ``_internal/whisper/<platform>/`` (T5). So it moves
when the build moves, and resolving it needs the frozen/dev branch.

The **model is downloaded** on first run (owner's decision D2), into
``app_data/models/whisper/``. That path is the same in dev and frozen, **with
no branch**, because ``app_data/`` is a student's data directory in both --
and on macOS it sits beside ``WIMI.app`` rather than inside it
(``src/app/main.py:33-43``), so a downloaded model survives replacing the
bundle. A frozen/dev branch on the model path would put a 141 MB download
inside a bundle that the next release deletes.

Which frozen base path, and why
-------------------------------

**One answer, stated the same way here and in both spec files:**

    ``Path(sys._MEIPASS) / 'whisper' / '<platform>'``

    Windows onedir   ``dist/WIMI/_internal/whisper/windows/whisper-cli.exe``
    macOS ``.app``   ``WIMI.app/Contents/Frameworks/whisper/macos-arm64/whisper-cli``

This codebase has **two frozen base paths in use and they are not the same
directory**. ``MainWindow.__init__`` uses ``Path(sys._MEIPASS) / 'web'``
(``main_window.py:100``); ``get_resource_path()`` in the same file
(``:12-26``) and ``schema_dir()`` (``migrations/_helpers.py:41``) use
``Path(sys.executable).parent / '_internal'``. The second names the same
directory on Windows and **does not exist inside a macOS ``.app``**, where
``sys.executable`` is ``Contents/MacOS/WIMI``.

``sys._MEIPASS`` is the one that is right on both **by definition rather than
by inspection**: PyInstaller points it at ``_internal`` in a onedir build, at
``Contents/Frameworks`` inside an ``.app``
(``fake-modules/_pyi_rth_utils/__init__.py`` keys on exactly that suffix),
and at the extraction directory in a onefile build. So this resolver does not
probe the filesystem to discover something already known, and there is no
``.exists()`` anywhere in it.

Two facts about the bundle that belong here because they constrain this
module rather than the spec. The tree is declared in the specs' ``binaries``
list, **not ``datas``** -- PyInstaller 6 reclassifies every collected file by
reading its contents before acting on any of it
(``bindepend.classify_binary_vs_data``), so the same bundle comes out either
way and the declaration was chosen to be the true statement; the one case
where it matters is a classification that returns ``None``, where the
declared typecode stands and a ``whisper-cli`` declared DATA would skip
dependency analysis and macOS path rewriting. And **the platform key must
contain no dot**: PyInstaller rewrites a directory name containing one under
``Contents/Frameworks`` to satisfy codesign, which is why
``host_platform()`` below says ``macos-arm64`` and never ``macos.arm64``.

All of that is reasoning about a build rather than a measurement. **T18
asserts it against a real frozen build**, which is why ``binary_dir()`` is a
public function with no side effects: a test can call it inside the bundle
and compare.

Reading the subprocess
----------------------

T1 settled the CLI contract; do not re-derive it. The binary is
``whisper-cli`` (``main.exe`` is a deprecated stub). With ``-np -nt``, stdout
carries the transcript and nothing else -- **all** logging goes to stderr
regardless of flags -- so there is nothing to parse and no JSON mode to ask
for. stderr is captured separately and logged, because that is where a real
failure explains itself.

**The return code is not the failure signal** (measured by T3 while building
``scripts/stt_measure.py``; #59 comment #2185, which is more current than the
plan on anything about invoking the binary). Re-measured here against
whisper.cpp **1.9.4 / b5130 on Linux x64**, since a fact this load-bearing
should be held by more than one run:

=========================  ======  ==============  ==============================
input                      exit    stdout          stderr
=========================  ======  ==============  ==============================
a text file named ``.wav``   **0**   **empty**       ``error: failed to read audio file``
model file absent            3      empty           ``error: failed to initialize whisper context``
model file truncated         3      empty           ``error: failed to initialize whisper context``
three seconds of silence     0      ``" you"``      normal timings
=========================  ======  ==============  ==============================

Three things follow, and each is a decision in the code below.

**A zero exit with empty stdout is a failure.** It is the only signal the
unreadable-audio case gives. And the row that makes this safe rather than
merely convenient is the last one: three seconds of digital silence does
**not** produce empty stdout -- it produces a hallucinated ``" you"``. So
"empty" never means "the student said nothing", and treating it as a failure
cannot swallow a legitimately silent recording. (That row is also why the
recorder's peak check matters beyond the Windows privacy toggle: without it,
a silent recording puts an invented word into the student's reflection.)

**A missing and a truncated model are indistinguishable to the engine** --
both exit 3 with the same "failed to initialize whisper context". That is
precisely the cryptic failure the plan asks this module to prevent, so the
model is verified *before* anything is invoked and the two arrive at the page
as ``model_missing`` and ``model_corrupt``, which have different fixes.
Nothing here depends on exit 3 to notice either.

Two more from the same measurement, both of which are things *not* to do
here. ``-np`` suppresses even the tokenizer's oversized-prompt warning, so
**there is no prompt length at which the engine reports a problem** -- this
module does not measure the prompt and must not pretend an engine error would
appear if it were too long; the 223-token budget is T10's, enforced before the
string arrives. And whisper.cpp's temperature fallback retries a segment that
fails its decode thresholds, which was observed to spread wall-clock time by
up to 10x on hard audio -- which is why the ceiling below is set where it is.

The CLI accepts wav/flac/mp3/ogg at any sample rate or channel count and
resamples internally via bundled miniaudio (T1 measured a 44.1 kHz stereo WAV
transcribing byte-identically to the 16 kHz mono original). So this module
**does not validate or convert its input**. It hands over whatever
``recorder.py`` wrote.

Plan: ``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §3.2, §3.3,
§3.8 and task T6.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform as platform_mod
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .errors import SttError, SttErrorKind

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Names and defaults
# --------------------------------------------------------------------------

#: Subdirectory holding the vendored engine, under ``_internal/`` when frozen
#: and under ``vendor/`` in a checkout. One constant so T4, T5 and T18 can
#: all name the same directory.
ENGINE_DIR_NAME = 'whisper'

#: Where the downloaded weights live, relative to ``app_data/``. Two levels
#: because ``app_data/models/`` is shared with other features that download
#: weights (the AI-capture branch puts its GGUF directly in ``models/``), and
#: a flat directory of ``ggml-*.bin`` beside a 2.5 GB GGUF is harder to
#: explain to a student who is trying to free disk space.
MODEL_DIR_PARTS = ('models', 'whisper')

#: T1: ``whisper-cli`` is the binary. ``main``/``main.exe`` is a deprecated
#: stub and must not be used as a fallback -- finding it would mean the fetch
#: script pulled the wrong asset, and running it would hide that.
BINARY_STEM = 'whisper-cli'

DEFAULT_LANGUAGE = 'en'

#: Wall-clock ceiling for one transcription. It exists because there is
#: **one** worker (§3.4) and a subprocess that never exits would hold the
#: whole feature forever.
#:
#: 120 s is the plan's proposal and is kept, but it is not comfortable and
#: the arithmetic should be redone when T3 reports real RTFs: at the 0.42x
#: max RTF measured for ``tiny.en`` (#59 comment #2185) a 60 s explanation is
#: ~25 s, and ``base`` is slower again -- so a long recording on a slow
#: machine with a larger model could approach this. Raising it is a
#: one-constant change and every caller can already override ``timeout_s``;
#: what must not happen is setting it near the *typical* time, because the
#: temperature fallback's 10x spread means typical is not the number that
#: matters.
TRANSCRIBE_TIMEOUT_S = 120.0

#: How much of stderr is kept in an error's ``detail``. The whole of it goes
#: to the log; the tail is what a student-facing error carries, and the useful
#: part of a whisper.cpp failure is always at the end.
STDERR_TAIL_CHARS = 2000

#: Streaming chunk for the sha256 check. 1 MiB keeps a 141 MB model at ~140
#: reads without holding it in memory.
_HASH_CHUNK = 1024 * 1024


def default_thread_count() -> int:
    """Threads to hand ``-t``.

    Capped at 4 rather than "every core": whisper.cpp's own default is 4, the
    gains past that are small for the ``base``-class models this feature uses,
    and the student is *waiting on the UI thread's page* while this runs --
    leaving headroom on a 4-core laptop matters more than the last 10%.
    """
    return max(1, min(4, os.cpu_count() or 1))


# --------------------------------------------------------------------------
# Locating the two files
# --------------------------------------------------------------------------

def host_platform() -> str:
    """The platform tag naming this machine's subdirectory of the engine dir.

    The tags match ``scripts/fetch_whisper.py`` (T4) and the specs'
    ``WHISPER_PLATFORM`` (T5) -- ``windows``, ``macos-arm64``, ``macos-x64``,
    ``linux`` -- which in turn follow ``scripts/fetch_llama_server.py`` on
    ``feature/ai-capture``. A fetch script that writes ``macos-arm64`` while
    the runtime looks in ``darwin`` fails only on the machine nobody tests on.

    **No tag may contain a dot.** PyInstaller rewrites a directory name
    containing one under ``Contents/Frameworks`` to satisfy codesign and
    leaves a symlink behind, so ``macos-arm64`` is collected verbatim and
    ``macos.arm64`` would not have been.
    """
    if sys.platform.startswith('win'):
        return 'windows'
    if sys.platform == 'darwin':
        machine = platform_mod.machine().lower()
        return 'macos-arm64' if machine in ('arm64', 'aarch64') else 'macos-x64'
    return 'linux'


def binary_name() -> str:
    """``whisper-cli`` with the host's executable suffix."""
    return BINARY_STEM + ('.exe' if sys.platform.startswith('win') else '')


def engine_root() -> Path:
    """The directory holding every platform's engine subdirectory.

    Frozen: ``<_MEIPASS>/whisper``. Dev: ``<repo>/vendor/whisper``. No
    filesystem probe -- see the module docstring for why ``sys._MEIPASS`` is
    the answer on every bundle shape rather than one candidate among several.
    """
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return Path(meipass) / ENGINE_DIR_NAME
        # Only reachable if something other than PyInstaller set sys.frozen.
        # We ship no such build; this exists so a path resolver cannot raise
        # AttributeError, and it is NOT a second candidate to be probed.
        return Path(sys.executable).parent / '_internal' / ENGINE_DIR_NAME
    # Dev: src/app/stt/runtime.py -> parents[3] is the repo root.
    return Path(__file__).resolve().parents[3] / 'vendor' / ENGINE_DIR_NAME


def binary_dir() -> Path:
    """This platform's engine directory -- the binary and its shared libraries."""
    return engine_root() / host_platform()


def binary_path() -> Path:
    """Where ``whisper-cli`` should be. Says nothing about whether it is."""
    return binary_dir() / binary_name()


def find_binary() -> Optional[Path]:
    """The runnable binary, or ``None``.

    "Runnable" is checked as well as "present" because the most likely way to
    end up with an unrunnable one is a fetch that extracted without the
    executable bit -- a failure that otherwise surfaces as ``PermissionError``
    from deep inside ``subprocess`` with no mention of whisper at all.
    """
    path = binary_path()
    try:
        if not path.is_file():
            return None
        if os.name != 'nt' and not os.access(path, os.X_OK):
            logger.warning('whisper binary is present but not executable: %s', path)
            return None
    except OSError as exc:  # a dead symlink, a permission error on the dir
        logger.warning('could not stat the whisper binary at %s: %s', path, exc)
        return None
    return path


def model_dir(app_data_dir: str | Path) -> Path:
    """``<app_data>/models/whisper``, created if absent.

    **No frozen branch, deliberately** -- see the module docstring. Eager
    ``mkdir`` follows ``browser_pane.py:338-339``: the directory is cheap, and
    the downloader (T21) writing a ``.part`` into a directory that does not
    exist yet is a failure mode nobody needs.
    """
    path = Path(app_data_dir).joinpath(*MODEL_DIR_PARTS)
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------
# The pinned model table (T21 owns it; this is the shape we consume)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelFile:
    """One row of the pin table, normalised.

    **T21 owns ``src/app/stt/model_spec.py``** -- the single pin table of
    repo, revision, filename, sha256, byte size and licence per model size
    (§3.3). This module must consume it, never duplicate it, so all it
    declares here is the narrow set of fields *transcription* needs:

    ``size``          the key ("base", "base.en", "base-q5_1", ...)
    ``filename``      the on-disk name, e.g. ``ggml-base.en.bin``
    ``sha256``        the pinned digest, or ``''`` while unpinned
    ``size_bytes``    the pinned byte size, or ``None``

    ``from_spec`` accepts a mapping **or** an object with attributes, so
    whichever of the two shapes T21 lands works without a change here. That
    tolerance is for the parallel-wave handover; once the two are reconciled
    it can narrow.
    """

    size: str
    filename: str
    sha256: str = ''
    size_bytes: Optional[int] = None

    @classmethod
    def from_spec(cls, size: str, spec: Any) -> 'ModelFile':
        def pick(*names, default=None):
            for name in names:
                if isinstance(spec, Mapping):
                    if name in spec:
                        return spec[name]
                elif hasattr(spec, name):
                    return getattr(spec, name)
            return default

        filename = pick('filename', 'name')
        if not filename:
            raise ValueError(
                f'model spec for {size!r} carries no filename: {spec!r}'
            )
        raw_size = pick('size_bytes', 'expected_bytes', 'bytes')
        return cls(
            size=str(pick('size', 'model_size', default=size) or size),
            filename=str(filename),
            sha256=str(pick('sha256', 'digest', default='') or ''),
            size_bytes=int(raw_size) if raw_size else None,
        )


def _import_model_spec():
    """Import T21's pin table lazily.

    Lazily because this module is imported by tests that inject their own
    spec, and because a missing pin table is a **build** defect rather than a
    runtime state: it fails loud, the way ``read_schema_file`` does for a
    schema that was not bundled, instead of degrading into "no model
    installed" and offering a download that cannot work.
    """
    from . import model_spec  # noqa: PLC0415 - deliberate, see docstring
    return model_spec


def default_model_size() -> str:
    """The pinned default size, from T21's table."""
    spec_module = _import_model_spec()
    for name in ('DEFAULT_MODEL_SIZE', 'DEFAULT_SIZE'):
        value = getattr(spec_module, name, None)
        if value:
            return str(value)
    raise AttributeError(
        'model_spec exposes no DEFAULT_MODEL_SIZE; the runtime needs one to '
        'resolve a model without being told a size.'
    )


def lookup_model(size: str) -> ModelFile:
    """One row of T21's pin table, normalised into a ``ModelFile``."""
    spec_module = _import_model_spec()
    getter = getattr(spec_module, 'get_model_spec', None)
    if callable(getter):
        return ModelFile.from_spec(size, getter(size))
    for name in ('MODEL_SPECS', 'MODELS', 'SPECS'):
        table = getattr(spec_module, name, None)
        if isinstance(table, Mapping) and size in table:
            return ModelFile.from_spec(size, table[size])
    raise KeyError(f'no pinned model spec for size {size!r}')


# --------------------------------------------------------------------------
# Verifying the model, once per process
# --------------------------------------------------------------------------

#: Verdicts already reached, keyed by (path, byte size, mtime_ns). Verifying
#: a 141 MB file is ~0.3 s of I/O and hashing, and ``getSttStatus()`` is
#: polled by the page; re-hashing on every poll would be visible. Keyed on
#: the file's identity rather than its name so a **replaced** model (a
#: finished download, a repaired file) is verified again rather than
#: inheriting the old verdict. Failures are cached too, for the same reason.
_VERDICTS: dict[tuple, Optional[SttError]] = {}
_VERDICT_LOCK = threading.Lock()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b''):
            digest.update(chunk)
    return digest.hexdigest()


def clear_verification_cache() -> None:
    """Forget every cached verdict. For tests and for a repaired download."""
    with _VERDICT_LOCK:
        _VERDICTS.clear()


def verify_model_file(path: Path, spec: ModelFile) -> None:
    """Raise ``SttError(MODEL_CORRUPT)`` unless ``path`` matches the pin.

    Size first, because it is a stat rather than a read and because the
    failure it catches -- a truncated download -- is the likely one. A model
    that fails this must produce a **named** error: a truncated ggml file
    makes ``whisper-cli`` exit non-zero with a message about a magic number,
    which reads to a student as "the feature is broken".
    """
    try:
        stat = path.stat()
    except OSError as exc:
        raise SttError(SttErrorKind.MODEL_MISSING, f'{path}: {exc}') from exc

    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _VERDICT_LOCK:
        if key in _VERDICTS:
            cached = _VERDICTS[key]
            if cached is not None:
                raise cached
            return

    error: Optional[SttError] = None
    if spec.size_bytes and stat.st_size != spec.size_bytes:
        error = SttError(
            SttErrorKind.MODEL_CORRUPT,
            f'{path.name} is {stat.st_size} bytes, expected {spec.size_bytes}',
        )
    elif not spec.sha256:
        # An unpinned digest is a state the pin table can be in before
        # scripts/pin_whisper_model.py has run against the real host. Say so
        # once rather than either failing (nothing would work) or staying
        # quiet (an unverified model would look verified).
        logger.warning(
            'model %s has no pinned sha256; checked byte size only', spec.filename
        )
    else:
        actual = _sha256_file(path)
        if actual != spec.sha256:
            error = SttError(
                SttErrorKind.MODEL_CORRUPT,
                f'{path.name} sha256 {actual} does not match the pin {spec.sha256}',
            )

    with _VERDICT_LOCK:
        _VERDICTS[key] = error
    if error is not None:
        logger.error('speech model failed verification: %s', error.detail)
        raise error


# --------------------------------------------------------------------------
# Three states, not one boolean
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ComponentState:
    """One of the three things that must be true, and why it is not.

    ``error`` is a serialised ``SttError`` -- so "no binary"
    (``binary_missing``) and "no model" (``model_missing``) arrive at the page
    as **different kinds with different fixes**: one is "this build is
    broken", the other is "press the button and wait for 140 MB".
    """

    ready: bool
    detail: dict = field(default_factory=dict)
    error: Optional[dict] = None

    def to_dict(self) -> dict:
        out = {'ready': self.ready}
        out.update(self.detail)
        out['error'] = self.error
        return out


@dataclass(frozen=True)
class SttAvailability:
    """Is this feature usable right now -- as three answers, never one.

    Collapsing these into ``available: false`` is how a student ends up with
    a greyed button and no idea which of three problems they have (§3.8, §7).
    The three are independent: an engine with no model, a model with no
    microphone and a working pair with a microphone another app holds are
    three different sentences on screen.

    ``microphone`` is whatever ``recorder.py`` (T7) reports, passed in rather
    than probed here -- this module must not import Qt (§3.4). ``None`` means
    nobody asked, which is not the same as "no microphone" and must not be
    rendered as one.
    """

    engine: ComponentState
    model: ComponentState
    microphone: Optional[dict] = None

    @property
    def ready(self) -> bool:
        """Every state true. For logging and tests -- **not** for the UI."""
        return bool(
            self.engine.ready
            and self.model.ready
            and (self.microphone or {}).get('ready', False)
        )

    def to_dict(self) -> dict:
        return {
            'engine_ready': self.engine.ready,
            'model_ready': self.model.ready,
            'microphone_ready': (
                None if self.microphone is None
                else bool(self.microphone.get('ready', False))
            ),
            'engine': self.engine.to_dict(),
            'model': self.model.to_dict(),
            'mic': self.microphone,
        }


@dataclass(frozen=True)
class TranscriptionResult:
    """What a finished run produced.

    ``stderr`` is carried so the caller can log it beside its own context; it
    is never parsed and never shown to a student.
    """

    text: str
    ms: int
    stderr: str = ''


# --------------------------------------------------------------------------
# The runtime
# --------------------------------------------------------------------------

@dataclass
class WhisperRuntime:
    """Resolve, verify, invoke. No Qt, no database, no threads of its own.

    Everything is an argument with a resolving default so a test can point the
    whole thing at a temporary directory, and so the frozen/dev branch is
    exercised by the resolver's own tests rather than by every test that wants
    to run something.
    """

    app_data_dir: str | Path
    model_size: Optional[str] = None
    binary: Optional[str | Path] = None
    #: Injected pin-table lookup: ``(size) -> ModelFile``. Left ``None`` in
    #: production, where it resolves through T21's ``model_spec``.
    spec_lookup: Optional[Callable[[str], ModelFile]] = None
    language: str = DEFAULT_LANGUAGE
    threads: Optional[int] = None
    timeout_s: float = TRANSCRIBE_TIMEOUT_S

    # -- resolution --------------------------------------------------------

    def resolve_binary(self) -> Path:
        """The engine, or ``SttError(BINARY_MISSING)`` naming where it looked."""
        if self.binary is not None:
            path = Path(self.binary)
            if not path.is_file():
                raise SttError(SttErrorKind.BINARY_MISSING, str(path))
            return path
        found = find_binary()
        if found is None:
            raise SttError(SttErrorKind.BINARY_MISSING, str(binary_path()))
        return found

    def resolve_model_spec(self) -> ModelFile:
        lookup = self.spec_lookup or lookup_model
        size = self.model_size
        if size is None:
            if self.spec_lookup is not None:
                raise ValueError('a spec_lookup needs an explicit model_size')
            size = default_model_size()
        return lookup(size)

    @property
    def model_directory(self) -> Path:
        return model_dir(self.app_data_dir)

    def resolve_model(self) -> Path:
        """The verified model file.

        Raises ``MODEL_MISSING`` when it has not been downloaded and
        ``MODEL_CORRUPT`` when it has but does not match the pin. Two kinds,
        because the fixes differ: download it, versus delete it and download
        it again.
        """
        spec = self.resolve_model_spec()
        path = self.model_directory / spec.filename
        if not path.is_file():
            raise SttError(SttErrorKind.MODEL_MISSING, str(path))
        verify_model_file(path, spec)
        return path

    # -- status ------------------------------------------------------------

    def availability(self, microphone: Optional[Mapping] = None) -> SttAvailability:
        """The three states. Cheap enough for the page to poll."""
        try:
            binary = self.resolve_binary()
            engine = ComponentState(True, {'path': str(binary)})
        except SttError as exc:
            engine = ComponentState(False, {'path': exc.detail}, exc.to_dict())

        model_detail: dict = {}
        try:
            spec = self.resolve_model_spec()
            model_detail = {
                'size': spec.size,
                'filename': spec.filename,
                'expected_bytes': spec.size_bytes,
                'path': str(self.model_directory / spec.filename),
            }
            path = self.resolve_model()
            model_detail['path'] = str(path)
            model = ComponentState(True, model_detail)
        except SttError as exc:
            # installed-but-corrupt is a different sentence from not-installed,
            # and the page needs to tell them apart without re-deriving it.
            model_detail['installed'] = exc.kind is SttErrorKind.MODEL_CORRUPT
            model = ComponentState(False, model_detail, exc.to_dict())

        return SttAvailability(
            engine=engine,
            model=model,
            microphone=dict(microphone) if microphone is not None else None,
        )

    # -- invocation --------------------------------------------------------

    def build_argv(
        self,
        binary: Path,
        model: Path,
        audio: Path,
        prompt: str = '',
    ) -> list[str]:
        """The exact command line, in one place so a test can assert on it.

        Settled by T1: ``-m`` model, ``-f`` file, ``-l`` language, ``-t``
        threads, ``-np -nt`` for clean output. ``--prompt`` is appended **only
        when the priming string is non-empty** -- an empty ``--prompt ''``
        would spend the argument on nothing and, worse, reads in a log as
        though priming were on when T10 had decided it was off.
        """
        argv = [
            str(binary),
            '-m', str(model),
            '-f', str(audio),
            '-l', self.language,
            '-t', str(self.threads or default_thread_count()),
            '-np',
            '-nt',
        ]
        if prompt and prompt.strip():
            argv += ['--prompt', prompt]
        return argv

    def transcribe(
        self,
        audio_path: str | Path,
        *,
        prompt: str = '',
        delete_audio: bool = True,
    ) -> TranscriptionResult:
        """Run one transcription. Blocking, and safe on a worker thread.

        ``delete_audio`` defaults to **True** and the delete happens in a
        ``finally``, on every path including failure and timeout: the input is
        a recording of the student's voice written to a temp file, and leaving
        it behind on the one path nobody tests is how a disk fills with audio
        nobody meant to keep. Pass ``False`` only for a file this process does
        not own -- a checked-in fixture, say.
        """
        audio = Path(audio_path)
        started = time.monotonic()
        try:
            binary = self.resolve_binary()
            model = self.resolve_model()
            argv = self.build_argv(binary, model, audio, prompt)
            logger.info(
                'transcribing %s with %s (%s)',
                audio.name, model.name, 'primed' if prompt.strip() else 'unprimed',
            )
            try:
                completed = subprocess.run(
                    argv,
                    stdin=subprocess.DEVNULL,   # a frozen GUI has no stdin
                    capture_output=True,
                    timeout=self.timeout_s,
                    check=False,
                    # No cwd=. Windows searches the directory of the
                    # executable image for its DLLs before it looks anywhere
                    # else, so whisper-cli finds the twelve ggml/whisper dlls
                    # beside it whatever the working directory is -- while
                    # setting one would silently change what a relative -f or
                    # -m resolved against.
                    **_no_console_window(),
                )
            except subprocess.TimeoutExpired as exc:
                # subprocess.run has already killed and reaped the child.
                raise SttError(
                    SttErrorKind.TRANSCRIPTION_TIMEOUT,
                    f'whisper-cli did not finish within {self.timeout_s:g}s',
                ) from exc
            except OSError as exc:
                # The binary vanished or is not executable after all -- a
                # different fix from "it produced a bad answer", so a
                # different kind.
                raise SttError(SttErrorKind.BINARY_MISSING, f'{binary}: {exc}') from exc

            stderr = _decode(completed.stderr)
            if stderr:
                # Never parsed -- only logged, because this is where a real
                # failure explains itself. DEBUG on success: a successful run
                # still writes its model-load banner and timings there, which
                # is useful when T3 is measuring and noise the rest of the
                # time.
                logger.log(
                    logging.ERROR if completed.returncode != 0 else logging.DEBUG,
                    'whisper-cli stderr: %s', stderr.strip(),
                )
            if completed.returncode != 0:
                raise SttError(
                    SttErrorKind.TRANSCRIPTION_FAILED,
                    f'whisper-cli exited {completed.returncode}: '
                    f'{stderr.strip()[-STDERR_TAIL_CHARS:]}',
                )

            # stdout IS the transcript. With -np -nt there is nothing else in
            # it, so the only processing is stripping the trailing newline.
            text = _decode(completed.stdout).strip()
            ms = int((time.monotonic() - started) * 1000)
            if not text:
                # Exit 0 and nothing on stdout is how an unreadable audio file
                # presents -- the return code is NOT the failure signal (#59
                # comment #2185; see the module docstring). Silence is the
                # recorder's to detect and has already been ruled out by the
                # time a file gets here, so this is the engine saying it could
                # not read what it was handed. The stderr tail carries the
                # actual sentence, which is usually
                # "error: failed to read audio file".
                raise SttError(
                    SttErrorKind.TRANSCRIPTION_FAILED,
                    'whisper-cli exited 0 but wrote no transcript: '
                    f'{stderr.strip()[-STDERR_TAIL_CHARS:]}',
                )
            return TranscriptionResult(text=text, ms=ms, stderr=stderr)
        finally:
            if delete_audio:
                try:
                    audio.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning('could not remove %s: %s', audio, exc)


def _decode(raw: bytes | str | None) -> str:
    """Bytes off the subprocess, as text.

    Explicitly UTF-8, which is why ``capture_output`` is left in bytes mode
    rather than passing ``text=True``: that decodes with the **locale**
    encoding, which on Windows is cp1252, and a transcript is exactly the kind
    of string that carries a character cp1252 cannot represent. #137 is the
    same lesson from the other direction.
    """
    if raw is None:
        return ''
    if isinstance(raw, str):
        return raw
    return raw.decode('utf-8', errors='replace')


def _no_console_window() -> dict:
    """Keep a console window from flashing over the app on Windows.

    ``wimi.spec`` keeps ``console=True`` with ``hide_console='hide-early'``
    (#142), so WIMI owns a hidden console; spawning a child without this flag
    pops a visible one for the length of the transcription.
    """
    if os.name == 'nt':
        return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
    return {}
