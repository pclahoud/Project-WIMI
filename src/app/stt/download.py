"""First-run acquisition of the whisper weights: download, resume, verify, install.

Owner's decision D2 (plan §0, §3.8): the binary ships in the build, the weights
download on first use. This module is the whole of that -- and it runs on the
worker, so it touches **no Qt object and no database connection** (§3.4). Its
only inputs are a spec from ``model_spec.py``, a path, and two plain callables;
its only outputs are a file and an exception.

The discipline, and why every line of it is load-bearing
--------------------------------------------------------

R15 is the risk this module exists to close: *a corrupt download presents as a
working install*. §3.7 keeps **no database column** saying a model is
installed, because a flag would disagree with the filesystem in exactly the
case that matters. The filesystem can only be the record if nothing that is not
a verified model is ever named like one. So:

1. bytes land in ``<name>.bin.part``, never in ``<name>.bin``;
2. the completed ``.part`` is checked against **both** the pinned byte size and
   the pinned sha256 -- size first because it is a ``stat``, digest because it
   is the one that decides;
3. only then ``os.replace()``, which is atomic on POSIX and on Windows.

A crash at any point leaves a ``.part``: resumable, and never mistakable for a
model.

Resume, and the trap inside it
------------------------------

An existing ``.part`` is resumed with an HTTP ``Range`` request. A server is
free to ignore that header and send the whole body with ``200``; appending that
to what we already had would produce a file of the right *shape* and entirely
wrong *content*. So the response is inspected rather than assumed -- ``206``
plus a ``Content-Range`` whose first byte is the offset we asked for, or we
truncate and start again -- and the digest check runs on the resume path
exactly as it does on the fresh one. Verified against the real host: Hugging
Face answers ``206`` with a correct ``Content-Range`` through its CDN redirect,
and a resumed download of ``ggml-tiny-q5_1.bin`` matched the pin.

Which error kind a failed verification raises
---------------------------------------------

``DOWNLOAD_FAILED``, not ``MODEL_CORRUPT``. The two differ by what the student
can usefully do: ``DOWNLOAD_FAILED`` is in ``errors.RETRYABLE`` and a retry is
honest, because a truncated or garbled transfer very often succeeds the second
time. ``MODEL_CORRUPT`` is for ``runtime.py``'s load-time check (T6), where a
file that is already installed and does not match the pin is a different
conversation. The ``detail`` string names the digest mismatch either way, so
nothing is hidden by the choice.

What is deliberately *not* here
-------------------------------

* **No retry loop.** One attempt; the UI offers retry, and resume makes a retry
  cheap. A loop here would multiply a slow failure by three before the student
  sees anything.
* **No percentage.** Progress is ``(bytes_so_far, total_or_None)`` and the UI
  decides how to render it. ``total`` really can be ``None`` -- a response
  without ``Content-Length`` is legal -- and a caller that treats it as a
  number will divide by it.
* **No substituted total.** When the host sends no ``Content-Length`` we report
  ``None`` rather than quietly passing off ``spec.size_bytes`` as the server's
  answer. The caller has the spec and may draw a determinate bar from it if it
  likes; that is a UI choice, and inventing it here would leave the
  indeterminate path untested until a student met it.
"""

from __future__ import annotations

import http.client
import logging
import os
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional, Union

from .errors import SttError, SttErrorKind
from .model_spec import (
    CHUNK_BYTES,
    ModelSpec,
    PathLike,
    get_spec,
    model_path,
    part_path,
    sha256_file,
)

logger = logging.getLogger(__name__)

#: ``(bytes_so_far, total_bytes_or_None)``. Never a percentage.
ProgressCallback = Callable[[int, Optional[int]], None]

#: Per-socket-operation, not per-download: a 487 MB model over a slow line must
#: not be killed for being large, but a connection that has gone quiet must not
#: hold the single worker forever.
DEFAULT_TIMEOUT_S = 60.0

USER_AGENT = 'WIMI-stt/1.0'

_CONTENT_RANGE = re.compile(r'bytes\s+(\d+)-(\d+)/(\d+|\*)', re.IGNORECASE)


# --------------------------------------------------------------------------
# public
# --------------------------------------------------------------------------


def download_model(
    app_data_dir: PathLike,
    size: Optional[str] = None,
    *,
    progress: Optional[ProgressCallback] = None,
    cancel: Optional[threading.Event] = None,
    url: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    chunk_bytes: int = CHUNK_BYTES,
) -> Path:
    """Put the pinned model for ``size`` into ``app_data/models/whisper``.

    Returns the installed path. Already installed and verifying means no
    network at all; already installed and *not* verifying means the file is
    deleted and fetched again (R15: a model that fails verification is deleted
    and re-offered, not patched around).

    Raises ``SttError`` with ``DOWNLOAD_CANCELLED`` or ``DOWNLOAD_FAILED``.
    """
    spec = get_spec(size)
    destination = model_path(app_data_dir, spec.size)
    return download_spec(
        spec,
        destination,
        progress=progress,
        cancel=cancel,
        url=url,
        timeout=timeout,
        chunk_bytes=chunk_bytes,
    )


def download_spec(
    spec: ModelSpec,
    destination: PathLike,
    *,
    progress: Optional[ProgressCallback] = None,
    cancel: Optional[threading.Event] = None,
    url: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    chunk_bytes: int = CHUNK_BYTES,
) -> Path:
    """The core: fetch ``spec`` to ``destination``, atomically and verified.

    ``url`` overrides the pinned URL (tests point it at a fixture server).
    Everything else is described in the module docstring.
    """
    destination = Path(destination)
    part = part_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if _existing_install_is_good(destination, spec, cancel):
        logger.debug('whisper model %s already installed at %s', spec.size, destination)
        return destination

    _raise_if_cancelled(cancel, part)

    # A .part the same size as the pin is a download that finished and then
    # lost the race to be renamed -- a crash, a power cut. Worth a hash before
    # worth a re-transfer.
    salvaged = _salvage_complete_part(part, destination, spec, cancel)
    if salvaged is not None:
        return salvaged

    resume_from = _resume_offset(part, spec)
    source = url or spec.url

    try:
        response = _open(source, resume_from, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and resume_from:
            # The .part is at or past the end of what the server will serve.
            # Nothing to salvage -- it was not this file.
            _unlink(part)
            response = _open_or_fail(source, 0, timeout)
            resume_from = 0
        else:
            raise SttError(
                SttErrorKind.DOWNLOAD_FAILED,
                f'HTTP {exc.code} for {source}',
            ) from exc
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        raise SttError(SttErrorKind.DOWNLOAD_FAILED, f'{source}: {exc}') from exc

    with response:
        appending, total = _interpret(response, resume_from)
        if resume_from and not appending:
            # The trap in the module docstring. Loud, because a silently
            # ignored Range is how a resumed download becomes garbage.
            logger.warning(
                'server ignored Range for %s (HTTP %s); restarting from zero',
                source,
                getattr(response, 'status', None),
            )
        downloaded = resume_from if appending else 0
        _emit(progress, downloaded, total)

        try:
            with open(part, 'ab' if appending else 'wb') as handle:
                while True:
                    if cancel is not None and cancel.is_set():
                        # Close before unlinking: Windows refuses to delete a
                        # file anything still holds open, and a cancel that
                        # left the .part behind on Windows only would be the
                        # worst possible way to find that out.
                        handle.close()
                        _unlink(part)
                        raise SttError(
                            SttErrorKind.DOWNLOAD_CANCELLED,
                            f'cancelled after {downloaded} bytes',
                        )
                    block = response.read(chunk_bytes)
                    if not block:
                        break
                    handle.write(block)
                    downloaded += len(block)
                    _emit(progress, downloaded, total)
                handle.flush()
                os.fsync(handle.fileno())
        except SttError:
            raise
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            # The .part survives a transport failure on purpose: it is the
            # thing a retry resumes from, and it can never be mistaken for an
            # installed model.
            raise SttError(
                SttErrorKind.DOWNLOAD_FAILED,
                f'{source}: {exc} (after {downloaded} bytes)',
            ) from exc

    _verify_part_or_discard(part, spec, cancel)
    os.replace(part, destination)
    _fsync_dir(destination.parent)
    logger.info('installed whisper model %s (%d bytes)', spec.size, spec.size_bytes)
    return destination


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------


def _open(source: str, resume_from: int, timeout: float):
    request = urllib.request.Request(source, headers={'User-Agent': USER_AGENT})
    if resume_from:
        request.add_header('Range', f'bytes={resume_from}-')
    # urllib carries non-content headers across a redirect, so ``Range``
    # survives Hugging Face's hop to its CDN -- measured, not assumed.
    return urllib.request.urlopen(request, timeout=timeout)


def _open_or_fail(source: str, resume_from: int, timeout: float):
    try:
        return _open(source, resume_from, timeout)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        raise SttError(SttErrorKind.DOWNLOAD_FAILED, f'{source}: {exc}') from exc


def _interpret(response, resume_from: int):
    """Decide append-vs-restart, and what ``total`` to report.

    A resume is honoured only when the server says ``206`` *and* names our
    offset in ``Content-Range``. Anything else -- ``200``, a missing header, a
    range starting somewhere else -- restarts from zero.
    """
    status = getattr(response, 'status', None) or response.getcode()
    content_length = _int_or_none(response.headers.get('Content-Length'))
    match = _CONTENT_RANGE.search(response.headers.get('Content-Range') or '')

    appending = False
    total: Optional[int] = content_length
    if resume_from and status == 206 and match and int(match.group(1)) == resume_from:
        appending = True
        full = match.group(3)
        if full != '*':
            total = int(full)
        elif content_length is not None:
            total = resume_from + content_length
        else:
            total = None
    return appending, total


def _resume_offset(part: Path, spec: ModelSpec) -> int:
    """How many bytes of ``part`` are worth keeping."""
    try:
        have = part.stat().st_size
    except OSError:
        return 0
    if have <= 0:
        return 0
    if spec.size_bytes and have >= spec.size_bytes:
        # Longer than the pinned model, so it is not a prefix of it.
        _unlink(part)
        return 0
    return have


def _salvage_complete_part(
    part: Path, destination: Path, spec: ModelSpec, cancel: Optional[threading.Event]
) -> Optional[Path]:
    try:
        have = part.stat().st_size
    except OSError:
        return None
    if not spec.size_bytes or have != spec.size_bytes:
        return None
    try:
        digest = sha256_file(part, cancel=cancel)
    except SttError:
        # Cancelled while hashing. One rule, everywhere: after a cancel there
        # is no .part, so nothing has to reason about which cancel it was.
        _unlink(part)
        raise
    if digest != spec.sha256:
        _unlink(part)
        return None
    os.replace(part, destination)
    _fsync_dir(destination.parent)
    logger.info('salvaged a completed .part for whisper model %s', spec.size)
    return destination


def _existing_install_is_good(
    destination: Path, spec: ModelSpec, cancel: Optional[threading.Event]
) -> bool:
    try:
        have = destination.stat().st_size
    except OSError:
        return False
    if have == spec.size_bytes and sha256_file(destination, cancel=cancel) == spec.sha256:
        return True
    logger.warning(
        'existing %s does not match the pin (%d bytes); re-downloading',
        destination.name,
        have,
    )
    _unlink(destination)
    return False


def _verify_part_or_discard(
    part: Path, spec: ModelSpec, cancel: Optional[threading.Event]
) -> None:
    try:
        actual_size = part.stat().st_size
    except OSError as exc:
        raise SttError(SttErrorKind.DOWNLOAD_FAILED, f'{part.name} vanished: {exc}') from exc

    if actual_size != spec.size_bytes:
        _unlink(part)
        raise SttError(
            SttErrorKind.DOWNLOAD_FAILED,
            f'{spec.filename}: got {actual_size} bytes, pinned at {spec.size_bytes}',
        )

    try:
        actual_sha = sha256_file(part, cancel=cancel)
    except SttError:
        _unlink(part)
        raise

    if actual_sha != spec.sha256:
        # Nothing here is salvageable and resuming from it would only produce
        # the same wrong file more slowly.
        _unlink(part)
        raise SttError(
            SttErrorKind.DOWNLOAD_FAILED,
            f'{spec.filename}: sha256 {actual_sha} does not match pin {spec.sha256}',
        )


def _raise_if_cancelled(cancel: Optional[threading.Event], part: Path) -> None:
    if cancel is not None and cancel.is_set():
        _unlink(part)
        raise SttError(SttErrorKind.DOWNLOAD_CANCELLED, 'cancelled before starting')


def _emit(progress: Optional[ProgressCallback], done: int, total: Optional[int]) -> None:
    if progress is None:
        return
    # A progress callback that raises must not be the reason a download fails;
    # it is a UI notification, and the bytes are already on disk.
    try:
        progress(done, total)
    except Exception:  # noqa: BLE001 - deliberately swallowed, see above
        logger.exception('whisper download progress callback raised')


def _unlink(path: Union[str, Path]) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _fsync_dir(directory: Path) -> None:
    """Best effort. A directory cannot be opened for fsync on Windows, and a
    failure here is never a reason to fail an install that has landed."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _int_or_none(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
