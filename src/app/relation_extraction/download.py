"""First-use acquisition of the GLiNER2 weights: download, resume, verify, install.

Owner's decision, 2026-10-04: the relations artifact ships the runtime and the
**weights download on first use**, as #59's D2 does for whisper. This module is
the whole of that, and it runs on the worker, so it touches **no Qt object and
no database connection**. Its inputs are the pin table, a directory and two
plain callables; its outputs are files and an exception.

Eight files, not one -- which changes nearly every decision
------------------------------------------------------------
``app/stt/download.py`` fetches one ``.bin``. GLiNER2 is a transformers
directory of eight pinned files totalling 845.1 MB, 833.9 MB of it
``model.safetensors``. So:

* **Each file is installed atomically on its own**, not the set. A cancel or a
  crash therefore leaves a *partial but honest* directory, and
  ``model_spec.missing_files()`` describes exactly what is still wanted. There
  is no "installing" marker anywhere, for #59 §3.7's reason: a flag would
  disagree with the filesystem in precisely the case that matters.
* **Smallest first**, which the pin table guarantees. A 236-byte config whose
  digest is wrong then fails in milliseconds instead of after 834 MB. This is
  the whole reason ``scripts/pin_relations_model.py`` sorts the table rather
  than leaving the order to whoever edits it.
* **A file already present and the right size is skipped**, so a resumed first
  use costs only what is left. That check is a ``stat``, never a hash -- see
  ``missing_files``.

The discipline, unchanged from #59 because it is what makes the filesystem
trustworthy
-----------------------------------------------------------------------------
1. bytes land in ``<name>.part``, never in ``<name>``;
2. the completed ``.part`` is checked against **both** the pinned byte size and
   the pinned sha256 -- size first because it is a ``stat``, digest because it
   is the one that decides;
3. only then ``os.replace()``, which is atomic on POSIX and on Windows.

A crash at any point leaves a ``.part``: resumable, and never mistakable for
part of a model.

Resume, and the trap inside it
------------------------------
An existing ``.part`` is resumed with an HTTP ``Range`` request. A server may
ignore that header and send the whole body with ``200``; appending that to what
we already hold would produce a file of the right *shape* and entirely wrong
*content*. So the response is inspected rather than assumed -- ``206`` plus a
``Content-Range`` whose first byte is the offset asked for, or the ``.part`` is
truncated and started again -- and the digest check runs on the resume path
exactly as on the fresh one.

Progress is determinate here, and that is NOT a departure from #59
-------------------------------------------------------------------
``app/stt/download.py`` refuses to substitute the pinned size for a missing
``Content-Length``, because for one file the question *"how big did the server
say this is"* has an answer that may be absent, and inventing it would leave
the indeterminate path untested.

This module reports ``(done, total)`` where ``total`` comes from the **pin
table** and is always a number. That is a different question, legitimately
answered: we are fetching a *known set of known sizes*, every file whose size
disagrees with its pin is rejected anyway, and a per-file ``Content-Length`` we
never trusted would not improve the set total. A caller still gets honest
per-file granularity through ``on_file``.

What is deliberately not here
-----------------------------
* **No retry loop.** One attempt per call; the UI offers retry, and resume
  makes a retry cheap. A loop here would multiply a slow failure before the
  student saw anything.
* **No Hub client.** Plain ``urllib`` against the pinned
  ``resolve/<revision>/<file>`` URLs. ``huggingface_hub`` would resolve
  ``main`` for some reads -- which is the trap #60 recorded when GLiNER2's own
  tokenizer load reached past a pinned revision -- and would add a dependency
  to a path that needs none.
* **No model load.** Proving the weights work means loading them, which costs
  seconds and gigabytes and belongs in ``runtime.py``. A verified digest is
  where this module's responsibility ends.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Tuple, Union

from . import model_spec
from .errors import RelationExtractionError, RelationExtractionErrorKind

logger = logging.getLogger(__name__)

PathLike = Union[str, os.PathLike]

#: Bytes per read. 1 MiB keeps the transfer I/O bound and a cancel felt within
#: a few milliseconds of the request.
CHUNK_BYTES = 1 << 20

#: Socket timeout per read. Long enough for a slow link to deliver a chunk,
#: short enough that a dead connection does not hold the worker for minutes.
TIMEOUT_S = 60

USER_AGENT = 'WIMI-relations/1.0'

_CONTENT_RANGE_RE = re.compile(r'bytes\s+(\d+)-')

#: ``(bytes_done_across_the_set, bytes_total_for_the_set)``. Both from the pin
#: table, so both are always numbers -- see the module docstring on why that
#: differs from #59's single-file case rather than contradicting it.
ProgressFn = Callable[[int, int], None]

#: ``(name, index_from_1, count)`` as each file starts. Lets a UI say which of
#: eight it is on without parsing the progress numbers.
FileFn = Callable[[str, int, int], None]


@dataclass(frozen=True)
class InstallResult:
    """What the call did, in enough detail for a log and a status line.

    Deliberately carries no ``complete`` flag. The call either returns -- in
    which case ``missing_files()`` was re-checked and empty -- or raises. A
    property that can only be ``True`` is a field nobody can act on, and it
    would invite a caller to branch on it instead of handling the exception.
    """

    #: Files written during this call, in the order they were installed.
    installed: Tuple[str, ...] = ()
    #: Files already present at the pinned size, so not fetched.
    skipped: Tuple[str, ...] = ()
    #: Bytes actually transferred, which excludes skipped files and the prefix
    #: a resume did not have to re-fetch.
    bytes_downloaded: int = 0

    def describe(self) -> str:
        return (f'{len(self.installed)} installed, {len(self.skipped)} already '
                f'present, {self.bytes_downloaded:,} bytes transferred')


def _check_cancelled(cancel: Optional[threading.Event], what: str) -> None:
    if cancel is not None and cancel.is_set():
        raise RelationExtractionError(
            RelationExtractionErrorKind.DOWNLOAD_CANCELLED,
            'the model download was cancelled',
            detail=what,
        )


def _open(url: str, offset: int):
    """GET ``url``, asking to resume from ``offset`` when that is non-zero."""
    headers = {'User-Agent': USER_AGENT}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    request = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(request, timeout=TIMEOUT_S)


def _resume_offset(response, wanted: int, part: Path) -> int:
    """How many bytes of ``part`` to keep, given what the server actually sent.

    The trap this closes: a server may ignore ``Range`` and answer ``200`` with
    the whole body. Appending that to an existing ``.part`` yields a file of the
    right size and wrong content, which the digest would catch -- after the
    whole transfer. Checking the status and the ``Content-Range`` instead
    throws away the stale prefix *before* spending the bandwidth.
    """
    if not wanted:
        return 0
    if getattr(response, 'status', None) != 206:
        logger.info(
            'relations download: resume refused for %s (status %s); '
            'restarting the file', part.name, getattr(response, 'status', '?'))
        return 0
    match = _CONTENT_RANGE_RE.search(response.headers.get('Content-Range', ''))
    if not match or int(match.group(1)) != wanted:
        logger.info(
            'relations download: Content-Range %r does not start at %d for '
            '%s; restarting the file',
            response.headers.get('Content-Range'), wanted, part.name)
        return 0
    return wanted


def _fetch_one(
    pin: model_spec.FilePin,
    destination: Path,
    *,
    cancel: Optional[threading.Event],
    on_bytes: Callable[[int], None],
    on_resume: Callable[[int], None],
) -> int:
    """Download one pinned file into place. Returns bytes transferred.

    ``on_resume`` is called once with the number of bytes a resume kept, after
    the ``Range`` negotiation settles and before any new byte arrives. The
    caller needs it to keep a progress bar honest: those bytes are on disk and
    count toward the set, but they are never passed to ``on_bytes``, which only
    reports what this call transferred. Without it a resumed
    ``model.safetensors`` would leave the bar short by the resumed prefix for
    the whole 834 MB -- and reaching 100% only because the final callback says
    so is the kind of number this project does not ship.

    Raises ``DOWNLOAD_FAILED`` on a transport error or a digest mismatch, and
    ``DOWNLOAD_CANCELLED`` if ``cancel`` is set. Leaves a ``.part`` behind on
    either, which the next call resumes.
    """
    part = model_spec.part_path(destination)
    have = part.stat().st_size if part.exists() else 0
    if have > pin.size_bytes:
        # A .part larger than the pin cannot be a prefix of it.
        logger.info('relations download: %s.part is oversized; discarding',
                    pin.name)
        part.unlink()
        have = 0

    transferred = 0
    try:
        with _open(pin.url, have) as response:
            keep = _resume_offset(response, have, part)
            on_resume(keep)
            # 'wb' truncates on open, which is what a refused resume needs;
            # 'ab' appends to the prefix the server agreed to continue from.
            with open(part, 'ab' if keep else 'wb') as handle:
                while True:
                    _check_cancelled(cancel, pin.name)
                    block = response.read(CHUNK_BYTES)
                    if not block:
                        break
                    handle.write(block)
                    transferred += len(block)
                    on_bytes(len(block))
    except RelationExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - every transport failure is one kind
        raise RelationExtractionError(
            RelationExtractionErrorKind.DOWNLOAD_FAILED,
            f'could not download {pin.name}',
            detail=f'{type(exc).__name__}: {exc}',
        ) from exc

    # Verify BEFORE the file is given its real name. A .part that fails here is
    # left in place: the next attempt resumes or restarts it, and nothing in
    # the directory ever looks like a model it is not.
    try:
        model_spec.verify_file(part, pin, cancel=cancel)
    except RelationExtractionError as exc:
        if exc.kind is RelationExtractionErrorKind.DOWNLOAD_CANCELLED:
            raise
        # MODEL_CORRUPT from the verifier becomes DOWNLOAD_FAILED here, and the
        # difference is what the student can do about it: a failed transfer is
        # in RETRYABLE and very often succeeds second time, while
        # MODEL_CORRUPT is runtime.py's verdict on a file that is already
        # installed -- a different conversation. The detail keeps the digest.
        raise RelationExtractionError(
            RelationExtractionErrorKind.DOWNLOAD_FAILED,
            f'{pin.name} did not match its pin after downloading',
            detail=exc.detail or exc.message,
        ) from exc

    os.replace(part, destination)
    return transferred


def install_model(
    app_data_dir: PathLike,
    *,
    cancel: Optional[threading.Event] = None,
    progress: Optional[ProgressFn] = None,
    on_file: Optional[FileFn] = None,
) -> InstallResult:
    """Make ``<app_data_dir>/models/gliner2/`` hold the pinned model.

    Idempotent and resumable: files already present at the pinned size are
    skipped, a partial ``.part`` is resumed, and a cancel leaves a directory
    that ``model_spec.missing_files()`` describes correctly.

    Runs on a worker thread. Touches no Qt object and no database connection.
    """
    base = model_spec.model_dir(app_data_dir, create=True)
    wanted = model_spec.missing_files(app_data_dir)
    total = model_spec.TOTAL_BYTES

    # Already-present files count toward progress from the first callback, so a
    # resumed download does not start a bar at zero and crawl to a hundred.
    done = total - model_spec.bytes_still_needed(app_data_dir)
    if progress is not None:
        progress(done, total)

    if not wanted:
        logger.info('relations model: already installed at %s', base)
        return InstallResult(skipped=model_spec.MODEL_FILE_NAMES)

    logger.info('relations model: fetching %d of %d files (%.1f MB) into %s',
                len(wanted), len(model_spec.MODEL_FILE_NAMES),
                model_spec.bytes_still_needed(app_data_dir) / 1_000_000, base)

    installed = []
    skipped = [n for n in model_spec.MODEL_FILE_NAMES if n not in wanted]
    transferred = 0

    for index, name in enumerate(wanted, start=1):
        _check_cancelled(cancel, name)
        pin = model_spec.MODEL_FILES[name]
        if on_file is not None:
            on_file(name, index, len(wanted))

        def advance(count: int) -> None:
            nonlocal done
            done += count
            if progress is not None:
                progress(min(done, total), total)

        destination = model_spec.file_path(app_data_dir, name, create=True)
        transferred += _fetch_one(
            pin, destination, cancel=cancel,
            on_bytes=advance, on_resume=advance)
        installed.append(name)
        logger.info('relations model: installed %s (%d/%d)',
                    name, index, len(wanted))

    # Re-derived rather than assumed. If this disagrees with the loop, the pin
    # table and the filesystem disagree, and the caller must not be told the
    # model is ready.
    still_missing = model_spec.missing_files(app_data_dir)
    if still_missing:
        raise RelationExtractionError(
            RelationExtractionErrorKind.DOWNLOAD_FAILED,
            'the model is still incomplete after installing',
            detail=f'missing: {", ".join(still_missing)}',
        )

    if progress is not None:
        progress(total, total)
    return InstallResult(
        installed=tuple(installed),
        skipped=tuple(skipped),
        bytes_downloaded=transferred,
    )


def discard_partials(app_data_dir: PathLike) -> tuple:
    """Delete any ``.part`` files. Returns the names removed.

    For a student who wants to start the download over rather than resume it --
    a stalled transfer from a bad link, say. Deliberately does **not** touch
    installed files: those are verified, and deleting them is uninstalling,
    which is a different action with a different button.
    """
    base = model_spec.model_dir(app_data_dir, create=False)
    removed = []
    for name in model_spec.MODEL_FILE_NAMES:
        part = model_spec.part_path(base / PurePosixPath(name))
        try:
            if part.exists():
                part.unlink()
                removed.append(name)
        except OSError as exc:
            logger.warning('relations model: could not remove %s (%s)',
                           part, exc)
    return tuple(removed)
