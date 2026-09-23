"""
The hydration layer — reading files that may not be locally present.

This is the whole risk of folder sync, and it is worse on Box than on any other
provider. Box Drive keeps every file online-only by default, and evicts a cached
file "when the file cache has not been modified for the past 30 days". Our
generation files are written once and **never modified again**, which starts that
clock immediately and also puts them first in line when the cache fills ("those
cached files that have gone the longest without being modified").

So on Box, **hydration is the normal path, not the exceptional one** — a profile
pushed in March and pulled in May will be evicted on both machines. See #123
comment #1503 §2.

Two rules, and neither is optional:

1.  **Never trust ``st_size`` as proof a file is present.** An evicted file
    reports its full logical size on every platform. Use :func:`is_dataless`.
2.  **Never call anything here on the Qt main thread.** A read that triggers
    materialisation crosses the network; Apple documents watchdog kills for
    exactly this (TN3150). Every function here is bounded and blocking, and is
    meant to be called from a worker.
"""
from __future__ import annotations

import hashlib
import os
import queue
import stat
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: macOS: the file exists with its real size but its data is not local.
#: This is the correct modern test. The ``.icloud`` sidecar check is WRONG on
#: current macOS -- those placeholder files no longer exist.
SF_DATALESS = 0x40000000

#: Windows. Two different mechanisms, and we mask for both because **Box Drive
#: uses both** -- one or the other, and a machine can change between them with
#: no update.
#:
#: ``RECALL_ON_OPEN`` / ``RECALL_ON_DATA_ACCESS`` are Cloud Files API
#: placeholders -- what OneDrive sets. ``OFFLINE`` is the old HSM flag,
#: predating CF by decades.
#:
#: What was measured, on the same machine and the same Box Drive (2.53.223),
#: twelve hours apart (#123 comments #1880 and #1951):
#:
#: * **Overnight 2026-09-21/22 ("Streem" mode).** ``SyncRootManager`` had no
#:   children; ``C:\Users\<u>\Box`` was a mount-point junction (``0xA0000003``)
#:   onto a virtual volume reporting FAT32. A not-locally-present file was
#:   ``0x3000``: OFFLINE + NOT_CONTENT_INDEXED, and **no RECALL flag**. #1503
#:   had inferred Cloud Files from Box shipping ``FS\cf\cfctl.exe``; for this
#:   mode that inference was wrong.
#: * **Morning 2026-09-22, after a Box restart ("cloud_files" mode).** One
#:   ``SyncRootManager`` entry; the Box folder a Cloud Files root (tag
#:   ``0x9000701A``). A not-locally-present file was ``0x400020``:
#:   RECALL_ON_DATA_ACCESS + ARCHIVE, and **no OFFLINE**.
#:
#: What makes Box pick one is not known. So each mode sets exactly one of the
#: flags the other does not, and a mask narrowed to either would report every
#: evicted file in the other mode as resident: ``determinate: True`` and
#: **wrong**, which is worse than admitting we cannot tell. OFFLINE was in
#: this mask as defensive breadth before either mode was measured -- the only
#: reason detection survived the first mode being the unexpected one.
#: Do not narrow this mask.
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000

#: Default ceiling for a single bounded read. Generous: a 0.28 MB archive over a
#: cold cloud link is fast, but the first byte can be slow while a client wakes.
DEFAULT_TIMEOUT_S = 30.0

_CHUNK = 1024 * 1024


class HydrationTimeout(TimeoutError):
    """A read did not finish inside its budget. The file may still be downloading."""


class HydrationError(OSError):
    """A file could not be materialised at all."""


@dataclass(frozen=True)
class Residency:
    """What we can tell about whether a file's bytes are actually here."""
    path: str
    exists: bool
    size_bytes: int
    dataless: bool
    #: True when the platform gave us a real answer; False when we are guessing.
    determinate: bool

    @property
    def needs_hydration(self) -> bool:
        return self.exists and self.dataless


def residency(path: str | Path) -> Residency:
    """
    Inspect a file without reading it — and so without triggering a download.

    ``determinate`` is False on platforms where we have no eviction flag to read
    (Linux, and any Windows Python without ``st_file_attributes``). A False there
    means "we cannot tell", not "the file is local"; callers must still be
    prepared for a slow read.
    """
    p = Path(path)
    try:
        st = os.stat(str(p))
    except FileNotFoundError:
        return Residency(str(p), exists=False, size_bytes=0, dataless=False, determinate=True)
    except OSError:
        # A stat that fails on a sync folder is itself a signal the client is unwell.
        return Residency(str(p), exists=False, size_bytes=0, dataless=False, determinate=False)

    size = int(getattr(st, "st_size", 0) or 0)

    if sys.platform == "darwin":
        flags = int(getattr(st, "st_flags", 0) or 0)
        return Residency(str(p), True, size, bool(flags & SF_DATALESS), determinate=True)

    if sys.platform == "win32":
        attrs = getattr(st, "st_file_attributes", None)
        if attrs is None:
            return Residency(str(p), True, size, False, determinate=False)
        mask = (
            FILE_ATTRIBUTE_OFFLINE
            | FILE_ATTRIBUTE_RECALL_ON_OPEN
            | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
        )
        return Residency(str(p), True, size, bool(int(attrs) & mask), determinate=True)

    # Linux and anything else: no placeholder concept we can read.
    return Residency(str(p), True, size, False, determinate=False)


def is_dataless(path: str | Path) -> bool:
    """True when the file exists but its bytes are known not to be local."""
    return residency(path).needs_hydration


def _run_bounded(fn, timeout_s: float, what: str):
    """
    Run ``fn`` on a worker thread and give up after ``timeout_s``.

    The worker is a daemon and is deliberately NOT killed on timeout — a thread
    blocked in a kernel read cannot be interrupted, and pretending otherwise
    would be worse than admitting it. It will finish or die with the process;
    the caller gets its timeout either way and the result is discarded.
    """
    box: "queue.Queue" = queue.Queue(maxsize=1)

    def _target():
        try:
            box.put(("ok", fn()))
        except BaseException as exc:  # noqa: BLE001 - relayed to the caller verbatim
            box.put(("err", exc))

    worker = threading.Thread(target=_target, name=f"foldersync-{what}", daemon=True)
    worker.start()
    try:
        status, payload = box.get(timeout=timeout_s)
    except queue.Empty:
        raise HydrationTimeout(
            f"{what} did not complete within {timeout_s:g}s. The file may still be "
            f"downloading from the cloud client; try again once it is available "
            f"offline."
        ) from None
    if status == "err":
        raise payload
    return payload


def read_bytes_bounded(path: str | Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> bytes:
    """
    Read a whole file, materialising it if needed, with a hard time budget.

    A plain ``open().read()`` is what triggers the download — Box: "When you open
    a file in your Box folder, Box Drive downloads the file to the mount point to
    open the file." So there is no special "materialise" call to make; the read
    *is* the materialisation. All this adds is the budget.
    """
    p = Path(path)

    def _read() -> bytes:
        with open(str(p), "rb") as fh:
            return fh.read()

    return _run_bounded(_read, timeout_s, f"read of {p.name}")


def sha256_bounded(path: str | Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """
    Stream a file's SHA-256, materialising it if needed, with a time budget.

    Streamed rather than read-then-hash so verifying a large archive does not
    need the whole thing in memory.
    """
    p = Path(path)

    def _hash() -> str:
        digest = hashlib.sha256()
        with open(str(p), "rb") as fh:
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    return _run_bounded(_hash, timeout_s, f"checksum of {p.name}")


def sha256_of_bytes(payload: bytes) -> str:
    """SHA-256 of an in-memory payload."""
    return hashlib.sha256(payload).hexdigest()


def hydration_advice(provider_pin_label: Optional[str], folder: str) -> str:
    """
    The sentence to show a user whose read timed out.

    Names the folder and the pinning setting, because "it didn't work" is not
    actionable and the pin is the only thing the user can actually do about it.
    """
    if provider_pin_label:
        return (
            f"WIMI could not read the sync folder in time: {folder}\n"
            f"The file is in the cloud but not on this device yet. Right-click the "
            f"folder in your file manager and choose \u201c{provider_pin_label}\u201d, "
            f"then try again."
        )
    return (
        f"WIMI could not read the sync folder in time: {folder}\n"
        f"The file may still be downloading. Try again once your cloud client "
        f"reports it as available offline."
    )
