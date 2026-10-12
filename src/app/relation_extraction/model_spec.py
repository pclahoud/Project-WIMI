"""The pinned GLiNER2 weights: which files, what digests, where they install.

**One pin table.** The downloader (``download.py``), the runtime that builds a
model (``runtime.py``), the bridge and the Settings line all read this module
and nothing else. A revision pinned in two places is a revision that will
eventually disagree with itself, and a *wrong* pin is worse than no pin because
everything downstream trusts it -- so no digest below is typed by hand. They
are written by ``scripts/pin_relations_model.py``.

This module imports no runtime package. It is stdlib plus :mod:`.errors`, so
the download path and Settings can both reach it on the default artifact, where
torch does not exist.

A directory, not a file -- which changes the whole shape
--------------------------------------------------------
#59's ``app/stt/model_spec.py`` pins **one** ``.bin`` per model size and the
student picks a size. GLiNER2 is a transformers model: ``from_pretrained``
wants a directory holding weights, a config and three tokenizer artefacts, and
there is one model rather than a size gradient. So the table is **per file**,
``is_installed`` asks about a set, and a partial download is a normal state
that has to be described rather than an error.

Only the files the loader needs, and the skip list is explicit
---------------------------------------------------------------
The repository holds **14 files, 851.0 MB**. The model needs **8 of them,
845.1 MB**. The other 5.9 MB is a banner PNG, a GitHub screenshot, a JPEG,
``README.md``, ``SKILL.md`` and ``.gitattributes`` -- repository decoration
that ``from_pretrained`` never opens.

:data:`IGNORED_FILES` names them rather than the code filtering by extension,
because the two lists together must **partition the repository listing**.
``scripts/pin_relations_model.py`` refuses to write when a file is in neither,
so a new artefact at a future revision is a decision somebody makes instead of
an omission nobody notices. Guessing "weights and json, skip images" would
silently drop a new required file the day the publisher adds one -- and the
symptom would be a model that fails to load with a message about neither the
file nor the pin.

**The download size is 845.1 MB, not 806.** Earlier #60 notes say 806 MB and
that figure is **MiB** -- 845,060,368 bytes is 805.9 MiB exactly. #59 settled
which unit a download dialog speaks (``megabytes()`` returns decimal MB,
"because that is what a download dialog should say"), so the student-facing
number is 845 MB. Stating 806 MB beside a file the operating system reports as
845 MB would read as a failed or padded download.

Where it installs -- there is no frozen-mode branch
----------------------------------------------------
``<app_data_dir>/models/gliner2/``, in development **and** in a frozen build,
with no ``sys.frozen`` test anywhere in this module. The argument is #59's and
holds unchanged: the weights are downloaded at runtime into writable
application data, which is the same place in both modes, and a frozen branch
could only point inside the bundle -- read-only on macOS and replaced wholesale
on every update. On macOS ``app_data/`` sits *beside* ``WIMI.app`` rather than
inside it, so a downloaded model survives replacing the bundle.

Under ``--test-mode`` ``app_data_dir`` is ``app_data_test/``, so a test build
downloads its own copy. That is correct and deliberate: 845 MB is a lot to
re-fetch, but a test run reading the real profile's model directory is how a
scratch run starts depending on what a human downloaded last week.

No database column records that the model is installed
-------------------------------------------------------
The files plus their digests are the record, exactly as #59's §3.7 decided.
That is only trustworthy because ``download.py`` writes ``<name>.part`` and
``os.replace()``s into position, so a half-finished file never looks installed.

The licence matters here more than it did for whisper
------------------------------------------------------
GLiNER2 is **Apache-2.0** (read from the repository's own card metadata, not
from prose) over an **MIT** DeBERTa-v3-base. Apache-2.0 §4 asks for more than
naming -- a copy of the licence, and any ``NOTICE`` file -- and **#336 is open
on precisely that**: the relations artifact adds 43 distributions and conveys
no Apache-2.0 text for any of them. The weights are a 44th component arriving
by a different route, after installation rather than in the bundle, and they
are **not** covered by anything #272 staged. Do not read these two constants as
discharging that obligation; they exist so the About panel and the student
guide have one place to read them from when #336 is settled.
"""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Optional, Tuple, Union

from .errors import RelationExtractionError, RelationExtractionErrorKind

PathLike = Union[str, os.PathLike]


# --------------------------------------------------------------------------
# Where the weights come from
# --------------------------------------------------------------------------

#: The model's Hugging Face repository. Named in ``requirements-relations.txt``
#: as the package's model; this is the weights, which the package does not ship.
MODEL_REPO = 'fastino/gliner2-base-v1'

#: The repository commit the table below was read from. Pinned to a commit
#: rather than ``main`` so a re-upload cannot change what a student downloads
#: without this file changing first. Rewritten by
#: ``scripts/pin_relations_model.py``.
MODEL_REVISION = 'f9634218e53580c56edf0de97ca1a7d3f1c2354e'

#: Read from the repository's own ``cardData.license`` (``apache-2.0``) rather
#: than from any report about it. See the module docstring on #336.
MODEL_LICENCE = 'Apache-2.0'
#: DeBERTa-v3-base, which GLiNER2 is built on, is MIT. Recorded because the
#: notices document has to name the stack rather than the top of it.
MODEL_BASE_LICENCE = 'MIT'
MODEL_LICENCE_URL = f'https://huggingface.co/{MODEL_REPO}'

_DOWNLOAD_URL_TEMPLATE = 'https://huggingface.co/{repo}/resolve/{revision}/{filename}'

#: ``app_data/models/gliner2``. ``MODELS_DIR_NAME`` matches
#: ``app/stt/model_spec.py`` on purpose: one ``models/`` directory with a
#: subdirectory per model family, so a student looking for what WIMI downloaded
#: finds both in one place.
MODELS_DIR_NAME = 'models'
RELATIONS_DIR_NAME = 'gliner2'

#: Suffix appended to a destination while a download is in flight. Never a
#: prefix and never a sibling temp name, so ``model.safetensors.part`` sorts
#: beside the file it will become and cannot be mistaken for the real thing.
PART_SUFFIX = '.part'


# --------------------------------------------------------------------------
# What is deliberately not downloaded
# --------------------------------------------------------------------------

#: Repository files the model loader never opens. Hand-written, and checked
#: against the repository listing by ``scripts/pin_relations_model.py``: a file
#: in neither this tuple nor the pin table makes that script **refuse to
#: write**, naming the file. See the module docstring for why the lists must
#: partition rather than one of them being derived.
IGNORED_FILES: Tuple[str, ...] = (
    '.gitattributes',
    'GitHub_new.jpg',
    'README.md',
    'SKILL.md',
    'image/GLiNER-2-Base-HF-Banner.png',
    'image/GitHub.png',
)


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FilePin:
    """One file the model needs: its repository path, digest and byte size.

    ``name`` is the path **within the repository and within the installed
    model directory**, so ``encoder_config/config.json`` keeps its
    subdirectory. It is always a relative POSIX path; :func:`_validate_name`
    enforces that at import time.
    """

    name: str
    sha256: str
    size_bytes: int

    @property
    def url(self) -> str:
        return download_url(self.name)

    def megabytes(self) -> float:
        """Decimal MB, because that is what a download dialog should say."""
        return self.size_bytes / 1_000_000


def _pins() -> Tuple[Tuple[str, str, int], ...]:
    """The pinned rows: ``(name, sha256, size_bytes)``.

    Everything between the two markers is **generated**. Add a row by hand with
    a 64-zero digest and a zero size, then run
    ``python scripts/pin_relations_model.py``; do not type a digest read off a
    web page or a report. #59's task T1 transcribed its own sha256 values
    truncated to 63 characters, which is the class of mistake this arrangement
    removes.
    """
    return (
        # --- BEGIN PINS (rewritten by scripts/pin_relations_model.py) ---
        ('added_tokens.json', '3c274ca559be8b7b18febf616724ec05f8a8abccd428bd2744608f45f7a0b067', 230),
        ('config.json', '33d8aa009deed4b5435d162e08b5a720b252a0084e59d30d366b37da8c0193c5', 236),
        ('encoder_config/config.json', '9840a4db70bc007e6b65d336ebe2bddc53bc2ce210dc5757e50d5bb17122f7cd', 823),
        ('special_tokens_map.json', '84ea70143f533d7e99b393d87f20010887a9ac2cba955828ef313886e4e83f4f', 2414),
        ('tokenizer_config.json', '4e6c6a8d26478b670692916266438485403b0c54af31fd1a12bab8a465d062e9', 3240),
        ('spm.model', 'c679fbf93643d19aab7ee10c0b99e460bdbc02fedf34b92b05af343b4af586fd', 2464616),
        ('tokenizer.json', '1b7fbabfb4c690bed84c6793bfecae9b8dfe205751b04f9ffd1e76a1e7df9c16', 8650701),
        ('model.safetensors', '845fc4bd93c525b86124c58ab4f56c9eacf8587953086b14c501fab25957c007', 833938108),
        # --- END PINS ---
    )


def _validate_name(name: str) -> str:
    """Refuse anything that is not a plain relative path inside the model dir.

    **The names in the pin table come from a remote listing**, which is the
    difference from ``app/stt/model_spec.py``, where each filename is one of a
    handful of constants written in the file. ``scripts/pin_relations_model.py``
    enumerates the repository and writes what it finds, so the publisher
    chooses these strings. A name like ``../../users.db`` or ``/etc/passwd``
    would otherwise be joined onto the model directory and written there by the
    downloader.

    Checked at import rather than at each use, so a bad table cannot be
    half-applied: the module fails to import, which is loud, instead of one
    file landing somewhere surprising.
    """
    if not name or name != name.strip():
        raise ValueError(f'pinned file name is blank or padded: {name!r}')
    pure = PurePosixPath(name)
    if pure.is_absolute() or '\\' in name:
        raise ValueError(f'pinned file name must be relative and POSIX: {name!r}')
    if any(part in ('..', '.', '') for part in pure.parts):
        raise ValueError(f'pinned file name must not traverse: {name!r}')
    # Canonical form, and this is a second reason rather than tidiness.
    # ``scripts/pin_relations_model.py`` decides that the table and
    # IGNORED_FILES partition the repository listing by comparing these
    # strings for EQUALITY against the names the API returns. A name that
    # means the right file but spells it differently -- ``./config.json``,
    # ``a//b`` -- would match nothing, be reported as unclassified, and the
    # partition check that exists to catch a new required file would instead
    # be arguing with itself about an existing one.
    if pure.as_posix() != name:
        raise ValueError(
            f'pinned file name must be in canonical form ({pure.as_posix()!r}, '
            f'not {name!r}); the pinning script compares these to the '
            f'repository listing by string equality'
        )
    return name


MODEL_FILES: Dict[str, FilePin] = {
    _validate_name(name): FilePin(name=name, sha256=sha256, size_bytes=size_bytes)
    for name, sha256, size_bytes in _pins()
}

#: Download and verification order: **ascending by size**, so a failure on 236
#: bytes of config surfaces in milliseconds rather than after 834 MB of
#: weights. ``scripts/pin_relations_model.py`` sorts the table when it writes,
#: so this is a property the generator guarantees rather than one a hand edit
#: has to remember -- and ``test_the_weights_dominate_so_order_matters`` is
#: what notices if that stops being true.
MODEL_FILE_NAMES: Tuple[str, ...] = tuple(MODEL_FILES)

#: Total bytes a first use must fetch. 845,060,368 -- see the docstring on why
#: that is 845 MB rather than the 806 earlier notes quote.
TOTAL_BYTES: int = sum(pin.size_bytes for pin in MODEL_FILES.values())


def total_megabytes() -> float:
    """Decimal MB for the whole download, for first-use copy."""
    return TOTAL_BYTES / 1_000_000


def get_pin(name: str) -> FilePin:
    """The pin for one file. Raises :class:`KeyError` on an unpinned name."""
    try:
        return MODEL_FILES[name]
    except KeyError:
        raise KeyError(
            f'{name!r} is not a pinned GLiNER2 file; pinned files are '
            f'{", ".join(MODEL_FILE_NAMES)}'
        ) from None


def download_url(name: str) -> str:
    """The pinned URL for one file, at the pinned revision."""
    return _DOWNLOAD_URL_TEMPLATE.format(
        repo=MODEL_REPO, revision=MODEL_REVISION, filename=get_pin(name).name
    )


# --------------------------------------------------------------------------
# Where it lands
# --------------------------------------------------------------------------


def model_dir(app_data_dir: PathLike, *, create: bool = True) -> Path:
    """``<app_data_dir>/models/gliner2``, created by default.

    Pass ``create=False`` where the answer is wanted without a side effect --
    a Settings line reporting a path, or a test asserting the layout.
    """
    path = Path(app_data_dir) / MODELS_DIR_NAME / RELATIONS_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def file_path(app_data_dir: PathLike, name: str, *, create: bool = True) -> Path:
    """Where one pinned file installs, subdirectory included.

    ``create`` makes the file's **parent** -- which is not always the model
    directory, because ``encoder_config/config.json`` has one of its own.
    """
    pin = get_pin(name)
    base = model_dir(app_data_dir, create=create)
    target = base / PurePosixPath(pin.name)
    if create:
        target.parent.mkdir(parents=True, exist_ok=True)
    return target


def part_path(destination: PathLike) -> Path:
    """The in-flight name for a destination: ``model.safetensors.part``."""
    path = Path(destination)
    return path.with_name(path.name + PART_SUFFIX)


def missing_files(app_data_dir: PathLike) -> Tuple[str, ...]:
    """Pinned files that are absent or the wrong byte size, in download order.

    Cheap -- a ``stat`` each, no hashing. This is what the downloader asks to
    decide what to fetch and what a page asks before offering a download, so
    hashing 845 MB to render a button would be #147's mistake (a status check
    doing real work) in another costume.

    Returning the *set* rather than a boolean is what makes a resumed or
    partial download describable: six files present and the weights absent is
    the ordinary state after a cancel, and it is neither installed nor empty.
    """
    base = model_dir(app_data_dir, create=False)
    missing = []
    for name in MODEL_FILE_NAMES:
        pin = MODEL_FILES[name]
        try:
            if (base / PurePosixPath(name)).stat().st_size != pin.size_bytes:
                missing.append(name)
        except OSError:
            missing.append(name)
    return tuple(missing)


def is_installed(app_data_dir: PathLike) -> bool:
    """Cheap: every pinned file is present at its pinned byte size.

    Call :func:`verify_dir` before building a model; this one only decides
    whether to offer a download.
    """
    return not missing_files(app_data_dir)


def bytes_still_needed(app_data_dir: PathLike) -> int:
    """How much of the download is left, for a resumed first use.

    Counts a wrong-sized file in full, because that file will be refetched in
    full -- :mod:`download` does not range-resume, it replaces.
    """
    return sum(MODEL_FILES[name].size_bytes for name in missing_files(app_data_dir))


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

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
    """Hex digest of a file, read in chunks so 834 MB does not sit in RAM.

    ``cancel`` is honoured between chunks. Hashing these weights is seconds of
    work, and a cancel that applied only to the network half would look like
    the button had stopped responding.
    """
    digest = hashlib.sha256()
    read = 0
    try:
        total: Optional[int] = os.path.getsize(path)
    except OSError:
        total = None
    with open(path, 'rb') as handle:
        while True:
            if cancel is not None and cancel.is_set():
                raise RelationExtractionError(
                    RelationExtractionErrorKind.DOWNLOAD_CANCELLED,
                    'cancelled while verifying the model',
                )
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
    pin: FilePin,
    *,
    cancel: Optional[threading.Event] = None,
    progress: Optional[Callable[[int, Optional[int]], None]] = None,
) -> None:
    """Raise unless the file on disk *is* the pinned one.

    Byte size first, because it is a ``stat`` and catches the common failure --
    a truncated or range-confused download -- without reading 834 MB; then the
    digest, which is the one that actually decides.

    ``progress`` is handed straight to :func:`sha256_file` and reports bytes
    hashed **of this file**. :func:`verify_dir` wraps it to report across the
    whole set.
    """
    file_target = Path(path)
    try:
        actual_size = file_target.stat().st_size
    except OSError as exc:
        raise RelationExtractionError(
            RelationExtractionErrorKind.MODEL_MISSING,
            f'{pin.name} is not where the pin says it should be',
            detail=f'{file_target}: {exc}',
        ) from exc

    if actual_size != pin.size_bytes:
        raise RelationExtractionError(
            RelationExtractionErrorKind.MODEL_CORRUPT,
            f'{pin.name} is {actual_size} bytes, pinned at {pin.size_bytes}',
        )

    actual_sha = sha256_file(file_target, cancel=cancel, progress=progress)
    if actual_sha != pin.sha256:
        raise RelationExtractionError(
            RelationExtractionErrorKind.MODEL_CORRUPT,
            f'{pin.name} does not match its pin',
            detail=f'sha256 {actual_sha} != {pin.sha256}',
        )


def verify_dir(
    app_data_dir: PathLike,
    *,
    cancel: Optional[threading.Event] = None,
    progress: Optional[Callable[[int, Optional[int]], None]] = None,
) -> None:
    """Hash every pinned file. The honest check, run before building a model.

    Smallest first, so a corrupt config is reported in milliseconds rather
    than after hashing the weights. ``progress`` is called with bytes hashed
    **across the whole set**, not per file, because that is what a progress bar
    wants; a caller needing per-file detail should loop :func:`verify_file`.
    """
    base = model_dir(app_data_dir, create=False)
    done = 0
    for name in MODEL_FILE_NAMES:
        pin = MODEL_FILES[name]
        relay = None
        if progress is not None:
            # Default argument, not a closure over ``done``: the loop rebinds
            # it, so a late-called relay would report the wrong offset.
            def relay(read: int, _total: Optional[int], _offset: int = done) -> None:
                progress(_offset + read, TOTAL_BYTES)

        verify_file(base / PurePosixPath(name), pin, cancel=cancel, progress=relay)
        done += pin.size_bytes
